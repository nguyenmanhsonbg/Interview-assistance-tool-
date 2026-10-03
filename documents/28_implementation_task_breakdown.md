# 28. Phase 2 Supervised Interview Mini Tool — Implementation Task Breakdown

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Engineering Lead |
| Last updated | 2026-10-04 |
| Depends on | 20 Domain and Database; 21 Workflow; 22 AI; 23 API; 24 UI; 25 Security; 26 Document Processing; 27 Test and Acceptance |
| Supersedes | Không có |

## 1. Global constraints

- Runtime Python 3.10+ Standard Library.
- HTTP ThreadingHTTPServer tại 127.0.0.1:8787.
- Frontend HTML/CSS/Vanilla JavaScript ES Modules.
- SQLite sqlite3, WAL, foreign keys, busy_timeout, connection per operation.
- Không Flask/FastAPI/Django/SQLAlchemy/Pydantic/Requests/Node.js/ORM runtime.
- AI qua urllib, persistent ai_tasks và một worker thread mặc định.
- Local data dưới LOCALAPPDATA\ClawCV.
- Candidate Mode không đọc Committee data.
- Không triển khai server tập trung, Phase 1 auth, AMIS, proctoring, OCR hoặc coding judge.

## 2. Batch map

| Batch | Scope | Depends on | Exit checkpoint |
| --- | --- | --- | --- |
| A | Bootstrap/config/HTTP/static frontend | 18, 23, 25 | Health + static page |
| B | SQLite/migration/repository foundation | 20, 27 DB | Migration/tests pass |
| C | Job/Candidate/Case/Document | B, 26 | Case/document flow |
| D | Question Set/Question/Committee review | C, 21, 22 | Approved immutable set |
| E | Candidate Mode/autosave/submit | D, 21, 24, 25 | Locked submitted attempt |
| F | AI provider/task queue/recovery | B, 21, 22 | Fake provider task lifecycle |
| G | Evaluation/Interview Brief | E, F, 22 | Valid result/manual fallback |
| H | Live Interview/Final Evaluation | G, 21, 23, 24 | HĐCM final decision |
| I | Security/audit/backup/restore | B–H, 25 | Security/backup tests |
| J | Full tests/package/Windows pilot | A–I, 27 | Portable smoke pass |

## 3. Task rules

Mỗi task phải:

- Chỉ sửa file trong Files to modify.
- Có test trước hoặc cùng task.
- Chạy test liên quan trước khi chuyển task.
- Không sửa specification để làm cho implementation pass.
- Ghi audit/state behavior trong service, không hardcode business rule trong UI.

## 4. Batch A — Bootstrap, config, HTTP server và static frontend

### TASK-A-001 — Project bootstrap

- Mục tiêu: tạo main process và source tree theo Technology Specification.
- References: TECH-ARCH-001, TECH-DEP-001.
- Depends on: 18, 23.
- Create: main.py; app/config.py; app/server.py; app/router.py; app/responses.py; web/index.html; web/js/app.js; web/js/api.js.
- Modify: none.
- Do not modify: documents, prompts, schemas.
- Test: server startup, host/port, static index.
- Acceptance: one process binds 127.0.0.1:8787; no third-party runtime.
- DoD: unittest smoke, safe shutdown, requestId response.
- Risk: Windows port conflict; show clear error.

### TASK-A-002 — API envelope and router

- Mục tiêu: route table, method/path/body limit and common envelope.
- References: API-ENV-001, API-ENV-002, TECH-HTTP-001.
- Depends on: TASK-A-001.
- Create/modify: app/router.py; app/responses.py; tests/test_router.py.
- Do not modify: domain repositories.
- Test: invalid JSON, body limits, 404/405, requestId.
- Acceptance: no large if/elif handler; no SQL in handler.
- DoD: TEST-API-001..003 pass.
- Risk: inconsistent error mapping; centralize error codes.

### TASK-A-003 — Frontend shell and fetch wrapper

