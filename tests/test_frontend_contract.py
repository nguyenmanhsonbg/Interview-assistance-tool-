import unittest
from pathlib import Path


class FrontendContractTests(unittest.TestCase):
    def test_frontend_avoids_unsafe_rendering_and_contains_workflow_routes(self):
        root = Path(__file__).resolve().parents[1] / "web"
        scripts = "\n".join(path.read_text(encoding="utf-8") for path in root.rglob("*.js"))
        for forbidden in ("innerHTML", "new Function", "localStorage", "sessionStorage"):
            self.assertNotIn(forbidden, scripts)
        for route in ("/documents", "/questions", "/check-in", "/brief", "/live", "/evaluation"):
            self.assertIn(route, scripts)
        self.assertIn("textContent", scripts)
        self.assertIn("state.committeeSession = null", scripts)
        self.assertIn("answerRevisions", scripts)
        self.assertIn("editor.inFlight", scripts)
        candidate = (root / "js" / "views" / "candidate_assessment.js").read_text(
            encoding="utf-8"
        )
        self.assertIn('error.code === "UNAUTHENTICATED"', candidate)
        self.assertIn("clearSensitiveState();", candidate)

    def test_no_third_party_runtime_import_manifest_exists(self):
        root = Path(__file__).resolve().parents[1]
        self.assertFalse((root / "requirements.txt").exists())
        self.assertFalse((root / "package.json").exists())


if __name__ == "__main__":
    unittest.main()
