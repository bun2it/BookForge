from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from bookforge.contracts.classification import (
    ClassificationProvenance,
    ClassificationResult,
    ClassifierIdentity,
    ClassifierKind,
    ReviewStatus,
)
from bookforge.contracts.common import DocumentId, ProcessingProvenance, TransformationStage
from bookforge.contracts.assembly import (
    EvidenceKind, EvidenceReference, FigureDataV3, FigureSemanticNode,
    TableDataV3, TableSemanticNode, UnsupportedContentKind, UnsupportedSemanticNode,
)
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.flow import (
    CaptionAssociationStatus,
    ContinuityType,
    InclusionType,
    FigurePlacement,
    LogicalBreakIntent,
    LogicalGroupType,
    LogicalListKind,
    LogicalListV3,
    StructuralRegion,
    StructuralRegionAssignment,
    StructuralBoundaryType,
    FlowDecisionReview,
    ResolverIdentity,
    ResolverKind,
)
from bookforge.contracts.ids import classification_result_id
from bookforge.contracts.raw import RawParagraph
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference
from bookforge.flow.models import AcceptedFlowReviewInput, FlowResolverInput, FlowResolverPolicy, FlowSourceFeatures
from bookforge.flow.policy import DEFAULT_RULES, FlowRule
from bookforge.flow.resolver import (
    EPOCH,
    DeterministicFlowResolver,
    FlowResolverInterrupted,
    build_flow_analysis_view,
    generate_flow_work_units,
)

DOC_ID = DocumentId("doc_aaaaaaaaaaaaaaaa")
FP = "a" * 64


def make_input(
    types_and_text: list[tuple[SemanticType, str]],
    *,
    features: dict[int, dict[str, Any]] | None = None,
    taxonomy: str = "bookforge-semantic-v1",
) -> tuple[FlowResolverInput, tuple[RawParagraph, ...]]:
    registry = EvidenceRegistry()
    raws: list[RawParagraph] = []
    fragments: list[SemanticFragment] = []
    classifications: dict[str, ClassificationResult] = {}
    source_features: dict[str, FlowSourceFeatures] = {}
    classifier = ClassifierIdentity(
        name="accepted-fixture", kind=ClassifierKind.DETERMINISTIC, version="1"
    )
    for index, (semantic_type, text) in enumerate(types_and_text, 1):
        raw = RawParagraph(
            id=f"docx_p{index:06d}", document_id=DOC_ID, order=index, text=text
        )
        registry.register(raw)
        raws.append(raw)
        fragment = SemanticFragment(
            id=f"sem_f{index:06d}",
            semantic_type=semantic_type,
            source_references=[SourceTextReference(source_id=raw.id)],
            provenance=ProcessingProvenance(
                document_id=DOC_ID,
                source_ids=[raw.id],
                stage=TransformationStage.SEMANTIC,
                processor="accepted-fixture",
                processor_version="1",
                created_at=EPOCH,
            ),
        )
        fragments.append(fragment)
        classification_id = classification_result_id(
            target_source_ids=[str(raw.id)],
            taxonomy_version=taxonomy,
            classifier_name=classifier.name,
            classifier_version=classifier.version,
            configuration_fingerprint=FP,
            input_fingerprint=FP,
            context_fingerprint=FP,
        )
        classifications[fragment.id] = ClassificationResult(
            id=classification_id,
            target_source_ids=(raw.id,),
            source_references=(SourceTextReference(source_id=raw.id),),
            semantic_type=semantic_type,
            confidence=1,
            review_status=ReviewStatus.NOT_REQUIRED,
            classifier=classifier,
            configuration_fingerprint=FP,
            input_fingerprint=FP,
            context_fingerprint=FP,
            taxonomy_version=taxonomy,
            provenance=ClassificationProvenance(
                document_id=DOC_ID, source_ids=(raw.id,), created_at=EPOCH
            ),
        )
        kwargs = (features or {}).get(index, {})
        source_features[fragment.id] = FlowSourceFeatures(source_order=index - 1, **kwargs)
    return (
        FlowResolverInput(
            document_id=DOC_ID,
            ordered_fragments=tuple(fragments),
            accepted_classifications=classifications,
            evidence_registry=registry,
            source_features=source_features,
            semantic_taxonomy_version=taxonomy,
        ),
        tuple(raws),
    )


