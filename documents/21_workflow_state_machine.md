# 21. Phase 2 Supervised Interview Mini Tool — Workflow State Machine

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Product Owner / BA Phase 2 |
| Last updated | 2026-10-04 |
| Depends on | 17 Context Specification; 18 Technology Specification; 19 Specification Document Set Plan; 20 Domain and Database Specification |
| Supersedes | Không có |

## 1. Mục tiêu

Tài liệu này chốt state machine, transition, actor, precondition, postcondition, side effect, error, retry, recovery và idempotency cho InterviewCase, AssessmentAttempt và AiTask.

Tài liệu không định nghĩa HTTP payload hoặc UI layout. API phải dùng các transition trong tài liệu này; UI không được tự đổi state bằng cách ghi trực tiếp vào database.

## 2. Nguyên tắc

- Một transition là một transaction nghiệp vụ.
- Domain service là nơi quyết định transition; AI provider không tự đổi workflow state.
- Mọi transition quan trọng ghi AuditLog.
- Transition lặp lại an toàn phải idempotent; transition mâu thuẫn trả STATE_CONFLICT.
- Không xóa hoặc overwrite snapshot đã được dùng.
- Answer đã submit/expired là immutable.
- Một case chỉ có một AssessmentAttempt ở MVP; không reopen và không tạo attempt thứ hai trong cùng case.
- AI failure không làm mất answer và luôn mở manual fallback.
- Startup recovery không giả định request AI hoặc timer cũ còn đang chạy.

## 3. State groups

### 3.1. InterviewCase state

~~~text
DRAFT
DOCUMENTS_READY
QUESTIONS_GENERATING
QUESTIONS_GENERATED
QUESTIONS_APPROVED
READY_FOR_ASSESSMENT
ASSESSMENT_IN_PROGRESS
ASSESSMENT_SUBMITTED
AI_ANALYZING
INTERVIEW_BRIEF_READY
LIVE_INTERVIEW_IN_PROGRESS
LIVE_INTERVIEW_COMPLETED
EVALUATION_PENDING
EVALUATED

DOCUMENT_PARSE_FAILED
QUESTION_GENERATION_FAILED
ASSESSMENT_INTERRUPTED
ASSESSMENT_EXPIRED
AI_ANALYSIS_FAILED
CANDIDATE_NO_SHOW
CANCELLED
~~~

### 3.2. AssessmentAttempt state

~~~text
READY_FOR_ASSESSMENT
ASSESSMENT_IN_PROGRESS
ASSESSMENT_SUBMITTED
ASSESSMENT_INTERRUPTED
ASSESSMENT_EXPIRED
~~~

ASSESSMENT_SUBMITTED và ASSESSMENT_EXPIRED là terminal state trong MVP.

### 3.3. AiTask state

~~~text
PENDING
RUNNING
PENDING_RETRY
COMPLETED
FAILED
~~~

COMPLETED và FAILED là terminal state. PENDING_RETRY chỉ được dùng trong giới hạn retry đã chốt.

## 4. State diagram

