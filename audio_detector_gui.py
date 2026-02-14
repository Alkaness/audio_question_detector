#!/usr/bin/env python3
"""
Audio Question Detector — GUI Application
Cross-platform: auto-detects Linux/Windows for hotkeys, audio sources, and stealth.
Multi-window architecture: Config → Test Mode / Overlay Mode
"""

import sys
import os
import subprocess
import threading
import queue
from io import BytesIO
import wave
import time
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QLabel, QComboBox,
                             QTextEdit, QGroupBox, QMessageBox, QDesktopWidget)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QTextCursor, QColor, QPalette

import sounddevice as sd
import numpy as np
from dotenv import load_dotenv
from groq import Groq
import logging
import platform

IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'

# Platform-specific hotkey backend
EVDEV_AVAILABLE = False
PYNPUT_AVAILABLE = False
WIN32_AVAILABLE = False

if IS_LINUX:
    try:
        import evdev
        from evdev import ecodes
        EVDEV_AVAILABLE = True
    except ImportError:
        print("Warning: evdev not installed. Hotkeys disabled. Install: pip install evdev")
else:
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

# Whisper prompt
WHISPER_PROMPT = (
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
CONTEXT_KEYWORDS = []


# ═══════════════════════════════════════════════════════════════
# Worker (unchanged from previous version)
# ═══════════════════════════════════════════════════════════════

class WorkerSignals(QObject):
    """Signals for GUI communication"""
    log = pyqtSignal(str, str)
    question = pyqtSignal(str, str)


class AudioDetectorWorker:
    """Worker for audio processing in a separate thread"""

    def __init__(self, device_index, signals, sample_rate=SAMPLE_RATE):
        self.device_index = device_index
        self.signals = signals
        self.sample_rate = sample_rate
        self.is_running = False
        self.client = Groq(api_key=GROQ_API_KEY)
        self.audio_queue = queue.Queue()
        self.last_transcription = ""
        self.conversation_history = []

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
            prompt = WHISPER_PROMPT
            if self.last_transcription:
                prev_context = self.last_transcription[-200:]
                prompt = prev_context + " " + WHISPER_PROMPT[:100]
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
        if not text:
            return False
        return True

    def is_relevant(self, text):
        if not CONTEXT_KEYWORDS:
            return True
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in CONTEXT_KEYWORDS)

    def answer_question(self, question):
        try:
            system_prompt = (
                "You are a helpful AI assistant that answers any questions. "
                "ALWAYS respond in Ukrainian, even if the question is in English. "
                "Give concise, clear answers (2-3 sentences maximum). "
                "If the question is about technology/programming, you may include a code example. "
                "Explain in simple terms so the person can quickly understand and respond in conversation. "
                "Take into account the context of previous questions and answers in the conversation."
            )
            messages = [{"role": "system", "content": system_prompt}]
            for prev_q, prev_a in self.conversation_history[-10:]:
                messages.append({"role": "user", "content": prev_q})
                messages.append({"role": "assistant", "content": prev_a})
            messages.append({"role": "user", "content": question})

            chat_completion = self.client.chat.completions.create(
                messages=messages,
                model="llama-3.3-70b-versatile",
                temperature=0.7,
                max_tokens=300,
                top_p=0.9
            )
            answer = chat_completion.choices[0].message.content.strip()
            self.conversation_history.append((question, answer))
            if len(self.conversation_history) > 10:
                self.conversation_history = self.conversation_history[-10:]
            return answer
        except Exception as e:
            self.signals.log.emit(f"Answer generation error: {e}", "error")
            return "Sorry, could not generate an answer."

    def has_speech(self, audio_data):
        # np.dot is faster than mean(x**2) for large arrays
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
            answer = self.answer_question(transcription)
            self.signals.question.emit(transcription, answer)

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
        self.on_double_f1 = None
        self.on_double_f2 = None
        self.on_double_f3 = None
        self._thread = None
        self._running = False
        self._listener = None  # pynput listener (Windows)

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

    # ── Windows (pynput) ──
    def _on_key_press_pynput(self, key):
        """Handle pynput key press (Windows)"""
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
        except AttributeError:
            pass

    # ── Cross-platform start/stop ──
    def start(self):
        if IS_LINUX and EVDEV_AVAILABLE:
            self._running = True
            self._thread = threading.Thread(target=self._listen_loop_evdev, daemon=True)
            self._thread.start()
        elif IS_WINDOWS and PYNPUT_AVAILABLE:
            self._listener = pynput_keyboard.Listener(on_press=self._on_key_press_pynput)
            self._listener.daemon = True
            self._listener.start()
            print("[HotkeyManager] pynput listener started. F1x2=hide, F2x2=show, F3x2=quit", flush=True)

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
    if IS_WINDOWS:
        return _get_audio_sources_windows()
    return _get_audio_sources_linux()

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
# Window 1: Configuration Window (Launcher)
# ═══════════════════════════════════════════════════════════════

