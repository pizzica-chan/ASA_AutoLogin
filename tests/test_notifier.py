"""Discord 通知モジュールのテスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.app_service import normalize_config
from src.login_flow import LoginAutomator, LoginState, LoginStats, RetryConfig, TemplateConfig
from src.ui_positions import UiPositions
from src.notifier import (
    build_discord_payload,
    capture_screenshot_png_from_vision,
    is_discord_notification_ready,
    loop_finished_summary,
    notify_loop_finished,
    notify_stuck_phase_repeated,
    parse_discord_notification_config,
    parse_mention_user_ids,
    redact_notifications_for_log,
    send_discord_test,
    send_discord_webhook_async,
    validate_webhook_url,
)


class NotifierConfigTests(unittest.TestCase):
    def test_parse_empty_config(self) -> None:
        cfg = parse_discord_notification_config({})
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.webhook_url, "")
        self.assertTrue(cfg.attach_screenshot)
        self.assertEqual(cfg.stuck_repeat_threshold, 10)

    def test_parse_discord_settings(self) -> None:
        cfg = parse_discord_notification_config(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                    },
                },
            },
        )
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.webhook_url, "https://discord.com/api/webhooks/1/abc")
        self.assertTrue(is_discord_notification_ready(cfg))

    def test_parse_mention_user_ids(self) -> None:
        self.assertEqual(parse_mention_user_ids(""), ())
        self.assertEqual(parse_mention_user_ids("123, 456"), ("123", "456"))
        self.assertEqual(parse_mention_user_ids("<@789>"), ("789",))
        self.assertEqual(parse_mention_user_ids(["111", "<@222>"]), ("111", "222"))
        self.assertEqual(parse_mention_user_ids("123, 123, 456"), ("123", "456"))

    def test_build_discord_payload_with_mentions(self) -> None:
        payload = build_discord_payload("hello", mention_user_ids=("111", "222"))
        self.assertIn("<@111>", payload["content"])
        self.assertIn("<@222>", payload["content"])
        self.assertEqual(payload["allowed_mentions"]["users"], ["111", "222"])
        self.assertEqual(payload["allowed_mentions"]["parse"], [])

    def test_build_discord_payload_with_everyone(self) -> None:
        payload = build_discord_payload("hello", mention_everyone=True)
        self.assertIn("@everyone", payload["content"])
        self.assertEqual(payload["allowed_mentions"]["parse"], ["everyone"])

    def test_build_discord_payload_with_everyone_and_users(self) -> None:
        payload = build_discord_payload(
            "hello",
            mention_user_ids=("111",),
            mention_everyone=True,
        )
        self.assertIn("@everyone", payload["content"])
        self.assertIn("<@111>", payload["content"])
        self.assertEqual(payload["allowed_mentions"]["parse"], ["everyone"])
        self.assertEqual(payload["allowed_mentions"]["users"], ["111"])

    def test_build_discord_payload_without_mentions(self) -> None:
        payload = build_discord_payload("hello")
        self.assertEqual(payload, {"content": "hello"})

    def test_normalize_notifications(self) -> None:
        normalized = normalize_config(
            {
                "notifications": {
                    "discord": {
                        "enabled": 1,
                        "webhook_url": "  https://discord.com/api/webhooks/1/abc  ",
                    },
                },
            },
        )
        discord = normalized["notifications"]["discord"]
        self.assertTrue(discord["enabled"])
        self.assertEqual(discord["webhook_url"], "https://discord.com/api/webhooks/1/abc")

    def test_normalize_mention_user_ids(self) -> None:
        normalized = normalize_config(
            {
                "notifications": {
                    "discord": {
                        "mention_user_ids": "111, <@222>",
                    },
                },
            },
        )
        self.assertEqual(normalized["notifications"]["discord"]["mention_user_ids"], ["111", "222"])

    def test_normalize_discord_defaults(self) -> None:
        normalized = normalize_config({})
        discord = normalized["notifications"]["discord"]
        self.assertTrue(discord["attach_screenshot"])
        self.assertEqual(discord["stuck_repeat_threshold"], 10)

    def test_normalize_discord_preserves_explicit_off(self) -> None:
        normalized = normalize_config(
            {
                "notifications": {
                    "discord": {
                        "attach_screenshot": False,
                        "stuck_repeat_threshold": 0,
                    },
                },
            },
        )
        discord = normalized["notifications"]["discord"]
        self.assertFalse(discord["attach_screenshot"])
        self.assertEqual(discord["stuck_repeat_threshold"], 0)

    def test_normalize_invalid_stuck_threshold_disables_notification(self) -> None:
        normalized = normalize_config(
            {
                "notifications": {
                    "discord": {
                        "stuck_repeat_threshold": "bad",
                    },
                },
            },
        )
        self.assertEqual(
            normalized["notifications"]["discord"]["stuck_repeat_threshold"],
            0,
        )

    def test_normalize_legacy_discord_defaults(self) -> None:
        normalized = normalize_config(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                    },
                },
            },
            legacy_discord_defaults=True,
        )
        discord = normalized["notifications"]["discord"]
        self.assertFalse(discord["attach_screenshot"])
        self.assertEqual(discord["stuck_repeat_threshold"], 0)

    def test_load_default_config_discord_defaults(self) -> None:
        from src.app_service import load_default_config

        discord = load_default_config()["notifications"]["discord"]
        self.assertTrue(discord["attach_screenshot"])
        self.assertEqual(discord["stuck_repeat_threshold"], 10)

    def test_normalize_attach_screenshot(self) -> None:
        normalized = normalize_config(
            {"notifications": {"discord": {"attach_screenshot": 1}}},
        )
        self.assertTrue(normalized["notifications"]["discord"]["attach_screenshot"])

    def test_redact_webhook_for_log(self) -> None:
        redacted = redact_notifications_for_log(
            {
                "notifications": {
                    "discord": {
                        "webhook_url": "https://discord.com/api/webhooks/secret",
                    },
                },
            },
        )
        self.assertEqual(redacted["notifications"]["discord"]["webhook_url"], "***")


class NotifierMessageTests(unittest.TestCase):
    def test_success_summary(self) -> None:
        stats = LoginStats(attempts=5, failures=4)
        title, body = loop_finished_summary(LoginState.SUCCESS, stats=stats)
        self.assertIn("成功", title)
        self.assertIn("試行: 5回", body)

    def test_stopped_summary(self) -> None:
        title, _body = loop_finished_summary(LoginState.STOPPED)
        self.assertIn("停止", title)

    def test_error_summary(self) -> None:
        title, body = loop_finished_summary(None, error="window missing")
        self.assertIn("エラー", title)
        self.assertIn("window missing", body)


class NotifierSendTests(unittest.TestCase):
    def test_validate_webhook_url(self) -> None:
        self.assertIsNotNone(validate_webhook_url(""))
        self.assertIsNotNone(validate_webhook_url("https://example.com/hook"))
        self.assertIsNone(validate_webhook_url("https://discord.com/api/webhooks/1/abc"))
        self.assertIsNone(validate_webhook_url("https://discordapp.com/api/webhooks/1/abc"))

    def test_build_discord_payload_truncates_long_content(self) -> None:
        payload = build_discord_payload("x" * 3000)
        self.assertLessEqual(len(payload["content"]), 2000)
        self.assertTrue(payload["content"].endswith("…"))

    @patch("src.notifier._post_discord_webhook")
    def test_send_discord_test_success(self, mock_post: MagicMock) -> None:
        ok, message = send_discord_test("https://discord.com/api/webhooks/1/abc")
        self.assertTrue(ok)
        self.assertIn("テスト", message)
        mock_post.assert_called_once()

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_skips_when_disabled(self, mock_send: MagicMock) -> None:
        notify_loop_finished({"notifications": {"discord": {"enabled": False}}}, result=LoginState.SUCCESS)
        mock_send.assert_not_called()

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_skips_when_stopped(self, mock_send: MagicMock) -> None:
        notify_loop_finished(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                    },
                },
            },
            result=LoginState.STOPPED,
        )
        mock_send.assert_not_called()

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_sends_when_enabled(self, mock_send: MagicMock) -> None:
        notify_loop_finished(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "mention_user_ids": ["555"],
                    },
                },
            },
            result=LoginState.SUCCESS,
            stats=LoginStats(attempts=1),
        )
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["mention_user_ids"], ("555",))

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_loop_finished_passes_screenshot(self, mock_send: MagicMock) -> None:
        notify_loop_finished(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "attach_screenshot": True,
                    },
                },
            },
            result=LoginState.SUCCESS,
            screenshot_png=b"fakepng",
        )
        mock_send.assert_called_once()
        self.assertEqual(mock_send.call_args.kwargs["screenshot_png"], b"fakepng")
        self.assertIsNone(mock_send.call_args.kwargs["resolve_screenshot"])

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_loop_finished_defers_screenshot_capture(self, mock_send: MagicMock) -> None:
        notify_loop_finished(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "attach_screenshot": True,
                    },
                },
            },
            result=LoginState.SUCCESS,
            vision=MagicMock(),
        )
        mock_send.assert_called_once()
        self.assertIsNone(mock_send.call_args.kwargs["screenshot_png"])
        self.assertIsNotNone(mock_send.call_args.kwargs["resolve_screenshot"])

    @patch("src.notifier.urllib.request.urlopen")
    def test_post_discord_webhook_multipart(self, mock_urlopen: MagicMock) -> None:
        from src.notifier import _post_discord_webhook

        mock_urlopen.return_value.__enter__.return_value.read.return_value = b""
        _post_discord_webhook(
            "https://discord.com/api/webhooks/1/abc",
            {"content": "hello"},
            screenshot_png=b"\x89PNG",
        )
        request = mock_urlopen.call_args.args[0]
        self.assertIn(b"multipart/form-data", request.headers["Content-type"].encode())
        self.assertIn(b"payload_json", request.data)
        self.assertIn(b"\x89PNG", request.data)

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_still_sends_when_screenshot_missing(
        self,
        mock_send: MagicMock,
    ) -> None:
        notify_loop_finished(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "attach_screenshot": True,
                    },
                },
            },
            result=LoginState.SUCCESS,
            screenshot_png=None,
            vision=None,
        )
        mock_send.assert_called_once()
        self.assertIsNone(mock_send.call_args.kwargs["screenshot_png"])
        self.assertIsNotNone(mock_send.call_args.kwargs["resolve_screenshot"])

    @patch("src.notifier._post_discord_webhook")
    def test_async_worker_resolves_screenshot_in_background(self, mock_post: MagicMock) -> None:
        import threading

        def sync_start(thread_self: threading.Thread) -> None:
            thread_self._target(*thread_self._args, **thread_self._kwargs)

        resolve = MagicMock(return_value=b"png-bytes")
        with patch.object(threading.Thread, "start", sync_start):
            send_discord_webhook_async(
                "https://discord.com/api/webhooks/1/abc",
                title="title",
                description="body",
                resolve_screenshot=resolve,
            )
        resolve.assert_called_once()
        mock_post.assert_called_once()
        self.assertEqual(mock_post.call_args.kwargs["screenshot_png"], b"png-bytes")

    @patch("src.notifier._post_discord_webhook")
    def test_async_worker_sends_text_when_screenshot_resolve_returns_none(self, mock_post: MagicMock) -> None:
        import threading

        def sync_start(thread_self: threading.Thread) -> None:
            thread_self._target(*thread_self._args, **thread_self._kwargs)

        with patch.object(threading.Thread, "start", sync_start):
            send_discord_webhook_async(
                "https://discord.com/api/webhooks/1/abc",
                title="title",
                description="body",
                resolve_screenshot=lambda: None,
            )
        mock_post.assert_called_once()
        self.assertIsNone(mock_post.call_args.kwargs["screenshot_png"])


class ScreenshotCaptureTests(unittest.TestCase):
    def test_capture_skips_black_frame(self) -> None:
        vision = MagicMock()
        vision.capture_screen.return_value = MagicMock()
        vision.is_black_frame.return_value = True
        self.assertIsNone(capture_screenshot_png_from_vision(vision))

    @patch("PIL.Image.fromarray")
    @patch("cv2.cvtColor", return_value=MagicMock())
    @patch("numpy.asarray", return_value=MagicMock())
    def test_capture_returns_png_bytes(self, _asarray, _cvtcolor, mock_fromarray) -> None:
        vision = MagicMock()
        frame = MagicMock()
        vision.capture_screen.return_value = frame
        vision.is_black_frame.return_value = False

        saved = MagicMock(side_effect=lambda buf, **_: buf.write(b"PNGDATA"))
        mock_fromarray.return_value.save = saved

        result = capture_screenshot_png_from_vision(vision)
        self.assertEqual(result, b"PNGDATA")

    def test_capture_returns_none_on_error(self) -> None:
        vision = MagicMock()
        vision.capture_screen.side_effect = RuntimeError("capture failed")
        self.assertIsNone(capture_screenshot_png_from_vision(vision))


class StuckPhaseNotificationTests(unittest.TestCase):
    def test_normalize_stuck_repeat_threshold(self) -> None:
        normalized = normalize_config(
            {"notifications": {"discord": {"stuck_repeat_threshold": "7"}}},
        )
        self.assertEqual(normalized["notifications"]["discord"]["stuck_repeat_threshold"], 7)

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_stuck_when_threshold_met(self, mock_send: MagicMock) -> None:
        notify_stuck_phase_repeated(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 5,
                    },
                },
            },
            phase_key="step1_not_ready",
            repeat_count=5,
            stats=LoginStats(attempts=5, failures=5),
        )
        mock_send.assert_called_once()
        description = mock_send.call_args.kwargs["description"]
        self.assertIn("サーバー一覧", description)
        self.assertIn("5", description)

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_stuck_defers_screenshot_capture(self, mock_send: MagicMock) -> None:
        notify_stuck_phase_repeated(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 5,
                        "attach_screenshot": True,
                    },
                },
            },
            phase_key="step1_not_ready",
            repeat_count=5,
            vision=MagicMock(),
        )
        mock_send.assert_called_once()
        self.assertIsNone(mock_send.call_args.kwargs["screenshot_png"])
        self.assertIsNotNone(mock_send.call_args.kwargs["resolve_screenshot"])

    @patch("src.notifier.send_discord_webhook_async")
    def test_notify_stuck_skips_when_threshold_zero(self, mock_send: MagicMock) -> None:
        notify_stuck_phase_repeated(
            {
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 0,
                    },
                },
            },
            phase_key="step1_not_ready",
            repeat_count=10,
        )
        mock_send.assert_not_called()


class LoginAutomatorStuckTests(unittest.TestCase):
    @patch("src.notifier.notify_stuck_phase_repeated")
    def test_record_stuck_phase_notifies_at_threshold(self, mock_notify: MagicMock) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=UiPositions.from_dict({"join_server_list": {"x_percent": 90.0, "y_percent": 90.0}}),
            config={
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 3,
                    },
                },
            },
        )
        for _ in range(3):
            automator._record_stuck_phase("step1_not_ready")
        mock_notify.assert_called_once()
        automator._record_stuck_phase("step1_not_ready")
        mock_notify.assert_called_once()

    @patch("src.notifier.notify_stuck_phase_repeated")
    def test_reset_stuck_on_progress(self, mock_notify: MagicMock) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=UiPositions.from_dict({"join_server_list": {"x_percent": 90.0, "y_percent": 90.0}}),
            config={
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 2,
                    },
                },
            },
        )
        automator._record_stuck_phase("step1_not_ready")
        automator._reset_stuck_tracking()
        automator._record_stuck_phase("step1_not_ready")
        mock_notify.assert_not_called()

    @patch("src.notifier.notify_stuck_phase_repeated")
    def test_record_stuck_phase_skips_when_stop_requested(self, mock_notify: MagicMock) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=UiPositions.from_dict({"join_server_list": {"x_percent": 90.0, "y_percent": 90.0}}),
            config={
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 1,
                    },
                },
            },
        )
        automator.stop()
        automator._record_stuck_phase("step1_not_ready")
        mock_notify.assert_not_called()

    @patch("src.notifier.notify_stuck_phase_repeated")
    def test_handle_attempt_retry_resets_after_successful_recovery(self, mock_notify: MagicMock) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=UiPositions.from_dict({"join_server_list": {"x_percent": 90.0, "y_percent": 90.0}}),
            config={
                "notifications": {
                    "discord": {
                        "enabled": True,
                        "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        "stuck_repeat_threshold": 2,
                    },
                },
            },
        )
        automator._record_stuck_phase("step1_not_ready")
        automator._last_stuck_phase_key = None
        automator._handle_attempt_retry()
        automator._record_stuck_phase("step1_not_ready")
        mock_notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
