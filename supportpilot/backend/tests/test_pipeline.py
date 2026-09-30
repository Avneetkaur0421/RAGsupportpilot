"""Tests that run offline: no API key and no model download needed.

Run from the backend folder:  pytest -q
"""
import hashlib

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings

from app import config, vectorstore
from app.graph import GradedAnswer, build_graph
from app.ingest import load_folder, parse_markdown


class HashEmbedding(EmbeddingFunction[Documents]):
    """Tiny fake embedding (bag of hashed words) so tests don't download a model."""
    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        out = []
        for text in input:
            v = [0.0] * 64
            for w in text.lower().split():
                v[int(hashlib.md5(w.strip(".,?!").encode()).hexdigest(), 16) % 64] += 1.0
            out.append(v)
        return out

    @staticmethod
    def name():
        return "hash-embedding"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return HashEmbedding()


class FakeLLM:
    """Stands in for ChatAnthropic and returns a fixed structured answer."""
    def __init__(self, confidence):
        self.confidence = confidence

    def with_structured_output(self, schema):
        return self

    def invoke(self, prompt):
        return GradedAnswer(answer="Refunds take 5 to 7 business days [P1].",
                            confidence=self.confidence, topic="refund timing", missing="")


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(vectorstore, "_collection", None)
    vectorstore.collection(embedding_function=HashEmbedding())
    vectorstore.upsert(load_folder(config.DOCS_DIR))
    monkeypatch.setattr(config, "MIN_RELEVANCE", 0.05)


def test_parse_markdown_reads_audience_and_sections():
    chunks = parse_markdown("demo", "---\naudience: internal\n---\n# Demo\n\n## One\nHello.\n\n## Two\nWorld.")
    assert [c.heading for c in chunks] == ["One", "Two"]
    assert all(c.audience == "internal" for c in chunks)


def test_customers_never_see_internal_guides():
    hits = vectorstore.search("refund approval limits for agents", "customer", 10)
    assert hits and all(h["audience"] == "public" for h in hits)


def test_confident_answer_is_returned():
    out = build_graph(FakeLLM("high")).invoke({"question": "How long does a refund take?", "audience": "customer"})
    assert out["status"] == "answered" and "[P1]" in out["answer"]


def test_low_confidence_goes_to_review():
    out = build_graph(FakeLLM("low")).invoke({"question": "Can I get a bulk discount?", "audience": "customer"})
    assert out["status"] == "escalated"


def test_api_escalation_creates_review_and_resolving_adds_to_kb(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, store

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "test.db")
    store.init()
    monkeypatch.setattr(main, "agent", build_graph(FakeLLM("low")))
    client = TestClient(main.app)  # not used as a context manager, so startup is skipped

    r = client.post("/api/ask", json={"question": "Can I get a bulk discount?", "audience": "customer"}).json()
    assert r["status"] == "escalated" and r["review_id"]

    ok = client.post(f"/api/reviews/{r['review_id']}/resolve",
                     json={"reply": "Email sales@kestrel.example for orders of 5+ bikes.", "add_to_kb": True})
    assert ok.status_code == 200
    titles = [d["title"] for d in client.get("/api/documents").json()]
    assert "Support team answers" in titles
    assert client.get("/api/insights").json()["escalated"] == 1


def test_api_upload_pdf(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main, store
    from tests.test_ingest import make_pdf

    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path)
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "uploads")
    store.init()
    client = TestClient(main.app)

    pdf = tmp_path / "holiday.pdf"
    make_pdf(pdf, ["Order by December 18 for delivery before December 25."])
    with pdf.open("rb") as f:
        r = client.post("/api/documents/upload", files={"file": ("holiday.pdf", f, "application/pdf")},
                        data={"title": "Holiday shipping", "audience": "public"})
    assert r.status_code == 200 and r.json()["passages"] == 1
    assert "Holiday shipping" in [d["title"] for d in client.get("/api/documents").json()]

    bad = client.post("/api/documents/upload", files={"file": ("sheet.xlsx", b"x", "application/octet-stream")})
    assert bad.status_code == 400
