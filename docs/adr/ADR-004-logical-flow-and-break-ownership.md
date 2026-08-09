# ADR-004: Logical flow and break ownership

- Status: Accepted
- Scope: M3, M4, Book Assembly, and M1B boundaries

## Decision

M3 identifies semantic meaning. M4 resolves continuity, logical structural
boundaries, grouping, inclusion, figure placement, caption association, and
logical break intent. Book Assembly materializes accepted resolved flow as
the active BookModel contract. ADR-005 selects BookModelV3 for future Assembly;
the frozen current M1B still renders V2 until later adaptation.

The layers remain:

```text
M3 SemanticFragments
  -> M4 ResolvedContentFlow
  -> Book Assembly
  -> BookModelV3
  -> compatible M1B EPUB
```

Continuity, structural boundary, logical break, relationship/placement, and
inclusion are separate typed dimensions. PART and CHAPTER logical break
decisions belong to M4. SECTION is structurally meaningful but does not
automatically create a new page.

Physical source layout never directly becomes the decision:

```text
PDF page boundary != EPUB logical break
DOCX anchor        != final figure placement
```

## Rationale

Separating the dimensions prevents a heading, physical page transition, or
image anchor from silently producing renderer behavior. Typed decisions allow
source-backed paragraph/table/list continuity and final reading placement to
remain auditable without rewriting evidence. Assembly can then materialize a
complete logical model rather than becoming another inference stage.

## Consequences

- M4 joins references and operations, never authoritative text.
- Logical NEW_PAGE intent contains no XHTML filename or EPUB package state.
- Figure placement uses logical neighboring fragment references, not geometry.
- Caption association is explicit and separate from classification.
- Exclusion removes content only from final flow, never from evidence/audit.
- Unresolved M4 decisions require review or block Assembly; runtime failure is
  represented separately in a future operational milestone.
- Current M1B remains frozen and deterministic over BookModel V2; a later
  approved adaptation must remain deterministic over V3.
