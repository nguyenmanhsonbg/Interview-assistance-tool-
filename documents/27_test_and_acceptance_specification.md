# 27. Phase 2 Supervised Interview Mini Tool — Test and Acceptance Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | QA/Test + Product Owner |
| Last updated | 2026-10-04 |
| Depends on | 17 Context; 18 Technology; 20 Domain and Database; 21 Workflow; 22 AI; 23 API; 24 UI; 25 Security; 26 Document Processing |
| Supersedes | Không có |

## 1. Test strategy

Mục tiêu là chứng minh MVP local-first không mất dữ liệu, không lộ dữ liệu Candidate và không cho state transition ngoài contract.

Test levels:

1. Unit: domain rule, validation, parser, hash, redaction.
2. Repository/database: DDL, FK, index, trigger, migration, transaction.
3. Service/workflow: transition, retry, recovery, idempotency.
4. HTTP integration: ThreadingHTTPServer localhost, envelope, auth/capability, status.
5. AI contract: fake provider, schema validation, retry/fallback.
6. Frontend manual: browser flow và Candidate isolation.
7. Packaging/smoke: Windows portable bundle.

Backend automated test dùng unittest và Python Standard Library. Không gọi AI provider thật.

## 2. Test environment và fixtures

- Windows test client.
- Temporary DATA_DIRECTORY và temporary SQLite database.
- PRAGMA foreign_keys=ON, WAL, busy_timeout=5000.
- Fake AI provider trả success, invalid JSON, schema-invalid, timeout, 429, 500 và 4xx.
- Fixtures: one Job, one Candidate, one case, JD/CV clean text, approved Question Set 8 questions, attempt with 8 answers.
- Malicious fixtures: DOCM marker, malformed DOCX, ZIP bomb metadata, path traversal filename, HTML/script text, prompt injection text.
- Session fixtures: valid/expired Committee session, valid/expired candidate token, wrong capability.
- Clock fixture để test expires_at/recovery.

## 3. Testcase format

Mỗi testcase gồm ID, requirement reference, priority, precondition, input, steps, expected result, automated/manual và evidence.

## 4. Database and migration tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-DB-001 | TECH-DB-001 | P0 | Run migration 001 on empty temp DB | All 17 tables, indexes, triggers and seed settings created; schema_migrations=1 |
| TEST-DB-002 | TECH-DB-001 | P0 | Open connection with FK on and insert orphan case | FK rejects insert |
| TEST-DB-003 | DATA-REL-001 | P0 | Insert duplicate candidate_code/job_code | UNIQUE rejects |
| TEST-DB-004 | DATA-REL-002 | P0 | Insert two current JD or two approved Question Set | Partial unique index rejects |
| TEST-DB-005 | DATA-Q-001 | P0 | Insert ninth Question into Question Set | Trigger rejects |
| TEST-DB-006 | DATA-ATT-001 | P0 | Create two attempts for one case | UNIQUE rejects |
| TEST-DB-007 | DATA-ANS-001 | P0 | Update answer after submitted attempt | Trigger/service rejects |
| TEST-DB-008 | DATA-EVAL-001 | P0 | Final evaluation without finalizer/timestamp | CHECK/service rejects |
| TEST-DB-009 | TECH-DB-002 | P1 | Run parameterized repository queries with quotes/input operators | No SQL injection; correct result |
| TEST-DB-010 | DATA-AUD-001 | P1 | Delete case graph | Case-owned rows removed, AuditLog retained |
| TEST-DB-011 | TECH-DB-003 | P1 | Run migration failure in transaction | No partial schema; startup blocked |

