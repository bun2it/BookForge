from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from bookforge.contracts.flow import (
    CaptionAssociation,
    FigurePlacement,
    FlowDecisionReview,
    InclusionDecision,
    LogicalBoundaryDecision,
    LogicalGroup,
    ResolvedContentFlow,
)

from .models import FlowFailureRecord, FlowManifest, FlowWorkUnit, FlowWorkUnitKind


class FlowWorkspaceError(RuntimeError):
    pass


class FlowWorkspace:
    def __init__(self, document_workspace: Path) -> None:
        self.root = document_workspace / "flow"
        self.units_dir = self.root / "units"
        self.decisions_dir = self.root / "decisions"
        self.groups_dir = self.root / "groups"
        self.placements_dir = self.root / "placements"
        self.captions_dir = self.root / "captions"
        self.inclusions_dir = self.root / "inclusions"
        self.reviews_dir = self.root / "reviews"
        self.failures_dir = self.root / "failures"

    def prepare(self) -> None:
        for path in (
            self.root,
            self.units_dir,
            self.decisions_dir,
            self.groups_dir,
            self.placements_dir,
            self.captions_dir,
            self.inclusions_dir,
            self.reviews_dir,
            self.failures_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def write_unit(self, unit: FlowWorkUnit) -> None:
        self._write_model(self.units_dir / f"{unit.work_unit_id}.json", unit)

    def write_local_decision(self, unit: FlowWorkUnit, decision: BaseModel) -> None:
        self._write_model(self._decision_path(unit), decision)

    def load_local_decision(self, unit: FlowWorkUnit) -> BaseModel | None:
        model_type: type[BaseModel]
        if unit.kind is FlowWorkUnitKind.BOUNDARY:
            model_type = LogicalBoundaryDecision
        elif unit.kind is FlowWorkUnitKind.INCLUSION:
            model_type = InclusionDecision
        elif unit.kind is FlowWorkUnitKind.FIGURE_PLACEMENT:
            model_type = FigurePlacement
        else:
            model_type = CaptionAssociation
        return self._load_model(self._decision_path(unit), model_type)

    def write_groups(self, groups: tuple[LogicalGroup, ...]) -> None:
        existing = {path.name for path in self.groups_dir.glob("*.json")}
        current: set[str] = set()
        for group in groups:
            name = f"{group.group_id}.json"
            current.add(name)
            self._write_model(self.groups_dir / name, group)
        for stale_name in existing - current:
            (self.groups_dir / stale_name).unlink()

    def write_review(self, review: FlowDecisionReview) -> None:
        self._write_model(self.reviews_dir / f"{review.review_id}.json", review)

    def write_failure(self, failure: FlowFailureRecord) -> None:
        self._write_model(self.failures_dir / f"{failure.work_unit_id}.json", failure)

    def clear_failure(self, work_unit_id: str) -> None:
        path = self.failures_dir / f"{work_unit_id}.json"
        if path.exists():
            path.unlink()

    def write_manifest(self, manifest: FlowManifest) -> None:
        self._write_model(self.root / "manifest.json", manifest)

    def write_resolved_flow(self, flow: ResolvedContentFlow) -> None:
        self._write_model(self.root / "resolved_flow.json", flow)

    def _decision_path(self, unit: FlowWorkUnit) -> Path:
        directory = {
            FlowWorkUnitKind.BOUNDARY: self.decisions_dir,
            FlowWorkUnitKind.INCLUSION: self.inclusions_dir,
            FlowWorkUnitKind.FIGURE_PLACEMENT: self.placements_dir,
            FlowWorkUnitKind.CAPTION_ASSOCIATION: self.captions_dir,
        }[unit.kind]
        return directory / f"{unit.work_unit_id}.json"

    @staticmethod
    def _load_model(path: Path, model_type: type[BaseModel]) -> Any | None:
        if not path.exists():
            return None
        try:
            return model_type.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError, ValueError) as error:
            raise FlowWorkspaceError(f"invalid flow workspace file: {path}") from error

    @staticmethod
    def _write_model(path: Path, model: BaseModel) -> None:
        FlowWorkspace._atomic_json(path, model.model_dump(mode="json"))

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
            if temporary_name is not None and Path(temporary_name).exists():
                Path(temporary_name).unlink()
