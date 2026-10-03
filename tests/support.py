import tempfile
from pathlib import Path


class MigratedDatabaseFixture:
    def setUp(self):
        super().setUp()
        from app.database import Database
        from app.migrations import MigrationRunner

        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_root = Path(self.temp_dir.name)
        self.database = Database(self.data_root / "database" / "test.db")
        migrations = Path(__file__).resolve().parents[1] / "migrations"
        MigrationRunner(self.database, migrations).apply_all()

    def tearDown(self):
        self.temp_dir.cleanup()
        super().tearDown()
