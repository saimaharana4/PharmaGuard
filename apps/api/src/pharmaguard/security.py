from datetime import UTC, datetime

from sqlalchemy.orm import Session

from pharmaguard.db import RequestBudget
from pharmaguard.errors import DomainError


def reserve_request(session: Session, limit: int) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    insert = pg_insert if session.bind.dialect.name == "postgresql" else sqlite_insert
    statement = insert(RequestBudget).values(day=datetime.now(UTC).date(), used=1)
    statement = statement.on_conflict_do_update(
        index_elements=["day"],
        set_={"used": RequestBudget.used + 1},
        where=RequestBudget.used < limit,
    ).returning(RequestBudget.used)
    count = session.scalar(statement)
    session.commit()
    if count is None:
        raise DomainError(
            "USAGE_LIMIT", "The shared daily investigation limit has been reached.", 429
        )
