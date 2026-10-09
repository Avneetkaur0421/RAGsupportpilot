"""Step 2 of RAG: store passages as embeddings and search them.

The embedding model comes from providers.py (EMBEDDING_PROVIDER in .env).
The default runs locally (all-MiniLM-L6-v2), so no API key is needed; it
downloads once (~80 MB) on first run.

Different embedding models produce incompatible vectors, so each one gets
its own collection. When you switch models, passages are copied from the
previous collection and re-embedded automatically: nothing to re-upload.
"""
import re

import chromadb

from . import config, providers
from .ingest import Chunk

_client = None
_collection = None
_UNSET = object()


def _name_for(key: str) -> str:
    return "kb-" + re.sub(r"[^a-zA-Z0-9]+", "-", key).strip("-").lower()[:60]


def collection(embedding_function=_UNSET, key: str | None = None):
    """Return the Chroma collection for the current embedding model, creating it on first use.

    embedding_function and key are only passed in tests.
    """
    global _client, _collection
    if _collection is None:
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
        ef = providers.embedding_function() if embedding_function is _UNSET else embedding_function
        name = _name_for(key or providers.embedding_key())
        kwargs = {"name": name, "metadata": {"hnsw:space": "cosine"}}
        if ef is not None:
            kwargs["embedding_function"] = ef
        _collection = _client.get_or_create_collection(**kwargs)
        _migrate_from_previous(name)
    return _collection


def _migrate_from_previous(name: str) -> None:
    """If the embedding model changed, copy passages over so they get re-embedded."""
    marker = config.STORAGE_DIR / "active_collection.txt"
    previous = marker.read_text().strip() if marker.exists() else ""
    if previous and previous != name and _collection.count() == 0:
        try:
            old = _client.get_collection(previous)  # read-only use: no embedding needed
            data = old.get(include=["documents", "metadatas"])
            for i in range(0, len(data["ids"]), 100):  # batches keep API calls a sensible size
                _collection.upsert(ids=data["ids"][i:i + 100], documents=data["documents"][i:i + 100],
                                   metadatas=data["metadatas"][i:i + 100])
        except Exception:
            pass  # nothing to copy; the folder sync will rebuild what it can
    marker.write_text(name)


def upsert(chunks: list[Chunk]) -> None:
    """Add or update passages. Using the passage id makes re-ingesting safe."""
    if not chunks:
        return
    collection().upsert(
        ids=[c.pid for c in chunks],
        # We embed title + heading + text so the heading's meaning helps matching.
        documents=[f"{c.doc_title}. {c.heading}. {c.text}" for c in chunks],
        metadatas=[{"doc_id": c.doc_id, "doc_title": c.doc_title, "heading": c.heading,
                    "text": c.text, "audience": c.audience, "kind": c.kind} for c in chunks],
    )


def replace_document(doc_id: str, chunks: list[Chunk]) -> None:
    """Swap a document's passages for new ones (old pages that no longer exist are removed)."""
    delete_document(doc_id)
    upsert(chunks)


def delete_document(doc_id: str) -> None:
    collection().delete(where={"doc_id": doc_id})


def doc_ids() -> set[str]:
    return {m["doc_id"] for m in collection().get(include=["metadatas"])["metadatas"]}


def sample_passages(n: int = 12) -> list[dict]:
    """A spread of passages from across the knowledge base (for suggested questions)."""
    data = collection().get(include=["metadatas"])
    metas = data["metadatas"]
    step = max(1, len(metas) // n)
    return metas[::step][:n]


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
                                             "audience": meta["audience"], "kind": meta.get("kind", "Text"),
                                             "sections": []})
        d["sections"].append({"pid": pid, "heading": meta["heading"], "text": meta["text"]})
    for d in docs.values():
        d["sections"].sort(key=lambda s: int(s["pid"].split("#")[1]))
    return sorted(docs.values(), key=lambda d: (d["audience"], d["title"]))
