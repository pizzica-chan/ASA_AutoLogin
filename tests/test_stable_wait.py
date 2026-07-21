"""クリック前の安定待ち（_wait_for_stable）のテスト"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from src.login_flow import LoginAutomator, RetryConfig, TemplateConfig


class StableWaitTests(unittest.TestCase):
    def _make_automator(self, *, stable_polls: int = 2) -> LoginAutomator:
        retry = RetryConfig(poll_interval=0.01, screen_stable_polls=stable_polls)
        automator = LoginAutomator(
            vision=MagicMock(),
            templates=TemplateConfig(),
            retry=retry,
            ui=MagicMock(),
        )
        automator._running = True
        return automator

    @patch("src.login_flow.time.sleep")
    def test_wait_for_stable_requires_consecutive_hits(self, _sleep) -> None:
        automator = self._make_automator(stable_polls=2)
        calls = {"n": 0}

        def predicate() -> bool:
            calls["n"] += 1
            return calls["n"] >= 2

        self.assertTrue(automator._wait_for_stable(1.0, predicate))

    @patch("src.login_flow.time.sleep")
    def test_wait_for_stable_resets_on_miss(self, _sleep) -> None:
        automator = self._make_automator(stable_polls=2)
        sequence = [True, False, True, True]
        index = {"i": 0}

        def predicate() -> bool:
            value = sequence[index["i"]]
            index["i"] += 1
            return value

        self.assertTrue(automator._wait_for_stable(1.0, predicate))
        self.assertEqual(index["i"], 4)

    @patch("src.login_flow.time.sleep")
    def test_stable_polls_one_behaves_like_single_hit(self, _sleep) -> None:
        automator = self._make_automator(stable_polls=1)

        self.assertTrue(automator._wait_for_stable(1.0, lambda: True))


if __name__ == "__main__":
    unittest.main()
