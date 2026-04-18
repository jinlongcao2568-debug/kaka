[CmdletBinding()]
param(
    [string]$RepoRoot,
    [string]$CaseId,
    [switch]$EmitJson,
    [switch]$Quiet
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-RepoRoot {
    param([string]$Provided)
    if ($Provided) { return (Resolve-Path $Provided).Path }
    $scriptDir = Split-Path -Parent $PSCommandPath
    return (Resolve-Path (Join-Path $scriptDir '..')).Path
}

function Fail($msg) {
    Write-Error $msg
    exit 1
}

function Add-CaseIssue {
    param(
        [ref]$Bag,
        [string]$CaseId,
        [string]$Message
    )

    $Bag.Value.Add([pscustomobject]@{
        severity = 'ERROR'
        caseId   = $CaseId
        message  = $Message
    }) | Out-Null
}

function Find-PythonCommand {
    foreach ($candidate in @(
        @{ executable = 'python'; arguments = @() },
        @{ executable = 'py'; arguments = @('-3') },
        @{ executable = 'py'; arguments = @() }
    )) {
        if (Get-Command $candidate.executable -ErrorAction SilentlyContinue) {
            return [pscustomobject]$candidate
        }
    }

    return $null
}

function Invoke-Stage89RuntimeGoldens {
    param(
        [string]$Root,
        [string[]]$CaseIds,
        [ref]$Issues
    )

    $pythonCommand = Find-PythonCommand
    if (-not $pythonCommand) {
        Add-CaseIssue -Bag $Issues -CaseId 'runtime-stage8-9' -Message 'No compatible python runtime command was found (python / py -3 / py).'
        return
    }

    $pythonScript = @'
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
sys.path.insert(0, str(ROOT / "src"))

from shared.contracts_runtime import StageBundle
from shared.pipeline import run_internal_chain
from stage9_delivery.service import Stage9Service


def load_fixture(root: Path, name: str) -> dict:
    return json.loads((root / "fixtures" / name).read_text(encoding="utf-8"))


def decision_entries(trace: list[dict]) -> tuple[list[str], dict[str, dict]]:
    ordered = []
    mapped = {}
    for entry in trace:
        if not isinstance(entry, dict):
            continue
        if entry.get("event") == "emit_decision" and entry.get("policy_key"):
            ordered.append(entry["policy_key"])
        if entry.get("policy_key") and entry.get("catalog_id"):
            mapped[entry["policy_key"]] = entry
    return ordered, mapped


def runtime_payload(root: Path, case: dict) -> dict:
    fixture_name = case.get("input_profile", {}).get("fixture")
    if not fixture_name:
        raise ValueError("runtime golden case missing input_profile.fixture")
    payload = load_fixture(root, fixture_name)
    payload.update(case.get("input_profile", {}).get("overrides", {}))
    return payload


def load_policy(root: Path, relative_path: str) -> dict:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))["policies"][0]


def select_cadence_profile(policy: dict, *, urgency: str, window_urgency: int) -> dict:
    normalized_urgency = (urgency or "NORMAL").upper()
    if normalized_urgency == "CRITICAL" or window_urgency >= 90:
        profile_id = "CADENCE-CRITICAL"
    elif normalized_urgency == "HIGH" or window_urgency >= 80:
        profile_id = "CADENCE-HIGH"
    elif normalized_urgency == "LOW":
        profile_id = "CADENCE-LOW"
    else:
        profile_id = "CADENCE-NORMAL"
    return next(item for item in policy["cadence_profiles"] if item["profile_id"] == profile_id)


def select_channel_override(policy: dict, channel_family: str) -> dict:
    return next(
        (item for item in policy["channel_overrides"] if item["channel_family"] == channel_family),
        {},
    )


def select_channel_ladder(policy: dict, channel_family: str) -> dict:
    return next(item for item in policy["channel_ladders"] if item["entry_channel_family"] == channel_family)


def retry_rule(policy: dict, response_status: str) -> dict:
    return next(item for item in policy["retry_rules"] if item["response_status"] == response_status)


