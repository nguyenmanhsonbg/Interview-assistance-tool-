# 20. Phase 2 Supervised Interview Mini Tool — Domain and Database Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Product Owner / BA Phase 2 |
| Last updated | 2026-10-04 |
| Depends on | 17_phase2_supervised_interview_mini_tool_context_specification.md; 18_phase2_supervised_interview_technology_specification.md; 19_phase2_specification_document_set_plan.md |
| Supersedes | Không có |

## 1. Mục tiêu và phạm vi

Tài liệu này chốt domain model và schema SQLite cho Phase 2 Supervised Interview Mini Tool. Đây là nguồn sự thật chính cho entity, field, relationship, constraint, index, data lifecycle và migration ban đầu.

Tài liệu chỉ thiết kế dữ liệu cho MVP. Tài liệu không triển khai source code, migration thực tế, API, frontend, prompt hoặc state machine chi tiết. Các nội dung đó sẽ được chốt trong các specification tiếp theo theo thứ tự tại tài liệu 19.

### 1.1. Phạm vi dữ liệu trong MVP

- Một Interview Case cho một candidate và một job/position.
- JD và CV được lưu dưới dạng document snapshot có version.
- Question Set được lưu theo version; Question Set đã dùng cho attempt là bất biến.
- Candidate có một Assessment Attempt duy nhất trong một case ở MVP.
- Candidate được phép submit khi chưa trả lời hết; answer chưa trả lời được lưu rõ là chưa được đánh giá.
- Hết thời gian mặc định sẽ auto-submit.
- AI task và AI result được lưu bền vững, có provider/model/prompt/schema version và không ghi đè kết quả cũ.
- Interview Brief, Live Interview Record và Final Evaluation được lưu local-first.
- Nhiều thành viên HĐCM có thể được gắn vào một case; một thành viên có thể là lead/finalizer.
- Dữ liệu không tự động hết hạn hoặc tự động xóa. Xóa là thao tác thủ công có backup và audit.

### 1.2. Ranh giới kỹ thuật

Schema phải phù hợp với các quyết định trong Technology Specification:

- Python 3.10+ Standard Library và sqlite3.
- SQLite tại %LOCALAPPDATA%\ClawCV\database\clawcv.db.
- SQLite WAL, foreign_keys và busy_timeout theo connection policy.
- Timestamp lưu UTC ISO 8601 dạng TEXT.
- SQL migration có version; migration chạy trong transaction.
- Không ORM, không framework bên thứ ba và không database server.
- File binary và document text lưu trên local filesystem; database chỉ lưu relative path và metadata cần thiết.
- JSON lưu dạng TEXT và được validate tại application boundary bằng Python Standard Library.

## 2. Nguyên tắc domain

### 2.1. InterviewCase là aggregate root

InterviewCase sở hữu workflow dữ liệu của một phiên phỏng vấn. Document, Question Set, Assessment Attempt, AI processing, Interview Brief, Live Interview Record và Evaluation đều phải truy được từ case.

Candidate và Job là các entity có thể được nhiều case tham chiếu. Xóa một case không tự động xóa Candidate hoặc Job nếu chúng còn được case khác tham chiếu.

### 2.2. Snapshot và version là bắt buộc

- JD/CV không được cập nhật tại chỗ sau khi đã dùng làm input; bản mới là Document version mới.
- Question Set được chỉnh sửa trước approval, sau đó approval tạo snapshot bất biến.
- Answer không được chỉnh sửa sau submit.
- AI result rerun tạo version mới và giữ lại version cũ.
- Interview Brief và Final Evaluation có version để hỗ trợ revision có audit.

### 2.3. HĐCM là người quyết định

Database lưu AI output để tham khảo, nhưng không có field hoặc trigger nào tự động biến AI score thành Final Evaluation. Chỉ Final Evaluation do HĐCM xác nhận mới là kết luận của case.

### 2.4. Dữ liệu không tin cậy và tối thiểu hóa dữ liệu AI

- Nội dung JD, CV và answer được lưu như dữ liệu, không phải instruction.
- AI task chỉ lưu manifest/reference đến snapshot và answer; raw file không được đưa vào AI payload.
- Remote AI provider chỉ nhận text đã làm sạch theo chính sách SANITIZED_TEXT_ONLY.
- Không lưu API key, PIN, session token hoặc candidate token dạng plain text.
- Audit/log không chứa full CV, full answer, raw AI payload hoặc secret.

## 3. Domain entity và trách nhiệm

| Entity / table | Trách nhiệm |
| --- | --- |
| Job | Lưu position title, target level và mã job tối thiểu cho case. Không phải recruitment workflow tổng thể. |
| Candidate | Lưu candidate code và tên cần thiết cho một case. |
| InterviewCase | Aggregate root; liên kết candidate, job, policy, lịch và case status. |
| InterviewCaseCommitteeMember | Danh sách thành viên HĐCM của case và lead/finalizer; không phải tài khoản đăng nhập. |
| Document | Snapshot metadata và extracted text của JD/CV theo version. |
| QuestionSet | Version của bộ câu hỏi, policy thời lượng, rubric snapshot và trạng thái approval. |
| Question | Một câu hỏi thuộc một Question Set snapshot. |
| AssessmentAttempt | Một phiên Candidate Mode, timer, token hash và trạng thái submit. |
| Answer | Answer theo attempt và question, hỗ trợ autosave trước submit. |
| AiTask | Công việc AI bền vững, trạng thái queue/retry/recovery và input manifest. |
| AiResult | Output AI đã validate, metadata provenance và version immutable. |
| InterviewBrief | Bản brief đọc nhanh cho HĐCM, từ AI hoặc manual fallback. |
| LiveInterviewRecord | Câu hỏi trực tiếp, ghi chú, điểm, evidence status và follow-up. |
| Evaluation | Kết luận cuối do HĐCM tạo/chốt; có revision nhưng không overwrite im lặng. |
| AuditLog | Append-only record cho thao tác quan trọng; không FK để vẫn tồn tại sau hard delete. |
| AppSetting | Cấu hình không phải secret và reference tới secret được bảo vệ bởi Windows DPAPI. |
| SchemaMigration | Version migration đã áp dụng. |

## 4. Kiểu dữ liệu và quy ước chung

| Quy ước | Quy định |
| --- | --- |
| ID | TEXT chứa UUID lower-case do application tạo bằng uuid.uuid4(). |
| Boolean | INTEGER, chỉ nhận 0 hoặc 1. |
| Timestamp | TEXT UTC ISO 8601, ví dụ 2026-10-04T08:30:00.000Z. |
| Enum | TEXT với CHECK constraint tại database và validation tại domain service. |
| JSON | TEXT UTF-8. Object/array phải được parse và validate bằng json trước khi ghi. |
| Hash | TEXT lower-case SHA-256 hex 64 ký tự. |
| Relative path | TEXT tương đối với %LOCALAPPDATA%\ClawCV; không lưu absolute path nếu không cần. |
| Secret | BLOB hoặc protected reference đã mã hóa bằng Windows DPAPI; không dùng value_text plain text. |
| Empty text | Text bắt buộc dùng CHECK length(trim(value)) > 0; text optional dùng NULL thay vì chuỗi rỗng. |
| Delete strategy | Không soft-delete tràn lan. Case-owned data hard-delete trong thao tác xóa thủ công; AuditLog giữ độc lập. |

## 5. Enum và policy cố định

### 5.1. Interview Case status

Các giá trị được Context Specification định nghĩa:

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

Transition và actor được phép chuyển trạng thái sẽ được chốt trong 21_workflow_state_machine.md. Schema chỉ giới hạn giá trị hợp lệ, không tự động thực hiện business transition.

### 5.2. Assessment policy đã chốt

- Số câu mặc định: 8.
- Thời lượng mặc định: 900 giây, tương đương 15 phút.
- Số câu và thời lượng có thể được cấu hình theo case/Question Set trong giới hạn MVP.
- Candidate được phép submit dù còn answer chưa trả lời.
- Answer chưa trả lời phải giữ trạng thái UNANSWERED và được AI/manual evaluation coi là NOT_ASSESSED.
- Hết thời gian mặc định chuyển sang auto-submit với submit reason TIME_EXPIRED.
- Attempt đã submit hoặc expired không được mở lại hoặc sửa.
- Trường hợp đặc biệt cần làm lại phải tạo Interview Case mới ở MVP.

### 5.3. Scoring và rubric

- Score tổng của một answer dùng integer từ 0 đến 4.
- Rubric mặc định được dùng chung, nhưng Question Set/question được lưu một rubric snapshot riêng để không bị thay đổi khi policy tương lai thay đổi.
- Database không tự tính weighted score. Nếu có weight hoặc dimension detail, lưu trong rubric_json và validated output; quy tắc tính sẽ do AI Assessment Specification chốt.
- Evidence status dùng các giá trị: VERIFIED, PARTIALLY_VERIFIED, UNVERIFIED, CONFLICTING, NOT_MET, NOT_ASSESSED.

### 5.4. Final Evaluation

