"""GUI ヘルパー（表示幅計算など）のテスト"""

from __future__ import annotations

import unittest

from src.app_service import CLICK_MODE_OPTIONS
from src.gui_app import LoginApp


class GuiHelperTests(unittest.TestCase):
    def test_text_display_width_counts_fullwidth_chars(self) -> None:
        self.assertEqual(LoginApp._text_display_width("abc"), 3)
        self.assertEqual(LoginApp._text_display_width("あ"), 2)
        self.assertEqual(LoginApp._text_display_width("あA"), 3)

    def test_option_menu_width_covers_longest_click_mode_label(self) -> None:
        labels = [label for _value, label in CLICK_MODE_OPTIONS]
        longest = max(labels, key=LoginApp._text_display_width)
        width = LoginApp._option_menu_width(*labels)
        self.assertGreaterEqual(width, LoginApp._text_display_width(longest))


if __name__ == "__main__":
    unittest.main()
