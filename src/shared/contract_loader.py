# Stage: shared
# Consumes formal objects: N/A
# Dependent handoff: N/A
# Dependent schema/contracts: contracts/schemas/schema_catalog.json, contracts/enums/enum_catalog.json, handoff/stage_handoff_catalog.json

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from shared.settings import Settings


def load_contract(path: str, settings: Optional[Settings] = None) -> Any:
    repo_root = Path(settings.repo_root) if settings and settings.repo_root else Path(__file__).resolve().parents[2]
    target = repo_root / path
    if not target.exists():
        raise FileNotFoundError(f"contract file not found: {target}")
    if target.suffix.lower() in {".yaml", ".yml"}:
        raise ValueError("YAML contracts are not supported in this runtime")
    return json.loads(target.read_text(encoding="utf-8"))


__all__ = ["load_contract"]
