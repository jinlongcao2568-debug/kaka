from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.model_quality_evaluation import (  # noqa: E402
    evaluate_real_provider_results,
    run_offline_model_quality_goldens,
)


def _read_json(path: Path) -> Any:
    if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError(f"input file is missing or too large: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Mapping[str, Any], *, overwrite: bool) -> None:
    resolved = path.resolve()
    if resolved == ROOT:
        raise ValueError("output path cannot be the repository root")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and not overwrite:
        raise FileExistsError(f"output already exists: {resolved}")
    resolved.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _materialize_case_results(items: list[Any], *, base_dir: Path) -> list[Mapping[str, Any]]:
    results: list[Mapping[str, Any]] = []
    for raw in items:
        if not isinstance(raw, Mapping):
            raise ValueError("each real-provider case result must be an object")
        item = dict(raw)
        result = item.get("result")
        if not isinstance(result, Mapping):
            result_path_value = str(item.get("result_path") or "").strip()
            if not result_path_value:
                raise ValueError(f"case {item.get('case_id')} has no result or result_path")
            result_path = Path(result_path_value)
            if not result_path.is_absolute():
                result_path = base_dir / result_path
            result = _read_json(result_path)
        if not isinstance(result, Mapping):
            raise ValueError(f"case {item.get('case_id')} result must be a JSON object")
        results.append(
            {
                "case_id": item.get("case_id"),
                "result": dict(result),
                "human_review": dict(item.get("human_review") or {}),
            }
        )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run offline model protocol goldens or evaluate captured real-provider shadow results."
    )
    parser.add_argument("--mode", choices=("offline", "real-results"), default="offline")
    parser.add_argument("--input", type=Path, help="Captured real-provider case result JSON.")
    parser.add_argument("--pricing-snapshot", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    try:
        if args.mode == "offline":
            report = run_offline_model_quality_goldens()
        else:
            if args.input is None:
                raise ValueError("--input is required for real-results mode")
            document = _read_json(args.input)
            case_results = document.get("cases") if isinstance(document, Mapping) else document
            if not isinstance(case_results, list):
                raise ValueError("real-provider input must be an array or an object with cases")
            case_results = _materialize_case_results(
                case_results,
                base_dir=args.input.resolve().parent,
            )
            pricing = _read_json(args.pricing_snapshot) if args.pricing_snapshot else None
            baseline = _read_json(args.baseline) if args.baseline else None
            report = evaluate_real_provider_results(
                case_results,
                pricing_snapshot=pricing if isinstance(pricing, Mapping) else None,
                baseline_report=baseline if isinstance(baseline, Mapping) else None,
            )
        _write_json(args.output, report, overwrite=args.overwrite)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"state": "FAILED", "reason": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    decision = dict(report.get("release_decision") or {})
    print(
        json.dumps(
            {
                "report_id": report.get("report_id"),
                "evaluation_mode": report.get("evaluation_mode"),
                "output": str(args.output.resolve()),
                "release_decision": decision,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
