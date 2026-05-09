import os
import unittest
from unittest.mock import patch


class TestOpenAIClientApiKeyFallback(unittest.TestCase):
    """OpenAI-compatible providers accept OPENAI_API_KEY when provider-specific env is unset."""

    @patch("tradingagents.llm_clients.openai_client.DeepSeekChatOpenAI")
    def test_deepseek_uses_openai_api_key_when_deepseek_unset(self, mock_chat):
        with patch.dict(
            os.environ,
            {"DEEPSEEK_API_KEY": "", "OPENAI_API_KEY": "openai-fallback"},
            clear=False,
        ):
            from tradingagents.llm_clients.openai_client import OpenAIClient

            OpenAIClient("deepseek-chat", provider="deepseek").get_llm()
        call_kwargs = mock_chat.call_args[1]
        self.assertEqual(call_kwargs.get("api_key"), "openai-fallback")


if __name__ == "__main__":
    unittest.main()
