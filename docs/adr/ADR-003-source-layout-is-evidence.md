# ADR-003: Source layout is evidence

- Status: Accepted
- Scope: Source extraction, semantic processing, flow, and EPUB rendering

## Decision

Physical source layout is evidence, not final ebook structure:

```text
PDF page break    != EPUB page break
DOCX image anchor != EPUB figure placement
source typography != semantic truth
```

PDF coordinates/pages, DOCX anchors/layout, styles, font sizes, and alignment may be preserved and considered during semantic and flow processing. They do not directly control BookModel structure or EPUB rendering.

## Rationale

BookForge produces reflowable reading structure, not a pixel reproduction of print pages. Source-layout signals can be useful but are ambiguous: a floating image anchor may be a Word layout artifact, a large font may not be a chapter, and a physical page break may divide one logical paragraph.

## Consequences

- Extraction preserves layout evidence without semantic classification.
- M3 may use layout as classification evidence but cannot decide final breaks/placement.
- M4 resolves logical continuity and placement.
- M1B renders only BookModel order and never reinterprets DOCX/PDF layout.
