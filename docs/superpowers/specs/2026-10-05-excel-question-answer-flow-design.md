# Excel Question + Answer Flow Design

**Status:** Proposed design for review
**Date:** 2026-10-05
**Scope:** Phase 2 Supervised Interview Mini Tool refinement

## 1. Goal

Refine the tool to support one focused workflow:

1. Import and confirm JD/CV.
2. Generate a question set from the JD and CV with Gemini.
3. Export the generated question set to Excel, allow answers to be entered in that workbook, and import the same workbook format.
4. Evaluate JD + CV + imported questions + answers with Gemini.

The Excel workbook is the canonical interchange format between question generation and answer evaluation. Export and import must use the same versioned workbook contract.

## 2. Current-state assessment

The current code already supports:

- JD/CV file or manual-text import and confirmation in `DocumentService`.
- Asynchronous Gemini question generation in `QuestionGenerationService`.
- Answer evaluation in `EvaluationService`, but only after a browser Candidate Mode creates and submits an `AssessmentAttempt`.

The current code does not support importing a question-and-answer workbook. Candidate Mode, Interview Brief, live follow-up, and Final Evaluation are separate capabilities that are not required by this refined flow.

## 3. Scope decision

### 3.1 Keep

- Job, Candidate, and InterviewCase as the case context.
- JD/CV extraction, confirmation, snapshots, hashes, and sanitized AI payloads.
- Question Set generation, validation, versioning, and export.
- Excel workbook import and round-trip validation.
- Imported assessment answer snapshot.
- Asynchronous AI task queue, Gemini provider, schema validation, audit, security, backup, and manual fallback.

### 3.2 Remove from the active product flow

- Candidate Mode timer, candidate token, autosave, and browser answer submission.
- `AssessmentService.start` and candidate answer routes.
- Interview Brief materialization and manual Brief editing.
- Live Interview records and follow-up question generation.
- Committee Final Evaluation and finalization routes.
- The CV recruitment parser pipeline described by `documents/cv-ai-parsing-flow-specification.md`; that document describes another recruitment system and is not an implementation requirement for this Phase 2 flow.

Existing database tables and historical data are not hard-deleted in the first refinement. Routes and UI for removed capabilities become inactive, while a later migration can remove unused structures after data-retention review.

## 4. Target workflow

```text
Create InterviewCase
        |
        v
Import JD + CV and confirm extracted text
        |
        v
Queue Gemini question generation
        |
        v
Validate and persist GENERATED Question Set
        |
        v
Export question-answer.v1.xlsx
        |
        v
User reviews questions and fills answer_text in Excel
        |
        v
Import the same workbook format
        |
        v
Validate workbook and create immutable imported assessment snapshot
        |
        v
Queue Gemini answer evaluation
        |
        v
Validate and display Evaluation Result
```

The workbook import is an explicit Committee action. Successful import validates and locks the question/answer snapshot used for evaluation; it does not allow later mutation of that snapshot.

## 5. Canonical Excel contract

The first implementation supports `.xlsx` only. Legacy binary `.xls` and macro-enabled `.xlsm` files are rejected. The runtime uses Python Standard Library ZIP/XML handling; no `openpyxl`, pandas, Node.js, or other runtime dependency is added.

### 5.1 Workbook sheets

The workbook must contain exactly these application sheets:

- `metadata`: two columns, `field` and `value`.
- `questions`: one row per question with the exact header contract below.

No third sheet is allowed in `question-answer.v1`; user guidance belongs in the UI or an external template document. This keeps export and import deterministic.

### 5.2 Metadata fields

Required metadata rows:

| Field | Meaning |
| --- | --- |
| `format_version` | `question-answer.v1` |
| `case_id` | InterviewCase identity |
| `question_set_id` | Exported Question Set identity |
| `question_set_version` | Question Set version |
| `duration_seconds` | Assessment duration, 600–900 seconds |
| `exported_at` | UTC ISO 8601 timestamp |

Candidate name, email, phone, address, API key, PIN, token, local file path, and raw CV/JD text are not exported.

### 5.3 Question sheet fields

The `questions` header row is fixed and ordered:

```text
question_id
display_order
question_text
competency_key
source_kind
purpose
question_type
difficulty
expected_evidence
rubric_score_0
rubric_score_1
rubric_score_2
rubric_score_3
rubric_score_4
is_required
estimated_seconds
answer_text
is_answered
```

`question_id` is the stable database question identity. `display_order` is a validated integer from 1 to 8. Question/rubric fields are exported so the reviewer can correct the question before import; the importer validates the complete row again. Imported corrections are captured in the immutable assessment snapshot and do not mutate the generated Question Set. `answer_text` may be blank. `is_answered=false` with blank `answer_text` becomes `NOT_ASSESSED`; it must never be inferred as a negative answer.

The importer rejects missing or duplicate IDs, duplicate display orders, unknown enum values, invalid rubric fields, more than eight rows, fewer than five rows, and rows that do not belong to the exported `question_set_id` unless the workbook is explicitly marked as a new manual set by a future contract version.

### 5.4 Round-trip rules

