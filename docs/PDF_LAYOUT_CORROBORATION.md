# PDF Layout Corroboration (M6.0)

## Ownership boundary

M6.0 defines contracts only. It does not read or render PDFs, run OCR, call a
model, align a real document pair, or alter M3/M4/M5 behavior.

DOCX raw evidence remains the only authoritative source of book text and image
assets. PDF contributes corroborating visual/layout evidence. PDF text-layer
strings may be supplied as localization hints, but are explicitly
non-authoritative and cannot populate `EvidenceRegistry`, semantic text, or
EPUB content.

The three relevant notions are intentionally separate:

1. `PdfPhysicalPageBoundary` records a boundary in the source PDF.
2. `PdfVisualParagraphGroup` and `PdfVisualObservation` describe visual
   candidates around that boundary.
3. M4 remains the owner of logical joins/breaks; the EPUB renderer remains the
   executor of an approved logical break. A physical PDF page boundary never
   implies EPUB `NEW_PAGE`.

## Contract families

`pdf_layout.py` owns deterministic PDF/page identity, page and region geometry,
physical boundaries, typed visual markers, scanner input/result provenance, and
the provider-neutral `PdfLayoutScanner` protocol.

`layout_alignment.py` explicitly pairs one authoritative DOCX with one
corroborating PDF. Alignment targets use DOCX `SourceTextReference` ranges or
DOCX evidence IDs. The model supports many PDF lines to one DOCX paragraph, one
visual paragraph to multiple DOCX paragraphs, cross-page evidence, candidates,
ambiguity, mismatch, and unaligned outcomes. It does not copy authoritative
text into an alignment record.

`corroboration.py` exposes source-neutral observations suitable as additional
evidence for future M3/M4 adapters. Names remain candidates or observations;
they are not final semantic types, join operations, page breaks,
`FigurePlacement`, or `CaptionAssociation`.

All M6.0 models use the existing contract-model schema version default. This is
an additive contract family and does not change `BookModel` V3.

## Scanner provider abstraction

`PdfLayoutScanner.scan()` accepts a bounded rendered page or adjacent page-pair
view with deterministic page identity, optional non-authoritative alignment
hints, and a configuration fingerprint. It returns typed regions/markers and
provenance containing input, scanner/model, schema, and policy fingerprints.

The core protocol contains no Ollama-, OpenAI-, Gemini-, or model-specific JSON.
M6 tests use a fixture implementation and predefined marker output. M6.0 does
not add heuristic substitutes such as font-size-to-heading or whitespace-to-
paragraph rules.

Scanner outputs are schema-validated structured data. Core contracts retain
compact reason codes and scores, never chain-of-thought, free-form hidden
reasoning, or prose rationales.

The future final local-LLM milestone owns the real visual scanner adapter and
runtime. Its primary input is rendered page or page-pair imagery. That phase
should implement `PdfLayoutScanner` without redesigning these contracts or the
downstream M3/M4 evidence boundary.

## Future staged implementation

- M6A: deterministic PDF identity, page rendering/reference production, and
  checkpointing—without semantic interpretation. Implemented using the
  runtime described in [`PDF_LAYOUT_RUNTIME.md`](PDF_LAYOUT_RUNTIME.md).
- M6B: structured-marker validation and deterministic result cataloging using
  fixture outputs; no real scanner/model adapter. See
  [`PDF_LAYOUT_SCANNER_PIPELINE.md`](PDF_LAYOUT_SCANNER_PIPELINE.md).
- M6C: DOCX/PDF source pairing and alignment implementation.
- M6D: corroboration adapters consumed as non-authoritative evidence by M3/M4.

M5A/M5B remain PDF-unaware and continue to consume approved `BookModel`/EPUB
inputs only.

Future M3 adapters may translate aligned observations into bounded features
such as `VISUAL_HEADING_SIGNAL`, `CAPTION_PROXIMITY_SIGNAL`, or
`REPEATED_HEADER_SIGNAL`. Future M4 adapters may translate them into boundary
evidence such as `PHYSICAL_PAGE_BOUNDARY` or `SAME_VISUAL_PARAGRAPH`. These are
adapter-level evidence features; neither consumer imports parser/runtime types
or accepts a preselected final decision.
