# 22. Phase 2 Supervised Interview Mini Tool — AI Assessment Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Product Owner / BA + AI reviewer |
| Last updated | 2026-10-04 |
| Depends on | 17 Context Specification; 18 Technology Specification; 20 Domain and Database Specification; 21 Workflow State Machine |
| Supersedes | Không có |

## 1. Mục tiêu và nguyên tắc

AI hỗ trợ HĐCM chuẩn bị câu hỏi và đánh giá sơ bộ answer. Interview Brief/follow-up là capability định hướng cho phase sau. AI không tuyển, không loại, không chuyển case sang PASS hoặc FAIL và không thay thế final evaluation của HĐCM.

Mỗi AI call phải:

- Nhận input đã được chọn lọc và sanitize.
- Có prompt_key, prompt_version và schema_version.
- Chạy qua persistent AiTask/background worker.
- Trả JSON theo schema tương ứng.
- Được validate trước khi tạo AiResult.
- Cho phép HĐCM xem evidence, chỉnh sửa Question Set và đánh giá lại.
- Giữ version cũ khi rerun.

## 2. Capability map

| Capability | Task type | Input chính | Output chính |
| --- | --- | --- | --- |
| Generate questions | GENERATE_QUESTIONS | JD text, CV text, job/level, policy | Competency matrix, 5–8 proposed questions, rubric, evidence |
| Generate question variant | GENERATE_QUESTION_VARIANT | Sanitized JD/CV context, current question, mode và bounded user prompt | Một proposal `QUESTION_VARIANT` cho đúng question slot |
| Generate question addition | GENERATE_QUESTION_ADDITION | Sanitized JD/CV, target category, existing question summaries, mode và bounded user prompt | Một proposal `QUESTION_ADDITION` cho câu mới |
| Evaluate answers | EVALUATE_ASSESSMENT | JD/CV, approved Question Set, answers | Two-pass per-answer evidence analysis and synthesized evaluation |
| Suggest follow-up | SUGGEST_FOLLOW_UP | Interview Brief, live notes, remaining competencies | 1–3 live follow-up questions, reason, evidence, stop condition |

Trong implementation active, `EVALUATE_ASSESSMENT` chạy hai phase trong cùng persistent task: phân tích evidence theo từng answer trước, sau đó tổng hợp thành evaluation. `Interview Brief` và `recommendedLiveQuestions` tạm thời chưa thuộc output active; sẽ được thiết kế ở phase sau mà không thay đổi final authority của HĐCM.

## 3. Input contract chung

### 3.1. Privacy-safe input envelope

~~~json
{
  "schemaVersion": "ai.input.v1",
  "operation": "GENERATE_QUESTIONS",
  "candidateCode": "CAND-001",
  "job": {
    "positionTitle": "string",
    "targetLevel": "string"
  },
  "documents": {
    "jd": {
      "documentId": "uuid",
      "contentSha256": "sha256",
      "sanitizedText": "text"
    },
    "cv": {
      "documentId": "uuid",
      "contentSha256": "sha256",
      "sanitizedText": "text"
    }
  },
  "policy": {
    "maxQuestions": 8,
    "defaultQuestionCount": 8,
    "durationSeconds": 900,
    "rubricVersion": "rubric.v1",
    "dataPolicy": "SANITIZED_TEXT_ONLY"
  }
}
~~~

Rules:

- Không đưa raw file bytes, local storage path, API key, PIN, email, số điện thoại, địa chỉ hoặc ảnh vào provider payload nếu không cần thiết.
- candidateCode được ưu tiên thay cho full name. Nếu cần tên để hiểu ngữ cảnh, chỉ dùng tên đã được HĐCM xác nhận.
- Text được bao bằng delimiter và gắn nhãn UNTRUSTED_DOCUMENT hoặc UNTRUSTED_ANSWER.
- Input manifest lưu document IDs/hashes và answer IDs; không lưu raw HTTP payload trong log.

### 3.2. Question generation input

Bắt buộc:

- Current confirmed JD text.
- Current confirmed clean CV text.
- Position title và target level.
- Default duration 900 giây hoặc duration của Question Set.
- maxQuestions không vượt 8.
- Question policy, question mix và rubric policy.
- Prompt/schema version.

Question policy mặc định:

- Tối đa 8 câu.
- Có câu standardized theo JD/level.
- Có câu situational.
- Có câu CV verification.
- Có câu gap/conflict nếu evidence chưa đủ.
- Mỗi câu có competency, purpose, expected evidence và rubric.
- Không hỏi lại dữ liệu đã rõ trong CV trừ mục đích kiểm chứng.

### 3.2.1. Question variant input

Bắt buộc:

