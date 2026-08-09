from __future__ import annotations

from time import perf_counter

import pytest

from bookforge.assembly import BookAssembler
from bookforge.contracts.assembly import (
    AssemblyInput,
    AssemblyNotReadyError,
    AssemblyReadinessCode,
    BookContentCatalogV3,
    BookMetadataV3,
    TextSemanticNode,
    UnsupportedContentKind,
    UnsupportedSemanticNode,
)
from bookforge.contracts.classification import ReviewStatus
from bookforge.contracts.common import FragmentId
from bookforge.contracts.flow import (
    BoundaryEdge,
    ContinuityType,
    FlowDecisionAudit,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    LogicalGroup,
    LogicalGroupType,
    ResolvedContentFlow,
    ResolvedFlowProvenance,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import flow_decision_id, flow_group_id
from bookforge.contracts.semantic import SemanticType

from tests.contracts.test_m45_assembly_contracts import (
    EPOCH,
    HASH,
    accepted_classifications,
    decision_provenance,
    fid,
    resolver,
    sid,
    text_node,
)


def audit(kind: str, fragments: tuple[FragmentId, ...]) -> FlowDecisionAudit:
    return FlowDecisionAudit(
        decision_id=flow_decision_id(
            decision_kind=kind,
            fragment_ids=[str(item) for item in fragments],
            input_fingerprint=HASH,
            configuration_fingerprint=HASH,
            policy_version="v1",
        ),
        confidence=1,
        review_status=ReviewStatus.NOT_REQUIRED,
        provenance=decision_provenance(),
    )


def start_boundary(fragment: FragmentId, structural: StructuralBoundaryType) -> LogicalBoundaryDecision:
    return LogicalBoundaryDecision(
        audit=audit(f"start-{structural.value}", (fragment,)),
        edge=BoundaryEdge.START_OF_DOCUMENT,
        following_fragment_id=fragment,
        continuity=ContinuityType.KEEP_SEPARATE,
        structural_boundary=structural,
        break_intent=LogicalBreakIntent.NONE,
    )


def between_boundary(
    left: FragmentId,
    right: FragmentId,
    *,
    structural: StructuralBoundaryType = StructuralBoundaryType.CHAPTER,
    break_intent: LogicalBreakIntent = LogicalBreakIntent.NEW_PAGE,
    continuity: ContinuityType = ContinuityType.KEEP_SEPARATE,
) -> LogicalBoundaryDecision:
    references = ()
    if continuity in {
        ContinuityType.JOIN_DIRECT,
        ContinuityType.JOIN_WITH_SPACE,
        ContinuityType.JOIN_WITH_NEWLINE,
        ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
        ContinuityType.CONTINUE_LIST,
    }:
        references = (*text_node(int(str(left)[-6:])).source_references, *text_node(int(str(right)[-6:])).source_references)
    return LogicalBoundaryDecision(
        audit=audit(f"between-{structural.value}-{continuity.value}", (left, right)),
        edge=BoundaryEdge.BETWEEN_FRAGMENTS,
        preceding_fragment_id=left,
        following_fragment_id=right,
        source_references=references,
        continuity=continuity,
        structural_boundary=structural,
        break_intent=break_intent,
    )


def inclusion(fragment: FragmentId, value: InclusionType = InclusionType.INCLUDE) -> InclusionDecision:
    return InclusionDecision(
        audit=audit(f"inclusion-{value.value}", (fragment,)),
        target_fragment_id=fragment,
        inclusion=value,
    )


def minimal_input(
    *,
    nodes: tuple[object, ...] | None = None,
    paragraph_ids: tuple[int, ...] = (2,),
    continuity: ContinuityType = ContinuityType.KEEP_SEPARATE,
) -> AssemblyInput:
    actual_nodes = nodes or (text_node(1, SemanticType.BOOK_TITLE), *(text_node(item) for item in paragraph_ids))
    catalog = BookContentCatalogV3(nodes={node.id: node for node in actual_nodes})  # type: ignore[attr-defined]
    title = fid(1)
    body_ids = tuple(fid(item) for item in paragraph_ids)
    front_boundary = start_boundary(title, StructuralBoundaryType.FRONT_MATTER_TRANSITION)
    chapter_boundary = between_boundary(
        title,
        body_ids[0],
        structural=StructuralBoundaryType.CHAPTER,
        break_intent=LogicalBreakIntent.NEW_PAGE,
    )
    boundaries = [front_boundary, chapter_boundary]
    if len(body_ids) > 1 and continuity is not ContinuityType.KEEP_SEPARATE:
        boundaries.append(
            between_boundary(
                body_ids[-2],
                body_ids[-1],
                structural=StructuralBoundaryType.NONE,
                break_intent=LogicalBreakIntent.NONE,
                continuity=continuity,
            )
        )
    flow = ResolvedContentFlow(
        revision="flow-m5a",
        source_fragment_ids=tuple(catalog.nodes),
        ordered_fragment_ids=(title, *body_ids),
        boundaries=tuple(boundaries),
        groups=(
            LogicalGroup(
                group_id=flow_group_id("front_matter", 1),
                group_type=LogicalGroupType.FRONT_MATTER,
                opening_fragment_ids=(title,),
                member_fragment_ids=(title,),
                boundary_decision_id=front_boundary.audit.decision_id,
            ),
            LogicalGroup(
                group_id=flow_group_id("chapter", 1),
                group_type=LogicalGroupType.CHAPTER,
                opening_fragment_ids=(body_ids[0],),
                member_fragment_ids=body_ids,
                boundary_decision_id=chapter_boundary.audit.decision_id,
            ),
        ),
        inclusion_decisions=tuple(inclusion(item) for item in catalog.nodes),
        provenance=ResolvedFlowProvenance(
            document_id="doc_aaaaaaaaaaaaaaaa",
            resolver=resolver(),
            configuration_fingerprint=HASH,
            input_fingerprint=HASH,
            semantic_taxonomy_version="bookforge-semantic-v1",
            flow_policy_version="v1",
            created_at=EPOCH,
        ),
    )
    return AssemblyInput(
        metadata=BookMetadataV3(
            title_fragment_id=title,
            language="vi",
            identifier="urn:bookforge:m5a",
            publisher="BookForge",
            description="Bản thử nghiệm tiếng Việt",
        ),
        semantic_catalog=catalog,
        accepted_classifications=accepted_classifications(catalog),
        resolved_flow=flow,
    )


def test_minimal_book_preflight_and_assembly_are_deterministic() -> None:
    value = minimal_input()
    before = value.model_dump_json()
    assembler = BookAssembler()
    assert assembler.preflight(value).ready
    first = assembler.assemble(value)
    second = assembler.assemble(value)
    assert first == second
    assert first.revision == second.revision
    assert first.model_dump_json() == second.model_dump_json()
    assert value.model_dump_json() == before
    assert first.metadata.language == "vi"
    assert first.body[0].break_intent is LogicalBreakIntent.NEW_PAGE


def test_part_hierarchy_and_m4_breaks_are_preserved_without_page_inference() -> None:
    catalog = BookContentCatalogV3(
        nodes={
            fid(1): text_node(1, SemanticType.BOOK_TITLE),
            fid(2): text_node(2, SemanticType.PART_TITLE),
            fid(3): text_node(3, SemanticType.CHAPTER_TITLE),
            fid(4): text_node(4, SemanticType.CHAPTER_TITLE),
        }
    )
    front = start_boundary(fid(1), StructuralBoundaryType.FRONT_MATTER_TRANSITION)
    part_boundary = between_boundary(
        fid(1), fid(2), structural=StructuralBoundaryType.PART,
        break_intent=LogicalBreakIntent.NEW_PAGE,
    )
    chapter_one = between_boundary(
        fid(2), fid(3), structural=StructuralBoundaryType.CHAPTER,
        break_intent=LogicalBreakIntent.NEW_PAGE,
    )
    chapter_two = between_boundary(
        fid(3), fid(4), structural=StructuralBoundaryType.CHAPTER,
        break_intent=LogicalBreakIntent.NONE,
    )
    part_id = flow_group_id("part", 1)
    groups = (
        LogicalGroup(
            group_id=flow_group_id("front_matter", 1),
            group_type=LogicalGroupType.FRONT_MATTER,
            opening_fragment_ids=(fid(1),), member_fragment_ids=(fid(1),),
            boundary_decision_id=front.audit.decision_id,
        ),
        LogicalGroup(
            group_id=part_id, group_type=LogicalGroupType.PART,
            opening_fragment_ids=(fid(2),), member_fragment_ids=(fid(2), fid(3), fid(4)),
            boundary_decision_id=part_boundary.audit.decision_id,
        ),
        LogicalGroup(
            group_id=flow_group_id("chapter", 1), group_type=LogicalGroupType.CHAPTER,
            opening_fragment_ids=(fid(3),), member_fragment_ids=(fid(3),),
            parent_group_id=part_id, boundary_decision_id=chapter_one.audit.decision_id,
        ),
        LogicalGroup(
            group_id=flow_group_id("chapter", 2), group_type=LogicalGroupType.CHAPTER,
            opening_fragment_ids=(fid(4),), member_fragment_ids=(fid(4),),
            parent_group_id=part_id, boundary_decision_id=chapter_two.audit.decision_id,
        ),
    )
    flow = ResolvedContentFlow(
        revision="flow-part",
        source_fragment_ids=tuple(catalog.nodes), ordered_fragment_ids=tuple(catalog.nodes),
        boundaries=(front, part_boundary, chapter_one, chapter_two), groups=groups,
        inclusion_decisions=tuple(inclusion(item) for item in catalog.nodes),
        provenance=ResolvedFlowProvenance(
            document_id="doc_aaaaaaaaaaaaaaaa", resolver=resolver(),
            configuration_fingerprint=HASH, input_fingerprint=HASH,
            semantic_taxonomy_version="bookforge-semantic-v1",
            flow_policy_version="v1", created_at=EPOCH,
        ),
    )
    value = AssemblyInput(
        metadata=BookMetadataV3(title_fragment_id=fid(1), language="vi", identifier="urn:part"),
        semantic_catalog=catalog, accepted_classifications=accepted_classifications(catalog),
        resolved_flow=flow,
    )
    model = BookAssembler().assemble(value)
    part = model.body[0]
    assert part.kind.value == "part"
    assert part.opening_fragment_ids == (fid(2),)
    assert [chapter.opening_fragment_ids for chapter in part.chapters] == [(fid(3),), (fid(4),)]
    assert part.break_intent is LogicalBreakIntent.NEW_PAGE
    assert part.chapters[0].break_intent is LogicalBreakIntent.NEW_PAGE
    # No source page field is consulted: the accepted M4 NONE survives verbatim.
    assert part.chapters[1].break_intent is LogicalBreakIntent.NONE


@pytest.mark.parametrize(
    "operation",
    [
        ContinuityType.JOIN_DIRECT,
        ContinuityType.JOIN_WITH_SPACE,
        ContinuityType.JOIN_WITH_NEWLINE,
        ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
    ],
)
def test_text_and_list_continuity_is_preserved_without_joining_text(operation: ContinuityType) -> None:
    value = minimal_input(paragraph_ids=(2, 3), continuity=operation)
    model = BookAssembler().assemble(value)
    selected = [edge for edge in model.continuity if edge.operation is operation]
    assert len(selected) == 1
    assert selected[0].left_node_id == fid(2)
    assert selected[0].right_node_id == fid(3)
    serialized = model.model_dump_json()
    assert "joined_text" not in serialized
    assert "comprehensive" not in serialized


def test_list_continuity_preserves_distinct_list_items() -> None:
    value = minimal_input(
        nodes=(
            text_node(1, SemanticType.BOOK_TITLE),
            text_node(2, SemanticType.LIST_ITEM),
            text_node(3, SemanticType.LIST_ITEM),
        ),
        paragraph_ids=(2, 3),
        continuity=ContinuityType.CONTINUE_LIST,
    )
    model = BookAssembler().assemble(value)
    assert any(edge.operation is ContinuityType.CONTINUE_LIST for edge in model.continuity)
    assert fid(2) in model.content.nodes and fid(3) in model.content.nodes


def test_missing_disposition_blocks_without_partial_model() -> None:
    value = minimal_input()
    flow = value.resolved_flow.model_copy(update={"inclusion_decisions": value.resolved_flow.inclusion_decisions[:-1]})
    invalid = value.model_copy(update={"resolved_flow": flow})
    report = BookAssembler().preflight(invalid)
    assert not report.ready
    assert AssemblyReadinessCode.INCOMPLETE_INCLUSION_DISPOSITION in {item.code for item in report.findings}
    with pytest.raises(AssemblyNotReadyError) as caught:
        BookAssembler().assemble(invalid)
    assert caught.value.report == report


def test_included_orphan_is_blocked() -> None:
    value = minimal_input(
        nodes=(text_node(1, SemanticType.BOOK_TITLE), text_node(2), text_node(3)),
        paragraph_ids=(2, 3),
    )
    chapter = value.resolved_flow.groups[1].model_copy(
        update={"member_fragment_ids": (fid(2),), "opening_fragment_ids": (fid(2),)}
    )
    flow = value.resolved_flow.model_copy(update={"groups": (value.resolved_flow.groups[0], chapter)})
    report = BookAssembler().preflight(value.model_copy(update={"resolved_flow": flow}))
    assert AssemblyReadinessCode.MISSING_OWNERSHIP in {item.code for item in report.findings}


def test_unsupported_included_blocks_but_explicit_exclusion_allows_assembly() -> None:
    drawing = UnsupportedSemanticNode(
        id=fid(3),
        content_kind=UnsupportedContentKind.DRAWING,
        evidence=({"source_id": sid(3), "kind": "drawing"},),
        reason_code="unsupported-drawing",
    )
    value = minimal_input(
        nodes=(text_node(1, SemanticType.BOOK_TITLE), text_node(2), drawing),
        paragraph_ids=(2, 3),
    )
    assert AssemblyReadinessCode.UNSUPPORTED_CONTENT in {
        item.code for item in BookAssembler().preflight(value).findings
    }
    decisions = tuple(
        decision.model_copy(update={"inclusion": InclusionType.EXCLUDE})
        if decision.target_fragment_id == fid(3)
        else decision
        for decision in value.resolved_flow.inclusion_decisions
    )
    chapter = value.resolved_flow.groups[1].model_copy(
        update={"member_fragment_ids": (fid(2),), "opening_fragment_ids": (fid(2),)}
    )
    flow = value.resolved_flow.model_copy(
        update={
            "ordered_fragment_ids": (fid(1), fid(2)),
            "groups": (value.resolved_flow.groups[0], chapter),
            "inclusion_decisions": decisions,
        }
    )
    excluded = value.model_copy(update={"resolved_flow": flow})
    assert BookAssembler().preflight(excluded).ready
    assert fid(3) in BookAssembler().assemble(excluded).content.nodes


def test_source_neutral_assembly_keeps_only_source_references_not_authoritative_text() -> None:
    model = BookAssembler().assemble(minimal_input())
    node = model.content.nodes[fid(2)]
    assert isinstance(node, TextSemanticNode)
    assert node.source_references == text_node(2).source_references
    serialized = model.model_dump_json()
    assert "Cà phê là một phần của văn hóa Việt Nam." not in serialized
    assert "regenerated_text" not in serialized


def test_large_book_1000_nodes_is_deterministic(capsys: pytest.CaptureFixture[str]) -> None:
    value = minimal_input(paragraph_ids=tuple(range(2, 1001)))
    started = perf_counter()
    first = BookAssembler().assemble(value)
    elapsed = perf_counter() - started
    second = BookAssembler().assemble(value)
    assert len(first.content.nodes) == 1000
    assert first.revision == second.revision
    print(f"M5A 1000-node assembly: {elapsed:.6f}s")
    assert capsys.readouterr().out


def test_assembly_package_has_no_source_renderer_or_ai_imports() -> None:
    from pathlib import Path

    source = Path("bookforge/assembly/assembler.py").read_text(encoding="utf-8")
    forbidden = ("bookforge.docx", "bookforge.pdf", "bookforge.epub", "openai", "ollama", "lxml")
    assert not any(item in source for item in forbidden)
