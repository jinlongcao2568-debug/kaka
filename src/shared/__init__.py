# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from shared.contract_loader import load_contract
from shared.contracts_runtime import ContractRecord, ContractStore, StageBundle
from shared.enums_runtime import EnumsRuntime
from shared.utils import (
    apply_rule,
    build_id,
    ensure_enum,
    ensure_list,
    get_flag,
    normalize_payload,
    resolve_bundle,
    utc_now_iso,
)

__all__ = [
    "ContractRecord",
    "ContractStore",
    "StageBundle",
    "EnumsRuntime",
    "apply_rule",
    "build_id",
    "ensure_enum",
    "ensure_list",
    "get_flag",
    "load_contract",
    "normalize_payload",
    "resolve_bundle",
    "utc_now_iso",
]
