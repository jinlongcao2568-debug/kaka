from __future__ import annotations

from storage.repositories._base import ContractRepository


class ContactTargetRepository(ContractRepository):
    object_type = "contact_target"
    id_field = "contact_target_id"


__all__ = ["ContactTargetRepository"]
