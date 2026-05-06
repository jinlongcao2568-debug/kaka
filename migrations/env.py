from __future__ import annotations

import os
import sys
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from storage.sqlalchemy_schema import metadata  # noqa: E402


config = context.config
target_metadata = metadata


def _database_url() -> str:
    x_args = context.get_x_argument(as_dictionary=True)
    database_url = x_args.get("database_url") or os.getenv("KAKA_STORAGE_DATABASE_URL")
    if not database_url:
        raise RuntimeError(
            "KAKA_STORAGE_DATABASE_URL or alembic -x database_url=... is required for storage migrations"
        )
    return database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(
        _database_url(),
        poolclass=pool.NullPool,
        future=True,
    )

    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
