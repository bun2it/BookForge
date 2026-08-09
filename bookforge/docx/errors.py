"""Typed failures raised at the DOCX extraction boundary."""


class DocxExtractionError(Exception):
    """Base error safe for callers to present without an internal traceback."""


class InvalidDocxError(DocxExtractionError):
    """The input is not a readable ZIP/OOXML package."""


class MissingDocumentPartError(InvalidDocxError):
    """The package has no required main document part."""


class UnsupportedDocxStructureError(DocxExtractionError):
    """A required structure cannot be represented safely by M1A."""
