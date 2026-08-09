from __future__ import annotations

import base64
import json
from pathlib import Path

from docx import Document
from docx.shared import Inches

from bookforge.docx import DocxExtractor
from bookforge.docx.report import build_report, load_report, render_human


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_report_counts_flow_contexts_and_does_not_mutate_raw_output(tmp_path: Path) -> None:
    image_path = tmp_path / "pixel.png"
    image_path.write_bytes(PNG_1X1)
    document = Document()
    document.add_paragraph("Before")
    image_paragraph = document.add_paragraph()
    image_paragraph.add_run().add_picture(str(image_path), width=Inches(1))
    document.add_paragraph("After")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Product"
    table.cell(0, 1).text = "Capacity"
    table.cell(1, 0).text = "A"
    table.cell(1, 1).text = "100"
    document.sections[0].header.paragraphs[0].text = "Header"
    document.sections[0].footer.paragraphs[0].text = "Footer"
    source_path = tmp_path / "report.docx"
    document.save(source_path)
    result = DocxExtractor().extract(source_path, tmp_path / "work")
    raw_path = result.workspace / "raw_document.json"
    raw_before = raw_path.read_bytes()

    report = load_report(raw_path)
    human = render_human(report)

    assert report["summary"]["body_paragraphs"] == 3
    assert report["summary"]["header_paragraphs"] == 1
    assert report["summary"]["footer_paragraphs"] == 1
    assert report["summary"]["images"] == 1
    assert report["summary"]["tables"] == 1
    assert report["summary"]["rows"] == 2
    assert report["summary"]["cells"] == 4
    assert report["summary"]["image_only_paragraphs"] == 1
    assert [item["type"] for item in report["body_flow"]] == [
        "PARAGRAPH",
        "PARAGRAPH",
        "IMAGE",
        "PARAGRAPH",
        "TABLE",
    ]
    assert report["image_contexts"][0]["before"]["text_preview"] == "Before"
    assert report["image_contexts"][0]["after"]["text_preview"] == "After"
    assert report["table_contexts"][0]["rows"] == 2
    assert report["table_contexts"][0]["columns"] == 2
    assert "BOOKFORGE DOCX EXTRACTION REPORT" in human
    assert "IMAGE CONTEXTS" in human
    assert "TABLE CONTEXTS" in human
    assert json.loads(json.dumps(report, ensure_ascii=False))["summary"] == report["summary"]
    assert raw_path.read_bytes() == raw_before


def test_build_report_without_warnings_is_supported(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("One")
    source_path = tmp_path / "minimal.docx"
    document.save(source_path)
    result = DocxExtractor().extract(source_path, tmp_path / "work")

    report = build_report(result.raw_document)

    assert report["summary"]["warnings"] == 0
    assert report["fragmentation"]["counts"]["extremely_short_non_empty_paragraphs"] == 1
