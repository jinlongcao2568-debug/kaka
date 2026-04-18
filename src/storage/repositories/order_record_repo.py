from __future__ import annotations

from storage.repositories._base import ContractRepository


class OrderRecordRepository(ContractRepository):
    object_type = "order_record"
    id_field = "order_id"


__all__ = ["OrderRecordRepository"]
