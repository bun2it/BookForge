# ADR-001: Core pipeline boundaries

- Status: Accepted
- Scope: All BookForge core conversion milestones

## Decision

BookForge separates:

```text
Extraction -> Semantic -> Flow/Boundary -> Book Assembly -> Rendering
```

Extraction preserves evidence and source order. M3 identifies semantic meaning—what content is. M4 determines continuity, logical grouping, boundaries, and final reading placement—how content flows. Book Assembly materializes resolved M4 output as the active BookModel contract (V3 after ADR-005). A compatible M1B renders BookModel without re-running semantic or source-layout inference.

## Rationale

The separation makes source extraction deterministic, semantic work replaceable/reviewable, flow decisions auditable, and rendering independently testable. It prevents parser layout, AI classification, and EPUB packaging from silently making each other's decisions.

## Consequences

- M3 cannot emit final page/chapter breaks, joins, or figure placement.
- M4 cannot mutate Raw Evidence.
- M1B treats BookModel order as authoritative.
- Cross-stage shortcuts are architecture violations and require explicit contract evolution.
