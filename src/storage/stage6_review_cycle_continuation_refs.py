from __future__ import annotations

from pathlib import Path
from typing import Any


def build_stage6_review_cycle_continuation_input_refs(
    *,
    output_root: str | Path,
    release_field_query_json: str | Path | None = None,
    supplemental_release_field_query_json: str | Path | None = None,
    runtime_blocker_next_subqueue_json: str | Path | None = None,
    stage6_review_loop_status_json: str | Path | None = None,
    gdcic_browser_readback_json: str | Path | None = None,
    stage1_6_scoreboard_json: str | Path | None = None,
) -> dict[str, Any]:
    out_dir = Path(output_root)
    status_path = _existing_file(stage6_review_loop_status_json) or out_dir / "stage6-review-loop-project-status-table.json"
    release_field_query_path = _existing_file(release_field_query_json)
    supplemental_release_field_query_paths = _existing_files(supplemental_release_field_query_json)
    next_subqueue_path = _provided_path(runtime_blocker_next_subqueue_json)
    gdcic_readback_path = _existing_file(gdcic_browser_readback_json)
    scoreboard_path = _existing_file(stage1_6_scoreboard_json)
    return {
        "prior_stage6_status_json": str(status_path),
        "effective_stage6_status_root": str(status_path.parent),
        "effective_release_field_query_json": str(release_field_query_path or ""),
        "effective_release_field_query_root": _parent_text(release_field_query_path),
        "effective_supplemental_release_field_query_json": _joined_paths(supplemental_release_field_query_paths),
        "effective_supplemental_release_field_query_root": _joined_parent_paths(supplemental_release_field_query_paths),
        "effective_runtime_blocker_next_subqueue_json": str(next_subqueue_path or ""),
        "effective_runtime_blocker_next_subqueue_root": _parent_text(next_subqueue_path),
        "effective_gdcic_browser_readback_json": str(gdcic_readback_path or ""),
        "effective_gdcic_browser_readback_root": _parent_text(gdcic_readback_path),
        "effective_stage1_6_scoreboard_json": str(scoreboard_path or ""),
        "stage6_status_root_resolution_state": "RESOLVED_FROM_OUTPUT_ROOT",
        "release_field_query_root_resolution_state": _resolution_state(release_field_query_path),
        "supplemental_release_field_query_root_resolution_state": _resolution_state(
            supplemental_release_field_query_paths
        ),
        "runtime_blocker_next_subqueue_root_resolution_state": _resolution_state(next_subqueue_path),
        "gdcic_browser_readback_root_resolution_state": _resolution_state(gdcic_readback_path),
        "stage1_6_scoreboard_resolution_state": _resolution_state(scoreboard_path),
        "customer_visible_allowed": False,
        "query_miss_is_not_clearance": True,
        "no_legal_conclusion": True,
    }


def _existing_file(value: str | Path | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.exists() and path.is_file() else None


def _existing_files(value: str | Path | None) -> list[Path]:
    if not value:
        return []
    out: list[Path] = []
    for part in str(value).split(";"):
        text = part.strip()
        if not text:
            continue
        path = Path(text)
        if path.exists() and path.is_file():
            out.append(path)
    return out


def _provided_path(value: str | Path | None) -> Path | None:
    if not value:
        return None
    return Path(value)


def _parent_text(path: Path | None) -> str:
    return str(path.parent) if path else ""


def _joined_paths(paths: list[Path]) -> str:
    return ";".join(str(path) for path in paths)


def _joined_parent_paths(paths: list[Path]) -> str:
    return ";".join(str(path.parent) for path in paths)


def _resolution_state(path: Path | list[Path] | None) -> str:
    if isinstance(path, list):
        return "RESOLVED_FROM_STAGE6_INPUT_REFS" if path else "UNRESOLVED"
    return "RESOLVED_FROM_STAGE6_INPUT_REFS" if path else "UNRESOLVED"
