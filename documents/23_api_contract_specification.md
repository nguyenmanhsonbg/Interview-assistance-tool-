# 23. Phase 2 Supervised Interview Mini Tool — API Contract Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Backend/API + Frontend |
| Last updated | 2026-10-04 |
| Depends on | 18 Technology Specification; 20 Domain and Database Specification; 21 Workflow State Machine; 22 AI Assessment Specification |
| Supersedes | Không có |

## 1. API boundary

- Base URL: http://127.0.0.1:8787.
- Base path: /api/v1.
- Frontend và API same-origin; không bật wildcard CORS.
- Content-Type request/response: application/json; charset=utf-8.
- Upload MVP dùng JSON metadata + base64 content.
- HTTP handler không chứa SQL hoặc business workflow.
- AI operation trả 202 và taskId; không giữ HTTP connection chờ provider.

## 2. Envelope và header

### 2.1. Success envelope

~~~json
{
  "success": true,
  "data": {},
  "requestId": "uuid"
}
~~~

### 2.2. Error envelope

~~~json
{
  "success": false,
  "error": {
    "code": "ERROR_CODE",
    "message": "Thông báo an toàn cho người dùng",
    "details": {}
  },
  "requestId": "uuid"
}
~~~

details không chứa stack trace, SQL, API key, PIN, token, full CV, full answer hoặc raw AI payload.

### 2.3. Headers

| Header | Bắt buộc | Ý nghĩa |
| --- | --- | --- |
| Content-Type | Có với body | application/json |
| X-Request-Id | Không | Client correlation; server tạo nếu thiếu |
| X-Startup-Token | Có với mutation | Token random của process |
| X-Committee-Session | Có với Committee API | Session sau PIN verification |
| X-Candidate-Token | Có với Candidate API | Token của một attempt |
| X-Idempotency-Key | Có với mutation có side effect | Chống duplicate operation |

Startup token rotate khi process restart. Candidate token và Committee session không được lưu localStorage.

### 2.4. Date/time và limit

- Timestamp: UTC ISO 8601, ví dụ 2026-10-04T08:30:00.000Z.
- JSON body tối đa 1 MiB.
- Upload body tối đa 10 MiB.
- AI response tối đa 5 MiB.
- Page size mặc định 50, tối đa 200.
- X-Request-Id luôn có trong response envelope và response header.

### 2.5. HTTP status

| Status | Dùng cho |
| ---: | --- |
| 200 | Read/update thành công |
| 201 | Tạo resource |
| 202 | Tạo background task |
| 204 | Xóa thành công không body |
| 400 | JSON/business input sai |
| 401 | Thiếu/sai session hoặc token |
| 403 | Sai capability |
| 404 | Resource không tồn tại |
| 409 | State/idempotency/revision conflict |
| 413 | Body quá lớn |
| 415 | Content-Type không hỗ trợ |
| 422 | Field/schema validation fail |
| 429 | Thao tác lặp/vượt giới hạn |
| 500 | Internal error an toàn |
| 502 | AI provider lỗi |
| 504 | AI timeout |

## 3. Error code catalog

| Code | HTTP | Điều kiện |
| --- | ---: | --- |
| INVALID_JSON | 400 | Body không parse |
| VALIDATION_ERROR | 422 | Field/type/enum/range sai |
| REQUEST_TOO_LARGE | 413 | Body vượt limit |
| UNSUPPORTED_MEDIA_TYPE | 415 | Content-Type sai |
| UNAUTHENTICATED | 401 | Session/token thiếu hoặc hết hạn |
| FORBIDDEN_CAPABILITY | 403 | Candidate gọi Committee hoặc ngược lại |
| RESOURCE_NOT_FOUND | 404 | Không có resource/không thuộc session |
| STATE_CONFLICT | 409 | Transition không hợp lệ |
| IDEMPOTENCY_CONFLICT | 409 | Key dùng với payload khác |
| ANSWER_REVISION_CONFLICT | 409 | Autosave revision cũ |
| DOCUMENT_PARSE_FAILED | 422 | Không extract được text |
| AI_TASK_FAILED | 502 | Provider/task terminal fail |
| AI_TASK_TIMEOUT | 504 | Provider timeout |
| DATABASE_BUSY | 409 | SQLite bận sau retry |
| BACKUP_REQUIRED | 409 | Chưa backup trước delete |
| INTERNAL_ERROR | 500 | Lỗi không expose chi tiết |