- Current DRAFT/GENERATED Question Set ID và source question ID.
- Sanitized JD/CV context nếu cần để giữ đúng competency và evidence.
- Source question content/rubric cùng protected slot metadata.
- `mode` là `USER_PROMPT` hoặc `SAME_GROUP`.
- Với `USER_PROMPT`, prompt sau trim phải khác rỗng và không vượt quá 2.000 ký tự; prompt là untrusted content.
- Prompt/schema version và source fingerprint.

AI không được trả hoặc thay đổi question ID, display order, competency, category, type, difficulty, required, estimated seconds hoặc source kind.

### 3.2.2. Question addition input

Input bắt buộc Question Set DRAFT/GENERATED ID, target category, mode `USER_PROMPT` hoặc
`AUTO_GROUP`, sanitized JD/CV và các câu hiện có để tránh lặp. Prompt USER_PROMPT sau trim tối
đa 2.000 ký tự và là untrusted instruction. Mapping source kind là FOUNDATION → STANDARDIZED,
APPLICATION → SITUATIONAL; DEEP_DIVE cho phép CV_VERIFICATION hoặc GAP_CONFLICT. Output không
được thay đổi identity hoặc workflow policy.

### 3.3. Answer evaluation input

Bắt buộc:

- JD/CV snapshot đã dùng để tạo approved Question Set.
- Approved Question Set và rubric snapshot.
- AssessmentAttempt ID và answer snapshot.
- Với answer chưa trả lời: isAnswered=false, answerText rỗng, không suy đoán nội dung.
- Prompt/schema version.

Mỗi answer phải có questionId, questionText, competencyKey, expectedEvidence, rubric và answerText/isAnswered.

### 3.4. Follow-up input

Bắt buộc:

- Current Interview Brief.
- Live Interview Records đã ghi.
- Competencies còn thiếu evidence hoặc đang conflict.
- Câu hỏi đã hỏi/bỏ qua.
- Stop conditions của HĐCM.

Không gửi transcript/audio vì MVP không có ghi âm hoặc speech-to-text.

## 4. Output contract

### 4.1. Generate questions

Output phải có:

- schemaVersion.
- competencyMatrix.
- questions từ 5 đến 8 phần tử.
- mỗi question có provisionalId, displayOrder, text, competencyKey, sourceKind, purpose, questionType, difficulty, expectedEvidence, rubric và isRequired.
- gaps và conflicts.
- estimatedDurationSeconds.
- confidence.
- limitations.

AI question output chỉ là DRAFT. HĐCM phải chỉnh/sắp xếp/duyệt trước khi case chuyển QUESTIONS_APPROVED.

### 4.1.1. Generate question variant

Output `question-variant.v1` có `schemaVersion`, `operation=GENERATE_QUESTION_VARIANT`, `mode`, `questionSetId`, `sourceQuestionId`, `variant`, `confidence` và `limitations`. `variant` chỉ gồm question text, purpose, next-step objective, expected evidence và rubric đã validate. Output là proposal, không tự apply và không có PASS/FAIL.

### 4.1.2. Generate question addition

Output `question-addition.v1` có `schemaVersion`, `operation=GENERATE_QUESTION_ADDITION`,
`mode`, `questionSetId`, `targetCategory`, một object `question` đầy đủ content/rubric,
`confidence` và `limitations`. Output là proposal, không tự thêm câu. Human-readable fields
dùng tiếng Việt; enum/field names giữ nguyên.

### 4.2. Evaluate answers — active two-pass contract

Một task `EVALUATE_ASSESSMENT` thực hiện tuần tự:

1. `EVIDENCE_ANALYSIS`: provider phân tích từng answer theo câu hỏi, competency và rubric, trả `answer-evidence.v1`. Kết quả trung gian chỉ dùng trong task, không materialize thành `AiResult` và không expose qua public endpoint.
2. `EVALUATION_SYNTHESIS`: provider nhận input đã sanitize cùng evidence analysis, trả `answer-evaluation.v2`. Chỉ output phase này được validate và materialize thành `AiResult`.

Task phải expose phase an toàn để frontend polling hiển thị đúng tiến trình. Nếu phase 1 hoặc phase 2 lỗi/schema không hợp lệ, task retry theo policy; không tạo partial/final result. Rerun tạo task/result version mới và giữ nguyên result cũ.

Output phase `EVALUATION_SYNTHESIS` phải có:

- schemaVersion.
- perAnswerEvaluations.
- competencyEvaluations.
- strengths.
- gaps.
- conflicts.
- risks.
- confidence.
- limitations.

`recommendedLiveQuestions` và `interviewBrief` không được yêu cầu, sinh hoặc lưu trong implementation active này.

