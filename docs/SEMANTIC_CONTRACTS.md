# M3 Semantic Classification Contracts

## Status and scope

This document defines the M3.0 contract baseline. It is a contract-design
milestone only: it does not implement classifiers, model providers, batching,
checkpoints, flow resolution, book assembly, or UI.

The normative rules in [`PRINCIPLES.md`](PRINCIPLES.md) remain authoritative.
M3 answers **what source evidence is**. It does not answer how evidence joins,
where chapters break, where figures are inserted, or what the final BookModel
order will be.

## Contract-version decision

M3.0 does not require Contracts V3. The new models are additive contracts and
the taxonomy additions do not rename, remove, or reinterpret persisted V2
fields. `BookModel` and `BookContentCatalog` therefore remain active at schema
version 2. A milestone number is not a schema version.

A future change that removes legacy semantic values, changes source-reference
meaning, or changes a V2 invariant will require an explicit version decision.

## Taxonomy

The first M3 taxonomy version is `bookforge-semantic-v1`. Taxonomy version is
independent of contract schema version and classifier/model version.

The useful classification concepts are:

- book title (`BOOK_TITLE`; legacy assembled books may contain `TITLE`),
  subtitle, and author;
- front-matter title/text and part title;
- chapter heading, chapter number/title, section heading, and subsection
  heading (legacy assembled books may contain generic `HEADING`);
- paragraph, quote, list, and list item;
- figure, caption, table, note, and footnote;
- running header, running footer, page number, decorative content, and unknown.

Existing `TIP` and `ARTIFACT` values remain compatible. They are not removed in
an additive V2 change. M4/Assembly, not M3, decides whether classified artifact
evidence is excluded from final reading flow.

`UNKNOWN` is a successful semantic decision meaning evidence was insufficient
for a narrower type. Operational classifier failure is not `UNKNOWN`; runtime
failure/retry contracts belong to M3A or later.

## ClassificationResult

`ClassificationResult` is an immutable structured decision with:

- deterministic classification ID;
- complete target source IDs and, for textual classifications, authoritative
  `SourceTextReference` values;
- selected semantic type, confidence, and optional alternative candidates;
- review status and compact rationale codes;
- classifier name/kind/version and optional model identifier;
- configuration, input, and context SHA-256 fingerprints;
- taxonomy version and semantic-stage provenance.

Candidate scores are individually bounded to `[0, 1]`; they do not need to sum
to one. Candidate semantic types must be unique, and the selected type is not
repeated as an alternative.

The contract stores neither authoritative/regenerated text nor private
chain-of-thought. Compact enums such as `STYLE_SIGNAL`, `REPEATED_PATTERN`, and
`MODEL_CLASSIFICATION` provide inspectable evidence without hidden reasoning.

Classification identity is derived from target identity, taxonomy, classifier,
and configuration/input/context fingerprints. It deliberately excludes the
selected semantic type. Re-running identical work produces the same ID;
changing the decision does not change source identity.

## Review and override

Review states are `NOT_REQUIRED`, `NEEDS_REVIEW`, `REVIEWED_ACCEPTED`, and
`REVIEWED_OVERRIDDEN`.

`ClassificationReview` is a separate immutable audit record. It references the
original classification ID, repeats its original semantic type, records the
accepted type, reviewer identity, rationale, fingerprint, and provenance. An
accepted review must retain the type; an overridden review must change it. The
original machine result is never edited or discarded.

For M4.6 Assembly admission, a review may also snapshot the base classification
input fingerprint and taxonomy version. Hardened Assembly input requires these
values for an active review and rejects missing or mismatched snapshots as
stale. Historical review serialization remains readable because these fields
are optional outside the Assembly admission boundary.

## Source traceability

Every target carries source IDs. Every classification representing textual
content additionally carries at least one `SourceTextReference`, and each
reference must belong to the target. Text continues to resolve only through:

```text
SourceTextReference -> EvidenceRegistry -> frozen Raw Evidence
```

Figure and table classification identifies their type only. It does not decide
figure placement, caption association, table reconstruction, or rendering
strategy. A DOCX anchor or PDF coordinate may influence a future classifier as
source evidence but cannot become logical EPUB placement.

## Explicitly absent from M3 output

The classification contracts contain no:

- page/chapter/section break instruction;
- paragraph join or hyphen-resolution operation;
- final chapter/part grouping;
- final figure placement or caption association;
- final BookModel order;
- checkpoint, retry, cache, or resume state;
- provider-specific AI request/response payload;
- authoritative generated text.

Those responsibilities remain with M3A runtime, M4 flow/boundary resolution,
Book Assembly, or rendering as defined by the architecture.
