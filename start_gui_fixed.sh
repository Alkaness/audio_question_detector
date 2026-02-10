#!/bin/bash

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║          Запуск GUI - Програма-Підказувач                      ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Активація віртуального середовища
if [ ! -d "venv" ]; then
    echo "❌ Віртуальне середовище не знайдено!"
    exit 1
fi

source venv/bin/activate

# Перевірка API ключа
API_KEY=$(python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('GROQ_API_KEY', ''))" 2>/dev/null)

if [ -z "$API_KEY" ] || [ "$API_KEY" == "your_groq_api_key_here" ]; then
    echo "⚠️  УВАГА: Groq API ключ не налаштований!"
    echo ""
    echo "Отримайте ключ на: https://console.groq.com/keys"
    echo "Додайте в файл .env: GROQ_API_KEY=ваш_ключ"
    echo ""
fi

echo "✅ Запуск GUI..."
echo ""

# Визначити найкращу платформу
if [ "$XDG_SESSION_TYPE" == "wayland" ]; then
    echo "Виявлено Wayland сесію"
    # Для Gnome на Wayland використаємо XWayland (більш стабільно)
    if [ "$GDMSESSION" == "ubuntu" ] || [ "$GDMSESSION" == "gnome" ]; then
        echo "Використовую XWayland для кращої сумісності..."
        export QT_QPA_PLATFORM=xcb
        export GDK_BACKEND=x11
    else
        export QT_QPA_PLATFORM=wayland
    fi
else
    echo "Використовую X11"
    export QT_QPA_PLATFORM=xcb
fi

# Запуск
python audio_detector_gui.py

