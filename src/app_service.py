"""設定の読み書きと LoginAutomator の構築"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

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

# GUI / config.yaml の retry キー: (表示ラベル, デフォルト, 最小, 最大, 刻み, グループ)
RETRY_TIMING_FIELDS: tuple[tuple[str, str, float, float, float, float, str], ...] = (
    ("start_countdown_seconds", "開始までのカウントダウン (秒)", 3, 0, 60, 1, "全体・開始前"),
    ("poll_interval", "画面・ボタンを確認する間隔 (秒)", 0.5, 0.1, 5.0, 0.1, "全体・開始前"),
    ("transition_settle", "クリック前の安定待ち (秒)", 0.4, 0.0, 5.0, 0.1, "全体・開始前"),
    ("after_click_delay", "クリック後の画面遷移待ち (秒)", 2.0, 0.0, 30.0, 0.5, "全体・開始前"),
    ("transition_timeout", "ボタン・画面が出るまでの上限 (秒)", 20.0, 1.0, 120.0, 1.0, "サーバー一覧・MODS"),
    ("mods_wait_seconds", "REQUIRED MODS 画面の出現待ち (秒)", 8.0, 0.0, 60.0, 1.0, "REQUIRED MODS"),
    ("result_timeout", "ログイン完了までの待ち (秒)", 120.0, 10.0, 600.0, 10.0, "ログイン処理"),
    ("login_movie_timeout", "ログインムービー再生中の追加待ち (秒)", 120.0, 10.0, 600.0, 10.0, "ログイン処理"),
    ("stuck_server_list_seconds", "一覧のまま動かないと判断する時間 (秒)", 30.0, 20.0, 120.0, 5.0, "ログイン処理"),
    ("recovery_timeout", "失敗後に次の画面を待つ上限 (秒)", 45.0, 5.0, 300.0, 5.0, "失敗後の復帰"),
)


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
) -> dict:
    updated = yaml.safe_load(yaml.dump(config)) or {}
    retry = updated.setdefault("retry", {})
    display = updated.setdefault("display", {})

    if max_attempts is not None:
        retry["max_attempts"] = max_attempts
    if delay_seconds is not None:
        retry["delay_seconds"] = delay_seconds
    if monitor_index is not None:
        display["monitor_index"] = monitor_index
    if retry_timing:
        for key, value in retry_timing.items():
            retry[key] = value

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
    screen_threshold = matching_cfg.get("screen_threshold", matching_cfg.get("threshold", 0.75))
    vision = Vision(threshold=matching_cfg.get("threshold", 0.8), monitor_index=monitor_index)

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
