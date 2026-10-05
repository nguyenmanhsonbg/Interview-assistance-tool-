# Excel Question + Answer Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved local-first workflow that imports JD/CV, generates questions with Gemini, round-trips the questions and answers through one canonical `.xlsx` format, and evaluates the immutable imported snapshot with the refined AI contract.

**Architecture:** Add a standard-library-only OOXML workbook adapter and an Excel assessment application service. Imported workbooks become versioned immutable assessment snapshots, separate from legacy Candidate Mode attempts, so changed workbooks can create new versions without overwriting submitted answers or completed AI results. Extend the existing asynchronous AI task pipeline with snapshot references and `answer-evaluation.v2`, then expose binary export/import endpoints and a linear Committee UI while retaining historical tables and direct legacy service data.

**Tech Stack:** Python 3.10+ standard library; `zipfile`, `xml.etree.ElementTree`, `hashlib`, `sqlite3`; `http.server.ThreadingHTTPServer`; Vanilla JavaScript modules and `fetch()`; SQLite versioned migrations.

**Spec:** `docs/superpowers/specs/2026-10-05-excel-question-answer-flow-design.md`

## Global Constraints

- Runtime remains Python 3.10+ Standard Library only; no `openpyxl`, pandas, Node.js, ORM, web framework, or third-party runtime dependency.
- HTTP remains localhost-only with `http.server.ThreadingHTTPServer`; Committee mutations require startup token and Committee session.
- Every SQLite operation uses a fresh configured connection; migrations are transactional and applied in version order.
- JD/CV/Question/Answer content sent to Gemini is sanitized text only; raw workbook bytes, secrets, tokens, paths, and full provider URLs never enter logs, audit metadata, AI payloads, backup exports, or frontend responses.
- Imported question/answer snapshots and completed AI results are immutable; reruns create new task/result versions.
- The AI may provide evidence scores but never sets or persists an automatic hiring decision.
- All new behavior is implemented test-first: write a focused failing test, observe the expected failure, implement the minimum code, then run the focused and full unittest suites.

## Review Focus

- Zip/XML workbook bombs and malformed OOXML: reject before unbounded parsing; covered by Task 2 parser security tests.
- Formula, macro, external-link, and embedded-object cells: reject or treat as inert without execution; covered by Task 2 and Task 5 HTTP tests.
- Workbook IDs and row ownership: a valid workbook for another case or Question Set must be rejected without creating a snapshot; covered by Task 3.
- Re-import and changed-workbook idempotency: same key/same bytes returns the same snapshot, while changed bytes create a new immutable version; covered by Task 3.
- AI output/result compatibility: v2 evaluation must omit live-interview fields, preserve sanitized snapshot provenance, and leave legacy v1 results readable; covered by Task 4 and Task 7.

---

### Task 1: Add refined-flow persistence and snapshot repository

**Files:**
- Create: `migrations/002_excel_question_answer_flow.sql`
- Create: `app/repositories/assessment_snapshots.py`
- Modify: `app/domain/states.py`
- Test: `tests/test_excel_snapshot_repository.py`
- Modify: `tests/test_migrations.py`

**Interfaces:**
- Produces `AssessmentSnapshotRepository.create_imported_snapshot(connection, *, case_id, question_set_id, workbook_sha256, normalized_fingerprint, idempotency_key_hash, document_manifest, questions, answers) -> dict[str, Any]`, `get(snapshot_id) -> dict[str, Any]`, `find_by_idempotency(case_id, idempotency_key_hash) -> dict[str, Any] | None`, `current_for_case(case_id) -> dict[str, Any] | None`, and `payload(snapshot_id) -> dict[str, Any]`.
- Adds nullable `interview_cases.refined_flow_status` with the refined states `DRAFT`, `DOCUMENTS_READY`, `QUESTIONS_GENERATING`, `QUESTIONS_GENERATED`, `QUESTIONS_EXPORTED`, `ANSWERS_IMPORTED`, `AI_ANALYZING`, `AI_EVALUATED`, `QUESTION_GENERATION_FAILED`, and `AI_ANALYSIS_FAILED`; legacy `status` remains unchanged for historical Candidate Mode records.
- Adds `assessment_snapshots`, `assessment_snapshot_questions`, and `assessment_snapshot_answers` tables, including case/version uniqueness, workbook hash, normalized fingerprint, hashed idempotency key, document manifest JSON, immutable copied question fields, answer text hashes, and source `EXCEL_IMPORT`.
- Adds nullable `assessment_snapshot_id` references to `ai_tasks` and `ai_results`, preserving `assessment_attempt_id` for legacy records.

