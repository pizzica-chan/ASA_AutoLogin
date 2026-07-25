"""ログイン成功 HUD (login_success) 判定のテスト"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from src.button_templates import ButtonConfig
from src.default_assets import BUNDLED_BUTTON_NAMES, list_button_paths
from src.login_flow import (
    LOGIN_SUCCESS_SEARCH_REGION,
    LoginAutomator,
    RetryConfig,
    TemplateConfig,
)
from src.ui_positions import UiPositions
from src.vision import MatchResult


class LoginSuccessDetectionTests(unittest.TestCase):
    def _automator(self, *, has_login_success: bool = True) -> LoginAutomator:
        buttons = ButtonConfig()
        if has_login_success:
            buttons.paths["login_success"] = "templates/buttons/login_success.png"
        return LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(login_success_threshold=0.62),
            retry=RetryConfig(),
            ui=UiPositions.from_dict({}),
            buttons=buttons,
        )

    def _step3_automator(self) -> LoginAutomator:
        automator = self._automator()
        automator._running = True
        automator.retry = RetryConfig(
            result_timeout=0.1,
            poll_interval=0.01,
            stuck_server_list_seconds=999,
        )
        return automator

    def test_login_success_search_region_is_bottom_right(self) -> None:
        self.assertEqual(LOGIN_SUCCESS_SEARCH_REGION[0], 0.78)
        self.assertEqual(LOGIN_SUCCESS_SEARCH_REGION[2], 1.0)

    def test_detects_login_success_hud_first(self) -> None:
        automator = self._automator()
        screen = MagicMock()
        hud = MatchResult(True, 0.71, 100, 200, (80, 150), (120, 250))

        with patch.object(automator, "_find_button", return_value=hud) as mock_find:
            ready, score, method = automator._is_login_success_ready(screen=screen)

        self.assertTrue(ready)
        self.assertEqual(score, 0.71)
        self.assertEqual(method, "login_success")
        mock_find.assert_called_once_with("login_success", screen=screen, strict=False)

    def test_falls_back_to_in_game_screen_template(self) -> None:
        automator = self._automator()
        screen = MagicMock()
        hud_miss = MatchResult(False, 0.40, 0, 0, (0, 0), (0, 0))

        with patch.object(automator, "_find_button", return_value=hud_miss):
            with patch.object(automator, "_match_screen", return_value=(True, 0.80)) as mock_screen:
                ready, score, method = automator._is_login_success_ready(screen=screen)

        self.assertTrue(ready)
        self.assertEqual(score, 0.80)
        self.assertEqual(method, "in_game")
        mock_screen.assert_called_once_with("in_game", screen=screen)

    def test_returns_false_when_both_miss(self) -> None:
        automator = self._automator()
        hud_miss = MatchResult(False, 0.35, 0, 0, (0, 0), (0, 0))

        with patch.object(automator, "_find_button", return_value=hud_miss):
            with patch.object(automator, "_match_screen", return_value=(False, 0.30)):
                ready, score, method = automator._is_login_success_ready(screen=MagicMock())

        self.assertFalse(ready)
        self.assertEqual(score, 0.35)
        self.assertEqual(method, "")

    def test_skips_hud_when_png_missing(self) -> None:
        automator = self._automator(has_login_success=False)

        with patch.object(automator.buttons, "has", return_value=False):
            with patch.object(automator, "_find_button") as mock_find:
                with patch.object(automator, "_match_screen", return_value=(True, 0.77)):
                    ready, _score, method = automator._is_login_success_ready(screen=MagicMock())

        self.assertTrue(ready)
        self.assertEqual(method, "in_game")
        mock_find.assert_not_called()

    def test_bundled_login_success_is_registered(self) -> None:
        self.assertIn("login_success", BUNDLED_BUTTON_NAMES)

    def test_list_button_paths_finds_user_login_success(self) -> None:
        path = Path("templates/buttons/login_success.png")
        if not path.exists():
            self.skipTest("login_success.png が未配置")
        paths = list_button_paths("login_success")
        self.assertTrue(paths)
        self.assertTrue(Path(paths[0]).exists())

    def test_login_success_relaxed_threshold_is_lower_than_primary(self) -> None:
        automator = self._automator()
        screen = MagicMock()
        thresholds_seen: list[float] = []

        def capture(*_args: object, **kwargs: object) -> MatchResult:
            thresholds_seen.append(float(kwargs["threshold"]))  # type: ignore[arg-type]
            return MatchResult(False, 0.58, 0, 0, (0, 0), (0, 0))

        automator.vision.find_button_on_screen.side_effect = capture
        automator._find_button("login_success", screen=screen, strict=False)

        self.assertEqual(thresholds_seen, [0.62, 0.55])

    def test_is_server_list_visible_uses_screen_score_threshold(self) -> None:
        automator = self._automator()
        self.assertTrue(automator._is_server_list_visible(score=0.72))
        self.assertFalse(automator._is_server_list_visible(score=0.50))

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_is_login_success_ready", return_value=(True, 0.9, "login_success"))
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.90))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.90)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_skips_success_while_server_list_visible(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        mock_success,
        mock_sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.02, 100.11, 100.11])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "timeout")
        mock_success.assert_not_called()
        mock_sleep.assert_called()

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_is_login_success_ready", return_value=(True, 0.9, "login_success"))
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.90))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.90)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_sleeps_while_server_list_visible(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        _success,
        mock_sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.02, 100.11, 100.11])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            automator._step3_wait_for_login()

        self.assertGreaterEqual(mock_sleep.call_count, 1)
        mock_sleep.assert_called_with(automator.retry.poll_seconds)

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_is_login_success_ready")
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.10)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=True)
    def test_step3_failure_dialog_before_success(
        self,
        _network,
        _connection,
        _list_score,
        mock_success,
        _sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.01])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "failure_network")
        mock_success.assert_not_called()

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_is_login_success_ready")
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.10)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=True)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_connection_failed_before_success(
        self,
        _network,
        _connection,
        _list_score,
        mock_success,
        _sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.01])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "failure_browser")
        mock_success.assert_not_called()

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.0))
    @patch.object(
        LoginAutomator,
        "_is_login_success_ready",
        return_value=(True, 0.88, "login_success"),
    )
    @patch.object(LoginAutomator, "_is_join_server_list_visible", return_value=False)
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.10))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.10)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_success_when_not_on_server_list(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        _join,
        _success,
        _movie,
        _sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.01])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "success")

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.0))
    @patch.object(LoginAutomator, "_is_login_success_ready", return_value=(True, 0.9, "login_success"))
    @patch.object(LoginAutomator, "_is_join_server_list_visible", return_value=True)
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.40))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.40)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_skips_success_when_join_visible_even_if_score_low(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        _join,
        mock_success,
        _movie,
        _sleep,
    ) -> None:
        automator = self._step3_automator()
        times = iter([100.0, 100.01, 100.02, 100.11, 100.11])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "timeout")
        mock_success.assert_not_called()

    def test_is_server_list_ready_returns_score_when_join_missing(self) -> None:
        automator = self._automator()
        join_miss = MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))

        with patch.object(automator, "_has_connection_failed_dialog", return_value=False):
            with patch.object(automator, "_has_network_failure_dialog", return_value=False):
                with patch.object(automator, "_is_coordinates_only", return_value=False):
                    with patch.object(automator, "_find_button", return_value=join_miss):
                        with patch.object(automator, "_screen_score", return_value=0.88):
                            ready, score = automator._is_server_list_ready(screen=MagicMock())

        self.assertFalse(ready)
        self.assertEqual(score, 0.88)

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.0))
    @patch.object(LoginAutomator, "_is_login_success_ready")
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.88))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.88)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_no_stuck_timeout_when_visible_but_not_ready(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        mock_success,
        _movie,
        _sleep,
    ) -> None:
        automator = self._automator()
        automator._running = True
        automator.retry = RetryConfig(
            result_timeout=0.2,
            poll_interval=0.01,
            stuck_server_list_seconds=0.05,
        )
        times = iter([100.0, 100.02, 100.04, 100.06, 100.21, 100.21])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "timeout")
        mock_success.assert_not_called()

    @patch.object(LoginAutomator, "_sleep", return_value=True)
    @patch.object(LoginAutomator, "_match_screen", return_value=(False, 0.0))
    @patch.object(LoginAutomator, "_is_login_success_ready")
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(True, 0.95))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.95)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_stuck_timeout_when_ready(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        mock_success,
        _movie,
        _sleep,
    ) -> None:
        automator = self._automator()
        automator._running = True
        automator.retry = RetryConfig(
            result_timeout=10.0,
            poll_interval=0.01,
            stuck_server_list_seconds=0.05,
        )
        times = iter([100.0, 100.02, 100.04, 100.08, 100.10, 100.10, 100.10])

        with patch("src.login_flow.time.time", side_effect=lambda: next(times)):
            result = automator._step3_wait_for_login()

        self.assertEqual(result, "timeout")
        mock_success.assert_not_called()

    @patch.object(LoginAutomator, "_is_login_success_ready")
    @patch.object(LoginAutomator, "_is_server_list_ready", return_value=(False, 0.88))
    @patch.object(LoginAutomator, "_server_list_visible_score", return_value=0.88)
    @patch.object(LoginAutomator, "_has_connection_failed_dialog", return_value=False)
    @patch.object(LoginAutomator, "_has_network_failure_dialog", return_value=False)
    def test_step3_detects_movie_while_server_list_visible(
        self,
        _network,
        _connection,
        _list_score,
        _ready,
        mock_success,
    ) -> None:
        automator = self._step3_automator()

        def stop_after_sleep(_seconds: float) -> bool:
            automator._running = False
            return True

        with patch.object(LoginAutomator, "_sleep", side_effect=stop_after_sleep):
            with patch.object(LoginAutomator, "_match_screen", return_value=(True, 0.85)) as mock_movie:
                with patch("src.login_flow.time.time", return_value=100.0):
                    automator._step3_wait_for_login()

        mock_success.assert_not_called()
        mock_movie.assert_any_call("login_movie", screen=ANY)


if __name__ == "__main__":
    unittest.main()