final_result dùng các giá trị:

~~~text
PASS
FAIL
NEXT_ROUND
NEEDS_ADDITIONAL_ASSESSMENT
PENDING
~~~

AI không được ghi trực tiếp final_result. final_level là TEXT optional vì danh sách level cuối chưa được chốt trong các tài liệu nền tảng.

## 6. Data dictionary

Các bảng dưới đây là schema chính thức đề xuất cho migration 001. Cột “Null” dùng N cho NOT NULL và Y cho nullable.

### 6.1. schema_migrations

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| version | INTEGER | N | — | PK; version > 0 | Migration version |
| applied_at | TEXT | N | UTC now | — | Thời điểm áp dụng |

### 6.2. jobs

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Job UUID |
| job_code | TEXT | Y | NULL | UNIQUE nếu có giá trị | Mã job do người dùng nhập |
| position_title | TEXT | N | — | CHECK không rỗng | Tên vị trí |
| target_level | TEXT | N | — | CHECK không rỗng | Level mục tiêu |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Job không chứa raw JD. JD là Document snapshot thuộc InterviewCase.

### 6.3. candidates

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Candidate UUID |
| candidate_code | TEXT | N | — | UNIQUE; CHECK không rỗng | Mã ứng viên |
| full_name | TEXT | N | — | CHECK không rỗng | Tên hiển thị cần thiết |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Không thêm email, số điện thoại hoặc địa chỉ vào MVP nếu không có yêu cầu nghiệp vụ trực tiếp.

### 6.4. interview_cases

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Case UUID |
| candidate_id | TEXT | N | — | FK candidates(id), ON DELETE RESTRICT | Candidate của case |
| job_id | TEXT | N | — | FK jobs(id), ON DELETE RESTRICT | Job/position của case |
| status | TEXT | N | DRAFT | CHECK theo Case status enum | Case workflow state |
| scheduled_at | TEXT | Y | NULL | UTC ISO 8601 nếu có | Lịch phỏng vấn |
| assessment_duration_seconds | INTEGER | N | 900 | CHECK > 0; domain default 900 | Thời lượng assessment |
| allow_incomplete_submit | INTEGER | N | 1 | CHECK 0/1 | Cho submit thiếu answer |
| auto_submit_on_expiry | INTEGER | N | 1 | CHECK 0/1 | Auto-submit khi hết giờ |
| materials_policy | TEXT | N | NOT_SPECIFIED | CHECK không rỗng | Chính sách tài liệu |
| internet_policy | TEXT | N | NOT_SPECIFIED | CHECK không rỗng | Chính sách Internet |
| tools_policy | TEXT | N | NOT_SPECIFIED | CHECK không rỗng | Chính sách công cụ hỗ trợ |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Case không có cột deleted_at. Xóa case là hard delete có kiểm soát.

### 6.5. interview_case_committee_members

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Membership UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| display_name | TEXT | N | — | CHECK không rỗng | Tên thành viên HĐCM |
| role | TEXT | N | MEMBER | CHECK MEMBER/LEAD | Vai trò trong case |
| display_order | INTEGER | N | 1 | CHECK > 0 | Thứ tự hiển thị |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

UNIQUE(interview_case_id, display_name). Partial unique index bảo đảm tối đa một LEAD trong một case. Bảng này không đại diện cho user account hoặc authentication.

### 6.6. documents

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Document UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case sở hữu snapshot |
| document_type | TEXT | N | — | CHECK JD/CV | Loại tài liệu |
| version_no | INTEGER | N | 1 | CHECK > 0; UNIQUE(case, type, version) | Version snapshot |
| source_kind | TEXT | N | — | CHECK IMPORTED_FILE/MANUAL_TEXT/PHASE1_CLEAN_SNAPSHOT | Nguồn dữ liệu |
| extraction_status | TEXT | N | PENDING | CHECK PENDING/SUCCEEDED/FAILED/MANUAL_CONFIRMED | Trạng thái extract |
| original_filename | TEXT | Y | NULL | Không dùng làm path | Tên hiển thị gốc |
| mime_type | TEXT | Y | NULL | — | MIME đã kiểm tra |
| file_size_bytes | INTEGER | Y | NULL | CHECK >= 0 nếu có | Kích thước file |
| file_sha256 | TEXT | Y | NULL | CHECK 64 hex nếu có | Hash file gốc |
| content_sha256 | TEXT | N | — | CHECK 64 hex | Hash extracted/canonical text |
| storage_path | TEXT | Y | NULL | Relative path; CHECK không chứa traversal | Path file local |
| extracted_text | TEXT | N | '' | — | Text đã extract/làm sạch |
| is_ai_eligible | INTEGER | N | 0 | CHECK 0/1 | Đã đủ điều kiện làm AI input |
| is_current | INTEGER | N | 1 | CHECK 0/1 | Snapshot hiện hành |
| confirmed_at | TEXT | Y | NULL | — | HĐCM xác nhận extracted text |
| supersedes_document_id | TEXT | Y | NULL | FK documents(id), ON DELETE SET NULL | Version trước |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

CHECK bảo đảm storage_path và file_sha256 cùng NULL hoặc cùng có giá trị. Manual text có thể không có file nhưng phải có content_sha256.

### 6.7. question_sets

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Question Set UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| version_no | INTEGER | N | 1 | CHECK > 0; UNIQUE(case, version) | Version bộ câu hỏi |
| status | TEXT | N | DRAFT | CHECK DRAFT/GENERATED/APPROVED/SUPERSEDED | Trạng thái review |
| duration_seconds | INTEGER | N | 900 | CHECK BETWEEN 600 AND 900 | Thời lượng Question Set |
| rubric_policy_json | TEXT | N | '{}' | JSON object do application validate | Rubric snapshot |
| question_policy_json | TEXT | N | '{}' | JSON object do application validate | Policy/mix snapshot |
| approved_by_member_id | TEXT | Y | NULL | FK committee member, ON DELETE SET NULL | Người approval |
| approved_at | TEXT | Y | NULL | — | Thời điểm approval |
| supersedes_question_set_id | TEXT | Y | NULL | FK question_sets(id), ON DELETE SET NULL | Version trước |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Partial unique index bảo đảm mỗi case chỉ có một Question Set APPROVED hiện hành. Khi cần sửa sau approval, tạo version mới; không sửa âm thầm version cũ.

### 6.8. questions

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Question UUID |
| question_set_id | TEXT | N | — | FK question_sets(id), ON DELETE CASCADE | Question Set snapshot |
| display_order | INTEGER | N | — | CHECK BETWEEN 1 AND 8; UNIQUE(set, order) | Thứ tự |
| question_text | TEXT | N | — | CHECK không rỗng | Nội dung câu hỏi |
| competency_key | TEXT | N | — | CHECK không rỗng | Năng lực được đánh giá |
| source_kind | TEXT | N | — | CHECK STANDARDIZED/SITUATIONAL/CV_VERIFICATION/GAP_CONFLICT/QUESTION_BANK/MANUAL/AI | Nguồn câu hỏi |
| purpose | TEXT | N | — | CHECK không rỗng | Mục đích |
| question_type | TEXT | N | SHORT_TEXT | CHECK SHORT_TEXT/LONG_TEXT/SCENARIO | Loại câu hỏi |
| difficulty | TEXT | N | MEDIUM | CHECK EASY/MEDIUM/HARD | Độ khó |
| expected_evidence | TEXT | N | — | CHECK không rỗng | Bằng chứng mong đợi |
| rubric_json | TEXT | N | '{}' | JSON object do application validate | Rubric snapshot của câu |
| is_required | INTEGER | N | 1 | CHECK 0/1 | Câu bắt buộc |
| estimated_seconds | INTEGER | Y | NULL | CHECK > 0 nếu có | Thời gian ước lượng |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

MVP giới hạn tối đa 8 câu trong một Question Set. Question Bank nếu có chỉ cung cấp nguồn câu hỏi; câu được chọn phải được copy thành row bất biến trong Question Set, không cần bảng Question Bank tập trung.

### 6.9. assessment_attempts

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Attempt UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE; UNIQUE | Một attempt/case ở MVP |
| question_set_id | TEXT | N | — | FK question_sets(id), ON DELETE RESTRICT | Snapshot dùng để làm bài |
| status | TEXT | N | READY_FOR_ASSESSMENT | CHECK READY_FOR_ASSESSMENT/ASSESSMENT_IN_PROGRESS/ASSESSMENT_SUBMITTED/ASSESSMENT_INTERRUPTED/ASSESSMENT_EXPIRED | Attempt state |
| candidate_token_hash | TEXT | Y | NULL | UNIQUE nếu có; không lưu token gốc | Candidate access token hash |
| started_at | TEXT | Y | NULL | — | Bắt đầu làm bài |
| expires_at | TEXT | Y | NULL | — | Hạn timer |
| submitted_at | TEXT | Y | NULL | — | Thời điểm submit/auto-submit |
| submit_reason | TEXT | Y | NULL | CHECK MANUAL/AUTO_SUBMIT/TIME_EXPIRED/RECOVERY nếu có | Lý do kết thúc |
| allow_answer_edit | INTEGER | N | 1 | CHECK 0/1 | Cho sửa trước submit |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Do quyết định không mở lại bài đã submit, attempt đã kết thúc không được đổi question_set_id, answer hoặc timer.

