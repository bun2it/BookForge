from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from bookforge.contracts.pdf_layout import (
    PdfLayoutScanInput,
    PdfLayoutScanner,
    PdfLayoutScanResult,
    PdfImageRegion,
    PdfLineRegion,
    PdfScannerIdentity,
    PdfVisualObservation,
    PdfVisualParagraphGroup,
)

from .errors import PdfScannerOutputError
from .models import (
    OpenedPdfLayout,
    PdfLayoutManifest,
    PdfLayoutRunResult,
    PdfRenderConfig,
    PdfScanFailure,
    PdfScanRunStatus,
    PdfScanWorkUnit,
    PdfScanWorkUnitKind,
    RenderedPdfPage,
)
from .reader import PdfLayoutReader
from .rendering import PdfPageRenderer, canonical_fingerprint, render_config_fingerprint
from .workspace import PdfLayoutWorkspace


def _work_unit(
    kind: PdfScanWorkUnitKind,
    sequence_index: int,
    opened: OpenedPdfLayout,
    renders: Sequence[RenderedPdfPage],
    scanner_identity: PdfScannerIdentity,
    scanner_fingerprint: str,
    boundary_index: int | None = None,
) -> PdfScanWorkUnit:
    boundary = opened.boundaries[boundary_index] if boundary_index is not None else None
    input_fingerprint = canonical_fingerprint(
        {
            "source": opened.source.document_id,
            "pages": [render.page.evidence.page_id for render in renders],
            "renders": [render.render_fingerprint for render in renders],
            "render_content": [render.content_sha256 for render in renders],
            "boundary": boundary.boundary_id if boundary else None,
            "scanner": scanner_fingerprint,
            "policy": "pdf-layout-work-unit-v1",
        }
    )
    scan_input = PdfLayoutScanInput(
        pdf_document_id=opened.source.document_id,
        pages=tuple(render.page.evidence for render in renders),
        physical_boundary=boundary,
        rendered_page_references=tuple(render.relative_path for render in renders),
        configuration_fingerprint=input_fingerprint,
    )
    work_id = "pwu_" + canonical_fingerprint(
        {
            "kind": kind,
            "source": opened.source.document_id,
            "pages": [render.page.evidence.page_id for render in renders],
            "renders": [render.render_fingerprint for render in renders],
            "scanner": scanner_fingerprint,
            "policy": "pdf-layout-work-unit-v1",
        }
    )[:20]
    return PdfScanWorkUnit(
        work_unit_id=work_id,
        kind=kind,
        sequence_index=sequence_index,
        scan_input=scan_input,
        render_fingerprints=tuple(render.render_fingerprint for render in renders),
        scanner_identity=scanner_identity,
        scanner_fingerprint=scanner_fingerprint,
    )


def generate_scan_work_units(
    opened: OpenedPdfLayout,
    renders: Sequence[RenderedPdfPage],
    scanner_identity: PdfScannerIdentity,
    scanner_fingerprint: str,
) -> tuple[tuple[PdfScanWorkUnit, ...], tuple[PdfScanWorkUnit, ...]]:
    pages = tuple(
        _work_unit(PdfScanWorkUnitKind.PAGE, index, opened, (render,), scanner_identity, scanner_fingerprint)
        for index, render in enumerate(renders)
    )
    pairs = tuple(
        _work_unit(
            PdfScanWorkUnitKind.PAGE_PAIR,
            index,
            opened,
            (renders[index], renders[index + 1]),
            scanner_identity,
            scanner_fingerprint,
            boundary_index=index,
        )
        for index in range(max(0, len(renders) - 1))
    )
    return pages, pairs


