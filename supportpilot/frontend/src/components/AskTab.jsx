import React, { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import { AUDIENCE_LABEL } from "../util.jsx";
import TracePanel from "./TracePanel.jsx";

const SUGGESTED = {
  customer: [
    "How long does a refund take?",
    "Can I ship a bike to a PO box?",
    "Is my battery covered if it loses range?",
    "Can I get a discount for buying 5 bikes for my company?",
  ],
  team: [
    "Can I approve a $450 refund myself?",
    "A customer says their battery is smoking. What do I do?",
    "What do I need for a frame warranty claim?",
  ],
};

export default function AskTab({ reviews, onEscalated }) {
  const [audience, setAudience] = useState("customer");
  const [thread, setThread] = useState([]); // [{id, question, audience, status, result?, error?}]
  const [activeId, setActiveId] = useState(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState(null); // passage number to highlight
  const threadRef = useRef(null);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [thread.length, busy]);

  async function ask(question) {
    question = question.trim();
    if (!question || busy) return;
    const id = crypto.randomUUID();
    setThread((t) => [...t, { id, question, audience, status: "thinking" }]);
    setActiveId(id);
    setInput("");
    setBusy(true);
    try {
      const result = await api.ask(question, audience);
      setThread((t) => t.map((x) => (x.id === id ? { ...x, status: result.status, result } : x)));
      if (result.review_id) onEscalated();
    } catch (e) {
      setThread((t) => t.map((x) => (x.id === id ? { ...x, status: "error", error: e.message } : x)));
    } finally {
      setBusy(false);
    }
  }

  function showSource(itemId, n) {
    setActiveId(itemId);
    setFlash(n);
    setTimeout(() => setFlash(null), 1200);
  }

  const active = thread.find((t) => t.id === activeId);

  return (
    <div className="ask-grid">
      <div className="panel chat">
        <div className="chat-head">
          <span>Asking as</span>
          <div className="seg" role="group" aria-label="Asking as">
            {["customer", "team"].map((a) => (
              <button key={a} type="button" aria-pressed={audience === a} onClick={() => setAudience(a)}>
                {AUDIENCE_LABEL[a]}
              </button>
            ))}
          </div>
        </div>

        <div id="thread" ref={threadRef} aria-live="polite">
          {thread.length === 0 && (
            <p className="empty">
              Ask a question or pick one below. Switch to <b>Support team</b> to include internal guides such as
              refund approval limits.
            </p>
          )}
          {thread.map((item) => (
            <Exchange
              key={item.id}
              item={item}
              active={item.id === activeId}
              reply={reviews.find((r) => r.id === item.result?.review_id && r.status === "resolved")}
              onSelect={() => setActiveId(item.id)}
              onCite={(n) => showSource(item.id, n)}
            />
          ))}
        </div>

        <div className="chips">
          {SUGGESTED[audience].map((s) => (
            <button key={s} type="button" className="chip" onClick={() => ask(s)}>
              {s}
            </button>
          ))}
        </div>
        <form
          className="askbar"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask about shipping, returns, warranty, batteries..."
            aria-label="Your question"
          />
          <button className="btn" type="submit" disabled={busy}>
            Ask
          </button>
        </form>
      </div>
      <TracePanel item={active} flash={flash} />
    </div>
  );
}

function Exchange({ item, active, reply, onSelect, onCite }) {
  const r = item.result;
  let body;
  if (item.status === "thinking") body = <p className="pending">Searching approved sources and drafting an answer</p>;
  else if (item.status === "error") body = <p className="meta err">{item.error}</p>;
  else {
    const cited = r.passages.filter((p) => p.cited).length;
    const plural = cited === 1 ? "" : "s";
    body = (
      <>
        <p>
          <AnswerText text={r.answer} passages={r.passages} onCite={onCite} />
        </p>
        {r.status === "escalated" ? (
          <p className="meta esc">Sent to the support team for review</p>
        ) : r.confidence === "medium" ? (
          <p className="meta part">Partly covered by {cited} source{plural}. Check the sources.</p>
        ) : (
          <p className="meta ok">Answered from {cited} source{plural}</p>
        )}
        {reply && (
          <div className="reply">
            <span>Support team replied</span>
            <p>{reply.reply}</p>
          </div>
        )}
      </>
    );
  }
  return (
    <article className={`ex ${active ? "is-active" : ""}`} onClick={onSelect}>
      <div className="q">
        <span className="who">{AUDIENCE_LABEL[item.audience]}</span>
        <p>{item.question}</p>
      </div>
      <div className={`a st-${item.status}`}>{body}</div>
    </article>
  );
}

// Turn "text [P1] more [P2]" into text with clickable source chips.
function AnswerText({ text, passages, onCite }) {
  return text.split(/(\[P\d+\])/).map((part, i) => {
    const m = part.match(/^\[P(\d+)\]$/);
    if (!m) return <React.Fragment key={i}>{part}</React.Fragment>;
    const n = Number(m[1]);
    if (!passages[n - 1]) return null;
    return (
      <button
        key={i}
        className="cite"
        aria-label={`Show source P${n}`}
        onClick={(e) => {
          e.stopPropagation();
          onCite(n);
        }}
      >
        P{n}
      </button>
    );
  });
}
