"""Win32 クリックエフェクトの実機スモークテスト（手動確認用）"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import win32gui

from src.click_indicator import (
    GWL_EXSTYLE,
    WS_EX_TRANSPARENT,
    _EFFECT_SIZE,
    _create_pass_through_window,
    _draw_frame,
    _update_layered_window,
)


def main() -> int:
    left, top = 280, 180
    hwnd = _create_pass_through_window(left, top, _EFFECT_SIZE)
    try:
        style = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
        if not (style & WS_EX_TRANSPARENT):
            print(f"FAIL: WS_EX_TRANSPARENT が未設定 (style={style:#x})")
            return 1

        _update_layered_window(hwnd, left, top, _draw_frame(0))
        style_after = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
        if not (style_after & WS_EX_TRANSPARENT):
            print(f"FAIL: 描画後に WS_EX_TRANSPARENT が失われました (style={style_after:#x})")
            return 1
    finally:
        if win32gui.IsWindow(hwnd):
            win32gui.DestroyWindow(hwnd)

    print("OK: Win32 クリックエフェクトのスモークテスト成功")
    return 0


if __name__ == "__main__":
    sys.exit(main())
