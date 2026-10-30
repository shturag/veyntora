from alembic import command

from tests.conftest import _alembic


def test_upgrade_downgrade_upgrade(migrated: str) -> None:
    cfg = _alembic(migrated)
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")


def test_models_match_migrations(migrated: str) -> None:
    # Raises if autogenerate would produce any operation, i.e. models and migrations drifted.
    command.check(_alembic(migrated))
