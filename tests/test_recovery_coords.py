"""座標のみモードの復帰経路テスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig


class CoordinatesOnlyRecoveryTests(unittest.TestCase):
    def _automator(self) -> LoginAutomator:
        templates = TemplateConfig(click_mode="coordinates_only")
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=templates,
            retry=RetryConfig(),
            ui=MagicMock(),
            config={"matching": {"click_mode": "coordinates_only"}},
        )
        automator._running = True
        return automator

    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(True, 0.9))
    @patch.object(LoginAutomator, "_click_target_when_ready", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=True)
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_button", return_value=True)
    def test_connection_failed_recovery_accepts_direct_return_to_list(
        self,
        mock_wait_button,
        _mock_click,
        _mock_has_failed,
        _mock_return,
        _mock_after,
        mock_when_ready,
        _mock_ready,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._recover_after_connection_failed())
        calls = [c.args[0] for c in mock_when_ready.call_args_list]
        self.assertEqual(calls, ["cancel_failed"])
        mock_wait_button.assert_not_called()

    @patch.object(LoginAutomator, "_wait_for_step1_ready", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_click_target_when_ready", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_step5_ready", return_value=True)
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    def test_return_to_server_list_uses_when_ready_for_join_game(
        self,
        _mock_click,
        _mock_step5,
        mock_when_ready,
        _mock_after,
        _mock_step1,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._return_to_server_list_via_main_menu())
        mock_when_ready.assert_called_once()
        self.assertEqual(mock_when_ready.call_args.args[0], "join_game")


if __name__ == "__main__":
    unittest.main()
