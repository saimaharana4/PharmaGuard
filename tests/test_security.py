import pytest
from pharmaguard.config import Settings
from pharmaguard.errors import DomainError
from pharmaguard.security import reserve_request
from pharmaguard.synthesis import (
    CitedParagraph,
    CitedSynthesis,
    VertexSynthesizer,
    render_synthesis,
)

from tests.test_api import hit


def test_env_files_are_never_loaded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("GROQ_API_KEY=not-a-real-key\n")
    assert Settings().groq_api_key.get_secret_value() == ""


def test_cloudsql_tcp_proxy_requires_explicit_transport_override():
    settings = Settings(cloud_sql_connection_name="project:region:instance", db_port=55433)
    assert settings.database_url().query["host"].startswith("/cloudsql/")
    proxy = settings.model_copy(update={"db_use_tcp": True})
    assert proxy.database_url().host == "127.0.0.1"
    assert proxy.database_url().port == 55433
    assert not proxy.database_url().query


def test_shared_usage_budget_fails_closed(sessions):
    with sessions() as session:
        reserve_request(session, 2)
        reserve_request(session, 2)
        with pytest.raises(DomainError, match="daily investigation limit"):
            reserve_request(session, 2)


def test_fallback_preserves_citation_validation(monkeypatch):
    import pharmaguard.synthesis as module

    def failed_primary(*args):
        raise DomainError("LLM_PROVIDER", "Provider unavailable", 502)

    monkeypatch.setattr(VertexSynthesizer, "_vertex", failed_primary)
    monkeypatch.setattr(
        module,
        "compatible_completion",
        lambda *args: CitedSynthesis(
            paragraphs=[CitedParagraph(text="Test evidence", cited_chunk_ids=[hit().chunk_id])],
            insufficient_evidence=False,
        ),
    )
    from datetime import date

    from pharmaguard.schemas import SignalFacts

    facts = SignalFacts(
        period_start=date(2024, 1, 1), period_end=date(2026, 1, 1), dataset_id="test"
    )
    result = VertexSynthesizer(Settings()).synthesize("Test question", facts, [hit()])
    assert result.provider == "groq" and result.fallback_used
    calls = []

    def bad_citation(*args):
        calls.append(1)
        return CitedSynthesis(
            paragraphs=[CitedParagraph(text="Unsupported", cited_chunk_ids=["invented"])],
            insufficient_evidence=False,
        )

    monkeypatch.setattr(module, "compatible_completion", bad_citation)
    with pytest.raises(DomainError, match="citations"):
        VertexSynthesizer(Settings()).synthesize("Test question", facts, [hit()])
    assert len(calls) == 1


def test_paragraph_rendering_preserves_claim_level_citations():
    result = render_synthesis(
        CitedSynthesis(
            paragraphs=[
                CitedParagraph(
                    text="Synthetic supported statement.", cited_chunk_ids=[hit().chunk_id]
                )
            ],
            insufficient_evidence=False,
        ),
        [hit()],
    )
    assert result.answer == f"Synthetic supported statement. [{hit().chunk_id}]"
    assert result.cited_chunk_ids == [hit().chunk_id]
    for text, ids in [
        ("Uncited statement", []),
        ("Unknown source", ["invented"]),
        ("Hidden [invented] reference", [hit().chunk_id]),
    ]:
        with pytest.raises(DomainError):
            render_synthesis(
                CitedSynthesis(
                    paragraphs=[CitedParagraph(text=text, cited_chunk_ids=ids)],
                    insufficient_evidence=False,
                ),
                [hit()],
            )
