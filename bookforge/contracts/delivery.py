from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from .common import ArtifactId, ContractModel, utc_now
from .validation import ValidationFinding, ValidationStatus


class DeliveryStatus(StrEnum):
    NOT_SENT = "not_sent"
    PREFLIGHT_FAILED = "preflight_failed"
    READY = "ready"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class DeliveryProfile(ContractModel):
    id: str
    provider_id: str
    display_name: str
    configuration: dict[str, Any] = Field(default_factory=dict)
    secret_reference: str | None = None


class PreflightReport(ContractModel):
    id: str
    artifact_id: ArtifactId
    provider_id: str
    capability_version: str
    status: ValidationStatus
    findings: list[ValidationFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class DeliveryAttempt(ContractModel):
    id: str
    delivery_record_id: str
    artifact_id: ArtifactId
    provider_id: str
    profile_id: str
    status: DeliveryStatus = DeliveryStatus.NOT_SENT
    preflight_report_id: str | None = None
    provider_request_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class DeliveryRecord(ContractModel):
    id: str
    artifact_id: ArtifactId
    latest_status: DeliveryStatus = DeliveryStatus.NOT_SENT
    attempts: list[DeliveryAttempt] = Field(default_factory=list)
