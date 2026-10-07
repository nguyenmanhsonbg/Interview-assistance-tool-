# AI Evaluation Two-Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement two logical AI operations for snapshot-based candidate evaluation: evidence analysis first, then evidence-backed evaluation synthesis, while keeping the existing public task/result flow.

**Architecture:** Keep one public `EVALUATE_ASSESSMENT` parent task and one versioned `ANSWER_EVALUATION` result. The snapshot evaluation path will run a two-pass pipeline inside the worker, validate the intermediate `answer-evidence.v1` contract, then validate and materialize the final `answer-evaluation.v2` contract. Legacy attempt evaluation remains one-pass and compatible until separately migrated.

**Tech Stack:** Python 3.10+ standard library only, `threading`/`queue.Queue`, SQLite migrations, `urllib.request`, JSON contracts, Vanilla JavaScript ES Modules, existing unittest suite.

**Spec:** [2026-10-07-ai-evaluation-two-pass-design.md](../specs/2026-10-07-ai-evaluation-two-pass-design.md), `documents/22_ai_assessment_specification.md`, `documents/23_api_contract_specification.md`, `documents/30_interview_workspace_ui_implementation_specification.md`.

## Global Constraints

- Runtime remains Python 3.10+ Standard Library only.
- HTTP server remains `http.server.ThreadingHTTPServer` bound to `127.0.0.1`.
- Database remains SQLite with one connection per operation/thread, WAL, foreign keys and parameterized SQL.
- AI work remains asynchronous through the persistent `AiTask`/worker path; HTTP returns `202` with `taskId`.
- Snapshot evaluation uses the imported immutable answer snapshot and the exact JD/CV/question-set provenance bound to it.
- Send only sanitized text; never send raw files, local paths, API keys, tokens or unnecessary PII.
- AI output is advisory; it must not create PASS/FAIL, weighted overall score, fit percentage or an automatic hiring decision.
- Unanswered answers are `NOT_ASSESSED` with `score=null`; score `0` remains a real score.
- Rerun creates a new task/result version and never overwrites a completed result payload.
- Do not overwrite the existing uncommitted UI changes in `web/js/app.js`, `web/css/layout.css` or `tests/test_frontend_contract.py`.

## Review Focus

- An invalid or incomplete phase-1 evidence output must prevent phase 2 and final-result materialization; cover in Task 4.
- Duplicate/unknown answer or question IDs from either model output must be rejected against the snapshot; cover in Tasks 1 and 4.
- A retry or restart must not expose intermediate evidence as a final result and must restart the two-pass sequence safely; cover in Tasks 3 and 4.
- An older result must remain tied to its original snapshot while a new evaluation task runs; cover in Task 6.
- Existing legacy attempt evaluation and question-generation tasks must continue to use their current provider methods and result schemas; cover in Tasks 2, 4 and 5.

### Task 1: Add the two-pass AI contracts

**Files:**
- Create: `schemas/answer_evidence.v1.schema.json`
- Create: `prompts/answer_evidence_analysis_prompt.md`
- Create: `prompts/answer_evaluation_synthesis_prompt.md`
- Modify: `app/ai/prompts.py`
- Modify: `app/ai/schemas.py`
- Test: `tests/ai_fixtures.py`, `tests/test_ai_schemas.py`

**Interfaces:**
- Produces prompt keys `answer_evidence_analysis` and `answer_evaluation_synthesis`.
- Produces schema operation `ANSWER_EVIDENCE` with version `answer-evidence.v1`.
- Keeps final operation `ANSWER_EVALUATION` with version `answer-evaluation.v2`.
- `SchemaRegistry.validate("ANSWER_EVIDENCE", payload, context=...)` validates schema and snapshot reference rules.

- [ ] **Step 1: Write failing contract tests**

Add tests for:

- A valid `answer-evidence.v1` fixture.
- `NOT_ASSESSED` requiring `score=null`.
- Missing, duplicate and unknown answer/question references rejected when context is supplied.
- Phase-2 v2 output accepted without `Interview Brief` or `recommendedLiveQuestions`.
- Prompt catalog returns the expected prompt versions and wraps input as untrusted content.

