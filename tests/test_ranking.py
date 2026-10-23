from datetime import date

import pytest
from pharmaguard.config import RetrievalConfig
from pharmaguard.db import Dataset, EvidenceChunk, SourceDocument
from pharmaguard.ranking import canonical_hit, rank_context, warning_anchor
from sqlalchemy import select

from ingestion.loader import load_documents
from tests.conftest import DATASET
from tests.test_retrieval import TestEmbedder


def document(version, source="pubmed", published=date(2026, 1, 1)):
    return {
        "source_type": source,
        "external_id": "synthetic-ranking-test",
        "version": version,
        "title": "WEGOVY synthetic label" if source == "dailymed" else "Synthetic study",
        "text": "5.2 Acute Pancreatitis\nSynthetic observed warning, not real medical evidence.",
        "source_date": published,
        "available_at": published,
        "url": "https://dailymed.nlm.nih.gov/"
        if source == "dailymed"
        else "https://pubmed.ncbi.nlm.nih.gov/",
        "locator": "test-only",
        "checksum": "test-only",
        "raw_uri": "test-only",
    }


def test_warning_anchor_respects_cutoff_and_explicit_brand(sessions):
    with sessions.begin() as session:
        load_documents(
            session,
            DATASET,
            [
                document("old", "dailymed"),
                document("future", "dailymed", date(2026, 9, 1)),
            ],
            "semaglutide",
            "pancreatitis",
        )
    with sessions() as session:
        dataset = session.get(Dataset, DATASET)
        args = ("semaglutide", "pancreatitis", ["dailymed", "pubmed"])
        past = warning_anchor(session, dataset, "semaglutide pancreatitis", date(2026, 6, 1), *args)
        now = warning_anchor(session, dataset, "semaglutide pancreatitis", date(2026, 10, 1), *args)
        assert past.available_at == date(2026, 1, 1)
        assert now.available_at == date(2026, 9, 1)
        # The reviewed Ozempic alias cannot silently select a different named formulation.
        assert (
            warning_anchor(session, dataset, "Ozempic pancreatitis", date(2026, 6, 1), *args)
            is None
        )


def test_abstract_context_preserves_top_k_budget(sessions):
    doc = document("context")
    doc["text"] = "Methods " + "m" * 800 + "\n\nResults " + "r" * 800
    with sessions.begin() as session:
        load_documents(session, DATASET, [doc], "semaglutide", "pancreatitis")
    with sessions() as session:
        rows = session.execute(select(EvidenceChunk, SourceDocument).join(SourceDocument)).all()
        assert len(rows) == 2
        best = canonical_hit(*rows[-1], "dense")
        dataset = session.get(Dataset, DATASET)

        def retrieve(k):
            return rank_context(
                session,
                dataset,
                "Synthetic question",
                date(2026, 6, 1),
                None,
                None,
                [best],
                TestEmbedder(),
                RetrievalConfig(version="test", top_k=k),
            )

        assert {hit.chunk_id for hit in retrieve(5)} == {row[0].id for row in rows}
        assert len(retrieve(1)) == 1


def test_availability_correction_cannot_mutate_published_evidence(sessions):
    doc = document("availability")
    with sessions.begin() as session:
        session.get(Dataset, DATASET).status = "loading"
        load_documents(session, DATASET, [doc], "semaglutide", "pancreatitis")
    doc["available_at"] = date(2026, 3, 1)
    with sessions.begin() as session:
        load_documents(session, DATASET, [doc], "semaglutide", "pancreatitis")
        session.get(Dataset, DATASET).status = "ready"
    doc["available_at"] = date(2026, 4, 1)
    with pytest.raises(ValueError, match="immutable"), sessions.begin() as session:
        load_documents(session, DATASET, [doc], "semaglutide", "pancreatitis")
    with sessions() as session:
        assert session.scalar(select(SourceDocument)).available_at == date(2026, 3, 1)
