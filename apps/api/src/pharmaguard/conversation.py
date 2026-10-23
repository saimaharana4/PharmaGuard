"""PostgreSQL-backed, session-isolated five-exchange memory and exact-answer cache."""

import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from pharmaguard.config import Settings
from pharmaguard.db import ChatSession, DatasetChunk, EvidenceChunk, SourceDocument
from pharmaguard.errors import DomainError
from pharmaguard.observability import event
from pharmaguard.schemas import InvestigateRequest, InvestigateResponse, Synthesis
from pharmaguard.service import active_dataset, investigate
from pharmaguard.source_links import readable_source_url
from pharmaguard.synthesis import validate_citations

ISSUER = "pharmaguard-anonymous-session"
AUDIENCE = "pharmaguard-chat"
HISTORY_LIMIT = 5


def signing_key(settings: Settings) -> str:
    key = settings.session_signing_key.get_secret_value()
    if len(key.encode()) < 32:
        raise RuntimeError("Session signing requires at least 32 bytes from Secret Manager")
    return key


def issue_token(sid: str, settings: Settings, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return jwt.encode(
        {
            "sub": sid,
            "iat": now,
            "exp": now + timedelta(seconds=settings.session_ttl_seconds),
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        signing_key(settings),
        algorithm="HS256",
    )


def token_session(token: str, settings: Settings) -> str:
    try:
        claims = jwt.decode(
            token,
            signing_key(settings),
            algorithms=["HS256"],
            issuer=ISSUER,
            audience=AUDIENCE,
            options={"require": ["sub", "iat", "exp", "iss", "aud"]},
        )
        return str(UUID(claims["sub"]))
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        raise DomainError("SESSION_EXPIRED", "Start a new anonymous session.", 401) from None


def session_row(session: Session, sid: str, *, lock: bool = False) -> ChatSession:
    query = select(ChatSession).where(ChatSession.id == sid)
    try:
        row = session.scalar(query.with_for_update(nowait=True) if lock else query)
    except OperationalError as exc:
        if getattr(exc.orig, "sqlstate", None) == "55P03":
            raise DomainError(
                "SESSION_BUSY", "A question is already running in this session.", 409
            ) from None
        raise
    if not row or row.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise DomainError("SESSION_EXPIRED", "Start a new anonymous session.", 401)
    return row


def open_session(session: Session, token: str | None, settings: Settings) -> tuple[dict, str]:
    now = datetime.now(UTC)
    # Opportunistic retention cleanup, also available as a scheduled maintenance command.
    session.execute(delete(ChatSession).where(ChatSession.expires_at <= now))
    if token:
        row = session_row(session, token_session(token, settings))
    else:
        if session.bind.dialect.name == "postgresql":
            # Serialize the small admission check across replicas, never across investigations.
            session.execute(text("SELECT pg_advisory_xact_lock(73191421)"))
        if session.scalar(select(func.count()).select_from(ChatSession)) >= 1000:
            raise DomainError("SESSION_CAPACITY", "Anonymous session capacity is full.", 429)
        row = ChatSession(
            id=str(uuid4()),
            history=[],
            answers=[],
            expires_at=now + timedelta(seconds=settings.session_retention_seconds),
        )
        session.add(row)
    session.commit()
    return {
        "enabled": True,
        "session_id": row.id,
        "history_count": len(row.history),
        "history": [
            {"question": item["question"], "answer": item["answer"]} for item in row.history
        ],
        "expires_in": settings.session_ttl_seconds,
    }, issue_token(row.id, settings)


def contextual_request(
    request: InvestigateRequest, history: list
) -> tuple[InvestigateRequest, list]:
    # Only explicit anaphoric follow-ups inherit a pair. New questions stay independent.
    followup = bool(
        re.match(
            r"^(does it\b|why (is that|so)\b|explain that\b|tell me more\b|"
            r"what about (its|their|that)\b)",
            request.question,
            re.IGNORECASE,
        )
    )
    if not followup or not history:
        return request, []
    previous = history[-1]
    resolved = request.model_dump()
    resolved.update(
        {
            "drug": request.drug or previous["drug"],
            "event": request.event or previous["event"],
            "cutoff_date": request.cutoff_date or previous["cutoff_date"],
        }
    )
    effective = InvestigateRequest.model_validate(resolved)
    context = [
        item
        for item in history
        if item["drug"] == effective.drug
        and item["event"] == effective.event
        and item["cutoff_date"] == str(effective.cutoff_date)
    ]
    return effective, context[-HISTORY_LIMIT:]


def cache_key(
    request: InvestigateRequest, dataset_id: str, settings: Settings, context: list
) -> str:
    value = {
        "request": request.model_dump(mode="json"),
        "context": context,
        "dataset": dataset_id,
        "retrieval": settings.retrieval().model_dump(),
        "query_revision": settings.embedding_query_revision,
        "article_revision": settings.embedding_document_revision,
        "reranker_revision": settings.reranker_revision,
        "models": [settings.llm_model, settings.groq_model, settings.openai_model],
        "fallbacks": settings.fallback_providers,
        "source": settings.git_sha,
        "contract": "session-cache-v1",
    }
    # Exact questions only: punctuation, case and temporal wording can change meaning.
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def validate_cached(session: Session, result: InvestigateResponse, settings: Settings) -> bool:
    """A cache entry cannot override canonical deletion, source edits or cutoff eligibility."""
    cutoff = result.data_window.cutoff_date
    for hit in result.retrieved_evidence:
        row = session.execute(
            select(EvidenceChunk, SourceDocument)
            .join(SourceDocument)
            .join(DatasetChunk, DatasetChunk.chunk_id == EvidenceChunk.id)
            .where(
                EvidenceChunk.id == hit.chunk_id,
                DatasetChunk.dataset_id == result.data_window.dataset_id,
            )
        ).first()
        if not row:
            return False
        chunk, doc = row
        if (
            chunk.text != hit.text
            or doc.id != hit.document_id
            or doc.title != hit.title
            or chunk.locator != hit.locator
            or doc.source_date != hit.source_date
            or doc.available_at != hit.available_at
            or doc.source_type != hit.source_type
            or readable_source_url(doc.url) != readable_source_url(hit.url)
            or doc.source_type not in settings.retrieval().allowed_sources
            or not result.data_window.window_start <= doc.source_date <= cutoff
            or doc.available_at > cutoff
        ):
            return False
    validate_citations(
        Synthesis(
            answer=result.answer,
            cited_chunk_ids=[hit.chunk_id for hit in result.citations],
            insufficient_evidence=result.insufficient_evidence,
        ),
        result.retrieved_evidence,
    )
    return True


def remember(row: ChatSession, request: InvestigateRequest, result: InvestigateResponse) -> None:
    exchange = {
        "question": request.question,
        "answer": result.answer,
        "drug": result.facts.drug,
        "event": result.facts.event,
        "cutoff_date": str(result.data_window.cutoff_date),
    }
    row.history = [*row.history, exchange][-HISTORY_LIMIT:]


def investigate_session(request, request_id, token, session, settings, retriever, synthesizer):
    sid = token_session(token or "", settings)
    row = session_row(session, sid, lock=True)
    effective, context = contextual_request(request, row.history)
    dataset = active_dataset(session)
    key = cache_key(effective, dataset.id, settings, context)
    now = datetime.now(UTC).timestamp()
    row.answers = [item for item in row.answers if item["expires"] > now]
    for item in row.answers:
        if item["key"] == key:
            result = InvestigateResponse.model_validate(item["response"])
            if validate_cached(session, result, settings):
                result = result.model_copy(
                    update={"request_id": request_id, "session_id": sid, "cache_status": "hit"}
                )
                remember(row, effective, result)
                session.commit()
                event(
                    "answer_cache",
                    request_id=request_id,
                    session_id=sid,
                    dataset_id=dataset.id,
                    cache_status="hit",
                    count=len(row.history),
                )
                return result
    result = investigate(
        effective, request_id, session, settings, retriever, synthesizer, history=context
    )
    result = result.model_copy(update={"session_id": sid, "cache_status": "miss"})
    remember(row, effective, result)
    # Abstentions are cheap and may hide a transient coverage gap; never cache failures.
    if not result.insufficient_evidence:
        row.answers = [
            *row.answers,
            {
                "key": key,
                "expires": now + settings.answer_cache_seconds,
                "response": result.model_dump(mode="json"),
            },
        ][-HISTORY_LIMIT:]
    session.commit()
    event(
        "answer_cache",
        request_id=request_id,
        session_id=sid,
        dataset_id=dataset.id,
        cache_status="miss",
        count=len(row.history),
    )
    return result