- [ ] **Step 1: Write failing migration/repository tests**

Add tests that apply migrations 001 and 002, assert the new columns/tables exist, create a snapshot with five rows, return the copied question edits and answer hashes, reject duplicate snapshot versions, and return the same snapshot for a duplicate idempotency hash.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m unittest tests.test_excel_snapshot_repository tests.test_migrations -v`

Expected: FAIL because migration 002 and `AssessmentSnapshotRepository` do not exist.

- [ ] **Step 3: Implement migration 002 and repository**

Use only parameterized SQL. Store imported questions and answers in snapshot tables rather than mutating `question_sets` or `questions`; keep `refined_flow_status` separate from legacy `interview_cases.status` so the old CHECK constraint and historical workflow remain readable. Return sanitized metadata only, never raw workbook bytes.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same unittest command.

Expected: PASS with all new repository/migration tests green and existing migration tests still green.

- [ ] **Step 5: Commit**

```bash
git add migrations/002_excel_question_answer_flow.sql app/domain/states.py app/repositories/assessment_snapshots.py tests/test_excel_snapshot_repository.py tests/test_migrations.py
git commit -m "feat: add immutable Excel assessment snapshots"
```

---

### Task 2: Implement the canonical `question-answer.v1.xlsx` codec

**Files:**
- Create: `app/infrastructure/excel_question_answer.py`
- Create: `tests/test_excel_question_answer.py`

**Interfaces:**
- Produces constants `WORKBOOK_FORMAT_VERSION`, `METADATA_FIELDS`, and `QUESTION_HEADERS`.
- Produces `export_question_answer_workbook(metadata: Mapping[str, str], questions: Sequence[Mapping[str, Any]]) -> bytes`.
- Produces `import_question_answer_workbook(raw: bytes) -> QuestionAnswerWorkbook`, where `QuestionAnswerWorkbook` exposes `metadata: dict[str, str]` and `questions: list[dict[str, Any]]`.
- Raises `ValidationError` for all contract or security violations, with no filesystem or network side effects.

- [ ] **Step 1: Write failing codec tests**

Cover exact two-sheet export, metadata rows, exact ordered headers, inline-string/numeric/boolean round-trip, Unicode and multiline text, missing/extra sheets, wrong version, duplicate metadata/IDs/orders, fewer than five or more than eight rows, invalid enum/rubric/boolean cells, `.xls`/macro archive signatures, formula cells, external links, embedded objects, XML entity declarations, oversized cell text, and oversized ZIP/uncompressed content.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_excel_question_answer -v`

Expected: FAIL because the codec module and contract constants do not exist.

- [ ] **Step 3: Implement standard-library OOXML export/import**

Create the minimal valid OOXML package with `metadata` and `questions` worksheets only. Use inline strings, explicit numeric and boolean cell types, bounded ZIP entries, path allow-listing, XML size limits, formula/macro/external-link/embedding rejection, exact headers, and strict field validation. Normalize blank `answer_text` plus `is_answered=false` as an unanswered row; do not infer a negative answer.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the same unittest command.

Expected: PASS, including round-trip semantic equality and safe rejection of every malformed/security case.

- [ ] **Step 5: Commit**

```bash
git add app/infrastructure/excel_question_answer.py tests/test_excel_question_answer.py
git commit -m "feat: add canonical question-answer workbook codec"
```

---

### Task 3: Add Excel export/import application service

**Files:**
- Create: `app/services/excel_assessment_service.py`
- Modify: `app/services/document_service.py`
- Modify: `app/services/question_service.py`
- Test: `tests/test_excel_assessment_service.py`

**Interfaces:**
- Consumes Task 1 repository and Task 2 codec.
- Produces `ExcelAssessmentService.export_question_set(case_id: str) -> ExportedWorkbook`, with `bytes`, `filename`, `content_type`, and `question_set_id`.
- Produces `ExcelAssessmentService.import_answers(case_id: str, raw: bytes, *, idempotency_key: str) -> dict[str, Any]`.
- Produces `ExcelAssessmentService.get_snapshot(case_id: str, snapshot_id: str | None = None) -> dict[str, Any]`.
- Produces `ExcelAssessmentService.snapshot_manifest(snapshot_id: str) -> dict[str, Any]` for the AI evaluation service.
- Adds small internal helpers to keep `refined_flow_status` synchronized when documents become ready, questions start/finish/fail generation, and a workbook is exported/imported; legacy `status` transitions remain intact.

