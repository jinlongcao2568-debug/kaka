# Stage: stage4_verification
# Internal PDF visual forensics for bid document review.

from __future__ import annotations

import hashlib
import json
import math
import re
from concurrent.futures import ProcessPoolExecutor, as_completed
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import fitz  # type: ignore
import numpy as np
from PIL import Image

try:
    from scipy import ndimage as ndi  # type: ignore
    from scipy.fftpack import dct as scipy_dct  # type: ignore
except Exception:  # pragma: no cover - dependency availability is environment-specific
    ndi = None  # type: ignore
    scipy_dct = None  # type: ignore


IMAGE_HEAVY_BID_FILE = "IMAGE_HEAVY_BID_FILE"
MIXED_TEXT_IMAGE_BID_FILE = "MIXED_TEXT_IMAGE_BID_FILE"
TEXT_LAYER_PRESENT = "TEXT_LAYER_PRESENT"
OBSERVED_REPEATED_STAMP_IMAGE = "OBSERVED_REPEATED_STAMP_IMAGE"
STAMP_CANDIDATES_REVIEW_REQUIRED = "STAMP_CANDIDATES_REVIEW_REQUIRED"
NO_STAMP_CANDIDATE_DETECTED = "NO_STAMP_CANDIDATE_DETECTED"
OCR_REQUIRED_FOR_CONTENT_SIMILARITY = "OCR_REQUIRED_FOR_CONTENT_SIMILARITY"
NOT_ENOUGH_EVIDENCE = "NOT_ENOUGH_EVIDENCE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

FORBIDDEN_MARKDOWN_TERMS = ("造假", "违法", "围标", "废标")


@dataclass(frozen=True)
class BidPdfTarget:
    company: str
    path: Path
    rank_role: str = "other_bidder"


def analyze_bid_pdf_targets(
    targets: Iterable[BidPdfTarget],
    *,
    assets_dir: str | Path,
    qualification_summary_path: str | Path | None = None,
    max_pages: int = 0,
    render_dpi: int = 72,
    asset_dpi: int = 120,
    ocr_sample_pages: int = 3,
    workers: int = 1,
    visual_max_pages_per_pdf: int = 0,
) -> dict[str, Any]:
    assets_root = Path(assets_dir)
    assets_root.mkdir(parents=True, exist_ok=True)
    qualification_by_company = _load_qualification_summary(qualification_summary_path)
    target_list = list(targets)
    records: list[dict[str, Any]] = []
    all_stamp_candidates: list[dict[str, Any]] = []
    page_hash_records: list[dict[str, Any]] = []
    if workers > 1 and len(target_list) > 1:
        indexed_records: dict[int, dict[str, Any]] = {}
        with ProcessPoolExecutor(max_workers=max(1, workers)) as executor:
            future_map = {
                executor.submit(
                    analyze_single_bid_pdf,
                    target,
                    assets_dir=assets_root,
                    max_pages=max_pages,
                    render_dpi=render_dpi,
                    asset_dpi=asset_dpi,
                    ocr_sample_pages=ocr_sample_pages,
                    visual_max_pages=visual_max_pages_per_pdf,
                ): index
                for index, target in enumerate(target_list)
            }
            for future in as_completed(future_map):
                indexed_records[future_map[future]] = future.result()
        records = [indexed_records[index] for index in range(len(target_list))]
    else:
        for target in target_list:
            records.append(
                analyze_single_bid_pdf(
                    target,
                    assets_dir=assets_root,
                    max_pages=max_pages,
                    render_dpi=render_dpi,
                    asset_dpi=asset_dpi,
                    ocr_sample_pages=ocr_sample_pages,
                    visual_max_pages=visual_max_pages_per_pdf,
                )
            )
    for record in records:
        target_company = str(record.get("company") or "")
        qualification = qualification_by_company.get(target_company, {})
        if qualification:
            record["project_manager_qualification_readback"] = {
                "jzsc_verification_state": qualification.get("jzsc_verification_state", ""),
                "stage5_qualification_overall_status": qualification.get(
                    "stage5_qualification_overall_status", ""
                ),
                "announcement_certificate_no": qualification.get(
                    "announcement_certificate_no", ""
                ),
                "responsible_person": qualification.get("responsible_person", ""),
            }
        all_stamp_candidates.extend(record.get("stamp_candidates", []))
        page_hash_records.extend(record.get("page_hash_records", []))

    stamp_clusters = cluster_stamp_candidates(all_stamp_candidates)
    _apply_stamp_cluster_results(records, stamp_clusters, assets_root)
    pairwise_similarity = compute_pairwise_similarity(records, page_hash_records)
    summary = {
        "forensics_version": "jg2026-11125-bid-pdf-forensics-v1",
        "record_count": len(records),
        "records": records,
        "stamp_cluster_count": len(stamp_clusters),
        "repeated_stamp_cluster_count": sum(
            1 for cluster in stamp_clusters if len(cluster.get("candidate_ids", [])) >= 2
        ),
        "stamp_clusters": stamp_clusters,
        "pairwise_similarity": pairwise_similarity,
        "status_counts": dict(
            Counter(status for record in records for status in record.get("forensic_statuses", []))
        ),
        "qualification_summary_path": str(qualification_summary_path or ""),
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }
    return summary


