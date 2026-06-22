"""Anthropic SDK wrapper with prompt caching and cost tracking."""

import logging
from typing import Optional

import anthropic

logger = logging.getLogger(__name__)

# Pricing per million tokens (as of 2025-2026)
PRICING = {
    "claude-haiku-4-5-20250514": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.00,
        "output:": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
}


class LLMClient:
    """Wrapper around Anthropic SDK with caching and cost tracking."""

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._total_cache_write_tokens = 0
        self._total_cache_read_tokens = 0
        self._total_cost = 0.0

    # ── Public API ────────────────────────────────────────────────

    def create_message(
        self,
        model: str,
        system_prompt: str,
        user_content: str,
        max_tokens: int = 4096,
        temperature: float = 0.3,
        use_caching: bool = True,
    ) -> str:
        """Send a message to Claude and return the text response.

        Args:
            model: Model ID string.
            system_prompt: System-level instructions.
            user_content: User message content.
            max_tokens: Maximum output tokens.
            temperature: Sampling temperature (0.0-1.0).
            use_caching: Whether to enable prompt caching on system prompt.

        Returns:
            The model's text response.
        """
        # Build system blocks with optional caching
        system_blocks = self._build_system_blocks(system_prompt, use_caching)

        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                system=system_blocks,
                messages=[{"role": "user", "content": user_content}],
            )
        except anthropic.APIError as e:
            logger.error("Anthropic API error: %s", e)
            raise

        # Track usage
        usage = response.usage
        self._total_input_tokens += usage.input_tokens
        self._total_output_tokens += usage.output_tokens

        # Cache token tracking
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self._total_cache_read_tokens += cache_read
        self._total_cache_write_tokens += cache_write

        # Cost calculation
        pricing = PRICING.get(model, {"input": 3.0, "output": 15.0, "cache_write": 3.75, "cache_read": 0.30})
        regular_input = usage.input_tokens - cache_read - cache_write
        cost = (
            (regular_input / 1_000_000) * pricing["input"]
            + (cache_write / 1_000_000) * pricing.get("cache_write", pricing["input"] * 1.25)
            + (cache_read / 1_000_000) * pricing.get("cache_read", pricing["input"] * 0.10)
            + (usage.output_tokens / 1_000_000) * pricing["output"]
        )
        self._total_cost += cost

        logger.debug(
            "API call: model=%s, tokens(in=%d, out=%d, cache_read=%d, cache_write=%d), cost=$%.6f",
            model,
            usage.input_tokens,
            usage.output_tokens,
            cache_read,
            cache_write,
            cost,
        )

        # Extract text
        content = response.content
        if not content:
            return ""

        # Get text from the first text block
        for block in content:
            if block.type == "text":
                return block.text

        return ""

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
            "cache_read_tokens": self._total_cache_read_tokens,
            "cache_write_tokens": self._total_cache_write_tokens,
            "total_tokens": self.total_tokens,
            "total_cost": round(self._total_cost, 6),
        }

    # ── Private helpers ───────────────────────────────────────────

    @staticmethod
    def _build_system_blocks(
        system_prompt: str, use_caching: bool
    ) -> list[dict]:
        """Build system message blocks, optionally with cache control."""
        if use_caching:
            return [{
                "type": "text",
                "text": system_prompt,
                "cache_control": {"type": "ephemeral"},
            }]
        else:
            return [{"type": "text", "text": system_prompt}]
