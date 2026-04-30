from __future__ import annotations

from pathlib import Path
import unittest

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
            "docs/D12_部署发布与运行治理规范.md",
            "docs/D13_公开可查边界能力清单.md",
            "docs/D14_AI模型治理规范.md",
        }
    )
    assert registry["open_capability_policy_ref"] == "control/product_task_library.yaml#open_capability_policy"
    assert registry["open_capability_policy_id"] == "PTL-I100-OPEN-CAPABILITY-BASELINE"
    assert "automated_refund_execution" in registry["open_capability_policy_summary"]["excluded_capabilities"]
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
        "PLATFORM-LOCAL-STACK-READINESS",
        "INTERNAL-PREVIEW-SURFACE",
    }
    assert required.issubset(module_ids)


def test_product_module_registry_current_files_exist_and_p1_to_p8_runtime_cleanup_is_recorded() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    registry_text = (ROOT / "control/product_module_registry.yaml").read_text(encoding="utf-8")
    modules = {module["module_id"]: module for module in registry["modules"]}

    for module in modules.values():
        assert_paths_exist(module["current_files"])

    stage1 = modules["STAGE1-TASKING-AUTHORITY"]
    stage2 = modules["STAGE2-PUBLIC-CHAIN-INGESTION"]
    stage3 = modules["STAGE3-PARSED-TRUTH-LAYER"]
    stage7 = modules["STAGE7-SALES-DERIVATION"]
    assert stage7["deferred_module_split"] is False
    assert "src/stage1_tasking/contract_runtime.py" in stage1["current_files"]
    assert "src/stage1_tasking/market_scan.py" in stage1["current_files"]
    assert "src/storage/repositories/stage1_market_scan_repo.py" in stage1["current_files"]
    assert "PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion" in stage1["completed_packets"]
    assert stage1["pending_packets"] == []
    assert stage1["current_runtime_state"] == "PARTIAL_RUNTIME"
    assert "contract-runtime first cut completed in local commit 2dbfb12" in " ".join(stage1["notes"])
    assert "tests/test_stage1_market_scan.py" in registry_text
    assert "src/stage2_ingestion/contract_runtime.py" in stage2["current_files"]
    assert "src/stage2_ingestion/public_source_adapters.py" in stage2["current_files"]
    assert "src/stage2_ingestion/source_validation.py" in stage2["current_files"]
    assert "src/stage2_ingestion/real_public_url_fetcher.py" in stage2["current_files"]
    assert "tests/test_stage2_public_source_adapters.py" in registry_text
    stage2_inventory = next(
        stage for stage in registry["stage_module_inventory"]
        if stage["stage_id"] == "stage2_ingestion"
    )
    stage2_slices = {module_slice["slice_id"]: module_slice for module_slice in stage2_inventory["module_slices"]}
    adaptive_slice = stage2_slices["stage2.public_web_adaptive_capture_hardening"]
    assert adaptive_slice["implementation_state"] == "INTERNAL_READY"
    assert "PTL-I100-150-public-web-adaptive-capture-hardening-and-failure-escalation" in adaptive_slice["target_packet_candidates"]
    assert "PTL-I100-151-public-web-captcha-automated-resolution-and-resume" in adaptive_slice["deferred_gaps"]
    challenge_slice = stage2_slices["stage2.public_web_challenge_resume"]
    assert challenge_slice["implementation_state"] == "INTERNAL_READY"
    assert "PTL-I100-151-public-web-captcha-automated-resolution-and-resume" in challenge_slice["target_packet_candidates"]
    assert "tests/test_stage2_public_source_adapters.py" in challenge_slice["test_files"]
    assert "tests/test_real_public_source_field_validation.py" in registry_text
    assert "tests/test_stage2_real_public_url_fetcher.py" in registry_text
    assert "PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion" in stage2["completed_packets"]
    assert stage2["pending_packets"] == []
    assert stage2["current_runtime_state"] == "PARTIAL_RUNTIME"
    assert "contract-runtime first cut completed in local commit 2dbfb12" in " ".join(stage2["notes"])
    assert "sandbox/readback only" in " ".join(stage2["notes"])
    assert "PTL-I100-114D extends the same Stage2 public source adapter seam for Credit China" in " ".join(stage2["notes"])
    assert "PTL-I100-114E extends the same Stage2 public source adapter seam for national enterprise credit publicity system" in " ".join(stage2["notes"])
    assert "PTL-I100-114F extends the same Stage2 public source adapter seam for government procurement public site" in " ".join(stage2["notes"])
    assert "PTL-I100-114G extends the same Stage2 public source adapter seam for tender agency public site" in " ".join(stage2["notes"])
    assert "PTL-I100-114H extends the same Stage2 public source adapter seam for tenderer/procurer/owner public notice pages" in " ".join(stage2["notes"])
    assert "PTL-I100-114I extends the same Stage2 public source adapter seam for industry authority filing pages" in " ".join(stage2["notes"])
    assert "PTL-I100-128 registers src/stage2_ingestion/source_validation.py" in " ".join(stage2["notes"])
    assert "PTL-I100-133A registers src/stage2_ingestion/real_public_url_fetcher.py" in " ".join(stage2["notes"])
    assert "src/stage3_parsing/real_parser.py" in stage3["current_files"]
    assert (ROOT / "src/stage3_parsing/real_parser.py").exists()
    stage4_inventory = next(
        stage for stage in registry["stage_module_inventory"]
        if stage["stage_id"] == "stage4_verification"
    )
    stage4_slices = {module_slice["slice_id"]: module_slice for module_slice in stage4_inventory["module_slices"]}
    strategy_slice = stage4_slices["stage4.evidence_risk_hard_defect_strategy"]
    assert strategy_slice["implementation_state"] == "INTERNAL_READY_CANDIDATE"
    assert "src/stage4_verification/hard_defect_strategy.py" in strategy_slice["current_files"]
    assert "tests/test_stage4_evidence_risk_strategy.py" in strategy_slice["test_files"]
    assert (
        "PTL-I100-146-evidence-risk-and-hard-defect-verification-strategy"
        in strategy_slice["target_packet_candidates"]
    )
    assert "PTL-S7-price-competitor-offer-resolution" in stage7["completed_packets"]
    assert "PTL-S7-module-boundary-refactor" in stage7["completed_packets"]
    assert stage7["pending_packets"] == []
    assert stage7["current_runtime_state"] == "HEAVY_RUNTIME"
    assert "src/stage7_sales/commercial_hook.py" in stage7["current_files"]
    split_files = {
        "src/stage7_sales/runtime.py",
        "src/stage7_sales/scorecard.py",
        "src/stage7_sales/pricing.py",
        "src/stage7_sales/recommendation.py",
    }
    assert split_files.issubset(set(stage7["current_files"]))
    assert set(stage7["completed_split_files"]) == split_files
    assert_paths_exist(sorted(split_files))
    stage7_inventory = next(
        stage for stage in registry["stage_module_inventory"]
        if stage["stage_id"] == "stage7_sales"
    )
    stage7_slices = {module_slice["slice_id"]: module_slice for module_slice in stage7_inventory["module_slices"]}
    commercial_hook_slice = stage7_slices["stage7.commercial_hook_lead"]
    assert commercial_hook_slice["implementation_state"] == "INTERNAL_READY_CANDIDATE"
    assert "src/stage7_sales/commercial_hook.py" in commercial_hook_slice["current_files"]
    assert "tests/test_stage7_commercial_hook_lead.py" in commercial_hook_slice["test_files"]
    assert (
        "PTL-I100-147-commercial-value-buyer-fit-and-hook-lead-engine"
        in commercial_hook_slice["target_packet_candidates"]
    )
    assert "tests/test_stage7_commercial_hook_lead.py" in registry_text

    stage8 = modules["STAGE8-OUTREACH-GOVERNED"]
    stage9 = modules["STAGE9-DELIVERY-GOVERNANCE"]
    assert "PTL-S78-contact-candidate-compliance-preview" in stage8["completed_packets"]
    assert "PTL-S8-101-p1-candidate-compliance-boundary-refactor" in stage8["completed_packets"]
    assert "PTL-S8-102-p2-plan-touch-productization" in stage8["completed_packets"]
    assert stage8["pending_packets"] == []
    assert "src/stage8_outreach/candidate_compliance.py" in stage8["current_files"]
    assert "PTL-S89-outreach-writeback-delivery-governance" in stage9["completed_packets"]
    assert "PTL-S9-101-p5-typed-lifecycle-deepening" in stage9["completed_packets"]
    assert "PTL-S9-102-p6-feedback-writeback-productization" in stage9["completed_packets"]
    assert stage9["pending_packets"] == []
    shared_runtime = modules["SHARED-RUNTIME-POLICY-CHAIN"]
    assert "src/shared/policy_contract_helpers.py" in shared_runtime["current_files"]
    assert "src/shared/runtime_semantic_rules.py" in shared_runtime["current_files"]
    assert "src/shared/model_assist_governance.py" in shared_runtime["current_files"]
    assert shared_runtime["completed_packets"] == ["PTL-INT-101-p3-policy-validator-boundary-split"]
    assert shared_runtime["pending_packets"] == []
    storage_boundary = modules["STORAGE-REPOSITORY-BOUNDARY"]
    assert "src/storage/db.py" in storage_boundary["current_files"]
    assert "src/storage/sqlite_backend.py" in storage_boundary["current_files"]
    assert "src/storage/sqlalchemy_backend.py" in storage_boundary["current_files"]
    assert "src/storage/sqlalchemy_schema.py" in storage_boundary["current_files"]
    assert "src/storage/production_infra_readiness.py" in storage_boundary["current_files"]
    assert "src/storage/object_storage.py" in storage_boundary["current_files"]
    assert "src/storage/backup_restore.py" in storage_boundary["current_files"]
    assert "src/storage/worker_queue.py" in storage_boundary["current_files"]
    assert "src/storage/monitoring_alerting.py" in storage_boundary["current_files"]
    assert "src/storage/production_slo_incident_readiness.py" in storage_boundary["current_files"]
    assert "src/storage/repositories/object_storage_repo.py" in storage_boundary["current_files"]
    assert "src/storage/repositories/backup_restore_repo.py" in storage_boundary["current_files"]
    assert "src/storage/repositories/worker_queue_repo.py" in storage_boundary["current_files"]
    assert "src/storage/repositories/monitoring_alerting_repo.py" in storage_boundary["current_files"]
    assert "src/storage/repositories/production_slo_incident_repo.py" in storage_boundary["current_files"]
    assert "src/storage/repository_bundle_io.py" in storage_boundary["current_files"]
    assert "src/storage/repository_context_projection.py" in storage_boundary["current_files"]
    assert "src/storage/operator_workbench_projection.py" in storage_boundary["current_files"]
    assert "PTL-INT-102-p4-repository-boundary-hardening" in storage_boundary["completed_packets"]
    assert "PTL-INT-104-p8-observability-operator-workbench" in storage_boundary["completed_packets"]
    assert "PTL-I100-112E-backup-restore-rollback-readiness" in storage_boundary["completed_packets"]
    assert "PTL-I100-112F-monitoring-alerting-readiness" in storage_boundary["completed_packets"]
    assert storage_boundary["pending_packets"] == []
    platform_stack = modules["PLATFORM-LOCAL-STACK-READINESS"]
    assert ".dockerignore" in platform_stack["current_files"]
    assert "Dockerfile" in platform_stack["current_files"]
    assert "docker-compose.yml" in platform_stack["current_files"]
    assert "src/storage/backup_restore.py" in platform_stack["current_files"]
    assert "src/storage/monitoring_alerting.py" in platform_stack["current_files"]
    assert "src/storage/production_slo_incident_readiness.py" in platform_stack["current_files"]
    assert "src/storage/repositories/backup_restore_repo.py" in platform_stack["current_files"]
    assert "src/storage/repositories/monitoring_alerting_repo.py" in platform_stack["current_files"]
    assert "src/storage/repositories/production_slo_incident_repo.py" in platform_stack["current_files"]
    assert "backup_restore_readiness" in platform_stack["formal_objects"]
    assert "rollback_readiness" in platform_stack["formal_objects"]
    assert "monitoring_readiness" in platform_stack["formal_objects"]
    assert "alert_rule_catalog" in platform_stack["formal_objects"]
    assert "alert_readiness" in platform_stack["formal_objects"]
    assert "incident_readiness" in platform_stack["formal_objects"]
    assert "PTL-I100-112D-docker-compose-health-readiness" in platform_stack["completed_packets"]
    assert "PTL-I100-112E-backup-restore-rollback-readiness" in platform_stack["completed_packets"]
    assert "PTL-I100-112F-monitoring-alerting-readiness" in platform_stack["completed_packets"]
    assert platform_stack["pending_packets"] == []
    assert platform_stack["external_release_allowed"] is False
    assert platform_stack["live_execution_allowed"] is False
    internal_preview = modules["INTERNAL-PREVIEW-SURFACE"]
    assert "src/api/workbench_observability.py" in internal_preview["current_files"]
    assert "src/api/routes/operator_frontend.py" in internal_preview["current_files"]
    assert "PTL-INT-104-p8-observability-operator-workbench" in internal_preview["completed_packets"]
    assert internal_preview["pending_packets"] == []
    api_transport = modules["SURFACE-API-TRANSPORT"]
    assert "src/api/routes/operator_frontend.py" in api_transport["current_files"]
    assert "src/stage9_delivery/typed_lifecycle.py" in stage9["current_files"]
    assert "src/stage9_delivery/feedback_writeback.py" in stage9["current_files"]
    assert stage9["pending_packets"] == []
    assert stage8["external_release_allowed"] is False
    assert stage8["live_execution_allowed"] is False
    assert stage9["external_release_allowed"] is False
    assert stage9["live_execution_allowed"] is False


