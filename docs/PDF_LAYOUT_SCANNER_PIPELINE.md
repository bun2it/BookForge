# M6B PDF Visual Scanner Result Pipeline

## Ownership

M6B validates, reconciles, indexes, and persists structured visual observations
returned through the frozen `PdfLayoutScanner` protocol. It owns no scanner
intelligence. DOCX remains authoritative for book text, images, tables, and
rendering; PDF scanner output remains corroborating visual evidence.

M6B never creates Raw Evidence, `SourceTextReference`, semantic nodes, flow
operations, `BookModel`, or EPUB content. It never opens a rendered PNG or PDF
to rediscover visual structure. M6C owns PDF↔DOCX alignment and M6D owns the
later source-neutral M3/M4 evidence adapter.

## Scanner-result lifecycle

```text
M6A page/page-pair work unit
  -> PdfLayoutScanner
  -> immutable PdfLayoutScanResult
  -> per-unit validation
  -> cross-result reconciliation
  -> deterministic PdfLayoutObservationCatalog
  -> M6C alignment input
```

Every accepted result must match the current work unit's PDF/page identities,
input fingerprint, scanner identity, and scanner fingerprint. Stale results are
excluded. Operational exceptions and malformed output remain failures; they
are never converted to UNKNOWN observations.

Fixture scanners used by tests map deterministic inputs to predefined typed
results. They do not inspect PNG bytes, PDF text, typography, indentation,
geometry patterns, or whitespace. A future local multimodal adapter follows the
same protocol and validation path; local model output is never implicitly
trusted.

## Catalog and visual topology

`PdfLayoutObservationCatalog` is frozen, deterministic, derived state. Scanner
result files remain the auditable source; deleting only the catalog and
rebuilding produces identical JSON and fingerprint.

The catalog stores one canonical copy of each accepted line region, image
region, visual paragraph group, and observation. Page and boundary indexes hold
only stable IDs. Page topology orders explicit regions by `visual_order`; it
does not infer order from coordinates. Two distinct regions cannot claim the
same page/order position.

Catalog ordering is physical page number, explicit visual order, then stable
identity. Completion order and timestamps have no effect.

Visual paragraph groups retain scanner-supplied membership. Same-page groups
reference only page lines. A cross-page group may span exactly two adjacent
pages and must reference the reader-owned physical boundary. M6B creates no
paragraph object and no join.

Paragraph-end, new-paragraph, heading, list, table, caption, repeated-header/
footer, and continuation observations remain candidate signals. Caption
candidates require explicit line and image-region references. Cross-page
continuation requires visual lines on both boundary pages and the exact
physical-boundary ID. Confidence and typed reason codes are preserved without
threshold acceptance.

`PdfImageRegion` records geometry/order only and contains no image bytes.
Images without caption candidates are valid. Optional line alignment text hints
remain non-authoritative and are persisted unchanged for future M6C use.

## Reconciliation and conflicts

Region and marker identity is scanner-owned within the frozen format:

- same ID and byte-equivalent typed payload across page/page-pair results is
  deterministic shared identity and is deduplicated;
- same ID with different geometry, membership, type, or payload is a typed
  conflict;
- page-pair output cannot redefine page-local region geometry;
- unknown regions/pages/boundaries and non-adjacent cross-page groups fail;
- duplicate explicit visual order positions fail rather than being repaired.

M6B performs no semantic conflict resolution and introduces no ad-hoc merging.

## Fingerprint, coverage, and readiness

The catalog fingerprint covers PDF bytes/identity, render configuration,
scanner identity/fingerprint, ordered accepted-result fingerprints, canonical
page/boundary indexes, coverage, and alignment-readiness findings. A source,
render, scanner, or result change rebuilds a different catalog while unrelated
PDF source identity remains stable.

Coverage reports total/scanned pages and page pairs, regions, groups,
observations, UNKNOWN observations, empty successful results, and failed work
units. A developer page-range scan is explicitly partial; it never claims full
PDF coverage.

Alignment-input readiness means only:

- `READY`: all page and adjacent-pair work completed, including valid empty or
  UNKNOWN results;
- `PARTIAL`: some valid evidence exists but coverage/failures are incomplete;
- `BLOCKED`: no accepted scanner work exists.

This is not semantic, flow, assembly, or book readiness.

## Persistence and resume

M6A's manifest records the exact current work-unit IDs so M6B rebuild cannot
accidentally consume older work left by another render/scanner configuration.
The derived catalog is atomically persisted as:

```text
pdf_layout/catalog/observations.json
```

`PdfLayoutCatalogBuilder.build()` catalogs an in-memory M6A run and optionally
persists it. `PdfLayoutCatalogBuilder.rebuild()` loads only the current manifest
inventory and validated result JSON. `PdfLayoutWorkspace.load_catalog()` reads
the derived artifact. Catalog deletion never reinvokes the scanner.

Cataloging loads structured JSON only, not rendered page pixels, so its memory
use scales with marker data rather than page-image size.

## M6C and future convergence

M6C can consume ordered pages/lines, visual paragraph groups, physical
boundaries, image/caption candidates, structural observations, optional
non-authoritative hints, and complete scanner provenance without rescanning.

The future high-level path is:

```text
DOCX authoritative extraction
  -> PDF visual scanner
  -> M6C alignment
  -> M6D corroboration into M3/M4
  -> book-level review/convergence
  -> user review where required
  -> BookModel -> EPUB -> final QA
```

That loop is not implemented in M6B. Even in later milestones, PDF observations
may refine decisions but can never mutate DOCX Raw Evidence, EvidenceRegistry,
or authoritative `SourceTextReference` content.
