# ADR-010: Typed semantic-to-flow handoff

## Status

Accepted — M4.8

## Context

M3A materialized only textual `SemanticFragment`, although Contracts V3 already
defined source-neutral text, figure, table, and unsupported nodes. M4A could not
receive accepted non-text truth, populate explicit list truth, or receive
explicit front/back ownership.

## Decision

Retain Contracts V3. M4 consumes the existing `SemanticContentNode` union and
continues accepting historical textual fragments through the same resolver.
Non-text nodes never receive fake `SourceTextReference`.

Explicit `LogicalListV3` and FRONT/BODY/BACK assignments enter M4 as accepted
upstream truth. M4 validates/materializes but does not infer them. Node order
controls order within a region; final region order is front, body, back.
Typed payload, list truth, and region truth are fingerprinted while work-unit
identity remains based on stable targets.

## Consequences

The historical text API remains compatible. Accepted non-text semantics, lists,
and matter ownership can reach Assembly mechanically. UNKNOWN remains explicit.
M5C is not introduced by this decision.