### 6.10. answers

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Answer UUID |
| assessment_attempt_id | TEXT | N | — | FK assessment_attempts(id), ON DELETE CASCADE | Attempt |
| question_id | TEXT | N | — | FK questions(id), ON DELETE RESTRICT | Question snapshot |
| answer_text | TEXT | N | '' | CHECK nếu answered thì không rỗng | Nội dung answer |
| is_answered | INTEGER | N | 0 | CHECK 0/1 | Có nội dung hay chưa |
| save_revision | INTEGER | N | 0 | CHECK >= 0 | Số lần autosave |
| last_saved_at | TEXT | Y | NULL | — | Autosave cuối |
| submitted_at | TEXT | Y | NULL | — | Copy timestamp khi submit |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

UNIQUE(assessment_attempt_id, question_id). Service phải xác minh question thuộc đúng Question Set của attempt. Khi attempt ở trạng thái submitted/expired, answer bị khóa bằng cả domain rule và database trigger.

### 6.11. ai_tasks

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | AI task UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| assessment_attempt_id | TEXT | Y | NULL | FK assessment_attempts(id), ON DELETE CASCADE | Attempt nếu là evaluation |
| task_type | TEXT | N | — | CHECK GENERATE_QUESTIONS/EVALUATE_ASSESSMENT/GENERATE_BRIEF/SUGGEST_FOLLOW_UP | Capability |
| status | TEXT | N | PENDING | CHECK PENDING/RUNNING/COMPLETED/FAILED/PENDING_RETRY | Queue state |
| idempotency_key | TEXT | N | — | UNIQUE | Chống duplicate operation |
| input_fingerprint | TEXT | N | — | CHECK 64 hex | Fingerprint input snapshot |
| input_manifest_json | TEXT | N | '{}' | JSON object | ID/hash tham chiếu input |
| redaction_policy | TEXT | N | SANITIZED_TEXT_ONLY | CHECK SANITIZED_TEXT_ONLY | Data policy |
| provider | TEXT | Y | NULL | — | Provider thực tế |
| model | TEXT | Y | NULL | — | Model thực tế |
| prompt_key | TEXT | Y | NULL | — | Prompt identifier |
| prompt_version | TEXT | Y | NULL | — | Prompt version |
| schema_version | TEXT | Y | NULL | — | Output schema version |
| retry_count | INTEGER | N | 0 | CHECK >= 0 | Số lần retry |
| max_retry | INTEGER | N | 1 | CHECK >= 0 | Giới hạn retry |
| error_code | TEXT | Y | NULL | — | Error code safe |
| error_message | TEXT | Y | NULL | Không chứa raw payload | Thông tin lỗi an toàn |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| started_at | TEXT | Y | NULL | — | Worker bắt đầu |
| finished_at | TEXT | Y | NULL | — | Kết thúc |

Task RUNNING khi restart phải được recovery thành FAILED hoặc PENDING_RETRY theo workflow policy; không giả định request cũ còn chạy.

### 6.12. ai_results

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Result UUID |
| ai_task_id | TEXT | N | — | FK ai_tasks(id), ON DELETE CASCADE; UNIQUE | Task sinh result |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| assessment_attempt_id | TEXT | Y | NULL | FK assessment_attempts(id), ON DELETE CASCADE | Attempt nếu có |
| question_set_id | TEXT | Y | NULL | FK question_sets(id), ON DELETE RESTRICT | Question Set nếu có |
| result_type | TEXT | N | — | CHECK QUESTION_GENERATION/ANSWER_EVALUATION/INTERVIEW_BRIEF/FOLLOW_UP | Loại output |
| version_no | INTEGER | N | 1 | CHECK > 0; UNIQUE(case, type, version) | Version result |
| supersedes_result_id | TEXT | Y | NULL | FK ai_results(id), ON DELETE SET NULL | Result cũ |
| payload_json | TEXT | N | — | JSON object đã validate | Output đầy đủ |
| confidence | REAL | Y | NULL | CHECK 0.0 <= confidence AND confidence <= 1.0 | Confidence AI |
| is_current | INTEGER | N | 1 | CHECK 0/1 | Version hiện hành |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

Result cũ không bị overwrite. Rerun tạo task/result/version mới; application chuyển is_current trong một transaction.

### 6.13. interview_briefs

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Brief UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| assessment_attempt_id | TEXT | N | — | FK assessment_attempts(id), ON DELETE CASCADE | Attempt nguồn |
| ai_result_id | TEXT | Y | NULL | FK ai_results(id), ON DELETE SET NULL | AI result nguồn |
| source_kind | TEXT | N | AI | CHECK AI/MANUAL | AI hoặc manual fallback |
| status | TEXT | N | READY | CHECK DRAFT/READY/SUPERSEDED | Brief state |
| version_no | INTEGER | N | 1 | CHECK > 0; UNIQUE(case, version) | Brief version |
| supersedes_brief_id | TEXT | Y | NULL | FK interview_briefs(id), ON DELETE SET NULL | Brief cũ |
| brief_json | TEXT | N | '{}' | JSON object đã validate | Summary/matrix/gap/question |
| is_current | INTEGER | N | 1 | CHECK 0/1 | Version hiện hành |
| created_by_member_id | TEXT | Y | NULL | FK committee member, ON DELETE SET NULL | Người tạo/manual override |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

AI Brief phải có: summary, completion, strengths, gaps, conflicts, competency matrix, 3 câu hỏi bắt buộc, tối đa 2 câu bổ sung, answer signals, confidence và limitations. Các chi tiết lưu trong brief_json theo schema AI.

### 6.14. live_interview_records

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Live record UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| interview_brief_id | TEXT | Y | NULL | FK interview_briefs(id), ON DELETE SET NULL | Brief nguồn |
| committee_member_id | TEXT | Y | NULL | FK committee member, ON DELETE SET NULL | Người ghi nhận |
| sequence_no | INTEGER | N | — | CHECK > 0; UNIQUE(case, sequence) | Thứ tự |
| question_text | TEXT | N | — | CHECK không rỗng | Câu hỏi thực tế |
| source_kind | TEXT | N | — | CHECK BRIEF_RECOMMENDED/MANUAL/FOLLOW_UP/AI_SUGGESTED | Nguồn |
| asked_status | TEXT | N | PLANNED | CHECK PLANNED/ASKED/SKIPPED | Đã hỏi/bỏ qua |
| live_notes | TEXT | Y | NULL | — | Ghi chú và tóm tắt câu trả lời |
| score | INTEGER | Y | NULL | CHECK 0..4 nếu có | Điểm HĐCM |
| evidence_status | TEXT | Y | NULL | CHECK theo Evidence enum nếu có | Trạng thái bằng chứng |
| asked_at | TEXT | Y | NULL | — | Thời điểm hỏi |
| completed_at | TEXT | Y | NULL | — | Thời điểm hoàn tất record |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

Nếu live answer mâu thuẫn với written answer, live_notes/evidence_status là căn cứ của HĐCM; service phải tạo audit/flag tương ứng.

### 6.15. evaluations

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Evaluation UUID |
| interview_case_id | TEXT | N | — | FK interview_cases(id), ON DELETE CASCADE | Case |
| version_no | INTEGER | N | 1 | CHECK > 0; UNIQUE(case, version) | Revision |
| status | TEXT | N | DRAFT | CHECK DRAFT/FINAL | Trạng thái chốt |
| final_result | TEXT | N | PENDING | CHECK theo Final Evaluation enum | Kết luận |
| final_level | TEXT | Y | NULL | — | Level cuối nếu HĐCM dùng |
| summary | TEXT | Y | NULL | — | Tóm tắt |
| strengths_json | TEXT | N | '[]' | JSON array | Điểm mạnh |
| gaps_json | TEXT | N | '[]' | JSON array | Gap |
| risks_json | TEXT | N | '[]' | JSON array | Rủi ro |
| final_comment | TEXT | Y | NULL | — | Nhận xét chốt |
| decided_by_member_id | TEXT | Y | NULL | FK committee member, ON DELETE SET NULL | Người chốt |
| decided_at | TEXT | Y | NULL | Required khi FINAL | Thời điểm chốt |
| supersedes_evaluation_id | TEXT | Y | NULL | FK evaluations(id), ON DELETE SET NULL | Evaluation cũ |
| is_current | INTEGER | N | 1 | CHECK 0/1 | Revision hiện hành |
| created_at | TEXT | N | UTC now | — | Thời điểm tạo |

CHECK: Evaluation FINAL phải có decided_by_member_id và decided_at. Chỉnh sửa kết quả đã chốt tạo row version mới và audit reason.

