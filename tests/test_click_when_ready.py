"""_click_target_when_ready の待機・クリック制御テスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.button_templates import ButtonConfig
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig
from src.ui_positions import Point, UiPositions


class ClickWhenReadyTests(unittest.TestCase):
    def _automator(
        self,
        *,
        click_mode: str = "image",
        buttons: ButtonConfig | None = None,
        ui: UiPositions | None = None,
    ) -> LoginAutomator:
        if ui is None:
            ui = UiPositions.from_dict(
                {
                    "join_server_list": {"x_percent": 92.0, "y_percent": 92.0},
                    "back_empty_list": {"x_percent": 5.0, "y_percent": 92.0},
                    "join_game": {"x_percent": 29.0, "y_percent": 91.0},
                },
            )
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(click_mode=click_mode),
            retry=RetryConfig(transition_settle=0.0),
            ui=ui,
            buttons=buttons or ButtonConfig(),
        )

    def test_wait_fn_uses_screen_when_only_coordinates_fallback(self) -> None:
        automator = self._automator(click_mode="coordinates")
        with patch.object(automator.buttons, "get", return_value=None):
            fn = automator._wait_before_click_fn("join_server_list")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    def test_join_server_list_always_uses_screen_ready_wait(self) -> None:
        automator = self._automator(click_mode="image")
        with patch.object(automator.buttons, "get", return_value="/fake/join.png"):
            fn = automator._wait_before_click_fn("join_server_list")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    def test_coordinates_mode_prefers_screen_wait_when_ui_point_exists(self) -> None:
        automator = self._automator(click_mode="coordinates")
        with patch.object(automator.buttons, "get", return_value="/fake/join.png"):
            fn = automator._wait_before_click_fn("join_server_list")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    def test_join_mods_uses_screen_wait_even_in_image_mode(self) -> None:
        automator = self._automator(click_mode="image")
        with patch.object(automator.buttons, "get", return_value="/fake/join_mods.png"):
            fn = automator._wait_before_click_fn("join_mods")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    def test_join_game_uses_hybrid_wait_in_image_mode(self) -> None:
        automator = self._automator(click_mode="image")
        with patch.object(automator.buttons, "get", return_value="/fake/join_game.png"):
            fn = automator._wait_before_click_fn("join_game")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    def test_back_empty_list_uses_hybrid_wait_in_image_mode(self) -> None:
        automator = self._automator(click_mode="image")
        with patch.object(automator.buttons, "get", return_value="/fake/back.png"):
            fn = automator._wait_before_click_fn("back_empty_list")
        self.assertEqual(fn.__name__, "_wait_for_screen_before_click")

    @patch("src.login_flow.time.sleep")
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen_before_click")
    def test_skip_wait_bypasses_pre_click_wait(
        self,
        mock_screen_wait,
        mock_click,
        _sleep,
    ) -> None:
        automator = self._automator(click_mode="image")
        with patch.object(automator.buttons, "get", return_value="/fake/join_mods.png"):
            self.assertTrue(
                automator._click_target_when_ready("join_mods", "② MODS JOIN", skip_wait=True),
            )
        mock_screen_wait.assert_not_called()
        mock_click.assert_called_once()

    @patch("src.login_flow.time.sleep")
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen_before_click", return_value=False)
    def test_skips_click_when_wait_fails(
        self,
        _screen_wait,
        mock_click,
        _sleep,
    ) -> None:
        automator = self._automator(click_mode="coordinates")
        with patch.object(automator.buttons, "get", return_value=None):
            self.assertFalse(automator._click_target_when_ready("join_server_list", "① JOIN"))
        mock_click.assert_not_called()

    @patch("src.login_flow.time.sleep")
    @patch.object(LoginAutomator, "_click_target", return_value=True)
    @patch.object(LoginAutomator, "_wait_for_screen_before_click", return_value=True)
    def test_coordinates_mode_waits_via_screen_before_click(
        self,
        mock_screen_wait,
        mock_click,
        _sleep,
    ) -> None:
        automator = self._automator(click_mode="coordinates")
        with patch.object(automator.buttons, "get", return_value=None):
            self.assertTrue(automator._click_target_when_ready("join_server_list", "① JOIN"))
        mock_screen_wait.assert_called_once()
        mock_click.assert_called_once()


if __name__ == "__main__":
    unittest.main()
