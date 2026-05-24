from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml


class StageStateMachine:
    def __init__(self, stage_graph: list[Mapping[str, Any]]) -> None:
        self._stages = [dict(stage) for stage in stage_graph]
        self._by_stage = {str(stage["stage_id"]): dict(stage) for stage in self._stages}

    @classmethod
    def from_contract_path(cls, path: str | Path) -> "StageStateMachine":
        payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls(payload["stage_graph"])

    @classmethod
    def default(cls) -> "StageStateMachine":
        root = Path(__file__).resolve().parents[2]
        return cls.from_contract_path(root / "control" / "runtime_architecture_contract.yaml")

    def next_stage_id(self, stage_id: str) -> str:
        if stage_id not in self._by_stage:
            raise KeyError(f"unknown_stage_id:{stage_id}")
        return str(self._by_stage[stage_id]["next_stage_id"])

    def stage_order_until(self, stage_id: str) -> list[str]:
        if stage_id not in self._by_stage:
            raise KeyError(f"unknown_stage_id:{stage_id}")
        ordered: list[str] = []
        for stage in sorted(self._stages, key=lambda item: int(item["stage_index"])):
            ordered.append(str(stage["stage_id"]))
            if stage["stage_id"] == stage_id:
                return ordered
        return ordered
