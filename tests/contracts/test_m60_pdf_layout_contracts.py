from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bookforge.contracts import (
    AlignmentMethod,
    AlignmentReasonCode,
    AlignmentStatus,
    CorroborationObservation,
    CorroborationProvenance,
    CorroborationSourcePair,
    BookModelV3,
    DocumentId,
    DocxTextAlignmentTarget,
    DocxBoundaryAlignmentTarget,
    LayoutAlignment,
    LayoutAlignmentCandidate,
    LayoutCorroborationEvidence,
    PdfBoundingBox,
    PdfLayoutScanInput,
    PdfLayoutScanResult,
    PdfLayoutScanner,
    PdfLayoutSource,
    PdfLineRegion,
    PdfMarkerId,
    PdfPageEvidence,
    PdfPhysicalPageBoundary,
    PdfScannerIdentity,
    PdfScannerProvenance,
    PdfVisualObservation,
    PdfVisualParagraphGroup,
    SourceId,
    SourceTextReference,
    pdf_document_id,
    pdf_layout_page_id,
    pdf_pair_fingerprint,
)

HEX = "a" * 64
POLICY = "b" * 64
INPUT = "c" * 64
SCANNER = "d" * 64
PAIR = pdf_pair_fingerprint("docx-book", f"pdf_{HEX[:16]}")
PAGE_1 = f"pdfp_{HEX[:12]}_p0001"
PAGE_2 = f"pdfp_{HEX[:12]}_p0002"
LINE_1 = f"pdfl_{HEX[:12]}_p0001_l0001"
LINE_2 = f"pdfl_{HEX[:12]}_p0002_l0001"
BOUNDARY = f"pdfb_{HEX[:12]}_p0001_p0002"
MARKER = PdfMarkerId("pdfm_" + "1" * 20)


def page(number: int) -> PdfPageEvidence:
    return PdfPageEvidence(
        page_id=PAGE_1 if number == 1 else PAGE_2,
        pdf_document_id=f"pdf_{HEX[:16]}",
        page_number=number,
        width=600,
        height=800,
        rendered_page_reference=f"rendered/page-{number}.png",
    )


def provenance() -> PdfScannerProvenance:
    return PdfScannerProvenance(
        scanner=PdfScannerIdentity(name="fixture-scanner", version="1"),
        input_fingerprint=INPUT,
        scanner_fingerprint=SCANNER,
        marker_schema_version="m6.0-v1",
        scanner_policy_version="fixture-v1",
    )


def test_pdf_identity_depends_on_bytes_not_path() -> None:
    first = PdfLayoutSource(
        document_id=pdf_document_id(HEX), content_sha256=HEX, original_name="a/book.pdf", page_count=2
    )
    second = first.model_copy(update={"original_name": "renamed.pdf"})
    assert first.document_id == second.document_id
    with pytest.raises(ValidationError, match="identity must derive"):
        PdfLayoutSource(
            document_id="pdf_0000000000000000",
            content_sha256=HEX,
            original_name="book.pdf",
            page_count=2,
        )


def test_page_identity_depends_on_pdf_bytes_and_page_number_not_workspace() -> None:
    pdf_id = pdf_document_id(HEX)
    assert pdf_layout_page_id(pdf_id, 10) == pdf_layout_page_id(pdf_id, 10)
    assert pdf_layout_page_id(pdf_id, 10) != pdf_layout_page_id(pdf_id, 11)


def test_visual_line_is_immutable_and_round_trips() -> None:
    line = PdfLineRegion(
        region_id=LINE_1,
        page_id=PAGE_1,
        visual_order=1,
        bbox=PdfBoundingBox(x0=10, y0=20, x1=500, y1=40),
        alignment_text_hint="non-authoritative only",
    )
    assert PdfLineRegion.model_validate_json(line.model_dump_json()) == line
    with pytest.raises(ValidationError):
        line.visual_order = 2  # type: ignore[misc]


def test_physical_boundary_is_adjacent_but_has_no_logical_break() -> None:
    boundary = PdfPhysicalPageBoundary(
        boundary_id=BOUNDARY,
        left_page_id=PAGE_1,
        right_page_id=PAGE_2,
        left_page_number=1,
        right_page_number=2,
    )
    assert "logical_break" not in boundary.model_dump()
    with pytest.raises(ValidationError, match="adjacent"):
        PdfPhysicalPageBoundary(
            boundary_id=BOUNDARY,
            left_page_id=PAGE_1,
            right_page_id=PAGE_2,
            left_page_number=1,
            right_page_number=3,
        )