def validate_stage8_failure_writeback(root: Path, case: dict, issues: list[dict]) -> None:
    payload = runtime_payload(root, case)
    result = run_internal_chain(payload)
    stage8 = result["stage8"]
    touch_record = stage8.record("touch_record").data
    expected_next_step = case["expected"].get("next_step_optional")

    if touch_record.get("next_step_optional") != expected_next_step:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"touch_record.next_step_optional drift. expected={expected_next_step}, actual={touch_record.get('next_step_optional')}",
        })
    if case["expected"].get("require_written_back_at_optional") and not touch_record.get("written_back_at_optional"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "touch_record.written_back_at_optional must be present on Stage 8 failure path.",
        })
    if stage8.inputs.get("next_step_optional") != touch_record.get("next_step_optional"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage8 projected inputs must keep next_step_optional aligned with touch_record.",
        })
    if stage8.inputs.get("written_back_at_optional") != touch_record.get("written_back_at_optional"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage8 projected inputs must keep written_back_at_optional aligned with touch_record.",
        })


def validate_h08_payload_closure(root: Path, case: dict, issues: list[dict]) -> None:
    payload = runtime_payload(root, case)
    result = run_internal_chain(payload)
    stage8 = result["stage8"]
    saleable_opportunity = stage8.record("saleable_opportunity").data
    touch_record = stage8.record("touch_record").data
    expected_fields = case["expected"].get("required_payload_fields", [])
    expected_producer_objects = case["expected"].get("producer_objects", [])
    expected_projection = {
        "opportunity_id": saleable_opportunity.get("opportunity_id"),
        "touch_record_id": touch_record.get("touch_record_id"),
        "response_status": touch_record.get("response_status"),
        "saleability_status": saleable_opportunity.get("saleability_status"),
        "crm_owner_state": saleable_opportunity.get("crm_owner_state"),
    }

    if sorted(stage8.records.keys()) != sorted(expected_producer_objects):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"Stage8 producer set drift. expected={sorted(expected_producer_objects)}, actual={sorted(stage8.records.keys())}",
        })

    for field_name in expected_fields:
        if field_name not in stage8.handoff:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Stage8 handoff missing H-08 field: {field_name}",
            })
        if field_name not in stage8.inputs:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Stage8 projected inputs missing H-08 field: {field_name}",
            })

    for field_name, expected_value in expected_projection.items():
        if stage8.handoff.get(field_name) != expected_value:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"H-08 handoff field {field_name} drift. expected={expected_value}, actual={stage8.handoff.get(field_name)}",
            })
        if stage8.inputs.get(field_name) != expected_value:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Stage8 projected input field {field_name} drift. expected={expected_value}, actual={stage8.inputs.get(field_name)}",
            })


def validate_stage9_consumer_h08(root: Path, case: dict, issues: list[dict]) -> None:
    payload = runtime_payload(root, case)
    result = run_internal_chain(payload)
    stage8 = result["stage8"]
    stage9 = result["stage9"]
    saleable_opportunity = stage8.record("saleable_opportunity").data
    touch_record = stage8.record("touch_record").data
    order_record = stage9.record("order_record").data
    governance = stage9.record("governance_feedback_event").data
    outcome = stage9.record("opportunity_outcome_event").data
    stage9_service = Stage9Service()

    if order_record.get("opportunity_id") != saleable_opportunity.get("opportunity_id"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage9 order_record.opportunity_id must come from saleable_opportunity / H-08.",
        })

    for token in (
        saleable_opportunity.get("opportunity_id"),
        touch_record.get("touch_record_id"),
        touch_record.get("response_status"),
        saleable_opportunity.get("saleability_status"),
        saleable_opportunity.get("crm_owner_state"),
    ):
        if token not in governance.get("trigger_summary", ""):
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": "Stage9 governance trigger_summary must retain all H-08 critical field values.",
            })
            break

    if outcome.get("contact_failure_state") != touch_record.get("response_status"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage9 outcome.contact_failure_state must come from H-08 response_status.",
        })

    missing_saleable_bundle = StageBundle(
        stage=8,
        records={key: value for key, value in stage8.records.items() if key != "saleable_opportunity"},
        handoff=dict(stage8.handoff),
        trace_rules=list(stage8.trace_rules),
        inputs=dict(stage8.inputs),
    )
    try:
        stage9_service.run(missing_saleable_bundle)
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage9 must fail when saleable_opportunity is missing from Stage8 bundle.",
        })
    except ValueError:
        pass

    missing_h08_field_bundle = StageBundle(
        stage=8,
        records=dict(stage8.records),
        handoff={key: value for key, value in stage8.handoff.items() if key != "crm_owner_state"},
        trace_rules=list(stage8.trace_rules),
        inputs=dict(stage8.inputs),
    )
    try:
        stage9_service.run(missing_h08_field_bundle)
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": "Stage9 must fail when H-08 required payload fields are missing.",
        })
    except ValueError:
        pass


