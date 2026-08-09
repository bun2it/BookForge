from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from bookforge.contracts.classification import ClassificationResult
from bookforge.contracts.common import (
    DocumentId,
    ProcessingProvenance,
    SourceType,
    TransformationStage,
)
from bookforge.contracts.raw import RawDocument, RawDrawing, RawImage, RawParagraph, RawRun, RawStyle
from bookforge.contracts.semantic import SemanticType
from bookforge.semantic.models import SemanticPipelineConfig, SemanticSourceKind, Story
from bookforge.semantic.pipeline import (
    EPOCH,
    BaselineUnknownClassifier,
    SemanticPipeline,
    SemanticPipelineInterrupted,
    build_analysis_view,
    build_evidence_registry,
    deterministic_batches,
    generate_work_units,
)

DOC_ID = DocumentId("doc_aaaaaaaaaaaaaaaa")


def provenance() -> ProcessingProvenance:
    return ProcessingProvenance(
        document_id=DOC_ID,
        stage=TransformationStage.EXTRACTION,
        processor="test",
        processor_version="1",
        created_at=EPOCH,
    )


def paragraph(index: int, text: str, *, story: str = "body", **metadata: object) -> RawParagraph:
    return RawParagraph(
        id=f"docx_p{index:06d}",
        document_id=DOC_ID,
        text=text,
        order=index,
        runs=(
            RawRun(
                id=f"docx_p{index:06d}_r0001",
                document_id=DOC_ID,
                text=text,
                order=1,
                bold=True if index % 2 == 0 else None,
            ),
        ),
        style=RawStyle(name="Heading1" if index == 2 else "Normal", alignment="center"),
        source_metadata={"story": story, "hyperlinks": [], **metadata},
    )


def document(objects: tuple[object, ...], *, name: str = "test.docx") -> RawDocument:
    return RawDocument(
        id=DOC_ID,
        source_type=SourceType.DOCX,
        original_name=name,
        objects=objects,
        provenance=provenance(),
    )


def test_critical_m3_m4_boundary_preserves_order_and_returns_unknown(tmp_path: Path) -> None:
    raw = document(
        (
            paragraph(1, "End of previous chapter."),
            paragraph(2, "CHAPTER TWO"),
            paragraph(3, "A NEW JOURNEY"),
            paragraph(4, "The morning was cold."),
        )
    )
    registry = build_evidence_registry(raw)
    units = generate_work_units(raw)
    assert [unit.target_source_ids[0] for unit in units] == [obj.id for obj in raw.objects]
    middle = build_analysis_view(units[1], raw, registry)
    assert [item.text for item in middle.context_before] == ["End of previous chapter."]
    assert [item.text for item in middle.context_after] == [
        "A NEW JOURNEY",
        "The morning was cold.",
    ]

    report = SemanticPipeline().run(raw, registry, BaselineUnknownClassifier(), tmp_path)
    assert report.completed == 4
    results = sorted((tmp_path / "semantic/results").glob("*.json"))
    assert all(ClassificationResult.model_validate_json(path.read_text()).semantic_type is SemanticType.UNKNOWN for path in results)
    forbidden = (
        "page_break",
        "new_page",
        "chapter_boundary",
        "join_previous",
        "join_next",
        "final_image_position",
        "chapter_grouping",
    )
    serialized = "".join(path.read_text() for path in (tmp_path / "semantic").rglob("*.json"))
    assert not any(field in serialized for field in forbidden)


def test_image_context_preserves_anchor_as_evidence_not_placement(tmp_path: Path) -> None:
    first = paragraph(1, "Paragraph A", anchored_object_ids=["docx_img000001"])
    image = RawImage(
        id="docx_img000001",
        document_id=DOC_ID,
        order=1,
        asset_reference="assets/docx_img000001.png",
        width=100,
        height=80,
        source_metadata={
            "story": "body",
            "content_type": "image/png",
            "containing_paragraph_id": first.id,
            "placement": "floating",
            "run_order": 1,
            "drawing_order_in_run": 1,
        },
    )
    raw = document((first, image, paragraph(2, "Paragraph B")))
    registry = build_evidence_registry(raw)
    units = generate_work_units(raw)
    assert [unit.source_kind for unit in units] == [
        SemanticSourceKind.PARAGRAPH,
        SemanticSourceKind.IMAGE,
        SemanticSourceKind.PARAGRAPH,
    ]
    view = build_analysis_view(units[1], raw, registry)
    assert view.target_text is None
    assert [item.text for item in view.context_before] == ["Paragraph A"]
    assert [item.text for item in view.context_after] == ["Paragraph B"]
    assert units[1].structural_features.docx_placement is not None
    assert units[1].structural_features.docx_placement.placement == "floating"
    SemanticPipeline().run(raw, registry, BaselineUnknownClassifier(), tmp_path)
    result_text = "".join(path.read_text() for path in (tmp_path / "semantic").rglob("*.json"))
    assert "final_image_position" not in result_text
    assert "caption_fragment_id" not in result_text