def test_work_units_preserve_order_have_stable_ids_and_runtime_only_text() -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")]
    )
    units_a = generate_flow_work_units(resolver_input, FlowResolverPolicy())
    units_b = generate_flow_work_units(resolver_input, FlowResolverPolicy())
    assert units_a == units_b
    boundary = units_a[0]
    assert boundary.target_fragment_ids == ("sem_f000001", "sem_f000002")
    view = build_flow_analysis_view(boundary, resolver_input)
    assert view.target_texts == ("A", "B")
    assert "target_texts" not in boundary.model_dump_json()


def test_actual_typed_non_text_nodes_reach_real_m4_without_fake_text(tmp_path: Path) -> None:
    resolver_input, _ = make_input([
        (SemanticType.PARAGRAPH, "before"),
        (SemanticType.FIGURE, "legacy placeholder"),
        (SemanticType.TABLE, "legacy placeholder"),
        (SemanticType.ARTIFACT, "legacy placeholder"),
    ], features={2: {"logical_sequence_explicit": True}, 3: {"source_boundary_before": True, "continuation_group_id": "t"}})
    nodes = list(resolver_input.ordered_fragments)
    nodes[1] = FigureSemanticNode(
        id="sem_f000002",
        evidence=(EvidenceReference(source_id="docx_img000002", kind=EvidenceKind.IMAGE, asset_reference="assets/image2.png"),),
        figure=FigureDataV3(fragment_id="sem_f000002", source_image_id="docx_img000002"),
    )
    nodes[2] = TableSemanticNode(
        id="sem_f000003",
        evidence=(EvidenceReference(source_id="docx_tbl000003", kind=EvidenceKind.TABLE),),
        table=TableDataV3(fragment_id="sem_f000003", source_ids=("docx_tbl000003",), rows=()),
    )
    nodes[3] = UnsupportedSemanticNode(
        id="sem_f000004", content_kind=UnsupportedContentKind.DRAWING,
        evidence=(EvidenceReference(source_id="docx_drw000004", kind=EvidenceKind.DRAWING),),
        reason_code="accepted_artifact",
    )
    typed_input = replace(resolver_input, ordered_fragments=tuple(nodes))
    flow = DeterministicFlowResolver().run(typed_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.source_fragment_ids == tuple(node.id for node in nodes)
    assert flow.figure_placements[0].figure_fragment_id == "sem_f000002"
    assert "source_references" not in nodes[1].model_dump()
    assert "source_references" not in nodes[2].model_dump()


def test_explicit_logical_list_is_carried_and_adjacent_items_do_not_infer_one(tmp_path: Path) -> None:
    resolver_input, _ = make_input([
        (SemanticType.LIST_ITEM, "A"), (SemanticType.LIST_ITEM, "B"), (SemanticType.LIST_ITEM, "C")
    ])
    without_truth = DeterministicFlowResolver().run(resolver_input, tmp_path / "none").resolved_flow
    assert without_truth is not None and without_truth.logical_lists == ()
    accepted = LogicalListV3(
        list_id="list_aaaaaaaaaaaaaaaaaaaa", kind=LogicalListKind.ORDERED,
        member_fragment_ids=("sem_f000001", "sem_f000002", "sem_f000003"), start_value=4,
    )
    with_truth = replace(resolver_input, accepted_logical_lists=(accepted,))
    resolved = DeterministicFlowResolver().run(with_truth, tmp_path / "accepted").resolved_flow
    assert resolved is not None and resolved.logical_lists == (accepted,)


def test_explicit_regions_control_front_body_back_order_and_groups(tmp_path: Path) -> None:
    resolver_input, _ = make_input([
        (SemanticType.PARAGRAPH, "body preface"),
        (SemanticType.CHAPTER_HEADING, "chapter"),
        (SemanticType.BOOK_TITLE, "front"),
        (SemanticType.NOTE, "back"),
    ])
    regions = StructuralRegionAssignment(by_fragment_id={
        "sem_f000001": StructuralRegion.BODY, "sem_f000002": StructuralRegion.BODY,
        "sem_f000003": StructuralRegion.FRONT, "sem_f000004": StructuralRegion.BACK,
    })
    value = replace(resolver_input, structural_regions=regions)
    flow = DeterministicFlowResolver().run(value, tmp_path).resolved_flow
    assert flow is not None
    assert flow.ordered_fragment_ids == ("sem_f000003", "sem_f000001", "sem_f000002", "sem_f000004")
    assert {group.group_type for group in flow.groups} >= {
        LogicalGroupType.FRONT_MATTER, LogicalGroupType.CHAPTER, LogicalGroupType.BACK_MATTER,
    }
    transitions = {item.structural_boundary for item in flow.boundaries}
    assert StructuralBoundaryType.FRONT_MATTER_TRANSITION in transitions
    assert StructuralBoundaryType.BACK_MATTER_TRANSITION in transitions


def test_changed_list_or_region_truth_changes_work_unit_fingerprint() -> None:
    resolver_input, _ = make_input([(SemanticType.LIST_ITEM, "A"), (SemanticType.LIST_ITEM, "B")])
    unordered = LogicalListV3(list_id="list_aaaaaaaaaaaaaaaaaaaa", kind=LogicalListKind.UNORDERED, member_fragment_ids=("sem_f000001", "sem_f000002"))
    ordered = LogicalListV3(list_id="list_aaaaaaaaaaaaaaaaaaaa", kind=LogicalListKind.ORDERED, member_fragment_ids=("sem_f000001", "sem_f000002"))
    a = replace(resolver_input, accepted_logical_lists=(unordered,))
    b = replace(resolver_input, accepted_logical_lists=(ordered,))
    assert generate_flow_work_units(a, FlowResolverPolicy())[0].work_unit_id == generate_flow_work_units(b, FlowResolverPolicy())[0].work_unit_id
    assert generate_flow_work_units(a, FlowResolverPolicy())[0].input_fingerprint != generate_flow_work_units(b, FlowResolverPolicy())[0].input_fingerprint


def test_continue_list_without_list_truth_remains_explicitly_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.LIST_ITEM, "A"), (SemanticType.LIST_ITEM, "B")],
        features={
            1: {"continuation_group_id": "list-a"},
            2: {"source_boundary_before": True, "continuation_group_id": "list-a"},
        },
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None and flow.logical_lists == ()
    boundary = flow.boundaries[0]
    assert boundary.continuity is ContinuityType.CONTINUE_LIST
    assert boundary.audit.decision_id in flow.unresolved_decision_ids


