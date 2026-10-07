# Offline HTML Candidate Package Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline two-machine candidate assessment flow where machine B exports a self-contained HTML question package, machine A produces a response HTML file, and machine B imports it into an immutable Answer Snapshot for AI evaluation.

**Architecture:** Keep machine B as the only server, SQLite owner, AI worker, and Committee UI. Add a pure Standard Library HTML package codec, a dedicated application service for export/import, and Committee-only binary endpoints. The existing Excel flow remains available as a fallback, but both sources use the same normalized Answer Snapshot and AI evaluation contract.

**Tech Stack:** Python 3.10+ Standard Library, `html.parser`, `html.escape`, `json`, `hashlib`, `uuid`, `datetime`, `http.server`, SQLite, HTML5/CSS3/Vanilla JavaScript ES Modules.

**Spec:** [HTML Candidate Package Flow Design](../specs/2026-10-07-html-candidate-package-flow-design.md)

## Global Constraints

- Runtime remains Python 3.10+ Standard Library only; do not add Flask, FastAPI, ORM, Pydantic, Requests, Node.js, or frontend frameworks.
- Machine B remains bound to `127.0.0.1`; do not open a LAN/public listener or add multi-machine authorization.
- Machine A receives a self-contained HTML file with no external resources, no network calls, and no secret.
- SQLite uses one connection per operation/thread, WAL, foreign keys, and parameterized SQL.
- Candidate package and response payloads are untrusted data; import never executes or renders received HTML as active DOM.
- JD, CV, rubric, expected evidence, API key, PIN, startup token, Committee session, and candidate token must not be embedded in HTML packages or logs.
- Answer Snapshot and completed AI results are immutable; changed input creates a new version and never overwrites a completed result.
- Blank answers become `NOT_ASSESSED`; the system does not infer a negative answer from an empty field.
- Browser persistence is not required for correctness; draft recovery uses an explicit downloaded draft HTML file.
- Existing user changes in `documents/30_interview_workspace_ui_implementation_specification.md`, `tests/test_frontend_contract.py`, `web/css/layout.css`, and `web/js/app.js` must be preserved and reconciled rather than reset.

## Review Focus

- HTML opened with `file://` must work without ES module imports, CDN assets, or a running server; pin this in `tests/test_html_candidate_package.py`.
- Question/answer text containing HTML, script, or JSON-breaking characters must remain plain text and cannot escape the embedded payload; pin this in `tests/test_html_candidate_package.py`.
- A response for the wrong case, package, Question Set, version, or fingerprint must be rejected without changing current snapshot/result; pin this in `tests/test_html_candidate_service.py`.
- A draft must restore answers but must not be importable as a submitted response; pin this in `tests/test_html_candidate_package.py` and service tests.
- Generalizing provenance from Excel to HTML must not break existing Excel snapshots or AI evaluation manifests; pin this in repository, Excel, and refined evaluation regression tests.

## File and Component Map

### New files

- `migrations/004_html_candidate_package_flow.sql` — adds canonical assessment input provenance for `HTML_IMPORT`, package ID, and generic source-file hash while preserving legacy Excel columns/data.
- `migrations/005_allow_multiple_candidate_responses.sql` — removes package-ID uniqueness so a changed response from the same exported package can create a new immutable snapshot version.
- `app/infrastructure/html_candidate_package.py` — validates, renders, and parses `candidate-html.v1` question/draft/response packages; owns no database or workflow state.
- `app/services/html_candidate_package_service.py` — exports approved Question Sets and imports validated response packages into snapshots; owns audit and case refined-flow transitions.
- `tests/test_html_candidate_package.py` — codec, HTML safety, file://-compatible bundle, draft, response, and malformed-payload tests.
- `tests/test_html_candidate_package_service.py` — service export/import, provenance, idempotency, mismatch, and recovery tests.

### Modified files

