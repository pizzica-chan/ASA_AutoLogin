"""default_assets のテンプレート解決テスト"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.default_assets import (
    is_fallback_screen_template,
    is_user_screen_template,
    resolve_screen_path,
    screen_template_source,
    setup_sample_path,
)


class ScreenTemplateSourceTests(unittest.TestCase):
    @patch("src.default_assets.app_root")
    def test_user_template_has_priority(self, mock_root) -> None:
        mock_root.return_value = Path("/app")
        user_file = Path("/app/templates/required_mods.png")

        def exists(self) -> bool:
            return Path(self) == user_file

        with patch.object(Path, "exists", exists):
            self.assertEqual(
                screen_template_source("required_mods", "templates/required_mods.png"),
                "user",
            )
            self.assertEqual(
                resolve_screen_path("required_mods", "templates/required_mods.png"),
                str(user_file),
            )
            self.assertTrue(
                is_user_screen_template("required_mods", "templates/required_mods.png")
            )

    @patch("src.default_assets.app_root")
    @patch("src.default_assets.FALLBACK_SCREENS_DIR", Path("/fallback"))
    def test_fallback_when_user_file_absent(self, mock_root) -> None:
        mock_root.return_value = Path("/app")
        fallback = Path("/fallback/required_mods.png")

        def exists(self) -> bool:
            return Path(self) == fallback

        with patch.object(Path, "exists", exists):
            self.assertEqual(
                screen_template_source("required_mods", "templates/required_mods.png"),
                "fallback",
            )
            self.assertEqual(
                resolve_screen_path("required_mods", "templates/required_mods.png"),
                str(fallback),
            )
            self.assertTrue(
                is_fallback_screen_template("required_mods", "templates/required_mods.png")
            )

    @patch("src.default_assets.app_root")
    @patch("src.default_assets.FALLBACK_SCREENS_DIR", Path("/fallback"))
    def test_missing_when_neither_exists(self, mock_root) -> None:
        mock_root.return_value = Path("/app")

        with patch.object(Path, "exists", return_value=False):
            self.assertEqual(
                screen_template_source("title_screen", "templates/title_screen.png"),
                "missing",
            )
            self.assertIsNone(
                resolve_screen_path("title_screen", "templates/title_screen.png"),
            )

    @patch("src.default_assets.SETUP_SAMPLES_DIR", Path("/samples"))
    def test_setup_sample_path_for_wizard_only(self) -> None:
        sample = Path("/samples/02_required_mods.png")

        def exists(self) -> bool:
            return Path(self) == sample

        with patch.object(Path, "exists", exists):
            self.assertEqual(setup_sample_path("02_required_mods.png"), sample)


if __name__ == "__main__":
    unittest.main()
