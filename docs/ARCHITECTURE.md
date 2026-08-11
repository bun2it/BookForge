# BookForge V1 Architecture

Contracts V3 deterministic assembly is documented in
[`BOOK_ASSEMBLY.md`](BOOK_ASSEMBLY.md). It consumes accepted semantic and flow
truth and emits `BookModelV3`; rendering remains a separate downstream stage.

> [`PRINCIPLES.md`](PRINCIPLES.md) contains BookForge's normative engineering invariants. This document is descriptive architecture documentation; implementations must comply with the normative principles.

## Scope

BookForge is a Windows and macOS desktop product that reconstructs PDF and DOCX documents as reflowable EPUB 3 books. Milestone M0 defines contracts only: it contains no parser, AI inference, EPUB renderer, persistence, delivery integration, UI, OCR, or Microsoft Word automation.

Image-only/scanned PDF and OCR are outside V1. A user may manually use Microsoft Word to turn a PDF into DOCX before importing it, but Word is outside BookForge.

## Module-first pipeline

```text
PDF  -> PDF evidence extractor  --+
                                +-> raw evidence -> semantic fragments
DOCX -> DOCX evidence extractor --+        -> boundary resolution
                                          -> continuous content flow
                                          -> source-independent BookModel
                                          -> EPUB builder -> validation
                                          -> Library -> optional delivery
```

Modules communicate only through typed, versioned contracts. Parser objects cannot cross the raw-evidence boundary. Downstream modules must not import PyMuPDF, WordprocessingML, or source-specific layout types.

The M1A implementation of the DOCX evidence boundary is documented in [`DOCX_EXTRACTION.md`](DOCX_EXTRACTION.md).

The independent Contracts V2 EPUB renderer is documented in [`EPUB_ENGINE.md`](EPUB_ENGINE.md).

M5B adds a native Contracts V3 renderer without downgrading `BookModelV3`.
Logical break intent drives deterministic XHTML resource planning; source pages
and source anchors remain non-authoritative. See [`EPUB_ENGINE.md`](EPUB_ENGINE.md)
and [ADR-008](adr/ADR-008-v3-epub-resource-partitioning.md).

M5B.1 adds typed logical-list truth at the M4 → Assembly → renderer boundary.
Membership, order, kind, continuation identity, and nesting are explicit while
item text remains source-backed. See [`LIST_CONTRACTS.md`](LIST_CONTRACTS.md)
and [ADR-009](adr/ADR-009-logical-list-ownership.md).

M5B.2 completes the mechanical list path: Assembly copies accepted M4 logical
lists and the V3 renderer emits native `ol`/`ul`/`li` from that catalog only.
No source numbering, indentation, adjacency, glyph, or layout inference occurs.

M4.8 makes the runtime semantic-to-flow handoff node-typed while retaining
historical text fragments. Explicit list and FRONT/BODY/BACK truth is validated
and materialized without source-layout inference. See
[`SEMANTIC_FLOW_HANDOFF.md`](SEMANTIC_FLOW_HANDOFF.md) and
[ADR-010](adr/ADR-010-typed-semantic-to-flow-handoff.md).

M4.9 adds explicit accepted flow reviews. Original, review, and replacement
remain separate; effective state controls unresolved inventory and inclusion
order. Region transitions no longer duplicate continuity edges. See
[`FLOW_REVIEWS.md`](FLOW_REVIEWS.md) and
[ADR-011](adr/ADR-011-accepted-flow-review-boundary.md).

M5C introduces the thin offline `PipelineRunner` that coordinates actual M1A,
M3A, M4A/M4.9, M5A, M5B, and validation without taking ownership of any stage
decision. See [`PIPELINE_INTEGRATION.md`](PIPELINE_INTEGRATION.md) and
[ADR-012](adr/ADR-012-deterministic-pipeline-orchestration.md).

The source-backed M3 classification boundary is documented in
[`SEMANTIC_CONTRACTS.md`](SEMANTIC_CONTRACTS.md). Its output describes what
evidence is and remains independent of flow, boundary, assembly, and rendering
decisions.

The deterministic, LLM-independent transport and resume layer for that boundary
is documented in [`SEMANTIC_PIPELINE.md`](SEMANTIC_PIPELINE.md). It builds
source-ordered work units and temporary analysis views, validates classifier
results, and checkpoints audit artifacts without changing Raw Evidence.

The typed M4 continuity, structural-boundary, logical-break, placement,
inclusion, grouping, and Assembly-handoff contracts are documented in
[`FLOW_BOUNDARY_CONTRACTS.md`](FLOW_BOUNDARY_CONTRACTS.md). M4 output is
`ResolvedContentFlow`, not BookModel or EPUB.

The deterministic M4A implementation is documented in
[`FLOW_RESOLVER.md`](FLOW_RESOLVER.md). It checkpoints independent local
decisions before a separate global grouping/order phase, consumes only accepted
M3 semantics, and emits conservative unresolved decisions when evidence is
insufficient. It has no LLM or renderer dependency.

