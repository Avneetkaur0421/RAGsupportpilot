"""Step 4: the API the React UI talks to.

Run from the backend folder:  uvicorn app.main:app --reload
Interactive docs:             http://localhost:8000/docs
"""
import re
from collections import Counter
from contextlib import asynccontextmanager
from typing import Literal

from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import config, store, vectorstore
from .graph import _llm, build_graph, cited_numbers
from .ingest import SUPPORTED, load_file, load_folder, parse_markdown

agent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent
    store.init()
    vectorstore.upsert(load_folder(config.DOCS_DIR))  # safe to repeat: upsert by passage id
    agent = build_graph()
    yield


app = FastAPI(title="SupportPilot API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173"],
                   allow_methods=["*"], allow_headers=["*"])


# ---------- request shapes ----------

class AskIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    audience: Literal["customer", "team"] = "customer"


class ResolveIn(BaseModel):
    reply: str = Field(min_length=1)
    add_to_kb: bool = True


class DocIn(BaseModel):
    title: str = Field(min_length=1)
    audience: Literal["public", "internal"] = "public"
    text: str = Field(min_length=1)


# ---------- endpoints ----------

@app.get("/api/health")
def health():
    return {"ok": True, "model": config.LLM_MODEL}


@app.post("/api/ask")
def ask(body: AskIn):
    try:
        result = agent.invoke({"question": body.question, "audience": body.audience})
    except Exception as e:  # e.g. missing API key, network error
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
        "skipped_llm": result.get("skipped_llm", False), "passages": passages,
        "review_id": review_id,
    }


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
        md = f"# Support team answers\n\n## {review['question']}\n{body.reply.strip()}\n"
        _add_markdown("Support team answers", audience, md)
    return {"ok": True}


@app.get("/api/documents")
def documents():
    return vectorstore.all_documents()


@app.post("/api/documents")
def add_document(body: DocIn):
    text = body.text if body.text.lstrip().startswith("#") else f"# {body.title}\n\n{body.text}"
    count = _add_markdown(body.title, body.audience, text)
    if not count:
        raise HTTPException(400, "No text found to add.")
    return {"ok": True, "passages": count}


@app.post("/api/documents/upload")
async def upload_document(file: UploadFile = File(...), title: str = Form(""),
                          audience: Literal["public", "internal"] = Form("public")):
    """Upload a .pdf, .docx, .md or .txt file. LangChain loads and splits it."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED:
        raise HTTPException(400, f"Unsupported file type. Use one of: {', '.join(sorted(SUPPORTED))}.")
    content = await file.read()
    if len(content) > config.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(400, f"File is larger than {config.MAX_UPLOAD_MB} MB.")

    title = title.strip() or Path(file.filename).stem
    key = store.add_doc(title, audience, f"[uploaded file] {file.filename}")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved = config.UPLOAD_DIR / f"{key}{ext}"
    saved.write_bytes(content)  # keep the original for re-ingesting later

    try:
        chunks = load_file(saved, audience=audience, title=title, doc_id=f"added-{key}")
    except Exception as e:
        raise HTTPException(400, f"Couldn't read the file ({e.__class__.__name__}).")
    if not chunks:
        raise HTTPException(400, "No text found. If this is a scanned PDF, it needs OCR first.")
    vectorstore.upsert(chunks)
    return {"ok": True, "passages": len(chunks)}


def _add_markdown(title: str, audience: str, markdown: str) -> int:
    doc_id = "added-" + store.add_doc(title, audience, markdown)
    chunks = parse_markdown(doc_id, markdown, default_audience=audience)
    for c in chunks:
        c.doc_title, c.audience = title, audience
    vectorstore.upsert(chunks)
    return len(chunks)


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
    prompt = (f"These questions to {config.COMPANY} couldn't be answered from its support docs:\n"
              + "\n".join(f"- {q}" for q in questions)
              + "\n\nGroup them into at most 5 documentation gaps. For each, give a short page or "
                "section title and one sentence on what the docs should cover.")
    try:
        return _llm().with_structured_output(GapList).invoke(prompt).model_dump()
    except Exception as e:
        raise HTTPException(502, f"Couldn't get suggestions ({e.__class__.__name__}).")
