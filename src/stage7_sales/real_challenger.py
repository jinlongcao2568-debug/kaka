from __future__ import annotations

from typing import Any, Mapping

from shared.utils import build_id, ensure_list


CONTACTABILITY_FIELDS = (
    "contact_validity_status",
    "contact_legal_basis",
    "reasonable_expectation_status",
    "channel_policy_status",
    "frequency_policy_state",
    "opt_out_state",
    "quiet_hours_policy_state",
)

CONTACTABILITY_BLOCK_VALUES = {
    "BLOCK",
    "BLOCKED",
    "INVALID",
    "UNREASONABLE",
    "OPTED_OUT",
}

CONTACTABILITY_HARD_BLOCK_VALUES_BY_FIELD = {
    "contact_validity_status": {"BLOCK", "BLOCKED", "INVALID"},
    "contact_legal_basis": {"BLOCK", "BLOCKED"},
    "reasonable_expectation_status": {"BLOCK", "BLOCKED", "UNREASONABLE"},
    "opt_out_state": {"BLOCK", "BLOCKED", "OPTED_OUT"},
}

CONTACTABILITY_STAGE8_SCHEDULE_VALUES_BY_FIELD = {
    "channel_policy_status": {"BLOCK", "UNAVAILABLE"},
    "frequency_policy_state": {"BLOCK"},
    "quiet_hours_policy_state": {"BLOCK"},
}

CONTACTABILITY_REVIEW_VALUES = {
    "",
    "UNKNOWN",
    "REVIEW",
    "REVIEW_REQUIRED",
    "PENDING_CONFIRMATION",
}

READY_CONTACTABILITY = {
    "contact_validity_status": {"VALID"},
    "contact_legal_basis": {"PUBLIC_ROLE_CONTACT", "CUSTOMER_AUTHORIZED_CONTACT"},
    "reasonable_expectation_status": {"REASONABLE"},
    "channel_policy_status": {"ALLOW"},
    "frequency_policy_state": {"ALLOW"},
    "opt_out_state": {"ACTIVE", "NOT_OPTED_OUT"},
    "quiet_hours_policy_state": {"ALLOW"},
}

SUPPORTED_CANDIDATE_SOURCE_TYPES = {
    "second_rank",
    "third_rank",
    "rejected_bidder",
    "historical_competitor",
    "regional_active_company",
}

