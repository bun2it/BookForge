"""M6.0 alignment between corroborating PDF layout and DOCX evidence."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, NewType, TypeAlias

from pydantic import Field, model_validator

from .classification import Fingerprint
from .common import DocumentId, FrozenContractModel, SourceId
from .pdf_layout import PdfDocumentId, PdfMarkerId, pdf_pair_fingerprint
from .source import SourceTextReference

LayoutAlignmentId = NewType("LayoutAlignmentId", str)


class AlignmentMethod(StrEnum):
    EXACT = "exact"
    NORMALIZED_EXACT = "normalized_exact"
    NGRAM = "ngram"
    FUZZY = "fuzzy"
    CONTEXT = "context"
    VISUAL_CONTEXT = "visual_context"
    AI_ASSISTED = "ai_assisted"
    UNRESOLVED = "unresolved"


class AlignmentStatus(StrEnum):
    MATCH = "match"
    NORMALIZED_MATCH = "normalized_match"
    PARTIAL_MATCH = "partial_match"
    AMBIGUOUS = "ambiguous"
    TEXT_MISMATCH = "text_mismatch"
    UNALIGNED = "unaligned"
    UNRESOLVED = "unresolved"


class AlignmentReasonCode(StrEnum):
    EXACT_SEQUENCE = "exact_sequence"
    NORMALIZATION_REQUIRED = "normalization_required"
    PARTIAL_RANGE = "partial_range"
    MANY_PDF_LINES_TO_ONE_DOCX_PARAGRAPH = "many_pdf_lines_to_one_docx_paragraph"
    ONE_VISUAL_PARAGRAPH_TO_MANY_DOCX_PARAGRAPHS = "one_visual_paragraph_to_many_docx_paragraphs"
    CROSSES_PHYSICAL_PAGE_BOUNDARY = "crosses_physical_page_boundary"
    MULTIPLE_CANDIDATES = "multiple_candidates"
    PDF_TEXT_LAYER_DISAGREES = "pdf_text_layer_disagrees"
    NO_RELIABLE_TARGET = "no_reliable_target"


class CorroborationSourcePair(FrozenContractModel):
    """Explicit pairing; DOCX remains authoritative and PDF corroborating."""

    docx_document_id: DocumentId
    pdf_document_id: PdfDocumentId
    pair_fingerprint: Fingerprint
    authoritative_source: Literal["docx"] = "docx"
    corroborating_source: Literal["pdf_layout"] = "pdf_layout"

    @model_validator(mode="after")
    def fingerprint_matches_pair(self) -> "CorroborationSourcePair":
        expected = pdf_pair_fingerprint(str(self.docx_document_id), str(self.pdf_document_id))
        if self.pair_fingerprint != expected:
            raise ValueError("source-pair fingerprint does not match DOCX/PDF identities")
        return self


class DocxTextAlignmentTarget(FrozenContractModel):
    target_type: Literal["text"] = "text"
    source_references: tuple[SourceTextReference, ...] = Field(min_length=1)


class DocxEvidenceAlignmentTarget(FrozenContractModel):
    target_type: Literal["evidence"] = "evidence"
    source_ids: tuple[SourceId, ...] = Field(min_length=1)


class DocxBoundaryAlignmentTarget(FrozenContractModel):
    target_type: Literal["boundary"] = "boundary"
    left_references: tuple[SourceTextReference, ...] = Field(min_length=1)
    right_references: tuple[SourceTextReference, ...] = Field(min_length=1)


DocxAlignmentTarget: TypeAlias = Annotated[
    DocxTextAlignmentTarget | DocxEvidenceAlignmentTarget | DocxBoundaryAlignmentTarget,
    Field(discriminator="target_type"),
]


class LayoutAlignmentCandidate(FrozenContractModel):
    target: DocxAlignmentTarget
    score: float | None = Field(default=None, ge=0, le=1)
    reason_codes: tuple[AlignmentReasonCode, ...] = ()


class LayoutAlignment(FrozenContractModel):
    alignment_id: LayoutAlignmentId = Field(pattern=r"^pda_[0-9a-f]{20}$")
    source_pair_fingerprint: Fingerprint
    pdf_marker_ids: tuple[PdfMarkerId, ...] = Field(min_length=1)
    target: DocxAlignmentTarget | None = None
    candidates: tuple[LayoutAlignmentCandidate, ...] = ()
    method: AlignmentMethod
    status: AlignmentStatus
    confidence: float | None = Field(default=None, ge=0, le=1)
    reason_codes: tuple[AlignmentReasonCode, ...] = ()
    input_fingerprint: Fingerprint
    alignment_policy_fingerprint: Fingerprint

    @model_validator(mode="after")
    def outcome_is_explicit(self) -> "LayoutAlignment":
        matched = {
            AlignmentStatus.MATCH,
            AlignmentStatus.NORMALIZED_MATCH,
            AlignmentStatus.PARTIAL_MATCH,
        }
        unresolved = {
            AlignmentStatus.AMBIGUOUS,
            AlignmentStatus.TEXT_MISMATCH,
            AlignmentStatus.UNALIGNED,
            AlignmentStatus.UNRESOLVED,
        }
        if self.status in matched and self.target is None:
            raise ValueError("matched PDF layout evidence requires a DOCX target")
        if self.status in unresolved and self.target is not None:
            raise ValueError("unresolved alignment outcomes cannot select a DOCX target")
        if self.status is AlignmentStatus.AMBIGUOUS and len(self.candidates) < 2:
            raise ValueError("ambiguous alignment requires at least two candidates")
        if len(self.pdf_marker_ids) != len(set(self.pdf_marker_ids)):
            raise ValueError("alignment PDF marker IDs must be unique")
        return self
