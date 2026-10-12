# Per-Question Question Variant Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved per-question question variant workflow on the Question Set screen: HĐCM can request a variant from a user prompt or a same-group regeneration, inspect the proposal, apply/discard it, or continue with manual editing without overwriting the approved source question or bypassing workflow rules.

**Architecture:** Keep the existing background AI task pipeline and add a dedicated `QuestionVariantService` plus `QuestionVariantRepository`. AI returns a validated proposal first; only an explicit apply action mutates the draft Question Set. The apply operation is transactional, checks the source fingerprint and current Question Set state, preserves structural question fields, revalidates the complete set, and writes an audit event. The frontend consumes the task/proposal API and never performs workflow mutation directly.

**Tech Stack:** Python 3.10+ standard library, `http.server`, `urllib`, SQLite with versioned SQL migrations, Vanilla JavaScript ES Modules, HTML/CSS, `unittest`, existing Gemini/provider adapter and background task worker.

**Spec:** `docs/superpowers/specs/2026-10-08-question-variant-generation-design.md`

## Global Constraints

- Preserve the existing local-first architecture and source-of-truth specification order; do not add Flask, an ORM, Node/NPM, a public listener, or runtime dependencies.
- Preserve all pre-existing uncommitted user changes in `documents/30_interview_workspace_ui_implementation_specification.md`, `tests/test_frontend_contract.py`, `web/css/layout.css`, and `web/js/app.js`. Patch only the relevant regions.
- Only Question Set states `DRAFT` and `GENERATED` can request, edit, apply, or discard a proposal. `APPROVED` and any assessment-started state are immutable for this feature.
- Keep the existing question slot identity and structure: `questionId`, `displayOrder`, `competencyKey`, `questionCategory`, `questionType`, `difficulty`, `isRequired`, `estimatedSeconds`, and `sourceKind`. A proposal may replace only the content/rubric fields defined by the approved design.
- A proposal is never automatically applied. AI/provider code may create a result but must not change Question Set workflow state.
- Candidate package export must continue to use the current approved Question Set only; proposals do not affect candidate content until explicitly applied before approval.
- Use one SQLite connection per operation/thread, parameterized SQL, foreign keys/WAL/busy timeout as already required, and append-only migrations. Do not modify migrations already applied.
- Sanitize JD/CV/question context before sending it to the AI provider. Treat the HĐCM prompt as untrusted input, enforce a `MAX_VARIANT_PROMPT_CHARS = 2000` boundary, and never log raw prompt, CV, JD, answer, token, or raw provider payload.
- Keep AI output in Vietnamese for human-readable evaluation/content fields only where the existing AI contract requires it; do not translate UI labels or enum/status values.
- Use safe DOM construction/text nodes for generated content. Do not introduce `innerHTML`, `eval`, or `new Function` for untrusted question or AI text.
- Preserve retry/recovery and idempotency behavior. A provider failure must leave the current draft and existing questions unchanged.
- Do not implement multi-variant comparison, question bank persistence, auto-selection, Interview Brief, `recommendedLiveQuestions`, PASS/FAIL, or post-start editing in this feature.

## Review Focus

During implementation, explicitly verify these risks with tests and code review:

1. A prompt containing whitespace-only content, more than 2,000 characters, or prompt-injection-like instructions is rejected before a task is created, while valid user intent remains available to the provider as untrusted context.
2. A provider payload that changes a protected field, contains the wrong case/question-set/source-question ID, or fails `question-variant.v1` validation creates no applicable proposal and does not mutate the draft.
3. Applying a proposal after a manual edit, another applied proposal, a question-set update, or a retry is rejected as stale atomically; neither the question nor proposal status is partially changed.
4. Repeating the same request with the same idempotency key returns the existing task/proposal and does not create duplicate active work.
5. `APPROVED` and assessment-started cases reject all variant and manual mutation paths, and candidate export remains identical until an explicit apply followed by the normal approval flow.

---

## Task 1: Synchronize normative specifications and define the persistence contract

**Files:**

- Modify `documents/20_domain_and_database_specification.md`
- Modify `documents/21_workflow_state_machine.md`
- Modify `documents/22_ai_assessment_specification.md`
- Modify `documents/23_api_contract_specification.md`
- Modify `documents/30_interview_workspace_ui_implementation_specification.md`
- Create `migrations/007_question_variant_generation.sql`
- Modify `app/migrations.py`
- Modify `tests/test_migrations.py`

