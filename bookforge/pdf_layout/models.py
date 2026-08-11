from __future__ import annotations

from enum import StrEnum
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field

from bookforge.contracts.classification import Fingerprint
from bookforge.contracts.common import FrozenContractModel
from bookforge.contracts.pdf_layout import (
    PdfDocumentId,
    PdfImageRegion,
    PdfLayoutScanInput,
    PdfLayoutScanResult,
    PdfLayoutSource,
    PdfLineRegion,
    PdfMarkerId,
    PdfPageEvidence,
    PdfPageId,
    PdfRegionId,
    PdfPhysicalPageBoundary,
    PdfScannerIdentity,
    PdfScannerProvenance,
    PdfVisualObservation,
    PdfVisualParagraphGroup,
)

PDF_LAYOUT_RUNTIME_VERSION = "m6a-v1"
PDF_RENDER_POLICY_VERSION = "pdfium-png-v1"
PDF_WORK_UNIT_POLICY_VERSION = "pdf-layout-work-unit-v1"


class PdfRenderConfig(FrozenContractModel):
    dpi: int = Field(default=144, ge=72, le=300)
    include_annotations: bool = True
    background_rgb: tuple[int, int, int] = (255, 255, 255)
    backend_version: str = Field(default_factory=lambda: version("pypdfium2"))
    policy_version: str = PDF_RENDER_POLICY_VERSION


class PdfRuntimePage(FrozenContractModel):
    evidence: PdfPageEvidence
    page_index: int = Field(ge=0)
    rotation_degrees: Literal[0, 90, 180, 270]


class OpenedPdfLayout(FrozenContractModel):
    source: PdfLayoutSource
    source_path: Path
    pages: tuple[PdfRuntimePage, ...] = Field(min_length=1)
    boundaries: tuple[PdfPhysicalPageBoundary, ...] = ()


class RenderedPdfPage(FrozenContractModel):
    page: PdfRuntimePage
    relative_path: str = Field(pattern=r"^renders/[0-9a-f]{64}\.png$")
    render_fingerprint: Fingerprint
    content_sha256: Fingerprint
    width_pixels: int = Field(gt=0)
    height_pixels: int = Field(gt=0)
    render_config: PdfRenderConfig


class PdfScanWorkUnitKind(StrEnum):
    PAGE = "page"
    PAGE_PAIR = "page_pair"


class PdfScanWorkUnit(FrozenContractModel):
    work_unit_id: str = Field(pattern=r"^pwu_[0-9a-f]{20}$")
    kind: PdfScanWorkUnitKind
    sequence_index: int = Field(ge=0)
    scan_input: PdfLayoutScanInput
    render_fingerprints: tuple[Fingerprint, ...] = Field(min_length=1, max_length=2)
    scanner_identity: PdfScannerIdentity
    scanner_fingerprint: Fingerprint


class PdfScanFailure(FrozenContractModel):
    work_unit_id: str
    category: str
    message: str
    input_fingerprint: Fingerprint
    scanner_fingerprint: Fingerprint


class PdfScanRunStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"


class PdfLayoutManifest(FrozenContractModel):
    source: PdfLayoutSource
    source_path: str
    runtime_version: str = PDF_LAYOUT_RUNTIME_VERSION
    render_config_fingerprint: Fingerprint
    scanner_identity: PdfScannerIdentity
    scanner_fingerprint: Fingerprint
    total_pages: int = Field(ge=1)
    total_boundaries: int = Field(ge=0)
    total_page_units: int = Field(ge=1)
    total_pair_units: int = Field(ge=0)
    current_work_unit_ids: tuple[str, ...] = ()
    completed: int = Field(ge=0)
    failed: int = Field(ge=0)
    reused: int = Field(ge=0)
    stale: int = Field(ge=0)
    status: PdfScanRunStatus


