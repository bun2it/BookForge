from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from bookforge.contracts.assembly import (
    AcceptedClassificationCatalog,
    AssemblyAdmissionMode,
    AssemblyInput,
    AssemblyPolicy,
    AssemblyProvenance,
    AssemblyReadinessCode,
    BodyEntryKind,
    BookContentCatalogV3,
    BookMetadataV3,
    BookModelV3,
    ChapterV3,
    EvidenceKind,
    EvidenceReference,
    FigureDataV3,
    FigureSemanticNode,
    MatterV3,
    PartV3,
    SectionLevel,
    SectionV3,
    TableCellV3,
    TableDataV3,
    TableRowV3,
    TableSemanticNode,
    TextSemanticNode,
    UnsupportedContentKind,
    UnsupportedSemanticNode,
    assess_assembly_readiness,
)
from bookforge.contracts.book import BookModel
from bookforge.contracts.interfaces import EpubBuilder
from bookforge.contracts.classification import (
    ClassificationProvenance,
    ClassificationResult,
    ClassifierIdentity,
    ClassifierKind,
    ReviewStatus,
)
from bookforge.contracts.common import FragmentId, SourceId
from bookforge.contracts.flow import (
    BoundaryEdge,
    ContinuityType,
    FlowDecisionAudit,
    FlowDecisionProvenance,
    FlowDecisionReview,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    ResolvedContentFlow,
    ResolvedFlowProvenance,
    ResolverIdentity,
    ResolverKind,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import classification_result_id, flow_decision_id, flow_decision_review_id, flow_group_id
from bookforge.contracts.semantic import SemanticType
from bookforge.contracts.source import SourceTextReference

HASH = "a" * 64
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fid(value: int) -> FragmentId:
    return FragmentId(f"sem_f{value:06d}")


def sid(value: int) -> SourceId:
    return SourceId(f"docx_p{value:06d}")


def text_node(value: int, semantic_type: SemanticType = SemanticType.PARAGRAPH) -> TextSemanticNode:
    source_id = sid(value)
    return TextSemanticNode(
        id=fid(value),
        semantic_type=semantic_type,
        source_references=(SourceTextReference(source_id=source_id),),
        source_evidence=(EvidenceReference(source_id=source_id, kind=EvidenceKind.TEXT),),
    )


def accepted_classifications(catalog: BookContentCatalogV3) -> AcceptedClassificationCatalog:
    values: dict[FragmentId, ClassificationResult] = {}
    for fragment_id, node in catalog.nodes.items():
        if isinstance(node, TextSemanticNode):
            source_ids = tuple(item.source_id for item in node.source_evidence)
            references = node.source_references
            semantic_type = node.semantic_type
        else:
            source_ids = tuple(item.source_id for item in node.evidence)
            references = ()
            semantic_type = getattr(node, "semantic_type", SemanticType.UNKNOWN)
        classification_id = classification_result_id(
            target_source_ids=[str(item) for item in source_ids], taxonomy_version="bookforge-semantic-v1",
            classifier_name="test", classifier_version="1", configuration_fingerprint=HASH,
            input_fingerprint=HASH, context_fingerprint=HASH,
        )
        values[fragment_id] = ClassificationResult(
            id=classification_id, target_source_ids=source_ids, source_references=references,
            semantic_type=semantic_type, confidence=1, review_status=ReviewStatus.NOT_REQUIRED,
            classifier=ClassifierIdentity(name="test", kind=ClassifierKind.DETERMINISTIC, version="1"),
            configuration_fingerprint=HASH, input_fingerprint=HASH, context_fingerprint=HASH,
            provenance=ClassificationProvenance(document_id="doc_aaaaaaaaaaaaaaaa", source_ids=source_ids, created_at=EPOCH),
        )
    return AcceptedClassificationCatalog(document_id="doc_aaaaaaaaaaaaaaaa", by_fragment_id=values)


def assembly_input(
    catalog: BookContentCatalogV3,
    flow: ResolvedContentFlow,
    *,
    replacement_decisions: tuple[LogicalBoundaryDecision, ...] = (),
) -> AssemblyInput:
    return AssemblyInput(
        metadata=BookMetadataV3(title_fragment_id=fid(1), language="en", identifier="urn:test"),
        semantic_catalog=catalog,
        accepted_classifications=accepted_classifications(catalog),
        resolved_flow=flow,
        replacement_decisions=replacement_decisions,
    )


def provenance() -> AssemblyProvenance:
    return AssemblyProvenance(
        document_id="doc_aaaaaaaaaaaaaaaa",
        semantic_catalog_fingerprint=HASH,
        accepted_classification_fingerprint=HASH,
        resolved_flow_fingerprint=HASH,
        assembly_policy_fingerprint=HASH,
    )


def make_book(*, body: tuple[ChapterV3 | PartV3, ...], nodes: tuple[object, ...]) -> BookModelV3:
    catalog = BookContentCatalogV3(nodes={node.id: node for node in nodes})  # type: ignore[attr-defined]
    return BookModelV3(
        revision="asm_aaaaaaaaaaaaaaaaaaaa",
        metadata=BookMetadataV3(title_fragment_id=fid(1), language="en", identifier="urn:test"),
        body=body,
        content=catalog,
        provenance=provenance(),
    )


def resolver() -> ResolverIdentity:
    return ResolverIdentity(name="test", kind=ResolverKind.DETERMINISTIC, version="1")


def decision_provenance() -> FlowDecisionProvenance:
    return FlowDecisionProvenance(
        document_id="doc_aaaaaaaaaaaaaaaa",
        resolver=resolver(), configuration_fingerprint=HASH, input_fingerprint=HASH,
        semantic_taxonomy_version="v1", flow_policy_version="v1", created_at=EPOCH,
    )


def unresolved_boundary() -> LogicalBoundaryDecision:
    decision_id = flow_decision_id(
        decision_kind="boundary", fragment_ids=[str(fid(1)), str(fid(2))],
        input_fingerprint=HASH, configuration_fingerprint=HASH, policy_version="v1",
    )
    return LogicalBoundaryDecision(
        audit=FlowDecisionAudit(decision_id=decision_id, confidence=0, review_status=ReviewStatus.NEEDS_REVIEW, provenance=decision_provenance()),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS, preceding_fragment_id=fid(1), following_fragment_id=fid(2),
        continuity=ContinuityType.UNRESOLVED, structural_boundary=StructuralBoundaryType.UNRESOLVED,
        break_intent=LogicalBreakIntent.UNRESOLVED,
    )


def make_flow(boundary: LogicalBoundaryDecision, *, reviews: tuple[FlowDecisionReview, ...] = ()) -> ResolvedContentFlow:
    return ResolvedContentFlow(
        revision="flow-test", source_fragment_ids=(fid(1), fid(2)), ordered_fragment_ids=(fid(1), fid(2)),
        boundaries=(boundary,), unresolved_decision_ids=(boundary.audit.decision_id,), decision_reviews=reviews,
        provenance=ResolvedFlowProvenance(
            document_id="doc_aaaaaaaaaaaaaaaa", resolver=resolver(), configuration_fingerprint=HASH,
            input_fingerprint=HASH, semantic_taxonomy_version="v1", flow_policy_version="v1", created_at=EPOCH,
        ),
    )


def test_chapter_only_book_has_one_authoritative_body_order() -> None:
    chapter1 = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    chapter2 = ChapterV3(id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(3),))
    book = make_book(body=(chapter1, chapter2), nodes=(text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)))
    assert [entry.id for entry in book.body] == ["flow_chapter_0001", "flow_chapter_0002"]
    assert "chapters" not in book.model_dump()


