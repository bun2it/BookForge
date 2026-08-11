"""Source-neutral M6 corroboration evidence for later M3/M4 consumers."""

from __future__ import annotations

from enum import StrEnum
from typing import NewType

from pydantic import Field, model_validator

from .classification import Fingerprint
from .common import FrozenContractModel, SourceId
from .layout_alignment import LayoutAlignmentId
from .pdf_layout import PdfMarkerId
from .source import SourceTextReference

CorroborationEvidenceId = NewType("CorroborationEvidenceId", str)


class CorroborationObservation(StrEnum):
    PHYSICAL_PAGE_BOUNDARY = "physical_page_boundary"
    SAME_VISUAL_PARAGRAPH = "same_visual_paragraph"
    PARAGRAPH_END_CANDIDATE = "paragraph_end_candidate"
    NEW_PARAGRAPH_CANDIDATE = "new_paragraph_candidate"
    PARAGRAPH_CONTINUATION_CANDIDATE = "paragraph_continuation_candidate"
    IMAGE_POSITION_CANDIDATE = "image_position_candidate"
    CAPTION_PROXIMITY_CANDIDATE = "caption_proximity_candidate"
    HEADING_VISUAL_CANDIDATE = "heading_visual_candidate"
    LIST_CONTINUATION_CANDIDATE = "list_continuation_candidate"
    TABLE_CONTINUATION_CANDIDATE = "table_continuation_candidate"
    RUNNING_HEADER_FOOTER_PATTERN = "running_header_footer_pattern"
    UNKNOWN = "unknown"


class CorroborationProvenance(FrozenContractModel):
    source_pair_fingerprint: Fingerprint
    scanner_fingerprint: Fingerprint
    alignment_policy_fingerprint: Fingerprint
    corroboration_policy_fingerprint: Fingerprint


class LayoutCorroborationEvidence(FrozenContractModel):
    """Observation only: never a final semantic, flow, or placement decision."""

    evidence_id: CorroborationEvidenceId = Field(pattern=r"^pdc_[0-9a-f]{20}$")
    observation: CorroborationObservation
    pdf_marker_ids: tuple[PdfMarkerId, ...] = Field(min_length=1)
    alignment_ids: tuple[LayoutAlignmentId, ...] = ()
    docx_source_references: tuple[SourceTextReference, ...] = ()
    docx_source_ids: tuple[SourceId, ...] = ()
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason_codes: tuple[str, ...] = ()
    provenance: CorroborationProvenance

    @model_validator(mode="after")
    def references_are_consistent(self) -> "LayoutCorroborationEvidence":
        known = set(self.docx_source_ids)
        if known and any(ref.source_id not in known for ref in self.docx_source_references):
            raise ValueError("corroboration text references must belong to its DOCX evidence IDs")
        if len(self.pdf_marker_ids) != len(set(self.pdf_marker_ids)):
            raise ValueError("corroboration PDF marker IDs must be unique")
        return self
