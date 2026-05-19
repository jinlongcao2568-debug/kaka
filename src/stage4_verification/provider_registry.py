# Stage: stage4_verification
# Provider registry and route planning for public verification adapters.

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable, Mapping


JZSC_PERSON_IDENTITY = "JZSC_PERSON_IDENTITY"
GUANGDONG_THREE_LIBRARY = "GUANGDONG_THREE_LIBRARY"
LOCAL_HOUSING_CONSTRUCTION = "LOCAL_HOUSING_CONSTRUCTION"
NATURAL_RESOURCE_REGISTERED_SURVEYOR = "NATURAL_RESOURCE_REGISTERED_SURVEYOR"
CONSTRUCTION_PERMIT = "CONSTRUCTION_PERMIT"
CONTRACT_FILING = "CONTRACT_FILING"
COMPLETION_FILING = "COMPLETION_FILING"
PROJECT_MANAGER_CHANGE = "PROJECT_MANAGER_CHANGE"
PENALTY_CREDIT = "PENALTY_CREDIT"
SUPPLIER_QUALIFICATION_CREDIT = "SUPPLIER_QUALIFICATION_CREDIT"


HIGH_VALUE_ENGINEERING_CLASSES = frozenset(
    {
        "A_HIGH_CONSTRUCTION_EPC",
        "B_HIGH_SUPERVISION",
        "C_MEDIUM_DESIGN_SURVEY",
    }
)


@dataclass(frozen=True)
class Stage4ProviderSpec:
    provider_id: str
    display_name: str
    source_family: str
    provider_role: str
    supported_priority_classes: tuple[str, ...]
    expected_input_fields: tuple[str, ...]
    output_identity_fields: tuple[str, ...]
    output_project_fields: tuple[str, ...]
    route_priority: int
    use_for_person_company_cert_identity: bool = False
    use_for_performance_conflict: bool = False
    public_only: bool = True
    customer_visible_by_default: bool = False
    no_legal_conclusion: bool = True

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Stage4ProviderTask:
    task_id: str
    provider_id: str
    provider_role: str
    target: dict[str, Any]
    required_input_fields: tuple[str, ...]
    expected_output_fields: tuple[str, ...]
    route_priority: int
    review_if_not_found: bool = True
    no_negative_conclusion_on_not_found: bool = True
    use_for_performance_conflict: bool = False

    def as_payload(self) -> dict[str, Any]:
        return asdict(self)


