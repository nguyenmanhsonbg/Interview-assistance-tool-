# Design: Thêm câu hỏi mới theo group

## Mục tiêu

Cho phép HĐCM thêm một câu hỏi mới vào Question Set đang ở giai đoạn chuẩn bị:

- Từ sidebar, mỗi group `Nền tảng`, `Ứng dụng`, `Chuyên sâu` có nút `Thêm câu hỏi`.
- HĐCM chọn một trong hai cách tạo:
  - `Gen theo prompt`: AI tạo câu hỏi dựa trên prompt bổ sung của HĐCM.
  - `Tự động gen`: AI tự tạo câu hỏi theo group được chọn.
- AI luôn tạo một proposal trước. HĐCM xem trước rồi chọn `Dùng câu hỏi này` hoặc `Bỏ qua`.
- Khi áp dụng, câu hỏi mới được thêm vào Question Set; câu hỏi cũ không bị thay thế.

## Quyết định đã chốt

### Cho phép Question Set vượt quá 9 câu

Question Set ban đầu vẫn được AI tạo theo framework hiện tại: 9 câu, phân bổ `3/4/2`.
Sau đó HĐCM có thể thêm câu, tối đa 30 câu trong MVP để tránh payload, thời gian làm bài và
chi phí AI tăng không kiểm soát.

Các quy tắc sau khi mở rộng:

- Question Set hợp lệ có từ 9 đến 30 câu.
- `displayOrder` liên tục từ 1 đến tổng số câu.
- Không bắt buộc giữ tỷ lệ `3/4/2` sau khi thêm.
- Không đổi `displayOrder` hoặc ID của các câu hiện có; câu mới được thêm ở cuối Question Set.
- UI vẫn hiển thị theo thứ tự group, nên câu mới xuất hiện trong group được chọn dù có order ở cuối.
- Thời lượng Question Set vẫn dùng giá trị hiện có, mặc định 900 giây; không tự động tăng thời lượng.

Giới hạn 30 là guardrail kỹ thuật của MVP, không phải quyết định về giới hạn nghiệp vụ lâu dài.

### Mapping group và loại nguồn

| Group UI | `questionCategory` | `sourceKind` khi tự động gen |
| --- | --- | --- |
| Nền tảng | `FOUNDATION` | `STANDARDIZED` |
| Ứng dụng | `APPLICATION` | `SITUATIONAL` |
| Chuyên sâu | `DEEP_DIVE` | AI chọn `CV_VERIFICATION` hoặc `GAP_CONFLICT` |

`questionType` (`SHORT_TEXT`, `LONG_TEXT`, `SCENARIO`) do AI chọn theo nội dung câu hỏi.
Backend vẫn kiểm tra enum và kiểm tra `sourceKind` có hợp lệ với group. Với `DEEP_DIVE`, AI
được chọn giữa hai nguồn hợp lệ dựa trên evidence trong JD/CV và các câu hiện có.

### Proposal-first

AI không được ghi trực tiếp vào `questions`. Kết quả được lưu thành proposal gắn với:

- `caseId`;
- `questionSetId`;
- `targetCategory`;
- mode tạo câu hỏi;
- fingerprint của Question Set và tài liệu tại thời điểm tạo.

HĐCM có thể:

- xem proposal;
- áp dụng proposal một lần;
- bỏ qua proposal;
- tạo lại bằng task mới.

Proposal cũ không bị overwrite. Apply stale hoặc apply proposal đã xử lý sẽ bị từ chối nguyên
tử, không làm thay đổi Question Set.

### Trạng thái được phép

Chỉ Question Set `DRAFT` hoặc `GENERATED` mới được tạo, áp dụng hoặc bỏ qua proposal.
Question Set `APPROVED` và case đã có `AssessmentAttempt` không cho thêm câu. Server là nguồn
quyết định; việc disable nút trên UI chỉ là hỗ trợ thao tác.

## Luồng nghiệp vụ

