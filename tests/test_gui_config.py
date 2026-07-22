"""GUI 設定の永続化・クリックインジケータ連携テスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.app_service import apply_ui_overrides, load_default_config
from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, LoginState, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions


class GuiConfigTests(unittest.TestCase):
    def test_apply_ui_overrides_persists_show_click_indicator(self) -> None:
        config = load_default_config()
        updated = apply_ui_overrides(config, show_click_indicator=False)
        self.assertFalse(updated["display"]["show_click_indicator"])

        updated = apply_ui_overrides(updated, show_click_indicator=True)
        self.assertTrue(updated["display"]["show_click_indicator"])


class LoginRunIndicatorTests(unittest.TestCase):
    def _automator(self) -> LoginAutomator:
        ui = UiPositions.from_dict(
            {"join_server_list": {"x_percent": 92.0, "y_percent": 92.0}},
        )
        buttons = ButtonConfig()
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(server_list="templates/server_list.png"),
            retry=RetryConfig(),
            ui=ui,
            buttons=buttons,
            config={"display": {"show_click_indicator": True}},
        )

    @patch("src.login_flow.input_handler.configure_click_indicator")
    @patch("src.login_flow.resolve_screen_path", return_value=None)
    def test_run_skips_indicator_when_failing_before_loop(
        self,
        _resolve,
        mock_configure,
    ) -> None:
        automator = self._automator()
        result = automator.run()
        self.assertEqual(result, LoginState.FAILED)
        mock_configure.assert_not_called()

    @patch("src.login_flow.input_handler.configure_click_indicator")
    @patch("src.login_flow.LoginAutomator._should_retry", return_value=False)
    @patch("src.login_flow.resolve_screen_path", return_value="/fake/server_list.png")
    def test_run_disables_click_indicator_after_loop(
        self,
        _resolve,
        _retry,
        mock_configure,
    ) -> None:
        automator = self._automator()
        automator.vision.capture_screen.return_value = MagicMock()

        result = automator.run()
        self.assertEqual(result, LoginState.FAILED)
        mock_configure.assert_any_call(True)
        mock_configure.assert_any_call(False)

    @patch("src.login_flow.input_handler.configure_click_indicator")
    @patch("src.login_flow.LoginAutomator._should_retry", return_value=False)
    @patch("src.login_flow.resolve_screen_path", return_value="/fake/server_list.png")
    def test_run_keeps_indicator_disabled_when_config_false(
        self,
        _resolve,
        _retry,
        mock_configure,
    ) -> None:
        automator = self._automator()
        automator.config = {"display": {"show_click_indicator": False}}
        automator.vision.capture_screen.return_value = MagicMock()

        automator.run()

        mock_configure.assert_any_call(False)
        self.assertFalse(any(call.args == (True,) for call in mock_configure.call_args_list))


if __name__ == "__main__":
    unittest.main()