- [ ] Update the relevant specification sections before code implementation so the approved design is represented in the project’s governing documents: proposal-first lifecycle, task/result types, source fingerprint, protected fields, API errors, audit events, and UI actions.
- [ ] Document that the user prompt is capped at 2,000 characters after validation and that `USER_PROMPT` and `SAME_GROUP` are the only supported generation modes.
- [ ] Add migration `007_question_variant_generation.sql` without editing migrations `001`–`006`.
- [ ] Extend the AI task/result contract to support `GENERATE_QUESTION_VARIANT` and `QUESTION_VARIANT`, with nullable `source_question_id` fields for variant provenance.
- [ ] Add `question_variant_proposals` with at least: `id`, `ai_result_id`, `interview_case_id`, `question_set_id`, `source_question_id`, `mode`, `source_fingerprint`, `status`, `created_at`, `updated_at`, `applied_at`, and `discarded_at`. Use checked status/mode values and indexes for case, question set, source question, status, and idempotent lookup. Do not add a source-question foreign key that would make historical stale proposals impossible to retain after draft replacement.
- [ ] Preserve the existing current-result uniqueness behavior for full Question Set generation/evaluation while adding a separate current-result path keyed by `question_set_id` and `source_question_id` for `QUESTION_VARIANT` results.
- [ ] Add migration tests for a fresh database and an upgrade from the current latest schema: table/column/check/index presence, migration idempotence, and preservation of existing task/result rows.
- [ ] Run `python -m unittest tests.test_migrations -v` and inspect the migration diff. Expected result: all migration tests pass and no earlier migration file changes.
- [ ] Commit only the specification and migration/test changes with message `feat: define question variant persistence contract`.

## Task 2: Add the AI schema, prompt, and provider operation

**Files:**

- Create `schemas/question-variant.v1.schema.json`
- Create `prompts/question_variant_generation_prompt.md`
- Modify `app/ai/schemas.py`
- Modify `app/ai/prompts.py`
- Modify `app/ai/provider.py`
- Modify `app/ai/http_provider.py`
- Modify `app/ai/gemini_provider.py`
- Modify `tests/test_ai_schemas.py`
- Modify `tests/test_ai_provider.py`
- Modify `tests/test_gemini_provider.py`
- Create or modify `tests/ai_fixtures.py` only if a reusable fixture is required

**Interfaces:**

- Provider operation: `generate_question_variant(payload: dict[str, Any]) -> dict[str, Any]`.
- Prompt catalog key: `question_variant_generation`.
- Provider operation name: `GENERATE_QUESTION_VARIANT`.
- Schema/result type: `question-variant.v1` / `QUESTION_VARIANT`.

- [ ] Write failing schema tests first for a valid proposal, missing required field, invalid enum, wrong source identity, protected-field injection, malformed rubric, and extra/unexpected output that must be rejected according to the existing schema-validation policy.
- [ ] Define `question-variant.v1` with stable top-level metadata: `schemaVersion`, `operation`, `mode`, `questionSetId`, `sourceQuestionId`, `variant`, `confidence`, and `limitations`. Define the variant content/rubric fields exactly once and keep protected slot fields out of the AI-owned output contract.
- [ ] Add the `question_variant_generation` prompt template. It must state that the output is one candidate proposal, must preserve the supplied structure, must return JSON only, must not make a hiring decision, and must treat the user prompt as an instruction to improve one question rather than as permission to change IDs or structural fields.
- [ ] Extend the provider protocol with `generate_question_variant(payload: dict[str, Any]) -> dict[str, Any]` or the project’s equivalent typed interface, without changing existing generation/evaluation method behavior.
- [ ] Map the operation to Gemini/HTTP provider configuration using the existing timeout, retry, schema, and redacted logging conventions. Ensure only sanitized context and the bounded prompt enter the provider payload.
- [ ] Make provider parsing/validation reject malformed JSON and contract violations as `AI_SCHEMA_VALIDATION_FAILED`; preserve the existing error envelope and retry classification.
- [ ] Run the focused AI tests. Expected result: the new valid fixture passes, all invalid fixtures fail at the schema boundary, and existing AI provider tests remain green.
- [ ] Commit with message `feat: add question variant ai contract`.

