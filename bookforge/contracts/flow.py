from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal, NewType

from pydantic import Field, field_validator, model_validator

from .classification import (
    ClassificationId,
    Fingerprint,
    ReviewStatus,
)
from .common import (
    ContractModel,
    DocumentId,
    FragmentId,
    FrozenContractModel,
    ProcessingProvenance,
    SourceId,
)
from .ids import validate_stable_id
from .semantic import BoundaryOperation
from .source import SourceTextReference


class FlowEntry(ContractModel):
    fragment_id: FragmentId
    parent_fragment_id: FragmentId | None = None
    depth: int = Field(default=0, ge=0)


class ContentFlow(ContractModel):
    revision: str
    entries: list[FlowEntry]
    applied_boundary_operations: list[BoundaryOperation] = Field(default_factory=list)
    provenance: ProcessingProvenance


# M4.0 additive contracts. The original ContentFlow/BoundaryOperation models
# remain available for historical compatibility.

FlowDecisionId = NewType("FlowDecisionId", str)
FlowGroupId = NewType("FlowGroupId", str)
FlowReviewId = NewType("FlowReviewId", str)


class ContinuityType(StrEnum):
    KEEP_SEPARATE = "keep_separate"
    JOIN_DIRECT = "join_direct"
    JOIN_WITH_SPACE = "join_with_space"
    JOIN_WITH_NEWLINE = "join_with_newline"
    JOIN_REMOVE_TRAILING_HYPHEN = "join_remove_trailing_hyphen"
    CONTINUE_LIST = "continue_list"
    CONTINUE_TABLE = "continue_table"
    NO_CONTINUITY_DECISION = "no_continuity_decision"
    UNRESOLVED = "unresolved"


class StructuralBoundaryType(StrEnum):
    NONE = "none"
    SECTION = "section"
    SUBSECTION = "subsection"
    CHAPTER = "chapter"
    PART = "part"
    FRONT_MATTER_TRANSITION = "front_matter_transition"
    BACK_MATTER_TRANSITION = "back_matter_transition"
    UNRESOLVED = "unresolved"


class LogicalBreakIntent(StrEnum):
    NONE = "none"
    NEW_PAGE = "new_page"
    UNRESOLVED = "unresolved"


class BoundaryEdge(StrEnum):
    BETWEEN_FRAGMENTS = "between_fragments"
    START_OF_DOCUMENT = "start_of_document"
    END_OF_DOCUMENT = "end_of_document"


class LogicalGroupType(StrEnum):
    FRONT_MATTER = "front_matter"
    BACK_MATTER = "back_matter"
    PART = "part"
    CHAPTER = "chapter"
    SECTION = "section"
    SUBSECTION = "subsection"


class FigurePlacementRelation(StrEnum):
    BEFORE = "before"
    AFTER = "after"
    BETWEEN = "between"
    INLINE_FLOW = "inline_flow"
    UNRESOLVED = "unresolved"


class CaptionAssociationStatus(StrEnum):
    ASSOCIATED = "associated"
    UNRESOLVED = "unresolved"


class CaptionLogicalPosition(StrEnum):
    BEFORE_FIGURE = "before_figure"
    AFTER_FIGURE = "after_figure"
    UNRESOLVED = "unresolved"


class InclusionType(StrEnum):
    INCLUDE = "include"
    EXCLUDE = "exclude"
    UNRESOLVED = "unresolved"


class FlowReasonCode(StrEnum):
    ADJACENT_PARAGRAPHS = "adjacent_paragraphs"
    SOURCE_PAGE_CONTINUATION = "source_page_continuation"
    TRAILING_HYPHEN = "trailing_hyphen"
    LOWERCASE_CONTINUATION = "lowercase_continuation"
    CHAPTER_SEMANTIC_SIGNAL = "chapter_semantic_signal"
    PART_SEMANTIC_SIGNAL = "part_semantic_signal"
    SECTION_SEMANTIC_SIGNAL = "section_semantic_signal"
    FIGURE_CONTEXT = "figure_context"
    CAPTION_CONTEXT = "caption_context"
    REPEATED_ARTIFACT = "repeated_artifact"
    TABLE_CONTINUATION_SIGNAL = "table_continuation_signal"
    LIST_CONTINUATION_SIGNAL = "list_continuation_signal"
    PRINT_ARTIFACT = "print_artifact"
    LAYOUT_ONLY = "layout_only"
    HUMAN_OVERRIDE = "human_override"


