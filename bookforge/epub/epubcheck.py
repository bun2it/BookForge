from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from bookforge.contracts.artifact import ImmutableEpubArtifact
from bookforge.contracts.validation import (
    FindingSeverity,
    ValidationFinding,
    ValidationRecord,
    ValidationStatus,
)

EPOCH = datetime(1980, 1, 1, tzinfo=timezone.utc)


class EpubCheckValidator:
    """Optional adapter; never downloads EPUBCheck and never treats absence as PASS."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or shutil.which("epubcheck")

    @property
    def available(self) -> bool:
        return self._executable is not None

    def validate(self, artifact: ImmutableEpubArtifact, path: Path | None = None) -> ValidationRecord:
        epub_path = path or Path(artifact.relative_path)
        if self._executable is None:
            return self._record(
                artifact,
                ValidationStatus.FAIL,
                [
                    ValidationFinding(
                        code="VALIDATOR_UNAVAILABLE",
                        severity=FindingSeverity.ERROR,
                        message="EPUBCheck executable is not available; official validation was not run",
                    )
                ],
            )
        try:
            completed = subprocess.run(
                [self._executable, str(epub_path)],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            return self._record(
                artifact,
                ValidationStatus.FAIL,
                [
                    ValidationFinding(
                        code="VALIDATOR_EXECUTION_FAILED",
                        severity=FindingSeverity.ERROR,
                        message=str(error),
                        affected_reference=str(epub_path),
                    )
                ],
            )
        output = "\n".join(part.strip() for part in (completed.stdout, completed.stderr) if part.strip())
        if completed.returncode != 0:
            status = ValidationStatus.FAIL
            severity = FindingSeverity.ERROR
            code = "EPUBCHECK_FAILED"
        elif "WARNING" in output.upper():
            status = ValidationStatus.PASS_WITH_WARNINGS
            severity = FindingSeverity.WARNING
            code = "EPUBCHECK_WARNING"
        else:
            status = ValidationStatus.PASS
            severity = FindingSeverity.INFO
            code = "EPUBCHECK_PASS"
        findings = [
            ValidationFinding(
                code=code,
                severity=severity,
                message=output or "EPUBCheck completed successfully",
                affected_reference=str(epub_path),
            )
        ]
        return self._record(artifact, status, findings)

    @staticmethod
    def _record(
        artifact: ImmutableEpubArtifact,
        status: ValidationStatus,
        findings: list[ValidationFinding],
    ) -> ValidationRecord:
        return ValidationRecord(
            id=f"epubcheck_{artifact.sha256[:16]}",
            artifact_id=artifact.id,
            validator="EPUBCheck",
            validator_version="external-or-unavailable",
            status=status,
            findings=findings,
            created_at=EPOCH,
        )
