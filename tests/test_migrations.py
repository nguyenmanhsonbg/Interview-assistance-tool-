import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path


class MigrationTests(unittest.TestCase):
    def setUp(self):
        from app.database import Database

        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.database = Database(self.root / "clawcv.db")
        self.migrations = Path(__file__).resolve().parents[1] / "migrations"

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_initial_migration_creates_contract_and_seed_once(self):
        from app.migrations import MigrationRunner

        runner = MigrationRunner(self.database, self.migrations)
        self.assertEqual([1, 2, 3], runner.apply_all())
        self.assertEqual([], runner.apply_all())

        with self.database.connection() as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            triggers = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='trigger'"
                )
            }
            settings = dict(
                connection.execute("SELECT key, value_text FROM app_settings")
            )
            versions = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()

        self.assertEqual(20, len(tables))
        self.assertIn("interview_briefs", tables)
        self.assertEqual(3, len(triggers))
        self.assertEqual("9", settings["assessment.default_question_count"])
        self.assertEqual("9", settings["assessment.max_question_count"])
        self.assertEqual("MANUAL_ONLY", settings["retention.mode"])
        self.assertEqual([1, 2, 3], [row[0] for row in versions])

    def test_question_and_answer_lock_triggers_enforce_immutable_snapshots(self):
        from app.migrations import MigrationRunner

        MigrationRunner(self.database, self.migrations).apply_all()
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT INTO jobs(id, position_title, target_level) VALUES ('j', 'Role', 'L1')"
            )
            connection.execute(
                "INSERT INTO candidates(id, candidate_code, full_name) VALUES ('c', 'C1', 'Candidate')"
            )
            connection.execute(
                "INSERT INTO interview_cases(id, candidate_id, job_id) VALUES ('case', 'c', 'j')"
            )
            connection.execute(
                "INSERT INTO question_sets(id, interview_case_id) VALUES ('set', 'case')"
            )
            for number in range(1, 10):
                connection.execute(
                    """INSERT INTO questions(
                        id, question_set_id, display_order, question_text,
                        competency_key, source_kind, purpose, expected_evidence
                    ) VALUES (?, 'set', ?, ?, 'skill', 'MANUAL', 'purpose', 'evidence')""",
                    (f"q{number}", number, f"Question {number}"),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO questions(
                        id, question_set_id, display_order, question_text,
                        competency_key, source_kind, purpose, expected_evidence
                    ) VALUES ('q10', 'set', 10, 'Tenth', 'skill', 'MANUAL', 'purpose', 'evidence')"""
                )
            connection.execute(
                """INSERT INTO assessment_attempts(
                    id, interview_case_id, question_set_id, status
                ) VALUES ('attempt', 'case', 'set', 'ASSESSMENT_IN_PROGRESS')"""
            )
            connection.execute(
                """INSERT INTO answers(id, assessment_attempt_id, question_id)
                    VALUES ('answer', 'attempt', 'q1')"""
            )
            connection.execute(
                "UPDATE assessment_attempts SET status='ASSESSMENT_SUBMITTED' WHERE id='attempt'"
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "UPDATE answers SET answer_text='changed', is_answered=1 WHERE id='answer'"
                )

    def test_failed_later_migration_rolls_back_its_partial_schema(self):
        from app.migrations import MigrationError, MigrationRunner

        migration_copy = self.root / "migrations"
        migration_copy.mkdir()
        shutil.copy2(self.migrations / "001_initial.sql", migration_copy)
        (migration_copy / "002_broken.sql").write_text(
            "CREATE TABLE partial_table(id INTEGER);\nTHIS IS INVALID SQL;",
            encoding="utf-8",
        )

        with self.assertRaises(MigrationError):
            MigrationRunner(self.database, migration_copy).apply_all()

        with self.database.connection() as connection:
            partial = connection.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE name='partial_table'"
            ).fetchone()[0]
            versions = connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        self.assertEqual(0, partial)
        self.assertEqual([1], [row[0] for row in versions])


if __name__ == "__main__":
    unittest.main()
