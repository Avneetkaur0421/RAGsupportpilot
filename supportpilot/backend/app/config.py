"""All settings in one place. Values come from backend/.env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DOCS_DIR = BACKEND_DIR / "data" / "docs"          # drop any supported file here
STORAGE_DIR = BACKEND_DIR / "storage"             # created on first run
CHROMA_DIR = STORAGE_DIR / "chroma"               # vector store
SQLITE_PATH = STORAGE_DIR / "supportpilot.db"     # logs, reviews, added docs

# Which AI models to use. See providers.py for every option.
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic").strip().lower()
LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001").strip()
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local").strip().lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "").strip()
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip()          # for OpenAI-compatible servers
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
TOP_K = int(os.getenv("TOP_K", "4"))
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
UPLOAD_DIR = STORAGE_DIR / "uploads"            # original files added from the UI
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "25"))

# Who the assistant works for. Change these and the whole app adapts.
ORG_NAME = os.getenv("ORG_NAME", "Kestrel Cycles")
ORG_DESCRIPTION = os.getenv("ORG_DESCRIPTION", "a fictional e-bike brand")

# Images and scanned PDFs have no text layer. When this is on, the chat model reads them
# (it must support images/PDFs, e.g. Claude, GPT-4o class, Gemini).
VISION_EXTRACT = os.getenv("VISION_EXTRACT", "true").lower() == "true"

# How many earlier exchanges to use for follow-up questions.
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "3"))

os.environ.setdefault("USER_AGENT", "SupportPilot/1.0")  # used by the web page loader
