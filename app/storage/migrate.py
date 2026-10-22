"""Run Alembic migrations from code (on app startup and in tests).

In production, migrations usually run as a separate deploy step before the new app version
starts; running them on startup keeps this project a one-command demo.
"""

from alembic import command
from alembic.config import Config

from app.config import PROJECT_ROOT


def alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade_to_head(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")
