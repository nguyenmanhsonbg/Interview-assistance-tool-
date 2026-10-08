# Question Variant Generation Design

## Goal

Cho phép HĐCM tinh chỉnh từng câu hỏi trong Question Set trước khi approval bằng ba thao tác:

1. `Gen theo prompt`: HĐCM nhập yêu cầu bổ sung để AI tạo một đề xuất thay thế.
2. `Gen câu thay thế`: AI tự tạo một đề xuất khác nhưng giữ nguyên nhóm và các ràng buộc của câu đang chọn.
3. `Sửa bằng tay`: HĐCM chỉnh sửa câu hỏi bằng form hiện có.

MVP chỉ tạo một đề xuất cho mỗi lần gọi. AI không tự ghi đè câu hỏi; HĐCM phải xem và bấm áp dụng.

## Scope and constraints

- Chỉ cho phép thao tác trên Question Set ở trạng thái `DRAFT` hoặc `GENERATED`.
- Question Set `APPROVED`, hoặc case đã bắt đầu assessment, không cho sửa/thay thế trực tiếp.
- Không thay đổi số lượng câu, `displayOrder` hoặc tỷ lệ nhóm của Question Set.
- Không triển khai sinh nhiều phương án cùng lúc, drag/drop, question bank hoặc lịch sử prompt trong MVP.
- Không thay đổi candidate HTML contract; chỉ Question Set draft sau khi áp dụng mới được export.
- Không tạo `Interview Brief`, `recommendedLiveQuestions` hoặc quyết định PASS/FAIL.

## Decisions

### Proposal-first

Kết quả AI được materialize thành proposal gắn với `caseId`, `questionSetId`, câu hỏi nguồn và fingerprint của câu hỏi tại thời điểm tạo. Proposal không thay đổi Question Set hiện tại.

HĐCM có thể:

- `Dùng câu này`: áp dụng proposal atomically vào đúng vị trí câu hỏi.
- `Tạo lại`: tạo task mới với idempotency key mới.
- `Bỏ qua`: đánh dấu proposal `DISCARDED`, giữ nguyên Question Set và không để proposal cũ hiện lại như đề xuất chờ xử lý.

### Preserved question constraints

Proposal phải giữ nguyên các trường sau của câu hỏi nguồn:

- `displayOrder`
- `competencyKey`
- `questionCategory`
- `questionType`
- `difficulty`
- `isRequired`
- `estimatedSeconds`
- `sourceKind` của slot hiện tại

AI được đề xuất lại các trường nội dung:

- `questionText`
- `purpose`
- `nextStepObjective`
- `expectedEvidence`
- `rubric`

Khi áp dụng, giữ nguyên `questionId` của slot để không làm mất liên kết UI và provenance; audit lưu fingerprint trước/sau. Tỷ lệ nhóm và thứ tự câu tiếp tục được backend validate.

### Manual edit

`Sửa bằng tay` dùng form chỉnh sửa hiện có và `PATCH question-set`. Manual edit không tạo AI task. Khi lưu, backend vẫn validate toàn bộ Question Set và chỉ cho phép sửa draft.

## UI flow

### Selected question action bar

Trong detail của câu hỏi đang chọn, đặt action bar gần tiêu đề:

- `Gen theo prompt`
- `Gen câu thay thế`
- `Sửa bằng tay`

Nếu Question Set bị khóa, action bar hiển thị disabled state và lý do ngắn gọn.

### Gen theo prompt

Mở modal/drawer có:

- Câu hỏi hiện tại ở trạng thái chỉ đọc.
- Các constraint được giữ nguyên ở trạng thái chỉ đọc.
- Ô prompt của HĐCM, giới hạn độ dài và bắt buộc nếu mode này được chọn.
- Nút `Tạo đề xuất`.

Prompt của HĐCM được xem là instruction bổ sung, không được phép thay đổi schema, constraint, workflow hoặc quyền quyết định của HĐCM.

### Gen câu thay thế

Thao tác một click tạo proposal theo cùng `questionCategory`, `competencyKey`, `questionType` và `difficulty`. Không cần nhập prompt. UI hiển thị rõ đây là “câu thay thế cùng nhóm”, không phải câu mới làm tăng số lượng.

