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


def test_dida365_client_builds_task_payload() -> None:
    client = Dida365TickTickClient(
        config=Dida365Config(
            access_token="token",
            project_id="proj_interview",
            project_name="Interview Copilot Agent",
            region="china",
        )
    )
    payload = client._build_task_payload(  # type: ignore[attr-defined]
        task=TickTickSyncTask(
            local_task_id="task_local_1",
            title="复习 Redis",
            content="补齐 epoll 机制",
            due_at=datetime(2026, 5, 7, 21, 0),
            priority=3,
        ),
        project_id="proj_interview",
    )

    assert payload["projectId"] == "proj_interview"
    assert payload["title"] == "复习 Redis"
    assert payload["content"] == "补齐 epoll 机制"
    assert payload["priority"] == 3
    assert payload["dueDate"] == "2026-05-07T21:00:00"


def test_dida365_client_sync_and_fetch_statuses_with_http_api() -> None:
    seen_requests: list[tuple[str, str, object | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = None
        if request.content:
            payload = request.read().decode("utf-8")
        seen_requests.append((request.method, request.url.path, payload))
        if request.method == "GET" and request.url.path == "/open/v1/project":
            return httpx.Response(200, json=[{"id": "proj_interview", "name": "Interview Copilot Agent"}])
        if request.method == "POST" and request.url.path == "/open/v1/task":
            return httpx.Response(200, json={"id": "remote_created"})
        if request.method == "POST" and request.url.path == "/open/v1/task/remote_existing":
            return httpx.Response(200, text="")
        if request.method == "GET" and request.url.path == "/open/v1/project/proj_interview/data":
            return httpx.Response(200, json={"tasks": [{"id": "remote_existing", "title": "pending task", "status": 0}]})
        if request.method == "POST" and request.url.path == "/open/v1/task/completed":
            return httpx.Response(200, json=[{"id": "remote_created", "title": "done task", "status": 2}])
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    client = Dida365TickTickClient(
        config=Dida365Config(
            access_token="token",
            project_id="",
            project_name="Interview Copilot Agent",
            region="china",
        )
    )
    client._client = httpx.Client(  # type: ignore[attr-defined]
        transport=httpx.MockTransport(handler),
        base_url=client.config.api_base_url,
        headers={"Authorization": "Bearer token"},
    )

    summary = client.sync(
        [
            TickTickSyncTask(
                local_task_id="local_1",
                title="新任务",
                content="创建",
                due_at=datetime(2026, 5, 7, 21, 0),
                priority=3,
            ),
            TickTickSyncTask(
                local_task_id="local_2",
                title="旧任务",
                content="更新",
                due_at=datetime(2026, 5, 7, 22, 0),
                priority=2,
                ticktick_id="remote_existing",
            ),
        ]
    )
    statuses = client.fetch_statuses(
        [
            TickTickSyncTask(
                local_task_id="local_1",
                title="新任务",
                content="创建",
                due_at=datetime(2026, 5, 7, 21, 0),
                priority=3,
                ticktick_id="remote_created",
            ),
            TickTickSyncTask(
                local_task_id="local_2",
                title="旧任务",
                content="更新",
                due_at=datetime(2026, 5, 7, 22, 0),
                priority=2,
                ticktick_id="remote_existing",
            ),
        ]
    )

    assert summary.synced_count == 2
    assert [item.remote_task_id for item in summary.synced_tasks] == ["remote_created", "remote_existing"]
    assert statuses == {"local_1": "completed", "local_2": "pending"}
    assert ("GET", "/open/v1/project", None) in seen_requests


def test_plan_service_sync_updates_local_ticktick_ids(tmp_path) -> None:
    class FakeTickTickClient:
        def __init__(self) -> None:
            self.seen: list[TickTickSyncTask] = []
            self.status_seen: list[TickTickSyncTask] = []

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

        def fetch_statuses(self, tasks):
            self.status_seen = list(tasks)
            return {
                tasks[0].local_task_id: "completed",
                tasks[1].local_task_id: "pending",
            }

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
    assert [task.local_task_id for task in fake_ticktick.status_seen] == [first.id, second.id]
    assert [task.ticktick_id for task in refreshed] == ["remote_1", "remote_2"]
    assert [task.status for task in refreshed] == ["completed", "pending"]
