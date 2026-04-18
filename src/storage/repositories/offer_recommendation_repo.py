from __future__ import annotations

from storage.repositories._base import ContractRepository


class OfferRecommendationRepository(ContractRepository):
    object_type = "offer_recommendation"
    id_field = "offer_recommendation_id"


__all__ = ["OfferRecommendationRepository"]
