from __future__ import annotations

import pytest
from pydantic import ValidationError

from bookforge.contracts.assembly import (
    AssemblyNotReadyError,
    AssemblyReadinessCode,
    AssemblyReadinessFinding,
    AssemblyReadinessReport,
)


NEW_CODES = (
    AssemblyReadinessCode.INVALID_HIERARCHY,
    AssemblyReadinessCode.DUPLICATE_OWNERSHIP,
    AssemblyReadinessCode.MISSING_OWNERSHIP,
    AssemblyReadinessCode.INCOMPLETE_INCLUSION_DISPOSITION,
    AssemblyReadinessCode.UNRESOLVED_FIGURE_PLACEMENT,
    AssemblyReadinessCode.UNRESOLVED_CAPTION_ASSOCIATION,
    AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE,
)


@pytest.mark.parametrize("code", NEW_CODES)
def test_each_m47_readiness_code_json_round_trips(code: AssemblyReadinessCode) -> None:
    finding = AssemblyReadinessFinding(code=code, reference_id="fixture", blocking=True)
    restored = AssemblyReadinessFinding.model_validate_json(finding.model_dump_json())
    assert restored.code is code


def test_multiple_typed_findings_coexist_in_blocked_report() -> None:
    report = AssemblyReadinessReport(
        ready=False,
        findings=(
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.DUPLICATE_OWNERSHIP,
                reference_id="sem_f000002",
                blocking=True,
            ),
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.UNRESOLVED_FIGURE_PLACEMENT,
                reference_id="sem_f000003",
                blocking=True,
            ),
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE,
                reference_id="flow_chapter_0001",
                blocking=True,
            ),
        ),
    )
    restored = AssemblyReadinessReport.model_validate_json(report.model_dump_json())
    assert tuple(item.code for item in restored.findings) == (
        AssemblyReadinessCode.DUPLICATE_OWNERSHIP,
        AssemblyReadinessCode.UNRESOLVED_FIGURE_PLACEMENT,
        AssemblyReadinessCode.REFERENTIAL_INTEGRITY_FAILURE,
    )
    assert not restored.ready


def test_ready_report_behavior_remains_unchanged() -> None:
    report = AssemblyReadinessReport(ready=True)
    assert report.findings == ()
    assert AssemblyReadinessReport.model_validate_json(report.model_dump_json()) == report


def test_assembly_not_ready_error_preserves_same_typed_report() -> None:
    report = AssemblyReadinessReport(
        ready=False,
        findings=(
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.MISSING_OWNERSHIP,
                reference_id="sem_f000004",
                blocking=True,
            ),
        ),
    )
    error = AssemblyNotReadyError(report)
    assert error.report is report
    assert error.report == report
    assert error.report.findings[0].code is AssemblyReadinessCode.MISSING_OWNERSHIP
    assert str(error) == "assembly input is not ready: missing_ownership"


def test_error_message_is_deterministic_but_report_is_the_api() -> None:
    report = AssemblyReadinessReport(
        ready=False,
        findings=(
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.UNRESOLVED_CAPTION_ASSOCIATION,
                reference_id="sem_f000006",
                blocking=True,
            ),
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.INVALID_HIERARCHY,
                reference_id="flow_part_0001",
                blocking=True,
            ),
        ),
    )
    first = AssemblyNotReadyError(report)
    second = AssemblyNotReadyError(report)
    assert str(first) == str(second)
    assert first.report.findings == report.findings


def test_readiness_finding_still_rejects_unknown_fields_and_enum_values() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        AssemblyReadinessFinding.model_validate(
            {
                "code": AssemblyReadinessCode.INVALID_HIERARCHY,
                "reference_id": "fixture",
                "blocking": True,
                "details": "not a contract field",
            }
        )
    with pytest.raises(ValidationError):
        AssemblyReadinessFinding.model_validate(
            {"code": "unknown_readiness_state", "reference_id": "fixture", "blocking": True}
        )


def test_previous_v3_readiness_code_remains_compatible() -> None:
    previous = AssemblyReadinessReport(
        ready=False,
        findings=(
            AssemblyReadinessFinding(
                code=AssemblyReadinessCode.INVALID_CONTINUITY,
                reference_id="fld_aaaaaaaaaaaaaaaaaaaa",
                blocking=True,
            ),
        ),
    )
    restored = AssemblyReadinessReport.model_validate_json(previous.model_dump_json())
    assert restored == previous
    assert restored.findings[0].code is AssemblyReadinessCode.INVALID_CONTINUITY
