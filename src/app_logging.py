"""ユーザー向けログと詳細ログの二系統管理"""

from __future__ import annotations

import logging
import queue
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import yaml

from .paths import app_root, ensure_app_dirs

CHANNEL_USER = "user"
CHANNEL_DETAIL = "detail"

USER_LOGGER_NAME = "asa_login.user"
DETAIL_LOGGER_NAME = "asa_login.detail"

user_log = logging.getLogger(USER_LOGGER_NAME)
detail_log = logging.getLogger(DETAIL_LOGGER_NAME)

USER_FORMAT = "%(asctime)s  %(message)s"
DETAIL_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%H:%M:%S"
FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

TEMPLATE_SCREEN_KEYS = (
    "server_list",
    "required_mods",
    "connection_failed",
    "login_movie",
    "network_failure",
    "title_screen",
    "server_list_empty",
    "main_menu",
    "in_game",
)

BUTTON_KEYS = (
    "join_server_list",
    "join_mods",
    "cancel_failed",
    "back_empty_list",
    "join_game",
    "join_game_center",
    "accept_network_failure",
    "login_success",
)

_gui_handlers: list[logging.Handler] = []
_file_handlers: list[logging.Handler] = []


class GuiQueueHandler(logging.Handler):
    """GUI へチャンネル付きでログを送る"""

    def __init__(self, log_queue: queue.Queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record: logging.LogRecord) -> None:
        channel = CHANNEL_USER if record.name == USER_LOGGER_NAME else CHANNEL_DETAIL
        self.log_queue.put(("log", channel, self.format(record)))


def _resolve_log_paths(config: dict | None) -> tuple[Path, Path]:
    ensure_app_dirs()
    log_cfg = (config or {}).get("logging", {})
    logs_dir = app_root() / "logs"

    user_file = log_cfg.get("user_file")
    detail_file = log_cfg.get("detail_file")
    legacy_file = log_cfg.get("file")

    if not user_file:
        user_file = "logs/asa_login_user.log"
    if not detail_file:
        detail_file = legacy_file or "logs/asa_login_detail.log"

    return logs_dir / Path(user_file).name, logs_dir / Path(detail_file).name


def _level_from_config(config: dict | None, key: str, default: str) -> int:
    log_cfg = (config or {}).get("logging", {})
    fallback = log_cfg.get("level", default)
    return getattr(logging, str(log_cfg.get(key, fallback)).upper(), logging.INFO)


def _attach_logger(
    logger: logging.Logger,
    *,
    level: int,
    handlers: list[logging.Handler],
) -> None:
    logger.setLevel(level)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
    for handler in handlers:
        logger.addHandler(handler)


