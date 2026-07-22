"""クリック位置の画面上オーバーレイ表示（デバッグ・確認用）

Win32 の単一 HWND + WS_EX_TRANSPARENT で描画し、マウス入力を絶対に奪わない。
"""

from __future__ import annotations

import ctypes
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

import win32api
import win32con
import win32gui
from PIL import Image, ImageDraw

from .app_logging import detail_log

WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01

_EFFECT_SIZE = 108
_EFFECT_STEPS = 13
_EFFECT_INTERVAL = 0.04

_PRIMARY_COLOR = "#4A9EFF"
_RECOVERY_COLOR = "#FF9F0A"

GWL_EXSTYLE = win32con.GWL_EXSTYLE

_CLICK_PASSTHROUGH_STYLE = (
    WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
)
_REQUIRED_PASSTHROUGH_FLAGS = WS_EX_LAYERED | WS_EX_TRANSPARENT

_display_handler: Callable[..., None] | None = None
_effect_slots = threading.BoundedSemaphore(2)


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", ctypes.c_long),
        ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


_user32 = ctypes.windll.user32
_gdi32 = ctypes.windll.gdi32


def set_display_handler(handler: Callable[..., None] | None) -> None:
    """GUI メインスレッドなど、描画先を登録する"""
    global _display_handler
    _display_handler = handler


def spawn_click_effect(
    _root: object | None,
    x: int,
    y: int,
    kind: str = "primary",
) -> None:
    """クリック位置にリングを表示（別スレッド・入力非干渉）"""
    threading.Thread(
        target=_run_win32_effect,
        args=(x, y) if kind == "primary" else (x, y, kind),
        daemon=True,
        name="ClickEffect",
    ).start()


def spawn_click_effect_burst(
    _root: object | None,
    x: int,
    y: int,
    *,
    count: int = 3,
    interval_ms: int = 600,
) -> None:
    """同じ位置にリングを連続表示（プレビュー用）"""

    def run_burst() -> None:
        for index in range(count):
            spawn_click_effect(None, x, y)
            if index < count - 1:
                time.sleep(interval_ms / 1000.0)

    threading.Thread(target=run_burst, daemon=True, name="ClickEffectBurst").start()


def _hex_rgba(hex_color: str, alpha: int) -> tuple[int, int, int, int]:
    value = hex_color.lstrip("#")
    red = int(value[0:2], 16)
    green = int(value[2:4], 16)
    blue = int(value[4:6], 16)
    return (red, green, blue, alpha)


def _draw_frame(
    step: int,
    size: int = _EFFECT_SIZE,
    kind: str = "primary",
) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    center = size // 2
    progress = min(1.0, step / max(1, _EFFECT_STEPS - 1))
    eased = 1.0 - (1.0 - progress) ** 3
    alpha = int(210 * (1.0 - progress) ** 1.7)
    radius = 7 + 25 * eased
    color = _RECOVERY_COLOR if kind == "recovery" else _PRIMARY_COLOR
    rgba = _hex_rgba(color, alpha)
    line_width = max(1, round(2.2 - progress))

    draw.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        outline=rgba,
        width=line_width,
    )
    dot_alpha = int(190 * (1.0 - progress))
    dot = _hex_rgba(color, dot_alpha)
    dot_radius = max(1.0, 3.0 * (1.0 - progress * 0.5))
    draw.ellipse(
        (
            center - dot_radius,
            center - dot_radius,
            center + dot_radius,
            center + dot_radius,
        ),
        fill=dot,
    )
    if kind == "recovery":
        arm = 7
        draw.line(
            [(center - arm, center), (center - 3, center)],
            fill=rgba,
            width=1,
        )
        draw.line(
            [(center + 3, center), (center + arm, center)],
            fill=rgba,
            width=1,
        )
    return image


