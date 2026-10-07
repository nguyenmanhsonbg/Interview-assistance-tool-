# HTML Candidate Package Flow Design

**Status:** Draft for written review
**Date:** 2026-10-07
**Scope:** Offline candidate assessment between two Windows machines
**Decision basis:** User confirmed that the MVP needs protection against ordinary operational mistakes, not deliberate candidate tampering.

## 1. Summary

The candidate assessment will use a self-contained HTML package instead of a LAN Candidate Mode or a shared Excel workbook as the primary flow.

- Committee uses the existing tool on machine B.
- Machine B exports an immutable question package as one HTML file.
- Candidate receives the HTML file on machine A, opens it locally, and answers in the browser.
- Candidate submits the package and downloads a response HTML file.
- Committee transfers the response file back to machine B and imports it.
- Backend B validates the package, creates an immutable Answer Snapshot, and uses that snapshot for AI evaluation.

The flow does not open a network listener, does not share SQLite between machines, and does not send candidate answers directly from machine A to an AI provider.

## 2. Context and source-of-truth decision

The repository currently contains two competing assessment directions:

1. The baseline workflow documents describe a browser Candidate Mode with server-side autosave, candidate token, timer, and submit.
2. The active UI implementation specification and the 2026-10-05 refined flow use Excel export/import and explicitly remove Candidate Mode from the active navigation.

This design selects a third, offline-compatible variant for the candidate collection step:

```text
Approved Question Set
    -> HTML Question Package
    -> HTML Response Package
    -> Immutable Answer Snapshot
    -> AI Evaluation
```

This is not the LAN Candidate Mode. The technology constraints remain local-first and localhost-only on machine B. The HTML package is a file exchange format and does not require machine A to connect to machine B.

The existing Excel flow may remain as a fallback while the HTML flow is introduced, but the two flows must produce the same normalized Answer Snapshot semantics before evaluation.

## 3. Goals

- Allow the candidate to work on machine A while the Committee keeps the tool and database on machine B.
- Avoid LAN configuration, firewall changes, CORS, TLS deployment, and multi-machine authorization for MVP.
- Give the candidate a better input experience than editing an Excel workbook.
- Prevent ordinary mistakes such as using the wrong question file, importing a response for another case, losing a submitted file, or importing an already processed file twice.
- Preserve the current AI contract: JD, CV, approved questions, and answer text are evaluated on machine B.
- Keep candidate answers, package metadata, and audit records versioned and traceable.

## 4. Non-goals

- Cryptographic proof that a candidate did not modify the response file.
- Server-authoritative timer enforcement while machine A is offline.
- Camera, microphone, recording, speech-to-text, proctoring, or biometric checks.
- Candidate access to JD, CV, rubric, expected evidence, AI output, or Committee data.
- Shared SQLite files, network database access, or synchronization between two database copies.
- Sending an HTML file, raw workbook, or raw answer package to the AI provider.

## 5. Actors and operating assumptions

### 5.1. Committee on machine B

The Committee or coordinator:

- reviews and approves the Question Set;
- exports the HTML Question Package;
- transfers the file to machine A using USB or an approved local file-transfer process;
- receives the HTML Response Package;
- imports and reviews the imported Answer Snapshot;
- starts AI evaluation from machine B.

### 5.2. Candidate on machine A

The candidate:

- opens the supplied HTML file in a supported Windows browser;
- reads and answers only the supplied questions;
- may save a draft file when instructed;
- submits the assessment and returns the generated response file.

Machine A is treated as a supervised assessment device. The threat model accepts that a technically motivated person could edit a local HTML file. The system therefore validates provenance and structure to prevent ordinary mistakes, but does not claim anti-tamper guarantees.

## 6. End-to-end workflow

```text
Machine B: Committee approves Question Set
        |
        v
Machine B: Export candidate-html.v1 Question Package
        |
        | USB or approved file transfer
        v
Machine A: Open package and start assessment
        |
        v
Machine A: Enter answers and optionally save draft
        |
        v
Machine A: Submit and download Response Package
        |
        | USB or approved file transfer
        v
Machine B: Import and validate Response Package
        |
        v
Machine B: Create immutable Answer Snapshot
        |
        v
Machine B: Queue AI answer evaluation
```

The original Question Package is never modified. Draft and response files are new files with distinct names.

## 7. Question Package contract

### 7.1. File format

The exported file uses the `.html` extension and the format identifier:

```text
candidate-html.v1
```

It is self-contained:

- no CDN assets;
- no external JavaScript;
- no external CSS;
- no network requests;
- no ES module imports that depend on a web server;
- no API key, session token, PIN, or candidate token.

The package contains a human-readable candidate view and an inert machine-readable payload embedded in the document. Machine B parses the known payload format; it never executes HTML or JavaScript received from machine A.

### 7.2. Package manifest

The manifest contains only the data required to match and render the assessment:

