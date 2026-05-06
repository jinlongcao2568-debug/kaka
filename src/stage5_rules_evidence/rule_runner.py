# Stage: stage5_rules_evidence
# Consumes formal objects: rule_hit, evidence, rule_gate_decision, evidence_gate_decision, review_request
# Dependent handoff: H-04-STAGE4-TO-STAGE5, H-05-STAGE5-TO-STAGE6
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, contracts/rules/rule_catalog.json, contracts/gates/gate_policies.json

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from shared.contracts_runtime import ContractStore
from shared.utils import apply_rule, build_id, ensure_enum, ensure_list, get_flag
from stage4_verification.public_evidence_readback import (
    PUBLIC_EVIDENCE_RULE_CODES,
    evaluate_public_evidence_gate,
    normalize_public_evidence_readbacks,
)
from stage5_rules_evidence.evidence_builder import EvidenceArtifacts


QUAL_PM_RULE_CODES = ("QUAL-PM-001", "QUAL-PM-002", "QUAL-PM-003", "QUAL-PM-004")
QUAL_PM_RULE_NAMES = {
    "QUAL-PM-001": "公告项目负责人证书号同单位公开记录未确认",
    "QUAL-PM-002": "同单位人员未公开确认为一级注册建造师",
    "QUAL-PM-003": "注册专业未公开确认或与招标要求不一致",
    "QUAL-PM-004": "安全B证不能替代注册建造师资格",
}
QUAL_PM_OFFICIAL_CHECKS = {
    "QUAL-PM-001": "请交易中心或主管部门核查公告证书号是否属于该单位拟派项目负责人。",
    "QUAL-PM-002": "请主管部门核查拟派项目负责人是否具备一级注册建造师资格。",
    "QUAL-PM-003": "请主管部门核查拟派项目负责人的注册专业是否满足招标要求。",
    "QUAL-PM-004": "请主管部门核查安全生产考核B证是否仅作为附加条件，不作为注册建造师资格替代。",
}


