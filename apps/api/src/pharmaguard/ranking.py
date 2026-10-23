"""Bounded semantic reranking, source context, and explicit regulatory warning coverage."""

import math
import re
from collections import Counter

from sqlalchemy import select

from pharmaguard.db import DatasetChunk, Entity, EvidenceChunk, SourceDocument
from pharmaguard.schemas import EvidenceHit
from pharmaguard.signals import normalize
from pharmaguard.source_links import readable_source_url


def lexical_order(question: str, hits: list[EvidenceHit]) -> list[int]:
    """BM25 supplies exact-term candidates alongside dense biomedical candidates."""

    def tokens(value):
        return re.findall(r"[a-z0-9]+", value.lower())

    documents = [Counter(tokens(hit.title + " " + hit.text)) for hit in hits]
    frequencies = Counter(term for document in documents for term in document)
    average = sum(sum(document.values()) for document in documents) / max(len(documents), 1)
    scores = []
    for document in documents:
        length, score = sum(document.values()), 0.0
        for term in set(tokens(question)):
            count = document[term]
            if count:
                inverse = math.log(
                    1 + (len(hits) - frequencies[term] + 0.5) / (frequencies[term] + 0.5)
                )
                score += inverse * count * 2.5 / (count + 1.5 * (0.25 + 0.75 * length / average))
        scores.append(score)
    return sorted(range(len(hits)), key=lambda index: (-scores[index], index))


def canonical_hit(chunk, doc, method: str) -> EvidenceHit:
    return EvidenceHit(
        chunk_id=chunk.id,
        document_id=doc.id,
        score=0,
        rank=0,
        source_type=doc.source_type,
        source_date=doc.source_date,
        available_at=doc.available_at,
        title=doc.title,
        locator=chunk.locator,
        polarity=chunk.polarity,
        text=chunk.text,
        url=readable_source_url(doc.url),
        retrieval_method=method,
    )


def source_rows(session, dataset, cutoff, drug, event):
    statement = (
        select(EvidenceChunk, SourceDocument)
        .join(SourceDocument)
        .join(DatasetChunk, DatasetChunk.chunk_id == EvidenceChunk.id)
        .where(
            DatasetChunk.dataset_id == dataset.id,
            SourceDocument.source_date >= dataset.window_start,
            SourceDocument.source_date <= cutoff,
            SourceDocument.available_at <= cutoff,
        )
    )
    if drug:
        statement = statement.where(EvidenceChunk.drug_id == drug)
    if event:
        statement = statement.where(EvidenceChunk.event_id == event)
    return statement


def warning_anchor(session, dataset, question, cutoff, drug, event, allowed_sources):
    if not drug or not event or "dailymed" not in allowed_sources:
        return None
    entity = session.get(Entity, ("event", event))
    aliases = {normalize(value) for value in [event, *(entity.aliases if entity else [])]}
    drug_entity = session.get(Entity, ("drug", drug))
    mentioned = [
        alias
        for alias in (drug_entity.aliases if drug_entity else [])
        if re.search(rf"\b{re.escape(normalize(alias))}\b", normalize(question))
    ]
    rows = session.execute(
        source_rows(session, dataset, cutoff, drug, event)
        .where(
            SourceDocument.source_type == "dailymed", EvidenceChunk.text.ilike("%" + event + "%")
        )
        .order_by(
            SourceDocument.available_at.desc(), SourceDocument.source_date.desc(), EvidenceChunk.id
        )
        .limit(200)
    )
    for chunk, doc in rows:
        if mentioned and not any(normalize(alias) in normalize(doc.title) for alias in mentioned):
            continue
        headings = re.findall(r"(?:^|\s)\d+\.\d+[ \t]+([^\n]+)", chunk.text)
        if any(normalize(heading) in aliases for heading in headings):
            return canonical_hit(chunk, doc, "label_warning")
    return None


def rank_context(session, dataset, question, cutoff, drug, event, hits, embedder, config):
    if not hits:
        return []
    lexical = lexical_order(question, hits)
    half = config.rerank_candidates // 2
    indices = list(dict.fromkeys([*range(min(half, len(hits))), *lexical[:half]]))
    candidates = [hits[index] for index in indices]
    scores = embedder.rank(question, candidates)
    if len(scores) != len(candidates) or any(not math.isfinite(score) for score in scores):
        raise ValueError("Invalid reranker output")
    ranked = sorted(
        [
            hit.model_copy(update={"rerank_score": score, "retrieval_method": "reranked"})
            for hit, score in zip(candidates, scores, strict=True)
        ],
        key=lambda hit: (-hit.rerank_score, -hit.score, hit.chunk_id),
    )
    selected = [ranked[0]]

    def add(hit):
        if len(selected) < config.top_k and all(x.chunk_id != hit.chunk_id for x in selected):
            selected.append(hit)

    # Reserve a safety-warning context slot when an eligible named label section exists.
    if config.top_k > 1:
        anchor = warning_anchor(
            session, dataset, question, cutoff, drug, event, config.allowed_sources
        )
        if anchor:
            add(anchor)
    best = ranked[0]
    if best.source_type == "pubmed":
        rows = list(
            session.execute(
                source_rows(session, dataset, cutoff, drug, event).where(
                    SourceDocument.id == best.document_id
                )
            )
        )

        def number(chunk):
            return int(chunk.locator.rsplit("-", 1)[-1])

        rows.sort(key=lambda row: (abs(number(row[0]) - number(best)), number(row[0])))
        for chunk, doc in rows[: config.abstract_context_chunks]:
            add(canonical_hit(chunk, doc, "abstract_context"))
    for hit in ranked:
        add(hit)
    return [hit.model_copy(update={"rank": index + 1}) for index, hit in enumerate(selected)]