def validate_stage9_executor_coverage(root: Path, case: dict, issues: list[dict]) -> None:
    payload = runtime_payload(root, case)
    result = run_internal_chain(payload)
    stage9 = result["stage9"]
    ordered_keys, mapped = decision_entries(stage9.inputs.get("policy_trace", []))
    expected_policy_keys = case["expected"].get("policy_keys", [])
    payment_record = stage9.record("payment_record").data
    delivery_record = stage9.record("delivery_record").data

    if ordered_keys != expected_policy_keys:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"Stage9 policy sequence drift. expected={expected_policy_keys}, actual={ordered_keys}",
        })

    for key in expected_policy_keys:
        entry = mapped.get(key)
        if entry is None:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Stage9 trace missing catalog-backed decision entry for {key}.",
            })

    if payment_record.get("payment_exception_family_optional") != case["expected"].get("payment_exception_family_optional"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"payment_exception_family_optional drift. expected={case['expected'].get('payment_exception_family_optional')}, actual={payment_record.get('payment_exception_family_optional')}",
        })
    if delivery_record.get("archival_status") != case["expected"].get("archival_status"):
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"delivery_record.archival_status drift. expected={case['expected'].get('archival_status')}, actual={delivery_record.get('archival_status')}",
        })


def validate_stage9_writeback_additive(root: Path, case: dict, issues: list[dict]) -> None:
    payload = runtime_payload(root, case)
    result = run_internal_chain(payload)
    stage9 = result["stage9"]
    outcome = stage9.record("opportunity_outcome_event").data
    expected_outcome_targets = case["expected"].get("outcome_writeback_targets", [])
    expected_governance_targets = case["expected"].get("governance_writeback_targets_optional", [])
    expected_effective_targets = case["expected"].get("effective_writeback_targets", [])

    if stage9.inputs.get("outcome_writeback_targets") != expected_outcome_targets:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"outcome_writeback_targets drift. expected={expected_outcome_targets}, actual={stage9.inputs.get('outcome_writeback_targets')}",
        })
    if outcome.get("writeback_targets") != expected_outcome_targets:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"opportunity_outcome_event.writeback_targets drift. expected={expected_outcome_targets}, actual={outcome.get('writeback_targets')}",
        })
    if stage9.inputs.get("governance_writeback_targets_optional") != expected_governance_targets:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"governance_writeback_targets_optional drift. expected={expected_governance_targets}, actual={stage9.inputs.get('governance_writeback_targets_optional')}",
        })
    if stage9.inputs.get("effective_writeback_targets") != expected_effective_targets:
        issues.append({
            "severity": "ERROR",
            "caseId": case["case_id"],
            "message": f"effective_writeback_targets drift. expected={expected_effective_targets}, actual={stage9.inputs.get('effective_writeback_targets')}",
        })