- [ ] **Step 1: Write failing service tests**

Create a generated question set and confirmed JD/CV fixture. Assert export contains the case/set/version metadata and all question/rubric fields without candidate PII. Fill one answer and leave one blank, import it into the matching case, and assert an immutable snapshot with `NOT_ASSESSED` semantics. Assert edited Excel question text/rubric is stored in the snapshot but the generated Question Set is unchanged. Add wrong case/set/version, foreign question ID, inconsistent answer flag, duplicate idempotency key with changed bytes, and re-import idempotency tests.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_excel_assessment_service -v`

Expected: FAIL because the application service and refined-flow persistence hooks do not exist.

- [ ] **Step 3: Implement export/import service**

Export only a current `GENERATED` or `APPROVED` Question Set with 5–8 questions and duration 600–900 seconds. Import must match metadata against the case and exported Question Set version, validate each row against ownership and enums, preserve the workbook byte hash and normalized row fingerprint, hash the idempotency key, create a new snapshot for changed workbook bytes, and audit export/import without logging question/answer contents. A successful import sets the refined flow to `ANSWERS_IMPORTED`; it never edits the source Question Set.

- [ ] **Step 4: Run focused and regression tests**

Run: `python -m unittest tests.test_excel_assessment_service tests.test_documents tests.test_question_generation tests.test_questions -v`

Expected: PASS, including existing document/question behavior and new immutable snapshot behavior.

- [ ] **Step 5: Commit**

```bash
git add app/services/excel_assessment_service.py app/services/document_service.py app/services/question_service.py tests/test_excel_assessment_service.py
git commit -m "feat: add Excel assessment export and import flow"
```

---

### Task 4: Add snapshot evaluation and `answer-evaluation.v2`

**Files:**
- Create: `schemas/answer_evaluation.v2.schema.json`
- Create: `prompts/answer_evaluation_prompt_v2.md`
- Modify: `app/ai/schemas.py`
- Modify: `app/ai/prompts.py`
- Modify: `app/repositories/ai_tasks.py`
- Modify: `app/services/ai_task_service.py`
- Modify: `app/services/evaluation_service.py`
- Modify: `app/application.py`
- Modify: `tests/ai_fixtures.py`
- Create: `tests/test_refined_evaluation.py`
- Modify: `tests/test_ai_schemas.py`
- Modify: `tests/test_ai_tasks.py`

**Interfaces:**
- Consumes `ExcelAssessmentService.snapshot_manifest(snapshot_id)`.
- Produces `EvaluationService.request_snapshot(case_id: str, snapshot_id: str, *, idempotency_key: str, force_rerun: bool = False) -> dict[str, Any]`.
- Produces `EvaluationService.current_ai_result(case_id: str) -> dict[str, Any]`.
- `AITaskService.enqueue(..., assessment_snapshot_id: str | None = None, ...) -> dict[str, Any]` and task/result dictionaries expose `assessmentSnapshotId`.
- `answer-evaluation.v2` has only `perAnswerEvaluations`, `competencyEvaluations`, `strengths`, `gaps`, `conflicts`, `risks`, `confidence`, and `limitations`, plus the required `schemaVersion` and `operation`; it has no `interviewBrief` or `recommendedLiveQuestions`.

- [ ] **Step 1: Write failing v2 schema/provider tests**

Add a valid v2 fixture and tests that v2 validates, v1 remains readable, v2 rejects live-interview fields, and `NOT_ASSESSED` requires a null score. Add a snapshot evaluation test asserting the task manifest contains only references/hashes, provider payload contains sanitized JD/CV/question/answer text, and no raw workbook bytes or candidate full name.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_refined_evaluation tests.test_ai_schemas tests.test_ai_tasks -v`

Expected: FAIL because v2 schema/task snapshot references are not implemented.

- [ ] **Step 3: Implement v2 schema and task integration**

Select the configured version when validating AI output. Keep legacy `GENERATE_BRIEF`/v1 records readable, but make new `EVALUATE_ASSESSMENT` snapshot tasks use `answer-evaluation.v2` and the v2 prompt. Persist `assessment_snapshot_id` in tasks/results, update refined snapshot/case state on success/failure, create a new AI result version on rerun, and never materialize Interview Brief for a snapshot task. Keep provider input sanitized and document provenance bound to the snapshot.