def analyze_single_bid_pdf(
    target: BidPdfTarget,
    *,
    assets_dir: Path,
    max_pages: int = 0,
    render_dpi: int = 72,
    asset_dpi: int = 120,
    ocr_sample_pages: int = 3,
    visual_max_pages: int = 0,
) -> dict[str, Any]:
    path = target.path
    base_record: dict[str, Any] = {
        "company": target.company,
        "rank_role": target.rank_role,
        "document_path": str(path),
        "document_exists": path.exists(),
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }
    if not path.exists():
        return {
            **base_record,
            "failure_reasons": ["pdf_path_missing"],
            "forensic_statuses": [REVIEW_REQUIRED],
        }

    data = path.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    render_failure_pages: list[int] = []
    text_lengths: list[int] = []
    image_counts: list[int] = []
    drawing_counts: list[int] = []
    page_hash_records: list[dict[str, Any]] = []
    stamp_candidates: list[dict[str, Any]] = []
    page_texts: list[str] = []
    ocr_samples: list[dict[str, Any]] = []
    doc_asset_dir = assets_dir / _safe_name(target.company)
    doc_asset_dir.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(path)) as doc:
        page_count = int(doc.page_count or 0)
        effective_pages = min(page_count, max_pages) if max_pages and max_pages > 0 else page_count
        visual_limit = (
            min(effective_pages, visual_max_pages)
            if visual_max_pages and visual_max_pages > 0
            else effective_pages
        )
        low_text_pages_for_ocr: list[int] = []
        for zero_index in range(effective_pages):
            page_no = zero_index + 1
            try:
                page = doc.load_page(zero_index)
                text = str(page.get_text("text") or "").strip()
                text_lengths.append(len(text))
                page_texts.append(text)
                if len(text) <= 30:
                    low_text_pages_for_ocr.append(page_no)
                images = page.get_images(full=True)
                image_counts.append(len(images))
                # Vector drawing extraction is expensive on these large public PDFs and is
                # not required for the current visual-review acceptance criteria.
                drawing_counts.append(0)
                if page_no <= visual_limit:
                    image = render_page_to_image(page, dpi=render_dpi)
                    page_hash = visual_hashes(image)
                    page_hash_records.append(
                        {
                            "company": target.company,
                            "page_no": page_no,
                            "dhash": page_hash["dhash"],
                            "phash": page_hash["phash"],
                        }
                    )
                    for candidate in detect_red_stamp_candidates(
                        image,
                        page_no=page_no,
                        company=target.company,
                        max_candidates=8,
                    ):
                        candidate_id = _stable_id(
                            "STAMP",
                            target.company,
                            page_no,
                            candidate.get("bbox"),
                            candidate.get("dhash"),
                            candidate.get("phash"),
                        )
                        candidate["candidate_id"] = candidate_id
                        stamp_candidates.append(candidate)
            except Exception as exc:
                render_failure_pages.append(page_no)

        for page_no in low_text_pages_for_ocr[: max(0, ocr_sample_pages)]:
            sample = ocr_page_sample(doc, page_no=page_no, dpi=asset_dpi)
            ocr_samples.append(sample)

        sample_pages = _select_sample_pages(
            page_count=effective_pages,
            text_lengths=text_lengths,
            stamp_candidates=stamp_candidates,
        )
        sample_assets = save_sample_page_assets(
            doc,
            company=target.company,
            page_numbers=sample_pages,
            output_dir=doc_asset_dir,
            dpi=asset_dpi,
        )

    text_layer_page_count = sum(1 for value in text_lengths if value > 30)
    low_text_page_count = sum(1 for value in text_lengths if value <= 30)
    image_heavy_state = classify_image_heavy_bid_file(
        page_count=len(text_lengths),
        text_layer_page_count=text_layer_page_count,
        pages_with_images=sum(1 for value in image_counts if value > 0),
        text_chars_total=sum(text_lengths),
    )
    ocr_text = "\n".join(
        sample.get("text", "") for sample in ocr_samples if str(sample.get("text", "")).strip()
    )
    content_similarity_state = (
        OCR_REQUIRED_FOR_CONTENT_SIMILARITY
        if sum(text_lengths) < 1500 and not ocr_text.strip()
        else "CONTENT_TEXT_AVAILABLE_FOR_SIMILARITY"
    )
    statuses = [image_heavy_state]
    if stamp_candidates:
        statuses.append(STAMP_CANDIDATES_REVIEW_REQUIRED)
    else:
        statuses.append(NO_STAMP_CANDIDATE_DETECTED)
    if content_similarity_state == OCR_REQUIRED_FOR_CONTENT_SIMILARITY:
        statuses.append(content_similarity_state)
    normalized_text = normalize_content_text("\n".join(page_texts + [ocr_text]))
    return {
        **base_record,
        "file_size_bytes": len(data),
        "sha256": sha256,
        "page_count": len(text_lengths),
        "original_page_count": page_count,
        "max_pages_applied": max_pages if max_pages else 0,
        "visual_scan_page_count": min(len(text_lengths), visual_max_pages)
        if visual_max_pages and visual_max_pages > 0
        else len(text_lengths),
        "visual_scan_policy": (
            f"first_{visual_max_pages}_pages_per_pdf"
            if visual_max_pages and visual_max_pages > 0
            else "all_pages"
        ),
        "text_layer_page_count": text_layer_page_count,
        "low_text_page_count": low_text_page_count,
        "text_chars_total": sum(text_lengths),
        "image_objects_total": sum(image_counts),
        "pages_with_images": sum(1 for value in image_counts if value > 0),
        "drawings_total": sum(drawing_counts),
        "image_heavy_ratio": round(low_text_page_count / max(1, len(text_lengths)), 4),
        "image_heavy_state": image_heavy_state,
        "render_failure_pages": render_failure_pages,
        "stamp_candidate_count": len(stamp_candidates),
        "pages_with_stamp_candidates": sorted(
            {int(candidate.get("page_no") or 0) for candidate in stamp_candidates}
        ),
        "stamp_candidates": stamp_candidates,
        "stamp_repeated_candidate_count": 0,
        "stamp_repeated_cluster_ids": [],
        "ocr_samples": ocr_samples,
        "content_similarity_state": content_similarity_state,
        "normalized_text_length": len(normalized_text),
        "text_shingles": sorted(text_shingles(normalized_text))[:5000],
        "chapter_headings": extract_chapter_headings("\n".join(page_texts + [ocr_text])),
        "page_hash_records": page_hash_records,
        "sample_assets": sample_assets,
        "forensic_statuses": list(dict.fromkeys(statuses)),
        "official_check_recommendations": build_pdf_forensic_recommendations(
            image_heavy_state=image_heavy_state,
            stamp_candidate_count=len(stamp_candidates),
            content_similarity_state=content_similarity_state,
        ),
        "failure_reasons": [],
    }


