from __future__ import annotations

from typing import Protocol, TypeAlias

from bookforge.contracts.classification import ReviewStatus
from bookforge.contracts.flow import (
    CaptionAssociation,
    CaptionAssociationStatus,
    CaptionLogicalPosition,
    ContinuityType,
    FigurePlacement,
    FigurePlacementRelation,
    FlowDecisionAudit,
    FlowReasonCode,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    StructuralBoundaryType,
)
from bookforge.contracts.semantic import SemanticType

from .models import FlowAnalysisView, FlowResolverPolicy, FlowWorkUnitKind

LocalDecision: TypeAlias = (
    LogicalBoundaryDecision | InclusionDecision | FigurePlacement | CaptionAssociation
)


class FlowRule(Protocol):
    rule_id: str
    version: str
    priority: int
    work_unit_kind: FlowWorkUnitKind

    def evaluate(
        self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit
    ) -> LocalDecision | None: ...


def _break(configured: bool) -> LogicalBreakIntent:
    return LogicalBreakIntent.NEW_PAGE if configured else LogicalBreakIntent.NONE


class StructuralBoundaryRule:
    rule_id = "structural-boundary"
    version = "1"
    priority = 100
    work_unit_kind = FlowWorkUnitKind.BOUNDARY

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        left, right = view.target_fragments
        mapping = {
            SemanticType.PART_TITLE: (
                StructuralBoundaryType.PART,
                _break(policy.part_break_new_page),
                FlowReasonCode.PART_SEMANTIC_SIGNAL,
            ),
            SemanticType.CHAPTER_HEADING: (
                StructuralBoundaryType.CHAPTER,
                _break(policy.chapter_break_new_page),
                FlowReasonCode.CHAPTER_SEMANTIC_SIGNAL,
            ),
            SemanticType.CHAPTER_NUMBER: (
                StructuralBoundaryType.CHAPTER,
                _break(policy.chapter_break_new_page),
                FlowReasonCode.CHAPTER_SEMANTIC_SIGNAL,
            ),
            SemanticType.SECTION_HEADING: (
                StructuralBoundaryType.SECTION,
                _break(policy.section_break_new_page),
                FlowReasonCode.SECTION_SEMANTIC_SIGNAL,
            ),
            SemanticType.SUBSECTION_HEADING: (
                StructuralBoundaryType.SUBSECTION,
                _break(policy.subsection_break_new_page),
                FlowReasonCode.SECTION_SEMANTIC_SIGNAL,
            ),
        }
        resolved = mapping.get(right.semantic_type)
        if resolved is None and right.semantic_type is SemanticType.CHAPTER_TITLE and left.semantic_type not in {
            SemanticType.CHAPTER_HEADING,
            SemanticType.CHAPTER_NUMBER,
        }:
            resolved = (
                StructuralBoundaryType.CHAPTER,
                _break(policy.chapter_break_new_page),
                FlowReasonCode.CHAPTER_SEMANTIC_SIGNAL,
            )
        if resolved is None:
            return None
        structural, break_intent, reason = resolved
        return LogicalBoundaryDecision(
            audit=audit.model_copy(update={"reason_codes": (reason,)}),
            edge="between_fragments",
            preceding_fragment_id=left.id,
            following_fragment_id=right.id,
            continuity=ContinuityType.KEEP_SEPARATE,
            structural_boundary=structural,
            break_intent=break_intent,
        )


