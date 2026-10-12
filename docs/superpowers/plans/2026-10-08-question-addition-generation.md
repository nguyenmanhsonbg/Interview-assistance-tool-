# Question Addition Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proposal-first workflow that lets Committee members generate and approve new questions from each Question Set group using either a user prompt or automatic group-based generation.

**Architecture:** Keep the existing localhost/background-AI pipeline and create a dedicated `QuestionAdditionService` and repository instead of overloading the existing per-question variant workflow. A generation task returns a validated `QUESTION_ADDITION` proposal; only an explicit atomic apply operation inserts a new question at the end of the draft Question Set. Expand the domain and candidate HTML limits from exactly nine to 9–30 only for the editable/approved Question Set flow; initial AI generation and the legacy Excel contract remain nine-question-only.

**Tech Stack:** Python 3.10+ standard library, `http.server`, `urllib`, SQLite versioned migrations, vanilla JavaScript ES Modules, HTML/CSS, `unittest`, existing Gemini/HTTP providers and one-worker task queue.

**Spec:** `docs/superpowers/specs/2026-10-08-question-addition-generation-design.md`

## Global Constraints

- Preserve the local-first architecture: bind only `127.0.0.1`, use `http.server.ThreadingHTTPServer`, SQLite and vanilla JavaScript.
- Runtime dependencies remain Python Standard Library only; do not add Flask, ORM, Node/NPM, frontend frameworks, or a public listener.
- Keep the layer rule: HTTP handler → controller/service → repository/infrastructure; no SQL in handlers and no workflow state changes in AI providers.
- Use one SQLite connection per operation/thread, parameterized SQL, foreign keys/WAL/busy timeout and append-only migrations.
- Initial AI Question Set generation remains exactly 9 questions with `FOUNDATION/APPLICATION/DEEP_DIVE = 3/4/2`.
- Added Question Sets may contain 9–30 questions; `displayOrder` must be contiguous and new questions append at `MAX(display_order)+1`.
- Only `DRAFT` and `GENERATED` Question Sets can request/apply/discard additions; `APPROVED` and assessment-started cases are locked server-side.
- AI output is a proposal only; it must never insert/update `questions`, approve a Question Set, or decide PASS/FAIL.
- Candidate HTML is the supported transfer path; increase its maximum question count to 30. Do not expand Excel fallback/export beyond its existing nine-question contract.
- Send only sanitized JD/CV/question context to AI. Never send raw files, paths, answers, tokens, API keys or raw provider payloads.
- Treat Committee prompt text as untrusted input; trim and enforce `MAX_ADDITION_PROMPT_CHARS = 2000` before creating a task.
- Never render untrusted question/prompt/AI content with `innerHTML`, `eval` or `new Function`.
- Keep human-readable generated content in Vietnamese; keep field names, enum values and status values unchanged.
- Preserve idempotency, retry/recovery, audit logging, candidate isolation and existing response/error envelopes.
- Preserve the user’s uncommitted changes in `documents/30_interview_workspace_ui_implementation_specification.md` and the existing question-variant plan; do not stage unrelated files.

## Review Focus

1. Applying a proposal after another Question Set change or concurrent apply must fail atomically and leave the source Question Set unchanged. Test in Task 4.
2. A provider output with the wrong `questionSetId`, target category, source kind, enum or unknown field must create no proposal. Test in Task 2 and Task 3.
3. Repeating an idempotency key must return the original addition task, while reusing it with different category/prompt/input must return conflict. Test in Task 3 and Task 5.
4. Question Sets with 10–30 questions must approve and export/import through candidate HTML without truncation; 31 must be rejected. Test in Task 1 and Task 7.
5. Empty groups, refreshes and locked states must preserve group actions, proposal progress and selected-question focus without creating duplicate tasks. Test in Task 6.

## File Map

