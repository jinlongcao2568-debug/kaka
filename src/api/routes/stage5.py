# Stage: api_stage5
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE5_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(5),
    "route_registrar": "register_stage5_routes",
}


def register_stage5_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE5_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE5_TRANSPORT_UNAVAILABLE", "register_stage5_routes"]
