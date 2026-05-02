param(
    [switch]$Compact
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$repoRoot = Split-Path -Parent $PSScriptRoot

$python = @'
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

ROOT = Path.cwd()
for search_path in (ROOT / "src", ROOT / "tests"):
    if str(search_path) not in sys.path:
        sys.path.insert(0, str(search_path))

from helpers import load_fixture
from shared.settings import Settings
from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage2_ingestion.real_public_url_fetcher import (
    REAL_PUBLIC_ENTRY_PROFILE_BY_ID,
    RealPublicFetchResponse,
)
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from storage.db import DatabaseSession
from storage.repositories.object_storage_repo import ObjectStorageRepository


def field(name: str, value: str, confidence: float = 0.91) -> dict:
    return {
        "field_name": name,
        "field_value_optional": value,
        "source_file_ref": "SNAP-STAGE45-TRACE",
        "source_slice": f"{name}: {value}",
        "source_slice_sha256": f"SHA-STAGE45-{name}",
        "confidence": confidence,
        "parser_version": "stage3-real-parser-v1",
        "review_required": False,
    }


def verification_carrier(
    name: str,
    target_type: str,
    *,
    role: str | None = None,
    extra: dict | None = None,
) -> dict:
    source_url = f"https://example.invalid/stage45-trace/{name}.html"
    snapshot_id = f"SNAP-STAGE45-{name.upper()}"
    carrier = {
        "verification_run_id": f"ST4PV-STAGE45-{name}",
        "verification_target_id": f"TARGET-STAGE45-{name}",
        "verification_target_type": target_type,
        "source_snapshot_id": snapshot_id,
        "source_url": source_url,
        "public_visibility_state": "PUBLIC_VISIBLE",
        "verification_provider": "stage4-public-verification-readback",
        "verification_result": "MATCHED",
        "evidence_grade": "PUBLIC_SNAPSHOT_FIELD_MATCH",
        "confidence": 0.92,
        "review_required": False,
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
        "source_refs": [
            {
                "source_url": source_url,
                "source_snapshot_id": snapshot_id,
                "public_visibility_state": "PUBLIC_VISIBLE",
            }
        ],
        "snapshot_refs": [{"snapshot_id": snapshot_id, "replayable": True}],
    }
    if role:
        carrier["verification_role"] = role
    if extra:
        carrier.update(extra)
    return carrier


class ControlledRealPublicFetchTransport:
    def __init__(self, responses: dict[str, RealPublicFetchResponse]) -> None:
        self.responses = responses
        self.call_log: list[dict] = []

    def fetch(
        self,
        url: str,
        *,
        timeout_seconds: float,
        user_agent: str,
    ) -> RealPublicFetchResponse:
        self.call_log.append(
            {
                "url": url,
                "timeout_seconds": timeout_seconds,
                "user_agent": user_agent,
            }
        )
        return self.responses[url]


def object_storage_repo(tmp_dir: str) -> ObjectStorageRepository:
    settings = Settings(
        storage_backend="json-file",
        storage_path_optional=str(Path(tmp_dir) / "stage45-real-public-trace.json"),
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(Path(tmp_dir) / "objects"),
    )
    return ObjectStorageRepository(
        session=DatabaseSession(settings=settings),
        settings=settings,
    )


def real_public_rule_html(*, profile_id: str, target_type: str, identifier: str) -> bytes:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID[profile_id]
    marker_text = " ".join(profile.visible_entry_markers or profile.lightweight_public_entry_markers)
    filler = "公开规则证据入口" * 80
    html = f"""
    <html>
      <head>
        <title>{profile.expected_title_contains} - {profile.site_name}</title>
        <meta name="description" content="{marker_text}">
      </head>
      <body>
        <h1>{profile.expected_title_contains}</h1>
        <p>{marker_text}</p>
        <p>{filler}</p>
        <table>
          <tr><th>项目名称</th><td>{identifier}</td></tr>
          <tr><th>招标人</th><td>{profile.site_name} 测试主体</td></tr>
          <tr><th>公告日期</th><td>2026-04-28</td></tr>
          <tr><th>{target_type}</th><td>{identifier}</td></tr>
        </table>
        <a href="{profile.sample_detail_url}">公开详情样例</a>
      </body>
    </html>
    """
    return html.encode("utf-8")


def build_real_public_snapshot_to_stage5_trace(base_stage4: StageBundle) -> dict:
    profile = REAL_PUBLIC_ENTRY_PROFILE_BY_ID["GGZY-DEAL-LIST"]
    target_type = "enterprise_public_record"
    identifier = "REAL-PUBLIC-STAGE45-VERIFY-001"

    with tempfile.TemporaryDirectory() as tmp_dir:
        repo = object_storage_repo(tmp_dir)
        transport = ControlledRealPublicFetchTransport(
            {
                profile.url: RealPublicFetchResponse(
                    url=profile.url,
                    status_code=200,
                    content=real_public_rule_html(
                        profile_id=profile.profile_id,
                        target_type=target_type,
                        identifier=identifier,
                    ),
                    content_type="text/html; charset=utf-8",
                    final_url=profile.url,
                    headers={"x-ax9s-fetch-transport": "stage45_controlled_transport"},
                )
            }
        )
        stage2_carrier = dict(
            Stage2Service().fetch_real_public_entry_url(
                profile.url,
                profile_id=profile.profile_id,
                repository=repo,
                transport=transport,
                lineage_refs={
                    "trace_id": "stage45-real-public-snapshot-to-stage5",
                    "entry_profile_id": profile.profile_id,
                },
            )
        )
        parsed = dict(
            Stage3Service().parse_raw_snapshot(
                stage2_carrier["snapshot_id_optional"],
                repository=repo,
            )
        )
        stage4_verification = dict(
            Stage4Service().verify_public_parsed_carrier(
                parsed,
                target={
                    "verification_target_id": f"TARGET-{target_type}-STAGE45",
                    "verification_target_type": target_type,
                    "target_identifier": identifier,
                },
                repository=repo,
            )
        )
        stage5_real_public = Stage5Service().run_public_verification_readback(
            base_stage4,
            stage4_verification,
            requested_rule_codes=["DOC-001"],
        )
        return {
            "profile_id": profile.profile_id,
            "source_url": profile.url,
            "fetch_calls": transport.call_log,
            "stage2": {
                "status": stage2_carrier.get("status"),
                "fetch_result": stage2_carrier.get("fetch_result"),
                "snapshot_id": stage2_carrier.get("snapshot_id_optional"),
                "source_url": stage2_carrier.get("source_url"),
                "fail_closed": stage2_carrier.get("fail_closed"),
                "failure_reason": stage2_carrier.get("failure_reason_optional"),
            },
            "stage3": {
                "parse_run_id": parsed.get("parse_run_id"),
                "snapshot_id": parsed.get("snapshot_id"),
                "parsed_field_count": len(parsed.get("parsed_fields") or []),
                "field_names": [
                    item.get("field_name")
                    for item in parsed.get("parsed_fields", [])
                    if item.get("field_name")
                ],
            },
            "stage4": {
                "verification_run_id": stage4_verification.get("verification_run_id"),
                "verification_target_type": stage4_verification.get("verification_target_type"),
                "verification_result": stage4_verification.get("verification_result"),
                "readback_state": Stage4Service().build_public_verification_readback(
                    stage4_verification
                ).get("readback_state"),
                "source_snapshot_id": stage4_verification.get("source_snapshot_id"),
                "input_parse_run_id": stage4_verification.get("input_parse_run_id"),
            },
            "stage5": {
                "rule_gate_status": stage5_real_public.record("rule_gate_decision").get("rule_gate_status"),
                "evidence_gate_status": stage5_real_public.record("evidence_gate_decision").get("evidence_gate_status"),
                "selected_rule_codes": stage5_real_public.inputs.get("stage5_rule_codes"),
                "stage4_public_verification_refs": stage5_real_public.inputs.get(
                    "stage4_public_verification_refs"
                ),
            },
        }


def conflict_project() -> dict:
    return {
        "project_id": "PRJ-STAGE45-CONFLICT-001",
        "project_name": "Earlier bridge works",
        "registered_unit_name": "Alpha Construction Co",
        "project_manager_name": "陈庆丽",
        "project_manager_public_identifier_optional": "鲁1372017201820810",
        "contract_time_window": {"start_at": "2026-03-01", "end_at": "2026-08-31"},
        "completion_acceptance_status": "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
        "verification_carriers": [
            verification_carrier("conflict-project", "performance_public_record"),
            verification_carrier("conflict-contract", "contract_public_info"),
            verification_carrier("conflict-completion", "completion_filing"),
        ],
    }


stage4_service = Stage4Service()
stage5_service = Stage5Service()

parsed_context = {
    "parse_run_id": "PARSE-STAGE45-TRACE",
    "snapshot_id": "SNAP-STAGE45-TRACE",
    "source_url": "https://example.invalid/stage45-trace/current-notice.html",
    "lineage_status": "NORMALIZED",
    "conflict_state": "CONSISTENT",
    "current_project_time_window": {"start_at": "2026-05-01", "end_at": "2026-10-01"},
    "parsed_fields": [
        field("project_id", "PRJ-STAGE45-CURRENT-001"),
        field("project_name", "Current municipal road project"),
        field("bidder_name", "Alpha Construction Co"),
        field("candidate_company_name", "Alpha Construction Co"),
        field("project_manager_name", "陈庆丽"),
        field("project_manager_registration_at", "2026-06-15"),
        field("project_manager_certificate_valid_until", "2026-07-01"),
        field("procedure_timeline_marker", "NOTICE-CLOCK-STAGE45"),
    ],
}

rendered_jzsc_personnel_rows = [
    {"row_text": "1 郭敏锋 350600**********39 注册监理工程师 35014418"},
    {"row_text": "2 郭敏锋 350600**********39 二级注册建造师 闽2352012201356897"},
    {
        "row_text": "5 陈庆丽 372929**********69 一级注册建造师 鲁1372017201820810",
        "detail_url": "https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
        "person_public_id": "person-chen-qingli",
        "registered_unit_name": "Alpha Construction Co",
        "registration_at": "2026-06-15",
        "certificate_valid_until": "2026-07-01",
    },
    {"row_text": "6 仓强芝 320923**********30 注册电气工程师（供配电） 3202873-DG009"},
]
rendered_jzsc_personnel_project_rows = [
    {
        "row_no": 1,
        "project_id": "PRJ-STAGE45-CONFLICT-001",
        "project_name": "Earlier bridge works",
        "registered_unit_name": "Alpha Construction Co",
        "project_manager_name": "陈庆丽",
        "registration_no": "鲁1372017201820810",
        "contract_start_at": "2026-03-01",
        "contract_end_at": "2026-08-31",
        "completion_acceptance_status": "NO_PUBLIC_COMPLETION_ACCEPTANCE_PROOF",
        "detail_url": "https://jzsc.mohurd.gov.cn/data/project/detail?id=stage45-conflict",
    }
]

registered_unit_carrier = verification_carrier(
    "registered-unit",
    "enterprise_public_record",
    role="registered_unit_verification",
)
jzsc_company_first_bundle = stage4_service.build_jzsc_project_manager_company_first_readback(
    parsed_context,
    target_company_name="Alpha Construction Co",
    target_project_manager_name="陈庆丽",
    rendered_company_personnel_rows=rendered_jzsc_personnel_rows,
    company_personnel_source_url="https://jzsc.mohurd.gov.cn/data/company/detail?id=alpha",
    company_personnel_source_snapshot_id="SNAP-JZSC-RENDERED-PERSON-TRACE",
    rendered_personnel_project_rows=rendered_jzsc_personnel_project_rows,
    personnel_project_source_url="https://jzsc.mohurd.gov.cn/data/person/detail?id=person-chen-qingli",
    personnel_project_source_snapshot_id="SNAP-JZSC-PERSON-PROJECTS-TRACE",
    base_public_verification_carriers=[registered_unit_carrier],
)
manager_personnel_carrier = jzsc_company_first_bundle["personnel_carrier"]
conflict_records = jzsc_company_first_bundle["conflict_records"]
strategy = jzsc_company_first_bundle["evidence_risk_hard_defect_strategy"]
active_conflict = jzsc_company_first_bundle["project_manager_active_conflict"]
active_conflict_readback = jzsc_company_first_bundle["project_manager_active_conflict_readback"]

base_stage4 = run_internal_chain(load_fixture("internal_chain_happy.json"))["stage4"]
real_public_snapshot_to_stage5 = build_real_public_snapshot_to_stage5_trace(base_stage4)
stage4_for_stage5 = StageBundle(
    stage=4,
    records=dict(base_stage4.records),
    handoff=dict(base_stage4.handoff),
    trace_rules=list(base_stage4.trace_rules),
    inputs={
        **base_stage4.inputs,
        "project_manager_id_optional": "PM-STAGE45-TRACE",
        "stage5_rule_confidence": 0.92,
    },
)
stage5 = stage5_service.run_evidence_risk_hard_defect_strategy_readback(
    stage4_for_stage5,
    strategy,
    project_manager_active_conflict_readback=active_conflict_readback,
)

review_request = None
if "review_request" in stage5.records:
    review_request = dict(stage5.record("review_request").data)

trace = {
    "trace_id": "stage45-real-slice-local",
    "stage4_jzsc_route": {
        "route": jzsc_company_first_bundle.get("route"),
        "resolved_public_identifier_optional": jzsc_company_first_bundle.get(
            "resolved_public_identifier_optional"
        ),
        "capture_plan_id": jzsc_company_first_bundle.get("capture_plan", {}).get(
            "capture_plan_id"
        ),
        "capture_step_count": len(
            jzsc_company_first_bundle.get("capture_plan", {}).get("capture_steps", [])
        ),
        "browser_required": jzsc_company_first_bundle.get("capture_plan", {}).get(
            "browser_required"
        ),
        "company_first_required": jzsc_company_first_bundle.get("capture_plan", {})
        .get("stable_identity_key_policy", {})
        .get("company_first_required"),
        "next_required_runtime_adapter": jzsc_company_first_bundle.get(
            "next_required_runtime_adapter"
        ),
    },
    "stage4_strategy": {
        "strategy_run_id": strategy.get("strategy_run_id"),
        "evidence_risk_state": strategy.get("evidence_risk_state"),
        "fail_closed_reasons": strategy.get("fail_closed_reasons"),
        "evidence_risk_taxonomy": strategy.get("evidence_risk_taxonomy"),
        "stage5_requested_rule_codes": strategy.get("stage5_requested_rule_codes"),
        "strategy_targets": [
            {
                "strategy_key": item.get("strategy_key"),
                "required_public_verifications": item.get("required_public_verifications"),
            }
            for item in strategy.get("strategy_targets", [])
        ],
        "verification_targets": [
            {
                "target_type": item.get("verification_target_type"),
                "target_identifier": item.get("target_identifier"),
                "missing_identifier": item.get("missing_identifier"),
            }
            for item in strategy.get("verification_targets", [])
        ],
    },
    "stage4_project_manager": {
        "overlap_judgement": active_conflict.get("overlap_judgement"),
        "failure_reasons": active_conflict.get("failure_reasons"),
        "identity_resolution": active_conflict.get("manager_identity_resolution"),
        "registration_timeline": active_conflict.get("registration_timeline_verification"),
        "readback_state": active_conflict_readback.get("readback_state"),
        "readback_failure_reasons": active_conflict_readback.get("failure_reasons"),
        "conflicting_project_count": len(active_conflict.get("possible_conflicting_projects") or []),
        "conflict_project_sources": [
            {
                "project_id": item.get("project_id"),
                "project_name": item.get("project_name"),
                "public_evidence_ref_count": len(item.get("public_evidence_refs") or []),
                "overlap_with_current": item.get("overlap_with_current"),
            }
            for item in active_conflict.get("possible_conflicting_projects", [])
        ],
    },
    "stage5": {
        "rule_gate_status": stage5.record("rule_gate_decision").get("rule_gate_status"),
        "evidence_gate_status": stage5.record("evidence_gate_decision").get("evidence_gate_status"),
        "selected_rule_codes": stage5.inputs.get("stage5_rule_codes"),
        "coverage_summary": stage5.inputs.get("stage5_rule_coverage_summary"),
        "execution_trace": [
            {
                "rule_code": item.get("rule_code"),
                "rule_gate_status": item.get("rule_gate_status"),
                "rule_hit_state": item.get("rule_hit_state"),
                "blocking_reasons": item.get("blocking_reasons"),
                "dependency_evidence": item.get("dependency_evidence"),
                "review_request_target_selected": item.get("review_request_target_selected"),
            }
            for item in stage5.inputs.get("stage5_rule_execution_trace", [])
        ],
        "review_request": review_request,
    },
    "real_public_snapshot_to_stage5": real_public_snapshot_to_stage5,
}

print(json.dumps(trace, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $output = python -X utf8 -c $python
    if ($Compact) {
        $output | python -X utf8 -c "import json,sys; sys.stdout.reconfigure(encoding='utf-8'); print(json.dumps(json.load(sys.stdin), ensure_ascii=False, separators=(',', ':')))"
    }
    else {
        $output
    }
}
finally {
    Pop-Location
}