def test_post_mainline_selection_block_is_navigation_only_and_references_existing_modules() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    modules = {module["module_id"]: module for module in registry["modules"]}
    selection = registry["post_mainline_selection"]

    assert selection["mainline_state"] == "MAINLINE_CLOSED"
    assert selection["automatic_next_candidate_disabled"] is True
    assert selection["mainline_closeout_ref"] == "PTL-GOV-117-product-mainline-completion-closeout"
    assert selection["selection_state"] == "OPEN_FOR_MANUAL_SELECTION"
    assert selection["recommended_direction_label"] == "Stage9 governed delivery 深化"
    assert selection["recommendation_is_navigation_only"] is True
    assert selection["detailed_execution_ladder_ref"] == "control/product_task_library.yaml#post_mainline_execution_ladder"
    assert selection["detailed_execution_scope"] == "PRODUCT_ONLY"
    assert selection["execution_management_notes"] == [
        "Execution-level management and reporting should use control/product_task_library.yaml#post_mainline_execution_ladder and its P1 -> P8 task_ids.",
        "Direction labels such as Stage8 governed touch 深化 / Stage9 governed delivery 深化 remain navigation-only and must not replace P1-P8 task_ids in execution-level communication.",
    ]

    bridge = selection["detailed_execution_bridge"]
    assert bridge["completed_stage8_task_ids"] == [
        "PTL-S8-101-p1-candidate-compliance-boundary-refactor",
        "PTL-S8-102-p2-plan-touch-productization",
    ]
    assert bridge["stage8_task_ids"] == [
        "PTL-S8-101-p1-candidate-compliance-boundary-refactor",
        "PTL-S8-102-p2-plan-touch-productization",
    ]
    assert bridge["shared_platform_task_ids"] == [
        "PTL-INT-101-p3-policy-validator-boundary-split",
        "PTL-INT-102-p4-repository-boundary-hardening",
    ]
    assert bridge["stage9_task_ids"] == [
        "PTL-S9-101-p5-typed-lifecycle-deepening",
        "PTL-S9-102-p6-feedback-writeback-productization",
    ]
    assert bridge["foundational_followup_task_ids"] == [
        "PTL-INT-103-p7-stage1-to-stage5-contract-runtime-completion",
        "PTL-INT-104-p8-observability-operator-workbench",
    ]
    assert bridge["non_product_followups_outside_pool"] == [
        "PTL-GOV-126-p0-current-governance-closeout",
        "PTL-GOV-127-p0b-ax9s-navigation-sync",
        "PTL-GOV-128-p9-future-unlock-prep-only",
    ]

    candidates = selection["direction_candidates"]
    assert [candidate["direction_label"] for candidate in candidates] == [
        "Stage7 模块边界重构",
        "Internal preview 产品化强化",
        "Stage8 governed touch 深化",
        "Stage9 governed delivery 深化",
    ]

    candidate_by_label = {candidate["direction_label"]: candidate for candidate in candidates}

    for candidate in candidates:
        assert candidate["future_packet_id_suggestion"]
        assert candidate["not_auto_activated"] is True
        assert candidate["rationale"]
        assert candidate["related_modules"]
        for module_id in candidate["related_modules"]:
            assert module_id in modules, module_id

    stage7_direction = candidate_by_label["Stage7 模块边界重构"]
    internal_preview_direction = candidate_by_label["Internal preview 产品化强化"]
    stage8_direction = candidate_by_label["Stage8 governed touch 深化"]
    assert stage7_direction["status"] == "COMPLETED"
    assert stage7_direction["recommended_now"] is False
    assert stage7_direction["completed_ref"] == "PTL-S7-module-boundary-refactor"
    assert internal_preview_direction["status"] == "COMPLETED"
    assert internal_preview_direction["recommended_now"] is False
    assert internal_preview_direction["completed_ref"] == "PTL-INT-internal-preview-productization-strengthening"
    assert stage8_direction["status"] == "COMPLETED"
    assert stage8_direction["recommended_now"] is False
    assert stage8_direction["completed_task_ids"] == [
        "PTL-S8-101-p1-candidate-compliance-boundary-refactor",
        "PTL-S8-102-p2-plan-touch-productization",
    ]
    assert stage8_direction["remaining_task_ids"] == []
    assert stage8_direction["last_completed_commit"] == "9d4662a"
    assert candidate_by_label["Stage9 governed delivery 深化"]["status"] == "COMPLETED"
    assert candidate_by_label["Stage9 governed delivery 深化"]["recommended_now"] is False
    assert candidate_by_label["Stage9 governed delivery 深化"]["completed_task_ids"] == [
        "PTL-S9-101-p5-typed-lifecycle-deepening",
        "PTL-S9-102-p6-feedback-writeback-productization",
    ]
    assert candidate_by_label["Stage9 governed delivery 深化"]["remaining_task_ids"] == []
    assert candidate_by_label["Stage9 governed delivery 深化"]["last_completed_commit"] == "edff5af"


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
    p8_packet_id = "PTL-INT-104-p8-observability-operator-workbench"

    for entry_id, entry in {
        "SURFACE-API-TRANSPORT": modules["SURFACE-API-TRANSPORT"],
        "STORAGE-REPOSITORY-BOUNDARY": modules["STORAGE-REPOSITORY-BOUNDARY"],
        "INTERNAL-PREVIEW-SURFACE": modules["INTERNAL-PREVIEW-SURFACE"],
        "api_transport_and_schema": surfaces["api_transport_and_schema"],
        "repository_boundary": surfaces["repository_boundary"],
    }.items():
        assert packet_id in entry["completed_packets"], entry_id
        assert packet_id not in entry["pending_packets"], entry_id
        assert p8_packet_id in entry["completed_packets"], entry_id
        assert p8_packet_id not in entry["pending_packets"], entry_id

    assert modules["INTERNAL-PREVIEW-SURFACE"]["external_release_allowed"] is False
    assert modules["INTERNAL-PREVIEW-SURFACE"]["live_execution_allowed"] is False


