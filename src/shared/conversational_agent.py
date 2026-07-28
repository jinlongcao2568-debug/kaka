from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from typing import Any, Mapping
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from shared.agent_memory import build_model_safe_agent_memory_context
from shared.model_provider_runtime import model_provider_readiness
from shared.utils import build_id, utc_now_iso
from stage1_tasking.scheduler import Stage1Scheduler
from storage.db import DatabaseSession, PersistedOperatorAction, PersistedRecord
from storage.repositories.operator_action_repo import OperatorActionRepository
from storage.repositories.stage1_scheduler_repo import Stage1SchedulerRepository
from storage.repositories.worker_queue_repo import WorkerQueueRepository
from storage.worker_queue import parse_iso


CONVERSATIONAL_AGENT_CONTRACT_REF = "contracts/agent/conversational_task_entry_contract.json"
_AGENT_AUDIT_WORK_ITEM_ID = "conversational-agent-internal-task-creation"
_ID_PATTERN = r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}"
_PROJECT_ID_RE = re.compile(
    rf"(?:项目\s*(?:ID|Id|id|编号)|project[_\s-]*id)\s*[:：=]?\s*({_ID_PATTERN})",
    re.IGNORECASE,
)
_OPPORTUNITY_ID_RE = re.compile(
    rf"(?:商机\s*(?:ID|Id|id|编号)|opportunity[_\s-]*id)\s*[:：=]?\s*({_ID_PATTERN})",
    re.IGNORECASE,
)
_QUEUE_ID_RE = re.compile(
    rf"(?:队列|任务)\s*(?:ID|Id|id|编号)\s*[:：=]?\s*({_ID_PATTERN})",
    re.IGNORECASE,
)
_SENSITIVE_TEXT_RE = re.compile(
    r"(?:api[_\s-]?key|authorization|bearer\s+\S+|cookie|password|"
    r"密码\s*[:：=]|secret\s*[:：=]|private[_\s-]?key|身份证|银行卡)",
    re.IGNORECASE,
)
_DIRECT_LIVE_ACTION_RE = re.compile(
    r"(?:帮我|请|立即|现在|自动|直接|马上).{0,12}"
    r"(?:发送|发邮件|发短信|联系|打电话|触达|付款|支付|扣款|退款|交付|发布|公开|下载)",
)
_QUESTION_MARKERS = ("能不能", "是否", "状态", "为什么", "依据", "证据", "查看", "怎么", "什么")
_SOURCE_QUERY_SECRET_KEYS = frozenset(
    {"token", "access_token", "api_key", "apikey", "signature", "sig", "auth", "session", "key"}
)

_OBJECT_TYPES = (
    "source_snapshot",
    "parse_run",
    "verification_run",
    "evidence",
    "rule_hit",
    "project_fact",
    "report_record",
    "saleable_opportunity",
    "offer_recommendation",
    "buyer_fit",
)
_FACT_FIELDS = {
    "source_snapshot": ("source_site_name", "source_profile_id", "captured_at", "capture_status"),
    "parse_run": ("parse_status", "parser_confidence_score", "requires_manual_review"),
    "verification_run": ("verification_result", "evidence_grade", "public_only"),
    "evidence": ("evidence_type", "evidence_grade", "verification_state", "review_required"),
    "rule_hit": ("rule_id", "hit_state", "review_required"),
    "project_fact": (
        "sale_gate_status",
        "rule_gate_status",
        "evidence_gate_status",
        "competitor_quality_grade",
        "real_competitor_count",
        "serviceable_competitor_count",
    ),
    "report_record": ("report_status", "review_task_status", "review_lane", "minimum_release_level"),
    "saleable_opportunity": ("saleability_status", "opportunity_grade", "evidence_strength"),
    "offer_recommendation": (
        "offer_recommendation_state",
        "package_template_code",
        "recommended_delivery_form",
    ),
    "buyer_fit": ("buyer_type", "buyer_fit_score", "buyer_fit_state"),
}
_SOURCE_VALUE_KEYS = frozenset(
    {
        "source_url",
        "announcement_url",
        "original_url",
        "detail_url",
        "source_snapshot_id",
        "source_snapshot_id_optional",
        "verification_run_id",
        "parse_run_id",
        "evidence_id",
        "snapshot_id",
    }
)


