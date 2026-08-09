# BookForge Core Engineering Principles

## Status and authority

This document is **NORMATIVE**. It defines constraints that every BookForge milestone, implementation, review, migration, Codex session, and AI agent MUST obey.

[`ARCHITECTURE.md`](ARCHITECTURE.md) describes the system. [`CONTRACTS.md`](CONTRACTS.md) describes data exchanged between modules. When descriptive documentation is ambiguous, this document governs implementation behavior. A genuine conflict MUST be reported and resolved explicitly; it MUST NOT be hidden behind a workaround.

The core pipeline is:

```text
Extraction
  -> Semantic Understanding
  -> Flow / Boundary Resolution
  -> Book Assembly
  -> Rendering
  -> Validation
  -> Immutable Artifact Consumers
```

## 1. Raw Evidence is immutable and authoritative

Raw Evidence is the authoritative representation of extracted source content. After extraction, downstream modules:

- MUST NOT rewrite raw text;
- MUST NOT overwrite or silently replace raw objects;
- MUST NOT delete evidence because it is excluded later;
- MUST NOT mutate extracted image bytes or table evidence;
- MUST NOT replace evidence with AI-generated content.

Transformations MUST create downstream representations and MUST remain traceable to their source evidence. Classification is not deletion. A footer classified as `RUNNING_FOOTER` MAY be omitted from a final BookModel, but its `RawParagraph` MUST remain preserved.

BookForge SHOULD follow:

```text
PRESERVE -> CLASSIFY -> DECIDE -> EXCLUDE FROM FINAL ARTIFACT IF APPROPRIATE
```

It MUST NOT follow `DETECT -> DELETE` in the core conversion pipeline.

## 2. AI never owns authoritative text

AI MAY read source text, classify evidence, identify relationships, and assess ambiguity. AI MUST NOT become the authoritative source of book text.

Authoritative rendering follows:

```text
SemanticFragment
  -> SourceTextReference
  -> EvidenceRegistry
  -> Raw Evidence
  -> rendered text
```

`SemanticFragment` MUST reference source evidence. It MUST NOT store an AI-regenerated authoritative copy for convenience. Within the core conversion pipeline, AI MUST NOT silently rewrite, paraphrase, translate, spell-correct, grammar-correct, summarize, expand, or shorten source content.

Any future user-requested editorial feature MUST be architecturally separate from conversion, MUST identify its output as edited content, and MUST NOT overwrite Raw Evidence.

## 3. Decisions are traceable, not privately reasoned

Every non-trivial semantic or flow decision SHOULD be auditable through structured data. Where applicable, the system SHOULD record:

- source evidence IDs;
- processing stage;
- classifier/engine identity and version;
- configuration or deterministic fingerprint;
- resulting classification or operation;
- confidence;
- review status;
- compact rationale or evidence codes.

Auditability MUST NOT depend on hidden chain-of-thought. BookForge MUST NOT store or require private LLM reasoning. Structured provenance and concise decision evidence are sufficient.

## 4. Stages have separate responsibilities

Each stage answers one question:

| Stage | Question | Responsibility |
|---|---|---|
| Extraction | What evidence exists? | Preserve source evidence and deterministic source order |
| Semantic / M3 | What is this content? | Classify meaning and semantic relationships |
| Flow + Boundary / M4 | How does it connect? | Resolve continuity, logical boundaries, and final reading placement |
| Book Assembly | What is the final logical book? | Materialize resolved decisions as a valid BookModel |
| Rendering / M1B | How is the logical book represented? | Render BookModel as EPUB without rediscovering semantics |

No stage MAY silently absorb another stage's ownership. Source-specific parser structures MUST stop at extraction boundaries. Downstream semantic and flow modules SHOULD operate on common evidence contracts and MUST NOT spread `if source == DOCX/PDF` logic unless an explicit evidence difference genuinely requires it.

## 5. Source layout is evidence, not structural truth

Physical layout MAY inform semantic or flow decisions, but it MUST NOT automatically become ebook structure:

```text
PDF page break       != EPUB logical page break
DOCX page layout     != EPUB page layout
DOCX image anchor    != final EPUB figure position
Word Heading 1       != automatically CHAPTER
font size            != automatically heading level
center alignment     != automatically title
source page number   != EPUB reading location
```

DOCX image anchors, PDF coordinates, typography, and page boundaries are source evidence. M3 MAY consider them. M4 MAY use them with semantic context. M1B MUST NOT inspect them to second-guess BookModel order.

## 6. M3 answers “What is this?”

M3 owns semantic interpretation. Potential concepts include book title, author, front matter, part/title, chapter heading/title, section heading, paragraph, quote, list/item, figure, caption, table, note, footnote, running header/footer, page number, decorative content, and unknown. Exact taxonomy MUST follow active contracts and the approved M3 milestone.

M3 MAY classify evidence and assign confidence. M3 MUST NOT make final decisions for:

- EPUB page or chapter-file breaks;
- paragraph joining;
- final figure placement;
- final chapter/part grouping;
- final BookModel ordering.