- [ ] **Step 2: Run the contract tests and verify they fail**

Run:

~~~
python -m unittest tests.test_ai_schemas -v
~~~

Expected: FAIL because the new operation, fixture and reference validation do not exist.

- [ ] **Step 3: Implement the phase-1 schema and prompt catalog entries**

Define `answer-evidence.v1` with one `perAnswerEvidence` item per answer, competency evidence, confidence and limitations. Add custom validation for answer/question/competency references and the unanswered rule. Keep prompt rendering provider-neutral and preserve the existing retry repair instruction.

- [ ] **Step 4: Implement the two prompts**

The evidence prompt must only analyze supplied JD/CV/question/answer data. The synthesis prompt must treat phase-1 output as untrusted model data, produce `answer-evaluation.v2`, and explicitly prohibit Interview Brief, live questions, PASS/FAIL and hiring recommendations.

- [ ] **Step 5: Run the contract tests and verify they pass**

Run:

~~~
python -m unittest tests.test_ai_schemas -v
~~~

Expected: PASS.

- [ ] **Step 6: Commit only the scoped contract files**

~~~
git add schemas/answer_evidence.v1.schema.json prompts/answer_evidence_analysis_prompt.md prompts/answer_evaluation_synthesis_prompt.md app/ai/prompts.py app/ai/schemas.py tests/ai_fixtures.py tests/test_ai_schemas.py
git commit -m "feat: add two-pass evaluation contracts"
~~~

### Task 2: Add provider operations for both AI calls

**Files:**
- Modify: `app/ai/provider.py`
- Modify: `app/ai/http_provider.py`
- Modify: `app/ai/gemini_provider.py`
- Test: `tests/test_ai_provider.py`, `tests/test_gemini_provider.py`, provider fakes in affected tests

**Interfaces:**
- `AIProvider.analyze_answer_evidence(payload: dict[str, Any]) -> dict[str, Any]`.
- `AIProvider.synthesize_answer_evaluation(payload: dict[str, Any]) -> dict[str, Any]`.
- Existing `generate_questions`, `evaluate_answers` and `suggest_follow_up` remain available.

- [ ] **Step 1: Write failing provider tests**

Assert that HTTP and Gemini adapters:

- Send `ANALYZE_ANSWER_EVIDENCE` with `answer_evidence_analysis` and `answer-evidence.v1` metadata.
- Send `SYNTHESIZE_ANSWER_EVALUATION` with `answer_evaluation_synthesis` and `answer-evaluation.v2` metadata.
- Preserve JSON-only parsing, retry behavior and secret redaction.
- Keep the existing question-generation response schema and legacy answer-evaluation method behavior.

- [ ] **Step 2: Run provider tests and verify they fail**

Run:

~~~
python -m unittest tests.test_ai_provider tests.test_gemini_provider -v
~~~

Expected: FAIL because the new provider methods and operation mappings do not exist.

- [ ] **Step 3: Implement provider-neutral operations**

Add the two methods to the protocol and map them to prompt keys/operation names in `HttpAIProvider`. Keep provider retry policy unchanged; transport retries are not additional evaluation phases.

- [ ] **Step 4: Implement Gemini operation mappings**

Add operation configuration, temperature and structured response schemas for the two new operations. Ensure no prompt input, answer text or API key is written to logs. Reuse the existing model rotation and JSON parsing behavior.

- [ ] **Step 5: Update test doubles and run provider tests**

Add both methods to every provider fake used by snapshot evaluation tests. Run the provider tests again and expect PASS.

- [ ] **Step 6: Commit only the scoped provider files**

~~~
git add app/ai/provider.py app/ai/http_provider.py app/ai/gemini_provider.py tests/test_ai_provider.py tests/test_gemini_provider.py tests/ai_fixtures.py tests/test_ai_tasks.py tests/test_refined_evaluation.py tests/test_api_e2e.py
git commit -m "feat: add two-pass AI provider operations"
~~~

