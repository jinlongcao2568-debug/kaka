# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Optional

from shared.provider_adapter_config import (
    ProviderAdapterConfig,
    build_provider_adapter_config_from_env,
    build_provider_adapter_readiness_summary,
    provider_adapter_bootstrap_payload,
)


_DEFAULT_STORAGE_BACKEND = "json-file"
_DEFAULT_STORAGE_SCOPE = "shared"
_DEFAULT_QUEUE_BACKEND = "storage"
_DEFAULT_WORKER_RUNTIME = "internal-storage-worker"
_DEFAULT_OBJECT_STORAGE_BACKEND = "local-filesystem"
_PROCESS_STORAGE_SCOPE = "process"
_DEFAULT_STORAGE_RUNTIME_MODE = "stable-default"
_EXPLICIT_STORAGE_RUNTIME_MODE = "explicit-path"
_PROCESS_SCOPED_STORAGE_RUNTIME_MODE = "process-scoped-default"
_STORAGE_DIR_NAME = "kaka"
_STORAGE_FILE_STEM = "internal_operator_loop_store"
_TEST_ISOLATION_TRUTHY = frozenset({"1", "true", "yes", "on", "process"})


def _read_env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _resolve_storage_scope(storage_scope_value: str | None, storage_test_isolation_value: str | None) -> str:
    if (storage_scope_value or "").lower() == _PROCESS_STORAGE_SCOPE:
        return _PROCESS_STORAGE_SCOPE
    if (storage_test_isolation_value or "").lower() in _TEST_ISOLATION_TRUTHY:
        return _PROCESS_STORAGE_SCOPE
    return _DEFAULT_STORAGE_SCOPE


def _resolve_storage_runtime_mode(storage_path_optional: str | None, storage_scope: str) -> str:
    if storage_path_optional:
        return _EXPLICIT_STORAGE_RUNTIME_MODE
    if storage_scope == _PROCESS_STORAGE_SCOPE:
        return _PROCESS_SCOPED_STORAGE_RUNTIME_MODE
    return _DEFAULT_STORAGE_RUNTIME_MODE


