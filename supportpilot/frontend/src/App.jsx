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
  const [appConfig, setAppConfig] = useState(null); // org name, formats, suggested questions

  // Suggested questions are generated from whatever documents are loaded,
  // so we reload them whenever the knowledge base changes.
  const refreshConfig = useCallback(() => {
    api.config().then(setAppConfig).catch(() => setBackendDown(true));
  }, []);
  useEffect(() => {
    refreshConfig();
  }, [refreshConfig]);

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
              Answers questions from {appConfig ? `${appConfig.org_name}'s` : "your"} documents, cites every source, and
              hands off anything it can't answer.
              {appConfig?.org_description ? ` ${appConfig.org_name} is ${appConfig.org_description}.` : ""}
            </p>
            {appConfig?.models && (
              <p className="note" style={{ margin: "-8px 0 14px" }}>
                Model: {appConfig.models.llm_model} ({appConfig.models.llm_provider}). Search:{" "}
                {appConfig.models.embedding_model} ({appConfig.models.embedding_provider}).
              </p>
            )}
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
          <AskTab reviews={reviews} onEscalated={refreshReviews} suggestions={appConfig?.suggestions} />
        </div>
        {tab === "review" && (
          <ReviewQueue
            reviews={reviews}
            onChange={async () => {
              await refreshReviews();
              refreshConfig();
            }}
          />
        )}
        {tab === "insights" && <Insights />}
        {tab === "knowledge" && <KnowledgeBase formats={appConfig?.formats || []} onChange={refreshConfig} />}
      </main>
    </>
  );
}
