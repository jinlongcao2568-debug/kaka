# Stage: stage8_outreach
# Consumes formal objects: contact_target, outreach_plan, touch_record
# Dependent handoff: H-07-STAGE7-TO-STAGE8, H-08-STAGE8-TO-STAGE9
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/sales/contact_policy_catalog.json, contracts/governance/field_policy_dictionary.json, contracts/release/release_gates.json

from dataclasses import dataclass


@dataclass(frozen=True)
class ContactTarget:
    contact_target_id: str
    # TODO: align with contracts/schemas/schema_catalog.json
