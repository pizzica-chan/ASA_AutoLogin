"""capture モジュールの基本テスト"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.capture import CaptureRegion, CaptureSettings, WindowNotFoundError, resolve_capture_region


class CaptureModuleTests(unittest.TestCase):
    def test_capture_region_to_absolute(self) -> None:
        region = CaptureRegion(100, 200, 800, 600, "window")
        self.assertEqual(region.to_absolute(400, 300), (500, 500))

    @patch("src.capture.get_window_client_region", return_value=None)
    @patch("src.capture.get_monitor")
    def test_resolve_falls_back_to_monitor(self, mock_get_monitor, _mock_window) -> None:
        from src.display import MonitorInfo

        mock_get_monitor.return_value = MonitorInfo(1, 0, 0, 1920, 1080)
        region = resolve_capture_region(
            CaptureSettings(mode="window", monitor_index=1),
            strict_window=False,
        )
        self.assertEqual(region.mode, "monitor")
        self.assertEqual((region.left, region.top, region.width, region.height), (0, 0, 1920, 1080))

    @patch("src.capture.get_window_client_region", return_value=None)
    def test_strict_window_raises_when_missing(self, _mock_window) -> None:
        with self.assertRaises(WindowNotFoundError):
            resolve_capture_region(
                CaptureSettings(mode="window"),
                strict_window=True,
            )

    @patch("src.capture.get_window_client_region")
    def test_window_mode_uses_client_region(self, mock_window) -> None:
        mock_window.return_value = CaptureRegion(50, 60, 1280, 720, "window")
        region = resolve_capture_region(CaptureSettings(mode="window"), strict_window=True)
        self.assertEqual(region.mode, "window")
        self.assertEqual(region.width, 1280)


if __name__ == "__main__":
    unittest.main()