- `migrations/009_question_addition_generation.sql`: add addition-specific AI task/result scope and proposal persistence.
- `app/domain/rules.py`: shared `MAX_QUESTION_SET_QUESTIONS` and question-set count/category rules.
- `app/services/question_service.py`: separate strict initial-generation validation from expanded editable/approval validation.
- `app/infrastructure/html_candidate_package.py`: increase candidate package maximum from 9 to 30.
- `app/ai/schemas.py`, `schemas/question-addition.v1.schema.json`: validate the new AI contract and trusted identity/category context.
- `app/ai/provider.py`, `app/ai/http_provider.py`, `app/ai/gemini_provider.py`, `app/application.py`: expose and dispatch the new AI operation.
- `app/services/ai_task_service.py`, `app/repositories/ai_tasks.py`: register task/result type and target-category version scope.
- `app/repositories/question_additions.py`: persist and serialize proposal lifecycle.
- `app/services/question_addition_service.py`: request, process, preview, discard and atomic apply behavior.
- `app/api.py`: expose secured group-level addition endpoints.
- `prompts/question_addition_generation_prompt.md`: fixed Vietnamese question-addition prompt contract.
- `web/js/app.js`, `web/css/layout.css`: group add buttons, mode popup, prompt modal, task progress and proposal preview.
- `documents/20_*.md` through `documents/30_*.md`: synchronize governing specifications without overwriting existing user refinements.
- `tests/test_migrations.py`, `tests/test_questions.py`, `tests/test_html_candidate_package.py`, `tests/test_ai_schemas.py`, `tests/test_gemini_provider.py`, `tests/test_ai_tasks.py`, `tests/test_question_additions.py`, `tests/test_api_e2e.py`, `tests/test_frontend_contract.py`: focused and regression coverage.

---

### Task 1: Synchronize specifications, migration and expanded Question Set rules

**Files:**

- Modify: `documents/20_domain_and_database_specification.md`
- Modify: `documents/21_workflow_state_machine.md`
- Modify: `documents/22_ai_assessment_specification.md`
- Modify: `documents/23_api_contract_specification.md`
- Modify: `documents/24_frontend_ui_specification.md`
- Modify: `documents/25_security_and_audit_specification.md`
- Modify: `documents/27_test_and_acceptance_specification.md`
- Modify: `documents/28_implementation_task_breakdown.md`
- Modify: `documents/30_interview_workspace_ui_implementation_specification.md` only in the relevant question-set sections, preserving current user edits
- Create: `migrations/009_question_addition_generation.sql`
- Modify: `app/domain/rules.py`
- Modify: `app/services/question_service.py`
- Modify: `app/infrastructure/html_candidate_package.py`
- Test: `tests/test_migrations.py`
- Test: `tests/test_questions.py`
- Test: `tests/test_html_candidate_package.py`

**Interfaces:**

- Produce `MAX_QUESTION_SET_QUESTIONS = 30` and `MAX_ADDITION_PROMPT_CHARS = 2000` constants in the shared/domain boundary used by services and tests.
- Change `_validate_questions(questions, *, allow_expanded: bool = False) -> list[dict[str, Any]]`; default `False` preserves the initial 9-question/3-4-2 contract, while editable/apply/approve paths pass `True` for 9–30 validation.
- Migration adds nullable `target_question_category` to `ai_tasks` and `ai_results`, addition-aware version indexes, and `question_addition_proposals` with checked `target_category`, `mode`, `status`, source fingerprint and nullable `applied_question_id`.

- [ ] Write failing tests proving initial AI/manual materialization still rejects non-nine/incorrect 3-4-2 sets, while editable Question Sets accept 10 and 30 questions and reject 8/31/non-contiguous orders.
- [ ] Write failing tests proving approval accepts 9–30 valid questions and rejects 31, while candidate HTML export/import accepts 30 and rejects 31.
- [ ] Write migration tests for a fresh database and upgrade from schema version 008: new columns/table/indexes/checks exist, existing AI task/result rows survive, and rerunning migrations is idempotent.
- [ ] Add the shared constants and the expanded validation branch. Keep initial generation calls strict; route `update_draft`, approval validation and future addition apply through the expanded branch.
- [ ] Keep source kinds, categories, question types, difficulty, rubric and required-field validation explicit at the application boundary; do not rely on frontend controls.
- [ ] Update candidate HTML `MAX_QUESTIONS` from 9 to 30 while keeping contiguous order, manifest count and fingerprint checks.
- [ ] Add migration 009 without editing migrations 001–008. Rebuild tables only if SQLite constraints require it, and preserve all existing rows/index semantics.
- [ ] Synchronize the governing documents with the approved design: 9–30 lifecycle, task/result types, API routes, audit actions, 2,000-character prompt limit, candidate HTML limit and Excel out-of-scope rule.
- [ ] Run `python -m unittest tests.test_migrations tests.test_questions tests.test_html_candidate_package -v`; expected result: all focused tests pass.
- [ ] Run `git diff --check` and inspect that only the intended specification/migration/domain/package/test files are staged.
- [ ] Commit with `feat: support expanded question sets for additions`.