def test_part_hierarchy_and_part_opening_content_round_trip() -> None:
    part = PartV3(
        id=flow_group_id("part", 1), break_intent=LogicalBreakIntent.NEW_PAGE,
        opening_fragment_ids=(fid(2),), content_fragment_ids=(fid(3),),
        chapters=(
            ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(4),)),
            ChapterV3(id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(5),)),
        ),
    )
    book = make_book(body=(part,), nodes=tuple(text_node(i, SemanticType.BOOK_TITLE if i == 1 else SemanticType.PARAGRAPH) for i in range(1, 6)))
    restored = BookModelV3.model_validate_json(book.model_dump_json())
    assert isinstance(restored.body[0], PartV3)
    assert restored.body[0].opening_fragment_ids == (fid(2),)


def test_mixed_parts_and_ungrouped_chapters_are_unambiguous() -> None:
    part = PartV3(id=flow_group_id("part", 1), break_intent=LogicalBreakIntent.NEW_PAGE, chapters=(ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),)),))
    loose = ChapterV3(id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(3),))
    book = make_book(body=(part, loose), nodes=(text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)))
    assert [entry.kind for entry in book.body] == [BodyEntryKind.PART, BodyEntryKind.CHAPTER]


def test_break_intent_survives_part_chapter_section_subsection() -> None:
    subsection = SectionV3(id=flow_group_id("subsection", 1), level=SectionLevel.SUBSECTION, break_intent=LogicalBreakIntent.NONE, content_fragment_ids=(fid(5),))
    section = SectionV3(id=flow_group_id("section", 1), level=SectionLevel.SECTION, break_intent=LogicalBreakIntent.NONE, content_fragment_ids=(fid(4),), subsections=(subsection,))
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(3),), sections=(section,))
    part = PartV3(id=flow_group_id("part", 1), break_intent=LogicalBreakIntent.NEW_PAGE, opening_fragment_ids=(fid(2),), chapters=(chapter,))
    book = make_book(body=(part,), nodes=tuple(text_node(i, SemanticType.BOOK_TITLE if i == 1 else SemanticType.PARAGRAPH) for i in range(1, 6)))
    assert (book.body[0].break_intent, book.body[0].chapters[0].break_intent) == (LogicalBreakIntent.NEW_PAGE, LogicalBreakIntent.NEW_PAGE)  # type: ignore[union-attr]
    assert section.break_intent is subsection.break_intent is LogicalBreakIntent.NONE


