from functools import lru_cache
from typing import Annotated, Iterator

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event, inspect
from sqlalchemy.orm import Session

from .config import database_description, database_url, sqlite_path


@lru_cache
def engine_for(url: str) -> Engine:
    engine = create_engine(url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def engine() -> Engine:
    return engine_for(database_url())


def missing_schema() -> str | None:
    """Explain why the identity tables are unavailable, without creating an empty SQLite file."""
    path = sqlite_path()
    if path is not None and not path.exists():
        return f"Identity database {path} does not exist. From station-service, run: python -m alembic upgrade head"
    if not inspect(engine()).has_table("users"):
        return f"Identity tables are missing in {database_description()}. From station-service, run: python -m alembic upgrade head"
    return None


def get_db() -> Iterator[Session]:
    with Session(engine(), expire_on_commit=False) as session:
        yield session


Database = Annotated[Session, Depends(get_db)]
