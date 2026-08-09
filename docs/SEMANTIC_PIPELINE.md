# M3A Deterministic Semantic Pipeline

## Purpose and boundary

M3A transports immutable Raw Evidence through semantic classification. It
provides deterministic work units, temporary analysis views, a vendor-neutral
classifier port, validation, source-referenced fragment materialization, and a
resumable audit workspace.

M3A performs no real semantic intelligence. It answers only **what is this?**
and deliberately contains no paragraph joining, chapter/part grouping, logical
break, final caption association, final figure placement, BookModel assembly,
or EPUB splitting. Those remain M4, Assembly, and M1B responsibilities under
[`PRINCIPLES.md`](PRINCIPLES.md).

## SemanticWorkUnit

`SemanticWorkUnit` is frozen operational state, not book content. It records:

- deterministic work-unit ID, document ID, and zero-based source sequence;
- story (`BODY`, `HEADER`, `FOOTER`, or fallback `OTHER`);
- target and ordered neighboring source IDs;
- source kind and typed structural features;
- input, context, and policy fingerprints.

It contains no source text copy. `swu_<20 hex>` identity hashes document ID,
source sequence, target source identity, and work-unit policy version. Semantic
classification is excluded, so reclassification cannot change work identity.

## Source ordering and supported targets

`RawDocument.objects` tuple order is authoritative. When only PDF-style pages
exist, page tuple order followed by each page's object tuple order is used. IDs
are never lexically sorted.

M3A creates targets for:

- `RawParagraph` and `RawTextBlock`;
- `RawImage`;
- `RawTable` as one source table target;
- `RawDrawing` where extraction preserved drawing evidence.

Runs, table rows, and table cells remain accessible evidence but are not
independent semantic targets. A table AnalysisView may temporarily expose its
cell text; M3A does not reconstruct or classify table structure beyond the
table target.

## Story and context policy

Defaults are three analyzable objects before and three after. Context follows
source order and never crosses stories. BODY sees only BODY; header and footer
evidence remain present and see only their own story class. Images inherit the
containing paragraph story when available.

Batch boundaries do not affect context or identity.

## Structural features

Typed, deterministic features include source kind/story/sequence, style ID,
alignment, text length/emptiness, run and formatting counts, uppercase ratio,
anchored-image/image-only evidence, hyperlink count, table dimensions, image
MIME/dimensions, drawing type, and DOCX placement evidence when present.

These are observations, never conclusions. `Heading1`, uppercase, centered
text, and floating anchors do not imply title/chapter/figure semantics.

## AnalysisView and authoritative text

`AnalysisView` is a frozen in-memory dataclass. It resolves target and context
text from `EvidenceRegistry` only while a classifier is running. Its text is
not written into unit, result, fragment, failure, or manifest JSON.

```text
Raw Evidence -> EvidenceRegistry -> temporary AnalysisView
                                  -> ClassificationResult (no text copy)
```

Raw Evidence remains the only authoritative text.

## Classifier protocol and baseline

`SemanticClassifier` exposes only identity, configuration fingerprint, and:

```python
classify(analysis_view) -> ClassificationResult
```

It contains no Ollama, llama.cpp, model, GPU, cloud, or vendor type.
`BaselineUnknownClassifier` is deliberately non-intelligent. It always returns
valid `UNKNOWN`, confidence `0.0`, and `NEEDS_REVIEW`, with epoch provenance and
complete fingerprints. It applies no text/style/layout heuristic.

## Acceptance validation and fragments

Before persistence or materialization, M3A verifies deterministic result ID,
target/document identity, input/context fingerprints, taxonomy version,
classifier/config identity, confidence through M3.0 validation, and resolvable
source references. Invalid output becomes a visible failed attempt; it is never
converted to `UNKNOWN`.

Text-backed accepted results materialize as deterministic `sem_f<sequence>`
`SemanticFragment` values referencing Raw Evidence. Image/table/drawing results
without textual references remain valid ClassificationResults but do not force
an invalid text-backed fragment. Results are retained after materialization.

`UNKNOWN` means classification completed with uncertainty. `FAILED` means no
valid result was produced. Operational states are `PENDING`, `COMPLETED`,
`FAILED`, and `NEEDS_REVIEW`; they are not fields on SemanticFragment.

## Batching and long books

Default batches contain 50 consecutive units: 1-50, 51-100, and so on. Batches
are deterministic execution slices and do not alter work-unit IDs. Work-unit
generation groups story positions once, so neighboring-context selection is
linear in the number of analyzable objects plus bounded context size.

## Filesystem workspace and manifest

M3A writes beneath the existing extraction workspace only:

```text
work/<document-id>/semantic/
├── manifest.json
├── units/<work-unit-id>.json
├── results/<work-unit-id>.json
├── fragments/<fragment-id>.json
└── failures/<work-unit-id>.json
```

It does not write `source.json`, `raw_document.json`, `warnings.json`, or
`assets/`. JSON replacement uses a flushed temporary file in the destination
directory followed by `os.replace`.

The manifest records document/pipeline/taxonomy identity, policy and classifier
fingerprints, context and batch settings, counts, processing summary, and a
fixed provenance epoch. It contains no book text.

## Fingerprints and cache validity

Input SHA-256 covers document identity, target source identity and evidence
digest, ordered context identities and evidence digests, typed features,
work-unit policy, and taxonomy. Context has a separate SHA-256. Classifier
configuration SHA-256 is separate from both.

A cached result is reused only after full contract and compatibility validation.
Target/context content, taxonomy, classifier configuration, or corrupt JSON
makes it stale and causes reprocessing.

## Checkpoint, resume, failure, and retry

Each valid result and optional fragment is atomically persisted immediately;
the manifest is updated after each unit. Interruption therefore preserves all
completed compatible units.

Resume checks each unit independently. Valid results are reused, missing/stale
results are processed, and failed units are retried with the same ID. The
default continues after an isolated failure. A failure record stores typed
category, bounded safe message, fingerprints, identity, and retryability—never
chain-of-thought. Successful retry removes only that unit's failure record.

## Auditability and determinism

Unit, result, fragment, failure, and manifest files reveal target/context,
fingerprints, classifier/taxonomy/review state, and materialized fragment.
Epoch provenance prevents timestamps from changing identical output. Same Raw
Evidence and configuration produce byte-identical semantic JSON workspaces.

M3A has no LLM dependency because inference is an adapter behind the classifier
Protocol. The Mac can fully test pipeline correctness while a later ASUS-local
runtime can implement the same narrow port without entering core infrastructure.
