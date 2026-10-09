"""Agent, knowledge sync and API tests. Run from the backend folder:  pytest -q"""
import pytest
from fastapi.testclient import TestClient

from app import config, knowledge, main, vectorstore
from app.graph import build_graph
from tests.conftest import FakeLLM
from tests.test_ingest import make_pdf


@pytest.fixture
def client(monkeypatch, demo_kb):
    monkeypatch.setattr(main, "agent", build_graph(FakeLLM("high")))
    def no_llm():
        raise RuntimeError("no API key in tests")
    monkeypatch.setattr(main, "_llm", no_llm)
    return TestClient(main.app)  # not a context manager, so startup is skipped


# ---------- agent ----------

def test_customers_never_see_internal_guides(demo_kb):
    hits = vectorstore.search("refund approval limits for agents", "customer", 10)
    assert hits and all(h["audience"] == "public" for h in hits)


def test_confident_answer_is_returned(demo_kb):
    out = build_graph(FakeLLM("high")).invoke({"question": "How long does a refund take?", "audience": "customer"})
    assert out["status"] == "answered" and "[P1]" in out["answer"]


def test_low_confidence_goes_to_review(demo_kb):
    out = build_graph(FakeLLM("low")).invoke({"question": "Can I get a bulk discount?", "audience": "customer"})
    assert out["status"] == "escalated"


def test_follow_up_is_rewritten_before_search(demo_kb):
    llm = FakeLLM("high")
    first = build_graph(llm).invoke({"question": "How long does a refund take?", "audience": "customer"})
    assert llm.plain_calls == 0 and first["search_query"] == "How long does a refund take?"

    follow = build_graph(llm).invoke({"question": "and for accessories?", "audience": "customer",
                                      "history": [{"question": "How long does a refund take?",
                                                   "answer": "5 to 7 business days."}]})
    assert llm.plain_calls == 1 and follow["search_query"] == "How long do refunds take?"


# ---------- knowledge sync ----------

def test_folder_sync_adds_updates_and_removes(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    (docs / "internal").mkdir(parents=True)
    monkeypatch.setattr(config, "DOCS_DIR", docs)
    faq = docs / "faq.md"
    faq.write_text("# FAQ\n\n## Shipping\nWe ship to the US.")
    (docs / "internal" / "limits.txt").write_text("Agents approve refunds up to $300.")

    assert knowledge.sync_folder()["added"] == 2
    assert knowledge.sync_folder()["unchanged"] == 2           # nothing re-read

    faq.write_text("# FAQ\n\n## Shipping\nWe ship to the US and Canada.")
    import os, time
    os.utime(faq, (time.time() + 5, time.time() + 5))         # make sure mtime changes
    assert knowledge.sync_folder()["updated"] == 1

    (docs / "internal" / "limits.txt").unlink()
    assert knowledge.sync_folder()["removed"] == 1
    assert vectorstore.doc_ids() == {"f-faq"}


def test_bad_file_in_folder_is_reported_not_fatal(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    monkeypatch.setattr(config, "DOCS_DIR", docs)
    monkeypatch.setattr(config, "VISION_EXTRACT", False)
    (docs / "ok.txt").write_text("Fine.")
    (docs / "photo.png").write_bytes(b"\x89PNG fake")
    result = knowledge.sync_folder()
    assert result["added"] == 1 and result["errors"][0]["file"] == "photo.png"


def test_only_public_urls_are_allowed():
    for bad in ["ftp://example.com", "http://localhost:8000", "http://127.0.0.1/admin", "not a url"]:
        with pytest.raises(ValueError):
            knowledge.check_public_url(bad)


# ---------- API ----------

def test_api_escalation_review_and_team_answer(client, monkeypatch):
    monkeypatch.setattr(main, "agent", build_graph(FakeLLM("low")))
    r = client.post("/api/ask", json={"question": "Can I get a bulk discount?", "audience": "customer"}).json()
    assert r["status"] == "escalated" and r["review_id"]

    ok = client.post(f"/api/reviews/{r['review_id']}/resolve",
                     json={"reply": "Email sales for orders of 5+ bikes.", "add_to_kb": True})
    assert ok.status_code == 200
    assert "Team answers" in [d["title"] for d in client.get("/api/documents").json()]
    assert client.get("/api/insights").json()["escalated"] == 1


def test_api_ask_accepts_history(client):
    r = client.post("/api/ask", json={"question": "and accessories?", "audience": "customer",
                                      "history": [{"question": "Refund time?", "answer": "5 to 7 days."}]})
    assert r.status_code == 200 and r.json()["search_query"] == "How long do refunds take?"


def test_api_upload_then_delete(client, tmp_path):
    pdf = tmp_path / "holiday.pdf"
    make_pdf(pdf, ["Order by December 18 for delivery before December 25."])
    with pdf.open("rb") as f:
        r = client.post("/api/documents/upload", files={"file": ("holiday.pdf", f, "application/pdf")},
                        data={"title": "Holiday shipping", "audience": "public"})
    assert r.status_code == 200 and r.json()["passages"] == 1

    doc = next(d for d in client.get("/api/documents").json() if d["title"] == "Holiday shipping")
    assert doc["kind"] == "PDF" and doc["deletable"]
    assert client.delete(f"/api/documents/{doc['doc_id']}").status_code == 200
    assert "Holiday shipping" not in [d["title"] for d in client.get("/api/documents").json()]


def test_api_rejects_unsupported_and_folder_deletes(client):
    bad = client.post("/api/documents/upload", files={"file": ("tool.exe", b"x", "application/octet-stream")})
    assert bad.status_code == 400
    folder_doc = next(d for d in client.get("/api/documents").json() if d["origin"] == "folder")
    assert client.delete(f"/api/documents/{folder_doc['doc_id']}").status_code == 400


def test_api_url_document(client, monkeypatch):
    from app.ingest import Chunk
    monkeypatch.setattr(knowledge, "check_public_url", lambda url: None)
    monkeypatch.setattr(knowledge, "load_url", lambda url, audience, title, doc_id: [
        Chunk(f"{doc_id}#1", doc_id, "Store hours", "Part 1", "Open 9 to 5.", audience, "Web page")])
    r = client.post("/api/documents/url", json={"url": "https://example.com/hours", "audience": "public"})
    assert r.status_code == 200
    assert "Store hours" in [d["title"] for d in client.get("/api/documents").json()]


def test_api_config_falls_back_without_llm(client):
    cfg = client.get("/api/config").json()
    assert cfg["org_name"] == config.ORG_NAME
    assert cfg["suggestions"]["customer"] and ".pdf" in cfg["formats"]
