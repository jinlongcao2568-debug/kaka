from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.model_provider_runtime import (  # noqa: E402
    ModelAssistRequest,
    ModelProviderExecutionError,
    execute_governed_model_assist_with_fallback,
    model_provider_readiness,
)


def _load_request(path: Path) -> ModelAssistRequest:
    if not path.is_file() or path.stat().st_size > 64 * 1024:
        raise ValueError("canary request file is missing or exceeds 64 KiB")
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, Mapping):
        raise ValueError("canary request must be a JSON object")
    source_refs = document.get("source_refs") or []
    sanitized_input = document.get("sanitized_input") or {}
    if not isinstance(source_refs, list) or not isinstance(sanitized_input, Mapping):
        raise ValueError("source_refs must be an array and sanitized_input must be an object")
    return ModelAssistRequest(
        request_id=str(document.get("request_id") or ""),
        task_kind=str(document.get("task_kind") or ""),
        input_data_classification=str(document.get("input_data_classification") or ""),
        sanitized_input=dict(sanitized_input),
        source_refs=tuple(str(item) for item in source_refs),
        prompt_template_id=str(
            document.get("prompt_template_id") or "PROMPT_GOVERNED_PROVIDER_SHADOW_V1"
        ),
        prompt_template_version=str(document.get("prompt_template_version") or "1"),
    )


def _write_new_json(path: Path, payload: Mapping[str, Any]) -> None:
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("canary result must be written outside the repository")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    descriptor = os.open(resolved, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run one explicitly approved internal-shadow model provider canary."
    )
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    readiness = model_provider_readiness()
    if readiness.get("state") != "READY_INTERNAL_SHADOW":
        print(
            json.dumps(
                {
                    "state": readiness.get("state"),
                    "mode": readiness.get("mode"),
                    "blocking_reason": readiness.get("blocking_reason")
                    or "model provider internal shadow is not ready",
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    try:
        result = execute_governed_model_assist_with_fallback(_load_request(args.request))
        _write_new_json(args.output, result)
    except (ValueError, OSError, json.JSONDecodeError, ModelProviderExecutionError) as exc:
        category = getattr(exc, "category", "CANARY_INPUT_OR_OUTPUT_ERROR")
        print(json.dumps({"state": "FAILED", "category": category}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "state": result["execution_state"],
                "request_id": result["trace"]["request_id"],
                "result_path": str(args.output.resolve()),
                "customer_visible_enabled": False,
                "formal_fact_write_enabled": False,
            },
            ensure_ascii=False,
        )
    )
    return 0 if result["execution_state"] == "COMPLETED_INTERNAL_SHADOW_REVIEW_REQUIRED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
