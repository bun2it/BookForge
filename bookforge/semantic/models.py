from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator

from bookforge.contracts.classification import ClassificationResult, ClassifierIdentity, Fingerprint
from bookforge.contracts.common import DocumentId, FrozenContractModel, SourceId


SEMANTIC_PIPELINE_VERSION = "m3a-v1"
WORK_UNIT_POLICY_VERSION = "semantic-work-unit-v1"


class Story(StrEnum):
    BODY = "body"
    HEADER = "header"
    FOOTER = "footer"
    OTHER = "other"


class SemanticSourceKind(StrEnum):
    PARAGRAPH = "paragraph"
    TEXT_BLOCK = "text_block"
    IMAGE = "image"
    TABLE = "table"
    DRAWING = "drawing"


class ProcessingState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class FailureCategory(StrEnum):
    CLASSIFIER_ERROR = "classifier_error"
    INVALID_RESULT = "invalid_result"
    EVIDENCE_ERROR = "evidence_error"


class SemanticPipelineConfig(FrozenContractModel):
    context_before: int = Field(default=3, ge=0)
    context_after: int = Field(default=3, ge=0)
    batch_size: int = Field(default=50, ge=1)
    continue_on_failure: bool = True
    policy_version: str = WORK_UNIT_POLICY_VERSION


class DocxPlacementEvidence(FrozenContractModel):
    placement: str | None = None
    containing_paragraph_id: SourceId | None = None
    run_order: int | None = Field(default=None, ge=0)
    drawing_order_in_run: int | None = Field(default=None, ge=0)


class StructuralFeatures(FrozenContractModel):
    source_kind: SemanticSourceKind
    story: Story
    sequence_index: int = Field(ge=0)
    style_id: str | None = None
    alignment: str | None = None
    text_length: int | None = Field(default=None, ge=0)
    is_empty: bool | None = None
    run_count: int | None = Field(default=None, ge=0)
    bold_run_count: int | None = Field(default=None, ge=0)
    italic_run_count: int | None = Field(default=None, ge=0)
    underline_run_count: int | None = Field(default=None, ge=0)
    superscript_run_count: int | None = Field(default=None, ge=0)
    subscript_run_count: int | None = Field(default=None, ge=0)
    uppercase_ratio: float | None = Field(default=None, ge=0, le=1)
    has_images: bool | None = None
    image_only_paragraph: bool | None = None
    hyperlink_count: int | None = Field(default=None, ge=0)
    table_row_count: int | None = Field(default=None, ge=0)
    table_max_column_count: int | None = Field(default=None, ge=0)
    image_mime_type: str | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    drawing_type: str | None = None
    docx_placement: DocxPlacementEvidence | None = None


class SemanticWorkUnit(FrozenContractModel):
    work_unit_id: str
    document_id: DocumentId
    sequence_index: int = Field(ge=0)
    story: Story
    target_source_ids: tuple[SourceId, ...] = Field(min_length=1)
    context_before_source_ids: tuple[SourceId, ...] = ()
    context_after_source_ids: tuple[SourceId, ...] = ()
    source_kind: SemanticSourceKind
    structural_features: StructuralFeatures
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    policy_fingerprint: Fingerprint

    @field_validator("work_unit_id")
    @classmethod
    def valid_work_unit_id(cls, value: str) -> str:
        import re

        if re.fullmatch(r"swu_[0-9a-f]{20}", value) is None:
            raise ValueError("invalid semantic work-unit ID")
        return value


@dataclass(frozen=True, slots=True)
class AnalysisContextItem:
    source_id: SourceId
    source_kind: SemanticSourceKind
    text: str | None


@dataclass(frozen=True, slots=True)
class AnalysisView:
    work_unit: SemanticWorkUnit
    target_text: str | None
    context_before: tuple[AnalysisContextItem, ...]
    context_after: tuple[AnalysisContextItem, ...]


class SemanticClassifier(Protocol):
    identity: ClassifierIdentity
    configuration_fingerprint: str

    def classify(self, analysis_view: AnalysisView) -> ClassificationResult: ...


class SemanticBatch(FrozenContractModel):
    batch_index: int = Field(ge=0)
    work_unit_ids: tuple[str, ...] = Field(min_length=1)


class FailureRecord(FrozenContractModel):
    work_unit_id: str
    category: FailureCategory
    message: str
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    classifier_configuration_fingerprint: Fingerprint
    retryable: bool


class ProcessingSummary(FrozenContractModel):
    pending: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    needs_review: int = Field(default=0, ge=0)
    reused: int = Field(default=0, ge=0)
    stale: int = Field(default=0, ge=0)


class SemanticManifest(FrozenContractModel):
    document_id: DocumentId
    semantic_pipeline_version: str = SEMANTIC_PIPELINE_VERSION
    taxonomy_version: str
    policy_fingerprint: Fingerprint
    classifier: ClassifierIdentity
    classifier_configuration_fingerprint: Fingerprint
    context_before: int = Field(ge=0)
    context_after: int = Field(ge=0)
    batch_size: int = Field(ge=1)
    total_work_units: int = Field(ge=0)
    total_batches: int = Field(ge=0)
    summary: ProcessingSummary
    provenance_epoch: str = "1970-01-01T00:00:00Z"


class PipelineReport(FrozenContractModel):
    total_work_units: int
    total_batches: int
    completed: int
    failed: int
    needs_review: int
    reused: int
    stale: int
    fragments_materialized: int
