from __future__ import annotations

import hashlib
from pathlib import Path

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pypdfium2._helpers.misc import PdfiumError  # type: ignore[import-untyped]

from bookforge.contracts.pdf_layout import (
    PdfLayoutSource,
    PdfPageEvidence,
    PdfPhysicalPageBoundary,
    pdf_boundary_id,
    pdf_document_id,
    pdf_layout_page_id,
)

from .errors import PdfEncryptedError, PdfOpenError
from .models import OpenedPdfLayout, PdfRuntimePage


class PdfLayoutReader:
    """Deterministic PDF source mechanics with no text/content extraction."""

    def open(self, source_path: Path) -> OpenedPdfLayout:
        path = source_path.resolve()
        try:
            source_bytes = path.read_bytes()
        except OSError as error:
            raise PdfOpenError(f"cannot read PDF source: {source_path}") from error
        digest = hashlib.sha256(source_bytes).hexdigest()
        try:
            document = pdfium.PdfDocument(source_bytes)
        except (PdfiumError, ValueError, TypeError) as error:
            if "password" in str(error).lower() or "security" in str(error).lower():
                raise PdfEncryptedError(
                    "encrypted/password-protected PDF is unsupported"
                ) from error
            raise PdfOpenError(f"invalid or unreadable PDF: {source_path}") from error
        try:
            count = len(document)
            if count < 1:
                raise PdfOpenError("PDF contains no pages")
            pdf_id = pdf_document_id(digest)
            source = PdfLayoutSource(
                document_id=pdf_id,
                content_sha256=digest,
                original_name=path.name,
                page_count=count,
            )
            pages: list[PdfRuntimePage] = []
            for index in range(count):
                page = document[index]
                try:
                    width, height = page.get_size()
                    rotation = page.get_rotation()
                finally:
                    page.close()
                page_number = index + 1
                pages.append(
                    PdfRuntimePage(
                        evidence=PdfPageEvidence(
                            page_id=pdf_layout_page_id(pdf_id, page_number),
                            pdf_document_id=pdf_id,
                            page_number=page_number,
                            width=width,
                            height=height,
                        ),
                        page_index=index,
                        rotation_degrees=rotation,
                    )
                )
            boundaries = tuple(
                PdfPhysicalPageBoundary(
                    boundary_id=pdf_boundary_id(pdf_id, number),
                    left_page_id=pages[number - 1].evidence.page_id,
                    right_page_id=pages[number].evidence.page_id,
                    left_page_number=number,
                    right_page_number=number + 1,
                )
                for number in range(1, count)
            )
            return OpenedPdfLayout(
                source=source,
                source_path=path,
                pages=tuple(pages),
                boundaries=boundaries,
            )
        finally:
            document.close()
