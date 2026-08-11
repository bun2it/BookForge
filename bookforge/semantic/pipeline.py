from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bookforge.contracts.classification import (
    SEMANTIC_TAXONOMY_VERSION,
    ClassificationProvenance,
    ClassificationResult,
    ClassifierIdentity,
    ClassifierKind,
    ReviewStatus,
)
from bookforge.contracts.assembly import (
    EvidenceKind,
    EvidenceReference,
    FigureDataV3,
    FigureSemanticNode,
    SemanticContentNode,
    TableCellV3,
    TableDataV3,
    TableRowV3,
    TableSemanticNode,
    TextSemanticNode,
    UnsupportedContentKind,
    UnsupportedSemanticNode,
)
from bookforge.contracts.common import ProcessingProvenance, SourceId, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.ids import classification_result_id, semantic_fragment_id
from bookforge.contracts.raw import (
    RawDocument,
    RawDrawing,
    RawImage,
    RawObject,
    RawParagraph,
    RawTable,
    RawTextBlock,
)
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference

from .models import (
    AnalysisContextItem,
    AnalysisView,
    DocxPlacementEvidence,
    FailureCategory,
    FailureRecord,
    PipelineReport,
    ProcessingSummary,
    SemanticBatch,
    SemanticClassifier,
    SemanticManifest,
    SemanticPipelineConfig,
    SemanticSourceKind,
    SemanticWorkUnit,
    Story,
    StructuralFeatures,
)
from .workspace import SemanticWorkspace, SemanticWorkspaceError

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class SemanticPipelineError(RuntimeError):
    pass


class InvalidClassificationResultError(SemanticPipelineError):
    pass


class SemanticPipelineInterrupted(SemanticPipelineError):
    pass


def _canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def classifier_configuration_fingerprint(identity: ClassifierIdentity, config: object) -> str:
    return _canonical_fingerprint(
        {"identity": identity.model_dump(mode="json"), "configuration": config}
    )


def build_evidence_registry(raw_document: RawDocument) -> EvidenceRegistry:
    """Rebuild the textual index from frozen raw evidence without modifying it."""
    registry = EvidenceRegistry()
    for source_object in _document_objects(raw_document):
        if isinstance(source_object, (RawParagraph, RawTextBlock)):
            registry.register(source_object)
            for run in source_object.runs:
                registry.register(run)
        elif isinstance(source_object, RawTable):
            for row in source_object.rows:
                for cell in row.cells:
                    registry.register(cell)
    return registry


def _document_objects(raw_document: RawDocument) -> tuple[RawObject, ...]:
    if raw_document.objects:
        return raw_document.objects
    return tuple(source_object for page in raw_document.pages for source_object in page.objects)


def _kind(source_object: RawObject) -> SemanticSourceKind | None:
    if isinstance(source_object, RawParagraph):
        return SemanticSourceKind.PARAGRAPH
    if isinstance(source_object, RawTextBlock):
        return SemanticSourceKind.TEXT_BLOCK
    if isinstance(source_object, RawImage):
        return SemanticSourceKind.IMAGE
    if isinstance(source_object, RawTable):
        return SemanticSourceKind.TABLE
    if isinstance(source_object, RawDrawing):
        return SemanticSourceKind.DRAWING
    return None


def _story_value(value: object) -> Story:
    normalized = str(value).lower()
    if normalized == "body":
        return Story.BODY
    if normalized.startswith("header") or normalized == "header":
        return Story.HEADER
    if normalized.startswith("footer") or normalized == "footer":
        return Story.FOOTER
    return Story.OTHER


def _object_story(source_object: RawObject, object_by_id: dict[SourceId, RawObject]) -> Story:
    metadata = getattr(source_object, "source_metadata", {})
    story = metadata.get("story")
    if story is not None:
        return _story_value(story)
    parent_id = metadata.get("containing_paragraph_id")
    if parent_id is not None:
        parent = object_by_id.get(SourceId(str(parent_id)))
        if parent is not None:
            return _object_story(parent, object_by_id)
    part_name = str(metadata.get("part_name", ""))
    if "/header" in part_name:
        return Story.HEADER
    if "/footer" in part_name:
        return Story.FOOTER
    return Story.BODY


