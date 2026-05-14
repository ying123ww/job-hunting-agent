from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from interview_agent.app.config import get_settings
from interview_agent.core.container import AppContainer
from interview_agent.diagnosis.service import DiagnosedGap
from interview_agent.retrieval.service import EvidenceItem


EVAL_CASE_DIR = Path(__file__).parent / "fixtures" / "eval_cases"
USER_ID = "u_eval"


def _load_eval_cases() -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    for path in sorted(EVAL_CASE_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for item in payload:
            cases.append({**item, "_path": str(path)})
    return cases


def source_recall_at_k(evidence: list[EvidenceItem], expected_sources: list[str], k: int) -> int:
    actual_sources = {item.source_type for item in evidence[:k]}
    return int(any(source in actual_sources for source in expected_sources))


def dimension_accuracy(actual_dimension: str | None, expected_dimension: str) -> int:
    return int((actual_dimension or "") == expected_dimension)


def evidence_grounding(evidence: list[EvidenceItem], expected_terms: list[str]) -> int:
    haystack = "\n".join(item.text for item in evidence)
    haystack_lower = haystack.lower()
    return int(any(term.lower() in haystack_lower for term in expected_terms))


def top_gap_hit_at_k(gaps: list[DiagnosedGap], expected_gap: str, k: int) -> int:
    actual_dimensions = [gap.dimension for gap in gaps[:k]]
    return int(expected_gap in actual_dimensions)


@pytest.mark.parametrize("case", _load_eval_cases(), ids=lambda item: item["id"])
def test_eval_case(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, case: dict[str, Any]) -> None:
    monkeypatch.setenv("INTERVIEW_AGENT_DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")
    monkeypatch.setenv("INTERVIEW_AGENT_CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setenv("INTERVIEW_AGENT_MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setenv("INTERVIEW_AGENT_DIDA365_ENABLED", "false")
    get_settings.cache_clear()

    container = AppContainer.build(get_settings())
    with container.db.session_scope() as session:
        jd_id = _seed_case(container, session, case)
        if case["kind"] == "rag":
            _assert_rag_case(container, session, case, jd_id=jd_id)
        elif case["kind"] == "diagnosis":
            _assert_diagnosis_case(container, session, case, jd_id=jd_id)
        else:
            raise AssertionError(f"Unsupported eval case kind: {case['kind']}")


def _seed_case(container: AppContainer, session, case: dict[str, Any]) -> str | None:
    seed = case["seed"]

    resume_text = str(seed.get("resume") or "").strip()
    if resume_text:
        resume = container.document_ingestion.ingest_document(
            session,
            user_id=USER_ID,
            source_type="resume",
            text=resume_text,
            content_base64=None,
            filename=f"{case['id']}_resume.md",
            metadata={},
        )
        container.document_ingestion.persist_resume_side_effects(
            session,
            user_id=USER_ID,
            document_id=resume.document_id,
            text=resume.raw_text,
        )

    jd_id = None
    jd_text = str(seed.get("jd") or "").strip()
    if jd_text:
        jd = container.document_ingestion.ingest_document(
            session,
            user_id=USER_ID,
            source_type="jd",
            text=jd_text,
            content_base64=None,
            filename=f"{case['id']}_jd.txt",
            metadata={"company": "EvalCorp", "role": "Backend Intern"},
        )
        jd_record = container.document_ingestion.persist_jd_side_effects(
            session,
            user_id=USER_ID,
            document_id=jd.document_id,
            text=jd.raw_text,
            company="EvalCorp",
            role="Backend Intern",
            url=None,
            job_description=None,
            job_requirements=None,
        )
        jd_id = jd_record.id
        container.repository.upsert_user_profile(
            session,
            user_id=USER_ID,
            current_jd_id=jd_id,
        )

    questions_text = str(seed.get("questions") or "").strip()
    if questions_text:
        result = container.question_ingestion.ingest_questions(
            session,
            user_id=USER_ID,
            text=questions_text,
            content_base64=None,
            filename=f"{case['id']}_questions.txt",
            metadata={"source_scope": case["id"]},
            source_company="EvalCorp",
            source_role="Backend Intern",
        )
        assert result.records, f"{case['id']} did not ingest any question records"

    return jd_id


def _assert_rag_case(container: AppContainer, session, case: dict[str, Any], *, jd_id: str | None) -> None:
    expected = case["expected"]
    k = int(expected.get("recall_at_k", 4))
    route = container.retrieval.route_request(
        query_text=case["query"],
        intent=case.get("intent"),
    )
    evidence = container.retrieval.build_evidence_bundle(
        session,
        user_id=USER_ID,
        query_text=case["query"],
        intent=case.get("intent"),
        jd_id=jd_id,
        limit=k,
    )

    metrics = {
        "source_recall_at_k": source_recall_at_k(evidence, list(expected["source_types"]), k),
        "dimension_accuracy": dimension_accuracy(route.dimension, str(expected["dimension"])),
        "evidence_grounding": evidence_grounding(evidence, list(expected["must_contain_any"])),
    }

    assert metrics == {
        "source_recall_at_k": 1,
        "dimension_accuracy": 1,
        "evidence_grounding": 1,
    }, {
        "case_id": case["id"],
        "fixture": case["_path"],
        "route": route,
        "metrics": metrics,
        "evidence": evidence,
    }


def _assert_diagnosis_case(container: AppContainer, session, case: dict[str, Any], *, jd_id: str | None) -> None:
    expected = case["expected"]
    k = int(expected.get("top_gap_in_top_k", 3))
    overall_risk, gaps = container.diagnosis.analyze(
        session,
        user_id=USER_ID,
        jd_id=jd_id,
        limit=k,
        persist=True,
    )

    metrics = {
        "top_gap_hit_at_k": top_gap_hit_at_k(gaps, str(expected["top_gap"]), k),
        "overall_risk_allowed": int(overall_risk in set(expected["overall_risk_in"])),
        "has_grounded_evidence": int(bool(gaps and gaps[0].evidence)),
        "why_grounded": int(_why_contains_any(gaps, list(expected.get("why_contains_any", [])))),
    }

    assert metrics == {
        "top_gap_hit_at_k": 1,
        "overall_risk_allowed": 1,
        "has_grounded_evidence": 1,
        "why_grounded": 1,
    }, {
        "case_id": case["id"],
        "fixture": case["_path"],
        "overall_risk": overall_risk,
        "metrics": metrics,
        "gaps": gaps,
    }


def _why_contains_any(gaps: list[DiagnosedGap], expected_terms: list[str]) -> bool:
    if not expected_terms:
        return True
    text = "\n".join(gap.why_it_matters for gap in gaps)
    return any(term in text for term in expected_terms)
