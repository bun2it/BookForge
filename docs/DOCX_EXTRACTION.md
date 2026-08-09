# M1A DOCX Evidence Extraction

## Boundary

`bookforge.docx.DocxExtractor` transforms a readable DOCX package into `RawDocument`, an `EvidenceRegistry`, copied image assets, and extraction warnings. It performs no semantic classification, page inference, flow normalization, ebook assembly, or rendering.

```text
DOCX bytes -> SHA-256/DocumentId -> safe OOXML read
           -> ordered raw evidence -> EvidenceRegistry
           -> deterministic debug JSON + original image bytes
```

## Package and traversal strategy

The extractor opens the source once as ZIP, requires `word/document.xml`, and parses XML with entity resolution and networking disabled. Invalid ZIP, missing main part, and non-recoverable XML failures become typed errors; no package repair is attempted.

The main story is traversed through direct `w:body` children. Only `w:p` and `w:tbl` are extracted; `w:sectPr` is configuration and other direct children generate warnings. This preserves interleaving such as paragraph → table → paragraph. Header/footer parts referenced by section properties are processed separately in first deterministic relationship appearance order and tagged with `story`, `part_name`, and `story_order` metadata.

IDs use Contracts V1 generators. Paragraph/table/image/drawing counters are deterministic across the main story followed by header/footer stories. Runs are ordered within their paragraph; rows within a table; cells within a physical row. A later semantic decision cannot change a raw ID.

Extraction provenance uses a fixed epoch timestamp so repeated extraction does not inject runtime time into serialized raw evidence.

## Paragraphs and runs

Each `w:p` becomes a frozen `RawParagraph`, including empty/image-only paragraphs. Paragraph style ID and alignment are evidence in `RawStyle`; they are never converted to title/heading/caption semantics.

Descendant `w:r` nodes are read in XML order without format-based merging. `RawRun` preserves text and direct bold, italic, underline, superscript, and subscript evidence. Paragraph text is the exact concatenation of extracted run text.

Explicit mappings are:

| OOXML element | Raw text character |
|---|---|
| `w:tab` | U+0009 tab |
| `w:br`, `w:cr` | U+000A line feed |
| `w:noBreakHyphen` | U+2011 non-breaking hyphen |
| `w:softHyphen` | U+00AD soft hyphen |

`w:t` Unicode, whitespace, and non-breaking spaces are retained. No punctuation, spelling, or global whitespace normalization occurs.

External hyperlinks preserve relationship ID, target, target mode, and internal anchor in run/paragraph metadata. Field instructions and field-character types are preserved with `resolved: false`; stored result text remains evidence, but BookForge does not evaluate PAGE, NUMPAGES, or other dynamic fields. Their presence produces `FIELD_PRESERVED_NOT_RESOLVED`.

Paragraphs and every run are registered as authoritative text evidence.

## Images and anchors

Each embedded `a:blip` referenced by `w:drawing` becomes `RawImage`. Image bytes are copied unchanged to:

```text
assets/docx_imgNNNNNN.<original extension>
```

The result records content type, original part/filename, byte count, SHA-256, relationship ID, run position, containing paragraph ID, placement (`inline`, `floating`, or `unknown`), and drawing extent in EMU/points when present. Repeated occurrences remain distinct source objects. No image decoding, resize, recompression, OCR, or keep/drop classification occurs.

Image objects appear immediately after their containing paragraph in `RawDocument.objects`; the paragraph also lists anchored object IDs. Run/drawing indices preserve the finer position inside the paragraph.

DrawingML without an embedded resolvable image becomes `RawDrawing` plus a warning. Legacy VML/OLE `w:pict`/`w:object` receives unsupported drawing evidence and a warning rather than disappearing.

## Tables

Each body `w:tbl` becomes a `RawTable` with physical `w:tr` rows and `w:tc` cells. No rectangular cells are invented. Cells carry authoritative text formed from direct cell paragraphs separated by a newline, row/column order, `gridSpan` where present, vertical-merge evidence in metadata, paragraph text evidence, and source part/story details. Every cell is registered in `EvidenceRegistry`.

Nested tables are detected but not expanded in M1A; a warning and count preserve this limitation. Images/drawings inside cells are flagged as metadata/warnings but not extracted as assets. Table style is source metadata only.

## Debug workspace

`extract(source, output_root)` writes:

```text
<output_root>/<document-id>/
├── source.json
├── raw_document.json
├── warnings.json
└── assets/
```

This workspace is inspect/debug output, not Library persistence. `python -m bookforge.docx.inspect SOURCE --output ROOT` exposes it to developers.

## Warning and error policy

Fatal typed errors:

- `InvalidDocxError`: unreadable ZIP/package XML or missing body;
- `MissingDocumentPartError`: missing required main document part;
- `UnsupportedDocxStructureError`: reserved for future required structures that cannot be safely represented.

Warnings preserve recoverable limitations: unsupported story child, unresolved/missing image relation or part, unsupported DrawingML/VML/OLE object, unresolved header/footer reference, dynamic field, nested table, and drawing inside a table cell.

## Unsupported M1A structures

- nested-table reconstruction;
- extraction of image assets located inside table cells;
- complete VML, SmartArt, chart, OLE, equation, text-box, and shape geometry;
- Word layout pagination and dynamically evaluated field values;
- tracked-change acceptance/rejection and comments/endnotes/footnotes;
- password-encrypted or damaged-package repair;
- remote/externally linked images.

These cases are not silently treated as ebook semantics. Evidence is retained where Contracts V1 allow it, otherwise a warning records the limitation.
