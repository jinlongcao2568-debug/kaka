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
PROVIDER_RELIABILITY_APPROVAL_READY = "APPROVAL_READY"
PROVIDER_RELIABILITY_SUSPENDED = "SUSPENDED"
LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER = "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER"

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
            "local_controlled_fake_crm_quote_provider",
            "local_controlled_fake_crm_quote",
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
_HEALTH_BLOCKING_STATES = frozenset({"UNHEALTHY"})
_CIRCUIT_BLOCKING_STATES = frozenset({"OPEN", "HALF_OPEN", "FORCED_OPEN"})
_NO_FAILURE_STATES = frozenset({"", "NONE", "OK", "NO_FAILURE"})
_DEFAULT_TIMEOUT_MS = 30_000
_DEFAULT_RETRY_MAX_ATTEMPTS = 0
_DEFAULT_RETRY_BACKOFF_MS = 0

_PROVIDER_RELIABILITY_ENV_PREFIX_BY_FAMILY = {
    "sales_outreach": "KAKA_SALES_OUTREACH_PROVIDER",
    "crm_quote": "KAKA_CRM_QUOTE_PROVIDER",
    "leadpack_page_delivery": "KAKA_LEADPACK_DELIVERY_PROVIDER",
    "payment_collection": "KAKA_PAYMENT_COLLECTION_PROVIDER",
}


@dataclass(frozen=True)
class ProviderAdapterFamilyConfig:
    family: str
    provider_id: str
    configured_provider_id: str | None
    provider_env: str
    credential_envs: tuple[str, ...]
    present_credential_envs: tuple[str, ...]
    reliability: Mapping[str, Any]


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


def _normalize_status(value: str | None, *, default: str) -> str:
    if value is None:
        return default
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    return normalized or default


def _read_family_or_global(
    environ: Mapping[str, str],
    *,
    family: str,
    suffix: str,
    global_name: str,
) -> tuple[str | None, str]:
    family_name = f"{_PROVIDER_RELIABILITY_ENV_PREFIX_BY_FAMILY[family]}{suffix}"
    family_value = _read_optional(environ, family_name)
    if family_value is not None:
        return family_value, family_name
    return _read_optional(environ, global_name), global_name


def _read_family_int(
    environ: Mapping[str, str],
    *,
    family: str,
    suffix: str,
    global_name: str,
    default: int,
) -> tuple[int, str]:
    value, env_name = _read_family_or_global(
        environ,
        family=family,
        suffix=suffix,
        global_name=global_name,
    )
    if value is None:
        return default, env_name
    try:
        parsed = int(value)
    except ValueError:
        return default, env_name
    return max(parsed, 0), env_name


