from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_REGISTRY_PATH = Path("control") / "automation_entrypoint_registry.yaml"
RUNTIME_CONTROLLER_TRANSPORT_ID = "runtime_controller_entrypoint_transport"


class RuntimeEntrypointRegistry:
    def __init__(self, *, payload: Mapping[str, Any], path: Path) -> None:
        self.payload = dict(payload)
        self.path = path

    @classmethod
    def from_path(cls, path: str | Path) -> "RuntimeEntrypointRegistry":
        registry_path = Path(path)
        if not registry_path.exists():
            raise ValueError(f"runtime_entrypoint_registry_missing:{registry_path}")
        loaded = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, Mapping):
            raise ValueError(f"runtime_entrypoint_registry_not_mapping:{registry_path}")
        return cls(payload=loaded, path=registry_path)

    @classmethod
    def default(cls, *, repo_root: str | Path | None = None) -> "RuntimeEntrypointRegistry":
        root = Path(repo_root).resolve() if repo_root is not None else Path(__file__).resolve().parents[2]
        return cls.from_path(root / DEFAULT_REGISTRY_PATH)

    def formal_entrypoints(self) -> list[dict[str, Any]]:
        raw = self.payload.get("formal_entrypoints")
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, Mapping)]

    def find_entrypoint(self, entrypoint_id: str) -> dict[str, Any] | None:
        target = str(entrypoint_id)
        for entrypoint in self.formal_entrypoints():
            if str(entrypoint.get("entrypoint_id") or "") == target:
                return entrypoint
        return None

    def require_registered_entrypoint(self, entrypoint_id: str) -> dict[str, Any]:
        entrypoint = self.find_entrypoint(entrypoint_id)
        if entrypoint is None:
            raise ValueError(f"unregistered_runtime_entrypoint_id:{entrypoint_id}")
        if bool(entrypoint.get("external_customer_action_enabled")):
            raise ValueError(f"runtime_entrypoint_external_customer_action_enabled:{entrypoint_id}")
        if entrypoint.get("replaces_human_memory") is not True:
            raise ValueError(f"runtime_entrypoint_does_not_replace_human_memory:{entrypoint_id}")
        return entrypoint

    def require_transport_entrypoint(self) -> dict[str, Any]:
        entrypoint = self.require_registered_entrypoint(RUNTIME_CONTROLLER_TRANSPORT_ID)
        if str(entrypoint.get("kind") or "") != "script":
            raise ValueError(f"runtime_controller_transport_not_script:{RUNTIME_CONTROLLER_TRANSPORT_ID}")
        if str(entrypoint.get("module_or_command") or "") != "runtime.entrypoint_cli":
            raise ValueError(f"runtime_controller_transport_module_mismatch:{RUNTIME_CONTROLLER_TRANSPORT_ID}")
        return entrypoint


__all__ = [
    "DEFAULT_REGISTRY_PATH",
    "RUNTIME_CONTROLLER_TRANSPORT_ID",
    "RuntimeEntrypointRegistry",
]
