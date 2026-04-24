from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Mapping


PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY = "provider_adapter_readiness_summary"
PROVIDER_ADAPTER_BOOTSTRAP_KEY = "provider_adapter_bootstrap"
PROVIDER_ADAPTER_CONFIG_RECORD_ID = "ACTIVE_PROVIDER_ADAPTER_CONFIG"
PROVIDER_ADAPTER_CONFIG_OBJECT_TYPE = "provider_adapter_config_readback"

PROVIDER_MODE = "SANDBOX_DRY_RUN_READBACK"
PROVIDER_CONFIG_SOURCE_DEFAULT = "Settings.provider_adapter_config"
PROVIDER_CONFIG_SOURCE_REF = "shared.provider_adapter_config"
PROVIDER_BLOCKED_LIVE_REASON = "live_provider_mode_requested_but_blocked"
PROVIDER_BLOCKED_REAL_CALL_REASON = "real_provider_call_blocked_readback_only"
PROVIDER_BLOCKED_REFUND_REASON = "automated_refund_program_absent_blocked"

PROVIDER_FAMILIES: tuple[str, ...] = (
    "sales_outreach",
    "crm_quote",
    "leadpack_page_delivery",
    "payment_collection",
)

_DEFAULT_PROVIDER_BY_FAMILY = {
    "sales_outreach": "internal_sandbox_sales_outreach",
    "crm_quote": "internal_sandbox_crm_quote",
    "leadpack_page_delivery": "internal_sandbox_leadpack_page_delivery",
    "payment_collection": "internal_sandbox_payment_collection",
}

_PROVIDER_ENV_BY_FAMILY = {
    "sales_outreach": "KAKA_SALES_OUTREACH_PROVIDER",
    "crm_quote": "KAKA_CRM_QUOTE_PROVIDER",
    "leadpack_page_delivery": "KAKA_LEADPACK_DELIVERY_PROVIDER",
    "payment_collection": "KAKA_PAYMENT_COLLECTION_PROVIDER",
}

_CREDENTIAL_ENVS_BY_FAMILY = {
    "sales_outreach": (
        "KAKA_SALES_OUTREACH_API_KEY",
        "KAKA_SALES_OUTREACH_TOKEN",
        "KAKA_SALES_OUTREACH_SECRET",
    ),
    "crm_quote": (
        "KAKA_CRM_QUOTE_API_KEY",
        "KAKA_CRM_QUOTE_TOKEN",
        "KAKA_CRM_QUOTE_SECRET",
    ),
    "leadpack_page_delivery": (
        "KAKA_LEADPACK_DELIVERY_API_KEY",
        "KAKA_LEADPACK_DELIVERY_TOKEN",
        "KAKA_LEADPACK_DELIVERY_SECRET",
    ),
    "payment_collection": (
        "KAKA_PAYMENT_COLLECTION_API_KEY",
        "KAKA_PAYMENT_COLLECTION_TOKEN",
        "KAKA_PAYMENT_COLLECTION_SECRET",
    ),
}

_ALLOWED_PROVIDER_IDS_BY_FAMILY = {
    "sales_outreach": frozenset(
        {
            "internal_sandbox_sales_outreach",
            "internal_sandbox_outreach",
            "sandbox_sales_outreach",
            "sandbox_outreach",
            "dry_run_sales_outreach",
            "readback_only_sales_outreach",
            "sendgrid_sandbox",
            "twilio_sandbox",
            "wecom_sandbox",
        }
    ),
    "crm_quote": frozenset(
        {
            "internal_sandbox_crm_quote",
            "internal_manual_crm",
            "internal_manual_quote",
            "sandbox_crm_quote",
            "dry_run_crm_quote",
            "readback_only_crm_quote",
            "hubspot_sandbox",
            "salesforce_sandbox",
        }
    ),
    "leadpack_page_delivery": frozenset(
        {
            "internal_sandbox_leadpack_page_delivery",
            "internal_sandbox_leadpack_delivery",
            "sandbox_leadpack_page_delivery",
            "sandbox_leadpack_delivery",
            "static_page_sandbox",
            "object_storage_sandbox",
            "dry_run_leadpack_page_delivery",
            "readback_only_leadpack_page_delivery",
        }
    ),
    "payment_collection": frozenset(
        {
            "internal_sandbox_payment_collection",
            "sandbox_payment_collection",
            "dry_run_payment_collection",
            "readback_only_payment_collection",
            "stripe_sandbox",
            "manual_bank_transfer_sandbox",
        }
    ),
}

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on", "live", "enabled", "production", "prod"})
_LIVE_MODE_VALUES = frozenset({"live", "production", "prod", "real", "external_live"})


@dataclass(frozen=True)
class ProviderAdapterFamilyConfig:
    family: str
    provider_id: str
    configured_provider_id: str | None
    provider_env: str
    credential_envs: tuple[str, ...]
    present_credential_envs: tuple[str, ...]


