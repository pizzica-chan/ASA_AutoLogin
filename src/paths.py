"""アプリのパス解決（開発環境 / PyInstaller 配布物）"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path:
    """同梱リソース（読み取り専用）のルート"""
    if is_frozen():
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def app_root() -> Path:
    """ユーザー設定・テンプレート・ログの保存先"""
    if is_frozen():
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def ensure_app_dirs() -> None:
    """配布物初回起動用のフォルダを用意"""
    for name in ("templates", "templates/buttons", "logs"):
        (app_root() / name).mkdir(parents=True, exist_ok=True)


def prepare_runtime() -> None:
    """配布 exe 起動時に作業ディレクトリとフォルダを整える"""
    ensure_app_dirs()
    if is_frozen():
        os.chdir(app_root())