def _update_layered_window(hwnd: int, left: int, top: int, image: Image.Image) -> None:
    width, height = image.size
    pixels = image.convert("RGBA").tobytes("raw", "BGRA")

    hdc_screen = win32gui.GetDC(0)
    if not hdc_screen:
        raise OSError("画面 DC の取得に失敗しました")

    hdc_mem = _gdi32.CreateCompatibleDC(hdc_screen)
    if not hdc_mem:
        win32gui.ReleaseDC(0, hdc_screen)
        raise OSError("メモリ DC の作成に失敗しました")

    try:
        header = _BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0

        bits = ctypes.c_void_p()
        bitmap = _gdi32.CreateDIBSection(
            hdc_mem,
            ctypes.byref(header),
            0,
            ctypes.byref(bits),
            None,
            0,
        )
        if not bitmap or not bits.value:
            raise OSError("レイヤードビットマップの作成に失敗しました")

        ctypes.memmove(bits.value, pixels, len(pixels))

        previous = _gdi32.SelectObject(hdc_mem, bitmap)
        destination = _POINT(left, top)
        source = _POINT(0, 0)
        size = _SIZE(width, height)
        blend = _BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        if not _user32.UpdateLayeredWindow(
            hwnd,
            hdc_screen,
            ctypes.byref(destination),
            ctypes.byref(size),
            hdc_mem,
            ctypes.byref(source),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        ):
            raise OSError("UpdateLayeredWindow に失敗しました")

        _gdi32.SelectObject(hdc_mem, previous)
        _gdi32.DeleteObject(bitmap)
    finally:
        _gdi32.DeleteDC(hdc_mem)
        win32gui.ReleaseDC(0, hdc_screen)


def _ensure_pass_through(hwnd: int) -> None:
    """UpdateLayeredWindow 後も WS_EX_TRANSPARENT が維持されるよう再適用する"""
    style = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
    merged = style | _REQUIRED_PASSTHROUGH_FLAGS | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
    if merged != style:
        win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, merged)


def _create_pass_through_window(left: int, top: int, size: int) -> int:
    hwnd = win32gui.CreateWindowEx(
        _CLICK_PASSTHROUGH_STYLE,
        "Static",
        "",
        WS_POPUP | WS_VISIBLE,
        left,
        top,
        size,
        size,
        0,
        0,
        win32api.GetModuleHandle(None),
        None,
    )
    if not hwnd:
        raise OSError("クリック表示ウィンドウの作成に失敗しました")

    _ensure_pass_through(hwnd)
    win32gui.SetWindowPos(
        hwnd,
        win32con.HWND_TOPMOST,
        left,
        top,
        size,
        size,
        win32con.SWP_NOACTIVATE,
    )
    return hwnd


def _run_win32_effect(x: int, y: int, kind: str = "primary") -> None:
    from .windows_environment import get_dpi_for_point

    if not _effect_slots.acquire(blocking=False):
        detail_log.debug("クリック表示を省略しました（同時表示上限）")
        return
    dpi_scale = max(0.75, min(2.0, get_dpi_for_point(x, y) / 96.0))
    effect_size = max(72, round(_EFFECT_SIZE * dpi_scale))
    half = effect_size // 2
    left = x - half
    top = y - half
    try:
        hwnd = _create_pass_through_window(left, top, effect_size)
    except OSError as exc:
        detail_log.warning("クリック表示をスキップしました (%d, %d): %s", x, y, exc)
        _effect_slots.release()
        return

    try:
        for step in range(_EFFECT_STEPS):
            if not win32gui.IsWindow(hwnd):
                break
            frame = _draw_frame(step, effect_size, kind)
            try:
                _update_layered_window(hwnd, left, top, frame)
                _ensure_pass_through(hwnd)
            except OSError as exc:
                detail_log.warning(
                    "クリック表示フレームの描画に失敗しました (%d, %d): %s",
                    x,
                    y,
                    exc,
                )
                break
            time.sleep(_EFFECT_INTERVAL)
    finally:
        if win32gui.IsWindow(hwnd):
            win32gui.DestroyWindow(hwnd)
        _effect_slots.release()


class ClickIndicator:
    """自動クリック位置を画面上にリング表示する（マウス入力は透過）"""

    _instance: ClickIndicator | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._enabled = False

    @classmethod
    def instance(cls) -> ClickIndicator:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def configure(self, enabled: bool) -> None:
        self._enabled = enabled

    def show(self, x: int, y: int, kind: str = "primary") -> None:
        if not self._enabled:
            return
        detail_log.debug("クリック表示: (%d, %d) kind=%s", x, y, kind)
        if _display_handler is not None:
            if kind == "primary":
                _display_handler(x, y)
            else:
                try:
                    _display_handler(x, y, kind)
                except TypeError:
                    _display_handler(x, y)
            return
        if kind == "primary":
            spawn_click_effect(None, x, y)
        else:
            spawn_click_effect(None, x, y, kind)


def configure_click_indicator(enabled: bool) -> None:
    ClickIndicator.instance().configure(enabled)


def show_click_indicator(x: int, y: int, kind: str = "primary") -> None:
    ClickIndicator.instance().show(x, y, kind)
