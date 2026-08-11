from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from bookforge.contracts.assembly import (
    AssemblyProvenance,
    BookContentCatalogV3,
    BookMetadataV3,
    BookModelV3,
    ChapterV3,
    LogicalContinuityV3,
    assembly_revision_for_state,
)
from bookforge.contracts.flow import (
    ContinuityType,
    LogicalBreakIntent,
    LogicalListId,
    LogicalListKind,
    LogicalListV3,
    ResolvedContentFlow,
)
from bookforge.contracts.ids import flow_decision_id, flow_group_id, logical_list_id
from bookforge.contracts.semantic import SemanticType

from tests.contracts.test_m45_assembly_contracts import HASH, fid, text_node
from tests.contracts.test_m46_contract_hardening import flow as resolved_flow_fixture


def lid(value: str) -> LogicalListId:
    return LogicalListId(f"list_{value * 20}")


def logical_list(
    value: str,
    members: tuple[int, ...],
    *,
    kind: LogicalListKind = LogicalListKind.UNORDERED,
    parent_list_id: LogicalListId | None = None,
    parent_item: int | None = None,
    segments: tuple[int, ...] = (),
    start_value: int | None = None,
) -> LogicalListV3:
    return LogicalListV3(
        list_id=lid(value),
        kind=kind,
        member_fragment_ids=tuple(fid(item) for item in members),
        source_segment_fragment_ids=tuple(fid(item) for item in segments),
        parent_list_id=parent_list_id,
        parent_item_fragment_id=fid(parent_item) if parent_item is not None else None,
        start_value=start_value,
    )


def continuity(left: int, right: int) -> LogicalContinuityV3:
    return LogicalContinuityV3(
        left_node_id=fid(left),
        right_node_id=fid(right),
        operation=ContinuityType.CONTINUE_LIST,
        source_decision_id=flow_decision_id(
            decision_kind="continue-list",
            fragment_ids=[str(fid(left)), str(fid(right))],
            input_fingerprint=HASH,
            configuration_fingerprint=HASH,
            policy_version="v1",
        ),
    )


def book(
    lists: tuple[LogicalListV3, ...],
    *,
    node_types: dict[int, SemanticType] | None = None,
    content: tuple[int, ...] = (2, 3, 4),
    edges: tuple[LogicalContinuityV3, ...] = (),
) -> BookModelV3:
    types = node_types or {1: SemanticType.BOOK_TITLE, 2: SemanticType.LIST_ITEM, 3: SemanticType.LIST_ITEM, 4: SemanticType.LIST_ITEM}
    nodes = {fid(value): text_node(value, semantic_type) for value, semantic_type in types.items()}
    return BookModelV3(
        revision="asm_1234567890abcdef1234",
        metadata=BookMetadataV3(title_fragment_id=fid(1), language="vi", identifier="urn:list"),
        body=(
            ChapterV3(
                id=flow_group_id("chapter", 1),
                break_intent=LogicalBreakIntent.NONE,
                content_fragment_ids=tuple(fid(item) for item in content),
            ),
        ),
        content=BookContentCatalogV3(nodes=nodes),
        continuity=edges,
        logical_lists=lists,
        provenance=AssemblyProvenance(
            document_id="doc_aaaaaaaaaaaaaaaa",
            semantic_catalog_fingerprint=HASH,
            accepted_classification_fingerprint=HASH,
            resolved_flow_fingerprint=HASH,
            assembly_policy_fingerprint=HASH,
        ),
    )


@pytest.mark.parametrize("kind", [LogicalListKind.UNORDERED, LogicalListKind.ORDERED])
def test_three_item_list_has_explicit_kind_membership_and_order(kind: LogicalListKind) -> None:
    value = logical_list("a", (2, 3, 4), kind=kind)
    model = book((value,))
    assert model.logical_lists[0].kind is kind
    assert model.logical_lists[0].member_fragment_ids == (fid(2), fid(3), fid(4))


def test_logical_list_id_is_deterministic_and_sensitive_to_order() -> None:
    arguments = dict(kind="ordered", member_fragment_ids=[str(fid(2)), str(fid(3))])
    first = logical_list_id(**arguments)
    assert first == logical_list_id(**arguments)
    assert first != logical_list_id(kind="ordered", member_fragment_ids=[str(fid(3)), str(fid(2))])
    assert first.startswith("list_") and len(first) == 25


def test_empty_and_duplicate_members_are_rejected() -> None:
    with pytest.raises(ValidationError):
        logical_list("a", ())
    with pytest.raises(ValidationError, match="member IDs must be unique"):
        logical_list("a", (2, 2))


def test_missing_and_non_list_item_members_are_rejected() -> None:
    with pytest.raises(ValidationError, match="LIST_ITEM"):
        book((logical_list("a", (9,)),))
    with pytest.raises(ValidationError, match="LIST_ITEM"):
        book(
            (logical_list("a", (2,)),),
            node_types={1: SemanticType.BOOK_TITLE, 2: SemanticType.PARAGRAPH},
            content=(2,),
        )


def test_item_cannot_belong_to_conflicting_lists() -> None:
    with pytest.raises(ValidationError, match="only one logical list"):
        book((logical_list("a", (2, 3)), logical_list("b", (3, 4))))


def test_member_order_must_follow_final_reading_order() -> None:
    with pytest.raises(ValidationError, match="member order"):
        book((logical_list("a", (3, 2, 4)),))


