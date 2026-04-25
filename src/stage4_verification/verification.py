# Stage: stage4_verification
# Consumes formal objects: public_attack_surface, focus_bidder_verification_profile, pseudo_competitor_signal_set, evidence_grade_profile
# Dependent handoff: H-03-STAGE3-TO-STAGE4, H-04-STAGE4-TO-STAGE5
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from shared.utils import utc_now_iso
from stage4_verification.evidence_grade import grade_public_verification_evidence
from storage.repositories.object_storage_repo import ObjectStorageRepository


@dataclass(frozen=True)
class FocusBidderVerificationProfile:
    verification_profile_id: str
    # TODO: align with contracts/schemas/schema_catalog.json


@dataclass(frozen=True)
class PseudoCompetitorSignalSet:
    signal_set_id: str
    # TODO: align with contracts/schemas/schema_catalog.json


PUBLIC_VERIFICATION_PROVIDER = "stage4-public-verification-readback"
PUBLIC_VERIFICATION_PROVIDER_VERSION = "stage4-public-verification-adapter-v1"

MATCHED = "MATCHED"
NOT_MATCHED = "NOT_MATCHED"
CONFLICT = "CONFLICT"
INSUFFICIENT_PUBLIC_EVIDENCE = "INSUFFICIENT_PUBLIC_EVIDENCE"
REVIEW_REQUIRED = "REVIEW_REQUIRED"

SOURCE_NOT_PUBLIC = "SOURCE_NOT_PUBLIC"
SNAPSHOT_NOT_REPLAYABLE = "SNAPSHOT_NOT_REPLAYABLE"
PARSED_FIELD_UNVERIFIED = "PARSED_FIELD_UNVERIFIED"
TARGET_IDENTIFIER_MISSING = "TARGET_IDENTIFIER_MISSING"
AMBIGUOUS_PUBLIC_MATCH = "AMBIGUOUS_PUBLIC_MATCH"
SOURCE_CONFLICT = "SOURCE_CONFLICT"
WEAK_PUBLIC_EVIDENCE = "WEAK_PUBLIC_EVIDENCE"
PROVIDER_RESERVED_NOT_LIVE = "PROVIDER_RESERVED_NOT_LIVE"

PUBLIC_VERIFICATION_FAILURE_TAXONOMY = (
    SOURCE_NOT_PUBLIC,
    SNAPSHOT_NOT_REPLAYABLE,
    PARSED_FIELD_UNVERIFIED,
    TARGET_IDENTIFIER_MISSING,
    AMBIGUOUS_PUBLIC_MATCH,
    SOURCE_CONFLICT,
    WEAK_PUBLIC_EVIDENCE,
    PROVIDER_RESERVED_NOT_LIVE,
)

SUPPORTED_PUBLIC_VERIFICATION_TARGET_TYPES = (
    "enterprise_public_record",
    "personnel_public_record",
    "enterprise_qualification",
    "credit_penalty_blacklist",
    "construction_permit",
    "contract_public_info",
    "completion_filing",
    "performance_public_record",
)

PUBLIC_VISIBLE_STATES = frozenset(
    {
        "PUBLIC",
        "PUBLIC_VISIBLE",
        "PUBLIC_SOURCE",
        "SANDBOX_LOCAL_MIRROR",
    }
)


@dataclass(frozen=True)
class PublicVerificationCarrier:
    verification_run_id: str
    verification_target_id: str
    verification_target_type: str
    input_parse_run_id: str
    parsed_field_refs: list[dict[str, Any]]
    source_snapshot_id: str
    source_url: str | None
    public_visibility_state: str
    verification_provider: str
    provider_version: str
    verification_result: str
    evidence_grade: str
    confidence: float
    verified_at: str
    source_refs: list[dict[str, Any]]
    snapshot_refs: list[dict[str, Any]]
    failure_reason_optional: str | None
    review_required: bool
    public_only: bool = True
    non_public_source_used: bool = False
    customer_visible: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["parsed_field_refs"] = [dict(ref) for ref in self.parsed_field_refs]
        payload["source_refs"] = [dict(ref) for ref in self.source_refs]
        payload["snapshot_refs"] = [dict(ref) for ref in self.snapshot_refs]
        return payload


