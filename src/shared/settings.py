# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from hashlib import sha256
from ipaddress import ip_address
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Optional
from urllib.parse import quote, unquote, urlsplit

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
_INTERNAL_API_ROLES = frozenset({"owner", "operator", "reviewer", "admin"})
_INTERNAL_API_ROLE_ALIASES = {
    "internal_operator": "operator",
    "internal_test_operator": "admin",
}
_INTERNAL_API_PRINCIPAL_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DEFAULT_DEPLOYMENT_TENANCY_MODE = "LOCAL_DEVELOPMENT"
_PRIVATE_SINGLE_TENANT_MODE = "PRIVATE_SINGLE_TENANT"
_DEPLOYMENT_TENANCY_MODES = frozenset(
    {_DEFAULT_DEPLOYMENT_TENANCY_MODE, _PRIVATE_SINGLE_TENANT_MODE}
)
_DEPLOYMENT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
_PRIVATE_HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)
_TRUSTED_PROXY_BOUNDARIES = frozenset({"DIRECT_ONLY", "PRIVATE_EDGE_NETWORK_ONLY"})
_MAX_PRINCIPAL_SECRET_BYTES = 64 * 1024
_MAX_DATABASE_PASSWORD_BYTES = 4 * 1024
_DATABASE_USER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,62}$")
_DATABASE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,62}$")


@dataclass(frozen=True)
class InternalApiPrincipal:
    principal_id: str
    role: str
    token: str = field(repr=False)


def normalize_internal_api_role(value: str) -> str:
    normalized = _INTERNAL_API_ROLE_ALIASES.get(value.strip().lower(), value.strip().lower())
    if normalized not in _INTERNAL_API_ROLES:
        allowed = ", ".join(sorted(_INTERNAL_API_ROLES))
        raise ValueError(f"internal API role must be one of: {allowed}")
    return normalized


def _parse_internal_api_principals(value: str | None) -> tuple[InternalApiPrincipal, ...]:
    if value is None:
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("KAKA_INTERNAL_API_PRINCIPALS_JSON must be valid JSON") from exc
    if not isinstance(parsed, list):
        raise ValueError("KAKA_INTERNAL_API_PRINCIPALS_JSON must be a JSON array")

    principals: list[InternalApiPrincipal] = []
    seen_principal_ids: set[str] = set()
    seen_tokens: set[str] = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, dict) or set(item) != {"principal_id", "role", "token"}:
            raise ValueError(
                "each KAKA_INTERNAL_API_PRINCIPALS_JSON item must contain only "
                "principal_id, role, and token"
            )
        if not all(isinstance(item.get(key), str) for key in ("principal_id", "role", "token")):
            raise ValueError(
                f"internal API principal at index {index} fields must all be strings"
            )
        principal_id = str(item["principal_id"]).strip()
        token = str(item["token"]).strip()
        if not _INTERNAL_API_PRINCIPAL_ID_PATTERN.fullmatch(principal_id):
            raise ValueError(f"internal API principal at index {index} has an invalid principal_id")
        if len(token) < 16 or len(token) > 1024:
            raise ValueError(f"internal API principal at index {index} token must be 16-1024 characters")
        if principal_id in seen_principal_ids:
            raise ValueError(f"duplicate internal API principal_id: {principal_id}")
        if token in seen_tokens:
            raise ValueError("duplicate internal API principal token")
        seen_principal_ids.add(principal_id)
        seen_tokens.add(token)
        principals.append(
            InternalApiPrincipal(
                principal_id=principal_id,
                role=normalize_internal_api_role(str(item.get("role") or "")),
                token=token,
            )
        )
    return tuple(principals)


def _read_internal_api_principals(
    value: str | None,
    file_path: str | None,
) -> tuple[tuple[InternalApiPrincipal, ...], str | None]:
    if value and file_path:
        raise ValueError(
            "configure only one of KAKA_INTERNAL_API_PRINCIPALS_JSON or "
            "KAKA_INTERNAL_API_PRINCIPALS_FILE"
        )
    if not file_path:
        return _parse_internal_api_principals(value), None
    secret_path = Path(file_path)
    if not secret_path.is_file():
        raise ValueError("KAKA_INTERNAL_API_PRINCIPALS_FILE must reference a readable file")
    if secret_path.stat().st_size > _MAX_PRINCIPAL_SECRET_BYTES:
        raise ValueError("KAKA_INTERNAL_API_PRINCIPALS_FILE exceeds 65536 bytes")
    try:
        secret_value = secret_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("KAKA_INTERNAL_API_PRINCIPALS_FILE must be readable UTF-8") from exc
    return _parse_internal_api_principals(secret_value.strip() or None), str(secret_path)