## 4. Authorization modes

| Mode | Header | Capability |
| --- | --- | --- |
| Committee | X-Committee-Session | Case, document, question, AI, brief, live, evaluation, settings, backup |
| Candidate | X-Candidate-Token | Read questions, save answer, submit |
| System/worker | Internal process call | Migration, task worker, recovery |

Candidate không được đọc JD, CV, rubric, expected evidence, AI result, Interview Brief, live record, evaluation, task hoặc case khác. Backend kiểm tra capability trước resource lookup.

## 5. Resource map

| Method | Path | Mode | Effect |
| --- | --- | --- | --- |
| GET | /api/v1/health | Localhost | Health read |
| GET/PATCH | /api/v1/settings | Committee | Read/update settings |
| GET/POST | /api/v1/jobs | Committee | Job list/create |
| GET/POST | /api/v1/candidates | Committee | Candidate list/create |
| GET/POST | /api/v1/interview-cases | Committee | List/create case |
| GET/PATCH/DELETE | /api/v1/interview-cases/{caseId} | Committee | Read/update/delete case |
| POST/GET | /api/v1/interview-cases/{caseId}/documents | Committee | Upload/list documents |
| POST | /api/v1/interview-cases/{caseId}/documents/{documentId}/confirm | Committee | Confirm text |
| POST/GET/PATCH | /api/v1/interview-cases/{caseId}/question-set | Committee | Generate/read/edit set |
| POST | /api/v1/interview-cases/{caseId}/question-set/approve | Committee | Approve set |
| POST/GET | /api/v1/interview-cases/{caseId}/assessment | Committee | Create/read attempt |
| POST | /api/v1/interview-cases/{caseId}/assessment/start | Committee | Start Candidate Mode |
| GET | /api/v1/assessment-attempts/{attemptId}/questions | Candidate | Candidate-safe questions |
| PUT | /api/v1/assessment-attempts/{attemptId}/answers/{questionId} | Candidate | Autosave |
| POST | /api/v1/assessment-attempts/{attemptId}/submit | Candidate | Submit and lock |
| POST | /api/v1/interview-cases/{caseId}/ai/evaluate | Committee | Enqueue evaluation |
| GET | /api/v1/tasks/{taskId} | Committee | Poll task |
| GET/POST | /api/v1/interview-cases/{caseId}/interview-brief | Committee | Read/manual fallback |
| POST | /api/v1/interview-cases/{caseId}/live-interview/start | Committee | Start live |
| POST | /api/v1/interview-cases/{caseId}/live-interview/records | Committee | Add record |
| POST | /api/v1/interview-cases/{caseId}/live-interview/follow-up | Committee | Enqueue follow-up |
| POST | /api/v1/interview-cases/{caseId}/live-interview/complete | Committee | Complete live |
| GET/PUT | /api/v1/interview-cases/{caseId}/final-evaluation | Committee | Read/edit evaluation |
| POST | /api/v1/interview-cases/{caseId}/final-evaluation/finalize | Committee | Finalize |
| POST | /api/v1/backups | Committee | SQLite backup |
| POST | /api/v1/exports | Committee | Report/package export |

## 6. Endpoint contract

Mọi success response dùng success envelope. Các response data dưới đây là payload bên trong data.

### 6.1. Health, settings, jobs và candidates

GET /api/v1/health

- Request: không body.
- Response data: status, version, database, aiConfigured, serverTime.
- Không trả secret.

GET /api/v1/settings

- Request: không body.
- Response data: items gồm key, valueType, isSensitive, updatedAt; không trả protected_value.

PATCH /api/v1/settings

Request:

~~~json
{
  "changes": [
    { "key": "assessment.default_duration_seconds", "value": 900 },
    { "key": "assessment.auto_submit_on_expiry", "value": true }
  ]
}
~~~

