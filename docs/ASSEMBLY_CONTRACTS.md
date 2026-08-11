# M4.5 Book Assembly Contract Freeze

M5B.1 additively permits `LogicalListV3` catalogs on accepted M4 flow and
`BookModelV3`. The catalog references source-backed LIST_ITEM nodes and
participates in deterministic revision identity. M5A runtime materialization is
deferred; this contract-only hardening does not reopen the frozen assembler.
See [`LIST_CONTRACTS.md`](LIST_CONTRACTS.md).

## Purpose and boundary

Book Assembly is the mechanical boundary between accepted semantic/flow state
and the final logical book:

```text
accepted M3 state + ResolvedContentFlow + admission policy
  -> readiness preflight
  -> future mechanical Assembly
  -> immutable BookModelV3
```

M4.5 defines contracts and preflight only. It contains no assembler. Assembly
does not classify, infer, join text, reconstruct tables, choose figures,
inspect raw layout, name XHTML files, or render EPUB. It never receives DOCX
anchors, drawing coordinates, PDF page geometry, font heuristics, XHTML, nav,
spine, CSS, or ZIP state as commands.

## Version decision

Contracts V3 is required. V2 has two semantic limitations that cannot be fixed
additively without two competing truths:

1. its top-level `chapters` list cannot represent PART ownership, part-opening
   content, or a mixed ordered sequence of parts and ungrouped chapters;
2. its catalog requires every `SemanticFragment` to carry text references,
   while figures, source tables, and drawings are not text evidence.

V1 remains historical (logical references without a catalog). V2 remains the
historical/current renderer input supported by the frozen M1B implementation.
V3 is the active Assembly output contract. There is no automatic migration.
A later V2-to-V3 migration must be explicit, must obtain missing hierarchy and
non-text provenance, and must never synthesize authoritative text.

## One logical ordering truth

`BookModelV3.body` is one ordered discriminated sequence of `PartV3` and
ungrouped `ChapterV3`. A part exclusively owns its ordered chapters. There is
no parallel flat chapter list. PART opening fragments and content precede the
part's first chapter. A semantic node may be owned only once across front
matter, body hierarchy, and back matter.

Officially supported structures are chapter-only books, part/chapter books,
mixed ordered parts and ungrouped chapters, front/body/back matter, and
matter-only/chapter-less books. A chapter may be untitled but must own content
or sections. A part title/opening is optional, but a part must own at least one
chapter. No title is invented.

`PartV3`, `ChapterV3`, and `SectionV3` preserve renderer-neutral
`LogicalBreakIntent`. The contract distinguishes PART/NEW_PAGE,
CHAPTER/NEW_PAGE, SECTION/NONE, and SUBSECTION/NONE. `NEW_PAGE` is logical
reader-break intent, never a source page number or EPUB filename.

## Typed semantic content and provenance

The common identity of anything in logical flow remains `FragmentId`.
`BookContentCatalogV3.nodes` is a discriminated union:

- `TextSemanticNode` has authoritative `SourceTextReference` values and
  matching TEXT evidence identities;
- `FigureSemanticNode` has IMAGE evidence, immutable asset reference, and
  figure data;
- `TableSemanticNode` has TABLE evidence and pre-existing row/cell structure;
- `UnsupportedSemanticNode` preserves unsupported DRAWING/other evidence.

This replaces fake text references for non-text content. No node stores source
text, joined text, generated text, image bytes, or reconstructed content.
Text still resolves only through `SourceTextReference -> EvidenceRegistry ->
Raw Evidence`. Figure bytes resolve through source image/asset identity and the
existing implementation-layer `AssetResolver`. Captions are separate textual
CAPTION nodes. Table cell text remains source-referenced; Assembly neither
copies nor merges cells.

Unsupported drawings cannot enter renderable V3 reading order. They must stay
as typed unsupported catalog evidence, be explicitly excluded by M4, or block
strict admission. Silent renderer omission is invalid.

## Reviews and admission

There are exactly two admission modes:

- `STRICT`: every decision required by the input must already be resolved;
- `REVIEWED`: the same rule, plus classifications marked NEEDS_REVIEW must have
  an explicit review.

There is no permissive guessing mode. Optional relationships may only be
omitted when upstream contracts explicitly make them non-required; omission
does not erase their audit state.

Original M3/M4 decisions remain immutable. A flow override is a separate typed
replacement plus `FlowDecisionReview`. Effective-state selection requires one
active review per original, a known original/replacement, the same decision
type and target fragments, and a matching upstream input fingerprint. Dangling,
conflicting, wrong-target, wrong-type, or stale reviews block readiness. No
timestamp wins conflicts.

`AssemblyReadinessReport` is the deterministic preflight boundary. Blocking
findings include unresolved required flow, missing semantic nodes, unsupported
content, missing asset provenance (rejected at catalog construction), dangling
or conflicting reviews, invalid/stale replacements, and required unreviewed
classifications. Logical hierarchy is validated when `BookModelV3` is
materialized. Typed future runtime errors mirror these categories.

M4.7 completes the typed readiness vocabulary with distinct codes for invalid
hierarchy, duplicate ownership, missing ownership, incomplete inclusion
disposition, unresolved figure placement, unresolved caption association, and
referential-integrity failure. The enum code owns failure semantics;
`reference_id` only identifies the affected object. In particular,
`INVALID_CONTINUITY`, `MISSING_SEMANTIC_CONTENT`,
`MISSING_ASSET_PROVENANCE`, and `UNSUPPORTED_CONTENT` must not be used as
generic buckets for unrelated preflight failures.

