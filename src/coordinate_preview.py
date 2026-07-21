"""クリック座標の画面上プレビュー・ピック"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from .capture import CaptureSettings, CaptureRegion, WindowNotFoundError, resolve_capture_region
from .input_handler import bring_window_to_front

PREVIEW_COLORS = (
    "#ff453a",
    "#ff9f0a",
    "#ffd60a",
    "#34c759",
    "#4a9eff",
    "#bf5af2",
)


def _strict_window(capture_settings: CaptureSettings) -> bool:
    return capture_settings.mode == "window"


def _resolve_overlay_region(
    capture_settings: CaptureSettings,
    *,
    strict_window: bool,
    bring_to_front: bool = False,
) -> CaptureRegion:
    if bring_to_front and capture_settings.mode == "window":
        bring_window_to_front(capture_settings.window_title)
    try:
        return resolve_capture_region(capture_settings, strict_window=strict_window)
    except WindowNotFoundError as exc:
        raise WindowNotFoundError(str(exc)) from exc


class CoordinatePreviewOverlay(tk.Toplevel):
    """キャプチャ領域上にクリック座標を点で表示する"""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        capture_settings: CaptureSettings,
        points: list[tuple[str, float, float]],
        bring_to_front: bool = False,
    ):
        super().__init__(parent)
        self.title("座標プレビュー")
        region = _resolve_overlay_region(
            capture_settings,
            strict_window=_strict_window(capture_settings),
            bring_to_front=bring_to_front,
        )

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#101010")
        self.attributes("-alpha", 0.55)

        geometry = f"{region.width}x{region.height}+{region.left}+{region.top}"
        self.geometry(geometry)

        canvas = tk.Canvas(
            self,
            width=region.width,
            height=region.height,
            bg="#101010",
            highlightthickness=0,
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        mode_label = "ゲームウィンドウ" if region.mode == "window" else "モニター全体"
        hint = (
            f"クリック座標プレビュー（{mode_label}）— 色の点が設定位置です。"
            " [Esc] または [クリック] で閉じます"
        )
        canvas.create_text(
            region.width // 2,
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
            x = int(region.width * x_percent / 100)
            y = int(region.height * y_percent / 100)
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


class CoordinatePickOverlay(tk.Toplevel):
    """キャプチャ領域上でクリック位置を％座標として取得する"""

    def __init__(
        self,
        parent: tk.Misc,
        *,
        capture_settings: CaptureSettings,
        label: str,
        on_pick: Callable[[float, float], None],
        on_cancel: Callable[[], None] | None = None,
        bring_to_front: bool = False,
    ):
        super().__init__(parent)
        self._region = _resolve_overlay_region(
            capture_settings,
            strict_window=_strict_window(capture_settings),
            bring_to_front=bring_to_front,
        )
        self._on_pick = on_pick
        self._on_cancel = on_cancel

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.configure(bg="#101010")
        self.attributes("-alpha", 0.42)

        geometry = (
            f"{self._region.width}x{self._region.height}"
            f"+{self._region.left}+{self._region.top}"
        )
        self.geometry(geometry)

        canvas = tk.Canvas(
            self,
            width=self._region.width,
            height=self._region.height,
            bg="#101010",
            highlightthickness=0,
            cursor="crosshair",
        )
        canvas.pack(fill=tk.BOTH, expand=True)

        hint = (
            f"{label} — クリックしたい位置を押してください"
            "　　[Esc] キャンセル"
        )
        canvas.create_text(
            self._region.width // 2,
            28,
            text=hint,
            fill="#ffffff",
            font=("Segoe UI", 12, "bold"),
        )

        self._cross_v = canvas.create_line(0, 0, 0, 0, fill="#4a9eff", width=1)
        self._cross_h = canvas.create_line(0, 0, 0, 0, fill="#4a9eff", width=1)

        canvas.bind("<Motion>", self._on_motion)
        canvas.bind("<Button-1>", self._on_click)
        self.bind("<Escape>", self._on_escape)
        self.protocol("WM_DELETE_WINDOW", self._on_escape)
        self.after(100, self.focus_set)
        self.grab_set()

    def _on_motion(self, event: tk.Event) -> None:
        widget = event.widget
        widget.coords(self._cross_v, event.x, 0, event.x, self._region.height)
        widget.coords(self._cross_h, 0, event.y, self._region.width, event.y)

    def _on_click(self, event: tk.Event) -> None:
        x_percent, y_percent = percent_from_capture_click(
            event.x,
            event.y,
            width=self._region.width,
            height=self._region.height,
        )
        self._on_pick(x_percent, y_percent)
        self.destroy()

    def _on_escape(self, _event: tk.Event | None = None) -> None:
        if self._on_cancel:
            self._on_cancel()
        self.destroy()


def percent_from_capture_click(
    x: int,
    y: int,
    *,
    width: int,
    height: int,
) -> tuple[float, float]:
    """キャプチャ領域上のピクセル座標を % 座標に変換"""
    if width <= 0 or height <= 0:
        return 0.0, 0.0
    return round(x / width * 100, 2), round(y / height * 100, 2)


def pick_coordinate_on_screen(
    parent: tk.Misc,
    *,
    capture_settings: CaptureSettings,
    label: str,
    on_pick: Callable[[float, float], None],
    on_cancel: Callable[[], None] | None = None,
    bring_to_front: bool = False,
) -> None:
    """キャプチャ領域上のクリックで％座標を取得するオーバーレイを表示"""
    CoordinatePickOverlay(
        parent,
        capture_settings=capture_settings,
        label=label,
        on_pick=on_pick,
        on_cancel=on_cancel,
        bring_to_front=bring_to_front,
    )


def show_coordinate_preview(
    parent: tk.Misc,
    *,
    capture_settings: CaptureSettings,
    points: list[tuple[str, float, float]],
    bring_to_front: bool = False,
) -> None:
    """座標プレビューオーバーレイを表示"""
    if not points:
        return
    CoordinatePreviewOverlay(
        parent,
        capture_settings=capture_settings,
        points=points,
        bring_to_front=bring_to_front,
    )