### Task 3: Persist safe task phase and expose progress metadata

**Files:**
- Create: `migrations/003_ai_evaluation_two_pass.sql`
- Modify: `app/repositories/ai_tasks.py`
- Modify: `app/services/ai_task_service.py`
- Modify: `app/api.py`
- Test: `tests/test_ai_tasks.py`, `tests/test_refined_evaluation.py`

**Interfaces:**
- Phase values are `EVIDENCE_ANALYSIS` and `EVALUATION_SYNTHESIS` for snapshot evaluation.
- `AITaskService.set_phase(task_id: str, phase: str) -> None` validates the phase and updates only safe metadata.
- `_task_dict` exposes `phase`; task API exposes it in its safe task projection.

- [ ] **Step 1: Write failing persistence tests**

Test that a snapshot evaluation task starts in `EVIDENCE_ANALYSIS`, can move to `EVALUATION_SYNTHESIS`, and that recovery/retry resets it to `EVIDENCE_ANALYSIS`. Test that task polling returns phase but never input manifest or intermediate model output.

- [ ] **Step 2: Run the targeted tests and verify they fail**

Run:

~~~
python -m unittest tests.test_ai_tasks tests.test_refined_evaluation -v
~~~

Expected: FAIL because the migration, repository field and phase methods do not exist.

- [ ] **Step 3: Add migration 003**

Add a nullable/application-validated `phase` column to `ai_tasks` so existing tasks remain readable. Do not modify migrations 001 or 002. New snapshot evaluation tasks must explicitly initialize `EVIDENCE_ANALYSIS`.

- [ ] **Step 4: Implement repository/service phase handling**

Read/write the phase through the existing repository, validate the allowlist in application code, and reset snapshot evaluation phase on retry/restart. Do not store phase-specific prompt payloads in the task row.

- [ ] **Step 5: Add phase to the safe task API response**

Extend `get_task` with `phase` while preserving the existing safe-field projection and hiding `inputManifest`, tokens and model payloads.

- [ ] **Step 6: Run the targeted tests and verify they pass**

Run:

~~~
python -m unittest tests.test_ai_tasks tests.test_refined_evaluation -v
~~~

Expected: PASS.

- [ ] **Step 7: Commit only the scoped persistence/API files**

~~~
git add migrations/003_ai_evaluation_two_pass.sql app/repositories/ai_tasks.py app/services/ai_task_service.py app/api.py tests/test_ai_tasks.py tests/test_refined_evaluation.py
git commit -m "feat: expose AI evaluation task phases"
~~~

### Task 4: Implement the snapshot two-pass orchestration

**Files:**
- Create: `app/services/two_pass_evaluation.py`
- Modify: `app/services/ai_task_service.py`
- Modify: `app/services/evaluation_service.py`
- Test: `tests/test_two_pass_evaluation.py`, `tests/test_refined_evaluation.py`

**Interfaces:**
- `TwoPassEvaluationPipeline.run(task: dict[str, Any], provider: AIProvider, payload: dict[str, Any]) -> dict[str, Any]` returns only validated final `answer-evaluation.v2` output.
- `AITaskService.process(...)` gains an optional runner callback for task-specific orchestration; existing single-call task behavior remains unchanged.
- Snapshot evaluation routes through the pipeline; legacy attempt evaluation continues using `provider.evaluate_answers`.

- [ ] **Step 1: Write failing pipeline tests**

Use a recording fake provider and assert:

- Snapshot evaluation calls `analyze_answer_evidence` then `synthesize_answer_evaluation` exactly once each, in order.
- Phase 2 payload contains validated phase-1 evidence and the same snapshot/provenance IDs.
- Invalid phase-1 JSON/schema/reference output prevents phase 2 and creates no result.
- Invalid phase-2 output creates no result and moves the task through the existing retry/failure path.
- A valid run creates one `ANSWER_EVALUATION` result with v2 payload and changes the case/snapshot to `AI_EVALUATED`.
- Unanswered rows remain `NOT_ASSESSED` with null score.
- Rerun creates version 2 and leaves version 1 immutable.

