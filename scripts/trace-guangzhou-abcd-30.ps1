param(
    [int]$Limit = 30,
    [int]$AttachmentCaptureLimit = 5,
    [double]$DetailCaptureTimeBudgetSeconds = 240,
    [string]$OutputStem = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$runRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("kaka-gz-abcd-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Force -Path $runRoot | Out-Null

if (-not $env:KAKA_STORAGE_PATH) {
    $env:KAKA_STORAGE_PATH = Join-Path $runRoot "store.json"
}
if (-not $env:KAKA_OBJECT_STORAGE_PATH) {
    $env:KAKA_OBJECT_STORAGE_PATH = Join-Path $runRoot "objects"
}
$env:PYTHONIOENCODING = "utf-8"
$env:GUANGZHOU_ABCD_LIMIT = [string]$Limit
$env:GUANGZHOU_ABCD_ATTACHMENT_LIMIT = [string]$AttachmentCaptureLimit
$env:GUANGZHOU_ABCD_DETAIL_BUDGET = [string]$DetailCaptureTimeBudgetSeconds
$env:GUANGZHOU_ABCD_OUTPUT_STEM = $OutputStem

$python = @'
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage1_tasking.real_candidate_discovery import RealPublicCandidateDiscoveryService
from stage2_ingestion.real_candidate_capture import RealCandidateStage2CaptureService

LIMIT = int(os.environ.get("GUANGZHOU_ABCD_LIMIT") or "30")
ATTACHMENT_LIMIT = int(os.environ.get("GUANGZHOU_ABCD_ATTACHMENT_LIMIT") or "5")
DETAIL_BUDGET = float(os.environ.get("GUANGZHOU_ABCD_DETAIL_BUDGET") or "240")
OUTPUT_STEM = (os.environ.get("GUANGZHOU_ABCD_OUTPUT_STEM") or "").strip()
NOW = datetime.now().astimezone().isoformat()

CLASS_LABELS = {
    "A_HIGH_CONSTRUCTION_EPC": "A 施工/EPC",
    "B_HIGH_SUPERVISION": "B 监理",
    "C_MEDIUM_DESIGN_SURVEY": "C 设计/勘察",
    "D_LOW_SUPPLIER_SERVICE": "D 设备材料/服务采购",
    "REVIEW_UNCLASSIFIED_ENGINEERING": "REVIEW 待分型",
}
ROLE_REQUIRED_CLASSES = {
    "A_HIGH_CONSTRUCTION_EPC",
    "B_HIGH_SUPERVISION",
    "C_MEDIUM_DESIGN_SURVEY",
    "REVIEW_UNCLASSIFIED_ENGINEERING",
}


def text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def has(value: Any) -> bool:
    return bool(text(value)) and text(value) != "0.0"


def md(value: Any) -> str:
    return text(value).replace("|", "\\|").replace("\n", " ")


def attachment_items(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_url: dict[str, dict[str, Any]] = {}
    for item in list(row.get("same_site_attachment_link_items") or []):
        if not isinstance(item, Mapping):
            continue
        name = text(item.get("text") or item.get("title") or item.get("attachment_link_text"))
        url = text(item.get("url") or item.get("href") or item.get("attachment_url"))
        if not url:
            continue
        by_url[url] = {
            "name": name or url.rsplit("/", 1)[-1][:80],
            "url": url,
            "status": "",
            "snapshot_id": "",
            "blocker_class": "",
            "resolution_route": "",
            "degraded_reasons": [],
        }
    for capture in list(row.get("stage2_attachment_captures") or []):
        if not isinstance(capture, Mapping):
            continue
        url = text(capture.get("attachment_url"))
        name = text(capture.get("attachment_link_text") or capture.get("attachment_filename"))
        if not url:
            continue
        item = by_url.setdefault(
            url,
            {
                "name": name or url.rsplit("/", 1)[-1][:80],
                "url": url,
                "status": "",
                "snapshot_id": "",
                "blocker_class": "",
                "resolution_route": "",
                "degraded_reasons": [],
            },
        )
        if name:
            item["name"] = name
        item["status"] = text(capture.get("attachment_capture_status") or capture.get("status"))
        item["snapshot_id"] = text(capture.get("attachment_snapshot_id_optional") or capture.get("snapshot_id_optional"))
        item["blocker_class"] = text(capture.get("attachment_blocker_class"))
        item["resolution_route"] = text(capture.get("attachment_resolution_route"))
        item["degraded_reasons"] = [
            text(reason)
            for reason in list(capture.get("attachment_degraded_reasons") or capture.get("degraded_reasons") or [])
            if text(reason)
        ]
    return list(by_url.values())[:10]


def attachment_names(row: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for item in attachment_items(row):
        label = re.sub(r"\s+", " ", text(item.get("name"))).strip()
        url = text(item.get("url"))
        if label and url:
            names.append(f"{label} => {url}")
        elif label:
            names.append(label)
        elif url:
            names.append(url)
    return names[:6]


def attachment_status(row: Mapping[str, Any]) -> tuple[dict[str, int], list[str]]:
    statuses: Counter[str] = Counter()
    reasons: list[str] = []
    for capture in list(row.get("stage2_attachment_captures") or []):
        if not isinstance(capture, Mapping):
            continue
        statuses[text(capture.get("attachment_capture_status") or capture.get("status") or "UNKNOWN")] += 1
        for reason in list(capture.get("attachment_degraded_reasons") or capture.get("degraded_reasons") or []):
            reason_text = text(reason)
            if reason_text and reason_text not in reasons:
                reasons.append(reason_text)
    return dict(statuses), reasons[:6]


def source_role_visible(row: Mapping[str, Any]) -> bool:
    return (
        has(row.get("primary_responsible_person_name"))
        or bool(list(row.get("responsible_role_gap_token_hits") or []))
        or text(row.get("responsible_role_gap_source_evidence")) == "captured_text_contains_responsible_role_tokens"
    )


def source_certificate_visible(row: Mapping[str, Any]) -> bool:
    cert_state = text(row.get("project_manager_certificate_no_parse_state"))
    cert_type_state = text(row.get("project_manager_certificate_type_parse_state"))
    return (
        has(row.get("project_manager_certificate_no"))
        or cert_state not in {"", "DETAIL_TEXT_NOT_FOUND"}
        or cert_type_state not in {"", "DETAIL_TEXT_NOT_FOUND"}
        or any(token in list(row.get("responsible_role_gap_token_hits") or []) for token in ("证书编号", "注册编号", "建造师", "注册监理工程师", "注册土木工程师"))
    )


def missing_reason(row: Mapping[str, Any], priority: str, role_required: bool) -> str:
    if has(row.get("primary_responsible_person_name")) and has(row.get("project_manager_certificate_no")):
        return "正文结构化表格已命中负责人和证书号"
    if has(row.get("primary_responsible_person_name")):
        return "正文命中负责人但缺证书号"
    if priority == "D_LOW_SUPPLIER_SERVICE":
        return "D 类不按项目经理/总监缺失处理，走供应商资格、业绩、价格、信用处罚链"
    tokens = list(row.get("responsible_role_gap_token_hits") or [])
    if tokens:
        return "正文有负责人角色词，但表格/联合体/列顺序复杂，Stage3 未结构化命中"
    if role_required:
        return "A/B/C 类应有负责人，但正文未见稳定结构化字段，需附件或 Stage4 公司优先补链"
    return "无需负责人"


def next_route(row: Mapping[str, Any], priority: str, role_required: bool) -> str:
    if priority == "D_LOW_SUPPLIER_SERVICE":
        return "供应商资格/业绩/参数/报价/信用处罚核验；附件验证码续跑仅作补证据"
    if has(row.get("primary_responsible_person_name")):
        return "进 Stage4：公司+人员+证书核验"
    if role_required:
        return "补 Stage3 深表格解析；附件验证码续跑；再走公司优先 Stage4"
    return "人工确认分型"


def row_record(index: int, row: Mapping[str, Any]) -> dict[str, Any]:
    priority = text(row.get("opportunity_priority_class")) or "REVIEW_UNCLASSIFIED_ENGINEERING"
    role_required = priority in ROLE_REQUIRED_CLASSES and priority != "D_LOW_SUPPLIER_SERVICE"
    att_statuses, att_reasons = attachment_status(row)
    role_visible = source_role_visible(row)
    cert_visible = source_certificate_visible(row)
    return {
        "idx": index,
        "type": priority,
        "type_label": CLASS_LABELS.get(priority, priority),
        "engineering_work_lane": text(row.get("engineering_work_lane")),
        "title": text(row.get("project_name")),
        "url": text(row.get("source_url")),
        "company": text(row.get("candidate_company")),
        "responsible_person": text(row.get("primary_responsible_person_name")),
        "responsible_role": text(row.get("primary_responsible_role")),
        "certificate_no": text(row.get("project_manager_certificate_no")),
        "responsible_role_required": role_required,
        "responsible_role_gap_review_required": bool(row.get("responsible_role_gap_review_required")),
        "expected_responsible_role_field": text(row.get("expected_responsible_role_field")),
        "missing_reason": missing_reason(row, priority, role_required),
        "next_route": next_route(row, priority, role_required),
        "attachment_link_count": int(row.get("stage2_attachment_link_count") or 0),
        "attachment_snapshot_count": int(row.get("stage2_attachment_snapshot_count") or 0),
        "attachment_capture_statuses": att_statuses,
        "attachment_degraded_reasons": att_reasons,
        "attachment_items": attachment_items(row),
        "attachments": attachment_names(row),
        "responsible_source_visible": role_visible,
        "responsible_extracted": has(row.get("primary_responsible_person_name")),
        "certificate_source_visible": cert_visible,
        "certificate_extracted": has(row.get("project_manager_certificate_no")),
        "source_trading_process": text(row.get("source_trading_process")),
        "source_dataset_name": text(row.get("source_dataset_name")),
    }


def summarize_by_type(rows: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    summary: dict[str, dict[str, int]] = {}
    for priority in list(CLASS_LABELS):
        group = [row for row in rows if row["type"] == priority]
        if not group:
            continue
        role_required_group = [row for row in group if row["responsible_role_required"]]
        summary[priority] = {
            "count": len(group),
            "company": sum(1 for row in group if row["company"]),
            "responsible_person": sum(1 for row in group if row["responsible_person"]),
            "certificate_no": sum(1 for row in group if row["certificate_no"]),
            "attachment_link": sum(1 for row in group if row["attachment_link_count"] > 0),
            "attachment_snapshot": sum(1 for row in group if row["attachment_snapshot_count"] > 0),
            "role_required_count": len(role_required_group),
            "role_required_missing_count": sum(1 for row in role_required_group if not row["responsible_person"]),
        }
    return summary


payload = {
    "region_codes": ["CN-GD"],
    "project_types": ["construction"],
    "amount_min": 0,
    "amount_max": 200000000,
    "discovery_profile_limit_per_region": 1,
    "now": NOW,
}
discovery = RealPublicCandidateDiscoveryService().discover(payload, now=NOW)
candidates = list(discovery.get("candidates") or [])[:LIMIT]
capture = RealCandidateStage2CaptureService().capture_candidates(
    candidates,
    now=NOW,
    detail_capture_limit=LIMIT,
    attachment_capture_limit=ATTACHMENT_LIMIT,
    reuse_existing_captures=False,
    reparse_existing_snapshots=True,
    detail_capture_time_budget_seconds=DETAIL_BUDGET,
)
rows = [row_record(index, row) for index, row in enumerate(list(capture.get("enriched_candidates") or []), 1)]
type_counts = dict(Counter(row["type"] for row in rows))
by_type = summarize_by_type(rows)
role_required_rows = [row for row in rows if row["responsible_role_required"]]
attachment_blockers = Counter()
attachment_blocker_classes = Counter()
for row in rows:
    for item in row["attachment_items"]:
        for reason in list(item.get("degraded_reasons") or []):
            attachment_blockers[text(reason)] += 1
        if item.get("blocker_class"):
            attachment_blocker_classes[text(item.get("blocker_class"))] += 1

summary = {
    "generated_at": NOW,
    "entry": "https://ywtb.gzggzy.cn/jyfw/002001/002001001/trade_purchasetoplen6.html",
    "filter": {
        "categorynum": "002001001",
        "jsgcggfl": "03",
    },
    "limit": LIMIT,
    "stage1_candidate_count": discovery.get("candidate_count"),
    "source_profile_counts": dict(Counter(text(row.get("source_profile_id")) for row in candidates)),
    "source_dataset_counts": dict(Counter(text(row.get("source_dataset_name")) for row in candidates)),
    "source_trading_process_counts": dict(Counter(text(row.get("source_trading_process")) for row in candidates)),
    "stage2": {
        "detail_snapshot_count": capture.get("detail_snapshot_count"),
        "stage3_parse_success_count": capture.get("stage3_parse_success_count"),
        "attachment_link_count": capture.get("attachment_link_count"),
        "attachment_capture_attempted_count": capture.get("attachment_capture_attempted_count"),
        "attachment_snapshot_count": capture.get("attachment_snapshot_count"),
    },
    "type_counts": type_counts,
    "by_type": by_type,
    "role_required_count": len(role_required_rows),
    "role_required_missing_count": sum(1 for row in role_required_rows if not row["responsible_person"]),
    "d_class_count_not_project_manager_failures": type_counts.get("D_LOW_SUPPLIER_SERVICE", 0),
    "attachment_blockers": dict(attachment_blockers),
    "attachment_blocker_classes": dict(attachment_blocker_classes),
}

date_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
stem = OUTPUT_STEM or f"guangzhou_candidate_30_abcd_trace_{date_suffix}"
out_dir = ROOT / "handoff"
out_dir.mkdir(parents=True, exist_ok=True)
md_path = out_dir / f"{stem}.md"
json_path = out_dir / f"{stem}.json"

lines: list[str] = []
lines.append("# 广州源头中标候选人公示 A/B/C/D 30 条追踪")
lines.append("")
lines.append(f"- 运行时间：{NOW}")
lines.append(f"- 入口：{summary['entry']}")
lines.append("- 口径：建设工程 categorynum=002001001；中标候选人公示 jsgcggfl=03")
lines.append(f"- Stage1 候选：{summary['stage1_candidate_count']}；本报告样本：{len(rows)}")
lines.append(f"- Stage2 详情快照：{summary['stage2']['detail_snapshot_count']}；Stage3 解析成功：{summary['stage2']['stage3_parse_success_count']}")
lines.append(f"- 附件：发现 {summary['stage2']['attachment_link_count']}；尝试 {summary['stage2']['attachment_capture_attempted_count']}；快照 {summary['stage2']['attachment_snapshot_count']}")
lines.append(f"- A/B/C 应有负责人缺失：{summary['role_required_missing_count']}/{summary['role_required_count']}")
lines.append(f"- D 类不计项目经理缺失失败：{summary['d_class_count_not_project_manager_failures']} 条")
lines.append("")
lines.append("## 类型总览")
lines.append("")
lines.append("| 类型 | 数量 | 公司 | 负责人 | 证书 | 附件入口 | 附件快照 | 应有负责人缺失 |")
lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
for priority, stats in by_type.items():
    lines.append(
        f"| {CLASS_LABELS.get(priority, priority)} | {stats['count']} | {stats['company']} | "
        f"{stats['responsible_person']} | {stats['certificate_no']} | {stats['attachment_link']} | "
        f"{stats['attachment_snapshot']} | {stats['role_required_missing_count']} |"
    )
lines.append("")
lines.append("## 明细")
lines.append("")
lines.append("| 序号 | 类型 | 标题 | URL | 公司 | 负责人/角色 | 证书 | 应有负责人 | 负责人诊断 | 附件 | 缺失原因 | 下一步 |")
lines.append("|---:|---|---|---|---|---|---|---|---|---|---|---|")
for row in rows:
    person_role = row["responsible_person"] + (f" / {row['responsible_role']}" if row["responsible_role"] else "")
    role_diag = (
        f"源码角色:{'是' if row['responsible_source_visible'] else '否'}"
        f"<br>负责人抽取:{'是' if row['responsible_extracted'] else '否'}"
        f"<br>源码证书:{'是' if row['certificate_source_visible'] else '否'}"
        f"<br>证书抽取:{'是' if row['certificate_extracted'] else '否'}"
    )
    att = f"{row['attachment_link_count']} 链接 / {row['attachment_snapshot_count']} 快照"
    if row["attachment_capture_statuses"]:
        att += "<br>状态:" + ",".join(f"{key}:{value}" for key, value in row["attachment_capture_statuses"].items())
    if row["attachment_degraded_reasons"]:
        att += "<br>原因:" + ",".join(row["attachment_degraded_reasons"])
    if row["attachments"]:
        att += "<br>" + "<br>".join(md(name) for name in row["attachments"])
    lines.append(
        f"| {row['idx']} | {md(row['type_label'])} | {md(row['title'])} | {md(row['url'])} | "
        f"{md(row['company'])} | {md(person_role)} | {md(row['certificate_no'])} | "
        f"{'是' if row['responsible_role_required'] else '否'} | {md(role_diag)} | {md(att)} | "
        f"{md(row['missing_reason'])} | {md(row['next_route'])} |"
    )
lines.append("")
lines.append("## D 类说明")
lines.append("")
lines.append("D 类不按项目经理/总监缺失失败处理，后续走供应商资格、业绩、参数、报价、信用处罚链；附件验证码续跑只作为补证据。")
lines.append("")
lines.append("## 附件阻断")
lines.append("")
lines.append(json.dumps(summary["attachment_blockers"], ensure_ascii=False, indent=2))
lines.append("")
lines.append("## 附件阻断分类")
lines.append("")
lines.append(json.dumps(summary["attachment_blocker_classes"], ensure_ascii=False, indent=2))

md_path.write_text("\n".join(lines), encoding="utf-8")
json_path.write_text(json.dumps({"summary": summary, "rows": rows}, ensure_ascii=False, indent=2), encoding="utf-8")

print(json.dumps({"markdown": str(md_path), "json": str(json_path), "summary": summary}, ensure_ascii=False, indent=2))
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
