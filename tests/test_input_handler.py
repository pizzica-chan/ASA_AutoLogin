"""input_handler のクリック順序・インジケータ連携テスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src import input_handler


class InputHandlerClickTests(unittest.TestCase):
    @patch("src.input_handler.show_click_indicator")
    @patch("src.input_handler.pydirectinput.click")
    @patch("src.input_handler.pydirectinput.moveTo")
    @patch("src.input_handler.human_delay")
    @patch("src.input_handler.random.randint", side_effect=[0, 0])
    def test_click_runs_before_indicator(
        self,
        _randint: MagicMock,
        _delay: MagicMock,
        mock_move: MagicMock,
        mock_click: MagicMock,
        mock_indicator: MagicMock,
    ) -> None:
        call_order: list[str] = []
        mock_move.side_effect = lambda *_args, **_kwargs: call_order.append("move")
        mock_click.side_effect = lambda *_args, **_kwargs: call_order.append("click")
        mock_indicator.side_effect = lambda *_args, **_kwargs: call_order.append("indicator")

        input_handler.click(100, 200)

        self.assertEqual(call_order, ["move", "click", "indicator"])
        mock_indicator.assert_called_once_with(100, 200)

    @patch("src.input_handler.configure_click_indicator")
    def test_configure_click_indicator_delegates(self, mock_configure: MagicMock) -> None:
        input_handler.configure_click_indicator(True)
        mock_configure.assert_called_once_with(True)


class WindowStackingTests(unittest.TestCase):
    @patch("src.input_handler._raise_dialog_above_game")
    @patch("src.input_handler._raise_game_window")
    @patch("src.input_handler.send_window_to_back")
    @patch("src.input_handler.select_window")
    def test_stack_windows_for_start_capture_orders_tool_game_dialog(
        self,
        mock_select,
        mock_send_back,
        mock_raise_game,
        mock_raise_dialog,
    ) -> None:
        mock_select.return_value = input_handler.WindowSelection(
            hwnd=200,
            title="ARK",
            process_id=1,
            client_area=1000,
            minimized=False,
            candidate_count=1,
        )
        self.assertTrue(
            input_handler.stack_windows_for_start_capture(
                game_title_contains="ARK",
                tool_hwnd=100,
                dialog_hwnd=300,
            ),
        )
        mock_send_back.assert_called_once_with(100)
        mock_raise_game.assert_called_once_with(200)
        mock_raise_dialog.assert_called_once_with(300)

    @patch("src.input_handler._raise_dialog_above_game")
    @patch("src.input_handler._raise_game_window")
    @patch("src.input_handler.bring_window_to_front", return_value=True)
    @patch("src.input_handler.select_window")
    @patch("src.input_handler.send_window_to_back")
    def test_prepare_with_dialog_reraises_dialog_without_long_bring(
        self,
        mock_send_back,
        mock_select,
        mock_bring,
        mock_raise_game,
        mock_raise_dialog,
    ) -> None:
        mock_select.return_value = input_handler.WindowSelection(
            hwnd=200,
            title="ARK",
            process_id=1,
            client_area=1000,
            minimized=False,
            candidate_count=1,
        )
        self.assertTrue(
            input_handler.prepare_game_visible_for_capture(
                game_title_contains="ARK",
                tool_hwnd=100,
                dialog_hwnd=300,
            ),
        )
        mock_send_back.assert_called_once_with(100)
        mock_raise_game.assert_called_once_with(200)
        mock_bring.assert_not_called()
        mock_raise_dialog.assert_called_once_with(300)

    @patch("src.input_handler.bring_window_to_front", return_value=True)
    @patch("src.input_handler.send_window_to_back")
    def test_prepare_game_visible_for_capture_sends_tool_back(
        self,
        mock_send_back,
        mock_bring,
    ) -> None:
        self.assertTrue(
            input_handler.prepare_game_visible_for_capture(
                game_title_contains="ARK",
                tool_hwnd=100,
            ),
        )
        mock_send_back.assert_called_once_with(100)
        mock_bring.assert_called_once_with("ARK")

    @patch("src.input_handler._raise_game_window")
    @patch("src.input_handler.select_window")
    @patch("src.input_handler.send_window_to_back")
    def test_prepare_without_bring_to_front_still_raises_game(
        self,
        mock_send_back,
        mock_select,
        mock_raise_game,
    ) -> None:
        mock_select.return_value = input_handler.WindowSelection(
            hwnd=200,
            title="ARK",
            process_id=1,
            client_area=1000,
            minimized=False,
            candidate_count=1,
        )
        self.assertTrue(
            input_handler.prepare_game_visible_for_capture(
                game_title_contains="ARK",
                tool_hwnd=100,
                bring_game_to_front=False,
            ),
        )
        mock_send_back.assert_called_once_with(100)
        mock_raise_game.assert_called_once_with(200)


if __name__ == "__main__":
    unittest.main()
