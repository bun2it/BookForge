"""M6.0 PDF visual/layout evidence contracts; never authoritative content."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Annotated, Literal, NewType, Protocol, TypeAlias

from pydantic import Field, model_validator

from .classification import Fingerprint
from .common import FrozenContractModel

PdfDocumentId = NewType("PdfDocumentId", str)
PdfPageId = NewType("PdfPageId", str)
PdfRegionId = NewType("PdfRegionId", str)
PdfBoundaryId = NewType("PdfBoundaryId", str)
PdfMarkerId = NewType("PdfMarkerId", str)


class PdfSourceRole(StrEnum):
    CORROBORATION_ONLY = "corroboration_only"


class PdfLayoutSource(FrozenContractModel):
    role: Literal[PdfSourceRole.CORROBORATION_ONLY] = PdfSourceRole.CORROBORATION_ONLY
    document_id: PdfDocumentId = Field(pattern=r"^pdf_[0-9a-f]{16}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_name: str = Field(min_length=1)
    page_count: int = Field(ge=1)

    @model_validator(mode="after")
    def identity_matches_bytes(self) -> "PdfLayoutSource":
        if self.document_id != f"pdf_{self.content_sha256[:16]}":
            raise ValueError("PDF identity must derive from content SHA-256")
        return self


class PdfBoundingBox(FrozenContractModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered(self) -> "PdfBoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("PDF visual bounding box is not ordered")
        return self


class PdfPageEvidence(FrozenContractModel):
    page_id: PdfPageId = Field(pattern=r"^pdfp_[0-9a-f]{12}_p\d{4,}$")
    pdf_document_id: PdfDocumentId
    page_number: int = Field(ge=1)
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    rendered_page_reference: str | None = None


class PdfLineRegion(FrozenContractModel):
    region_id: PdfRegionId = Field(pattern=r"^pdfl_[0-9a-f]{12}_p\d{4,}_l\d{4,}$")
    page_id: PdfPageId
    visual_order: int = Field(ge=1)
    bbox: PdfBoundingBox
    baseline: float | None = None
    line_height: float | None = Field(default=None, gt=0)
    font_size_hint: float | None = Field(default=None, gt=0)
    alignment_text_hint: str | None = None


class PdfImageRegion(FrozenContractModel):
    region_id: PdfRegionId = Field(pattern=r"^pdfi_[0-9a-f]{12}_p\d{4,}_i\d{4,}$")
    page_id: PdfPageId
    visual_order: int = Field(ge=1)
    bbox: PdfBoundingBox
    nearby_line_region_ids: tuple[PdfRegionId, ...] = ()


class PdfPhysicalPageBoundary(FrozenContractModel):
    boundary_id: PdfBoundaryId = Field(pattern=r"^pdfb_[0-9a-f]{12}_p\d{4,}_p\d{4,}$")
    left_page_id: PdfPageId
    right_page_id: PdfPageId
    left_page_number: int = Field(ge=1)
    right_page_number: int = Field(ge=2)

    @model_validator(mode="after")
    def adjacent_pages(self) -> "PdfPhysicalPageBoundary":
        if self.right_page_number != self.left_page_number + 1:
            raise ValueError("physical PDF boundary requires adjacent pages")
        if self.left_page_id == self.right_page_id:
            raise ValueError("physical PDF boundary requires distinct pages")
        return self


class PdfVisualMarkerType(StrEnum):
    PARAGRAPH_END_CANDIDATE = "paragraph_end_candidate"
    NEW_PARAGRAPH_CANDIDATE = "new_paragraph_candidate"
    PARAGRAPH_CONTINUATION_CANDIDATE = "paragraph_continuation_candidate"
    CAPTION_REGION_CANDIDATE = "caption_region_candidate"
    HEADING_VISUAL_CANDIDATE = "heading_visual_candidate"
    LIST_CONTINUATION_CANDIDATE = "list_continuation_candidate"
    TABLE_CONTINUATION_CANDIDATE = "table_continuation_candidate"
    RUNNING_HEADER_FOOTER_PATTERN = "running_header_footer_pattern"
    UNKNOWN = "unknown"


class PdfVisualReasonCode(StrEnum):
    VISUAL_GAP = "visual_gap"
    FIRST_LINE_INDENT = "first_line_indent"
    SAME_INDENTATION = "same_indentation"
    SIMILAR_LINE_WIDTH = "similar_line_width"
    PAGE_CONTINUATION = "page_continuation"
    IMAGE_BETWEEN_TEXT = "image_between_text"
    CAPTION_BELOW_IMAGE = "caption_below_image"
    CAPTION_ABOVE_IMAGE = "caption_above_image"
    TABLE_GEOMETRY_CONTINUATION = "table_geometry_continuation"
    LIST_GEOMETRY_CONTINUATION = "list_geometry_continuation"


class PdfVisualParagraphGroup(FrozenContractModel):
    marker_id: PdfMarkerId = Field(pattern=r"^pdfm_[0-9a-f]{20}$")
    marker_type: Literal["visual_paragraph_group"] = "visual_paragraph_group"
    line_region_ids: tuple[PdfRegionId, ...] = Field(min_length=1)
    continues_across_physical_boundary_ids: tuple[PdfBoundaryId, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)


class PdfVisualObservation(FrozenContractModel):
    marker_id: PdfMarkerId = Field(pattern=r"^pdfm_[0-9a-f]{20}$")
    marker_type: Literal["visual_observation"] = "visual_observation"
    observation: PdfVisualMarkerType
    page_ids: tuple[PdfPageId, ...] = Field(min_length=1, max_length=2)
    line_region_ids: tuple[PdfRegionId, ...] = ()
    image_region_ids: tuple[PdfRegionId, ...] = ()
    physical_boundary_id: PdfBoundaryId | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason_codes: tuple[PdfVisualReasonCode, ...] = ()


PdfVisualMarker: TypeAlias = Annotated[
    PdfVisualParagraphGroup | PdfVisualObservation, Field(discriminator="marker_type")
]


class PdfScannerIdentity(FrozenContractModel):
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    provider: str | None = None
    model_identifier: str | None = None


class PdfScannerProvenance(FrozenContractModel):
    scanner: PdfScannerIdentity
    input_fingerprint: Fingerprint
    scanner_fingerprint: Fingerprint
    marker_schema_version: str = Field(min_length=1)
    scanner_policy_version: str = Field(min_length=1)


class PdfLayoutScanInput(FrozenContractModel):
    pdf_document_id: PdfDocumentId
    pages: tuple[PdfPageEvidence, ...] = Field(min_length=1, max_length=2)
    physical_boundary: PdfPhysicalPageBoundary | None = None
    rendered_page_references: tuple[str, ...] = Field(min_length=1, max_length=2)
    non_authoritative_alignment_hints: tuple[str, ...] = ()
    configuration_fingerprint: Fingerprint

    @model_validator(mode="after")
    def bounded_consistent_view(self) -> "PdfLayoutScanInput":
        if len(self.pages) != len(self.rendered_page_references):
            raise ValueError("rendered page references must match bounded page inputs")
        if any(page.pdf_document_id != self.pdf_document_id for page in self.pages):
            raise ValueError("scanner pages must belong to one PDF layout source")
        if self.physical_boundary is not None and len(self.pages) != 2:
            raise ValueError("page-boundary scan requires a page pair")
        return self


class PdfLayoutScanResult(FrozenContractModel):
    pdf_document_id: PdfDocumentId
    page_ids: tuple[PdfPageId, ...] = Field(min_length=1, max_length=2)
    line_regions: tuple[PdfLineRegion, ...] = ()
    image_regions: tuple[PdfImageRegion, ...] = ()
    markers: tuple[PdfVisualMarker, ...] = ()
    provenance: PdfScannerProvenance


class PdfLayoutScanner(Protocol):
    """Vendor-neutral future visual scanner; implementations return markers only."""

    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult: ...


def pdf_document_id(content_sha256: str) -> PdfDocumentId:
    if re.fullmatch(r"[0-9a-f]{64}", content_sha256) is None:
        raise ValueError("PDF content SHA-256 is invalid")
    return PdfDocumentId(f"pdf_{content_sha256[:16]}")


def pdf_layout_page_id(pdf_id: PdfDocumentId, page_number: int) -> PdfPageId:
    if page_number < 1:
        raise ValueError("PDF page number must be positive")
    digest = hashlib.sha256(str(pdf_id).encode()).hexdigest()[:12]
    return PdfPageId(f"pdfp_{digest}_p{page_number:04d}")


def pdf_line_region_id(pdf_id: PdfDocumentId, page_number: int, visual_order: int) -> PdfRegionId:
    if visual_order < 1:
        raise ValueError("PDF line visual order must be positive")
    page = pdf_layout_page_id(pdf_id, page_number)
    digest = str(page).split("_")[1]
    return PdfRegionId(f"pdfl_{digest}_p{page_number:04d}_l{visual_order:04d}")


def pdf_image_region_id(pdf_id: PdfDocumentId, page_number: int, visual_order: int) -> PdfRegionId:
    if visual_order < 1:
        raise ValueError("PDF image visual order must be positive")
    page = pdf_layout_page_id(pdf_id, page_number)
    digest = str(page).split("_")[1]
    return PdfRegionId(f"pdfi_{digest}_p{page_number:04d}_i{visual_order:04d}")


def pdf_boundary_id(pdf_id: PdfDocumentId, left_page_number: int) -> PdfBoundaryId:
    left = pdf_layout_page_id(pdf_id, left_page_number)
    digest = str(left).split("_")[1]
    return PdfBoundaryId(
        f"pdfb_{digest}_p{left_page_number:04d}_p{left_page_number + 1:04d}"
    )


def pdf_pair_fingerprint(docx_document_id: str, pdf_id: str) -> str:
    return hashlib.sha256(f"{docx_document_id}\0{pdf_id}".encode()).hexdigest()
