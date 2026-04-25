# Stage: stage3_parsing
# Consumes formal objects: project_base, field_lineage_record, bidder_candidate, project_manager
# Dependent handoff: H-02-STAGE2-TO-STAGE3, H-03-STAGE3-TO-STAGE4
# Dependent schema/contracts: handoff/stage_handoff_catalog.json, contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json

from stage3_parsing.real_parser import Stage3ParserCarrier, Stage3RealParser

__all__ = ["Stage3ParserCarrier", "Stage3RealParser"]
