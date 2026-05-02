from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = ROOT / "tests"
for search_path in (SRC, TESTS):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.main import create_app
from api.projections import build_real_sample_autonomous_opportunity_acceptance_surface
from api.routes.operator_customer_access import (
    OPERATOR_CUSTOMER_ACCESS_ROUTES,
    list_operator_region_adapters,
    preview_real_sample_autonomous_opportunity_acceptance,
)
from helpers import load_fixture
from shared.pipeline import run_internal_chain
from stage1_tasking.market_scan import Stage1MarketScanEngine
from stage1_tasking.source_blueprint import Stage1SourceBlueprintOrchestrator
from storage import reset_default_storage


class _FakeNoCandidateDiscoveryService:
    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        return {
            "surface_id": "operator_real_candidate_discovery",
            "discovery_run_id": "REAL-CANDIDATE-DISCOVERY-EMPTY",
            "discovery_state": "NO_CANDIDATES",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "real_market_discovery": False,
            "region_codes": list(payload.get("region_codes", []) or []),
            "project_types": list(payload.get("project_types", []) or []),
            "candidate_count": 0,
            "candidates": [],
            "profile_reports": [
                {
                    "profile_id": "GGZY-DEAL-LIST",
                    "status": "FETCHED",
                    "same_site_detail_link_count": 0,
                    "candidate_count": 0,
                }
            ],
            "repository_backed_readback": True,
        }


class _FakeReviewCandidateDiscoveryService:
    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        return {
            "surface_id": "operator_real_candidate_discovery",
            "discovery_run_id": "REAL-CANDIDATE-DISCOVERY-REVIEW",
            "discovery_state": "COMPLETED",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "real_market_discovery": True,
            "region_codes": list(payload.get("region_codes", []) or []),
            "project_types": list(payload.get("project_types", []) or []),
            "candidate_count": 1,
            "candidates": [
                {
                    "notice_id": "NOTICE-REAL-LIST-001",
                    "project_id": "PROJ-REAL-LIST-001",
                    "project_name": "广东市政道路工程招标公告",
                    "region_code": "CN-GD",
                    "region_name": "广东",
                    "project_type": "municipal",
                    "project_type_label": "市政工程",
                    "notice_stage": "tender_notice",
                    "amount": 12_000_000,
                    "estimated_amount": 12_000_000,
                    "amount_min": 8_000_000,
                    "amount_max": 30_000_000,
                    "candidate_count": 0,
                    "competitor_count": 0,
                    "candidate_company": "",
                    "key_fields_present": ["project_name", "notice_stage"],
                    "source_url": "https://www.ggzy.gov.cn/information/deal/html/a/440000/0101/20260424/real-list-001.html",
                    "source_family": "local_public_resource_trading_center",
                    "source_registry_id": "REAL_PUBLIC_LIST_PAGE_DISCOVERY",
                    "source_profile_id": "GGZY-DEAL-LIST",
                    "source_site_name": "全国公共资源交易平台",
                    "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                    "is_offline_sample_candidate": False,
                    "sellability_evidence_state": "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE",
                    "candidate_key": "real-list-001",
                    "snapshot_id_optional": "SNAP-GGZY-DEAL-LIST",
                    "market_scan_generated_at": now or "2026-05-01T00:00:00+00:00",
                }
            ],
            "profile_reports": [
                {
                    "profile_id": "GGZY-DEAL-LIST",
                    "status": "FETCHED",
                    "same_site_detail_link_count": 1,
                    "candidate_count": 1,
                }
            ],
            "repository_backed_readback": True,
        }


