"""Fail closed when production dependency locks are missing or incomplete."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOCK_PAIRS = (
    (ROOT / "requirements-api.txt", ROOT / "requirements-api.lock.txt"),
    (ROOT / "requirements.txt", ROOT / "requirements.lock.txt"),
)
REQUIREMENT_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==(?P<version>[^\s;]+)"
)
LOCKED_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s\\;]+)(?:\s*;.*)?\s*\\?$"
)
HASH_RE = re.compile(r"^\s+--hash=sha256:[0-9a-f]{64}(?:\s+\\)?$")


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = REQUIREMENT_RE.fullmatch(line)
        if match is None:
            raise ValueError(f"{path.name}:{line_number}: only exact == pins are allowed")
        name = _canonical_name(match.group("name"))
        if name in pins:
            raise ValueError(f"{path.name}:{line_number}: duplicate direct pin for {name}")
        pins[name] = match.group("version")
    if not pins:
        raise ValueError(f"{path.name}: no direct dependency pins found")
    return pins


def _locked_pins(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lowered = text.lower()
    forbidden = (
        "--index-url",
        "--extra-index-url",
        "--trusted-host",
        "--find-links",
        "http://",
        "https://",
        "file://",
    )
    for marker in forbidden:
        if marker in lowered:
            raise ValueError(f"{path.name}: forbidden dependency source marker {marker!r}")
    if "pip-compile" not in text or "Python 3.12" not in text:
        raise ValueError(f"{path.name}: missing Python 3.12 pip-compile provenance")

    lines = text.splitlines()
    pins: dict[str, str] = {}
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        match = LOCKED_RE.fullmatch(raw_line)
        if match is None:
            stripped = raw_line.strip()
            if stripped and not stripped.startswith("#"):
                raise ValueError(
                    f"{path.name}:{index + 1}: unrecognized lock content"
                )
            index += 1
            continue
        name = _canonical_name(match.group("name"))
        if name in pins:
            raise ValueError(f"{path.name}:{index + 1}: duplicate lock entry for {name}")
        pins[name] = match.group("version")
        index += 1
        hash_count = 0
        while index < len(lines) and HASH_RE.fullmatch(lines[index]):
            hash_count += 1
            index += 1
        if hash_count == 0:
            raise ValueError(f"{path.name}: lock entry {name} has no sha256 hash")
    if not pins:
        raise ValueError(f"{path.name}: no locked dependencies found")
    return pins


def validate_pair(requirements_path: Path, lock_path: Path) -> None:
    direct = _direct_pins(requirements_path)
    locked = _locked_pins(lock_path)
    for name, expected_version in direct.items():
        actual_version = locked.get(name)
        if actual_version is None:
            raise ValueError(f"{lock_path.name}: missing direct dependency {name}")
        if actual_version != expected_version:
            raise ValueError(
                f"{lock_path.name}: {name} is {actual_version}, expected {expected_version}"
            )


def main() -> int:
    try:
        for requirements_path, lock_path in LOCK_PAIRS:
            validate_pair(requirements_path, lock_path)
    except (OSError, ValueError) as exc:
        print(f"dependency lock validation failed: {exc}", file=sys.stderr)
        return 1
    print("dependency lock validation passed: api and worker locks are exact and hashed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
