import io
import unittest
from unittest.mock import AsyncMock, patch

from starlette.datastructures import Headers, UploadFile

from main import submit_voice_query


class VoicePipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_voice_uses_the_text_query_workflow_with_its_context(self):
        audio = UploadFile(
            file=io.BytesIO(b"voice"),
            filename="question.webm",
            headers=Headers({"content-type": "audio/webm"}),
        )
        query_result = {
            "answer": "এখন সমুদ্রে যাওয়া নিরাপদ।",
            "language": "bn-IN",
            "visual_trace": {},
            "execution_log": [],
        }
        history = '[{"role":"user","text":"আগের প্রশ্ন"}]'

        with (
            patch("main.speech_to_text", return_value="আমি কি এখন বেরোতে পারি?"),
            patch("main.translate_to_english", return_value="Can I go out now?"),
            patch("main.run_query", new=AsyncMock(return_value=query_result)) as run_query,
            patch("main.text_to_speech", return_value="audio-data") as text_to_speech,
        ):
            result = await submit_voice_query(
                audio=audio,
                language="bn-IN",
                reply_language="bn-IN",
                latitude=20.25,
                longitude=88.45,
                history=history,
            )

        run_query.assert_awaited_once_with(
            "Can I go out now?",
            "bn-IN",
            20.25,
            88.45,
            history=[{"role": "user", "text": "আগের প্রশ্ন"}],
            input_language="en-IN",
        )
        text_to_speech.assert_called_once_with(query_result["answer"], "bn-IN")
        self.assertEqual(result["answer"], query_result["answer"])
        self.assertEqual(result["language"], "bn-IN")


if __name__ == "__main__":
    unittest.main()
