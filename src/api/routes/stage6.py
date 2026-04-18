# Stage: api_stage6
# Consumes formal objects: project_fact, legal_action_recommendation, review_queue_profile, report_record, challenger_candidate_profile
# Dependent handoff: H-05-STAGE5-TO-STAGE6, H-06-STAGE6-TO-STAGE7
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json

from __future__ import annotations

from typing import Any

from api.deps import build_transport_unavailable


STAGE6_TRANSPORT_UNAVAILABLE = {
    **build_transport_unavailable(6),
    "route_registrar": "register_stage6_routes",
}


def register_stage6_routes(router: object | None = None) -> list[dict[str, Any]]:
    return [dict(STAGE6_TRANSPORT_UNAVAILABLE)]


__all__ = ["STAGE6_TRANSPORT_UNAVAILABLE", "register_stage6_routes"]
