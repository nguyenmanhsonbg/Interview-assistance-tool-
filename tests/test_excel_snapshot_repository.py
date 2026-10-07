import hashlib
import json
import unittest

from tests.support import MigratedDatabaseFixture


def _question(number: int, text: str | None = None) -> dict:
    return {
        "questionId": f"q{number}",
        "displayOrder": number,
        "questionText": text or f"Question {number}",
        "competencyKey": "backend",
        "sourceKind": "SITUATIONAL" if number <= 4 else "CV_VERIFICATION",
        "questionCategory": "FOUNDATION" if number <= 3 else "APPLICATION" if number <= 4 else "DEEP_DIVE",
        "purpose": "Validate evidence",
        "nextStepObjective": "Use the answer evidence in the evaluation rubric.",
        "questionType": "LONG_TEXT",
        "difficulty": "MEDIUM",
        "expectedEvidence": "Context and outcome",
        "rubric": {f"score{score}": f"Level {score}" for score in range(5)},
        "isRequired": True,
        "estimatedSeconds": 120,
    }


class ExcelSnapshotRepositoryTests(MigratedDatabaseFixture, unittest.TestCase):
    def test_migration_adds_refined_flow_and_snapshot_tables(self):
        from app.migrations import MigrationRunner

        with self.database.connection() as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(interview_cases)")
            }
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            versions = [
                row[0]
                for row in connection.execute(
                    "SELECT version FROM schema_migrations ORDER BY version"
                )
            ]
        self.assertIn("refined_flow_status", columns)
        self.assertTrue({
            "assessment_snapshots",
            "assessment_snapshot_questions",
            "assessment_snapshot_answers",
        }.issubset(tables))
        self.assertEqual([1, 2, 3, 4], versions)

    def test_snapshot_round_trip_preserves_edited_questions_and_answer_hashes(self):
        from app.repositories.assessment_snapshots import AssessmentSnapshotRepository

        repository = AssessmentSnapshotRepository(self.database)
        answers = [
            {
                "answerId": "a1",
                "questionId": "q1",
                "answerText": "A concrete answer",
                "isAnswered": True,
                "saveRevision": 1,
                "contentHash": hashlib.sha256(b"A concrete answer").hexdigest(),
            },
            {
                "answerId": "a2",
                "questionId": "q2",
                "answerText": "",
                "isAnswered": False,
                "saveRevision": 0,
                "contentHash": hashlib.sha256(b"").hexdigest(),
            },
        ]
        questions = [_question(number) for number in range(1, 6)]
        questions[0]["questionText"] = "Edited question from Excel"
        document_manifest = [{
            "id": "jd-1", "document_type": "JD", "version_no": 1,
            "content_sha256": "a" * 64,
        }]

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
            for number in range(1, 6):
                connection.execute(
                    """INSERT INTO questions(
                        id, question_set_id, display_order, question_text,
                        competency_key, source_kind, purpose, question_type,
                        difficulty, expected_evidence, rubric_json,
                        is_required, estimated_seconds
                    ) VALUES (?, 'set', ?, ?, 'backend', 'AI', 'Validate evidence',
                              'LONG_TEXT', 'MEDIUM', 'Context and outcome', ?, 1, 120)""",
                    (f"q{number}", number, f"Question {number}", json.dumps(questions[number - 1]["rubric"])),
                )
            snapshot = repository.create_imported_snapshot(
                connection,
                case_id="case",
                question_set_id="set",
                source_kind="HTML_IMPORT",
                source_file_sha256="b" * 64,
                package_id="package-1",
                normalized_fingerprint="c" * 64,
                idempotency_key_hash="d" * 64,
                document_manifest=document_manifest,
                questions=questions,
                answers=answers,
            )

        loaded = repository.get(snapshot["id"])
        self.assertEqual(1, loaded["versionNo"])
        self.assertEqual("HTML_IMPORT", loaded["sourceKind"])
        self.assertEqual("package-1", loaded["packageId"])
        self.assertEqual("b" * 64, loaded["sourceFileSha256"])
        self.assertEqual("b" * 64, loaded["workbookSha256"])
        self.assertEqual("Edited question from Excel", loaded["questions"][0]["questionText"])
        self.assertEqual("NOT_ASSESSED", loaded["answers"][1]["assessmentStatus"])
        self.assertEqual(answers[0]["contentHash"], loaded["answers"][0]["contentHash"])
        self.assertEqual(document_manifest, loaded["documentManifest"])

    def test_same_case_and_idempotency_hash_is_findable(self):
        from app.repositories.assessment_snapshots import AssessmentSnapshotRepository

        repository = AssessmentSnapshotRepository(self.database)
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
            for number in range(1, 6):
                connection.execute(
                    """INSERT INTO questions(
                        id, question_set_id, display_order, question_text,
                        competency_key, source_kind, purpose, expected_evidence
                    ) VALUES (?, 'set', ?, ?, 'skill', 'MANUAL', 'purpose', 'evidence')""",
                    (f"q{number}", number, f"Question {number}"),
                )
            created = repository.create_imported_snapshot(
                connection,
                case_id="case",
                question_set_id="set",
                source_kind="EXCEL_IMPORT",
                source_file_sha256="e" * 64,
                package_id=None,
                normalized_fingerprint="f" * 64,
                idempotency_key_hash="1" * 64,
                document_manifest=[],
                questions=[_question(number) for number in range(1, 6)],
                answers=[],
            )

        found = repository.find_by_idempotency("case", "1" * 64)
        self.assertEqual(created["id"], found["id"])
        self.assertEqual(created["id"], repository.current_for_case("case")["id"])


if __name__ == "__main__":
    unittest.main()
