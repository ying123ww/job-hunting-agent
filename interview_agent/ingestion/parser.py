from __future__ import annotations

import re
from dataclasses import dataclass


ABILITY_DIMENSIONS = (
    "project_expression",
    "backend_basic",
    "algorithm",
    "system_design",
    "rag_llm",
    "behavioral",
    "english",
    "execution",
)

TOPIC_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Redis": ("redis",),
    "MySQL": ("mysql", "索引", "b+树", "b树"),
    "epoll": ("epoll", "io 多路复用", "i/o 多路复用", "poll", "select"),
    "缓存一致性": ("缓存一致性", "cache consistency"),
    "系统设计": ("系统设计", "高并发", "qps", "限流", "架构", "短链"),
    "RAG": ("rag", "检索增强", "向量库", "召回", "embedding", "faithfulness", "recall@k"),
    "Agent": ("agent", "workflow", "状态机", "生命周期"),
    "算法": ("算法", "链表", "二叉树", "动态规划", "排序"),
    "行为面": ("自我介绍", "冲突", "合作", "优点", "缺点"),
    "英文": ("english", "英文", "translate"),
}

TOPIC_TO_DIMENSION = {
    "Redis": "backend_basic",
    "MySQL": "backend_basic",
    "epoll": "backend_basic",
    "缓存一致性": "system_design",
    "系统设计": "system_design",
    "RAG": "rag_llm",
    "Agent": "rag_llm",
    "算法": "algorithm",
    "行为面": "behavioral",
    "英文": "english",
}


@dataclass(slots=True)
class ParsedQuestion:
    question: str
    answer: str
    source_company: str | None
    source_role: str | None
    block_text: str


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def compose_jd_source_text(
    *,
    job_description: str | None = None,
    job_requirements: str | None = None,
) -> str:
    sections: list[str] = []
    description = (job_description or "").strip()
    requirements = (job_requirements or "").strip()
    if description:
        sections.append(f"职位描述\n{description}")
    if requirements:
        sections.append(f"职位要求\n{requirements}")
    return "\n\n".join(sections).strip()


def split_jd_sections(text: str) -> tuple[str | None, str | None]:
    description_lines: list[str] = []
    requirement_lines: list[str] = []
    current_section: str | None = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            if current_section == "description" and description_lines and description_lines[-1] != "":
                description_lines.append("")
            elif current_section == "requirements" and requirement_lines and requirement_lines[-1] != "":
                requirement_lines.append("")
            continue

        section, remainder = _match_jd_section_heading(stripped)
        if section is not None:
            current_section = section
            if remainder:
                if section == "description":
                    description_lines.append(remainder)
                else:
                    requirement_lines.append(remainder)
            continue

        if current_section == "description":
            description_lines.append(stripped)
        elif current_section == "requirements":
            requirement_lines.append(stripped)

    description = "\n".join(description_lines).strip() or None
    requirements = "\n".join(requirement_lines).strip() or None
    return description, requirements


def _match_jd_section_heading(line: str) -> tuple[str | None, str]:
    aliases = {
        "description": ("职位描述", "工作描述", "岗位描述", "job description"),
        "requirements": ("职位要求", "任职要求", "岗位要求", "requirements", "job requirements"),
    }
    lowered = line.lower()
    for section, names in aliases.items():
        for name in names:
            if lowered == name.lower():
                return section, ""
            for delimiter in ("：", ":"):
                prefix = f"{name}{delimiter}"
                if lowered.startswith(prefix.lower()):
                    return section, line[len(prefix):].strip()
    return None, ""


def parse_source_header(raw_text: str) -> tuple[str | None, str | None]:
    header_match = re.search(r"【来源】\s*(.+)", raw_text)
    if not header_match:
        return None, None
    header = header_match.group(1).strip()
    parts = [part.strip() for part in re.split(r"[，,]", header) if part.strip()]
    company = parts[0] if parts else None
    role = parts[1] if len(parts) > 1 else None
    return company, role


def parse_question_batch(
    raw_text: str,
    *,
    fallback_company: str | None = None,
    fallback_role: str | None = None,
) -> list[ParsedQuestion]:
    company, role = parse_source_header(raw_text)
    source_company = fallback_company or company
    source_role = fallback_role or role
    cleaned = re.sub(r"【来源】.+\n?", "", raw_text).strip()
    blocks = [block.strip() for block in re.split(r"\n\s*\n", cleaned) if block.strip()]
    questions: list[ParsedQuestion] = []
    answer_markers = ("我的答案：", "我的答案:", "answer:", "Answer:")

    for block in blocks:
        question_text = block
        answer_text = ""
        for marker in answer_markers:
            if marker in block:
                before, after = block.split(marker, 1)
                question_text = before.strip()
                answer_text = after.strip()
                break
        if not answer_text:
            lines = [line.strip() for line in block.splitlines() if line.strip()]
            if not lines:
                continue
            question_text = lines[0]
            answer_text = "\n".join(lines[1:]).strip()
        question_text = question_text.strip("：: \n")
        if not question_text:
            continue
        questions.append(
            ParsedQuestion(
                question=question_text,
                answer=answer_text,
                source_company=source_company,
                source_role=source_role,
                block_text=block,
            )
        )
    return questions


