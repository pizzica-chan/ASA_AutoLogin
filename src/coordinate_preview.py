"""クリック座標の画面上プレビュー（点表示）"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .display import get_monitor

PREVIEW_COLORS = (
    "#ff453a",
    "#ff9f0a",
    "#ffd60a",
    "#34c759",
    "#4a9eff",
    "#bf5af2",
)


class CoordinatePreviewOverlay(tk.Toplevel):
    """選択モニター上にクリック座標を点で表示する"""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        monitor_index: int,
        points: list[tuple[str, float, float]],
    ):
        super().__init__(parent)
        self.title("座標プレビュー")
        self._monitor = get_monitor(monitor_index)

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#101010")
        self.attributes("-alpha", 0.55)

        geometry = (
            f"{self._monitor.width}x{self._monitor.height}"
            f"+{self._monitor.left}+{self._monitor.top}"
        )
        self.geometry(geometry)

        canvas = tk.Canvas(
            self,
            width=self._monitor.width,
            height=self._monitor.height,
            bg="#101010",
            highlightthickness=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        hint = (
            "クリック座標プレビュー — 色の点が設定位置です。"
            " [Esc] または [クリック] で閉じます"
        )
        canvas.create_text(
            self._monitor.width // 2,
            28,
            text=hint,
            fill="#ffffff",
            font=("Segoe UI", 12, "bold"),
        )

        radius = 10
        for index, (label, x_percent, y_percent) in enumerate(points):
            if x_percent <= 0 or y_percent <= 0:
                continue
            color = PREVIEW_COLORS[index % len(PREVIEW_COLORS)]
            x = int(self._monitor.width * x_percent / 100)
            y = int(self._monitor.height * y_percent / 100)
            canvas.create_oval(
                x - radius,
                y - radius,
                x + radius,
                y + radius,
                fill=color,
                outline="#ffffff",
                width=2,
            )
            canvas.create_line(x - 16, y, x + 16, y, fill=color, width=2)
            canvas.create_line(x, y - 16, x, y + 16, fill=color, width=2)
            canvas.create_text(
                x + 14,
                y - 14,
                text=label,
                anchor=tk.SW,
                fill=color,
                font=("Segoe UI", 10, "bold"),
            )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Button-1>", lambda _e: self.destroy())
        self.focus_set()
        self.grab_set()


def show_coordinate_preview(
    parent: tk.Misc,
    *,
    monitor_index: int,
    points: list[tuple[str, float, float]],
) -> None:
    """座標プレビューオーバーレイを表示"""
    if not points:
        return
    CoordinatePreviewOverlay(parent, monitor_index=monitor_index, points=points)
