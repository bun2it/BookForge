# M4.0 Flow and Boundary Contracts

## Status and ownership

M4.0 defines the legal output of future flow/boundary resolution. It introduces
contracts only—no resolver, heuristic, AI, workspace, Book Assembly, or EPUB
change. [`PRINCIPLES.md`](PRINCIPLES.md) remains normative.

```text
accepted M3 SemanticFragments
  -> M4 typed decisions
  -> ResolvedContentFlow
  -> Book Assembly
  -> BookModel V2
  -> deterministic M1B rendering
```

M3 decides what content is. M4 decides how accepted semantic content connects,
groups, breaks, is included, and is placed in logical reading order. M4 cannot
rewrite Raw Evidence, reinterpret raw text independently of accepted M3
semantics, name EPUB files, serialize BookModel as a side effect, or render.

## Contract audit and versioning

Historical `BoundaryOperation` and `ContentFlow` preserve basic operation and
ordered-fragment data, but cannot cleanly express the required orthogonal
dimensions, review, candidates, fingerprints, placement, exclusion, or
Assembly handoff. M4.0 therefore adds a new flow contract family while leaving
those models unchanged.

This is additive Contracts V2 work. No V2 field is removed, renamed, or assigned
a new meaning, so Contracts V3 is not required. New flow models use their own
schema version 1 under the active Contracts V2 architecture, as M3 decision
contracts do.

## Five independent decision dimensions

M4 does not collapse flow to one `join` or `page_break` boolean:

1. continuity—how adjacent content connects;
2. structural boundary—whether logical hierarchy transitions;
3. logical break intent—reader-page intent independent of packaging;
4. relationship/placement—figure and caption logical relationships;
5. inclusion—whether preserved evidence enters final book flow.

## LogicalBoundaryDecision

A first-class boundary represents `BETWEEN_FRAGMENTS`, `START_OF_DOCUMENT`, or
`END_OF_DOCUMENT`. Between-fragment boundaries identify distinct preceding and
following semantic fragments.

Continuity values are:

- `KEEP_SEPARATE`;
- `JOIN_DIRECT`;
- `JOIN_WITH_SPACE`;
- `JOIN_WITH_NEWLINE`;
- `JOIN_REMOVE_TRAILING_HYPHEN`;
- `CONTINUE_LIST`;
- `CONTINUE_TABLE`;
- `NO_CONTINUITY_DECISION`;
- `UNRESOLVED`.

Text and list joins carry at least two `SourceTextReference` values. Table
continuation carries at least two generic source evidence IDs because a
`RawTable` is not itself textual evidence. Neither form stores joined text,
merged cells, or regenerated list content.

Optional continuity candidates are typed and unique. Scores are individually
bounded to `[0, 1]` and need not sum to one. Candidates are retained only for
the ambiguous pairwise continuity dimension; other decisions use explicit
unresolved/review states to keep the base contract small.

## Structural boundaries and break intent

Structural types are `NONE`, `SECTION`, `SUBSECTION`, `CHAPTER`, `PART`,
`FRONT_MATTER_TRANSITION`, `BACK_MATTER_TRANSITION`, and `UNRESOLVED`. Source
page is deliberately absent.

Break intent is independently `NONE`, `NEW_PAGE`, or `UNRESOLVED`. Fixed-layout
and spread concepts are absent. Contracts can express typical policy outcomes:

- PART + NEW_PAGE;
- CHAPTER + NEW_PAGE;
- SECTION + NONE;
- SUBSECTION + NONE.

They do not hardwire those outcomes. Future M4 configuration combines accepted
semantics and context. `NEW_PAGE` is logical intent, not an XHTML filename,
spine entry, or package operation.

## Logical grouping

`LogicalGroup` minimally represents `FRONT_MATTER`, `BACK_MATTER`, `PART`,
`CHAPTER`, `SECTION`, or `SUBSECTION`. It contains ordered opening fragments,
ordered members, an optional parent group, and the boundary decision that
created it. N-ary openings such as chapter heading + title + subtitle need one
group rather than fragile pairwise relationships.

IDs use `flow_<kind>_<order:04>`, such as `flow_part_0001` and
`flow_chapter_0003`. They are deterministic logical identities independent of
EPUB filenames.

## Figure placement

`FigurePlacement` records a figure reference and logical relation `BEFORE`,
`AFTER`, `BETWEEN`, `INLINE_FLOW`, or `UNRESOLVED`. Resolved placements identify
neighboring logical fragments and must agree with `ResolvedContentFlow` order.

Optional source anchor evidence IDs preserve audit inputs only. There are no
X/Y coordinates, float CSS, left/right layout, or mandatory DOCX fields.
Changing a DOCX anchor cannot itself change the typed logical placement.

