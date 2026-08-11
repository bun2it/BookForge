from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pypdfium2 as pdfium  # type: ignore[import-untyped]
import pytest

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
    PdfVisualReasonCode,
    pdf_image_region_id,
    pdf_line_region_id,
)
from bookforge.pdf_layout import (
    PdfCatalogReadiness,
    PdfLayoutCatalogBuilder,
    PdfLayoutScanPipeline,
    PdfLayoutObservationCatalog,
    PdfLayoutRunResult,
    PdfLayoutWorkspace,
    PdfMarkerConflictError,
    PdfMarkerReferenceError,
    PdfRenderConfig,
    PdfScannerOutputError,
    PdfStaleScannerResultError,
)

IDENTITY = PdfScannerIdentity(name="catalog-fixture", version="1")
SCANNER_FP = "a" * 64


def make_pdf(path: Path, pages: int) -> None:
    document = pdfium.PdfDocument.new()
    try:
        for _ in range(pages):
            document.new_page(300, 400).close()
        document.save(path)
    finally:
        document.close()


def marker_id(value: str) -> str:
    return "pdfm_" + hashlib.sha256(value.encode()).hexdigest()[:20]


def line(scan_input: PdfLayoutScanInput, page_index: int, order: int) -> PdfLineRegion:
    page = scan_input.pages[page_index]
    return PdfLineRegion(
        region_id=pdf_line_region_id(scan_input.pdf_document_id, page.page_number, order),
        page_id=page.page_id,
        visual_order=order,
        bbox=PdfBoundingBox(x0=20, y0=20 + order * 25, x1=280, y1=35 + order * 25),
        alignment_text_hint=f"non-authoritative hint {page.page_number}:{order}",
    )


def result(
    scan_input: PdfLayoutScanInput,
    lines: tuple[PdfLineRegion, ...] = (),
    images: tuple[PdfImageRegion, ...] = (),
    markers: tuple[PdfVisualParagraphGroup | PdfVisualObservation, ...] = (),
    scanner_fp: str = SCANNER_FP,
) -> PdfLayoutScanResult:
    return PdfLayoutScanResult(
        pdf_document_id=scan_input.pdf_document_id,
        page_ids=tuple(page.page_id for page in scan_input.pages),
        line_regions=lines,
        image_regions=images,
        markers=markers,
        provenance=PdfScannerProvenance(
            scanner=IDENTITY,
            input_fingerprint=scan_input.configuration_fingerprint,
            scanner_fingerprint=scanner_fp,
            marker_schema_version="m6.0-v1",
            scanner_policy_version="predefined-v1",
        ),
    )


