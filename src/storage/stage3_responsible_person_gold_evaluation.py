from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage3_parsing.responsible_person_identity import (
    CRITICAL_IDENTITY_REVIEW_THRESHOLD,
    assess_responsible_person_name,
)
from storage.responsible_person_early_probe import extract_responsible_person_profile


STAGE3_RESPONSIBLE_PERSON_GOLD_EVALUATION_KIND = (
    "stage3_responsible_person_gold_evaluation_v1_manifest"
)
STAGE3_RESPONSIBLE_PERSON_GOLD_EVALUATION_VERSION = 1
DEFAULT_GOLDEN_SET = Path("contracts/evaluation/stage3_responsible_person_golden_set.json")
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/stage3-responsible-person-golden-evaluation-v1"
)
EVALUATED_FIELDS = (
    "candidate_company",
    "responsible_person",
    "certificate_no",
    "candidate_row_binding",
    "consortium_member",
)


def build_stage3_responsible_person_gold_evaluation(
    *,
    golden_set_json: str | Path = DEFAULT_GOLDEN_SET,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    contract_path = Path(golden_set_json)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)

    blocking_reasons: list[str] = []
    contract = _load_json(contract_path)
    if not contract:
        blocking_reasons.append("stage3_responsible_person_golden_set_missing_or_invalid")
    cases = [case for case in list(contract.get("cases") or []) if isinstance(case, Mapping)]
    if contract and not cases:
        blocking_reasons.append("stage3_responsible_person_golden_set_has_no_cases")

    case_results = [_evaluate_case(case) for case in cases]
    metrics = _metrics(case_results, thresholds=_mapping(contract.get("metric_thresholds")))
    regression_errors = _regression_errors(case_results)
    review_assertion_failures = [
        result["case_id"]
        for result in case_results
        if not result.get("critical_identity_review_assertion_passed")
    ]
    failed_metric_fields = [
        field_name
        for field_name, metric in metrics.items()
        if metric.get("threshold_state") == "FAILED"
    ]
    evaluation_passed = bool(case_results) and not (
        blocking_reasons
        or regression_errors
        or review_assertion_failures
        or failed_metric_fields
    )
    label_review_state = str(contract.get("label_review_state") or "UNSPECIFIED")

    summary = {
        "evaluation_state": "PASSED" if evaluation_passed else "FAILED",
        "case_count": len(case_results),
        "real_public_structure_case_count": sum(
            1
            for case in cases
            if str(case.get("sample_class") or "").startswith("REAL_PUBLIC")
        ),
        "controlled_case_count": sum(
            1
            for case in cases
            if str(case.get("sample_class") or "").startswith("CONTROLLED")
        ),
        "regression_error_count": len(regression_errors),
        "review_assertion_failure_count": len(review_assertion_failures),
        "failed_metric_fields": failed_metric_fields,
        "field_metrics": metrics,
        "label_review_state": label_review_state,
        "external_second_review_complete": label_review_state
        == "EXTERNALLY_SECOND_REVIEWED_GOLDEN",
        "scope_boundary": (
            "Internal Guangzhou-structure and controlled OCR-text replay only; "
            "not a cross-region OCR recognition benchmark or production-readiness claim."
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_version": STAGE3_RESPONSIBLE_PERSON_GOLD_EVALUATION_VERSION,
        "manifest_kind": STAGE3_RESPONSIBLE_PERSON_GOLD_EVALUATION_KIND,
        "created_at": created,
        "golden_set_path": str(contract_path),
        "golden_set_sha256": _file_sha256(contract_path),
        "contract_id": str(contract.get("contract_id") or ""),
        "contract_version": contract.get("contract_version"),
        "label_review_state": label_review_state,
        "case_results": case_results,
        "regression_error_samples": regression_errors,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "live_provider_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_benchmark_claimed": False,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "stage3_responsible_person_gold_evaluation_mode": "EXECUTED",
        "safe_to_execute": not blocking_reasons,
        "evaluation_passed": evaluation_passed,
        "blocking_reasons": blocking_reasons,
        "manifest": manifest,
        "summary": summary,
    }
    (out_root / "stage3-responsible-person-golden-evaluation.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "regression-error-samples.json").write_text(
        json.dumps(
            {
                "manifest_kind": "stage3_responsible_person_regression_error_samples_v1",
                "created_at": created,
                "source_evaluation_manifest_id": manifest["manifest_sha256"],
                "items": regression_errors,
                "summary": {"error_sample_count": len(regression_errors)},
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_root / "summary.md").write_text(_markdown_summary(summary), encoding="utf-8")
    return result


def _evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "UNNAMED-CASE")
    source_modality = str(case.get("source_modality") or "text")
    source_confidence = _float(case.get("source_confidence"), 0.0)
    rejected_quality_state = ""
    if source_modality == "stage16_identity_value":
        quality = assess_responsible_person_name(
            case.get("input_value"),
            confidence=source_confidence,
        )
        actual = {field_name: [] for field_name in EVALUATED_FIELDS}
        if quality.accepted:
            actual["responsible_person"] = [quality.normalized_value]
        critical_review_required = quality.review_required
        rejected_quality_state = quality.quality_state if not quality.accepted else ""
    else:
        profile = extract_responsible_person_profile(str(case.get("input_text") or ""))
        actual = _actual_fields(profile)
        critical_review_required = bool(profile.get("critical_identity_review_required")) or (
            source_confidence < CRITICAL_IDENTITY_REVIEW_THRESHOLD
            and bool(actual["responsible_person"])
        )

    expected_payload = _mapping(case.get("expected"))
    field_results: dict[str, Any] = {}
    for field_name in EVALUATED_FIELDS:
        expected = _normalized_values(expected_payload.get(field_name))
        observed = _normalized_values(actual.get(field_name))
        expected_set = set(expected)
        observed_set = set(observed)
        field_results[field_name] = {
            "expected": sorted(expected_set),
            "actual": sorted(observed_set),
            "true_positive": sorted(expected_set & observed_set),
            "false_positive": sorted(observed_set - expected_set),
            "false_negative": sorted(expected_set - observed_set),
            "passed": expected_set == observed_set,
        }
    expected_review_required = bool(
        expected_payload.get("critical_identity_review_required")
    )
    expected_rejected_quality_state = str(
        expected_payload.get("rejected_quality_state") or ""
    )
    quality_state_assertion_passed = (
        not expected_rejected_quality_state
        or expected_rejected_quality_state == rejected_quality_state
    )
    return {
        "case_id": case_id,
        "sample_class": str(case.get("sample_class") or ""),
        "project_id": str(case.get("project_id") or ""),
        "source_url": str(case.get("source_url") or ""),
        "source_ref": str(case.get("source_ref") or ""),
        "source_modality": source_modality,
        "source_confidence": source_confidence,
        "field_results": field_results,
        "critical_identity_review_required": critical_review_required,
        "expected_critical_identity_review_required": expected_review_required,
        "critical_identity_review_assertion_passed": (
            critical_review_required == expected_review_required
            and quality_state_assertion_passed
        ),
        "rejected_quality_state": rejected_quality_state,
        "expected_rejected_quality_state": expected_rejected_quality_state,
        "case_passed": all(result["passed"] for result in field_results.values())
        and critical_review_required == expected_review_required
        and quality_state_assertion_passed,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _actual_fields(profile: Mapping[str, Any]) -> dict[str, list[str]]:
    groups = [
        group
        for group in list(profile.get("candidate_groups") or [])
        if isinstance(group, Mapping)
    ]
    row_bindings = [
        "|".join(
            (
                str(group.get("candidate_group_order") or ""),
                str(group.get("primary_company_name") or ""),
                str(group.get("responsible_person_name") or ""),
                str(group.get("certificate_no") or ""),
            )
        )
        for group in groups
        if group.get("primary_company_name") and group.get("responsible_person_name")
    ]
    if not row_bindings:
        row_bindings = [
            "|".join(
                (
                    str(target.get("candidate_group_order") or ""),
                    str(target.get("candidate_company_name") or ""),
                    str(target.get("responsible_person_name") or ""),
                    str(target.get("certificate_no") or ""),
                )
            )
            for target in list(profile.get("verification_targets") or [])
            if isinstance(target, Mapping)
            and target.get("candidate_company_name")
            and target.get("responsible_person_name")
        ]
    consortium_members = [
        f"{group.get('candidate_group_order') or ''}|{member.get('company_name') or ''}"
        for group in groups
        for member in list(group.get("consortium_members") or [])
        if isinstance(member, Mapping) and member.get("company_name")
    ]
    return {
        "candidate_company": _candidate_values(profile.get("candidate_company_candidates")),
        "responsible_person": _candidate_values(profile.get("responsible_person_candidates")),
        "certificate_no": _candidate_values(profile.get("certificate_no_candidates")),
        "candidate_row_binding": row_bindings,
        "consortium_member": consortium_members,
    }


def _metrics(
    case_results: list[Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Any],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for field_name in EVALUATED_FIELDS:
        tp = fp = fn = 0
        for case in case_results:
            result = _mapping(_mapping(case.get("field_results")).get(field_name))
            tp += len(result.get("true_positive") or [])
            fp += len(result.get("false_positive") or [])
            fn += len(result.get("false_negative") or [])
        precision = _ratio(tp, tp + fp)
        recall = _ratio(tp, tp + fn)
        threshold = _mapping(thresholds.get(field_name))
        threshold_precision = _float(threshold.get("precision"), 0.0)
        threshold_recall = _float(threshold.get("recall"), 0.0)
        if precision is None or recall is None:
            threshold_state = "NOT_APPLICABLE_NO_POSITIVE_DENOMINATOR"
        elif precision >= threshold_precision and recall >= threshold_recall:
            threshold_state = "PASSED"
        else:
            threshold_state = "FAILED"
        metrics[field_name] = {
            "true_positive_count": tp,
            "false_positive_count": fp,
            "false_negative_count": fn,
            "precision": precision,
            "recall": recall,
            "precision_denominator": tp + fp,
            "recall_denominator": tp + fn,
            "required_precision": threshold_precision,
            "required_recall": threshold_recall,
            "threshold_state": threshold_state,
        }
    return metrics


def _regression_errors(case_results: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for case in case_results:
        for field_name, result in _mapping(case.get("field_results")).items():
            field_result = _mapping(result)
            if field_result.get("passed"):
                continue
            errors.append(
                {
                    "error_id": "STAGE3-GOLD-ERROR-"
                    + _fingerprint(
                        {
                            "case": case.get("case_id"),
                            "field": field_name,
                            "fp": field_result.get("false_positive"),
                            "fn": field_result.get("false_negative"),
                        }
                    )[:16],
                    "case_id": case.get("case_id"),
                    "project_id": case.get("project_id"),
                    "field_name": field_name,
                    "false_positive": list(field_result.get("false_positive") or []),
                    "false_negative": list(field_result.get("false_negative") or []),
                    "recommended_action": "add_or_keep_case_in_stage3_identity_regression_and_fix_parser_without_weakening_review_gate",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
        if not case.get("critical_identity_review_assertion_passed"):
            errors.append(
                {
                    "error_id": "STAGE3-GOLD-REVIEW-" + _fingerprint(case.get("case_id"))[:16],
                    "case_id": case.get("case_id"),
                    "project_id": case.get("project_id"),
                    "field_name": "critical_identity_review_required",
                    "false_positive": [],
                    "false_negative": [],
                    "recommended_action": "preserve_or_restore_fail_closed_review_for_low_confidence_or_rejected_identity",
                    "customer_visible_allowed": False,
                    "no_legal_conclusion": True,
                }
            )
    return errors


def _candidate_values(value: Any) -> list[str]:
    return [
        str(item.get("value") or "").strip()
        for item in list(value or [])
        if isinstance(item, Mapping) and str(item.get("value") or "").strip()
    ]


def _normalized_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _file_sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _markdown_summary(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage3 负责人金标评估",
        "",
        f"- evaluation_state: `{summary.get('evaluation_state')}`",
        f"- case_count: `{summary.get('case_count')}`",
        f"- regression_error_count: `{summary.get('regression_error_count')}`",
        f"- label_review_state: `{summary.get('label_review_state')}`",
        f"- scope_boundary: {summary.get('scope_boundary')}",
        "",
        "| field | precision | recall | state |",
        "|---|---:|---:|---|",
    ]
    for field_name, metric in _mapping(summary.get("field_metrics")).items():
        value = _mapping(metric)
        lines.append(
            f"| {field_name} | {value.get('precision')} | {value.get('recall')} | {value.get('threshold_state')} |"
        )
    lines.extend(
        [
            "",
            "> 本报告只证明仓库内金标样本和受控 OCR 文本回放；不代表跨地区 OCR、任意表格或生产部署已达标。",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Stage3 responsible-person golden cases.")
    parser.add_argument("--golden-set-json", default=str(DEFAULT_GOLDEN_SET))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_stage3_responsible_person_gold_evaluation(
        golden_set_json=args.golden_set_json,
        output_root=args.output_root,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] and result["evaluation_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "STAGE3_RESPONSIBLE_PERSON_GOLD_EVALUATION_KIND",
    "build_stage3_responsible_person_gold_evaluation",
]