class ResolverKind(StrEnum):
    DETERMINISTIC = "deterministic"
    LOCAL_MODEL = "local_model"
    CLOUD_ADAPTER = "cloud_adapter"
    HUMAN_REVIEW = "human_review"


class ResolverIdentity(FrozenContractModel):
    name: str = Field(min_length=1)
    kind: ResolverKind
    version: str = Field(min_length=1)
    model_identifier: str | None = None


class FlowDecisionProvenance(FrozenContractModel):
    document_id: DocumentId
    resolver: ResolverIdentity
    configuration_fingerprint: Fingerprint
    input_fingerprint: Fingerprint
    semantic_taxonomy_version: str = Field(min_length=1)
    flow_policy_version: str = Field(min_length=1)
    classification_result_ids: tuple[ClassificationId, ...] = ()
    created_at: datetime


class FlowDecisionAudit(FrozenContractModel):
    decision_id: FlowDecisionId
    confidence: float = Field(ge=0, le=1)
    review_status: ReviewStatus
    reason_codes: tuple[FlowReasonCode, ...] = ()
    provenance: FlowDecisionProvenance

    @field_validator("decision_id")
    @classmethod
    def stable_decision_id(cls, value: FlowDecisionId) -> FlowDecisionId:
        validate_stable_id(str(value))
        return value

    @model_validator(mode="after")
    def unique_reason_codes(self) -> "FlowDecisionAudit":
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("flow reason codes must be unique")
        return self


class ContinuityCandidate(FrozenContractModel):
    continuity: ContinuityType
    confidence: float = Field(ge=0, le=1)


class LogicalBoundaryDecision(FrozenContractModel):
    audit: FlowDecisionAudit
    edge: BoundaryEdge
    preceding_fragment_id: FragmentId | None = None
    following_fragment_id: FragmentId | None = None
    source_references: tuple[SourceTextReference, ...] = ()
    source_evidence_ids: tuple[SourceId, ...] = ()
    continuity: ContinuityType
    structural_boundary: StructuralBoundaryType = StructuralBoundaryType.NONE
    break_intent: LogicalBreakIntent = LogicalBreakIntent.NONE
    continuity_candidates: tuple[ContinuityCandidate, ...] = ()

    @model_validator(mode="after")
    def valid_edge_and_continuity(self) -> "LogicalBoundaryDecision":
        if self.edge is BoundaryEdge.BETWEEN_FRAGMENTS:
            if self.preceding_fragment_id is None or self.following_fragment_id is None:
                raise ValueError("a between-fragments boundary requires both fragment references")
            if self.preceding_fragment_id == self.following_fragment_id:
                raise ValueError("a boundary must reference two distinct fragments")
        elif self.edge is BoundaryEdge.START_OF_DOCUMENT:
            if self.preceding_fragment_id is not None or self.following_fragment_id is None:
                raise ValueError("start-of-document requires only a following fragment")
        elif self.following_fragment_id is not None or self.preceding_fragment_id is None:
            raise ValueError("end-of-document requires only a preceding fragment")

        joining = {
            ContinuityType.JOIN_DIRECT,
            ContinuityType.JOIN_WITH_SPACE,
            ContinuityType.JOIN_WITH_NEWLINE,
            ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
            ContinuityType.CONTINUE_LIST,
            ContinuityType.CONTINUE_TABLE,
        }
        if self.continuity in joining and self.edge is not BoundaryEdge.BETWEEN_FRAGMENTS:
            raise ValueError("continuity joins require a between-fragments boundary")
        text_joins = joining - {ContinuityType.CONTINUE_TABLE}
        if self.continuity in text_joins and len(self.source_references) < 2:
            raise ValueError("text/list continuity requires source references from both sides")
        if self.continuity is ContinuityType.CONTINUE_TABLE and len(self.source_evidence_ids) < 2:
            raise ValueError("table continuity requires source evidence IDs from both sides")
        candidate_types = [candidate.continuity for candidate in self.continuity_candidates]
        if len(candidate_types) != len(set(candidate_types)):
            raise ValueError("continuity candidates must be unique")
        if self.continuity in candidate_types:
            raise ValueError("selected continuity must not be repeated as a candidate")
        return self


