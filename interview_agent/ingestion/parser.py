from __future__ import annotations

import re
from dataclasses import dataclass


ABILITY_DIMENSIONS = (
    "project_expression",
    "backend_basic",
    "algorithm",
    "system_design",
    "llm_foundations",
    "post_training_alignment",
    "llm_inference_serving",
    "rag_retrieval",
    "agent_orchestration",
    "llm_evaluation",
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
    "RAG": ("rag", "检索增强", "retrieval augmented generation"),
    "检索召回": ("召回", "recall@k", "召回率", "query rewrite", "hybrid search", "混合检索"),
    "重排排序": ("rerank", "reranker", "重排", "排序模型", "cross-encoder"),
    "索引切分": ("chunk", "chunking", "切分", "索引构建", "向量库", "embedding"),
    "事实性评估": ("faithfulness", "groundedness", "citation", "引用", "幻觉"),
    "知识图谱": ("知识图谱", "kg-rag", "graphrag"),
    "Agent": ("agent", "workflow", "状态机", "生命周期"),
    "工具调用": ("tool calling", "function calling", "工具调用", "tools"),
    "规划记忆": ("plan-and-execute", "planning", "reflection", "react", "memory", "记忆", "规划"),
    "HITL": ("human-in-the-loop", "人工介入", "人工审批", "interrupt", "checkpoint"),
    "LLM基础": (
        "transformer",
        "attention",
        "self-attention",
        "kv cache",
        "kvcache",
        "prefill",
        "decode",
        "rope",
        "rotary",
        "位置编码",
        "moe",
        "ffn",
        "decoder",
    ),
    "位置编码": ("rope", "rotary", "位置编码", "alibi"),
    "MoE": ("moe", "expert parallel", "专家混合"),
    "稀疏注意力": ("稀疏注意力", "linear attention", "rwkv", "mamba", "flash attention"),
    "微调对齐": (
        "微调",
        "finetune",
        "fine-tune",
        "fine tune",
        "lora",
        "qlora",
        "sft",
        "dpo",
        "ppo",
        "rlhf",
        "对齐",
        "蒸馏",
        "冻结层",
        "训练数据",
        "样本多样性",
    ),
    "偏好对齐": ("dpo", "ppo", "rlhf", "reward model", "preference data", "偏好数据", "对齐"),
    "蒸馏量化": ("蒸馏", "distill", "量化感知", "gptq", "awq", "fp8"),
    "推理优化": (
        "推理",
        "inference",
        "吞吐",
        "时延",
        "latency",
        "throughput",
        "显存",
        "量化",
        "vllm",
        "pagedattention",
        "continuous batching",
        "tensor parallel",
        "pipeline parallel",
        "speculative decoding",
        "gpu",
        "cuda",
    ),
    "LLM评测": (
        "评测",
        "eval",
        "benchmark",
        "幻觉",
        "hallucination",
        "groundedness",
        "a/b",
        "judge",
    ),
    "安全鲁棒": ("safety", "红队", "越狱", "jailbreak", "攻击", "鲁棒性"),
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
    "RAG": "rag_retrieval",
    "检索召回": "rag_retrieval",
    "重排排序": "rag_retrieval",
    "索引切分": "rag_retrieval",
    "事实性评估": "rag_retrieval",
    "知识图谱": "rag_retrieval",
    "Agent": "agent_orchestration",
    "工具调用": "agent_orchestration",
    "规划记忆": "agent_orchestration",
    "HITL": "agent_orchestration",
    "LLM基础": "llm_foundations",
    "位置编码": "llm_foundations",
    "MoE": "llm_foundations",
    "稀疏注意力": "llm_foundations",
    "微调对齐": "post_training_alignment",
    "偏好对齐": "post_training_alignment",
    "蒸馏量化": "post_training_alignment",
    "推理优化": "llm_inference_serving",
    "LLM评测": "llm_evaluation",
    "安全鲁棒": "llm_evaluation",
    "算法": "algorithm",
    "行为面": "behavioral",
    "英文": "english",
}


