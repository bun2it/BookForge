from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import TypeVar

from bookforge.contracts.pdf_layout import (
    PdfImageRegion,
    PdfLayoutScanResult,
    PdfLineRegion,
    PdfMarkerId,
    PdfPageEvidence,
    PdfPageId,
    PdfPhysicalPageBoundary,
    PdfVisualMarkerType,
    PdfVisualObservation,
    PdfVisualParagraphGroup,
)

from .errors import (
    PdfCatalogError,
    PdfMarkerConflictError,
    PdfMarkerReferenceError,
    PdfStaleScannerResultError,
)
from .models import (
    PdfAlignmentReadinessReport,
    PdfBoundaryObservationIndex,
    PdfCatalogCoverage,
    PdfCatalogFinding,
    PdfCatalogFindingCode,
    PdfCatalogReadiness,
    PdfLayoutManifest,
    PdfLayoutObservationCatalog,
    PdfLayoutRunResult,
    PdfPageObservationIndex,
    PdfScanFailure,
    PdfScanWorkUnit,
    PdfScanWorkUnitKind,
    PdfVisualTopologyEntry,
    PdfVisualTopologyKind,
)
from .rendering import canonical_fingerprint
from .scanner_pipeline import validate_scanner_result
from .workspace import PdfLayoutWorkspace


def _model_fingerprint(model: object) -> str:
    dump = getattr(model, "model_dump")
    return canonical_fingerprint(dump(mode="json"))


CatalogValue = TypeVar("CatalogValue")


def _add_identical_or_conflict(
    catalog: dict[str, CatalogValue], identity: str, value: CatalogValue, kind: str
) -> None:
    previous = catalog.get(identity)
    if previous is None:
        catalog[identity] = value
    elif previous != value:
        raise PdfMarkerConflictError(f"conflicting {kind} payload for ID {identity}")


def _result_by_unit(
    units: Sequence[PdfScanWorkUnit], results: Sequence[PdfLayoutScanResult]
) -> dict[str, PdfLayoutScanResult]:
    unit_by_input = {unit.scan_input.configuration_fingerprint: unit for unit in units}
    if len(unit_by_input) != len(units):
        raise PdfCatalogError("scan work units contain duplicate input fingerprints")
    mapped: dict[str, PdfLayoutScanResult] = {}
    for result in results:
        unit = unit_by_input.get(result.provenance.input_fingerprint)
        if unit is None:
            raise PdfStaleScannerResultError("scanner result has no current work unit")
        if unit.work_unit_id in mapped:
            raise PdfMarkerConflictError(
                f"multiple scanner results exist for work unit {unit.work_unit_id}"
            )
        if (
            result.provenance.input_fingerprint
            != unit.scan_input.configuration_fingerprint
            or result.provenance.scanner_fingerprint != unit.scanner_fingerprint
            or result.provenance.scanner != unit.scanner_identity
        ):
            raise PdfStaleScannerResultError(
                f"scanner result is stale for work unit {unit.work_unit_id}"
            )
        validate_scanner_result(unit, result)
        mapped[unit.work_unit_id] = result
    return mapped


