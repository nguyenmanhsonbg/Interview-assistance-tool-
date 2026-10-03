import tempfile
import unittest
from pathlib import Path


class RepositoryBaseTests(unittest.TestCase):
    def setUp(self):
        from app.database import Database

        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp_dir.name) / "repo.db")
        with self.database.connection() as connection:
            connection.execute("CREATE TABLE items(id TEXT PRIMARY KEY, value TEXT)")
            connection.commit()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parameter_binding_treats_operator_text_as_data(self):
        from app.repositories.base import RepositoryBase

        repository = RepositoryBase(self.database)
        hostile = "x' OR 1=1 --"
        repository.execute("INSERT INTO items(id, value) VALUES (?, ?)", ("1", hostile))

        row = repository.query_one("SELECT value FROM items WHERE id = ?", ("1",))
        missing = repository.query_one(
            "SELECT value FROM items WHERE value = ?", ("not-present' OR 1=1 --",)
        )

        self.assertEqual(hostile, row["value"])
        self.assertIsNone(missing)

    def test_repository_transaction_rolls_back_as_one_unit(self):
        from app.repositories.base import RepositoryBase

        repository = RepositoryBase(self.database)
        with self.assertRaises(ValueError):
            with repository.transaction() as connection:
                connection.execute("INSERT INTO items VALUES (?, ?)", ("1", "one"))
                raise ValueError("cancel")

        self.assertEqual([], repository.query_all("SELECT * FROM items"))


if __name__ == "__main__":
    unittest.main()