class ExplicitContinuationRule:
    rule_id = "explicit-continuation"
    version = "1"
    priority = 80
    work_unit_kind = FlowWorkUnitKind.BOUNDARY

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        del policy
        left, right = view.target_fragments
        left_features, right_features = view.source_features
        explicit = (
            right_features.source_boundary_before
            and left_features.continuation_group_id is not None
            and left_features.continuation_group_id == right_features.continuation_group_id
        )
        if not explicit:
            return None
        if left.semantic_type is SemanticType.TABLE and right.semantic_type is SemanticType.TABLE:
            return LogicalBoundaryDecision(
                audit=audit.model_copy(update={"reason_codes": (FlowReasonCode.TABLE_CONTINUATION_SIGNAL,)}),
                edge="between_fragments",
                preceding_fragment_id=left.id,
                following_fragment_id=right.id,
                source_evidence_ids=tuple((*left.provenance.source_ids, *right.provenance.source_ids)),
                continuity=ContinuityType.CONTINUE_TABLE,
            )
        if left.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM} and right.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}:
            return LogicalBoundaryDecision(
                audit=audit.model_copy(update={"reason_codes": (FlowReasonCode.LIST_CONTINUATION_SIGNAL,)}),
                edge="between_fragments",
                preceding_fragment_id=left.id,
                following_fragment_id=right.id,
                source_references=tuple((*left.source_references, *right.source_references)),
                continuity=ContinuityType.CONTINUE_LIST,
            )
        if left.semantic_type is SemanticType.PARAGRAPH and right.semantic_type is SemanticType.PARAGRAPH:
            left_text = view.target_texts[0]
            continuity = (
                ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN
                if left_text is not None and left_text.endswith(("-", "\u00ad"))
                else ContinuityType.JOIN_WITH_SPACE
            )
            reasons = [FlowReasonCode.SOURCE_PAGE_CONTINUATION]
            if continuity is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN:
                reasons.append(FlowReasonCode.TRAILING_HYPHEN)
            return LogicalBoundaryDecision(
                audit=audit.model_copy(update={"reason_codes": tuple(reasons)}),
                edge="between_fragments",
                preceding_fragment_id=left.id,
                following_fragment_id=right.id,
                source_references=tuple((*left.source_references, *right.source_references)),
                continuity=continuity,
                break_intent=LogicalBreakIntent.NONE,
            )
        return None


class KnownSeparationRule:
    rule_id = "known-separation"
    version = "1"
    priority = 40
    work_unit_kind = FlowWorkUnitKind.BOUNDARY

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        del policy
        left, right = view.target_fragments
        if left.semantic_type is SemanticType.UNKNOWN or right.semantic_type is SemanticType.UNKNOWN:
            return None
        if left.semantic_type is not SemanticType.PARAGRAPH or right.semantic_type is not SemanticType.PARAGRAPH:
            return LogicalBoundaryDecision(
                audit=audit,
                edge="between_fragments",
                preceding_fragment_id=left.id,
                following_fragment_id=right.id,
                continuity=ContinuityType.KEEP_SEPARATE,
            )
        return None


class UnresolvedBoundaryRule:
    rule_id = "unresolved-boundary"
    version = "1"
    priority = 0
    work_unit_kind = FlowWorkUnitKind.BOUNDARY

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        del policy
        left, right = view.target_fragments
        return LogicalBoundaryDecision(
            audit=audit.model_copy(update={"confidence": 0.0, "review_status": ReviewStatus.NEEDS_REVIEW}),
            edge="between_fragments",
            preceding_fragment_id=left.id,
            following_fragment_id=right.id,
            continuity=ContinuityType.UNRESOLVED,
        )


class InclusionRule:
    rule_id = "accepted-semantic-inclusion"
    version = "1"
    priority = 100
    work_unit_kind = FlowWorkUnitKind.INCLUSION

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        fragment = view.target_fragments[0]
        exclusions = {
            SemanticType.RUNNING_HEADER: policy.exclude_running_headers,
            SemanticType.RUNNING_FOOTER: policy.exclude_running_footers,
            SemanticType.PAGE_NUMBER: policy.exclude_page_numbers,
            SemanticType.DECORATIVE: policy.exclude_decorative,
        }
        if fragment.semantic_type in exclusions and exclusions[fragment.semantic_type]:
            return InclusionDecision(
                audit=audit.model_copy(update={"reason_codes": (FlowReasonCode.PRINT_ARTIFACT,)}),
                target_fragment_id=fragment.id,
                inclusion=InclusionType.EXCLUDE,
            )
        if fragment.semantic_type is SemanticType.UNKNOWN:
            return InclusionDecision(
                audit=audit.model_copy(update={"confidence": 0.0, "review_status": ReviewStatus.NEEDS_REVIEW}),
                target_fragment_id=fragment.id,
                inclusion=InclusionType.UNRESOLVED,
            )
        return InclusionDecision(audit=audit, target_fragment_id=fragment.id, inclusion=InclusionType.INCLUDE)


