from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from stage1_tasking.service import Stage1Service
from stage2_ingestion.service import Stage2Service
from stage3_parsing.service import Stage3Service
from stage4_verification.service import Stage4Service
from stage5_rules_evidence.service import Stage5Service
from stage6_fact_review.service import Stage6Service
from stage7_sales.service import Stage7Service

FIXTURES = ROOT / "fixtures"


def load_fixture(name: str) -> Dict[str, Any]:
    path = FIXTURES / name
    return json.loads(path.read_text(encoding="utf-8"))


def load_repo_json(relative_path: str) -> Dict[str, Any]:
    path = ROOT / relative_path
    return json.loads(path.read_text(encoding="utf-8"))


def run_internal_chain_to_stage7(payload: Dict[str, Any]) -> Dict[str, Any]:
    stage1 = Stage1Service().run(payload)
    stage2 = Stage2Service().run(stage1)
    stage3 = Stage3Service().run(stage2)
    stage4 = Stage4Service().run(stage3)
    stage5 = Stage5Service().run(stage4)
    stage6 = Stage6Service().run(stage5)
    stage7 = Stage7Service().run(stage6)
    return {
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3,
        "stage4": stage4,
        "stage5": stage5,
        "stage6": stage6,
        "stage7": stage7,
    }


def extract_service_record_dependencies(relative_path: str) -> list[str]:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    return sorted(set(__import__("re").findall(r'\.record\("([^"]+)"\)', text)))


def extract_service_optional_record_dependencies(relative_path: str) -> list[str]:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    re_module = __import__("re")
    matches = set(re_module.findall(r'\.records\.get\("([^"]+)"\)', text))
    matches.update(re_module.findall(r"\.records\[['\"]([^'\"]+)['\"]\]", text))
    return sorted(matches)
