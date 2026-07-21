"""② MODS 画面の検出（coordinates_only 含む）"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions
from src.vision import MatchResult, Vision


class ModsDetectionTests(unittest.TestCase):
    def _automator(
        self,
        *,
        click_mode: str = "coordinates_only",
        mods_detect_mode: str = "hybrid",
        mods_screen_region: str = "center",
    ) -> LoginAutomator:
        ui = UiPositions.from_dict(
            {
                "join_server_list": {"x_percent": 90.62, "y_percent": 87.67},
                "join_mods": {"x_percent": 27.38, "y_percent": 86.89},
            },
        )
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(
                click_mode=click_mode,
                mods_screen_threshold=0.55,
                mods_detect_mode=mods_detect_mode,
                mods_screen_region=mods_screen_region,
            ),
            retry=RetryConfig(),
            ui=ui,
            buttons=ButtonConfig(),
        )

    @patch.object(LoginAutomator, "_mods_screen_score", return_value=0.36)
    @patch.object(LoginAutomator, "_find_button")
    def test_hybrid_uses_button_when_screen_score_low(
        self,
        mock_find_button,
        _mock_score,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.84, 0, 0, (0, 0), (0, 0))
        automator = self._automator(mods_detect_mode="hybrid")
        self.assertTrue(automator._is_mods_dialog_visible(screen=np.zeros((900, 1600, 3), dtype=np.uint8)))
        mock_find_button.assert_called_once()

    @patch.object(LoginAutomator, "_mods_screen_score", return_value=0.36)
    @patch.object(LoginAutomator, "_find_button")
    def test_screen_mode_ignores_button(
        self,
        mock_find_button,
        _mock_score,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.84, 0, 0, (0, 0), (0, 0))
        automator = self._automator(mods_detect_mode="screen")
        self.assertFalse(automator._is_mods_dialog_visible(screen=np.zeros((900, 1600, 3), dtype=np.uint8)))
        mock_find_button.assert_not_called()

    @patch.object(LoginAutomator, "_mods_screen_score", return_value=0.80)
    @patch.object(LoginAutomator, "_find_button")
    def test_button_mode_ignores_screen(
        self,
        mock_find_button,
        _mock_score,
    ) -> None:
        mock_find_button.return_value = MatchResult(False, 0.40, 0, 0, (0, 0), (0, 0))
        automator = self._automator(mods_detect_mode="button")
        self.assertFalse(automator._is_mods_dialog_visible(screen=np.zeros((900, 1600, 3), dtype=np.uint8)))
        mock_find_button.assert_called_once()

    @patch.object(LoginAutomator, "_mods_screen_score", return_value=0.36)
    @patch.object(LoginAutomator, "_find_button")
    def test_hybrid_false_when_both_miss(
        self,
        mock_find_button,
        _mock_score,
    ) -> None:
        mock_find_button.return_value = MatchResult(False, 0.40, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        self.assertFalse(automator._is_mods_dialog_visible(screen=np.zeros((900, 1600, 3), dtype=np.uint8)))

    def test_center_region_improves_self_similarity(self) -> None:
        path = "assets/defaults/fallback_screens/required_mods.png"
        screen = cv2.imread(path)
        resized = cv2.resize(screen, (1600, 900))
        vision = Vision(threshold=0.55)
        full = vision.compare_with_reference(path, threshold=0.0, screen=resized)
        center = vision.compare_with_reference(
            path,
            threshold=0.0,
            screen=resized,
            region=(0.15, 0.08, 0.85, 0.92),
        )
        self.assertGreater(center.confidence, 0.9)
        self.assertGreater(full.confidence, 0.9)


if __name__ == "__main__":
    unittest.main()