def evaluate_project_manager_qualification_rules(readback: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate cautious Stage5 project-manager qualification rule states."""
    carrier = dict(readback or {})
    all_failure_reasons = _qualification_failure_reasons(carrier)
    required_certificate_type = str(
        carrier.get("required_certificate_type")
        or carrier.get("required_registration_category")
        or ""
    )
    required_title = str(carrier.get("required_title") or carrier.get("professional_title_requirement") or "")
    non_constructor_requirement = _is_non_constructor_certificate_requirement(required_certificate_type)
    title_only_requirement = bool(required_title and not required_certificate_type)
    announced_certificate_same_company_match = bool(
        carrier.get("announced_certificate_same_company_match")
        or carrier.get("registration_certificate_publicly_confirmed")
    )
    first_class_constructor_confirmed = bool(
        carrier.get("first_class_constructor_publicly_confirmed")
        or carrier.get("required_registration_category_publicly_confirmed")
    )
    required_profession_confirmed = bool(
        carrier.get("required_registration_profession_publicly_confirmed")
    )
    safety_b_certificate_present = bool(
        carrier.get("safety_b_certificate_present")
        or carrier.get("safety_b_certificate_no")
        or carrier.get("safety_b_certificate_no_optional")
    )

    rule_results = []
    rule_results.append(
        _qualification_rule_result(
            "QUAL-PM-001",
            "PASS" if announced_certificate_same_company_match else "NOT_CONFIRMED",
            all_failure_reasons,
            fallback_reason="announced_certificate_no_not_confirmed_in_same_company_public_records",
        )
    )
    rule_results.append(
        _qualification_rule_result(
            "QUAL-PM-002",
            "NOT_APPLICABLE"
            if non_constructor_requirement or title_only_requirement
            else "PASS"
            if first_class_constructor_confirmed
            else "NOT_CONFIRMED",
            all_failure_reasons,
            fallback_reason=(
                "first_class_constructor_rule_not_applicable_to_non_constructor_requirement"
                if non_constructor_requirement or title_only_requirement
                else "first_class_constructor_registration_not_publicly_confirmed"
            ),
        )
    )
    profession_conflict = any(
        reason == "matched_certificate_profession_conflicts_with_requirement"
        for reason in all_failure_reasons
    )
    rule_results.append(
        _qualification_rule_result(
            "QUAL-PM-003",
            "PASS"
            if required_profession_confirmed
            else "REVIEW_REQUIRED"
            if profession_conflict
            else "NOT_CONFIRMED",
            all_failure_reasons,
            fallback_reason="required_registration_profession_not_publicly_confirmed",
        )
    )
    safety_b_needs_review = safety_b_certificate_present and not announced_certificate_same_company_match
    rule_results.append(
        _qualification_rule_result(
            "QUAL-PM-004",
            "NOT_APPLICABLE"
            if (non_constructor_requirement or title_only_requirement) and not safety_b_certificate_present
            else "REVIEW_REQUIRED"
            if safety_b_needs_review
            else "PASS",
            all_failure_reasons,
            fallback_reason=(
                "safety_b_rule_not_applicable_without_safety_b_requirement"
                if (non_constructor_requirement or title_only_requirement) and not safety_b_certificate_present
                else "safety_b_certificate_cannot_substitute_national_constructor_registration"
            ),
        )
    )

    overall_state = "PASS"
    if any(result["status"] == "REVIEW_REQUIRED" for result in rule_results):
        overall_state = "REVIEW_REQUIRED"
    elif any(result["status"] == "NOT_CONFIRMED" for result in rule_results):
        overall_state = "NOT_CONFIRMED"
    elif all(result["status"] == "NOT_APPLICABLE" for result in rule_results):
        overall_state = "NOT_APPLICABLE"
    return {
        "readback_state": carrier.get("readback_state", "READBACK_READY"),
        "qualification_run_id": carrier.get("qualification_run_id"),
        "overall_status": overall_state,
        "rule_results": rule_results,
        "failure_reasons": all_failure_reasons,
        "official_check_recommendations": [
            result["official_check_recommendation"]
            for result in rule_results
            if result["status"] not in {"PASS", "NOT_APPLICABLE"}
        ],
        "public_only": True,
        "customer_visible": False,
        "no_legal_conclusion": True,
    }


def _qualification_rule_result(
    rule_code: str,
    status: str,
    failure_reasons: list[str],
    *,
    fallback_reason: str,
) -> dict[str, Any]:
    reasons = list(failure_reasons)
    if status != "PASS" and fallback_reason not in reasons:
        reasons.append(fallback_reason)
    return {
        "rule_code": rule_code,
        "rule_name": QUAL_PM_RULE_NAMES[rule_code],
        "status": status,
        "failure_reasons": [] if status == "PASS" else reasons,
        "official_check_recommendation": QUAL_PM_OFFICIAL_CHECKS[rule_code],
        "no_legal_conclusion": True,
    }


def _qualification_failure_reasons(readback: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for key in ("failure_reasons", "review_reasons"):
        reasons.extend(str(value) for value in ensure_list(readback.get(key)) if value not in (None, ""))
    for nested_key in (
        "jzsc",
        "jzsc_readback",
        "jzsc_personnel_carrier",
        "guangdong_three_library_person_directory",
        "gdcic_person_directory",
        "person_directory_readback",
    ):
        nested = readback.get(nested_key)
        if not isinstance(nested, Mapping):
            continue
        for key in ("failure_reasons", "review_reasons"):
            reasons.extend(str(value) for value in ensure_list(nested.get(key)) if value not in (None, ""))
        for result in ensure_list(nested.get("source_results")):
            if not isinstance(result, Mapping):
                continue
            reasons.extend(
                str(value)
                for value in ensure_list(result.get("failure_reasons"))
                if value not in (None, "")
            )
    return list(dict.fromkeys(reasons))


def _is_non_constructor_certificate_requirement(certificate_type: str) -> bool:
    text = str(certificate_type or "")
    if not text or "建造师" in text:
        return False
    return bool(
        any(
            token in text
            for token in (
                "注册土木工程师",
                "注册建筑师",
                "注册结构工程师",
                "注册电气工程师",
                "注册公用设备工程师",
                "注册化工工程师",
                "注册环保工程师",
                "注册监理工程师",
            )
        )
    )


@dataclass(frozen=True)
class RuleArtifacts:
    rule_hit: Any
    rule_hits: list[Any]
    rule_gate_decision: Any
    rule_selection_trace: list[dict[str, Any]]
    rule_execution_trace: list[dict[str, Any]]
    rule_coverage_summary: dict[str, Any]
    rule_hit_state: str
    rule_gate_status: str
    lineage_status: str
    conflict_state: str


class RuleRunner:
    FIRST_SLICE_SUPPORTED_UPSTREAM_OBJECTS = frozenset(
        {
            "clock_chain_profile",
            "evidence_grade_profile",
            "field_lineage_record",
            "focus_bidder_verification_profile",
            "notice_version_chain",
            "pseudo_competitor_signal_set",
            "public_attack_surface",
            "public_chain",
        }
    )
    # Compatibility labels retained for existing anti-drift guards:
    # selected_first_slice_priority, not_in_first_slice_priority, unsupported_upstream_objects.
    LEGACY_SELECTION_REASON_ALIASES = {
        "selected_first_slice_priority": "selected_catalog_priority",
        "not_in_first_slice_priority": "skipped_by_priority_limit",
        "unsupported_upstream_objects": "unsupported_upstream_objects",
    }
    RULE_SOURCE_OBJECT_REF_FIELDS = {
        "PROC-001": (
            "public_attack_surface_id",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ),
        "PROC-002": (
            "winning_version_resolution_rule_id",
            "clock_resolution_rule_id",
            "clock_precedence_rule_id",
        ),
        "DOC-001": (
            "winning_version_resolution_rule_id",
            "verification_profile_id",
            "public_attack_surface_id",
        ),
        "PM-001": (
            "project_manager_active_conflict_readback.active_conflict_run_id",
            "project_manager_active_conflict_readback.registration_timeline_verification.registration_at",
            "project_manager_active_conflict_readback.project_timeline_evidence_refs",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "PM-002": (
            "project_manager_active_conflict_readback.active_conflict_run_id",
            "project_manager_active_conflict_readback.project_timeline_evidence_refs",
            "project_manager_active_conflict_readback.risk_signal_evidence_refs",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "QUAL-PM-001": (
            "project_manager_qualification_readback.qualification_run_id",
            "project_manager_qualification_readback.announced_certificate_no",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "QUAL-PM-002": (
            "project_manager_qualification_readback.qualification_run_id",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "QUAL-PM-003": (
            "project_manager_qualification_readback.qualification_run_id",
            "project_manager_qualification_readback.required_registration_profession_keywords",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "QUAL-PM-004": (
            "project_manager_qualification_readback.qualification_run_id",
            "project_manager_id_optional",
            "verification_profile_id",
        ),
        "CREDIT-001": (
            "stage4_public_evidence_readbacks",
            "stage4_public_evidence_refs",
            "verification_profile_id",
            "evidence_grade_profile_id",
        ),
        "REL-001": (
            "stage4_public_evidence_readbacks",
            "stage4_public_evidence_refs",
            "verification_profile_id",
        ),
        "ENG-001": (
            "stage4_public_evidence_readbacks",
            "stage4_public_evidence_refs",
            "verification_profile_id",
            "evidence_grade_profile_id",
        ),
        "ENG-002": (
            "stage4_public_evidence_readbacks",
            "stage4_public_evidence_refs",
            "verification_profile_id",
            "evidence_grade_profile_id",
        ),
        "PERF-001": (
            "stage4_public_evidence_readbacks",
            "stage4_public_evidence_refs",
            "verification_profile_id",
            "evidence_grade_profile_id",
        ),
    }
    ACTIVE_RULE_STATUSES = frozenset({"DRAFT", "ACTIVE", "INTERNAL_READY"})

    def __init__(self, store: ContractStore) -> None:
        self.store = store

    def _factory_config(self) -> Mapping[str, Any]:
        factory = self.store.rule_catalog.get("stage5_rule_factory", {})
        return factory if isinstance(factory, Mapping) else {}

    def _selection_policy(self) -> Mapping[str, Any]:
        policy = self._factory_config().get("selection_policy", {})
        return policy if isinstance(policy, Mapping) else {}

    def _rule_binding(self, rule_code: str) -> Mapping[str, Any]:
        bindings = self._factory_config().get("rule_bindings", {})
        if not isinstance(bindings, Mapping):
            return {}
        binding = bindings.get(rule_code, {})
        return binding if isinstance(binding, Mapping) else {}

    def _rule_basis_entry(self, basis_id: str) -> Mapping[str, Any]:
        basis_index = getattr(self.store, "rule_basis_index", {})
        if not isinstance(basis_index, Mapping):
            return {}
        entry = basis_index.get(basis_id, {})
        return entry if isinstance(entry, Mapping) else {}

    def _coerce_bool(self, value: Any, *, default: bool) -> bool:
        if value in (None, ""):
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "disabled"}
        return bool(value)

    def _priority_from_value(self, rule: Mapping[str, Any]) -> int:
        value = str(rule.get("value_priority", "P9")).upper()
        if value.startswith("P") and value[1:].isdigit():
            return 1000 + int(value[1:]) * 100
        return 9999

    def _get_path(self, data: Mapping[str, Any], path: str) -> Any:
        current: Any = data
        for part in path.split("."):
            if isinstance(current, Mapping):
                current = current.get(part)
            else:
                return None
        return current

    def _is_missing(self, value: Any) -> bool:
        return value in (None, "", [], {})

    def _as_strings(self, values: Any) -> list[str]:
        result: list[str] = []
        for value in ensure_list(values):
            if value in (None, "", [], {}):
                continue
            if isinstance(value, Mapping):
                for key in (
                    "readback_id",
                    "snapshot_hash",
                    "source_snapshot_id",
                    "source_url",
                    "verification_run_id",
                    "verification_target_type",
                    "subject_identifier",
                    "evidence_id",
                    "active_conflict_run_id",
                ):
                    nested_value = value.get(key)
                    if nested_value not in (None, "", [], {}):
                        result.append(str(nested_value))
                continue
            result.append(str(value))
        return list(dict.fromkeys(result))

    def _supported_upstream_objects(self, inputs: Mapping[str, Any]) -> set[str]:
        policy = self._selection_policy()
        configured = {
            str(value)
            for value in ensure_list(policy.get("supported_upstream_objects"))
            if value not in (None, "")
        }
        supported = configured or set(self.FIRST_SLICE_SUPPORTED_UPSTREAM_OBJECTS)
        for key in ("stage5_supported_upstream_objects", "stage5_supported_upstream_objects_optional"):
            supported.update(str(value) for value in ensure_list(inputs.get(key)) if value not in (None, ""))
        return supported

    def _requested_rule_codes(self, inputs: Mapping[str, Any]) -> list[str]:
        requested = ensure_list(
            inputs.get("stage5_requested_rule_codes")
            or inputs.get("stage5_rule_codes_requested")
            or inputs.get("requested_stage5_rule_codes")
        )
        return [str(value) for value in requested if value not in (None, "")]

    def _active_rule_statuses(self) -> set[str]:
        configured = {
            str(value)
            for value in ensure_list(self._selection_policy().get("active_statuses"))
            if value not in (None, "")
        }
        return configured or set(self.ACTIVE_RULE_STATUSES)

    def _version_pin_for(self, inputs: Mapping[str, Any], rule_code: str) -> str | None:
        pins = inputs.get("stage5_rule_version_pins")
        if isinstance(pins, Mapping) and pins.get(rule_code) not in (None, ""):
            return str(pins.get(rule_code))
        return None

    def _strict_basis_gate_required(self, inputs: Mapping[str, Any]) -> bool:
        mode = str(inputs.get("stage5_basis_gate_mode") or "").upper()
        if mode in {"STRICT", "CUSTOMER_VISIBLE", "REAL_PUBLIC"}:
            return True
        if self._coerce_bool(inputs.get("stage5_strict_basis_gate"), default=False):
            return True
        flags = inputs.get("flags")
        if isinstance(flags, Mapping) and self._coerce_bool(flags.get("stage5_strict_basis_gate"), default=False):
            return True
        if str(inputs.get("source_candidate_mode") or "") == "REAL_PUBLIC_SOURCE_CANDIDATES":
            return True
        if inputs.get("stage4_public_verification_carrier") or inputs.get("stage4_public_verification_refs"):
            return True
        return any(
            self._coerce_bool(inputs.get(key), default=False)
            for key in (
                "approved_customer_visible_unlock_requested",
                "customer_visible_export_requested",
                "customer_visible_publication_requested",
            )
        )

    def _basis_gate_status(self, profile: Mapping[str, Any], *, inputs: Mapping[str, Any]) -> tuple[str, list[str]]:
        rule_code = str(profile["rule_code"])
        basis_state = str(profile.get("basis_verification_state") or "BASIS_MISSING")
        strict_required = self._strict_basis_gate_required(inputs)
        basis_refs = [str(value) for value in ensure_list(profile.get("basis_refs")) if value not in (None, "")]
        basis_statuses = dict(profile.get("basis_statuses", {}))
        reasons: list[str] = []

        if not basis_refs:
            reasons.append(f"{rule_code}: basis refs missing")
        missing_basis_refs = [basis_ref for basis_ref in basis_refs if basis_statuses.get(basis_ref) == "MISSING"]
        if missing_basis_refs:
            reasons.append(f"{rule_code}: basis catalog refs missing {','.join(missing_basis_refs)}")

        if basis_state == "VERIFIED":
            non_verified_refs = [
                f"{basis_ref}:{basis_statuses.get(basis_ref)}"
                for basis_ref in basis_refs
                if basis_statuses.get(basis_ref) != "VERIFIED"
            ]
            if non_verified_refs:
                reasons.append(f"{rule_code}: non-verified basis refs {','.join(non_verified_refs)}")
        elif basis_state == "INTERNAL_ONLY":
            if strict_required:
                reasons.append(f"{rule_code}: internal-only basis cannot support strict or customer-visible gate")
        elif basis_state == "HEURISTIC_ONLY":
            reasons.append(f"{rule_code}: heuristic-only rule is review-only")
        elif basis_state in {"BASIS_MISSING", "DEPRECATED"}:
            reasons.append(f"{rule_code}: basis verification state {basis_state}")
        else:
            reasons.append(f"{rule_code}: unsupported basis verification state {basis_state}")

        if profile.get("customer_visible_allowed") is True and basis_state != "VERIFIED":
            reasons.append(f"{rule_code}: customer-visible rule requires verified basis")

        return ("PASS" if not reasons else "REVIEW"), list(dict.fromkeys(reasons))

    def _dependency_evidence_refs(
        self,
        *,
        dependency_evidence_fields: list[str],
        inputs: Mapping[str, Any],
        evidence_artifacts: EvidenceArtifacts,
        public_attack_surface: Any,
        focus_bidder_verification_profile: Any,
        pseudo_competitor_signal_set: Any,
    ) -> list[str]:
        merged_inputs = {
            **dict(inputs),
            "evidence_id": evidence_artifacts.evidence.get("evidence_id"),
            "public_attack_surface_id": public_attack_surface.get("public_attack_surface_id"),
            "verification_profile_id": focus_bidder_verification_profile.get("verification_profile_id"),
            "pseudo_competitor_signal_set_id": pseudo_competitor_signal_set.get("signal_set_id"),
        }
        refs: list[str] = []
        for field_path in dependency_evidence_fields:
            refs.extend(self._as_strings(self._get_path(merged_inputs, field_path)))
        if not refs:
            refs.append(str(evidence_artifacts.evidence.get("evidence_id")))
        return list(dict.fromkeys(refs))

    def _confidence_score(self, *, inputs: Mapping[str, Any], pseudo_competitor_signal_set: Any) -> float:
        explicit = inputs.get("stage5_rule_confidence")
        if explicit not in (None, ""):
            try:
                return float(explicit)
            except (TypeError, ValueError):
                return 0.0
        band = str(inputs.get("confidence_band") or pseudo_competitor_signal_set.get("confidence_band") or "LOW")
        return {
            "HIGH": 0.9,
            "MEDIUM": 0.72,
            "LOW": 0.35,
        }.get(band.upper(), 0.5)

    def _rule_profile(self, rule: Mapping[str, Any], *, inputs: Mapping[str, Any]) -> dict[str, Any]:
        rule_code = str(rule.get("rule_code"))
        binding = self._rule_binding(rule_code)
        factory = self._factory_config()
        version = str(
            binding.get("version")
            or rule.get("version")
            or factory.get("default_rule_version")
            or self.store.rule_catalog.get("version", "")
        )
        dependency_fields = [
            str(value)
            for value in ensure_list(binding.get("dependency_fields"))
            if value not in (None, "")
        ]
        dependency_evidence_fields = [
            str(value)
            for value in ensure_list(binding.get("dependency_evidence"))
            if value not in (None, "")
        ]
        upstream_objects = [
            str(object_name)
            for object_name in ensure_list(rule.get("upstream_objects"))
            if object_name not in (None, "")
        ]
        supported_upstream_objects = self._supported_upstream_objects(inputs)
        unsupported_upstream_objects = [
            object_name for object_name in upstream_objects if object_name not in supported_upstream_objects
        ]
        missing_dependency_fields = [
            field_name for field_name in dependency_fields if self._is_missing(self._get_path(inputs, field_name))
        ]
        expected_version = self._version_pin_for(inputs, rule_code)
        version_conflict = bool(expected_version and expected_version != version)
        priority = binding.get("priority", rule.get("priority"))
        if priority in (None, ""):
            priority = self._priority_from_value(rule)

        basis_refs = [
            str(value)
            for value in ensure_list(binding.get("basis_refs") or rule.get("basis_refs"))
            if value not in (None, "")
        ]
        basis_statuses = {
            basis_ref: str(self._rule_basis_entry(basis_ref).get("basis_status") or "MISSING")
            for basis_ref in basis_refs
        }
        profile = {
            "rule": rule,
            "rule_code": rule_code,
            "rule_name": str(rule.get("name", rule_code)),
            "enabled": self._coerce_bool(binding.get("enabled", rule.get("enabled", True)), default=True),
            "status": str(rule.get("status", "")),
            "version": version,
            "expected_version": expected_version,
            "version_conflict": version_conflict,
            "priority": int(priority),
            "upstream_objects": upstream_objects,
            "unsupported_upstream_objects": unsupported_upstream_objects,
            "dependency_fields": dependency_fields,
            "missing_dependency_fields": missing_dependency_fields,
            "dependency_evidence_fields": dependency_evidence_fields,
            "input_contract": dict(binding.get("input_contract", {}))
            if isinstance(binding.get("input_contract"), Mapping)
            else {},
            "output_contract": dict(binding.get("output_contract", {}))
            if isinstance(binding.get("output_contract"), Mapping)
            else {},
            "document_term_refs": [
                str(value)
                for value in ensure_list(binding.get("document_term_refs"))
                if value not in (None, "")
            ],
            "golden_case_refs": [
                str(value)
                for value in ensure_list(binding.get("golden_case_refs"))
                if value not in (None, "")
            ],
            "minimum_confidence": float(binding.get("minimum_confidence", factory.get("minimum_confidence", 0.6))),
            "basis_refs": basis_refs,
            "basis_statuses": basis_statuses,
            "basis_verification_state": str(
                binding.get("basis_verification_state")
                or rule.get("basis_verification_state")
                or "BASIS_MISSING"
            ),
            "applicability_scope": dict(rule.get("applicability_scope", {}))
            if isinstance(rule.get("applicability_scope"), Mapping)
            else {},
            "result_ceiling": str(rule.get("result_ceiling") or rule.get("default_result") or "REVIEW_REQUEST"),
            "customer_visible_allowed": self._coerce_bool(
                rule.get("customer_visible_allowed"),
                default=False,
            ),
            "no_legal_conclusion": self._coerce_bool(
                rule.get("no_legal_conclusion"),
                default=True,
            ),
            "basis_gate_policy": str(rule.get("basis_gate_policy") or "STRICT_FOR_REAL_PUBLIC_OR_CUSTOMER_VISIBLE"),
        }
        basis_gate_status, basis_gate_reasons = self._basis_gate_status(profile, inputs=inputs)
        profile["basis_gate_status"] = basis_gate_status
        profile["basis_gate_reasons"] = basis_gate_reasons
        return profile

    def _profile_fail_closed_reasons(self, profile: Mapping[str, Any]) -> list[str]:
        rule_code = str(profile["rule_code"])
        active_statuses = self._active_rule_statuses()
        reasons: list[str] = []
        if not profile["enabled"]:
            reasons.append(f"{rule_code}: catalog disabled")
        if profile["status"] not in active_statuses:
            reasons.append(f"{rule_code}: catalog status {profile['status']} not executable")
        if profile["unsupported_upstream_objects"]:
            reasons.append(
                f"{rule_code}: unsupported upstream objects {','.join(profile['unsupported_upstream_objects'])}"
            )
        if profile["missing_dependency_fields"]:
            reasons.append(f"{rule_code}: missing dependency fields {','.join(profile['missing_dependency_fields'])}")
        if profile["version_conflict"]:
            reasons.append(
                f"{rule_code}: version conflict expected {profile['expected_version']} actual {profile['version']}"
            )
        if profile.get("basis_gate_status") != "PASS":
            reasons.extend(str(reason) for reason in ensure_list(profile.get("basis_gate_reasons")))
        return reasons

    def _selection_reason(self, rule: Mapping[str, Any], *, selected_rule_codes: set[str]) -> str:
        rule_code = str(rule.get("rule_code"))
        if rule_code in selected_rule_codes:
            return "selected_first_slice_priority"

        upstream_objects = {
            str(object_name)
            for object_name in ensure_list(rule.get("upstream_objects"))
            if object_name not in (None, "")
        }
        if upstream_objects.issubset(self.FIRST_SLICE_SUPPORTED_UPSTREAM_OBJECTS):
            return "not_in_first_slice_priority"
        return "unsupported_upstream_objects"

    def _select_stage5_rules(
        self,
        *,
        inputs: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        stage5_profiles = [
            self._rule_profile(entry, inputs=inputs)
            for entry in self.store.rule_catalog.get("rules", [])
            if int(entry.get("stage", -1)) == 5
        ]
        requested_rule_codes = self._requested_rule_codes(inputs)
        requested_rule_code_set = set(requested_rule_codes)
        selection_limit = int(self._selection_policy().get("default_selection_limit", 3))

        eligible_profiles = [
            profile
            for profile in stage5_profiles
            if not self._profile_fail_closed_reasons(profile)
        ]
        if requested_rule_codes:
            selected_by_code = {
                profile["rule_code"]: profile
                for profile in stage5_profiles
                if profile["rule_code"] in requested_rule_code_set
            }
            selected_profiles = [
                selected_by_code[rule_code]
                for rule_code in requested_rule_codes
                if rule_code in selected_by_code
            ]
            missing_requested = [
                rule_code for rule_code in requested_rule_codes if rule_code not in {p["rule_code"] for p in selected_profiles}
            ]
            if missing_requested:
                raise ValueError(f"stage5_requested_rule_not_in_catalog:{','.join(missing_requested)}")
        else:
            selected_profiles = sorted(eligible_profiles, key=lambda profile: (profile["priority"], profile["rule_code"]))[
                :selection_limit
            ]

        if not selected_profiles and stage5_profiles:
            selected_profiles = [sorted(stage5_profiles, key=lambda profile: (profile["priority"], profile["rule_code"]))[0]]

        selected_rule_codes = {profile["rule_code"] for profile in selected_profiles}
        active_statuses = self._active_rule_statuses()
        for profile in selected_profiles:
            fail_closed_reasons = self._profile_fail_closed_reasons(profile)
            profile["fail_closed_reasons"] = fail_closed_reasons
            profile["selected_reason"] = (
                "selected_requested_fail_closed"
                if requested_rule_codes and fail_closed_reasons
                else "selected_requested_rule"
                if requested_rule_codes
                else "selected_catalog_priority"
            )

        selection_trace: list[dict[str, Any]] = []
        disabled_count = 0
        unsupported_count = 0
        missing_dependency_count = 0
        version_conflict_count = 0
        basis_gate_review_count = 0
        basis_missing_count = 0
        basis_internal_only_count = 0
        basis_heuristic_only_count = 0
        for profile in stage5_profiles:
            fail_closed_reasons = self._profile_fail_closed_reasons(profile)
            if not profile["enabled"] or profile["status"] not in active_statuses:
                disabled_count += 1
            if profile["unsupported_upstream_objects"]:
                unsupported_count += 1
            if profile["missing_dependency_fields"]:
                missing_dependency_count += 1
            if profile["version_conflict"]:
                version_conflict_count += 1
            if profile.get("basis_gate_status") != "PASS":
                basis_gate_review_count += 1
            if profile.get("basis_verification_state") == "BASIS_MISSING":
                basis_missing_count += 1
            if profile.get("basis_verification_state") == "INTERNAL_ONLY":
                basis_internal_only_count += 1
            if profile.get("basis_verification_state") == "HEURISTIC_ONLY":
                basis_heuristic_only_count += 1

            if profile["rule_code"] in selected_rule_codes:
                reason = str(profile.get("selected_reason", "selected_catalog_priority"))
                selected = True
            elif fail_closed_reasons:
                selected = False
                if not profile["enabled"] or profile["status"] not in active_statuses:
                    reason = "catalog_disabled"
                elif profile["version_conflict"]:
                    reason = "version_conflict"
                elif profile.get("basis_gate_status") != "PASS":
                    reason = "basis_gate_review"
                elif profile["unsupported_upstream_objects"]:
                    reason = "unsupported_upstream_objects"
                else:
                    reason = "missing_dependency"
            else:
                selected = False
                reason = "skipped_by_priority_limit"

            selection_trace.append(
                {
                    "rule_code": profile["rule_code"],
                    "rule_name": profile["rule_name"],
                    "stage": 5,
                    "enabled": profile["enabled"],
                    "status": profile["status"],
                    "version": profile["version"],
                    "priority": profile["priority"],
                    "selected": selected,
                    "reason": reason,
                    "selected_reason": reason if selected else None,
                    "upstream_objects": list(profile["upstream_objects"]),
                    "unsupported_upstream_objects": list(profile["unsupported_upstream_objects"]),
                    "dependency_fields": list(profile["dependency_fields"]),
                    "missing_dependency_fields": list(profile["missing_dependency_fields"]),
                    "dependency_evidence_fields": list(profile["dependency_evidence_fields"]),
                    "golden_case_refs": list(profile["golden_case_refs"]),
                    "input_contract": dict(profile["input_contract"]),
                    "output_contract": dict(profile["output_contract"]),
                    "document_term_refs": list(profile["document_term_refs"]),
                    "basis_refs": list(profile["basis_refs"]),
                    "basis_statuses": dict(profile["basis_statuses"]),
                    "basis_verification_state": profile["basis_verification_state"],
                    "basis_gate_status": profile["basis_gate_status"],
                    "basis_gate_reasons": list(profile["basis_gate_reasons"]),
                    "basis_gate_policy": profile["basis_gate_policy"],
                    "customer_visible_allowed": bool(profile["customer_visible_allowed"]),
                    "no_legal_conclusion": bool(profile["no_legal_conclusion"]),
                    "result_ceiling": profile["result_ceiling"],
                    "fail_closed_reasons": list(fail_closed_reasons),
                }
            )

        golden_case_refs = sorted(
            {
                ref
                for profile in selected_profiles
                for ref in ensure_list(profile.get("golden_case_refs"))
                if ref not in (None, "")
            }
        )
        coverage_summary = {
            "catalog_id": self.store.rule_catalog.get("catalog_id"),
            "catalog_version": self.store.rule_catalog.get("version"),
            "factory_version": self._factory_config().get("version"),
            "selected_count": len(selected_profiles),
            "skipped_count": max(len(stage5_profiles) - len(selected_profiles), 0),
            "disabled_count": disabled_count,
            "unsupported_count": unsupported_count,
            "missing_dependency_count": missing_dependency_count,
            "version_conflict_count": version_conflict_count,
            "basis_gate_review_count": basis_gate_review_count,
            "basis_missing_count": basis_missing_count,
            "basis_internal_only_count": basis_internal_only_count,
            "basis_heuristic_only_count": basis_heuristic_only_count,
            "selected_rule_codes": [profile["rule_code"] for profile in selected_profiles],
            "skipped_rule_codes": [
                profile["rule_code"] for profile in stage5_profiles if profile["rule_code"] not in selected_rule_codes
            ],
            "golden_case_refs": golden_case_refs,
        }
        return selected_profiles, selection_trace, coverage_summary

    def _build_rule_source_object_refs(
        self,
        rule_code: str,
        *,
        inputs: Mapping[str, Any],
        public_attack_surface: Any,
        focus_bidder_verification_profile: Any,
        pseudo_competitor_signal_set: Any,
    ) -> list[str]:
        source_refs = [
            inputs.get("project_root_id"),
            public_attack_surface.get("public_attack_surface_id"),
            focus_bidder_verification_profile.get("verification_profile_id"),
            pseudo_competitor_signal_set.get("signal_set_id"),
            inputs.get("pseudo_competitor_signal_set_id"),
            inputs.get("winning_version_resolution_rule_id"),
            inputs.get("clock_resolution_rule_id"),
            inputs.get("clock_precedence_rule_id"),
        ]
        preferred_fields = self.RULE_SOURCE_OBJECT_REF_FIELDS.get(rule_code, ())
        ordered_refs = [self._get_path(inputs, field_name) for field_name in preferred_fields]
        ordered_refs.extend(source_refs)
        return [str(ref) for ref in ordered_refs if ref not in (None, "")]

    def _evaluate_rule_status(
        self,
        *,
        rule_code: str,
        evidence_gate_status: str,
        verification_state: str,
        lineage_status: str,
        conflict_state: str,
        version_conflict_state: str,
        clock_conflict_state: str,
        flags: Mapping[str, Any],
    ) -> tuple[str, str, list[str], str]:
        reasons: list[str] = []
        if get_flag(flags, "rule_superseded"):
            reasons.append(f"{rule_code}: superseded by newer rule outcome")
            return "REVIEW", "SUPERSEDED", reasons, "STATE-508"

        if verification_state == "BLOCK":
            reasons.append(f"{rule_code}: verification blocked")
        if evidence_gate_status == "BLOCK":
            reasons.append(f"{rule_code}: evidence gate blocked")
        if get_flag(flags, "rule_blocked"):
            reasons.append(f"{rule_code}: rule_blocked flag active")
        if reasons:
            return "BLOCK", "BLOCKED", reasons, "STATE-504"

        if version_conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: version conflict {version_conflict_state}")
        if clock_conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: clock conflict {clock_conflict_state}")
        if verification_state in {"REVIEW", "NOT_RUN"}:
            reasons.append(f"{rule_code}: verification {verification_state.lower()}")
        if evidence_gate_status == "REVIEW":
            reasons.append(f"{rule_code}: evidence gate review")
        if lineage_status != "NORMALIZED":
            reasons.append(f"{rule_code}: lineage {lineage_status}")
        if conflict_state != "CONSISTENT":
            reasons.append(f"{rule_code}: conflict {conflict_state}")
        if get_flag(flags, "rule_review"):
            reasons.append(f"{rule_code}: rule_review flag active")
        if reasons:
            return "REVIEW", "REVIEW_REQUIRED", reasons, "STATE-503"

        return "PASS", "CONFIRMED", [], "STATE-507"

    def _project_manager_public_readback_review_reasons(
        self,
        *,
        rule_code: str,
        inputs: Mapping[str, Any],
    ) -> list[str]:
        if rule_code in QUAL_PM_RULE_CODES:
            return self._project_manager_qualification_review_reasons(
                rule_code=rule_code,
                inputs=inputs,
            )
        if rule_code not in {"PM-001", "PM-002"}:
            return []
        carrier = inputs.get("project_manager_active_conflict_readback") or inputs.get(
            "project_manager_active_conflict_carrier"
        )
        if not isinstance(carrier, Mapping):
            return []
        reasons: list[str] = []
        if rule_code == "PM-002" and carrier.get("review_required") is True:
            reasons.append(f"{rule_code}: project manager active conflict requires manual review")
        if carrier.get("fail_closed") is True or carrier.get("readback_state") == "FAIL_CLOSED_INCOMPLETE_OR_NON_PUBLIC":
            reasons.append(f"{rule_code}: active conflict readback failed closed")
        if carrier.get("no_legal_conclusion") is False or carrier.get("customer_visible") is True:
            reasons.append(f"{rule_code}: active conflict boundary violation")
        identity_resolution = carrier.get("manager_identity_resolution")
        if rule_code == "PM-002" and isinstance(identity_resolution, Mapping):
            for reason in ensure_list(identity_resolution.get("failure_reasons")):
                if reason not in (None, ""):
                    reasons.append(f"{rule_code}: identity resolution {reason}")
        registration_timeline = carrier.get("registration_timeline_verification")
        if rule_code == "PM-001":
            if not isinstance(registration_timeline, Mapping):
                reasons.append(f"{rule_code}: project manager registration timeline missing")
            elif registration_timeline.get("verification_result") != "PASS":
                timeline_reasons = ensure_list(registration_timeline.get("failure_reasons"))
                if not timeline_reasons:
                    reasons.append(f"{rule_code}: project manager registration timeline review")
                for reason in timeline_reasons:
                    if reason not in (None, ""):
                        reasons.append(f"{rule_code}: registration timeline {reason}")
        return reasons

    def _project_manager_qualification_review_reasons(
        self,
        *,
        rule_code: str,
        inputs: Mapping[str, Any],
    ) -> list[str]:
        carrier = inputs.get("project_manager_qualification_readback")
        if not isinstance(carrier, Mapping):
            return []
        readback = evaluate_project_manager_qualification_rules(carrier)
        result = next(
            (
                item
                for item in readback.get("rule_results", [])
                if isinstance(item, Mapping) and item.get("rule_code") == rule_code
            ),
            None,
        )
        if not isinstance(result, Mapping) or result.get("status") == "PASS":
            return []
        reasons = [
            f"{rule_code}: {result.get('status')} {reason}"
            for reason in ensure_list(result.get("failure_reasons"))
            if reason not in (None, "")
        ]
        if not reasons:
            reasons.append(f"{rule_code}: {result.get('status')}")
        return reasons

    def _public_evidence_gate(self, *, rule_code: str, inputs: Mapping[str, Any]) -> dict[str, Any]:
        if rule_code not in PUBLIC_EVIDENCE_RULE_CODES:
            return {
                "gate_status": "PASS",
                "review_required": False,
                "reasons": [],
                "readback_ids": [],
                "passed_readback_ids": [],
                "source_refs": [],
                "no_legal_conclusion": True,
                "customer_visible": False,
            }
        readbacks: list[dict[str, Any]] = []
        for key in (
            "stage4_public_evidence_readbacks",
            "public_evidence_readbacks",
            "credit_public_readbacks",
            "engineering_public_readbacks",
            "relation_public_readbacks",
        ):
            readbacks.extend(normalize_public_evidence_readbacks(inputs.get(key)))
        return evaluate_public_evidence_gate(rule_code, readbacks)

    def _public_evidence_rule_review_reasons(
        self,
        *,
        rule_code: str,
        public_evidence_gate: Mapping[str, Any],
    ) -> list[str]:
        if rule_code not in PUBLIC_EVIDENCE_RULE_CODES:
            return []
        if public_evidence_gate.get("gate_status") == "PASS":
            return []
        reasons = [
            str(reason)
            for reason in ensure_list(public_evidence_gate.get("reasons"))
            if reason not in (None, "")
        ]
        if not reasons:
            reasons.append(f"{rule_code}: public evidence gate review")
        return reasons

    def _result_type_for_rule(
        self,
        *,
        rule_code: str,
        rule: Mapping[str, Any],
        profile: Mapping[str, Any],
        inputs: Mapping[str, Any],
    ) -> str:
        result_type = str(inputs.get("result_type") or rule.get("default_result") or "REVIEW_REQUEST")
        if rule_code in PUBLIC_EVIDENCE_RULE_CODES:
            ceiling = str(profile.get("result_ceiling") or "")
            if ceiling:
                return ceiling
        return result_type

    def _degrade_for_preflight(
        self,
        *,
        rule_code: str,
        current_status: str,
        current_hit_state: str,
        current_reasons: list[str],
        current_state_trace_rule: str,
        preflight_reasons: list[str],
    ) -> tuple[str, str, list[str], str]:
        if not preflight_reasons:
            return current_status, current_hit_state, current_reasons, current_state_trace_rule
        merged_reasons = list(dict.fromkeys([*preflight_reasons, *current_reasons]))
        if current_status == "BLOCK":
            return current_status, current_hit_state, merged_reasons, current_state_trace_rule
        return "REVIEW", "REVIEW_REQUIRED", merged_reasons, "STATE-503"

    def run(
        self,
        *,
        project_id: str,
        evidence_grade_profile: Any,
        public_attack_surface: Any,
        focus_bidder_verification_profile: Any,
        pseudo_competitor_signal_set: Any,
        evidence_artifacts: EvidenceArtifacts,
        inputs: Mapping[str, Any],
        flags: Mapping[str, Any],
        trace_rules: list[str],
    ) -> RuleArtifacts:
        lineage_status = str(inputs["lineage_status"])
        conflict_state = str(inputs["conflict_state"])
        verification_state = str(inputs["verification_state"])
        version_conflict_state = str(inputs.get("version_conflict_state", "CONSISTENT"))
        clock_conflict_state = str(inputs.get("clock_conflict_state", "CONSISTENT"))

        selected_profiles, rule_selection_trace, coverage_summary = self._select_stage5_rules(inputs=inputs)
        if not selected_profiles:
            raise ValueError("stage5_rule_catalog_selection_empty")

        evaluated_rules: list[tuple[Any, str, str, list[str], dict[str, Any]]] = []
        for profile in selected_profiles:
            rule = profile["rule"]
            rule_code = str(profile["rule_code"])
            apply_rule(self.store, trace_rules, rule_code)
            rule_gate_status_for_hit, rule_hit_state_for_hit, reasons, state_trace_rule = self._evaluate_rule_status(
                rule_code=rule_code,
                evidence_gate_status=evidence_artifacts.evidence_gate_status,
                verification_state=verification_state,
                lineage_status=lineage_status,
                conflict_state=conflict_state,
                version_conflict_state=version_conflict_state,
                clock_conflict_state=clock_conflict_state,
                flags=flags,
            )

            confidence = self._confidence_score(
                inputs=inputs,
                pseudo_competitor_signal_set=pseudo_competitor_signal_set,
            )
            public_evidence_gate = self._public_evidence_gate(rule_code=rule_code, inputs=inputs)
            preflight_reasons = list(profile.get("fail_closed_reasons", []))
            if confidence < float(profile["minimum_confidence"]):
                preflight_reasons.append(
                    f"{rule_code}: weak evidence confidence {confidence:.2f} below {float(profile['minimum_confidence']):.2f}"
                )
            preflight_reasons.extend(
                self._project_manager_public_readback_review_reasons(
                    rule_code=rule_code,
                    inputs=inputs,
                )
            )
            preflight_reasons.extend(
                self._public_evidence_rule_review_reasons(
                    rule_code=rule_code,
                    public_evidence_gate=public_evidence_gate,
                )
            )
            (
                rule_gate_status_for_hit,
                rule_hit_state_for_hit,
                reasons,
                state_trace_rule,
            ) = self._degrade_for_preflight(
                rule_code=rule_code,
                current_status=rule_gate_status_for_hit,
                current_hit_state=rule_hit_state_for_hit,
                current_reasons=reasons,
                current_state_trace_rule=state_trace_rule,
                preflight_reasons=preflight_reasons,
            )
            apply_rule(self.store, trace_rules, state_trace_rule)

            dependency_evidence_refs = self._dependency_evidence_refs(
                dependency_evidence_fields=list(profile["dependency_evidence_fields"]),
                inputs=inputs,
                evidence_artifacts=evidence_artifacts,
                public_attack_surface=public_attack_surface,
                focus_bidder_verification_profile=focus_bidder_verification_profile,
                pseudo_competitor_signal_set=pseudo_competitor_signal_set,
            )
            public_evidence_refs = [
                str(ref)
                for ref in ensure_list(public_evidence_gate.get("source_refs"))
                if ref not in (None, "")
            ]
            dependency_evidence_refs = list(dict.fromkeys([*dependency_evidence_refs, *public_evidence_refs]))
            source_object_refs = ensure_list(inputs.get("source_object_refs"))
            if not source_object_refs:
                source_object_refs = self._build_rule_source_object_refs(
                    rule_code,
                    inputs=inputs,
                    public_attack_surface=public_attack_surface,
                    focus_bidder_verification_profile=focus_bidder_verification_profile,
                    pseudo_competitor_signal_set=pseudo_competitor_signal_set,
            )
            source_object_refs = list(dict.fromkeys([*dependency_evidence_refs, *[str(ref) for ref in source_object_refs]]))
            result_type = self._result_type_for_rule(
                rule_code=rule_code,
                rule=rule,
                profile=profile,
                inputs=inputs,
            )
            boundary_note = (
                f"{rule.get('name')}; version={profile['version']}; priority={profile['priority']}; "
                f"upstream={','.join(profile['upstream_objects'])}; "
                f"dependency_fields={','.join(profile['dependency_fields'])}; "
                f"verification={verification_state}; evidence_gate={evidence_artifacts.evidence_gate_status}; "
                f"version_state={version_conflict_state}; clock={clock_conflict_state}; "
                f"basis_gate={profile['basis_gate_status']}; basis_state={profile['basis_verification_state']}; "
                f"confidence={confidence:.2f}; pseudo_signal={pseudo_competitor_signal_set.get('confidence_band')}"
            )
            if reasons:
                boundary_note = f"{boundary_note}; reasons={'; '.join(reasons)}"
            rule_hit = self.store.build_record(
                "rule_hit",
                {
                    "rule_hit_id": build_id("RH", project_id, rule_code),
                    "project_id": project_id,
                    "rule_code": rule_code,
                    "result_type": ensure_enum(
                        self.store,
                        "result_type",
                        result_type,
                    ),
                    "rule_hit_state": rule_hit_state_for_hit,
                    "evidence_refs": [evidence_artifacts.evidence.get("evidence_id")],
                    "boundary_note": inputs.get("boundary_note", boundary_note),
                    "evidence_grade": evidence_grade_profile.get("external_use_grade"),
                    "source_object_refs": source_object_refs,
                },
            )
            evaluated_rules.append(
                (
                    rule_hit,
                    rule_gate_status_for_hit,
                    rule_hit_state_for_hit,
                    reasons,
                    {
                        "rule_code": rule_code,
                        "rule_name": str(profile["rule_name"]),
                        "version": str(profile["version"]),
                        "priority": int(profile["priority"]),
                        "selected_reason": str(profile.get("selected_reason", "selected_catalog_priority")),
                        "upstream_objects": list(profile["upstream_objects"]),
                        "dependency_fields": list(profile["dependency_fields"]),
                        "dependency_evidence": dependency_evidence_refs,
                        "dependency_evidence_fields": list(profile["dependency_evidence_fields"]),
                        "evidence_refs": [evidence_artifacts.evidence.get("evidence_id")],
                        "basis_refs": list(profile["basis_refs"]),
                        "basis_statuses": dict(profile["basis_statuses"]),
                        "basis_verification_state": str(profile["basis_verification_state"]),
                        "basis_gate_status": str(profile["basis_gate_status"]),
                        "basis_gate_reasons": list(profile["basis_gate_reasons"]),
                        "basis_gate_policy": str(profile["basis_gate_policy"]),
                        "customer_visible_allowed": bool(profile["customer_visible_allowed"]),
                        "no_legal_conclusion": bool(profile["no_legal_conclusion"]),
                        "result_ceiling": str(profile["result_ceiling"]),
                        "public_evidence_gate_status": str(public_evidence_gate.get("gate_status")),
                        "public_evidence_gate_reasons": [
                            str(reason)
                            for reason in ensure_list(public_evidence_gate.get("reasons"))
                            if reason not in (None, "")
                        ],
                        "public_evidence_readback_ids": [
                            str(readback_id)
                            for readback_id in ensure_list(public_evidence_gate.get("readback_ids"))
                            if readback_id not in (None, "")
                        ],
                        "public_evidence_passed_readback_ids": [
                            str(readback_id)
                            for readback_id in ensure_list(public_evidence_gate.get("passed_readback_ids"))
                            if readback_id not in (None, "")
                        ],
                        "confidence": confidence,
                        "rule_gate_status": rule_gate_status_for_hit,
                        "rule_hit_state": rule_hit_state_for_hit,
                        "blocking_reasons": list(reasons),
                        "rule_hit_id": rule_hit.get("rule_hit_id"),
                        "golden_case_refs": list(profile["golden_case_refs"]),
                        "document_term_refs": list(profile["document_term_refs"]),
                    },
                )
            )

        severity_order = {"BLOCK": 0, "REVIEW": 1, "PASS": 2}
        primary_rule_hit, _, primary_rule_hit_state, _, _ = min(
            evaluated_rules,
            key=lambda entry: severity_order.get(entry[1], 99),
        )
        rule_hits = [entry[0] for entry in evaluated_rules]
        rule_execution_trace = [dict(entry[4]) for entry in evaluated_rules]
        passed_rule_hits = [
            rule_hit.get("rule_hit_id")
            for rule_hit, rule_status, _, _, _ in evaluated_rules
            if rule_status == "PASS"
        ]
        blocked_rule_hits = [
            rule_hit.get("rule_hit_id")
            for rule_hit, rule_status, _, _, _ in evaluated_rules
            if rule_status == "BLOCK"
        ]
        aggregated_reasons: list[str] = []
        for _, rule_status, _, reasons, _ in evaluated_rules:
            if rule_status != "PASS":
                aggregated_reasons.extend(reasons)
        blocking_reasons = list(dict.fromkeys(aggregated_reasons))
        if blocked_rule_hits:
            rule_gate_status = "BLOCK"
        elif any(rule_status == "REVIEW" for _, rule_status, _, _, _ in evaluated_rules):
            rule_gate_status = "REVIEW"
        else:
            rule_gate_status = "PASS"

        rule_gate_decision = self.store.build_record(
            "rule_gate_decision",
            {
                "gate_id": build_id("RGATE", project_id),
                "project_id": project_id,
                "gate_scope": "PROJECT",
                "rule_gate_status": rule_gate_status,
                "passed_rule_hits": passed_rule_hits,
                "blocked_rule_hits": blocked_rule_hits,
                "blocking_reasons": [] if rule_gate_status == "PASS" else blocking_reasons,
                "resolved_by_version_state": inputs.get("version_conflict_state", "CONSISTENT"),
            },
        )

        pass_count = sum(1 for _, rule_status, _, _, _ in evaluated_rules if rule_status == "PASS")
        review_count = sum(1 for _, rule_status, _, _, _ in evaluated_rules if rule_status == "REVIEW")
        block_count = sum(1 for _, rule_status, _, _, _ in evaluated_rules if rule_status == "BLOCK")
        coverage_summary = {
            **coverage_summary,
            "pass_count": pass_count,
            "review_count": review_count,
            "block_count": block_count,
            "rule_gate_status": rule_gate_status,
            "evidence_gate_status": evidence_artifacts.evidence_gate_status,
            "blocking_reasons": [] if rule_gate_status == "PASS" else blocking_reasons,
            "evidence_refs": [evidence_artifacts.evidence.get("evidence_id")],
        }

        return RuleArtifacts(
            rule_hit=primary_rule_hit,
            rule_hits=rule_hits,
            rule_gate_decision=rule_gate_decision,
            rule_selection_trace=rule_selection_trace,
            rule_execution_trace=rule_execution_trace,
            rule_coverage_summary=coverage_summary,
            rule_hit_state=primary_rule_hit_state,
            rule_gate_status=rule_gate_status,
            lineage_status=lineage_status,
            conflict_state=conflict_state,
        )


__all__ = [
    "QUAL_PM_RULE_CODES",
    "RuleArtifacts",
    "RuleRunner",
    "evaluate_project_manager_qualification_rules",
]
