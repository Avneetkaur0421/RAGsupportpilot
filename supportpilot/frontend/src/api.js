// Every call to the Python backend lives here, so components stay simple.
async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
  return data;
}

export const api = {
  ask: (question, audience) =>
    request("/ask", { method: "POST", body: JSON.stringify({ question, audience }) }),
  reviews: () => request("/reviews"),
  resolve: (id, reply, addToKb) =>
    request(`/reviews/${id}/resolve`, {
      method: "POST",
      body: JSON.stringify({ reply, add_to_kb: addToKb }),
    }),
  documents: () => request("/documents"),
  addDocument: (title, audience, text) =>
    request("/documents", { method: "POST", body: JSON.stringify({ title, audience, text }) }),
  // Files are sent as multipart form data, so no JSON Content-Type header here.
  uploadDocument: async (file, title, audience) => {
    const form = new FormData();
    form.append("file", file);
    form.append("title", title);
    form.append("audience", audience);
    const res = await fetch("/api/documents/upload", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || `Upload failed (${res.status})`);
    return data;
  },
  insights: () => request("/insights"),
  suggest: () => request("/insights/suggest", { method: "POST" }),
};
