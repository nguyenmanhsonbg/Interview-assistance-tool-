# Phase 2 Pilot Release Readiness Checklist

## Automated evidence

- [x] Full `unittest` suite passes on target Windows Python (79 tests, 2026-10-04).
- [x] HTTP E2E completes case → documents → questions → candidate → AI → brief → live → final.
- [x] SQLite backup restores with `integrity_check=ok` and no foreign-key violations.
- [x] Candidate isolation, answer lock, Host validation and secret redaction tests pass.
- [x] No `requirements.txt`, `package.json` or third-party runtime dependency exists.

## Portable artifact

- [x] Official CPython embeddable ZIP checksum verified.
- [x] Portable smoke test creates database/migration under a temporary data directory.
- [x] Release ZIP and `.sha256` generated under `release/`.
- [x] ZIP contains no test data, database, log, API key, PIN or token.
- [ ] Clean Windows user can unpack, run `start.bat` and open `127.0.0.1:8787`.
- [ ] `%LOCALAPPDATA%\ClawCV` contains all runtime data; install directory stays immutable.

## Manual pilot acceptance

- [ ] Set PIN and reopen Committee session.
- [ ] Complete both AI-configured and manual-fallback workflows.
- [ ] Refresh during autosave and verify latest committed answer remains.
- [ ] Restart during a running AI task and verify retry/fail recovery without duplicate result.
- [ ] Confirm Candidate Mode cannot access Committee routes/data.
- [ ] Create backup/export; inspect manifest and verify no secret.
- [ ] Finalize as Lead; verify non-Lead cannot finalize and revision preserves prior FINAL.

## Governance and rollback

- [ ] DRAFT specifications receive owner review before being marked APPROVED.
- [ ] Approved AI gateway/data-processing policy is recorded for the pilot organization.
- [ ] Backup is captured before pilot migration or upgrade.
- [ ] Rollback procedure and responsible operator are named.
- [ ] Known limitations and open backlog are accepted by Product Owner/Security reviewer.