def _accepted_override(original, replacement):
    review = FlowDecisionReview(
        review_id="fdr_aaaaaaaaaaaaaaaaaaaa",
        original_decision_id=original.audit.decision_id,
        status=ReviewStatus.REVIEWED_OVERRIDDEN,
        accepted_decision_id=replacement.audit.decision_id,
        reviewer=ResolverIdentity(name="fixture-reviewer", kind=ResolverKind.HUMAN_REVIEW, version="1"),
        review_fingerprint="b" * 64,
        created_at=EPOCH,
    )
    return AcceptedFlowReviewInput(review=review, replacement_decision=replacement)


def test_accepted_boundary_review_preserves_original_and_clears_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")])
    baseline = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert baseline is not None
    original = baseline.boundaries[0]
    original_json = original.model_dump_json()
    replacement = original.model_copy(update={
        "audit": original.audit.model_copy(update={"decision_id": "fld_bbbbbbbbbbbbbbbbbbbb"}),
        "continuity": ContinuityType.JOIN_DIRECT,
        "source_references": tuple(
            reference for fragment in resolver_input.ordered_fragments
            for reference in fragment.source_references
        ),
    })
    reviewed_input = replace(
        resolver_input, accepted_flow_reviews=(_accepted_override(original, replacement),)
    )
    report = DeterministicFlowResolver().run(reviewed_input, tmp_path)
    flow = report.resolved_flow
    assert flow is not None
    assert flow.boundaries[0].model_dump_json() == original_json
    assert flow.decision_reviews[0].original_decision_id == original.audit.decision_id
    assert report.accepted_replacement_decisions == (replacement,)
    assert original.audit.decision_id not in flow.unresolved_decision_ids
    assert (tmp_path / "flow/reviews/fdr_aaaaaaaaaaaaaaaaaaaa.json").is_file()
    assert (tmp_path / "flow/reviews/replacements/fld_bbbbbbbbbbbbbbbbbbbb.json").is_file()
    persisted_before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in sorted((tmp_path / "flow").rglob("*.json")) if path.name != "manifest.json"
    }
    repeated = DeterministicFlowResolver().run(reviewed_input, tmp_path)
    assert repeated.resolved_flow == flow
    assert repeated.reused == repeated.total_work_units
    assert persisted_before == {
        path.relative_to(tmp_path): path.read_bytes()
        for path in sorted((tmp_path / "flow").rglob("*.json")) if path.name != "manifest.json"
    }