def build_conversational_agent_turn(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    message = str(payload.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    if len(message) > 4000:
        raise ValueError("message exceeds 4000 characters")

    conversation_id = _safe_identifier(payload.get("conversation_id")) or build_id(
        "AGENT-CONV", _message_hash(message)[:20]
    )
    turn_id = build_id("AGENT-TURN", conversation_id, _message_hash(message)[:20])
    project_id = _safe_identifier(payload.get("project_id")) or _match_identifier(
        _PROJECT_ID_RE, message
    )
    opportunity_id = _safe_identifier(payload.get("opportunity_id")) or _match_identifier(
        _OPPORTUNITY_ID_RE, message
    )
    queue_item_id = _safe_identifier(payload.get("queue_item_id")) or _match_identifier(
        _QUEUE_ID_RE, message
    )
    actor = dict(payload.get("_internal_auth_context") or {})
    base = _base_response(
        conversation_id=conversation_id,
        turn_id=turn_id,
        message=message,
        project_id=project_id,
        actor=actor,
        session=active_session,
    )

    if _SENSITIVE_TEXT_RE.search(message):
        return _finalize(
            base,
            intent="BLOCKED_SENSITIVE_INPUT",
            answer_state="BLOCKED",
            answer="消息可能包含凭据、密钥或受限个人信息，系统未处理也未回显该内容。请删除敏感信息，只提交公开或已脱敏的项目标识。",
            required_inputs=["删除凭据、密钥、身份证件、银行卡等敏感内容后重试"],
        )

    if _direct_live_action_requested(message):
        return _finalize(
            base,
            intent="BLOCKED_LIVE_ACTION",
            answer_state="BLOCKED",
            answer="该请求涉及真实触达、支付、退款、客户交付或发布；对话入口没有这些权限，也不会代替审批执行。可以改为查询当前状态、证据或人工下一步。",
            suggested_actions=[
                _navigation("查看系统与放行状态", "/operator-console#systemRelease"),
                _navigation("查看证据与下一步", "/operator-console#agent"),
            ],
        )

    intent = _classify_intent(message)
    if intent == "CREATE_INTERNAL_TASK":
        return _create_internal_task_turn(
            base,
            payload=payload,
            message=message,
            project_id=project_id,
            conversation_id=conversation_id,
            actor=actor,
            session=active_session,
        )
    if intent == "TASK_STATUS":
        return _task_status_turn(
            base,
            project_id=project_id,
            queue_item_id=queue_item_id,
            session=active_session,
        )

    project_id = _resolve_project_id(
        session=active_session,
        explicit_project_id=project_id,
        opportunity_id=opportunity_id,
    )
    base["memory_context"] = build_model_safe_agent_memory_context(
        actor,
        project_id=project_id,
        session=active_session,
    )
    if intent == "EVIDENCE_QUERY":
        return _evidence_turn(
            base,
            project_id=project_id,
            opportunity_id=opportunity_id,
            session=active_session,
        )
    if intent == "NEXT_STEP_QUERY":
        return _next_step_turn(base, project_id=project_id, session=active_session)
    return _help_turn(base, project_id=project_id)


def _base_response(
    *,
    conversation_id: str,
    turn_id: str,
    message: str,
    project_id: str,
    actor: Mapping[str, Any],
    session: DatabaseSession,
) -> dict[str, Any]:
    readiness = model_provider_readiness()
    memory_context = build_model_safe_agent_memory_context(
        actor,
        project_id=project_id,
        session=session,
    )
    return {
        "surface_id": "conversational_agent_internal_entry",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "user_message_sha256": _message_hash(message),
        "intent": "HELP",
        "answer_state": "READY",
        "answer": "",
        "facts": [],
        "citations": [_contract_citation()],
        "required_inputs": [],
        "suggested_actions": [],
        "task": {},
        "runtime": {
            "response_generation_mode": "DETERMINISTIC_GROUNDED",
            "provider_runtime_state": readiness.get("state"),
            "model_provider_call_enabled": False,
            "model_provider_call_executed": False,
        },
        "memory_context": memory_context,
        "governance": {
            "internal_only": True,
            "conversation_memory_persisted": False,
            "governed_principal_project_memory_enabled": True,
            "memory_is_not_fact_or_evidence": True,
            "memory_can_satisfy_citation": False,
            "memory_can_change_gate_or_approval": False,
            "formal_object_grounding_required": True,
            "query_miss_is_not_clearance": True,
            "no_legal_conclusion": True,
            "live_source_execution_enabled": False,
            "external_contact_enabled": False,
            "payment_enabled": False,
            "refund_enabled": False,
            "customer_delivery_enabled": False,
            "customer_publication_enabled": False,
            "tool_calling_enabled": False,
        },
    }


def _finalize(
    response: dict[str, Any],
    *,
    intent: str,
    answer_state: str,
    answer: str,
    facts: list[dict[str, Any]] | None = None,
    citations: list[dict[str, Any]] | None = None,
    required_inputs: list[str] | None = None,
    suggested_actions: list[dict[str, Any]] | None = None,
    task: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    response.update(
        {
            "intent": intent,
            "answer_state": answer_state,
            "answer": answer,
            "facts": list(facts or []),
            "citations": _deduplicate_citations(
                [*response.get("citations", []), *(citations or [])]
            ),
            "required_inputs": list(required_inputs or []),
            "suggested_actions": list(suggested_actions or []),
            "task": dict(task or {}),
        }
    )
    return response


def _create_internal_task_turn(
    response: dict[str, Any],
    *,
    payload: Mapping[str, Any],
    message: str,
    project_id: str,
    conversation_id: str,
    actor: Mapping[str, Any],
    session: DatabaseSession,
) -> dict[str, Any]:
    if not project_id:
        return _finalize(
            response,
            intent="CREATE_INTERNAL_TASK",
            answer_state="NEEDS_INPUT",
            answer="可以创建受限内部任务，但还缺项目 ID。请在消息里写“项目ID：…”，或填写项目 ID 输入框。",
            required_inputs=["project_id"],
        )
    region_code = _safe_region_code(payload.get("region_code")) or _region_from_message(message)
    task_id = build_id("AGENT-TASK", conversation_id, _message_hash(message)[:20])
    queue_item_id = build_id("S1Q", task_id)
    proposed_task = {
        "task_id": task_id,
        "project_id": project_id,
        "region_code": region_code,
        "queue_item_id": queue_item_id,
        "task_mode": "SANITIZED_OFFLINE_INTERNAL",
        "source_mode": "INTERNAL_OPERATOR_TASK",
        "stage2_fetch_enabled": False,
        "real_external_fetch_enabled": False,
        "live_execution_enabled": False,
    }
    if payload.get("confirm_internal_task") is not True:
        return _finalize(
            response,
            intent="CREATE_INTERNAL_TASK",
            answer_state="CONFIRMATION_REQUIRED",
            answer="已生成内部任务方案。勾选“确认创建内部预览任务”后再次发送，才会写入 Stage1 队列；这不会启动真实外部抓取。",
            required_inputs=["confirm_internal_task=true"],
            task={**proposed_task, "task_state": "PROPOSED_NOT_CREATED"},
        )

    queue_repo = WorkerQueueRepository(session=session)
    existing = queue_repo.get(queue_item_id)
    if existing is None:
        scheduler = Stage1Scheduler(
            repository=Stage1SchedulerRepository(session=session),
        )
        created = scheduler.create_task(
            {
                "task_id": task_id,
                "project_id": project_id,
                "project_name": f"对话创建的内部任务 {project_id}",
                "region_code": region_code,
                "region_scope": "NATIONAL",
                "source_family": "PROCUREMENT_NOTICE",
                "platform_level": "NATIONAL",
                "coverage_tier": "T0_CORE",
                "default_route": "LIST_TO_DETAIL",
                "review_lane": "STANDARD",
                "carrier_type": "HTML_PAGE",
                "procurement_regime": "OPEN_TENDER",
                "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
                "source_mode": "INTERNAL_OPERATOR_TASK",
                "run_mode": "DRY_RUN",
                "live_execution_enabled": False,
                "real_external_fetch_enabled": False,
                "real_provider_call_enabled": False,
                "external_release_enabled": False,
                "now": utc_now_iso(),
            }
        )
        existing = queue_repo.get(created.queue_item_id)
        _record_task_creation_audit(
            task_id=task_id,
            project_id=project_id,
            queue_item_id=created.queue_item_id,
            conversation_id=conversation_id,
            actor=actor,
            session=session,
        )
        task_state = "CREATED_INTERNAL_ONLY"
    else:
        task_state = "EXISTING_IDEMPOTENT_READBACK"

    citation = _task_citation(existing, project_id=project_id)
    return _finalize(
        response,
        intent="CREATE_INTERNAL_TASK",
        answer_state="TASK_CREATED" if task_state == "CREATED_INTERNAL_ONLY" else "TASK_EXISTS",
        answer=(
            "内部任务已写入 Stage1 队列。它只生成后续交接意图，真实外部抓取仍关闭。"
            if task_state == "CREATED_INTERNAL_ONLY"
            else "相同对话请求对应的内部任务已经存在，本次返回原任务，未重复创建。"
        ),
        facts=[
            {
                "object_type": "task_record",
                "object_id": task_id,
                "field": "status",
                "value": str(getattr(existing, "status", "queued") or "queued"),
                "supported_by": citation["citation_id"],
            }
        ],
        citations=[citation],
        suggested_actions=[
            _navigation("查看任务进度", f"/operator-console/tasks/{queue_item_id}"),
        ],
        task={**proposed_task, "task_state": task_state, "status": getattr(existing, "status", None)},
    )


def _task_status_turn(
    response: dict[str, Any],
    *,
    project_id: str,
    queue_item_id: str,
    session: DatabaseSession,
) -> dict[str, Any]:
    repository = WorkerQueueRepository(session=session)
    item = repository.get(queue_item_id) if queue_item_id else None
    if item is None and project_id:
        candidates = [
            row
            for row in repository.list()
            if str(row.trace_refs.get("project_id") or "") == project_id
        ]
        item = max(
            candidates,
            key=lambda row: (parse_iso(row.updated_at), parse_iso(row.created_at), row.queue_item_id),
        ) if candidates else None
    if item is None:
        return _finalize(
            response,
            intent="TASK_STATUS",
            answer_state="INSUFFICIENT_CONTEXT",
            answer="没有找到可回放的任务记录。请提供队列编号，或提供唯一的项目 ID。",
            required_inputs=["queue_item_id 或 project_id"],
        )
    project_id = str(item.trace_refs.get("project_id") or project_id)
    citation = _task_citation(item, project_id=project_id)
    facts = [
        {
            "object_type": "task_record",
            "object_id": item.queue_item_id,
            "field": field,
            "value": value,
            "supported_by": citation["citation_id"],
        }
        for field, value in (
            ("status", item.status),
            ("progress_stage", item.progress_stage),
            ("progress_percent", item.progress_percent),
            ("last_error_category", item.last_error_category),
        )
        if value not in (None, "")
    ]
    return _finalize(
        response,
        intent="TASK_STATUS",
        answer_state="GROUNDED",
        answer=(
            f"任务 {item.queue_item_id} 当前状态为 {item.status}。"
            + (f" 进度 {item.progress_percent}%。" if item.progress_percent is not None else "")
            + (f" 当前阶段：{item.progress_stage}。" if item.progress_stage else "")
        ),
        facts=facts,
        citations=[citation],
        suggested_actions=[_navigation("打开任务读回", citation["href"])],
        task={
            "queue_item_id": item.queue_item_id,
            "project_id": project_id,
            "status": item.status,
            "progress_stage": item.progress_stage,
            "progress_percent": item.progress_percent,
            "live_execution_enabled": False,
        },
    )


def _evidence_turn(
    response: dict[str, Any],
    *,
    project_id: str,
    opportunity_id: str,
    session: DatabaseSession,
) -> dict[str, Any]:
    if not project_id:
        return _finalize(
            response,
            intent="EVIDENCE_QUERY",
            answer_state="NEEDS_INPUT",
            answer="要追问证据，必须先确定唯一项目。请提供项目 ID 或商机 ID；系统不会根据相似名称猜项目。",
            required_inputs=["project_id 或 opportunity_id"],
        )
    records = _project_records(session, project_id, opportunity_id=opportunity_id)
    facts, citations = _facts_and_citations(records, project_id=project_id)
    if not facts:
        return _finalize(
            response,
            intent="EVIDENCE_QUERY",
            answer_state="INSUFFICIENT_EVIDENCE",
            answer=f"项目 {project_id} 暂无可回链的正式对象或登记来源，因此不能给出事实判断。未找到不等于没有风险。",
            required_inputs=["先完成公开来源采集、核验或正式对象持久化"],
            suggested_actions=[_navigation("返回运营总览", "/operator-console#overview")],
        )
    source_count = sum(1 for item in citations if item.get("citation_kind") == "PUBLIC_SOURCE")
    object_count = sum(1 for item in citations if item.get("citation_kind") == "FORMAL_OBJECT")
    return _finalize(
        response,
        intent="EVIDENCE_QUERY",
        answer_state="GROUNDED",
        answer=(
            f"项目 {project_id} 找到 {object_count} 个正式对象引用和 {source_count} 个公开来源引用。"
            "下面只展示字段白名单中的状态；缺失、未命中或阻断均不解释为无风险。"
        ),
        facts=facts,
        citations=citations,
        suggested_actions=[_navigation("打开项目复核工作台", f"/review-report-workbench?project_id={project_id}")],
    )


def _next_step_turn(
    response: dict[str, Any],
    *,
    project_id: str,
    session: DatabaseSession,
) -> dict[str, Any]:
    if not project_id:
        return _finalize(
            response,
            intent="NEXT_STEP_QUERY",
            answer_state="NEEDS_INPUT",
            answer="查看下一步需要唯一项目 ID；系统不会跨项目拼接状态。",
            required_inputs=["project_id"],
        )
    work_items = [item for item in session.list_work_items() if item.project_id == project_id]
    work_items.sort(key=lambda item: (item.stage_scope, item.updated_at), reverse=True)
    citations: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    next_actions: list[str] = []
    for item in work_items[:5]:
        citation = {
            "citation_id": f"WORK-{item.work_item_id}",
            "citation_kind": "FORMAL_OBJECT",
            "object_type": item.primary_object_type,
            "object_id": item.primary_record_id,
            "label": f"Stage{item.stage_scope} 工作项",
            "href": _object_href(item.primary_object_type, item.primary_record_id, project_id),
        }
        citations.append(citation)
        for action in item.pending_actions:
            action_text = str(action).strip()
            if action_text and action_text not in next_actions:
                next_actions.append(action_text)
        facts.append(
            {
                "object_type": "work_item",
                "object_id": item.work_item_id,
                "field": "current_operational_state",
                "value": item.current_operational_state,
                "supported_by": citation["citation_id"],
            }
        )
    if not next_actions:
        records = _project_records(session, project_id)
        fallback_facts, fallback_citations = _facts_and_citations(records, project_id=project_id)
        facts.extend(fallback_facts[:8])
        citations.extend(fallback_citations)
        next_actions = _deterministic_next_actions(records)
    if not next_actions:
        return _finalize(
            response,
            intent="NEXT_STEP_QUERY",
            answer_state="INSUFFICIENT_CONTEXT",
            answer=f"项目 {project_id} 没有足够的正式状态来确定下一步。请先创建内部任务或完成项目对象持久化。",
            suggested_actions=[_navigation("创建内部任务", "/operator-console#agent")],
        )
    return _finalize(
        response,
        intent="NEXT_STEP_QUERY",
        answer_state="GROUNDED",
        answer="建议按正式工作项顺序处理：" + "；".join(next_actions[:5]) + "。这些是内部建议，不会自动执行。",
        facts=facts[:20],
        citations=citations,
        suggested_actions=[_navigation("打开项目复核工作台", f"/review-report-workbench?project_id={project_id}")],
    )


def _help_turn(response: dict[str, Any], *, project_id: str) -> dict[str, Any]:
    return _finalize(
        response,
        intent="HELP",
        answer_state="READY",
        answer=(
            "我可以创建受限内部任务、查询任务进度、按正式对象追问证据，以及给出有来源的下一步。"
            "请提供项目 ID；创建任务还需要显式确认。真实抓取、触达、支付、退款和客户交付不由对话入口执行。"
        ),
        required_inputs=[] if project_id else ["处理具体项目时提供 project_id"],
        suggested_actions=[
            _navigation("查看运营总览", "/operator-console#overview"),
            _navigation("查看系统边界", "/operator-console#systemRelease"),
        ],
    )


def _classify_intent(message: str) -> str:
    normalized = message.casefold()
    if any(token in normalized for token in ("任务状态", "任务进度", "跑到哪", "队列状态", "进度怎么样")):
        return "TASK_STATUS"
    if re.search(r"(?:创建|新建|建立|生成|安排).{0,10}任务", normalized) or any(
        token in normalized for token in ("帮我查", "帮我找", "搜索项目")
    ):
        return "CREATE_INTERNAL_TASK"
    if any(token in normalized for token in ("证据", "来源", "依据", "为什么", "核验", "风险")):
        return "EVIDENCE_QUERY"
    if any(token in normalized for token in ("下一步", "怎么办", "如何继续", "该做什么", "继续做什么")):
        return "NEXT_STEP_QUERY"
    return "HELP"


def _direct_live_action_requested(message: str) -> bool:
    if any(marker in message for marker in _QUESTION_MARKERS):
        return False
    return bool(_DIRECT_LIVE_ACTION_RE.search(message))


def _project_records(
    session: DatabaseSession,
    project_id: str,
    *,
    opportunity_id: str = "",
) -> list[PersistedRecord]:
    records: list[PersistedRecord] = []
    for object_type in _OBJECT_TYPES:
        for record in session.find_records(object_type, project_id=project_id):
            if opportunity_id and object_type == "saleable_opportunity" and record.record_id != opportunity_id:
                continue
            records.append(record)
    records.sort(key=lambda item: (item.stage_scope, item.persisted_at, item.record_id))
    return records


def _facts_and_citations(
    records: Iterable[PersistedRecord],
    *,
    project_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    facts: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    for record in list(records)[:40]:
        citation_id = f"OBJ-{record.object_type}-{record.record_id}"
        citations.append(
            {
                "citation_id": citation_id,
                "citation_kind": "FORMAL_OBJECT",
                "object_type": record.object_type,
                "object_id": record.record_id,
                "label": f"{record.object_type} {record.record_id}",
                "href": _object_href(record.object_type, record.record_id, project_id),
            }
        )
        for field in _FACT_FIELDS.get(record.object_type, ()):
            value = record.payload.get(field)
            if value in (None, "", [], {}):
                continue
            facts.append(
                {
                    "object_type": record.object_type,
                    "object_id": record.record_id,
                    "field": field,
                    "value": value,
                    "supported_by": citation_id,
                }
            )
        citations.extend(_source_citations(record.payload, record_id=record.record_id))
    return facts[:50], _deduplicate_citations(citations)[:60]


def _source_citations(value: Any, *, record_id: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    def visit(current: Any, key: str = "") -> None:
        if len(results) >= 20:
            return
        if isinstance(current, Mapping):
            for child_key, child in current.items():
                child_key_text = str(child_key)
                if child_key_text in _SOURCE_VALUE_KEYS or child_key_text in {"source_refs", "evidence_refs"}:
                    collect(child, child_key_text)
                elif isinstance(child, (Mapping, list, tuple)):
                    visit(child, child_key_text)
        elif isinstance(current, (list, tuple)):
            for child in current:
                visit(child, key)

    def collect(candidate: Any, key: str) -> None:
        if isinstance(candidate, Mapping):
            visit(candidate, key)
            return
        if isinstance(candidate, (list, tuple)):
            for item in candidate:
                collect(item, key)
            return
        if not isinstance(candidate, (str, int, float)):
            return
        text = str(candidate).strip()
        if not text or len(text) > 2048 or _SENSITIVE_TEXT_RE.search(text):
            return
        public_url = _safe_public_url(text)
        citation_id = "SRC-" + hashlib.sha256(f"{record_id}:{key}:{text}".encode("utf-8")).hexdigest()[:20]
        results.append(
            {
                "citation_id": citation_id,
                "citation_kind": "PUBLIC_SOURCE" if public_url else "SOURCE_REF",
                "object_type": "source_ref",
                "object_id": text if not public_url else citation_id,
                "label": "公开来源" if public_url else key,
                "href": public_url,
            }
        )

    visit(value)
    return results


def _deterministic_next_actions(records: Iterable[PersistedRecord]) -> list[str]:
    actions: list[str] = []
    for record in records:
        payload = record.payload
        if record.object_type == "project_fact":
            if str(payload.get("evidence_gate_status") or "") not in {"PASS", "APPROVED"}:
                actions.append("补齐证据引用并进入人工复核")
            elif str(payload.get("rule_gate_status") or "") not in {"PASS", "APPROVED"}:
                actions.append("复核规则命中和阻断原因")
            elif str(payload.get("sale_gate_status") or "") not in {"PASS", "APPROVED"}:
                actions.append("复核可售门状态，不得直接外发")
        if record.object_type == "report_record" and str(payload.get("review_task_status") or "") not in {
            "COMPLETED",
            "APPROVED",
        }:
            actions.append("完成报告人工复核")
        if record.object_type == "saleable_opportunity" and str(payload.get("saleability_status") or "") in {
            "QUALIFIED",
            "PASS",
        }:
            actions.append("进入内部机会工作台复核报价和证据强度")
    return list(dict.fromkeys(actions))


def _resolve_project_id(
    *,
    session: DatabaseSession,
    explicit_project_id: str,
    opportunity_id: str,
) -> str:
    if explicit_project_id:
        return explicit_project_id
    if opportunity_id:
        opportunity = session.get_record("saleable_opportunity", opportunity_id)
        if opportunity and opportunity.project_id:
            return str(opportunity.project_id)
    project_ids: set[str] = set()
    for object_type in ("project_fact", "saleable_opportunity", "report_record"):
        project_ids.update(
            str(record.project_id)
            for record in session.list_records(object_type)
            if record.project_id
        )
    if len(project_ids) == 1:
        return next(iter(project_ids))
    return ""


def _record_task_creation_audit(
    *,
    task_id: str,
    project_id: str,
    queue_item_id: str,
    conversation_id: str,
    actor: Mapping[str, Any],
    session: DatabaseSession,
) -> None:
    now = utc_now_iso()
    principal_id = str(actor.get("principal_id") or "unknown-internal-principal")
    role = str(actor.get("role") or "unknown-internal-role")
    OperatorActionRepository(session=session).append(
        PersistedOperatorAction(
            action_event_id=build_id("AGENT-TASK-AUDIT", queue_item_id),
            work_item_id=_AGENT_AUDIT_WORK_ITEM_ID,
            stage_scope=1,
            action_id="conversational_create_internal_task",
            button_flow_id="conversational_agent_confirm_internal_task",
            action_state="CREATED_INTERNAL_ONLY",
            resulting_assignment_lifecycle_state=None,
            requested_by_role=role,
            requested_by=principal_id,
            assigned_owner_role=role,
            assigned_owner=principal_id,
            reviewer_role="",
            reviewer="",
            reason="explicit_confirmed_conversational_internal_task_creation",
            object_refs={
                "task_id": task_id,
                "project_id": project_id,
                "queue_item_id": queue_item_id,
                "conversation_id": conversation_id,
            },
            trace_refs={"contract_ref": CONVERSATIONAL_AGENT_CONTRACT_REF},
            audit_refs={
                "actor_from_authenticated_transport": "true",
                "message_body_persisted": "false",
                "live_execution_enabled": "false",
            },
            requested_at=now,
            completed_at=now,
        )
    )


def _task_citation(item: Any, *, project_id: str) -> dict[str, Any]:
    queue_item_id = str(getattr(item, "queue_item_id", "") or "")
    return {
        "citation_id": f"TASK-{queue_item_id}",
        "citation_kind": "FORMAL_TASK_RECORD",
        "object_type": "task_record",
        "object_id": queue_item_id,
        "label": f"内部任务 {queue_item_id}",
        "href": f"/operator-console/tasks/{quote(queue_item_id, safe='')}",
        "project_id": project_id,
    }


def _contract_citation() -> dict[str, Any]:
    return {
        "citation_id": "CONTRACT-CONVERSATIONAL-TASK-ENTRY-V1",
        "citation_kind": "POLICY_CONTRACT",
        "object_type": "contract",
        "object_id": "conversational_task_entry_contract:1.0.0",
        "label": "对话任务入口边界合同",
        "href": "",
    }


def _navigation(label: str, href: str) -> dict[str, Any]:
    return {"action_type": "NAVIGATE", "label": label, "href": href, "executes_action": False}


def _object_href(object_type: str, object_id: str, project_id: str) -> str:
    if object_type == "saleable_opportunity":
        return f"/saleable-opportunities/{quote(object_id, safe='')}"
    if object_type in {"project_fact", "report_record", "work_item"}:
        return "/review-report-workbench?" + urlencode({"project_id": project_id})
    return "/operator-console#overview"


def _safe_public_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return ""
        if parsed.username or parsed.password:
            return ""
        host = parsed.hostname.casefold().rstrip(".")
        if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".lan")):
            return ""
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return ""
        safe_query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in _SOURCE_QUERY_SECRET_KEYS
        ]
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(safe_query, doseq=True), "")
        )
    except ValueError:
        return ""


