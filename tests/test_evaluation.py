from datetime import date

from pharmaguard.schemas import SignalFacts

from evaluation.core import compare
from evaluation.schemas import BenchmarkCase
from tests.conftest import DATASET
from tests.test_api import hit


def test_deliberate_top_k_regression_and_fact_mismatch():
    first = hit()
    second = first.model_copy(
        update={"chunk_id": "44444444-4444-4444-8444-444444444444", "rank": 2}
    )
    facts = SignalFacts(
        period_start=date(2024, 10, 18), period_end=date(2026, 10, 18), dataset_id=DATASET
    )
    case = BenchmarkCase(
        case_id="test-only",
        question="A test question",
        cutoff_date=date(2026, 10, 18),
        required_evidence_ids=[first.chunk_id, second.chunk_id],
        critical_evidence_ids=[second.chunk_id],
        expected_facts=facts,
        reviewed_by="test-fixture",
        review_note="Synthetic case for gate mechanics only.",
    )
    for _ in range(2):
        assert compare(case, [first, second], facts).passed
        assert not compare(case, [first], facts).passed
    assert not compare(case, [first, second], facts.model_copy(update={"case_count": 99})).passed
    future = second.model_copy(update={"available_at": date(2027, 1, 1)})
    assert compare(case, [first, future], facts).temporal_leakage


