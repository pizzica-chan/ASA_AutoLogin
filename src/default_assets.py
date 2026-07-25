"""同梱デフォルト資産

フォルダ役割:
  docs/setup_samples/              … セットアップウィザードの参考イメージ（表示のみ）
  assets/defaults/fallback_screens/ … セットアップ未実施時の実行時フォールバック（画面認識）
  assets/defaults/buttons/         … ボタン画像の初回コピー元 → templates/buttons/
  templates/                         … ユーザーがセットアップで保存した正本（最優先）
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .paths import app_root, bundle_root

# ボタン画像（正本）→ 初回起動時に templates/buttons/ へコピー
BUNDLED_BUTTONS_DIR = bundle_root() / "assets" / "defaults" / "buttons"
USER_BUTTONS_DIR = app_root() / "templates" / "buttons"

# セットアップウィザードの参考イメージ（番号付きファイル名・認識には不使用）
SETUP_SAMPLES_DIR = bundle_root() / "docs" / "setup_samples"

# セットアップ未実施時の画面認識フォールバック（テンプレートキー名 = ファイル名）
FALLBACK_SCREENS_DIR = bundle_root() / "assets" / "defaults" / "fallback_screens"

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
    "login_success",
)

# フォールバックを同梱する画面テンプレート（templates/ 未保存時に参照）
FALLBACK_SCREEN_NAMES = (
    "server_list",
    "required_mods",
    "connection_failed",
    "main_menu",
    "network_failure",
)

TEMPLATE_SCREEN_KEYS = FALLBACK_SCREEN_NAMES + (
    "login_movie",
    "title_screen",
    "server_list_empty",
    "in_game",
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
    """初回起動時にユーザー側フォルダへ同梱ボタン画像を用意する"""
    seed_button_templates(USER_BUTTONS_DIR)


def setup_sample_path(filename: str) -> Path | None:
    """セットアップウィザード用の参考画像（実行時の画面認識には使わない）"""
    path = SETUP_SAMPLES_DIR / filename
    return path if path.exists() else None


def _user_template_path(user_path: str | None) -> Path | None:
    if not user_path:
        return None
    path = Path(user_path)
    if path.is_absolute():
        return path if path.exists() else None
    candidate = app_root() / path
    return candidate if candidate.exists() else None


def _fallback_screen_path(name: str) -> Path | None:
    path = FALLBACK_SCREENS_DIR / f"{name}.png"
    return path if path.exists() else None


def screen_template_source(name: str, user_path: str | None) -> str:
    """画面テンプレートの由来: user | fallback | missing"""
    if _user_template_path(user_path) is not None:
        return "user"
    if _fallback_screen_path(name) is not None:
        return "fallback"
    return "missing"


def is_user_screen_template(name: str, user_path: str | None) -> bool:
    return screen_template_source(name, user_path) == "user"


def is_fallback_screen_template(name: str, user_path: str | None) -> bool:
    return screen_template_source(name, user_path) == "fallback"


def resolve_screen_path(name: str, user_path: str | None) -> str | None:
    """実行時の画面テンプレート: templates/（ユーザー）→ fallback_screens/（同梱）"""
    user_file = _user_template_path(user_path)
    if user_file is not None:
        return str(user_file)
    fallback = _fallback_screen_path(name)
    return str(fallback) if fallback is not None else None


def prune_stale_template_paths(config: dict) -> int:
    """config の templates/ 参照のうち、実ファイルが無い標準パスを削除する"""
    templates = config.get("templates")
    if not isinstance(templates, dict):
        return 0

    removed = 0
    templates_dir = app_root() / "templates"
    for key in TEMPLATE_SCREEN_KEYS:
        rel_path = templates.get(key)
        if not isinstance(rel_path, str):
            continue
        expected = f"templates/{key}.png"
        if rel_path != expected:
            continue
        if not (templates_dir / f"{key}.png").exists():
            templates.pop(key, None)
            removed += 1
    return removed


def resolve_button_path(name: str, user_path: str | None = None) -> str | None:
    paths = list_button_paths(name, user_path)
    return paths[0] if paths else None


def list_button_paths(name: str, user_path: str | None = None) -> list[str]:
    """templates/buttons/ を参照（ユーザーがファイル差し替え可能）"""
    if user_path and Path(user_path).exists():
        return [user_path]

    filenames = BUTTON_TEMPLATE_FILES.get(name, (f"{name}.png",))
    paths: list[str] = []
    for filename in filenames:
        user_file = USER_BUTTONS_DIR / filename
        if user_file.exists():
            paths.append(str(user_file))
    return paths