def _deduplicate_citations(values: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        citation = dict(value)
        citation_id = str(citation.get("citation_id") or "")
        if not citation_id or citation_id in seen:
            continue
        seen.add(citation_id)
        deduplicated.append(citation)
    return deduplicated


def _match_identifier(pattern: re.Pattern[str], message: str) -> str:
    match = pattern.search(message)
    return _safe_identifier(match.group(1)) if match else ""


def _safe_identifier(value: Any) -> str:
    text = str(value or "").strip()
    return text if re.fullmatch(_ID_PATTERN, text) else ""


def _safe_region_code(value: Any) -> str:
    text = str(value or "").strip().upper()
    return text if re.fullmatch(r"CN-[A-Z0-9-]{2,24}", text) else ""


def _region_from_message(message: str) -> str:
    for token, code in (
        ("广州", "CN-GD-GZ"),
        ("深圳", "CN-GD-SZ"),
        ("佛山", "CN-GD-FS"),
        ("东莞", "CN-GD-DG"),
        ("广东", "CN-GD"),
    ):
        if token in message:
            return code
    return "CN-GD"


def _message_hash(message: str) -> str:
    normalized = " ".join(message.split()).casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


__all__ = [
    "CONVERSATIONAL_AGENT_CONTRACT_REF",
    "build_conversational_agent_turn",
]
