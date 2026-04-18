from __future__ import annotations

from storage.repositories._base import ContractRepository


class SaleableOpportunityRepository(ContractRepository):
    object_type = "saleable_opportunity"
    id_field = "opportunity_id"


__all__ = ["SaleableOpportunityRepository"]
