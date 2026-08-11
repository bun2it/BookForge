from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from bookforge.contracts.assembly import (
    AcceptedClassificationCatalog,
    AssemblyInput,
    AssemblyProvenance,
    AssemblyReadinessCode,
    BookContentCatalogV3,
    BookMetadataV3,
    BookModelV3,
    ChapterV3,
    EvidenceKind,
    EvidenceReference,
    FigureDataV3,
    FigureSemanticNode,
    LogicalContinuityV3,
    MatterV3,
    TableDataV3,
    TableSemanticNode,
    TextSemanticNode,
    assembly_revision_for_state,
    assess_assembly_readiness,
    materialize_effective_catalog,
    materialize_effective_continuity,
    resolve_effective_classifications,
)
from bookforge.contracts.classification import (
    ClassificationReview,
    ReviewStatus,
)
from bookforge.contracts.flow import (
    BoundaryEdge,
    ContinuityType,
    FlowDecisionAudit,
    FlowDecisionReview,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    ResolvedContentFlow,
    ResolvedFlowProvenance,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import (
    classification_review_id,
    flow_decision_id,
    flow_decision_review_id,
    flow_group_id,
)
from bookforge.contracts.semantic import SemanticType
from bookforge.contracts.common import SourceId

from tests.contracts.test_m45_assembly_contracts import (
    EPOCH,
    HASH,
    accepted_classifications,
    decision_provenance,
    fid,
    provenance,
    resolver,
    sid,
    text_node,
)


def metadata() -> BookMetadataV3:
    return BookMetadataV3(
        title_fragment_id=fid(1), language="vi", identifier="urn:bookforge:test",
        publisher="BookForge", description="Contract fixture",
    )


def boundary(
    left: int,
    right: int,
    operation: ContinuityType,
    *,
    structural: StructuralBoundaryType = StructuralBoundaryType.NONE,
    break_intent: LogicalBreakIntent = LogicalBreakIntent.NONE,
    kind: str = "boundary",
) -> LogicalBoundaryDecision:
    decision_id = flow_decision_id(
        decision_kind=kind, fragment_ids=[str(fid(left)), str(fid(right))],
        input_fingerprint=HASH, configuration_fingerprint=HASH, policy_version="v1",
    )
    source_references = ()
    source_evidence_ids = ()
    if operation in {
        ContinuityType.JOIN_DIRECT, ContinuityType.JOIN_WITH_SPACE,
        ContinuityType.JOIN_WITH_NEWLINE, ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
        ContinuityType.CONTINUE_LIST,
    }:
        source_references = (*text_node(left).source_references, *text_node(right).source_references)
    if operation is ContinuityType.CONTINUE_TABLE:
        source_evidence_ids = (sid(left), sid(right))
    return LogicalBoundaryDecision(
        audit=FlowDecisionAudit(
            decision_id=decision_id, confidence=1, review_status=ReviewStatus.NOT_REQUIRED,
            provenance=decision_provenance(),
        ),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id=fid(left), following_fragment_id=fid(right),
        source_references=source_references, source_evidence_ids=source_evidence_ids,
        continuity=operation, structural_boundary=structural, break_intent=break_intent,
    )


def flow(
    source: tuple[int, ...],
    ordered: tuple[int, ...],
    boundaries: tuple[LogicalBoundaryDecision, ...] = (),
    *,
    reviews: tuple[FlowDecisionReview, ...] = (),
    unresolved: tuple[str, ...] = (),
) -> ResolvedContentFlow:
    return ResolvedContentFlow(
        revision="flow-m46", source_fragment_ids=tuple(fid(item) for item in source),
        ordered_fragment_ids=tuple(fid(item) for item in ordered), boundaries=boundaries,
        decision_reviews=reviews, unresolved_decision_ids=unresolved,
        provenance=ResolvedFlowProvenance(
            document_id="doc_aaaaaaaaaaaaaaaa", resolver=resolver(),
            configuration_fingerprint=HASH, input_fingerprint=HASH,
            semantic_taxonomy_version="bookforge-semantic-v1", flow_policy_version="v1", created_at=EPOCH,
        ),
    )


def input_for(
    catalog: BookContentCatalogV3,
    resolved_flow: ResolvedContentFlow,
    *,
    reviews: tuple[ClassificationReview, ...] = (),
    replacements: tuple[LogicalBoundaryDecision, ...] = (),
    accepted: AcceptedClassificationCatalog | None = None,
) -> AssemblyInput:
    return AssemblyInput(
        metadata=metadata(), semantic_catalog=catalog,
        accepted_classifications=accepted or accepted_classifications(catalog),
        classification_reviews=reviews, resolved_flow=resolved_flow,
        replacement_decisions=replacements,
    )


def classification_review(
    catalog: BookContentCatalogV3,
    fragment: int,
    accepted_type: SemanticType,
    *,
    base_fingerprint: str = HASH,
    taxonomy: str = "bookforge-semantic-v1",
) -> ClassificationReview:
    result = accepted_classifications(catalog).by_fragment_id[fid(fragment)]
    review_fingerprint = "b" * 64
    return ClassificationReview(
        id=classification_review_id(
            classification_id=str(result.id), reviewer_name="reviewer",
            review_fingerprint=review_fingerprint,
        ),
        classification_id=result.id, original_semantic_type=result.semantic_type,
        status=ReviewStatus.REVIEWED_OVERRIDDEN, accepted_semantic_type=accepted_type,
        reviewer=result.classifier, review_fingerprint=review_fingerprint,
        base_input_fingerprint=base_fingerprint, taxonomy_version=taxonomy,
        provenance=result.provenance,
    )


def model(
    nodes: tuple[Any, ...],
    continuity: tuple[LogicalContinuityV3, ...],
    *,
    chapter_content: tuple[int, ...],
) -> BookModelV3:
    catalog = BookContentCatalogV3(nodes={node.id: node for node in nodes})
    body = (
        ChapterV3(
            id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
            content_fragment_ids=tuple(fid(item) for item in chapter_content),
        ),
    )
    revision = assembly_revision_for_state(
        metadata=metadata(), front_matter=MatterV3(), body=body, back_matter=MatterV3(),
        content=catalog, continuity=continuity, provenance=provenance(),
        logical_lists=(),
    )
    return BookModelV3(
        revision=revision, metadata=metadata(), body=body, content=catalog,
        continuity=continuity, provenance=provenance(),
    )


def edge(left: int, right: int, operation: ContinuityType, *, kind: str = "edge") -> LogicalContinuityV3:
    decision = boundary(left, right, operation, kind=kind)
    return LogicalContinuityV3(
        left_node_id=fid(left), right_node_id=fid(right), operation=operation,
        source_decision_id=decision.audit.decision_id,
    )


def test_assembly_input_requires_explicit_metadata() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE)})
    with pytest.raises(ValidationError, match="metadata"):
        AssemblyInput(semantic_catalog=catalog, accepted_classifications=accepted_classifications(catalog), resolved_flow=flow((1,), (1,)))


