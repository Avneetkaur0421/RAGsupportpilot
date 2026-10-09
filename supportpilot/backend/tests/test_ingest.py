"""Tests for LangChain-based loading and splitting. Offline, no extra packages.

The helpers below build tiny real .pdf and .docx files so each loader is exercised.
"""
import zipfile

import pytest

from app import config
from app import ingest
from app.ingest import load_file, parse_markdown


def make_pdf(path, pages):
    """Write a minimal valid PDF with one line of text per page."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None,
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET" if text else ""
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
    assert len(chunks) > 1 and all(len(c.text) <= 120 for c in chunks)
    assert all(c.heading == "Refunds" for c in chunks)


def test_pdf_becomes_one_passage_per_page(tmp_path):
    pdf = tmp_path / "warranty-policy.pdf"
    make_pdf(pdf, ["Frames are covered for 5 years.", "Batteries are covered for 2 years."])
    chunks = load_file(pdf)
    assert [c.heading for c in chunks] == ["Page 1", "Page 2"]
    assert chunks[0].doc_title == "Warranty policy" and chunks[0].kind == "PDF"


def test_scanned_pdf_falls_back_to_claude(tmp_path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    make_pdf(pdf, [""])  # a page with no text layer
    seen = {}
    def fake_vision(data, media_type):
        seen["type"] = media_type
        return "## Opening hours\nOpen 9 to 5."
    monkeypatch.setattr(ingest, "vision_extract", fake_vision)
    chunks = load_file(pdf)
    assert seen["type"] == "application/pdf"
    assert chunks[0].heading == "Opening hours" and chunks[0].kind == "PDF (scanned)"


def test_image_is_read_by_claude(tmp_path, monkeypatch):
    img = tmp_path / "price-list.png"
    img.write_bytes(b"\x89PNG fake")
    monkeypatch.setattr(ingest, "vision_extract", lambda data, mt: "## Prices\nService: $50")
    chunks = load_file(img)
    assert chunks[0].text == "Service: $50" and chunks[0].kind == "Image"


def test_image_without_vision_gives_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VISION_EXTRACT", False)
    img = tmp_path / "x.png"
    img.write_bytes(b"x")
    with pytest.raises(ValueError, match="VISION_EXTRACT"):
        load_file(img)


def test_docx_is_loaded(tmp_path):
    docx = tmp_path / "returns.docx"
    make_docx(docx, ["Returns are accepted within 30 days.", "Refunds take 5 to 7 business days."])
    chunks = load_file(docx)
    assert chunks and "30 days" in chunks[0].text and chunks[0].kind == "Word"


def test_pptx_one_passage_per_slide_with_notes(tmp_path):
    from pptx import Presentation
    prs = Presentation()
    for title, body, note in [("Pricing", "Basic plan is $10.", "Mention the discount."),
                              ("Support", "Email us any time.", "")]:
        slide = prs.slides.add_slide(prs.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = body
        if note:
            slide.notes_slide.notes_text_frame.text = note
    path = tmp_path / "deck.pptx"
    prs.save(path)
    chunks = load_file(path)
    assert [c.heading for c in chunks] == ["Slide 1: Pricing", "Slide 2: Support"]
    assert "Notes: Mention the discount." in chunks[0].text


def test_excel_rows_keep_column_names(tmp_path):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Plans"
    ws.append(["Plan", "Price", "Users"])
    ws.append(["Basic", 10, 1])
    ws.append(["Team", 49, 10])
    path = tmp_path / "plans.xlsx"
    wb.save(path)
    chunks = load_file(path)
    assert chunks[0].heading == "Plans, rows 2 to 3"
    assert "Plan: Team; Price: 49; Users: 10" in chunks[0].text


def test_large_csv_is_split_into_row_ranges(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CHUNK_SIZE", 200)
    path = tmp_path / "orders.csv"
    path.write_text("order,status\n" + "\n".join(f"A{i},shipped" for i in range(1, 41)))
    chunks = load_file(path)
    assert len(chunks) > 1 and chunks[0].heading.startswith("Sheet, rows 2 to")
    assert "order: A1; status: shipped" in chunks[0].text


def test_html_strips_tags_and_uses_page_title(tmp_path):
    path = tmp_path / "page.html"
    path.write_text("<html><head><title>Store hours</title><script>var x=1</script></head>"
                    "<body><h1>Hours</h1><p>Open 9 to 5, Monday to Saturday.</p></body></html>")
    chunks = load_file(path)
    assert chunks[0].doc_title == "Store hours" and "Open 9 to 5" in chunks[0].text
    assert "<p>" not in chunks[0].text


def test_json_is_flattened(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text('{"plans": [{"name": "Basic", "price": 10}]}')
    text = load_file(path)[0].text
    assert "plans[0].name: Basic" in text and "plans[0].price: 10" in text


def test_internal_folder_sets_audience(tmp_path):
    (tmp_path / "internal").mkdir()
    (tmp_path / "internal" / "limits.txt").write_text("Agents can approve refunds up to $300.")
    (tmp_path / "faq.txt").write_text("We ship to the US and Canada.")
    assert load_file(tmp_path / "internal" / "limits.txt")[0].audience == "internal"
    assert load_file(tmp_path / "faq.txt")[0].audience == "public"


def test_unsupported_file_type_is_rejected(tmp_path):
    f = tmp_path / "tool.exe"
    f.write_bytes(b"x")
    with pytest.raises(ValueError):
        load_file(f)
