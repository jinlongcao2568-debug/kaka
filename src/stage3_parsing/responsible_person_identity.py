from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any


CRITICAL_IDENTITY_REVIEW_THRESHOLD = 0.75

_PLACEHOLDER_VALUES = {
    "",
    "/",
    "／",
    "-",
    "--",
    "无",
    "暂无",
    "未填",
    "空",
    "不适用",
    "详见附件",
    "详见附表",
    "详见投标文件",
    "详见投标文件公开",
    "按招标人规定",
    "按招标文件要求",
    "按合同约定",
}

_NON_PERSON_EXACT_VALUES = {
    "达到",
    "满足",
    "符合",
    "响应",
    "承诺",
    "通过",
    "不通过",
    "公开",
    "单元",
    "合格",
    "不合格",
    "项目负责人",
    "负责人",
    "项目经理",
    "总监",
    "总监理",
    "总监理工程师",
    "工程师",
    "候选人",
}

_NON_PERSON_FRAGMENTS = (
    "达到国家",
    "达到标准",
    "满足要求",
    "符合要求",
    "响应招标",
    "质量目标",
    "质量标准",
    "项目负责",
    "候选",
    "公示",
    "公告",
    "投标",
    "招标",
    "评标",
    "报价",
    "证书",
    "资质",
    "资格",
    "业绩",
    "注册",
    "建造师",
    "工程师",
    "详见",
    "附件",
    "附表",
    "合同约定",
    "文件要求",
    "国家标准",
    "行业甲级",
    "建筑工程",
    "施工总承包",
)


@dataclass(frozen=True)
class ResponsiblePersonIdentityQuality:
    normalized_value: str
    accepted: bool
    quality_state: str
    reject_reason: str
    confidence: float | None
    review_required: bool
    review_reasons: tuple[str, ...]

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["review_reasons"] = list(self.review_reasons)
        return payload


def assess_responsible_person_name(
    value: Any,
    *,
    confidence: float | None = None,
) -> ResponsiblePersonIdentityQuality:
    normalized = _normalize(value)
    compact = normalized.replace(" ", "")
    normalized_confidence = _confidence(confidence)

    if compact in {_normalize(item).replace(" ", "") for item in _PLACEHOLDER_VALUES}:
        return _rejected(
            compact,
            confidence=normalized_confidence,
            quality_state="REJECTED_PLACEHOLDER_PERSON_VALUE",
            reject_reason="responsible_person_value_is_placeholder",
        )
    if compact in _NON_PERSON_EXACT_VALUES:
        return _rejected(
            compact,
            confidence=normalized_confidence,
            quality_state="REJECTED_NON_PERSON_TOKEN",
            reject_reason="stage3_non_person_token_must_not_be_used_as_responsible_person",
        )
    if not re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", compact):
        return _rejected(
            compact,
            confidence=normalized_confidence,
            quality_state="REJECTED_PERSON_NAME_SHAPE",
            reject_reason="responsible_person_name_shape_invalid",
        )
    if any(fragment in compact for fragment in _NON_PERSON_FRAGMENTS):
        return _rejected(
            compact,
            confidence=normalized_confidence,
            quality_state="REJECTED_NON_PERSON_PHRASE",
            reject_reason="responsible_person_name_contains_business_phrase",
        )

    review_reasons: list[str] = []
    if normalized_confidence is None:
        review_reasons.append("critical_identity_confidence_missing")
    elif normalized_confidence < CRITICAL_IDENTITY_REVIEW_THRESHOLD:
        review_reasons.append("critical_identity_confidence_below_review_threshold")
    return ResponsiblePersonIdentityQuality(
        normalized_value=compact,
        accepted=True,
        quality_state="ACCEPTED_PERSON_NAME_SHAPE",
        reject_reason="",
        confidence=normalized_confidence,
        review_required=bool(review_reasons),
        review_reasons=tuple(review_reasons),
    )


def _rejected(
    value: str,
    *,
    confidence: float | None,
    quality_state: str,
    reject_reason: str,
) -> ResponsiblePersonIdentityQuality:
    return ResponsiblePersonIdentityQuality(
        normalized_value=value,
        accepted=False,
        quality_state=quality_state,
        reject_reason=reject_reason,
        confidence=confidence,
        review_required=True,
        review_reasons=(reject_reason,),
    )


def _confidence(value: float | None) -> float | None:
    if value is None:
        return None
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return None


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split()).strip(" ：:，,；;。|｜")


__all__ = [
    "CRITICAL_IDENTITY_REVIEW_THRESHOLD",
    "ResponsiblePersonIdentityQuality",
    "assess_responsible_person_name",
]
