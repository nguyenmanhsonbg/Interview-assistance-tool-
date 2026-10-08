-- @requires_foreign_keys_off

DROP INDEX IF EXISTS uq_case_result_version;
DROP INDEX IF EXISTS uq_case_question_variant_version;
DROP INDEX IF EXISTS uq_case_current_ai_result;
DROP INDEX IF EXISTS uq_case_current_question_variant_result;
DROP INDEX IF EXISTS ix_ai_tasks_status_created;
DROP INDEX IF EXISTS ix_ai_tasks_case;
DROP INDEX IF EXISTS ix_ai_tasks_snapshot;
DROP INDEX IF EXISTS ix_ai_tasks_source_question;
DROP INDEX IF EXISTS ix_ai_results_attempt;
DROP INDEX IF EXISTS ix_ai_results_snapshot;
DROP INDEX IF EXISTS ix_ai_results_source_question;
DROP INDEX IF EXISTS ix_questions_set_order;
DROP INDEX IF EXISTS ix_questions_competency;
DROP INDEX IF EXISTS ix_assessment_snapshot_questions_order;

CREATE TABLE questions_v9 (
    id TEXT PRIMARY KEY,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 30),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    competency_key TEXT NOT NULL CHECK (length(trim(competency_key)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'STANDARDIZED', 'SITUATIONAL', 'CV_VERIFICATION',
            'GAP_CONFLICT', 'QUESTION_BANK', 'MANUAL', 'AI'
        )
    ),
    question_category TEXT NOT NULL DEFAULT 'APPLICATION' CHECK (
        question_category IN ('FOUNDATION', 'APPLICATION', 'DEEP_DIVE')
    ),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    next_step_objective TEXT NOT NULL
        DEFAULT 'Assess evidence against the question rubric.'
        CHECK (length(trim(next_step_objective)) > 0),
    question_type TEXT NOT NULL DEFAULT 'SHORT_TEXT' CHECK (
        question_type IN ('SHORT_TEXT', 'LONG_TEXT', 'SCENARIO')
    ),
    difficulty TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (
        difficulty IN ('EASY', 'MEDIUM', 'HARD')
    ),
    expected_evidence TEXT NOT NULL CHECK (length(trim(expected_evidence)) > 0),
    rubric_json TEXT NOT NULL DEFAULT '{}',
    is_required INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1)),
    estimated_seconds INTEGER CHECK (
        estimated_seconds IS NULL OR estimated_seconds > 0
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (question_set_id, display_order)
);

INSERT INTO questions_v9(
    id, question_set_id, display_order, question_text, competency_key,
    source_kind, question_category, purpose, next_step_objective,
    question_type, difficulty, expected_evidence, rubric_json,
    is_required, estimated_seconds, created_at
)
SELECT
    id, question_set_id, display_order, question_text, competency_key,
    source_kind, question_category, purpose, next_step_objective,
    question_type, difficulty, expected_evidence, rubric_json,
    is_required, estimated_seconds, created_at
FROM questions;

DROP TABLE questions;
ALTER TABLE questions_v9 RENAME TO questions;

CREATE TABLE assessment_snapshot_questions_v9 (
    assessment_snapshot_id TEXT NOT NULL
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 30),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    competency_key TEXT NOT NULL CHECK (length(trim(competency_key)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'STANDARDIZED', 'SITUATIONAL', 'CV_VERIFICATION',
            'GAP_CONFLICT', 'QUESTION_BANK', 'MANUAL', 'AI'
        )
    ),
    question_category TEXT NOT NULL DEFAULT 'APPLICATION' CHECK (
        question_category IN ('FOUNDATION', 'APPLICATION', 'DEEP_DIVE')
    ),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    next_step_objective TEXT NOT NULL
        DEFAULT 'Assess evidence against the question rubric.'
        CHECK (length(trim(next_step_objective)) > 0),
    question_type TEXT NOT NULL CHECK (
        question_type IN ('SHORT_TEXT', 'LONG_TEXT', 'SCENARIO')
    ),
    difficulty TEXT NOT NULL CHECK (difficulty IN ('EASY', 'MEDIUM', 'HARD')),
    expected_evidence TEXT NOT NULL CHECK (length(trim(expected_evidence)) > 0),
    rubric_json TEXT NOT NULL,
    is_required INTEGER NOT NULL CHECK (is_required IN (0, 1)),
    estimated_seconds INTEGER NOT NULL CHECK (estimated_seconds > 0),
    PRIMARY KEY (assessment_snapshot_id, question_id),
    UNIQUE (assessment_snapshot_id, display_order)
);

INSERT INTO assessment_snapshot_questions_v9(
    assessment_snapshot_id, question_id, display_order, question_text,
    competency_key, source_kind, question_category, purpose,
    next_step_objective, question_type, difficulty, expected_evidence,
    rubric_json, is_required, estimated_seconds
)
SELECT
    assessment_snapshot_id, question_id, display_order, question_text,
    competency_key, source_kind, question_category, purpose,
    next_step_objective, question_type, difficulty, expected_evidence,
    rubric_json, is_required, estimated_seconds
FROM assessment_snapshot_questions;

DROP TABLE assessment_snapshot_questions;
ALTER TABLE assessment_snapshot_questions_v9 RENAME TO assessment_snapshot_questions;

CREATE INDEX ix_questions_set_order ON questions(question_set_id, display_order);
CREATE INDEX ix_questions_competency ON questions(competency_key);
CREATE INDEX ix_assessment_snapshot_questions_order
    ON assessment_snapshot_questions(assessment_snapshot_id, display_order);

CREATE TRIGGER trg_questions_max_thirty
AFTER INSERT ON questions
WHEN (
    SELECT COUNT(*) FROM questions
    WHERE question_set_id = NEW.question_set_id
) > 30
BEGIN
    SELECT RAISE(ABORT, 'question_set_maximum_is_thirty');