1. HĐCM mở màn Bộ câu hỏi.
2. Sidebar render đủ ba group và nút `Thêm câu hỏi` ở từng group, kể cả khi group đang rỗng.
3. HĐCM bấm nút của một group; popup hiển thị hai lựa chọn `Gen theo prompt` và `Tự động gen`.
4. Với `Gen theo prompt`, HĐCM nhập instruction tối đa 2.000 ký tự sau khi trim.
5. Frontend gửi task với `questionCategory` của group và mode tương ứng.
6. Backend kiểm tra quyền Committee, trạng thái Question Set, category, prompt, idempotency và
   tạo task AI bất đồng bộ.
7. Worker gửi cho provider dữ liệu đã sanitize gồm JD/CV, group mục tiêu và tóm tắt các câu
   hiện có để AI tránh lặp lại. Không gửi answer hoặc file thô.
8. Provider trả đúng một proposal theo schema `question-addition.v1`.
9. Backend validate schema, identity, enum, category/source mapping và lưu proposal `PROPOSED`.
10. UI hiển thị progress và preview trong group tương ứng.
11. HĐCM chọn:
    - `Dùng câu hỏi này`: backend kiểm tra fingerprint, tạo question ID mới, thêm câu ở cuối,
      cập nhật `displayOrder`, đánh dấu proposal `APPLIED` và ghi audit trong một transaction.
    - `Bỏ qua`: chỉ chuyển proposal sang `DISCARDED`.
    - `Tạo lại`: tạo task mới; proposal cũ vẫn giữ lịch sử.
12. UI tải lại Question Set từ backend; count và order lấy từ dữ liệu trả về.

## AI contract

Tạo operation riêng, không dùng `QUESTION_VARIANT` vì đây là thêm slot mới chứ không phải thay
thế một câu hiện có:

- task type: `GENERATE_QUESTION_ADDITION`;
- result type: `QUESTION_ADDITION`;
- prompt key: `question_addition_generation`;
- schema: `question-addition.v1`;
- mode: `USER_PROMPT` hoặc `AUTO_GROUP`.

Output dự kiến:

```json
{
  "schemaVersion": "question-addition.v1",
  "operation": "GENERATE_QUESTION_ADDITION",
  "mode": "AUTO_GROUP",
  "questionSetId": "uuid",
  "targetCategory": "APPLICATION",
  "question": {
    "questionText": "string",
    "competencyKey": "string",
    "sourceKind": "SITUATIONAL",
    "purpose": "string",
    "nextStepObjective": "string",
    "questionType": "SCENARIO",
    "difficulty": "MEDIUM",
    "expectedEvidence": "string",
    "rubric": {
      "score0": "string",
      "score1": "string",
      "score2": "string",
      "score3": "string",
      "score4": "string"
    },
    "isRequired": true,
    "estimatedSeconds": 100
  },
  "confidence": 0.8,
  "limitations": []
}
```

Các field human-readable phải bằng tiếng Việt. Tên field và enum giữ nguyên tiếng Anh. AI không
được trả `displayOrder`, `id`, `questionSetId` khác trusted input, hoặc instruction thay đổi
workflow/quyết định tuyển dụng.

Backend không tin `targetCategory` hay `sourceKind` từ browser. Category được lấy từ request,
được đưa vào task manifest, rồi đối chiếu với output AI. `sourceKind` được kiểm tra theo mapping
ở trên; `DEEP_DIVE` chỉ nhận `CV_VERIFICATION` hoặc `GAP_CONFLICT`.

`USER_PROMPT` là untrusted instruction bổ sung, không được phép thay đổi schema, enum, group,
quyền quyết định hay quy tắc bảo mật. Prompt rỗng, chỉ có whitespace hoặc dài hơn 2.000 ký tự
bị từ chối trước khi tạo task.

## Persistence

### AI task/result

Mở rộng pipeline AI hiện có với `target_question_category` nullable trên `ai_tasks` và
`ai_results`. Với `QUESTION_ADDITION`, version hiện tại được scope theo:

`interview_case_id + result_type + question_set_id + target_question_category`.

Điều này cho phép tạo nhiều proposal liên tiếp cho các group khác nhau mà không bị unique rule
của kết quả `GENERATE_QUESTIONS` ghi đè. Proposal history vẫn được giữ nguyên.

### Bảng `question_addition_proposals`

Migration mới, không sửa migration đã áp dụng:

| Cột | Mục đích |
| --- | --- |
| `id` | Proposal ID |
| `ai_result_id` | Kết quả AI tương ứng, unique |
| `interview_case_id` | Case sở hữu |
| `question_set_id` | Question Set snapshot |
| `target_category` | `FOUNDATION/APPLICATION/DEEP_DIVE` |
| `mode` | `USER_PROMPT/AUTO_GROUP` |
| `source_fingerprint` | Chống apply stale |
| `status` | `PROPOSED/APPLIED/DISCARDED` |
| `applied_question_id` | ID câu mới sau khi apply, nullable |
| timestamps | created/updated/applied/discarded |

Không xóa proposal history sau khi câu hỏi được thêm. `applied_question_id` là provenance
metadata và không được dùng để cho phép sửa câu sau khi Question Set đã approved.

## Atomic apply

`apply` chạy trong một transaction:

1. Kiểm tra case, Question Set, category và assessment lock.
2. Kiểm tra proposal thuộc đúng case/Question Set/category và đang `PROPOSED`.
3. So sánh `expectedQuestionSetUpdatedAt` và source fingerprint với dữ liệu hiện tại.
4. Validate payload `QUESTION_ADDITION` lần cuối ở boundary backend.
5. Xác định `displayOrder = MAX(display_order) + 1`, tạo UUID câu hỏi mới và insert toàn bộ
   field đã validate.
6. Validate toàn bộ Question Set theo rule mở rộng 9–30 câu, order liên tục và enum hợp lệ.
7. Cập nhật `question_sets.updated_at`.
8. Đánh dấu proposal `APPLIED`, lưu `applied_question_id`.
9. Ghi audit `QUESTION_ADDITION_APPLIED` với ID/fingerprint/count, không ghi raw prompt hoặc
   raw AI payload.

Nếu bất kỳ bước nào lỗi, transaction rollback: không có question mới và proposal vẫn
`PROPOSED`.

## API

Giữ API variant hiện tại cho chức năng thay thế câu. Chức năng thêm câu dùng namespace riêng:

```text
POST /api/v1/interview-cases/{caseId}/question-set/question-additions
GET  /api/v1/interview-cases/{caseId}/question-set/question-additions
GET  /api/v1/interview-cases/{caseId}/question-set/question-additions/{proposalId}
POST /api/v1/interview-cases/{caseId}/question-set/question-additions/{proposalId}/discard
POST /api/v1/interview-cases/{caseId}/question-set/question-additions/{proposalId}/apply
```

Create request:

```json
{
  "questionSetId": "uuid",
  "questionCategory": "FOUNDATION",
  "mode": "USER_PROMPT",
  "prompt": "Tập trung vào khả năng xử lý sự cố production"
}
```

`AUTO_GROUP` không nhận prompt. Response create là `202` với `taskId`, `questionSetId`,
`questionCategory`, `mode` và task metadata an toàn. GET proposal trả preview đã validate,
provenance và status; không trả raw provider payload.

Apply request:

```json
{
  "questionSetId": "uuid",
  "expectedQuestionSetUpdatedAt": "2026-10-08T10:00:00.000Z",
  "expectedSourceFingerprint": "sha256"
}
```

Tất cả mutation yêu cầu startup token và Committee session theo cơ chế hiện tại. Host validation,
case ownership, idempotency, error envelope và request ID giữ nguyên convention của API hiện có.

## UI

### Sidebar group

`questionGroups` phải luôn trả ba group chuẩn theo thứ tự `FOUNDATION`, `APPLICATION`,
`DEEP_DIVE`, kể cả group không có câu. Header group gồm:

- nhãn tiếng Việt hiện tại;
- số lượng lấy từ dữ liệu;
- nút `Thêm câu hỏi`;
- progress/proposal summary nếu group đang có task hoặc proposal.

Nút group truyền category enum nội bộ, không truyền nhãn tiếng Việt làm business input.

### Popup và prompt modal

Popup đầu tiên có đúng hai lựa chọn. Chọn `Gen theo prompt` mở modal có textarea, character
counter, validation, `Hủy` và `Tạo đề xuất`. Chọn `Tự động gen` gửi task ngay sau confirmation/loading
state phù hợp.