def validate_stage8_cadence_ladder_alignment(root: Path, issues: list[dict]) -> None:
    cadence_policy = load_policy(root, "contracts/sales/outreach_cadence_catalog.json")
    retry_policy = load_policy(root, "contracts/sales/retry_policy_catalog.json")
    payload = load_fixture(root, "internal_chain_happy.json")
    payload.update(
        {
            "channel_family": "PERSONAL_PHONE",
            "contact_channel": "PHONE",
            "response_status": "NO_RESPONSE",
        }
    )
    stage8 = run_internal_chain(payload)["stage8"]
    trace = decision_entries(stage8.handoff.get("policy_trace", []))[1]
    cadence_outputs = trace.get("outreach_cadence", {}).get("outputs", {})
    expected_profile = select_cadence_profile(cadence_policy, urgency="NORMAL", window_urgency=50)
    expected_override = select_channel_override(cadence_policy, "PERSONAL_PHONE")
    expected_ladder = select_channel_ladder(cadence_policy, "PERSONAL_PHONE")
    expected_retry = retry_rule(retry_policy, "NO_RESPONSE")

    if stage8.record("outreach_plan").get("cadence_profile_id") != expected_profile["profile_id"]:
        issues.append({
            "severity": "ERROR",
            "caseId": "runtime-stage8-cadence-ladder",
            "message": "Stage8 cadence_profile_id drift against outreach_cadence_catalog.",
        })
    if (
        stage8.record("outreach_plan").get("retry_policy_id") != cadence_policy["retry_policy_id"]
        or stage8.record("outreach_plan").get("stop_policy_id") != cadence_policy["stop_policy_id"]
    ):
        issues.append({
            "severity": "ERROR",
            "caseId": "runtime-stage8-cadence-ladder",
            "message": "Stage8 retry/stop policy refs must come from outreach_cadence_catalog.",
        })
    if (
        stage8.record("outreach_plan").get("max_retry_count")
        != expected_override.get("max_attempts_7d", expected_profile["max_attempts_7d"])
        or stage8.record("outreach_plan").get("retry_count")
        != (1 if expected_retry["next_action"] == "RETRY" else 0)
    ):
        issues.append({
            "severity": "ERROR",
            "caseId": "runtime-stage8-cadence-ladder",
            "message": "Stage8 retry outputs drift against cadence/retry policy catalogs.",
        })
    if (
        cadence_outputs.get("channel_ladder_id") != expected_ladder["ladder_id"]
        or cadence_outputs.get("ladder_sequence") != expected_ladder["step_sequence"]
        or cadence_outputs.get("channel_fallback_sequence") != expected_ladder["fallback_sequence"]
        or cadence_outputs.get("fallback_channel_family_optional")
        != expected_ladder["fallback_sequence"][0]
        or cadence_outputs.get("ladder_sequence_mode") != expected_ladder["sequence_mode"]
        or cadence_outputs.get("live_execution_enabled") is not False
    ):
        issues.append({
            "severity": "ERROR",
            "caseId": "runtime-stage8-cadence-ladder",
            "message": "Stage8 outreach_cadence trace must expose catalog-defined ladder/fallback sequence without live execution enablement.",
        })


CHECKS = {
    "STAGE8_FAILURE_WRITEBACK": validate_stage8_failure_writeback,
    "H08_PAYLOAD_CLOSURE": validate_h08_payload_closure,
    "STAGE9_CONSUMER_H08": validate_stage9_consumer_h08,
    "STAGE9_EXECUTOR_COVERAGE": validate_stage9_executor_coverage,
    "STAGE9_WRITEBACK_ADDITIVE": validate_stage9_writeback_additive,
}


def main() -> int:
    root = Path(sys.argv[1]).resolve()
    selected_ids = {item for item in sys.argv[2].split(",") if item} if len(sys.argv) > 2 else set()
    case_path = root / "contracts" / "testing" / "golden_cases.json"
    all_cases = json.loads(case_path.read_text(encoding="utf-8"))["cases"]

    runtime_cases = [
        case for case in all_cases
        if case.get("expected", {}).get("runtime_check_id")
        and (not selected_ids or case["case_id"] in selected_ids)
    ]

    issues: list[dict] = []
    for case in runtime_cases:
        runtime_check_id = case["expected"].get("runtime_check_id")
        check = CHECKS.get(runtime_check_id)
        if check is None:
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Unsupported runtime_check_id: {runtime_check_id}",
            })
            continue
        try:
            check(root, case, issues)
        except Exception as exc:  # pragma: no cover - defensive gate
            issues.append({
                "severity": "ERROR",
                "caseId": case["case_id"],
                "message": f"Runtime golden execution failed: {exc}",
            })

    try:
        validate_stage8_cadence_ladder_alignment(root, issues)
    except Exception as exc:  # pragma: no cover - defensive gate
        issues.append({
            "severity": "ERROR",
            "caseId": "runtime-stage8-cadence-ladder",
            "message": f"Stage8 cadence ladder golden execution failed: {exc}",
        })

    print(json.dumps({"issues": issues, "executed": len(runtime_cases)}, ensure_ascii=False))
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
'@

    $tempPython = [System.IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tempPython -Value $pythonScript -Encoding UTF8
        Push-Location $Root
        $pythonArgs = @($pythonCommand.arguments + @($tempPython, $Root, ($CaseIds -join ',')))
        $pythonOutput = & $pythonCommand.executable @pythonArgs 2>&1
        if ($LASTEXITCODE -ne 0) {
            Add-CaseIssue -Bag $Issues -CaseId 'runtime-stage8-9' -Message "Stage8-9 runtime golden runner failed: $($pythonOutput -join ' ')"
            return
        }

        $raw = ($pythonOutput -join [Environment]::NewLine)
        $jsonStart = $raw.IndexOf('{')
        if ($jsonStart -lt 0) {
            Add-CaseIssue -Bag $Issues -CaseId 'runtime-stage8-9' -Message 'Stage8-9 runtime golden runner did not emit JSON.'
            return
        }

        $parsed = $raw.Substring($jsonStart) | ConvertFrom-Json -Depth 50
        foreach ($issue in @($parsed.issues)) {
            $Issues.Value.Add($issue) | Out-Null
        }
    }
    finally {
        Pop-Location -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tempPython -Force -ErrorAction SilentlyContinue
    }
}