RAG_LLM_FALLBACK_KEYWORDS = (
    "llm",
    "大模型",
    "模型推理",
    "模型服务",
    "transformer",
    "attention",
    "kv cache",
    "kvcache",
    "lora",
    "qlora",
    "sft",
    "dpo",
    "ppo",
    "rlhf",
    "moe",
    "vllm",
    "cuda",
    "gpu",
    "显存",
    "量化",
    "蒸馏",
    "prefill",
    "decode",
    "rope",
    "推理优化",
    "训练数据",
    "对齐",
    "微调",
)


TOPIC_DIMENSION_HINTS: dict[str, tuple[str, ...]] = {
    "llm_foundations": (
        "transformer",
        "attention",
        "rope",
        "位置编码",
        "moe",
        "rwkv",
        "mamba",
        "decoder-only",
        "多头注意力",
        "自注意力",
    ),
    "post_training_alignment": (
        "rag",
        "lora",
        "qlora",
        "微调",
        "训练数据",
        "冻结层",
        "dpo",
        "rlhf",
        "ppo",
        "偏好",
        "蒸馏",
    ),
    "llm_inference_serving": (
        "kv cache",
        "kvcache",
        "推理",
        "时延",
        "吞吐",
        "batching",
        "vllm",
        "量化",
        "显存",
        "gpu",
        "pagedattention",
    ),
    "rag_retrieval": (
        "rag",
        "召回",
        "重排",
        "向量库",
        "embedding",
        "hybrid search",
        "citation",
        "知识图谱",
        "graphrag",
    ),
    "agent_orchestration": (
        "agent",
        "tool calling",
        "workflow",
        "多 agent",
        "memory",
        "planning",
        "reflection",
        "human-in-the-loop",
    ),
    "llm_evaluation": (
        "评测",
        "faithfulness",
        "groundedness",
        "hallucination",
        "benchmark",
        "judge",
    ),
    "system_design": ("系统设计", "高并发", "qps", "限流", "架构", "资源调度"),
    "algorithm": ("算法", "复杂度", "链表", "二叉树", "动态规划", "排序"),
    "behavioral": ("行为面", "合作", "冲突", "优点", "缺点"),
    "english": ("英文", "english", "translate"),
}


TEXT_DIMENSION_HINTS: dict[str, tuple[str, ...]] = {
    "backend_basic": ("redis", "mysql", "epoll", "数据库", "缓存", "索引"),
    "system_design": ("系统设计", "架构", "高并发", "qps", "trade-off", "限流", "资源调度", "负载均衡", "扩展性"),
    "llm_foundations": ("transformer", "attention", "自注意力", "位置编码", "moe", "rwkv", "mamba", "decoder"),
    "post_training_alignment": ("lora", "qlora", "sft", "dpo", "rlhf", "ppo", "偏好", "微调", "蒸馏", "训练数据"),
    "llm_inference_serving": ("kv cache", "推理", "吞吐", "时延", "vllm", "gpu", "cuda", "量化", "显存", "batching", "prefill", "decode"),
    "rag_retrieval": ("rag", "召回", "重排", "embedding", "向量库", "检索", "citation", "知识图谱", "graphrag"),
    "agent_orchestration": ("agent", "tool calling", "workflow", "状态机", "memory", "planning", "reflection", "human-in-the-loop"),
    "llm_evaluation": ("评测", "benchmark", "faithfulness", "groundedness", "hallucination", "judge", "win-rate", "回归测试"),
    "algorithm": ("算法", "复杂度", "链表", "树", "动态规划", "排序"),
    "behavioral": ("自我介绍", "冲突", "合作", "优点", "缺点"),
    "english": ("english", "英文", "translate"),
}


SYSTEM_DESIGN_OVERRIDE_KEYWORDS = (
    "如何设计",
    "架构设计",
    "资源调度",
    "资源分配",
    "任务调度",
    "容量规划",
    "高并发",
    "吞吐",
    "时延",
    "扩展性",
    "负载均衡",
)