def render_page_to_image(page: Any, *, dpi: int) -> Image.Image:
    scale = max(0.5, dpi / 72)
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)


def detect_red_stamp_candidates(
    image: Image.Image,
    *,
    page_no: int = 1,
    company: str = "",
    max_candidates: int = 8,
) -> list[dict[str, Any]]:
    rgb = np.array(image.convert("RGB"))
    height, width = rgb.shape[:2]
    hsv = np.array(image.convert("HSV"))
    hue = hsv[:, :, 0].astype(np.int16)
    sat = hsv[:, :, 1].astype(np.int16)
    val = hsv[:, :, 2].astype(np.int16)
    # PIL hue is 0-255. These ranges correspond approximately to low/high red.
    mask = (((hue <= 18) | (hue >= 235)) & (sat >= 55) & (val >= 45))
    if ndi is not None:
        mask = ndi.binary_closing(mask, structure=np.ones((3, 3), dtype=bool), iterations=1)
        labels, label_count = ndi.label(mask)
        objects = ndi.find_objects(labels)
    else:  # pragma: no cover - scipy is available in the target workspace
        labels, objects, label_count = _label_mask_fallback(mask)
    candidates: list[dict[str, Any]] = []
    page_area = max(1, width * height)
    for label_index, slices in enumerate(objects, start=1):
        if slices is None:
            continue
        y_slice, x_slice = slices
        y, x = int(y_slice.start), int(x_slice.start)
        h, w = int(y_slice.stop - y_slice.start), int(x_slice.stop - x_slice.start)
        component = labels[y_slice, x_slice] == label_index
        red_pixels = int(np.count_nonzero(component))
        area = float(red_pixels)
        if area < max(80, page_area * 0.00012) or area > page_area * 0.09:
            continue
        if w < 18 or h < 18:
            continue
        aspect = w / max(1, h)
        if aspect < 0.45 or aspect > 2.2:
            continue
        bbox_area = w * h
        red_ratio = red_pixels / max(1, bbox_area)
        if red_ratio < 0.035:
            continue
        compactness = red_ratio
        if compactness < 0.06 and max(w, h) < 45:
            continue
        pad = max(4, int(max(w, h) * 0.08))
        x0, y0 = max(0, x - pad), max(0, y - pad)
        x1, y1 = min(width, x + w + pad), min(height, y + h + pad)
        crop = image.crop((x0, y0, x1, y1))
        hashes = visual_hashes(crop)
        candidates.append(
            {
                "company": company,
                "page_no": page_no,
                "bbox": [int(x0), int(y0), int(x1), int(y1)],
                "width": int(x1 - x0),
                "height": int(y1 - y0),
                "area": round(area, 2),
                "red_ratio": round(red_ratio, 4),
                "compactness": round(compactness, 4),
                "dhash": hashes["dhash"],
                "phash": hashes["phash"],
            }
        )
    candidates.sort(key=lambda item: (item.get("red_ratio", 0), item.get("area", 0)), reverse=True)
    return candidates[:max_candidates]


