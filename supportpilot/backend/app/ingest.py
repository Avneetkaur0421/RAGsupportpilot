"""Step 1 of RAG: turn documents into passages ("chunks"), using LangChain.

Pipeline:  LOAD  ->  SPLIT  ->  CHUNK cards

LOAD   A LangChain "loader" reads a file and returns Document objects:
         Document(page_content="the text", metadata={"source": ..., "page": ...})
         .md / .txt  -> read as text
         .pdf        -> PyPDFLoader      (one Document per page)
         .docx       -> Docx2txtLoader   (one Document for the whole file)

SPLIT  Markdown first goes through MarkdownHeaderTextSplitter, which cuts at
       "#" and "##" headings and remembers them in metadata. Then every piece
       goes through RecursiveCharacterTextSplitter, which cuts anything longer
       than CHUNK_SIZE, trying paragraph breaks first, then sentences, then words.
       CHUNK_OVERLAP repeats a little text between neighbours so a fact that sits
       on a boundary isn't lost.

CHUNK  We convert each piece into our own small Chunk card, so the rest of the
       app (vector store, agent, API) doesn't need to know about LangChain.

Who can see a document ("audience"):
  - Markdown can say so in front matter:  ---\\naudience: internal\\n---
  - Otherwise, files inside a folder named "internal" are internal.
  - Everything else is public.
"""
from dataclasses import dataclass
from pathlib import Path
import re

from langchain_community.document_loaders import Docx2txtLoader, PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from . import config

SUPPORTED = {".md", ".txt", ".pdf", ".docx"}


@dataclass
class Chunk:
    pid: str          # passage id, e.g. "returns#3"
    doc_id: str       # e.g. "returns"
    doc_title: str    # e.g. "Returns and refunds"
    heading: str      # e.g. "Refund timing" (or "Page 2" for PDFs)
    text: str
    audience: str     # "public" or "internal"


# ---------- the two LangChain splitters ----------

_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "title"), ("##", "heading")],
    strip_headers=True,  # headings go into metadata, not into the text
)


def _size_splitter() -> RecursiveCharacterTextSplitter:
    # Built on each call so changes to CHUNK_SIZE in config/tests take effect.
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""],  # try big breaks first
    )


# ---------- public functions ----------

def parse_markdown(doc_id: str, raw: str, default_audience: str = "public",
                   title: str | None = None) -> list[Chunk]:
    """Markdown (or plain text) -> Chunk cards, one per ## section where possible."""
    audience, body = _read_front_matter(raw, default_audience)
    sections = _header_splitter.split_text(body)            # list[Document]
    pieces = _size_splitter().split_documents(sections)     # long sections cut further

    doc_title = title or next((p.metadata["title"] for p in pieces if p.metadata.get("title")),
                              _pretty(doc_id))
    return _to_chunks(doc_id, doc_title, audience, pieces,
                      heading_for=lambda p, i: p.metadata.get("heading")
                      or ("Overview" if p.metadata.get("title") else f"Part {i}"))


def load_file(path: Path, audience: str | None = None, title: str | None = None,
              doc_id: str | None = None) -> list[Chunk]:
    """Any supported file -> Chunk cards. Raises ValueError for other file types."""
    path = Path(path)
    ext = path.suffix.lower()
    doc_id = doc_id or _slug(path.stem)
    audience = audience or _audience_from_path(path)

    if ext in {".md", ".txt"}:
        return parse_markdown(doc_id, path.read_text(encoding="utf-8"), audience, title)

    if ext == ".pdf":
        docs = PyPDFLoader(str(path)).load()        # one Document per page
    elif ext == ".docx":
        docs = Docx2txtLoader(str(path)).load()     # one Document for the file
    else:
        raise ValueError(f"Unsupported file type: {ext}")

    docs = [d for d in docs if d.page_content.strip()]  # scanned pages have no text
    pieces = _size_splitter().split_documents(docs)
    return _to_chunks(doc_id, title or _pretty(path.stem), audience, pieces,
                      heading_for=lambda p, i: f"Page {p.metadata['page'] + 1}"
                      if isinstance(p.metadata.get("page"), int) else f"Part {i}")


def load_folder(folder: Path) -> list[Chunk]:
    """Every supported file in a folder (and its subfolders)."""
    chunks: list[Chunk] = []
    for path in sorted(folder.rglob("*")):
        if path.suffix.lower() in SUPPORTED and path.is_file():
            chunks.extend(load_file(path))
    return chunks


# ---------- helpers ----------

def _to_chunks(doc_id, doc_title, audience, pieces: list[Document], heading_for) -> list[Chunk]:
    chunks = []
    for i, piece in enumerate(pieces, 1):
        text = _clean(piece.page_content)
        if text:
            chunks.append(Chunk(f"{doc_id}#{len(chunks) + 1}", doc_id, doc_title,
                                heading_for(piece, i), text, audience))
    return chunks


def _read_front_matter(raw: str, default_audience: str) -> tuple[str, str]:
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if not fm:
        return default_audience, raw
    m = re.search(r"audience:\s*(\w+)", fm.group(1))
    audience = default_audience
    if m:
        audience = "internal" if m.group(1).lower() == "internal" else "public"
    return audience, raw[fm.end():]


def _audience_from_path(path: Path) -> str:
    return "internal" if "internal" in (p.lower() for p in path.parts) else "public"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "doc"


def _pretty(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip().capitalize()


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