### 6.16. audit_logs

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| id | TEXT | N | — | PK | Audit UUID |
| actor_type | TEXT | N | — | CHECK SYSTEM/AI/HR_COORDINATOR/COMMITTEE/CANDIDATE | Actor |
| actor_ref_id | TEXT | Y | NULL | Không FK bắt buộc | ID tham chiếu nếu có |
| action | TEXT | N | — | CHECK không rỗng | Hành động |
| entity_type | TEXT | N | — | CHECK không rỗng | Loại entity |
| entity_id | TEXT | N | — | Không FK để giữ audit sau delete | Entity bị tác động |
| request_id | TEXT | Y | NULL | — | HTTP/request correlation |
| metadata_json | TEXT | N | '{}' | JSON object, không PII/raw payload | Metadata đã redact |
| created_at | TEXT | N | UTC now | — | Thời điểm |

AuditLog append-only. Không UPDATE/DELETE audit trong thao tác nghiệp vụ thông thường.

### 6.17. app_settings

| Field | SQLite type | Null | Default | Key / constraint | Mục đích |
| --- | --- | --- | --- | --- | --- |
| key | TEXT | N | — | PK | Setting key |
| value_type | TEXT | N | — | CHECK STRING/INTEGER/BOOLEAN/JSON/SECRET_REF | Kiểu giá trị |
| value_text | TEXT | Y | NULL | NULL nếu secret | Giá trị không nhạy cảm |
| protected_value | BLOB | Y | NULL | Dữ liệu DPAPI nếu secret | Secret protected |
| is_sensitive | INTEGER | N | 0 | CHECK 0/1 | Đánh dấu secret |
| updated_at | TEXT | N | UTC now | — | Thời điểm cập nhật |

CHECK: is_sensitive=1 phải dùng protected_value và không dùng value_text; is_sensitive=0 không chứa protected secret. API key không được lưu plain text.

## 7. Relationship và cardinality

| Quan hệ | Cardinality | Quy tắc |
| --- | --- | --- |
| Job → InterviewCase | 1:N | Một job có thể có nhiều candidate case; xóa job bị chặn nếu còn case. |
| Candidate → InterviewCase | 1:N | Một candidate có thể có nhiều case; mỗi case đúng một candidate. |
| InterviewCase → CommitteeMember | 1:N | Nhiều thành viên; tối đa một LEAD. |
| InterviewCase → Document | 1:N | Nhiều version nhưng một current JD và một current CV. |
| InterviewCase → QuestionSet | 1:N | Nhiều version; tối đa một APPROVED current. |
| QuestionSet → Question | 1:N | Tối đa 8 câu ở MVP; thứ tự unique trong set. |
| InterviewCase → AssessmentAttempt | 1:1 ở MVP | Một attempt duy nhất; không reopen/không retry trong cùng case. |
| AssessmentAttempt → Answer | 1:N | Tối đa một answer cho mỗi question. |
| InterviewCase → AiTask | 1:N | Task bền vững, có thể failed/rerun. |
| AiTask → AiResult | 1:0..1 | Task failed không có result thành công. |
| AssessmentAttempt → InterviewBrief | 1:N | Brief có version; tối đa một current. |
| InterviewCase → LiveInterviewRecord | 1:N | Sequence tăng dần, có thể planned/asked/skipped. |
| InterviewCase → Evaluation | 1:N | Revision có version; tối đa một current. |
| Case-owned entity → AuditLog | 1:N logical | Audit không dùng FK để tồn tại sau hard delete. |
| AppSetting | độc lập | Không thuộc case. |
| SchemaMigration | độc lập | Theo dõi migration version. |

## 8. ER diagram

