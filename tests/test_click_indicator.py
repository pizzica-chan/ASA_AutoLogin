"""クリック位置インジケータのユニットテスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

from src.click_indicator import (
    GWL_EXSTYLE,
    WS_EX_LAYERED,
    WS_EX_TRANSPARENT,
    ClickIndicator,
    _CLICK_PASSTHROUGH_STYLE,
    _REQUIRED_PASSTHROUGH_FLAGS,
    _draw_frame,
    _ensure_pass_through,
    set_display_handler,
    show_click_indicator,
    spawn_click_effect,
)


class ClickIndicatorTests(unittest.TestCase):
    def tearDown(self) -> None:
        set_display_handler(None)
        ClickIndicator.instance().configure(False)

    def test_show_ignored_when_disabled(self) -> None:
        indicator = ClickIndicator()
        indicator._enabled = False
        with patch("src.click_indicator.spawn_click_effect") as mock_spawn:
            indicator.show(100, 200)
            mock_spawn.assert_not_called()

    @patch("src.click_indicator.spawn_click_effect")
    def test_show_spawns_effect_when_enabled_without_handler(self, mock_spawn: MagicMock) -> None:
        set_display_handler(None)
        indicator = ClickIndicator()
        indicator._enabled = True
        indicator.show(100, 200)
        mock_spawn.assert_called_once_with(None, 100, 200)

    def test_show_uses_display_handler_when_set(self) -> None:
        handler = MagicMock()
        set_display_handler(handler)
        indicator = ClickIndicator()
        indicator._enabled = True
        indicator.show(300, 400)
        handler.assert_called_once_with(300, 400)

    def test_show_click_indicator_logs_coordinates_when_enabled(self) -> None:
        indicator = ClickIndicator.instance()
        indicator.configure(True)
        set_display_handler(lambda _x, _y: None)
        with self.assertLogs("asa_login.detail", level="DEBUG") as logs:
            show_click_indicator(111, 222)
        self.assertTrue(any("111" in msg and "222" in msg for msg in logs.output))

    def test_pass_through_style_includes_transparent_flag(self) -> None:
        self.assertTrue(_CLICK_PASSTHROUGH_STYLE & WS_EX_TRANSPARENT)
        self.assertTrue(_CLICK_PASSTHROUGH_STYLE & WS_EX_LAYERED)

    def test_draw_frame_has_visible_pixels(self) -> None:
        frame = _draw_frame(0)
        alpha_channel = frame.getchannel("A")
        self.assertGreater(max(alpha_channel.get_flattened_data()), 0)

    def test_recovery_effect_uses_different_visual(self) -> None:
        primary = _draw_frame(2, kind="primary")
        recovery = _draw_frame(2, kind="recovery")
        self.assertNotEqual(primary.tobytes(), recovery.tobytes())

    @patch("src.click_indicator.win32gui.SetWindowLong")
    @patch("src.click_indicator.win32gui.GetWindowLong", return_value=0)
    def test_ensure_pass_through_applies_required_flags(
        self,
        _get_style: MagicMock,
        set_style: MagicMock,
    ) -> None:
        _ensure_pass_through(12345)
        set_style.assert_called_once()
        hwnd, style_name, new_style = set_style.call_args[0]
        self.assertEqual(hwnd, 12345)
        self.assertEqual(style_name, GWL_EXSTYLE)
        self.assertTrue(new_style & _REQUIRED_PASSTHROUGH_FLAGS)

    @patch("src.click_indicator.threading.Thread")
    def test_spawn_click_effect_starts_thread(self, mock_thread: MagicMock) -> None:
        spawn_click_effect(None, 10, 20)
        mock_thread.assert_called_once()
        _, kwargs = mock_thread.call_args
        self.assertEqual(kwargs["args"], (10, 20))

    @patch("src.click_indicator.win32gui.DestroyWindow")
    @patch("src.click_indicator.time.sleep")
    @patch("src.click_indicator._update_layered_window")
    @patch("src.click_indicator._create_pass_through_window", return_value=999)
    @patch("src.click_indicator.win32gui.IsWindow", return_value=True)
    def test_run_win32_effect_always_destroys_window(
        self,
        _is_window: MagicMock,
        _create: MagicMock,
        mock_update: MagicMock,
        _sleep: MagicMock,
        destroy: MagicMock,
    ) -> None:
        from src.click_indicator import _run_win32_effect

        mock_update.side_effect = OSError("描画失敗")
        _run_win32_effect(50, 60)
        destroy.assert_called_once_with(999)


if __name__ == "__main__":
    unittest.main()
