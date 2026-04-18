# Stage: stage7_sales
# Consumes formal objects: legal_action_actor_profile, procurement_decision_actor_profile, buyer_fit, challenger_buyer_fit, offer_recommendation, sales_lead, saleable_opportunity
# Dependent handoff: H-06-STAGE6-TO-STAGE7, H-07-STAGE7-TO-STAGE8
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/challenger_profile_catalog.json, contracts/sales/buyer_fit_scorecard.json, contracts/sales/opportunity_policy_catalog.json

from dataclasses import dataclass


@dataclass(frozen=True)
class BuyerFit:
    buyer_fit_id: str
    # TODO: align with contracts/schemas/schema_catalog.json

@dataclass(frozen=True)
class ChallengerBuyerFit:
    challenger_buyer_fit_id: str
    # TODO: align with contracts/schemas/schema_catalog.json
