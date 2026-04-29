from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from shared.utils import build_id, utc_now_iso
from storage.repositories.stage1_market_scan_repo import Stage1MarketScanRepository


MARKET_SCAN_OBJECT_TYPE = "stage1_market_scan_run"
MARKET_SCAN_QUEUE_NAME = "stage1_market_scan_queue"
DEFAULT_MINIMUM_AMOUNT = 1_000_000.0
DEFAULT_ANALYZE_SCORE = 50
PILOT_REGION_CODES = {
    "CN-SC",
    "CN-JS",
    "CN-ZJ",
    "CN-SD",
    "CN-GD",
    "CN-HB",
}
HIGH_VALUE_AMOUNT = 10_000_000.0
MEDIUM_VALUE_AMOUNT = 3_000_000.0
ANALYSIS_NOTICE_STAGES = {
    "candidate_notice",
    "candidate_publicity",
    "award_result",
    "result_notice",
    "bid_result",
}
DISCOVERY_NOTICE_STAGES = {
    "tender_notice",
    "procurement_notice",
    "correction_notice",
}
REQUIRED_KEY_FIELDS = {
    "project_name",
    "candidate_company",
    "notice_stage",
}
_BLOCKED_LIVE_FLAGS = (
    "live_execution_enabled",
    "external_fetch_enabled",
    "real_external_fetch_enabled",
    "unregistered_capture_enabled",
    "provider_call_enabled",
    "real_provider_call_enabled",
    "customer_visible_enabled",
    "manual_url_picker_primary_flow",
)
_BLOCKED_SOURCE_TOKENS = ("LOGIN", "CAPTCHA", "ANTI_BOT")


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on", "live"}
    return bool(value)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_stage(value: Any) -> str:
    return str(value or "unknown").strip().lower().replace("-", "_")


def _candidate_id(scan_run_id: str, index: int, candidate: Mapping[str, Any]) -> str:
    return str(
        candidate.get("opportunity_candidate_id")
        or candidate.get("candidate_id")
        or build_id("OPP", scan_run_id, str(index + 1).zfill(3))
    )


def _candidate_project_id(index: int, candidate: Mapping[str, Any]) -> str:
    return str(
        candidate.get("project_id")
        or candidate.get("notice_id")
        or candidate.get("source_record_id")
        or f"PROJECT-CANDIDATE-{index + 1:03d}"
    )


def _key_fields(candidate: Mapping[str, Any]) -> set[str]:
    values = candidate.get("key_fields_present")
    if isinstance(values, str):
        return {item.strip() for item in values.split(",") if item.strip()}
    if isinstance(values, list):
        return {str(item) for item in values if item}
    fields = set()
    for field in REQUIRED_KEY_FIELDS:
        if candidate.get(field) not in (None, "", [], {}):
            fields.add(field)
    if candidate.get("candidate_company") or candidate.get("winner_name") or candidate.get("first_rank_company"):
        fields.add("candidate_company")
    return fields


def _public_boundary_blockers(candidate: Mapping[str, Any]) -> list[str]:
    source_markers = " ".join(
        str(candidate.get(field, ""))
        for field in (
            "source_mode",
            "source_family",
            "source_registry_id",
            "source_url",
            "visibility",
            "source_visibility_state",
        )
    ).upper()
    blockers = [token.lower() for token in _BLOCKED_SOURCE_TOKENS if token in source_markers]
    return [f"blocked_source_marker_{token}" for token in blockers]


