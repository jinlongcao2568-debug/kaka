param(
    [string]$MergedStage4Json = "handoff/guangzhou_candidate_22_stage4_jzsc_merged_retry5_20260504_impl.json",
    [string]$QueuePath = "handoff/guangzhou_stage4_provider_jobs_20260504_impl.json",
    [string]$OutputStem = "guangzhou_stage4_provider_queue_20260504_impl",
    [int]$Limit = 22,
    [int]$MaxAttempts = 3,
    [switch]$RunDueJobs,
    [switch]$EnableLiveGdcic
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$repoRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"
$env:STAGE4_GZ_MERGED_JSON = $MergedStage4Json
$env:STAGE4_GZ_QUEUE_PATH = $QueuePath
$env:STAGE4_GZ_OUTPUT_STEM = $OutputStem
$env:STAGE4_GZ_LIMIT = [string]$Limit
$env:STAGE4_GZ_MAX_ATTEMPTS = [string]$MaxAttempts
$env:STAGE4_GZ_RUN_DUE = if ($RunDueJobs) { "1" } else { "0" }
$env:STAGE4_GZ_ENABLE_LIVE_GDCIC = if ($EnableLiveGdcic) { "1" } else { "0" }

$python = @'
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path.cwd()
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from stage4_verification.local_job_queue import Stage4LocalJobQueue, enqueue_provider_plan_tasks
from stage4_verification.provider_handlers import build_stage4_provider_handlers
from stage4_verification.provider_registry import build_stage4_provider_plan


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def compact_stage4_record(record: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "idx",
        "type",
        "title",
        "notice_url",
        "project_id",
        "project_name",
        "candidate_company",
        "responsible_person",
        "announcement_certificate_no",
        "stage4_outcome",
        "normalized_stage4_outcome",
        "executor_state",
        "readback_state",
        "identity_resolution_state",
        "matched_company_name",
        "matched_company_public_id",
        "jzsc_certificate_no",
        "jzsc_registered_unit",
        "person_public_id",
        "personnel_detail_url",
        "company_personnel_source_url",
        "personnel_project_source_url",
        "rendered_company_personnel_row_count",
        "rendered_personnel_project_row_count",
        "fail_closed_reasons",
        "nonfatal_diagnostics",
        "active_conflict_overlap_judgement",
        "next_manual_review_route",
        "source_stage4_report",
    )
    return {key: record.get(key) for key in keys if record.get(key) not in (None, "", [], {})}


def build_tasks(records: list[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    provider_plans: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    for record in records:
        priority_class = clean_text(record.get("type"))
        candidate_company = clean_text(record.get("candidate_company") or record.get("matched_company_name"))
        responsible_person = clean_text(record.get("responsible_person"))
        cert = clean_text(record.get("announcement_certificate_no") or record.get("jzsc_certificate_no"))
        person_public_id = clean_text(record.get("person_public_id"))
        plan = build_stage4_provider_plan(
            opportunity_priority_class=priority_class,
            candidate_company_name=candidate_company,
            responsible_person_name=responsible_person,
            certificate_no=cert,
            person_public_id=person_public_id,
        )
        source_record = compact_stage4_record(record)
        enriched_tasks = []
        for task in list(plan.get("tasks") or []):
            task = dict(task)
            task["source_stage4_jzsc_record"] = source_record
            task["source_trace_record_idx"] = record.get("idx")
            task["source_notice_url"] = record.get("notice_url")
            task["source_title"] = record.get("title")
            enriched_tasks.append(task)
            tasks.append(task)
        plan["tasks"] = enriched_tasks
        plan["source_stage4_jzsc_record"] = source_record
        provider_plans.append(plan)
    return provider_plans, tasks


def summarize_jobs(jobs: list[Mapping[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(clean_text(job.get("status")) for job in jobs)
    provider_counts = Counter(clean_text(job.get("provider_id")) for job in jobs)
    result_counts = Counter()
    provider_result_counts = Counter()
    pending_or_review = []
    for job in jobs:
        result = job.get("result") if isinstance(job.get("result"), Mapping) else {}
        verification = clean_text(result.get("verification_result"))
        provider_state = clean_text(result.get("provider_result_state"))
        if verification:
            result_counts[verification] += 1
        if provider_state:
            provider_result_counts[provider_state] += 1
        if verification and verification != "MATCHED":
            pending_or_review.append(
                {
                    "job_id": job.get("job_id"),
                    "provider_id": job.get("provider_id"),
                    "verification_result": verification,
                    "provider_result_state": provider_state,
                    "review_reasons": result.get("review_reasons") or [],
                    "target": result.get("target") or (job.get("payload") or {}).get("target") or {},
                }
            )
    return {
        "status_counts": dict(status_counts),
        "provider_counts": dict(provider_counts),
        "verification_result_counts": dict(result_counts),
        "provider_result_state_counts": dict(provider_result_counts),
        "pending_or_review_jobs": pending_or_review[:200],
    }


def write_markdown(path: Path, payload: Mapping[str, Any]) -> None:
    summary = payload["summary"]
    lines = [
        "# 广州 22 条 Stage4 Provider Queue 追踪",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- input_json: `{summary['input_json']}`",
        f"- queue_path: `{summary['queue_path']}`",
        f"- source_record_count: {summary['source_record_count']}",
        f"- provider_task_count: {summary['provider_task_count']}",
        f"- run_due_jobs: {summary['run_due_jobs']}",
        f"- enable_live_gdcic: {summary['enable_live_gdcic']}",
        "",
        "## Provider Counts",
        "",
    ]
    for provider_id, count in sorted((payload.get("provider_counts") or {}).items()):
        lines.append(f"- {provider_id}: {count}")
    lines.extend(["", "## Queue Summary", ""])
    queue_summary = payload.get("queue_summary") or {}
    for key in ("status_counts", "verification_result_counts", "provider_result_state_counts"):
        lines.append(f"### {key}")
        for name, count in sorted((queue_summary.get(key) or {}).items()):
            lines.append(f"- {name}: {count}")
        lines.append("")
    lines.extend(
        [
            "## Pending / Review 明细",
            "",
            "说明：这里的 REVIEW/PENDING 只表示当前 provider 没形成自动核验证据，不能反推违规，也不能当销售证据。",
            "",
        ]
    )
    for item in queue_summary.get("pending_or_review_jobs") or []:
        target = item.get("target") or {}
        lines.append(
            "- "
            + f"{item.get('provider_id')} | "
            + f"{target.get('candidate_company_name', '')} | "
            + f"{target.get('responsible_person_name', '')} | "
            + f"{item.get('verification_result')} / {item.get('provider_result_state')} | "
            + "；".join(str(reason) for reason in (item.get("review_reasons") or []))
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    input_path = (ROOT / os.environ.get("STAGE4_GZ_MERGED_JSON", "")).resolve()
    queue_path = (ROOT / os.environ.get("STAGE4_GZ_QUEUE_PATH", "")).resolve()
    output_stem = clean_text(os.environ.get("STAGE4_GZ_OUTPUT_STEM")) or "guangzhou_stage4_provider_queue"
    limit = int(os.environ.get("STAGE4_GZ_LIMIT") or "22")
    max_attempts = int(os.environ.get("STAGE4_GZ_MAX_ATTEMPTS") or "3")
    run_due = os.environ.get("STAGE4_GZ_RUN_DUE") == "1"
    enable_live_gdcic = os.environ.get("STAGE4_GZ_ENABLE_LIVE_GDCIC") == "1"

    data = json.loads(input_path.read_text(encoding="utf-8"))
    source_records = list(data.get("records") or [])[: max(0, limit)]
    provider_plans, tasks = build_tasks(source_records)

    queue = Stage4LocalJobQueue(queue_path)
    enqueued_jobs = []
    for plan in provider_plans:
        enqueued_jobs.extend(
            enqueue_provider_plan_tasks(queue, plan, max_attempts=max_attempts)
        )

    run_result: dict[str, Any] = {}
    if run_due:
        handlers = build_stage4_provider_handlers(enable_live_gdcic=enable_live_gdcic)
        run_result = queue.run_due_jobs(handlers, limit=max(1, len(tasks) + 20))

    jobs = queue.list_jobs()
    provider_counts = Counter(clean_text(task.get("provider_id")) for task in tasks)
    generated_at = datetime.now(timezone.utc).isoformat()
    payload: dict[str, Any] = {
        "summary": {
            "generated_at": generated_at,
            "input_json": str(input_path),
            "queue_path": str(queue.queue_path),
            "source_record_count": len(source_records),
            "provider_task_count": len(tasks),
            "enqueued_count": len(enqueued_jobs),
            "run_due_jobs": run_due,
            "enable_live_gdcic": enable_live_gdcic,
        },
        "source_summary": data.get("summary") or {},
        "provider_counts": dict(provider_counts),
        "provider_plans": provider_plans,
        "run_result": run_result,
        "queue_summary": summarize_jobs(jobs),
        "jobs": jobs,
    }
    handoff_dir = ROOT / "handoff"
    handoff_dir.mkdir(parents=True, exist_ok=True)
    json_path = handoff_dir / f"{output_stem}.json"
    md_path = handoff_dir / f"{output_stem}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(md_path, payload)
    print(json.dumps(
        {
            "json_path": str(json_path),
            "md_path": str(md_path),
            "queue_path": str(queue.queue_path),
            "source_record_count": len(source_records),
            "provider_task_count": len(tasks),
            "queue_summary": payload["queue_summary"],
        },
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
'@

Push-Location $repoRoot
try {
    $python | python -X utf8 -
}
finally {
    Pop-Location
}
