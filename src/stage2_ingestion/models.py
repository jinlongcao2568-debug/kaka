# Stage: stage2_ingestion
# Consumes formal objects: public_chain, clock_chain_profile, notice_version_chain, fixation_bundle
# Dependent handoff: H-01-STAGE1-TO-STAGE2, H-02-STAGE2-TO-STAGE3
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from dataclasses import dataclass


@dataclass(frozen=True)
class PublicChain:
    public_chain_id: str
    # TODO: align with contracts/schemas/schema_catalog.json

@dataclass(frozen=True)
class ClockChainProfile:
    clock_chain_id: str
    # TODO: align with contracts/schemas/schema_catalog.json

@dataclass(frozen=True)
class NoticeVersionChain:
    version_chain_id: str
    # TODO: align with contracts/schemas/schema_catalog.json
