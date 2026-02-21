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

from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QTextEdit, QGroupBox, QMessageBox,
                             QLineEdit, QDialog, QScrollArea, QCheckBox,
                             QRubberBand)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QPoint, QRect, QSize, QUrl
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette, QPainter, QPen, QDesktopServices

import sounddevice as sd
import numpy as np
from dotenv import load_dotenv
from groq import Groq
from styles import COLORS, get_stylesheet, apply_theme_palette
from modern_widgets import ModernButton, ModernInput, ModernToggle, ModernCard, ModernComboBox, ModernDialog

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
APP_VERSION = "1.3.0"
GITHUB_REPO = "Alkaness/audio_question_detector"


def load_config():
    """Load saved settings from config file."""
    defaults = {
        "language": "Ukrainian",
        "topic": "",
        "whisper_prompt": "",
        "font_size": 16,
        "theme": "dark",
        "overlay_geometry": None,  # None = fullscreen
        "source_name": None,
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

# Load env
load_dotenv()

# Settings
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
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

QUESTION_WORDS_UKRAINIAN = [
    "що", "де", "коли", "чому", "як", "хто", "який", "яка", "яке", "які",
    "чи", "скільки", "котрий", "куди", "звідки", "навіщо", "відколи"
]
QUESTION_WORDS_ENGLISH = [
    "what", "where", "when", "why", "how", "who", "which", "whom",
    "can", "could", "would", "should", "is", "are", "do", "does", "did"
]
QUESTION_WORDS = QUESTION_WORDS_UKRAINIAN + QUESTION_WORDS_ENGLISH


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


class AudioDetectorWorker:
    """Worker for audio processing in a separate thread"""

    def __init__(self, device_index, signals, sample_rate=SAMPLE_RATE, language="Ukrainian", topic="", whisper_prompt=""):
        self.device_index = device_index
        self.signals = signals
        self.sample_rate = sample_rate
        self.is_running = False
        if not GROQ_API_KEY:
            raise ValueError("GROQ_API_KEY is not set. Add it to .env file.")
        self.client = Groq(api_key=GROQ_API_KEY)
        self.audio_queue = queue.Queue()
        self.last_transcription = ""
        self.conversation_history = []
        self.language = language
        self.topic = topic
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
            transcription = self.client.audio.transcriptions.create(
                file=wav_buffer,
                model="whisper-large-v3",
                response_format="text",
                prompt=prompt,
                temperature=0.0
            )
            result = transcription.strip() if transcription else ""
            if result:
                self.last_transcription = result
            return result
        except Exception as e:
            self.signals.log.emit(f"Transcription error: {e}", "error")
            return ""

    def correct_transcription(self, raw_text):
        try:
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
                    {"role": "user", "content": raw_text}
                ],
                model="llama-3.1-8b-instant",
                temperature=0.0,
                max_tokens=150
            )
            corrected = correction.choices[0].message.content.strip()
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
                f"Take into account the context of previous questions and answers in the conversation. "
                f"At the very end of your response, on a new line, add a confidence tag like [CONF:85] "
                f"where the number is your percentage confidence (0-100) in the accuracy of your answer."
            )
            messages = [{"role": "system", "content": system_prompt}]
            for prev_q, prev_a in self.conversation_history[-10:]:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_a})
            messages.append({"role": "user", "content": question})

            # Signal UI to prepare answer block
            self.signals.answer_start.emit(question)

            # Streaming response
            stream = self.client.chat.completions.create(
                messages=messages,
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                max_tokens=300,
                top_p=0.9,
                stream=True
            )

            full_answer = ""
            for chunk in stream:
                token = chunk.choices[0].delta.content or ""
                if token:
                    full_answer += token
                    self.signals.answer_token.emit(token)

            answer = full_answer.strip()

            # Extract confidence score
            conf_match = re.search(r'\[CONF:(\d+)\]', answer)
            confidence = None
            if conf_match:
                confidence = int(conf_match.group(1))
                answer = re.sub(r'\s*\[CONF:\d+\]\s*', '', answer).strip()

            # Add confidence badge
            if confidence is not None:
                if confidence >= 80:
                    badge = f"🟢 {confidence}%"
                elif confidence >= 50:
                    badge = f"🟡 {confidence}%"
                else:
                    badge = f"🔴 {confidence}% ⚠️"
                answer = f"{answer}\n\n[Confidence: {badge}]"

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
        if self.is_question(transcription):
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
        self.last_f9_time = 0.0
        self.last_f10_time = 0.0
        self.on_double_f1 = None
        self.on_double_f2 = None
        self.on_double_f3 = None
        self.on_double_f4 = None  # Copy to clipboard
        self.on_double_f9 = None  # Font size up
        self.on_double_f10 = None  # Font size down
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
        self.audio_sources = get_audio_sources()
        self.test_window = None
        self.overlay_window = None
        self.history_window = None
        self.init_ui()
        # Wire update signal to handler
        self.update_available.connect(self.on_update_available)
        self.check_for_updates()

    def init_ui(self):
        self.setWindowTitle("Audio Question Detector — Settings")
        # self.setFixedSize(500, 550) # Removing fixed size to prevent overlap
        self.setMinimumSize(500, 650) # Taller minimum size
        self.theme = self.config.get("theme", "dark")
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        x = (screen.width() - 500) // 2
        y = (screen.height() - 650) // 2
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

        # 2. Mode & Language Row
        row2 = QHBoxLayout()
        
        # Mode
        mode_layout = QVBoxLayout()
        mode_lbl = QLabel("Mode")
        mode_lbl.setObjectName("Subtitle")
        mode_layout.addWidget(mode_lbl)
        self.mode_combo = ModernComboBox(self.theme)
        self.mode_combo.addItems(["Test Mode", "Overlay Mode"])
        mode_layout.addWidget(self.mode_combo)
        row2.addLayout(mode_layout)
        
        # Language
        lang_layout = QVBoxLayout()
        lang_lbl = QLabel("Language")
        lang_lbl.setObjectName("Subtitle")
        lang_layout.addWidget(lang_lbl)
        self.lang_combo = ModernComboBox(self.theme)
        langs = [
            "Ukrainian", "English", "Russian", "German",
            "French", "Spanish", "Polish", "Chinese", "Japanese"
        ]
        self.lang_combo.addItems(langs)
        saved_lang = self.config.get("language", "Ukrainian")
        if saved_lang in langs:
            self.lang_combo.setCurrentText(saved_lang)
        lang_layout.addWidget(self.lang_combo)
        row2.addLayout(lang_layout)
        
        card_layout.addLayout(row2)

        # 3. Topic
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

        if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
            QMessageBox.warning(self, "Error",
                                "Groq API key not configured!\n\n"
                                "Add key to .env file:\nGROQ_API_KEY=your_key")
            return None

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

        # Save current settings
        self.config.update({
            "language": language,
            "topic": topic,
            "whisper_prompt": whisper_prompt,
            "source_name": self.source_combo.currentText(),
            "theme": "light" if self.theme_toggle.isChecked() else "dark"
        })
        save_config(self.config)

        self.hide()

        if mode == 0:
            # Test Mode
            self.test_window = TestModeWindow(device_index, sample_rate, self, language, topic, self.config.get("theme", "dark"), whisper_prompt)
            self.test_window.show()
        else:
            # Overlay Mode
            self.overlay_window = OverlayWindow(device_index, sample_rate, self, language, topic, self.config)
            self.overlay_window.show()

    def show_config(self):
        """Return to configuration"""
        self.show()
        self.raise_()
        self.activateWindow()

    def show_history(self):
        """Open history window — always recreate to ensure fresh theme"""
        self.history_window = HistoryWindow(self.theme, self)
        self.history_window.show()
        self.history_window.raise_()

