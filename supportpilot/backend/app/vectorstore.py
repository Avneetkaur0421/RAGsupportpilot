"""Step 2 of RAG: store passages as embeddings and search them.

ChromaDB's default embedding model (all-MiniLM-L6-v2) runs locally, so no
extra API key is needed. It downloads once (~80 MB) on first run.
"""
import chromadb

from . import config
from .ingest import Chunk

_client = None
_collection = None


def collection(embedding_function=None):
    """Return the Chroma collection, creating it on first use.

    embedding_function is only passed in tests; the app uses Chroma's default.
    """
    global _client, _collection
    if _collection is None:
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        kwargs = {"name": "knowledge_base", "metadata": {"hnsw:space": "cosine"}}
        if embedding_function is not None:
            kwargs["embedding_function"] = embedding_function
        _collection = _client.get_or_create_collection(**kwargs)
    return _collection


def upsert(chunks: list[Chunk]) -> None:
    """Add or update passages. Using the passage id makes re-ingesting safe."""
    if not chunks:
        return
    collection().upsert(
        ids=[c.pid for c in chunks],
        # We embed title + heading + text so the heading's meaning helps matching.
        documents=[f"{c.doc_title}. {c.heading}. {c.text}" for c in chunks],
        metadatas=[{"doc_id": c.doc_id, "doc_title": c.doc_title, "heading": c.heading,
                    "text": c.text, "audience": c.audience} for c in chunks],
    )


def search(question: str, audience: str, k: int) -> list[dict]:
    """Return the k closest passages. Customers only ever see public passages."""
    where = None if audience == "team" else {"audience": "public"}
    res = collection().query(query_texts=[question], n_results=k, where=where)
    hits = []
    for pid, meta, dist in zip(res["ids"][0], res["metadatas"][0], res["distances"][0]):
        hits.append({
            "pid": pid,
            "doc_title": meta["doc_title"],
            "heading": meta["heading"],
            "text": meta["text"],
            "audience": meta["audience"],
            # Cosine distance 0 = identical. Turn it into a 0..1 relevance score.
            "relevance": round(max(0.0, 1 - dist), 3),
        })
    return hits


def all_documents() -> list[dict]:
    """Group every stored passage by document, for the Knowledge base screen."""
    data = collection().get(include=["metadatas"])
    docs: dict[str, dict] = {}
    for pid, meta in zip(data["ids"], data["metadatas"]):
        d = docs.setdefault(meta["doc_id"], {"doc_id": meta["doc_id"], "title": meta["doc_title"],
                                             "audience": meta["audience"], "sections": []})
        d["sections"].append({"pid": pid, "heading": meta["heading"], "text": meta["text"]})
    for d in docs.values():
        d["sections"].sort(key=lambda s: int(s["pid"].split("#")[1]))
    return sorted(docs.values(), key=lambda d: (d["audience"], d["title"]))
