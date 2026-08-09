from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .artifact import ImmutableEpubArtifact
from .common import ContractModel, DocumentId, EditionId, utc_now
from .delivery import DeliveryRecord
from .validation import ValidationRecord


class EditionState(StrEnum):
    BUILDING = "building"
    BUILT = "built"
    VALIDATED = "validated"
    REVIEW_REQUIRED = "review_required"
    INVALID = "invalid"
    ARCHIVED = "archived"


class LibraryEdition(ContractModel):
    id: EditionId
    book_id: str
    source_document_id: DocumentId
    book_model_revision: str
    state: EditionState
    epub_artifact: ImmutableEpubArtifact | None = None
    validation_records: list[ValidationRecord] = Field(default_factory=list)
    delivery_history: list[DeliveryRecord] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class LibraryBook(ContractModel):
    id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    current_edition_id: EditionId | None = None
    editions: list[LibraryEdition] = Field(default_factory=list)
