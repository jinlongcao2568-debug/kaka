from __future__ import annotations

import hashlib
from typing import Any, Mapping

from shared.utils import build_id, ensure_list, utc_now_iso


MODEL_ASSIST_INPUT_KEY = "model_assist_governance"
MODEL_ASSIST_SUMMARY_INPUT_KEY = "model_assist_governance_summary"
MODEL_ASSIST_MODE = "GOVERNED_ASSIST_READBACK"
MODEL_ASSIST_PROVIDER_SURFACE = "LOCAL_DETERMINISTIC_ASSIST"
MODEL_ASSIST_POLICY_REF = "contracts/model/model_usage_policy.json#governed_model_assist"
MODEL_ASSIST_GOLDEN_CASE_REFS = [
    "MODEL-GOLDEN-FIELD-EXTRACTION-CANDIDATE",
    "MODEL-GOLDEN-EVIDENCE-SUMMARY-REVIEW",
    "MODEL-GOLDEN-SALES-TALK-TRACK-DRAFT",
]

_EMPTY_VALUES = {None, "", "UNKNOWN", "None"}


def build_model_assist_governance_summary(
    *,
    assist_scope: str,
    source_refs: Mapping[str, Any] | None = None,
    prompt_purpose: str,
    output_kind: str,
    field_candidates: list[Mapping[str, Any]] | None = None,
    evidence_refs: list[Any] | None = None,
    sales_context_refs: Mapping[str, Any] | None = None,
    private_data_requested: bool = False,
    customer_visible_requested: bool = False,
) -> dict[str, Any]:
    """Build a deterministic model-assist carrier.

    This is intentionally a governed readback surface. It records what a model
    *may assist with* and the review obligations, without calling an external
    model provider or upgrading model output into facts/customer conclusions.
    """

    now = utc_now_iso()
    normalized_fields = [_field_candidate_payload(field) for field in field_candidates or []]
    normalized_evidence_refs = [ref for ref in ensure_list(evidence_refs) if not _is_empty(ref)]
    normalized_source_refs = dict(source_refs or {})
    normalized_sales_refs = dict(sales_context_refs or {})
    prompt_trace = {
        "prompt_trace_id": _stable_id("MA-PROMPT", assist_scope, prompt_purpose, normalized_source_refs),
        "prompt_purpose": prompt_purpose,
        "input_boundary": "PUBLIC_OR_INTERNAL_SANITIZED_ONLY",
        "private_data_requested": bool(private_data_requested),
        "customer_visible_requested": bool(customer_visible_requested),
        "prompt_template_ref": "contracts/model/model_usage_policy.json#prompt_templates.governed_assist",
        "source_refs": normalized_source_refs,
        "evidence_refs": list(normalized_evidence_refs),
        "sales_context_refs": normalized_sales_refs,
        "redaction_policy": {
            "private_data_to_model_allowed": False,
            "credential_or_secret_to_model_allowed": False,
            "customer_personal_data_to_model_allowed": False,
            "raw_private_document_to_model_allowed": False,
        },
    }
    blocked_reasons: list[str] = []
    if private_data_requested:
        blocked_reasons.append("private_data_to_model_without_policy")
    if customer_visible_requested:
        blocked_reasons.append("customer_visible_model_output_requires_human_review")
    output_trace = {
        "output_trace_id": _stable_id("MA-OUT", assist_scope, output_kind, normalized_fields, normalized_evidence_refs),
        "output_kind": output_kind,
        "deterministic_assist": True,
        "external_model_provider_called": False,
        "real_model_provider_call_enabled": False,
        "real_model_provider_call_executed": False,
        "field_candidate_count": len(normalized_fields),
        "evidence_ref_count": len(normalized_evidence_refs),
        "model_output_not_final_fact": True,
        "model_output_not_customer_conclusion": True,
        "human_review_required": True,
        "blocked_reasons": list(blocked_reasons),
        "generated_at": now,
    }
    return {
        "assist_id": _stable_id("MA", assist_scope, output_kind, normalized_source_refs, normalized_fields),
        "assist_scope": assist_scope,
        "model_assist_mode": MODEL_ASSIST_MODE,
        "model_provider_execution_surface": MODEL_ASSIST_PROVIDER_SURFACE,
        "policy_ref": MODEL_ASSIST_POLICY_REF,
        "model_provider_configured": False,
        "real_model_provider_call_enabled": False,
        "real_model_provider_call_executed": False,
        "external_network_call_executed": False,
        "prompt_trace": prompt_trace,
        "output_trace": output_trace,
        "field_extraction_candidates": normalized_fields,
        "evidence_summary_draft": _evidence_summary_draft(normalized_evidence_refs, normalized_source_refs),
        "review_triage": _review_triage(blocked_reasons, normalized_fields, normalized_evidence_refs),
        "sales_talk_track_draft": _sales_talk_track_draft(normalized_sales_refs),
        "source_refs": normalized_source_refs,
        "evidence_refs": normalized_evidence_refs,
        "sales_context_refs": normalized_sales_refs,
        "audit_refs": {
            "model_usage_policy_ref": MODEL_ASSIST_POLICY_REF,
            "model_registry_ref": "control/model_registry.yaml",
            "model_release_manifest_ref": "control/model_release_manifest.yaml",
            "golden_case_refs": list(MODEL_ASSIST_GOLDEN_CASE_REFS),
            "prompt_trace_id": prompt_trace["prompt_trace_id"],
            "output_trace_id": output_trace["output_trace_id"],
        },
        "human_review_required": True,
        "customer_visible": False,
        "formal_fact_write_enabled": False,
        "stage_fact_mutation_enabled": False,
        "customer_visible_claim_enabled": False,
        "no_private_data_to_model_without_policy": not private_data_requested,
        "no_internal_blackbox_customer_exposure": True,
        "controlled_opening_boundaries": {
            "model_output_not_final_fact": True,
            "model_output_not_customer_conclusion": True,
            "human_review_required_for_customer_visible_claim": True,
            "private_data_to_model_without_policy_blocked": True,
            "credential_or_secret_to_model_blocked": True,
        },
        "blocked_reasons": blocked_reasons,
        "replay_state": {
            "replayable": True,
            "readback_only": True,
            "no_broad_fallback": True,
            "created_at": now,
        },
    }


