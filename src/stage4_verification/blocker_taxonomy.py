from __future__ import annotations

from typing import Any, Mapping


CLASSIFIER_ID = "stage4-verification-blocker-taxonomy-v1"

MATCHED = "MATCHED"
NOT_FOUND = "NOT_FOUND"
BLOCKED = "BLOCKED"
NEEDS_BROWSER = "NEEDS_BROWSER"
REVIEW_REQUIRED = "REVIEW_REQUIRED"
LOGIN_OR_SSO_REQUIRED = "LOGIN_OR_SSO_REQUIRED"

_NOT_FOUND_STATUSES = {
    "EMPTY",
    "EMPTY_RESULT",
    "NO_HIT",
    "NO_MATCH",
    "NO_RECORD",
    "NO_RESULT",
    "NOT_FOUND",
    "ZERO_RESULT",
}
_NEEDS_BROWSER_STATUSES = {
    "BROWSER_REQUIRED",
    "DYNAMIC_RENDER_REQUIRED",
    "NEEDS_BROWSER",
}
_LOGIN_STATUSES = {
    "LOGIN_OR_SSO_REQUIRED",
    "LOGIN_REQUIRED",
    "SSO_REQUIRED",
}
_BLOCKED_STATUSES = {
    "BLOCK",
    "BLOCKED",
    "CAPTCHA",
    "RATE_LIMITED",
    "SOURCE_BLOCKED",
    "SOURCE_UNAVAILABLE",
}


def classify_stage4_probe_result(probe_result: Mapping[str, Any]) -> dict[str, Any]:
    probe = dict(probe_result)
    status = _status(probe)
    field_match_state = _upper_text(probe.get("field_match_state"))

    if status in _LOGIN_STATUSES:
        return _outcome(
            probe,
            verification_state=BLOCKED,
            run_state=BLOCKED,
            blocker_ids=["login_or_sso_required"],
            blocking_reasons=_blocking_reasons(probe, "login_or_sso_required"),
            authorization_readiness_state=LOGIN_OR_SSO_REQUIRED,
            operator_next_action="OPERATOR_LOGIN_OR_SSO_CAPTURE_REQUIRED",
            readback_required=True,
        )

    if status in _NEEDS_BROWSER_STATUSES:
        return _outcome(
            probe,
            verification_state=NEEDS_BROWSER,
            run_state=BLOCKED,
            blocker_ids=["needs_browser"],
            blocking_reasons=_blocking_reasons(probe, "needs_browser"),
            operator_next_action="RUN_BROWSER_WORKER_OR_OPERATOR_CAPTURE",
            readback_required=True,
        )

    if status in _BLOCKED_STATUSES:
        return _outcome(
            probe,
            verification_state=BLOCKED,
            run_state=BLOCKED,
            blocker_ids=["source_blocked"],
            blocking_reasons=_blocking_reasons(probe, "source_blocked"),
            operator_next_action="RETRY_OR_ROUTE_TO_OPERATOR_SOURCE_DIAGNOSTIC",
            readback_required=True,
        )

    if status in _NOT_FOUND_STATUSES or _looks_like_empty_success(probe, status):
        return _outcome(
            probe,
            verification_state=NOT_FOUND,
            run_state=REVIEW_REQUIRED,
            blocker_ids=["source_not_found_not_clearance"],
            blocking_reasons=_blocking_reasons(probe, "source_not_found_not_clearance"),
            operator_next_action="REVIEW_SOURCE_SCOPE_OR_QUERY_TERMS",
            readback_required=True,
        )

    if status == MATCHED or field_match_state == MATCHED:
        if _has_replayable_ref(probe):
            return _outcome(
                probe,
                verification_state=MATCHED,
                run_state="READY",
                blocker_ids=[],
                blocking_reasons=[],
                operator_next_action="NONE",
                readback_required=False,
            )
        return _outcome(
            probe,
            verification_state=REVIEW_REQUIRED,
            run_state=REVIEW_REQUIRED,
            blocker_ids=["matched_without_replayable_readback"],
            blocking_reasons=_blocking_reasons(probe, "matched_without_replayable_readback"),
            operator_next_action="ATTACH_REPLAYABLE_READBACK_BEFORE_RULE_USE",
            readback_required=True,
        )

    return _outcome(
        probe,
        verification_state=REVIEW_REQUIRED,
        run_state=REVIEW_REQUIRED,
        blocker_ids=["stage4_probe_requires_review"],
        blocking_reasons=_blocking_reasons(probe, "stage4_probe_requires_review"),
        operator_next_action="REVIEW_STAGE4_PROBE_RESULT",
        readback_required=True,
    )