class RichFixtureScanner:
    """Predefined ID mapping only; it never opens the rendered PNG references."""

    def __init__(self, scanner_fp: str = SCANNER_FP, empty_page: int | None = None) -> None:
        self.scanner_fp = scanner_fp
        self.empty_page = empty_page
        self.calls = 0

    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        self.calls += 1
        if len(scan_input.pages) == 1:
            page = scan_input.pages[0]
            if page.page_number == self.empty_page:
                return result(scan_input, scanner_fp=self.scanner_fp)
            lines = tuple(line(scan_input, 0, order) for order in (1, 2, 4, 5, 6))
            image = PdfImageRegion(
                region_id=pdf_image_region_id(
                    scan_input.pdf_document_id, page.page_number, 3
                ),
                page_id=page.page_id,
                visual_order=3,
                bbox=PdfBoundingBox(x0=60, y0=120, x1=220, y1=220),
                nearby_line_region_ids=(lines[1].region_id, lines[2].region_id),
            )
            groups = (
                PdfVisualParagraphGroup(
                    marker_id=marker_id(f"group-a:{page.page_id}"),
                    line_region_ids=(lines[0].region_id, lines[1].region_id),
                    confidence=0.9,
                ),
                PdfVisualParagraphGroup(
                    marker_id=marker_id(f"group-b:{page.page_id}"),
                    line_region_ids=(lines[2].region_id,),
                ),
                PdfVisualParagraphGroup(
                    marker_id=marker_id(f"group-c:{page.page_id}"),
                    line_region_ids=(lines[4].region_id,),
                ),
            )
            observations = (
                PdfVisualObservation(
                    marker_id=marker_id(f"end:{page.page_id}"),
                    observation=PdfVisualMarkerType.PARAGRAPH_END_CANDIDATE,
                    page_ids=(page.page_id,),
                    line_region_ids=(lines[1].region_id,),
                    confidence=0.7,
                ),
                PdfVisualObservation(
                    marker_id=marker_id(f"caption:{page.page_id}"),
                    observation=PdfVisualMarkerType.CAPTION_REGION_CANDIDATE,
                    page_ids=(page.page_id,),
                    line_region_ids=(lines[3].region_id,),
                    image_region_ids=(image.region_id,),
                    reason_codes=(PdfVisualReasonCode.CAPTION_BELOW_IMAGE,),
                ),
                PdfVisualObservation(
                    marker_id=marker_id(f"heading:{page.page_id}"),
                    observation=PdfVisualMarkerType.HEADING_VISUAL_CANDIDATE,
                    page_ids=(page.page_id,),
                    line_region_ids=(lines[0].region_id,),
                ),
                PdfVisualObservation(
                    marker_id=marker_id(f"list:{page.page_id}"),
                    observation=PdfVisualMarkerType.LIST_CONTINUATION_CANDIDATE,
                    page_ids=(page.page_id,),
                    line_region_ids=(lines[2].region_id,),
                ),
                PdfVisualObservation(
                    marker_id=marker_id(f"table:{page.page_id}"),
                    observation=PdfVisualMarkerType.TABLE_CONTINUATION_CANDIDATE,
                    page_ids=(page.page_id,),
                    line_region_ids=(lines[4].region_id,),
                ),
            )
            return result(
                scan_input,
                lines,
                (image,),
                (*groups, *observations),
                self.scanner_fp,
            )
        left = line(scan_input, 0, 6)
        right = line(scan_input, 1, 1)
        assert scan_input.physical_boundary is not None
        group = PdfVisualParagraphGroup(
            marker_id=marker_id(
                f"cross-group:{scan_input.pages[0].page_id}:{scan_input.pages[1].page_id}"
            ),
            line_region_ids=(left.region_id, right.region_id),
            continues_across_physical_boundary_ids=(
                scan_input.physical_boundary.boundary_id,
            ),
        )
        continuation = PdfVisualObservation(
            marker_id=marker_id(
                f"continue:{scan_input.pages[0].page_id}:{scan_input.pages[1].page_id}"
            ),
            observation=PdfVisualMarkerType.PARAGRAPH_CONTINUATION_CANDIDATE,
            page_ids=tuple(page.page_id for page in scan_input.pages),
            line_region_ids=(left.region_id, right.region_id),
            physical_boundary_id=scan_input.physical_boundary.boundary_id,
            reason_codes=(PdfVisualReasonCode.PAGE_CONTINUATION,),
        )
        return result(
            scan_input,
            (left, right),
            markers=(group, continuation),
            scanner_fp=self.scanner_fp,
        )


class UnknownFixtureScanner(RichFixtureScanner):
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        if len(scan_input.pages) != 1:
            return super().scan(scan_input)
        page = scan_input.pages[0]
        unknown = PdfVisualObservation(
            marker_id=marker_id(f"unknown:{page.page_id}"),
            observation=PdfVisualMarkerType.UNKNOWN,
            page_ids=(page.page_id,),
        )
        return result(scan_input, markers=(unknown,), scanner_fp=self.scanner_fp)


class FailingFixtureScanner(RichFixtureScanner):
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        if any(page.page_number == 2 for page in scan_input.pages):
            raise RuntimeError("planned catalog fixture failure")
        return super().scan(scan_input)


class ImageWithoutCaptionScanner(RichFixtureScanner):
    def scan(self, scan_input: PdfLayoutScanInput) -> PdfLayoutScanResult:
        scan_result = super().scan(scan_input)
        return scan_result.model_copy(
            update={
                "markers": tuple(
                    marker
                    for marker in scan_result.markers
                    if not (
                        isinstance(marker, PdfVisualObservation)
                        and marker.observation
                        is PdfVisualMarkerType.CAPTION_REGION_CANDIDATE
                    )
                )
            }
        )