```json
{
  "formatVersion": "candidate-html.v1",
  "packageId": "opaque-package-id",
  "questionSetId": "opaque-question-set-id",
  "questionSetVersion": 1,
  "questionSetFingerprint": "sha256",
  "durationSeconds": 900,
  "questionCount": 8,
  "exportedAt": "UTC ISO 8601"
}
```

The package must not include raw JD/CV text, rubric details, expected evidence, AI prompts, or unnecessary candidate PII.

### 7.3. Question projection

Each rendered question contains:

- opaque question ID in the machine-readable payload;
- display order;
- question text;
- supported answer type;
- optional required/display flags defined by the approved Question Set.

Competency keys, purpose, expected evidence, difficulty, and rubric are backend/Committee data and must not be visible to the candidate unless a later product decision explicitly permits them.

## 8. Candidate experience on machine A

### 8.1. Start screen

The start screen displays:

- assessment instructions;
- number of questions;
- duration;
- basic save/submit guidance;
- package code or candidate code only when required for human matching;
- `Bắt đầu làm bài`.

The candidate must not see internal case data or AI metadata.

### 8.2. Assessment screen

The screen uses a question navigator and one active question:

- current question text;
- answer textarea;
- previous/next controls;
- question list with answered/unanswered status;
- visible timer;
- `Lưu bản nháp`;
- `Nộp bài`.

The candidate may revisit and edit answers before submission. The UI must preserve blank answers as blank and must not infer a negative answer from an empty field.

### 8.3. Draft saving

Because machine A has no backend connection, the primary recovery mechanism is an explicit downloaded draft file:

```text
candidate-assessment-<package-id>-draft.html
```

Opening a draft restores the answers and package identity. A draft is not importable as a submitted assessment until the candidate uses `Nộp bài`.

The UI must display a clear instruction to save a draft periodically and before closing the browser. Silent browser persistence is not required for MVP; the package must not depend on localStorage or IndexedDB for correctness.

### 8.4. Submit

On submit:

1. The UI shows the answered count and asks for confirmation.
2. The current in-memory answers are included in the response payload.
3. The assessment view becomes read-only.
4. The browser downloads a new Response Package:

```text
candidate-assessment-<package-id>-response.html
```

5. The page tells the candidate to return that exact file to the Committee.

The original Question Package remains unchanged. If the response download fails, the page must provide a retry path without clearing the answers.

## 9. Response Package contract

The response package contains:

- `formatVersion`;
- `packageId`;
- `questionSetId` and version;
- `questionSetFingerprint`;
- answer rows keyed by question ID;
- answer text as plain text;
- `isAnswered`;
- client-side started/submitted timestamps;
- answered count and total count;
- response payload fingerprint for idempotency and diagnostics.

It must not contain:

- JD/CV text;
- API keys, PINs, server sessions, or candidate tokens;
- Committee-only rubric or AI fields;
- executable external resources;
- arbitrary user-supplied HTML intended for rendering by the importer.

Client timestamps are operational metadata only. They are not authoritative audit evidence because machine A is offline.

## 10. Import and normalization on machine B

The import endpoint is Committee-only and accepts only the generated response package format.

### 10.1. Validation

The service must validate:

- file size and embedded payload size limits;
- exact supported format version;
- required manifest fields;
- package ID and Question Set match;
- Question Set version and fingerprint match;
- known question IDs and display orders;
- no duplicate or missing question rows;
- answer value types and maximum lengths;
- `isAnswered` consistency with answer text;
- safe plain-text handling;
- idempotency key and response fingerprint.

The importer must parse the known embedded data structure with a standard-library parser and JSON validation. It must not execute scripts, render imported HTML as active DOM, follow external links, or accept arbitrary HTML as a trusted payload.

### 10.2. Snapshot creation

A successful import creates an immutable Answer Snapshot containing:

- case and candidate references from the matched server-side package;
- JD/CV document IDs, versions, and hashes;
- Question Set ID/version and question fingerprint;
- question rows copied from the package/server match;
- answer text, answered flags, and normalized status;
- package ID, source marker `HTML_IMPORT`, import timestamp, and response fingerprint.

The snapshot is the only answer input used for AI evaluation. Later edits to the current Question Set or documents must not silently change the snapshot.

### 10.3. Idempotency and re-import

- Re-importing the same response with the same idempotency key returns the original import result.
- Re-importing the same semantic response under a new request key must not create duplicate current data.
- A changed response creates a new version only when the Committee explicitly starts a new import operation; it never overwrites a completed AI result.
- A failed import preserves all existing snapshots and AI results.

## 11. Workflow states

The active offline flow uses the following business sequence:

```text
QUESTIONS_APPROVED
    -> QUESTIONS_EXPORTED
    -> ANSWERS_IMPORTED
    -> AI_ANALYZING
    -> AI_EVALUATED
```

`QUESTIONS_EXPORTED` means that at least one candidate package was generated. Exporting a file does not itself start an assessment attempt on the server.