def test_untitled_chapter_is_valid_but_empty_chapter_is_not() -> None:
    ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    with pytest.raises(ValidationError, match="must own content"):
        ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE)


def test_duplicate_fragment_ownership_is_rejected() -> None:
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    with pytest.raises(ValidationError, match="owned only once"):
        BookModelV3(
            revision="asm_aaaaaaaaaaaaaaaaaaaa", metadata=BookMetadataV3(title_fragment_id=fid(1), language="en", identifier="x"),
            front_matter=MatterV3(content_fragment_ids=(fid(2),)), body=(chapter,),
            content=BookContentCatalogV3(nodes={fid(1): text_node(1), fid(2): text_node(2)}), provenance=provenance(),
        )


def test_dangling_hierarchy_reference_is_rejected() -> None:
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(9),))
    with pytest.raises(ValidationError, match="missing semantic nodes"):
        make_book(body=(chapter,), nodes=(text_node(1),))


def test_unknown_fields_and_old_schema_are_rejected() -> None:
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    book = make_book(body=(chapter,), nodes=(text_node(1), text_node(2)))
    payload = book.model_dump(mode="json")
    payload["schema_version"] = 2
    with pytest.raises(ValidationError):
        BookModelV3.model_validate(payload)
    payload["schema_version"] = 3
    payload["physical_page_number"] = 1
    with pytest.raises(ValidationError, match="Extra inputs"):
        BookModelV3.model_validate(payload)


