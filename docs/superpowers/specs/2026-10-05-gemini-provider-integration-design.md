# Gemini Provider Integration Design

**Status:** Proposed design for review  
**Date:** 2026-10-05  
**Scope:** Phase 2 Supervised Interview Mini Tool

## Goal

Integrate Google Gemini REST `generateContent` into the existing Phase 2 AI task pipeline while preserving the current `AIProvider` interface, asynchronous task lifecycle, schema validation, human review gates, security boundary, and manual fallback behavior.

## References

- `documents/gemini-api-specification.md`
- `documents/18_phase2_supervised_interview_technology_specification.md`
- `documents/21_workflow_state_machine.md`
- `documents/22_ai_assessment_specification.md`
- `documents/25_security_and_audit_specification.md`
- `documents/26_document_processing_specification.md`

## Scope and conflict resolution

### In scope

Gemini is integrated for the three capabilities already present in the Phase 2 codebase:

1. `GENERATE_QUESTIONS`.
2. `EVALUATE_ASSESSMENT`.
3. `SUGGEST_FOLLOW_UP`.

Interview Brief remains a local materialization of the validated `EVALUATE_ASSESSMENT` result. It does not create a second Gemini request in the normal flow.

### Out of scope

- Phase 1 recruitment/screening routes and prompt catalog entries.
- Dedicated structured CV parser.
- Direct multimodal CV analysis.
- Sending raw CV/JD files or base64 file bytes to Gemini.
- Gemini SDK or any third-party runtime dependency.
- Automatic hiring decisions or AI final evaluation.

### Conflict resolution

`documents/gemini-api-specification.md` describes an optional inline base64 CV request. This conflicts with the Phase 2 security and document-processing rules, which require AI input to be sanitized extracted text and prohibit sending raw files. The Phase 2 rule is the source of truth for this integration; the inline-file path remains an explicit backlog item and is not implemented.

## Architecture

The existing provider abstraction remains unchanged:

```text
AIProvider protocol
├── HttpAIProvider       # existing provider-neutral JSON gateway
└── GeminiAIProvider     # Gemini REST adapter
```

`main.py` selects the adapter through `AI_PROVIDER`:

- `generic`: existing `AI_ENDPOINT`/`AI_MODEL`/`AI_API_KEY` configuration.
- `gemini`: `GEMINI_API_KEY` and Gemini model rotation configuration.

The API layer continues to enqueue an `AiTask` and return `202`. The worker invokes the selected provider. The provider never changes workflow state directly; existing task services continue to validate output and materialize domain results.

## Configuration

The following environment variables are added for the Gemini provider:

| Variable | Required | Default | Behavior |
| --- | --- | --- | --- |
| `AI_PROVIDER` | No | `generic` | Selects `generic` or `gemini`; unknown values fail startup validation. |
| `GEMINI_API_KEY` | For Gemini | None | Backend-only secret. Missing key makes Gemini unavailable without exposing the expected value. |
| `GEMINI_CV_PARSE_MODELS` | No | `gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite` | Comma-separated configured models. Default models are always retained; duplicates are removed after normalization. |
| `GEMINI_CV_PARSE_TIMEOUT_MS` | No | `45000` | Per-request timeout converted to seconds for `urllib.request`. |

The existing generic variables remain supported. No database migration is required. Existing `ai_tasks.provider` and `ai_tasks.model` fields are populated with safe provider/model metadata when tasks are created.

## Model normalization and rotation

The Gemini adapter owns model selection:

1. Normalize aliases `gemini 3.6 flash`, `gemini 3.5 flash`, and `gemini 3.5 flash lite`.
2. Build an ordered, de-duplicated list from the default models followed by valid configured models.
3. Select the first model using a process-local round-robin index protected by a lock.
4. Attempt each model at most once for the logical provider call.
5. Move to the next model for HTTP errors, rate limits, network errors, timeouts, or empty responses.
6. Return the first non-empty successful parsed JSON object.
7. Raise the last safe provider error if all models fail.

The adapter does not retry the same model. The existing `AiTaskService` remains responsible for one task-level retry with `repairInstruction` after schema or provider errors marked retryable.

## Gemini request contract

For each current Phase 2 operation, the adapter sends:

```json
{
  "contents": [
    {
      "role": "user",
      "parts": [{"text": "<rendered versioned prompt>"}]
    }
  ],
  "systemInstruction": {
    "parts": [{"text": "<provider safety and JSON-only instruction>"}]
  },
  "generationConfig": {
    "temperature": 0.7
  }
}
```

The URL is constructed per model:

```text
https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}
```

The API key is used only while constructing the in-memory request. Error messages and logs must not contain the URL or query string. The request uses `Content-Type: application/json` and an explicit timeout.

