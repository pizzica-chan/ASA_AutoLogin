"""マウス・キーボード入力とウィンドウ操作"""

from __future__ import annotations

import logging
import random
import time

import pydirectinput
import win32con
import win32gui

logger = logging.getLogger(__name__)

pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = True

_vx360_gamepad = None


def human_delay(min_sec: float = 0.1, max_sec: float = 0.3) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def click(x: int, y: int, button: str = "left") -> None:
    offset_x = random.randint(-2, 2)
    offset_y = random.randint(-2, 2)
    pydirectinput.moveTo(x + offset_x, y + offset_y)
    human_delay(0.05, 0.15)
    pydirectinput.click(x + offset_x, y + offset_y, button=button)
    logger.debug("クリック: (%d, %d)", x + offset_x, y + offset_y)


def press_key(key: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.press(key)
    logger.debug("キー押下: %s", key)


def press_gamepad_x() -> bool:
    """ゲームパッドの X ボタン（Xbox レイアウト）を送信。ViGEmBus + vgamepad が必要"""
    global _vx360_gamepad
    try:
        import vgamepad as vg
    except ImportError:
        logger.warning("vgamepad が未インストールです（pip install vgamepad）")
        return False

    try:
        if _vx360_gamepad is None:
            _vx360_gamepad = vg.VX360Gamepad()
        pad = _vx360_gamepad
        pad.press_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
        pad.update()
        human_delay(0.08, 0.15)
        pad.release_button(button=vg.XUSB_BUTTON.XUSB_GAMEPAD_X)
        pad.update()
        logger.debug("ゲームパッド X ボタンを送信しました")
        return True
    except Exception as exc:
        logger.warning("ゲームパッド X の送信に失敗しました: %s", exc)
        _vx360_gamepad = None
        return False


def hotkey(*keys: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.hotkey(*keys)
    logger.debug("ホットキー: %s", "+".join(keys))


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
        logger.warning("ウィンドウが見つかりません: %s", title_contains)
        return False

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)

    human_delay(0.3, 0.5)
    logger.info("ウィンドウを前面に表示: %s", title_contains)
    return True
