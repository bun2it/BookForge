# BookForge Contract Catalog

> Contracts implement the authority, traceability, and explicit-evolution rules defined normatively in [`PRINCIPLES.md`](PRINCIPLES.md). Contract consumers must preserve source-text authority, referential traceability, and versioned contract evolution; they must not introduce hidden workarounds.

All contracts are Pydantic v2 models under `bookforge/contracts`, forbid unknown fields, and support JSON serialization. Most source/evidence contracts remain at schema version 1. `BookModelV3` and `BookContentCatalogV3` are the active future Assembly contracts; historical `BookModel` V2 remains the frozen M1B input. IDs are opaque stable strings; producers must not encode business logic that consumers need to parse from an ID.

| Contract group | Owner / producer | Primary consumers | Invariants |
|---|---|---|---|
| Common primitives | Architecture | Every module | Valid bounding-box ordering; explicit source and stage provenance |
| Source references | Source/evidence layer | Semantic, renderer | References authoritative evidence; ranges are complete and ordered; joining is deferred |
| Raw evidence | PDF/DOCX extractors | Semantic analyzer | Evidence only; source-specific data is optional/metadata; no semantic labels |
| Semantic fragments | Semantic analyzer | Boundary, flow, inspector | At least one source reference; no authoritative/generated text; relationships use stable IDs |
| ClassificationResult/Review | Semantic analyzer/reviewer | M3 QA, later acceptance | Immutable source-backed decision; deterministic fingerprints; no flow decisions or authoritative text |
| PageFragment | Page analyzer | Checkpoint, boundary | Ordered fragments for a processing page, never an EPUB page |
| BookState | State updater | Incremental analyzer | Compact and serializable; references rather than full book text |
| BoundaryOperation | Boundary resolver | Flow normalizer, QA | Active operations reference source or fragment IDs; unresolved is explicit |
| ContentFlow | Flow normalizer | Book assembler | Logical reading order only; no physical page/layout dependency |
| ResolvedContentFlow | M4 Flow/Boundary | Book Assembly | Final logical order plus typed continuity, grouping, break, placement, association, and inclusion decisions; no book text or EPUB state |
| BookModel | Book assembler | EPUB builder, inspector | Source-format independent; chapter/section content references semantic fragments |
| SemanticTable | Table analyzer | Flow, EPUB strategy | Missing cells need not be invented; strategy is declarative only |
| SemanticFigure | Visual analyzer | Flow, EPUB strategy | Source image remains traceable; keep/drop/review is explicit |
| ArtifactClassification | Artifact analyzer | Flow, QA | Exclusion never deletes raw evidence |
| Job/progress | Runtime coordinator | CLI/UI | Explicit lifecycle and non-negative progress values |
| ProcessingCheckpoint | Runtime coordinator | Resume runtime | Document/version/config, completed pages, latest state, and fragment references |
| EngineEvent | Runtime coordinator | Future Tauri bridge | JSON serializable; event type and job ID always present |
| ValidationRecord | Validator | Library, UI, delivery preflight | PASS/PASS_WITH_WARNINGS/FAIL and structured findings; no validation execution in M0 |
| ImmutableEpubArtifact | EPUB builder | Validator, Library, Delivery | Frozen metadata; valid SHA-256; delivery cannot mutate it |
| LibraryBook/Edition | Library service | UI/export/delivery | Edition references source, BookModel revision, artifact, validation, delivery history |
| Delivery records | Delivery provider/coordinator | Library/UI | Provider receives artifact, not BookModel; UNKNOWN never implies SENT |

## Stable IDs

Stable IDs derive from immutable source order and document content, never database rows or semantic/AI classification. Numeric order is one-based and zero-padded to a minimum width; larger values may exceed that width. IDs are unique within one document namespace.

| Object | Format | Example |
|---|---|---|
| Document | `doc_<first 16 lowercase hex of source SHA-256>` | `doc_2cf24dba5fb0a30e` |
| PDF page | `p<page:04>` | `p0007` |
| PDF paragraph/block/image/drawing/table | `<page>_<par/b/img/drw/tbl><order:04>` | `p0007_b0003` |
| DOCX body paragraph/image/drawing/table | `docx_<p/img/drw/tbl><body-order:06>` | `docx_p000123` |
| Run | `<parent-text-id>_r<order:04>` | `docx_p000123_r0004` |
| Table row | `<table-id>_row<order:04>` | `docx_tbl000008_row0002` |
| Table cell | `<row-id>_c<order:04>` | `docx_tbl000008_row0002_c0003` |
| Semantic fragment | `sem_f<flow-order:06>` | `sem_f000042` |
| Boundary operation | `bnd<operation-order:06>` | `bnd000017` |
| Semantic classification | `cls_<first 20 hex of decision-input SHA-256>` | `cls_0123456789abcdefabcd` |
| Classification review | `rev_<first 20 hex of review-input SHA-256>` | `rev_0123456789abcdefabcd` |
| Flow decision | `fld_<first 20 hex of decision-input SHA-256>` | `fld_0123456789abcdefabcd` |
| Flow decision review | `fdr_<first 20 hex of review-input SHA-256>` | `fdr_0123456789abcdefabcd` |
| Logical flow group | `flow_<kind>_<order:04>` | `flow_chapter_0003` |

