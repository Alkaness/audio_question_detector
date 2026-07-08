#!/usr/bin/env python3
"""
Audio Question Detector — GUI Application
Cross-platform: auto-detects Linux/Windows for hotkeys, audio sources, and stealth.
Multi-window architecture: Config → Test Mode / Overlay Mode
"""

import sys, os, time, queue, threading, subprocess, re
import wave, json, platform
from io import BytesIO
from datetime import datetime
from pathlib import Path
import requests  # For auto-update check

# Process name masking (optional stealth feature)
try:
    import setproctitle
    SETPROCTITLE_AVAILABLE = True
except ImportError:
    SETPROCTITLE_AVAILABLE = False

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QTextEdit, QGroupBox, QMessageBox,
                             QLineEdit, QDialog, QScrollArea, QCheckBox,
                             QRubberBand, QSystemTrayIcon, QMenu, QAction,
                             QFileDialog, QSplitter, QTextBrowser)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint, QRect, QSize, QUrl
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette, QPainter, QPen, QDesktopServices, QIcon, QPixmap

import sounddevice as sd
import numpy as np
from dotenv import load_dotenv
from providers import get_provider, PROVIDER_NAMES, TRANSCRIPTION_PROVIDERS, ANSWER_PROVIDERS
from styles import COLORS, get_stylesheet, apply_theme_palette
from modern_widgets import ModernButton, ModernInput, ModernToggle, ModernCard, ModernComboBox, ModernDialog
from languages import get_language_names, get_question_words, get_all_question_words
from context_manager import (load_context, save_context, parse_resume,
                             build_context_prompt, get_resume_summary, get_jd_summary)
import screen_capture

IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MACOS = platform.system() == 'Darwin'

# Platform-specific hotkey backend
EVDEV_AVAILABLE = False
PYNPUT_AVAILABLE = False
WIN32_AVAILABLE = False
OBJC_AVAILABLE = False

if IS_LINUX:
    try:
        import evdev
        from evdev import ecodes
        EVDEV_AVAILABLE = True
    except ImportError:
        print("Warning: evdev not installed. Hotkeys disabled. Install: pip install evdev")
else:
    # Windows and macOS both use pynput
    try:
        from pynput import keyboard as pynput_keyboard
        PYNPUT_AVAILABLE = True
    except ImportError:
        print("Warning: pynput not installed. Hotkeys disabled. Install: pip install pynput")

# Windows screen capture exclusion API
if IS_WINDOWS:
    import ctypes
    try:
        user32 = ctypes.windll.user32
        WDA_EXCLUDEFROMCAPTURE = 0x00000011
        WIN32_AVAILABLE = True
    except AttributeError:
        pass

# macOS screen capture exclusion via PyObjC
if IS_MACOS:
    try:
        from AppKit import NSApplication, NSWindow
        OBJC_AVAILABLE = True
    except ImportError:
        print("Warning: pyobjc not installed. Screen capture exclusion disabled.")
        print("Install: pip install pyobjc-framework-Cocoa")

# WebRTC VAD for better speech detection
WEBRTC_VAD_AVAILABLE = False
try:
    import webrtcvad
    WEBRTC_VAD_AVAILABLE = True
except ImportError:
    pass  # Falls back to RMS-based VAD

# History and config file paths
HISTORY_FILE = Path.home() / ".audio_detector_history.json"
CONFIG_FILE = Path.home() / ".audio_detector_config.json"
APP_VERSION = "2.0.0"
GITHUB_REPO = "Alkaness/audio_question_detector"

# Load API keys from .env
load_dotenv()
GROQ_API_KEY = os.getenv('GROQ_API_KEY', '')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

API_KEYS = {
    "groq": GROQ_API_KEY,
    "openai": OPENAI_API_KEY,
    "ollama": None,  # No API key needed
}


def load_config():
    """Load saved settings from config file."""
    defaults = {
        "language": "English",
        "topic": "",
        "whisper_prompt": "",
        "font_size": 16,
        "theme": "dark",
        "minimize_to_tray": True,
        "transcription_provider": "groq",
        "answer_provider": "groq",
        "overlay_geometry": None,  # None = fullscreen
        "source_name": None,
        "interview_mode": "coding",  # "coding" or "non-coding"
        "show_all_transcriptions": True,
        "overlay_opacity": 0.85,
    }
    try:
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
            defaults.update(saved)
    except Exception:
        pass
    return defaults


def save_config(config):
    """Save settings to config file."""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# Load env (providers already loaded keys above)

# Settings
SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 0.01

# VAD-based chunking parameters
MIN_CHUNK_DURATION = 2
MAX_CHUNK_DURATION = 15
SILENCE_DURATION = 0.6
SILENCE_WINDOW = 0.05
VAD_THRESHOLD = 0.008

# Whisper prompt (default — can be overridden in config)
DEFAULT_WHISPER_PROMPT = (
    "Big Data, Python, JavaScript, TypeScript, React, Angular, Vue, Node.js, "
    "REST API, GraphQL, Docker, Kubernetes, DevOps, CI/CD, Git, GitHub, "
    "Machine Learning, Deep Learning, Neural Network, TensorFlow, PyTorch, "
    "SQL, NoSQL, MongoDB, PostgreSQL, Redis, AWS, Azure, Google Cloud, "
    "microservices, framework, backend, frontend, deploy, refactoring, "
    "algorithm, recursion, sprint, scrum, agile, waterfall"
)

QUESTION_WORDS = get_all_question_words()



# ═══════════════════════════════════════════════════════════════
# Worker (unchanged from previous version)
# ═══════════════════════════════════════════════════════════════

class WorkerSignals(QObject):
    """Signals for GUI communication"""
    log = pyqtSignal(str, str)
    question = pyqtSignal(str, str)          # legacy: final Q&A (used for history)
    answer_start = pyqtSignal(str)           # streaming: question text, starts answer block
    answer_token = pyqtSignal(str)           # streaming: one token at a time
    answer_done = pyqtSignal(str, str)       # streaming: final (question, full_answer)
    transcription = pyqtSignal(str, bool)    # live transcript: (text, is_question)


def is_image_black(img):
    if img is None:
        return True
    try:
        extrema = img.convert("L").getextrema()
        return extrema[1] == 0
    except Exception:
        return False


class ScreenAnalysisWorker(QObject):
    """Helper to run screen capture analysis on a background thread and emit signals safely."""
    sig_start = pyqtSignal(str)
    sig_token = pyqtSignal(str)
    sig_done = pyqtSignal(str, str)

    def __init__(self, provider, img, language, mode, topic):
        super().__init__()
        self.provider = provider
        self.img = img
        self.language = language
        self.mode = mode
        self.topic = topic

    def run(self):
        screen_capture.analyze_screenshot(
            provider=self.provider,
            img=self.img,
            language=self.language,
            mode=self.mode,
            topic=self.topic,
            callback_start=self.sig_start.emit,
            callback_token=self.sig_token.emit,
            callback_done=self.sig_done.emit
        )




