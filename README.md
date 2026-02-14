# Audio Question Detector

A real-time audio recognition and AI answering system. The application captures audio from desktop calls (Discord, Google Meet, Telegram, Zoom), transcribes speech using Groq Whisper, and generates concise answers using Groq LLM — all displayed in a GUI overlay or a standalone window.

## Table of Contents

- [Features](#features)
- [System Requirements](#system-requirements)
- [Installation](#installation)
  - [Linux (Ubuntu/Debian)](#linux-ubuntudebian)
  - [macOS](#macos)
  - [Windows](#windows)
- [Configuration](#configuration)
- [Usage](#usage)
  - [GUI Application](#gui-application)
  - [Console Version](#console-version)
  - [Overlay Mode Hotkeys](#overlay-mode-hotkeys)
- [Architecture](#architecture)
- [Troubleshooting](#troubleshooting)
- [Privacy and Data Handling](#privacy-and-data-handling)
- [API Rate Limits](#api-rate-limits)
- [License](#license)

---

## Features

- **Real-time audio capture** from any system audio source (Monitor/Loopback devices)
- **Speech-to-text** via Groq Whisper Large v3 with automatic language detection
- **VAD-based chunking** — silence detection splits audio at natural pauses instead of fixed intervals
- **LLM-powered correction** of garbled technical terms (e.g., "paithan" to "Python")
- **Conversational memory** — retains the last 10 Q&A exchanges for context-aware follow-up answers
- **Multi-window architecture:**
  - **Configuration Window** — select audio source and operating mode
  - **Test Mode** — standard window with live log, Q&A display, and stop control
  - **Overlay Mode** — fullscreen semi-transparent overlay, invisible to screen capture and the taskbar, with global hotkey control
- **Desktop integration** — installable as a GNOME application launcher (no terminal required)

---

## System Requirements

| Component | Minimum |
|-----------|---------|
| Python | 3.10+ |
| OS | Linux (Ubuntu 22.04+), macOS 12+, Windows 10+ |
| API | Groq account (free tier: https://console.groq.com) |
| Audio | PulseAudio, PipeWire (Linux), CoreAudio (macOS), WASAPI (Windows) |

---

## Installation

### Linux (Ubuntu/Debian)

**1. Install system dependencies**

```bash
sudo apt-get update
sudo apt-get install -y libportaudio2 portaudio19-dev pulseaudio pavucontrol python3-venv
```

**2. Clone and set up the project**

```bash
cd ~/interview_help
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Configure the API key**

Obtain a free API key from https://console.groq.com/keys and create a `.env` file:

```bash
echo "GROQ_API_KEY=your_key_here" > .env
```

**4. (Optional) Enable global hotkeys for Overlay Mode**

Overlay Mode global hotkeys require read access to `/dev/input/` via the `evdev` library. Add your user to the `input` group:

```bash
sudo usermod -aG input $USER
```

Log out and log back in for the group change to take effect.

**5. Launch the application**

```bash
# Via desktop launcher (no terminal)
./launch.sh

# Or via terminal with debug output
./start_gui_fixed.sh
```

The application is also available in the GNOME Activities menu as "Audio Question Detector" after installation.

---

### macOS

**1. Install system dependencies**

Install Homebrew (https://brew.sh) if not already present, then install PortAudio:

```bash
brew install portaudio
```

**2. Clone and set up the project**

```bash
cd ~/interview_help
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

On Apple Silicon (M1/M2/M3), if `PyAudio` or `sounddevice` fail to build, install with:

```bash
CFLAGS="-I$(brew --prefix portaudio)/include" \
LDFLAGS="-L$(brew --prefix portaudio)/lib" \
pip install sounddevice
```

**3. Configure the API key**

```bash
echo "GROQ_API_KEY=your_key_here" > .env
```

**4. Audio routing**

macOS does not expose a system audio loopback device by default. You need a virtual audio driver to capture desktop audio:

- **BlackHole** (free, open-source): https://existential.audio/blackhole/
  - Install BlackHole 2ch
  - Open Audio MIDI Setup, create a Multi-Output Device combining your speakers and BlackHole
  - Set the Multi-Output Device as the system default
  - In the application, select "BlackHole 2ch" as the input source

- **Loopback** (paid, by Rogue Amoeba): https://rogueamoeba.com/loopback/

**5. Launch**

```bash
source venv/bin/activate
python audio_detector_gui.py
```

Note: Overlay Mode stealth features (X11 window type hints, `evdev` hotkeys) are Linux-specific. On macOS, Overlay Mode functions as a standard always-on-top transparent window. Global hotkeys are not available on macOS.

---

### Windows

**1. Install Python**

Download Python 3.12+ from https://www.python.org/downloads/ and install it. Ensure "Add Python to PATH" is checked during installation.

**2. Set up the project**

Open PowerShell or Command Prompt in the project directory:

```powershell
cd C:\path\to\interview_help
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

If `sounddevice` fails to install, you may need the Microsoft Visual C++ Build Tools: https://visualstudio.microsoft.com/visual-cpp-build-tools/

**3. Configure the API key**

Create a `.env` file in the project root with the following content:

```
GROQ_API_KEY=your_key_here
```

**4. Audio routing**

Windows requires a virtual audio cable to capture desktop audio:

- **VB-Audio Virtual Cable** (free): https://vb-audio.com/Cable/
  - Install VB-CABLE
  - In Windows Sound Settings > App volume and device preferences, set the target application's output to "CABLE Input (VB-Audio Virtual Cable)"
  - Keep your default playback device set to your speakers
  - In the application, select "CABLE Output (VB-Audio Virtual Cable)" as the input source

- **VoiceMeeter** (free, more advanced): https://vb-audio.com/Voicemeeter/

**5. Launch**

```powershell
.\venv\Scripts\Activate.ps1
python audio_detector_gui.py
```

Note: Overlay Mode stealth features and `evdev`-based global hotkeys are Linux-specific and are not available on Windows. Overlay Mode will function as a standard always-on-top transparent window.

---

## Configuration

Key parameters can be adjusted in `audio_detector_gui.py` (or `audio_question_detector.py` for the console version):

| Parameter | Default | Description |
|-----------|---------|-------------|
| `SAMPLE_RATE` | 16000 | Audio sample rate in Hz |
| `SILENCE_THRESHOLD` | 0.01 | Amplitude threshold for speech detection |
| `MIN_CHUNK_DURATION` | 2 | Minimum seconds of speech before processing |
| `MAX_CHUNK_DURATION` | 15 | Maximum chunk duration before forced split |
| `SILENCE_DURATION` | 0.6 | Duration of silence (seconds) to trigger a split |
| `VAD_THRESHOLD` | 0.008 | RMS threshold for VAD silence detection |
| `CONTEXT_KEYWORDS` | `[]` | Keyword filter (empty = answer all recognized text) |

### AI Model Selection

The application uses two Groq models:

- **Whisper Large v3** — speech-to-text transcription
- **Llama 3.3 70B Versatile** — answer generation (high quality, contextual)
- **Llama 3.1 8B Instant** — transcription correction (fast, lightweight)

To change the answer generation model, modify the `model` parameter in the `answer_question` method.

---

## Usage

### GUI Application

Launch the Configuration Window, select an audio source and mode, then click Start.

```bash
./launch.sh
```

**Audio source selection:** Choose a Monitor/Loopback device to capture system audio. Microphone devices capture only local input.

**Test Mode** opens a standard window with:
- Real-time processing log
- Q&A display with formatted question-answer blocks
- Stop button to return to the Configuration Window

**Overlay Mode** opens a fullscreen transparent overlay with:
- Semi-transparent dark background
- Q&A content rendered over other applications
- Invisible to the system taskbar (`Qt.Tool` flag)
- Invisible to screen sharing applications (X11 `_NET_WM_WINDOW_TYPE_NOTIFICATION`)
- Mouse clicks pass through to underlying windows

### Console Version

```bash
source venv/bin/activate
python audio_question_detector.py
```

Follow the interactive prompts to select an audio device. Transcriptions and answers are printed to stdout.

### Overlay Mode Hotkeys

All hotkeys require a double-press within 400ms to prevent accidental activation. Hotkeys require `evdev` and `input` group membership (Linux only).

| Hotkey | Action |
|--------|--------|
| F1 x2 | Hide the overlay (enter silent mode) |
| F2 x2 | Restore the overlay (exit silent mode) |
| F3 x2 | Terminate the application |
| Escape | Close overlay and return to Configuration Window |

### Screen Sharing Privacy

The overlay uses multi-layered stealth to avoid appearing in screen shares:

- **`_NET_WM_WINDOW_TYPE_NOTIFICATION`** — tells the window manager to treat the window as a transient notification
- **`_NET_WM_BYPASS_COMPOSITOR`** — requests the GPU to render the window outside the compositor's buffer, making it invisible to XComposite/XSHM-based capture tools
- **`_NET_WM_STATE_SKIP_TASKBAR`** — hides from taskbar, pager, and Alt-Tab
- **`Qt.Tool | Qt.WindowTransparentForInput`** — hides from the taskbar and passes mouse clicks through

**Important:** These hints are effective only on **X11/Xorg sessions**. On **Wayland** (default on modern Ubuntu/Fedora), PipeWire captures the final composited framebuffer and no API exists to exclude individual windows. Linux has no equivalent to Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`.

**Recommended workarounds for Wayland:**

1. **Share a specific window** — in Google Meet, select the "Window" tab and share only the browser or app window, not the entire screen. The overlay is a separate window and will not be included.
2. **Use a second monitor** — place the overlay on monitor 2 and share only monitor 1.
3. **Toggle visibility** — press F1 x2 to hide the overlay before sharing, press F2 x2 to restore it afterwards.
4. **Switch to X11** — log out, select "Ubuntu on Xorg" at the login screen, and log back in for best-effort stealth.

---

## Architecture

```
audio_detector_gui.py
├── AudioDetectorWorker      # Audio capture, VAD, transcription, LLM pipeline
│   ├── audio_callback()     # Sounddevice callback → queue
│   ├── run()                # Main loop: buffer → VAD split → process
│   ├── transcribe_audio()   # Groq Whisper API call
│   ├── correct_transcription()  # LLM-based term correction
│   └── answer_question()    # LLM answer generation with conversation history
├── ConfigWindow             # Mode/source selection launcher
├── TestModeWindow           # Standard window with log + Q&A
├── OverlayWindow            # Stealth fullscreen overlay
└── HotkeyManager            # evdev-based global hotkey listener
```

### Processing Pipeline

1. Audio is captured in 100ms blocks via `sounddevice.InputStream`
2. Blocks accumulate in a list-based buffer (O(1) append)
3. VAD scans the buffer for silence gaps after the minimum chunk duration
4. On detection of a silence gap, the chunk is split and sent for processing
5. Whisper transcribes the audio with a sliding context window prompt
6. An LLM corrects garbled technical terms (conservative, length-guarded)
7. A second LLM call generates a concise answer with the full conversation history
8. The Q&A pair is emitted to the GUI via Qt signals

---

## Troubleshooting

### GUI does not start

Wayland/X11 platform conflict. Use the provided launch script which sets `QT_QPA_PLATFORM=xcb` automatically:

```bash
./start_gui_fixed.sh
```

### No audio detected from calls

Verify that you have selected a Monitor/Loopback device, not a microphone. Monitor devices capture system audio output, which includes call audio. List available sources:

```bash
pactl list sources short
```

### Invalid sample rate error

The application auto-detects the device's native sample rate. If the error persists, ensure the selected device is active and not claimed exclusively by another application.

### API errors or "Model decommissioned"

1. Verify the API key is valid at https://console.groq.com/keys
2. Check that the `.env` file contains `GROQ_API_KEY=your_key` with no extra whitespace
3. Confirm internet connectivity
4. Check Groq service status at https://status.groq.com

### PyQt5 installation failure

On Ubuntu, install the system package as a fallback:

```bash
sudo apt-get install python3-pyqt5
```

### Global hotkeys not working (Overlay Mode)

Hotkeys require the `evdev` library and membership in the `input` group:

```bash
sudo usermod -aG input $USER
# Log out and log back in
```

Verify with: `groups | grep input`

---

## Privacy and Data Handling

- Audio data is sent to Groq's servers for transcription and answer generation
- No audio is stored locally or on remote servers beyond the duration of API processing
- Transcriptions are held in memory only during the application session
- Review Groq's privacy policy: https://groq.com/privacy-policy/

For fully offline operation, consider replacing the Groq API with:
- **Whisper.cpp** — local speech-to-text inference
- **Ollama** with a Llama model — local LLM inference

---

## API Rate Limits

Groq's free tier provides sufficient capacity for extended use:

| Resource | Limit |
|----------|-------|
| Whisper API | ~30 requests/minute |
| LLM API (Llama) | 30 requests/minute, 6,000 requests/day |
| LLM tokens | ~7,000 tokens/minute |

With VAD-based chunking, the application typically generates 2-6 API calls per minute, well within free tier limits.

---

## Project Structure

```
interview_help/
├── audio_detector_gui.py          # GUI application (multi-window)
├── audio_question_detector.py     # Console application
├── launch.sh                      # Silent launcher (no terminal window)
├── start_gui_fixed.sh             # Terminal launcher with debug output
├── requirements.txt               # Python dependencies
├── .env                           # API keys (user-created, not tracked)
├── .env.example                   # Example .env template
└── README.md                      # This documentation
```

---

## License

This project is provided as-is for educational and personal use.

---

## Acknowledgments

- **Groq** — high-speed AI inference API
- **OpenAI** — Whisper speech recognition model
- **Meta** — Llama large language models
- **VB-Audio** — virtual audio cable software (Windows)
- **Existential Audio** — BlackHole virtual audio driver (macOS)