class ConfigWindow(QMainWindow):
    """Configuration window — application entry point"""

    def __init__(self):
        super().__init__()
        self.test_window = None
        self.overlay_window = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Audio Question Detector — Settings")
        self.setFixedSize(500, 350)

        # Center on screen
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - 500) // 2
        y = (screen.height() - 350) // 2
        self.move(x, y)

        # Style — dark grey background
        self.setStyleSheet("""
            QMainWindow { background-color: #2d2d2d; }
            QLabel { color: #e0e0e0; font-size: 14px; }
            QComboBox {
                background-color: #3a3a3a; color: #e0e0e0;
                border: 1px solid #555; border-radius: 4px;
                padding: 8px; font-size: 13px; min-height: 20px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background-color: #3a3a3a; color: #e0e0e0;
                selection-background-color: #4a90d9;
            }
            QPushButton {
                font-size: 15px; font-weight: bold;
                padding: 12px 30px; border-radius: 6px;
                border: none;
            }
            QGroupBox {
                color: #b0b0b0; border: 1px solid #444;
                border-radius: 6px; margin-top: 10px; padding-top: 15px;
                font-size: 13px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(25, 20, 25, 25)
        central.setLayout(layout)

        # Title
        title = QLabel("Audio Question Detector")
        title.setFont(QFont("Arial", 18, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("color: #ffffff; margin-bottom: 5px;")
        layout.addWidget(title)

        # Settings group
        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout()
        settings_layout.setSpacing(12)

        # Audio source
        source_layout = QHBoxLayout()
        source_label = QLabel("Source:")
        source_label.setFixedWidth(80)
        source_layout.addWidget(source_label)
        self.source_combo = QComboBox()
        source_layout.addWidget(self.source_combo)
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFixedWidth(40)
        refresh_btn.setStyleSheet("background-color: #3a3a3a; color: #e0e0e0; padding: 8px;")
        refresh_btn.clicked.connect(self.refresh_sources)
        source_layout.addWidget(refresh_btn)
        settings_layout.addLayout(source_layout)

        # Mode
        mode_layout = QHBoxLayout()
        mode_label = QLabel("Mode:")
        mode_label.setFixedWidth(80)
        mode_layout.addWidget(mode_label)
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Test Mode", "Overlay Mode"])
        mode_layout.addWidget(self.mode_combo)
        settings_layout.addLayout(mode_layout)

        settings_group.setLayout(settings_layout)
        layout.addWidget(settings_group)

        layout.addStretch()

        # Launch button
        self.start_btn = QPushButton("Start")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50; color: white;
            }
            QPushButton:hover { background-color: #45a049; }
        """)
        self.start_btn.clicked.connect(self.launch_mode)
        layout.addWidget(self.start_btn)

        # Populate sources
        self.refresh_sources()

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
            # Windows: source_name is already a sounddevice index (int)
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

        self.hide()

        if mode == 0:
            # Test Mode
            self.test_window = TestModeWindow(device_index, sample_rate, self)
            self.test_window.show()
        else:
            # Overlay Mode
            self.overlay_window = OverlayWindow(device_index, sample_rate, self)
            self.overlay_window.show()

    def show_config(self):
        """Return to configuration"""
        self.show()
        self.raise_()
        self.activateWindow()


# ═══════════════════════════════════════════════════════════════
# Window 2: Test Mode (Standard Window)
# ═══════════════════════════════════════════════════════════════

