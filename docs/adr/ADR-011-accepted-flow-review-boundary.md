# ADR-011: Accepted flow review boundary

## Status

Accepted — M4.9

## Decision

M4A accepts explicit typed review/replacement pairs after producing immutable
baseline decisions. It preserves original, review, and replacement separately;
effective state controls unresolved inventory and inclusion order.

Contracts V3 is retained. `ResolvedContentFlow.replacement_decisions` is an
additive typed catalog needed to validate reviewed state without hidden metadata
or mutation. M5A remains the Assembly decision consumer.

Region transitions reconcile onto an existing logical boundary, and explicit
region order is applied before boundary work-unit generation.

## Consequences

Future M5C can pass reviewed JOIN/inclusion truth through actual M4A without
manual flow construction. No review inference, AI, PDF, Assembly, or renderer
behavior is added.
