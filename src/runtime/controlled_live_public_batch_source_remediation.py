from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso


CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_KIND = (
    "controlled_live_public_batch_source_remediation_v1"
)
CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_VERSION = 1
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-live-public-batch-source-remediation-v1")


def build_controlled_live_public_batch_source_remediation(
    *,
    evidence_summary_json: str | Path,
    real_sample_execution_json: str | Path,
    stage4_readback_json: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    evidence_path = Path(evidence_summary_json)
    execution_path = Path(real_sample_execution_json)
    stage4_path = Path(stage4_readback_json) if stage4_readback_json else None
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    evidence_payload = _load_json(evidence_path)
    execution_payload = _load_json(execution_path)
    stage4_payload = _load_json(stage4_path) if stage4_path and stage4_path.exists() else {}
    evidence_summary = _mapping(evidence_payload.get("summary"))
    stage4_summary = _mapping(stage4_payload.get("summary"))
    sample_records = _records(_mapping(evidence_payload.get("sample_evidence_table")).get("records"))
    execution_manifest = _mapping(execution_payload.get("manifest") or execution_payload)
    execution_samples = _execution_sample_index(_records(execution_manifest.get("project_sample_items")))

    remediation_records = [
        _remediation_record(
            sample,
            execution_sample=_lookup_execution_sample(sample, execution_samples),
            created_at=created,
        )
        for sample in sample_records
        if _requires_source_remediation(sample)
    ]
    grouped_records = _group_records(remediation_records, created_at=created)
    summary = _summary(
        evidence_summary=evidence_summary,
        stage4_summary=stage4_summary,
        remediation_records=remediation_records,
        grouped_records=grouped_records,
    )
    result = {
        "manifest_kind": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_KIND,
        "manifest_version": CONTROLLED_LIVE_PUBLIC_BATCH_SOURCE_REMEDIATION_VERSION,
        "adapter_id": "controlled-live-public-batch-source-remediation-v1",
        "created_at": created,
        "source_evidence_summary_json": str(evidence_path),
        "source_real_sample_execution_json": str(execution_path),
        "source_stage4_readback_json": str(stage4_path or ""),
        "summary": summary,
        "source_remediation_queue": {"records": remediation_records, "summary": summary},
        "source_remediation_groups": {"records": grouped_records, "summary": summary},
        "safety": _safety(),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-live-public-batch-source-remediation-v1.json", result)
    (output_dir / "controlled-live-public-batch-source-remediation-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _requires_source_remediation(sample: Mapping[str, Any]) -> bool:
    outcome = str(sample.get("public_source_outcome") or "")
    state = str(sample.get("target_execution_state") or "")
    return outcome in {
        "PUBLIC_SOURCE_PARTIAL_OR_BLOCKED_REVIEW",
        "PUBLIC_SOURCE_NO_MATCH_REVIEW",
        "PUBLIC_SOURCE_REVIEW_REQUIRED",
    } or state in {"CAPTURE_PARTIAL_REVIEW", "DISCOVERY_NO_MATCH_REVIEW", "DISCOVERY_FAILED_CLOSED"}


def _remediation_record(
    sample: Mapping[str, Any],
    *,
    execution_sample: Mapping[str, Any],
    created_at: str,
) -> dict[str, Any]:
    failure_taxonomy = _dedupe(
        [
            *_string_list(execution_sample.get("failure_taxonomy")),
            *_string_list(sample.get("failure_taxonomy")),
            *_detail_retry_failures(execution_sample),
            *_document_quality_reasons(execution_sample),
        ]
    )
    blocker_class = _blocker_class(failure_taxonomy, sample=sample, execution_sample=execution_sample)
    action = _remediation_action(blocker_class, sample=sample, execution_sample=execution_sample)
    alternate = _alternate_public_source_route(blocker_class, sample=sample, execution_sample=execution_sample)
    state = _remediation_state(blocker_class)
    return {
        "remediation_record_id": _stable_id("CLPB-SRCREM", sample.get("sample_id"), failure_taxonomy),
        "created_at": created_at,
        "sample_id": str(sample.get("sample_id") or ""),
        "target_id": str(sample.get("target_id") or ""),
        "parent_target_id": str(sample.get("parent_target_id") or ""),
        "project_id": str(sample.get("project_id") or ""),
        "project_name": str(sample.get("project_name") or ""),
        "document_kind": str(sample.get("document_kind") or ""),
        "jurisdiction": str(sample.get("jurisdiction") or ""),
        "source_profile_id": str(sample.get("source_profile_id") or ""),
        "source_url": str(sample.get("source_url") or ""),
        "project_match_key": str(execution_sample.get("project_match_key") or ""),
        "target_execution_state": str(sample.get("target_execution_state") or ""),
        "public_source_outcome": str(sample.get("public_source_outcome") or ""),
        "detail_capture_status": str(sample.get("detail_capture_status") or ""),
        "document_completeness_state": str(sample.get("document_completeness_state") or ""),
        "failure_taxonomy": failure_taxonomy,
        "blocker_class": blocker_class,
        "source_remediation_state": state,
        "remediation_action": action,
        "alternate_public_source_route": alternate,
        "minimum_rerun_target_ids": _dedupe([sample.get("parent_target_id")]),
        "same_source_retry_allowed": bool(action.get("same_source_retry_allowed")),
        "alternate_source_required": bool(alternate.get("alternate_source_required")),
        "can_auto_resolve_without_new_public_fetch": False,
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _blocker_class(
    failure_taxonomy: list[str],
    *,
    sample: Mapping[str, Any],
    execution_sample: Mapping[str, Any],
) -> str:
    text = " ".join(failure_taxonomy).lower()
    if "captcha" in text or "manual" in text or "login" in text:
        return "PUBLIC_SOURCE_CHALLENGE_OR_MANUAL_BLOCKER"
    if "attachment_url_expired" in text or "http_status:400" in text or "attachment_interface_error" in text:
        return "ATTACHMENT_ENDPOINT_EXPIRED_OR_INTERFACE_BLOCKED"
    if "http_status:502" in text or "curl:52" in text or "tls" in text or "fetch_failed" in text:
        return "DETAIL_TRANSPORT_RETRY_EXHAUSTED"
    if "detail_body_too_small" in text or "detail_title_missing" in text:
        return "DETAIL_CONTENT_INCOMPLETE"
    if str(sample.get("public_source_outcome") or "") == "PUBLIC_SOURCE_NO_MATCH_REVIEW":
        return "PUBLIC_SOURCE_NO_MATCH_REVIEW"
    if str(execution_sample.get("document_completeness_state") or "").endswith("_MISSING_REVIEW"):
        return "DOCUMENT_SNAPSHOT_MISSING_REVIEW"
    return "PUBLIC_SOURCE_REVIEW_REQUIRED"


def _remediation_action(
    blocker_class: str,
    *,
    sample: Mapping[str, Any],
    execution_sample: Mapping[str, Any],
) -> dict[str, Any]:
    if blocker_class in {"DETAIL_TRANSPORT_RETRY_EXHAUSTED", "DETAIL_CONTENT_INCOMPLETE"}:
        return {
            "action_id": "retry_detail_with_backoff_and_clean_url_variants",
            "action_state": "AUTOMATION_READY",
            "same_source_retry_allowed": True,
            "retry_scope": "blocked_parent_target_ids_only",
            "retry_url_variants": _retry_url_variants(str(sample.get("source_url") or "")),
            "max_retry_attempts": 3,
            "minimum_wait_seconds": 30,
        }
    if blocker_class == "ATTACHMENT_ENDPOINT_EXPIRED_OR_INTERFACE_BLOCKED":
        return {
            "action_id": "rediscover_attachment_endpoint_then_fallback_detail_text",
            "action_state": "AUTOMATION_READY",
            "same_source_retry_allowed": True,
            "retry_scope": "blocked_parent_target_ids_only",
            "max_retry_attempts": 2,
            "minimum_wait_seconds": 15,
        }
    if blocker_class == "PUBLIC_SOURCE_CHALLENGE_OR_MANUAL_BLOCKER":
        return {
            "action_id": "skip_challenge_path_and_use_public_alternate_source",
            "action_state": "ALTERNATE_SOURCE_REQUIRED",
            "same_source_retry_allowed": False,
            "retry_scope": "none",
            "max_retry_attempts": 0,
            "minimum_wait_seconds": 0,
        }
    return {
        "action_id": "rerun_with_more_precise_project_identifiers",
        "action_state": "AUTOMATION_READY",
        "same_source_retry_allowed": True,
        "retry_scope": "blocked_parent_target_ids_only",
        "max_retry_attempts": 2,
        "minimum_wait_seconds": 15,
    }


def _alternate_public_source_route(
    blocker_class: str,
    *,
    sample: Mapping[str, Any],
    execution_sample: Mapping[str, Any],
) -> dict[str, Any]:
    jurisdiction = str(sample.get("jurisdiction") or "")
    source_profile_id = str(sample.get("source_profile_id") or "")
    if jurisdiction == "CN-SD" or source_profile_id == "SHANDONG-GGZY-JYXXGK-LIST":
        return {
            "alternate_source_required": True,
            "alternate_source_profile_ids": ["GGZY-DEAL-LIST"],
            "alternate_query_terms": _dedupe(
                [
                    execution_sample.get("project_match_key"),
                    sample.get("project_name"),
                    sample.get("project_id"),
                ]
            ),
            "route_reason": "same_source_detail_transport_degraded_use_national_public_resource_index",
            "must_not_treat_no_match_as_clearance": True,
        }
    if (
        blocker_class == "PUBLIC_SOURCE_CHALLENGE_OR_MANUAL_BLOCKER"
        and source_profile_id
        and source_profile_id != "GGZY-DEAL-LIST"
    ):
        return {
            "alternate_source_required": True,
            "alternate_source_profile_ids": ["GGZY-DEAL-LIST"],
            "alternate_query_terms": _dedupe(
                [
                    execution_sample.get("project_match_key"),
                    sample.get("project_name"),
                    sample.get("project_id"),
                ]
            ),
            "route_reason": "primary_public_source_challenge_use_national_public_resource_index",
            "must_not_treat_no_match_as_clearance": True,
        }
    if blocker_class == "PUBLIC_SOURCE_NO_MATCH_REVIEW":
        return {
            "alternate_source_required": True,
            "alternate_source_profile_ids": ["GGZY-DEAL-LIST"],
            "alternate_query_terms": _dedupe([execution_sample.get("project_match_key"), sample.get("project_name")]),
            "route_reason": "primary_source_no_match_requires_public_alternate_search",
            "must_not_treat_no_match_as_clearance": True,
        }
    return {
        "alternate_source_required": False,
        "alternate_source_profile_ids": [],
        "alternate_query_terms": [],
        "route_reason": "",
        "must_not_treat_no_match_as_clearance": True,
    }


def _remediation_state(blocker_class: str) -> str:
    if blocker_class == "PUBLIC_SOURCE_CHALLENGE_OR_MANUAL_BLOCKER":
        return "ALTERNATE_PUBLIC_SOURCE_REQUIRED"
    if blocker_class in {
        "DETAIL_TRANSPORT_RETRY_EXHAUSTED",
        "DETAIL_CONTENT_INCOMPLETE",
        "ATTACHMENT_ENDPOINT_EXPIRED_OR_INTERFACE_BLOCKED",
        "DOCUMENT_SNAPSHOT_MISSING_REVIEW",
        "PUBLIC_SOURCE_NO_MATCH_REVIEW",
        "PUBLIC_SOURCE_REVIEW_REQUIRED",
    }:
        return "SOURCE_REMEDIATION_QUEUE_READY"
    return "SOURCE_REMEDIATION_REVIEW_REQUIRED"


def _group_records(records: list[Mapping[str, Any]], *, created_at: str) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
    for record in records:
        key = (
            str(record.get("source_profile_id") or ""),
            str(record.get("blocker_class") or ""),
            str(record.get("project_id") or record.get("project_name") or ""),
        )
        groups.setdefault(key, []).append(record)
    out: list[dict[str, Any]] = []
    for (source_profile_id, blocker_class, project_key), group in sorted(groups.items()):
        parent_target_ids = _dedupe(record.get("parent_target_id") for record in group)
        alternate_profiles = _dedupe(
            profile
            for record in group
            for profile in _string_list(_mapping(record.get("alternate_public_source_route")).get("alternate_source_profile_ids"))
        )
        out.append(
            {
                "source_remediation_group_id": _stable_id("CLPB-SRCGRP", source_profile_id, blocker_class, project_key),
                "created_at": created_at,
                "source_profile_id": source_profile_id,
                "blocker_class": blocker_class,
                "project_key": project_key,
                "sample_count": len(group),
                "parent_target_ids": parent_target_ids,
                "document_kinds": _dedupe(record.get("document_kind") for record in group),
                "project_names": _dedupe(record.get("project_name") for record in group),
                "source_urls": _dedupe(record.get("source_url") for record in group),
                "failure_taxonomy": _dedupe(
                    reason for record in group for reason in _string_list(record.get("failure_taxonomy"))
                ),
                "recommended_execution": _recommended_execution(group, parent_target_ids, alternate_profiles),
                "customer_visible_allowed": False,
                "query_miss_is_not_clearance": True,
                "no_legal_conclusion": True,
            }
        )
    return out


def _recommended_execution(
    group: list[Mapping[str, Any]],
    parent_target_ids: list[str],
    alternate_profiles: list[str],
) -> dict[str, Any]:
    same_source_retry = any(bool(record.get("same_source_retry_allowed")) for record in group)
    alternate_required = any(bool(record.get("alternate_source_required")) for record in group)
    if same_source_retry:
        primary_action = "rerun_blocked_targets_same_source_with_backoff"
    elif alternate_required:
        primary_action = "run_alternate_public_source_query"
    else:
        primary_action = "source_review_required"
    return {
        "primary_action": primary_action,
        "blocked_parent_target_ids": parent_target_ids,
        "alternate_source_profile_ids": alternate_profiles,
        "rerun_all_targets": False,
        "execute_customer_visible": False,
        "execute_payment": False,
        "execute_delivery": False,
    }


def _summary(
    *,
    evidence_summary: Mapping[str, Any],
    stage4_summary: Mapping[str, Any],
    remediation_records: list[Mapping[str, Any]],
    grouped_records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    state_counts = _counts(record.get("source_remediation_state") for record in remediation_records)
    blocker_counts = _counts(record.get("blocker_class") for record in remediation_records)
    ready_count = sum(
        1
        for record in remediation_records
        if str(record.get("source_remediation_state") or "") == "SOURCE_REMEDIATION_QUEUE_READY"
    )
    alternate_required_count = sum(1 for record in remediation_records if bool(record.get("alternate_source_required")))
    unresolved_count = len(remediation_records)
    if not remediation_records:
        closeout_state = "NO_SOURCE_REMEDIATION_REQUIRED"
        next_step = "gray_launch_review_if_other_gates_ready"
    elif ready_count == len(remediation_records):
        closeout_state = "SOURCE_REMEDIATION_QUEUE_READY"
        next_step = "execute_source_remediation_queue"
    elif alternate_required_count:
        closeout_state = "ALTERNATE_PUBLIC_SOURCE_REQUIRED"
        next_step = "execute_alternate_public_source_queries"
    else:
        closeout_state = "SOURCE_REMEDIATION_REVIEW_REQUIRED"
        next_step = "review_source_remediation_queue"
    return {
        "source_execute": bool(evidence_summary.get("source_execute")),
        "project_sample_count": _int(evidence_summary.get("project_sample_count")),
        "stage4_all_required_readbacks_ready": bool(stage4_summary.get("stage4_all_required_readbacks_ready")),
        "source_remediation_record_count": len(remediation_records),
        "source_remediation_group_count": len(grouped_records),
        "source_remediation_ready_count": ready_count,
        "alternate_public_source_required_count": alternate_required_count,
        "source_remediation_unresolved_count": unresolved_count,
        "source_remediation_state_counts": state_counts,
        "blocker_class_counts": blocker_counts,
        "blocked_parent_target_ids": _dedupe(
            target_id for record in remediation_records for target_id in _string_list(record.get("minimum_rerun_target_ids"))
        ),
        "source_remediation_closeout_state": closeout_state,
        "next_required_step": next_step,
        "eligible_for_gray_launch_review_after_source_remediation": len(remediation_records) == 0
        and bool(stage4_summary.get("stage4_all_required_readbacks_ready")),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _detail_retry_failures(sample: Mapping[str, Any]) -> list[str]:
    failures: list[str] = []
    retry = _mapping(sample.get("detail_url_retry_audit"))
    for attempt in _records(retry.get("attempts")):
        if attempt.get("http_status") not in (None, ""):
            failures.append(f"detail_retry_http_status:{attempt.get('http_status')}")
        failures.extend(f"detail_retry_degraded:{reason}" for reason in _string_list(attempt.get("degraded_reasons")))
    return failures


def _document_quality_reasons(sample: Mapping[str, Any]) -> list[str]:
    parse_summary = _mapping(sample.get("parse_summary"))
    return _string_list(parse_summary.get("document_quality_reasons"))


def _retry_url_variants(source_url: str) -> list[str]:
    if not source_url:
        return []
    variants = [source_url]
    if source_url.startswith("http://"):
        variants.append("https://" + source_url[len("http://") :].replace(":80/", "/"))
    if ":80/" in source_url:
        variants.append(source_url.replace(":80/", "/"))
    return _dedupe(variants)


def _execution_sample_index(samples: list[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for sample in samples:
        for key in ("sample_id", "target_id"):
            value = str(sample.get(key) or "")
            if value and value not in result:
                result[value] = sample
    return result


def _lookup_execution_sample(
    sample: Mapping[str, Any],
    execution_samples: Mapping[str, Mapping[str, Any]],
) -> Mapping[str, Any]:
    for key in ("sample_id", "target_id"):
        value = str(sample.get(key) or "")
        if value in execution_samples:
            return execution_samples[value]
    return {}


def _safety() -> dict[str, Any]:
    return {
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "source_remediation_generation_enabled": True,
        "source_remediation_execution_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Live Public Batch Source Remediation",
        "",
        f"- source_remediation_record_count: {summary.get('source_remediation_record_count')}",
        f"- source_remediation_group_count: {summary.get('source_remediation_group_count')}",
        f"- source_remediation_ready_count: {summary.get('source_remediation_ready_count')}",
        f"- alternate_public_source_required_count: {summary.get('alternate_public_source_required_count')}",
        f"- source_remediation_closeout_state: {summary.get('source_remediation_closeout_state')}",
        f"- next_required_step: {summary.get('next_required_step')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- query_miss_is_not_clearance: {str(bool(summary.get('query_miss_is_not_clearance'))).lower()}",
        "",
        "## Blocker Classes",
    ]
    for key, value in _mapping(summary.get("blocker_class_counts")).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def _load_json(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("records"), list):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Iterable) and not isinstance(value, (bytes, Mapping)):
        return [str(item) for item in value if str(item or "")]
    return [str(value)] if str(value or "") else []


def _dedupe(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _counts(values: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "")
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        json.dumps([str(part or "") for part in parts], ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-summary-json", required=True)
    parser.add_argument("--real-sample-execution-json", required=True)
    parser.add_argument("--stage4-readback-json", default="")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_live_public_batch_source_remediation(
        evidence_summary_json=args.evidence_summary_json,
        real_sample_execution_json=args.real_sample_execution_json,
        stage4_readback_json=args.stage4_readback_json or None,
        output_root=args.output_root,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
