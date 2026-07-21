"""座標系（パーセント ↔ ピクセル ↔ 絶対座標）の整合性テスト"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src.capture import CaptureRegion, CaptureSettings
from src.coordinate_preview import percent_from_capture_click
from src.ui_positions import Point, UiPositions


class CoordinateSystemTests(unittest.TestCase):
    def test_point_to_pixels(self) -> None:
        point = Point(92.0, 50.0)
        self.assertEqual(point.to_pixels(1920, 1080), (1766, 540))

    def test_percent_from_capture_click_roundtrip(self) -> None:
        width, height = 2560, 1440
        rel_x, rel_y = 2304, 1324
        x_percent, y_percent = percent_from_capture_click(
            rel_x,
            rel_y,
            width=width,
            height=height,
        )
        self.assertEqual((x_percent, y_percent), (90.0, 91.94))

        back_x, back_y = Point(x_percent, y_percent).to_pixels(width, height)
        self.assertEqual((back_x, back_y), (2304, 1323))

    def test_capture_region_to_absolute(self) -> None:
        region = CaptureRegion(left=100, top=200, width=1920, height=1080, mode="window")
        self.assertEqual(region.to_absolute(960, 540), (1060, 740))

    @patch("src.ui_positions.resolve_capture_region")
    def test_ui_positions_click_pixels_uses_same_region(self, mock_resolve) -> None:
        region = CaptureRegion(left=50, top=80, width=1600, height=900, mode="window")
        mock_resolve.return_value = region

        ui = UiPositions.from_dict(
            {"join_server_list": {"x_percent": 92.0, "y_percent": 92.0}},
            monitor_index=1,
            capture_settings=CaptureSettings(mode="window"),
        )
        abs_x, abs_y = ui.click_pixels(ui.join_server_list)
        self.assertEqual(abs_x, 50 + int(1600 * 0.92))
        self.assertEqual(abs_y, 80 + int(900 * 0.92))
        mock_resolve.assert_called_once()
        self.assertTrue(mock_resolve.call_args.kwargs["strict_window"])

    @patch("src.ui_positions.resolve_capture_region")
    def test_pick_and_click_use_same_formula(self, mock_resolve) -> None:
        region = CaptureRegion(left=300, top=100, width=1920, height=1080, mode="monitor")
        mock_resolve.return_value = region

        click_x, click_y = 960, 540
        x_percent, y_percent = percent_from_capture_click(
            click_x,
            click_y,
            width=region.width,
            height=region.height,
        )

        ui = UiPositions.from_dict(
            {"join_server_list": {"x_percent": x_percent, "y_percent": y_percent}},
            capture_settings=CaptureSettings(mode="monitor"),
        )
        abs_x, abs_y = ui.click_pixels(ui.join_server_list)
        self.assertEqual(abs_x, region.left + click_x)
        self.assertEqual(abs_y, region.top + click_y)


if __name__ == "__main__":
    unittest.main()
