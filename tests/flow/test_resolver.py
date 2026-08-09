from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from bookforge.contracts.classification import (
    ClassificationProvenance,
    ClassificationResult,
    ClassifierIdentity,
    ClassifierKind,
    ReviewStatus,
)
from bookforge.contracts.common import DocumentId, ProcessingProvenance, TransformationStage
from bookforge.contracts.evidence import EvidenceRegistry
from bookforge.contracts.flow import (
    CaptionAssociationStatus,
    ContinuityType,
    InclusionType,
    FigurePlacement,
    LogicalBreakIntent,
    LogicalGroupType,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import classification_result_id
from bookforge.contracts.raw import RawParagraph
from bookforge.contracts.semantic import SemanticFragment, SemanticType
from bookforge.contracts.source import SourceTextReference
from bookforge.flow.models import FlowResolverInput, FlowResolverPolicy, FlowSourceFeatures
from bookforge.flow.policy import DEFAULT_RULES, FlowRule
from bookforge.flow.resolver import (
    EPOCH,
    DeterministicFlowResolver,
    FlowResolverInterrupted,
    build_flow_analysis_view,
    generate_flow_work_units,
)

DOC_ID = DocumentId("doc_aaaaaaaaaaaaaaaa")
FP = "a" * 64


def make_input(
    types_and_text: list[tuple[SemanticType, str]],
    *,
    features: dict[int, dict[str, Any]] | None = None,
    taxonomy: str = "bookforge-semantic-v1",
) -> tuple[FlowResolverInput, tuple[RawParagraph, ...]]:
    registry = EvidenceRegistry()
    raws: list[RawParagraph] = []
    fragments: list[SemanticFragment] = []
    classifications: dict[str, ClassificationResult] = {}
    source_features: dict[str, FlowSourceFeatures] = {}
    classifier = ClassifierIdentity(
        name="accepted-fixture", kind=ClassifierKind.DETERMINISTIC, version="1"
    )
    for index, (semantic_type, text) in enumerate(types_and_text, 1):
        raw = RawParagraph(
            id=f"docx_p{index:06d}", document_id=DOC_ID, order=index, text=text
        )
        registry.register(raw)
        raws.append(raw)
        fragment = SemanticFragment(
            id=f"sem_f{index:06d}",
            semantic_type=semantic_type,
            source_references=[SourceTextReference(source_id=raw.id)],
            provenance=ProcessingProvenance(
                document_id=DOC_ID,
                source_ids=[raw.id],
                stage=TransformationStage.SEMANTIC,
                processor="accepted-fixture",
                processor_version="1",
                created_at=EPOCH,
            ),
        )
        fragments.append(fragment)
        classification_id = classification_result_id(
            target_source_ids=[str(raw.id)],
            taxonomy_version=taxonomy,
            classifier_name=classifier.name,
            classifier_version=classifier.version,
            configuration_fingerprint=FP,
            input_fingerprint=FP,
            context_fingerprint=FP,
        )
        classifications[fragment.id] = ClassificationResult(
            id=classification_id,
            target_source_ids=(raw.id,),
            source_references=(SourceTextReference(source_id=raw.id),),
            semantic_type=semantic_type,
            confidence=1,
            review_status=ReviewStatus.NOT_REQUIRED,
            classifier=classifier,
            configuration_fingerprint=FP,
            input_fingerprint=FP,
            context_fingerprint=FP,
            taxonomy_version=taxonomy,
            provenance=ClassificationProvenance(
                document_id=DOC_ID, source_ids=(raw.id,), created_at=EPOCH
            ),
        )
        kwargs = (features or {}).get(index, {})
        source_features[fragment.id] = FlowSourceFeatures(source_order=index - 1, **kwargs)
    return (
        FlowResolverInput(
            document_id=DOC_ID,
            ordered_fragments=tuple(fragments),
            accepted_classifications=classifications,
            evidence_registry=registry,
            source_features=source_features,
            semantic_taxonomy_version=taxonomy,
        ),
        tuple(raws),
    )


def test_work_units_preserve_order_have_stable_ids_and_runtime_only_text() -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")]
    )
    units_a = generate_flow_work_units(resolver_input, FlowResolverPolicy())
    units_b = generate_flow_work_units(resolver_input, FlowResolverPolicy())
    assert units_a == units_b
    boundary = units_a[0]
    assert boundary.target_fragment_ids == ("sem_f000001", "sem_f000002")
    view = build_flow_analysis_view(boundary, resolver_input)
    assert view.target_texts == ("A", "B")
    assert "target_texts" not in boundary.model_dump_json()


