# Gemini Provider Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend-only Google Gemini REST provider for the three existing Phase 2 AI capabilities without changing the `AIProvider` protocol, workflow state machine, schemas, or manual fallback behavior.

**Architecture:** Keep the existing provider-neutral adapter and add a `GeminiAIProvider` implementation of the existing protocol. `main.py` selects the provider through `AI_PROVIDER`; API requests still create persistent AI tasks and return `202`, while the background worker performs Gemini calls, parses the provider envelope, and delegates domain validation to the existing task service. Gemini model rotation and redacted provider telemetry stay inside the adapter boundary.

**Tech Stack:** Python 3.10+ standard library only; `urllib.request`, `urllib.error`, `json`, `logging`, `threading`, `time`; SQLite existing task tables; `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-05-gemini-provider-integration-design.md` and `documents/gemini-api-specification.md`, constrained by `AGENTS.md`, documents 18, 21, 22, 25 and 26.

## Global Constraints

- Runtime uses Python 3.10+ Standard Library only.
- The server binds only to `127.0.0.1`; no public or LAN listener is added.
- The existing `AIProvider` protocol remains `generate_questions`, `evaluate_answers`, and `suggest_follow_up`.
- AI calls remain asynchronous; API endpoints enqueue tasks and return `202`.
- Gemini receives sanitized extracted text only; raw files, base64 file parts, local paths, secrets, PINs, tokens and unnecessary PII are never sent.
- The provider never changes workflow state directly; services own state transitions and audit events.
- AI output is untrusted and must pass existing manual schema/range/enum/reference validation before persistence.
- Existing generic `AI_ENDPOINT`/`AI_MODEL`/`AI_API_KEY` behavior remains available through `AI_PROVIDER=generic`.
- `GEMINI_API_KEY` is process-only and must not appear in source, frontend, database, logs, backups, exports or error messages.
- No migration, SDK, ORM, third-party runtime package, Phase 1 route or automatic hiring decision is added.
- Automated tests use fake openers/providers and never call Google or any real AI endpoint.

## Review Focus

- Gemini HTTP errors must rotate models without exposing the API key or query URL; covered by `test_rotates_after_retryable_http_error_without_leaking_key` in `tests/test_gemini_provider.py`.
- A valid response split across multiple Gemini text parts must be concatenated and parsed once; covered by `test_concatenates_text_parts_and_parses_json`.
- A Markdown JSON fence must be accepted, while malformed JSON must remain an explicit provider error and must not silently invent a result; covered by `test_accepts_json_fence_and_rejects_invalid_json`.
- `AI_PROVIDER` and model-list configuration must reject unsupported providers, normalize aliases, and preserve defaults; covered by `tests/test_config.py`.
- Existing task-producing services must record provider/model metadata while fake-provider E2E remains network-free; covered by `test_task_records_provider_metadata` and `tests/test_api_e2e.py`.

---

### Task 1: Add Gemini configuration and provider selection

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- `AppConfig.ai_provider: str` defaults to `generic`.
- `AppConfig.gemini_api_key: str | None` reads `GEMINI_API_KEY` with `repr=False`.
- `AppConfig.gemini_models: tuple[str, ...]` reads the comma-separated `GEMINI_CV_PARSE_MODELS` value; empty entries are ignored and the default model list is retained for Gemini.
- `AppConfig.gemini_timeout_seconds: float` converts `GEMINI_CV_PARSE_TIMEOUT_MS` from milliseconds and requires a positive value.

- [ ] **Step 1: Write the failing tests**

  Add configuration tests for default generic behavior, Gemini environment parsing, positive timeout conversion, unsupported provider rejection, and an empty model-list fallback to the three Gemini defaults.

- [ ] **Step 2: Run tests to verify they fail**

  Run: `python -m unittest tests.test_config tests.test_application -v`

  Expected: FAIL because the Gemini configuration fields do not exist.

- [ ] **Step 3: Implement the minimal configuration and factory**

  Add only the fields and environment parsing required by the design. Keep the API key out of `repr` and preserve existing generic configuration behavior. Provider construction is implemented in Task 2 after the Gemini adapter exists.

- [ ] **Step 4: Run tests to verify they pass**

  Run: `python -m unittest tests.test_config tests.test_application -v`

  Expected: PASS, with no secret values in test output.

- [ ] **Step 5: Commit**

  ```powershell
  git add app/config.py tests/test_config.py
  git commit -m "feat: add Gemini provider configuration"
  ```

### Task 2: Implement the Gemini REST adapter