def build_model_assist_summary(carrier: Mapping[str, Any]) -> dict[str, Any]:
    output_trace = dict(carrier.get("output_trace", {}))
    controlled_opening_boundaries = dict(carrier.get("controlled_opening_boundaries", {}))
    return {
        "assist_id": carrier.get("assist_id"),
        "assist_scope": carrier.get("assist_scope"),
        "model_assist_mode": carrier.get("model_assist_mode"),
        "output_kind": output_trace.get("output_kind"),
        "human_review_required": bool(carrier.get("human_review_required", True)),
        "customer_visible": bool(carrier.get("customer_visible", False)),
        "formal_fact_write_enabled": bool(carrier.get("formal_fact_write_enabled", False)),
        "real_model_provider_call_executed": bool(carrier.get("real_model_provider_call_executed", False)),
        "model_output_not_final_fact": bool(controlled_opening_boundaries.get("model_output_not_final_fact", True)),
        "model_output_not_customer_conclusion": bool(
            controlled_opening_boundaries.get("model_output_not_customer_conclusion", True)
        ),
        "no_private_data_to_model_without_policy": bool(
            carrier.get("no_private_data_to_model_without_policy", True)
        ),
        "golden_case_refs": list(dict(carrier.get("audit_refs", {})).get("golden_case_refs", [])),
        "replayable": bool(dict(carrier.get("replay_state", {})).get("replayable", False)),
    }


