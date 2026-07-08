<p align="center">
  <h1 align="center">Audio Question Detector</h1>
  <p align="center">
    Real-time audio question detection with AI-powered answers.<br>
    Captures system audio, detects questions via Whisper, and generates instant answers using LLaMA 3.3.
  </p>
</p>

<p align="center">
  <a href="https://github.com/Alkaness/audio_question_detector/actions"><img src="https://img.shields.io/github/actions/workflow/status/Alkaness/audio_question_detector/ci.yml?branch=main&label=CI&logo=github" alt="CI"></a>
  <img src="https://img.shields.io/badge/version-1.3.0-blue?logo=github" alt="Version 1.3.0">
  <a href="https://github.com/Alkaness/audio_question_detector/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
  <img src="https://img.shields.io/badge/python-3.9+-blue?logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey" alt="Platform">
  <img src="https://img.shields.io/badge/AI-Groq%20LLaMA%203.3-orange?logo=meta" alt="AI">
</p>

---

> **Disclaimer — Educational Use Only**
>
> This software is provided **strictly for educational and research purposes**. It is intended as a demonstration of real-time audio processing, speech recognition, and large language model integration. **Using this tool during actual interviews, exams, certifications, or any form of assessment is unethical and may violate terms of service, academic integrity policies, or applicable laws.** The authors assume no responsibility for misuse. By using this software, you agree to use it only in lawful and ethical contexts, such as personal learning, experimentation, and technical exploration.

---

## Features

- **Real-time audio capture** — system audio monitor or microphone input
- **WebRTC VAD** — ML-based voice activity detection with RMS fallback
- **AI-powered answers** — Groq Whisper transcription + LLaMA 3.3 70B generation
- **Screen capture for coding interviews** — capture LeetCode/HackerRank problems and get AI-analyzed solutions with pseudocode, complexity analysis, and edge cases
- **Resume & Job Description context** — upload your resume and paste the JD for personalized, tailored answers
- **Live transcript panel** — see all transcribed speech in real-time, not just questions
- **Stealth overlay** — transparent fullscreen overlay, invisible to screen capture on Windows and macOS
- **52 answer languages** — comprehensive Whisper language support with question-word detection
- **Coding / Non-Coding interview modes** — optimized prompts and features for each interview type
- **Topic context** — configurable domain for more relevant answers
- **Custom Whisper prompt** — keywords to improve transcription accuracy
- **Conversation memory** — maintains last 10 Q&A pairs for contextual follow-ups
- **Clipboard integration** — copy the last answer with a hotkey
- **Adjustable overlay font & opacity** — resize text and control transparency on the fly
- **Searchable answer history** — JSON-backed history panel with full-text search and Markdown export
- **Persistent settings** — remembers preferences across restarts
- **Dark / Light themes** — Apple-inspired UI
- **Process name masking** — stealth process name for enhanced privacy
- **Multi-provider support** — Groq, OpenAI (GPT-4o), and Ollama (local models)
- **Auto-update checker** — notifies of new GitHub releases

## Architecture

### How It Works

The application follows a simple pipeline — audio goes in, answers come out:

```mermaid
graph LR
    MIC["Microphone /<br/>System Audio"] --> CAP["Audio Capture<br/>(sounddevice)"]
    CAP --> VAD["Speech Detection<br/>(WebRTC VAD)"]
    VAD --> STT["Speech-to-Text<br/>(Groq Whisper)"]
    STT --> DET{"Is it a<br/>question?"}
    DET -->|Yes| LLM["Generate Answer<br/>(Groq LLaMA 3.3)"]
    DET -->|No| SKIP["Skip"]
    LLM --> DISP["Display in<br/>Overlay / Window"]
    LLM --> HIST["Save to<br/>History"]
```

### Application Windows

The user moves through the application in a straightforward flow:

```mermaid
graph LR
    CFG["Settings"] -->|"Start"| TEST["Test Mode<br/>(standard window)"]
    CFG -->|"Start"| OVER["Overlay Mode<br/>(stealth fullscreen)"]
    CFG -->|"History"| HIST["History Viewer"]
    TEST -->|"Stop"| CFG
    OVER -->|"Escape / F3×2"| CFG
    HIST -->|"Close"| CFG
```

