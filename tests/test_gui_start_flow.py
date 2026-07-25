"""GUI 開始フロー（ウィンドウ整列・_on_start 分岐）のモックテスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.gui_app import LoginApp
from src.login_flow import LoginState, LoginStats


def _make_login_app_stub(*, viewable: bool = True) -> LoginApp:
    app = LoginApp.__new__(LoginApp)
    app.window_title_var = MagicMock()
    app.window_title_var.get.return_value = "ARK: Survival Ascended"
    app._append_log = MagicMock()
    app.update_idletasks = MagicMock()
    app.withdraw = MagicMock()
    app.deiconify = MagicMock()
    app.lower = MagicMock()
    app.lift = MagicMock()
    app.focus_force = MagicMock()
    app.winfo_viewable = MagicMock(return_value=viewable)
    app._preflight_cache = ("old", 0.0, MagicMock())
    app._running = False
    app.start_btn = MagicMock()
    app.stop_btn = MagicMock()
    app._set_status = MagicMock()
    app._worker = None
    app._automator = None
    app._start_config = {}
    app._log_queue = MagicMock()
    return app


class StartFlowHelperTests(unittest.TestCase):
    def test_enter_start_flow_withdraws_app(self) -> None:
        app = _make_login_app_stub()
        app._enter_start_flow()
        app.update_idletasks.assert_called_once()
        app.withdraw.assert_called_once()

    def test_exit_start_flow_normal_lifts_and_focuses(self) -> None:
        app = _make_login_app_stub()
        with patch.object(app, "_apply_start_window_stack") as stack:
            app._exit_start_flow()
        app.deiconify.assert_called_once()
        app.lift.assert_called_once()
        app.focus_force.assert_called_once()
        app.lower.assert_not_called()
        stack.assert_not_called()

    def test_exit_start_flow_behind_game_stacks_windows(self) -> None:
        app = _make_login_app_stub()
        with patch.object(app, "_apply_start_window_stack", return_value=True) as stack:
            app._exit_start_flow(behind_game=True)
        app.deiconify.assert_called_once()
        app.lower.assert_called_once()
        stack.assert_called_once_with(None)
        app.lift.assert_not_called()
        app.focus_force.assert_not_called()

    def test_messagebox_while_hidden_rewithdraws_after_dialog(self) -> None:
        app = _make_login_app_stub(viewable=False)
        dialog = MagicMock(return_value=True)
        result = app._messagebox_while_hidden(dialog, "title", "message")
        self.assertTrue(result)
        dialog.assert_called_once()
        self.assertEqual(dialog.call_args.kwargs["parent"], app)
        app.withdraw.assert_called_once()
        app.update_idletasks.assert_called()

    def test_messagebox_while_hidden_leaves_visible_app_alone(self) -> None:
        app = _make_login_app_stub(viewable=True)
        dialog = MagicMock(return_value=False)
        app._messagebox_while_hidden(dialog, "title", "message")
        app.withdraw.assert_not_called()

    @patch("src.input_handler.stack_windows_for_start_capture", return_value=True)
    @patch("src.input_handler.hwnd_from_tk", side_effect=lambda w: 100 if w is None else 200)
    def test_apply_start_window_stack_delegates_to_input_handler(
        self,
        _hwnd_from_tk,
        mock_stack,
    ) -> None:
        app = _make_login_app_stub()
        dialog = MagicMock()
        self.assertTrue(app._apply_start_window_stack(dialog))
        app.lower.assert_called_once()
        mock_stack.assert_called_once_with(
            game_title_contains="ARK: Survival Ascended",
            tool_hwnd=200,
            dialog_hwnd=200,
        )

    @patch("src.input_handler.stack_windows_for_start_capture", return_value=False)
    @patch("src.input_handler.hwnd_from_tk", return_value=100)
    def test_apply_start_window_stack_logs_when_game_missing(
        self,
        _hwnd_from_tk,
        _mock_stack,
    ) -> None:
        app = _make_login_app_stub()
        self.assertFalse(app._apply_start_window_stack(None))
        app._append_log.assert_called_once_with(
            "ARK ウィンドウが見つからないため、前面整列をスキップしました",
        )


class OnStartFlowTests(unittest.TestCase):
    def test_on_start_skips_when_already_running(self) -> None:
        app = _make_login_app_stub()
        app._running = True
        with patch.object(app, "_preflight_start") as preflight:
            app._on_start()
        preflight.assert_not_called()

    def test_on_start_skips_start_flow_when_preflight_start_fails(self) -> None:
        app = _make_login_app_stub()
        with patch.object(app, "_preflight_start", return_value=False):
            with patch.object(app, "_enter_start_flow") as enter_flow:
                app._on_start()
        enter_flow.assert_not_called()

    def test_on_start_cancel_dialog_restores_ui(self) -> None:
        app = _make_login_app_stub()
        dialog = MagicMock()
        dialog.confirmed = False
        with patch.object(app, "_preflight_start", return_value=True):
            with patch.object(app, "_enter_start_flow") as enter_flow:
                with patch("src.gui_app.StartReadyDialog", return_value=dialog):
                    with patch.object(app, "_apply_start_window_stack"):
                        with patch.object(app, "wait_window"):
                            with patch.object(app, "_exit_start_flow") as exit_flow:
                                app._on_start()
        enter_flow.assert_called_once()
        exit_flow.assert_called_once_with()

    def test_on_start_preflight_failure_restores_ui(self) -> None:
        app = _make_login_app_stub()
        dialog = MagicMock()
        dialog.confirmed = True
        with patch.object(app, "_preflight_start", return_value=True):
            with patch.object(app, "_enter_start_flow"):
                with patch("src.gui_app.StartReadyDialog", return_value=dialog):
                    with patch.object(app, "_apply_start_window_stack"):
                        with patch.object(app, "wait_window"):
                            with patch.object(app, "_confirm_environment_preflight", return_value=False):
                                with patch.object(app, "_exit_start_flow") as exit_flow:
                                    app._on_start()
        exit_flow.assert_called_once_with()
        self.assertFalse(app._running)

    def test_on_start_success_exits_behind_game_and_starts_worker(self) -> None:
        app = _make_login_app_stub()
        dialog = MagicMock()
        dialog.confirmed = True
        automator = MagicMock()
        capture_settings = MagicMock(mode="monitor")
        with patch.object(app, "_preflight_start", return_value=True):
            with patch.object(app, "_enter_start_flow"):
                with patch("src.gui_app.StartReadyDialog", return_value=dialog):
                    with patch.object(app, "_apply_start_window_stack"):
                        with patch.object(app, "wait_window"):
                            with patch.object(app, "_confirm_environment_preflight", return_value=True):
                                with patch.object(app, "_get_capture_settings", return_value=capture_settings):
                                    with patch.object(
                                        app,
                                        "_confirm_capture_mode_matches_setup",
                                        return_value=True,
                                    ):
                                        with patch.object(app, "_get_form_config", return_value={"retry": {}}):
                                            with patch(
                                                "src.gui_app.build_automator",
                                                return_value=automator,
                                            ):
                                                with patch.object(app, "_exit_start_flow") as exit_flow:
                                                    with patch(
                                                        "src.gui_app.threading.Thread",
                                                    ) as thread_cls:
                                                        worker = MagicMock()
                                                        thread_cls.return_value = worker
                                                        app._on_start()
        exit_flow.assert_called_once_with(behind_game=True)
        self.assertTrue(app._running)
        self.assertIs(app._automator, automator)
        app.start_btn.configure.assert_called_once_with(state="disabled")
        app.stop_btn.configure.assert_called_once_with(state="normal")
        worker.start.assert_called_once()

    def test_on_start_build_failure_restores_ui(self) -> None:
        app = _make_login_app_stub()
        dialog = MagicMock()
        dialog.confirmed = True
        capture_settings = MagicMock(mode="monitor")
        with patch.object(app, "_preflight_start", return_value=True):
            with patch.object(app, "_enter_start_flow"):
                with patch("src.gui_app.StartReadyDialog", return_value=dialog):
                    with patch.object(app, "_apply_start_window_stack"):
                        with patch.object(app, "wait_window"):
                            with patch.object(app, "_confirm_environment_preflight", return_value=True):
                                with patch.object(app, "_get_capture_settings", return_value=capture_settings):
                                    with patch.object(
                                        app,
                                        "_confirm_capture_mode_matches_setup",
                                        return_value=True,
                                    ):
                                        with patch.object(app, "_get_form_config", return_value={}):
                                            with patch(
                                                "src.gui_app.build_automator",
                                                side_effect=RuntimeError("bad config"),
                                            ):
                                                with patch.object(app, "_messagebox_while_hidden"):
                                                    with patch.object(app, "_exit_start_flow") as exit_flow:
                                                        app._on_start()
        exit_flow.assert_called_once_with()
        self.assertFalse(app._running)


class ConfirmEnvironmentPreflightTests(unittest.TestCase):
    @patch.object(LoginApp, "_run_preflight_with_progress")
    def test_confirm_environment_preflight_clears_cache_and_skips_cache(
        self,
        mock_run,
    ) -> None:
        app = _make_login_app_stub()
        report = MagicMock()
        report.can_start = True
        report.has_warnings = False
        mock_run.return_value = report
        with patch.object(app, "_get_form_config", return_value={"display": {}}):
            self.assertTrue(app._confirm_environment_preflight())
        self.assertIsNone(app._preflight_cache)
        mock_run.assert_called_once_with({"display": {}}, use_cache=False)


class RunWorkerNotificationTests(unittest.TestCase):
    @patch("src.gui_app.teardown_logging")
    @patch("src.gui_app.setup_logging")
    @patch("src.gui_app.notify_loop_finished")
    def test_run_worker_skips_notify_when_cancelled_during_countdown(
        self,
        mock_notify: MagicMock,
        _setup: MagicMock,
        _teardown: MagicMock,
    ) -> None:
        app = _make_login_app_stub()
        app._start_config = {"retry": {"start_countdown_seconds": 3}}
        app._running = True

        def stop_on_sleep(_seconds: float) -> None:
            app._running = False

        with patch("src.gui_app.time.sleep", side_effect=stop_on_sleep):
            app._run_worker()

        mock_notify.assert_not_called()
        app._log_queue.put.assert_called_with(("done", None))

    @patch("src.gui_app.teardown_logging")
    @patch("src.gui_app.setup_logging")
    @patch("src.notifier.send_discord_webhook_async")
    def test_run_worker_stopped_does_not_send_discord(
        self,
        mock_send: MagicMock,
        _setup: MagicMock,
        _teardown: MagicMock,
    ) -> None:
        app = _make_login_app_stub()
        app._start_config = {
            "retry": {"start_countdown_seconds": 0},
            "notifications": {
                "discord": {
                    "enabled": True,
                    "webhook_url": "https://discord.com/api/webhooks/1/abc",
                },
            },
        }
        app._running = True
        automator = MagicMock()
        automator.run.return_value = LoginState.STOPPED
        automator.stats = LoginStats()
        automator.vision = MagicMock()
        app._automator = automator

        app._run_worker()

        mock_send.assert_not_called()

    @patch("src.gui_app.teardown_logging")
    @patch("src.gui_app.setup_logging")
    @patch("src.notifier.send_discord_webhook_async")
    def test_run_worker_success_sends_discord(
        self,
        mock_send: MagicMock,
        _setup: MagicMock,
        _teardown: MagicMock,
    ) -> None:
        app = _make_login_app_stub()
        app._start_config = {
            "retry": {"start_countdown_seconds": 0},
            "notifications": {
                "discord": {
                    "enabled": True,
                    "webhook_url": "https://discord.com/api/webhooks/1/abc",
                },
            },
        }
        app._running = True
        automator = MagicMock()
        automator.run.return_value = LoginState.SUCCESS
        automator.stats = LoginStats(attempts=2)
        automator.vision = MagicMock()
        app._automator = automator

        app._run_worker()

        mock_send.assert_called_once()

    @patch("src.gui_app.teardown_logging")
    @patch("src.gui_app.setup_logging")
    @patch("src.notifier.send_discord_webhook_async")
    def test_run_worker_error_sends_discord(
        self,
        mock_send: MagicMock,
        _setup: MagicMock,
        _teardown: MagicMock,
    ) -> None:
        app = _make_login_app_stub()
        app._start_config = {
            "retry": {"start_countdown_seconds": 0},
            "notifications": {
                "discord": {
                    "enabled": True,
                    "webhook_url": "https://discord.com/api/webhooks/1/abc",
                },
            },
        }
        app._running = True
        automator = MagicMock()
        automator.run.side_effect = RuntimeError("boom")
        automator.stats = LoginStats()
        automator.vision = MagicMock()
        app._automator = automator

        app._run_worker()

        mock_send.assert_called_once()


if __name__ == "__main__":
    unittest.main()
