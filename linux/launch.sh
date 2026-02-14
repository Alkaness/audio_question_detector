#!/bin/bash
# Silent launcher for Audio Question Detector (no terminal needed)
cd "$(dirname "$0")"

# Activate venv
source venv/bin/activate

# Set display platform
if [ "$XDG_SESSION_TYPE" == "wayland" ]; then
    if [ "$GDMSESSION" == "ubuntu" ] || [ "$GDMSESSION" == "gnome" ]; then
        export QT_QPA_PLATFORM=xcb
        export GDK_BACKEND=x11
    else
        export QT_QPA_PLATFORM=wayland
    fi
else
    export QT_QPA_PLATFORM=xcb
fi

# Launch GUI (stderr to log file for debugging)
exec python audio_detector_gui.py 2>>"$HOME/.cache/audio-detector.log"