M4.6 hardens the future Assembly boundary with explicit metadata, a persisted
FragmentId-to-classification association, deterministic reviewed semantic-node
materialization, and renderer-neutral continuity edges. M4 owns joins;
Assembly preserves them; a later V3 renderer executes them. See
[`ASSEMBLY_CONTRACTS.md`](ASSEMBLY_CONTRACTS.md) and
[ADR-007](adr/ADR-007-continuity-through-assembly.md).

Small protocols in `bookforge.contracts.interfaces` express dependency direction. They are ports, not working implementations and not a single oversized engine interface.

## Immutable source content

Raw evidence owns authoritative text. A `SemanticFragment` has one or more `SourceTextReference` values and deliberately has no `text` field. Unknown fields are rejected, making accidental AI-authored text invalid at the contract boundary.

Future AI may classify, group, order, associate, exclude artifacts, and help resolve ambiguity. It may not author book text. Rendering must retrieve text from referenced evidence. Raw evidence remains present even when an artifact is excluded from reading flow.

Raw evidence models are frozen. The contract-level `EvidenceRegistry` uniquely indexes textual evidence and resolves whole-source or half-open range references. It rejects duplicate IDs and strict lookups of missing evidence. Multiple references resolve as ordered segments; joining remains the responsibility of future boundary/flow logic.

## PDF pages and incremental state

A PDF page is a bounded processing/checkpoint unit, not an EPUB page. `PageFragment` records ordered semantic results for one source page. Page numbers and coordinates may remain as provenance, but `ContentFlow` contains only logical fragment order and structural relationships.

`BookState` is the compact resumable context between pages: open structures, recent references, and learned profiles. It must never contain the entire book text. A checkpoint records completed page IDs, references to saved page fragments, the latest state, versions, and processing configuration. Persistence and job execution are deferred.

## Boundaries and continuous flow

M3 classification produces immutable, fingerprinted decisions over source
evidence. It may label chapter-like text, captions, figures, tables, recurring
headers/footers, page numbers, decorative content, or uncertainty. It does not
emit joins, logical breaks, final grouping, caption associations, or figure
placement. Those remain M4 and Book Assembly responsibilities.

`BoundaryOperation` can describe paragraph/hyphen/list/table continuation, caption association, structural boundaries, no-op, and unresolved outcomes. It always refers to evidence or semantic IDs for active operations. The resolver is deferred.

After resolution, `ContentFlow` is the continuous ebook reading order. Physical X/Y positions and source pagination are allowed only in earlier evidence/provenance, not as flow semantics.

M4.0's additive `ResolvedContentFlow` is the complete typed handoff for future
Book Assembly. It keeps continuity, structural transition, logical break,
placement/association, and inclusion decisions orthogonal. Assembly follows its
logical order and groups without inspecting source anchors/pages or repeating
semantic inference.

## Book and artifact ownership

Contracts V3 is the active future Assembly output. `BookModelV3` contains one
ordered part/chapter hierarchy and a source-neutral typed semantic-node catalog.
Authoritative text still resolves through `SourceTextReference` and
`EvidenceRegistry`. V1 and V2 remain historical contracts; the frozen M1B
renderer continues to accept V2 only until a separately approved adaptation.
No automatic migration engine exists. See [`ASSEMBLY_CONTRACTS.md`](ASSEMBLY_CONTRACTS.md).

EPUB is the primary immutable artifact. `ImmutableEpubArtifact` is a frozen value containing path reference, size, checksum, BookModel revision, metadata snapshot, and optional validation reference. A build creates an artifact; validation appends a separate record.

The Library owns catalog/edition history and references artifacts. It does not generate or mutate EPUBs. Persistence is deferred.

Delivery is optional post-processing. A provider receives an immutable EPUB artifact, delivery profile, and preflight result—not `BookModel`. Delivery failure or unknown confirmation cannot mutate/delete the EPUB. `UNKNOWN` is distinct from `SENT`. No Amazon mechanism is selected or implemented in M0; a future provider may use only an officially supported mechanism available at implementation time.

## Versioning and migration policy

Every persisted/inter-module model includes `schema_version`, defaulting to `1`. Producers write the version they implement. Consumers must reject unsupported versions rather than guess.

Future schema changes should be classified as:

- additive and backward compatible: optional field or enum-safe extension;
- breaking: renamed/removed fields, changed meaning, or new invariant.

Breaking changes increment the schema version and require an explicit, tested migration at the owning boundary. Migrations must preserve source references and artifact checksums; migration infrastructure is not part of M0.

## Serialization

Contracts use Pydantic v2 and deterministic field ordering. Major contracts support JSON round trips. Datetimes are timezone-aware values in examples/tests, enums serialize to stable string values, and arbitrary extra fields are rejected.
