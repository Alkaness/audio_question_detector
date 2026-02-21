"""
Groq AI Provider — Whisper transcription + LLaMA answers.
"""

from groq import Groq
from providers.base import AIProvider


class GroqProvider(AIProvider):
    """Groq: fast inference for Whisper + LLaMA."""

    DEFAULT_TRANSCRIPTION_MODEL = "whisper-large-v3"
    DEFAULT_ANSWER_MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key=None, **kwargs):
        super().__init__(api_key=api_key)
        if not api_key:
            raise ValueError("Groq requires an API key. Set GROQ_API_KEY in .env")
        self.client = Groq(api_key=api_key)

    def transcribe(self, wav_buffer, language="uk", prompt="") -> str:
        try:
            transcription = self.client.audio.transcriptions.create(
                file=wav_buffer,
                model=self.DEFAULT_TRANSCRIPTION_MODEL,
                response_format="text",
                prompt=prompt,
                temperature=0.0
            )
            return transcription.strip() if transcription else ""
        except Exception as e:
            print(f"[Groq] Transcription error: {e}")
            return ""

    def answer_stream(self, messages, model=None, **kwargs):
        try:
            stream = self.client.chat.completions.create(
                messages=messages,
                model=model or self.DEFAULT_ANSWER_MODEL,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 300),
                top_p=kwargs.get("top_p", 0.9),
                stream=True
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield token
        except Exception as e:
            print(f"[Groq] Answer error: {e}")
            yield f"Error: {e}"
