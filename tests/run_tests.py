from __future__ import annotations

import unittest
from pathlib import Path
import sys


def main() -> int:
    start_dir = Path(__file__).resolve().parent
    repo_root = start_dir.parent
    src_dir = repo_root / "src"
    for path in (repo_root, src_dir, start_dir):
        if str(path) not in sys.path:
            sys.path.insert(0, str(path))
    suite = unittest.TestLoader().discover(str(start_dir), top_level_dir=str(repo_root))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