class AudioDetectorWorker:
    """Worker for audio processing in a separate thread"""

    def __init__(self, device_index, signals, sample_rate=SAMPLE_RATE, language="Ukrainian", topic="", whisper_prompt="", transcription_provider=None, answer_provider=None, context_prompt="", mode="coding"):
        self.device_index = device_index
        self.signals = signals
        self.sample_rate = sample_rate
        self.is_running = False
        self.transcription_provider = transcription_provider
        self.answer_provider = answer_provider
        self.audio_queue = queue.Queue()
        self.last_transcription = ""
        self.conversation_history = []
        self.language = language
        self.topic = topic
        self.context_prompt = context_prompt  # Resume + JD context
        self.mode = mode  # "coding" or "non-coding"
        self.whisper_prompt = whisper_prompt.strip() if whisper_prompt else DEFAULT_WHISPER_PROMPT

        # WebRTC VAD (if available)
        self._vad = None
        if WEBRTC_VAD_AVAILABLE:
            try:
                self._vad = webrtcvad.Vad(2)  # aggressiveness 0-3 (2 = balanced)
                self.signals.log.emit("Using WebRTC VAD (ML-based speech detection)", "success")
            except Exception:
                pass

        # Cached VAD parameters (computed once)
        self._min_frames = int(sample_rate * MIN_CHUNK_DURATION)
        self._max_frames = int(sample_rate * MAX_CHUNK_DURATION)
        self._silence_frames = int(sample_rate * SILENCE_DURATION)
        self._window_frames = int(sample_rate * SILENCE_WINDOW)

    def audio_callback(self, indata, frames, time_info, status):
        if status:
            self.signals.log.emit(f"Audio status: {status}", "warning")
        self.audio_queue.put(indata.copy())

    def save_audio_to_wav(self, audio_data, sample_rate):
        buf = BytesIO()
        with wave.open(buf, 'wb') as wav_file:
            wav_file.setnchannels(CHANNELS)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())
        buf.seek(0)
        return buf

    def transcribe_audio(self, audio_data):
        try:
            wav_buffer = self.save_audio_to_wav(audio_data, self.sample_rate)
            wav_buffer.name = "audio.wav"
            prompt = self.whisper_prompt
            if self.last_transcription:
                prev_context = self.last_transcription[-200:]
                prompt = prev_context + " " + self.whisper_prompt[:100]
            result = self.transcription_provider.transcribe(wav_buffer, prompt=prompt)
            if result:
                self.last_transcription = result
            return result
        except Exception as e:
            self.signals.log.emit(f"Transcription error: {e}", "error")
            return ""

    def correct_transcription(self, raw_text):
        try:
            corrected = self.transcription_provider.correct_text(raw_text)
            if len(corrected) > len(raw_text) * 1.5 or len(corrected) < len(raw_text) * 0.5:
                self.signals.log.emit("Correction rejected (change too large)", "warning")
                return raw_text
            return corrected
        except Exception as e:
            self.signals.log.emit(f"Correction error: {e}", "warning")
            return raw_text


    def is_question(self, text):
        """Check if transcription is likely a question."""
        if not text or len(text.strip()) < 5:
            return False
        text_lower = text.lower().strip()
        # Check for question mark
        if text.strip().endswith('?'):
            return True
        # Check for question words at start of sentence
        first_word = text_lower.split()[0] if text_lower.split() else ""
        if first_word in QUESTION_WORDS:
            return True
        # Check for question words anywhere (weaker signal, but still useful)
        words = set(text_lower.split())
        if words & set(QUESTION_WORDS):
            return True
        return False

    def answer_question(self, question):
        """Generate answer with streaming tokens."""
        try:
            topic_ctx = ""
            if self.topic:
                topic_ctx = f"The conversation topic is: {self.topic}. Focus your answers on this domain. "
            system_prompt = (
                f"You are a helpful AI assistant that answers any questions. "
                f"ALWAYS respond in {self.language}, even if the question is in another language. "
                f"{topic_ctx}"
                f"Give concise, clear answers (2-3 sentences maximum). "
                f"If the question is about technology/programming, you may include a code example. "
                f"Explain in simple terms so the person can quickly understand and respond in conversation. "
                f"Take into account the context of previous questions and answers in the conversation."
            )
            # Inject resume/JD context if available
            if self.context_prompt:
                system_prompt += "\n" + self.context_prompt
            messages = [{"role": "system", "content": system_prompt}]
            for prev_q, prev_a in self.conversation_history[-10:]:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_a})
            messages.append({"role": "user", "content": question})

            # Signal UI to prepare answer block
            self.signals.answer_start.emit(question)

            # Streaming response via provider
            full_answer = ""
            for token in self.answer_provider.answer_stream(messages):
                full_answer += token
                self.signals.answer_token.emit(token)

            answer = full_answer.strip()

            self.conversation_history.append((question, answer))
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]
            self._save_to_history(question, answer)

            # Signal UI that answer is complete (for confidence badge update)
            self.signals.answer_done.emit(question, answer)
            return answer
        except Exception as e:
            self.signals.log.emit(f"Answer generation error: {e}", "error")
            return "Sorry, could not generate an answer."

    def _save_to_history(self, question, answer):
        """Append Q&A to history JSON file (with file locking)."""
        try:
            history = []
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    try:
                        history = json.load(f)
                    except json.JSONDecodeError:
                        history = []  # Corrupted file, start fresh
            history.append({
                "timestamp": datetime.now().isoformat(),
                "question": question,
                "answer": answer,
                "language": self.language,
                "topic": self.topic
            })
            # Write atomically: write to temp, then rename
            tmp_file = HISTORY_FILE.with_suffix('.tmp')
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            tmp_file.replace(HISTORY_FILE)
        except Exception:
            pass  # Don't break detection over history file errors

    def has_speech(self, audio_data):
        """Detect speech using WebRTC VAD (preferred) or RMS fallback."""
        if self._vad and WEBRTC_VAD_AVAILABLE:
            return self._has_speech_webrtcvad(audio_data)
        # RMS fallback
        rms = np.sqrt(np.dot(audio_data, audio_data) / len(audio_data))
        return rms > SILENCE_THRESHOLD

    def _has_speech_webrtcvad(self, audio_data):
        """WebRTC VAD: check if audio contains speech.
        webrtcvad requires 16-bit PCM at 8/16/32/48 kHz in 10/20/30ms frames.
        """
        try:
            # Convert float32 to int16 PCM
            audio_int16 = np.clip(audio_data * 32767, -32768, 32767).astype(np.int16)
            pcm_bytes = audio_int16.tobytes()
            # Frame size: 30ms at sample_rate
            frame_size = int(self.sample_rate * 0.03)  # 30ms
            frame_bytes = frame_size * 2  # 16-bit = 2 bytes per sample
            speech_frames = 0
            total_frames = 0
            for i in range(0, len(pcm_bytes) - frame_bytes, frame_bytes):
                frame = pcm_bytes[i:i + frame_bytes]
                if len(frame) == frame_bytes:
                    total_frames += 1
                    if self._vad.is_speech(frame, self.sample_rate):
                        speech_frames += 1
            if total_frames == 0:
                return False
            # Speech if >15% of frames contain speech
            return (speech_frames / total_frames) > 0.15
        except Exception:
            # Fallback to RMS
            rms = np.sqrt(np.dot(audio_data, audio_data) / len(audio_data))
            return rms > SILENCE_THRESHOLD

    def detect_silence_split(self, buffer):
        buf_len = len(buffer)
        if buf_len < self._min_frames:
            return None
        search_start = self._min_frames
        search_end = buf_len - self._silence_frames
        if search_start >= search_end:
            return None
        # Use np.dot for faster RMS
        pos = search_start
        sf = self._silence_frames
        wf = self._window_frames
        threshold_sq = VAD_THRESHOLD * VAD_THRESHOLD  # Compare squares, skip sqrt
        while pos < search_end:
            window = buffer[pos:pos + sf]
            mean_sq = np.dot(window, window) / sf
            if mean_sq < threshold_sq:
                return pos + sf
            pos += wf
        return None

    def process_chunk(self, chunk):
        if not self.has_speech(chunk):
            return
        chunk_duration = len(chunk) / self.sample_rate
        self.signals.log.emit(f"Processing audio ({chunk_duration:.1f}s)...", "info")
        raw_transcription = self.transcribe_audio(chunk)
        if not raw_transcription:
            return
        self.signals.log.emit(f"Raw text: {raw_transcription}", "info")
        transcription = self.correct_transcription(raw_transcription)
        if transcription != raw_transcription:
            self.signals.log.emit(f"Corrected: {transcription}", "success")
        self.signals.log.emit(f"Transcription: {transcription}", "info")
        is_q = self.is_question(transcription)
        # Emit live transcription for all speech (not just questions)
        self.signals.transcription.emit(transcription, is_q)
        if is_q:
            self.signals.log.emit("Generating answer...", "info")
            self.answer_question(transcription)  # streaming signals handle UI updates

    def run(self):
        self.is_running = True
        self.signals.log.emit(f"Starting capture from device {self.device_index}", "success")
        self.signals.log.emit(f"Sample rate: {self.sample_rate} Hz | VAD: {MIN_CHUNK_DURATION}-{MAX_CHUNK_DURATION}s", "info")
        try:
            with sd.InputStream(
                device=self.device_index,
                channels=CHANNELS,
                samplerate=self.sample_rate,
                callback=self.audio_callback,
                blocksize=int(self.sample_rate * 0.1)
            ):
                # List instead of np.append — O(1) append instead of O(n) copy
                buffer_chunks = []
                buffer_len = 0

                while self.is_running:
                    try:
                        audio_data = self.audio_queue.get(timeout=1.0)
                        flat = audio_data.flatten()
                        buffer_chunks.append(flat)
                        buffer_len += len(flat)

                        # Concatenate only when VAD check is needed
                        if buffer_len >= self._min_frames:
                            buffer = np.concatenate(buffer_chunks)
                            split_point = self.detect_silence_split(buffer)

                            if split_point is not None:
                                chunk = buffer[:split_point]
                                rest = buffer[split_point:]
                                buffer_chunks = [rest] if len(rest) > 0 else []
                                buffer_len = len(rest)
                                self.process_chunk(chunk)
                            elif buffer_len >= self._max_frames:
                                self.signals.log.emit("Forced split (max duration)", "warning")
                                chunk = buffer[:self._max_frames]
                                rest = buffer[self._max_frames:]
                                buffer_chunks = [rest] if len(rest) > 0 else []
                                buffer_len = len(rest)
                                self.process_chunk(chunk)
                            else:
                                # Keep merged buffer for next iteration
                                buffer_chunks = [buffer]
                    except queue.Empty:
                        continue
        except Exception as e:
            self.signals.log.emit(f"Error: {e}", "error")
        finally:
            self.is_running = False
            self.signals.log.emit("Capture stopped", "info")

    def stop(self):
        self.is_running = False


# ═══════════════════════════════════════════════════════════════
# Hotkey Manager (cross-platform: evdev on Linux, pynput on Windows)
# ═══════════════════════════════════════════════════════════════

