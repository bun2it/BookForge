from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from bookforge.contracts.classification import ClassificationResult
from bookforge.contracts.semantic import SemanticFragment

from .models import FailureRecord, SemanticManifest, SemanticWorkUnit


class SemanticWorkspaceError(RuntimeError):
    pass


class SemanticWorkspace:
    """Filesystem checkpoint store beneath an immutable extraction workspace."""

    def __init__(self, document_workspace: Path) -> None:
        self.root = document_workspace / "semantic"
        self.units_dir = self.root / "units"
        self.results_dir = self.root / "results"
        self.fragments_dir = self.root / "fragments"
        self.failures_dir = self.root / "failures"

    def prepare(self) -> None:
        for path in (
            self.root,
            self.units_dir,
            self.results_dir,
            self.fragments_dir,
            self.failures_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def write_unit(self, unit: SemanticWorkUnit) -> None:
        self._write_model(self.units_dir / f"{unit.work_unit_id}.json", unit)

    def write_result(self, work_unit_id: str, result: ClassificationResult) -> None:
        self._write_model(self.results_dir / f"{work_unit_id}.json", result)

    def load_result(self, work_unit_id: str) -> ClassificationResult | None:
        return self._load_model(
            self.results_dir / f"{work_unit_id}.json", ClassificationResult
        )

    def write_fragment(self, fragment: SemanticFragment) -> None:
        self._write_model(self.fragments_dir / f"{fragment.id}.json", fragment)

    def load_fragment(self, fragment_id: str) -> SemanticFragment | None:
        return self._load_model(self.fragments_dir / f"{fragment_id}.json", SemanticFragment)

    def write_failure(self, failure: FailureRecord) -> None:
        self._write_model(self.failures_dir / f"{failure.work_unit_id}.json", failure)

    def clear_failure(self, work_unit_id: str) -> None:
        path = self.failures_dir / f"{work_unit_id}.json"
        if path.exists():
            path.unlink()

    def write_manifest(self, manifest: SemanticManifest) -> None:
        self._write_model(self.root / "manifest.json", manifest)

    @staticmethod
    def _load_model(path: Path, model_type: type[BaseModel]) -> Any | None:
        if not path.exists():
            return None
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise SemanticWorkspaceError(f"invalid semantic workspace file: {path}") from error

    @staticmethod
    def _write_model(path: Path, model: BaseModel) -> None:
        payload = model.model_dump(mode="json")
        SemanticWorkspace._atomic_json(path, payload)

    @staticmethod
    def _atomic_json(path: Path, payload: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            separators=(",", ": "),
        ) + "\n"
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, path)
        finally:
            if temporary_name is not None:
                temporary = Path(temporary_name)
                if temporary.exists():
                    temporary.unlink()
