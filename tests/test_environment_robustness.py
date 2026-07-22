"""環境差異対策の回帰テスト。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.app_service import CONFIG_SCHEMA_VERSION, load_config, normalize_config
from src.input_handler import find_window_candidates
from src.preflight_diagnostics import _difference_items
from src.vision import Vision


class ConfigNormalizationTests(unittest.TestCase):
    def test_invalid_values_are_recovered_without_dropping_unknown_keys(self) -> None:
        config = {
            "display": {"monitor_index": "x", "capture_mode": "typo"},
            "matching": {"click_mode": "bad", "screen_threshold": 99},
            "custom": {"keep": True},
        }
        normalized = normalize_config(config)
        self.assertEqual(normalized["display"]["monitor_index"], 1)
        self.assertEqual(normalized["display"]["capture_mode"], "window")
        self.assertEqual(normalized["matching"]["click_mode"], "image")
        self.assertEqual(normalized["matching"]["screen_threshold"], 0.95)
        self.assertTrue(normalized["custom"]["keep"])
        self.assertEqual(normalized["meta"]["config_schema_version"], CONFIG_SCHEMA_VERSION)
        self.assertEqual(config["display"]["capture_mode"], "typo")

    def test_broken_yaml_reports_error_without_overwriting_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            original = "display:\n\tmonitor_index: ["
            path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "形式が壊れています"):
                load_config(path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)


class EnvironmentDifferenceTests(unittest.TestCase):
    def test_aspect_change_is_warning(self) -> None:
        config = {
            "meta": {
                "setup_capture_width": 1920,
                "setup_capture_height": 1080,
                "setup_dpi": 96,
            }
        }
        items = _difference_items(config, 1280, 1024, 96)
        self.assertEqual(items[0].level, "warning")
        self.assertEqual(items[0].title, "画面比率")


class WindowSelectionTests(unittest.TestCase):
    @patch("src.input_handler.win32gui.IsIconic", side_effect=[True, False])
    @patch(
        "src.input_handler.win32gui.GetClientRect",
        side_effect=[(0, 0, 1920, 1080), (0, 0, 1280, 720)],
    )
    @patch(
        "src.input_handler.win32gui.GetWindowText",
        side_effect=["ARK: Survival Ascended", "ARK: Survival Ascended"],
    )
    @patch("src.input_handler.win32gui.IsWindowVisible", return_value=True)
    @patch("src.input_handler.win32gui.EnumWindows")
    def test_visible_non_minimized_window_is_preferred(
        self,
        enum_windows,
        _visible,
        _title,
        _rect,
        _iconic,
    ) -> None:
        enum_windows.side_effect = lambda callback, arg: [
            callback(10, arg),
            callback(20, arg),
        ]
        self.assertEqual(find_window_candidates("ARK"), [20, 10])


class AdaptiveVisionTests(unittest.TestCase):
    def test_setup_size_ratio_adds_adaptive_button_scale(self) -> None:
        rng = np.random.default_rng(42)
        template = rng.integers(0, 256, (20, 24, 3), dtype=np.uint8)
        scaled = cv2.resize(template, (30, 25), interpolation=cv2.INTER_LINEAR)
        screen = np.zeros((125, 125, 3), dtype=np.uint8)
        screen[40:65, 50:80] = scaled

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "button.png"
            cv2.imwrite(str(path), template)
            vision = Vision(setup_capture_size=(100, 100))
            with patch.object(vision, "to_absolute", side_effect=lambda x, y: (x, y)):
                result = vision.find_button_on_screen(
                    path,
                    threshold=0.95,
                    screen=screen,
                    extra_scales=(),
                )
        self.assertTrue(result.found)
        self.assertAlmostEqual(result.scale, 1.25, places=2)


if __name__ == "__main__":
    unittest.main()
