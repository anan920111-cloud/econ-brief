"""DeepSeek API wrapper (OpenAI-compatible) with cost tracking."""

import logging

from openai import OpenAI

logger = logging.getLogger(__name__)

# DeepSeek pricing per million tokens (USD, as of 2025-2026)
# deepseek-chat (V3): $0.27/M input, $1.10/M output
# deepseek-reasoner (R1): $0.55/M input, $2.19/M output
PRICING = {
    "deepseek-chat": {
        "input": 0.27,
        "output": 1.10,
    },
    "deepseek-reasoner": {
        "input": 0.55,
        "output": 2.19,
    },
}

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class LLMClient:
    """Wrapper around OpenAI SDK targeting DeepSeek API.

    DeepSeek's API is fully OpenAI-compatible. We use the standard
    OpenAI client with a custom base_url and API key.

    DeepSeek does not support Anthropic-style prompt caching, but
    its pricing is so low ($0.27/1M input tokens) that caching is
    unnecessary for our use case.
    """

    def __init__(self, api_key: str, base_url: str | None = None):
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or DEEPSEEK_BASE_URL,
        )
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cost = 0.0

    # ── Public API ────────────────────────────────────────────────

    def create_message(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
    ) -> str:
        """Send a chat completion request to DeepSeek.

        Args:
            model: Model ID (e.g., "deepseek-chat", "deepseek-reasoner").
            system_prompt: System-level instructions.
            user_content: User message content.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature (0.0-2.0).

        Returns:
            The model's text response.
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            logger.error("DeepSeek API error: %s", e)
            raise

        # Track usage
        usage = response.usage
        input_tokens = usage.prompt_tokens
        output_tokens = usage.completion_tokens
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens

        # Cost calculation
        pricing = PRICING.get(model, {"input": 0.27, "output": 1.10})
        cost = (
            (input_tokens / 1_000_000) * pricing["input"]
            + (output_tokens / 1_000_000) * pricing["output"]
        )
        self._total_cost += cost

        logger.debug(
            "API call: model=%s, tokens(in=%d, out=%d), cost=$%.6f",
            model,
            input_tokens,
            output_tokens,
            cost,
        )

        # Extract text from response
        choices = response.choices
        if not choices:
            return ""

        return choices[0].message.content or ""

    # ── Statistics ────────────────────────────────────────────────

    @property
    def total_tokens(self) -> int:
        return self._total_input_tokens + self._total_output_tokens

    @property
    def total_cost(self) -> float:
        return self._total_cost

    def usage_summary(self) -> dict:
        """Return a summary of API usage."""
        return {
            "input_tokens": self._total_input_tokens,
            "output_tokens": self._total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_cost": round(self._total_cost, 6),
        }
