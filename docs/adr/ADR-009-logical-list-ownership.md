# ADR-009: Logical List Ownership

## Status

Accepted for M5B.1.

## Context

Semantic LIST/LIST_ITEM classification does not determine identity, membership,
order, kind, continuation, or nesting. A renderer cannot derive those facts
from adjacency or source layout without taking ownership from M4.

## Decision

Logical lists are top-level flow structure represented by `LogicalListV3` in
`ResolvedContentFlow` and `BookModelV3`. M3 owns classification; M4 owns final
grouping/order/continuation; M5A materializes it; M5B renders it.

Membership/order, ordered/unordered kind, optional starting ordinal, and nesting
are typed. Item text remains exclusively source-backed. CONTINUE_LIST audit
edges must agree with final list identity.

Contracts V3 is retained because the fields are additive and default empty.

## Consequences

Renderers need no DOCX numbering ID, indentation, glyph, PDF coordinate, or
source page. M5A/M5B.2 runtime adaptation remains required. Multi-block items
and per-item ordinal overrides remain unsupported until explicitly contracted.
