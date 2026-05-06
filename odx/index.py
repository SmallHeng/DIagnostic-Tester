from __future__ import annotations

from dataclasses import dataclass

from .model import OdxComputation, OdxDataObjectProperty, OdxDatabase, OdxDiagService, OdxDid, OdxDtc, OdxRoutine


@dataclass(frozen=True)
class OdxIndex:
    database: OdxDatabase
    dids: dict[str, OdxDid]
    services: dict[str, OdxDiagService]
    routines: dict[str, OdxRoutine]
    dtcs: dict[str, OdxDtc]
    dops: dict[str, OdxDataObjectProperty]
    computations: dict[str, OdxComputation]

    def service_for_request(self, request: bytes) -> OdxDiagService | None:
        return next((service for service in self.database.services if service.request == request), None)

    def services_by_semantic(self, semantic: str) -> list[OdxDiagService]:
        normalized = semantic.upper()
        return [service for service in self.database.services if service.semantic.upper() == normalized]

    def dop_for_did(self, did: str) -> OdxDataObjectProperty | None:
        normalized = did.upper().replace("0X", "")
        did_definition = self.dids.get(normalized)
        if did_definition is None or did_definition.dop_ref is None:
            return None
        return self.dops.get(did_definition.dop_ref)

    def computation_for_dop(self, dop: OdxDataObjectProperty) -> OdxComputation | None:
        if not dop.compu_method_ref:
            return None
        return self.computations.get(dop.compu_method_ref)

    def services_with_input_parameters(self) -> list[OdxDiagService]:
        return [service for service in self.database.services if any(parameter.is_input for parameter in service.request_parameters)]


def build_index(database: OdxDatabase) -> OdxIndex:
    return OdxIndex(
        database=database,
        dids={did.did: did for did in database.dids},
        services={service.name: service for service in database.services},
        routines={routine.routine_id: routine for routine in database.routines},
        dtcs={dtc.code: dtc for dtc in database.dtcs},
        dops=database.dops,
        computations=database.computations,
    )
