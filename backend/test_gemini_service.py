import os
import unittest
from unittest.mock import Mock, patch

from app.services.gemini_service import GeminiServiceError, _generate


class GeminiServiceTests(unittest.TestCase):
    def setUp(self):
        self.api_key = patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"})
        self.api_key.start()
        self.addCleanup(self.api_key.stop)

    @patch("app.services.gemini_service.requests.post")
    def test_requests_and_reads_structured_text(self, post):
        response = Mock()
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": '{"text":"Safe to sail."}'}]}}]}
        post.return_value = response

        self.assertEqual(_generate("system", "question"), "Safe to sail.")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"]["required"], ["text"])

    @patch("app.services.gemini_service.requests.post")
    def test_reports_safety_block_without_candidate(self, post):
        response = Mock()
        response.json.return_value = {"promptFeedback": {"blockReason": "SAFETY"}}
        post.return_value = response

        with self.assertRaisesRegex(GeminiServiceError, "blocked this request"):
            _generate("system", "question")

    @patch("app.services.gemini_service.requests.post")
    def test_rejects_unstructured_model_content(self, post):
        response = Mock()
        response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "plain text"}]}}]}
        post.return_value = response

        with self.assertRaisesRegex(GeminiServiceError, "invalid structured"):
            _generate("system", "question")


if __name__ == "__main__":
    unittest.main()