def test_metadata_language_identifier_and_title_traceability() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE)})
    value = input_for(catalog, flow((1,), (1,)))
    assert value.metadata.language == "vi"
    assert value.metadata.identifier == "urn:bookforge:test"
    assert assess_assembly_readiness(value).ready


@pytest.mark.parametrize("field", ["language", "identifier"])
def test_metadata_rejects_missing_required_strings(field: str) -> None:
    payload = metadata().model_dump()
    payload[field] = ""
    with pytest.raises(ValidationError):
        BookMetadataV3.model_validate(payload)


def test_title_reference_must_exist_and_remain_title_classified() -> None:
    catalog = BookContentCatalogV3(nodes={fid(2): text_node(2)})
    accepted = accepted_classifications(catalog)
    bad = AssemblyInput(
        metadata=metadata(), semantic_catalog=catalog, accepted_classifications=accepted,
        resolved_flow=flow((2,), (2,)),
    )
    assert AssemblyReadinessCode.INVALID_METADATA in {item.code for item in assess_assembly_readiness(bad).findings}


def test_fragment_classification_index_round_trip_is_explicit() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    accepted = accepted_classifications(catalog)
    restored = AcceptedClassificationCatalog.model_validate_json(accepted.model_dump_json())
    assert restored.by_fragment_id[fid(2)].target_source_ids == (sid(2),)


