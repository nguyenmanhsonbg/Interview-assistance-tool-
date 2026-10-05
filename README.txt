ClawCV Phase 2 Supervised Interview — Windows Portable
======================================================

1. Giải nén toàn bộ ZIP vào một thư mục local.
2. Chạy start.bat. Trình duyệt mở http://127.0.0.1:8787.
3. Lần chạy đầu, đặt Committee PIN gồm 4–12 chữ số.
4. Dữ liệu nằm tại %LOCALAPPDATA%\ClawCV, không nằm trong thư mục cài đặt.

AI là tùy chọn. Nếu chưa cấu hình, ứng dụng chuyển task sang FAILED an toàn và
cho phép dùng bộ câu hỏi/Interview Brief manual. Để cấu hình approved gateway,
đặt AI_ENDPOINT, AI_MODEL và AI_API_KEY trong environment trước khi chạy.

Backup thủ công nằm dưới %LOCALAPPDATA%\ClawCV\backups. Hãy tạo backup trước
khi xóa case hoặc chuyển dữ liệu. Không chia sẻ backup/export khi chưa kiểm tra
chính sách dữ liệu của tổ chức.

Ứng dụng chỉ bind 127.0.0.1. Không sửa APP_HOST sang địa chỉ LAN/public.

Gemini provider (optional)
-------------------------
Set these environment variables before starting the portable app:

  AI_PROVIDER=gemini
  GEMINI_API_KEY=<your-gemini-api-key>
  GEMINI_CV_PARSE_MODELS=gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite
  GEMINI_CV_PARSE_TIMEOUT_MS=45000

Alternatively, create a .env file in the project root with these values.
Windows environment variables override values from .env. The .env file is
ignored by Git; never commit a real API key.

The app calls Gemini through generateContent, rotates configured models for
retryable failures, and keeps the manual fallback. Only extracted, sanitized,
confirmed text is sent. Raw files, base64 content, PINs, tokens and API keys
are not sent to the provider or written to logs. Verify model availability and
the account data policy before a pilot. Without AI_PROVIDER=gemini, the
generic provider configuration remains the default.

Active Excel assessment flow
----------------------------
The current Committee flow is:
  1. Create a case and enter/confirm JD and CV text.
  2. Generate or manually create the question set.
  3. Review/approve questions and export the canonical question-answer.v1 .xlsx workbook.
  4. Fill the answer cells in that workbook and import the same .xlsx file.
  5. Start AI evaluation and review the read-only answer-evaluation.v2 result.

Only .xlsx files exported by the tool are accepted. The backend validates the
metadata, question rows, rubric, answer flags and file limits. Blank answers
are NOT_ASSESSED. Imported snapshots are immutable; a changed workbook creates
a new version. Raw workbook bytes are not sent to Gemini or written to logs.

Candidate Mode, Interview Brief, live interview and Final Evaluation are not
active in this refined UI. Existing historical data is retained for recovery.
AI output is advisory evidence only; it does not make a hiring decision.
