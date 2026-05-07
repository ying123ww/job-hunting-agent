from datetime import date, datetime

from interview_agent.actions.ticktick import (
    Dida365McpConfig,
    Dida365McpTickTickClient,
    TickTickSyncResult,
    TickTickSyncTask,
    TickTickSyncedTask,
)
from interview_agent.planning.service import PlanService
from interview_agent.storage.database import DatabaseManager
from interview_agent.storage.repositories import InterviewRepository


def test_dida365_mcp_client_builds_arguments_from_tool_schema() -> None:
    client = Dida365McpTickTickClient(
        config=Dida365McpConfig(
            command="uvx",
            args=["dida365-agent-mcp"],
            env={},
            project_id="proj_interview",
            project_name="Interview Copilot Agent",
        )
    )
    create_tool = type(
        "Tool",
        (),
        {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "projectId": {},
                    "title": {},
                    "content": {},
                    "dueDate": {},
                    "priority": {},
                },
            }
        },
    )()
    update_tool = type(
        "Tool",
        (),
        {
            "inputSchema": {
                "type": "object",
                "properties": {
                    "taskId": {},
                    "projectId": {},
                    "title": {},
                    "content": {},
                    "dueDate": {},
                    "priority": {},
                },
            }
        },
    )()

    create_args = client._build_task_arguments(  # type: ignore[attr-defined]
        tool=create_tool,
        task=TickTickSyncTask(
            local_task_id="task_local_1",
            title="复习 Redis",
            content="补齐 epoll 机制",
            due_at=datetime(2026, 5, 7, 21, 0),
            priority=3,
        ),
        project_id="proj_interview",
        for_update=False,
    )
    update_args = client._build_task_arguments(  # type: ignore[attr-defined]
        tool=update_tool,
        task=TickTickSyncTask(
            local_task_id="task_local_2",
            title="重做系统设计",
            content="补 QPS 估算",
            due_at=datetime(2026, 5, 7, 22, 0),
            priority=2,
            ticktick_id="remote_existing",
        ),
        project_id="proj_interview",
        for_update=True,
    )

    assert create_args["projectId"] == "proj_interview"
    assert create_args["title"] == "复习 Redis"
    assert create_args["content"] == "补齐 epoll 机制"
    assert create_args["priority"] == 3
    assert "dueDate" in create_args
    assert update_args["taskId"] == "remote_existing"
    assert update_args["projectId"] == "proj_interview"


def test_dida365_mcp_client_extracts_remote_task_id() -> None:
    client = Dida365McpTickTickClient(
        config=Dida365McpConfig(
            command="uvx",
            args=["dida365-agent-mcp"],
            env={},
            project_id="proj_interview",
            project_name="Interview Copilot Agent",
        )
    )
    result = type(
        "CallResult",
        (),
        {
            "structuredContent": {
                "task": {
                    "id": "remote_created",
                }
            }
        },
    )()

    remote_task_id = client._extract_remote_task_id(result, fallback="")  # type: ignore[attr-defined]

    assert remote_task_id == "remote_created"


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
