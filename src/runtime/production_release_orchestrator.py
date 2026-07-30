from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit
from uuid import uuid4

from runtime.operational_alert_dispatcher import (
    OperationalAlertConfig,
    OperationalAlertConfigError,
)
from shared.settings import Settings
from shared.utils import utc_now_iso
from storage.db import DatabaseSession, PersistedRecord, build_persisted_at
from storage.sqlalchemy_backend import REQUIRED_STORAGE_SCHEMA_REVISION


PRODUCTION_RELEASE_RECORD_TYPE = "production_release_window"
PRODUCTION_RELEASE_MODE_DISABLED = "DISABLED"
PRODUCTION_RELEASE_MODE_CANARY = "CANARY"
PRODUCTION_RELEASE_MODE_LIVE = "LIVE"
PRODUCTION_RELEASE_STATE_NOT_CONFIGURED = "NOT_CONFIGURED"
PRODUCTION_RELEASE_STATE_BLOCKED = "BLOCKED"
PRODUCTION_RELEASE_STATE_READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
PRODUCTION_RELEASE_STATE_PENDING_APPROVAL = "PENDING_APPROVAL"
PRODUCTION_RELEASE_STATE_ACTIVE = "ACTIVE"
PRODUCTION_RELEASE_STATE_SUSPENDED = "SUSPENDED"
PRODUCTION_RELEASE_STATE_EXPIRED = "EXPIRED"

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})
_APPROVER_ROLES = frozenset({"reviewer"})
_REQUESTER_ROLES = frozenset({"owner", "admin"})
_SUSPEND_ROLES = frozenset({"owner", "reviewer", "admin"})
_LIVE_PROVIDER_STATES = frozenset({"LIVE_READY"})
_ACTIVE_WINDOW_STATES = frozenset(
    {
        PRODUCTION_RELEASE_STATE_ACTIVE,
        "APPROVED",
    }
)


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in _TRUTHY


