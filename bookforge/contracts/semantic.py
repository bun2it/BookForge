from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator, model_validator

from .common import ContractModel, FragmentId, PageId, ProcessingProvenance, SourceId
from .source import SourceTextReference
from .ids import validate_stable_id


class SemanticType(StrEnum):
    BOOK_TITLE = "book_title"
    TITLE = "title"
    SUBTITLE = "subtitle"
    AUTHOR = "author"
    FRONT_MATTER_TITLE = "front_matter_title"
    FRONT_MATTER_TEXT = "front_matter_text"
    PART_TITLE = "part_title"
    CHAPTER_HEADING = "chapter_heading"
    CHAPTER_NUMBER = "chapter_number"
    CHAPTER_TITLE = "chapter_title"
    SECTION_HEADING = "section_heading"
    SUBSECTION_HEADING = "subsection_heading"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    LIST_ITEM = "list_item"
    FIGURE = "figure"
    CAPTION = "caption"
    TABLE = "table"
    QUOTE = "quote"
    NOTE = "note"
    TIP = "tip"
    FOOTNOTE = "footnote"
    RUNNING_HEADER = "running_header"
    RUNNING_FOOTER = "running_footer"
    PAGE_NUMBER = "page_number"
    DECORATIVE = "decorative"
    ARTIFACT = "artifact"
    UNKNOWN = "unknown"


class RelationshipType(StrEnum):
    CAPTION_OF = "caption_of"
    MEMBER_OF = "member_of"
    FOOTNOTE_FOR = "footnote_for"
    ANCHORED_AFTER = "anchored_after"
    ANCHORED_BEFORE = "anchored_before"
    CONTINUES = "continues"


class FragmentRelationship(ContractModel):
    relationship_type: RelationshipType
    target_fragment_id: FragmentId
    metadata: dict[str, Any] = Field(default_factory=dict)


class SemanticFragment(ContractModel):
    id: FragmentId
    semantic_type: SemanticType
    source_references: list[SourceTextReference] = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    relationships: list[FragmentRelationship] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    provenance: ProcessingProvenance

    @field_validator("id")
    @classmethod
    def stable_fragment_id(cls, value: FragmentId) -> FragmentId:
        validate_stable_id(str(value))
        return value


class AnalysisStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    COMPLETE_WITH_WARNINGS = "complete_with_warnings"
    FAILED = "failed"


class StateTransitionMetadata(ContractModel):
    previous_state_revision: str | None = None
    next_state_revision: str | None = None
    changed_fields: list[str] = Field(default_factory=list)


class PageFragment(ContractModel):
    source_page_id: PageId
    ordered_fragments: list[SemanticFragment]
    analysis_status: AnalysisStatus
    warnings: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    state_transition: StateTransitionMetadata | None = None


class OpenStructureState(ContractModel):
    fragment_id: FragmentId
    source_ids: list[SourceId] = Field(default_factory=list)


class BookState(ContractModel):
    revision: str
    current_chapter_id: str | None = None
    current_section_id: str | None = None
    previous_heading_id: FragmentId | None = None
    previous_page_last_fragment_id: FragmentId | None = None
    open_paragraph: OpenStructureState | None = None
    open_list: OpenStructureState | None = None
    open_table: OpenStructureState | None = None
    known_heading_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    known_body_profile: dict[str, Any] = Field(default_factory=dict)
    known_header_candidate_ids: list[SourceId] = Field(default_factory=list)
    known_footer_candidate_ids: list[SourceId] = Field(default_factory=list)


class TableRenderingStrategy(StrEnum):
    SEMANTIC_HTML = "semantic_html"
    VISUAL_FALLBACK = "visual_fallback"
    REVIEW_REQUIRED = "review_required"


class SemanticTableCell(ContractModel):
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    source_references: list[SourceTextReference] = Field(default_factory=list)
    row_span: int | None = Field(default=None, ge=1)
    column_span: int | None = Field(default=None, ge=1)
    is_header: bool | None = None


class SemanticTableRow(ContractModel):
    index: int = Field(ge=0)
    cells: list[SemanticTableCell]


class SemanticTable(ContractModel):
    fragment_id: FragmentId
    source_ids: list[SourceId] = Field(min_length=1)
    rows: list[SemanticTableRow]
    reconstruction_confidence: float | None = Field(default=None, ge=0, le=1)
    preferred_rendering: TableRenderingStrategy = TableRenderingStrategy.REVIEW_REQUIRED


class FigureType(StrEnum):
    PHOTO = "photo"
    ILLUSTRATION = "illustration"
    GRAPH = "graph"
    CHART = "chart"
    DIAGRAM = "diagram"
    MAP = "map"
    UNKNOWN = "unknown"


class KeepDecision(StrEnum):
    KEEP = "keep"
    DROP = "drop"
    REVIEW = "review"


class SemanticFigure(ContractModel):
    fragment_id: FragmentId
    source_image_id: SourceId
    figure_type: FigureType = FigureType.UNKNOWN
    caption_fragment_id: FragmentId | None = None
    anchor_fragment_id: FragmentId | None = None
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    aspect_ratio: float | None = Field(default=None, gt=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    keep_decision: KeepDecision = KeepDecision.REVIEW


class ArtifactType(StrEnum):
    RUNNING_HEADER = "running_header"
    RUNNING_FOOTER = "running_footer"
    PAGE_NUMBER = "page_number"
    DECORATIVE_GRAPHIC = "decorative_graphic"
    BACKGROUND = "background"
    BORDER = "border"
    REPEATED_LOGO = "repeated_logo"
    LAYOUT_ONLY = "layout_only"
    UNKNOWN = "unknown"


class ArtifactClassification(ContractModel):
    source_ids: list[SourceId] = Field(min_length=1)
    artifact_type: ArtifactType
    confidence: float | None = Field(default=None, ge=0, le=1)
    excluded_from_flow: bool = False


class BoundaryOperationType(StrEnum):
    MERGE_PARAGRAPH = "merge_paragraph"
    JOIN_HYPHENATED_WORD = "join_hyphenated_word"
    CONTINUE_LIST = "continue_list"
    CONTINUE_TABLE = "continue_table"
    ASSOCIATE_CAPTION = "associate_caption"
    CHAPTER_BOUNDARY = "chapter_boundary"
    SECTION_BOUNDARY = "section_boundary"
    NO_OPERATION = "no_operation"
    UNRESOLVED = "unresolved"


class BoundaryDecision(StrEnum):
    RESOLVED = "resolved"
    NO_CHANGE = "no_change"
    UNRESOLVED = "unresolved"


class BoundaryOperation(ContractModel):
    id: str
    operation_type: BoundaryOperationType
    decision: BoundaryDecision
    source_fragment_ids: list[FragmentId] = Field(default_factory=list)
    source_ids: list[SourceId] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason: str | None = None

    @field_validator("id")
    @classmethod
    def stable_operation_id(cls, value: str) -> str:
        validate_stable_id(value)
        return value

    @model_validator(mode="after")
    def references_for_active_operations(self) -> "BoundaryOperation":
        exempt = {BoundaryOperationType.NO_OPERATION, BoundaryOperationType.UNRESOLVED}
        if self.operation_type not in exempt and not (self.source_fragment_ids or self.source_ids):
            raise ValueError("boundary operations must reference source or semantic IDs")
        return self