def test_reviewed_inclusion_controls_order_and_wrong_family_is_rejected(tmp_path: Path) -> None:
    resolver_input, _ = make_input([(SemanticType.ARTIFACT, "drawing placeholder")])
    unsupported = UnsupportedSemanticNode(
        id="sem_f000001", content_kind=UnsupportedContentKind.DRAWING,
        evidence=(EvidenceReference(source_id="docx_drw000001", kind=EvidenceKind.DRAWING),),
        reason_code="accepted_artifact",
    )
    typed = replace(resolver_input, ordered_fragments=(unsupported,))
    baseline = DeterministicFlowResolver().run(typed, tmp_path / "base").resolved_flow
    assert baseline is not None
    original = baseline.inclusion_decisions[0]
    replacement = original.model_copy(update={
        "audit": original.audit.model_copy(update={"decision_id": "fld_cccccccccccccccccccc"}),
        "inclusion": InclusionType.EXCLUDE,
    })
    reviewed = replace(typed, accepted_flow_reviews=(_accepted_override(original, replacement),))
    flow = DeterministicFlowResolver().run(reviewed, tmp_path / "excluded").resolved_flow
    assert flow is not None
    assert flow.source_fragment_ids == (unsupported.id,)
    assert flow.ordered_fragment_ids == ()
    boundary_input, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")])
    boundary_flow = DeterministicFlowResolver().run(boundary_input, tmp_path / "boundary").resolved_flow
    assert boundary_flow is not None
    wrong = _accepted_override(boundary_flow.boundaries[0], replacement)
    with pytest.raises(Exception, match="family"):
        DeterministicFlowResolver().run(
            replace(boundary_input, accepted_flow_reviews=(wrong,)), tmp_path / "wrong"
        )


def test_region_transitions_reconcile_existing_edges_without_duplicates(tmp_path: Path) -> None:
    resolver_input, _ = make_input([
        (SemanticType.BOOK_TITLE, "front"),
        (SemanticType.CHAPTER_HEADING, "body"),
        (SemanticType.NOTE, "back"),
    ])
    regions = StructuralRegionAssignment(by_fragment_id={
        "sem_f000001": StructuralRegion.FRONT,
        "sem_f000002": StructuralRegion.BODY,
        "sem_f000003": StructuralRegion.BACK,
    })
    flow = DeterministicFlowResolver().run(
        replace(resolver_input, structural_regions=regions), tmp_path
    ).resolved_flow
    assert flow is not None
    edges = [(item.preceding_fragment_id, item.following_fragment_id) for item in flow.boundaries]
    assert len(edges) == len(set(edges))
    transitions = [item.structural_boundary for item in flow.boundaries]
    assert transitions.count(StructuralBoundaryType.FRONT_MATTER_TRANSITION) == 1
    assert transitions.count(StructuralBoundaryType.BACK_MATTER_TRANSITION) == 1


