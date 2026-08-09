from __future__ import annotations

import pytest
from pydantic import ValidationError

from bookforge.contracts.book import BookContentCatalog, BookMetadata, BookModel, Chapter
from bookforge.contracts.common import ProcessingProvenance, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.raw import RawTextBlock
from bookforge.contracts.semantic import (
    FigureType,
    SemanticFigure,
    SemanticFragment,
    SemanticTable,
    SemanticType,
)
from bookforge.contracts.source import SourceTextReference


def provenance() -> ProcessingProvenance:
    return ProcessingProvenance(
        document_id="doc_1111111111111111",
        source_ids=["p0001_b0001"],
        stage=TransformationStage.SEMANTIC,
        processor="contract-test",
        processor_version="2",
    )


def fragment(fragment_id: str, semantic_type: SemanticType) -> SemanticFragment:
    return SemanticFragment(
        id=fragment_id,
        semantic_type=semantic_type,
        source_references=[SourceTextReference(source_id="p0001_b0001")],
        provenance=provenance(),
    )


def base_fragments() -> dict[str, SemanticFragment]:
    return {
        "sem_f000001": fragment("sem_f000001", SemanticType.TITLE),
        "sem_f000002": fragment("sem_f000002", SemanticType.AUTHOR),
        "sem_f000003": fragment("sem_f000003", SemanticType.CHAPTER_TITLE),
        "sem_f000004": fragment("sem_f000004", SemanticType.PARAGRAPH),
    }


def make_book(
    *,
    fragments: dict[str, SemanticFragment] | None = None,
    figures: dict[str, SemanticFigure] | None = None,
    tables: dict[str, SemanticTable] | None = None,
    content_ids: list[str] | None = None,
) -> BookModel:
    return BookModel(
        revision="book-v2",
        metadata=BookMetadata(
            title_fragment_id="sem_f000001",
            author_fragment_ids=["sem_f000002"],
            language="en",
            identifier="book-id",
        ),
        chapters=[
            Chapter(
                id="chapter-1",
                title_fragment_id="sem_f000003",
                content_fragment_ids=content_ids or ["sem_f000004"],
            )
        ],
        content=BookContentCatalog(
            fragments=fragments or base_fragments(),
            figures=figures or {},
            tables=tables or {},
        ),
    )


def test_v2_serialization_round_trip() -> None:
    book = make_book()
    restored = BookModel.model_validate_json(book.model_dump_json())
    assert restored == book
    assert restored.schema_version == 2
    assert restored.content.schema_version == 2


def test_missing_referenced_fragment_is_rejected() -> None:
    fragments = base_fragments()
    del fragments["sem_f000004"]
    with pytest.raises(ValidationError, match="missing fragments"):
        make_book(fragments=fragments)


def test_duplicate_fragment_ids_are_rejected() -> None:
    fragments = base_fragments()
    fragments["sem_f000099"] = fragments["sem_f000004"]
    with pytest.raises(ValidationError, match="duplicate fragment IDs"):
        make_book(fragments=fragments)


def test_wrong_figure_type_and_orphan_figure_are_rejected() -> None:
    fragments = base_fragments()
    fragments["sem_f000005"] = fragment("sem_f000005", SemanticType.PARAGRAPH)
    figure = SemanticFigure(
        fragment_id="sem_f000005", source_image_id="docx_img000001", figure_type=FigureType.PHOTO
    )
    with pytest.raises(ValidationError, match="FIGURE semantic fragment"):
        make_book(fragments=fragments, figures={"sem_f000005": figure}, content_ids=["sem_f000004", "sem_f000005"])

    fragments["sem_f000005"] = fragment("sem_f000005", SemanticType.FIGURE)
    with pytest.raises(ValidationError, match="orphan figure"):
        make_book(fragments=fragments, figures={"sem_f000005": figure})


def test_wrong_table_type_and_orphan_table_are_rejected() -> None:
    fragments = base_fragments()
    fragments["sem_f000006"] = fragment("sem_f000006", SemanticType.PARAGRAPH)
    table = SemanticTable(fragment_id="sem_f000006", source_ids=["docx_tbl000001"], rows=[])
    with pytest.raises(ValidationError, match="TABLE semantic fragment"):
        make_book(fragments=fragments, tables={"sem_f000006": table}, content_ids=["sem_f000006"])

    fragments["sem_f000006"] = fragment("sem_f000006", SemanticType.TABLE)
    with pytest.raises(ValidationError, match="orphan table"):
        make_book(fragments=fragments, tables={"sem_f000006": table})


def test_caption_reference_integrity() -> None:
    fragments = base_fragments()
    fragments["sem_f000005"] = fragment("sem_f000005", SemanticType.FIGURE)
    fragments["sem_f000006"] = fragment("sem_f000006", SemanticType.CAPTION)
    valid = SemanticFigure(
        fragment_id="sem_f000005",
        source_image_id="docx_img000001",
        caption_fragment_id="sem_f000006",
    )
    book = make_book(
        fragments=fragments,
        figures={"sem_f000005": valid},
        content_ids=["sem_f000005", "sem_f000006"],
    )
    assert book.content.figures["sem_f000005"].caption_fragment_id == "sem_f000006"

    missing = valid.model_copy(update={"caption_fragment_id": "sem_f000007"})
    with pytest.raises(ValidationError, match="missing caption"):
        make_book(
            fragments=fragments,
            figures={"sem_f000005": missing},
            content_ids=["sem_f000005"],
        )


def test_book_has_no_authoritative_text_and_registry_remains_authority() -> None:
    evidence = RawTextBlock(
        id="p0001_b0001",
        document_id="doc_1111111111111111",
        text="Authoritative source text",
        order=1,
    )
    registry = EvidenceRegistry()
    registry.register(evidence)
    book = make_book()
    serialized = book.model_dump_json()
    assert "Authoritative source text" not in serialized
    paragraph = book.content.fragments["sem_f000004"]
    assert registry.resolve_text(paragraph.source_references[0]) == "Authoritative source text"

    reclassified = paragraph.model_copy(update={"semantic_type": SemanticType.QUOTE})
    assert registry.resolve_text(reclassified.source_references[0]) == "Authoritative source text"
    assert evidence.text == "Authoritative source text"
