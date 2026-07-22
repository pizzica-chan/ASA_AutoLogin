"""自動ログイン開始前の環境・認識診断。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Literal

from .app_service import build_capture_settings, build_vision
from .button_templates import ButtonConfig
from .capture import WindowNotFoundError, resolve_capture_region
from .default_assets import resolve_screen_path
from .display import list_monitors
from .vision import ASPECT_WARN_DELTA
from .windows_environment import get_dpi_for_point

DiagnosticLevel = Literal["ok", "warning", "fatal"]


@dataclass(frozen=True)
class DiagnosticItem:
    level: DiagnosticLevel
    title: str
    detail: str
    action: str = ""


@dataclass
class PreflightReport:
    items: list[DiagnosticItem]

    @property
    def can_start(self) -> bool:
        return not any(item.level == "fatal" for item in self.items)

    @property
    def has_warnings(self) -> bool:
        return any(item.level == "warning" for item in self.items)

    def to_text(self) -> str:
        labels = {"ok": "正常", "warning": "注意", "fatal": "開始不可"}
        lines = ["ASA_Login 開始前診断"]
        for item in self.items:
            line = f"[{labels[item.level]}] {item.title}: {item.detail}"
            if item.action:
                line += f" / 推奨: {item.action}"
            lines.append(line)
        return "\n".join(lines)

    def to_support_text(self, config: dict) -> str:
        from .app_logging import build_runtime_config_snapshot
        from .windows_environment import environment_snapshot

        snapshot = build_runtime_config_snapshot(config)
        support = {
            "environment": environment_snapshot(),
            "capture": snapshot.get("capture_region"),
            "templates_source": snapshot.get("templates_source"),
            "matching": snapshot.get("matching"),
            "meta": snapshot.get("meta"),
            "log_files": snapshot.get("log_files"),
        }
        return self.to_text() + "\n\n=== サポート情報 ===\n" + json.dumps(
            support,
            ensure_ascii=False,
            indent=2,
            default=str,
        )


def _difference_items(config: dict, width: int, height: int, dpi: int) -> list[DiagnosticItem]:
    meta = config.get("meta", {})
    base_w = meta.get("setup_capture_width")
    base_h = meta.get("setup_capture_height")
    base_dpi = meta.get("setup_dpi")
    if not base_w or not base_h:
        return [
            DiagnosticItem(
                "warning",
                "セットアップ環境",
                "旧設定のため解像度・DPIの基準情報がありません",
                "セットアップを再実行",
            )
        ]

    width_ratio = width / float(base_w)
    height_ratio = height / float(base_h)
    aspect_delta = abs((width / height) / (float(base_w) / float(base_h)) - 1.0)
    scale_delta = max(abs(width_ratio - 1.0), abs(height_ratio - 1.0))
    if aspect_delta > ASPECT_WARN_DELTA:
        return [
            DiagnosticItem(
                "warning",
                "画面比率",
                f"現在 {width}x{height} / セットアップ時 {base_w}x{base_h}",
                "同じ表示モードで再セットアップ",
            )
        ]
    if scale_delta > 0.05 or (base_dpi and abs(dpi / float(base_dpi) - 1.0) > 0.05):
        return [
            DiagnosticItem(
                "warning",
                "表示スケール",
                f"現在 {width}x{height}・{dpi}DPI / セットアップ時 {base_w}x{base_h}・{base_dpi or '?'}DPI",
                "認識できない場合は再セットアップ",
            )
        ]
    return [DiagnosticItem("ok", "セットアップ環境", "画面サイズとDPIは基準内です")]


def run_preflight(config: dict) -> PreflightReport:
    items: list[DiagnosticItem] = []
    settings = build_capture_settings(config)
    monitor_indexes = {monitor.index for monitor in list_monitors()}
    if settings.monitor_index not in monitor_indexes:
        level: DiagnosticLevel = "fatal" if settings.mode == "monitor" else "warning"
        items.append(
            DiagnosticItem(
                level,
                "モニター設定",
                f"モニター {settings.monitor_index} は現在存在しません",
                "表示設定で実在するモニターを選択",
            )
        )
    if not bool(config.get("window", {}).get("bring_to_front", True)):
        items.append(
            DiagnosticItem(
                "warning",
                "フォーカス設定",
                "ARKを自動で前面化しない設定です",
                "誤入力防止のため「操作前にARKを前面に出す」を有効化",
            )
        )

    server_list_path = resolve_screen_path(
        "server_list", config.get("templates", {}).get("server_list")
    )
    if not server_list_path:
        items.append(
            DiagnosticItem(
                "fatal",
                "必須キャプチャ",
                "サーバー一覧画像がありません",
                "最小セットアップを実行",
            )
        )
        return PreflightReport(items)

    try:
        region = resolve_capture_region(
            settings, strict_window=settings.mode == "window"
        )
    except WindowNotFoundError as exc:
        items.append(DiagnosticItem("fatal", "ARKウィンドウ", str(exc), "ARKを起動して前面表示"))
        return PreflightReport(items)

    dpi = get_dpi_for_point(
        region.left + region.width // 2, region.top + region.height // 2
    )
    items.append(
        DiagnosticItem(
            "ok",
            "キャプチャ領域",
            f"{region.mode} {region.width}x{region.height} ({region.left}, {region.top})",
        )
    )
    items.extend(_difference_items(config, region.width, region.height, dpi))

    try:
        vision = build_vision(config)
        screen = vision.capture_screen()
    except Exception as exc:
        items.append(DiagnosticItem("fatal", "画面キャプチャ", f"取得に失敗: {exc}", "表示モードを確認"))
        return PreflightReport(items)

    if vision.is_black_frame(screen):
        items.append(
            DiagnosticItem(
                "fatal",
                "画面キャプチャ",
                "黒画面または単色画面です",
                "排他フルスクリーンをボーダーレスへ変更",
            )
        )
        return PreflightReport(items)

    matching = config.get("matching", {})
    screen_threshold = float(matching.get("screen_threshold", 0.75))
    screen_match = vision.compare_with_reference(
        server_list_path, threshold=screen_threshold, screen=screen
    )
    if screen_match.found:
        items.append(
            DiagnosticItem("ok", "サーバー一覧認識", f"一致度 {screen_match.confidence:.2f}")
        )
    else:
        items.append(
            DiagnosticItem(
                "warning",
                "サーバー一覧認識",
                f"一致度 {screen_match.confidence:.2f}（基準 {screen_threshold:.2f}）",
                "サーバーを選択した一覧画面にするか再セットアップ",
            )
        )

    buttons = ButtonConfig.from_dict(config.get("buttons", {}), matching)
    button_paths = buttons.list_paths("join_server_list")
    if button_paths:
        best = 0.0
        for path in button_paths:
            match = vision.find_button_on_screen(
                path,
                threshold=float(matching.get("button_threshold", 0.75)),
                screen=screen,
            )
            best = max(best, match.confidence)
        level: DiagnosticLevel = "ok" if best >= float(matching.get("button_threshold", 0.75)) else "warning"
        items.append(
            DiagnosticItem(
                level,
                "JOINボタン認識",
                f"最高一致度 {best:.2f}",
                "" if level == "ok" else "座標を確認またはボタン画像を差し替え",
            )
        )
    return PreflightReport(items)