class _FakeAcceptedRealCandidateDiscoveryService:
    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        return {
            "surface_id": "operator_real_candidate_discovery",
            "discovery_run_id": "REAL-CANDIDATE-DISCOVERY-ACCEPTED",
            "discovery_state": "COMPLETED",
            "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
            "real_market_discovery": True,
            "region_codes": list(payload.get("region_codes", []) or []),
            "project_types": list(payload.get("project_types", []) or []),
            "candidate_count": 1,
            "candidates": [
                {
                    "notice_id": "NOTICE-REAL-LIST-READY-001",
                    "project_id": "PROJ-REAL-LIST-READY-001",
                    "project_name": "广东市政道路工程中标候选人公示",
                    "region_code": "CN-GD",
                    "region_name": "广东",
                    "project_type": "municipal",
                    "project_type_label": "市政工程",
                    "notice_stage": "candidate_notice",
                    "amount": 12_000_000,
                    "estimated_amount": 12_000_000,
                    "amount_min": 8_000_000,
                    "amount_max": 30_000_000,
                    "candidate_count": 2,
                    "competitor_count": 2,
                    "candidate_company": "广东测试建设有限公司",
                    "key_fields_present": ["project_name", "notice_stage", "candidate_company"],
                    "objection_deadline_at_optional": "2026-05-08T23:59:59+08:00",
                    "source_url": "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=ready-001",
                    "source_family": "local_public_resource_trading_center",
                    "source_registry_id": "REAL_PUBLIC_LIST_PAGE_DISCOVERY",
                    "source_profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
                    "source_site_name": "广东省公共资源交易平台",
                    "source_candidate_mode": "REAL_PUBLIC_SOURCE_CANDIDATES",
                    "is_offline_sample_candidate": False,
                    "sellability_evidence_state": "REAL_LIST_PAGE_CANDIDATE_NEEDS_DETAIL_CAPTURE",
                    "candidate_key": "real-list-ready-001",
                    "snapshot_id_optional": "SNAP-GD-READY-LIST",
                    "market_scan_generated_at": now or "2026-05-01T00:00:00+00:00",
                }
            ],
            "profile_reports": [
                {
                    "profile_id": "GUANGDONG-YGP-PROVINCE-TRADING-LIST",
                    "status": "FETCHED",
                    "same_site_detail_link_count": 1,
                    "candidate_count": 1,
                }
            ],
            "repository_backed_readback": True,
        }


class _FakeTwoAcceptedRealCandidateDiscoveryService:
    def discover(self, payload: dict, *, now: str | None = None) -> dict:
        base = _FakeAcceptedRealCandidateDiscoveryService().discover(payload, now=now)
        first = dict(base["candidates"][0])
        second = {
            **first,
            "notice_id": "NOTICE-REAL-LIST-READY-002",
            "project_id": "PROJ-REAL-LIST-READY-002",
            "project_name": "广东市政道路工程中标候选人公示二",
            "source_url": "https://ygp.gdzwfw.gov.cn/#/44/new/jygg/v3/A?noticeId=ready-002",
            "candidate_key": "real-list-ready-002",
            "snapshot_id_optional": "SNAP-GD-READY-LIST-002",
        }
        base["candidate_count"] = 2
        base["candidates"] = [first, second]
        base["profile_reports"][0]["same_site_detail_link_count"] = 2
        base["profile_reports"][0]["candidate_count"] = 2
        return base


class _FakeReviewCandidateStage2CaptureService:
    def capture_candidates(
        self,
        candidates: list[dict],
        *,
        now: str | None = None,
        detail_capture_limit: int = 5,
        attachment_capture_limit: int = 2,
    ) -> dict:
        enriched = []
        for candidate in candidates:
            row = dict(candidate)
            row["stage2_detail_capture_state"] = "FETCHED"
            row["stage2_detail_snapshot_id_optional"] = "REAL-DETAIL-GGZY-DEAL-LIST-001"
            row["stage3_detail_parse_state"] = "PARSED_WITH_REVIEW"
            row["stage2_attachment_link_count"] = 0
            row["stage2_attachment_snapshot_count"] = 0
            row["sellability_evidence_state"] = "REAL_DETAIL_SNAPSHOT_PARSED_NEEDS_STAGE4_TO_STAGE9"
            enriched.append(row)
        return {
            "surface_id": "operator_real_candidate_stage2_capture",
            "detail_capture_attempted_count": len(enriched),
            "detail_snapshot_count": len(enriched),
            "stage3_parse_success_count": len(enriched),
            "attachment_link_count": 0,
            "attachment_capture_attempted_count": 0,
            "attachment_snapshot_count": 0,
            "captures": [],
            "enriched_candidates": enriched,
            "repository_backed_readback": True,
        }


class _FakePartialCandidateStage2CaptureService:
    def capture_candidates(
        self,
        candidates: list[dict],
        *,
        now: str | None = None,
        detail_capture_limit: int = 5,
        attachment_capture_limit: int = 2,
    ) -> dict:
        enriched = []
        for index, candidate in enumerate(candidates):
            row = dict(candidate)
            if index == 0:
                row["stage2_detail_capture_state"] = "FETCHED"
                row["stage2_detail_snapshot_id_optional"] = "REAL-DETAIL-GGZY-DEAL-LIST-001"
                row["stage3_detail_parse_state"] = "PARSED_WITH_REVIEW"
            else:
                row["stage2_detail_capture_state"] = "PENDING_TIME_BUDGET"
                row["stage3_detail_parse_state"] = "PENDING_DETAIL_CAPTURE"
            row["stage2_attachment_link_count"] = 0
            row["stage2_attachment_snapshot_count"] = 0
            enriched.append(row)
        return {
            "surface_id": "operator_real_candidate_stage2_capture",
            "detail_capture_attempted_count": 1,
            "detail_snapshot_count": 1,
            "pending_detail_capture_count": max(len(enriched) - 1, 0),
            "stage3_parse_success_count": 1,
            "stage3_parse_failed_count": 0,
            "attachment_link_count": 0,
            "attachment_capture_attempted_count": 0,
            "attachment_snapshot_count": 0,
            "captures": [],
            "enriched_candidates": enriched,
            "repository_backed_readback": True,
        }