class PublicVerificationAdapter:
    def __init__(
        self,
        *,
        repository: ObjectStorageRepository | None = None,
        provider: str = PUBLIC_VERIFICATION_PROVIDER,
        provider_version: str = PUBLIC_VERIFICATION_PROVIDER_VERSION,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.provider_version = provider_version

    def verify(
        self,
        parsed_carrier: Mapping[str, Any],
        *,
        target: Mapping[str, Any],
        repository: ObjectStorageRepository | None = None,
        snapshot_readback: Mapping[str, Any] | None = None,
    ) -> PublicVerificationCarrier:
        carrier = dict(parsed_carrier)
        target_map = dict(target)
        parsed_fields = [_field_mapping(field) for field in _list(carrier.get("parsed_fields"))]
        source_snapshot_id = _first_non_empty(
            target_map.get("source_snapshot_id"),
            carrier.get("snapshot_id"),
        )
        readback = self._readback(
            source_snapshot_id,
            repository=repository,
            snapshot_readback=snapshot_readback,
        )
        manifest = _mapping(readback.get("manifest"))
        raw_snapshot_metadata = _mapping(manifest.get("raw_snapshot_metadata"))
        source_health = _mapping(manifest.get("source_health"))
        public_visibility_state = _visibility_state(
            target_map,
            carrier,
            manifest,
            raw_snapshot_metadata,
        )
        source_url = _first_non_empty(
            target_map.get("source_url"),
            carrier.get("source_url"),
            manifest.get("source_url_optional"),
            raw_snapshot_metadata.get("source_url"),
        )
        source_family = _first_non_empty(
            carrier.get("source_family"),
            manifest.get("source_family_optional"),
            raw_snapshot_metadata.get("source_family"),
            source_health.get("source_family"),
        )
        source_registry_id = _first_non_empty(
            carrier.get("source_registry_id"),
            raw_snapshot_metadata.get("source_registry_id"),
            _mapping(manifest.get("lineage_refs")).get("source_registry_id"),
        )

        target_type = str(
            target_map.get("verification_target_type")
            or target_map.get("target_type")
            or "unknown_public_verification_target"
        )
        target_identifier = _normalize_text(
            target_map.get("target_identifier")
            or target_map.get("identifier")
            or ""
        )
        target_id = str(
            target_map.get("verification_target_id")
            or target_map.get("target_id")
            or _stable_id("ST4T", target_type, target_identifier, carrier.get("parse_run_id"))
        )
        parse_run_id = str(carrier.get("parse_run_id") or "")
        requested_provider = str(
            target_map.get("verification_provider")
            or target_map.get("requested_provider")
            or self.provider
        )
        live_provider_requested = bool(
            target_map.get("live_provider_requested")
            or target_map.get("real_provider_requested")
        )

        parsed_field_refs = _parsed_field_refs(parsed_fields)
        snapshot_refs = [
            _snapshot_ref(
                source_snapshot_id=source_snapshot_id,
                readback=readback,
                manifest=manifest,
            )
        ]
        source_refs = [
            {
                "source_url": source_url,
                "source_family": source_family,
                "source_registry_id": source_registry_id,
                "source_snapshot_id": source_snapshot_id,
                "public_visibility_state": public_visibility_state,
                "stage3_verification_state": carrier.get("verification_state"),
                "parser_version": carrier.get("parser_version"),
            }
        ]

        replayable = bool(readback.get("replayable"))
        public_source = public_visibility_state in PUBLIC_VISIBLE_STATES
        matching_fields = _matching_fields(parsed_fields, target_identifier)
        field_confidence = _field_confidence(matching_fields or parsed_fields)
        snapshot_text = _snapshot_text(readback)
        snapshot_matches = bool(target_identifier) and _contains_normalized(
            snapshot_text,
            target_identifier,
        )
        field_matches = bool(matching_fields)
        matched = field_matches and snapshot_matches
        distinct_values = _distinct_field_values(matching_fields)
        ambiguous = bool(target_map.get("ambiguous_public_match")) or len(distinct_values) > 1
        conflict = bool(target_map.get("source_conflict")) or bool(carrier.get("source_conflict"))
        weak = (
            field_confidence < 0.75
            or any(bool(field.get("review_required")) for field in matching_fields)
            or bool(target_map.get("weak_public_evidence"))
        )

        failure_reason, result = self._decision(
            requested_provider=requested_provider,
            live_provider_requested=live_provider_requested,
            replayable=replayable,
            public_source=public_source,
            target_identifier=target_identifier,
            conflict=conflict,
            ambiguous=ambiguous,
            weak=weak,
            matched=matched,
        )
        evidence_grade = grade_public_verification_evidence(
            replayable_snapshot=replayable,
            public_source=public_source,
            matched=matched and failure_reason is None,
            conflict=conflict,
            ambiguous=ambiguous,
            weak=weak or failure_reason == WEAK_PUBLIC_EVIDENCE,
        )
        confidence = _confidence(
            result=result,
            field_confidence=field_confidence,
            replayable=replayable,
            public_source=public_source,
            matched=matched,
        )
        review_required = result != MATCHED or failure_reason is not None

        return PublicVerificationCarrier(
            verification_run_id=_stable_id(
                "ST4PV",
                parse_run_id,
                target_id,
                source_snapshot_id,
                self.provider_version,
            ),
            verification_target_id=target_id,
            verification_target_type=target_type,
            input_parse_run_id=parse_run_id,
            parsed_field_refs=parsed_field_refs,
            source_snapshot_id=source_snapshot_id,
            source_url=source_url,
            public_visibility_state=public_visibility_state,
            verification_provider=self.provider,
            provider_version=self.provider_version,
            verification_result=result,
            evidence_grade=evidence_grade,
            confidence=confidence,
            verified_at=utc_now_iso(),
            source_refs=source_refs,
            snapshot_refs=snapshot_refs,
            failure_reason_optional=failure_reason,
            review_required=review_required,
        )

    def _readback(
        self,
        source_snapshot_id: str,
        *,
        repository: ObjectStorageRepository | None,
        snapshot_readback: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if snapshot_readback is not None:
            return dict(snapshot_readback)
        if not source_snapshot_id:
            return {
                "snapshot_id": source_snapshot_id,
                "readback_state": "MISSING_SNAPSHOT_ID",
                "manifest_present": False,
                "object_present": False,
                "replayable": False,
                "fail_closed": True,
                "no_broad_fallback": True,
                "external_service_connection_enabled": False,
            }
        resolved_repository = repository or self.repository
        if resolved_repository is None:
            return {
                "snapshot_id": source_snapshot_id,
                "readback_state": "SNAPSHOT_REPOSITORY_NOT_PROVIDED",
                "manifest_present": False,
                "object_present": False,
                "replayable": False,
                "fail_closed": True,
                "no_broad_fallback": True,
                "external_service_connection_enabled": False,
            }
        return dict(resolved_repository.replay_snapshot(source_snapshot_id))

    def _decision(
        self,
        *,
        requested_provider: str,
        live_provider_requested: bool,
        replayable: bool,
        public_source: bool,
        target_identifier: str,
        conflict: bool,
        ambiguous: bool,
        weak: bool,
        matched: bool,
    ) -> tuple[str | None, str]:
        if requested_provider != self.provider or live_provider_requested:
            return PROVIDER_RESERVED_NOT_LIVE, REVIEW_REQUIRED
        if not replayable:
            return SNAPSHOT_NOT_REPLAYABLE, INSUFFICIENT_PUBLIC_EVIDENCE
        if not public_source:
            return SOURCE_NOT_PUBLIC, REVIEW_REQUIRED
        if not target_identifier:
            return TARGET_IDENTIFIER_MISSING, REVIEW_REQUIRED
        if conflict:
            return SOURCE_CONFLICT, CONFLICT
        if ambiguous:
            return AMBIGUOUS_PUBLIC_MATCH, REVIEW_REQUIRED
        if weak:
            return WEAK_PUBLIC_EVIDENCE, INSUFFICIENT_PUBLIC_EVIDENCE
        if matched:
            return None, MATCHED
        return PARSED_FIELD_UNVERIFIED, NOT_MATCHED


def build_public_verification_readback(carrier: Mapping[str, Any]) -> dict[str, Any]:
    required_fields = (
        "verification_run_id",
        "verification_target_id",
        "verification_target_type",
        "input_parse_run_id",
        "parsed_field_refs",
        "source_snapshot_id",
        "source_refs",
        "snapshot_refs",
        "verification_result",
        "evidence_grade",
        "confidence",
    )
    missing = [field_name for field_name in required_fields if carrier.get(field_name) in (None, "", [])]
    snapshot_refs = _list(carrier.get("snapshot_refs"))
    replayable = not missing and all(bool(_mapping(ref).get("replayable")) for ref in snapshot_refs)
    return {
        "readback_state": "READBACK_READY" if replayable else "FAIL_CLOSED_INCOMPLETE_OR_NON_REPLAYABLE",
        "replayable": replayable,
        "fail_closed": not replayable,
        "no_broad_fallback": True,
        "public_only": bool(carrier.get("public_only", True)),
        "customer_visible": False,
        "no_legal_conclusion": True,
        "missing_required_fields": missing,
        "verification_run_id": carrier.get("verification_run_id"),
        "verification_result": carrier.get("verification_result"),
        "review_required": bool(carrier.get("review_required")),
    }


def _field_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value not in (None, ""):
            return str(value)
    return ""


def _visibility_state(
    target: Mapping[str, Any],
    carrier: Mapping[str, Any],
    manifest: Mapping[str, Any],
    raw_snapshot_metadata: Mapping[str, Any],
) -> str:
    return _first_non_empty(
        target.get("public_visibility_state"),
        carrier.get("public_visibility_state"),
        manifest.get("source_visibility_state_optional"),
        raw_snapshot_metadata.get("source_visibility_state"),
        "UNKNOWN",
    )


def _parsed_field_refs(fields: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for index, field in enumerate(fields):
        refs.append(
            {
                "field_name": field.get("field_name"),
                "field_value_optional": field.get("field_value_optional"),
                "source_file_ref": field.get("source_file_ref"),
                "source_page_optional": field.get("source_page_optional"),
                "source_slice_sha256": field.get("source_slice_sha256"),
                "confidence": _float(field.get("confidence"), 0.0),
                "parser_version": field.get("parser_version"),
                "review_required": bool(field.get("review_required")),
                "field_ref": _stable_id(
                    "ST3FIELD",
                    index,
                    field.get("field_name"),
                    field.get("source_slice_sha256"),
                ),
            }
        )
    return refs


def _snapshot_ref(
    *,
    source_snapshot_id: str,
    readback: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "snapshot_id": source_snapshot_id,
        "readback_state": readback.get("readback_state"),
        "manifest_present": bool(readback.get("manifest_present")),
        "object_present": bool(readback.get("object_present")),
        "replayable": bool(readback.get("replayable")),
        "sha256": readback.get("sha256") or manifest.get("sha256"),
        "object_key": readback.get("object_key") or manifest.get("object_key"),
        "no_broad_fallback": bool(readback.get("no_broad_fallback", True)),
        "external_service_connection_enabled": False,
    }


def _matching_fields(fields: list[Mapping[str, Any]], target_identifier: str) -> list[Mapping[str, Any]]:
    if not target_identifier:
        return []
    return [
        field
        for field in fields
        if _contains_normalized(field.get("field_value_optional"), target_identifier)
        or _contains_normalized(field.get("source_slice"), target_identifier)
    ]


def _distinct_field_values(fields: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for field in fields:
        value = _normalize_text(field.get("field_value_optional") or "")
        if value and value not in values:
            values.append(value)
    return values


def _field_confidence(fields: list[Mapping[str, Any]]) -> float:
    values = [_float(field.get("confidence"), 0.0) for field in fields]
    if not values:
        return 0.0
    return round(min(values), 4)


def _confidence(
    *,
    result: str,
    field_confidence: float,
    replayable: bool,
    public_source: bool,
    matched: bool,
) -> float:
    if not replayable or not public_source:
        return 0.0
    if result == MATCHED and matched:
        return round(min(field_confidence, 0.95), 4)
    if result in {CONFLICT, REVIEW_REQUIRED, INSUFFICIENT_PUBLIC_EVIDENCE}:
        return round(min(field_confidence, 0.49), 4)
    return round(min(field_confidence, 0.7), 4)


def _snapshot_text(readback: Mapping[str, Any]) -> str:
    data = readback.get("bytes")
    if not isinstance(data, bytes):
        return ""
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return ""


def _contains_normalized(value: Any, needle: str) -> bool:
    haystack = _normalize_text(value)
    normalized_needle = _normalize_text(needle)
    return bool(normalized_needle) and normalized_needle in haystack


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _stable_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256(
        "|".join(str(part or "") for part in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}-{digest[:20]}"


__all__ = [
    "AMBIGUOUS_PUBLIC_MATCH",
    "CONFLICT",
    "FocusBidderVerificationProfile",
    "INSUFFICIENT_PUBLIC_EVIDENCE",
    "MATCHED",
    "NOT_MATCHED",
    "PARSED_FIELD_UNVERIFIED",
    "PROVIDER_RESERVED_NOT_LIVE",
    "PUBLIC_VERIFICATION_FAILURE_TAXONOMY",
    "PUBLIC_VERIFICATION_PROVIDER",
    "PUBLIC_VERIFICATION_PROVIDER_VERSION",
    "PublicVerificationAdapter",
    "PublicVerificationCarrier",
    "REVIEW_REQUIRED",
    "SNAPSHOT_NOT_REPLAYABLE",
    "SOURCE_CONFLICT",
    "SOURCE_NOT_PUBLIC",
    "SUPPORTED_PUBLIC_VERIFICATION_TARGET_TYPES",
    "TARGET_IDENTIFIER_MISSING",
    "WEAK_PUBLIC_EVIDENCE",
    "PseudoCompetitorSignalSet",
    "build_public_verification_readback",
]
