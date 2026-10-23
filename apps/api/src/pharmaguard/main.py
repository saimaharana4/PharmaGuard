import json
import logging
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from pharmaguard.config import Settings, load_settings
from pharmaguard.conversation import investigate_session, open_session, signing_key
from pharmaguard.db import session_factory
from pharmaguard.errors import DomainError
from pharmaguard.observability import request_context as log_context
from pharmaguard.retrieval import (
    EMBEDDING_INPUT_VERSION,
    MedCPT,
    Retriever,
    collection_name,
    qdrant_client,
)
from pharmaguard.schemas import InvestigateRequest, InvestigateResponse
from pharmaguard.security import reserve_request
from pharmaguard.service import active_dataset, investigate
from pharmaguard.synthesis import VertexSynthesizer

logger = logging.getLogger("pharmaguard")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    supplied_settings = settings is not None
    settings = settings or Settings()
    settings.retrieval()  # Validate the checked-in retrieval contract at startup.

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal settings
        if not supplied_settings:
            settings = load_settings()
        if settings.sessions_enabled:
            signing_key(settings)
        app.state.sessions = session_factory(settings)
        client = qdrant_client(settings)
        app.state.retriever = Retriever(settings, client, MedCPT(settings))
        if settings.preload_models:
            app.state.retriever.embedder.preload()
        app.state.synthesizer = VertexSynthesizer(settings)
        yield
        client.close()
        app.state.sessions.kw["bind"].dispose()

    app = FastAPI(title="PharmaGuard AI", version=settings.app_version, lifespan=lifespan)

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request.state.request_id = str(uuid4())
        context_token = log_context.set(
            {"request_id": request.state.request_id, "git_sha": settings.git_sha}
        )
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            # Prevent ASGI traceback logging from serializing SQL parameters or provider headers.
            logger.error(
                json.dumps(
                    {
                        "event": "request_failed",
                        "error_type": type(exc).__name__,
                        "request_id": request.state.request_id,
                    }
                )
            )
            response = error_response(
                request, "INTERNAL_ERROR", "The investigation could not be completed.", 500
            )
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            json.dumps(
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "severity": "INFO",
                    "request_id": request.state.request_id,
                    "route": request.url.path,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "app_version": settings.app_version,
                    "git_sha": settings.git_sha,
                }
            )
        )
        log_context.reset(context_token)
        return response

    def error_response(request: Request, code: str, message: str, status: int) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": request.state.request_id,
                }
            },
        )

    @app.exception_handler(DomainError)
    async def domain_error(request: Request, exc: DomainError):
        logger.warning(
            json.dumps(
                {
                    "severity": "WARNING",
                    "dependency": exc.code,
                    "request_id": request.state.request_id,
                }
            )
        )
        return error_response(request, exc.code, exc.message, exc.status)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, exc: SQLAlchemyError):
        return error_response(
            request, "DATABASE_UNAVAILABLE", "Canonical data is unavailable.", 503
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return error_response(
            request, "INVALID_REQUEST", "Check the question and optional filters.", 422
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        return error_response(
            request, "INTERNAL_ERROR", "The investigation could not be completed.", 500
        )

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/version")
    def version():
        return {
            "app_version": settings.app_version,
            "git_sha": settings.git_sha,
            "retrieval": settings.retrieval().model_dump(),
            "query_model_revision": settings.embedding_query_revision,
            "document_model_revision": settings.embedding_document_revision,
        }

    @app.get("/ready")
    def ready():
        with app.state.sessions() as session:
            session.execute(text("SELECT 1"))
            dataset = active_dataset(session)
            try:
                collection = app.state.retriever.client.get_collection(
                    collection_name(settings, dataset.id)
                )
                sample, _ = app.state.retriever.client.scroll(
                    collection_name(settings, dataset.id),
                    limit=1,
                    with_payload=["embedding_input_version"],
                    with_vectors=False,
                )
            except Exception as exc:
                raise DomainError(
                    "RETRIEVAL_UNAVAILABLE", "Evidence index is unavailable."
                ) from exc
            if not collection.points_count:
                raise DomainError("DATASET_NOT_READY", "The active evidence index is empty.")
            if not sample or (sample[0].payload or {}).get("embedding_input_version") != (
                EMBEDDING_INPUT_VERSION
            ):
                raise DomainError("INDEX_VERSION_MISMATCH", "The evidence index must be rebuilt.")
        return {"status": "ready", "dataset_id": dataset.id, "coverage": dataset.coverage}

    @app.post("/investigate", response_model=InvestigateResponse)
    def investigation(body: InvestigateRequest, request: Request):
        with app.state.sessions() as session:
            reserve_request(session, settings.daily_request_limit)
            if settings.sessions_enabled:
                return investigate_session(
                    body,
                    request.state.request_id,
                    request.headers.get("X-Session-Token"),
                    session,
                    settings,
                    app.state.retriever,
                    app.state.synthesizer,
                )
            return investigate(
                body,
                request.state.request_id,
                session,
                settings,
                app.state.retriever,
                app.state.synthesizer,
            )

    @app.post("/session")
    def anonymous_session(request: Request):
        if not settings.sessions_enabled:
            return {"enabled": False}
        with app.state.sessions() as session:
            body, token = open_session(session, request.headers.get("X-Session-Token"), settings)
            return JSONResponse(
                body, headers={"X-Session-Token": token, "Cache-Control": "no-store"}
            )

    return app


app = create_app()