def test_synthetic_structured_book_rules_groups_order_caption_and_exclusion(tmp_path: Path) -> None:
    sequence = [
        (SemanticType.BOOK_TITLE, "Book"),
        (SemanticType.PART_TITLE, "Part I"),
        (SemanticType.CHAPTER_HEADING, "Chapter 1"),
        (SemanticType.CHAPTER_TITLE, "Opening"),
        (SemanticType.PARAGRAPH, "P1"),
        (SemanticType.PARAGRAPH, "P2"),
        (SemanticType.FIGURE, "figure evidence"),
        (SemanticType.CAPTION, "caption"),
        (SemanticType.PARAGRAPH, "P3"),
        (SemanticType.SECTION_HEADING, "Section"),
        (SemanticType.PARAGRAPH, "P4"),
        (SemanticType.CHAPTER_HEADING, "Chapter 2"),
        (SemanticType.CHAPTER_TITLE, "Second"),
        (SemanticType.PARAGRAPH, "P5"),
        (SemanticType.PART_TITLE, "Part II"),
        (SemanticType.CHAPTER_HEADING, "Chapter 3"),
        (SemanticType.CHAPTER_TITLE, "Third"),
        (SemanticType.PARAGRAPH, "P6"),
        (SemanticType.RUNNING_FOOTER, "footer"),
    ]
    resolver_input, raws = make_input(
        sequence,
        features={7: {"logical_sequence_explicit": True, "image_only_container": True}},
    )
    before = tuple(raw.model_dump_json() for raw in raws)
    report = DeterministicFlowResolver().run(resolver_input, tmp_path)
    flow = report.resolved_flow
    assert flow is not None
    assert report.failed == 0
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.PART) == 2
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.CHAPTER) == 3
    assert [group.group_type for group in flow.groups].count(LogicalGroupType.SECTION) == 1
    chapter_boundaries = [
        value for value in flow.boundaries if value.structural_boundary is StructuralBoundaryType.CHAPTER
    ]
    assert all(value.break_intent is LogicalBreakIntent.NEW_PAGE for value in chapter_boundaries)
    section = next(value for value in flow.boundaries if value.structural_boundary is StructuralBoundaryType.SECTION)
    assert section.break_intent is LogicalBreakIntent.NONE
    assert flow.figure_placements[0].previous_fragment_id == "sem_f000006"
    assert flow.figure_placements[0].next_fragment_id == "sem_f000008"
    assert flow.caption_associations[0].status is CaptionAssociationStatus.ASSOCIATED
    assert flow.caption_associations[0].figure_fragment_id == "sem_f000007"
    footer = next(value for value in flow.inclusion_decisions if value.target_fragment_id == "sem_f000019")
    assert footer.inclusion is InclusionType.EXCLUDE
    assert "sem_f000019" in flow.source_fragment_ids
    assert "sem_f000019" not in flow.ordered_fragment_ids
    assert tuple(raw.model_dump_json() for raw in raws) == before
    assert "epub" not in flow.model_dump_json().lower()
    assert "bookmodel" not in flow.model_dump_json().lower()