def visual_hashes(image: Image.Image) -> dict[str, str]:
    return {
        "dhash": dhash(image),
        "phash": phash(image),
    }


def dhash(image: Image.Image, hash_size: int = 8) -> str:
    gray = image.convert("L").resize((hash_size + 1, hash_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.int16)
    diff = pixels[:, 1:] > pixels[:, :-1]
    return _bits_to_hex(diff.flatten())


def phash(image: Image.Image, hash_size: int = 8, highfreq_factor: int = 4) -> str:
    img_size = hash_size * highfreq_factor
    gray = image.convert("L").resize((img_size, img_size), Image.Resampling.LANCZOS)
    pixels = np.asarray(gray, dtype=np.float32)
    dct = _dct2(pixels)
    low = dct[:hash_size, :hash_size]
    median = float(np.median(low[1:, 1:]))
    diff = low > median
    return _bits_to_hex(diff.flatten())


def hamming_hex(left: str, right: str) -> int:
    try:
        value = int(left, 16) ^ int(right, 16)
    except ValueError:
        return 9999
    return int(value.bit_count())


def cluster_stamp_candidates(candidates: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    clusters: list[dict[str, Any]] = []
    for candidate in candidates:
        matched: dict[str, Any] | None = None
        for cluster in clusters:
            rep = cluster["representative"]
            if (
                hamming_hex(str(candidate.get("dhash", "")), str(rep.get("dhash", ""))) <= 8
                and hamming_hex(str(candidate.get("phash", "")), str(rep.get("phash", ""))) <= 12
            ):
                matched = cluster
                break
        payload = dict(candidate)
        if matched is None:
            clusters.append(
                {
                    "cluster_id": f"STAMP-CLUSTER-{len(clusters) + 1:04d}",
                    "representative": payload,
                    "candidate_ids": [payload.get("candidate_id", "")],
                    "companies": [payload.get("company", "")],
                    "pages": [payload.get("page_no", 0)],
                    "candidates": [payload],
                }
            )
        else:
            matched["candidate_ids"].append(payload.get("candidate_id", ""))
            matched["companies"] = sorted(set([*matched.get("companies", []), payload.get("company", "")]))
            matched["pages"].append(payload.get("page_no", 0))
            matched["candidates"].append(payload)
    clusters = [cluster for cluster in clusters if len(cluster.get("candidate_ids", [])) >= 2]
    for cluster in clusters:
        companies = sorted(set(str(item.get("company", "")) for item in cluster.get("candidates", [])))
        cluster["candidate_count"] = len(cluster.get("candidate_ids", []))
        cluster["cross_company"] = len([company for company in companies if company]) > 1
        cluster["companies"] = companies
        cluster["sample_candidates"] = list(cluster.get("candidates", []))[:8]
        cluster.pop("candidates", None)
    clusters.sort(key=lambda item: (item.get("candidate_count", 0), item.get("cross_company", False)), reverse=True)
    return clusters


def classify_image_heavy_bid_file(
    *,
    page_count: int,
    text_layer_page_count: int,
    pages_with_images: int,
    text_chars_total: int,
) -> str:
    if page_count <= 0:
        return NOT_ENOUGH_EVIDENCE
    low_text_ratio = 1 - text_layer_page_count / max(1, page_count)
    image_page_ratio = pages_with_images / max(1, page_count)
    avg_text = text_chars_total / max(1, page_count)
    if low_text_ratio >= 0.80 and image_page_ratio >= 0.65:
        return IMAGE_HEAVY_BID_FILE
    if avg_text < 120 and image_page_ratio >= 0.45:
        return IMAGE_HEAVY_BID_FILE
    if low_text_ratio >= 0.35 or image_page_ratio >= 0.35:
        return MIXED_TEXT_IMAGE_BID_FILE
    return TEXT_LAYER_PRESENT


def compute_pairwise_similarity(
    records: list[Mapping[str, Any]],
    page_hash_records: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_company_hashes: dict[str, set[str]] = defaultdict(set)
    for item in page_hash_records:
        company = str(item.get("company") or "")
        key = str(item.get("dhash") or "")
        if company and key:
            by_company_hashes[company].add(key)
    by_company_text = {
        str(record.get("company")): set(record.get("text_shingles") or [])
        for record in records
    }
    output: list[dict[str, Any]] = []
    for left_index, left in enumerate(records):
        for right in records[left_index + 1 :]:
            left_company = str(left.get("company") or "")
            right_company = str(right.get("company") or "")
            left_text = by_company_text.get(left_company, set())
            right_text = by_company_text.get(right_company, set())
            text_jaccard = _jaccard(left_text, right_text)
            left_hashes = by_company_hashes.get(left_company, set())
            right_hashes = by_company_hashes.get(right_company, set())
            shared_page_hashes = left_hashes & right_hashes
            output.append(
                {
                    "left_company": left_company,
                    "right_company": right_company,
                    "text_shingle_jaccard": round(text_jaccard, 4),
                    "shared_page_visual_hash_count": len(shared_page_hashes),
                    "similarity_review_state": (
                        REVIEW_REQUIRED
                        if text_jaccard >= 0.35 or len(shared_page_hashes) >= 3
                        else NOT_ENOUGH_EVIDENCE
                    ),
                }
            )
    output.sort(
        key=lambda item: (
            item.get("similarity_review_state") == REVIEW_REQUIRED,
            item.get("text_shingle_jaccard", 0),
            item.get("shared_page_visual_hash_count", 0),
        ),
        reverse=True,
    )
    return output


def write_forensics_outputs(
    summary: Mapping[str, Any],
    *,
    output_jsonl: str | Path,
    output_json: str | Path,
    output_markdown: str | Path,
) -> None:
    jsonl_path = Path(output_jsonl)
    json_path = Path(output_json)
    markdown_path = Path(output_markdown)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    records = list(summary.get("records") or [])
    jsonl_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown = build_forensics_markdown(summary)
    markdown_path.write_text(markdown, encoding="utf-8")


def build_forensics_markdown(summary: Mapping[str, Any]) -> str:
    lines: list[str] = []
    records = list(summary.get("records") or [])
    lines.append("# JG2026-11125 投标 PDF 内部视觉复核表")
    lines.append("")
    lines.append("- 用途：内部复核和后续人工核查。")
    lines.append("- 边界：仅记录公开文件的视觉和结构异常线索，不作法律定性或处理结论。")
    lines.append("- 说明：页数、文本层和图片对象为全页统计；红色图块为低 DPI 视觉扫描结果，具体扫描页数见表。")
    lines.append("")
    lines.append("| 序号 | 投标单位 | 页数 | 视觉页 | 图片化状态 | 文本页/低文本页 | 印章候选 | 重复印章候选 | 资格核验 | 人工复核建议 |")
    lines.append("| --- | --- | ---: | ---: | --- | ---: | ---: | ---: | --- | --- |")
    for index, record in enumerate(records, start=1):
        qualification = dict(record.get("project_manager_qualification_readback") or {})
        advice = "；".join(str(item) for item in list(record.get("official_check_recommendations") or []))
        lines.append(
            "| "
            + " | ".join(
                [
                    str(index),
                    _md(record.get("company")),
                    _md(record.get("page_count")),
                    _md(record.get("visual_scan_page_count")),
                    _md(record.get("image_heavy_state")),
                    _md(
                        f"{record.get('text_layer_page_count', 0)}/{record.get('low_text_page_count', 0)}"
                    ),
                    _md(record.get("stamp_candidate_count")),
                    _md(record.get("stamp_repeated_candidate_count")),
                    _md(qualification.get("stage5_qualification_overall_status", "")),
                    _md(advice),
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append("## 状态统计")
    lines.append("")
    for key, value in sorted(dict(summary.get("status_counts") or {}).items()):
        lines.append(f"- {_md(key)}：{value}")
    lines.append("")
    lines.append("## 重复印章图像簇")
    lines.append("")
    clusters = list(summary.get("stamp_clusters") or [])
    if not clusters:
        lines.append("- 未形成重复图像簇。")
    for cluster in clusters[:20]:
        lines.append(
            f"- {cluster.get('cluster_id')}：候选 {cluster.get('candidate_count')} 个，"
            f"跨单位 {cluster.get('cross_company')}，单位：{_md('、'.join(cluster.get('companies') or []))}"
        )
    lines.append("")
    lines.append("## 标书相似度最高组合")
    lines.append("")
    for item in list(summary.get("pairwise_similarity") or [])[:15]:
        lines.append(
            f"- {_md(item.get('left_company'))} / {_md(item.get('right_company'))}："
            f"文本相似 {item.get('text_shingle_jaccard')}，共享页面哈希 {item.get('shared_page_visual_hash_count')}，"
            f"状态 {item.get('similarity_review_state')}"
        )
    markdown = "\n".join(lines) + "\n"
    for term in FORBIDDEN_MARKDOWN_TERMS:
        markdown = markdown.replace(term, "**")
    return markdown


def build_pdf_forensic_recommendations(
    *,
    image_heavy_state: str,
    stamp_candidate_count: int,
    content_similarity_state: str,
) -> list[str]:
    recommendations: list[str] = []
    if image_heavy_state == IMAGE_HEAVY_BID_FILE:
        recommendations.append("建议人工复核该投标文件是否以扫描图片为主，并核查可回链原始 PDF。")
    if stamp_candidate_count > 0:
        recommendations.append("建议人工查看疑似红色印章图块、页码和坐标，区分 CA 签章外观与扫描公章图像。")
    if content_similarity_state == OCR_REQUIRED_FOR_CONTENT_SIMILARITY:
        recommendations.append("建议对低文本页面抽样 OCR 后再做内容相似度复核。")
    if not recommendations:
        recommendations.append("未形成足够视觉异常线索，保留人工抽样复核。")
    return recommendations


def ocr_page_sample(doc: Any, *, page_no: int, dpi: int) -> dict[str, Any]:
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        return {
            "page_no": page_no,
            "ocr_state": f"OCR_ENGINE_UNAVAILABLE:{type(exc).__name__}",
            "text": "",
        }
    try:
        page = doc.load_page(page_no - 1)
        image = render_page_to_image(page, dpi=dpi)
        try:
            text = pytesseract.image_to_string(image, lang="chi_sim+eng").strip()
            engine = "pytesseract:chi_sim+eng"
        except Exception:
            text = pytesseract.image_to_string(image, lang="eng").strip()
            engine = "pytesseract:eng"
        return {
            "page_no": page_no,
            "ocr_state": "OCR_TEXT_EXTRACTED" if text else "OCR_TEXT_EMPTY",
            "extractor": engine,
            "text": text[:2000],
        }
    except Exception as exc:
        return {
            "page_no": page_no,
            "ocr_state": f"OCR_EXTRACT_FAILED:{type(exc).__name__}",
            "text": "",
        }


def save_sample_page_assets(
    doc: Any,
    *,
    company: str,
    page_numbers: list[int],
    output_dir: Path,
    dpi: int,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    for page_no in page_numbers[:8]:
        try:
            page = doc.load_page(page_no - 1)
            image = render_page_to_image(page, dpi=dpi)
            path = output_dir / f"page_{page_no:04d}.png"
            image.save(path)
            assets.append({"company": company, "page_no": page_no, "path": str(path)})
        except Exception as exc:
            assets.append({"company": company, "page_no": page_no, "error": type(exc).__name__})
    return assets


def normalize_content_text(text: str) -> str:
    value = re.sub(r"\s+", "", str(text or ""))
    value = re.sub(r"[^\w\u4e00-\u9fff]", "", value)
    return value


def text_shingles(text: str, *, size: int = 5) -> set[str]:
    normalized = normalize_content_text(text)
    if len(normalized) < size:
        return set()
    return {normalized[index : index + size] for index in range(0, len(normalized) - size + 1)}


def extract_chapter_headings(text: str) -> list[str]:
    headings: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = " ".join(raw_line.split()).strip()
        if not line or len(line) > 80:
            continue
        if re.search(r"^(第[一二三四五六七八九十\d]+[章节篇部分])|目录|投标函|授权|承诺|施工组织|资格|项目管理", line):
            headings.append(line)
    return list(dict.fromkeys(headings))[:80]


def _apply_stamp_cluster_results(
    records: list[dict[str, Any]],
    clusters: list[Mapping[str, Any]],
    assets_root: Path,
) -> None:
    repeated_ids: dict[str, list[str]] = defaultdict(list)
    for cluster in clusters:
        cluster_id = str(cluster.get("cluster_id") or "")
        for candidate_id in list(cluster.get("candidate_ids") or []):
            repeated_ids[str(candidate_id)].append(cluster_id)
    for record in records:
        record_clusters = sorted(
            {
                cluster_id
                for candidate in list(record.get("stamp_candidates") or [])
                for cluster_id in repeated_ids.get(str(candidate.get("candidate_id") or ""), [])
            }
        )
        repeated_count = sum(
            1
            for candidate in list(record.get("stamp_candidates") or [])
            if repeated_ids.get(str(candidate.get("candidate_id") or ""))
        )
        record["stamp_repeated_candidate_count"] = repeated_count
        record["stamp_repeated_cluster_ids"] = record_clusters
        if repeated_count:
            statuses = list(record.get("forensic_statuses") or [])
            statuses.append(OBSERVED_REPEATED_STAMP_IMAGE)
            record["forensic_statuses"] = list(dict.fromkeys(statuses))
    _save_repeated_stamp_assets(records, clusters, assets_root)


def _save_repeated_stamp_assets(
    records: list[Mapping[str, Any]],
    clusters: list[Mapping[str, Any]],
    assets_root: Path,
) -> None:
    if not clusters:
        return
    by_company_path = {str(record.get("company")): Path(str(record.get("document_path"))) for record in records}
    saved = 0
    for cluster in clusters[:30]:
        cluster_dir = assets_root / "repeated_stamp_clusters" / str(cluster.get("cluster_id"))
        cluster_dir.mkdir(parents=True, exist_ok=True)
        for candidate in list(cluster.get("sample_candidates") or [])[:6]:
            company = str(candidate.get("company") or "")
            path = by_company_path.get(company)
            if not path or not path.exists():
                continue
            try:
                with fitz.open(str(path)) as doc:
                    page = doc.load_page(int(candidate.get("page_no") or 1) - 1)
                    image = render_page_to_image(page, dpi=120)
                    scale = 120 / 72
                    x0, y0, x1, y1 = [int(float(value) * scale) for value in candidate.get("bbox", [0, 0, 0, 0])]
                    crop = image.crop((max(0, x0), max(0, y0), min(image.width, x1), min(image.height, y1)))
                    out = cluster_dir / f"{_safe_name(company)}_p{int(candidate.get('page_no') or 0):04d}_{saved:04d}.png"
                    crop.save(out)
                    saved += 1
            except Exception:
                continue


def _select_sample_pages(
    *,
    page_count: int,
    text_lengths: list[int],
    stamp_candidates: list[Mapping[str, Any]],
) -> list[int]:
    pages = {1, page_count} if page_count else set()
    pages.update(int(candidate.get("page_no") or 0) for candidate in stamp_candidates[:5])
    for index, length in enumerate(text_lengths[:50], start=1):
        if length <= 30:
            pages.add(index)
        if len(pages) >= 8:
            break
    return sorted(page for page in pages if 1 <= page <= page_count)[:8]


def _load_qualification_summary(path: str | Path | None) -> dict[str, dict[str, Any]]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return {
        str(record.get("company") or ""): dict(record)
        for record in list(payload.get("records") or [])
        if str(record.get("company") or "")
    }


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:20]


def _stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}-{_sha1_text(json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str))}"


def _bits_to_hex(bits: Iterable[Any]) -> str:
    bit_string = "".join("1" if bool(bit) else "0" for bit in bits)
    width = max(1, (len(bit_string) + 3) // 4)
    return f"{int(bit_string or '0', 2):0{width}x}"


def _dct2(values: np.ndarray) -> np.ndarray:
    if scipy_dct is None:  # pragma: no cover - scipy is available in the target workspace
        return np.real(np.fft.fft2(values))
    return scipy_dct(scipy_dct(values, axis=0, norm="ortho"), axis=1, norm="ortho")


def _label_mask_fallback(mask: np.ndarray) -> tuple[np.ndarray, list[Any], int]:
    labels = np.zeros(mask.shape, dtype=np.int32)
    objects: list[Any] = []
    label = 0
    height, width = mask.shape
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or labels[y, x]:
                continue
            label += 1
            stack = [(y, x)]
            labels[y, x] = label
            min_y = max_y = y
            min_x = max_x = x
            while stack:
                cy, cx = stack.pop()
                min_y, max_y = min(min_y, cy), max(max_y, cy)
                min_x, max_x = min(min_x, cx), max(max_x, cx)
                for ny in range(max(0, cy - 1), min(height, cy + 2)):
                    for nx in range(max(0, cx - 1), min(width, cx + 2)):
                        if mask[ny, nx] and not labels[ny, nx]:
                            labels[ny, nx] = label
                            stack.append((ny, nx))
            objects.append((slice(min_y, max_y + 1), slice(min_x, max_x + 1)))
    return labels, objects, label


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(1, len(left | right))


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", str(value or "").strip())
    return cleaned[:80] or "unknown"


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("|", "\\|").replace("\n", "<br>")
