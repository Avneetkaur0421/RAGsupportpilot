"""Tests for LangChain-based loading and splitting. Offline, no extra packages.

The helpers below build tiny real .pdf and .docx files so each loader is exercised.
"""
import zipfile

import pytest

from app import config
from app.ingest import load_file, load_folder, parse_markdown


def make_pdf(path, pages):
    """Write a minimal valid PDF with one line of text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET"
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
        content_id = len(objs)
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Contents {content_id} 0 R /Resources << /Font << /F1 3 0 R >> >> >>")
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(out)


def make_docx(path, paragraphs):
    """Write a minimal .docx (a zip with one XML file inside)."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
                   '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f"<w:body>{body}</w:body></w:document>")


def test_markdown_splits_by_heading_and_keeps_title():
    chunks = parse_markdown("demo", "# Demo guide\n\n## One\nHello.\n\n## Two\nWorld.")
    assert [c.heading for c in chunks] == ["One", "Two"]
    assert {c.doc_title for c in chunks} == {"Demo guide"}


def test_long_section_is_cut_into_overlapping_pieces(monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE", 120)
    monkeypatch.setattr(config, "CHUNK_OVERLAP", 20)
    long_text = " ".join(f"Sentence number {i} about refunds." for i in range(20))
    chunks = parse_markdown("long", f"# Long\n\n## Refunds\n{long_text}")
    assert len(chunks) > 1
    assert all(len(c.text) <= 120 for c in chunks)
    assert all(c.heading == "Refunds" for c in chunks)  # heading kept on every piece


def test_pdf_becomes_one_passage_per_page(tmp_path):
    pdf = tmp_path / "warranty-policy.pdf"
    make_pdf(pdf, ["Frames are covered for 5 years.", "Batteries are covered for 2 years."])
    chunks = load_file(pdf)
    assert [c.heading for c in chunks] == ["Page 1", "Page 2"]
    assert "5 years" in chunks[0].text
    assert chunks[0].doc_title == "Warranty policy"


def test_docx_is_loaded(tmp_path):
    docx = tmp_path / "returns.docx"
    make_docx(docx, ["Returns are accepted within 30 days.", "Refunds take 5 to 7 business days."])
    chunks = load_file(docx)
    assert chunks and "30 days" in chunks[0].text


def test_internal_folder_sets_audience(tmp_path):
    (tmp_path / "internal").mkdir()
    (tmp_path / "internal" / "limits.txt").write_text("Agents can approve refunds up to $300.")
    (tmp_path / "faq.txt").write_text("We ship to the US and Canada.")
    by_doc = {c.doc_id: c.audience for c in load_folder(tmp_path)}
    assert by_doc == {"limits": "internal", "faq": "public"}


def test_unsupported_file_type_is_rejected(tmp_path):
    f = tmp_path / "data.xlsx"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        load_file(f)