**Files:**
- Create: `app/ai/gemini_provider.py`
- Create: `app/ai/factory.py`
- Modify: `main.py`
- Modify: `app/ai/provider.py` only if a shared safe error helper is needed
- Test: `tests/test_gemini_provider.py`
- Test: `tests/test_config.py`
- Test: `tests/test_application.py`

**Interfaces:**
- `GeminiAIProvider(api_key: str | None, models: Sequence[str], timeout: float, *, opener: Callable[..., Any] = urllib.request.urlopen, sleep: Callable[[float], None] = time.sleep, logger: logging.Logger | None = None)`
- `generate_questions(payload: dict[str, Any]) -> dict[str, Any]`
- `evaluate_answers(payload: dict[str, Any]) -> dict[str, Any]`
- `suggest_follow_up(payload: dict[str, Any]) -> dict[str, Any]`
- `build_ai_provider(config: AppConfig, *, logger: logging.Logger | None = None) -> AIProvider | None` returns `GeminiAIProvider` for `AI_PROVIDER=gemini`, the existing `HttpAIProvider` for `AI_PROVIDER=generic` when `AI_ENDPOINT` is configured, and `None` otherwise.
- Internal operation mapping: `GENERATE_QUESTIONS → question_generation`, `EVALUATE_ASSESSMENT → answer_evaluation`, `SUGGEST_FOLLOW_UP → follow_up_question`.
- Public constants for the three default model IDs and accepted aliases; model normalization returns canonical IDs and removes duplicates without dropping defaults.

- [ ] **Step 1: Write the failing tests**

  Build a fake `urlopen` response/context manager and add tests for:

  - Gemini URL path and URL-encoded query key.
  - `Content-Type: application/json` and no authorization header requirement.
  - `contents`, `systemInstruction`, `generationConfig.temperature`, rendered prompt version and payload.
  - Multiple response text fragments concatenated into one JSON object.
  - Optional Markdown JSON fences.
  - Empty response and malformed JSON errors.
  - Rotation across timeout, 429, 5xx, network failure and empty response.
  - No second model attempt for malformed JSON from the same provider call.
  - Process-local round-robin starting model and canonical alias normalization.
  - Missing API key returns `ProviderError(code="MISSING_API_KEY", retryable=False)` without including the key in the error text.
  Move the provider-factory tests into this task and add application construction coverage for Gemini selection without a network call.

- [ ] **Step 2: Run tests to verify they fail**

  Run: `python -m unittest tests.test_gemini_provider -v`

  Expected: FAIL because `app.ai.gemini_provider.GeminiAIProvider` and `app.ai.factory.build_ai_provider` do not exist.

- [ ] **Step 3: Implement the minimal adapter**

  Construct `https://generativelanguage.googleapis.com/v1beta/models/{canonical_model}:generateContent` with the key query parameter only in the in-memory request. Use the existing `PromptCatalog` for prompt key/version and render the current payload as the user text. Add a short system instruction for untrusted input and JSON-only output. Extract and concatenate `candidates[0].content.parts[*].text`, trim it, remove one optional JSON fence, parse one object, and return it. Keep raw provider response and request URL out of exceptions/logs. Implement `build_ai_provider` and update `main.py` to select the new adapter while preserving the generic path.

- [ ] **Step 4: Run tests to verify they pass**

  Run: `python -m unittest tests.test_gemini_provider -v`

  Expected: PASS for all adapter and rotation cases.

- [ ] **Step 5: Commit**

  ```powershell
  git add app/ai/gemini_provider.py app/ai/factory.py app/ai/provider.py main.py tests/test_gemini_provider.py tests/test_config.py tests/test_application.py
  git commit -m "feat: add Gemini generateContent provider"
  ```

### Task 3: Wire task metadata and redacted AI telemetry

**Files:**
- Modify: `app/services/question_generation_service.py`
- Modify: `app/services/evaluation_service.py`
- Modify: `app/services/interview_service.py`
- Modify: `app/application.py`
- Modify: `app/api.py`
- Test: `tests/test_ai_tasks.py`
- Test: Existing `tests/test_gemini_provider.py` covers redacted provider telemetry; `tests/test_api_e2e.py` only if the existing fake-provider setup needs metadata assertions.

**Interfaces:**
- Task-producing service constructors accept keyword-only `provider_name: str | None = None` and `model_name: str | None = None`.
- Each AI task enqueue passes those safe values into the existing `ai_tasks.provider` and `ai_tasks.model` columns.
- `_TaskProcessor` and `APIController` receive the same metadata from `create_application` so both enqueue and worker materialization use one configuration snapshot.
- Gemini attempt telemetry uses safe fields only: provider, model, operation/prompt key, status, duration and error code.

