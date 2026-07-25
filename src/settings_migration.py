"""旧版 ASA_Login から設定・テンプレート画像を引き継ぐ"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .paths import app_root

# exe と同じフォルダを基準にコピーする相対パス
MIGRATION_RELATIVE_FILES: tuple[str, ...] = (
    "config.yaml",
)

MIGRATION_RELATIVE_DIRS: tuple[str, ...] = (
    "templates",
)


@dataclass(frozen=True)
class MigrationUserSummary:
    has_settings: bool
    screen_template_count: int
    button_image_count: int
    total_files: int


# GUI・確認ダイアログ用（ユーザー向けの説明）
MIGRATION_SETTINGS_ITEMS: tuple[str, ...] = (
    "モニター・キャプチャ範囲（メインタブ）",
    "リトライ回数・各場面の待ち時間（メイン・待ち時間タブ）",
    "画像認識の一致度・② MODS 設定（画像認識タブ）",
    "クリック方式・クリック座標（クリック座標タブ）",
    "Discord 通知（Discord 通知タブ）",
    "ARK ウィンドウ設定（前面に出す など）",
)

MIGRATION_IMAGE_ITEMS: tuple[str, ...] = (
    "セットアップで保存した画面キャプチャ（① サーバー一覧 など）",
    "ボタン認識用の画像（JOIN / BACK など・差し替え済み PNG）",
)

MIGRATION_NOT_COPIED_ITEMS: tuple[str, ...] = (
    "ログファイル（logs/）",
    "旧版の exe 本体",
)


@dataclass(frozen=True)
class MigrationPreview:
    source_root: Path
    destination_root: Path
    files: tuple[str, ...]
    missing: tuple[str, ...] = ()


@dataclass
class MigrationResult:
    source_root: Path
    destination_root: Path
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    config_normalized: bool = False


def resolve_legacy_root(legacy_exe: str | Path) -> Path:
    """旧版 exe のパスから引き継ぎ元フォルダ（exe の親ディレクトリ）を返す。"""
    path = Path(legacy_exe).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"指定した exe が見つかりません: {path}")
    if not path.is_file():
        raise ValueError(f"ファイルではありません: {path}")
    if path.suffix.lower() != ".exe":
        raise ValueError("ASA_Login.exe など .exe ファイルを指定してください")
    return path.resolve().parent


def _normalize_rel_path(rel: str) -> str:
    return rel.replace("\\", "/")


def collect_migration_files(source_root: Path) -> tuple[list[str], list[str]]:
    """引き継ぎ可能な相対パス一覧と、見つからなかった既定ファイルを返す。"""
    source_root = source_root.resolve()
    found: list[str] = []
    missing: list[str] = []

    for rel in MIGRATION_RELATIVE_FILES:
        if (source_root / rel).is_file():
            found.append(_normalize_rel_path(rel))
        else:
            missing.append(_normalize_rel_path(rel))

    for rel_dir in MIGRATION_RELATIVE_DIRS:
        base = source_root / rel_dir
        if not base.is_dir():
            missing.append(_normalize_rel_path(rel_dir) + "/")
            continue
        for src_file in sorted(base.rglob("*")):
            if src_file.is_file():
                rel = _normalize_rel_path(str(src_file.relative_to(source_root)))
                found.append(rel)

    return found, missing


def preview_legacy_import(
    legacy_exe: str | Path,
    *,
    destination_root: Path | None = None,
) -> MigrationPreview:
    source_root = resolve_legacy_root(legacy_exe)
    dest_root = (destination_root or app_root()).resolve()
    if source_root == dest_root:
        raise ValueError("引き継ぎ元と現在のフォルダが同じです")

    files, missing = collect_migration_files(source_root)
    if not files:
        raise ValueError("引き継ぎ可能なファイルが旧版フォルダに見つかりません")

    return MigrationPreview(
        source_root=source_root,
        destination_root=dest_root,
        files=tuple(files),
        missing=tuple(missing),
    )


def _backup_destination_config(dest_root: Path) -> None:
    config_path = dest_root / "config.yaml"
    backup_path = dest_root / "config.yaml.bak"
    if config_path.is_file():
        shutil.copy2(config_path, backup_path)


def _restore_config_from_backup(dest_root: Path) -> None:
    """引き継ぎ失敗時に config.yaml.bak を config.yaml へ戻す。"""
    config_path = dest_root / "config.yaml"
    backup_path = dest_root / "config.yaml.bak"
    if backup_path.is_file():
        shutil.copy2(backup_path, config_path)


def _migration_apply_order(files: tuple[str, ...] | list[str]) -> list[str]:
    """templates を先に、config.yaml を最後に適用する。"""
    return sorted(files, key=lambda rel: (rel == "config.yaml", rel))


def import_from_legacy_exe(
    legacy_exe: str | Path,
    *,
    destination_root: Path | None = None,
    backup_current: bool = True,
) -> MigrationResult:
    """旧版 exe 横の設定・templates を現在の app_root へコピーする。"""
    preview = preview_legacy_import(legacy_exe, destination_root=destination_root)
    result = MigrationResult(
        source_root=preview.source_root,
        destination_root=preview.destination_root,
    )

    backed_up_config = False
    if backup_current and "config.yaml" in preview.files:
        _backup_destination_config(preview.destination_root)
        backed_up_config = True

    staging_root = Path(tempfile.mkdtemp(prefix="asa_login_migration_"))
    try:
        staged: list[str] = []
        for rel in preview.files:
            src = preview.source_root / rel
            if not src.is_file():
                result.skipped.append(rel)
                continue
            dest_stage = staging_root / rel
            dest_stage.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest_stage)
            staged.append(rel)

        config_staged = "config.yaml" in staged
        if config_staged:
            from .app_service import save_config

            config_path = staging_root / "config.yaml"
            with open(config_path, encoding="utf-8") as f:
                raw_config = yaml.safe_load(f) or {}
            save_config(
                raw_config,
                config_path,
                backup_before_write=False,
                legacy_discord_defaults=True,
            )

        for rel in _migration_apply_order(staged):
            src = staging_root / rel
            dest = preview.destination_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            result.copied.append(rel)

        if config_staged:
            result.config_normalized = True
    except Exception:
        if backed_up_config:
            _restore_config_from_backup(preview.destination_root)
        raise
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return result


def summarize_migration_for_user(files: tuple[str, ...] | list[str]) -> MigrationUserSummary:
    screen_count = 0
    button_count = 0
    has_settings = False
    for rel in files:
        if rel == "config.yaml":
            has_settings = True
            continue
        if not rel.startswith("templates/"):
            continue
        if rel.startswith("templates/buttons/"):
            button_count += 1
        elif rel.endswith(".png"):
            screen_count += 1
    return MigrationUserSummary(
        has_settings=has_settings,
        screen_template_count=screen_count,
        button_image_count=button_count,
        total_files=len(files),
    )


def _bullet_lines(items: tuple[str, ...] | list[str]) -> str:
    return "\n".join(f"  • {item}" for item in items)


def format_migration_help_text() -> str:
    """メインタブに表示する引き継ぎ内容の説明。"""
    sections = [
        "旧版の ASA_Login.exe を指定すると、exe と同じフォルダから次を引き継ぎます。",
        "",
        "【引き継がれる設定】",
        _bullet_lines(MIGRATION_SETTINGS_ITEMS),
        "",
        "【引き継がれる画像】",
        _bullet_lines(MIGRATION_IMAGE_ITEMS),
        "",
        "【引き継がれないもの】",
        _bullet_lines(MIGRATION_NOT_COPIED_ITEMS),
    ]
    return "\n".join(sections)


def format_migration_confirm_message(preview: MigrationPreview) -> str:
    """確認ダイアログ用のユーザー向けメッセージ。"""
    summary = summarize_migration_for_user(preview.files)
    lines = [
        "次の内容を現在のフォルダへコピーします。",
        "",
        f"引き継ぎ元:\n  {preview.source_root}",
        f"コピー先:\n  {preview.destination_root}",
        "",
        "【引き継がれる設定】",
    ]
    if summary.has_settings:
        lines.append(_bullet_lines(MIGRATION_SETTINGS_ITEMS))
    else:
        lines.append("  • （旧版に config.yaml がありません）")

    lines.extend(["", "【引き継がれる画像】"])
    image_lines: list[str] = []
    if summary.screen_template_count:
        image_lines.append(f"画面キャプチャ … {summary.screen_template_count} 枚")
    if summary.button_image_count:
        image_lines.append(f"ボタン画像 … {summary.button_image_count} 枚")
    if image_lines:
        lines.append(_bullet_lines(image_lines))
    else:
        lines.append("  • （旧版に templates/ がありません）")

    lines.extend(
        [
            "",
            *(
                ["現在の設定は config.yaml.bak に退避されます。"]
                if summary.has_settings
                else []
            ),
            "続行しますか？",
        ]
    )
    return "\n".join(lines)


def format_migration_summary(result: MigrationResult) -> str:
    """完了ダイアログ用のユーザー向けメッセージ。"""
    summary = summarize_migration_for_user(result.copied)
    lines = [
        "引き継ぎが完了しました。",
        "",
        f"引き継ぎ元: {result.source_root}",
        "",
        "【反映された内容】",
    ]
    if summary.has_settings:
        lines.append("  • 各タブの設定（モニター、待ち時間、画像認識、座標、Discord 通知 など）")
    if summary.screen_template_count:
        lines.append(f"  • 画面キャプチャ … {summary.screen_template_count} 枚")
    if summary.button_image_count:
        lines.append(f"  • ボタン画像 … {summary.button_image_count} 枚")
    if result.config_normalized:
        lines.append("  • 設定ファイルを最新形式に整えました")
        lines.append("  • 旧版に無かった Discord オプション（スクショ・停滞通知）は OFF のまま")
    lines.append("")
    lines.append("GUI に反映済みです。必要なら「開始」前に内容を確認してください。")
    if result.skipped:
        lines.append(f"\n（スキップ: {len(result.skipped)} 件）")
    return "\n".join(lines)


def format_migration_summary_detail(result: MigrationResult) -> str:
    """詳細ログ用（ファイルパス一覧）。"""
    lines = [
        f"引き継ぎ元: {result.source_root}",
        f"コピー先: {result.destination_root}",
        f"コピー: {len(result.copied)} 件",
    ]
    for rel in result.copied:
        lines.append(f"  - {rel}")
    if result.config_normalized:
        lines.append("config.yaml を正規化しました")
    if result.skipped:
        lines.append(f"スキップ: {len(result.skipped)} 件")
    return "\n".join(lines)
