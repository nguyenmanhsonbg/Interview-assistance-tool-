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
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], runner.apply_all())
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

        self.assertEqual(22, len(tables))
        self.assertIn("interview_briefs", tables)
        self.assertEqual(3, len(triggers))
        self.assertEqual("9", settings["assessment.default_question_count"])
        self.assertEqual("30", settings["assessment.max_question_count"])
        self.assertEqual("MANUAL_ONLY", settings["retention.mode"])
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [row[0] for row in versions])

    def test_jd_level_migration_preserves_jobs_and_extends_ai_contract(self):
        from app.migrations import MigrationRunner

        migration_copy = self.root / "migrations"
        migration_copy.mkdir()
        for version in range(1, 10):
            source = next(self.migrations.glob(f"{version:03d}_*.sql"))
            shutil.copy2(source, migration_copy / source.name)

        runner = MigrationRunner(self.database, migration_copy)
        self.assertEqual(list(range(1, 10)), runner.apply_all())
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

        shutil.copy2(
            self.migrations / "010_jd_level_provisioning.sql",
            migration_copy / "010_jd_level_provisioning.sql",
        )
        self.assertEqual([10], runner.apply_all())

        with self.database.transaction() as connection:
            job = connection.execute(
                "SELECT target_level, target_level_status, target_level_source, target_level_confidence FROM jobs WHERE id='j'"
            ).fetchone()
            connection.execute(
                """INSERT INTO ai_tasks(
                    id, interview_case_id, task_type, idempotency_key, input_fingerprint
                ) VALUES ('level-task', 'case', 'EXTRACT_JOB_LEVEL', 'level-idem', ?)""",
                ("a" * 64,),
            )
            connection.execute(
                """INSERT INTO ai_results(
                    id, ai_task_id, interview_case_id, result_type, payload_json
                ) VALUES ('level-result', 'level-task', 'case', 'JOB_LEVEL_EXTRACTION', '{}')"""
            )
        self.assertEqual(("L1", "READY", "LEGACY", None), tuple(job))

        with self.database.connection() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO jobs(
                        id, position_title, target_level_status
                    ) VALUES ('invalid-status', 'Role', 'UNKNOWN')"""
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO jobs(
                        id, position_title, target_level_status, target_level_source
                    ) VALUES ('invalid-source', 'Role', 'PENDING', 'UNKNOWN')"""
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    """INSERT INTO jobs(
                        id, position_title, target_level_status, target_level_confidence
                    ) VALUES ('invalid-confidence', 'Role', 'PENDING', 2.0)"""
                )

    def test_question_addition_migration_adds_scoped_ai_contract_and_proposals(self):
        from app.migrations import MigrationRunner

        runner = MigrationRunner(self.database, self.migrations)
        self.assertEqual([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], runner.apply_all())
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
            connection.execute(
                """INSERT INTO ai_tasks(
                    id, interview_case_id, task_type, idempotency_key,
                    input_fingerprint, target_question_category
                ) VALUES ('task', 'case', 'GENERATE_QUESTION_ADDITION', 'idem', ?, 'APPLICATION')""",
                ("a" * 64,),
            )
            connection.execute(
                """INSERT INTO ai_results(
                    id, ai_task_id, interview_case_id, question_set_id,
                    target_question_category, result_type, payload_json
                ) VALUES ('result', 'task', 'case', 'set', 'APPLICATION',
                    'QUESTION_ADDITION', '{}')"""
            )
            connection.execute(
                """INSERT INTO question_addition_proposals(
                    id, ai_result_id, interview_case_id, question_set_id,
                    target_category, mode, source_fingerprint, status
                ) VALUES ('proposal', 'result', 'case', 'set', 'APPLICATION',
                    'AUTO_GROUP', ?, 'PROPOSED')""",
                ("b" * 64,),
            )

        self.assertEqual([], runner.apply_all())
        with self.database.connection() as connection:
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_tasks)")
            }
            result_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_results)")
            }
            proposal = connection.execute(
                "SELECT target_category, status FROM question_addition_proposals WHERE id='proposal'"
            ).fetchone()
        self.assertIn("target_question_category", task_columns)
        self.assertIn("target_question_category", result_columns)
        self.assertEqual(("APPLICATION", "PROPOSED"), tuple(proposal))

        with self.database.connection() as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(assessment_snapshots)")
            }
            self.assertTrue({
                "assessment_input_source",
                "source_file_sha256",
                "package_id",
            }.issubset(columns))

    def test_question_variant_migration_extends_ai_contract_and_preserves_rows(self):
        from app.migrations import MigrationRunner

        migration_copy = self.root / "migrations"
        migration_copy.mkdir()
        for version in range(1, 7):
            source = next(self.migrations.glob(f"{version:03d}_*.sql"))
            shutil.copy2(source, migration_copy / source.name)

        runner = MigrationRunner(self.database, migration_copy)
        self.assertEqual([1, 2, 3, 4, 5, 6], runner.apply_all())
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
            connection.execute(
                """INSERT INTO questions(
                    id, question_set_id, display_order, question_text,
                    competency_key, source_kind, purpose, expected_evidence
                ) VALUES ('q1', 'set', 1, 'Question', 'skill', 'MANUAL', 'purpose', 'evidence')"""
            )
            connection.execute(
                """INSERT INTO questions(
                    id, question_set_id, display_order, question_text,
                    competency_key, source_kind, purpose, expected_evidence
                ) VALUES ('q2', 'set', 2, 'Question 2', 'skill', 'MANUAL', 'purpose', 'evidence')"""
            )
            connection.execute(
                """INSERT INTO ai_tasks(
                    id, interview_case_id, task_type, idempotency_key,
                    input_fingerprint
                ) VALUES ('task', 'case', 'GENERATE_QUESTIONS', 'idem', ?)""",
                ("a" * 64,),
            )
            connection.execute(
                """INSERT INTO ai_results(
                    id, ai_task_id, interview_case_id, result_type, payload_json
                ) VALUES ('result', 'task', 'case', 'QUESTION_GENERATION', '{}')"""
            )

        shutil.copy2(
            self.migrations / "007_question_variant_generation.sql",
            migration_copy / "007_question_variant_generation.sql",
        )
        self.assertEqual([7], runner.apply_all())

        with self.database.connection() as connection:
            task_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_tasks)")
            }
            result_columns = {
                row[1] for row in connection.execute("PRAGMA table_info(ai_results)")
            }
            proposal_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(question_variant_proposals)"
                )
            }
            indexes = {
                row[1]
                for row in connection.execute(
                    "PRAGMA index_list(question_variant_proposals)"
                )
            }
            old_task = connection.execute(
                "SELECT task_type, source_question_id FROM ai_tasks WHERE id = 'task'"
            ).fetchone()
            old_result = connection.execute(
                "SELECT result_type, source_question_id FROM ai_results WHERE id = 'result'"
            ).fetchone()

            self.assertIn("source_question_id", task_columns)
            self.assertIn("source_question_id", result_columns)
            self.assertTrue({
                "id",
                "ai_result_id",
                "interview_case_id",
                "question_set_id",
                "source_question_id",
                "mode",
                "source_fingerprint",
                "status",
                "created_at",
                "updated_at",
                "applied_at",
                "discarded_at",
            }.issubset(proposal_columns))
            self.assertTrue(any("source" in name or "status" in name for name in indexes))
            self.assertEqual(("GENERATE_QUESTIONS", None), tuple(old_task))
            self.assertEqual(("QUESTION_GENERATION", None), tuple(old_result))

            connection.execute(
                """INSERT INTO ai_tasks(
                    id, interview_case_id, task_type, idempotency_key,
                    input_fingerprint, source_question_id
                ) VALUES ('variant-task', 'case', 'GENERATE_QUESTION_VARIANT', 'variant-idem', ?, 'q1')""",
                ("b" * 64,),
            )
            connection.execute(
                """INSERT INTO ai_results(
                    id, ai_task_id, interview_case_id, question_set_id,
                    source_question_id, result_type, payload_json
                ) VALUES ('variant-result', 'variant-task', 'case', 'set', 'q1', 'QUESTION_VARIANT', '{}')"""
            )
            connection.execute(
                """INSERT INTO question_variant_proposals(
                    id, ai_result_id, interview_case_id, question_set_id,
                    source_question_id, mode, source_fingerprint, status
                ) VALUES ('proposal', 'variant-result', 'case', 'set', 'q1',
                    'SAME_GROUP', ?, 'PROPOSED')""",
                ("c" * 64,),
            )

        self.assertEqual([], runner.apply_all())

        shutil.copy2(
            self.migrations / "008_scope_question_variant_versions.sql",
            migration_copy / "008_scope_question_variant_versions.sql",
        )
        self.assertEqual([8], runner.apply_all())

        with self.database.transaction() as connection:
            connection.execute(
                """INSERT INTO ai_tasks(
                    id, interview_case_id, task_type, idempotency_key,
                    input_fingerprint, source_question_id
                ) VALUES ('variant-task-2', 'case', 'GENERATE_QUESTION_VARIANT', 'variant-idem-2', ?, 'q2')""",
                ("d" * 64,),
            )
            connection.execute(
                """INSERT INTO ai_results(
                    id, ai_task_id, interview_case_id, question_set_id,
                    source_question_id, result_type, payload_json
                ) VALUES ('variant-result-2', 'variant-task-2', 'case', 'set', 'q2',
                    'QUESTION_VARIANT', '{}')"""
            )

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
                    ) VALUES ('q31', 'set', 31, 'Thirty-first', 'skill', 'MANUAL', 'purpose', 'evidence')"""
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
