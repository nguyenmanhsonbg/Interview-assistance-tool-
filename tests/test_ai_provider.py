import io
import json
import unittest
import urllib.error


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self.payload if size < 0 else self.payload[:size]


class AIProviderTests(unittest.TestCase):
    def test_http_provider_sends_json_and_parses_object(self):
        from app.ai.http_provider import HttpAIProvider

        captured = []

        def opener(request, timeout):
            captured.append((request, timeout))
            return FakeResponse(b'{"schemaVersion":"question-generation.v1"}')

        provider = HttpAIProvider(
            "https://ai.example.test/v1", api_key="secret", model="model-1",
            timeout=4, opener=opener, sleep=lambda _: None,
        )
        result = provider.generate_questions({"candidateCode": "C-1"})

        sent = json.loads(captured[0][0].data)
        self.assertEqual("GENERATE_QUESTIONS", sent["operation"])
        self.assertEqual("model-1", sent["model"])
        self.assertEqual(4, captured[0][1])
        self.assertEqual("question-generation.v1", result["schemaVersion"])

    def test_retryable_500_is_retried_once_but_400_is_not(self):
        from app.ai.http_provider import HttpAIProvider
        from app.ai.provider import ProviderError

        calls = []

        def retry_opener(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError(request.full_url, 500, "server", {}, io.BytesIO())
            return FakeResponse(b'{}')

        provider = HttpAIProvider(
            "https://ai.example.test", api_key=None, model="m",
            max_retry=1, opener=retry_opener, sleep=lambda _: None,
        )
        self.assertEqual({}, provider.evaluate_answers({}))
        self.assertEqual(2, len(calls))

        def bad_request(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, io.BytesIO())

        provider = HttpAIProvider(
            "https://ai.example.test", api_key=None, model="m",
            max_retry=1, opener=bad_request, sleep=lambda _: None,
        )
        with self.assertRaises(ProviderError) as error:
            provider.evaluate_answers({})
        self.assertFalse(error.exception.retryable)

    def test_response_larger_than_limit_is_rejected(self):
        from app.ai.http_provider import HttpAIProvider
        from app.ai.provider import ProviderError

        provider = HttpAIProvider(
            "https://ai.example.test", api_key=None, model="m", max_response_bytes=5,
            opener=lambda request, timeout: FakeResponse(b"123456"), sleep=lambda _: None,
        )
        with self.assertRaises(ProviderError):
            provider.suggest_follow_up({})


if __name__ == "__main__":
    unittest.main()