- Response 200: settings summary.
- Audit: SETTINGS_UPDATED.

POST /api/v1/jobs

Request:

~~~json
{
  "jobCode": "JOB-001",
  "positionTitle": "Senior Backend Engineer",
  "targetLevel": "Senior"
}
~~~

- Response 201 data.job: id, jobCode, positionTitle, targetLevel, createdAt, updatedAt.

GET /api/v1/jobs?query=&page=&pageSize=

- Response 200: items, page, pageSize, total.

POST /api/v1/candidates

Request:

~~~json
{
  "candidateCode": "CAND-001",
  "fullName": "Candidate Name"
}
~~~

- Response 201 data.candidate: id, candidateCode, fullName, createdAt, updatedAt.

GET /api/v1/candidates?query=&page=&pageSize=

- Response 200: items, page, pageSize, total.

### 6.2. Interview cases

POST /api/v1/interview-cases

Request:

~~~json
{
  "candidateId": "uuid",
  "jobId": "uuid",
  "scheduledAt": "2026-10-04T08:30:00.000Z",
  "assessmentDurationSeconds": 900,
  "allowIncompleteSubmit": true,
  "autoSubmitOnExpiry": true,
  "materialsPolicy": "ALLOWED",
  "internetPolicy": "RESTRICTED",
  "toolsPolicy": "NO_EXTERNAL_TOOLS",
  "committeeMembers": [
    { "displayName": "Member A", "role": "LEAD" },
    { "displayName": "Member B", "role": "MEMBER" }
  ]
}
~~~

- Response 201 data.case: id, candidate, job, status=DRAFT, policy, committeeMembers, timestamps.
- Audit: CASE_CREATED.

GET /api/v1/interview-cases?status=&candidateId=&jobId=&from=&to=&page=&pageSize=

- Response 200: items of caseSummary, page, pageSize, total.

GET /api/v1/interview-cases/{caseId}

- Response 200: caseSummary, current document status, Question Set status, attempt summary, task summary, current workflow state.
- Không trả candidate token hash hoặc secret.

PATCH /api/v1/interview-cases/{caseId}

Request chỉ cho field chưa khóa:

~~~json
{
  "scheduledAt": "2026-10-04T09:00:00.000Z",
  "materialsPolicy": "ALLOWED",
  "internetPolicy": "RESTRICTED",
  "toolsPolicy": "NO_EXTERNAL_TOOLS"
}
~~~

- Response 200: caseSummary.
- Không cho đổi candidate/job hoặc policy ảnh hưởng attempt sau khi bắt đầu.
- Audit: CASE_UPDATED.

DELETE /api/v1/interview-cases/{caseId}

Request:

~~~json
{
  "confirmation": "DELETE_CASE",
  "reason": "Duplicate case"
}
~~~

- Server backup trước, kiểm tra path, hard-delete theo Domain Specification.
- Response 204.
- Audit: CASE_DELETE_REQUESTED, CASE_DELETE_COMPLETED hoặc CASE_DELETE_FAILED.

### 6.3. Documents

POST /api/v1/interview-cases/{caseId}/documents

File request:

~~~json
{
  "documentType": "JD",
  "sourceKind": "IMPORTED_FILE",
  "originalFilename": "job-description.pdf",
  "mimeType": "application/pdf",
  "contentBase64": "base64-content"
}
~~~

Manual text request:

~~~json
{
  "documentType": "CV",
  "sourceKind": "MANUAL_TEXT",
  "text": "clean text"
}
~~~

- Response 201: document summary, extraction status, versionNo.
- Audit: DOCUMENT_IMPORTED hoặc DOCUMENT_VERSION_CREATED.
- Với PDF có extractor được cấu hình và extraction thành công, hệ thống tự động
  đặt `isAiEligible=true` và ghi audit `DOCUMENT_TEXT_AUTO_CONFIRMED`.

GET /api/v1/interview-cases/{caseId}/documents

- Response 200: document metadata và extracted text preview cho Committee.

POST /api/v1/interview-cases/{caseId}/documents/{documentId}/confirm

