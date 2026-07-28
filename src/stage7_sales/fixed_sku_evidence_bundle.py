from __future__ import annotations

import hashlib
import html
import io
import json
import os
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from runtime.operational_observability import (
    get_operational_event_sink,
    record_operational_event_safely,
)
from stage7_sales.customer_delivery_boundary import (
    CONTRACT_REF as CUSTOMER_DELIVERY_BOUNDARY_CONTRACT_REF,
    assert_customer_delivery_payload_safe,
    customer_delivery_boundary,
    customer_delivery_disclaimer_texts,
    customer_safe_approval_audit,
    customer_safe_field_policy,
)


SKU_CODE = "SKU-B"
SKU_NAME = "单项目公开来源履约风险证据核验包"
SKU_VERSION = "1.0.0"
SKU_CONTRACT_REF = "contracts/sales/sku_b_evidence_pack_product_contract.json"
PACKAGE_SCHEMA_VERSION = "kaka_fixed_sku_evidence_bundle_v1"
WATERMARK_TEXT = "内部复核稿 - 人工签发前不得交付 / NOT CUSTOMER RELEASED"
PDF_FONT_NAME = "KakaCJK"
SUPPORTED_VERIFICATION_TYPES = (
    "施工许可",
    "竣工验收",
    "项目经理变更",
    "合同履约",
)
DISCLAIMER_ITEMS = customer_delivery_disclaimer_texts()


