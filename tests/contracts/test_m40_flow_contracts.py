from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from bookforge.contracts.classification import ReviewStatus
from bookforge.contracts.common import DocumentId, ProcessingProvenance, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.flow import (
    BoundaryEdge,
    CaptionAssociation,
    CaptionAssociationStatus,
    CaptionLogicalPosition,
    ContinuityCandidate,
    ContinuityType,
    FigurePlacement,
    FigurePlacementRelation,
    FlowDecisionAudit,
    FlowDecisionProvenance,
    FlowDecisionReview,
    FlowReasonCode,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    LogicalGroup,
    LogicalGroupType,
    ResolvedContentFlow,
    ResolvedFlowProvenance,
    ResolverIdentity,
    ResolverKind,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import (
    flow_decision_id,
    flow_decision_review_id,
    flow_group_id,
)
from bookforge.contracts.raw import RawImage, RawParagraph, RawTable
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
DOC_ID = DocumentId("doc_aaaaaaaaaaaaaaaa")
FP_A = "a" * 64
FP_B = "b" * 64
POLICY = "flow-policy-v1"


def resolver() -> ResolverIdentity:
    return ResolverIdentity(
        name="bookforge.test_resolver",
        kind=ResolverKind.DETERMINISTIC,
        version="1",
    )


def decision_id(kind: str, fragments: tuple[str, ...]) -> str:
    return flow_decision_id(
        decision_kind=kind,
        fragment_ids=fragments,
        input_fingerprint=FP_A,
        configuration_fingerprint=FP_B,
        policy_version=POLICY,
    )


def audit(
    kind: str,
    fragments: tuple[str, ...],
    *,
    confidence: float = 0.9,
    review_status: ReviewStatus = ReviewStatus.NOT_REQUIRED,
    reasons: tuple[FlowReasonCode, ...] = (),
) -> FlowDecisionAudit:
    return FlowDecisionAudit(
        decision_id=decision_id(kind, fragments),
        confidence=confidence,
        review_status=review_status,
        reason_codes=reasons,
        provenance=FlowDecisionProvenance(
            document_id=DOC_ID,
            resolver=resolver(),
            configuration_fingerprint=FP_B,
            input_fingerprint=FP_A,
            semantic_taxonomy_version="bookforge-semantic-v1",
            flow_policy_version=POLICY,
            created_at=EPOCH,
        ),
    )


def raw_paragraph(index: int, text: str, *, page_number: int | None = None) -> RawParagraph:
    return RawParagraph(
        id=f"docx_p{index:06d}",
        document_id=DOC_ID,
        order=index,
        page_number=page_number,
        text=text,
    )


def fragment(index: int, raw: RawParagraph, kind: SemanticType) -> SemanticFragment:
    return SemanticFragment(
        id=f"sem_f{index:06d}",
        semantic_type=kind,
        source_references=[SourceTextReference(source_id=raw.id)],
        provenance=ProcessingProvenance(
            document_id=DOC_ID,
            source_ids=[raw.id],
            stage=TransformationStage.SEMANTIC,
            processor="test",
            processor_version="1",
            created_at=EPOCH,
        ),
    )


def flow_provenance() -> ResolvedFlowProvenance:
    return ResolvedFlowProvenance(
        document_id=DOC_ID,
        resolver=resolver(),
        configuration_fingerprint=FP_B,
        input_fingerprint=FP_A,
        semantic_taxonomy_version="bookforge-semantic-v1",
        flow_policy_version=POLICY,
        created_at=EPOCH,
    )


def test_paragraph_join_is_source_referenced_round_trip_without_joined_text() -> None:
    raw_a = raw_paragraph(1, "The organization developed a compre-")
    raw_b = raw_paragraph(2, "hensive strategy.")
    sem_a = fragment(1, raw_a, SemanticType.PARAGRAPH)
    sem_b = fragment(2, raw_b, SemanticType.PARAGRAPH)
    before_raw = (raw_a.model_dump_json(), raw_b.model_dump_json())
    before_semantic = (sem_a.model_dump_json(), sem_b.model_dump_json())

    operation = LogicalBoundaryDecision(
        audit=audit(
            "paragraph_join",
            (str(sem_a.id), str(sem_b.id)),
            reasons=(FlowReasonCode.TRAILING_HYPHEN,),
        ),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id=sem_a.id,
        following_fragment_id=sem_b.id,
        source_references=(raw_a_ref := sem_a.source_references[0], sem_b.source_references[0]),
        continuity=ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
    )

    restored = LogicalBoundaryDecision.model_validate_json(operation.model_dump_json())
    assert restored == operation
    assert operation.source_references[0] == raw_a_ref
    assert "text" not in LogicalBoundaryDecision.model_fields
    assert "join_result_text" not in operation.model_dump_json()
    assert before_raw == (raw_a.model_dump_json(), raw_b.model_dump_json())
    assert before_semantic == (sem_a.model_dump_json(), sem_b.model_dump_json())


def test_chapter_boundary_new_page_and_nary_grouping_have_no_renderer_fields() -> None:
    raws = tuple(raw_paragraph(index, f"source {index}") for index in range(1, 5))
    fragments = (
        fragment(1, raws[0], SemanticType.PARAGRAPH),
        fragment(2, raws[1], SemanticType.CHAPTER_HEADING),
        fragment(3, raws[2], SemanticType.CHAPTER_TITLE),
        fragment(4, raws[3], SemanticType.PARAGRAPH),
    )
    boundary = LogicalBoundaryDecision(
        audit=audit("chapter_boundary", ("sem_f000001", "sem_f000002")),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000001",
        following_fragment_id="sem_f000002",
        continuity=ContinuityType.KEEP_SEPARATE,
        structural_boundary=StructuralBoundaryType.CHAPTER,
        break_intent=LogicalBreakIntent.NEW_PAGE,
    )
    group = LogicalGroup(
        group_id=flow_group_id("chapter", 1),
        group_type=LogicalGroupType.CHAPTER,
        opening_fragment_ids=("sem_f000002", "sem_f000003"),
        member_fragment_ids=("sem_f000002", "sem_f000003", "sem_f000004"),
        boundary_decision_id=boundary.audit.decision_id,
    )
    flow = ResolvedContentFlow(
        revision="r1",
        source_fragment_ids=tuple(value.id for value in fragments),
        ordered_fragment_ids=tuple(value.id for value in fragments),
        boundaries=(boundary,),
        groups=(group,),
        provenance=flow_provenance(),
    )
    assert flow.groups[0].opening_fragment_ids == ("sem_f000002", "sem_f000003")
    assert "epub_filename" not in boundary.model_dump_json()
    assert "xhtml" not in boundary.model_dump_json()
    assert "page_number" not in boundary.model_dump_json()


def test_section_boundary_can_explicitly_continue_without_new_page() -> None:
    boundary = LogicalBoundaryDecision(
        audit=audit("section_boundary", ("sem_f000001", "sem_f000002")),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000001",
        following_fragment_id="sem_f000002",
        continuity=ContinuityType.KEEP_SEPARATE,
        structural_boundary=StructuralBoundaryType.SECTION,
        break_intent=LogicalBreakIntent.NONE,
    )
    assert boundary.structural_boundary is StructuralBoundaryType.SECTION
    assert boundary.break_intent is LogicalBreakIntent.NONE


def test_part_boundary_capability_does_not_hardwire_break_policy() -> None:
    common: dict[str, Any] = {
        "audit": audit("part_boundary", ("sem_f000001", "sem_f000002")),
        "edge": BoundaryEdge.BETWEEN_FRAGMENTS,
        "preceding_fragment_id": "sem_f000001",
        "following_fragment_id": "sem_f000002",
        "continuity": ContinuityType.KEEP_SEPARATE,
        "structural_boundary": StructuralBoundaryType.PART,
    }
    assert LogicalBoundaryDecision(**common, break_intent=LogicalBreakIntent.NEW_PAGE)
    assert LogicalBoundaryDecision(**common, break_intent=LogicalBreakIntent.NONE)


def test_figure_placement_is_logical_and_anchor_neutral() -> None:
    raw_a = raw_paragraph(1, "Paragraph A")
    raw_b = raw_paragraph(2, "Paragraph B")
    source_image = RawImage(
        id="docx_img000001",
        document_id=DOC_ID,
        order=1,
        asset_reference="assets/image.png",
        source_metadata={
            "placement": "floating",
            "containing_paragraph_id": raw_a.id,
            "x": 123,
            "y": 456,
        },
    )
    placement = FigurePlacement(
        audit=audit("figure_placement", ("sem_f000001", "sem_f000002", "sem_f000003")),
        figure_fragment_id="sem_f000002",
        relation=FigurePlacementRelation.BETWEEN,
        previous_fragment_id="sem_f000001",
        next_fragment_id="sem_f000003",
        source_anchor_evidence_ids=(source_image.id, raw_a.id),
    )
    changed_anchor = source_image.model_copy(
        update={"source_metadata": {"placement": "inline", "containing_paragraph_id": raw_b.id}}
    )
    assert placement.previous_fragment_id == "sem_f000001"
    assert placement.next_fragment_id == "sem_f000003"
    assert "x" not in FigurePlacement.model_fields
    assert "y" not in FigurePlacement.model_fields
    assert changed_anchor.source_metadata != source_image.source_metadata
    assert placement.relation is FigurePlacementRelation.BETWEEN


def test_caption_association_copies_no_caption_text_and_resolves_source() -> None:
    raw_caption = raw_paragraph(1, "Figure caption")
    caption = fragment(2, raw_caption, SemanticType.CAPTION)
    registry = EvidenceRegistry()
    registry.register(raw_caption)
    association = CaptionAssociation(
        audit=audit("caption_association", ("sem_f000001", "sem_f000002")),
        caption_fragment_id=caption.id,
        status=CaptionAssociationStatus.ASSOCIATED,
        figure_fragment_id="sem_f000001",
        logical_position=CaptionLogicalPosition.AFTER_FIGURE,
    )
    assert registry.resolve_text(caption.source_references[0]) == "Figure caption"
    assert "caption_text" not in association.model_dump_json()
    assert association.figure_fragment_id == "sem_f000001"


def test_table_and_list_continuation_express_operations_without_content() -> None:
    source_table_a = RawTable(
        id="docx_tbl000001", document_id=DOC_ID, order=1, rows=()
    )
    source_table_b = RawTable(
        id="docx_tbl000002", document_id=DOC_ID, order=2, rows=()
    )
    source_tables_before = (source_table_a.model_dump_json(), source_table_b.model_dump_json())
    refs = (
        SourceTextReference(source_id="docx_p000001"),
        SourceTextReference(source_id="docx_p000002"),
    )
    table = LogicalBoundaryDecision(
        audit=audit("table_continuation", ("sem_f000001", "sem_f000002")),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000001",
        following_fragment_id="sem_f000002",
        source_evidence_ids=(source_table_a.id, source_table_b.id),
        continuity=ContinuityType.CONTINUE_TABLE,
    )
    list_decision = LogicalBoundaryDecision(
        audit=audit("list_continuation", ("sem_f000003", "sem_f000004")),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000003",
        following_fragment_id="sem_f000004",
        source_references=refs,
        continuity=ContinuityType.CONTINUE_LIST,
    )
    assert table.continuity is ContinuityType.CONTINUE_TABLE
    assert list_decision.continuity is ContinuityType.CONTINUE_LIST
    assert source_tables_before == (
        source_table_a.model_dump_json(),
        source_table_b.model_dump_json(),
    )
    forbidden = {"rows", "cells", "merged_text", "list_text", "page_break"}
    assert forbidden.isdisjoint(LogicalBoundaryDecision.model_fields)


def test_artifact_exclusion_changes_flow_only_and_preserves_evidence() -> None:
    raw = raw_paragraph(1, "Running footer")
    semantic = fragment(1, raw, SemanticType.RUNNING_FOOTER)
    before = (raw.model_dump_json(), semantic.model_dump_json())
    exclusion = InclusionDecision(
        audit=audit(
            "artifact_exclusion",
            (str(semantic.id),),
            reasons=(FlowReasonCode.PRINT_ARTIFACT,),
        ),
        target_fragment_id=semantic.id,
        inclusion=InclusionType.EXCLUDE,
    )
    flow = ResolvedContentFlow(
        revision="r1",
        source_fragment_ids=(semantic.id,),
        ordered_fragment_ids=(),
        inclusion_decisions=(exclusion,),
        provenance=flow_provenance(),
    )
    assert flow.ordered_fragment_ids == ()
    assert before == (raw.model_dump_json(), semantic.model_dump_json())


def test_unresolved_is_valid_and_distinct_from_runtime_failure() -> None:
    boundary = LogicalBoundaryDecision(
        audit=audit(
            "unresolved_boundary",
            ("sem_f000001", "sem_f000002"),
            review_status=ReviewStatus.NEEDS_REVIEW,
        ),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000001",
        following_fragment_id="sem_f000002",
        continuity=ContinuityType.UNRESOLVED,
        structural_boundary=StructuralBoundaryType.UNRESOLVED,
        break_intent=LogicalBreakIntent.UNRESOLVED,
    )
    placement = FigurePlacement(
        audit=audit(
            "unresolved_figure",
            ("sem_f000003",),
            review_status=ReviewStatus.NEEDS_REVIEW,
        ),
        figure_fragment_id="sem_f000003",
        relation=FigurePlacementRelation.UNRESOLVED,
    )
    assert boundary.continuity is ContinuityType.UNRESOLVED
    assert placement.relation is FigurePlacementRelation.UNRESOLVED
    assert "failed" not in {value.value for value in ContinuityType}
    assert "failed" not in {value.value for value in FigurePlacementRelation}


def test_confidence_candidates_and_review_states_validate() -> None:
    boundary = LogicalBoundaryDecision(
        audit=audit(
            "ambiguous",
            ("sem_f000001", "sem_f000002"),
            confidence=0.55,
            review_status=ReviewStatus.NEEDS_REVIEW,
        ),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id="sem_f000001",
        following_fragment_id="sem_f000002",
        continuity=ContinuityType.KEEP_SEPARATE,
        continuity_candidates=(
            ContinuityCandidate(continuity=ContinuityType.JOIN_WITH_SPACE, confidence=0.41),
        ),
    )
    restored = LogicalBoundaryDecision.model_validate_json(boundary.model_dump_json())
    assert restored.audit.review_status is ReviewStatus.NEEDS_REVIEW
    with pytest.raises(ValidationError):
        audit("bad", ("sem_f000001",), confidence=1.01)
    with pytest.raises(ValidationError, match="selected continuity"):
        LogicalBoundaryDecision.model_validate(
            {
                **boundary.model_dump(),
                "continuity_candidates": (
                    ContinuityCandidate(
                        continuity=ContinuityType.KEEP_SEPARATE, confidence=0.2
                    ),
                ),
            }
        )


def test_human_override_links_original_and_replacement_without_erasure() -> None:
    original_id = decision_id("original", ("sem_f000001", "sem_f000002"))
    replacement_id = decision_id("replacement", ("sem_f000001", "sem_f000002"))
    review_fp = "c" * 64
    review = FlowDecisionReview(
        review_id=flow_decision_review_id(
            original_decision_id=original_id,
            accepted_decision_id=replacement_id,
            review_fingerprint=review_fp,
        ),
        original_decision_id=original_id,
        status=ReviewStatus.REVIEWED_OVERRIDDEN,
        accepted_decision_id=replacement_id,
        reviewer=ResolverIdentity(
            name="human-reviewer",
            kind=ResolverKind.HUMAN_REVIEW,
            version="1",
        ),
        review_fingerprint=review_fp,
        created_at=EPOCH,
    )
    assert review.original_decision_id == original_id
    assert review.accepted_decision_id == replacement_id


def test_decision_and_group_ids_are_deterministic_and_output_independent() -> None:
    first = decision_id("boundary_input", ("sem_f000001", "sem_f000002"))
    second = decision_id("boundary_input", ("sem_f000001", "sem_f000002"))
    assert first == second
    changed_input = flow_decision_id(
        decision_kind="boundary_input",
        fragment_ids=("sem_f000001", "sem_f000002"),
        input_fingerprint="d" * 64,
        configuration_fingerprint=FP_B,
        policy_version=POLICY,
    )
    assert changed_input != first
    assert flow_group_id("part", 1) == "flow_part_0001"
    assert flow_group_id("chapter", 3) == "flow_chapter_0003"


def test_source_page_transition_does_not_imply_logical_break() -> None:
    raw_a = raw_paragraph(1, "end of", page_number=10)
    raw_b = raw_paragraph(2, " paragraph", page_number=11)
    sem_a = fragment(1, raw_a, SemanticType.PARAGRAPH)
    sem_b = fragment(2, raw_b, SemanticType.PARAGRAPH)
    boundary = LogicalBoundaryDecision(
        audit=audit(
            "page_continuation",
            (str(sem_a.id), str(sem_b.id)),
            reasons=(FlowReasonCode.SOURCE_PAGE_CONTINUATION,),
        ),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id=sem_a.id,
        following_fragment_id=sem_b.id,
        source_references=(sem_a.source_references[0], sem_b.source_references[0]),
        continuity=ContinuityType.JOIN_WITH_SPACE,
        break_intent=LogicalBreakIntent.NONE,
    )
    assert raw_a.page_number != raw_b.page_number
    assert boundary.break_intent is LogicalBreakIntent.NONE
    assert "page_number" not in LogicalBoundaryDecision.model_fields


def test_resolved_flow_round_trip_with_placement_caption_and_inclusion() -> None:
    fragments = tuple(f"sem_f{index:06d}" for index in range(1, 6))
    boundary = LogicalBoundaryDecision(
        audit=audit("chapter", (fragments[0], fragments[1])),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id=fragments[0],
        following_fragment_id=fragments[1],
        continuity=ContinuityType.KEEP_SEPARATE,
        structural_boundary=StructuralBoundaryType.CHAPTER,
        break_intent=LogicalBreakIntent.NEW_PAGE,
    )
    placement = FigurePlacement(
        audit=audit("figure", (fragments[1], fragments[2], fragments[3])),
        figure_fragment_id=fragments[2],
        relation=FigurePlacementRelation.BETWEEN,
        previous_fragment_id=fragments[1],
        next_fragment_id=fragments[3],
    )
    caption = CaptionAssociation(
        audit=audit("caption", (fragments[2], fragments[3])),
        caption_fragment_id=fragments[3],
        status=CaptionAssociationStatus.ASSOCIATED,
        figure_fragment_id=fragments[2],
        logical_position=CaptionLogicalPosition.AFTER_FIGURE,
    )
    exclusion = InclusionDecision(
        audit=audit("exclude", (fragments[4],)),
        target_fragment_id=fragments[4],
        inclusion=InclusionType.EXCLUDE,
    )
    group = LogicalGroup(
        group_id=flow_group_id("chapter", 1),
        group_type=LogicalGroupType.CHAPTER,
        opening_fragment_ids=(fragments[1],),
        member_fragment_ids=(fragments[1], fragments[2], fragments[3]),
        boundary_decision_id=boundary.audit.decision_id,
    )
    flow = ResolvedContentFlow(
        revision="flow-r1",
        source_fragment_ids=fragments,
        ordered_fragment_ids=fragments[:4],
        boundaries=(boundary,),
        groups=(group,),
        figure_placements=(placement,),
        caption_associations=(caption,),
        inclusion_decisions=(exclusion,),
        provenance=flow_provenance(),
    )
    restored = ResolvedContentFlow.model_validate_json(flow.model_dump_json())
    assert restored == flow
    forbidden = {
        "text",
        "joined_text",
        "xhtml_filename",
        "package_opf",
        "nav_xhtml",
        "x",
        "y",
    }
    assert forbidden.isdisjoint(ResolvedContentFlow.model_fields)