@pytest.mark.parametrize(
    ("semantic_type", "expected"),
    [
        (SemanticType.PART_TITLE, StructuralBoundaryType.PART),
        (SemanticType.CHAPTER_HEADING, StructuralBoundaryType.CHAPTER),
        (SemanticType.SECTION_HEADING, StructuralBoundaryType.SECTION),
        (SemanticType.SUBSECTION_HEADING, StructuralBoundaryType.SUBSECTION),
    ],
)
def test_structural_rules_only_consume_accepted_semantics(
    tmp_path: Path, semantic_type: SemanticType, expected: StructuralBoundaryType
) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "before"), (semantic_type, "accepted")]
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    boundary = flow.boundaries[0]
    assert boundary.structural_boundary is expected
    expected_break = (
        LogicalBreakIntent.NEW_PAGE
        if expected in {StructuralBoundaryType.PART, StructuralBoundaryType.CHAPTER}
        else LogicalBreakIntent.NONE
    )
    assert boundary.break_intent is expected_break


def test_break_policy_override_changes_fingerprint_decision_and_cache(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "before"), (SemanticType.CHAPTER_HEADING, "chapter")]
    )
    first = DeterministicFlowResolver().run(resolver_input, tmp_path)
    changed_policy = FlowResolverPolicy(chapter_break_new_page=False, policy_version="flow-v2")
    second = DeterministicFlowResolver(changed_policy).run(resolver_input, tmp_path)
    assert first.resolved_flow is not None and second.resolved_flow is not None
    assert first.resolved_flow.boundaries[0].break_intent is LogicalBreakIntent.NEW_PAGE
    assert second.resolved_flow.boundaries[0].break_intent is LogicalBreakIntent.NONE
    assert second.stale > 0
    assert first.resolved_flow.boundaries[0].audit.decision_id != second.resolved_flow.boundaries[0].audit.decision_id


def test_explicit_trailing_hyphen_and_space_continuations_preserve_evidence(tmp_path: Path) -> None:
    features = {
        1: {"continuation_group_id": "source-paragraph-1", "physical_segment_id": "page-10"},
        2: {"continuation_group_id": "source-paragraph-1", "source_boundary_before": True, "physical_segment_id": "page-11"},
        3: {"continuation_group_id": "source-paragraph-2"},
        4: {"continuation_group_id": "source-paragraph-2", "source_boundary_before": True},
    }
    resolver_input, raws = make_input(
        [
            (SemanticType.PARAGRAPH, "compre-"),
            (SemanticType.PARAGRAPH, "hensive"),
            (SemanticType.PARAGRAPH, "coffee"),
            (SemanticType.PARAGRAPH, "house"),
        ],
        features=features,
    )
    before = tuple(raw.model_dump_json() for raw in raws)
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.boundaries[0].continuity is ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN
    assert flow.boundaries[2].continuity is ContinuityType.JOIN_WITH_SPACE
    assert flow.boundaries[0].break_intent is LogicalBreakIntent.NONE
    assert tuple(raw.model_dump_json() for raw in raws) == before
    persisted = "".join(path.read_text() for path in (tmp_path / "flow").rglob("*.json"))
    assert "comprehensive" not in persisted


def test_source_continuation_signal_is_required_for_join(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "compre-"), (SemanticType.PARAGRAPH, "hensive")],
        features={
            1: {"continuation_group_id": "same-source"},
            2: {"continuation_group_id": "same-source", "source_boundary_before": False},
        },
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.boundaries[0].continuity is ContinuityType.UNRESOLVED


def test_ambiguous_paragraphs_are_unresolved_not_language_guessed(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "no punctuation"), (SemanticType.PARAGRAPH, "lowercase")]
    )
    report = DeterministicFlowResolver().run(resolver_input, tmp_path)
    assert report.resolved_flow is not None
    assert report.resolved_flow.boundaries[0].continuity is ContinuityType.UNRESOLVED
    assert report.resolved_flow.boundaries[0].audit.review_status is ReviewStatus.NEEDS_REVIEW
    assert report.failed == 0


