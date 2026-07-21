"""同梱デフォルト画像（エラー画面の手動キャプチャ省略用）"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import app_root, bundle_root

# 配布物に同梱するボタン画像（正本）。実行時は templates/buttons/ にコピーして使う
BUNDLED_BUTTONS_DIR = bundle_root() / "assets" / "defaults" / "buttons"
USER_BUTTONS_DIR = app_root() / "templates" / "buttons"
DEFAULT_SCREENS_DIR = bundle_root() / "assets" / "defaults" / "screens"
SAMPLES_DIR = bundle_root() / "docs" / "setup_samples"

# ボタンキー → 参照する PNG ファイル名（複数レイアウト対応）
BUTTON_TEMPLATE_FILES: dict[str, tuple[str, ...]] = {
    "join_game": ("join_game.png", "join_game_center.png"),
}

BUNDLED_BUTTON_NAMES = (
    "join_server_list",
    "join_mods",
    "cancel_failed",
    "back_empty_list",
    "join_game",
    "join_game_center",
    "accept_network_failure",
)


def seed_button_templates(dest_dir: Path | None = None, *, overwrite: tuple[str, ...] = ()) -> None:
    """同梱ボタン画像を dest_dir にコピーする（未作成のファイルのみ）"""
    target = dest_dir or USER_BUTTONS_DIR
    target.mkdir(parents=True, exist_ok=True)

    for button_name in BUNDLED_BUTTON_NAMES:
        dst = target / f"{button_name}.png"
        if dst.exists() and button_name not in overwrite:
            continue

        bundled = BUNDLED_BUTTONS_DIR / f"{button_name}.png"
        if bundled.exists():
            shutil.copy2(bundled, dst)


def ensure_default_assets() -> None:
    """初回起動時にユーザー側フォルダへデフォルト画像を用意する"""
    seed_button_templates(USER_BUTTONS_DIR)

    DEFAULT_SCREENS_DIR.mkdir(parents=True, exist_ok=True)
    for screen_name, sample_file in _SCREEN_SOURCES.items():
        src = SAMPLES_DIR / sample_file
        dst = DEFAULT_SCREENS_DIR / f"{screen_name}.png"
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)


_SCREEN_SOURCES: dict[str, str] = {
    "server_list": "01_server_list.png",
    "required_mods": "02_required_mods.png",
    "connection_failed": "03a_connection_failed.png",
    "main_menu": "04_main_menu.png",
    "network_failure": "05_network_failure.png",
}


def resolve_screen_path(name: str, user_path: str | None) -> str | None:
    if user_path and Path(user_path).exists():
        return user_path
    default = DEFAULT_SCREENS_DIR / f"{name}.png"
    return str(default) if default.exists() else None


def resolve_button_path(name: str, user_path: str | None = None) -> str | None:
    paths = list_button_paths(name, user_path)
    return paths[0] if paths else None


def list_button_paths(name: str, user_path: str | None = None) -> list[str]:
    """exe 外の templates/buttons/ を参照（ユーザーがファイル差し替え可能）"""
    if user_path and Path(user_path).exists():
        return [user_path]

    filenames = BUTTON_TEMPLATE_FILES.get(name, (f"{name}.png",))
    paths: list[str] = []
    for filename in filenames:
        user_file = USER_BUTTONS_DIR / filename
        if user_file.exists():
            paths.append(str(user_file))
    return paths
