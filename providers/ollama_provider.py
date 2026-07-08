"""
Ollama Provider — Local models via HTTP API.
No API key needed. Requires Ollama running on localhost.
"""

import json
import requests
from providers.base import AIProvider


class OllamaProvider(AIProvider):
    """Ollama: local models via HTTP API (no API key needed)."""

    DEFAULT_ANSWER_MODEL = "llama3.2"
    BASE_URL = "http://localhost:11434"

    def __init__(self, api_key=None, **kwargs):
        super().__init__(api_key=api_key)
        self.base_url = kwargs.get("base_url", self.BASE_URL)

    def transcribe(self, wav_buffer, language="uk", prompt="") -> str:
        """Ollama doesn't support audio transcription natively."""
        raise NotImplementedError(
            "Ollama does not support audio transcription. "
            "Use Groq or OpenAI for transcription."
        )

    def supports_transcription(self) -> bool:
        return False

    def answer_stream(self, messages, model=None, **kwargs):
        try:
            # Ollama uses /api/chat with OpenAI-compatible message format
            payload = {
                "model": model or self.DEFAULT_ANSWER_MODEL,
                "messages": messages,
                "stream": True,
                "options": {
                    "temperature": kwargs.get("temperature", 0.7),
                    "top_p": kwargs.get("top_p", 0.9),
                    "num_predict": kwargs.get("max_tokens", 300),
                }
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=30
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done", False):
                        break
        except requests.ConnectionError:
            yield "Error: Cannot connect to Ollama. Is it running? (ollama serve)"
        except Exception as e:
            print(f"[Ollama] Answer error: {e}")
            yield f"Error: {e}"

    def supports_vision(self) -> bool:
        return True

    def analyze_image(self, image_base64, system_prompt, model=None, **kwargs):
        """Analyze an image using Ollama's vision-capable model (e.g., llava)."""
        vision_model = model or "llava"
        try:
            payload = {
                "model": vision_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": "Analyze this screenshot and provide your response:",
                        "images": [image_base64]
                    }
                ],
                "stream": True,
                "options": {
                    "temperature": kwargs.get("temperature", 0.3),
                    "num_predict": kwargs.get("max_tokens", 2000),
                }
            }
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                stream=True,
                timeout=60
            )
            resp.raise_for_status()

            for line in resp.iter_lines():
                if line:
                    data = json.loads(line)
                    token = data.get("message", {}).get("content", "")
                    if token:
                        yield token
                    if data.get("done", False):
                        break
        except requests.ConnectionError:
            yield "Error: Cannot connect to Ollama. Is it running? (ollama serve)"
        except Exception as e:
            print(f"[Ollama] Vision error: {e}")
            yield f"Error: {e}"

