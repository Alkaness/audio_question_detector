# Audio Question Detector — Windows Version

Real-time audio question detector with AI-powered answers. Captures system audio, detects questions using Whisper, and generates answers using Groq LLaMA.

## ✅ Screen Sharing Privacy

**On Windows, the overlay is INVISIBLE to screen capture by default.**

Uses `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` — a native Windows API that excludes the overlay from:
- Google Meet / Zoom / Teams screen sharing
- OBS Studio recording
- PrintScreen / Snipping Tool
- Any screen capture tool

The overlay remains fully visible to you on your monitor.

## Requirements

- **Windows 10** (version 2004+) or **Windows 11**
- **Python 3.9+** — [Download](https://www.python.org/downloads/)
- **Groq API key** — [Get one](https://console.groq.com/keys)

### System Audio Capture

To capture system audio on Windows, enable **Stereo Mix**:

1. Right-click the speaker icon in the taskbar → **Sound settings**
2. Go to **Recording** tab
3. Right-click → **Show Disabled Devices**
4. Enable **Stereo Mix**

If Stereo Mix is not available, install [VB-Audio Virtual Cable](https://vb-audio.com/Cable/).

## Installation

1. Clone the repo and switch to the windows branch:
```bash
git clone https://github.com/yourusername/audio_question_detector.git
cd audio_question_detector
git checkout windows
```

2. Create `.env` file:
```
GROQ_API_KEY=your_groq_api_key_here
```

3. Run `launch.bat` — it will create a venv and install dependencies automatically.

Or manually:
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python audio_detector_gui.py
```

## Usage

### Modes

| Mode | Description |
|------|-------------|
| **Test Mode** | Standard window with log output and Q&A display |
| **Overlay Mode** | Transparent fullscreen overlay — **invisible to screen capture** |

### Overlay Hotkeys

| Key | Action |
|-----|--------|
| F1 x2 | Hide overlay |
| F2 x2 | Restore overlay |
| F3 x2 | Terminate the application |
| Escape | Close overlay and return to Settings |

## Architecture

```
audio_detector_gui.py    — Main application (all GUI + logic)
audio_question_detector.py — CLI version (no GUI)
requirements.txt         — Python dependencies
launch.bat               — Windows launcher
.env                     — API key (not committed)
```

## Differences from Linux Version

| Feature | Linux | Windows |
|---------|-------|---------|
| **Screen capture exclusion** | ❌ Not possible | ✅ `SetWindowDisplayAffinity` |
| **Audio sources** | PulseAudio (`pactl`) | `sounddevice` (WASAPI) |
| **Hotkeys** | `evdev` (raw input) | `pynput` (cross-platform) |
| **Launch script** | `launch.sh` | `launch.bat` |