class Stage1MarketScanEngine:
    def __init__(self, *, repository: Stage1MarketScanRepository | None = None) -> None:
        self.repository = repository or Stage1MarketScanRepository()

    def run(self, payload: Mapping[str, Any], *, persist: bool = True) -> dict[str, Any]:
        payload_dict = dict(payload)
        self._assert_internal_boundary(payload_dict)
        now = str(payload_dict.get("now") or utc_now_iso())
        scan_run_id = str(
            payload_dict.get("scan_run_id")
            or payload_dict.get("market_scan_run_id")
            or build_id("MKTSCAN", str(payload_dict.get("task_id") or "RUN"))
        )
        candidates = self._candidate_inputs(payload_dict)
        decision_candidates = [
            self._score_candidate(scan_run_id, index, candidate, now=now, payload=payload_dict)
            for index, candidate in enumerate(candidates)
        ]
        selected = [
            candidate
            for candidate in decision_candidates
            if candidate["analysis_decision"] == "ANALYZE"
        ]
        review = [
            candidate
            for candidate in decision_candidates
            if candidate["analysis_decision"] == "REVIEW"
        ]
        skipped = [
            candidate
            for candidate in decision_candidates
            if candidate["analysis_decision"] == "SKIP"
        ]
        next_action = self._next_action(selected=selected, review=review, skipped=skipped)
        run_controller = self._build_run_controller(
            scan_run_id=scan_run_id,
            payload=payload_dict,
            selected=selected,
            review=review,
            skipped=skipped,
            next_action=next_action,
        )
        stage_state_machine = self._build_stage_state_machine(next_action=next_action)
        audit_refs = {
            "market_scan_audit_id": build_id("MKTSCANAUD", scan_run_id),
            "decision_trace_id": build_id("MKTSCANTRACE", scan_run_id),
            "source_blueprint_batch_id": str(payload_dict.get("source_blueprint_batch_id") or "PTL-I100-ROADMAP-01"),
        }
        scan = {
            "scan_run_id": scan_run_id,
            "task_id": str(payload_dict.get("task_id") or scan_run_id),
            "batch_id": str(payload_dict.get("batch_id") or payload_dict.get("source_blueprint_batch_id") or "MARKET-SCAN-BATCH"),
            "created_at": now,
            "updated_at": now,
            "capability_state": "INTERNAL_READY",
            "internal_only": True,
            "customer_visible": False,
            "live_execution_enabled": False,
            "real_external_fetch_enabled": False,
            "unregistered_capture_enabled": False,
            "manual_url_picker_primary_flow": False,
            "autonomous_decision": True,
            "input_candidate_count": len(candidates),
            "selected_candidate_count": len(selected),
            "review_candidate_count": len(review),
            "skipped_candidate_count": len(skipped),
            "market_scan_candidates": decision_candidates,
            "opportunity_candidates": selected,
            "review_candidates": review,
            "skipped_candidates": skipped,
            "run_controller": run_controller,
            "stage_state_machine": stage_state_machine,
            "next_action": next_action,
            "readback_summary": {
                "readback_state": "READBACK_READY",
                "repository_backed": persist,
                "replayable": persist,
                "autonomous_run_controller_visible": True,
                "stage_state_machine_visible": True,
                "manual_url_picker_primary_flow": False,
                "selected_candidate_count": len(selected),
                "review_candidate_count": len(review),
                "skipped_candidate_count": len(skipped),
                "next_action": next_action,
            },
            "controlled_opening_boundaries": {
                "unapproved_capture_enabled": False,
                "real_external_fetch_enabled": False,
                "provider_call_enabled": False,
                "customer_visible_claim_enabled": False,
                "manual_url_picker_as_primary_flow": False,
            },
            "audit_refs": audit_refs,
        }
        if persist:
            self.repository.save(scan)
            scan["readback_summary"]["repository_backed"] = True
            scan["readback_summary"]["replayable"] = True
        return scan

    def readback(self, scan_run_id: str) -> dict[str, Any]:
        return self.repository.readback(scan_run_id)

    def replay(self, scan_run_id: str) -> dict[str, Any]:
        return self.repository.replay(scan_run_id)

    def _candidate_inputs(self, payload: Mapping[str, Any]) -> list[dict[str, Any]]:
        candidates = payload.get("notice_candidates") or payload.get("market_scan_candidates")
        if isinstance(candidates, list) and candidates:
            return [dict(candidate) for candidate in candidates if isinstance(candidate, Mapping)]
        return [
            {
                "notice_id": payload.get("notice_id") or payload.get("task_id") or "NOTICE-001",
                "project_id": payload.get("project_id"),
                "project_name": payload.get("project_name"),
                "region_code": payload.get("region_code"),
                "project_type": payload.get("project_type") or payload.get("procurement_regime"),
                "notice_stage": payload.get("notice_stage") or payload.get("carrier_type") or "tender_notice",
                "amount": payload.get("amount") or payload.get("contract_amount_optional") or payload.get("estimated_amount"),
                "objection_deadline_at_optional": payload.get("objection_deadline_at_optional")
                or payload.get("current_action_deadline_at_optional")
                or payload.get("time_range_until"),
                "candidate_count": payload.get("candidate_count") or payload.get("competitor_count") or 0,
                "candidate_company": payload.get("candidate_company") or payload.get("winner_name"),
                "source_url": payload.get("source_url") or payload.get("announcement_url"),
                "source_family": payload.get("source_family"),
                "source_registry_id": payload.get("source_registry_id"),
                "key_fields_present": payload.get("key_fields_present"),
            }
        ]

    def _score_candidate(
        self,
        scan_run_id: str,
        index: int,
        candidate: Mapping[str, Any],
        *,
        now: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        effective_now = _parse_time(now) or datetime.now(tz=timezone.utc)
        score_components: dict[str, int] = {}
        why_analyze: list[str] = []
        why_skip: list[str] = []
        review_reasons: list[str] = []
        amount = _as_float(
            candidate.get("contract_amount_optional")
            or candidate.get("estimated_amount")
            or candidate.get("amount")
        )
        minimum_amount = _as_float(payload.get("minimum_amount"), DEFAULT_MINIMUM_AMOUNT)
        notice_stage = _normalize_stage(candidate.get("notice_stage"))
        region_code = str(candidate.get("region_code") or payload.get("region_code") or "UNKNOWN")
        competitor_count = max(
            _as_int(candidate.get("candidate_count")),
            _as_int(candidate.get("competitor_count")),
            _as_int(candidate.get("bidder_count")),
        )
        key_fields = _key_fields(candidate)
        deadline = _parse_time(
            candidate.get("objection_deadline_at_optional")
            or candidate.get("objection_deadline_at")
            or candidate.get("challenge_deadline_at")
        )

        why_skip.extend(_public_boundary_blockers(candidate))
        if amount and amount < minimum_amount:
            why_skip.append("amount_below_minimum")
        if deadline is not None and deadline < effective_now:
            why_skip.append("objection_window_expired")
        if competitor_count < 1:
            why_skip.append("no_competitor_signal")
        missing_fields = sorted(REQUIRED_KEY_FIELDS - key_fields)
        if missing_fields:
            review_reasons.append("missing_key_fields:" + ",".join(missing_fields))

        if amount >= HIGH_VALUE_AMOUNT:
            score_components["value_band"] = 25
            why_analyze.append("high_value_amount_band")
        elif amount >= MEDIUM_VALUE_AMOUNT:
            score_components["value_band"] = 15
            why_analyze.append("medium_value_amount_band")
        elif amount >= minimum_amount:
            score_components["value_band"] = 8
            why_analyze.append("minimum_value_amount_band")
        else:
            score_components["value_band"] = 0

        if notice_stage in ANALYSIS_NOTICE_STAGES:
            score_components["notice_stage"] = 20
            why_analyze.append("candidate_or_award_stage")
        elif notice_stage in DISCOVERY_NOTICE_STAGES:
            score_components["notice_stage"] = 10
            why_analyze.append("early_discovery_stage")
        else:
            score_components["notice_stage"] = 0
            review_reasons.append("unknown_notice_stage")

        if deadline is None:
            score_components["objection_window"] = 5
            review_reasons.append("objection_window_unknown")
        elif deadline >= effective_now:
            score_components["objection_window"] = 25
            why_analyze.append("active_objection_window")
        else:
            score_components["objection_window"] = 0

        if competitor_count >= 3:
            score_components["competitor_signal"] = 20
            why_analyze.append("multi_competitor_signal_present")
        elif competitor_count >= 1:
            score_components["competitor_signal"] = 12
            why_analyze.append("competitor_signal_present")
        else:
            score_components["competitor_signal"] = 0

        if region_code in PILOT_REGION_CODES:
            score_components["region_priority"] = 10
            why_analyze.append("first_batch_pilot_region")
        elif region_code == "CN-BJ":
            score_components["region_priority"] = 0
            review_reasons.append("beijing_technical_regression_only_not_commercial_pilot")
        else:
            score_components["region_priority"] = 4

        key_field_score = max(0, 15 - (5 * len(missing_fields)))
        score_components["key_field_completeness"] = key_field_score
        if not missing_fields:
            why_analyze.append("critical_fields_present")

        score = sum(score_components.values())
        analyze_threshold = _as_int(payload.get("analysis_score_threshold"), DEFAULT_ANALYZE_SCORE)
        if why_skip:
            decision = "SKIP"
            priority = "SKIPPED"
            selected = False
        elif review_reasons or score < analyze_threshold:
            decision = "REVIEW"
            priority = "REVIEW"
            selected = False
            if score < analyze_threshold:
                review_reasons.append("score_below_analysis_threshold")
        else:
            decision = "ANALYZE"
            selected = True
            if score >= 85:
                priority = "HIGH"
            elif score >= 65:
                priority = "MEDIUM"
            else:
                priority = "LOW"

        project_id = _candidate_project_id(index, candidate)
        return {
            "opportunity_candidate_id": _candidate_id(scan_run_id, index, candidate),
            "notice_id": str(candidate.get("notice_id") or candidate.get("source_record_id") or project_id),
            "project_id": project_id,
            "project_name": str(candidate.get("project_name") or "UNKNOWN"),
            "region_code": region_code,
            "project_type": str(candidate.get("project_type") or "UNKNOWN"),
            "notice_stage": notice_stage,
            "amount": amount,
            "competitor_count": competitor_count,
            "key_fields_present": sorted(key_fields),
            "objection_deadline_at_optional": str(
                candidate.get("objection_deadline_at_optional")
                or candidate.get("objection_deadline_at")
                or ""
            ),
            "analysis_score": score,
            "score_components": score_components,
            "analysis_decision": decision,
            "analysis_priority": priority,
            "selected_for_capture_plan": selected,
            "why_analyze": why_analyze if selected else [],
            "why_skip": why_skip,
            "review_reasons": review_reasons,
            "source_refs": {
                "source_url": str(candidate.get("source_url") or ""),
                "source_family": str(candidate.get("source_family") or ""),
                "source_registry_id": str(candidate.get("source_registry_id") or ""),
            },
            "required_next_stage_inputs": [
                "source_blueprint_selection",
                "stage2_capture_plan",
            ]
            if selected
            else [],
            "customer_visible": False,
        }

    def _next_action(
        self,
        *,
        selected: list[dict[str, Any]],
        review: list[dict[str, Any]],
        skipped: list[dict[str, Any]],
    ) -> str:
        if selected:
            return "CREATE_STAGE2_CAPTURE_PLAN"
        if review:
            return "OPERATOR_REVIEW_MARKET_SCAN_CANDIDATES"
        if skipped:
            return "WAIT_NEXT_MARKET_SCAN"
        return "NO_CANDIDATES"

    def _build_run_controller(
        self,
        *,
        scan_run_id: str,
        payload: Mapping[str, Any],
        selected: list[dict[str, Any]],
        review: list[dict[str, Any]],
        skipped: list[dict[str, Any]],
        next_action: str,
    ) -> dict[str, Any]:
        return {
            "run_controller_id": build_id("RUNCTRL", scan_run_id),
            "controller_state": "INTERNAL_READY",
            "autonomous_decision": True,
            "manual_url_picker_primary_flow": False,
            "decision_planner": "stage1_market_scan_decision_planner.v1",
            "stage_state_machine_enabled": True,
            "work_queue_dispatcher": MARKET_SCAN_QUEUE_NAME,
            "transition_guard": {
                "requires_selected_opportunity_candidate": next_action == "CREATE_STAGE2_CAPTURE_PLAN",
                "blocks_external_fetch": True,
                "blocks_customer_visible_claim": True,
                "blocks_manual_url_picker_primary_flow": True,
            },
            "pushes_next_step_by": "stage_state_machine_next_action",
            "next_action": next_action,
            "next_packet_hint": "PTL-I100-145-source-blueprint-orchestration-and-capture-plan"
            if selected
            else "PTL-I100-144-market-scan-opportunity-discovery-engine",
            "selected_candidate_ids": [candidate["opportunity_candidate_id"] for candidate in selected],
            "review_candidate_ids": [candidate["opportunity_candidate_id"] for candidate in review],
            "skipped_candidate_ids": [candidate["opportunity_candidate_id"] for candidate in skipped],
            "source_policy": {
                "manual_url_selection_as_primary_flow": False,
                "market_segment_selection_source": "market_scan_policy",
                "region_project_type_amount_stage_window_competitor_filter": True,
            },
            "operator_intervention_gate": {
                "required": bool(review) and not selected,
                "reason": "review_candidates_without_selected_analysis_candidate" if review and not selected else "",
            },
            "audit_ref": build_id("RUNCTRLAUD", scan_run_id),
            "task_id": str(payload.get("task_id") or scan_run_id),
        }

    def _build_stage_state_machine(self, *, next_action: str) -> dict[str, Any]:
        return {
            "state_machine_id": "STAGE1-9-AUTONOMOUS-RUN-CONTROLLER-V1",
            "current_stage": "stage1_market_scan",
            "current_state": "COMPLETED" if next_action != "NO_CANDIDATES" else "NO_CANDIDATES",
            "next_action": next_action,
            "stage_progression": [
                {
                    "stage": "stage1_market_scan",
                    "state": "COMPLETED",
                    "executor": "market_scan_decision_planner",
                },
                {
                    "stage": "stage2_capture_plan",
                    "state": "WAITING_FOR_145" if next_action == "CREATE_STAGE2_CAPTURE_PLAN" else "BLOCKED_UNTIL_SELECTED_CANDIDATE",
                    "executor": "source_blueprint_orchestrator",
                },
                {
                    "stage": "stage3_to_stage9",
                    "state": "BLOCKED_UNTIL_STAGE2_CAPTURE_PLAN",
                    "executor": "downstream_stage_state_machine",
                },
            ],
            "external_live_transport_enabled": False,
            "real_external_fetch_enabled": False,
            "customer_visible_claim_enabled": False,
        }

    def _assert_internal_boundary(self, payload: Mapping[str, Any]) -> None:
        requested_live_flags = [flag for flag in _BLOCKED_LIVE_FLAGS if _truthy(payload.get(flag))]
        if requested_live_flags:
            raise ValueError(
                "market scan is internal opportunity discovery only; blocked flags: "
                + ", ".join(requested_live_flags)
            )
        source_mode = str(payload.get("source_selection_mode") or payload.get("source_mode") or "").upper()
        if "MANUAL_URL" in source_mode and "PRIMARY" in source_mode:
            raise ValueError("manual URL picker cannot be the primary market scan flow")


__all__ = [
    "DEFAULT_ANALYZE_SCORE",
    "DEFAULT_MINIMUM_AMOUNT",
    "MARKET_SCAN_OBJECT_TYPE",
    "MARKET_SCAN_QUEUE_NAME",
    "PILOT_REGION_CODES",
    "Stage1MarketScanEngine",
]