def test_no_authoritative_copied_text_or_layout_commands_serialize() -> None:
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    serialized = make_book(body=(chapter,), nodes=(text_node(1), text_node(2))).model_dump_json()
    for forbidden in ('"text":', "joined_text", "generated_text", "docx_anchor", "pdf_page", "physical_page"):
        assert forbidden not in serialized


def test_figure_has_source_neutral_asset_and_caption_traceability() -> None:
    figure = FigureSemanticNode(
        id=fid(2), evidence=(EvidenceReference(source_id=SourceId("docx_img000002"), kind=EvidenceKind.IMAGE, asset_reference="assets/image-2.png"),),
        figure=FigureDataV3(fragment_id=fid(2), source_image_id=SourceId("docx_img000002"), caption_fragment_id=fid(3)),
    )
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2), fid(3), fid(4)))
    book = make_book(body=(chapter,), nodes=(text_node(1), figure, text_node(3, SemanticType.CAPTION), text_node(4)))
    assert book.content.nodes[fid(2)].figure.caption_fragment_id == fid(3)  # type: ignore[union-attr]
    assert book.content.nodes[fid(3)].source_references  # type: ignore[union-attr]


def test_missing_figure_asset_provenance_is_rejected() -> None:
    with pytest.raises(ValidationError, match="asset reference"):
        EvidenceReference(source_id=SourceId("docx_img000002"), kind=EvidenceKind.IMAGE)


def test_table_structure_and_cell_text_remain_source_backed() -> None:
    source_table = SourceId("docx_tbl000002")
    cell_ref = SourceTextReference(source_id=SourceId("docx_tbl000002_row0001_c0001"))
    table = TableSemanticNode(
        id=fid(2), evidence=(EvidenceReference(source_id=source_table, kind=EvidenceKind.TABLE),),
        table=TableDataV3(fragment_id=fid(2), source_ids=(source_table,), rows=(TableRowV3(index=0, cells=(TableCellV3(row_index=0, column_index=0, source_references=(cell_ref,), is_header=True, row_span=2, column_span=1),)),)),
    )
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    book = make_book(body=(chapter,), nodes=(text_node(1), table))
    assert book.content.nodes[fid(2)].table.rows[0].cells[0].source_references == (cell_ref,)  # type: ignore[union-attr]


def test_unsupported_drawing_cannot_enter_reading_order() -> None:
    drawing = UnsupportedSemanticNode(id=fid(2), content_kind=UnsupportedContentKind.DRAWING, evidence=(EvidenceReference(source_id=SourceId("docx_drw000002"), kind=EvidenceKind.DRAWING),), reason_code="renderer_unsupported")
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),))
    with pytest.raises(ValidationError, match="unsupported semantic content"):
        make_book(body=(chapter,), nodes=(text_node(1), drawing))


def test_strict_unresolved_flow_is_a_blocker() -> None:
    boundary = unresolved_boundary()
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    report = assess_assembly_readiness(assembly_input(catalog, make_flow(boundary)))
    assert not report.ready
    assert AssemblyReadinessCode.UNRESOLVED_FLOW in {finding.code for finding in report.findings}


def test_reviewed_replacement_is_accepted_without_mutating_original() -> None:
    original = unresolved_boundary()
    replacement_id = flow_decision_id(decision_kind="replacement", fragment_ids=[str(fid(1)), str(fid(2))], input_fingerprint=HASH, configuration_fingerprint=HASH, policy_version="v1")
    replacement = original.model_copy(update={
        "audit": original.audit.model_copy(update={"decision_id": replacement_id, "review_status": ReviewStatus.REVIEWED_OVERRIDDEN}),
        "continuity": ContinuityType.KEEP_SEPARATE, "structural_boundary": StructuralBoundaryType.CHAPTER,
        "break_intent": LogicalBreakIntent.NEW_PAGE,
    })
    review = FlowDecisionReview(
        review_id=flow_decision_review_id(original_decision_id=str(original.audit.decision_id), accepted_decision_id=str(replacement_id), review_fingerprint=HASH),
        original_decision_id=original.audit.decision_id, status=ReviewStatus.REVIEWED_OVERRIDDEN,
        accepted_decision_id=replacement_id, reviewer=resolver(), review_fingerprint=HASH, created_at=EPOCH,
    )
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    report = assess_assembly_readiness(assembly_input(catalog, make_flow(original, reviews=(review,)), replacement_decisions=(replacement,)))
    assert report.ready
    assert original.continuity is ContinuityType.UNRESOLVED


