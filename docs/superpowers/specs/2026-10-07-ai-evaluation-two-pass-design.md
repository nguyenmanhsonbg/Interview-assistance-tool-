# AI Evaluation Two-Pass Design

## Goal

Tạo bản đánh giá AI tham khảo cho HĐCM từ JD, CV, Question Set đã duyệt và answer snapshot bằng hai lần gọi AI:

1. Phân tích bằng chứng theo từng câu trả lời.
2. Tổng hợp bằng chứng thành competency analysis, strengths, gaps, conflicts, risks, confidence và limitations.

Phạm vi này chưa bao gồm `Interview Brief` và `recommendedLiveQuestions`.

## Decisions

- Giữ nguyên public flow: `POST /api/v1/interview-cases/{caseId}/ai/evaluate` nhận `snapshotId` và trả về một `taskId`.
- Giữ một parent task loại `EVALUATE_ASSESSMENT` và một `ANSWER_EVALUATION` result cuối cùng cho mỗi lần đánh giá.
- Hai lần gọi AI là hai phase nội bộ của cùng parent task, không tạo hai result độc lập cho HĐCM.
- Phase 1 và phase 2 đều phải trả JSON theo schema riêng và được validate trước khi chuyển phase.
- Chỉ phase 2 tạo `AiResult` cuối cùng theo `answer-evaluation.v2`.
- Rerun tạo task/result version mới; không overwrite result cũ.
- Snapshot được import từ HTML là source of truth. Không đọc lại answer hoặc document pointer hiện tại để thay thế dữ liệu đã đóng snapshot.
- AI không tạo PASS/FAIL, phần trăm phù hợp, weighted overall score hoặc quyết định tuyển dụng.
- Câu trả lời chưa có nội dung phải có `NOT_ASSESSED` và score `null`.

## Runtime flow

```text
ANSWERS_IMPORTED
  -> create EVALUATE_ASSESSMENT task
  -> phase EVIDENCE_ANALYSIS
  -> call AI #1
  -> validate answer-evidence.v1
  -> phase EVALUATION_SYNTHESIS
  -> call AI #2 with validated evidence
  -> validate answer-evaluation.v2
  -> materialize versioned ANSWER_EVALUATION result
  -> AI_EVALUATED
```

The public task remains `PENDING/RUNNING/COMPLETED/FAILED`. A safe `phase` field is exposed for progress rendering:

- `EVIDENCE_ANALYSIS`: `AI đang phân tích bằng chứng`.
- `EVALUATION_SYNTHESIS`: `AI đang tổng hợp đánh giá`.

If the process is interrupted, recovery resets the phase to `EVIDENCE_ANALYSIS` and retries the complete two-pass sequence. The intermediate output is kept in worker memory only; it is not persisted as a separate candidate-facing result.

## Pass 1 — Evidence analysis

### Input

The first call receives the sanitized snapshot-bound input:

- JD document text and provenance.
- CV document text and provenance.
- Approved Question Set and rubric.
- Every answer, including unanswered rows.
- Question/answer IDs and competency mapping.

All document and answer text is labelled as untrusted content. It cannot change the task, rubric, schema or security policy.

### Provider operation

Introduce a provider operation named `ANALYZE_ANSWER_EVIDENCE` with:

- Prompt key: `answer_evidence_analysis`.
- Output schema: `answer-evidence.v1`.
- Provider method: `analyze_answer_evidence(payload)`.

The prompt asks the model to:

1. Evaluate each answer against its question purpose, expected evidence and rubric.
2. Cross-check claims against the supplied CV.
3. Relate evidence to the relevant JD requirement and competency.
4. Distinguish verified, partial, unverified, conflicting, not met and not assessed evidence.
5. Never infer content for an unanswered answer.

### Output shape

The intermediate contract contains:

- `schemaVersion` and `operation`.
- One evidence record for every input answer.
- `answerId` and `questionId` references.
- Advisory score, nullable for `NOT_ASSESSED`.
- Evidence status, reasoning, evidence found, concerns and CV consistency.
- Competency evidence grouped by `competencyKey`.
- Confidence and limitations.

