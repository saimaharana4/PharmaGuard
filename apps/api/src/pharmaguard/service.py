import json
import logging
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from pharmaguard.config import Settings
from pharmaguard.db import ActiveDataset, Dataset
from pharmaguard.errors import DomainError
from pharmaguard.retrieval import Retriever, collection_name
from pharmaguard.schemas import (
    DataWindow,
    InvestigateRequest,
    InvestigateResponse,
    RetrievalMetadata,
    Synthesis,
)
from pharmaguard.signals import resolve_entity, signal_facts
from pharmaguard.synthesis import VertexSynthesizer


def active_dataset(session: Session) -> Dataset:
    dataset = session.scalar(
        select(Dataset)
        .join(
            ActiveDataset,
            ActiveDataset.dataset_id == Dataset.id,
        )
        .where(ActiveDataset.id == 1, Dataset.status == "ready")
    )
    if dataset is None:
        raise DomainError(
            "DATASET_NOT_READY", "No fully ingested and indexed dataset is published."
        )
    return dataset


def investigate(
    request: InvestigateRequest,
    request_id: str,
    session: Session,
    settings: Settings,
    retriever: Retriever,
    synthesizer: VertexSynthesizer,
    history: list | None = None,
) -> InvestigateResponse:
    started = perf_counter()
    dataset = active_dataset(session)
    cutoff = request.cutoff_date or dataset.as_of_date
    if cutoff < dataset.window_start or cutoff > dataset.as_of_date:
        raise DomainError(
            "INVALID_CUTOFF", "Cutoff must be within the published dataset window.", 422
        )
    drug = resolve_entity(session, "drug", request.drug, request.question)
    event = resolve_entity(session, "event", request.event, request.question)
    # Unknown explicit filters must never silently broaden retrieval.
    if (request.drug and not drug) or (request.event and not event):
        raise DomainError(
            "UNKNOWN_ENTITY", "A filter is unknown or ambiguous. Use a canonical name.", 422
        )
    retrieval_question = request.question
    if history:
        retrieval_question += f"\nInvestigation context: {drug or ''} / {event or ''}"
    facts, facts_ms = None, 0.0

    def calculate_facts():
        nonlocal facts, facts_ms
        facts_started = perf_counter()
        facts = signal_facts(session, dataset, cutoff, drug, event)
        facts_ms = round((perf_counter() - facts_started) * 1000, 2)

    retrieval_started = perf_counter()
    search_and_run = getattr(retriever, "search_and_run", None)
    if callable(search_and_run):
        hits = search_and_run(
            session, dataset, retrieval_question, cutoff, drug, event, work=calculate_facts
        )
    else:
        calculate_facts()
        retrieval_started = perf_counter()
        hits = retriever.search(session, dataset, retrieval_question, cutoff, drug, event)
    if facts is None:
        raise RuntimeError("Evidence preparation did not calculate deterministic facts")
    retrieval_done = perf_counter()
    warnings = ["Spontaneous-reporting signals do not establish causality. Not medical advice."]
    if history:
        warnings.append(
            f"Follow-up context: {drug or 'unresolved drug'} / "
            f"{event or 'unresolved event'}; evidence cutoff {cutoff}."
        )
    if facts.reason:
        warnings.append(facts.reason)
    warnings.extend(dataset.coverage.get("warnings", []))
    result = (
        (
            synthesizer.synthesize(request.question, facts, hits, history=history)
            if history
            else synthesizer.synthesize(request.question, facts, hits)
        )
        if hits
        else Synthesis(
            answer="Insufficient qualifying evidence within the selected data window.",
            cited_chunk_ids=[],
            insufficient_evidence=True,
        )
    )
    config = settings.retrieval()
    logging.getLogger("pharmaguard").info(
        json.dumps(
            {
                "event": "investigation_stages",
                "request_id": request_id,
                "dataset_id": dataset.id,
                "facts_ms": facts_ms,
                "retrieval_ms": round((retrieval_done - retrieval_started) * 1000, 2),
                "prepare_ms": round((retrieval_done - started) * 1000, 2),
                "synthesis_ms": round((perf_counter() - retrieval_done) * 1000, 2),
            }
        )
    )
    return InvestigateResponse(
        request_id=request_id,
        answer=result.answer,
        facts=facts,
        citations=[hit for hit in hits if hit.chunk_id in result.cited_chunk_ids],
        retrieved_evidence_ids=[hit.chunk_id for hit in hits],
        retrieved_evidence=hits,
        retrieval=RetrievalMetadata(
            top_k=config.top_k,
            returned=len(hits),
            collection=collection_name(settings, dataset.id),
            config_version=config.version,
            query_model_revision=settings.embedding_query_revision,
        ),
        data_window=DataWindow(
            lookback_months=settings.lookback_months,
            window_start=dataset.window_start,
            as_of_date=dataset.as_of_date,
            cutoff_date=cutoff,
            dataset_id=dataset.id,
            coverage=dataset.coverage,
        ),
        warnings=warnings,
        insufficient_evidence=result.insufficient_evidence,
        synthesis={
            "provider": result.provider,
            "model": result.model,
            "fallback_used": result.fallback_used,
        },
    )
