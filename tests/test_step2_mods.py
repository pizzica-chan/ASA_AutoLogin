"""② MODS フローの統合テスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions


class Step2ModsTests(unittest.TestCase):
    def _automator(self, *, click_mode: str = "image") -> LoginAutomator:
        ui = UiPositions.from_dict(
            {
                "join_server_list": {"x_percent": 90.0, "y_percent": 90.0},
                "join_mods": {"x_percent": 27.0, "y_percent": 87.0},
            },
        )
        buttons = ButtonConfig()
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(click_mode=click_mode),
            retry=RetryConfig(
                poll_interval=0.01,
                mods_wait_seconds=1.0,
                transition_timeout=0.2,
                transition_settle=0.0,
            ),
            ui=ui,
            buttons=buttons,
        )

    @patch.object(LoginAutomator, "_wait_for_mods_dismissed", return_value=True)
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    @patch.object(LoginAutomator, "_focus_game")
    @patch.object(LoginAutomator, "_wait_for_mods_dialog_stable", return_value=(True, 0.67))
    @patch("src.login_flow.time.sleep")
    def test_step2_clicks_without_duplicate_wait(
        self,
        _sleep,
        _stable,
        _focus,
        mock_click,
        _dismissed,
    ) -> None:
        automator = self._automator()
        automator._running = True
        with patch.object(automator.buttons, "has", return_value=True):
            with patch.object(
                LoginAutomator,
                "_click_target_when_ready",
                wraps=automator._click_target_when_ready,
            ) as when_ready:
                self.assertTrue(automator._step2_maybe_join_mods())
        when_ready.assert_called_once()
        self.assertTrue(when_ready.call_args.kwargs.get("skip_wait"))
        mock_click.assert_called_once()

    @patch.object(LoginAutomator, "_wait_for_mods_dialog_stable")
    @patch.object(LoginAutomator, "_click_target_when_ready")
    def test_step2_skips_when_option_enabled(
        self,
        mock_click_when_ready,
        mock_stable,
    ) -> None:
        automator = self._automator()
        automator.templates.skip_required_mods = True
        automator._running = True

        self.assertTrue(automator._step2_maybe_join_mods())
        mock_stable.assert_not_called()
        mock_click_when_ready.assert_not_called()


if __name__ == "__main__":
    unittest.main()
