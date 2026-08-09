from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from bookforge.contracts.artifact import ImmutableEpubArtifact, MetadataSnapshot
from bookforge.contracts.book import BookContentCatalog, BookMetadata, BookModel, Chapter
from bookforge.contracts.common import BoundingBox, ProcessingProvenance, TransformationStage
from bookforge.contracts.delivery import DeliveryAttempt, DeliveryStatus
from bookforge.contracts.events import (
    EngineEvent,
    EngineEventType,
    ProcessingJob,
    ProcessingProgress,
    ProcessingStage,
)
from bookforge.contracts.flow import ContentFlow, FlowEntry
from bookforge.contracts.raw import RawDocument, RawPage, RawTextBlock
from bookforge.contracts.semantic import (
    AnalysisStatus,
    BookState,
    BoundaryDecision,
    BoundaryOperation,
    BoundaryOperationType,
    PageFragment,
    SemanticFragment,
    SemanticType,
)
from bookforge.contracts.source import SourceTextReference


def provenance(stage: TransformationStage = TransformationStage.EXTRACTION) -> ProcessingProvenance:
    return ProcessingProvenance(
        document_id="doc-1",
        source_ids=["source-1"],
        stage=stage,
        processor="contract-test",
        processor_version="1",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def fragment(fragment_id: str = "sem_f000001") -> SemanticFragment:
    return SemanticFragment(
        id=fragment_id,
        semantic_type=SemanticType.PARAGRAPH,
        source_references=[SourceTextReference(source_id="p0001_b0001")],
        provenance=provenance(TransformationStage.SEMANTIC),
    )


class ContractTests(unittest.TestCase):
    def assert_round_trip(self, value: object) -> None:
        cls = type(value)
        payload = value.model_dump_json()  # type: ignore[attr-defined]
        self.assertEqual(value, cls.model_validate_json(payload))
        self.assertEqual(payload, cls.model_validate_json(payload).model_dump_json())

    def test_invalid_bounding_boxes(self) -> None:
        with self.assertRaises(ValidationError):
            BoundingBox(x0=10, y0=0, x1=2, y1=4)

    def test_source_text_range_validation(self) -> None:
        with self.assertRaises(ValidationError):
            SourceTextReference(source_id="s1", start_offset=4)
        with self.assertRaises(ValidationError):
            SourceTextReference(source_id="s1", start_offset=4, end_offset=2)

    def test_semantic_fragment_requires_sources_and_forbids_generated_text(self) -> None:
        with self.assertRaises(ValidationError):
            SemanticFragment(
                id="sem_f000001",
                semantic_type=SemanticType.PARAGRAPH,
                source_references=[],
                provenance=provenance(TransformationStage.SEMANTIC),
            )
        with self.assertRaises(ValidationError):
            SemanticFragment.model_validate(
                {
                    "id": "sem_f000001",
                    "semantic_type": "paragraph",
                    "source_references": [{"source_id": "s1"}],
                    "provenance": provenance(TransformationStage.SEMANTIC).model_dump(),
                    "text": "AI reconstructed text",
                }
            )

    def test_page_fragment_preserves_order(self) -> None:
        page = PageFragment(
            source_page_id="p0001",
            ordered_fragments=[fragment("sem_f000002"), fragment("sem_f000001")],
            analysis_status=AnalysisStatus.COMPLETE,
        )
        self.assertEqual(["sem_f000002", "sem_f000001"], [item.id for item in page.ordered_fragments])
        self.assert_round_trip(page)

    def test_raw_models_round_trip(self) -> None:
        block = RawTextBlock(
            id="p0001_b0001",
            document_id="doc_1111111111111111",
            page_id="p0001",
            page_number=1,
            text="Original source text",
            bbox=BoundingBox(x0=0, y0=0, x1=100, y1=20),
            order=0,
        )
        page = RawPage(
            id="p0001", document_id="doc_1111111111111111", page_number=1, objects=[block], provenance=provenance()
        )
        document = RawDocument(
            id="doc_1111111111111111", source_type="pdf", original_name="book.pdf", pages=[page], provenance=provenance()
        )
        self.assert_round_trip(page)
        self.assert_round_trip(document)

    def test_book_state_round_trip_without_book_text(self) -> None:
        state = BookState(revision="state-7", previous_page_last_fragment_id="frag-9")
        self.assertNotIn("text", state.model_dump())
        self.assert_round_trip(state)

    def test_boundary_operation_requires_references(self) -> None:
        with self.assertRaises(ValidationError):
            BoundaryOperation(
                id="bnd000001",
                operation_type=BoundaryOperationType.MERGE_PARAGRAPH,
                decision=BoundaryDecision.RESOLVED,
            )
        operation = BoundaryOperation(
            id="bnd000001",
            operation_type=BoundaryOperationType.MERGE_PARAGRAPH,
            decision=BoundaryDecision.RESOLVED,
            source_fragment_ids=["f1", "f2"],
        )
        self.assert_round_trip(operation)

    def test_content_flow_round_trip(self) -> None:
        flow = ContentFlow(
            revision="flow-1",
            entries=[FlowEntry(fragment_id="f1"), FlowEntry(fragment_id="f2")],
            provenance=provenance(TransformationStage.FLOW),
        )
        self.assert_round_trip(flow)

    def test_book_model_has_no_source_type(self) -> None:
        book = BookModel(
            revision="book-1",
            metadata=BookMetadata(
                title_fragment_id="sem_f000010", author_fragment_ids=["sem_f000011"], language="en", identifier="id-1"
            ),
            chapters=[Chapter(id="chapter-1", content_fragment_ids=["sem_f000001"])],
            content=BookContentCatalog(
                fragments={
                    "sem_f000001": fragment("sem_f000001"),
                    "sem_f000010": fragment("sem_f000010").model_copy(
                        update={"semantic_type": SemanticType.TITLE}
                    ),
                    "sem_f000011": fragment("sem_f000011").model_copy(
                        update={"semantic_type": SemanticType.AUTHOR}
                    ),
                }
            ),
        )
        serialized = book.model_dump_json()
        self.assertNotIn("source_type", serialized)
        self.assert_round_trip(book)

    def test_epub_artifact_is_immutable_and_round_trips(self) -> None:
        artifact = ImmutableEpubArtifact(
            id="artifact-1",
            relative_path="artifacts/book.epub",
            size_bytes=123,
            sha256="a" * 64,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            book_model_revision="book-1",
            metadata_snapshot=MetadataSnapshot(title="A Book", language="en", identifier="id-1"),
        )
        with self.assertRaises(ValidationError):
            artifact.size_bytes = 124
        self.assert_round_trip(artifact)

    def test_delivery_unknown_is_explicit_and_round_trips(self) -> None:
        attempt = DeliveryAttempt(
            id="attempt-1",
            delivery_record_id="delivery-1",
            artifact_id="artifact-1",
            provider_id="future-official-provider",
            profile_id="profile-1",
            status=DeliveryStatus.UNKNOWN,
        )
        self.assertEqual(DeliveryStatus.UNKNOWN, attempt.status)
        self.assert_round_trip(attempt)

    def test_job_and_event_serialization(self) -> None:
        progress = ProcessingProgress(current_stage=ProcessingStage.SEMANTIC_ANALYSIS, current_page=188, total_pages=300)
        job = ProcessingJob(id="job-1", document_id="doc-1", progress=progress)
        event = EngineEvent(event_type=EngineEventType.PROGRESS_UPDATED, job_id="job-1", progress=progress)
        self.assert_round_trip(job)
        self.assert_round_trip(event)

    def test_schema_version_defaults_and_enum_validation(self) -> None:
        self.assertEqual(1, BookState(revision="r1").schema_version)
        with self.assertRaises(ValidationError):
            SemanticFragment(
                id="sem_f000001",
                semantic_type="invented-type",
                source_references=[SourceTextReference(source_id="s1")],
                provenance=provenance(TransformationStage.SEMANTIC),
            )

    def test_unknown_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            BookState.model_validate({"revision": "r1", "entire_book_text": "forbidden"})


if __name__ == "__main__":
    unittest.main()