def test_conflicting_and_stale_accepted_reviews_fail_deterministically(tmp_path: Path) -> None:
    resolver_input, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")])
    baseline = DeterministicFlowResolver().run(resolver_input, tmp_path / "base").resolved_flow
    assert baseline is not None
    original = baseline.boundaries[0]
    refs = tuple(reference for fragment in resolver_input.ordered_fragments for reference in fragment.source_references)
    replacement = original.model_copy(update={
        "audit": original.audit.model_copy(update={"decision_id": "fld_dddddddddddddddddddd"}),
        "continuity": ContinuityType.JOIN_WITH_NEWLINE, "source_references": refs,
    })
    first = _accepted_override(original, replacement)
    second = first.model_copy(update={
        "review": first.review.model_copy(update={"review_id": "fdr_bbbbbbbbbbbbbbbbbbbb"})
    })
    with pytest.raises(Exception, match="conflicting"):
        DeterministicFlowResolver().run(
            replace(resolver_input, accepted_flow_reviews=(first, second)), tmp_path / "conflict"
        )
    stale = replacement.model_copy(update={
        "audit": replacement.audit.model_copy(update={
            "provenance": replacement.audit.provenance.model_copy(update={"input_fingerprint": "c" * 64})
        })
    })
    with pytest.raises(Exception, match="stale"):
        DeterministicFlowResolver().run(
            replace(resolver_input, accepted_flow_reviews=(_accepted_override(original, stale),)),
            tmp_path / "stale",
        )


def test_reviewed_exclusion_cannot_silently_damage_logical_list(tmp_path: Path) -> None:
    resolver_input, _ = make_input([(SemanticType.LIST_ITEM, "A"), (SemanticType.LIST_ITEM, "B")])
    logical_list = LogicalListV3(
        list_id="list_aaaaaaaaaaaaaaaaaaaa", kind=LogicalListKind.UNORDERED,
        member_fragment_ids=("sem_f000001", "sem_f000002"),
    )
    with_list = replace(resolver_input, accepted_logical_lists=(logical_list,))
    baseline = DeterministicFlowResolver().run(with_list, tmp_path / "base").resolved_flow
    assert baseline is not None
    original = baseline.inclusion_decisions[0]
    replacement = original.model_copy(update={
        "audit": original.audit.model_copy(update={"decision_id": "fld_eeeeeeeeeeeeeeeeeeee"}),
        "inclusion": InclusionType.EXCLUDE,
    })
    with pytest.raises(Exception, match="list member"):
        DeterministicFlowResolver().run(
            replace(with_list, accepted_flow_reviews=(_accepted_override(original, replacement),)),
            tmp_path / "excluded",
        )


def test_synthetic_structured_book_rules_groups_order_caption_and_exclusion(tmp_path: Path) -> None:
    sequence = [
        (SemanticType.BOOK_TITLE, "Book"),
        (SemanticType.PART_TITLE, "Part I"),
        (SemanticType.CHAPTER_HEADING, "Chapter 1"),
        (SemanticType.CHAPTER_TITLE, "Opening"),
        (SemanticType.PARAGRAPH, "P1"),
        (SemanticType.PARAGRAPH, "P2"),
        (SemanticType.FIGURE, "figure evidence"),
        (SemanticType.CAPTION, "caption"),
        (SemanticType.PARAGRAPH, "P3"),
        (SemanticType.SECTION_HEADING, "Section"),
        (SemanticType.PARAGRAPH, "P4"),
        (SemanticType.CHAPTER_HEADING, "Chapter 2"),
        (SemanticType.CHAPTER_TITLE, "Second"),
        (SemanticType.PARAGRAPH, "P5"),
        (SemanticType.PART_TITLE, "Part II"),
        (SemanticType.CHAPTER_HEADING, "Chapter 3"),
        (SemanticType.CHAPTER_TITLE, "Third"),
        (SemanticType.PARAGRAPH, "P6"),
        (SemanticType.RUNNING_FOOTER, "footer"),
    ]
    resolver_input, raws = make_input(
        sequence,
        features={7: {"logical_sequence_explicit": True, "image_only_container": True}},
    )
    before = tuple(raw.model_dump_json() for raw in raws)
    report = DeterministicFlowResolver().run(resolver_input, tmp_path)
    flow = report.resolved_flow
    assert flow is not None
    assert report.failed == 0
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.PART) == 2
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.CHAPTER) == 3
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.SECTION) == 1
    chapter_boundaries = [
        value for value in flow.boundaries if value.structural_boundary is StructuralBoundaryType.CHAPTER
    ]
    assert all(value.break_intent is LogicalBreakIntent.NEW_PAGE for value in chapter_boundaries)
    section = next(value for value in flow.boundaries if value.structural_boundary is StructuralBoundaryType.SECTION)
    assert section.break_intent is LogicalBreakIntent.NONE
    assert flow.figure_placements[0].previous_fragment_id == "sem_f000006"
    assert flow.figure_placements[0].next_fragment_id == "sem_f000008"
    assert flow.caption_associations[0].status is CaptionAssociationStatus.ASSOCIATED
    assert flow.caption_associations[0].figure_fragment_id == "sem_f000007"
    footer = next(value for value in flow.inclusion_decisions if value.target_fragment_id == "sem_f000019")
    assert footer.inclusion is InclusionType.EXCLUDE
    assert "sem_f000019" in flow.source_fragment_ids
    assert "sem_f000019" not in flow.ordered_fragment_ids
    assert tuple(raw.model_dump_json() for raw in raws) == before
    assert "epub" not in flow.model_dump_json().lower()
    assert "bookmodel" not in flow.model_dump_json().lower()