`AssemblyNotReadyError(report)` preserves the exact immutable
`AssemblyReadinessReport` through its typed `report` property. Its deterministic
message is informational; callers inspect `error.report`, never parse the
message or rely on `exception.args` for contract state.

## Input, output, identity, and integrity

M4.6 hardens `AssemblyInput` with required `BookMetadataV3`, the typed semantic
catalog, an explicit `AcceptedClassificationCatalog` mapping every
`FragmentId` to its accepted `ClassificationResult`, classification reviews,
`ResolvedContentFlow`, replacement decisions, and assembly policy. Metadata is
input truth: Assembly never infers title, language, identifier, publisher,
description, or cover. The title fragment must resolve to a source-backed
BOOK_TITLE/TITLE text node after review resolution.

The M3 acceptance/materialization boundary owns the fragment-to-classification
mapping. M4A's existing runtime mapping already follows this ownership; M4.6
makes it persistable and explicit for Assembly. Assembly never scans source
references to rediscover an association.

`EffectiveClassification` records fragment, base classification, optional
review, taxonomy, effective semantic type, and deterministic fingerprint. A
review must match base input fingerprint, taxonomy, source identity, and
original type. One active review is allowed. Text-to-text changes such as
PARAGRAPH to QUOTE update only semantic type and preserve references. Typed
node families are TEXT, FIGURE, TABLE, and UNSUPPORTED. Cross-family conversion
without the already-required target provenance is invalid; no node shape is
synthesized. FIGURE to DECORATIVE is therefore invalid for a FigureSemanticNode;
explicit M4 exclusion is the supported non-rendering decision.

Assembly does not need `EvidenceRegistry` to materialize hierarchy; text
resolution is a renderer/validation concern. It does not need `AssetResolver`;
catalog asset provenance is validated without reading bytes.

Future `BookAssemblerV3.assemble(AssemblyInput) -> BookModelV3` is the narrow
port. No god-object engine is introduced. Persistent group IDs reuse M4's
deterministic `flow_<kind>_<ordinal>` identity. `revision` is an
`asm_<20 hex>` content identity derived later from canonical accepted inputs,
not a clock or review timestamp.

`AssemblyProvenance` fingerprints the semantic catalog, accepted
classifications, resolved flow, policy, and document. V3 and its new nested
models are frozen. Referential validation covers hierarchy-to-catalog,
figure-to-image/asset, figure-to-caption, table-to-source evidence, and unique
content ownership. Catalog evidence may remain unowned only when it is
explicitly excluded or unsupported upstream; it is not silently deleted.

## Continuity through Assembly

M4.6 adds top-level `BookModelV3.continuity`, a tuple of immutable
`LogicalContinuityV3` edges. The hierarchy remains the only ordering truth;
continuity only annotates an ordered left/right pair with the accepted M4
operation and effective source decision ID. Nodes remain separate and no edge
contains joined, normalized, or merged text.

Persisted operations are KEEP_SEPARATE, JOIN_DIRECT, JOIN_WITH_SPACE,
JOIN_WITH_NEWLINE, JOIN_REMOVE_TRAILING_HYPHEN, CONTINUE_LIST, and
CONTINUE_TABLE. Text joins require two textual nodes. List continuation
requires LIST/LIST_ITEM text nodes. Table continuation requires two table
nodes and never merges rows. Targets must exist, be included, and be adjacent
in final hierarchy order. Thus an explicitly excluded footer between two source
paragraphs does not prevent their final adjacency. Non-separating continuity
cannot cross front/body/back, PART, CHAPTER, SECTION, or SUBSECTION containers.
Duplicate operations for one edge are rejected.

`materialize_effective_continuity` resolves zero-or-one valid flow review and
retains the accepted replacement decision ID. Later M5B resolves both nodes'
source references and executes the operation. Changing continuity changes the
canonical Assembly revision input while preserving node/source identity.

## Front and back matter audit

V2/V3 matter containers are structurally sufficient for ordered cover/title,
copyright, dedication, preface/foreword, generated TOC identity, appendix,
notes, bibliography, index, and about-author fragments. Semantic detection and
subtyping remain M3/M4 concerns. M4.5 adds no inference or speculative fields.

## M1B compatibility matrix

| Area | Current M1B | Later action |
|---|---|---|
| V2 chapter-only rendering | Supported unchanged | None |
| V3 typed text nodes | Not supported | Resolve V3 text-node references |
| PART opening/hierarchy | Not supported | Render part opening and ordered child chapters |
| logical NEW_PAGE | Not supported as first-class intent | Map intent to renderer-neutral XHTML/CSS boundary behavior |
| V3 figure/table nodes | V2 representation only | Adapt catalog access; keep AssetResolver/EvidenceRegistry ports |
| unsupported drawing | Rejects/does not model V3 | Fail visibly or require explicit exclusion |

M1B source and behavior are unchanged in M4.5. Before rendering V3 it needs a
separately approved adaptation. That adaptation must use BookModelV3 order and
break intent without semantic inference or source-layout inspection.

## Future implementation constraints

The future assembler must first require a ready report, resolve accepted
reviews deterministically, copy references and logical ownership mechanically,
validate V3, and stop on any typed failure. It must not inspect source layout,
guess unresolved decisions, generate titles/captions/text, merge table content,
or create any EPUB state.