def _validate_observation(
    marker: PdfVisualObservation,
    lines: dict[str, PdfLineRegion],
    images: dict[str, PdfImageRegion],
    boundary_by_id: dict[str, PdfPhysicalPageBoundary],
) -> None:
    line_pages = {lines[str(region_id)].page_id for region_id in marker.line_region_ids if str(region_id) in lines}
    image_pages = {images[str(region_id)].page_id for region_id in marker.image_region_ids if str(region_id) in images}
    missing_lines = [
        str(region_id) for region_id in marker.line_region_ids if str(region_id) not in lines
    ]
    if missing_lines:
        raise PdfMarkerReferenceError(
            f"observation references unknown line regions: {missing_lines}"
        )
    missing_images = [str(region_id) for region_id in marker.image_region_ids if str(region_id) not in images]
    if missing_images:
        raise PdfMarkerReferenceError(f"observation references unknown image regions: {missing_images}")
    referenced_pages = line_pages | image_pages
    if any(page_id not in marker.page_ids for page_id in referenced_pages):
        raise PdfMarkerReferenceError("observation region page is absent from marker page IDs")
    concrete = bool(marker.line_region_ids or marker.image_region_ids or marker.physical_boundary_id)
    if not concrete and marker.observation is not PdfVisualMarkerType.UNKNOWN:
        raise PdfMarkerReferenceError("visual observation is free-floating")
    if marker.physical_boundary_id is not None and str(marker.physical_boundary_id) not in boundary_by_id:
        raise PdfMarkerReferenceError("observation references an unknown physical boundary")
    if marker.observation is PdfVisualMarkerType.CAPTION_REGION_CANDIDATE:
        if not marker.line_region_ids or not marker.image_region_ids:
            raise PdfMarkerReferenceError("caption candidate requires line and image regions")
    if marker.observation is PdfVisualMarkerType.PARAGRAPH_CONTINUATION_CANDIDATE:
        if len(marker.page_ids) == 2:
            if marker.physical_boundary_id is None or not marker.line_region_ids:
                raise PdfMarkerReferenceError(
                    "cross-page continuation requires a boundary and visual lines"
                )
            boundary = boundary_by_id[str(marker.physical_boundary_id)]
            boundary_pages = {boundary.left_page_id, boundary.right_page_id}
            if set(marker.page_ids) != boundary_pages or referenced_pages != boundary_pages:
                raise PdfMarkerReferenceError(
                    "cross-page continuation pages/lines do not match its physical boundary"
                )


def _validate_paragraph_group(
    group: PdfVisualParagraphGroup,
    lines: dict[str, PdfLineRegion],
    boundary_by_id: dict[str, PdfPhysicalPageBoundary],
    page_number_by_id: dict[PdfPageId, int],
) -> set[PdfPageId]:
    missing = [str(region_id) for region_id in group.line_region_ids if str(region_id) not in lines]
    if missing:
        raise PdfMarkerReferenceError(f"paragraph group references unknown lines: {missing}")
    pages = {lines[str(region_id)].page_id for region_id in group.line_region_ids}
    if len(pages) > 2:
        raise PdfMarkerReferenceError("visual paragraph group spans more than one page boundary")
    if len(pages) == 2:
        numbers = sorted(page_number_by_id[page_id] for page_id in pages)
        if numbers[1] != numbers[0] + 1:
            raise PdfMarkerReferenceError("visual paragraph group spans non-adjacent pages")
        matching = {
            boundary_id
            for boundary_id, boundary in boundary_by_id.items()
            if {boundary.left_page_id, boundary.right_page_id} == pages
        }
        if set(map(str, group.continues_across_physical_boundary_ids)) != matching:
            raise PdfMarkerReferenceError(
                "cross-page paragraph group must reference its exact physical boundary"
            )
    elif group.continues_across_physical_boundary_ids:
        raise PdfMarkerReferenceError("same-page paragraph group cannot reference a boundary")
    return pages


