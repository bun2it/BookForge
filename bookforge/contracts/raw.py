from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import Field, field_validator

from .common import BoundingBox, DocumentId, FrozenContractModel, PageId, ProcessingProvenance, SourceId, SourceType
from .ids import validate_stable_id


class RawStyle(FrozenContractModel):
    name: str | None = None
    font_family: str | None = None
    font_size: float | None = Field(default=None, ge=0)
    bold: bool | None = None
    italic: bool | None = None
    alignment: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawEvidenceBase(FrozenContractModel):
    id: SourceId
    document_id: DocumentId

    @field_validator("id")
    @classmethod
    def stable_evidence_id(cls, value: SourceId) -> SourceId:
        validate_stable_id(str(value))
        return value


class RawRun(RawEvidenceBase):
    kind: Literal["run"] = "run"
    text: str
    order: int = Field(ge=0)
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    style: RawStyle | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawTextBlock(RawEvidenceBase):
    kind: Literal["text_block"] = "text_block"
    page_id: PageId | None = None
    page_number: int | None = Field(default=None, ge=1)
    text: str
    bbox: BoundingBox | None = None
    order: int = Field(ge=0)
    runs: tuple[RawRun, ...] = ()
    style: RawStyle | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawParagraph(RawEvidenceBase):
    kind: Literal["paragraph"] = "paragraph"
    page_id: PageId | None = None
    page_number: int | None = Field(default=None, ge=1)
    text: str
    bbox: BoundingBox | None = None
    order: int = Field(ge=0)
    runs: tuple[RawRun, ...] = ()
    style: RawStyle | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawImage(RawEvidenceBase):
    kind: Literal["image"] = "image"
    page_id: PageId | None = None
    order: int = Field(ge=0)
    bbox: BoundingBox | None = None
    asset_reference: str
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawDrawing(RawEvidenceBase):
    kind: Literal["drawing"] = "drawing"
    page_id: PageId | None = None
    order: int = Field(ge=0)
    bbox: BoundingBox | None = None
    drawing_type: str | None = None
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawTableCell(RawEvidenceBase):
    kind: Literal["table_cell"] = "table_cell"
    row_index: int = Field(ge=0)
    column_index: int = Field(ge=0)
    text: str
    row_span: int | None = Field(default=None, ge=1)
    column_span: int | None = Field(default=None, ge=1)
    text_source_ids: tuple[SourceId, ...] = ()
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawTableRow(RawEvidenceBase):
    kind: Literal["table_row"] = "table_row"
    index: int = Field(ge=0)
    cells: tuple[RawTableCell, ...]


class RawTable(RawEvidenceBase):
    kind: Literal["table"] = "table"
    page_id: PageId | None = None
    order: int = Field(ge=0)
    bbox: BoundingBox | None = None
    rows: tuple[RawTableRow, ...]
    source_metadata: dict[str, Any] = Field(default_factory=dict)


class RawArtifactCandidate(RawEvidenceBase):
    kind: Literal["artifact_candidate"] = "artifact_candidate"
    evidence_source_ids: tuple[SourceId, ...] = Field(min_length=1)
    candidate_kind: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


RawObject = Annotated[
    Union[
        RawTextBlock,
        RawParagraph,
        RawRun,
        RawImage,
        RawDrawing,
        RawTable,
        RawTableRow,
        RawTableCell,
        RawArtifactCandidate,
    ],
    Field(discriminator="kind"),
]


class RawPage(FrozenContractModel):
    id: PageId
    document_id: DocumentId
    page_number: int = Field(ge=1)
    width: float | None = Field(default=None, gt=0)
    height: float | None = Field(default=None, gt=0)
    objects: tuple[RawObject, ...] = ()
    provenance: ProcessingProvenance

    @field_validator("id")
    @classmethod
    def stable_page_id(cls, value: PageId) -> PageId:
        validate_stable_id(str(value))
        return value


class RawDocument(FrozenContractModel):
    id: DocumentId
    source_type: SourceType
    original_name: str
    pages: tuple[RawPage, ...] = ()
    objects: tuple[RawObject, ...] = ()
    provenance: ProcessingProvenance
    source_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def stable_document_id(cls, value: DocumentId) -> DocumentId:
        validate_stable_id(str(value))
        return value