- `app/repositories/assessment_snapshots.py` — store/read canonical source kind, package ID, source-file hash, and maintain the legacy `workbookSha256` response field for existing consumers until the API contract is migrated.
- `app/services/excel_assessment_service.py` — pass `EXCEL_IMPORT` explicitly through the generalized provenance fields and keep Excel fallback behavior unchanged.
- `app/services/evaluation_service.py` — use canonical `sourceFileSha256`/`packageId` in the evaluation manifest while accepting the legacy workbook alias for old snapshots.
- `app/api.py` — register Committee-only HTML export/import endpoints and delegate to `HtmlCandidatePackageService`.
- `web/js/app.js` — make HTML candidate package export/import the primary Committee flow, retain Excel as fallback, and update labels, file filters, size checks, and next-step navigation.
- `web/css/layout.css` — add only the small layout rules needed for package transfer instructions, validation status, and source badges.
- `tests/test_migrations.py`, `tests/test_excel_snapshot_repository.py`, `tests/test_excel_assessment_service.py`, `tests/test_refined_evaluation.py` — assert migration 004 and Excel backward compatibility.
- `tests/test_api_e2e.py`, `tests/test_frontend_contract.py` — cover new endpoints and active HTML UI contracts while preserving fallback coverage.
- `documents/30_interview_workspace_ui_implementation_specification.md` — reconcile the active flow from Excel-primary to HTML-primary with Excel fallback after code/API behavior is verified.
- `documents/23_api_contract_specification.md`, `documents/24_frontend_ui_specification.md`, `documents/25_security_and_audit_specification.md`, `documents/27_test_and_acceptance_specification.md` — record the implemented package format, endpoint behavior, security model, and acceptance criteria.

### Existing code that must not be copied into the new codec

- `app/infrastructure/excel_question_answer.py` remains the Excel adapter and is not modified to parse HTML.
- `app/services/assessment_service.py` remains the server-side Candidate Mode implementation and is not reused for offline browser autosave.
- `web/js/store.js` must not be used to persist candidate answers or tokens for the offline HTML file.

## Implementation Tasks

### Task 1: Add canonical assessment input provenance without breaking Excel

**Files:**
- Create: `migrations/004_html_candidate_package_flow.sql`
- Modify: `app/repositories/assessment_snapshots.py`
- Modify: `app/services/excel_assessment_service.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_excel_snapshot_repository.py`
- Modify: `tests/test_excel_assessment_service.py`

**Interfaces:**
- Repository method becomes:
  `create_imported_snapshot(connection, *, case_id: str, question_set_id: str, source_kind: str, source_file_sha256: str, package_id: str | None, normalized_fingerprint: str, idempotency_key_hash: str, document_manifest: list[dict[str, Any]], questions: Sequence[dict[str, Any]], answers: Sequence[dict[str, Any]]) -> dict[str, Any]`.
- Repository output adds `sourceKind`, `sourceFileSha256`, and `packageId`; retain `workbookSha256` as a compatibility alias for existing Excel/evaluation consumers during this migration.
- Excel import calls the generalized method with `source_kind="EXCEL_IMPORT"`, `package_id=None`, and the workbook SHA-256 as `source_file_sha256`.

- [ ] **Step 1: Write failing migration and repository tests**

  Add assertions that migration versions are `[1, 2, 3, 4]`, existing Excel rows still load as `EXCEL_IMPORT`, a new snapshot can use `HTML_IMPORT`, `packageId` is returned, and the generic source hash is available without exposing raw content.

- [ ] **Step 2: Run focused tests to verify failure**

  Run: `python -m unittest tests.test_migrations tests.test_excel_snapshot_repository tests.test_excel_assessment_service -v`

  Expected: FAIL because migration 004 and the new provenance fields do not exist.

- [ ] **Step 3: Implement migration 004**

  Add an `assessment_input_source` column with allowed values `EXCEL_IMPORT` and `HTML_IMPORT`, add nullable `package_id`, add `source_file_sha256`, backfill it from the legacy `workbook_sha256`, and add a partial unique index for non-null package IDs. Keep the old `source_kind` and `workbook_sha256` columns/data intact for backward compatibility; the new column is the canonical API source marker.