class PdfLayoutCatalogBuilder:
    """Build a deterministic derived index without reopening PDF or PNG inputs."""

    def build(
        self,
        run: PdfLayoutRunResult,
        workspace: PdfLayoutWorkspace | None = None,
    ) -> PdfLayoutObservationCatalog:
        pages = (
            workspace.load_pages()
            if workspace is not None
            else tuple(page.evidence for page in run.pages)
        )
        boundaries = workspace.load_boundaries() if workspace is not None else run.boundaries
        return self._build(
            manifest=run.manifest,
            pages=pages,
            boundaries=boundaries,
            units=(*run.page_work_units, *run.page_pair_work_units),
            results=run.results,
            failures=run.failures,
            workspace=workspace,
        )

    def rebuild(self, document_workspace: Path) -> PdfLayoutObservationCatalog:
        workspace = PdfLayoutWorkspace(document_workspace)
        manifest = workspace.load_manifest()
        current_ids = set(manifest.current_work_unit_ids)
        if not current_ids:
            raise PdfCatalogError(
                "manifest predates M6B current-work-unit inventory and cannot be rebuilt safely"
            )
        pages = workspace.load_pages()
        boundaries = workspace.load_boundaries()
        units = workspace.load_units(current_ids)
        results = workspace.load_results(current_ids)
        failures = workspace.load_failures(current_ids)
        return self._build(
            manifest=manifest,
            pages=pages,
            boundaries=boundaries,
            units=units,
            results=results,
            failures=failures,
            workspace=workspace,
        )

    def _build(
        self,
        *,
        manifest: PdfLayoutManifest,
        pages: Sequence[PdfPageEvidence],
        boundaries: Sequence[PdfPhysicalPageBoundary],
        units: Sequence[PdfScanWorkUnit],
        results: Sequence[PdfLayoutScanResult],
        failures: Sequence[PdfScanFailure],
        workspace: PdfLayoutWorkspace | None,
    ) -> PdfLayoutObservationCatalog:
        typed_pages = tuple(pages)
        page_number_by_id = {page.page_id: page.page_number for page in typed_pages}
        boundary_by_id = {str(boundary.boundary_id): boundary for boundary in boundaries}
        mapped = _result_by_unit(units, results)
        line_by_id: dict[str, PdfLineRegion] = {}
        image_by_id: dict[str, PdfImageRegion] = {}
        group_by_id: dict[str, PdfVisualParagraphGroup] = {}
        observation_by_id: dict[str, PdfVisualObservation] = {}
        result_fingerprints: list[str] = []
        provenances = []
        ordered_units = sorted(
            units,
            key=lambda unit: (
                0 if unit.kind is PdfScanWorkUnitKind.PAGE else 1,
                unit.sequence_index,
                unit.work_unit_id,
            ),
        )
        completed_page_ids: set[PdfPageId] = set()
        completed_boundary_ids: set[str] = set()
        empty_results = 0
        for unit in ordered_units:
            result = mapped.get(unit.work_unit_id)
            if result is None:
                continue
            result_fingerprints.append(_model_fingerprint(result))
            provenances.append(result.provenance)
            if unit.kind is PdfScanWorkUnitKind.PAGE:
                completed_page_ids.add(unit.scan_input.pages[0].page_id)
            elif unit.scan_input.physical_boundary is not None:
                completed_boundary_ids.add(str(unit.scan_input.physical_boundary.boundary_id))
            if not result.line_regions and not result.image_regions and not result.markers:
                empty_results += 1
            for line in result.line_regions:
                _add_identical_or_conflict(line_by_id, str(line.region_id), line, "line region")
            for image in result.image_regions:
                _add_identical_or_conflict(image_by_id, str(image.region_id), image, "image region")
            for marker in result.markers:
                if isinstance(marker, PdfVisualParagraphGroup):
                    _add_identical_or_conflict(
                        group_by_id, str(marker.marker_id), marker, "paragraph-group marker"
                    )
                else:
                    _add_identical_or_conflict(
                        observation_by_id, str(marker.marker_id), marker, "observation marker"
                    )
        for identity in set(group_by_id) & set(observation_by_id):
            raise PdfMarkerConflictError(f"marker ID changes type across results: {identity}")

        line_order_by_page: dict[PdfPageId, dict[int, str]] = defaultdict(dict)
        image_order_by_page: dict[PdfPageId, dict[int, str]] = defaultdict(dict)
        combined_order_by_page: dict[PdfPageId, dict[int, str]] = defaultdict(dict)
        for line in line_by_id.values():
            self._record_order(line_order_by_page[line.page_id], line.visual_order, str(line.region_id))
            self._record_order(combined_order_by_page[line.page_id], line.visual_order, str(line.region_id))
        for image in image_by_id.values():
            self._record_order(image_order_by_page[image.page_id], image.visual_order, str(image.region_id))
            self._record_order(combined_order_by_page[image.page_id], image.visual_order, str(image.region_id))

        group_pages: dict[str, set[PdfPageId]] = {}
        for identity, group in group_by_id.items():
            group_pages[identity] = _validate_paragraph_group(
                group, line_by_id, boundary_by_id, page_number_by_id
            )
        for observation in observation_by_id.values():
            _validate_observation(observation, line_by_id, image_by_id, boundary_by_id)

        sorted_lines = tuple(
            sorted(
                line_by_id.values(),
                key=lambda line: (
                    page_number_by_id[line.page_id],
                    line.visual_order,
                    str(line.region_id),
                ),
            )
        )
        sorted_images = tuple(
            sorted(
                image_by_id.values(),
                key=lambda image: (
                    page_number_by_id[image.page_id],
                    image.visual_order,
                    str(image.region_id),
                ),
            )
        )
        sorted_groups = tuple(
            sorted(
                group_by_id.values(),
                key=lambda group: self._group_order(group, line_by_id, page_number_by_id),
            )
        )
        sorted_observations = tuple(
            sorted(
                observation_by_id.values(),
                key=lambda marker: self._observation_order(
                    marker, line_by_id, image_by_id, page_number_by_id
                ),
            )
        )
        page_indexes = tuple(
            PdfPageObservationIndex(
                page=page,
                scan_completed=page.page_id in completed_page_ids,
                line_region_ids=tuple(
                    str(line.region_id) for line in sorted_lines if line.page_id == page.page_id
                ),
                image_region_ids=tuple(
                    str(image.region_id)
                    for image in sorted_images
                    if image.page_id == page.page_id
                ),
                paragraph_group_ids=tuple(
                    group.marker_id
                    for group in sorted_groups
                    if page.page_id in group_pages[str(group.marker_id)]
                ),
                observation_ids=tuple(
                    marker.marker_id
                    for marker in sorted_observations
                    if page.page_id in marker.page_ids
                ),
                visual_topology=tuple(
                    PdfVisualTopologyEntry(
                        kind=PdfVisualTopologyKind.LINE
                        if region_id in line_by_id
                        else PdfVisualTopologyKind.IMAGE,
                        region_id=region_id,
                        visual_order=order,
                    )
                    for order, region_id in sorted(
                        combined_order_by_page[page.page_id].items()
                    )
                ),
            )
            for page in sorted(typed_pages, key=lambda item: item.page_number)
        )
        boundary_indexes = tuple(
            PdfBoundaryObservationIndex(
                boundary=boundary,
                scan_completed=str(boundary.boundary_id) in completed_boundary_ids,
                paragraph_group_ids=tuple(
                    group.marker_id
                    for group in sorted_groups
                    if boundary.boundary_id in group.continues_across_physical_boundary_ids
                ),
                observation_ids=tuple(
                    marker.marker_id
                    for marker in sorted_observations
                    if marker.physical_boundary_id == boundary.boundary_id
                ),
            )
            for boundary in sorted(boundaries, key=lambda item: item.left_page_number)
        )
        coverage = PdfCatalogCoverage(
            pages_total=manifest.total_pages,
            pages_scanned=len(completed_page_ids),
            page_pairs_total=max(manifest.total_pages - 1, 0),
            page_pairs_scanned=len(completed_boundary_ids),
            line_regions=len(sorted_lines),
            image_regions=len(sorted_images),
            paragraph_groups=len(sorted_groups),
            observations=len(sorted_observations),
            unknown_observations=sum(
                marker.observation is PdfVisualMarkerType.UNKNOWN for marker in sorted_observations
            ),
            empty_results=empty_results,
            failed_work_units=len(failures),
        )
        readiness = self._readiness(coverage, failures)
        fingerprint_payload = {
            "pdf_document_id": manifest.source.document_id,
            "source_content_sha256": manifest.source.content_sha256,
            "render_config_fingerprint": manifest.render_config_fingerprint,
            "scanner_identity": manifest.scanner_identity.model_dump(mode="json"),
            "scanner_fingerprint": manifest.scanner_fingerprint,
            "result_fingerprints": result_fingerprints,
            "pages": [index.model_dump(mode="json") for index in page_indexes],
            "boundaries": [index.model_dump(mode="json") for index in boundary_indexes],
            "coverage": coverage.model_dump(mode="json"),
            "readiness": readiness.model_dump(mode="json"),
        }
        catalog = PdfLayoutObservationCatalog(
            catalog_fingerprint=canonical_fingerprint(fingerprint_payload),
            pdf_document_id=manifest.source.document_id,
            source_content_sha256=manifest.source.content_sha256,
            render_config_fingerprint=manifest.render_config_fingerprint,
            scanner_identity=manifest.scanner_identity,
            scanner_fingerprint=manifest.scanner_fingerprint,
            pages=page_indexes,
            boundaries=boundary_indexes,
            line_regions=sorted_lines,
            image_regions=sorted_images,
            paragraph_groups=sorted_groups,
            observations=sorted_observations,
            result_fingerprints=tuple(result_fingerprints),
            scanner_provenance=tuple(provenances),
            readiness=readiness,
        )
        if workspace is not None:
            workspace.write_catalog(catalog)
        return catalog

    @staticmethod
    def _record_order(index: dict[int, str], order: int, identity: str) -> None:
        existing = index.get(order)
        if existing is not None and existing != identity:
            raise PdfMarkerConflictError(
                f"visual order {order} is assigned to both {existing} and {identity}"
            )
        index[order] = identity

    @staticmethod
    def _group_order(
        group: PdfVisualParagraphGroup,
        lines: dict[str, PdfLineRegion],
        page_number_by_id: dict[PdfPageId, int],
    ) -> tuple[int, int, str]:
        members = [lines[str(region_id)] for region_id in group.line_region_ids]
        return (
            min(page_number_by_id[line.page_id] for line in members),
            min(line.visual_order for line in members),
            str(group.marker_id),
        )

    @staticmethod
    def _observation_order(
        marker: PdfVisualObservation,
        lines: dict[str, PdfLineRegion],
        images: dict[str, PdfImageRegion],
        page_number_by_id: dict[PdfPageId, int],
    ) -> tuple[int, int, str]:
        visual_orders = [
            lines[str(region_id)].visual_order
            for region_id in marker.line_region_ids
            if str(region_id) in lines
        ]
        visual_orders.extend(
            images[str(region_id)].visual_order
            for region_id in marker.image_region_ids
            if str(region_id) in images
        )
        return (
            min(page_number_by_id[page_id] for page_id in marker.page_ids),
            min(visual_orders, default=2**31 - 1),
            str(marker.marker_id),
        )

    @staticmethod
    def _readiness(
        coverage: PdfCatalogCoverage, failures: Sequence[PdfScanFailure]
    ) -> PdfAlignmentReadinessReport:
        findings: list[PdfCatalogFinding] = []
        if coverage.pages_scanned < coverage.pages_total:
            findings.append(PdfCatalogFinding(code=PdfCatalogFindingCode.PARTIAL_PAGE_COVERAGE))
        if coverage.page_pairs_scanned < coverage.page_pairs_total:
            findings.append(
                PdfCatalogFinding(code=PdfCatalogFindingCode.PARTIAL_PAGE_PAIR_COVERAGE)
            )
        if failures:
            findings.append(
                PdfCatalogFinding(
                    code=PdfCatalogFindingCode.SCANNER_WORK_FAILURE,
                    work_unit_ids=tuple(sorted(failure.work_unit_id for failure in failures)),
                )
            )
        accepted_units = coverage.pages_scanned + coverage.page_pairs_scanned
        if accepted_units == 0:
            findings.append(PdfCatalogFinding(code=PdfCatalogFindingCode.NO_ACCEPTED_RESULTS))
            status = PdfCatalogReadiness.BLOCKED
        elif findings:
            status = PdfCatalogReadiness.PARTIAL
        else:
            status = PdfCatalogReadiness.READY
        return PdfAlignmentReadinessReport(
            status=status, coverage=coverage, findings=tuple(findings)
        )
