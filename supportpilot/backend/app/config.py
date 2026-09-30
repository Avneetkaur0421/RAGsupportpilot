"""All settings in one place. Values come from backend/.env (see .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

DOCS_DIR = BACKEND_DIR / "data" / "docs"          # markdown knowledge base
STORAGE_DIR = BACKEND_DIR / "storage"             # created on first run
CHROMA_DIR = STORAGE_DIR / "chroma"               # vector store
SQLITE_PATH = STORAGE_DIR / "supportpilot.db"     # logs, reviews, added docs

LLM_MODEL = os.getenv("LLM_MODEL", "claude-haiku-4-5-20251001")
TOP_K = int(os.getenv("TOP_K", "4"))
MIN_RELEVANCE = float(os.getenv("MIN_RELEVANCE", "0.30"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "800"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
UPLOAD_DIR = STORAGE_DIR / "uploads"            # original files added from the UI
MAX_UPLOAD_MB = 10

COMPANY = "Kestrel Cycles"  # fictional demo company
