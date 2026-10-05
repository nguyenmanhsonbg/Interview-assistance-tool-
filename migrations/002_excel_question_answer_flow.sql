ALTER TABLE interview_cases
    ADD COLUMN refined_flow_status TEXT CHECK (
        refined_flow_status IS NULL OR refined_flow_status IN (
            'DRAFT', 'DOCUMENTS_READY', 'QUESTIONS_GENERATING',
            'QUESTIONS_GENERATED', 'QUESTIONS_EXPORTED', 'ANSWERS_IMPORTED',
            'AI_ANALYZING', 'AI_EVALUATED', 'QUESTION_GENERATION_FAILED',
            'AI_ANALYSIS_FAILED'
        )
    );

CREATE TABLE assessment_snapshots (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE RESTRICT,
    version_no INTEGER NOT NULL CHECK (version_no > 0),
    source_kind TEXT NOT NULL CHECK (source_kind = 'EXCEL_IMPORT'),
    status TEXT NOT NULL DEFAULT 'IMPORTED' CHECK (
        status IN ('IMPORTED', 'AI_ANALYZING', 'AI_EVALUATED', 'AI_ANALYSIS_FAILED')
    ),
    workbook_sha256 TEXT NOT NULL CHECK (length(workbook_sha256) = 64),
    normalized_fingerprint TEXT NOT NULL CHECK (length(normalized_fingerprint) = 64),
    idempotency_key_hash TEXT NOT NULL CHECK (length(idempotency_key_hash) = 64),
    document_manifest_json TEXT NOT NULL DEFAULT '[]',
    imported_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no),
    UNIQUE (interview_case_id, idempotency_key_hash)
);

CREATE TABLE assessment_snapshot_questions (
    assessment_snapshot_id TEXT NOT NULL
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE RESTRICT,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 8),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    competency_key TEXT NOT NULL CHECK (length(trim(competency_key)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'STANDARDIZED', 'SITUATIONAL', 'CV_VERIFICATION',
            'GAP_CONFLICT', 'QUESTION_BANK', 'MANUAL', 'AI'
        )
    ),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
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

ALTER TABLE ai_tasks
    ADD COLUMN assessment_snapshot_id TEXT
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE;

ALTER TABLE ai_results
    ADD COLUMN assessment_snapshot_id TEXT
        REFERENCES assessment_snapshots(id) ON DELETE CASCADE;

CREATE INDEX ix_assessment_snapshots_case_version
    ON assessment_snapshots(interview_case_id, version_no);
CREATE INDEX ix_assessment_snapshot_questions_order
    ON assessment_snapshot_questions(assessment_snapshot_id, display_order);
CREATE INDEX ix_assessment_snapshot_answers_snapshot
    ON assessment_snapshot_answers(assessment_snapshot_id);
CREATE INDEX ix_ai_tasks_snapshot
    ON ai_tasks(assessment_snapshot_id);
CREATE INDEX ix_ai_results_snapshot
    ON ai_results(assessment_snapshot_id, result_type);
