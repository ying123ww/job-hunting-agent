from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from interview_agent.actions.ticktick import TickTickClient, TickTickSyncTask
from interview_agent.diagnosis.service import DiagnosedGap, GapAnalysisService
from interview_agent.storage.repositories import InterviewRepository


@dataclass(slots=True)
class PlannedTask:
    task_id: str
    title: str
    dimension: str
    priority: int
    due_at: datetime
    duration_min: int
    status: str
    reason: str


@dataclass(slots=True)
class GeneratedPlan:
    plan_id: str
    jd_id: str | None
    summary: str
    tasks: list[PlannedTask]


@dataclass(slots=True)
class TickTickSyncSummary:
    mode: str
    synced_count: int
    tasks: list[PlannedTask]


class PlanService:
    def __init__(
        self,
        *,
        repository: InterviewRepository,
        diagnosis: GapAnalysisService,
        ticktick: TickTickClient,
    ) -> None:
        self.repository = repository
        self.diagnosis = diagnosis
        self.ticktick = ticktick

    def generate(
        self,
        session: Session,
        *,
        user_id: str,
        jd_id: str | None,
        gap_limit: int,
        day: date | None,
    ) -> GeneratedPlan:
        overall_risk, gaps = self.diagnosis.analyze(
            session,
            user_id=user_id,
            jd_id=jd_id,
            limit=gap_limit,
            persist=True,
        )
        target_day = day or date.today()
        summary = f"当前整体风险为 {overall_risk}，今天优先修复 {', '.join(gap.dimension for gap in gaps[:3]) or '基础准备'}。"
        plan = self.repository.create_plan(
            session,
            user_id=user_id,
            jd_id=jd_id,
            start_date=target_day,
            end_date=target_day,
            summary=summary,
        )
        tasks: list[PlannedTask] = []
        base_time = datetime.combine(target_day, time(hour=20, minute=0))
        cursor = base_time
        for gap in gaps:
            for title, duration, priority in self._tasks_for_gap(gap):
                task = self.repository.create_task(
                    session,
                    user_id=user_id,
                    plan_id=plan.id,
                    title=title,
                    dimension=gap.dimension,
                    priority=priority,
                    due_at=cursor,
                    duration_min=duration,
                    reason=gap.why_it_matters,
                )
                tasks.append(
                    PlannedTask(
                        task_id=task.id,
                        title=task.title,
                        dimension=task.dimension,
                        priority=task.priority,
                        due_at=task.due_at,
                        duration_min=task.duration_min,
                        status=task.status,
                        reason=task.reason,
                    )
                )
                cursor += timedelta(minutes=duration + 5)
        return GeneratedPlan(plan_id=plan.id, jd_id=jd_id, summary=summary, tasks=tasks)

    def today(self, session: Session, *, user_id: str, jd_id: str | None, day: date | None) -> GeneratedPlan | None:
        target_day = day or date.today()
        plan = self.repository.latest_plan(session, user_id=user_id, jd_id=jd_id)
        if plan is None:
            return None
        tasks = [
            item
            for item in self.repository.tasks_for_plan(session, plan_id=plan.id)
            if item.due_at.date() == target_day
        ]
        return GeneratedPlan(
            plan_id=plan.id,
            jd_id=plan.jd_id,
            summary=plan.summary,
            tasks=[
                PlannedTask(
                    task_id=item.id,
                    title=item.title,
                    dimension=item.dimension,
                    priority=item.priority,
                    due_at=item.due_at,
                    duration_min=item.duration_min,
                    status=item.status,
                    reason=item.reason,
                )
                for item in tasks
            ],
        )

    def sync_ticktick(self, session: Session, *, user_id: str, plan_id: str | None) -> TickTickSyncSummary:
        plan = self.repository.latest_plan(session, user_id=user_id) if plan_id is None else None
        target_plan_id = plan_id or (plan.id if plan else None)
        if target_plan_id is None:
            return TickTickSyncSummary(mode="dry_run", synced_count=0, tasks=[])
        tasks = self.repository.tasks_for_plan(session, plan_id=target_plan_id)
        sync_tasks = [self._to_sync_task(item) for item in tasks]
        sync_result = self.ticktick.sync(sync_tasks)
        synced_lookup = {item.local_task_id: item for item in sync_result.synced_tasks}
        for item in tasks:
            synced = synced_lookup.get(item.id)
            if synced is None:
                continue
            self.repository.update_task_sync_state(
                session,
                task_id=item.id,
                ticktick_id=synced.remote_task_id,
            )
        refreshed_tasks = self.repository.tasks_for_plan(session, plan_id=target_plan_id)
        status_map = self.ticktick.fetch_statuses([self._to_sync_task(item) for item in refreshed_tasks])
        for item in refreshed_tasks:
            status = status_map.get(item.id)
            if status is None:
                continue
            self.repository.update_task_sync_state(
                session,
                task_id=item.id,
                status=status,
            )
        planned = [
            PlannedTask(
                task_id=item.id,
                title=item.title,
                dimension=item.dimension,
                priority=item.priority,
                due_at=item.due_at,
                duration_min=item.duration_min,
                status=item.status,
                reason=item.reason,
            )
            for item in tasks
        ]
        return TickTickSyncSummary(
            mode=sync_result.mode,
            synced_count=sync_result.synced_count,
            tasks=planned,
        )

    def _tasks_for_gap(self, gap: DiagnosedGap) -> list[tuple[str, int, int]]:
        priority = 2 if gap.severity == "high" else 3 if gap.severity == "medium" else 4
        first_action = gap.repair_actions[0] if gap.repair_actions else "完成一轮针对性复盘"
        second_action = gap.repair_actions[1] if len(gap.repair_actions) > 1 else "录一遍口述答案"
        return [
            (first_action, 25, priority),
            (second_action, 10, priority),
        ]

    def _to_sync_task(self, task) -> TickTickSyncTask:
        return TickTickSyncTask(
            local_task_id=task.id,
            title=task.title,
            content=f"{task.reason}\n预计耗时：{task.duration_min} 分钟",
            due_at=task.due_at,
            priority=task.priority,
            ticktick_id=task.ticktick_id,
        )
