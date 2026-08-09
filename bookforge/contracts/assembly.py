"""Contracts V3 and the future Book Assembly admission boundary.

This module deliberately contains no assembler.  It defines the complete
logical model an assembler will materialize and a deterministic readiness
preflight over already-made M3/M4 decisions.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal, Protocol, TypeAlias

from pydantic import Field, model_validator

from .classification import ClassificationId, ClassificationResult, ClassificationReview, ReviewStatus
from .common import DocumentId, FragmentId, FrozenContractModel, SourceId
from .flow import (
    CaptionAssociation,
    CaptionAssociationStatus,
    ContinuityType,
    FlowDecisionId,
    FlowDecisionReview,
    FigurePlacement,
    FigurePlacementRelation,
    InclusionDecision,
    InclusionType,
    LogicalBoundaryDecision,
    LogicalBreakIntent,
    ResolvedContentFlow,
    StructuralBoundaryType,
)
from .ids import validate_stable_id
from .semantic import FigureType, KeepDecision, SemanticType, TableRenderingStrategy
from .source import SourceTextReference


class EvidenceKind(StrEnum):
    TEXT = "text"
    IMAGE = "image"
    TABLE = "table"
    DRAWING = "drawing"
    OTHER = "other"


class EvidenceReference(FrozenContractModel):
    """Source-neutral identity of evidence; it never carries evidence bytes/text."""

    source_id: SourceId
    kind: EvidenceKind
    asset_reference: str | None = None

    @model_validator(mode="after")
    def asset_only_for_images(self) -> "EvidenceReference":
        if self.kind is EvidenceKind.IMAGE and not self.asset_reference:
            raise ValueError("image evidence requires an immutable asset reference")
        if self.kind is not EvidenceKind.IMAGE and self.asset_reference is not None:
            raise ValueError("only image evidence may carry an asset reference")
        return self


class SemanticNodeKind(StrEnum):
    TEXT = "text"
    FIGURE = "figure"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


class TextSemanticNode(FrozenContractModel):
    kind: Literal[SemanticNodeKind.TEXT] = SemanticNodeKind.TEXT
    id: FragmentId
    semantic_type: SemanticType
    source_references: tuple[SourceTextReference, ...] = Field(min_length=1)
    source_evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def matching_text_fragment(self) -> "TextSemanticNode":
        validate_stable_id(str(self.id))
        if self.semantic_type in {SemanticType.FIGURE, SemanticType.TABLE}:
            raise ValueError("figure/table content requires its typed semantic node")
        evidence_ids = {item.source_id for item in self.source_evidence if item.kind is EvidenceKind.TEXT}
        if not evidence_ids or not {item.source_id for item in self.source_references}.issubset(evidence_ids):
            raise ValueError("authoritative text references require matching text evidence provenance")
        return self


class FigureSemanticNode(FrozenContractModel):
    kind: Literal[SemanticNodeKind.FIGURE] = SemanticNodeKind.FIGURE
    id: FragmentId
    semantic_type: Literal[SemanticType.FIGURE] = SemanticType.FIGURE
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    figure: "FigureDataV3"

    @model_validator(mode="after")
    def valid_figure(self) -> "FigureSemanticNode":
        if self.figure.fragment_id != self.id:
            raise ValueError("figure node ID must match SemanticFigure")
        image_refs = [item for item in self.evidence if item.kind is EvidenceKind.IMAGE]
        if not image_refs or self.figure.source_image_id not in {item.source_id for item in image_refs}:
            raise ValueError("figure requires matching image evidence and asset provenance")
        return self


class TableSemanticNode(FrozenContractModel):
    kind: Literal[SemanticNodeKind.TABLE] = SemanticNodeKind.TABLE
    id: FragmentId
    semantic_type: Literal[SemanticType.TABLE] = SemanticType.TABLE
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    table: "TableDataV3"

    @model_validator(mode="after")
    def valid_table(self) -> "TableSemanticNode":
        if self.table.fragment_id != self.id:
            raise ValueError("table node ID must match SemanticTable")
        source_ids = {item.source_id for item in self.evidence if item.kind is EvidenceKind.TABLE}
        if not source_ids or not set(self.table.source_ids).issubset(source_ids):
            raise ValueError("table requires matching source-neutral table provenance")
        return self


class FigureDataV3(FrozenContractModel):
    fragment_id: FragmentId
    source_image_id: SourceId
    figure_type: FigureType = FigureType.UNKNOWN
    caption_fragment_id: FragmentId | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    keep_decision: KeepDecision = KeepDecision.REVIEW


class TableCellV3(FrozenContractModel):
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    source_references: tuple[SourceTextReference, ...] = Field(min_length=1)
    row_span: int | None = Field(default=None, ge=1)
    column_span: int | None = Field(default=None, ge=1)
    is_header: bool | None = None


class TableRowV3(FrozenContractModel):
    index: int = Field(ge=0)
    cells: tuple[TableCellV3, ...]


class TableDataV3(FrozenContractModel):
    fragment_id: FragmentId
    source_ids: tuple[SourceId, ...] = Field(min_length=1)
    rows: tuple[TableRowV3, ...]
    reconstruction_confidence: float | None = Field(default=None, ge=0, le=1)
    preferred_rendering: TableRenderingStrategy = TableRenderingStrategy.REVIEW_REQUIRED


class UnsupportedContentKind(StrEnum):
    DRAWING = "drawing"
    OTHER = "other"


class UnsupportedSemanticNode(FrozenContractModel):
    kind: Literal[SemanticNodeKind.UNSUPPORTED] = SemanticNodeKind.UNSUPPORTED
    id: FragmentId
    content_kind: UnsupportedContentKind
    evidence: tuple[EvidenceReference, ...] = Field(min_length=1)
    reason_code: str = Field(min_length=1)

    @model_validator(mode="after")
    def matching_evidence_kind(self) -> "UnsupportedSemanticNode":
        if self.content_kind is UnsupportedContentKind.DRAWING and not any(
            item.kind is EvidenceKind.DRAWING for item in self.evidence
        ):
            raise ValueError("unsupported drawing requires drawing evidence")
        return self


SemanticContentNode: TypeAlias = Annotated[
    TextSemanticNode | FigureSemanticNode | TableSemanticNode | UnsupportedSemanticNode,
    Field(discriminator="kind"),
]


class BookContentCatalogV3(FrozenContractModel):
    schema_version: Literal[3] = 3
    nodes: dict[FragmentId, SemanticContentNode]

    @model_validator(mode="after")
    def matching_unique_ids(self) -> "BookContentCatalogV3":
        value_ids = [node.id for node in self.nodes.values()]
        if len(value_ids) != len(set(value_ids)):
            raise ValueError("content catalog contains duplicate semantic node IDs")
        for key, node in self.nodes.items():
            if key != node.id:
                raise ValueError("semantic node catalog key must match node ID")
        return self


class SemanticNodeFamily(StrEnum):
    TEXT = "text"
    FIGURE = "figure"
    TABLE = "table"
    UNSUPPORTED = "unsupported"


def semantic_node_family(node: SemanticContentNode) -> SemanticNodeFamily:
    if isinstance(node, TextSemanticNode):
        return SemanticNodeFamily.TEXT
    if isinstance(node, FigureSemanticNode):
        return SemanticNodeFamily.FIGURE
    if isinstance(node, TableSemanticNode):
        return SemanticNodeFamily.TABLE
    return SemanticNodeFamily.UNSUPPORTED


def semantic_type_is_compatible(node: SemanticContentNode, semantic_type: SemanticType) -> bool:
    family = semantic_node_family(node)
    if family is SemanticNodeFamily.TEXT:
        return semantic_type not in {SemanticType.FIGURE, SemanticType.TABLE}
    if family is SemanticNodeFamily.FIGURE:
        return semantic_type is SemanticType.FIGURE
    if family is SemanticNodeFamily.TABLE:
        return semantic_type is SemanticType.TABLE
    return semantic_type in {SemanticType.UNKNOWN, SemanticType.DECORATIVE, SemanticType.ARTIFACT}


class AcceptedClassificationCatalog(FrozenContractModel):
    """M3-owned explicit FragmentId to accepted decision association."""

    document_id: DocumentId
    by_fragment_id: dict[FragmentId, ClassificationResult]

    @model_validator(mode="after")
    def one_current_document(self) -> "AcceptedClassificationCatalog":
        ids = [result.id for result in self.by_fragment_id.values()]
        if len(ids) != len(set(ids)):
            raise ValueError("one ClassificationResult cannot be assigned to multiple fragments")
        for result in self.by_fragment_id.values():
            if result.provenance.document_id != self.document_id:
                raise ValueError("accepted classification document identity mismatch")
        return self


class EffectiveClassification(FrozenContractModel):
    fragment_id: FragmentId
    semantic_type: SemanticType
    base_classification_id: ClassificationId
    review_id: str | None = None
    taxonomy_version: str = Field(min_length=1)
    effective_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


def resolve_effective_classifications(
    catalog: AcceptedClassificationCatalog,
    reviews: tuple[ClassificationReview, ...],
) -> tuple[EffectiveClassification, ...]:
    """Resolve immutable M3 reviews; invalid/conflicting audit fails explicitly."""

    by_classification_id = {result.id: (fragment_id, result) for fragment_id, result in catalog.by_fragment_id.items()}
    reviews_by_id: dict[ClassificationId, list[ClassificationReview]] = {}
    for review in reviews:
        reviews_by_id.setdefault(review.classification_id, []).append(review)
    unknown = set(reviews_by_id) - set(by_classification_id)
    if unknown:
        raise ValueError("classification review references an unknown accepted classification")
    if any(len(group) != 1 for group in reviews_by_id.values()):
        raise ValueError("accepted classifications may have at most one active review")

    effective: list[EffectiveClassification] = []
    for fragment_id, result in catalog.by_fragment_id.items():
        review_group = reviews_by_id.get(result.id, [])
        active_classification_review = review_group[0] if review_group else None
        semantic_type = result.semantic_type
        review_id: str | None = None
        if active_classification_review is not None:
            if active_classification_review.original_semantic_type is not result.semantic_type:
                raise ValueError("classification review original type is stale")
            if set(active_classification_review.provenance.source_ids) != set(result.target_source_ids):
                raise ValueError("classification review source identity is stale")
            if active_classification_review.base_input_fingerprint != result.input_fingerprint:
                raise ValueError("classification review input fingerprint is stale")
            if active_classification_review.taxonomy_version != result.taxonomy_version:
                raise ValueError("classification review taxonomy is stale")
            semantic_type = active_classification_review.accepted_semantic_type
            review_id = str(active_classification_review.id)
        payload = (str(fragment_id), str(result.id), semantic_type.value, review_id, result.taxonomy_version)
        fingerprint = hashlib.sha256(repr(payload).encode("utf-8")).hexdigest()
        effective.append(
            EffectiveClassification(
                fragment_id=fragment_id,
                semantic_type=semantic_type,
                base_classification_id=result.id,
                review_id=review_id,
                taxonomy_version=result.taxonomy_version,
                effective_fingerprint=fingerprint,
            )
        )
    return tuple(effective)


def materialize_effective_catalog(
    catalog: BookContentCatalogV3,
    effective: tuple[EffectiveClassification, ...],
) -> BookContentCatalogV3:
    """Apply only representation-compatible semantic review outcomes."""

    effective_by_fragment = {item.fragment_id: item for item in effective}
    if set(effective_by_fragment) != set(catalog.nodes):
        raise ValueError("effective classifications must cover the semantic catalog exactly")
    nodes: dict[FragmentId, SemanticContentNode] = {}
    for fragment_id, node in catalog.nodes.items():
        decision = effective_by_fragment[fragment_id]
        if not semantic_type_is_compatible(node, decision.semantic_type):
            raise ValueError("effective semantic type is incompatible with the typed node family")
        if isinstance(node, TextSemanticNode):
            node = node.model_copy(update={"semantic_type": decision.semantic_type})
        nodes[fragment_id] = node
    return BookContentCatalogV3(nodes=nodes)


class SectionLevel(StrEnum):
    SECTION = "section"
    SUBSECTION = "subsection"


class SectionV3(FrozenContractModel):
    id: str
    level: SectionLevel
    break_intent: LogicalBreakIntent
    opening_fragment_ids: tuple[FragmentId, ...] = ()
    content_fragment_ids: tuple[FragmentId, ...] = ()
    subsections: tuple["SectionV3", ...] = ()

    @model_validator(mode="after")
    def valid_nesting(self) -> "SectionV3":
        validate_stable_id(self.id)
        expected = f"flow_{self.level.value}_"
        if not self.id.startswith(expected):
            raise ValueError("section ID kind must match its hierarchy level")
        if self.break_intent is LogicalBreakIntent.UNRESOLVED:
            raise ValueError("assembled hierarchy cannot retain unresolved break intent")
        if self.level is SectionLevel.SUBSECTION and self.subsections:
            raise ValueError("subsections cannot contain a deeper unsupported hierarchy level")
        if any(child.level is not SectionLevel.SUBSECTION for child in self.subsections):
            raise ValueError("section children must be subsections")
        return self


class BodyEntryKind(StrEnum):
    CHAPTER = "chapter"
    PART = "part"


class ChapterV3(FrozenContractModel):
    kind: Literal[BodyEntryKind.CHAPTER] = BodyEntryKind.CHAPTER
    id: str
    break_intent: LogicalBreakIntent
    opening_fragment_ids: tuple[FragmentId, ...] = ()
    content_fragment_ids: tuple[FragmentId, ...] = ()
    sections: tuple[SectionV3, ...] = ()

    @model_validator(mode="after")
    def valid_chapter(self) -> "ChapterV3":
        validate_stable_id(self.id)
        if not self.id.startswith("flow_chapter_"):
            raise ValueError("chapter ID kind must match chapter hierarchy")
        if not (self.opening_fragment_ids or self.content_fragment_ids or self.sections):
            raise ValueError("chapter must own content; a title is optional")
        if self.break_intent is LogicalBreakIntent.UNRESOLVED:
            raise ValueError("assembled chapter cannot retain unresolved break intent")
        if any(section.level is not SectionLevel.SECTION for section in self.sections):
            raise ValueError("chapter children must be sections")
        return self


class PartV3(FrozenContractModel):
    kind: Literal[BodyEntryKind.PART] = BodyEntryKind.PART
    id: str
    break_intent: LogicalBreakIntent
    opening_fragment_ids: tuple[FragmentId, ...] = ()
    content_fragment_ids: tuple[FragmentId, ...] = ()
    chapters: tuple[ChapterV3, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def valid_part(self) -> "PartV3":
        validate_stable_id(self.id)
        if not self.id.startswith("flow_part_"):
            raise ValueError("part ID kind must match part hierarchy")
        if self.break_intent is LogicalBreakIntent.UNRESOLVED:
            raise ValueError("assembled part cannot retain unresolved break intent")
        return self


BookBodyEntry: TypeAlias = Annotated[ChapterV3 | PartV3, Field(discriminator="kind")]


class MatterV3(FrozenContractModel):
    content_fragment_ids: tuple[FragmentId, ...] = ()


class BookMetadataV3(FrozenContractModel):
    title_fragment_id: FragmentId
    author_fragment_ids: tuple[FragmentId, ...] = ()
    language: str = Field(min_length=1)
    identifier: str = Field(min_length=1)
    publisher: str | None = None
    description: str | None = None
    cover_reference: str | None = None


class AssemblyProvenance(FrozenContractModel):
    document_id: DocumentId
    semantic_catalog_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted_classification_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    resolved_flow_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    assembly_policy_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")


_TEXT_CONTINUITY = {
    ContinuityType.JOIN_DIRECT,
    ContinuityType.JOIN_WITH_SPACE,
    ContinuityType.JOIN_WITH_NEWLINE,
    ContinuityType.JOIN_REMOVE_TRAILING_HYPHEN,
}
_PERSISTED_CONTINUITY = {
    ContinuityType.KEEP_SEPARATE,
    *_TEXT_CONTINUITY,
    ContinuityType.CONTINUE_LIST,
    ContinuityType.CONTINUE_TABLE,
}


class LogicalContinuityV3(FrozenContractModel):
    """Renderer-neutral annotation over the authoritative hierarchy order."""

    left_node_id: FragmentId
    right_node_id: FragmentId
    operation: ContinuityType
    source_decision_id: FlowDecisionId

    @model_validator(mode="after")
    def resolved_distinct_edge(self) -> "LogicalContinuityV3":
        if self.left_node_id == self.right_node_id:
            raise ValueError("continuity requires two distinct semantic nodes")
        if self.operation not in _PERSISTED_CONTINUITY:
            raise ValueError("BookModel continuity must be an accepted resolved operation")
        validate_stable_id(str(self.source_decision_id))
        return self


class BookModelV3(FrozenContractModel):
    """Complete immutable logical truth with one authoritative body tree."""

    schema_version: Literal[3] = 3
    revision: str = Field(pattern=r"^asm_[0-9a-f]{20}$")
    metadata: BookMetadataV3
    front_matter: MatterV3 = MatterV3()
    body: tuple[BookBodyEntry, ...]
    back_matter: MatterV3 = MatterV3()
    content: BookContentCatalogV3
    continuity: tuple[LogicalContinuityV3, ...] = ()
    provenance: AssemblyProvenance

    @model_validator(mode="after")
    def complete_unambiguous_reading_truth(self) -> "BookModelV3":
        catalog_ids = set(self.content.nodes)
        owned: list[FragmentId] = []
        ordered_paths: list[tuple[FragmentId, tuple[str, ...]]] = []

        def add_ids(fragment_ids: tuple[FragmentId, ...], path: tuple[str, ...]) -> None:
            owned.extend(fragment_ids)
            ordered_paths.extend((fragment_id, path) for fragment_id in fragment_ids)

        add_ids(self.front_matter.content_fragment_ids, ("front_matter",))

        def add_section(section: SectionV3) -> None:
            path = ("body", section.id)
            add_ids(section.opening_fragment_ids, path)
            add_ids(section.content_fragment_ids, path)
            for child in section.subsections:
                add_section(child)

        for entry in self.body:
            if isinstance(entry, PartV3):
                add_ids(entry.opening_fragment_ids, ("body", entry.id))
                add_ids(entry.content_fragment_ids, ("body", entry.id))
                chapters = entry.chapters
            else:
                chapters = (entry,)
            for chapter in chapters:
                add_ids(chapter.opening_fragment_ids, ("body", chapter.id))
                add_ids(chapter.content_fragment_ids, ("body", chapter.id))
                for section in chapter.sections:
                    add_section(section)
        add_ids(self.back_matter.content_fragment_ids, ("back_matter",))
        if len(owned) != len(set(owned)):
            raise ValueError("a semantic node may be owned only once in final reading order")
        metadata_ids = {self.metadata.title_fragment_id, *self.metadata.author_fragment_ids}
        missing = sorted(str(item) for item in set(owned) | metadata_ids if item not in catalog_ids)
        if missing:
            raise ValueError(f"BookModel V3 references missing semantic nodes: {', '.join(missing)}")
        for node in self.content.nodes.values():
            if isinstance(node, FigureSemanticNode) and node.figure.caption_fragment_id is not None:
                caption = self.content.nodes.get(node.figure.caption_fragment_id)
                if not isinstance(caption, TextSemanticNode) or caption.semantic_type is not SemanticType.CAPTION:
                    raise ValueError("figure caption must resolve to a textual CAPTION semantic node")
        unsupported_owned = [item for item in owned if isinstance(self.content.nodes[item], UnsupportedSemanticNode)]
        if unsupported_owned:
            raise ValueError("unsupported semantic content cannot enter renderable reading order")
        positions = {fragment_id: index for index, (fragment_id, _) in enumerate(ordered_paths)}
        paths = dict(ordered_paths)
        edges: set[tuple[FragmentId, FragmentId]] = set()
        decisions: set[FlowDecisionId] = set()
        for continuity in self.continuity:
            edge = (continuity.left_node_id, continuity.right_node_id)
            if edge in edges:
                raise ValueError("final continuity may define one operation per logical edge")
            edges.add(edge)
            if continuity.source_decision_id in decisions:
                raise ValueError("final continuity decision IDs must be unique")
            decisions.add(continuity.source_decision_id)
            if continuity.left_node_id not in positions or continuity.right_node_id not in positions:
                raise ValueError("continuity targets must be included in final logical hierarchy")
            if positions[continuity.right_node_id] != positions[continuity.left_node_id] + 1:
                raise ValueError("continuity targets must be adjacent in final included order")
            left = self.content.nodes[continuity.left_node_id]
            right = self.content.nodes[continuity.right_node_id]
            if continuity.operation in _TEXT_CONTINUITY and not (
                isinstance(left, TextSemanticNode) and isinstance(right, TextSemanticNode)
            ):
                raise ValueError("text join continuity requires two textual semantic nodes")
            if continuity.operation is ContinuityType.CONTINUE_LIST and not (
                isinstance(left, TextSemanticNode)
                and isinstance(right, TextSemanticNode)
                and left.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}
                and right.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}
            ):
                raise ValueError("list continuity requires two list-family text nodes")
            if continuity.operation is ContinuityType.CONTINUE_TABLE and not (
                isinstance(left, TableSemanticNode) and isinstance(right, TableSemanticNode)
            ):
                raise ValueError("table continuity requires two table semantic nodes")
            if continuity.operation is not ContinuityType.KEEP_SEPARATE and paths[continuity.left_node_id] != paths[continuity.right_node_id]:
                raise ValueError("joining continuity cannot cross logical hierarchy containers")
        return self


FlowDecision: TypeAlias = LogicalBoundaryDecision | FigurePlacement | CaptionAssociation | InclusionDecision


class AssemblyAdmissionMode(StrEnum):
    STRICT = "strict"
    REVIEWED = "reviewed"


class AssemblyPolicy(FrozenContractModel):
    mode: AssemblyAdmissionMode = AssemblyAdmissionMode.STRICT
    policy_version: str = Field(default="assembly-admission-v1", min_length=1)


class AssemblyReadinessCode(StrEnum):
    INVALID_METADATA = "invalid_metadata"
    INVALID_CLASSIFICATION_INDEX = "invalid_classification_index"
    INCOMPATIBLE_SEMANTIC_NODE = "incompatible_semantic_node"
    INVALID_CONTINUITY = "invalid_continuity"
    INVALID_HIERARCHY = "invalid_hierarchy"
    DUPLICATE_OWNERSHIP = "duplicate_ownership"
    MISSING_OWNERSHIP = "missing_ownership"
    INCOMPLETE_INCLUSION_DISPOSITION = "incomplete_inclusion_disposition"
    UNRESOLVED_FIGURE_PLACEMENT = "unresolved_figure_placement"
    UNRESOLVED_CAPTION_ASSOCIATION = "unresolved_caption_association"
    REFERENTIAL_INTEGRITY_FAILURE = "referential_integrity_failure"
    UNRESOLVED_FLOW = "unresolved_flow"
    CONFLICTING_REVIEW = "conflicting_review"
    DANGLING_REVIEW = "dangling_review"
    INVALID_REPLACEMENT = "invalid_replacement"
    STALE_REVIEW = "stale_review"
    MISSING_SEMANTIC_CONTENT = "missing_semantic_content"
    UNSUPPORTED_CONTENT = "unsupported_content"
    MISSING_ASSET_PROVENANCE = "missing_asset_provenance"
    UNREVIEWED_CLASSIFICATION = "unreviewed_classification"


class AssemblyReadinessFinding(FrozenContractModel):
    code: AssemblyReadinessCode
    reference_id: str
    blocking: bool


class AssemblyReadinessReport(FrozenContractModel):
    ready: bool
    findings: tuple[AssemblyReadinessFinding, ...] = ()

    @model_validator(mode="after")
    def ready_matches_findings(self) -> "AssemblyReadinessReport":
        if self.ready == any(item.blocking for item in self.findings):
            raise ValueError("ready must be false exactly when a blocking finding exists")
        return self


class AssemblyInput(FrozenContractModel):
    metadata: BookMetadataV3
    semantic_catalog: BookContentCatalogV3
    resolved_flow: ResolvedContentFlow
    accepted_classifications: AcceptedClassificationCatalog
    classification_reviews: tuple[ClassificationReview, ...] = ()
    replacement_decisions: tuple[FlowDecision, ...] = ()
    policy: AssemblyPolicy = AssemblyPolicy()


def _decision_id(decision: FlowDecision) -> FlowDecisionId:
    return decision.audit.decision_id


def _decision_target(decision: FlowDecision) -> tuple[FragmentId, ...]:
    if isinstance(decision, LogicalBoundaryDecision):
        return tuple(item for item in (decision.preceding_fragment_id, decision.following_fragment_id) if item)
    if isinstance(decision, FigurePlacement):
        return (decision.figure_fragment_id,)
    if isinstance(decision, CaptionAssociation):
        return (decision.caption_fragment_id,)
    return (decision.target_fragment_id,)


def resolve_effective_flow_decisions(
    flow: ResolvedContentFlow,
    replacement_decisions: tuple[FlowDecision, ...],
) -> tuple[FlowDecision, ...]:
    originals: dict[FlowDecisionId, FlowDecision] = {}
    ordered_originals: list[FlowDecisionId] = []
    all_decisions: tuple[FlowDecision, ...] = (
        *flow.boundaries,
        *flow.figure_placements,
        *flow.caption_associations,
        *flow.inclusion_decisions,
    )
    for decision in all_decisions:
        decision_id = _decision_id(decision)
        originals[decision_id] = decision
        ordered_originals.append(decision_id)
    replacements = {_decision_id(item): item for item in replacement_decisions}
    reviews_by_original: dict[FlowDecisionId, list[FlowDecisionReview]] = {}
    for review in flow.decision_reviews:
        reviews_by_original.setdefault(review.original_decision_id, []).append(review)
    if any(len(group) != 1 for group in reviews_by_original.values()):
        raise ValueError("flow decisions may have at most one active review")
    effective = dict(originals)
    for original_id, review_group in reviews_by_original.items():
        original = originals.get(original_id)
        if original is None:
            raise ValueError("flow review references an unknown original decision")
        review = review_group[0]
        if review.status is ReviewStatus.REVIEWED_OVERRIDDEN:
            replacement = replacements.get(review.accepted_decision_id)
            if replacement is None or type(replacement) is not type(original):
                raise ValueError("flow review replacement kind is invalid")
            if _decision_target(replacement) != _decision_target(original):
                raise ValueError("flow review replacement target is invalid")
            if replacement.audit.provenance.input_fingerprint != original.audit.provenance.input_fingerprint:
                raise ValueError("flow review replacement is stale")
            effective[original_id] = replacement
    return tuple(effective[item] for item in ordered_originals)


def materialize_effective_continuity(
    flow: ResolvedContentFlow,
    replacement_decisions: tuple[FlowDecision, ...],
) -> tuple[LogicalContinuityV3, ...]:
    result: list[LogicalContinuityV3] = []
    for decision in resolve_effective_flow_decisions(flow, replacement_decisions):
        if not isinstance(decision, LogicalBoundaryDecision):
            continue
        if decision.edge.value != "between_fragments" or decision.continuity not in _PERSISTED_CONTINUITY:
            continue
        assert decision.preceding_fragment_id is not None and decision.following_fragment_id is not None
        result.append(
            LogicalContinuityV3(
                left_node_id=decision.preceding_fragment_id,
                right_node_id=decision.following_fragment_id,
                operation=decision.continuity,
                source_decision_id=decision.audit.decision_id,
            )
        )
    return tuple(result)


def assess_assembly_readiness(value: AssemblyInput) -> AssemblyReadinessReport:
    """Validate admission only; it does not materialize any BookModel fields."""

    findings: list[AssemblyReadinessFinding] = []
    flow = value.resolved_flow
    catalog_ids = set(value.semantic_catalog.nodes)
    if value.metadata.title_fragment_id not in catalog_ids:
        findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_METADATA, reference_id=str(value.metadata.title_fragment_id), blocking=True))
    elif not isinstance(value.semantic_catalog.nodes[value.metadata.title_fragment_id], TextSemanticNode):
        findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_METADATA, reference_id=str(value.metadata.title_fragment_id), blocking=True))
    if value.accepted_classifications.document_id != flow.provenance.document_id:
        findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CLASSIFICATION_INDEX, reference_id=str(value.accepted_classifications.document_id), blocking=True))
    if set(value.accepted_classifications.by_fragment_id) != catalog_ids:
        findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CLASSIFICATION_INDEX, reference_id="catalog-coverage", blocking=True))
    for fragment_id, classification in value.accepted_classifications.by_fragment_id.items():
        node = value.semantic_catalog.nodes.get(fragment_id)
        if node is None:
            continue
        if isinstance(node, TextSemanticNode):
            evidence_ids = {item.source_id for item in node.source_evidence}
        else:
            evidence_ids = {item.source_id for item in node.evidence}
        if set(classification.target_source_ids) != evidence_ids:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CLASSIFICATION_INDEX, reference_id=str(fragment_id), blocking=True))
    for fragment_id in flow.source_fragment_ids:
        if fragment_id not in catalog_ids:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.MISSING_SEMANTIC_CONTENT, reference_id=str(fragment_id), blocking=True))
    originals: dict[FlowDecisionId, FlowDecision] = {}
    all_decisions: tuple[FlowDecision, ...] = (
        *flow.boundaries,
        *flow.figure_placements,
        *flow.caption_associations,
        *flow.inclusion_decisions,
    )
    for decision in all_decisions:
        originals[_decision_id(decision)] = decision
    replacements = {_decision_id(item): item for item in value.replacement_decisions}
    reviews_by_original: dict[FlowDecisionId, list[FlowDecisionReview]] = {}
    for review in flow.decision_reviews:
        reviews_by_original.setdefault(review.original_decision_id, []).append(review)
    effective: dict[FlowDecisionId, FlowDecision] = dict(originals)
    for original_id, reviews in reviews_by_original.items():
        if len(reviews) > 1:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.CONFLICTING_REVIEW, reference_id=str(original_id), blocking=True))
            continue
        review = reviews[0]
        original = originals.get(original_id)
        if original is None:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.DANGLING_REVIEW, reference_id=str(original_id), blocking=True))
            continue
        if review.status is ReviewStatus.REVIEWED_OVERRIDDEN:
            replacement = replacements.get(review.accepted_decision_id)
            if replacement is None or type(replacement) is not type(original) or _decision_target(replacement) != _decision_target(original):
                findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_REPLACEMENT, reference_id=str(original_id), blocking=True))
                continue
            if replacement.audit.provenance.input_fingerprint != original.audit.provenance.input_fingerprint:
                findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.STALE_REVIEW, reference_id=str(original_id), blocking=True))
                continue
            effective[original_id] = replacement

    unresolved_ids = set(flow.unresolved_decision_ids)
    for original_id in originals:
        effective_decision = effective.get(original_id)
        resolved = effective_decision is not None and not (
            isinstance(effective_decision, LogicalBoundaryDecision)
            and (effective_decision.continuity.value == "unresolved" or effective_decision.structural_boundary is StructuralBoundaryType.UNRESOLVED or effective_decision.break_intent is LogicalBreakIntent.UNRESOLVED)
            or isinstance(effective_decision, FigurePlacement) and effective_decision.relation is FigurePlacementRelation.UNRESOLVED
            or isinstance(effective_decision, CaptionAssociation) and effective_decision.status is CaptionAssociationStatus.UNRESOLVED
            or isinstance(effective_decision, InclusionDecision) and effective_decision.inclusion is InclusionType.UNRESOLVED
        )
        if not resolved or (original_id in unresolved_ids and effective_decision is None):
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.UNRESOLVED_FLOW, reference_id=str(original_id), blocking=True))

    excluded_ids = {
        decision.target_fragment_id
        for decision in effective.values()
        if isinstance(decision, InclusionDecision) and decision.inclusion is InclusionType.EXCLUDE
    }
    for node in value.semantic_catalog.nodes.values():
        if isinstance(node, UnsupportedSemanticNode) and node.id not in excluded_ids:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.UNSUPPORTED_CONTENT, reference_id=str(node.id), blocking=True))

    classification_by_id = {result.id: result for result in value.accepted_classifications.by_fragment_id.values()}
    classification_reviews_by_id: dict[ClassificationId, list[ClassificationReview]] = {}
    for classification_review in value.classification_reviews:
        classification_reviews_by_id.setdefault(classification_review.classification_id, []).append(classification_review)
    for classification_id, classification_review_group in classification_reviews_by_id.items():
        classification_original = classification_by_id.get(classification_id)
        if len(classification_review_group) > 1:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.CONFLICTING_REVIEW, reference_id=str(classification_id), blocking=True))
        elif classification_original is None:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.DANGLING_REVIEW, reference_id=str(classification_id), blocking=True))
        elif (
            classification_review_group[0].original_semantic_type is not classification_original.semantic_type
            or set(classification_review_group[0].provenance.source_ids) != set(classification_original.target_source_ids)
            or classification_review_group[0].base_input_fingerprint != classification_original.input_fingerprint
            or classification_review_group[0].taxonomy_version != classification_original.taxonomy_version
        ):
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.STALE_REVIEW, reference_id=str(classification_id), blocking=True))
    classification_reviews = set(classification_reviews_by_id)
    if value.policy.mode is AssemblyAdmissionMode.REVIEWED:
        for result in value.accepted_classifications.by_fragment_id.values():
            if result.review_status is ReviewStatus.NEEDS_REVIEW and result.id not in classification_reviews:
                findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.UNREVIEWED_CLASSIFICATION, reference_id=str(result.id), blocking=True))
    catalog_for_validation = value.semantic_catalog
    try:
        effective_classifications = resolve_effective_classifications(value.accepted_classifications, value.classification_reviews)
        effective_catalog = materialize_effective_catalog(value.semantic_catalog, effective_classifications)
        catalog_for_validation = effective_catalog
        title_node = effective_catalog.nodes.get(value.metadata.title_fragment_id)
        if not isinstance(title_node, TextSemanticNode) or title_node.semantic_type not in {SemanticType.BOOK_TITLE, SemanticType.TITLE}:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_METADATA, reference_id=str(value.metadata.title_fragment_id), blocking=True))
    except ValueError as error:
        findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INCOMPATIBLE_SEMANTIC_NODE, reference_id=str(error), blocking=True))

    ordered_positions = {fragment_id: index for index, fragment_id in enumerate(flow.ordered_fragment_ids)}
    effective_edges: set[tuple[FragmentId, FragmentId]] = set()
    for original_id, decision in effective.items():
        if not isinstance(decision, LogicalBoundaryDecision) or decision.edge.value != "between_fragments":
            continue
        if decision.continuity not in _PERSISTED_CONTINUITY:
            continue
        assert decision.preceding_fragment_id is not None and decision.following_fragment_id is not None
        edge = (decision.preceding_fragment_id, decision.following_fragment_id)
        if edge in effective_edges:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CONTINUITY, reference_id=f"{edge[0]}->{edge[1]}", blocking=True))
            continue
        effective_edges.add(edge)
        left_position = ordered_positions.get(edge[0])
        right_position = ordered_positions.get(edge[1])
        if left_position is None or right_position != left_position + 1:
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CONTINUITY, reference_id=str(original_id), blocking=True))
            continue
        left_node = catalog_for_validation.nodes.get(edge[0])
        right_node = catalog_for_validation.nodes.get(edge[1])
        compatible = True
        if decision.continuity in _TEXT_CONTINUITY:
            compatible = isinstance(left_node, TextSemanticNode) and isinstance(right_node, TextSemanticNode)
        elif decision.continuity is ContinuityType.CONTINUE_LIST:
            compatible = (
                isinstance(left_node, TextSemanticNode) and isinstance(right_node, TextSemanticNode)
                and left_node.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}
                and right_node.semantic_type in {SemanticType.LIST, SemanticType.LIST_ITEM}
            )
        elif decision.continuity is ContinuityType.CONTINUE_TABLE:
            compatible = isinstance(left_node, TableSemanticNode) and isinstance(right_node, TableSemanticNode)
        if not compatible or (
            decision.continuity is not ContinuityType.KEEP_SEPARATE
            and decision.structural_boundary is not StructuralBoundaryType.NONE
        ):
            findings.append(AssemblyReadinessFinding(code=AssemblyReadinessCode.INVALID_CONTINUITY, reference_id=str(original_id), blocking=True))
    return AssemblyReadinessReport(ready=not any(item.blocking for item in findings), findings=tuple(findings))


def assembly_revision_for_state(
    *,
    metadata: BookMetadataV3,
    front_matter: MatterV3,
    body: tuple[BookBodyEntry, ...],
    back_matter: MatterV3,
    content: BookContentCatalogV3,
    continuity: tuple[LogicalContinuityV3, ...],
    provenance: AssemblyProvenance,
) -> str:
    """Deterministic logical identity helper for the future mechanical assembler."""

    payload = {
        "schema_version": 3,
        "metadata": metadata.model_dump(mode="json"),
        "front_matter": front_matter.model_dump(mode="json"),
        "body": [entry.model_dump(mode="json") for entry in body],
        "back_matter": back_matter.model_dump(mode="json"),
        "content": content.model_dump(mode="json"),
        "continuity": [edge.model_dump(mode="json") for edge in continuity],
        "provenance": provenance.model_dump(mode="json"),
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"asm_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()[:20]}"


class AssemblyNotReadyError(RuntimeError):
    """Typed assembly admission failure preserving the complete report."""

    report: AssemblyReadinessReport

    def __init__(self, report: AssemblyReadinessReport) -> None:
        self.report = report
        blocking_codes = sorted(
            {finding.code.value for finding in report.findings if finding.blocking}
        )
        detail = ", ".join(blocking_codes) if blocking_codes else "no blocking findings"
        super().__init__(f"assembly input is not ready: {detail}")
class UnresolvedFlowError(AssemblyNotReadyError): ...
class InvalidHierarchyError(AssemblyNotReadyError): ...
class MissingSemanticContentError(AssemblyNotReadyError): ...
class MissingAssetProvenanceError(AssemblyNotReadyError): ...
class ConflictingReviewError(AssemblyNotReadyError): ...
class ReferentialIntegrityError(AssemblyNotReadyError): ...
class UnsupportedLogicalContentError(AssemblyNotReadyError): ...


class BookAssemblerV3(Protocol):
    def assemble(self, assembly_input: AssemblyInput) -> BookModelV3: ...