class PdfLayoutRunResult(FrozenContractModel):
    source: PdfLayoutSource
    pages: tuple[PdfRuntimePage, ...]
    boundaries: tuple[PdfPhysicalPageBoundary, ...]
    page_work_units: tuple[PdfScanWorkUnit, ...]
    page_pair_work_units: tuple[PdfScanWorkUnit, ...]
    results: tuple[PdfLayoutScanResult, ...]
    failures: tuple[PdfScanFailure, ...]
    manifest: PdfLayoutManifest


class PdfVisualTopologyKind(StrEnum):
    LINE = "line"
    IMAGE = "image"


class PdfVisualTopologyEntry(FrozenContractModel):
    kind: PdfVisualTopologyKind
    region_id: PdfRegionId
    visual_order: int = Field(ge=1)


class PdfPageObservationIndex(FrozenContractModel):
    page: PdfPageEvidence
    scan_completed: bool
    line_region_ids: tuple[PdfRegionId, ...] = ()
    image_region_ids: tuple[PdfRegionId, ...] = ()
    paragraph_group_ids: tuple[PdfMarkerId, ...] = ()
    observation_ids: tuple[PdfMarkerId, ...] = ()
    visual_topology: tuple[PdfVisualTopologyEntry, ...] = ()


class PdfBoundaryObservationIndex(FrozenContractModel):
    boundary: PdfPhysicalPageBoundary
    scan_completed: bool
    paragraph_group_ids: tuple[PdfMarkerId, ...] = ()
    observation_ids: tuple[PdfMarkerId, ...] = ()


class PdfCatalogReadiness(StrEnum):
    READY = "ready"
    PARTIAL = "partial"
    BLOCKED = "blocked"


class PdfCatalogFindingCode(StrEnum):
    PARTIAL_PAGE_COVERAGE = "partial_page_coverage"
    PARTIAL_PAGE_PAIR_COVERAGE = "partial_page_pair_coverage"
    SCANNER_WORK_FAILURE = "scanner_work_failure"
    NO_ACCEPTED_RESULTS = "no_accepted_results"


class PdfCatalogFinding(FrozenContractModel):
    code: PdfCatalogFindingCode
    work_unit_ids: tuple[str, ...] = ()


class PdfCatalogCoverage(FrozenContractModel):
    pages_total: int = Field(ge=1)
    pages_scanned: int = Field(ge=0)
    page_pairs_total: int = Field(ge=0)
    page_pairs_scanned: int = Field(ge=0)
    line_regions: int = Field(ge=0)
    image_regions: int = Field(ge=0)
    paragraph_groups: int = Field(ge=0)
    observations: int = Field(ge=0)
    unknown_observations: int = Field(ge=0)
    empty_results: int = Field(ge=0)
    failed_work_units: int = Field(ge=0)


class PdfAlignmentReadinessReport(FrozenContractModel):
    status: PdfCatalogReadiness
    coverage: PdfCatalogCoverage
    findings: tuple[PdfCatalogFinding, ...] = ()


class PdfLayoutObservationCatalog(FrozenContractModel):
    catalog_fingerprint: Fingerprint
    pdf_document_id: PdfDocumentId
    source_content_sha256: Fingerprint
    render_config_fingerprint: Fingerprint
    scanner_identity: PdfScannerIdentity
    scanner_fingerprint: Fingerprint
    pages: tuple[PdfPageObservationIndex, ...]
    boundaries: tuple[PdfBoundaryObservationIndex, ...]
    line_regions: tuple[PdfLineRegion, ...] = ()
    image_regions: tuple[PdfImageRegion, ...] = ()
    paragraph_groups: tuple[PdfVisualParagraphGroup, ...] = ()
    observations: tuple[PdfVisualObservation, ...] = ()
    result_fingerprints: tuple[Fingerprint, ...] = ()
    scanner_provenance: tuple[PdfScannerProvenance, ...] = ()
    readiness: PdfAlignmentReadinessReport