def test_conflicting_active_reviews_are_rejected() -> None:
    original = unresolved_boundary()
    reviews = tuple(
        FlowDecisionReview(
            review_id=flow_decision_review_id(original_decision_id=str(original.audit.decision_id), accepted_decision_id=str(original.audit.decision_id), review_fingerprint=char * 64),
            original_decision_id=original.audit.decision_id, status=ReviewStatus.REVIEWED_ACCEPTED,
            accepted_decision_id=original.audit.decision_id, reviewer=resolver(), review_fingerprint=char * 64, created_at=EPOCH,
        ) for char in ("b", "c")
    )
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2)})
    report = assess_assembly_readiness(assembly_input(catalog, make_flow(original, reviews=reviews)))
    assert AssemblyReadinessCode.CONFLICTING_REVIEW in {finding.code for finding in report.findings}


def test_explicit_exclusion_retains_catalog_evidence() -> None:
    decision_id = flow_decision_id(decision_kind="inclusion", fragment_ids=[str(fid(2))], input_fingerprint=HASH, configuration_fingerprint=HASH, policy_version="v1")
    exclusion = InclusionDecision(audit=FlowDecisionAudit(decision_id=decision_id, confidence=1, review_status=ReviewStatus.NOT_REQUIRED, provenance=decision_provenance()), target_fragment_id=fid(2), inclusion=InclusionType.EXCLUDE)
    flow = ResolvedContentFlow(
        revision="flow-exclusion", source_fragment_ids=(fid(1), fid(2)), ordered_fragment_ids=(fid(1),), inclusion_decisions=(exclusion,),
        provenance=ResolvedFlowProvenance(document_id="doc_aaaaaaaaaaaaaaaa", resolver=resolver(), configuration_fingerprint=HASH, input_fingerprint=HASH, semantic_taxonomy_version="v1", flow_policy_version="v1", created_at=EPOCH),
    )
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2, SemanticType.RUNNING_FOOTER)})
    report = assess_assembly_readiness(assembly_input(catalog, flow))
    assert report.ready and fid(2) in catalog.nodes and fid(2) not in flow.ordered_fragment_ids


def test_readiness_rejects_missing_semantic_node() -> None:
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE)})
    report = assess_assembly_readiness(assembly_input(catalog, make_flow(unresolved_boundary())))
    assert AssemblyReadinessCode.MISSING_SEMANTIC_CONTENT in {finding.code for finding in report.findings}


def test_permissive_guessing_mode_does_not_exist() -> None:
    assert {mode.value for mode in AssemblyAdmissionMode} == {"strict", "reviewed"}


def test_v3_models_are_deeply_immutable_at_new_contract_boundaries() -> None:
    node = text_node(1)
    with pytest.raises(ValidationError):
        node.semantic_type = SemanticType.AUTHOR


def test_part_ids_are_deterministic_and_kind_checked() -> None:
    assert flow_group_id("part", 1) == flow_group_id("part", 1) == "flow_part_0001"
    with pytest.raises(ValidationError):
        PartV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, chapters=(ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2),)),))


def test_unresolved_break_cannot_cross_assembly_output_boundary() -> None:
    with pytest.raises(ValidationError, match="unresolved break"):
        ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.UNRESOLVED, content_fragment_ids=(fid(2),))