PDF object order is deterministic extractor order within a page. DOCX body order is deterministic XML body traversal order; nested order is within its stable parent. A collision must fail rather than gain a random suffix. Re-extracting identical content with identical traversal produces identical IDs. `ids.py` owns construction and validation; zero order and unknown formats are rejected.

## Raw evidence

`RawDocument` can contain document-ordered objects and/or `RawPage` records. `RawTextBlock`, `RawParagraph`, `RawRun`, `RawImage`, `RawDrawing`, `RawTable`, rows/cells, and artifact candidates preserve evidence available from their source. Geometry and page numbers are optional when DOCX cannot provide them. `source_metadata` carries explicit source-specific evidence without forcing fake parity between PDF and DOCX.

Every raw object has an explicit literal `kind`. `RawObject` is a Pydantic discriminated union on that field, so deserialization never guesses from optional fields and unknown kinds fail. Raw evidence is frozen; tuple containers protect nested ordered textual evidence. Processing/job state remains mutable.

## Source text references

`SourceTextReference` points to one evidence object and may include an offset range. Both offsets must be present together. A missing range means the complete authoritative text. A supplied range is Python-style half-open `[start_offset, end_offset)`: start included, end excluded. Construction enforces `0 <= start <= end`; resolution additionally enforces `end <= len(source_text)`. Empty ranges are valid. References contain no text copy.

Join behavior is declarative: direct concatenation, space, newline, trailing-hyphen removal, or defer. `resolve_many` returns ordered segments without applying joining policy.

## Evidence Registry

`EvidenceRegistry` is an in-memory contract service, not persistence or parser logic. It registers frozen `RawTextBlock`, `RawParagraph`, `RawRun`, and `RawTableCell` objects by stable `SourceId`. It provides `contains`, strict `get`, `resolve_text`, and ordered `resolve_many`. Duplicate IDs raise `DuplicateEvidenceIdError`, missing IDs raise `UnknownEvidenceIdError`, and invalid resolved ranges raise `InvalidSourceTextRangeError`. Registration never overwrites evidence silently.

## Semantic and relationships

`SemanticType` includes title, author, chapter number/title, heading, paragraph, list/list item, figure, caption, table, quote, note, tip, footnote, artifact, and unknown. Relationships express caption, membership, footnote, anchor, and continuation links. Semantic metadata may hold non-authoritative analysis details only.

M3.0 adds an additive semantic taxonomy and immutable
`ClassificationResult`/`ClassificationReview` contracts without changing
BookModel V2. They record source target identity, authoritative text references
where applicable, confidence/candidates, review state, rationale codes,
classifier identity, fingerprints, taxonomy version, and provenance. They carry
no source text copy, flow operation, final placement, or checkpoint state. See
[`SEMANTIC_CONTRACTS.md`](SEMANTIC_CONTRACTS.md).

## BookModel version history

Contracts V1 is historical. V1 `BookModel` contained logical `FragmentId` references but no semantic catalog, so a renderer could not deterministically resolve those IDs to `SemanticFragment`, `SemanticFigure`, or `SemanticTable` values.

Contracts V2 is the historical renderer contract. V2 added the required `BookContentCatalog` containing typed fragment, figure, and table maps. `BookModel` and `BookContentCatalog` both serialize with `schema_version: 2`. V2 validates that all logical references exist, catalog keys match object IDs, figure/table types are correct, captions resolve, and figure/table entries are not orphaned.

M3.0 remains an additive Contracts V2 extension. It does not justify a V3 bump:
no V2 field is renamed/removed, no existing meaning changes, and no V2 invariant
is weakened. Semantic taxonomy versioning is separate from schema versioning.

V2 still contains no authoritative regenerated text. Each `SemanticFragment` carries only `SourceTextReference` values; consumers resolve them through `EvidenceRegistry` to frozen raw evidence. Logical order comes only from V2 front matter, chapters, sections, and back matter. Parser page geometry and DOCX image anchors are not logical placement instructions.

No automatic V1-to-V2 migration engine exists yet. A future assembler/migration must supply the semantic catalog and pass V2 referential-integrity validation; it must never synthesize missing source text.

