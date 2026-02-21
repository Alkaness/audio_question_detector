
# Apple-like UI/UX Styles

# Color Palette (iOS 15+ / macOS Monterey+)
COLORS = {
    "light": {
        "bg": "#F2F2F7",         # System Grouped Background
        "card": "#FFFFFF",       # Secondary System Grouped Background
        "text_primary": "#000000",
        "text_secondary": "#3C3C43", # Darker gray for readability
        "accent": "#007AFF",     # System Blue
        "accent_hover": "#0062CC",
        "danger": "#FF3B30",     # System Red
        "success": "#34C759",    # System Green
        "border": "#C6C6C8",     # Darker border for visibility
        "input_bg": "#EFEFF4",   # Slightly gray input to pop against white card
        "shadow": "rgba(0, 0, 0, 0.15)"
    },
    "dark": {
        "bg": "#000000",         # System Background
        "card": "#1C1C1E",       # Secondary System Grouped Background
        "text_primary": "#FFFFFF",
        "text_secondary": "#98989D",
        "accent": "#0A84FF",     # System Blue Dark Mode
        "accent_hover": "#007AFF",
        "danger": "#FF453A",
        "success": "#32D74B",
        "border": "#38383A",
        "input_bg": "#2C2C2E",       # Tertiary System Grouped Background
        "shadow": "rgba(0, 0, 0, 0.3)"
    }
}

FONTS = {
    "ui": "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;",
    "mono": "font-family: 'SF Mono', 'Segoe UI Mono', 'Roboto Mono', monospace;",
}

def get_stylesheet(theme="dark"):
    c = COLORS[theme]
    
    return f"""
    QMainWindow, QDialog, QWidget#ConfigWindow {{
        background-color: {c['bg']};
        color: {c['text_primary']};
        {FONTS['ui']}
    }}

    QLabel {{
        color: {c['text_primary']};
        font-size: 14px;
        {FONTS['ui']}
    }}
    
    QLabel#Title {{
        font-size: 24px;
        font-weight: bold;
        color: {c['text_primary']};
        margin-bottom: 10px;
    }}

    QLabel#Subtitle {{
        font-size: 13px;
        color: {c['text_primary']};
        font-weight: normal;
    }}

    /* QComboBox Styling */
    QComboBox {{
        background-color: {c['input_bg']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        padding: 5px 10px;
        font-size: 14px;
        {FONTS['ui']}
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 20px;
        border-left-width: 0px;
        border-top-right-radius: 8px;
        border-bottom-right-radius: 8px;
    }}
    QComboBox::down-arrow {{
        width: 0; 
        height: 0;
        border-left: 5px solid transparent;
        border-right: 5px solid transparent;
        border-top: 5px solid {c['text_secondary']};
        margin-right: 10px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {c['card']};
        color: {c['text_primary']};
        selection-background-color: {c['accent']};
        selection-color: #FFFFFF;
        border: 1px solid {c['border']};
        outline: none;
    }}

    /* Scrollbars (MacOS style) */
    QScrollBar:vertical {{
        border: none;
        background: {c['bg']};
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {c['border']};
        min-height: 20px;
        border-radius: 5px;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    """
    
def apply_theme_palette(app, theme="dark"):
    """Apply global QPalette to the application"""
    from PyQt5.QtGui import QPalette, QColor
    from PyQt5.QtCore import Qt

    c = COLORS[theme]
    palette = QPalette()
    
    # Map theme colors to QPalette roles
    palette.setColor(QPalette.Window, QColor(c['bg']))
    palette.setColor(QPalette.WindowText, QColor(c['text_primary']))
    palette.setColor(QPalette.Base, QColor(c['input_bg']))
    palette.setColor(QPalette.AlternateBase, QColor(c['card']))
    palette.setColor(QPalette.ToolTipBase, QColor(c['card']))
    palette.setColor(QPalette.ToolTipText, QColor(c['text_primary']))
    palette.setColor(QPalette.Text, QColor(c['text_primary']))
    palette.setColor(QPalette.Button, QColor(c['card']))
    palette.setColor(QPalette.ButtonText, QColor(c['text_primary']))
    palette.setColor(QPalette.BrightText, QColor(c['accent']))
    palette.setColor(QPalette.Link, QColor(c['accent']))
    palette.setColor(QPalette.Highlight, QColor(c['accent']))
    palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    
    # Disabled state (simple dimming)
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(c['text_secondary']))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(c['text_secondary']))

    app.setPalette(palette)
    
    # Also set global stylesheet for common controls if not handled by widgets
    # This helps with message boxes, menus, etc.
    app.setStyleSheet(get_stylesheet(theme))
