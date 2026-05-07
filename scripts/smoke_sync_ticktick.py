from __future__ import annotations

from datetime import date, datetime, time

from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer


def main() -> None:
    settings = get_settings()
    container = AppContainer.build(settings)
    user_id = settings.default_user_id

    with container.db.session_scope() as session:
        plan = container.repository.latest_plan(session, user_id=user_id)
        if plan is None:
            today = date.today()
            plan = container.repository.create_plan(
                session,
                user_id=user_id,
                jd_id=None,
                start_date=today,
                end_date=today,
                summary="Smoke sync plan",
            )
            container.repository.create_task(
                session,
                user_id=user_id,
                plan_id=plan.id,
                title="Smoke test: sync one task to Dida365",
                dimension="execution",
                priority=4,
                due_at=datetime.combine(today, time(hour=21, minute=0)),
                duration_min=5,
                reason="Created by scripts/smoke_sync_ticktick.py to verify MCP sync.",
            )

        summary = container.planning.sync_ticktick(session, user_id=user_id, plan_id=plan.id)

    print(f"mode={summary.mode}")
    print(f"synced={summary.synced_count}")
    for task in summary.tasks:
        print(f"{task.task_id} | {task.title} | {task.due_at.isoformat()} | status={task.status}")


if __name__ == "__main__":
    main()
