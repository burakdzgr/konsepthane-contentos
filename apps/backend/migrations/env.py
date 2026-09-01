"""Alembic environment bound to ContentOS settings and metadata.

The database URL always comes from the typed ContentOS settings
(CONTENTOS_DATABASE_URL) and must never be logged or printed here.
"""

from alembic import context

from contentos.core.config import Settings
from contentos.db.base import Base
from contentos.db.session import create_database_engine

# Model modules must be imported so Base.metadata reflects the full schema.
from contentos.discovery import models as _discovery_models  # noqa: F401
from contentos.duplicates import models as _duplicate_models  # noqa: F401
from contentos.fetching import snapshots as _fetch_snapshots  # noqa: F401
from contentos.normalization import models as _normalization_models  # noqa: F401
from contentos.opportunities import models as _opportunity_models  # noqa: F401
from contentos.payloads import postgres as _payload_models  # noqa: F401
from contentos.research import models as _research_models  # noqa: F401
from contentos.sources import models as _sources_models  # noqa: F401
from contentos.workflow import models as _workflow_models  # noqa: F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Render migration SQL without opening a database connection."""
    context.configure(
        url=Settings().database_url.get_secret_value(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations through the standard ContentOS engine factory."""
    engine = create_database_engine(Settings())
    try:
        with engine.connect() as connection:
            context.configure(connection=connection, target_metadata=target_metadata)
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
