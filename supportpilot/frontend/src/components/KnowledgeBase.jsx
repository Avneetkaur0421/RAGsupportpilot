import React, { useEffect, useState } from "react";
import { api } from "../api.js";

const TEXT_TYPES = /\.(md|markdown|txt)$/i; // shown in the box so they can be edited first

export default function KnowledgeBase({ formats, onChange }) {
  const [docs, setDocs] = useState([]);
  const [message, setMessage] = useState("");

  const load = () => api.documents().then(setDocs).catch((e) => setMessage(e.message));
  useEffect(() => {
    load();
  }, []);

  // Called after any add, delete or sync: refresh the list and the suggested questions.
  async function changed(text) {
    setMessage(text);
    await load();
    onChange();
  }

  async function remove(doc) {
    if (!confirm(`Remove "${doc.title}" from the knowledge base?`)) return;
    try {
      await api.deleteDocument(doc.doc_id);
      changed(`Removed "${doc.title}".`);
    } catch (e) {
      setMessage(e.message);
    }
  }

  async function sync() {
    setMessage("Scanning the docs folder...");
    try {
      const r = await api.syncFolder();
      const errors = r.errors.map((e) => `${e.file}: ${e.error}`).join(" ");
      changed(
        `Docs folder: ${r.added} added, ${r.updated} updated, ${r.removed} removed, ${r.unchanged} unchanged.` +
          (errors ? ` Couldn't read: ${errors}` : "")
      );
    } catch (e) {
      setMessage(e.message);
    }
  }

  const passages = docs.reduce((n, d) => n + d.sections.length, 0);

  return (
    <div className="cols">
      <div className="panel sec kb">
        <h2>Approved sources</h2>
        <p className="lede">
          {docs.length} documents, {passages} passages. The assistant only answers from these. Internal documents are
          used for team questions, never for customers.
        </p>
        <div className="row" style={{ marginBottom: 8 }}>
          <button type="button" className="btn ghost" onClick={sync}>
            Rescan docs folder
          </button>
        </div>
        {docs.map((d) => (
          <details key={d.doc_id}>
            <summary>
              {d.title} <span className="m">{d.sections.length} passage{d.sections.length === 1 ? "" : "s"}</span>
              <span className="tag">{d.kind}</span>
              {d.audience === "internal" && <span className="tag int">Internal</span>}
            </summary>
            <p className="note" style={{ margin: "6px 0 0" }}>
              {d.origin === "folder" && `From the docs folder: ${d.location}`}
              {d.origin === "upload" && `Uploaded: ${d.location}`}
              {d.origin === "url" && `Web page: ${d.location}`}
              {d.origin === "text" && "Pasted text"}
              {d.origin === "team" && "Reply from the review queue"}
              {d.deletable && (
                <>
                  {" "}
                  <button type="button" className="btn ghost" onClick={() => remove(d)}>
                    Remove
                  </button>
                </>
              )}
            </p>
            <dl>
              {d.sections.map((s) => (
                <React.Fragment key={s.pid}>
                  <dt>{s.heading}</dt>
                  <dd style={{ whiteSpace: "pre-line" }}>{s.text}</dd>
                </React.Fragment>
              ))}
            </dl>
          </details>
        ))}
      </div>

      <div>
        <AddFile formats={formats} onAdded={changed} />
        <AddUrl onAdded={changed} />
        {message && <p className="note">{message}</p>}
      </div>
    </div>
  );
}

function AudienceSelect({ value, onChange }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Who can see it">
      <option value="public">Customer-facing</option>
      <option value="internal">Internal only</option>
    </select>
  );
}

function AddFile({ formats, onAdded }) {
  const [title, setTitle] = useState("");
  const [audience, setAudience] = useState("public");
  const [text, setText] = useState("");
  const [file, setFile] = useState(null); // any non-text file waiting to upload
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function pickFile(e) {
    const picked = e.target.files[0];
    if (!picked) return;
    if (!title) setTitle(picked.name.replace(/\.[^.]+$/, ""));
    if (TEXT_TYPES.test(picked.name)) {
      setFile(null);
      picked.text().then(setText);
    } else {
      setFile(picked); // PDF, Word, Excel, images...: the backend extracts the text
      setText("");
    }
  }

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    const form = e.target;
    try {
      const res = file
        ? await api.uploadDocument(file, title.trim(), audience)
        : await api.addDocument(title.trim(), audience, text);
      onAdded(`Added "${title}" as ${res.passages} passage${res.passages === 1 ? "" : "s"}.`);
      setTitle("");
      setText("");
      setFile(null);
      form.reset();
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel sec">
      <h2>Add a file or text</h2>
      <p className="lede">
        Any of: {formats.join(" ")}. Images and scanned PDFs are read by the AI model. Or paste text below.
      </p>
      <form className="kbform" onSubmit={add}>
        <div className="two">
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" aria-label="Title" required />
          <AudienceSelect value={audience} onChange={setAudience} />
        </div>
        {file ? (
          <p className="note">
            Ready to upload <b>{file.name}</b>.{" "}
            <button type="button" className="btn ghost" onClick={() => setFile(null)}>
              Remove file
            </button>
          </p>
        ) : (
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"## Holiday cut-off\nOrder by December 18 for delivery before December 25..."}
            aria-label="Text"
            required
          />
        )}
        <div className="row">
          <input type="file" accept={formats.join(",")} onChange={pickFile} aria-label="Pick a file" />
          <button className="btn" type="submit" disabled={saving}>
            {saving ? "Reading..." : "Add"}
          </button>
        </div>
        {error && <p className="meta err">{error}</p>}
      </form>
    </div>
  );
}

function AddUrl({ onAdded }) {
  const [url, setUrl] = useState("");
  const [audience, setAudience] = useState("public");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function add(e) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      const res = await api.addUrl(url.trim(), "", audience);
      onAdded(`Added ${url} as ${res.passages} passage${res.passages === 1 ? "" : "s"}.`);
      setUrl("");
    } catch (err) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="panel sec">
      <h2>Add a web page</h2>
      <p className="lede">Paste a public page address, such as an FAQ or help article.</p>
      <form className="kbform" onSubmit={add}>
        <div className="two">
          <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://..." aria-label="Web address" required />
          <AudienceSelect value={audience} onChange={setAudience} />
        </div>
        <div className="row">
          <button className="btn" type="submit" disabled={saving}>
            {saving ? "Reading..." : "Add page"}
          </button>
        </div>
        {error && <p className="meta err">{error}</p>}
      </form>
    </div>
  );
}