def build_parser_model_assist(
    parser_carrier: Mapping[str, Any],
    *,
    customer_visible_requested: bool = False,
) -> dict[str, Any]:
    fields = [
        {
            "field_name": field.get("field_name"),
            "field_value_optional": field.get("field_value_optional"),
            "source_slice_sha256": field.get("source_slice_sha256"),
            "confidence": field.get("confidence"),
            "review_required": True,
            "candidate_state": "MODEL_ASSISTED_CANDIDATE_REVIEW_REQUIRED",
        }
        for field in ensure_list(parser_carrier.get("parsed_fields"))
        if isinstance(field, Mapping)
    ]
    source_refs = {
        "snapshot_id": parser_carrier.get("snapshot_id"),
        "parse_run_id": parser_carrier.get("parse_run_id"),
        "source_url": parser_carrier.get("source_url"),
        "source_family": parser_carrier.get("source_family"),
        "content_type": parser_carrier.get("content_type"),
    }
    return build_model_assist_governance_summary(
        assist_scope="stage3_parser_field_extraction",
        source_refs=source_refs,
        prompt_purpose="field_extraction_candidate_and_ocr_table_review_assist",
        output_kind="llm_assisted_field_extraction_candidate",
        field_candidates=fields,
        evidence_refs=[parser_carrier.get("snapshot_id"), parser_carrier.get("parse_run_id")],
        private_data_requested=False,
        customer_visible_requested=customer_visible_requested,
    )


def build_verification_model_assist(
    verification_carrier: Mapping[str, Any],
    *,
    customer_visible_requested: bool = False,
) -> dict[str, Any]:
    source_refs = {
        "verification_run_id": verification_carrier.get("verification_run_id"),
        "verification_target_id": verification_carrier.get("verification_target_id"),
        "verification_target_type": verification_carrier.get("verification_target_type"),
        "source_snapshot_id": verification_carrier.get("source_snapshot_id"),
        "verification_result": verification_carrier.get("verification_result"),
        "evidence_grade": verification_carrier.get("evidence_grade"),
    }
    return build_model_assist_governance_summary(
        assist_scope="stage4_public_verification_review",
        source_refs=source_refs,
        prompt_purpose="public_evidence_summary_and_review_triage_assist",
        output_kind="llm_assisted_evidence_summary",
        evidence_refs=ensure_list(verification_carrier.get("snapshot_refs"))
        + ensure_list(verification_carrier.get("source_refs"))
        + [verification_carrier.get("verification_run_id")],
        private_data_requested=not bool(verification_carrier.get("public_only", True)),
        customer_visible_requested=customer_visible_requested,
    )


