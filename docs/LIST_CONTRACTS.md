# Logical List Contracts

## Status and version

M5B.1 retains Contracts V3. `ResolvedContentFlow.logical_lists` and
`BookModelV3.logical_lists` are additive and default empty, so historical V3
payloads retain their meaning. V2 is unchanged. The empty default provides
compatibility; it does not authorize a renderer to infer missing list truth.

## Model and ownership

LIST/LIST_ITEM classification and CONTINUE_LIST previously did not identify one
logical list, its ordered members, ordered versus unordered behavior, or nested
ownership. Adjacency, DOCX numbering IDs, indentation, bullet glyphs, PDF
coordinates, and arbitrary metadata cannot fill that gap at rendering time.

`LogicalListV3` is top-level logical flow structure in `ResolvedContentFlow` and
`BookModelV3`, not semantic text in `BookContentCatalogV3`. It contains only:

- deterministic `list_id`;
- explicit `ORDERED` or `UNORDERED` kind;
- authoritative ordered `member_fragment_ids`;
- optional source-backed LIST segment fragment IDs;
- optional parent-list and parent-item IDs;
- optional positive ordered-list `start_value`.

It contains no text, markers, indentation, source numbering identity, geometry,
or markup. Text remains:

`LogicalListV3 -> FragmentId -> LIST_ITEM TextSemanticNode -> SourceTextReference -> EvidenceRegistry -> Raw Evidence`

LIST_ITEM is the textual item identity. A LIST node, when present, is optional
source-backed segment evidence rather than the final structural container.

## Identity, order, and nesting

`logical_list_id()` hashes kind, ordered members, nesting identity, and optional
start value into `list_<20 lowercase hex>`. It uses no randomness, timestamp,
database identity, or source layout.

Member order must agree with final reading order. One item cannot belong to
multiple lists and one list cannot cross structural containers. Nested lists
are explicit and acyclic: a child supplies both `parent_list_id` and
`parent_item_fragment_id`, and the item must belong to the parent. Indentation
is never consulted.

Each item is currently one textual LIST_ITEM fragment, optionally owning a
child list. Multi-paragraph items and item-owned figures/tables are unsupported.

## CONTINUE_LIST

CONTINUE_LIST remains traceable in `BookModelV3.continuity`. Optional source
segment IDs associate source-backed LIST segments with the final list. When a
logical-list catalog exists, both CONTINUE_LIST endpoints must map to the same
list through member or segment identity. Contradictions fail validation.

M5B.2 mechanically emits one `<ol>`/`<ul>` from this catalog while preserving
continuity provenance. A source LIST segment is a placement trigger only; it is
consumed with the catalog list and is not emitted as another item or text block.

## Ordered-list policy

`start_value=None` means the ordinary start of one. A positive explicit value
supports another start. Unordered lists cannot define it. Per-item ordinal
overrides such as 1, 3, 7 are intentionally unsupported.

## Integrity and handoff

Validation rejects empty lists, duplicate IDs/members, conflicting membership,
missing or non-LIST_ITEM members, invalid LIST segments, wrong member order,
cross-container lists, unknown parents, invalid parent items, nesting cycles,
unordered start values, and contradictory CONTINUE_LIST endpoints.

M3 classifies LIST/LIST_ITEM. M4 must emit accepted LogicalListV3 truth. M5A
will later copy it mechanically and include it in revision identity. Runtime
adaptation is deferred because M5A is frozen in this contract-only milestone.
M5B.2 renders this frozen supported scope. List-family nodes without a complete
logical-list catalog still fail visibly.