Nội dung proposal được render bằng text node/safe DOM helper. Không dùng `innerHTML`, `eval` hay
`new Function` cho prompt, question text, rubric hoặc AI output.

### Progress và preview

UI tái sử dụng cơ chế polling task hiện có. Refresh hoặc mở lại màn hình phải đọc task/proposal
đang tồn tại, không tạo task thứ hai. Proposal card hiển thị:

- câu hỏi đề xuất;
- group/source/type/difficulty;
- purpose, expected evidence và rubric;
- `Dùng câu hỏi này`, `Tạo lại`, `Bỏ qua`.

Các enum và status hiển thị nguyên giá trị enum theo quy ước hiện tại; chỉ nhãn UI group được
dịch sang tiếng Việt.

## Security, audit và recovery

- Không gửi file thô, path, token, API key, answer hoặc raw payload tới provider.
- Sanitize JD/CV và câu hỏi hiện có trước khi đưa vào provider.
- Không log prompt thô, câu trả lời, JD/CV hoặc AI payload.
- Idempotency key lặp lại với cùng input trả task cũ; cùng key khác input trả conflict.
- Provider/network/schema failure giữ nguyên Question Set và cho phép retry.
- Restart server khôi phục task theo pipeline hiện có; proposal chỉ materialize sau khi result
  validate thành công.
- Audit tối thiểu: `QUESTION_ADDITION_TASK_REQUESTED`, `QUESTION_ADDITION_GENERATED`,
  `QUESTION_ADDITION_FAILED`, `QUESTION_ADDITION_DISCARDED`, `QUESTION_ADDITION_APPLIED`.

## Tương thích các flow hiện có

- Initial AI generation vẫn dùng schema cũ và vẫn bắt buộc đúng 9 câu, phân bổ 3/4/2.
- Candidate HTML package phải nâng giới hạn tối đa từ 9 lên 30 và tiếp tục kiểm tra order liên
  tục, fingerprint và version. Package chỉ export Question Set sau khi HĐCM approve.
- Assessment snapshot, candidate answers và AI evaluation lấy danh sách câu từ snapshot/database,
  không hardcode 9.
- Excel fallback/export không được mở rộng trong scope này; UI đã bỏ nút Excel fallback. Nếu
  endpoint Excel cũ nhận Question Set mở rộng, backend tiếp tục từ chối theo contract Excel hiện
  tại thay vì âm thầm cắt bớt câu.
- Không thay đổi Question Set đã approved hoặc assessment đang chạy.

## Test và acceptance criteria

1. Sidebar render đủ ba group và nút thêm đúng category.
2. Prompt modal validate prompt rỗng và quá 2.000 ký tự.
3. `USER_PROMPT` và `AUTO_GROUP` tạo đúng task, idempotency và task progress.
4. Schema addition chấp nhận proposal hợp lệ, từ chối sai category, sai sourceKind, enum hoặc
   protected identity.
5. `DEEP_DIVE` chấp nhận cả `CV_VERIFICATION` và `GAP_CONFLICT`, group khác chỉ nhận sourceKind
   tương ứng.
6. Proposal không tự thêm câu; preview, discard và retry hoạt động đúng.
7. Apply thêm đúng một câu ở cuối, giữ nguyên toàn bộ câu cũ, order liên tục và tăng count.
8. Apply stale, duplicate apply, wrong case, locked Question Set và vượt quá 30 câu bị từ chối
   nguyên tử.
9. Question Set 10–30 câu được approve và candidate HTML export/import đúng count/fingerprint.
10. Provider/schema failure, restart/recovery và candidate isolation không làm lộ hoặc thay đổi
    dữ liệu ngoài scope.
11. Full backend tests, frontend syntax/contract tests và `git diff --check` pass.

## Ngoài phạm vi

- Sinh nhiều proposal đồng thời để so sánh.
- Semantic duplicate detection hoàn chỉnh.
- Question bank hoặc kéo-thả sắp xếp câu.
- Tự động chọn proposal tốt nhất.
- Thêm câu sau khi Question Set đã approved hoặc candidate đã bắt đầu.
- Mở rộng Excel fallback cho Question Set vượt quá 9 câu.
- Interview Brief, `recommendedLiveQuestions`, PASS/FAIL hoặc quyết định tuyển dụng tự động.