- [ ] **Step 2: Run the pipeline tests and verify they fail**

Run:

~~~
python -m unittest tests.test_two_pass_evaluation tests.test_refined_evaluation -v
~~~

Expected: FAIL because the pipeline and runner integration do not exist.

- [ ] **Step 3: Build phase-1 and phase-2 payload adapters**

Use `_snapshot_provider_payload` as the source of the exact snapshot-bound JD/CV/question/answer data. Set operation metadata for phase 1, then send the validated phase-1 output inside an explicitly labelled untrusted evidence block to phase 2. Validate all IDs and competency keys against the input context before phase 2.

- [ ] **Step 4: Implement the pipeline runner**

Set task phase before each call, invoke the matching provider method, validate the intermediate/final schema, and return only the final v2 payload. Add retry repair instructions to each phase when the parent task is in `PENDING_RETRY`. Keep intermediate output in memory only.

- [ ] **Step 5: Integrate the runner with `AITaskService.process`**

Preserve the existing mark-running, provider-error, schema-error, retry, audit and result-materialization behavior. The runner must not alter workflow state directly; `EvaluationService.process` remains responsible for snapshot/case terminal state updates.

- [ ] **Step 6: Preserve the legacy evaluation path**

Branch only when `assessmentSnapshotId` is present. Legacy attempt tasks continue to use `provider.evaluate_answers` and their existing v1/v2 compatibility behavior.

- [ ] **Step 7: Run the pipeline and regression tests**

Run:

~~~
python -m unittest tests.test_two_pass_evaluation tests.test_refined_evaluation tests.test_ai_tasks tests.test_ai_evaluation -v
~~~

Expected: PASS.

- [ ] **Step 8: Commit only the scoped orchestration files**

~~~
git add app/services/two_pass_evaluation.py app/services/ai_task_service.py app/services/evaluation_service.py tests/test_two_pass_evaluation.py tests/test_refined_evaluation.py tests/test_ai_tasks.py tests/test_ai_evaluation.py
git commit -m "feat: orchestrate two-pass snapshot evaluation"
~~~

### Task 5: Update end-to-end API coverage and failure recovery

**Files:**
- Modify: `tests/test_api_e2e.py`
- Modify: `tests/test_refined_evaluation.py`
- Modify: `tests/test_ai_tasks.py`
- Modify: `tests/test_ai_provider.py` if shared recording fakes need adjustment

**Interfaces:**
- Existing API remains `POST /api/v1/interview-cases/{caseId}/ai/evaluate` followed by `GET /api/v1/tasks/{taskId}` and `GET /api/v1/interview-cases/{caseId}/ai/evaluation`.

- [ ] **Step 1: Add failing HTTP-flow assertions**

Cover the HTML import path through two-pass evaluation, including:

- `202` task creation with phase metadata available during polling.
- Final result schema `answer-evaluation.v2` without legacy brief/live-question fields.
- Same idempotency key returning the same parent task.
- Provider phase-1 failure, phase-2 failure and restart recovery preserving the answer snapshot.
- Rerun against the same snapshot creating a new result version.

- [ ] **Step 2: Run the end-to-end tests and verify the new assertions fail**

Run:

~~~
python -m unittest tests.test_api_e2e tests.test_refined_evaluation tests.test_ai_tasks -v
~~~

Expected: FAIL on the new two-pass assertions before integration is complete.

- [ ] **Step 3: Implement only test support needed for the new flow**

Use recording providers that return deterministic phase-1 evidence and phase-2 v2 output. Do not add real candidate data, API keys or provider payload dumps to fixtures.

- [ ] **Step 4: Run the end-to-end tests and verify they pass**

Run the same command and expect PASS.

- [ ] **Step 5: Commit only the scoped test files**

~~~
git add tests/test_api_e2e.py tests/test_refined_evaluation.py tests/test_ai_tasks.py tests/test_ai_provider.py
git commit -m "test: cover two-pass evaluation API flow"
~~~

