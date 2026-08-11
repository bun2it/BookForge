# M6A PDF Page and Visual Work-Unit Runtime

## Purpose and authority

M6A opens an optional original PDF, derives deterministic source/page facts,
renders bounded scanner inputs, invokes the frozen provider-neutral
`PdfLayoutScanner`, validates typed results, and checkpoints each page or
adjacent page pair. It performs no semantic interpretation, DOCX alignment, or
M3/M4 integration.

DOCX remains authoritative for text, book images, tables, and final rendering.
PDF renders exist only under `pdf_layout/renders/` as scanner inputs. They do
not enter `EvidenceRegistry`, `AssetResolver`, `BookModelV3`, or EPUB.

## Backend and geometry

The runtime uses `pypdfium2` 5.x, currently qualified with 5.12.1. It supplies
one offline PDFium-backed dependency for file validation, page access,
dimensions, rotation, and rasterization. Its Apache-2.0/BSD-3-Clause licensing
is more suitable for a desktop product than a strong-copyleft rendering
dependency; packaged products must still ship PDFium dependency licenses.

`PdfPageEvidence.width` and `height` are visible page dimensions in PDF points
(normally 1/72 inch) in displayed orientation. Runtime `PdfRuntimePage` records
the source rotation separately as 0/90/180/270 degrees. Mixed-size documents
are supported per page. M6A calls no text, embedded-image, table, or OCR
extraction API.

## Deterministic identity and rendering

- PDF identity derives from SHA-256 of source bytes, independent of path,
  filename, mtime, workspace, render configuration, or scanner.
- Page identity derives from PDF identity and one-based physical page number.
- Each adjacent physical boundary is a deterministic source fact; it contains
  no logical or EPUB break.
- Render fingerprint covers PDF identity, page identity, backend version, and
  the complete render configuration.
- Scanner work input fingerprint additionally covers rendered inputs and
  scanner fingerprint.

The default render is full-page, RGB, opaque white-background PNG at 144 DPI,
with annotations enabled. DPI is bounded to 72–300. PDFium applies stored page
orientation; M6A does not crop or semantically transform pages. PNG encoding
is deterministic, contains no timestamps/metadata, and is written atomically.
Changing render configuration changes render/work-unit fingerprints without
changing PDF/page/boundary identities.

## Work units and scanner boundary

Each selected page creates one page work unit. Each adjacent selected pair
creates one page-pair work unit and references its physical boundary. A
single-page PDF therefore creates one page unit and zero pair units. Debug page
ranges must be non-empty and contiguous; they never alter source identity.

Both unit types build the frozen `PdfLayoutScanInput`: one or two page records,
relative rendered PNG references, optional physical boundary, and input
fingerprint. They contain no `BookModel`. The scanner output is only frozen
`PdfLayoutScanResult` regions and visual markers.

M6A tests use a mapping-like fixture scanner that constructs predefined output
from deterministic IDs. It never opens or inspects a page image and contains no
font-size, whitespace, indentation, rectangle, or other detection heuristic.

Every result is rejected when its source/page/input/scanner fingerprint is
wrong, a region references another page, geometry falls outside page bounds, a
marker references an unknown region/boundary, or IDs conflict. Structured
reason codes are allowed; prose reasoning and chain-of-thought are not stored.
Operational failure is separate from a valid UNKNOWN/empty-marker result.

## Workspace, atomic writes, and resume

Given an existing document workspace, M6A writes:

```text
pdf_layout/
  source.json
  manifest.json
  pages/<page-id>.json
  boundaries/<boundary-id>.json
  renders/<render-fingerprint>.png
  renders/<render-fingerprint>.json
  work_units/<work-unit-id>.json
  results/<work-unit-id>.json
  failures/<work-unit-id>.json
```

The original PDF is referenced once by explicit path and checksum; it is not
copied into each stage. JSON and PNG writes use same-directory temporary files,
`fsync`, and atomic replacement. Cached PNG bytes are checked against their
persisted checksum; scanner results are reused only after complete validation
against the current work unit. Source bytes, render configuration,
scanner configuration/model fingerprint, or page input changes generate new
dependent identities or fail validation as stale.

Pages are read/rendered one at a time and cached on disk. Work units are
executed sequentially and persisted independently, so a late failure preserves
earlier valid results. Scheduling can become parallel later without changing
unit identity or serialized page order.

## Future local multimodal scanner

A future `LocalVisionScannerAdapter` receives exactly the same bounded page or
page-pair PNG references, page geometry/identity, optional physical boundary,
configuration, and optional future non-authoritative hints. It returns typed
visual markers only. It receives no BookModel or accepted semantic/flow truth
and cannot return authoritative book text.

The final local-LLM milestone may add the real provider adapter/model runtime.
M6C owns PDF↔DOCX alignment, and M6D owns source-neutral corroboration
integration with M3/M4. Those milestones require no reader, workspace, or
work-unit redesign.

M6B now catalogs validated results through the separate derived pipeline in
[`PDF_LAYOUT_SCANNER_PIPELINE.md`](PDF_LAYOUT_SCANNER_PIPELINE.md). The M6A
manifest inventories exact current work-unit IDs so catalog rebuild ignores
stale files from older configurations.
