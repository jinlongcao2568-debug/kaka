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
PROVIDER_BINDING_MODE = "REAL_PROVIDER_BINDING_READBACK_GATED"
PROVIDER_BINDING_STATE_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
PROVIDER_BINDING_STATE_SUSPENDED = "SUSPENDED"
PROVIDER_BINDING_STATE_CREDENTIAL_MISSING = "CREDENTIAL_MISSING"
PROVIDER_BINDING_STATE_SANDBOX_VERIFIED = "SANDBOX_VERIFIED"

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
            "wecom_robot",
            "sendgrid_email",
            "twilio_sms",
            "twilio_phone",
            "aliyun_sms",
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
            "hubspot_crm",
            "salesforce_crm",
            "quote_provider",
            "internal_quote_engine",
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
            "customer_portal_delivery",
            "signed_url_delivery",
            "s3_delivery",
            "minio_delivery",
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
            "stripe_payment",
            "manual_bank_transfer",
            "alipay_payment",
            "wechat_pay_payment",
        }
    ),
}

_PROVIDER_BINDING_DEFINITIONS: dict[str, tuple[dict[str, Any], ...]] = {
    "sales_outreach": (
        {
            "binding_id": "sales_outreach.wecom_robot",
            "provider_id": "wecom_robot",
            "adapter_family": "wecom_im",
            "provider_kind": "wecom_robot",
            "display_name": "WeCom robot webhook",
            "credential_envs": ("KAKA_WECOM_ROBOT_WEBHOOK_URL", "KAKA_WECOM_ROBOT_SECRET"),
            "callback_secret_envs": ("KAKA_WECOM_ROBOT_CALLBACK_SECRET",),
        },
        {
            "binding_id": "sales_outreach.email_sendgrid",
            "provider_id": "sendgrid_email",
            "adapter_family": "email",
            "provider_kind": "email",
            "display_name": "SendGrid email",
            "credential_envs": ("KAKA_SENDGRID_API_KEY", "KAKA_EMAIL_FROM"),
            "callback_secret_envs": ("KAKA_SENDGRID_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "sales_outreach.sms_twilio",
            "provider_id": "twilio_sms",
            "adapter_family": "sms",
            "provider_kind": "sms",
            "display_name": "Twilio SMS",
            "credential_envs": ("KAKA_TWILIO_ACCOUNT_SID", "KAKA_TWILIO_AUTH_TOKEN", "KAKA_TWILIO_SMS_FROM"),
            "callback_secret_envs": ("KAKA_TWILIO_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "sales_outreach.phone_twilio",
            "provider_id": "twilio_phone",
            "adapter_family": "phone_call",
            "provider_kind": "phone_call",
            "display_name": "Twilio phone call",
            "credential_envs": ("KAKA_TWILIO_ACCOUNT_SID", "KAKA_TWILIO_AUTH_TOKEN", "KAKA_TWILIO_PHONE_FROM"),
            "callback_secret_envs": ("KAKA_TWILIO_WEBHOOK_SECRET",),
        },
    ),
    "crm_quote": (
        {
            "binding_id": "crm_quote.hubspot_crm",
            "provider_id": "hubspot_crm",
            "adapter_family": "crm",
            "provider_kind": "crm",
            "display_name": "HubSpot CRM",
            "credential_envs": ("KAKA_HUBSPOT_PRIVATE_APP_TOKEN",),
            "callback_secret_envs": ("KAKA_HUBSPOT_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "crm_quote.salesforce_crm",
            "provider_id": "salesforce_crm",
            "adapter_family": "crm",
            "provider_kind": "crm",
            "display_name": "Salesforce CRM",
            "credential_envs": ("KAKA_SALESFORCE_CLIENT_ID", "KAKA_SALESFORCE_CLIENT_SECRET"),
            "callback_secret_envs": ("KAKA_SALESFORCE_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "crm_quote.quote_provider",
            "provider_id": "quote_provider",
            "adapter_family": "quote",
            "provider_kind": "quote",
            "display_name": "External quote provider",
            "credential_envs": ("KAKA_QUOTE_PROVIDER_API_KEY",),
            "callback_secret_envs": ("KAKA_QUOTE_PROVIDER_WEBHOOK_SECRET",),
        },
    ),
    "leadpack_page_delivery": (
        {
            "binding_id": "leadpack_page_delivery.customer_portal_delivery",
            "provider_id": "customer_portal_delivery",
            "adapter_family": "customer_portal",
            "provider_kind": "delivery",
            "display_name": "Customer portal delivery",
            "credential_envs": ("KAKA_CUSTOMER_PORTAL_SIGNING_KEY", "KAKA_DELIVERY_BASE_URL"),
            "callback_secret_envs": ("KAKA_DELIVERY_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "leadpack_page_delivery.signed_url_delivery",
            "provider_id": "signed_url_delivery",
            "adapter_family": "signed_url",
            "provider_kind": "delivery",
            "display_name": "Signed URL delivery",
            "credential_envs": ("KAKA_DELIVERY_SIGNING_KEY",),
            "callback_secret_envs": ("KAKA_DELIVERY_WEBHOOK_SECRET",),
        },
    ),
    "payment_collection": (
        {
            "binding_id": "payment_collection.stripe_payment",
            "provider_id": "stripe_payment",
            "adapter_family": "payment_gateway",
            "provider_kind": "payment",
            "display_name": "Stripe payment",
            "credential_envs": ("KAKA_STRIPE_SECRET_KEY",),
            "callback_secret_envs": ("KAKA_STRIPE_WEBHOOK_SECRET",),
        },
        {
            "binding_id": "payment_collection.manual_bank_transfer",
            "provider_id": "manual_bank_transfer",
            "adapter_family": "manual_bank_transfer",
            "provider_kind": "payment",
            "display_name": "Manual bank transfer",
            "credential_envs": ("KAKA_BANK_TRANSFER_ACCOUNT_REF",),
            "callback_secret_envs": (),
        },
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
    binding_controls: Mapping[str, Any]
    binding_statuses: Mapping[str, Any]


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


def _build_family_binding_controls(environ: Mapping[str, str], family: str) -> dict[str, Any]:
    approval_state, approval_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_APPROVAL_STATE",
        global_name="KAKA_PROVIDER_BINDING_APPROVAL_STATE",
    )
    audit_state, audit_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_AUDIT_STATE",
        global_name="KAKA_PROVIDER_BINDING_AUDIT_STATE",
    )
    operator_action_ref, operator_action_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_OPERATOR_ACTION_REF",
        global_name="KAKA_PROVIDER_BINDING_OPERATOR_ACTION_REF",
    )
    sandbox_pass_state, sandbox_pass_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_SANDBOX_PASS_STATE",
        global_name="KAKA_PROVIDER_BINDING_SANDBOX_PASS_STATE",
    )
    callback_validation_state, callback_validation_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CALLBACK_VALIDATION_STATE",
        global_name="KAKA_PROVIDER_BINDING_CALLBACK_VALIDATION_STATE",
    )
    kill_switch_state, kill_switch_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_KILL_SWITCH",
        global_name="KAKA_PROVIDER_BINDING_KILL_SWITCH",
    )
    suspension_state, suspension_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_SUSPENSION_STATE",
        global_name="KAKA_PROVIDER_BINDING_SUSPENSION_STATE",
    )
    credential_rotated_at, credential_rotated_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CREDENTIAL_ROTATED_AT",
        global_name="KAKA_PROVIDER_BINDING_CREDENTIAL_ROTATED_AT",
    )
    credential_rotation_due_at, credential_due_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CREDENTIAL_ROTATION_DUE_AT",
        global_name="KAKA_PROVIDER_BINDING_CREDENTIAL_ROTATION_DUE_AT",
    )
    credential_version_ref, credential_version_env = _read_family_or_global(
        environ,
        family=family,
        suffix="_CREDENTIAL_VERSION_REF",
        global_name="KAKA_PROVIDER_BINDING_CREDENTIAL_VERSION_REF",
    )
    normalized_suspension_state = _normalize_status(suspension_state, default="ACTIVE")
    kill_switch_enabled = _is_truthy(kill_switch_state) or normalized_suspension_state in {
        "SUSPENDED",
        "KILL_SWITCHED",
        "DISABLED",
    }
    return {
        "approval_state": _normalize_status(approval_state, default="MISSING"),
        "audit_state": _normalize_status(audit_state, default="MISSING"),
        "operator_action_ref_present": bool(operator_action_ref),
        "sandbox_pass_state": _normalize_status(sandbox_pass_state, default="NOT_RUN"),
        "callback_validation_state": _normalize_status(callback_validation_state, default="NOT_VALIDATED"),
        "kill_switch_enabled": kill_switch_enabled,
        "suspension_state": "SUSPENDED" if kill_switch_enabled else normalized_suspension_state,
        "credential_rotation": {
            "credential_version_ref_present": bool(credential_version_ref),
            "credential_rotated_at_optional": credential_rotated_at,
            "credential_rotation_due_at_optional": credential_rotation_due_at,
            "plaintext_persisted": False,
        },
        "env_refs": {
            "approval_state": approval_env,
            "audit_state": audit_env,
            "operator_action_ref": operator_action_env,
            "sandbox_pass_state": sandbox_pass_env,
            "callback_validation_state": callback_validation_env,
            "kill_switch": kill_switch_env,
            "suspension_state": suspension_env,
            "credential_rotated_at": credential_rotated_env,
            "credential_rotation_due_at": credential_due_env,
            "credential_version_ref": credential_version_env,
        },
    }


