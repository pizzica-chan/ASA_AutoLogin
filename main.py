"""ASA_Login メインエントリポイント"""

from __future__ import annotations

import argparse
import signal
import sys
import time

from src.app_logging import setup_logging
from src.app_service import STATE_LABELS, build_automator, load_config
from src.gui_app import run_gui
from src.login_flow import LoginState
from src.setup_wizard import run_wizard_gui


def on_state_change(state: LoginState, stats) -> None:
    msg = STATE_LABELS.get(state, str(state))
    print(f"[{msg}] 試行: {stats.attempts}回, 失敗: {stats.failures}回, 経過: {stats.elapsed_seconds:.0f}秒")


def run_login(config: dict) -> int:
    automator = build_automator(config, on_state_change=on_state_change)

    def handle_interrupt(_sig, _frame):
        print("\n停止シグナルを受信しました...")
        automator.stop()

    signal.signal(signal.SIGINT, handle_interrupt)

    print("=" * 50)
    print("  ASA_Login - ARK: Survival Ascended 自動ログイン")
    print("=" * 50)
    print()
    print("対象サーバー選択済みのサーバー一覧画面を表示した状態で開始してください。")
    print("停止するには Ctrl+C を押してください。")
    print()

    for i in range(max(0, int(config.get("retry", {}).get("start_countdown_seconds", 3))), 0, -1):
        print(f"  {i}秒後に開始...")
        time.sleep(1)

    result = automator.run()

    if result == LoginState.SUCCESS:
        print("\nログインに成功しました！")
        return 0
    if result == LoginState.FAILED:
        print("\nログインに失敗しました（リトライ上限到達）。")
        return 1
    print("\n自動ログインを停止しました。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="ARK: Survival Ascended ログイン自動化ツール",
    )
    parser.add_argument(
        "--config", "-c",
        default="config.yaml",
        help="設定ファイルのパス (デフォルト: config.yaml)",
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="セットアップウィザードを実行",
    )
    parser.add_argument(
        "--gui", "-g",
        action="store_true",
        help="GUIモードで起動",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="CLIモードで起動（デフォルトはGUI）",
    )
    args = parser.parse_args()

    if args.setup:
        run_wizard_gui()
        return

    if args.gui or not args.cli:
        run_gui()
        return

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        print(exc)
        print("以下の方法でセットアップを実行してください:")
        print("  python gui.py  → 「セットアップ」ボタン")
        sys.exit(1)

    setup_logging(config)
    sys.exit(run_login(config))


if __name__ == "__main__":
    main()