SOURCE_TYPE_ALIASES = {
    "SECOND": "second_rank",
    "SECOND_RANK": "second_rank",
    "SECOND_CANDIDATE": "second_rank",
    "THIRD": "third_rank",
    "THIRD_RANK": "third_rank",
    "THIRD_CANDIDATE": "third_rank",
    "REJECTED": "rejected_bidder",
    "REJECTED_BIDDER": "rejected_bidder",
    "HISTORICAL": "historical_competitor",
    "HISTORICAL_COMPETITOR": "historical_competitor",
    "REGIONAL": "regional_active_company",
    "REGIONAL_ACTIVE": "regional_active_company",
    "REGIONAL_ACTIVE_COMPANY": "regional_active_company",
}


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _bounded_score(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    return max(0, min(100, round(float(value))))


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in (None, ""):
            continue
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _raw_candidate_lookup(inputs: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    raw_pool = inputs.get("multi_competitor_candidate_pool", [])
    if not isinstance(raw_pool, list):
        return lookup
    for raw in raw_pool:
        if not isinstance(raw, Mapping):
            continue
        raw_dict = dict(raw)
        for key in (
            raw_dict.get("candidate_id"),
            raw_dict.get("challenger_profile_id"),
            raw_dict.get("challenger_bidder_id"),
            raw_dict.get("bidder_id"),
        ):
            if key not in (None, ""):
                lookup[str(key)] = raw_dict
    return lookup


def _raw_for_candidate(
    candidate: Mapping[str, Any],
    lookup: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    for key in (
        candidate.get("candidate_id"),
        candidate.get("challenger_profile_id"),
        candidate.get("challenger_bidder_id"),
    ):
        if key not in (None, "") and str(key) in lookup:
            return dict(lookup[str(key)])
    return {}


def _candidate_source_type(candidate: Mapping[str, Any], raw: Mapping[str, Any]) -> str:
    explicit = (
        _optional_str(raw.get("candidate_source_type"))
        or _optional_str(raw.get("candidate_relationship_type"))
        or _optional_str(raw.get("relationship_type"))
        or _optional_str(raw.get("candidate_source"))
    )
    if explicit:
        normalized = explicit.strip().upper().replace("-", "_")
        if normalized in SOURCE_TYPE_ALIASES:
            return SOURCE_TYPE_ALIASES[normalized]
        lowered = explicit.strip().lower()
        if lowered in SUPPORTED_CANDIDATE_SOURCE_TYPES:
            return lowered

    position = str(candidate.get("candidate_position_label", "")).upper()
    if position in SOURCE_TYPE_ALIASES:
        return SOURCE_TYPE_ALIASES[position]
    if position == "WINNER":
        return "winning_competitor"
    if position == "FIRST_CANDIDATE":
        return "first_rank"
    return "stage6_challenger_profile" if candidate.get("candidate_source") == "STAGE6_CHALLENGER_PROFILE" else "other_candidate"


def _subject_eligibility(
    *,
    candidate: Mapping[str, Any],
    raw: Mapping[str, Any],
    sale_gate_status: str,
    report_status: str,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    explicit = _optional_str(
        raw.get("subject_eligibility_state")
        or raw.get("subject_eligibility_status")
        or raw.get("standing_state")
    )
    if sale_gate_status == "BLOCK":
        return "BLOCK", [f"upstream_closed:sale_gate_status={sale_gate_status};report_status={report_status}"]
    if report_status != "ISSUED":
        return "REVIEW", [f"upstream_report_status={report_status}"]
    if explicit:
        normalized = explicit.upper()
        if normalized in {"BLOCK", "BLOCKED", "INELIGIBLE", "NO_SUBJECT", "NOT_ELIGIBLE"}:
            return "BLOCK", [f"subject_eligibility_state={explicit}"]
        if normalized in {"REVIEW", "REVIEW_REQUIRED", "UNKNOWN", "MISSING", "UNVERIFIED"}:
            return "REVIEW", [f"subject_eligibility_state={explicit}"]
        if normalized in {"ELIGIBLE", "HAS_STANDING", "QUALIFIED"}:
            return "ELIGIBLE", []
    if not candidate.get("challenger_profile_id") or not candidate.get("challenger_bidder_id"):
        reasons.append("missing_challenger_identity")
        return "REVIEW", reasons
    return "ELIGIBLE", []


def _contactability(
    *,
    raw: Mapping[str, Any],
    inputs: Mapping[str, Any],
) -> tuple[str, dict[str, str], list[str]]:
    snapshot = {
        field_name: str(raw.get(field_name, inputs.get(field_name, "")) or "")
        for field_name in CONTACTABILITY_FIELDS
    }
    reasons: list[str] = []
    for field_name, value in snapshot.items():
        normalized = value.upper()
        if normalized in CONTACTABILITY_STAGE8_SCHEDULE_VALUES_BY_FIELD.get(field_name, set()):
            continue
        if normalized in CONTACTABILITY_HARD_BLOCK_VALUES_BY_FIELD.get(field_name, CONTACTABILITY_BLOCK_VALUES):
            reasons.append(f"{field_name}={value}")
        elif normalized in CONTACTABILITY_REVIEW_VALUES:
            reasons.append(f"{field_name}={value or 'MISSING'}")
        elif value not in READY_CONTACTABILITY.get(field_name, {value}):
            reasons.append(f"{field_name}={value}")

    if any(
        str(snapshot[field]).upper() in CONTACTABILITY_HARD_BLOCK_VALUES_BY_FIELD.get(field, set())
        for field in CONTACTABILITY_FIELDS
    ):
        return "BLOCK", snapshot, reasons
    if reasons:
        return "REVIEW", snapshot, reasons
    return "INTERNAL_READY", snapshot, []


def _purchase_capacity(
    *,
    raw: Mapping[str, Any],
    runtime_capacity_score: int,
) -> tuple[int, list[str]]:
    if "purchase_capacity_score" in raw and raw.get("purchase_capacity_score") in (None, ""):
        return 0, ["purchase_capacity_score=MISSING"]
    if "payment_capacity_score" in raw and raw.get("payment_capacity_score") in (None, ""):
        return 0, ["payment_capacity_score=MISSING"]
    score = _bounded_score(
        raw.get("purchase_capacity_score", raw.get("payment_capacity_score", runtime_capacity_score)),
        default=runtime_capacity_score,
    )
    reasons: list[str] = []
    if score < 35:
        reasons.append(f"purchase_capacity_score_lt_35:{score}")
    return score, reasons


def _sales_priority(
    *,
    subject_state: str,
    contactability_status: str,
    buyer_fit_score: int,
    challenge_motivation_score: int,
    purchase_capacity_score: int,
    ranking_score: int,
) -> tuple[str, int]:
    priority_score = round(
        buyer_fit_score * 0.35
        + challenge_motivation_score * 0.25
        + purchase_capacity_score * 0.20
        + ranking_score * 0.20
    )
    if subject_state == "BLOCK" or contactability_status == "BLOCK":
        return "BLOCK", priority_score
    if subject_state == "REVIEW" or contactability_status == "REVIEW":
        return "REVIEW", priority_score
    if priority_score >= 82:
        return "P1", priority_score
    if priority_score >= 68:
        return "P2", priority_score
    return "P3", priority_score


def build_real_challenger_readback(
    *,
    project_id: str,
    inputs: Mapping[str, Any],
    runtime_state: Any,
    multi_competitor_candidates: list[Any],
    top_n_competitor_ids: list[Any],
    winning_competitor_candidate: Mapping[str, Any],
    competitor_selection_trace: Mapping[str, Any],
    competitor_trace_summary: Mapping[str, Any],
    sale_gate_status: str,
    saleability_status_seed: str,
    report_status: str,
    review_task_status: str,
    action_family: str,
    linked_review_request_id_optional: str | None,
    missing_condition_family_optional: str | None,
    offer_recommendation_id: str,
) -> dict[str, Any]:
    raw_lookup = _raw_candidate_lookup(inputs)
    selected_candidate_id = str(winning_competitor_candidate.get("candidate_id"))
    candidate_only_ids = {
        str(candidate_id)
        for candidate_id in ensure_list(competitor_trace_summary.get("candidate_only_candidate_ids"))
    }
    top_n_ids = [str(candidate_id) for candidate_id in top_n_competitor_ids]
    runtime_capacity_score = _bounded_score(runtime_state.resolve("buyer_fit_payment_capacity_score"), default=50)
    selected_buyer_fit_score = _bounded_score(
        runtime_state.resolve(
            "challenger_buyer_fit_scorecard_score",
            runtime_state.resolve("buyer_fit_scorecard_score"),
        ),
        default=50,
    )
    sku_code = _optional_str(runtime_state.resolve("sku_code", inputs.get("sku_code"))) or "SKU-C"
    service_tier_code = _optional_str(runtime_state.resolve("service_tier_code"))
    package_template_code = (
        _optional_str(runtime_state.resolve("package_template_code"))
        or _optional_str(runtime_state.resolve("recommended_delivery_form", inputs.get("recommended_delivery_form")))
    )
    recommended_delivery_form = (
        _optional_str(runtime_state.resolve("recommended_delivery_form", inputs.get("recommended_delivery_form")))
        or package_template_code
        or "PROJECT_BRIEF"
    )
    recommended_quote_band = _optional_str(runtime_state.resolve("recommended_quote_band")) or "CUSTOM"
    offer_state = _optional_str(runtime_state.resolve("offer_recommendation_state")) or "DRAFT"
    recommended_offer_summary = {
        "offer_recommendation_id": offer_recommendation_id,
        "sku_code": sku_code,
        "service_tier_code": service_tier_code,
        "package_template_code": package_template_code,
        "recommended_delivery_form": recommended_delivery_form,
        "recommended_quote_band": recommended_quote_band,
        "offer_recommendation_state": offer_state,
        "why_recommended": _optional_str(runtime_state.resolve("why_recommended")),
    }

    upstream_reasons: list[str] = []
    if sale_gate_status in {"BLOCK", "REVIEW", "HOLD"}:
        upstream_reasons.append(f"sale_gate_status={sale_gate_status}")
    if saleability_status_seed in {"BLOCKED", "RESTRICTED"}:
        upstream_reasons.append(f"h06_saleability_status={saleability_status_seed}")
    if report_status != "ISSUED":
        upstream_reasons.append(f"report_status={report_status}")
    if review_task_status not in {"CLOSED"}:
        upstream_reasons.append(f"review_task_status={review_task_status}")
    if linked_review_request_id_optional:
        upstream_reasons.append(f"linked_review_request_id={linked_review_request_id_optional}")
    if missing_condition_family_optional:
        upstream_reasons.append(f"missing_condition_family={missing_condition_family_optional}")

    enriched_candidates: list[dict[str, Any]] = []
    for candidate in multi_competitor_candidates:
        if not isinstance(candidate, Mapping):
            continue
        item = dict(candidate)
        raw = _raw_for_candidate(item, raw_lookup)
        candidate_id = str(item.get("candidate_id"))
        candidate_source_type = _candidate_source_type(item, raw)
        subject_state, subject_reasons = _subject_eligibility(
            candidate=item,
            raw=raw,
            sale_gate_status=sale_gate_status,
            report_status=report_status,
        )
        contactability_status, contactability_snapshot, contactability_reasons = _contactability(raw=raw, inputs=inputs)
        purchase_capacity_score, capacity_reasons = _purchase_capacity(
            raw=raw,
            runtime_capacity_score=runtime_capacity_score,
        )
        is_candidate_only = candidate_id in candidate_only_ids and candidate_id != selected_candidate_id
        challenge_motivation_score = _bounded_score(
            raw.get("challenge_motivation_score", item.get("challenge_actionability_score")),
            default=_bounded_score(item.get("challenge_actionability_score"), default=50),
        )
        ranking_score = _bounded_score(item.get("ranking_score"), default=50)
        buyer_fit_score = (
            selected_buyer_fit_score
            if candidate_id == selected_candidate_id
            else round(
                (
                    selected_buyer_fit_score
                    + challenge_motivation_score
                    + purchase_capacity_score
                    + ranking_score
                )
                / 4
            )
        )
        sales_priority, sales_priority_score = _sales_priority(
            subject_state=subject_state,
            contactability_status=contactability_status,
            buyer_fit_score=buyer_fit_score,
            challenge_motivation_score=challenge_motivation_score,
            purchase_capacity_score=purchase_capacity_score,
            ranking_score=ranking_score,
        )
        candidate_blocking_reasons = _dedupe_strings(
            upstream_reasons
            + subject_reasons
            + capacity_reasons
            + [f"contactability:{reason}" for reason in contactability_reasons]
            + (
                ["candidate_only_by_competitor_cutoff"]
                if is_candidate_only
                else []
            )
        )
        status = "SELECTED" if candidate_id == selected_candidate_id else "AVAILABLE"
        if sales_priority == "BLOCK":
            status = "BLOCK"
        elif sales_priority == "REVIEW" or candidate_blocking_reasons:
            status = "REVIEW"
        elif is_candidate_only:
            status = "CANDIDATE_ONLY"

        source_refs = _dedupe_strings(
            ensure_list(raw.get("source_refs"))
            + [
                f"stage6.challenger_candidate_profile:{item.get('challenger_profile_id')}",
                f"stage7.multi_competitor_collection:{candidate_id}",
                f"stage7.competitor_confidence_policy:{competitor_trace_summary.get('ranking_policy_id')}",
            ]
        )
        enriched_candidates.append(
            {
                **item,
                "challenger_name": _optional_str(
                    raw.get("challenger_name")
                    or raw.get("challenger_org_name_optional")
                    or raw.get("normalized_org_name_optional")
                    or raw.get("name_optional")
                    or item.get("challenger_bidder_id")
                ),
                "name_optional": _optional_str(
                    raw.get("name_optional")
                    or raw.get("challenger_org_name_optional")
                    or raw.get("normalized_org_name_optional")
                ),
                "candidate_source_type": candidate_source_type,
                "rank": int(item.get("candidate_rank", 0)),
                "status": status,
                "subject_eligibility_state": subject_state,
                "challenge_motivation_score": challenge_motivation_score,
                "purchase_capacity_score": purchase_capacity_score,
                "buyer_fit_score": buyer_fit_score,
                "contactability_status": contactability_status,
                "contactability_snapshot": contactability_snapshot,
                "recommended_offer_ref": offer_recommendation_id,
                "recommended_offer_summary": dict(recommended_offer_summary),
                "sales_priority": sales_priority,
                "sales_priority_score": sales_priority_score,
                "source_refs": source_refs,
                "explainability_reasons": _dedupe_strings(
                    [
                        f"candidate_source_type={candidate_source_type}",
                        f"subject_eligibility_state={subject_state}",
                        f"challenge_motivation_score={challenge_motivation_score}",
                        f"purchase_capacity_score={purchase_capacity_score}",
                        f"buyer_fit_score={buyer_fit_score}",
                        f"contactability_status={contactability_status}",
                        f"sales_priority={sales_priority}",
                        f"selected_flag={bool(item.get('selected_flag'))}",
                    ]
                ),
                "blocking_reasons": candidate_blocking_reasons,
                "customer_visible": False,
                "internal_sales_judgment_only": True,
            }
        )

    winning_candidate = next(
        (
            candidate
            for candidate in enriched_candidates
            if candidate.get("candidate_id") == selected_candidate_id
        ),
        enriched_candidates[0] if enriched_candidates else dict(winning_competitor_candidate),
    )
    supported_coverage = sorted(
        {
            candidate["candidate_source_type"]
            for candidate in enriched_candidates
            if candidate.get("candidate_source_type") in SUPPORTED_CANDIDATE_SOURCE_TYPES
        }
    )
    winning_reasons = ensure_list(winning_candidate.get("blocking_reasons"))
    if winning_candidate.get("status") == "BLOCK":
        real_challenger_decision_state = "BLOCK"
    elif winning_reasons or winning_candidate.get("status") in {"REVIEW", "CANDIDATE_ONLY"}:
        real_challenger_decision_state = "REVIEW"
    else:
        real_challenger_decision_state = "ALLOW"

    score_components = {
        str(candidate["candidate_id"]): {
            "ranking_score": candidate.get("ranking_score"),
            "confidence_score_optional": candidate.get("confidence_score_optional"),
            "challenge_motivation_score": candidate.get("challenge_motivation_score"),
            "purchase_capacity_score": candidate.get("purchase_capacity_score"),
            "buyer_fit_score": candidate.get("buyer_fit_score"),
            "sales_priority_score": candidate.get("sales_priority_score"),
        }
        for candidate in enriched_candidates
    }
    reject_skip_reasons = [
        {
            "candidate_id": str(candidate["candidate_id"]),
            "status": str(candidate.get("status")),
            "reasons": ensure_list(candidate.get("blocking_reasons")),
            "candidate_only": (
                str(candidate["candidate_id"]) in candidate_only_ids
                and str(candidate["candidate_id"]) != selected_candidate_id
            ),
        }
        for candidate in enriched_candidates
        if candidate.get("status") != "SELECTED" or candidate.get("blocking_reasons")
    ]
    base_selection_trace = dict(competitor_selection_trace)
    base_selection_trace.update(
        {
            "selection_policy": base_selection_trace.get("selection_policy_id"),
            "selected_candidate_id": winning_candidate.get("candidate_id"),
            "selected_challenger_profile_id": winning_candidate.get("challenger_profile_id"),
            "selected_candidate_source_type": winning_candidate.get("candidate_source_type"),
            "score_components": score_components,
            "tie_breaker": [
                "ranking_score desc",
                "confidence_score_optional desc",
                "candidate_position_label asc",
                "candidate_id asc",
            ],
            "reject_skip_reasons": reject_skip_reasons,
            "winning_candidate_blocking_reasons": winning_reasons,
            "winning_consumed_by": [
                "buyer_fit",
                "challenger_buyer_fit",
                "sales_lead",
                "offer_recommendation",
                "saleable_opportunity",
            ],
        }
    )
    readback = {
        "readback_id": build_id("RCHAL", project_id),
        "readiness_state": "INTERNAL_READY" if real_challenger_decision_state == "ALLOW" else real_challenger_decision_state,
        "candidate_set": enriched_candidates,
        "candidate_source_types_covered": supported_coverage,
        "supported_candidate_source_types": sorted(SUPPORTED_CANDIDATE_SOURCE_TYPES),
        "top_n_candidate_ids": top_n_ids,
        "winning_candidate": winning_candidate,
        "selection_trace": base_selection_trace,
        "real_challenger_decision_state": real_challenger_decision_state,
        "blocking_reasons": winning_reasons,
        "recommended_offer_summary": recommended_offer_summary,
        "stage8_compliance_boundary": {
            "stage7_contactability_is_readiness_only": True,
            "stage8_compliance_required_before_touch": True,
            "stage8ComplianceRequiredBeforeTouch": True,
            "outbox_created": False,
            "outboxCreated": False,
            "real_touch_enabled": False,
            "realTouchEnabled": False,
            "crm_or_quote_provider_called": False,
            "crmOrQuoteProviderCalled": False,
        },
        "customer_visible_field_isolation": {
            "customer_visible_enabled": False,
            "customerVisibleEnabled": False,
            "external_delivery_enabled": False,
            "externalDeliveryEnabled": False,
            "internal_only_fields": [
                "challenge_motivation_score",
                "purchase_capacity_score",
                "buyer_fit_score",
                "contactability_status",
                "sales_priority",
                "sales_priority_score",
                "selection_trace",
                "blocking_reasons",
            ],
            "internalOnlyFields": [
                "challenge_motivation_score",
                "purchase_capacity_score",
                "buyer_fit_score",
                "contactability_status",
                "sales_priority",
                "sales_priority_score",
                "selection_trace",
                "blocking_reasons",
            ],
            "not_legal_conclusion": True,
            "notLegalConclusion": True,
        },
        "policy_refs": {
            "challenger_profile_catalog": "contracts/sales/challenger_profile_catalog.json",
            "buyer_fit_scorecard": "contracts/sales/buyer_fit_scorecard.json",
            "opportunity_policy_catalog": "contracts/sales/opportunity_policy_catalog.json",
        },
        "action_family": action_family,
    }
    return {
        "multi_competitor_candidates": enriched_candidates,
        "winning_competitor_candidate": winning_candidate,
        "competitor_selection_trace": base_selection_trace,
        "real_challenger_readback": readback,
        "real_challenger_decision_state": real_challenger_decision_state,
        "real_challenger_blocking_reasons": winning_reasons,
    }


__all__ = ["build_real_challenger_readback"]
