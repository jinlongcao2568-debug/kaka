from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


REPORT_KIND = "PRODUCT_VALUE_ACCEPTANCE_V1"
REPORT_VERSION = 1
CONTRACT_REF = "contracts/evaluation/product_value_acceptance_contract.json"
EXPECTED_SCOREBOARD_KIND = "stage1_6_sellable_scoreboard_v1"
EXPECTED_DENOMINATOR_KIND = "REAL_PUBLIC_CANDIDATES"
EMPTY_DENOMINATOR_KIND = "NO_CANDIDATES"
EXPECTED_LINEAGE_STATE = "CLEAN_BATCH_OR_DIRECT_STAGE1_6"
OBSERVED = "OBSERVED"
WITHHELD_MISSING_INPUT = "WITHHELD_MISSING_INPUT"
WITHHELD_INCOMPLETE_WINDOW = "WITHHELD_INCOMPLETE_WINDOW"
WITHHELD_INVALID_COHORT = "WITHHELD_INVALID_COHORT"
NOT_APPLICABLE_NO_CANDIDATES = "NOT_APPLICABLE_NO_CANDIDATES"
REFUND_STATES = {"REQUESTED", "APPROVED", "COMPLETED"}
NON_REAL_MODE_TOKENS = ("PREVIEW", "DRY_RUN", "SANDBOX", "FIXTURE", "SAMPLE")


