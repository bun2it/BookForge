# ADR-012: Deterministic pipeline orchestration

## Status

Accepted — M5C

## Decision

`PipelineRunner` is a thin coordinator, not a decision engine. Typed accepted
semantic/list/region/review truth enters through existing stage boundaries. M4
owns flow, M5A owns BookModel materialization, and M5B owns rendering.

The runner reuses stage-owned extraction, semantic, and flow workspaces. It
passes M4.9 replacement decisions mechanically to M5A and never constructs
`ResolvedContentFlow`, `BookModelV3`, or XHTML itself.

Future M3B plugs into the semantic classifier/accepted-truth boundary. Future
PDF evidence must enter before M3/M4 and cannot issue renderer instructions.
Future LLM output cannot directly mutate BookModel or EPUB.

## Consequences

The deterministic core can be qualified offline end-to-end with explicit test
truth, strict readiness, immutable source checks, structural validation,
resume, and path-independent byte determinism. This ADR adds no intelligence,
PDF runtime, UI, Library, or delivery behavior.
