from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "validate_dependency_locks.py"
SPEC = importlib.util.spec_from_file_location("validate_dependency_locks", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
lock_validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lock_validator)


class DependencyLockValidationTests(unittest.TestCase):
    def test_repository_locks_are_exact_and_hashed(self) -> None:
        for requirements_path, lock_path in lock_validator.LOCK_PAIRS:
            lock_validator.validate_pair(requirements_path, lock_path)

    def test_missing_hash_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            requirements_path = root / "requirements.txt"
            lock_path = root / "requirements.lock.txt"
            requirements_path.write_text("demo==1.0\n", encoding="utf-8")
            lock_path.write_text(
                "# pip-compile with Python 3.12\ndemo==1.0\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "has no sha256 hash"):
                lock_validator.validate_pair(requirements_path, lock_path)

    def test_direct_pin_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            requirements_path = root / "requirements.txt"
            lock_path = root / "requirements.lock.txt"
            requirements_path.write_text("demo[extra]==2.0\n", encoding="utf-8")
            lock_path.write_text(
                "# pip-compile with Python 3.12\n"
                "demo==1.0 \\" + "\n"
                "    --hash=sha256:" + "a" * 64 + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "expected 2.0"):
                lock_validator.validate_pair(requirements_path, lock_path)

    def test_direct_url_source_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            requirements_path = root / "requirements.txt"
            lock_path = root / "requirements.lock.txt"
            requirements_path.write_text("demo==1.0\n", encoding="utf-8")
            lock_path.write_text(
                "# pip-compile with Python 3.12\n"
                "demo==1.0 \\" + "\n"
                "    --hash=sha256:" + "a" * 64 + "\n"
                "payload@https://packages.invalid/payload.whl\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "forbidden dependency source"):
                lock_validator.validate_pair(requirements_path, lock_path)


if __name__ == "__main__":
    unittest.main()
