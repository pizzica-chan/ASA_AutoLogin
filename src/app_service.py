"""設定の読み書きと LoginAutomator の構築"""

from __future__ import annotations

import copy
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import yaml

from .paths import app_root, bundle_root, ensure_app_dirs
from .button_templates import ButtonConfig
from .capture import CaptureSettings, DEFAULT_CAPTURE_MODE
from .default_assets import ensure_default_assets
from .login_flow import LoginAutomator, LoginState, RetryConfig, TemplateConfig
from .notifier import normalize_discord_section, parse_mention_user_ids
from .ui_positions import UiPositions
from .vision import Vision

CONFIG_PATH = app_root() / "config.yaml"
EXAMPLE_CONFIG_PATH = app_root() / "config.example.yaml"
BUNDLED_EXAMPLE_CONFIG_PATH = bundle_root() / "config.example.yaml"
CONFIG_SCHEMA_VERSION = 1
logger = logging.getLogger(__name__)

CLICK_MODE_COORDINATES_ONLY = "coordinates_only"


@dataclass(frozen=True)
class UiClickField:
    """GUI 用クリック座標フィールド"""

    key: str
    label: str
    default_x: float
    default_y: float
    required: bool = True


UI_CLICK_FIELDS: tuple[UiClickField, ...] = (
    UiClickField("join_server_list", "① サーバー一覧 JOIN", 92.0, 92.0),
    UiClickField("join_mods", "② MODS JOIN", 42.0, 92.0, required=False),
    UiClickField("back_empty_list", "④ BACK", 5.0, 92.0),
    UiClickField("join_game", "⑤ JOIN GAME", 29.0, 91.0),
)

# Enter キー確定へ移行したため ui 座標は不要（読み込み時に除去）
OBSOLETE_UI_KEYS = ("cancel_failed", "accept_network_failure")

STATE_LABELS = {
    LoginState.IDLE: "待機中",
    LoginState.JOINING_SERVER: "サーバー一覧で JOIN 中",
    LoginState.JOINING_MODS: "MODS 画面で JOIN 中",
    LoginState.WAITING_LOGIN: "ログイン処理を待機中",
    LoginState.HANDLING_FAILURE: "接続失敗を処理中",
    LoginState.HANDLING_NETWORK_FAILURE: "ネットワーク失敗を処理中",
    LoginState.RECOVERING: "メニューへ戻る処理中",
    LoginState.SUCCESS: "ログイン成功",
    LoginState.FAILED: "ログイン失敗",
    LoginState.STOPPED: "停止",
}


@dataclass(frozen=True)
class SettingField:
    """GUI 用の数値設定メタデータ"""

    key: str
    label: str
    help: str
    default: float
    vmin: float
    vmax: float
    increment: float
    group: str
    value_type: Literal["float", "int"] = "float"


# GUI / config.yaml の retry キー
RETRY_TIMING_FIELDS: tuple[SettingField, ...] = (
    SettingField(
        "start_countdown_seconds",
        "開始までの待ち",
        "「開始」押下後、実際の操作を始めるまでの秒数",
        3, 0, 60, 1, "全体", "int",
    ),
    SettingField(
        "poll_interval",
        "画面チェック間隔",
        "ボタンや画面の状態を何秒ごとに確認するか（短いほど反応は早い）",
        0.5, 0.1, 5.0, 0.1, "全体",
    ),
    SettingField(
        "screen_stable_polls",
        "クリック前の安定確認回数",
        "クリック前に同じ画面/ボタン判定を連続何回満たすまで待つか（2推奨・1で従来並み）",
        2, 1, 5, 1, "全体", "int",
    ),
    SettingField(
        "transition_settle",
        "クリック前の待ち",
        "ボタンを検出してから実際にクリックするまでの安定待ち",
        0.4, 0.0, 5.0, 0.1, "全体",
    ),
    SettingField(
        "after_click_delay",
        "クリック後の待ち",
        "クリック後、画面が切り替わり始めるまでの待ち",
        2.0, 0.0, 30.0, 0.5, "全体",
    ),
    SettingField(
        "transition_timeout",
        "次の画面・ボタンの出現待ち（上限）",
        "JOIN や BACK 後、次に押すボタンや画面が出るまでの最大秒数",
        20.0, 1.0, 120.0, 1.0, "①② サーバー一覧・MODS",
    ),
    SettingField(
        "mods_wait_seconds",
        "② MODS 画面の確認時間",
        "① JOIN 後、この秒数だけ MODS 画面の有無を確認する（なければ③へ進む）",
        8.0, 0.0, 60.0, 1.0, "①② サーバー一覧・MODS",
    ),
    SettingField(
        "result_timeout",
        "③ ログイン結果の待ち（上限）",
        "ログイン試行後、成功・失敗・動画のいずれかが出るまでの最大秒数",
        120.0, 10.0, 600.0, 10.0, "③ ログイン処理",
    ),
    SettingField(
        "login_movie_timeout",
        "③ ログイン動画の追加待ち",
        "ログイン動画が表示されたあと、成功と判断するまでの追加秒数",
        120.0, 10.0, 600.0, 10.0, "③ ログイン処理",
    ),
    SettingField(
        "stuck_server_list_seconds",
        "③ 停滞とみなす時間",
        "ログイン中ずっとサーバー一覧のままなら、固まったと判断してリトライする",
        30.0, 20.0, 120.0, 5.0, "③ ログイン処理",
    ),
    SettingField(
        "recovery_timeout",
        "失敗後の画面復帰待ち（上限）",
        "Enter 確定・BACK 後、次の操作可能画面が出るまでの最大秒数",
        45.0, 5.0, 300.0, 5.0, "失敗時の復帰（④〜⑦）",
    ),
)