def _uppercase_ratio(text: str) -> float | None:
    letters = [character for character in text if character.isalpha()]
    if not letters:
        return None
    return sum(character.isupper() for character in letters) / len(letters)


def _features(
    source_object: RawObject,
    kind: SemanticSourceKind,
    story: Story,
    sequence_index: int,
) -> StructuralFeatures:
    if isinstance(source_object, (RawParagraph, RawTextBlock)):
        metadata = source_object.source_metadata
        anchored = tuple(metadata.get("anchored_object_ids", ()))
        style_id = None
        if source_object.style is not None:
            style_id = source_object.style.name
            if style_id is None:
                raw_style_id = source_object.style.source_metadata.get("style_id")
                style_id = str(raw_style_id) if raw_style_id is not None else None
        return StructuralFeatures(
            source_kind=kind,
            story=story,
            sequence_index=sequence_index,
            style_id=style_id,
            alignment=source_object.style.alignment if source_object.style else None,
            text_length=len(source_object.text),
            is_empty=source_object.text == "",
            run_count=len(source_object.runs),
            bold_run_count=sum(run.bold is True for run in source_object.runs),
            italic_run_count=sum(run.italic is True for run in source_object.runs),
            underline_run_count=sum(run.underline is True for run in source_object.runs),
            superscript_run_count=sum(run.superscript is True for run in source_object.runs),
            subscript_run_count=sum(run.subscript is True for run in source_object.runs),
            uppercase_ratio=_uppercase_ratio(source_object.text),
            has_images=bool(anchored),
            image_only_paragraph=bool(anchored) and source_object.text == "",
            hyperlink_count=len(tuple(metadata.get("hyperlinks", ()))),
        )
    if isinstance(source_object, RawImage):
        metadata = source_object.source_metadata
        return StructuralFeatures(
            source_kind=kind,
            story=story,
            sequence_index=sequence_index,
            image_mime_type=str(metadata.get("content_type"))
            if metadata.get("content_type") is not None
            else None,
            width=source_object.width,
            height=source_object.height,
            docx_placement=DocxPlacementEvidence(
                placement=str(metadata.get("placement"))
                if metadata.get("placement") is not None
                else None,
                containing_paragraph_id=SourceId(str(metadata["containing_paragraph_id"]))
                if metadata.get("containing_paragraph_id") is not None
                else None,
                run_order=int(metadata["run_order"])
                if metadata.get("run_order") is not None
                else None,
                drawing_order_in_run=int(metadata["drawing_order_in_run"])
                if metadata.get("drawing_order_in_run") is not None
                else None,
            ),
        )
    if isinstance(source_object, RawTable):
        return StructuralFeatures(
            source_kind=kind,
            story=story,
            sequence_index=sequence_index,
            table_row_count=len(source_object.rows),
            table_max_column_count=max((len(row.cells) for row in source_object.rows), default=0),
        )
    assert isinstance(source_object, RawDrawing)
    metadata = source_object.source_metadata
    return StructuralFeatures(
        source_kind=kind,
        story=story,
        sequence_index=sequence_index,
        drawing_type=source_object.drawing_type,
        docx_placement=DocxPlacementEvidence(
            placement=str(metadata.get("placement"))
            if metadata.get("placement") is not None
            else None,
            containing_paragraph_id=SourceId(str(metadata["containing_paragraph_id"]))
            if metadata.get("containing_paragraph_id") is not None
            else None,
        ),
    )


def _evidence_digest(source_object: RawObject) -> str:
    return _canonical_fingerprint(source_object.model_dump(mode="json"))