LLM_SPECIFIC_DIMENSIONS = (
    "llm_foundations",
    "post_training_alignment",
    "llm_inference_serving",
    "rag_retrieval",
    "agent_orchestration",
    "llm_evaluation",
    "rag_llm",
)


DIMENSION_TIE_BREAK_ORDER = (
    "system_design",
    "llm_inference_serving",
    "post_training_alignment",
    "rag_retrieval",
    "agent_orchestration",
    "llm_foundations",
    "llm_evaluation",
    "backend_basic",
    "algorithm",
    "behavioral",
    "english",
    "project_expression",
    "execution",
    "rag_llm",
)


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
    lowered = text.lower()
    scores = {dimension: 0 for dimension in ABILITY_DIMENSIONS}

    for topic in topics:
        mapped = TOPIC_TO_DIMENSION.get(topic)
        if mapped:
            scores[mapped] += 3

    lowered_topics = " | ".join(topic.lower() for topic in topics if topic)
    for dimension, hints in TOPIC_DIMENSION_HINTS.items():
        scores[dimension] += sum(1 for hint in hints if hint.lower() in lowered_topics)

    for dimension, hints in TEXT_DIMENSION_HINTS.items():
        scores[dimension] += sum(1 for hint in hints if hint.lower() in lowered or hint in text)

    if any(keyword in lowered or keyword in text for keyword in RAG_LLM_FALLBACK_KEYWORDS):
        scores["rag_llm"] += 2

    llm_signal = sum(scores[dimension] for dimension in LLM_SPECIFIC_DIMENSIONS)
    system_design_hits = sum(
        1 for keyword in SYSTEM_DESIGN_OVERRIDE_KEYWORDS if keyword.lower() in lowered or keyword in text
    )
    if llm_signal and system_design_hits >= 2 and any(
        marker in text for marker in ("如何做", "如何设计", "资源分配", "任务调度", "架构设计")
    ):
        return "system_design"
    if llm_signal and system_design_hits >= 2:
        scores["system_design"] += 6

    ranked = sorted(
        scores.items(),
        key=lambda item: (
            -item[1],
            DIMENSION_TIE_BREAK_ORDER.index(item[0]) if item[0] in DIMENSION_TIE_BREAK_ORDER else len(DIMENSION_TIE_BREAK_ORDER),
        ),
    )
    if ranked and ranked[0][1] > 0:
        return ranked[0][0]
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
    if dimension == "llm_foundations":
        return "回答应覆盖：核心结构、关键机制、复杂度或内存特征，以及与替代方案的 trade-off。"
    if dimension == "post_training_alignment":
        return "回答应覆盖：训练目标、数据构建、可训练参数范围、关键超参，以及效果与成本 trade-off。"
    if dimension == "llm_inference_serving":
        return "回答应覆盖：prefill/decode 路径、吞吐/时延/显存瓶颈，以及 batching、cache 或并行策略。"
    if dimension == "rag_retrieval":
        return "回答应覆盖：切分与索引、召回与重排、生成注入方式、评测指标与幻觉控制。"
    if dimension == "agent_orchestration":
        return "回答应覆盖：状态、规划、工具调用、记忆、失败恢复和人工介入机制。"
    if dimension == "llm_evaluation":
        return "回答应覆盖：离线/在线指标、评测集设计、judge 或人工标注方案，以及回归监控。"
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
    if dimension == "llm_foundations":
        expected_keywords.extend(["结构", "机制", "复杂度", "trade-off"])
    if dimension == "post_training_alignment":
        expected_keywords.extend(["训练目标", "数据", "参数", "trade-off"])
    if dimension == "llm_inference_serving":
        expected_keywords.extend(["prefill", "decode", "吞吐", "显存"])
    if dimension == "rag_retrieval":
        expected_keywords.extend(["召回", "重排", "评测", "幻觉"])
    if dimension == "agent_orchestration":
        expected_keywords.extend(["状态", "工具", "记忆", "恢复"])
    if dimension == "llm_evaluation":
        expected_keywords.extend(["指标", "评测集", "judge", "回归"])
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