The existing `PromptCatalog` remains the source of prompt text and versions. The rendered prompt is treated as user content; the adapter adds a short system-level instruction requiring untrusted input handling and one JSON object response. Existing prompt files and Phase 2 prompt versions remain unchanged.

## Response parsing

The Gemini adapter converts the provider envelope into the current `AIProvider` return type:

1. Parse the top-level JSON object.
2. Require `candidates[0].content.parts`.
3. Concatenate every non-empty `text` fragment in order.
4. Trim whitespace.
5. Reject empty text with `EMPTY_RESPONSE`.
6. Remove an optional Markdown JSON fence.
7. Parse one JSON object and return it.

Operation-specific schema and cross-reference validation remain in `SchemaRegistry` and `AITaskService`; the adapter does not invent or repair domain output.

## Error mapping

Provider errors are safe typed `ProviderError` instances:

| Condition | Code | Model rotation | Task retry |
| --- | --- | --- | --- |
| Missing API key | `MISSING_API_KEY` | No | No; manual fallback |
| HTTP 429 | `RATE_LIMITED` | Yes | Yes if task retry remains |
| HTTP 5xx | `PROVIDER_ERROR` | Yes | Yes if task retry remains |
| HTTP 4xx auth/payload | `MODEL_UNAVAILABLE` or `PROVIDER_ERROR` | Yes only for model availability; no blind retry for invalid payload | No for non-repairable errors |
| Network/timeout | `NETWORK_ERROR` or `TIMEOUT` | Yes | Yes if task retry remains |
| Empty response | `EMPTY_RESPONSE` | Yes | Yes if task retry remains |
| Invalid JSON text | `INVALID_JSON` | No additional model attempt for this call | Yes once through existing repair path |

When all attempts fail, the current task state machine applies `QUESTION_GENERATION_FAILED` or `AI_ANALYSIS_FAILED` and leaves manual fallback available.

## Security and privacy

- `GEMINI_API_KEY` is read from the process environment only.
- The key is not returned by bootstrap, stored in settings, logged, or exported.
- Request URLs containing the key are never logged or persisted.
- Payloads contain only existing sanitized text manifests.
- Raw files, local paths, PINs, tokens, email, phone, address, and full unneeded names are excluded by existing service payload builders.
- Gemini output is untrusted and must pass existing schema, enum, range, and question-reference validation.
- The provider cannot update case state or finalize evaluation.

## Observability and audit

Existing task timestamps/status/retry fields remain the source of task lifecycle evidence. At task creation, safe provider/model metadata is stored in the existing `ai_tasks.provider` and `ai_tasks.model` fields. The adapter emits only redacted metadata for attempted models, prompt key/version, status, duration, and error code through the existing logging/audit boundary. Prompt text, raw response, API key, and candidate data are never logged.

Existing audit events remain authoritative:

- `AI_TASK_CREATED`.
- `AI_TASK_RETRIED`.
- `AI_TASK_COMPLETED`.
- `AI_TASK_FAILED`.
- `AI_RESULT_RERUN` where applicable.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `app/ai/gemini_provider.py` | Gemini URL/request/response adapter, model normalization and rotation. |
| `app/ai/provider.py` | Keep provider protocol and typed provider errors. |
| `app/config.py` | Parse and validate provider/model/key/timeout environment configuration. |
| `main.py` | Select generic or Gemini provider without exposing secrets. |
| `app/services/ai_task_service.py` and task-producing services | Preserve task metadata and current workflow behavior. |
| `tests/test_gemini_provider.py` | Unit tests with fake `urllib` opener; no network. |
| `tests/test_application.py` / `tests/test_api_e2e.py` | Provider selection and Phase 2 integration coverage using fake providers. |
| `README.md` and `README.txt` | Document Gemini configuration and safe fallback. |

No frontend, migration, domain-state, or schema changes are required for the first integration slice.

## Verification strategy

Tests must be written before production implementation:

1. Configuration parses `AI_PROVIDER=gemini`, aliases, defaults, timeout and missing key safely.
2. Successful Gemini response with multiple text parts produces the expected JSON object.
3. JSON fences are accepted and empty/malformed responses are rejected safely.
4. Model rotation proceeds on timeout, 429, 5xx, network errors and empty responses, but not on malformed JSON for the same call.
5. API key is present in the request query only and absent from errors/logging.
6. Missing Gemini configuration uses the existing unavailable-provider/manual fallback path.
7. Existing fake-provider E2E workflow remains independent of network and still covers question generation, evaluation, Brief, live interview and final evaluation.
8. Full unittest discovery is run after implementation on a machine with Python 3.10+ available.

## Open questions deferred from this integration

- Google account/model availability must be verified before pilot deployment.
- Gemini data-processing/retention approval remains an operational prerequisite.
- Dedicated CV parsing and inline file analysis require a separate security review and specification update before implementation.
