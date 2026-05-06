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
                "## Self Model",
                memory_snapshot.self_model.strip() or "- empty",
                "",
                "## Recent Context",
                memory_snapshot.recent_context.strip() or "- empty",
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
