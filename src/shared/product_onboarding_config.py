from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage1_tasking.region_adapters import REGION_SOURCE_ADAPTER_BY_CODE
from storage.db import DatabaseSession, PersistedRecord


PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF = (
    "contracts/governance/product_onboarding_config_contract.json"
)
PROFILE_VERSION_OBJECT_TYPE = "product_onboarding_profile_version"
ACTIVE_POINTER_OBJECT_TYPE = "product_onboarding_active_pointer"
TEST_RUN_OBJECT_TYPE = "product_onboarding_test_run"
AUDIT_OBJECT_TYPE = "product_onboarding_audit"

INDUSTRY_CODE = "CONSTRUCTION_PUBLIC_EVIDENCE"
EVIDENCE_TEMPLATE_ID = "SKU_B_PUBLIC_SOURCE_FOUR_FIELD_RISK_REVIEW"
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_NAME_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,100}$")
_SENSITIVE_RE = re.compile(
    r"(?:api[_ -]?key|access[_ -]?token|authorization|bearer\s+\S+|cookie|password|"
    r"passwd|secret\s*[:=]|private[_ -]?key|身份证|银行卡)",
    re.IGNORECASE,
)
_BUDGET_LIMITS = {
    "discovery_candidate_limit": (1, 30, 10),
    "detail_capture_limit": (0, 10, 3),
    "attachment_capture_limit": (0, 20, 6),
    "job_time_budget_seconds": (60, 1800, 600),
}


class ProductOnboardingAccessError(ValueError):
    pass


class ProductOnboardingInputError(ValueError):
    pass


class ProductOnboardingConflictError(ValueError):
    pass


