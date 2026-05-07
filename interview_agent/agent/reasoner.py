from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy.orm import Session

from interview_agent.agent.context import AgentContextBuilder
from interview_agent.agent.memory import MemorySnapshot
from interview_agent.agent.tools import ToolCall, ToolResult
from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.memory2.injection_planner import build_memory_injection_block
from interview_agent.memory2.models import MemoryHit
from interview_agent.retrieval.service import EvidenceItem


Intent = Literal["plan", "diagnosis", "qa", "sync"]


@dataclass(slots=True)
class AgentTurnDecision:
    intent: Intent
    reply: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    generated_plan_id: str | None = None
    top_gap_dimensions: list[str] = field(default_factory=list)
    pending_memory: str | None = None
    tool_results: list[ToolResult] = field(default_factory=list)


class AgentReasoner:
    def __init__(
        self,
        *,
        settings: AppSettings,
        provider: OpenAICompatibleProvider,
        context_builder: AgentContextBuilder,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.context_builder = context_builder

    def detect_intent(self, message: str) -> Intent:
        lowered = message.lower()
        if "ticktick" in lowered and any(token in lowered for token in ("同步", "sync")):
            return "sync"
        if any(token in lowered for token in ("今天", "today", "计划", "安排", "待办", "todo", "学什么")):
            return "plan"
        if any(token in lowered for token in ("短板", "gap", "诊断", "薄弱", "准备情况", "哪里不行")):
            return "diagnosis"
        return "qa"

    def max_tool_iterations(self, intent: Intent) -> int:
        if intent == "qa":
            return 3
        return 4

    def plan_tool_calls(
        self,
        *,
        message: str,
        intent: Intent,
        current_jd_id: str | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        previous_results: list[ToolResult] | None = None,
    ) -> list[ToolCall]:
        results = previous_results or []
        executed = {result.tool_name for result in results}
        current_goal = memory_snapshot.working_memory.current_goal if memory_snapshot is not None else ""
        top_dimension = (
            memory_snapshot.working_memory.latest_top_gap_dimensions[0]
            if memory_snapshot is not None and memory_snapshot.working_memory.latest_top_gap_dimensions
            else None
        )
        recall_query = self._build_recall_query(message=message, current_goal=current_goal)

        if intent == "plan":
            if "recall_memory" not in executed:
                return [ToolCall(tool_name="recall_memory", arguments={"query": recall_query})]
            if "analyze_gaps" not in executed:
                return [ToolCall(tool_name="analyze_gaps", arguments={"limit": 3})]
            if "plan_today" not in executed:
                return [ToolCall(tool_name="plan_today", arguments={"gap_limit": 3})]
            return []

        if intent == "diagnosis":
            if "recall_memory" not in executed:
                return [ToolCall(tool_name="recall_memory", arguments={"query": recall_query})]
            if "analyze_gaps" not in executed:
                return [ToolCall(tool_name="analyze_gaps", arguments={"limit": 3})]
            gap_result = self._find_result(results, "analyze_gaps")
            if (
                gap_result is not None
                and gap_result.status == "ok"
                and not gap_result.payload.get("gaps")
                and "search_evidence" not in executed
            ):
                return [
                    ToolCall(
                        tool_name="search_evidence",
                        arguments={
                            "query": self._build_search_query(message=message, current_goal=current_goal),
                            "dimension": top_dimension or "",
                        },
                    )
                ]
            return []

        if intent == "sync":
            if "plan_today" not in executed:
                return [ToolCall(tool_name="plan_today", arguments={"gap_limit": 3})]
            if "sync_ticktick" not in executed:
                return [ToolCall(tool_name="sync_ticktick", arguments={})]
            return []

        if "recall_memory" not in executed:
            return [ToolCall(tool_name="recall_memory", arguments={"query": recall_query})]
        if "search_evidence" not in executed:
            recall_result = self._find_result(results, "recall_memory")
            recall_hits = list((recall_result.payload.get("hits") if recall_result else []) or [])
            query = self._build_search_query(message=message, current_goal=current_goal)
            if recall_hits:
                query = f"{message}\n{recall_hits[0].summary}"
            return [
                ToolCall(
                    tool_name="search_evidence",
                    arguments={
                        "query": query,
                        "dimension": top_dimension or "",
                        "source_types": self._qa_source_hints(message=message, current_jd_id=current_jd_id),
                    },
                )
            ]
        return []

    def reflect_tool_results(
        self,
        *,
        message: str,
        intent: Intent,
        current_jd_id: str | None = None,
        memory_snapshot: MemorySnapshot | None = None,
        tool_results: list[ToolResult],
    ) -> list[ToolCall]:
        return self.plan_tool_calls(
            message=message,
            intent=intent,
            current_jd_id=current_jd_id,
            memory_snapshot=memory_snapshot,
            previous_results=tool_results,
        )

    def finalize_turn(
        self,
        session: Session,
        *,
        user_id: str,
        message: str,
        current_jd_id: str | None,
        intent: Intent,
        memory_snapshot: MemorySnapshot,
        tool_results: list[ToolResult],
    ) -> AgentTurnDecision:
        if intent == "plan":
            return self._plan_decision(tool_results)
        if intent == "diagnosis":
            return self._diagnosis_decision(tool_results)
        if intent == "sync":
            return self._sync_decision(tool_results)
        return self._qa_decision(
            session,
            user_id=user_id,
            message=message,
            current_jd_id=current_jd_id,
            memory_snapshot=memory_snapshot,
            tool_results=tool_results,
        )

    def _plan_decision(self, tool_results: list[ToolResult]) -> AgentTurnDecision:
        plan_result = self._find_result(tool_results, "plan_today")
        if plan_result is None or plan_result.status != "ok" or "plan" not in plan_result.payload:
            return AgentTurnDecision(
                intent="plan",
                reply="我这次没能顺利生成今日计划。可以先重新跑一次诊断，或者检查一下计划生成链路。",
                tool_results=tool_results,
            )
        plan = plan_result.payload["plan"]
        lines = [plan.summary]
        for task in plan.tasks[:4]:
            lines.append(
                f"- {task.title} | {task.duration_min}min | 优先级 {task.priority} | {task.due_at.strftime('%H:%M')}"
            )
        dimensions = sorted({task.dimension for task in plan.tasks})
        return AgentTurnDecision(
            intent="plan",
            reply="\n".join(lines),
            generated_plan_id=plan.plan_id,
            top_gap_dimensions=dimensions,
            pending_memory=f"- [requested_memory] 用户刚查看了今日计划，计划ID：{plan.plan_id}。",
            tool_results=tool_results,
        )

    def _diagnosis_decision(self, tool_results: list[ToolResult]) -> AgentTurnDecision:
        result = self._find_result(tool_results, "analyze_gaps")
        if result is None or result.status != "ok":
            return AgentTurnDecision(
                intent="diagnosis",
                reply="我这次没能顺利完成短板诊断。可以先检查现有数据是否完整，再重新触发一次分析。",
                tool_results=tool_results,
            )
        overall_risk = result.payload["overall_risk"]
        gaps = result.payload["gaps"]
        if not gaps:
            reply = "当前还没有足够的题目或诊断数据。先上传 JD、简历和一批题目作答，我们再做短板分析。"
            return AgentTurnDecision(intent="diagnosis", reply=reply, tool_results=tool_results)

        evidence: list[EvidenceItem] = []
        lines = [f"当前整体风险：{overall_risk}。优先修复这几个短板："]
        dimensions: list[str] = []
        for gap in gaps[:3]:
            dimensions.append(gap.dimension)
            evidence.extend(gap.evidence)
            action = gap.repair_actions[0] if gap.repair_actions else "补一轮针对性练习"
            lines.append(f"- {gap.dimension} ({gap.severity})：{gap.why_it_matters} 建议先做：{action}")
        return AgentTurnDecision(
            intent="diagnosis",
            reply="\n".join(lines),
            evidence=evidence[:4],
            top_gap_dimensions=dimensions,
            pending_memory=(
                f"- [requested_memory] 用户刚查看了短板诊断，当前重点维度：{', '.join(dimensions) or 'none'}。"
            ),
            tool_results=tool_results,
        )

    def _sync_decision(self, tool_results: list[ToolResult]) -> AgentTurnDecision:
        sync_result = self._find_result(tool_results, "sync_ticktick")
        if sync_result is None or sync_result.status != "ok":
            return AgentTurnDecision(
                intent="sync",
                reply="这次 TickTick dry-run 同步没有成功完成。",
                tool_results=tool_results,
            )
        count = int(sync_result.payload.get("synced_count", len(sync_result.payload["tasks"])))
        mode = str(sync_result.payload.get("mode", "dry_run"))
        reply = f"已经完成一次 TickTick {mode} 同步，共处理 {count} 个任务。"
        return AgentTurnDecision(intent="sync", reply=reply, tool_results=tool_results)

    def _qa_decision(
        self,
        session: Session,
        *,
        user_id: str,
        message: str,
        current_jd_id: str | None,
        memory_snapshot: MemorySnapshot,
        tool_results: list[ToolResult],
    ) -> AgentTurnDecision:
        recall_hits: list[MemoryHit] = []
        evidence: list[EvidenceItem] = []
        for result in tool_results:
            if result.tool_name == "recall_memory":
                recall_hits = list(result.payload.get("hits", []))
            if result.tool_name == "search_evidence":
                evidence = list(result.payload.get("hits", []))

        if self.settings.llm_base_url and self.settings.llm_api_key:
            prompt_context = self.context_builder.build(
                session,
                user_id=user_id,
                current_jd_id=current_jd_id,
                memory_snapshot=memory_snapshot,
                evidence=evidence,
            )
            semantic_memory_block = build_memory_injection_block(recall_hits)
            system_prompt = (
                "你是一个中文面试准备 agent。只基于给定 evidence 和 memory 回答，"
                "优先给结论，再补必要细节，不要编造未给出的经历。"
            )
            user_prompt = (
                f"{prompt_context.memory_block}\n\n"
                f"{semantic_memory_block}\n\n"
                f"{prompt_context.jd_block}\n\n"
                f"{prompt_context.evidence_block}\n\n"
                f"用户问题：{message}"
            )
            reply = self.provider.chat(system_prompt=system_prompt, user_prompt=user_prompt)
            return AgentTurnDecision(intent="qa", reply=reply, evidence=evidence, tool_results=tool_results)

        if not evidence and not recall_hits:
            reply = (
                "我先没有在现有证据和语义记忆里找到足够直接的支撑。"
                "如果你愿意，可以先上传相关 JD、简历片段或题目作答，我再基于证据帮你回答。"
            )
            return AgentTurnDecision(intent="qa", reply=reply, tool_results=tool_results)

        lines = [f"我先基于现有证据回答：{message}"]
        if recall_hits:
            lines.append("相关语义记忆：")
            for hit in recall_hits[:2]:
                lines.append(f"- [{hit.memory_type}] {hit.summary} (score={hit.score:.2f})")
        if evidence:
            lines.append("直接证据：")
            for item in evidence[:3]:
                lines.append(
                    f"- {item.source_type}（doc={item.document_id}, chunk={item.chunk_id}）：{item.text[:160]}"
                )
        lines.append("如果你想，我下一步可以把这些证据整理成一版更像面试回答的话术。")
        return AgentTurnDecision(intent="qa", reply="\n".join(lines), evidence=evidence, tool_results=tool_results)

    def _find_result(self, tool_results: list[ToolResult], tool_name: str) -> ToolResult | None:
        for result in tool_results:
            if result.tool_name == tool_name:
                return result
        return None

    def _build_recall_query(self, *, message: str, current_goal: str) -> str:
        if current_goal and current_goal not in message:
            return f"{message}\n{current_goal}"
        return message

    def _build_search_query(self, *, message: str, current_goal: str) -> str:
        if current_goal and current_goal not in message:
            return f"{message}\n当前目标：{current_goal}"
        return message

    def _qa_source_hints(self, *, message: str, current_jd_id: str | None) -> list[str]:
        lowered = message.lower()
        if any(token in lowered for token in ("简历", "resume", "bullet", "项目")):
            return ["resume", "jd"] if current_jd_id else ["resume"]
        if any(token in lowered for token in ("岗位", "jd", "匹配")):
            return ["jd", "resume"]
        return ["resume", "jd", "question", "gap_record"]