For example, M3 MAY classify `CHƯƠNG II` as a chapter heading with confidence. It MUST NOT directly emit `page_break_before = true` as a final rendering decision.

## 7. M4 answers “How does it flow?”

M4 owns logical continuity and boundary decisions, including where applicable:

- paragraph continuation and joining;
- resolution of deferred joins;
- chapter and part grouping;
- logical chapter/part boundaries;
- logical EPUB break decisions;
- final figure placement in reading flow;
- caption association;
- final ordering relationships.

M4 MUST express operations through downstream references/relationships. It MUST NOT mutate Raw Evidence.

Given:

```text
P100 = "He walked toward the"
P101 = "door and stopped."
```

M4 MAY produce a logical join operation over the two references. It MUST NOT rewrite either raw paragraph.

## 8. Logical break ownership

Logical break ownership is explicit:

```text
M3: CHAPTER_HEADING classification
  -> M4: CHAPTER_START boundary and grouping
  -> Book Assembly: Chapter in BookModel
  -> M1B: chapter_NNN.xhtml and spine order
```

M3 identifies semantic structure. M4 decides continuity and logical boundaries. Book Assembly materializes those decisions. M1B executes the valid BookModel. M1B MUST NOT rediscover chapter boundaries from source text, styles, coordinates, or anchors.

## 9. EPUB represents reading structure, not printed pages

BookForge targets reflowable EPUB. It MUST NOT treat pixel-perfect PDF reproduction as the objective. A 300-page PDF does not imply 300 EPUB breaks.

Parts and chapters will usually become logical boundaries after M4/Assembly resolves them. Sections, paragraphs, figures, and tables normally participate in continuous flow according to the resolved BookModel. Exact decisions belong to M4; M1B renders them.

## 10. Unknown is better than wrong

Uncertainty MUST remain representable with stage-appropriate states such as `UNKNOWN`, `DEFER`, `NEEDS_REVIEW`, or `FAILED`.

The system MUST NOT:

- label evidence `PARAGRAPH` merely because classification failed;
- invent chapter boundaries to keep a pipeline moving;
- discard ambiguous evidence silently;
- treat an unknown delivery result as sent;
- render unresolved `DEFER` joins by guessing.

Explicit uncertainty is a valid and preferred result when evidence is insufficient.

## 11. Deterministic before intelligent

Reliable deterministic operations MUST remain deterministic. LLM inference MUST NOT replace ordinary program logic.

Deterministic responsibilities include:

- SHA-256 and stable IDs;
- source ordering and reference resolution;
- XML escaping;
- ZIP/EPUB packaging;
- manifest and spine generation from BookModel;
- cache validation and fingerprinting;
- checkpoint management;
- referential integrity;
- structural validation.

Semantic questions such as chapter-heading, caption, recurring-footer, or meaningful-visual classification MAY use semantic intelligence. AI usage MUST be justified by semantic value, not convenience.

## 12. Hybrid decisions preserve ownership

Some outcomes combine semantic evidence with deterministic resolution. Paragraph joining is canonical: M3/AI MAY report likely continuation and confidence, but M4 owns the final boundary operation. AI MUST NOT concatenate Raw Evidence.

Likewise, M3 MAY identify a visual as a figure. M4 determines final reading placement. Book Assembly records it. M1B renders that placement without consulting a DOCX anchor.

## 13. Long books are incremental

BookForge MUST assume hundreds of pages and thousands of evidence objects. Semantic processing MUST be designed for incremental work. Future implementations SHOULD support:

- deterministic work units and batching;
- checkpoints and resume;
- bounded retries;
- configuration/model/input fingerprints;
- stale-result detection;
- reuse of completed valid work.

A late failure SHOULD NOT force an entire long book to restart when prior work remains valid.

## 14. Failure and unsupported content are visible

BookForge MUST NOT hide damage or unsupported content merely to produce an output. Unsupported drawings, missing assets, unresolved references, invalid tables, failed classifications, unresolved joins, invalid EPUBs, and unavailable validators MUST produce an appropriate warning, error, failure, or review state.

“An EPUB file was produced” does not prove conversion success. Artifact creation, structural validity, official validation availability, and review status are separate facts.

## 15. BookModel is logical truth for rendering

Once assembled and validated, active BookModel V2 is authoritative for logical reading structure. M1B MUST follow its front matter, chapter, section, fragment, figure, table, caption, navigation, and spine order. It MUST NOT inspect DOCX anchors, Word styles, PDF coordinates, source page numbers, or raw text patterns to infer a different structure.

Authority is deliberately split:

```text
Raw Evidence = authoritative source content
BookModel V2 = authoritative logical reading structure
EPUB = deterministic rendered artifact
```

Rendered characters still resolve through source references; logical ordering comes from BookModel.

## 16. Immutable artifact boundary

After EPUB generation produces `ImmutableEpubArtifact`, validation, Library, and Delivery MUST operate on that immutable artifact. They MUST NOT rebuild or modify book content as part of validation or sending.