- [ ] **Step 4: Run focused and regression AI tests**

Run: `python -m unittest tests.test_refined_evaluation tests.test_ai_schemas tests.test_ai_tasks tests.test_ai_evaluation tests.test_gemini_provider -v`

Expected: PASS with both new v2 snapshot evaluation and existing legacy provider/task tests green.

- [ ] **Step 5: Commit**

```bash
git add schemas/answer_evaluation.v2.schema.json prompts/answer_evaluation_prompt_v2.md app/ai/schemas.py app/ai/prompts.py app/repositories/ai_tasks.py app/services/ai_task_service.py app/services/evaluation_service.py app/application.py tests/ai_fixtures.py tests/test_refined_evaluation.py tests/test_ai_schemas.py tests/test_ai_tasks.py
git commit -m "feat: evaluate imported snapshots with schema v2"
```

---

### Task 5: Add binary HTTP transport and refined API endpoints

**Files:**
- Modify: `app/responses.py`
- Modify: `app/router.py`
- Modify: `app/server.py`
- Modify: `app/api.py`
- Test: `tests/test_server.py`
- Test: `tests/test_router.py`
- Modify: `tests/test_api_e2e.py`

**Interfaces:**
- `Request` gains `raw_body: bytes | None` and route body mode supports `json`, `binary`, and `none`.
- `Response` supports `raw_body: bytes | None` and content-disposition/content-type headers while preserving JSON envelopes and error handling.
- Adds routes:
  - `POST /api/v1/interview-cases/{case_id}/question-set/export` — Committee mutation, returns `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
  - `POST /api/v1/interview-cases/{case_id}/assessment-snapshots/import` — Committee mutation, accepts the same `.xlsx` bytes and `X-Idempotency-Key`.
  - `POST /api/v1/interview-cases/{case_id}/ai/evaluate` — accepts `snapshotId` and optional `forceRerun`.
  - `GET /api/v1/interview-cases/{case_id}/ai/evaluation` — read-only current AI result.
  - `GET /api/v1/interview-cases/{case_id}/assessment-snapshots/{snapshot_id}` — read-only imported snapshot summary.
- The active router no longer registers Candidate Mode, Interview Brief, live interview, or Committee Final Evaluation endpoints; their service/table data is retained for historical compatibility.

- [ ] **Step 1: Write failing transport/API tests**

Test binary response headers/body, binary upload content-type and size limits, JSON routes unchanged, missing Committee/startup authorization, export/import response contracts, task polling, read-only v2 result, and the complete HTTP workflow using a fake v2 provider. Assert removed active routes return 404 while old database rows remain readable through direct repositories.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_router tests.test_server tests.test_api_e2e -v`

Expected: FAIL because binary request/response support, refined endpoints, and new workflow are not implemented.

- [ ] **Step 3: Implement transport and endpoints**

Add route metadata for body mode, parse bounded binary bodies without JSON decoding, and write binary responses with `nosniff`, `no-store`, content type, content length, and a safe generated filename. Use the Excel service for export/import and the snapshot evaluation service for AI calls. Do not log or return workbook bytes in JSON. Keep old error mapping and security checks.

- [ ] **Step 4: Run focused and regression API tests**

Run: `python -m unittest tests.test_router tests.test_server tests.test_api_e2e tests.test_security tests.test_frontend_contract -v`

Expected: PASS, including the end-to-end JD/CV → question generation → Excel export → Excel import → v2 evaluation flow.

- [ ] **Step 5: Commit**

```bash
git add app/responses.py app/router.py app/server.py app/api.py tests/test_router.py tests/test_server.py tests/test_api_e2e.py
git commit -m "feat: expose Excel workflow over binary API"
```

---

### Task 6: Replace the active UI with the linear Excel workflow

**Files:**
- Modify: `web/js/api.js`
- Modify: `web/js/app.js`
- Modify: `web/js/store.js`
- Modify: `web/index.html`
- Modify: `tests/test_frontend_contract.py`

**Interfaces:**
- `apiDownload(path, options) -> Promise<{blob, response}>` handles binary export without attempting JSON parsing.
- `apiUpload(path, blob, options) -> Promise<any>` sends `.xlsx` bytes with Committee/startup headers and parses the JSON response.
- UI routes are limited to case list/new, documents, questions/export, answers import, AI evaluation, and read-only evaluation result.
- All user-controlled content is inserted with `textContent`/DOM APIs; no `innerHTML`, `eval`, or `new Function`.

