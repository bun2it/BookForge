# ADR-014: PDF layout runtime and scan work units

- Status: Accepted
- Milestone: M6A

## Context

The frozen M6.0 contracts require bounded rendered visual inputs, deterministic
identity, provider replacement, validation, and long-book resume. The runtime
also needs one cross-platform rendering backend suitable for a desktop product.

## Decision

Use `pypdfium2` 5.x as the sole PDF runtime dependency. It provides PDFium page
access and rendering under Apache-2.0/BSD-3-Clause plus dependency licenses.
BookForge uses it only for source mechanics and full-page PNG rendering; it
does not use PDFium text, embedded-image, table, or semantic extraction.

Create deterministic page and adjacent page-pair work units. Their identities
cover source/page/render/scanner configuration but never scanner output,
confidence, completion order, or timestamp. Work units invoke the existing
`PdfLayoutScanner`; no second provider interface is introduced.

Persist source facts, renders, units, results, failures, and manifest beneath a
dedicated `pdf_layout/` workspace using atomic writes. Revalidate cached results
before reuse and process incrementally.

## Consequences

- Rendered PNGs are scanner inputs, never book assets.
- Physical page boundaries remain source facts, never EPUB break intent.
- Fixture scanners can qualify runtime without fake visual intelligence.
- A future local multimodal adapter replaces the fixture by implementing the
  frozen protocol; reader/workspace/work-unit architecture stays unchanged.
- Distributions must include applicable PDFium/dependency license notices.
- Real model scanning, DOCX alignment, and M3/M4 integration remain deferred.
