# Accepted Flow Reviews

M4.9 transports already-established review truth; it does not infer reviews.
`FlowResolverInput.accepted_flow_reviews` contains typed pairs of an existing
`FlowDecisionReview` and its replacement decision.

The resolver first produces and persists the immutable original. It validates
original/replacement IDs, decision family and target, document, input, resolver
configuration, policy, taxonomy, and resolver provenance. Conflicts and stale
replacements fail deterministically; timestamps never select a winner.

Original decisions remain in their normal catalogs. The additive V3
`ResolvedContentFlow.replacement_decisions` and existing `decision_reviews`
preserve accepted truth. Effective reviewed state controls unresolved inventory
and inclusion order without mutating the original. Lists are revalidated after
effective inclusion, so excluding a member fails instead of repairing truth.

Review payloads participate in the final flow fingerprint. Original local work
units remain reusable. Reviews persist under `flow/reviews/`; replacements under
`flow/reviews/replacements/`. Structural region order is applied before boundary
work units, and transitions reconcile onto existing logical edges.

No authoritative text, asset bytes, source-layout inference, or AI state is
stored in review records.
