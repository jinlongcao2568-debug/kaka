from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from shared.utils import utc_now_iso
from stage1_tasking.region_adapters import resolve_source_quality_policy


CONTROLLED_GRAY_PUBLIC_SOURCE_TARGETS_KIND = "controlled_gray_public_source_targets_v1"
CONTROLLED_GRAY_PUBLIC_SOURCE_TARGETS_VERSION = 1
DEFAULT_SOURCE_TARGETS_JSON = Path("contracts/evaluation/evaluation_real_project_sample_targets.json")
DEFAULT_OUTPUT_ROOT = Path("tmp/evaluation-real-samples/controlled-gray-public-source-targets-v1")


def build_controlled_gray_public_source_targets(
    *,
    source_targets_json: str | Path = DEFAULT_SOURCE_TARGETS_JSON,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    per_target_sample_goal: int = 12,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    source_path = Path(source_targets_json)
    output_dir = Path(output_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_payload = _load_json(source_path)
    source_targets = _records(source_payload.get("targets"))
    sample_goal = max(1, int(per_target_sample_goal))
    derived_targets: list[dict[str, Any]] = []
    target_records: list[dict[str, Any]] = []
    for target in source_targets:
        profile_id = str(target.get("required_fetch_profile_id_optional") or "")
        policy = resolve_source_quality_policy(profile_id)
        if str(policy.get("source_quality_state") or "") != "PRIMARY_FRIENDLY":
            continue
        original_count = _int(target.get("target_count"))
        derived = dict(target)
        derived["target_count"] = max(original_count, sample_goal)
        derived["selection_filters"] = _selection_filters(target, sample_goal=derived["target_count"])
        derived_targets.append(derived)
        target_records.append(
            {
                "target_id": str(target.get("target_id") or ""),
                "jurisdiction": str(target.get("jurisdiction") or ""),
                "document_kind": str(target.get("document_kind") or ""),
                "source_profile_id": profile_id,
                "source_quality_state": str(policy.get("source_quality_state") or ""),
                "original_target_count": original_count,
                "gray_target_count": _int(derived.get("target_count")),
                "selection_filters": list(derived.get("selection_filters") or []),
                "customer_visible_allowed": False,
                "payment_execution_enabled": False,
                "delivery_execution_enabled": False,
                "query_miss_is_not_clearance": True,
                "no_legal_conclusion": True,
            }
        )

    targets_payload = {
        "target_version": int(source_payload.get("target_version") or 1),
        "target_set_id": "controlled-gray-public-source-targets-v1",
        "minimum_total_sample_goal": sum(_int(target.get("target_count")) for target in derived_targets),
        "created_from": "controlled_gray_public_source_targets_v1",
        "source_targets_json": str(source_path),
        "target_policy": {
            "customer_visible_allowed": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
        "targets": derived_targets,
    }
    targets_payload["manifest_sha256"] = _fingerprint(
        {key: value for key, value in targets_payload.items() if key != "manifest_sha256"}
    )
    targets_json = output_dir / "controlled-gray-public-source-targets-v1.json"
    _write_json(targets_json, targets_payload)

    summary = {
        "source_targets_json": str(source_path),
        "derived_targets_json": str(targets_json),
        "source_target_count": len(source_targets),
        "derived_target_count": len(derived_targets),
        "per_target_sample_goal": sample_goal,
        "minimum_total_sample_goal": targets_payload["minimum_total_sample_goal"],
        "source_profile_counts": _counts(record.get("source_profile_id") for record in target_records),
        "document_kind_counts": _counts(record.get("document_kind") for record in target_records),
        "jurisdiction_counts": _counts(record.get("jurisdiction") for record in target_records),
        "customer_visible_allowed": False,
        "external_send_enabled": False,
        "payment_execution_enabled": False,
        "delivery_execution_enabled": False,
        "automatic_refund_enabled": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }
    result = {
        "manifest_kind": CONTROLLED_GRAY_PUBLIC_SOURCE_TARGETS_KIND,
        "manifest_version": CONTROLLED_GRAY_PUBLIC_SOURCE_TARGETS_VERSION,
        "adapter_id": "controlled-gray-public-source-targets-v1",
        "created_at": created,
        "summary": summary,
        "target_table": {"records": target_records, "summary": summary},
        "targets_json": str(targets_json),
        "targets_manifest_sha256": targets_payload["manifest_sha256"],
        "safety": {
            "customer_visible_allowed": False,
            "external_send_enabled": False,
            "payment_execution_enabled": False,
            "delivery_execution_enabled": False,
            "automatic_refund_enabled": False,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
        },
    }
    result["manifest_sha256"] = _fingerprint(
        {key: value for key, value in result.items() if key != "manifest_sha256"}
    )
    _write_json(output_dir / "controlled-gray-public-source-targets-summary-v1.json", result)
    (output_dir / "controlled-gray-public-source-targets-summary-v1.md").write_text(
        _markdown(result),
        encoding="utf-8",
    )
    return result


def _selection_filters(target: Mapping[str, Any], *, sample_goal: int) -> list[str]:
    filters = _dedupe([*_string_list(target.get("selection_filters")), "CONTROLLED_GRAY_SAMPLE_EXPANSION"])
    filters = [value for value in filters if not value.startswith("GRAY_SAMPLE_TARGET_COUNT:")]
    filters.append(f"GRAY_SAMPLE_TARGET_COUNT:{sample_goal}")
    return filters


def _markdown(result: Mapping[str, Any]) -> str:
    summary = _mapping(result.get("summary"))
    lines = [
        "# Controlled Gray Public Source Targets",
        "",
        f"- derived_target_count: {summary.get('derived_target_count')}",
        f"- minimum_total_sample_goal: {summary.get('minimum_total_sample_goal')}",
        f"- per_target_sample_goal: {summary.get('per_target_sample_goal')}",
        f"- targets_json: {result.get('targets_json')}",
        f"- customer_visible_allowed: {str(bool(summary.get('customer_visible_allowed'))).lower()}",
        f"- payment_execution_enabled: {str(bool(summary.get('payment_execution_enabled'))).lower()}",
        f"- delivery_execution_enabled: {str(bool(summary.get('delivery_execution_enabled'))).lower()}",
        "",
        "## Source Profiles",
    ]
    for key, value in _mapping(summary.get("source_profile_counts")).items():
        lines.append(f"- {key}: {value}")
    return "\n".join(lines) + "\n"


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _records(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping) and isinstance(value.get("records"), list):
        value = value.get("records")
    if isinstance(value, list):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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


def _fingerprint(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-targets-json", default=str(DEFAULT_SOURCE_TARGETS_JSON))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--per-target-sample-goal", type=int, default=12)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = build_controlled_gray_public_source_targets(
        source_targets_json=args.source_targets_json,
        output_root=args.output_root,
        per_target_sample_goal=args.per_target_sample_goal,
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