def _optional(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _utc_datetime(value: str, *, field_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _now_utc(now: datetime | None = None) -> datetime:
    resolved = now or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        raise ValueError("now must include a timezone")
    return resolved.astimezone(timezone.utc)


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json_file(path: Path, *, max_bytes: int) -> dict[str, Any]:
    if not path.is_absolute() or not path.is_file() or path.is_symlink():
        raise ValueError("evidence path must be an absolute regular file")
    if path.stat().st_size <= 0 or path.stat().st_size > max_bytes:
        raise ValueError("evidence file size is invalid")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("evidence file is unreadable or invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("evidence file must contain a JSON object")
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        normalized = str(item or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _serialized_session_key(session: Any, lock_key: str) -> Any:
    factory = getattr(session, "serialized_key", None)
    return factory(lock_key) if callable(factory) else nullcontext(session)


@dataclass(frozen=True)
class ProductionReleaseConfig:
    enabled: bool
    mode: str
    release_id: str
    release_version: str
    tenant_id: str
    public_base_url: str
    window_start_at: str
    window_end_at: str
    canary_customer_limit: int
    customer_visible_enabled: bool
    payment_enabled: bool
    delivery_enabled: bool
    refund_enabled: bool
    automated_refund_enabled: bool
    kill_switch_enabled: bool
    customer_portal_signing_key_file: str | None
    payment_secret_key_file: str | None
    payment_webhook_secret_file: str | None
    backup_manifest_ref: str | None
    restore_report_ref: str | None
    rollback_ref: str | None
    alert_dispatch_required: bool
    payment_provider_account_id: str | None = None
    payment_provider_probe_ref: str | None = None
    provider_evidence_signing_key_file: str | None = None

    @classmethod
    def from_env(
        cls,
        environ: Mapping[str, str] | None = None,
        *,
        settings: Settings | None = None,
    ) -> "ProductionReleaseConfig":
        env = environ if environ is not None else os.environ
        resolved_settings = settings or Settings.from_env()
        mode = str(env.get("KAKA_PRODUCTION_RELEASE_MODE") or PRODUCTION_RELEASE_MODE_DISABLED)
        mode = mode.strip().upper().replace("-", "_")
        if mode not in {
            PRODUCTION_RELEASE_MODE_DISABLED,
            PRODUCTION_RELEASE_MODE_CANARY,
            PRODUCTION_RELEASE_MODE_LIVE,
        }:
            raise ValueError("KAKA_PRODUCTION_RELEASE_MODE must be DISABLED, CANARY, or LIVE")
        release_id = str(env.get("KAKA_PRODUCTION_RELEASE_ID") or "production-release-unconfigured")
        release_version = str(env.get("KAKA_PRODUCTION_RELEASE_VERSION") or "unconfigured")
        tenant_id = str(
            env.get("KAKA_PRODUCTION_RELEASE_TENANT_ID")
            or resolved_settings.deployment_tenant_id_optional
            or ""
        )
        public_base_url = str(env.get("KAKA_PUBLIC_BASE_URL") or "").strip().rstrip("/")
        start_at = str(env.get("KAKA_PRODUCTION_RELEASE_WINDOW_START_AT") or "")
        end_at = str(env.get("KAKA_PRODUCTION_RELEASE_WINDOW_END_AT") or "")
        try:
            canary_limit = int(env.get("KAKA_PRODUCTION_CANARY_CUSTOMER_LIMIT") or "1")
        except ValueError as exc:
            raise ValueError("KAKA_PRODUCTION_CANARY_CUSTOMER_LIMIT must be an integer") from exc
        if canary_limit < 1 or canary_limit > 100:
            raise ValueError("KAKA_PRODUCTION_CANARY_CUSTOMER_LIMIT must be between 1 and 100")
        return cls(
            enabled=_truthy(
                env.get("KAKA_PRODUCTION_RELEASE_ENABLED"),
                default=mode != PRODUCTION_RELEASE_MODE_DISABLED,
            ),
            mode=mode,
            release_id=release_id.strip(),
            release_version=release_version.strip(),
            tenant_id=tenant_id.strip(),
            public_base_url=public_base_url,
            window_start_at=start_at.strip(),
            window_end_at=end_at.strip(),
            canary_customer_limit=canary_limit,
            customer_visible_enabled=_truthy(
                env.get("KAKA_PRODUCTION_CUSTOMER_VISIBLE_ENABLED")
            ),
            payment_enabled=_truthy(env.get("KAKA_PRODUCTION_PAYMENT_ENABLED")),
            delivery_enabled=_truthy(env.get("KAKA_PRODUCTION_DELIVERY_ENABLED")),
            refund_enabled=_truthy(env.get("KAKA_PRODUCTION_REFUND_ENABLED")),
            automated_refund_enabled=_truthy(
                env.get("KAKA_PRODUCTION_AUTOMATED_REFUND_ENABLED")
            ),
            kill_switch_enabled=_truthy(env.get("KAKA_PRODUCTION_KILL_SWITCH")),
            customer_portal_signing_key_file=_optional(
                env.get("KAKA_CUSTOMER_PORTAL_SIGNING_KEY_FILE")
            ),
            payment_secret_key_file=_optional(env.get("KAKA_STRIPE_SECRET_KEY_FILE")),
            payment_webhook_secret_file=_optional(
                env.get("KAKA_STRIPE_WEBHOOK_SECRET_FILE")
            ),
            backup_manifest_ref=_optional(
                env.get("KAKA_PRODUCTION_BACKUP_MANIFEST_REF")
            ),
            restore_report_ref=_optional(
                env.get("KAKA_PRODUCTION_RESTORE_REPORT_REF")
            ),
            rollback_ref=_optional(env.get("KAKA_PRODUCTION_ROLLBACK_REF")),
            alert_dispatch_required=_truthy(
                env.get("KAKA_PRODUCTION_ALERT_DISPATCH_REQUIRED"),
                default=True,
            ),
            payment_provider_account_id=_optional(
                env.get("KAKA_STRIPE_ACCOUNT_ID")
            ),
            payment_provider_probe_ref=_optional(
                env.get("KAKA_PRODUCTION_PAYMENT_PROVIDER_PROBE_FILE")
            ),
            provider_evidence_signing_key_file=_optional(
                env.get("KAKA_PROVIDER_LIVE_EVIDENCE_SIGNING_KEY_FILE")
            ),
        )

    def capability_flags(self) -> dict[str, bool]:
        return {
            "customer_visible": self.customer_visible_enabled,
            "payment": self.payment_enabled,
            "delivery": self.delivery_enabled,
            "refund": self.refund_enabled,
        }

    def fingerprint_payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "release_id": self.release_id,
            "release_version": self.release_version,
            "tenant_id": self.tenant_id,
            "public_base_url": self.public_base_url,
            "window_start_at": self.window_start_at,
            "window_end_at": self.window_end_at,
            "canary_customer_limit": self.canary_customer_limit,
            "capabilities": self.capability_flags(),
            "automated_refund_enabled": self.automated_refund_enabled,
            "backup_manifest_ref": self.backup_manifest_ref,
            "restore_report_ref": self.restore_report_ref,
            "rollback_ref": self.rollback_ref,
            "alert_dispatch_required": self.alert_dispatch_required,
            "payment_provider_account_id": self.payment_provider_account_id,
            "payment_provider_probe_ref": self.payment_provider_probe_ref,
        }

    @property
    def fingerprint_sha256(self) -> str:
        return _canonical_sha256(self.fingerprint_payload())


def production_alert_dispatch_readiness(
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else os.environ
    try:
        config = OperationalAlertConfig.from_env() if environ is None else _alert_config_from_mapping(env)
    except (OperationalAlertConfigError, ValueError, OSError) as exc:
        return {
            "ready": False,
            "state": "NOT_CONFIGURED",
            "blocked_reasons": [f"alert_dispatch_not_ready:{type(exc).__name__}"],
            "external_dispatch_configured": False,
        }
    status_path_value = str(env.get("KAKA_ALERT_DISPATCHER_STATUS_PATH") or "").strip()
    test_event_id = str(env.get("KAKA_PRODUCTION_ALERT_TEST_EVENT_ID") or "").strip()
    test_evidence_path_value = str(
        env.get("KAKA_PRODUCTION_ALERT_TEST_EVIDENCE_FILE") or ""
    ).strip()
    try:
        max_age_seconds = int(
            env.get("KAKA_ALERT_DISPATCHER_STATUS_MAX_AGE_SECONDS") or "120"
        )
    except ValueError:
        max_age_seconds = 0
    runtime_reasons: list[str] = []
    status: dict[str, Any] = {}
    test_evidence: dict[str, Any] = {}
    test_evidence_sha256 = ""
    if test_evidence_path_value:
        try:
            test_evidence_path = Path(test_evidence_path_value)
            test_evidence = _read_json_file(
                test_evidence_path,
                max_bytes=64 * 1024,
            )
            test_evidence_sha256 = hashlib.sha256(
                test_evidence_path.read_bytes()
            ).hexdigest()
        except (OSError, ValueError):
            runtime_reasons.append("production_alert_test_evidence_unreadable")
        else:
            if int(test_evidence.get("evidence_version") or 0) != 1:
                runtime_reasons.append("production_alert_test_evidence_version_invalid")
            evidence_event_id = str(test_evidence.get("event_id") or "").strip()
            if not re.fullmatch(r"OPSEVT-[a-f0-9]{32}", evidence_event_id):
                runtime_reasons.append("production_alert_test_evidence_event_id_invalid")
            elif test_event_id and test_event_id != evidence_event_id:
                runtime_reasons.append("production_alert_test_evidence_event_id_mismatch")
            else:
                test_event_id = evidence_event_id
    elif not test_event_id:
        runtime_reasons.append("production_alert_test_evidence_missing")
    if not status_path_value:
        runtime_reasons.append("alert_dispatcher_status_path_missing")
    else:
        try:
            status = _read_json_file(Path(status_path_value), max_bytes=1024 * 1024)
        except (OSError, ValueError):
            runtime_reasons.append("alert_dispatcher_status_unreadable")
    completed_at = status.get("completed_at_unix_seconds")
    try:
        status_age_seconds = max(time.time() - float(completed_at), 0.0)
    except (TypeError, ValueError):
        status_age_seconds = None
    if status and str(status.get("state") or "") != "DISPATCH_COMPLETED":
        runtime_reasons.append("alert_dispatcher_not_healthy")
    if (
        status_age_seconds is None
        or max_age_seconds < 30
        or max_age_seconds > 600
        or status_age_seconds > max_age_seconds
    ):
        runtime_reasons.append("alert_dispatcher_status_stale")
    delivered_test_event = False
    if not test_event_id:
        runtime_reasons.append("production_alert_test_event_id_missing")
    else:
        try:
            state = _read_json_file(config.state_path, max_bytes=8 * 1024 * 1024)
        except (OSError, ValueError):
            runtime_reasons.append("alert_dispatcher_state_unreadable")
        else:
            delivered_test_event = test_event_id in {
                str(item)
                for item in list(state.get("delivered_event_ids") or [])
            }
            if not delivered_test_event:
                runtime_reasons.append("production_alert_test_event_not_delivered")
    ready = not runtime_reasons
    return {
        **config.readiness(),
        "ready": ready,
        "state": "READY" if ready else "RUNTIME_NOT_READY",
        "blocked_reasons": sorted(set(runtime_reasons)),
        "external_dispatch_configured": True,
        "dispatcher_runtime_fresh": bool(status_age_seconds is not None and ready),
        "dispatcher_status_age_seconds": status_age_seconds,
        "production_alert_test_event_id": test_event_id or None,
        "production_alert_test_event_delivered": delivered_test_event,
        "production_alert_test_evidence_file_configured": bool(
            test_evidence_path_value
        ),
        "production_alert_test_evidence_sha256": (
            test_evidence_sha256 or None
        ),
    }


def _alert_config_from_mapping(environ: Mapping[str, str]) -> OperationalAlertConfig:
    names = (
        "KAKA_OBSERVABILITY_EVENT_PATH",
        "KAKA_ALERT_WEBHOOK_URL",
        "KAKA_ALERT_ALLOWED_HOSTS",
        "KAKA_ALERT_SIGNING_SECRET_FILE",
        "KAKA_ALERT_STATE_PATH",
        "KAKA_ALERT_DEAD_LETTER_PATH",
        "KAKA_CONTROLLED_EGRESS_PROXY_URL",
        "KAKA_PRIVATE_EDGE_REQUIRED",
    )
    original: dict[str, str | None] = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            if name in environ:
                os.environ[name] = str(environ[name])
            else:
                os.environ.pop(name, None)
        return OperationalAlertConfig.from_env()
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _secret_file_readiness(path_value: str | None, *, name: str) -> dict[str, Any]:
    if not path_value:
        return {
            "ready": False,
            "configured": False,
            "blocked_reason": f"{name}_secret_file_missing",
        }
    path = Path(path_value)
    if not path.is_file():
        return {
            "ready": False,
            "configured": True,
            "blocked_reason": f"{name}_secret_file_unreadable",
        }
    try:
        secret = path.read_bytes().strip()
    except OSError:
        return {
            "ready": False,
            "configured": True,
            "blocked_reason": f"{name}_secret_file_unreadable",
        }
    if len(secret) < 32 or len(secret) > 4096:
        return {
            "ready": False,
            "configured": True,
            "blocked_reason": f"{name}_secret_length_invalid",
        }
    return {
        "ready": True,
        "configured": True,
        "blocked_reason": "",
        "sha256": hashlib.sha256(secret).hexdigest(),
        "plaintext_exposed": False,
    }


def _secret_file_prefix_ready(path_value: str | None, *, prefix: bytes) -> bool:
    if not path_value:
        return False
    try:
        value = Path(path_value).read_bytes().strip()
    except OSError:
        return False
    return value.startswith(prefix)


def production_recovery_evidence_readiness(
    *,
    config: ProductionReleaseConfig,
    settings: Settings,
) -> dict[str, Any]:
    reasons: list[str] = []
    backup: dict[str, Any] = {}
    restore: dict[str, Any] = {}
    rollback: dict[str, Any] = {}
    backup_hash = restore_hash = rollback_hash = ""
    backup_path = Path(config.backup_manifest_ref or "")
    if not config.backup_manifest_ref:
        reasons.append("validated_backup_manifest_ref_missing")
    else:
        try:
            from runtime.private_pilot_backup import validate_private_pilot_backup

            if backup_path.name != "manifest.json":
                raise ValueError("backup manifest filename must be manifest.json")
            backup = validate_private_pilot_backup(backup_path.parent)
            backup_hash = str(backup.get("manifest_sha256") or "")
        except Exception:
            reasons.append("validated_backup_manifest_invalid")
    expected_tenant = str(settings.deployment_tenant_id_optional or "")
    expected_instance = str(settings.deployment_instance_id_optional or "")
    if backup:
        if (
            str(backup.get("source_tenant_id") or "") != expected_tenant
            or str(backup.get("source_instance_id") or "") != expected_instance
        ):
            reasons.append("backup_manifest_deployment_mismatch")
        if str(backup.get("source_schema_revision") or "") != REQUIRED_STORAGE_SCHEMA_REVISION:
            reasons.append("backup_manifest_schema_revision_mismatch")
        if not bool(dict(backup.get("consistency") or {}).get(
            "operator_writers_paused_acknowledged"
        )):
            reasons.append("backup_manifest_writer_pause_not_acknowledged")
        if not bool(dict(backup.get("rpo") or {}).get("target_met_by_estimate")):
            reasons.append("backup_manifest_rpo_target_not_met")

    restore_path = Path(config.restore_report_ref or "")
    if not config.restore_report_ref:
        reasons.append("validated_restore_report_ref_missing")
    else:
        try:
            restore = _read_json_file(restore_path, max_bytes=1024 * 1024)
            restore_hash = hashlib.sha256(restore_path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            reasons.append("validated_restore_report_invalid")
    if restore:
        if str(restore.get("backup_id") or "") != str(backup.get("backup_id") or ""):
            reasons.append("restore_report_backup_mismatch")
        if str(restore.get("restore_state") or "") != "VALIDATED_ISOLATED_RESTORE":
            reasons.append("restore_report_state_invalid")
        if str(restore.get("restored_schema_revision") or "") != REQUIRED_STORAGE_SCHEMA_REVISION:
            reasons.append("restore_report_schema_revision_mismatch")
        if not bool(restore.get("isolated_target")):
            reasons.append("restore_report_not_isolated")
        if bool(restore.get("active_database_mutated")) or bool(
            restore.get("active_object_storage_mutated")
        ):
            reasons.append("restore_report_active_storage_mutated")
        if not bool(dict(restore.get("rto") or {}).get("target_met")):
            reasons.append("restore_report_rto_target_not_met")

    rollback_path = Path(config.rollback_ref or "")
    if not config.rollback_ref:
        reasons.append("validated_rollback_ref_missing")
    else:
        try:
            rollback = _read_json_file(rollback_path, max_bytes=1024 * 1024)
            rollback_hash = hashlib.sha256(rollback_path.read_bytes()).hexdigest()
        except (OSError, ValueError):
            reasons.append("validated_rollback_report_invalid")
    if rollback:
        if (
            str(rollback.get("tenant_id") or "") != expected_tenant
            or str(rollback.get("instance_id") or "") != expected_instance
        ):
            reasons.append("rollback_report_deployment_mismatch")
        if str(rollback.get("backup_id") or "") != str(backup.get("backup_id") or ""):
            reasons.append("rollback_report_backup_mismatch")
        if str(rollback.get("current_image_tag") or "") != config.release_version:
            reasons.append("rollback_report_release_version_mismatch")
        if not bool(rollback.get("rollback_succeeded")):
            reasons.append("rollback_report_failed")
        if not bool(rollback.get("health_gate_required")):
            reasons.append("rollback_report_health_gate_missing")
        if not bool(rollback.get("production_overlay_used")):
            reasons.append("rollback_report_production_overlay_missing")
        if not bool(rollback.get("post_rollback_readiness_verified")):
            reasons.append("rollback_report_post_readiness_missing")
        if not bool(rollback.get("current_release_restored_after_drill")):
            reasons.append("rollback_report_current_release_not_restored")
    return {
        "ready": not reasons,
        "state": "VALIDATED" if not reasons else "BLOCKED",
        "blocked_reasons": sorted(set(reasons)),
        "backup_id": backup.get("backup_id"),
        "backup_manifest_sha256": backup_hash or None,
        "restore_report_sha256": restore_hash or None,
        "rollback_report_sha256": rollback_hash or None,
        "source_schema_revision": backup.get("source_schema_revision"),
        "restore_state": restore.get("restore_state"),
        "rollback_succeeded": bool(rollback.get("rollback_succeeded")),
        "production_overlay_used": bool(rollback.get("production_overlay_used")),
        "plaintext_evidence_embedded": False,
    }


def production_payment_provider_probe_readiness(
    *,
    config: ProductionReleaseConfig,
    now: datetime | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    evidence: dict[str, Any] = {}
    evidence_sha256 = ""
    signature_verified = False
    expected_account_id = str(config.payment_provider_account_id or "")
    if not re.fullmatch(r"acct_[A-Za-z0-9]{8,64}", expected_account_id):
        reasons.append("stripe_expected_account_id_invalid")
    if not config.payment_provider_probe_ref:
        reasons.append("stripe_account_probe_evidence_missing")
    if not config.provider_evidence_signing_key_file:
        reasons.append("stripe_account_probe_signing_key_missing")
    if not reasons:
        evidence_path = Path(str(config.payment_provider_probe_ref))
        key_path = Path(str(config.provider_evidence_signing_key_file))
        try:
            evidence = _read_json_file(evidence_path, max_bytes=64 * 1024)
            evidence_sha256 = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if (
                not key_path.is_absolute()
                or not key_path.is_file()
                or key_path.is_symlink()
            ):
                raise ValueError("invalid signing key path")
            key = key_path.read_bytes().strip()
            if len(key) < 32 or len(key) > 4096:
                raise ValueError("invalid signing key")
            signed_payload = dict(evidence)
            supplied = str(signed_payload.pop("signature_sha256") or "")
            canonical = json.dumps(
                signed_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected_signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
            signature_verified = bool(
                re.fullmatch(r"[a-f0-9]{64}", supplied)
                and hmac.compare_digest(expected_signature, supplied)
            )
        except (OSError, UnicodeDecodeError, ValueError):
            reasons.append("stripe_account_probe_evidence_unreadable")
    if evidence:
        if int(evidence.get("evidence_version") or 0) != 1:
            reasons.append("stripe_account_probe_evidence_version_invalid")
        if str(evidence.get("probe_id") or "") != "runtime.production_payment_provider_probe.v1":
            reasons.append("stripe_account_probe_id_invalid")
        if str(evidence.get("account_id") or "") != expected_account_id:
            reasons.append("stripe_account_probe_account_mismatch")
        for field_name in ("charges_enabled", "payouts_enabled", "details_submitted"):
            if evidence.get(field_name) is not True:
                reasons.append(f"stripe_account_probe_{field_name}_false")
        try:
            probed_at = _utc_datetime(
                str(evidence.get("probed_at") or ""),
                field_name="Stripe account probe timestamp",
            )
            age_seconds = (
                _now_utc(now) - probed_at
            ).total_seconds()
            if age_seconds < -300 or age_seconds > 24 * 60 * 60:
                raise ValueError("stale")
        except ValueError:
            reasons.append("stripe_account_probe_expired_or_invalid")
    if not signature_verified:
        reasons.append("stripe_account_probe_signature_invalid")
    reasons = sorted(set(reasons))
    return {
        "ready": not reasons,
        "state": "VALIDATED" if not reasons else "BLOCKED",
        "blocked_reasons": reasons,
        "account_id": expected_account_id or None,
        "evidence_sha256": evidence_sha256 or None,
        "signature_verified": signature_verified,
        "charges_enabled": bool(evidence.get("charges_enabled")),
        "payouts_enabled": bool(evidence.get("payouts_enabled")),
        "details_submitted": bool(evidence.get("details_submitted")),
        "plaintext_secret_persisted": False,
    }


def _family_live_ready(
    provider_summary: Mapping[str, Any],
    family: str,
) -> tuple[bool, list[str]]:
    families = provider_summary.get("families")
    family_summary = (
        dict(families.get(family) or {})
        if isinstance(families, Mapping)
        else {}
    )
    ready = bool(family_summary.get("real_provider_call_enabled", False))
    selected = list(family_summary.get("selected_provider_bindings") or [])
    if ready and selected:
        ready = all(
            str(dict(item.get("live_binding_gate") or {}).get("live_binding_readiness_state"))
            in _LIVE_PROVIDER_STATES
            for item in selected
            if isinstance(item, Mapping)
        )
    reasons = _string_list(family_summary.get("blocked_reasons"))
    if not ready and not reasons:
        reasons = [f"{family}_live_provider_not_ready"]
    return ready, reasons


def build_production_release_readiness(
    *,
    config: ProductionReleaseConfig,
    settings: Settings,
    provider_summary: Mapping[str, Any],
    session: DatabaseSession,
    alert_readiness: Mapping[str, Any] | None = None,
    recovery_readiness: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed_at = _now_utc(now)
    tenancy = settings.deployment_tenancy_readiness()
    auth = settings.internal_api_auth_readiness()
    storage = settings.storage_bootstrap_payload()
    alert = dict(alert_readiness or production_alert_dispatch_readiness())
    recovery = dict(
        recovery_readiness
        or production_recovery_evidence_readiness(
            config=config,
            settings=settings,
        )
    )
    payment_provider_probe = production_payment_provider_probe_readiness(
        config=config,
        now=observed_at,
    )
    portal_secret = _secret_file_readiness(
        config.customer_portal_signing_key_file,
        name="customer_portal_signing",
    )
    payment_secret = _secret_file_readiness(
        config.payment_secret_key_file,
        name="payment_provider",
    )
    webhook_secret = _secret_file_readiness(
        config.payment_webhook_secret_file,
        name="payment_webhook",
    )
    technical_blockers: list[str] = []
    warnings: list[str] = []

    if str(settings.environment or "").strip().upper() != "PROD_LIVE_MODE":
        technical_blockers.append("production_environment_mode_required")
    if not config.enabled or config.mode == PRODUCTION_RELEASE_MODE_DISABLED:
        technical_blockers.append("production_release_not_enabled")
    if not _ID_PATTERN.fullmatch(config.release_id):
        technical_blockers.append("production_release_id_invalid")
    if not _ID_PATTERN.fullmatch(config.release_version):
        technical_blockers.append("production_release_version_invalid")
    if not config.tenant_id or config.tenant_id != str(
        settings.deployment_tenant_id_optional or ""
    ):
        technical_blockers.append("production_release_tenant_mismatch")
    if not tenancy.get("private_single_tenant_boundary_ready"):
        technical_blockers.extend(_string_list(tenancy.get("blocking_reasons")))
        if not tenancy.get("blocking_reasons"):
            technical_blockers.append("private_single_tenant_boundary_not_ready")
    if not tenancy.get("private_edge_configuration_ready"):
        technical_blockers.append("production_private_edge_not_ready")
    if not auth.get("token_configured"):
        technical_blockers.append("operator_auth_principal_registry_missing")
    if not auth.get("object_approval_workflow_ready"):
        technical_blockers.append("distinct_requester_reviewer_workflow_not_ready")
    if auth.get("principal_config_source") != "secret_file":
        technical_blockers.append("operator_principals_must_use_secret_file")
    if str(storage.get("active_backend") or "") != "postgresql":
        technical_blockers.append("production_postgresql_required")
    storage_schema_revision = getattr(session, "storage_schema_revision", None)
    storage_schema_revision_ready = (
        storage_schema_revision == REQUIRED_STORAGE_SCHEMA_REVISION
    )
    if not storage_schema_revision_ready:
        technical_blockers.append("production_storage_schema_revision_not_ready")
    if str(storage.get("active_object_storage_backend") or "") != "local-filesystem":
        technical_blockers.append("production_object_storage_not_ready")
    if not bool(recovery.get("ready")):
        technical_blockers.extend(
            _string_list(recovery.get("blocked_reasons"))
            or ["production_recovery_evidence_not_ready"]
        )
    if config.kill_switch_enabled:
        technical_blockers.append("production_kill_switch_enabled")
    if config.automated_refund_enabled:
        technical_blockers.append("production_automated_refund_forbidden")
    if not config.window_start_at or not config.window_end_at:
        technical_blockers.append("production_release_window_missing")
        window_start = window_end = None
    else:
        try:
            window_start = _utc_datetime(
                config.window_start_at,
                field_name="production release window start",
            )
            window_end = _utc_datetime(
                config.window_end_at,
                field_name="production release window end",
            )
        except ValueError:
            technical_blockers.append("production_release_window_invalid")
            window_start = window_end = None
        else:
            if window_end <= window_start:
                technical_blockers.append("production_release_window_order_invalid")
            if window_end <= observed_at:
                technical_blockers.append("production_release_window_expired")
    parsed_public_url = urlsplit(config.public_base_url)
    if (
        parsed_public_url.scheme.lower() != "https"
        or not parsed_public_url.hostname
        or parsed_public_url.username
        or parsed_public_url.password
        or parsed_public_url.query
        or parsed_public_url.fragment
    ):
        technical_blockers.append("production_public_https_base_url_invalid")
    elif str(settings.private_hostname_optional or "").lower() != str(
        parsed_public_url.hostname
    ).lower():
        technical_blockers.append("production_public_hostname_mismatch")

    if config.customer_visible_enabled or config.delivery_enabled:
        if not portal_secret["ready"]:
            technical_blockers.append(str(portal_secret["blocked_reason"]))
        delivery_ready, delivery_reasons = _family_live_ready(
            provider_summary,
            "leadpack_page_delivery",
        )
        if not delivery_ready:
            technical_blockers.extend(delivery_reasons)
    if config.payment_enabled or config.refund_enabled:
        if not payment_secret["ready"]:
            technical_blockers.append(str(payment_secret["blocked_reason"]))
        elif not _secret_file_prefix_ready(
            config.payment_secret_key_file,
            prefix=b"sk_live_",
        ):
            technical_blockers.append("stripe_live_secret_key_required")
        if not webhook_secret["ready"]:
            technical_blockers.append(str(webhook_secret["blocked_reason"]))
        elif not _secret_file_prefix_ready(
            config.payment_webhook_secret_file,
            prefix=b"whsec_",
        ):
            technical_blockers.append("stripe_webhook_secret_format_invalid")
        payment_ready, payment_reasons = _family_live_ready(
            provider_summary,
            "payment_collection",
        )
        if not payment_ready:
            technical_blockers.extend(payment_reasons)
        if not payment_provider_probe["ready"]:
            technical_blockers.extend(
                _string_list(payment_provider_probe.get("blocked_reasons"))
            )
    if config.refund_enabled and not config.payment_enabled:
        technical_blockers.append("refund_requires_payment_capability")
    if config.customer_visible_enabled and not config.delivery_enabled:
        technical_blockers.append("customer_visible_requires_delivery_capability")
    if config.alert_dispatch_required and not bool(alert.get("ready")):
        technical_blockers.extend(
            _string_list(alert.get("blocked_reasons"))
            or ["production_alert_dispatch_not_ready"]
        )

    active_window = _active_release_window(
        session=session,
        config=config,
        now=observed_at,
    )
    technical_blockers = sorted(set(technical_blockers))
    technical_ready = not technical_blockers
    readiness_basis = {
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "technical_blockers": technical_blockers,
        "provider_payment_ready": _family_live_ready(
            provider_summary,
            "payment_collection",
        )[0],
        "provider_delivery_ready": _family_live_ready(
            provider_summary,
            "leadpack_page_delivery",
        )[0],
        "alert_ready": bool(alert.get("ready")),
        "alert_test_event_id": alert.get("production_alert_test_event_id"),
        "alert_test_event_delivered": bool(
            alert.get("production_alert_test_event_delivered")
        ),
        "recovery_ready": bool(recovery.get("ready")),
        "backup_manifest_sha256": recovery.get("backup_manifest_sha256"),
        "restore_report_sha256": recovery.get("restore_report_sha256"),
        "rollback_report_sha256": recovery.get("rollback_report_sha256"),
        "payment_provider_probe_ready": bool(payment_provider_probe.get("ready")),
        "payment_provider_probe_sha256": payment_provider_probe.get(
            "evidence_sha256"
        ),
        "tenancy_ready": bool(tenancy.get("private_single_tenant_boundary_ready")),
        "auth_ready": bool(auth.get("object_approval_workflow_ready")),
        "storage_backend": storage.get("active_backend"),
        "schema_ready": storage_schema_revision_ready,
    }
    readiness_hash = _canonical_sha256(readiness_basis)
    approval_hash_matches = bool(
        active_window.get("active")
        and str(active_window.get("readiness_hash") or "") == readiness_hash
    )
    release_active = technical_ready and approval_hash_matches
    blockers = list(technical_blockers)
    if technical_ready and not release_active:
        blockers.append(
            "production_release_approval_stale"
            if active_window.get("active")
            else "production_release_approval_missing"
        )
    state = (
        PRODUCTION_RELEASE_STATE_ACTIVE
        if release_active
        else PRODUCTION_RELEASE_STATE_READY_FOR_APPROVAL
        if technical_ready
        else PRODUCTION_RELEASE_STATE_NOT_CONFIGURED
        if not config.enabled
        else PRODUCTION_RELEASE_STATE_BLOCKED
    )
    if config.mode == PRODUCTION_RELEASE_MODE_LIVE and config.canary_customer_limit < 10:
        warnings.append("live_mode_customer_limit_is_small")

    return {
        "orchestrator_id": "runtime.production_release_orchestrator.v1",
        "release_id": config.release_id,
        "release_version": config.release_version,
        "tenant_id": config.tenant_id,
        "mode": config.mode,
        "state": state,
        "technical_ready": technical_ready,
        "ready_for_approval": technical_ready,
        "release_active": release_active,
        "customer_visible_allowed": bool(
            release_active and config.customer_visible_enabled
        ),
        "payment_execution_enabled": bool(release_active and config.payment_enabled),
        "delivery_execution_enabled": bool(release_active and config.delivery_enabled),
        "refund_execution_enabled": bool(release_active and config.refund_enabled),
        "automated_refund_enabled": False,
        "public_software_release_allowed": False,
        "customer_artifact_production_release_allowed": bool(
            release_active
            and config.customer_visible_enabled
            and config.delivery_enabled
        ),
        "capabilities": config.capability_flags(),
        "canary_customer_limit": config.canary_customer_limit,
        "window": {
            "start_at": config.window_start_at,
            "end_at": config.window_end_at,
            "currently_open": bool(
                window_start
                and window_end
                and window_start <= observed_at < window_end
            ),
        },
        "active_release_window": active_window,
        "readiness_hash": readiness_hash,
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "blocking_reasons": sorted(set(blockers)),
        "technical_blocking_reasons": technical_blockers,
        "warnings": warnings,
        "tenancy_readiness": tenancy,
        "operator_auth_readiness": auth,
        "provider_readiness": {
            "payment_collection": _family_live_ready(
                provider_summary,
                "payment_collection",
            )[0],
            "leadpack_page_delivery": _family_live_ready(
                provider_summary,
                "leadpack_page_delivery",
            )[0],
        },
        "secret_file_readiness": {
            "customer_portal_signing": portal_secret,
            "payment_provider": payment_secret,
            "payment_webhook": webhook_secret,
        },
        "alert_dispatch_readiness": alert,
        "recovery_evidence_readiness": recovery,
        "payment_provider_probe_readiness": payment_provider_probe,
        "backup_manifest_ref_present": bool(config.backup_manifest_ref),
        "restore_report_ref_present": bool(config.restore_report_ref),
        "rollback_ref_present": bool(config.rollback_ref),
        "storage_schema_revision": storage_schema_revision,
        "required_storage_schema_revision": REQUIRED_STORAGE_SCHEMA_REVISION,
        "storage_schema_revision_ready": storage_schema_revision_ready,
        "kill_switch_enabled": config.kill_switch_enabled,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "fail_closed": not release_active,
    }


def request_production_release(
    *,
    config: ProductionReleaseConfig,
    settings: Settings,
    provider_summary: Mapping[str, Any],
    session: DatabaseSession,
    actor: Mapping[str, Any],
    reason: str,
    evidence_refs: list[str],
    alert_readiness: Mapping[str, Any] | None = None,
    recovery_readiness: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    requester_id, requester_role = _authorized_actor(actor, _REQUESTER_ROLES)
    normalized_reason = reason.strip()
    if len(normalized_reason) < 10 or len(normalized_reason) > 1000:
        raise ValueError("production release request reason must be 10-1000 characters")
    refs = _string_list(evidence_refs)
    if len(refs) < 3:
        raise ValueError("production release request requires at least three evidence refs")
    with _serialized_session_key(
        session,
        f"production-release:{config.release_id}",
    ):
        return _request_production_release_locked(
            config=config,
            settings=settings,
            provider_summary=provider_summary,
            session=session,
            requester_id=requester_id,
            requester_role=requester_role,
            normalized_reason=normalized_reason,
            refs=refs,
            alert_readiness=alert_readiness,
            recovery_readiness=recovery_readiness,
            now=now,
        )


def _request_production_release_locked(
    *,
    config: ProductionReleaseConfig,
    settings: Settings,
    provider_summary: Mapping[str, Any],
    session: DatabaseSession,
    requester_id: str,
    requester_role: str,
    normalized_reason: str,
    refs: list[str],
    alert_readiness: Mapping[str, Any] | None,
    recovery_readiness: Mapping[str, Any] | None,
    now: datetime | None,
) -> dict[str, Any]:
    existing_requests = [
        row
        for row in session.list_records(PRODUCTION_RELEASE_RECORD_TYPE)
        if str(row.payload.get("release_id") or "") == config.release_id
        and str(row.payload.get("tenant_id") or "") == config.tenant_id
        and str(row.payload.get("state") or "")
        in {PRODUCTION_RELEASE_STATE_PENDING_APPROVAL, PRODUCTION_RELEASE_STATE_ACTIVE}
    ]
    if existing_requests:
        raise ValueError("production release already has a pending or active request")
    readiness = build_production_release_readiness(
        config=config,
        settings=settings,
        provider_summary=provider_summary,
        session=session,
        alert_readiness=alert_readiness,
        recovery_readiness=recovery_readiness,
        now=now,
    )
    if not readiness["technical_ready"]:
        raise ValueError(
            "production release technical gates are blocked: "
            + ",".join(readiness["technical_blocking_reasons"])
        )
    request_id = f"PRR-{uuid4().hex}"
    payload = {
        "request_id": request_id,
        "release_id": config.release_id,
        "release_version": config.release_version,
        "tenant_id": config.tenant_id,
        "state": PRODUCTION_RELEASE_STATE_PENDING_APPROVAL,
        "requester_id": requester_id,
        "requester_role": requester_role,
        "approver_id": None,
        "approver_role": None,
        "reason": normalized_reason,
        "evidence_refs": refs,
        "readiness_hash": readiness["readiness_hash"],
        "config_fingerprint_sha256": config.fingerprint_sha256,
        "capabilities": config.capability_flags(),
        "window": dict(readiness["window"]),
        "canary_customer_limit": config.canary_customer_limit,
        "requested_at": utc_now_iso(),
        "approved_at": None,
        "suspended_at": None,
        "suspension_reason": None,
        "audit_refs": [
            f"production_release_request:{request_id}",
            *refs,
        ],
        "automated_refund_enabled": False,
        "public_software_release_allowed": False,
    }
    _save_runtime_record(
        session=session,
        record_id=request_id,
        payload=payload,
        governed_state={
            "state": payload["state"],
            "release_id": config.release_id,
            "config_fingerprint_sha256": config.fingerprint_sha256,
        },
        audit_refs={"request_audit_ref": f"production_release_request:{request_id}"},
    )
    return {
        **payload,
        "technical_readiness": readiness,
    }


def approve_production_release(
    *,
    request_id: str,
    expected_readiness_hash: str,
    config: ProductionReleaseConfig,
    settings: Settings,
    provider_summary: Mapping[str, Any],
    session: DatabaseSession,
    actor: Mapping[str, Any],
    approval_note: str,
    alert_readiness: Mapping[str, Any] | None = None,
    recovery_readiness: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    approver_id, approver_role = _authorized_actor(actor, _APPROVER_ROLES)
    with _serialized_session_key(
        session,
        f"production-release:{config.release_id}",
    ):
        return _approve_production_release_locked(
            request_id=request_id,
            expected_readiness_hash=expected_readiness_hash,
            config=config,
            settings=settings,
            provider_summary=provider_summary,
            session=session,
            approver_id=approver_id,
            approver_role=approver_role,
            approval_note=approval_note,
            alert_readiness=alert_readiness,
            recovery_readiness=recovery_readiness,
            now=now,
        )


def _approve_production_release_locked(
    *,
    request_id: str,
    expected_readiness_hash: str,
    config: ProductionReleaseConfig,
    settings: Settings,
    provider_summary: Mapping[str, Any],
    session: DatabaseSession,
    approver_id: str,
    approver_role: str,
    approval_note: str,
    alert_readiness: Mapping[str, Any] | None,
    recovery_readiness: Mapping[str, Any] | None,
    now: datetime | None,
) -> dict[str, Any]:
    record = session.get_record(PRODUCTION_RELEASE_RECORD_TYPE, request_id)
    if record is None:
        raise ValueError("production release request not found")
    payload = dict(record.payload)
    if payload.get("state") != PRODUCTION_RELEASE_STATE_PENDING_APPROVAL:
        raise ValueError("production release request is not pending approval")
    if str(payload.get("requester_id") or "") == approver_id:
        raise ValueError("production release approver must differ from requester")
    if str(payload.get("config_fingerprint_sha256") or "") != config.fingerprint_sha256:
        raise ValueError("production release configuration changed after request")
    readiness = build_production_release_readiness(
        config=config,
        settings=settings,
        provider_summary=provider_summary,
        session=session,
        alert_readiness=alert_readiness,
        recovery_readiness=recovery_readiness,
        now=now,
    )
    if not readiness["technical_ready"]:
        raise ValueError("production release technical gates changed to blocked")
    if (
        str(payload.get("readiness_hash") or "") != expected_readiness_hash
        or readiness["readiness_hash"] != expected_readiness_hash
    ):
        raise ValueError("production release readiness hash changed")
    note = approval_note.strip()
    if len(note) < 10 or len(note) > 1000:
        raise ValueError("production release approval note must be 10-1000 characters")
    payload.update(
        {
            "state": PRODUCTION_RELEASE_STATE_ACTIVE,
            "approver_id": approver_id,
            "approver_role": approver_role,
            "approval_note": note,
            "approved_at": utc_now_iso(),
            "audit_refs": [
                *_string_list(payload.get("audit_refs")),
                f"production_release_approval:{request_id}:{approver_id}",
            ],
        }
    )
    _save_runtime_record(
        session=session,
        record_id=request_id,
        payload=payload,
        governed_state={
            "state": payload["state"],
            "release_id": config.release_id,
            "config_fingerprint_sha256": config.fingerprint_sha256,
        },
        audit_refs={
            "request_audit_ref": f"production_release_request:{request_id}",
            "approval_audit_ref": f"production_release_approval:{request_id}:{approver_id}",
        },
    )
    return {
        **payload,
        "technical_readiness": readiness,
    }


def suspend_production_release(
    *,
    request_id: str,
    session: DatabaseSession,
    actor: Mapping[str, Any],
    reason: str,
) -> dict[str, Any]:
    actor_id, actor_role = _authorized_actor(actor, _SUSPEND_ROLES)
    release_key = request_id
    existing = session.get_record(PRODUCTION_RELEASE_RECORD_TYPE, request_id)
    if existing is not None:
        release_key = str(existing.payload.get("release_id") or request_id)
    with _serialized_session_key(
        session,
        f"production-release:{release_key}",
    ):
        return _suspend_production_release_locked(
            request_id=request_id,
            session=session,
            actor_id=actor_id,
            actor_role=actor_role,
            reason=reason,
        )


def _suspend_production_release_locked(
    *,
    request_id: str,
    session: DatabaseSession,
    actor_id: str,
    actor_role: str,
    reason: str,
) -> dict[str, Any]:
    record = session.get_record(PRODUCTION_RELEASE_RECORD_TYPE, request_id)
    if record is None:
        raise ValueError("production release request not found")
    payload = dict(record.payload)
    if str(payload.get("state") or "") not in _ACTIVE_WINDOW_STATES:
        raise ValueError("only an active production release can be suspended")
    normalized_reason = reason.strip()
    if len(normalized_reason) < 10 or len(normalized_reason) > 1000:
        raise ValueError("production release suspension reason must be 10-1000 characters")
    payload.update(
        {
            "state": PRODUCTION_RELEASE_STATE_SUSPENDED,
            "suspended_at": utc_now_iso(),
            "suspended_by": actor_id,
            "suspended_by_role": actor_role,
            "suspension_reason": normalized_reason,
            "audit_refs": [
                *_string_list(payload.get("audit_refs")),
                f"production_release_suspension:{request_id}:{actor_id}",
            ],
        }
    )
    _save_runtime_record(
        session=session,
        record_id=request_id,
        payload=payload,
        governed_state={
            "state": payload["state"],
            "release_id": payload.get("release_id"),
            "config_fingerprint_sha256": payload.get("config_fingerprint_sha256"),
        },
        audit_refs={
            "suspension_audit_ref": f"production_release_suspension:{request_id}:{actor_id}"
        },
    )
    return payload


def _authorized_actor(
    actor: Mapping[str, Any],
    roles: frozenset[str],
) -> tuple[str, str]:
    if not actor.get("authenticated"):
        raise PermissionError("authenticated actor required")
    principal_id = str(actor.get("principal_id") or "").strip()
    role = str(actor.get("role") or "").strip()
    if not principal_id or role not in roles:
        raise PermissionError("actor role is not authorized for production release action")
    return principal_id, role


def require_active_production_release_window(
    *,
    config: ProductionReleaseConfig,
    session: DatabaseSession,
    release_readiness: Mapping[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    if not bool(release_readiness.get("release_active")):
        raise PermissionError("active approved production release window required")
    active = _active_release_window(
        session=session,
        config=config,
        now=_now_utc(now),
    )
    supplied_window = dict(
        release_readiness.get("active_release_window") or {}
    )
    if (
        not active.get("active")
        or str(active.get("request_id") or "")
        != str(supplied_window.get("request_id") or "")
        or str(active.get("readiness_hash") or "")
        != str(release_readiness.get("readiness_hash") or "")
    ):
        raise PermissionError(
            "production release window changed or was suspended before execution"
        )
    return active


def _active_release_window(
    *,
    session: DatabaseSession,
    config: ProductionReleaseConfig,
    now: datetime,
) -> dict[str, Any]:
    rows = sorted(
        session.list_records(PRODUCTION_RELEASE_RECORD_TYPE),
        key=lambda row: str(row.persisted_at),
        reverse=True,
    )
    matching = [
        dict(row.payload)
        for row in rows
        if str(row.payload.get("release_id") or "") == config.release_id
        and str(row.payload.get("tenant_id") or "") == config.tenant_id
    ]
    if not matching:
        return {
            "active": False,
            "state": "MISSING",
            "request_id": None,
            "separation_of_duties_satisfied": False,
        }
    payload = matching[0]
    state = str(payload.get("state") or "")
    if state == PRODUCTION_RELEASE_STATE_SUSPENDED:
        return {
            "active": False,
            "state": state,
            "request_id": payload.get("request_id"),
            "separation_of_duties_satisfied": True,
        }
    try:
        start_at = _utc_datetime(
            str(dict(payload.get("window") or {}).get("start_at") or ""),
            field_name="release window start",
        )
        end_at = _utc_datetime(
            str(dict(payload.get("window") or {}).get("end_at") or ""),
            field_name="release window end",
        )
    except ValueError:
        return {
            "active": False,
            "state": PRODUCTION_RELEASE_STATE_BLOCKED,
            "request_id": payload.get("request_id"),
            "separation_of_duties_satisfied": False,
        }
    if now >= end_at:
        state = PRODUCTION_RELEASE_STATE_EXPIRED
    active = bool(
        state in _ACTIVE_WINDOW_STATES
        and start_at <= now < end_at
        and str(payload.get("config_fingerprint_sha256") or "")
        == config.fingerprint_sha256
        and str(payload.get("requester_id") or "")
        != str(payload.get("approver_id") or "")
    )
    return {
        "active": active,
        "state": state,
        "request_id": payload.get("request_id"),
        "requester_id": payload.get("requester_id"),
        "approver_id": payload.get("approver_id"),
        "separation_of_duties_satisfied": bool(
            payload.get("requester_id")
            and payload.get("approver_id")
            and payload.get("requester_id") != payload.get("approver_id")
        ),
        "readiness_hash": payload.get("readiness_hash"),
        "config_fingerprint_sha256": payload.get("config_fingerprint_sha256"),
        "window": dict(payload.get("window") or {}),
        "audit_refs": _string_list(payload.get("audit_refs")),
    }


def _save_runtime_record(
    *,
    session: DatabaseSession,
    record_id: str,
    payload: Mapping[str, Any],
    governed_state: Mapping[str, Any],
    audit_refs: Mapping[str, str],
) -> PersistedRecord:
    return session.upsert_record(
        PersistedRecord(
            object_type=PRODUCTION_RELEASE_RECORD_TYPE,
            record_id=record_id,
            stage_scope=9,
            project_id=None,
            object_refs={
                "release_id": str(payload.get("release_id") or ""),
                "tenant_id": str(payload.get("tenant_id") or ""),
            },
            decision_states={"state": str(payload.get("state") or "")},
            trace_refs={},
            audit_refs=dict(audit_refs),
            governed_state=dict(governed_state),
            writeback_state={
                "approved_at": payload.get("approved_at"),
                "suspended_at": payload.get("suspended_at"),
            },
            payload=dict(payload),
            persisted_at=build_persisted_at(),
        )
    )


__all__ = [
    "PRODUCTION_RELEASE_MODE_CANARY",
    "PRODUCTION_RELEASE_MODE_DISABLED",
    "PRODUCTION_RELEASE_MODE_LIVE",
    "PRODUCTION_RELEASE_RECORD_TYPE",
    "PRODUCTION_RELEASE_STATE_ACTIVE",
    "PRODUCTION_RELEASE_STATE_BLOCKED",
    "PRODUCTION_RELEASE_STATE_PENDING_APPROVAL",
    "PRODUCTION_RELEASE_STATE_READY_FOR_APPROVAL",
    "PRODUCTION_RELEASE_STATE_SUSPENDED",
    "ProductionReleaseConfig",
    "approve_production_release",
    "build_production_release_readiness",
    "production_alert_dispatch_readiness",
    "production_payment_provider_probe_readiness",
    "production_recovery_evidence_readiness",
    "request_production_release",
    "require_active_production_release_window",
    "suspend_production_release",
]