MATCHING_FIELDS: tuple[SettingField, ...] = (
    SettingField(
        "screen_threshold",
        "画面判定の一致度",
        "サーバー一覧やメインメニューなど「画面全体」の一致度。この値以上で一致とみなす",
        0.75, 0.50, 0.95, 0.01, "画像認識の感度",
    ),
    SettingField(
        "button_threshold",
        "ボタン判定の一致度",
        "JOIN や BACK などボタン画像の一致度。低くすると誤クリック、高くすると見逃しやすい",
        0.75, 0.50, 0.95, 0.01, "画像認識の感度",
    ),
    SettingField(
        "button_threshold_relaxed",
        "ボタン再検索の緩い一致度",
        "通常のしきい値で見つからないとき、こちらの値でもう一度検索する",
        0.68, 0.45, 0.90, 0.01, "画像認識の感度",
    ),
    SettingField(
        "mods_screen_threshold",
        "② MODS 画面の一致度",
        "MODS 画面が出ているかの判定。低くすると見逃しにくいが誤判定も増える",
        0.55, 0.40, 0.90, 0.01, "画像認識の感度",
    ),
    SettingField(
        "screen_ready_margin",
        "① 復帰判定のゆるさ",
        "サーバー一覧に戻った判定をどれだけ緩くするか（大きいほど緩い）",
        0.05, 0.00, 0.20, 0.01, "画像認識の感度",
    ),
)

CLICK_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("image", "画像優先（見つかったら画像の位置をクリック）"),
    ("image_only", "画像のみ（座標フォールバックなし）"),
    ("coordinates", "座標優先（登録座標をクリック・未設定時は画像）"),
    ("coordinates_only", "座標のみ（クリックは座標・到達判定は画面＋ボタン PNG）"),
)

CLICK_MODE_LABEL_TO_VALUE = {label: value for value, label in CLICK_MODE_OPTIONS}
CLICK_MODE_VALUE_TO_LABEL = {value: label for value, label in CLICK_MODE_OPTIONS}

MODS_DETECT_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("hybrid", "ハイブリッド（推奨）… 画面＋ボタン"),
    ("screen", "画面テンプレートのみ"),
    ("button", "ボタン画像のみ"),
)

MODS_DETECT_MODE_LABEL_TO_VALUE = {label: value for value, label in MODS_DETECT_MODE_OPTIONS}
MODS_DETECT_MODE_VALUE_TO_LABEL = {value: label for value, label in MODS_DETECT_MODE_OPTIONS}

MODS_SCREEN_REGION_OPTIONS: tuple[tuple[str, str], ...] = (
    ("center", "中央モーダル（推奨）… 背景の一覧差を無視"),
    ("full", "画面全体"),
)

MODS_SCREEN_REGION_LABEL_TO_VALUE = {label: value for value, label in MODS_SCREEN_REGION_OPTIONS}
MODS_SCREEN_REGION_VALUE_TO_LABEL = {value: label for value, label in MODS_SCREEN_REGION_OPTIONS}

VALID_MODS_DETECT_MODES = frozenset(value for value, _label in MODS_DETECT_MODE_OPTIONS)
VALID_MODS_SCREEN_REGIONS = frozenset(value for value, _label in MODS_SCREEN_REGION_OPTIONS)


