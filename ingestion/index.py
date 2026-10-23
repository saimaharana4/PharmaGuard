from pharmaguard.config import Settings
from pharmaguard.db import DatasetChunk, EvidenceChunk, SourceDocument
from pharmaguard.retrieval import EMBEDDING_INPUT_VERSION, MedCPT, collection_name, epoch
from qdrant_client import models
from sqlalchemy import func, select


def index_dataset(
    sessions, settings: Settings, client, embedder: MedCPT, dataset_id: str, *, rebuild=False
) -> int:
    name = collection_name(settings, dataset_id)
    if rebuild and client.collection_exists(name):
        client.delete_collection(name)
    if not client.collection_exists(name):
        client.create_collection(
            name, vectors_config=models.VectorParams(size=768, distance=models.Distance.COSINE)
        )
    else:
        config = client.get_collection(name).config.params.vectors
        if config.size != 768 or config.distance != models.Distance.COSINE:
            raise ValueError("Existing collection has incompatible vector configuration")
    for key in ["source_type", "drug_id", "event_id"]:
        client.create_payload_index(name, key, models.PayloadSchemaType.KEYWORD, wait=True)
    for key in ["source_date", "available_at"]:
        client.create_payload_index(name, key, models.PayloadSchemaType.INTEGER, wait=True)
    last, count = "", 0
    while True:
        with sessions() as session:
            rows = session.execute(
                select(EvidenceChunk, SourceDocument)
                .join(SourceDocument)
                .join(
                    DatasetChunk,
                    DatasetChunk.chunk_id == EvidenceChunk.id,
                )
                .where(DatasetChunk.dataset_id == dataset_id, EvidenceChunk.id > last)
                .order_by(EvidenceChunk.id)
                .limit(16)
            ).all()
        if not rows:
            break
        vectors = embedder.encode(
            [chunk.text.removeprefix(doc.title).strip() for chunk, doc in rows],
            article=True,
            titles=[doc.title for _, doc in rows],
        )
        client.upsert(
            name,
            points=[
                models.PointStruct(
                    id=chunk.id,
                    vector=vector,
                    payload={
                        "document_id": doc.id,
                        "source_type": doc.source_type,
                        "source_date": epoch(doc.source_date),
                        "available_at": epoch(doc.available_at),
                        "drug_id": chunk.drug_id,
                        "event_id": chunk.event_id,
                        "polarity": chunk.polarity,
                        "embedding_input_version": EMBEDDING_INPUT_VERSION,
                    },
                )
                for (chunk, doc), vector in zip(rows, vectors, strict=True)
            ],
            wait=True,
        )
        last = rows[-1][0].id
        count += len(rows)
    with sessions() as session:
        expected = session.scalar(
            select(func.count())
            .select_from(DatasetChunk)
            .where(DatasetChunk.dataset_id == dataset_id)
        )
    actual = client.count(name, exact=True).count
    if not expected or expected != actual or count != expected:
        raise ValueError("Index count differs from canonical dataset membership")
    return count
