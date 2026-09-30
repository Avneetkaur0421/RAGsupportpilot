"""Step 3: the agent, as a LangGraph state machine.

            +----------+
 question ->| retrieve |
            +----------+
                 |  any passage relevant enough?
         yes     v            no
            +----------+      |
            | generate |      |
            +----------+      |
                 | confident? |
         yes     v    no      v
            +---------+   +----------+
            | respond |   | escalate |   -> review queue
            +---------+   +----------+

Each node is a plain function: it reads the state dict and returns the
fields it wants to update. LangGraph handles the wiring.
"""
import re
from typing import Literal, TypedDict

from langchain_anthropic import ChatAnthropic
from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from . import config, vectorstore


class State(TypedDict, total=False):
    question: str
    audience: Literal["customer", "team"]
    passages: list[dict]
    answer: str
    confidence: Literal["high", "medium", "low"]
    topic: str
    missing: str
    status: Literal["answered", "escalated"]
    skipped_llm: bool


class GradedAnswer(BaseModel):
    """The structured output we ask Claude for. Pydantic validates it."""
    answer: str = Field(description="Answer with [P1]-style markers after every fact")
    confidence: Literal["high", "medium", "low"] = Field(
        description="high: passages fully answer it. medium: mostly. low: not answered, "
                    "or it needs a human decision or account-specific data")
    topic: str = Field(description="1 to 3 word topic, e.g. 'Refund timing'")
    missing: str = Field(default="", description="What information is missing, or empty")


PROMPT = """You are the support assistant for {company}. You are answering {who}.
Answer the question using ONLY the numbered passages below. Never use outside knowledge or invent details.

Rules:
- Cite every fact with its passage marker right after it, like [P1] or [P2][P3].
- Keep the answer under 90 words, in plain sentences. No markdown.
- Use confidence "low" if the passages don't contain the answer, or if the question needs a human
  decision or account-specific data (discounts, exceptions, a specific order's status).
- If confidence is low, say briefly what the passages do confirm, or that it isn't covered. Don't guess.

Passages:
{passages}

Question: {question}"""


def _llm():
    # Created lazily so tests can run without an API key.
    return ChatAnthropic(model=config.LLM_MODEL, temperature=0, max_tokens=600)


# ---------- nodes ----------

def retrieve(state: State) -> State:
    hits = vectorstore.search(state["question"], state["audience"], config.TOP_K)
    kept = [h for h in hits if h["relevance"] >= config.MIN_RELEVANCE]
    return {"passages": kept}


def generate(state: State, llm=None) -> State:
    passages = "\n\n".join(
        f"[P{i}] ({p['doc_title']} > {p['heading']}"
        f"{', internal guide' if p['audience'] == 'internal' else ''})\n{p['text']}"
        for i, p in enumerate(state["passages"], 1))
    prompt = PROMPT.format(
        company=config.COMPANY,
        who="a member of the support team" if state["audience"] == "team" else "a customer",
        passages=passages, question=state["question"])
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
                "answer": "This isn't covered in the approved sources, so I've passed it to the support team."}
    return {"status": "escalated"}


# ---------- routing ----------

def after_retrieve(state: State) -> str:
    return "generate" if state["passages"] else "escalate"


def after_generate(state: State) -> str:
    return "escalate" if state["confidence"] == "low" else "respond"


def build_graph(llm=None):
    g = StateGraph(State)
    g.add_node("retrieve", retrieve)
    g.add_node("generate", lambda s: generate(s, llm))
    g.add_node("respond", respond)
    g.add_node("escalate", escalate)
    g.set_entry_point("retrieve")
    g.add_conditional_edges("retrieve", after_retrieve, {"generate": "generate", "escalate": "escalate"})
    g.add_conditional_edges("generate", after_generate, {"respond": "respond", "escalate": "escalate"})
    g.add_edge("respond", END)
    g.add_edge("escalate", END)
    return g.compile()


def cited_numbers(answer: str) -> set[int]:
    """Which [Pn] markers did the answer actually use?"""
    return {int(n) for n in re.findall(r"\[P(\d+)\]", answer or "")}