def setup_logging(config: dict | None = None, log_queue: queue.Queue | None = None) -> None:
    """ファイル出力と（任意で）GUI キューへログを配線する"""
    global _gui_handlers, _file_handlers

    for handler in _gui_handlers + _file_handlers:
        handler.close()
    _gui_handlers = []
    _file_handlers = []

    user_level = _level_from_config(config, "user_level", "INFO")
    detail_level = _level_from_config(config, "detail_level", "DEBUG")
    user_path, detail_path = _resolve_log_paths(config)
    user_path.parent.mkdir(parents=True, exist_ok=True)
    detail_path.parent.mkdir(parents=True, exist_ok=True)

    log_cfg = (config or {}).get("logging", {})
    try:
        max_bytes = max(0, int(log_cfg.get("max_bytes", 5 * 1024 * 1024)))
    except (TypeError, ValueError):
        max_bytes = 5 * 1024 * 1024
    try:
        backup_count = max(1, int(log_cfg.get("backup_count", 3)))
    except (TypeError, ValueError):
        backup_count = 3

    user_file_handler = RotatingFileHandler(
        user_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    user_file_handler.setFormatter(logging.Formatter(USER_FORMAT, FILE_DATE_FORMAT))
    user_file_handler.setLevel(user_level)

    detail_file_handler = RotatingFileHandler(
        detail_path,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    detail_file_handler.setFormatter(logging.Formatter(DETAIL_FORMAT, FILE_DATE_FORMAT))
    detail_file_handler.setLevel(detail_level)

    _file_handlers = [user_file_handler, detail_file_handler]

    user_handlers: list[logging.Handler] = [user_file_handler]
    detail_handlers: list[logging.Handler] = [detail_file_handler]

    if log_queue is not None:
        gui_user = GuiQueueHandler(log_queue)
        gui_user.setFormatter(logging.Formatter(USER_FORMAT, DATE_FORMAT))
        gui_user.setLevel(user_level)

        gui_detail = GuiQueueHandler(log_queue)
        gui_detail.setFormatter(logging.Formatter(DETAIL_FORMAT, DATE_FORMAT))
        gui_detail.setLevel(detail_level)

        user_handlers.append(gui_user)
        detail_handlers.append(gui_detail)
        _gui_handlers = [gui_user, gui_detail]

    _attach_logger(user_log, level=user_level, handlers=user_handlers)
    _attach_logger(detail_log, level=detail_level, handlers=detail_handlers)

    detail_log.debug(
        "ログ出力を初期化しました (user=%s, detail=%s)",
        user_path,
        detail_path,
    )


def log_runtime_config_detail(config: dict | None, *, runtime: dict[str, Any] | None = None) -> None:
    """実行開始時の設定値を詳細ログへすべて書き出す"""
    from .notifier import redact_notifications_for_log

    config = config or {}
    runtime = runtime or {}
    log_config = redact_notifications_for_log(config)

    detail_log.info("=== 実行時設定（config.yaml 相当） ===")
    if log_config:
        dumped = yaml.dump(
            log_config,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
        for line in dumped.rstrip().splitlines():
            detail_log.info("  %s", line)
    else:
        detail_log.info("  (設定が空です)")

    detail_log.info("=== 解決済みランタイム情報 ===")
    for key, value in runtime.items():
        if isinstance(value, list):
            if not value:
                detail_log.info("  %s: (未設定)", key)
            elif len(value) == 1:
                detail_log.info("  %s: %s", key, value[0])
            else:
                detail_log.info("  %s:", key)
                for item in value:
                    detail_log.info("    - %s", item)
        elif isinstance(value, dict):
            detail_log.info("  %s:", key)
            for sub_key, sub_value in value.items():
                detail_log.info("    %s: %s", sub_key, sub_value)
        else:
            detail_log.info("  %s: %s", key, value)


def build_runtime_config_snapshot(
    config: dict,
    *,
    vision: Any | None = None,
    window_title: str | None = None,
    bring_to_front: bool | None = None,
    buttons: Any | None = None,
) -> dict[str, Any]:
    """config から詳細ログ用の解決済み情報を組み立てる"""
    from .button_templates import ButtonConfig
    from .capture import CaptureSettings, WindowNotFoundError, resolve_capture_region
    from .default_assets import resolve_screen_path, screen_template_source
    from .windows_environment import environment_snapshot, get_dpi_for_point

    display = config.get("display", {})
    window = config.get("window", {})
    capture_settings = CaptureSettings(
        mode=display.get("capture_mode", "window"),
        monitor_index=int(display.get("monitor_index", 1)),
        window_title=window.get("title_contains", "ARK: Survival Ascended"),
    )

    snapshot: dict[str, Any] = {
        "capture_mode": capture_settings.mode,
        "monitor_index": capture_settings.monitor_index,
        "window_title": window_title or capture_settings.window_title,
        "bring_to_front": bring_to_front,
        "environment": environment_snapshot(),
    }

    if vision is not None:
        snapshot["monitor_label"] = vision.monitor.label

    try:
        region = resolve_capture_region(
            capture_settings,
            strict_window=capture_settings.mode == "window",
        )
        snapshot["capture_region"] = {
            "mode": region.mode,
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        }
        current_dpi = get_dpi_for_point(
            region.left + region.width // 2,
            region.top + region.height // 2,
        )
        meta = config.get("meta", {})
        baseline_width = meta.get("setup_capture_width")
        baseline_height = meta.get("setup_capture_height")
        snapshot["environment_difference"] = {
            "current_dpi": current_dpi,
            "setup_dpi": meta.get("setup_dpi"),
            "width_ratio": (
                round(region.width / float(baseline_width), 4)
                if baseline_width
                else None
            ),
            "height_ratio": (
                round(region.height / float(baseline_height), 4)
                if baseline_height
                else None
            ),
        }
    except WindowNotFoundError as exc:
        snapshot["capture_region"] = f"未解決 ({exc})"

    templates_cfg = config.get("templates", {})
    resolved_templates: dict[str, str | None] = {}
    template_sources: dict[str, str] = {}
    for name in TEMPLATE_SCREEN_KEYS:
        user_path = templates_cfg.get(name)
        resolved_templates[name] = resolve_screen_path(name, user_path)
        template_sources[name] = screen_template_source(name, user_path)
    snapshot["templates_resolved"] = resolved_templates
    snapshot["templates_source"] = template_sources

    matching = config.get("matching", {})
    snapshot["matching"] = {
        key: matching[key]
        for key in (
            "click_mode",
            "mods_detect_mode",
            "mods_screen_region",
            "skip_required_mods",
            "screen_threshold",
            "mods_screen_threshold",
            "button_threshold",
        )
        if key in matching
    }
    button_cfg = buttons if buttons is not None else ButtonConfig.from_dict(
        config.get("buttons", {}),
        matching,
    )
    resolved_buttons: dict[str, list[str]] = {}
    for key in BUTTON_KEYS:
        resolved_buttons[key] = button_cfg.list_paths(key)
    snapshot["buttons_resolved"] = resolved_buttons

    ui_cfg = config.get("ui", {})
    if ui_cfg:
        snapshot["ui_percent"] = ui_cfg

    meta = config.get("meta")
    if meta:
        snapshot["meta"] = meta

    user_path, detail_path = _resolve_log_paths(config)
    snapshot["log_files"] = {
        "user": str(user_path),
        "detail": str(detail_path),
    }

    return snapshot


def teardown_logging(*, close_files: bool = True) -> None:
    handlers = list(_gui_handlers)
    if close_files:
        handlers += list(_file_handlers)
    for handler in handlers:
        for logger in (user_log, detail_log):
            if handler in logger.handlers:
                logger.removeHandler(handler)
        handler.close()
    _gui_handlers.clear()
    if close_files:
        _file_handlers.clear()
