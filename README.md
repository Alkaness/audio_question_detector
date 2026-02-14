# Audio Question Detector

Real-time audio question detection with AI-powered answers. Captures system audio, detects questions via Whisper (Groq), and generates instant answers using LLaMA 3.3.

**Cross-platform** — auto-detects Linux/Windows and uses the appropriate APIs.

## Platform Support

| Feature | Linux | Windows |
|---------|-------|---------|
| **Screen capture exclusion** | ❌ Not possible | ✅ `SetWindowDisplayAffinity` |
| **Audio sources** | PulseAudio (`pactl`) | `sounddevice` (WASAPI) |
| **Global hotkeys** | `evdev` (raw input) | `pynput` (cross-platform) |

## Requirements

- **Python 3.9+**
- **Groq API key** — [Get one](https://console.groq.com/keys)

### Linux additional requirements

```bash
sudo apt-get install python3-pyqt5 pulseaudio-utils
sudo usermod -aG input $USER  # for global hotkeys
# Log out and back in
```

### Windows additional requirements

To capture system audio, enable **Stereo Mix**:
1. Right-click speaker icon → Sound settings → Recording tab
2. Right-click → Show Disabled Devices → Enable Stereo Mix

If unavailable, install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/).

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Alkaness/audio_question_detector.git
cd audio_question_detector
```

2. Create `.env` file:
```
GROQ_API_KEY=your_groq_api_key_here
```

3. Install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate    # Linux
# venv\Scripts\activate     # Windows
pip install -r requirements.txt
```

4. Run:
```bash
python3 audio_detector_gui.py
# or use launch.sh (Linux) / launch.bat (Windows)
```

## Usage

### Modes

| Mode | Description |
|------|-------------|
| **Test Mode** | Standard window with log output and Q&A display |
| **Overlay Mode** | Transparent fullscreen overlay (always on top, click-through) |

### Overlay Hotkeys

| Key | Action |
|-----|--------|
| F1 x2 | Hide overlay |
| F2 x2 | Restore overlay |
| F3 x2 | Terminate the application |
| Escape | Close overlay → Settings |

### Screen Sharing Privacy (Windows only)

On Windows, the overlay uses `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` making it **invisible** to:
- Google Meet / Zoom / Teams screen sharing
- OBS Studio
- PrintScreen / Snipping Tool

On Linux, screen capture exclusion is not possible. Workarounds:
1. Share a **specific window** instead of full screen
2. Toggle overlay visibility with F1×2 / F2×2

## Features

- 🎤 Real-time audio capture (system audio or microphone)
- 🧠 VAD-based speech chunking with Whisper transcription
- 💡 AI-powered answers via Groq LLaMA 3.3 70B
- 🔒 Overlay mode with transparent, click-through fullscreen display
- ⌨️ Global hotkeys (F1×2 hide, F2×2 show, F3×2 quit)
- 🇺🇦 Answers in Ukrainian

## Architecture

```
audio_detector_gui.py      — Main GUI application (cross-platform)
audio_question_detector.py — CLI version (no GUI)
requirements.txt           — Python dependencies (platform-conditional)
launch.sh                  — Linux launcher
launch.bat                 — Windows launcher
.env                       — API key (not committed)
```

## License

MIT
