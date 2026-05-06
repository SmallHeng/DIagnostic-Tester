from __future__ import annotations

from dataclasses import replace

from .model import OdxDatabase


def resolve_inheritance(database: OdxDatabase) -> OdxDatabase:
    """Return a conservative effective view.

    The current model already merges all parsed layers into one database. This
    function keeps that behavior explicit and removes duplicate services while
    preserving child definitions later in the file.
    """
    services = {service.name: service for service in database.services}
    dids = {did.did: did for did in database.dids}
    routines = {routine.routine_id: routine for routine in database.routines}
    dtcs = {dtc.code: dtc for dtc in database.dtcs}
    return replace(
        database,
        services=list(services.values()),
        dids=list(dids.values()),
        routines=list(routines.values()),
        dtcs=list(dtcs.values()),
    )