- Mục tiêu: Committee shell, route placeholder, fetch/error wrapper.
- References: UI-ROUTE-001, UI-SEC-001.
- Depends on: TASK-A-002.
- Create/modify: web/css/base.css; web/css/layout.css; web/js/router.js; web/js/store.js; web/js/validation.js; web/js/views/*; web/js/components/*.
- Test: manual route and text rendering checklist.
- Acceptance: textContent for untrusted text; no localStorage token.
- DoD: frontend loads without build step.
- Risk: UI state drift; keep server state authoritative.

## 5. Batch B — SQLite, migration và repository foundation

### TASK-B-001 — Database connection policy

- Mục tiêu: connection factory, directories, PRAGMA.
- References: TECH-DB-001, DATA-DB-001.
- Depends on: TASK-A-001.
- Create/modify: app/database.py; app/config.py; tests/test_database.py.
- Test: WAL, foreign_keys, busy_timeout, connection close.
- Acceptance: no shared global connection and no check_same_thread=False.
- DoD: TEST-DB-002 and connection tests pass.
- Risk: Windows file permission; fail clearly.

### TASK-B-002 — Migration runner and 001 schema

- Mục tiêu: versioned SQL migration matching document 20.
- References: DATA-MIG-001, TECH-MIG-001.
- Depends on: TASK-B-001.
- Create: app/migrations.py; migrations/001_initial.sql; tests/test_migrations.py.
- Do not modify: document DDL without review.
- Test: empty DB migration, idempotency, transaction rollback.
- Acceptance: exactly schema from 20; seed settings; startup stops on failure.
- DoD: TEST-DB-001, TEST-DB-011 pass.
- Risk: SQLite DDL/trigger differences; test on target Windows SQLite.

### TASK-B-003 — Repository base and transaction helpers

- Mục tiêu: parameterized query helpers, row mapping, transaction boundaries.
- References: TECH-DB-002, DATA-QUERY-001.
- Depends on: TASK-B-001/B-002.
- Create: app/repositories/base.py; tests/test_repository_base.py.
- Test: parameter injection strings, rollback, row_factory.
- Acceptance: repositories contain SQL; services contain workflow.
- DoD: TEST-DB-009 pass.
- Risk: long transaction causing lock; keep operations short.

## 6. Batch C — Job, Candidate, Interview Case và Document

### TASK-C-001 — Job/Candidate repositories and services

- Mục tiêu: create/list/update minimum Job and Candidate.
- References: DATA-JOB-001, DATA-CAND-001, API-JOB-001, API-CAND-001.
- Depends on: B.
- Create: app/repositories/jobs.py; candidates.py; app/services/case_service.py; tests/test_job_candidate_service.py.
- Test: unique codes, validation, list filtering.
- Acceptance: no Phase 1 recruitment fields/auth.
- DoD: job/candidate API tests pass.
- Risk: PII overcollection; keep only candidate code/name.

### TASK-C-002 — InterviewCase aggregate service

- Mục tiêu: create/update/list case, policy defaults, committee members.
- References: DATA-CASE-001, WF-CASE-001, API-CASE-001.
- Depends on: TASK-C-001, B.
- Create/modify: app/repositories/interview_cases.py; app/domain/states.py; app/domain/rules.py; app/services/case_service.py; tests/test_case_service.py.
- Test: DRAFT, policy defaults 8/900, one LEAD, cancel pre-attempt.
- Acceptance: case transition uses workflow rules; audit created.
- DoD: TEST-WF-001 and case API tests pass.
- Risk: state rule leaking into controllers; keep domain service boundary.

### TASK-C-003 — Document storage and extraction

- Mục tiêu: safe storage, hash, TXT/MD/DOCX extraction, manual fallback.
- References: DOC-001..DOC-010, SEC-PATH-001.
- Depends on: TASK-C-002.
- Create: app/services/document_service.py; app/infrastructure/file_storage.py; app/repositories/documents.py; tests/test_documents.py; tests/fixtures/.
- Test: TXT/MD/DOCX, malformed/DOCM/traversal/size, version.
- Acceptance: no PDF parser dependency; optional pdftotext adapter isolated.
- DoD: document tests and TEST-SEC-008 pass.
- Risk: ZIP/XML malicious input; guards before extraction.

## 7. Batch D — Question Set, Question và Committee Review

### TASK-D-001 — Question Set repository/service

- Mục tiêu: draft/version/status/edit/order/approval.
- References: DATA-QSET-001, WF-CASE-005..010, AI-Q-001.
- Depends on: C, 21, 22.
- Create/modify: app/repositories/questions.py; app/services/question_service.py; tests/test_questions.py.
- Test: 5–8 questions, 600–900 seconds, immutable approved set, max-eight trigger.
- Acceptance: approval transaction and audit.
- DoD: TEST-WF-005..008 pass.
- Risk: version race; update/supersede in one transaction.

### TASK-D-002 — Question generation task integration

- Mục tiêu: enqueue generation and materialize validated draft.
- References: AI-Q-001, WF-AI-001..005.
- Depends on: TASK-D-001, Batch F interfaces may use fake adapter first.
- Create/modify: app/services/question_service.py; app/ai/schemas.py; tests/test_question_generation.py.
- Test: valid/invalid/failure/manual generation.
- Acceptance: AI result never directly approves; HĐCM gate remains.
- DoD: fake provider tests pass.
- Risk: schema drift; use versioned schema files.

## 8. Batch E — Candidate Mode, autosave và submit

### TASK-E-001 — Candidate session/capability boundary

- Mục tiêu: start attempt, candidate token hash, safe question projection.
- References: SEC-CAND-001, API-CAND-001, WF-ATT-001..002.
- Depends on: C, D, 25.
- Create/modify: app/security.py; app/services/assessment_service.py; app/repositories/assessments.py; tests/test_candidate_access.py.
- Test: valid token, wrong token, safe fields only, one attempt.
- Acceptance: no CV/rubric/AI/evaluation response.
- DoD: TEST-API-005..007, TEST-SEC-004 pass.
- Risk: accidental aggregate serialization; explicit DTO projection.

### TASK-E-002 — Autosave and answer repository

- Mục tiêu: debounced client save endpoint, revision conflict, transaction.
- References: DATA-ANS-001, API-ANS-001, UI-CAND-001.
- Depends on: TASK-E-001.
- Create/modify: app/repositories/assessments.py; app/services/assessment_service.py; web/js/views/candidate_assessment.js; tests/test_answers.py.
- Test: revision, refresh persistence, blank answer, submitted lock.
- Acceptance: answer loss impossible after committed save.
- DoD: TEST-REL-001/002 and TEST-DB-007 pass.
- Risk: stale client; compare clientRevision server-side.

### TASK-E-003 — Submit, timer and recovery

- Mục tiêu: flush/submit/auto-submit/interrupt/resume.
- References: WF-ATT-003..007, API-ATT-001.
- Depends on: TASK-E-002, 21.
- Create/modify: app/services/assessment_service.py; app/domain/rules.py; web/js/components/timer.js; tests/test_assessment_workflow.py.
- Test: incomplete manual submit, expiry auto-submit, crash/restart, no reopen.
- Acceptance: lock transaction and audit.
- DoD: TEST-WF-010..014 and TEST-UI-003..005 pass.
- Risk: client clock mismatch; server expiresAt authoritative.

## 9. Batch F — AI provider, persistent task queue và recovery

### TASK-F-001 — AI provider interface and HTTP adapter

- Mục tiêu: AIProvider interface and urllib implementation.
- References: TECH-AI-001, AI-PRIV-001.
- Depends on: B, 22.
- Create: app/ai/provider.py; app/ai/http_provider.py; app/ai/prompts.py; tests/test_ai_provider.py.
- Test: JSON request, timeout, 429, 4xx, 5xx, response size.
- Acceptance: no requests/aiohttp; explicit timeout/backoff.
- DoD: AI adapter unit tests pass.
- Risk: provider contract differences; isolate adapter.

### TASK-F-002 — Prompt/schema validation

- Mục tiêu: load versioned prompts and validate output manually.
- References: AI-VAL-001, AI-PRM-001.
- Depends on: TASK-F-001.
- Create: app/ai/schemas.py; app/ai/prompts.py; tests/test_ai_schemas.py.
- Test: all fixtures valid/invalid/range/enum/missing.
- Acceptance: no Pydantic/jsonschema runtime.
- DoD: TEST-AI-001..008, TEST-AI-011/012 pass.
- Risk: schema files and validator diverge; schema tests pin both.

### TASK-F-003 — Persistent queue and worker

- Mục tiêu: ai_tasks repository, Queue, one worker, retry/recovery.
- References: WF-AI-001..007, TECH-AI-002.
- Depends on: TASK-F-001/002, B.
- Create: app/repositories/ai_tasks.py; app/ai/task_worker.py; app/services/ai_task_service.py; tests/test_ai_tasks.py.
- Test: FIFO, idempotency, retry once, restart RUNNING recovery.
- Acceptance: HTTP returns 202; worker not unbounded.
- DoD: TEST-WF-015..018 and TEST-REL-004 pass.
- Risk: duplicate task/result; unique idempotency and transaction.

## 10. Batch G — AI evaluation và Interview Brief

### TASK-G-001 — Answer evaluation materialization

- Mục tiêu: create evaluation task input manifest and persist validated AiResult.
- References: AI-A-001, AI-AI-RESULT-001, WF-CASE-018..020.
- Depends on: E, F.
- Create/modify: app/services/evaluation_service.py; app/repositories/evaluations.py; tests/test_ai_evaluation.py.
- Test: answered/unanswered, conflict, score range, result version.
- Acceptance: no final decision from AI; failure leaves answer readable.
- DoD: TEST-AI-004..006, TEST-UI-007 pass.
- Risk: raw payload leakage; sanitize manifest/result handling.

### TASK-G-002 — Interview Brief and manual fallback

- Mục tiêu: materialize AI brief, create manual brief, version/revision.
- References: AI-B-001, WF-CASE-019..022, API-BRIEF-001.
- Depends on: TASK-G-001.
- Create/modify: app/services/interview_brief_service.py; app/repositories/evaluations.py; tests/test_brief.py.
- Test: current version, manual fallback, limitations, 3+2 live question limits.
- Acceptance: brief readable in 3–5 minutes; no candidate access.
- DoD: TEST-AI-006 and brief API/UI tests pass.
- Risk: AI result schema changes; store schema version/payload.

## 11. Batch H — Live Interview và Final Evaluation

### TASK-H-001 — Live interview records

- Mục tiêu: start/record/skip/follow-up/complete.
- References: WF-CASE-023..025, API-LIVE-001, UI-LIVE-001.
- Depends on: G, 23, 24.
- Create/modify: app/services/interview_service.py; app/repositories/evaluations.py; tests/test_live_interview.py.
- Test: sequence, score/evidence enum, conflict flag, member attribution.
- Acceptance: records immutable enough for audit; updates are explicit.
- DoD: TEST-UI-008 and workflow live tests pass.
- Risk: notes lost; save mutation with retry-safe idempotency.

### TASK-H-002 — Final evaluation and revisions

- Mục tiêu: draft/finalize/revise with lead/finalizer.
- References: WF-CASE-026, DATA-EVAL-001, API-EVAL-001.
- Depends on: TASK-H-001.
- Create/modify: app/services/evaluation_service.py; app/repositories/evaluations.py; tests/test_final_evaluation.py.
- Test: final enum, required member/time, revision preserves old version.
- Acceptance: only Committee finalizes; case EVALUATED only after final.
- DoD: TEST-WF-019/020 and TEST-UI-009 pass.
- Risk: accidental overwrite; unique current + version transaction.

## 12. Batch I — Security, audit, backup và restore

### TASK-I-001 — Localhost/session/PIN security

- Mục tiêu: Host validation, startup token, Committee PIN/session, candidate capability middleware.
- References: 25 Security, SEC-NET-001..003.
- Depends on: A, E.
- Create/modify: app/security.py; app/server.py; app/router.py; tests/test_security.py.
- Test: host/token/PIN/session expiry/capability.
- Acceptance: no secret logs/frontend; Candidate isolation.
- DoD: TEST-SEC-001..006 pass.
- Risk: local browser cross-process calls; strict headers and token checks.

### TASK-I-002 — Audit service and redacted logging

- Mục tiêu: append-only audit events and rotating redacted logs.
- References: DATA-AUD-001, SEC-AUDIT-001.
- Depends on: B, all services.
- Create/modify: app/services/audit_service.py; app/config.py; tests/test_audit_logging.py.
- Test: event catalog, redaction, case delete retention.
- Acceptance: no raw PII/secret; audit remains after delete.
- DoD: TEST-SEC-006/009 and audit tests pass.
- Risk: accidental log argument; central redaction helper.

### TASK-I-003 — Backup, export and restore

- Mục tiêu: SQLite Backup API and ZIP export with manifest.
- References: TECH-BACKUP-001, SEC-BACKUP-001, API-BACKUP-001.
- Depends on: B, C, H.
- Create: app/services/backup_service.py; tests/test_backup.py.
- Test: online backup, restore temp DB, export excludes secrets, delete requires backup.
- Acceptance: no raw db copy while writing; safe package.
- DoD: TEST-REL-005/006 and TEST-SEC-010 pass.
- Risk: document/db mismatch; package manifest hashes.

## 13. Batch J — Test, packaging và Windows pilot

### TASK-J-001 — Full automated test suite

- Mục tiêu: integrate tests and regression command.
- References: 27 Test and Acceptance.
- Depends on: A–I.
- Create/modify: tests/*; scripts/run_tests.ps1.
- Test: python -m unittest discover -s tests -v.
- Acceptance: all P0 pass; report artifacts captured.
- DoD: exit criteria from 27 satisfied.
- Risk: flaky time/network tests; fake clock/provider.

### TASK-J-002 — Packaging

- Mục tiêu: portable bundle with Python runtime and launch script.
- References: TECH-DEPLOY-001.
- Depends on: J-001.
- Create: scripts/package_windows.ps1; start.bat; README.txt; packaging config.
- Do not modify: user data under LOCALAPPDATA.
- Test: clean Windows smoke, checksum.
- Acceptance: client does not need Python/Node/database/Docker.
- DoD: TEST Windows smoke passes.
- Risk: runtime bundling/licensing; record build tool versions.

### TASK-J-003 — Release readiness

- Mục tiêu: package verification, known limitations, handoff.
- References: 27 exit criteria, 19 S3.
- Depends on: J-002.
- Create/modify: README.md; release checklist.
- Test: clean install/unpack and full manual acceptance.
- Acceptance: DRAFT specifications reviewed before marking APPROVED; no untracked secret.
- DoD: release evidence and rollback backup available.
- Risk: pilot data migration; provide backup/restore instructions.

## 14. File ownership summary

| Area | Owner files | Must not contain |
| --- | --- | --- |
| HTTP | app/server.py, router.py, responses.py | SQL/business workflow |
| Domain | app/domain/*, services/* | HTTP request/response details |
| Repository | app/repositories/* | UI rendering/business orchestration |
| AI | app/ai/*, prompts/*, schemas/* | Direct state mutation without service |
| Storage | database.py, migrations, file_storage.py | User-provided raw paths |
| Frontend | web/* | SQLite/filesystem/API key |
| Tests | tests/* | Real provider/real PII |
| Packaging | scripts/* | Runtime data in install directory |

## 15. Risk register

| Risk | Mitigation | Owner batch |
| --- | --- | --- |
| State drift across UI/API/DB | Workflow tests and centralized service | D–H |
| Answer loss | SQLite transaction, autosave, restart tests | E |
| AI output invalid | Versioned schemas, fake provider, manual fallback | F–G |
| Candidate data leakage | Capability DTO projection and security tests | E/I |
| Unsafe document | Size/signature/path/parser guards | C |
| Accidental deletion | Backup gate and audit | I |
| Runtime dependency drift | CI/package dependency check | A/J |

## 16. Definition of Done

Một task hoàn tất khi:

- Code nằm đúng file ownership.
- Requirement/spec reference được ghi trong task/commit.
- Test liên quan chạy và có evidence.
- Không thêm runtime dependency ngoài Technology Specification.
- Error/failure/recovery path được kiểm thử.
- Audit/state/security behavior được kiểm tra.
- Không có raw PII/secret trong log/test fixture.

## 17. Conflict / Assumption / Open Questions

### Conflict

- File 19 có đánh số AI/API cũ; task dùng thứ tự chính thức 22 AI, 23 API.
- Technology cho phép build-time packaging tool nhưng runtime chỉ Standard Library; Batch J giữ ranh giới này.

### Assumption

- Native desktop framework không được dùng; browser localhost là UI runtime.
- Batch có thể dùng fake adapter trước khi provider thật được chốt.
- Tasks độc lập trong batch nhưng phải giữ interfaces nêu trong các specification.

### Open Questions / Backlog

- Provider/model chính thức và quota.
- Code signing/installer tool.
- CI runner Windows.
- Multi-machine/server mode.

## 18. Acceptance criteria

1. Có Batch A–J đúng phạm vi yêu cầu.
2. Mỗi batch có task nhỏ, dependency, files, tests, acceptance, DoD và risk.
3. Task tham chiếu specification/requirement.
4. Có file ownership và do-not-touch boundaries.
5. Có test command, packaging checkpoint, risk register và Definition of Done.
6. Không có task yêu cầu ORM/framework/runtime dependency ngoài scope.