~~~mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> DOCUMENTS_READY: confirm documents
    DRAFT --> CANCELLED: cancel case
    DOCUMENTS_READY --> QUESTIONS_GENERATING: request generation
    DOCUMENTS_READY --> DOCUMENT_PARSE_FAILED: parse/validation failure
    DOCUMENT_PARSE_FAILED --> DOCUMENTS_READY: replace or paste text
    QUESTIONS_GENERATING --> QUESTIONS_GENERATED: AI task completed
    QUESTIONS_GENERATING --> QUESTION_GENERATION_FAILED: AI task failed
    QUESTION_GENERATION_FAILED --> QUESTIONS_GENERATING: retry
    QUESTION_GENERATION_FAILED --> QUESTIONS_GENERATED: manual questions
    QUESTIONS_GENERATED --> QUESTIONS_APPROVED: committee approves
    QUESTIONS_APPROVED --> READY_FOR_ASSESSMENT: prepare check-in
    READY_FOR_ASSESSMENT --> ASSESSMENT_IN_PROGRESS: candidate starts
    READY_FOR_ASSESSMENT --> CANDIDATE_NO_SHOW: coordinator marks no-show
    ASSESSMENT_IN_PROGRESS --> ASSESSMENT_SUBMITTED: submit or auto-submit
    ASSESSMENT_IN_PROGRESS --> ASSESSMENT_INTERRUPTED: recoverable interruption
    ASSESSMENT_INTERRUPTED --> ASSESSMENT_IN_PROGRESS: resume before expiry
    ASSESSMENT_INTERRUPTED --> ASSESSMENT_EXPIRED: timer cannot resume
    ASSESSMENT_SUBMITTED --> AI_ANALYZING: queue evaluation
    ASSESSMENT_EXPIRED --> AI_ANALYZING: answers available
    AI_ANALYZING --> INTERVIEW_BRIEF_READY: valid AI result
    AI_ANALYZING --> AI_ANALYSIS_FAILED: AI failure
    AI_ANALYSIS_FAILED --> INTERVIEW_BRIEF_READY: manual fallback brief
    AI_ANALYSIS_FAILED --> EVALUATION_PENDING: manual review without brief
    INTERVIEW_BRIEF_READY --> LIVE_INTERVIEW_IN_PROGRESS: committee starts
    LIVE_INTERVIEW_IN_PROGRESS --> LIVE_INTERVIEW_COMPLETED: committee completes
    LIVE_INTERVIEW_COMPLETED --> EVALUATION_PENDING: evidence complete
    EVALUATION_PENDING --> EVALUATED: committee finalizes
    EVALUATED --> [*]
    CANCELLED --> [*]
    CANDIDATE_NO_SHOW --> [*]

    state AiTask {
        [*] --> PENDING
        PENDING --> RUNNING: worker claims
        RUNNING --> COMPLETED: valid output
        RUNNING --> PENDING_RETRY: retryable error
        PENDING_RETRY --> RUNNING: retry
        RUNNING --> FAILED: terminal error
        PENDING_RETRY --> FAILED: retry exhausted
        COMPLETED --> [*]
        FAILED --> [*]
    }
~~~

## 5. Transition contract

### 5.1. InterviewCase transitions

