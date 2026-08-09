from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Any, NewType

from pydantic import BaseModel, ConfigDict, Field, model_validator

SchemaVersion = Annotated[int, Field(ge=1)]
SourceId = NewType("SourceId", str)
DocumentId = NewType("DocumentId", str)
PageId = NewType("PageId", str)
FragmentId = NewType("FragmentId", str)
ArtifactId = NewType("ArtifactId", str)
EditionId = NewType("EditionId", str)
JobId = NewType("JobId", str)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)
    schema_version: SchemaVersion = 1


class FrozenContractModel(ContractModel):
    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)


class SourceType(StrEnum):
    PDF = "pdf"
    DOCX = "docx"


class TransformationStage(StrEnum):
    SOURCE = "source"
    EXTRACTION = "extraction"
    SEMANTIC = "semantic"
    BOUNDARY = "boundary"
    FLOW = "flow"
    ASSEMBLY = "assembly"
    BUILD = "build"
    VALIDATION = "validation"
    DELIVERY = "delivery"


class BoundingBox(ContractModel):
    x0: float
    y0: float
    x1: float
    y1: float

    @model_validator(mode="after")
    def ordered_coordinates(self) -> "BoundingBox":
        if self.x1 < self.x0 or self.y1 < self.y0:
            raise ValueError("bounding box maximums must not be below minimums")
        return self


class ProcessingProvenance(ContractModel):
    document_id: DocumentId
    source_ids: list[SourceId] = Field(default_factory=list)
    stage: TransformationStage
    processor: str
    processor_version: str
    created_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)