Request:

~~~json
{
  "confirmed": true,
  "textSha256": "64-char-sha256"
}
~~~

- Response 200: document summary và caseStatus DOCUMENTS_READY nếu đủ JD/CV.
- Audit: DOCUMENT_TEXT_CONFIRMED.

### 6.4. Question Set

POST /api/v1/interview-cases/{caseId}/question-set

Request:

~~~json
{
  "operation": "GENERATE",
  "maxQuestions": 8,
  "durationSeconds": 900,
  "questionPolicy": {
    "standardized": true,
    "situational": true,
    "cvVerification": true,
    "gapConflict": true
  },
  "forceRerun": false
}
~~~

- Response 202: taskId, status=PENDING, caseStatus=QUESTIONS_GENERATING.
- Audit: QUESTION_SET_GENERATION_REQUESTED.

GET /api/v1/interview-cases/{caseId}/question-set

- Response 200: current/draft questionSet, questions ordered by displayOrder, versions.

PATCH /api/v1/interview-cases/{caseId}/question-set

Request:

~~~json
{
  "questionSetId": "uuid",
  "questions": [
    {
      "id": "uuid-or-null",
      "displayOrder": 1,
      "questionText": "string",
      "competencyKey": "system-design",
      "sourceKind": "AI",
      "purpose": "Validate design reasoning",
      "questionType": "SCENARIO",
      "difficulty": "HARD",
      "expectedEvidence": "Concrete decisions and trade-offs",
      "rubric": {},
      "isRequired": true
    }
  ]
}
~~~

- Response 200: questionSet và questions.
- Chỉ DRAFT/GENERATED, tối đa 8 câu.
- Audit: QUESTION_SET_EDITED.

POST /api/v1/interview-cases/{caseId}/question-set/approve

Request: questionSetId, memberId, confirmation=APPROVE_QUESTION_SET.

- Response 200: approved questionSet, caseStatus=QUESTIONS_APPROVED.
- Audit: QUESTION_SET_APPROVED.

### 6.5. Assessment và Candidate Mode

POST /api/v1/interview-cases/{caseId}/assessment

Request: questionSetId.

- Preconditions: Question Set APPROVED, case READY_FOR_ASSESSMENT.
- Response 201: attempt summary.
- Chỉ tạo một attempt/case.

GET /api/v1/interview-cases/{caseId}/assessment

- Response 200: attempt summary và answerSummary answered/total.

POST /api/v1/interview-cases/{caseId}/assessment/start

Request: candidateCodeConfirmed=true, committeePinVerified=true.

- Response 200: attempt id/status/expiresAt và candidate session expiry.
- Audit: ASSESSMENT_STARTED.

GET /api/v1/assessment-attempts/{attemptId}/questions

- Candidate response chỉ có attemptId, status, expiresAt, question id/order/text/type và answer text/isAnswered/saveRevision.
- Không trả competency, purpose, expectedEvidence, rubric, AI result hoặc CV/JD.

PUT /api/v1/assessment-attempts/{attemptId}/answers/{questionId}

Request:

~~~json
{
  "text": "answer text",
  "isAnswered": true,
  "clientRevision": 3
}
~~~

- Response 200: questionId, isAnswered, saveRevision, lastSavedAt.
- Stale revision trả ANSWER_REVISION_CONFLICT.
- Attempt submitted/expired trả STATE_CONFLICT.
- Audit: ANSWER_AUTOSAVED.

POST /api/v1/assessment-attempts/{attemptId}/submit

Request: confirmation=SUBMIT_ASSESSMENT, clientRevision.

- Response 200: attempt status, submittedAt, submitReason, caseStatus.
- Submit thiếu answer được phép.
- Hết giờ dùng submitReason TIME_EXPIRED.
- Retry cùng idempotency key trả kết quả cũ.
- Audit: ASSESSMENT_SUBMITTED hoặc ASSESSMENT_AUTO_SUBMITTED.

### 6.6. AI task và evaluation

POST /api/v1/interview-cases/{caseId}/ai/evaluate

Request: attemptId, forceRerun, reason.