| ID | From | To | Actor | Preconditions | Postconditions / side effects |
| --- | --- | --- | --- | --- | --- |
| WF-CASE-001 | — | DRAFT | HR_COORDINATOR/COMMITTEE | Candidate, Job và case fields hợp lệ | Tạo case, audit CASE_CREATED |
| WF-CASE-002 | DRAFT | DOCUMENTS_READY | HR_COORDINATOR/COMMITTEE | Current JD và CV đã confirmed, text AI-eligible | Case đủ input; audit DOCUMENTS_CONFIRMED |
| WF-CASE-003 | DRAFT/DOCUMENTS_READY | DOCUMENT_PARSE_FAILED | SYSTEM | Extract/validation không thành công | Lưu lỗi document; answer không liên quan; audit DOCUMENT_PARSE_FAILED |
| WF-CASE-004 | DOCUMENT_PARSE_FAILED | DOCUMENTS_READY | HR_COORDINATOR/COMMITTEE | Có document version mới hoặc manual text confirmed | Version cũ giữ nguyên; audit DOCUMENT_VERSION_CREATED |
| WF-CASE-005 | DOCUMENTS_READY | QUESTIONS_GENERATING | COMMITTEE/HR_COORDINATOR | JD/CV current và policy hợp lệ | Tạo AiTask GENERATE_QUESTIONS PENDING; audit QUESTION_SET_GENERATION_REQUESTED |
| WF-CASE-006 | QUESTIONS_GENERATING | QUESTIONS_GENERATED | SYSTEM | AiTask completed và output schema hợp lệ | Tạo proposed Question Set/questions; audit QUESTION_SET_GENERATED |
| WF-CASE-007 | QUESTIONS_GENERATING | QUESTION_GENERATION_FAILED | SYSTEM | Task terminal failed hoặc output invalid sau retry | Giữ document; cho manual question path; audit QUESTION_GENERATION_FAILED |
| WF-CASE-008 | QUESTION_GENERATION_FAILED | QUESTIONS_GENERATING | COMMITTEE/HR_COORDINATOR | Request retry có idempotency key mới | Tạo task version mới; không overwrite task cũ |
| WF-CASE-009 | QUESTION_GENERATION_FAILED | QUESTIONS_GENERATED | COMMITTEE | HĐCM tạo đủ câu hỏi thủ công | Tạo Question Set source MANUAL; audit QUESTION_SET_MANUAL_CREATED |
| WF-CASE-010 | QUESTIONS_GENERATED | QUESTIONS_APPROVED | COMMITTEE | Có 5–8 câu, rubric/evidence/competency đầy đủ | Question Set APPROVED immutable; audit QUESTION_SET_APPROVED |
| WF-CASE-011 | QUESTIONS_APPROVED | READY_FOR_ASSESSMENT | COMMITTEE/HR_COORDINATOR | Có approved set, case policy và check-in sẵn sàng | Cho phép tạo attempt; audit ASSESSMENT_READY |
| WF-CASE-012 | READY_FOR_ASSESSMENT | ASSESSMENT_IN_PROGRESS | COMMITTEE/HR_COORDINATOR | Đã xác minh candidate, PIN hợp lệ, approved set | Tạo attempt/token hash và timer; vào Candidate Mode; audit ASSESSMENT_STARTED |
| WF-CASE-013 | READY_FOR_ASSESSMENT | CANDIDATE_NO_SHOW | HR_COORDINATOR/COMMITTEE | Hết ngưỡng chờ theo policy | Terminal no-show; audit CANDIDATE_NO_SHOW |
| WF-CASE-014 | ASSESSMENT_IN_PROGRESS | ASSESSMENT_SUBMITTED | CANDIDATE/SYSTEM/COMMITTEE | Submit idempotent; answer cuối đã flush | Khóa answers, ghi submitted_at/reason; audit ASSESSMENT_SUBMITTED hoặc AUTO_SUBMITTED |
| WF-CASE-015 | ASSESSMENT_IN_PROGRESS | ASSESSMENT_INTERRUPTED | SYSTEM | App crash/close bất thường trước submit | Attempt interrupted; answer đã commit vẫn còn; audit ASSESSMENT_INTERRUPTED |
| WF-CASE-016 | ASSESSMENT_INTERRUPTED | ASSESSMENT_IN_PROGRESS | COMMITTEE/CANDIDATE | PIN/token hợp lệ, expires_at còn hiệu lực | Resume cùng attempt; không tạo attempt mới |
| WF-CASE-017 | ASSESSMENT_INTERRUPTED | ASSESSMENT_EXPIRED | SYSTEM | Timer đã hết hoặc resume không an toàn | Khóa answer; giữ dữ liệu đã commit; audit ASSESSMENT_EXPIRED |
| WF-CASE-018 | ASSESSMENT_SUBMITTED/ASSESSMENT_EXPIRED | AI_ANALYZING | SYSTEM/COMMITTEE | Có answer snapshot và chưa có current result tương ứng | Tạo AiTask EVALUATE_ASSESSMENT; audit AI_TASK_CREATED |
| WF-CASE-019 | AI_ANALYZING | INTERVIEW_BRIEF_READY | SYSTEM | AI result hợp lệ hoặc manual brief được tạo | Brief current; audit INTERVIEW_BRIEF_CREATED |
| WF-CASE-020 | AI_ANALYZING | AI_ANALYSIS_FAILED | SYSTEM | Retry exhausted, provider/schema failure | Answer vẫn đọc được; mở manual fallback; audit AI_TASK_FAILED |
| WF-CASE-021 | AI_ANALYSIS_FAILED | INTERVIEW_BRIEF_READY | COMMITTEE | HĐCM tạo manual brief hoặc xác nhận brief đủ dùng | Brief source MANUAL; audit MANUAL_FALLBACK_USED |
| WF-CASE-022 | AI_ANALYSIS_FAILED | EVALUATION_PENDING | COMMITTEE | HĐCM bỏ qua brief và đủ điều kiện đánh giá trực tiếp | Cho phép live/final workflow theo policy |
| WF-CASE-023 | INTERVIEW_BRIEF_READY | LIVE_INTERVIEW_IN_PROGRESS | COMMITTEE | HĐCM vào live workspace | Ghi live start; audit LIVE_INTERVIEW_STARTED |
| WF-CASE-024 | LIVE_INTERVIEW_IN_PROGRESS | LIVE_INTERVIEW_COMPLETED | COMMITTEE | HĐCM kết thúc hoặc stop condition đạt | Ghi live completion; audit LIVE_INTERVIEW_COMPLETED |
| WF-CASE-025 | LIVE_INTERVIEW_COMPLETED | EVALUATION_PENDING | COMMITTEE | Live records đã lưu; không còn câu bắt buộc chưa xử lý | Tạo evaluation draft; audit EVALUATION_PENDING |
| WF-CASE-026 | EVALUATION_PENDING | EVALUATED | COMMITTEE | Final result hợp lệ, lead/finalizer xác nhận | Evaluation FINAL; audit EVALUATION_FINALIZED |
| WF-CASE-027 | DRAFT/DOCUMENTS_READY/QUESTIONS_GENERATED/READY_FOR_ASSESSMENT | CANCELLED | HR_COORDINATOR/COMMITTEE | Có lý do hủy và chưa bắt đầu attempt | Terminal cancelled; audit CASE_CANCELLED |

