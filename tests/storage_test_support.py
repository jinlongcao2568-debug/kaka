from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

from storage import reset_default_storage
from storage.db import DatabaseSession

try:
    from api.deps import get_settings
except Exception:  # pragma: no cover - defensive test bootstrap fallback
    get_settings = None


def _clear_settings_cache() -> None:
    if get_settings is not None:
        get_settings.cache_clear()


def _close_default_database_session() -> None:
    if DatabaseSession._default is not None:
        DatabaseSession._default.close()
        DatabaseSession._default = None


class IsolatedStorageTestMixin:
    _storage_test_tmp_dir: tempfile.TemporaryDirectory[str] | None = None
    _storage_test_env_patcher: Any = None

    def setUp_storage_test_env(self, *, storage_filename: str) -> None:
        self._storage_test_tmp_dir = tempfile.TemporaryDirectory()
        tmp_root = Path(self._storage_test_tmp_dir.name)
        self._storage_test_env_patcher = patch.dict(
            os.environ,
            {
                "KAKA_STORAGE_BACKEND": "json-file",
                "KAKA_STORAGE_SCOPE": "process",
                "KAKA_STORAGE_PATH": str(tmp_root / storage_filename),
                "KAKA_OBJECT_STORAGE_BACKEND": "local-filesystem",
                "KAKA_OBJECT_STORAGE_PATH": str(tmp_root / "objects"),
                "LOCALAPPDATA": str(tmp_root / "local-app-data"),
            },
            clear=False,
        )
        self._storage_test_env_patcher.start()
        for key in ("KAKA_STORAGE_DATABASE_URL", "KAKA_STORAGE_TEST_ISOLATION"):
            os.environ.pop(key, None)
        _clear_settings_cache()
        _close_default_database_session()
        reset_default_storage()

    def tearDown_storage_test_env(self) -> None:
        try:
            reset_default_storage()
        finally:
            _close_default_database_session()
            _clear_settings_cache()
            if self._storage_test_env_patcher is not None:
                self._storage_test_env_patcher.stop()
                self._storage_test_env_patcher = None
            if self._storage_test_tmp_dir is not None:
                self._storage_test_tmp_dir.cleanup()
                self._storage_test_tmp_dir = None
            _clear_settings_cache()
