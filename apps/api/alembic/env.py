from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from apps.api.app import model_extraction_models, models  # noqa: F401
from apps.api.app.calculation_rules import models as calculation_rule_models  # noqa: F401
from apps.api.app.calculation_rules import phase2_models as calculation_engine_models  # noqa: F401
from apps.api.app.database import Base, DATABASE_URL


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

configured_url = config.get_main_option("sqlalchemy.url").strip()
database_url = configured_url or DATABASE_URL
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def _context_options() -> dict[str, object]:
    return {
        "target_metadata": target_metadata,
        "compare_type": True,
        "render_as_batch": database_url.startswith("sqlite"),
    }


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_context_options(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, **_context_options())

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
