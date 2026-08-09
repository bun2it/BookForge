from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import cast

from bookforge.contracts.classification import ReviewStatus
from bookforge.contracts.common import FragmentId
from bookforge.contracts.flow import (
    CaptionAssociation,
    CaptionAssociationStatus,
    FigurePlacement,
    FigurePlacementRelation,
    FlowDecisionAudit,
    FlowDecisionProvenance,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalGroup,
    LogicalGroupType,
    ResolvedContentFlow,
    ResolvedFlowProvenance,
    ResolverIdentity,
    ResolverKind,
    StructuralBoundaryType,
)
from bookforge.contracts.ids import flow_decision_id, flow_group_id
from bookforge.contracts.semantic import SemanticFragment, SemanticType

from .models import (
    FLOW_RESOLVER_VERSION,
    FlowAnalysisView,
    FlowFailureCategory,
    FlowFailureRecord,
    FlowManifest,
    FlowProcessingSummary,
    FlowResolverInput,
    FlowResolverPolicy,
    FlowResolverReport,
    FlowSourceFeatures,
    FlowWorkUnit,
    FlowWorkUnitKind,
)
from .policy import DEFAULT_RULES, FlowRule, LocalDecision
from .workspace import FlowWorkspace, FlowWorkspaceError

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class FlowResolverError(RuntimeError):
    pass


class FlowResolverInterrupted(FlowResolverError):
    pass


def canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def policy_fingerprint(policy: FlowResolverPolicy) -> str:
    return canonical_fingerprint(policy.model_dump(mode="json"))


def _resolved_text_hash(fragment: SemanticFragment, resolver_input: FlowResolverInput) -> str:
    segments = [
        resolver_input.evidence_registry.resolve_text(reference)
        for reference in fragment.source_references
    ]
    return canonical_fingerprint(segments)


def _fragment_payload(fragment: SemanticFragment, resolver_input: FlowResolverInput) -> dict[str, object]:
    classification = resolver_input.accepted_classifications.get(fragment.id)
    feature = resolver_input.source_features.get(
        fragment.id, FlowSourceFeatures(source_order=0)
    )
    return {
        "fragment": fragment.model_dump(mode="json"),
        "classification": classification.model_dump(mode="json") if classification else None,
        "source_text_hash": _resolved_text_hash(fragment, resolver_input),
        "source_features": feature.model_dump(mode="json"),
    }


def generate_flow_work_units(
    resolver_input: FlowResolverInput,
    policy: FlowResolverPolicy,
) -> tuple[FlowWorkUnit, ...]:
    fragments = resolver_input.ordered_fragments
    if len({fragment.id for fragment in fragments}) != len(fragments):
        raise FlowResolverError("flow input contains duplicate fragment IDs")
    configured_policy_fingerprint = policy_fingerprint(policy)
    fragment_positions = {fragment.id: index for index, fragment in enumerate(fragments)}
    units: list[FlowWorkUnit] = []

    def create(kind: FlowWorkUnitKind, targets: tuple[SemanticFragment, ...], sequence: int) -> None:
        target_ids = tuple(fragment.id for fragment in targets)
        relevant_index = min(fragment_positions[fragment.id] for fragment in targets)
        before = fragments[max(0, relevant_index - policy.context_size) : relevant_index]
        after_start = relevant_index + len(targets)
        after = fragments[after_start : after_start + policy.context_size]
        context_payload = [
            _fragment_payload(fragment, resolver_input) for fragment in (*before, *after)
        ]
        context_fp = canonical_fingerprint(context_payload)
        input_fp = canonical_fingerprint(
            {
                "document_id": str(resolver_input.document_id),
                "kind": kind.value,
                "targets": [_fragment_payload(fragment, resolver_input) for fragment in targets],
                "context": context_payload,
                "taxonomy": resolver_input.semantic_taxonomy_version,
                "policy": configured_policy_fingerprint,
            }
        )
        unit_id = "fwu_" + canonical_fingerprint(
            {
                "document_id": str(resolver_input.document_id),
                "kind": kind.value,
                "target_ids": [str(value) for value in target_ids],
                "sequence": sequence,
            }
        )[:20]
        classifications = tuple(
            str(result.id)
            for fragment in targets
            if (result := resolver_input.accepted_classifications.get(fragment.id)) is not None
        )
        units.append(
            FlowWorkUnit(
                work_unit_id=unit_id,
                kind=kind,
                document_id=resolver_input.document_id,
                sequence_index=sequence,
                target_fragment_ids=target_ids,
                context_before_fragment_ids=tuple(fragment.id for fragment in before),
                context_after_fragment_ids=tuple(fragment.id for fragment in after),
                accepted_semantic_types=tuple(fragment.semantic_type for fragment in targets),
                classification_result_ids=classifications,
                input_fingerprint=input_fp,
                context_fingerprint=context_fp,
                policy_fingerprint=configured_policy_fingerprint,
            )
        )

    sequence = 0
    for index in range(len(fragments) - 1):
        create(FlowWorkUnitKind.BOUNDARY, (fragments[index], fragments[index + 1]), sequence)
        sequence += 1
    for fragment in fragments:
        create(FlowWorkUnitKind.INCLUSION, (fragment,), sequence)
        sequence += 1
    for fragment in fragments:
        if fragment.semantic_type is SemanticType.FIGURE:
            create(FlowWorkUnitKind.FIGURE_PLACEMENT, (fragment,), sequence)
            sequence += 1
        elif fragment.semantic_type is SemanticType.CAPTION:
            create(FlowWorkUnitKind.CAPTION_ASSOCIATION, (fragment,), sequence)
            sequence += 1
    return tuple(units)


