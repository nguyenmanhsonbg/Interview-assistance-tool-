import unittest
from pathlib import Path


class WindowsPackagingContractTests(unittest.TestCase):
    def test_windows_packaging_script_builds_self_extracting_exe(self):
        script = (Path(__file__).resolve().parents[1] / "scripts" / "package_windows.ps1").read_text(encoding="utf-8")

        for marker in (
            "iexpress.exe",
            "ClawCV-0.1.0-win64.exe",
            "Class=IEXPRESS",
            "AppLaunched=",
            "SourceFiles0=",
            "start.bat",
        ):
            self.assertIn(marker, script)


if __name__ == "__main__":
    unittest.main()