$root = Resolve-RepoRoot -Provided $RepoRoot
$path = Join-Path $root 'contracts/testing/golden_cases.json'
if (-not (Test-Path -LiteralPath $path)) { Fail "golden cases file not found: $path" }

try {
    $cases = (Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json -Depth 100)
}
catch {
    Fail "Failed to parse golden cases JSON: $($_.Exception.Message)"
}

if (-not ($cases.PSObject.Properties.Name -contains 'cases')) { Fail 'golden_cases.json must contain top-level key: cases' }

$selected = @($cases.cases)
if ($CaseId) {
    $selected = @($cases.cases | Where-Object case_id -eq $CaseId)
    if ($selected.Count -eq 0) { Fail "Golden case not found: $CaseId" }
}

$issues = [System.Collections.Generic.List[object]]::new()
foreach ($case in $selected) {
    foreach ($key in @('case_id','capability_id','capability_tier','target_stage','input_profile','expected','source_refs')) {
        if (-not ($case.PSObject.Properties.Name -contains $key)) {
            $issues.Add([pscustomobject]@{ severity='ERROR'; caseId=$case.case_id; message="Missing key: $key" }) | Out-Null
        }
    }

    $expected = $case.expected
    if ($expected) {
        $expectedProps = @($expected.PSObject.Properties.Name)
        $resultType = if ($expectedProps -contains 'result_type') { $expected.result_type } else { $null }
        $ruleGate = if ($expectedProps -contains 'rule_gate_status') { $expected.rule_gate_status } else { $null }
        $evidenceGate = if ($expectedProps -contains 'evidence_gate_status') { $expected.evidence_gate_status } else { $null }

        if ($resultType -eq 'AUTO_HIT' -and ($ruleGate -ne 'PASS' -or $evidenceGate -ne 'PASS')) {
            $issues.Add([pscustomobject]@{ severity='ERROR'; caseId=$case.case_id; message='AUTO_HIT cases must expect rule/evidence PASS.' }) | Out-Null
        }
        if ($resultType -eq 'BLOCK' -and ($ruleGate -ne 'BLOCK' -and $evidenceGate -ne 'BLOCK')) {
            $issues.Add([pscustomobject]@{ severity='ERROR'; caseId=$case.case_id; message='BLOCK cases must include at least one BLOCK gate.' }) | Out-Null
        }
    }
}

$runtimeCases = @($selected | Where-Object {
    $_.expected -and ($_.expected.PSObject.Properties.Name -contains 'runtime_check_id')
})
foreach ($case in $runtimeCases) {
    if (-not ($case.input_profile.PSObject.Properties.Name -contains 'fixture')) {
        Add-CaseIssue -Bag ([ref]$issues) -CaseId $case.case_id -Message 'Runtime golden case must declare input_profile.fixture.'
    }
}
if ($runtimeCases.Count -gt 0) {
    Invoke-Stage89RuntimeGoldens -Root $root -CaseIds @($runtimeCases | ForEach-Object case_id) -Issues ([ref]$issues)
}

$result = [pscustomobject]@{
    script = 'run-golden.ps1'
    repoRoot = $root
    selectedCount = $selected.Count
    runtimeCaseCount = $runtimeCases.Count
    ok = (@($issues | Where-Object severity -eq 'ERROR').Count -eq 0)
    issues = $issues
}

if (-not $Quiet -and -not $EmitJson) {
    Write-Host "[run-golden] repo: $root"
    Write-Host "[run-golden] cases: $($selected.Count)"
    if ($issues.Count -eq 0) {
        Write-Host '[run-golden] PASS'
    } else {
        foreach ($issue in $issues) {
            Write-Host ("[{0}] {1}: {2}" -f $issue.severity, $issue.caseId, $issue.message)
        }
    }
}

if ($EmitJson) {
    $result | ConvertTo-Json -Depth 20
}

if (-not $result.ok) { exit 1 }
exit 0
