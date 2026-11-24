from functools import lru_cache
from typing import Annotated, Iterator

from fastapi import Depends
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session

from .config import database_url


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


def get_db() -> Iterator[Session]:
    with Session(engine_for(database_url()), expire_on_commit=False) as session:
        yield session


Database = Annotated[Session, Depends(get_db)]
