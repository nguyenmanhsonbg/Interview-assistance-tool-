# CV AI Parsing Flow Specification

Status: Current implementation baseline  
Version: 1.0  
Audience: Engineers implementing the CV parsing flow in another system

## 1. Mục tiêu

Hệ thống nhận CV, trích xuất nội dung bằng parser cục bộ, gửi nội dung đã kiểm soát lên Gemini để chuẩn hóa thành hồ sơ ứng viên có cấu trúc, sau đó lưu kết quả để dùng cho recruitment screening, mapping và interview workflow.

Luồng hiện tại có hai pipeline:

1. Recruitment CV pipeline mới: upload original CV, malware scan, sanitize sang safe storage, parse clean CV, gọi Gemini và lưu ParsedProfile.
2. Candidate upload pipeline cũ: upload một hoặc nhiều file, parse cục bộ, merge nội dung, gọi Gemini để enrich profile rồi upsert Candidate.

Hai pipeline dùng cùng Gemini API nhưng khác lifecycle, database model và fallback.

## 2. Phạm vi và ngoài phạm vi

### 2.1 Trong phạm vi

- CV PDF, DOCX và XLSX.
- File parser cục bộ.
- Chuẩn hóa raw text.
- Resume signal validation.
- Gemini structured CV parsing.
- Model rotation và fallback.
- Lưu parsed profile, parser metadata và audit/workflow events.
- Idempotency, retry và force reparse.
- Fallback khi Gemini không khả dụng.

### 2.2 Ngoài phạm vi

- AI screening ứng viên sau khi profile đã được parse.
- Sanitizer implementation chi tiết của Ghostscript/Docker worker.
- Malware scanner implementation chi tiết.
- Prompt business đầy đủ của từng role.
- Quyết định tuyển dụng tự động.

## 3. Kiến trúc tổng quan

### 3.1 Recruitment pipeline mới

    Original CV
        |
        v
    Upload vào QUARANTINE storage
        |
        v
    Malware scan
        |
        +-- rejected/failed --> CV_REJECTED_MALWARE hoặc CV_SCAN_FAILED
        |
        v
    Sanitize CV
        |
        +-- failed --> CV_SANITIZE_FAILED
        |
        v
    Clean CV trong SAFE storage
        |
        v
    Local file parser
        |
        +-- parser error/empty text --> CV_PARSE_FAILED
        |
        v
    Normalize text + validate resume signals
        |
        v
    Gemini structured parser
        |
        +-- Gemini unavailable --> giữ local parser data, đánh dấu AI skipped/failed
        |
        v
    Normalize Gemini profile
        |
        v
    Merge parsed data + AI metadata
        |
        v
    Lưu ParsedProfile
        |
        v
    CV_PARSED + duplicate checks + audit events

### 3.2 Candidate upload pipeline cũ

    Candidate upload files
        |
        v
    Local FileParserService
        |
        +-- raw text + regex/basic fields
        |
        v
    Merge nhiều file và file bổ sung đã lưu
        |
        +-- có raw text --> AiService.enrichParsedProfile
        |
        +-- không có raw text --> AiService.analyzeFileDirectly
        |
        v
    Merge Gemini profile với parser fields
        |
        v
    Upsert Candidate.parsedProfile

Pipeline cũ không đi qua cùng lifecycle original/CLEAN/SAFE của recruitment pipeline mới.

## 4. Các component

| Component | Trách nhiệm |
|---|---|
| CvDocumentsController | Upload, sanitize và parse CV qua HTTP API. |
| CvDocumentsService | Quản lý CV document versions, current document và metadata. |
| CvSanitizationService | Chuyển original CV từ QUARANTINE sang clean CV trong SAFE storage. |
| FileParserService | Đọc PDF/DOCX/XLSX và tạo raw text cùng parser hints. |
| CvParsingService | Orchestrate parse, state transition, persistence, idempotency và audit. |
| GeminiCvParserService | Gọi Gemini cho structured CV parsing, model rotation và response normalization. |
| ParsedProfileEntity | Lưu parsed profile gắn với application, candidate và clean CV. |
| AiService | Pipeline cũ: profile enrichment và direct file analysis. |
| WorkflowStateService | Ghi application status transition hoặc workflow event. |

## 5. API contract của recruitment pipeline

Tất cả route dưới đây yêu cầu backend authentication theo role hiện tại. Prefix /api được giả định là global prefix của backend.