def ensure_config_exists() -> Path:
    ensure_app_dirs()
    if CONFIG_PATH.exists():
        return CONFIG_PATH
    for example in (EXAMPLE_CONFIG_PATH, BUNDLED_EXAMPLE_CONFIG_PATH):
        if example.exists():
            CONFIG_PATH.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
            return CONFIG_PATH
    raise FileNotFoundError("config.yaml / config.example.yaml が見つかりません")


def load_config(config_path: str | Path | None = None) -> dict:
    path = Path(config_path) if config_path else ensure_config_exists()
    if not path.exists():
        raise FileNotFoundError(f"設定ファイルが見つかりません: {path}")
    try:
        with open(path, encoding="utf-8") as f:
            loaded = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise ValueError(
            f"config.yaml の形式が壊れています。元ファイルは変更していません。\n{exc}"
        ) from exc
    if not isinstance(loaded, dict):
        raise ValueError("config.yaml の最上位は key: value 形式である必要があります。")
    return normalize_config(loaded)


def load_default_config() -> dict:
    """config.example.yaml の内容を返す（設定の初期値）"""
    for example in (EXAMPLE_CONFIG_PATH, BUNDLED_EXAMPLE_CONFIG_PATH):
        if example.exists():
            with open(example, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    raise FileNotFoundError("config.example.yaml が見つかりません")


def save_config(
    config: dict,
    config_path: str | Path | None = None,
    *,
    backup_before_write: bool = True,
    legacy_discord_defaults: bool = False,
) -> None:
    from .default_assets import prune_stale_template_paths

    config = normalize_config(config, legacy_discord_defaults=legacy_discord_defaults)
    prune_stale_template_paths(config)
    path = Path(config_path) if config_path else CONFIG_PATH
    text = yaml.dump(
        config,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    _atomic_write_config(path, text, backup_before_write=backup_before_write)


def _atomic_write_config(path: Path, text: str, *, backup_before_write: bool = True) -> None:
    """正常な旧設定を保持し、同一ディレクトリ内で原子的に置換する。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if backup_before_write and path.exists():
        try:
            current = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(current, dict):
                shutil.copy2(path, backup)
        except (OSError, UnicodeError, yaml.YAMLError):
            logger.warning("現在の設定が不正なためバックアップ更新をスキップします: %s", path)

    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def restore_config_backup(config_path: str | Path | None = None) -> bool:
    path = Path(config_path) if config_path else CONFIG_PATH
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        return False
    loaded = yaml.safe_load(backup.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        return False
    # 退避ファイル自体を壊れた現行設定で上書きしない（引き継ぎ退避を含む）
    # .bak に無い Discord キーは旧既定 OFF/0 を維持する
    save_config(loaded, path, backup_before_write=False, legacy_discord_defaults=True)
    return True


def normalize_config(config: dict, *, legacy_discord_defaults: bool = False) -> dict:
    """旧設定を保持しつつ、実行不能な型・範囲・列挙値だけを安全値へ直す。"""
    normalized = copy.deepcopy(config)

    def section(name: str) -> dict:
        value = normalized.get(name)
        if not isinstance(value, dict):
            if value is not None:
                logger.warning("設定セクション %s を初期化します", name)
            value = {}
            normalized[name] = value
        return value

    display = section("display")
    retry = section("retry")
    matching = section("matching")
    window = section("window")
    meta = section("meta")
    notifications = section("notifications")
    discord = notifications.setdefault("discord", {})
    if not isinstance(discord, dict):
        discord = {}
        notifications["discord"] = discord
    discord["enabled"] = bool(discord.get("enabled", False))
    discord["webhook_url"] = str(discord.get("webhook_url") or "").strip()
    discord["mention_user_ids"] = list(parse_mention_user_ids(discord.get("mention_user_ids")))
    discord["mention_everyone"] = bool(discord.get("mention_everyone", False))
    normalize_discord_section(discord, use_legacy_defaults=legacy_discord_defaults)
    ui = section("ui")
    for key in OBSOLETE_UI_KEYS:
        if key in ui:
            logger.info("不要になった ui.%s を削除します", key)
            ui.pop(key)

    def enum_value(section: dict, key: str, valid: set[str], default: str) -> None:
        value = section.get(key, default)
        if value not in valid:
            logger.warning("不正な設定 %s=%r を %s に修正します", key, value, default)
            section[key] = default

    enum_value(display, "capture_mode", {"window", "monitor"}, DEFAULT_CAPTURE_MODE)
    enum_value(
        matching,
        "click_mode",
        {"image", "image_only", "coordinates", "coordinates_only"},
        "image",
    )
    enum_value(matching, "mods_detect_mode", set(VALID_MODS_DETECT_MODES), "hybrid")
    enum_value(matching, "mods_screen_region", set(VALID_MODS_SCREEN_REGIONS), "center")
    matching["skip_required_mods"] = bool(matching.get("skip_required_mods", False))

    try:
        display["monitor_index"] = max(1, int(display.get("monitor_index", 1)))
    except (TypeError, ValueError):
        logger.warning("monitor_index を 1 に修正します")
        display["monitor_index"] = 1

    for field in RETRY_TIMING_FIELDS:
        raw = retry.get(field.key, field.default)
        try:
            value = int(raw) if field.value_type == "int" else float(raw)
        except (TypeError, ValueError):
            value = field.default
        retry[field.key] = max(field.vmin, min(field.vmax, value))
        if field.value_type == "int":
            retry[field.key] = int(retry[field.key])
    for field in MATCHING_FIELDS:
        try:
            value = float(matching.get(field.key, field.default))
        except (TypeError, ValueError):
            value = field.default
        matching[field.key] = max(field.vmin, min(field.vmax, value))

    try:
        retry["max_attempts"] = max(0, int(retry.get("max_attempts", 0)))
    except (TypeError, ValueError):
        retry["max_attempts"] = 0
    try:
        retry["delay_seconds"] = max(0.0, float(retry.get("delay_seconds", 3.0)))
    except (TypeError, ValueError):
        retry["delay_seconds"] = 3.0
    window["title_contains"] = str(
        window.get("title_contains") or "ARK: Survival Ascended"
    )
    meta["config_schema_version"] = CONFIG_SCHEMA_VERSION
    return normalized


CAPTURE_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    ("window", "ゲームウィンドウ（推奨）"),
    ("monitor", "モニター全体"),
)

CAPTURE_MODE_LABEL_TO_VALUE = {label: value for value, label in CAPTURE_MODE_OPTIONS}
CAPTURE_MODE_VALUE_TO_LABEL = {value: label for value, label in CAPTURE_MODE_OPTIONS}


def _normalize_mods_detect_mode(value: str | None) -> str:
    if value in VALID_MODS_DETECT_MODES:
        return value
    return "hybrid"


def _normalize_mods_screen_region(value: str | None) -> str:
    if value in VALID_MODS_SCREEN_REGIONS:
        return value
    return "center"


def build_capture_settings(config: dict) -> CaptureSettings:
    display = config.get("display", {})
    window = config.get("window", {})
    return CaptureSettings(
        mode=display.get("capture_mode", DEFAULT_CAPTURE_MODE),
        monitor_index=int(display.get("monitor_index", 1)),
        window_title=window.get("title_contains", "ARK: Survival Ascended"),
    )


def build_vision(config: dict) -> Vision:
    display = config.get("display", {})
    matching = config.get("matching", {})
    meta = config.get("meta", {})
    monitor_index = int(display.get("monitor_index", 1))
    setup_size = None
    if meta.get("setup_capture_width") and meta.get("setup_capture_height"):
        setup_size = (
            int(meta["setup_capture_width"]),
            int(meta["setup_capture_height"]),
        )
    return Vision(
        threshold=float(matching.get("threshold", 0.8)),
        monitor_index=monitor_index,
        capture_settings=build_capture_settings(config),
        setup_capture_size=setup_size,
        setup_dpi=int(meta["setup_dpi"]) if meta.get("setup_dpi") else None,
    )


def apply_ui_overrides(
    config: dict,
    *,
    max_attempts: int | None = None,
    delay_seconds: float | None = None,
    monitor_index: int | None = None,
    capture_mode: str | None = None,
    show_click_indicator: bool | None = None,
    retry_timing: dict[str, float | int] | None = None,
    matching_overrides: dict[str, float | str] | None = None,
    window_overrides: dict[str, str | bool] | None = None,
    ui_overrides: dict[str, dict[str, float]] | None = None,
) -> dict:
    updated = yaml.safe_load(yaml.dump(config)) or {}
    retry = updated.setdefault("retry", {})
    display = updated.setdefault("display", {})
    matching = updated.setdefault("matching", {})
    window = updated.setdefault("window", {})
    ui = updated.setdefault("ui", {})

    if max_attempts is not None:
        retry["max_attempts"] = max_attempts
    if delay_seconds is not None:
        retry["delay_seconds"] = delay_seconds
    if monitor_index is not None:
        display["monitor_index"] = monitor_index
    if capture_mode is not None:
        display["capture_mode"] = capture_mode
    if show_click_indicator is not None:
        display["show_click_indicator"] = show_click_indicator
    if retry_timing:
        for key, value in retry_timing.items():
            retry[key] = value
    if matching_overrides:
        for key, value in matching_overrides.items():
            matching[key] = value
    if window_overrides:
        for key, value in window_overrides.items():
            window[key] = value
    if ui_overrides:
        for key, value in ui_overrides.items():
            ui[key] = value

    return updated


def build_automator(
    config: dict,
    on_state_change: Callable | None = None,
) -> LoginAutomator:
    ensure_default_assets()
    retry_cfg = config.get("retry", {})
    matching_cfg = config.get("matching", {})
    templates_cfg = config.get("templates", {})
    window_cfg = config.get("window", {})
    ui_cfg = config.get("ui", {})
    display_cfg = config.get("display", {})

    monitor_index = int(display_cfg.get("monitor_index", 1))
    capture_settings = build_capture_settings(config)
    screen_threshold = float(matching_cfg.get("screen_threshold", matching_cfg.get("threshold", 0.75)))
    vision = build_vision(config)

    templates = TemplateConfig(
        server_list=templates_cfg.get("server_list", "templates/server_list.png"),
        required_mods=templates_cfg.get("required_mods", "templates/required_mods.png"),
        connection_failed=templates_cfg.get("connection_failed", "templates/connection_failed.png"),
        login_movie=templates_cfg.get("login_movie", "templates/login_movie.png"),
        network_failure=templates_cfg.get("network_failure", "templates/network_failure.png"),
        title_screen=templates_cfg.get("title_screen", "templates/title_screen.png"),
        server_list_empty=templates_cfg.get("server_list_empty", "templates/server_list_empty.png"),
        main_menu=templates_cfg.get("main_menu", "templates/main_menu.png"),
        in_game=templates_cfg.get("in_game", "templates/in_game.png"),
        screen_threshold=screen_threshold,
        mods_screen_threshold=float(matching_cfg.get("mods_screen_threshold", 0.55)),
        mods_detect_mode=_normalize_mods_detect_mode(matching_cfg.get("mods_detect_mode", "hybrid")),
        mods_screen_region=_normalize_mods_screen_region(matching_cfg.get("mods_screen_region", "center")),
        skip_required_mods=bool(matching_cfg.get("skip_required_mods", False)),
        screen_ready_margin=float(matching_cfg.get("screen_ready_margin", 0.05)),
        click_mode=matching_cfg.get("click_mode", "image"),
    )

    retry = RetryConfig(
        max_attempts=retry_cfg.get("max_attempts", 0),
        delay_seconds=retry_cfg.get("delay_seconds", 3.0),
        join_click_delay=retry_cfg.get("join_click_delay", 1.5),
        check_interval=retry_cfg.get("check_interval", 0.5),
        poll_interval=retry_cfg.get("poll_interval", retry_cfg.get("check_interval", 0.5)),
        transition_settle=retry_cfg.get("transition_settle", 0.4),
        after_click_delay=retry_cfg.get("after_click_delay", retry_cfg.get("join_click_delay", 1.5)),
        transition_timeout=retry_cfg.get("transition_timeout", 20.0),
        result_timeout=retry_cfg.get("result_timeout", 120.0),
        login_movie_timeout=retry_cfg.get("login_movie_timeout", 120.0),
        mods_wait_seconds=retry_cfg.get("mods_wait_seconds", 8.0),
        recovery_timeout=retry_cfg.get("recovery_timeout", 45.0),
        stuck_server_list_seconds=retry_cfg.get("stuck_server_list_seconds", 30.0),
        start_countdown_seconds=int(retry_cfg.get("start_countdown_seconds", 3)),
        screen_stable_polls=max(1, int(retry_cfg.get("screen_stable_polls", 2))),
    )

    ui = UiPositions.from_dict(ui_cfg, monitor_index=monitor_index, capture_settings=capture_settings)
    buttons = ButtonConfig.from_dict(config.get("buttons", {}), matching_cfg)

    return LoginAutomator(
        vision=vision,
        templates=templates,
        retry=retry,
        ui=ui,
        buttons=buttons,
        window_title=window_cfg.get("title_contains", "ARK: Survival Ascended"),
        bring_to_front=window_cfg.get("bring_to_front", True),
        on_state_change=on_state_change,
        config=config,
    )
