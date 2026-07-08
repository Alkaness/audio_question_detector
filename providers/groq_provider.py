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
        
        # Split comma-separated keys and strip whitespace
        if isinstance(api_key, str):
            self.api_keys = [k.strip() for k in api_key.split(",") if k.strip()]
        elif isinstance(api_key, list):
            self.api_keys = api_key
        else:
            self.api_keys = [api_key]

        if not self.api_keys:
            raise ValueError("Groq requires at least one valid API key.")

        self.current_key_index = 0
        self.client = Groq(api_key=self.api_keys[self.current_key_index])

    def _execute_with_retry(self, api_call_func, *args, **kwargs):
        """Execute a Groq API call, rotating keys if a rate limit (429) is hit."""
        import groq
        attempts = 0
        max_attempts = len(self.api_keys)
        
        while attempts < max_attempts:
            try:
                return api_call_func(*args, **kwargs)
            except (groq.RateLimitError, Exception) as e:
                # Check if it is a rate limit error
                is_rate_limit = False
                if isinstance(e, groq.RateLimitError):
                    is_rate_limit = True
                elif "rate limit" in str(e).lower() or "429" in str(e):
                    is_rate_limit = True
                
                if is_rate_limit and len(self.api_keys) > 1:
                    attempts += 1
                    old_index = self.current_key_index
                    self.current_key_index = (self.current_key_index + 1) % len(self.api_keys)
                    print(f"[Groq] Rate limit hit on key index {old_index}. Rotating to key index {self.current_key_index} (Attempt {attempts}/{max_attempts})")
                    self.client = Groq(api_key=self.api_keys[self.current_key_index])
                    continue
                else:
                    # Not a rate limit, or we have no other keys to try
                    raise e
        
        # If we exhausted all keys
        raise Exception("All Groq API keys are currently rate-limited.")

    def transcribe(self, wav_buffer, language="uk", prompt="") -> str:
        def _do_transcribe():
            return self.client.audio.transcriptions.create(
                file=wav_buffer,
                model=self.DEFAULT_TRANSCRIPTION_MODEL,
                response_format="text",
                prompt=prompt,
                temperature=0.0
            )

        try:
            transcription = self._execute_with_retry(_do_transcribe)
            return transcription.strip() if transcription else ""
        except Exception as e:
            print(f"[Groq] Transcription error: {e}")
            return ""

    def answer_stream(self, messages, model=None, **kwargs):
        def _get_stream():
            return self.client.chat.completions.create(
                messages=messages,
                model=model or self.DEFAULT_ANSWER_MODEL,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 300),
                top_p=kwargs.get("top_p", 0.9),
                stream=True
            )

        try:
            stream = self._execute_with_retry(_get_stream)
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

        def _get_vision_stream():
            return self.client.chat.completions.create(
                messages=messages,
                model=vision_model,
                temperature=kwargs.get("temperature", 0.3),
                max_tokens=kwargs.get("max_tokens", 2000),
                stream=True
            )

        try:
            stream = self._execute_with_retry(_get_vision_stream)
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    yield token
        except Exception as e:
            print(f"[Groq] Vision error: {e}")
            yield f"Error: {e}"

    def correct_text(self, text) -> str:
        """Correct raw transcribed text using Groq llama-3.1-8b-instant."""
        if not text:
            return ""
        
        def _do_correct():
            correction = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content":
                        "You are a speech recognition text corrector.\n"
                        "Strict rules:\n"
                        "1. Fix ONLY individual words that are obviously garbled IT terms\n"
                        "2. NEVER add new words or sentences\n"
                        "3. NEVER delete words\n"
                        "4. NEVER explain or expand the text\n"
                        "5. The word count in your response must match the original\n"
                        "6. If the text is already correct, return it unchanged\n"
                        "Examples: 'paithan' → 'Python', 'rest apay' → 'REST API', 'dokker' → 'Docker'."},
                    {"role": "user", "content": text}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                max_tokens=150
            )
            return correction.choices[0].message.content.strip()

        try:
            return self._execute_with_retry(_do_correct)
        except Exception as e:
            print(f"[Groq] Correction error: {e}")
            return text


