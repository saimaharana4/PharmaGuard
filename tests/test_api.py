from datetime import date

import pytest
from fastapi.testclient import TestClient
from pharmaguard.config import Settings
from pharmaguard.errors import DomainError
from pharmaguard.main import create_app
from pharmaguard.schemas import EvidenceHit, Synthesis
from pharmaguard.synthesis import validate_citations


def hit() -> EvidenceHit:
    return EvidenceHit(
        chunk_id="33333333-3333-4333-8333-333333333333",
        document_id="test",
        score=1,
        rank=1,
        source_type="pubmed",
        source_date=date(2026, 1, 1),
        available_at=date(2026, 1, 1),
        title="Test fixture",
        locator="test",
        polarity="context",
        text="Test evidence",
        url="https://pubmed.ncbi.nlm.nih.gov/",
    )


@pytest.mark.parametrize(
    "result",
    [
        Synthesis(answer="Unsupported [unknown]", cited_chunk_ids=["unknown"]),
        Synthesis(answer="No citations.", cited_chunk_ids=[]),
        Synthesis(answer="Mismatched [unknown]", cited_chunk_ids=[hit().chunk_id]),
        Synthesis(
            answer=f"Evidence [{hit().chunk_id}]. Hidden [invented citation].",
            cited_chunk_ids=[hit().chunk_id],
        ),
    ],
)
def test_citation_rejection(result):
    with pytest.raises(DomainError):
        validate_citations(result, [hit()])


def test_valid_citation():
    validate_citations(
        Synthesis(answer=f"Test evidence [{hit().chunk_id}]", cited_chunk_ids=[hit().chunk_id]),
        [hit()],
    )


class EmptyRetriever:
    def search(self, *args, **kwargs):
        return []


class UnavailableRetriever:
    def search(self, *args, **kwargs):
        raise DomainError("RETRIEVAL_UNAVAILABLE", "Evidence retrieval is unavailable.")


def test_api_contract_abstention_and_validation(sessions):
    app = create_app(Settings())
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.sessions = sessions
        app.state.retriever = EmptyRetriever()
        assert client.get("/health").json() == {"status": "ok"}
        assert "db_password" not in str(client.get("/version").json())
        result = client.post("/investigate", json={"question": "semaglutide pancreatitis"})
        assert result.status_code == 200
        assert result.json()["insufficient_evidence"]
        assert result.json()["citations"] == []
        assert result.headers["X-Request-ID"] == result.json()["request_id"]
        assert client.post("/investigate", json={"question": " "}).status_code == 422
        assert (
            client.post(
                "/investigate", json={"question": "abc", "cutoff_date": "2099-01-01"}
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/investigate", json={"question": "abc", "drug": "unrecognized"}
            ).status_code
            == 422
        )
        app.state.retriever = UnavailableRetriever()
        failure = client.post("/investigate", json={"question": "semaglutide pancreatitis"})
        assert failure.status_code == 503
        assert failure.json()["error"]["request_id"]
        assert "Traceback" not in failure.text