def test_visual_paragraph_can_cross_a_physical_page_boundary() -> None:
    marker = PdfVisualParagraphGroup(
        marker_id=MARKER,
        line_region_ids=(LINE_1, LINE_2),
        continues_across_physical_boundary_ids=(BOUNDARY,),
        confidence=0.8,
    )
    assert marker.continues_across_physical_boundary_ids == (BOUNDARY,)


def test_visual_observation_rejects_final_flow_and_placement_fields() -> None:
    with pytest.raises(ValidationError):
        PdfVisualObservation.model_validate(
            {
                "marker_id": MARKER,
                "observation": "caption_region_candidate",
                "page_ids": [PAGE_1],
                "figure_placement": "before",
            }
        )


def test_explicit_source_pair_preserves_docx_authority() -> None:
    pair = CorroborationSourcePair(
        docx_document_id=DocumentId("docx-book"),
        pdf_document_id=f"pdf_{HEX[:16]}",
        pair_fingerprint=PAIR,
    )
    assert pair.authoritative_source == "docx"
    assert pair.corroborating_source == "pdf_layout"


def test_alignment_supports_subranges_and_many_pdf_lines_to_one_docx_target() -> None:
    target = DocxTextAlignmentTarget(
        source_references=(
            SourceTextReference(source_id=SourceId("p-1"), start_offset=3, end_offset=8),
            SourceTextReference(source_id=SourceId("p-1"), start_offset=8, end_offset=14),
            SourceTextReference(source_id=SourceId("p-1"), start_offset=14, end_offset=21),
        )
    )
    alignment = LayoutAlignment(
        alignment_id="pda_" + "2" * 20,
        source_pair_fingerprint=PAIR,
        pdf_marker_ids=(MARKER, PdfMarkerId("pdfm_" + "3" * 20)),
        target=target,
        method=AlignmentMethod.NGRAM,
        status=AlignmentStatus.PARTIAL_MATCH,
        reason_codes=(AlignmentReasonCode.MANY_PDF_LINES_TO_ONE_DOCX_PARAGRAPH,),
        input_fingerprint=INPUT,
        alignment_policy_fingerprint=POLICY,
    )
    assert alignment.target == target


def test_physical_boundary_alignment_records_where_without_deciding_a_break() -> None:
    target = DocxBoundaryAlignmentTarget(
        left_references=(SourceTextReference(source_id=SourceId("p-100")),),
        right_references=(SourceTextReference(source_id=SourceId("p-101")),),
    )
    alignment = LayoutAlignment(
        alignment_id="pda_" + "8" * 20,
        source_pair_fingerprint=PAIR,
        pdf_marker_ids=(MARKER,),
        target=target,
        method=AlignmentMethod.CONTEXT,
        status=AlignmentStatus.MATCH,
        input_fingerprint=INPUT,
        alignment_policy_fingerprint=POLICY,
    )
    assert isinstance(alignment.target, DocxBoundaryAlignmentTarget)
    assert "break_intent" not in alignment.model_dump()


def test_alignment_supports_one_visual_paragraph_to_many_docx_paragraphs() -> None:
    target = DocxTextAlignmentTarget(
        source_references=(
            SourceTextReference(source_id=SourceId("p-1")),
            SourceTextReference(source_id=SourceId("p-2")),
        )
    )
    alignment = LayoutAlignment(
        alignment_id="pda_" + "4" * 20,
        source_pair_fingerprint=PAIR,
        pdf_marker_ids=(MARKER,),
        target=target,
        method=AlignmentMethod.CONTEXT,
        status=AlignmentStatus.MATCH,
        input_fingerprint=INPUT,
        alignment_policy_fingerprint=POLICY,
    )
    assert isinstance(alignment.target, DocxTextAlignmentTarget)
    assert len(alignment.target.source_references) == 2