class HotkeyManager:
    """Global hotkey manager with double-press detection (cross-platform)"""

    def __init__(self):
        self.last_f1_time = 0.0
        self.last_f2_time = 0.0
        self.last_f3_time = 0.0
        self.last_f4_time = 0.0
        self.last_f6_time = 0.0
        self.last_f7_time = 0.0
        self.last_f8_time = 0.0
        self.last_f9_time = 0.0
        self.last_f10_time = 0.0
        self.last_f11_time = 0.0
        self.last_f12_time = 0.0
        self.on_double_f1 = None
        self.on_double_f2 = None
        self.on_double_f3 = None
        self.on_double_f4 = None  # Copy to clipboard
        self.on_double_f6 = None  # Screen capture
        self.on_double_f7 = None  # Opacity up
        self.on_double_f8 = None  # Opacity down
        self.on_double_f9 = None  # Font size up
        self.on_double_f10 = None  # Font size down
        self.on_double_f11 = None  # Scroll up
        self.on_double_f12 = None  # Scroll down
        self._thread = None
        self._running = False
        self._listener = None  # pynput listener (Windows/macOS)

    # ── Linux (evdev) ──
    def _find_keyboards(self):
        """Find keyboards in /dev/input/ (Linux only)"""
        keyboards = []
        try:
            for path in evdev.list_devices():
                device = evdev.InputDevice(path)
                caps = device.capabilities(verbose=False)
                if ecodes.EV_KEY in caps:
                    key_caps = caps[ecodes.EV_KEY]
                    if ecodes.KEY_F1 in key_caps and ecodes.KEY_F2 in key_caps:
                        keyboards.append(device)
        except Exception:
            pass
        return keyboards

    def _listen_loop_evdev(self):
        """Main keyboard listener loop — Linux evdev"""
        keyboards = self._find_keyboards()
        if not keyboards:
            print("[HotkeyManager] No keyboards found. Add user to input group:", flush=True)
            print("  sudo usermod -aG input $USER", flush=True)
            print("  Then log out and log back in.", flush=True)
            return
        print(f"[HotkeyManager] Found {len(keyboards)} keyboards. F1x2=hide, F2x2=show, F3x2=quit", flush=True)
        import select as sel
        while self._running:
            try:
                r, _, _ = sel.select(keyboards, [], [], 0.1)
                for device in r:
                    for event in device.read():
                        if event.type == ecodes.EV_KEY and event.value == 1:
                            self._handle_key_evdev(event.code)
            except Exception:
                continue

    def _handle_key_evdev(self, code):
        """Handle evdev key press (Linux)"""
        now = time.time()
        if code == ecodes.KEY_F1:
            if now - self.last_f1_time < 0.4:
                if self.on_double_f1: self.on_double_f1()
                self.last_f1_time = 0.0
            else: self.last_f1_time = now
        elif code == ecodes.KEY_F2:
            if now - self.last_f2_time < 0.4:
                if self.on_double_f2: self.on_double_f2()
                self.last_f2_time = 0.0
            else: self.last_f2_time = now
        elif code == ecodes.KEY_F3:
            if now - self.last_f3_time < 0.4:
                if self.on_double_f3: self.on_double_f3()
                self.last_f3_time = 0.0
            else: self.last_f3_time = now
        elif code == ecodes.KEY_F4:
            if now - self.last_f4_time < 0.4:
                if self.on_double_f4: self.on_double_f4()
                self.last_f4_time = 0.0
            else: self.last_f4_time = now
        elif code == ecodes.KEY_F6:
            if now - self.last_f6_time < 0.4:
                if self.on_double_f6: self.on_double_f6()
                self.last_f6_time = 0.0
            else: self.last_f6_time = now
        elif code == ecodes.KEY_F7:
            if now - self.last_f7_time < 0.4:
                if self.on_double_f7: self.on_double_f7()
                self.last_f7_time = 0.0
            else: self.last_f7_time = now
        elif code == ecodes.KEY_F8:
            if now - self.last_f8_time < 0.4:
                if self.on_double_f8: self.on_double_f8()
                self.last_f8_time = 0.0
            else: self.last_f8_time = now
        elif code == ecodes.KEY_F9:
            if now - self.last_f9_time < 0.4:
                if self.on_double_f9: self.on_double_f9()
                self.last_f9_time = 0.0
            else: self.last_f9_time = now
        elif code == ecodes.KEY_F10:
            if now - self.last_f10_time < 0.4:
                if self.on_double_f10: self.on_double_f10()
                self.last_f10_time = 0.0
            else: self.last_f10_time = now
        elif code == ecodes.KEY_F11:
            if now - self.last_f11_time < 0.4:
                if self.on_double_f11: self.on_double_f11()
                self.last_f11_time = 0.0
            else: self.last_f11_time = now
        elif code == ecodes.KEY_F12:
            if now - self.last_f12_time < 0.4:
                if self.on_double_f12: self.on_double_f12()
                self.last_f12_time = 0.0
            else: self.last_f12_time = now

    # ── Windows (pynput) ──
    def _on_key_press_pynput(self, key):
        """Handle pynput key press (Windows/macOS)"""
        now = time.time()
        try:
            if key == pynput_keyboard.Key.f1:
                if now - self.last_f1_time < 0.4:
                    if self.on_double_f1: self.on_double_f1()
                    self.last_f1_time = 0.0
                else: self.last_f1_time = now
            elif key == pynput_keyboard.Key.f2:
                if now - self.last_f2_time < 0.4:
                    if self.on_double_f2: self.on_double_f2()
                    self.last_f2_time = 0.0
                else: self.last_f2_time = now
            elif key == pynput_keyboard.Key.f3:
                if now - self.last_f3_time < 0.4:
                    if self.on_double_f3: self.on_double_f3()
                    self.last_f3_time = 0.0
                else: self.last_f3_time = now
            elif key == pynput_keyboard.Key.f4:
                if now - self.last_f4_time < 0.4:
                    if self.on_double_f4: self.on_double_f4()
                    self.last_f4_time = 0.0
                else: self.last_f4_time = now
            elif key == pynput_keyboard.Key.f6:
                if now - self.last_f6_time < 0.4:
                    if self.on_double_f6: self.on_double_f6()
                    self.last_f6_time = 0.0
                else: self.last_f6_time = now
            elif key == pynput_keyboard.Key.f7:
                if now - self.last_f7_time < 0.4:
                    if self.on_double_f7: self.on_double_f7()
                    self.last_f7_time = 0.0
                else: self.last_f7_time = now
            elif key == pynput_keyboard.Key.f8:
                if now - self.last_f8_time < 0.4:
                    if self.on_double_f8: self.on_double_f8()
                    self.last_f8_time = 0.0
                else: self.last_f8_time = now
            elif key == pynput_keyboard.Key.f9:
                if now - self.last_f9_time < 0.4:
                    if self.on_double_f9: self.on_double_f9()
                    self.last_f9_time = 0.0
                else: self.last_f9_time = now
            elif key == pynput_keyboard.Key.f10:
                if now - self.last_f10_time < 0.4:
                    if self.on_double_f10: self.on_double_f10()
                    self.last_f10_time = 0.0
                else: self.last_f10_time = now
            elif key == pynput_keyboard.Key.f11:
                if now - self.last_f11_time < 0.4:
                    if self.on_double_f11: self.on_double_f11()
                    self.last_f11_time = 0.0
                else: self.last_f11_time = now
            elif key == pynput_keyboard.Key.f12:
                if now - self.last_f12_time < 0.4:
                    if self.on_double_f12: self.on_double_f12()
                    self.last_f12_time = 0.0
                else: self.last_f12_time = now
        except AttributeError:
            pass

    # ── Cross-platform start/stop ──
    def start(self):
        if IS_LINUX and EVDEV_AVAILABLE:
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop_evdev, daemon=True)
            self._thread.start()
        elif (IS_WINDOWS or IS_MACOS) and PYNPUT_AVAILABLE:
            self._listener = pynput_keyboard.Listener(on_press=self._on_key_press_pynput)
            self._listener.daemon = True
            self._listener.start()
            print("[HotkeyManager] pynput listener started. F1-F4, F9-F10 hotkeys active", flush=True)

    def stop(self):
        self._running = False
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._thread = None


# ═══════════════════════════════════════════════════════════════
# Helper: get audio sources (pactl on Linux, sounddevice on Windows)
# ═══════════════════════════════════════════════════════════════

def get_audio_sources():
    """Get list of audio sources — cross-platform"""
    if IS_LINUX:
        return _get_audio_sources_linux()
    else:
        # Windows and macOS both use sounddevice
        return _get_audio_sources_windows()

def _get_audio_sources_linux():
    """Linux: get sources via pactl"""
    monitor_devices = []
    input_devices = []
    try:
        result = subprocess.run(['pactl', 'list', 'sources', 'short'],
                                capture_output=True, text=True, check=True)
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = line.split('\t')
                if len(parts) >= 2:
                    source_name = parts[1]
                    if 'monitor' in source_name.lower():
                        if 'alsa_output' in source_name:
                            friendly = "System Audio (Monitor)"
                        elif 'call_monitor' in source_name:
                            friendly = "Virtual Monitor"
                        else:
                            friendly = source_name
                        monitor_devices.append((friendly, source_name))
                    elif 'input' in source_name.lower() or 'mic' in source_name.lower():
                        friendly = "Microphone" if 'alsa_input' in source_name else source_name
                        input_devices.append((friendly, source_name))
    except Exception:
        pass
    return monitor_devices + input_devices

def _get_audio_sources_windows():
    """Windows: get sources via sounddevice"""
    devices = []
    try:
        for i, dev in enumerate(sd.query_devices()):
            if dev['max_input_channels'] > 0:
                name = dev['name']
                # Prefer loopback/stereo mix for system audio
                if any(kw in name.lower() for kw in ['stereo mix', 'loopback', 'what u hear']):
                    devices.insert(0, (f"System Audio ({name})", i))
                else:
                    devices.append((name, i))
    except Exception:
        pass
    return devices


class ScreenSelector(QWidget):
    """Custom transparent overlay to select a screen region for vision LLM analysis"""
    def __init__(self, callback):
        super().__init__()
        self.callback = callback
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setCursor(Qt.CrossCursor)
        self.start_pos = QPoint()
        self.current_pos = QPoint()
        self.is_selecting = False
        
        # Cover the entire virtual desktop for multi-monitor support
        self.setGeometry(QApplication.desktop().geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        # Semi-transparent dark background
        painter.fillRect(self.rect(), QColor(15, 15, 15, 180))

        # Instructions banner at the top-center
        painter.setRenderHint(QPainter.Antialiasing)
        instructions = "Drag a box around the question | Escape/Right-click to Cancel"
        font = QFont("Segoe UI", 12, QFont.DemiBold)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        w = metrics.horizontalAdvance(instructions) + 40
        h = metrics.height() + 20
        banner_rect = QRect((self.width() - w) // 2, 40, w, h)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(30, 30, 30, 240))
        painter.drawRoundedRect(banner_rect, 8, 8)
        
        painter.setPen(QColor("#0A84FF"))
        painter.drawText(banner_rect, Qt.AlignCenter, instructions)

        # Selection rectangle
        if self.is_selecting and not self.start_pos.isNull() and not self.current_pos.isNull():
            rect = QRect(self.start_pos, self.current_pos).normalized()
            
            # Punch a hole in the overlay
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            
            # Draw premium border
            painter.setPen(QPen(QColor("#0A84FF"), 2))
            painter.drawRect(rect)
            
            # Draw size text box
            size_text = f"{rect.width()} x {rect.height()}"
            font_size = QFont("Segoe UI", 9)
            painter.setFont(font_size)
            sz_metrics = painter.fontMetrics()
            sz_w = sz_metrics.horizontalAdvance(size_text) + 16
            sz_h = sz_metrics.height() + 8
            
            sz_y = rect.bottom() + 5 if rect.bottom() + sz_h + 5 < self.height() else rect.top() - sz_h - 5
            sz_rect = QRect(rect.right() - sz_w, sz_y, sz_w, sz_h)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(15, 15, 15, 220))
            painter.drawRoundedRect(sz_rect, 4, 4)
            
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(sz_rect, Qt.AlignCenter, size_text)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.current_pos = event.pos()
            self.is_selecting = True
            self.update()
        elif event.button() == Qt.RightButton:
            self.close()
            self.callback(None)

    def mouseMoveEvent(self, event):
        if self.is_selecting:
            self.current_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.is_selecting:
            self.is_selecting = False
            rect = QRect(self.start_pos, self.current_pos).normalized()
            self.close()
            
            # capture region after window has closed to avoid capturing the selector itself
            QTimer.singleShot(100, lambda: self.capture_region(rect))

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            self.callback(None)
        super().keyPressEvent(event)

    def capture_region(self, rect):
        if rect.width() > 5 and rect.height() > 5:
            global_pos = self.mapToGlobal(rect.topLeft())
            x = global_pos.x()
            y = global_pos.y()
            w = rect.width()
            h = rect.height()
            
            img = screen_capture.capture_region(x, y, w, h)
            self.callback(img)
        else:
            self.callback(None)


# ═══════════════════════════════════════════════════════════════
# Window 1: Configuration (Entry Point)
# ═══════════════════════════════════════════════════════════════

class AreaSelectionWindow(QWidget):
    """Transparent overlay for selecting screen area"""
    def __init__(self, parent=None):
        super().__init__()
        self.parent_config = parent
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowState(Qt.WindowFullScreen)
        self.setCursor(Qt.CrossCursor)
        self.rubberband = QRubberBand(QRubberBand.Rectangle, self)
        self.origin = QPoint()
        self.setGeometry(QApplication.primaryScreen().geometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 100))  # Dim background

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.origin = event.pos()
            self.rubberband.setGeometry(QRect(self.origin, QSize()))
            self.rubberband.show()
        elif event.button() == Qt.RightButton:
            self.close()
            self.parent_config.show()

    def mouseMoveEvent(self, event):
        if not self.origin.isNull():
            self.rubberband.setGeometry(QRect(self.origin, event.pos()).normalized())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            rect = self.rubberband.geometry()
            self.close()
            # Save geometry to config
            self.parent_config.config["overlay_geometry"] = [rect.x(), rect.y(), rect.width(), rect.height()]
            save_config(self.parent_config.config)
            self.parent_config.show()
            ModernDialog(
                "Area Set", 
                "Overlay area updated.\nStart Overlay Mode to see changes.",
                self.parent_config.theme, self.parent_config
            ).exec_()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()
            self.parent_config.show()

