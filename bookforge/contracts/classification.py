"""M3 semantic-classification decision contracts.

These models record what source evidence appears to be. They deliberately do
not express flow, boundaries, joins, chapter grouping, or rendering placement.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, NewType

from pydantic import Field, StringConstraints, field_validator, model_validator

from .common import DocumentId, FrozenContractModel, SourceId, TransformationStage, utc_now
from .ids import validate_stable_id
from .semantic import SemanticType
from .source import SourceTextReference

ClassificationId = NewType("ClassificationId", str)
ReviewId = NewType("ReviewId", str)
Fingerprint = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]

SEMANTIC_TAXONOMY_VERSION = "bookforge-semantic-v1"

_NON_TEXTUAL_OR_POLYMORPHIC_TYPES = {
    SemanticType.FIGURE,
    SemanticType.TABLE,
    SemanticType.DECORATIVE,
    SemanticType.ARTIFACT,
    SemanticType.UNKNOWN,
}


class ReviewStatus(StrEnum):
    NOT_REQUIRED = "not_required"
    NEEDS_REVIEW = "needs_review"
    REVIEWED_ACCEPTED = "reviewed_accepted"
    REVIEWED_OVERRIDDEN = "reviewed_overridden"


class RationaleCode(StrEnum):
    STYLE_SIGNAL = "style_signal"
    POSITION_SIGNAL = "position_signal"
    TYPOGRAPHY_SIGNAL = "typography_signal"
    SHORT_TEXT = "short_text"
    UPPERCASE_TEXT = "uppercase_text"
    SURROUNDED_BY_BODY = "surrounded_by_body"
    IMAGE_CONTEXT = "image_context"
    REPEATED_PATTERN = "repeated_pattern"
    HEADER_STORY = "header_story"
    FOOTER_STORY = "footer_story"
    MODEL_CLASSIFICATION = "model_classification"


class ClassifierKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_MODEL = "local_model"
    CLOUD_ADAPTER = "cloud_adapter"
    HUMAN_REVIEW = "human_review"


class ClassifierIdentity(FrozenContractModel):
    name: str = Field(min_length=1)
    kind: ClassifierKind
    version: str = Field(min_length=1)
    model_identifier: str | None = None


class ClassificationProvenance(FrozenContractModel):
    document_id: DocumentId
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    stage: Literal[TransformationStage.SEMANTIC] = TransformationStage.SEMANTIC
    created_at: datetime = Field(default_factory=utc_now)


class ClassificationCandidate(FrozenContractModel):
    semantic_type: SemanticType
    confidence: float = Field(ge=0, le=1)


class ClassificationResult(FrozenContractModel):
    """Immutable, reproducible M3 decision over one logical evidence target."""

    id: ClassificationId
    target_source_ids: tuple[SourceId, ...] = Field(min_length=1)
    source_references: tuple[SourceTextReference, ...] = ()
    semantic_type: SemanticType
    confidence: float = Field(ge=0, le=1)
    candidates: tuple[ClassificationCandidate, ...] = ()
    review_status: ReviewStatus
    rationale_codes: tuple[RationaleCode, ...] = ()
    classifier: ClassifierIdentity
    configuration_fingerprint: Fingerprint
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    taxonomy_version: str = Field(default=SEMANTIC_TAXONOMY_VERSION, min_length=1)
    provenance: ClassificationProvenance

    @field_validator("id")
    @classmethod
    def stable_classification_id(cls, value: ClassificationId) -> ClassificationId:
        validate_stable_id(str(value))
        return value

    @model_validator(mode="after")
    def validate_traceability_and_candidates(self) -> "ClassificationResult":
        if len(self.target_source_ids) != len(set(self.target_source_ids)):
            raise ValueError("classification target source IDs must be unique")
        if set(self.provenance.source_ids) != set(self.target_source_ids):
            raise ValueError("classification provenance must identify the complete target")
        target_ids = set(self.target_source_ids)
        if any(reference.source_id not in target_ids for reference in self.source_references):
            raise ValueError("text references must belong to the classification target")
        if self.semantic_type not in _NON_TEXTUAL_OR_POLYMORPHIC_TYPES and not self.source_references:
            raise ValueError("textual classifications require an authoritative source text reference")
        candidate_types = [candidate.semantic_type for candidate in self.candidates]
        if len(candidate_types) != len(set(candidate_types)):
            raise ValueError("classification candidates must not repeat semantic types")
        if self.semantic_type in candidate_types:
            raise ValueError("the selected semantic type must not be repeated as a candidate")
        if len(self.rationale_codes) != len(set(self.rationale_codes)):
            raise ValueError("rationale codes must be unique")
        return self


class ClassificationReview(FrozenContractModel):
    """Auditable review record that leaves the original result unchanged."""

    id: ReviewId
    classification_id: ClassificationId
    original_semantic_type: SemanticType
    status: Literal[ReviewStatus.REVIEWED_ACCEPTED, ReviewStatus.REVIEWED_OVERRIDDEN]
    accepted_semantic_type: SemanticType
    reviewer: ClassifierIdentity
    review_fingerprint: Fingerprint
    rationale_codes: tuple[RationaleCode, ...] = ()
    provenance: ClassificationProvenance

    @field_validator("id", "classification_id")
    @classmethod
    def stable_review_ids(cls, value: ReviewId | ClassificationId) -> ReviewId | ClassificationId:
        validate_stable_id(str(value))
        return value

    @model_validator(mode="after")
    def validate_review_outcome(self) -> "ClassificationReview":
        changed = self.accepted_semantic_type is not self.original_semantic_type
        if self.status is ReviewStatus.REVIEWED_ACCEPTED and changed:
            raise ValueError("an accepted review must retain the original semantic type")
        if self.status is ReviewStatus.REVIEWED_OVERRIDDEN and not changed:
            raise ValueError("an overridden review must change the semantic type")
        if len(self.rationale_codes) != len(set(self.rationale_codes)):
            raise ValueError("rationale codes must be unique")
        return self
