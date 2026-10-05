# ClawCV — Phase 2 Supervised Interview

Ứng dụng local-first hỗ trợ HĐCM chuẩn bị và thực hiện supervised interview trên một máy Windows. Runtime chỉ dùng Python Standard Library, `ThreadingHTTPServer`, SQLite và HTML/CSS/JavaScript thuần.

## Chạy development

Yêu cầu Python 3.10+:

```powershell
python main.py
```

Mở `http://127.0.0.1:8787`. Lần đầu ứng dụng yêu cầu tạo Committee PIN. Dữ liệu mặc định nằm dưới `%LOCALAPPDATA%\ClawCV`.

Chạy test:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_tests.ps1
```

Nếu `python` không có trong PATH, truyền đường dẫn rõ ràng bằng `-PythonExe`.

## Cấu hình AI

AI là tùy chọn; không cấu hình vẫn dùng được manual fallback.

```powershell
$env:AI_ENDPOINT = "https://approved-ai-gateway.example/v1/interview"
$env:AI_MODEL = "approved-model"
$env:AI_API_KEY = "session-secret"
python main.py
```

Để dùng Gemini trực tiếp thay cho approved gateway, đặt provider và API key:

```powershell
$env:AI_PROVIDER = "gemini"
$env:GEMINI_API_KEY = "your-gemini-api-key"
$env:GEMINI_CV_PARSE_MODELS = "gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite"
$env:GEMINI_CV_PARSE_TIMEOUT_MS = "45000"
python main.py
```

Hoặc tạo file `.env` ở thư mục gốc project với cùng các biến trên:

```dotenv
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
GEMINI_CV_PARSE_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite
GEMINI_CV_PARSE_TIMEOUT_MS=45000
```

Biến môi trường của Windows luôn được ưu tiên hơn giá trị trong `.env`.
File `.env` đã được git ignore; không commit file này chứa API key thật.

Gemini được gọi qua REST `generateContent`. Ứng dụng xoay vòng các model khi
gặp lỗi retryable, ghi provider/model vào metadata của AI task, và vẫn giữ
manual fallback khi provider không khả dụng. Chỉ text đã được extract,
sanitize và confirm mới được gửi; không gửi raw file, base64, PIN, token hoặc
API key. Kiểm tra model ID và chính sách dữ liệu của tài khoản Gemini trước
khi pilot. Nếu chưa cấu hình `AI_PROVIDER=gemini`, runtime mặc định dùng
provider generic hiện có.

Gateway nhận JSON `operation`, `model`, `promptVersion`, `prompt` và `input`; response phải là đúng một JSON object theo schema trong `schemas/`. Chỉ text đã xác nhận/sanitize được gửi; raw file, PIN và token không được gửi. API key chỉ đọc từ environment trong MVP và không được lưu vào database, frontend, log, backup hoặc export.

## Backup, restore và dữ liệu

- Dữ liệu: `%LOCALAPPDATA%\ClawCV` hoặc `DATA_DIRECTORY` khi development/test.
- Tạo backup/export từ màn hình Backup hoặc API Committee.
- Backup dùng SQLite Backup API; export ZIP có hash manifest và loại bỏ protected settings/token.
- Xóa case luôn tạo backup trước và giữ audit row sau khi dữ liệu case bị xóa.
- MVP không tự động xóa dữ liệu ứng viên.

Restore là thao tác operator có kiểm soát: dừng ứng dụng, giữ bản sao database hiện tại, xác minh backup bằng chức năng `BackupService.restore_to` vào đường dẫn tạm, rồi mới thay thế dữ liệu vận hành.

## Đóng gói Windows portable

```powershell
powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1
```

Script tải Python embeddable 64-bit chính thức, kiểm tra SHA-256, chạy smoke test, rồi tạo:

- `release/ClawCV-0.1.0-win64-portable.zip`
- `release/ClawCV-0.1.0-win64-portable.zip.sha256`

Máy pilot không cần cài Python, Node.js, Docker hoặc database server.

## Giới hạn pilot

- Một máy, một process, một candidate tại một thời điểm.
- PDF cần manual clean-text fallback; TXT/Markdown/DOCX được xử lý bằng Standard Library.
- Không có account doanh nghiệp/SSO, camera, microphone, coding judge hoặc tuyển dụng tự động.
- AI không được chốt PASS/FAIL; chỉ Committee lead mới finalize.
- External penetration test và browser automation là backlog trước production rộng.
