from __future__ import annotations

import base64
import hashlib
import zipfile
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_BREAK
from docx.opc.constants import RELATIONSHIP_TYPE
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches

from bookforge.contracts.raw import RawImage, RawParagraph, RawTable
from bookforge.contracts.source import SourceTextReference
from bookforge.docx import DocxExtractor, InvalidDocxError, MissingDocumentPartError


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def save_document(document: Document, path: Path) -> Path:
    document.save(path)
    return path


@pytest.fixture
def image_path(tmp_path: Path) -> Path:
    path = tmp_path / "pixel.png"
    path.write_bytes(PNG_1X1)
    return path


def body_objects(result: object) -> list[RawParagraph | RawTable | RawImage]:
    raw_document = result.raw_document  # type: ignore[attr-defined]
    return [
        item
        for item in raw_document.objects
        if isinstance(item, (RawParagraph, RawTable, RawImage))
        and item.source_metadata.get("story", "body") == "body"
    ]


def test_basic_unicode_formatting_and_special_text(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("Đây là tiếng Việt — English “quoted” text.")
    paragraph = document.add_paragraph()
    paragraph.add_run("normal")
    bold = paragraph.add_run(" bold")
    bold.bold = True
    italic = paragraph.add_run(" italic")
    italic.italic = True
    underline = paragraph.add_run(" underline")
    underline.underline = True
    superscript = paragraph.add_run("2")
    superscript.font.superscript = True
    subscript = paragraph.add_run("3")
    subscript.font.subscript = True
    special = paragraph.add_run("\u00a0tab")
    special.add_tab()
    special.add_text("line")
    special.add_break(WD_BREAK.LINE)
    special.add_text("after")
    source = save_document(document, tmp_path / "formatting.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    paragraphs = [item for item in result.raw_document.objects if isinstance(item, RawParagraph)]

    assert paragraphs[0].text == "Đây là tiếng Việt — English “quoted” text."
    assert [run.bold for run in paragraphs[1].runs][1] is True
    assert [run.italic for run in paragraphs[1].runs][2] is True
    assert [run.underline for run in paragraphs[1].runs][3] is True
    assert paragraphs[1].runs[4].superscript is True
    assert paragraphs[1].runs[5].subscript is True
    assert "\u00a0tab\tline\nafter" in paragraphs[1].text


def test_interleaved_order_is_deterministic_and_image_is_anchored(
    tmp_path: Path, image_path: Path
) -> None:
    document = Document()
    document.add_paragraph("Paragraph A")
    document.add_paragraph("Paragraph B")
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Cell A"
    table.cell(0, 1).text = "Cell B"
    document.add_paragraph("Paragraph C")
    image_paragraph = document.add_paragraph()
    image_paragraph.add_run().add_picture(str(image_path), width=Inches(1))
    document.add_paragraph("Paragraph D")
    source = save_document(document, tmp_path / "ordered.docx")

    first = DocxExtractor().extract(source, tmp_path / "work-a")
    second = DocxExtractor().extract(source, tmp_path / "work-b")
    first_objects = body_objects(first)
    second_objects = body_objects(second)

    assert [type(item).__name__ for item in first_objects] == [
        "RawParagraph",
        "RawParagraph",
        "RawTable",
        "RawParagraph",
        "RawParagraph",
        "RawImage",
        "RawParagraph",
    ]
    assert first.document_id == second.document_id
    assert first.raw_document.model_dump_json() == second.raw_document.model_dump_json()
    assert [item.id for item in first_objects] == [item.id for item in second_objects]
    image = next(item for item in first_objects if isinstance(item, RawImage))
    containing = first_objects[3 + 1]
    assert isinstance(containing, RawParagraph)
    assert image.source_metadata["containing_paragraph_id"] == containing.id
    assert image.id in containing.source_metadata["anchored_object_ids"]


def test_authoritative_source_text_resolves_without_semantics(tmp_path: Path) -> None:
    expected = "The company developed a comprehensive strategy."
    document = Document()
    document.add_paragraph(expected)
    source = save_document(document, tmp_path / "source-text.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    paragraph = next(item for item in result.raw_document.objects if isinstance(item, RawParagraph))

    assert result.evidence_registry.resolve_text(SourceTextReference(source_id=paragraph.id)) == expected
    assert result.evidence_registry.resolve_text(
        SourceTextReference(source_id=paragraph.id, start_offset=4, end_offset=11)
    ) == "company"


def test_image_bytes_mime_stable_id_and_anchor(tmp_path: Path, image_path: Path) -> None:
    document = Document()
    document.add_paragraph("Before image")
    image_paragraph = document.add_paragraph()
    image_paragraph.add_run().add_picture(str(image_path), width=Inches(1))
    document.add_paragraph("After image")
    source = save_document(document, tmp_path / "image.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    image = next(item for item in result.raw_document.objects if isinstance(item, RawImage))
    extracted_path = result.workspace / image.asset_reference

    assert image.id == "docx_img000001"
    assert extracted_path.read_bytes() == PNG_1X1
    assert image.source_metadata["content_type"] == "image/png"
    assert image.source_metadata["placement"] == "inline"
    assert result.assets[0].sha256 == hashlib.sha256(PNG_1X1).hexdigest()
    assert result.assets[0].size_bytes == len(PNG_1X1)


def test_table_structure_ids_text_registry_and_no_invented_cells(tmp_path: Path) -> None:
    document = Document()
    table = document.add_table(rows=3, cols=2)
    values = [("Product", "Capacity"), ("A", "100"), ("B", "200")]
    for row, values_row in zip(table.rows, values, strict=True):
        for cell, value in zip(row.cells, values_row, strict=True):
            cell.text = value
    table.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
    source = save_document(document, tmp_path / "table.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    raw_table = next(item for item in result.raw_document.objects if isinstance(item, RawTable))

    assert raw_table.id == "docx_tbl000001"
    assert raw_table.source_metadata["header_row_indices"] == [0]
    assert [row.id for row in raw_table.rows] == [
        "docx_tbl000001_row0001",
        "docx_tbl000001_row0002",
        "docx_tbl000001_row0003",
    ]
    assert [[cell.text for cell in row.cells] for row in raw_table.rows] == [list(row) for row in values]
    assert all(len(row.cells) == 2 for row in raw_table.rows)
    last_cell = raw_table.rows[2].cells[1]
    assert last_cell.id == "docx_tbl000001_row0003_c0002"
    assert result.evidence_registry.resolve_text(SourceTextReference(source_id=last_cell.id)) == "200"


def test_header_and_footer_are_preserved_as_separate_story_evidence(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("Body text")
    section = document.sections[0]
    section.header.paragraphs[0].text = "Running header"
    section.footer.paragraphs[0].text = "Running footer"
    source = save_document(document, tmp_path / "stories.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    paragraphs = [item for item in result.raw_document.objects if isinstance(item, RawParagraph)]
    stories = {(item.source_metadata["story"], item.text) for item in paragraphs}

    assert ("body", "Body text") in stories
    assert ("header", "Running header") in stories
    assert ("footer", "Running footer") in stories


def test_hyperlink_and_field_evidence_are_preserved_without_resolution(tmp_path: Path) -> None:
    document = Document()
    paragraph = document.add_paragraph("Visit ")
    rel_id = document.part.relate_to(
        "https://example.com", RELATIONSHIP_TYPE.HYPERLINK, is_external=True
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), rel_id)
    hyperlink_run = OxmlElement("w:r")
    hyperlink_text = OxmlElement("w:t")
    hyperlink_text.text = "Example"
    hyperlink_run.append(hyperlink_text)
    hyperlink.append(hyperlink_run)
    paragraph._p.append(hyperlink)

    field_paragraph = document.add_paragraph()
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    field_run = OxmlElement("w:r")
    field_text = OxmlElement("w:t")
    field_text.text = "7"
    field_run.append(field_text)
    field.append(field_run)
    field_paragraph._p.append(field)
    source = save_document(document, tmp_path / "links-fields.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")
    paragraphs = [item for item in result.raw_document.objects if isinstance(item, RawParagraph)]

    hyperlink_metadata = paragraphs[0].runs[-1].source_metadata["hyperlink"]
    assert hyperlink_metadata["target"] == "https://example.com"
    assert hyperlink_metadata["target_mode"] == "External"
    assert paragraphs[0].text == "Visit Example"
    assert paragraphs[1].source_metadata["fields"][0]["simple_instruction"] == "PAGE"
    assert paragraphs[1].source_metadata["fields"][0]["resolved"] is False
    assert any(warning.code == "FIELD_PRESERVED_NOT_RESOLVED" for warning in result.warnings)


def test_debug_workspace_is_written(tmp_path: Path) -> None:
    document = Document()
    document.add_paragraph("Debug me")
    source = save_document(document, tmp_path / "debug.docx")

    result = DocxExtractor().extract(source, tmp_path / "work")

    assert (result.workspace / "source.json").is_file()
    assert (result.workspace / "raw_document.json").is_file()
    assert (result.workspace / "warnings.json").is_file()
    assert '"source_type":"docx"' in result.raw_document.model_dump_json()


def test_invalid_zip_and_missing_document_part_are_typed_errors(tmp_path: Path) -> None:
    corrupt = tmp_path / "corrupt.docx"
    corrupt.write_bytes(b"not a zip")
    with pytest.raises(InvalidDocxError, match="valid DOCX ZIP"):
        DocxExtractor().extract(corrupt, tmp_path / "work-corrupt")

    incomplete = tmp_path / "incomplete.docx"
    with zipfile.ZipFile(incomplete, "w") as package:
        package.writestr("[Content_Types].xml", "<Types/>")
    with pytest.raises(MissingDocumentPartError, match="word/document.xml"):
        DocxExtractor().extract(incomplete, tmp_path / "work-incomplete")