def infer_topics(text: str) -> list[str]:
    lowered = text.lower()
    topics = [
        topic
        for topic, keywords in TOPIC_KEYWORDS.items()
        if any(keyword in lowered for keyword in keywords)
    ]
    return topics or ["General"]


def infer_dimension(text: str, topics: list[str]) -> str:
    for topic in topics:
        mapped = TOPIC_TO_DIMENSION.get(topic)
        if mapped:
            return mapped
    lowered = text.lower()
    if "项目" in text or "project" in lowered:
        return "project_expression"
    return "backend_basic"


def build_reference_answer(question: str, topics: list[str], dimension: str) -> str:
    if "Redis" in topics:
        return "回答应覆盖：内存操作快、单线程避免锁竞争、IO 多路复用、事件循环模型。"
    if "MySQL" in topics:
        return "回答应覆盖：B+ 树更适合范围查询、磁盘页利用率、树高更低、叶子节点链表。"
    if dimension == "system_design":
        return "回答应覆盖：需求澄清、容量估算、核心组件、数据流、瓶颈与 trade-off。"
    if dimension == "rag_llm":
        return "回答应覆盖：检索、召回、重排、生成、评测指标与幻觉控制。"
    if dimension == "behavioral":
        return "回答应覆盖：背景、行动、结果、复盘。"
    if dimension == "algorithm":
        return "回答应覆盖：思路、复杂度、边界情况和优化。"
    return f"围绕问题 `{question}` 给出定义、原理、关键细节和适用场景。"


def evaluate_answer(
    *,
    question: str,
    answer: str,
    topics: list[str],
    dimension: str,
) -> tuple[str, list[str], list[str]]:
    expected_keywords: list[str] = []
    if "Redis" in topics:
        expected_keywords.extend(["内存", "单线程", "多路复用", "事件循环"])
    if "MySQL" in topics:
        expected_keywords.extend(["范围查询", "叶子节点", "树高", "磁盘页"])
    if "epoll" in topics:
        expected_keywords.extend(["select", "poll", "epoll", "事件通知"])
    if dimension == "system_design":
        expected_keywords.extend(["qps", "缓存", "限流", "trade-off"])
    if dimension == "rag_llm":
        expected_keywords.extend(["召回", "重排", "embedding", "评测"])
    if dimension == "behavioral":
        expected_keywords.extend(["背景", "行动", "结果", "复盘"])
    if dimension == "algorithm":
        expected_keywords.extend(["复杂度", "边界", "优化"])

    lowered = answer.lower()
    matched = [keyword for keyword in expected_keywords if keyword.lower() in lowered]
    coverage = len(set(matched)) / len(set(expected_keywords)) if expected_keywords else 0.0

    if coverage >= 0.7 and len(answer) >= 40:
        mastery = "熟练掌握"
    elif coverage >= 0.3 or len(answer) >= 20:
        mastery = "部分掌握"
    else:
        mastery = "需要加强"

    gaps = [
        f"没有覆盖 `{keyword}` 这一点"
        for keyword in expected_keywords
        if keyword.lower() not in lowered
    ][:3]
    if not gaps:
        gaps = ["表达可以更结构化，建议补充更清晰的回答框架。"]

    probes = [f"继续追问：{keyword} 在这个问题里为什么重要？" for keyword in expected_keywords[:2]]
    if not probes:
        probes = [f"继续追问：如何把这个问题答得更完整？"]
    return mastery, gaps, probes


def extract_jd_requirements(text: str) -> list[dict[str, object]]:
    _, job_requirements = split_jd_sections(text)
    source_text = job_requirements or text
    lines = [line.strip("-• \t") for line in source_text.splitlines() if line.strip()]
    requirements: list[dict[str, object]] = []
    for line in lines[:20]:
        topics = infer_topics(line)
        dimension = infer_dimension(line, topics)
        weight = 0.9 if any(token in line for token in ("熟悉", "精通", "负责", "能力")) else 0.6
        requirements.append(
            {
                "text": line,
                "dimension": dimension,
                "topics": topics,
                "weight": weight,
            }
        )
    return requirements or [
        {
            "text": source_text[:200],
            "dimension": "backend_basic",
            "topics": ["General"],
            "weight": 0.5,
        }
    ]


def extract_projects_from_resume(text: str) -> list[dict[str, object]]:
    projects: list[dict[str, object]] = []
    for line in text.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if not stripped:
            continue
        if "项目" in stripped or lowered.startswith("project"):
            topics = infer_topics(stripped)
            projects.append(
                {
                    "name": stripped[:80],
                    "tech_stack": [topic for topic in topics if topic != "General"],
                    "role": None,
                    "metrics": {},
                }
            )
    return projects[:5]
