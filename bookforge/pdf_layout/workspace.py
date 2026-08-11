from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, ValidationError

from bookforge.contracts.pdf_layout import (
    PdfLayoutScanResult,
    PdfLayoutSource,
    PdfPageEvidence,
    PdfPhysicalPageBoundary,
)

from .errors import PdfLayoutWorkspaceError
from .models import (
    PdfLayoutManifest,
    PdfLayoutObservationCatalog,
    PdfScanFailure,
    PdfScanWorkUnit,
    RenderedPdfPage,
)


class PdfLayoutWorkspace:
    def __init__(self, document_workspace: Path) -> None:
        self.root = document_workspace / "pdf_layout"
        self.pages_dir = self.root / "pages"
        self.boundaries_dir = self.root / "boundaries"
        self.renders_dir = self.root / "renders"
        self.units_dir = self.root / "work_units"
        self.results_dir = self.root / "results"
        self.failures_dir = self.root / "failures"
        self.catalog_dir = self.root / "catalog"

    def prepare(self) -> None:
        for path in (
            self.root,
            self.pages_dir,
            self.boundaries_dir,
            self.renders_dir,
            self.units_dir,
            self.results_dir,
            self.failures_dir,
            self.catalog_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def write_source(self, source: PdfLayoutSource, source_path: Path) -> None:
        self._atomic_json(
            self.root / "source.json",
            {"source": source.model_dump(mode="json"), "source_path": str(source_path)},
        )

    def write_page(self, page: PdfPageEvidence) -> None:
        self._write_model(self.pages_dir / f"{page.page_id}.json", page)

    def write_boundary(self, boundary: PdfPhysicalPageBoundary) -> None:
        self._write_model(self.boundaries_dir / f"{boundary.boundary_id}.json", boundary)

    def write_render(self, render: RenderedPdfPage) -> None:
        self._write_model(self.renders_dir / f"{render.render_fingerprint}.json", render)

    def write_unit(self, unit: PdfScanWorkUnit) -> None:
        self._write_model(self.units_dir / f"{unit.work_unit_id}.json", unit)

    def write_result(self, unit: PdfScanWorkUnit, result: PdfLayoutScanResult) -> None:
        self._write_model(self.results_dir / f"{unit.work_unit_id}.json", result)

    def load_result(self, unit: PdfScanWorkUnit) -> PdfLayoutScanResult | None:
        return self._load_model(self.results_dir / f"{unit.work_unit_id}.json", PdfLayoutScanResult)

    def write_failure(self, failure: PdfScanFailure) -> None:
        self._write_model(self.failures_dir / f"{failure.work_unit_id}.json", failure)

    def clear_failure(self, work_unit_id: str) -> None:
        path = self.failures_dir / f"{work_unit_id}.json"
        if path.exists():
            path.unlink()

    def write_manifest(self, manifest: PdfLayoutManifest) -> None:
        self._write_model(self.root / "manifest.json", manifest)

    def load_manifest(self) -> PdfLayoutManifest:
        value = self._load_model(self.root / "manifest.json", PdfLayoutManifest)
        if value is None:
            raise PdfLayoutWorkspaceError("PDF layout manifest is missing")
        return cast(PdfLayoutManifest, value)

    def load_pages(self) -> tuple[PdfPageEvidence, ...]:
        return tuple(
            sorted(
                self._load_all(self.pages_dir, PdfPageEvidence),
                key=lambda page: page.page_number,
            )
        )

    def load_boundaries(self) -> tuple[PdfPhysicalPageBoundary, ...]:
        return tuple(
            sorted(
                self._load_all(self.boundaries_dir, PdfPhysicalPageBoundary),
                key=lambda boundary: boundary.left_page_number,
            )
        )

    def load_units(self, identities: set[str] | None = None) -> tuple[PdfScanWorkUnit, ...]:
        return tuple(self._load_all(self.units_dir, PdfScanWorkUnit, identities))

    def load_results(self, identities: set[str] | None = None) -> tuple[PdfLayoutScanResult, ...]:
        return tuple(self._load_all(self.results_dir, PdfLayoutScanResult, identities))

    def load_failures(self, identities: set[str] | None = None) -> tuple[PdfScanFailure, ...]:
        return tuple(self._load_all(self.failures_dir, PdfScanFailure, identities))

    def write_catalog(self, catalog: PdfLayoutObservationCatalog) -> None:
        self._write_model(self.catalog_dir / "observations.json", catalog)

    def load_catalog(self) -> PdfLayoutObservationCatalog | None:
        return self._load_model(
            self.catalog_dir / "observations.json", PdfLayoutObservationCatalog
        )

    @classmethod
    def _load_all(
        cls,
        directory: Path,
        model_type: type[BaseModel],
        identities: set[str] | None = None,
    ) -> tuple[Any, ...]:
        values: list[Any] = []
        for path in sorted(directory.glob("*.json")):
            if identities is not None and path.stem not in identities:
                continue
            value = cls._load_model(path, model_type)
            if value is not None:
                values.append(value)
        return tuple(values)

    @staticmethod
    def _load_model(path: Path, model_type: type[BaseModel]) -> Any | None:
        if not path.exists():
            return None
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, ValidationError) as error:
            raise PdfLayoutWorkspaceError(f"invalid PDF layout workspace file: {path}") from error

    @staticmethod
    def _write_model(path: Path, model: BaseModel) -> None:
        PdfLayoutWorkspace._atomic_json(path, model.model_dump(mode="json"))

    @staticmethod
    def _atomic_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, separators=(",", ": ")) + "\n"
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
                temporary_name = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if temporary_name is not None and Path(temporary_name).exists():
                Path(temporary_name).unlink()