Delivery providers receive a completed artifact, not mutable semantic state. Send failures MUST NOT corrupt or delete the original EPUB.

## 17. Contracts before workarounds

If active contracts cannot correctly represent required information, the affected implementation MUST stop and report `CONTRACT BLOCKER`.

Implementations MUST NOT compensate with:

- hidden dictionaries;
- required state encoded only in arbitrary metadata;
- duplicated authoritative text;
- undocumented conventions;
- bypassed referential integrity.

Contract evolution MUST be explicit, versioned, minimal, documented, and tested.

## 18. No silent cross-stage heuristics

Convenience heuristics MUST NOT run in the wrong layer. Forbidden examples include:

- M1A: uppercase text implies chapter;
- M3: chapter classification directly implies final page break;
- M1B: text beginning with `CHAPTER` creates new XHTML;
- Delivery: EPUB content is modified before sending.

If a decision belongs to a later stage, the current stage MUST preserve evidence and defer the decision.

## 19. Local-first semantic processing

Future semantic architecture SHOULD be local-first and capable of processing long books without mandatory per-page cloud costs. Cloud AI, if supported, SHOULD be an adapter or fallback rather than a core dependency.

Local-first does not mean AI-everywhere. Deterministic work remains deterministic. This principle does not authorize an AI runtime; each AI milestone requires explicit approval and contracts.

## 20. Boundary tests are first-class

Tests MUST verify prohibited behavior as well as expected output:

- M3 tests SHOULD prove no final page breaks, paragraph joins, or figure placement;
- M4 tests MUST prove Raw Evidence remains unchanged;
- M1B tests MUST prove BookModel order wins and no DOCX/PDF inference occurs;
- extraction tests MUST prove no semantic classification occurs;
- delivery tests MUST prove artifact immutability.

Architecture boundaries are testable product behavior, not documentation aspirations.

## Core decision ownership

| Decision | Owner |
|---|---|
| Extract DOCX paragraph/run/table/image evidence | M1A extraction |
| Extract future native PDF evidence | PDF extraction milestone |
| Preserve source text and source assets | Raw/Evidence layer |
| Identify book/chapter/section heading | M3 semantic processing |
| Identify paragraph, quote, list, caption, table meaning | M3 semantic processing |
| Identify running header/footer/page-number candidate | M3 semantic processing |
| Assign semantic confidence/review evidence | M3 semantic processing |
| Join split paragraphs or words | M4 Flow/Boundary |
| Group content into parts/chapters | M4 Flow/Boundary |
| Determine logical chapter/part breaks | M4 Flow/Boundary |
| Determine final figure placement and caption association | M4 Flow/Boundary |
| Materialize resolved logical structure as BookModel V2 | Book Assembly from M4 output |
| Render chapter XHTML | M1B rendering |
| Generate EPUB navigation and spine from BookModel | M1B rendering |
| Package deterministic EPUB | M1B rendering |
| Validate internal EPUB structure | M1B structural validator |
| Perform official EPUBCheck when available | EPUBCheck adapter |
| Store/export completed artifact | Library |
| Send completed artifact | Delivery |
| Modify Raw Evidence text in core conversion | **NEVER** |

## Non-negotiable invariants

- **I1.** Raw Evidence MUST NOT be silently mutated downstream.
- **I2.** AI-generated text MUST NOT replace authoritative source text.
- **I3.** Every rendered textual fragment MUST remain traceable to source evidence.
- **I4.** M3 MUST NOT determine final logical page/chapter breaks.
- **I5.** M3 MUST NOT perform final paragraph joins.
- **I6.** M3 MUST NOT determine final figure placement.
- **I7.** M4 MUST NOT mutate Raw Evidence.
- **I8.** M1B MUST NOT infer semantics from source layout or text patterns.
- **I9.** DOCX image anchors are evidence, not EPUB placement instructions.
- **I10.** PDF physical page boundaries are not EPUB logical boundaries.
- **I11.** Unknown and uncertain states MUST remain representable.
- **I12.** Unsupported content MUST NOT disappear silently.
- **I13.** Deterministic operations SHOULD NOT be delegated to AI.
- **I14.** BookModel V2 determines logical rendering order.
- **I15.** Delivery MUST operate on immutable EPUB artifacts.

## Instructions for future Codex and AI development agents

Before implementing any milestone, an agent MUST read:

1. `docs/PRINCIPLES.md`
2. `docs/ARCHITECTURE.md`
3. `docs/CONTRACTS.md`

The agent MUST also read milestone-specific documentation and active contracts. `PRINCIPLES.md` is normative.

If requested work conflicts with a Core Principle, the agent MUST stop the affected work and report:

```text
ARCHITECTURE PRINCIPLE CONFLICT

Requested behavior:
...

Conflicting principle/invariant:
...

Affected architecture/files:
...

Smallest proposed resolution:
...
```

The agent MUST NOT silently work around a principle, hide state in metadata, broaden scope, or modify a frozen stage without explicit approval.
