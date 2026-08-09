from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .common import ContractModel, DocumentId, FrozenContractModel, SourceId, SourceType


class TextJoinBehavior(StrEnum):
    DIRECT = "direct"
    SPACE = "space"
    NEWLINE = "newline"
    REMOVE_TRAILING_HYPHEN = "remove_trailing_hyphen"
    DEFER = "defer"


class SourceTextReference(FrozenContractModel):
    source_id: SourceId
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    join_behavior: TextJoinBehavior = TextJoinBehavior.DEFER

    @model_validator(mode="after")
    def valid_range(self) -> "SourceTextReference":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("both text offsets must be supplied together")
        if self.start_offset is not None and self.end_offset is not None and self.end_offset < self.start_offset:
            raise ValueError("end_offset must not precede start_offset")
        return self


class SourceDocumentReference(ContractModel):
    document_id: DocumentId
    source_type: SourceType
    original_name: str
    content_sha256: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