def _partial_real_public_stage4_9_readback(*args: object, **kwargs: object) -> dict:
    return {
        "surface_id": "operator_real_public_stage4_9_readback",
        "readback_state": "READBACK_READY",
        "real_public_stage4_9_chain_state": "INTERNAL_READY",
        "real_public_stage1_6_chain_state": "INTERNAL_READY",
        "stage1_6_closed_loop_ready": True,
        "stage4_public_verification_result": "MATCHED",
        "stage4_public_verification_readback_state": "READBACK_READY",
        "stage5_rule_gate_status": "PASS",
        "stage5_evidence_gate_status": "PASS",
        "stage6_real_public_product_package_chain_state": "INTERNAL_READY",
        "stage7_real_public_sales_package_chain_state": "INTERNAL_READY",
        "stage8_real_public_outreach_chain_state": "INTERNAL_READY",
        "stage9_real_public_order_payment_delivery_chain_state": "INTERNAL_READY",
        "formal_real_public_readback_ready": True,
        "real_public_sellable_gate_ready": False,
        "customer_sellable_evidence_ready": False,
        "real_world_hard_defect_gate_state": "PARTIAL_SOURCE_COVERAGE",
        "remaining_real_world_gaps": [
            "missing_stage4_5_source_type:construction_permit",
            "stage4_5_local_housing_contract_completion_pm_change_penalty_adapters_pending",
        ],
        "fail_closed_reasons": [],
    }


