"""One place that decides WHICH AI models the app uses.

Every other file asks this module for a chat model or an embedding model,
so switching from Claude to GPT, Gemini or a free local model is a change
to .env only. No code changes.

Chat models (LLM_PROVIDER):
  anthropic  Claude                    pip install langchain-anthropic      ANTHROPIC_API_KEY
  openai     GPT models                pip install langchain-openai         OPENAI_API_KEY
             ...or any OpenAI-compatible server (Groq, OpenRouter, DeepSeek,
             Together, vLLM, LM Studio) by also setting OPENAI_BASE_URL
  azure      Azure OpenAI              pip install langchain-openai         AZURE_OPENAI_API_KEY,
                                                                            AZURE_OPENAI_ENDPOINT, OPENAI_API_VERSION
  google     Gemini (API key)          pip install langchain-google-genai   GOOGLE_API_KEY
  vertexai   Gemini on Google Cloud    pip install langchain-google-vertexai  gcloud login / service account
  ollama     Local models, free        pip install langchain-ollama         Ollama running on your machine

Embedding models (EMBEDDING_PROVIDER):
  local      all-MiniLM-L6-v2 via ChromaDB, runs on your machine (default, free)
  openai / azure / google / vertexai / ollama   (same packages and keys as above)

Packages are imported only when that provider is picked, so you only need
to install the ones you use.
"""
from chromadb import Documents, EmbeddingFunction, Embeddings

from . import config

CHAT_PROVIDERS = {"anthropic", "openai", "azure", "google", "vertexai", "ollama"}
EMBEDDING_PROVIDERS = {"local", "openai", "azure", "google", "vertexai", "ollama"}


class ProviderError(RuntimeError):
    """A clear, fixable setup problem (unknown provider, missing package)."""


def _need(package: str):
    raise ProviderError(f"This provider needs an extra package. Run: pip install {package}")


# ---------- chat models ----------

def chat_model(max_tokens: int = 800, temperature: float = 0):
    """Return a LangChain chat model for the configured provider.

    All of them share the same interface: .invoke(), .with_structured_output()
    and image/PDF input, which is why the rest of the app doesn't care which one it gets.
    """
    provider, model = config.LLM_PROVIDER, config.LLM_MODEL
    if provider not in CHAT_PROVIDERS:
        raise ProviderError(f"Unknown LLM_PROVIDER '{provider}'. Use one of: {', '.join(sorted(CHAT_PROVIDERS))}.")

    if provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            _need("langchain-anthropic")
        return ChatAnthropic(model=model, temperature=temperature, max_tokens=max_tokens)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            _need("langchain-openai")
        # base_url=None means the normal OpenAI API; set it for OpenAI-compatible servers.
        return ChatOpenAI(model=model, temperature=temperature, max_tokens=max_tokens,
                          base_url=config.OPENAI_BASE_URL or None)

    if provider == "azure":
        try:
            from langchain_openai import AzureChatOpenAI
        except ImportError:
            _need("langchain-openai")
        # On Azure, LLM_MODEL is your *deployment* name.
        return AzureChatOpenAI(azure_deployment=model, temperature=temperature, max_tokens=max_tokens)

    if provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            _need("langchain-google-genai")
        return ChatGoogleGenerativeAI(model=model, temperature=temperature, max_output_tokens=max_tokens)

    if provider == "vertexai":
        try:
            from langchain_google_vertexai import ChatVertexAI
        except ImportError:
            _need("langchain-google-vertexai")
        return ChatVertexAI(model=model, temperature=temperature, max_output_tokens=max_tokens)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError:
            _need("langchain-ollama")
        return ChatOllama(model=model, temperature=temperature, num_predict=max_tokens,
                          base_url=config.OLLAMA_BASE_URL)


# ---------- embedding models ----------

class LangChainEmbedding(EmbeddingFunction[Documents]):
    """Lets ChromaDB use any LangChain embedding model."""

    def __init__(self, embeddings, key: str):
        self._embeddings = embeddings
        self._key = key

    def __call__(self, input: Documents) -> Embeddings:          # used when storing passages
        return self._embeddings.embed_documents(list(input))

    def embed_query(self, input: Documents) -> Embeddings:       # used when searching
        return [self._embeddings.embed_query(text) for text in input]

    def name(self) -> str:
        return "langchain"

    def get_config(self) -> dict:
        return {"key": self._key}

    @staticmethod
    def build_from_config(config):  # Chroma calls this when reopening; we always pass our own
        raise ProviderError("Reopen the collection with embedding_function().")


def embedding_key() -> str:
    """A short id for the current embedding setup, e.g. 'openai-text-embedding-3-small'.

    Different embedding models produce incompatible vectors, so each setup
    gets its own Chroma collection (see vectorstore.py).
    """
    if config.EMBEDDING_PROVIDER == "local":
        return "local-minilm"
    return f"{config.EMBEDDING_PROVIDER}-{config.EMBEDDING_MODEL}"


def embedding_function():
    """Return a ChromaDB embedding function, or None for Chroma's built-in local model."""
    provider, model = config.EMBEDDING_PROVIDER, config.EMBEDDING_MODEL
    if provider not in EMBEDDING_PROVIDERS:
        raise ProviderError(f"Unknown EMBEDDING_PROVIDER '{provider}'. "
                            f"Use one of: {', '.join(sorted(EMBEDDING_PROVIDERS))}.")
    if provider == "local":
        return None
    if not model:
        raise ProviderError(f"Set EMBEDDING_MODEL for the '{provider}' embedding provider.")

    if provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings
        except ImportError:
            _need("langchain-openai")
        emb = OpenAIEmbeddings(model=model, base_url=config.OPENAI_BASE_URL or None)
    elif provider == "azure":
        try:
            from langchain_openai import AzureOpenAIEmbeddings
        except ImportError:
            _need("langchain-openai")
        emb = AzureOpenAIEmbeddings(azure_deployment=model)
    elif provider == "google":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
        except ImportError:
            _need("langchain-google-genai")
        emb = GoogleGenerativeAIEmbeddings(model=model)
    elif provider == "vertexai":
        try:
            from langchain_google_vertexai import VertexAIEmbeddings
        except ImportError:
            _need("langchain-google-vertexai")
        emb = VertexAIEmbeddings(model_name=model)
    else:  # ollama
        try:
            from langchain_ollama import OllamaEmbeddings
        except ImportError:
            _need("langchain-ollama")
        emb = OllamaEmbeddings(model=model, base_url=config.OLLAMA_BASE_URL)
    return LangChainEmbedding(emb, embedding_key())


def describe() -> dict:
    """What's running, for the UI and /api/health."""
    return {"llm_provider": config.LLM_PROVIDER, "llm_model": config.LLM_MODEL,
            "embedding_provider": config.EMBEDDING_PROVIDER,
            "embedding_model": config.EMBEDDING_MODEL or "all-MiniLM-L6-v2"}