### Task 2: Add the question-addition AI schema, prompt and provider operation

**Files:**

- Create: `schemas/question-addition.v1.schema.json`
- Create: `prompts/question_addition_generation_prompt.md`
- Modify: `app/ai/schemas.py`
- Modify: `app/ai/provider.py`
- Modify: `app/ai/http_provider.py`
- Modify: `app/ai/gemini_provider.py`
- Modify: `app/ai/prompts.py` if prompt catalog registration/version behavior requires it
- Test: `tests/test_ai_schemas.py`
- Test: `tests/test_gemini_provider.py`
- Test: `tests/test_ai_provider.py` if the provider contract has a dedicated test module

**Interfaces:**

- Add `AIProvider.generate_question_addition(payload: dict[str, Any]) -> dict[str, Any]`.
- Use operation `GENERATE_QUESTION_ADDITION`, result type `QUESTION_ADDITION`, prompt key `question_addition_generation`, schema `question-addition.v1`.
- Add `validate_question_addition(payload, *, question_set_id: str | None = None, target_category: str | None = None) -> dict[str, Any]` or the equivalent `SchemaRegistry` context validation.
- Output contains `schemaVersion`, `operation`, `mode`, `questionSetId`, `targetCategory`, `question`, `confidence`, and `limitations`; `question` contains full new-question content but no ID/display order.

- [ ] Write failing schema tests for a valid `USER_PROMPT`/`AUTO_GROUP` proposal, blank/invalid mode, wrong identity/category, invalid source-kind mapping, unsupported enum, missing rubric score and unknown fields.
- [ ] Create the strict JSON schema with bounded text fields, fixed operation/version/mode enums, question fields, rubric score0–score4 and confidence/limitations bounds.
- [ ] Extend `SchemaRegistry` so the new operation validates both structural schema and target-category/source-kind rules. `FOUNDATION` only accepts `STANDARDIZED`, `APPLICATION` only `SITUATIONAL`, and `DEEP_DIVE` accepts `CV_VERIFICATION` or `GAP_CONFLICT`.
- [ ] Write the fixed prompt: return one JSON object only, write human-readable fields in Vietnamese, use the trusted group/category, avoid duplicate existing questions, and never change workflow/decision authority.
- [ ] Extend the generic HTTP provider operation map and Gemini operation/temperature/response-schema map. Preserve existing retry, timeout, response-size and redaction behavior.
- [ ] Add the unavailable-provider method in `app/application.py` and update provider test doubles with a deterministic addition response.
- [ ] Run `python -m unittest tests.test_ai_schemas tests.test_gemini_provider tests.test_ai_provider -v`; expected result: new valid fixtures pass, all malformed fixtures fail at schema validation, and existing operations remain green.
- [ ] Commit with `feat: add question addition ai contract`.

### Task 3: Implement addition task persistence and background orchestration

**Files:**

- Create: `app/repositories/question_additions.py`
- Create: `app/services/question_addition_service.py`
- Modify: `app/repositories/ai_tasks.py`
- Modify: `app/services/ai_task_service.py`
- Modify: `app/application.py`
- Test: `tests/test_ai_tasks.py`
- Create: `tests/test_question_additions.py`

**Interfaces:**

