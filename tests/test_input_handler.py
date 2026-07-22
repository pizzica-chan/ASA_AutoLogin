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


if __name__ == "__main__":
    unittest.main()
