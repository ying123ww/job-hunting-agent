from __future__ import annotations

import re
from collections.abc import Iterable


_TOKEN_RE = re.compile(r"[A-Za-z0-9_+#.@-]+|[\u4e00-\u9fff]{2,}")


def rerank_score(
    *,
    base_score: float,
    metadata: dict[str, object],
    text: str,
    query_variants: Iterable[str],
    dimension: str | None,
    strategy: str,
) -> float:
    score = base_score
    meta_dimension = str(metadata.get("dimension", "") or "")
    source_type = str(metadata.get("source_type", "") or "")

    if dimension and meta_dimension == dimension:
        score += 0.18

    if strategy in {"planning", "diagnosis"} and source_type == "gap_record":
        score += 0.12
    elif strategy == "resume_edit" and source_type in {"resume", "jd"}:
        score += 0.12
    elif source_type in {"resume", "jd"}:
        score += 0.05

    lexical_overlap = max((_overlap_ratio(text, query) for query in query_variants), default=0.0)
    score += min(lexical_overlap * 0.25, 0.2)
    return round(score, 4)


def _overlap_ratio(text: str, query: str) -> float:
    text_tokens = set(_TOKEN_RE.findall(text.lower()))
    query_tokens = set(_TOKEN_RE.findall(query.lower()))
    if not text_tokens or not query_tokens:
        return 0.0
    overlap = text_tokens & query_tokens
    return len(overlap) / len(query_tokens)