- [ ] **Step 4: Implement repository provenance fields**

  Update `AssessmentSnapshotRepository.create_imported_snapshot`, `_read`, and payload output to write/read the canonical fields, validate source kind and 64-character SHA-256 values at the application boundary, and return the legacy aliases required by current evaluation code.

- [ ] **Step 5: Route Excel through the generalized repository contract**

  Update `ExcelAssessmentService.import_answers` to compare the generic source hash, pass `EXCEL_IMPORT`, and preserve current Excel idempotency, versioning, audit action, and `NOT_ASSESSED` behavior.

- [ ] **Step 6: Run focused tests to verify pass**

  Run: `python -m unittest tests.test_migrations tests.test_excel_snapshot_repository tests.test_excel_assessment_service -v`

  Expected: PASS, including all existing Excel snapshot behavior.

- [ ] **Step 7: Commit**

  ```text
  git add migrations/004_html_candidate_package_flow.sql app/repositories/assessment_snapshots.py app/services/excel_assessment_service.py tests/test_migrations.py tests/test_excel_snapshot_repository.py tests/test_excel_assessment_service.py
  git commit -m "feat: add assessment package provenance"
  ```

### Task 2: Implement the self-contained HTML package codec and candidate runtime

**Files:**
- Create: `app/infrastructure/html_candidate_package.py`
- Create: `tests/test_html_candidate_package.py`

**Interfaces:**
- Constants: `HTML_PACKAGE_FORMAT_VERSION = "candidate-html.v1"`, `HTML_CONTENT_TYPE = "text/html; charset=utf-8"`, and `MAX_HTML_PACKAGE_BYTES = 10 * 1024 * 1024`.
- Dataclass: `CandidateHtmlPackage(package_type: str, manifest: dict[str, Any], questions: list[dict[str, Any]], answers: list[dict[str, Any]], package_sha256: str)`.
- Export function: `export_question_package(manifest: Mapping[str, Any], questions: Sequence[Mapping[str, Any]]) -> bytes`.
- Parse function: `import_candidate_package(raw: bytes) -> CandidateHtmlPackage`.
- The generated browser runtime must expose `Start`, `Save draft`, `Resume draft`, and `Submit` behavior through inline classic JavaScript only; it must download draft/response HTML files with `Blob` and `URL.createObjectURL` and never call a server.

- [ ] **Step 1: Write failing codec tests**

  Add tests for a question export that parses back with identical manifest/questions, no external URLs/imports, no secrets or JD/CV/rubric fields, HTML/script characters rendered safely, draft payload restoration, response payload creation, blank-answer normalization, and rejection of missing marker, wrong format, duplicate questions, missing questions, invalid answer flags, oversized input, and unsupported package type.

- [ ] **Step 2: Run codec tests to verify failure**

  Run: `python -m unittest tests.test_html_candidate_package -v`

  Expected: FAIL because the codec module and package format do not exist.

- [ ] **Step 3: Implement strict payload validation**

  Parse only the exact inert JSON element ID/type with `html.parser`; reject multiple payloads, missing payloads, wrong `formatVersion`, unknown package types, invalid manifest types, duplicate question IDs/orders, answer rows for unknown questions, inconsistent `isAnswered`, and over-limit text. Use dynamic question count from the input list; do not hardcode a visible count in the generated UI.

- [ ] **Step 4: Implement safe self-contained HTML rendering**

  Escape visible question text with `html.escape`, serialize payload JSON with `<`, `>`, `&`, and U+2028/U+2029 protected for script embedding, and render candidate-facing values with `textContent`/DOM text nodes. Include only candidate-safe question fields. Do not include external assets, module imports, raw JD/CV, rubric, expected evidence, or secrets.

- [ ] **Step 5: Implement draft and response browser actions**

  Keep answer state in memory, offer explicit draft download that preserves package identity and answer state, restore drafts when opened, and on submit show the answered count, make the view read-only, and download a response package without clearing state if the download is retried.

- [ ] **Step 6: Run codec tests to verify pass**

  Run: `python -m unittest tests.test_html_candidate_package -v`

  Expected: PASS with no external network/resource dependency in the generated HTML.

