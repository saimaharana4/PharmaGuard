"""MedCPT embedding and filtered Qdrant retrieval with canonical integrity checks."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, time, timedelta
from threading import Lock
from time import perf_counter

from qdrant_client import QdrantClient, models
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from pharmaguard.config import Settings
from pharmaguard.db import Dataset, DatasetChunk, EvidenceChunk, SourceDocument
from pharmaguard.errors import DomainError
from pharmaguard.observability import event as log_event
from pharmaguard.schemas import EvidenceHit
from pharmaguard.source_links import readable_source_url

EMBEDDING_INPUT_VERSION = "medcpt-title-body-v2"


def collection_name(settings: Settings, dataset_id: str) -> str:
    # A staging ingestion never mutates the active dataset's searchable collection.
    return f"{settings.qdrant_collection}_{dataset_id.replace('-', '')}"


def qdrant_client(settings: Settings) -> QdrantClient:
    key = settings.qdrant_api_key.get_secret_value()
    if not key and settings.qdrant_secret_version:
        import base64
        import re

        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        resource = settings.qdrant_secret_version
        if not re.fullmatch(r"projects/[\w-]+/secrets/[\w-]+/versions/\d+", resource):
            raise ValueError("QDRANT_SECRET_VERSION must identify a pinned Secret Manager version")
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        with AuthorizedSession(credentials) as session:
            response = session.get(
                f"https://secretmanager.googleapis.com/v1/{resource}:access", timeout=15
            )
            response.raise_for_status()
            key = base64.b64decode(response.json()["payload"]["data"]).decode()
    return QdrantClient(
        url=settings.qdrant_url,
        api_key=key or None,
        timeout=15,
        check_compatibility=False,
    )


class MedCPT:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._models: dict = {}
        self._lock = Lock()

    def encode(
        self, texts: list[str], *, article: bool = False, titles: list[str] | None = None
    ) -> list[list[float]]:
        import torch
        from transformers import AutoModel, AutoTokenizer

        kind = "Article" if article else "Query"
        with self._lock:
            if kind not in self._models:
                revision = (
                    self.settings.embedding_document_revision
                    if article
                    else self.settings.embedding_query_revision
                )
                name = (
                    self.settings.embedding_document_model
                    if article
                    else self.settings.embedding_query_model
                )
                tokenizer = AutoTokenizer.from_pretrained(name, revision=revision)
                model = AutoModel.from_pretrained(name, revision=revision, use_safetensors=True)
                model.eval()
                self._models[kind] = tokenizer, model
            tokenizer, model = self._models[kind]
        # Title/body pairs follow the article model's input convention.
        if titles is not None and (not article or len(titles) != len(texts)):
            raise ValueError("Article titles must correspond one-to-one with article bodies")
        inputs = (
            [[title, text] for title, text in zip(titles or [""] * len(texts), texts, strict=True)]
            if article
            else texts
        )
        tokens = tokenizer(
            inputs,
            padding=True,
            truncation=True,
            max_length=512 if article else 64,
            return_tensors="pt",
        )
        with torch.inference_mode():
            vectors = model(**tokens).last_hidden_state[:, 0, :]
        if vectors.shape[1] != 768:
            raise DomainError("EMBEDDING_DIMENSION", "Unexpected embedding dimension.", 500)
        return vectors.tolist()

    def rank(self, question: str, hits: list[EvidenceHit]) -> list[float]:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        with self._lock:
            if "Cross" not in self._models:
                tokenizer = AutoTokenizer.from_pretrained(
                    self.settings.reranker_model, revision=self.settings.reranker_revision
                )
                model = AutoModelForSequenceClassification.from_pretrained(
                    self.settings.reranker_model,
                    revision=self.settings.reranker_revision,
                    use_safetensors=False,
                    weights_only=True,
                    trust_remote_code=False,
                ).eval()
                self._models["Cross"] = tokenizer, model
            tokenizer, model = self._models["Cross"]
        if not hits:
            return []
        # Preserve every candidate and the same tokens. Group by encoded length so short
        # abstracts do not pay for padding to long label sections in every CPU batch.
        encoded = tokenizer(
            [[question, hit.title + " " + hit.text] for hit in hits],
            padding=False,
            truncation=True,
            max_length=384,
        )
        # Archived versions can produce identical model inputs. Infer each input once,
        # then scatter its score back to every original candidate in the same order.
        representatives: dict[tuple, int] = {}
        owners = []
        for index in range(len(hits)):
            key = tuple((name, tuple(values[index])) for name, values in sorted(encoded.items()))
            owners.append(representatives.setdefault(key, index))
        order = sorted(
            representatives.values(),
            key=lambda index: (len(encoded["input_ids"][index]), index),
        )
        scores = [0.0] * len(hits)
        for start in range(0, len(order), 8):
            indices = order[start : start + 8]
            tokens = tokenizer.pad(
                {key: [values[index] for index in indices] for key, values in encoded.items()},
                padding=True,
                return_tensors="pt",
            )
            with torch.inference_mode():
                values = model(**tokens).logits.squeeze(-1).tolist()
            for index, score in zip(indices, values, strict=True):
                scores[index] = score
        return [scores[index] for index in owners]

    def preload(self) -> None:
        """Load online models during startup, before accepting investigations."""
        self.encode(["Model initialization"])
        self.rank("Model initialization", [])


def epoch(day: date) -> int:
    return int(datetime.combine(day, time.min, UTC).timestamp())


def evidence_filter(
    start: date,
    cutoff: date,
    sources: list[str],
    drug: str | None,
    event: str | None,
) -> models.Filter:
    conditions: list = [
        models.FieldCondition(key="source_type", match=models.MatchAny(any=sources)),
        models.FieldCondition(
            key="source_date",
            range=models.Range(gte=epoch(start), lt=epoch(cutoff + timedelta(days=1))),
        ),
        models.FieldCondition(
            key="available_at", range=models.Range(lt=epoch(cutoff + timedelta(days=1)))
        ),
    ]
    for key, value in [("drug_id", drug), ("event_id", event)]:
        if value:
            conditions.append(models.FieldCondition(key=key, match=models.MatchValue(value=value)))
    return models.Filter(must=conditions)


class _RankWithWork:
    """Only inference crosses threads; caller-owned SQL work stays on the caller thread."""

    def __init__(self, embedder: MedCPT, work: Callable[[], None]):
        self.embedder, self.work = embedder, work
        self.work_started = False
        self.work_error: Exception | None = None

    def encode(self, *args, **kwargs):
        return self.embedder.encode(*args, **kwargs)

    def run_work(self):
        self.work_started = True
        try:
            self.work()
        except Exception as exc:
            self.work_error = exc
            raise

    def rank(self, question, hits):
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="rerank") as pool:
            scores = pool.submit(self.embedder.rank, question, hits)
            self.run_work()
            return scores.result()


class Retriever:
    def __init__(self, settings: Settings, client: QdrantClient, embedder: MedCPT):
        self.settings, self.client, self.embedder = settings, client, embedder

    def search_and_run(
        self, session, dataset, question, cutoff, drug=None, event=None, *, work
    ) -> list[EvidenceHit]:
        """Overlap independent caller work with CPU reranking, without a second DB session."""
        ranker = _RankWithWork(self.embedder, work)
        try:
            return Retriever(self.settings, self.client, ranker).search(
                session, dataset, question, cutoff, drug, event
            )
        except Exception:
            # Retrieval's error boundary must not relabel a failure from caller SQL.
            if ranker.work_error is not None:
                raise ranker.work_error from None
            raise
        finally:
            # Empty results and dependency failures still execute facts exactly once.
            # A facts error takes precedence, preserving the previous facts-first path.
            if not ranker.work_started:
                ranker.run_work()

    def search(
        self,
        session: Session,
        dataset: Dataset,
        question: str,
        cutoff: date,
        drug: str | None = None,
        event: str | None = None,
    ) -> list[EvidenceHit]:
        started = perf_counter()
        config = self.settings.retrieval()
        log_event(
            "retrieval_started",
            dataset_id=dataset.id,
            top_k=config.top_k,
            config_version=config.version,
        )
        try:
            vector = self.embedder.encode([question])[0]
            points = self.client.query_points(
                collection_name=collection_name(self.settings, dataset.id),
                query=vector,
                query_filter=evidence_filter(
                    dataset.window_start, cutoff, config.allowed_sources, drug, event
                ),
                limit=config.candidate_pool,
                with_payload=["embedding_input_version"],
                search_params=models.SearchParams(exact=True),
            ).points
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError(
                "RETRIEVAL_UNAVAILABLE", "Evidence retrieval is unavailable."
            ) from exc
        hits = []
        for rank, point in enumerate(points, 1):
            row = session.execute(
                select(EvidenceChunk, SourceDocument)
                .join(SourceDocument)
                .join(
                    DatasetChunk,
                    DatasetChunk.chunk_id == EvidenceChunk.id,
                )
                .where(DatasetChunk.dataset_id == dataset.id, EvidenceChunk.id == str(point.id))
            ).first()
            if row is None:
                raise DomainError("EVIDENCE_INTEGRITY", "Retrieved evidence is missing.", 502)
            chunk, doc = row
            if (point.payload or {}).get("embedding_input_version") != EMBEDDING_INPUT_VERSION:
                raise DomainError(
                    "INDEX_VERSION_MISMATCH", "The evidence index must be rebuilt.", 503
                )
            if (
                not dataset.window_start <= doc.source_date <= cutoff
                or doc.available_at > cutoff
                or doc.source_type not in config.allowed_sources
                or (drug and chunk.drug_id != drug)
                or (event and chunk.event_id != event)
            ):
                raise DomainError(
                    "EVIDENCE_INTEGRITY", "Evidence violates the requested filters.", 502
                )
            hits.append(
                EvidenceHit(
                    chunk_id=chunk.id,
                    document_id=doc.id,
                    score=point.score,
                    rank=rank,
                    source_type=doc.source_type,
                    source_date=doc.source_date,
                    available_at=doc.available_at,
                    title=doc.title,
                    locator=chunk.locator,
                    polarity=chunk.polarity,
                    text=chunk.text,
                    url=readable_source_url(doc.url),
                )
            )
        from pharmaguard.ranking import rank_context

        try:
            result = rank_context(
                session, dataset, question, cutoff, drug, event, hits, self.embedder, config
            )
            log_event(
                "retrieval_completed",
                dataset_id=dataset.id,
                candidate_count=len(points),
                returned=len(result),
                top_k=config.top_k,
                config_version=config.version,
                duration_ms=round((perf_counter() - started) * 1000),
            )
            return result
        except (DomainError, SQLAlchemyError):
            raise
        except Exception as exc:
            raise DomainError(
                "RERANKER_UNAVAILABLE", "Evidence reranking is unavailable.", 503
            ) from exc