def validate_scanner_result(unit: PdfScanWorkUnit, result: PdfLayoutScanResult) -> None:
    expected_pages = tuple(page.page_id for page in unit.scan_input.pages)
    if result.pdf_document_id != unit.scan_input.pdf_document_id:
        raise PdfScannerOutputError("scanner result references a different PDF source")
    if result.page_ids != expected_pages:
        raise PdfScannerOutputError("scanner result page IDs do not match work unit")
    if result.provenance.input_fingerprint != unit.scan_input.configuration_fingerprint:
        raise PdfScannerOutputError("scanner result input fingerprint is stale or incorrect")
    if result.provenance.scanner_fingerprint != unit.scanner_fingerprint:
        raise PdfScannerOutputError("scanner result scanner fingerprint is stale or incorrect")
    if result.provenance.scanner != unit.scanner_identity:
        raise PdfScannerOutputError("scanner result identity does not match work unit")
    page_map = {page.page_id: page for page in unit.scan_input.pages}
    region_ids: set[str] = set()

    def validate_region(region: PdfLineRegion | PdfImageRegion) -> None:
        if region.region_id in region_ids:
            raise PdfScannerOutputError("duplicate scanner region ID")
        region_ids.add(str(region.region_id))
        page = page_map.get(region.page_id)
        if page is None:
            raise PdfScannerOutputError("scanner region references a nonexistent work-unit page")
        box = region.bbox
        if box.x0 < 0 or box.y0 < 0 or box.x1 > page.width or box.y1 > page.height:
            raise PdfScannerOutputError("scanner region geometry is outside page bounds")

    for line_region in result.line_regions:
        validate_region(line_region)
    for image_region in result.image_regions:
        validate_region(image_region)
        if any(str(region_id) not in region_ids for region_id in image_region.nearby_line_region_ids):
            raise PdfScannerOutputError("image region references an unknown nearby line region")
    marker_ids: set[str] = set()
    valid_boundaries = {unit.scan_input.physical_boundary.boundary_id} if unit.scan_input.physical_boundary else set()
    for marker in result.markers:
        if marker.marker_id in marker_ids:
            raise PdfScannerOutputError("duplicate scanner marker ID")
        marker_ids.add(marker.marker_id)
        if isinstance(marker, PdfVisualParagraphGroup):
            if any(str(region_id) not in region_ids for region_id in marker.line_region_ids):
                raise PdfScannerOutputError("visual paragraph marker references unknown line region")
            if any(boundary not in valid_boundaries for boundary in marker.continues_across_physical_boundary_ids):
                raise PdfScannerOutputError("visual paragraph marker references an invalid boundary")
        elif isinstance(marker, PdfVisualObservation):
            if any(page_id not in page_map for page_id in marker.page_ids):
                raise PdfScannerOutputError("visual observation references an invalid page")
            referenced_regions = (*marker.line_region_ids, *marker.image_region_ids)
            if any(str(region_id) not in region_ids for region_id in referenced_regions):
                raise PdfScannerOutputError("visual observation references unknown region")
            if marker.physical_boundary_id is not None and marker.physical_boundary_id not in valid_boundaries:
                raise PdfScannerOutputError("visual observation references an invalid boundary")