def _build_family_reliability_config(environ: Mapping[str, str], family: str) -> dict[str, Any]:
    health_status, health_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_HEALTH",
        global_name="KAKA_PROVIDER_ADAPTER_HEALTH",
    )
    rate_limited, rate_limit_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_RATE_LIMITED",
        global_name="KAKA_PROVIDER_ADAPTER_RATE_LIMITED",
    )
    timeout_triggered, timeout_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_TIMEOUT",
        global_name="KAKA_PROVIDER_ADAPTER_TIMEOUT",
    )
    failure_class, failure_class_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_FAILURE_CLASS",
        global_name="KAKA_PROVIDER_ADAPTER_FAILURE_CLASS",
    )
    failure_reason, failure_reason_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_FAILURE_REASON",
        global_name="KAKA_PROVIDER_ADAPTER_FAILURE_REASON",
    )
    circuit_state, circuit_state_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CIRCUIT_STATE",
        global_name="KAKA_PROVIDER_ADAPTER_CIRCUIT_STATE",
    )
    circuit_open, circuit_open_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CIRCUIT_OPEN",
        global_name="KAKA_PROVIDER_ADAPTER_CIRCUIT_OPEN",
    )
    timeout_ms, timeout_ms_env = _read_family_int(
        environ,
        family=family,
        suffix="_TIMEOUT_MS",
        global_name="KAKA_PROVIDER_ADAPTER_TIMEOUT_MS",
        default=_DEFAULT_TIMEOUT_MS,
    )
    retry_max_attempts, retry_max_attempts_env = _read_family_int(
        environ,
        family=family,
        suffix="_RETRY_MAX_ATTEMPTS",
        global_name="KAKA_PROVIDER_ADAPTER_RETRY_MAX_ATTEMPTS",
        default=_DEFAULT_RETRY_MAX_ATTEMPTS,
    )
    retry_backoff_ms, retry_backoff_ms_env = _read_family_int(
        environ,
        family=family,
        suffix="_RETRY_BACKOFF_MS",
        global_name="KAKA_PROVIDER_ADAPTER_RETRY_BACKOFF_MS",
        default=_DEFAULT_RETRY_BACKOFF_MS,
    )
    rate_limit_retry_after_seconds, rate_limit_retry_after_env = _read_family_int(
        environ,
        family=family,
        suffix="_RATE_LIMIT_RETRY_AFTER_SECONDS",
        global_name="KAKA_PROVIDER_ADAPTER_RATE_LIMIT_RETRY_AFTER_SECONDS",
        default=0,
    )

    normalized_circuit_state = _normalize_status(circuit_state, default="CLOSED")
    circuit_open_enabled = _is_truthy(circuit_open) or normalized_circuit_state in _CIRCUIT_BLOCKING_STATES
    if circuit_open_enabled and normalized_circuit_state == "CLOSED":
        normalized_circuit_state = "OPEN"

    return {
        "health_status": _normalize_status(health_status, default="HEALTHY"),
        "rate_limited": _is_truthy(rate_limited),
        "timeout_triggered": _is_truthy(timeout_triggered),
        "configured_failure_class": _normalize_status(failure_class, default="NONE"),
        "configured_failure_reason": (failure_reason or "").strip()[:160],
        "circuit_state": normalized_circuit_state,
        "circuit_open": circuit_open_enabled,
        "timeout_ms": timeout_ms,
        "retry_max_attempts": retry_max_attempts,
        "retry_backoff_ms": retry_backoff_ms,
        "rate_limit_retry_after_seconds": rate_limit_retry_after_seconds,
        "env_refs": {
            "health": health_env,
            "rate_limit": rate_limit_env,
            "timeout": timeout_env,
            "failure_class": failure_class_env,
            "failure_reason": failure_reason_env,
            "circuit_state": circuit_state_env,
            "circuit_open": circuit_open_env,
            "timeout_ms": timeout_ms_env,
            "retry_max_attempts": retry_max_attempts_env,
            "retry_backoff_ms": retry_backoff_ms_env,
            "rate_limit_retry_after_seconds": rate_limit_retry_after_env,
        },
    }


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
                reliability=_build_family_reliability_config(env, family),
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


