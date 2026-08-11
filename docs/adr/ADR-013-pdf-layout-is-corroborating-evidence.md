# ADR-013: PDF layout is corroborating visual evidence

- Status: Accepted
- Milestone: M6.0

## Context

The authoritative DOCX extraction can lose visual facts that a companion PDF
preserves, especially paragraph continuation across physical pages and the
proximity of figures and captions. Treating the PDF as a second content source
would create conflicting text/asset authority and would leak source pagination
into ebook flow.

## Decision

BookForge treats PDF layout as a corroboration-only side channel. PDF identity
is content-derived. Visual scanners return typed marker candidates with
reproducible provenance. A separate alignment layer maps those markers to DOCX
evidence references and records ambiguity or failure explicitly. A further
corroboration layer exposes observations to later semantic/flow owners.

Rendered page imagery is the intended input to the future provider-neutral
`PdfLayoutScanner`. Optional PDF text-layer hints are non-authoritative.
Provider/model runtime and model-specific response formats stay outside core
contracts. M6.0 uses fixture outputs and implements no heuristic scanner.

The scanner cannot reconstruct text/assets, create semantic nodes or
`BookModel`, emit EPUB, or decide final joins, page breaks, figure placement, or
caption association. M3 and M4 retain those decisions. M5 remains PDF-unaware.

## Consequences

- PDF evidence can corroborate layout without competing with DOCX authority.
- Physical PDF boundaries cannot silently become logical or EPUB boundaries.
- Alignment failures and ambiguity are preserved rather than guessed away.
- A future local multimodal model plugs in through one vendor-neutral protocol.
- Runtime PDF reading, rendering, model execution, alignment, and M3/M4 adapter
  work remain future milestones.
