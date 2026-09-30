import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api.js";
import AskTab from "./components/AskTab.jsx";
import ReviewQueue from "./components/ReviewQueue.jsx";
import Insights from "./components/Insights.jsx";
import KnowledgeBase from "./components/KnowledgeBase.jsx";

const TABS = [
  ["ask", "Ask"],
  ["review", "Review queue"],
  ["insights", "Insights"],
  ["knowledge", "Knowledge base"],
];

export default function App() {
  const [tab, setTab] = useState("ask");
  const [reviews, setReviews] = useState([]);
  const [backendDown, setBackendDown] = useState(false);

  // Reviews are shared by the Ask tab (to show team replies) and the Review tab.
  const refreshReviews = useCallback(async () => {
    try {
      setReviews(await api.reviews());
      setBackendDown(false);
    } catch {
      setBackendDown(true);
    }
  }, []);

  useEffect(() => {
    refreshReviews();
  }, [tab, refreshReviews]);

  const openCount = reviews.filter((r) => r.status === "open").length;

  return (
    <>
      <header className="top">
        <div className="wrap">
          <div className="brand">
            <h1>SupportPilot</h1>
            <p>
              Answers customer and team questions from approved docs, cites every source, and hands off anything it
              can't answer. Demo data: Kestrel Cycles, a fictional e-bike brand.
            </p>
          </div>
          <nav className="tabs" role="tablist" aria-label="Sections">
            {TABS.map(([id, label]) => (
              <button key={id} className="tab" role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                {label}
                {id === "review" && openCount > 0 && <span className="count">{openCount}</span>}
              </button>
            ))}
          </nav>
        </div>
      </header>
      <main className="wrap">
        {backendDown && (
          <p className="err-banner">
            Can't reach the backend. Start it from the backend folder with: uvicorn app.main:app --reload
          </p>
        )}
        {/* AskTab stays mounted so the conversation survives tab switches. */}
        <div hidden={tab !== "ask"}>
          <AskTab reviews={reviews} onEscalated={refreshReviews} />
        </div>
        {tab === "review" && <ReviewQueue reviews={reviews} onChange={refreshReviews} />}
        {tab === "insights" && <Insights />}
        {tab === "knowledge" && <KnowledgeBase />}
      </main>
    </>
  );
}
