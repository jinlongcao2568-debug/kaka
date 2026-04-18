from __future__ import annotations

from storage.repositories._base import ContractRepository


class TouchRecordRepository(ContractRepository):
    object_type = "touch_record"
    id_field = "touch_record_id"


__all__ = ["TouchRecordRepository"]
