"""Factory function to instantiate the configured AI adapter."""

from dailygreen.ai.base import AIAdapter, AIAdapterError
from dailygreen.ai.gemini import GeminiAIAdapter
from dailygreen.ai.mock import MockAIAdapter
from dailygreen.config import AIConfig


def get_ai_adapter(config: AIConfig) -> AIAdapter:
    """Return an AI adapter instance matching the given configuration."""
    provider = config.provider.lower().strip()
    if provider == "mock":
        return MockAIAdapter()
    elif provider == "gemini":
        return GeminiAIAdapter(config)
    else:
        raise AIAdapterError(f"Unsupported AI provider: '{config.provider}'. Supported: 'mock', 'gemini'.")
