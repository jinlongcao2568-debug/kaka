from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage3_parsing.tailored_bid_signals import (
    DEFAULT_SEED_PATH as DEFAULT_TAILORED_SIGNAL_SEED_PATH,
)
from storage.evaluation_rule_calibration import (
    FILE_REVIEW_RULE_CODE,
    TAILORED_REVIEW_RULE_CODE,
    _calibrate_file_review_item,
    _calibrate_tailored_review_item,
)


STAGE5_REAL_PROJECT_RULE_CALIBRATION_KIND = (
    "stage5_real_project_rule_calibration_v1_manifest"
)
DEFAULT_INPUT_ROOT = Path("tmp/evaluation-real-samples")
DEFAULT_CONTRACT = Path(
    "contracts/evaluation/stage5_rule_truth_label_contract.json"
)
DEFAULT_OUTPUT_ROOT = Path(
    "tmp/evaluation-real-samples/stage5-real-project-rule-calibration-v1"
)
BASELINE_RULE_VERSION = "FILE_REVIEW_ONLY_V1"
CURRENT_RULE_VERSION = "FILE_REVIEW_PLUS_TAILORED_REVIEW_V1"


def build_stage5_real_project_rule_calibration(
    *,
    input_root: str | Path = DEFAULT_INPUT_ROOT,
    input_manifest_jsons: Iterable[str | Path] | None = None,
    truth_label_contract_json: str | Path = DEFAULT_CONTRACT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    contract_path = Path(truth_label_contract_json)
    contract = _load_json(contract_path)
    out_root = Path(output_root)
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_paths = _manifest_paths(
        input_root=Path(input_root),
        explicit=input_manifest_jsons,
    )
    existing_labels = _existing_labels(
        out_root / "stage5-real-project-truth-label-packet.json"
    )
    groups: dict[str, dict[str, Any]] = {}
    accepted_manifests: list[dict[str, Any]] = []
    skipped_manifests: list[dict[str, Any]] = []
    seed_path = Path(DEFAULT_TAILORED_SIGNAL_SEED_PATH)
    for path in manifest_paths:
        payload = _load_json(path)
        manifest = _mapping(payload.get("manifest"))
        if not _real_executed_manifest(payload):
            skipped_manifests.append(
                {"path": str(path), "reason": "not_real_executed_manifest"}
            )
            continue
        samples = [
            dict(item)
            for item in list(manifest.get("project_sample_items") or [])
            if isinstance(item, Mapping)
        ]
        if not samples:
            skipped_manifests.append(
                {"path": str(path), "reason": "project_sample_items_missing"}
            )
            continue
        accepted_manifests.append(
            {
                "path": str(path),
                "sha256": _file_sha256(path),
                "manifest_id": str(manifest.get("manifest_id") or ""),
                "created_at": str(manifest.get("created_at") or ""),
                "project_sample_count": len(samples),
            }
        )
        for sample in samples:
            dedupe_key = _dedupe_key(sample)
            if not dedupe_key:
                continue
            group = groups.setdefault(dedupe_key, _new_group(dedupe_key))
            _merge_observation(
                group,
                sample=sample,
                source_manifest_path=path,
                source_manifest_id=str(manifest.get("manifest_id") or ""),
                source_manifest_created_at=str(manifest.get("created_at") or ""),
                tailored_seed_path=seed_path,
            )
    sample_rows = [
        _finalize_group(
            group,
            existing_label=existing_labels.get(_gold_sample_id(key)),
        )
        for key, group in sorted(groups.items())
    ]
    label_validation = _validate_labels(sample_rows, contract=contract)
    comparison = _comparison_metrics(
        sample_rows,
        valid_labeled_sample_ids=set(label_validation["valid_evaluation_sample_ids"]),
    )
    minimum = _int(
        contract.get("minimum_deduplicated_real_project_count"),
        50,
    )
    sample_count_ready = len(sample_rows) >= minimum
    truth_labels_ready = not label_validation["truth_label_required_sample_ids"]
    if not sample_count_ready:
        evaluation_state = "BLOCKED_INSUFFICIENT_UNIQUE_REAL_PROJECTS"
    elif not truth_labels_ready:
        evaluation_state = "BLOCKED_TRUTH_LABELS_PENDING"
    else:
        evaluation_state = "READY_FOR_HUMAN_THRESHOLD_DECISION"
    summary = {
        "evaluation_state": evaluation_state,
        "minimum_unique_real_project_count": minimum,
        "unique_real_project_count": len(sample_rows),
        "sample_count_ready": sample_count_ready,
        "accepted_execution_manifest_count": len(accepted_manifests),
        "skipped_manifest_count": len(skipped_manifests),
        "raw_project_observation_count": sum(
            len(row["observation_refs"]) for row in sample_rows
        ),
        "truth_label_valid_count": len(label_validation["valid_label_sample_ids"]),
        "truth_label_evaluation_count": len(
            label_validation["valid_evaluation_sample_ids"]
        ),
        "truth_label_required_count": len(
            label_validation["truth_label_required_sample_ids"]
        ),
        "truth_labels_ready": truth_labels_ready,
        "truth_label_state_counts": label_validation["truth_label_state_counts"],
        "baseline_rule_version": BASELINE_RULE_VERSION,
        "current_rule_version": CURRENT_RULE_VERSION,
        "baseline_prediction_counts": _counts(
            row["baseline_prediction"] for row in sample_rows
        ),
        "current_prediction_counts": _counts(
            row["current_prediction"] for row in sample_rows
        ),
        "baseline_review_share": _review_share(
            row["baseline_prediction"] for row in sample_rows
        ),
        "current_review_share": _review_share(
            row["current_prediction"] for row in sample_rows
        ),
        "changed_prediction_count": comparison["changed_prediction_count"],
        "baseline_truth_metrics": comparison["baseline_truth_metrics"],
        "current_truth_metrics": comparison["current_truth_metrics"],
        "metrics_withheld_reason": None
        if truth_labels_ready
        else "human_truth_labels_incomplete_false_positive_and_false_negative_not_reported_as_zero",
        "automatic_threshold_mutation_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    truth_packet = {
        "packet_kind": "stage5_real_project_truth_label_packet_v1",
        "packet_version": 1,
        "created_at": created,
        "contract_id": str(contract.get("contract_id") or ""),
        "contract_version": contract.get("contract_version"),
        "baseline_rule_version": BASELINE_RULE_VERSION,
        "current_rule_version": CURRENT_RULE_VERSION,
        "labels": sample_rows,
        "summary": {
            "unique_real_project_count": len(sample_rows),
            "truth_label_required_count": len(
                label_validation["truth_label_required_sample_ids"]
            ),
            "existing_human_labels_preserved": sum(
                bool(existing_labels.get(row["sample_id"])) for row in sample_rows
            ),
        },
        "editing_contract": {
            "editable_fields": [
                "truth_label",
                "truth_label_state",
                "reviewer_id",
                "reviewed_at",
                "truth_evidence_refs",
                "review_note",
            ],
            "do_not_replace_prediction_with_truth": True,
            "rerun_preserves_existing_labels_by_sample_id": True,
        },
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_kind": STAGE5_REAL_PROJECT_RULE_CALIBRATION_KIND,
        "manifest_version": 1,
        "created_at": created,
        "truth_label_contract_path": str(contract_path),
        "truth_label_contract_sha256": _file_sha256(contract_path),
        "accepted_execution_manifests": accepted_manifests,
        "skipped_manifests": skipped_manifests,
        "sample_results": sample_rows,
        "label_validation": label_validation,
        "before_after_comparison": comparison,
        "summary": summary,
        "safety": {
            "network_enabled": False,
            "stage5_rule_execution_enabled": False,
            "formal_rule_threshold_mutation_enabled": False,
            "ai_self_label_enabled": False,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(manifest)
    result = {
        "stage5_real_project_rule_calibration_mode": "EXECUTED_OFFLINE",
        "safe_to_execute": bool(contract),
        "evaluation_ready": sample_count_ready and truth_labels_ready,
        "manifest": manifest,
        "summary": summary,
    }
    (out_root / "stage5-real-project-truth-label-packet.json").write_text(
        json.dumps(truth_packet, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_root / "stage5-real-project-rule-calibration-v1.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    error_samples = comparison["current_false_positive_samples"] + comparison[
        "current_false_negative_samples"
    ]
    (out_root / "regression-error-samples.json").write_text(
        json.dumps(
            {
                "manifest_kind": "stage5_rule_regression_error_samples_v1",
                "created_at": created,
                "items": error_samples,
                "summary": {
                    "error_sample_count": len(error_samples),
                    "withheld_until_truth_labels_complete": not truth_labels_ready,
                },
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_label_csv(out_root / "truth-label-required.csv", sample_rows)
    (out_root / "summary.md").write_text(
        _markdown_summary(summary),
        encoding="utf-8",
    )
    return result


def _manifest_paths(
    *,
    input_root: Path,
    explicit: Iterable[str | Path] | None,
) -> list[Path]:
    if explicit is not None:
        return sorted({Path(path) for path in explicit}, key=lambda path: str(path))
    if not input_root.exists():
        return []
    return sorted(input_root.rglob("run-manifest.json"), key=lambda path: str(path))


def _real_executed_manifest(payload: Mapping[str, Any]) -> bool:
    execution = _mapping(payload.get("execution"))
    mode = str(payload.get("real_sample_execution_mode") or "")
    return bool(
        mode == "EXECUTED"
        and payload.get("execute") is True
        and execution.get("executed") is True
    )


def _dedupe_key(sample: Mapping[str, Any]) -> str:
    project_id = str(sample.get("project_id") or "").strip()
    if project_id:
        return f"project_id:{project_id}"
    source_url = str(sample.get("source_url") or "").strip()
    return f"source_url:{source_url}" if source_url else ""


def _new_group(dedupe_key: str) -> dict[str, Any]:
    return {
        "dedupe_key": dedupe_key,
        "project_ids": set(),
        "project_names": set(),
        "source_urls": set(),
        "document_kinds": set(),
        "jurisdictions": set(),
        "source_profile_ids": set(),
        "observation_refs": [],
        "baseline_review": False,
        "current_review": False,
        "file_review_reasons": set(),
        "tailored_review_reasons": set(),
    }


def _merge_observation(
    group: dict[str, Any],
    *,
    sample: Mapping[str, Any],
    source_manifest_path: Path,
    source_manifest_id: str,
    source_manifest_created_at: str,
    tailored_seed_path: Path,
) -> None:
    file_item = _calibrate_file_review_item(sample)
    tailored_item = _calibrate_tailored_review_item(
        sample,
        seed_path=tailored_seed_path,
    )
    file_review = file_item["expected_file_review_state"] == "REVIEW_REQUIRED"
    tailored_review = (
        tailored_item["expected_tailored_review_state"] == "REVIEW_REQUIRED"
    )
    group["baseline_review"] = bool(group["baseline_review"] or file_review)
    group["current_review"] = bool(
        group["current_review"] or file_review or tailored_review
    )
    group["file_review_reasons"].update(
        file_item.get("expected_file_review_reasons") or []
    )
    group["tailored_review_reasons"].update(
        tailored_item.get("expected_tailored_review_reasons") or []
    )
    for field, target in (
        ("project_id", "project_ids"),
        ("project_name", "project_names"),
        ("source_url", "source_urls"),
        ("document_kind", "document_kinds"),
        ("jurisdiction", "jurisdictions"),
        ("source_profile_id", "source_profile_ids"),
    ):
        value = str(sample.get(field) or "").strip()
        if value:
            group[target].add(value)
    group["observation_refs"].append(
        {
            "source_manifest_path": str(source_manifest_path),
            "source_manifest_id": source_manifest_id,
            "source_manifest_created_at": source_manifest_created_at,
            "sample_id": str(sample.get("sample_id") or ""),
            "target_id": str(sample.get("target_id") or ""),
            "candidate_key": str(sample.get("candidate_key") or ""),
            "document_kind": str(sample.get("document_kind") or ""),
            "source_url": str(sample.get("source_url") or ""),
            "detail_snapshot_ids": sorted(
                str(ref.get("snapshot_id") or "")
                for ref in list(sample.get("detail_snapshot_refs") or [])
                if isinstance(ref, Mapping) and ref.get("snapshot_id")
            ),
            "attachment_snapshot_ids": sorted(
                str(ref.get("snapshot_id") or "")
                for ref in list(sample.get("attachment_snapshot_refs") or [])
                if isinstance(ref, Mapping) and ref.get("snapshot_id")
            ),
            "source_text_sha256": _text_sha256(str(sample.get("source_text") or "")),
        }
    )


def _finalize_group(
    group: Mapping[str, Any],
    *,
    existing_label: Mapping[str, Any] | None,
) -> dict[str, Any]:
    sample_id = _gold_sample_id(str(group["dedupe_key"]))
    label = _mapping(existing_label)
    return {
        "sample_id": sample_id,
        "dedupe_key": str(group["dedupe_key"]),
        "project_ids": sorted(group["project_ids"]),
        "project_names": sorted(group["project_names"]),
        "source_urls": sorted(group["source_urls"]),
        "document_kinds": sorted(group["document_kinds"]),
        "jurisdictions": sorted(group["jurisdictions"]),
        "source_profile_ids": sorted(group["source_profile_ids"]),
        "observation_refs": sorted(
            group["observation_refs"],
            key=lambda item: (
                item["source_manifest_path"],
                item["sample_id"],
            ),
        ),
        "baseline_prediction": "REVIEW_REQUIRED"
        if group["baseline_review"]
        else "PASS",
        "current_prediction": "REVIEW_REQUIRED"
        if group["current_review"]
        else "PASS",
        "prediction_changed": bool(
            group["baseline_review"] != group["current_review"]
        ),
        "file_review_rule_code": FILE_REVIEW_RULE_CODE,
        "tailored_review_rule_code": TAILORED_REVIEW_RULE_CODE,
        "file_review_reasons": sorted(group["file_review_reasons"]),
        "tailored_review_reasons": sorted(group["tailored_review_reasons"]),
        "truth_label": label.get("truth_label"),
        "truth_label_state": str(
            label.get("truth_label_state") or "PENDING_HUMAN_REVIEW"
        ),
        "reviewer_id": str(label.get("reviewer_id") or ""),
        "reviewed_at": str(label.get("reviewed_at") or ""),
        "truth_evidence_refs": [
            str(value)
            for value in list(label.get("truth_evidence_refs") or [])
            if str(value or "").strip()
        ],
        "review_note": str(label.get("review_note") or ""),
        "external_second_review_state": str(
            label.get("external_second_review_state") or "NOT_REVIEWED"
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _gold_sample_id(dedupe_key: str) -> str:
    return "S5-GOLD-" + hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()[:16]


def _existing_labels(path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(path)
    return {
        str(item.get("sample_id") or ""): dict(item)
        for item in list(payload.get("labels") or [])
        if isinstance(item, Mapping) and item.get("sample_id")
    }


def _validate_labels(
    rows: list[Mapping[str, Any]],
    *,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    allowed = {str(value) for value in list(contract.get("allowed_truth_labels") or [])}
    evaluation_labels = {
        str(value) for value in list(contract.get("evaluation_labels") or [])
    }
    accepted_state = str(
        contract.get("accepted_truth_label_state") or "HUMAN_REVIEWED"
    )
    valid: list[str] = []
    valid_eval: list[str] = []
    required: list[str] = []
    errors: list[dict[str, Any]] = []
    for row in rows:
        sample_id = str(row.get("sample_id") or "")
        label = str(row.get("truth_label") or "")
        evidence_refs = list(row.get("truth_evidence_refs") or [])
        valid_row = bool(
            label in allowed
            and str(row.get("truth_label_state") or "") == accepted_state
            and str(row.get("reviewer_id") or "").strip()
            and str(row.get("reviewed_at") or "").strip()
            and evidence_refs
            and str(row.get("review_note") or "").strip()
        )
        if valid_row:
            valid.append(sample_id)
            if label in evaluation_labels:
                valid_eval.append(sample_id)
        else:
            required.append(sample_id)
            errors.append(
                {
                    "sample_id": sample_id,
                    "truth_label": label or None,
                    "truth_label_state": str(row.get("truth_label_state") or ""),
                    "reason": "human_truth_label_or_review_evidence_incomplete",
                }
            )
    return {
        "valid_label_sample_ids": valid,
        "valid_evaluation_sample_ids": valid_eval,
        "truth_label_required_sample_ids": required,
        "truth_label_errors": errors,
        "truth_label_state_counts": _counts(
            str(row.get("truth_label_state") or "") for row in rows
        ),
    }


def _comparison_metrics(
    rows: list[Mapping[str, Any]],
    *,
    valid_labeled_sample_ids: set[str],
) -> dict[str, Any]:
    labeled = [
        row
        for row in rows
        if str(row.get("sample_id") or "") in valid_labeled_sample_ids
        and row.get("truth_label") in {"PASS", "REVIEW_REQUIRED"}
    ]
    baseline = _truth_metrics(labeled, prediction_field="baseline_prediction")
    current = _truth_metrics(labeled, prediction_field="current_prediction")
    changed = [row for row in rows if row.get("prediction_changed")]
    false_positive = [
        _error_sample(row, error_type="FALSE_POSITIVE")
        for row in labeled
        if row.get("current_prediction") == "REVIEW_REQUIRED"
        and row.get("truth_label") == "PASS"
    ]
    false_negative = [
        _error_sample(row, error_type="FALSE_NEGATIVE")
        for row in labeled
        if row.get("current_prediction") == "PASS"
        and row.get("truth_label") == "REVIEW_REQUIRED"
    ]
    return {
        "baseline_rule_version": BASELINE_RULE_VERSION,
        "current_rule_version": CURRENT_RULE_VERSION,
        "labeled_evaluation_sample_count": len(labeled),
        "changed_prediction_count": len(changed),
        "changed_prediction_sample_ids": [row["sample_id"] for row in changed],
        "baseline_truth_metrics": baseline,
        "current_truth_metrics": current,
        "current_false_positive_samples": false_positive,
        "current_false_negative_samples": false_negative,
        "formal_rule_threshold_mutation_enabled": False,
    }


def _truth_metrics(
    rows: list[Mapping[str, Any]],
    *,
    prediction_field: str,
) -> dict[str, Any]:
    if not rows:
        return {
            "sample_count": 0,
            "true_positive": None,
            "true_negative": None,
            "false_positive": None,
            "false_negative": None,
            "precision": None,
            "recall": None,
            "review_share": None,
            "false_positive_rate": None,
            "false_negative_rate": None,
            "metrics_state": "WITHHELD_NO_VALID_HUMAN_TRUTH_LABELS",
        }
    tp = sum(
        row.get(prediction_field) == "REVIEW_REQUIRED"
        and row.get("truth_label") == "REVIEW_REQUIRED"
        for row in rows
    )
    tn = sum(
        row.get(prediction_field) == "PASS" and row.get("truth_label") == "PASS"
        for row in rows
    )
    fp = sum(
        row.get(prediction_field) == "REVIEW_REQUIRED"
        and row.get("truth_label") == "PASS"
        for row in rows
    )
    fn = sum(
        row.get(prediction_field) == "PASS"
        and row.get("truth_label") == "REVIEW_REQUIRED"
        for row in rows
    )
    review_count = sum(row.get(prediction_field) == "REVIEW_REQUIRED" for row in rows)
    return {
        "sample_count": len(rows),
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": _ratio(tp, tp + fp),
        "recall": _ratio(tp, tp + fn),
        "review_share": _ratio(review_count, len(rows)),
        "false_positive_rate": _ratio(fp, fp + tn),
        "false_negative_rate": _ratio(fn, fn + tp),
        "metrics_state": "CALCULATED_FROM_HUMAN_TRUTH_LABELS",
    }


def _error_sample(row: Mapping[str, Any], *, error_type: str) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id"),
        "error_type": error_type,
        "truth_label": row.get("truth_label"),
        "current_prediction": row.get("current_prediction"),
        "project_ids": row.get("project_ids"),
        "source_urls": row.get("source_urls"),
        "reviewer_id": row.get("reviewer_id"),
        "truth_evidence_refs": row.get("truth_evidence_refs"),
    }


def _write_label_csv(path: Path, rows: list[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "sample_id",
                "project_ids",
                "project_names",
                "document_kinds",
                "source_profile_ids",
                "baseline_prediction",
                "current_prediction",
                "truth_label",
                "truth_label_state",
                "reviewer_id",
                "reviewed_at",
                "truth_evidence_refs",
                "review_note",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: " | ".join(str(value) for value in row.get(key, []))
                    if isinstance(row.get(key), list)
                    else row.get(key)
                    for key in writer.fieldnames
                }
            )


def _review_share(values: Iterable[str]) -> float | None:
    predictions = list(values)
    return _ratio(
        sum(value == "REVIEW_REQUIRED" for value in predictions),
        len(predictions),
    )


def _counts(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(str(value or "") for value in values).items()))


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator > 0 else None


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _file_sha256(path: Path) -> str:
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""


def _fingerprint(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _markdown_summary(summary: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# Stage5 real-project rule calibration",
            "",
            f"- Evaluation state: `{summary['evaluation_state']}`",
            f"- Unique real projects: `{summary['unique_real_project_count']}` (minimum `{summary['minimum_unique_real_project_count']}`)",
            f"- Valid human truth labels: `{summary['truth_label_valid_count']}`",
            f"- Truth labels still required: `{summary['truth_label_required_count']}`",
            f"- Baseline REVIEW share: `{summary['baseline_review_share']}`",
            f"- Current REVIEW share: `{summary['current_review_share']}`",
            "- False positives/negatives are withheld, not reported as zero, until human truth labels are complete.",
            "- Formal rule thresholds are never mutated automatically.",
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build Stage5 deduplicated real-project truth-label and calibration packet"
    )
    parser.add_argument("--input-root", default=str(DEFAULT_INPUT_ROOT))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--truth-label-contract", default=str(DEFAULT_CONTRACT))
    args = parser.parse_args()
    result = build_stage5_real_project_rule_calibration(
        input_root=args.input_root,
        truth_label_contract_json=args.truth_label_contract,
        output_root=args.output_root,
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0 if result["safe_to_execute"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
