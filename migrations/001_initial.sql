PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    job_code TEXT UNIQUE,
    position_title TEXT NOT NULL CHECK (length(trim(position_title)) > 0),
    target_level TEXT NOT NULL CHECK (length(trim(target_level)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    candidate_code TEXT NOT NULL UNIQUE CHECK (length(trim(candidate_code)) > 0),
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE interview_cases (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT', 'DOCUMENTS_READY', 'QUESTIONS_GENERATING',
        'QUESTIONS_GENERATED', 'QUESTIONS_APPROVED',
        'READY_FOR_ASSESSMENT', 'ASSESSMENT_IN_PROGRESS',
        'ASSESSMENT_SUBMITTED', 'AI_ANALYZING',
        'INTERVIEW_BRIEF_READY', 'LIVE_INTERVIEW_IN_PROGRESS',
        'LIVE_INTERVIEW_COMPLETED', 'EVALUATION_PENDING', 'EVALUATED',
        'DOCUMENT_PARSE_FAILED', 'QUESTION_GENERATION_FAILED',
        'ASSESSMENT_INTERRUPTED', 'ASSESSMENT_EXPIRED',
        'AI_ANALYSIS_FAILED', 'CANDIDATE_NO_SHOW', 'CANCELLED'
    )),
    scheduled_at TEXT,
    assessment_duration_seconds INTEGER NOT NULL DEFAULT 900
        CHECK (assessment_duration_seconds > 0),
    allow_incomplete_submit INTEGER NOT NULL DEFAULT 1
        CHECK (allow_incomplete_submit IN (0, 1)),
    auto_submit_on_expiry INTEGER NOT NULL DEFAULT 1
        CHECK (auto_submit_on_expiry IN (0, 1)),
    materials_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    internet_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    tools_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE interview_case_committee_members (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    role TEXT NOT NULL DEFAULT 'MEMBER' CHECK (role IN ('MEMBER', 'LEAD')),
    display_order INTEGER NOT NULL DEFAULT 1 CHECK (display_order > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, display_name)
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL CHECK (document_type IN ('JD', 'CV')),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('IMPORTED_FILE', 'MANUAL_TEXT', 'PHASE1_CLEAN_SNAPSHOT')
    ),
    extraction_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        extraction_status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'MANUAL_CONFIRMED')
    ),
    original_filename TEXT,
    mime_type TEXT,
    file_size_bytes INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    file_sha256 TEXT CHECK (
        file_sha256 IS NULL OR length(file_sha256) = 64
    ),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    storage_path TEXT,
    extracted_text TEXT NOT NULL DEFAULT '',
    is_ai_eligible INTEGER NOT NULL DEFAULT 0 CHECK (is_ai_eligible IN (0, 1)),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    confirmed_at TEXT,
    supersedes_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, document_type, version_no),
    CHECK (
        (storage_path IS NULL AND file_sha256 IS NULL)
        OR (storage_path IS NOT NULL AND file_sha256 IS NOT NULL)
    )
);

CREATE TABLE question_sets (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT', 'GENERATED', 'APPROVED', 'SUPERSEDED')
    ),
    duration_seconds INTEGER NOT NULL DEFAULT 900
        CHECK (duration_seconds BETWEEN 600 AND 900),
    rubric_policy_json TEXT NOT NULL DEFAULT '{}',
    question_policy_json TEXT NOT NULL DEFAULT '{}',
    approved_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    approved_at TEXT,
    supersedes_question_set_id TEXT
        REFERENCES question_sets(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no)
);

CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
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