def test_mismatched_fragment_classification_source_identity_is_blocked() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    accepted = accepted_classifications(catalog)
    swapped = AcceptedClassificationCatalog(
        document_id=accepted.document_id,
        by_fragment_id={fid(1): accepted.by_fragment_id[fid(2)], fid(2): accepted.by_fragment_id[fid(1)]},
    )
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), accepted=swapped))
    assert AssemblyReadinessCode.INVALID_CLASSIFICATION_INDEX in {item.code for item in report.findings}


def test_same_family_review_materializes_without_source_change() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    accepted = accepted_classifications(catalog)
    review = classification_review(catalog, 2, SemanticType.QUOTE)
    effective = resolve_effective_classifications(accepted, (review,))
    updated = materialize_effective_catalog(catalog, effective)
    assert updated.nodes[fid(2)].semantic_type is SemanticType.QUOTE  # type: ignore[union-attr]
    assert updated.nodes[fid(2)].source_references == catalog.nodes[fid(2)].source_references  # type: ignore[union-attr]


def test_cross_family_text_to_figure_review_is_blocked() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    review = classification_review(catalog, 2, SemanticType.FIGURE)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), reviews=(review,)))
    assert AssemblyReadinessCode.INCOMPATIBLE_SEMANTIC_NODE in {item.code for item in report.findings}


def test_stale_classification_review_is_rejected() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    review = classification_review(catalog, 2, SemanticType.QUOTE, base_fingerprint="c" * 64)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), reviews=(review,)))
    assert AssemblyReadinessCode.STALE_REVIEW in {item.code for item in report.findings}


def test_conflicting_classification_reviews_are_rejected() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    first = classification_review(catalog, 2, SemanticType.QUOTE)
    second = first.model_copy(update={"id": classification_review_id(classification_id=str(first.classification_id), reviewer_name="other", review_fingerprint="d" * 64), "review_fingerprint": "d" * 64})
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), reviews=(first, second)))
    assert AssemblyReadinessCode.CONFLICTING_REVIEW in {item.code for item in report.findings}


@pytest.mark.parametrize(
    "operation",
    [
        ContinuityType.JOIN_DIRECT,
        ContinuityType.JOIN_WITH_SPACE,
        ContinuityType.JOIN_WITH_NEWLINE,
        ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
    ],
)
def test_text_continuity_operations_round_trip_without_joined_text(operation: ContinuityType) -> None:
    continuity = (edge(2, 3, operation),)
    book = model(
        (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)),
        continuity, chapter_content=(1, 2, 3),
    )
    restored = BookModelV3.model_validate_json(book.model_dump_json())
    assert restored.continuity[0].operation is operation
    assert "joined_text" not in restored.model_dump_json()


def test_list_continuity_preserves_nodes_without_regenerating_text() -> None:
    book = model(
        (text_node(1, SemanticType.BOOK_TITLE), text_node(2, SemanticType.LIST), text_node(3, SemanticType.LIST_ITEM)),
        (edge(2, 3, ContinuityType.CONTINUE_LIST),), chapter_content=(1, 2, 3),
    )
    assert len(book.content.nodes) == 3
    assert book.continuity[0].operation is ContinuityType.CONTINUE_LIST


def table_node(value: int) -> TableSemanticNode:
    source = sid(value)
    return TableSemanticNode(
        id=fid(value), evidence=(EvidenceReference(source_id=source, kind=EvidenceKind.TABLE),),
        table=TableDataV3(fragment_id=fid(value), source_ids=(source,), rows=()),
    )


def test_table_continuity_does_not_merge_or_duplicate_tables() -> None:
    left, right = table_node(2), table_node(3)
    book = model(
        (text_node(1, SemanticType.BOOK_TITLE), left, right),
        (edge(2, 3, ContinuityType.CONTINUE_TABLE),), chapter_content=(1, 2, 3),
    )
    assert book.content.nodes[fid(2)] == left and book.content.nodes[fid(3)] == right
    assert book.continuity[0].operation is ContinuityType.CONTINUE_TABLE