class FigurePlacementRule:
    rule_id = "explicit-sequence-figure-placement"
    version = "1"
    priority = 100
    work_unit_kind = FlowWorkUnitKind.FIGURE_PLACEMENT

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        del policy
        fragment = view.target_fragments[0]
        feature = view.source_features[0]
        before = view.work_unit.context_before_fragment_ids
        after = view.work_unit.context_after_fragment_ids
        if not feature.logical_sequence_explicit:
            return FigurePlacement(
                audit=audit.model_copy(update={"confidence": 0.0, "review_status": ReviewStatus.NEEDS_REVIEW}),
                figure_fragment_id=fragment.id,
                relation=FigurePlacementRelation.UNRESOLVED,
                source_anchor_evidence_ids=feature.source_anchor_evidence_ids,
            )
        previous = before[-1] if before else None
        following = after[0] if after else None
        if previous is not None and following is not None:
            relation = FigurePlacementRelation.BETWEEN
        elif previous is not None:
            relation = FigurePlacementRelation.AFTER
        elif following is not None:
            relation = FigurePlacementRelation.BEFORE
        else:
            relation = FigurePlacementRelation.UNRESOLVED
        return FigurePlacement(
            audit=audit,
            figure_fragment_id=fragment.id,
            relation=relation,
            previous_fragment_id=previous,
            next_fragment_id=following,
            source_anchor_evidence_ids=feature.source_anchor_evidence_ids,
        )


class CaptionAssociationRule:
    rule_id = "unambiguous-adjacent-caption"
    version = "1"
    priority = 100
    work_unit_kind = FlowWorkUnitKind.CAPTION_ASSOCIATION

    def evaluate(self, view: FlowAnalysisView, policy: FlowResolverPolicy, audit: FlowDecisionAudit) -> LocalDecision | None:
        del policy
        caption = view.target_fragments[0]
        before_ids = view.work_unit.context_before_fragment_ids
        after_ids = view.work_unit.context_after_fragment_ids
        before_types = view.context_before_types
        after_types = view.context_after_types
        candidate_ids = tuple(
            fragment_id
            for fragment_id, semantic_type in (*zip(before_ids, before_types), *zip(after_ids, after_types))
            if semantic_type is SemanticType.FIGURE
        )
        immediate_before = before_ids[-1] if before_types and before_types[-1] is SemanticType.FIGURE else None
        immediate_after = after_ids[0] if after_types and after_types[0] is SemanticType.FIGURE else None
        adjacent = tuple(value for value in (immediate_before, immediate_after) if value is not None)
        if len(candidate_ids) == 1 and len(adjacent) == 1:
            figure_id = adjacent[0]
            return CaptionAssociation(
                audit=audit.model_copy(update={"reason_codes": (FlowReasonCode.CAPTION_CONTEXT,)}),
                caption_fragment_id=caption.id,
                status=CaptionAssociationStatus.ASSOCIATED,
                figure_fragment_id=figure_id,
                logical_position=CaptionLogicalPosition.AFTER_FIGURE
                if immediate_before is not None
                else CaptionLogicalPosition.BEFORE_FIGURE,
            )
        return CaptionAssociation(
            audit=audit.model_copy(update={"confidence": 0.0, "review_status": ReviewStatus.NEEDS_REVIEW}),
            caption_fragment_id=caption.id,
            status=CaptionAssociationStatus.UNRESOLVED,
            candidate_figure_fragment_ids=candidate_ids,
        )


DEFAULT_RULES: tuple[FlowRule, ...] = (
    StructuralBoundaryRule(),
    ExplicitContinuationRule(),
    KnownSeparationRule(),
    UnresolvedBoundaryRule(),
    InclusionRule(),
    FigurePlacementRule(),
    CaptionAssociationRule(),
)