## 5. Domain and workflow tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-WF-001 | WF-CASE-001 | P0 | Create case with candidate/job/policy | DRAFT and CASE_CREATED |
| TEST-WF-002 | WF-CASE-002 | P0 | Confirm current JD/CV | DOCUMENTS_READY only when both eligible |
| TEST-WF-003 | WF-CASE-003 | P0 | Parse failure and manual paste replacement | DOCUMENT_PARSE_FAILED then DOCUMENTS_READY |
| TEST-WF-004 | WF-CASE-005 | P0 | Generate questions with missing CV text | Transition rejected, no task |
| TEST-WF-005 | WF-CASE-006 | P0 | Fake AI success | QUESTIONS_GENERATED and draft set |
| TEST-WF-006 | WF-CASE-007 | P0 | Fake AI failure after retry | QUESTION_GENERATION_FAILED; manual path available |
| TEST-WF-007 | WF-CASE-010 | P0 | Approve 8 valid questions | APPROVED immutable snapshot |
| TEST-WF-008 | WF-CASE-010 | P0 | Approve 4 or 9 questions | Validation rejects |
| TEST-WF-009 | WF-CASE-012 | P0 | Start Candidate Mode with valid PIN/token | Attempt IN_PROGRESS and expiresAt |
| TEST-WF-010 | WF-ATT-003 | P0 | Submit incomplete answers | SUBMITTED; blank answers remain NOT_ASSESSED downstream |
| TEST-WF-011 | WF-ATT-004 | P0 | Advance clock past expiresAt | Auto-submit TIME_EXPIRED |
| TEST-WF-012 | WF-ATT-008 | P0 | Reopen or edit submitted attempt | STATE_CONFLICT; answer unchanged |
| TEST-WF-013 | WF-ATT-005 | P1 | Simulate crash after autosave | ATTEMPT_INTERRUPTED; saved answer remains |
| TEST-WF-014 | WF-ATT-006 | P1 | Resume interrupted attempt before expiry | Same attempt returns IN_PROGRESS |
| TEST-WF-015 | WF-AI-004 | P0 | Network timeout with retry count 0 | PENDING_RETRY then one retry |
| TEST-WF-016 | WF-AI-005 | P0 | Provider 4xx auth/payload | FAILED, no successful result |
| TEST-WF-017 | WF-AI-003 | P0 | Valid AI output | COMPLETED and one immutable AiResult |
| TEST-WF-018 | WF-AI-008 | P0 | Force rerun same case | New task/result version; old result unchanged |
| TEST-WF-019 | WF-CASE-026 | P0 | Finalize with lead member | EVALUATED and FINAL evaluation |
| TEST-WF-020 | WF-CASE-026 | P0 | AI tries to set final PASS/FAIL | No direct transition; authorization rejects |

## 6. AI contract tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-AI-001 | AI-Q-001 | P0 | Validate question-generation fixture | JSON schema and domain validation pass |
| TEST-AI-002 | AI-Q-002 | P0 | Fixture with 4/9 questions | Reject |
| TEST-AI-003 | AI-Q-003 | P0 | Fixture score/rubric enum out of range | Reject |
| TEST-AI-004 | AI-A-001 | P0 | Evaluate answered and unanswered answers | Unanswered score null/NOT_ASSESSED |
| TEST-AI-005 | AI-A-002 | P0 | Fixture with invalid evidenceStatus | Reject |
| TEST-AI-006 | AI-B-001 | P0 | Brief has 3 required and max 2 additional questions | Valid |
| TEST-AI-007 | AI-F-001 | P1 | Follow-up output 1–3 questions | Valid |
| TEST-AI-008 | AI-F-002 | P1 | Follow-up repeats asked question | Domain validation rejects |
| TEST-AI-009 | AI-SEC-001 | P0 | Prompt injection in JD/CV/answer | Treated as content; no task/schema change |
| TEST-AI-010 | AI-PRIV-001 | P0 | Inspect provider payload | No raw file, token, API key or unnecessary PII |
| TEST-AI-011 | AI-FAIL-001 | P0 | Invalid JSON then repair success | One retry, then result only after validation |
| TEST-AI-012 | AI-FAIL-002 | P0 | Invalid JSON twice | FAILED and manual fallback |

## 7. API tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-API-001 | API-ENV-001 | P0 | Health request | 200 success envelope/requestId |
| TEST-API-002 | API-ENV-002 | P0 | Malformed JSON | 400 INVALID_JSON safe envelope |
| TEST-API-003 | API-ENV-003 | P0 | Body over limit | 413 before full read |
| TEST-API-004 | API-AUTH-001 | P0 | Mutation without startup token | 401 |
| TEST-API-005 | API-AUTH-002 | P0 | Candidate calls Committee endpoint | 403 or generic 404 |
| TEST-API-006 | API-CAND-001 | P0 | Candidate reads questions | Only safe fields returned |
| TEST-API-007 | API-CAND-002 | P0 | Candidate requests CV/AI task | Denied; no existence leakage |
| TEST-API-008 | API-IDEMP-001 | P0 | Repeat submit same key | Same result, no duplicate audit/transition |
| TEST-API-009 | API-IDEMP-002 | P1 | Same key with different payload | 409 IDEMPOTENCY_CONFLICT |
| TEST-API-010 | API-STATE-001 | P0 | Approve before documents/questions valid | 409 STATE_CONFLICT |
| TEST-API-011 | API-UPLOAD-001 | P0 | Upload valid DOCX/base64 | 201 Document version |
| TEST-API-012 | API-UPLOAD-002 | P0 | Upload DOCM/traversal filename | Rejected, no unsafe path |
| TEST-API-013 | API-AI-001 | P0 | Enqueue AI evaluation | 202, taskId, no long request |
| TEST-API-014 | API-AI-002 | P1 | Poll terminal task | Poll stops at COMPLETED/FAILED |

