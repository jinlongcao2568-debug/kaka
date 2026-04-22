from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def read_yaml(relative_path: str) -> dict:
    return yaml.safe_load((ROOT / relative_path).read_text(encoding="utf-8"))


def assert_paths_exist(paths: list[str]) -> None:
    for relative_path in paths:
        assert (ROOT / relative_path).exists(), relative_path


def collect_declared_paths(node: object, field_names: set[str]) -> set[str]:
    declared: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            if key in field_names and isinstance(value, list):
                declared.update(item for item in value if isinstance(item, str))
            else:
                declared.update(collect_declared_paths(value, field_names))
    elif isinstance(node, list):
        for item in node:
            declared.update(collect_declared_paths(item, field_names))
    return declared


def collect_slice_ids(registry: dict) -> set[str]:
    slice_ids: set[str] = set()
    for stage in registry["stage_module_inventory"]:
        for module_slice in stage["module_slices"]:
            slice_ids.add(module_slice["slice_id"])
    return slice_ids


def test_product_module_registry_exists_and_is_not_status_source() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    assert registry["registry_id"] == "PRODUCT_MODULE_REGISTRY"
    assert registry["status"] == "ACTIVE"
    assert registry["source_priority"]["product_direction"] == "control/product_task_library.yaml"
    assert registry["source_priority"]["active_execution_source"] == "control/current_task.yaml"
    assert set(registry["source_priority"]["authority_docs"]).issuperset(
        {
            "docs/L0.md",
            "docs/D1_研发_Codex执行手册.md",
            "docs/D2_正式对象契约与字段字典.md",
            "docs/D3_正式规则码总表与判定说明书.md",
            "docs/D4_OpenAPI接口契约.md",
            "docs/D5_页面导出与人工复核规范.md",
            "docs/D6_字段策略字典与客户交付字段规范.md",
            "docs/D7_对象级交付矩阵与外发治理规范.md",
            "docs/D8_真实竞争者识别可售对象与销售推进规范.md",
            "docs/D9_联系对象与销售触达规范.md",
            "docs/D10_订单支付交付与治理反馈规范.md",
            "docs/D11_测试验收与金标回归清单.md",
            "docs/D13_公开可查边界能力清单.md",
        }
    )
    assert registry["registry_rules"]["not_a_status_source"] is True
    assert registry["registry_rules"]["not_a_release_gate"] is True
    assert registry["registry_rules"]["not_a_second_product_direction_source"] is True


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


def test_stage_module_inventory_is_expanded_for_stage1_to_stage9() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    stages = {stage["stage_id"]: stage for stage in registry["stage_module_inventory"]}
    assert set(stages) == {
        "stage1_tasking",
        "stage2_ingestion",
        "stage3_parsing",
        "stage4_verification",
        "stage5_rules_evidence",
        "stage6_fact_review",
        "stage7_sales",
        "stage8_outreach",
        "stage9_delivery",
    }

    required_stage_fields = set(registry["ledger_schema"]["required_stage_fields"])
    required_slice_fields = set(registry["ledger_schema"]["required_slice_fields"])
    all_slice_ids = collect_slice_ids(registry)

    for stage in stages.values():
        assert required_stage_fields.issubset(stage), stage["stage_id"]
        assert stage["business_summary"]
        assert stage["exit_criteria"]
        assert stage["module_slices"]
        for module_slice in stage["module_slices"]:
            assert required_slice_fields.issubset(module_slice), module_slice["slice_id"]
            assert module_slice["business_summary"]
            assert module_slice["exit_criteria"]
            for dependency in module_slice["depends_on_slices"]:
                assert dependency in all_slice_ids, dependency


def test_stage_module_inventory_declares_only_existing_current_surfaces() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    path_fields = {
        "current_files",
        "handoff_files",
        "api_surface_files",
        "repository_files",
        "test_files",
    }
    for relative_path in sorted(collect_declared_paths(registry, path_fields)):
        assert (ROOT / relative_path).exists(), relative_path


def test_api_and_repository_surfaces_are_not_lost_from_module_ledger() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    registry_text = (ROOT / "control/product_module_registry.yaml").read_text(encoding="utf-8")

    for path in (ROOT / "src" / "api" / "routes").glob("stage*.py"):
        assert f"src/api/routes/{path.name}" in registry_text
    for path in (ROOT / "src" / "api" / "schemas").glob("stage*.py"):
        assert f"src/api/schemas/{path.name}" in registry_text
    assert "src/api/schemas/common.py" in registry_text

    ignored_repository_files = {"__init__.py", "_base.py"}
    for path in (ROOT / "src" / "storage" / "repositories").glob("*.py"):
        if path.name in ignored_repository_files:
            continue
        assert f"src/storage/repositories/{path.name}" in registry_text


def test_internal_preview_packet_is_not_left_pending_in_registry() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    modules = {module["module_id"]: module for module in registry["modules"]}
    surfaces = {surface["surface_id"]: surface for surface in registry["cross_cutting_surfaces"]}
    packet_id = "PTL-INT-internal-preview-surface-envelope"

    for entry_id, entry in {
        "SURFACE-API-TRANSPORT": modules["SURFACE-API-TRANSPORT"],
        "STORAGE-REPOSITORY-BOUNDARY": modules["STORAGE-REPOSITORY-BOUNDARY"],
        "INTERNAL-PREVIEW-SURFACE": modules["INTERNAL-PREVIEW-SURFACE"],
        "api_transport_and_schema": surfaces["api_transport_and_schema"],
        "repository_boundary": surfaces["repository_boundary"],
    }.items():
        assert packet_id in entry["completed_packets"], entry_id
        assert packet_id not in entry["pending_packets"], entry_id

    assert modules["INTERNAL-PREVIEW-SURFACE"]["external_release_allowed"] is False
    assert modules["INTERNAL-PREVIEW-SURFACE"]["live_execution_allowed"] is False


def test_stage7_deferred_split_and_stage8_stage9_redlines_remain_locked() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    stages = {stage["stage_id"]: stage for stage in registry["stage_module_inventory"]}

    stage7_slices = {
        module_slice["slice_id"]: module_slice
        for module_slice in stages["stage7_sales"]["module_slices"]
    }
    gaps = stage7_slices["stage7.sales_derivation"]["deferred_gaps"]
    gap = next(item for item in gaps if item["gap_id"] == "STAGE7-SALES-RUNTIME-SPLIT")
    assert gap["not_current_blocker"] is True
    for relative_path in gap["future_files"]:
        assert not (ROOT / relative_path).exists(), relative_path

    assert stages["stage8_outreach"]["implementation_state"] == "GOVERNANCE_BLOCKED_LIVE_EXECUTION"
    assert stages["stage9_delivery"]["implementation_state"] == "GOVERNANCE_BLOCKED_LIVE_EXECUTION"
    assert stages["stage8_outreach"]["customer_visibility"] == "INTERNAL_GOVERNED"
    assert stages["stage9_delivery"]["customer_visibility"] == "INTERNAL_GOVERNED"

    modules = {module["module_id"]: module for module in registry["modules"]}
    assert modules["STAGE8-OUTREACH-GOVERNED"]["external_release_allowed"] is False
    assert modules["STAGE8-OUTREACH-GOVERNED"]["live_execution_allowed"] is False
    assert modules["STAGE9-DELIVERY-GOVERNANCE"]["external_release_allowed"] is False
    assert modules["STAGE9-DELIVERY-GOVERNANCE"]["live_execution_allowed"] is False