- Preconditions: attempt SUBMITTED/EXPIRED, approved question snapshot.
- Response 202: taskId, status=PENDING, caseStatus=AI_ANALYZING.
- Audit: AI_TASK_CREATED.

GET /api/v1/tasks/{taskId}

Response data:

~~~json
{
  "task": {
    "id": "uuid",
    "type": "EVALUATE_ASSESSMENT",
    "status": "PENDING",
    "retryCount": 0,
    "createdAt": "2026-10-04T08:30:00.000Z",
    "startedAt": null,
    "finishedAt": null,
    "errorCode": null
  },
  "result": {
    "id": null,
    "resultType": null,
    "versionNo": null
  }
}
~~~

Polling dừng ở COMPLETED/FAILED; Candidate không được gọi.

### 6.7. Interview Brief

GET /api/v1/interview-cases/{caseId}/interview-brief

- Response 200: current brief, sourceKind, versionNo, isCurrent.

POST /api/v1/interview-cases/{caseId}/interview-brief

Request:

~~~json
{
  "sourceKind": "MANUAL",
  "attemptId": "uuid",
  "brief": {
    "summary": "string",
    "strengths": [],
    "gaps": [],
    "conflicts": [],
    "competencyMatrix": [],
    "requiredLiveQuestions": [],
    "additionalLiveQuestions": [],
    "limitations": ["AI unavailable"]
  }
}
~~~

- Response 201: brief và caseStatus=INTERVIEW_BRIEF_READY.
- Audit: INTERVIEW_BRIEF_CREATED, MANUAL_FALLBACK_USED nếu manual.

### 6.8. Live Interview

POST /api/v1/interview-cases/{caseId}/live-interview/start

Request: memberId.

- Response 200: caseStatus=LIVE_INTERVIEW_IN_PROGRESS, startedAt.
- Audit: LIVE_INTERVIEW_STARTED.

POST /api/v1/interview-cases/{caseId}/live-interview/records

Request:

~~~json
{
  "briefId": "uuid",
  "committeeMemberId": "uuid",
  "sequenceNo": 1,
  "questionText": "string",
  "sourceKind": "BRIEF_RECOMMENDED",
  "askedStatus": "ASKED",
  "liveNotes": "summary",
  "score": 3,
  "evidenceStatus": "VERIFIED"
}
~~~

- Response 201: live record.
- Audit: LIVE_QUESTION_RECORDED hoặc LIVE_QUESTION_SKIPPED.

POST /api/v1/interview-cases/{caseId}/live-interview/follow-up

Request: briefId, remainingCompetencies, notes.

- Response 202: taskId/status.
- Audit: AI_TASK_CREATED.

POST /api/v1/interview-cases/{caseId}/live-interview/complete

Request: memberId, reason.

- Response 200: caseStatus=LIVE_INTERVIEW_COMPLETED, completedAt.
- Audit: LIVE_INTERVIEW_COMPLETED.

### 6.9. Final Evaluation

GET /api/v1/interview-cases/{caseId}/final-evaluation

- Response 200: current evaluation và versions.

PUT /api/v1/interview-cases/{caseId}/final-evaluation

Request gồm versionNo, status=DRAFT, finalResult, finalLevel, summary, strengths, gaps, risks, finalComment.

- Response 200: evaluation draft.
- Audit: EVALUATION_DRAFTED.

POST /api/v1/interview-cases/{caseId}/final-evaluation/finalize

Request: evaluationId, memberId, finalResult, confirmation=FINALIZE_EVALUATION.

- Preconditions: member là LEAD hoặc capability finalizer; evaluation draft hợp lệ.
- Response 200: evaluation FINAL và caseStatus=EVALUATED.
- Audit: EVALUATION_FINALIZED.

### 6.10. Backup và export

POST /api/v1/backups

Request: label, includeDocuments.

- Response 201/202: backupId, status, safePathSummary.
- Dùng SQLite Backup API, không copy db đang ghi.
- Audit: BACKUP_CREATED.

POST /api/v1/exports

Request: caseId, includeDocuments, format=ZIP.

