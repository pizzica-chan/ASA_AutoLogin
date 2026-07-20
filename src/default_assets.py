"""同梱デフォルト画像（エラー画面の手動キャプチャ省略用）"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import app_root, bundle_root

DEFAULT_BUTTONS_DIR = bundle_root() / "assets" / "defaults" / "buttons"
DEFAULT_SCREENS_DIR = bundle_root() / "assets" / "defaults" / "screens"
SAMPLES_DIR = bundle_root() / "docs" / "setup_samples"

# サンプル画像上の代表座標（%）からボタン切り出し
BUTTON_SOURCES: dict[str, tuple[str, float, float]] = {
    "join_server_list": ("01_server_list.png", 92.0, 92.0),
    "join_mods": ("02_required_mods.png", 15.0, 85.0),
    "cancel_failed": ("03a_connection_failed.png", 55.0, 55.0),
    "back_empty_list": ("03a_connection_failed.png", 5.0, 92.0),
    "join_game": ("04_main_menu.png", 50.0, 52.0),
    "accept_network_failure": ("05_network_failure.png", 50.0, 60.0),
}

SCREEN_SOURCES: dict[str, str] = {
    "server_list": "01_server_list.png",
    "required_mods": "02_required_mods.png",
    "connection_failed": "03a_connection_failed.png",
    "main_menu": "04_main_menu.png",
    "network_failure": "05_network_failure.png",
}


def ensure_default_assets() -> None:
    """サンプル画像から同梱デフォルトを生成（未作成の場合のみ）"""
    from .button_templates import extract_and_save_button_crop

    DEFAULT_BUTTONS_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_SCREENS_DIR.mkdir(parents=True, exist_ok=True)

    for screen_name, sample_file in SCREEN_SOURCES.items():
        src = SAMPLES_DIR / sample_file
        dst = DEFAULT_SCREENS_DIR / f"{screen_name}.png"
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)

    for button_name, (sample_file, x_pct, y_pct) in BUTTON_SOURCES.items():
        dst = DEFAULT_BUTTONS_DIR / f"{button_name}.png"
        if dst.exists():
            continue
        src = SAMPLES_DIR / sample_file
        if not src.exists():
            continue
        import cv2

        image = cv2.imread(str(src), cv2.IMREAD_COLOR)
        if image is None:
            continue
        h, w = image.shape[:2]
        cx, cy = int(w * x_pct / 100), int(h * y_pct / 100)
        extract_and_save_button_crop(src, cx, cy, dst)


def resolve_screen_path(name: str, user_path: str | None) -> str | None:
    if user_path and Path(user_path).exists():
        return user_path
    default = DEFAULT_SCREENS_DIR / f"{name}.png"
    return str(default) if default.exists() else None


def resolve_button_path(name: str, user_path: str | None = None) -> str | None:
    """画像認識は同梱デフォルトのみ使用（セットアップ切り出しは使わない）"""
    paths = list_button_paths(name, user_path)
    return paths[0] if paths else None


def list_button_paths(name: str, user_path: str | None = None) -> list[str]:
    """同梱デフォルトのボタン画像（assets/defaults/buttons）のみ返す"""
    default = DEFAULT_BUTTONS_DIR / f"{name}.png"
    if default.exists():
        return [str(default)]
    return []