def generate_work_units(
    raw_document: RawDocument,
    config: SemanticPipelineConfig = SemanticPipelineConfig(),
    taxonomy_version: str = SEMANTIC_TAXONOMY_VERSION,
) -> tuple[SemanticWorkUnit, ...]:
    objects = _document_objects(raw_document)
    object_by_id = {source_object.id: source_object for source_object in objects}
    analyzable: list[tuple[RawObject, SemanticSourceKind, Story]] = []
    for source_object in objects:
        kind = _kind(source_object)
        if kind is not None:
            analyzable.append((source_object, kind, _object_story(source_object, object_by_id)))

    story_groups: dict[Story, list[tuple[RawObject, SemanticSourceKind, Story]]] = {}
    story_positions: dict[SourceId, int] = {}
    for item in analyzable:
        group = story_groups.setdefault(item[2], [])
        story_positions[item[0].id] = len(group)
        group.append(item)

    policy_fingerprint = _canonical_fingerprint(
        {
            "pipeline": "m3a-v1",
            "policy_version": config.policy_version,
            "context_before": config.context_before,
            "context_after": config.context_after,
            "story_crossing": "never",
            "targets": [kind.value for kind in SemanticSourceKind],
        }
    )
    units: list[SemanticWorkUnit] = []
    for sequence_index, (target, kind, story) in enumerate(analyzable):
        same_story = story_groups[story]
        story_index = story_positions[target.id]
        before_objects = same_story[max(0, story_index - config.context_before) : story_index]
        after_objects = same_story[story_index + 1 : story_index + 1 + config.context_after]
        before_ids = tuple(item[0].id for item in before_objects)
        after_ids = tuple(item[0].id for item in after_objects)
        context_payload = [
            {"source_id": str(item[0].id), "digest": _evidence_digest(item[0])}
            for item in (*before_objects, *after_objects)
        ]
        context_fingerprint = _canonical_fingerprint(context_payload)
        structural_features = _features(target, kind, story, sequence_index)
        input_fingerprint = _canonical_fingerprint(
            {
                "document_id": str(raw_document.id),
                "target": {"source_id": str(target.id), "digest": _evidence_digest(target)},
                "context": context_payload,
                "structural_features": structural_features.model_dump(mode="json"),
                "policy_fingerprint": policy_fingerprint,
                "taxonomy_version": taxonomy_version,
            }
        )
        work_unit_id = "swu_" + _canonical_fingerprint(
            {
                "document_id": str(raw_document.id),
                "sequence_index": sequence_index,
                "target_source_ids": [str(target.id)],
                "policy_version": config.policy_version,
            }
        )[:20]
        units.append(
            SemanticWorkUnit(
                work_unit_id=work_unit_id,
                document_id=raw_document.id,
                sequence_index=sequence_index,
                story=story,
                target_source_ids=(target.id,),
                context_before_source_ids=before_ids,
                context_after_source_ids=after_ids,
                source_kind=kind,
                structural_features=structural_features,
                input_fingerprint=input_fingerprint,
                context_fingerprint=context_fingerprint,
                policy_fingerprint=policy_fingerprint,
            )
        )
    return tuple(units)


def deterministic_batches(
    units: Sequence[SemanticWorkUnit], batch_size: int = 50
) -> tuple[SemanticBatch, ...]:
    if batch_size < 1:
        raise ValueError("batch size must be at least one")
    return tuple(
        SemanticBatch(
            batch_index=start // batch_size,
            work_unit_ids=tuple(unit.work_unit_id for unit in units[start : start + batch_size]),
        )
        for start in range(0, len(units), batch_size)
    )


def _text_for_object(source_object: RawObject, registry: EvidenceRegistry) -> str | None:
    if isinstance(source_object, (RawParagraph, RawTextBlock)):
        return registry.resolve_text(SourceTextReference(source_id=source_object.id))
    if isinstance(source_object, RawTable):
        return "\n".join(
            registry.resolve_text(SourceTextReference(source_id=cell.id))
            for row in source_object.rows
            for cell in row.cells
        )
    return None


def build_analysis_view(
    unit: SemanticWorkUnit,
    raw_document: RawDocument,
    registry: EvidenceRegistry,
) -> AnalysisView:
    objects = _document_objects(raw_document)
    object_by_id = {source_object.id: source_object for source_object in objects}

    def context_item(source_id: SourceId) -> AnalysisContextItem:
        source_object = object_by_id[source_id]
        kind = _kind(source_object)
        if kind is None:
            raise SemanticPipelineError(f"context object is not analyzable: {source_id}")
        return AnalysisContextItem(
            source_id=source_id,
            source_kind=kind,
            text=_text_for_object(source_object, registry),
        )

    target = object_by_id[unit.target_source_ids[0]]
    return AnalysisView(
        work_unit=unit,
        target_text=_text_for_object(target, registry),
        context_before=tuple(context_item(source_id) for source_id in unit.context_before_source_ids),
        context_after=tuple(context_item(source_id) for source_id in unit.context_after_source_ids),
    )


