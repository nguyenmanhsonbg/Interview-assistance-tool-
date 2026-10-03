# 24. Phase 2 Supervised Interview Mini Tool — Frontend UI Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Product Owner / UX + Frontend |
| Last updated | 2026-10-04 |
| Depends on | 17 Context Specification; 18 Technology Specification; 20 Domain and Database Specification; 21 Workflow State Machine; 23 API Contract Specification |
| Supersedes | Không có |

## 1. Mục tiêu và ranh giới

Frontend là HTML5, CSS3 và Vanilla JavaScript ES Modules, gọi REST API bằng fetch(). Không có frontend framework, third-party UI library hoặc build step trong MVP.

UI có hai capability boundary:

- Committee Mode: chuẩn bị, xem, duyệt, phân tích, phỏng vấn trực tiếp và chốt.
- Candidate Mode: chỉ làm bài, autosave và submit.

Candidate Mode không hiển thị CV, JD nội bộ, rubric, expected evidence, AI evaluation, Interview Brief, live notes, evaluation hoặc menu quản trị.

## 2. Route map

### Committee routes

| Route | Screen | Entry state |
| --- | --- | --- |
| /cases | Interview Case List | Any Committee session |
| /cases/new | Create Interview Case | Committee |
| /cases/:caseId | Case Overview | Case exists |
| /cases/:caseId/documents | Import and Confirm Documents | DRAFT/DOCUMENT_PARSE_FAILED |
| /cases/:caseId/questions | Question Review and Approval | QUESTIONS_GENERATED |
| /cases/:caseId/check-in | Candidate Check-in | READY_FOR_ASSESSMENT |
| /cases/:caseId/ai | AI Evaluation Status/Result | ASSESSMENT_SUBMITTED/AI_ANALYZING |
| /cases/:caseId/brief | Interview Brief | INTERVIEW_BRIEF_READY |
| /cases/:caseId/live | Live Interview Workspace | INTERVIEW_BRIEF_READY/LIVE_INTERVIEW_IN_PROGRESS |
| /cases/:caseId/evaluation | Final Evaluation | EVALUATION_PENDING/EVALUATED |
| /settings | AI and Application Settings | Committee |
| /backups | Backup and Export | Committee |

### Candidate routes

| Route | Screen | Entry state |
| --- | --- | --- |
| /candidate/start | Candidate instructions | Candidate session |
| /candidate/assessment | Candidate Assessment | ASSESSMENT_IN_PROGRESS |
| /candidate/submitted | Submitted/Waiting | ASSESSMENT_SUBMITTED/EXPIRED |

Candidate session token chỉ tồn tại trong memory của tab/session; không đưa vào URL, localStorage hoặc log.

## 3. Global components và UI state

| Component | Behavior |
| --- | --- |
| AppShell | Committee navigation; ẩn hoàn toàn trong Candidate Mode |
| StatusBadge | Render enum state bằng text an toàn |
| ErrorBanner | Hiển thị safe error code/message và retry action |
| ConfirmDialog | Xác nhận approval, submit, finalize, delete |
| TaskProgress | Poll taskId; dừng ở COMPLETED/FAILED |
| SaveIndicator | SAVING, SAVED, SAVE_FAILED |
| Timer | Dùng expiresAt server; không tin client clock |
| AuditToast | Feedback sau mutation thành công |
| EmptyState | Hướng dẫn action tiếp theo |

Untrusted text từ candidate/AI/document luôn render bằng textContent. Không dùng innerHTML, eval hoặc new Function.

## 4. Screen specification

### 4.1. Interview Case List — /cases

- Actor: Committee/HR.
- API: GET cases, POST case, GET jobs/candidates.
- Fields: search, status filter, scheduled date, candidate code, position.
- Actions: Create, Open, Backup, Delete.
- Loading: skeleton/list spinner.
- Empty: hướng dẫn tạo case.
- Error: retry list, giữ filter.
- Locked: case EVALUATED không cho sửa workflow.
- Accessibility: table semantics, keyboard focus, status text không chỉ dùng màu.

### 4.2. Create/Edit Interview Case — /cases/new hoặc /cases/:id