@dataclass(frozen=True)
class Settings:
    repo_root: Optional[str] = None
    environment: Optional[str] = None
    storage_backend: str = _DEFAULT_STORAGE_BACKEND
    storage_path_optional: Optional[str] = None
    storage_database_url_optional: Optional[str] = None
    storage_scope: str = _DEFAULT_STORAGE_SCOPE
    storage_runtime_mode: str = _DEFAULT_STORAGE_RUNTIME_MODE
    queue_backend: str = _DEFAULT_QUEUE_BACKEND
    worker_runtime: str = _DEFAULT_WORKER_RUNTIME
    object_storage_backend: str = _DEFAULT_OBJECT_STORAGE_BACKEND
    object_storage_path_optional: Optional[str] = None
    provider_adapter_config: ProviderAdapterConfig | None = None
    production_live_dependency_drill_inputs: dict[str, Any] | None = None

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: str | None = None,
        environment: str | None = None,
    ) -> "Settings":
        storage_path_optional = _read_env_optional("KAKA_STORAGE_PATH")
        storage_scope = _resolve_storage_scope(
            _read_env_optional("KAKA_STORAGE_SCOPE"),
            _read_env_optional("KAKA_STORAGE_TEST_ISOLATION"),
        )
        return cls(
            repo_root=repo_root,
            environment=environment,
            storage_backend=_read_env_optional("KAKA_STORAGE_BACKEND") or _DEFAULT_STORAGE_BACKEND,
            storage_path_optional=storage_path_optional,
            storage_database_url_optional=_read_env_optional("KAKA_STORAGE_DATABASE_URL"),
            storage_scope=storage_scope,
            storage_runtime_mode=_resolve_storage_runtime_mode(storage_path_optional, storage_scope),
            queue_backend=_read_env_optional("KAKA_QUEUE_BACKEND") or _DEFAULT_QUEUE_BACKEND,
            worker_runtime=_read_env_optional("KAKA_WORKER_RUNTIME") or _DEFAULT_WORKER_RUNTIME,
            object_storage_backend=(
                _read_env_optional("KAKA_OBJECT_STORAGE_BACKEND")
                or _DEFAULT_OBJECT_STORAGE_BACKEND
            ),
            object_storage_path_optional=_read_env_optional("KAKA_OBJECT_STORAGE_PATH"),
            provider_adapter_config=build_provider_adapter_config_from_env(),
        )

    def resolved_storage_path(self) -> Path:
        if self.storage_path_optional:
            return Path(self.storage_path_optional)
        base_dir = Path(os.getenv("LOCALAPPDATA") or gettempdir())
        file_name = (
            f"{_STORAGE_FILE_STEM}-{os.getpid()}.json"
            if self.storage_scope == _PROCESS_STORAGE_SCOPE
            else f"{_STORAGE_FILE_STEM}.json"
        )
        return base_dir / _STORAGE_DIR_NAME / file_name

    def normalized_storage_backend(self) -> str:
        from storage.production_infra_readiness import normalize_storage_backend_name

        return normalize_storage_backend_name(self.storage_backend)

    def normalized_object_storage_backend(self) -> str:
        from storage.object_storage import normalize_object_storage_backend_name

        return normalize_object_storage_backend_name(self.object_storage_backend)

    def resolved_object_storage_path(self) -> Path:
        from storage.object_storage import default_object_storage_path

        return default_object_storage_path(self)

    def platform_infra_readiness(self) -> dict[str, Any]:
        from storage.production_infra_readiness import build_platform_infra_readiness
        from storage.monitoring_alerting import build_monitoring_alerting_readiness
        from storage.production_slo_incident_readiness import (
            build_production_slo_incident_readiness,
        )

        readiness = build_platform_infra_readiness(
            storage_backend=self.storage_backend,
            storage_database_url_optional=self.storage_database_url_optional,
            queue_backend=self.queue_backend,
            worker_runtime=self.worker_runtime,
            object_storage_backend=self.object_storage_backend,
            object_storage_path_optional=str(self.resolved_object_storage_path()),
            repo_root=self.repo_root,
        )
        monitoring_alerting_readiness = build_monitoring_alerting_readiness(
            platform_infra_readiness=readiness,
            provider_adapter_readiness=self.provider_adapter_readiness_summary(),
        )
        readiness["monitoring_alerting_readiness"] = monitoring_alerting_readiness
        readiness["monitoring_readiness"] = monitoring_alerting_readiness["monitoring_readiness"]
        readiness["alert_rule_catalog"] = monitoring_alerting_readiness["alert_rule_catalog"]
        readiness["alert_readiness"] = monitoring_alerting_readiness["alert_readiness"]
        readiness["incident_readiness"] = monitoring_alerting_readiness["incident_readiness"]
        production_slo_incident_readiness = build_production_slo_incident_readiness(
            platform_infra_readiness=readiness,
            monitoring_alerting_readiness=monitoring_alerting_readiness,
            provider_adapter_readiness=self.provider_adapter_readiness_summary(),
            approved_dependency_drill_inputs=self.production_live_dependency_drill_inputs,
        )
        readiness["production_slo_incident_readiness"] = production_slo_incident_readiness
        readiness["approved_production_live_dependency_drill"] = production_slo_incident_readiness[
            "approved_production_live_dependency_drill"
        ]
        readiness["production_slo_readiness"] = production_slo_incident_readiness[
            "slo_readiness_carrier"
        ]
        readiness["production_monitoring_dashboard"] = production_slo_incident_readiness[
            "monitoring_dashboard_readback"
        ]
        readiness["production_alert_rule_catalog"] = production_slo_incident_readiness[
            "alert_rule_catalog"
        ]
        readiness["simulated_alert_evaluation_readback"] = production_slo_incident_readiness[
            "simulated_alert_evaluation_readback"
        ]
        readiness["production_incident_runbook"] = production_slo_incident_readiness[
            "incident_runbook_carrier"
        ]
        readiness["production_drill_evidence"] = {
            "backup_restore_drill_evidence": production_slo_incident_readiness[
                "backup_restore_drill_evidence"
            ],
            "rollback_drill_evidence": production_slo_incident_readiness[
                "rollback_drill_evidence"
            ],
        }
        readiness["suspended_state_operation_readback"] = production_slo_incident_readiness[
            "suspended_state_operation_readback"
        ]
        readiness["controlled_opening_requirements"].update(
            {
                "external_observability_provider_enabled": False,
                "external_apm_enabled": False,
                "external_paging_enabled": False,
                "notification_enabled": False,
                "live_alert_dispatch_enabled": False,
                "real_alert_dispatch_enabled": False,
                "incident_automation_enabled": False,
                "active_storage_mutation_enabled": False,
                "go_live_enabled": False,
                "production_release_enabled": False,
            }
        )
        return readiness

    def storage_bootstrap_payload(self) -> dict[str, Any]:
        active_backend = self.normalized_storage_backend()
        readiness = self.platform_infra_readiness()
        return {
            "active_backend": active_backend,
            "storage_backend": self.storage_backend,
            "storage_path": str(self.resolved_storage_path()),
            "storage_path_optional": self.storage_path_optional,
            "storage_database_url_configured": bool(self.storage_database_url_optional),
            "storage_database_url_redacted": readiness["storage_database_url_redacted"],
            "storage_database_url_dialect": readiness["storage_database_url_dialect"],
            "storage_scope": self.storage_scope,
            "storage_runtime_mode": self.storage_runtime_mode,
            "queue_backend": self.queue_backend,
            "worker_runtime": self.worker_runtime,
            "object_storage_backend": self.object_storage_backend,
            "active_object_storage_backend": self.normalized_object_storage_backend(),
            "object_storage_path": str(self.resolved_object_storage_path()),
            "object_storage_path_optional": self.object_storage_path_optional,
            "object_storage_bootstrap": readiness["object_storage_readiness"],
            "worker_queue_bootstrap": readiness["worker_queue_bootstrap"],
            "backup_restore_readiness": readiness["backup_restore_readiness"],
            "rollback_readiness": readiness["rollback_readiness"],
            "monitoring_alerting_readiness": readiness["monitoring_alerting_readiness"],
            "monitoring_readiness": readiness["monitoring_readiness"],
            "alert_rule_catalog": readiness["alert_rule_catalog"],
            "alert_readiness": readiness["alert_readiness"],
            "incident_readiness": readiness["incident_readiness"],
            "production_slo_incident_readiness": readiness["production_slo_incident_readiness"],
            "approved_production_live_dependency_drill": readiness[
                "approved_production_live_dependency_drill"
            ],
            "production_slo_readiness": readiness["production_slo_readiness"],
            "production_monitoring_dashboard": readiness["production_monitoring_dashboard"],
            "production_alert_rule_catalog": readiness["production_alert_rule_catalog"],
            "simulated_alert_evaluation_readback": readiness["simulated_alert_evaluation_readback"],
            "production_incident_runbook": readiness["production_incident_runbook"],
            "production_drill_evidence": readiness["production_drill_evidence"],
            "suspended_state_operation_readback": readiness["suspended_state_operation_readback"],
            "local_stack_readiness": readiness["compose_readiness"],
            "platform_infra_readiness": readiness,
            "provider_adapter_bootstrap": self.provider_adapter_bootstrap_payload(),
        }

    def provider_adapter_readiness_summary(self) -> dict[str, Any]:
        config = self.provider_adapter_config or build_provider_adapter_config_from_env()
        return build_provider_adapter_readiness_summary(config)

    def provider_adapter_bootstrap_payload(self) -> dict[str, Any]:
        return provider_adapter_bootstrap_payload(self.provider_adapter_readiness_summary())


__all__ = ["Settings"]
