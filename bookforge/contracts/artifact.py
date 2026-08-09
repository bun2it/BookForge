from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import Field, StringConstraints

from .common import ArtifactId, FrozenContractModel, utc_now

Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class MetadataSnapshot(FrozenContractModel):
    title: str
    authors: tuple[str, ...] = ()
    language: str
    identifier: str
    cover_reference: str | None = None
    toc_reference: str | None = None


class BuildArtifact(FrozenContractModel):
    id: ArtifactId
    relative_path: str
    size_bytes: int = Field(ge=0)
    sha256: Sha256
    created_at: datetime = Field(default_factory=utc_now)
    book_model_revision: str
    metadata_snapshot: MetadataSnapshot
    validation_record_id: str | None = None


class ImmutableEpubArtifact(BuildArtifact):
    media_type: str = "application/epub+zip"
