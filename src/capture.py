"""キャプチャ領域（モニター / ゲームウィンドウ）の解決"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import win32gui

from .display import get_monitor
from .input_handler import select_window

CaptureMode = Literal["monitor", "window"]
DEFAULT_CAPTURE_MODE: CaptureMode = "window"


@dataclass(frozen=True)
class CaptureSettings:
    mode: CaptureMode = DEFAULT_CAPTURE_MODE
    monitor_index: int = 1
    window_title: str = "ARK: Survival Ascended"


@dataclass(frozen=True)
class CaptureRegion:
    left: int
    top: int
    width: int
    height: int
    mode: CaptureMode

    def to_absolute(self, rel_x: int, rel_y: int) -> tuple[int, int]:
        return self.left + rel_x, self.top + rel_y


class WindowNotFoundError(RuntimeError):
    """capture_mode=window なのに ARK ウィンドウが見つからない"""


def get_window_client_region(title_contains: str) -> CaptureRegion | None:
    selection = select_window(title_contains)
    if selection is None:
        return None
    hwnd = selection.hwnd

    try:
        client_left, client_top, client_right, client_bottom = win32gui.GetClientRect(hwnd)
        screen_left, screen_top = win32gui.ClientToScreen(hwnd, (client_left, client_top))
        screen_right, screen_bottom = win32gui.ClientToScreen(hwnd, (client_right, client_bottom))
        width = screen_right - screen_left
        height = screen_bottom - screen_top
        if width <= 0 or height <= 0:
            return None
        return CaptureRegion(screen_left, screen_top, width, height, "window")
    except Exception:
        return None


def resolve_capture_region(
    settings: CaptureSettings,
    *,
    strict_window: bool = False,
) -> CaptureRegion:
    if settings.mode == "window":
        region = get_window_client_region(settings.window_title)
        if region is not None:
            return region
        if strict_window:
            raise WindowNotFoundError(
                f"ARK ウィンドウが見つかりません（タイトルに「{settings.window_title}」を含むウィンドウ）。"
                "前面に表示してから再試行してください。"
            )

    monitor = get_monitor(settings.monitor_index)
    return CaptureRegion(
        monitor.left,
        monitor.top,
        monitor.width,
        monitor.height,
        "monitor",
    )