## Task 3: Implement proposal/task persistence and background orchestration

**Files:**

- Create `app/repositories/question_variants.py`
- Modify `app/repositories/ai_tasks.py`
- Modify `app/services/ai_task_service.py`
- Create `app/services/question_variant_service.py`
- Modify `app/application.py`
- Modify `tests/test_ai_tasks.py`
- Create `tests/test_question_variants.py`

**Interfaces:**

- `QuestionVariantService.request_variant(case_id: str, question_set_id: str, question_id: str, mode: str, prompt: str | None, idempotency_key: str) -> dict[str, Any]` returns the existing task envelope with `taskId`, `questionSetId`, `questionId`, and source snapshot metadata.
- `QuestionVariantService.process(task_id: str, provider: AIProvider) -> dict[str, Any]` returns the completed task/proposal envelope or raises the existing classified AI task error.
- `QuestionVariantRepository.get_proposal(case_id: str, question_set_id: str, question_id: str, proposal_id: str) -> dict[str, Any]` returns only validated proposal fields plus provenance/status metadata.
- `QuestionVariantRepository.create_or_get_task(...)` and `create_proposal_from_result(...)` must preserve the existing repository serialization conventions and return UUID/string IDs in API-ready form.

- [ ] Write failing service/repository tests for request creation, idempotent retry, source fingerprint creation, task-to-proposal materialization, provider failure, schema failure, retry metadata, and recovery without draft mutation.
- [ ] Add repository methods with explicit boundaries, including:
  - `create_or_get_task(...)` keyed by the existing idempotency mechanism and variant source identity.
  - `create_proposal_from_result(...)` linking exactly one `ai_result_id` to one source question and one source fingerprint.
  - `get_proposal(...)`, `list_active_proposals(...)`, `mark_discarded(...)`, and `mark_applied(...)` with status guards.
  - AI task/result serialization that includes `sourceQuestionId` without exposing tokens or provider payloads.
- [ ] Add `QuestionVariantService.request_variant(case_id, question_set_id, question_id, mode, prompt, idempotency_key)` to validate ownership/state, normalize input, build sanitized context, compute the source fingerprint, write the audit request event, and enqueue a `GENERATE_QUESTION_VARIANT` task. It must return the existing task for a repeated idempotency key.
- [ ] Add `QuestionVariantService.process(task_id, provider)` to load the task, invoke only `generate_question_variant`, validate identity/schema/protected-field invariants, persist `QUESTION_VARIANT`, create a `PROPOSED` proposal, and write success/failure audit events. The provider adapter must not perform the apply mutation.
- [ ] Register the new task type in `app/application.py`’s existing task processor dispatch. Keep the existing one-worker/background semantics and task progress states.
- [ ] Ensure a failed task preserves the source question, Question Set status, all prior proposals, and candidate package data; a retry creates the normal new task/result version rather than overwriting a completed result.
- [ ] Run `python -m unittest tests.test_ai_tasks tests.test_question_variants -v`. Expected result: all orchestration tests pass, including duplicate request and failure/retry cases.
- [ ] Commit with message `feat: orchestrate question variant proposals`.

## Task 4: Implement atomic apply/discard and manual-edit audit semantics

**Files:**

- Modify `app/services/question_variant_service.py`
- Modify `app/services/question_service.py`
- Modify `app/repositories/questions.py`
- Modify `app/services/audit_service.py`
- Modify `app/repositories/audit.py` only if a new audit persistence helper is needed
- Modify `tests/test_questions.py`
- Modify `tests/test_question_variants.py`
- Modify `tests/test_audit_logging.py`

**Interfaces:**

- `QuestionVariantService.apply_proposal(case_id: str, question_set_id: str, question_id: str, proposal_id: str, expected_question_set_updated_at: str, expected_source_fingerprint: str) -> dict[str, Any]` returns the updated question and applied proposal metadata.
- `QuestionVariantService.discard_proposal(case_id: str, question_set_id: str, question_id: str, proposal_id: str) -> dict[str, Any]` returns the discarded proposal metadata and never changes the question row.
- The existing manual update path remains the source of truth for manual edits; it must emit `QUESTION_MANUALLY_EDITED` after a successful mutation and update the same source fingerprint inputs used by apply.

