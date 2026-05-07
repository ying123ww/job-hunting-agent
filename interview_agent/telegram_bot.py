from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import httpx

from interview_agent.agent.runtime import AgentTurnRequest
from interview_agent.app.config import AppSettings
from interview_agent.core.container import AppContainer


logger = logging.getLogger(__name__)

_TELEGRAM_MESSAGE_LIMIT = 4000


class TelegramApiError(RuntimeError):
    pass


class TelegramPollingConflictError(TelegramApiError):
    pass


@dataclass(slots=True)
class TelegramMessage:
    chat_id: int
    text: str
    update_id: int
    first_name: str | None = None


def _split_message(text: str, limit: int = _TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= limit:
        return [stripped]

    parts: list[str] = []
    remaining = stripped
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        cut = remaining.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunk = remaining[:cut].strip()
        if chunk:
            parts.append(chunk)
        remaining = remaining[cut:].strip()
    return parts


class TelegramBotClient:
    def __init__(self, settings: AppSettings) -> None:
        if not settings.telegram_bot_token:
            raise ValueError("INTERVIEW_AGENT_TELEGRAM_BOT_TOKEN is required.")
        self._base_url = (
            f"{settings.telegram_api_base_url.rstrip('/')}/bot{settings.telegram_bot_token}"
        )
        self._client = httpx.AsyncClient(timeout=40.0)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_updates(
        self,
        *,
        offset: int | None,
        timeout_sec: int,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, Any] = {
            "timeout": timeout_sec,
            "allowed_updates": '["message"]',
        }
        if offset is not None:
            payload["offset"] = offset
        if limit is not None:
            payload["limit"] = limit
        response = await self._client.get(
            f"{self._base_url}/getUpdates",
            params=payload,
            timeout=timeout_sec + 10,
        )
        data = self._parse_json_response(response, action="getUpdates")
        return list(data.get("result") or [])

    async def get_latest_offset(self) -> int | None:
        updates = await self.get_updates(offset=-1, timeout_sec=0, limit=1)
        if not updates:
            return None
        update_id = updates[-1].get("update_id")
        if not isinstance(update_id, int):
            return None
        return update_id + 1

    async def send_message(self, *, chat_id: int, text: str) -> None:
        chunks = _split_message(text)
        for chunk in chunks:
            response = await self._client.post(
                f"{self._base_url}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                },
                timeout=30,
            )
            self._parse_json_response(response, action="sendMessage")

    def _parse_json_response(
        self,
        response: httpx.Response,
        *,
        action: str,
    ) -> dict[str, Any]:
        try:
            data = response.json()
        except ValueError as exc:
            response.raise_for_status()
            raise TelegramApiError(f"Telegram {action} returned invalid JSON.") from exc
        if response.status_code == 409:
            description = data.get("description") or "getUpdates conflict"
            raise TelegramPollingConflictError(str(description))
        if response.is_error:
            description = data.get("description") or response.text
            raise TelegramApiError(
                f"Telegram {action} failed with HTTP {response.status_code}: {description}"
            )
        if not data.get("ok"):
            description = data.get("description") or data
            raise TelegramApiError(f"Telegram {action} failed: {description}")
        return data


@contextmanager
def _session_scope(container: AppContainer) -> Iterator[Any]:
    with container.db.session_scope() as session:
        yield session


class TelegramBotService:
    def __init__(
        self,
        *,
        container: AppContainer,
        client: TelegramBotClient,
        settings: AppSettings,
    ) -> None:
        self.container = container
        self.client = client
        self.settings = settings

    async def handle_message(self, message: TelegramMessage) -> None:
        text = message.text.strip()
        if not text:
            return
        if text == "/start":
            name = message.first_name or "there"
            await self.client.send_message(
                chat_id=message.chat_id,
                text=(
                    f"Hi, {name}. "
                    "Send me an interview prep question and I will pass it to your agent."
                ),
            )
            return
        if text == "/help":
            await self.client.send_message(
                chat_id=message.chat_id,
                text="Send a text message to chat with the interview agent.",
            )
            return

        with _session_scope(self.container) as session:
            result = await self.container.agent_runtime.run_turn(
                session,
                AgentTurnRequest(
                    user_id=self._user_id(message.chat_id),
                    message=text,
                    jd_id=None,
                ),
            )
        await self.client.send_message(chat_id=message.chat_id, text=result.reply)

    def extract_message(self, update: dict[str, Any]) -> TelegramMessage | None:
        payload = update.get("message")
        if not isinstance(payload, dict):
            return None
        text = payload.get("text")
        chat = payload.get("chat")
        if not isinstance(text, str) or not isinstance(chat, dict):
            return None
        chat_id = chat.get("id")
        if not isinstance(chat_id, int):
            return None
        sender = payload.get("from")
        first_name = sender.get("first_name") if isinstance(sender, dict) else None
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            return None
        return TelegramMessage(
            chat_id=chat_id,
            text=text,
            update_id=update_id,
            first_name=first_name if isinstance(first_name, str) else None,
        )

    async def bootstrap_offset(self) -> int | None:
        if not self.settings.telegram_drop_pending_updates:
            return None
        offset = await self.client.get_latest_offset()
        if offset is not None:
            logger.info("Telegram bot dropped pending updates before polling. offset=%s", offset)
        return offset

    async def process_updates(
        self,
        updates: list[dict[str, Any]],
        *,
        current_offset: int | None,
    ) -> int | None:
        offset = current_offset
        for update in updates:
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                offset = update_id + 1
            message = self.extract_message(update)
            if message is None:
                continue
            try:
                await self.handle_message(message)
            except Exception:
                logger.exception("Failed to process Telegram update %s", message.update_id)
                await self._safe_notify_processing_failure(message.chat_id)
        return offset

    async def run_forever(self) -> None:
        logger.info("Telegram bot polling started.")
        offset = await self.bootstrap_offset()
        backoff_sec = 1.0
        while True:
            try:
                updates = await self.client.get_updates(
                    offset=offset,
                    timeout_sec=self.settings.telegram_poll_timeout_sec,
                )
                backoff_sec = 1.0
            except TelegramPollingConflictError as exc:
                logger.error(
                    "Telegram polling stopped due to getUpdates conflict: %s. "
                    "Make sure only one polling worker uses this bot token.",
                    exc,
                )
                return
            except (TelegramApiError, httpx.HTTPError) as exc:
                logger.warning(
                    "Telegram polling failed, retrying in %.1fs: %s",
                    backoff_sec,
                    exc,
                )
                await asyncio.sleep(backoff_sec)
                backoff_sec = min(
                    backoff_sec * 2,
                    float(self.settings.telegram_poll_max_backoff_sec),
                )
                continue
            offset = await self.process_updates(updates, current_offset=offset)

    async def aclose(self) -> None:
        try:
            await self.client.aclose()
        finally:
            event_bus = getattr(self.container, "agent_event_bus", None)
            if event_bus is not None:
                await event_bus.aclose()

    def run(self) -> None:
        asyncio.run(self._run_main())

    async def _run_main(self) -> None:
        try:
            await self.run_forever()
        finally:
            await self.aclose()

    async def _safe_notify_processing_failure(self, chat_id: int) -> None:
        try:
            await self.client.send_message(
                chat_id=chat_id,
                text="Agent processing failed. Check server logs and try again.",
            )
        except Exception:
            logger.exception("Failed to send Telegram error notification to chat %s", chat_id)

    def _user_id(self, chat_id: int) -> str:
        return f"tg_{chat_id}"
