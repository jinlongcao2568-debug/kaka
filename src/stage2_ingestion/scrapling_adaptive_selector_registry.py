from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from urllib.parse import urljoin, urlsplit

from stage2_ingestion.scrapling_snapshot_parser import _decode_html, _normalize_text


SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID = "stage2.scrapling_adaptive_selector_registry.v1"


@dataclass(frozen=True)
class ScraplingAdaptiveSelectorProbe:
    probe_id: str
    selector_kind: str
    selectors: tuple[str, ...]
    label: str = ""
    identifier: str = ""
    max_records: int = 8
    attribute_names: tuple[str, ...] = ("href", "onclick", "title", "data-url", "class")

    def resolved_identifier(self) -> str:
        return self.identifier or f"stage2.public_notice.{self.probe_id}"


DEFAULT_PUBLIC_NOTICE_ADAPTIVE_SELECTOR_PROBES: tuple[ScraplingAdaptiveSelectorProbe, ...] = (
    ScraplingAdaptiveSelectorProbe(
        probe_id="notice_title",
        label="公告标题",
        selector_kind="css",
        selectors=(
            ".notice-title",
            ".article-title",
            ".detail-title",
            ".ewb-article-title",
            "h1",
            "h2",
            "title",
        ),
        max_records=3,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="notice_body",
        label="公告正文",
        selector_kind="css",
        selectors=(
            ".article-content",
            ".detail-content",
            ".ewb-info-main",
            ".content",
            "#content",
            "body",
        ),
        max_records=2,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="attachment_link",
        label="附件入口",
        selector_kind="css",
        selectors=(
            "a[href*='download']",
            "a[href*='attach']",
            "a[href$='.pdf']",
            "a[onclick*='download']",
            "a[onclick*='attachGuid']",
            "a",
        ),
        max_records=12,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="table",
        label="表格",
        selector_kind="css",
        selectors=("table",),
        max_records=12,
    ),
    ScraplingAdaptiveSelectorProbe(
        probe_id="candidate_row",
        label="候选人表行",
        selector_kind="xpath",
        selectors=(
            "//tr[contains(string(.), '中标候选人') or contains(string(.), '成交候选人') or contains(string(.), '第一名')]",
        ),
        max_records=12,
    ),
)


