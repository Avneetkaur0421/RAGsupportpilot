"""Step 3: the agent, as a LangGraph state machine.

                 +--------------+
  question  ---> | contextualize|  follow-up? rewrite it as a standalone question
                 +--------------+
                        |
                 +--------------+
                 |   retrieve   |  vector search (customers: public docs only)
                 +--------------+
                        |  any passage relevant enough?
               yes      v               no
                 +--------------+       |
                 |   generate   |       |   (any chat model: see providers.py)
                 +--------------+       |
                        | confident?    |
               yes      v     no        v
                 +----------+     +----------+
                 | respond  |     | escalate |  -> review queue
                 +----------+     +----------+

Each node is a plain function: it reads the state dict and returns the
fields it wants to update. LangGraph handles the wiring.
"""
import re
from typing import Literal, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from . import config, providers, vectorstore


class State(TypedDict, total=False):
    question: str
    audience: Literal["customer", "team"]
    history: list[dict]          # earlier [{"question": ..., "answer": ...}]
    search_query: str            # the question rewritten to stand on its own
    passages: list[dict]
    answer: str
    confidence: Literal["high", "medium", "low"]
    topic: str
    missing: str
    status: Literal["answered", "escalated"]
    skipped_llm: bool


class GradedAnswer(BaseModel):
    """The structured output we ask the model for. Pydantic validates it."""
    answer: str = Field(description="Answer with [P1]-style markers after every fact")
    confidence: Literal["high", "medium", "low"] = Field(
        description="high: passages fully answer it. medium: mostly. low: not answered, "
                    "or it needs a human decision or account-specific data")
    topic: str = Field(description="1 to 3 word topic in English, e.g. 'Refund timing'")
    missing: str = Field(default="", description="What information is missing, or empty")


REWRITE_PROMPT = """Here is a conversation and a follow-up question.
Rewrite the follow-up as one standalone question that makes sense without the conversation.
Keep its meaning and language. Reply with only the question.

Conversation:
{conversation}

Follow-up question: {question}"""

ANSWER_PROMPT = """You are the assistant for {org}. You are answering {who}.
Answer using ONLY the numbered passages below. Never use outside knowledge or invent details.

Rules:
- Reply in the same language as the question.
- Cite every fact with its passage marker right after it, like [P1] or [P2][P3].
- Keep the answer under 120 words, in plain sentences. No markdown.
- Passages may come from tables (rows written as "Column: value"); read them carefully.
- Use confidence "low" if the passages don't contain the answer, or if the question needs a
  human decision or account-specific data (discounts, exceptions, a specific order's status).
- If confidence is low, say briefly what the passages do confirm, or that it isn't covered. Don't guess.
{conversation}
Passages:
{passages}

Question: {question}"""


def _llm():
    # Whichever provider is set in .env (Claude, GPT, Gemini, a local model...).
    # Created lazily so tests can run without an API key.
    return providers.chat_model(max_tokens=800)


def _text(response) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    return str(content).strip()


def _recent(state: State) -> list[dict]:
    return (state.get("history") or [])[-config.HISTORY_TURNS:]


# ---------- nodes ----------

def contextualize(state: State, llm=None) -> State:
    history = _recent(state)
    if not history:  # first question: nothing to rewrite, no model call
        return {"search_query": state["question"]}
    conversation = "\n".join(f"User: {h['question']}\nAssistant: {h['answer']}" for h in history)
    rewritten = _text((llm or _llm()).invoke(
        REWRITE_PROMPT.format(conversation=conversation, question=state["question"])))
    return {"search_query": rewritten.strip('"')[:500] or state["question"]}


def retrieve(state: State) -> State:
    query = state.get("search_query") or state["question"]
    hits = vectorstore.search(query, state["audience"], config.TOP_K)
    return {"passages": [h for h in hits if h["relevance"] >= config.MIN_RELEVANCE]}


def generate(state: State, llm=None) -> State:
    passages = "\n\n".join(
        f"[P{i}] ({p['doc_title']} > {p['heading']}"
        f"{', internal' if p['audience'] == 'internal' else ''})\n{p['text']}"
        for i, p in enumerate(state["passages"], 1))
    history = _recent(state)
    conversation = ("\nEarlier conversation (context only, not a source):\n" + "\n".join(
        f"User: {h['question']}\nAssistant: {h['answer']}" for h in history) + "\n") if history else ""
    org = config.ORG_NAME + (f", {config.ORG_DESCRIPTION}" if config.ORG_DESCRIPTION else "")
    prompt = ANSWER_PROMPT.format(
        org=org, who="a member of the team" if state["audience"] == "team" else "a customer",
        conversation=conversation, passages=passages, question=state["question"])
    result: GradedAnswer = (llm or _llm()).with_structured_output(GradedAnswer).invoke(prompt)
    return {"answer": result.answer, "confidence": result.confidence,
            "topic": result.topic.strip().capitalize() or "General", "missing": result.missing}


def respond(state: State) -> State:
    return {"status": "answered"}


def escalate(state: State) -> State:
    if not state.get("passages"):
        # Nothing relevant was found, so we never called the model.
        return {"status": "escalated", "skipped_llm": True, "confidence": "low",
                "topic": "Not covered", "missing": "No passage matched the question.",
                "answer": "This isn't covered in the approved sources, so I've passed it to the team."}
    return {"status": "escalated"}


# ---------- routing ----------

def after_retrieve(state: State) -> str:
    return "generate" if state["passages"] else "escalate"


def after_generate(state: State) -> str:
    return "escalate" if state["confidence"] == "low" else "respond"


def build_graph(llm=None):
    g = StateGraph(State)
    g.add_node("contextualize", lambda s: contextualize(s, llm))
    g.add_node("retrieve", retrieve)
    g.add_node("generate", lambda s: generate(s, llm))
    g.add_node("respond", respond)
    g.add_node("escalate", escalate)
    g.set_entry_point("contextualize")
    g.add_edge("contextualize", "retrieve")
    g.add_conditional_edges("retrieve", after_retrieve, {"generate": "generate", "escalate": "escalate"})
    g.add_conditional_edges("generate", after_generate, {"respond": "respond", "escalate": "escalate"})
    g.add_edge("respond", END)
    g.add_edge("escalate", END)
    return g.compile()


def cited_numbers(answer: str) -> set[int]:
    """Which [Pn] markers did the answer actually use?"""
    return {int(n) for n in re.findall(r"\[P(\d+)\]", answer or "")}
