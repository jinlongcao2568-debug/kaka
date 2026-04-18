from __future__ import annotations

from storage.repositories._base import ContractRepository


class LegalActionRecommendationRepository(ContractRepository):
    object_type = "legal_action_recommendation"
    id_field = "action_id"


__all__ = ["LegalActionRecommendationRepository"]
