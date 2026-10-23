"""Cache pinned public model artifacts in the image, never in Git."""

from huggingface_hub import snapshot_download
from pharmaguard.config import Settings


def main() -> None:
    settings = Settings()
    for kind, revision in [
        ("Query", settings.embedding_query_revision),
        ("Article", settings.embedding_document_revision),
    ]:
        snapshot_download(
            f"ncbi/MedCPT-{kind}-Encoder",
            revision=revision,
            allow_patterns=["*.json", "vocab.txt", "model.safetensors"],
        )
        print(f"Cached MedCPT {kind} revision {revision}")
    snapshot_download(
        settings.reranker_model,
        revision=settings.reranker_revision,
        allow_patterns=["*.json", "vocab.txt", "pytorch_model.bin"],
    )
    print(f"Cached MedCPT Cross revision {settings.reranker_revision}")


if __name__ == "__main__":
    main()
