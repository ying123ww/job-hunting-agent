from __future__ import annotations

from interview_agent.memory2.models import MemoryHit


def build_memory_injection_block(hits: list[MemoryHit], *, max_chars: int = 900) -> str:
    if not hits:
        return ""
    lines = ["## Semantic Memory"]
    current = len(lines[0])
    for hit in hits:
        line = (
            f"- [{hit.memory_type}] {hit.summary} "
            f"(score={hit.score:.2f}, reinforcement={hit.reinforcement})"
        )
        if current + len(line) > max_chars:
            break
        lines.append(line)
        current += len(line)
    return "\n".join(lines)