- [ ] **Step 7: Commit**

  ```text
  git add app/infrastructure/html_candidate_package.py tests/test_html_candidate_package.py
  git commit -m "feat: add offline HTML candidate package codec"
  ```

### Task 3: Add export/import application service for HTML packages

**Files:**
- Create: `app/services/html_candidate_package_service.py`
- Create: `tests/test_html_candidate_package_service.py`
- Create: `migrations/005_allow_multiple_candidate_responses.sql`
- Modify: `app/repositories/assessment_snapshots.py` if Task 1 exposes a missing shared helper

**Interfaces:**
- Dataclass: `ExportedCandidatePackage(content: bytes, filename: str, content_type: str, package_id: str, question_set_id: str)`.
- Service constructor: `HtmlCandidatePackageService(database: Database)`.
- Export method: `export_question_package(case_id: str) -> ExportedCandidatePackage`.
- Import method: `import_response(case_id: str, raw: bytes, *, idempotency_key: str) -> dict[str, Any]`.
- Read methods: `get_snapshot(case_id: str, snapshot_id: str | None = None) -> dict[str, Any]` and `snapshot_manifest(snapshot_id: str) -> dict[str, Any]` may delegate to the shared snapshot repository/service so Excel and HTML expose the same response shape.

- [ ] **Step 1: Write failing service tests**

  Cover approved Question Set export, generated package ID and filename, `QUESTIONS_EXPORTED` transition and audit, package with only candidate-safe fields, successful response import as `HTML_IMPORT`, package/source provenance, `ANSWERS_IMPORTED`, immutable snapshot, blank answer `NOT_ASSESSED`, idempotent replay, changed response versioning, wrong package/Question Set/version/fingerprint rejection, draft rejection, malformed HTML rejection, and preservation of an existing snapshot after failure.

- [ ] **Step 2: Run service tests to verify failure**

  Run: `python -m unittest tests.test_html_candidate_package_service -v`

  Expected: FAIL because the service and HTML provenance path do not exist.

- [ ] **Step 3: Implement export**

  Load the current Question Set, require `GENERATED` or `APPROVED` according to the existing export policy, generate a UUID package ID, build an opaque manifest with question-set fingerprint/duration/count, project only candidate-safe fields, call the codec, and in one transaction set `refined_flow_status='QUESTIONS_EXPORTED'` and append `QUESTION_SET_EXPORTED` audit metadata without answer text.

- [ ] **Step 4: Implement response import**

  Hash the raw response file, validate idempotency, parse the codec, match package ID/question-set ID/version/fingerprint against the server Question Set, normalize answer rows, compute answer hashes and normalized fingerprint, create an `HTML_IMPORT` snapshot, set `ANSWERS_IMPORTED`, and append `ASSESSMENT_ANSWERS_IMPORTED` audit metadata with counts only.

- [ ] **Step 5: Preserve Excel and evaluation snapshot access**

  Ensure the HTML service and Excel service use the same snapshot read shape and status mapping. Do not reuse server-side Candidate Mode start/save/submit routes, and do not allow the HTML service to mutate the approved Question Set.

- [ ] **Step 6: Run service tests to verify pass**

  Run: `python -m unittest tests.test_html_candidate_package_service tests.test_excel_assessment_service tests.test_refined_evaluation -v`

  Expected: PASS for HTML and existing Excel/refined evaluation flows.

- [ ] **Step 7: Commit**

  ```text
  git add app/services/html_candidate_package_service.py app/repositories/assessment_snapshots.py tests/test_html_candidate_package_service.py
  git commit -m "feat: add HTML candidate package service"
  ```

### Task 4: Wire Committee-only API endpoints and generic evaluation provenance

**Files:**
- Modify: `app/api.py`
- Modify: `app/services/evaluation_service.py`
- Modify: `tests/test_api_e2e.py`
- Modify: `tests/test_refined_evaluation.py`