def mutate_product_onboarding_config(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    actor = _trusted_actor(payload)
    _reject_unknown(
        payload,
        {
            "_internal_auth_context",
            "action",
            "profile_id",
            "expected_version",
            "target_version",
            "profile_name",
            "region_codes",
            "industry_code",
            "evidence_template_id",
            "source_profile_ids",
            "budgets",
        },
    )
    action = str(payload.get("action") or "").strip().upper()
    if action not in {"UPSERT_DRAFT", "ACTIVATE", "ROLLBACK"}:
        raise ProductOnboardingInputError("unsupported onboarding configuration action")
    profile_id = _identifier(payload.get("profile_id"), "profile_id")
    expected_version = _optional_positive_int(payload.get("expected_version"), "expected_version")
    versions = _profile_versions(active_session, actor["tenant_scope_sha256"], profile_id)
    latest = versions[-1] if versions else None
    current_version = int(latest.get("version") or 0) if latest else 0
    if latest is None and expected_version is not None:
        raise ProductOnboardingConflictError("new profile does not accept expected_version")
    if latest is not None and expected_version != current_version:
        raise ProductOnboardingConflictError(
            f"profile version conflict: expected {expected_version}, current {current_version}"
        )

    if action == "UPSERT_DRAFT":
        config = _validate_config(payload)
        next_version = current_version + 1
        profile = _profile_payload(
            actor=actor,
            profile_id=profile_id,
            version=next_version,
            state="DRAFT_VALIDATED",
            config=config,
            previous_version=current_version or None,
        )
        audit_id = _persist_profile_mutation(
            session=active_session,
            actor=actor,
            profile=profile,
            action=action,
            pointer=None,
        )
        return _mutation_response(
            action=action,
            operation_state="DRAFT_CREATED" if latest is None else "DRAFT_VERSIONED",
            profile=profile,
            pointer=_active_pointer(active_session, actor["tenant_scope_sha256"]),
            audit_id=audit_id,
        )

    _reject_config_fields_for_state_action(payload)
    if latest is None:
        raise ProductOnboardingConflictError("profile does not exist")
    if action == "ACTIVATE":
        if str(latest.get("state") or "") != "DRAFT_VALIDATED":
            raise ProductOnboardingConflictError("ACTIVATE requires the latest validated draft")
        if not _passing_test_exists(
            active_session,
            actor["tenant_scope_sha256"],
            profile_id,
            current_version,
            str(latest.get("config_sha256") or ""),
        ):
            raise ProductOnboardingConflictError(
                "ACTIVATE requires a passing offline test for the latest config hash"
            )
        next_version = current_version + 1
        profile = _profile_payload(
            actor=actor,
            profile_id=profile_id,
            version=next_version,
            state="ACTIVE",
            config=dict(latest["config"]),
            previous_version=current_version,
            activated_from_version=current_version,
        )
        pointer = _pointer_payload(actor, profile)
        audit_id = _persist_profile_mutation(
            session=active_session,
            actor=actor,
            profile=profile,
            action=action,
            pointer=pointer,
        )
        return _mutation_response(
            action=action,
            operation_state="ACTIVATED",
            profile=profile,
            pointer=pointer,
            audit_id=audit_id,
        )

    target_version = _optional_positive_int(payload.get("target_version"), "target_version")
    if target_version is None or target_version >= current_version:
        raise ProductOnboardingInputError("ROLLBACK requires an earlier target_version")
    target = next((item for item in versions if int(item["version"]) == target_version), None)
    if target is None or str(target.get("state") or "") not in {"ACTIVE", "ACTIVE_ROLLBACK"}:
        raise ProductOnboardingConflictError("rollback target must be a previously active version")
    next_version = current_version + 1
    profile = _profile_payload(
        actor=actor,
        profile_id=profile_id,
        version=next_version,
        state="ACTIVE_ROLLBACK",
        config=dict(target["config"]),
        previous_version=current_version,
        rolled_back_from_version=current_version,
        rollback_target_version=target_version,
    )
    pointer = _pointer_payload(actor, profile)
    audit_id = _persist_profile_mutation(
        session=active_session,
        actor=actor,
        profile=profile,
        action=action,
        pointer=pointer,
    )
    return _mutation_response(
        action=action,
        operation_state="ROLLED_BACK_AS_NEW_ACTIVE_VERSION",
        profile=profile,
        pointer=pointer,
        audit_id=audit_id,
    )


def list_product_onboarding_configs(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    actor = _trusted_actor(payload)
    _reject_unknown(payload, {"_internal_auth_context", "profile_id", "include_history"})
    profile_id = _optional_identifier(payload.get("profile_id"), "profile_id")
    include_history = payload.get("include_history", False)
    if not isinstance(include_history, bool):
        raise ProductOnboardingInputError("include_history must be a boolean")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in active_session.list_records(PROFILE_VERSION_OBJECT_TYPE):
        value = dict(record.payload)
        if value.get("tenant_scope_sha256") != actor["tenant_scope_sha256"]:
            continue
        if profile_id and value.get("profile_id") != profile_id:
            continue
        grouped.setdefault(str(value["profile_id"]), []).append(value)
    pointer = _active_pointer(active_session, actor["tenant_scope_sha256"])
    profiles: list[dict[str, Any]] = []
    for values in grouped.values():
        values.sort(key=lambda item: int(item.get("version") or 0))
        latest = values[-1]
        item = {
            "profile_id": latest["profile_id"],
            "latest_version": latest["version"],
            "latest_state": latest["state"],
            "latest": _public_profile(latest),
            "active": bool(
                pointer
                and pointer.get("profile_id") == latest["profile_id"]
                and int(pointer.get("active_version") or 0)
                in {int(value.get("version") or 0) for value in values}
            ),
            "active_version": (
                pointer.get("active_version")
                if pointer and pointer.get("profile_id") == latest["profile_id"]
                else None
            ),
        }
        if include_history:
            item["history"] = [_public_profile(value) for value in reversed(values)]
        profiles.append(item)
    profiles.sort(key=lambda item: str(item["profile_id"]))
    return {
        "surface_id": "product_onboarding_config_internal",
        "context": {
            "tenant_scope_sha256": actor["tenant_scope_sha256"],
            "deployment_mode": "PRIVATE_SINGLE_TENANT",
        },
        "profiles": profiles,
        "count": len(profiles),
        "active_profile": _public_pointer(pointer),
        "catalog": product_onboarding_config_catalog(),
        "governance": _governance(),
    }


def run_product_onboarding_offline_test(
    payload: Mapping[str, Any],
    *,
    session: DatabaseSession | None = None,
) -> dict[str, Any]:
    active_session = session or DatabaseSession.default()
    actor = _trusted_actor(payload)
    _reject_unknown(
        payload,
        {"_internal_auth_context", "profile_id", "version", "mode"},
    )
    profile_id = _identifier(payload.get("profile_id"), "profile_id")
    version = _optional_positive_int(payload.get("version"), "version")
    mode = str(payload.get("mode") or "OFFLINE_VALIDATION").strip().upper()
    if mode != "OFFLINE_VALIDATION":
        raise ProductOnboardingInputError("only OFFLINE_VALIDATION test mode is supported")
    versions = _profile_versions(active_session, actor["tenant_scope_sha256"], profile_id)
    if not versions:
        raise ProductOnboardingConflictError("profile does not exist")
    profile = versions[-1]
    if version is not None and int(profile["version"]) != version:
        raise ProductOnboardingConflictError("offline test only accepts the latest version")
    config = _validate_config(dict(profile["config"]), config_only=True)
    projection = _execution_projection(config)
    checks = {
        "registered_regions_only": True,
        "registered_sources_only": True,
        "each_region_has_source": True,
        "budget_bounds_valid": True,
        "fixed_industry_and_template": True,
        "live_and_external_actions_disabled": True,
        "approval_and_source_allowlist_not_overridable": True,
        "task_or_fetch_created": False,
    }
    test_run_id = (
        f"ONBOARDING-TEST-{actor['tenant_scope_sha256'][:12]}-{profile_id}-"
        f"v{profile['version']}-{str(profile['config_sha256'])[:12]}"
    )
    now = utc_now_iso()
    test_run = {
        "test_run_id": test_run_id,
        "tenant_scope_sha256": actor["tenant_scope_sha256"],
        "profile_id": profile_id,
        "version": profile["version"],
        "config_sha256": profile["config_sha256"],
        "test_state": "PASSED",
        "mode": mode,
        "checks": checks,
        "execution_projection": projection,
        "task_created": False,
        "fetch_executed": False,
        "provider_call_executed": False,
        "tested_at": now,
    }
    active_session.upsert_record(
        PersistedRecord(
            object_type=TEST_RUN_OBJECT_TYPE,
            record_id=test_run_id,
            stage_scope=0,
            project_id=None,
            object_refs={"profile_id": profile_id, "tenant_id": actor["tenant_id"]},
            decision_states={"test_state": "PASSED", "mode": mode},
            trace_refs={
                "config_sha256": profile["config_sha256"],
                "contract_ref": PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF,
            },
            audit_refs={
                "actor_principal_id": actor["principal_id"],
                "actor_role": actor["role"],
            },
            governed_state=_fixed_boundary(),
            writeback_state={"formal_fact_writeback": False, "customer_writeback": False},
            payload=copy.deepcopy(test_run),
            persisted_at=now,
        )
    )
    return {
        "surface_id": "product_onboarding_config_internal",
        "test_state": "PASSED",
        "test_run": test_run,
        "profile": _public_profile(profile),
        "execution_projection": projection,
        "checks": checks,
        "governance": _governance(),
    }


def product_onboarding_config_catalog() -> dict[str, Any]:
    regions = []
    for adapter in REGION_SOURCE_ADAPTER_BY_CODE.values():
        allowed = bool(adapter.commercial_pilot_region) or adapter.region_code == "CN-NATIONAL"
        if not allowed or adapter.onboarding_required or not adapter.entry_profile_ids:
            continue
        regions.append(
            {
                "region_code": adapter.region_code,
                "region_name": adapter.region_name,
                "commercial_pilot_region": adapter.commercial_pilot_region,
                "source_quality_state": adapter.source_quality_state,
                "allowed_source_profile_ids": list(
                    dict.fromkeys((*adapter.entry_profile_ids, *adapter.fallback_entry_profile_ids))
                ),
                "default_source_profile_id": adapter.entry_profile_ids[0],
            }
        )
    regions.sort(key=lambda item: (item["region_code"] != "CN-GD", item["region_code"]))
    return {
        "industry_codes": [INDUSTRY_CODE],
        "evidence_template_ids": [EVIDENCE_TEMPLATE_ID],
        "regions": regions,
        "budget_limits": {
            key: {"minimum": value[0], "maximum": value[1], "default": value[2]}
            for key, value in _BUDGET_LIMITS.items()
        },
        "safe_default": {
            "region_codes": ["CN-GD"],
            "industry_code": INDUSTRY_CODE,
            "evidence_template_id": EVIDENCE_TEMPLATE_ID,
            "source_profile_ids": ["GUANGZHOU-YWTB-CONSTRUCTION-LIST"],
            "budgets": {key: value[2] for key, value in _BUDGET_LIMITS.items()},
        },
    }


def _validate_config(payload: Mapping[str, Any], *, config_only: bool = False) -> dict[str, Any]:
    source = dict(payload)
    if config_only:
        allowed = {
            "profile_name",
            "region_codes",
            "industry_code",
            "evidence_template_id",
            "source_profile_ids",
            "budgets",
        }
        if set(source) != allowed:
            raise ProductOnboardingInputError("stored onboarding config fields are invalid")
    profile_name = str(source.get("profile_name") or "").strip()
    if not _NAME_RE.fullmatch(profile_name) or _SENSITIVE_RE.search(profile_name):
        raise ProductOnboardingInputError("profile_name must contain 1-100 safe characters")
    region_values = source.get("region_codes")
    if not isinstance(region_values, list) or not 1 <= len(region_values) <= 3:
        raise ProductOnboardingInputError("region_codes must contain 1-3 items")
    region_codes = [str(item or "").strip().upper() for item in region_values]
    if len(region_codes) != len(set(region_codes)):
        raise ProductOnboardingInputError("region_codes must be unique")
    allowed_by_region: dict[str, set[str]] = {}
    for region_code in region_codes:
        adapter = REGION_SOURCE_ADAPTER_BY_CODE.get(region_code)
        if adapter is None:
            raise ProductOnboardingInputError(f"region is not registered: {region_code}")
        allowed_region = bool(adapter.commercial_pilot_region) or region_code == "CN-NATIONAL"
        if not allowed_region or adapter.onboarding_required or not adapter.entry_profile_ids:
            raise ProductOnboardingInputError(f"region is not enabled for onboarding: {region_code}")
        allowed_by_region[region_code] = set(
            (*adapter.entry_profile_ids, *adapter.fallback_entry_profile_ids)
        )
    industry_code = str(source.get("industry_code") or "").strip().upper()
    if industry_code != INDUSTRY_CODE:
        raise ProductOnboardingInputError("industry_code is outside the fixed MVP product")
    evidence_template_id = str(source.get("evidence_template_id") or "").strip().upper()
    if evidence_template_id != EVIDENCE_TEMPLATE_ID:
        raise ProductOnboardingInputError("evidence_template_id is not registered")
    requested_profiles = source.get("source_profile_ids")
    if requested_profiles in (None, []):
        source_profile_ids = [
            REGION_SOURCE_ADAPTER_BY_CODE[region_code].entry_profile_ids[0]
            for region_code in region_codes
        ]
    elif isinstance(requested_profiles, list) and 1 <= len(requested_profiles) <= 8:
        source_profile_ids = [str(item or "").strip() for item in requested_profiles]
    else:
        raise ProductOnboardingInputError("source_profile_ids must contain 1-8 items")
    if any(not item for item in source_profile_ids) or len(source_profile_ids) != len(
        set(source_profile_ids)
    ):
        raise ProductOnboardingInputError("source_profile_ids must be non-empty and unique")
    allowed_all = set().union(*allowed_by_region.values())
    unknown_sources = sorted(set(source_profile_ids).difference(allowed_all))
    if unknown_sources:
        raise ProductOnboardingInputError(
            "source profile is not allowed for the selected regions: " + ",".join(unknown_sources)
        )
    missing_regions = [
        region_code
        for region_code, allowed in allowed_by_region.items()
        if not allowed.intersection(source_profile_ids)
    ]
    if missing_regions:
        raise ProductOnboardingInputError(
            "each selected region requires a registered source profile: " + ",".join(missing_regions)
        )
    budgets_input = source.get("budgets")
    if not isinstance(budgets_input, Mapping) or set(budgets_input) != set(_BUDGET_LIMITS):
        raise ProductOnboardingInputError("budgets must contain the complete registered field set")
    budgets: dict[str, int] = {}
    for key, (minimum, maximum, _) in _BUDGET_LIMITS.items():
        value = budgets_input.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ProductOnboardingInputError(
                f"budget {key} must be an integer between {minimum} and {maximum}"
            )
        budgets[key] = value
    return {
        "profile_name": profile_name,
        "region_codes": region_codes,
        "industry_code": industry_code,
        "evidence_template_id": evidence_template_id,
        "source_profile_ids": source_profile_ids,
        "budgets": budgets,
    }


def _profile_payload(
    *,
    actor: Mapping[str, str],
    profile_id: str,
    version: int,
    state: str,
    config: Mapping[str, Any],
    previous_version: int | None,
    activated_from_version: int | None = None,
    rolled_back_from_version: int | None = None,
    rollback_target_version: int | None = None,
) -> dict[str, Any]:
    now = utc_now_iso()
    config_copy = copy.deepcopy(dict(config))
    return {
        "profile_version_id": (
            f"ONBOARDING-{actor['tenant_scope_sha256'][:12]}-{profile_id}-v{version}"
        ),
        "tenant_scope_sha256": actor["tenant_scope_sha256"],
        "profile_id": profile_id,
        "version": version,
        "state": state,
        "config": config_copy,
        "config_sha256": _sha256(config_copy),
        "previous_version": previous_version,
        "activated_from_version": activated_from_version,
        "rolled_back_from_version": rolled_back_from_version,
        "rollback_target_version": rollback_target_version,
        "created_at": now,
        "created_by_principal_id": actor["principal_id"],
        "created_by_role": actor["role"],
        "fixed_execution_boundary": _fixed_boundary(),
    }


def _persist_profile_mutation(
    *,
    session: DatabaseSession,
    actor: Mapping[str, str],
    profile: Mapping[str, Any],
    action: str,
    pointer: Mapping[str, Any] | None,
) -> str:
    now = str(profile["created_at"])
    audit_id = f"ONBOARDING-AUDIT-{profile['profile_version_id']}-{action}"
    with session.bulk_write():
        session.upsert_record(
            PersistedRecord(
                object_type=PROFILE_VERSION_OBJECT_TYPE,
                record_id=str(profile["profile_version_id"]),
                stage_scope=0,
                project_id=None,
                object_refs={
                    "profile_id": str(profile["profile_id"]),
                    "tenant_id": actor["tenant_id"],
                },
                decision_states={"profile_state": str(profile["state"])},
                trace_refs={
                    "config_sha256": str(profile["config_sha256"]),
                    "contract_ref": PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF,
                },
                audit_refs={
                    "actor_principal_id": actor["principal_id"],
                    "actor_role": actor["role"],
                },
                governed_state=_fixed_boundary(),
                writeback_state={"formal_fact_writeback": False, "customer_writeback": False},
                payload=copy.deepcopy(dict(profile)),
                persisted_at=now,
            )
        )
        if pointer is not None:
            session.upsert_record(
                PersistedRecord(
                    object_type=ACTIVE_POINTER_OBJECT_TYPE,
                    record_id=str(pointer["pointer_id"]),
                    stage_scope=0,
                    project_id=None,
                    object_refs={
                        "profile_id": str(pointer["profile_id"]),
                        "tenant_id": actor["tenant_id"],
                    },
                    decision_states={"pointer_state": "ACTIVE"},
                    trace_refs={"config_sha256": str(pointer["config_sha256"])},
                    audit_refs={"actor_principal_id": actor["principal_id"]},
                    governed_state=_fixed_boundary(),
                    writeback_state={"formal_fact_writeback": False},
                    payload=copy.deepcopy(dict(pointer)),
                    persisted_at=now,
                )
            )
        session.upsert_record(
            PersistedRecord(
                object_type=AUDIT_OBJECT_TYPE,
                record_id=audit_id,
                stage_scope=0,
                project_id=None,
                object_refs={
                    "profile_id": str(profile["profile_id"]),
                    "profile_version_id": str(profile["profile_version_id"]),
                    "tenant_id": actor["tenant_id"],
                },
                decision_states={"action": action, "profile_state": str(profile["state"])},
                trace_refs={
                    "config_sha256": str(profile["config_sha256"]),
                    "contract_ref": PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF,
                },
                audit_refs={
                    "actor_principal_id": actor["principal_id"],
                    "actor_role": actor["role"],
                },
                governed_state={"raw_secret_persisted": False, **_fixed_boundary()},
                writeback_state={"formal_fact_writeback": False},
                payload={
                    "audit_id": audit_id,
                    "profile_id": profile["profile_id"],
                    "version": profile["version"],
                    "action": action,
                    "config_sha256": profile["config_sha256"],
                    "actor_principal_id": actor["principal_id"],
                    "actor_role": actor["role"],
                    "occurred_at": now,
                    "raw_config_persisted_in_audit": False,
                },
                persisted_at=now,
            )
        )
    return audit_id


def _pointer_payload(actor: Mapping[str, str], profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "pointer_id": f"ONBOARDING-ACTIVE-{actor['tenant_scope_sha256'][:20]}",
        "tenant_scope_sha256": actor["tenant_scope_sha256"],
        "profile_id": profile["profile_id"],
        "active_version": profile["version"],
        "profile_version_id": profile["profile_version_id"],
        "config_sha256": profile["config_sha256"],
        "activated_at": profile["created_at"],
        "fixed_execution_boundary": _fixed_boundary(),
    }


def _execution_projection(config: Mapping[str, Any]) -> dict[str, Any]:
    budgets = dict(config["budgets"])
    return {
        "region_codes": list(config["region_codes"]),
        "source_profile_ids": list(config["source_profile_ids"]),
        "industry_code": config["industry_code"],
        "evidence_template_id": config["evidence_template_id"],
        "candidate_limit": budgets["discovery_candidate_limit"],
        "detail_capture_limit": budgets["detail_capture_limit"],
        "attachment_capture_limit": budgets["attachment_capture_limit"],
        "job_time_budget_seconds": budgets["job_time_budget_seconds"],
        **_fixed_boundary(),
    }


def _profile_versions(
    session: DatabaseSession, tenant_scope_sha256: str, profile_id: str
) -> list[dict[str, Any]]:
    values = [
        dict(record.payload)
        for record in session.list_records(PROFILE_VERSION_OBJECT_TYPE)
        if record.payload.get("tenant_scope_sha256") == tenant_scope_sha256
        and record.payload.get("profile_id") == profile_id
    ]
    values.sort(key=lambda item: int(item.get("version") or 0))
    return values


def _active_pointer(
    session: DatabaseSession, tenant_scope_sha256: str
) -> dict[str, Any] | None:
    record = session.get_record(
        ACTIVE_POINTER_OBJECT_TYPE,
        f"ONBOARDING-ACTIVE-{tenant_scope_sha256[:20]}",
    )
    return dict(record.payload) if record is not None else None


def _passing_test_exists(
    session: DatabaseSession,
    tenant_scope_sha256: str,
    profile_id: str,
    version: int,
    config_sha256: str,
) -> bool:
    return any(
        record.payload.get("tenant_scope_sha256") == tenant_scope_sha256
        and record.payload.get("profile_id") == profile_id
        and int(record.payload.get("version") or 0) == version
        and record.payload.get("config_sha256") == config_sha256
        and record.payload.get("test_state") == "PASSED"
        for record in session.list_records(TEST_RUN_OBJECT_TYPE)
    )


def _trusted_actor(payload: Mapping[str, Any]) -> dict[str, str]:
    actor = payload.get("_internal_auth_context")
    if not isinstance(actor, Mapping) or not actor.get("authenticated"):
        raise ProductOnboardingAccessError("authenticated transport context is required")
    principal_id = str(actor.get("principal_id") or "").strip()
    if not _ID_RE.fullmatch(principal_id):
        raise ProductOnboardingAccessError("valid authenticated principal_id is required")
    if "internal_product_config" not in set(actor.get("permissions") or []):
        raise ProductOnboardingAccessError("internal_product_config permission is required")
    tenant_id = str(actor.get("deployment_tenant_id") or "local-development").strip()
    if not tenant_id or len(tenant_id) > 128:
        raise ProductOnboardingAccessError("valid deployment tenant scope is required")
    return {
        "tenant_id": tenant_id,
        "tenant_scope_sha256": hashlib.sha256(tenant_id.encode("utf-8")).hexdigest(),
        "principal_id": principal_id,
        "role": str(actor.get("role") or "unknown"),
    }


def _reject_unknown(payload: Mapping[str, Any], allowed: set[str]) -> None:
    unknown = sorted(set(payload).difference(allowed))
    if unknown:
        raise ProductOnboardingInputError("unknown fields: " + ",".join(unknown))


def _reject_config_fields_for_state_action(payload: Mapping[str, Any]) -> None:
    forbidden = {
        "profile_name",
        "region_codes",
        "industry_code",
        "evidence_template_id",
        "source_profile_ids",
        "budgets",
    }.intersection(payload)
    if forbidden:
        raise ProductOnboardingInputError(
            "state transition does not accept config fields: " + ",".join(sorted(forbidden))
        )


def _identifier(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _ID_RE.fullmatch(normalized):
        raise ProductOnboardingInputError(f"{field} is invalid")
    return normalized


def _optional_identifier(value: Any, field: str) -> str:
    if value in (None, ""):
        return ""
    return _identifier(value, field)


def _optional_positive_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProductOnboardingInputError(f"{field} must be a positive integer or null")
    return value


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _fixed_boundary() -> dict[str, Any]:
    return {
        "payload_boundary": "SANITIZED_OFFLINE_INTERNAL",
        "source_mode": "OFFLINE_SANITIZED",
        "run_mode": "PREVIEW",
        "live_source_enabled": False,
        "real_external_fetch_enabled": False,
        "external_contact_enabled": False,
        "payment_enabled": False,
        "refund_enabled": False,
        "customer_delivery_enabled": False,
        "customer_publication_enabled": False,
        "source_allowlist_override_enabled": False,
        "approval_bypass_enabled": False,
    }


def _governance() -> dict[str, Any]:
    return {
        "contract_ref": PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF,
        "private_single_tenant": True,
        "customer_self_service_enabled": False,
        "configuration_can_expand_source_allowlist": False,
        "configuration_can_change_approval_or_release_gate": False,
        "offline_test_creates_task_or_fetch": False,
        "live_and_external_actions_enabled": False,
        "saas_onboarding_complete": False,
    }


def _public_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(
        {
            key: profile.get(key)
            for key in (
                "profile_version_id",
                "profile_id",
                "version",
                "state",
                "config",
                "config_sha256",
                "previous_version",
                "activated_from_version",
                "rolled_back_from_version",
                "rollback_target_version",
                "created_at",
                "fixed_execution_boundary",
            )
        }
    )


def _public_pointer(pointer: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if pointer is None:
        return None
    return copy.deepcopy(
        {
            key: pointer.get(key)
            for key in (
                "profile_id",
                "active_version",
                "profile_version_id",
                "config_sha256",
                "activated_at",
                "fixed_execution_boundary",
            )
        }
    )


def _mutation_response(
    *,
    action: str,
    operation_state: str,
    profile: Mapping[str, Any],
    pointer: Mapping[str, Any] | None,
    audit_id: str,
) -> dict[str, Any]:
    return {
        "surface_id": "product_onboarding_config_internal",
        "action": action,
        "operation_state": operation_state,
        "profile": _public_profile(profile),
        "active_profile": _public_pointer(pointer),
        "audit": {"audit_id": audit_id, "raw_config_persisted_in_audit": False},
        "governance": _governance(),
    }


__all__ = [
    "ACTIVE_POINTER_OBJECT_TYPE",
    "AUDIT_OBJECT_TYPE",
    "PROFILE_VERSION_OBJECT_TYPE",
    "PRODUCT_ONBOARDING_CONFIG_CONTRACT_REF",
    "ProductOnboardingAccessError",
    "ProductOnboardingConflictError",
    "ProductOnboardingInputError",
    "TEST_RUN_OBJECT_TYPE",
    "list_product_onboarding_configs",
    "mutate_product_onboarding_config",
    "product_onboarding_config_catalog",
    "run_product_onboarding_offline_test",
]
