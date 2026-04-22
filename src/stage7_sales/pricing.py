from __future__ import annotations

from typing import Any

from stage7_sales.runtime import optional_number, optional_str, resolved_policy_output


def resolve_price_projection(runtime_state: Any) -> dict[str, Any]:
    return {
        "normalized_price_amount_optional": optional_number(
            resolved_policy_output(
                runtime_state,
                "price_normalization",
                "normalized_price_amount",
                allow_none=True,
            )
        ),
        "price_conflict_gate_status_optional": optional_str(
            resolved_policy_output(runtime_state, "price_normalization", "price_conflict_gate_status")
        ),
        "price_band_optional": optional_str(
            resolved_policy_output(runtime_state, "price_normalization", "price_band")
        ),
        "price_recommended_quote_band": optional_str(
            resolved_policy_output(runtime_state, "price_normalization", "recommended_quote_band")
        ),
    }


def build_price_resolution_trace(
    runtime_state: Any,
    *,
    price_band_optional: str | None,
    price_recommended_quote_band: str | None,
) -> dict[str, Any]:
    return {
        "policy_id": runtime_state.resolve("price_resolution_policy_id"),
        "selected_source_type": runtime_state.resolve("selected_price_source_type"),
        "price_candidate_count": runtime_state.resolve("price_candidate_count", 0),
        "price_candidate_deduped_count": runtime_state.resolve("price_candidate_deduped_count", 0),
        "price_source_priority_applied": runtime_state.resolve("price_source_priority_applied", []),
        "normalized_currency": runtime_state.resolve("normalized_price_currency", "CNY"),
        "normalized_tax_basis": runtime_state.resolve("normalized_tax_basis", "EX_TAX"),
        "normalized_unit_basis": runtime_state.resolve("normalized_unit_basis", "TOTAL_AMOUNT"),
        "selected_scope_key": runtime_state.resolve("selected_scope_key", "GLOBAL"),
        "price_band": price_band_optional,
        "recommended_quote_band": price_recommended_quote_band,
        "quote_band_authority_ref": "contracts/sales/price_normalization_catalog.json#authorityContract",
        "review_flags": runtime_state.resolve("price_review_flags", []),
        "selected_candidate_trace": runtime_state.resolve("selected_candidate_trace", {}),
    }