class LogicalGroup(FrozenContractModel):
    group_id: FlowGroupId
    group_type: LogicalGroupType
    opening_fragment_ids: tuple[FragmentId, ...] = Field(min_length=1)
    member_fragment_ids: tuple[FragmentId, ...] = Field(min_length=1)
    parent_group_id: FlowGroupId | None = None
    boundary_decision_id: FlowDecisionId

    @field_validator("group_id", "parent_group_id")
    @classmethod
    def stable_group_id(cls, value: FlowGroupId | None) -> FlowGroupId | None:
        if value is not None:
            validate_stable_id(str(value))
        return value

    @field_validator("boundary_decision_id")
    @classmethod
    def stable_group_boundary_id(cls, value: FlowDecisionId) -> FlowDecisionId:
        validate_stable_id(str(value))
        return value

    @model_validator(mode="after")
    def opening_fragments_are_members(self) -> "LogicalGroup":
        if not set(self.opening_fragment_ids).issubset(self.member_fragment_ids):
            raise ValueError("group opening fragments must also be group members")
        if len(self.member_fragment_ids) != len(set(self.member_fragment_ids)):
            raise ValueError("group members must be unique")
        expected_prefix = f"flow_{self.group_type.value}_"
        if not str(self.group_id).startswith(expected_prefix):
            raise ValueError("logical group ID kind must match group type")
        if self.parent_group_id == self.group_id:
            raise ValueError("a logical group cannot parent itself")
        return self


class FigurePlacement(FrozenContractModel):
    audit: FlowDecisionAudit
    figure_fragment_id: FragmentId
    relation: FigurePlacementRelation
    previous_fragment_id: FragmentId | None = None
    next_fragment_id: FragmentId | None = None
    source_anchor_evidence_ids: tuple[SourceId, ...] = ()

    @model_validator(mode="after")
    def valid_logical_anchors(self) -> "FigurePlacement":
        if self.relation is FigurePlacementRelation.BETWEEN:
            if self.previous_fragment_id is None or self.next_fragment_id is None:
                raise ValueError("BETWEEN placement requires previous and next fragments")
        elif self.relation in {
            FigurePlacementRelation.BEFORE,
            FigurePlacementRelation.AFTER,
            FigurePlacementRelation.INLINE_FLOW,
        } and self.previous_fragment_id is None and self.next_fragment_id is None:
            raise ValueError("resolved figure placement requires a logical fragment anchor")
        return self


class CaptionAssociation(FrozenContractModel):
    audit: FlowDecisionAudit
    caption_fragment_id: FragmentId
    status: CaptionAssociationStatus
    figure_fragment_id: FragmentId | None = None
    candidate_figure_fragment_ids: tuple[FragmentId, ...] = ()
    logical_position: CaptionLogicalPosition = CaptionLogicalPosition.UNRESOLVED

    @model_validator(mode="after")
    def valid_association(self) -> "CaptionAssociation":
        if self.status is CaptionAssociationStatus.ASSOCIATED and self.figure_fragment_id is None:
            raise ValueError("an associated caption requires exactly one figure")
        if self.status is CaptionAssociationStatus.UNRESOLVED and self.figure_fragment_id is not None:
            raise ValueError("an unresolved caption cannot claim a final figure")
        if len(self.candidate_figure_fragment_ids) != len(set(self.candidate_figure_fragment_ids)):
            raise ValueError("candidate figure IDs must be unique")
        return self


