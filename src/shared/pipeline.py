# Stage: shared
# Consumes formal objects: stage1-9 bundles
# Dependent handoff: stage handoff catalog
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json

from __future__ import annotations

from typing import Any, Dict, Mapping

from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service
from stage8_outreach.service import Stage8Service
from stage9_delivery.service import Stage9Service
from shared.contracts_runtime import ContractStore, StageBundle


def _validate_handoff(store: ContractStore, producer_bundle: StageBundle, consumer_stage: int) -> None:
    result = store.evaluate_handoff_consumer(
        producer_bundle=producer_bundle,
        consumer_stage=consumer_stage,
    )
    if result and result.decision_state == "BLOCK":
        raise ValueError(f"{result.semantic_scope} blocked: {result.reasons}")


def run_internal_chain(payload: Mapping[str, Any], settings: Any | None = None) -> Dict[str, StageBundle]:
    store = ContractStore.default(settings)
    stage1 = Stage1Service(settings).run(payload)
    _validate_handoff(store, stage1, 2)
    stage2 = Stage2Service(settings).run(stage1)
    _validate_handoff(store, stage2, 3)
    stage3 = Stage3Service(settings).run(stage2)
    _validate_handoff(store, stage3, 4)
    stage4 = Stage4Service(settings).run(stage3)
    _validate_handoff(store, stage4, 5)
    stage5 = Stage5Service(settings).run(stage4)
    _validate_handoff(store, stage5, 6)
    stage6 = Stage6Service(settings).run(stage5)
    _validate_handoff(store, stage6, 7)
    stage7 = Stage7Service(settings).run(stage6)
    _validate_handoff(store, stage7, 8)
    stage8 = Stage8Service(settings).run(stage7)
    _validate_handoff(store, stage8, 9)
    stage9 = Stage9Service(settings).run(stage8)

    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4,
        "stage5": stage5,
        "stage6": stage6,
        "stage7": stage7,
        "stage8": stage8,
        "stage9": stage9,
    }


__all__ = ["run_internal_chain"]