### 5.1 Upload original CV

    POST /api/applications/{applicationId}/cv

Content-Type:

    multipart/form-data

Form fields:

| Field | Required | Type | Description |
|---|---:|---|---|
| cvFile | Yes | file | Original CV. |
| replaceCurrent | No | boolean | Mặc định true. Có thay CV current hay không. |
| reason | No | string, max 1000 | Lý do upload/thay thế CV. |

Header tùy chọn:

    Idempotency-Key: <client-generated-key>

Response đại diện:

    {
      "success": true,
      "data": {
        "applicationId": "<application-id>",
        "cvDocumentId": "<original-cv-document-id>",
        "documentType": "ORIGINAL",
        "versionNo": 1,
        "scanStatus": "PENDING",
        "sanitizeStatus": "PENDING",
        "parseStatus": "PENDING",
        "isCurrent": true,
        "nextStep": "CV_SANITIZE_PENDING"
      },
      "meta": {
        "idempotencyKey": "<echo-or-null>",
        "timestamp": "<iso-timestamp>"
      }
    }

Upload chỉ tiếp nhận original CV. Không được parse trực tiếp file đang ở QUARANTINE.

### 5.2 Sanitize CV

    POST /api/applications/{applicationId}/cv/{cvDocumentId}/sanitize

Body:

    {
      "force": false
    }

Điều kiện:

- Document phải là ORIGINAL.
- scanStatus phải là PASSED.
- Document phải thuộc application tương ứng.
- Application status phải cho phép sanitize.
- Chỉ current original CV được sanitize, trừ retry hợp lệ sau failure.

Kết quả thành công tạo một document CLEAN mới:

    {
      "success": true,
      "data": {
        "applicationId": "<application-id>",
        "cvDocumentId": "<clean-cv-document-id>",
        "cleanCvDocumentId": "<clean-cv-document-id>",
        "documentType": "CLEAN",
        "versionNo": 1,
        "sanitizeStatus": "SANITIZED",
        "cleanFileHashRecorded": true,
        "storageZone": "SAFE",
        "nextStatus": "CV_SANITIZED",
        "nextStep": "CV_PARSE_PENDING"
      }
    }

### 5.3 Parse clean CV bằng Gemini

    POST /api/applications/{applicationId}/cv/{cvDocumentId}/parse

Body:

    {
      "parserMode": "GEMINI",
      "force": false
    }

Header tùy chọn:

    Idempotency-Key: <client-generated-key>

Ý nghĩa fields:

| Field | Description |
|---|---|
| parserMode | Tên mode dùng cho audit metadata. Giá trị hiện tại thường là GEMINI. Trong implementation hiện tại, mode chưa phải provider switch; parser vẫn gọi Gemini. |
| force | Nếu false, trả parsed profile hiện có. Nếu true, chạy parse mới và tạo profile mới. |

Response thành công:

    {
      "success": true,
      "data": {
        "applicationId": "<application-id>",
        "cvDocumentId": "<clean-cv-document-id>",
        "parsedProfileId": "<parsed-profile-id>",
        "candidateId": "<candidate-id>",
        "status": "CV_PARSED",
        "normalizedTextHashRecorded": true,
        "parserVersion": "gemini-cv-parser-v1:gemini-3.6-flash",
        "createdAt": "<iso-timestamp>"
      },
      "meta": {
        "idempotencyKey": "<echo-or-null>",
        "timestamp": "<iso-timestamp>"
      }
    }

Frontend hiện tại gọi API này với:

    {
      "parserMode": "GEMINI",
      "force": true
    }

## 6. Điều kiện trước khi parse

CvParsingService chỉ cho parse khi thỏa tất cả điều kiện sau:

- CV document tồn tại và thuộc application.
- documentType = CLEAN.
- storageZone = SAFE.
- sanitizeStatus = SANITIZED.
- cleanFileHash tồn tại.
- Document là current clean CV, hoặc application đang tham chiếu đúng document đó.
- Application không ở terminal status.
- CV không đang có parseStatus = PARSING.

Application có thể bắt đầu parse khi:

- status là CV_SANITIZED;
- status là CV_PARSE_FAILED để retry;
- hoặc status không thuộc terminal application statuses.

Nếu đã có ParsedProfile cho clean CV và force = false, API trả profile cũ theo cơ chế idempotent và không gọi Gemini lại.

## 7. File parser cục bộ

