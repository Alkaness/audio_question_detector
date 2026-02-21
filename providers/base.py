"""
Abstract base class for AI providers.
"""

from abc import ABC, abstractmethod


class AIProvider(ABC):
    """Base class for all AI providers."""

    def __init__(self, api_key=None, **kwargs):
        self.api_key = api_key

    @abstractmethod
    def transcribe(self, wav_buffer, language="uk", prompt="") -> str:
        """Transcribe audio from a WAV buffer.
        
        Args:
            wav_buffer: BytesIO object with WAV audio data (.name must be set)
            language: ISO language code for transcription
            prompt: Context prompt to improve accuracy
            
        Returns:
            Transcribed text string, or empty string on failure.
        """
        pass

    @abstractmethod
    def answer_stream(self, messages, model=None, **kwargs):
        """Generate an answer with streaming tokens.
        
        Args:
            messages: List of message dicts [{"role": "...", "content": "..."}]
            model: Optional model override
            
        Yields:
            String tokens as they arrive.
        """
        pass

    def supports_transcription(self) -> bool:
        """Override to return False if provider doesn't support transcription."""
        return True

    def supports_answer(self) -> bool:
        """Override to return False if provider doesn't support answers."""
        return True
