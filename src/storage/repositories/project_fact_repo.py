from __future__ import annotations

from storage.repositories._base import ContractRepository


class ProjectFactRepository(ContractRepository):
    object_type = "project_fact"
    id_field = "project_id"


__all__ = ["ProjectFactRepository"]
