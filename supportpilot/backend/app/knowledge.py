"""Keeps the knowledge base in sync with all its sources.

Sources can come from four places, and each is tracked in the SQLite
"sources" table so the app always knows what's loaded and where it came from:

  folder   files in data/docs (added, changed or deleted files are picked up by sync)
  upload   files uploaded in the UI
  url      web pages
  text     text pasted in the UI, and team replies from the review queue
"""
import ipaddress
import socket
from pathlib import Path
from urllib.parse import urlparse

from . import config, store, vectorstore
from .ingest import SUPPORTED, Chunk, _slug, load_file, load_url, parse_markdown

# Goes up whenever the knowledge base changes, so cached suggestions refresh.
version = 0


def _changed():
    global version
    version += 1


def _register(chunks: list[Chunk], origin: str, location: str, signature: str = "") -> int:
    if not chunks:
        raise ValueError("No text found in this source.")
    first = chunks[0]
    vectorstore.replace_document(first.doc_id, chunks)
    store.upsert_source(first.doc_id, first.doc_title, first.audience, first.kind,
                        origin, location, signature, len(chunks))
    _changed()
    return len(chunks)


def _signature(path: Path) -> str:
    st = path.stat()
    return f"{st.st_size}-{int(st.st_mtime)}"


def sync_folder() -> dict:
    """Bring the vector store in line with data/docs: add new files, re-read
    changed ones, remove deleted ones. Unchanged files are skipped, so this is
    cheap to run often (and images aren't re-read by the model every time)."""
    known = {s["location"]: s for s in store.list_sources() if s["origin"] == "folder"}
    result = {"added": 0, "updated": 0, "removed": 0, "unchanged": 0, "errors": []}
    seen = set()
    config.DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for path in sorted(config.DOCS_DIR.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        rel = path.relative_to(config.DOCS_DIR).as_posix()
        seen.add(rel)
        sig, old = _signature(path), known.get(rel)
        if old and old["signature"] == sig:
            result["unchanged"] += 1
            continue
        try:
            chunks = load_file(path, doc_id="f-" + _slug(str(Path(rel).with_suffix(""))))
            _register(chunks, "folder", rel, sig)
            result["updated" if old else "added"] += 1
        except Exception as e:
            result["errors"].append({"file": rel, "error": str(e) or e.__class__.__name__})

    for rel, old in known.items():
        if rel not in seen:
            remove(old["doc_id"])
            result["removed"] += 1

    # Clean up passages from older versions of the app that no source owns.
    owned = {s["doc_id"] for s in store.list_sources()}
    for orphan in vectorstore.doc_ids() - owned:
        vectorstore.delete_document(orphan)
    return result


def add_file(path: Path, filename: str, title: str, audience: str, key: str) -> int:
    chunks = load_file(path, audience=audience, title=title, doc_id=f"u-{key}")
    return _register(chunks, "upload", filename)


def add_text(title: str, audience: str, text: str, key: str, origin: str = "text") -> int:
    markdown = text if text.lstrip().startswith("#") else f"# {title}\n\n{text}"
    chunks = parse_markdown(f"t-{key}", markdown, default_audience=audience, title=title)
    for c in chunks:
        c.audience = audience  # the choice made in the UI wins over front matter
    return _register(chunks, origin, title)


def add_url(url: str, title: str, audience: str) -> int:
    check_public_url(url)
    chunks = load_url(url, audience=audience, title=title or None, doc_id="w-" + _slug(url))
    return _register(chunks, "url", url)


def remove(doc_id: str) -> None:
    vectorstore.delete_document(doc_id)
    store.delete_source(doc_id)
    _changed()


def check_public_url(url: str) -> None:
    """Only fetch public http(s) pages, never internal addresses like localhost."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Use a full web address starting with http:// or https://.")
    try:
        infos = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror:
        raise ValueError("That web address couldn't be found.")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError("Only public web pages can be added.")
