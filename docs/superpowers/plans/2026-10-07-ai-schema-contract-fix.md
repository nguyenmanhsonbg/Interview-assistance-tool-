# AI Evaluation Schema Contract Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent `AI_SCHEMA_VALIDATION_FAILED` during two-pass answer evaluation by making Gemini's nested response schema and prompts explicitly require the fields validated by the application.

**Architecture:** Keep the existing manual backend validation and retry policy as the final safety boundary. Strengthen the Gemini adapter's `responseSchema` for both evidence analysis and evaluation synthesis, and align the versioned prompt files with the same fixed output contract.

**Tech Stack:** Python 3.10+ standard library, `unittest`, Gemini REST structured JSON response schema, Markdown prompt templates.

**Spec:** `documents/22_ai_assessment_specification.md`, `schemas/answer_evidence.v1.schema.json`, `schemas/answer_evaluation.v2.schema.json`

## Global Constraints

- Runtime remains Python standard library only; do not add dependencies.
- AI receives sanitized input only and must return one JSON object without Markdown or commentary.
- `answer-evidence.v1` and `answer-evaluation.v2` remain the active schema versions.
- Backend validation remains authoritative; no partial or invalid AI result may be materialized.
- Do not modify unrelated user-owned changes in `tests/test_frontend_contract.py`, `web/css/layout.css`, or `web/js/app.js`.

## Review Focus

- A phase-1 answer evidence item missing `answerId` must be prevented by the provider contract and still rejected by backend validation.
- A phase-1 competency evidence item must contain all four validated fields.
- A phase-2 per-answer evaluation must preserve the same answer/question reference fields and nullable score rule.
- A phase-2 competency evaluation must contain the required summary and confidence fields.
- Prompt instructions must require exact IDs, one record per supplied answer/question, JSON-only output, and no PASS/FAIL or recommendation fields.

---

### Task 1: Add regression tests for nested schemas and fixed prompts

**Files:**
- Modify: `tests/test_gemini_provider.py`
- Modify: `tests/test_ai_schemas.py`

**Interfaces:**
- Consumes: Existing `GeminiAIProvider` request capture and `PromptCatalog` rendering tests.
- Produces: Failing tests that specify the nested Gemini response schema and prompt wording required by the active JSON contracts.

- [ ] **Step 1: Write the failing response-schema test**

Add assertions for `perAnswerEvidence`, `competencyEvidence`, `perAnswerEvaluations`, and `competencyEvaluations` requiring the exact fields in the corresponding JSON schema files, including `answerId` and `questionId`.

- [ ] **Step 2: Run the focused provider test and verify it fails for the missing nested contract**

Run: `python -m unittest tests.test_gemini_provider.GeminiProviderTests.test_two_pass_response_schemas_declare_nested_required_fields -v`

Expected: FAIL because the current provider declares nested array items as generic `OBJECT` without `properties` or `required`.

- [ ] **Step 3: Write the failing prompt-contract test**

Assert both two-pass prompts contain fixed top-level output examples, required nested field names, exact schema versions, exact IDs copied from input, one-record-per-answer guidance, and the JSON-only/no-PASS-FAIL rules.

- [ ] **Step 4: Run the focused prompt test and verify it fails for the missing instructions**

Run: `python -m unittest tests.test_ai_schemas.AISchemaTests.test_two_pass_prompts_declare_fixed_nested_output_contract -v`

Expected: FAIL because the current prompts do not declare the full nested output contract.

### Task 2: Strengthen Gemini schemas and two-pass prompts

**Files:**
- Modify: `app/ai/gemini_provider.py`
- Modify: `prompts/answer_evidence_analysis_prompt.md`
- Modify: `prompts/answer_evaluation_synthesis_prompt.md`

**Interfaces:**
- Consumes: Nested field requirements from `schemas/answer_evidence.v1.schema.json` and `schemas/answer_evaluation.v2.schema.json`.
- Produces: Gemini structured response schemas and prompts that require complete per-answer and per-competency objects while preserving current operation/schema versions.

- [ ] **Step 1: Add complete nested response schemas**

Define `properties`, `required`, enums, array item types, and nullable score behavior for both two-pass response schemas. Keep the provider schema compatible with Gemini's JSON response schema format and do not weaken the application validator.

- [ ] **Step 2: Add fixed output contracts to the evidence and synthesis prompts**

Add explicit JSON shape references and validation reminders, including exact IDs from input, one record per answer/question, required fields, nullable score for `NOT_ASSESSED`, and prohibition of extra decision fields.

- [ ] **Step 3: Run the focused tests and verify they pass**

Run: `python -m unittest tests.test_gemini_provider tests.test_ai_schemas -v`

Expected: PASS, with the new tests proving both provider schemas and prompt contracts.

### Task 3: Full verification and handoff

**Files:**
- No additional production files.

- [ ] **Step 1: Run the full backend test suite**

Run: `python -m unittest discover -s tests -v`

Expected: All tests pass with zero failures or errors.

- [ ] **Step 2: Inspect the scoped diff and repository status**

Confirm only `app/ai/gemini_provider.py`, the two two-pass prompt files, and the two test files are part of this change; preserve pre-existing user-owned UI/test modifications.

- [ ] **Step 3: Commit only the scoped fix**

Use commit message: `fix: enforce nested AI evaluation output schema`

