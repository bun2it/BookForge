from __future__ import annotations

import json

import pytest
from pydantic import TypeAdapter, ValidationError

from bookforge.contracts.common import ProcessingProvenance, TransformationStage
from bookforge.contracts.evidence import (
    DuplicateEvidenceIdError,
    EvidenceRegistry,
    InvalidSourceTextRangeError,
    UnknownEvidenceIdError,
)
from bookforge.contracts.ids import (
    SourceObjectKind,
    StableIdError,
    boundary_operation_id,
    document_id_from_bytes,
    docx_object_id,
    pdf_object_id,
    pdf_page_id,
    run_id,
    semantic_fragment_id,
    table_cell_id,
    table_row_id,
    validate_stable_id,
)
from bookforge.contracts.raw import RawObject, RawParagraph, RawRun, RawTableCell, RawTextBlock
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference, TextJoinBehavior


DOCUMENT_ID = "doc_1111111111111111"


def semantic_provenance() -> ProcessingProvenance:
    return ProcessingProvenance(
        document_id=DOCUMENT_ID,
        source_ids=["p0001_b0001"],
        stage=TransformationStage.SEMANTIC,
        processor="test",
        processor_version="1",
    )


def test_stable_ids_are_deterministic_unique_and_round_trip() -> None:
    assert document_id_from_bytes(b"same source") == document_id_from_bytes(b"same source")
    ids = {
        pdf_page_id(1),
        pdf_object_id(1, SourceObjectKind.TEXT_BLOCK, 1),
        pdf_object_id(1, SourceObjectKind.IMAGE, 1),
        docx_object_id(SourceObjectKind.PARAGRAPH, 1),
        docx_object_id(SourceObjectKind.TABLE, 1),
        semantic_fragment_id(1),
        boundary_operation_id(1),
    }
    assert len(ids) == 7
    assert json.loads(json.dumps(sorted(ids))) == sorted(ids)
    assert all(validate_stable_id(value) == value for value in ids)


def test_pdf_docx_and_nested_ids() -> None:
    assert pdf_page_id(7) == "p0007"
    assert pdf_object_id(7, SourceObjectKind.TEXT_BLOCK, 3) == "p0007_b0003"
    paragraph = docx_object_id(SourceObjectKind.PARAGRAPH, 123)
    assert paragraph == "docx_p000123"
    assert run_id(paragraph, 4) == "docx_p000123_r0004"
    table = docx_object_id(SourceObjectKind.TABLE, 8)
    row = table_row_id(table, 2)
    assert row == "docx_tbl000008_row0002"
    assert table_cell_id(row, 3) == "docx_tbl000008_row0002_c0003"


@pytest.mark.parametrize("invalid", ["", "page-1", "docx_p1", "p0000_b0001", "sem_heading000001"])
def test_invalid_ids_are_rejected(invalid: str) -> None:
    with pytest.raises(StableIdError):
        validate_stable_id(invalid)
    with pytest.raises(StableIdError):
        pdf_page_id(0)


def test_raw_discriminator_is_explicit_and_unknown_kind_is_rejected() -> None:
    adapter = TypeAdapter(RawObject)
    block = RawTextBlock(
        id="p0001_b0001", document_id=DOCUMENT_ID, text="evidence", order=1
    )
    restored = adapter.validate_json(adapter.dump_json(block))
    assert type(restored) is RawTextBlock
    assert restored.kind == "text_block"
    with pytest.raises(ValidationError):
        adapter.validate_python(
            {"kind": "mystery", "id": "p0001_b0001", "document_id": DOCUMENT_ID}
        )


def test_nested_run_and_cell_discriminators() -> None:
    adapter = TypeAdapter(RawObject)
    run = RawRun(
        id="docx_p000001_r0001", document_id=DOCUMENT_ID, text="run", order=1
    )
    cell = RawTableCell(
        id="docx_tbl000001_row0001_c0001",
        document_id=DOCUMENT_ID,
        row_index=0,
        column_index=0,
        text="cell",
    )
    assert type(adapter.validate_json(adapter.dump_json(run))) is RawRun
    assert type(adapter.validate_json(adapter.dump_json(cell))) is RawTableCell


def test_registry_resolves_whole_text_and_half_open_ranges() -> None:
    registry = EvidenceRegistry()
    block = RawTextBlock(
        id="p0007_b0003", document_id=DOCUMENT_ID, text="0123456789", order=3
    )
    registry.register(block)
    assert registry.contains(block.id)
    assert registry.get(block.id) is block
    assert registry.resolve_text(SourceTextReference(source_id=block.id)) == "0123456789"
    assert registry.resolve_text(
        SourceTextReference(source_id=block.id, start_offset=2, end_offset=6)
    ) == "2345"
    assert registry.resolve_text(
        SourceTextReference(source_id=block.id, start_offset=4, end_offset=4)
    ) == ""
    with pytest.raises(InvalidSourceTextRangeError):
        registry.resolve_text(SourceTextReference(source_id=block.id, start_offset=0, end_offset=11))


def test_registry_rejects_duplicates_and_unknown_ids() -> None:
    registry = EvidenceRegistry()
    block = RawTextBlock(
        id="p0001_b0001", document_id=DOCUMENT_ID, text="first", order=1
    )
    registry.register(block)
    with pytest.raises(DuplicateEvidenceIdError):
        registry.register(
            RawParagraph(
                id="p0001_b0001", document_id=DOCUMENT_ID, text="replacement", order=1
            )
        )
    with pytest.raises(UnknownEvidenceIdError):
        registry.get("p0001_b9999")


def test_source_text_safety_survives_semantic_reclassification() -> None:
    registry = EvidenceRegistry()
    first = RawTextBlock(
        id="p0001_b0001",
        document_id=DOCUMENT_ID,
        text="The company developed a ",
        order=1,
    )
    second = RawTextBlock(
        id="p0001_b0002",
        document_id=DOCUMENT_ID,
        text="comprehensive strategy.",
        order=2,
    )
    registry.register(first)
    registry.register(second)
    references = [
        SourceTextReference(source_id=first.id, join_behavior=TextJoinBehavior.DIRECT),
        SourceTextReference(source_id=second.id, join_behavior=TextJoinBehavior.DIRECT),
    ]
    semantic = SemanticFragment(
        id="sem_f000001",
        semantic_type=SemanticType.PARAGRAPH,
        source_references=references,
        provenance=semantic_provenance(),
    )
    expected = "The company developed a comprehensive strategy."
    for classification in (SemanticType.PARAGRAPH, SemanticType.QUOTE, SemanticType.HEADING):
        classified = semantic.model_copy(update={"semantic_type": classification})
        assert "".join(registry.resolve_many(classified.source_references)) == expected
    assert first.text == "The company developed a "
    assert second.text == "comprehensive strategy."
    with pytest.raises(ValidationError):
        first.text = "mutated"


def test_source_reference_is_frozen_and_contains_no_text_copy() -> None:
    reference = SourceTextReference(source_id="p0001_b0001")
    assert "text" not in reference.model_dump()
    with pytest.raises(ValidationError):
        reference.start_offset = 1
