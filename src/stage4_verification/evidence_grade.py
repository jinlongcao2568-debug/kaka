# Stage: stage4_verification
# Consumes formal objects: public_attack_surface, focus_bidder_verification_profile, pseudo_competitor_signal_set, evidence_grade_profile
# Dependent handoff: H-03-STAGE3-TO-STAGE4, H-04-STAGE4-TO-STAGE5
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceGradeProfile:
    evidence_grade_id: str
    # TODO: align with contracts/schemas/schema_catalog.json


PUBLIC_EVIDENCE_STRONG = "PUBLIC_SNAPSHOT_FIELD_MATCH"
PUBLIC_EVIDENCE_WEAK = "PUBLIC_WEAK_REVIEW_REQUIRED"
PUBLIC_EVIDENCE_CONFLICT = "PUBLIC_CONFLICT_REVIEW_REQUIRED"
PUBLIC_EVIDENCE_INSUFFICIENT = "INSUFFICIENT_PUBLIC_EVIDENCE"
PUBLIC_EVIDENCE_NOT_REPLAYABLE = "NO_REPLAYABLE_PUBLIC_SNAPSHOT"
PUBLIC_EVIDENCE_NOT_PUBLIC = "SOURCE_NOT_PUBLIC_REVIEW_REQUIRED"


def grade_public_verification_evidence(
    *,
    replayable_snapshot: bool,
    public_source: bool,
    matched: bool,
    conflict: bool = False,
    ambiguous: bool = False,
    weak: bool = False,
) -> str:
    """Return a Stage4 readback-only evidence grade string, not a formal enum."""
    if not replayable_snapshot:
        return PUBLIC_EVIDENCE_NOT_REPLAYABLE
    if not public_source:
        return PUBLIC_EVIDENCE_NOT_PUBLIC
    if conflict:
        return PUBLIC_EVIDENCE_CONFLICT
    if ambiguous or weak:
        return PUBLIC_EVIDENCE_WEAK
    if matched:
        return PUBLIC_EVIDENCE_STRONG
    return PUBLIC_EVIDENCE_INSUFFICIENT
