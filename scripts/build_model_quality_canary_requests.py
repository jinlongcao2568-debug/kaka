from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from shared.model_quality_evaluation import (  # noqa: E402
    MODEL_QUALITY_GOLDEN_REF,
    build_real_provider_quality_request_documents,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the 12 governed real-provider shadow quality request files."
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    if output_dir == ROOT:
        print("output directory cannot be the repository root", file=sys.stderr)
        return 2
    output_dir.mkdir(parents=True, exist_ok=True)
    entries = build_real_provider_quality_request_documents()
    manifest_cases: list[dict] = []
    manifest_path = output_dir / "model-quality-canary-manifest.json"
    try:
        target_paths = [
            output_dir / f"{entry['case_id']}.request.json" for entry in entries
        ] + [manifest_path]
        existing = [path for path in target_paths if path.exists()]
        if existing and not args.overwrite:
            raise FileExistsError(f"output already exists: {existing[0]}")
        for entry in entries:
            path = output_dir / f"{entry['case_id']}.request.json"
            path.write_text(
                json.dumps(entry["request"], ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            manifest_cases.append(
                {
                    "case_id": entry["case_id"],
                    "request_path": str(path),
                    "request_sha256": entry["request_sha256"],
                    "manual_checks": entry["manual_checks"],
                    "result_path": None,
                    "human_review": {
                        "accepted": None,
                        "hallucination_found": None,
                        "boundary_leak_found": None,
                        "prohibited_conclusion_found": None,
                        "reviewer_ref": None,
                    },
                }
            )
        manifest = {
            "state": "REQUESTS_BUILT_NOT_EXECUTED",
            "golden_ref": MODEL_QUALITY_GOLDEN_REF,
            "case_count": len(manifest_cases),
            "real_provider_call_executed": False,
            "cases": manifest_cases,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "state": "REQUESTS_BUILT_NOT_EXECUTED",
                "case_count": len(manifest_cases),
                "manifest": str(manifest_path),
                "real_provider_call_executed": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
