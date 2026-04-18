# Stage: api_stage3
# Consumes formal objects: project_base, field_lineage_record, bidder_candidate, project_manager
# Dependent handoff: H-02-STAGE2-TO-STAGE3, H-03-STAGE3-TO-STAGE4
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE3_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(3),
    "route_registrar": "register_stage3_routes",
}


def register_stage3_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE3_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE3_TRANSPORT_UNAVAILABLE", "register_stage3_routes"]