def test_continue_list_endpoints_must_share_one_logical_list() -> None:
    accepted = book((logical_list("a", (2, 3, 4)),), edges=(continuity(2, 3),))
    assert accepted.continuity[0].source_decision_id
    with pytest.raises(ValidationError, match="one logical list"):
        book(
            (logical_list("a", (2,)), logical_list("b", (3, 4))),
            edges=(continuity(2, 3),),
        )


def test_source_segment_must_be_explicit_list_node() -> None:
    types = {
        1: SemanticType.BOOK_TITLE,
        2: SemanticType.LIST_ITEM,
        3: SemanticType.LIST_ITEM,
        4: SemanticType.LIST_ITEM,
        5: SemanticType.LIST,
    }
    accepted = book((logical_list("a", (2, 3, 4), segments=(5,)),), node_types=types, content=(5, 2, 3, 4))
    assert accepted.logical_lists[0].source_segment_fragment_ids == (fid(5),)
    with pytest.raises(ValidationError, match="source segments"):
        book((logical_list("a", (2, 3, 4), segments=(2,)),))


def test_nested_list_is_explicit_and_acyclic() -> None:
    parent = logical_list("a", (2, 5))
    child = logical_list("b", (3, 4), parent_list_id=parent.list_id, parent_item=2)
    model = book(
        (parent, child),
        node_types={
            1: SemanticType.BOOK_TITLE,
            2: SemanticType.LIST_ITEM,
            3: SemanticType.LIST_ITEM,
            4: SemanticType.LIST_ITEM,
            5: SemanticType.LIST_ITEM,
        },
        content=(2, 3, 4, 5),
    )
    assert model.logical_lists[1].parent_item_fragment_id == fid(2)


def test_invalid_parent_item_and_nesting_cycle_are_rejected() -> None:
    parent = logical_list("a", (2, 5))
    with pytest.raises(ValidationError, match="parent item"):
        book(
            (parent, logical_list("b", (3, 4), parent_list_id=parent.list_id, parent_item=4)),
            node_types={
                1: SemanticType.BOOK_TITLE,
                2: SemanticType.LIST_ITEM,
                3: SemanticType.LIST_ITEM,
                4: SemanticType.LIST_ITEM,
                5: SemanticType.LIST_ITEM,
            },
            content=(2, 3, 4, 5),
        )
    first = logical_list("a", (2,), parent_list_id=lid("b"), parent_item=3)
    second = logical_list("b", (3,), parent_list_id=lid("a"), parent_item=2)
    with pytest.raises(ValidationError, match="cycle"):
        book((first, second), content=(2, 3))


def test_list_cannot_cross_structural_containers() -> None:
    base = book((logical_list("a", (2, 3)),), content=(2, 3))
    chapters = (
        ChapterV3(
            id=flow_group_id("chapter", 1), break_intent=LogicalBreakIntent.NONE,
            content_fragment_ids=(fid(2),),
        ),
        ChapterV3(
            id=flow_group_id("chapter", 2), break_intent=LogicalBreakIntent.NONE,
            content_fragment_ids=(fid(3),),
        ),
    )
    with pytest.raises(ValidationError, match="structural containers"):
        BookModelV3.model_validate({**base.model_dump(), "body": [item.model_dump() for item in chapters]})


def test_ordered_start_is_explicit_and_unordered_start_is_rejected() -> None:
    ordered = logical_list("a", (2, 3, 4), kind=LogicalListKind.ORDERED, start_value=3)
    assert book((ordered,)).logical_lists[0].start_value == 3
    with pytest.raises(ValidationError, match="unordered"):
        logical_list("a", (2,), start_value=2)


def test_json_round_trip_is_deterministic_and_contains_no_item_text() -> None:
    model = book((logical_list("a", (2, 3, 4)),))
    payload = model.model_dump_json()
    restored = BookModelV3.model_validate_json(payload)
    assert restored == model
    assert restored.model_dump_json() == payload
    list_payload = json.dumps(model.logical_lists[0].model_dump(mode="json"), sort_keys=True)
    assert "text" not in list_payload
    assert "SourceTextReference" not in list_payload
    for item_id in model.logical_lists[0].member_fragment_ids:
        assert model.content.nodes[item_id].source_references  # type: ignore[union-attr]


def test_resolved_flow_carries_accepted_logical_list_truth() -> None:
    base = resolved_flow_fixture((1, 2, 3), (1, 2, 3))
    value = logical_list("a", (2, 3), kind=LogicalListKind.ORDERED)
    flow = ResolvedContentFlow.model_validate(
        {**base.model_dump(mode="json"), "logical_lists": [value.model_dump(mode="json")]}
    )
    restored = ResolvedContentFlow.model_validate_json(flow.model_dump_json())
    assert restored.logical_lists == (value,)


def test_assembly_revision_includes_logical_list_truth() -> None:
    unordered = book((logical_list("a", (2, 3, 4)),))
    ordered_list = logical_list("b", (2, 3, 4), kind=LogicalListKind.ORDERED)

    def revision(lists: tuple[LogicalListV3, ...]) -> str:
        return assembly_revision_for_state(
            metadata=unordered.metadata,
            front_matter=unordered.front_matter,
            body=unordered.body,
            back_matter=unordered.back_matter,
            content=unordered.content,
            continuity=unordered.continuity,
            logical_lists=lists,
            provenance=unordered.provenance,
        )

    assert revision(unordered.logical_lists) == revision(unordered.logical_lists)
    assert revision(unordered.logical_lists) != revision((ordered_list,))
