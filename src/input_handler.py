"""マウス・キーボード入力とウィンドウ操作"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

import pydirectinput
import win32con
import win32gui
import win32process

from .app_logging import detail_log, user_log
from .click_indicator import show_click_indicator

pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = True


@dataclass(frozen=True)
class WindowSelection:
    hwnd: int
    title: str
    process_id: int
    client_area: int
    minimized: bool
    candidate_count: int


def human_delay(min_sec: float = 0.1, max_sec: float = 0.3) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


def click(
    x: int,
    y: int,
    button: str = "left",
    *,
    kind: str = "primary",
) -> None:
    offset_x = 0 if kind == "recovery" else random.randint(-2, 2)
    offset_y = 0 if kind == "recovery" else random.randint(-2, 2)
    target_x = x + offset_x
    target_y = y + offset_y
    pydirectinput.moveTo(target_x, target_y)
    human_delay(0.05, 0.15)
    pydirectinput.click(target_x, target_y, button=button)
    detail_log.debug("クリック: (%d, %d)", target_x, target_y)
    if kind == "primary":
        show_click_indicator(target_x, target_y)
    else:
        show_click_indicator(target_x, target_y, kind)


def configure_click_indicator(enabled: bool) -> None:
    from .click_indicator import configure_click_indicator as _configure

    _configure(enabled)


def press_key(key: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.press(key)
    detail_log.debug("キー押下: %s", key)


def hotkey(*keys: str) -> None:
    human_delay(0.05, 0.1)
    pydirectinput.hotkey(*keys)
    detail_log.debug("ホットキー: %s", "+".join(keys))


def find_window(title_contains: str) -> int | None:
    selection = select_window(title_contains)
    return selection.hwnd if selection else None


def find_window_candidates(title_contains: str) -> list[int]:
    """タイトル一致候補を、操作対象として妥当な順に返す。"""
    result: list[tuple[int, int, bool]] = []

    def callback(hwnd: int, _: object) -> bool:
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_contains.lower() in title.lower():
                try:
                    left, top, right, bottom = win32gui.GetClientRect(hwnd)
                    area = max(0, right - left) * max(0, bottom - top)
                except Exception:
                    area = 0
                result.append((hwnd, area, not bool(win32gui.IsIconic(hwnd))))
        return True

    win32gui.EnumWindows(callback, None)
    result.sort(key=lambda item: (item[2], item[1]), reverse=True)
    if len(result) > 1:
        detail_log.warning(
            "同名ウィンドウが %d 件あります。最大の表示中ウィンドウを選択します: %s",
            len(result),
            [item[0] for item in result],
        )
    return [item[0] for item in result]


def select_window(title_contains: str) -> WindowSelection | None:
    candidates = find_window_candidates(title_contains)
    if not candidates:
        return None
    hwnd = candidates[0]
    try:
        _thread_id, process_id = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        process_id = 0
    try:
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        area = max(0, right - left) * max(0, bottom - top)
    except Exception:
        area = 0
    selection = WindowSelection(
        hwnd=hwnd,
        title=win32gui.GetWindowText(hwnd),
        process_id=process_id,
        client_area=area,
        minimized=bool(win32gui.IsIconic(hwnd)),
        candidate_count=len(candidates),
    )
    detail_log.debug(
        "ARKウィンドウ選択: hwnd=%s pid=%s area=%s minimized=%s candidates=%s title=%r",
        selection.hwnd,
        selection.process_id,
        selection.client_area,
        selection.minimized,
        selection.candidate_count,
        selection.title,
    )
    return selection


def bring_window_to_front(title_contains: str) -> bool:
    selection = select_window(title_contains)
    if selection is None:
        detail_log.warning("ウィンドウが見つかりません: %s", title_contains)
        return False
    hwnd = selection.hwnd

    try:
        if win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd):
            return True
    except Exception:
        pass

    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)

    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)

    human_delay(0.3, 0.5)
    try:
        foreground = win32gui.GetForegroundWindow()
    except Exception:
        foreground = None
    if foreground != hwnd:
        detail_log.warning(
            "ウィンドウを前面にできませんでした: target=%s foreground=%s",
            hwnd,
            foreground,
        )
        return False
    detail_log.info("ウィンドウを前面に表示: %s (hwnd=%s)", title_contains, hwnd)
    return True


def hwnd_from_tk(window) -> int:
    """tkinter ウィンドウのトップレベル HWND を取得（Windows 専用）"""
    hwnd = int(window.winfo_id())
    try:
        root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
        if root:
            return int(root)
    except Exception:
        pass
    return hwnd


def send_window_to_back(hwnd: int) -> None:
    """ウィンドウを Z 順序の背面へ送る（位置・サイズは変えない）"""
    try:
        win32gui.SetWindowPos(
            hwnd,
            win32con.HWND_BOTTOM,
            0,
            0,
            0,
            0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
        )
        detail_log.debug("ウィンドウを背面へ: hwnd=%s", hwnd)
    except Exception as exc:
        detail_log.warning("ウィンドウを背面へ送れませんでした: hwnd=%s (%s)", hwnd, exc)


def _raise_game_window(hwnd: int) -> None:
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        win32gui.BringWindowToTop(hwnd)


def _raise_dialog_above_game(dialog_hwnd: int) -> None:
    win32gui.SetWindowPos(
        dialog_hwnd,
        win32con.HWND_TOPMOST,
        0,
        0,
        0,
        0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
    )
    try:
        win32gui.SetForegroundWindow(dialog_hwnd)
    except Exception:
        win32gui.BringWindowToTop(dialog_hwnd)


def stack_windows_for_start_capture(
    *,
    game_title_contains: str,
    tool_hwnd: int,
    dialog_hwnd: int | None = None,
) -> bool:
    """開始前確認用: ツール本体 < ARK < 確認ダイアログ の順に並べる"""
    selection = select_window(game_title_contains)
    if selection is None:
        detail_log.warning("開始前ウィンドウ整列: ゲームが見つかりません (%s)", game_title_contains)
        return False

    send_window_to_back(tool_hwnd)
    _raise_game_window(selection.hwnd)
    if dialog_hwnd:
        _raise_dialog_above_game(dialog_hwnd)
    elif win32gui.GetForegroundWindow() == tool_hwnd:
        # 本体が前面に残った場合の保険
        _raise_game_window(selection.hwnd)

    detail_log.info(
        "開始前ウィンドウ整列: tool=%s game=%s dialog=%s",
        tool_hwnd,
        selection.hwnd,
        dialog_hwnd,
    )
    return True


def prepare_game_visible_for_capture(
    *,
    game_title_contains: str,
    tool_hwnd: int | None = None,
    bring_game_to_front: bool = True,
    dialog_hwnd: int | None = None,
) -> bool:
    """画面キャプチャ直前にツールを背面へ。必要ならゲームを前面へ"""
    if tool_hwnd:
        send_window_to_back(tool_hwnd)

    selection = select_window(game_title_contains)
    if selection is None:
        detail_log.warning("キャプチャ準備: ゲームが見つかりません (%s)", game_title_contains)
        return False

    if bring_game_to_front:
        if dialog_hwnd:
            # 診断ダイアログ表示中は長い待機付き前面化を避け、Z 順のみ整える
            _raise_game_window(selection.hwnd)
        else:
            if not bring_window_to_front(game_title_contains):
                if dialog_hwnd:
                    _raise_dialog_above_game(dialog_hwnd)
                return False
    else:
        _raise_game_window(selection.hwnd)

    if dialog_hwnd:
        _raise_dialog_above_game(dialog_hwnd)
    return True