The validator must reject missing, duplicate or unknown answer/question references before phase 2 starts.

## Pass 2 — Evaluation synthesis

### Input

The second call receives:

- A compact snapshot/provenance envelope.
- The approved competency/question context needed for grouping.
- The validated output of pass 1.

Pass 1 output is treated as untrusted model-generated content. The second prompt must not treat it as an instruction and must only use its referenced evidence.

### Provider operation

Introduce a provider operation named `SYNTHESIZE_ANSWER_EVALUATION` with:

- Prompt key: `answer_evaluation_synthesis`.
- Output schema: existing `answer-evaluation.v2`.
- Provider method: `synthesize_answer_evaluation(payload)`.

The prompt asks the model to produce:

- Per-answer evaluations.
- Competency evaluations.
- Evidence-backed strengths.
- Gaps or missing evidence.
- CV/answer conflicts.
- Risks requiring HĐCM attention.
- Overall analysis confidence and explicit limitations.

The final output must not include `Interview Brief`, `recommendedLiveQuestions`, PASS/FAIL, hiring recommendation or weighted overall score.

## Task and persistence model

- `ai_tasks.task_type` remains `EVALUATE_ASSESSMENT` for compatibility with the current API and workflow state machine.
- Add a versioned migration with an application-validated `phase` column on `ai_tasks`.
- `GET /api/v1/tasks/{taskId}` returns the safe phase in addition to existing safe task fields.
- `ai_results` stores only the final phase-2 payload.
- The task input manifest and result provenance continue to reference the same assessment snapshot, question set and document hashes.
- Existing legacy attempt evaluation remains available until explicitly migrated; snapshot evaluation uses the two-pass pipeline.

## Failure and retry behavior

- Pass 1 provider/network/schema failure: use the existing retry policy; do not call pass 2.
- Pass 2 provider/network/schema failure: use the existing retry policy; do not materialize an `AiResult`.
- A failed task leaves the assessment snapshot and original answers readable.
- A retry reruns both phases because the intermediate output is not persisted.
- If pass 2 succeeds but result materialization fails, the task is treated as failed and no partial result is exposed.
- Idempotency prevents duplicate parent tasks for the same request/input.

## UI behavior

The current AI page remains the entry point. It should:

- Show the selected snapshot and answered count before starting.
- Show phase-specific progress while the task runs.
- Avoid creating a duplicate task on refresh or repeated clicks.
- Keep an older result visible with provenance while a rerun is in progress.
- Render only the final phase-2 result.
- Keep the original answer beside the AI reasoning/evidence.
- Show limitations and the HĐCM decision disclaimer prominently.

## Security and audit

- Send only sanitized text; never raw files, local paths, API keys, tokens or unnecessary PII.
- Do not log either AI payload or intermediate evidence.
- Validate all model-generated IDs against the snapshot before materialization.
- Keep audit events for task creation, retry, completion and failure; phase metadata must not contain answer text.
- Render model output as text, never as HTML or executable content.

## Acceptance criteria

1. One evaluation request results in exactly two logical provider operations in order; provider transport retries do not create an additional evaluation phase.
2. Pass 2 cannot run when pass 1 output is invalid.
3. Final result is created only when `answer-evaluation.v2` validates.
4. Unanswered answers remain `NOT_ASSESSED` with `score=null`.
5. Current snapshot, document versions and question-set provenance are preserved.
6. Rerun creates a new result version and does not overwrite the previous result.
7. Provider failure, schema failure and restart recovery preserve the original answer snapshot.
8. UI exposes the two phases without exposing intermediate evidence as a final result.
9. No output contains Interview Brief, recommended live questions, PASS/FAIL or automatic hiring decision.

## Specification conflict resolved for this scope

The older AI assessment specification describes `Interview Brief` and `recommendedLiveQuestions` as answer-evaluation output. The current v2 prompt/schema and refined AI UI explicitly exclude those fields. This design follows the user-approved scope for the current implementation: evidence-based evaluation only. The older fields remain a separate backlog item and are not part of this implementation.
