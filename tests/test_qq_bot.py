import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

from interview_agent.agent.runtime import AgentTurnResponse
from interview_agent.qq_bot import QQBotService


class FakeQQBotClient:
    def __init__(self) -> None:
        self.private_messages: list[tuple[str, str]] = []
        self.input_notifies: list[tuple[str, str]] = []
        self.closed = False

    async def send_private_text(self, *, openid: str, text: str) -> None:
        self.private_messages.append((openid, text))

    async def send_input_notify(self, *, openid: str, message_id: str) -> None:
        self.input_notifies.append((openid, message_id))

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


class FakeQuestionIngestion:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest_questions(
        self,
        session,
        *,
        user_id: str,
        text: str | None,
        content_base64,
        filename: str | None,
        metadata,
        source_company: str | None,
        source_role: str | None,
    ):
        self.calls.append(
            {
                "user_id": user_id,
                "text": text,
                "filename": filename,
                "metadata": metadata,
                "source_company": source_company,
                "source_role": source_role,
            }
        )
        return SimpleNamespace(
            processed_count=2,
            records=[{"question_id": "q1"}, {"question_id": "q2"}],
            skipped_count=1,
            inactive_count=0,
            fallback_used=False,
        )


def _settings(**overrides):
    base = {
        "qqbot_gateway_backoff_sec": 5,
        "qqbot_allowed_openids": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_qq_bot_handles_c2c_message() -> None:
    client = FakeQQBotClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=runtime,
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_1",
            "content": "今天我该准备什么？",
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is not None
    asyncio.run(service.handle_inbound(inbound))

    assert runtime.calls == [("qqbot_openid_123", "今天我该准备什么？", None)]
    assert client.input_notifies == [("openid_123", "msg_1")]
    assert client.private_messages == [("openid_123", "reply:今天我该准备什么？")]


def test_qq_bot_ignores_empty_content() -> None:
    client = FakeQQBotClient()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=FakeAgentRuntime(),
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_1",
            "content": "   ",
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is None


def test_qq_bot_blocks_openid_not_in_allowlist() -> None:
    client = FakeQQBotClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=runtime,
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(qqbot_allowed_openids="allowed_1"),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_1",
            "content": "hello",
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is not None
    asyncio.run(service.handle_inbound(inbound))

    assert runtime.calls == []
    assert client.private_messages == []
    assert client.input_notifies == []


def test_qq_bot_allows_openid_in_allowlist() -> None:
    client = FakeQQBotClient()
    runtime = FakeAgentRuntime()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=runtime,
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(qqbot_allowed_openids="openid_123,openid_999"),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_1",
            "content": "hello",
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is not None
    asyncio.run(service.handle_inbound(inbound))

    assert runtime.calls == [("qqbot_openid_123", "hello", None)]


def test_qq_bot_failure_notifies_user() -> None:
    client = FakeQQBotClient()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=FakeAgentRuntime(),
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(),
    )

    async def fake_handle(_inbound) -> None:
        raise RuntimeError("boom")

    service.handle_inbound = fake_handle  # type: ignore[method-assign]

    asyncio.run(
        service.handle_dispatch(
            "C2C_MESSAGE_CREATE",
            {
                "id": "msg_1",
                "content": "hello",
                "author": {"user_openid": "openid_123"},
            },
        )
    )

    assert client.private_messages == [
        ("openid_123", "Agent processing failed. Check server logs and try again.")
    ]


def test_qq_bot_ingests_question_bank_from_command() -> None:
    client = FakeQQBotClient()
    runtime = FakeAgentRuntime()
    ingestion = FakeQuestionIngestion()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=runtime,
        question_ingestion=ingestion,
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_2",
            "content": (
                "/ingest_questions source_key=mock-001 company=ByteDance role=Backend\n"
                "Redis 为什么单线程还这么快？\n"
                "我的答案：因为它是内存操作。"
            ),
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is not None
    asyncio.run(service.handle_inbound(inbound))

    assert runtime.calls == []
    assert ingestion.calls == [
        {
            "user_id": "qqbot_openid_123",
            "text": "Redis 为什么单线程还这么快？\n我的答案：因为它是内存操作。",
            "filename": "qqbot_questions.txt",
            "metadata": {"source_key": "mock-001"},
            "source_company": "ByteDance",
            "source_role": "Backend",
        }
    ]
    assert client.private_messages == [
        (
            "openid_123",
            "Question bank ingested successfully.\nprocessed=2\ndeduped=2\nskipped=1\ninactive=0\nfallback=False",
        )
    ]


def test_qq_bot_ingest_command_requires_body() -> None:
    client = FakeQQBotClient()
    container = SimpleNamespace(
        db=FakeDB(),
        agent_runtime=FakeAgentRuntime(),
        question_ingestion=FakeQuestionIngestion(),
    )
    service = QQBotService(
        container=container,
        client=client,
        settings=_settings(),
    )

    inbound = service.extract_inbound_message(
        {
            "id": "msg_3",
            "content": "/ingest_questions source_key=mock-001",
            "author": {"user_openid": "openid_123"},
        }
    )

    assert inbound is not None
    asyncio.run(service.handle_inbound(inbound))
    assert client.private_messages == [
        ("openid_123", "Question bank upload requires pasted content after /ingest_questions.")
    ]