Gemini không nhận file trực tiếp trong main clean-CV parsing flow. Hệ thống trước tiên đọc clean file từ SAFE storage bằng FileParserService.

### 7.1 Supported file types

| Extension | Parser | Output chính |
|---|---|---|
| .pdf | pdf-parse | rawText + basic email/phone/skill hints |
| .docx | mammoth | rawText + basic email/phone/skill hints |
| .xlsx | ExcelJS | structured fields + rawText tổng hợp |

PDF có giới hạn local parser là 20 MB. Parser phải trả về:

    {
      "rawText": "<extracted-text>",
      "...": "basic parser fields"
    }

Nếu parser lỗi:

    {
      "rawText": "",
      "error": "<safe-error-message>"
    }

### 7.2 Raw text validation

Sau khi local parser chạy:

1. Loại bỏ null character và giá trị JSON không hợp lệ.
2. Lấy parsedData.rawText.
3. Chuẩn hóa whitespace/text.
4. Nếu parser có error, dừng parse với reason code PARSER_FAILED.
5. Nếu text rỗng sau normalize, dừng parse với reason code EMPTY_PARSED_TEXT.
6. Chạy validateResumeSignals.
7. Gửi raw text và parser hints cho Gemini.

Local parser là bước extraction và hint generation. Gemini là bước semantic structuring/enrichment.

## 8. Gemini CV parser contract

### 8.1 Provider endpoint

    POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}

Header:

    Content-Type: application/json

API key chỉ được lưu và sử dụng ở backend.

### 8.2 Models

Model rotation hiện tại:

    gemini-3.6-flash
    gemini-3.5-flash
    gemini-3.5-flash-lite

Model alias được normalize trước khi gọi. Một parse attempt có thể gửi tối đa một request cho mỗi model trong rotation.

### 8.3 Configuration

    GEMINI_API_KEY=<server-side-secret>
    GEMINI_CV_PARSE_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite
    GEMINI_CV_PARSE_TIMEOUT_MS=45000
    GEMINI_CV_PARSE_MAX_CHARS=36000

Rules:

- GEMINI_API_KEY là bắt buộc để AI parse.
- Nếu không cấu hình model, dùng default model list.
- Model không hợp lệ bị bỏ qua.
- Timeout tối thiểu hợp lệ là 5000 ms; mặc định 45000 ms.
- Text gửi Gemini bị giới hạn mặc định 36000 ký tự.

### 8.4 Request body

Dedicated CV parser gửi toàn bộ prompt dưới dạng một user text part:

    {
      "contents": [
        {
          "role": "user",
          "parts": [
            {
              "text": "<COMBINED_CV_PARSER_PROMPT>"
            }
          ]
        }
      ],
      "generationConfig": {
        "temperature": 0.1,
        "topP": 0.8,
        "responseMimeType": "application/json"
      }
    }

Combined prompt phải bao gồm:

1. System instruction về vai trò CV parser song ngữ Anh/Việt.
2. Level categorization guidelines.
3. Project extraction rules.
4. Target JSON schema.
5. Regex/parser hints.
6. Raw CV text đã truncate.

Prompt phải yêu cầu Gemini:

- chỉ trả về một JSON object;
- không trả Markdown;
- không giải thích bên ngoài JSON;
- không tự tạo thông tin không có trong CV;
- trường không có dữ liệu phải bỏ qua hoặc trả mảng rỗng.

### 8.5 Response extraction

Đọc response theo đường dẫn:

    candidates[0].content.parts[*].text

Các text parts được nối lại, trim và parse JSON. Dedicated parser chấp nhận cả response nằm trong Markdown code fence để tăng khả năng chịu lỗi.

Response rỗng, HTTP error hoặc JSON không hợp lệ được xem là failed attempt. Parser thử model tiếp theo.

## 9. Rotation và fallback

Thuật toán:

    models = normalize(defaultModels + configuredModels)
    startIndex = nextModelIndex modulo models.length
    advance nextModelIndex

    for model in rotation:
        send request with timeout
        if HTTP/network/timeout/empty/invalid JSON:
            log safe error
            try next model
        else:
            return normalized profile

    return null

Đặc điểm:

- Rotation là process-local round-robin.
- Không retry cùng model với exponential backoff trong implementation hiện tại.
- Không log API key.
- Error message phải redact API key nếu provider trả lại URL hoặc token.
- Nếu tất cả Gemini models thất bại, GeminiCvParserService.parseProfile trả null thay vì throw ra ngoài.

