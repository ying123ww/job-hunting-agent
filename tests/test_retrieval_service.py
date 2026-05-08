from interview_agent.agent.memory import AgentMemoryStore
from interview_agent.retrieval.service import RetrievalService
from interview_agent.storage.vector_store import VectorMatch


class FakeRepository:
    def latest_target_jd(self, session, *, user_id: str, jd_id: str | None = None):
        if jd_id == "jd_1":
            return type("JD", (), {"document_id": "doc_jd_1"})()
        return None

    def lexical_search(self, session, *, user_id: str, query_text: str, source_types, limit: int):
        return []


class FakeVectorStore:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    def query(self, *, collection_name: str, query_text: str, where, limit: int):
        self.queries.append((collection_name, query_text))
        if collection_name == "gap_memory":
            return [
                VectorMatch(
                    vector_id="gap_1",
                    text="系统设计 mock 中未提到 QPS 估算和缓存策略",
                    metadata={
                        "source_type": "gap_record",
                        "document_id": "doc_gap",
                        "chunk_id": "chunk_gap",
                        "dimension": "system_design",
                        "question_id": "",
                        "topics_text": "",
                    },
                    score=0.8,
                )
            ]
        return [
            VectorMatch(
                vector_id="chunk_resume",
                text="简历里写了 Redis 缓存，但没有展开容量估算。",
                metadata={
                    "source_type": "resume",
                    "document_id": "doc_resume",
                    "chunk_id": "chunk_resume",
                    "dimension": "system_design",
                    "question_id": "",
                    "topics_text": "Redis,缓存",
                },
                score=0.7,
            ),
            VectorMatch(
                vector_id="chunk_jd_1",
                text="JD 1 强调 Redis 与缓存设计。",
                metadata={
                    "source_type": "jd",
                    "document_id": "doc_jd_1",
                    "chunk_id": "chunk_jd_1",
                    "dimension": "backend_basic",
                    "question_id": "",
                    "topics_text": "Redis,缓存",
                },
                score=0.68,
            ),
            VectorMatch(
                vector_id="chunk_jd_2",
                text="JD 2 强调系统设计与高并发。",
                metadata={
                    "source_type": "jd",
                    "document_id": "doc_jd_2",
                    "chunk_id": "chunk_jd_2",
                    "dimension": "system_design",
                    "question_id": "",
                    "topics_text": "系统设计,高并发",
                },
                score=0.67,
            ),
            VectorMatch(
                vector_id="chunk_resume_dup",
                text="简历里写了 Redis 缓存，但没有展开容量估算。",
                metadata={
                    "source_type": "resume",
                    "document_id": "doc_resume",
                    "chunk_id": "chunk_resume",
                    "dimension": "system_design",
                    "question_id": "",
                    "topics_text": "Redis,缓存",
                },
                score=0.65,
            ),
        ]


def test_route_request_builds_strategy_and_query_variants(tmp_path) -> None:
    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.current_goal = "准备后端一面"
    working.current_focus = "系统设计表达"
    working.latest_top_gap_dimensions = ["system_design"]
    memory_store.write_working_memory(working)

    retrieval = RetrievalService(repository=None, vector_store=FakeVectorStore())  # type: ignore[arg-type]
    route = retrieval.route_request(
        query_text="今天该学什么？",
        intent="plan",
        memory_snapshot=memory_store.snapshot(),
    )

    assert route.strategy == "planning"
    assert route.source_types == ["gap_record", "question", "jd", "resume"]
    assert route.dimension == "system_design"
    assert len(route.query_variants) >= 2
    assert any("goal:准备后端一面" in item for item in route.query_variants)


def test_build_evidence_bundle_uses_multi_lane_queries_and_dedupes(tmp_path) -> None:
    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.current_goal = "准备后端一面"
    working.latest_top_gap_dimensions = ["system_design"]
    memory_store.write_working_memory(working)

    vector_store = FakeVectorStore()
    retrieval = RetrievalService(repository=None, vector_store=vector_store)  # type: ignore[arg-type]
    evidence = retrieval.build_evidence_bundle(
        None,
        user_id="u_demo",
        query_text="今天该学什么？",
        intent="plan",
        memory_snapshot=memory_store.snapshot(),
        limit=4,
    )

    assert len(evidence) == 4
    assert evidence[0].source_type == "gap_record"
    assert evidence[0].score >= evidence[1].score
    assert len([item for item in evidence if item.source_type == "resume"]) == 1
    assert len([item for item in evidence if item.source_type == "jd"]) == 2
    assert len(vector_store.queries) >= 3


def test_build_evidence_bundle_filters_jd_hits_to_selected_document(tmp_path) -> None:
    memory_store = AgentMemoryStore(tmp_path / "memory")
    working = memory_store.read_working_memory()
    working.current_goal = "针对 JD 1 改简历"
    memory_store.write_working_memory(working)

    retrieval = RetrievalService(repository=FakeRepository(), vector_store=FakeVectorStore())  # type: ignore[arg-type]
    evidence = retrieval.build_evidence_bundle(
        object(),
        user_id="u_demo",
        query_text="Redis 相关经历怎么改写？",
        source_types=["resume", "jd"],
        jd_id="jd_1",
        memory_snapshot=memory_store.snapshot(),
        limit=6,
    )

    jd_evidence = [item for item in evidence if item.source_type == "jd"]

    assert jd_evidence
    assert {item.document_id for item in jd_evidence} == {"doc_jd_1"}