def test_figure_anchor_does_not_control_logical_geometry(tmp_path: Path) -> None:
    sequence = [
        (SemanticType.PARAGRAPH, "A"),
        (SemanticType.FIGURE, "figure evidence"),
        (SemanticType.PARAGRAPH, "B"),
    ]
    first_input, _ = make_input(
        sequence,
        features={
            2: {
                "logical_sequence_explicit": True,
                "source_anchor_evidence_ids": ("docx_p000001",),
            }
        },
    )
    second_input, _ = make_input(
        sequence,
        features={
            2: {
                "logical_sequence_explicit": True,
                "source_anchor_evidence_ids": ("docx_p000003",),
            }
        },
    )
    first = DeterministicFlowResolver().run(first_input, tmp_path / "one").resolved_flow
    second = DeterministicFlowResolver().run(second_input, tmp_path / "two").resolved_flow
    assert first is not None and second is not None
    assert first.ordered_fragment_ids == second.ordered_fragment_ids
    assert first.figure_placements[0].previous_fragment_id == second.figure_placements[0].previous_fragment_id
    assert "x" not in FigurePlacement.model_fields


def test_ambiguous_two_figures_one_caption_remains_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [
            (SemanticType.FIGURE, "f1"),
            (SemanticType.FIGURE, "f2"),
            (SemanticType.CAPTION, "caption"),
        ]
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    association = flow.caption_associations[0]
    assert association.status is CaptionAssociationStatus.UNRESOLVED
    assert set(association.candidate_figure_fragment_ids) == {"sem_f000001", "sem_f000002"}


@pytest.mark.parametrize("kind", [SemanticType.TABLE, SemanticType.LIST])
def test_explicit_table_and_list_continuation_only_emit_operations(
    tmp_path: Path, kind: SemanticType
) -> None:
    resolver_input, _ = make_input(
        [(kind, "first"), (kind, "second")],
        features={
            1: {"continuation_group_id": "logical-1"},
            2: {"continuation_group_id": "logical-1", "source_boundary_before": True},
        },
    )
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    expected = ContinuityType.CONTINUE_TABLE if kind is SemanticType.TABLE else ContinuityType.CONTINUE_LIST
    assert flow.boundaries[0].continuity is expected
    serialized = flow.boundaries[0].model_dump_json()
    assert "merged_text" not in serialized
    assert "rows" not in serialized


@pytest.mark.parametrize(
    "kind",
    [SemanticType.RUNNING_HEADER, SemanticType.RUNNING_FOOTER, SemanticType.PAGE_NUMBER, SemanticType.DECORATIVE],
)
def test_explicit_artifact_semantics_are_excluded_but_preserved(
    tmp_path: Path, kind: SemanticType
) -> None:
    resolver_input, raws = make_input([(kind, "evidence")])
    raw_before = raws[0].model_dump_json()
    fragment_before = resolver_input.ordered_fragments[0].model_dump_json()
    classification_before = resolver_input.accepted_classifications["sem_f000001"].model_dump_json()
    flow = DeterministicFlowResolver().run(resolver_input, tmp_path).resolved_flow
    assert flow is not None
    assert flow.inclusion_decisions[0].inclusion is InclusionType.EXCLUDE
    assert flow.ordered_fragment_ids == ()
    assert flow.source_fragment_ids == ("sem_f000001",)
    assert raws[0].model_dump_json() == raw_before
    assert resolver_input.ordered_fragments[0].model_dump_json() == fragment_before
    assert resolver_input.accepted_classifications["sem_f000001"].model_dump_json() == classification_before


class FailOnceRule:
    rule_id = "fail-once"
    version = "1"
    priority = 1000
    work_unit_kind = DEFAULT_RULES[0].work_unit_kind

    def __init__(self) -> None:
        self.failed = False

    def evaluate(self, view, policy, audit):  # type: ignore[no-untyped-def]
        if view.work_unit.sequence_index == 1 and not self.failed:
            self.failed = True
            raise RuntimeError("safe failure")
        return None