## 8. Document processing tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-DOC-001 | DOC-001 | P0 | TXT UTF-8/BOM/newline | Canonical normalized text/hash |
| TEST-DOC-002 | DOC-002 | P0 | Markdown with HTML/script text | Stored as text; never executed/rendered raw |
| TEST-DOC-003 | DOC-003 | P0 | Valid DOCX paragraphs/table | Extracted ordered text |
| TEST-DOC-004 | DOC-004 | P0 | DOCX containing vbaProject.bin | Rejected |
| TEST-DOC-005 | DOC-005 | P0 | Malformed ZIP/XML | DOCUMENT_PARSE_FAILED and paste fallback |
| TEST-DOC-006 | DOC-006 | P0 | PDF without extractor | Failed/manual paste path |
| TEST-DOC-007 | DOC-007 | P1 | Approved pdftotext success/failure | Success stores text; failure safe fallback |
| TEST-DOC-008 | DOC-008 | P0 | File > decoded limit | Rejected before extraction |
| TEST-DOC-009 | DOC-009 | P0 | Filename ../ or absolute path | Generated safe path only |
| TEST-DOC-010 | DOC-010 | P1 | New document version | Old snapshot unchanged/current pointer updated |

## 9. Security and privacy tests

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-SEC-001 | SEC-NET-001 | P0 | Inspect server bind | 127.0.0.1 only |
| TEST-SEC-002 | SEC-NET-002 | P0 | Invalid Host header | Rejected |
| TEST-SEC-003 | SEC-AUTH-001 | P0 | Wrong PIN rate limit | Delay/lock behavior, no secret leak |
| TEST-SEC-004 | SEC-AUTH-002 | P0 | Candidate token from another attempt | Denied |
| TEST-SEC-005 | SEC-XSS-001 | P0 | AI/CV text containing script | Rendered as text, no execution |
| TEST-SEC-006 | SEC-SECRET-001 | P0 | Search logs/frontend/export | No key/PIN/token |
| TEST-SEC-007 | SEC-AI-001 | P0 | Inspect AI payload | Sanitized text only |
| TEST-SEC-008 | SEC-PATH-001 | P0 | Resolve delete path outside root | Delete blocked |
| TEST-SEC-009 | SEC-AUDIT-001 | P1 | Case hard delete | Delete audit remains |
| TEST-SEC-010 | SEC-BACKUP-001 | P0 | Delete without backup | BACKUP_REQUIRED; no delete |

## 10. Autosave, restart, backup and reliability

| ID | Ref | Priority | Test | Expected |
| --- | --- | --- | --- | --- |
| TEST-REL-001 | TECH-REL-001 | P0 | Autosave while typing | Debounced, no UI blocking |
| TEST-REL-002 | TECH-REL-002 | P0 | Refresh after autosave | Latest answer remains |
| TEST-REL-003 | TECH-REL-003 | P0 | Crash before submit | Committed answer remains |
| TEST-REL-004 | TECH-REL-004 | P0 | Restart with RUNNING AiTask | Recovery to retry/fail, no duplicate result |
| TEST-REL-005 | TECH-REL-005 | P1 | Backup while DB writes | SQLite Backup API produces restorable DB |
| TEST-REL-006 | TECH-REL-006 | P1 | Restore backup to temp directory | Schema/data/foreign keys valid |
| TEST-REL-007 | TECH-PERF-001 | P1 | Local API with AI task pending | API remains responsive |
| TEST-REL-008 | TECH-PERF-002 | P1 | One AI worker with multiple tasks | FIFO/persistent status, no unbounded threads |

## 11. Frontend manual acceptance