class BaselineUnknownClassifier:
    """Conservative infrastructure classifier: always UNKNOWN, never heuristic."""

    identity = ClassifierIdentity(
        name="bookforge.baseline_unknown",
        kind=ClassifierKind.DETERMINISTIC,
        version="1",
    )

    def __init__(
        self,
        *,
        taxonomy_version: str = SEMANTIC_TAXONOMY_VERSION,
        configuration_label: str = "default",
    ) -> None:
        self.taxonomy_version = taxonomy_version
        self.configuration_fingerprint = classifier_configuration_fingerprint(
            self.identity,
            {
                "decision": "always_unknown",
                "confidence": 0.0,
                "configuration_label": configuration_label,
            },
        )

    def classify(self, analysis_view: AnalysisView) -> ClassificationResult:
        unit = analysis_view.work_unit
        references: tuple[SourceTextReference, ...] = ()
        if unit.source_kind in {
            SemanticSourceKind.PARAGRAPH,
            SemanticSourceKind.TEXT_BLOCK,
        }:
            references = tuple(
                SourceTextReference(source_id=source_id) for source_id in unit.target_source_ids
            )
        result_id = classification_result_id(
            target_source_ids=[str(source_id) for source_id in unit.target_source_ids],
            taxonomy_version=self.taxonomy_version,
            classifier_name=self.identity.name,
            classifier_version=self.identity.version,
            configuration_fingerprint=self.configuration_fingerprint,
            input_fingerprint=unit.input_fingerprint,
            context_fingerprint=unit.context_fingerprint,
        )
        return ClassificationResult(
            id=result_id,
            target_source_ids=unit.target_source_ids,
            source_references=references,
            semantic_type=SemanticType.UNKNOWN,
            confidence=0.0,
            review_status=ReviewStatus.NEEDS_REVIEW,
            classifier=self.identity,
            configuration_fingerprint=self.configuration_fingerprint,
            input_fingerprint=unit.input_fingerprint,
            context_fingerprint=unit.context_fingerprint,
            taxonomy_version=self.taxonomy_version,
            provenance=ClassificationProvenance(
                document_id=unit.document_id,
                source_ids=unit.target_source_ids,
                created_at=EPOCH,
            ),
        )


def validate_classification_result(
    result: ClassificationResult,
    unit: SemanticWorkUnit,
    classifier: SemanticClassifier,
    registry: EvidenceRegistry,
    taxonomy_version: str = SEMANTIC_TAXONOMY_VERSION,
) -> None:
    expected_id = classification_result_id(
        target_source_ids=[str(source_id) for source_id in unit.target_source_ids],
        taxonomy_version=taxonomy_version,
        classifier_name=classifier.identity.name,
        classifier_version=classifier.identity.version,
        configuration_fingerprint=classifier.configuration_fingerprint,
        input_fingerprint=unit.input_fingerprint,
        context_fingerprint=unit.context_fingerprint,
    )
    checks = {
        "classification ID": str(result.id) == expected_id,
        "target identity": result.target_source_ids == unit.target_source_ids,
        "document identity": result.provenance.document_id == unit.document_id,
        "input fingerprint": result.input_fingerprint == unit.input_fingerprint,
        "context fingerprint": result.context_fingerprint == unit.context_fingerprint,
        "taxonomy version": result.taxonomy_version == taxonomy_version,
        "classifier identity": result.classifier == classifier.identity,
        "classifier configuration": result.configuration_fingerprint
        == classifier.configuration_fingerprint,
    }
    failed = [label for label, valid in checks.items() if not valid]
    if failed:
        raise InvalidClassificationResultError(
            "classification result does not match work unit: " + ", ".join(failed)
        )
    try:
        for reference in result.source_references:
            registry.resolve_text(reference)
    except Exception as error:
        raise InvalidClassificationResultError("classification has invalid source references") from error


def materialize_fragment(
    result: ClassificationResult, unit: SemanticWorkUnit
) -> SemanticFragment | None:
    if not result.source_references:
        return None
    return SemanticFragment(
        id=semantic_fragment_id(unit.sequence_index + 1),
        semantic_type=result.semantic_type,
        source_references=list(result.source_references),
        confidence=result.confidence,
        provenance=ProcessingProvenance(
            document_id=unit.document_id,
            source_ids=list(unit.target_source_ids),
            stage=TransformationStage.SEMANTIC,
            processor=result.classifier.name,
            processor_version=result.classifier.version,
            created_at=EPOCH,
        ),
    )