@pytest.mark.parametrize(
    ("semantic_type", "expected"),
    [
        (SemanticType.PART_TITLE, StructuralBoundaryType.PART),
        (SemanticType.CHAPTER_HEADING, StructuralBoundaryType.CHAPTER),
        (SemanticType.SECTION_HEADING, StructuralBoundaryType.SECTION),
        (SemanticType.SUBSECTION_HEADING, StructuralBoundaryType.SUBSECTION),
    ],
)
def test_structural_rules_only_consume_accepted_semantics(
    tmp_path: Path, semantic_type: SemanticType, expected: StructuralBoundaryType
) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "before"), (semantic_type, "accepted")]
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    boundary = flow.boundaries[0]
    assert boundary.structural_boundary is expected
    expected_break = (
        LogicalBreakIntent.NEW_PAGE
        if expected in {StructuralBoundaryType.PART, StructuralBoundaryType.CHAPTER}
        else LogicalBreakIntent.NONE
    )
    assert boundary.break_intent is expected_break


def test_break_policy_override_changes_fingerprint_decision_and_cache(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "before"), (SemanticType.CHAPTER_HEADING, "chapter")]
    )
    first = DeterministicFlowResolver().run(resolver_input, tmp_path)
    changed_policy = FlowResolverPolicy(chapter_break_new_page=False, policy_version="flow-v2")
    second = DeterministicFlowResolver(changed_policy).run(resolver_input, tmp_path)
    assert first.resolved_flow is not None and second.resolved_flow is not None
    assert first.resolved_flow.boundaries[0].break_intent is LogicalBreakIntent.NEW_PAGE
    assert second.resolved_flow.boundaries[0].break_intent is LogicalBreakIntent.NONE
    assert second.stale > 0
    assert first.resolved_flow.boundaries[0].audit.decision_id != second.resolved_flow.boundaries[0].audit.decision_id


def test_explicit_trailing_hyphen_and_space_continuations_preserve_evidence(tmp_path: Path) -> None:
    features = {
        1: {"continuation_group_id": "source-paragraph-1", "physical_segment_id": "page-10"},
        2: {"continuation_group_id": "source-paragraph-1", "source_boundary_before": True, "physical_segment_id": "page-11"},
        3: {"continuation_group_id": "source-paragraph-2"},
        4: {"continuation_group_id": "source-paragraph-2", "source_boundary_before": True},
    }
    resolver_input, raws = make_input(
        [
            (SemanticType.PARAGRAPH, "compre-"),
            (SemanticType.PARAGRAPH, "hensive"),
            (SemanticType.PARAGRAPH, "coffee"),
            (SemanticType.PARAGRAPH, "house"),
        ],
        features=features,
    )
    before = tuple(raw.model_dump_json() for raw in raws)
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.boundaries[0].continuity is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN
    assert flow.boundaries[2].continuity is ContinuityType.JOIN_WITH_SPACE
    assert flow.boundaries[0].break_intent is LogicalBreakIntent.NONE
    assert tuple(raw.model_dump_json() for raw in raws) == before
    persisted = "".join(path.read_text() for path in (tmp_path / "flow").rglob("*.json"))
    assert "comprehensive" not in persisted


