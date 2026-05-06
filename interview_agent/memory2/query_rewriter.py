from __future__ import annotations

import re


def rewrite_query(query: str) -> list[str]:
    text = re.sub(r"\s+", " ", query.strip())
    if not text:
        return []
    candidates = [text]
    if "今天" in text and "计划" in text:
        candidates.append("今日计划 面试准备")
    if "短板" in text or "诊断" in text:
        candidates.append("面试短板 历史错误")
    if "项目" in text:
        candidates.append("项目经历 项目表达")
    tokens = [token for token in re.split(r"[，,。！？?\s]+", text) if len(token) >= 2]
    for token in tokens[:3]:
        if token not in candidates:
            candidates.append(token)
    return candidates