def build_product_value_acceptance(
    scoreboard_payload: Mapping[str, Any],
    *,
    observations: Mapping[str, Any] | None = None,
    run_result_payload: Mapping[str, Any] | None = None,
    scoreboard_ref: str = "",
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build an internal-only value report for one clean Stage1-6 cohort.

    Missing observation files are withheld, never silently converted to zero.
    All project rates except discovery use the scoreboard's fixed candidate
    denominator. Discovery retains its own upstream source-item denominator.
    """

    scoreboard_document = _mapping(scoreboard_payload)
    scoreboard = _mapping(scoreboard_document.get("scoreboard"))
    project_rows = _mapping_list(scoreboard_document.get("project_rows"))
    observation_payload = _mapping(observations)
    created = created_at or datetime.now(timezone.utc).isoformat()
    candidate_count = _nonnegative_int(scoreboard.get("candidate_count"), "scoreboard.candidate_count")
    cohort_gate = _cohort_gate(scoreboard_document, scoreboard, project_rows, candidate_count)
    cohort_project_ids = _project_ids(project_rows)
    fixed_denominator = candidate_count
    if not _mapping(observation_payload.get("discovery")) and run_result_payload:
        derived = _derive_discovery_observation(
            _mapping(run_result_payload),
            cohort_project_ids=cohort_project_ids,
            candidate_count=candidate_count,
        )
        observation_payload = {**observation_payload, **derived}
    observation_window = _observation_window(observation_payload)

    if cohort_gate["state"] != "PASS":
        metrics = _withheld_metrics_for_invalid_cohort(cohort_gate["blocking_reasons"])
        report_state = "BLOCKED_INVALID_COHORT"
    elif fixed_denominator == 0:
        metrics = _metrics_for_empty_cohort(
            discovery_metric=_discovery_metric(observation_payload, fixed_denominator, observation_window)
        )
        report_state = (
            "NO_CANDIDATES_OBSERVED"
            if metrics["discovery_rate"]["state"] == OBSERVED
            else "NO_CANDIDATES_INCOMPLETE"
        )
    else:
        metrics = {
            "discovery_rate": _discovery_metric(observation_payload, fixed_denominator, observation_window),
            "stage4_ready_rate": _stage4_ready_metric(project_rows, fixed_denominator),
            "reviewable_rate": _reviewable_metric(project_rows, fixed_denominator),
            "evidence_bundle_rate": _evidence_bundle_metric(
                observation_payload,
                cohort_project_ids=cohort_project_ids,
                denominator=fixed_denominator,
                observation_window=observation_window,
            ),
            "human_review_minutes": _human_review_metric(
                observation_payload,
                cohort_project_ids=cohort_project_ids,
                denominator=fixed_denominator,
                observation_window=observation_window,
            ),
            "final_adoption": _adoption_metric(
                observation_payload,
                cohort_project_ids=cohort_project_ids,
                denominator=fixed_denominator,
                observation_window=observation_window,
            ),
            "refund": _refund_metric(
                observation_payload,
                cohort_project_ids=cohort_project_ids,
                denominator=fixed_denominator,
                observation_window=observation_window,
            ),
        }
        report_state = (
            "FULLY_OBSERVED"
            if all(metric.get("state") == OBSERVED for metric in metrics.values())
            else "PARTIALLY_OBSERVED"
        )

    report = {
        "report_kind": REPORT_KIND,
        "report_version": REPORT_VERSION,
        "contract_ref": CONTRACT_REF,
        "created_at": created,
        "report_state": report_state,
        "acceptance_decision": (
            "READY_FOR_THRESHOLD_DECISION"
            if report_state == "FULLY_OBSERVED"
            else "INSUFFICIENT_OBSERVATION"
        ),
        "cohort": {
            "scoreboard_ref": scoreboard_ref,
            "scoreboard_sha256": _fingerprint(scoreboard_document),
            "scoreboard_kind": str(scoreboard_document.get("scoreboard_kind") or ""),
            "candidate_count": candidate_count,
            "unique_project_row_count": len(cohort_project_ids),
            "fixed_denominator_kind": str(scoreboard.get("denominator_kind") or ""),
            "input_mode": str(scoreboard.get("input_mode") or ""),
            "projection_or_merge_state": str(scoreboard.get("projection_or_merge_state") or ""),
            "clean_batch_comparable": bool(scoreboard.get("clean_batch_comparable", False)),
            "gate": cohort_gate,
        },
        "metrics": metrics,
        "observation_summary": {
            "observed_metric_count": sum(1 for metric in metrics.values() if metric.get("state") == OBSERVED),
            "withheld_metric_count": sum(1 for metric in metrics.values() if str(metric.get("state", "")).startswith("WITHHELD")),
            "not_applicable_metric_count": sum(
                1 for metric in metrics.values() if metric.get("state") == NOT_APPLICABLE_NO_CANDIDATES
            ),
            "thresholds_defined": False,
            "threshold_decision_made": False,
            "observation_window": observation_window,
        },
        "safety": {
            "internal_only": True,
            "customer_visible_allowed": False,
            "missing_data_reported_as_zero": False,
            "task_count_used_as_project_denominator": False,
            "followup_or_projection_accepted": False,
            "no_legal_or_financial_conclusion": True,
        },
    }
    report["report_sha256"] = _fingerprint(report)
    return report


def build_product_value_acceptance_from_files(
    *,
    scoreboard_json: str | Path,
    observations_json: str | Path | None = None,
    run_result_json: str | Path | None = None,
    output_json: str | Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    scoreboard_path = Path(scoreboard_json).resolve()
    scoreboard_payload = _read_json_mapping(scoreboard_path)
    observations: Mapping[str, Any] | None = None
    if observations_json:
        observations = _read_json_mapping(Path(observations_json).resolve())
    run_result: Mapping[str, Any] | None = None
    if run_result_json:
        run_result = _read_json_mapping(Path(run_result_json).resolve())
    report = build_product_value_acceptance(
        scoreboard_payload,
        observations=observations,
        run_result_payload=run_result,
        scoreboard_ref=str(scoreboard_path),
        created_at=created_at,
    )
    if output_json:
        output_path = Path(output_json).resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _cohort_gate(
    document: Mapping[str, Any],
    scoreboard: Mapping[str, Any],
    project_rows: Sequence[Mapping[str, Any]],
    candidate_count: int,
) -> dict[str, Any]:
    reasons: list[str] = []
    scoreboard_kind = str(document.get("scoreboard_kind") or "")
    if scoreboard_kind != EXPECTED_SCOREBOARD_KIND:
        reasons.append(f"scoreboard_kind_must_equal:{EXPECTED_SCOREBOARD_KIND}")
    if scoreboard.get("clean_batch_comparable") is not True:
        reasons.append("clean_batch_comparable_must_be_true")
    expected_denominator_kind = EXPECTED_DENOMINATOR_KIND if candidate_count > 0 else EMPTY_DENOMINATOR_KIND
    if str(scoreboard.get("denominator_kind") or "") != expected_denominator_kind:
        reasons.append(f"denominator_kind_must_equal:{expected_denominator_kind}")
    if str(scoreboard.get("projection_or_merge_state") or "") != EXPECTED_LINEAGE_STATE:
        reasons.append(f"projection_or_merge_state_must_equal:{EXPECTED_LINEAGE_STATE}")
    if not str(scoreboard.get("input_mode") or "").strip():
        reasons.append("input_mode_missing_legacy_scoreboard_not_accepted")
    project_ids = [str(row.get("project_id") or "").strip() for row in project_rows]
    if any(not project_id for project_id in project_ids):
        reasons.append("project_row_missing_project_id")
    if len(project_ids) != len(set(project_ids)):
        reasons.append("project_rows_contain_duplicate_project_id")
    if len(set(project_ids)) != candidate_count:
        reasons.append("candidate_count_must_equal_unique_project_row_count")
    return {
        "state": "PASS" if not reasons else "BLOCKED",
        "blocking_reasons": reasons,
        "legacy_lineage_inference_allowed": False,
    }


def _discovery_metric(
    observations: Mapping[str, Any],
    candidate_count: int,
    observation_window: Mapping[str, Any],
) -> dict[str, Any]:
    item = _mapping(observations.get("discovery"))
    if not item:
        return _withheld_rate("discovery_observation_missing", denominator_kind="SOURCE_ITEMS")
    if item.get("discovery_observation_complete") is not True:
        return _withheld_rate("discovery_observation_window_not_complete", WITHHELD_INCOMPLETE_WINDOW, "SOURCE_ITEMS")
    source_count = _positive_int(item.get("source_item_count"), "discovery.source_item_count")
    discovered_count = _nonnegative_int(
        item.get("discovered_candidate_count"), "discovery.discovered_candidate_count"
    )
    if discovered_count != candidate_count:
        raise ValueError("discovery.discovered_candidate_count must equal clean cohort candidate_count")
    if discovered_count > source_count:
        raise ValueError("discovery.discovered_candidate_count cannot exceed source_item_count")
    _require_nonempty(item, "batch_id", "discovery")
    observed_at = _require_nonempty(item, "observed_at", "discovery")
    _assert_in_observation_window(observed_at, "discovery.observed_at", observation_window)
    if str(item.get("batch_id")) != str(observation_window.get("batch_id")):
        raise ValueError("discovery.batch_id must equal observation_window.batch_id")
    _require_nonempty_list(item, "source_refs", "discovery")
    metric = _rate_metric(
        numerator=discovered_count,
        denominator=source_count,
        numerator_kind="DISCOVERED_CANDIDATES",
        denominator_kind="SOURCE_ITEMS",
        provenance={
            "batch_id": str(item["batch_id"]),
            "source_refs": _strings(item["source_refs"]),
            "denominator_source": str(item.get("denominator_source") or "explicit_observation"),
        },
    )
    prelimit_count = item.get("prelimit_accepted_candidate_count")
    if prelimit_count is not None:
        prelimit = _nonnegative_int(prelimit_count, "discovery.prelimit_accepted_candidate_count")
        if prelimit < discovered_count or prelimit > source_count:
            raise ValueError("discovery prelimit accepted count must be between cohort and source item counts")
        metric["prelimit_accepted_candidate_count"] = prelimit
        metric["prelimit_candidate_discovery_rate"] = _ratio(prelimit, source_count)
        metric["candidate_limit_truncated_count"] = prelimit - discovered_count
    return metric


def _derive_discovery_observation(
    run_result: Mapping[str, Any],
    *,
    cohort_project_ids: set[str],
    candidate_count: int,
) -> dict[str, Any]:
    discovery = _mapping(run_result.get("real_candidate_discovery"))
    if not discovery:
        raise ValueError("run result is missing real_candidate_discovery")
    if bool(discovery.get("evaluation_corpus_mode")):
        raise ValueError("evaluation corpus discovery cannot count as real product discovery")
    if str(discovery.get("source_candidate_mode") or "") != "REAL_PUBLIC_SOURCE_CANDIDATES":
        raise ValueError("run result discovery must use REAL_PUBLIC_SOURCE_CANDIDATES")
    state = str(discovery.get("discovery_state") or "")
    if state not in {"COMPLETED", "NO_CANDIDATES"}:
        raise ValueError("run result discovery must be complete")
    candidates = _mapping_list(discovery.get("candidates"))
    candidate_ids = _project_ids(candidates)
    if candidate_ids != cohort_project_ids:
        raise ValueError("run result discovery project IDs must exactly match clean cohort")
    if _nonnegative_int(discovery.get("candidate_count"), "real_candidate_discovery.candidate_count") != candidate_count:
        raise ValueError("run result discovery candidate_count must equal clean cohort candidate_count")

    ledger = _mapping(run_result.get("stage1_6_validation_ledger"))
    stage_rows = _mapping_list(ledger.get("stage_counts"))
    stage1 = next((row for row in stage_rows if _nonnegative_int(row.get("stage"), "stage_counts.stage") == 1), None)
    if stage1 is None:
        raise ValueError("run result stage1 validation ledger is required for discovery denominator")
    source_item_count = _positive_int(stage1.get("input_count"), "stage1_validation.input_count")
    effective_count = _nonnegative_int(stage1.get("effective_count"), "stage1_validation.effective_count")
    if effective_count != candidate_count:
        raise ValueError("stage1 validation effective_count must equal clean cohort candidate_count")
    diagnostics = _mapping(discovery.get("candidate_discovery_diagnostics"))
    diagnostic_input_count = diagnostics.get("link_item_count")
    if diagnostic_input_count is not None and _nonnegative_int(
        diagnostic_input_count, "candidate_discovery_diagnostics.link_item_count"
    ) != source_item_count:
        raise ValueError("discovery diagnostics and Stage1 ledger source item counts disagree")
    prelimit_accepted_count = _nonnegative_int(
        diagnostics.get("accepted_candidate_count", candidate_count),
        "candidate_discovery_diagnostics.accepted_candidate_count",
    )

    timestamps = sorted(
        _require_nonempty(candidate, "discovered_at", "real_candidate_discovery.candidate")
        for candidate in candidates
    )
    if not timestamps:
        raise ValueError("zero-candidate run result requires explicit discovery observation timestamps")
    for timestamp in timestamps:
        _parse_datetime(timestamp, "real_candidate_discovery.candidate.discovered_at")
    run_id = _require_nonempty(discovery, "discovery_run_id", "real_candidate_discovery")
    profile_reports = _mapping_list(discovery.get("profile_reports"))
    source_refs = [run_id]
    source_refs.extend(
        str(report.get("snapshot_id_optional") or "").strip()
        for report in profile_reports
        if str(report.get("snapshot_id_optional") or "").strip()
    )
    return {
        "observation_window": {
            "batch_id": run_id,
            "started_at": timestamps[0],
            "ended_at": timestamps[-1],
        },
        "discovery": {
            "batch_id": run_id,
            "observed_at": timestamps[-1],
            "source_item_count": source_item_count,
            "discovered_candidate_count": candidate_count,
            "source_refs": list(dict.fromkeys(source_refs)),
            "discovery_observation_complete": True,
            "denominator_source": "stage1_6_validation_ledger.stage_counts[stage=1].input_count",
            "prelimit_accepted_candidate_count": prelimit_accepted_count,
            "candidate_limit_truncated_count": _nonnegative_int(
                _mapping(discovery.get("stage1_6_validation_caps")).get("candidate_limit_truncated_count", 0),
                "stage1_6_validation_caps.candidate_limit_truncated_count",
            ),
        },
    }


def _stage4_ready_metric(project_rows: Sequence[Mapping[str, Any]], denominator: int) -> dict[str, Any]:
    project_ids = {
        str(row.get("project_id"))
        for row in project_rows
        if _nonnegative_int(
            _mapping(row.get("stage4_adapter_result_state_counts")).get("MATCHED", 0),
            "project_row.stage4_adapter_result_state_counts.MATCHED",
        )
        > 0
    }
    metric = _rate_metric(
        numerator=len(project_ids),
        denominator=denominator,
        numerator_kind="UNIQUE_STAGE4_MATCHED_PROJECTS",
        denominator_kind="CLEAN_COHORT_PROJECTS",
        provenance={"source": "scoreboard.project_rows", "task_counts_used_only_as_project_boolean": True},
    )
    metric["ready_project_count"] = len(project_ids)
    return metric


def _reviewable_metric(project_rows: Sequence[Mapping[str, Any]], denominator: int) -> dict[str, Any]:
    project_ids = {
        str(row.get("project_id"))
        for row in project_rows
        if bool(row.get("stage7_commercial_input_allowed"))
        or str(row.get("limited_sellable_review_candidate_state") or "") == "REVIEW_CANDIDATE"
    }
    metric = _rate_metric(
        numerator=len(project_ids),
        denominator=denominator,
        numerator_kind="UNIQUE_REVIEWABLE_PROJECTS",
        denominator_kind="CLEAN_COHORT_PROJECTS",
        provenance={"source": "scoreboard.project_rows"},
    )
    metric["reviewable_project_count"] = len(project_ids)
    return metric


def _evidence_bundle_metric(
    observations: Mapping[str, Any],
    *,
    cohort_project_ids: set[str],
    denominator: int,
    observation_window: Mapping[str, Any],
) -> dict[str, Any]:
    complete = observations.get("evidence_bundle_observation_window_complete") is True
    records = _mapping_list(observations.get("evidence_bundles"))
    if not records and not complete:
        return _withheld_rate("evidence_bundle_observation_missing", denominator_kind="CLEAN_COHORT_PROJECTS")
    if not complete:
        return _withheld_rate(
            "evidence_bundle_observation_window_not_complete",
            WITHHELD_INCOMPLETE_WINDOW,
            "CLEAN_COHORT_PROJECTS",
        )
    generated: set[str] = set()
    signoff_ready: set[str] = set()
    for raw in records:
        record = _unwrap_bundle(raw)
        project_id = str(record.get("project_id") or "").strip()
        if not project_id:
            raise ValueError("evidence bundle record requires project_id for cohort attribution")
        _assert_in_cohort(project_id, cohort_project_ids, "evidence bundle")
        opportunity_id = str(record.get("opportunity_id") or "").strip()
        if not opportunity_id:
            raise ValueError("evidence bundle record requires opportunity_id")
        timestamp = str(record.get("generated_at") or record.get("created_at") or "").strip()
        if not timestamp:
            raise ValueError("evidence bundle record requires generated_at or created_at")
        _assert_in_observation_window(timestamp, "evidence_bundle.generated_at", observation_window)
        if _is_fixed_sku_manifest(record):
            control = _mapping(record.get("issuance_control"))
            if str(control.get("bundle_state") or "") == "INTERNAL_REVIEW_BUNDLE_READY":
                generated.add(project_id)
            if str(control.get("manual_signoff_state") or "") == "READY_FOR_HUMAN_SIGNOFF":
                signoff_ready.add(project_id)
        else:
            package_state = str(record.get("package_state") or "").upper()
            if package_state and package_state not in {"MISSING", "NOT_READY", "BLOCKED", "FAILED"}:
                generated.add(project_id)
            if bool(record.get("delivery_ready")):
                signoff_ready.add(project_id)
    metric = _rate_metric(
        numerator=len(generated),
        denominator=denominator,
        numerator_kind="UNIQUE_PROJECTS_WITH_GENERATED_EVIDENCE_BUNDLE",
        denominator_kind="CLEAN_COHORT_PROJECTS",
        provenance={"source": "observations.evidence_bundles", "window_complete": True},
    )
    metric.update(
        {
            "generated_project_count": len(generated),
            "human_signoff_ready_project_count": len(signoff_ready),
            "human_signoff_ready_rate": _ratio(len(signoff_ready), denominator),
            "external_delivery_counted": False,
        }
    )
    return metric


def _human_review_metric(
    observations: Mapping[str, Any],
    *,
    cohort_project_ids: set[str],
    denominator: int,
    observation_window: Mapping[str, Any],
) -> dict[str, Any]:
    complete = observations.get("human_review_observation_window_complete") is True
    logs = _mapping_list(observations.get("human_review_logs"))
    if not logs and not complete:
        return _withheld_value("human_review_logs_missing")
    if not complete:
        return _withheld_value("human_review_observation_window_not_complete", WITHHELD_INCOMPLETE_WINDOW)
    seen_ids: set[str] = set()
    intervals_by_operator: dict[str, list[tuple[datetime, datetime]]] = {}
    reviewed_projects: set[str] = set()
    total_seconds = 0.0
    for log in logs:
        log_id = _require_nonempty(log, "work_log_id", "human_review_log")
        if log_id in seen_ids:
            raise ValueError(f"duplicate human review work_log_id: {log_id}")
        seen_ids.add(log_id)
        if str(log.get("activity_kind") or "") != "HUMAN_REVIEW":
            raise ValueError("human review activity_kind must equal HUMAN_REVIEW")
        project_id = _require_nonempty(log, "project_id", "human_review_log")
        _assert_in_cohort(project_id, cohort_project_ids, "human review log")
        operator_id = _require_nonempty(log, "operator_id", "human_review_log")
        _require_nonempty(log, "source_ref", "human_review_log")
        started = _parse_datetime(log.get("started_at"), "human_review_log.started_at")
        ended = _parse_datetime(log.get("ended_at"), "human_review_log.ended_at")
        if ended <= started:
            raise ValueError("human review ended_at must be after started_at")
        _assert_interval_in_observation_window(started, ended, observation_window, "human_review_log")
        intervals = intervals_by_operator.setdefault(operator_id, [])
        if any(started < prior_end and ended > prior_start for prior_start, prior_end in intervals):
            raise ValueError(f"overlapping human review intervals for operator_id: {operator_id}")
        intervals.append((started, ended))
        total_seconds += (ended - started).total_seconds()
        reviewed_projects.add(project_id)
    total_minutes = round(total_seconds / 60.0, 2)
    return {
        "state": OBSERVED,
        "value": total_minutes,
        "unit": "HUMAN_MINUTES",
        "reviewed_project_count": len(reviewed_projects),
        "cohort_project_count": denominator,
        "project_observation_coverage_rate": _ratio(len(reviewed_projects), denominator),
        "minutes_per_reviewed_project": (
            round(total_minutes / len(reviewed_projects), 2) if reviewed_projects else 0.0
        ),
        "work_log_count": len(logs),
        "operator_count": len(intervals_by_operator),
        "window_complete": True,
        "individual_operator_ids_exposed": False,
    }


def _adoption_metric(
    observations: Mapping[str, Any],
    *,
    cohort_project_ids: set[str],
    denominator: int,
    observation_window: Mapping[str, Any],
) -> dict[str, Any]:
    complete = observations.get("outcome_observation_window_complete") is True
    events = _mapping_list(observations.get("opportunity_outcomes"))
    if not events and not complete:
        return _withheld_rate("opportunity_outcomes_missing", denominator_kind="CLEAN_COHORT_PROJECTS")
    if not complete:
        return _withheld_rate(
            "outcome_observation_window_not_complete",
            WITHHELD_INCOMPLETE_WINDOW,
            "CLEAN_COHORT_PROJECTS",
        )
    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        project_id = _confirmed_customer_record(event, cohort_project_ids, "opportunity outcome")
        _require_nonempty(event, "outcome_event_id", "opportunity outcome")
        _require_nonempty(event, "opportunity_id", "opportunity outcome")
        _require_nonempty(event, "outcome_family", "opportunity outcome")
        written_back_at = _require_nonempty(event, "written_back_at", "opportunity outcome")
        _assert_in_observation_window(written_back_at, "opportunity_outcome.written_back_at", observation_window)
        _replace_latest(latest, project_id, event, "written_back_at")
    adopted = [event for event in latest.values() if str(event.get("outcome_family")) == "WON"]
    reason_counts = Counter(
        reason
        for event in latest.values()
        for reason in _strings(event.get("outcome_reason_tags"))
    )
    family_counts = Counter(str(event.get("outcome_family") or "UNKNOWN") for event in latest.values())
    metric = _rate_metric(
        numerator=len(adopted),
        denominator=denominator,
        numerator_kind="UNIQUE_PROJECTS_WITH_CONFIRMED_WON_OUTCOME",
        denominator_kind="CLEAN_COHORT_PROJECTS",
        provenance={"source": "formal opportunity_outcome_event", "window_complete": True},
    )
    metric.update(
        {
            "final_outcome_project_count": len(latest),
            "outcome_observation_coverage_rate": _ratio(len(latest), denominator),
            "adopted_project_count": len(adopted),
            "outcome_family_counts": dict(sorted(family_counts.items())),
            "outcome_reason_counts": dict(sorted(reason_counts.items())),
        }
    )
    return metric


def _refund_metric(
    observations: Mapping[str, Any],
    *,
    cohort_project_ids: set[str],
    denominator: int,
    observation_window: Mapping[str, Any],
) -> dict[str, Any]:
    complete = observations.get("payment_observation_window_complete") is True
    records = _mapping_list(observations.get("payment_records"))
    if not records and not complete:
        return _withheld_rate("payment_records_missing", denominator_kind="CLEAN_COHORT_PROJECTS")
    if not complete:
        return _withheld_rate(
            "payment_observation_window_not_complete",
            WITHHELD_INCOMPLETE_WINDOW,
            "CLEAN_COHORT_PROJECTS",
        )
    latest: dict[str, Mapping[str, Any]] = {}
    for record in records:
        project_id = _confirmed_customer_record(record, cohort_project_ids, "payment record")
        _require_nonempty(record, "payment_id", "payment record")
        observed_at_field = "written_back_at_optional" if record.get("written_back_at_optional") else "written_back_at"
        observed_at = _require_nonempty(record, observed_at_field, "payment record")
        _assert_in_observation_window(observed_at, f"payment_record.{observed_at_field}", observation_window)
        _replace_latest(latest, project_id, record, observed_at_field)
    refunded = [record for record in latest.values() if str(record.get("refund_state") or "") in REFUND_STATES]
    refund_state_counts = Counter(str(record.get("refund_state") or "UNKNOWN") for record in latest.values())
    reason_counts: Counter[str] = Counter()
    for record in refunded:
        family = str(record.get("payment_exception_family_optional") or "").strip()
        reason = str(record.get("payment_exception_reason_optional") or "").strip()
        if family:
            reason_counts[family] += 1
        if reason:
            reason_counts[reason] += 1
        reason_counts.update(_strings(record.get("payment_exception_reason_tags_optional")))
    metric = _rate_metric(
        numerator=len(refunded),
        denominator=denominator,
        numerator_kind="UNIQUE_PROJECTS_WITH_CONFIRMED_REFUND_STATE",
        denominator_kind="CLEAN_COHORT_PROJECTS",
        provenance={"source": "formal payment_record", "window_complete": True},
    )
    metric.update(
        {
            "payment_observed_project_count": len(latest),
            "payment_observation_coverage_rate": _ratio(len(latest), denominator),
            "refund_project_count": len(refunded),
            "refund_state_counts": dict(sorted(refund_state_counts.items())),
            "refund_reason_counts": dict(sorted(reason_counts.items())),
        }
    )
    return metric


def _confirmed_customer_record(
    record: Mapping[str, Any], cohort_project_ids: set[str], label: str
) -> str:
    project_id = _require_nonempty(record, "project_id", label)
    _assert_in_cohort(project_id, cohort_project_ids, label)
    confirmation = _mapping(record.get("value_observation"))
    if confirmation.get("real_customer_confirmed") is not True:
        raise ValueError(f"{label} requires value_observation.real_customer_confirmed=true")
    _require_nonempty(confirmation, "confirmation_ref", f"{label}.value_observation")
    mode = str(record.get("governed_execution_mode") or "").upper()
    if not mode:
        raise ValueError(f"{label} requires governed_execution_mode")
    if any(token in mode for token in NON_REAL_MODE_TOKENS):
        raise ValueError(f"{label} preview/dry-run/sandbox/fixture mode cannot count as real customer observation")
    return project_id


def _replace_latest(
    latest: dict[str, Mapping[str, Any]],
    project_id: str,
    record: Mapping[str, Any],
    timestamp_field: str,
) -> None:
    timestamp = _parse_datetime(record.get(timestamp_field), timestamp_field)
    prior = latest.get(project_id)
    if prior is None:
        latest[project_id] = record
        return
    prior_field = "written_back_at_optional" if prior.get("written_back_at_optional") else "written_back_at"
    prior_timestamp = _parse_datetime(prior.get(prior_field), prior_field)
    if timestamp > prior_timestamp:
        latest[project_id] = record


def _unwrap_bundle(raw: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(raw)
    manifest = record.get("manifest")
    if isinstance(manifest, Mapping):
        unwrapped = dict(manifest)
        if not unwrapped.get("project_id") and record.get("project_id"):
            unwrapped["project_id"] = record.get("project_id")
        return unwrapped
    return record


def _is_fixed_sku_manifest(record: Mapping[str, Any]) -> bool:
    return str(_mapping(record.get("sku")).get("sku_code") or "") == "SKU-B"


def _withheld_metrics_for_invalid_cohort(reasons: Sequence[str]) -> dict[str, Any]:
    return {
        key: {
            "state": WITHHELD_INVALID_COHORT,
            "value": None,
            "withheld_reason": "clean_cohort_gate_failed",
            "cohort_blocking_reasons": list(reasons),
        }
        for key in (
            "discovery_rate",
            "stage4_ready_rate",
            "reviewable_rate",
            "evidence_bundle_rate",
            "human_review_minutes",
            "final_adoption",
            "refund",
        )
    }


def _metrics_for_empty_cohort(*, discovery_metric: Mapping[str, Any]) -> dict[str, Any]:
    metrics = {
        key: {"state": NOT_APPLICABLE_NO_CANDIDATES, "value": None}
        for key in (
            "stage4_ready_rate",
            "reviewable_rate",
            "evidence_bundle_rate",
            "human_review_minutes",
            "final_adoption",
            "refund",
        )
    }
    return {"discovery_rate": dict(discovery_metric), **metrics}


def _observation_window(observations: Mapping[str, Any]) -> dict[str, Any]:
    discovery = _mapping(observations.get("discovery"))
    completion_fields = (
        "evidence_bundle_observation_window_complete",
        "human_review_observation_window_complete",
        "outcome_observation_window_complete",
        "payment_observation_window_complete",
    )
    required = discovery.get("discovery_observation_complete") is True or any(
        observations.get(field) is True for field in completion_fields
    )
    window = _mapping(observations.get("observation_window"))
    if not required and not window:
        return {}
    batch_id = _require_nonempty(window, "batch_id", "observation_window")
    started_text = _require_nonempty(window, "started_at", "observation_window")
    ended_text = _require_nonempty(window, "ended_at", "observation_window")
    started = _parse_datetime(started_text, "observation_window.started_at")
    ended = _parse_datetime(ended_text, "observation_window.ended_at")
    if ended < started:
        raise ValueError("observation_window.ended_at must not be before started_at")
    return {"batch_id": batch_id, "started_at": started_text, "ended_at": ended_text}


def _assert_in_observation_window(value: Any, field_name: str, window: Mapping[str, Any]) -> None:
    if not window:
        raise ValueError(f"{field_name} requires observation_window")
    timestamp = _parse_datetime(value, field_name)
    started = _parse_datetime(window.get("started_at"), "observation_window.started_at")
    ended = _parse_datetime(window.get("ended_at"), "observation_window.ended_at")
    if timestamp < started or timestamp > ended:
        raise ValueError(f"{field_name} must fall inside observation_window")


def _assert_interval_in_observation_window(
    started: datetime,
    ended: datetime,
    window: Mapping[str, Any],
    label: str,
) -> None:
    if not window:
        raise ValueError(f"{label} requires observation_window")
    window_started = _parse_datetime(window.get("started_at"), "observation_window.started_at")
    window_ended = _parse_datetime(window.get("ended_at"), "observation_window.ended_at")
    if started < window_started or ended > window_ended:
        raise ValueError(f"{label} interval must fall inside observation_window")


def _rate_metric(
    *,
    numerator: int,
    denominator: int,
    numerator_kind: str,
    denominator_kind: str,
    provenance: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "state": OBSERVED,
        "value": _ratio(numerator, denominator),
        "unit": "RATIO",
        "numerator": numerator,
        "denominator": denominator,
        "numerator_kind": numerator_kind,
        "denominator_kind": denominator_kind,
        "provenance": dict(provenance),
    }


def _withheld_rate(
    reason: str,
    state: str = WITHHELD_MISSING_INPUT,
    denominator_kind: str = "",
) -> dict[str, Any]:
    return {
        "state": state,
        "value": None,
        "unit": "RATIO",
        "numerator": None,
        "denominator": None,
        "denominator_kind": denominator_kind,
        "withheld_reason": reason,
    }


def _withheld_value(reason: str, state: str = WITHHELD_MISSING_INPUT) -> dict[str, Any]:
    return {"state": state, "value": None, "unit": "HUMAN_MINUTES", "withheld_reason": reason}


def _assert_in_cohort(project_id: str, cohort_project_ids: set[str], label: str) -> None:
    if project_id not in cohort_project_ids:
        raise ValueError(f"{label} project_id is outside clean cohort: {project_id}")


def _parse_datetime(value: Any, field_name: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} must be non-empty ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include timezone")
    return parsed


def _project_ids(rows: Iterable[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("project_id") or "").strip() for row in rows if str(row.get("project_id") or "").strip()}


def _read_json_mapping(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError(f"JSON root must be an object: {path}")
    return dict(loaded)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("observation record collection must be a list")
    if any(not isinstance(item, Mapping) for item in value):
        raise ValueError("observation record collection entries must be objects")
    return [dict(item) for item in value]


def _strings(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("reason/source field must be a list")
    return [str(item).strip() for item in value if str(item).strip()]


def _require_nonempty(record: Mapping[str, Any], field: str, label: str) -> str:
    value = str(record.get(field) or "").strip()
    if not value:
        raise ValueError(f"{label}.{field} is required")
    return value


def _require_nonempty_list(record: Mapping[str, Any], field: str, label: str) -> list[str]:
    values = _strings(record.get(field))
    if not values:
        raise ValueError(f"{label}.{field} must be a non-empty list")
    return values


def _nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{field_name} must be a non-negative integer")
    if isinstance(value, str) and (not value.strip() or not value.strip().isdigit()):
        raise ValueError(f"{field_name} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a non-negative integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return parsed


def _positive_int(value: Any, field_name: str) -> int:
    parsed = _nonnegative_int(value, field_name)
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return parsed


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        raise ValueError("ratio denominator must be greater than zero")
    return round(numerator / denominator, 4)


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a clean-batch product value acceptance report")
    parser.add_argument("--scoreboard", required=True, help="Stage1-6 scoreboard JSON")
    parser.add_argument("--observations", help="Optional value observation JSON")
    parser.add_argument("--run-result", help="Optional matching real-public run-result JSON for discovery rate")
    parser.add_argument("--output", help="Optional report JSON output path")
    parser.add_argument("--created-at", help="Optional deterministic ISO-8601 report timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_product_value_acceptance_from_files(
        scoreboard_json=args.scoreboard,
        observations_json=args.observations,
        run_result_json=args.run_result,
        output_json=args.output,
        created_at=args.created_at,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["cohort"]["gate"]["state"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CONTRACT_REF",
    "REPORT_KIND",
    "REPORT_VERSION",
    "build_product_value_acceptance",
    "build_product_value_acceptance_from_files",
    "main",
]