Case không cho phép transition ngược tùy ý. Mọi transition không có trong bảng trả INVALID_TRANSITION hoặc STATE_CONFLICT.

### 5.2. AssessmentAttempt transitions

| ID | From | To | Actor | Preconditions | Side effect |
| --- | --- | --- | --- | --- | --- |
| WF-ATT-001 | — | READY_FOR_ASSESSMENT | COMMITTEE/SYSTEM | Case QUESTIONS_APPROVED | Tạo một attempt duy nhất |
| WF-ATT-002 | READY_FOR_ASSESSMENT | ASSESSMENT_IN_PROGRESS | COMMITTEE/CANDIDATE | Check-in và token/PIN hợp lệ | started_at, expires_at, Candidate Mode |
| WF-ATT-003 | ASSESSMENT_IN_PROGRESS | ASSESSMENT_SUBMITTED | CANDIDATE | Submit chưa thành công trước đó | Flush answer, khóa attempt |
| WF-ATT-004 | ASSESSMENT_IN_PROGRESS | ASSESSMENT_SUBMITTED | SYSTEM | expires_at <= now và auto_submit_on_expiry=1 | Auto-submit, reason TIME_EXPIRED |
| WF-ATT-005 | ASSESSMENT_IN_PROGRESS | ASSESSMENT_INTERRUPTED | SYSTEM | Crash/unclean shutdown | Không xóa draft answer |
| WF-ATT-006 | ASSESSMENT_INTERRUPTED | ASSESSMENT_IN_PROGRESS | COMMITTEE/CANDIDATE | Token hợp lệ, timer chưa hết | Resume cùng attempt |
| WF-ATT-007 | ASSESSMENT_INTERRUPTED | ASSESSMENT_EXPIRED | SYSTEM | Timer hết hoặc recovery không an toàn | Khóa answer hiện có |
| WF-ATT-008 | ASSESSMENT_SUBMITTED/ASSESSMENT_EXPIRED | — | ANY | Mọi update answer/reopen | INVALID_ATTEMPT_STATE; không ghi dữ liệu |

### 5.3. AiTask transitions

