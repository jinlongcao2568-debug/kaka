from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from shared.settings import Settings
from shared.utils import utc_now_iso
from stage2_ingestion.service import Stage2Service
from stage3_parsing.ocr_text import _extract_pdf_embedded_text
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.object_storage import default_object_storage_path
from storage.repositories.object_storage_repo import ObjectStorageRepository


EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE = "evaluation_method_source_catalog"
EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE = "evaluation_corpus_sample_manifest"
EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE = "evaluation_parse_probe_manifest"

EVALUATION_CORPUS_VERSION = 1
EVALUATION_CORPUS_RULESET_ID = "evaluation-corpus-v1"
EVALUATION_CORPUS_ADAPTER_ID = "evaluation-corpus-builder"
EVALUATION_SNAPSHOT_KIND = "evaluation_corpus_public_snapshot"

DOCUMENT_KINDS = frozenset(
    {
        "official_basis",
        "local_method",
        "tender_file",
        "candidate_notice",
        "award_result",
        "clarification",
    }
)
EVALUATION_METHOD_FAMILIES = frozenset(
    {
        "comprehensive",
        "reviewed_lowest_price",
        "reasonable_low_price",
        "technical_pass",
        "technical_scored",
        "bid_separation",
        "unknown",
    }
)
CANDIDATE_SELECTION_MODES = frozenset(
    {
        "ranked_candidates",
        "unranked_candidates",
        "bid_separation_candidates",
        "single_winner",
        "unknown",
    }
)

DEFAULT_SEED_PATH = Path("contracts") / "evaluation" / "evaluation_corpus_seed.json"
TEXT_PROBE_LIMIT = 256 * 1024


@dataclass(frozen=True)
class EvaluationCorpusSeed:
    seed_id: str
    source_url: str
    source_family: str
    jurisdiction: str
    project_type: str
    document_kind: str
    source_title: str | None = None
    fetch_profile_id_optional: str | None = None
    capture_kind: str = "detail"
    object_key_optional: str | None = None
    snapshot_id_optional: str | None = None
    sha256_optional: str | None = None
    probe_text_optional: str | None = None
    seed_tags: tuple[str, ...] = ()

    def public_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("probe_text_optional", None)
        payload["seed_tags"] = list(self.seed_tags)
        return payload


@dataclass(frozen=True)
class EvaluationCorpusSample:
    seed_id: str
    source_url: str
    source_family: str
    jurisdiction: str
    project_type: str
    document_kind: str
    source_title_optional: str | None
    evaluation_method_family: str
    candidate_selection_mode: str
    has_dark_bid_requirement: bool
    has_bright_bid_requirement: bool
    candidate_count_optional: int | None
    objection_window_optional: str | None
    snapshot_id_optional: str | None
    object_key_optional: str | None
    sha256_optional: str | None
    fetch_status: str
    fetch_failure_reason_optional: str | None
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvaluationParseProbe:
    seed_id: str
    source_url: str
    document_kind: str
    evaluation_method_family: str
    candidate_selection_mode: str
    method_markers: list[str]
    candidate_markers: list[str]
    fairness_markers: list[str]
    has_dark_bid_requirement: bool
    has_bright_bid_requirement: bool
    candidate_count_optional: int | None
    objection_window_optional: str | None
    candidate_rows_probe_summary: list[dict[str, Any]]
    scoring_dimensions_probe_summary: list[dict[str, Any]]
    fairness_signal_types: list[str]
    project_manager_field_detected: bool
    certificate_number_field_detected: bool
    probe_state: str
    review_required: bool = True
    customer_visible_allowed: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


def default_evaluation_seed_path() -> Path:
    return DEFAULT_SEED_PATH


def default_evaluation_object_storage_path() -> Path:
    base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
    return base_dir / "kaka" / "object-storage"


