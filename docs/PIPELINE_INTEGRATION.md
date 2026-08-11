# M5C Deterministic Core Pipeline Integration

## Purpose and stage graph

`PipelineRunner` qualifies the existing deterministic owners as one offline
system:

```text
DOCX -> M1A -> M3A -> typed projection -> M4A/M4.9 -> M5A -> M5B -> validation
```

The runner coordinates and carries typed values. It does not classify content,
infer structure, resolve boundaries, materialize BookModel, or render XHTML.

## Explicit input

`PipelineInput` requires the source/workspace/output paths, explicit
`BookMetadataV3`, a `SemanticClassifier` provider, explicit
`StructuralRegionAssignment`, and optionally logical lists, classification
reviews, accepted flow reviews, source features, and policies. Qualification
tests use a mapping-backed classifier keyed only by deterministic work-unit ID;
it does not inspect text, style, layout, or filenames.

This classifier/provider boundary is the future M3B injection point. A future
local model may propose accepted semantic truth through the same M3 contract;
it may not directly change flow, BookModel, or EPUB.

## Ownership and outputs

- M1A owns DOCX parsing, evidence, registry, warnings, and extracted assets.
- M3A owns work units, analysis views, classification validation, fingerprints,
  semantic workspace, and historical materialization.
- M4.8 projects accepted results into typed source-neutral nodes.
- M4A owns flow; M4.9 validates and preserves accepted reviews/replacements.
- M5A alone creates `BookModelV3` after strict readiness.
- M5B alone creates EPUB bytes and immutable artifact metadata.

`PipelineResult` exposes the stage reports, readiness, resolved flow, book,
artifact, structural validation, optional EPUBCheck record, statuses, and
before/after source-state digests. It is not Library persistence.

## Workspace, resume, and stale detection

M1A creates the document-ID workspace. M3A and M4A reuse their own `semantic/`
and `flow/` checkpoint trees underneath it; the runner creates no duplicate
cache. An idempotent repeated run reuses valid work units. Source bytes,
semantic classifier/configuration, context, node/list/region truth, reviews,
resolver policy, Assembly state, and renderer inputs already participate in
their owning fingerprints/revisions. Changed truth cannot silently reuse a
compatible final result.

## Failure and traceability

Typed stage exceptions are preserved. UNKNOWN or missing required truth reaches
strict readiness and blocks; unsupported included content remains visible and
blocks; explicit reviewed exclusion preserves raw/semantic evidence. List and
region inconsistencies fail rather than being repaired. Text/table cells remain
traceable through `SourceTextReference`; figure bytes resolve by the exact M1A
asset reference and are byte-preserved.

M1A debug JSON and extracted assets are hashed before and after downstream
execution. Flow and BookModel are immutable contracts and are not mutated by
their consumers. Structural validation is mandatory. EPUBCheck is optional and
its unavailable state is reported as `VALIDATOR_UNAVAILABLE`, never PASS.

## Determinism and architecture boundary

Identical inputs in different empty workspace roots produce identical document
identity, semantic/flow output, BookModel revision, EPUB bytes, and SHA-256.
Absolute paths and physical source pages do not drive EPUB internal paths or
logical breaks. DOCX anchors remain evidence, not final figure placement.

Future PDF evidence enters before semantic and flow decisions. It may not
directly command EPUB page breaks, figure positions, chapter boundaries, or
paragraph joins. M6 owns that future evidence/corroboration work.
