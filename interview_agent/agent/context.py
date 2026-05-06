from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from interview_agent.agent.memory import MemorySnapshot
from interview_agent.retrieval.service import EvidenceItem
from interview_agent.storage.repositories import InterviewRepository


@dataclass(slots=True)
class AgentPromptContext:
    memory_block: str
    jd_block: str
    evidence_block: str


@dataclass(slots=True)
class StructuredProfileSnapshot:
    target_roles: list[str]
    target_companies: list[str]
    weak_points: list[str]
    ability_scores: dict[str, float]
    learning_preference: dict[str, object]
    latest_overall_risk: str


class AgentContextBuilder:
    def __init__(self, repository: InterviewRepository) -> None:
        self.repository = repository

    def build(
        self,
        session: Session,
        *,
        user_id: str,
        current_jd_id: str | None,
        memory_snapshot: MemorySnapshot,
        evidence: list[EvidenceItem],
    ) -> AgentPromptContext:
        jd = self.repository.latest_target_jd(session, user_id=user_id, jd_id=current_jd_id)
        profile = self._build_profile(session, user_id=user_id)
        jd_lines: list[str] = []
        if jd is not None:
            jd_lines.append("## Current JD")
            requirements = jd.structured_requirements[:5]
            for item in requirements:
                jd_lines.append(f"- {item.get('text', '')}")

        memory_lines = ["## Long-term Memory", memory_snapshot.long_term.strip() or "- empty"]
        memory_lines.extend(
            [
                "",
                "## Structured Profile",
                self._format_profile(profile),
                "",
                "## Self Model",
                memory_snapshot.self_model.strip() or "- empty",
                "",
                "## Recent Context",
                memory_snapshot.recent_context.strip() or "- empty",
                "",
                "## Working Memory",
                self._format_working_memory(memory_snapshot),
                "",
                "## NOW",
                memory_snapshot.now_text.strip() or "- empty",
            ]
        )

        evidence_lines = ["## Evidence"]
        if evidence:
            for item in evidence[:4]:
                evidence_lines.append(
                    f"- ({item.source_type}) [doc={item.document_id} chunk={item.chunk_id}] {item.text[:220]}"
                )
        else:
            evidence_lines.append("- no matched evidence")

        return AgentPromptContext(
            memory_block="\n".join(memory_lines).strip(),
            jd_block="\n".join(jd_lines).strip(),
            evidence_block="\n".join(evidence_lines).strip(),
        )

    def _build_profile(self, session: Session, *, user_id: str) -> StructuredProfileSnapshot:
        profile = self.repository.get_user_profile(session, user_id=user_id)
        ability_scores = {
            item.dimension: item.score for item in self.repository.list_ability_scores(session, user_id=user_id)
        }
        if profile is None:
            return StructuredProfileSnapshot(
                target_roles=[],
                target_companies=[],
                weak_points=[],
                ability_scores=ability_scores,
                learning_preference={},
                latest_overall_risk="unknown",
            )
        return StructuredProfileSnapshot(
            target_roles=list(profile.target_roles),
            target_companies=list(profile.target_companies),
            weak_points=list(profile.weak_points),
            ability_scores=ability_scores,
            learning_preference=dict(profile.learning_preference),
            latest_overall_risk=profile.latest_overall_risk or "unknown",
        )

    def _format_profile(self, profile: StructuredProfileSnapshot) -> str:
        lines = [
            f"- target_roles: {', '.join(profile.target_roles) or 'none'}",
            f"- target_companies: {', '.join(profile.target_companies) or 'none'}",
            f"- weak_points: {', '.join(profile.weak_points[:5]) or 'none'}",
            f"- latest_overall_risk: {profile.latest_overall_risk}",
        ]
        if profile.ability_scores:
            rendered = ", ".join(
                f"{dimension}={score:.2f}" for dimension, score in list(profile.ability_scores.items())[:6]
            )
            lines.append(f"- ability_scores: {rendered}")
        if profile.learning_preference:
            rendered_pref = ", ".join(f"{key}={value}" for key, value in profile.learning_preference.items())
            lines.append(f"- learning_preference: {rendered_pref}")
        return "\n".join(lines)

    def _format_working_memory(self, memory_snapshot: MemorySnapshot) -> str:
        state = memory_snapshot.working_memory
        return "\n".join(
            [
                f"- current_goal: {state.current_goal or 'none'}",
                f"- current_jd_id: {state.current_jd_id or 'none'}",
                f"- current_plan_id: {state.current_plan_id or 'none'}",
                f"- current_mock_session: {state.current_mock_session or 'none'}",
                f"- latest_top_gap_dimensions: {', '.join(state.latest_top_gap_dimensions) or 'none'}",
                f"- temporary_context: {' | '.join(state.temporary_context) or 'none'}",
            ]
        )
