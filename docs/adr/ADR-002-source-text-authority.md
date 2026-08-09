# ADR-002: Source-text authority

- Status: Accepted
- Scope: Extraction through artifact rendering

## Decision

Raw Evidence is authoritative for source content. Semantic layers store `SourceTextReference` values, not regenerated authoritative text. `EvidenceRegistry` resolves those references to frozen evidence. The active BookModel represents logical structure; EPUB represents the deterministic rendered artifact. ADR-006 adds source-neutral non-text provenance without changing text authority.

```text
SemanticFragment -> SourceTextReference -> EvidenceRegistry -> Raw Evidence -> XHTML
```

AI may classify and relate evidence, but it cannot replace, paraphrase, correct, translate, summarize, expand, or shorten authoritative text inside the core conversion pipeline.

## Rationale

Duplicated AI-generated text would destroy provenance, allow silent content drift, make reclassification alter book wording, and prevent reliable validation against the source. References preserve fidelity while allowing semantic and flow models to evolve.

## Consequences

- Downstream transformations create references/operations rather than rewriting evidence.
- Rendered text remains auditable to source IDs and ranges.
- Editorial features, if introduced, must be separate and explicit.
- Missing or unresolved evidence is visible failure/review state, not an invitation to fabricate text.