def test_continuity_targets_must_exist_and_be_adjacent() -> None:
    with pytest.raises(ValidationError, match="adjacent"):
        model(
            (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3), text_node(4)),
            (edge(2, 4, ContinuityType.JOIN_WITH_SPACE),), chapter_content=(1, 2, 3, 4),
        )


def test_excluded_intermediary_uses_final_included_adjacency() -> None:
    catalog = BookContentCatalogV3(nodes={
        fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2),
        fid(3): text_node(3, SemanticType.RUNNING_FOOTER), fid(4): text_node(4),
    })
    join = boundary(2, 4, ContinuityType.JOIN_WITH_SPACE)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2, 3, 4), (1, 2, 4), (join,))))
    assert report.ready


def test_join_across_chapter_boundary_is_rejected() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2), fid(3): text_node(3)})
    join = boundary(2, 3, ContinuityType.JOIN_WITH_SPACE, structural=StructuralBoundaryType.CHAPTER, break_intent=LogicalBreakIntent.NEW_PAGE)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2, 3), (1, 2, 3), (join,))))
    assert AssemblyReadinessCode.INVALID_CONTINUITY in {item.code for item in report.findings}


def test_contradictory_continuity_for_same_edge_is_rejected() -> None:
    with pytest.raises(ValidationError, match="one operation"):
        model(
            (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)),
            (edge(2, 3, ContinuityType.JOIN_DIRECT, kind="direct"), edge(2, 3, ContinuityType.JOIN_WITH_SPACE, kind="space")),
            chapter_content=(1, 2, 3),
        )


def test_reviewed_continuity_replacement_is_ready_and_original_unchanged() -> None:
    original = boundary(2, 3, ContinuityType.UNRESOLVED, kind="unresolved")
    replacement = boundary(2, 3, ContinuityType.JOIN_WITH_SPACE, kind="replacement")
    review = FlowDecisionReview(
        review_id=flow_decision_review_id(
            original_decision_id=str(original.audit.decision_id), accepted_decision_id=str(replacement.audit.decision_id),
            review_fingerprint=HASH,
        ),
        original_decision_id=original.audit.decision_id, status=ReviewStatus.REVIEWED_OVERRIDDEN,
        accepted_decision_id=replacement.audit.decision_id, reviewer=resolver(), review_fingerprint=HASH, created_at=EPOCH,
    )
    resolved = flow((1, 2, 3), (1, 2, 3), (original,), reviews=(review,), unresolved=(str(original.audit.decision_id),))
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2), fid(3): text_node(3)})
    report = assess_assembly_readiness(input_for(catalog, resolved, replacements=(replacement,)))
    assert report.ready
    assert original.continuity is ContinuityType.UNRESOLVED
    effective = materialize_effective_continuity(resolved, (replacement,))
    assert effective[0].operation is ContinuityType.JOIN_WITH_SPACE
    assert effective[0].source_decision_id == replacement.audit.decision_id


def test_continuity_changes_revision_and_serialization_is_deterministic() -> None:
    nodes = (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3))
    space = model(nodes, (edge(2, 3, ContinuityType.JOIN_WITH_SPACE),), chapter_content=(1, 2, 3))
    direct = model(nodes, (edge(2, 3, ContinuityType.JOIN_DIRECT),), chapter_content=(1, 2, 3))
    repeated = model(nodes, (edge(2, 3, ContinuityType.JOIN_WITH_SPACE),), chapter_content=(1, 2, 3))
    assert space.revision != direct.revision
    assert space.model_dump_json() == repeated.model_dump_json()


def test_continuity_contract_rejects_unknown_fields() -> None:
    payload = edge(2, 3, ContinuityType.JOIN_DIRECT).model_dump()
    payload["joined_text"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs"):
        LogicalContinuityV3.model_validate(payload)


def test_figure_to_decorative_review_is_invalid_cross_family() -> None:
    image_id = SourceId("docx_img000002")
    figure = FigureSemanticNode(
        id=fid(2), evidence=(EvidenceReference(source_id=image_id, kind=EvidenceKind.IMAGE, asset_reference="assets/f.png"),),
        figure=FigureDataV3(fragment_id=fid(2), source_image_id=image_id),
    )
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): figure})
    review = classification_review(catalog, 2, SemanticType.DECORATIVE)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), reviews=(review,)))
    assert AssemblyReadinessCode.INCOMPATIBLE_SEMANTIC_NODE in {item.code for item in report.findings}