def test_source_continuation_signal_is_required_for_join(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "compre-"), (SemanticType.PARAGRAPH, "hensive")],
        features={
            1: {"continuation_group_id": "same-source"},
            2: {"continuation_group_id": "same-source", "source_boundary_before": False},
        },
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.boundaries[0].continuity is ContinuityType.UNRESOLVED


def test_ambiguous_paragraphs_are_unresolved_not_language_guessed(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "no punctuation"), (SemanticType.PARAGRAPH, "lowercase")]
    )
    report = DeterministicFlowResolver().run(resolver_input, tmp_path)
    assert report.resolved_flow is not None
    assert report.resolved_flow.boundaries[0].continuity is ContinuityType.UNRESOLVED
    assert report.resolved_flow.boundaries[0].audit.review_status is ReviewStatus.NEEDS_REVIEW
    assert report.failed == 0


def test_figure_anchor_does_not_control_logical_geometry(tmp_path: Path) -> None:
    sequence = [
        (SemanticType.PARAGRAPH, "A"),
        (SemanticType.FIGURE, "figure evidence"),
        (SemanticType.PARAGRAPH, "B"),
    ]
    first_input, _ = make_input(
        sequence,
        features={
            2: {
                "logical_sequence_explicit": True,
                "source_anchor_evidence_ids": ("docx_p000001",),
            }
        },
    )
    second_input, _ = make_input(
        sequence,
        features={
            2: {
                "logical_sequence_explicit": True,
                "source_anchor_evidence_ids": ("docx_p000003",),
            }
        },
    )
    first = DeterministicFlowResolver().run(first_input, tmp_path / "one").resolved_flow
    second = DeterministicFlowResolver().run(second_input, tmp_path / "two").resolved_flow
    assert first is not None and second is not None
    assert first.ordered_fragment_ids == second.ordered_fragment_ids
    assert first.figure_placements[0].previous_fragment_id == second.figure_placements[0].previous_fragment_id
    assert "x" not in FigurePlacement.model_fields


def test_ambiguous_two_figures_one_caption_remains_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [
            (SemanticType.FIGURE, "f1"),
            (SemanticType.FIGURE, "f2"),
            (SemanticType.CAPTION, "caption"),
        ]
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    association = flow.caption_associations[0]
    assert association.status is CaptionAssociationStatus.UNRESOLVED
    assert set(association.candidate_figure_fragment_ids) == {"sem_f000001", "sem_f000002"}


@pytest.mark.parametrize("kind", [SemanticType.TABLE, SemanticType.LIST])
def test_explicit_table_and_list_continuation_only_emit_operations(
    tmp_path: Path, kind: SemanticType
) -> None:
    resolver_input, _ = make_input(
        [(kind, "first"), (kind, "second")],
        features={
            1: {"continuation_group_id": "logical-1"},
            2: {"continuation_group_id": "logical-1", "source_boundary_before": True},
        },
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    expected = ContinuityType.CONTINUE_TABLE if kind is SemanticType.TABLE else ContinuityType.CONTINUE_LIST
    assert flow.boundaries[0].continuity is expected
    serialized = flow.boundaries[0].model_dump_json()
    assert "merged_text" not in serialized
    assert "rows" not in serialized


@pytest.mark.parametrize(
    "kind",
    [SemanticType.RUNNING_HEADER, SemanticType.RUNNING_FOOTER, SemanticType.PAGE_NUMBER, SemanticType.DECORATIVE],
)
def test_explicit_artifact_semantics_are_excluded_but_preserved(
    tmp_path: Path, kind: SemanticType
) -> None:
    resolver_input, raws = make_input([(kind, "evidence")])
    raw_before = raws[0].model_dump_json()
    fragment_before = resolver_input.ordered_fragments[0].model_dump_json()
    classification_before = resolver_input.accepted_classifications["sem_f000001"].model_dump_json()
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.inclusion_decisions[0].inclusion is InclusionType.EXCLUDE
    assert flow.ordered_fragment_ids == ()
    assert flow.source_fragment_ids == ("sem_f000001",)
    assert raws[0].model_dump_json() == raw_before
    assert resolver_input.ordered_fragments[0].model_dump_json() == fragment_before
    assert resolver_input.accepted_classifications["sem_f000001"].model_dump_json() == classification_before


class FailOnceRule:
    rule_id = "fail-once"
    version = "1"
    priority = 1000
    work_unit_kind = DEFAULT_RULES[0].work_unit_kind

    def __init__(self) -> None:
        self.failed = False

    def evaluate(self, view, policy, audit):  # type: ignore[no-untyped-def]
        if view.work_unit.sequence_index == 1 and not self.failed:
            self.failed = True
            raise RuntimeError("safe failure")
        return None


def test_failure_isolation_retry_and_failed_differs_from_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")]
    )
    failing = FailOnceRule()
    resolver = DeterministicFlowResolver(rules=(failing, *DEFAULT_RULES))
    first = resolver.run(resolver_input, tmp_path)
    assert first.failed == 1
    assert first.resolved_flow is None
    assert len(tuple((tmp_path / "flow/failures").glob("*.json"))) == 1
    second = resolver.run(resolver_input, tmp_path)
    assert second.failed == 0
    assert second.resolved_flow is not None
    assert second.unresolved > 0
    assert second.reused == second.total_work_units - 1
    assert not tuple((tmp_path / "flow/failures").glob("*.json"))