def test_failure_isolation_retry_and_failed_differs_from_unresolved(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")]
    )
    failing = FailOnceRule()
    resolver = DeterministicFlowResolver(rules=(failing, *DEFAULT_RULES))
    first = resolver.run(resolver_input, tmp_path)
    assert first.failed == 1
    assert first.resolved_flow is None
    assert len(tuple((tmp_path / "flow/failures").glob("*.json"))) == 1
    second = resolver.run(resolver_input, tmp_path)
    assert second.failed == 0
    assert second.resolved_flow is not None
    assert second.unresolved > 0
    assert second.reused == second.total_work_units - 1
    assert not tuple((tmp_path / "flow/failures").glob("*.json"))


@pytest.mark.parametrize("change", ["semantic", "context", "taxonomy", "policy", "resolver", "evidence"])
def test_stale_inputs_are_recomputed(tmp_path: Path, change: str) -> None:
    original, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")]
    )
    DeterministicFlowResolver().run(original, tmp_path)
    changed = original
    policy = FlowResolverPolicy()
    rules: tuple[FlowRule, ...] = DEFAULT_RULES
    if change == "semantic":
        changed, _ = make_input([(SemanticType.QUOTE, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")])
    elif change == "context":
        changed, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.QUOTE, "B"), (SemanticType.PARAGRAPH, "C")])
    elif change == "taxonomy":
        changed, _ = make_input([(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")], taxonomy="taxonomy-v2")
    elif change == "policy":
        policy = FlowResolverPolicy(policy_version="flow-v2", chapter_break_new_page=False)
    elif change == "resolver":
        rules = (*DEFAULT_RULES, FailOnceRule())
    else:
        changed, _ = make_input([(SemanticType.PARAGRAPH, "changed evidence"), (SemanticType.PARAGRAPH, "B"), (SemanticType.PARAGRAPH, "C")])
    report = DeterministicFlowResolver(policy, rules).run(changed, tmp_path)
    assert report.stale > 0
    assert report.reused < report.total_work_units


def test_interruption_resume_long_book_and_clean_determinism(tmp_path: Path) -> None:
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, f"Paragraph {index}") for index in range(1, 1001)]
    )
    interrupted_workspace = tmp_path / "interrupted"
    with pytest.raises(FlowResolverInterrupted):
        DeterministicFlowResolver().run(
            resolver_input, interrupted_workspace, interrupt_after=173
        )
    resumed = DeterministicFlowResolver().run(resolver_input, interrupted_workspace)
    assert resumed.failed == 0
    assert resumed.reused == 173
    assert resumed.total_work_units == 1999
    assert resumed.resolved_flow is not None

    clean_a = tmp_path / "clean_a"
    clean_b = tmp_path / "clean_b"
    flow_a = DeterministicFlowResolver().run(resolver_input, clean_a).resolved_flow
    flow_b = DeterministicFlowResolver().run(resolver_input, clean_b).resolved_flow
    assert flow_a == flow_b == resumed.resolved_flow
    files_a = {path.relative_to(clean_a): path.read_bytes() for path in (clean_a / "flow").rglob("*.json")}
    files_b = {path.relative_to(clean_b): path.read_bytes() for path in (clean_b / "flow").rglob("*.json")}
    assert files_a == files_b
    assert all(b"Paragraph 1" not in data for data in files_a.values())


def test_flow_workspace_does_not_modify_extraction_or_semantic_inputs(tmp_path: Path) -> None:
    immutable_paths = (
        tmp_path / "source.json",
        tmp_path / "raw_document.json",
        tmp_path / "warnings.json",
        tmp_path / "semantic" / "manifest.json",
        tmp_path / "semantic" / "results" / "result.json",
        tmp_path / "semantic" / "fragments" / "fragment.json",
    )
    for index, path in enumerate(immutable_paths):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"immutable-{index}", encoding="utf-8")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in immutable_paths}
    resolver_input, _ = make_input(
        [(SemanticType.PARAGRAPH, "A"), (SemanticType.PARAGRAPH, "B")]
    )
    DeterministicFlowResolver().run(resolver_input, tmp_path)
    after = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in immutable_paths}
    assert after == before
