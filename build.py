#!/usr/bin/env python3
"""
Build script for Audio Question Detector — creates standalone executable.
Uses PyInstaller to bundle as .exe (Windows), .app (macOS), or AppImage-ready (Linux).

Usage:
    pip install pyinstaller
    python build.py
"""
import subprocess
import sys
import platform

APP_NAME = "AudioQuestionDetector"
MAIN_SCRIPT = "audio_detector_gui.py"

# Hidden imports that PyInstaller might miss
HIDDEN_IMPORTS = [
    "sounddevice",
    "numpy",
    "groq",
    "dotenv",
    "PyQt5",
    "PyQt5.QtWidgets",
    "PyQt5.QtCore",
    "PyQt5.QtGui",
    "styles",
    "modern_widgets",
    "providers",
    "providers.base",
    "providers.groq_provider",
    "providers.openai_provider",
    "providers.ollama_provider",
]

# Data files to include
DATA_FILES = []

def build():
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--windowed",
        f"--name={APP_NAME}",
        "--clean",
    ]

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Platform-specific hidden imports
    system = platform.system()
    if system == "Linux":
        cmd.extend(["--hidden-import", "evdev"])
    elif system == "Windows":
        cmd.extend(["--hidden-import", "pynput"])
        cmd.extend(["--hidden-import", "pynput.keyboard"])
    elif system == "Darwin":
        cmd.extend(["--hidden-import", "pynput"])
        cmd.extend(["--hidden-import", "pynput.keyboard"])
        cmd.extend(["--hidden-import", "AppKit"])

    # Optional: webrtcvad
    try:
        import webrtcvad
        cmd.extend(["--hidden-import", "webrtcvad"])
    except ImportError:
        pass

    # Add data files
    for src, dst in DATA_FILES:
        cmd.extend(["--add-data", f"{src}:{dst}"])

    # Add icon if exists
    # cmd.extend(["--icon", "icon.ico"])

    cmd.append(MAIN_SCRIPT)

    print(f"Building {APP_NAME} for {system}...")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"\n✅ Build successful!")
        print(f"   Output: dist/{APP_NAME}")
        if system == "Windows":
            print(f"   Executable: dist/{APP_NAME}.exe")
        elif system == "Darwin":
            print(f"   App bundle: dist/{APP_NAME}.app")
        else:
            print(f"   Binary: dist/{APP_NAME}")
            print(f"   To create AppImage, use linuxdeploy or appimagetool.")
    else:
        print(f"\n❌ Build failed with exit code {result.returncode}")
        sys.exit(1)


if __name__ == "__main__":
    build()
