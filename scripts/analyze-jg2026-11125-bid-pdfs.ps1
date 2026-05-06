param(
    [string]$PdfRoot = "C:\Users\92407\Downloads",
    [string]$OutputJsonl = "handoff\jg2026_11125_bid_pdf_forensics.jsonl",
    [string]$OutputJson = "handoff\jg2026_11125_bid_pdf_forensics.summary.json",
    [string]$OutputMarkdown = "handoff\jg2026_11125_bid_pdf_forensics.md",
    [string]$AssetsDir = "handoff\jg2026_11125_bid_pdf_forensics_assets",
    [string]$QualificationSummary = "handoff\jg2026_11125_pm_qualification_rerun.summary.json",
    [int]$MaxPages = 0,
    [int]$RenderDpi = 72,
    [int]$AssetDpi = 120,
    [int]$OcrSamplePages = 3,
    [int]$Workers = 2,
    [int]$VisualMaxPagesPerPdf = 0
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:JG2026_11125_PDF_ROOT = $PdfRoot
$env:JG2026_11125_OUTPUT_JSONL = $OutputJsonl
$env:JG2026_11125_OUTPUT_JSON = $OutputJson
$env:JG2026_11125_OUTPUT_MD = $OutputMarkdown
$env:JG2026_11125_ASSETS_DIR = $AssetsDir
$env:JG2026_11125_QUALIFICATION_SUMMARY = $QualificationSummary
$env:JG2026_11125_MAX_PAGES = [string]$MaxPages
$env:JG2026_11125_RENDER_DPI = [string]$RenderDpi
$env:JG2026_11125_ASSET_DPI = [string]$AssetDpi
$env:JG2026_11125_OCR_SAMPLE_PAGES = [string]$OcrSamplePages
$env:JG2026_11125_WORKERS = [string]$Workers
$env:JG2026_11125_VISUAL_MAX_PAGES_PER_PDF = [string]$VisualMaxPagesPerPdf

$python = @'
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage4_verification.bid_pdf_forensics import (
    BidPdfTarget,
    analyze_bid_pdf_targets,
    write_forensics_outputs,
)


def main() -> None:
    pdf_root = Path(os.environ["JG2026_11125_PDF_ROOT"])
    targets = [
        BidPdfTarget("中铁十八局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁十八局集团有限公司.pdf"),
        BidPdfTarget("中铁八局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁八局集团有限公司.pdf"),
        BidPdfTarget("中铁十四局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁十四局集团有限公司.pdf"),
        BidPdfTarget("中铁一局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁一局集团有限公司.pdf"),
        BidPdfTarget("中铁五局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁五局集团有限公司.pdf"),
        BidPdfTarget("中铁二局集团有限公司", pdf_root / "投标文件公开JG2026-11125中铁二局集团有限公司.pdf"),
        BidPdfTarget(
            "中国水利水电第十四工程局有限公司",
            pdf_root / "投标文件公开JG2026-11125中国水利水电第十四工程局有限公司.pdf",
            rank_role="first_candidate",
        ),
    ]

    summary = analyze_bid_pdf_targets(
        targets,
        assets_dir=os.environ["JG2026_11125_ASSETS_DIR"],
        qualification_summary_path=os.environ.get("JG2026_11125_QUALIFICATION_SUMMARY") or None,
        max_pages=int(os.environ.get("JG2026_11125_MAX_PAGES") or "0"),
        render_dpi=int(os.environ.get("JG2026_11125_RENDER_DPI") or "72"),
        asset_dpi=int(os.environ.get("JG2026_11125_ASSET_DPI") or "120"),
        ocr_sample_pages=int(os.environ.get("JG2026_11125_OCR_SAMPLE_PAGES") or "3"),
        workers=int(os.environ.get("JG2026_11125_WORKERS") or "1"),
        visual_max_pages_per_pdf=int(os.environ.get("JG2026_11125_VISUAL_MAX_PAGES_PER_PDF") or "0"),
    )
    write_forensics_outputs(
        summary,
        output_jsonl=os.environ["JG2026_11125_OUTPUT_JSONL"],
        output_json=os.environ["JG2026_11125_OUTPUT_JSON"],
        output_markdown=os.environ["JG2026_11125_OUTPUT_MD"],
    )
    print(
        json.dumps(
            {
                "jsonl": os.environ["JG2026_11125_OUTPUT_JSONL"],
                "summary": os.environ["JG2026_11125_OUTPUT_JSON"],
                "markdown": os.environ["JG2026_11125_OUTPUT_MD"],
                "assets_dir": os.environ["JG2026_11125_ASSETS_DIR"],
                "record_count": summary.get("record_count"),
                "status_counts": summary.get("status_counts"),
                "repeated_stamp_cluster_count": summary.get("repeated_stamp_cluster_count"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
'@

Push-Location $repoRoot
try {
    $tmp = New-TemporaryFile
    Set-Content -LiteralPath $tmp -Value $python -Encoding UTF8
    python -X utf8 $tmp
}
finally {
    if ($tmp) {
        Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    }
    Pop-Location
}
