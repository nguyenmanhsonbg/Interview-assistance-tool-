-- @requires_foreign_keys_off

DROP INDEX IF EXISTS uq_case_current_ai_result;
DROP INDEX IF EXISTS uq_case_current_question_variant_result;
DROP INDEX IF EXISTS ix_ai_results_attempt;
DROP INDEX IF EXISTS ix_ai_results_snapshot;
DROP INDEX IF EXISTS ix_ai_results_source_question;

CREATE TABLE ai_results_v8 (
    id TEXT PRIMARY KEY,
    ai_task_id TEXT NOT NULL UNIQUE
        REFERENCES ai_tasks(id) ON DELETE CASCADE,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_set_id TEXT
        REFERENCES question_sets(id) ON DELETE RESTRICT,
    result_type TEXT NOT NULL CHECK (
        result_type IN (
            'QUESTION_GENERATION', 'QUESTION_VARIANT', 'ANSWER_EVALUATION',
            'INTERVIEW_BRIEF', 'FOLLOW_UP'
        )
    ),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    supersedes_result_id TEXT REFERENCES ai_results(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL,
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
    ),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    assessment_snapshot_id TEXT
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    source_question_id TEXT
);

INSERT INTO ai_results_v8(
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, source_question_id
)
SELECT
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, source_question_id
FROM ai_results;

DROP TABLE ai_results;
ALTER TABLE ai_results_v8 RENAME TO ai_results;

CREATE UNIQUE INDEX uq_case_result_version
    ON ai_results(interview_case_id, result_type, version_no)
    WHERE result_type <> 'QUESTION_VARIANT';

CREATE UNIQUE INDEX uq_case_question_variant_version
    ON ai_results(
        interview_case_id, result_type, question_set_id, source_question_id, version_no
    )
    WHERE result_type = 'QUESTION_VARIANT';

CREATE UNIQUE INDEX uq_case_current_ai_result
    ON ai_results(interview_case_id, result_type)
    WHERE is_current = 1 AND result_type <> 'QUESTION_VARIANT';

CREATE UNIQUE INDEX uq_case_current_question_variant_result
    ON ai_results(interview_case_id, result_type, question_set_id, source_question_id)
    WHERE is_current = 1 AND result_type = 'QUESTION_VARIANT';

CREATE INDEX ix_ai_results_attempt
    ON ai_results(assessment_attempt_id, result_type);
CREATE INDEX ix_ai_results_snapshot
    ON ai_results(assessment_snapshot_id, result_type);
CREATE INDEX ix_ai_results_source_question
    ON ai_results(interview_case_id, question_set_id, source_question_id, result_type);