Contracts V3 is active for future Book Assembly. V3 introduces one ordered
`body` union of parts and ungrouped chapters, preserves logical break intent on
the hierarchy, and replaces the all-text fragment assumption with typed text,
figure, table, and unsupported semantic nodes. These changes are breaking:
serialized V2 books cannot acquire PART ownership or clean non-text provenance
without information not present in V2. V2 remains supported by the frozen M1B
renderer. There is no V2-to-V3 automatic migration. See
[`ASSEMBLY_CONTRACTS.md`](ASSEMBLY_CONTRACTS.md), [ADR-005](adr/ADR-005-book-assembly-boundary.md),
and [ADR-006](adr/ADR-006-semantic-content-provenance.md).

M4.6 is hardening within Contracts V3. Assembly input now requires
`BookMetadataV3` and an explicit `AcceptedClassificationCatalog` keyed by
`FragmentId`. `BookModelV3` adds a default-empty typed continuity catalog so
accepted M4 joins survive Assembly without merging nodes or copying text.
Existing V3 hierarchy/catalog meaning remains coherent, so V4 is not required.
Classification reviews may snapshot base input fingerprint and taxonomy for
stale-review validation. See [ADR-007](adr/ADR-007-continuity-through-assembly.md).

M4.7 additively completes Assembly readiness/error vocabulary within V3. Seven
new enum values distinguish hierarchy, ownership, inclusion-disposition,
figure-placement, caption-association, and referential-integrity failures.
`AssemblyNotReadyError.report` exposes the complete immutable typed report.
Existing V3 codes, findings, reports, and serialization retain their meaning.

M5B.1 additively introduces `LogicalListV3` on `ResolvedContentFlow` and
`BookModelV3`: deterministic identity, ordered/unordered kind, ordered
LIST_ITEM membership, optional source segments, explicit nesting, and optional
ordered start value without copied text. Contracts V3 remains active. See
[`LIST_CONTRACTS.md`](LIST_CONTRACTS.md) and
[ADR-009](adr/ADR-009-logical-list-ownership.md).

## Table, figure, and artifact decisions

`SemanticTable` records source-backed rows/cells, spans when known, header evidence, confidence, and a preferred future rendering strategy. `SemanticFigure` records a source image, optional caption/anchor, dimensions, classification, confidence, and keep/drop/review. `ArtifactClassification` records evidence and an explicit exclusion flag without removing it.

## M4 flow and boundary decisions

M4.0 additively defines `LogicalBoundaryDecision`, `LogicalGroup`,
`FigurePlacement`, `CaptionAssociation`, `InclusionDecision`, auditable review,
and `ResolvedContentFlow`. Continuity, structural boundary, logical break,
placement/relationship, and inclusion are independent typed dimensions.

Text/list joins reference authoritative source text; table continuation
references source table evidence without inventing cells. Flow decisions carry
resolver identity, confidence/review state, reason codes, input/config
fingerprints, taxonomy/policy versions, and deterministic IDs. They contain no
authoritative regenerated text, source-specific mandatory layout, BookModel,
or EPUB packaging fields. Historical `BoundaryOperation` and `ContentFlow`
remain unchanged. See [`FLOW_BOUNDARY_CONTRACTS.md`](FLOW_BOUNDARY_CONTRACTS.md)
and [ADR-004](adr/ADR-004-logical-flow-and-break-ownership.md).

## Processing and events

Jobs support pending, running, paused, completed, failed, and cancelled. Progress supports stage, pages, units, elapsed time, and optional ETA. Checkpoints are storage-neutral. Events cover job/stage/page/progress/warning/checkpoint/completion/failure and are suitable for a future JSON IPC bridge; M0 provides no IPC.

## Artifacts, Library, and delivery

Build artifacts use a relative reference and SHA-256 identity. Metadata is snapshotted so title, authors, language, identifier, cover, and TOC identity remain inspectable without reopening the book model.

A `LibraryEdition` may exist while building and therefore has an optional EPUB artifact. Once built/validated, higher-level services must enforce state-transition requirements; no database or state machine is implemented here.

`DeliveryProfile` contains public configuration and only a reference to secrets. `PreflightReport`, `DeliveryRecord`, and appendable `DeliveryAttempt` capture post-build activity. Status `UNKNOWN` is required when confirmation is unavailable. Provider protocols accept `ImmutableEpubArtifact`; they have no authority to rebuild content.

## Interfaces

The protocols are `SourceExtractor`, `SemanticAnalyzer`, `BoundaryResolver`, `FlowNormalizer`, `BookAssembler`, `EpubBuilder`, `BookValidator`, and `DeliveryProvider`. Each exposes only its boundary operation. They intentionally contain no implementation, orchestration, persistence, or giant `BookForgeEngine` facade.

## Consumer validation and compatibility

Consumers should validate JSON using the concrete expected contract, then check supported `schema_version`. Missing required references, invalid enums/geometry/checksums, and unknown fields fail validation. A consumer must not repair invalid data silently. Future migrations belong to the contract owner and must be explicit and lossless with respect to source provenance.
