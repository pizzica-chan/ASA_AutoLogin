"""templates/ 幽霊パスの整理"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src.default_assets import prune_stale_template_paths


class TemplatePruneTests(unittest.TestCase):
    @patch("src.default_assets.app_root")
    def test_removes_missing_standard_paths(self, mock_root) -> None:
        mock_root.return_value = Path("/app")
        config = {
            "templates": {
                "server_list": "templates/server_list.png",
                "required_mods": "templates/required_mods.png",
            }
        }

        def exists(self) -> bool:
            return str(self).endswith("server_list.png")

        with patch.object(Path, "exists", exists):
            removed = prune_stale_template_paths(config)

        self.assertEqual(removed, 1)
        self.assertIn("server_list", config["templates"])
        self.assertNotIn("required_mods", config["templates"])

    @patch("src.default_assets.app_root")
    def test_keeps_non_standard_paths(self, mock_root) -> None:
        mock_root.return_value = Path("/app")
        config = {"templates": {"server_list": "custom/server_list.png"}}

        with patch.object(Path, "exists", return_value=False):
            removed = prune_stale_template_paths(config)

        self.assertEqual(removed, 0)
        self.assertEqual(config["templates"]["server_list"], "custom/server_list.png")


if __name__ == "__main__":
    unittest.main()
