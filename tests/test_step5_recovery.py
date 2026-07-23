"""⑤ メインメニュー・④ 空一覧の復帰検出"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions
from src.vision import MatchResult


class Step5RecoveryTests(unittest.TestCase):
    def _automator(self) -> LoginAutomator:
        ui = UiPositions.from_dict(
            {
                "join_server_list": {"x_percent": 90.62, "y_percent": 87.67},
                "join_mods": {"x_percent": 27.38, "y_percent": 86.89},
                "back_empty_list": {"x_percent": 8.5, "y_percent": 81.89},
                "join_game": {"x_percent": 49.81, "y_percent": 53.11},
            },
        )
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(click_mode="coordinates_only"),
            retry=RetryConfig(poll_interval=0.01, screen_stable_polls=1),
            ui=ui,
            buttons=ButtonConfig(),
            config={"matching": {"click_mode": "coordinates_only"}},
        )

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.56))
    @patch.object(LoginAutomator, "_find_button")
    def test_main_menu_ready_uses_join_game_button_when_screen_low(
        self,
        mock_find_button,
        _mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 0.81, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        ready, join_score, menu_score = automator._is_main_menu_ready(screen=screen)
        self.assertTrue(ready)
        self.assertAlmostEqual(join_score, 0.81)
        self.assertAlmostEqual(menu_score, 0.0)
        mock_find_button.assert_called_once()
        _mock_match.assert_not_called()

    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.0))
    @patch.object(LoginAutomator, "_find_button")
    def test_empty_server_list_uses_back_button_without_screen_template(
        self,
        mock_find_button,
        _mock_match,
    ) -> None:
        mock_find_button.return_value = MatchResult(True, 1.0, 0, 0, (0, 0), (0, 0))
        automator = self._automator()
        screen = np.zeros((900, 1600, 3), dtype=np.uint8)
        self.assertTrue(automator._is_empty_server_list_visible(screen=screen))
        mock_find_button.assert_called_once()

    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_click_target_when_ready", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_is_main_menu_ready", return_value=(False, 0.0, 0.0))
    @patch.object(LoginAutomator, "_is_server_list_ready", side_effect=[(False, 0.0), (True, 0.91)])
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    @patch.object(LoginAutomator, "_is_empty_server_list_visible", return_value=True)
    def test_ensure_at_step1_recovers_from_empty_list_via_button(
        self,
        _empty,
        _net,
        _conn,
        _ready,
        _main,
        _after,
        _click,
        _return,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._ensure_at_step1())
        _click.assert_called_once_with("back_empty_list", "④ BACK")

    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_is_main_menu_ready", return_value=(True, 0.82, 0.0))
    @patch.object(LoginAutomator, "_is_empty_server_list_visible", return_value=False)
    @patch.object(LoginAutomator, "_is_server_list_ready", side_effect=[(False, 0.0), (True, 0.91)])
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_ensure_at_step1_recovers_from_main_menu_via_button(
        self,
        _net,
        _conn,
        _ready,
        _empty,
        _main,
        mock_return,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._ensure_at_step1())
        mock_return.assert_called_once()


if __name__ == "__main__":
    unittest.main()
