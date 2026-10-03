# Phase 2 Supervised Interview Mini Tool — Agent Instructions

## Project scope

Đây là mini tool hỗ trợ HĐCM trong supervised interview assessment tại một máy Windows. MVP local-first, phục vụ tuần tự trên một máy, không phải recruitment platform tổng thể.

In scope:

- Job/Candidate/InterviewCase.
- Import và xử lý JD/CV.
- AI question generation.
- Committee review/approval.
- Candidate Mode assessment, autosave, submit.
- AI evaluation, Interview Brief, live interview notes.
- HĐCM Final Evaluation.
- Audit, backup/export và Windows portable packaging.

Out of scope:

- Recruitment posting, public candidate form, HR Review Phase 1.
- AMIS/Recruitment Core integration.
- Central server, multi-machine, enterprise account/SSO.
- Camera, microphone, biometric, realtime speech-to-text.
- Coding judge, vector database, RAG platform.
- AI automatic hiring decision.

## Specification priority

Đọc và tuân thủ theo thứ tự:

1. 17_phase2_supervised_interview_mini_tool_context_specification.md — business scope/actor/flow.
2. 18_phase2_supervised_interview_technology_specification.md — runtime/architecture/dependency.
3. 19_phase2_specification_document_set_plan.md — document governance/order.
4. 20_domain_and_database_specification.md — data/entity/schema.
5. 21_workflow_state_machine.md — state/transition/recovery.
6. 22_ai_assessment_specification.md — AI contract/rubric/schema.
7. 23_api_contract_specification.md — frontend/backend contract.
8. 24_frontend_ui_specification.md — route/screen/interaction.
9. 25_security_and_audit_specification.md — security/privacy/audit.
10. 26_document_processing_specification.md — file/extraction.
11. 27_test_and_acceptance_specification.md — verification/exit criteria.
12. 28_implementation_task_breakdown.md — implementation order.

Nếu hai specification mâu thuẫn, không sửa âm thầm. Ghi conflict và dừng implementation phần bị ảnh hưởng để xác định source of truth. README không override specification.

## Technology constraints

- Python 3.10+ Standard Library only at runtime.
- HTTP server: http.server.ThreadingHTTPServer.
- Host: 127.0.0.1; default port: 8787.
- Frontend: HTML5, CSS3, Vanilla JavaScript ES Modules.
- Frontend HTTP client: fetch().
- Database: SQLite, sqlite3, WAL, foreign_keys=ON, busy_timeout=5000.
- One SQLite connection per operation/thread; never share a global connection and never use check_same_thread=False.
- AI HTTP: urllib.request/urllib.error.
- Background work: threading and queue.Queue; one AI worker by default.
- JSON: json; IDs: uuid/secrets; time: datetime UTC ISO 8601.
- File/hash: pathlib/hashlib/shutil; DOCX: zipfile/xml.etree.ElementTree.
- Logging: logging and RotatingFileHandler with redaction.
- Backup: SQLite Connection.backup and zipfile.
- Deployment: portable bundle first; installer later.

Forbidden runtime dependencies:

- Flask, FastAPI, Django.
- SQLAlchemy or any ORM.
- Pydantic, Requests, aiohttp.
- Node.js/NPM/frontend frameworks.
- PostgreSQL/MySQL/MariaDB/Redis/Kafka/Docker.
- Native desktop framework.

Build-time packaging tools are allowed only when the client artifact remains self-contained and does not require the tool at runtime.

## Source structure

Follow the Technology Specification:

~~~text
main.py
app/
  config.py
  server.py
  router.py
  responses.py
  security.py
  database.py
  migrations.py
  repositories/
  services/
  ai/
  domain/
web/
migrations/
prompts/
schemas/
tests/
scripts/
~~~

## Layer rule

~~~text
HTTP Handler
→ Router/controller
→ Application service/domain rule
→ Repository or infrastructure adapter
→ SQLite/filesystem/AI provider
~~~