class RealSampleAutonomousOpportunityAcceptanceTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_default_storage()

    def _run_real_sample_acceptance_payload(self) -> dict[str, object]:
        real_sample_payload = copy.deepcopy(
            load_fixture("stage1_to_stage5_real_source_vertical_slice_proc_national_html.json")
        )
        real_sample_payload.update(
            {
                "task_id": "TASK-149-REAL-SAMPLE-001",
                "project_id": "PROJ-149-REAL-SAMPLE-001",
                "project_name": "Sichuan public construction real sample",
                "region_code": "CN-SC",
                "project_type": "construction",
                "procurement_regime": "OPEN_TENDER",
                "notice_stage": "candidate_notice",
                "amount": 22800000,
                "candidate_count": 3,
                "candidate_company": "First Rank Construction Co",
                "objection_deadline_at_optional": "2026-05-02T00:00:00+00:00",
                "key_fields_present": [
                    "project_name",
                    "candidate_company",
                    "notice_stage",
                ],
                "source_mode": "OFFLINE_REAL_PUBLIC_SAMPLE",
                "run_mode": "DRY_RUN",
                "automation_level": "AUTONOMOUS",
                "live_execution_enabled": False,
                "real_provider_call_enabled": False,
            }
        )
        market_scan = Stage1MarketScanEngine().run(
            {
                **real_sample_payload,
                "scan_run_id": "MKTSCAN-149-REAL-SAMPLE-001",
                "batch_id": "PTL-I100-ROADMAP-01",
                "minimum_amount": 1000000,
                "analysis_score_threshold": 50,
            }
        )
        source_blueprint = Stage1SourceBlueprintOrchestrator().build(
            {
                "scan_run_id": market_scan["scan_run_id"],
                "source_blueprint_plan_id": "SRCBLUE-149-REAL-SAMPLE-001",
                "coverage_gap_signals": [
                    "province_platform_missing_detail_or_attachment",
                ],
            }
        )
        selected = market_scan["opportunity_candidates"][0]
        chain_payload = {
            **real_sample_payload,
            "announcement_url": selected["source_refs"]["source_url"]
            or real_sample_payload["announcement_url"],
            "source_blueprint_plan_id": source_blueprint["source_blueprint_plan_id"],
            "stage2_capture_plan_id": source_blueprint["stage2_capture_plan"]["capture_plan_id"],
        }
        chain = run_internal_chain(chain_payload)
        return {
            **chain,
            "market_scan": market_scan,
            "source_blueprint_plan": source_blueprint,
        }

    def test_real_sample_acceptance_closes_market_scan_to_hook_and_delivery_candidate(self) -> None:
        payload = self._run_real_sample_acceptance_payload()

        surface = build_real_sample_autonomous_opportunity_acceptance_surface(payload)

        self.assertEqual(
            surface["acceptance_state"],
            "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED",
        )
        self.assertEqual(surface["capability_state"], "PRODUCTION_READY")
        self.assertEqual(surface["fail_closed_reasons"], [])
        flow = surface["real_sample_flow"]
        self.assertTrue(flow["market_scan_observed"])
        self.assertTrue(flow["market_scan_autonomous_decision"])
        self.assertEqual(flow["selected_candidate_count"], 1)
        self.assertTrue(flow["source_blueprint_observed"])
        self.assertTrue(flow["source_blueprint_auto_selection"])
        self.assertTrue(flow["stage2_capture_plan_observed"])
        self.assertGreaterEqual(flow["stage2_capture_step_count"], 6)
        self.assertTrue(flow["stage1_to_stage9_chain_observed"])
        self.assertTrue(flow["commercial_hook_observed"])
        self.assertTrue(flow["leadpack_delivery_candidate_observed"])
        self.assertTrue(flow["operator_workbench_observed"])
        self.assertTrue(flow["controlled_opening_requirements_preserved"])

        owner = surface["owner_workbench_acceptance"]
        self.assertTrue(owner["owner_can_observe_without_raw_json"])
        self.assertTrue(owner["opportunity_queue_visible"])
        self.assertTrue(owner["commercial_hook_review_visible"])
        self.assertTrue(owner["buyer_ranking_visible"])
        self.assertTrue(owner["evidence_risk_visible"])
        self.assertTrue(owner["delivery_state_visible"])
        self.assertTrue(owner["next_action_visible"])
        self.assertFalse(surface["raw_json_required"])
        self.assertFalse(surface["manual_url_picker_primary_flow"])
        self.assertTrue(
            all(ref["observed"] for ref in surface["stage_refs"].values())
        )
        self.assertFalse(
            any(surface["controlled_opening_requirements"].values())
        )

        hook = surface["commercial_hook_acceptance"]
        self.assertEqual(hook["disclosure_level"], "L1_HOOK")
        self.assertTrue(hook["no_full_evidence_leakage"])
        self.assertTrue(hook["forbidden_claims_filter_passed"])
        self.assertIn("source_url", hook["withheld_fields"])

        delivery = surface["delivery_candidate_acceptance"]
        self.assertTrue(delivery["readback_ready"])
        self.assertFalse(delivery["customer_visible_enabled"])
        self.assertFalse(delivery["external_delivery_enabled"])
        self.assertFalse(delivery["customer_download_enabled"])

    def test_operator_route_registers_real_sample_acceptance_without_live_execution(self) -> None:
        routes = {route["operationId"]: route for route in OPERATOR_CUSTOMER_ACCESS_ROUTES}
        route = routes["previewRealSampleAutonomousOpportunityAcceptance"]

        self.assertEqual(route["path"], "/operator-console/real-sample-autonomous-acceptance")
        self.assertTrue(route["real_sample_autonomous_acceptance"])
        self.assertTrue(route["real_sample_flow_visible"])
        self.assertTrue(route["productized_owner_workbench"])
        self.assertFalse(route["raw_json_required"])
        self.assertFalse(route["live_execution_enabled"])
        self.assertFalse(route["external_release_enabled"])
        self.assertFalse(route["real_provider_call_enabled"])

        surface = preview_real_sample_autonomous_opportunity_acceptance(
            self._run_real_sample_acceptance_payload()
        )
        self.assertEqual(surface["surface_id"], "real_sample_autonomous_opportunity_acceptance")
        self.assertEqual(surface["fail_closed_reasons"], [])

    def test_region_adapters_are_visible_for_owner_search(self) -> None:
        catalog = list_operator_region_adapters({})

        self.assertEqual(catalog["surface_id"], "operator_region_source_adapters")
        self.assertTrue(catalog["region_adapter_catalog"])
        self.assertIn("CN-GD", catalog["searchable_region_codes"])
        self.assertIn("CN-SC", catalog["commercial_pilot_region_codes"])
        by_code = {
            adapter["region_code"]: adapter
            for adapter in catalog["region_adapters"]
        }
        self.assertTrue(by_code["CN-GD"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-SC"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-JS"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-ZJ"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-SD"]["dedicated_local_profiles"])
        self.assertTrue(by_code["CN-HB"]["dedicated_local_profiles"])
        self.assertFalse(by_code["CN-SC"]["onboarding_required"])
        self.assertFalse(by_code["CN-SC"]["manual_url_picker_primary_flow"])

    @patch(
        "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService",
        return_value=_FakeNoCandidateDiscoveryService(),
    )
    def test_operator_autonomous_search_calls_real_candidate_discovery_and_does_not_fabricate_when_empty(
        self,
        _discovery_service: object,
    ) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD", "CN-JS"],
                "query": "公共建筑工程",
                "project_types": ["construction", "municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "candidate_count": 3,
                "now": "2026-04-30T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_state"], "NO_CANDIDATES")
        self.assertEqual(payload["reason"], "real_public_candidate_discovery_returned_no_candidates")
        self.assertEqual(payload["search_scope"]["candidate_count"], 0)
        self.assertEqual(payload["search_scope"]["selected_candidate_count"], 0)
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 0)
        self.assertEqual(payload["search_scope"]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
        self.assertTrue(payload["search_scope"]["real_candidate_discovery_attempted"])
        self.assertFalse(payload["search_scope"]["real_market_discovery"])
        self.assertEqual(payload["runtime_flow"]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
        self.assertTrue(payload["runtime_flow"]["real_candidate_discovery_attempted"])
        self.assertFalse(payload["runtime_flow"]["test_path_unblocked"])
        self.assertFalse(payload["runtime_flow"]["customer_sellable_evidence_ready"])
        self.assertEqual(payload["real_candidate_discovery"]["surface_id"], "operator_real_candidate_discovery")
        self.assertIn("没有生成机会", payload["runtime_flow"]["data_boundary_message"])
        self.assertFalse(payload["data_boundary"]["offline_sample_validation"])
        self.assertFalse(payload["data_boundary"]["customer_sellable_evidence_ready"])
        self.assertIn("没有生成机会", payload["display_message"])
        self.assertEqual(payload["opportunity_id"], "")
        self.assertEqual(payload["opportunity_ids"], [])
        self.assertEqual(payload["candidate_options"], [])

    @patch(
        "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService",
        return_value=_FakeReviewCandidateDiscoveryService(),
    )
    @patch(
        "api.routes.operator_customer_access.RealCandidateStage2CaptureService",
        return_value=_FakeReviewCandidateStage2CaptureService(),
    )
    def test_operator_autonomous_search_feeds_real_list_candidates_into_stage1_without_sample_fabrication(
        self,
        _stage2_capture_service: object,
        _discovery_service: object,
    ) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD"],
                "query": "市政道路",
                "project_types": ["municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "now": "2026-05-01T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_state"], "REVIEW_REQUIRED")
        self.assertEqual(payload["search_scope"]["candidate_count"], 1)
        self.assertEqual(payload["search_scope"]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
        self.assertTrue(payload["search_scope"]["real_candidate_discovery_attempted"])
        self.assertTrue(payload["search_scope"]["real_market_discovery"])
        self.assertEqual(payload["search_scope"]["stage2_detail_snapshot_count"], 1)
        self.assertEqual(payload["search_scope"]["stage3_parse_success_count"], 1)
        self.assertFalse(payload["data_boundary"]["offline_sample_validation"])
        self.assertFalse(payload["data_boundary"]["customer_sellable_evidence_ready"])
        self.assertEqual(payload["real_candidate_discovery"]["candidate_count"], 1)
        self.assertEqual(payload["real_candidate_stage2_capture"]["detail_snapshot_count"], 1)
        self.assertEqual(payload["candidate_options"][0]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
        self.assertEqual(payload["candidate_options"][0]["stage2_detail_capture_state"], "FETCHED")
        self.assertEqual(payload["candidate_options"][0]["source_url"], "https://www.ggzy.gov.cn/information/deal/html/a/440000/0101/20260424/real-list-001.html")
        self.assertIn("review_reasons", payload["candidate_options"][0])
        self.assertIn("missing_key_fields:candidate_company", payload["candidate_options"][0]["review_reasons"])
        self.assertEqual(payload["opportunity_id"], "")
        self.assertEqual(payload["opportunity_ids"], [])

        runs_response = client.request("GET", "/operator-console/autonomous-search-runs")
        self.assertEqual(runs_response.status_code, 200)
        runs = runs_response.json()
        self.assertEqual(runs["run_count"], 1)
        self.assertEqual(runs["runs"][0]["source_candidate_mode"], "REAL_PUBLIC_SOURCE_CANDIDATES")
        self.assertEqual(runs["runs"][0]["search_state"], "REVIEW_REQUIRED")

    @patch(
        "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService",
        return_value=_FakeAcceptedRealCandidateDiscoveryService(),
    )
    @patch(
        "api.routes.operator_customer_access.RealCandidateStage2CaptureService",
        return_value=_FakeReviewCandidateStage2CaptureService(),
    )
    @patch(
        "api.routes.operator_customer_access._build_real_public_stage4_9_readback_from_candidate",
        side_effect=_partial_real_public_stage4_9_readback,
    )
    def test_real_public_search_does_not_accept_when_hard_defect_sources_are_partial(
        self,
        _real_public_readback: object,
        _stage2_capture_service: object,
        _discovery_service: object,
    ) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD"],
                "query": "市政道路",
                "project_types": ["municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "now": "2026-05-01T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_state"], "STAGE1_6_INTERNAL_READY")
        self.assertEqual(
            payload["capability_state"],
            "REAL_PUBLIC_STAGE1_6_INTERNAL_READY_SOURCE_COVERAGE_PENDING",
        )
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 0)
        self.assertEqual(payload["search_scope"]["stage1_6_closed_loop_count"], 1)
        self.assertEqual(payload["opportunity_id"], "")
        self.assertEqual(
            payload["real_public_stage4_9_readback"]["real_public_stage4_9_chain_state"],
            "INTERNAL_READY",
        )
        self.assertEqual(
            payload["real_public_stage4_9_readback"]["real_public_stage1_6_chain_state"],
            "INTERNAL_READY",
        )
        self.assertFalse(payload["real_public_stage4_9_readback"]["real_public_sellable_gate_ready"])
        self.assertEqual(
            payload["closed_loop_results"][0]["real_world_hard_defect_gate_state"],
            "PARTIAL_SOURCE_COVERAGE",
        )
        self.assertEqual(payload["closed_loop_results"][0]["search_state"], "STAGE1_6_INTERNAL_READY")
        self.assertTrue(payload["closed_loop_results"][0]["stage1_6_closed_loop_ready"])
        self.assertIn(
            "stage4_5_local_housing_contract_completion_pm_change_penalty_adapters_pending",
            payload["data_boundary"]["remaining_real_world_gaps"],
        )
        self.assertFalse(payload["data_boundary"]["customer_sellable_evidence_ready"])

    @patch(
        "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService",
        return_value=_FakeTwoAcceptedRealCandidateDiscoveryService(),
    )
    @patch(
        "api.routes.operator_customer_access.RealCandidateStage2CaptureService",
        return_value=_FakeReviewCandidateStage2CaptureService(),
    )
    @patch(
        "api.routes.operator_customer_access._build_real_public_stage4_9_readback_from_candidate",
        side_effect=_partial_real_public_stage4_9_readback,
    )
    def test_real_public_search_keeps_all_candidates_when_stage1_6_budget_expires(
        self,
        _real_public_readback: object,
        _stage2_capture_service: object,
        _discovery_service: object,
    ) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD"],
                "query": "市政道路",
                "project_types": ["municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "stage1_6_time_budget_seconds": 0,
                "now": "2026-05-01T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_scope"]["candidate_count"], 2)
        self.assertEqual(payload["search_scope"]["selected_candidate_count"], 2)
        self.assertEqual(payload["search_scope"]["stage1_6_attempted_count"], 1)
        self.assertEqual(payload["search_scope"]["stage1_6_pending_count"], 1)
        self.assertTrue(payload["search_scope"]["stage1_6_time_budget_exhausted"])
        self.assertEqual(len(payload["closed_loop_results"]), 2)
        self.assertEqual(payload["closed_loop_results"][1]["search_state"], "STAGE1_6_PENDING_TIME_BUDGET")
        self.assertTrue(payload["candidate_options"][1]["stage1_6_time_budget_pending"])

    @patch(
        "api.routes.operator_customer_access.RealPublicCandidateDiscoveryService",
        return_value=_FakeTwoAcceptedRealCandidateDiscoveryService(),
    )
    @patch(
        "api.routes.operator_customer_access.RealCandidateStage2CaptureService",
        return_value=_FakePartialCandidateStage2CaptureService(),
    )
    @patch(
        "api.routes.operator_customer_access._build_real_public_stage4_9_readback_from_candidate",
        side_effect=_partial_real_public_stage4_9_readback,
    )
    def test_real_public_search_keeps_stage2_pending_candidates_out_of_stage1_6(
        self,
        _real_public_readback: object,
        _stage2_capture_service: object,
        _discovery_service: object,
    ) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD"],
                "query": "市政道路",
                "project_types": ["municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "now": "2026-05-01T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_scope"]["candidate_count"], 2)
        self.assertEqual(payload["search_scope"]["stage1_6_attempted_count"], 1)
        self.assertEqual(payload["search_scope"]["stage1_6_pending_count"], 1)
        self.assertEqual(payload["search_scope"]["stage2_detail_pending_for_stage1_6_count"], 1)
        self.assertEqual(payload["closed_loop_results"][1]["search_state"], "STAGE2_DETAIL_CAPTURE_PENDING")
        self.assertTrue(payload["candidate_options"][1]["stage2_detail_capture_pending"])

    def test_operator_autonomous_search_runs_region_to_workbench_loop(self) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_code": "CN-GD",
                "query": "市政工程",
                "project_type": "municipal",
                "amount_min": 8000000,
                "amount_max": 30000000,
                "candidate_count": 3,
                "allow_offline_sample_candidates": True,
                "now": "2026-04-30T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["surface_id"], "operator_autonomous_opportunity_search")
        self.assertEqual(payload["search_state"], "AUTONOMOUS_SEARCH_ACCEPTED")
        self.assertEqual(payload["region_adapter"]["region_code"], "CN-GD")
        self.assertTrue(payload["region_adapter"]["dedicated_local_profiles"])
        self.assertEqual(
            payload["acceptance"]["acceptance_state"],
            "REAL_SAMPLE_AUTONOMOUS_OPPORTUNITY_ACCEPTED",
        )
        self.assertFalse(payload["manual_url_picker_primary_flow"])
        self.assertFalse(payload["live_execution_enabled"])
        self.assertFalse(payload["real_provider_call_enabled"])
        self.assertEqual(payload["amount_range"]["minimum"], 8000000)
        self.assertEqual(payload["amount_range"]["maximum"], 30000000)
        self.assertTrue(payload["runtime_flow"]["test_path_unblocked"])
        self.assertTrue(payload["runtime_flow"]["live_delivery_gates_preserved"])
        self.assertEqual(payload["runtime_flow"]["source_candidate_mode"], "OFFLINE_SAMPLE_CANDIDATES")
        self.assertTrue(payload["runtime_flow"]["offline_sample_validation"])
        self.assertFalse(payload["runtime_flow"]["customer_sellable_evidence_ready"])
        self.assertIn("不能当作真实市场发现", payload["runtime_flow"]["data_boundary_message"])
        self.assertEqual(payload["runtime_flow"]["totals"]["stage_count"], 9)
        self.assertEqual(len(payload["runtime_flow"]["stage_stats"]), 9)
        self.assertEqual(payload["search_scope"]["candidate_count"], 1)
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 1)
        self.assertEqual(payload["search_scope"]["source_candidate_mode"], "OFFLINE_SAMPLE_CANDIDATES")
        self.assertTrue(payload["search_scope"]["offline_sample_candidates_enabled"])
        self.assertFalse(payload["search_scope"]["real_market_discovery"])
        self.assertTrue(payload["data_boundary"]["offline_sample_validation"])
        self.assertFalse(payload["data_boundary"]["customer_sellable_evidence_ready"])
        self.assertIn("不能当作真实市场发现", payload["data_boundary"]["display_message"])
        self.assertEqual(len(payload["candidate_options"]), 1)
        self.assertEqual(payload["candidate_options"][0]["region_code"], "CN-GD")
        self.assertEqual(payload["candidate_options"][0]["project_type"], "municipal")
        self.assertTrue(payload["candidate_options"][0]["is_offline_sample_candidate"])
        self.assertEqual(
            payload["candidate_options"][0]["sellability_evidence_state"],
            "SAMPLE_NOT_CUSTOMER_SELLABLE",
        )
        self.assertTrue(payload["search_run_id"])
        self.assertEqual(
            payload["search_run_record"]["search_state"],
            "AUTONOMOUS_SEARCH_ACCEPTED",
        )

        opportunity_id = payload["opportunity_id"]
        self.assertTrue(opportunity_id)
        runs_response = client.request("GET", "/operator-console/autonomous-search-runs")
        self.assertEqual(runs_response.status_code, 200)
        runs = runs_response.json()
        self.assertEqual(runs["surface_id"], "operator_autonomous_search_runs")
        self.assertEqual(runs["run_count"], 1)
        self.assertTrue(runs["autonomous_search_run_list"])
        self.assertFalse(runs["raw_json_required"])
        self.assertEqual(runs["runs"][0]["opportunity_id"], opportunity_id)
        self.assertEqual(runs["runs"][0]["region_code"], "CN-GD")
        self.assertEqual(runs["latest_runtime_flow"]["totals"]["stage_count"], 9)
        self.assertEqual(runs["runs"][0]["search_scope"]["candidate_count"], 1)
        self.assertEqual(runs["runs"][0]["candidate_options"][0]["region_code"], "CN-GD")
        self.assertEqual(runs["runs"][0]["source_candidate_mode"], "OFFLINE_SAMPLE_CANDIDATES")
        self.assertTrue(runs["runs"][0]["offline_sample_validation"])
        self.assertFalse(runs["runs"][0]["customer_sellable_evidence_ready"])
        self.assertEqual(
            runs["runs"][0]["search_state"],
            "AUTONOMOUS_SEARCH_ACCEPTED",
        )
        workbench_response = client.request(
            "GET",
            "/operator-console/autonomous-workbench",
            params={"opportunity_id": opportunity_id},
        )
        self.assertEqual(workbench_response.status_code, 200)
        workbench = workbench_response.json()
        self.assertEqual(workbench["opportunity_queue"][0]["opportunity_id"], opportunity_id)
        self.assertIn(
            "公开风险信号",
            workbench["opportunity_queue"][0]["commercial_hook_teaser"],
        )
        self.assertEqual(
            workbench["opportunity_queue"][0]["next_action"],
            "PREPARE_LEADPACK_REVIEW_AND_DELIVERY_GATE",
        )
        self.assertEqual(
            workbench["panels"]["commercial_hook_panel"]["disclosure_level"],
            "L1_HOOK",
        )
        self.assertEqual(
            workbench["panels"]["evidence_risk_panel"]["evidence_strength_label"],
            "REVIEWABLE_PUBLIC_SIGNAL",
        )
        self.assertFalse(workbench["raw_json_required"])
        self.assertFalse(workbench["safe_display_contract"]["customer_download_enabled"])

    def test_operator_autonomous_search_runs_collapse_duplicate_opportunities(self) -> None:
        client = TestClient(create_app())
        search_payload = {
            "region_code": "CN-GD",
            "query": "市政工程",
            "project_type": "municipal",
            "amount_min": 8000000,
            "amount_max": 30000000,
            "candidate_count": 3,
            "allow_offline_sample_candidates": True,
            "now": "2026-04-30T00:00:00+00:00",
        }

        first_response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json=search_payload,
        )
        second_response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json=search_payload,
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        opportunity_id = second_response.json()["opportunity_id"]

        runs_response = client.request("GET", "/operator-console/autonomous-search-runs")
        self.assertEqual(runs_response.status_code, 200)
        runs = runs_response.json()
        self.assertEqual(runs["run_count"], 1)
        self.assertEqual(runs["raw_run_count"], 2)
        self.assertEqual(runs["duplicate_collapsed_count"], 1)
        self.assertEqual(runs["latest_opportunity_id"], opportunity_id)
        self.assertEqual(
            runs["latest_customer_artifact_portal_path"],
            f"/customer-artifact-portal/{opportunity_id}",
        )
        self.assertEqual(runs["runs"][0]["opportunity_id"], opportunity_id)
        self.assertEqual(runs["runs"][0]["amount_min"], "8000000")
        self.assertEqual(runs["runs"][0]["amount_max"], "30000000")
        self.assertEqual(runs["runs"][0]["search_scope"]["closed_loop_generated_count"], 1)
        self.assertTrue(runs["runs"][0]["runtime_flow"]["stage_stats"])

    def test_operator_autonomous_search_accepts_multi_region_and_project_type_scope(self) -> None:
        client = TestClient(create_app())

        response = client.request(
            "POST",
            "/operator-console/autonomous-opportunity-search",
            json={
                "region_codes": ["CN-GD", "CN-JS"],
                "query": "公共建筑工程",
                "project_types": ["construction", "municipal"],
                "amount_min": 8000000,
                "amount_max": 30000000,
                "candidate_count": 3,
                "allow_offline_sample_candidates": True,
                "now": "2026-04-30T00:00:00+00:00",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["search_state"], "AUTONOMOUS_SEARCH_ACCEPTED")
        self.assertEqual(payload["search_scope"]["region_codes"], ["CN-GD", "CN-JS"])
        self.assertEqual(payload["search_scope"]["project_types"], ["construction", "municipal"])
        self.assertEqual(payload["search_scope"]["candidate_count"], 4)
        self.assertEqual(payload["search_scope"]["selected_candidate_count"], 4)
        self.assertEqual(payload["search_scope"]["closed_loop_generated_count"], 4)
        self.assertEqual(
            payload["search_scope"]["selection_semantics"],
            "CANDIDATE_PUBLICITY_WINDOW_LAYER_NOT_SINGLE_PICK",
        )
        self.assertIn("所有候选", payload["search_scope"]["stage1_policy"])
        self.assertEqual(len(payload["opportunity_ids"]), 4)
        self.assertEqual(payload["region_adapter"]["region_code"], "CN-GD")
        self.assertEqual(payload["candidate"]["project_type"], "construction")
        self.assertEqual(len(payload["candidate_options"]), 4)
        self.assertEqual(
            {candidate["region_code"] for candidate in payload["candidate_options"]},
            {"CN-GD", "CN-JS"},
        )
        self.assertTrue(all(candidate["opportunity_id"] for candidate in payload["candidate_options"]))
        self.assertTrue(payload["candidate_options"][0]["project_name"])
        self.assertEqual(payload["runtime_flow"]["stage_stats"][0]["produced_count"], 4)
        self.assertEqual(payload["runtime_flow"]["stage_stats"][0]["object_refs"]["passed_filter_candidate_count"], 4)


if __name__ == "__main__":
    unittest.main()
