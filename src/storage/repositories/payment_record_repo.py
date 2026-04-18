from __future__ import annotations

from storage.repositories._base import ContractRepository


class PaymentRecordRepository(ContractRepository):
    object_type = "payment_record"
    id_field = "payment_id"


__all__ = ["PaymentRecordRepository"]
