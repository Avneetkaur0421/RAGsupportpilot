"""Step 4: the API the React UI talks to.

Run from the backend folder:  uvicorn app.main:app --reload
Interactive docs:             http://localhost:8000/docs
"""
import logging
import re
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, knowledge, providers, store, vectorstore
from .graph import _llm, build_graph, cited_numbers
from .ingest import SUPPORTED

log = logging.getLogger("supportpilot")
agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    store.init()
    result = knowledge.sync_folder()  # picks up any files added while the server was off
    log.warning("Knowledge base sync: %s", result)
    agent = build_graph()
    yield


app = FastAPI(title="SupportPilot API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------- request shapes ----------

class Turn(BaseModel):
    question: str
    answer: str


class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    audience: Literal["customer", "team"] = "customer"
    history: list[Turn] = Field(default_factory=list, max_length=10)


class ResolveIn(BaseModel):
    reply: str = Field(min_length=1)
    add_to_kb: bool = True


class TextIn(BaseModel):
    title: str = Field(min_length=1)
    audience: Literal["public", "internal"] = "public"
    text: str = Field(min_length=1)


class UrlIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    title: str = ""
    audience: Literal["public", "internal"] = "public"


# ---------- app info ----------

@app.get("/api/health")
def health():
    return {"ok": True, **providers.describe()}


_suggestion_cache = {"version": None, "data": None}


class Suggestions(BaseModel):
    customer: list[str]
    team: list[str]


@app.get("/api/config")
def app_config():
    """Name, description and starter questions, all based on what's loaded."""
    if _suggestion_cache["version"] != knowledge.version or _suggestion_cache["data"] is None:
        _suggestion_cache.update(version=knowledge.version, data=_make_suggestions())
    return {"org_name": config.ORG_NAME, "org_description": config.ORG_DESCRIPTION,
            "formats": sorted(SUPPORTED), "suggestions": _suggestion_cache["data"],
            "models": providers.describe()}


def _make_suggestions() -> dict:
    samples = vectorstore.sample_passages(12)
    if not samples:
        return {"customer": [], "team": []}
    public = [s for s in samples if s["audience"] == "public"]
    internal = [s for s in samples if s["audience"] == "internal"]
    listing = lambda rows: "\n".join(f"- {r['doc_title']} > {r['heading']}: {r['text'][:200]}" for r in rows)
    prompt = (f"Here are passages from {config.ORG_NAME}'s knowledge base.\n\n"
              f"Customer-facing passages:\n{listing(public) or '(none)'}\n\n"
              f"Internal team passages:\n{listing(internal) or '(none)'}\n\n"
              "Write short, natural questions these passages can answer: 4 a customer might ask, "
              "and 3 a team member might ask (use internal passages for those if there are any). "
              "Each under 12 words.")
    try:
        return _llm().with_structured_output(Suggestions).invoke(prompt).model_dump()
    except Exception:
        # No API key or a network problem: fall back to questions built from headings.
        q = lambda rows: [f"What do you have on {r['heading'].lower()}?" for r in rows[:4]]
        return {"customer": q(public), "team": q(internal or public)[:3]}


# ---------- asking ----------

@app.post("/api/ask")
def ask(body: AskIn):
    try:
        result = agent.invoke({"question": body.question, "audience": body.audience,
                               "history": [t.model_dump() for t in body.history]})
    except providers.ProviderError as e:  # setup problem: say exactly what to fix
        raise HTTPException(500, str(e))
    except Exception as e:  # e.g. missing API key, network error
        log.exception("ask failed")
        raise HTTPException(502, f"The assistant couldn't answer ({e.__class__.__name__}). Check the backend logs.")

    passages = result.get("passages", [])
    cited = cited_numbers(result.get("answer", ""))
    for i, p in enumerate(passages, 1):
        p["n"], p["cited"] = i, i in cited
    sources = sorted({p["doc_title"] for p in passages if p["cited"]})

    store.add_log(body.question, body.audience, result.get("topic"), result.get("confidence"),
                  result["status"], sources)
    review_id = None
    if result["status"] == "escalated":
        draft = "" if result.get("skipped_llm") else re.sub(r"\[P\d+\]", "", result.get("answer", ""))
        review_id = store.add_review(body.question, body.audience, result.get("topic"),
                                     draft, result.get("missing", ""))

    return {
        "question": body.question, "audience": body.audience, "status": result["status"],
        "answer": result.get("answer", ""), "confidence": result.get("confidence"),
        "topic": result.get("topic"), "missing": result.get("missing", ""),
        "search_query": result.get("search_query", body.question),
        "skipped_llm": result.get("skipped_llm", False), "passages": passages,
        "review_id": review_id,
    }


# ---------- review queue ----------

@app.get("/api/reviews")
def reviews():
    return store.list_reviews()


@app.post("/api/reviews/{rid}/resolve")
def resolve(rid: str, body: ResolveIn):
    review = store.get_review(rid)
    if not review:
        raise HTTPException(404, "Review not found.")
    store.resolve_review(rid, body.reply.strip())
    if body.add_to_kb:
        # Closing the loop: the team's answer becomes a new searchable passage.
        audience = "internal" if review["audience"] == "team" else "public"
        knowledge.add_text("Team answers", audience, f"## {review['question']}\n{body.reply.strip()}",
                           key=rid, origin="team")
    return {"ok": True}


# ---------- knowledge base ----------

@app.get("/api/documents")
def documents():
    sources = {s["doc_id"]: s for s in store.list_sources()}
    docs = vectorstore.all_documents()
    for d in docs:
        src = sources.get(d["doc_id"], {})
        d["origin"], d["location"] = src.get("origin", "folder"), src.get("location", "")
        d["deletable"] = d["origin"] != "folder"  # folder files are removed by deleting the file
    return docs


@app.post("/api/documents/sync")
def sync_documents():
    """Re-scan data/docs after adding, editing or deleting files there."""
    return knowledge.sync_folder()


@app.post("/api/documents")
def add_text_document(body: TextIn):
    try:
        count = knowledge.add_text(body.title.strip(), body.audience, body.text, key=store.new_id())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "passages": count}


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...), title: str = Form(""),
                          audience: Literal["public", "internal"] = Form("public")):
    """Upload any supported file. LangChain (or the chat model, for images) extracts the text."""
    name = file.filename or "upload"
    ext = Path(name).suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type. Supported: {', '.join(sorted(SUPPORTED))}.")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File is larger than {config.MAX_UPLOAD_MB} MB.")

    key = store.new_id()
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = config.UPLOAD_DIR / f"{key}{ext}"
    saved.write_bytes(content)  # keep the original
    try:
        count = knowledge.add_file(saved, name, title.strip() or Path(name).stem, audience, key)
    except (ValueError, providers.ProviderError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("upload failed")
        raise HTTPException(400, f"Couldn't read the file ({e.__class__.__name__}).")
    return {"ok": True, "passages": count}


@app.post("/api/documents/url")
def add_url_document(body: UrlIn):
    try:
        count = knowledge.add_url(body.url.strip(), body.title.strip(), body.audience)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        log.exception("url failed")
        raise HTTPException(400, f"Couldn't read that page ({e.__class__.__name__}).")
    return {"ok": True, "passages": count}


@app.delete("/api/documents/{doc_id}")
def delete_document(doc_id: str):
    source = next((s for s in store.list_sources() if s["doc_id"] == doc_id), None)
    if not source:
        raise HTTPException(404, "Document not found.")
    if source["origin"] == "folder":
        raise HTTPException(400, "This file lives in the docs folder. Delete the file there, then sync.")
    knowledge.remove(doc_id)
    return {"ok": True}


# ---------- insights ----------

@app.get("/api/insights")
def insights():
    logs = store.list_logs()
    reviews = store.list_reviews()
    total = len(logs)
    answered = sum(1 for l in logs if l["status"] == "answered")
    return {
        "total": total,
        "answered_pct": round(answered / total * 100) if total else 0,
        "escalated": total - answered,
        "open_reviews": sum(1 for r in reviews if r["status"] == "open"),
        "top_topics": Counter(l["topic"] or "General" for l in logs).most_common(8),
        "top_sources": Counter(s for l in logs for s in l["sources"]).most_common(8),
        "gaps": [{"question": l["question"], "topic": l["topic"], "created_at": l["created_at"]}
                 for l in logs if l["status"] == "escalated"][:10],
    }


class Gap(BaseModel):
    title: str
    add: str


class GapList(BaseModel):
    gaps: list[Gap]


@app.post("/api/insights/suggest")
def suggest_doc_updates():
    questions = [g["question"] for g in insights()["gaps"]]
    if not questions:
        return {"gaps": []}
    prompt = (f"These questions to {config.ORG_NAME} couldn't be answered from its knowledge base:\n"
              + "\n".join(f"- {q}" for q in questions)
              + "\n\nGroup them into at most 5 documentation gaps. For each, give a short page or "
                "section title and one sentence on what the docs should cover.")
    try:
        return _llm().with_structured_output(GapList).invoke(prompt).model_dump()
    except Exception as e:
        raise HTTPException(502, f"Couldn't get suggestions ({e.__class__.__name__}).")
