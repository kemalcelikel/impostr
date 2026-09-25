from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select

from app.models import BootstrapState


def _alembic_config() -> Config:
    api_directory = Path(__file__).resolve().parents[1]
    config = Config(str(api_directory / "alembic.ini"))
    config.set_main_option("script_location", str(api_directory / "migrations"))
    return config


def test_identity_and_private_metadata_migration_upgrades_and_downgrades(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'migration.db'}")
    config = _alembic_config()

    try:
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            table_names = set(inspect(connection).get_table_names())
            assert {
                "users",
                "web_sessions",
                "rate_limit_buckets",
                "audit_events",
                "projects",
                "bootstrap_state",
            }.issubset(table_names)
            assert connection.scalar(select(BootstrapState.completed)) is False

        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.downgrade(config, "base")
            assert set(inspect(connection).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
