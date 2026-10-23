"""Run against real PostgreSQL/Qdrant: RUN_INTEGRATION=1 uv run pytest -m integration."""

import os
from contextlib import closing
from datetime import date
from uuid import uuid4

import pytest
from pharmaguard.config import load_settings
from pharmaguard.db import (
    Base,
    Dataset,
    DatasetChunk,
    EvidenceChunk,
    SourceDocument,
    session_factory,
)
from pharmaguard.retrieval import Retriever, collection_name, qdrant_client
from sqlalchemy import select

from ingestion.index import index_dataset
from ingestion.loader import load_documents
from tests.test_retrieval import TestEmbedder

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("RUN_INTEGRATION") != "1",
        reason="Set RUN_INTEGRATION=1 with PostgreSQL/Qdrant running",
    ),
]


def test_real_postgres_and_qdrant():
    settings = load_settings()
    sessions = session_factory(settings)
    assert sessions.kw["bind"].dialect.name == "postgresql"
    from sqlalchemy import inspect

    assert set(Base.metadata.tables) <= set(inspect(sessions.kw["bind"]).get_table_names())
    dataset_id = str(uuid4())
    with sessions.begin() as session:
        session.add(
            Dataset(
                id=dataset_id,
                status="loading",
                window_start=date(2024, 1, 1),
                as_of_date=date(2026, 1, 1),
                coverage={},
                model_revision="test-only",
            )
        )
    docs = [
        {
            "source_type": "pubmed",
            "external_id": str(uuid4()),
            "version": "test-only",
            "title": "Synthetic integration fixture",
            "text": "Synthetic evidence for integration tests.",
            "source_date": date(2025, 1, 1),
            "available_at": date(2025, 1, 1),
            "url": "https://pubmed.ncbi.nlm.nih.gov/",
            "locator": "test-only",
            "checksum": "test-only",
            "raw_uri": "test-only",
        }
    ]
    with closing(qdrant_client(settings)) as client:
        try:
            for _ in range(2):
                with sessions.begin() as session:
                    load_documents(session, dataset_id, docs, "test-drug", "test-event")
                assert index_dataset(sessions, settings, client, TestEmbedder(), dataset_id) == 1
            with sessions() as session:
                hits = Retriever(settings, client, TestEmbedder()).search(
                    session, session.get(Dataset, dataset_id), "test", date(2026, 1, 1)
                )
                assert len(hits) == 1
        finally:
            if client.collection_exists(collection_name(settings, dataset_id)):
                client.delete_collection(collection_name(settings, dataset_id))
            with sessions.begin() as session:
                ids = list(
                    session.scalars(
                        select(DatasetChunk.chunk_id).where(DatasetChunk.dataset_id == dataset_id)
                    )
                )
                doc_ids = list(
                    session.scalars(
                        select(EvidenceChunk.document_id).where(EvidenceChunk.id.in_(ids))
                    )
                )
                for model, condition in [
                    (DatasetChunk, DatasetChunk.dataset_id == dataset_id),
                    (EvidenceChunk, EvidenceChunk.id.in_(ids)),
                    (SourceDocument, SourceDocument.id.in_(doc_ids)),
                    (Dataset, Dataset.id == dataset_id),
                ]:
                    session.query(model).filter(condition).delete(synchronize_session=False)


def test_real_session_lock_and_isolation():
    from datetime import UTC, datetime, timedelta

    from pharmaguard.conversation import session_row
    from pharmaguard.db import ChatSession
    from pharmaguard.errors import DomainError

    sessions = session_factory(load_settings())
    sid = str(uuid4())
    try:
        with sessions.begin() as session:
            session.add(
                ChatSession(
                    id=sid,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                    history=[],
                    answers=[],
                )
            )
        with sessions() as first, sessions() as second:
            assert session_row(first, sid, lock=True).id == sid
            with pytest.raises(DomainError) as error:
                session_row(second, sid, lock=True)
            assert error.value.code == "SESSION_BUSY"
    finally:
        with sessions.begin() as session:
            session.query(ChatSession).filter(ChatSession.id == sid).delete()
        sessions.kw["bind"].dispose()
