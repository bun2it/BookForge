# ADR-005: Book Assembly boundary and Contracts V3

- Status: Accepted
- Scope: M4 handoff, Book Assembly, BookModel, and later M1B adaptation

## Decision

Book Assembly is a mechanical, readiness-gated transformation from accepted
semantic state plus `ResolvedContentFlow` into immutable `BookModelV3`.
Contracts V3 uses one ordered top-level union of parts and ungrouped chapters;
parts exclusively own their child chapters. Logical break intent is stored on
the materialized hierarchy.

V3 is necessary because V2's flat chapter list cannot gain part hierarchy
without a second ordering truth. V2 remains the input supported by the frozen
M1B renderer until a later renderer milestone explicitly adds V3 support. No
automatic migration is introduced.

## Consequences

- Assembly cannot classify, infer, repair, join, place, or render.
- Strict/reviewed preflight rejects unresolved, conflicting, stale, missing,
  or unsupported input rather than guessing.
- PART opening content and mixed part/chapter books have deterministic order.
- M1B must later learn V3 hierarchy and break intent; it still must not inspect
  DOCX/PDF layout.
