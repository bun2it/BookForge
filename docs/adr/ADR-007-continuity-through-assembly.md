# ADR-007: Preserve continuity through Book Assembly

- Status: Accepted
- Scope: M4 output, Contracts V3 Assembly boundary, and future M5B rendering

## Decision

M4 owns continuity. Book Assembly preserves each effective accepted operation
as an immutable `LogicalContinuityV3` edge in `BookModelV3`. A future compatible
renderer executes that edge after resolving both nodes through authoritative
source references.

The hierarchy remains the sole ordering truth. A continuity edge cannot reorder
content: it references two nodes that must be adjacent in final included order.
It records only left/right IDs, operation, and accepted M4 decision ID. Nodes
are never merged or deleted to represent a join.

Supported persisted operations are KEEP_SEPARATE, the four text joins,
CONTINUE_LIST, and CONTINUE_TABLE. Joins cannot cross logical hierarchy
containers. Explicitly excluded source artifacts do not prevent adjacency when
the remaining nodes are adjacent in final flow.

## Rationale

Dropping M4 continuity would make BookModel incomplete and force M1B to consult
M4 state or rediscover semantics. Merging nodes would destroy source identity,
review identity, and auditability. A small edge catalog preserves the decision
without creating a second reading order or authoritative text copy.

## Consequences

- JOIN operations carry no joined/generated text.
- CONTINUE_TABLE and CONTINUE_LIST do not reconstruct content.
- Conflicting edges, missing targets, incompatible families, non-adjacency, and
  structural-boundary crossings are validation failures.
- Effective reviewed replacement identity survives into BookModelV3.
- Canonical Assembly revision input includes continuity.
- Current M1B V2 remains unchanged; M5B must execute V3 continuity later.