def _build_family_binding_statuses(environ: Mapping[str, str], family: str) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    for definition in _PROVIDER_BINDING_DEFINITIONS.get(family, ()):
        binding_id = str(definition["binding_id"])
        credential_envs = tuple(str(name) for name in definition.get("credential_envs", ()))
        callback_secret_envs = tuple(str(name) for name in definition.get("callback_secret_envs", ()))
        present_credential_envs = tuple(name for name in credential_envs if _read_optional(environ, name))
        present_callback_secret_envs = tuple(name for name in callback_secret_envs if _read_optional(environ, name))
        statuses[binding_id] = {
            "credential_envs": list(credential_envs),
            "present_credential_envs": list(present_credential_envs),
            "callback_secret_envs": list(callback_secret_envs),
            "present_callback_secret_envs": list(present_callback_secret_envs),
            "credential_present": bool(present_credential_envs),
            "callback_secret_present": bool(present_callback_secret_envs) or not callback_secret_envs,
            "redaction": "present-redacted" if present_credential_envs else "absent",
            "callback_secret_redaction": (
                "present-redacted"
                if present_callback_secret_envs
                else ("not-required" if not callback_secret_envs else "absent")
            ),
            "plaintext_persisted": False,
            "plaintext_output_enabled": False,
        }
    return statuses


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
                binding_controls=_build_family_binding_controls(env, family),
                binding_statuses=_build_family_binding_statuses(env, family),
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


