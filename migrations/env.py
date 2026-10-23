from alembic import context
from pharmaguard.config import load_settings
from pharmaguard.db import Base
from sqlalchemy import create_engine

if context.is_offline_mode():
    context.configure(
        url=load_settings().database_url(),
        target_metadata=Base.metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    with create_engine(
        load_settings().database_url(), connect_args={"connect_timeout": 5}
    ).connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
