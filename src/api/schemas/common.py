# Stage: api
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/api/api_catalog.json


from typing import TypedDict, List

class Meta(TypedDict, total=False):
    trace_id: str
    source_refs: List[str]

class ErrorEnvelope(TypedDict, total=False):
    error_code: str
    message: str
    meta: Meta
