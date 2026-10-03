import sqlite3
import tempfile
import unittest
from pathlib import Path


class DatabaseConnectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "database" / "test.db"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_connection_enables_required_pragmas_and_row_factory(self):
        from app.database import Database

        database = Database(self.path)
        with database.connection() as connection:
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
            connection.execute("CREATE TABLE sample (id INTEGER, name TEXT)")
            connection.execute("INSERT INTO sample VALUES (?, ?)", (1, "one"))
            row = connection.execute("SELECT * FROM sample").fetchone()

        self.assertEqual(1, foreign_keys)
        self.assertEqual(5000, busy_timeout)
        self.assertEqual("wal", journal_mode.lower())
        self.assertIsInstance(row, sqlite3.Row)
        self.assertEqual("one", row["name"])
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def test_transaction_rolls_back_all_writes_on_error(self):
        from app.database import Database

        database = Database(self.path)
        with database.connection() as connection:
            connection.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY)")
            connection.commit()

        with self.assertRaises(RuntimeError):
            with database.transaction() as connection:
                connection.execute("INSERT INTO sample VALUES (1)")
                raise RuntimeError("stop")

        with database.connection() as connection:
            count = connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
        self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main()