- [ ] **Step 1: Write the failing tests**

  Add a service-level test that creates a question-generation task with `provider_name="gemini"` and a canonical model and asserts those values in the persisted task row. Reuse the Task 2 provider test as the redacted telemetry proof; do not duplicate it here.

- [ ] **Step 2: Run tests to verify they fail**

  Run: `python -m unittest tests.test_ai_tasks tests.test_audit_logging -v`

  Expected: FAIL because task producers do not currently receive provider/model metadata.

- [ ] **Step 3: Implement the minimal wiring**

  Thread provider/model metadata from `AppConfig` through `create_application`, `_TaskProcessor`, and `APIController` into the three task-producing services. Keep the safe logger wiring and provider telemetry implemented in Task 2; do not add a second logging path.

- [ ] **Step 4: Run tests to verify they pass**

  Run: `python -m unittest tests.test_ai_tasks tests.test_audit_logging tests.test_api_e2e -v`

  Expected: PASS, including the existing fake-provider E2E workflow and redaction assertions.

- [ ] **Step 5: Commit**

  ```powershell
  git add app/services/question_generation_service.py app/services/evaluation_service.py app/services/interview_service.py app/application.py app/api.py tests/test_ai_tasks.py tests/test_api_e2e.py
  git commit -m "feat: record Gemini task metadata safely"
  ```

### Task 4: Document Gemini runtime configuration and fallback

**Files:**
- Modify: `README.md`
- Modify: `README.txt`
- Test: Existing configuration/provider tests from Tasks 1–3; no new production behavior is introduced by this task.

- [ ] **Step 1: Confirm the existing contract tests cover the documented behavior**

  Review the Task 1–3 tests for `AI_PROVIDER=gemini`, no `AI_ENDPOINT` requirement, missing-key behavior, model aliases/rotation, and redacted errors. Do not add a duplicate test after the implementation exists; this task only documents already-tested behavior.

- [ ] **Step 2: Run the existing contract tests**

  Run: `python -m unittest tests.test_config tests.test_gemini_provider tests.test_ai_tasks -v`

  Expected: PASS before documentation edits.

- [ ] **Step 3: Update documentation only**

  Document the three Gemini environment variables, model aliases/rotation, backend-only key handling, no raw-file upload, no real-AI automated tests, and manual fallback. Do not add a real secret or a live endpoint example that can be copied into production without review.

- [ ] **Step 4: Re-run the existing contract tests**

  Run: `python -m unittest tests.test_config tests.test_gemini_provider tests.test_ai_tasks -v`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```powershell
  git add README.md README.txt tests/test_application.py
  git commit -m "docs: document Gemini configuration and fallback"
  ```

### Task 5: Full verification and handoff

**Files:**
- Modify: only files identified by failing tests or documentation review
- Test: existing `tests/*`

- [ ] **Step 1: Run focused provider and configuration tests**

  Run: `python -m unittest tests.test_config tests.test_gemini_provider tests.test_ai_tasks tests.test_application -v`

  Expected: PASS with no warnings or secret output.

- [ ] **Step 2: Run the complete suite**

  Run: `python -m unittest discover -s tests -v`

  Expected: all tests pass, including candidate isolation, workflow recovery, audit, backup and existing fake-provider E2E.

- [ ] **Step 3: Run the portable smoke test**

  Run: `powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1` only if packaging prerequisites are already available; otherwise run the repository's existing smoke command with the configured Python executable.

  Expected: package/smoke completes without requiring Gemini credentials and without placing runtime data in the install directory.

- [ ] **Step 4: Inspect status and diff**

  Run: `git status --short` and `git diff HEAD --stat`.

  Expected: only Gemini integration files, tests, docs, and the approved design/plan are changed; `documents/gemini-api-specification.md` remains untouched as the user's untracked source document.

- [ ] **Step 5: Perform secret/PII review**

  Search tracked changes for `GEMINI_API_KEY`, `AIza`, bearer tokens, full CV/JD/answer fixtures, raw URLs containing `key=`, and base64 file payloads.

  Expected: only variable names/placeholders and redacted test values appear; no real secret or candidate data is present.

- [ ] **Step 6: Commit verification-ready implementation**

  ```powershell
  git status --short
  git add app tests README.md README.txt
  git commit -m "feat: integrate Gemini AI provider for Phase 2"
  ```

