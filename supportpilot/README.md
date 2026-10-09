# SupportPilot

A RAG assistant that answers questions from **any set of documents**, cites every source, and hands off anything it can't answer to a human review queue. Point it at a client's files, set their name, and it's ready.

Built with **Python (FastAPI + LangGraph + LangChain + ChromaDB)** and a **React** UI. Works with **Claude, GPT, Gemini, Azure OpenAI, Groq/OpenRouter-style APIs, or free local models via Ollama**: switching is a `.env` change. Demo data is for Kestrel Cycles, a fictional e-bike brand.

## What it does

- **Any AI model:** pick the chat model and the embedding model in `.env`. No code changes.
- **Ingests almost anything:** PDF, Word, PowerPoint, Excel, CSV, HTML, JSON, Markdown, text, web pages, and images or scanned PDFs (read by the AI model).
- **Stays in sync:** drop, edit or delete files in `data/docs/` and click **Rescan**. Only changed files are re-read.
- **Grounded answers:** every fact carries a `[P1]`-style marker linked to the passage it came from.
- **Follow-up questions:** "and for accessories?" is rewritten into a full question before searching.
- **Answers in the user's language.**
- **Customer vs team access:** internal documents are only used for team questions.
- **Confidence-based handoff:** uncertain questions go to a review queue instead of guessing.
- **Closing the loop:** a team reply can be added to the knowledge base, so the same question is answered next time.
- **Adapts to the client:** the name, description and suggested starter questions all come from config and the loaded documents.
- **Insights:** top topics, most-used sources, documentation gaps, and AI-suggested doc updates.

## How it works

```
question (+ recent conversation)
   |
contextualize -- follow-up? rewrite as a standalone question (skipped for first questions)
   |
retrieve      -- ChromaDB vector search (customers: public docs only)
   |
   |-- nothing relevant? --> escalate (skips the model, saves cost)
   |
generate      -- the chat model answers from the passages + rates its confidence
   |
   |-- confidence low?    --> escalate --> review queue
   |
respond
```

| File | Role |
|---|---|
| `backend/app/providers.py` | Picks the chat and embedding models from `.env` (Claude, GPT, Gemini, Ollama...) |
| `backend/app/ingest.py` | Loads every file type into LangChain Documents and splits them into passages |
| `backend/app/knowledge.py` | Keeps the knowledge base in sync: docs folder, uploads, web pages, pasted text |
| `backend/app/vectorstore.py` | Stores and searches passages in ChromaDB |
| `backend/app/graph.py` | The LangGraph agent: contextualize, retrieve, generate, respond, escalate |
| `backend/app/store.py` | SQLite for logs, the review queue, and the list of sources |
| `backend/app/main.py` | FastAPI endpoints the UI calls |
| `backend/data/docs/` | Drop any supported file here |
| `frontend/src/` | React UI: Ask, Review queue, Insights, Knowledge base |

## Run it locally

You need Python 3.11+, Node 18+, and an API key for your chosen model (or Ollama for free local models).

**1. Backend** (terminal 1)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # Windows: copy .env.example .env   then pick a provider and add its key
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

## Adding documents

Three ways:

- **Docs folder:** put files in `backend/data/docs/`, then click **Rescan docs folder** (or restart the backend).
- **Upload or paste:** on the Knowledge base tab.
- **Web page:** paste a public address on the Knowledge base tab.

| Type | How it's read | Split into |
|---|---|---|
| Markdown, text | as text | One passage per `## heading` |
| PDF | `PyPDFLoader` | One passage per page |
| Scanned PDF | the AI model reads it | By headings the model finds |
| Word | `Docx2txtLoader` | By paragraph |
| PowerPoint | `python-pptx` | One passage per slide, with speaker notes |
| Excel, CSV | `openpyxl` / `csv` | Groups of rows, each written as `Column: value` |
| HTML | `BSHTMLLoader` | By paragraph (tags and scripts removed) |
| JSON | flattened | `path.to.field: value` lines |
| Images | the AI model reads them | Text, tables and a sentence per diagram |
| Web page | `WebBaseLoader` | By paragraph |

Anything longer than `CHUNK_SIZE` is cut further by `RecursiveCharacterTextSplitter`, with `CHUNK_OVERLAP` characters shared between neighbours.

**Who can see a document:** put team-only files in a folder named `internal` (for example `data/docs/internal/refund-limits.pdf`), or add `audience: internal` front matter to markdown. Uploads and web pages have a dropdown. Everything else is customer-facing.

## Choose your AI model

Everything model-related lives in `app/providers.py`, and you pick in `backend/.env`. `.env.example` has a ready-made block for each option.