## 10. Chuẩn hóa Gemini profile

Sau khi Gemini trả JSON, hệ thống chuẩn hóa profile trước khi lưu.

### 10.1 Sanitization

- Loại bỏ null character.
- Trim string.
- Bỏ các redacted placeholder không hợp lệ.
- Chỉ giữ object record hợp lệ.
- Không overwrite raw text bằng nội dung do Gemini tạo ra.

### 10.2 Work experience

- Đảm bảo workExperience là array các object.
- Tìm current company từ entry chưa có end date/end year hoặc chứa present/current/now/nay.
- Tính lại tổng số năm kinh nghiệm bằng cách merge các khoảng thời gian bị overlap.
- Làm tròn total years experience đến một chữ số thập phân.

### 10.3 Skills và fields

- Gộp skills từ skills, techstack và groupedSkills.
- Loại trùng bằng Set.
- Giữ techstack, certifications, languages, warnings ở dạng array string.
- Parse birthYear thành integer nếu hợp lệ.
- Clamp parseConfidence về range domain đã định nghĩa.
- Chỉ giữ skill Go/Golang khi raw CV thực sự có evidence cho Go/Golang; tránh false positive từ từ ngữ thông thường.

### 10.4 Parsed profile shape

    {
      "name": "Nguyen Van A",
      "email": "candidate@example.com",
      "phone": "+84901234567",
      "education": "...",
      "totalYearsExperience": 5.5,
      "experienceByLanguage": {
        "TypeScript": 3,
        "Java": 2
      },
      "skills": ["Node.js", "PostgreSQL"],
      "groupedSkills": {
        "backend": ["NestJS", "REST API"]
      },
      "techstack": ["NestJS", "React", "PostgreSQL"],
      "certifications": [],
      "workExperience": [],
      "projects": [],
      "level": "SENIOR",
      "parseConfidence": 0.88,
      "vcsSignals": {},
      "warnings": []
    }

Unknown fields nên được giữ lại để tương thích forward-compatible, trừ khi chứa dữ liệu nhạy cảm hoặc không hợp lệ cho JSONB.

## 11. Merge và persistence

Kết quả cuối cùng của parse clean CV có dạng:

    parsedData = {
      ...localParserData,
      ...geminiParsedData,
      rawText,
      resumeValidation,
      parserMode,
      aiParse
    }

Gemini fields ghi đè field cùng tên từ local parser vì Gemini là semantic source chính. rawText, resumeValidation, parserMode và aiParse được backend gắn lại sau đó.

### 11.1 AI metadata

Khi Gemini thành công:

    {
      "provider": "gemini",
      "status": "SUCCESS",
      "model": "gemini-3.6-flash",
      "attemptedModels": ["gemini-3.6-flash"],
      "parsedAt": "<iso-timestamp>"
    }

Khi Gemini không có key hoặc toàn bộ models thất bại:

    {
      "provider": "gemini",
      "status": "SKIPPED_OR_FAILED",
      "parsedAt": "<iso-timestamp>"
    }

Trong trường hợp AI thất bại nhưng local parser đã tạo được raw text, flow vẫn có thể tạo ParsedProfile với local data và metadata SKIPPED_OR_FAILED.

### 11.2 ParsedProfileEntity

Parsed profile cần lưu tối thiểu:

| Field | Description |
|---|---|
| applicationId | Application sở hữu CV. |
| cvDocumentId | Clean CV đã được parse. |
| candidateId | Candidate được liên kết. |
| parsedData | JSONB profile sau merge và normalize. |
| normalizedTextHash | SHA-256 của normalized raw text. |
| parserVersion | gemini-cv-parser-v1:<model> hoặc file-parser-v1 nếu không có Gemini result. |
| createdAt | Timestamp tạo profile. |

### 11.3 Document state

Khi persistence thành công:

- CvDocument.parseStatus = PARSED.
- Application transition/event tới CV_PARSED nếu expected status phù hợp.
- Ghi workflow event CV_PARSED.
- Ghi audit logs CV_PARSED và PARSED_PROFILE_CREATED.
- Chạy parsed profile duplicate check.
- Lưu metadata gồm rawTextLength, extractedFields, parserMode và normalizedTextHash.

## 12. Idempotency và concurrency

### 12.1 Idempotent parse