def _read_env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def resolve_storage_database_url_from_env() -> tuple[str | None, str | None]:
    """Resolve a database URL without placing a PostgreSQL password in the environment."""
    explicit_url = _read_env_optional("KAKA_STORAGE_DATABASE_URL")
    password_file = _read_env_optional("KAKA_STORAGE_DATABASE_PASSWORD_FILE")
    component_names = (
        "KAKA_STORAGE_DATABASE_HOST",
        "KAKA_STORAGE_DATABASE_PORT",
        "KAKA_STORAGE_DATABASE_USER",
        "KAKA_STORAGE_DATABASE_NAME",
    )
    configured_components = {
        name: _read_env_optional(name)
        for name in component_names
    }
    if explicit_url and (password_file or any(configured_components.values())):
        raise ValueError(
            "configure either KAKA_STORAGE_DATABASE_URL or the PostgreSQL password-file "
            "connection settings, not both"
        )
    if explicit_url:
        return explicit_url, None
    if not password_file:
        if any(configured_components.values()):
            raise ValueError(
                "KAKA_STORAGE_DATABASE_PASSWORD_FILE is required when PostgreSQL connection "
                "components are configured"
            )
        return None, None

    secret_path = Path(password_file)
    if not secret_path.is_file():
        raise ValueError("KAKA_STORAGE_DATABASE_PASSWORD_FILE must reference a readable file")
    if secret_path.stat().st_size > _MAX_DATABASE_PASSWORD_BYTES:
        raise ValueError("KAKA_STORAGE_DATABASE_PASSWORD_FILE exceeds 4096 bytes")
    try:
        raw_password = secret_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError("KAKA_STORAGE_DATABASE_PASSWORD_FILE must be readable UTF-8") from exc
    # Docker's official PostgreSQL image reads *_FILE through shell command
    # substitution, which removes trailing newlines but preserves spaces.
    password = raw_password.rstrip("\r\n")
    if not password or "\x00" in password or "\r" in password or "\n" in password:
        raise ValueError(
            "KAKA_STORAGE_DATABASE_PASSWORD_FILE must contain one non-empty password line"
        )

    host = configured_components["KAKA_STORAGE_DATABASE_HOST"] or "postgres"
    user = configured_components["KAKA_STORAGE_DATABASE_USER"] or "kaka"
    database_name = configured_components["KAKA_STORAGE_DATABASE_NAME"]
    port_text = configured_components["KAKA_STORAGE_DATABASE_PORT"] or "5432"
    if not _PRIVATE_HOSTNAME_PATTERN.fullmatch(host.lower()):
        raise ValueError("KAKA_STORAGE_DATABASE_HOST must be a valid private DNS hostname")
    if not _DATABASE_USER_PATTERN.fullmatch(user):
        raise ValueError("KAKA_STORAGE_DATABASE_USER is invalid")
    if not database_name or not _DATABASE_NAME_PATTERN.fullmatch(database_name):
        raise ValueError("KAKA_STORAGE_DATABASE_NAME is required and invalid")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("KAKA_STORAGE_DATABASE_PORT must be an integer from 1 to 65535") from exc
    if port < 1 or port > 65535:
        raise ValueError("KAKA_STORAGE_DATABASE_PORT must be an integer from 1 to 65535")

    database_url = (
        "postgresql+psycopg://"
        f"{quote(user, safe='')}:{quote(password, safe='')}@{host.lower()}:{port}/"
        f"{quote(database_name, safe='')}"
    )
    return database_url, str(secret_path)


