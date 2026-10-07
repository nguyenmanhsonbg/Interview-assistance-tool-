# 25. Phase 2 Supervised Interview Mini Tool — Security and Audit Specification

## Thông tin tài liệu

| Thuộc tính | Giá trị |
| --- | --- |
| Phiên bản | 1.0 |
| Trạng thái | DRAFT |
| Owner | Security reviewer + Product Owner |
| Last updated | 2026-10-04 |
| Depends on | 18 Technology Specification; 20 Domain and Database Specification; 21 Workflow State Machine; 22 AI Assessment Specification; 23 API Contract Specification; 24 Frontend UI Specification |
| Supersedes | Không có |

## 1. Security objectives

- Candidate chỉ truy cập Candidate API của một attempt.
- Committee API yêu cầu local session/PIN và startup token.
- Server chỉ bind localhost, không mở LAN/public listener.
- JD/CV/answer không bị gửi raw file tới AI.
- API key, PIN, session token và candidate token không xuất hiện trong log/frontend/database plain text.
- File path chống traversal và file upload không thực thi macro/script.
- Audit bảo toàn thao tác quan trọng, kể cả sau hard delete case.

MVP không bao gồm account doanh nghiệp, SSO, multi-machine authorization, camera, microphone, biometric hoặc proctoring tự động.

## 2. Trust boundary

~~~mermaid
flowchart LR
    C[Committee user] --> B[Browser localhost]
    A[Candidate] --> B
    B --> S[ThreadingHTTPServer 127.0.0.1:8787]
    S --> R[REST authorization/router]
    R --> D[Domain/Application services]
    D --> DB[(SQLite)]
    D --> FS[Local filesystem]
    D --> AI[Approved AI endpoint]
    A -. untrusted answer .-> B
    C -. untrusted document .-> B
~~~

Trust assumptions:

- Windows user account and NTFS permissions are the primary local boundary.
- Candidate is physically supervised at the interview location.
- Browser UI is not trusted for authorization.
- CV/JD/answer/live notes are untrusted content.
- AI provider is an external processor and must be configured/approved.

## 3. Localhost protection

- Bind exactly 127.0.0.1:8787.
- Reject production configuration 0.0.0.0, LAN address or public interface.
- Validate Host header against 127.0.0.1:8787 and localhost:8787.
- Reject unexpected Origin/Referer for mutation when present.
- Same-origin frontend/API; no wildcard CORS.
- Use Content-Security-Policy, X-Content-Type-Options, X-Frame-Options, Referrer-Policy and Cache-Control headers.
- Do not expose debug server, directory listing or stack trace.
- Acquire single-instance lock so two processes cannot write one database.

Required headers:

~~~text
Content-Security-Policy: default-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Referrer-Policy: no-referrer
Cache-Control: no-store
~~~

## 4. Startup/CSRF token

- Generate a cryptographically random startup token with secrets.token_urlsafe() at process start.
- Token rotates on every restart.
- Mutation API requires X-Startup-Token plus the relevant Committee/Candidate capability.
- Token is held in process memory and delivered only to same-origin frontend bootstrap.
- Never log, persist or include token in backup/export.
- Missing/invalid token returns UNAUTHENTICATED without revealing expected value.

The startup token is a CSRF defense for the local browser context; it is not an identity or authorization role.

## 5. Committee PIN and session

### Recommended MVP model

- One local Committee PIN protects Committee Mode.
- PIN is verified only on localhost through a mutation protected by startup token.
- Store a salted slow hash, not the PIN. Use Python Standard Library hashlib.pbkdf2_hmac with a random salt and explicit iteration count.
- Store hash/salt metadata in protected app configuration; never log or export it.
- Do not auto-fill or expose the PIN.
- Rate-limit failed attempts in memory and use increasing delay.
- Successful verification creates a short-lived Committee session with random session ID stored server-side in memory.
- Session expires on inactivity, explicit lock, or process restart.
- Session ID is sent in X-Committee-Session and never placed in URL/localStorage.
- Forgot PIN requires controlled local reset; Candidate cannot reset it.

Committee session is capability-based, not an enterprise account. Member attribution uses the case member ID selected by the Committee UI and is separately audited.

## 6. Candidate session token

- At Candidate Mode start, generate a random high-entropy token.
- Store only a one-way hash in assessment_attempts.candidate_token_hash.
- Send token to the Candidate tab/session through an ephemeral same-origin mechanism.
- Candidate token is scoped to one attempt and expires at attempt expiry/submission.
- Candidate token can only call:
  - GET attempt questions.
  - PUT one answer.
  - POST submit.
- Candidate token cannot enumerate case IDs, read documents, call tasks or use Committee endpoints.
- Invalid token returns generic UNAUTHENTICATED/RESOURCE_NOT_FOUND behavior without confirming resource existence.

## 7. Capability matrix

