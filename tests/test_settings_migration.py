"""旧版からの設定引き継ぎのテスト"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from src.settings_migration import (
    format_migration_confirm_message,
    format_migration_help_text,
    import_from_legacy_exe,
    preview_legacy_import,
    resolve_legacy_root,
    summarize_migration_for_user,
)


class SettingsMigrationTests(unittest.TestCase):
    def _write_legacy_install(
        self,
        root: Path,
        *,
        config: dict | None = None,
    ) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        (root / "templates" / "buttons").mkdir(parents=True)
        if config is None:
            config = {
                "display": {"monitor_index": 2},
                "retry": {"max_attempts": 5},
                "templates": {"server_list": "templates/server_list.png"},
            }
        (root / "config.yaml").write_text(
            yaml.dump(config, allow_unicode=True),
            encoding="utf-8",
        )
        (root / "templates" / "server_list.png").write_bytes(b"png1")
        (root / "templates" / "buttons" / "join_server_list.png").write_bytes(b"png2")
        exe = root / "ASA_Login.exe"
        exe.write_bytes(b"MZ")
        return exe

    def test_resolve_legacy_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "legacy"
            exe = self._write_legacy_install(root)
            self.assertEqual(resolve_legacy_root(exe), root.resolve())

    def test_preview_lists_relative_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            exe = self._write_legacy_install(legacy)
            current = Path(tmp) / "current"
            current.mkdir()
            preview = preview_legacy_import(exe, destination_root=current)
            self.assertEqual(preview.source_root, legacy.resolve())
            self.assertIn("config.yaml", preview.files)
            self.assertIn("templates/server_list.png", preview.files)
            self.assertIn("templates/buttons/join_server_list.png", preview.files)

    def test_import_copies_files_and_normalizes_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            exe = self._write_legacy_install(legacy)
            current = Path(tmp) / "current"
            current.mkdir()
            (current / "config.yaml").write_text("retry:\n  max_attempts: 1\n", encoding="utf-8")

            result = import_from_legacy_exe(exe, destination_root=current)

            self.assertTrue((current / "config.yaml.bak").exists())
            backup = yaml.safe_load((current / "config.yaml.bak").read_text(encoding="utf-8"))
            self.assertEqual(backup["retry"]["max_attempts"], 1)
            self.assertTrue((current / "templates" / "server_list.png").exists())
            self.assertTrue((current / "templates" / "buttons" / "join_server_list.png").exists())
            self.assertEqual(len(result.copied), 3)
            self.assertTrue(result.config_normalized)

            loaded = yaml.safe_load((current / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(loaded["display"]["monitor_index"], 2)
            self.assertEqual(loaded["retry"]["max_attempts"], 5)

    def test_import_preserves_legacy_discord_defaults_when_keys_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            exe = self._write_legacy_install(
                legacy,
                config={
                    "display": {"monitor_index": 2},
                    "retry": {"max_attempts": 5},
                    "notifications": {
                        "discord": {
                            "enabled": True,
                            "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        },
                    },
                },
            )
            current = Path(tmp) / "current"
            current.mkdir()

            import_from_legacy_exe(exe, destination_root=current)

            loaded = yaml.safe_load((current / "config.yaml").read_text(encoding="utf-8"))
            discord = loaded["notifications"]["discord"]
            self.assertFalse(discord["attach_screenshot"])
            self.assertEqual(discord["stuck_repeat_threshold"], 0)

    def test_templates_only_import_does_not_rewrite_destination_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            legacy.mkdir(parents=True)
            (legacy / "templates").mkdir()
            (legacy / "templates" / "server_list.png").write_bytes(b"png1")
            exe = legacy / "ASA_Login.exe"
            exe.write_bytes(b"MZ")

            current = Path(tmp) / "current"
            current.mkdir()
            original = yaml.dump(
                {
                    "retry": {"max_attempts": 3},
                    "notifications": {
                        "discord": {
                            "enabled": True,
                            "webhook_url": "https://discord.com/api/webhooks/1/abc",
                        },
                    },
                },
                allow_unicode=True,
            )
            (current / "config.yaml").write_text(original, encoding="utf-8")

            result = import_from_legacy_exe(exe, destination_root=current)

            self.assertNotIn("config.yaml", result.copied)
            self.assertFalse(result.config_normalized)
            self.assertTrue((current / "templates" / "server_list.png").exists())
            after = yaml.safe_load((current / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(after["retry"]["max_attempts"], 3)
            self.assertNotIn("attach_screenshot", after["notifications"]["discord"])
            self.assertNotIn("stuck_repeat_threshold", after["notifications"]["discord"])

    def test_import_failure_restores_config_from_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            exe = self._write_legacy_install(legacy)
            current = Path(tmp) / "current"
            current.mkdir()
            (current / "config.yaml").write_text("retry:\n  max_attempts: 1\n", encoding="utf-8")

            with patch(
                "src.settings_migration.shutil.copy2",
                side_effect=[None, None, OSError("disk full")],
            ):
                with self.assertRaises(OSError):
                    import_from_legacy_exe(exe, destination_root=current)

            restored = yaml.safe_load((current / "config.yaml").read_text(encoding="utf-8"))
            self.assertEqual(restored["retry"]["max_attempts"], 1)

    def test_rejects_same_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exe = self._write_legacy_install(root)
            with self.assertRaises(ValueError):
                preview_legacy_import(exe, destination_root=root)

    def test_rejects_missing_exe(self) -> None:
        with self.assertRaises(FileNotFoundError):
            resolve_legacy_root("missing.exe")

    def test_format_migration_help_includes_user_items(self) -> None:
        help_text = format_migration_help_text()
        self.assertIn("モニター・キャプチャ範囲", help_text)
        self.assertIn("Discord 通知", help_text)
        self.assertIn("セットアップで保存した画面キャプチャ", help_text)
        self.assertIn("引き継がれないもの", help_text)

    def test_summarize_migration_for_user(self) -> None:
        summary = summarize_migration_for_user(
            [
                "config.yaml",
                "templates/server_list.png",
                "templates/buttons/join_server_list.png",
            ],
        )
        self.assertTrue(summary.has_settings)
        self.assertEqual(summary.screen_template_count, 1)
        self.assertEqual(summary.button_image_count, 1)

    def test_confirm_message_uses_user_facing_labels(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            exe = self._write_legacy_install(legacy)
            current = Path(tmp) / "current"
            current.mkdir()
            preview = preview_legacy_import(exe, destination_root=current)
            message = format_migration_confirm_message(preview)
            self.assertIn("【引き継がれる設定】", message)
            self.assertIn("画面キャプチャ", message)
            self.assertIn("ボタン画像", message)
            self.assertIn("config.yaml.bak", message)

    def test_confirm_message_skips_backup_note_without_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            legacy = Path(tmp) / "legacy"
            legacy.mkdir(parents=True)
            (legacy / "templates").mkdir()
            (legacy / "templates" / "server_list.png").write_bytes(b"png1")
            exe = legacy / "ASA_Login.exe"
            exe.write_bytes(b"MZ")
            current = Path(tmp) / "current"
            current.mkdir()
            preview = preview_legacy_import(exe, destination_root=current)
            message = format_migration_confirm_message(preview)
            self.assertNotIn("config.yaml.bak", message)
            self.assertIn("（旧版に config.yaml がありません）", message)

    def test_format_migration_summary(self) -> None:
        from src.settings_migration import MigrationResult, format_migration_summary

        result = MigrationResult(
            source_root=Path("C:/legacy"),
            destination_root=Path("C:/current"),
            copied=[
                "config.yaml",
                "templates/server_list.png",
                "templates/buttons/join_server_list.png",
            ],
            config_normalized=True,
        )
        summary = format_migration_summary(result)
        self.assertIn("引き継ぎが完了しました", summary)
        self.assertIn("画面キャプチャ", summary)
        self.assertIn("最新形式", summary)


if __name__ == "__main__":
    unittest.main()
