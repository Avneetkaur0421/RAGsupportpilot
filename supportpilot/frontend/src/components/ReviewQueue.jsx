import React, { useState } from "react";
import { api } from "../api.js";
import { AUDIENCE_LABEL, timeAgo } from "../util.jsx";

export default function ReviewQueue({ reviews, onChange }) {
  return (
    <div className="panel sec">
      <h2>Review queue</h2>
      <p className="lede">
        Questions the assistant couldn't answer confidently. Reply to close them, and add the reply to the knowledge
        base so the assistant can answer next time.
      </p>
      {reviews.length === 0 ? (
        <p className="empty">
          Nothing to review. Questions the assistant can't answer will show up here. Try asking about a bulk discount.
        </p>
      ) : (
        reviews.map((r) => <ReviewItem key={r.id} review={r} onChange={onChange} />)
      )}
    </div>
  );
}

function ReviewItem({ review, onChange }) {
  const [reply, setReply] = useState("");
  const [addToKb, setAddToKb] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const resolved = review.status === "resolved";

  async function send() {
    if (!reply.trim()) return;
    setSaving(true);
    setError("");
    try {
      await api.resolve(review.id, reply.trim(), addToKb);
      await onChange();
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="rv">
      <div className="row" style={{ margin: 0 }}>
        <span className={`tag ${resolved ? "done" : ""}`}>{resolved ? "Replied" : "Open"}</span>
        <span className="note">
          {AUDIENCE_LABEL[review.audience]}, {review.topic || "General"}, {timeAgo(review.created_at)}
        </span>
      </div>
      <h3>{review.question}</h3>
      {review.missing && <p className="draft">Missing from the docs: {review.missing}</p>}
      {resolved ? (
        <p style={{ margin: 0 }}>{review.reply}</p>
      ) : (
        <>
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            placeholder="Write the reply the customer will see"
            aria-label="Reply"
          />
          <div className="row">
            <button className="btn" onClick={send} disabled={saving || !reply.trim()}>
              Send reply
            </button>
            <label>
              <input type="checkbox" checked={addToKb} onChange={(e) => setAddToKb(e.target.checked)} /> Add this
              answer to the knowledge base
            </label>
          </div>
          {error && <p className="meta err">{error}</p>}
        </>
      )}
    </div>
  );
}
