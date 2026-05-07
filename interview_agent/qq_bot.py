from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, cast

import httpx
import websockets

from interview_agent.agent.runtime import AgentTurnRequest
from interview_agent.app.config import AppSettings
from interview_agent.core.container import AppContainer


logger = logging.getLogger(__name__)

_QQBOT_C2C_INTENT = 1 << 25


class QQBotApiError(RuntimeError):
    pass


@dataclass(slots=True)
class _TokenCache:
    token: str
    expires_at: float


@dataclass(slots=True)
class QQInboundMessage:
    openid: str
    text: str
    message_id: str


@contextmanager
def _session_scope(container: AppContainer) -> Iterator[Any]:
    with container.db.session_scope() as session:
        yield session


class QQBotClient:
    def __init__(self, settings: AppSettings) -> None:
        if not settings.qqbot_app_id or not settings.qqbot_client_secret:
            raise ValueError(
                "INTERVIEW_AGENT_QQBOT_APP_ID and "
                "INTERVIEW_AGENT_QQBOT_CLIENT_SECRET are required."
            )
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=30.0)
        self._token: _TokenCache | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_access_token(self) -> str:
        now = time.time()
        if self._token is not None and now < self._token.expires_at - 300:
            return self._token.token
        response = await self._client.post(
            self.settings.qqbot_token_url,
            json={
                "appId": self.settings.qqbot_app_id,
                "clientSecret": self.settings.qqbot_client_secret,
            },
        )
        response.raise_for_status()
        data = response.json()
        token = str(data["access_token"])
        expires_in = int(data.get("expires_in") or 7200)
        self._token = _TokenCache(token=token, expires_at=now + expires_in)
        return token

    async def get_gateway(self) -> str:
        data = await self.api_request("GET", "/gateway")
        url = data.get("url")
        if not isinstance(url, str) or not url:
            raise QQBotApiError("QQBot gateway URL is missing.")
        return url

    async def send_private_text(
        self,
        *,
        openid: str,
        text: str,
    ) -> None:
        await self.api_request(
            "POST",
            f"/v2/users/{openid}/messages",
            body={
                "markdown": {"content": text},
                "msg_type": 2,
                "msg_seq": self._next_msg_seq(),
            },
        )

    async def send_input_notify(
        self,
        *,
        openid: str,
        message_id: str,
    ) -> None:
        try:
            await self.api_request(
                "POST",
                f"/v2/users/{openid}/messages",
                body={
                    "msg_type": 6,
                    "input_notify": {"input_type": 1, "input_second": 60},
                    "msg_seq": self._next_msg_seq(),
                    "msg_id": message_id,
                },
            )
        except Exception as exc:
            logger.debug("QQBot input notify skipped for openid=%s: %s", openid, exc)

    async def api_request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        token = await self.get_access_token()
        kwargs: dict[str, Any] = {
            "headers": {
                "Authorization": f"QQBot {token}",
                "Content-Type": "application/json",
            }
        }
        if body is not None:
            kwargs["json"] = body
        response = await self._client.request(
            method,
            f"{self.settings.qqbot_api_base_url.rstrip('/')}{path}",
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return {}
        data = response.json()
        return cast(dict[str, Any], data) if isinstance(data, dict) else {}

    def _next_msg_seq(self) -> int:
        return int(time.time() * 1000) % 65536


class QQBotService:
    def __init__(
        self,
        *,
        container: AppContainer,
        client: QQBotClient,
        settings: AppSettings,
    ) -> None:
        self.container = container
        self.client = client
        self.settings = settings
        self.allowed_openids = self._load_allowed_openids(settings)
        self._stopped = asyncio.Event()
        self._last_message_ids: dict[str, str] = {}

    async def run_forever(self) -> None:
        logger.info("QQBot gateway started.")
        while not self._stopped.is_set():
            try:
                gateway_url = await self.client.get_gateway()
                token = await self.client.get_access_token()
                await self._run_gateway(gateway_url, token)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "QQBot gateway failed, retrying in %ss: %s",
                    self.settings.qqbot_gateway_backoff_sec,
                    exc,
                )
                await asyncio.sleep(self.settings.qqbot_gateway_backoff_sec)

    async def aclose(self) -> None:
        self._stopped.set()
        try:
            await self.client.aclose()
        finally:
            event_bus = getattr(self.container, "agent_event_bus", None)
            if event_bus is not None:
                await event_bus.aclose()

    def run(self) -> None:
        asyncio.run(self._run_main())

    async def handle_inbound(self, message: QQInboundMessage) -> None:
        if not self.is_allowed_openid(message.openid):
            logger.warning("Ignored QQBot message from unauthorized openid=%s", message.openid)
            return
        text = message.text.strip()
        if not text:
            return
        self._last_message_ids[message.openid] = message.message_id
        await self.client.send_input_notify(openid=message.openid, message_id=message.message_id)

        if text == "/start":
            await self.client.send_private_text(
                openid=message.openid,
                text="Send a text message to chat with the interview agent.",
            )
            return
        if text == "/help":
            await self.client.send_private_text(
                openid=message.openid,
                text="Send a text message to chat with the interview agent.",
            )
            return

        with _session_scope(self.container) as session:
            result = await self.container.agent_runtime.run_turn(
                session,
                AgentTurnRequest(
                    user_id=self._user_id(message.openid),
                    message=text,
                    jd_id=None,
                ),
            )
        await self.client.send_private_text(openid=message.openid, text=result.reply)

    async def handle_dispatch(self, event_type: str, data: dict[str, Any]) -> None:
        if event_type != "C2C_MESSAGE_CREATE":
            return
        inbound = self.extract_inbound_message(data)
        if inbound is None:
            return
        try:
            await self.handle_inbound(inbound)
        except Exception:
            logger.exception("Failed to process QQBot message %s", inbound.message_id)
            await self._safe_notify_processing_failure(inbound.openid)

    def extract_inbound_message(self, data: dict[str, Any]) -> QQInboundMessage | None:
        author = data.get("author")
        author_dict = author if isinstance(author, dict) else {}
        openid = str(author_dict.get("user_openid") or data.get("user_openid") or "").strip()
        if not openid:
            return None
        text = str(data.get("content") or "").strip()
        if not text:
            return None
        message_id = str(data.get("id") or "").strip()
        if not message_id:
            return None
        return QQInboundMessage(
            openid=openid,
            text=text,
            message_id=message_id,
        )

    def is_allowed_openid(self, openid: str) -> bool:
        if not self.allowed_openids:
            return True
        return openid in self.allowed_openids

    def _load_allowed_openids(self, settings: AppSettings) -> set[str]:
        value = getattr(settings, "qqbot_allowed_openid_set", None)
        if value is not None:
            return set(value)
        raw = str(getattr(settings, "qqbot_allowed_openids", "") or "")
        allowed: set[str] = set()
        for item in raw.split(","):
            stripped = item.strip()
            if not stripped:
                continue
            allowed.add(stripped)
        return allowed

    async def _run_main(self) -> None:
        try:
            await self.run_forever()
        finally:
            await self.aclose()

    async def _run_gateway(self, url: str, token: str) -> None:
        last_seq: int | None = None
        heartbeat_task: asyncio.Task[None] | None = None
        async with websockets.connect(url) as websocket:
            async for raw in websocket:
                payload = json.loads(raw)
                op = payload.get("op")
                raw_data = payload.get("d")
                data = cast(dict[str, Any], raw_data) if isinstance(raw_data, dict) else {}
                event_type = str(payload.get("t") or "")
                if isinstance(payload.get("s"), int):
                    last_seq = int(payload["s"])

                if op == 10:
                    heartbeat_ms = int(data["heartbeat_interval"])
                    await websocket.send(
                        json.dumps(
                            {
                                "op": 2,
                                "d": {
                                    "token": f"QQBot {token}",
                                    "intents": _QQBOT_C2C_INTENT,
                                    "shard": [0, 1],
                                },
                            }
                        )
                    )
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat(websocket, heartbeat_ms, lambda: last_seq)
                    )
                elif op == 0:
                    await self.handle_dispatch(event_type, data)
                elif op == 7:
                    break
        if heartbeat_task is not None:
            heartbeat_task.cancel()

    async def _heartbeat(
        self,
        websocket: Any,
        heartbeat_ms: int,
        seq_fn: Any,
    ) -> None:
        while True:
            await asyncio.sleep(max(1, heartbeat_ms / 1000))
            await websocket.send(json.dumps({"op": 1, "d": seq_fn()}))

    async def _safe_notify_processing_failure(self, openid: str) -> None:
        try:
            await self.client.send_private_text(
                openid=openid,
                text="Agent processing failed. Check server logs and try again.",
            )
        except Exception:
            logger.exception("Failed to send QQBot error notification to openid=%s", openid)

    def _user_id(self, openid: str) -> str:
        return f"qqbot_{openid}"
