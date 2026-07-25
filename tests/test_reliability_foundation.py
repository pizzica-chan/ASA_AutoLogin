"""信頼性強化で追加した基盤動作の回帰テスト。"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import yaml

from src.app_service import build_vision, load_config, restore_config_backup, save_config
from src.button_templates import extract_and_save_button_crop, verify_button_crop
from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig


class AtomicConfigTests(unittest.TestCase):
    def test_failed_replace_preserves_previous_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            save_config({"retry": {"max_attempts": 1}}, path)
            original = path.read_text(encoding="utf-8")
            with patch("src.app_service.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    save_config({"retry": {"max_attempts": 2}}, path)
            self.assertEqual(path.read_text(encoding="utf-8"), original)
            self.assertEqual(load_config(path)["retry"]["max_attempts"], 1)

    def test_restore_config_backup_does_not_overwrite_bak(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_text("retry:\n  max_attempts: 9\n", encoding="utf-8")
            path.write_text("retry:\n  max_attempts: 1\n", encoding="utf-8")

            self.assertTrue(restore_config_backup(path))
            self.assertEqual(load_config(path)["retry"]["max_attempts"], 9)
            restored_bak = yaml.safe_load(backup.read_text(encoding="utf-8"))
            self.assertEqual(restored_bak["retry"]["max_attempts"], 9)

    def test_restore_config_backup_preserves_legacy_discord_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.yaml"
            backup = path.with_suffix(path.suffix + ".bak")
            backup.write_text(
                yaml.dump(
                    {
                        "notifications": {
                            "discord": {
                                "enabled": True,
                                "webhook_url": "https://discord.com/api/webhooks/1/abc",
                            },
                        },
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            path.write_text("retry:\n  max_attempts: 1\n", encoding="utf-8")

            self.assertTrue(restore_config_backup(path))
            discord = load_config(path)["notifications"]["discord"]
            self.assertFalse(discord["attach_screenshot"])
            self.assertEqual(discord["stuck_repeat_threshold"], 0)


class InterruptibleWaitTests(unittest.TestCase):
    def test_stop_interrupts_long_wait(self) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=MagicMock(),
        )
        automator._running = True
        result: list[bool] = []
        worker = threading.Thread(target=lambda: result.append(automator._sleep(10)))
        worker.start()
        time.sleep(0.02)
        automator.stop()
        worker.join(0.5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])

    def test_focus_failure_prevents_click(self) -> None:
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=RetryConfig(),
            ui=MagicMock(),
        )
        automator._running = True
        with patch.object(automator, "_focus_game", return_value=False):
            with patch("src.login_flow.input_handler.click") as click:
                self.assertFalse(automator._click_target("join_server_list", "JOIN"))
        click.assert_not_called()


class VisionParityTests(unittest.TestCase):
    def test_build_vision_applies_setup_metadata(self) -> None:
        config = {
            "display": {"monitor_index": 1, "capture_mode": "monitor"},
            "meta": {
                "setup_capture_width": 1920,
                "setup_capture_height": 1080,
                "setup_dpi": 120,
            },
        }
        vision = build_vision(config)
        self.assertEqual(vision.setup_capture_size, (1920, 1080))
        self.assertEqual(vision.setup_dpi, 120)

    def test_template_cache_reloads_changed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "template.png"
            cv2.imwrite(str(path), np.zeros((20, 20, 3), dtype=np.uint8))
            vision = build_vision({"display": {"capture_mode": "monitor"}})
            first = vision.load_template(path)
            cv2.imwrite(str(path), np.full((21, 20, 3), 255, dtype=np.uint8))
            second = vision.load_template(path)
            self.assertEqual(first.shape, (20, 20, 3))
            self.assertEqual(second.shape, (21, 20, 3))


class CapturedButtonTests(unittest.TestCase):
    def test_generated_button_passes_self_test(self) -> None:
        rng = np.random.default_rng(7)
        image = rng.integers(0, 256, (600, 1000, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "screen.png"
            output = Path(temp_dir) / "captured" / "join.png"
            cv2.imwrite(str(source), image)
            extract_and_save_button_crop(source, 800, 500, output)
            score = verify_button_crop(source, output)
        self.assertGreaterEqual(score, 0.90)


if __name__ == "__main__":
    unittest.main()