def build_scrapling_adaptive_selector_registry_readback(
    html: str | bytes,
    *,
    base_url: str = "",
    storage_file: str | Path | None = None,
    storage_scope_url: str = "",
    train: bool = False,
    allow_adaptive_relocation: bool = True,
    percentage: int = 40,
    probes: Iterable[ScraplingAdaptiveSelectorProbe] = DEFAULT_PUBLIC_NOTICE_ADAPTIVE_SELECTOR_PROBES,
    selector_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    body = _decode_html(html)
    selected_probes = tuple(probes)
    if storage_file is None or not str(storage_file).strip():
        return _disabled_readback(
            body=body,
            base_url=base_url,
            selected_probes=selected_probes,
            state="ADAPTIVE_SELECTOR_STORAGE_NOT_CONFIGURED",
            failure_taxonomy=["adaptive_selector_storage_not_configured"],
        )

    storage_path = Path(storage_file)
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    failure_taxonomy: list[str] = []
    selector_backend_available = False
    selector: Any | None = None

    if selector_factory is None:
        try:
            from scrapling.parser import Selector  # type: ignore

            selector_factory = Selector
            selector_backend_available = True
        except Exception as exc:  # pragma: no cover - depends on optional runtime dependency
            failure_taxonomy.append(f"scrapling_import_failed:{type(exc).__name__}")
    else:
        selector_backend_available = True

    if selector_factory is None:
        return _disabled_readback(
            body=body,
            base_url=base_url,
            selected_probes=selected_probes,
            state="SCRAPLING_SELECTOR_UNAVAILABLE",
            failure_taxonomy=failure_taxonomy,
        )

    try:
        selector = selector_factory(
            content=body,
            url=base_url,
            adaptive=True,
            storage_args={
                "storage_file": str(storage_path),
                "url": storage_scope_url or _adaptive_storage_scope_url(base_url),
            },
        )
        probe_records = [
            _run_adaptive_selector_probe(
                selector=selector,
                probe=probe,
                base_url=base_url,
                train=train,
                allow_adaptive_relocation=allow_adaptive_relocation,
                percentage=percentage,
            )
            for probe in selected_probes
        ]
        state = "ADAPTIVE_SELECTOR_REGISTRY_PROBED"
    except Exception as exc:  # pragma: no cover - Scrapling internals may vary by release
        probe_records = []
        state = "ADAPTIVE_SELECTOR_REGISTRY_FAILED"
        failure_taxonomy.append(f"adaptive_selector_registry_failed:{type(exc).__name__}")
    finally:
        _close_scrapling_selector_storage(selector)

    summary = _adaptive_selector_summary(
        selected_probes=selected_probes,
        probe_records=probe_records,
        state=state,
    )
    return {
        "parser_adapter_id": SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID,
        "registry_state": state,
        "registry_mode": "TRAIN" if train else "RELOCATE_OR_PROBE",
        "scrapling_available": selector_backend_available,
        "scrapling_missing": not selector_backend_available,
        "no_live_request": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "base_url": base_url,
        "storage_scope_url": storage_scope_url or _adaptive_storage_scope_url(base_url),
        "storage_file": str(storage_path),
        "source_html_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "adaptive_selector_summary": summary,
        "probe_records": probe_records,
        "failure_taxonomy": list(dict.fromkeys(failure_taxonomy)),
    }


def build_scrapling_adaptive_selector_summary(readback: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "parser_adapter_id": str(readback.get("parser_adapter_id") or ""),
        "registry_state": str(readback.get("registry_state") or ""),
        "registry_mode": str(readback.get("registry_mode") or ""),
        "scrapling_available": bool(readback.get("scrapling_available")),
        "scrapling_missing": bool(readback.get("scrapling_missing")),
        "no_live_request": bool(readback.get("no_live_request")),
        "customer_visible_allowed": bool(readback.get("customer_visible_allowed")),
        "no_legal_conclusion": bool(readback.get("no_legal_conclusion")),
        "storage_scope_url": str(readback.get("storage_scope_url") or ""),
        "adaptive_selector_summary": dict(readback.get("adaptive_selector_summary") or {}),
        "failure_taxonomy": list(readback.get("failure_taxonomy") or []),
    }


def _run_adaptive_selector_probe(
    *,
    selector: Any,
    probe: ScraplingAdaptiveSelectorProbe,
    base_url: str,
    train: bool,
    allow_adaptive_relocation: bool,
    percentage: int,
) -> dict[str, Any]:
    errors: list[str] = []
    identifier = probe.resolved_identifier()
    for expression in probe.selectors:
        try:
            selections = _select_elements(
                selector=selector,
                selector_kind=probe.selector_kind,
                expression=expression,
                identifier=identifier,
                adaptive=False,
                auto_save=train,
                percentage=percentage,
            )
        except Exception as exc:
            errors.append(f"selector_failed:{type(exc).__name__}")
            continue
        if selections:
            return _probe_record(
                probe=probe,
                identifier=identifier,
                match_state="SELECTOR_HIT",
                selector_expression=expression,
                adaptive_relocated=False,
                trained=bool(train),
                selections=selections,
                base_url=base_url,
                errors=errors,
            )

    if allow_adaptive_relocation and probe.selectors:
        expression = probe.selectors[0]
        try:
            selections = _select_elements(
                selector=selector,
                selector_kind=probe.selector_kind,
                expression=expression,
                identifier=identifier,
                adaptive=True,
                auto_save=train,
                percentage=percentage,
            )
        except Exception as exc:
            errors.append(f"adaptive_relocation_failed:{type(exc).__name__}")
            selections = []
        if selections:
            return _probe_record(
                probe=probe,
                identifier=identifier,
                match_state="ADAPTIVE_RELOCATED",
                selector_expression=expression,
                adaptive_relocated=True,
                trained=bool(train),
                selections=selections,
                base_url=base_url,
                errors=errors,
            )

    return _probe_record(
        probe=probe,
        identifier=identifier,
        match_state="NOT_FOUND",
        selector_expression=probe.selectors[0] if probe.selectors else "",
        adaptive_relocated=False,
        trained=False,
        selections=[],
        base_url=base_url,
        errors=errors,
    )


def _select_elements(
    *,
    selector: Any,
    selector_kind: str,
    expression: str,
    identifier: str,
    adaptive: bool,
    auto_save: bool,
    percentage: int,
) -> list[Any]:
    if selector_kind == "css":
        return list(
            selector.css(
                expression,
                identifier=identifier,
                adaptive=adaptive,
                auto_save=auto_save,
                percentage=percentage,
            )
        )
    if selector_kind == "xpath":
        return list(
            selector.xpath(
                expression,
                identifier=identifier,
                adaptive=adaptive,
                auto_save=auto_save,
                percentage=percentage,
            )
        )
    raise ValueError(f"Unsupported selector kind: {selector_kind}")


def _probe_record(
    *,
    probe: ScraplingAdaptiveSelectorProbe,
    identifier: str,
    match_state: str,
    selector_expression: str,
    adaptive_relocated: bool,
    trained: bool,
    selections: Iterable[Any],
    base_url: str,
    errors: Iterable[str],
) -> dict[str, Any]:
    result_records = [
        _element_record(element, base_url=base_url, attribute_names=probe.attribute_names)
        for element in list(selections)[: max(1, probe.max_records)]
    ]
    return {
        "probe_id": probe.probe_id,
        "label": probe.label,
        "identifier": identifier,
        "selector_kind": probe.selector_kind,
        "selector_expression": selector_expression,
        "match_state": match_state,
        "adaptive_relocated": adaptive_relocated,
        "trained": trained,
        "record_count": len(result_records),
        "records": result_records,
        "probe_contract": asdict(probe),
        "parser_only_signal": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "failure_taxonomy": list(dict.fromkeys(errors)),
    }


def _element_record(element: Any, *, base_url: str, attribute_names: Iterable[str]) -> dict[str, Any]:
    text = _normalize_text(str(element.get_all_text(separator=" ", strip=True)))
    raw_attrs = getattr(element, "attrib", {}) or {}
    allowed_attribute_names = {str(name).lower() for name in attribute_names}
    attributes = {
        str(key): _normalize_text(str(value or ""))
        for key, value in dict(raw_attrs).items()
        if str(key).lower() in allowed_attribute_names and str(value or "").strip()
    }
    href = str(attributes.get("href") or "").strip()
    return {
        "tag": str(getattr(element, "tag", "") or ""),
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else "",
        "text_probe": text[:500],
        "attributes": attributes,
        "url_optional": urljoin(base_url, href).split("#", 1)[0] if href else "",
    }


def _adaptive_selector_summary(
    *,
    selected_probes: tuple[ScraplingAdaptiveSelectorProbe, ...],
    probe_records: list[Mapping[str, Any]],
    state: str,
) -> dict[str, Any]:
    selector_hit_count = sum(1 for record in probe_records if record.get("match_state") == "SELECTOR_HIT")
    adaptive_relocated_count = sum(1 for record in probe_records if record.get("match_state") == "ADAPTIVE_RELOCATED")
    not_found_count = sum(1 for record in probe_records if record.get("match_state") == "NOT_FOUND")
    trained_count = sum(1 for record in probe_records if record.get("trained"))
    record_total = sum(int(record.get("record_count") or 0) for record in probe_records)
    return {
        "summary_state": "ADAPTIVE_SELECTOR_SIGNALS_FOUND" if record_total else "NO_ADAPTIVE_SELECTOR_SIGNALS_FOUND",
        "registry_state": state,
        "probe_count": len(selected_probes),
        "selector_hit_probe_count": selector_hit_count,
        "adaptive_relocated_probe_count": adaptive_relocated_count,
        "not_found_probe_count": not_found_count,
        "trained_probe_count": trained_count,
        "record_total": record_total,
        "matched_probe_ids": [
            str(record.get("probe_id") or "")
            for record in probe_records
            if str(record.get("match_state") or "") in {"SELECTOR_HIT", "ADAPTIVE_RELOCATED"}
        ],
        "adaptive_relocated_probe_ids": [
            str(record.get("probe_id") or "")
            for record in probe_records
            if record.get("match_state") == "ADAPTIVE_RELOCATED"
        ],
    }


def _disabled_readback(
    *,
    body: str,
    base_url: str,
    selected_probes: tuple[ScraplingAdaptiveSelectorProbe, ...],
    state: str,
    failure_taxonomy: Iterable[str],
) -> dict[str, Any]:
    return {
        "parser_adapter_id": SCRAPLING_ADAPTIVE_SELECTOR_REGISTRY_ADAPTER_ID,
        "registry_state": state,
        "registry_mode": "DISABLED",
        "scrapling_available": False,
        "scrapling_missing": True,
        "no_live_request": True,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "base_url": base_url,
        "storage_scope_url": _adaptive_storage_scope_url(base_url),
        "storage_file": "",
        "source_html_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
        "adaptive_selector_summary": _adaptive_selector_summary(
            selected_probes=selected_probes,
            probe_records=[],
            state=state,
        ),
        "probe_records": [],
        "failure_taxonomy": list(dict.fromkeys(failure_taxonomy)),
    }


def _adaptive_storage_scope_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc.lower()}"
    return "local://stage2-snapshot"


def _close_scrapling_selector_storage(selector: Any | None) -> None:
    if selector is None:
        return
    storage = getattr(selector, "_storage", None)
    if storage is not None:
        try:
            storage.close()
        except Exception:
            pass
    try:
        from scrapling.core.storage import SQLiteStorageSystem  # type: ignore

        cache_clear = getattr(SQLiteStorageSystem, "cache_clear", None)
        if callable(cache_clear):
            cache_clear()
    except Exception:
        pass