def test_story_context_never_crosses_body_header_footer() -> None:
    raw = document(
        (
            paragraph(1, "Body one"),
            paragraph(2, "Header one", story="header"),
            paragraph(3, "Footer one", story="footer"),
            paragraph(4, "Body two"),
            paragraph(5, "Header two", story="header"),
            paragraph(6, "Footer two", story="footer"),
        )
    )
    units = generate_work_units(raw)
    assert units[3].story is Story.BODY
    assert units[3].context_before_source_ids == (raw.objects[0].id,)
    assert units[4].context_before_source_ids == (raw.objects[1].id,)
    assert units[5].context_before_source_ids == (raw.objects[2].id,)


def test_runs_are_features_not_independent_targets() -> None:
    raw = document((paragraph(1, "One"), paragraph(2, "TWO")))
    units = generate_work_units(raw)
    assert len(units) == 2
    assert units[1].structural_features.run_count == 1
    assert units[1].structural_features.bold_run_count == 1
    assert units[1].structural_features.uppercase_ratio == 1


def test_source_evidence_is_structurally_unchanged(tmp_path: Path) -> None:
    raw = document((paragraph(1, "Immutable source"), paragraph(2, "Still immutable")))
    before = hashlib.sha256(raw.model_dump_json().encode()).hexdigest()
    SemanticPipeline().run(
        raw, build_evidence_registry(raw), BaselineUnknownClassifier(), tmp_path
    )
    after = hashlib.sha256(raw.model_dump_json().encode()).hexdigest()
    assert after == before


def test_deterministic_units_batches_results_fragments_and_workspace(tmp_path: Path) -> None:
    raw = document(tuple(paragraph(index, f"Paragraph {index}") for index in range(1, 8)))
    config = SemanticPipelineConfig(context_before=2, context_after=2, batch_size=3)
    units_a = generate_work_units(raw, config)
    units_b = generate_work_units(raw, config)
    assert units_a == units_b
    assert deterministic_batches(units_a, 3) == deterministic_batches(units_b, 3)
    assert [len(batch.work_unit_ids) for batch in deterministic_batches(units_a, 3)] == [3, 3, 1]

    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    pipeline = SemanticPipeline(config)
    pipeline.run(raw, build_evidence_registry(raw), BaselineUnknownClassifier(), first_workspace)
    pipeline.run(raw, build_evidence_registry(raw), BaselineUnknownClassifier(), second_workspace)
    first_files = {
        path.relative_to(first_workspace): path.read_bytes()
        for path in (first_workspace / "semantic").rglob("*.json")
    }
    second_files = {
        path.relative_to(second_workspace): path.read_bytes()
        for path in (second_workspace / "semantic").rglob("*.json")
    }
    assert first_files == second_files


def test_checkpoint_interruption_resume_and_reuse(tmp_path: Path) -> None:
    raw = document(tuple(paragraph(index, f"P{index}") for index in range(1, 11)))
    pipeline = SemanticPipeline(SemanticPipelineConfig(batch_size=4))
    registry = build_evidence_registry(raw)
    with pytest.raises(SemanticPipelineInterrupted):
        pipeline.run(
            raw,
            registry,
            BaselineUnknownClassifier(),
            tmp_path,
            interrupt_after=4,
        )
    assert len(tuple((tmp_path / "semantic/results").glob("*.json"))) == 4
    resumed = pipeline.run(raw, registry, BaselineUnknownClassifier(), tmp_path)
    assert resumed.completed == 10
    assert resumed.reused == 4
    assert len(tuple((tmp_path / "semantic/results").glob("*.json"))) == 10