### Task progress

Khi task đang `PENDING`, `RUNNING` hoặc `PENDING_RETRY`:

- Câu hỏi hiện tại vẫn được hiển thị.
- Action bar bị khóa.
- Hiển thị progress panel với trạng thái task.
- Refresh hoặc mở lại màn hình không tạo task thứ hai.

### Proposal preview

Khi task hoàn tất, detail hiển thị proposal card gồm:

- Câu hỏi hiện tại và câu hỏi đề xuất.
- Các field nội dung thay đổi.
- Các constraint được giữ nguyên.
- `provider`, `model`, `promptVersion`, `schemaVersion` an toàn nếu API trả về.
- `confidence` và `limitations` nếu có.

Proposal card có ba action: `Dùng câu này`, `Tạo lại`, `Bỏ qua`. Không render AI output bằng HTML; mọi nội dung dùng text node an toàn.

## API and task contract

### Create variant task

Đề xuất endpoint:

`POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants`

Request:

```json
{
  "questionSetId": "uuid",
  "mode": "USER_PROMPT",
  "prompt": "Tập trung hơn vào khả năng xử lý sự cố production"
}
```

`mode` nhận `USER_PROMPT` hoặc `SAME_GROUP`. Với `SAME_GROUP`, `prompt` phải rỗng hoặc không gửi. Response `202` trả `taskId`, `questionSetId`, `questionId` và snapshot metadata an toàn.

Task input manifest phải chứa ID/hash và constraint, không ghi raw JD/CV, raw prompt hoặc answer vào log. Idempotency key gồm case, Question Set, question ID, source fingerprint, mode và prompt hash.

### Read proposal

Đề xuất endpoint:

`GET /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}`

Chỉ trả proposal đã validate, metadata provenance cần cho UI và trạng thái `PROPOSED`, `APPLIED` hoặc `DISCARDED`. `variantId` là ID của proposal, không phải ID của Question hiện tại. Endpoint kiểm tra proposal thuộc đúng case và Question Set.

### Discard proposal

`POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}/discard`

Endpoint kiểm tra committee session, proposal đang ở `PROPOSED` và đúng source question, sau đó đánh dấu `DISCARDED` trong một transaction. Thao tác không thay đổi Question Set.

### Apply proposal

Đề xuất endpoint:

`POST /api/v1/interview-cases/{caseId}/question-set/questions/{questionId}/variants/{variantId}/apply`

Request có `expectedQuestionSetUpdatedAt` hoặc fingerprint tương đương. Backend trong một transaction:

1. Kiểm tra committee session, draft status và chưa bắt đầu assessment.
2. Kiểm tra proposal chưa áp dụng và source fingerprint vẫn khớp.
3. Thay nội dung đúng question slot, giữ `questionId`, `displayOrder` và constraint.
4. Revalidate toàn bộ Question Set.
5. Ghi audit và đánh dấu proposal `APPLIED`.

Nếu Question Set đã thay đổi, trả lỗi conflict an toàn và không áp dụng một phần.

## AI operation and schema

Tạo provider operation riêng:

- Operation: `GENERATE_QUESTION_VARIANT`
- Prompt key: `question_variant_generation`
- Schema: `question-variant.v1`
- Task type: `GENERATE_QUESTION_VARIANT`
- Result type: `QUESTION_VARIANT`

Output tối thiểu:

```json
{
  "schemaVersion": "question-variant.v1",
  "operation": "GENERATE_QUESTION_VARIANT",
  "mode": "USER_PROMPT",
  "questionSetId": "uuid",
  "sourceQuestionId": "uuid",
  "variant": {
    "questionText": "string",
    "purpose": "string",
    "nextStepObjective": "string",
    "expectedEvidence": "string",
    "rubric": {
      "score0": "string",
      "score1": "string",
      "score2": "string",
      "score3": "string",
      "score4": "string"
    }
  },
  "confidence": 0.8,
  "limitations": []
}
```

Validator phải kiểm tra:

