"""System info widget — CPU, RAM, GPU, disk, temp, uptime. 440×440."""
from datetime import timedelta
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QVBoxLayout, QLabel

from ui.base_widget import BaseWidget, FitLabel, TRANS
from ui_backend.system_info_backend import snapshot


class SystemInfoWidget(BaseWidget):
    def __init__(self) -> None:
        super().__init__(fixed_size=(440, 440))

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(6)

        title = QLabel("SYSTEM")
        title.setFont(QFont("Arial", 11, QFont.Weight.Medium))
        title.setStyleSheet("color: #444444; letter-spacing: 3px; " + TRANS)
        layout.addWidget(title)

        self._cpu  = FitLabel(max_pt=24)
        self._mem  = FitLabel(max_pt=24)
        self._disk = FitLabel(max_pt=24)
        self._gpu  = FitLabel(max_pt=24)
        self._temp = FitLabel(max_pt=24)
        self._up   = FitLabel(max_pt=24)

        for lbl in (self._cpu, self._mem, self._disk,
                    self._gpu, self._temp, self._up):
            lbl.setStyleSheet("color: #bbbbbb; " + TRANS)
            layout.addWidget(lbl)

        poll = QTimer(self)
        poll.timeout.connect(self._refresh)
        poll.start(3_000)
        self._refresh()

    def _refresh(self) -> None:
        s = snapshot()
        if not s.get("available"):
            self._cpu.setText("psutil not installed")
            return

        up = str(timedelta(seconds=s["uptime_seconds"])).split(".")[0]
        self._cpu.setText(f"CPU   {s['cpu_percent']:.0f}%")
        self._mem.setText(f"MEM   {s['mem_used_gb']:.1f} / {s['mem_total_gb']:.1f} GB")
        self._disk.setText(f"DISK  {s['disk_used_gb']:.1f} / {s['disk_total_gb']:.1f} GB")

        if "gpu_percent" in s:
            self._gpu.setText(
                f"GPU   {s['gpu_percent']}%  "
                f"{s['gpu_mem_used_mb']} / {s['gpu_mem_total_mb']} MB")
            self._gpu.show()
        else:
            self._gpu.hide()

        if "temp_c" in s:
            self._temp.setText(f"TEMP  {s['temp_c']:.0f}°C")
            self._temp.show()
        else:
            self._temp.hide()

        self._up.setText(f"UP TIME   {up}")
