from __future__ import annotations

import re
from typing import Any, Mapping


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_key_value_condition(condition: str, facts: Mapping[str, Any]) -> bool:
    field_name, separator, expected_value = str(condition).partition("=")
    if not separator:
        return False
    actual = facts.get(field_name.strip())
    return str(actual) == expected_value.strip()


def _ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value]


def _match_contract_rule(rules: list[dict[str, Any]], facts: Mapping[str, Any]) -> dict[str, Any] | None:
    for rule in rules:
        if _matches_key_value_condition(str(rule.get("condition", "")), facts):
            return rule
    return None


def _merge_contract_state_sinks(*sources: Mapping[str, Any] | None) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        if source:
            merged.update(dict(source))
    return merged


def _coerce_assignment_value(value: str) -> Any:
    token = value.strip()
    lowered = token.casefold()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    return token


def _parse_assignment_actions(actions: list[str]) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for action in actions:
        field_name, separator, raw_value = str(action).partition("=")
        if not separator:
            continue
        parsed[field_name.strip()] = _coerce_assignment_value(raw_value)
    return parsed


def _resolve_condition_operand(token: str, facts: Mapping[str, Any]) -> Any:
    candidate = token.strip()
    if candidate in facts:
        return facts[candidate]
    return _coerce_assignment_value(candidate)


def _matches_stage8_policy_condition(condition: str, facts: Mapping[str, Any]) -> bool:
    normalized = str(condition).strip()
    if not normalized:
        return False

    in_match = re.fullmatch(r"(?P<field>[A-Za-z0-9_]+)\s+in\s+\[(?P<values>[^\]]+)\]", normalized)
    if in_match:
        actual = facts.get(in_match.group("field"))
        allowed = {
            str(_coerce_assignment_value(token)).upper()
            for token in in_match.group("values").split(",")
            if token.strip()
        }
        return str(actual).upper() in allowed

    compare_match = re.fullmatch(
        r"(?P<left>[A-Za-z0-9_]+)\s*(?P<op>>=|<=|>|<)\s*(?P<right>[A-Za-z0-9_]+)",
        normalized,
    )
    if compare_match:
        left_value = _resolve_condition_operand(compare_match.group("left"), facts)
        right_value = _resolve_condition_operand(compare_match.group("right"), facts)
        if not (_is_number(left_value) and _is_number(right_value)):
            return False
        left_number = float(left_value)
        right_number = float(right_value)
        operator = compare_match.group("op")
        if operator == ">=":
            return left_number >= right_number
        if operator == "<=":
            return left_number <= right_number
        if operator == ">":
            return left_number > right_number
        return left_number < right_number

    equals_match = re.fullmatch(r"(?P<field>[A-Za-z0-9_]+)=(?P<value>.+)", normalized)
    if equals_match:
        actual = facts.get(equals_match.group("field"))
        expected = _coerce_assignment_value(equals_match.group("value"))
        if isinstance(expected, bool):
            return bool(actual) is expected
        return str(actual).upper() == str(expected).upper()

    return False


__all__ = [
    "_coerce_assignment_value",
    "_ensure_list",
    "_match_contract_rule",
    "_matches_stage8_policy_condition",
    "_merge_contract_state_sinks",
    "_parse_assignment_actions",
    "_resolve_condition_operand",
]