def build_evaluation_corpus(
    *,
    input_json: str | Path | None = None,
    database_url: str | None = None,
    target_backend: str = "postgresql",
    object_storage_path: str | Path | None = None,
    execute: bool = False,
    fetch_public_urls: bool = False,
    limit: int | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now_iso()
    seed_path = Path(input_json) if input_json is not None else default_evaluation_seed_path()
    root = Path(object_storage_path) if object_storage_path is not None else default_evaluation_object_storage_path()
    seeds = load_evaluation_corpus_seeds(seed_path)
    if limit is not None and limit >= 0:
        seeds = seeds[:limit]
    blocking_reasons = _blocking_reasons(seed_path=seed_path, seeds=seeds, execute=execute, database_url=database_url)

    settings: Settings | None = None
    session: DatabaseSession | None = None
    repository: ObjectStorageRepository | None = None
    fetch_results: dict[str, Mapping[str, Any]] = {}
    if execute and not blocking_reasons:
        settings = Settings(
            storage_backend=target_backend,
            storage_database_url_optional=database_url,
            storage_scope="shared",
            storage_runtime_mode="explicit-path",
            object_storage_path_optional=str(root),
        )
        session = DatabaseSession(settings=settings)
        repository = ObjectStorageRepository(session=session, settings=settings)

    try:
        if fetch_public_urls and execute and repository is not None:
            fetch_results = _fetch_seed_public_urls(seeds, repository=repository)
        samples, probes = build_evaluation_corpus_items(
            seeds,
            fetch_results=fetch_results,
            repository=repository,
        )
        source_catalog = build_source_catalog_manifest(
            seeds=seeds,
            samples=samples,
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        sample_manifest = build_sample_manifest(
            seeds=seeds,
            samples=samples,
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        probe_manifest = build_probe_manifest(
            probes=probes,
            sample_manifest_id=sample_manifest["manifest_id"],
            database_url=database_url,
            target_backend=target_backend,
            created_at=created,
        )
        result = {
            "evaluation_corpus_mode": "EXECUTED" if execute else "DRY_RUN",
            "execute": execute,
            "fetch_public_urls": bool(fetch_public_urls),
            "safe_to_execute": not blocking_reasons,
            "blocking_reasons": blocking_reasons,
            "source_catalog_manifest": source_catalog,
            "sample_manifest": sample_manifest,
            "probe_manifest": probe_manifest,
            "summary": {
                "source_catalog": source_catalog["summary"],
                "sample_manifest": sample_manifest["summary"],
                "probe_manifest": probe_manifest["summary"],
            },
            "execution": {
                "executed": False,
                "target_mutation_enabled": False,
                "database_write_enabled": False,
                "fetch_public_urls_enabled": False,
                "large_object_blob_database_import_enabled": False,
                "stage4_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
            },
        }
        if execute:
            if blocking_reasons:
                raise RuntimeError("evaluation corpus is not safe to execute: " + ", ".join(blocking_reasons))
            assert session is not None
            with session.bulk_write():
                session.upsert_record(_manifest_record(source_catalog, EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE, discovered_at=created))
                session.upsert_record(_manifest_record(sample_manifest, EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE, discovered_at=created))
                session.upsert_record(_manifest_record(probe_manifest, EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE, discovered_at=created))
            result["execution"] = {
                "executed": True,
                "target_mutation_enabled": True,
                "database_write_enabled": True,
                "fetch_public_urls_enabled": bool(fetch_public_urls),
                "fetched_snapshot_count": sum(1 for sample in samples if sample.snapshot_id_optional),
                "upserted_evaluation_method_source_catalog_count": 1,
                "upserted_evaluation_corpus_sample_manifest_count": 1,
                "upserted_evaluation_parse_probe_manifest_count": 1,
                "large_object_blob_database_import_enabled": False,
                "stage4_readback_generation_enabled": False,
                "stage5_rule_execution_enabled": False,
            }
        return result
    finally:
        if session is not None:
            session.close()


def load_evaluation_corpus_seeds(path: str | Path) -> list[EvaluationCorpusSeed]:
    seed_path = Path(path)
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    raw_items = payload.get("sources", payload if isinstance(payload, list) else [])
    if not isinstance(raw_items, list):
        raise ValueError("evaluation corpus seed must contain a sources list")
    seeds: list[EvaluationCorpusSeed] = []
    seen_urls: set[str] = set()
    for index, raw in enumerate(raw_items):
        if not isinstance(raw, Mapping):
            continue
        url = str(raw.get("source_url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        document_kind = _valid_or_default(str(raw.get("document_kind") or ""), DOCUMENT_KINDS, "official_basis")
        seeds.append(
            EvaluationCorpusSeed(
                seed_id=str(raw.get("seed_id") or f"EVAL-SEED-{index + 1:03d}"),
                source_url=url,
                source_family=str(raw.get("source_family") or _infer_source_family(url)),
                jurisdiction=str(raw.get("jurisdiction") or _infer_jurisdiction(url)),
                project_type=str(raw.get("project_type") or "construction"),
                document_kind=document_kind,
                source_title=_optional_str(raw.get("source_title")),
                fetch_profile_id_optional=_optional_str(raw.get("fetch_profile_id_optional") or raw.get("fetch_profile_id")),
                capture_kind=str(raw.get("capture_kind") or "detail"),
                object_key_optional=_optional_str(raw.get("object_key_optional") or raw.get("object_key")),
                snapshot_id_optional=_optional_str(raw.get("snapshot_id_optional") or raw.get("snapshot_id")),
                sha256_optional=_optional_str(raw.get("sha256_optional") or raw.get("sha256")),
                probe_text_optional=_optional_str(raw.get("probe_text_optional") or raw.get("probe_text")),
                seed_tags=tuple(str(tag) for tag in raw.get("seed_tags", []) if tag not in (None, "")),
            )
        )
    return seeds


def build_evaluation_corpus_items(
    seeds: Iterable[EvaluationCorpusSeed],
    *,
    fetch_results: Mapping[str, Mapping[str, Any]] | None = None,
    repository: ObjectStorageRepository | None = None,
) -> tuple[list[EvaluationCorpusSample], list[EvaluationParseProbe]]:
    samples: list[EvaluationCorpusSample] = []
    probes: list[EvaluationParseProbe] = []
    fetch_by_seed = dict(fetch_results or {})
    for seed in seeds:
        fetch_result = fetch_by_seed.get(seed.seed_id, {})
        snapshot_id = _optional_str(fetch_result.get("snapshot_id_optional") or seed.snapshot_id_optional)
        object_key = _optional_str(_manifest_payload(fetch_result).get("object_key") or seed.object_key_optional)
        sha256 = _optional_str(fetch_result.get("sha256") or _manifest_payload(fetch_result).get("sha256") or seed.sha256_optional)
        fetch_status = _fetch_status(seed, fetch_result)
        fetch_failure = _optional_str(fetch_result.get("failure_reason_optional") or fetch_result.get("blocked_reason"))
        text = _probe_text_for_seed(seed, fetch_result=fetch_result, repository=repository)
        probe = probe_evaluation_text(seed=seed, text=text)
        samples.append(
            EvaluationCorpusSample(
                seed_id=seed.seed_id,
                source_url=seed.source_url,
                source_family=seed.source_family,
                jurisdiction=seed.jurisdiction,
                project_type=seed.project_type,
                document_kind=seed.document_kind,
                source_title_optional=seed.source_title,
                evaluation_method_family=probe.evaluation_method_family,
                candidate_selection_mode=probe.candidate_selection_mode,
                has_dark_bid_requirement=probe.has_dark_bid_requirement,
                has_bright_bid_requirement=probe.has_bright_bid_requirement,
                candidate_count_optional=probe.candidate_count_optional,
                objection_window_optional=probe.objection_window_optional,
                snapshot_id_optional=snapshot_id,
                object_key_optional=object_key,
                sha256_optional=sha256,
                fetch_status=fetch_status,
                fetch_failure_reason_optional=fetch_failure,
            )
        )
        probes.append(probe)
    return samples, probes


def probe_evaluation_text(*, seed: EvaluationCorpusSeed, text: str | None) -> EvaluationParseProbe:
    normalized = _normalize_text(text or "")
    method_family, method_markers = _detect_evaluation_method(normalized)
    selection_mode, candidate_markers = _detect_candidate_selection_mode(normalized)
    fairness_markers = _detect_fairness_markers(normalized)
    candidate_rows = _extract_candidate_rows_probe_summary(normalized, selection_mode)
    scoring_dimensions = _scoring_dimensions_probe_summary(normalized)
    fairness_signal_types = _fairness_signal_types(normalized)
    has_dark = "暗标" in normalized or "暗 标" in normalized
    has_bright = "明标" in normalized or "明 标" in normalized
    candidate_count = _candidate_count(normalized)
    if candidate_count is None and candidate_rows:
        candidate_count = len(candidate_rows)
    objection_window = _objection_window(normalized)
    project_manager = any(token in normalized for token in ("项目负责人", "项目经理", "拟派项目负责人"))
    certificate_number = any(token in normalized for token in ("证书编号", "注册编号", "注册证书编号", "注册号"))
    probe_state = "PROBED" if normalized else "REVIEW_NO_TEXT"
    if method_family == "unknown" and selection_mode == "unknown" and not fairness_markers and normalized:
        probe_state = "PROBED_REVIEW_LOW_SIGNAL"
    return EvaluationParseProbe(
        seed_id=seed.seed_id,
        source_url=seed.source_url,
        document_kind=seed.document_kind,
        evaluation_method_family=method_family,
        candidate_selection_mode=selection_mode,
        method_markers=method_markers,
        candidate_markers=candidate_markers,
        fairness_markers=fairness_markers,
        has_dark_bid_requirement=has_dark,
        has_bright_bid_requirement=has_bright,
        candidate_count_optional=candidate_count,
        objection_window_optional=objection_window,
        candidate_rows_probe_summary=candidate_rows,
        scoring_dimensions_probe_summary=scoring_dimensions,
        fairness_signal_types=fairness_signal_types,
        project_manager_field_detected=project_manager,
        certificate_number_field_detected=certificate_number,
        probe_state=probe_state,
    )


def build_source_catalog_manifest(
    *,
    seeds: list[EvaluationCorpusSeed],
    samples: list[EvaluationCorpusSample],
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    catalog_items = [
        {
            **seed.public_payload(),
            "catalog_role": "basis_or_method_source",
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
        }
        for seed in seeds
        if seed.document_kind in {"official_basis", "local_method"}
    ]
    payload = _base_manifest(
        manifest_kind=EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE,
        items=catalog_items,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created_at,
    )
    payload["summary"] = {
        "source_count": len(catalog_items),
        "document_kind_counts": _counts(item["document_kind"] for item in catalog_items),
        "jurisdiction_counts": _counts(item["jurisdiction"] for item in catalog_items),
        "source_family_counts": _counts(item["source_family"] for item in catalog_items),
        "linked_sample_count": len(samples),
    }
    payload["sample_items"] = catalog_items[:50]
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def build_sample_manifest(
    *,
    seeds: list[EvaluationCorpusSeed],
    samples: list[EvaluationCorpusSample],
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    items = [sample.as_payload() for sample in samples]
    payload = _base_manifest(
        manifest_kind=EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE,
        items=items,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created_at,
    )
    payload["summary"] = {
        "seed_count": len(seeds),
        "sample_count": len(items),
        "document_kind_counts": _counts(sample.document_kind for sample in samples),
        "evaluation_method_family_counts": _counts(sample.evaluation_method_family for sample in samples),
        "candidate_selection_mode_counts": _counts(sample.candidate_selection_mode for sample in samples),
        "snapshot_ref_count": sum(1 for sample in samples if sample.snapshot_id_optional),
        "object_key_ref_count": sum(1 for sample in samples if sample.object_key_optional),
        "fetch_status_counts": _counts(sample.fetch_status for sample in samples),
    }
    payload["items"] = items
    payload["sample_items"] = items[:50]
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def build_probe_manifest(
    *,
    probes: list[EvaluationParseProbe],
    sample_manifest_id: str,
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    items = [probe.as_payload() for probe in probes]
    payload = _base_manifest(
        manifest_kind=EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE,
        items=items,
        database_url=database_url,
        target_backend=target_backend,
        created_at=created_at,
    )
    payload["source_sample_manifest_id"] = sample_manifest_id
    payload["summary"] = {
        "probe_count": len(items),
        "probe_state_counts": _counts(probe.probe_state for probe in probes),
        "evaluation_method_family_counts": _counts(probe.evaluation_method_family for probe in probes),
        "candidate_selection_mode_counts": _counts(probe.candidate_selection_mode for probe in probes),
        "dark_bid_requirement_count": sum(1 for probe in probes if probe.has_dark_bid_requirement),
        "bright_bid_requirement_count": sum(1 for probe in probes if probe.has_bright_bid_requirement),
        "fairness_marker_count": sum(1 for probe in probes if probe.fairness_markers),
        "project_manager_certificate_field_count": sum(
            1 for probe in probes if probe.project_manager_field_detected and probe.certificate_number_field_detected
        ),
    }
    payload["items"] = items
    payload["sample_items"] = items[:50]
    payload["manifest_sha256"] = _manifest_sha256(payload)
    return payload


def _fetch_seed_public_urls(
    seeds: Iterable[EvaluationCorpusSeed],
    *,
    repository: ObjectStorageRepository,
) -> dict[str, Mapping[str, Any]]:
    service = Stage2Service(settings=repository.settings)
    results: dict[str, Mapping[str, Any]] = {}
    for seed in seeds:
        if not seed.fetch_profile_id_optional:
            results[seed.seed_id] = {
                "status": "FETCH_SKIPPED",
                "failure_reason_optional": "missing_stage2_fetch_profile",
                "source_url": seed.source_url,
            }
            continue
        lineage_refs = {
            "evaluation_corpus_seed_id": seed.seed_id,
            "document_kind": seed.document_kind,
            "source_family": seed.source_family,
            "jurisdiction": seed.jurisdiction,
        }
        try:
            if seed.capture_kind == "entry":
                carrier = service.fetch_real_public_entry_url(
                    seed.source_url,
                    profile_id=seed.fetch_profile_id_optional,
                    repository=repository,
                    lineage_refs=lineage_refs,
                )
            elif seed.capture_kind == "attachment":
                carrier = service.fetch_real_public_same_site_attachment_url(
                    seed.source_url,
                    parent_profile_id=seed.fetch_profile_id_optional,
                    repository=repository,
                    lineage_refs=lineage_refs,
                )
            else:
                carrier = service.fetch_real_public_candidate_detail_url(
                    seed.source_url,
                    profile_id=seed.fetch_profile_id_optional,
                    repository=repository,
                    lineage_refs=lineage_refs,
                )
            results[seed.seed_id] = dict(carrier)
        except Exception as exc:
            results[seed.seed_id] = {
                "status": "FETCH_FAILED_REVIEW",
                "failure_reason_optional": str(exc),
                "source_url": seed.source_url,
                "fail_closed": True,
            }
    return results


def _probe_text_for_seed(
    seed: EvaluationCorpusSeed,
    *,
    fetch_result: Mapping[str, Any],
    repository: ObjectStorageRepository | None,
) -> str:
    if seed.probe_text_optional:
        return seed.probe_text_optional[:TEXT_PROBE_LIMIT]
    snapshot_id = _optional_str(fetch_result.get("snapshot_id_optional") or seed.snapshot_id_optional)
    if not snapshot_id or repository is None:
        return ""
    readback = repository.replay_snapshot(snapshot_id)
    data = readback.get("bytes")
    if not isinstance(data, (bytes, bytearray)):
        return ""
    content_type = str(readback.get("content_type") or _manifest_payload(fetch_result).get("content_type") or "")
    if content_type == "application/pdf" or bytes(data).startswith(b"%PDF"):
        return _extract_pdf_embedded_text(bytes(data), max_pages=20).text[:TEXT_PROBE_LIMIT]
    return _decode_text(bytes(data))[:TEXT_PROBE_LIMIT]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "gb18030", "gbk"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _detect_evaluation_method(text: str) -> tuple[str, list[str]]:
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
            markers.append("技术标打分")
            return "technical_scored", markers
        return "comprehensive", markers
    if re.search(r"技术标.{0,8}(通过制|合格制)", text):
        markers.append("技术标通过制")
        return "technical_pass", markers
    if re.search(r"技术标.{0,8}(打分|评分)", text):
        markers.append("技术标打分")
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
    if re.search(r"第[一二三四五六七八九十0-9]+(?:中标|成交)?候选人", text) or "候选人排序" in text:
        markers.append("候选人排序")
        return "ranked_candidates", markers
    if any(token in text for token in ("中标人名称", "中标单位", "成交供应商", "中标结果公告")) and "候选人" not in text:
        markers.append("单一中标结果")
        return "single_winner", markers
    return "unknown", markers


def _detect_fairness_markers(text: str) -> list[str]:
    marker_tokens = (
        "特定行政区域",
        "特定行业",
        "指定品牌",
        "指定供应商",
        "限定所有制",
        "排斥潜在投标人",
        "限制潜在投标人",
        "量身定制",
        "类似业绩",
        "奖项",
        "注册地",
        "本地企业",
        "差别待遇",
        "歧视待遇",
    )
    return [token for token in marker_tokens if token in text]


def _scoring_dimensions_probe_summary(text: str) -> list[dict[str, Any]]:
    checks = (
        ("price", ("报价", "价格分", "评标基准价", "投标总价")),
        ("technical", ("技术标", "技术评分", "施工组织设计", "技术方案")),
        ("commercial", ("商务标", "商务评分", "商务部分")),
        ("credit", ("信用", "诚信", "资信标", "资信评分")),
        ("qualification", ("资质", "资格", "资格审查")),
        ("performance", ("业绩", "类似工程", "类似项目")),
        ("project_manager", ("项目负责人", "项目经理", "注册建造师")),
    )
    dimensions: list[dict[str, Any]] = []
    for dimension, tokens in checks:
        markers = [token for token in tokens if token in text]
        if markers:
            dimensions.append(
                {
                    "dimension": dimension,
                    "markers": list(dict.fromkeys(markers)),
                    "match_basis": "probe_text_marker_summary",
                    "review_required": True,
                }
            )
    return dimensions


def _fairness_signal_types(text: str) -> list[str]:
    signal_defs = (
        ("geographic_restriction", ("特定行政区域", "注册地", "本地企业", "须在本市", "须在本省", "外地业绩不予认可")),
        ("specified_brand_or_supplier", ("指定品牌", "指定供应商", "唯一品牌", "不接受同等", "不接受同等档次")),
        ("ownership_restriction", ("限定所有制", "仅限国有", "限定国有企业", "仅限央企")),
        ("performance_threshold", ("类似业绩", "特定行业业绩", "单项合同额", "业绩金额")),
        ("discriminatory_scoring", ("差别待遇", "歧视待遇", "排斥潜在投标人", "限制潜在投标人", "评分倾斜")),
        ("evaluation_method_change", ("评标办法变更", "评标标准变更", "澄清修改评标", "修改评分办法", "技术标评分项调整")),
        ("dark_bid_identity_leakage", ("暗标出现投标人名称", "暗标出现单位名称", "暗标识别投标人")),
    )
    signals: list[str] = []
    for signal_type, tokens in signal_defs:
        if any(token in text for token in tokens):
            signals.append(signal_type)
    return signals


def _extract_candidate_rows_probe_summary(text: str, selection_mode: str) -> list[dict[str, Any]]:
    if not text:
        return []
    if selection_mode == "single_winner":
        winner = _match_labeled_value(text, ("中标人名称", "中标单位", "成交供应商"))
        return [_candidate_row_summary(candidate_name=winner, rank=1, segment=text)] if winner else []
    ranked = _extract_ranked_candidate_rows(text)
    if ranked:
        return ranked
    if selection_mode in {"unranked_candidates", "bid_separation_candidates"}:
        return _extract_unranked_candidate_rows(text)
    return []


def _extract_ranked_candidate_rows(text: str) -> list[dict[str, Any]]:
    pattern = re.compile(r"第(?P<rank>[一二三四五六七八九十0-9]+)(?:中标|成交)?候选人")
    matches = list(pattern.finditer(text))
    rows: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), start + 500)
        segment = text[start:end]
        name = _candidate_name_from_segment(segment)
        if name:
            rows.append(_candidate_row_summary(candidate_name=name, rank=_cn_int(match.group("rank")), segment=segment))
    return rows


def _extract_unranked_candidate_rows(text: str) -> list[dict[str, Any]]:
    match = re.search(r"(?:定标候选人|中标候选人|候选人名单|候选人名称)\s*[:：]\s*(?P<value>[^。；;\n\r]+)", text)
    if not match:
        return []
    value = re.split(r"(?:排名不分先后|不分先后|不排序|公示期|公示时间)", match.group("value"), maxsplit=1)[0]
    names = [_clean_candidate_name(part) for part in re.split(r"[、,，;；\n\r]+", value)]
    return [
        _candidate_row_summary(candidate_name=name, rank=None, segment=text)
        for name in names[:10]
        if name and len(name) >= 2
    ]


def _candidate_row_summary(*, candidate_name: str, rank: int | None, segment: str) -> dict[str, Any]:
    return {
        "candidate_name": _limit_summary_text(candidate_name, 200),
        "candidate_rank_optional": rank,
        "bid_price_optional": _match_regex_value(segment, r"(?:投标报价|报价|投标总价|中标金额)\s*[:：]?\s*([0-9,.]+(?:\s*(?:元|万元))?)"),
        "total_score_optional": _match_regex_value(segment, r"(?:总得分|综合得分|得分|评分)\s*[:：]?\s*([0-9.]+)"),
        "project_manager_optional": _match_regex_value(segment, r"(?:项目负责人|项目经理|拟派项目负责人)\s*[:：]?\s*([^\s，,；;。]+)"),
        "certificate_no_optional": _match_regex_value(segment, r"(?:证书编号|注册编号|注册证书编号|注册号)\s*[:：]?\s*([A-Za-z0-9\u4e00-\u9fa5-]+)"),
        "match_basis": "probe_text_marker_summary",
        "review_required": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
    }


def _candidate_name_from_segment(segment: str) -> str | None:
    for labels in (
        ("单位名称", "投标人名称", "中标候选人名称", "候选人名称"),
        ("中标候选人", "成交候选人"),
    ):
        value = _match_labeled_value(segment, labels)
        if value:
            return value
    head = re.split(
        r"(?:投标报价|报价|投标总价|中标金额|总得分|综合得分|得分|评分|项目负责人|项目经理|拟派项目负责人|证书编号|注册编号|注册证书编号|注册号|质量|工期|资格能力|公示期|公示时间|异议期)",
        segment,
        maxsplit=1,
    )[0]
    return _clean_candidate_name(head)


def _match_labeled_value(text: str, labels: tuple[str, ...]) -> str | None:
    pattern = re.compile(rf"(?:{'|'.join(re.escape(label) for label in labels)})\s*[:：]\s*(?P<value>[^；;。,\n\r]+)")
    match = pattern.search(text)
    return _clean_candidate_name(_trim_candidate_value(match.group("value"))) if match else None


def _match_regex_value(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    if not match:
        return None
    return _limit_summary_text(re.sub(r"\s+", " ", match.group(1)).strip(" :：，,；;。"), 120)


def _clean_candidate_name(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", value)
    text = re.sub(r"\s+", " ", text).strip(" :：，,；;。-—")
    text = re.sub(r"^(?:名称|单位|候选人|为)\s*[:：]?", "", text).strip(" :：，,；;。-—")
    return _limit_summary_text(text, 200) if text else None


def _trim_candidate_value(value: str) -> str:
    return re.split(
        r"(?:投标报价|报价|投标总价|中标金额|总得分|综合得分|得分|评分|项目负责人|项目经理|拟派项目负责人|证书编号|注册编号|注册证书编号|注册号|公示期|公示时间|异议期)\s*[:：]?",
        value,
        maxsplit=1,
    )[0]


def _limit_summary_text(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[:limit]


def _candidate_count(text: str) -> int | None:
    ranked = set(re.findall(r"第([一二三四五六七八九十0-9]+)(?:中标|成交)?候选人", text))
    if ranked:
        return len(ranked)
    match = re.search(r"(?:推荐|确定|提出).{0,12}([0-9一二三四五六七八九十]+)\s*名.{0,8}(?:候选人|定标候选人)", text)
    if match:
        return _cn_int(match.group(1))
    match = re.search(r"候选人.{0,8}([0-9一二三四五六七八九十]+)\s*名", text)
    if match:
        return _cn_int(match.group(1))
    return None


def _objection_window(text: str) -> str | None:
    date_range = re.search(
        r"(?:公示|异议).{0,12}(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?).{0,20}(?:至|到|-|—).{0,8}(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?)",
        text,
    )
    if date_range:
        return f"{date_range.group(1)}至{date_range.group(2)}"
    days = re.search(r"(?:公示期|公示时间|异议期).{0,20}([0-9一二三四五六七八九十]+)\s*(?:个)?(?:工作日|日)", text)
    if days:
        return f"{days.group(1)}日"
    return None


def _base_manifest(
    *,
    manifest_kind: str,
    items: list[Mapping[str, Any]],
    database_url: str | None,
    target_backend: str,
    created_at: str,
) -> dict[str, Any]:
    fingerprint = _fingerprint({"manifest_kind": manifest_kind, "items": items})
    return {
        "manifest_version": EVALUATION_CORPUS_VERSION,
        "ruleset_id": EVALUATION_CORPUS_RULESET_ID,
        "adapter_id": EVALUATION_CORPUS_ADAPTER_ID,
        "manifest_id": f"{manifest_kind.upper().replace('_', '-')}-{fingerprint[:16]}",
        "manifest_kind": manifest_kind,
        "created_at": created_at,
        "database_url_redacted": _redact_database_url(database_url),
        "target_storage_backend": target_backend,
        "corpus_fingerprint": fingerprint,
        "items": list(items),
        "safety": {
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "download_requires_explicit_fetch_public_urls": True,
            "login_required_fetch_enabled": False,
            "captcha_resolution_enabled": False,
            "hidden_api_call_enabled": False,
            "bulk_ocr_enabled": False,
            "stage4_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
            "large_object_blob_database_import_enabled": False,
        },
    }


def _manifest_record(manifest: Mapping[str, Any], object_type: str, *, discovered_at: str) -> PersistedRecord:
    manifest_id = str(manifest["manifest_id"])
    return PersistedRecord(
        object_type=object_type,
        record_id=manifest_id,
        stage_scope=0,
        project_id=None,
        object_refs={"manifest_id": manifest_id},
        decision_states={f"{object_type}_state": "CURRENT"},
        trace_refs={},
        audit_refs={"manifest_sha256": str(manifest.get("manifest_sha256") or "")},
        governed_state={
            "review_required": True,
            "customer_visible_allowed": False,
            "no_legal_conclusion": True,
            "external_service_connection_enabled": False,
        },
        writeback_state={
            "stage4_readback_generation_enabled": False,
            "stage5_rule_execution_enabled": False,
        },
        payload=dict(manifest),
        persisted_at=discovered_at or build_persisted_at(),
    )


def _fetch_status(seed: EvaluationCorpusSeed, fetch_result: Mapping[str, Any]) -> str:
    if fetch_result.get("snapshot_id_optional") or _manifest_payload(fetch_result).get("snapshot_id"):
        return "FETCHED_WITH_SNAPSHOT"
    if fetch_result:
        return str(fetch_result.get("status") or "REVIEW_NO_SNAPSHOT")
    if seed.snapshot_id_optional or seed.object_key_optional:
        return "EXISTING_REF_ONLY"
    return "NOT_FETCHED"


def _manifest_payload(fetch_result: Mapping[str, Any]) -> Mapping[str, Any]:
    manifest = fetch_result.get("manifest_optional")
    return manifest if isinstance(manifest, Mapping) else {}


def _blocking_reasons(
    *,
    seed_path: Path,
    seeds: list[EvaluationCorpusSeed],
    execute: bool,
    database_url: str | None,
) -> list[str]:
    reasons: list[str] = []
    if not seed_path.exists():
        reasons.append("evaluation_seed_file_missing")
    if not seeds:
        reasons.append("evaluation_seed_empty")
    invalid_urls = [seed.seed_id for seed in seeds if urlsplit(seed.source_url).scheme not in {"http", "https"}]
    if invalid_urls:
        reasons.append("invalid_seed_url:" + ",".join(invalid_urls[:10]))
    if execute and not database_url:
        reasons.append("database_url_required_for_execute")
    return reasons


def _normalize_text(value: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", value, flags=re.I | re.S)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _valid_or_default(value: str, allowed: frozenset[str], default: str) -> str:
    return value if value in allowed else default


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _infer_source_family(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if "ggzy" in host or "jyxx" in host or "bid" in host:
        return "local_public_resource_trading_center"
    if "gov.cn" in host or "npc.gov.cn" in host or "ndrc.gov.cn" in host or "mohurd.gov.cn" in host:
        return "official_government_policy"
    return "evaluation_corpus_public_source"


def _infer_jurisdiction(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if "gd.gov.cn" in host or "gzggzy" in host:
        return "CN-GD"
    if "jiangsu" in host or "jszwfw" in host or "jsjlztb" in host:
        return "CN-JS"
    if "zj.gov.cn" in host or "zhejiang" in host:
        return "CN-ZJ"
    if "beijing" in host or "bj" in host:
        return "CN-BJ"
    if "hubei" in host or "hbbidcloud" in host:
        return "CN-HB"
    if "hlj.gov.cn" in host:
        return "CN-HLJ"
    return "CN"


def _cn_int(value: str) -> int | None:
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


def _redact_database_url(database_url: str | None) -> str:
    if not database_url or "://" not in database_url or "@" not in database_url:
        return database_url or ""
    scheme, rest = database_url.split("://", 1)
    credentials, host = rest.split("@", 1)
    username = credentials.split(":", 1)[0]
    return f"{scheme}://{username}:***@{host}"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build evaluation method and candidate corpus manifests.")
    parser.add_argument("--input-json", default=str(default_evaluation_seed_path()))
    parser.add_argument("--database-url")
    parser.add_argument("--target-backend", default="postgresql")
    parser.add_argument("--object-storage-path", default="")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--fetch-public-urls", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_evaluation_corpus(
        input_json=args.input_json,
        database_url=args.database_url,
        target_backend=args.target_backend,
        object_storage_path=args.object_storage_path or None,
        execute=args.execute,
        fetch_public_urls=args.fetch_public_urls,
        limit=args.limit,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"evaluation corpus {result['evaluation_corpus_mode']}: safe_to_execute={result['safe_to_execute']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
    return 0 if result["safe_to_execute"] or not args.execute else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EVALUATION_CORPUS_SAMPLE_MANIFEST_OBJECT_TYPE",
    "EVALUATION_METHOD_SOURCE_CATALOG_OBJECT_TYPE",
    "EVALUATION_PARSE_PROBE_MANIFEST_OBJECT_TYPE",
    "build_evaluation_corpus",
    "build_evaluation_corpus_items",
    "load_evaluation_corpus_seeds",
    "probe_evaluation_text",
]
