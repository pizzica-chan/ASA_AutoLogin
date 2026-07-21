"""ユーザー向けログと詳細ログの二系統管理"""

from __future__ import annotations

import logging
import queue
from pathlib import Path
from typing import Any

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

    user_file_handler = logging.FileHandler(user_path, encoding="utf-8")
    user_file_handler.setFormatter(logging.Formatter(USER_FORMAT, FILE_DATE_FORMAT))
    user_file_handler.setLevel(user_level)

    detail_file_handler = logging.FileHandler(detail_path, encoding="utf-8")
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


def teardown_logging() -> None:
    for handler in _gui_handlers + _file_handlers:
        handler.close()
    _gui_handlers.clear()
    _file_handlers.clear()
