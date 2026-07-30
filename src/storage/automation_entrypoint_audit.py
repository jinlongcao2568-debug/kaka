from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml


AUTOMATION_ENTRYPOINT_AUDIT_VERSION = 1
AUTOMATION_ENTRYPOINT_AUDIT_RULESET_ID = "automation-entrypoint-audit-v1"
DEFAULT_REGISTRY_PATH = Path("control") / "automation_entrypoint_registry.yaml"
DEFAULT_OUTPUT_ROOT = Path("tmp") / "evaluation-real-samples" / "automation-entrypoint-audit-v1"

REQUIRED_FORMAL_FIELDS = {
    "entrypoint_id",
    "kind",
    "entrypoint_role",
    "status",
    "automation_layer",
    "module_or_command",
    "state_inputs",
    "state_outputs",
    "manual_gate_required",
    "replaces_human_memory",
}


def default_automation_entrypoint_registry_path() -> Path:
    return DEFAULT_REGISTRY_PATH


def build_automation_entrypoint_audit(
    *,
    repo_root: str | Path | None = None,
    registry_path: str | Path | None = None,
    output_root: str | Path | None = None,
    write_output: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root or Path.cwd()).resolve()
    registry = _resolve_path(root, registry_path or DEFAULT_REGISTRY_PATH)
    output = _resolve_path(root, output_root or DEFAULT_OUTPUT_ROOT)
    created = created_at or _utc_now_iso()

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    registry_payload: dict[str, Any] = {}
    if not registry.exists():
        blocking_reasons.append("automation_entrypoint_registry_missing")
    else:
        try:
            loaded = yaml.safe_load(registry.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, Mapping):
                blocking_reasons.append("automation_entrypoint_registry_not_mapping")
            else:
                registry_payload = dict(loaded)
        except Exception as exc:  # pragma: no cover - defensive path.
            blocking_reasons.append(f"automation_entrypoint_registry_load_failed:{exc}")

    scripts = sorted((root / "scripts").glob("*.ps1"))
    if not scripts:
        blocking_reasons.append("scripts_directory_has_no_powershell_entrypoints")

    classified_scripts = [
        _classify_script(script=script, repo_root=root, registry=registry_payload)
        for script in scripts
    ]
    unclassified = [
        item["script"]
        for item in classified_scripts
        if item["entrypoint_role"] == "unclassified"
    ]
    if unclassified:
        blocking_reasons.append("unclassified_scripts:" + ",".join(unclassified[:20]))

    formal_entrypoints = _formal_entrypoints(registry_payload)
    if not formal_entrypoints:
        blocking_reasons.append("formal_entrypoints_missing")

    formal_results = [
        _audit_formal_entrypoint(
            entrypoint=entrypoint,
            repo_root=root,
            registry=registry_payload,
        )
        for entrypoint in formal_entrypoints
    ]
    for result in formal_results:
        blocking_reasons.extend(result["blocking_reasons"])
        warnings.extend(result["warnings"])

    if not _architecture_decision_ok(registry_payload):
        blocking_reasons.append("scripts_not_declared_as_thin_launchers")

    readme_path = root / "README.md"
    if not readme_path.exists():
        blocking_reasons.append("readme_missing")
    else:
        readme_text = readme_path.read_text(encoding="utf-8")
        if "automation_entrypoint_registry.yaml" not in readme_text:
            blocking_reasons.append("readme_missing_automation_registry_pointer")
        if "脚本不是状态机本体" not in readme_text:
            blocking_reasons.append("readme_missing_scripts_not_state_machine_statement")

    manifest = {
        "manifest_version": AUTOMATION_ENTRYPOINT_AUDIT_VERSION,
        "ruleset_id": AUTOMATION_ENTRYPOINT_AUDIT_RULESET_ID,
        "created_at": created,
        "repo_root": str(root),
        "registry_path": str(registry),
        "audit_state": "PASS" if not blocking_reasons else "BLOCKED",
        "blocking_reasons": list(dict.fromkeys(blocking_reasons)),
        "warnings": list(dict.fromkeys(warnings)),
        "summary": {
            "script_count": len(scripts),
            "classified_script_count": len(classified_scripts) - len(unclassified),
            "unclassified_script_count": len(unclassified),
            "formal_entrypoint_count": len(formal_entrypoints),
            "formal_script_entrypoint_count": sum(1 for item in formal_entrypoints if item.get("kind") == "script"),
            "formal_http_route_entrypoint_count": sum(1 for item in formal_entrypoints if item.get("kind") == "http_route"),
            "script_role_counts": _counts(item["entrypoint_role"] for item in classified_scripts),
            "formal_status_counts": _counts(str(item.get("status") or "") for item in formal_entrypoints),
            "formal_role_counts": _counts(str(item.get("entrypoint_role") or "") for item in formal_entrypoints),
            "scripts_are_thin_launchers": bool(
                registry_payload.get("architecture_decision", {}).get("scripts_are_thin_launchers")
            ),
            "external_customer_action_enabled_count": sum(
                1 for item in formal_entrypoints if bool(item.get("external_customer_action_enabled"))
            ),
            "manual_gate_required_count": sum(1 for item in formal_entrypoints if bool(item.get("manual_gate_required"))),
        },
        "formal_entrypoints": formal_results,
        "classified_scripts_sample": classified_scripts[:160],
        "unclassified_scripts": unclassified,
        "safety": {
            "customer_visible_allowed": False,
            "external_touch_enabled": False,
            "payment_enabled": False,
            "delivery_enabled": False,
            "refund_enabled": False,
            "audit_only": True,
        },
    }
    manifest["manifest_sha256"] = _fingerprint(
        {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    )
    result = {
        "safe_to_continue_automation": manifest["audit_state"] == "PASS",
        "manifest": manifest,
        "summary": manifest["summary"],
        "blocking_reasons": manifest["blocking_reasons"],
        "warnings": manifest["warnings"],
        "output_path": "",
    }
    if write_output:
        output.mkdir(parents=True, exist_ok=True)
        output_path = output / "automation-entrypoint-audit-v1.json"
        output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(output_path)
    return result


def _audit_formal_entrypoint(
    *,
    entrypoint: Mapping[str, Any],
    repo_root: Path,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    blocking_reasons: list[str] = []
    warnings: list[str] = []
    entrypoint_id = str(entrypoint.get("entrypoint_id") or "")
    kind = str(entrypoint.get("kind") or "")
    role = str(entrypoint.get("entrypoint_role") or "")
    status = str(entrypoint.get("status") or "")
    missing_fields = sorted(field for field in REQUIRED_FORMAL_FIELDS if field not in entrypoint)
    if missing_fields:
        blocking_reasons.append(f"{entrypoint_id}:missing_fields:{','.join(missing_fields)}")

    allowed_roles = set(_string_list(registry.get("allowed_entrypoint_roles")))
    if allowed_roles and role not in allowed_roles:
        blocking_reasons.append(f"{entrypoint_id}:unknown_entrypoint_role:{role}")
    allowed_statuses = set(_string_list(registry.get("allowed_status_values")))
    if allowed_statuses and status not in allowed_statuses:
        blocking_reasons.append(f"{entrypoint_id}:unknown_status:{status}")

    script_exists = False
    route_exists = False
    module_exists = False
    module_or_command = str(entrypoint.get("module_or_command") or "")

    if kind == "script":
        script_value = str(entrypoint.get("script") or "")
        if not script_value:
            blocking_reasons.append(f"{entrypoint_id}:script_missing")
        else:
            script_path = _resolve_path(repo_root, script_value)
            script_exists = script_path.exists()
            if not script_exists:
                blocking_reasons.append(f"{entrypoint_id}:script_path_missing:{script_value}")
        if module_or_command:
            module_exists = _module_exists(module_or_command)
            if not module_exists:
                blocking_reasons.append(f"{entrypoint_id}:module_not_importable:{module_or_command}")
    elif kind == "http_route":
        route = str(entrypoint.get("route") or "")
        module_path = _resolve_path(repo_root, module_or_command)
        if not route:
            blocking_reasons.append(f"{entrypoint_id}:route_missing")
        if not module_path.exists():
            blocking_reasons.append(f"{entrypoint_id}:route_module_path_missing:{module_or_command}")
        else:
            text = module_path.read_text(encoding="utf-8")
            route_exists = route in text
            if not route_exists:
                blocking_reasons.append(f"{entrypoint_id}:route_not_found:{route}")
            for marker in ("SANITIZED_OFFLINE_INTERNAL", "live_execution_enabled", "BLOCKED_CONTROLLED_UNAVAILABLE"):
                if marker not in text:
                    blocking_reasons.append(f"{entrypoint_id}:route_guard_marker_missing:{marker}")
    else:
        blocking_reasons.append(f"{entrypoint_id}:unsupported_entrypoint_kind:{kind}")

    if not entrypoint.get("state_inputs"):
        blocking_reasons.append(f"{entrypoint_id}:state_inputs_empty")
    if not entrypoint.get("state_outputs"):
        blocking_reasons.append(f"{entrypoint_id}:state_outputs_empty")
    if entrypoint.get("replaces_human_memory") is not True:
        blocking_reasons.append(f"{entrypoint_id}:does_not_replace_human_memory")
    if bool(entrypoint.get("external_customer_action_enabled")):
        warnings.append(f"{entrypoint_id}:external_customer_action_enabled_requires_release_gate")

    return {
        "entrypoint_id": entrypoint_id,
        "kind": kind,
        "entrypoint_role": role,
        "status": status,
        "automation_layer": str(entrypoint.get("automation_layer") or ""),
        "script": str(entrypoint.get("script") or ""),
        "route": str(entrypoint.get("route") or ""),
        "module_or_command": module_or_command,
        "script_exists": script_exists,
        "route_exists": route_exists,
        "module_exists": module_exists,
        "superseded_by_entrypoint_id": str(entrypoint.get("superseded_by_entrypoint_id") or ""),
        "cleanup_state": str(entrypoint.get("cleanup_state") or ""),
        "purpose": str(entrypoint.get("purpose") or ""),
        "manual_gate_required": bool(entrypoint.get("manual_gate_required")),
        "external_customer_action_enabled": bool(entrypoint.get("external_customer_action_enabled")),
        "replaces_human_memory": bool(entrypoint.get("replaces_human_memory")),
        "blocking_reasons": blocking_reasons,
        "warnings": warnings,
    }


def _classify_script(*, script: Path, repo_root: Path, registry: Mapping[str, Any]) -> dict[str, Any]:
    relative_script = script.relative_to(repo_root).as_posix()
    name = script.name
    rules = registry.get("script_classification_rules")
    if not isinstance(rules, Mapping):
        return {"script": relative_script, "entrypoint_role": "unclassified", "classification_rule": "missing_rules"}
    exact = rules.get("exact")
    if isinstance(exact, Mapping) and name in exact:
        return {
            "script": relative_script,
            "entrypoint_role": str(exact[name]),
            "classification_rule": f"exact:{name}",
        }
    prefixes = rules.get("prefixes")
    if isinstance(prefixes, Mapping):
        for prefix, role in prefixes.items():
            if name.startswith(str(prefix)):
                return {
                    "script": relative_script,
                    "entrypoint_role": str(role),
                    "classification_rule": f"prefix:{prefix}",
                }
    return {"script": relative_script, "entrypoint_role": "unclassified", "classification_rule": "none"}


def _formal_entrypoints(registry: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = registry.get("formal_entrypoints")
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, Mapping)]


def _architecture_decision_ok(registry: Mapping[str, Any]) -> bool:
    decision = registry.get("architecture_decision")
    if not isinstance(decision, Mapping):
        return False
    return bool(decision.get("scripts_are_thin_launchers")) and bool(decision.get("scripts_are_not_the_system_brain"))


def _module_exists(module_or_command: str) -> bool:
    if module_or_command.endswith(".py") or "/" in module_or_command or "\\" in module_or_command:
        return True
    return importlib.util.find_spec(module_or_command) is not None


def _resolve_path(repo_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return repo_root / path


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item not in (None, "")]
    return [str(value)]


def _counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit automation entrypoint registry and script classification.")
    parser.add_argument("--repo-root", default=str(Path.cwd()))
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY_PATH))
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--write-output", action="store_true")
    parser.add_argument("--json", action="store_true", dest="emit_json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_automation_entrypoint_audit(
        repo_root=args.repo_root,
        registry_path=args.registry,
        output_root=args.output_root,
        write_output=args.write_output,
    )
    if args.emit_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        state = result["manifest"]["audit_state"]
        print(f"automation entrypoint audit {state}: safe_to_continue={result['safe_to_continue_automation']}")
        print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
        if result["blocking_reasons"]:
            print("blocking_reasons:")
            for reason in result["blocking_reasons"]:
                print(f"- {reason}")
        if result["warnings"]:
            print("warnings:")
            for warning in result["warnings"]:
                print(f"- {warning}")
        if result["output_path"]:
            print(f"output_path: {result['output_path']}")
    return 0 if result["safe_to_continue_automation"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "AUTOMATION_ENTRYPOINT_AUDIT_RULESET_ID",
    "build_automation_entrypoint_audit",
    "default_automation_entrypoint_registry_path",
]
