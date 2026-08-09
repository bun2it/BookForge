from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import ContractModel, DocumentId, FragmentId, JobId, PageId, utc_now
from .semantic import BookState


class ProcessingStage(StrEnum):
    QUEUED = "queued"
    EXTRACTION = "extraction"
    SEMANTIC_ANALYSIS = "semantic_analysis"
    BOUNDARY_RESOLUTION = "boundary_resolution"
    FLOW_NORMALIZATION = "flow_normalization"
    ASSEMBLY = "assembly"
    BUILD = "build"
    VALIDATION = "validation"
    LIBRARY = "library"
    DELIVERY = "delivery"


class ProcessingStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProcessingProgress(ContractModel):
    current_stage: ProcessingStage
    current_page: int | None = Field(default=None, ge=1)
    total_pages: int | None = Field(default=None, ge=1)
    completed_units: int = Field(default=0, ge=0)
    total_units: int | None = Field(default=None, ge=0)
    elapsed_seconds: float = Field(default=0, ge=0)
    estimated_remaining_seconds: float | None = Field(default=None, ge=0)


class ProcessingJob(ContractModel):
    id: JobId
    document_id: DocumentId
    status: ProcessingStatus = ProcessingStatus.PENDING
    progress: ProcessingProgress
    configuration: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ProcessingCheckpoint(ContractModel):
    job_id: JobId
    document_id: DocumentId
    pipeline_version: str
    completed_page_ids: list[PageId] = Field(default_factory=list)
    latest_book_state: BookState
    page_fragment_references: dict[PageId, str] = Field(default_factory=dict)
    processing_configuration: dict[str, Any] = Field(default_factory=dict)
    saved_at: datetime = Field(default_factory=utc_now)


class EngineEventType(StrEnum):
    JOB_STARTED = "job_started"
    STAGE_CHANGED = "stage_changed"
    PAGE_STARTED = "page_started"
    PAGE_COMPLETED = "page_completed"
    PAGE_FAILED = "page_failed"
    PROGRESS_UPDATED = "progress_updated"
    WARNING = "warning"
    CHECKPOINT_SAVED = "checkpoint_saved"
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"


class EngineEvent(ContractModel):
    event_type: EngineEventType
    job_id: JobId
    timestamp: datetime = Field(default_factory=utc_now)
    stage: ProcessingStage | None = None
    page_id: PageId | None = None
    fragment_id: FragmentId | None = None
    progress: ProcessingProgress | None = None
    message: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
