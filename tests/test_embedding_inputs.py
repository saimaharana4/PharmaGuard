import gzip
import json

import pytest
from pharmaguard.config import Settings

from evaluation.core import file_digest
from evaluation.embedding_inputs import ArticleInputs, key, signature


class Encoder:
    settings = Settings()

    def encode(self, *args, **kwargs):
        return [[2.0] * 768]

    def rank(self, question, hits):
        return [3.0] * len(hits)


@pytest.mark.parametrize("drift", [None, "encoder", "corpus", "vector", "checksum"])
def test_article_cache_never_reuses_queries_or_ranking(tmp_path, drift):
    path = tmp_path / "articles.json.gz"
    data = {
        "signature": signature(Settings()),
        "snapshot_sha256": "synthetic-corpus",
        "vectors": {key("Title", "Body"): [1.0] * 768},
    }
    if drift == "encoder":
        data["signature"]["encode_sha256"] = "different-encoder-code"
    elif drift == "corpus":
        data["snapshot_sha256"] = "different-corpus"
    elif drift == "vector":
        data["vectors"][key("Title", "Body")] = [1.0] * 10
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(data, stream)
    checksum = "wrong" if drift == "checksum" else file_digest(path)
    if drift in {"corpus", "vector", "checksum"}:
        with pytest.raises(ValueError):
            ArticleInputs(Encoder(), path, checksum, "synthetic-corpus")
        return
    cached = ArticleInputs(Encoder(), path, checksum, "synthetic-corpus")
    assert cached.encode(["Body"], article=True, titles=["Title"]) == [
        [2.0 if drift == "encoder" else 1.0] * 768
    ]
    assert cached.encode(["Body"]) == [[2.0] * 768]
    assert cached.encode(["Changed body"], article=True, titles=["Title"]) == [[2.0] * 768]
    assert cached.rank("Question", [object()]) == [3.0]


def test_concurrent_tokenizers_are_isolated_and_weights_shared():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace

    from evaluation.embedding_inputs import ConcurrentEncoders

    weights = object()
    raw = SimpleNamespace(_models={"Query": ([0], weights), "Cross": ([0], weights)})
    wrapper = ConcurrentEncoders(raw)
    barrier = Barrier(2)

    def infer(_):
        encoder = wrapper.current()
        encoder._models["Query"][0][0] += 1
        barrier.wait(timeout=10)
        assert encoder._models["Query"][0] == [1]
        assert encoder._models["Query"][1] is weights
        return id(encoder._models["Query"][0])

    with ThreadPoolExecutor(max_workers=2) as executor:
        instances = list(executor.map(infer, range(2)))
    assert len(set(instances)) == 2
    assert raw._models["Query"][0] == [0]
