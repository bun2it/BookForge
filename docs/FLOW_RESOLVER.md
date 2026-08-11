# M4A Deterministic Flow and Boundary Resolver

As of M4.8, one resolver accepts historical text fragments and V3 typed nodes.
Accepted lists and explicit structural regions are fingerprinted, validated,
and materialized without inference. See
[`SEMANTIC_FLOW_HANDOFF.md`](SEMANTIC_FLOW_HANDOFF.md).

M4.9 accepts typed, already-reviewed replacements without inference. Original
decisions remain immutable; review/replacement truth is validated,
fingerprinted, and persisted separately. See [`FLOW_REVIEWS.md`](FLOW_REVIEWS.md).

## Scope

M4A consumes accepted M3 semantic fragments and produces the typed M4.0
`ResolvedContentFlow`. It implements deterministic infrastructure and only
high-certainty policies. It contains no semantic classifier, LLM, PDF parser,
Book Assembly, BookModel mutation, or EPUB behavior.

Correct, auditable, deterministic, resumable, and conservative decisions take
precedence over coverage. Insufficient evidence produces `UNRESOLVED`, not a
guess.

## Input and output

Runtime `FlowResolverInput` provides document identity, source-ordered accepted
SemanticFragments, accepted ClassificationResults, EvidenceRegistry, typed
source-neutral features, and semantic taxonomy identity. It does not persist a
copy of authoritative text.

Output is `ResolvedContentFlow`. Book Assembly remains a later boundary.

## Two phases

Phase A processes independent local work units:

- boundary between adjacent semantic fragments;
- inclusion for each fragment;
- placement for accepted FIGURE fragments;
- association for accepted CAPTION fragments.

Phase B runs only when no local unit failed. It removes explicitly excluded
fragments from logical order, builds deterministic PART/CHAPTER/SECTION/
SUBSECTION hierarchy, inventories unresolved decisions, validates references,
and writes `resolved_flow.json`.

This prevents global hierarchy mutation during a partially completed local
loop. Local work is O(n) with bounded context; global finalization is O(n + g²)
for `g` structural group starts. For ordinary books `g` is much smaller than
the fragment count.

## Work units and AnalysisView

`FlowWorkUnit` stores kind, ordered target/context fragment IDs, accepted types,
ClassificationResult IDs, and input/context/policy fingerprints. IDs use
`fwu_<20 hex>` over document, kind, target identity, and source sequence. They
do not depend on the resulting decision.

`FlowAnalysisView` resolves target text temporarily through:

```text
SemanticFragment -> SourceTextReference -> EvidenceRegistry
```

It exposes semantic context and typed source features in memory. Text is never
written to units, decisions, manifests, failures, or resolved flow. A fragment
with multiple unresolved references is not implicitly joined merely to build a
view.

## Rule architecture and priority

Rules expose stable ID, version, priority, supported work-unit kind, and
`evaluate(view, policy, audit)`. Resolver order is explicit and deterministic:

1. accepted PART/CHAPTER/SECTION/SUBSECTION structural boundary;
2. explicit source continuation;
3. known semantic separation;
4. unresolved boundary fallback;
5. independent inclusion, figure, and caption rules for their unit kinds.

No rule examines uppercase, Heading styles, font sizes, or raw text to invent a
semantic type.

## Structural and break policy

Only accepted semantics trigger structure:

- `PART_TITLE` -> PART;
- `CHAPTER_HEADING`/`CHAPTER_NUMBER`, or standalone accepted `CHAPTER_TITLE`,
  -> CHAPTER;
- `SECTION_HEADING` -> SECTION;
- `SUBSECTION_HEADING` -> SUBSECTION.

Default break policy is NEW_PAGE for PART/CHAPTER and NONE for SECTION/
SUBSECTION. Every value is configurable, versioned, and fingerprinted. Changing
policy recomputes affected decisions. Structural rules return KEEP_SEPARATE;
they never create renderer filenames.

## Conservative continuity

Paragraph joining requires typed explicit segmentation evidence:

- both fragments are accepted PARAGRAPH;
- both share a non-empty continuation-group identity;
- the right side explicitly records a source boundary.

If the left source text ends in a hyphen or soft hyphen, the operation is
`JOIN_REMOVE_TRAILING_HYPHEN`; otherwise it is `JOIN_WITH_SPACE`. Raw strings
remain unchanged. Adjacent paragraphs without this evidence are `UNRESOLVED`,
even when one lacks punctuation or the next starts lowercase.