~~~mermaid
erDiagram
    JOBS ||--o{ INTERVIEW_CASES : has
    CANDIDATES ||--o{ INTERVIEW_CASES : assessed_in
    INTERVIEW_CASES ||--o{ COMMITTEE_MEMBERS : includes
    INTERVIEW_CASES ||--o{ DOCUMENTS : snapshots
    INTERVIEW_CASES ||--o{ QUESTION_SETS : versions
    QUESTION_SETS ||--|{ QUESTIONS : contains
    INTERVIEW_CASES ||--o| ASSESSMENT_ATTEMPTS : has_one_in_mvp
    QUESTION_SETS ||--o{ ASSESSMENT_ATTEMPTS : used_by
    ASSESSMENT_ATTEMPTS ||--|{ ANSWERS : contains
    QUESTIONS ||--o{ ANSWERS : answered_as
    INTERVIEW_CASES ||--o{ AI_TASKS : queues
    ASSESSMENT_ATTEMPTS ||--o{ AI_TASKS : may_trigger
    AI_TASKS ||--o| AI_RESULTS : produces
    QUESTION_SETS ||--o{ AI_RESULTS : may_contextualize
    ASSESSMENT_ATTEMPTS ||--o{ AI_RESULTS : may_evaluate
    INTERVIEW_CASES ||--o{ INTERVIEW_BRIEFS : versions
    AI_RESULTS ||--o{ INTERVIEW_BRIEFS : may_generate
    INTERVIEW_BRIEFS ||--o{ LIVE_INTERVIEW_RECORDS : informs
    INTERVIEW_CASES ||--o{ LIVE_INTERVIEW_RECORDS : records
    INTERVIEW_CASES ||--o{ EVALUATIONS : concludes
    COMMITTEE_MEMBERS ||--o{ EVALUATIONS : decides
    COMMITTEE_MEMBERS ||--o{ LIVE_INTERVIEW_RECORDS : records

    JOBS {
        TEXT id PK
        TEXT job_code UK
        TEXT position_title
        TEXT target_level
    }
    CANDIDATES {
        TEXT id PK
        TEXT candidate_code UK
        TEXT full_name
    }
    INTERVIEW_CASES {
        TEXT id PK
        TEXT candidate_id FK
        TEXT job_id FK
        TEXT status
        TEXT scheduled_at
        INTEGER assessment_duration_seconds
    }
    COMMITTEE_MEMBERS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT display_name
        TEXT role
    }
    DOCUMENTS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT document_type
        INTEGER version_no
        TEXT content_sha256
        TEXT extracted_text
    }
    QUESTION_SETS {
        TEXT id PK
        TEXT interview_case_id FK
        INTEGER version_no
        TEXT status
        INTEGER duration_seconds
    }
    QUESTIONS {
        TEXT id PK
        TEXT question_set_id FK
        INTEGER display_order
        TEXT competency_key
        TEXT rubric_json
    }
    ASSESSMENT_ATTEMPTS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT question_set_id FK
        TEXT status
        TEXT expires_at
    }
    ANSWERS {
        TEXT id PK
        TEXT assessment_attempt_id FK
        TEXT question_id FK
        TEXT answer_text
        INTEGER is_answered
    }
    AI_TASKS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT task_type
        TEXT status
        TEXT input_fingerprint
    }
    AI_RESULTS {
        TEXT id PK
        TEXT ai_task_id FK
        TEXT result_type
        INTEGER version_no
        TEXT payload_json
    }
    INTERVIEW_BRIEFS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT ai_result_id FK
        INTEGER version_no
        TEXT brief_json
    }
    LIVE_INTERVIEW_RECORDS {
        TEXT id PK
        TEXT interview_case_id FK
        TEXT interview_brief_id FK
        INTEGER sequence_no
        INTEGER score
    }
    EVALUATIONS {
        TEXT id PK
        TEXT interview_case_id FK
        INTEGER version_no
        TEXT status
        TEXT final_result
    }

## 9. SQLite DDL đề xuất cho migration 001

DDL dưới đây là contract của migration ban đầu, không phải migration thực tế. Migration implementation phải đặt trong migrations/001_initial.sql và chạy trong transaction.

~~~sql
PRAGMA foreign_keys = ON;

CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    job_code TEXT UNIQUE,
    position_title TEXT NOT NULL CHECK (length(trim(position_title)) > 0),
    target_level TEXT NOT NULL CHECK (length(trim(target_level)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE candidates (
    id TEXT PRIMARY KEY,
    candidate_code TEXT NOT NULL UNIQUE CHECK (length(trim(candidate_code)) > 0),
    full_name TEXT NOT NULL CHECK (length(trim(full_name)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE interview_cases (
    id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL REFERENCES candidates(id) ON DELETE RESTRICT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN (
        'DRAFT', 'DOCUMENTS_READY', 'QUESTIONS_GENERATING',
        'QUESTIONS_GENERATED', 'QUESTIONS_APPROVED',
        'READY_FOR_ASSESSMENT', 'ASSESSMENT_IN_PROGRESS',
        'ASSESSMENT_SUBMITTED', 'AI_ANALYZING',
        'INTERVIEW_BRIEF_READY', 'LIVE_INTERVIEW_IN_PROGRESS',
        'LIVE_INTERVIEW_COMPLETED', 'EVALUATION_PENDING', 'EVALUATED',
        'DOCUMENT_PARSE_FAILED', 'QUESTION_GENERATION_FAILED',
        'ASSESSMENT_INTERRUPTED', 'ASSESSMENT_EXPIRED',
        'AI_ANALYSIS_FAILED', 'CANDIDATE_NO_SHOW', 'CANCELLED'
    )),
    scheduled_at TEXT,
    assessment_duration_seconds INTEGER NOT NULL DEFAULT 900
        CHECK (assessment_duration_seconds > 0),
    allow_incomplete_submit INTEGER NOT NULL DEFAULT 1
        CHECK (allow_incomplete_submit IN (0, 1)),
    auto_submit_on_expiry INTEGER NOT NULL DEFAULT 1
        CHECK (auto_submit_on_expiry IN (0, 1)),
    materials_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    internet_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    tools_policy TEXT NOT NULL DEFAULT 'NOT_SPECIFIED',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE interview_case_committee_members (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
    role TEXT NOT NULL DEFAULT 'MEMBER' CHECK (role IN ('MEMBER', 'LEAD')),
    display_order INTEGER NOT NULL DEFAULT 1 CHECK (display_order > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, display_name)
);

CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    document_type TEXT NOT NULL CHECK (document_type IN ('JD', 'CV')),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN ('IMPORTED_FILE', 'MANUAL_TEXT', 'PHASE1_CLEAN_SNAPSHOT')
    ),
    extraction_status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        extraction_status IN ('PENDING', 'SUCCEEDED', 'FAILED', 'MANUAL_CONFIRMED')
    ),
    original_filename TEXT,
    mime_type TEXT,
    file_size_bytes INTEGER CHECK (file_size_bytes IS NULL OR file_size_bytes >= 0),
    file_sha256 TEXT CHECK (
        file_sha256 IS NULL OR length(file_sha256) = 64
    ),
    content_sha256 TEXT NOT NULL CHECK (length(content_sha256) = 64),
    storage_path TEXT,
    extracted_text TEXT NOT NULL DEFAULT '',
    is_ai_eligible INTEGER NOT NULL DEFAULT 0 CHECK (is_ai_eligible IN (0, 1)),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    confirmed_at TEXT,
    supersedes_document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, document_type, version_no),
    CHECK (
        (storage_path IS NULL AND file_sha256 IS NULL)
        OR (storage_path IS NOT NULL AND file_sha256 IS NOT NULL)
    )
);

CREATE TABLE question_sets (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT', 'GENERATED', 'APPROVED', 'SUPERSEDED')
    ),
    duration_seconds INTEGER NOT NULL DEFAULT 900
        CHECK (duration_seconds BETWEEN 600 AND 900),
    rubric_policy_json TEXT NOT NULL DEFAULT '{}',
    question_policy_json TEXT NOT NULL DEFAULT '{}',
    approved_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    approved_at TEXT,
    supersedes_question_set_id TEXT
        REFERENCES question_sets(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no)
);

CREATE TABLE questions (
    id TEXT PRIMARY KEY,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE CASCADE,
    display_order INTEGER NOT NULL CHECK (display_order BETWEEN 1 AND 8),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    competency_key TEXT NOT NULL CHECK (length(trim(competency_key)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'STANDARDIZED', 'SITUATIONAL', 'CV_VERIFICATION',
            'GAP_CONFLICT', 'QUESTION_BANK', 'MANUAL', 'AI'
        )
    ),
    purpose TEXT NOT NULL CHECK (length(trim(purpose)) > 0),
    question_type TEXT NOT NULL DEFAULT 'SHORT_TEXT' CHECK (
        question_type IN ('SHORT_TEXT', 'LONG_TEXT', 'SCENARIO')
    ),
    difficulty TEXT NOT NULL DEFAULT 'MEDIUM' CHECK (
        difficulty IN ('EASY', 'MEDIUM', 'HARD')
    ),
    expected_evidence TEXT NOT NULL CHECK (length(trim(expected_evidence)) > 0),
    rubric_json TEXT NOT NULL DEFAULT '{}',
    is_required INTEGER NOT NULL DEFAULT 1 CHECK (is_required IN (0, 1)),
    estimated_seconds INTEGER CHECK (
        estimated_seconds IS NULL OR estimated_seconds > 0
    ),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (question_set_id, display_order)
);

CREATE TABLE assessment_attempts (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL UNIQUE
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    question_set_id TEXT NOT NULL
        REFERENCES question_sets(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'READY_FOR_ASSESSMENT' CHECK (
        status IN (
            'READY_FOR_ASSESSMENT', 'ASSESSMENT_IN_PROGRESS',
            'ASSESSMENT_SUBMITTED', 'ASSESSMENT_INTERRUPTED',
            'ASSESSMENT_EXPIRED'
        )
    ),
    candidate_token_hash TEXT UNIQUE,
    started_at TEXT,
    expires_at TEXT,
    submitted_at TEXT,
    submit_reason TEXT CHECK (
        submit_reason IS NULL OR submit_reason IN (
            'MANUAL', 'AUTO_SUBMIT', 'TIME_EXPIRED', 'RECOVERY'
        )
    ),
    allow_answer_edit INTEGER NOT NULL DEFAULT 1
        CHECK (allow_answer_edit IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE answers (
    id TEXT PRIMARY KEY,
    assessment_attempt_id TEXT NOT NULL
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL
        REFERENCES questions(id) ON DELETE RESTRICT,
    answer_text TEXT NOT NULL DEFAULT '',
    is_answered INTEGER NOT NULL DEFAULT 0 CHECK (is_answered IN (0, 1)),
    save_revision INTEGER NOT NULL DEFAULT 0 CHECK (save_revision >= 0),
    last_saved_at TEXT,
    submitted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (assessment_attempt_id, question_id),
    CHECK (
        (is_answered = 0 AND answer_text = '')
        OR (is_answered = 1 AND length(trim(answer_text)) > 0)
    )
);

CREATE TABLE ai_tasks (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK (
        task_type IN (
            'GENERATE_QUESTIONS', 'EVALUATE_ASSESSMENT',
            'GENERATE_BRIEF', 'SUGGEST_FOLLOW_UP'
        )
    ),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'PENDING_RETRY')
    ),
    idempotency_key TEXT NOT NULL UNIQUE,
    input_fingerprint TEXT NOT NULL CHECK (length(input_fingerprint) = 64),
    input_manifest_json TEXT NOT NULL DEFAULT '{}',
    redaction_policy TEXT NOT NULL DEFAULT 'SANITIZED_TEXT_ONLY'
        CHECK (redaction_policy = 'SANITIZED_TEXT_ONLY'),
    provider TEXT,
    model TEXT,
    prompt_key TEXT,
    prompt_version TEXT,
    schema_version TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retry INTEGER NOT NULL DEFAULT 1 CHECK (max_retry >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE ai_results (
    id TEXT PRIMARY KEY,
    ai_task_id TEXT NOT NULL UNIQUE
        REFERENCES ai_tasks(id) ON DELETE CASCADE,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    question_set_id TEXT
        REFERENCES question_sets(id) ON DELETE RESTRICT,
    result_type TEXT NOT NULL CHECK (
        result_type IN (
            'QUESTION_GENERATION', 'ANSWER_EVALUATION',
            'INTERVIEW_BRIEF', 'FOLLOW_UP'
        )
    ),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    supersedes_result_id TEXT REFERENCES ai_results(id) ON DELETE SET NULL,
    payload_json TEXT NOT NULL,
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
    ),
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, result_type, version_no)
);

CREATE TABLE interview_briefs (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    assessment_attempt_id TEXT NOT NULL
        REFERENCES assessment_attempts(id) ON DELETE CASCADE,
    ai_result_id TEXT REFERENCES ai_results(id) ON DELETE SET NULL,
    source_kind TEXT NOT NULL DEFAULT 'AI' CHECK (
        source_kind IN ('AI', 'MANUAL')
    ),
    status TEXT NOT NULL DEFAULT 'READY' CHECK (
        status IN ('DRAFT', 'READY', 'SUPERSEDED')
    ),
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    supersedes_brief_id TEXT REFERENCES interview_briefs(id) ON DELETE SET NULL,
    brief_json TEXT NOT NULL DEFAULT '{}',
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no),
    CHECK (
        (source_kind = 'AI' AND ai_result_id IS NOT NULL)
        OR (source_kind = 'MANUAL')
    )
);

CREATE TABLE live_interview_records (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    interview_brief_id TEXT
        REFERENCES interview_briefs(id) ON DELETE SET NULL,
    committee_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    sequence_no INTEGER NOT NULL CHECK (sequence_no > 0),
    question_text TEXT NOT NULL CHECK (length(trim(question_text)) > 0),
    source_kind TEXT NOT NULL CHECK (
        source_kind IN (
            'BRIEF_RECOMMENDED', 'MANUAL', 'FOLLOW_UP', 'AI_SUGGESTED'
        )
    ),
    asked_status TEXT NOT NULL DEFAULT 'PLANNED' CHECK (
        asked_status IN ('PLANNED', 'ASKED', 'SKIPPED')
    ),
    live_notes TEXT,
    score INTEGER CHECK (score IS NULL OR score BETWEEN 0 AND 4),
    evidence_status TEXT CHECK (
        evidence_status IS NULL OR evidence_status IN (
            'VERIFIED', 'PARTIALLY_VERIFIED', 'UNVERIFIED',
            'CONFLICTING', 'NOT_MET', 'NOT_ASSESSED'
        )
    ),
    asked_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, sequence_no)
);

CREATE TABLE evaluations (
    id TEXT PRIMARY KEY,
    interview_case_id TEXT NOT NULL
        REFERENCES interview_cases(id) ON DELETE CASCADE,
    version_no INTEGER NOT NULL DEFAULT 1 CHECK (version_no > 0),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'FINAL')),
    final_result TEXT NOT NULL DEFAULT 'PENDING' CHECK (
        final_result IN (
            'PASS', 'FAIL', 'NEXT_ROUND',
            'NEEDS_ADDITIONAL_ASSESSMENT', 'PENDING'
        )
    ),
    final_level TEXT,
    summary TEXT,
    strengths_json TEXT NOT NULL DEFAULT '[]',
    gaps_json TEXT NOT NULL DEFAULT '[]',
    risks_json TEXT NOT NULL DEFAULT '[]',
    final_comment TEXT,
    decided_by_member_id TEXT
        REFERENCES interview_case_committee_members(id) ON DELETE SET NULL,
    decided_at TEXT,
    supersedes_evaluation_id TEXT
        REFERENCES evaluations(id) ON DELETE SET NULL,
    is_current INTEGER NOT NULL DEFAULT 1 CHECK (is_current IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE (interview_case_id, version_no),
    CHECK (
        status = 'DRAFT'
        OR (decided_by_member_id IS NOT NULL AND decided_at IS NOT NULL)
    )
);

CREATE TABLE audit_logs (
    id TEXT PRIMARY KEY,
    actor_type TEXT NOT NULL CHECK (
        actor_type IN ('SYSTEM', 'AI', 'HR_COORDINATOR', 'COMMITTEE', 'CANDIDATE')
    ),
    actor_ref_id TEXT,
    action TEXT NOT NULL CHECK (length(trim(action)) > 0),
    entity_type TEXT NOT NULL CHECK (length(trim(entity_type)) > 0),
    entity_id TEXT NOT NULL CHECK (length(trim(entity_id)) > 0),
    request_id TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value_type TEXT NOT NULL CHECK (
        value_type IN ('STRING', 'INTEGER', 'BOOLEAN', 'JSON', 'SECRET_REF')
    ),
    value_text TEXT,
    protected_value BLOB,
    is_sensitive INTEGER NOT NULL DEFAULT 0 CHECK (is_sensitive IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (
        (is_sensitive = 1 AND protected_value IS NOT NULL AND value_text IS NULL)
        OR (is_sensitive = 0 AND protected_value IS NULL)
    )
);

CREATE UNIQUE INDEX uq_case_one_lead
    ON interview_case_committee_members(interview_case_id)
    WHERE role = 'LEAD';

CREATE UNIQUE INDEX uq_case_one_current_jd
    ON documents(interview_case_id, document_type)
    WHERE document_type = 'JD' AND is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_cv
    ON documents(interview_case_id, document_type)
    WHERE document_type = 'CV' AND is_current = 1;

CREATE UNIQUE INDEX uq_case_one_approved_question_set
    ON question_sets(interview_case_id)
    WHERE status = 'APPROVED';

CREATE UNIQUE INDEX uq_case_one_current_brief
    ON interview_briefs(interview_case_id)
    WHERE is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_evaluation
    ON evaluations(interview_case_id)
    WHERE is_current = 1;

CREATE UNIQUE INDEX uq_case_one_current_ai_result
    ON ai_results(interview_case_id, result_type)
    WHERE is_current = 1;

CREATE INDEX ix_cases_status_schedule
    ON interview_cases(status, scheduled_at);
CREATE INDEX ix_cases_candidate ON interview_cases(candidate_id);
CREATE INDEX ix_cases_job ON interview_cases(job_id);
CREATE INDEX ix_committee_case ON interview_case_committee_members(interview_case_id);
CREATE INDEX ix_documents_case_type
    ON documents(interview_case_id, document_type, is_current);
CREATE INDEX ix_question_sets_case_status
    ON question_sets(interview_case_id, status);
CREATE INDEX ix_questions_set_order
    ON questions(question_set_id, display_order);
CREATE INDEX ix_questions_competency
    ON questions(competency_key);
CREATE INDEX ix_attempts_status_expiry
    ON assessment_attempts(status, expires_at);
CREATE INDEX ix_answers_attempt
    ON answers(assessment_attempt_id);
CREATE INDEX ix_ai_tasks_status_created
    ON ai_tasks(status, created_at);
CREATE INDEX ix_ai_tasks_case ON ai_tasks(interview_case_id);
CREATE INDEX ix_ai_results_attempt
    ON ai_results(assessment_attempt_id, result_type);
CREATE INDEX ix_briefs_case_current
    ON interview_briefs(interview_case_id, is_current);
CREATE INDEX ix_live_case_sequence
    ON live_interview_records(interview_case_id, sequence_no);
CREATE INDEX ix_evaluations_case_current
    ON evaluations(interview_case_id, is_current);
CREATE INDEX ix_audit_entity_time
    ON audit_logs(entity_type, entity_id, created_at);
CREATE INDEX ix_audit_action_time
    ON audit_logs(action, created_at);

CREATE TRIGGER trg_answers_no_update_after_submit
BEFORE UPDATE OF answer_text, is_answered, save_revision, last_saved_at, submitted_at, updated_at
ON answers
WHEN EXISTS (
    SELECT 1
    FROM assessment_attempts a
    WHERE a.id = OLD.assessment_attempt_id
      AND a.status IN ('ASSESSMENT_SUBMITTED', 'ASSESSMENT_EXPIRED')
)
BEGIN
    SELECT RAISE(ABORT, 'answer_locked_after_submit');
END;

CREATE TRIGGER trg_answers_no_insert_after_submit
BEFORE INSERT ON answers
WHEN EXISTS (
    SELECT 1
    FROM assessment_attempts a
    WHERE a.id = NEW.assessment_attempt_id
      AND a.status IN ('ASSESSMENT_SUBMITTED', 'ASSESSMENT_EXPIRED')
)
BEGIN
    SELECT RAISE(ABORT, 'answer_locked_after_submit');
END;

CREATE TRIGGER trg_questions_max_eight
AFTER INSERT ON questions
WHEN (
    SELECT COUNT(*) FROM questions
    WHERE question_set_id = NEW.question_set_id
) > 8
BEGIN
    SELECT RAISE(ABORT, 'question_set_maximum_is_eight');
END;

INSERT INTO app_settings(key, value_type, value_text, is_sensitive)
VALUES
    ('assessment.default_question_count', 'INTEGER', '8', 0),
    ('assessment.max_question_count', 'INTEGER', '8', 0),
    ('assessment.default_duration_seconds', 'INTEGER', '900', 0),
    ('assessment.allow_incomplete_submit', 'BOOLEAN', '1', 0),
    ('assessment.auto_submit_on_expiry', 'BOOLEAN', '1', 0),
    ('ai.redaction_policy', 'STRING', 'SANITIZED_TEXT_ONLY', 0),
    ('retention.mode', 'STRING', 'MANUAL_ONLY', 0);

INSERT INTO schema_migrations(version) VALUES (1);
~~~

Migration implementation must also:

1. Use parameterized SQL for all runtime writes.
2. Create schema_migrations before recording version 1.
3. Run the complete migration in one transaction.
4. Stop application startup if migration fails.
5. Create a SQLite backup before a risky future migration.
6. Insert version 1 only after all DDL, index and trigger statements succeed.

## 10. Index and query policy

### 10.1. Required query paths

- Case list by status and scheduled_at.
- Cases by candidate_id and job_id.
- Current JD/CV snapshot by case and document_type.
- Current approved Question Set by case.
- Questions ordered by question_set_id/display_order.
- Active/expired attempts by status/expires_at.
- Answers by attempt.
- AI queue by status/created_at.
- AI results by case/type/version and by attempt.
- Current Interview Brief and Evaluation by case.
- Live records by case/sequence.
- Audit trail by entity/time and action/time.

### 10.2. Query safety

- Mọi query dùng parameter binding.
- Không tạo SQL bằng string nối từ user input.
- Mỗi repository operation mở connection riêng và đóng sau transaction.
- Foreign key enforcement bật trên từng connection.
- Write liên quan nhiều bảng phải nằm trong một transaction.
- Không dùng global shared SQLite connection hoặc check_same_thread=False.

## 11. Data lifecycle

### 11.1. Tạo case

1. Tạo hoặc chọn Candidate và Job.
2. Tạo InterviewCase ở DRAFT.
3. Gắn thành viên HĐCM nếu đã biết; có thể thêm trước approval.
4. Import JD/CV tạo Document version 1.
5. HĐCM xác nhận extracted text; chỉ document AI_eligible mới được đưa vào AI task.

### 11.2. Document lifecycle

- File được hash, lưu dưới thư mục case ID và relative path.
- Extracted text được lưu local để tái lập input.
- Nếu parse thất bại, giữ metadata/error và cho phép MANUAL_TEXT.
- Thay file hoặc text tạo version mới; version cũ không bị overwrite.
- Chỉ một JD và một CV được đánh dấu current trong một thời điểm.
- AI input dùng extracted_text đã làm sạch và content_sha256; không dùng raw file path làm input.

### 11.3. Question Set lifecycle

- AI tạo proposed payload trong AiTask/AiResult hoặc HĐCM tạo thủ công.
- HĐCM chỉnh sửa, thêm, xóa, sắp xếp câu hỏi trong DRAFT/GENERATED.
- Approval tạo Question Set APPROVED bất biến.
- Khi assessment bắt đầu, Question Set được tham chiếu bởi attempt và không được sửa.
- Thay đổi sau approval chỉ tạo version mới khi chưa có attempt bắt đầu; nếu attempt đã bắt đầu, case hiện tại giữ nguyên snapshot.

### 11.4. Assessment lifecycle

- Tạo một AssessmentAttempt cho case sau khi Question Set được APPROVED.
- Auto-save cập nhật Answer khi attempt chưa submit.
- Submit thủ công hoặc auto-submit ghi submitted_at và submit_reason.
- Answer chưa trả lời vẫn được lưu với is_answered=0 và không bị xóa.
- Sau submit/expiry, database trigger và domain service chặn thay đổi answer.
- Không tạo attempt thứ hai hoặc reopen trong cùng case ở MVP.

### 11.5. AI lifecycle

- Insert AiTask PENDING với idempotency_key và input_manifest_json.
- Worker chuyển task sang RUNNING, gọi provider qua adapter, validate JSON/schema.
- Output hợp lệ tạo AiResult COMPLETED; output lỗi không tạo successful AiResult.
- Retry tối đa một lần theo technology policy; sau đó task FAILED và workflow cho manual fallback.
- Rerun tạo idempotency_key, task, result version và input fingerprint mới.
- Kết quả cũ giữ nguyên; is_current chỉ là con trỏ version, không phải overwrite payload.

### 11.6. Interview Brief, live interview và evaluation

- Interview Brief có thể là AI hoặc MANUAL.
- HĐCM có thể ghi live question/notes/score/evidence status.
- Final Evaluation DRAFT có thể chỉnh trước khi chốt.
- Final Evaluation FINAL phải có member và timestamp.
- Sửa kết quả FINAL tạo version mới, giữ version cũ và ghi audit reason.

## 12. Quy tắc xóa dữ liệu

### 12.1. Retention

Theo quyết định đã chốt, MVP không tự động xóa dữ liệu ứng viên. Dữ liệu tiếp tục được lưu cho tới khi người có thẩm quyền thực hiện thao tác xóa thủ công.

Không tạo job/cron/worker tự động xóa dựa trên created_at, evaluated_at hoặc updated_at.

### 12.2. Hard delete một InterviewCase

Trước khi xóa:

1. Yêu cầu Committee/HR xác nhận rõ case ID và phạm vi xóa.
2. Tạo SQLite backup bằng Connection.backup().
3. Ghi AuditLog về yêu cầu xóa, chỉ chứa ID và metadata đã redact.
4. Chặn thao tác ghi mới lên case trong suốt transaction/xóa.
5. Xóa file trong thư mục documents/{case-id} sau khi kiểm tra path đã resolve nằm trong allowed root.
6. Hard-delete case-owned rows theo FK cascade hoặc explicit transaction.
7. Giữ AuditLog vì audit không có FK.
8. Chỉ xóa Candidate/Job nếu người vận hành chọn xóa riêng và chúng không còn được case khác tham chiếu.

Nếu file deletion và database transaction không thể hoàn tất đồng thời, operation phải báo lỗi và tạo audit/error để người vận hành xử lý orphan file; không được báo thành công giả.

### 12.3. Backup và export

- Backup SQLite chứa dữ liệu database tại thời điểm backup.
- Export ZIP có thể chứa metadata, report, allowed documents và hash manifest, nhưng không chứa API key, PIN hoặc internal token.
- Xóa case không tự động scrub các backup/ZIP đã tạo trước đó. Vì retention là manual-only, người vận hành phải xóa backup/export liên quan bằng thao tác riêng nếu chính sách tổ chức yêu cầu.

## 13. Local file storage contract

Base directory:

~~~text
%LOCALAPPDATA%\ClawCV\
├── database\
│   └── clawcv.db
├── documents\
│   └── {interview-case-id}\
│       ├── jd\
│       └── cv\
├── exports\
├── backups\
├── logs\
└── config\
~~~

Database chỉ lưu relative path, ví dụ:

~~~text
documents/{case-id}/jd/v001/source.pdf
documents/{case-id}/cv/v001/source.docx
~~~

Rules:

- Directory key chỉ dùng UUID/case ID, không dùng candidate name hoặc filename.
- Resolve path và kiểm tra path nằm trong allowed root trước mọi read/write/delete.
- Không lưu dữ liệu runtime trong Program Files hoặc current working directory.
- Không ghi raw document/answer vào log.
- Manual text không cần tạo file binary; extracted_text và content_sha256 vẫn phải lưu trong Document.

## 14. Seed data tối thiểu

Migration 001 không seed Candidate, Job hoặc InterviewCase thật. Có thể seed các app settings không nhạy cảm sau:

| key | value_type | value | Ý nghĩa |
| --- | --- | --- | --- |
| assessment.default_question_count | INTEGER | 8 | Số câu mặc định |
| assessment.max_question_count | INTEGER | 8 | Giới hạn MVP |
| assessment.default_duration_seconds | INTEGER | 900 | 15 phút |
| assessment.allow_incomplete_submit | BOOLEAN | 1 | Cho submit chưa đủ câu |
| assessment.auto_submit_on_expiry | BOOLEAN | 1 | Auto-submit khi hết giờ |
| ai.redaction_policy | STRING | SANITIZED_TEXT_ONLY | Text đã làm sạch |
| retention.mode | STRING | MANUAL_ONLY | Không tự động xóa |

Secret AI endpoint/key không seed vào database. Cấu hình secret phải được lưu bằng Windows DPAPI hoặc environment variable trong development theo Technology Specification.

## 15. Audit event tối thiểu

Các event sau phải ghi AuditLog; action name cụ thể sẽ được chuẩn hóa trong Security and Audit Specification:

- CASE_CREATED, CASE_UPDATED, CASE_CANCELLED, CASE_DELETED.
- DOCUMENT_IMPORTED, DOCUMENT_TEXT_CONFIRMED, DOCUMENT_VERSION_CREATED.
- QUESTION_SET_GENERATION_REQUESTED, QUESTION_SET_EDITED, QUESTION_SET_APPROVED, QUESTION_SET_VERSION_CREATED.
- ASSESSMENT_CREATED, ASSESSMENT_STARTED, ANSWER_AUTOSAVED, ASSESSMENT_SUBMITTED, ASSESSMENT_AUTO_SUBMITTED, ASSESSMENT_EXPIRED.
- CANDIDATE_MODE_ENTERED, COMMITTEE_MODE_ENTERED.
- AI_TASK_CREATED, AI_TASK_RETRIED, AI_TASK_COMPLETED, AI_TASK_FAILED, AI_RESULT_RERUN.
- INTERVIEW_BRIEF_CREATED, INTERVIEW_BRIEF_REVISED.
- LIVE_INTERVIEW_STARTED, LIVE_QUESTION_RECORDED, LIVE_QUESTION_SKIPPED, CONFLICT_FLAGGED.
- EVALUATION_DRAFTED, EVALUATION_FINALIZED, EVALUATION_REVISED.
- BACKUP_CREATED, EXPORT_CREATED, CASE_DELETE_REQUESTED, CASE_DELETE_COMPLETED, CASE_DELETE_FAILED.

## 16. Conflict / Assumption / Open Questions

### 16.1. Conflict đã kiểm tra

| ID | Conflict | Cách xử lý |
| --- | --- | --- |
| CONFLICT-TECH-001 | Context Specification mô tả C#/WPF/EF Core, trong khi Technology Specification chốt Python Standard Library, localhost web app và không ORM. | Technology Specification là nguồn sự thật cho công nghệ. Schema dùng SQLite/sqlite3, không EF Core và không ORM. |
| CONFLICT-TECH-002 | Context dùng tên VCSInterviewAssistant/interview.db; Technology Specification dùng ClawCV/clawcv.db và %LOCALAPPDATA%\\ClawCV. | Dùng tên/path theo Technology Specification. |
| CONFLICT-ARCH-003 | Context nói không cần server; Technology Specification dùng ThreadingHTTPServer localhost. | Hiểu “không server” là không có server/backend trung tâm; localhost process vẫn dùng HTTP server theo Technology Specification. |
| CONFLICT-DATA-004 | Context và Document Set Plan yêu cầu InterviewBrief; danh sách table tối thiểu trong Technology Specification không liệt kê interview_briefs. | Bổ sung interview_briefs vì đây là output nghiệp vụ bắt buộc và entity bắt buộc của tài liệu 19. |
| CONFLICT-DOC-005 | Context liệt kê PDF trong input; Technology Specification không có PDF parser native. | Database hỗ trợ Document snapshot cho PDF, nhưng extraction phải dùng text fallback hoặc executable pdftotext được phê duyệt; không tự xây PDF parser. |
| CONFLICT-QBANK-006 | Context cho phép chọn từ Question Bank, nhưng Technology Specification và table list không chốt bảng Question Bank. | MVP chỉ lưu source_kind=QUESTION_BANK và copy câu đã chọn vào Question Set snapshot; Question Bank tập trung là extension hoặc nguồn cấu hình được chốt sau. |

### 16.2. Assumption đã sử dụng

| ID | Assumption | Lý do và ảnh hưởng |
| --- | --- | --- |
| ASSUMPTION-001 | Một Candidate hoặc Job có thể được tham chiếu bởi nhiều case. | Không làm mất dữ liệu dùng chung và phù hợp nhiều vị trí/case. |
| ASSUMPTION-002 | MVP chỉ có một AssessmentAttempt cho mỗi InterviewCase; không reopen và không retry trong cùng case. | Phù hợp lựa chọn 4A và giữ answer immutable. Case cần làm lại được tạo mới. |
| ASSUMPTION-003 | Default 8 câu/900 giây; Question Set có tối đa 8 câu và thời lượng 600–900 giây. | Ánh xạ lựa chọn 2C và giới hạn 5–8 câu, 10–15 phút của Context. |
| ASSUMPTION-004 | Rubric snapshot được lưu JSON theo Question Set/question; score tổng vẫn integer 0–4. | Ánh xạ lựa chọn 1A mà không tự phát minh công thức weighted score. |
| ASSUMPTION-005 | Multiple HĐCM member chỉ là named participant trong MVP; không có account/role system tập trung. | Ánh xạ lựa chọn 7A và không sao chép auth của Phase 1. |
| ASSUMPTION-006 | Manual retention-only bao gồm cả database và local files; backup/export cũ không tự bị scrub. | Tránh tuyên bố xóa hoàn toàn khi artifact backup vẫn tồn tại; deletion backup là thao tác riêng. |
| ASSUMPTION-007 | Remote AI provider được phép nhận sanitized text theo lựa chọn 5A; raw file, email, phone, address và image không gửi nếu không cần. | Giữ khả năng AI MVP nhưng giảm dữ liệu gửi ra ngoài. |
| ASSUMPTION-008 | Rerun AI luôn tạo version mới và không overwrite; result current chỉ là pointer. | Ánh xạ lựa chọn 8A và bảo toàn provenance. |
| ASSUMPTION-009 | final_level chưa có enum chính thức nên dùng nullable TEXT; final_result dùng enum đã chốt trong Context. | Không tự quyết định taxonomy level. |
| ASSUMPTION-010 | Question Bank tập trung chưa phải aggregate độc lập của MVP; selected question được snapshot vào Question Set. | Giữ chức năng chọn câu mà không mở rộng thành knowledge platform. |
| ASSUMPTION-011 | AI output hợp lệ được lưu full trong ai_results.payload_json; raw provider request/response chưa redact không được lưu. | Đủ audit/provenance nhưng không làm log/database thành nơi lưu secret hoặc file gốc. |
| ASSUMPTION-012 | Case delete hard-delete case-owned records; Candidate/Job dùng chung chỉ xóa khi không còn reference và có xác nhận riêng. | Tránh cascade xóa dữ liệu ngoài phạm vi case. |

### 16.3. Open Questions không chặn Domain and Database

Các câu hỏi sau không làm thay đổi schema cốt lõi và được chuyển sang specification phù hợp:

1. Provider/model/quota/endpoint AI cụ thể: chốt trong AI Assessment hoặc Configuration specification.
2. Có đóng gói pdftotext trong pilot hay chỉ cho paste text: chốt trong Document Processing specification.
3. Danh sách giá trị hợp lệ của final_level: chốt trong AI Assessment/Workflow specification; hiện tại lưu TEXT nullable.
4. Format report PDF/HTML và artifact nào được phép đưa vào export ZIP: chốt trong API/Backup hoặc Report specification.
5. Chi tiết thao tác xóa backup/export cũ và quyền thực hiện: chốt trong Security and Audit specification.
6. Question Bank static/configuration source cụ thể: chốt trong Question Preparation hoặc AI Assessment specification.

Không còn open question mức BLOCKER về candidate flow, submit, reopen, rubric, retention, committee relationship hoặc AI data boundary cho việc tạo schema này.

## 17. Acceptance criteria của tài liệu

Tài liệu được xem là đạt yêu cầu Domain and Database Specification khi:

1. Có entity list và boundary phù hợp MVP.
2. Mỗi bảng chính có field, SQLite type, nullability, default, primary key, foreign key, constraint và index/relationship liên quan.
3. Có relationship/cardinality từ InterviewCase tới toàn bộ dữ liệu liên quan.
4. Có enum/status cần thiết nhưng không thay thế Workflow State Machine.
5. Có quy ước JSON, timestamp, hash, relative path và secret.
6. Có version/snapshot cho document, Question Set, AI result, Interview Brief và Evaluation.
7. Có rule candidate submit incomplete, auto-submit, answer lock và no reopen.
8. Có rule AI sanitized input, persistent task, manual fallback và immutable rerun.
9. Có rule multiple committee members và finalizer.
10. Có data lifecycle từ tạo case đến manual hard delete.
11. Có retention manual-only và quy tắc xử lý backup/export.
12. Có migration 001 DDL đề xuất, seed tối thiểu và SQLite-specific indexes/triggers.
13. Có Mermaid ER diagram.
14. Có Conflict / Assumption / Open Questions.
15. Không dùng ORM, không mở rộng sang Phase 1 auth, recruitment server, centralized Question Bank hoặc cloud database.

## 18. Traceability matrix

| Requirement | Cách đáp ứng trong tài liệu |
| --- | --- |
| CTX-CASE-001: Tạo case cho candidate, position, level và schedule | jobs, candidates, interview_cases, scheduled_at |
| CTX-DOC-001: Snapshot JD/CV, hash và extracted text | documents, content_sha256, storage_path, extracted_text |
| CTX-QST-001: HĐCM sửa, duyệt, khóa câu hỏi | question_sets/questions status, version và approval fields |
| CTX-ASS-001: Candidate làm bài tại chỗ, timer, autosave | assessment_attempts, answers, expires_at, save_revision |
| CTX-ASS-002: Submit thiếu câu và auto-submit | allow_incomplete_submit, is_answered, submit_reason, trigger |
| CTX-ASS-003: Không sửa sau submit và không reopen | unique attempt/case, answer lock trigger, lifecycle rule |
| CTX-AI-001: AI đánh giá và tạo Interview Brief | ai_tasks, ai_results, interview_briefs |
| CTX-AI-002: AI failure/manual fallback | ai_tasks FAILED, InterviewBrief source_kind MANUAL, no result on invalid output |
| CTX-AI-003: Rerun không overwrite | version_no, supersedes_result_id, is_current |
| CTX-LIVE-001: Live notes/score/evidence | live_interview_records |
| CTX-EVAL-001: HĐCM chốt result | evaluations, decided_by_member_id, decided_at |
| CTX-AUDIT-001: Audit thao tác quan trọng | audit_logs và event catalog |
| CTX-DATA-001: Retention và xóa hồ sơ | manual-only lifecycle, hard delete and backup rule |
| TECH-DB-001: SQLite local, WAL, migration version | DDL/migration rules; runtime PRAGMA do Technology Specification |
| TECH-DB-002: Không ORM | DDL thuần SQL, repository query policy |
| TECH-AI-001: Persistent task/background worker | ai_tasks status/retry/recovery |
| TECH-SEC-001: Không lưu secret plain text | app_settings protected_value, no secret in audit/log |

## 19. Kết luận

Domain/database MVP được tổ chức quanh InterviewCase và giữ riêng các snapshot cần để tái lập quá trình: JD/CV version, Question Set version, Assessment Attempt/Answer, AI task/result version, Interview Brief version và Final Evaluation revision.

Các quyết định nghiệp vụ đã được phản ánh:

- Default assessment là 8 câu trong 15 phút.
- Candidate được submit khi chưa trả lời hết; hết giờ auto-submit.
- Attempt đã submit không được sửa hoặc mở lại.
- Rubric dùng chung nhưng snapshot theo Question Set/question; score 0–4.
- AI nhận sanitized text và rerun tạo version mới.
- Retention là manual-only, không tự động xóa.
- Một case có nhiều thành viên HĐCM và tối đa một lead.

Schema này là nền tảng dữ liệu cho 21_workflow_state_machine.md, 22_ai_assessment_specification.md, 23_api_contract_specification.md và các tài liệu tiếp theo. Chưa triển khai source code hoặc migration thực tế.
