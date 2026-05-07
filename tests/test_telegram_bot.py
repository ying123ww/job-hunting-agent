import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from interview_agent.agent.runtime import AgentTurnResponse
from interview_agent.telegram_bot import TelegramBotService, _split_message


class FakeTelegramClient:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str]] = []
        self.latest_offset: int | None = None
        self.closed = False

    async def send_message(self, *, chat_id: int, text: str) -> None:
        self.messages.append((chat_id, text))

    async def get_latest_offset(self) -> int | None:
        return self.latest_offset

    async def aclose(self) -> None:
        self.closed = True


class FakeAgentRuntime:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    async def run_turn(self, session, request):
        self.calls.append((request.user_id, request.message, request.jd_id))
        return AgentTurnResponse(
            turn_id="turn_1",
            intent="qa",
            reply=f"reply:{request.message}",
            current_jd_id=None,
            generated_plan_id=None,
            evidence=[],
        )


class FakeDB:
    @contextmanager
    def session_scope(self):
        yield object()


def test_telegram_bot_handles_text_message() -> None:
    client = FakeTelegramClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(db=FakeDB(), agent_runtime=runtime)
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="",
        ),
    )

    message = service.extract_message(
        {
            "update_id": 123,
            "message": {
                "text": "今天我该准备什么？",
                "chat": {"id": 456},
                "from": {"first_name": "Ying"},
            },
        }
    )

    assert message is not None
    asyncio.run(service.handle_message(message))

    assert runtime.calls == [("tg_456", "今天我该准备什么？", None)]
    assert client.messages == [(456, "reply:今天我该准备什么？")]


def test_telegram_bot_ignores_non_text_message() -> None:
    client = FakeTelegramClient()
    container = SimpleNamespace(db=FakeDB(), agent_runtime=FakeAgentRuntime())
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="",
        ),
    )

    message = service.extract_message(
        {
            "update_id": 123,
            "message": {
                "photo": [{"file_id": "abc"}],
                "chat": {"id": 456},
            },
        }
    )

    assert message is None


def test_telegram_bot_bootstrap_offset_drops_pending_updates() -> None:
    client = FakeTelegramClient()
    client.latest_offset = 42
    container = SimpleNamespace(db=FakeDB(), agent_runtime=FakeAgentRuntime())
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="",
        ),
    )

    offset = asyncio.run(service.bootstrap_offset())

    assert offset == 42


def test_process_updates_continues_after_single_message_failure() -> None:
    client = FakeTelegramClient()
    container = SimpleNamespace(db=FakeDB(), agent_runtime=FakeAgentRuntime())
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="",
        ),
    )

    seen: list[int] = []

    async def fake_handle(message) -> None:
        seen.append(message.update_id)
        if message.update_id == 1:
            raise RuntimeError("boom")

    service.handle_message = fake_handle  # type: ignore[method-assign]

    offset = asyncio.run(
        service.process_updates(
            [
                {"update_id": 1, "message": {"text": "a", "chat": {"id": 10}}},
                {"update_id": 2, "message": {"text": "b", "chat": {"id": 10}}},
            ],
            current_offset=None,
        )
    )

    assert seen == [1, 2]
    assert offset == 3
    assert client.messages == [(10, "Agent processing failed. Check server logs and try again.")]


def test_split_message_breaks_long_text() -> None:
    parts = _split_message(("a" * 2500) + "\n\n" + ("b" * 2500), limit=3000)

    assert len(parts) == 2
    assert parts[0] == "a" * 2500
    assert parts[1] == "b" * 2500


def test_telegram_bot_blocks_chat_not_in_allowlist() -> None:
    client = FakeTelegramClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(db=FakeDB(), agent_runtime=runtime)
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="999",
        ),
    )

    message = service.extract_message(
        {
            "update_id": 123,
            "message": {
                "text": "今天我该准备什么？",
                "chat": {"id": 456},
            },
        }
    )

    assert message is not None
    asyncio.run(service.handle_message(message))

    assert runtime.calls == []
    assert client.messages == []


def test_telegram_bot_allows_chat_in_allowlist() -> None:
    client = FakeTelegramClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(db=FakeDB(), agent_runtime=runtime)
    service = TelegramBotService(
        container=container,
        client=client,
        settings=SimpleNamespace(
            telegram_poll_timeout_sec=30,
            telegram_poll_max_backoff_sec=30,
            telegram_drop_pending_updates=True,
            telegram_allowed_chat_ids="456,999",
        ),
    )

    message = service.extract_message(
        {
            "update_id": 123,
            "message": {
                "text": "今天我该准备什么？",
                "chat": {"id": 456},
            },
        }
    )

    assert message is not None
    asyncio.run(service.handle_message(message))

    assert runtime.calls == [("tg_456", "今天我该准备什么？", None)]
