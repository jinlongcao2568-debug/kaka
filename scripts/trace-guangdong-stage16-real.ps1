param(
    [string[]]$ProjectTypes = @("construction", "municipal", "water_conservancy", "highway"),
    [double]$AmountMin = 0,
    [double]$AmountMax = 200000000,
    [int]$DiscoveryProfileLimitPerRegion = 1,
    [Nullable[int]]$CandidateLimit = $null,
    [Nullable[int]]$DetailCaptureLimit = 30,
    [Nullable[int]]$AttachmentCaptureLimit = 80,
    [double]$Stage2DetailCaptureTimeBudgetSeconds = 600,
    [double]$Stage16TimeBudgetSeconds = 600,
    [switch]$Full,
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot

$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaka-gd-stage16-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not $env:KAKA_STORAGE_PATH) {
    $env:KAKA_STORAGE_PATH = Join-Path $runRoot "store.json"
}
if (-not $env:KAKA_OBJECT_STORAGE_PATH) {
    $env:KAKA_OBJECT_STORAGE_PATH = Join-Path $runRoot "objects"
}
$env:PYTHONIOENCODING = "utf-8"

$payload = @{
    region_codes = @("CN-GD")
    project_types = $ProjectTypes
    amount_min = $AmountMin
    amount_max = $AmountMax
    discovery_profile_limit_per_region = $DiscoveryProfileLimitPerRegion
    detail_capture_limit = $DetailCaptureLimit
    stage2_detail_capture_time_budget_seconds = $Stage2DetailCaptureTimeBudgetSeconds
    attachment_capture_limit = $AttachmentCaptureLimit
    stage1_6_time_budget_seconds = $Stage16TimeBudgetSeconds
    trace_mode = "GUANGDONG_STAGE1_6_REAL_PUBLIC_TRACE"
}
if ($null -ne $CandidateLimit) {
    $payload.discovery_candidate_limit = $CandidateLimit
}
$payloadJson = $payload | ConvertTo-Json -Depth 20 -Compress

