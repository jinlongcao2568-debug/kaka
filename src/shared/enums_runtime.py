# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

from typing import Iterable, List, Optional

from shared.contracts_runtime import ContractStore


class EnumsRuntime:
    def __init__(self, store: Optional[ContractStore] = None) -> None:
        self.store = store or ContractStore.default()

    def get_values(self, enum_name: str) -> List[str]:
        return self.store.get_enum_values(enum_name)

    def list_enums(self) -> Iterable[str]:
        return sorted(self.store.enum_index.keys())

    def default_value(self, enum_name: str, fallback: str = "") -> str:
        return self.store.get_default_enum_value(enum_name, fallback)


__all__ = ["EnumsRuntime"]
