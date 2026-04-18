from __future__ import annotations

from storage.repositories._base import ContractRepository


class BuyerFitRepository(ContractRepository):
    object_type = "buyer_fit"
    id_field = "buyer_fit_id"


__all__ = ["BuyerFitRepository"]