- Response 202: taskId.
- Export không chứa API key, PIN hoặc token.
- Audit: EXPORT_CREATED.

## 7. State, audit và idempotency matrix

| Endpoint | State rule | Audit |
| --- | --- | --- |
| question-set POST generate | DOCUMENTS_READY → QUESTIONS_GENERATING | QUESTION_SET_GENERATION_REQUESTED |
| question-set approve | QUESTIONS_GENERATED → QUESTIONS_APPROVED | QUESTION_SET_APPROVED |
| assessment start | READY_FOR_ASSESSMENT → ASSESSMENT_IN_PROGRESS | ASSESSMENT_STARTED |
| answer PUT | Attempt IN_PROGRESS only | ANSWER_AUTOSAVED |
| submit | Attempt IN_PROGRESS → SUBMITTED | ASSESSMENT_SUBMITTED/AUTO_SUBMITTED |
| ai/evaluate | SUBMITTED/EXPIRED → AI_ANALYZING | AI_TASK_CREATED |
| brief manual | AI_ANALYSIS_FAILED → BRIEF_READY | MANUAL_FALLBACK_USED |
| live complete | LIVE_IN_PROGRESS → LIVE_COMPLETED | LIVE_INTERVIEW_COMPLETED |
| finalize | EVALUATION_PENDING → EVALUATED | EVALUATION_FINALIZED |

Mutations phải có X-Startup-Token, session/candidate token và Idempotency-Key theo capability. Key dùng lại với payload khác trả IDEMPOTENCY_CONFLICT.

## 8. Conflict / Assumption / Open Questions

### Conflict

- Technology Specification liệt kê path collection assessment/answers; contract này thêm path item question để autosave idempotent và vẫn giữ collection resource.
- File 19 ban đầu đánh số AI/API ngược; thứ tự chính thức là 22 AI trước 23 API.

### Assumption

- Pagination chỉ cần cho Jobs, Candidates và InterviewCases trong MVP.
- Candidate token truyền trong header/session memory, không lưu localStorage.
- Delete case Committee-only, bắt buộc backup trước và không tự scrub backup cũ.

### Open Questions / Backlog

- Streaming progress UI cho AI.
- Export PDF/HTML chính thức.
- Bulk import/export.
- API v2 khi server mode được hỗ trợ.

## 0A. Active offline HTML candidate transfer

The approved active assessment bridge is a self-contained offline HTML package. Machine B remains the only application/API host at `127.0.0.1`; machine A only opens a generated file and never connects to the application.

Primary Committee endpoints:

| Method | Route | Body/response | Policy |
| --- | --- | --- | --- |
| POST | `/api/v1/interview-cases/{caseId}/candidate-package/export` | No body; binary `text/html; charset=utf-8` attachment | Committee session + startup token |
| POST | `/api/v1/interview-cases/{caseId}/candidate-package/import` | Binary HTML body, max 10 MiB; JSON snapshot envelope | Committee session + startup token + idempotency key |

The exported package format is `candidate-html.v1`. It contains only candidate-safe question fields. The candidate submits a `RESPONSE` package; import validates the case-owned Question Set ID/version/fingerprint and exact question projection before creating an immutable `HTML_IMPORT` Assessment Snapshot. Excel export/import remains supported as an explicitly labeled fallback through the existing `/question-set/export` and `/assessment-snapshots/import` routes.

Evaluation consumes the normalized snapshot shape and records `sourceKind`, `sourceFileSha256`, and `packageId`; no HTML source or raw package bytes are sent to an AI provider.

## 9. Acceptance criteria

1. Resource map bao phủ health, jobs, candidates, cases, documents, question sets, assessment, AI, brief, live, evaluation, settings, backup/export.
2. Mỗi endpoint có method/path/mode/request hoặc input/response/effect.
3. Có success/error envelope, requestId, date/time, HTTP status và error codes.
4. Có body size, validation, upload và polling protocol.
5. Candidate API không trả dữ liệu nội bộ.
6. Mutation có state transition, audit và idempotency.
7. AI không block request và trả 202.
8. Không cần frontend/backend tự suy đoán payload cốt lõi.
