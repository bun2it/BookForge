# ADR-015: Scanner results are immutable visual evidence

- Status: Accepted
- Milestone: M6B

## Context

Page and page-pair scanners can emit overlapping region identities. M6C needs
one deterministic, rebuildable view without allowing derived indexes to replace
auditable scanner results or silently reconcile contradictions.

## Decision

Persist each validated `PdfLayoutScanResult` unchanged and derive one frozen
`PdfLayoutObservationCatalog`. The catalog owns indexes and coverage only.
Identical repeated IDs are shared/deduplicated; the same ID with a different
typed payload is a conflict. Explicit `visual_order` determines page topology;
geometry is never used to infer missing order.

Catalog fingerprinting covers source, render/scanner configuration, accepted
result fingerprints, indexes, and readiness. M6A manifests inventory the exact
current work-unit IDs so rebuild excludes stale result files. Catalog writes
are atomic and deletion/rebuild does not reinvoke the scanner.

## Consequences

- Page-pair output cannot silently redefine page-local regions.
- Empty and UNKNOWN results remain successful evidence states; operational
  failures remain separate.
- Partial scans produce partial alignment-input readiness.
- M6C receives ordered, provider-neutral visual evidence without reopening PDF
  or PNG inputs.
- A future local model uses the same protocol and validation/catalog path.
- No PDF text/asset authority, DOCX alignment, M3/M4 decision, or EPUB behavior
  is introduced.
