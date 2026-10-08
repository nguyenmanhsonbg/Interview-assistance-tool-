-- @requires_foreign_keys_off

DROP INDEX IF EXISTS uq_case_one_current_ai_result;
DROP INDEX IF EXISTS ix_ai_tasks_status_created;
DROP INDEX IF EXISTS ix_ai_tasks_case;
DROP INDEX IF EXISTS ix_ai_results_attempt;
DROP INDEX IF EXISTS ix_ai_tasks_snapshot;
DROP INDEX IF EXISTS ix_ai_results_snapshot;

CREATE TABLE ai_tasks_v7 (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    assessment_snapshot_id TEXT
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK (
        task_type IN (
            'GENERATE_QUESTIONS', 'GENERATE_QUESTION_VARIANT',
            'EVALUATE_ASSESSMENT', 'GENERATE_BRIEF', 'SUGGEST_FOLLOW_UP'
        )
    ),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PENDING_RETRY')
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint) = 64),
    input_manifest_json TEXT NOT NULL DEFAULT '{}',
    redaction_policy TEXT NOT NULL DEFAULT 'SANITIZED_TEXT_ONLY'
        CHECK (redaction_policy = 'SANITIZED_TEXT_ONLY'),
    provider TEXT,
    model TEXT,
    prompt_key TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retry INTEGER NOT NULL DEFAULT 1 CHECK (max_retry >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT,
    phase TEXT,
    source_question_id TEXT
);

INSERT INTO ai_tasks_v7(
    id, interview_case_id, assessment_attempt_id, assessment_snapshot_id,
    task_type, status, idempotency_key, input_fingerprint,
    input_manifest_json, redaction_policy, provider, model, prompt_key,
    prompt_version, schema_version, retry_count, max_retry, error_code,
    error_message, created_at, started_at, finished_at, phase, source_question_id
)
SELECT
    id, interview_case_id, assessment_attempt_id, assessment_snapshot_id,
    task_type, status, idempotency_key, input_fingerprint,
    input_manifest_json, redaction_policy, provider, model, prompt_key,
    prompt_version, schema_version, retry_count, max_retry, error_code,
    error_message, created_at, started_at, finished_at, phase, NULL
FROM ai_tasks;

CREATE TABLE ai_results_v7 (
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
    source_question_id TEXT,
    UNIQUE (interview_case_id, result_type, version_no)
);

INSERT INTO ai_results_v7(
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, source_question_id
)
SELECT
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, NULL
FROM ai_results;

DROP TABLE ai_results;
DROP TABLE ai_tasks;
ALTER TABLE ai_tasks_v7 RENAME TO ai_tasks;
ALTER TABLE ai_results_v7 RENAME TO ai_results;

CREATE UNIQUE INDEX uq_case_current_ai_result
    ON ai_results(interview_case_id, result_type)
    WHERE is_current = 1 AND result_type <> 'QUESTION_VARIANT';

CREATE UNIQUE INDEX uq_case_current_question_variant_result
    ON ai_results(interview_case_id, result_type, question_set_id, source_question_id)
    WHERE is_current = 1 AND result_type = 'QUESTION_VARIANT';

CREATE INDEX ix_ai_tasks_status_created
    ON ai_tasks(status, created_at);
CREATE INDEX ix_ai_tasks_case ON ai_tasks(interview_case_id);
CREATE INDEX ix_ai_tasks_snapshot
    ON ai_tasks(assessment_snapshot_id);
CREATE INDEX ix_ai_tasks_source_question
    ON ai_tasks(interview_case_id, source_question_id, task_type);
CREATE INDEX ix_ai_results_attempt
    ON ai_results(assessment_attempt_id, result_type);
CREATE INDEX ix_ai_results_snapshot
    ON ai_results(assessment_snapshot_id, result_type);
CREATE INDEX ix_ai_results_source_question
    ON ai_results(interview_case_id, question_set_id, source_question_id, result_type);

CREATE TABLE question_variant_proposals (
    id TEXT PRIMARY KEY,
    ai_result_id TEXT NOT NULL UNIQUE
        REFERENCES ai_results(id) ON DELETE RESTRICT,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
    source_question_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('USER_PROMPT', 'SAME_GROUP')),
    source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint) = 64),
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'APPLIED', 'DISCARDED')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    applied_at TEXT,
    discarded_at TEXT
);

CREATE INDEX ix_question_variant_proposals_case_set
    ON question_variant_proposals(interview_case_id, question_set_id);
CREATE INDEX ix_question_variant_proposals_source_status
    ON question_variant_proposals(source_question_id, status);
CREATE INDEX ix_question_variant_proposals_result
    ON question_variant_proposals(ai_result_id);
