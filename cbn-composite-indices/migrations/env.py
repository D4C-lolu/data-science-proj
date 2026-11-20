"""Alembic runtime configuration; schema changes are handwritten migrations."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

database_url = os.environ.get("DATABASE_URL")
if database_url:
    # ConfigParser treats percent signs as interpolation syntax.
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))

# Intentionally no target_metadata: ORM metadata must never drive migrations.
target_metadata = None


def reject_autogenerate():
    command_options = getattr(config, "cmd_opts", None)
    if command_options is not None and getattr(command_options, "autogenerate", False):
        raise RuntimeError(
            "Autogenerate is disabled. Write and review schema migrations by hand."
        )


def run_migrations_offline():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


reject_autogenerate()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