def _provider_binding_matrix(
    family_config: ProviderAdapterFamilyConfig,
    *,
    requested_live_mode: bool,
    provider_suspended: bool,
) -> dict[str, Any]:
    controls = dict(family_config.binding_controls)
    statuses = dict(family_config.binding_statuses)
    approval_state = str(controls.get("approval_state", "MISSING"))
    audit_state = str(controls.get("audit_state", "MISSING"))
    sandbox_pass_state = str(controls.get("sandbox_pass_state", "NOT_RUN"))
    callback_validation_state = str(controls.get("callback_validation_state", "NOT_VALIDATED"))
    operator_action_ref_present = bool(controls.get("operator_action_ref_present", False))
    kill_switch_enabled = bool(controls.get("kill_switch_enabled", False))
    family_binding_rows: list[dict[str, Any]] = []
    selected_bindings: list[dict[str, Any]] = []

    for definition in _PROVIDER_BINDING_DEFINITIONS.get(family_config.family, ()):
        binding_id = str(definition["binding_id"])
        provider_id = str(definition["provider_id"])
        status = dict(statuses.get(binding_id, {}))
        selected = provider_id == family_config.provider_id
        credential_envs = list(status.get("credential_envs", definition.get("credential_envs", ())))
        callback_secret_envs = list(
            status.get("callback_secret_envs", definition.get("callback_secret_envs", ()))
        )
        credential_present = bool(status.get("credential_present", False))
        callback_secret_present = bool(status.get("callback_secret_present", not callback_secret_envs))
        sandbox_verified = (
            selected
            and credential_present
            and not provider_suspended
            and not kill_switch_enabled
            and sandbox_pass_state in {"PASSED", "PASS", "SANDBOX_VERIFIED", "VERIFIED"}
        )
        callback_validated = (
            selected
            and callback_secret_present
            and callback_validation_state in {"VALIDATED", "PASSED", "PASS", "VERIFIED"}
        )
        live_prerequisites_satisfied = (
            sandbox_verified
            and callback_validated
            and approval_state in {"APPROVED", "APPROVAL_READY", "SATISFIED"}
            and audit_state in {"APPROVED", "AUDITED", "PRESENT", "SATISFIED"}
            and operator_action_ref_present
        )
        if provider_suspended or kill_switch_enabled:
            binding_state = PROVIDER_BINDING_STATE_SUSPENDED
        elif selected and not credential_present:
            binding_state = PROVIDER_BINDING_STATE_CREDENTIAL_MISSING
        elif sandbox_verified:
            binding_state = PROVIDER_BINDING_STATE_SANDBOX_VERIFIED
        elif selected:
            binding_state = "SELECTED_PENDING_SANDBOX"
        else:
            binding_state = "AVAILABLE_NOT_SELECTED"
        live_binding_readiness_state = (
            "LIVE_READY_GATED"
            if requested_live_mode and live_prerequisites_satisfied
            else PROVIDER_BINDING_STATE_APPROVAL_REQUIRED
        )
        blocked_reasons: list[str] = []
        if selected and not credential_present:
            blocked_reasons.append("credential_missing")
        if selected and not callback_secret_present:
            blocked_reasons.append("callback_secret_missing")
        if selected and sandbox_pass_state not in {"PASSED", "PASS", "SANDBOX_VERIFIED", "VERIFIED"}:
            blocked_reasons.append(f"sandbox_pass_state={sandbox_pass_state}")
        if selected and callback_validation_state not in {"VALIDATED", "PASSED", "PASS", "VERIFIED"}:
            blocked_reasons.append(f"callback_validation_state={callback_validation_state}")
        if selected and approval_state not in {"APPROVED", "APPROVAL_READY", "SATISFIED"}:
            blocked_reasons.append("approval_required")
        if selected and audit_state not in {"APPROVED", "AUDITED", "PRESENT", "SATISFIED"}:
            blocked_reasons.append("audit_required")
        if selected and not operator_action_ref_present:
            blocked_reasons.append("operator_action_required")
        if selected and provider_suspended:
            blocked_reasons.append("provider_reliability_suspended")
        if selected and kill_switch_enabled:
            blocked_reasons.append("provider_kill_switch_enabled")

        row = {
            "binding_id": binding_id,
            "family": family_config.family,
            "provider_id": provider_id,
            "adapter_family": definition.get("adapter_family"),
            "provider_kind": definition.get("provider_kind"),
            "display_name": definition.get("display_name"),
            "selected": selected,
            "binding_state": binding_state,
            "binding_mode": PROVIDER_BINDING_MODE,
            "credential_metadata": {
                "credential_present": credential_present,
                "present_env_vars": list(status.get("present_credential_envs", [])),
                "checked_env_vars": credential_envs,
                "redaction": status.get("redaction", "absent"),
                "plaintext_persisted": False,
                "plaintext_output_enabled": False,
            },
            "credential_rotation": dict(controls.get("credential_rotation", {})),
            "sandbox_call_evidence": {
                "sandbox_call_verified": sandbox_verified,
                "sandbox_pass_state": sandbox_pass_state,
                "provider_network_call_executed": False,
                "controlled_local_handshake_recorded": bool(selected),
                "evidence_id": f"SANDBOX-EVIDENCE-{binding_id.upper().replace('.', '-')}",
                "replayable": True,
            },
            "webhook_callback_validation": {
                "callback_validation_state": callback_validation_state,
                "callback_secret_present": callback_secret_present,
                "present_env_vars": list(status.get("present_callback_secret_envs", [])),
                "checked_env_vars": callback_secret_envs,
                "redaction": status.get("callback_secret_redaction", "absent"),
                "provider_network_callback_received": False,
                "validation_replayable": True,
            },
            "live_binding_gate": {
                "requested_live_mode": requested_live_mode,
                "live_binding_readiness_state": live_binding_readiness_state,
                "approval_state": approval_state,
                "audit_state": audit_state,
                "operator_action_ref_present": operator_action_ref_present,
                "live_provider_call_enabled": False,
                "real_provider_call_enabled": False,
                "no_silent_fallback": True,
                "blocked_reasons": _dedupe(blocked_reasons),
            },
            "kill_switch": {
                "kill_switch_enabled": kill_switch_enabled,
                "suspension_state": controls.get("suspension_state", "ACTIVE"),
                "suspends_live_provider_call": True,
                "resume_requires_manual_review": True,
            },
        }
        family_binding_rows.append(row)
        if selected:
            selected_bindings.append(row)

    coverage = {
        "wecom_robot_provider_binding": any(
            row["provider_id"] == "wecom_robot" for row in family_binding_rows
        ),
        "email_provider_binding": any(
            row["adapter_family"] == "email" for row in family_binding_rows
        ),
        "sms_provider_binding": any(row["adapter_family"] == "sms" for row in family_binding_rows),
        "phone_provider_binding": any(
            row["adapter_family"] == "phone_call" for row in family_binding_rows
        ),
        "crm_provider_binding": any(row["adapter_family"] == "crm" for row in family_binding_rows),
        "quote_provider_binding": any(
            row["adapter_family"] == "quote" for row in family_binding_rows
        ),
        "payment_provider_binding": any(
            row["provider_kind"] == "payment" for row in family_binding_rows
        ),
        "delivery_provider_binding": any(
            row["provider_kind"] == "delivery" for row in family_binding_rows
        ),
    }
    return {
        "family": family_config.family,
        "binding_mode": PROVIDER_BINDING_MODE,
        "selected_provider_id": family_config.provider_id,
        "selected_bindings": selected_bindings,
        "bindings": family_binding_rows,
        "coverage": coverage,
        "binding_controls": {
            "approval_state": approval_state,
            "audit_state": audit_state,
            "operator_action_ref_present": operator_action_ref_present,
            "sandbox_pass_state": sandbox_pass_state,
            "callback_validation_state": callback_validation_state,
            "kill_switch_enabled": kill_switch_enabled,
            "suspension_state": controls.get("suspension_state", "ACTIVE"),
            "env_refs": dict(controls.get("env_refs", {})),
        },
        "provider_call_enabled": False,
        "real_provider_call_enabled": False,
        "live_fallback_allowed": False,
        "automated_refund_enabled": False,
    }


