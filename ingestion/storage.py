import hashlib
import json
import re
import secrets
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse

import httpx
from pharmaguard.config import Settings


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get(client: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """Retry only transient HTTP/network failures, with a bounded delay."""
    for attempt in range(4):
        try:
            response = client.get(url, **kwargs)
            if response.status_code not in [429, 500, 502, 503, 504]:
                response.raise_for_status()
                return response
            response.raise_for_status()
        except (httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            transient = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code in [429, 500, 502, 503, 504]
            )
            if not transient or attempt == 3:
                raise
            time.sleep(min(2**attempt, 8) + secrets.randbelow(251) / 1000)
    raise RuntimeError("Unreachable retry state")


FDA_RANGE_BYTES = 1024 * 1024


def download_fda_archive(client: httpx.Client, url: str, output) -> None:
    """FDA's server can stall on large responses; validate bounded byte ranges."""

    def part(start: int, end: int, total: int | None = None):
        response = get(
            client,
            url,
            headers={
                "Range": f"bytes={start}-{end}",
                "Accept-Encoding": "identity",
                "User-Agent": "PharmaGuardAI/0.1 (public FDA dataset ingestion)",
            },
        )
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", ""))
        if response.status_code != 206 or not match:
            raise ValueError("FDA archive requires a valid partial-content response")
        actual_start, actual_end, actual_total = map(int, match.groups())
        if (
            actual_start != start
            or actual_end != min(end, actual_total - 1)
            or len(response.content) != actual_end - actual_start + 1
            or (total is not None and total != actual_total)
            or not 0 < actual_total <= 4 * 1024**3
        ):
            raise ValueError("FDA archive byte range failed integrity validation")
        return response.content, actual_total

    content, total = part(0, FDA_RANGE_BYTES - 1)
    output.write(content)
    with ThreadPoolExecutor(max_workers=3) as pool:
        for start in range(FDA_RANGE_BYTES, total, 3 * FDA_RANGE_BYTES):
            offsets = range(start, min(start + 3 * FDA_RANGE_BYTES, total), FDA_RANGE_BYTES)
            futures = [
                pool.submit(part, offset, min(offset + FDA_RANGE_BYTES - 1, total - 1), total)
                for offset in offsets
            ]
            for future in futures:
                output.write(future.result()[0])


class RawStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.raw_directory.mkdir(parents=True, exist_ok=True)
        self.bucket = None
        if settings.raw_store == "gcs":
            from google.cloud import storage

            if not settings.gcs_bucket:
                raise ValueError("GCS_BUCKET is required in GCS mode")
            self.bucket = storage.Client(project=settings.gcp_project_id).bucket(
                settings.gcs_bucket
            )
        elif settings.raw_store != "local":
            raise ValueError("RAW_STORE must be local or gcs")

    def put(self, path: Path, key: str) -> str:
        if self.bucket is not None:
            from google.api_core.exceptions import PreconditionFailed

            blob = self.bucket.blob(key)
            try:
                blob.upload_from_filename(str(path), if_generation_match=0, checksum="auto")
            except PreconditionFailed:
                # Content-addressed paths cannot contain a different source asset.
                with NamedTemporaryFile(delete=False) as handle:
                    check = Path(handle.name)
                try:
                    blob.download_to_filename(str(check))
                    if sha256(check) != sha256(path):
                        raise ValueError("Immutable raw object checksum mismatch") from None
                finally:
                    check.unlink(missing_ok=True)
            return f"gs://{self.settings.gcs_bucket}/{key}"
        destination = self.settings.raw_directory / key
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if sha256(destination) != sha256(path):
                raise ValueError("Immutable local object checksum mismatch")
        elif path.resolve() != destination.resolve():
            shutil.copyfile(path, destination)
        return str(destination)

    def download(self, url: str, source: str) -> tuple[Path, dict]:
        parsed = urlparse(url)
        if parsed.scheme != "https":
            raise ValueError("Public source downloads require HTTPS")
        with NamedTemporaryFile(delete=False, dir=self.settings.raw_directory) as handle:
            temp = Path(handle.name)
        try:
            for attempt in range(4):
                try:
                    with httpx.Client(timeout=120, follow_redirects=True) as client:
                        with temp.open("wb") as output:
                            if parsed.hostname == "fis.fda.gov" and parsed.path.endswith(".zip"):
                                download_fda_archive(client, url, output)
                            else:
                                with client.stream("GET", url) as response:
                                    response.raise_for_status()
                                    for block in response.iter_bytes(1024 * 1024):
                                        output.write(block)
                    break
                except (httpx.NetworkError, httpx.TimeoutException, httpx.HTTPStatusError) as exc:
                    transient = not isinstance(exc, httpx.HTTPStatusError) or (
                        exc.response.status_code in [429, 500, 502, 503, 504]
                    )
                    if not transient or attempt == 3:
                        raise
                    time.sleep(2**attempt)
            digest = sha256(temp)
            key = f"raw/{source}/{digest}/{Path(parsed.path).name or 'response'}"
            uri = self.put(temp, key)
            cached = self.settings.raw_directory / "cache" / digest
            cached.parent.mkdir(parents=True, exist_ok=True)
            if not cached.exists():
                shutil.copyfile(temp, cached)
            return cached, {
                "source_url": url,
                "sha256": digest,
                "uri": uri,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "bytes": temp.stat().st_size,
            }
        finally:
            temp.unlink(missing_ok=True)

    def manifest(self, run_id: str, manifest: dict) -> str:
        payload = json.dumps(manifest, sort_keys=True, indent=2).encode()
        with NamedTemporaryFile(delete=False, dir=self.settings.raw_directory) as handle:
            path = Path(handle.name)
            handle.write(payload)
        try:
            return self.put(path, f"manifests/ingestion/{run_id}.json")
        finally:
            path.unlink(missing_ok=True)
