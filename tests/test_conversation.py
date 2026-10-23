from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from pharmaguard.config import Settings
from pharmaguard.conversation import (
    cache_key,
    contextual_request,
    investigate_session,
    issue_token,
    open_session,
    session_row,
    token_session,
)
from pharmaguard.db import ChatSession, EvidenceChunk
from pharmaguard.errors import DomainError
from pharmaguard.schemas import InvestigateRequest, Synthesis
from pydantic import SecretStr

from ingestion.loader import load_documents
from tests.conftest import DATASET
from tests.test_api import hit


@pytest.fixture
def settings():
    return Settings(sessions_enabled=True, session_signing_key=SecretStr("x" * 48))


def test_signed_expiring_scoped_tokens(settings):
    sid = str(uuid4())
    token = issue_token(sid, settings)
    assert token_session(token, settings) == sid
    expired = issue_token(sid, settings, datetime.now(UTC) - timedelta(hours=2))
    for invalid in [expired, token + "bad", "", jwt.encode({"sub": sid}, "x" * 48)]:
        with pytest.raises(DomainError, match="Start a new"):
            token_session(invalid, settings)
    with pytest.raises(DomainError):
        token_session(
            token, settings.model_copy(update={"session_signing_key": SecretStr("y" * 48)})
        )


def test_rotation_preserves_session_and_retention_cleanup(sessions, settings):
    with sessions() as session:
        body, token = open_session(session, None, settings)
        assert body["expires_in"] == 3600
        renewed, _ = open_session(session, token, settings)
        assert body["session_id"] == renewed["session_id"]
        row = session.get(ChatSession, body["session_id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
        with pytest.raises(DomainError):
            session_row(session, row.id)
        open_session(session, None, settings)
        assert session.get(ChatSession, row.id) is None


def test_cache_namespace_and_context(settings):
    request = InvestigateRequest(question="semaglutide pancreatitis")
    key = cache_key(request, DATASET, settings, [])
    for changed in [
        request.model_copy(update={"question": "Semaglutide pancreatitis"}),
        request.model_copy(update={"drug": "semaglutide"}),
    ]:
        assert cache_key(changed, DATASET, settings, []) != key
    assert cache_key(request, "other-dataset", settings, []) != key
    assert cache_key(request, DATASET, settings.model_copy(update={"git_sha": "new"}), []) != key
    assert cache_key(request, DATASET, settings, [{"question": "prior"}]) != key
    history = [{"drug": "semaglutide", "event": "pancreatitis", "cutoff_date": "2026-01-01"}]
    followup, context = contextual_request(
        InvestigateRequest(question="Does it cause harm?"), history
    )
    assert followup.drug == "semaglutide" and context == history
    independent, context = contextual_request(
        InvestigateRequest(question="tirzepatide risk"), history
    )
    assert independent.drug is None and context == []


def test_cache_avoids_model_and_rejects_canonical_changes(sessions, settings):
    with sessions.begin() as session:
        load_documents(
            session,
            DATASET,
            [
                {
                    "source_type": "pubmed",
                    "external_id": "cache-test",
                    "version": "1",
                    "title": "Test fixture",
                    "text": "Test evidence",
                    "source_date": hit().source_date,
                    "available_at": hit().available_at,
                    "url": hit().url,
                    "checksum": "test",
                    "raw_uri": "test",
                    "locator": "test",
                }
            ],
            "semaglutide",
            "pancreatitis",
        )
    from pharmaguard.db import SourceDocument
    from sqlalchemy import select

    with sessions() as session:
        chunk = session.scalar(select(EvidenceChunk))
        doc = session.get(SourceDocument, chunk.document_id)
        evidence = hit().model_copy(
            update={"chunk_id": chunk.id, "document_id": doc.id, "locator": chunk.locator}
        )
        _, token = open_session(session, None, settings)
        _, other = open_session(session, None, settings)

    class Retriever:
        def search(self, *args):
            return [evidence]

    class Synthesizer:
        calls = 0

        def synthesize(self, *args, **kwargs):
            self.calls += 1
            return Synthesis(
                answer=f"Test evidence [{evidence.chunk_id}]", cited_chunk_ids=[evidence.chunk_id]
            )

    synthesizer = Synthesizer()
    request = InvestigateRequest(question="semaglutide pancreatitis")
    with sessions() as session:
        first = investigate_session(
            request, "one", token, session, settings, Retriever(), synthesizer
        )
        second = investigate_session(
            request, "two", token, session, settings, Retriever(), synthesizer
        )
        assert first.cache_status == "miss" and second.cache_status == "hit"
        assert second.request_id == "two" and synthesizer.calls == 1
        investigate_session(request, "three", other, session, settings, Retriever(), synthesizer)
        assert synthesizer.calls == 2
        for _ in range(6):
            investigate_session(
                request, "repeat", token, session, settings, Retriever(), synthesizer
            )
        row = session.get(ChatSession, token_session(token, settings))
        assert len(row.history) == 5
        session.get(EvidenceChunk, evidence.chunk_id).text = "Changed canonical text"
        session.commit()
        # A deleted or changed canonical chunk invalidates cached text, never serves it silently.
        from pharmaguard.conversation import validate_cached

        assert not validate_cached(session, second, settings)
        row.answers = [{**item, "expires": 0} for item in row.answers]
        session.commit()
        investigate_session(request, "expired", token, session, settings, Retriever(), synthesizer)
        assert synthesizer.calls == 3


def test_log_allowlist_and_no_prompt_leaks(caplog):
    from pharmaguard.observability import event

    with pytest.raises(ValueError):
        event("unsafe", question="private user prompt")
    with caplog.at_level("INFO"):
        event("answer_cache", cache_status="hit", request_id="safe-id")
    assert '"cache_status": "hit"' in caplog.text
    assert "private user prompt" not in caplog.text


def test_dailymed_version_link():
    from pharmaguard.source_links import readable_source_url

    value = "https://dailymed.nlm.nih.gov/dailymed/getFile.cfm?type=zip&setid=abc&version=17"
    assert readable_source_url(value).endswith("drugInfo.cfm?setid=abc&version=17")
    assert readable_source_url("https://untrusted.example/getFile.cfm") == (
        "https://untrusted.example/getFile.cfm"
    )


def test_session_api_requires_token(sessions, settings):
    from fastapi.testclient import TestClient
    from pharmaguard.main import create_app

    app = create_app(settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        app.state.sessions = sessions
        response = client.post("/session")
        assert response.status_code == 200
        token = response.headers["X-Session-Token"]
        assert "token" not in response.text
        assert (
            client.post("/session", headers={"X-Session-Token": token}).json()["session_id"]
            == (response.json()["session_id"])
        )
        assert client.post("/investigate", json={"question": "test question"}).status_code == 401
