from __future__ import annotations

from storage.repositories._base import ContractRepository


class DeliveryRecordRepository(ContractRepository):
    object_type = "delivery_record"
    id_field = "delivery_id"


__all__ = ["DeliveryRecordRepository"]