- HTTP handler không chứa SQL.
- Repository không chứa workflow orchestration.
- Service không phụ thuộc HTTP request/response.
- AI provider không tự đổi workflow state.
- Frontend không truy cập SQLite/filesystem.
- Business rule không hardcode trong UI.

## Domain and workflow rules

- InterviewCase là aggregate root.
- Một case có một AssessmentAttempt ở MVP.
- Default assessment: 8 questions, 900 seconds.
- Candidate được submit thiếu câu; answer chưa trả lời là NOT_ASSESSED.
- Hết giờ auto-submit.
- Answer đã submit/expired không được sửa.
- Không reopen attempt; trường hợp cần làm lại tạo case mới.
- AI chỉ hỗ trợ; HĐCM approve questions và finalize evaluation.
- AI rerun tạo task/result version mới, không overwrite.
- Final Evaluation FINAL cần Committee lead/finalizer và audit.
- Hard delete case cần SQLite backup, path validation và audit.

## Database and migration rules

- Migration SQL versioned trong migrations/; migration 001 phải khớp tài liệu 20.
- Mỗi migration chạy transaction; failure chặn startup bình thường.
- Không sửa migration đã áp dụng; tạo version mới.
- Viết parameterized SQL.
- Dùng UTC ISO 8601 TEXT.
- JSON TEXT phải validate tại application boundary.
- Foreign keys bật trên từng connection.
- Không dùng soft-delete tràn lan; chỉ dùng khi specification yêu cầu.

## Security and logging

- Chỉ bind localhost và validate Host header.
- Mutation yêu cầu startup token; Committee yêu cầu Committee session; Candidate yêu cầu candidate token.
- Candidate capability chỉ đọc questions, save answer, submit.
- Không tin frontend hide.
- Không render untrusted content bằng innerHTML/eval/new Function.
- Không lưu/log API key, PIN, startup token, session, candidate token.
- Không log full CV, JD, answer, live notes hoặc raw AI payload.
- AI chỉ nhận sanitized text, không raw file.
- File path luôn generated từ UUID và resolve-inside-root.
- Backup/export không chứa secret/token/PIN.

## Commands

Development run:

~~~text
python main.py
~~~

Backend tests:

~~~text
python -m unittest discover -s tests -v
~~~

Windows portable package:

~~~text
powershell -ExecutionPolicy Bypass -File scripts/package_windows.ps1
~~~

Commands are targets for the implementation batches; do not add a runtime package just to make a command work.

## Do-not-touch list

- Do not alter Context/Technology decisions to simplify code.
- Do not copy Phase 1 NestJS/PostgreSQL/Docker/auth/role architecture.
- Do not add ORM or third-party runtime package.
- Do not create server/public network listener.
- Do not send raw JD/CV/file/answer to AI provider.
- Do not overwrite submitted answers, approved Question Sets, completed AiResults or FINAL Evaluations.
- Do not let AI set PASS/FAIL or EVALUATED.
- Do not change state directly from frontend.
- Do not place user data in install directory.
- Do not commit real candidate data, secrets or provider credentials.

## Assumption and conflict handling

Allowed assumption only when:

- It does not change MVP scope or decision authority.
- It does not weaken candidate data security.
- It is reversible.
- It is written in the relevant specification/task.

For unresolved business, security, data retention, state transition or provider data policy, record an Open Question/Backlog and do not silently invent a behavior during implementation.

## Testing and definition of done

Before claiming a task complete:

1. Read the referenced specification and task.
2. Add/update tests for happy path, invalid input, failure and recovery.
3. Run the relevant unittest command.
4. Inspect diff/status and confirm only scoped files changed.
5. Verify no secret/PII/test fixture leak.
6. Report command, result, files and remaining risk.

A feature is done only when:

- State/DB/API/UI/security behavior matches its specification.
- Candidate isolation is tested.
- Audit event is present for required mutations.
- Failure/manual fallback is preserved.
- Migration/backup implications are handled.
- Tests pass with fresh evidence.

Do not mark a specification APPROVED or implementation complete merely because files exist.