$python = @'
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path.cwd()
for search_path in (ROOT / "src", ROOT / "tests"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from api.routes.operator_customer_access import run_operator_autonomous_opportunity_search


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _status_counts(rows: list[Mapping[str, Any]], key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        counts[str(row.get(key) or "UNKNOWN")] += 1
    return dict(counts)


def _field_count(rows: list[Mapping[str, Any]], key: str) -> int:
    return sum(1 for row in rows if str(row.get(key) or "").strip())


def _detail_field_count(rows: list[Mapping[str, Any]], key: str) -> int:
    total = 0
    for row in rows:
        fields = row.get("detail_fields")
        if isinstance(fields, Mapping) and str(fields.get(key) or "").strip():
            total += 1
    return total


def _counter_from_nested_list(rows: list[Mapping[str, Any]], outer_key: str, nested_key: str) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        nested = row.get(outer_key)
        if not isinstance(nested, Mapping):
            continue
        for value in list(nested.get(nested_key) or []):
            text = str(value or "").strip()
            if text:
                counts[text] += 1
    return dict(counts.most_common(30))


def _first_non_empty(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _sample_candidate_rows(rows: list[Mapping[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for row in rows[:limit]:
        fields = row.get("detail_fields") if isinstance(row.get("detail_fields"), Mapping) else {}
        samples.append(
            {
                "project_id": row.get("project_id"),
                "project_name": row.get("project_name"),
                "source_url": row.get("source_url"),
                "candidate_company": _first_non_empty(row, "candidate_company", "winner_name", "first_rank_company"),
                "amount": row.get("amount"),
                "notice_stage": row.get("notice_stage"),
                "engineering_work_lane": row.get("engineering_work_lane"),
                "opportunity_priority_class": row.get("opportunity_priority_class"),
                "primary_responsible_person_name": row.get("primary_responsible_person_name"),
                "project_manager_name": row.get("project_manager_name"),
                "project_manager_certificate_no": row.get("project_manager_certificate_no"),
                "responsible_role_gap_code": row.get("responsible_role_gap_code"),
                "detail_project_manager_name": fields.get("project_manager_name") if isinstance(fields, Mapping) else "",
                "detail_project_manager_certificate_no": fields.get("project_manager_certificate_no")
                if isinstance(fields, Mapping)
                else "",
                "stage2_detail_snapshot_id_optional": row.get("stage2_detail_snapshot_id_optional"),
                "stage3_parse_state": row.get("stage3_parse_state"),
            }
        )
    return samples


def build_summary(result: Mapping[str, Any], *, payload: Mapping[str, Any], full: bool) -> dict[str, Any]:
    discovery = result.get("real_candidate_discovery") if isinstance(result.get("real_candidate_discovery"), Mapping) else {}
    stage2 = (
        result.get("real_candidate_stage2_capture")
        if isinstance(result.get("real_candidate_stage2_capture"), Mapping)
        else {}
    )
    ledger = result.get("stage1_6_validation_ledger") if isinstance(result.get("stage1_6_validation_ledger"), Mapping) else {}
    enriched = [
        dict(row)
        for row in list(stage2.get("enriched_candidates") or discovery.get("candidates") or [])
        if isinstance(row, Mapping)
    ]
    closed = [
        dict(row)
        for row in list(result.get("closed_loop_results") or [])
        if isinstance(row, Mapping)
    ]
    readbacks = [
        dict(row.get("real_public_stage4_9_readback") or {})
        for row in closed
        if isinstance(row.get("real_public_stage4_9_readback"), Mapping)
    ]

    fail_reasons: Counter[str] = Counter()
    remaining_gaps: Counter[str] = Counter()
    for row in closed:
        for reason in list(row.get("fail_closed_reasons") or []):
            fail_reasons[str(reason)] += 1
    for readback in readbacks:
        for reason in list(readback.get("fail_closed_reasons") or []):
            fail_reasons[str(reason)] += 1
        for gap in list(readback.get("remaining_real_world_gaps") or []):
            remaining_gaps[str(gap)] += 1

    profile_reports = []
    for row in list(discovery.get("profile_reports") or []):
        if not isinstance(row, Mapping):
            continue
        profile_reports.append(
            {
                "profile_id": row.get("profile_id"),
                "status": row.get("status"),
                "http_status": row.get("http_status"),
                "public_api_state": row.get("public_api_state"),
                "public_api_url": row.get("public_api_url"),
                "public_api_total": row.get("public_api_total"),
                "public_api_row_count": row.get("public_api_row_count"),
                "accepted_candidate_count": row.get("accepted_candidate_count"),
                "candidate_count": row.get("candidate_count"),
                "candidate_limit_truncated_count": row.get("candidate_limit_truncated_count"),
                "operator_diagnosis": row.get("operator_diagnosis"),
                "next_action": row.get("next_action"),
                "rejected_counts": row.get("rejected_counts"),
            }
        )

    summary: dict[str, Any] = {
        "trace_id": "guangdong-stage1-6-real-public",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "storage_path": os.environ.get("KAKA_STORAGE_PATH", ""),
        "object_storage_path": os.environ.get("KAKA_OBJECT_STORAGE_PATH", ""),
        "payload": dict(payload),
        "topline": {
            "search_state": result.get("search_state"),
            "capability_state": result.get("capability_state"),
            "customer_sellable_evidence_ready": bool(
                (result.get("data_boundary") or {}).get("customer_sellable_evidence_ready")
            )
            if isinstance(result.get("data_boundary"), Mapping)
            else False,
            "closed_loop_results_count": len(closed),
        },
        "stage1": {
            "candidate_count": discovery.get("candidate_count"),
            "candidate_limit_source": discovery.get("candidate_limit_source"),
            "candidate_limit_effective": discovery.get("candidate_limit_effective"),
            "stage1_6_validation_mode": discovery.get("stage1_6_validation_mode"),
            "stage1_6_validation_caps": discovery.get("stage1_6_validation_caps"),
            "profile_reports": profile_reports,
            "candidate_discovery_diagnostics": discovery.get("candidate_discovery_diagnostics"),
        },
        "stage2": {
            "input_candidate_count": stage2.get("input_candidate_count"),
            "capture_limit": stage2.get("capture_limit"),
            "detail_capture_attempted_count": stage2.get("detail_capture_attempted_count"),
            "new_detail_capture_attempted_count": stage2.get("new_detail_capture_attempted_count"),
            "existing_capture_reused_count": stage2.get("existing_capture_reused_count"),
            "pending_detail_capture_count": stage2.get("pending_detail_capture_count"),
            "pending_detail_capture_reason": stage2.get("pending_detail_capture_reason"),
            "detail_capture_failed_count": stage2.get("detail_capture_failed_count"),
            "detail_snapshot_count": stage2.get("detail_snapshot_count"),
            "attachment_link_count": stage2.get("attachment_link_count"),
            "attachment_capture_attempted_count": stage2.get("attachment_capture_attempted_count"),
            "attachment_snapshot_count": stage2.get("attachment_snapshot_count"),
            "detail_capture_failure_summary": stage2.get("detail_capture_failure_summary"),
            "detail_capture_time_budget_seconds": stage2.get("detail_capture_time_budget_seconds"),
            "detail_capture_time_budget_exhausted": stage2.get("detail_capture_time_budget_exhausted"),
        },
        "stage3": {
            "stage3_parse_success_count": stage2.get("stage3_parse_success_count"),
            "stage3_parse_failed_count": stage2.get("stage3_parse_failed_count"),
            "field_coverage": {
                "candidate_company": _field_count(enriched, "candidate_company"),
                "amount": _field_count(enriched, "amount"),
                "notice_stage": _field_count(enriched, "notice_stage"),
                "engineering_work_lane": _field_count(enriched, "engineering_work_lane"),
                "opportunity_priority_class": _field_count(enriched, "opportunity_priority_class"),
                "expected_responsible_role_present": _field_count(enriched, "expected_responsible_role_present"),
                "primary_responsible_person_name": _field_count(enriched, "primary_responsible_person_name"),
                "chief_supervision_engineer_name": _field_count(enriched, "chief_supervision_engineer_name"),
                "design_lead_name": _field_count(enriched, "design_lead_name"),
                "survey_lead_name": _field_count(enriched, "survey_lead_name"),
                "project_manager_name": _field_count(enriched, "project_manager_name"),
                "project_manager_certificate_no": _field_count(enriched, "project_manager_certificate_no"),
                "project_manager_certificate_type": _field_count(enriched, "project_manager_certificate_type"),
                "project_manager_cert_specialty": _field_count(enriched, "project_manager_cert_specialty"),
                "detail_project_manager_name": _detail_field_count(enriched, "project_manager_name"),
                "detail_project_manager_certificate_no": _detail_field_count(
                    enriched, "project_manager_certificate_no"
                ),
                "attachment_ocr_required_count_total": sum(
                    _as_int(row.get("attachment_ocr_required_count")) for row in enriched
                ),
                "attachment_ocr_extracted_count_total": sum(
                    _as_int(row.get("attachment_ocr_extracted_count")) for row in enriched
                ),
            },
            "priority_class_counts": _status_counts(enriched, "opportunity_priority_class"),
            "responsible_role_gap_counts": _status_counts(enriched, "responsible_role_gap_code"),
            "sample_candidates": _sample_candidate_rows(enriched),
        },
        "stage4": {
            "attempted_count": (result.get("search_scope") or {}).get("stage1_6_attempted_count")
            if isinstance(result.get("search_scope"), Mapping)
            else None,
            "pending_count": (result.get("search_scope") or {}).get("stage1_6_pending_count")
            if isinstance(result.get("search_scope"), Mapping)
            else None,
            "hard_defect_gate_states": _status_counts(closed, "real_world_hard_defect_gate_state"),
            "identity_resolution_required_count": sum(
                1 for row in readbacks if row.get("jzsc_company_first_identity_resolution_required")
            ),
            "fail_reason_counts": dict(fail_reasons.most_common(30)),
            "remaining_gap_counts": dict(remaining_gaps.most_common(30)),
        },
        "stage5": {
            "rule_gate_counts": _status_counts(readbacks, "stage5_rule_gate_status"),
            "evidence_gate_counts": _status_counts(readbacks, "stage5_evidence_gate_status"),
        },
        "stage6": {
            "package_chain_state_counts": _status_counts(
                readbacks, "stage6_real_public_product_package_chain_state"
            ),
            "stage1_6_chain_state_counts": _status_counts(closed, "real_public_stage1_6_chain_state"),
            "closed_loop_ready_count": sum(1 for row in closed if row.get("stage1_6_closed_loop_ready")),
            "evidence_readback_ready_count": (
                (ledger.get("stage_counts") or [{} for _ in range(6)])[5].get("evidence_readback_ready_count")
                if isinstance(ledger, Mapping) and len(ledger.get("stage_counts") or []) >= 6
                else None
            ),
        },
        "ledger": ledger,
    }
    if full:
        summary["raw_result"] = result
    return summary


payload = json.loads(os.environ["KAKA_GD_STAGE16_PAYLOAD_JSON"])
payload.setdefault("now", datetime.now(timezone.utc).isoformat())
full = os.environ.get("KAKA_GD_STAGE16_FULL", "").lower() in {"1", "true", "yes", "on"}
result = run_operator_autonomous_opportunity_search(payload)
summary = build_summary(result, payload=payload, full=full)
print(json.dumps(summary, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $env:KAKA_GD_STAGE16_PAYLOAD_JSON = $payloadJson
    $env:KAKA_GD_STAGE16_FULL = if ($Full) { "1" } else { "0" }
    $output = python -X utf8 -c $python
    if ($OutputPath) {
        $resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
            $OutputPath
        }
        else {
            Join-Path $repoRoot $OutputPath
        }
        $output | Set-Content -LiteralPath $resolvedOutput -Encoding utf8NoBOM
    }
    $output
}
finally {
    Remove-Item Env:KAKA_GD_STAGE16_PAYLOAD_JSON -ErrorAction SilentlyContinue
    Remove-Item Env:KAKA_GD_STAGE16_FULL -ErrorAction SilentlyContinue
    Pop-Location
}