class InclusionDecision(FrozenContractModel):
    audit: FlowDecisionAudit
    target_fragment_id: FragmentId
    inclusion: InclusionType


class FlowDecisionReview(FrozenContractModel):
    review_id: FlowReviewId
    original_decision_id: FlowDecisionId
    status: Literal[ReviewStatus.REVIEWED_ACCEPTED, ReviewStatus.REVIEWED_OVERRIDDEN]
    accepted_decision_id: FlowDecisionId
    reviewer: ResolverIdentity
    review_fingerprint: Fingerprint
    created_at: datetime

    @field_validator("review_id", "original_decision_id", "accepted_decision_id")
    @classmethod
    def stable_review_ids(
        cls, value: FlowReviewId | FlowDecisionId
    ) -> FlowReviewId | FlowDecisionId:
        validate_stable_id(str(value))
        return value

    @model_validator(mode="after")
    def valid_review_link(self) -> "FlowDecisionReview":
        same = self.original_decision_id == self.accepted_decision_id
        if self.status is ReviewStatus.REVIEWED_ACCEPTED and not same:
            raise ValueError("accepted review must retain the original decision")
        if self.status is ReviewStatus.REVIEWED_OVERRIDDEN and same:
            raise ValueError("overridden review must reference a replacement decision")
        return self


class ResolvedFlowProvenance(FrozenContractModel):
    document_id: DocumentId
    resolver: ResolverIdentity
    configuration_fingerprint: Fingerprint
    input_fingerprint: Fingerprint
    semantic_taxonomy_version: str = Field(min_length=1)
    flow_policy_version: str = Field(min_length=1)
    created_at: datetime