- Đúng schema và đúng một proposal.
- `questionSetId`/`sourceQuestionId` khớp task input.
- Nội dung bắt buộc không rỗng.
- Variant không tự đổi các constraint được bảo vệ.
- Không chứa PASS/FAIL, hiring recommendation hoặc instruction làm thay đổi workflow.

AI nhận sanitized JD/CV và question context cần thiết. Prompt của HĐCM được đánh dấu là untrusted user instruction và không được ghi raw vào log.

## Persistence and migration

Mở rộng schema hiện có bằng migration mới, không sửa migration đã áp dụng:

- Cho phép `GENERATE_QUESTION_VARIANT` trong `ai_tasks.task_type`.
- Cho phép `QUESTION_VARIANT` trong `ai_results.result_type`.
- Thêm `source_question_id` vào `ai_tasks` và `ai_results` để truy vết câu hỏi nguồn.
- Thêm bảng `question_variant_proposals` liên kết một proposal với một `ai_result_id`, lưu `case_id`, `question_set_id`, `source_question_id`, mode, source fingerprint, status và timestamps.
- Giữ `supersedes_result_id`, retry, provider/model/prompt/schema metadata.
- Điều chỉnh unique current-result rule để hai câu khác nhau trong cùng Question Set không triệt tiêu proposal của nhau; proposal status là nguồn sự thật cho `PROPOSED/APPLIED/DISCARDED`.

Proposal history không được overwrite im lặng. Apply là mutation riêng có audit, không tạo Question Set APPROVED mới.

## Failure, recovery and security

- Provider/network/schema failure: giữ nguyên câu hỏi hiện tại, cho retry hoặc manual edit.
- Restart khi task đang chạy: task recovery theo policy hiện có; UI resume bằng `taskId`.
- Double-click/refresh: idempotency không tạo task trùng.
- Proposal stale: reject apply, yêu cầu tải lại Question Set và tạo proposal mới.
- Approved Question Set hoặc assessment đã bắt đầu: reject mutation bằng state conflict.
- Không gửi raw file, local path, token, API key hoặc unnecessary PII tới provider.
- Không log raw prompt, raw AI payload hoặc nội dung câu hỏi đầy đủ ngoài dữ liệu domain đã được phép lưu.

## Audit events

Tối thiểu cần các action:

- `QUESTION_VARIANT_TASK_REQUESTED`
- `QUESTION_VARIANT_GENERATED`
- `QUESTION_VARIANT_FAILED`
- `QUESTION_VARIANT_DISCARDED`
- `QUESTION_VARIANT_APPLIED`
- `QUESTION_MANUALLY_EDITED`

Audit metadata chỉ chứa ID, mode, fingerprint/hash, task/result version và error code an toàn; không chứa raw prompt hay AI payload.

## Acceptance criteria

1. HĐCM có đúng ba action cho câu hỏi draft: prompt AI, thay thế cùng nhóm và sửa tay.
2. Mỗi AI action tạo tối đa một proposal và không ghi đè câu hỏi hiện tại khi task hoàn tất.
3. Proposal cùng nhóm giữ nguyên category, competency, type, difficulty, order và required constraints.
4. HĐCM chỉ áp dụng sau khi xem preview; apply stale bị từ chối nguyên tử.
5. Task progress hiển thị sau refresh và không tạo task trùng.
6. AI/schema/provider failure giữ nguyên draft và vẫn cho manual edit.
7. Approved Question Set và case đã bắt đầu assessment không cho variant/apply/manual mutation.
8. Candidate export chỉ thấy câu hỏi sau khi proposal được áp dụng và Question Set được approve.
9. Audit và provenance đủ để truy ngược proposal, người áp dụng và phiên bản Question Set.
10. Test bao phủ happy path, invalid prompt, invalid output, retry/recovery, idempotency, stale apply, locked state và candidate isolation.

## Out of scope

- Sinh nhiều variant để so sánh đồng thời.
- Question bank hoặc semantic duplicate detection.
- Tự động chọn proposal tốt nhất.
- Sửa câu hỏi sau khi candidate đã bắt đầu làm bài.
- Dịch nhãn hoặc thay đổi enum hiện có.