@pytest.mark.parametrize("change", ["target", "context", "taxonomy", "classifier"])
def test_stale_results_are_not_reused(tmp_path: Path, change: str) -> None:
    original = document((paragraph(1, "One"), paragraph(2, "Two"), paragraph(3, "Three")))
    pipeline = SemanticPipeline()
    pipeline.run(
        original, build_evidence_registry(original), BaselineUnknownClassifier(), tmp_path
    )
    changed = original
    classifier = BaselineUnknownClassifier()
    active_pipeline = pipeline
    if change == "target":
        changed = document((paragraph(1, "Changed"), paragraph(2, "Two"), paragraph(3, "Three")))
    elif change == "context":
        changed = document((paragraph(1, "One"), paragraph(2, "Context changed"), paragraph(3, "Three")))
    elif change == "taxonomy":
        active_pipeline = SemanticPipeline(taxonomy_version="bookforge-semantic-v2-test")
        classifier = BaselineUnknownClassifier(taxonomy_version="bookforge-semantic-v2-test")
    else:
        classifier = BaselineUnknownClassifier(configuration_label="changed")
    report = active_pipeline.run(changed, build_evidence_registry(changed), classifier, tmp_path)
    assert report.stale >= 1
    assert report.reused < 3


class FailingOnceClassifier(BaselineUnknownClassifier):
    def __init__(self) -> None:
        super().__init__()
        self.failed = False

    def classify(self, analysis_view):  # type: ignore[no-untyped-def]
        if analysis_view.work_unit.sequence_index == 2 and not self.failed:
            self.failed = True
            raise RuntimeError("safe test failure")
        return super().classify(analysis_view)


def test_failure_is_isolated_and_retry_keeps_work_unit_identity(tmp_path: Path) -> None:
    raw = document(tuple(paragraph(index, f"P{index}") for index in range(1, 6)))
    units = generate_work_units(raw)
    classifier = FailingOnceClassifier()
    first = SemanticPipeline().run(raw, build_evidence_registry(raw), classifier, tmp_path)
    assert first.completed == 4
    assert first.failed == 1
    failed_unit_id = units[2].work_unit_id
    assert (tmp_path / f"semantic/failures/{failed_unit_id}.json").exists()
    second = SemanticPipeline().run(raw, build_evidence_registry(raw), classifier, tmp_path)
    assert second.completed == 5
    assert second.reused == 4
    assert not (tmp_path / f"semantic/failures/{failed_unit_id}.json").exists()


def test_invalid_classifier_output_fails_visibly_instead_of_becoming_unknown(tmp_path: Path) -> None:
    class InvalidClassifier(BaselineUnknownClassifier):
        def classify(self, analysis_view):  # type: ignore[no-untyped-def]
            result = super().classify(analysis_view)
            return result.model_copy(update={"input_fingerprint": "f" * 64})

    raw = document((paragraph(1, "Text"),))
    report = SemanticPipeline().run(
        raw, build_evidence_registry(raw), InvalidClassifier(), tmp_path
    )
    assert report.failed == 1
    assert report.completed == 0
    assert not tuple((tmp_path / "semantic/results").glob("*.json"))
    assert tuple((tmp_path / "semantic/failures").glob("*.json"))


def test_drawing_is_supported_without_semantic_or_placement_conclusion() -> None:
    drawing = RawDrawing(
        id="docx_drw000001",
        document_id=DOC_ID,
        order=1,
        drawing_type="unsupported_vml",
        source_metadata={"story": "body", "placement": "floating"},
    )
    raw = document((paragraph(1, "Before"), drawing, paragraph(2, "After")))
    units = generate_work_units(raw)
    assert units[1].source_kind is SemanticSourceKind.DRAWING
    assert units[1].structural_features.docx_placement is not None
    assert units[1].structural_features.docx_placement.placement == "floating"


def test_long_book_one_thousand_units_process_resume_and_batch(tmp_path: Path) -> None:
    raw = document(tuple(paragraph(index, f"Paragraph {index}") for index in range(1, 1001)))
    config = SemanticPipelineConfig(batch_size=50)
    units = generate_work_units(raw, config)
    assert len(units) == 1000
    assert len(deterministic_batches(units, config.batch_size)) == 20
    with pytest.raises(SemanticPipelineInterrupted):
        SemanticPipeline(config).run(
            raw,
            build_evidence_registry(raw),
            BaselineUnknownClassifier(),
            tmp_path,
            interrupt_after=137,
        )
    resumed = SemanticPipeline(config).run(
        raw,
        build_evidence_registry(raw),
        BaselineUnknownClassifier(),
        tmp_path,
    )
    assert resumed.completed == 1000
    assert resumed.reused == 137
    assert resumed.failed == 0
    assert resumed.fragments_materialized == 1000
