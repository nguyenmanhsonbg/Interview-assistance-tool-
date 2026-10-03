from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator, Sequence

from app.database import Database


class RepositoryBase:
    def __init__(self, database: Database) -> None:
        self.database = database

    def query_one(
        self, sql: str, parameters: Sequence[Any] = ()
    ) -> sqlite3.Row | None:
        with self.database.connection() as connection:
            return connection.execute(sql, tuple(parameters)).fetchone()

    def query_all(
        self, sql: str, parameters: Sequence[Any] = ()
    ) -> list[sqlite3.Row]:
        with self.database.connection() as connection:
            return list(connection.execute(sql, tuple(parameters)).fetchall())

    def execute(self, sql: str, parameters: Sequence[Any] = ()) -> int:
        with self.database.transaction() as connection:
            cursor = connection.execute(sql, tuple(parameters))
            return cursor.rowcount

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.database.transaction() as connection:
            yield connection
