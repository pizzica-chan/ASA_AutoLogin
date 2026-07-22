"""Windows の DPI・モニター環境情報を安全に取得する。"""

from __future__ import annotations

import ctypes
import platform
import sys
from ctypes import wintypes
from typing import Any


def enable_per_monitor_dpi_awareness() -> bool:
    """プロセスを物理ピクセル基準にする。既に設定済みの場合も安全に扱う。"""
    try:
        awareness_context = ctypes.c_void_p(-4)  # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(awareness_context):
            return True
    except (AttributeError, OSError):
        pass
    try:
        return ctypes.windll.shcore.SetProcessDpiAwareness(2) in (0, -2147024891)
    except (AttributeError, OSError):
        pass
    try:
        return bool(ctypes.windll.user32.SetProcessDPIAware())
    except (AttributeError, OSError):
        return False


def get_system_dpi() -> int:
    """現在のシステム DPI。取得不能時は標準の 96 を返す。"""
    try:
        get_dpi = ctypes.windll.user32.GetDpiForSystem
        get_dpi.restype = ctypes.c_uint
        return int(get_dpi())
    except (AttributeError, OSError):
        return 96


def get_dpi_for_point(x: int, y: int) -> int:
    """指定点を含むモニターの DPI。古い Windows では system DPI を返す。"""
    try:
        point = wintypes.POINT(x, y)
        monitor = ctypes.windll.user32.MonitorFromPoint(point, 2)
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        if ctypes.windll.shcore.GetDpiForMonitor(
            monitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)
        ) == 0:
            return int(dpi_x.value)
    except (AttributeError, OSError):
        pass
    return get_system_dpi()


def environment_snapshot() -> dict[str, Any]:
    from .display import list_monitors
    from .version import APP_VERSION

    return {
        "app_version": APP_VERSION,
        "platform": platform.platform(),
        "windows_version": platform.win32_ver()[1],
        "python": sys.version.split()[0],
        "frozen": bool(getattr(sys, "frozen", False)),
        "system_dpi": get_system_dpi(),
        "display_scale_percent": round(get_system_dpi() / 96 * 100),
        "monitors": [
            {
                "index": mon.index,
                "left": mon.left,
                "top": mon.top,
                "width": mon.width,
                "height": mon.height,
            }
            for mon in list_monitors()
        ],
    }