- Fields bắt buộc: candidateCode/candidateId, fullName khi tạo Candidate, position/job, targetLevel, scheduledAt, duration.
- Defaults: 8 questions qua policy, 900 seconds, allow incomplete submit=true, auto-submit=true.
- Policy fields: materials, Internet, tools.
- Committee members: displayName, role MEMBER/LEAD; tối đa một LEAD.
- Validation: UUID/reference tồn tại, duration >0, date ISO, non-empty name/title/level.
- Actions: Save Draft, Add Member, Remove unsaved Member, Continue Documents, Cancel.
- API: POST/PATCH case, POST candidate/job.
- Disabled: candidate/job và assessment policy khóa khi attempt bắt đầu.

### 4.3. Import JD and CV — /cases/:id/documents

- Fields: type JD/CV, file selector hoặc paste text, sourceKind.
- File UI: filename, size, type, parse status, SHA-256 summary.
- Actions: Upload, Parse, Replace with new version, Confirm extracted text.
- API: POST documents, GET documents, POST confirm.
- Loading: parse progress/status; không block app shell.
- Error: unsupported format, too large, parse failed, paste fallback.
- Locked: Candidate không truy cập; sau assessment bắt đầu không thay snapshot current cho attempt.
- Security: không preview raw HTML; text-only display.

### 4.4. Question Generation Status — /cases/:id/questions?mode=status

- Shows task status PENDING/RUNNING/COMPLETED/FAILED/PENDING_RETRY.
- API: POST question-set generate, GET task, GET question-set.
- Actions: Retry, Create Manual Questions, Open Draft.
- Error: AI failure giữ original document and answer state; show manual fallback.
- Empty: chưa có task; CTA Generate.

### 4.5. Question Review and Approval — /cases/:id/questions

- Data per question: order, text, competency, source, purpose, type, difficulty, expected evidence, rubric, required.
- Actions: Edit, Add, Delete, Reorder, Generate Again, Save Draft, Approve.
- Validation: 5–8 questions, order 1..8, non-empty evidence/purpose/rubric, duration 600–900.
- API: GET/PATCH question-set, POST approve.
- Locked: after attempt started, current set read-only.
- Confirmation: approval warns that snapshot will be immutable.
- Success: status QUESTIONS_APPROVED and CTA Check-in.

### 4.6. Candidate Check-in — /cases/:id/check-in

- Shows candidate code/name, schedule, policy, approved question set summary.
- Actions: Verify candidate, Enter Committee PIN, Start Candidate Mode, Mark No-show.
- API: GET case, GET assessment, POST assessment, POST assessment/start.
- Validation: candidateCode confirmed and approved set exists.
- Error: wrong PIN, wrong state, duplicate attempt.
- Success: open Candidate Mode in same browser and hide Committee navigation.

### 4.7. Candidate Assessment — /candidate/assessment

- Shows instructions, question text, textarea, progress answered/total, server-based timer.
- Does not show rubric, competency, expected evidence, JD/CV or AI data.
- Autosave: debounce 500–1000 ms; SaveIndicator; flush last change before submit.
- API: GET attempt questions, PUT answer.
- Loading: disable only current field during save; do not block other safe navigation.
- Error: show save failed and retry; never clear local draft.
- Locked: when submitted/expired, redirect to /candidate/submitted.
- Accessibility: labeled textareas, visible focus, timer announced appropriately, keyboard submit dialog.

### 4.8. Submitted / Waiting — /candidate/submitted

- Shows completion message, submittedAt and no internal result.
- API: GET attempt safe summary if needed.
- No back-to-answer action.
- Refresh must remain on locked state.

### 4.9. AI Evaluation Result — /cases/:id/ai

- Shows task status, provider status safe, result version, confidence, limitations, per-answer evaluation and evidence.
- API: GET task, GET case/brief, Committee only.
- Actions: Retry/rerun with reason, Open answer, Manual fallback.
- Error: AI failed message with original answers available.
- Locked: no direct mutation of AI result; override is a separate HĐCM action/audit.

### 4.10. Interview Brief — /cases/:id/brief

