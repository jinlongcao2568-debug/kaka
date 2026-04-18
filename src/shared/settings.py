# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json


from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Settings:
    repo_root: Optional[str] = None
    environment: Optional[str] = None
    # TODO: extend with contract-driven settings only.