def build_rule_model_assist(
    *,
    stage5_readback_summary: Mapping[str, Any],
    rule_execution_trace: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    source_refs = {
        "catalog_id": stage5_readback_summary.get("catalog_id"),
        "catalog_version": stage5_readback_summary.get("catalog_version"),
        "rule_gate_decision_id": stage5_readback_summary.get("rule_gate_decision_id"),
        "evidence_gate_decision_id": stage5_readback_summary.get("evidence_gate_decision_id"),
        "review_request_id": stage5_readback_summary.get("review_request_id"),
    }
    return build_model_assist_governance_summary(
        assist_scope="stage5_rule_review_triage",
        source_refs=source_refs,
        prompt_purpose="rule_hit_review_triage_and_evidence_gap_summary",
        output_kind="llm_assisted_review_triage",
        evidence_refs=ensure_list(stage5_readback_summary.get("evidence_refs")),
        sales_context_refs={
            "selected_rule_count": stage5_readback_summary.get("selected_count"),
            "review_count": stage5_readback_summary.get("review_count"),
            "block_count": stage5_readback_summary.get("block_count"),
            "trace_count": len(rule_execution_trace or []),
        },
        private_data_requested=False,
        customer_visible_requested=False,
    )


def build_sales_talk_track_model_assist(
    *,
    sales_lead: Mapping[str, Any],
    saleable_opportunity: Mapping[str, Any],
    offer_recommendation: Mapping[str, Any],
    source_refs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    sales_refs = {
        "sales_lead_id": sales_lead.get("lead_id") or sales_lead.get("sales_lead_id"),
        "lead_status": sales_lead.get("lead_status"),
        "opportunity_id": saleable_opportunity.get("opportunity_id"),
        "saleability_status": saleable_opportunity.get("saleability_status"),
        "offer_recommendation_id": offer_recommendation.get("offer_recommendation_id"),
        "offer_state": offer_recommendation.get("offer_state"),
        "recommended_quote_band": offer_recommendation.get("recommended_quote_band"),
    }
    return build_model_assist_governance_summary(
        assist_scope="stage7_sales_talk_track",
        source_refs=source_refs or {},
        prompt_purpose="sales_talk_track_draft_and_risk_disclaimer_assist",
        output_kind="llm_assisted_sales_talk_track_draft",
        sales_context_refs=sales_refs,
        evidence_refs=[value for value in sales_refs.values() if not _is_empty(value)],
        private_data_requested=False,
        customer_visible_requested=True,
    )


def _field_candidate_payload(field: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "field_name": field.get("field_name"),
        "field_value_optional": field.get("field_value_optional"),
        "source_slice_sha256": field.get("source_slice_sha256"),
        "confidence": field.get("confidence"),
        "candidate_state": field.get("candidate_state", "MODEL_ASSISTED_CANDIDATE_REVIEW_REQUIRED"),
        "review_required": True,
        "not_formal_fact": True,
    }


def _evidence_summary_draft(evidence_refs: list[Any], source_refs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "draft_state": "REVIEW_REQUIRED",
        "summary_kind": "INTERNAL_EVIDENCE_SUMMARY_DRAFT",
        "source_ref_count": len([value for value in source_refs.values() if not _is_empty(value)]),
        "evidence_ref_count": len(evidence_refs),
        "customer_visible_enabled": False,
        "legal_conclusion_enabled": False,
        "must_be_reviewed_by_human": True,
    }


def _review_triage(blocked_reasons: list[str], fields: list[dict[str, Any]], evidence_refs: list[Any]) -> dict[str, Any]:
    return {
        "triage_state": "BLOCKED" if blocked_reasons else "REVIEW_REQUIRED",
        "review_lane": "MODEL_ASSISTED_HUMAN_REVIEW",
        "field_candidate_count": len(fields),
        "evidence_ref_count": len(evidence_refs),
        "blocked_reasons": list(blocked_reasons),
        "human_owner_action_required": True,
    }


def _sales_talk_track_draft(sales_refs: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "draft_state": "REVIEW_REQUIRED",
        "talk_track_kind": "INTERNAL_SALES_TALK_TRACK_DRAFT",
        "sales_context_refs": dict(sales_refs),
        "misleading_claim_guard": "REQUIRED",
        "customer_send_enabled": False,
        "human_review_required": True,
        "not_legal_conclusion": True,
    }


def _stable_id(prefix: str, *parts: Any) -> str:
    digest_source = repr(parts).encode("utf-8")
    digest = hashlib.sha256(digest_source).hexdigest()[:12].upper()
    return build_id(prefix, digest)


def _is_empty(value: Any) -> bool:
    if isinstance(value, (dict, list, tuple, set)):
        return len(value) == 0
    return value in _EMPTY_VALUES


__all__ = [
    "MODEL_ASSIST_GOLDEN_CASE_REFS",
    "MODEL_ASSIST_INPUT_KEY",
    "MODEL_ASSIST_MODE",
    "MODEL_ASSIST_PROVIDER_SURFACE",
    "MODEL_ASSIST_SUMMARY_INPUT_KEY",
    "build_model_assist_governance_summary",
    "build_model_assist_summary",
    "build_parser_model_assist",
    "build_rule_model_assist",
    "build_sales_talk_track_model_assist",
    "build_verification_model_assist",
]
