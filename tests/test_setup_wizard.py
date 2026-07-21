"""セットアップウィザードのステップ選択・検証"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.setup_wizard import (
    SETUP_STEPS,
    SetupStep,
    _complete_setup,
    _steps_from_selection,
    _validate_server_list_ui,
)


class SetupStepSelectionTests(unittest.TestCase):
    def test_minimal_selection(self) -> None:
        steps = _steps_from_selection(["server_list"])
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0].name, "server_list")

    def test_custom_preserves_setup_order(self) -> None:
        steps = _steps_from_selection(["main_menu", "required_mods", "server_list"])
        self.assertEqual([s.name for s in steps], ["server_list", "required_mods", "main_menu"])

    def test_full_selection(self) -> None:
        steps = _steps_from_selection([s.name for s in SETUP_STEPS])
        self.assertEqual(len(steps), len(SETUP_STEPS))


class SetupValidationTests(unittest.TestCase):
    def test_server_list_requires_join_coordinate(self) -> None:
        steps = [SetupStep(
            name="server_list",
            title="① サーバー一覧",
            required=True,
            sample_image=None,
            prepare_lines=(),
            capture_hint="",
            click_key="join_server_list",
            click_hint="JOIN",
        )]
        parent = MagicMock()
        with patch("src.setup_wizard.resolve_button_path", return_value=None):
            with patch("src.setup_wizard.messagebox.showerror") as showerror:
                self.assertFalse(_validate_server_list_ui(steps, {}, parent))
                showerror.assert_called_once()

    def test_server_list_ok_with_ui_coordinate(self) -> None:
        steps = _steps_from_selection(["server_list"])
        parent = MagicMock()
        with patch("src.setup_wizard.resolve_button_path", return_value=None):
            self.assertTrue(
                _validate_server_list_ui(
                    steps,
                    {"join_server_list": {"x_percent": 50.0, "y_percent": 90.0}},
                    parent,
                )
            )

    def test_complete_setup_validates_server_list(self) -> None:
        root = MagicMock()
        completed = _steps_from_selection(["server_list"])
        with patch("src.setup_wizard._validate_server_list_ui", return_value=False):
            self.assertFalse(
                _complete_setup(
                    root,
                    owns_root=False,
                    ui={},
                    monitor_index=1,
                    wizard_capture=MagicMock(mode="window"),
                    base_config=None,
                    completed_steps=completed,
                    completed_titles=["① サーバー一覧"],
                    on_complete=None,
                )
            )


if __name__ == "__main__":
    unittest.main()