## Caption association

`CaptionAssociation` explicitly links one caption to one final figure, records
whether the caption is logically before or after it, or remains `UNRESOLVED`
with optional candidate figures. Referential validation prevents duplicate
final association decisions for one caption. Caption text remains available
only through its SemanticFragment source references.

Association and order are distinct: a caption may validly precede or follow its
figure. Same-page placement is not required.

## Table and list continuity

`CONTINUE_TABLE` relates source-backed table fragments without copying rows,
inventing cells, or reconstructing a logical table. `CONTINUE_LIST` relates
source-referenced list segments without generating list text. Ambiguity is
represented by `UNRESOLVED`; source page changes imply neither continuation nor
logical break.

## Inclusion and artifact evidence

`InclusionDecision` is `INCLUDE`, `EXCLUDE`, or `UNRESOLVED`. It is separate
from M3 semantic values such as `RUNNING_FOOTER`, `PAGE_NUMBER`, `DECORATIVE`,
and from empty-paragraph evidence.

`EXCLUDE` removes a fragment only from final logical order. Raw Evidence,
ClassificationResult, SemanticFragment, and the decision audit remain intact.
No contract-level rule automatically excludes any semantic type.

## Audit, confidence, reasons, and reviews

Every decision embeds `FlowDecisionAudit` containing deterministic ID,
confidence `[0, 1]`, shared `ReviewStatus`, compact reason codes, and provenance.
Provenance records resolver identity/version/kind, document, configuration and
input fingerprints, semantic taxonomy, flow-policy version, relevant
ClassificationResult IDs, and explicit timestamp. It stores no chain-of-thought.

Reason codes include adjacency, source-page continuation, trailing hyphen,
semantic structure signals, figure/caption context, repeated/print artifact,
table/list continuation, and human override.

`FlowDecisionReview` never mutates the original decision. Accepted review links
the original ID to itself; override links it to a separate replacement typed
decision. Runtime resolver failure is outside content contracts. `UNRESOLVED`
means M4 completed but could not safely decide; `FAILED` will be an operational
M4A state.

## Fingerprints and deterministic IDs

Future M4A input fingerprints must cover relevant fragment IDs, accepted
classification identity, local semantic context, semantic taxonomy, and flow
policy. Resolver configuration remains a separate fingerprint.

`fld_<20 hex>` decision IDs derive from decision kind, relevant fragments,
input/config fingerprints, and policy version—not output text or random state.
Changed semantic input is therefore detectable as stale. Review IDs use
`fdr_<20 hex>` over original/replacement identities and review fingerprint.
M4.0 defines this support but implements no cache or workspace.

## ResolvedContentFlow

The frozen M4 handoff contains:

- the complete accepted source fragment ID set;
- authoritative final logical fragment order;
- typed boundaries and groups;
- figure placements and caption associations;
- inclusion decisions and review records;
- explicit unresolved decision IDs;
- resolver/policy/fingerprint provenance.

It references fragments rather than duplicating SemanticFragment objects.
Referential validation rejects unknown/duplicate fragments or decisions,
unknown group parents, duplicate caption/inclusion decisions, excluded content
in final order, and resolved placement inconsistent with final order.

## M4 to Assembly boundary

Book Assembly receives the accepted semantic catalog/classification audit plus
`ResolvedContentFlow`. It may materialize BookMetadata, front/back matter,
part/chapter/section hierarchy, BookContentCatalog, and ordering. It must not:

- reclassify a heading;
- re-solve joins or breaks;
- reposition figures or captions;
- inspect DOCX anchors, PDF coordinates, or physical pages;
- invent a choice for unresolved decisions.

If required decisions remain unresolved, orchestration must obtain review or
stop before Assembly. Assembly materializes decisions; it is not M4.5.

M4.6 clarifies that accepted continuity is not consumed-and-discarded at this
boundary. Assembly maps each effective resolved boundary operation to a
`LogicalContinuityV3` annotation. Node identity and authoritative source
references remain unchanged; see ADR-007.

## Source and renderer neutrality

Flow contracts require no DOCX or PDF field. Source anchor/page evidence may be
referenced in provenance, but:

```text
PDF page boundary != logical EPUB break
DOCX anchor        != final figure placement
```

M1B continues to receive only BookModel V2 and need not know why content was
joined, grouped, placed, or excluded.

## Prohibited M4 behavior

M4 contracts and future resolvers must not contain authoritative joined text,
XHTML filenames, OPF/nav/CSS state, physical coordinates, raw-evidence
mutation, semantic reclassification by side effect, BookModel construction, or
runtime failure encoded as an unresolved content decision.
