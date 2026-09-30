import React, { useEffect, useState } from "react";
import { api } from "../api.js";
import { timeAgo } from "../util.jsx";

export default function Insights() {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState(null);
  const [suggesting, setSuggesting] = useState(false);

  useEffect(() => {
    api.insights().then(setData).catch((e) => setError(e.message));
  }, []);

  async function suggest() {
    setSuggesting(true);
    try {
      setSuggestions((await api.suggest()).gaps);
    } catch (e) {
      setSuggestions([{ title: "Couldn't get suggestions", add: e.message }]);
    } finally {
      setSuggesting(false);
    }
  }

  if (error) return <p className="err-banner">{error}</p>;
  if (!data) return <p className="note">Loading insights...</p>;
  if (data.total === 0)
    return (
      <div className="panel sec">
        <h2>Insights</h2>
        <p className="empty">
          No questions yet. Ask a few on the Ask tab to see top topics, the most-used sources and documentation gaps.
        </p>
      </div>
    );

  return (
    <>
      <div className="stats">
        <div><b>{data.total}</b><span>Questions asked</span></div>
        <div><b>{data.answered_pct}%</b><span>Answered with sources</span></div>
        <div><b>{data.escalated}</b><span>Handed to the team</span></div>
        <div><b>{data.open_reviews}</b><span>Waiting for a reply</span></div>
      </div>
      <div className="cols">
        <div className="panel sec"><h2>Top topics</h2><Bars items={data.top_topics} /></div>
        <div className="panel sec"><h2>Most-used sources</h2><Bars items={data.top_sources} /></div>
      </div>
      <div className="panel sec" style={{ marginTop: 18 }}>
        <h2>Documentation gaps</h2>
        <p className="lede">Questions the docs couldn't answer. These are the pages worth writing next.</p>
        {data.gaps.length === 0 ? (
          <p className="note">No gaps so far. Every question was answered from the docs.</p>
        ) : (
          <>
            <ol className="gaps">
              {data.gaps.map((g, i) => (
                <li key={i}>
                  {g.question} <span>{g.topic}, {timeAgo(g.created_at)}</span>
                </li>
              ))}
            </ol>
            <div className="row">
              <button className="btn ghost" onClick={suggest} disabled={suggesting}>
                {suggesting ? "Suggesting..." : "Suggest documentation updates"}
              </button>
            </div>
            {suggestions && (
              <ul className="gaps" style={{ marginTop: 12 }}>
                {suggestions.map((s, i) => (
                  <li key={i}>
                    <b>{s.title}</b>
                    <br />
                    <span>{s.add}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
    </>
  );
}

function Bars({ items }) {
  if (!items.length) return <p className="note">Nothing yet.</p>;
  const max = items[0][1];
  return (
    <ul className="bars">
      {items.map(([label, n]) => (
        <li key={label}>
          <span>{label}</span>
          <span className="n">{n}</span>
          <span className="bar"><i style={{ width: `${Math.round((n / max) * 100)}%` }} /></span>
        </li>
      ))}
    </ul>
  );
}
