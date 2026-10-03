# 26. Phase 2 Supervised Interview Mini Tool — Document Processing Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Document Processing + Security |
| Last updated | 2026-10-04 |
| Depends on | 18 Technology Specification; 20 Domain and Database Specification; 21 Workflow State Machine; 23 API Contract Specification; 25 Security and Audit Specification |
| Supersedes | Không có |

## 1. Scope và format

| Format | MVP | Handling |
| --- | --- | --- |
| TXT | Có | Python open/read_text |
| Markdown | Có | Text đọc như plain text |
| DOCX | Có | zipfile + xml.etree.ElementTree |
| PDF text | Fallback | Paste extracted text hoặc approved pdftotext |
| PDF scan | Không | OCR ngoài MVP |
| DOC | Không | Reject binary legacy Word |
| DOCM | Không | Reject macro-enabled file |

MVP không tự xây PDF parser và không giả định Python Standard Library parse PDF đầy đủ.

## 2. Limits và canonicalization

- JSON request body tối đa 1 MiB.
- Upload HTTP body tối đa 10 MiB.
- Decoded binary file tối đa 7.5 MiB để còn base64/JSON overhead trong request limit.
- Extracted text tối đa 200,000 Unicode code points/document.
- Filename tối đa 255 code points trước normalize.
- Original filename chỉ là metadata hiển thị; không dùng làm directory key.
- Decode text ưu tiên UTF-8 BOM-aware; fallback UTF-8 strict rồi lỗi rõ.
- Normalize Unicode NFC.
- Normalize CRLF/CR thành LF.
- Loại bỏ NUL/control characters không cần thiết; giữ newline/tab.
- Trim trailing whitespace theo dòng và toàn text.
- SHA-256 file bytes nếu có file; SHA-256 canonical extracted text cho content_sha256.

## 3. Upload pipeline

~~~text
Receive JSON
→ Check Content-Length before body read
→ Parse metadata/base64
→ Validate documentType/sourceKind/extension/MIME/size
→ Decode bytes to temporary file under case staging root
→ Validate magic/signature
→ SHA-256
→ Extract text
→ Normalize and length-check text
→ Store immutable Document version and relative path
→ Mark extraction status
→ Audit event
~~~

Không gửi file trực tiếp tới AI. Chỉ extracted_text đã làm sạch và được HĐCM confirm mới có is_ai_eligible=1.

## 4. File validation

### Extension/MIME

Allowlist:

- .txt: text/plain hoặc user-supplied text mode.
- .md/.markdown: text/markdown hoặc text/plain.
- .docx: application/vnd.openxmlformats-officedocument.wordprocessingml.document.
- .pdf: application/pdf nhưng chỉ fallback/pdftotext.

Không tin MIME client đơn độc; phải kiểm tra extension, MIME hợp lý và signature.

### Magic/signature

- DOCX: ZIP signature PK và required entry [Content_Types].xml; reject nếu có vbaProject.bin.
- PDF: bắt đầu bằng %PDF-; vẫn không đảm bảo extract native.
- TXT/Markdown: không có magic tin cậy; giới hạn extension, decode và content.
- DOCM/DOC: reject trước extraction.

## 5. Storage path

Base:

~~~text
%LOCALAPPDATA%\ClawCV\documents\{case-id}\
~~~

Path format:

~~~text
documents/{case-id}/jd/v001/source-{document-id}.ext
documents/{case-id}/cv/v001/source-{document-id}.ext
~~~

Rules:

- case-id/document-id do application tạo UUID.
- Không dùng candidate name, original filename hoặc user path.
- Resolve final path và xác nhận nằm trong allowed root.
- File mới ghi vào temporary sibling rồi atomic replace vào generated path.
- Database lưu relative path.
- Khi tạo version mới, version cũ giữ nguyên; current pointer đổi trong transaction.
- Cleanup chỉ chạy khi explicit case deletion sau backup hoặc dọn staging file mồ côi có audit.

## 6. TXT/Markdown extraction

1. Đọc bytes từ staged file.
2. Decode UTF-8 BOM-aware.
3. Nếu decode fail, trả DOCUMENT_PARSE_FAILED và cho paste text.
4. Normalize NFC/newline/control characters.
5. Validate non-empty và max length.
6. Tính content_sha256.
7. Lưu extracted_text vào Document.

Markdown không render HTML trong pipeline; lưu text/markdown content và mọi frontend preview phải text-only.

## 7. DOCX extraction

Dùng zipfile.ZipFile và xml.etree.ElementTree:

1. Mở ZIP từ staged path với timeout/size guard.
2. Kiểm tra [Content_Types].xml và word/document.xml.
3. Reject nếu có vbaProject.bin hoặc extension DOCM.
4. Parse word/document.xml.
5. Thu thập text từ thẻ WordprocessingML w:t theo document order.
6. Chuyển paragraph/table text thành newline/tab ổn định.
7. Không thực thi relationship URL, embedded object, macro hoặc external resource.
8. Normalize/length-check/hash như text.

