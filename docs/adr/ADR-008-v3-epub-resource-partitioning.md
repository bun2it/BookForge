# ADR-008: V3 EPUB Resource Partitioning

## Status

Accepted for M5B.

## Context

The historical V2 renderer creates one XHTML resource per chapter. Contracts
V3 explicitly preserve `LogicalBreakIntent` for PART, CHAPTER, SECTION, and
SUBSECTION. An unconditional chapter split would impose a hard reading-system
boundary even when an accepted chapter has `NONE`, contradicting the active
logical model.

## Decision

The V3 renderer derives an implementation-only resource plan from the ordered
BookModelV3 hierarchy:

- `NEW_PAGE` begins a new deterministic `segment_NNN.xhtml` when previous
  rendered content exists;
- `NONE` remains in the current segment;
- hierarchy is retained through semantic sections, anchors, and nested nav,
  independently of resource boundaries;
- CSS `break-before: page` and `page-break-before: always` complement hard
  NEW_PAGE partitioning;
- empty structural groupings do not create empty resources;
- filenames, spine, and anchors are renderer-controlled and deterministic.

No technical size threshold is introduced in M5B. A future technical split must
remain visually neutral and must not claim logical page intent.

## Consequences

`CHAPTER + NONE` and `SECTION + NONE` can remain continuous, while `NEW_PAGE`
has a strong resource boundary independent of source pages. Navigation targets
may share one XHTML resource and therefore use deterministic internal anchors.
V2 packaging remains unchanged.