- Tìm ParsedProfile mới nhất theo cvDocumentId.
- Nếu force = false và profile tồn tại, trả profile cũ.
- Ghi audit event CV_PARSE_IDEMPOTENT_RETRY.
- Không đọc file và không gọi Gemini lại.

### 12.2 Force parse

- force = true bỏ qua existing profile.
- Đọc lại clean file.
- Gọi local parser và Gemini.
- Tạo ParsedProfile mới.
- Không xóa profile lịch sử cũ.

### 12.3 Locking

- Chuẩn bị parse dùng database transaction.
- Application và CV document được đọc với pessimistic write lock khi cần.
- parseStatus = PARSING ngăn hai parse job chạy đồng thời cho cùng một document.
- Khi persist kết quả, kiểm tra lại existing profile nếu không force để tránh duplicate do race condition.

### 12.4 Idempotency-Key

- Client gửi header Idempotency-Key.
- Backend chỉ lưu hash của key trong metadata/audit.
- Không lưu raw idempotency key.
- Idempotency key không thay thế database lock hoặc existing-profile check.

## 13. Error và fallback matrix

| Situation | Reason code/status | Behavior |
|---|---|---|
| CV document không tồn tại | BadRequest | HTTP 400, không gọi parser/Gemini. |
| Document không phải CLEAN | BadRequest | HTTP 400. |
| Storage không phải SAFE | BadRequest | HTTP 400. |
| Chưa sanitize | BadRequest | HTTP 400. |
| Chưa có clean hash | BadRequest | HTTP 400. |
| CV đang PARSING | BadRequest | HTTP 400, tránh concurrent parse. |
| Unsupported extension | Parser error | Parse failed, manual review/retry. |
| PDF > 20 MB | PARSER_FAILED | CV_PARSE_FAILED; reupload có thể cần. |
| Local parser error | PARSER_FAILED | CvDocument.parseStatus = FAILED, application CV_PARSE_FAILED. |
| Raw text rỗng | EMPTY_PARSED_TEXT | CV_PARSE_FAILED, có thể yêu cầu candidate reupload. |
| Missing GEMINI_API_KEY | SKIPPED_OR_FAILED | Giữ local parser data nếu có, không có Gemini fields. |
| Gemini HTTP 4xx/5xx | Per-model failure | Thử model tiếp theo. |
| Gemini timeout | Per-model failure | Thử model tiếp theo. |
| Gemini response rỗng | Per-model failure | Thử model tiếp theo. |
| JSON response invalid | Per-model failure | Thử model tiếp theo. |
| Tất cả models failed | SKIPPED_OR_FAILED | Có thể persist local parse data nếu raw text hợp lệ. |
| Database persistence lỗi | CV_PARSE_FAILED hoặc transaction rollback | Không trả profile chưa lưu. |

Điểm quan trọng: Gemini failure không đồng nghĩa local extraction failure. Hệ thống phải phân biệt hai loại lỗi này để không làm mất dữ liệu parser cục bộ.

## 14. Legacy candidate upload flow

### 14.1 Endpoint

    POST /api/candidates/upload

Content-Type:

    multipart/form-data

Fields:

| Field | Description |
|---|---|
| files | Tối đa 20 files theo controller hiện tại. |
| socketId | Tùy chọn để emit progress event. |
| candidateId | Tùy chọn; nếu có thì update candidate đó. |

### 14.2 Processing

1. Parse từng uploaded file bằng FileParserService.
2. Thu thập raw texts.
3. Thu thập regex/basic fields.
4. Parse các complementary files đã lưu của candidate.
5. Merge raw texts bằng separator.
6. Merge regex fields.
7. Nếu có raw text:
   - gọi AiService.enrichParsedProfile;
   - nếu Gemini fail, dùng merged regex fields.
8. Nếu không có raw text:
   - gọi AiService.analyzeFileDirectly cho file đầu tiên;
   - nếu Gemini fail, dùng regex fields.
9. Nếu thiếu name, tạo name fallback từ filename.
10. Upsert một Candidate.

### 14.3 Re-analysis endpoint

    POST /api/candidates/{idOrSlug}/analyze

Flow:

1. Đọc resumeUrl/profileXlsxUrl đã lưu.
2. Parse lại bằng FileParserService.
3. Gọi Gemini enrich profile.
4. Gọi Gemini detect profile anomalies.
5. Lưu Candidate parsed profile.
6. Emit parsing, analyzing, saving, done/error progress events.

Legacy flow lưu profile trực tiếp trên Candidate, không tạo ParsedProfileEntity theo application/CV document model mới.

