# Stage: api_stage3
# Consumes formal objects: project_base, field_lineage_record, bidder_candidate, project_manager
# Dependent handoff: H-02-STAGE2-TO-STAGE3, H-03-STAGE3-TO-STAGE4
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json


from typing import TypedDict

class Stage3Request(TypedDict, total=False):
    project_id: str
    notice_version_id: str

class Stage3Response(TypedDict, total=False):
    status: str
