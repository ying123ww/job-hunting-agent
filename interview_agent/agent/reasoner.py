from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from sqlalchemy.orm import Session

from interview_agent.agent.context import AgentContextBuilder
from interview_agent.agent.memory import MemorySnapshot
from interview_agent.app.config import AppSettings
from interview_agent.app.providers import OpenAICompatibleProvider
from interview_agent.diagnosis.service import GapAnalysisService
from interview_agent.ingestion.parser import infer_dimension, infer_topics
from interview_agent.planning.service import GeneratedPlan, PlanService
from interview_agent.retrieval.service import EvidenceItem, RetrievalService


Intent = Literal["plan", "diagnosis", "qa"]


@dataclass(slots=True)
class AgentTurnDecision:
    intent: Intent
    reply: str
    evidence: list[EvidenceItem] = field(default_factory=list)
    generated_plan_id: str | None = None
    top_gap_dimensions: list[str] = field(default_factory=list)
    pending_memory: str | None = None


class AgentReasoner:
    def __init__(
        self,
        *,
        settings: AppSettings,
        provider: OpenAICompatibleProvider,
        context_builder: AgentContextBuilder,
        retrieval: RetrievalService,
        diagnosis: GapAnalysisService,
        planning: PlanService,
    ) -> None:
        self.settings = settings
        self.provider = provider
        self.context_builder = context_builder
        self.retrieval = retrieval
        self.diagnosis = diagnosis
        self.planning = planning

    def detect_intent(self, message: str) -> Intent:
        lowered = message.lower()
        if any(token in lowered for token in ("今天", "today", "计划", "安排", "待办", "todo", "学什么")):
            return "plan"
        if any(token in lowered for token in ("短板", "gap", "诊断", "薄弱", "准备情况", "哪里不行")):
            return "diagnosis"
        return "qa"

    def run_turn(
        self,
        session: Session,
        *,
        user_id: str,
        message: str,
        current_jd_id: str | None,
        memory_snapshot: MemorySnapshot,
    ) -> AgentTurnDecision:
        intent = self.detect_intent(message)
        if intent == "plan":
            return self._plan_turn(
                session,
                user_id=user_id,
                current_jd_id=current_jd_id,
            )
        if intent == "diagnosis":
            return self._diagnosis_turn(
                session,
                user_id=user_id,
                current_jd_id=current_jd_id,
            )
        return self._qa_turn(
            session,
            user_id=user_id,
            message=message,
            current_jd_id=current_jd_id,
            memory_snapshot=memory_snapshot,
        )

    def _plan_turn(
        self,
        session: Session,
        *,
        user_id: str,
        current_jd_id: str | None,
    ) -> AgentTurnDecision:
        plan = self.planning.today(session, user_id=user_id, day=date.today())
        if plan is None or not plan.tasks:
            plan = self.planning.generate(
                session,
                user_id=user_id,
                jd_id=current_jd_id,
                gap_limit=3,
                day=date.today(),
            )
        reply = self._render_plan_reply(plan)
        dimensions = sorted({task.dimension for task in plan.tasks})
        return AgentTurnDecision(
            intent="plan",
            reply=reply,
            generated_plan_id=plan.plan_id,
            top_gap_dimensions=dimensions,
            pending_memory=f"- [requested_memory] 用户刚查看了今日计划，计划ID：{plan.plan_id}。",
        )

    def _diagnosis_turn(
        self,
        session: Session,
        *,
        user_id: str,
        current_jd_id: str | None,
    ) -> AgentTurnDecision:
        overall_risk, gaps = self.diagnosis.analyze(
            session,
            user_id=user_id,
            jd_id=current_jd_id,
            limit=3,
            persist=True,
        )
        evidence: list[EvidenceItem] = []
        for gap in gaps:
            evidence.extend(gap.evidence)
        dimensions = [gap.dimension for gap in gaps]
        reply = self._render_gap_reply(overall_risk, gaps)
        return AgentTurnDecision(
            intent="diagnosis",
            reply=reply,
            evidence=evidence[:4],
            top_gap_dimensions=dimensions,
            pending_memory=(
                f"- [requested_memory] 用户刚查看了短板诊断，当前重点维度：{', '.join(dimensions) or 'none'}。"
            ),
        )

    def _qa_turn(
        self,
        session: Session,
        *,
        user_id: str,
        message: str,
        current_jd_id: str | None,
        memory_snapshot: MemorySnapshot,
    ) -> AgentTurnDecision:
        topics = infer_topics(message)
        dimension = infer_dimension(message, topics)
        evidence = self.retrieval.build_evidence_bundle(
            session,
            user_id=user_id,
            query_text=message,
            source_types=["resume", "jd", "question", "gap_record"],
            dimension=dimension,
            limit=4,
        )
        reply = self._render_qa_reply(
            session,
            user_id=user_id,
            message=message,
            current_jd_id=current_jd_id,
            memory_snapshot=memory_snapshot,
            evidence=evidence,
        )
        return AgentTurnDecision(intent="qa", reply=reply, evidence=evidence)

    def _render_plan_reply(self, plan: GeneratedPlan) -> str:
        lines = [plan.summary]
        for task in plan.tasks[:4]:
            lines.append(
                f"- {task.title} | {task.duration_min}min | 优先级 {task.priority} | {task.due_at.strftime('%H:%M')}"
            )
        return "\n".join(lines)

    def _render_gap_reply(self, overall_risk: str, gaps) -> str:
        if not gaps:
            return "当前还没有足够的题目或诊断数据。先上传 JD、简历和一批题目作答，我们再做短板分析。"
        lines = [f"当前整体风险：{overall_risk}。优先修复这几个短板："]
        for gap in gaps[:3]:
            action = gap.repair_actions[0] if gap.repair_actions else "补一轮针对性练习"
            lines.append(f"- {gap.dimension} ({gap.severity})：{gap.why_it_matters} 建议先做：{action}")
        return "\n".join(lines)

    def _render_qa_reply(
        self,
        session: Session,
        *,
        user_id: str,
        message: str,
        current_jd_id: str | None,
        memory_snapshot: MemorySnapshot,
        evidence: list[EvidenceItem],
    ) -> str:
        if self.settings.llm_base_url and self.settings.llm_api_key:
            prompt_context = self.context_builder.build(
                session,
                user_id=user_id,
                current_jd_id=current_jd_id,
                memory_snapshot=memory_snapshot,
                evidence=evidence,
            )
            system_prompt = (
                "你是一个中文面试准备 agent。只基于给定 evidence 和 memory 回答，"
                "优先给结论，再补必要细节，不要编造未给出的经历。"
            )
            user_prompt = (
                f"{prompt_context.memory_block}\n\n"
                f"{prompt_context.jd_block}\n\n"
                f"{prompt_context.evidence_block}\n\n"
                f"用户问题：{message}"
            )
            return self.provider.chat(system_prompt=system_prompt, user_prompt=user_prompt)

        if not evidence:
            return (
                "我先没有在现有证据里找到足够直接的支撑。"
                "如果你愿意，可以先上传相关 JD、简历片段或题目作答，我再基于证据帮你回答。"
            )

        lines = [f"我先基于现有证据回答：{message}"]
        for item in evidence[:3]:
            lines.append(
                f"- 证据来自 {item.source_type}（doc={item.document_id}, chunk={item.chunk_id}）：{item.text[:160]}"
            )
        lines.append("如果你想，我下一步可以把这些证据整理成一版更像面试回答的话术。")
        return "\n".join(lines)
