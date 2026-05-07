from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage3_parsing.ocr_text import _extract_pdf_embedded_text
from stage3_parsing.real_parser import _extract_fields_from_text
from stage3_parsing.service import Stage3Service
from storage.db import DatabaseSession, PersistedRecord
from storage.evaluation_corpus import (
    EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE,
    EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE,
)
from storage.repositories.object_storage_repo import ObjectStorageRepository


EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE = "evaluation_stage3_profile_manifest"
EVALUATION_STAGE3_PROFILE_VERSION = 1
EVALUATION_STAGE3_PROFILE_RULESET_ID = "evaluation-stage3-profile-v1"
EVALUATION_STAGE3_PROFILE_ADAPTER_ID = "evaluation-stage3-profile-builder"

PROFILE_TEXT_LIMIT = 256 * 1024
FIELD_VALUE_LIMIT = 500

METHOD_FAMILIES = {
    "comprehensive",
    "reviewed_lowest_price",
    "reasonable_low_price",
    "technical_pass",
    "technical_scored",
    "bid_separation",
    "unknown",
}

CANDIDATE_SELECTION_MODES = {
    "ranked_candidates",
    "unranked_candidates",
    "bid_separation_candidates",
    "single_winner",
    "unknown",
}

RANK_LABEL_RE = re.compile(r"第(?P<rank>[一二三四五六七八九十0-9]+)(?:中标|成交)?候选人")
STOP_TOKEN_RE = re.compile(
    r"(?:投标报价|报价|投标总价|总得分|综合得分|得分|评分|项目负责人|项目经理|"
    r"拟派项目负责人|证书编号|注册编号|注册证书编号|注册号|质量|工期|资格能力)"
)
PUNCT_SPLIT_RE = re.compile(r"[、,，;；\n\r]+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class EvaluationStage3ProfileItem:
    seed_id: str
    source_url: str
    source_family: str
    jurisdiction: str
    project_type: str
    document_kind: str
    source_title_optional: str | None
    snapshot_id_optional: str | None
    object_key_optional: str | None
    sha256_optional: str | None
    profile_state: str
    profile_text_source: str
    stage3_parse_state_optional: str | None
    parsed_field_count: int
    parsed_fields_summary: list[dict[str, Any]]
    evaluation_method_profile: dict[str, Any]
    candidate_set_profile: dict[str, Any]
    fairness_clause_probe: dict[str, Any]
    review_required: bool = True
    review_reasons: list[str] = field(default_factory=list)
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_evaluation_stage3_profiles(
    *,
    database_url: str,
    target_backend: str = "postgresql",
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    limit: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    object_root = Path(object_storage_path) if object_storage_path is not None else default_object_storage_path()
    settings = Settings(
        storage_backend=target_backend,
        storage_database_url_optional=database_url,
        storage_scope="shared",
        storage_runtime_mode="explicit-path",
        object_storage_path_optional=str(object_root),
    )
    session = DatabaseSession(settings=settings)
    try:
        sample_record = _latest_record(session.list_records(EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE))
        probe_record = _latest_record(session.list_records(EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE))
        blocking_reasons = _blocking_reasons(sample_record=sample_record, probe_record=probe_record)

        samples = _manifest_items(sample_record)
        if limit is not None and limit >= 0:
            samples = samples[:limit]
        probes_by_seed = {str(item.get("seed_id") or ""): dict(item) for item in _manifest_items(probe_record)}
        repository = ObjectStorageRepository(session=session, settings=settings)
        items = build_profile_items(
            samples=samples,
            probes_by_seed=probes_by_seed,
            repository=repository,
        )
        manifest = build_profile_manifest(
            items=items,
            sample_manifest_id=str((sample_record.payload if sample_record else {}).get("manifest_id") or ""),
            probe_manifest_id=str((probe_record.payload if probe_record else {}).get("manifest_id") or ""),
            database_url=database_url,
            target_backend=target_backend,
            object_storage_path=object_root,
            created_at=created,
        )
        result = {
            "profile_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "manifest": manifest,
            "summary": manifest["summary"],
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "database_write_enabled": False,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            },
        }
        if execute and not blocking_reasons:
            with session.bulk_write():
                session.upsert_record(_profile_manifest_record(manifest, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "upserted_evaluation_stage3_profile_manifest_count": 1,
                "stage4_public_evidence_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
                "large_object_blob_database_import_enabled": False,
            }
        return result
    finally:
        session.close()


def build_profile_items(
    *,
    samples: Iterable[Mapping[str, Any]],
    probes_by_seed: Mapping[str, Mapping[str, Any]],
    repository: ObjectStorageRepository,
) -> list[EvaluationStage3ProfileItem]:
    service = Stage3Service()
    items: list[EvaluationStage3ProfileItem] = []
    for sample in samples:
        seed_id = str(sample.get("seed_id") or "")
        probe = dict(probes_by_seed.get(seed_id) or {})
        context = _profile_context(sample=sample, repository=repository, service=service)
        profile_text = context["profile_text"]
        fields = list(context["parsed_fields"])
        field_summary = _parsed_fields_summary(fields)
        method_profile = build_evaluation_method_profile(
            text=profile_text,
            sample=sample,
            probe=probe,
            field_summary=field_summary,
        )
        candidate_profile = build_candidate_set_profile(
            text=profile_text,
            sample=sample,
            probe=probe,
            field_summary=field_summary,
        )
        fairness_probe = build_fairness_clause_probe(text=profile_text, probe=probe)
        review_reasons = _review_reasons(
            context=context,
            method_profile=method_profile,
            candidate_profile=candidate_profile,
            fairness_probe=fairness_probe,
        )
        profile_state = _profile_state(
            context=context,
            method_profile=method_profile,
            candidate_profile=candidate_profile,
            fairness_probe=fairness_probe,
        )
        items.append(
            EvaluationStage3ProfileItem(
                seed_id=seed_id,
                source_url=str(sample.get("source_url") or ""),
                source_family=str(sample.get("source_family") or ""),
                jurisdiction=str(sample.get("jurisdiction") or ""),
                project_type=str(sample.get("project_type") or ""),
                document_kind=str(sample.get("document_kind") or ""),
                source_title_optional=_text(sample.get("source_title_optional")),
                snapshot_id_optional=_text(sample.get("snapshot_id_optional")),
                object_key_optional=_text(sample.get("object_key_optional") or context.get("object_key_optional")),
                sha256_optional=_text(sample.get("sha256_optional") or context.get("sha256_optional")),
                profile_state=profile_state,
                profile_text_source=str(context.get("profile_text_source") or "probe_manifest_only"),
                stage3_parse_state_optional=_text(context.get("stage3_parse_state_optional")),
                parsed_field_count=len(fields),
                parsed_fields_summary=field_summary,
                evaluation_method_profile=method_profile,
                candidate_set_profile=candidate_profile,
                fairness_clause_probe=fairness_probe,
                review_required=True,
                review_reasons=review_reasons,
                customer_visible_allowed=False,
                no_legal_conclusion=True,
            )
        )
    return items


def build_evaluation_method_profile(
    *,
    text: str,
    sample: Mapping[str, Any],
    probe: Mapping[str, Any],
    field_summary: list[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized = _normalize_text(text)
    family, markers = _detect_method_family(normalized)
    family_source = "text_marker"
    if family == "unknown":
        family = _known_or_unknown(probe.get("evaluation_method_family") or sample.get("evaluation_method_family"), METHOD_FAMILIES)
        family_source = "probe_manifest" if family != "unknown" else "unresolved"
        markers = [str(marker) for marker in list(probe.get("method_markers") or [])]
    dark = _contains_any(normalized, ("暗标", "暗 标")) or bool(probe.get("has_dark_bid_requirement"))
    bright = _contains_any(normalized, ("明标", "明 标")) or bool(probe.get("has_bright_bid_requirement"))
    scoring_dimensions = _scoring_dimensions(normalized, field_summary)
    confidence = 0.86 if normalized and markers else 0.66 if family != "unknown" else 0.3
    review_reasons = ["evaluation_method_profile_review_required"]
    if family == "unknown":
        review_reasons.append("evaluation_method_family_unresolved")
    if not normalized:
        review_reasons.append("profile_text_unavailable")
    return {
        "evaluation_method_family": family,
        "method_family_source": family_source,
        "raw_method_markers": markers,
        "has_dark_bid_requirement": dark,
        "has_bright_bid_requirement": bright,
        "scoring_dimensions": scoring_dimensions,
        "profile_confidence": round(confidence, 2),
        "review_required": True,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def build_candidate_set_profile(
    *,
    text: str,
    sample: Mapping[str, Any],
    probe: Mapping[str, Any],
    field_summary: list[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized = _normalize_text(text)
    mode, markers = _detect_candidate_selection_mode(normalized)
    mode_source = "text_marker"
    if mode == "unknown":
        mode = _known_or_unknown(
            probe.get("candidate_selection_mode") or sample.get("candidate_selection_mode"),
            CANDIDATE_SELECTION_MODES,
        )
        mode_source = "probe_manifest" if mode != "unknown" else "unresolved"
        markers = [str(marker) for marker in list(probe.get("candidate_markers") or [])]
    candidates = _extract_candidates(normalized, mode=mode)
    if not candidates:
        candidates = _candidate_from_field_summary(field_summary)
    candidate_count = len(candidates) if candidates else _int_or_none(
        probe.get("candidate_count_optional") or sample.get("candidate_count_optional")
    )
    objection_window = _objection_window(normalized) or _text(
        probe.get("objection_window_optional") or sample.get("objection_window_optional")
    )
    review_reasons = ["candidate_set_profile_review_required"]
    if mode == "unknown":
        review_reasons.append("candidate_selection_mode_unresolved")
    if not candidates:
        review_reasons.append("candidate_rows_not_extracted")
    if candidate_count is None:
        review_reasons.append("candidate_count_unresolved")
    if not normalized:
        review_reasons.append("profile_text_unavailable")
    return {
        "candidate_selection_mode": mode,
        "candidate_selection_mode_source": mode_source,
        "candidate_markers": markers,
        "candidate_count_optional": candidate_count,
        "objection_window_optional": objection_window,
        "candidate_rows": candidates,
        "candidate_rows_extracted_count": len(candidates),
        "review_required": True,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def build_fairness_clause_probe(*, text: str, probe: Mapping[str, Any]) -> dict[str, Any]:
    normalized = _normalize_text(text)
    signals = _fairness_signals(normalized)
    if not signals:
        for marker in list(probe.get("fairness_markers") or []):
            marker_text = str(marker)
            signals.append(
                {
                    "signal_type": "probe_manifest_fairness_marker",
                    "markers": [marker_text],
                    "match_basis": "evaluation_parse_probe_manifest",
                    "review_required": True,
                    "legal_conclusion_allowed": False,
                }
            )
    review_reasons = ["fairness_clause_probe_review_required"]
    if not signals:
        review_reasons.append("fairness_clause_marker_not_detected")
    if not normalized:
        review_reasons.append("profile_text_unavailable")
    return {
        "probe_state": "PROBED" if signals else "REVIEW_NO_FAIRNESS_MARKER",
        "fairness_signal_count": len(signals),
        "signals": signals,
        "review_required": True,
        "review_reasons": list(dict.fromkeys(review_reasons)),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def build_profile_manifest(
    *,
    items: list[EvaluationStage3ProfileItem],
    sample_manifest_id: str,
    probe_manifest_id: str,
    database_url: str,
    target_backend: str,
    object_storage_path: Path,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint(
        {
            "manifest_version": EVALUATION_STAGE3_PROFILE_VERSION,
            "ruleset_id": EVALUATION_STAGE3_PROFILE_RULESET_ID,
            "sample_manifest_id": sample_manifest_id,
            "probe_manifest_id": probe_manifest_id,
            "items": [
                {
                    "seed_id": item.seed_id,
                    "snapshot_id_optional": item.snapshot_id_optional,
                    "profile_state": item.profile_state,
                    "evaluation_method_family": item.evaluation_method_profile.get("evaluation_method_family"),
                    "candidate_selection_mode": item.candidate_set_profile.get("candidate_selection_mode"),
                    "candidate_count_optional": item.candidate_set_profile.get("candidate_count_optional"),
                    "fairness_signal_count": item.fairness_clause_probe.get("fairness_signal_count"),
                }
                for item in items
            ],
        }
    )
    manifest_id = f"EVALUATION-STAGE3-PROFILE-{fingerprint[:16]}"
    payload = {
        "manifest_version": EVALUATION_STAGE3_PROFILE_VERSION,
        "ruleset_id": EVALUATION_STAGE3_PROFILE_RULESET_ID,
        "adapter_id": EVALUATION_STAGE3_PROFILE_ADAPTER_ID,
        "manifest_id": manifest_id,
        "profile_id": manifest_id,
        "created_at": created_at,
        "target_storage_backend": target_backend,
        "database_url_redacted": _redact_database_url(database_url),
        "object_storage_path": str(object_storage_path),
        "evaluation_corpus_sample_manifest_id": sample_manifest_id,
        "evaluation_parse_probe_manifest_id": probe_manifest_id,
        "profile_fingerprint": fingerprint,
        "summary": _summary(items),
        "items": [item.as_payload() for item in items],
        "sample_items": [item.as_payload() for item in items[:50]],
        "safety": _safety(),
    }
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _profile_context(
    *,
    sample: Mapping[str, Any],
    repository: ObjectStorageRepository,
    service: Stage3Service,
) -> dict[str, Any]:
    snapshot_id = _text(sample.get("snapshot_id_optional"))
    context: dict[str, Any] = {
        "profile_text": "",
        "profile_text_source": "probe_manifest_only",
        "parsed_fields": [],
        "stage3_parse_state_optional": None,
        "object_key_optional": _text(sample.get("object_key_optional")),
        "sha256_optional": _text(sample.get("sha256_optional")),
        "review_reasons": [],
    }
    if not snapshot_id:
        context["review_reasons"].append("snapshot_id_missing")
        return context
    readback = repository.replay_snapshot(snapshot_id)
    context["object_key_optional"] = _text(readback.get("object_key") or context.get("object_key_optional"))
    context["sha256_optional"] = _text(readback.get("sha256") or context.get("sha256_optional"))
    if not readback.get("replayable") or not isinstance(readback.get("bytes"), (bytes, bytearray)):
        context["profile_text_source"] = "snapshot_replay_failed"
        context["review_reasons"].append(f"snapshot_replay_failed:{readback.get('readback_state') or 'UNKNOWN'}")
        return context
    data = bytes(readback["bytes"])
    content_type = str(readback.get("content_type") or "")
    if _is_pdf(content_type=content_type, object_key=str(readback.get("object_key") or ""), data=data):
        pdf_result = _extract_pdf_embedded_text(data, max_pages=30)
        context["profile_text"] = _limit_text(pdf_result.text)
        context["profile_text_source"] = "pdf_embedded_text"
        if pdf_result.text:
            fields = [
                field.as_payload()
                for field in _extract_fields_from_text(
                    pdf_result.text,
                    source_file_ref=str(readback.get("object_key") or snapshot_id),
                    locator_type="pdf_text",
                    base_locator={"source": "pdf_text", "extractor": pdf_result.extractor},
                    confidence=pdf_result.confidence,
                    review_required=pdf_result.review_required,
                    parse_warnings=pdf_result.warnings,
                )
            ]
            context["parsed_fields"] = fields
            context["stage3_parse_state_optional"] = "PARSED" if fields else "REVIEW_REQUIRED"
        else:
            context["review_reasons"].append("pdf_embedded_text_unavailable")
            context["stage3_parse_state_optional"] = "REVIEW_REQUIRED"
        return context
    try:
        context["profile_text"] = _limit_text(_decode_text(data))
        context["profile_text_source"] = "snapshot_text_readback"
    except UnicodeDecodeError:
        context["profile_text_source"] = "snapshot_text_decode_failed"
        context["review_reasons"].append("snapshot_text_decode_failed")
    try:
        carrier = dict(service.parse_raw_snapshot_readback(readback))
        context["parsed_fields"] = list(carrier.get("parsed_fields") or [])
        context["stage3_parse_state_optional"] = _text(carrier.get("parse_state"))
        if bool(carrier.get("review_required")):
            context["review_reasons"].append("stage3_parser_review_required")
        for code in list(carrier.get("parse_error_taxonomy") or []):
            context["review_reasons"].append(f"stage3_parse_error:{code}")
    except Exception as exc:
        context["review_reasons"].append(f"stage3_parse_failed:{exc.__class__.__name__}")
        context["stage3_parse_state_optional"] = "REVIEW_REQUIRED"
    return context


def _detect_method_family(text: str) -> tuple[str, list[str]]:
    markers: list[str] = []
    if not text:
        return "unknown", markers
    if "评定分离" in text or "定标候选" in text:
        markers.append("评定分离/定标候选")
        return "bid_separation", markers
    if "合理低价" in text:
        markers.append("合理低价")
        return "reasonable_low_price", markers
    if re.search(r"经评审.{0,8}最低(?:投标)?价", text) or "最低投标价法" in text:
        markers.append("经评审最低投标价")
        return "reviewed_lowest_price", markers
    if "综合评估" in text:
        markers.append("综合评估")
        if re.search(r"技术标.{0,8}(打分|评分)", text):
            markers.append("技术标评分")
            return "technical_scored", markers
        return "comprehensive", markers
    if re.search(r"技术标.{0,8}(通过制|合格制)", text):
        markers.append("技术标通过制")
        return "technical_pass", markers
    if re.search(r"技术标.{0,8}(打分|评分)", text):
        markers.append("技术标评分")
        return "technical_scored", markers
    return "unknown", markers


def _detect_candidate_selection_mode(text: str) -> tuple[str, list[str]]:
    markers: list[str] = []
    if not text:
        return "unknown", markers
    if "评定分离" in text or "定标候选人" in text:
        markers.append("评定分离/定标候选人")
        return "bid_separation_candidates", markers
    if "排名不分先后" in text or "不排序" in text or "不分先后" in text:
        markers.append("排名不分先后")
        return "unranked_candidates", markers
    if RANK_LABEL_RE.search(text) or "候选人排序" in text:
        markers.append("候选人排序")
        return "ranked_candidates", markers
    if any(token in text for token in ("中标人名称", "中标单位", "成交供应商", "中标结果公告")) and "候选人" not in text:
        markers.append("单一中标结果")
        return "single_winner", markers
    return "unknown", markers


def _scoring_dimensions(text: str, field_summary: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    checks = (
        ("price", ("报价", "价格分", "评标基准价", "投标总价")),
        ("technical", ("技术标", "技术评分", "施工组织设计", "技术方案")),
        ("commercial", ("商务标", "商务评分", "商务部分")),
        ("credit", ("信用", "诚信", "履约信用")),
        ("qualification", ("资质", "资格", "资格审查")),
        ("performance", ("业绩", "类似工程", "类似项目")),
        ("project_manager", ("项目负责人", "项目经理", "注册建造师")),
    )
    dimensions: list[dict[str, Any]] = []
    field_names = {str(field.get("field_name") or "") for field in field_summary}
    for dimension, tokens in checks:
        markers = [token for token in tokens if token in text]
        if dimension == "project_manager" and {
            "project_manager_name",
            "project_manager_public_identifier_optional",
        } & field_names:
            markers.append("stage3_project_manager_field")
        if markers:
            dimensions.append(
                {
                    "dimension": dimension,
                    "markers": list(dict.fromkeys(markers)),
                    "review_required": True,
                }
            )
    return dimensions


def _extract_candidates(text: str, *, mode: str) -> list[dict[str, Any]]:
    if not text:
        return []
    if mode == "single_winner":
        winner = _match_value(text, ("中标人名称", "中标单位", "成交供应商"))
        return [_candidate_row(candidate_name=winner, rank=1, segment=text)] if winner else []
    ranked = _extract_ranked_candidates(text)
    if ranked:
        return ranked
    if mode in {"unranked_candidates", "bid_separation_candidates"}:
        return _extract_unranked_candidates(text)
    return []


def _extract_ranked_candidates(text: str) -> list[dict[str, Any]]:
    matches = list(RANK_LABEL_RE.finditer(text))
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), start + 500)
        segment = text[start:end]
        name = _candidate_name_from_segment(segment)
        if not name:
            continue
        rows.append(_candidate_row(candidate_name=name, rank=_cn_int(match.group("rank")), segment=segment))
    return rows


def _extract_unranked_candidates(text: str) -> list[dict[str, Any]]:
    match = re.search(r"(?:定标候选人|中标候选人|候选人名称)\s*[:：]\s*(?P<value>[^。；;\n\r]+)", text)
    if not match:
        return []
    value = re.split(r"(?:排名不分先后|不分先后|不排序|公示期|公示时间)", match.group("value"), maxsplit=1)[0]
    names = [_clean_candidate_name(part) for part in PUNCT_SPLIT_RE.split(value)]
    names = [name for name in names if name and len(name) >= 2]
    return [_candidate_row(candidate_name=name, rank=None, segment=text) for name in names[:10]]


def _candidate_row(*, candidate_name: str, rank: int | None, segment: str) -> dict[str, Any]:
    return {
        "candidate_name": _limit_text(candidate_name, limit=200),
        "candidate_rank_optional": rank,
        "bid_price_optional": _match_regex_value(segment, r"(?:投标报价|报价|投标总价)\s*[:：]?\s*([0-9,.]+(?:\s*(?:元|万元))?)"),
        "total_score_optional": _match_regex_value(segment, r"(?:总得分|综合得分|得分|评分)\s*[:：]?\s*([0-9.]+)"),
        "project_manager_optional": _match_regex_value(segment, r"(?:项目负责人|项目经理|拟派项目负责人)\s*[:：]?\s*([^\s，,；;。]+)"),
        "certificate_no_optional": _match_regex_value(segment, r"(?:证书编号|注册编号|注册证书编号|注册号)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fa5-]+)"),
        "match_basis": "deterministic_text_marker",
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_from_field_summary(field_summary: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    values = {
        str(field.get("field_name") or ""): _text(field.get("field_value_optional"))
        for field in field_summary
    }
    name = values.get("candidate_company")
    if not name:
        return []
    return [
        {
            "candidate_name": _limit_text(name, limit=200),
            "candidate_rank_optional": None,
            "bid_price_optional": None,
            "total_score_optional": None,
            "project_manager_optional": values.get("project_manager_name"),
            "certificate_no_optional": values.get("project_manager_public_identifier_optional"),
            "match_basis": "stage3_parsed_field_summary",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
    ]


def _candidate_name_from_segment(segment: str) -> str | None:
    for labels in (
        ("单位名称", "投标人名称", "中标候选人名称", "候选人名称"),
        ("中标候选人", "成交候选人"),
    ):
        value = _match_value(segment, labels)
        if value:
            return value
    head = STOP_TOKEN_RE.split(segment, maxsplit=1)[0]
    return _clean_candidate_name(head)


def _clean_candidate_name(value: str | None) -> str | None:
    if not value:
        return None
    text = HTML_TAG_RE.sub(" ", value)
    text = SPACE_RE.sub(" ", text).strip(" :：，,；;。-—")
    text = re.sub(r"^(?:名称|单位|候选人|为)\s*[:：]?", "", text).strip(" :：，,；;。-—")
    if not text:
        return None
    return _limit_text(text, limit=200)


def _fairness_signals(text: str) -> list[dict[str, Any]]:
    signal_defs = (
        ("geographic_restriction", ("特定行政区域", "注册地", "本地企业", "须在本市", "须在本省")),
        ("specified_brand_or_supplier", ("指定品牌", "指定供应商", "唯一品牌", "不接受同等产品")),
        ("ownership_restriction", ("限定所有制", "仅限国有", "限定国有企业", "仅限央企")),
        ("performance_threshold", ("类似业绩", "特定行业业绩", "单项合同额", "业绩金额")),
        ("discriminatory_scoring", ("差别待遇", "歧视待遇", "排斥潜在投标人", "限制潜在投标人")),
        ("evaluation_method_change", ("评标办法变更", "评标标准变更", "澄清修改评标", "修改评分办法")),
        ("dark_bid_identity_leakage", ("暗标出现投标人名称", "暗标出现单位名称", "暗标识别投标人")),
    )
    signals: list[dict[str, Any]] = []
    for signal_type, tokens in signal_defs:
        markers = [token for token in tokens if token in text]
        if markers:
            signals.append(
                {
                    "signal_type": signal_type,
                    "markers": markers,
                    "match_basis": "deterministic_text_marker",
                    "review_required": True,
                    "legal_conclusion_allowed": False,
                }
            )
    return signals


def _profile_state(
    *,
    context: Mapping[str, Any],
    method_profile: Mapping[str, Any],
    candidate_profile: Mapping[str, Any],
    fairness_probe: Mapping[str, Any],
) -> str:
    if context.get("review_reasons") and not context.get("profile_text"):
        return "PROFILE_REVIEW_REQUIRED"
    if (
        method_profile.get("evaluation_method_family") == "unknown"
        and candidate_profile.get("candidate_selection_mode") == "unknown"
        and fairness_probe.get("fairness_signal_count") == 0
    ):
        return "PROFILE_REVIEW_LOW_SIGNAL"
    return "PROFILED_REVIEW_READY"


def _review_reasons(
    *,
    context: Mapping[str, Any],
    method_profile: Mapping[str, Any],
    candidate_profile: Mapping[str, Any],
    fairness_probe: Mapping[str, Any],
) -> list[str]:
    reasons = ["evaluation_stage3_profile_review_required"]
    reasons.extend(str(reason) for reason in list(context.get("review_reasons") or []))
    reasons.extend(str(reason) for reason in list(method_profile.get("review_reasons") or []))
    reasons.extend(str(reason) for reason in list(candidate_profile.get("review_reasons") or []))
    reasons.extend(str(reason) for reason in list(fairness_probe.get("review_reasons") or []))
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _parsed_fields_summary(fields: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for field in fields:
        locator = dict(field.get("locator") or {})
        rows.append(
            {
                "field_name": _text(field.get("field_name")),
                "field_value_optional": _limit_text(_text(field.get("field_value_optional"))),
                "source_file_ref": _text(field.get("source_file_ref")),
                "source_slice_sha256": _text(field.get("source_slice_sha256")),
                "locator_type": _text(locator.get("type")),
                "confidence": field.get("confidence"),
                "review_required": bool(field.get("review_required")),
                "parse_warnings": list(field.get("parse_warnings") or []),
            }
        )
    return rows[:50]


def _profile_manifest_record(manifest: Mapping[str, Any], *, discovered_at: str) -> PersistedRecord:
    return PersistedRecord(
        object_type=EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE,
        record_id=str(manifest["manifest_id"]),
        stage_scope=3,
        project_id=None,
        object_refs={
            "evaluation_corpus_sample_manifest_id": str(manifest["evaluation_corpus_sample_manifest_id"]),
            "evaluation_parse_probe_manifest_id": str(manifest["evaluation_parse_probe_manifest_id"]),
        },
        decision_states={"evaluation_stage3_profile_manifest_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest["manifest_sha256"])},
        governed_state={
            "primary_status": "EVALUATION_STAGE3_PROFILE_READY",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "stage4_public_evidence_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at,
    )


def _summary(items: list[EvaluationStage3ProfileItem]) -> dict[str, Any]:
    return {
        "profile_item_count": len(items),
        "profile_state_counts": _counts(item.profile_state for item in items),
        "evaluation_method_family_counts": _counts(
            str(item.evaluation_method_profile.get("evaluation_method_family") or "unknown") for item in items
        ),
        "candidate_selection_mode_counts": _counts(
            str(item.candidate_set_profile.get("candidate_selection_mode") or "unknown") for item in items
        ),
        "candidate_rows_extracted_count": sum(
            int(item.candidate_set_profile.get("candidate_rows_extracted_count") or 0) for item in items
        ),
        "fairness_signal_count": sum(int(item.fairness_clause_probe.get("fairness_signal_count") or 0) for item in items),
        "review_required_count": len(items),
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _safety() -> dict[str, Any]:
    return {
        "external_service_connection_enabled": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "source_mutation_enabled": False,
        "download_enabled": False,
        "login_required_fetch_enabled": False,
        "captcha_resolution_enabled": False,
        "hidden_api_call_enabled": False,
        "bulk_ocr_enabled": False,
        "pdf_ocr_bulk_enablement": False,
        "stage4_public_evidence_readback_generation_enabled": False,
        "stage5_rule_execution_enabled": False,
        "large_object_blob_database_import_enabled": False,
    }


def _blocking_reasons(
    *,
    sample_record: PersistedRecord | None,
    probe_record: PersistedRecord | None,
) -> list[str]:
    reasons: list[str] = []
    if sample_record is None:
        reasons.append("evaluation_corpus_sample_manifest_missing")
    if probe_record is None:
        reasons.append("evaluation_parse_probe_manifest_missing")
    return reasons


def _manifest_items(record: PersistedRecord | None) -> list[dict[str, Any]]:
    if record is None:
        return []
    return [dict(item) for item in list(record.payload.get("items") or []) if isinstance(item, Mapping)]


def _latest_record(records: list[PersistedRecord]) -> PersistedRecord | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda row: (
            str(row.payload.get("created_at") or ""),
            row.persisted_at,
            row.record_id,
        ),
    )[-1]


def _normalize_text(value: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", str(value or ""), flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = HTML_TAG_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text)
    return text.strip()


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("utf-8", data, 0, min(len(data), 1), "decode failed")


def _is_pdf(*, content_type: str, object_key: str, data: bytes) -> bool:
    return content_type.split(";", 1)[0].strip().lower() == "application/pdf" or object_key.lower().endswith(".pdf") or data.startswith(b"%PDF")


def _contains_any(value: str, tokens: Iterable[str]) -> bool:
    return any(token in value for token in tokens)


def _known_or_unknown(value: Any, allowed: set[str]) -> str:
    text = str(value or "")
    return text if text in allowed else "unknown"


def _match_value(text: str, labels: Iterable[str]) -> str | None:
    pattern = re.compile(rf"(?:{'|'.join(re.escape(label) for label in labels)})\s*[:：]\s*(?P<value>[^；;。,\n\r]+)")
    match = pattern.search(text)
    return _clean_candidate_name(match.group("value")) if match else None


def _match_regex_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return _limit_text(SPACE_RE.sub(" ", match.group(1)).strip(" :：，,；;。"), limit=120)


def _objection_window(text: str) -> str | None:
    date_range = re.search(
        r"(?:公示|异议).{0,12}(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?).{0,20}(?:至|到|-|—).{0,8}(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)",
        text,
    )
    if date_range:
        return f"{date_range.group(1)}至{date_range.group(2)}"
    days = re.search(r"(?:公示期|公示时间|异议期).{0,20}([0-9一二三四五六七八九十]+)\s*(?:个)?工作?日", text)
    if days:
        return f"{days.group(1)}日"
    return None


def _cn_int(value: str | None) -> int | None:
    value = str(value or "").strip()
    if value.isdigit():
        return int(value)
    mapping = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    if value in mapping:
        return mapping[value]
    if value.startswith("十") and len(value) == 2:
        return 10 + mapping.get(value[1], 0)
    if "十" in value:
        left, right = value.split("十", 1)
        return mapping.get(left, 1) * 10 + mapping.get(right, 0)
    return None


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _limit_text(value: str | None, *, limit: int = PROFILE_TEXT_LIMIT) -> str:
    if value is None:
        return ""
    return value if len(value) <= limit else value[:limit]


def _text(value: Any) -> str | None:
    if value in (None, "", [], {}):
        return None
    return str(value)


def _counts(values: Iterable[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return _fingerprint({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def _redact_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build Stage3 evaluation method, candidate, and fairness profiles.")
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--object-storage-path", default=str(default_object_storage_path()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_stage3_profiles(
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path,
        execute=args.execute,
        limit=args.limit,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"evaluation stage3 profiles {result['profile_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVALUATION_STAGE3_PROFILE_MANIFEST_OBJECT_TYPE",
    "build_candidate_set_profile",
    "build_evaluation_method_profile",
    "build_evaluation_stage3_profiles",
    "build_fairness_clause_probe",
    "build_profile_items",
]