def _outcome(
    probe: Mapping[str, Any],
    *,
    verification_state: str,
    run_state: str,
    blocker_ids: list[str],
    blocking_reasons: list[str],
    operator_next_action: str,
    readback_required: bool,
    authorization_readiness_state: str = "",
) -> dict[str, Any]:
    return {
        "classifier_id": CLASSIFIER_ID,
        "stage_id": "stage4_verification",
        "verification_state": verification_state,
        "run_state": run_state,
        "blocker_ids": _unique(blocker_ids),
        "blocking_reasons": _unique(blocking_reasons),
        "authorization_readiness_state": authorization_readiness_state,
        "operator_next_action": operator_next_action,
        "query_miss_is_not_clearance": True,
        "clearance_allowed": False,
        "legal_conclusion_allowed": False,
        "customer_visible_allowed": False,
        "no_legal_conclusion": True,
        "readback_required": readback_required,
        "verification_target_type": _text(probe.get("verification_target_type")),
        "source_url": _text(probe.get("source_url")),
        "source_snapshot_id": _text(probe.get("source_snapshot_id")),
        "snapshot_hash": _text(probe.get("snapshot_hash")),
        "evidence_refs": _evidence_refs(probe),
    }


def _status(probe: Mapping[str, Any]) -> str:
    for key in (
        "probe_status",
        "verification_state",
        "source_access_state",
        "query_state",
        "status",
    ):
        value = _upper_text(probe.get(key))
        if value:
            return value
    return ""


def _looks_like_empty_success(probe: Mapping[str, Any], status: str) -> bool:
    records = probe.get("records")
    if records not in (None, "") and not _as_list(records):
        return status in {"", "OK", "SUCCESS", "QUERY_OK"}
    return bool(probe.get("query_executed")) and status in {"", "OK", "SUCCESS", "QUERY_OK"}


def _has_replayable_ref(probe: Mapping[str, Any]) -> bool:
    if _as_list(probe.get("readback_refs")):
        return True
    return bool(_text(probe.get("source_snapshot_id")) and _text(probe.get("snapshot_hash")))


def _blocking_reasons(probe: Mapping[str, Any], default_reason: str) -> list[str]:
    reasons = _as_list(probe.get("blocking_reasons"))
    single = probe.get("blocking_reason")
    if single not in (None, "", [], {}):
        reasons.append(single)
    if not reasons:
        reasons.append(default_reason)
    return [str(reason) for reason in reasons if reason not in (None, "", [], {})]


def _evidence_refs(probe: Mapping[str, Any]) -> list[str]:
    refs: list[Any] = []
    refs.extend(_as_list(probe.get("readback_refs")))
    for key in ("readback_id", "verification_run_id", "source_snapshot_id", "snapshot_hash", "source_url"):
        value = probe.get(key)
        if value not in (None, "", [], {}):
            refs.append(value)
    return _unique([str(ref) for ref in refs if ref not in (None, "", [], {})])


def _upper_text(value: Any) -> str:
    return _text(value).upper()


def _text(value: Any) -> str:
    if value in (None, [], {}):
        return ""
    return str(value).strip()


def _as_list(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


__all__ = [
    "BLOCKED",
    "CLASSIFIER_ID",
    "LOGIN_OR_SSO_REQUIRED",
    "MATCHED",
    "NEEDS_BROWSER",
    "NOT_FOUND",
    "REVIEW_REQUIRED",
    "classify_stage4_probe_result",
]