END;

CREATE TABLE ai_tasks_v9 (
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
            'GENERATE_QUESTION_ADDITION', 'EVALUATE_ASSESSMENT',
            'GENERATE_BRIEF', 'SUGGEST_FOLLOW_UP'
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
    source_question_id TEXT,
    target_question_category TEXT
);

INSERT INTO ai_tasks_v9(
    id, interview_case_id, assessment_attempt_id, assessment_snapshot_id,
    task_type, status, idempotency_key, input_fingerprint,
    input_manifest_json, redaction_policy, provider, model, prompt_key,
    prompt_version, schema_version, retry_count, max_retry, error_code,
    error_message, created_at, started_at, finished_at, phase, source_question_id,
    target_question_category
)
SELECT
    id, interview_case_id, assessment_attempt_id, assessment_snapshot_id,
    task_type, status, idempotency_key, input_fingerprint,
    input_manifest_json, redaction_policy, provider, model, prompt_key,
    prompt_version, schema_version, retry_count, max_retry, error_code,
    error_message, created_at, started_at, finished_at, phase, source_question_id,
    NULL
FROM ai_tasks;

CREATE TABLE ai_results_v9 (
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
            'QUESTION_GENERATION', 'QUESTION_VARIANT', 'QUESTION_ADDITION',
            'ANSWER_EVALUATION', 'INTERVIEW_BRIEF', 'FOLLOW_UP'
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
    target_question_category TEXT
);

INSERT INTO ai_results_v9(
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, source_question_id,
    target_question_category
)
SELECT
    id, ai_task_id, interview_case_id, assessment_attempt_id, question_set_id,
    result_type, version_no, supersedes_result_id, payload_json, confidence,
    is_current, created_at, assessment_snapshot_id, source_question_id,
    NULL
FROM ai_results;

DROP TABLE ai_results;
DROP TABLE ai_tasks;
ALTER TABLE ai_tasks_v9 RENAME TO ai_tasks;
ALTER TABLE ai_results_v9 RENAME TO ai_results;

CREATE UNIQUE INDEX uq_case_result_version
    ON ai_results(interview_case_id, result_type, version_no)
    WHERE result_type NOT IN ('QUESTION_VARIANT', 'QUESTION_ADDITION');
CREATE UNIQUE INDEX uq_case_question_variant_version
    ON ai_results(
        interview_case_id, result_type, question_set_id, source_question_id, version_no
    )
    WHERE result_type = 'QUESTION_VARIANT';
CREATE UNIQUE INDEX uq_case_question_addition_version
    ON ai_results(
        interview_case_id, result_type, question_set_id,
        target_question_category, version_no
    )
    WHERE result_type = 'QUESTION_ADDITION';

CREATE UNIQUE INDEX uq_case_current_ai_result
    ON ai_results(interview_case_id, result_type)
    WHERE is_current = 1
      AND result_type NOT IN ('QUESTION_VARIANT', 'QUESTION_ADDITION');
CREATE UNIQUE INDEX uq_case_current_question_variant_result
    ON ai_results(interview_case_id, result_type, question_set_id, source_question_id)
    WHERE is_current = 1 AND result_type = 'QUESTION_VARIANT';
CREATE UNIQUE INDEX uq_case_current_question_addition_result
    ON ai_results(
        interview_case_id, result_type, question_set_id, target_question_category
    )
    WHERE is_current = 1 AND result_type = 'QUESTION_ADDITION';

CREATE INDEX ix_ai_tasks_status_created ON ai_tasks(status, created_at);
CREATE INDEX ix_ai_tasks_case ON ai_tasks(interview_case_id);
CREATE INDEX ix_ai_tasks_snapshot ON ai_tasks(assessment_snapshot_id);
CREATE INDEX ix_ai_tasks_source_question
    ON ai_tasks(interview_case_id, source_question_id, task_type);
CREATE INDEX ix_ai_tasks_target_category
    ON ai_tasks(interview_case_id, target_question_category, task_type);
CREATE INDEX ix_ai_results_attempt ON ai_results(assessment_attempt_id, result_type);
CREATE INDEX ix_ai_results_snapshot ON ai_results(assessment_snapshot_id, result_type);
CREATE INDEX ix_ai_results_source_question
    ON ai_results(interview_case_id, question_set_id, source_question_id, result_type);
CREATE INDEX ix_ai_results_target_category
    ON ai_results(
        interview_case_id, question_set_id, target_question_category, result_type
    );

CREATE TABLE question_addition_proposals (
    id TEXT PRIMARY KEY,
    ai_result_id TEXT NOT NULL UNIQUE
        REFERENCES ai_results(id) ON DELETE RESTRICT,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
    target_category TEXT NOT NULL CHECK (
        target_category IN ('FOUNDATION', 'APPLICATION', 'DEEP_DIVE')
    ),
    mode TEXT NOT NULL CHECK (mode IN ('USER_PROMPT', 'AUTO_GROUP')),
    source_fingerprint TEXT NOT NULL CHECK (length(source_fingerprint) = 64),
    status TEXT NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'APPLIED', 'DISCARDED')),
    applied_question_id TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    applied_at TEXT,
    discarded_at TEXT
);

CREATE INDEX ix_question_addition_proposals_case_set
    ON question_addition_proposals(interview_case_id, question_set_id);
CREATE INDEX ix_question_addition_proposals_category_status
    ON question_addition_proposals(target_category, status);
CREATE INDEX ix_question_addition_proposals_result
    ON question_addition_proposals(ai_result_id);

UPDATE app_settings
SET value_text = '30'
WHERE key = 'assessment.max_question_count';