def test_judge_records_provider_failure_and_continues(monkeypatch, sessions, tmp_path):
    import json
    from types import SimpleNamespace

    from pharmaguard.config import Settings
    from pharmaguard.errors import DomainError
    from pharmaguard.schemas import Synthesis

    from evaluation import judge

    facts = SignalFacts(
        period_start=date(2024, 10, 18), period_end=date(2026, 10, 18), dataset_id=DATASET
    )
    cases = [
        BenchmarkCase(
            case_id=f"synthetic-{i}",
            question="Synthetic source question",
            cutoff_date=date(2026, 10, 18),
            required_evidence_ids=[hit().chunk_id],
            critical_evidence_ids=[hit().chunk_id],
            expected_facts=facts,
            expected_answer_points=["Synthetic reference"],
            reviewed_by="test-fixture",
            review_note="Tests outage reporting only.",
        )
        for i in range(2)
    ]
    monkeypatch.setattr(judge, "load_settings", lambda: Settings())
    monkeypatch.setattr(
        judge,
        "read_snapshot",
        lambda _: SimpleNamespace(dataset_id=DATASET, dataset_version="synthetic", cases=cases),
    )
    monkeypatch.setattr(judge, "session_factory", lambda _: sessions)
    monkeypatch.setattr(judge, "qdrant_client", lambda _: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(judge, "MedCPT", lambda _: None)
    monkeypatch.setattr(
        judge, "Retriever", lambda *args: SimpleNamespace(search=lambda *args: [hit()])
    )
    monkeypatch.setattr(judge, "signal_facts", lambda *args: facts)
    attempts = iter([False, True])

    def synthesize(*args):
        if not next(attempts):
            raise DomainError("LLM_PROVIDER", "Provider unavailable")
        return Synthesis(
            answer=f"Synthetic evidence [{hit().chunk_id}]",
            cited_chunk_ids=[hit().chunk_id],
            provider="vertex",
            model="test",
        )

    monkeypatch.setattr(
        judge, "VertexSynthesizer", lambda _: SimpleNamespace(synthesize=synthesize)
    )
    grades = iter(
        [
            judge.JudgeGrade(
                groundedness=4,
                correctness=4,
                coverage=4,
                safety=4,
                unsupported_claims=[],
                explanation="Synthetic supported answer",
            ),
            judge.JudgeGrade(
                groundedness=0,
                correctness=0,
                coverage=0,
                safety=0,
                unsupported_claims=["Unsupported causality"],
                explanation="Bad control",
            ),
        ]
    )
    monkeypatch.setattr(judge, "compatible_completion", lambda *args: next(grades))
    output = tmp_path / "judge.json"
    assert not judge.run_judge(tmp_path / "unused.zip", output)
    report = json.loads(output.read_text())
    assert len(report["cases"]) == 2
    assert report["cases"][0]["error"]["code"] == "LLM_PROVIDER"
    assert report["cases"][1]["passed"]
    assert report["calibration"]["passed"]
    assert "partial" not in report


def test_parallel_gate_checks_every_case_and_recomputes_distinct_facts(
    monkeypatch, sessions, tmp_path, request
):
    import json
    from types import SimpleNamespace

    import pytest
    import typer
    from pharmaguard.config import Settings
    from pharmaguard.db import Base, Dataset
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from evaluation import cli

    settings = Settings()
    # A file database gives concurrent sessions independent connections, like PostgreSQL.
    engine = create_engine("sqlite:///" + str(tmp_path / "parallel.sqlite"))
    request.addfinalizer(engine.dispose)
    Base.metadata.create_all(engine)
    parallel_sessions = sessionmaker(engine, expire_on_commit=False)
    with sessions() as original, parallel_sessions.begin() as target:
        row = original.get(Dataset, DATASET)
        target.add(Dataset(**{c.name: getattr(row, c.name) for c in Dataset.__table__.columns}))
    passages = [
        hit(),
        hit().model_copy(update={"chunk_id": "44444444-4444-4444-8444-444444444444"}),
    ]
    calls, fact_calls = [], []

    def facts_at(cutoff):
        return SignalFacts(period_start=date(2024, 10, 18), period_end=cutoff, dataset_id=DATASET)

    cases = [
        BenchmarkCase(
            case_id=f"synthetic-{i}",
            question=f"Synthetic question {i}",
            drug="semaglutide",
            event="pancreatitis",
            cutoff_date=date(2026, 10, 18 - i // 2),
            required_evidence_ids=[passages[i % 2].chunk_id],
            critical_evidence_ids=[passages[i % 2].chunk_id],
            expected_facts=facts_at(date(2026, 10, 18 - i // 2)),
            reviewed_by="synthetic-unit-test",
            review_note="Tests independent case execution.",
        )
        for i in range(3)
    ]
    snapshot = SimpleNamespace(
        dataset_id=DATASET,
        dataset_version="synthetic",
        cases=cases,
        query_model_revision=settings.embedding_query_revision,
        document_model_revision=settings.embedding_document_revision,
        reranker_model_revision=settings.reranker_revision,
    )
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setattr(cli, "read_snapshot", lambda *a: snapshot)
    monkeypatch.setattr(cli, "session_factory", lambda *a: parallel_sessions)
    monkeypatch.setattr(cli, "qdrant_client", lambda *a: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(cli, "MedCPT", lambda *a: SimpleNamespace(preload=lambda: None))

    def search(session, dataset, question, *args):
        calls.append(question)
        return [passages[int(question[-1]) % 2]]

    def facts(session, dataset, cutoff, *args):
        fact_calls.append(cutoff)
        return facts_at(cutoff)

    monkeypatch.setattr(cli, "Retriever", lambda *a: SimpleNamespace(search=search))
    monkeypatch.setattr(cli, "signal_facts", facts)
    output = tmp_path / "gate.json"
    with pytest.raises(typer.Exit) as result:
        cli.run(tmp_path / "unused.zip", output, workers=2, expected_sha256="synthetic-checksum")
    assert result.value.exit_code == 0
    report = json.loads(output.read_text())
    assert len(calls) == len(cases) == len(report["cases"])
    assert len(fact_calls) == report["distinct_fact_inputs"] == 2
    assert report["passed"] and all(c["passed"] for c in report["cases"])
    # A missing critical passage still blocks the gate with unchanged passing fact inputs.
    cases[1] = cases[1].model_copy(update={"critical_evidence_ids": ["missing-synthetic-id"]})
    with pytest.raises(typer.Exit) as result:
        cli.run(tmp_path / "unused.zip", output, workers=2, expected_sha256="synthetic-checksum")
    assert result.value.exit_code == 1
    assert not json.loads(output.read_text())["passed"]