- Shows summary, completion, strengths, gaps, conflicts, competency matrix, 3 required live questions, max 2 extra, signals, confidence and limitations.
- API: GET brief.
- Actions: Start Live Interview, Create Manual Brief when AI failed.
- Empty: no brief; show manual fallback if state allows.
- Rendering: all AI content text-only.

### 4.11. Live Interview Workspace — /cases/:id/live

- Shows brief side panel, ordered live records, question text, notes, score 0–4, evidence status, asked/skipped state.
- Actions: Start, Add Manual Question, Ask, Skip, Save Note, Request Follow-up, Complete.
- API: live start, records, follow-up task, complete.
- Validation: sequence unique, score 0–4, evidence enum, notes optional.
- Conflict flag: mark PRE_ASSESSMENT_AND_LIVE_ANSWER_CONFLICT and require reason.
- Error: autosave-like retry for records; do not lose typed notes.

### 4.12. Final Evaluation — /cases/:id/evaluation

- Shows evidence summary, live records, current evaluation and prior versions.
- Fields: finalResult enum, finalLevel optional text, summary, strengths, gaps, risks, finalComment.
- Actions: Save Draft, Finalize, Create Revision.
- Validation: finalization requires finalResult, finalizer member and confirmation.
- Confirmation: final is immutable; revision requires reason.
- API: GET/PUT evaluation, POST finalize.
- Success: case EVALUATED, display report/export CTA.

### 4.13. Settings — /settings

- Fields: AI provider/model display, endpoint display without secret, timeout/retry, assessment defaults, retention MANUAL_ONLY.
- Secret fields never prefilled or rendered.
- API: GET/PATCH settings.
- Validation: safe numeric range, known enum, invalid config fails clearly.

### 4.14. Backup and Export — /backups

- Actions: Create SQLite backup, Export ZIP, view status.
- Fields: label, includeDocuments, caseId, format.
- API: POST backups/exports, GET task.
- Confirmation: backup/export contains candidate data and must be protected.
- Error: show backup required/provider/task failure.

## 5. Responsive and accessibility baseline

- Candidate UI ưu tiên full-screen, readable text, no horizontal scroll.
- Committee UI responsive tối thiểu cho 1280px desktop; bảng có alternate stacked layout.
- Mọi input có label và error text liên kết bằng aria-describedby.
- Keyboard navigation đầy đủ; focus visible.
- Dialog trap focus và Escape chỉ đóng khi chưa commit.
- Không dùng màu là tín hiệu duy nhất.
- Timer có text và aria-live phù hợp, cảnh báo không làm mất input.

## 6. Security rules

- XSS prevention bằng textContent.
- Không render raw AI/document HTML.
- Không expose API key/PIN/candidate token trong source, URL hoặc localStorage.
- Không giữ Committee route state trong Candidate Mode.
- Backend là authorization boundary; UI hide không phải security control.
- Browser cache/no-store và refresh không được làm mất answer đã autosave.

## 7. Conflict / Assumption / Open Questions

### Conflict

- Context nói Candidate Mode là desktop controlled; Technology dùng browser localhost. UI giải quyết bằng same-origin localhost, fullscreen là biện pháp hỗ trợ chứ không phải proctoring.
- API resource dùng singular question-set; UI dùng cùng resource, không tạo endpoint khác.

### Assumption

- Một tab/browser instance phục vụ tuần tự Committee rồi Candidate; không hỗ trợ đồng thời nhiều candidate.
- UI polling task dùng interval giới hạn và dừng ở terminal state.
- Manual fallback là thao tác Committee, không phải Candidate.

### Open Questions / Backlog

- Visual design system và branding.
- Automated browser test framework sau khi có Node/build decision.
- Native kiosk mode nếu pilot yêu cầu.

## 8. Acceptance criteria

1. Có route map cho toàn bộ flow MVP.
2. Có screen/component/field/action/API/state cho từng bước.
3. Committee Mode và Candidate Mode tách biệt.
4. Candidate không thấy dữ liệu nội bộ.
5. Autosave debounce, flush trước submit và locked state sau submit rõ.
6. Loading, empty, error, disabled/locked và success feedback được định nghĩa.
7. Có accessibility baseline và responsive behavior.
8. Untrusted content dùng text-only rendering.
9. Không UI action nào thiếu API dependency hoặc state rule.
