"""Switching models is a .env change. These tests check each provider is wired
correctly without calling any API (fake keys, no network)."""
from types import SimpleNamespace

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from app import config, ingest, providers, vectorstore
from app.ingest import Chunk


@pytest.fixture
def fake_keys(monkeypatch):
    for k in ["ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY", "AZURE_OPENAI_API_KEY"]:
        monkeypatch.setenv(k, "test-key")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    monkeypatch.setenv("OPENAI_API_VERSION", "2024-10-21")


@pytest.mark.parametrize("provider, model, class_name", [
    ("anthropic", "claude-haiku-4-5-20251001", "ChatAnthropic"),
    ("openai", "gpt-4o-mini", "ChatOpenAI"),
    ("azure", "my-deployment", "AzureChatOpenAI"),
    ("google", "gemini-2.5-flash", "ChatGoogleGenerativeAI"),
    ("ollama", "llama3.1", "ChatOllama"),
])
def test_each_chat_provider_builds_its_model(monkeypatch, fake_keys, provider, model, class_name):
    monkeypatch.setattr(config, "LLM_PROVIDER", provider)
    monkeypatch.setattr(config, "LLM_MODEL", model)
    llm = providers.chat_model()
    assert type(llm).__name__ == class_name
    assert hasattr(llm, "with_structured_output")  # what the agent relies on


def test_openai_compatible_server_uses_base_url(monkeypatch, fake_keys):
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(config, "LLM_MODEL", "llama-3.3-70b-versatile")
    monkeypatch.setattr(config, "OPENAI_BASE_URL", "https://api.groq.com/openai/v1")
    assert "groq.com" in str(providers.chat_model().openai_api_base)


def test_unknown_provider_gives_clear_error(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "mystery")
    with pytest.raises(providers.ProviderError, match="Unknown LLM_PROVIDER"):
        providers.chat_model()


def test_missing_package_says_what_to_install(monkeypatch):
    import builtins
    real_import = builtins.__import__
    def no_vertex(name, *args, **kwargs):
        if name.startswith("langchain_google_vertexai"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", no_vertex)
    monkeypatch.setattr(config, "LLM_PROVIDER", "vertexai")
    with pytest.raises(providers.ProviderError, match="pip install langchain-google-vertexai"):
        providers.chat_model()


def test_embedding_providers(monkeypatch, fake_keys):
    monkeypatch.setattr(config, "EMBEDDING_PROVIDER", "local")
    assert providers.embedding_function() is None
    monkeypatch.setattr(config, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "")
    with pytest.raises(providers.ProviderError, match="EMBEDDING_MODEL"):
        providers.embedding_function()
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "text-embedding-3-small")
    assert isinstance(providers.embedding_function(), providers.LangChainEmbedding)
    assert providers.embedding_key() == "openai-text-embedding-3-small"


def test_switching_embedding_model_reembeds_existing_passages(monkeypatch):
    # The autouse fixture already opened a collection with the hash embedding. Add a passage...
    vectorstore.upsert([Chunk("t-1#1", "t-1", "FAQ", "Hours", "Open 9 to 5.", "public")])
    vectorstore.collection().get()
    (config.STORAGE_DIR / "active_collection.txt").write_text(vectorstore.collection().name)

    # ...then "change .env" to a different embedding model and reopen.
    monkeypatch.setattr(vectorstore, "_collection", None)
    new_ef = providers.LangChainEmbedding(DeterministicFakeEmbedding(size=32), "fake-32")
    coll = vectorstore.collection(embedding_function=new_ef, key="fake-32")
    assert coll.name == "kb-fake-32" and coll.count() == 1
    assert vectorstore.search("When are you open?", "customer", 1)[0]["text"] == "Open 9 to 5."


def test_vision_uses_standard_blocks_for_any_provider(monkeypatch):
    captured = {}
    class FakeVisionModel:
        def invoke(self, messages):
            captured["content"] = messages[0].content
            return SimpleNamespace(content="## Menu\nTea: $2")
    monkeypatch.setattr(providers, "chat_model", lambda max_tokens=800: FakeVisionModel())
    assert "Tea" in ingest.vision_extract(b"\x89PNG", "image/png")
    block = captured["content"][0]
    assert block["type"] == "image" and block["mime_type"] == "image/png" and "base64" in block


def test_model_that_cannot_read_images_gives_clear_error(monkeypatch):
    class TextOnlyModel:
        def invoke(self, messages):
            raise RuntimeError("images not supported")
    monkeypatch.setattr(providers, "chat_model", lambda max_tokens=800: TextOnlyModel())
    with pytest.raises(ValueError, match="may not support images"):
        ingest.vision_extract(b"x", "image/png")
