# Stage: api_stage2
# Consumes formal objects: public_chain, clock_chain_profile, notice_version_chain, fixation_bundle
# Dependent handoff: H-01-STAGE1-TO-STAGE2, H-02-STAGE2-TO-STAGE3
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE2_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(2),
    "route_registrar": "register_stage2_routes",
}


def register_stage2_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE2_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE2_TRANSPORT_UNAVAILABLE", "register_stage2_routes"]
