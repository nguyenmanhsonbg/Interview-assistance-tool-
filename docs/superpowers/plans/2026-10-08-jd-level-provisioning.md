# JD-derived Interview Level Provisioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove manual Level entry from interview-case creation, extract the level from the confirmed JD through a versioned AI task, and block question generation until the extracted level is ready.

**Architecture:** Keep `InterviewCase` creation early in the existing flow, but make `Job.targetLevel` temporarily nullable with explicit provisioning status. Confirmed JD text starts an idempotent `EXTRACT_JOB_LEVEL` task; its application-service materialization updates the Job only after verifying the current JD fingerprint. Existing Jobs with a level remain `READY` and continue through the current question/evaluation flow.

**Tech Stack:** Python 3.10+ standard library, `http.server`, SQLite migrations, `urllib.request`, `threading`, JSON Schema subset, HTML5/CSS3/Vanilla JavaScript ES Modules, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-08-jd-level-provisioning-design.md`

## Global Constraints

- Runtime remains Python 3.10+ Standard Library only; do not add Flask, ORM, requests, Node runtime, or a server listener.
- SQLite keeps WAL, foreign keys per connection, busy timeout, parameterized SQL, and versioned transactional migrations.
- AI receives sanitized, length-limited JD text only; never raw files, secrets, tokens, full CV text, or raw provider payloads in logs.
- AI provider parses responses only; application services own task state, Job mutation, workflow guards, and audit events.
- Existing valid Jobs and completed AI results are immutable/versioned; reruns never overwrite a completed result or a newer JD-derived level.
- Frontend does not write workflow state directly and must refetch after mutations.
- Preserve the current offline/local-first MVP and localhost security model.

## Review Focus

- A new case omits `targetLevel` but still creates a valid pending Job and can reach JD import.
- A stale extraction task cannot update the Job after the current JD version changes.
- Duplicate confirm/retry requests reuse the same task for the same JD fingerprint.
- Provider, malformed-schema, and worker-restart failures leave the Job level unchanged and expose a safe retry state.
- Question generation cannot enqueue an AI task while the Job level is pending, extracting, or failed, while legacy ready Jobs remain unaffected.

### Task 1: Add pending Job-level persistence and domain projection

**Files:**
- Create: `migrations/010_jd_level_provisioning.sql`
- Modify: `app/repositories/jobs.py`
- Modify: `app/services/case_service.py`
- Modify: `app/repositories/interview_cases.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_job_candidate_service.py`
- Modify: `tests/test_case_service.py`

**Interfaces:**
- `CaseService.create_job(job_code: str | None, position_title: str, target_level: str | None) -> dict[str, Any]` accepts an omitted level and creates `PENDING`; a non-empty level creates `READY` with legacy provenance.
- Job projections expose `targetLevel`, `targetLevelStatus`, `targetLevelSource`, and `targetLevelConfidence`.
- A repository update primitive will later accept a job ID, expected JD fingerprint, extracted level, confidence, and source in one transaction; this task establishes the columns and projection needed by that primitive.

- [ ] **Step 1: Write failing migration and service tests**
  - Assert migration 010 is applied after migration 009.
  - Assert existing non-empty Jobs become `READY`/`LEGACY`.
  - Assert `create_job(..., None)` returns `PENDING` with a null level.
  - Assert invalid status/source/confidence values are rejected by the database contract.

- [ ] **Step 2: Run focused tests and verify the expected failure**

  Run: `\.\python\python.exe -m unittest tests.test_migrations tests.test_job_candidate_service tests.test_case_service -v`

  Expected: FAIL because migration 010, nullable Job level, and the new projection fields do not exist.

- [ ] **Step 3: Implement migration 010 and domain/repository changes**
  - Rebuild the SQLite `jobs` table transactionally because the existing `NOT NULL` constraint must be changed without editing an applied migration.
  - Add `target_level_status`, `target_level_source`, and `target_level_confidence` with the exact states and confidence range from the design.
  - Extend the same migration to rebuild the AI task/result type checks for `EXTRACT_JOB_LEVEL` and `JOB_LEVEL_EXTRACTION`, preserving all existing rows and indexes.
  - Preserve IDs, timestamps, foreign-key references, and existing data.
  - Update `JobRepository.insert`, `CaseService.create_job`, and all Job/case projections without changing callers that still pass a level.

- [ ] **Step 4: Run focused tests and verify they pass**

  Run: `\.\python\python.exe -m unittest tests.test_migrations tests.test_job_candidate_service tests.test_case_service -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add migrations/010_jd_level_provisioning.sql app/repositories/jobs.py app/services/case_service.py app/repositories/interview_cases.py tests/test_migrations.py tests/test_job_candidate_service.py tests/test_case_service.py
  git commit -m "feat: support pending JD-derived job levels"
  ```

### Task 2: Add the fixed AI level-extraction contract

**Files:**
- Create: `prompts/job_level_extraction_prompt.md`
- Create: `schemas/job-level-extraction.v1.schema.json`
- Modify: `app/ai/provider.py`
- Modify: `app/ai/prompts.py`
- Modify: `app/ai/schemas.py`
- Modify: `app/ai/gemini_provider.py`
- Modify: `app/ai/http_provider.py`
- Modify: `tests/test_ai_schemas.py`
- Modify: `tests/test_gemini_provider.py`
- Modify: `tests/test_ai_provider.py`

**Interfaces:**
- `AIProvider.extract_job_level(payload: dict[str, Any]) -> dict[str, Any]`.
- Operation name: `EXTRACT_JOB_LEVEL`.
- Result type: `JOB_LEVEL_EXTRACTION`.
- Prompt key: `job_level_extraction`.
- Schema version: `job-level-extraction.v1`.
- Valid output contains `schemaVersion`, `targetLevel`, `confidence`, and `evidence`; evidence is bounded text, not a hiring decision.

- [ ] **Step 1: Write failing schema/provider contract tests**
  - Valid output is accepted.
  - Missing fields, non-string/empty level, confidence outside `0..1`, oversized evidence, and extra unsupported fields are rejected.
  - Gemini request metadata uses `EXTRACT_JOB_LEVEL`, the new prompt key, and the new response schema.
  - Provider failures remain sanitized and do not leak JD content or API keys.

- [ ] **Step 2: Run focused tests and verify the expected failure**

  Run: `\.\python\python.exe -m unittest tests.test_ai_schemas tests.test_gemini_provider tests.test_ai_provider -v`

  Expected: FAIL because the operation, schema, prompt, and provider method are missing.

- [ ] **Step 3: Implement the fixed contract**
  - Add the prompt instruction to extract only the level supported by the JD and return JSON only.
  - Add the JSON schema and SchemaRegistry mapping/validation.
  - Add provider protocol and HTTP/Gemini operation routing using existing retry/model-rotation behavior.
  - Keep JD text inside the existing untrusted-input delimiters.

- [ ] **Step 4: Run focused tests and verify they pass**

  Run: `\.\python\python.exe -m unittest tests.test_ai_schemas tests.test_gemini_provider tests.test_ai_provider -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add prompts/job_level_extraction_prompt.md schemas/job-level-extraction.v1.schema.json app/ai/provider.py app/ai/prompts.py app/ai/schemas.py app/ai/gemini_provider.py app/ai/http_provider.py tests/test_ai_schemas.py tests/test_gemini_provider.py tests/test_ai_provider.py
  git commit -m "feat: add JD level extraction AI contract"
  ```

### Task 3: Implement task orchestration, materialization, and recovery

**Files:**
- Create: `app/services/job_level_service.py`
- Modify: `app/services/ai_task_service.py`
- Modify: `app/repositories/ai_tasks.py`
- Modify: `app/application.py`
- Modify: `app/api.py`
- Modify: `tests/test_ai_tasks.py`
- Create: `tests/test_job_level_service.py`
- Modify: `tests/test_documents.py`

**Interfaces:**
- `JobLevelService.request_for_confirmed_jd(case_id: str, *, retry: bool = False) -> dict[str, Any]` enqueues/reuses one task for the current JD fingerprint.
- `JobLevelService.process(task_id: str, provider: AIProvider) -> dict[str, Any]` calls the generic AI task service and materializes a valid result.
- `JobLevelService.provider_payload(task: dict[str, Any]) -> dict[str, Any]` returns only the job identifiers, JD provenance, and sanitized text required by the prompt.
- A Committee-only retry request reuses the same service with a new idempotency key only when the previous task is terminal and the JD fingerprint is still current.

- [ ] **Step 1: Write failing orchestration and recovery tests**
  - Confirmed JD creates one extraction task and duplicate confirmation is idempotent.
  - Task manifest contains the current JD ID/version/hash and sanitized text, with no raw file path or CV text.
  - Successful output updates the Job to `READY` in one transaction and records audit metadata.
  - Stale JD output is rejected without changing the Job.
  - Provider/schema failure sets level status `FAILED` without a fake/default level.
  - Interrupted task follows existing recovery and retry behavior.

- [ ] **Step 2: Run focused tests and verify the expected failure**

  Run: `\.\python\python.exe -m unittest tests.test_job_level_service tests.test_ai_tasks tests.test_documents -v`

  Expected: FAIL because the task type, service, materialization, and confirm trigger are not implemented.

- [ ] **Step 3: Implement task orchestration and materialization**
  - Add `_TASK_CONFIG` and the `AITaskService.process` provider branch for `EXTRACT_JOB_LEVEL`.
  - Add successful result materialization that checks current JD ID/version/content hash and mutable case state before updating the Job.
  - Trigger extraction after JD confirmation and add the Committee retry service path.
  - Keep terminal failures from changing the case to an unrelated question/AI workflow state.
  - Wire the worker/application dispatcher to process the new task type.

- [ ] **Step 4: Run focused tests and verify they pass**

  Run: `\.\python\python.exe -m unittest tests.test_job_level_service tests.test_ai_tasks tests.test_documents -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/services/job_level_service.py app/services/ai_task_service.py app/repositories/ai_tasks.py app/application.py app/api.py tests/test_ai_tasks.py tests/test_job_level_service.py tests/test_documents.py
  git commit -m "feat: extract and materialize job level from JD"
  ```

### Task 4: Add API guards and update the question-generation boundary

**Files:**
- Modify: `app/api.py`
- Modify: `app/services/question_generation_service.py`
- Modify: `tests/test_api_e2e.py`
- Modify: `tests/test_question_generation.py`

**Interfaces:**
- `POST /api/v1/interview-cases/{caseId}/job-level/extract` is Committee-only and supports retry of a terminal failed extraction for the current JD.
- `GET case` includes the safe Job level provisioning projection.
- Question generation returns a domain validation error and creates no AI task unless `targetLevelStatus == READY`.

- [ ] **Step 1: Write failing API/guard tests**
  - Job creation without `targetLevel` succeeds with pending status.
  - Confirmed JD exposes/reuses an extraction task.
  - Retry is rejected for locked cases, stale/non-current JD, or an active task.
  - Question generation while level is not ready returns the expected error and leaves task count unchanged.
  - Legacy Job with `READY` level follows the existing happy path.

- [ ] **Step 2: Run focused tests and verify the expected failure**

  Run: `\.\python\python.exe -m unittest tests.test_api_e2e tests.test_question_generation -v`

  Expected: FAIL because the endpoint and level guard are absent.

- [ ] **Step 3: Implement the API and workflow guards**
  - Register the new route with Committee capability and startup/session protections.
  - Return safe task/status data only.
  - Add the backend guard before question task creation and before any state transition to `QUESTIONS_GENERATING`.
  - Preserve existing error envelopes and request IDs.

- [ ] **Step 4: Run focused tests and verify they pass**

  Run: `\.\python\python.exe -m unittest tests.test_api_e2e tests.test_question_generation -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add app/api.py app/services/question_generation_service.py tests/test_api_e2e.py tests/test_question_generation.py
  git commit -m "feat: guard question generation on JD level readiness"
  ```

### Task 5: Refine the create-case and JD/CV UI

**Files:**
- Modify: `web/js/app.js`
- Modify: `tests/test_frontend_contract.py`

**Interfaces:**
- `/cases/new` submits candidate, position title, and Lead only; no `targetLevel` field, draft-key component, or request property remains.
- Documents screen consumes `case.job.targetLevelStatus` and the extraction task projection, uses existing `resumeTask`/polling behavior, and refetches case state after completion.
- Questions screen does not enable generation until the safe case projection reports `READY`.

- [ ] **Step 1: Write failing frontend contract tests**
  - Assert the create-case form does not render `Level`/`targetLevel` or send it in the Job request.
  - Assert the JD screen contains pending/extracting/failed/ready copy and the retry route/action.
  - Assert the questions screen checks `targetLevelStatus === "READY"` before generating.
  - Assert no client code directly changes Job level or case workflow state.

- [ ] **Step 2: Run the focused frontend test and verify the expected failure**

  Run: `\.\python\python.exe -m unittest tests.test_frontend_contract -v`

  Expected: FAIL because the current form still renders and submits `targetLevel` and the UI has no extraction status.

- [ ] **Step 3: Implement the UI changes**
  - Remove the Level field and related draft-key/request references from `renderNewCase`.
  - Add a compact JD level extraction progress/status block to the JD & CV screen.
  - Show `Đang xác định level từ JD` until ready, show safe extracted level when ready, and expose retry on failure.
  - Keep the existing case header and question controls responsive to refetched backend state.
  - Use `textContent`/existing safe DOM helpers for all provider-derived values.

- [ ] **Step 4: Run frontend and syntax checks**

  Run: `\.\python\python.exe -m unittest tests.test_frontend_contract -v`
  Run: `node --check web/js/app.js`
  Run: `git diff --check`

  Expected: PASS with no syntax or whitespace errors.

- [ ] **Step 5: Commit**

  ```bash
  git add web/js/app.js tests/test_frontend_contract.py
  git commit -m "refine: derive interview level from JD"
  ```

### Task 6: Full verification and handoff

**Files:**
- Modify: only files required by failed tests or review findings from Tasks 1–5.

- [ ] **Step 1: Run the complete backend/frontend suite**

  Run: `\.\python\python.exe -m unittest discover -s tests -v`

  Expected: all tests pass, including migration, API, AI boundary, stale-task, retry, and frontend contract coverage.

- [ ] **Step 2: Inspect the final scoped diff**

  Run: `git diff --check`, `git status --short`, and `git diff --stat`.

  Confirm no secrets, candidate data, raw JD/CV fixtures, unrelated user changes, or untracked plan/spec files are staged.

- [ ] **Step 3: Run the portable smoke check if packaging paths changed**

  Run: `powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1` only if the implementation changes packaging/runtime asset discovery; otherwise record that packaging was not affected.

- [ ] **Step 4: Report evidence**

  Report test command/result, migrations/API/UI files changed, the pending/failed recovery behavior, and any remaining risk around AI level inference.
