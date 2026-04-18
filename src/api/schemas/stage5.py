# Stage: api_stage5
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json


from typing import TypedDict

class Stage5Request(TypedDict, total=False):
    project_id: str
    rule_gate_status: str

class Stage5Response(TypedDict, total=False):
    status: str