PROVIDER_SPECS: tuple[Stage4ProviderSpec, ...] = (
    Stage4ProviderSpec(
        provider_id=JZSC_PERSON_IDENTITY,
        display_name="全国建筑市场监管公共服务平台人员身份核验",
        source_family="national_construction_market_platform",
        provider_role="person_company_certificate_identity",
        supported_priority_classes=tuple(sorted(HIGH_VALUE_ENGINEERING_CLASSES)),
        expected_input_fields=(
            "candidate_company_name",
            "responsible_person_name",
        ),
        output_identity_fields=(
            "person_company_cert_matched",
            "registered_unit_name",
            "certificate_no",
            "person_public_id",
            "certificate_type",
            "specialty",
            "grade",
            "registration_at",
            "registration_changed_at",
            "certificate_valid_from",
            "certificate_valid_until",
        ),
        output_project_fields=(),
        route_priority=10,
        use_for_person_company_cert_identity=True,
        use_for_performance_conflict=False,
    ),
    Stage4ProviderSpec(
        provider_id=GUANGDONG_THREE_LIBRARY,
        display_name="广东省三库一平台人员/企业核验",
        source_family="guangdong_three_library",
        provider_role="local_person_company_certificate_identity",
        supported_priority_classes=tuple(sorted(HIGH_VALUE_ENGINEERING_CLASSES)),
        expected_input_fields=(
            "candidate_company_name",
            "responsible_person_name",
            "certificate_no_optional",
            "person_public_id_optional",
        ),
        output_identity_fields=(
            "registered_unit_name",
            "certificate_no",
            "person_public_id",
            "certificate_type",
            "specialty",
            "grade",
            "registration_at",
            "registration_changed_at",
            "certificate_valid_from",
            "certificate_valid_until",
        ),
        output_project_fields=(),
        route_priority=20,
        use_for_person_company_cert_identity=True,
        use_for_performance_conflict=False,
    ),
    Stage4ProviderSpec(
        provider_id=LOCAL_HOUSING_CONSTRUCTION,
        display_name="地方住建人员注册/企业资质核验",
        source_family="local_housing_construction_authority",
        provider_role="local_registered_personnel_and_enterprise_qualification",
        supported_priority_classes=tuple(sorted(HIGH_VALUE_ENGINEERING_CLASSES)),
        expected_input_fields=(
            "candidate_company_name",
            "responsible_person_name",
            "certificate_no_optional",
        ),
        output_identity_fields=(
            "registered_unit_name",
            "certificate_no",
            "certificate_type",
            "specialty",
            "grade",
            "certificate_valid_until",
        ),
        output_project_fields=(),
        route_priority=30,
        use_for_person_company_cert_identity=True,
        use_for_performance_conflict=False,
    ),
    Stage4ProviderSpec(
        provider_id=NATURAL_RESOURCE_REGISTERED_SURVEYOR,
        display_name="自然资源注册测绘师公开注册核验",
        source_family="natural_resource_registered_surveyor_public_registry",
        provider_role="registered_surveyor_person_company_certificate_identity",
        supported_priority_classes=("C_MEDIUM_DESIGN_SURVEY",),
        expected_input_fields=(
            "candidate_company_name",
            "responsible_person_name",
            "certificate_no_optional",
        ),
        output_identity_fields=(
            "person_company_cert_matched",
            "registered_unit_name",
            "certificate_no_or_registration_no",
            "certificate_type",
            "registration_status",
            "certificate_valid_from",
            "certificate_valid_until",
            "source_url_or_snapshot_id",
        ),
        output_project_fields=(),
        route_priority=35,
        use_for_person_company_cert_identity=True,
        use_for_performance_conflict=False,
    ),
    Stage4ProviderSpec(
        provider_id=CONSTRUCTION_PERMIT,
        display_name="施工许可公开信息核验",
        source_family="construction_permit_public_source",
        provider_role="active_project_and_role_public_record",
        supported_priority_classes=("A_HIGH_CONSTRUCTION_EPC", "B_HIGH_SUPERVISION"),
        expected_input_fields=(
            "certificate_no_or_person_public_id",
            "responsible_person_name",
            "candidate_company_name",
        ),
        output_identity_fields=(),
        output_project_fields=(
            "project_name",
            "permit_no",
            "construction_unit",
            "contractor_name",
            "project_manager_name",
            "chief_supervision_engineer_name",
            "permit_date",
            "construction_start_at",
            "construction_end_at",
        ),
        route_priority=40,
        use_for_performance_conflict=True,
    ),
    Stage4ProviderSpec(
        provider_id=CONTRACT_FILING,
        display_name="合同备案公开信息核验",
        source_family="contract_filing_public_source",
        provider_role="contract_role_time_window_public_record",
        supported_priority_classes=("A_HIGH_CONSTRUCTION_EPC", "B_HIGH_SUPERVISION"),
        expected_input_fields=(
            "certificate_no_or_person_public_id",
            "responsible_person_name",
            "candidate_company_name",
        ),
        output_identity_fields=(),
        output_project_fields=(
            "contract_no",
            "project_name",
            "contractor_name",
            "project_manager_name",
            "chief_supervision_engineer_name",
            "contract_start_at",
            "contract_end_at",
        ),
        route_priority=50,
        use_for_performance_conflict=True,
    ),
    Stage4ProviderSpec(
        provider_id=COMPLETION_FILING,
        display_name="竣工/验收备案公开信息核验",
        source_family="completion_filing_public_source",
        provider_role="completion_acceptance_public_record",
        supported_priority_classes=("A_HIGH_CONSTRUCTION_EPC", "B_HIGH_SUPERVISION"),
        expected_input_fields=(
            "certificate_no_or_person_public_id",
            "responsible_person_name",
            "candidate_company_name",
        ),
        output_identity_fields=(),
        output_project_fields=(
            "project_name",
            "completion_acceptance_at",
            "completion_acceptance_status",
            "project_manager_name",
            "chief_supervision_engineer_name",
        ),
        route_priority=60,
        use_for_performance_conflict=True,
    ),
    Stage4ProviderSpec(
        provider_id=PROJECT_MANAGER_CHANGE,
        display_name="项目负责人/总监变更公告核验",
        source_family="project_manager_change_public_notice",
        provider_role="role_change_public_record",
        supported_priority_classes=("A_HIGH_CONSTRUCTION_EPC", "B_HIGH_SUPERVISION"),
        expected_input_fields=(
            "certificate_no_or_person_public_id",
            "responsible_person_name",
            "candidate_company_name",
        ),
        output_identity_fields=(),
        output_project_fields=(
            "project_name",
            "before_person_name",
            "after_person_name",
            "change_date",
            "change_approval_source_url",
        ),
        route_priority=70,
        use_for_performance_conflict=True,
    ),
    Stage4ProviderSpec(
        provider_id=PENALTY_CREDIT,
        display_name="处罚/信用公告核验",
        source_family="credit_penalty_public_notice",
        provider_role="enterprise_person_credit_penalty_public_record",
        supported_priority_classes=(
            "A_HIGH_CONSTRUCTION_EPC",
            "B_HIGH_SUPERVISION",
            "C_MEDIUM_DESIGN_SURVEY",
            "D_LOW_SUPPLIER_SERVICE",
        ),
        expected_input_fields=(
            "candidate_company_name",
            "responsible_person_name_optional",
            "certificate_no_optional",
        ),
        output_identity_fields=(),
        output_project_fields=(
            "penalty_subject",
            "penalty_reason",
            "penalty_date",
            "credit_status",
        ),
        route_priority=80,
        use_for_performance_conflict=False,
    ),
    Stage4ProviderSpec(
        provider_id=SUPPLIER_QUALIFICATION_CREDIT,
        display_name="供应商资格/信用/业绩核验",
        source_family="supplier_qualification_credit_public_source",
        provider_role="supplier_qualification_credit_review",
        supported_priority_classes=("D_LOW_SUPPLIER_SERVICE",),
        expected_input_fields=("candidate_company_name",),
        output_identity_fields=(),
        output_project_fields=(
            "supplier_qualification",
            "similar_performance",
            "price_signal",
            "credit_status",
        ),
        route_priority=90,
        use_for_performance_conflict=False,
    ),
)