**Interfaces:**
- New route: `POST /api/v1/interview-cases/{case_id}/candidate-package/export`, `body_mode="none"`, Committee access, binary `text/html; charset=utf-8` response.
- New route: `POST /api/v1/interview-cases/{case_id}/candidate-package/import`, binary body, Committee access, max body `10 * 1024 * 1024`, JSON snapshot response.
- New controller methods: `export_candidate_package(request: Request) -> Response` and `import_candidate_package(request: Request) -> Response`.
- `EvaluationService._snapshot_manifest` emits `sourceFileSha256`, `packageId`, and `sourceKind`; `_snapshot_provider_payload` validates the canonical source hash and still reads legacy `workbookSha256` when processing old snapshots.

- [ ] **Step 1: Write failing API and provenance tests**

  Add end-to-end export/import through the new endpoints, assert content disposition and MIME type, assert Committee auth/startup-token enforcement, assert wrong/malformed uploads return safe errors, and assert an HTML-imported snapshot can queue and complete `answer-evaluation.v2` without raw HTML or package bytes in the AI payload.

- [ ] **Step 2: Run focused API tests to verify failure**

  Run: `python -m unittest tests.test_api_e2e tests.test_refined_evaluation -v`

  Expected: FAIL because routes and canonical evaluation manifest fields do not exist.

- [ ] **Step 3: Register service and routes**

  Instantiate `HtmlCandidatePackageService` in `APIController`, register both routes with the existing Committee access policy, use the existing startup/idempotency header helpers, return binary HTML with safe `Content-Disposition`, and return the normalized snapshot envelope on import.

- [ ] **Step 4: Update evaluation provenance**

  Change only the snapshot provenance manifest and matching guard; keep the AI payload limited to sanitized JD/CV/question/answer text and preserve existing snapshot/document hash checks, retry behavior, and no-hiring-decision contract.

- [ ] **Step 5: Run focused API tests to verify pass**

  Run: `python -m unittest tests.test_api_e2e tests.test_refined_evaluation tests.test_ai_redaction tests.test_security -v`

  Expected: PASS, including candidate-data redaction and Committee authorization.

- [ ] **Step 6: Commit**

  ```text
  git add app/api.py app/services/evaluation_service.py tests/test_api_e2e.py tests/test_refined_evaluation.py
  git commit -m "feat: expose HTML candidate package API"
  ```

### Task 5: Make HTML transfer the primary Committee UI flow and keep Excel fallback

**Files:**
- Modify: `web/js/app.js`
- Modify: `web/css/layout.css`
- Modify: `tests/test_frontend_contract.py`

**Interfaces:**
- Questions screen primary CTA calls `POST /api/v1/interview-cases/{caseId}/candidate-package/export` through `apiDownload` and downloads the filename from `Content-Disposition`.
- Answers screen primary upload accepts `.html`, calls `POST /api/v1/interview-cases/{caseId}/candidate-package/import` with `Content-Type: text/html` and an idempotency key, then refetches the snapshot.
- Excel export/import remains an explicitly labeled fallback action and continues to use the current endpoints.

- [ ] **Step 1: Write failing frontend contract tests**

  Assert the built frontend references the new candidate-package export/import endpoints, labels the primary actions for HTML, retains the Excel fallback route, accepts `.html`, keeps safe text rendering, and does not add Candidate Mode routes to the Committee navigation.

- [ ] **Step 2: Run frontend contract tests to verify failure**

  Run: `python -m unittest tests.test_frontend_contract -v`

  Expected: FAIL because the current UI only exposes Excel as the primary action.

- [ ] **Step 3: Update questions and answers UI**

  Change the primary CTA/copy, add transfer instructions and source badges, use dynamic question/snapshot counts, add HTML file validation and 10 MB limit, preserve current immutable snapshot display, and keep the current Excel upload as a secondary fallback without duplicating state logic.

- [ ] **Step 4: Add focused layout styling**

  Add styles for transfer instruction panels, file-status/error text, and primary/secondary package actions without changing the established shell, typography, or security rendering rules.

- [ ] **Step 5: Run frontend contract tests to verify pass**

  Run: `python -m unittest tests.test_frontend_contract -v`

  Expected: PASS with no API key, token, answer text, or raw AI payload introduced into persistent browser state or URLs.

