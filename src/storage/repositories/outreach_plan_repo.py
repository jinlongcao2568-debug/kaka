from __future__ import annotations

from storage.repositories._base import ContractRepository


class OutreachPlanRepository(ContractRepository):
    object_type = "outreach_plan"
    id_field = "outreach_plan_id"


__all__ = ["OutreachPlanRepository"]
