import React, { useEffect, useRef } from "react";
import { Highlight, queryTerms } from "../util.jsx";

// Shows the LangGraph path for the selected question: Retrieve -> Grade -> Answer or Hand off.
export default function TracePanel({ item, flash }) {
  const refs = useRef({});

  useEffect(() => {
    if (flash) refs.current[flash]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [flash]);

  if (!item) {
    return (
      <aside className="panel trace">
        <h2>How this answer was found</h2>
        <p className="empty" style={{ padding: "4px 0" }}>
          Ask a question to see which passages the assistant read, how it graded them, and why it answered or
          handed off.
        </p>
      </aside>
    );
  }

  const r = item.result;
  const done = item.status === "answered" || item.status === "escalated";
  const escalated = item.status === "escalated";
  const scope = item.audience === "team" ? "including internal guides" : "customer-facing docs only";
  const k = r?.passages.length ?? 0;

  let grade = "Claude is reading the passages and rating how well they answer the question.";
  if (item.status === "error") grade = "Grading didn't finish.";
  else if (r?.skipped_llm) grade = "No passage was relevant enough, so the question skipped the model and went straight to the team.";
  else if (done)
    grade = {
      high: "Claude rated the passages as fully answering the question.",
      medium: "Claude rated the passages as partly answering the question.",
      low: `Claude found the passages don't answer it.${r.missing ? " Missing: " + r.missing : ""}`,
    }[r.confidence];

  const terms = queryTerms(item.question);

  return (
    <aside className="panel trace" aria-label="How this answer was found">
      <h2>How this answer was found</h2>
      <ol className="steps">
        <li className={done ? "on" : ""}>
          <b>Retrieve</b>
          <span>{done ? `Searched the knowledge base (${scope}) and kept ${k} relevant passage${k === 1 ? "" : "s"}.` : "Searching."}</span>
        </li>
        <li className={done ? (r.confidence === "low" ? "bad" : "on") : ""}>
          <b>Grade</b>
          <span>{grade}</span>
        </li>
        <li className={done ? (escalated ? "bad" : "on") : ""}>
          <b>{escalated ? "Hand off" : "Answer"}</b>
          <span>
            {escalated
              ? "Added to the review queue with the question and what's missing."
              : done
              ? "Replied with a source marker on every fact."
              : "Waiting."}
          </span>
        </li>
      </ol>
      {r?.passages.map((p) => (
        <div key={p.pid} ref={(el) => (refs.current[p.n] = el)} className={`pas ${flash === p.n ? "flash" : ""}`}>
          <div className="pas-h">
            <span className="pn">P{p.n}</span>
            <span className="t">
              {p.doc_title}: {p.heading}
            </span>
            {p.audience === "internal" && <span className="aud">Internal</span>}
            {p.cited && <span className="used">Cited</span>}
          </div>
          <div className="rel" title={`Relevance ${p.relevance}`}>
            <i style={{ width: `${Math.max(6, Math.round(p.relevance * 100))}%` }} />
          </div>
          <p className="src">
            <Highlight text={p.text} terms={terms} />
          </p>
        </div>
      ))}
      {done && k === 0 && <p className="note">No passages matched.</p>}
    </aside>
  );
}
