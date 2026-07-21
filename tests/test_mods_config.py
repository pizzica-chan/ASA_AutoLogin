"""MODS 検出設定の正規化"""

from __future__ import annotations

import unittest

from src.app_service import _normalize_mods_detect_mode, _normalize_mods_screen_region


class ModsConfigTests(unittest.TestCase):
    def test_detect_mode_defaults_invalid(self) -> None:
        self.assertEqual(_normalize_mods_detect_mode("hybrid"), "hybrid")
        self.assertEqual(_normalize_mods_detect_mode("unknown"), "hybrid")
        self.assertEqual(_normalize_mods_detect_mode(None), "hybrid")

    def test_screen_region_defaults_invalid(self) -> None:
        self.assertEqual(_normalize_mods_screen_region("center"), "center")
        self.assertEqual(_normalize_mods_screen_region("full"), "full")
        self.assertEqual(_normalize_mods_screen_region("bad"), "center")


if __name__ == "__main__":
    unittest.main()