def build_fixed_sku_evidence_bundle(
    package: Mapping[str, Any],
    *,
    approval_audit: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    opportunity_id = _text(package.get("商机编号"))
    sink = get_operational_event_sink("api")
    try:
        bundle = _build_fixed_sku_evidence_bundle(
            package,
            approval_audit=approval_audit,
            generated_at=generated_at,
        )
    except Exception as exc:
        record_operational_event_safely(
            sink,
            component="delivery",
            operation="evidence_bundle_build",
            outcome="error",
            severity="ERROR",
            duration_ms=(time.perf_counter() - started) * 1000,
            trace_id=opportunity_id or None,
            error_category=type(exc).__name__,
        )
        raise
    issuance_control = _mapping(_mapping(bundle.get("manifest")).get("issuance_control"))
    signoff_state = _text(issuance_control.get("manual_signoff_state"))
    ready = signoff_state == "READY_FOR_HUMAN_SIGNOFF"
    record_operational_event_safely(
        sink,
        component="delivery",
        operation="evidence_bundle_build",
        outcome="success" if ready else "blocked",
        severity="INFO" if ready else "WARNING",
        duration_ms=(time.perf_counter() - started) * 1000,
        trace_id=opportunity_id or None,
        error_category=None if ready else "human_signoff_blocked",
        attributes={
            "sku_code": SKU_CODE,
            "manual_signoff_state": signoff_state,
            "external_delivery_executed": False,
            "missing_issuance_field_count": len(
                list(issuance_control.get("missing_issuance_fields") or [])
            ),
        },
    )
    return bundle


def _build_fixed_sku_evidence_bundle(
    package: Mapping[str, Any],
    *,
    approval_audit: Mapping[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    opportunity_id = _text(package.get("商机编号"))
    if not opportunity_id:
        raise ValueError("fixed SKU evidence bundle requires 商机编号")

    created_at = generated_at or datetime.now(timezone.utc).isoformat()
    source = _mapping(package.get("公开来源验证"))
    project_id = _text(package.get("项目编号") or source.get("项目编号"))
    boundary = _mapping(package.get("数据真实性边界"))
    package_meta = _mapping(package.get("证据包"))
    field_policy = customer_safe_field_policy(_mapping(package.get("字段策略")))
    approval_summary = customer_safe_approval_audit(approval_audit)
    delivery_boundary = customer_delivery_boundary()
    evidence_items = [_normalize_evidence_item(item, source) for item in _mapping_list(package.get("证据项清单"))]
    source_url = _text(source.get("公开来源网址"))
    source_query_time = _text(source.get("查询时点"))
    source_snapshot_sha256 = _text(source.get("快照SHA256") or source.get("快照哈希"))
    offline_sample = bool(boundary.get("是否离线样本"))
    approval_ready = bool(approval_audit.get("审批对象版本一致")) and bool(
        approval_audit.get("职责分离已满足")
    )
    validation_only_approval = bool(approval_audit.get("validation_only"))

    missing_issuance_fields: list[str] = []
    if not project_id:
        missing_issuance_fields.append("project_id")
    if not source_url:
        missing_issuance_fields.append("public_source_url")
    if not source_query_time:
        missing_issuance_fields.append("source_query_time")
    if not source_snapshot_sha256:
        missing_issuance_fields.append("source_snapshot_sha256")
    if offline_sample:
        missing_issuance_fields.append("real_public_source_required")
    if not evidence_items:
        missing_issuance_fields.append("evidence_items")
    covered_verification_types = {
        _text(item.get("evidence_type"))
        for item in evidence_items
        if _text(item.get("evidence_type")) in SUPPORTED_VERIFICATION_TYPES
    }
    missing_verification_types = [
        item for item in SUPPORTED_VERIFICATION_TYPES if item not in covered_verification_types
    ]
    missing_issuance_fields.extend(
        f"verification_type:{item}" for item in missing_verification_types
    )
    evidence_item_required_fields = (
        "verification_state",
        "evidence_grade",
        "source_url",
        "query_time",
        "snapshot_sha256",
        "blocking_reason",
        "next_step",
    )
    evidence_item_field_gaps = {
        _text(item.get("item_id")) or f"evidence_item_{index}": [
            field_name
            for field_name in evidence_item_required_fields
            if not _text(item.get(field_name))
        ]
        for index, item in enumerate(evidence_items, start=1)
        if _text(item.get("evidence_type")) in SUPPORTED_VERIFICATION_TYPES
    }
    evidence_item_field_gaps = {
        item_id: fields for item_id, fields in evidence_item_field_gaps.items() if fields
    }
    for item_id, fields in evidence_item_field_gaps.items():
        missing_issuance_fields.extend(f"evidence_item:{item_id}:{field_name}" for field_name in fields)
    if not _text(package_meta.get("版本哈希")):
        missing_issuance_fields.append("artifact_version_hash")
    if not approval_ready:
        missing_issuance_fields.append("object_approval_and_separation_of_duties")
    if validation_only_approval:
        missing_issuance_fields.append("production_object_approval_required")
    if not field_policy["allowlist_enforced"]:
        missing_issuance_fields.append("customer_field_allowlist_required")
    if not field_policy["masking_required"]:
        missing_issuance_fields.append("customer_field_masking_required")
    if field_policy["internal_blackbox_fields_exposed"]:
        missing_issuance_fields.append("internal_blackbox_fields_must_be_removed")

    signoff_state = (
        "READY_FOR_HUMAN_SIGNOFF"
        if not missing_issuance_fields
        else "BLOCKED_BEFORE_HUMAN_SIGNOFF"
    )
    manifest_core = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "sku": {
            "sku_code": SKU_CODE,
            "sku_name": SKU_NAME,
            "sku_version": SKU_VERSION,
            "contract_ref": SKU_CONTRACT_REF,
            "customer_delivery_boundary_contract_ref": CUSTOMER_DELIVERY_BOUNDARY_CONTRACT_REF,
            "verification_types": list(SUPPORTED_VERIFICATION_TYPES),
            "delivery_formats": ["PDF", "HTML", "JSON_MANIFEST", "ZIP"],
        },
        "project_id": project_id,
        "opportunity_id": opportunity_id,
        "generated_at": created_at,
        "artifact_ids": {
            "evidence_pack_id": package_meta.get("证据包编号"),
            "delivery_package_id": package_meta.get("交付包编号"),
            "artifact_manifest_id": package_meta.get("清单编号"),
            "upstream_artifact_version_hash": package_meta.get("版本哈希"),
        },
        "watermark": {
            "text": WATERMARK_TEXT,
            "applied_to": ["PDF", "HTML"],
            "removal_allowed": False,
        },
        "source_verification": {
            "source_url": source_url,
            "source_site_name": _text(source.get("公开来源名称")),
            "source_profile_id": _text(source.get("来源配置编号")),
            "project_name": _text(source.get("项目名称")),
            "region": _text(source.get("地区")),
            "project_type": _text(source.get("项目类型")),
            "verification_hint": _text(source.get("验证口径")),
            "query_time": _text(source.get("查询时点")) or created_at,
            "query_time_state": (
                "SOURCE_QUERY_TIME"
                if _text(source.get("查询时点"))
                else "PACKAGE_GENERATION_TIME_FALLBACK"
            ),
            "snapshot_sha256": source_snapshot_sha256,
        },
        "verification_coverage": {
            "required_types": list(SUPPORTED_VERIFICATION_TYPES),
            "covered_types": [item for item in SUPPORTED_VERIFICATION_TYPES if item in covered_verification_types],
            "missing_types": missing_verification_types,
            "item_required_field_gaps": evidence_item_field_gaps,
            "complete": not missing_verification_types and not evidence_item_field_gaps,
        },
        "evidence_items": evidence_items,
        "data_boundary": _safe_data_boundary(boundary),
        "customer_delivery_boundary": delivery_boundary,
        "disclaimers": list(DISCLAIMER_ITEMS),
        "issuance_control": {
            "bundle_state": "INTERNAL_REVIEW_BUNDLE_READY",
            "manual_signoff_state": signoff_state,
            "manual_signoff_required": True,
            "manual_signoff_present": False,
            "customer_release_authorized": False,
            "external_delivery_executed": False,
            "customer_self_service_download_enabled": False,
            "missing_issuance_fields": missing_issuance_fields,
        },
        "delivery_audit": {
            "delivery_mode": delivery_boundary["delivery_mode"],
            "approval_audit": approval_summary,
            "recipient": None,
            "delivery_channel": None,
            "delivered_at": None,
            "external_delivery_executed": False,
            "operator_must_record_recipient_channel_and_time_after_manual_handoff": True,
        },
        "field_policy": field_policy,
    }

    assert_customer_delivery_payload_safe(manifest_core)

    html_bytes = _render_html(manifest_core).encode("utf-8")
    pdf_bytes = _render_pdf(manifest_core)
    manifest = {
        **manifest_core,
        "file_hashes": {
            "evidence-pack.html": _sha256(html_bytes),
            "evidence-pack.pdf": _sha256(pdf_bytes),
        },
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    readme_bytes = _render_readme(manifest).encode("utf-8")
    zip_bytes = _build_zip(
        {
            "evidence-pack.pdf": pdf_bytes,
            "evidence-pack.html": html_bytes,
            "manifest.json": manifest_bytes,
            "README.txt": readme_bytes,
        }
    )
    return {
        "filename": f"{SKU_CODE.lower()}-evidence-pack-{_safe_token(opportunity_id)}.zip",
        "media_type": "application/zip",
        "bytes": zip_bytes,
        "bundle_sha256": _sha256(zip_bytes),
        "manifest": manifest,
        "pdf_bytes": pdf_bytes,
        "html_bytes": html_bytes,
    }


def _normalize_evidence_item(item: Mapping[str, Any], source: Mapping[str, Any]) -> dict[str, Any]:
    grade = _text(item.get("证据等级") or item.get("下游证据等级") or item.get("证据级别"))
    state = _text(item.get("核验状态") or item.get("清单状态"))
    return {
        "item_id": _text(item.get("证据项编号")),
        "evidence_type": _text(item.get("证据类型")),
        "clue_type": _text(item.get("线索类型")),
        "evidence_grade": grade,
        "verification_state": state,
        "description": _text(item.get("证据说明")),
        "customer_delivery_boundary": _text(item.get("客户交付判断")),
        "blocking_reason": _text(item.get("阻断原因")),
        "next_step": _text(item.get("下一步")),
        "source_url": _text(item.get("公开来源网址")) or _text(source.get("公开来源网址")),
        "source_site_name": _text(item.get("公开来源名称")) or _text(source.get("公开来源名称")),
        "source_profile_id": _text(item.get("来源配置编号")) or _text(source.get("来源配置编号")),
        "snapshot_sha256": _text(item.get("快照SHA256") or item.get("快照哈希")),
        "query_time": _text(item.get("查询时点")) or _text(source.get("查询时点")),
        "source_refs": _safe_string_list(item.get("来源引用")),
        "masking_policy": _text(item.get("脱敏策略")),
    }


def _render_html(manifest: Mapping[str, Any]) -> str:
    sku = _mapping(manifest.get("sku"))
    source = _mapping(manifest.get("source_verification"))
    control = _mapping(manifest.get("issuance_control"))
    delivery_boundary = _mapping(manifest.get("customer_delivery_boundary"))
    evidence_rows = "".join(
        "<tr>"
        f"<td>{_h(item.get('evidence_type') or item.get('item_id'))}</td>"
        f"<td>{_h(item.get('verification_state'))}</td>"
        f"<td>{_h(item.get('evidence_grade'))}</td>"
        f"<td>{_h(item.get('blocking_reason'))}</td>"
        f"<td>{_h(item.get('next_step'))}</td>"
        f"<td><a href=\"{_ha(item.get('source_url'))}\">{_h(item.get('source_site_name') or item.get('source_url'))}</a></td>"
        "</tr>"
        for item in _mapping_list(manifest.get("evidence_items"))
    ) or '<tr><td colspan="6">暂无证据项，禁止人工签发。</td></tr>'
    disclaimers = "".join(f"<li>{_h(item)}</li>" for item in manifest.get("disclaimers") or [])
    gaps = "、".join(_issuance_gap_label(item) for item in control.get("missing_issuance_fields") or []) or "无"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_h(sku.get('sku_name'))}</title>
<style>
body{{font-family:"Microsoft YaHei","Noto Sans CJK SC",sans-serif;margin:0;color:#17312d;background:#f3f6f4;line-height:1.65}}
main{{max-width:980px;margin:32px auto;background:#fff;padding:48px;box-shadow:0 10px 35px #17312d22}}
.watermark{{border:2px solid #c2410c;color:#9a3412;background:#fff7ed;padding:10px 16px;font-weight:700;text-align:center}}
h1{{font-size:30px;margin:24px 0 6px}} h2{{font-size:20px;border-bottom:2px solid #0f766e;padding-bottom:6px;margin-top:34px}}
.meta{{color:#52706a}} .state{{display:inline-block;padding:4px 10px;background:#e7f5f1;border-radius:999px;font-weight:700}}
table{{width:100%;border-collapse:collapse}} th,td{{border:1px solid #cbd8d4;padding:10px;text-align:left;vertical-align:top}} th{{background:#e7f5f1}}
a{{color:#0f766e;word-break:break-all}} footer{{margin-top:40px;border-top:1px solid #cbd8d4;padding-top:14px;color:#667b77;font-size:13px}}
a:focus-visible{{outline:3px solid #0f766e;outline-offset:3px}}
@media (max-width:680px){{main{{margin:0;padding:24px 18px}}h1{{font-size:25px}}table{{display:block;overflow-x:auto}}}}
</style></head><body><main>
<div class="watermark">{_h(WATERMARK_TEXT)}</div>
<h1>{_h(sku.get('sku_name'))}</h1>
<p class="meta">产品 {_h(sku.get('sku_code'))} · 版本 {_h(sku.get('sku_version'))} · 商机 {_h(manifest.get('opportunity_id'))}</p>
<p><span class="state">{_h(_signoff_state_label(control.get('manual_signoff_state')))}</span></p>
<h2>项目与来源</h2>
<p><strong>项目：</strong>{_h(source.get('project_name') or '未提供')}</p>
<p><strong>地区 / 类型：</strong>{_h(source.get('region') or '未提供')} / {_h(source.get('project_type') or '未提供')}</p>
<p><strong>公开来源：</strong><a href="{_ha(source.get('source_url'))}">{_h(source.get('source_url') or '缺失')}</a></p>
<p><strong>查询时点：</strong>{_h(source.get('query_time'))} ({_h(_query_time_state_label(source.get('query_time_state')))})</p>
<p><strong>快照 SHA-256：</strong>{_h(source.get('snapshot_sha256') or '未固定')}</p>
<h2>四类核验范围</h2><p>{_h('、'.join(sku.get('verification_types') or []))}</p>
<h2>证据项</h2><table><thead><tr><th>类型</th><th>状态</th><th>等级</th><th>阻断原因</th><th>下一步</th><th>来源</th></tr></thead><tbody>{evidence_rows}</tbody></table>
<h2>人工签发门禁</h2><p>缺失项：{_h(gaps)}</p><p>本包未执行客户外发，客户自助下载未开放。人工签发人必须复核来源、证据等级、限制声明并另行记录接收方、交付渠道和交付时间。</p>
<h2>客户交付与责任边界</h2><p>{_h(delivery_boundary.get('current_delivery_statement'))}</p><ol>{disclaimers}</ol>
<footer>版本清单与文件 SHA-256 见 manifest.json。本页无脚本、无外部资源；不得移除水印或把内部复核稿冒充已签发报告。</footer>
</main></body></html>"""


def _render_pdf(manifest: Mapping[str, Any]) -> bytes:
    _register_pdf_font()
    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=22 * mm,
        bottomMargin=20 * mm,
        title=SKU_NAME,
        author="Kaka",
        subject="SKU-B evidence pack internal review bundle",
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "KakaTitle",
        parent=styles["Title"],
        fontName=PDF_FONT_NAME,
        fontSize=22,
        leading=30,
        textColor=colors.HexColor("#17312d"),
        alignment=TA_LEFT,
        spaceAfter=8,
    )
    heading = ParagraphStyle(
        "KakaHeading",
        parent=styles["Heading2"],
        fontName=PDF_FONT_NAME,
        fontSize=14,
        leading=20,
        textColor=colors.HexColor("#0f766e"),
        spaceBefore=13,
        spaceAfter=7,
    )
    body = ParagraphStyle(
        "KakaBody",
        parent=styles["BodyText"],
        fontName=PDF_FONT_NAME,
        fontSize=9.5,
        leading=15,
        wordWrap="CJK",
        spaceAfter=5,
    )
    small = ParagraphStyle(
        "KakaSmall",
        parent=body,
        fontSize=8,
        leading=12,
        textColor=colors.HexColor("#526b66"),
    )
    center = ParagraphStyle("KakaCenter", parent=body, alignment=TA_CENTER, textColor=colors.HexColor("#9a3412"))
    sku = _mapping(manifest.get("sku"))
    source = _mapping(manifest.get("source_verification"))
    control = _mapping(manifest.get("issuance_control"))
    delivery_boundary = _mapping(manifest.get("customer_delivery_boundary"))
    story: list[Any] = [
        Paragraph(_p(WATERMARK_TEXT), center),
        Spacer(1, 5 * mm),
        Paragraph(_p(sku.get("sku_name")), title),
        Paragraph(
            _p(f"产品 {sku.get('sku_code')} · 版本 {sku.get('sku_version')} · 商机 {manifest.get('opportunity_id')}"),
            small,
        ),
        Paragraph(_p(f"签发状态：{_signoff_state_label(control.get('manual_signoff_state'))}"), body),
        Paragraph("项目与来源", heading),
    ]
    summary_rows = [
        ["项目", source.get("project_name") or "未提供"],
        ["地区 / 类型", f"{source.get('region') or '未提供'} / {source.get('project_type') or '未提供'}"],
        ["公开来源", source.get("source_url") or "缺失"],
        ["查询时点", f"{source.get('query_time') or ''} ({_query_time_state_label(source.get('query_time_state'))})"],
        ["快照 SHA-256", source.get("snapshot_sha256") or "未固定"],
    ]
    table = Table(
        [[Paragraph(_p(left), body), Paragraph(_p(right), body)] for left, right in summary_rows],
        colWidths=[34 * mm, 132 * mm],
        repeatRows=0,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#e7f5f1")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#b8c9c4")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend(
        [
            table,
            Paragraph("四类核验范围", heading),
            Paragraph(_p("、".join(sku.get("verification_types") or [])), body),
            Paragraph("证据项", heading),
        ]
    )
    evidence_items = _mapping_list(manifest.get("evidence_items"))
    if not evidence_items:
        story.append(Paragraph("暂无证据项，禁止人工签发。", body))
    for index, item in enumerate(evidence_items, start=1):
        story.append(
            KeepTogether(
                [
                Paragraph(_p(f"{index}. {item.get('evidence_type') or item.get('item_id') or '证据项'}"), body),
                Paragraph(
                    _p(
                        f"状态：{item.get('verification_state') or '缺失'} · 证据等级：{item.get('evidence_grade') or '缺失'}"
                    ),
                    small,
                ),
                Paragraph(_p(f"来源：{item.get('source_url') or '缺失'}"), small),
                Paragraph(_p(f"阻断原因：{item.get('blocking_reason') or '缺失'}"), small),
                Paragraph(_p(f"下一步：{item.get('next_step') or '缺失'}"), small),
                ]
            )
        )
    gaps = "、".join(_issuance_gap_label(item) for item in control.get("missing_issuance_fields") or []) or "无"
    story.extend(
        [
            Paragraph("人工签发门禁", heading),
            Paragraph(_p(f"缺失项：{gaps}"), body),
            Paragraph(
                "本包未执行客户外发，客户自助下载未开放。人工签发人必须复核来源、证据等级、限制声明，并另行记录接收方、交付渠道和交付时间。",
                body,
            ),
            Paragraph("客户交付与责任边界", heading),
            Paragraph(_p(delivery_boundary.get("current_delivery_statement")), body),
        ]
    )
    for index, item in enumerate(manifest.get("disclaimers") or [], start=1):
        story.append(Paragraph(_p(f"{index}. {item}"), body))

    def decorate(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(PDF_FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#667b77"))
        canvas.drawString(18 * mm, 10 * mm, f"{SKU_CODE} · {SKU_VERSION} · {manifest.get('opportunity_id')}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"第 {doc.page} 页")
        canvas.setFillColor(colors.Color(0.76, 0.26, 0.05, alpha=0.08))
        canvas.setFont(PDF_FONT_NAME, 22)
        canvas.translate(A4[0] / 2, A4[1] / 2)
        canvas.rotate(32)
        canvas.drawCentredString(0, 0, "内部复核稿 - 未签发")
        canvas.restoreState()

    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _register_pdf_font() -> None:
    if PDF_FONT_NAME in pdfmetrics.getRegisteredFontNames():
        return
    configured = str(os.environ.get("KAKA_EVIDENCE_PDF_FONT_FILE") or "").strip()
    candidates = [
        configured,
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    ]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        pdfmetrics.registerFont(TTFont(PDF_FONT_NAME, candidate, subfontIndex=0))
        return
    raise RuntimeError(
        "CJK PDF font missing; install fonts-noto-cjk or set KAKA_EVIDENCE_PDF_FONT_FILE"
    )


def _render_readme(manifest: Mapping[str, Any]) -> str:
    control = _mapping(manifest.get("issuance_control"))
    lines = [
            f"{SKU_CODE} {SKU_NAME}",
            f"版本: {SKU_VERSION}",
            f"商机: {manifest.get('opportunity_id')}",
            f"人工签发状态: {_signoff_state_label(control.get('manual_signoff_state'))}",
            "",
            "本 ZIP 是内部复核包，不代表已经交付客户。",
            "人工签发前必须核对 PDF、HTML、manifest.json 的来源、证据等级、限制声明和 SHA-256。",
            "签发后必须另行记录接收方、交付渠道、交付时间和签发人；系统当前不会自动邮件发送或开放客户自助下载。",
            "",
            "客户交付与责任边界:",
    ]
    lines.extend(
        f"{index}. {item}"
        for index, item in enumerate(manifest.get("disclaimers") or [], start=1)
    )
    lines.append("")
    return "\n".join(lines)


def _build_zip(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _signoff_state_label(value: Any) -> str:
    return {
        "READY_FOR_HUMAN_SIGNOFF": "已具备人工签发复核条件",
        "BLOCKED_BEFORE_HUMAN_SIGNOFF": "人工签发前仍有阻断",
    }.get(_text(value), _text(value) or "状态未知")


def _query_time_state_label(value: Any) -> str:
    return {
        "SOURCE_QUERY_TIME": "来源查询时点",
        "PACKAGE_GENERATION_TIME_FALLBACK": "使用包生成时点补位，签发前需补真实查询时点",
    }.get(_text(value), _text(value) or "时点性质未知")


def _issuance_gap_label(value: Any) -> str:
    text = _text(value)
    labels = {
        "public_source_url": "缺公开来源网址",
        "source_query_time": "缺真实查询时点",
        "source_snapshot_sha256": "缺来源快照 SHA-256",
        "real_public_source_required": "仅离线样本，需真实公开来源",
        "evidence_items": "缺证据项",
        "artifact_version_hash": "缺版本哈希",
        "object_approval_and_separation_of_duties": "缺逐对象审批或职责分离",
        "production_object_approval_required": "当前仅视觉验收，缺正式逐对象审批",
    }
    if text.startswith("verification_type:"):
        return f"缺核验类型：{text.split(':', 1)[1]}"
    return labels.get(text, text)


def _safe_token(value: str) -> str:
    token = "".join(char if char.isascii() and (char.isalnum() or char in "-_") else "-" for char in value)
    return "-".join(part for part in token.split("-") if part) or "opportunity"


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    return [dict(item) for item in value or [] if isinstance(item, Mapping)]


def _safe_data_boundary(value: Mapping[str, Any]) -> dict[str, Any]:
    allowed = (
        "数据模式",
        "来源候选模式",
        "是否离线样本",
        "是否真实市场发现",
        "客户可交付判断",
        "来源网址精度",
        "证据包用途",
        "客户可见导出已开放",
        "真实外发已开放",
    )
    return {key: value.get(key) for key in allowed if key in value}


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()]


def _text(value: Any) -> str:
    return str(value or "").strip()


def _h(value: Any) -> str:
    return html.escape(_text(value), quote=False)


def _ha(value: Any) -> str:
    return html.escape(_text(value), quote=True)


def _p(value: Any) -> str:
    return html.escape(_text(value), quote=True)


__all__ = [
    "PACKAGE_SCHEMA_VERSION",
    "SKU_CODE",
    "SKU_CONTRACT_REF",
    "SKU_NAME",
    "SKU_VERSION",
    "build_fixed_sku_evidence_bundle",
]