- [ ] Write failing tests for applying a valid proposal, preserving all protected fields, retaining `questionId`/order/group, changing only allowed content/rubric fields, and updating the proposal to `APPLIED` in the same transaction.
- [ ] Implement `apply_proposal(case_id, question_set_id, question_id, proposal_id, expected_question_set_updated_at, expected_source_fingerprint)` with one transaction that:
  - Rechecks committee authorization and current Question Set state.
  - Confirms proposal belongs to the requested case/question set/source question and is `PROPOSED`.
  - Compares both expected and persisted source fingerprint/update timestamp to reject stale applications.
  - Reconstructs the replacement from the current protected fields plus validated proposal content; never trusts protected fields from the browser or provider.
  - Revalidates the entire Question Set using existing count, group-ratio, required-field, and normalized-question rules.
  - Updates the question, marks the proposal `APPLIED`, writes `QUESTION_VARIANT_APPLIED`, and records before/after fingerprints in the existing redacted audit shape.
- [ ] Implement discard as an idempotent status transition to `DISCARDED`, with `QUESTION_VARIANT_DISCARDED`; it must never mutate the source question.
- [ ] Add/retain `QUESTION_MANUALLY_EDITED` audit coverage for the existing manual editor. Ensure a manual edit changes the source fingerprint so an older proposal cannot subsequently apply.
- [ ] Test rejection and atomic rollback for wrong case/question set, already applied/discarded proposal, stale source, invalid full-set constraints, approved set, assessment-started case, and concurrent apply attempts.
- [ ] Run `python -m unittest tests.test_questions tests.test_question_variants tests.test_audit_logging -v`. Expected result: all mutation, locking, stale, and audit tests pass.
- [ ] Commit with message `feat: apply question variants safely`.

## Task 5: Expose the proposal lifecycle through secured API routes

**Files:**

- Modify `app/api.py`
- Modify any existing router/controller file only if route registration is not centralized in `app/api.py`
- Modify `tests/test_api_e2e.py`
- Modify `tests/test_router.py` if route matching is covered there

**Interfaces:**

- Create request body: `{ "mode": "USER_PROMPT|SAME_GROUP", "prompt": "..." }`; response status `202` with `{ "taskId", "questionSetId", "questionId" }` plus the existing response envelope.
- Read response: `{ "proposalId", "status": "PROPOSED|APPLIED|DISCARDED", "questionSetId", "questionId", "sourceFingerprint", "variant", "confidence", "limitations" }` plus provenance metadata.
- Apply request body: `{ "expectedQuestionSetUpdatedAt": "...", "expectedSourceFingerprint": "..." }`.
- Discard and apply responses must use the project’s standard success/error envelope and must not expose raw AI payloads.

- [ ] Write failing API tests for the four endpoints and their error envelopes:
  - `POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants`
  - `GET /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}`
  - `POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}/discard`
  - `POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}/apply`
- [ ] Accept only `mode: USER_PROMPT|SAME_GROUP`; require a nonblank prompt for `USER_PROMPT`, reject a prompt for `SAME_GROUP` unless the API contract explicitly permits it, and reject prompt length above 2,000 characters with a deterministic validation error.
- [ ] Return `202` and `taskId` for a newly accepted generation request; return the existing task/proposal identity for an idempotent repeat. Keep task progress polling compatible with existing `GET /tasks/{taskId}` behavior.
- [ ] Return a proposal envelope that includes proposal status, source question identity/fingerprint, safe preview content, task/result metadata, and timestamps, but never provider raw payload or secrets.
- [ ] Reuse existing startup-token and committee-session checks, Host validation, case/question-set ownership checks, and request ID/error response conventions. Do not rely on frontend-hidden buttons for authorization.
- [ ] Enforce apply preconditions server-side, including expected update timestamp/fingerprint, and map stale/locked/invalid schema cases to the project’s existing machine-readable errors.
- [ ] Run `python -m unittest tests.test_api_e2e tests.test_router -v`. Expected result: happy-path and unauthorized/invalid/stale/locked route tests pass.
- [ ] Commit with message `feat: expose question variant api`.