@pytest.mark.parametrize("change", ["semantic", "context", "taxonomy", "policy", "resolver", "evidence"])
def test_stale_inputs_are_recomputed(tmp_path: Path, change: str) -> None:
    original, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")]
    )
    DeterministicFlowResolver().run(original, tmp_path)
    changed = original
    policy = FlowResolverPolicy()
    rules: tuple[FlowRule, ...] = DEFAULT_RULES
    if change == "semantic":
        changed, _ = make_input([(SemanticType.QUOTE, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")])
    elif change == "context":
        changed, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.QUOTE, "B"), (SemanticType.PARAGRAPH, "C")])
    elif change == "taxonomy":
        changed, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")], taxonomy="taxonomy-v2")
    elif change == "policy":
        policy = FlowResolverPolicy(policy_version="flow-v2", chapter_break_new_page=False)
    elif change == "resolver":
        rules = (*DEFAULT_RULES, FailOnceRule())
    else:
        changed, _ = make_input([(SemanticType.PARAGRAPH, "changed evidence"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")])
    report = DeterministicFlowResolver(policy, rules).run(changed, tmp_path)
    assert report.stale > 0
    assert report.reused < report.total_work_units


def test_interruption_resume_long_book_and_clean_determinism(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, f"Paragraph {index}") for index in range(1, 1001)]
    )
    interrupted_workspace = tmp_path / "interrupted"
    with pytest.raises(FlowResolverInterrupted):
        DeterministicFlowResolver().run(
            resolver_input, interrupted_workspace, interrupt_after=173
        )
    resumed = DeterministicFlowResolver().run(resolver_input, interrupted_workspace)
    assert resumed.failed == 0
    assert resumed.reused == 173
    assert resumed.total_work_units == 1999
    assert resumed.resolved_flow is not None

    clean_a = tmp_path / "clean_a"
    clean_b = tmp_path / "clean_b"
    flow_a = DeterministicFlowResolver().run(resolver_input, clean_a).resolved_flow
    flow_b = DeterministicFlowResolver().run(resolver_input, clean_b).resolved_flow
    assert flow_a == flow_b == resumed.resolved_flow
    files_a = {path.relative_to(clean_a): path.read_bytes() for path in (clean_a / "flow").rglob("*.json")}
    files_b = {path.relative_to(clean_b): path.read_bytes() for path in (clean_b / "flow").rglob("*.json")}
    assert files_a == files_b
    assert all(b"Paragraph 1" not in data for data in files_a.values())


def test_flow_workspace_does_not_modify_extraction_or_semantic_inputs(tmp_path: Path) -> None:
    immutable_paths = (
        tmp_path / "source.json",
        tmp_path / "raw_document.json",
        tmp_path / "warnings.json",
        tmp_path / "semantic" / "manifest.json",
        tmp_path / "semantic" / "results" / "result.json",
        tmp_path / "semantic" / "fragments" / "fragment.json",
    )
    for index, path in enumerate(immutable_paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"immutable-{index}", encoding="utf-8")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in immutable_paths}
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")]
    )
    DeterministicFlowResolver().run(resolver_input, tmp_path)
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in immutable_paths}
    assert after == before