@dataclass(frozen=True)
class ProviderAdapterConfig:
    config_source: str = PROVIDER_CONFIG_SOURCE_DEFAULT
    requested_mode: str = PROVIDER_MODE
    requested_live_mode: bool = False
    families: tuple[ProviderAdapterFamilyConfig, ...] = ()


def _normalize_provider_id(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    return normalized or None


def _read_optional(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _is_truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() in _TRUTHY_VALUES)


def _requested_live_mode(environ: Mapping[str, str], requested_mode: str) -> bool:
    return (
        requested_mode.strip().lower() in _LIVE_MODE_VALUES
        or _is_truthy(_read_optional(environ, "KAKA_PROVIDER_ADAPTER_LIVE"))
        or _is_truthy(_read_optional(environ, "KAKA_PROVIDER_LIVE"))
    )


def build_provider_adapter_config_from_env(
    environ: Mapping[str, str] | None = None,
) -> ProviderAdapterConfig:
    env = environ if environ is not None else os.environ
    config_source = _read_optional(env, "KAKA_PROVIDER_ADAPTER_CONFIG_SOURCE") or PROVIDER_CONFIG_SOURCE_DEFAULT
    requested_mode = _read_optional(env, "KAKA_PROVIDER_ADAPTER_MODE") or PROVIDER_MODE
    families: list[ProviderAdapterFamilyConfig] = []

    for family in PROVIDER_FAMILIES:
        provider_env = _PROVIDER_ENV_BY_FAMILY[family]
        configured_provider_id = _normalize_provider_id(_read_optional(env, provider_env))
        provider_id = configured_provider_id or _DEFAULT_PROVIDER_BY_FAMILY[family]
        allowed_provider_ids = _ALLOWED_PROVIDER_IDS_BY_FAMILY[family]
        if provider_id not in allowed_provider_ids:
            raise ValueError(
                "unsupported provider adapter "
                f"{provider_id!r} for {family}; supported sandbox/readback providers: {sorted(allowed_provider_ids)}"
            )

        credential_envs = _CREDENTIAL_ENVS_BY_FAMILY[family]
        present_credential_envs = tuple(name for name in credential_envs if _read_optional(env, name))
        families.append(
            ProviderAdapterFamilyConfig(
                family=family,
                provider_id=provider_id,
                configured_provider_id=configured_provider_id,
                provider_env=provider_env,
                credential_envs=credential_envs,
                present_credential_envs=present_credential_envs,
            )
        )

    return ProviderAdapterConfig(
        config_source=config_source,
        requested_mode=requested_mode,
        requested_live_mode=_requested_live_mode(env, requested_mode),
        families=tuple(families),
    )


def _credential_metadata(family_config: ProviderAdapterFamilyConfig) -> dict[str, Any]:
    credential_present = bool(family_config.present_credential_envs)
    return {
        "credential_present": credential_present,
        "present_env_vars": list(family_config.present_credential_envs),
        "checked_env_vars": list(family_config.credential_envs),
        "redaction": "present-redacted" if credential_present else "absent",
        "plaintext_persisted": False,
        "plaintext_output_enabled": False,
    }


def _family_summary(
    family_config: ProviderAdapterFamilyConfig,
    *,
    requested_live_mode: bool,
) -> dict[str, Any]:
    blocked_reasons = [
        f"{family_config.family}_sandbox_dry_run_readback_only",
        PROVIDER_BLOCKED_REAL_CALL_REASON,
        "approval_and_audit_required_before_any_live_provider_use",
    ]
    if requested_live_mode:
        blocked_reasons.append(PROVIDER_BLOCKED_LIVE_REASON)

    return {
        "family": family_config.family,
        "provider_id": family_config.provider_id,
        "configured_provider_id": family_config.configured_provider_id,
        "provider_env": family_config.provider_env,
        "readiness_state": "SANDBOX_DRY_RUN_READY",
        "mode": PROVIDER_MODE,
        "sandbox_enabled": True,
        "dry_run_enabled": True,
        "readback_only": True,
        "provider_adapter_configured": True,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "live_request_blocked": True,
        "credential_metadata": _credential_metadata(family_config),
        "approval_audit_prerequisites": {
            "approval_required_before_live_provider_use": True,
            "audit_required_before_live_provider_use": True,
            "human_review_required_before_live_provider_use": True,
            "current_approval_satisfied": False,
            "current_audit_satisfied": False,
        },
        "blocked_reasons": blocked_reasons,
    }


def build_provider_adapter_readiness_summary(config: ProviderAdapterConfig) -> dict[str, Any]:
    family_summaries = {
        family_config.family: _family_summary(
            family_config,
            requested_live_mode=config.requested_live_mode,
        )
        for family_config in config.families
    }
    blocked_reasons = [
        PROVIDER_BLOCKED_REAL_CALL_REASON,
        "provider_adapters_readback_only",
        "approval_and_audit_required_before_any_live_provider_use",
        PROVIDER_BLOCKED_REFUND_REASON,
    ]
    if config.requested_live_mode:
        blocked_reasons.append(PROVIDER_BLOCKED_LIVE_REASON)

    automated_refund_program = {
        "present": False,
        "enabled": False,
        "state": "ABSENT_BLOCKED",
        "automated_refund_enabled": False,
        "real_refund_enabled": False,
        "operator_can_execute_automated_refund": False,
        "blocked_reasons": [PROVIDER_BLOCKED_REFUND_REASON, "automatic_refund_out_of_scope"],
    }

    summary: dict[str, Any] = {
        "config_source": config.config_source,
        "config_source_ref": PROVIDER_CONFIG_SOURCE_REF,
        "mode": PROVIDER_MODE,
        "requested_mode": config.requested_mode,
        "requested_live_mode": config.requested_live_mode,
        "readback_only": True,
        "sandbox_enabled": True,
        "dry_run_enabled": True,
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "live_execution_enabled": False,
        "live_request_blocked": True,
        "blocked_reasons": blocked_reasons,
        "approval_audit_prerequisites": {
            "approval_required_before_live_provider_use": True,
            "audit_required_before_live_provider_use": True,
            "human_review_required_before_live_provider_use": True,
            "missing_prerequisites": [
                "live_provider_approval_chain",
                "live_provider_audit_chain",
                "human_provider_activation_review",
            ],
        },
        "families": family_summaries,
        "automated_refund_program": automated_refund_program,
    }
    for family, family_summary in family_summaries.items():
        summary[family] = family_summary
    return summary


def provider_readiness_for_family(
    readiness_summary: Mapping[str, Any] | None,
    family: str,
) -> dict[str, Any]:
    if not isinstance(readiness_summary, Mapping):
        return {}
    families = readiness_summary.get("families")
    if isinstance(families, Mapping):
        family_summary = families.get(family)
        if isinstance(family_summary, Mapping):
            return dict(family_summary)
    family_summary = readiness_summary.get(family)
    return dict(family_summary) if isinstance(family_summary, Mapping) else {}


def provider_adapter_bootstrap_payload(
    readiness_summary: Mapping[str, Any],
) -> dict[str, Any]:
    summary = dict(readiness_summary)
    return {
        "provider_adapter_config_source": summary.get("config_source"),
        "provider_adapter_config_source_ref": summary.get("config_source_ref"),
        "provider_adapter_mode": summary.get("mode"),
        "provider_adapter_requested_mode": summary.get("requested_mode"),
        "provider_adapter_readback_only": bool(summary.get("readback_only", True)),
        "provider_adapter_sandbox_enabled": bool(summary.get("sandbox_enabled", True)),
        "provider_adapter_dry_run_enabled": bool(summary.get("dry_run_enabled", True)),
        "provider_adapter_live_execution_enabled": False,
        "provider_adapter_provider_call_enabled": False,
        "provider_adapter_real_provider_call_enabled": False,
        "provider_adapter_blocked_reasons": list(summary.get("blocked_reasons", [])),
        "provider_adapter_approval_audit_prerequisites": dict(
            summary.get("approval_audit_prerequisites", {})
        ),
        PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY: summary,
    }


def attach_provider_adapter_readiness(
    payload: Mapping[str, Any],
    readiness_summary: Mapping[str, Any],
    *,
    family: str | None = None,
) -> dict[str, Any]:
    result = dict(payload)
    summary = dict(readiness_summary)
    result[PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY] = summary
    result["provider_adapter_config_source"] = summary.get("config_source")
    result["provider_adapter_mode"] = summary.get("mode")
    result["provider_adapter_blocked_reasons"] = list(summary.get("blocked_reasons", []))
    result["provider_adapter_approval_audit_prerequisites"] = dict(
        summary.get("approval_audit_prerequisites", {})
    )
    if family:
        result["provider_adapter_readiness"] = provider_readiness_for_family(summary, family)
    return result


__all__ = [
    "PROVIDER_ADAPTER_BOOTSTRAP_KEY",
    "PROVIDER_ADAPTER_CONFIG_OBJECT_TYPE",
    "PROVIDER_ADAPTER_CONFIG_RECORD_ID",
    "PROVIDER_ADAPTER_READINESS_SUMMARY_INPUT_KEY",
    "PROVIDER_FAMILIES",
    "ProviderAdapterConfig",
    "ProviderAdapterFamilyConfig",
    "attach_provider_adapter_readiness",
    "build_provider_adapter_config_from_env",
    "build_provider_adapter_readiness_summary",
    "provider_adapter_bootstrap_payload",
    "provider_readiness_for_family",
]
