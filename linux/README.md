# Audio Question Detector — Linux

Real-time audio question detector with AI-powered answers for Ubuntu / Fedora (Wayland & X11).

> ⚠️ **Screen sharing limitation:** On Linux there is no API to exclude windows from screen capture. The overlay **will be visible** in Google Meet / Zoom screen shares. See [Workarounds](#workarounds) below.

## Requirements

- **Ubuntu 22.04+** / Fedora 38+ (Wayland or X11)
- **Python 3.9+**
- **PulseAudio** (for audio source listing via `pactl`)
- **Groq API key** — [Get one](https://console.groq.com/keys)

### System dependencies

```bash
sudo apt-get install python3-pyqt5 pulseaudio-utils
```

For global hotkeys (evdev), your user must be in the `input` group:

```bash
sudo usermod -aG input $USER
# Log out and back in for the change to take effect
```

## Installation

1. Create `.env` file in this folder:
```
GROQ_API_KEY=your_groq_api_key_here
```

2. Create virtual environment and install dependencies:
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

3. Run:
```bash
./launch.sh
# or directly:
python3 audio_detector_gui.py
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
| Escape | Close overlay → return to Settings |

## Workarounds

Since the overlay cannot be hidden from screen capture on Linux:

1. **Share a specific window** — in Google Meet, select "Window" tab → share only the browser. The overlay is a separate window and won't be included.
2. **Second monitor** — place overlay on monitor 2, share monitor 1.
3. **Toggle visibility** — press F1×2 to hide before sharing, F2×2 to restore.
4. **Use the Windows version** — switch to the `windows` branch for `SetWindowDisplayAffinity` support.

## Architecture

```
audio_detector_gui.py      — Main GUI application
audio_question_detector.py — CLI version (no GUI)
requirements.txt           — Python dependencies
launch.sh                  — Quick launcher
start_gui_fixed.sh         — Launcher with Wayland workarounds
.env                       — API key (not committed)
```