def materialize_flow_node(
    result: ClassificationResult,
    unit: SemanticWorkUnit,
    raw_document: RawDocument,
) -> SemanticContentNode | None:
    """Project an accepted M3 result into the source-neutral V3 flow union.

    Identity is the historical deterministic semantic ID for the work-unit
    sequence. UNKNOWN non-text evidence deliberately remains unresolved.
    """
    fragment_id = semantic_fragment_id(unit.sequence_index + 1)
    objects = {item.id: item for item in _document_objects(raw_document)}
    targets = tuple(objects[source_id] for source_id in result.target_source_ids)
    if result.semantic_type is SemanticType.FIGURE:
        images = [item for item in targets if isinstance(item, RawImage)]
        if len(images) != 1 or len(targets) != 1:
            raise InvalidClassificationResultError("FIGURE requires one explicitly targeted RawImage")
        image = images[0]
        return FigureSemanticNode(
            id=fragment_id,
            evidence=(EvidenceReference(source_id=image.id, kind=EvidenceKind.IMAGE, asset_reference=image.asset_reference),),
            figure=FigureDataV3(fragment_id=fragment_id, source_image_id=image.id, confidence=result.confidence),
        )
    if result.semantic_type is SemanticType.TABLE:
        tables = [item for item in targets if isinstance(item, RawTable)]
        if len(tables) != 1 or len(targets) != 1:
            raise InvalidClassificationResultError("TABLE requires one explicitly targeted RawTable")
        table = tables[0]
        rows = tuple(
            TableRowV3(
                index=row.index,
                cells=tuple(
                    TableCellV3(
                        row_index=cell.row_index,
                        column_index=cell.column_index,
                        source_references=(SourceTextReference(source_id=cell.id),),
                        row_span=cell.row_span,
                        column_span=cell.column_span,
                    )
                    for cell in row.cells
                ),
            )
            for row in table.rows
        )
        return TableSemanticNode(
            id=fragment_id,
            evidence=(EvidenceReference(source_id=table.id, kind=EvidenceKind.TABLE),),
            table=TableDataV3(fragment_id=fragment_id, source_ids=(table.id,), rows=rows),
        )
    if any(isinstance(item, RawDrawing) for item in targets):
        if result.semantic_type is SemanticType.UNKNOWN:
            return None
        if result.semantic_type not in {SemanticType.ARTIFACT, SemanticType.DECORATIVE}:
            raise InvalidClassificationResultError("drawing classification is incompatible with unsupported node family")
        return UnsupportedSemanticNode(
            id=fragment_id,
            content_kind=UnsupportedContentKind.DRAWING,
            evidence=tuple(EvidenceReference(source_id=item.id, kind=EvidenceKind.DRAWING) for item in targets),
            reason_code=f"accepted_{result.semantic_type.value}",
        )
    if not result.source_references:
        return None
    return TextSemanticNode(
        id=fragment_id,
        semantic_type=result.semantic_type,
        source_references=result.source_references,
        source_evidence=tuple(
            EvidenceReference(source_id=reference.source_id, kind=EvidenceKind.TEXT)
            for reference in result.source_references
        ),
        confidence=result.confidence,
    )