def test_title_review_to_non_title_is_metadata_blocker() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE)})
    review = classification_review(catalog, 1, SemanticType.PARAGRAPH)
    report = assess_assembly_readiness(input_for(catalog, flow((1,), (1,)), reviews=(review,)))
    assert AssemblyReadinessCode.INVALID_METADATA in {item.code for item in report.findings}


def test_taxonomy_stale_classification_review_is_rejected() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    review = classification_review(catalog, 2, SemanticType.QUOTE, taxonomy="old-taxonomy")
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2), (1, 2)), reviews=(review,)))
    assert AssemblyReadinessCode.STALE_REVIEW in {item.code for item in report.findings}


def test_classification_catalog_rejects_wrong_document_identity() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE)})
    result = accepted_classifications(catalog).by_fragment_id[fid(1)]
    wrong = result.model_copy(update={"provenance": result.provenance.model_copy(update={"document_id": "doc_bbbbbbbbbbbbbbbb"})})
    with pytest.raises(ValidationError, match="document identity"):
        AcceptedClassificationCatalog(document_id="doc_aaaaaaaaaaaaaaaa", by_fragment_id={fid(1): wrong})


def test_text_continuity_rejects_table_node_family() -> None:
    with pytest.raises(ValidationError, match="text join"):
        model(
            (text_node(1, SemanticType.BOOK_TITLE), table_node(2), text_node(3)),
            (edge(2, 3, ContinuityType.JOIN_WITH_SPACE),), chapter_content=(1, 2, 3),
        )


def test_list_continuity_rejects_generic_paragraphs() -> None:
    with pytest.raises(ValidationError, match="list continuity"):
        model(
            (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)),
            (edge(2, 3, ContinuityType.CONTINUE_LIST),), chapter_content=(1, 2, 3),
        )


def test_table_continuity_rejects_text_nodes() -> None:
    with pytest.raises(ValidationError, match="table continuity"):
        model(
            (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)),
            (edge(2, 3, ContinuityType.CONTINUE_TABLE),), chapter_content=(1, 2, 3),
        )


def test_join_cannot_cross_bookmodel_chapter_containers() -> None:
    nodes = (text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3))
    catalog = BookContentCatalogV3(nodes={node.id: node for node in nodes})
    body = (
        ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(1), fid(2))),
        ChapterV3(id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(3),)),
    )
    with pytest.raises(ValidationError, match="cannot cross"):
        BookModelV3(
            revision="asm_aaaaaaaaaaaaaaaaaaaa", metadata=metadata(), body=body, content=catalog,
            continuity=(edge(2, 3, ContinuityType.JOIN_WITH_SPACE),), provenance=provenance(),
        )


def test_keep_separate_is_preserved_as_auditable_edge() -> None:
    book = model(
        (text_node(1, SemanticType.BOOK_TITLE), text_node(2)),
        (edge(1, 2, ContinuityType.KEEP_SEPARATE),), chapter_content=(1, 2),
    )
    assert book.continuity[0].operation is ContinuityType.KEEP_SEPARATE


def test_continuity_family_validation_uses_effective_reviewed_types() -> None:
    catalog = BookContentCatalogV3(nodes={
        fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2), fid(3): text_node(3),
    })
    reviews = (
        classification_review(catalog, 2, SemanticType.LIST),
        classification_review(catalog, 3, SemanticType.LIST_ITEM).model_copy(
            update={"id": classification_review_id(
                classification_id=str(accepted_classifications(catalog).by_fragment_id[fid(3)].id),
                reviewer_name="second", review_fingerprint="e" * 64,
            ), "review_fingerprint": "e" * 64}
        ),
    )
    continuation = boundary(2, 3, ContinuityType.CONTINUE_LIST)
    report = assess_assembly_readiness(input_for(catalog, flow((1, 2, 3), (1, 2, 3), (continuation,)), reviews=reviews))
    assert report.ready