def _credential_redaction_audit(family_config: ProviderAdapterFamilyConfig) -> dict[str, Any]:
    credential_metadata = _credential_metadata(family_config)
    return {
        "family": family_config.family,
        "credential_presence_checked": True,
        "credential_present": bool(credential_metadata["credential_present"]),
        "present_env_vars": list(credential_metadata["present_env_vars"]),
        "checked_env_vars": list(credential_metadata["checked_env_vars"]),
        "redaction": credential_metadata["redaction"],
        "plaintext_persisted": False,
        "plaintext_output_enabled": False,
        "audit_event": f"{family_config.family}.credential_presence_redacted",
    }


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _family_reliability_readback(family_config: ProviderAdapterFamilyConfig) -> tuple[dict[str, Any], list[str]]:
    reliability = dict(family_config.reliability)
    health_status = str(reliability.get("health_status", "HEALTHY"))
    rate_limited = bool(reliability.get("rate_limited", False))
    timeout_triggered = bool(reliability.get("timeout_triggered", False))
    configured_failure_class = str(reliability.get("configured_failure_class", "NONE"))
    configured_failure_active = configured_failure_class not in _NO_FAILURE_STATES
    circuit_state = str(reliability.get("circuit_state", "CLOSED"))
    circuit_open = bool(reliability.get("circuit_open", False)) or circuit_state in _CIRCUIT_BLOCKING_STATES

    blocked_reasons: list[str] = []
    failure_class = "NONE"
    failure_reason = ""
    retryable = False

    if health_status in _HEALTH_BLOCKING_STATES:
        blocked_reasons.append("provider_health_unhealthy_fail_closed")
        failure_class = "UNHEALTHY"
        failure_reason = "health_check_unhealthy"
    if rate_limited:
        blocked_reasons.append("provider_rate_limited_fail_closed")
        failure_class = "RATE_LIMITED"
        failure_reason = "rate_limit_signal_present"
        retryable = True
    if timeout_triggered:
        blocked_reasons.append("provider_timeout_fail_closed")
        failure_class = "TIMEOUT"
        failure_reason = "timeout_signal_present"
        retryable = True
    if circuit_open:
        blocked_reasons.append("provider_circuit_open_fail_closed")
        failure_class = "CIRCUIT_OPEN"
        failure_reason = "circuit_breaker_open"
    if configured_failure_active:
        blocked_reasons.append("provider_failure_taxonomy_fail_closed")
        failure_class = configured_failure_class
        failure_reason = str(reliability.get("configured_failure_reason", "")) or "configured_provider_failure"

    blocked_reasons = _dedupe(blocked_reasons)
    suspended = bool(blocked_reasons)
    reliability_state = PROVIDER_RELIABILITY_SUSPENDED if suspended else PROVIDER_RELIABILITY_APPROVAL_READY
    if not suspended:
        failure_class = "NONE"
        failure_reason = ""

    retry_max_attempts = int(reliability.get("retry_max_attempts", _DEFAULT_RETRY_MAX_ATTEMPTS))
    retry_backoff_ms = int(reliability.get("retry_backoff_ms", _DEFAULT_RETRY_BACKOFF_MS))
    timeout_ms = int(reliability.get("timeout_ms", _DEFAULT_TIMEOUT_MS))
    rate_limit_retry_after_seconds = int(reliability.get("rate_limit_retry_after_seconds", 0))

    readback = {
        "family": family_config.family,
        "reliability_state": reliability_state,
        "provider_adapter_suspended": suspended,
        "health_check": {
            "enabled": True,
            "mode": "READBACK_ONLY",
            "status": health_status,
            "external_probe_enabled": False,
            "real_provider_call_enabled": False,
            "fail_closed_on_unhealthy": True,
        },
        "rate_limit": {
            "enabled": True,
            "state": "RATE_LIMITED" if rate_limited else "OK",
            "rate_limited": rate_limited,
            "retry_after_seconds": rate_limit_retry_after_seconds,
            "live_fallback_allowed": False,
            "fail_closed_when_limited": True,
        },
        "timeout": {
            "enabled": True,
            "state": "TIMEOUT" if timeout_triggered else "OK",
            "timeout_ms": timeout_ms,
            "timeout_triggered": timeout_triggered,
            "live_fallback_allowed": False,
            "fail_closed_on_timeout": True,
        },
        "retry": {
            "policy_visible": True,
            "max_attempts": retry_max_attempts,
            "backoff_ms": retry_backoff_ms,
            "retryable": retryable,
            "real_retry_execution_enabled": False,
            "provider_call_enabled": False,
        },
        "failure_taxonomy": {
            "failure_class": failure_class,
            "failure_reason": failure_reason,
            "retryable": retryable,
            "fail_closed": suspended,
            "no_silent_live_fallback": True,
        },
        "circuit_breaker": {
            "enabled": True,
            "state": "OPEN" if circuit_open else circuit_state,
            "open": circuit_open,
            "failure_threshold": 1,
            "half_open_probe_enabled": False,
            "live_fallback_allowed": False,
            "fail_closed_when_open": True,
        },
        "fallback_policy": {
            "policy": "SUSPEND_OR_BLOCK_NO_LIVE_FALLBACK",
            "fallback_state": PROVIDER_RELIABILITY_SUSPENDED if suspended else "READBACK_ONLY",
            "live_fallback_allowed": False,
            "sandbox_live_fallback_allowed": False,
            "provider_call_enabled": False,
        },
        "provider_status_readback": {
            "status_record_id": f"PROVIDER_STATUS_{family_config.family.upper()}",
            "readback_state": reliability_state,
            "replayable": True,
            "readback_only": True,
            "external_probe_executed": False,
            "provider_call_executed": False,
            "env_refs": dict(reliability.get("env_refs", {})),
        },
    }
    return readback, blocked_reasons


