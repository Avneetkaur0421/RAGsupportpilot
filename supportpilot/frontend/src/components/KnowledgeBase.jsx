import React, { useEffect, useState } from "react";
import { api } from "../api.js";

export default function KnowledgeBase() {
  const [docs, setDocs] = useState([]);
  const [title, setTitle] = useState("");
  const [audience, setAudience] = useState("public");
  const [text, setText] = useState("");
  const [message, setMessage] = useState("");
  const [file, setFile] = useState(null); // a PDF or Word file waiting to upload
  const [saving, setSaving] = useState(false);

  const load = () => api.documents().then(setDocs).catch((e) => setMessage(e.message));
  useEffect(() => {
    load();
  }, []);

  function pickFile(e) {
    const picked = e.target.files[0];
    if (!picked) return;
    if (!title) setTitle(picked.name.replace(/\.[^.]+$/, ""));
    if (/\.(pdf|docx)$/i.test(picked.name)) {
      setFile(picked); // binary: the backend extracts the text with LangChain
      setText("");
    } else {
      setFile(null);
      picked.text().then(setText); // text files: show them so they can be edited
    }
  }

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    try {
      const res = file
        ? await api.uploadDocument(file, title.trim(), audience)
        : await api.addDocument(title.trim(), audience, text);
      setMessage(`Added "${title}" as ${res.passages} passage${res.passages === 1 ? "" : "s"}. Ask about it on the Ask tab.`);
      setTitle("");
      setText("");
      setFile(null);
      e.target.reset();
      load();
    } catch (err) {
      setMessage(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="cols">
      <div className="panel sec kb">
        <h2>Approved sources</h2>
        <p className="lede">
          The assistant only answers from these. Internal guides are used for support team questions, never for
          customers.
        </p>
        {docs.map((d) => (
          <details key={d.doc_id}>
            <summary>
              {d.title} <span className="m">{d.sections.length} passage{d.sections.length === 1 ? "" : "s"}</span>
              {d.audience === "internal" && <span className="tag int">Internal</span>}
              {d.doc_id.startsWith("added-") && <span className="tag">Added</span>}
            </summary>
            <dl>
              {d.sections.map((s) => (
                <React.Fragment key={s.pid}>
                  <dt>{s.heading}</dt>
                  <dd>{s.text}</dd>
                </React.Fragment>
              ))}
            </dl>
          </details>
        ))}
      </div>
      <div className="panel sec">
        <h2>Add a document</h2>
        <p className="lede">
          Upload a PDF, Word, Markdown or text file, or paste text. Headings, pages and long sections are split into
          passages automatically.
        </p>
        <form className="kbform" onSubmit={add}>
          <div className="two">
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Document title" aria-label="Document title" required />
            <select value={audience} onChange={(e) => setAudience(e.target.value)} aria-label="Audience">
              <option value="public">Customer-facing</option>
              <option value="internal">Internal only</option>
            </select>
          </div>
          {file ? (
            <p className="note">
              Ready to upload <b>{file.name}</b>. Its text will be extracted on the server.{" "}
              <button type="button" className="btn ghost" onClick={() => setFile(null)}>
                Remove file
              </button>
            </p>
          ) : (
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder={"## Holiday cut-off\nOrder by December 18 for delivery before December 25..."}
              aria-label="Document text"
              required
            />
          )}
          <div className="row">
            <input type="file" accept=".pdf,.docx,.txt,.md" onChange={pickFile} aria-label="Pick a text file" />
            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Adding..." : "Add document"}
            </button>
          </div>
          {message && <p className="note">{message}</p>}
        </form>
      </div>
    </div>
  );
}
