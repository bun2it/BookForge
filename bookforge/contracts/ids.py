"""Deterministic stable-ID construction and validation for source evidence."""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from collections.abc import Sequence


class StableIdError(ValueError):
    """Raised when an ID cannot be generated or does not follow the specification."""


class SourceObjectKind(StrEnum):
    PARAGRAPH = "par"
    TEXT_BLOCK = "b"
    RUN = "r"
    IMAGE = "img"
    DRAWING = "drw"
    TABLE = "tbl"
    TABLE_ROW = "row"
    TABLE_CELL = "c"


_DOCUMENT_RE = re.compile(r"^doc_[0-9a-f]{16}$")
_PDF_PAGE_RE = re.compile(r"^p\d{4,}$")
_PDF_OBJECT_RE = re.compile(r"^p\d{4,}_(?:par|b|img|drw|tbl)\d{4,}$")
_DOCX_OBJECT_RE = re.compile(r"^docx_(?:p|img|drw|tbl)\d{6,}$")
_NESTED_RE = re.compile(
    r"^(?:p\d{4,}_(?:par|b)\d{4,}|docx_p\d{6,})_r\d{4,}$"
    r"|^(?:p\d{4,}_tbl\d{4,}|docx_tbl\d{6,})_row\d{4,}(?:_c\d{4,})?$"
)
_SEMANTIC_RE = re.compile(r"^sem_f\d{6,}$")
_BOUNDARY_RE = re.compile(r"^bnd\d{6,}$")
_CLASSIFICATION_RE = re.compile(r"^cls_[0-9a-f]{20}$")
_REVIEW_RE = re.compile(r"^rev_[0-9a-f]{20}$")


def _positive_order(value: int, label: str) -> int:
    if value < 1:
        raise StableIdError(f"{label} must be >= 1")
    return value


def document_id(content_sha256: str) -> str:
    """Build a document namespace from a validated source-content SHA-256."""
    normalized = content_sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", normalized):
        raise StableIdError("document ID input must be a 64-character SHA-256")
    return f"doc_{normalized[:16]}"


def document_id_from_bytes(content: bytes) -> str:
    return document_id(hashlib.sha256(content).hexdigest())


def pdf_page_id(page_number: int) -> str:
    return f"p{_positive_order(page_number, 'page_number'):04d}"


def pdf_object_id(page_number: int, kind: SourceObjectKind, order: int) -> str:
    if kind in {SourceObjectKind.RUN, SourceObjectKind.TABLE_ROW, SourceObjectKind.TABLE_CELL}:
        raise StableIdError(f"{kind.value} requires a parent ID")
    return f"{pdf_page_id(page_number)}_{kind.value}{_positive_order(order, 'order'):04d}"


def docx_object_id(kind: SourceObjectKind, order: int) -> str:
    prefix = {
        SourceObjectKind.PARAGRAPH: "p",
        SourceObjectKind.IMAGE: "img",
        SourceObjectKind.DRAWING: "drw",
        SourceObjectKind.TABLE: "tbl",
    }.get(kind)
    if prefix is None:
        raise StableIdError(f"{kind.value} requires a parent or is not a DOCX body object")
    return f"docx_{prefix}{_positive_order(order, 'order'):06d}"


def run_id(parent_text_id: str, order: int) -> str:
    if not (_PDF_OBJECT_RE.fullmatch(parent_text_id) or re.fullmatch(r"docx_p\d{6,}", parent_text_id)):
        raise StableIdError("run parent must be a valid paragraph or text-block ID")
    return f"{parent_text_id}_r{_positive_order(order, 'order'):04d}"


def table_row_id(table_id: str, order: int) -> str:
    if not (re.fullmatch(r"p\d{4,}_tbl\d{4,}", table_id) or re.fullmatch(r"docx_tbl\d{6,}", table_id)):
        raise StableIdError("row parent must be a valid table ID")
    return f"{table_id}_row{_positive_order(order, 'order'):04d}"


def table_cell_id(row_id: str, order: int) -> str:
    if not re.fullmatch(r"(?:p\d{4,}_tbl\d{4,}|docx_tbl\d{6,})_row\d{4,}", row_id):
        raise StableIdError("cell parent must be a valid row ID")
    return f"{row_id}_c{_positive_order(order, 'order'):04d}"


def semantic_fragment_id(order: int) -> str:
    return f"sem_f{_positive_order(order, 'order'):06d}"


def boundary_operation_id(order: int) -> str:
    return f"bnd{_positive_order(order, 'order'):06d}"


def classification_result_id(
    *,
    target_source_ids: Sequence[str],
    taxonomy_version: str,
    classifier_name: str,
    classifier_version: str,
    configuration_fingerprint: str,
    input_fingerprint: str,
    context_fingerprint: str,
) -> str:
    """Derive an M3 decision ID without random or database-owned state."""
    components = (
        tuple(target_source_ids),
        taxonomy_version,
        classifier_name,
        classifier_version,
        configuration_fingerprint,
        input_fingerprint,
        context_fingerprint,
    )
    digest = hashlib.sha256(repr(components).encode("utf-8")).hexdigest()
    return f"cls_{digest[:20]}"


def classification_review_id(
    *, classification_id: str, reviewer_name: str, review_fingerprint: str
) -> str:
    components = (classification_id, reviewer_name, review_fingerprint)
    digest = hashlib.sha256(repr(components).encode("utf-8")).hexdigest()
    return f"rev_{digest[:20]}"


def validate_stable_id(value: str) -> str:
    matched = any(
        pattern.fullmatch(value)
        for pattern in (
            _DOCUMENT_RE,
            _PDF_PAGE_RE,
            _PDF_OBJECT_RE,
            _DOCX_OBJECT_RE,
            _NESTED_RE,
            _SEMANTIC_RE,
            _BOUNDARY_RE,
            _CLASSIFICATION_RE,
            _REVIEW_RE,
        )
    )
    hash_ids = ("doc_", "cls_", "rev_")
    if matched and (value.startswith(hash_ids) or all(int(part) >= 1 for part in re.findall(r"\d+", value))):
        return value
    raise StableIdError(f"invalid BookForge stable ID: {value!r}")
