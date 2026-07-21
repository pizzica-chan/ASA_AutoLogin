"""設定の読み書きと LoginAutomator の構築"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Literal

import yaml

from .paths import app_root, bundle_root, ensure_app_dirs
from .button_templates import ButtonConfig
from .default_assets import ensure_default_assets
from .login_flow import LoginAutomator, LoginState, RetryConfig, TemplateConfig
from .ui_positions import UiPositions
from .vision import Vision

CONFIG_PATH = app_root() / "config.yaml"
EXAMPLE_CONFIG_PATH = app_root() / "config.example.yaml"
BUNDLED_EXAMPLE_CONFIG_PATH = bundle_root() / "config.example.yaml"

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
    UiClickField("cancel_failed", "③-A CANCEL", 55.0, 55.0),
    UiClickField("back_empty_list", "④ BACK", 5.0, 92.0),
    UiClickField("join_game", "⑤ JOIN GAME", 29.0, 91.0),
    UiClickField("accept_network_failure", "⑥ ACCEPT", 50.0, 60.0),
)

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
        "CANCEL・BACK・ACCEPT 後、次の操作可能画面が出るまでの最大秒数",
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
        "JOIN や CANCEL などボタン画像の一致度。低くすると誤クリック、高くすると見逃しやすい",
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
    ("coordinates", "座標優先（画像が見つからなければ登録座標）"),
    ("coordinates_only", "座標のみ（画像は画面判定のみ・クリックはすべて座標）"),
)

CLICK_MODE_LABEL_TO_VALUE = {label: value for value, label in CLICK_MODE_OPTIONS}
CLICK_MODE_VALUE_TO_LABEL = {value: label for value, label in CLICK_MODE_OPTIONS}


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
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_config(config: dict, config_path: str | Path | None = None) -> None:
    path = Path(config_path) if config_path else CONFIG_PATH
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def apply_ui_overrides(
    config: dict,
    *,
    max_attempts: int | None = None,
    delay_seconds: float | None = None,
    monitor_index: int | None = None,
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
    screen_threshold = float(matching_cfg.get("screen_threshold", matching_cfg.get("threshold", 0.75)))
    vision = Vision(threshold=float(matching_cfg.get("threshold", 0.8)), monitor_index=monitor_index)

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
    )

    ui = UiPositions.from_dict(ui_cfg, monitor_index=monitor_index)
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
    )