`ANSWERS_IMPORTED` is entered only after a valid Response Package creates an Answer Snapshot. Empty answers are valid and remain `NOT_ASSESSED`.

The server-side browser Candidate Mode states from the baseline specification are not used for this offline package flow. Historical records remain readable; no existing data is deleted as part of this design.

## 12. Error and recovery behavior

| Situation | Required behavior |
| --- | --- |
| Wrong Question Package returned | Reject import and identify package mismatch |
| Draft file supplied instead of response | Explain that the candidate must submit the draft first |
| Response file already imported | Return idempotent existing result |
| Response package malformed | Reject without changing case state or current result |
| Browser closed before draft save | Show operational warning; unsaved in-memory answers may be lost |
| Response download fails | Keep submitted view and allow retry |
| USB/file transfer fails | No server mutation; retry transfer |
| AI provider unavailable | Keep imported snapshot; expose retry/manual review |
| Machine B restarts after import | Snapshot remains available through SQLite transaction/WAL |

The UI and operating instructions should recommend saving a draft before switching applications or moving the machine A file.

## 13. Security and privacy

- Machine B remains bound to localhost and stores the canonical case data.
- Machine A receives only the minimum question projection.
- No secret is embedded in either HTML package.
- The response file contains candidate answers and must be treated as sensitive data during transfer and deletion.
- Export and import paths are generated and validated inside the configured data root on machine B.
- Logging must contain package IDs, status, counts, and error codes, but not answer text or raw HTML.
- Frontend rendering on machine B uses safe text nodes for imported answer content.
- Imported HTML is treated as untrusted data; scripts and external resources are never executed by the importer.

The design intentionally does not claim that a candidate cannot edit a local response file. That risk is accepted for the selected MVP threat model.

## 14. API and UI impact

The exact endpoint names must follow the existing API conventions, but the active flow requires:

- Committee-only export of an HTML Question Package;
- Committee-only import of an HTML Response Package;
- read-only access to the resulting Answer Snapshot;
- AI evaluation using that snapshot;
- package/source metadata in case and evaluation views.

The active workspace becomes:

```text
Documents -> Questions -> Export Candidate HTML -> Import Response HTML -> AI Evaluation
```

Excel export/import can remain behind a manual fallback action until the HTML flow is validated in operation.

## 15. Testing and acceptance

Tests must cover:

1. Export produces a self-contained `candidate-html.v1` file with the expected manifest and question projection.
2. Export contains no JD, CV, rubric, secret, token, or API key.
3. Candidate package opens without a web server or external resources.
4. Blank, partial, and fully answered assessments produce correct answer semantics.
5. Save draft and reopen draft restore answer text without changing package identity.
6. Submit creates a response package and locks the candidate view.
7. Response import round-trips questions and answers into an immutable snapshot.
8. Wrong package, wrong Question Set, duplicate question, missing question, malformed payload, oversized file, and unsupported version are rejected safely.
9. HTML/script content in answer text is stored and rendered as plain text.
10. Repeated import is idempotent and does not overwrite an existing AI result.
11. AI evaluation receives the matched JD/CV/question/answer snapshot only.
12. AI failure preserves the imported snapshot and exposes manual fallback.
13. Existing Excel snapshots and completed AI results remain readable.

## 16. Specification updates required before implementation

This design is approved conversationally but still needs to be reconciled in the written specification set before implementation:

- `documents/30_interview_workspace_ui_implementation_specification.md`: replace or branch the active Excel answer flow with HTML package export/import.
- `documents/18_phase2_supervised_interview_technology_specification.md`: no LAN change is needed; document that machine A is an offline file consumer.
- `documents/20_domain_and_database_specification.md`: add or confirm the snapshot source marker and package provenance fields through a new migration if needed.
- `documents/21_workflow_state_machine.md`: reconcile the offline package transitions with the existing Candidate Mode and refined Excel states.
- `documents/23_api_contract_specification.md`: define binary HTML export/import envelopes, idempotency, and validation errors.
- `documents/24_frontend_ui_specification.md`: define Committee export/import states and the separate candidate HTML interaction contract.
- `documents/25_security_and_audit_specification.md`: define offline package handling, sensitive file transfer, and the accepted non-adversarial threat model.
- `documents/27_test_and_acceptance_specification.md`: add package round-trip, recovery, and malformed-file acceptance criteria.

Existing migrations must not be edited after application. Any schema change requires a new versioned migration.

## 17. Open operational decisions

These decisions are intentionally not invented in this design:

- approved transfer mechanism: USB, controlled shared folder, or another offline process;
- supported browser baseline on machine A;
- exact per-answer character limits;
- whether the Committee requires a printed or manually recorded start/end time;
- retention and deletion procedure for the response HTML file after successful import.

The first implementation can proceed with a documented Windows browser baseline, USB transfer, existing question count/duration policy, and explicit operator instructions, provided those choices are recorded in the relevant specification.
