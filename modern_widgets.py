from PyQt5.QtWidgets import (
    QPushButton, QLineEdit, QCheckBox, QFrame, QGraphicsDropShadowEffect,
    QWidget, QHBoxLayout, QLabel, QApplication, QComboBox, QStyledItemDelegate,
    QDialog, QVBoxLayout
)
from PyQt5.QtCore import Qt, QPropertyAnimation, QRect, QEasingCurve, pyqtProperty, QSize, QPoint
from PyQt5.QtGui import QColor, QPainter, QBrush, QPen, QFont, QCursor

from styles import COLORS, FONTS


class ModernCard(QFrame):
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.update_style()

    def update_style(self):
        c = COLORS[self.theme]
        self.setStyleSheet(f"""
            ModernCard {{
                background-color: {c['card']};
                color: {c['text_primary']};
                border-radius: 12px;
                border: 1px solid {c['border']};
            }}
        """)
        # Refresh shadow color
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(20)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(c['shadow']))
        self.setGraphicsEffect(shadow)


class ModernButton(QPushButton):
    def __init__(self, text, theme="dark", parent=None, accent=False):
        super().__init__(text, parent)
        self.theme = theme
        self.accent = accent
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(40)
        self.update_style()

    def update_style(self):
        c = COLORS[self.theme]
        bg = c['accent'] if self.accent else c['card']
        fg = "#FFFFFF" if self.accent else c['text_primary']
        border = "none" if self.accent else f"1px solid {c['border']}"

        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                color: {fg};
                border: {border};
                border-radius: 8px;
                font-weight: 600;
                font-size: 14px;
                padding: 5px 15px;
                {FONTS['ui']}
            }}
            QPushButton:hover {{
                background-color: {c['accent_hover'] if self.accent else c['input_bg']};
            }}
            QPushButton:pressed {{
                background-color: {c['accent'] if self.accent else c['border']};
            }}
        """)


class ModernInput(QLineEdit):
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedHeight(36)
        self.update_style()

    def update_style(self):
        c = COLORS[self.theme]
        self.setStyleSheet(f"""
            QLineEdit {{
                background-color: {c['input_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 0 10px;
                font-size: 14px;
                {FONTS['ui']}
            }}
            QLineEdit:focus {{
                border: 2px solid {c['accent']};
            }}
        """)


class ModernToggle(QCheckBox):
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setFixedSize(52, 30)
        self.setCursor(Qt.PointingHandCursor)

        # Animation
        self._position = 3.0
        self._anim = QPropertyAnimation(self, b"circle_pos")
        self._anim.setDuration(250)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)

        # Wire stateChanged → animate
        self.stateChanged.connect(self._on_state_changed)

    # ---- animated property ----
    @pyqtProperty(float)
    def circle_pos(self):
        return self._position

    @circle_pos.setter
    def circle_pos(self, val):
        self._position = val
        self.update()

    # ---- click region ----
    def hitButton(self, pos: QPoint):
        return self.contentsRect().contains(pos)

    # ---- animation driver ----
    def _on_state_changed(self, state):
        end = 25.0 if state == Qt.Checked else 3.0
        self._anim.stop()
        self._anim.setStartValue(self._position)
        self._anim.setEndValue(end)
        self._anim.start()

    # ---- programmatic set (skip animation when not visible) ----
    def setChecked(self, checked):
        self._anim.stop()
        if not self.isVisible():
            self._position = 25.0 if checked else 3.0
        super().setChecked(checked)

    # ---- paint ----
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        c = COLORS[self.theme]

        # Track
        track_color = QColor(c['accent']) if self.isChecked() else QColor(c['border'])
        p.setBrush(track_color)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, self.width(), self.height(), 15, 15)

        # Knob
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(int(self._position), 3, 24, 24)
        p.end()

    def update_style(self):
        self.update()  # repaint with new theme colors


class ModernComboBox(QComboBox):
    def __init__(self, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(36)
        self.setItemDelegate(QStyledItemDelegate())
        self.update_style()

    def update_style(self):
        c = COLORS[self.theme]
        self.setStyleSheet(f"""
            QComboBox {{
                background-color: {c['input_bg']};
                color: {c['text_primary']};
                border: 1px solid {c['border']};
                border-radius: 8px;
                padding: 5px 12px;
                font-size: 14px;
                {FONTS['ui']}
            }}
            QComboBox::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 24px;
                border: none;
            }}
            QComboBox::down-arrow {{
                width: 0; height: 0;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid {c['text_secondary']};
                margin-right: 8px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {c['card']};
                color: {c['text_primary']};
                selection-background-color: {c['accent']};
                selection-color: #FFFFFF;
                border: 1px solid {c['border']};
                border-radius: 6px;
                outline: none;
                padding: 4px;
            }}
            QComboBox QAbstractItemView::item {{
                padding: 6px 10px;
                min-height: 24px;
            }}
        """)


class ModernDialog(QDialog):
    def __init__(self, title, message, theme="dark", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setWindowTitle(title)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer)

        card = ModernCard(theme)
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(24, 24, 24, 24)
        card_layout.setSpacing(16)
        card.setLayout(card_layout)
        outer.addWidget(card)

        c = COLORS[theme]

        # Title
        lbl_title = QLabel(title)
        lbl_title.setStyleSheet(f"""
            font-size: 18px; font-weight: bold;
            color: {c['text_primary']};
            {FONTS['ui']}
        """)
        card_layout.addWidget(lbl_title)

        # Message
        lbl_msg = QLabel(message)
        lbl_msg.setWordWrap(True)
        lbl_msg.setStyleSheet(f"""
            color: {c['text_secondary']};
            font-size: 14px;
            {FONTS['ui']}
        """)
        card_layout.addWidget(lbl_msg)

        # OK button
        btn = ModernButton("OK", theme, accent=True)
        btn.clicked.connect(self.accept)
        card_layout.addWidget(btn)

        self.setFixedWidth(340)
