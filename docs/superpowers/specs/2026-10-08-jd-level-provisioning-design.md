# JD-derived Interview Level Design

**Status:** Draft for review  
**Date:** 2026-10-08

## 1. Goal

Bỏ trường `Level` khỏi màn tạo hồ sơ phỏng vấn. Sau khi JD được import và xác nhận, hệ thống dùng nội dung JD đã chuẩn hóa để trích xuất level bất đồng bộ, cập nhật `Job.targetLevel`, rồi mới cho phép sinh bộ câu hỏi.

## 2. Current conflict

- `renderNewCase` hiện yêu cầu `targetLevel` và gửi giá trị này khi tạo Job.
- `jobs.target_level` đang `NOT NULL`.
- `POST /api/v1/jobs` và `CaseService.create_job` đang yêu cầu `targetLevel`.
- JD hiện chỉ có extracted text; chưa có pipeline trích xuất metadata.
- Frontend specification hiện tại vẫn mô tả `targetLevel` là field bắt buộc.

Implementation phải cập nhật contract/spec liên quan, không chỉ ẩn field trên UI.

## 3. Proposed flow

```text
Create interview case without Level
        |
        v
Import/confirm JD
        |
        v
Enqueue EXTRACT_JOB_LEVEL using sanitized confirmed JD text
        |
        +-- COMPLETED --> persist targetLevel + provenance, unlock Question Set
        |
        +-- FAILED -----> keep Level pending/failed, show retry, keep Question Set blocked
```

CV flow không thay đổi. Việc tạo hồ sơ vẫn giữ candidate, position title và Lead HĐCM; chỉ `targetLevel` được trì hoãn.

## 4. Domain and persistence

Add a versioned migration that changes Job level provisioning without changing existing valid jobs:

- `jobs.target_level` trở thành nullable cho tới khi JD extraction hoàn tất.
- Thêm `jobs.target_level_status` với các trạng thái `PENDING`, `EXTRACTING`, `READY`, `FAILED`.
- Thêm `jobs.target_level_source` nullable; flow mới dùng `JD_AI`.
- Thêm `jobs.target_level_confidence` nullable và giới hạn trong `0..1`.
- Existing jobs with a non-empty level được migrate thành `READY` và source `LEGACY`.
- Không xóa hoặc ghi đè level đã `READY` khi retry; extraction mới chỉ cập nhật khi Job còn pending/failed và case chưa bắt đầu assessment.
- Evidence extraction được giữ trong versioned AI result payload; không thêm raw provider payload vào Job row.

The job projection exposes `targetLevel`, `targetLevelStatus`, `targetLevelSource`, and `targetLevelConfidence`. Question generation and all downstream AI payload builders must reject a case whose level is not `READY` instead of sending a null level to Gemini.

## 5. AI contract and task lifecycle

Add a dedicated `EXTRACT_JOB_LEVEL` task/provider operation:

- Input: case/job identifiers, confirmed current JD document reference, content hash, and sanitized JD text only.
- Output schema:

```json
{
  "schemaVersion": "job-level-extraction.v1",
  "targetLevel": "Senior",
  "confidence": 0.92,
  "evidence": ["Senior Backend Engineer", "5+ years of experience"]
}
```

- `targetLevel` is a concise text value found or inferred from JD; it is not a hiring decision or PASS/FAIL result.
- Extraction is idempotent for the same case, current JD version, and content hash.
- Provider/schema failure follows the existing AI retry and manual-fallback task rules; no partial Job update is allowed.
- On successful materialization, the application service updates the Job in one transaction and records audit metadata without storing raw provider payload in logs.

The AI provider remains responsible only for the HTTP call and response parsing. It does not mutate workflow state directly.

## 6. API and workflow changes

- `POST /api/v1/jobs`: `targetLevel` becomes optional for new jobs; omitted value creates `PENDING` level status. Existing callers that send a value retain current behavior.
- Confirming the current JD enqueues or reuses `EXTRACT_JOB_LEVEL` and returns the task reference in the response when applicable.
- Add a Committee-only retry endpoint for a failed/pending extraction, guarded by case mutability and JD version fingerprint.
- `GET case` and `GET task` expose safe level status and task state.
- `POST question-set generation` returns a domain validation error while level status is not `READY`; no AI task is created.
- Required audit actions: request, completed, failed, and retry for JD level extraction.

## 7. UI behavior

- Remove the `Level` field from `/cases/new` and remove it from the client draft key/request body.
- Keep `Vị trí` as the position title supplied at case creation.
- Case header shows the level when `READY`; otherwise shows `Đang xác định level từ JD`.
- JD & CV screen shows an inline task progress/status card after JD confirmation.
- On `FAILED`, show a retry action and keep the Question Set CTA disabled with an explanation.
- On `READY`, refetch the case and enable the existing Question Set CTA. No client-side status mutation is allowed.
- The UI does not expose provider raw output; evidence is displayed only if the safe API projection includes it.

## 8. Security and recovery

- Send only sanitized, length-limited JD text to the provider; never send the source file or unrelated CV text for this operation.
- Bind extraction to the current JD content hash so a stale task cannot update a newer JD.
- A server restart recovers the task through the existing AI worker recovery path.
- A provider failure leaves the Job level unchanged and keeps the case usable for document retry; it must not create a fake default level.

## 9. Acceptance criteria

1. New case UI contains no editable `Level` field and does not send `targetLevel`.
2. A new case can be created with a pending Job level.
3. Confirmed JD creates one idempotent extraction task using sanitized JD text.
4. Valid AI output updates Job level to `READY` and is visible in the case header.
5. Invalid output, stale JD, provider failure, and retry are handled without partial updates.
6. Question generation is blocked until level is `READY` and proceeds normally afterward.
7. Existing jobs/cases with a level continue to work unchanged.
8. Tests cover migration, API, task retry/idempotency, stale-version protection, UI contract, and candidate/AI data boundaries.

## 10. Open decision for review

The proposed MVP auto-persists a valid extracted level with provenance and confidence. HĐCM remains the authority over questions and final evaluation; no hiring decision is derived from this metadata. If HĐCM must explicitly approve the extracted level, add a separate `PROPOSED`/`CONFIRMED` state before implementation.
