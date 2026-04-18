from __future__ import annotations

from storage.repositories._base import ContractRepository


class OpportunityOutcomeEventRepository(ContractRepository):
    object_type = "opportunity_outcome_event"
    id_field = "outcome_event_id"


__all__ = ["OpportunityOutcomeEventRepository"]
