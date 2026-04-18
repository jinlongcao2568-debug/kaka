from __future__ import annotations

from storage.repositories._base import ContractRepository


class ProcurementDecisionActorProfileRepository(ContractRepository):
    object_type = "procurement_decision_actor_profile"
    id_field = "actor_id"


__all__ = ["ProcurementDecisionActorProfileRepository"]
