from __future__ import annotations

import binascii
import hashlib
import json
import os
import struct
import tempfile
import zlib
from pathlib import Path

import pypdfium2 as pdfium  # type: ignore[import-untyped]
from pypdfium2._helpers.misc import PdfiumError  # type: ignore[import-untyped]

from .errors import PdfRenderError
from .models import OpenedPdfLayout, PdfRenderConfig, PdfRuntimePage, RenderedPdfPage


def canonical_fingerprint(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def render_config_fingerprint(config: PdfRenderConfig) -> str:
    return canonical_fingerprint(config.model_dump(mode="json"))


def page_render_fingerprint(
    opened: OpenedPdfLayout, page: PdfRuntimePage, config: PdfRenderConfig
) -> str:
    return canonical_fingerprint(
        {
            "pdf_document_id": opened.source.document_id,
            "page_id": page.evidence.page_id,
            "render_config": config.model_dump(mode="json"),
        }
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", binascii.crc32(kind + payload))


def _png_bytes(bitmap: object) -> bytes:
    width = int(getattr(bitmap, "width"))
    height = int(getattr(bitmap, "height"))
    stride = int(getattr(bitmap, "stride"))
    channels = int(getattr(bitmap, "n_channels"))
    mode = str(getattr(bitmap, "mode"))
    raw = bytes(getattr(bitmap, "buffer"))
    if channels != 3 or mode not in {"BGR", "RGB"}:
        raise PdfRenderError(f"unsupported PDFium bitmap mode: {mode}/{channels}")
    rows = bytearray()
    for row_number in range(height):
        row = raw[row_number * stride : row_number * stride + width * 3]
        if mode == "BGR":
            row = bytes(channel for index in range(0, len(row), 3) for channel in (row[index + 2], row[index + 1], row[index]))
        rows.append(0)
        rows.extend(row)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(bytes(rows), 9)) + _chunk(b"IEND", b"")


class PdfPageRenderer:
    def render(
        self,
        opened: OpenedPdfLayout,
        page: PdfRuntimePage,
        workspace_root: Path,
        config: PdfRenderConfig,
    ) -> RenderedPdfPage:
        fingerprint = page_render_fingerprint(opened, page, config)
        relative_path = f"renders/{fingerprint}.png"
        output_path = workspace_root / relative_path
        metadata_path = workspace_root / "renders" / f"{fingerprint}.json"
        cached_metadata: RenderedPdfPage | None = None
        if output_path.exists() and metadata_path.exists():
            try:
                cached_metadata = RenderedPdfPage.model_validate_json(
                    metadata_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError):
                cached_metadata = None
        if cached_metadata is not None:
            payload = output_path.read_bytes()
            content_sha256 = hashlib.sha256(payload).hexdigest()
            if (
                cached_metadata.render_fingerprint != fingerprint
                or cached_metadata.content_sha256 != content_sha256
                or cached_metadata.render_config != config
            ):
                cached_metadata = None
            else:
                width, height = _png_dimensions(payload)
        if cached_metadata is None:
            try:
                document = pdfium.PdfDocument(opened.source_path)
                pdf_page = document[page.page_index]
                try:
                    bitmap = pdf_page.render(
                        scale=config.dpi / 72,
                        rotation=0,
                        may_draw_forms=config.include_annotations,
                        draw_annots=config.include_annotations,
                        fill_color=(*config.background_rgb, 255),
                        rev_byteorder=False,
                    )
                    try:
                        payload = _png_bytes(bitmap)
                        width, height = bitmap.width, bitmap.height
                    finally:
                        bitmap.close()
                finally:
                    pdf_page.close()
                    document.close()
            except (PdfiumError, OSError, ValueError) as error:
                raise PdfRenderError(f"failed to render PDF page {page.evidence.page_number}") from error
            _atomic_bytes(output_path, payload)
        return RenderedPdfPage(
            page=page,
            relative_path=relative_path,
            render_fingerprint=fingerprint,
            content_sha256=hashlib.sha256(payload).hexdigest(),
            width_pixels=width,
            height_pixels=height,
            render_config=config,
        )


def _png_dimensions(payload: bytes) -> tuple[int, int]:
    if payload[:8] != b"\x89PNG\r\n\x1a\n" or len(payload) < 24:
        raise PdfRenderError("cached rendered page is not a valid PNG")
    return struct.unpack(">II", payload[16:24])


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
            temporary_name = handle.name
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name is not None and Path(temporary_name).exists():
            Path(temporary_name).unlink()