## Task 6: Build the Question Set UI workflow

**Files:**

- Modify `web/js/app.js`
- Modify `web/css/layout.css`
- Modify `tests/test_frontend_contract.py`

- [ ] Write/update frontend contract tests before implementation for action labels, endpoint paths, payload modes, task polling, proposal status actions, locked-state behavior, and absence of the removed Excel fallback/obsolete copy. Keep these tests scoped to the new feature and preserve current user changes in the file.
- [ ] Add a per-question action bar in `renderQuestionDetail` with:
  - `Gen theo prompt` opening a compact prompt modal/drawer.
  - `Tự động gen câu khác` submitting `SAME_GROUP` immediately with confirmation/loading state.
  - `Sửa bằng tay` retaining the existing manual editor behavior.
- [ ] Add the prompt modal/drawer with character count, 2,000-character limit, clear validation, cancel, and submit controls. Render all question/AI content with text nodes or existing safe helpers.
- [ ] Reuse `createTaskProgress`/`waitForTask`/`resumeTask` to show task progress inline for the selected question. Handle refresh/re-entry by loading the proposal/task status rather than starting another request.
- [ ] Add a proposal preview card with `Dùng câu này`, `Tạo lại`, and `Bỏ qua`. `Dùng câu này` sends the current Question Set `updatedAt`/source fingerprint; on stale response, refresh the question detail and explain that the source changed. `Tạo lại` starts a new generation request without applying the old proposal. `Bỏ qua` calls discard and leaves the question unchanged.
- [ ] Disable/hide all mutation actions for `APPROVED` and assessment-started states based on server state, while keeping the UI robust if a stale browser attempts an action and receives a lock error.
- [ ] Keep question count/order/group display derived from returned data. Do not translate enum/status labels, and do not add Interview Brief/recommended live-question UI.
- [ ] Run `node --check web/js/app.js`, the focused frontend contract test, and `git diff --check`. Expected result: JavaScript parses, contract tests pass, and no whitespace errors are introduced.
- [ ] Commit with message `feat: add question variant workflow ui`.

## Task 7: Run end-to-end acceptance and regression verification

**Files:**

- Modify only tests/fixtures that expose a real uncovered behavior found during verification; do not broaden production scope.
- Review `docs/superpowers/specs/2026-10-08-question-variant-generation-design.md` against the final implementation.

- [ ] Add or complete an end-to-end test covering: create a draft Question Set, request `USER_PROMPT`, complete the background task with a deterministic provider fixture, inspect proposal, apply it, verify only allowed fields changed, approve the set, and verify candidate package export contains the applied question.
- [ ] Add an end-to-end same-group test proving the generated proposal keeps `competencyKey`, `questionCategory`, and the question slot while producing one replacement candidate.
- [ ] Add negative acceptance tests for malformed AI schema (`AI_SCHEMA_VALIDATION_FAILED`), provider failure/retry, duplicate idempotency key, stale apply, discard, approved lock, assessment-started lock, and candidate isolation.
- [ ] Run the project-prescribed commands:
  - `python -m unittest discover -s tests -v`
  - `node --check web/js/app.js`
  - `git diff --check`
- [ ] Inspect `git status --short` and `git diff --stat`; confirm only the intended migration, app/provider/service/repository/API/UI/test/spec/plan files changed and no real candidate data, API keys, tokens, or raw AI payloads are present.
- [ ] Review audit entries and database backup/export behavior for the new proposal rows, then document any remaining risk or open question instead of silently widening scope.
- [ ] Commit the final verification/test additions with message `test: verify question variant workflow` only if the task introduced new test changes.

## Definition of Done

- [ ] The design specification’s ten acceptance criteria are covered by implementation and tests.
- [ ] A valid proposal can be generated in both supported modes, previewed, applied or discarded, and retried without overwriting source data unexpectedly.
- [ ] Structural question constraints, workflow locks, candidate isolation, audit/provenance, idempotency, and stale-write protection are enforced server-side.
- [ ] AI schema/provider failures are visible and recoverable without mutating the draft.
- [ ] The Questions UI exposes the three approved actions and task progress without unsafe rendering or enum/label translation.
- [ ] The full backend suite, frontend syntax/contract checks, and diff hygiene checks pass with fresh output.