Malformed XML/ZIP trả parse failure, không retry vô hạn.

## 8. PDF handling

### Default MVP

- Reject native parse assumption.
- Cho HĐCM paste text đã extract từ hệ thống khác.
- Lưu source metadata nếu có file PDF nhưng extracted_text chỉ được confirm sau khi có text.

### Optional approved pdftotext

- Executable phải được đơn vị phê duyệt và đóng gói cùng pilot hoặc cấu hình absolute allowlisted path.
- Gọi bằng subprocess với shell=False, argument list, timeout và output size limit.
- Không nhận executable path từ user.
- Kiểm tra exit code và output encoding.
- Không OCR scan PDF trong core MVP.
- Nếu executable thiếu/lỗi, chuyển manual paste fallback.

## 9. Manual paste fallback

- UI gửi sourceKind MANUAL_TEXT và text field.
- Text đi qua cùng normalize, length-check và hash.
- original_filename/storage_path/file_sha256 có thể NULL.
- HĐCM phải xem và confirm text.
- Audit DOCUMENT_TEXT_CONFIRMED.

## 10. Versioning và cleanup

- Mỗi replace/import tạo Document version mới với supersedes_document_id.
- Một case chỉ có current JD và current CV.
- Document đã dùng làm AI input không sửa tại chỗ.
- Raw file giữ local cùng snapshot cho tới explicit case delete.
- Staging temp file cleanup khi success/failure; cleanup lỗi ghi audit/log safe.
- Case delete phải theo backup/path/security policy.

## 11. Error handling và retry

| Error | Status | Handling |
| --- | --- | --- |
| Body quá lớn | REQUEST_TOO_LARGE | Reject trước đọc body |
| Base64 invalid | VALIDATION_ERROR | Không lưu file |
| Extension/MIME/signature mismatch | VALIDATION_ERROR | Reject và audit |
| Unsupported DOC/DOCM | UNSUPPORTED_MEDIA_TYPE | Paste fallback |
| ZIP/XML malformed | DOCUMENT_PARSE_FAILED | Giữ error snapshot, cho replace/paste |
| PDF native unavailable | DOCUMENT_PARSE_FAILED | Paste hoặc approved pdftotext |
| Text empty/too long | DOCUMENT_PARSE_FAILED | Yêu cầu text khác |
| File write failure | INTERNAL_ERROR | Không tạo current pointer |
| Duplicate hash | 409/state rule | Có thể tạo reference mới nhưng không overwrite snapshot |

Parse không retry tự động nếu input không đổi. User replace file/text tạo version/fingerprint mới.

## 12. Audit event

- DOCUMENT_UPLOAD_REQUESTED.
- DOCUMENT_IMPORTED.
- DOCUMENT_PARSE_SUCCEEDED.
- DOCUMENT_PARSE_FAILED.
- DOCUMENT_TEXT_CONFIRMED.
- DOCUMENT_VERSION_CREATED.
- DOCUMENT_REJECTED_UNSUPPORTED.
- DOCUMENT_CLEANUP_FAILED.

Audit chỉ lưu case/document ID, format, size, hash prefix/full hash theo policy, status và error code; không lưu file/text.

## 13. Security consideration

- File content là untrusted.
- Không mở bằng Office.
- Không chạy macro/script.
- Chống ZIP bomb bằng compressed/uncompressed size guard.
- Chống path traversal bằng generated path + resolve-inside-root.
- Không log raw content.
- AI chỉ nhận sanitized extracted text.

## 14. Conflict / Assumption / Open Questions

### Conflict

- Context liệt kê PDF trong input; Technology không có PDF parser native. Tài liệu này hỗ trợ PDF metadata/fallback và pdftotext optional, không OCR.
- Technology upload body max 10 MiB; do base64 overhead, decoded binary limit thấp hơn để giữ body limit.

### Assumption

- Text limit 200,000 code points/document là giới hạn an toàn có thể cấu hình, không thay đổi scope.
- DOCX tables được flatten thành text theo thứ tự đọc.
- Duplicate content vẫn được lưu version nếu user chủ động import; không silently overwrite.

### Open Questions / Backlog

- Approved pdftotext binary/version/checksum.
- OCR hoặc PDF parser sau MVP.
- Multipart upload cho file lớn.
- Rich document layout preservation.

## 15. Acceptance criteria

1. TXT, Markdown và DOCX có extraction path rõ.
2. PDF limitation, paste fallback và optional pdftotext rõ.
3. Có size, MIME/extension/signature, filename, hash và path rule.
4. DOCX extraction dùng zipfile/XML, không dependency runtime.
5. Có Unicode normalization, text limit và empty text handling.
6. Có Document versioning/current pointer và cleanup.
7. Có error/retry behavior và audit events.
8. Không thực thi macro/script hoặc dùng filename làm path.
9. Không gửi raw file sang AI.
