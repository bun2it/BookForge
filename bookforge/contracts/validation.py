from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import Field

from .common import ArtifactId, ContractModel, utc_now


class ValidationStatus(StrEnum):
    PASS = "pass"
    PASS_WITH_WARNINGS = "pass_with_warnings"
    FAIL = "fail"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class ValidationFinding(ContractModel):
    code: str
    severity: FindingSeverity
    message: str
    affected_reference: str | None = None
    remediation: str | None = None


class ValidationRecord(ContractModel):
    id: str
    artifact_id: ArtifactId
    validator: str
    validator_version: str
    status: ValidationStatus
    findings: list[ValidationFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