def _read_env_positive_int(name: str, default: int) -> int:
    value = _read_env_optional(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _read_env_bool(name: str, default: bool) -> bool:
    value = _read_env_optional(name)
    if value is None:
        return default
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _normalize_deployment_tenancy_mode(value: str | None) -> str:
    normalized = (value or _DEFAULT_DEPLOYMENT_TENANCY_MODE).strip().upper().replace("-", "_")
    if normalized not in _DEPLOYMENT_TENANCY_MODES:
        allowed = ", ".join(sorted(_DEPLOYMENT_TENANCY_MODES))
        raise ValueError(f"KAKA_DEPLOYMENT_TENANCY_MODE must be one of: {allowed}")
    return normalized


def _parse_allowed_hosts(value: str | None) -> tuple[str, ...]:
    hosts: list[str] = []
    for item in str(value or "").split(","):
        host = item.strip().lower()
        if not host:
            continue
        if host != "*" and not (
            host.startswith("*.") and _PRIVATE_HOSTNAME_PATTERN.fullmatch(host[2:])
        ) and not _PRIVATE_HOSTNAME_PATTERN.fullmatch(host):
            raise ValueError(f"KAKA_API_ALLOWED_HOSTS contains an invalid host: {host!r}")
        if host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _normalize_trusted_proxy_boundary(value: str | None) -> str:
    normalized = (value or "DIRECT_ONLY").strip().upper().replace("-", "_")
    if normalized not in _TRUSTED_PROXY_BOUNDARIES:
        allowed = ", ".join(sorted(_TRUSTED_PROXY_BOUNDARIES))
        raise ValueError(f"KAKA_API_TRUSTED_PROXY_BOUNDARY must be one of: {allowed}")
    return normalized


def _parse_trusted_proxy_ips(value: str | None) -> tuple[str, ...]:
    addresses: list[str] = []
    for item in str(value or "").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        if candidate == "*":
            raise ValueError("KAKA_API_TRUSTED_PROXY_IPS must not trust every address")
        try:
            address = ip_address(candidate)
        except ValueError as exc:
            raise ValueError(
                f"KAKA_API_TRUSTED_PROXY_IPS contains an invalid IP address: {candidate!r}"
            ) from exc
        if not address.is_private or address.is_unspecified or address.is_multicast:
            raise ValueError(
                "KAKA_API_TRUSTED_PROXY_IPS must contain only explicit private proxy addresses"
            )
        normalized = str(address)
        if normalized not in addresses:
            addresses.append(normalized)
    return tuple(addresses)


def _path_contains_namespace(path: Path, namespace: str) -> bool:
    expected = namespace.casefold()
    return any(str(part).casefold() == expected for part in path.parts)


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
    deployment_tenancy_mode: str = _DEFAULT_DEPLOYMENT_TENANCY_MODE
    deployment_tenant_id_optional: Optional[str] = None
    deployment_instance_id_optional: Optional[str] = None
    private_edge_required: bool = False
    private_hostname_optional: Optional[str] = None
    api_allowed_hosts: tuple[str, ...] = ()
    api_trusted_proxy_boundary: str = "DIRECT_ONLY"
    api_trusted_proxy_ips: tuple[str, ...] = ()
    storage_backend: str = _DEFAULT_STORAGE_BACKEND
    storage_path_optional: Optional[str] = None
    storage_database_url_optional: Optional[str] = field(default=None, repr=False)
    storage_database_password_file_optional: Optional[str] = None
    storage_scope: str = _DEFAULT_STORAGE_SCOPE
    storage_runtime_mode: str = _DEFAULT_STORAGE_RUNTIME_MODE
    queue_backend: str = _DEFAULT_QUEUE_BACKEND
    worker_runtime: str = _DEFAULT_WORKER_RUNTIME
    object_storage_backend: str = _DEFAULT_OBJECT_STORAGE_BACKEND
    object_storage_path_optional: Optional[str] = None
    internal_api_token_optional: Optional[str] = None
    internal_api_role: str = "internal_operator"
    internal_api_principals: tuple[InternalApiPrincipal, ...] = ()
    internal_api_principals_file_optional: Optional[str] = None
    operator_artifact_root_optional: Optional[str] = None
    operator_input_root_optional: Optional[str] = None
    api_max_request_body_bytes: int = 2 * 1024 * 1024
    api_expensive_requests_per_minute: int = 20
    api_expensive_concurrency_per_principal: int = 2
    api_public_requests_per_minute: int = 120
    api_public_concurrency_per_client: int = 8
    internal_api_session_ttl_seconds: int = 60 * 60
    internal_object_approval_ttl_seconds: int = 15 * 60
    internal_api_cookie_secure: bool = True
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
        principals, principals_file_optional = _read_internal_api_principals(
            _read_env_optional("KAKA_INTERNAL_API_PRINCIPALS_JSON"),
            _read_env_optional("KAKA_INTERNAL_API_PRINCIPALS_FILE"),
        )
        storage_database_url_optional, storage_database_password_file_optional = (
            resolve_storage_database_url_from_env()
        )
        return cls(
            repo_root=repo_root,
            environment=environment,
            deployment_tenancy_mode=_normalize_deployment_tenancy_mode(
                _read_env_optional("KAKA_DEPLOYMENT_TENANCY_MODE")
            ),
            deployment_tenant_id_optional=_read_env_optional("KAKA_DEPLOYMENT_TENANT_ID"),
            deployment_instance_id_optional=_read_env_optional("KAKA_DEPLOYMENT_INSTANCE_ID"),
            private_edge_required=_read_env_bool("KAKA_PRIVATE_EDGE_REQUIRED", False),
            private_hostname_optional=_read_env_optional("KAKA_PRIVATE_HOSTNAME"),
            api_allowed_hosts=_parse_allowed_hosts(_read_env_optional("KAKA_API_ALLOWED_HOSTS")),
            api_trusted_proxy_boundary=_normalize_trusted_proxy_boundary(
                _read_env_optional("KAKA_API_TRUSTED_PROXY_BOUNDARY")
            ),
            api_trusted_proxy_ips=_parse_trusted_proxy_ips(
                _read_env_optional("KAKA_API_TRUSTED_PROXY_IPS")
            ),
            storage_backend=_read_env_optional("KAKA_STORAGE_BACKEND") or _DEFAULT_STORAGE_BACKEND,
            storage_path_optional=storage_path_optional,
            storage_database_url_optional=storage_database_url_optional,
            storage_database_password_file_optional=storage_database_password_file_optional,
            storage_scope=storage_scope,
            storage_runtime_mode=_resolve_storage_runtime_mode(storage_path_optional, storage_scope),
            queue_backend=_read_env_optional("KAKA_QUEUE_BACKEND") or _DEFAULT_QUEUE_BACKEND,
            worker_runtime=_read_env_optional("KAKA_WORKER_RUNTIME") or _DEFAULT_WORKER_RUNTIME,
            object_storage_backend=(
                _read_env_optional("KAKA_OBJECT_STORAGE_BACKEND")
                or _DEFAULT_OBJECT_STORAGE_BACKEND
            ),
            object_storage_path_optional=_read_env_optional("KAKA_OBJECT_STORAGE_PATH"),
            internal_api_token_optional=_read_env_optional("KAKA_INTERNAL_API_TOKEN"),
            internal_api_role=_read_env_optional("KAKA_INTERNAL_API_ROLE") or "internal_operator",
            internal_api_principals=principals,
            internal_api_principals_file_optional=principals_file_optional,
            operator_artifact_root_optional=_read_env_optional("KAKA_OPERATOR_ARTIFACT_ROOT"),
            operator_input_root_optional=_read_env_optional("KAKA_OPERATOR_INPUT_ROOT"),
            api_max_request_body_bytes=_read_env_positive_int(
                "KAKA_API_MAX_REQUEST_BODY_BYTES",
                2 * 1024 * 1024,
            ),
            api_expensive_requests_per_minute=_read_env_positive_int(
                "KAKA_API_EXPENSIVE_REQUESTS_PER_MINUTE",
                20,
            ),
            api_expensive_concurrency_per_principal=_read_env_positive_int(
                "KAKA_API_EXPENSIVE_CONCURRENCY_PER_PRINCIPAL",
                2,
            ),
            api_public_requests_per_minute=_read_env_positive_int(
                "KAKA_API_PUBLIC_REQUESTS_PER_MINUTE",
                120,
            ),
            api_public_concurrency_per_client=_read_env_positive_int(
                "KAKA_API_PUBLIC_CONCURRENCY_PER_CLIENT",
                8,
            ),
            internal_api_session_ttl_seconds=_read_env_positive_int(
                "KAKA_INTERNAL_API_SESSION_TTL_SECONDS",
                60 * 60,
            ),
            internal_object_approval_ttl_seconds=_read_env_positive_int(
                "KAKA_INTERNAL_OBJECT_APPROVAL_TTL_SECONDS",
                15 * 60,
            ),
            internal_api_cookie_secure=_read_env_bool(
                "KAKA_INTERNAL_API_COOKIE_SECURE",
                True,
            ),
            provider_adapter_config=build_provider_adapter_config_from_env(),
        )

    def is_private_single_tenant_deployment(self) -> bool:
        return self.deployment_tenancy_mode == _PRIVATE_SINGLE_TENANT_MODE

    def deployment_data_namespace(self) -> str | None:
        tenant_id = str(self.deployment_tenant_id_optional or "").strip()
        instance_id = str(self.deployment_instance_id_optional or "").strip()
        if not tenant_id or not instance_id:
            return None
        return f"{tenant_id}-{instance_id}"

    def deployment_boundary_identity(self) -> dict[str, str]:
        readiness = self.deployment_tenancy_readiness()
        if not readiness["private_single_tenant_boundary_ready"]:
            blockers = ", ".join(readiness["blocking_reasons"])
            raise ValueError(f"private single-tenant deployment boundary is not ready: {blockers}")
        tenant_id = str(self.deployment_tenant_id_optional)
        instance_id = str(self.deployment_instance_id_optional)
        namespace = str(self.deployment_data_namespace())
        boundary_key = f"{tenant_id}:{instance_id}:{namespace}"
        return {
            "tenant_id": tenant_id,
            "instance_id": instance_id,
            "data_namespace": namespace,
            "boundary_sha256": sha256(boundary_key.encode("utf-8")).hexdigest(),
        }

    def deployment_tenancy_readiness(self) -> dict[str, Any]:
        private_mode = self.is_private_single_tenant_deployment()
        tenant_id = str(self.deployment_tenant_id_optional or "").strip()
        instance_id = str(self.deployment_instance_id_optional or "").strip()
        namespace = self.deployment_data_namespace()
        blocking_reasons: list[str] = []

        if private_mode:
            if not _DEPLOYMENT_ID_PATTERN.fullmatch(tenant_id):
                blocking_reasons.append("PRIVATE_TENANT_ID_REQUIRED_OR_INVALID")
            if not _DEPLOYMENT_ID_PATTERN.fullmatch(instance_id):
                blocking_reasons.append("PRIVATE_INSTANCE_ID_REQUIRED_OR_INVALID")
            if self.internal_api_token_optional:
                blocking_reasons.append("PRIVATE_LEGACY_SHARED_TOKEN_FORBIDDEN")
            if not self.internal_api_principals:
                blocking_reasons.append("PRIVATE_PRINCIPAL_REGISTRY_REQUIRED")
            if self.storage_scope == _PROCESS_STORAGE_SCOPE:
                blocking_reasons.append("PRIVATE_PROCESS_SCOPED_STORAGE_FORBIDDEN")
            if not self.internal_api_cookie_secure:
                blocking_reasons.append("PRIVATE_SECURE_COOKIE_REQUIRED")

            active_backend = self.normalized_storage_backend()
            if active_backend in {"json-file", "sqlite"}:
                if not self.storage_path_optional:
                    blocking_reasons.append("PRIVATE_EXPLICIT_STORAGE_PATH_REQUIRED")
                elif namespace and not _path_contains_namespace(
                    Path(self.storage_path_optional), namespace
                ):
                    blocking_reasons.append("PRIVATE_STORAGE_PATH_NAMESPACE_MISMATCH")
            elif active_backend in {"sqlalchemy", "postgresql"}:
                database_url = str(self.storage_database_url_optional or "")
                if not database_url:
                    blocking_reasons.append("PRIVATE_DATABASE_URL_REQUIRED")
                else:
                    parsed = urlsplit(database_url)
                    dialect = parsed.scheme.split("+", 1)[0].lower()
                    database_name = unquote(parsed.path.lstrip("/")).strip()
                    if dialect == "sqlite":
                        if namespace and not _path_contains_namespace(
                            Path(unquote(parsed.path)), namespace
                        ):
                            blocking_reasons.append("PRIVATE_DATABASE_NAMESPACE_MISMATCH")
                    elif dialect in {"postgres", "postgresql"}:
                        if not namespace or database_name != namespace:
                            blocking_reasons.append("PRIVATE_DATABASE_NAMESPACE_MISMATCH")
                        if (
                            self.private_edge_required
                            and not self.storage_database_password_file_optional
                        ):
                            blocking_reasons.append(
                                "PRIVATE_DATABASE_PASSWORD_SECRET_FILE_REQUIRED"
                            )
                    else:
                        blocking_reasons.append("PRIVATE_DATABASE_DIALECT_UNSUPPORTED")
            else:
                blocking_reasons.append("PRIVATE_STORAGE_BACKEND_UNSUPPORTED")

            if self.normalized_object_storage_backend() != "local-filesystem":
                blocking_reasons.append("PRIVATE_OBJECT_STORAGE_BACKEND_UNSUPPORTED")
            if not self.object_storage_path_optional:
                blocking_reasons.append("PRIVATE_EXPLICIT_OBJECT_STORAGE_PATH_REQUIRED")
            elif namespace and not _path_contains_namespace(
                Path(self.object_storage_path_optional), namespace
            ):
                blocking_reasons.append("PRIVATE_OBJECT_STORAGE_NAMESPACE_MISMATCH")
            if not self.operator_artifact_root_optional:
                blocking_reasons.append("PRIVATE_EXPLICIT_ARTIFACT_ROOT_REQUIRED")
            elif namespace and not _path_contains_namespace(
                Path(self.operator_artifact_root_optional), namespace
            ):
                blocking_reasons.append("PRIVATE_ARTIFACT_ROOT_NAMESPACE_MISMATCH")
            if (
                self.operator_input_root_optional
                and namespace
                and not _path_contains_namespace(Path(self.operator_input_root_optional), namespace)
            ):
                blocking_reasons.append("PRIVATE_INPUT_ROOT_NAMESPACE_MISMATCH")
            if self.private_edge_required:
                hostname = str(self.private_hostname_optional or "").strip().lower()
                if not _PRIVATE_HOSTNAME_PATTERN.fullmatch(hostname):
                    blocking_reasons.append("PRIVATE_EDGE_HOSTNAME_REQUIRED_OR_INVALID")
                if not self.internal_api_principals_file_optional:
                    blocking_reasons.append("PRIVATE_EDGE_PRINCIPAL_SECRET_FILE_REQUIRED")
                if not self.api_allowed_hosts or "*" in self.api_allowed_hosts:
                    blocking_reasons.append("PRIVATE_EDGE_EXPLICIT_ALLOWED_HOSTS_REQUIRED")
                elif hostname and hostname not in self.api_allowed_hosts:
                    blocking_reasons.append("PRIVATE_EDGE_HOSTNAME_NOT_ALLOWED")
                if self.api_trusted_proxy_boundary != "PRIVATE_EDGE_NETWORK_ONLY":
                    blocking_reasons.append("PRIVATE_EDGE_TRUSTED_PROXY_BOUNDARY_REQUIRED")
                if not self.api_trusted_proxy_ips:
                    blocking_reasons.append("PRIVATE_EDGE_EXPLICIT_TRUSTED_PROXY_IP_REQUIRED")

        boundary_ready = private_mode and not blocking_reasons
        namespace_sha256 = (
            sha256(str(namespace).encode("utf-8")).hexdigest() if namespace else None
        )
        return {
            "deployment_tenancy_mode": self.deployment_tenancy_mode,
            "configuration_valid": not blocking_reasons,
            "private_single_tenant_mode": private_mode,
            "private_single_tenant_boundary_ready": boundary_ready,
            "single_customer_per_deployment": private_mode,
            "deployment_tenant_id_configured": bool(tenant_id),
            "deployment_instance_id_configured": bool(instance_id),
            "deployment_data_namespace_configured": bool(namespace),
            "deployment_data_namespace_sha256": namespace_sha256,
            "principal_registry_required": private_mode,
            "legacy_shared_token_allowed": not private_mode,
            "storage_boundary_seal_required": private_mode,
            "object_storage_boundary_seal_required": private_mode,
            "private_edge_required": self.private_edge_required,
            "private_edge_configuration_ready": bool(
                private_mode
                and self.private_edge_required
                and not any(reason.startswith("PRIVATE_EDGE_") for reason in blocking_reasons)
            ),
            "private_hostname_configured": bool(self.private_hostname_optional),
            "api_allowed_host_count": len(self.api_allowed_hosts),
            "api_trusted_proxy_boundary": self.api_trusted_proxy_boundary,
            "api_trusted_proxy_ip_count": len(self.api_trusted_proxy_ips),
            "principal_secret_file_configured": bool(
                self.internal_api_principals_file_optional
            ),
            "cross_tenant_routing_enabled": False,
            "tenant_id_on_business_objects": False,
            "multi_tenant_saas_ready": False,
            "blocking_reasons": blocking_reasons,
        }

    def assert_deployment_tenancy_boundary(self) -> None:
        readiness = self.deployment_tenancy_readiness()
        if self.is_private_single_tenant_deployment() and not readiness[
            "private_single_tenant_boundary_ready"
        ]:
            blockers = ", ".join(readiness["blocking_reasons"])
            raise ValueError(f"private single-tenant deployment boundary is not ready: {blockers}")

    def internal_api_auth_readiness(self) -> dict[str, Any]:
        principals = self.configured_internal_api_principals()
        requesters = [
            principal
            for principal in principals
            if principal.role in {"owner", "operator", "admin"}
        ]
        decision_makers = [
            principal
            for principal in principals
            if principal.role in {"reviewer", "admin"}
        ]
        object_approval_workflow_ready = any(
            requester.principal_id != decision_maker.principal_id
            for requester in requesters
            for decision_maker in decision_makers
        )
        return {
            "auth_required": True,
            "auth_scheme": "bearer",
            "token_configured": bool(principals),
            "principal_count": len(principals),
            "configured_roles": sorted({principal.role for principal in principals}),
            "principal_config_source": (
                "secret_file"
                if self.internal_api_principals_file_optional
                else "environment"
                if self.internal_api_principals
                else "legacy_environment"
                if self.internal_api_token_optional
                else "not_configured"
            ),
            "supported_roles": sorted(_INTERNAL_API_ROLES),
            "authentication_implies_object_approval": False,
            "object_approval_workflow_ready": object_approval_workflow_ready,
            "object_approval_requester_count": len(requesters),
            "object_approval_decision_maker_count": len(decision_makers),
            "object_approval_requires_distinct_principals": True,
            "network_request_without_configured_token_state": "SERVICE_UNAVAILABLE_FAIL_CLOSED",
            "request_boolean_auth_allowed": False,
            "browser_session_enabled": True,
            "browser_session_ttl_seconds": self.internal_api_session_ttl_seconds,
            "object_approval_ttl_seconds": self.internal_object_approval_ttl_seconds,
            "browser_session_cookie_http_only": True,
            "browser_session_cookie_same_site": "strict",
            "browser_session_cookie_secure": self.internal_api_cookie_secure,
            "browser_session_csrf_required_for_unsafe_methods": True,
        }

    def configured_internal_api_principals(self) -> tuple[InternalApiPrincipal, ...]:
        principals = list(self.internal_api_principals)
        if self.internal_api_token_optional:
            legacy = InternalApiPrincipal(
                principal_id="configured-internal-operator",
                role=normalize_internal_api_role(self.internal_api_role),
                token=self.internal_api_token_optional,
            )
            if any(principal.token == legacy.token for principal in principals):
                raise ValueError("legacy and principal registry tokens must be distinct")
            if any(principal.principal_id == legacy.principal_id for principal in principals):
                raise ValueError("legacy and principal registry principal_ids must be distinct")
            principals.append(legacy)
        return tuple(principals)

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
            private_pilot_deployment=(
                self.is_private_single_tenant_deployment() and self.private_edge_required
            ),
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
        from storage.sqlalchemy_backend import REQUIRED_STORAGE_SCHEMA_REVISION

        active_backend = self.normalized_storage_backend()
        readiness = self.platform_infra_readiness()
        return {
            "active_backend": active_backend,
            "storage_backend": self.storage_backend,
            "storage_path": str(self.resolved_storage_path()),
            "storage_path_optional": self.storage_path_optional,
            "storage_database_url_configured": bool(self.storage_database_url_optional),
            "storage_database_password_file_configured": bool(
                self.storage_database_password_file_optional
            ),
            "storage_database_url_redacted": readiness["storage_database_url_redacted"],
            "storage_database_url_dialect": readiness["storage_database_url_dialect"],
            "storage_schema_revision": None,
            "required_storage_schema_revision": REQUIRED_STORAGE_SCHEMA_REVISION,
            "storage_schema_revision_ready": active_backend != "postgresql",
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
            "deployment_tenancy_readiness": self.deployment_tenancy_readiness(),
        }

    def provider_adapter_readiness_summary(self) -> dict[str, Any]:
        config = self.provider_adapter_config or build_provider_adapter_config_from_env()
        return build_provider_adapter_readiness_summary(config)

    def provider_adapter_bootstrap_payload(self) -> dict[str, Any]:
        return provider_adapter_bootstrap_payload(self.provider_adapter_readiness_summary())


__all__ = ["InternalApiPrincipal", "Settings", "resolve_storage_database_url_from_env"]