| ID | From | To | Actor | Preconditions | Side effect |
| --- | --- | --- | --- | --- | --- |
| WF-AI-001 | — | PENDING | Application Service | Input manifest, fingerprint và idempotency key hợp lệ | Persist task rồi enqueue |
| WF-AI-002 | PENDING/PENDING_RETRY | RUNNING | AI Worker | Worker claim thành công | started_at; không tạo thread không giới hạn |
| WF-AI-003 | RUNNING | COMPLETED | AI Worker | HTTP response JSON schema hợp lệ | Persist AiResult version; task immutable |
| WF-AI-004 | RUNNING | PENDING_RETRY | AI Worker | Timeout/network/429/5xx hoặc repairable schema error; retry_count < max_retry | retry_count tăng; backoff |
| WF-AI-005 | RUNNING | FAILED | AI Worker | 4xx payload/auth, invalid after retry hoặc fatal error | error_code/message safe; manual fallback |
| WF-AI-006 | PENDING_RETRY | RUNNING | AI Worker | Backoff elapsed | Retry cùng input fingerprint |
| WF-AI-007 | RUNNING | PENDING_RETRY/FAILED | SYSTEM | Startup recovery thấy task RUNNING từ process trước | Không giả định request tiếp tục |
| WF-AI-008 | COMPLETED | — | Application | Force rerun | Tạo task mới, key mới, result version mới; không đổi task cũ |

## 6. Idempotency và concurrency

### 6.1. Idempotency key

- Generate questions: key gồm case_id, current document content hashes, question policy version và operation nonce.
- Submit attempt: client gửi key; server lưu kết quả submit đầu tiên. Retry cùng key trả cùng trạng thái.
- Save answer: key gồm attempt_id, question_id và client revision; revision cũ hơn không được ghi đè revision mới.
- AI evaluation: key gồm attempt_id, question_set_id, answer snapshot fingerprint và prompt/schema version.
- Finalize evaluation: key gồm case_id, evaluation draft version và finalizer member id.

### 6.2. SQLite transaction

- Claim task, update state và tạo audit nằm trong transaction ngắn.
- Submit answer cuối, khóa attempt và tạo audit nằm trong một transaction.
- Approve Question Set phải tạo immutable snapshot và chuyển status trong cùng transaction.
- Không giữ transaction trong thời gian gọi AI hoặc đọc file lớn.
- Mỗi operation dùng connection riêng, foreign_keys=ON và busy_timeout=5000.

## 7. Error state và recovery

| Error | State/result | Recovery |
| --- | --- | --- |
| Unsupported/malformed document | DOCUMENT_PARSE_FAILED | Replace file hoặc paste text; giữ snapshot lỗi để audit |
| AI timeout/network | PENDING_RETRY rồi FAILED nếu hết retry | Retry một lần; manual fallback |
| AI invalid JSON/schema | PENDING_RETRY rồi FAILED | Repair instruction một lần; không ghi result thành công |
| Duplicate submit | State giữ nguyên | Trả response idempotent |
| Save answer stale revision | Không đổi row mới | Trả ANSWER_REVISION_CONFLICT và fetch latest |
| SQLite locked | Operation fail transient | Retry ngắn theo database policy; không retry vô hạn |
| Crash khi candidate nhập | ATTEMPT_INTERRUPTED khi restart | Resume nếu còn hạn; nếu không thì EXPIRED |
| Crash khi AI RUNNING | PENDING_RETRY hoặc FAILED | Recovery worker xử lý theo retry_count |
| Port/server restart | Không đổi domain state | Browser reconnect; đọc state từ SQLite |
| Backup failure trước delete | Không xóa | CASE_DELETE_BLOCKED, yêu cầu backup lại |

## 8. Candidate Mode và Committee Mode

### Candidate Mode

Candidate chỉ được xem câu hỏi của attempt, lưu answer và submit. Candidate không được đọc case, document, rubric, AI result, brief, live record, evaluation hoặc task.

### Committee Mode

Committee/HR được thực hiện các transition theo actor matrix, nhưng Candidate Mode không thể gọi Committee transition chỉ bằng frontend state. Backend phải validate capability/session/token.

## 9. Audit mapping

