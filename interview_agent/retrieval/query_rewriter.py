from __future__ import annotations

import re

from interview_agent.agent.memory import MemorySnapshot


_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.@-]+|[\u4e00-\u9fff]{2,}")
_STOPWORDS = {
    "帮我",
    "看看",
    "一下",
    "这个",
    "怎么",
    "今天",
    "什么",
    "以及",
    "需要",
    "应该",
    "准备",
}


def rewrite_query(
    *,
    query_text: str,
    intent: str | None,
    dimension: str | None,
    memory_snapshot: MemorySnapshot | None,
    max_variants: int = 3,
) -> list[str]:
    variants: list[str] = [query_text.strip()]
    keyword_lane = _keyword_lane(query_text)
    if keyword_lane and keyword_lane not in variants:
        variants.append(keyword_lane)

    focused_lane = _focus_lane(
        query_text=query_text,
        intent=intent,
        dimension=dimension,
        memory_snapshot=memory_snapshot,
    )
    if focused_lane and focused_lane not in variants:
        variants.append(focused_lane)

    return [item for item in variants if item][:max_variants]


def _keyword_lane(query_text: str) -> str:
    tokens = [token for token in _TOKEN_RE.findall(query_text) if token.lower() not in _STOPWORDS]
    return " ".join(tokens[:8]).strip()


def _focus_lane(
    *,
    query_text: str,
    intent: str | None,
    dimension: str | None,
    memory_snapshot: MemorySnapshot | None,
) -> str:
    parts = [query_text.strip()]
    if dimension and dimension not in query_text:
        parts.append(f"dimension:{dimension}")
    if intent and intent not in query_text:
        parts.append(f"intent:{intent}")
    if memory_snapshot is not None:
        working = memory_snapshot.working_memory
        if working.current_goal and working.current_goal not in query_text:
            parts.append(f"goal:{working.current_goal}")
        if working.current_focus and working.current_focus not in query_text:
            parts.append(f"focus:{working.current_focus}")
    return "\n".join(part for part in parts if part).strip()