| Window | Purpose |
|--------|---------|
| **ConfigWindow** | Select audio source, language, topic, whisper prompt, theme. Entry point. |
| **TestModeWindow** | Standard window showing live log + Q&A. For debugging and development. |
| **OverlayWindow** | Transparent always-on-top window. Invisible to screen capture (Win/Mac). Controlled entirely via hotkeys. |
| **HistoryWindow** | Browse and search all past Q&A entries. |

### Platform Abstraction

Each platform-specific concern is handled by a dedicated abstraction:

| Concern | Linux | Windows | macOS |
|---------|-------|---------|-------|
| Audio sources | PulseAudio (`pactl`) | `sounddevice` (WASAPI) | `sounddevice` (CoreAudio) |
| Global hotkeys | `evdev` (raw `/dev/input`) | `pynput` | `pynput` |
| Screen capture exclusion | Not available | `SetWindowDisplayAffinity` | `NSWindow.sharingType` |

### File Structure

| File | Description |
|------|-------------|
| `audio_detector_gui.py` | Main application — all windows, worker, hotkey manager |
| `screen_capture.py` | Screen capture module — mss-based capture + vision LLM analysis |
| `context_manager.py` | Resume/JD parser and context prompt builder |
| `languages.py` | 52-language registry with question word detection |
| `modern_widgets.py` | Custom themed Qt widgets (ModernCard, ModernButton, ModernToggle, etc.) |
| `styles.py` | Color palette, QSS stylesheet generator, QPalette theme applicator |
| `providers/` | Modular AI provider backends (Groq, OpenAI, Ollama) |
| `build.py` | PyInstaller build script, auto-detects platform |
| `launch.sh` | Linux / macOS launcher (auto-creates `.venv`) |
| `launch.bat` | Windows launcher |
| `requirements.txt` | Python dependencies with platform-conditional entries |
| `.env` | API keys (not committed to git) |

### Processing Pipeline Detail

| Step | Technology | What happens |
|------|-----------|--------------|
| 1. Capture | `sounddevice` | Records audio in 100ms blocks from selected input device |
| 2. Buffering | NumPy | Accumulates audio chunks in memory (2–15 seconds) |
| 3. Speech detection | WebRTC VAD / RMS | Detects silence boundaries to split audio into speech segments |
| 4. Transcription | Groq Whisper `large-v3` | Converts speech to text, uses custom prompt + prior context for accuracy |
| 5. Question detection | Heuristics | Checks for question words and punctuation patterns |
| 6. Answer generation | Groq LLaMA 3.3 70B | Generates answer using conversation memory (last 10 Q&A pairs) |
| 7. Display | PyQt5 QTextEdit | Renders answer as styled HTML in the active window |

## Platform Support

| Feature | Linux | Windows | macOS |
|---------|-------|---------|-------|
| **Screen capture exclusion** | Not available | `SetWindowDisplayAffinity` | `NSWindow.sharingType` |
| **Audio sources** | PulseAudio (`pactl`) | `sounddevice` (WASAPI) | `sounddevice` (CoreAudio) |
| **Global hotkeys** | `evdev` (raw input) | `pynput` | `pynput` |
| **Standalone build** | `dist/AudioQuestionDetector` | `dist/AudioQuestionDetector.exe` | `dist/AudioQuestionDetector.app` |

## Quick Start

### Prerequisites

- **Python 3.9+**
- **Groq API key** — [Get one](https://console.groq.com/keys)

### Installation

```bash
git clone https://github.com/Alkaness/audio_question_detector.git
cd audio_question_detector

# Create .env
echo "GROQ_API_KEY=your_key_here" > .env

# Setup virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows
pip install -r requirements.txt

# Run
python3 audio_detector_gui.py
```

Or use the launcher script:
```bash
./launch.sh     # Linux / macOS (auto-creates venv)
launch.bat      # Windows
```

### Platform-Specific Setup

<details>
<summary><b>Linux</b></summary>

```bash
sudo apt-get install python3-pyqt5 pulseaudio-utils
sudo usermod -aG input $USER   # Required for global hotkeys
# Log out and back in for group changes to take effect
```
</details>

<details>
<summary><b>Windows</b></summary>

To capture system audio, enable **Stereo Mix**:
1. Right-click speaker icon → Sound settings → Recording tab
2. Right-click → Show Disabled Devices → Enable Stereo Mix

If unavailable, install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/).
</details>

