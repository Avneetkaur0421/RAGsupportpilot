"""Shared test setup: a temporary store, a fake embedding and a fake LLM,
so tests run offline with no API key and no model download."""
import hashlib
from types import SimpleNamespace

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings

from app import config, knowledge, store, vectorstore
from app.graph import GradedAnswer


class HashEmbedding(EmbeddingFunction[Documents]):
    """Tiny fake embedding (bag of hashed words)."""
    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        out = []
        for text in input:
            v = [0.0] * 64
            for w in text.lower().split():
                v[int(hashlib.md5(w.strip(".,?!;:").encode()).hexdigest(), 16) % 64] += 1.0
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
    """Stands in for ChatAnthropic. Plain calls rewrite questions; structured calls answer."""
    def __init__(self, confidence="high"):
        self.confidence = confidence
        self.plain_calls = 0

    def invoke(self, prompt):
        self.plain_calls += 1
        return SimpleNamespace(content="How long do refunds take?")

    def with_structured_output(self, schema):
        llm = self
        return SimpleNamespace(invoke=lambda prompt: GradedAnswer(
            answer="Refunds take 5 to 7 business days [P1].",
            confidence=llm.confidence, topic="refund timing", missing=""))


@pytest.fixture(autouse=True)
def temp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "STORAGE_DIR", tmp_path / "storage")
    monkeypatch.setattr(config, "CHROMA_DIR", tmp_path / "storage" / "chroma")
    monkeypatch.setattr(config, "SQLITE_PATH", tmp_path / "storage" / "test.db")
    monkeypatch.setattr(config, "UPLOAD_DIR", tmp_path / "storage" / "uploads")
    monkeypatch.setattr(config, "MIN_RELEVANCE", 0.05)
    monkeypatch.setattr(vectorstore, "_collection", None)
    vectorstore.collection(embedding_function=HashEmbedding(), key="test-hash")
    store.init()
    yield


@pytest.fixture
def demo_kb():
    """Load the real demo documents from data/docs."""
    return knowledge.sync_folder()
