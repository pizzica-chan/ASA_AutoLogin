"""マウス・キーボード入力とウィンドウ操作"""

from __future__ import annotations

import random
import time

import pydirectinput
import win32con
import win32gui

from .app_logging import detail_log, user_log

pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = True


def human_delay(min_sec: float = 0.1, max_sec: float = 0.3) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def click(x: int, y: int, button: str = "left") -> None:
    offset_x = random.randint(-2, 2)
    offset_y = random.randint(-2, 2)
    pydirectinput.moveTo(x + offset_x, y + offset_y)
    human_delay(0.05, 0.15)
    pydirectinput.click(x + offset_x, y + offset_y, button=button)
    detail_log.debug("クリック: (%d, %d)", x + offset_x, y + offset_y)


def press_key(key: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.press(key)
    detail_log.debug("キー押下: %s", key)


def hotkey(*keys: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.hotkey(*keys)
    detail_log.debug("ホットキー: %s", "+".join(keys))


def find_window(title_contains: str) -> int | None:
    result: list[int] = []

    def callback(hwnd: int, _: object) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_contains.lower() in title.lower():
                result.append(hwnd)
        return True

    win32gui.EnumWindows(callback, None)
    return result[0] if result else None


def bring_window_to_front(title_contains: str) -> bool:
    hwnd = find_window(title_contains)
    if hwnd is None:
        detail_log.warning("ウィンドウが見つかりません: %s", title_contains)
        return False

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)

    human_delay(0.3, 0.5)
    detail_log.info("ウィンドウを前面に表示: %s", title_contains)
    return True