def test_catalog_key_must_match_node_id() -> None:
    with pytest.raises(ValidationError, match="catalog key"):
        BookContentCatalogV3(nodes={fid(9): text_node(1)})


def test_figure_caption_must_resolve_to_caption_text_node() -> None:
    figure = FigureSemanticNode(
        id=fid(2), evidence=(EvidenceReference(source_id=SourceId("docx_img000002"), kind=EvidenceKind.IMAGE, asset_reference="assets/i.png"),),
        figure=FigureDataV3(fragment_id=fid(2), source_image_id=SourceId("docx_img000002"), caption_fragment_id=fid(3)),
    )
    chapter = ChapterV3(id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NEW_PAGE, content_fragment_ids=(fid(2), fid(3)))
    with pytest.raises(ValidationError, match="CAPTION"):
        make_book(body=(chapter,), nodes=(text_node(1), figure, text_node(3, SemanticType.PARAGRAPH)))


def test_table_requires_matching_table_provenance() -> None:
    with pytest.raises(ValidationError, match="table provenance"):
        TableSemanticNode(
            id=fid(2), evidence=(EvidenceReference(source_id=SourceId("docx_tbl000003"), kind=EvidenceKind.TABLE),),
            table=TableDataV3(fragment_id=fid(2), source_ids=(SourceId("docx_tbl000002"),), rows=()),
        )


def test_unsupported_catalog_content_blocks_readiness_even_when_not_ordered() -> None:
    drawing = UnsupportedSemanticNode(id=fid(3), content_kind=UnsupportedContentKind.DRAWING, evidence=(EvidenceReference(source_id=SourceId("docx_drw000003"), kind=EvidenceKind.DRAWING),), reason_code="unsupported")
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): text_node(2), fid(3): drawing})
    report = assess_assembly_readiness(assembly_input(catalog, make_flow(unresolved_boundary())))
    assert AssemblyReadinessCode.UNSUPPORTED_CONTENT in {finding.code for finding in report.findings}


def test_unsupported_drawing_with_explicit_exclusion_is_admissible() -> None:
    drawing = UnsupportedSemanticNode(id=fid(2), content_kind=UnsupportedContentKind.DRAWING, evidence=(EvidenceReference(source_id=SourceId("docx_drw000002"), kind=EvidenceKind.DRAWING),), reason_code="unsupported")
    decision_id = flow_decision_id(decision_kind="drawing-exclusion", fragment_ids=[str(fid(2))], input_fingerprint=HASH, configuration_fingerprint=HASH, policy_version="v1")
    exclusion = InclusionDecision(audit=FlowDecisionAudit(decision_id=decision_id, confidence=1, review_status=ReviewStatus.NOT_REQUIRED, provenance=decision_provenance()), target_fragment_id=fid(2), inclusion=InclusionType.EXCLUDE)
    flow = ResolvedContentFlow(
        revision="flow-drawing-exclusion", source_fragment_ids=(fid(1), fid(2)), ordered_fragment_ids=(fid(1),), inclusion_decisions=(exclusion,),
        provenance=ResolvedFlowProvenance(document_id="doc_aaaaaaaaaaaaaaaa", resolver=resolver(), configuration_fingerprint=HASH, input_fingerprint=HASH, semantic_taxonomy_version="v1", flow_policy_version="v1", created_at=EPOCH),
    )
    catalog = BookContentCatalogV3(nodes={fid(1): text_node(1, SemanticType.BOOK_TITLE), fid(2): drawing})
    report = assess_assembly_readiness(assembly_input(catalog, flow))
    assert report.ready


def test_v2_remains_renderer_protocol_input_while_v3_is_assembly_output() -> None:
    assert BookModel.model_fields["schema_version"].default == 2
    assert BookModelV3.model_fields["schema_version"].default == 3
    assert "BookModel" in str(EpubBuilder.build.__annotations__["book"])
