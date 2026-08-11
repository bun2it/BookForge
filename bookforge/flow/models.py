from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Mapping, TypeAlias

from pydantic import Field, field_validator, model_validator

from bookforge.contracts.classification import ClassificationResult, Fingerprint
from bookforge.contracts.common import DocumentId, FragmentId, FrozenContractModel, SourceId
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.assembly import SemanticContentNode
from bookforge.contracts.flow import (
    CaptionAssociation, FigurePlacement, FlowDecisionReview, InclusionDecision,
    LogicalBoundaryDecision, LogicalListV3, ResolvedContentFlow, StructuralRegionAssignment,
)
from bookforge.contracts.semantic import SemanticFragment, SemanticType

FlowInputNode = SemanticContentNode | SemanticFragment
FlowReplacementDecision: TypeAlias = (
    LogicalBoundaryDecision | InclusionDecision | FigurePlacement | CaptionAssociation
)


class AcceptedFlowReviewInput(FrozenContractModel):
    """Explicit accepted review and its immutable replacement decision."""

    review: FlowDecisionReview
    replacement_decision: FlowReplacementDecision

    @model_validator(mode="after")
    def matching_accepted_identity(self) -> "AcceptedFlowReviewInput":
        if self.review.accepted_decision_id != self.replacement_decision.audit.decision_id:
            raise ValueError("accepted review ID must match replacement decision ID")
        return self

FLOW_RESOLVER_VERSION = "m4a-v1"
DEFAULT_FLOW_POLICY_VERSION = "deterministic-flow-v1"


class FlowWorkUnitKind(StrEnum):
    BOUNDARY = "boundary"
    INCLUSION = "inclusion"
    FIGURE_PLACEMENT = "figure_placement"
    CAPTION_ASSOCIATION = "caption_association"


class FlowProcessingState(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_REVIEW = "needs_review"


class FlowFailureCategory(StrEnum):
    RULE_ERROR = "rule_error"
    INVALID_DECISION = "invalid_decision"
    EVIDENCE_ERROR = "evidence_error"


class FlowSourceFeatures(FrozenContractModel):
    source_order: int = Field(ge=0)
    story: str | None = None
    physical_segment_id: str | None = None
    source_boundary_before: bool = False
    continuation_group_id: str | None = None
    logical_sequence_explicit: bool = False
    image_only_container: bool = False
    source_anchor_evidence_ids: tuple[SourceId, ...] = ()


class FlowResolverPolicy(FrozenContractModel):
    policy_version: str = DEFAULT_FLOW_POLICY_VERSION
    context_size: int = Field(default=2, ge=0)
    chapter_break_new_page: bool = True
    part_break_new_page: bool = True
    section_break_new_page: bool = False
    subsection_break_new_page: bool = False
    exclude_running_headers: bool = True
    exclude_running_footers: bool = True
    exclude_page_numbers: bool = True
    exclude_decorative: bool = True
    review_threshold: float = Field(default=0.75, ge=0, le=1)
    continue_on_failure: bool = True


@dataclass(frozen=True, slots=True)
class FlowResolverInput:
    document_id: DocumentId
    ordered_fragments: tuple[FlowInputNode, ...]
    accepted_classifications: Mapping[FragmentId, ClassificationResult]
    evidence_registry: EvidenceRegistry
    source_features: Mapping[FragmentId, FlowSourceFeatures]
    semantic_taxonomy_version: str
    accepted_logical_lists: tuple[LogicalListV3, ...] = ()
    structural_regions: StructuralRegionAssignment | None = None
    accepted_flow_reviews: tuple[AcceptedFlowReviewInput, ...] = ()


class FlowWorkUnit(FrozenContractModel):
    work_unit_id: str
    kind: FlowWorkUnitKind
    document_id: DocumentId
    sequence_index: int = Field(ge=0)
    target_fragment_ids: tuple[FragmentId, ...] = Field(min_length=1)
    context_before_fragment_ids: tuple[FragmentId, ...] = ()
    context_after_fragment_ids: tuple[FragmentId, ...] = ()
    accepted_semantic_types: tuple[SemanticType, ...] = Field(min_length=1)
    classification_result_ids: tuple[str, ...] = ()
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    policy_fingerprint: Fingerprint

    @field_validator("work_unit_id")
    @classmethod
    def valid_work_unit_id(cls, value: str) -> str:
        import re

        if re.fullmatch(r"fwu_[0-9a-f]{20}", value) is None:
            raise ValueError("invalid flow work-unit ID")
        return value


@dataclass(frozen=True, slots=True)
class FlowAnalysisView:
    work_unit: FlowWorkUnit
    target_fragments: tuple[FlowInputNode, ...]
    target_texts: tuple[str | None, ...]
    context_before_types: tuple[SemanticType, ...]
    context_after_types: tuple[SemanticType, ...]
    source_features: tuple[FlowSourceFeatures, ...]


class FlowFailureRecord(FrozenContractModel):
    work_unit_id: str
    category: FlowFailureCategory
    message: str
    input_fingerprint: Fingerprint
    context_fingerprint: Fingerprint
    policy_fingerprint: Fingerprint
    resolver_configuration_fingerprint: Fingerprint
    retryable: bool = True


class FlowProcessingSummary(FrozenContractModel):
    pending: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    needs_review: int = Field(default=0, ge=0)
    reused: int = Field(default=0, ge=0)
    stale: int = Field(default=0, ge=0)


class FlowManifest(FrozenContractModel):
    document_id: DocumentId
    resolver_version: str = FLOW_RESOLVER_VERSION
    semantic_taxonomy_version: str
    policy_version: str
    policy_fingerprint: Fingerprint
    resolver_configuration_fingerprint: Fingerprint
    total_fragments: int = Field(ge=0)
    total_work_units: int = Field(ge=0)
    summary: FlowProcessingSummary
    provenance_epoch: str = "1970-01-01T00:00:00Z"


class FlowResolverReport(FrozenContractModel):
    total_fragments: int
    total_work_units: int
    completed: int
    failed: int
    needs_review: int
    reused: int
    stale: int
    boundary_decisions: int
    inclusion_decisions: int
    placements: int
    caption_associations: int
    groups: int
    unresolved: int
    resolved_flow: ResolvedContentFlow | None = None
    accepted_replacement_decisions: tuple[FlowReplacementDecision, ...] = ()
