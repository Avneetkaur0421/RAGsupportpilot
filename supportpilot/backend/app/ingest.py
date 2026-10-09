"""Step 1 of RAG: turn any document into passages ("chunks"), using LangChain.

Pipeline:  LOAD  ->  SPLIT  ->  CHUNK cards

LOAD   Each file type has a loader that returns LangChain Document objects:
         Document(page_content="the text", metadata={"heading": ..., ...})

         .md .txt            read as text (markdown headings kept)
         .pdf                PyPDFLoader, one Document per page
                             (scanned PDF with no text -> the chat model reads it)
         .docx               Docx2txtLoader
         .pptx               python-pptx, one Document per slide (+ speaker notes)
         .xlsx .csv          one line per row: "Column: value; Column: value"
         .html .htm          BSHTMLLoader (strips tags and scripts)
         .json               flattened to "path.to.field: value" lines
         .png .jpg .webp     the chat model reads the image (text, tables, diagrams)
         web URL             WebBaseLoader

SPLIT  Markdown is cut at "#" / "##" headings by MarkdownHeaderTextSplitter.
       Then RecursiveCharacterTextSplitter cuts anything longer than CHUNK_SIZE,
       with CHUNK_OVERLAP characters shared between neighbours.

CHUNK  Every piece becomes our own Chunk card, so the rest of the app never
       needs to know which file type it came from.

Who can see a document ("audience"):
  - Markdown can say so in front matter:  ---\\naudience: internal\\n---
  - Files inside a folder named "internal" are internal.
  - Everything else is public.
"""
import base64
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from . import config

# extension -> human-readable kind (shown in the UI)
SUPPORTED = {
    ".md": "Markdown", ".markdown": "Markdown", ".txt": "Text",
    ".pdf": "PDF", ".docx": "Word", ".pptx": "PowerPoint",
    ".xlsx": "Excel", ".xlsm": "Excel", ".csv": "CSV",
    ".html": "Web page", ".htm": "Web page", ".json": "JSON",
    ".png": "Image", ".jpg": "Image", ".jpeg": "Image", ".webp": "Image", ".gif": "Image",
}
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}
MAX_TABLE_ROWS = 5000   # per sheet, to keep huge spreadsheets manageable


@dataclass
class Chunk:
    pid: str          # passage id, e.g. "f-returns#3"
    doc_id: str
    doc_title: str
    heading: str      # section, page, slide or row range
    text: str
    audience: str     # "public" or "internal"
    kind: str = "Text"


# ---------- splitting ----------

_header_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "title"), ("##", "heading")], strip_headers=True)


def _size_splitter() -> RecursiveCharacterTextSplitter:
    return RecursiveCharacterTextSplitter(
        chunk_size=config.CHUNK_SIZE, chunk_overlap=config.CHUNK_OVERLAP,
        separators=["\n\n", "\n", ". ", " ", ""])


def _to_chunks(doc_id, title, audience, kind, docs: list[Document]) -> list[Chunk]:
    """Split Documents to size and turn them into Chunk cards."""
    docs = [d for d in docs if d.page_content.strip()]
    chunks = []
    for i, piece in enumerate(_size_splitter().split_documents(docs), 1):
        text = _clean(piece.page_content)
        if text:
            heading = piece.metadata.get("heading") or f"Part {i}"
            chunks.append(Chunk(f"{doc_id}#{len(chunks) + 1}", doc_id, title, heading, text, audience, kind))
    return chunks


# ---------- public functions ----------

def parse_markdown(doc_id: str, raw: str, default_audience: str = "public",
                   title: str | None = None, kind: str = "Markdown") -> list[Chunk]:
    """Markdown or plain text -> chunks, one per ## section where possible."""
    audience, body = _read_front_matter(raw, default_audience)
    sections = _header_splitter.split_text(body)
    for s in sections:
        if not s.metadata.get("heading") and s.metadata.get("title"):
            s.metadata["heading"] = "Overview"
    doc_title = title or next((s.metadata["title"] for s in sections if s.metadata.get("title")), _pretty(doc_id))
    return _to_chunks(doc_id, doc_title, audience, kind, sections)


