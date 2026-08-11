# M1B/M5B Reflowable EPUB 3 Engine

## Contracts V3 native rendering

M5B adds `EpubV3Builder` beside the historical V2-only `EpubBuilder`. The V3
path consumes `BookModelV3`, `EvidenceRegistry`, `AssetResolver`, and an output
path directly. It never downgrades V3 to V2. Low-level asset packaging,
deterministic ZIP behavior, CSS foundations, structural validation, and the
optional EPUBCheck adapter remain shared. Existing V2 behavior and tests remain
unchanged.

V3 semantic dispatch is explicit for `TextSemanticNode`,
`FigureSemanticNode`, and `TableSemanticNode`. An included
`UnsupportedSemanticNode` fails with `UnsupportedV3ContentError`. Text always
resolves through `SourceTextReference -> EvidenceRegistry`; concatenated text
exists only as temporary render state and XHTML output.

### Resource planning and breaks

V3 uses deterministic `segment_NNN.xhtml` resources. A logical component with
`NEW_PAGE` starts a new resource when prior rendered content exists. A component
with `NONE` stays in the current resource, including `CHAPTER + NONE`,
`SECTION + NONE`, and `SUBSECTION + NONE`. This separates logical hierarchy
from XHTML partitioning and avoids the historical contradiction caused by
unconditional one-file-per-chapter splitting. `NEW_PAGE` resources also carry
the complementary `.logical-break-page` class:

```css
break-before: page;
page-break-before: always;
```

No PDF/DOCX page or source layout field is inspected. There is currently no
arbitrary technical size split; one can be introduced later only as a
non-visual compatibility partition. See ADR-008.

PART opening content renders before its chapters. Empty untitled PARTs create
no empty document; their titled chapters appear at the surrounding nav level.
Untitled chapters remain in spine order but receive no fabricated nav label.
PART/chapter/section labels come only from explicit accepted heading nodes.
Spine follows generated segment order, never filename or source order.

### Continuity execution

The renderer builds an O(1) outgoing-edge index and runtime-only text render
groups. It executes `JOIN_DIRECT`, `JOIN_WITH_SPACE`, `JOIN_WITH_NEWLINE`, and
`JOIN_REMOVE_TRAILING_HYPHEN` without modifying nodes or evidence. Newline uses
`<br/>`. Hyphen removal deletes only an actual terminal hyphen or soft hyphen;
absence is a typed `InvalidContinuityError`. Chains are supported, cycles and
local-order contradictions fail, and inline `RawRun` formatting remains around
its original source segment.

`CONTINUE_TABLE` combines already-typed row sequences into one rendered table;
it never invents rows or cells and rejects incompatible explicit column
extents. Table spans and header flags remain explicit.

### V3 list contract blocker

Contracts V3 identify `LIST`/`LIST_ITEM` and allow `CONTINUE_LIST`, but
`TextSemanticNode` contains neither list membership nor ordered/unordered list
semantics. Therefore correct list rendering cannot be derived deterministically.
M5B deliberately fails list-family nodes with `UnsupportedV3ContentError`
instead of guessing paragraphs or unordered lists. The smallest future contract
correction is typed list data containing list ID/type and ordered member IDs (or
equivalent explicit membership) while retaining source references on items.

M5B.1 now supplies that additive contract as `LogicalListV3`; see
[`LIST_CONTRACTS.md`](LIST_CONTRACTS.md). Rendering intentionally remains
disabled for list-family nodes without this final catalog.

M5B.2 renders only `BookModelV3.logical_lists`. It indexes list IDs, members,
source segments, and parent-item children once. A root list renders at its first
catalog-owned position; its members and segments are consumed so items never
render again as standalone paragraphs. Ordered lists use `<ol>`, unordered lists
use `<ul>`, and items use `<li>`. Explicit `start_value` becomes `ol start`;
the default emits no unnecessary attribute.

Nested lists are recursively placed inside their explicit parent `<li>` at any
valid depth. LIST source segments are placement triggers only and their marker
text is not emitted as an item. CONTINUE_LIST remains audit evidence, not text
concatenation. Text JOIN between catalog list items is rejected because the
supported model defines one textual fragment per item.

### Figures, captions, covers, and assets

Figure position is its V3 logical position. Asset resolution uses the explicit
image `EvidenceReference.asset_reference`, never a source filename or DOCX
anchor. Bytes are copied unchanged and deduplicated by asset reference. Because
V3 currently has no explicit alt-text field, figures use the documented safe
empty-alt policy; no description is generated.

Accepted caption association comes from `FigureDataV3.caption_fragment_id`.
Caption and figure must be adjacent in logical order. Caption-before-figure is
rendered as `figcaption` before `img`; figure-before-caption retains the inverse
order. Covers are packaged only from `BookMetadataV3.cover_reference`.

### Defensive errors and M5C handoff

Renderer-level checks reject missing evidence/assets, unsupported nodes,
invalid continuity, invalid caption adjacency, incompatible continued tables,
unsafe asset references, and missing navigation targets. They do not rerun M5A
preflight or repair the logical model. ZIP paths and filenames remain controlled
by BookForge.

M5C may connect a qualified deterministic M3/M4/M5A handoff to
`EpubV3Builder`; M5B itself performs no DOCX/PDF traversal or end-to-end
orchestration.

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
