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

    def supports_vision(self) -> bool:
        return True

    def analyze_image(self, image_base64, system_prompt, model=None, **kwargs):
        """Analyze an image using Groq's vision-capable model."""
        vision_model = model or "meta-llama/llama-4-scout-17b-16e-instruct"
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this screenshot and provide your response:"
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{image_base64}",
                            }
                        }
                    ]
                }
            ]
            stream = self.client.chat.completions.create(
                messages=messages,
                model=vision_model,
                temperature=kwargs.get("temperature", 0.3),
                max_tokens=kwargs.get("max_tokens", 2000),
                stream=True
            )
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield token
        except Exception as e:
            print(f"[Groq] Vision error: {e}")
            yield f"Error: {e}"