def load_file(path: Path, audience: str | None = None, title: str | None = None,
              doc_id: str | None = None) -> list[Chunk]:
    """Any supported file -> chunks. Raises ValueError for unsupported or unreadable files."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise ValueError(f"Unsupported file type: {ext or 'no extension'}")
    kind = SUPPORTED[ext]
    doc_id = doc_id or _slug(path.stem)
    audience = audience or _audience_from_path(path)
    title = title or None

    if ext in {".md", ".markdown", ".txt"}:
        return parse_markdown(doc_id, path.read_text(encoding="utf-8", errors="replace"), audience, title, kind)

    if ext in IMAGE_TYPES:
        text = vision_extract(path.read_bytes(), IMAGE_TYPES[ext])
        return parse_markdown(doc_id, text, audience, title or _pretty(path.stem), kind)

    if ext == ".pdf":
        from langchain_community.document_loaders import PyPDFLoader
        docs = [d for d in PyPDFLoader(str(path)).load() if d.page_content.strip()]
        if not docs:  # scanned PDF: pages are pictures with no text layer
            text = vision_extract(path.read_bytes(), "application/pdf")
            return parse_markdown(doc_id, text, audience, title or _pretty(path.stem), "PDF (scanned)")
        for d in docs:
            d.metadata["heading"] = f"Page {d.metadata.get('page', 0) + 1}"
    elif ext == ".docx":
        from langchain_community.document_loaders import Docx2txtLoader
        docs = Docx2txtLoader(str(path)).load()
    elif ext == ".pptx":
        docs = _load_pptx(path)
    elif ext in {".xlsx", ".xlsm"}:
        docs = _table_docs(_read_xlsx(path))
    elif ext == ".csv":
        docs = _table_docs([("Sheet", _read_csv(path))])
    elif ext in {".html", ".htm"}:
        from langchain_community.document_loaders import BSHTMLLoader
        docs = BSHTMLLoader(str(path), open_encoding="utf-8").load()
        title = title or (docs[0].metadata.get("title") if docs else None)
    elif ext == ".json":
        lines = _flatten_json(json.loads(path.read_text(encoding="utf-8")))
        docs = [Document(page_content="\n".join(lines))]

    return _to_chunks(doc_id, title or _pretty(path.stem), audience, kind, docs)


def load_url(url: str, audience: str = "public", title: str | None = None,
             doc_id: str | None = None) -> list[Chunk]:
    """A public web page -> chunks."""
    from langchain_community.document_loaders import WebBaseLoader
    docs = WebBaseLoader(web_paths=[url]).load()
    page_title = (docs[0].metadata.get("title") or "").strip() if docs else ""
    return _to_chunks(doc_id or _slug(url), title or page_title or url, audience, "Web page", docs)


def vision_extract(data: bytes, media_type: str) -> str:
    """Ask the chat model to read an image or scanned PDF and return its text as markdown.

    Uses LangChain's standard content blocks, which each provider package
    translates into its own format, so this works with Claude, GPT and Gemini.
    """
    if not config.VISION_EXTRACT:
        raise ValueError("This file has no text layer. Set VISION_EXTRACT=true to let the model read it.")
    from langchain_core.messages import HumanMessage
    from . import providers

    block_type = "file" if media_type == "application/pdf" else "image"
    message = HumanMessage(content=[
        {"type": block_type, "base64": base64.b64encode(data).decode(), "mime_type": media_type},
        {"type": "text", "text": (
            "Extract all the text from this file so it can be searched. Use '## ' lines for "
            "headings, write each table row as 'Column: value; Column: value', and describe any "
            "chart or diagram in one sentence. Return only the extracted content.")},
    ])
    try:
        content = providers.chat_model(max_tokens=4000).invoke([message]).content
    except providers.ProviderError:
        raise
    except Exception as e:
        raise ValueError(f"The model ({config.LLM_PROVIDER}: {config.LLM_MODEL}) couldn't read this file. "
                         f"It may not support {'PDFs' if block_type == 'file' else 'images'} "
                         f"({e.__class__.__name__}).")
    return content if isinstance(content, str) else "".join(
        part.get("text", "") for part in content if isinstance(part, dict))


# ---------- file-type helpers ----------

def _load_pptx(path: Path) -> list[Document]:
    from pptx import Presentation
    docs = []
    for n, slide in enumerate(Presentation(str(path)).slides, 1):
        parts = []
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    parts.append(" | ".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            parts.append("Notes: " + slide.notes_slide.notes_text_frame.text)
        title = slide.shapes.title.text.strip() if slide.shapes.title is not None else ""
        heading = f"Slide {n}: {title}" if title else f"Slide {n}"
        docs.append(Document(page_content="\n".join(parts), metadata={"heading": heading}))
    return docs


def _read_xlsx(path: Path) -> list[tuple[str, list[list]]]:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    sheets = []
    for ws in wb.worksheets:
        rows = []
        for row in ws.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_TABLE_ROWS:
                break
        sheets.append((ws.title, rows))
    wb.close()
    return sheets


def _read_csv(path: Path) -> list[list]:
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as f:
        return [row for _, row in zip(range(MAX_TABLE_ROWS + 1), csv.reader(f))]


def _table_docs(sheets: list[tuple[str, list[list]]]) -> list[Document]:
    """Rows -> 'Column: value' lines, grouped into passages of about CHUNK_SIZE.

    Repeating the column name on every row means each passage makes sense
    on its own, which is what retrieval needs.
    """
    docs = []
    for sheet, rows in sheets:
        rows = [r for r in rows if any(v not in (None, "") for v in r)]
        if not rows:
            continue
        header = [str(h).strip() if h not in (None, "") else f"Column {i + 1}" for i, h in enumerate(rows[0])]
        lines, start = [], 2
        for row_no, row in enumerate(rows[1:], 2):
            line = "; ".join(f"{header[i] if i < len(header) else f'Column {i + 1}'}: {v}"
                             for i, v in enumerate(row) if v not in (None, ""))
            if lines and sum(len(l) for l in lines) + len(line) > config.CHUNK_SIZE:
                docs.append(Document(page_content="\n".join(lines),
                                     metadata={"heading": f"{sheet}, rows {start} to {row_no - 1}"}))
                lines, start = [], row_no
            lines.append(line)
        if lines:
            docs.append(Document(page_content="\n".join(lines),
                                 metadata={"heading": f"{sheet}, rows {start} to {start + len(lines) - 1}"}))
    return docs


def _flatten_json(value, prefix="") -> list[str]:
    if isinstance(value, dict):
        return [line for k, v in value.items() for line in _flatten_json(v, f"{prefix}.{k}" if prefix else str(k))]
    if isinstance(value, list):
        return [line for i, v in enumerate(value) for line in _flatten_json(v, f"{prefix}[{i}]")]
    return [f"{prefix or 'value'}: {value}"]


# ---------- small helpers ----------

def _read_front_matter(raw: str, default_audience: str) -> tuple[str, str]:
    fm = re.match(r"^---\s*\n(.*?)\n---\s*\n", raw, re.S)
    if not fm:
        return default_audience, raw
    m = re.search(r"audience:\s*(\w+)", fm.group(1))
    audience = ("internal" if m.group(1).lower() == "internal" else "public") if m else default_audience
    return audience, raw[fm.end():]


def _audience_from_path(path: Path) -> str:
    return "internal" if "internal" in (p.lower() for p in path.parts) else "public"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:80] or "doc"


def _pretty(name: str) -> str:
    return re.sub(r"[-_]+", " ", name).strip().capitalize()


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", re.sub(r"\s*\n\s*", "\n", text)).strip()
