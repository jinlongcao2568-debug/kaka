from __future__ import annotations

from storage.repositories._base import ContractRepository


class GovernanceFeedbackEventRepository(ContractRepository):
    object_type = "governance_feedback_event"
    id_field = "governance_feedback_event_id"


__all__ = ["GovernanceFeedbackEventRepository"]