class ResolvedContentFlow(FrozenContractModel):
    revision: str = Field(min_length=1)
    source_fragment_ids: tuple[FragmentId, ...] = Field(min_length=1)
    ordered_fragment_ids: tuple[FragmentId, ...]
    boundaries: tuple[LogicalBoundaryDecision, ...] = ()
    groups: tuple[LogicalGroup, ...] = ()
    figure_placements: tuple[FigurePlacement, ...] = ()
    caption_associations: tuple[CaptionAssociation, ...] = ()
    inclusion_decisions: tuple[InclusionDecision, ...] = ()
    decision_reviews: tuple[FlowDecisionReview, ...] = ()
    unresolved_decision_ids: tuple[FlowDecisionId, ...] = ()
    provenance: ResolvedFlowProvenance

    @model_validator(mode="after")
    def validate_referential_integrity(self) -> "ResolvedContentFlow":
        source_ids = set(self.source_fragment_ids)
        if len(source_ids) != len(self.source_fragment_ids):
            raise ValueError("source fragment IDs must be unique")
        if len(self.ordered_fragment_ids) != len(set(self.ordered_fragment_ids)):
            raise ValueError("logical flow order must not repeat fragments")
        if not set(self.ordered_fragment_ids).issubset(source_ids):
            raise ValueError("logical flow order references unknown source fragments")

        decision_ids: list[FlowDecisionId] = []
        referenced_fragments: set[FragmentId] = set()
        for boundary in self.boundaries:
            decision_ids.append(boundary.audit.decision_id)
            if boundary.preceding_fragment_id is not None:
                referenced_fragments.add(boundary.preceding_fragment_id)
            if boundary.following_fragment_id is not None:
                referenced_fragments.add(boundary.following_fragment_id)
        for placement in self.figure_placements:
            decision_ids.append(placement.audit.decision_id)
            referenced_fragments.add(placement.figure_fragment_id)
            if placement.previous_fragment_id is not None:
                referenced_fragments.add(placement.previous_fragment_id)
            if placement.next_fragment_id is not None:
                referenced_fragments.add(placement.next_fragment_id)
        associated_captions: set[FragmentId] = set()
        for association in self.caption_associations:
            decision_ids.append(association.audit.decision_id)
            if association.caption_fragment_id in associated_captions:
                raise ValueError("a caption may have only one final association decision")
            associated_captions.add(association.caption_fragment_id)
            referenced_fragments.add(association.caption_fragment_id)
            if association.figure_fragment_id is not None:
                referenced_fragments.add(association.figure_fragment_id)
            referenced_fragments.update(association.candidate_figure_fragment_ids)
        included_targets: set[FragmentId] = set()
        for inclusion in self.inclusion_decisions:
            decision_ids.append(inclusion.audit.decision_id)
            if inclusion.target_fragment_id in included_targets:
                raise ValueError("a fragment may have only one inclusion decision")
            included_targets.add(inclusion.target_fragment_id)
            referenced_fragments.add(inclusion.target_fragment_id)
        if not referenced_fragments.issubset(source_ids):
            raise ValueError("flow decisions reference unknown semantic fragments")
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("flow decision IDs must be unique")
        actual_decision_ids = set(decision_ids)
        group_ids = {group.group_id for group in self.groups}
        if len(group_ids) != len(self.groups):
            raise ValueError("logical group IDs must be unique")
        for group in self.groups:
            referenced_fragments.update(group.member_fragment_ids)
            if group.boundary_decision_id not in actual_decision_ids:
                raise ValueError("logical group references an unknown boundary decision")
            if group.parent_group_id is not None and group.parent_group_id not in group_ids:
                raise ValueError("logical group references an unknown parent group")
        if not referenced_fragments.issubset(source_ids):
            raise ValueError("logical groups reference unknown semantic fragments")

        ordered_positions = {
            fragment_id: index for index, fragment_id in enumerate(self.ordered_fragment_ids)
        }
        for inclusion in self.inclusion_decisions:
            present = inclusion.target_fragment_id in ordered_positions
            if inclusion.inclusion is InclusionType.EXCLUDE and present:
                raise ValueError("excluded fragments must not appear in final logical order")
            if inclusion.inclusion is InclusionType.INCLUDE and not present:
                raise ValueError("included fragments must appear in final logical order")
        for placement in self.figure_placements:
            if placement.relation is FigurePlacementRelation.UNRESOLVED:
                continue
            if placement.figure_fragment_id not in ordered_positions:
                raise ValueError("resolved figures must appear in final logical order")
            figure_position = ordered_positions[placement.figure_fragment_id]
            if placement.relation is FigurePlacementRelation.BETWEEN:
                assert placement.previous_fragment_id is not None
                assert placement.next_fragment_id is not None
                if (
                    ordered_positions.get(placement.previous_fragment_id) != figure_position - 1
                    or ordered_positions.get(placement.next_fragment_id) != figure_position + 1
                ):
                    raise ValueError("BETWEEN placement must match final logical order")
            elif placement.relation is FigurePlacementRelation.BEFORE:
                anchor = placement.next_fragment_id or placement.previous_fragment_id
                if anchor is None or ordered_positions.get(anchor) != figure_position + 1:
                    raise ValueError("BEFORE placement must precede its logical anchor")
            elif placement.relation is FigurePlacementRelation.AFTER:
                anchor = placement.previous_fragment_id or placement.next_fragment_id
                if anchor is None or ordered_positions.get(anchor) != figure_position - 1:
                    raise ValueError("AFTER placement must follow its logical anchor")
        for association in self.caption_associations:
            if association.status is CaptionAssociationStatus.UNRESOLVED:
                continue
            assert association.figure_fragment_id is not None
            caption_figure_position = ordered_positions.get(association.figure_fragment_id)
            caption_position = ordered_positions.get(association.caption_fragment_id)
            if caption_figure_position is None or caption_position is None:
                raise ValueError("resolved caption association must appear in logical order")
            if (
                association.logical_position is CaptionLogicalPosition.BEFORE_FIGURE
                and caption_position >= caption_figure_position
            ):
                raise ValueError("caption position contradicts final logical order")
            if (
                association.logical_position is CaptionLogicalPosition.AFTER_FIGURE
                and caption_position <= caption_figure_position
            ):
                raise ValueError("caption position contradicts final logical order")
        if not set(self.unresolved_decision_ids).issubset(set(decision_ids)):
            raise ValueError("unresolved list references unknown flow decisions")
        return self