## 15. Security và privacy

1. Chỉ gửi clean CV từ SAFE storage trong recruitment pipeline mới.
2. Không gửi original/quarantine file tới Gemini.
3. API key chỉ tồn tại ở backend.
4. Không log raw CV, interview data, base64 file hoặc full URL có query key.
5. Redact API key trong mọi provider error.
6. Giới hạn file size và raw text size trước khi gọi Gemini.
7. Validate MIME type trước khi dùng inline base64 fallback.
8. Xem Gemini output là untrusted input.
9. Validate enum, numeric range, array size và object shape trước khi lưu.
10. Không dùng protected attributes để xếp hạng hoặc quyết định ứng viên.
11. AI parsing chỉ tạo dữ liệu hỗ trợ; không tự động reject/hire candidate.
12. Xác định chính sách consent, retention và Google data processing trước production.

## 16. Observability và audit

Mỗi parse request nên ghi metadata không chứa raw content:

    {
      "applicationId": "<application-id>",
      "cvDocumentId": "<clean-cv-document-id>",
      "parserMode": "GEMINI",
      "provider": "gemini",
      "status": "SUCCESS",
      "model": "gemini-3.6-flash",
      "attemptedModels": ["gemini-3.6-flash"],
      "rawTextLength": 18420,
      "normalizedTextHash": "<sha256>",
      "parserVersion": "gemini-cv-parser-v1:gemini-3.6-flash",
      "durationMs": 1820,
      "generatedAt": "<iso-timestamp>"
    }

Metrics nên có:

- parse request count theo parserMode;
- Gemini success/skipped/failed count;
- model fallback count;
- timeout/rate-limit/provider error count;
- local parser failure count;
- empty raw text count;
- parse latency;
- CV parse success rate;
- percentage profile chỉ có local parser data;
- duplicate profile detection count.

Audit/workflow events hiện tại gồm:

- CV_PARSE_REQUESTED;
- CV_PARSED;
- CV_PARSE_FAILED;
- CV_PARSE_IDEMPOTENT_RETRY;
- PARSED_PROFILE_CREATED.

## 17. Implementation checklist cho hệ thống khác

- [ ] Tách original file và clean file thành hai storage zone.
- [ ] Không parse file từ quarantine.
- [ ] Thêm malware scan trước sanitize.
- [ ] Tạo clean artifact và lưu clean hash.
- [ ] Implement local parser cho PDF/DOCX/XLSX.
- [ ] Normalize raw text và giới hạn kích thước.
- [ ] Tạo resume signal validation trước Gemini.
- [ ] Implement Gemini structured parser adapter.
- [ ] Implement model rotation và timeout.
- [ ] Implement JSON extraction và schema validation.
- [ ] Implement profile normalization sau Gemini.
- [ ] Lưu provider/model/attempt metadata nhưng không lưu secret/prompt content nhạy cảm.
- [ ] Implement idempotency và force reparse.
- [ ] Implement parse state machine.
- [ ] Phân biệt local parser failure và Gemini failure.
- [ ] Cho phép lưu local parser data khi Gemini unavailable nếu raw text hợp lệ.
- [ ] Thêm duplicate check sau khi ParsedProfile được tạo.
- [ ] Thêm audit/workflow events.
- [ ] Mock Gemini trong test cho các case success, fallback, timeout, empty response và invalid JSON.
- [ ] Test file parser riêng cho PDF, DOCX, XLSX, file lớn và file rỗng.

## 18. Repository references

Implementation hiện tại:

- apps/backend/src/cv-documents/cv-documents.controller.ts
- apps/backend/src/cv-documents/entities/cv-document.entity.ts
- apps/backend/src/cv-documents/entities/parsed-profile.entity.ts
- apps/backend/src/cv-parsing/cv-parsing.service.ts
- apps/backend/src/cv-parsing/gemini-cv-parser.service.ts
- apps/backend/src/cv-parsing/resume-validation.util.ts
- apps/backend/src/file-parser/file-parser.service.ts
- apps/backend/src/cv-sanitization/cv-sanitization.service.ts
- apps/backend/src/candidates/candidates.controller.ts
- apps/backend/src/ai/ai.service.ts
- apps/backend/src/recruitment-common/enums/recruitment.enum.ts
- apps/frontend/src/lib/recruitment-api.ts

Provider-level contract chi tiết nằm trong:

- docs/gemini-api-specification.md

