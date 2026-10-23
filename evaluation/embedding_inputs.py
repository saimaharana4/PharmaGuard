"""Reuse immutable article vectors, while always executing current query/ranking code."""

import argparse
import ast
import copy
import gzip
import hashlib
import inspect
import json
import math
import textwrap
import threading
from pathlib import Path

from pharmaguard.config import Settings
from pharmaguard.retrieval import EMBEDDING_INPUT_VERSION, MedCPT

from evaluation.core import file_digest, read_snapshot


def signature(settings: Settings) -> dict:
    source = ast.unparse(ast.parse(textwrap.dedent(inspect.getsource(MedCPT.encode))))
    return {
        "model": settings.embedding_document_model,
        "revision": settings.embedding_document_revision,
        "format": EMBEDDING_INPUT_VERSION,
        "encode_sha256": hashlib.sha256(source.encode()).hexdigest(),
        "lock_sha256": file_digest(Path("uv.lock")),
    }


def key(title: str, body: str) -> str:
    return hashlib.sha256(json.dumps([title, body], ensure_ascii=False).encode()).hexdigest()


class ArticleInputs:
    def __init__(self, delegate: MedCPT, path: Path, checksum: str, snapshot_sha256: str):
        if file_digest(path) != checksum:
            raise ValueError("Article input checksum mismatch")
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            data = json.load(stream)
        if data["snapshot_sha256"] != snapshot_sha256:
            raise ValueError("Article inputs belong to a different corpus")
        self.delegate = delegate
        self.settings = delegate.settings
        # Changed encoder code/dependencies must execute their current implementation.
        self.enabled = data["signature"] == signature(delegate.settings)
        self.vectors = data["vectors"] if self.enabled else {}
        self.hits = 0
        for vector in self.vectors.values():
            if len(vector) != 768 or not all(math.isfinite(value) for value in vector):
                raise ValueError("Invalid prepared article vector")

    def encode(self, texts, *, article=False, titles=None):
        if article and titles is not None and len(titles) == len(texts):
            keys = [key(title, body) for title, body in zip(titles, texts, strict=True)]
            if all(value in self.vectors for value in keys):
                self.hits += len(keys)
                return [self.vectors[value] for value in keys]
        return self.delegate.encode(texts, article=article, titles=titles)

    def rank(self, question, hits):
        return self.delegate.rank(question, hits)

    def preload(self):
        self.delegate.preload()


class ConcurrentEncoders:
    """Share read-only model weights, isolate mutable tokenizer state per worker."""

    def __init__(self, delegate):
        self.encoder = delegate.delegate if isinstance(delegate, ArticleInputs) else delegate
        self.local = threading.local()

    def current(self):
        if not hasattr(self.local, "encoder"):
            encoder = copy.copy(self.encoder)
            encoder._models = {
                name: (copy.deepcopy(tokenizer), model)
                for name, (tokenizer, model) in self.encoder._models.items()
            }
            self.local.encoder = encoder
        return self.local.encoder

    def encode(self, *args, **kwargs):
        return self.current().encode(*args, **kwargs)

    def rank(self, *args, **kwargs):
        return self.current().rank(*args, **kwargs)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = read_snapshot(args.snapshot, args.sha256)
    settings = Settings()
    if snapshot.document_model_revision != settings.embedding_document_revision:
        raise ValueError("Article model revision does not match the frozen corpus")
    documents = {row["id"]: row for row in snapshot.documents}
    embedder, vectors = MedCPT(settings), {}
    for start in range(0, len(snapshot.chunks), 16):
        chunks = snapshot.chunks[start : start + 16]
        titles = [documents[row["document_id"]]["title"] for row in chunks]
        bodies = [
            row["text"].removeprefix(title).strip()
            for row, title in zip(chunks, titles, strict=True)
        ]
        encoded = embedder.encode(bodies, article=True, titles=titles)
        vectors.update(
            {
                key(title, body): vector
                for title, body, vector in zip(titles, bodies, encoded, strict=True)
            }
        )
        print(
            json.dumps({"event": "article_inputs_prepared", "chunks": start + len(chunks)}),
            flush=True,
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wt", encoding="utf-8") as stream:
        json.dump(
            {"snapshot_sha256": args.sha256, "signature": signature(settings), "vectors": vectors},
            stream,
            separators=(",", ":"),
        )
    print(json.dumps({"sha256": file_digest(args.output), "vectors": len(vectors)}), flush=True)


if __name__ == "__main__":
    main()