class PdfLayoutScanPipeline:
    def __init__(self, reader: PdfLayoutReader | None = None, renderer: PdfPageRenderer | None = None) -> None:
        self.reader = reader or PdfLayoutReader()
        self.renderer = renderer or PdfPageRenderer()

    def run(
        self,
        source_path: Path,
        document_workspace: Path,
        scanner: PdfLayoutScanner,
        scanner_identity: PdfScannerIdentity,
        scanner_fingerprint: str,
        render_config: PdfRenderConfig = PdfRenderConfig(),
        page_range: range | None = None,
        continue_on_failure: bool = True,
    ) -> PdfLayoutRunResult:
        opened = self.reader.open(source_path)
        workspace = PdfLayoutWorkspace(document_workspace)
        workspace.prepare()
        workspace.write_source(opened.source, opened.source_path)
        for page in opened.pages:
            workspace.write_page(page.evidence)
        for boundary in opened.boundaries:
            workspace.write_boundary(boundary)
        selected_indexes = tuple(page_range) if page_range is not None else tuple(range(len(opened.pages)))
        if not selected_indexes:
            raise ValueError("page range must select at least one page")
        if any(right != left + 1 for left, right in zip(selected_indexes, selected_indexes[1:])):
            raise ValueError("page range must be contiguous")
        if any(index < 0 or index >= len(opened.pages) for index in selected_indexes):
            raise ValueError("page range is outside the PDF")
        selected_pages = tuple(opened.pages[index] for index in selected_indexes)
        renders: list[RenderedPdfPage] = []
        for page in selected_pages:
            render = self.renderer.render(opened, page, workspace.root, render_config)
            workspace.write_render(render)
            renders.append(render)
        selected_opened = opened.model_copy(
            update={
                "pages": selected_pages,
                "boundaries": tuple(
                    boundary
                    for boundary in opened.boundaries
                    if boundary.left_page_id in {page.evidence.page_id for page in selected_pages}
                    and boundary.right_page_id in {page.evidence.page_id for page in selected_pages}
                ),
            }
        )
        page_units, pair_units = generate_scan_work_units(
            selected_opened, renders, scanner_identity, scanner_fingerprint
        )
        results: list[PdfLayoutScanResult] = []
        failures: list[PdfScanFailure] = []
        reused = stale = 0
        for unit in (*page_units, *pair_units):
            workspace.write_unit(unit)
            cached = workspace.load_result(unit)
            if cached is not None:
                try:
                    validate_scanner_result(unit, cached)
                except PdfScannerOutputError:
                    stale += 1
                else:
                    reused += 1
                    results.append(cached)
                    continue
            try:
                result = scanner.scan(unit.scan_input)
                validate_scanner_result(unit, result)
                workspace.write_result(unit, result)
                workspace.clear_failure(unit.work_unit_id)
                results.append(result)
            except Exception as error:
                failure = PdfScanFailure(
                    work_unit_id=unit.work_unit_id,
                    category="scanner_or_validation_error",
                    message=str(error),
                    input_fingerprint=unit.scan_input.configuration_fingerprint,
                    scanner_fingerprint=scanner_fingerprint,
                )
                workspace.write_failure(failure)
                failures.append(failure)
                if not continue_on_failure:
                    raise
        total = len(page_units) + len(pair_units)
        status = PdfScanRunStatus.COMPLETE
        if failures:
            status = PdfScanRunStatus.FAILED if len(failures) == total else PdfScanRunStatus.PARTIAL
        manifest = PdfLayoutManifest(
            source=opened.source,
            source_path=str(opened.source_path),
            render_config_fingerprint=render_config_fingerprint(render_config),
            scanner_identity=scanner_identity,
            scanner_fingerprint=scanner_fingerprint,
            total_pages=len(opened.pages),
            total_boundaries=len(opened.boundaries),
            total_page_units=len(page_units),
            total_pair_units=len(pair_units),
            current_work_unit_ids=tuple(
                unit.work_unit_id for unit in (*page_units, *pair_units)
            ),
            completed=len(results),
            failed=len(failures),
            reused=reused,
            stale=stale,
            status=status,
        )
        workspace.write_manifest(manifest)
        return PdfLayoutRunResult(
            source=opened.source,
            pages=selected_pages,
            boundaries=selected_opened.boundaries,
            page_work_units=page_units,
            page_pair_work_units=pair_units,
            results=tuple(results),
            failures=tuple(failures),
            manifest=manifest,
        )

    def resume(
        self,
        source_path: Path,
        document_workspace: Path,
        scanner: PdfLayoutScanner,
        scanner_identity: PdfScannerIdentity,
        scanner_fingerprint: str,
        render_config: PdfRenderConfig = PdfRenderConfig(),
        page_range: range | None = None,
        continue_on_failure: bool = True,
    ) -> PdfLayoutRunResult:
        return self.run(
            source_path=source_path,
            document_workspace=document_workspace,
            scanner=scanner,
            scanner_identity=scanner_identity,
            scanner_fingerprint=scanner_fingerprint,
            render_config=render_config,
            page_range=page_range,
            continue_on_failure=continue_on_failure,
        )