def build_flow_analysis_view(
    unit: FlowWorkUnit, resolver_input: FlowResolverInput
) -> FlowAnalysisView:
    by_id = {fragment.id: fragment for fragment in resolver_input.ordered_fragments}
    targets = tuple(by_id[fragment_id] for fragment_id in unit.target_fragment_ids)
    def unjoined_text(fragment: SemanticFragment) -> str | None:
        if len(fragment.source_references) != 1:
            return None
        return resolver_input.evidence_registry.resolve_text(fragment.source_references[0])

    texts = tuple(unjoined_text(fragment) for fragment in targets)
    return FlowAnalysisView(
        work_unit=unit,
        target_fragments=targets,
        target_texts=texts,
        context_before_types=tuple(
            by_id[fragment_id].semantic_type for fragment_id in unit.context_before_fragment_ids
        ),
        context_after_types=tuple(
            by_id[fragment_id].semantic_type for fragment_id in unit.context_after_fragment_ids
        ),
        source_features=tuple(
            resolver_input.source_features.get(
                fragment.id, FlowSourceFeatures(source_order=index)
            )
            for index, fragment in enumerate(targets)
        ),
    )


class DeterministicFlowResolver:
    identity = ResolverIdentity(
        name="bookforge.deterministic_flow",
        kind=ResolverKind.DETERMINISTIC,
        version=FLOW_RESOLVER_VERSION,
    )

    def __init__(
        self,
        policy: FlowResolverPolicy = FlowResolverPolicy(),
        rules: Sequence[FlowRule] = DEFAULT_RULES,
    ) -> None:
        self.policy = policy
        self.rules = tuple(sorted(rules, key=lambda rule: (-rule.priority, rule.rule_id)))
        self.configuration_fingerprint = canonical_fingerprint(
            {
                "identity": self.identity.model_dump(mode="json"),
                "rules": [(rule.rule_id, rule.version, rule.priority) for rule in self.rules],
            }
        )

    def run(
        self,
        resolver_input: FlowResolverInput,
        document_workspace: Path,
        *,
        interrupt_after: int | None = None,
    ) -> FlowResolverReport:
        units = generate_flow_work_units(resolver_input, self.policy)
        workspace = FlowWorkspace(document_workspace)
        workspace.prepare()
        for unit in units:
            workspace.write_unit(unit)

        completed = failed = needs_review = reused = stale = newly_processed = 0
        decisions: dict[str, LocalDecision] = {}

        def manifest() -> None:
            workspace.write_manifest(
                FlowManifest(
                    document_id=resolver_input.document_id,
                    semantic_taxonomy_version=resolver_input.semantic_taxonomy_version,
                    policy_version=self.policy.policy_version,
                    policy_fingerprint=policy_fingerprint(self.policy),
                    resolver_configuration_fingerprint=self.configuration_fingerprint,
                    total_fragments=len(resolver_input.ordered_fragments),
                    total_work_units=len(units),
                    summary=FlowProcessingSummary(
                        pending=max(0, len(units) - completed - failed),
                        completed=completed,
                        failed=failed,
                        needs_review=needs_review,
                        reused=reused,
                        stale=stale,
                    ),
                )
            )

        manifest()
        for unit in units:
            decision: LocalDecision | None = None
            try:
                cached = workspace.load_local_decision(unit)
                if cached is not None:
                    typed_cached = cast(LocalDecision, cached)
                    if self._compatible(typed_cached, unit, resolver_input):
                        decision = typed_cached
                        reused += 1
                    else:
                        stale += 1
                if decision is None:
                    decision = self._evaluate(unit, resolver_input)
                    workspace.write_local_decision(unit, decision)
                    newly_processed += 1
                decisions[unit.work_unit_id] = decision
                workspace.clear_failure(unit.work_unit_id)
                completed += 1
                if decision.audit.review_status is ReviewStatus.NEEDS_REVIEW:
                    needs_review += 1
            except FlowWorkspaceError:
                stale += 1
                try:
                    decision = self._evaluate(unit, resolver_input)
                    workspace.write_local_decision(unit, decision)
                    decisions[unit.work_unit_id] = decision
                    workspace.clear_failure(unit.work_unit_id)
                    completed += 1
                    needs_review += decision.audit.review_status is ReviewStatus.NEEDS_REVIEW
                    newly_processed += 1
                except Exception as error:
                    failed += 1
                    self._record_failure(workspace, unit, error)
            except Exception as error:
                failed += 1
                self._record_failure(workspace, unit, error)
                if not self.policy.continue_on_failure:
                    manifest()
                    raise FlowResolverError(f"flow unit failed: {unit.work_unit_id}") from error
            manifest()
            if interrupt_after is not None and newly_processed >= interrupt_after:
                raise FlowResolverInterrupted(
                    f"flow resolver interrupted after {newly_processed} local decisions"
                )

        resolved: ResolvedContentFlow | None = None
        if failed == 0:
            resolved = self._finalize(resolver_input, tuple(decisions.values()))
            workspace.write_groups(resolved.groups)
            workspace.write_resolved_flow(resolved)
        boundaries = tuple(d for d in decisions.values() if isinstance(d, LogicalBoundaryDecision))
        inclusions = tuple(d for d in decisions.values() if isinstance(d, InclusionDecision))
        placements = tuple(d for d in decisions.values() if isinstance(d, FigurePlacement))
        captions = tuple(d for d in decisions.values() if isinstance(d, CaptionAssociation))
        unresolved = sum(self._is_unresolved(decision) for decision in decisions.values())
        return FlowResolverReport(
            total_fragments=len(resolver_input.ordered_fragments),
            total_work_units=len(units),
            completed=completed,
            failed=failed,
            needs_review=needs_review,
            reused=reused,
            stale=stale,
            boundary_decisions=len(boundaries),
            inclusion_decisions=len(inclusions),
            placements=len(placements),
            caption_associations=len(captions),
            groups=len(resolved.groups) if resolved else 0,
            unresolved=unresolved,
            resolved_flow=resolved,
        )

    def _evaluate(self, unit: FlowWorkUnit, resolver_input: FlowResolverInput) -> LocalDecision:
        view = build_flow_analysis_view(unit, resolver_input)
        expected_id = self._decision_id(unit)
        audit = FlowDecisionAudit(
            decision_id=expected_id,
            confidence=1.0,
            review_status=ReviewStatus.NOT_REQUIRED,
            provenance=FlowDecisionProvenance(
                document_id=resolver_input.document_id,
                resolver=self.identity,
                configuration_fingerprint=self.configuration_fingerprint,
                input_fingerprint=unit.input_fingerprint,
                semantic_taxonomy_version=resolver_input.semantic_taxonomy_version,
                flow_policy_version=self.policy.policy_version,
                classification_result_ids=unit.classification_result_ids,
                created_at=EPOCH,
            ),
        )
        for rule in self.rules:
            if rule.work_unit_kind is unit.kind:
                decision = rule.evaluate(view, self.policy, audit)
                if decision is not None:
                    if (
                        decision.audit.confidence < self.policy.review_threshold
                        and decision.audit.review_status is ReviewStatus.NOT_REQUIRED
                    ):
                        decision = decision.model_copy(
                            update={
                                "audit": decision.audit.model_copy(
                                    update={"review_status": ReviewStatus.NEEDS_REVIEW}
                                )
                            }
                        )
                    return decision
        raise FlowResolverError(f"no deterministic rule handled {unit.kind.value}")

    def _decision_id(self, unit: FlowWorkUnit) -> str:
        return flow_decision_id(
            decision_kind=unit.kind.value,
            fragment_ids=[str(value) for value in unit.target_fragment_ids],
            input_fingerprint=unit.input_fingerprint,
            configuration_fingerprint=self.configuration_fingerprint,
            policy_version=self.policy.policy_version,
        )

    def _compatible(
        self, decision: LocalDecision, unit: FlowWorkUnit, resolver_input: FlowResolverInput
    ) -> bool:
        provenance = decision.audit.provenance
        return (
            str(decision.audit.decision_id) == self._decision_id(unit)
            and provenance.document_id == resolver_input.document_id
            and provenance.input_fingerprint == unit.input_fingerprint
            and provenance.configuration_fingerprint == self.configuration_fingerprint
            and provenance.semantic_taxonomy_version == resolver_input.semantic_taxonomy_version
            and provenance.flow_policy_version == self.policy.policy_version
            and tuple(str(value) for value in provenance.classification_result_ids)
            == unit.classification_result_ids
            and self._decision_targets_match(decision, unit)
        )

    @staticmethod
    def _decision_targets_match(decision: LocalDecision, unit: FlowWorkUnit) -> bool:
        targets = unit.target_fragment_ids
        if isinstance(decision, LogicalBoundaryDecision):
            return (
                len(targets) == 2
                and decision.preceding_fragment_id == targets[0]
                and decision.following_fragment_id == targets[1]
            )
        if isinstance(decision, InclusionDecision):
            return decision.target_fragment_id == targets[0]
        if isinstance(decision, FigurePlacement):
            return decision.figure_fragment_id == targets[0]
        return decision.caption_fragment_id == targets[0]

    def _finalize(
        self, resolver_input: FlowResolverInput, decisions: tuple[LocalDecision, ...]
    ) -> ResolvedContentFlow:
        boundaries = tuple(d for d in decisions if isinstance(d, LogicalBoundaryDecision))
        inclusions = tuple(d for d in decisions if isinstance(d, InclusionDecision))
        placements = tuple(d for d in decisions if isinstance(d, FigurePlacement))
        captions = tuple(d for d in decisions if isinstance(d, CaptionAssociation))
        excluded = {
            decision.target_fragment_id
            for decision in inclusions
            if decision.inclusion is InclusionType.EXCLUDE
        }
        final_order = tuple(
            fragment.id for fragment in resolver_input.ordered_fragments if fragment.id not in excluded
        )
        groups = self._groups(resolver_input, final_order, boundaries)
        unresolved_ids = tuple(
            decision.audit.decision_id
            for decision in decisions
            if self._is_unresolved(decision)
        )
        flow_input_fp = canonical_fingerprint(
            {
                "units": [
                    (str(decision.audit.decision_id), decision.audit.provenance.input_fingerprint)
                    for decision in decisions
                ],
                "final_order": [str(value) for value in final_order],
            }
        )
        revision = "flow_" + flow_input_fp[:20]
        return ResolvedContentFlow(
            revision=revision,
            source_fragment_ids=tuple(fragment.id for fragment in resolver_input.ordered_fragments),
            ordered_fragment_ids=final_order,
            boundaries=boundaries,
            groups=groups,
            figure_placements=placements,
            caption_associations=captions,
            inclusion_decisions=inclusions,
            unresolved_decision_ids=unresolved_ids,
            provenance=ResolvedFlowProvenance(
                document_id=resolver_input.document_id,
                resolver=self.identity,
                configuration_fingerprint=self.configuration_fingerprint,
                input_fingerprint=flow_input_fp,
                semantic_taxonomy_version=resolver_input.semantic_taxonomy_version,
                flow_policy_version=self.policy.policy_version,
                created_at=EPOCH,
            ),
        )

    def _groups(
        self,
        resolver_input: FlowResolverInput,
        final_order: tuple[FragmentId, ...],
        boundaries: tuple[LogicalBoundaryDecision, ...],
    ) -> tuple[LogicalGroup, ...]:
        by_id = {fragment.id: fragment for fragment in resolver_input.ordered_fragments}
        boundary_by_start = {
            boundary.following_fragment_id: boundary
            for boundary in boundaries
            if boundary.structural_boundary
            not in {StructuralBoundaryType.NONE, StructuralBoundaryType.UNRESOLVED}
        }
        type_map = {
            StructuralBoundaryType.PART: (LogicalGroupType.PART, 1),
            StructuralBoundaryType.CHAPTER: (LogicalGroupType.CHAPTER, 2),
            StructuralBoundaryType.SECTION: (LogicalGroupType.SECTION, 3),
            StructuralBoundaryType.SUBSECTION: (LogicalGroupType.SUBSECTION, 4),
        }
        starts: list[tuple[int, LogicalBoundaryDecision, LogicalGroupType, int]] = []
        for index, fragment_id in enumerate(final_order):
            boundary = boundary_by_start.get(fragment_id)
            if boundary is not None and boundary.structural_boundary in type_map:
                group_type, level = type_map[boundary.structural_boundary]
                starts.append((index, boundary, group_type, level))
        counts: dict[LogicalGroupType, int] = {}
        specs: list[tuple[int, int, LogicalBoundaryDecision, LogicalGroupType, int, str]] = []
        for position, (start, boundary, group_type, level) in enumerate(starts):
            end = len(final_order)
            for next_start, _, _, next_level in starts[position + 1 :]:
                if next_level <= level:
                    end = next_start
                    break
            counts[group_type] = counts.get(group_type, 0) + 1
            group_id = flow_group_id(group_type.value, counts[group_type])
            specs.append((start, end, boundary, group_type, level, group_id))
        groups: list[LogicalGroup] = []
        for start, end, boundary, group_type, level, group_id in specs:
            parent_id = None
            parents = [spec for spec in specs if spec[0] < start < spec[1] and spec[4] < level]
            if parents:
                parent_id = parents[-1][5]
            members = tuple(final_order[start:end])
            opening_types = {
                LogicalGroupType.PART: {SemanticType.PART_TITLE, SemanticType.SUBTITLE},
                LogicalGroupType.CHAPTER: {
                    SemanticType.CHAPTER_HEADING,
                    SemanticType.CHAPTER_NUMBER,
                    SemanticType.CHAPTER_TITLE,
                    SemanticType.SUBTITLE,
                },
                LogicalGroupType.SECTION: {SemanticType.SECTION_HEADING},
                LogicalGroupType.SUBSECTION: {SemanticType.SUBSECTION_HEADING},
            }[group_type]
            opening: list[FragmentId] = []
            for fragment_id in members:
                if by_id[fragment_id].semantic_type in opening_types:
                    opening.append(fragment_id)
                else:
                    break
            groups.append(
                LogicalGroup(
                    group_id=group_id,
                    group_type=group_type,
                    opening_fragment_ids=tuple(opening),
                    member_fragment_ids=members,
                    parent_group_id=parent_id,
                    boundary_decision_id=boundary.audit.decision_id,
                )
            )
        return tuple(groups)

    @staticmethod
    def _is_unresolved(decision: LocalDecision) -> bool:
        if isinstance(decision, LogicalBoundaryDecision):
            return decision.continuity.value == "unresolved" or decision.structural_boundary.value == "unresolved" or decision.break_intent.value == "unresolved"
        if isinstance(decision, InclusionDecision):
            return decision.inclusion is InclusionType.UNRESOLVED
        if isinstance(decision, FigurePlacement):
            return decision.relation is FigurePlacementRelation.UNRESOLVED
        return decision.status is CaptionAssociationStatus.UNRESOLVED

    def _record_failure(self, workspace: FlowWorkspace, unit: FlowWorkUnit, error: Exception) -> None:
        workspace.write_failure(
            FlowFailureRecord(
                work_unit_id=unit.work_unit_id,
                category=FlowFailureCategory.RULE_ERROR,
                message=f"{type(error).__name__}: {str(error)[:400]}",
                input_fingerprint=unit.input_fingerprint,
                context_fingerprint=unit.context_fingerprint,
                policy_fingerprint=unit.policy_fingerprint,
                resolver_configuration_fingerprint=self.configuration_fingerprint,
            )
        )