def _family_summary(
    family_config: ProviderAdapterFamilyConfig,
    *,
    requested_live_mode: bool,
) -> dict[str, Any]:
    reliability, reliability_blocked_reasons = _family_reliability_readback(family_config)
    blocked_reasons = [
        f"{family_config.family}_sandbox_dry_run_readback_only",
        PROVIDER_BLOCKED_REAL_CALL_REASON,
        "approval_and_audit_required_before_any_live_provider_use",
    ] + reliability_blocked_reasons
    if requested_live_mode:
        blocked_reasons.append(PROVIDER_BLOCKED_LIVE_REASON)
    blocked_reasons = _dedupe(blocked_reasons)

    suspended = bool(reliability.get("provider_adapter_suspended", False))

    return {
        "family": family_config.family,
        "provider_id": family_config.provider_id,
        "configured_provider_id": family_config.configured_provider_id,
        "provider_env": family_config.provider_env,
        "readiness_state": PROVIDER_RELIABILITY_SUSPENDED if suspended else "SANDBOX_DRY_RUN_READY",
        "provider_reliability_state": reliability["reliability_state"],
        "provider_adapter_suspended": suspended,
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
        "credential_redaction_audit": _credential_redaction_audit(family_config),
        "provider_reliability": reliability,
        "provider_status_readback": dict(reliability["provider_status_readback"]),
        "provider_circuit_breaker": dict(reliability["circuit_breaker"]),
        "provider_failure_taxonomy": dict(reliability["failure_taxonomy"]),
        "fallback_policy": dict(reliability["fallback_policy"]),
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
    suspended_families = [
        family
        for family, family_summary in family_summaries.items()
        if family_summary.get("provider_adapter_suspended")
    ]
    family_blocked_reasons = [
        reason
        for family_summary in family_summaries.values()
        for reason in list(family_summary.get("blocked_reasons", []))
        if str(reason).startswith("provider_")
    ]
    reliability_state = (
        PROVIDER_RELIABILITY_SUSPENDED if suspended_families else PROVIDER_RELIABILITY_APPROVAL_READY
    )
    circuit_breaker_state = (
        "OPEN"
        if any(
            dict(family_summary.get("provider_circuit_breaker", {})).get("open")
            for family_summary in family_summaries.values()
        )
        else "CLOSED"
    )

    blocked_reasons = [
        PROVIDER_BLOCKED_REAL_CALL_REASON,
        "provider_adapters_readback_only",
        "approval_and_audit_required_before_any_live_provider_use",
        PROVIDER_BLOCKED_REFUND_REASON,
    ] + family_blocked_reasons
    if suspended_families:
        blocked_reasons.append("provider_reliability_suspended_fail_closed")
    if config.requested_live_mode:
        blocked_reasons.append(PROVIDER_BLOCKED_LIVE_REASON)
    blocked_reasons = _dedupe(blocked_reasons)

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
        "capability_state": reliability_state,
        "provider_reliability_state": reliability_state,
        "provider_circuit_breaker_state": circuit_breaker_state,
        "provider_adapter_suspended": bool(suspended_families),
        "provider_adapter_suspended_families": suspended_families,
        "provider_status_replayable": True,
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
        "provider_reliability_summary": {
            "state": reliability_state,
            "capability_state": reliability_state,
            "health_check_visible": True,
            "rate_limit_visible": True,
            "timeout_visible": True,
            "retry_visible": True,
            "failure_taxonomy_visible": True,
            "circuit_breaker_visible": True,
            "credential_redaction_audit_visible": True,
            "replayable_provider_status": True,
            "readback_only": True,
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "live_fallback_allowed": False,
            "no_silent_live_fallback": True,
            "suspended": bool(suspended_families),
            "suspended_families": suspended_families,
            "circuit_breaker_state": circuit_breaker_state,
            "blocked_reasons": blocked_reasons,
        },
        "provider_status_readback": {
            "readback_state": reliability_state,
            "replayable": True,
            "readback_only": True,
            "provider_call_executed": False,
            "families": {
                family: dict(family_summary.get("provider_status_readback", {}))
                for family, family_summary in family_summaries.items()
            },
        },
        "credential_redaction_audit": {
            "credential_presence_checked": True,
            "plaintext_persisted": False,
            "plaintext_output_enabled": False,
            "families": {
                family: dict(family_summary.get("credential_redaction_audit", {}))
                for family, family_summary in family_summaries.items()
            },
        },
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
        "provider_reliability_state": summary.get("provider_reliability_state"),
        "provider_circuit_breaker_state": summary.get("provider_circuit_breaker_state"),
        "provider_adapter_suspended": bool(summary.get("provider_adapter_suspended", False)),
        "provider_adapter_suspended_families": list(summary.get("provider_adapter_suspended_families", [])),
        "provider_status_replayable": bool(summary.get("provider_status_replayable", True)),
        "provider_reliability_summary": dict(summary.get("provider_reliability_summary", {})),
        "provider_status_readback": dict(summary.get("provider_status_readback", {})),
        "provider_credential_redaction_audit": dict(summary.get("credential_redaction_audit", {})),
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
    result["provider_reliability_state"] = summary.get("provider_reliability_state")
    result["provider_circuit_breaker_state"] = summary.get("provider_circuit_breaker_state")
    result["provider_adapter_suspended"] = bool(summary.get("provider_adapter_suspended", False))
    result["provider_reliability_summary"] = dict(summary.get("provider_reliability_summary", {}))
    result["provider_status_readback"] = dict(summary.get("provider_status_readback", {}))
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
    "LOCAL_CONTROLLED_FAKE_CRM_QUOTE_PROVIDER",
    "ProviderAdapterConfig",
    "ProviderAdapterFamilyConfig",
    "attach_provider_adapter_readiness",
    "build_provider_adapter_config_from_env",
    "build_provider_adapter_readiness_summary",
    "provider_adapter_bootstrap_payload",
    "provider_readiness_for_family",
]