class TestModeWindow(QMainWindow):
    """Test Mode — standard window with log and answers"""

    def __init__(self, device_index, sample_rate, config_window):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.worker = None
        self.worker_thread = None
        self.init_ui()
        # Auto-start
        QTimer.singleShot(100, self.start_detection)

    def init_ui(self):
        self.setWindowTitle("Test Mode — Audio Question Detector")
        self.setGeometry(100, 100, 850, 650)

        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; }
            QLabel { color: #e0e0e0; }
            QTextEdit {
                background-color: #252525; color: #d4d4d4;
                border: 1px solid #3a3a3a; border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace; font-size: 12px;
            }
            QGroupBox {
                color: #b0b0b0; border: 1px solid #3a3a3a;
                border-radius: 6px; margin-top: 10px; padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin; left: 10px; padding: 0 5px;
            }
        """)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(15, 15, 15, 15)
        central.setLayout(layout)

        # Header + status
        header = QHBoxLayout()
        title = QLabel("Test Mode")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setStyleSheet("color: #ffffff;")
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
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        # Q&A
        qa_group = QGroupBox("Conversation & Answers")
        qa_layout = QVBoxLayout()
        self.qa_text = QTextEdit()
        self.qa_text.setReadOnly(True)
        self.qa_text.setStyleSheet(self.qa_text.styleSheet() + "font-size: 13px;")
        qa_layout.addWidget(self.qa_text)
        qa_group.setLayout(qa_layout)
        layout.addWidget(qa_group)

        # Stop button
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #f44336; color: white;
                font-size: 15px; font-weight: bold;
                padding: 12px 30px; border-radius: 6px; border: none;
            }
            QPushButton:hover { background-color: #e53935; }
        """)
        self.stop_btn.clicked.connect(self.stop_and_return)
        layout.addWidget(self.stop_btn)

    def log_message(self, message, level="info"):
        colors = {"info": "#b0b0b0", "success": "#4CAF50", "warning": "#FF9800", "error": "#f44336"}
        color = colors.get(level, "#b0b0b0")
        self.log_text.append(f'<span style="color: {color};">{message}</span>')
        self.log_text.moveCursor(QTextCursor.End)

    def add_qa(self, question, answer):
        self.qa_text.append(
            f'<div style="background-color: #1a3a5c; padding: 10px; margin: 5px; border-radius: 6px;">'
            f'<b style="color: #64b5f6;">TEXT:</b> <span style="color: #e0e0e0;">{question}</span></div>'
        )
        self.qa_text.append(
            f'<div style="background-color: #1b4332; padding: 10px; margin: 5px; border-radius: 6px;">'
            f'<b style="color: #81c784;">ANSWER:</b> <span style="color: #e0e0e0;">{answer}</span></div><br>'
        )
        self.qa_text.moveCursor(QTextCursor.End)

    def start_detection(self):
        signals = WorkerSignals()
        signals.log.connect(self.log_message)
        signals.question.connect(self.add_qa)
        self.worker = AudioDetectorWorker(self.device_index, signals, self.sample_rate)
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

    def __init__(self, device_index, sample_rate, config_window):
        super().__init__()
        self.config_window = config_window
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.worker = None
        self.worker_thread = None
        self.hotkey_manager = None
        self.is_silent = False
        self._pending_action = None  # 'hide', 'show', or 'kill' — for QTimer polling

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

        # Fullscreen
        screen = QDesktopWidget().screenGeometry()
        self.setGeometry(screen)

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
        """
        if IS_WINDOWS:
            QTimer.singleShot(500, self._apply_win32_stealth)
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

    def setup_hotkeys(self):
        """Set up global hotkeys"""
        if not (EVDEV_AVAILABLE or PYNPUT_AVAILABLE):
            return
        self.hotkey_manager = HotkeyManager()
        self.hotkey_manager.on_double_f1 = self._request_hide
        self.hotkey_manager.on_double_f2 = self._request_show
        self.hotkey_manager.on_double_f3 = self._request_kill
        self.hotkey_manager.start()

    def _request_hide(self):
        """Called from listener thread — safe via flag"""
        self._pending_action = 'hide'

    def _request_show(self):
        """Called from listener thread — safe via flag"""
        self._pending_action = 'show'

    def _request_kill(self):
        """Called from listener thread — terminate app"""
        self._pending_action = 'kill'

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

    def log_message(self, message, level="info"):
        """Log in overlay — debug only, not shown"""
        pass  # Overlay shows only Q&A

    def add_qa(self, question, answer):
        """Add answer to overlay"""
        if self.is_silent:
            return
        self.text_display.append(
            f'<div style="margin-bottom: 15px;">'
            f'<div style="color: #64b5f6; font-size: 14px; margin-bottom: 5px;">'
            f'<b>Q:</b> {question}</div>'
            f'<div style="color: #e8f5e9; font-size: 16px; line-height: 1.5;">'
            f'<b>A:</b> {answer}</div>'
            f'<hr style="border-color: #333;">'
            f'</div>'
        )
        self.text_display.moveCursor(QTextCursor.End)

    def start_detection(self):
        signals = WorkerSignals()
        signals.log.connect(self.log_message)
        signals.question.connect(self.add_qa)
        self.worker = AudioDetectorWorker(self.device_index, signals, self.sample_rate)
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
# Main
# ═══════════════════════════════════════════════════════════════

def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    # Dark palette for all windows
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(45, 45, 45))
    palette.setColor(QPalette.WindowText, QColor(224, 224, 224))
    palette.setColor(QPalette.Base, QColor(37, 37, 37))
    palette.setColor(QPalette.AlternateBase, QColor(45, 45, 45))
    palette.setColor(QPalette.ToolTipBase, QColor(224, 224, 224))
    palette.setColor(QPalette.ToolTipText, QColor(224, 224, 224))
    palette.setColor(QPalette.Text, QColor(224, 224, 224))
    palette.setColor(QPalette.Button, QColor(45, 45, 45))
    palette.setColor(QPalette.ButtonText, QColor(224, 224, 224))
    palette.setColor(QPalette.Highlight, QColor(74, 144, 217))
    palette.setColor(QPalette.HighlightedText, QColor(0, 0, 0))
    app.setPalette(palette)

    window = ConfigWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
