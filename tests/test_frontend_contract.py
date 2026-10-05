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
        self.assertIn("textContent", scripts)
        self.assertIn("currentSnapshotId", scripts)
        self.assertIn("clearSensitiveState", scripts)

    def test_no_third_party_runtime_import_manifest_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "requirements.txt").exists())
        self.assertFalse((root / "package.json").exists())


if __name__ == "__main__":
    unittest.main()
