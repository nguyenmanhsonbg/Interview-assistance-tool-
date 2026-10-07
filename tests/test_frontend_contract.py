import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_frontend_avoids_unsafe_rendering_and_contains_refined_workflow(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        for forbidden in ("innerHTML", "new Function", "localStorage", "sessionStorage"):
            self.assertNotIn(forbidden, scripts)
        for route in (
            "/documents",
            "/questions",
            "/question-set/export",
            "/assessment-snapshots/import",
            "/ai/evaluate",
            "/ai/evaluation",
        ):
            self.assertIn(route, scripts)
        for removed in (
            "/check-in",
            "/brief",
            "/live-interview",
            "/final-evaluation",
            "/assessment-attempts",
            "candidate_assessment",
            "enterCandidateMode",
        ):
            self.assertNotIn(removed, scripts)
        self.assertIn("apiDownload", scripts)
        self.assertIn("apiUpload", scripts)
        self.assertIn('file.accept = ".xlsx"', scripts)
        self.assertIn('pdf.input.accept = ".pdf,application/pdf"', scripts)
        self.assertIn("contentBase64: await fileToBase64(file)", scripts)
        self.assertIn("textContent", scripts)
        self.assertIn("currentSnapshotId", scripts)
        self.assertIn("clearSensitiveState", scripts)

    def test_no_third_party_runtime_import_manifest_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "requirements.txt").exists())
        self.assertFalse((root / "package.json").exists())

    def test_interview_workspace_shell_and_active_routes_are_present(self):
        root = Path(__file__).resolve().parents[1] / "web"
        index = (root / "index.html").read_text(encoding="utf-8")
        styles = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.css"))
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))

        for marker in ("app-shell", "main-content", "app.js"):
            self.assertIn(marker, index)
        for token in (
            "--ui-primary",
            "--ui-surface",
            "sidebar",
            "case-header",
            "case-stepper",
            "prefers-reduced-motion",
            "@media (max-width: 899px)",
        ):
            self.assertIn(token, styles)
        for marker in (
            "renderAppShell",
            "renderCaseHeader",
            "renderCaseStepper",
            "renderCasesWithStatus(status.input.value, listHost",
            "renderDocumentHistory",
            "questionPolicy",
            "item.score === null",
            "/settings",
            "/backups",
            'stepHref(caseId, "ai")',
            "/api/v1/auth/lock",
            "committee-session-expired",
            "generate.disabled",
            "manual.disabled",
            "host?.isConnected",
            "resultSnapshot",
            "item.concerns",
            "role",
            "tablist",
            "tabpanel",
            "skipLink?.addEventListener",
            "submitting",
            "X-Idempotency-Key",
            "next.addEventListener",
            "aria-selected",
            "aria-describedby",
            "role",
            "NOT_ASSESSED",
            "assessmentSnapshotId",
        ):
            self.assertIn(marker, scripts)
        self.assertNotIn("function manualQuestions", scripts)


if __name__ == "__main__":
    unittest.main()