<details>
<summary><b>macOS</b></summary>

- Requires **macOS 12+ (Monterey)** for screen capture exclusion
- Grant **Accessibility** and **Screen Recording** permissions when prompted
- For system audio capture, install [BlackHole](https://github.com/ExistentialAudio/BlackHole)
</details>

## Configuration

| Option | Description |
|--------|-------------|
| **Audio Source** | System audio monitor or microphone |
| **Interview Type** | Coding (enables screen capture) or Non-Coding |
| **Display Mode** | Test Mode (windowed) or Overlay Mode (transparent fullscreen) |
| **Language** | Answer language — 52 options with type-to-filter |
| **Topic** | Context topic for better answers (e.g. "React interview", "System design") |
| **Whisper Prompt** | Keywords to improve transcription accuracy |
| **Resume Upload** | Upload PDF/DOCX/TXT resume for personalized answers |
| **Job Description** | Paste JD text for targeted responses |
| **Theme** | Dark / Light mode toggle |
| **Overlay Area** | Custom screen region for the overlay |
| **Live Transcript** | Show all transcribed speech (toggle on/off) |

## Overlay Hotkeys

All hotkeys require **double-press** within 400ms:

| Key | Action |
|-----|--------|
| `F1` ×2 | Hide overlay (go silent) |
| `F2` ×2 | Restore overlay |
| `F3` ×2 | Quit application |
| `F4` ×2 | Copy last answer to clipboard |
| `F6` ×2 | Capture screen (coding mode) |
| `F7` ×2 | Increase overlay opacity |
| `F8` ×2 | Decrease overlay opacity |
| `F9` ×2 | Increase font size |
| `F10` ×2 | Decrease font size |
| `F11` ×2 | Scroll overlay up |
| `F12` ×2 | Scroll overlay down |
| `Escape` | Close overlay, return to Settings |

## Screen Sharing Privacy

| Platform | Method | Result |
|----------|--------|--------|
| **Windows** | `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` | Overlay invisible to all capture tools |
| **macOS 12+** | `NSWindow.sharingType = .none` | Overlay invisible to screenshots, recording, AirPlay |
| **Linux** | No API available | Share a specific window (not full screen) as workaround |

## Building Standalone Executable

```bash
pip install pyinstaller
python build.py
```

Output:
- **Linux**: `dist/AudioQuestionDetector`
- **Windows**: `dist/AudioQuestionDetector.exe`
- **macOS**: `dist/AudioQuestionDetector.app`

## Answer History

All Q&A pairs are saved automatically to `~/.audio_detector_history.json`.

Access via **View History** in Settings:
- Full-text search across questions and answers
- Clear all history
- Timestamps, language, and topic metadata per entry

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

## Terms of Use

This project is released for **educational and research purposes only**. It serves as a technical demonstration of:

- Real-time audio stream processing with Python
- Voice activity detection (WebRTC VAD)
- Speech-to-text via the Groq Whisper API
- Large language model integration (LLaMA 3.3)
- Cross-platform desktop application development with PyQt5
- Stealth window management on Windows, macOS, and Linux

**You must not use this software to gain an unfair advantage in any interview, examination, certification, academic assessment, or competitive setting.** Doing so may violate the policies of the administering organization, academic integrity codes, employment agreements, or applicable laws. The authors disclaim all liability for any consequences resulting from misuse.

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.

---

<p align="center">
  Built with <a href="https://groq.com">Groq</a> · <a href="https://www.python.org">Python</a> · <a href="https://riverbankcomputing.com/software/pyqt/">PyQt5</a>
</p>