def test_platform_local_stack_files_are_registered_on_deployment_surface_and_module() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    modules = {module["module_id"]: module for module in registry["modules"]}
    surfaces = {surface["surface_id"]: surface for surface in registry["cross_cutting_surfaces"]}
    expected_files = {
        ".dockerignore",
        "Dockerfile",
        "docker-compose.yml",
        "src/shared/settings.py",
        "src/storage/production_infra_readiness.py",
        "src/storage/backup_restore.py",
        "src/storage/monitoring_alerting.py",
        "src/storage/production_slo_incident_readiness.py",
        "src/storage/repositories/backup_restore_repo.py",
        "src/storage/repositories/monitoring_alerting_repo.py",
        "src/storage/repositories/production_slo_incident_repo.py",
        "src/api/deps.py",
        "src/api/main.py",
    }

    deployment_surface = surfaces["platform_deployment_readiness"]
    deployment_module = modules["PLATFORM-LOCAL-STACK-READINESS"]

    assert expected_files.issubset(set(deployment_surface["current_files"]))
    assert expected_files.issubset(set(deployment_module["current_files"]))
    assert "tests/test_product_module_registry.py" in deployment_surface["test_files"]
    assert deployment_surface["completed_packets"] == [
        "PTL-I100-112D-docker-compose-health-readiness",
        "PTL-I100-112E-backup-restore-rollback-readiness",
        "PTL-I100-112F-monitoring-alerting-readiness",
    ]
    assert deployment_module["completed_packets"] == [
        "PTL-I100-112D-docker-compose-health-readiness",
        "PTL-I100-112E-backup-restore-rollback-readiness",
        "PTL-I100-112F-monitoring-alerting-readiness",
    ]
    assert deployment_surface["pending_packets"] == []
    assert deployment_module["pending_packets"] == []
    assert "backup_restore_readiness" in deployment_module["formal_objects"]
    assert "rollback_readiness" in deployment_module["formal_objects"]
    assert "monitoring_readiness" in deployment_module["formal_objects"]
    assert "alert_rule_catalog" in deployment_module["formal_objects"]
    assert "alert_readiness" in deployment_module["formal_objects"]
    assert "incident_readiness" in deployment_module["formal_objects"]
    assert deployment_module["external_release_allowed"] is False
    assert deployment_module["live_execution_allowed"] is False
    assert_paths_exist(sorted(expected_files))


