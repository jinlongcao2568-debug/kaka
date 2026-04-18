# Stage: api_stage4
# Consumes formal objects: public_attack_surface, focus_bidder_verification_profile, pseudo_competitor_signal_set, evidence_grade_profile
# Dependent handoff: H-03-STAGE3-TO-STAGE4, H-04-STAGE4-TO-STAGE5
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE4_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(4),
    "route_registrar": "register_stage4_routes",
}


def register_stage4_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE4_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE4_TRANSPORT_UNAVAILABLE", "register_stage4_routes"]