def test_ambiguous_alignment_requires_multiple_candidates_and_no_selection() -> None:
    def candidate(source: str) -> LayoutAlignmentCandidate:
        return LayoutAlignmentCandidate(
            target=DocxTextAlignmentTarget(
                source_references=(SourceTextReference(source_id=SourceId(source)),)
            )
        )

    alignment = LayoutAlignment(
        alignment_id="pda_" + "5" * 20,
        source_pair_fingerprint=PAIR,
        pdf_marker_ids=(MARKER,),
        candidates=(candidate("p-1"), candidate("p-2")),
        method=AlignmentMethod.FUZZY,
        status=AlignmentStatus.AMBIGUOUS,
        input_fingerprint=INPUT,
        alignment_policy_fingerprint=POLICY,
    )
    assert alignment.target is None


@pytest.mark.parametrize("status", [AlignmentStatus.TEXT_MISMATCH, AlignmentStatus.UNALIGNED])
def test_non_matches_remain_explicit_without_authoritative_target(status: AlignmentStatus) -> None:
    alignment = LayoutAlignment(
        alignment_id="pda_" + "6" * 20,
        source_pair_fingerprint=PAIR,
        pdf_marker_ids=(MARKER,),
        method=AlignmentMethod.UNRESOLVED,
        status=status,
        input_fingerprint=INPUT,
        alignment_policy_fingerprint=POLICY,
    )
    assert alignment.target is None


def test_corroboration_is_observation_not_final_semantic_or_flow_decision() -> None:
    evidence = LayoutCorroborationEvidence(
        evidence_id="pdc_" + "7" * 20,
        observation=CorroborationObservation.PARAGRAPH_CONTINUATION_CANDIDATE,
        pdf_marker_ids=(MARKER,),
        docx_source_references=(SourceTextReference(source_id=SourceId("p-1")),),
        docx_source_ids=(SourceId("p-1"),),
        provenance=CorroborationProvenance(
            source_pair_fingerprint=PAIR,
            scanner_fingerprint=SCANNER,
            alignment_policy_fingerprint=POLICY,
            corroboration_policy_fingerprint=HEX,
        ),
    )
    dumped = evidence.model_dump()
    assert "boundary_operation" not in dumped
    assert "figure_placement" not in dumped
    assert "semantic_type" not in dumped


class FixtureScanner:
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        return PdfLayoutScanResult(
            pdf_document_id=scan_input.pdf_document_id,
            page_ids=tuple(item.page_id for item in scan_input.pages),
            markers=(),
            provenance=provenance(),
        )


def accepts_scanner(scanner: PdfLayoutScanner) -> PdfLayoutScanner:
    return scanner


def test_vendor_neutral_scanner_protocol_accepts_fixture_outputs() -> None:
    scan_input = PdfLayoutScanInput(
        pdf_document_id=f"pdf_{HEX[:16]}",
        pages=(page(1),),
        rendered_page_references=("rendered/page-1.png",),
        non_authoritative_alignment_hints=("localization hint",),
        configuration_fingerprint=POLICY,
    )
    result = accepts_scanner(FixtureScanner()).scan(scan_input)
    assert result.page_ids == (PAGE_1,)


def test_pdf_text_hint_cannot_stand_in_for_authoritative_source_reference() -> None:
    with pytest.raises(ValidationError):
        SourceTextReference.model_validate({"alignment_text_hint": "PDF-only words"})


def test_book_model_v3_remains_pdf_free() -> None:
    fields = BookModelV3.model_fields
    assert not any("pdf" in name for name in fields)
    serialized_schema = BookModelV3.model_json_schema()
    assert "pdf_marker_id" not in str(serialized_schema).lower()
    assert "pdf_coordinates" not in str(serialized_schema).lower()


def test_epub_v3_renderer_does_not_import_m6_contracts() -> None:
    source = (Path(__file__).parents[2] / "bookforge/epub/v3_builder.py").read_text()
    assert "contracts.pdf_layout" not in source
    assert "contracts.layout_alignment" not in source
    assert "contracts.corroboration" not in source


def test_scanner_input_is_bounded_to_a_page_pair() -> None:
    data: dict[str, Any] = {
        "pdf_document_id": f"pdf_{HEX[:16]}",
        "pages": [page(1), page(2), page(2)],
        "rendered_page_references": ["1.png", "2.png", "3.png"],
        "configuration_fingerprint": POLICY,
    }
    with pytest.raises(ValidationError):
        PdfLayoutScanInput.model_validate(data)
