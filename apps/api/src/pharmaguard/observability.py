"""Allowlisted JSON events: no prompts, answers, tokens, headers or provider exceptions."""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

request_context: ContextVar[dict | None] = ContextVar("log_context", default=None)
logging.basicConfig(level=logging.INFO, format="%(message)s")

FIELDS = frozenset(
    {
        "request_id",
        "session_id",
        "dataset_id",
        "run_id",
        "stage",
        "status",
        "duration_ms",
        "count",
        "candidate_count",
        "returned",
        "top_k",
        "config_version",
        "cache_status",
        "error_type",
        "error_code",
        "release_id",
        "git_sha",
        "app_version",
        "manifest",
        "dependency",
        "route",
        "method",
        "facts_ms",
        "retrieval_ms",
        "synthesis_ms",
        "operation",
        "resource",
        "exit_code",
        "image_digest",
        "previous_digest",
    }
)


def event(name: str, **fields: object) -> None:
    if unknown := fields.keys() - FIELDS:
        raise ValueError(f"Unapproved log fields: {sorted(unknown)}")
    logging.getLogger("pharmaguard").info(
        json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "severity": "INFO",
                "event": name,
                **(request_context.get() or {}),
                **fields,
            },
            default=str,
        )
    )
