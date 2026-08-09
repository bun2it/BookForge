"""Mechanical Contracts V3 Book Assembly.

This module consumes accepted semantic/flow truth.  It contains no parser,
semantic inference, source-layout policy, renderer, network, or persistence.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, cast

from pydantic import ValidationError

from bookforge.contracts.assembly import (
    AssemblyInput,
    AssemblyNotReadyError,
    AssemblyProvenance,
    AssemblyReadinessCode,
    AssemblyReadinessFinding,
    AssemblyReadinessReport,
    BookContentCatalogV3,
    BookModelV3,
    ChapterV3,
    ConflictingReviewError,
    FlowDecision,
    InvalidHierarchyError,
    LogicalContinuityV3,
    MatterV3,
    MissingAssetProvenanceError,
    MissingSemanticContentError,
    PartV3,
    ReferentialIntegrityError,
    SectionLevel,
    SectionV3,
    TextSemanticNode,
    UnsupportedLogicalContentError,
    UnsupportedSemanticNode,
    UnresolvedFlowError,
    assembly_revision_for_state,
    assess_assembly_readiness,
    materialize_effective_catalog,
    materialize_effective_continuity,
    resolve_effective_classifications,
    resolve_effective_flow_decisions,
)
from bookforge.contracts.common import FragmentId
from bookforge.contracts.flow import (
    CaptionAssociation,
    CaptionAssociationStatus,
    FigurePlacement,
    FigurePlacementRelation,
    FlowDecisionId,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    LogicalGroup,
    LogicalGroupType,
    StructuralBoundaryType,
)
from bookforge.contracts.semantic import SemanticType


@dataclass(frozen=True, slots=True)
class _AssemblyPlan:
    catalog: BookContentCatalogV3
    front_matter: MatterV3
    body: tuple[PartV3 | ChapterV3, ...]
    back_matter: MatterV3
    continuity: tuple[LogicalContinuityV3, ...]
    provenance: AssemblyProvenance


def _canonical_digest(value: object) -> str:
    def default(item: object) -> object:
        if hasattr(item, "model_dump"):
            return cast(Any, item).model_dump(mode="json")
        raise TypeError(f"unsupported canonical fingerprint value: {type(item).__name__}")

    encoded = json.dumps(
        value,
        default=default,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finding(
    code: AssemblyReadinessCode,
    reference_id: str,
) -> AssemblyReadinessFinding:
    return AssemblyReadinessFinding(code=code, reference_id=reference_id, blocking=True)


def _append_unique(
    findings: list[AssemblyReadinessFinding],
    additions: Iterable[AssemblyReadinessFinding],
) -> None:
    known = {(item.code, item.reference_id, item.blocking) for item in findings}
    for item in additions:
        identity = (item.code, item.reference_id, item.blocking)
        if identity not in known:
            findings.append(item)
            known.add(identity)


class BookAssembler:
    """Pure deterministic materializer from ``AssemblyInput`` to ``BookModelV3``."""

    def preflight(self, assembly_input: AssemblyInput) -> AssemblyReadinessReport:
        report, _ = self._prepare(assembly_input)
        return report

    def assemble(self, assembly_input: AssemblyInput) -> BookModelV3:
        report, plan = self._prepare(assembly_input)
        if not report.ready or plan is None:
            raise self._typed_error(report)
        revision = assembly_revision_for_state(
            metadata=assembly_input.metadata,
            front_matter=plan.front_matter,
            body=plan.body,
            back_matter=plan.back_matter,
            content=plan.catalog,
            continuity=plan.continuity,
            provenance=plan.provenance,
        )
        try:
            return BookModelV3(
                revision=revision,
                metadata=assembly_input.metadata,
                front_matter=plan.front_matter,
                body=plan.body,
                back_matter=plan.back_matter,
                content=plan.catalog,
                continuity=plan.continuity,
                provenance=plan.provenance,
            )
        except ValidationError as error:
            final_report = AssemblyReadinessReport(
                ready=False,
                findings=(*report.findings, _finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(error))),
            )
            raise ReferentialIntegrityError(final_report) from error

    def _prepare(self, value: AssemblyInput) -> tuple[AssemblyReadinessReport, _AssemblyPlan | None]:
        base = assess_assembly_readiness(value)
        findings = list(base.findings)
        try:
            effective_classifications = resolve_effective_classifications(
                value.accepted_classifications, value.classification_reviews
            )
            catalog = materialize_effective_catalog(value.semantic_catalog, effective_classifications)
        except ValueError as error:
            _append_unique(findings, (_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(error)),))
            return self._blocked(findings), None

        try:
            effective_decisions = resolve_effective_flow_decisions(
                value.resolved_flow, value.replacement_decisions
            )
        except ValueError as error:
            _append_unique(findings, (_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(error)),))
            return self._blocked(findings), None

        disposition_findings, included, excluded = self._validate_dispositions(
            value, effective_decisions, catalog
        )
        _append_unique(findings, disposition_findings)
        _append_unique(
            findings,
            self._validate_required_figure_caption_decisions(
                catalog, included, effective_decisions
            ),
        )

        hierarchy_findings, hierarchy = self._materialize_hierarchy(
            value, effective_decisions, included
        )
        _append_unique(findings, hierarchy_findings)
        if hierarchy is None:
            return self._blocked(findings), None
        front_matter, body, back_matter, owned = hierarchy

        metadata_ids = {
            value.metadata.title_fragment_id,
            *value.metadata.author_fragment_ids,
        }
        missing_owner = included - owned - metadata_ids
        if missing_owner:
            _append_unique(
                findings,
                (_finding(AssemblyReadinessCode.MISSING_OWNERSHIP, str(item)) for item in sorted(missing_owner)),
            )
        duplicate_owner = owned - included
        if duplicate_owner:
            _append_unique(
                findings,
                (_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(item)) for item in sorted(duplicate_owner)),
            )

        try:
            catalog = self._apply_caption_associations(catalog, effective_decisions, included)
            continuity = materialize_effective_continuity(
                value.resolved_flow, value.replacement_decisions
            )
        except ValueError as error:
            _append_unique(findings, (_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(error)),))
            return self._blocked(findings), None

        provenance = AssemblyProvenance(
            document_id=value.resolved_flow.provenance.document_id,
            semantic_catalog_fingerprint=_canonical_digest(catalog),
            accepted_classification_fingerprint=_canonical_digest(effective_classifications),
            resolved_flow_fingerprint=_canonical_digest(
                {
                    "flow": value.resolved_flow,
                    "effective_decisions": effective_decisions,
                    "continuity": continuity,
                    "excluded": sorted(str(item) for item in excluded),
                }
            ),
            assembly_policy_fingerprint=_canonical_digest(value.policy),
        )

        if findings:
            return self._blocked(findings), None

        plan = _AssemblyPlan(
            catalog=catalog,
            front_matter=front_matter,
            body=body,
            back_matter=back_matter,
            continuity=continuity,
            provenance=provenance,
        )
        try:
            revision = assembly_revision_for_state(
                metadata=value.metadata,
                front_matter=front_matter,
                body=body,
                back_matter=back_matter,
                content=catalog,
                continuity=continuity,
                provenance=provenance,
            )
            BookModelV3(
                revision=revision,
                metadata=value.metadata,
                front_matter=front_matter,
                body=body,
                back_matter=back_matter,
                content=catalog,
                continuity=continuity,
                provenance=provenance,
            )
        except ValidationError as error:
            return self._blocked([
                *findings,
                _finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(error)),
            ]), None
        return AssemblyReadinessReport(ready=True), plan

    @staticmethod
    def _blocked(findings: list[AssemblyReadinessFinding]) -> AssemblyReadinessReport:
        return AssemblyReadinessReport(ready=False, findings=tuple(findings))

    @staticmethod
    def _typed_error(report: AssemblyReadinessReport) -> AssemblyNotReadyError:
        codes = {item.code for item in report.findings if item.blocking}
        if AssemblyReadinessCode.INVALID_HIERARCHY in codes or AssemblyReadinessCode.DUPLICATE_OWNERSHIP in codes or AssemblyReadinessCode.MISSING_OWNERSHIP in codes:
            return InvalidHierarchyError(report)
        if AssemblyReadinessCode.MISSING_SEMANTIC_CONTENT in codes:
            return MissingSemanticContentError(report)
        if AssemblyReadinessCode.MISSING_ASSET_PROVENANCE in codes:
            return MissingAssetProvenanceError(report)
        if AssemblyReadinessCode.CONFLICTING_REVIEW in codes:
            return ConflictingReviewError(report)
        if AssemblyReadinessCode.UNSUPPORTED_CONTENT in codes:
            return UnsupportedLogicalContentError(report)
        if AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE in codes:
            return ReferentialIntegrityError(report)
        if (
            AssemblyReadinessCode.UNRESOLVED_FLOW in codes
            or AssemblyReadinessCode.UNRESOLVED_FIGURE_PLACEMENT in codes
            or AssemblyReadinessCode.UNRESOLVED_CAPTION_ASSOCIATION in codes
            or AssemblyReadinessCode.INCOMPLETE_INCLUSION_DISPOSITION in codes
        ):
            return UnresolvedFlowError(report)
        return AssemblyNotReadyError(report)

    @staticmethod
    def _validate_dispositions(
        value: AssemblyInput,
        decisions: tuple[FlowDecision, ...],
        catalog: BookContentCatalogV3,
    ) -> tuple[list[AssemblyReadinessFinding], set[FragmentId], set[FragmentId]]:
        findings: list[AssemblyReadinessFinding] = []
        dispositions: dict[FragmentId, InclusionType] = {}
        for decision in decisions:
            if not isinstance(decision, InclusionDecision):
                continue
            if decision.target_fragment_id in dispositions:
                findings.append(_finding(AssemblyReadinessCode.INCOMPLETE_INCLUSION_DISPOSITION, str(decision.target_fragment_id)))
            dispositions[decision.target_fragment_id] = decision.inclusion

        source_ids = set(value.resolved_flow.source_fragment_ids)
        catalog_ids = set(catalog.nodes)
        for fragment_id in sorted(source_ids | catalog_ids):
            disposition = dispositions.get(fragment_id)
            if disposition is None or disposition is InclusionType.UNRESOLVED:
                findings.append(_finding(AssemblyReadinessCode.INCOMPLETE_INCLUSION_DISPOSITION, str(fragment_id)))
        included = {item for item, disposition in dispositions.items() if disposition is InclusionType.INCLUDE}
        excluded = {item for item, disposition in dispositions.items() if disposition is InclusionType.EXCLUDE}
        ordered = set(value.resolved_flow.ordered_fragment_ids)
        for fragment_id in sorted(included - ordered):
            findings.append(_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(fragment_id)))
        for fragment_id in sorted(excluded & ordered):
            findings.append(_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(fragment_id)))
        for fragment_id in sorted((included | excluded) - catalog_ids):
            findings.append(_finding(AssemblyReadinessCode.MISSING_SEMANTIC_CONTENT, str(fragment_id)))
        return findings, included, excluded

    @staticmethod
    def _validate_required_figure_caption_decisions(
        catalog: BookContentCatalogV3,
        included: set[FragmentId],
        decisions: tuple[FlowDecision, ...],
    ) -> tuple[AssemblyReadinessFinding, ...]:
        placements = {
            decision.figure_fragment_id: decision
            for decision in decisions
            if isinstance(decision, FigurePlacement)
        }
        associations = {
            decision.caption_fragment_id: decision
            for decision in decisions
            if isinstance(decision, CaptionAssociation)
        }
        findings: list[AssemblyReadinessFinding] = []
        for fragment_id in sorted(included):
            node = catalog.nodes.get(fragment_id)
            if node is None:
                continue
            if node is not None and not isinstance(node, UnsupportedSemanticNode) and node.semantic_type is SemanticType.FIGURE:
                placement = placements.get(fragment_id)
                if placement is None or placement.relation is FigurePlacementRelation.UNRESOLVED:
                    findings.append(_finding(AssemblyReadinessCode.UNRESOLVED_FIGURE_PLACEMENT, str(fragment_id)))
            if isinstance(node, TextSemanticNode) and node.semantic_type is SemanticType.CAPTION:
                association = associations.get(fragment_id)
                if association is None or association.status is CaptionAssociationStatus.UNRESOLVED:
                    findings.append(_finding(AssemblyReadinessCode.UNRESOLVED_CAPTION_ASSOCIATION, str(fragment_id)))
        return tuple(findings)

    def _materialize_hierarchy(
        self,
        value: AssemblyInput,
        decisions: tuple[FlowDecision, ...],
        included: set[FragmentId],
    ) -> tuple[
        list[AssemblyReadinessFinding],
        tuple[MatterV3, tuple[PartV3 | ChapterV3, ...], MatterV3, set[FragmentId]] | None,
    ]:
        findings: list[AssemblyReadinessFinding] = []
        groups = {group.group_id: group for group in value.resolved_flow.groups}
        children: dict[object | None, list[LogicalGroup]] = {}
        for group in value.resolved_flow.groups:
            children.setdefault(group.parent_group_id, []).append(group)
        positions = {
            fragment_id: index
            for index, fragment_id in enumerate(value.resolved_flow.ordered_fragment_ids)
        }
        for values in children.values():
            values.sort(key=lambda group: min(positions.get(item, len(positions)) for item in group.member_fragment_ids))

        effective_by_original: dict[FlowDecisionId, FlowDecision] = {}
        original_decisions: tuple[FlowDecision, ...] = (
            *value.resolved_flow.boundaries,
            *value.resolved_flow.figure_placements,
            *value.resolved_flow.caption_associations,
            *value.resolved_flow.inclusion_decisions,
        )
        for original, effective in zip(original_decisions, decisions, strict=True):
            effective_by_original[original.audit.decision_id] = effective

        expected_parent = {
            LogicalGroupType.FRONT_MATTER: None,
            LogicalGroupType.BACK_MATTER: None,
            LogicalGroupType.PART: None,
            LogicalGroupType.CHAPTER: {LogicalGroupType.PART, None},
            LogicalGroupType.SECTION: {LogicalGroupType.CHAPTER},
            LogicalGroupType.SUBSECTION: {LogicalGroupType.SECTION},
        }
        for group in value.resolved_flow.groups:
            parent = groups.get(group.parent_group_id) if group.parent_group_id is not None else None
            allowed = expected_parent[group.group_type]
            parent_kind = parent.group_type if parent is not None else None
            valid_parent = parent_kind == allowed if not isinstance(allowed, set) else parent_kind in allowed
            if not valid_parent:
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
            if parent is not None and not set(group.member_fragment_ids).issubset(parent.member_fragment_ids):
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
            if not set(group.member_fragment_ids).issubset(included):
                findings.append(_finding(AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE, str(group.group_id)))

        root_groups = children.get(None, [])
        front_groups = [item for item in root_groups if item.group_type is LogicalGroupType.FRONT_MATTER]
        back_groups = [item for item in root_groups if item.group_type is LogicalGroupType.BACK_MATTER]
        body_groups = [item for item in root_groups if item.group_type in {LogicalGroupType.PART, LogicalGroupType.CHAPTER}]
        if len(front_groups) > 1 or len(back_groups) > 1:
            findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, "matter-groups"))

        direct_ownership: list[FragmentId] = []

        def direct_ids(group: LogicalGroup) -> tuple[tuple[FragmentId, ...], tuple[FragmentId, ...]]:
            child_members = {
                fragment_id
                for child in children.get(group.group_id, [])
                for fragment_id in child.member_fragment_ids
            }
            opening = tuple(
                item for item in group.opening_fragment_ids
                if item not in child_members
            )
            content = tuple(
                item for item in group.member_fragment_ids
                if item not in child_members and item not in set(opening)
            )
            direct_ownership.extend((*opening, *content))
            return opening, content

        def break_for(group: LogicalGroup, expected: StructuralBoundaryType) -> LogicalBreakIntent:
            decision = effective_by_original.get(group.boundary_decision_id)
            if not isinstance(decision, LogicalBoundaryDecision) or decision.structural_boundary is not expected or decision.break_intent is LogicalBreakIntent.UNRESOLVED:
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
                return LogicalBreakIntent.NONE
            return decision.break_intent

        def section(group: LogicalGroup) -> SectionV3 | None:
            expected = StructuralBoundaryType.SECTION if group.group_type is LogicalGroupType.SECTION else StructuralBoundaryType.SUBSECTION
            opening, content = direct_ids(group)
            nested: list[SectionV3] = []
            for child in children.get(group.group_id, []):
                if child.group_type is not LogicalGroupType.SUBSECTION:
                    findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(child.group_id)))
                    continue
                built = section(child)
                if built is not None:
                    nested.append(built)
            try:
                return SectionV3(
                    id=str(group.group_id),
                    level=SectionLevel.SECTION if group.group_type is LogicalGroupType.SECTION else SectionLevel.SUBSECTION,
                    break_intent=break_for(group, expected),
                    opening_fragment_ids=opening,
                    content_fragment_ids=content,
                    subsections=tuple(nested),
                )
            except ValidationError:
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
                return None

        def chapter(group: LogicalGroup) -> ChapterV3 | None:
            opening, content = direct_ids(group)
            sections: list[SectionV3] = []
            for child in children.get(group.group_id, []):
                if child.group_type is not LogicalGroupType.SECTION:
                    findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(child.group_id)))
                    continue
                built = section(child)
                if built is not None:
                    sections.append(built)
            try:
                return ChapterV3(
                    id=str(group.group_id),
                    break_intent=break_for(group, StructuralBoundaryType.CHAPTER),
                    opening_fragment_ids=opening,
                    content_fragment_ids=content,
                    sections=tuple(sections),
                )
            except ValidationError:
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
                return None

        def part(group: LogicalGroup) -> PartV3 | None:
            opening, content = direct_ids(group)
            chapters: list[ChapterV3] = []
            for child in children.get(group.group_id, []):
                if child.group_type is not LogicalGroupType.CHAPTER:
                    findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(child.group_id)))
                    continue
                built = chapter(child)
                if built is not None:
                    chapters.append(built)
            try:
                return PartV3(
                    id=str(group.group_id),
                    break_intent=break_for(group, StructuralBoundaryType.PART),
                    opening_fragment_ids=opening,
                    content_fragment_ids=content,
                    chapters=tuple(chapters),
                )
            except ValidationError:
                findings.append(_finding(AssemblyReadinessCode.INVALID_HIERARCHY, str(group.group_id)))
                return None

        front_ids: tuple[FragmentId, ...] = ()
        if front_groups:
            opening, content = direct_ids(front_groups[0])
            front_ids = (*opening, *content)
        back_ids: tuple[FragmentId, ...] = ()
        if back_groups:
            opening, content = direct_ids(back_groups[0])
            back_ids = (*opening, *content)

        body: list[PartV3 | ChapterV3] = []
        for group in body_groups:
            built: PartV3 | ChapterV3 | None
            if group.group_type is LogicalGroupType.PART:
                built = part(group)
            else:
                built = chapter(group)
            if built is not None:
                body.append(built)

        counts: dict[FragmentId, int] = {}
        for fragment_id in direct_ownership:
            counts[fragment_id] = counts.get(fragment_id, 0) + 1
        duplicates = {item for item, count in counts.items() if count > 1}
        if duplicates:
            _append_unique(
                findings,
                (_finding(AssemblyReadinessCode.DUPLICATE_OWNERSHIP, str(item)) for item in sorted(duplicates)),
            )
        owned = set(direct_ownership)
        if findings:
            return findings, None
        return findings, (MatterV3(content_fragment_ids=front_ids), tuple(body), MatterV3(content_fragment_ids=back_ids), owned)

    @staticmethod
    def _apply_caption_associations(
        catalog: BookContentCatalogV3,
        decisions: tuple[FlowDecision, ...],
        included: set[FragmentId],
    ) -> BookContentCatalogV3:
        from bookforge.contracts.assembly import FigureSemanticNode

        nodes = dict(catalog.nodes)
        for decision in decisions:
            if not isinstance(decision, CaptionAssociation) or decision.status is not CaptionAssociationStatus.ASSOCIATED:
                continue
            if decision.caption_fragment_id not in included or decision.figure_fragment_id not in included:
                raise ValueError("caption association targets must both be included")
            assert decision.figure_fragment_id is not None
            figure = nodes.get(decision.figure_fragment_id)
            caption = nodes.get(decision.caption_fragment_id)
            if not isinstance(figure, FigureSemanticNode):
                raise ValueError("caption association target is not a figure node")
            if not isinstance(caption, TextSemanticNode) or caption.semantic_type is not SemanticType.CAPTION:
                raise ValueError("caption association source is not a caption text node")
            nodes[figure.id] = figure.model_copy(
                update={
                    "figure": figure.figure.model_copy(
                        update={"caption_fragment_id": decision.caption_fragment_id}
                    )
                }
            )
        return BookContentCatalogV3(nodes=nodes)