Mỗi perAnswerEvaluation có:

- answerId/questionId.
- score từ 0 đến 4; answer chưa trả lời có score null.
- evidenceStatus.
- reasoning ngắn dựa trên answer và rubric.
- evidenceFound.
- concerns.
- cvConsistency.

### 4.3. Follow-up

Output có 1–3 câu hỏi. Mỗi câu có text, targetCompetency, reason, evidenceToSeek, stopCondition và priority.

Follow-up chỉ là gợi ý. HĐCM quyết định hỏi, bỏ qua hoặc sửa trước khi ghi LiveInterviewRecord.

## 5. Rubric và scoring

### 5.1. Scoring dimensions

Rubric chung gồm các chiều:

1. Đúng trọng tâm.
2. Chính xác.
3. Độ sâu.
4. Bằng chứng thực tế.
5. Mức độ làm chủ công việc.
6. Khả năng lập luận.
7. Nhất quán với CV.
8. Đầy đủ.

Score tổng là integer 0–4:

| Score | Ý nghĩa |
| ---: | --- |
| 0 | Không trả lời hoặc hoàn toàn sai |
| 1 | Rất yếu, không có bằng chứng |
| 2 | Có hiểu biết cơ bản nhưng chưa đủ |
| 3 | Đáp ứng yêu cầu |
| 4 | Đáp ứng tốt, có bằng chứng và lập luận rõ |

AI không được tự tính PASS/FAIL từ score. HĐCM có thể override score/evidence và phải ghi audit.

### 5.2. Evidence status

Giá trị:

- VERIFIED.
- PARTIALLY_VERIFIED.
- UNVERIFIED.
- CONFLICTING.
- NOT_MET.
- NOT_ASSESSED.

Answer rỗng phải là NOT_ASSESSED, không phải UNVERIFIED.

### 5.3. Confidence

confidence là số thực 0.0–1.0, phản ánh độ chắc chắn của AI về evidence analysis, không phải xác suất tuyển dụng. AI phải ghi limitations khi confidence thấp hoặc input thiếu.

## 6. Interview Brief contract — deferred

Phần này là target contract cho phase sau, chưa được sinh/lưu trong implementation active của `EVALUATE_ASSESSMENT`.

Interview Brief phải đọc được trong 3–5 phút và gồm:

1. candidate/job/level summary.
2. assessment completion và time.
3. strengths có evidence.
4. gaps/missing evidence.
5. conflicts giữa CV và answer.
6. competency matrix.
7. đúng 3 câu hỏi live bắt buộc nếu đủ dữ liệu.
8. tối đa 2 câu bổ sung.
9. signals của answer tốt/yếu.
10. confidence và limitations.

Nếu AI fail, HĐCM có thể tạo brief manual tối thiểu hoặc đi thẳng EVALUATION_PENDING theo 21 Workflow.

## 7. Prompt contract

### 7.1. Prompt files và version

| Prompt key | File | Version |
| --- | --- | --- |
| question_generation | prompts/question_generation_prompt.md | question-generation.v1 |
| question_variant_generation | prompts/question_variant_generation_prompt.md | question-variant.v1 |
| answer_evidence_analysis | prompts/answer_evidence_analysis_prompt.md | answer-evidence.v1 |
| answer_evaluation_synthesis | prompts/answer_evaluation_synthesis_prompt.md | answer-evaluation.v2 |
| answer_evaluation | prompts/answer_evaluation_prompt.md | answer-evaluation.v1 (legacy) |
| follow_up_question | prompts/follow_up_question_prompt.md | follow-up.v1 |

Prompt không hardcode trong HTTP handler. Provider adapter nhận prompt đã render từ file/versioned template.

### 7.2. Instruction hierarchy

Prompt phải phân tách:

1. System instruction của ứng dụng.
2. Task instruction.
3. Schema/format instruction.
4. Untrusted content: JD, CV, answer, live notes.

Instruction nằm trong CV/JD/answer không có quyền thay đổi task, schema, scoring hoặc policy.

### 7.3. Output-only rule

Provider phải trả một JSON object duy nhất, không Markdown fence, không giải thích ngoài schema. Nếu provider trả thêm text, validator reject và task được repair/retry một lần.

## 8. Validation

Validation thủ công bằng json và rule nội bộ, không dùng Pydantic hoặc jsonschema runtime dependency:

- JSON parse thành object.
- schemaVersion đúng.
- Required field đủ.
- Field type đúng.
- Enum đúng.
- Score 0–4 hoặc null theo rule.
- Confidence 0.0–1.0.
- Questions 5–8.
- Recommended live questions 3–5.
- Follow-up 1–3.
- String/array không vượt giới hạn.
- ID tham chiếu tồn tại trong input.
- Không có finalResult hoặc instruction yêu cầu tự tuyển/loại.

