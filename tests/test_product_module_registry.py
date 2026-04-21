from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def assert_paths_exist(paths: list[str]) -> None:
    for relative_path in paths:
        assert (ROOT / relative_path).exists(), relative_path


def test_product_module_registry_exists_and_is_not_status_source() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    assert registry["registry_id"] == "PRODUCT_MODULE_REGISTRY"
    assert registry["status"] == "ACTIVE"
    assert registry["source_priority"]["product_direction"] == "control/product_task_library.yaml"
    assert registry["source_priority"]["active_execution_source"] == "control/current_task.yaml"
    assert registry["registry_rules"]["not_a_status_source"] is True
    assert registry["registry_rules"]["not_a_release_gate"] is True


def test_product_module_registry_covers_core_stage_modules() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    module_ids = {module["module_id"] for module in registry["modules"]}
    required = {
        "STAGE1-TASKING-AUTHORITY",
        "STAGE2-PUBLIC-CHAIN-INGESTION",
        "STAGE3-PARSED-TRUTH-LAYER",
        "STAGE4-VERIFICATION-ATTACK-SURFACE",
        "STAGE5-RULES-EVIDENCE-DUAL-GATE",
        "STAGE6-FACT-REVIEW-REPORT",
        "STAGE7-SALES-DERIVATION",
        "STAGE8-OUTREACH-GOVERNED",
        "STAGE9-DELIVERY-GOVERNANCE",
        "SURFACE-API-TRANSPORT",
        "SHARED-RUNTIME-POLICY-CHAIN",
        "STORAGE-REPOSITORY-BOUNDARY",
        "INTERNAL-PREVIEW-SURFACE",
    }
    assert required.issubset(module_ids)


def test_product_module_registry_current_files_exist_and_stage7_split_is_recorded() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    modules = {module["module_id"]: module for module in registry["modules"]}

    for module in modules.values():
        assert_paths_exist(module["current_files"])

    stage7 = modules["STAGE7-SALES-DERIVATION"]
    assert stage7["deferred_module_split"] is True
    assert "PTL-S7-price-competitor-offer-resolution" in stage7["pending_packets"]
    assert stage7["current_runtime_state"] == "HEAVY_RUNTIME"
    for relative_path in stage7["proposed_future_files"]:
        assert not (ROOT / relative_path).exists(), relative_path

    stage8 = modules["STAGE8-OUTREACH-GOVERNED"]
    stage9 = modules["STAGE9-DELIVERY-GOVERNANCE"]
    assert stage8["external_release_allowed"] is False
    assert stage8["live_execution_allowed"] is False
    assert stage9["external_release_allowed"] is False
    assert stage9["live_execution_allowed"] is False
