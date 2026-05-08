from interview_agent.ingestion.parser import (
    compose_jd_source_text,
    evaluate_answer,
    extract_jd_requirements,
    infer_dimension,
    infer_topics,
    parse_question_batch,
    split_jd_sections,
)


def test_parse_question_batch_extracts_source_and_answer() -> None:
    raw_text = """
【来源】字节跳动后端实习，Backend Intern

Redis 为什么单线程还这么快？
我的答案：因为它是内存操作，然后用了 IO 多路复用。

MySQL 的索引为什么用 B+ 树不用 B 树？
我的答案：范围查询更方便，但是其他细节不太会。
""".strip()

    parsed = parse_question_batch(raw_text)

    assert len(parsed) == 2
    assert parsed[0].source_company == "字节跳动后端实习"
    assert parsed[0].source_role == "Backend Intern"
    assert "IO 多路复用" in parsed[0].answer


def test_topic_dimension_and_answer_evaluation() -> None:
    question = "Redis 为什么单线程还这么快？"
    answer = "因为 Redis 主要是内存操作，单线程避免锁竞争，还依赖 IO 多路复用和事件循环。"

    topics = infer_topics(question)
    dimension = infer_dimension(question, topics)
    mastery, gaps, probes = evaluate_answer(
        question=question,
        answer=answer,
        topics=topics,
        dimension=dimension,
    )

    assert "Redis" in topics
    assert dimension == "backend_basic"
    assert mastery in {"熟练掌握", "部分掌握"}
    assert probes
    assert all(isinstance(item, str) for item in gaps)


def test_split_jd_sections_extracts_description_and_requirements() -> None:
    raw_text = """
职位描述
负责推荐系统后端服务开发，与算法团队协作推动上线。

职位要求
- 熟悉 Python / Go
- 具备高并发系统设计能力
""".strip()

    description, requirements = split_jd_sections(raw_text)

    assert description == "负责推荐系统后端服务开发，与算法团队协作推动上线。"
    assert "- 熟悉 Python / Go" in requirements
    assert "高并发系统设计能力" in requirements


def test_extract_jd_requirements_prefers_requirement_section() -> None:
    raw_text = compose_jd_source_text(
        job_description="负责研发和跨团队协作。",
        job_requirements="熟悉 Redis\n具备系统设计能力",
    )

    requirements = extract_jd_requirements(raw_text)

    assert [item["text"] for item in requirements] == ["熟悉 Redis", "具备系统设计能力"]
