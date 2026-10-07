import io
import json
import logging
import tempfile
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self, _limit):
        return self.payload


def gemini_response(text: str) -> bytes:
    return json.dumps(
        {
            "candidates": [
                {"content": {"parts": [{"text": text}]}}
            ]
        }
    ).encode("utf-8")


class GeminiProviderTests(unittest.TestCase):
    def make_provider(self, opener, *, models=None, api_key="secret-key", logger=None):
        from app.ai.gemini_provider import GeminiAIProvider

        return GeminiAIProvider(
            api_key=api_key,
            models=models or ("gemini-3.6-flash", "gemini-3.5-flash"),
            timeout=12.5,
            opener=opener,
            sleep=lambda _seconds: None,
            logger=logger,
        )

    def test_concatenates_text_parts_and_builds_gemini_request(self):
        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return FakeResponse(
                json.dumps(
                    {
                        "candidates": [
                            {
                                "content": {
                                    "parts": [
                                        {"text": '{"ok": '},
                                        {"text": "true}"},
                                    ]
                                }
                            }
                        ]
                    }
                ).encode("utf-8")
            )

        result = self.make_provider(opener).generate_questions(
            {"candidateCode": "C-1"}
        )

        self.assertEqual({"ok": True}, result)
        request, timeout = captured[0]
        self.assertEqual(12.5, timeout)
        self.assertEqual(
            "gemini-3.6-flash",
            urlsplit(request.full_url).path.rsplit("/", 1)[-1].split(":", 1)[0],
        )
        self.assertEqual("secret-key", parse_qs(urlsplit(request.full_url).query)["key"][0])
        self.assertEqual("application/json", request.headers["Content-type"])
        self.assertNotIn("Authorization", request.headers)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual("user", body["contents"][0]["role"])
        self.assertIn("candidateCode", body["contents"][0]["parts"][0]["text"])
        self.assertEqual(
            "You are a safe JSON-only assistant for the supervised interview tool.",
            body["systemInstruction"]["parts"][0]["text"],
        )
        self.assertEqual(0.2, body["generationConfig"]["temperature"])
        self.assertEqual(
            "application/json", body["generationConfig"]["responseMimeType"]
        )
        response_schema = body["generationConfig"]["responseSchema"]
        self.assertEqual("OBJECT", response_schema["type"])
        self.assertEqual(
            [
                "schemaVersion",
                "operation",
                "competencyMatrix",
                "questions",
                "gaps",
                "conflicts",
                "estimatedDurationSeconds",
                "confidence",
                "limitations",
            ],
            response_schema["required"],
        )
        self.assertEqual("STRING", response_schema["properties"]["schemaVersion"]["type"])
        self.assertEqual("STRING", response_schema["properties"]["operation"]["type"])
        self.assertEqual(
            ["question-generation.v1"],
            response_schema["properties"]["schemaVersion"]["enum"],
        )
        self.assertEqual(
            ["QUESTION_GENERATION"],
            response_schema["properties"]["operation"]["enum"],
        )
        self.assertEqual(
            ["SHORT_TEXT", "LONG_TEXT", "SCENARIO"],
            response_schema["properties"]["questions"]["items"]["properties"]["questionType"]["enum"],
        )
        self.assertIn("questions", response_schema["properties"])

    def test_accepts_json_fence_and_commentary_before_json(self):
        calls = []

        def fenced_opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return FakeResponse(
                    gemini_response('Here is the JSON:\n```json\n{"status":"ok"}\n```')
                )
            return FakeResponse(gemini_response('{"status":"second"}'))

        self.assertEqual(
            {"status": "ok"},
            self.make_provider(fenced_opener).evaluate_answers({}),
        )
        self.assertEqual(1, len(calls))

    def test_retries_malformed_json_on_next_model(self):
        calls = []

        def invalid_then_valid_opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                return FakeResponse(gemini_response("not json"))
            return FakeResponse(gemini_response('{"status":"ok"}'))

        self.assertEqual(
            {"status": "ok"},
            self.make_provider(invalid_then_valid_opener).evaluate_answers({}),
        )
        self.assertEqual(2, len(calls))

    def test_rotates_after_retryable_http_error_without_leaking_key(self):
        calls = []
        log_output = io.StringIO()
        logger = logging.getLogger("gemini-provider-test")
        logger.handlers.clear()
        logger.setLevel(logging.INFO)
        logger.propagate = False
        handler = logging.StreamHandler(log_output)
        logger.addHandler(handler)

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    request.full_url, 429, "rate limited", {}, io.BytesIO()
                )
            return FakeResponse(gemini_response('{"status":"ok"}'))

        result = self.make_provider(
            opener,
            models=("gemini-3.6-flash", "gemini-3.5-flash"),
            logger=logger,
        ).suggest_follow_up({})

        self.assertEqual({"status": "ok"}, result)
        self.assertEqual(2, len(calls))
        self.assertNotEqual(
            urlsplit(calls[0].full_url).path,
            urlsplit(calls[1].full_url).path,
        )
        self.assertNotIn("secret-key", log_output.getvalue())
        logger.removeHandler(handler)

    def test_rotates_after_network_error_and_empty_response(self):
        for failure in (urllib.error.URLError("offline"), "empty"):
            calls = []

            def opener(request, timeout, failure=failure):
                calls.append(request)
                if len(calls) == 1:
                    if isinstance(failure, Exception):
                        raise failure
                    return FakeResponse(gemini_response(""))
                return FakeResponse(gemini_response('{"status":"ok"}'))

            result = self.make_provider(opener).generate_questions({})
            self.assertEqual({"status": "ok"}, result)
            self.assertEqual(2, len(calls))

    def test_model_aliases_are_normalized_and_round_robin_starts_next_model(self):
        from app.ai.gemini_provider import normalize_model_ids

        self.assertEqual(
            (
                "gemini-3.6-flash",
                "gemini-3.5-flash",
                "gemini-3.5-flash-lite",
            ),
            normalize_model_ids(("gemini 3.5 flash", "gemini-3.6-flash")),
        )

        calls = []

        def opener(request, timeout):
            calls.append(request)
            return FakeResponse(gemini_response('{"status":"ok"}'))

        provider = self.make_provider(opener)
        provider.generate_questions({})
        provider.generate_questions({})

        self.assertEqual(
            "gemini-3.6-flash",
            urlsplit(calls[0].full_url).path.rsplit("/", 1)[-1].split(":", 1)[0],
        )
        self.assertEqual(
            "gemini-3.5-flash",
            urlsplit(calls[1].full_url).path.rsplit("/", 1)[-1].split(":", 1)[0],
        )

    def test_missing_api_key_is_safe_nonretryable_error(self):
        from app.ai.provider import ProviderError

        with self.assertRaises(ProviderError) as caught:
            self.make_provider(lambda *_: None, api_key=None).generate_questions({})

        self.assertEqual("MISSING_API_KEY", caught.exception.code)
        self.assertFalse(caught.exception.retryable)
        self.assertNotIn("secret", str(caught.exception))


class GeminiFactoryTests(unittest.TestCase):
    def test_builds_gemini_provider_without_network_call(self):
        from app.ai.factory import build_ai_provider
        from app.ai.gemini_provider import GeminiAIProvider
        from app.config import AppConfig

        config = AppConfig(
            ai_provider="gemini",
            gemini_api_key="secret-key",
            gemini_models=("gemini-3.6-flash",),
        )

        provider = build_ai_provider(config)

        self.assertIsInstance(provider, GeminiAIProvider)
        self.assertEqual("secret-key", provider.api_key)

    def test_generic_provider_requires_endpoint(self):
        from app.ai.factory import build_ai_provider
        from app.config import AppConfig

        self.assertIsNone(build_ai_provider(AppConfig(ai_provider="generic")))


if __name__ == "__main__":
    unittest.main()
