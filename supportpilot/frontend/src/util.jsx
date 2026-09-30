import React from "react";

const STOP = new Set(
  "a an the and or of to in on for is are was be it i my me we you your our can do does how what when where which who why will with at by from this that as if not no yes have has had there their they them its about into than then so any just get much long many take need want".split(" ")
);

// Words from the question worth highlighting inside a passage.
export function queryTerms(question) {
  return (question.toLowerCase().match(/[a-z0-9]+/g) || [])
    .filter((w) => w.length > 2 && !STOP.has(w))
    .map((w) => w.replace(/(ing|ed|es|s)$/, ""));
}

// Wrap words that start with a query term in <mark>, without using innerHTML.
export function Highlight({ text, terms }) {
  const parts = text.split(/([A-Za-z0-9]+)/);
  return parts.map((p, i) =>
    i % 2 && terms.some((t) => t.length > 2 && p.toLowerCase().startsWith(t)) ? (
      <mark key={i}>{p}</mark>
    ) : (
      <React.Fragment key={i}>{p}</React.Fragment>
    )
  );
}

export function timeAgo(seconds) {
  const s = Math.max(1, Math.round(Date.now() / 1000 - seconds));
  if (s < 60) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  return h < 24 ? `${h} h ago` : `${Math.round(h / 24)} d ago`;
}

export const AUDIENCE_LABEL = { customer: "Customer", team: "Support team" };
