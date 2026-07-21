"""実行時設定の詳細ログ出力テスト"""

from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from src.app_logging import build_runtime_config_snapshot, log_runtime_config_detail


class ConfigLoggingTests(unittest.TestCase):
    def test_build_runtime_config_snapshot_contains_sections(self) -> None:
        config = {
            "display": {"monitor_index": 1, "capture_mode": "monitor"},
            "window": {"title_contains": "ARK", "bring_to_front": True},
            "retry": {"max_attempts": 0, "delay_seconds": 3.0},
            "matching": {"click_mode": "image", "button_threshold": 0.75},
            "templates": {"server_list": "templates/server_list.png"},
            "ui": {"join_server_list": {"x_percent": 92.0, "y_percent": 92.0}},
            "meta": {"setup_capture_version": 2},
        }

        with patch("src.capture.resolve_capture_region") as mock_region:
            mock_region.return_value = type(
                "R",
                (),
                {"mode": "monitor", "left": 0, "top": 0, "width": 1920, "height": 1080},
            )()
            snapshot = build_runtime_config_snapshot(
                config,
                window_title="ARK",
                bring_to_front=True,
            )

        self.assertEqual(snapshot["capture_mode"], "monitor")
        self.assertIn("templates_resolved", snapshot)
        self.assertIn("buttons_resolved", snapshot)
        self.assertEqual(snapshot["ui_percent"]["join_server_list"]["x_percent"], 92.0)
        self.assertEqual(snapshot["meta"]["setup_capture_version"], 2)

    def test_log_runtime_config_detail_emits_config_block(self) -> None:
        records: list[str] = []

        class CollectHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record.getMessage())

        from src.app_logging import detail_log

        handler = CollectHandler()
        detail_log.setLevel(logging.INFO)
        detail_log.addHandler(handler)
        try:
            log_runtime_config_detail(
                {"retry": {"max_attempts": 1}, "matching": {"click_mode": "image"}},
                runtime={"capture_mode": "window"},
            )
        finally:
            detail_log.removeHandler(handler)

        joined = "\n".join(records)
        self.assertIn("実行時設定（config.yaml 相当）", joined)
        self.assertIn("max_attempts: 1", joined)
        self.assertIn("解決済みランタイム情報", joined)
        self.assertIn("capture_mode: window", joined)


if __name__ == "__main__":
    unittest.main()
