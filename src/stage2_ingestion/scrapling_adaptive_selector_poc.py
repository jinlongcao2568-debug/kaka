from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage2_ingestion.scrapling_adaptive_selector_registry import (
    SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID,
    ScraplingAdaptiveSelectorProbe,
    build_scrapling_adaptive_selector_registry_readback,
    build_scrapling_adaptive_selector_summary,
)


STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_KIND = "stage2_scrapling_adaptive_selector_poc_v1"
STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_VERSION = "1.0"
DEFAULT_OUTPUT_DIR = Path("tmp/evaluation-real-samples/stage2-scrapling-adaptive-selector-poc-v1")


_TRAIN_HTML = """
<html>
  <body>
    <main class="notice-page">
      <h1 class="notice-title">测试道路工程中标候选人公示</h1>
      <section class="notice-body">
        <p>第一中标候选人：测试建设有限公司</p>
        <p>项目负责人：张三</p>
      </section>
      <a class="download-link" href="/files/candidate-notice.pdf">候选人公示附件</a>
    </main>
  </body>
</html>
"""

_REPLAY_HTML_WITH_SELECTOR_DRIFT = """
<html>
  <body>
    <article class="notice-page-v2">
      <div class="renamed-title">测试道路工程中标候选人公示</div>
      <div class="renamed-body">
        <p>第一中标候选人：测试建设有限公司</p>
        <p>项目负责人：张三</p>
      </div>
      <a class="file-entry" href="/files/candidate-notice.pdf">候选人公示附件</a>
    </article>
  </body>
</html>
"""

_POC_PROBES = (
    ScraplingAdaptiveSelectorProbe(
        probe_id="notice_title",
        label="公告标题",
        selector_kind="css",
        selectors=(".notice-title",),
        max_records=1,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="notice_body",
        label="公告正文",
        selector_kind="css",
        selectors=(".notice-body",),
        max_records=1,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="attachment_link",
        label="附件入口",
        selector_kind="css",
        selectors=(".download-link",),
        max_records=1,
    ),
)


def build_stage2_scrapling_adaptive_selector_poc(
    *,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    percentage: int = 20,
) -> dict[str, Any]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    storage_file = out / "scrapling-adaptive-selector-registry-v1.sqlite"
    _remove_previous_storage(storage_file)

    base_url = "https://example.gov/detail/2026-001.html"
    train_readback = build_scrapling_adaptive_selector_registry_readback(
        _TRAIN_HTML,
        base_url=base_url,
        storage_file=storage_file,
        train=True,
        allow_adaptive_relocation=False,
        percentage=percentage,
        probes=_POC_PROBES,
    )
    replay_readback = build_scrapling_adaptive_selector_registry_readback(
        _REPLAY_HTML_WITH_SELECTOR_DRIFT,
        base_url=base_url,
        storage_file=storage_file,
        train=False,
        allow_adaptive_relocation=True,
        percentage=percentage,
        probes=_POC_PROBES,
    )
    train_summary = build_scrapling_adaptive_selector_summary(train_readback)
    replay_summary = build_scrapling_adaptive_selector_summary(replay_readback)
    replay_adaptive_summary = dict(replay_summary.get("adaptive_selector_summary") or {})
    manifest = {
        "kind": STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_KIND,
        "version": STAGE2_SCRAPLING_ADAPTIVE_SELECTOR_POC_VERSION,
        "generated_at": utc_now_iso(),
        "adapter_id": SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID,
        "no_live_request_all_true": bool(train_readback.get("no_live_request"))
        and bool(replay_readback.get("no_live_request")),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "storage_file": str(storage_file),
        "percentage": percentage,
        "train_summary": train_summary,
        "replay_summary": replay_summary,
        "train_probe_records": train_readback.get("probe_records") or [],
        "replay_probe_records": replay_readback.get("probe_records") or [],
        "acceptance": {
            "trained_probe_count": int(
                dict(train_summary.get("adaptive_selector_summary") or {}).get("trained_probe_count") or 0
            ),
            "adaptive_relocated_probe_count": int(replay_adaptive_summary.get("adaptive_relocated_probe_count") or 0),
            "selector_drift_recovered": int(replay_adaptive_summary.get("adaptive_relocated_probe_count") or 0)
            >= len(_POC_PROBES),
            "expected_probe_count": len(_POC_PROBES),
        },
    }
    json_path = out / "stage2-scrapling-adaptive-selector-poc-v1.json"
    md_path = out / "stage2-scrapling-adaptive-selector-poc-v1.md"
    json_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(manifest), encoding="utf-8")
    return {
        "manifest": manifest,
        "json_path": str(json_path),
        "markdown_path": str(md_path),
    }


def _markdown_report(manifest: Mapping[str, Any]) -> str:
    acceptance = dict(manifest.get("acceptance") or {})
    train_summary = dict(dict(manifest.get("train_summary") or {}).get("adaptive_selector_summary") or {})
    replay_summary = dict(dict(manifest.get("replay_summary") or {}).get("adaptive_selector_summary") or {})
    lines = [
        "# Stage2 Scrapling Adaptive Selector PoC v1",
        "",
        f"- generated_at: {manifest.get('generated_at')}",
        f"- adapter_id: {manifest.get('adapter_id')}",
        f"- no_live_request_all_true: {manifest.get('no_live_request_all_true')}",
        f"- selector_drift_recovered: {acceptance.get('selector_drift_recovered')}",
        f"- trained_probe_count: {acceptance.get('trained_probe_count')}",
        f"- adaptive_relocated_probe_count: {acceptance.get('adaptive_relocated_probe_count')}",
        "",
        "## Train",
        "",
        f"- matched_probe_ids: {', '.join(train_summary.get('matched_probe_ids') or [])}",
        f"- trained_probe_count: {train_summary.get('trained_probe_count')}",
        "",
        "## Replay After Selector Drift",
        "",
        f"- matched_probe_ids: {', '.join(replay_summary.get('matched_probe_ids') or [])}",
        f"- adaptive_relocated_probe_ids: {', '.join(replay_summary.get('adaptive_relocated_probe_ids') or [])}",
        f"- adaptive_relocated_probe_count: {replay_summary.get('adaptive_relocated_probe_count')}",
        "",
        "## Boundary",
        "",
        "- This PoC only uses local HTML strings and Scrapling parser/adaptive selector storage.",
        "- It does not perform HTTP fetch, browser automation, stealth behavior, customer output, or legal conclusion.",
    ]
    return "\n".join(lines) + "\n"


def _remove_previous_storage(storage_file: Path) -> None:
    for path in (storage_file, Path(f"{storage_file}-wal"), Path(f"{storage_file}-shm")):
        if path.exists():
            path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage2 Scrapling adaptive selector local PoC.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--percentage", type=int, default=20)
    args = parser.parse_args(argv)
    result = build_stage2_scrapling_adaptive_selector_poc(
        output_dir=args.output_dir,
        percentage=args.percentage,
    )
    print(json.dumps(result["manifest"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
