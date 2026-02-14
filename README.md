# Audio Question Detector

Real-time audio question detection with AI-powered answers. Captures system audio, detects questions via Whisper (Groq), and generates instant answers using LLaMA 3.3.

**Cross-platform** — auto-detects Linux / Windows / macOS and uses the appropriate APIs.

## Platform Support

| Feature | Linux | Windows | macOS |
|---------|-------|---------|-------|
| **Screen capture exclusion** | ❌ Not possible | ✅ `SetWindowDisplayAffinity` | ✅ `NSWindow.sharingType` |
| **Audio sources** | PulseAudio (`pactl`) | `sounddevice` (WASAPI) | `sounddevice` (CoreAudio) |
| **Global hotkeys** | `evdev` (raw input) | `pynput` | `pynput` |

## Requirements

- **Python 3.9+**
- **Groq API key** — [Get one](https://console.groq.com/keys)

### Linux

```bash
sudo apt-get install python3-pyqt5 pulseaudio-utils
sudo usermod -aG input $USER  # for global hotkeys
# Log out and back in
```

### Windows

To capture system audio, enable **Stereo Mix**:
1. Right-click speaker icon → Sound settings → Recording tab
2. Right-click → Show Disabled Devices → Enable Stereo Mix

If unavailable, install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/).

### macOS

- Requires **macOS 12+ (Monterey)** for screen capture exclusion
- Grant **Accessibility** and **Screen Recording** permissions when prompted
- For system audio capture, install [BlackHole](https://github.com/ExistentialAudio/BlackHole)

## Installation

```bash
git clone https://github.com/Alkaness/audio_question_detector.git
cd audio_question_detector
```

Create `.env` file:
```
GROQ_API_KEY=your_groq_api_key_here
```

Install and run:
```bash
python3 -m venv venv
source venv/bin/activate       # Linux / macOS
# venv\Scripts\activate        # Windows
pip install -r requirements.txt
python3 audio_detector_gui.py
```

Or use launchers: `./launch.sh` (Linux/macOS) or `launch.bat` (Windows).

## Usage

### Settings

| Option | Description |
|--------|-------------|
| **Source** | Audio input device (system audio monitor or microphone) |
| **Mode** | Test Mode (windowed) or Overlay Mode (transparent fullscreen) |
| **Language** | Answer language (Ukrainian, English, Russian, German, French, Spanish, Polish, Chinese, Japanese) |

### Overlay Hotkeys

| Key | Action |
|-----|--------|
| F1 ×2 | Hide overlay |
| F2 ×2 | Restore overlay |
| F3 ×2 | Terminate the application |
| F4 ×2 | Copy last answer to clipboard |
| F5 ×2 | Increase font size |
| F6 ×2 | Decrease font size |
| Escape | Close overlay → Settings |

### Screen Sharing Privacy

| Platform | Method | Result |
|----------|--------|--------|
| **Windows** | `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` | Overlay invisible to all capture tools |
| **macOS 12+** | `NSWindow.sharingType = .none` | Overlay invisible to screenshots, recording, AirPlay |
| **Linux** | No API available | Share a specific window (not full screen) as workaround |

## Features

- 🎤 Real-time audio capture (system audio or microphone)
- 🧠 VAD-based speech chunking with Whisper transcription
- 💡 AI-powered answers via Groq LLaMA 3.3 70B
- 🔒 Overlay mode — invisible to screen capture on Windows & macOS
- 🌐 Configurable answer language (9 languages)
- 💬 Conversation context memory (last 10 Q&A pairs)
- 📋 Copy answers to clipboard (F4×2)
- 🔤 Adjustable font size (F5×2 / F6×2)
- ⌨️ Global hotkeys (F1-F6 double-press)

## Architecture

```
audio_detector_gui.py  — Main application (cross-platform)
requirements.txt       — Python dependencies (platform-conditional)
launch.sh              — Linux / macOS launcher
launch.bat             — Windows launcher
.env                   — API key (not committed)
```

## License

MIT