| Capability | Committee | Candidate | AI worker | System |
| --- | --- | --- | --- | --- |
| Create/edit case | Yes | No | No | Recovery only |
| Read candidate name/code | Yes | Own display only | Minimized code | Yes |
| Read JD/CV | Yes | No | Sanitized text only | Yes |
| Upload/confirm document | Yes | No | No | No |
| Generate/edit/approve questions | Yes | No | Generate only | Recovery |
| Read question text | Yes | Own attempt questions | Input reference | Yes |
| Read rubric/evidence | Yes | No | Input/output | Yes |
| Save answer | No | Own attempt only | No | Recovery only |
| Submit answer | Committee can force operational auto-submit only; Candidate submits own | Own attempt | No | Timer auto-submit |
| Read AI result/brief | Yes | No | Own task result | Yes |
| Write live record | Yes | No | Suggested questions only | No |
| Finalize evaluation | Lead/finalizer | No | No | No |
| Backup/export/delete | Yes with confirmation | No | No | System execution |
| Change settings | Authorized Committee | No | No | Startup/migration |

## 8. File upload and path security

- Validate JSON body size before reading body.
- Validate extension and MIME against allowlist.
- Validate magic/signature where available.
- Reject DOC, DOCM, executable, script, macro and archive content not required.
- Store generated filename under documents/{case-id}/{type}/version.
- Never concatenate user filename into a path.
- Resolve candidate path and verify it is inside allowed root.
- Use UUID/case ID as directory key.
- Do not open uploaded files with Office or execute subprocess except approved pdftotext adapter.
- Set file permissions using Windows ACL/NTFS policy where available.
- Delete only after backup and explicit case deletion confirmation.

## 9. Frontend output encoding

- Render AI/document/candidate text with textContent.
- Do not use innerHTML, eval, new Function or dynamic script injection.
- Escape values placed into attributes.
- Do not trust Markdown/HTML returned by AI.
- Avoid storing sensitive state in URL/query string.
- Disable browser caching for candidate pages and API responses.

## 10. AI data policy

Allowed provider payload:

- Cleaned JD/CV text required for question generation.
- Question Set snapshot and sanitized answer text required for evaluation.
- Interview Brief/live notes required for follow-up.
- Candidate code instead of name whenever possible.

Prohibited by default:

- Raw PDF/DOCX/file bytes.
- Local filesystem path.
- API key/PIN/session/candidate token.
- Email, phone, address or image unless a separately approved use case requires it.
- Instructions embedded in documents treated as system instructions.

If remote processing is not approved, configure internal gateway/local endpoint or use manual fallback. Provider, model, prompt version, schema version and data policy are stored in AiTask/AiResult metadata.

## 11. PII lifecycle and deletion

- Retention mode is MANUAL_ONLY; no automatic expiry deletion.
- Candidate full name and documents remain local until explicit deletion.
- Deletion requires Committee/HR capability, confirmation, backup and audit.
- Case-owned rows/files hard-delete; AuditLog remains because it has no FK.
- Shared Candidate/Job is not cascaded while referenced by another case.
- Existing backup/export ZIP is not automatically scrubbed; operator must delete it separately when required.
- Manual paste text is treated as candidate data just like imported CV.

## 12. Secret and backup protection

- API key stored through Windows DPAPI via ctypes or development environment variable.
- Do not store API key in app_settings.value_text, JavaScript, prompt files or logs.
- Backup directory is under local data root with restricted NTFS access.
- Export package excludes API key, PIN, tokens and protected secret blobs.
- Display only safe path summary and hash manifest.
- Before migration/delete/large import, create backup with SQLite Backup API.

## 13. Logging and redaction

### Allowed fields

- UTC timestamp, level, requestId/taskId, module/action, method/route, duration, status/error code, provider status.

### Never log

- API key, PIN, password, startup token, Committee session, candidate token.
- Full CV, JD, answer, live notes or raw AI payload.
- Protected settings or filesystem absolute paths containing sensitive names.

Use RotatingFileHandler with size and backup-count limits. Log user-facing safe message separately from raw exception; raw exception is not returned to client.

## 14. Audit record and event catalog

Audit row follows 20 Domain:

- id.
- actor_type and optional actor_ref_id.
- action.
- entity_type/entity_id.
- request_id.
- metadata_json redacted.
- created_at UTC.

Required actions:

- CASE_CREATED, CASE_UPDATED, CASE_CANCELLED, CASE_DELETED.
- DOCUMENT_IMPORTED, DOCUMENT_TEXT_CONFIRMED, DOCUMENT_VERSION_CREATED.
- QUESTION_SET_GENERATION_REQUESTED, QUESTION_SET_GENERATED, QUESTION_SET_EDITED, QUESTION_SET_APPROVED.
- ASSESSMENT_CREATED, ASSESSMENT_STARTED, ASSESSMENT_RESUMED, ANSWER_AUTOSAVED, ASSESSMENT_SUBMITTED, ASSESSMENT_AUTO_SUBMITTED, ASSESSMENT_EXPIRED.
- CANDIDATE_MODE_ENTERED, COMMITTEE_MODE_ENTERED, CANDIDATE_NO_SHOW.
- AI_TASK_CREATED, AI_TASK_RETRIED, AI_TASK_COMPLETED, AI_TASK_FAILED, AI_RESULT_RERUN.
- INTERVIEW_BRIEF_CREATED, MANUAL_FALLBACK_USED.
- LIVE_INTERVIEW_STARTED, LIVE_QUESTION_RECORDED, LIVE_QUESTION_SKIPPED, CONFLICT_FLAGGED, LIVE_INTERVIEW_COMPLETED.
- EVALUATION_DRAFTED, EVALUATION_FINALIZED, EVALUATION_REVISED.
- SETTINGS_UPDATED, BACKUP_CREATED, EXPORT_CREATED, CASE_DELETE_REQUESTED, CASE_DELETE_COMPLETED, CASE_DELETE_FAILED.

Audit events are append-only. Any repair/admin operation must create a new audit event.

## 15. Security error response

Return the standard API error envelope with safe code/message:

- Invalid session/token: UNAUTHENTICATED.
- Wrong capability: FORBIDDEN_CAPABILITY.
- Resource outside candidate scope: RESOURCE_NOT_FOUND or generic forbidden behavior.
- Unsafe upload: VALIDATION_ERROR or UNSUPPORTED_MEDIA_TYPE.
- Path/delete safety failure: INTERNAL_ERROR to user plus detailed redacted local log/audit.

Never disclose whether another candidate/case exists to Candidate Mode.

## 16. Threats and mitigations

| Threat | Mitigation |
| --- | --- |
| Other local process calls API | Host validation, startup token, session/candidate capability, localhost boundary |
| Candidate invokes Committee endpoint | Backend capability check, not frontend hiding |
| XSS through AI/CV/answer | textContent, CSP, no raw HTML |
| Path traversal | UUID directory, resolve-inside-root check, generated filename |
| Malicious DOCM/macro | Reject DOCM, never open Office, magic/extension validation |
| Prompt injection | Delimiters, untrusted labels, output schema validation |
| Secret leakage | DPAPI, redacted logs/exports, no frontend secret |
| Data loss during AI failure | Answers local first, AI result optional, manual fallback |
| Data loss during crash | SQLite transaction/WAL, autosave, restart recovery |
| Accidental delete | Confirmation, backup required, audit, explicit path check |
| Backup exfiltration | Local permissions, protected handling, no secrets in package |
| Brute-force PIN | Rate limit, delay, session expiry |

## 17. Conflict / Assumption / Open Questions

### Conflict

- Context mentions one local PIN while Technology mentions startup/CSRF token and candidate token. These are separate controls: PIN/session for Committee, startup token for mutation/CSRF, candidate token for Candidate scope.
- Local-first does not mean unprotected; NTFS, DPAPI and session boundaries remain required.

### Assumption

- One Committee PIN is sufficient for MVP; per-member accounts are backlog.
- Physical supervision is the primary anti-cheat control; fullscreen/copy events are signals only.
- Audit metadata contains IDs/counts, not full PII.

### Open Questions / Backlog

- Windows credential/enterprise secret vault integration.
- SSO and per-user authorization.
- Security review/penetration test for production pilot.
- Formal retention/legal policy for old backup packages.

## 0A. Offline package trust boundary

The approved topology is:

```text
Machine B: Committee browser -> localhost API/SQLite/filesystem
Machine A: candidate opens generated HTML file -> local browser only
Transfer: Question Package HTML B -> A; Response Package HTML A -> B
```

Machine A is not a second API client and does not receive the server startup token, Committee session, candidate token, API key, JD/CV, rubric, or internal evidence. The generated package contains candidate-safe question text and a minimal manifest only. The response is treated as untrusted input at import; the parser reads the inert JSON payload and does not render imported HTML as application markup.

The accepted MVP threat model is protection against ordinary operational mistakes: wrong file, wrong case, draft file, malformed file, duplicate import, and accidental re-import. Deliberate modification of a local HTML file by a determined actor is out of scope for this supervised local MVP; case-owned Question Set ID/version/fingerprint, exact question projection, source hash, idempotency, audit, and immutable snapshot versioning still prevent silent mixing during normal operation.

## 18. Acceptance criteria

1. Trust boundary and threat model are explicit.
2. Localhost, Host header, startup token and security headers are defined.
3. Committee PIN/session and candidate token are defined without Phase 1 auth reuse.
4. Capability matrix isolates Candidate/Committee/System.
5. Upload/path/XSS/prompt-injection controls are defined.
6. AI data minimization and PII lifecycle are defined.
7. Secrets and backup handling are defined.
8. Logs are redacted and AuditLog schema/events are complete.
9. Security errors do not leak sensitive existence or implementation details.
10. Conflicts, assumptions, backlog and requirement IDs are present.