Known non-paragraph semantic transitions are KEEP_SEPARATE. This is not used as
a disguised fallback: UNKNOWN or ambiguous paragraph boundaries remain
UNRESOLVED and NEEDS_REVIEW.

Accepted TABLE/LIST fragments use `CONTINUE_TABLE`/`CONTINUE_LIST` only with the
same explicit continuation evidence. M4A does not merge tables, rows, cells,
lists, or text.

Physical segment/page identity is an input feature only. An explicitly known
same source paragraph may join across physical pages with break NONE; a page
transition alone never creates NEW_PAGE.

## Figure and caption policy

An accepted FIGURE is placed in source-neutral semantic sequence only when the
adapter marks that logical sequence explicit. Its final relation references
previous/next fragments. Source anchor IDs are audit evidence; coordinates and
floating geometry are absent. Otherwise placement is UNRESOLVED.

An accepted CAPTION associates with an immediately adjacent FIGURE only when
the bounded context has exactly one figure candidate. Caption-before and
caption-after are both supported. Two figures followed by one caption remains
UNRESOLVED rather than choosing the nearest for coverage.

## Inclusion and grouping

Accepted RUNNING_HEADER, RUNNING_FOOTER, PAGE_NUMBER, and DECORATIVE fragments
are excluded only when the versioned policy enables that type. Other known
semantic content is included. UNKNOWN inclusion remains UNRESOLVED. Empty text
alone never causes exclusion.

Final order omits only EXCLUDE decisions. Every excluded fragment remains in
source inventory and all source/M3 audit state remains untouched.

Global grouping scans structural boundaries in final order. PART, CHAPTER,
SECTION, and SUBSECTION IDs use deterministic per-kind ordinals. A group ends
at the next same-or-higher boundary; its parent is the nearest enclosing
higher-level group. Chapter heading/number/title/subtitle can form one n-ary
opening. Malformed or absent accepted structure is not repaired from typography.

## Review, unresolved, and failure

Review threshold is policy configuration, not a contract constant. Decisions
below it become NEEDS_REVIEW; rules can explicitly request review regardless of
confidence.

UNRESOLVED is a successful content decision. FAILED means rule execution or
decision persistence did not produce a valid local result. If any unit fails,
other units continue and checkpoint, but global `ResolvedContentFlow` is not
emitted. Retrying preserves the unit ID and removes only the successful unit's
failure record. Existing `reviews/` accepts immutable `FlowDecisionReview`
records; no GUI is implemented.

## Workspace and atomic checkpointing

```text
flow/
├── manifest.json
├── units/
├── decisions/
├── inclusions/
├── placements/
├── captions/
├── groups/
├── reviews/
├── failures/
└── resolved_flow.json
```

Each completed local decision is flushed to a same-directory temporary file,
fsynced, and atomically replaced. Manifest updates after each unit. Interrupted
books reuse all compatible completed work.

Cache validation checks contract parsing, deterministic decision ID, target
fragment identity, input/context identity, accepted classification IDs,
taxonomy, policy, resolver identity/version, and configuration fingerprint.
Changed semantics, neighboring context, policy, resolver rules/configuration,
taxonomy, source references, or relevant source text makes decisions stale.

## Fingerprints and determinism

Input fingerprints cover fragment serialization, semantic type, accepted
ClassificationResult, source-text digest, typed source features, bounded
semantic context, taxonomy, and policy fingerprint. Context fingerprint is
separate. Resolver configuration fingerprint covers resolver identity and
ordered rule ID/version/priority.

All generated provenance timestamps use the established epoch. Identical clean
runs produce identical work-unit IDs, decisions, groups, final ordering,
resolved flow, and byte-identical JSON workspaces.

## Source neutrality and boundaries

Core models require no DOCX/PDF types. Adapters may supply story, physical
segment, continuation identity, or source anchor IDs through typed features.
These remain evidence:

```text
DOCX floating anchor != final figure geometry/placement command
PDF physical page     != logical NEW_PAGE
```

M4A never creates BookModel, Part extensions, XHTML, CSS, OPF, navigation, or
spine data. The known Part-hierarchy and non-text semantic-provenance gaps are
deferred to the Assembly Contract Audit as instructed; neither blocks M4A.

## Current limitations

- No general natural-language paragraph reconstruction.
- No join based only on punctuation, lowercase, typography, or adjacency.
- No table reconstruction or list-item synthesis.
- No figure placement without explicit logical-sequence evidence.
- No ambiguous caption selection.
- No automatic hierarchy repair.
- UNKNOWN-heavy M3A baseline naturally yields mostly unresolved M4 output until
  M3B supplies accepted semantics.
