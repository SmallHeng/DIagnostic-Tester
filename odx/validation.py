from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .model import OdxDatabase


Severity = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class OdxValidationIssue:
    severity: Severity
    code: str
    message: str
    subject: str = ""


def validate_database(database: OdxDatabase) -> list[OdxValidationIssue]:
    issues: list[OdxValidationIssue] = []
    issues.extend(validate_references(database))
    issues.extend(validate_duplicates(database))
    issues.extend(validate_services(database))
    return issues


def validate_references(database: OdxDatabase) -> list[OdxValidationIssue]:
    issues: list[OdxValidationIssue] = []
    for did in database.dids:
        if did.dop_ref and did.dop_ref not in database.dops and did.dop_ref not in database.structures:
            issues.append(
                OdxValidationIssue(
                    severity="error",
                    code="missing-dop-ref",
                    subject=did.did,
                    message=f"DID {did.did} references missing DOP {did.dop_ref}",
                )
            )
    for dop in database.dops.values():
        if dop.compu_method_ref and dop.compu_method_ref not in database.computations:
            issues.append(
                OdxValidationIssue(
                    severity="error",
                    code="missing-compu-method-ref",
                    subject=dop.name,
                    message=f"DOP {dop.name} references missing COMPU-METHOD {dop.compu_method_ref}",
                )
            )
    for structure in database.structures.values():
        for field in structure.fields:
            if field.dop_ref and field.dop_ref not in database.dops and field.dop_ref not in database.structures:
                issues.append(
                    OdxValidationIssue(
                        severity="error",
                        code="missing-structure-field-ref",
                        subject=f"{structure.name}.{field.name}",
                        message=f"Structure field {field.name} in {structure.name} references missing DOP/STRUCTURE {field.dop_ref}",
                    )
                )
    for service in database.services:
        for parameter in service.request_parameters:
            if parameter.dop_ref and parameter.dop_ref not in database.dops and parameter.dop_ref not in database.structures:
                issues.append(
                    OdxValidationIssue(
                        severity="error",
                        code="missing-parameter-dop-ref",
                        subject=f"{service.name}.{parameter.name}",
                        message=f"Request parameter {parameter.name} in service {service.name} references missing DOP {parameter.dop_ref}",
                    )
                )
        if service.positive_response is not None:
            for parameter in service.positive_response.parameters:
                if parameter.dop_ref and parameter.dop_ref not in database.dops and parameter.dop_ref not in database.structures:
                    issues.append(
                        OdxValidationIssue(
                            severity="error",
                            code="missing-parameter-dop-ref",
                            subject=f"{service.name}.{parameter.name}",
                            message=f"Response parameter {parameter.name} in service {service.name} references missing DOP {parameter.dop_ref}",
                        )
                    )
    return issues


def validate_duplicates(database: OdxDatabase) -> list[OdxValidationIssue]:
    issues: list[OdxValidationIssue] = []
    issues.extend(_duplicate_issues("duplicate-did", "DID", [did.did for did in database.dids]))
    issues.extend(_duplicate_issues("duplicate-routine", "Routine", [routine.routine_id for routine in database.routines]))
    issues.extend(_duplicate_issues("duplicate-dtc", "DTC", [dtc.code for dtc in database.dtcs]))
    issues.extend(_duplicate_issues("duplicate-service", "Service", [service.name for service in database.services]))
    return issues


def validate_services(database: OdxDatabase) -> list[OdxValidationIssue]:
    issues: list[OdxValidationIssue] = []
    for service in database.services:
        if not service.request:
            issues.append(
                OdxValidationIssue(
                    severity="warning",
                    code="empty-service-request",
                    subject=service.name,
                    message=f"Service {service.name} has no request bytes",
                )
            )
        if service.request_parameters and not any(parameter.is_input for parameter in service.request_parameters) and not service.request:
            issues.append(
                OdxValidationIssue(
                    severity="info",
                    code="constant-only-service",
                    subject=service.name,
                    message=f"Service {service.name} only contains constant request parameters",
                )
            )
    return issues


def _duplicate_issues(code: str, label: str, values: list[str]) -> list[OdxValidationIssue]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return [
        OdxValidationIssue(
            severity="warning",
            code=code,
            subject=value,
            message=f"{label} {value} is defined more than once",
        )
        for value in sorted(duplicates)
    ]
