from __future__ import annotations

from functools import lru_cache
from typing import Any, Mapping

from shared.contract_loader import load_contract


CONTRACT_REF = "contracts/sales/customer_delivery_boundary_contract.json"


@lru_cache(maxsize=1)
def _contract() -> dict[str, Any]:
    contract = dict(load_contract(CONTRACT_REF))
    required = {
        "contract_id",
        "contract_version",
        "title",
        "delivery_policy",
        "required_clauses",
        "customer_visible_field_allowlist",
        "forbidden_field_keys",
    }
    missing = sorted(required - set(contract))
    if missing:
        raise ValueError(f"customer delivery boundary contract missing fields: {missing}")
    clauses = list(contract.get("required_clauses") or [])
    if not clauses or any(
        not isinstance(item, Mapping)
        or not str(item.get("code") or "").strip()
        or not str(item.get("text") or "").strip()
        for item in clauses
    ):
        raise ValueError("customer delivery boundary contract has invalid required_clauses")
    return contract


def customer_delivery_boundary() -> dict[str, Any]:
    contract = _contract()
    policy = dict(contract["delivery_policy"])
    return {
        "contract_id": str(contract["contract_id"]),
        "contract_version": str(contract["contract_version"]),
        "contract_ref": CONTRACT_REF,
        "title": str(contract["title"]),
        "delivery_mode": str(policy.get("delivery_mode") or ""),
        "current_delivery_statement": str(policy.get("current_delivery_statement") or ""),
        "human_signoff_required": bool(policy.get("human_signoff_required")),
        "automatic_email_delivery_enabled": bool(
            policy.get("automatic_email_delivery_enabled")
        ),
        "customer_self_service_download_enabled": bool(
            policy.get("customer_self_service_download_enabled")
        ),
        "clauses": [
            {
                "code": str(item["code"]),
                "title": str(item.get("title") or ""),
                "text": str(item["text"]),
            }
            for item in contract["required_clauses"]
        ],
    }


def customer_delivery_disclaimer_texts() -> tuple[str, ...]:
    return tuple(item["text"] for item in customer_delivery_boundary()["clauses"])


def customer_safe_field_policy(policy: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = dict(policy or {})
    allowlist_enforced = bool(
        source.get("allowlist_enforced", source.get("字段白名单已执行", True))
    )
    masking_required = bool(source.get("masking_required", source.get("脱敏必需", True)))
    hidden = bool(
        source.get(
            "内部黑箱字段已隐藏",
            not bool(source.get("internal_blackbox_fields_exposed", False)),
        )
    )
    return {
        "policy_ref": "contracts/governance/field_policy_dictionary.json",
        "allowlist_enforced": allowlist_enforced,
        "masking_required": masking_required,
        "internal_blackbox_fields_exposed": not hidden,
        "customer_visible_field_allowlist": list(
            _contract()["customer_visible_field_allowlist"]
        ),
        "internal_field_names_embedded": False,
    }


def customer_safe_approval_audit(approval: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(approval)
    request_ref = source.get("审批请求编号") or source.get("request_id")
    execution_ref = source.get("下载执行审计编号") or source.get("execution_event_id")
    state = source.get("审批状态") or source.get("state")
    validation_only = bool(source.get("validation_only"))
    return {
        "approval_record_present": bool(request_ref),
        "approval_state": str(state or "APPROVAL_CONFIRMED_BY_CALLER"),
        "object_version_matches": bool(
            source.get("审批对象版本一致", source.get("resource_version_matches", False))
        ),
        "separation_of_duties_satisfied": bool(
            source.get(
                "职责分离已满足",
                source.get("separation_of_duties_satisfied", False),
            )
        ),
        "download_execution_recorded": bool(execution_ref),
        "production_approval_confirmed": not validation_only,
    }


def assert_customer_delivery_payload_safe(payload: Any) -> None:
    forbidden = {str(item).strip().casefold() for item in _contract()["forbidden_field_keys"]}
    violations: list[str] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                key_text = str(key).strip()
                child = f"{path}.{key_text}" if path else key_text
                if key_text.casefold() in forbidden:
                    violations.append(child)
                visit(item, child)
        elif isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")

    visit(payload, "")
    if violations:
        raise ValueError(
            "customer delivery payload contains forbidden internal fields: "
            + ", ".join(sorted(set(violations)))
        )
    if isinstance(payload, Mapping):
        field_policy = payload.get("field_policy")
        if isinstance(field_policy, Mapping) and bool(
            field_policy.get("internal_blackbox_fields_exposed")
        ):
            raise ValueError("customer delivery payload exposes internal blackbox fields")


__all__ = [
    "CONTRACT_REF",
    "assert_customer_delivery_payload_safe",
    "customer_delivery_boundary",
    "customer_delivery_disclaimer_texts",
    "customer_safe_approval_audit",
    "customer_safe_field_policy",
]