CREATE TABLE assessment_attempts (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL UNIQUE
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'READY_FOR_ASSESSMENT' CHECK (
        status IN (
            'READY_FOR_ASSESSMENT', 'ASSESSMENT_IN_PROGRESS',
            'ASSESSMENT_SUBMITTED', 'ASSESSMENT_INTERRUPTED',
            'ASSESSMENT_EXPIRED'
        )
    ),
    candidate_token_hash TEXT UNIQUE,
    started_at TEXT,
    expires_at TEXT,
    submitted_at TEXT,
    submit_reason TEXT CHECK (
        submit_reason IS NULL OR submit_reason IN (
            'MANUAL', 'AUTO_SUBMIT', 'TIME_EXPIRED', 'RECOVERY'
        )
    ),
    allow_answer_edit INTEGER NOT NULL DEFAULT 1
        CHECK (allow_answer_edit IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

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

CREATE TABLE ai_tasks (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK (
        task_type IN (
            'GENERATE_QUESTIONS', 'EVALUATE_ASSESSMENT',
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
    finished_at TEXT
);

CREATE TABLE ai_results (
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
            'QUESTION_GENERATION', 'ANSWER_EVALUATION',
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
    UNIQUE (interview_case_id, result_type, version_no)
);

CREATE TABLE interview_briefs (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT NOT NULL
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    ai_result_id TEXT REFERENCES ai_results(id) ON DELETE SET NULL,
    source_kind TEXT NOT NULL DEFAULT 'AI' CHECK (
        source_kind IN ('AI', 'MANUAL')
    ),
    status TEXT NOT NULL DEFAULT 'READY' CHECK (
        status IN ('DRAFT', 'READY', 'SUPERSEDED')
    ),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    supersedes_brief_id TEXT REFERENCES interview_briefs(id) ON DELETE SET NULL,
    brief_json TEXT NOT NULL DEFAULT '{}',
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no),
    CHECK (
        (source_kind = 'AI' AND ai_result_id IS NOT NULL)
        OR (source_kind = 'MANUAL')
    )
);

CREATE TABLE live_interview_records (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    interview_brief_id TEXT
        REFERENCES interview_briefs(id) ON DELETE SET NULL,
    committee_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'BRIEF_RECOMMENDED', 'MANUAL', 'FOLLOW_UP', 'AI_SUGGESTED'
        )
    ),
    asked_status TEXT NOT NULL DEFAULT 'PLANNED' CHECK (
        asked_status IN ('PLANNED', 'ASKED', 'SKIPPED')
    ),
    live_notes TEXT,
    score INTEGER CHECK (score IS NULL OR score BETWEEN 0 AND 4),
    evidence_status TEXT CHECK (
        evidence_status IS NULL OR evidence_status IN (
            'VERIFIED', 'PARTIALLY_VERIFIED', 'UNVERIFIED',
            'CONFLICTING', 'NOT_MET', 'NOT_ASSESSED'
        )
    ),
    asked_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, sequence_no)
);

CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'FINAL')),
    final_result TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        final_result IN (
            'PASS', 'FAIL', 'NEXT_ROUND',
            'NEEDS_ADDITIONAL_ASSESSMENT', 'PENDING'
        )
    ),
    final_level TEXT,
    summary TEXT,
    strengths_json TEXT NOT NULL DEFAULT '[]',
    gaps_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    final_comment TEXT,
    decided_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    decided_at TEXT,
    supersedes_evaluation_id TEXT
        REFERENCES evaluations(id) ON DELETE SET NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no),
    CHECK (
        status = 'DRAFT'
        OR (decided_by_member_id IS NOT NULL AND decided_at IS NOT NULL)
    )
);

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL CHECK (
        actor_type IN ('SYSTEM', 'AI', 'HR_COORDINATOR', 'COMMITTEE', 'CANDIDATE')
    ),
    actor_ref_id TEXT,
    action TEXT NOT NULL CHECK (length(trim(action)) > 0),
    entity_type TEXT NOT NULL CHECK (length(trim(entity_type)) > 0),
    entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
    request_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_type TEXT NOT NULL CHECK (
        value_type IN ('STRING', 'INTEGER', 'BOOLEAN', 'JSON', 'SECRET_REF')
    ),
    value_text TEXT,
    protected_value BLOB,
    is_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (is_sensitive IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (is_sensitive = 1 AND protected_value IS NOT NULL AND value_text IS NULL)
        OR (is_sensitive = 0 AND protected_value IS NULL)
    )
);