- Export always produces the same metadata and question headers required by import.
- Import accepts only `format_version=question-answer.v1`.
- `case_id` and `question_set_id` must match the target case and current export context.
- Question and answer text is read as plain text; formulas, macros, external links, and embedded objects are not executed or preserved.
- The importer stores a workbook hash and normalized row fingerprint for audit/idempotency; it does not store the raw workbook as an AI payload.
- Re-importing the same workbook with the same idempotency key is idempotent.
- A changed workbook creates a new assessment snapshot/task version and never overwrites a completed AI result.

## 6. Data and state design

The existing `InterviewCase` remains the aggregate root. The first implementation reuses the existing `question_sets`, `questions`, `assessment_attempts`, and `answers` concepts, but adds an explicit source marker for imported assessment input through a new versioned migration if the current schema does not provide one.

Target state transitions:

```text
DRAFT
  -> DOCUMENTS_READY
  -> QUESTIONS_GENERATING
  -> QUESTIONS_GENERATED
  -> QUESTIONS_EXPORTED
  -> ANSWERS_IMPORTED
  -> AI_ANALYZING
  -> AI_EVALUATED
```

The exact persisted state names must be reconciled with the existing state machine specification before implementation. Existing terminal/final-evaluation states remain readable for historical records but are not reachable from the refined UI flow.

The imported assessment snapshot contains:

- JD/CV document IDs, versions, and hashes.
- Question Set ID/version and each question ID.
- Imported answer IDs, answer text hashes, answered flags, and revisions.
- Workbook hash, import timestamp, and source marker `EXCEL_IMPORT`.

Evaluation uses this snapshot and cannot read mutable current documents or questions without matching the recorded hashes.

## 7. API and UI design

The active API flow will contain:

- Existing JD/CV import, list, and confirm endpoints.
- Existing question generation endpoint.
- New Question Set export endpoint returning an `.xlsx` download.
- New Question + Answer workbook import endpoint accepting `.xlsx` and Committee authorization.
- Existing task polling endpoint.
- A refined evaluation endpoint that evaluates the imported snapshot.
- A read-only Evaluation Result endpoint.

The following current endpoints become inactive in the refined flow: Candidate Mode assessment start/answer/submit, Interview Brief, live interview/follow-up, and Final Evaluation. They are not deleted from the first migration so old data remains recoverable.

The UI becomes a linear case workspace: Documents → Generate Questions → Export Excel → Import Completed Excel → Evaluate → Evaluation Result. Manual fallback remains available when Gemini generation or evaluation fails.

## 8. Evaluation contract

The current answer-evaluation schema includes `interviewBrief` and `recommendedLiveQuestions`, which belong to the removed live-interview flow. The refined implementation uses the new versioned schema `answer-evaluation.v2`, containing only:

- `perAnswerEvaluations`.
- `competencyEvaluations`.
- `strengths`.
- `gaps`.
- `conflicts`.
- `risks`.
- `confidence`.
- `limitations`.

Scores remain advisory 0–4 evidence assessments. The AI must not produce or persist an automatic hiring decision. A human remains the final decision owner outside this simplified flow.

## 9. Security and privacy

- Excel parsing occurs only on the backend.
- File path is generated from a UUID and remains inside the data root.
- `.xlsx` size, sheet count, row count, cell length, and XML structure are bounded before parsing.
- Formula cells, macros, external links, and embedded objects are rejected or treated as inert text; they are never executed.
- Only sanitized JD/CV/Question/Answer text is sent to Gemini.
- API key, PIN, startup token, committee session, candidate token, raw workbook bytes, local paths, and full provider URLs never enter logs, audit metadata, AI payloads, backup exports, or frontend responses.
- Workbook import requires Committee session and startup authorization.
- Question and answer snapshots are immutable once evaluation is queued.

## 10. Migration and compatibility

- Existing migrations are not edited; new schema changes use a new migration version.
- Existing cases and completed AI results are preserved.
- Removed active routes are disabled through routing/UI changes before any table cleanup.
- Old `answer-evaluation.v1` results remain readable as historical records; new evaluations use the refined schema version.
- A later cleanup migration is required only after retention and backward-compatibility review.

## 11. Verification strategy

Tests must cover:

1. Exported workbook has the exact required sheets, metadata, headers, and row values.
2. Export → fill answer cells → import produces an equivalent semantic snapshot.
3. Missing sheets, wrong format version, wrong case/set IDs, duplicate IDs/orders, invalid enums, invalid rubric, blank workbook, `.xls`, `.xlsm`, formulas, oversized cells, and oversized files are rejected safely.
4. Blank answers become `NOT_ASSESSED`.
5. Import is idempotent and changed workbooks create a new snapshot/version.
6. Evaluation payload contains only the matched JD/CV/question/answer snapshot and sanitized text.
7. Gemini provider remains mocked in automated tests; no real API key or network call is required.
8. Removed flow routes are not reachable from the refined UI and old data remains readable.
9. Full end-to-end flow passes with a fake AI provider and manual fallback.

## 12. Explicit non-goals

- Implementing the separate recruitment CV AI parsing pipeline.
- Supporting `.xls`, `.xlsm`, macros, formulas, or arbitrary Excel workbooks.
- Reintroducing Candidate Mode, live interview, Interview Brief, or Final Evaluation into the refined flow.
- Sending Excel files or raw file bytes to Gemini.
- Automatic hiring decisions.
