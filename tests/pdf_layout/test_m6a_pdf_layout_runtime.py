from __future__ import annotations

import ctypes
import hashlib
import shutil
from pathlib import Path

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pypdfium2.raw as pdfium_raw  # type: ignore[import-untyped]
import pytest
from pypdfium2._helpers.misc import PdfiumError  # type: ignore[import-untyped]

from bookforge.contracts.pdf_layout import (
    PdfBoundingBox,
    PdfImageRegion,
    PdfLayoutScanInput,
    PdfLayoutScanResult,
    PdfLineRegion,
    PdfScannerIdentity,
    PdfScannerProvenance,
    PdfVisualMarkerType,
    PdfVisualObservation,
    PdfVisualParagraphGroup,
    pdf_image_region_id,
    pdf_line_region_id,
)
from bookforge.pdf_layout import (
    PdfEncryptedError,
    PdfLayoutReader,
    PdfLayoutScanPipeline,
    PdfOpenError,
    PdfRenderConfig,
    PdfScanRunStatus,
)

SCANNER_IDENTITY = PdfScannerIdentity(name="predefined-fixture-scanner", version="1")
SCANNER_FINGERPRINT = "d" * 64


def make_pdf(path: Path, sizes: tuple[tuple[float, float], ...], rotations: tuple[int, ...] = ()) -> None:
    document = pdfium.PdfDocument.new()
    try:
        for index, (width, height) in enumerate(sizes):
            page = document.new_page(width, height)
            if index < len(rotations) and rotations[index]:
                page.set_rotation(rotations[index])
            page.close()
        document.save(path)
    finally:
        document.close()


