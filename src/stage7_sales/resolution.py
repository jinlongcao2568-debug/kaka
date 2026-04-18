# Stage: stage7_sales
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: contracts/sales/stage7_resolution_policy.json, contracts/sales/price_normalization_catalog.json

from __future__ import annotations

from typing import Any, Mapping

from shared.contract_loader import load_contract


def _resolution_contract(settings: Any | None = None) -> dict[str, Any]:
    return load_contract("contracts/sales/stage7_resolution_policy.json", settings)


def resolve_actor_seed(
    *,
    settings: Any | None,
    policy_id: str,
    stage6_handoff: Mapping[str, Any],
    inputs: Mapping[str, Any],
    project_id: str,
    challenger_bidder_id: str,
) -> dict[str, str]:
    contract = _resolution_contract(settings)
    policy = next(entry for entry in contract["actorSeedPolicies"] if entry["policyId"] == policy_id)
    for step in policy["resolutionOrder"]:
        source = step["source"]
        provenance = step["provenance"]
        value: str | None = None
        if source == "stage6_handoff.legal_action_actor_org_name_seed":
            value = stage6_handoff.get("legal_action_actor_org_name_seed")
        elif source == "stage6_handoff.procurement_decision_actor_org_name_seed":
            value = stage6_handoff.get("procurement_decision_actor_org_name_seed")
        elif source == "inputs.legal_action_actor_org_name_seed":
            value = inputs.get("legal_action_actor_org_name_seed")
        elif source == "inputs.legal_action_actor_org_name":
            value = inputs.get("legal_action_actor_org_name")
        elif source == "inputs.procurement_decision_actor_org_name_seed":
            value = inputs.get("procurement_decision_actor_org_name_seed")
        elif source == "inputs.procurement_actor_org_name":
            value = inputs.get("procurement_actor_org_name")
        elif source == "challenger_bidder_id":
            value = challenger_bidder_id
        elif source == "project_id_template":
            value = f"PROCUREMENT_DECISION::{project_id}"
        if value not in (None, ""):
            return {"value": str(value), "source": provenance}
    raise ValueError(f"unable to resolve actor seed for policy {policy_id}")


__all__ = ["resolve_actor_seed"]