def test_stage7_deferred_split_and_stage8_stage9_controlled_opening_requirements_remain_locked() -> None:
    registry = read_yaml("control/product_module_registry.yaml")
    stages = {stage["stage_id"]: stage for stage in registry["stage_module_inventory"]}

    stage7_slices = {
        module_slice["slice_id"]: module_slice
        for module_slice in stages["stage7_sales"]["module_slices"]
    }
    gaps = stage7_slices["stage7.sales_derivation"]["deferred_gaps"]
    gap = next(item for item in gaps if item["gap_id"] == "STAGE7-SALES-RUNTIME-SPLIT")
    split_files = {
        "src/stage7_sales/runtime.py",
        "src/stage7_sales/scorecard.py",
        "src/stage7_sales/pricing.py",
        "src/stage7_sales/recommendation.py",
    }
    assert gap["status"] == "COMPLETED"
    assert gap["completed_in_packet"] == "PTL-S7-module-boundary-refactor"
    assert gap["not_current_blocker"] is False
    assert set(gap["completed_files"]) == split_files
    assert split_files.issubset(set(stage7_slices["stage7.sales_derivation"]["current_files"]))

    top_level_gap = next(item for item in registry["deferred_module_splits"] if item["gap_id"] == "STAGE7-SALES-RUNTIME-SPLIT")
    assert top_level_gap["status"] == "COMPLETED"
    assert top_level_gap["pending"] is False
    assert top_level_gap["not_current_blocker"] is False
    assert set(top_level_gap["completed_files"]) == split_files

    assert stages["stage8_outreach"]["implementation_state"] == "GOVERNANCE_BLOCKED_LIVE_EXECUTION"
    assert stages["stage9_delivery"]["implementation_state"] == "GOVERNANCE_BLOCKED_LIVE_EXECUTION"
    assert stages["stage8_outreach"]["customer_visibility"] == "INTERNAL_GOVERNED"
    assert stages["stage9_delivery"]["customer_visibility"] == "INTERNAL_GOVERNED"

    modules = {module["module_id"]: module for module in registry["modules"]}
    assert modules["STAGE8-OUTREACH-GOVERNED"]["external_release_allowed"] is False
    assert modules["STAGE8-OUTREACH-GOVERNED"]["live_execution_allowed"] is False
    assert "PTL-S8-101-p1-candidate-compliance-boundary-refactor" in modules["STAGE8-OUTREACH-GOVERNED"]["completed_packets"]
    assert "PTL-S8-102-p2-plan-touch-productization" in modules["STAGE8-OUTREACH-GOVERNED"]["completed_packets"]
    assert modules["STAGE8-OUTREACH-GOVERNED"]["pending_packets"] == []
    assert modules["STAGE9-DELIVERY-GOVERNANCE"]["external_release_allowed"] is False
    assert modules["STAGE9-DELIVERY-GOVERNANCE"]["live_execution_allowed"] is False
    assert "PTL-S9-101-p5-typed-lifecycle-deepening" in modules["STAGE9-DELIVERY-GOVERNANCE"]["completed_packets"]
    assert "PTL-S9-102-p6-feedback-writeback-productization" in modules["STAGE9-DELIVERY-GOVERNANCE"]["completed_packets"]
    assert modules["STAGE9-DELIVERY-GOVERNANCE"]["pending_packets"] == []


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    suite = unittest.TestSuite()
    for test in (
        test_product_module_registry_exists_and_is_not_status_source,
        test_product_module_registry_covers_core_stage_modules,
        test_product_module_registry_current_files_exist_and_p1_to_p8_runtime_cleanup_is_recorded,
        test_post_mainline_selection_block_is_navigation_only_and_references_existing_modules,
        test_stage_module_inventory_is_expanded_for_stage1_to_stage9,
        test_stage_module_inventory_declares_only_existing_current_surfaces,
        test_api_and_repository_surfaces_are_not_lost_from_module_ledger,
        test_internal_preview_packet_is_not_left_pending_in_registry,
        test_platform_local_stack_files_are_registered_on_deployment_surface_and_module,
        test_stage7_deferred_split_and_stage8_stage9_controlled_opening_requirements_remain_locked,
    ):
        suite.addTest(unittest.FunctionTestCase(test))
    return suite
