"""One typed configuration boundary; secrets never appear in serialized status."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

from dateutil.relativedelta import relativedelta
from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class RetrievalConfig(BaseModel):
    version: str
    top_k: int = Field(default=5, ge=1, le=20)
    allowed_sources: list[str] = Field(default_factory=lambda: ["pubmed", "dailymed"])
    candidate_pool: int = Field(default=100, ge=5, le=200)
    rerank_candidates: int = Field(default=32, ge=5, le=64)
    abstract_context_chunks: int = Field(default=3, ge=1, le=3)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")
    app_config_secret: str = ""
    app_env: str = "local"
    app_version: str = "0.1.1"
    git_sha: str = "development"
    db_host: str = "127.0.0.1"
    db_port: int = 5432
    db_name: str = "pharmaguard"
    db_user: str = "pharmaguard_app"
    db_password: SecretStr = SecretStr("")
    db_use_tcp: bool = False
    cloud_sql_connection_name: str = ""
    gcp_project_id: str = ""
    gcp_region: str = "asia-south1"
    gcs_bucket: str = ""
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_secret_version: str = ""
    qdrant_collection: str = "pharmaguard_evidence_v1"
    llm_model: str = "gemini-3.8-flash"
    groq_model: str = "openai/gpt-oss-120b"
    openai_model: str = "gpt-4.1-mini"
    judge_provider: str = "openai"
    judge_model: str = "gpt-4.1-mini"
    groq_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    fallback_providers: list[str] = Field(default_factory=lambda: ["groq", "openai"])
    daily_request_limit: int = Field(default=200, ge=1, le=10000)
    preload_models: bool = False
    sessions_enabled: bool = False
    session_signing_key: SecretStr = SecretStr("")
    session_ttl_seconds: int = Field(default=3600, ge=3600, le=3600)
    session_retention_seconds: int = Field(default=86400, ge=3600, le=86400)
    answer_cache_seconds: int = Field(default=3600, ge=1, le=3600)
    embedding_query_model: str = "ncbi/MedCPT-Query-Encoder"
    embedding_document_model: str = "ncbi/MedCPT-Article-Encoder"
    reranker_model: str = "ncbi/MedCPT-Cross-Encoder"
    reranker_revision: str = "71caf65d4927987813984f54c284405a13fcca49"
    vertex_location: str = "global"
    lookback_months: int = Field(default=24, ge=1, le=120)
    as_of_date: date | None = None
    retrieval_config: Path = Path("config/retrieval.json")
    embedding_query_revision: str = "d83a36cc6b8e3a5c5e9d9d6ba156808c1643dcbc"
    embedding_document_revision: str = "d05a736da4bb84ee4057b7f7999485be6ed85465"
    raw_store: str = "local"
    raw_directory: Path = Path(".data/raw")
    demo_drug: str = "semaglutide"
    demo_event: str = "pancreatitis"

    @field_validator("as_of_date", mode="before")
    @classmethod
    def empty_date(cls, value: object) -> object:
        return None if value == "" else value

    @property
    def effective_date(self) -> date:
        return self.as_of_date or datetime.now(UTC).date()

    @property
    def window_start(self) -> date:
        return self.effective_date - relativedelta(months=self.lookback_months)

    def database_url(self) -> URL:
        host = self.db_host
        query = {}
        if self.cloud_sql_connection_name and not self.db_use_tcp:
            host = ""
            query = {"host": f"/cloudsql/{self.cloud_sql_connection_name}"}
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=host or None,
            port=None if query else self.db_port,
            database=self.db_name,
            query=query,
        )

    def retrieval(self) -> RetrievalConfig:
        return RetrievalConfig.model_validate(json.loads(self.retrieval_config.read_text()))


def secret_text(resource: str) -> str:
    """Fetch a pinned version with ADC. Never serialize provider errors or secret values."""
    import base64
    import re

    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    if not re.fullmatch(r"projects/[\w-]+/secrets/[\w-]+/versions/\d+", resource):
        raise ValueError("A pinned Secret Manager version is required")
    try:
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        with AuthorizedSession(credentials) as session:
            response = session.get(
                f"https://secretmanager.googleapis.com/v1/{resource}:access", timeout=15
            )
            response.raise_for_status()
            return base64.b64decode(response.json()["payload"]["data"]).decode()
    except Exception:
        raise RuntimeError("Secret Manager configuration could not be loaded") from None


def load_settings() -> Settings:
    base = Settings()
    resource = base.app_config_secret
    if not resource:
        bootstrap = Path("config/bootstrap.local.json")
        if bootstrap.is_file():
            resource = json.loads(bootstrap.read_text())["app_config_secret"]
    if base.app_env == "ci":
        return base
    if not resource:
        return base  # Disposable CI services receive job-local configuration, never a .env file.
    config = json.loads(secret_text(resource))
    references = config.pop("secret_references", {})
    for field, reference in references.items():
        if field not in {
            "db_password",
            "qdrant_api_key",
            "groq_api_key",
            "openai_api_key",
            "session_signing_key",
        }:
            raise ValueError("Unexpected credential reference in application configuration")
        if field == "qdrant_api_key":
            import os

            if os.environ.get("QDRANT_URL", "").startswith("http://"):
                config[field] = ""
                continue
        config[field] = secret_text(reference)
    # Explicit process configuration wins for host/port overrides in Docker and CI.
    import os

    for field in Settings.model_fields:
        if field.upper() in os.environ and field not in references:
            config[field] = getattr(base, field)
    return Settings(**config)
