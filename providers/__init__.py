"""
AI Provider Registry — factory for transcription and answer providers.
"""

from providers.groq_provider import GroqProvider
from providers.openai_provider import OpenAIProvider
from providers.ollama_provider import OllamaProvider

# Registry of available providers
PROVIDERS = {
    "groq": GroqProvider,
    "openai": OpenAIProvider,
    "ollama": OllamaProvider,
}

# Display names for UI
PROVIDER_NAMES = {
    "groq": "Groq (LLaMA 3.3 + Whisper)",
    "openai": "OpenAI (GPT-4o-mini + Whisper)",
    "ollama": "Ollama (Local Models)",
}

# Which providers support transcription
TRANSCRIPTION_PROVIDERS = ["groq", "openai"]

# Which providers support answer generation
ANSWER_PROVIDERS = ["groq", "openai", "ollama"]


def get_provider(name, api_key=None, **kwargs):
    """Create a provider instance by name."""
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name}. Available: {list(PROVIDERS.keys())}")
    return cls(api_key=api_key, **kwargs)