# ═══════════════════════════════════════════════════════════════
# Window 2: Test Mode (Standard Window)
# ═══════════════════════════════════════════════════════════════

class TestModeWindow(QMainWindow):
    """Test Mode — standard window with log and answers"""

    def __init__(self, device_index, sample_rate, config_window, language="Ukrainian", topic="", theme="dark", whisper_prompt=""):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.language = language
        self.topic = topic
        self.theme = theme
        self.whisper_prompt = whisper_prompt
        self.worker = None
        self.worker_thread = None
        self.init_ui()
        # Auto-start
        QTimer.singleShot(100, self.start_detection)

    def init_ui(self):
        self.setWindowTitle("Test Mode — Audio Question Detector")
        self.setGeometry(100, 100, 850, 650)
        
        self.setStyleSheet(get_stylesheet(self.theme))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        central.setLayout(layout)

        # Header + status
        header = QHBoxLayout()
        title = QLabel("Test Mode")
        title.setObjectName("Title")
        header.addWidget(title)
        header.addStretch()

        self.status_label = QLabel("Listening...")
        self.status_label.setStyleSheet("color: #4CAF50; font-size: 14px; font-weight: bold;")
        header.addWidget(self.status_label)
        layout.addLayout(header)

        # Log
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(180)
        # Apply specific style for log
        c = COLORS[self.theme]
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

        # Stop button
        # ModernButton with danger color
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
        layout.addWidget(self.stop_btn)

    def log_message(self, message, level="info"):
        colors = {"info": "#b0b0b0", "success": "#4CAF50", "warning": "#FF9800", "error": "#f44336"}
        color = colors.get(level, "#b0b0b0")
        self.log_text.append(f'<span style="color: {color};">{message}</span>')
        self.log_text.moveCursor(QTextCursor.End)

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

    def start_detection(self):
        signals = WorkerSignals()
        signals.log.connect(self.log_message)
        signals.question.connect(self.add_qa)
        signals.answer_start.connect(self.on_answer_start)
        signals.answer_token.connect(self.on_answer_token)
        signals.answer_done.connect(self.on_answer_done)
        self.worker = AudioDetectorWorker(self.device_index, signals, self.sample_rate, self.language, self.topic, self.whisper_prompt)
        self.worker_thread = threading.Thread(target=self.worker.run, daemon=True)
        self.worker_thread.start()
        self.log_message("Detection started!", "success")

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

    def __init__(self, device_index, sample_rate, config_window, language="Ukrainian", topic="", config=None):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.language = language
        self.topic = topic
        self.config = config or {}
        self.worker = None
        self.worker_thread = None
        self.hotkey_manager = None
        self.is_silent = False
        self._pending_action = None  # 'hide', 'show', 'kill', 'copy', 'font_up', 'font_down'
        self.last_answer = ""  # For clipboard copy
        self.overlay_font_size = self.config.get("font_size", 16)
        
        # Current answer being streamed
        self.current_question = ""
        self.current_answer = ""

        # Signals for thread-safe updates
        self.sig_hide.connect(self._go_silent)
        self.sig_show.connect(self._restore)

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
        self.setWindowOpacity(0.85)

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
        self.hotkey_manager.on_double_f9 = self._request_font_up
        self.hotkey_manager.on_double_f10 = self._request_font_down
        self.hotkey_manager.start()

    def _request_hide(self): self._pending_action = 'hide'
    def _request_show(self): self._pending_action = 'show'
    def _request_kill(self): self._pending_action = 'kill'
    def _request_copy(self): self._pending_action = 'copy'
    def _request_font_up(self): self._pending_action = 'font_up'
    def _request_font_down(self): self._pending_action = 'font_down'

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
        elif action == 'font_up':
            self._change_font_size(2)
        elif action == 'font_down':
            self._change_font_size(-2)

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
        self.worker = AudioDetectorWorker(self.device_index, signals, self.sample_rate, self.language, self.topic, self.config.get("whisper_prompt", ""))
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


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    
    # Load config to determine initial theme
    config = load_config()
    theme = config.get("theme", "dark")
    
    # Validate API key early
    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        print("WARNING: GROQ_API_KEY not set. Create .env file with: GROQ_API_KEY=your_key")
    
    # Apply global theme (Palette + Stylesheet)
    app.setStyle('Fusion') # Fusion provides good base for custom palette. Set BEFORE palette!
    apply_theme_palette(app, theme)

    window = ConfigWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
