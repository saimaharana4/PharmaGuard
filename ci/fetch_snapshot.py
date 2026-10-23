"""Fetch an approved immutable Generic Package, authenticated with this job's token."""

import hashlib
import os
from pathlib import Path

import httpx

version = os.environ["EVAL_DATASET_VERSION"]
expected = os.environ["EVAL_SNAPSHOT_SHA256"]
base = os.environ["CI_API_V4_URL"]
project = os.environ["CI_PROJECT_ID"]
url = f"{base}/projects/{project}/packages/generic/pharmaguard-eval/{version}/snapshot.zip"
destination = Path(".data/evaluation/snapshot.zip")
destination.parent.mkdir(parents=True, exist_ok=True)
digest = hashlib.sha256()
with httpx.Client(timeout=120, follow_redirects=True) as client:
    with client.stream("GET", url, headers={"JOB-TOKEN": os.environ["CI_JOB_TOKEN"]}) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for block in response.iter_bytes(1024 * 1024):
                output.write(block)
                digest.update(block)
if digest.hexdigest() != expected:
    raise SystemExit("Approved evaluation snapshot checksum mismatch")
destination.with_suffix(".zip.sha256").write_text(expected)

# Pinned article vectors are corpus inputs, not query results or benchmark scores.
article_sha = os.environ["EVAL_EMBEDDING_SHA256"]
article_url = (
    f"{base}/projects/{project}/packages/generic/pharmaguard-eval/"
    f"{version}/articles-{article_sha}.json.gz"
)
article_path = destination.with_name("articles.json.gz")
article_digest = hashlib.sha256()
with httpx.Client(timeout=120, follow_redirects=True) as client:
    with client.stream(
        "GET", article_url, headers={"JOB-TOKEN": os.environ["CI_JOB_TOKEN"]}
    ) as response:
        response.raise_for_status()
        with article_path.open("wb") as output:
            for block in response.iter_bytes(1024 * 1024):
                output.write(block)
                article_digest.update(block)
if article_digest.hexdigest() != os.environ["EVAL_EMBEDDING_SHA256"]:
    raise SystemExit("Approved article-input checksum mismatch")
