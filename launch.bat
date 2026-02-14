@echo off
echo Starting Audio Question Detector...
cd /d "%~dp0"

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

python audio_detector_gui.py
pause