| Transition group | Audit action |
| --- | --- |
| Case create/update/cancel | CASE_CREATED, CASE_UPDATED, CASE_CANCELLED |
| Document confirm/version | DOCUMENT_TEXT_CONFIRMED, DOCUMENT_VERSION_CREATED |
| Question generation/approval | QUESTION_SET_GENERATION_REQUESTED, QUESTION_SET_GENERATED, QUESTION_SET_APPROVED |
| Attempt start/resume | ASSESSMENT_STARTED, ASSESSMENT_RESUMED |
| Answer save/submit | ANSWER_AUTOSAVED, ASSESSMENT_SUBMITTED, ASSESSMENT_AUTO_SUBMITTED |
| AI queue/retry/fail | AI_TASK_CREATED, AI_TASK_RETRIED, AI_TASK_FAILED, AI_RESULT_RERUN |
| Brief/manual fallback | INTERVIEW_BRIEF_CREATED, MANUAL_FALLBACK_USED |
| Live interview | LIVE_INTERVIEW_STARTED, LIVE_QUESTION_RECORDED, LIVE_INTERVIEW_COMPLETED |
| Evaluation | EVALUATION_DRAFTED, EVALUATION_FINALIZED, EVALUATION_REVISED |
| Delete/backup | BACKUP_CREATED, CASE_DELETE_REQUESTED, CASE_DELETE_COMPLETED, CASE_DELETE_FAILED |

## 10. Restart recovery

Startup order:

1. Acquire single-instance lock.
2. Open SQLite connections and apply existing migrations.
3. Find AiTask RUNNING từ process trước; chuyển thành PENDING_RETRY nếu còn retry, nếu không FAILED.
4. Find AssessmentAttempt IN_PROGRESS không có heartbeat mới hơn shutdown boundary; chuyển ATTEMPT_INTERRUPTED.
5. Với attempt interrupted, không tự động mở Candidate Mode. HĐCM phải xác thực và resume.
6. Nếu expires_at đã qua, auto-submit nếu answer/DB còn đủ; nếu không thì ASSESSMENT_EXPIRED.
7. Rebuild in-memory queue từ AiTask PENDING/PENDING_RETRY.
8. Không tạo lại AiResult cho task COMPLETED.

## 11. Conflict / Assumption / Open Questions

### Conflict

- Context dùng state AI_ANALYZING và AI_ANALYSIS_FAILED; Technology dùng task state PENDING/RUNNING/COMPLETED/FAILED. Tài liệu này giữ cả hai lớp: AiTask state cho background work và InterviewCase state cho business workflow.
- Context cho phép “auto-submit hoặc khóa” khi hết giờ; quyết định MVP đã chốt auto-submit. ASSESSMENT_EXPIRED chỉ dùng cho failure/recovery không thể auto-submit an toàn.

### Assumption

- HĐCM là actor xác nhận resume, manual fallback và final evaluation; không có role/account tập trung trong MVP.
- Case cancellation chỉ được phép trước khi attempt bắt đầu; cần hủy sau đó sẽ tạo audit/manual process riêng.
- Live Interview có thể đi thẳng tới EVALUATION_PENDING trong manual fallback nếu HĐCM đủ evidence.

### Open Questions / Backlog

- Chính sách check-in muộn và ngưỡng no-show cụ thể.
- Có cần heartbeat UI để phát hiện đóng browser nhanh hơn recovery khi restart hay không.
- Multi-machine/server mode sau MVP.

## 12. Acceptance criteria

1. Mọi action MVP trong Context Specification có transition rõ ràng.
2. InterviewCase, AssessmentAttempt và AiTask có state list và diagram.
3. Mỗi transition có actor, precondition, postcondition/side effect và audit.
4. Submit thiếu answer, auto-submit và answer lock được mô tả rõ.
5. Attempt đã submit không có transition reopen.
6. AI retry, failure, manual fallback, restart recovery và idempotency được mô tả.
7. AI provider không tự thay đổi workflow state.
8. Candidate Mode và Committee Mode có boundary rõ.
9. Không có transition ngầm hoặc transition cho phép overwrite snapshot.
10. Có conflict, assumption, backlog và requirement ID.
