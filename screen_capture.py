"""
Screen Capture Module — capture screen regions for coding interview analysis.
Supports full-screen and region capture via mss (cross-platform).
Images are compressed and sent to vision-capable LLMs for analysis.
"""

import base64
import io
import platform
import threading

IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

# Lazy imports — graceful degradation if not installed
MSS_AVAILABLE = False
PIL_AVAILABLE = False

try:
    import mss
    import mss.tools
    MSS_AVAILABLE = True
except ImportError:
    pass

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    pass


def is_available():
    """Check if screen capture dependencies are installed."""
    return MSS_AVAILABLE and PIL_AVAILABLE


def capture_full_screen(monitor_index=0):
    """Capture full screen as a PIL Image.

    Args:
        monitor_index: 0 = all monitors combined, 1+ = specific monitor

    Returns:
        PIL.Image or None on failure.
    """
    if not is_available():
        print("[ScreenCapture] mss or Pillow not installed.")
        return None
    try:
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index >= len(monitors):
                monitor_index = 0
            monitor = monitors[monitor_index]
            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            return img
    except Exception as e:
        print(f"[ScreenCapture] Full screen capture error: {e}")
        return None


def capture_region(x, y, width, height):
    """Capture a specific screen region as a PIL Image.

    Args:
        x, y: Top-left corner coordinates
        width, height: Region dimensions in pixels

    Returns:
        PIL.Image or None on failure.
    """
    if not is_available():
        print("[ScreenCapture] mss or Pillow not installed.")
        return None
    try:
        with mss.mss() as sct:
            region = {"top": y, "left": x, "width": width, "height": height}
            screenshot = sct.grab(region)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            return img
    except Exception as e:
        print(f"[ScreenCapture] Region capture error: {e}")
        return None


def image_to_base64(img, max_size=1920, quality=85):
    """Convert PIL Image to base64-encoded JPEG string.

    Resizes if larger than max_size to reduce API costs and latency.

    Args:
        img: PIL.Image object
        max_size: Maximum dimension (width or height) in pixels
        quality: JPEG quality (1-100)

    Returns:
        Base64-encoded string, or empty string on failure.
    """
    if img is None:
        return ""
    try:
        # Resize if too large (maintain aspect ratio)
        w, h = img.size
        if max(w, h) > max_size:
            ratio = max_size / max(w, h)
            new_w = int(w * ratio)
            new_h = int(h * ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)

        # Convert to JPEG bytes
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception as e:
        print(f"[ScreenCapture] Image encoding error: {e}")
        return ""


def get_coding_analysis_prompt(language="English"):
    """Get the system prompt for analyzing coding interview screenshots.

    Args:
        language: Language for the response.

    Returns:
        System prompt string.
    """
    return (
        f"You are an expert coding interview assistant. "
        f"Analyze the coding problem shown in the screenshot and provide a solution. "
        f"ALWAYS respond in {language}.\n\n"
        f"Structure your response as follows:\n"
        f"1. **Problem Summary** — Brief restatement of the problem\n"
        f"2. **Approach** — Explain the optimal algorithm/strategy\n"
        f"3. **Solution** — Complete, clean code solution\n"
        f"4. **Complexity** — Time and space complexity analysis\n"
        f"5. **Edge Cases** — Key edge cases to consider\n\n"
        f"Be concise but thorough. Use the programming language shown in the problem, "
        f"or Python if no language is specified."
    )


def get_general_screen_prompt(language="English"):
    """Get the system prompt for analyzing general screen content.

    Args:
        language: Language for the response.

    Returns:
        System prompt string.
    """
    return (
        f"You are a helpful AI assistant analyzing a screenshot from a job interview. "
        f"ALWAYS respond in {language}.\n\n"
        f"Describe what you see on screen and provide helpful context. "
        f"If it's a question or problem, provide a clear, concise answer. "
        f"If it's a diagram or architecture, explain the components and relationships."
    )


def analyze_screenshot(provider, img, language="English", mode="coding",
                       topic="", callback_start=None, callback_token=None,
                       callback_done=None):
    """Analyze a screenshot using a vision-capable LLM provider.

    This runs synchronously — call from a thread if needed.

    Args:
        provider: An AI provider instance with analyze_image() support.
        img: PIL.Image to analyze.
        language: Response language.
        mode: "coding" or "general" — determines the analysis prompt.
        topic: Optional topic context.
        callback_start: Called with (prompt_text) when analysis begins.
        callback_token: Called with (token) for each streamed token.
        callback_done: Called with (prompt_text, full_answer) when complete.

    Returns:
        Full analysis text, or error message.
    """
    if not provider:
        return "Error: No vision provider configured."

    if not hasattr(provider, 'analyze_image') or not provider.supports_vision():
        return "Error: Selected provider does not support image analysis."

    # Encode image
    b64 = image_to_base64(img)
    if not b64:
        return "Error: Failed to encode screenshot."

    # Select prompt based on mode
    if mode == "coding":
        system_prompt = get_coding_analysis_prompt(language)
    else:
        system_prompt = get_general_screen_prompt(language)

    if topic:
        system_prompt += f"\n\nContext topic: {topic}"

    prompt_text = "[Screenshot Analysis]"

    # Signal start
    if callback_start:
        callback_start(prompt_text)

    try:
        full_answer = ""
        for token in provider.analyze_image(b64, system_prompt):
            full_answer += token
            if callback_token:
                callback_token(token)

        if callback_done:
            callback_done(prompt_text, full_answer.strip())

        return full_answer.strip()
    except Exception as e:
        error_msg = f"Error analyzing screenshot: {e}"
        if callback_done:
            callback_done(prompt_text, error_msg)
        return error_msg


def analyze_screenshot_async(provider, img, language="English", mode="coding",
                             topic="", callback_start=None, callback_token=None,
                             callback_done=None):
    """Non-blocking version of analyze_screenshot — runs in a daemon thread."""
    thread = threading.Thread(
        target=analyze_screenshot,
        args=(provider, img, language, mode, topic,
              callback_start, callback_token, callback_done),
        daemon=True
    )
    thread.start()
    return thread
