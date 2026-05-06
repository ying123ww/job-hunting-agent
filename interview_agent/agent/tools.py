from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy.orm import Session

from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.memory2.retriever import SemanticMemoryRetriever
from interview_agent.planning.service import PlanService
from interview_agent.retrieval.service import EvidenceItem, RetrievalService


@dataclass(slots=True)
class ToolCall:
    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    status: str
    payload: dict[str, Any]
    preview: str


@dataclass(slots=True)
class ToolExecutionContext:
    session: Session
    user_id: str
    current_jd_id: str | None
    message: str


class AgentTool(Protocol):
    name: str

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        ...


class RecallMemoryTool:
    name = "recall_memory"

    def __init__(self, retriever: SemanticMemoryRetriever) -> None:
        self.retriever = retriever

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or ctx.message)
        hits = self.retriever.retrieve(ctx.session, user_id=ctx.user_id, query=query, limit=5)
        return ToolResult(
            tool_name=self.name,
            status="ok",
            payload={"hits": hits},
            preview=f"recalled {len(hits)} semantic memories",
        )


class SearchEvidenceTool:
    name = "search_evidence"

    def __init__(self, retrieval: RetrievalService) -> None:
        self.retrieval = retrieval

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        query = str(arguments.get("query") or ctx.message)
        dimension = arguments.get("dimension")
        hits = self.retrieval.build_evidence_bundle(
            ctx.session,
            user_id=ctx.user_id,
            query_text=query,
            source_types=["resume", "jd", "question", "gap_record"],
            dimension=str(dimension) if isinstance(dimension, str) and dimension else None,
            limit=4,
        )
        return ToolResult(
            tool_name=self.name,
            status="ok",
            payload={"hits": hits},
            preview=f"retrieved {len(hits)} evidence hits",
        )


class AnalyzeGapTool:
    name = "analyze_gaps"

    def __init__(self, diagnosis: GapAnalysisService) -> None:
        self.diagnosis = diagnosis

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        limit = int(arguments.get("limit", 3))
        overall_risk, gaps = self.diagnosis.analyze(
            ctx.session,
            user_id=ctx.user_id,
            jd_id=ctx.current_jd_id,
            limit=limit,
            persist=True,
        )
        return ToolResult(
            tool_name=self.name,
            status="ok",
            payload={"overall_risk": overall_risk, "gaps": gaps},
            preview=f"overall_risk={overall_risk}, gaps={len(gaps)}",
        )


class PlanTodayTool:
    name = "plan_today"

    def __init__(self, planning: PlanService) -> None:
        self.planning = planning

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        plan = self.planning.today(ctx.session, user_id=ctx.user_id, day=None)
        if plan is None or not plan.tasks:
            plan = self.planning.generate(
                ctx.session,
                user_id=ctx.user_id,
                jd_id=ctx.current_jd_id,
                gap_limit=int(arguments.get("gap_limit", 3)),
                day=None,
            )
        return ToolResult(
            tool_name=self.name,
            status="ok",
            payload={"plan": plan},
            preview=f"plan_id={plan.plan_id}, tasks={len(plan.tasks)}",
        )


class SyncTickTickTool:
    name = "sync_ticktick"

    def __init__(self, planning: PlanService) -> None:
        self.planning = planning

    def run(self, ctx: ToolExecutionContext, arguments: dict[str, Any]) -> ToolResult:
        tasks = self.planning.sync_ticktick(ctx.session, user_id=ctx.user_id, plan_id=arguments.get("plan_id"))
        return ToolResult(
            tool_name=self.name,
            status="ok",
            payload={"tasks": tasks},
            preview=f"synced {len(tasks)} tasks",
        )


class ToolRegistry:
    def __init__(self, tools: list[AgentTool]) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> AgentTool:
        return self._tools[name]

    def list_names(self) -> list[str]:
        return list(self._tools.keys())