- `QuestionAdditionService.request_addition(case_id: str, question_set_id: str, target_category: str, mode: str, prompt: str | None, idempotency_key: str) -> dict[str, Any]` returns the existing task envelope with `id`, `taskType`, `targetQuestionCategory`, `status`, and safe metadata.
- `QuestionAdditionService.process(task_id: str, provider: AIProvider) -> dict[str, Any]` materializes a validated `PROPOSED` addition without changing `questions`.
- `QuestionAdditionService.get_proposal(case_id: str, question_set_id: str, proposal_id: str) -> dict[str, Any]` and `list_active_proposals(case_id: str, question_set_id: str, target_category: str | None) -> list[dict[str, Any]]` return safe previews.
- `QuestionAdditionService.discard_proposal(case_id: str, question_set_id: str, proposal_id: str) -> dict[str, Any]` is an idempotent status transition.
- Repository methods include `create_proposal_from_result`, `get_proposal`, `list_active_proposals`, `mark_discarded`, and `mark_applied` with case/Question Set/category guards.

- [ ] Write failing service tests for valid `USER_PROMPT`, valid `AUTO_GROUP`, blank/overlong prompt rejection, invalid category/mode, locked Question Set, assessment-started case and missing Question Set.
- [ ] Write failing repository/task tests for target-category persistence, result version scope by Question Set/category, idempotent repeated requests and conflict on same key with different input.
- [ ] Add `GENERATE_QUESTION_ADDITION` to `_TASK_CONFIG`, pass `target_question_category` through `AITaskService.enqueue`, and make `AITaskRepository.complete` scope `QUESTION_ADDITION` versions by Question Set/category without disturbing `QUESTION_GENERATION`, `QUESTION_VARIANT` or evaluation uniqueness.
- [ ] Build `QuestionAdditionService.request_addition`: normalize mode/category/prompt, enforce 2,000 characters, load current draft Question Set and sanitized current documents/questions, compute a SHA-256 source fingerprint, create the task manifest and audit request event.
- [ ] Build `provider_payload` with sanitized JD/CV text, target category, mode, prompt and safe summaries of existing questions. Do not include answers, local paths, secrets or raw file contents.
- [ ] Build `process`: call `AITaskService.process` with `generate_question_addition`, validate trusted identity/category/source mapping, create one proposal from the completed AI result, and write generated/failed audit events. A completed AI result without a proposal must surface as materialization failure, not as a silently successful UI state.
- [ ] Register the service in `_TaskProcessor` and ensure startup recovery resubmits addition tasks through the existing worker.
- [ ] Run `python -m unittest tests.test_ai_tasks tests.test_question_additions -v`; expected result: proposal creation, idempotency, retry/recovery, provider failure and schema failure tests pass without question mutation.
- [ ] Commit with `feat: orchestrate question addition proposals`.

### Task 4: Implement atomic apply/discard and expanded question materialization

**Files:**

- Modify: `app/services/question_addition_service.py`
- Modify: `app/services/question_service.py`
- Modify: `app/repositories/question_additions.py`
- Modify: `app/repositories/questions.py` only if a transaction-safe insert/serialization helper is needed
- Modify: `app/services/audit_service.py` only if the existing audit helper needs a typed action registration
- Test: `tests/test_question_additions.py`
- Test: `tests/test_questions.py`
- Test: `tests/test_audit_logging.py`

**Interfaces:**

- `QuestionAdditionService.apply_proposal(case_id: str, question_set_id: str, proposal_id: str, expected_question_set_updated_at: str, expected_source_fingerprint: str) -> dict[str, Any]` returns the inserted question and applied proposal metadata.
- `QuestionAdditionService.discard_proposal(case_id: str, question_set_id: str, proposal_id: str) -> dict[str, Any]` returns the final proposal metadata and never inserts a question.
- The inserted question keeps the validated AI fields, receives a new UUID, and receives `displayOrder = max(existing displayOrder) + 1`.

