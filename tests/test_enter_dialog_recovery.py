"""③-A / ⑥ の Enter キー確定リカバリーテスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.app_service import build_automator, load_default_config, normalize_config
from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions


class EnterDialogRecoveryTests(unittest.TestCase):
    def _automator(self, *, click_mode: str = "image") -> LoginAutomator:
        ui = UiPositions.from_dict(
            {
                "join_server_list": {"x_percent": 92.0, "y_percent": 92.0},
                "back_empty_list": {"x_percent": 5.0, "y_percent": 92.0},
                "join_game": {"x_percent": 29.0, "y_percent": 91.0},
            },
        )
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(click_mode=click_mode),
            retry=RetryConfig(transition_settle=0.0, poll_interval=0.01),
            ui=ui,
            buttons=ButtonConfig(),
            config={"matching": {"click_mode": click_mode}},
        )
        automator._running = True
        return automator

    @patch("src.login_flow.input_handler.press_key")
    @patch.object(LoginAutomator, "_focus_game", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen", return_value=True)
    @patch("src.login_flow.time.sleep")
    def test_confirm_dialog_with_enter_sends_enter(
        self,
        _sleep,
        _wait_screen,
        _focus,
        press_key,
    ) -> None:
        automator = self._automator()
        self.assertTrue(
            automator._confirm_dialog_with_enter(
                "connection_failed",
                "cancel_failed",
                "③-A CANCEL",
            ),
        )
        press_key.assert_called_once_with("enter")

    @patch("src.login_flow.input_handler.press_key")
    @patch.object(LoginAutomator, "_focus_game", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen", return_value=False)
    def test_confirm_dialog_with_enter_skips_enter_when_wait_fails(
        self,
        _wait_screen,
        _focus,
        press_key,
    ) -> None:
        automator = self._automator()
        self.assertFalse(
            automator._confirm_dialog_with_enter(
                "network_failure",
                "accept_network_failure",
                "⑥ ACCEPT",
            ),
        )
        press_key.assert_not_called()

    @patch("src.login_flow.input_handler.press_key")
    @patch.object(LoginAutomator, "_focus_game", return_value=False)
    @patch.object(LoginAutomator, "_wait_for_screen", return_value=True)
    @patch("src.login_flow.time.sleep")
    def test_confirm_dialog_with_enter_skips_enter_when_focus_fails(
        self,
        _sleep,
        _wait_screen,
        _focus,
        press_key,
    ) -> None:
        automator = self._automator()
        self.assertFalse(
            automator._confirm_dialog_with_enter(
                "connection_failed",
                "cancel_failed",
                "③-A CANCEL",
            ),
        )
        press_key.assert_not_called()

    @patch("src.login_flow.input_handler.press_key")
    @patch.object(LoginAutomator, "_focus_game", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen", return_value=True)
    @patch("src.login_flow.time.sleep")
    def test_confirm_dialog_with_enter_respects_stop_flag(
        self,
        _sleep,
        _wait_screen,
        _focus,
        press_key,
    ) -> None:
        automator = self._automator()
        automator._running = False
        self.assertFalse(
            automator._confirm_dialog_with_enter(
                "connection_failed",
                "cancel_failed",
                "③-A CANCEL",
            ),
        )
        press_key.assert_not_called()

    @patch.object(LoginAutomator, "_can_use_button_detection", return_value=True)
    @patch("src.login_flow.resolve_screen_path", return_value=None)
    def test_can_detect_connection_failed_via_button(
        self,
        _screen,
        _button,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._can_detect_connection_failed())

    @patch.object(LoginAutomator, "_can_use_button_detection", return_value=False)
    @patch("src.login_flow.resolve_screen_path", return_value="/fake/connection_failed.png")
    def test_can_detect_connection_failed_via_screen(
        self,
        _screen,
        _button,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._can_detect_connection_failed())

    @patch.object(LoginAutomator, "_can_use_button_detection", return_value=False)
    @patch("src.login_flow.resolve_screen_path", return_value=None)
    def test_can_detect_connection_failed_false_when_nothing_configured(
        self,
        _screen,
        _button,
    ) -> None:
        automator = self._automator()
        self.assertFalse(automator._can_detect_connection_failed())

    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_confirm_dialog_with_enter", return_value=True)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=True)
    @patch.object(LoginAutomator, "_can_detect_connection_failed", return_value=True)
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(True, 0.9))
    def test_recover_connection_failed_uses_enter_not_click(
        self,
        _ready,
        _can_detect,
        _has_dialog,
        mock_confirm,
        _after,
        _return,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._recover_after_connection_failed())
        mock_confirm.assert_called_once_with(
            "connection_failed",
            "cancel_failed",
            "③-A CANCEL",
        )

    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_proceed_from_title_screen_to_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_title_screen", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_confirm_dialog_with_enter", return_value=True)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=True)
    @patch.object(LoginAutomator, "_can_detect_network_failure", return_value=True)
    def test_recover_network_failure_uses_enter_not_click(
        self,
        _can_detect,
        _has_dialog,
        mock_confirm,
        _after,
        _title,
        _proceed,
        _return,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._recover_after_network_failure())
        mock_confirm.assert_called_once_with(
            "network_failure",
            "accept_network_failure",
            "⑥ ACCEPT",
        )

    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=True)
    @patch.object(LoginAutomator, "_can_detect_connection_failed", return_value=False)
    def test_recover_connection_failed_aborts_without_detection_assets(
        self,
        _can_detect,
        _has_dialog,
    ) -> None:
        automator = self._automator()
        self.assertFalse(automator._recover_after_connection_failed())

    @patch("src.login_flow.resolve_screen_path", return_value=None)
    @patch.object(LoginAutomator, "_wait_for_network_failure_dismissed", return_value=True)
    def test_wait_for_title_screen_without_template_proceeds_after_dismiss(
        self,
        mock_dismiss,
        _resolve,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._wait_for_title_screen(1.0))
        mock_dismiss.assert_called_once_with(1.0)

    @patch("src.login_flow.resolve_screen_path", return_value=None)
    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_proceed_from_title_screen_to_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_network_failure_dismissed", return_value=True)
    @patch.object(LoginAutomator, "_wait_after_click")
    @patch.object(LoginAutomator, "_confirm_dialog_with_enter", return_value=True)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=True)
    @patch.object(LoginAutomator, "_can_detect_network_failure", return_value=True)
    def test_recover_network_failure_without_title_template_sends_space(
        self,
        _can_detect,
        _has_dialog,
        _confirm,
        _after,
        _dismiss,
        mock_proceed,
        _return,
        _resolve,
    ) -> None:
        automator = self._automator()
        self.assertTrue(automator._recover_after_network_failure())
        mock_proceed.assert_called_once()

    @patch.object(LoginAutomator, "_return_to_server_list_via_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_proceed_from_title_screen_to_main_menu", return_value=True)
    @patch.object(LoginAutomator, "_is_empty_server_list_visible", return_value=False)
    @patch.object(LoginAutomator, "_is_main_menu_ready", return_value=(False, 0.0, 0.0))
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_is_server_list_ready", side_effect=[(False, 0.0), (True, 0.88)])
    def test_ensure_at_step1_recovers_from_title_screen(
        self,
        _ready,
        _conn,
        _net,
        _main,
        _empty,
        mock_proceed,
        _return,
    ) -> None:
        automator = self._automator()
        automator._running = True
        self.assertTrue(automator._ensure_at_step1())
        mock_proceed.assert_called_once()

    def test_login_flow_never_clicks_obsolete_button_keys(self) -> None:
        import inspect

        from src import login_flow as lf

        source = inspect.getsource(lf.LoginAutomator)
        self.assertNotIn('_click_target_when_ready("cancel_failed"', source)
        self.assertNotIn('_click_target_when_ready("accept_network_failure"', source)
        self.assertNotIn('_click_target("cancel_failed"', source)
        self.assertNotIn('_click_target("accept_network_failure"', source)


class EnterDialogConfigTests(unittest.TestCase):
    def test_coordinates_only_configured_without_obsolete_ui_keys(self) -> None:
        ui = UiPositions.from_dict(
            {
                "join_server_list": {"x_percent": 92.0, "y_percent": 92.0},
                "back_empty_list": {"x_percent": 5.0, "y_percent": 92.0},
                "join_game": {"x_percent": 29.0, "y_percent": 91.0},
            },
        )
        self.assertTrue(ui.is_configured(coordinates_only=True))
        self.assertFalse(hasattr(ui, "cancel_failed"))
        self.assertFalse(hasattr(ui, "accept_network_failure"))

    def test_default_config_has_no_obsolete_ui_keys(self) -> None:
        config = normalize_config(load_default_config())
        ui = config.get("ui", {})
        self.assertNotIn("cancel_failed", ui)
        self.assertNotIn("accept_network_failure", ui)

    @patch("src.app_service.build_vision")
    @patch("src.app_service.ensure_default_assets")
    def test_build_automator_accepts_normalized_default_config(
        self,
        _assets,
        mock_vision,
    ) -> None:
        mock_vision.return_value = MagicMock()
        config = normalize_config(load_default_config())
        automator = build_automator(config)
        self.assertFalse(hasattr(automator.ui, "cancel_failed"))
        self.assertFalse(hasattr(automator.ui, "accept_network_failure"))


if __name__ == "__main__":
    unittest.main()
