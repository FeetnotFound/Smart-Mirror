"""Music widget — AirPlay Now Playing via shairport-sync. 440×440.

Swaps into the system info slot when AirPlay is active.
Shows large cover art, title, artist, album.
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, TRANS

_ART_SIZE = 200


class MusicWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 440))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        hdr = QLabel("AIRPLAY")
        hdr.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        hdr.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        layout.addWidget(hdr)

        layout.addSpacing(12)

        # Album art — centered
        self._art = QLabel()
        self._art.setFixedSize(_ART_SIZE, _ART_SIZE)
        self._art.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._art.setStyleSheet(
            "background: #111111; border-radius: 8px; border: 1px solid #222222;")
        layout.addWidget(self._art, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addSpacing(16)

        self._title = QLabel()
        self._title.setFont(QFont("Arial", 22, QFont.Weight.Normal))
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setWordWrap(True)
        self._title.setStyleSheet("color: #eeeeee; " + TRANS)
        layout.addWidget(self._title)

        layout.addSpacing(4)

        self._artist = QLabel()
        self._artist.setFont(QFont("Arial", 15, QFont.Weight.Light))
        self._artist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._artist.setWordWrap(True)
        self._artist.setStyleSheet("color: #888888; " + TRANS)
        layout.addWidget(self._artist)

        layout.addSpacing(2)

        self._album = QLabel()
        self._album.setFont(QFont("Arial", 12, QFont.Weight.Light))
        self._album.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._album.setWordWrap(True)
        self._album.setStyleSheet("color: #555555; " + TRANS)
        layout.addWidget(self._album)

        self._idle()

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(2_000)

    def _idle(self) -> None:
        self._art.clear()
        self._art.setStyleSheet(
            "background: #0f0f0f; border-radius: 8px; border: 1px solid #1a1a1a;")
        self._title.setText("not playing")
        self._title.setStyleSheet("color: #222222; " + TRANS)
        self._artist.setText("")
        self._album.setText("")

    def _refresh(self) -> None:
        from ui_backend.music_backend import poll
        info = poll()

        if not info.playing:
            self._idle()
            return

        # Cover art
        if info.art_url.startswith("file://"):
            px = QPixmap(info.art_url[7:])
            if not px.isNull():
                self._art.setPixmap(
                    px.scaled(_ART_SIZE, _ART_SIZE,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation))
                self._art.setStyleSheet(
                    "border-radius: 8px; border: 1px solid #333333;")
            else:
                self._art.clear()
        else:
            self._art.clear()

        self._title.setText(info.title or "Unknown track")
        self._title.setStyleSheet("color: #eeeeee; " + TRANS)
        self._artist.setText(info.artist)
        self._album.setText(info.album)

    @property
    def is_playing(self) -> bool:
        from ui_backend.music_backend import poll
        return poll().playing