- [ ] Write failing tests for applying a valid proposal to produce exactly one new question, preserve all nine existing question IDs/fields/orders, append order 10, and mark the proposal `APPLIED` with `appliedQuestionId`.
- [ ] Write failing tests for 30-question success and 31-question rejection, invalid AI payload, stale updated-at/fingerprint, wrong case/Question Set, proposal already applied/discarded, approved set, assessment-started case and concurrent apply.
- [ ] Implement `apply_proposal` as one SQLite transaction: lock-check state and ownership, verify proposal status and fingerprint, revalidate the saved AI payload, insert only server-built fields, validate the complete 9–30 Question Set, update Question Set timestamp, mark proposal applied and append `QUESTION_ADDITION_APPLIED`.
- [ ] Implement discard as a guarded/idempotent `PROPOSED → DISCARDED` transition with `QUESTION_ADDITION_DISCARDED`; never alter Question Set rows.
- [ ] Preserve proposal history and ensure any failure rolls back both question insertion and proposal status.
- [ ] Add audit assertions that store only IDs, category/mode, count and fingerprints; no raw prompt, JD/CV, answer or AI payload appears.
- [ ] Run `python -m unittest tests.test_question_additions tests.test_questions tests.test_audit_logging -v`; expected result: all mutation, rollback, stale-write, lock and audit tests pass.
- [ ] Commit with `feat: apply question addition proposals safely`.

### Task 5: Expose secured question-addition API routes

**Files:**

- Modify: `app/api.py`
- Modify: `tests/test_api_e2e.py`
- Modify: `tests/test_router.py` if route precedence/matching needs explicit coverage

**Interfaces:**

- `POST /api/v1/interview-cases/{caseId}/question-set/question-additions` with body `{questionSetId, questionCategory, mode, prompt?}` returns `202` and `{taskId, questionSetId, questionCategory, mode}`.
- `GET /api/v1/interview-cases/{caseId}/question-set/question-additions?questionSetId=...&questionCategory=...` returns `{items}`.
- `GET /api/v1/interview-cases/{caseId}/question-set/question-additions/{proposalId}` returns a safe proposal preview.
- `POST .../{proposalId}/discard` returns the final proposal.
- `POST .../{proposalId}/apply` requires `{questionSetId, expectedQuestionSetUpdatedAt, expectedSourceFingerprint}` and returns `{question, proposal}`.

- [ ] Write failing API tests for the five routes, status codes, success envelope, missing/invalid fields, invalid mode/category, overlong prompt, unauthorized requests, wrong case and locked state.
- [ ] Register addition routes before any ambiguous dynamic question route and require the same startup token, Committee session, Host validation and case ownership checks as existing question mutations.
- [ ] Implement create validation so `USER_PROMPT` requires nonblank prompt, `AUTO_GROUP` rejects a nonblank prompt, category is an enum, and the body Question Set ID matches the case.
- [ ] Submit accepted tasks to `Application.submit_task` and return safe task metadata. Extend `get_task` serialization with `targetQuestionCategory` and `additionProposalId` without exposing input manifests or raw result payloads.
- [ ] Implement list/get/discard/apply through `QuestionAdditionService`; derive Question Set identity server-side where possible and map stale/locked/schema errors to the established machine-readable error envelope.
- [ ] Run `python -m unittest tests.test_api_e2e tests.test_router -v`; expected result: happy path, auth, isolation, idempotency and error-envelope tests pass.
- [ ] Commit with `feat: expose question addition api`.

### Task 6: Build the Question Set group UI workflow

**Files:**

- Modify: `web/js/app.js`
- Modify: `web/css/layout.css`
- Modify: `tests/test_frontend_contract.py`

**Interfaces:**

- Change `questionGroups(questions)` to return the three standard groups in fixed order, including empty groups.
- Extend `renderQuestionWorkspace(questionSet, caseId, onRefresh, assessmentStarted = false)` to render group add actions and addition proposal state while preserving selected-question state/focus behavior.
- Add frontend helpers with stable responsibilities: `openQuestionAdditionChoice(groupKey, handlers)`, `openQuestionAdditionPrompt(groupKey, handlers)`, `requestQuestionAddition(caseId, questionSetId, groupKey, mode, prompt)`, and `renderQuestionAdditionProposal(...)`.