- [ ] **Step 1: Write failing frontend contract tests**

Assert that the UI references export/import/evaluation snapshot endpoints, exposes a file input restricted to `.xlsx`, does not register Candidate Mode/Brief/Live/Final routes, and uses blob upload/download helpers.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `python -m unittest tests.test_frontend_contract -v`

Expected: FAIL because the current UI still registers and exposes Candidate Mode, Check-in, Brief, Live Interview, and Final Evaluation.

- [ ] **Step 3: Implement linear case workspace**

Remove legacy navigation and route registration. Keep JD/CV manual import/confirm, question generation and manual fallback, add an export button, add `.xlsx` import with file-size/type validation, poll the evaluation task, and render the v2 result fields read-only. Store only case/snapshot IDs and auth capabilities in client state.

- [ ] **Step 4: Run frontend contract and API regression tests**

Run: `python -m unittest tests.test_frontend_contract tests.test_api_e2e tests.test_security -v`

Expected: PASS with no unsafe DOM rendering and no removed active routes in the UI.

- [ ] **Step 5: Commit**

```bash
git add web/js/api.js web/js/app.js web/js/store.js web/index.html tests/test_frontend_contract.py
git commit -m "feat: make Excel assessment flow the active UI"
```

---

### Task 7: Full verification, documentation, and packaging smoke

**Files:**
- Modify: `README.md`
- Modify: `README.txt`
- Modify: `documents/28_implementation_task_breakdown.md` only if implementation traceability needs a status note
- Create: `tests/test_refined_flow_acceptance.py` if the E2E coverage is not sufficient after Tasks 5–6

- [ ] **Step 1: Write any missing acceptance regression test first**

Add only tests for gaps discovered against the approved design: full flow, blank answers, changed workbook versioning, sanitization, and removed active routes. Run each new test and observe RED before implementation.

- [ ] **Step 2: Update operator documentation**

Document that Committee runs the local server, confirms JD/CV, generates questions, exports the canonical workbook, fills `answer_text`/updates `is_answered`, imports the same `.xlsx`, then starts evaluation; document that no API key/workbook bytes are exposed in logs and that manual fallback remains available.

- [ ] **Step 3: Run the complete verification suite**

Run: `python -m unittest discover -s tests -v`

Expected: PASS with zero failures/errors.

- [ ] **Step 4: Run packaging and portable smoke**

Run: `powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1` and then the repository's portable smoke command defined by the script.

Expected: package command exits 0; smoke confirms startup, health/bootstrap, migration, and refined route availability without real candidate data or secrets.

- [ ] **Step 5: Inspect scope and commit**

Run: `git diff --check` and `git status --short`; confirm only scoped implementation/docs/tests changed and user-provided `.env`, `documents/gemini-api-specification.md`, and `documents/cv-ai-parsing-flow-specification.md` are not staged.

```bash
git add README.md README.txt tests/test_refined_flow_acceptance.py
git commit -m "docs: document Excel assessment workflow"
```

- [ ] **Step 6: Final verification**

Run: `python -m unittest discover -s tests -v`

Expected: PASS; report exact test count, package/smoke result, changed files, and remaining risk.

## Plan self-review

- Spec coverage: all approved design sections map to Tasks 1–7: canonical workbook/round trip (2–3), immutable snapshot and idempotency (1, 3), v2 AI/sanitization (4), binary API/security (5), linear UI/removal (6), acceptance/backup-compatible packaging (7).
- Compatibility: migration 002 is additive; old Candidate Mode tables/results remain readable, while active routes/UI are removed as required.
- Interface consistency: Task 1 repository contracts feed Task 3; Task 2 codec feeds Task 3; Task 3 snapshot manifest feeds Task 4; Task 4 request/result contracts feed Task 5; Task 5 endpoints feed Task 6.
- TDD coverage: every task starts with named failing tests and a focused command before production code.
- Review focus coverage: all five failure classes are explicitly assigned to tests in Tasks 2–5.
- Known design ruling: refined state is stored in a separate `refined_flow_status` column because migration 001's legacy `status` CHECK is applied and existing historical workflows must remain readable; the API/UI expose the refined state where relevant.
