# SupportPilot

A RAG customer-support assistant that answers only from approved documents, cites every source, and hands off anything it can't answer to a human review queue. Built with **Python (FastAPI + LangGraph + ChromaDB + Claude)** and a **React** UI.

Demo data is for Kestrel Cycles, a fictional e-bike brand.

## What it does

- **Grounded answers:** every fact carries a `[P1]`-style marker linked to the passage it came from.
- **Customer vs team access:** internal guides (like refund approval limits) are only searched for support-team questions.
- **Confidence-based handoff:** low-confidence or out-of-scope questions go to a review queue instead of guessing.
- **Closing the loop:** a team member's reply can be added to the knowledge base, so the next identical question gets answered automatically.
- **Insights:** top topics, most-used sources, documentation gaps, and AI-suggested doc updates.

## How it works

```
question
   |
retrieve  -- ChromaDB vector search (customers: public docs only)
   |
   |-- nothing relevant? --> escalate (skips the model, saves cost)
   |
generate  -- Claude answers from the passages + rates its confidence (structured output)
   |
   |-- confidence low?    --> escalate --> review queue
   |
respond
```

| File | Role |
|---|---|
| `backend/app/ingest.py` | LangChain loaders read .md, .txt, .pdf and .docx; LangChain splitters cut them into passages |
| `backend/app/vectorstore.py` | Stores and searches passages in ChromaDB |
| `backend/app/graph.py` | The LangGraph agent: retrieve, generate, respond, escalate |
| `backend/app/store.py` | SQLite for logs, the review queue and added docs |
| `backend/app/main.py` | FastAPI endpoints the UI calls |
| `backend/data/docs/` | The knowledge base: drop .md, .txt, .pdf or .docx files here |
| `frontend/src/` | React UI: Ask, Review queue, Insights, Knowledge base |

## Run it locally

You need Python 3.11+, Node 18+ and an Anthropic API key.

**1. Backend** (terminal 1)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # then paste your ANTHROPIC_API_KEY into .env
uvicorn app.main:app --reload
```

The first start downloads a small local embedding model (about 80 MB). API docs are at http://localhost:8000/docs.

**2. Frontend** (terminal 2)

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

**3. Tests** (no API key needed)

```bash
cd backend
pytest -q
```

## Try this demo flow

1. Ask "How long does a refund take?" and click a source marker.
2. Ask "Can I get a discount for buying 5 bikes for my company?" It's handed off to the review queue.
3. In **Review queue**, reply with "add to knowledge base" ticked, then ask the same question again.
4. Switch to **Support team** and ask "Can I approve a $450 refund myself?" to see internal guides used.
5. Open **Insights**.

## Adding documents

Two ways:

- **Folder:** drop files into `backend/data/docs/` and restart the backend.
- **UI:** upload a file (or paste text) on the Knowledge base tab.

Supported: `.md`, `.txt`, `.pdf`, `.docx`. How each is split:

| Type | Loaded with | Split into |
|---|---|---|
| Markdown | text | One passage per `## heading` (via `MarkdownHeaderTextSplitter`) |
| PDF | `PyPDFLoader` | One passage per page |
| Word | `Docx2txtLoader` | Passages by paragraph |
| Text | text | Passages by paragraph |

Any passage longer than `CHUNK_SIZE` is cut further by `RecursiveCharacterTextSplitter`, with `CHUNK_OVERLAP` characters shared between neighbours.

**Who can see a document:** markdown can set `audience: internal` in front matter. For other files, put them in a folder named `internal` (for example `data/docs/internal/refund-limits.pdf`). Everything else is customer-facing.

**Scanned PDFs** are images with no text layer, so they come out empty. Run them through OCR first.

## Settings (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | Use `claude-sonnet-5-5` for higher-quality answers |
| `TOP_K` | `4` | Passages retrieved per question |
| `MIN_RELEVANCE` | `0.30` | Passages below this score are ignored |
| `CHUNK_SIZE` | `800` | Maximum characters per passage |
| `CHUNK_OVERLAP` | `100` | Characters shared between neighbouring passages |

To reset all data, stop the backend and delete `backend/storage/`. Do this after changing the chunk settings, so old passages are cleared out.

**Note on `langchain-community`:** the PDF and Word loaders come from this package, which LangChain is winding down. It's pinned below version 0.5 so installs stay stable. If you need to move off it later, only `load_file()` in `ingest.py` changes: call `pypdf` and `docx2txt` directly and wrap the text in LangChain `Document` objects.

## Ideas for next steps

- OCR for scanned PDFs
- Website crawling as a source
- Conversation memory for follow-up questions
- Slack, WhatsApp or website widget channels
- Auth for the review queue, and Docker for deployment