- [ ] **Step 6: Commit**

  ```text
  git add web/js/app.js web/css/layout.css tests/test_frontend_contract.py
  git commit -m "feat: make HTML candidate transfer primary in Committee UI"
  ```

### Task 6: Reconcile written specifications and operator-facing behavior

**Files:**
- Modify: `documents/30_interview_workspace_ui_implementation_specification.md`
- Modify: `documents/23_api_contract_specification.md`
- Modify: `documents/24_frontend_ui_specification.md`
- Modify: `documents/25_security_and_audit_specification.md`
- Modify: `documents/27_test_and_acceptance_specification.md`
- Modify: `documents/28_implementation_task_breakdown.md`

**Interfaces:**
- Documentation must name HTML package export/import as the primary offline flow, retain Excel as fallback, and point to the approved design and implemented endpoint names.
- Documentation must state that machine B remains localhost-only and machine A is an offline file consumer, not a second server or database client.

- [ ] **Step 1: Update the active UI/API/security/test documents**

  Replace statements that make Excel the only active assessment bridge, add the exact package contract and error semantics, record the accepted non-adversarial threat model, and add the acceptance criteria from the design.

- [ ] **Step 2: Reconcile implementation task breakdown**

  Add the HTML package tasks after Question Set approval and before AI evaluation; mark server-side Candidate Mode as a separate historical/alternative capability rather than silently mixing its token/autosave assumptions into offline HTML.

- [ ] **Step 3: Run documentation consistency scans**

  Run: `rg -n "Excel|Candidate Mode|HTML|candidate-html.v1|candidate-package|127.0.0.1|HTML_IMPORT" documents/23_api_contract_specification.md documents/24_frontend_ui_specification.md documents/25_security_and_audit_specification.md documents/27_test_and_acceptance_specification.md documents/28_implementation_task_breakdown.md documents/30_interview_workspace_ui_implementation_specification.md`

  Expected: no statement claims that HTML requires LAN access, no statement exposes secrets to machine A, and active-flow wording is internally consistent.

- [ ] **Step 4: Commit**

  ```text
  git add documents/23_api_contract_specification.md documents/24_frontend_ui_specification.md documents/25_security_and_audit_specification.md documents/27_test_and_acceptance_specification.md documents/28_implementation_task_breakdown.md documents/30_interview_workspace_ui_implementation_specification.md
  git commit -m "docs: reconcile offline HTML assessment flow"
  ```

### Task 7: Full verification and handoff

**Files:**
- Test/inspect: all files changed by Tasks 1–6
- No new runtime dependency or generated candidate data

- [ ] **Step 1: Run the complete backend test suite**

  Run: `python -m unittest discover -s tests -v`

  Expected: PASS with fresh evidence for migrations, Excel fallback, HTML codec/service/API, security, redaction, AI evaluation, and frontend contract checks.

- [ ] **Step 2: Run repository hygiene checks**

  Run: `git diff --check` and `git status --short`.

  Expected: no whitespace errors; only scoped implementation/documentation changes are present; pre-existing user modifications are not reverted or included in unrelated commits.

- [ ] **Step 3: Perform manual package smoke test**

  Start the app with `python main.py`, create/approve a test Question Set, export HTML from the Committee UI, open the downloaded file directly with the supported Windows browser, save a draft, reopen the draft, submit, import the response on machine B, and queue AI evaluation with a fake provider.

  Expected: no network request from machine A, response imports as `HTML_IMPORT`, answer count/status is correct, AI receives sanitized snapshot data only, and the original Question Set remains unchanged.

- [ ] **Step 4: Inspect sensitive-data output**

  Search generated HTML, logs, frontend persistent storage, and test fixtures for API keys, PINs, tokens, raw JD/CV, and unintended full-answer logging.

  Expected: no secret or test PII leak; response HTML contains only the intended candidate package/answer data.

- [ ] **Step 5: Commit verification/handoff notes**

  Add only if the repository convention requires a release/readiness note; otherwise report commands, results, changed files, and remaining operational risk without creating a new artifact.
