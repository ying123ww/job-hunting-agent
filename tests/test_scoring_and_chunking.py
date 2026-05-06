from interview_agent.diagnosis.service import compute_priority_score
from interview_agent.ingestion.chunking import split_text


def test_split_text_handles_long_paragraphs() -> None:
    text = "A" * 650 + "\n\n" + "B" * 700

    chunks = split_text(text, chunk_size=300, chunk_overlap=50)

    assert len(chunks) >= 4
    assert all(chunks)
    assert all(len(chunk) <= 300 for chunk in chunks)


def test_priority_score_favors_stronger_signals() -> None:
    higher = compute_priority_score(
        jd_weight=0.9,
        weakness_severity=0.9,
        evidence_confidence=0.9,
        repeated_failure_factor=1.3,
        recent_improvement=0.0,
    )
    lower = compute_priority_score(
        jd_weight=0.45,
        weakness_severity=0.4,
        evidence_confidence=0.7,
        repeated_failure_factor=1.0,
        recent_improvement=0.4,
    )

    assert higher > lower
    assert round(higher, 4) == higher
