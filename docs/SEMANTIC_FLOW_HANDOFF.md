# M4.8 Typed Semantic-to-Flow Handoff

M4.8 removes the historical runtime bottleneck where M4 accepted only textual
`SemanticFragment` values. Contracts V3 remains active: the existing
`SemanticContentNode` union is the source-neutral M3-to-M4 representation.

Accepted text projects to `TextSemanticNode` with the same deterministic
sequence `FragmentId` used by historical materialization. Authoritative text
remains exclusively `SourceTextReference -> EvidenceRegistry -> Raw Evidence`.
Accepted FIGURE/TABLE projects only from explicitly targeted RawImage/RawTable
evidence. Figure asset bytes are not loaded or changed; table cells remain
source-referenced. Accepted drawing artifact/decorative states may project to
`UnsupportedSemanticNode`. UNKNOWN non-text evidence remains unresolved.

Historical textual `SemanticFragment` remains supported by the same resolver.
Runtime text is resolved only for text-bearing nodes.

`FlowResolverInput.accepted_logical_lists` carries upstream accepted
`LogicalListV3` truth. M4 validates and copies it; it never derives list kind,
order, membership, nesting, or start value from adjacency or source layout.
`StructuralRegionAssignment` explicitly assigns nodes to FRONT, BODY, or BACK.
Input order remains authoritative within each region; final region order is
front -> body -> back. M4 materializes typed matter groups/transitions without
position, style, page, or anchor inference.

Typed payload, list truth, and region truth participate in input and final-flow
fingerprints. Work-unit IDs remain tied to stable target identity, so resume can
retain local identity while rejecting stale decisions.

M4.8 adds no LLM, PDF logic, EPUB behavior, or M5C orchestration.