def scan_and_catalog(
    tmp_path: Path,
    pages: int = 1,
    scanner: RichFixtureScanner | None = None,
    page_range: range | None = None,
    dpi: int = 72,
) -> tuple[PdfLayoutRunResult, PdfLayoutObservationCatalog, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / "source.pdf"
    make_pdf(source, pages)
    workspace_path = tmp_path / "workspace"
    actual_scanner = scanner or RichFixtureScanner()
    run = PdfLayoutScanPipeline().run(
        source,
        workspace_path,
        actual_scanner,
        IDENTITY,
        actual_scanner.scanner_fp,
        PdfRenderConfig(dpi=dpi),
        page_range=page_range,
    )
    catalog = PdfLayoutCatalogBuilder().build(
        run, PdfLayoutWorkspace(workspace_path)
    )
    return run, catalog, workspace_path


def test_single_page_catalog_preserves_topology_groups_and_signals(tmp_path: Path) -> None:
    _, catalog, workspace = scan_and_catalog(tmp_path)
    assert catalog.readiness.status is PdfCatalogReadiness.READY
    assert [entry.visual_order for entry in catalog.pages[0].visual_topology] == [1, 2, 3, 4, 5, 6]
    assert [entry.kind.value for entry in catalog.pages[0].visual_topology][2] == "image"
    assert len(catalog.paragraph_groups) == 3
    assert len(catalog.image_regions) == 1
    types = {marker.observation for marker in catalog.observations}
    assert {
        PdfVisualMarkerType.PARAGRAPH_END_CANDIDATE,
        PdfVisualMarkerType.CAPTION_REGION_CANDIDATE,
        PdfVisualMarkerType.HEADING_VISUAL_CANDIDATE,
        PdfVisualMarkerType.LIST_CONTINUATION_CANDIDATE,
        PdfVisualMarkerType.TABLE_CONTINUATION_CANDIDATE,
    } <= types
    assert (workspace / "pdf_layout/catalog/observations.json").is_file()
    assert "semantic" not in catalog.model_dump()
    assert "join" not in catalog.model_dump_json().lower()


def test_cross_page_group_and_continuation_reference_reader_boundary(tmp_path: Path) -> None:
    run, catalog, _ = scan_and_catalog(tmp_path, pages=2)
    assert catalog.readiness.status is PdfCatalogReadiness.READY
    boundary = run.boundaries[0]
    assert catalog.boundaries[0].boundary == boundary
    assert catalog.boundaries[0].paragraph_group_ids
    continuation = next(
        marker
        for marker in catalog.observations
        if marker.observation is PdfVisualMarkerType.PARAGRAPH_CONTINUATION_CANDIDATE
    )
    assert continuation.physical_boundary_id == boundary.boundary_id


def test_catalog_rebuild_is_byte_identical_without_scanner_reinvocation(tmp_path: Path) -> None:
    scanner = RichFixtureScanner()
    _, catalog, workspace_path = scan_and_catalog(tmp_path, pages=2, scanner=scanner)
    calls = scanner.calls
    serialized = catalog.model_dump_json()
    catalog_path = workspace_path / "pdf_layout/catalog/observations.json"
    persisted = catalog_path.read_bytes()
    shutil.rmtree(workspace_path / "pdf_layout/catalog")
    rebuilt = PdfLayoutCatalogBuilder().rebuild(workspace_path)
    assert scanner.calls == calls
    assert rebuilt.model_dump_json() == serialized
    assert rebuilt.catalog_fingerprint == catalog.catalog_fingerprint
    assert catalog_path.read_bytes() == persisted
    assert PdfLayoutWorkspace(workspace_path).load_catalog() == rebuilt


def test_same_inputs_in_different_workspaces_have_same_catalog(tmp_path: Path) -> None:
    source = tmp_path / "shared.pdf"
    make_pdf(source, 2)
    catalogs = []
    for name in ("one", "two"):
        workspace = tmp_path / name
        run = PdfLayoutScanPipeline().run(
            source, workspace, RichFixtureScanner(), IDENTITY, SCANNER_FP, PdfRenderConfig(dpi=72)
        )
        catalogs.append(PdfLayoutCatalogBuilder().build(run).model_dump_json())
    assert catalogs[0] == catalogs[1]


def test_partial_range_reports_partial_coverage(tmp_path: Path) -> None:
    _, catalog, _ = scan_and_catalog(tmp_path, pages=12, page_range=range(9, 12))
    assert catalog.readiness.status is PdfCatalogReadiness.PARTIAL
    assert catalog.readiness.coverage.pages_total == 12
    assert catalog.readiness.coverage.pages_scanned == 3
    assert catalog.readiness.coverage.page_pairs_total == 11
    assert catalog.readiness.coverage.page_pairs_scanned == 2
    assert len(catalog.pages) == 12


def test_empty_and_unknown_results_are_valid_not_failures(tmp_path: Path) -> None:
    scanner = RichFixtureScanner(empty_page=1)
    _, catalog, _ = scan_and_catalog(tmp_path, scanner=scanner)
    assert catalog.readiness.status is PdfCatalogReadiness.READY
    assert catalog.readiness.coverage.empty_results == 1
    assert catalog.readiness.coverage.failed_work_units == 0
    _, unknown_catalog, _ = scan_and_catalog(
        tmp_path / "unknown", scanner=UnknownFixtureScanner()
    )
    assert unknown_catalog.readiness.coverage.unknown_observations == 1
    assert unknown_catalog.readiness.status is PdfCatalogReadiness.READY


def test_image_without_caption_is_valid_and_failure_is_reported_separately(
    tmp_path: Path,
) -> None:
    _, image_catalog, _ = scan_and_catalog(
        tmp_path / "image-only", scanner=ImageWithoutCaptionScanner()
    )
    assert len(image_catalog.image_regions) == 1
    assert all(
        marker.observation is not PdfVisualMarkerType.CAPTION_REGION_CANDIDATE
        for marker in image_catalog.observations
    )
    _, failed_catalog, _ = scan_and_catalog(
        tmp_path / "failed", pages=2, scanner=FailingFixtureScanner()
    )
    assert failed_catalog.readiness.status is PdfCatalogReadiness.PARTIAL
    assert failed_catalog.readiness.coverage.failed_work_units == 2


def test_invalid_caption_reference_and_wrong_boundary_are_rejected(tmp_path: Path) -> None:
    run, _, _ = scan_and_catalog(tmp_path, pages=2)
    page_result = run.results[0]
    caption = next(
        marker
        for marker in page_result.markers
        if isinstance(marker, PdfVisualObservation)
        and marker.observation is PdfVisualMarkerType.CAPTION_REGION_CANDIDATE
    )
    invalid_caption = caption.model_copy(
        update={"image_region_ids": ("pdfi_000000000000_p0001_i9999",)}
    )
    invalid_page = page_result.model_copy(
        update={
            "markers": tuple(
                invalid_caption if marker == caption else marker
                for marker in page_result.markers
            )
        }
    )
    invalid_run = run.model_copy(update={"results": (invalid_page, *run.results[1:])})
    with pytest.raises(PdfScannerOutputError):
        PdfLayoutCatalogBuilder().build(invalid_run)

    pair = run.results[-1]
    continuation = next(
        marker
        for marker in pair.markers
        if isinstance(marker, PdfVisualObservation)
    )
    wrong = continuation.model_copy(update={"physical_boundary_id": None})
    invalid_pair = pair.model_copy(
        update={
            "markers": tuple(wrong if marker == continuation else marker for marker in pair.markers)
        }
    )
    wrong_run = run.model_copy(update={"results": (*run.results[:-1], invalid_pair)})
    with pytest.raises(PdfMarkerReferenceError):
        PdfLayoutCatalogBuilder().build(wrong_run)


def test_identical_region_is_deduped_but_conflicting_payload_is_rejected(tmp_path: Path) -> None:
    run, catalog, _ = scan_and_catalog(tmp_path, pages=2)
    assert len({line.region_id for line in catalog.line_regions}) == len(catalog.line_regions)
    pair = run.results[-1]
    bad_line = pair.line_regions[0].model_copy(
        update={"bbox": PdfBoundingBox(x0=1, y0=1, x1=50, y1=50)}
    )
    bad_pair = pair.model_copy(update={"line_regions": (bad_line, *pair.line_regions[1:])})
    bad_run = run.model_copy(update={"results": (*run.results[:-1], bad_pair)})
    with pytest.raises(PdfMarkerConflictError):
        PdfLayoutCatalogBuilder().build(bad_run)

    page_marker = run.results[0].markers[0]
    conflicting_marker = pair.markers[0].model_copy(
        update={"marker_id": page_marker.marker_id}
    )
    marker_pair = pair.model_copy(
        update={"markers": (conflicting_marker, *pair.markers[1:])}
    )
    marker_run = run.model_copy(update={"results": (*run.results[:-1], marker_pair)})
    with pytest.raises(PdfMarkerConflictError):
        PdfLayoutCatalogBuilder().build(marker_run)


def test_stale_result_is_rejected_before_cataloging(tmp_path: Path) -> None:
    run, _, _ = scan_and_catalog(tmp_path)
    stale_result = run.results[0].model_copy(
        update={
            "provenance": run.results[0].provenance.model_copy(
                update={"scanner_fingerprint": "f" * 64}
            )
        }
    )
    stale_run = run.model_copy(update={"results": (stale_result,)})
    with pytest.raises(PdfStaleScannerResultError):
        PdfLayoutCatalogBuilder().build(stale_run)


def test_scanner_and_render_changes_change_catalog_not_pdf_identity(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    outputs = []
    for index, (dpi, scanner_fp) in enumerate(((72, SCANNER_FP), (144, SCANNER_FP), (72, "b" * 64))):
        scanner = RichFixtureScanner(scanner_fp=scanner_fp)
        run = PdfLayoutScanPipeline().run(
            source,
            tmp_path / f"workspace-{index}",
            scanner,
            IDENTITY,
            scanner_fp,
            PdfRenderConfig(dpi=dpi),
        )
        outputs.append((run.source.document_id, PdfLayoutCatalogBuilder().build(run)))
    assert len({source_id for source_id, _ in outputs}) == 1
    assert len({catalog.catalog_fingerprint for _, catalog in outputs}) == 3


def test_rebuild_filters_old_results_in_same_workspace(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    make_pdf(source, 1)
    workspace_path = tmp_path / "workspace"
    pipeline = PdfLayoutScanPipeline()
    first_run = pipeline.run(
        source,
        workspace_path,
        RichFixtureScanner(),
        IDENTITY,
        SCANNER_FP,
        PdfRenderConfig(dpi=72),
    )
    first = PdfLayoutCatalogBuilder().build(
        first_run, PdfLayoutWorkspace(workspace_path)
    )
    second_run = pipeline.run(
        source,
        workspace_path,
        RichFixtureScanner(),
        IDENTITY,
        SCANNER_FP,
        PdfRenderConfig(dpi=144),
    )
    second = PdfLayoutCatalogBuilder().build(
        second_run, PdfLayoutWorkspace(workspace_path)
    )
    assert first.catalog_fingerprint != second.catalog_fingerprint
    assert len(list((workspace_path / "pdf_layout/results").glob("*.json"))) == 2
    assert PdfLayoutCatalogBuilder().rebuild(workspace_path) == second


def test_source_byte_change_changes_catalog_source_identity(tmp_path: Path) -> None:
    _, first, _ = scan_and_catalog(tmp_path / "first", pages=1)
    _, second, _ = scan_and_catalog(tmp_path / "second", pages=2)
    assert first.pdf_document_id != second.pdf_document_id
    assert first.catalog_fingerprint != second.catalog_fingerprint


def test_large_100_page_catalog_is_complete_and_structured_only(tmp_path: Path) -> None:
    _, catalog, workspace = scan_and_catalog(tmp_path, pages=100)
    coverage = catalog.readiness.coverage
    assert catalog.readiness.status is PdfCatalogReadiness.READY
    assert coverage.pages_scanned == 100
    assert coverage.page_pairs_scanned == 99
    assert len(catalog.result_fingerprints) == 199
    assert len(list((workspace / "pdf_layout/renders").glob("*.png"))) == 100
