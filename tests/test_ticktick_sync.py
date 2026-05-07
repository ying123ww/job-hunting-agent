from datetime import date, datetime

import httpx

from interview_agent.actions.ticktick import (
    Dida365Config,
    Dida365TickTickClient,
    TickTickSyncResult,
    TickTickSyncTask,
    TickTickSyncedTask,
)
from interview_agent.planning.service import PlanService
from interview_agent.storage.database import DatabaseManager
from interview_agent.storage.repositories import InterviewRepository


def test_dida365_client_creates_and_updates_tasks() -> None:
    calls: list[tuple[str, str, object | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = None
        if request.content:
            payload = request.read().decode("utf-8")
        calls.append((request.method, request.url.path, payload))
        if request.method == "GET" and request.url.path == "/open/v1/project":
            return httpx.Response(200, json=[{"id": "proj_interview", "name": "Interview Copilot Agent"}])
        if request.method == "POST" and request.url.path == "/open/v1/task":
            return httpx.Response(200, json={"id": "remote_created"})
        if request.method == "POST" and request.url.path == "/open/v1/task/remote_existing":
            return httpx.Response(200, json={"id": "remote_existing"})
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    transport = httpx.MockTransport(handler)
    client = Dida365TickTickClient(
        config=Dida365Config(
            access_token="token",
            project_id="",
            project_name="Interview Copilot Agent",
            base_url="https://api.dida365.com/open/v1",
        ),
        client_factory=lambda: httpx.Client(
            transport=transport,
            base_url="https://api.dida365.com/open/v1",
            headers={"Authorization": "Bearer token"},
        ),
    )

    result = client.sync(
        [
            TickTickSyncTask(
                local_task_id="task_local_1",
                title="复习 Redis",
                content="补齐 epoll 机制",
                due_at=datetime(2026, 5, 7, 21, 0),
                priority=3,
            ),
            TickTickSyncTask(
                local_task_id="task_local_2",
                title="重做系统设计",
                content="补 QPS 估算",
                due_at=datetime(2026, 5, 7, 22, 0),
                priority=2,
                ticktick_id="remote_existing",
            ),
        ]
    )

    assert result.mode == "live"
    assert result.synced_count == 2
    assert [item.remote_task_id for item in result.synced_tasks] == ["remote_created", "remote_existing"]
    assert [item[:2] for item in calls] == [
        ("GET", "/open/v1/project"),
        ("POST", "/open/v1/task"),
        ("POST", "/open/v1/task/remote_existing"),
    ]


def test_plan_service_sync_updates_local_ticktick_ids(tmp_path) -> None:
    class FakeTickTickClient:
        def __init__(self) -> None:
            self.seen: list[TickTickSyncTask] = []

        def sync(self, tasks):
            self.seen = list(tasks)
            return TickTickSyncResult(
                mode="live",
                synced_count=len(self.seen),
                synced_tasks=[
                    TickTickSyncedTask(
                        local_task_id=task.local_task_id,
                        remote_task_id=f"remote_{index}",
                        project_id="proj_interview",
                        mode="live",
                    )
                    for index, task in enumerate(self.seen, start=1)
                ],
            )

    db = DatabaseManager(f"sqlite:///{tmp_path / 'app.db'}")
    db.create_all()
    repository = InterviewRepository()
    fake_ticktick = FakeTickTickClient()
    planning = PlanService(
        repository=repository,
        diagnosis=None,  # type: ignore[arg-type]
        ticktick=fake_ticktick,
    )

    with db.session_scope() as session:
        repository.ensure_user(session, "u_demo")
        plan = repository.create_plan(
            session,
            user_id="u_demo",
            jd_id=None,
            start_date=date(2026, 5, 7),
            end_date=date(2026, 5, 7),
            summary="today",
        )
        first = repository.create_task(
            session,
            user_id="u_demo",
            plan_id=plan.id,
            title="复习 Redis",
            dimension="backend_basic",
            priority=3,
            due_at=datetime(2026, 5, 7, 21, 0),
            duration_min=25,
            reason="数据库基础要补强",
        )
        second = repository.create_task(
            session,
            user_id="u_demo",
            plan_id=plan.id,
            title="口述系统设计",
            dimension="system_design",
            priority=2,
            due_at=datetime(2026, 5, 7, 22, 0),
            duration_min=10,
            reason="系统设计表达不稳定",
        )

        summary = planning.sync_ticktick(session, user_id="u_demo", plan_id=plan.id)

        refreshed = repository.tasks_for_plan(session, plan_id=plan.id)

    assert summary.mode == "live"
    assert summary.synced_count == 2
    assert [task.local_task_id for task in fake_ticktick.seen] == [first.id, second.id]
    assert [task.ticktick_id for task in refreshed] == ["remote_1", "remote_2"]
