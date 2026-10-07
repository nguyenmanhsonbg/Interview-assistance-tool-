PRAGMA foreign_keys = ON;

DROP INDEX ix_questions_set_order;
DROP INDEX ix_questions_competency;
DROP INDEX ix_answers_attempt;
DROP INDEX ix_assessment_snapshot_questions_order;
DROP INDEX ix_assessment_snapshot_answers_snapshot;

DROP TRIGGER trg_questions_max_eight;
DROP TRIGGER trg_answers_no_update_after_submit;
DROP TRIGGER trg_answers_no_insert_after_submit;

ALTER TABLE assessment_snapshot_answers
    RENAME TO assessment_snapshot_answers_v2_old;
ALTER TABLE assessment_snapshot_questions
    RENAME TO assessment_snapshot_questions_v2_old;
ALTER TABLE answers
    RENAME TO answers_v2_old;
ALTER TABLE questions
    RENAME TO questions_v2_old;

CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 9),
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

INSERT INTO questions(
    id, question_set_id, display_order, question_text, competency_key,
    source_kind, question_category, purpose, next_step_objective,
    question_type, difficulty, expected_evidence, rubric_json,
    is_required, estimated_seconds, created_at
)
SELECT
    id, question_set_id, display_order, question_text, competency_key,
    source_kind,
    CASE source_kind
        WHEN 'STANDARDIZED' THEN 'FOUNDATION'
        WHEN 'SITUATIONAL' THEN 'APPLICATION'
        WHEN 'CV_VERIFICATION' THEN 'DEEP_DIVE'
        WHEN 'GAP_CONFLICT' THEN 'DEEP_DIVE'
        ELSE 'APPLICATION'
    END,
    purpose, 'Assess evidence against the question rubric.',
    question_type, difficulty, expected_evidence, rubric_json,
    is_required, estimated_seconds, created_at
FROM questions_v2_old;

CREATE TABLE answers (
    id TEXT PRIMARY KEY,
    assessment_attempt_id TEXT NOT NULL
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL
        REFERENCES questions(id) ON DELETE RESTRICT,
    answer_text TEXT NOT NULL DEFAULT '',
    is_answered INTEGER NOT NULL DEFAULT 0 CHECK (is_answered IN (0, 1)),
    save_revision INTEGER NOT NULL DEFAULT 0 CHECK (save_revision >= 0),
    last_saved_at TEXT,
    submitted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assessment_attempt_id, question_id),
    CHECK (
        (is_answered = 0 AND answer_text = '')
        OR (is_answered = 1 AND length(trim(answer_text)) > 0)
    )
);

INSERT INTO answers(
    id, assessment_attempt_id, question_id, answer_text, is_answered,
    save_revision, last_saved_at, submitted_at, created_at, updated_at
)
SELECT
    id, assessment_attempt_id, question_id, answer_text, is_answered,
    save_revision, last_saved_at, submitted_at, created_at, updated_at
FROM answers_v2_old;

CREATE TABLE assessment_snapshot_questions (
    assessment_snapshot_id TEXT NOT NULL
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 9),
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

INSERT INTO assessment_snapshot_questions(
    assessment_snapshot_id, question_id, display_order, question_text,
    competency_key, source_kind, question_category, purpose,
    next_step_objective, question_type, difficulty, expected_evidence,
    rubric_json, is_required, estimated_seconds
)
SELECT
    assessment_snapshot_id, question_id, display_order, question_text,
    competency_key, source_kind,
    CASE source_kind
        WHEN 'STANDARDIZED' THEN 'FOUNDATION'
        WHEN 'SITUATIONAL' THEN 'APPLICATION'
        WHEN 'CV_VERIFICATION' THEN 'DEEP_DIVE'
        WHEN 'GAP_CONFLICT' THEN 'DEEP_DIVE'
        ELSE 'APPLICATION'
    END,
    purpose, 'Assess evidence against the question rubric.',
    question_type, difficulty, expected_evidence, rubric_json,
    is_required, estimated_seconds
FROM assessment_snapshot_questions_v2_old;

CREATE TABLE assessment_snapshot_answers (
    id TEXT PRIMARY KEY,
    assessment_snapshot_id TEXT NOT NULL
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL,
    answer_text TEXT NOT NULL DEFAULT '',
    is_answered INTEGER NOT NULL CHECK (is_answered IN (0, 1)),
    save_revision INTEGER NOT NULL DEFAULT 0 CHECK (save_revision >= 0),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assessment_snapshot_id, question_id),
    FOREIGN KEY (assessment_snapshot_id, question_id)
        REFERENCES assessment_snapshot_questions(assessment_snapshot_id, question_id)
        ON DELETE CASCADE,
    CHECK (
        (is_answered = 0 AND answer_text = '')
        OR (is_answered = 1 AND length(trim(answer_text)) > 0)
    )
);

INSERT INTO assessment_snapshot_answers(
    id, assessment_snapshot_id, question_id, answer_text, is_answered,
    save_revision, content_sha256, created_at
)
SELECT
    id, assessment_snapshot_id, question_id, answer_text, is_answered,
    save_revision, content_sha256, created_at
FROM assessment_snapshot_answers_v2_old;

DROP TABLE assessment_snapshot_answers_v2_old;
DROP TABLE assessment_snapshot_questions_v2_old;
DROP TABLE answers_v2_old;
DROP TABLE questions_v2_old;

CREATE INDEX ix_questions_set_order
    ON questions(question_set_id, display_order);
CREATE INDEX ix_questions_competency
    ON questions(competency_key);
CREATE INDEX ix_answers_attempt
    ON answers(assessment_attempt_id);
CREATE INDEX ix_assessment_snapshot_questions_order
    ON assessment_snapshot_questions(assessment_snapshot_id, display_order);
CREATE INDEX ix_assessment_snapshot_answers_snapshot
    ON assessment_snapshot_answers(assessment_snapshot_id);

CREATE TRIGGER trg_answers_no_update_after_submit
BEFORE UPDATE OF answer_text, is_answered, save_revision, last_saved_at, submitted_at, updated_at
ON answers
WHEN EXISTS (
    SELECT 1
    FROM assessment_attempts a
    WHERE a.id = OLD.assessment_attempt_id
      AND a.status IN ('ASSESSMENT_SUBMITTED', 'ASSESSMENT_EXPIRED')
)
BEGIN
    SELECT RAISE(ABORT, 'answer_locked_after_submit');
END;

CREATE TRIGGER trg_answers_no_insert_after_submit
BEFORE INSERT ON answers
WHEN EXISTS (
    SELECT 1
    FROM assessment_attempts a
    WHERE a.id = NEW.assessment_attempt_id
      AND a.status IN ('ASSESSMENT_SUBMITTED', 'ASSESSMENT_EXPIRED')
)
BEGIN
    SELECT RAISE(ABORT, 'answer_locked_after_submit');
END;

CREATE TRIGGER trg_questions_max_nine
AFTER INSERT ON questions
WHEN (
    SELECT COUNT(*) FROM questions
    WHERE question_set_id = NEW.question_set_id
) > 9
BEGIN
    SELECT RAISE(ABORT, 'question_set_maximum_is_nine');
END;

UPDATE app_settings
SET value_text = '9', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE key IN ('assessment.default_question_count', 'assessment.max_question_count');