PROVIDERS_BY_ID = {provider.provider_id: provider for provider in PROVIDER_SPECS}


def list_stage4_providers() -> list[dict[str, Any]]:
    return [provider.as_payload() for provider in PROVIDER_SPECS]


def get_stage4_provider(provider_id: str) -> dict[str, Any]:
    provider = PROVIDERS_BY_ID.get(str(provider_id or "").strip())
    if provider is None:
        raise KeyError(f"unknown_stage4_provider:{provider_id}")
    return provider.as_payload()


def build_stage4_provider_plan(
    context: Mapping[str, Any] | None = None,
    *,
    opportunity_priority_class: str | None = None,
    candidate_company_name: str | None = None,
    responsible_person_name: str | None = None,
    certificate_no: str | None = None,
    person_public_id: str | None = None,
    requested_provider_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    payload = dict(context or {})
    priority_class = (
        str(opportunity_priority_class or payload.get("opportunity_priority_class") or "").strip()
        or "REVIEW_UNCLASSIFIED_ENGINEERING"
    )
    company = str(candidate_company_name or payload.get("candidate_company_name") or "").strip()
    person = str(
        responsible_person_name
        or payload.get("responsible_person_name")
        or payload.get("project_manager_name")
        or payload.get("chief_supervision_engineer_name")
        or payload.get("design_lead_name")
        or ""
    ).strip()
    cert = str(certificate_no or payload.get("certificate_no") or "").strip()
    public_id = str(person_public_id or payload.get("person_public_id") or "").strip()
    requested = {str(item).strip() for item in requested_provider_ids or [] if str(item).strip()}

    selected = [
        provider
        for provider in PROVIDER_SPECS
        if priority_class in provider.supported_priority_classes
        and (not requested or provider.provider_id in requested)
    ]
    selected.sort(key=lambda provider: provider.route_priority)

    tasks = [
        _task_for_provider(
            provider,
            priority_class=priority_class,
            company=company,
            person=person,
            certificate_no=cert,
            person_public_id=public_id,
        ).as_payload()
        for provider in selected
    ]
    return {
        "provider_plan_id": _stable_plan_id(priority_class, company, person, cert, public_id),
        "opportunity_priority_class": priority_class,
        "target": {
            "candidate_company_name": company,
            "responsible_person_name": person,
            "certificate_no_optional": cert,
            "person_public_id_optional": public_id,
        },
        "providers": [provider.as_payload() for provider in selected],
        "tasks": tasks,
        "policy": {
            "jzsc_project_records_used_for_performance_conflict": False,
            "not_found_is_review_not_negative_fact": True,
            "no_name_only_final_proof": True,
            "public_only": True,
            "no_legal_conclusion": True,
        },
    }


def _task_for_provider(
    provider: Stage4ProviderSpec,
    *,
    priority_class: str,
    company: str,
    person: str,
    certificate_no: str,
    person_public_id: str,
) -> Stage4ProviderTask:
    target = {
        "opportunity_priority_class": priority_class,
        "candidate_company_name": company,
        "responsible_person_name": person,
        "certificate_no_optional": certificate_no,
        "person_public_id_optional": person_public_id,
    }
    expected_output_fields = tuple(
        dict.fromkeys([*provider.output_identity_fields, *provider.output_project_fields])
    )
    return Stage4ProviderTask(
        task_id=_stable_plan_id(provider.provider_id, priority_class, company, person, certificate_no, person_public_id),
        provider_id=provider.provider_id,
        provider_role=provider.provider_role,
        target=target,
        required_input_fields=provider.expected_input_fields,
        expected_output_fields=expected_output_fields,
        route_priority=provider.route_priority,
        use_for_performance_conflict=provider.use_for_performance_conflict,
    )


def _stable_plan_id(*parts: Any) -> str:
    import hashlib
    import json

    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    return "ST4PROV-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