class SemanticPipeline:
    def __init__(
        self,
        config: SemanticPipelineConfig = SemanticPipelineConfig(),
        taxonomy_version: str = SEMANTIC_TAXONOMY_VERSION,
    ) -> None:
        self.config = config
        self.taxonomy_version = taxonomy_version

    def run(
        self,
        raw_document: RawDocument,
        registry: EvidenceRegistry,
        classifier: SemanticClassifier,
        document_workspace: Path,
        *,
        interrupt_after: int | None = None,
    ) -> PipelineReport:
        units = generate_work_units(raw_document, self.config, self.taxonomy_version)
        batches = deterministic_batches(units, self.config.batch_size)
        workspace = SemanticWorkspace(document_workspace)
        workspace.prepare()
        for unit in units:
            workspace.write_unit(unit)

        completed = failed = needs_review = reused = stale = fragments = 0
        newly_processed = 0

        def update_manifest() -> None:
            workspace.write_manifest(
                SemanticManifest(
                    document_id=raw_document.id,
                    taxonomy_version=self.taxonomy_version,
                    policy_fingerprint=units[0].policy_fingerprint
                    if units
                    else _canonical_fingerprint(self.config.model_dump(mode="json")),
                    classifier=classifier.identity,
                    classifier_configuration_fingerprint=classifier.configuration_fingerprint,
                    context_before=self.config.context_before,
                    context_after=self.config.context_after,
                    batch_size=self.config.batch_size,
                    total_work_units=len(units),
                    total_batches=len(batches),
                    summary=ProcessingSummary(
                        pending=max(0, len(units) - completed - failed),
                        completed=completed,
                        failed=failed,
                        needs_review=needs_review,
                        reused=reused,
                        stale=stale,
                    ),
                )
            )

        update_manifest()
        for unit in units:
            result: ClassificationResult | None = None
            try:
                cached = workspace.load_result(unit.work_unit_id)
                if cached is not None:
                    try:
                        validate_classification_result(
                            cached, unit, classifier, registry, self.taxonomy_version
                        )
                    except InvalidClassificationResultError:
                        stale += 1
                    else:
                        result = cached
                        reused += 1
                if result is None:
                    view = build_analysis_view(unit, raw_document, registry)
                    result = classifier.classify(view)
                    validate_classification_result(
                        result, unit, classifier, registry, self.taxonomy_version
                    )
                    workspace.write_result(unit.work_unit_id, result)
                    newly_processed += 1
                fragment = materialize_fragment(result, unit)
                if fragment is not None:
                    workspace.write_fragment(fragment)
                    fragments += 1
                workspace.clear_failure(unit.work_unit_id)
                completed += 1
                if result.review_status is ReviewStatus.NEEDS_REVIEW:
                    needs_review += 1
            except SemanticWorkspaceError:
                stale += 1
                try:
                    view = build_analysis_view(unit, raw_document, registry)
                    result = classifier.classify(view)
                    validate_classification_result(
                        result, unit, classifier, registry, self.taxonomy_version
                    )
                    workspace.write_result(unit.work_unit_id, result)
                    fragment = materialize_fragment(result, unit)
                    if fragment is not None:
                        workspace.write_fragment(fragment)
                        fragments += 1
                    workspace.clear_failure(unit.work_unit_id)
                    completed += 1
                    needs_review += result.review_status is ReviewStatus.NEEDS_REVIEW
                    newly_processed += 1
                except Exception as error:
                    failed += 1
                    self._record_failure(workspace, unit, classifier, error)
            except Exception as error:
                failed += 1
                self._record_failure(workspace, unit, classifier, error)
                if not self.config.continue_on_failure:
                    update_manifest()
                    raise SemanticPipelineError(f"semantic unit failed: {unit.work_unit_id}") from error
            update_manifest()
            if interrupt_after is not None and newly_processed >= interrupt_after:
                raise SemanticPipelineInterrupted(
                    f"semantic pipeline interrupted after {newly_processed} new units"
                )
        return PipelineReport(
            total_work_units=len(units),
            total_batches=len(batches),
            completed=completed,
            failed=failed,
            needs_review=needs_review,
            reused=reused,
            stale=stale,
            fragments_materialized=fragments,
        )

    @staticmethod
    def _record_failure(
        workspace: SemanticWorkspace,
        unit: SemanticWorkUnit,
        classifier: SemanticClassifier,
        error: Exception,
    ) -> None:
        category = (
            FailureCategory.INVALID_RESULT
            if isinstance(error, InvalidClassificationResultError)
            else FailureCategory.CLASSIFIER_ERROR
        )
        safe_message = f"{type(error).__name__}: {str(error)[:400]}"
        workspace.write_failure(
            FailureRecord(
                work_unit_id=unit.work_unit_id,
                category=category,
                message=safe_message,
                input_fingerprint=unit.input_fingerprint,
                context_fingerprint=unit.context_fingerprint,
                classifier_configuration_fingerprint=classifier.configuration_fingerprint,
                retryable=True,
            )
        )
