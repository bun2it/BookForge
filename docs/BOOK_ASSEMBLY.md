# Deterministic Book Assembly

## Purpose and public API

M5A mechanically converts `AssemblyInput` into immutable `BookModelV3`. It is
the boundary between accepted M3 semantic truth plus accepted M4 flow truth and
later rendering.

```python
from bookforge.assembly import BookAssembler

report = BookAssembler().preflight(assembly_input)
book = BookAssembler().assemble(assembly_input)
```

`preflight()` returns the frozen typed `AssemblyReadinessReport`. `assemble()`
runs that validation first and either returns a complete model or raises an
existing `AssemblyNotReadyError` subclass whose `.report` contains the blocking
findings. It never returns a partial model.

## Admission and preflight

`STRICT` requires fully resolved original decisions. `REVIEWED` permits only
valid explicit classification or flow replacements under frozen V3 rules; it
never guesses or suppresses uncertainty. Stale, unknown, cross-family, or
conflicting reviews block assembly.

Readiness covers metadata and catalog integrity, accepted classification and
review integrity, explicit INCLUDE/EXCLUDE disposition for every node, complete
front/body/back ownership, valid PART/CHAPTER/SECTION/SUBSECTION hierarchy,
continuity, figure/caption/table/asset references, and all required resolved
decisions. Included unsupported content fails instead of disappearing silently.
Failures use `AssemblyReadinessCode` and existing typed V3 exceptions.

## Materialization

The assembler resolves effective classifications and reviewed M4 decisions,
then materializes the catalog, explicit dispositions, hierarchy, breaks,
continuity, captions, metadata, and deterministic provenance. Opening content
stays before nested containers. PART remains first-class and ungrouped chapters
remain ungrouped. It never invents titles or labels.

Logical group order and `ResolvedContentFlow.ordered_fragment_ids` are
authoritative. Accepted M4 break intents are copied exactly. Physical pages,
blank paragraphs, fonts, source coordinates, and DOCX image anchors never
determine breaks or placement.

## Continuity and source text

Authoritative text remains exclusively:

`SourceTextReference -> EvidenceRegistry -> raw evidence`

Assembly stores no cleaned, normalized, joined, rewritten, or generated text.
`JOIN_DIRECT`, `JOIN_WITH_SPACE`, `JOIN_WITH_NEWLINE`,
`JOIN_REMOVE_TRAILING_HYPHEN`, `CONTINUE_TABLE`, and `CONTINUE_LIST` remain
operations between unchanged nodes. Assembly never executes joins, merges rows,
reconstructs cells, or regenerates list text.

## Figures, captions, tables, lists, and assets

Figures follow final M4 logical order and require accepted placement. Source
anchors remain evidence only. Captions require explicit accepted association;
adjacency and styling are not interpreted. Tables remain source-backed semantic
table nodes without reconstruction. Typed asset references are retained and
validated without loading or transforming bytes. Covers are copied only from
explicit metadata and are never auto-selected.

M5B.2 mechanically copies `ResolvedContentFlow.logical_lists` into
`BookModelV3.logical_lists`. Preflight rejects excluded, missing, or wrongly
typed members; final model validation enforces order, structural ownership,
nesting, and CONTINUE_LIST consistency. Assembly never derives a list from
adjacent LIST_ITEM nodes and never chooses its kind.

## Determinism and complexity

Canonical sorted-key JSON SHA-256 fingerprints plus
`assembly_revision_for_state` make identical effective input produce identical
models, revisions, and canonical JSON. No timestamps, randomness, network,
model calls, or environment-dependent decisions are used. Revision covers
effective metadata, catalog, hierarchy, breaks, continuity, reviewed decisions,
policy, and provenance. Explicit excluded disposition remains represented in
the resolved-flow provenance fingerprint.

Node, decision, group, position, and ownership indexes keep the normal path
approximately `O(n + e + g)`. Canonical key sorting is required for stable
fingerprints.

## Failure modes and non-responsibilities

Typed blocking reasons include unresolved flow, invalid hierarchy, duplicate or
missing ownership, incomplete inclusion disposition, missing semantic content,
missing asset provenance, conflicting review, unsupported content, unresolved
figure/caption state, and referential-integrity failure. Inputs and upstream
evidence remain unchanged after either success or failure.

M5A does not parse DOCX/PDF, inspect physical pages or floating geometry, infer
semantics/flow/breaks/placement, call AI providers, rewrite text, load image
bytes, generate EPUB resources, adapt M1B to V3, or persist checkpoints.
