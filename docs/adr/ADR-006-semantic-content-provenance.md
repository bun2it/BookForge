# ADR-006: Typed semantic content and source-neutral provenance

- Status: Accepted
- Scope: semantic catalog, Assembly, and rendering inputs

## Decision

Contracts V3 replaces V2's all-text `SemanticFragment` catalog assumption with
a discriminated semantic-node catalog sharing `FragmentId` identity. Text,
figure, table, and unsupported content have typed provenance appropriate to
their evidence. Text keeps `SourceTextReference`; figures reference image and
asset identity; tables reference source tables and source-backed cells;
drawings remain explicit unsupported evidence.

## Rationale

An image/table/drawing is not authoritative text. Requiring a fake
`SourceTextReference` corrupts provenance, while arbitrary metadata would hide
an architectural requirement. A typed union lets M4 refer uniformly to logical
items and lets Assembly validate them without copying text or asset bytes.

## Consequences

- Caption text remains a separate source-backed semantic node.
- Asset bytes remain outside BookModel and are resolved by `AssetResolver`.
- Table rows/cells are accepted structured semantic data; Assembly does not
  reconstruct or merge them.
- Unsupported content must be excluded explicitly or block readiness; it never
  disappears silently.