Output invalid không tạo AiResult thành công. Lưu AiTask error_code/message safe và chuyển retry/failure theo 21 Workflow.

## 9. Retry, timeout và failure

| Tình huống | Xử lý |
| --- | --- |
| Timeout/network | Retry tối đa một lần, exponential backoff |
| HTTP 429 | Retry một lần theo Retry-After hợp lệ hoặc backoff |
| HTTP 5xx | Retry tối đa một lần |
| HTTP 4xx do payload/auth | Không tự retry; FAILED |
| Invalid JSON/schema | Retry một lần với repair instruction |
| Provider không phản hồi | FAILED sau timeout; manual fallback |
| App restart khi RUNNING | Recovery thành PENDING_RETRY hoặc FAILED |
| AI result đã COMPLETED | Không chạy lại cùng idempotency key |

Timeout connect/read lấy từ configuration. AI call không chạy đồng bộ trong HTTP request; API trả 202 và frontend poll task.

## 10. Rerun và idempotency

- Rerun sau HĐCM sửa answer/rubric/question set tạo task mới với input fingerprint mới.
- Result mới tăng version_no và tham chiếu supersedes_result_id.
- Result cũ không bị sửa hoặc xóa.
- Sau khi Final Evaluation FINAL, rerun chỉ được tạo như một revision có audit reason; không tự đổi evaluation.
- Force rerun phải có actor Committee/HR hợp lệ.

## 11. Privacy và prompt-injection protection

- Chỉ dùng clean CV và extracted text đã HĐCM xác nhận.
- Không gửi file gốc.
- Không gửi PII không cần thiết.
- Nếu tổ chức không cho phép dữ liệu ra ngoài, adapter phải trỏ tới approved internal gateway/local endpoint; nếu không có, dùng manual fallback.
- Prompt luôn coi document/answer/live notes là untrusted content.
- Không thực thi macro, script, URL, function call hoặc instruction trong document.
- AI output được render/lưu như dữ liệu; frontend dùng textContent, không innerHTML.
- Log chỉ lưu task ID, provider status, duration và error code đã redact.

## 12. Human review

| AI output | Human gate |
| --- | --- |
| Proposed questions | HĐCM edit và approve Question Set |
| Per-answer evaluation | HĐCM xem answer gốc và có thể override |
| Interview Brief | HĐCM dùng để hỏi live, không phải kết luận |
| Follow-up | HĐCM chọn/sửa trước khi hỏi |
| Final Evaluation | Chỉ HĐCM lead/finalizer được chốt |

## 13. Conflict / Assumption / Open Questions

### Conflict

- Context mô tả cả GenerateInterviewBrief và SuggestFollowUp, nhưng implementation active hiện chỉ materialize output evaluation hai phase; Interview Brief/follow-up được giữ ở backlog và không được giả lập trong UI/runtime.
- Context gọi score 0–4 là “khuyến nghị”; quyết định 1A đã chốt score range và rubric chung cho MVP.

### Assumption

- AI output payload đầy đủ được lưu trong ai_results.payload_json sau validation; bảng normalized riêng chỉ bổ sung khi có nhu cầu query sau MVP.
- Ba câu live bắt buộc và tối đa hai câu bổ sung là giới hạn MVP; nếu AI không đủ evidence, output ghi limitation thay vì bịa câu trả lời.
- final_level không thuộc AI output bắt buộc và chỉ do HĐCM nhập/chốt.

### Open Questions / Backlog

- Chọn provider/model/quota cụ thể.
- Tách riêng GenerateInterviewBrief thành provider capability sau MVP nếu cần.
- Rubric weight và competency-level aggregation chi tiết.
- Benchmark quality và calibration giữa nhiều HĐCM.

## 14. Acceptance criteria

1. Có contract cho question generation, answer evaluation và follow-up.
2. Có prompt key/version và supporting artifact path.
3. Có schema JSON tương ứng cho cả ba capability.
4. Có rubric 0–4 và evidence status đúng Context.
5. Có strengths, gaps, concerns, conflicts, missing evidence và confidence.
6. Có Interview Brief tối đa 3–5 phút đọc khi capability deferred được kích hoạt.
7. Có validation thủ công, retry tối đa một lần, timeout và manual fallback.
8. Có rerun versioning/idempotency, không overwrite.
9. Có prompt injection protection và data minimization.
10. AI không có khả năng tự chốt PASS/FAIL.
11. Có human review gate, audit và traceability về snapshot input.
