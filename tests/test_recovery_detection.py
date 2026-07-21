"""coordinates_only 復帰ダイアログのボタン検出フォールバック"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions
from src.vision import MatchResult


class RecoveryDetectionTests(unittest.TestCase):
    def _automator(self) -> LoginAutomator:
        ui = UiPositions.from_dict(
            {
                "cancel_failed": {"x_percent": 60.0, "y_percent": 69.0},
                "accept_network_failure": {"x_percent": 49.0, "y_percent": 68.0},
            },
        )
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(click_mode="coordinates_only"),
            retry=RetryConfig(),
            ui=ui,
            buttons=ButtonConfig(),
            config={"matching": {"click_mode": "coordinates_only"}},
        )

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.31))
    @patch.object(LoginAutomator, "_find_button")
    def test_connection_failed_uses_button_when_screen_misses(
        self,
        mock_find_button,
        _mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.82, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        self.assertTrue(automator._has_connection_failed_dialog(screen=screen))
        mock_find_button.assert_called()

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.28))
    @patch.object(LoginAutomator, "_find_button")
    def test_network_failure_uses_button_when_screen_misses(
        self,
        mock_find_button,
        _mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.79, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        self.assertTrue(automator._has_network_failure_dialog(screen=screen))

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.56))
    @patch.object(LoginAutomator, "_find_button")
    def test_step5_ready_uses_join_game_button_in_coordinates_only(
        self,
        mock_find_button,
        mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.91, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        automator._running = True
        automator.vision.capture_screen.return_value = np.zeros((900, 1600, 3), dtype=np.uint8)
        automator.retry = RetryConfig(poll_interval=0.01, screen_stable_polls=1, recovery_timeout=1.0)
        self.assertTrue(automator._wait_for_step5_ready(1.0))
        mock_find_button.assert_called()
        mock_match.assert_not_called()

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.21))
    @patch.object(LoginAutomator, "_find_button")
    def test_wait_for_screen_logs_miss_scores(
        self,
        mock_find_button,
        _mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(False, 0.42, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        automator._running = True
        automator.retry = RetryConfig(poll_interval=0.01, screen_stable_polls=1)
        with patch.object(automator.buttons, "list_paths", return_value=["/fake/cancel.png"]):
            self.assertFalse(
                automator._wait_for_screen(
                    "connection_failed",
                    0.05,
                    button_key="cancel_failed",
                ),
            )
        mock_find_button.assert_called()


if __name__ == "__main__":
    unittest.main()
