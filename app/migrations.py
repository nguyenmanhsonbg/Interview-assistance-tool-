from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from app.database import Database


class MigrationError(RuntimeError):
    pass


class MigrationRunner:
    def __init__(self, database: Database, directory: Path) -> None:
        self.database = database
        self.directory = Path(directory)

    def apply_all(self) -> list[int]:
        applied = self._applied_versions()
        completed: list[int] = []
        for version, path in self._migration_files():
            if version in applied:
                continue
            try:
                if _requires_foreign_keys_off(path):
                    self._apply_with_foreign_keys_off(version, path)
                else:
                    self._apply_in_transaction(version, path)
            except (OSError, sqlite3.Error) as error:
                raise MigrationError(
                    f"Migration {version:03d} failed; startup cannot continue"
                ) from error
            completed.append(version)
            applied.add(version)
        return completed

    def _apply_in_transaction(self, version: int, path: Path) -> None:
        with self.database.transaction() as connection:
            self._execute_migration(connection, version, path)

    def _apply_with_foreign_keys_off(self, version: int, path: Path) -> None:
        with self.database.connection() as connection:
            connection.execute("PRAGMA foreign_keys = OFF")
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._execute_migration(connection, version, path)
                violation = connection.execute(
                    "PRAGMA foreign_key_check"
                ).fetchone()
                if violation is not None:
                    raise sqlite3.IntegrityError(
                        "foreign key check failed during migration "
                        f"{version:03d}: {tuple(violation)}"
                    )
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _execute_migration(
        self, connection: sqlite3.Connection, version: int, path: Path
    ) -> None:
        for statement in _split_sql(path.read_text(encoding="utf-8")):
            connection.execute(statement)
        recorded = connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
        ).fetchone()
        if recorded is None:
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
            )

    def _applied_versions(self) -> set[int]:
        if not self.database.path.exists():
            return set()
        try:
            with self.database.connection() as connection:
                rows = connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {int(row[0]) for row in rows}

    def _migration_files(self) -> list[tuple[int, Path]]:
        migrations: list[tuple[int, Path]] = []
        for path in self.directory.glob("*.sql"):
            match = re.fullmatch(r"(\d+)_[-_a-zA-Z0-9]+\.sql", path.name)
            if match:
                migrations.append((int(match.group(1)), path))
        migrations.sort(key=lambda item: item[0])
        versions = [version for version, _ in migrations]
        if len(versions) != len(set(versions)):
            raise MigrationError("Duplicate migration version")
        return migrations


def _split_sql(script: str) -> list[str]:
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise MigrationError("Incomplete SQL statement")
    return statements


def _requires_foreign_keys_off(path: Path) -> bool:
    return "-- @requires_foreign_keys_off" in path.read_text(encoding="utf-8")