| `LLM_PROVIDER` | Models | Needs |
|---|---|---|
| `anthropic` | Claude (default) | `ANTHROPIC_API_KEY` |
| `openai` | GPT models | `OPENAI_API_KEY` |
| `openai` + `OPENAI_BASE_URL` | Any OpenAI-compatible service: Groq, OpenRouter, DeepSeek, Together, vLLM, LM Studio | that service's key and URL |
| `azure` | Azure OpenAI (`LLM_MODEL` = deployment name) | `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT`, `OPENAI_API_VERSION` |
| `google` | Gemini with an API key | `GOOGLE_API_KEY` |
| `vertexai` | Gemini on Google Cloud | `pip install langchain-google-vertexai` and gcloud login |
| `ollama` | Free local models (Llama, Qwen, Mistral...) | Ollama running locally |

**Embeddings** are separate (`EMBEDDING_PROVIDER`): `local` (free, default), `openai`, `azure`, `google`, `vertexai` or `ollama`. Switching is safe: each embedding model gets its own collection, and existing passages are copied over and re-embedded automatically on the next start.

**Things to check when you switch:**
- The model must support **structured output** (all the providers above do, but very small local models can be unreliable at it).
- Reading **images and scanned PDFs** needs a model that accepts them (Claude, GPT-4o class, Gemini). With text-only models, set `VISION_EXTRACT=false`.
- `MIN_RELEVANCE` may need tuning for a new embedding model, since each scores similarity differently. Ask a few questions and check the relevance bars in the trace panel.

**Adding another provider** (for example Bedrock or Mistral): add one `if provider == "...":` block to `chat_model()` in `providers.py`. Nothing else changes.

## Reuse it for a new client

1. Set `ORG_NAME` and `ORG_DESCRIPTION` in `.env`.
2. Delete the demo files in `backend/data/docs/` and add the client's files.
3. Delete `backend/storage/` and restart.

Suggested questions in the UI are generated from the new documents automatically.

## Settings (`backend/.env`)

| Variable | Default | Meaning |
|---|---|---|
| `ORG_NAME` | `Kestrel Cycles` | Who the assistant works for |
| `ORG_DESCRIPTION` | `a fictional e-bike brand` | One line about them (can be empty) |
| `LLM_PROVIDER` | `anthropic` | Which chat model service (see above) |
| `LLM_MODEL` | `claude-haiku-4-5-20251001` | The model name at that provider |
| `EMBEDDING_PROVIDER` | `local` | Which embedding service |
| `EMBEDDING_MODEL` | (empty) | Required for any provider except `local` |
| `OPENAI_BASE_URL` | (empty) | For OpenAI-compatible services |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Where Ollama runs |
| `TOP_K` | `4` | Passages retrieved per question |
| `MIN_RELEVANCE` | `0.30` | Passages below this score are ignored |
| `CHUNK_SIZE` | `800` | Maximum characters per passage |
| `CHUNK_OVERLAP` | `100` | Characters shared between neighbouring passages |
| `VISION_EXTRACT` | `true` | Let the chat model read images and scanned PDFs (one call per file) |
| `HISTORY_TURNS` | `3` | Earlier exchanges used for follow-up questions |
| `MAX_UPLOAD_MB` | `25` | Upload size limit |

To reset all data, stop the backend and delete `backend/storage/`. Do this after changing the chunk settings, so old passages are cleared out.

## Costs to know

- **Embeddings** run locally by default, so they're free. Cloud embeddings cost a little per document and per question.
- **With Ollama,** everything runs on your machine at no API cost, but answers are slower and usually lower quality than cloud models.
- **Each question** is one chat model call, plus one more for follow-ups. Questions with no relevant passage skip the model entirely.
- **Each image or scanned PDF** is one model call when it's added. Unchanged files aren't re-read on rescan.
- **Suggested questions** are one model call each time the knowledge base changes.

## Notes and limits

- **`langchain-community`** provides the PDF, Word, HTML and web loaders. LangChain is winding this package down, so it's pinned below version 0.5. If you move off it later, only `ingest.py` changes.
- **Very large spreadsheets** are capped at 5,000 rows per sheet. For numeric questions over big tables ("total sales in Q3"), a SQL agent is a better fit than RAG.
- **Web pages** must be public. Pages that need a login or load content with JavaScript may come back empty.
- **Scanned PDFs** are sent to the model in one request, so very long scans should be split first.

## Ideas for next steps

- Website crawling (whole sites, not single pages)
- Google Drive, SharePoint or Notion as live sources
- Slack, WhatsApp or website widget channels
- Auth for the review queue, and Docker for deployment
