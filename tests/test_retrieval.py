from contextlib import closing
from datetime import date
from uuid import uuid4

import pytest
from pharmaguard.config import Settings
from pharmaguard.db import Dataset
from pharmaguard.errors import DomainError
from pharmaguard.retrieval import Retriever, collection_name, epoch, evidence_filter
from qdrant_client import QdrantClient, models

from ingestion.index import index_dataset
from ingestion.loader import load_documents
from tests.conftest import DATASET


class TestEmbedder:
    """Deterministic test-only vectors; never used by production embedding paths."""

    __test__ = False

    def encode(self, texts, *, article=False, titles=None):
        return [[1.0] + [0.0] * 767 for _ in texts]

    def rank(self, question, hits):
        return [float(len(hits) - index) for index in range(len(hits))]


def test_qdrant_filters_and_canonical_lookup(sessions):
    settings = Settings()
    docs = [
        {
            "source_type": "pubmed",
            "external_id": "test-only",
            "version": "1",
            "title": "Synthetic evidence",
            "text": "Synthetic test excerpt.",
            "source_date": date(2026, 1, 1),
            "available_at": date(2026, 2, 1),
            "url": "https://pubmed.ncbi.nlm.nih.gov/",
            "locator": "test",
            "checksum": "test",
            "raw_uri": "test",
        }
    ]
    with sessions.begin() as session:
        load_documents(session, DATASET, docs, "semaglutide", "pancreatitis")
    with closing(QdrantClient(":memory:")) as client:
        assert index_dataset(sessions, settings, client, TestEmbedder(), DATASET) == 1
        retriever = Retriever(settings, client, TestEmbedder())
        with sessions() as session:
            dataset = session.get(Dataset, DATASET)
            assert not retriever.search(session, dataset, "question", date(2026, 1, 20))
            assert len(retriever.search(session, dataset, "question", date(2026, 3, 1))) == 1
            assert not retriever.search(session, dataset, "question", date(2026, 3, 1), "other")
            client.upsert(
                collection_name(settings, DATASET),
                [
                    models.PointStruct(
                        id=str(uuid4()),
                        vector=[1.0] + [0.0] * 767,
                        payload={
                            "source_type": "pubmed",
                            "source_date": epoch(date(2026, 1, 1)),
                            "available_at": epoch(date(2026, 1, 1)),
                            "drug_id": "semaglutide",
                        },
                    )
                ],
            )
            with pytest.raises(DomainError, match="missing"):
                retriever.search(session, dataset, "question", date(2026, 3, 1))


def test_cutoff_filter_has_two_dates():
    filter_ = evidence_filter(date(2024, 1, 1), date(2026, 1, 1), ["pubmed"], "drug", "event")
    assert {condition.key for condition in filter_.must} == {
        "source_type",
        "source_date",
        "available_at",
        "drug_id",
        "event_id",
    }
