from __future__ import annotations

from storage.repositories._base import ContractRepository


class LegalActionActorProfileRepository(ContractRepository):
    object_type = "legal_action_actor_profile"
    id_field = "actor_id"


__all__ = ["LegalActionActorProfileRepository"]