class ConfigWindow(QWidget):
    """Configuration window — application entry point"""

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.user_context = load_context()  # Resume + JD
        self.audio_sources = get_audio_sources()
        self.test_window = None
        self.overlay_window = None
        self.history_window = None
        self._force_quit = False  # True when user explicitly quits
        self.init_ui()
        self.setup_tray()
        # Wire update signal to handler
        self.update_available.connect(self.on_update_available)
        self.check_for_updates()

    def init_ui(self):
        self.setWindowTitle("Audio Question Detector — Settings")
        self.setMinimumSize(520, 820) # Taller to accommodate new controls
        self.theme = self.config.get("theme", "dark")
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 520) // 2
        y = (screen.height() - 820) // 2
        self.move(x, y)
        
        # Apply base stylesheet
        self.setStyleSheet(get_stylesheet(self.theme))

        main_layout = QVBoxLayout()
        main_layout.setSpacing(20)
        main_layout.setContentsMargins(30, 30, 30, 30)
        self.setLayout(main_layout)

        # Header
        header = QHBoxLayout()
        title = QLabel(f"Audio Detector")
        title.setObjectName("Title")
        subtitle = QLabel(f"v{APP_VERSION}")
        subtitle.setObjectName("Subtitle")
        header.addWidget(title)
        header.addWidget(subtitle)
        header.addStretch()
        
        # Theme Toggle
        self.theme_toggle = ModernToggle(self.theme)
        self.theme_toggle.setChecked(self.theme == "light")
        self.theme_toggle.stateChanged.connect(self.toggle_theme)
        header.addWidget(self.theme_toggle)
        
        main_layout.addLayout(header)

        # Settings Card
        self.settings_card = ModernCard(self.theme)
        card_layout = QVBoxLayout()
        card_layout.setSpacing(15)
        card_layout.setContentsMargins(20, 20, 20, 20)
        self.settings_card.setLayout(card_layout)

        # 1. Device Selection
        lbl = QLabel("Audio Source")
        lbl.setObjectName("Subtitle")
        card_layout.addWidget(lbl)
        
        source_row = QHBoxLayout()
        self.source_combo = ModernComboBox(self.theme)
        # self.source_combo.setFixedHeight(36) # Handled by widget
        source_row.addWidget(self.source_combo)
        
        refresh_btn = ModernButton("↻", self.theme)
        refresh_btn.setFixedWidth(40)
        refresh_btn.clicked.connect(self.refresh_sources)
        source_row.addWidget(refresh_btn)
        card_layout.addLayout(source_row)

        # 2. Interview Mode & Language Row
        row2 = QHBoxLayout()
        
        # Interview Mode (Coding / Non-Coding)
        mode_layout = QVBoxLayout()
        mode_lbl = QLabel("Interview Type")
        mode_lbl.setObjectName("Subtitle")
        mode_layout.addWidget(mode_lbl)
        
        interview_mode_row = QHBoxLayout()
        self.interview_mode_combo = ModernComboBox(self.theme)
        self.interview_mode_combo.addItems(["Coding", "Non-Coding"])
        saved_interview_mode = self.config.get("interview_mode", "coding")
        self.interview_mode_combo.setCurrentText(saved_interview_mode.capitalize())
        interview_mode_row.addWidget(self.interview_mode_combo)
        mode_layout.addLayout(interview_mode_row)
        row2.addLayout(mode_layout)

        # Display Mode
        dmode_layout = QVBoxLayout()
        dmode_lbl = QLabel("Display")
        dmode_lbl.setObjectName("Subtitle")
        dmode_layout.addWidget(dmode_lbl)
        self.mode_combo = ModernComboBox(self.theme)
        self.mode_combo.addItems(["Test Mode", "Overlay Mode"])
        dmode_layout.addWidget(self.mode_combo)
        row2.addLayout(dmode_layout)
        
        # Language (now 52 languages)
        lang_layout = QVBoxLayout()
        lang_lbl = QLabel("Language")
        lang_lbl.setObjectName("Subtitle")
        lang_layout.addWidget(lang_lbl)
        self.lang_combo = ModernComboBox(self.theme)
        langs = get_language_names()
        self.lang_combo.addItems(langs)
        saved_lang = self.config.get("language", "English")
        if saved_lang in langs:
            self.lang_combo.setCurrentText(saved_lang)
        self.lang_combo.setEditable(True)  # Type-to-filter
        self.lang_combo.setInsertPolicy(QComboBox.NoInsert)
        lang_layout.addWidget(self.lang_combo)
        row2.addLayout(lang_layout)
        
        card_layout.addLayout(row2)

        # 3. AI Provider Row
        row3 = QHBoxLayout()

        # Transcription Provider
        tp_layout = QVBoxLayout()
        tp_lbl = QLabel("Transcription")
        tp_lbl.setObjectName("Subtitle")
        tp_layout.addWidget(tp_lbl)
        self.tp_combo = ModernComboBox(self.theme)
        for key in TRANSCRIPTION_PROVIDERS:
            self.tp_combo.addItem(PROVIDER_NAMES[key], key)
        saved_tp = self.config.get("transcription_provider", "groq")
        idx = self.tp_combo.findData(saved_tp)
        if idx >= 0:
            self.tp_combo.setCurrentIndex(idx)
        tp_layout.addWidget(self.tp_combo)
        row3.addLayout(tp_layout)

        # Answer Provider
        ap_layout = QVBoxLayout()
        ap_lbl = QLabel("Answers")
        ap_lbl.setObjectName("Subtitle")
        ap_layout.addWidget(ap_lbl)
        self.ap_combo = ModernComboBox(self.theme)
        for key in ANSWER_PROVIDERS:
            self.ap_combo.addItem(PROVIDER_NAMES[key], key)
        saved_ap = self.config.get("answer_provider", "groq")
        idx = self.ap_combo.findData(saved_ap)
        if idx >= 0:
            self.ap_combo.setCurrentIndex(idx)
        ap_layout.addWidget(self.ap_combo)
        row3.addLayout(ap_layout)

        card_layout.addLayout(row3)

        # 4. Topic
        lbl_topic = QLabel("Conversation Topic")
        lbl_topic.setObjectName("Subtitle")
        card_layout.addWidget(lbl_topic)
        self.topic_input = ModernInput(self.theme)
        self.topic_input.setPlaceholderText("e.g. System Design, React Interview...")
        self.topic_input.setText(self.config.get("topic", ""))
        card_layout.addWidget(self.topic_input)

        # 4. Whisper Prompt
        lbl_whisper = QLabel("Whisper Prompt")
        lbl_whisper.setObjectName("Subtitle")
        card_layout.addWidget(lbl_whisper)
        self.whisper_input = ModernInput(self.theme)
        self.whisper_input.setPlaceholderText("Keywords to improve transcription accuracy...")
        self.whisper_input.setText(self.config.get("whisper_prompt", ""))
        card_layout.addWidget(self.whisper_input)

        # 5. Overlay Area
        self.area_btn = ModernButton("Set Overlay Area", self.theme)
        self.area_btn.clicked.connect(self.select_overlay_area)
        card_layout.addWidget(self.area_btn)

        # 6. Resume & Job Description
        context_lbl = QLabel("Personalization")
        context_lbl.setObjectName("Subtitle")
        card_layout.addWidget(context_lbl)

        resume_row = QHBoxLayout()
        self.resume_btn = ModernButton("Upload Resume", self.theme)
        self.resume_btn.clicked.connect(self.upload_resume)
        resume_row.addWidget(self.resume_btn)
        self.resume_status = QLabel(get_resume_summary(self.user_context))
        self.resume_status.setStyleSheet(f"font-size: 11px; color: {COLORS[self.theme]['text_secondary']};")
        resume_row.addWidget(self.resume_status)
        card_layout.addLayout(resume_row)

        self.jd_input = ModernInput(self.theme)
        self.jd_input.setPlaceholderText("Paste job description here...")
        self.jd_input.setText(self.user_context.get("job_description", ""))
        card_layout.addWidget(self.jd_input)

        # 7. Minimize to tray toggle
        self.tray_toggle = QCheckBox("Minimize to tray on close")
        self.tray_toggle.setChecked(self.config.get("minimize_to_tray", True))
        self.tray_toggle.stateChanged.connect(self._on_tray_toggle)
        card_layout.addWidget(self.tray_toggle)

        # 8. Show all transcriptions toggle
        self.show_transcriptions_toggle = QCheckBox("Show all transcriptions (live transcript)")
        self.show_transcriptions_toggle.setChecked(self.config.get("show_all_transcriptions", True))
        card_layout.addWidget(self.show_transcriptions_toggle)

        main_layout.addWidget(self.settings_card)
        main_layout.addStretch()

        # Action Buttons
        self.start_btn = ModernButton("Start Detection", self.theme, accent=True)
        self.start_btn.setFixedHeight(50)
        self.start_btn.clicked.connect(self.launch_mode)
        main_layout.addWidget(self.start_btn)
        
        bottom_row = QHBoxLayout()
        self.history_btn = ModernButton("History", self.theme)
        self.history_btn.clicked.connect(self.show_history)
        bottom_row.addWidget(self.history_btn)
        
        self.github_btn = ModernButton("GitHub", self.theme)
        self.github_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(f"https://github.com/{GITHUB_REPO}")))
        bottom_row.addWidget(self.github_btn)
        
        main_layout.addLayout(bottom_row)

        # Populate sources
        self.refresh_sources()
        saved_source = self.config.get("source_name")
        if saved_source:
             index = self.source_combo.findText(saved_source, Qt.MatchContains)
             if index >= 0:
                 self.source_combo.setCurrentIndex(index)

    def apply_theme(self, theme):
        """Update theme for window and all modern widgets"""
        self.theme = theme

        # 1. Global palette + app-level stylesheet
        apply_theme_palette(QApplication.instance(), theme)

        # 2. Re-apply this window's own stylesheet so background/labels update
        self.setStyleSheet(get_stylesheet(theme))

        # 3. Walk every child that has a 'theme' attr and refresh it
        for child in self.findChildren(QWidget):
            if hasattr(child, "theme"):
                child.theme = theme
                if hasattr(child, "update_style"):
                    child.update_style()
                else:
                    child.update()

    def toggle_theme(self, state):
        # State can be checked (2) or unchecked (0) if from stateChanged
        checked = self.theme_toggle.isChecked()
        theme = "light" if checked else "dark"
        self.config["theme"] = theme
        save_config(self.config)
        self.apply_theme(theme)

    def select_overlay_area(self):
        """Launch area selection overlay"""
        self.hide()
        self.area_selector = AreaSelectionWindow(self)
        self.area_selector.show()

    def check_for_updates(self):
        """Check GitHub for newer version"""
        def check():
            try:
                url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    data = resp.json()
                    latest_tag = data.get("tag_name", "").lstrip("v")
                    if latest_tag and latest_tag != APP_VERSION:
                        self.update_available.emit(latest_tag)
            except Exception:
                pass
        
        # Simple threading to not block UI
        threading.Thread(target=check, daemon=True).start()

    # Signal for update (hacky way to run on main thread)
    update_available = pyqtSignal(str)

    def on_update_available(self, version):
        ModernDialog(
            "Update Available",
            f"A new version ({version}) is available!\nCheck GitHub to download.",
            self.theme, self
        ).exec_()



    def refresh_sources(self):
        self.source_combo.clear()
        sources = get_audio_sources()
        for friendly, source_name in sources:
            self.source_combo.addItem(friendly, source_name)
        if not sources:
            self.source_combo.addItem("No devices found", None)

    def get_device_config(self):
        """Returns (source_name, device_index, sample_rate) or None on error"""
        source_name = self.source_combo.currentData()
        if not source_name:
            QMessageBox.warning(self, "Error", "Please select an audio source!")
            return None

        # Provider validation is done later in launch_mode when providers are instantiated

        if IS_LINUX:
            # Linux: set as default source via pactl, use default device
            try:
                subprocess.run(['pactl', 'set-default-source', source_name], check=True)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Failed to set audio source:\n{e}")
                return None
            device_index = None  # use default input after pactl set
        else:
            # Windows and macOS: source_name is already a sounddevice index (int)
            device_index = source_name

        try:
            device_info = sd.query_devices(device_index, 'input')
            sample_rate = int(device_info['default_samplerate'])
        except Exception:
            sample_rate = SAMPLE_RATE

        return source_name, device_index, sample_rate

    def launch_mode(self):
        config = self.get_device_config()
        if not config:
            return

        source_name, device_index, sample_rate = config
        mode = self.mode_combo.currentIndex()
        language = self.lang_combo.currentText()
        topic = self.topic_input.text().strip()
        whisper_prompt = self.whisper_input.text().strip()
        interview_mode = self.interview_mode_combo.currentText().lower().replace("-", "_")
        show_all_transcriptions = self.show_transcriptions_toggle.isChecked()

        # Save JD to context
        jd_text = self.jd_input.text().strip()
        if jd_text != self.user_context.get("job_description", ""):
            self.user_context["job_description"] = jd_text
            save_context(self.user_context)

        # Build context prompt from resume + JD
        context_prompt = build_context_prompt(self.user_context)

        # Save current settings
        tp_key = self.tp_combo.currentData()
        ap_key = self.ap_combo.currentData()
        self.config.update({
            "language": language,
            "topic": topic,
            "whisper_prompt": whisper_prompt,
            "source_name": self.source_combo.currentText(),
            "theme": "light" if self.theme_toggle.isChecked() else "dark",
            "transcription_provider": tp_key,
            "answer_provider": ap_key,
            "interview_mode": interview_mode,
            "show_all_transcriptions": show_all_transcriptions,
        })
        save_config(self.config)

        # Create provider instances
        try:
            tp = get_provider(tp_key, api_key=API_KEYS.get(tp_key))
        except Exception as e:
            ModernDialog("Provider Error", f"Transcription provider error:\n{e}", self.theme, self).exec_()
            return
        try:
            ap = get_provider(ap_key, api_key=API_KEYS.get(ap_key))
        except Exception as e:
            ModernDialog("Provider Error", f"Answer provider error:\n{e}", self.theme, self).exec_()
            return

        self.hide()

        if mode == 0:
            # Test Mode
            self.test_window = TestModeWindow(
                device_index, sample_rate, self, language, topic,
                self.config.get("theme", "dark"), whisper_prompt, tp, ap,
                context_prompt=context_prompt, interview_mode=interview_mode,
                show_all_transcriptions=show_all_transcriptions
            )
            self.test_window.show()
        else:
            # Overlay Mode
            self.overlay_window = OverlayWindow(
                device_index, sample_rate, self, language, topic,
                self.config, tp, ap, context_prompt=context_prompt,
                interview_mode=interview_mode
            )
            self.overlay_window.show()

    def upload_resume(self):
        """Open file dialog to upload resume (PDF, DOCX, TXT)."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Upload Resume",
            str(Path.home()),
            "Documents (*.pdf *.docx *.doc *.txt);;All Files (*)"
        )
        if not file_path:
            return

        resume_text = parse_resume(file_path)
        if resume_text.startswith("Error:") or resume_text.startswith("Unsupported"):
            ModernDialog("Resume Error", resume_text, self.theme, self).exec_()
            return

        self.user_context["resume_text"] = resume_text
        self.user_context["resume_file"] = file_path
        save_context(self.user_context)

        self.resume_status.setText(get_resume_summary(self.user_context))
        ModernDialog(
            "Resume Loaded",
            f"Successfully loaded resume.\n{get_resume_summary(self.user_context)}",
            self.theme, self
        ).exec_()

    def show_config(self):
        """Return to configuration"""
        self.show()
        self.raise_()
        self.activateWindow()

    def setup_tray(self):
        """Create system tray icon with context menu"""
        # Create a simple app icon (colored circle)
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(QColor("#0A84FF"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(4, 4, 56, 56)
        # White headphone shape
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(12, 28, 12, 16)
        painter.drawEllipse(40, 28, 12, 16)
        painter.setPen(QPen(QColor("#FFFFFF"), 3))
        painter.drawArc(16, 12, 32, 32, 30 * 16, 120 * 16)
        painter.end()
        icon = QIcon(pixmap)

        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip(f"Audio Question Detector v{APP_VERSION}")

        # Tray menu
        tray_menu = QMenu()
        show_action = QAction("Show Settings", self)
        show_action.triggered.connect(self.show_config)
        tray_menu.addAction(show_action)

        tray_menu.addSeparator()

        test_action = QAction("Start Test Mode", self)
        test_action.triggered.connect(lambda: self._tray_launch(0))
        tray_menu.addAction(test_action)

        overlay_action = QAction("Start Overlay Mode", self)
        overlay_action.triggered.connect(lambda: self._tray_launch(1))
        tray_menu.addAction(overlay_action)

        tray_menu.addSeparator()

        history_action = QAction("History", self)
        history_action.triggered.connect(self.show_history)
        tray_menu.addAction(history_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self._quit_app)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._tray_activated)
        # Only show tray icon if enabled in settings
        if self.config.get("minimize_to_tray", True):
            self.tray_icon.show()

        # Set app icon too
        self.setWindowIcon(icon)

    def _tray_activated(self, reason):
        """Handle tray icon click"""
        if reason == QSystemTrayIcon.Trigger:  # Single click
            if self.isVisible():
                self.hide()
            else:
                self.show_config()

    def _tray_launch(self, mode_index):
        """Launch detection from tray menu"""
        self.mode_combo.setCurrentIndex(mode_index)
        self.launch_mode()

    def _quit_app(self):
        """Actually quit the application"""
        self._force_quit = True
        self.tray_icon.hide()
        QApplication.quit()

    def _on_tray_toggle(self, state):
        """Save minimize-to-tray preference and show/hide tray icon"""
        enabled = self.tray_toggle.isChecked()
        self.config["minimize_to_tray"] = enabled
        save_config(self.config)
        # Show or hide the tray icon itself
        if enabled:
            self.tray_icon.show()
        else:
            self.tray_icon.hide()

    def closeEvent(self, event):
        """Minimize to tray or quit based on user preference"""
        if self._force_quit:
            event.accept()
            return
        if self.config.get("minimize_to_tray", True):
            event.ignore()
            self.hide()
            self.tray_icon.showMessage(
                "Audio Question Detector",
                "App minimized to tray. Right-click the tray icon for options.",
                QSystemTrayIcon.Information,
                2000
            )
        else:
            self._quit_app()
            event.accept()

    def show_history(self):
        """Open history window — always recreate to ensure fresh theme"""
        self.history_window = HistoryWindow(self.theme, self)
        self.history_window.show()
        self.history_window.raise_()

# ═══════════════════════════════════════════════════════════════
# Window 2: Test Mode (Standard Window)
# ═══════════════════════════════════════════════════════════════

class TestModeWindow(QMainWindow):
    """Test Mode — standard window with log, live transcript, and answers"""

    def __init__(self, device_index, sample_rate, config_window, language="English", topic="", theme="dark", whisper_prompt="", transcription_provider=None, answer_provider=None, context_prompt="", interview_mode="coding", show_all_transcriptions=True):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.language = language
        self.topic = topic
        self.theme = theme
        self.whisper_prompt = whisper_prompt
        self.transcription_provider = transcription_provider
        self.answer_provider = answer_provider
        self.context_prompt = context_prompt
        self.interview_mode = interview_mode
        self.show_all_transcriptions = show_all_transcriptions
        self.worker = None
        self.worker_thread = None
        self.init_ui()
        # Auto-start
        QTimer.singleShot(100, self.start_detection)

    def init_ui(self):
        self.setWindowTitle("Test Mode — Audio Question Detector")
        self.setGeometry(100, 100, 950, 750)
        
        self.setStyleSheet(get_stylesheet(self.theme))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        central.setLayout(layout)

        # Header + status
        header = QHBoxLayout()
        title = QLabel("Test Mode")
        title.setObjectName("Title")
        header.addWidget(title)
        
        # Mode badge
        mode_badge = QLabel(f"  {self.interview_mode.upper()}  ")
        badge_color = "#34C759" if self.interview_mode == "coding" else "#007AFF"
        mode_badge.setStyleSheet(f"background-color: {badge_color}; color: white; border-radius: 4px; font-size: 11px; font-weight: bold; padding: 2px 8px;")
        header.addWidget(mode_badge)
        
        header.addStretch()

        self.status_label = QLabel("Listening...")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 14px; font-weight: bold;")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        c = COLORS[self.theme]

        # Log (compact)
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c['input_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                font-family: 'Consolas', 'Courier New', monospace; 
                font-size: 12px;
            }}
        """)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Live Transcript (new!)
        if self.show_all_transcriptions:
            transcript_group = QGroupBox("Live Transcript")
            transcript_layout = QVBoxLayout()
            self.transcript_text = QTextEdit()
            self.transcript_text.setReadOnly(True)
            self.transcript_text.setMaximumHeight(140)
            self.transcript_text.setStyleSheet(f"""
                QTextEdit {{
                    background-color: {c['input_bg']};
                    color: {c['text_primary']};
                    border: 1px solid {c['border']};
                    border-radius: 6px;
                    font-size: 13px;
                }}
            """)
            transcript_layout.addWidget(self.transcript_text)
            transcript_group.setLayout(transcript_layout)
            layout.addWidget(transcript_group)

        # Q&A
        qa_group = QGroupBox("Conversation & Answers")
        qa_layout = QVBoxLayout()
        self.qa_text = QTextEdit()
        self.qa_text.setReadOnly(True)
        self.qa_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c['input_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 6px;
                font-size: 13px;
            }}
        """)
        qa_layout.addWidget(self.qa_text)
        qa_group.setLayout(qa_layout)
        layout.addWidget(qa_group)

        # Bottom buttons row
        btn_row = QHBoxLayout()

        # Screen Capture button (coding mode)
        if self.interview_mode == "coding" and screen_capture.is_available():
            self.capture_btn = ModernButton("📸 Capture Screen", self.theme)
            self.capture_btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: #5856D6;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    font-weight: 600;
                    padding: 10px 20px;
                    font-size: 14px;
                }}
                QPushButton:hover {{ background-color: #4B49B6; }}
            """)
            self.capture_btn.clicked.connect(self.capture_and_analyze)
            btn_row.addWidget(self.capture_btn)

        btn_row.addStretch()

        # Stop button
        self.stop_btn = ModernButton("Stop", self.theme)
        danger = COLORS[self.theme]['danger']
        self.stop_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {danger};
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                padding: 10px 30px;
                font-size: 14px;
            }}
            QPushButton:hover {{ background-color: #d32f2f; }}
        """)
        self.stop_btn.clicked.connect(self.stop_and_return)
        btn_row.addWidget(self.stop_btn)

        layout.addLayout(btn_row)

    def log_message(self, message, level="info"):
        colors = {"info": "#b0b0b0", "success": "#4CAF50", "warning": "#FF9800", "error": "#f44336"}
        color = colors.get(level, "#b0b0b0")
        self.log_text.append(f'<span style="color: {color};">{message}</span>')
        self.log_text.moveCursor(QTextCursor.End)

    def on_transcription(self, text, is_question):
        """Live transcript: show all transcribed speech."""
        if not self.show_all_transcriptions or not hasattr(self, 'transcript_text'):
            return
        c = COLORS[self.theme]
        if is_question:
            color = c['accent']
            prefix = "❓ "
        else:
            color = c['text_secondary']
            prefix = ""
        self.transcript_text.append(
            f'<span style="color: {color};">{prefix}{text}</span>'
        )
        self.transcript_text.moveCursor(QTextCursor.End)

    def add_qa(self, question, answer):
        """Add complete Q&A pair (non-streaming fallback)"""
        c = COLORS[self.theme]
        q_bg = c['input_bg']
        a_bg = c['card']
        self.qa_text.append(
            f'<div style="background-color: {q_bg}; padding: 10px; margin: 5px; border-radius: 6px; border: 1px solid {c["border"]};">' 
            f'<b style="color: {c["accent"]};">TEXT:</b> <span style="color: {c["text_primary"]};">{question}</span></div>'
        )
        self.qa_text.append(
            f'<div style="background-color: {a_bg}; padding: 10px; margin: 5px; border-radius: 6px; border: 1px solid {c["border"]};">' 
            f'<b style="color: {c["success"]};">ANSWER:</b> <span style="color: {c["text_primary"]};">{answer}</span></div><br>'
        )
        self.qa_text.moveCursor(QTextCursor.End)

    def on_answer_start(self, question):
        """Streaming: prepare question block, start empty answer"""
        c = COLORS[self.theme]
        q_bg = c['input_bg']
        self.qa_text.append(
            f'<div style="background-color: {q_bg}; padding: 10px; margin: 5px; border-radius: 6px; border: 1px solid {c["border"]};">' 
            f'<b style="color: {c["accent"]};">TEXT:</b> <span style="color: {c["text_primary"]};">{question}</span></div>'
        )
        # Start answer block with label
        c2 = COLORS[self.theme]
        a_bg = c2['card']
        self.qa_text.append(
            f'<div style="background-color: {a_bg}; padding: 10px; margin: 5px; border-radius: 6px; border: 1px solid {c2["border"]};">' 
            f'<b style="color: {c2["success"]};">ANSWER:</b> <span style="color: {c2["text_primary"]};" id="streaming">'
        )
        self._streaming_answer = ""
        self.qa_text.moveCursor(QTextCursor.End)

    def on_answer_token(self, token):
        """Streaming: append one token to current answer"""
        self._streaming_answer += token
        # Insert token at cursor position (end of document)
        cursor = self.qa_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.qa_text.setTextCursor(cursor)
        self.qa_text.ensureCursorVisible()

    def on_answer_done(self, question, answer):
        """Streaming: finalize answer block"""
        # Close the open HTML tags
        cursor = self.qa_text.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml('</span></div><br>')
        self.qa_text.moveCursor(QTextCursor.End)

    def capture_and_analyze(self):
        """Capture screen and analyze with vision LLM."""
        if not screen_capture.is_available():
            self.log_message("Screen capture not available. Install: pip install mss Pillow", "error")
            return

        # Use answer_provider for vision (if supported)
        provider = self.answer_provider
        if not provider or not provider.supports_vision():
            self.log_message("Vision provider not available. Use OpenAI or Groq provider.", "error")
            return

        self.log_message("Please select the region to analyze...", "info")
        
        # Hide TestModeWindow temporarily
        self.hide()
        QTimer.singleShot(300, lambda: self._launch_selector_test(provider))

    def _launch_selector_test(self, provider):
        def on_captured(img):
            self.show()
            self.raise_()
            
            if img is None:
                self.log_message("Screen capture cancelled.", "warning")
                return

            if is_image_black(img):
                self.log_message("⚠️ Captured screen is black (Wayland detected). Please switch your session to X11 (Xorg) at the login screen.", "error")

            self.log_message(f"Screenshot region captured ({img.size[0]}x{img.size[1]}). Analyzing...", "success")

            # Analyze async using thread-safe QObject worker & signals
            self.analysis_worker = ScreenAnalysisWorker(
                provider=provider,
                img=img,
                language=self.language,
                mode=self.interview_mode,
                topic=self.topic
            )
            self.analysis_worker.sig_start.connect(self.on_answer_start)
            self.analysis_worker.sig_token.connect(self.on_answer_token)
            self.analysis_worker.sig_done.connect(self.on_answer_done)

            self.analysis_thread = threading.Thread(target=self.analysis_worker.run, daemon=True)
            self.analysis_thread.start()


    def start_detection(self):
        signals = WorkerSignals()
        signals.log.connect(self.log_message)
        signals.question.connect(self.add_qa)
        signals.answer_start.connect(self.on_answer_start)
        signals.answer_token.connect(self.on_answer_token)
        signals.answer_done.connect(self.on_answer_done)
        signals.transcription.connect(self.on_transcription)
        self.worker = AudioDetectorWorker(
            self.device_index, signals, self.sample_rate, self.language,
            self.topic, self.whisper_prompt, self.transcription_provider,
            self.answer_provider, context_prompt=self.context_prompt,
            mode=self.interview_mode
        )
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()
        self.log_message("Detection started!", "success")
        if self.interview_mode == "coding" and screen_capture.is_available():
            self.log_message("📸 Screen capture available — click 'Capture Screen' or double-press F6", "info")

    def stop_and_return(self):
        """Stop and return to configuration"""
        if self.worker:
            self.worker.stop()
            self.worker = None
        self.status_label.setText("Stopped")
        self.status_label.setStyleSheet("color: #f44336; font-size: 14px; font-weight: bold;")
        self.close()
        self.config_window.show_config()

    def closeEvent(self, event):
        if self.worker:
            self.worker.stop()
        self.config_window.show_config()
        event.accept()


# ═══════════════════════════════════════════════════════════════
# Window 3: Overlay Mode (Stealth Fullscreen)
# ═══════════════════════════════════════════════════════════════

class OverlayWindow(QWidget):
    """Overlay Mode — transparent fullscreen window with stealth features"""

    # Signals for thread-safe GUI updates
    sig_hide = pyqtSignal()
    sig_show = pyqtSignal()

    def __init__(self, device_index, sample_rate, config_window, language="English", topic="", config=None, transcription_provider=None, answer_provider=None, context_prompt="", interview_mode="coding"):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.language = language
        self.topic = topic
        self.config = config or {}
        self.transcription_provider = transcription_provider
        self.answer_provider = answer_provider
        self.context_prompt = context_prompt
        self.interview_mode = interview_mode
        self.worker = None
        self.worker_thread = None
        self.hotkey_manager = None
        self.is_silent = False
        self._pending_action = None
        self.last_answer = ""  # For clipboard copy
        self.overlay_font_size = self.config.get("font_size", 16)
        self.overlay_opacity = self.config.get("overlay_opacity", 0.85)
        
        # Current answer being streamed
        self.current_question = ""
        self.current_answer = ""

        # Signals for thread-safe updates
        self.sig_hide.connect(self._go_silent)
        self.sig_show.connect(self._restore)

        # Process name masking (stealth)
        if SETPROCTITLE_AVAILABLE:
            setproctitle.setproctitle("System Service")

        self.init_ui()
        self.setup_stealth()
        self.setup_hotkeys()

        # QTimer to check hotkey state (thread-safe)
        self._poll_timer = QTimer()
        self._poll_timer.timeout.connect(self._poll_hotkey_action)
        self._poll_timer.start(100)  # Check every 100ms

        # Auto-start
        QTimer.singleShot(200, self.start_detection)

    def init_ui(self):
        # Frameless, always-on-top, hidden from taskbar
        self.setWindowFlags(
            Qt.WindowStaysOnTopHint |
            Qt.FramelessWindowHint |
            Qt.WindowTransparentForInput |  # Mouse clicks pass through
            Qt.Tool  # Hide from taskbar
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowOpacity(self.overlay_opacity)
        self.setWindowTitle("")  # Empty title for stealth

        # Fullscreen or Custom Area
        geometry = self.config.get("overlay_geometry")
        if geometry:
            self.setGeometry(QRect(*geometry))
        else:
            self.setGeometry(QApplication.primaryScreen().geometry())

        # Layout
        layout = QVBoxLayout()
        layout.setContentsMargins(40, 40, 40, 40)
        self.setLayout(layout)

        # Answer display
        self.text_display = QTextEdit()
        self.text_display.setReadOnly(True)
        self.text_display.setStyleSheet("""
            QTextEdit {
                background-color: rgba(15, 15, 15, 180);
                color: #e0e0e0;
                border: none;
                border-radius: 10px;
                padding: 20px;
                font-family: 'Arial', 'Helvetica', sans-serif;
                font-size: 16px;
                line-height: 1.6;
            }
        """)
        layout.addWidget(self.text_display)

        # Compact live transcript line (fades after 5s)
        self.transcript_label = QLabel("")
        self.transcript_label.setStyleSheet("""
            QLabel {
                color: rgba(255, 255, 255, 120);
                font-size: 12px;
                padding: 4px 10px;
            }
        """)
        self.transcript_label.setWordWrap(True)
        self.transcript_label.setMaximumHeight(30)
        layout.insertWidget(0, self.transcript_label)

        # Timer to fade transcript
        self._transcript_timer = QTimer()
        self._transcript_timer.setSingleShot(True)
        self._transcript_timer.timeout.connect(lambda: self.transcript_label.setText(""))

    def setup_stealth(self):
        """Platform-aware stealth mode.
        Linux: Qt window flags only (no API to exclude from screen capture).
        Windows: SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE).
        macOS: NSWindow.sharingType = .none (macOS 12+).
        """
        if IS_WINDOWS:
            QTimer.singleShot(500, self._apply_win32_stealth)
        elif IS_MACOS:
            QTimer.singleShot(500, self._apply_macos_stealth)
        else:
            print("[Stealth] Qt window flags applied (Tool + Frameless + TransparentForInput)")
            print("[Stealth] ⚠ Overlay IS visible in screen sharing on Linux.")
            print("[Stealth] Workaround: share a specific window, not the entire screen.")

    def _apply_win32_stealth(self):
        """Windows: SetWindowDisplayAffinity to exclude from screen capture."""
        if not WIN32_AVAILABLE:
            print("[Stealth] Win32 API not available")
            return
        try:
            hwnd = int(self.winId())
            result = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
            if result:
                print("[Stealth] SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE) — overlay invisible to capture")
            else:
                WDA_MONITOR = 0x00000001
                result = user32.SetWindowDisplayAffinity(hwnd, WDA_MONITOR)
                if result:
                    print("[Stealth] SetWindowDisplayAffinity(WDA_MONITOR) — overlay shows black in capture")
                else:
                    print(f"[Stealth] SetWindowDisplayAffinity failed")
        except Exception as e:
            print(f"[Stealth] Win32 stealth error: {e}")

    def _apply_macos_stealth(self):
        """macOS: NSWindow.sharingType = .none to exclude from screen capture.
        Available on macOS 12.0+ (Monterey). Makes the window invisible to
        screenshots, screen recording, AirPlay, and screen sharing apps.
        """
        if not OBJC_AVAILABLE:
            print("[Stealth] PyObjC not available. Install: pip install pyobjc-framework-Cocoa")
            return
        try:
            # Get the native NSWindow from Qt's window handle
            ns_app = NSApplication.sharedApplication()
            for ns_window in ns_app.windows():
                # Match by window title or find the frameless fullscreen one
                frame = ns_window.frame()
                if frame.size.width > 100 and frame.size.height > 100:
                    # sharingType 0 = NSWindowSharingNone (macOS 12+)
                    if hasattr(ns_window, 'setSharingType_'):
                        ns_window.setSharingType_(0)  # NSWindowSharingNone
                        print("[Stealth] NSWindow.sharingType = .none — overlay invisible to capture")
                        return
            print("[Stealth] Could not find NSWindow to apply sharingType")
        except Exception as e:
            print(f"[Stealth] macOS stealth error: {e}")

    def setup_hotkeys(self):
        """Set up global hotkeys"""
        if not (EVDEV_AVAILABLE or PYNPUT_AVAILABLE):
            return
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.on_double_f1 = self._request_hide
        self.hotkey_manager.on_double_f2 = self._request_show
        self.hotkey_manager.on_double_f3 = self._request_kill
        self.hotkey_manager.on_double_f4 = self._request_copy
        self.hotkey_manager.on_double_f6 = self._request_capture
        self.hotkey_manager.on_double_f7 = self._request_opacity_up
        self.hotkey_manager.on_double_f8 = self._request_opacity_down
        self.hotkey_manager.on_double_f9 = self._request_font_up
        self.hotkey_manager.on_double_f10 = self._request_font_down
        self.hotkey_manager.on_double_f11 = self._request_scroll_up
        self.hotkey_manager.on_double_f12 = self._request_scroll_down
        self.hotkey_manager.start()

    def _request_hide(self): self._pending_action = 'hide'
    def _request_show(self): self._pending_action = 'show'
    def _request_kill(self): self._pending_action = 'kill'
    def _request_copy(self): self._pending_action = 'copy'
    def _request_capture(self): self._pending_action = 'capture'
    def _request_opacity_up(self): self._pending_action = 'opacity_up'
    def _request_opacity_down(self): self._pending_action = 'opacity_down'
    def _request_font_up(self): self._pending_action = 'font_up'
    def _request_font_down(self): self._pending_action = 'font_down'
    def _request_scroll_up(self): self._pending_action = 'scroll_up'
    def _request_scroll_down(self): self._pending_action = 'scroll_down'

    def _poll_hotkey_action(self):
        """Check flag every 100ms (runs in GUI thread)"""
        action = self._pending_action
        if action is None:
            return
        self._pending_action = None
        if action == 'hide':
            self._go_silent()
        elif action == 'show':
            self._restore()
        elif action == 'kill':
            self._kill_app()
        elif action == 'copy':
            self._copy_to_clipboard()
        elif action == 'capture':
            self._capture_screen()
        elif action == 'opacity_up':
            self._change_opacity(0.1)
        elif action == 'opacity_down':
            self._change_opacity(-0.1)
        elif action == 'font_up':
            self._change_font_size(2)
        elif action == 'font_down':
            self._change_font_size(-2)
        elif action == 'scroll_up':
            self._scroll_overlay('up')
        elif action == 'scroll_down':
            self._scroll_overlay('down')

    def _scroll_overlay(self, direction):
        """Scroll overlay text display up or down (F11/F12)"""
        bar = self.text_display.verticalScrollBar()
        if bar:
            step = max(20, bar.pageStep() // 2)  # Scroll by half a page or 20px min
            if direction == 'up':
                bar.setValue(max(bar.minimum(), bar.value() - step))
            else:
                bar.setValue(min(bar.maximum(), bar.value() + step))

    def _go_silent(self):
        """Double F1: hide and stop output"""
        if not self.is_silent:
            self.is_silent = True
            self.hide()

    def _restore(self):
        """Double F2: restore overlay"""
        if self.is_silent:
            self.is_silent = False
            self.show()
            self.raise_()

    def _kill_app(self):
        """Double F3: terminate the application"""
        self.stop_detection()
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        QApplication.quit()

    def _copy_to_clipboard(self):
        """Double F4: copy last answer to clipboard"""
        if self.last_answer:
            clipboard = QApplication.clipboard()
            clipboard.setText(self.last_answer)
            self.text_display.append(
                '<div style="color: #34C759; font-size: 12px; text-align: center;">'
                '📋 Answer copied to clipboard</div>'
            )
            self.text_display.moveCursor(QTextCursor.End)
        else:
            self.text_display.append(
                '<div style="color: #FF453A; font-size: 12px; text-align: center;">'
                'No answer to copy yet</div>'
            )
            self.text_display.moveCursor(QTextCursor.End)

    def _change_font_size(self, delta):
        """Change overlay answer font size by delta px"""
        self.overlay_font_size = max(10, min(60, self.overlay_font_size + delta))
        self.config["font_size"] = self.overlay_font_size
        save_config(self.config)
        
        self.text_display.append(
            f'<div style="color: #98989D; font-size: 12px; text-align: center;">'
            f'Font size: {self.overlay_font_size}px</div>'
        )
        self.text_display.moveCursor(QTextCursor.End)

    def _change_opacity(self, delta):
        """Change overlay opacity by delta (F7/F8)"""
        self.overlay_opacity = max(0.2, min(1.0, self.overlay_opacity + delta))
        self.setWindowOpacity(self.overlay_opacity)
        self.config["overlay_opacity"] = self.overlay_opacity
        save_config(self.config)
        self.text_display.append(
            f'<div style="color: #98989D; font-size: 12px; text-align: center;">'
            f'Opacity: {int(self.overlay_opacity * 100)}%</div>'
        )
        self.text_display.moveCursor(QTextCursor.End)

    def _capture_screen(self):
        """F6×2: Capture screen and analyze with vision LLM."""
        if not screen_capture.is_available():
            return

        provider = self.answer_provider
        if not provider or not provider.supports_vision():
            self.text_display.append(
                '<div style="color: #FF453A; font-size: 12px; text-align: center;">'
                'Vision provider not available</div>'
            )
            return

        # Temporarily hide overlay to capture clean screenshot
        was_visible = self.isVisible()
        if was_visible:
            self.hide()
            # Wait a brief moment for the overlay window to hide
            QTimer.singleShot(300, lambda: self._launch_selector_overlay(was_visible, provider))
        else:
            self._launch_selector_overlay(was_visible, provider)

    def _launch_selector_overlay(self, was_visible, provider):
        def on_captured(img):
            if was_visible:
                self.show()
                self.raise_()
            
            if img is None:
                return

            if is_image_black(img):
                self.text_display.append(
                    '<div style="color: #FF9500; font-size: 13px; text-align: center; font-weight: bold; margin: 10px 0;">'
                    '⚠️ Captured screen is black (Wayland detected).<br>'
                    'Please switch your session to Xorg (X11) at the login screen.</div>'
                )

            # Analyze async using thread-safe QObject worker & signals
            self.analysis_worker = ScreenAnalysisWorker(
                provider=provider,
                img=img,
                language=self.language,
                mode=self.interview_mode,
                topic=self.topic
            )
            self.analysis_worker.sig_start.connect(self.on_answer_start)
            self.analysis_worker.sig_token.connect(self.on_answer_token)
            self.analysis_worker.sig_done.connect(self.on_answer_done)

            self.analysis_thread = threading.Thread(target=self.analysis_worker.run, daemon=True)
            self.analysis_thread.start()

        self.selector = ScreenSelector(on_captured)
        self.selector.show()


    def on_transcription(self, text, is_question):
        """Show live transcript as a compact line at top of overlay."""
        if self.is_silent:
            return
        prefix = "❓ " if is_question else "🎤 "
        self.transcript_label.setText(f"{prefix}{text}")
        # Reset fade timer
        self._transcript_timer.stop()
        self._transcript_timer.start(5000)  # Fade after 5 seconds

    def log_message(self, message, level="info"):
        """Log in overlay — debug only, not shown"""
        pass  # Overlay shows only Q&A

    def add_qa(self, question, answer):
        """Add complete Q&A to overlay (non-streaming fallback)"""
        if self.is_silent: return
        self.last_answer = answer
        
        fs = self.overlay_font_size
        self.text_display.append(
            f'<div style="margin-bottom: 5px; margin-top: 15px;">'
            f'<div style="color: #0A84FF; font-size: {fs - 2}px; margin-bottom: 4px; font-weight: bold;">'
            f'Q: {question}</div>'
            f'<div style="color: #FFFFFF; font-size: {fs}px; line-height: 1.4;">'
            f'A: {answer}</div>'
            f'</div>'
        )
        self.text_display.moveCursor(QTextCursor.End)

    def on_answer_start(self, question):
        """Streaming: prepare question block, start empty answer"""
        if self.is_silent: return
        fs = self.overlay_font_size
        self.text_display.append(
            f'<div style="margin-bottom: 5px; margin-top: 15px;">'
            f'<div style="color: #0A84FF; font-size: {fs - 2}px; margin-bottom: 4px; font-weight: bold;">'
            f'Q: {question}</div>'
            f'<div style="color: #FFFFFF; font-size: {fs}px; line-height: 1.4;">'
            f'A: '
        )
        self._streaming_answer = ""
        self.text_display.moveCursor(QTextCursor.End)

    def on_answer_token(self, token):
        """Streaming: append one token"""
        if self.is_silent: return
        self._streaming_answer += token
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(token)
        self.text_display.setTextCursor(cursor)
        self.text_display.ensureCursorVisible()

    def on_answer_done(self, question, answer):
        """Streaming: finalize answer"""
        self.last_answer = answer
        cursor = self.text_display.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertHtml('</div></div>')
        self.text_display.moveCursor(QTextCursor.End)

    def start_detection(self):
        signals = WorkerSignals()
        signals.log.connect(self.log_message)
        signals.question.connect(self.add_qa)
        signals.answer_start.connect(self.on_answer_start)
        signals.answer_token.connect(self.on_answer_token)
        signals.answer_done.connect(self.on_answer_done)
        signals.transcription.connect(self.on_transcription)
        self.worker = AudioDetectorWorker(
            self.device_index, signals, self.sample_rate, self.language,
            self.topic, self.config.get("whisper_prompt", ""),
            self.transcription_provider, self.answer_provider,
            context_prompt=self.context_prompt, mode=self.interview_mode
        )
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()

    def stop_detection(self):
        if self.worker:
            self.worker.stop()
            self.worker = None

    def close_and_return(self):
        """Close overlay and return to configuration"""
        self.stop_detection()
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        self.close()
        self.config_window.show_config()

    def keyPressEvent(self, event):
        """Escape closes overlay and returns to configuration"""
        if event.key() == Qt.Key_Escape:
            self.close_and_return()
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.stop_detection()
        if self.hotkey_manager:
            self.hotkey_manager.stop()
        self.config_window.show_config()
        event.accept()


# ═══════════════════════════════════════════════════════════════
# Answer History Window
# ═══════════════════════════════════════════════════════════════

class HistoryWindow(QDialog):
    """Browsable Q&A history window with search and clear"""

    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle("Answer History")
        self.setMinimumSize(700, 500)
        
        self.setStyleSheet(get_stylesheet(theme))

        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        header = QHBoxLayout()
        title = QLabel("History")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch()

        self.count_label = QLabel("")
        self.count_label.setObjectName("Subtitle")
        header.addWidget(self.count_label)
        layout.addLayout(header)

        # Search bar
        search_layout = QHBoxLayout()
        self.search_input = ModernInput(self.theme)
        self.search_input.setPlaceholderText("🔍 Search questions and answers...")
        self.search_input.textChanged.connect(self.filter_history)
        search_layout.addWidget(self.search_input)
        layout.addLayout(search_layout)

        # History display
        self.history_text = QTextEdit()
        self.history_text.setReadOnly(True)
        # Apply specific text edit style from theme colors
        c = COLORS[self.theme]
        self.history_text.setStyleSheet(f"""
            QTextEdit {{
                background-color: {c['input_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                line-height: 1.5;
            }}
        """)
        layout.addWidget(self.history_text)

        # Buttons
        btn_layout = QHBoxLayout()
        
        clear_btn = ModernButton("Clear All History", self.theme)
        # Custom danger style for clear button
        danger = COLORS[self.theme]['danger']
        clear_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {danger};
                color: white;
                border: none;
                border-radius: 8px;
                font-weight: 600;
                padding: 5px 15px;
            }}
            QPushButton:hover {{ background-color: #d32f2f; }}
        """)
        clear_btn.clicked.connect(self.clear_history)
        btn_layout.addWidget(clear_btn)

        export_btn = ModernButton("Export to Markdown", self.theme)
        export_btn.clicked.connect(self.export_to_markdown)
        btn_layout.addWidget(export_btn)

        btn_layout.addStretch()

        close_btn = ModernButton("Close", self.theme)
        close_btn.clicked.connect(self.close)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

        # Load history
        self.all_entries = []
        self.load_history()

    def load_history(self):
        """Load history from JSON file"""
        self.all_entries = []
        try:
            if HISTORY_FILE.exists():
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    self.all_entries = json.load(f)
        except Exception:
            pass
        self.display_entries(self.all_entries)

    def display_entries(self, entries):
        """Display a list of history entries"""
        self.history_text.clear()
        self.count_label.setText(f"{len(entries)} entries")
        
        c = COLORS[self.theme]

        if not entries:
            self.history_text.setHtml(
                f'<div style="color: {c["text_secondary"]}; text-align: center; margin-top: 50px;">'
                'No history entries yet.<br>Start detecting questions to build history.</div>'
            )
            return

        # Show newest first
        for entry in reversed(entries):
            ts = entry.get("timestamp", "")
            q = entry.get("question", "")
            a = entry.get("answer", "")
            lang = entry.get("language", "")
            topic = entry.get("topic", "")

            # Format timestamp
            try:
                dt = datetime.fromisoformat(ts)
                ts_fmt = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                ts_fmt = ts
            
            # Styles for HTML
            meta_style = f"color: {c['text_secondary']}; font-size: 12px; margin-bottom: 4px;"
            q_style = f"color: {c['accent']}; font-weight: bold; margin-bottom: 2px;"
            a_style = f"color: {c['text_primary']}; margin-bottom: 15px;"

            meta = f"<div style='{meta_style}'>{ts_fmt}"
            if lang:
                meta += f" • {lang}"
            if topic:
                meta += f" • {topic}"
            meta += "</div>"

            self.history_text.append(
                f'<div style="margin-bottom: 15px;">'
                f'{meta}'
                f'<div style="{q_style}">Q: {q}</div>'
                f'<div style="{a_style}">A: {a}</div>'
                f'<hr style="border: 0; border-top: 1px solid {c["border"]}; margin: 10px 0;">'
                f'</div>'
            )

    def filter_history(self, text):
        """Filter history entries by search text"""
        if not text:
            self.display_entries(self.all_entries)
            return
        text_lower = text.lower()
        filtered = [
            e for e in self.all_entries
            if text_lower in e.get("question", "").lower()
            or text_lower in e.get("answer", "").lower()
            or text_lower in e.get("topic", "").lower()
        ]
        self.display_entries(filtered)

    def clear_history(self):
        """Clear all history after confirmation"""
        reply = QMessageBox.question(
            self, "Clear History",
            "Are you sure you want to delete all history?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    json.dump([], f)
            except Exception:
                pass
            self.load_history()

    def export_to_markdown(self):
        """Export history to a Markdown file."""
        if not self.all_entries:
            ModernDialog("Export", "No history entries to export.", self.theme, self).exec_()
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export History",
            str(Path.home() / "interview_history.md"),
            "Markdown Files (*.md);;All Files (*)"
        )
        if not file_path:
            return

        try:
            lines = ["# Interview Q&A History\n"]
            lines.append(f"**Total entries:** {len(self.all_entries)}\n")

            # Group by date
            current_date = ""
            for entry in self.all_entries:
                ts = entry.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts)
                    date_str = dt.strftime("%Y-%m-%d")
                    time_str = dt.strftime("%H:%M")
                except Exception:
                    date_str = "Unknown"
                    time_str = ""

                if date_str != current_date:
                    current_date = date_str
                    lines.append(f"\n## {date_str}\n")

                q = entry.get("question", "")
                a = entry.get("answer", "")
                topic = entry.get("topic", "")
                lang = entry.get("language", "")

                meta_parts = [time_str]
                if lang:
                    meta_parts.append(lang)
                if topic:
                    meta_parts.append(topic)
                meta = " • ".join(filter(None, meta_parts))

                lines.append(f"### Q: {q}\n")
                if meta:
                    lines.append(f"*{meta}*\n")
                lines.append(f"**A:** {a}\n")
                lines.append("---\n")

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines))

            ModernDialog(
                "Export Complete",
                f"History exported to:\n{file_path}",
                self.theme, self
            ).exec_()
        except Exception as e:
            ModernDialog("Export Error", f"Failed to export:\n{e}", self.theme, self).exec_()


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    
    # Load config to determine initial theme
    config = load_config()
    theme = config.get("theme", "dark")
    
    # Validate API keys early
    if not GROQ_API_KEY and not OPENAI_API_KEY:
        print("WARNING: No API keys set. Create .env file with GROQ_API_KEY or OPENAI_API_KEY")
    
    # Apply global theme (Palette + Stylesheet)
    app.setStyle('Fusion') # Fusion provides good base for custom palette. Set BEFORE palette!
    apply_theme_palette(app, theme)

    window = ConfigWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
