"""Deterministic DOCX evidence extraction boundary."""

from .errors import (
    DocxExtractionError,
    InvalidDocxError,
    MissingDocumentPartError,
    UnsupportedDocxStructureError,
)
from .extractor import DocxExtractor
from .models import DocxExtractionResult, DocxExtractionWarning, ExtractedAsset

__all__ = [
    "DocxExtractionError",
    "DocxExtractionResult",
    "DocxExtractionWarning",
    "DocxExtractor",
    "ExtractedAsset",
    "InvalidDocxError",
    "MissingDocumentPartError",
    "UnsupportedDocxStructureError",
]