CREATE UNIQUE INDEX uq_case_one_lead
    ON interview_case_committee_members(interview_case_id)
    WHERE role = 'LEAD';

CREATE UNIQUE INDEX uq_case_one_current_jd
    ON documents(interview_case_id, document_type)
    WHERE document_type = 'JD' AND is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_cv
    ON documents(interview_case_id, document_type)
    WHERE document_type = 'CV' AND is_current = 1;

CREATE UNIQUE INDEX uq_case_one_approved_question_set
    ON question_sets(interview_case_id)
    WHERE status = 'APPROVED';

CREATE UNIQUE INDEX uq_case_one_current_brief
    ON interview_briefs(interview_case_id)
    WHERE is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_evaluation
    ON evaluations(interview_case_id)
    WHERE is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_ai_result
    ON ai_results(interview_case_id, result_type)
    WHERE is_current = 1;

CREATE INDEX ix_cases_status_schedule
    ON interview_cases(status, scheduled_at);
CREATE INDEX ix_cases_candidate ON interview_cases(candidate_id);
CREATE INDEX ix_cases_job ON interview_cases(job_id);
CREATE INDEX ix_committee_case ON interview_case_committee_members(interview_case_id);
CREATE INDEX ix_documents_case_type
    ON documents(interview_case_id, document_type, is_current);
CREATE INDEX ix_question_sets_case_status
    ON question_sets(interview_case_id, status);
CREATE INDEX ix_questions_set_order
    ON questions(question_set_id, display_order);
CREATE INDEX ix_questions_competency
    ON questions(competency_key);
CREATE INDEX ix_attempts_status_expiry
    ON assessment_attempts(status, expires_at);
CREATE INDEX ix_answers_attempt
    ON answers(assessment_attempt_id);
CREATE INDEX ix_ai_tasks_status_created
    ON ai_tasks(status, created_at);
CREATE INDEX ix_ai_tasks_case ON ai_tasks(interview_case_id);
CREATE INDEX ix_ai_results_attempt
    ON ai_results(assessment_attempt_id, result_type);
CREATE INDEX ix_briefs_case_current
    ON interview_briefs(interview_case_id, is_current);
CREATE INDEX ix_live_case_sequence
    ON live_interview_records(interview_case_id, sequence_no);
CREATE INDEX ix_evaluations_case_current
    ON evaluations(interview_case_id, is_current);
CREATE INDEX ix_audit_entity_time
    ON audit_logs(entity_type, entity_id, created_at);
CREATE INDEX ix_audit_action_time
    ON audit_logs(action, created_at);

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

CREATE TRIGGER trg_questions_max_eight
AFTER INSERT ON questions
WHEN (
    SELECT COUNT(*) FROM questions
    WHERE question_set_id = NEW.question_set_id
) > 8
BEGIN
    SELECT RAISE(ABORT, 'question_set_maximum_is_eight');
END;

INSERT INTO app_settings(key, value_type, value_text, is_sensitive)
VALUES
    ('assessment.default_question_count', 'INTEGER', '8', 0),
    ('assessment.max_question_count', 'INTEGER', '8', 0),
    ('assessment.default_duration_seconds', 'INTEGER', '900', 0),
    ('assessment.allow_incomplete_submit', 'BOOLEAN', '1', 0),
    ('assessment.auto_submit_on_expiry', 'BOOLEAN', '1', 0),
    ('ai.redaction_policy', 'STRING', 'SANITIZED_TEXT_ONLY', 0),
    ('retention.mode', 'STRING', 'MANUAL_ONLY', 0);

INSERT INTO schema_migrations(version) VALUES (1);