### Task 6: Show phase-aware progress and preserve old-result provenance in the UI

**Files:**
- Modify: `web/js/app.js`
- Test: `tests/test_frontend_contract.py`
- Modify only if required: `web/css/layout.css`

**Interfaces:**
- `GET /api/v1/tasks/{taskId}` supplies `task.phase`.
- `waitForTask` and `createTaskProgress` consume phase without changing the existing question-generation progress behavior.

- [ ] **Step 1: Write failing frontend contract assertions**

Assert that the AI UI source:

- Maps `EVIDENCE_ANALYSIS` to evidence-analysis copy.
- Maps `EVALUATION_SYNTHESIS` to synthesis copy.
- Still renders only final evaluation data.
- Does not add Interview Brief, recommended live questions, PASS/FAIL or fit percentage.
- Keeps an older result/provenance visible while a rerun task is active.

- [ ] **Step 2: Run frontend contract tests and verify they fail**

Run:

~~~
python -m unittest tests.test_frontend_contract -v
~~~

Expected: FAIL on the new phase/provenance assertions.

- [ ] **Step 3: Implement phase-aware progress**

Update the shared progress component to prefer phase labels for evaluation tasks and fall back to the existing status labels for question generation and older tasks. Keep `aria-live`, indeterminate progress and duplicate-task protection.

- [ ] **Step 4: Update AI page rerun behavior**

When a rerun is active and an older result exists, show the running phase and retain the old result with its snapshot/version warning. Do not mix old answer analysis with the current snapshot.

- [ ] **Step 5: Run frontend tests and JavaScript syntax validation**

Run:

~~~
python -m unittest tests.test_frontend_contract -v
node --check web/js/app.js
~~~

Expected: PASS and exit code 0.

- [ ] **Step 6: Commit only the scoped UI/test files**

~~~
git add web/js/app.js web/css/layout.css tests/test_frontend_contract.py
git commit -m "feat: show two-pass AI evaluation progress"
~~~

### Task 7: Reconcile active documentation and run the complete verification gate

**Files:**
- Modify: `documents/30_interview_workspace_ui_implementation_specification.md`
- Modify only if needed: `documents/22_ai_assessment_specification.md`
- Review: `docs/superpowers/specs/2026-10-07-ai-evaluation-two-pass-design.md`

- [ ] **Step 1: Update the active implementation specification**

Document the two phases, final-only materialization, phase-aware task polling, retry semantics and the explicit temporary exclusion of Interview Brief/recommendedLiveQuestions. Preserve the existing UI contract for evidence, limitations, provenance and HĐCM final authority.

- [ ] **Step 2: Run the full backend test suite**

Run:

~~~
python -m unittest discover -s tests -v
~~~

Expected: all tests pass.

- [ ] **Step 3: Run frontend syntax and diff checks**

Run:

~~~
node --check web/js/app.js
git diff --check
~~~

Expected: syntax check exits 0; diff check reports no new whitespace errors.

- [ ] **Step 4: Inspect status and scoped diff**

Run:

~~~
git status --short
git diff --stat
git diff -- migrations/003_ai_evaluation_two_pass.sql app/ai app/services app/repositories app/api.py web/js/app.js web/css/layout.css schemas prompts tests documents/30_interview_workspace_ui_implementation_specification.md
~~~

Confirm that no secrets, candidate PII fixtures, raw AI payload logs or unrelated files were added.

- [ ] **Step 5: Commit documentation only if the user wants repository history updated**

If committing, stage only the documentation change and use:

~~~
git add documents/30_interview_workspace_ui_implementation_specification.md
git commit -m "docs: specify two-pass AI evaluation flow"
~~~

## Execution Notes

- Execute tasks in order; each task must pass its focused tests before the next task.
- Preserve the current uncommitted UI refinement changes and inspect the diff before every commit.
- Do not add a runtime dependency or introduce a second server/process.
- Do not expose the intermediate `answer-evidence.v1` payload through a new public endpoint in this MVP.
