import unittest
from unittest.mock import patch

from app.agents.intent_agent import _intent, intent_translation_agent
from app.language import translate_answer


class IntentAgentTests(unittest.TestCase):
    def test_tomorrow_sailing_question_uses_weather_agent(self):
        self.assertEqual(_intent("is tomorrow okay to go out"), "Weather")

    def test_selected_bengali_reply_language_is_preserved(self):
        result = intent_translation_agent({"query": "আমি বুঝেছি", "requested_language": "bn-IN"})
        self.assertEqual(result["requested_language"], "bn-IN")

    def test_bengali_general_fallback_is_not_english(self):
        with patch("app.services.gemini_service.translate_from_english", side_effect=RuntimeError):
            answer = translate_answer("General", "bn-IN", {"available": True, "english": "Marine help."})
        self.assertRegex(answer, r"[\u0980-\u09FF]")

    def test_bengali_unavailable_data_message_is_translated(self):
        with patch("app.services.gemini_service.translate_from_english", return_value="সরাসরি তথ্য পাওয়া যাচ্ছে না।"):
            answer = translate_answer("Weather", "bn-IN", {"available": False, "english": "Live data is unavailable."})
        self.assertRegex(answer, r"[\u0980-\u09FF]")

    def test_input_and_reply_languages_are_independent(self):
        result = intent_translation_agent({
            "query": "मछली कहाँ है",
            "input_language": "hi-IN",
            "requested_language": "bn-IN",
        })
        self.assertEqual(result["detected_language"], "hi-IN")
        self.assertEqual(result["requested_language"], "bn-IN")

    def test_bengali_safety_question_uses_weather_agent(self):
        result = intent_translation_agent({
            "query": "আমি কি এখন বেরোতে পারি?",
            "input_language": "bn-IN",
            "requested_language": "bn-IN",
        })
        self.assertEqual(result["intent"], "Weather")


if __name__ == "__main__":
    unittest.main()
