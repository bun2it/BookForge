from __future__ import annotations

from pydantic import Field

from .common import ContractModel, FragmentId, ProcessingProvenance
from .semantic import BoundaryOperation


class FlowEntry(ContractModel):
    fragment_id: FragmentId
    parent_fragment_id: FragmentId | None = None
    depth: int = Field(default=0, ge=0)


class ContentFlow(ContractModel):
    revision: str
    entries: list[FlowEntry]
    applied_boundary_operations: list[BoundaryOperation] = Field(default_factory=list)
    provenance: ProcessingProvenance