- [ ] Add frontend contract tests for all three group labels/buttons, `question-additions` endpoint, `FOUNDATION/APPLICATION/DEEP_DIVE` request values, `USER_PROMPT/AUTO_GROUP`, 2,000-character limit, proposal actions and locked-state guards.
- [ ] Render every group header with count from returned questions and a `Thêm câu hỏi` button. Keep the button’s internal dataset/category enum separate from the Vietnamese label.
- [ ] Implement the two-choice popup. `Gen theo prompt` opens a safe modal with textarea, character counter, cancel and submit; `Tự động gen` submits `AUTO_GROUP` without a prompt and shows loading state.
- [ ] Reuse existing task polling/progress helpers so pending/running/retry states render within the target group, refresh resumes existing task/proposal state, and repeated clicks cannot create a duplicate request.
- [ ] Render safe proposal preview with question text, group/source/type/difficulty, purpose/evidence/rubric and `Dùng câu hỏi này`, `Tạo lại`, `Bỏ qua`. Apply sends the current Question Set timestamp/fingerprint; discard and retry preserve proposal history.
- [ ] On apply success, refresh the Question Set and preserve the selected existing question if it still exists. On stale/locked errors, refresh and show a concise error without resetting focus to question 1.
- [ ] Disable addition actions for `APPROVED` or assessment-started state using server data, while retaining server-error handling for stale browser actions. Do not restore the removed manual-edit UI, Excel fallback button or obsolete count copy.
- [ ] Add CSS for group action headers, popup/modal, progress and proposal preview with existing responsive tokens and reduced-motion behavior.
- [ ] Run `node --check web/js/app.js`, `python -m unittest tests.test_frontend_contract -v`, and `git diff --check`; expected result: all pass.
- [ ] Commit with `feat: add question addition workflow ui`.

### Task 7: End-to-end acceptance and regression verification

**Files:**

- Modify: `tests/test_api_e2e.py` or shared deterministic provider fixtures only where coverage reveals a real gap.
- Modify: `tests/test_question_generation.py`, `tests/test_candidate_access.py`, `tests/test_html_candidate_package_service.py` only if expanded-count regression needs explicit assertions.
- Review: `docs/superpowers/specs/2026-10-08-question-addition-generation-design.md`

- [ ] Add an end-to-end test that creates a draft nine-question set, requests `USER_PROMPT` for `APPLICATION`, completes a deterministic AI task, reads the proposal, verifies the set is still nine, applies it, verifies ten questions/order/provenance, approves and exports candidate HTML with ten questions.
- [ ] Add an end-to-end `AUTO_GROUP` test for `FOUNDATION`, `APPLICATION` and `DEEP_DIVE`, asserting the exact category/source-kind mapping and that Deep Dive accepts either allowed source kind.
- [ ] Add negative acceptance tests for malformed addition schema, provider failure/retry, duplicate idempotency key, stale apply, discard, wrong-case proposal access, approved lock, assessment-started lock, 31-question limit and candidate-package fingerprint mismatch.
- [ ] Verify existing question-variant replacement still preserves its source slot and does not use the addition proposal table.
- [ ] Run the prescribed commands:
  - `python -m unittest discover -s tests -v`
  - `node --check web/js/app.js`
  - `git diff --check`
- [ ] Inspect `git status --short`, `git diff --stat` and staged files. Confirm the existing user-modified specification and prior untracked plan are not accidentally included, and no secrets/real candidate data/raw AI payloads are present.
- [ ] Review backup/export behavior for addition proposal rows and document any remaining risk or open question rather than widening scope silently.
- [ ] Commit only new verification tests if required with `test: verify question addition workflow`.

## Definition of Done

- [ ] Each sidebar group exposes the two requested generation choices.
- [ ] AI generation is asynchronous, proposal-first, idempotent, recoverable and schema-validated.
- [ ] HĐCM explicitly applies or discards proposals; AI never mutates the Question Set directly.
- [ ] Question Sets grow from 9 up to 30 questions with contiguous order, correct category/source rules and no mutation of existing question IDs.
- [ ] Approved/assessment-started locks, stale apply protection, candidate isolation and audit provenance are enforced server-side.
- [ ] Candidate HTML export/import supports the expanded count; Excel fallback remains unchanged and out of scope.
- [ ] Focused tests, full backend tests, frontend syntax/contract checks and diff hygiene checks pass with fresh output.