| ID | Ref | Priority | Scenario | Expected |
| --- | --- | --- | --- | --- |
| TEST-UI-001 | UI-CASE-001 | P0 | Create case and import JD/CV | End-to-end case preparation |
| TEST-UI-002 | UI-Q-001 | P0 | Generate/edit/approve 8 questions | Locked approved snapshot |
| TEST-UI-003 | UI-CAND-001 | P0 | Candidate completes 8-question assessment | Timer/autosave/submit |
| TEST-UI-004 | UI-CAND-002 | P0 | Candidate submits incomplete | Completion page; no result leak |
| TEST-UI-005 | UI-CAND-003 | P0 | Timer expires | Auto-submit and locked page |
| TEST-UI-006 | UI-SEC-001 | P0 | Candidate attempts browser back/devtools API | Committee data unavailable |
| TEST-UI-007 | UI-AI-001 | P0 | AI failure | Original answers visible to Committee; manual fallback |
| TEST-UI-008 | UI-LIVE-001 | P1 | Live notes/score/conflict flag | Records save and audit |
| TEST-UI-009 | UI-EVAL-001 | P0 | Draft/finalize/revise evaluation | Final immutable; revision versioned |
| TEST-UI-010 | UI-BACKUP-001 | P1 | Backup/export/delete confirmation | Safe confirmation and feedback |

## 12. Windows smoke test

1. Unpack portable bundle on clean Windows user profile.
2. Start using configured command.
3. Verify browser opens at 127.0.0.1:8787.
4. Verify directories/database/migration are created under LOCALAPPDATA\ClawCV.
5. Complete case → documents → questions → candidate → AI fake/manual → live → evaluation.
6. Close/restart app and verify data/task recovery.
7. Verify no Python installation, Node.js, Docker or database server is required.
8. Verify package checksum and no user data under install directory.

## 13. Regression checklist

- [ ] Server remains localhost-only.
- [ ] No runtime third-party dependency introduced.
- [ ] Migration version increments only with backup/review.
- [ ] Candidate API still cannot read Committee data.
- [ ] Answer lock after submit remains enforced.
- [ ] AI failure never deletes answer.
- [ ] AI rerun never overwrites prior result.
- [ ] PDF behavior remains fallback/optional extractor.
- [ ] No PII/secret enters logs/export.
- [ ] Final result still requires HĐCM.

## 14. Exit criteria

- All P0 automated tests pass.
- All P1 tests are executed or have an explicit accepted risk.
- No open security defect involving token, PII, path traversal, XSS or Candidate isolation.
- Migration/backup/restore evidence captured.
- Manual Windows smoke test passes on clean profile.
- Traceability matrix has no important requirement without test.
- Test report records commit/build/package version and environment.

## 15. Conflict / Assumption / Open Questions

### Conflict

- Technology requires unittest and no Node.js; frontend automated test is manual in MVP.
- Context has optional PDF input; tests treat native PDF parser as unsupported and cover fallback/pdftotext only.

### Assumption

- Fake provider is deterministic and fixtures are stored without real candidate PII.
- Performance targets are pilot targets, not hard SLA.
- Security test can use a controlled local process; it does not claim protection from a fully privileged Windows administrator.

### Open Questions / Backlog

- Browser automation framework after frontend build decision.
- Load test scale for multi-machine/server mode.
- Formal external penetration test.

## 0A. Offline HTML package acceptance

The following acceptance checks are required in addition to the existing Candidate Mode regression cases:

- Approved Question Set export returns a self-contained `candidate-html.v1` HTML file with no internal rubric/expected-evidence fields and records `QUESTION_SET_EXPORTED`.
- Candidate opens the file offline, submits a response, and the Committee imports it through the binary endpoint; blank answers are preserved as `NOT_ASSESSED`.
- Wrong case/set/version/fingerprint, draft package, malformed HTML, duplicate idempotency key, and response over 10 MiB are rejected without replacing an existing snapshot.
- Re-importing the same response with the same idempotency key is idempotent; a changed response creates a new immutable snapshot version.
- Committee auth/startup-token enforcement applies to both HTML endpoints; machine A needs no application endpoint.
- HTML-imported snapshots queue and complete `answer-evaluation.v2`; the provider payload contains sanitized JD/CV/question/answer data but never HTML/package bytes or internal tokens.
- Excel export/import remains a passing fallback path.

## 16. Acceptance criteria

1. Có test strategy, environment, fixtures và testcase format.
2. Có functional, API, DB, workflow, AI, document, security và UI tests.
3. Có Candidate isolation, autosave/submit, restart recovery và backup/restore.
4. Có performance, Windows smoke, manual acceptance, regression checklist và exit criteria.
5. Mỗi requirement quan trọng có testcase/reference.
