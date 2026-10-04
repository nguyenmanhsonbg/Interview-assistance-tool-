import os
import unittest
from unittest.mock import patch


class AppConfigTests(unittest.TestCase):
    def test_defaults_keep_generic_provider_and_hide_api_key(self):
        from app.config import AppConfig

        with patch.dict(os.environ, {}, clear=True):
            os.environ["LOCALAPPDATA"] = os.getcwd()
            config = AppConfig.from_environment()

        self.assertEqual("generic", config.ai_provider)
        self.assertIsNone(config.ai_endpoint)
        self.assertEqual("configured-model", config.ai_model)
        self.assertNotIn("secret", repr(config))

    def test_reads_gemini_environment_contract(self):
        from app.config import AppConfig

        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "gemini",
                "GEMINI_API_KEY": "secret-key",
                "GEMINI_CV_PARSE_MODELS": "gemini 3.5 flash, gemini-3.6-flash",
                "GEMINI_CV_PARSE_TIMEOUT_MS": "12345",
                "LOCALAPPDATA": os.getcwd(),
            },
            clear=True,
        ):
            config = AppConfig.from_environment()

        self.assertEqual("gemini", config.ai_provider)
        self.assertEqual("secret-key", config.gemini_api_key)
        self.assertEqual(
            ("gemini 3.5 flash", "gemini-3.6-flash"), config.gemini_models
        )
        self.assertEqual(12.345, config.gemini_timeout_seconds)
        self.assertNotIn("secret-key", repr(config))

    def test_empty_gemini_model_configuration_uses_default_models(self):
        from app.config import AppConfig

        with patch.dict(
            os.environ,
            {
                "AI_PROVIDER": "gemini",
                "GEMINI_CV_PARSE_MODELS": " , ",
                "LOCALAPPDATA": os.getcwd(),
            },
            clear=True,
        ):
            config = AppConfig.from_environment()

        self.assertEqual(
            (
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
            ),
            config.gemini_models,
        )

    def test_rejects_unknown_provider_and_nonpositive_gemini_timeout(self):
        from app.config import AppConfig

        with self.assertRaises(ValueError):
            AppConfig(ai_provider="unknown")
        with self.assertRaises(ValueError):
            AppConfig(ai_provider="gemini", gemini_timeout_seconds=0)

if __name__ == "__main__":
    unittest.main()
