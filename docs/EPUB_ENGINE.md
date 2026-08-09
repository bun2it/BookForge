# M1B Reflowable EPUB 3 Engine

## Boundary

M1B accepts active Contracts V2 `BookModel`, `EvidenceRegistry`, an explicit `AssetResolver`, and an output path. It emits an immutable `.epub` artifact. It does not import or inspect DOCX, OOXML, PDF, source pages, extraction geometry, AI results, or parser layout.

DOCX image anchor position is source evidence, not EPUB placement. Figure placement comes exclusively from fragment IDs in BookModel logical order. M1B never consults M1A anchors.

## Reflowable philosophy

The package is EPUB 3 reflowable content. XHTML follows logical chapters/sections and reader-controlled typography. It contains no fixed pages, absolute coordinates, fixed viewport, source fonts, or page-per-source-page splitting.

## Authoritative text

V2 `BookContentCatalog` maps every logical `FragmentId` to a typed `SemanticFragment`. The renderer follows:

```text
BookModel logical FragmentId
  -> BookContentCatalog SemanticFragment
  -> SourceTextReference
  -> EvidenceRegistry
  -> frozen raw evidence text
  -> escaped XHTML
```

BookModel contains semantic structure and references, never regenerated authoritative text. Missing evidence is fatal. Reclassifying a semantic fragment changes markup but cannot change raw text.

Join behavior is explicit and applies before a referenced segment after the first: `DIRECT`, `SPACE`, `NEWLINE`, and `REMOVE_TRAILING_HYPHEN` are honored. `DEFER` is fatal because boundary resolution has not completed. Hyphen removal fails if the preceding segment has no trailing hyphen/soft hyphen; the renderer does not guess.

When a reference resolves to `RawRun`, explicit bold, italic, superscript, subscript, and underline evidence maps to `strong`, `em`, `sup`, `sub`, and the `.underline` CSS class. Source fonts and arbitrary Word typography are ignored.

## Package structure

```text
mimetype                         first, ZIP_STORED
META-INF/container.xml
EPUB/package.opf
EPUB/nav.xhtml
EPUB/styles.css
EPUB/text/cover.xhtml            optional
EPUB/text/title.xhtml
EPUB/text/front_matter.xhtml     optional
EPUB/text/chapter_NNN.xhtml
EPUB/text/back_matter.xhtml      optional
EPUB/images/image_NNNNNN.ext
```

Internal names are controlled by the builder. ZIP timestamps are fixed at 1980-01-01, entry order is fixed, `dcterms:modified` is `1980-01-01T00:00:00Z`, and manifest/spine/image IDs are deterministic. Identical inputs produce byte-identical EPUBs and SHA-256 values.

## Semantic XHTML

- title/chapter title -> `h1`
- section hierarchy -> `h2` through `h6`
- paragraph -> `p`
- heading -> `h2`
- quote -> `blockquote`
- note/tip/footnote -> `aside`
- list -> `ol` or `ul`; related contiguous list items -> `li`
- figure -> `figure` and `img`
- linked, immediately following caption -> `figcaption`
- logical table -> `table`, `tr`, `th`/`td`, `rowspan`, `colspan`

Linked captions and list items must be contiguous in logical order. Non-contiguous structure is rejected instead of silently reordered. `UNKNOWN` and `ARTIFACT` logical fragments are not renderable.

All content is XML-escaped and UTF-8. Vietnamese and Unicode punctuation are preserved.

## CSS

CSS is intentionally small and uses normal flow and relative sizing. Images have `max-width: 100%` and `height: auto`. Tables use collapsed borders and a horizontally scrollable wrapper on narrow screens. No fonts are embedded and no device viewport is assumed.

## Cover and images

Cover packaging occurs only when `BookMetadata.cover_reference` is explicit. No cover detection occurs. The original bytes are preserved, the image receives `cover-image` manifest metadata, and cover XHTML precedes the title page in the spine. Books without covers remain valid.

Figures resolve only `SemanticFigure.source_image_id` through `AssetResolver`. Assets are deduplicated by reference, copied once, and assigned deterministic internal names. MIME type comes from the resolved file extension. Original filenames never become internal paths. Empty `alt` is used when no explicit string `alt_text` exists in semantic metadata; M1B never invents descriptions.

## Tables

Only typed `SemanticTable` data is rendered. Serialized row/cell order is retained. Header flags, row spans, and column spans are rendered when explicit. Missing cells are not invented. Visual fallback is not implemented; unsupported logical table strategies require a later explicit feature rather than fabricated HTML.

## Navigation and spine

`nav.xhtml` is generated from chapter titles and nested section titles in BookModel. Chapters without explicit titles remain in the spine but do not receive an invented TOC heading. Source page numbers and DOCX positions never affect navigation.

Spine order is deterministic: optional cover, title page, optional front matter, chapters in BookModel order, optional back matter. Only present structures are emitted.

## Artifact and validation

The final bytes are hashed with SHA-256. `ImmutableEpubArtifact` uses the checksum-derived artifact ID, fixed creation time, BookModel revision, resolved metadata snapshot, and deterministic structural-validation reference.

`StructuralEpubValidator` checks ZIP/mimetype rules, container/OPF/nav presence, unique manifest IDs, manifest targets, safe internal paths, spine references, XHTML XML parsing, and image references. This internal validation is not EPUBCheck and is never presented as official validation. Builder output is removed if internal validation fails.

`EpubCheckValidator` is optional. It uses a locally available `epubcheck` executable or an explicitly configured executable and never downloads a binary. Absence returns `FAIL` with `VALIDATOR_UNAVAILABLE`; execution failure returns `VALIDATOR_EXECUTION_FAILED`. Normal tests require no Java or EPUBCheck.

Example development validation after installing EPUBCheck separately:

```python
record = EpubCheckValidator().validate(artifact, epub_path)
```

## Security

Asset references that are empty, absolute, or contain `..` are rejected. Resolved paths must be files. Internal filenames are generated by BookForge, extensions are restricted, and structural validation rejects package references escaping the EPUB root.

## Unsupported M1B cases

- fixed-layout EPUB;
- media overlays, audio/video, scripting, MathML, SVG generation;
- CSS/font preservation from DOCX/PDF;
- table visual-fallback assets;
- non-contiguous linked captions/list items;
- unresolved `DEFER` joins;
- unknown image MIME types;
- AI-generated alt text/captions;
- semantic inference, source-anchor placement inference, or DOCX-to-EPUB wiring.
