from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.playwright_challenge_resolver import PlaywrightAttachmentChallengeResolver
from stage2_ingestion.real_public_url_fetcher import RealPublicEntryFetcher


GUANGZHOU_DETAIL_TRANSPORT_DIAGNOSTICS_KIND = "guangzhou_detail_transport_diagnostics_manifest"
GUANGZHOU_PROFILE_ID = "GUANGZHOU-YWTB-CONSTRUCTION-LIST"


def build_guangzhou_detail_transport_diagnostics(
    *,
    input_root: str | Path,
    output_root: str | Path,
    project_ids: list[str] | None = None,
    flow_nos: list[str] | None = None,
    execute: bool = False,
    fetcher: Any | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    input_path = Path(input_root)
    output_path = Path(output_root)
    output_path.mkdir(parents=True, exist_ok=True)
    requested_projects = {str(item).strip() for item in list(project_ids or []) if str(item).strip()}
    requested_flow_nos = {_flow_no(item) for item in list(flow_nos or []) if str(item).strip()}
    items = _load_strategy_items(input_path)
    if requested_projects:
        items = [item for item in items if str(item.get("project_id") or "") in requested_projects]
    if requested_flow_nos:
        items = [item for item in items if _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")) in requested_flow_nos]
    items = [item for item in items if str(item.get("source_url") or "").strip()]

    active_fetcher = fetcher
    if active_fetcher is None and execute:
        active_fetcher = RealPublicEntryFetcher(
            attachment_challenge_resolver=PlaywrightAttachmentChallengeResolver.from_environment(),
            automated_challenge_resolution_enabled=True,
            repository=None,
        )

    records: list[dict[str, Any]] = []
    for item in items:
        records.append(
            _diagnose_item(
                item=item,
                fetcher=active_fetcher,
                execute=execute,
            )
        )

    summary = {
        "project_count": len({str(item.get("project_id") or "") for item in records if item.get("project_id")}),
        "detail_url_count": len(records),
        "fetched_count": sum(1 for item in records if item.get("detail_transport_state") == "FETCHED"),
        "failed_count": sum(1 for item in records if item.get("detail_transport_state") not in {"FETCHED", "PLANNED"}),
        "planned_count": sum(1 for item in records if item.get("detail_transport_state") == "PLANNED"),
        "failure_taxonomy_counts": _counts(
            reason for item in records for reason in list(item.get("failure_taxonomy") or [])
        ),
        "route_state_counts": _counts(
            f"{attempt.get('route', '')}:{attempt.get('state', '')}"
            for item in records
            for attempt in list(item.get("detail_transport_attempts") or [])
            if isinstance(attempt, Mapping)
        ),
        "detail_transport_attempt_count": sum(
            len(list(item.get("detail_transport_attempts") or []))
            for item in records
        ),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest = {
        "manifest_kind": GUANGZHOU_DETAIL_TRANSPORT_DIAGNOSTICS_KIND,
        "manifest_version": 1,
        "adapter_id": "guangzhou-detail-transport-diagnostics-v1",
        "created_at": created,
        "input_root": str(input_path),
        "requested_project_ids": sorted(requested_projects),
        "requested_flow_nos": sorted(requested_flow_nos),
        "execute": bool(execute),
        "items": records,
        "summary": summary,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    manifest["manifest_id"] = "GUANGZHOU-DETAIL-TRANSPORT-" + _fingerprint(
        {"items": records, "created_at": created}
    )[:16]
    result = {
        "safe_to_execute": True,
        "blocking_reasons": [],
        "manifest": manifest,
        "summary": summary,
    }
    (output_path / "detail-transport-diagnostics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_path / "manual-detail-transport-check-table.json").write_text(
        json.dumps(
            {
                "items": [
                    {
                        "project_id": item.get("project_id"),
                        "flow_no": item.get("flow_no"),
                        "project_name": item.get("project_name"),
                        "source_url": item.get("source_url"),
                        "detail_transport_state": item.get("detail_transport_state"),
                        "failure_taxonomy": item.get("failure_taxonomy"),
                        "detail_transport_attempt_count": len(list(item.get("detail_transport_attempts") or [])),
                    }
                    for item in records
                ],
                "customer_visible_allowed": False,
                "no_legal_conclusion": True,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


def _diagnose_item(*, item: Mapping[str, Any], fetcher: Any | None, execute: bool) -> dict[str, Any]:
    source_url = str(item.get("source_url") or "")
    record = {
        "project_id": str(item.get("project_id") or ""),
        "project_name": str(item.get("project_name") or ""),
        "flow_no": _flow_no(item.get("flow_no") or item.get("guangzhou_flow_no")),
        "flow_title": str(item.get("flow_title") or ""),
        "document_kind": str(item.get("document_kind") or ""),
        "source_url": source_url,
        "detail_transport_state": "PLANNED",
        "http_status": None,
        "detail_transport_attempts": [],
        "failure_taxonomy": [],
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }
    if not execute:
        return record
    if fetcher is None:
        record["detail_transport_state"] = "FAILED"
        record["failure_taxonomy"] = ["detail_fetcher_unavailable"]
        return record
    carrier = fetcher.fetch_candidate_detail_url(source_url, profile_id=GUANGZHOU_PROFILE_ID)
    record["detail_transport_state"] = str(carrier.get("status") or "UNKNOWN")
    record["http_status"] = carrier.get("http_status")
    record["detail_transport_attempts"] = list(carrier.get("detail_transport_attempts") or [])
    record["failure_taxonomy"] = _failure_taxonomy_from_carrier(carrier)
    return record


def _load_strategy_items(input_root: Path) -> list[dict[str, Any]]:
    analysis_path = input_root / "analysis-plan.json"
    if analysis_path.exists():
        payload = _load_json(analysis_path)
        manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
        return [
            dict(item)
            for item in list((manifest or {}).get("items") or [])
            if isinstance(item, Mapping)
        ]
    run_path = input_root / "run-manifest.json"
    payload = _load_json(run_path)
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), Mapping) else payload
    return [
        dict(item)
        for item in list((manifest or {}).get("project_sample_items") or [])
        if isinstance(item, Mapping)
    ]


def _failure_taxonomy_from_carrier(carrier: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    raw = carrier.get("failure_taxonomy")
    if isinstance(raw, Mapping):
        for key in ("failure_class", "direct_fetch_failure_class", "resolver_error"):
            value = str(raw.get(key) or "").strip()
            if value:
                out.append(value if key == "failure_class" else f"{key}:{value}")
        for attempt in list(raw.get("detail_transport_attempts") or []):
            if isinstance(attempt, Mapping):
                out.extend(str(value) for value in list(attempt.get("failure_taxonomy") or []) if str(value))
        out.extend(str(value) for value in list(raw.get("detail_transport_failure_flags") or []) if str(value))
    else:
        out.extend(str(value) for value in list(raw or []) if str(value))
    out.extend(str(value) for value in list(carrier.get("degraded_reasons") or []) if str(value))
    out.extend(
        str(value)
        for attempt in list(carrier.get("detail_transport_attempts") or [])
        if isinstance(attempt, Mapping)
        for value in list(attempt.get("failure_taxonomy") or [])
        if str(value)
    )
    if carrier.get("detail_fetch_repair_state"):
        out.append(str(carrier.get("detail_fetch_repair_state")))
    return list(dict.fromkeys(out))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _flow_no(value: Any) -> str:
    text = str(value or "").strip()
    if text.isdigit() and len(text) == 1:
        return f"0{text}"
    return text


def _counts(values: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    for value in values:
        text = str(value or "").strip()
        if text:
            out[text] = out.get(text, 0) + 1
    return dict(sorted(out.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Guangzhou detail transport diagnostics.")
    parser.add_argument("--input-root", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--project-ids", default="")
    parser.add_argument("--flow-nos", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_guangzhou_detail_transport_diagnostics(
        input_root=args.input_root,
        output_root=args.output_root,
        project_ids=[item.strip() for item in args.project_ids.split(",") if item.strip()],
        flow_nos=[item.strip() for item in args.flow_nos.split(",") if item.strip()],
        execute=bool(args.execute),
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("guangzhou detail transport diagnostics built")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
