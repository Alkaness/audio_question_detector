# Audio Question Detector

Real-time audio question detection with AI-powered answers. Captures system audio, detects questions via Whisper (Groq), and generates instant answers using LLaMA 3.3.

## Platform Versions

| Folder | Platform | Screen Capture Exclusion |
|--------|----------|--------------------------|
| [`linux/`](linux/) | Ubuntu / Fedora (Wayland & X11) | ❌ Not possible on Linux |
| [`windows/`](windows/) | Windows 10/11 | ✅ `SetWindowDisplayAffinity` — overlay invisible to capture |

## Quick Start

1. Choose your platform folder (`linux/` or `windows/`)
2. Read the platform-specific `README.md` inside
3. Create a `.env` file with your Groq API key
4. Run the launcher script (`launch.sh` or `launch.bat`)

## Features

- 🎤 Real-time audio capture (system audio or microphone)
- 🧠 VAD-based speech chunking with Whisper transcription
- 💡 AI-powered answers via Groq LLaMA 3.3 70B
- 🔒 Overlay mode with transparent, click-through fullscreen display
- ⌨️ Global hotkeys (F1×2 hide, F2×2 show, F3×2 quit)
- 🇺🇦 Answers in Ukrainian

## License

MIT