def _family_summary(
    family_config: ProviderAdapterFamilyConfig,
    *,
    requested_live_mode: bool,
) -> dict[str, Any]:
    reliability, reliability_blocked_reasons = _family_reliability_readback(family_config)
    provider_binding_matrix = _provider_binding_matrix(
        family_config,
        requested_live_mode=requested_live_mode,
        provider_suspended=bool(reliability.get("provider_adapter_suspended", False)),
    )
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
        "provider_binding_matrix": provider_binding_matrix,
        "selected_provider_bindings": list(provider_binding_matrix.get("selected_bindings", [])),
        "provider_binding_controls": dict(provider_binding_matrix.get("binding_controls", {})),
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
    provider_binding_coverage = {
        "wecom_robot_provider_binding": False,
        "email_provider_binding": False,
        "sms_provider_binding": False,
        "phone_provider_binding": False,
        "crm_provider_binding": False,
        "quote_provider_binding": False,
        "payment_provider_binding": False,
        "delivery_provider_binding": False,
    }
    selected_provider_bindings: list[dict[str, Any]] = []
    for family_summary in family_summaries.values():
        matrix = dict(family_summary.get("provider_binding_matrix", {}))
        selected_provider_bindings.extend(list(matrix.get("selected_bindings", [])))
        for key, covered in dict(matrix.get("coverage", {})).items():
            if key in provider_binding_coverage:
                provider_binding_coverage[key] = bool(provider_binding_coverage[key] or covered)
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
        "provider_binding_mode": PROVIDER_BINDING_MODE,
        "provider_binding_summary": {
            "binding_mode": PROVIDER_BINDING_MODE,
            "coverage": provider_binding_coverage,
            "selected_provider_bindings": selected_provider_bindings,
            "all_required_product_provider_bindings_registered": all(provider_binding_coverage.values()),
            "sandbox_provider_call_evidence_replayable": True,
            "webhook_callback_validation_replayable": True,
            "credential_redaction_and_rotation_visible": True,
            "kill_switch_and_suspension_visible": True,
            "provider_call_enabled": False,
            "real_provider_call_enabled": False,
            "live_fallback_allowed": False,
            "automated_refund_enabled": False,
        },
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
        "provider_binding_mode": summary.get("provider_binding_mode"),
        "provider_binding_summary": dict(summary.get("provider_binding_summary", {})),
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
    result["provider_binding_mode"] = summary.get("provider_binding_mode")
    result["provider_binding_summary"] = dict(summary.get("provider_binding_summary", {}))
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
    "PROVIDER_BINDING_MODE",
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