def make_visual_vietnamese_pdf(path: Path) -> None:
    document = pdfium.PdfDocument.new()
    try:
        font = pdfium.PdfFont.load_standard(document, "Helvetica")
        page_text = (
            ("Cà phê triết đạo", "Một đoạn văn tiếp tục ở cuối trang"),
            ("sang trang kế tiếp.", "Hình 1 — Minh họa"),
        )
        for page_number, lines in enumerate(page_text):
            page = document.new_page(300, 400)
            for line_number, value in enumerate(lines):
                text_object = pdfium_raw.FPDFPageObj_CreateTextObj(document.raw, font.raw, 14)
                encoded = value.encode("utf-16-le") + b"\0\0"
                wide = (ctypes.c_ushort * (len(encoded) // 2)).from_buffer_copy(encoded)
                assert pdfium_raw.FPDFText_SetText(text_object, wide)
                pdfium_raw.FPDFPageObj_Transform(
                    text_object, 1, 0, 0, 1, 30, 350 - line_number * 28
                )
                pdfium_raw.FPDFPage_InsertObject(page.raw, text_object)
            if page_number == 0:
                rectangle = pdfium_raw.FPDFPageObj_CreateNewRect(60, 140, 180, 100)
                assert pdfium_raw.FPDFPageObj_SetFillColor(rectangle, 30, 90, 150, 255)
                pdfium_raw.FPDFPage_InsertObject(page.raw, rectangle)
            assert pdfium_raw.FPDFPage_GenerateContent(page.raw)
            page.close()
        document.save(path)
    finally:
        document.close()


def marker_id(value: str) -> str:
    return "pdfm_" + hashlib.sha256(value.encode()).hexdigest()[:20]


class FixtureScanner:
    """Returns predefined typed shapes from IDs; never examines rendered pixels."""

    def __init__(self, fail_page_number: int | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_page_number = fail_page_number

    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        page_ids = tuple(str(page.page_id) for page in scan_input.pages)
        self.calls.append(page_ids)
        if self.fail_page_number in {page.page_number for page in scan_input.pages}:
            raise RuntimeError("planned fixture interruption")
        lines: list[PdfLineRegion] = []
        images: list[PdfImageRegion] = []
        for page in scan_input.pages:
            lines.append(
                PdfLineRegion(
                    region_id=pdf_line_region_id(
                        scan_input.pdf_document_id, page.page_number, 1
                    ),
                    page_id=page.page_id,
                    visual_order=1,
                    bbox=PdfBoundingBox(x0=10, y0=10, x1=page.width - 10, y1=30),
                )
            )
        markers: list[PdfVisualParagraphGroup | PdfVisualObservation] = []
        if len(scan_input.pages) == 1:
            page = scan_input.pages[0]
            image = PdfImageRegion(
                region_id=pdf_image_region_id(
                    scan_input.pdf_document_id, page.page_number, 1
                ),
                page_id=page.page_id,
                visual_order=2,
                bbox=PdfBoundingBox(x0=20, y0=50, x1=min(page.width, 120), y1=min(page.height, 140)),
                nearby_line_region_ids=(lines[0].region_id,),
            )
            images.append(image)
            markers.append(
                PdfVisualParagraphGroup(
                    marker_id=marker_id(f"page:{page.page_id}"),
                    line_region_ids=(lines[0].region_id,),
                )
            )
        else:
            assert scan_input.physical_boundary is not None
            markers.append(
                PdfVisualObservation(
                    marker_id=marker_id(f"pair:{page_ids}"),
                    observation=PdfVisualMarkerType.PARAGRAPH_CONTINUATION_CANDIDATE,
                    page_ids=tuple(page.page_id for page in scan_input.pages),
                    line_region_ids=tuple(line.region_id for line in lines),
                    physical_boundary_id=scan_input.physical_boundary.boundary_id,
                    confidence=0.75,
                )
            )
        return PdfLayoutScanResult(
            pdf_document_id=scan_input.pdf_document_id,
            page_ids=tuple(page.page_id for page in scan_input.pages),
            line_regions=tuple(lines),
            image_regions=tuple(images),
            markers=tuple(markers),
            provenance=PdfScannerProvenance(
                scanner=SCANNER_IDENTITY,
                input_fingerprint=scan_input.configuration_fingerprint,
                scanner_fingerprint=SCANNER_FINGERPRINT,
                marker_schema_version="m6.0-v1",
                scanner_policy_version="fixture-v1",
            ),
        )


def test_real_pdf_identity_pages_rotation_sizes_and_boundaries(tmp_path: Path) -> None:
    source = tmp_path / "nguon-viet.pdf"
    make_pdf(source, ((300, 400), (500, 250)), rotations=(0, 90))
    renamed = tmp_path / "renamed.pdf"
    shutil.copyfile(source, renamed)
    first = PdfLayoutReader().open(source)
    second = PdfLayoutReader().open(renamed)
    assert first.source.document_id == second.source.document_id
    assert [page.evidence.page_id for page in first.pages] == [
        page.evidence.page_id for page in second.pages
    ]
    assert [(page.evidence.width, page.evidence.height) for page in first.pages] == [
        (300, 400),
        (250, 500),
    ]
    assert first.pages[1].rotation_degrees == 90
    assert len(first.boundaries) == 1
    different = tmp_path / "different.pdf"
    make_pdf(different, ((300, 401),))
    assert PdfLayoutReader().open(different).source.document_id != first.source.document_id


def test_invalid_and_single_page_pdf_behavior(tmp_path: Path) -> None:
    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    with pytest.raises(PdfOpenError):
        PdfLayoutReader().open(invalid)
    source = tmp_path / "one.pdf"
    make_pdf(source, ((300, 400),))
    opened = PdfLayoutReader().open(source)
    assert len(opened.pages) == 1
    assert opened.boundaries == ()


def test_password_failure_is_exposed_as_typed_encrypted_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "encrypted.pdf"
    source.write_bytes(b"%PDF-encrypted-fixture")

    def reject_password(_source: bytes) -> None:
        raise PdfiumError("PDFium: Incorrect password error")

    monkeypatch.setattr("bookforge.pdf_layout.reader.pdfium.PdfDocument", reject_password)
    with pytest.raises(PdfEncryptedError):
        PdfLayoutReader().open(source)


def test_render_png_is_cached_deterministically_and_not_a_book_asset(tmp_path: Path) -> None:
    source = tmp_path / "visual.pdf"
    make_pdf(source, ((300, 400),))
    pipeline = PdfLayoutScanPipeline()
    result = pipeline.run(
        source,
        tmp_path / "workspace",
        FixtureScanner(),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    render_paths = list((tmp_path / "workspace/pdf_layout/renders").glob("*.png"))
    assert len(render_paths) == 1
    first_bytes = render_paths[0].read_bytes()
    resumed = pipeline.resume(
        source,
        tmp_path / "workspace",
        FixtureScanner(),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    assert render_paths[0].read_bytes() == first_bytes
    assert resumed.manifest.reused == 1
    assert not (tmp_path / "workspace/assets").exists()
    assert "book" not in result.model_dump()


def test_page_and_pair_units_markers_persist_and_reload(tmp_path: Path) -> None:
    source = tmp_path / "two-pages.pdf"
    make_visual_vietnamese_pdf(source)
    scanner = FixtureScanner()
    result = PdfLayoutScanPipeline().run(
        source,
        tmp_path / "workspace",
        scanner,
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    assert len(result.page_work_units) == 2
    assert len(result.page_pair_work_units) == 1
    assert len(result.results) == 3
    assert result.manifest.status is PdfScanRunStatus.COMPLETE
    pair = result.results[-1]
    assert isinstance(pair.markers[0], PdfVisualObservation)
    assert pair.markers[0].physical_boundary_id == result.boundaries[0].boundary_id
    assert "join" not in pair.model_dump_json().lower()
    assert len(list((tmp_path / "workspace/pdf_layout/results").glob("*.json"))) == 3


def test_resume_preserves_success_and_retries_only_failed_units(tmp_path: Path) -> None:
    source = tmp_path / "three-pages.pdf"
    make_pdf(source, ((200, 200),) * 3)
    workspace = tmp_path / "workspace"
    first = PdfLayoutScanPipeline().run(
        source,
        workspace,
        FixtureScanner(fail_page_number=3),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    assert first.manifest.status is PdfScanRunStatus.PARTIAL
    successful = len(first.results)
    scanner = FixtureScanner()
    resumed = PdfLayoutScanPipeline().resume(
        source,
        workspace,
        scanner,
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    assert resumed.manifest.status is PdfScanRunStatus.COMPLETE
    assert resumed.manifest.reused == successful
    assert len(scanner.calls) == 5 - successful


def test_render_and_scanner_config_changes_stale_dependencies(tmp_path: Path) -> None:
    source = tmp_path / "config.pdf"
    make_pdf(source, ((200, 300),))
    pipeline = PdfLayoutScanPipeline()
    first = pipeline.run(
        source,
        tmp_path / "workspace",
        FixtureScanner(),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
        PdfRenderConfig(dpi=72),
    )
    second = pipeline.run(
        source,
        tmp_path / "workspace",
        FixtureScanner(),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
        PdfRenderConfig(dpi=144),
    )
    assert first.source.document_id == second.source.document_id
    assert first.pages[0].evidence.page_id == second.pages[0].evidence.page_id
    assert first.page_work_units[0].work_unit_id != second.page_work_units[0].work_unit_id
    changed_scanner = "e" * 64
    scanner = FixtureScanner()
    with pytest.raises(Exception):
        pipeline.run(
            source,
            tmp_path / "workspace",
            scanner,
            SCANNER_IDENTITY,
            changed_scanner,
            continue_on_failure=False,
        )


class InvalidPageScanner(FixtureScanner):
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        result = super().scan(scan_input)
        return result.model_copy(update={"page_ids": ("pdfp_000000000000_p9999",)})


class InvalidGeometryScanner(FixtureScanner):
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        result = super().scan(scan_input)
        bad = result.line_regions[0].model_copy(
            update={"bbox": PdfBoundingBox(x0=0, y0=0, x1=99999, y1=99999)}
        )
        return result.model_copy(update={"line_regions": (bad,)})


@pytest.mark.parametrize("scanner", [InvalidPageScanner(), InvalidGeometryScanner()])
def test_malformed_scanner_output_fails_one_unit_visibly(
    tmp_path: Path, scanner: FixtureScanner
) -> None:
    source = tmp_path / "bad-output.pdf"
    make_pdf(source, ((200, 300),))
    result = PdfLayoutScanPipeline().run(
        source,
        tmp_path / "workspace",
        scanner,
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
    )
    assert result.manifest.status is PdfScanRunStatus.FAILED
    assert result.results == ()
    assert len(result.failures) == 1


def test_page_range_is_contiguous_and_does_not_change_source_identity(tmp_path: Path) -> None:
    source = tmp_path / "range.pdf"
    make_pdf(source, ((100, 100),) * 4)
    full_source = PdfLayoutReader().open(source).source
    result = PdfLayoutScanPipeline().run(
        source,
        tmp_path / "workspace",
        FixtureScanner(),
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
        page_range=range(1, 3),
    )
    assert result.source.document_id == full_source.document_id
    assert [page.evidence.page_number for page in result.pages] == [2, 3]
    assert len(result.page_pair_work_units) == 1


def test_large_pdf_runs_incrementally_with_disk_render_cache(tmp_path: Path) -> None:
    source = tmp_path / "large.pdf"
    make_pdf(source, ((72, 72),) * 100)
    scanner = FixtureScanner()
    result = PdfLayoutScanPipeline().run(
        source,
        tmp_path / "workspace",
        scanner,
        SCANNER_IDENTITY,
        SCANNER_FINGERPRINT,
        PdfRenderConfig(dpi=72),
    )
    assert len(result.pages) == 100
    assert len(result.boundaries) == 99
    assert len(result.page_work_units) == 100
    assert len(result.page_pair_work_units) == 99
    assert len(result.results) == 199
    assert len(list((tmp_path / "workspace/pdf_layout/renders").glob("*.png"))) == 100
    assert result.manifest.status is PdfScanRunStatus.COMPLETE
