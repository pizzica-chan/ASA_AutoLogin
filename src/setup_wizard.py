"""初回セットアップ: サンプル画像ナビ + 画面キャプチャ + クリック登録（GUI）"""

from __future__ import annotations

import copy
import logging
import shutil
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import cv2
import mss
import numpy as np
import yaml
from PIL import Image, ImageTk

from .display import list_monitors
from .coordinate_preview import percent_from_capture_click
from .default_assets import ensure_default_assets, resolve_button_path, SETUP_SAMPLES_DIR, prune_stale_template_paths
from .paths import app_root, bundle_root
from .capture import CaptureSettings, DEFAULT_CAPTURE_MODE, WindowNotFoundError, resolve_capture_region
from .button_templates import extract_and_save_button_crop, verify_button_crop
from .windows_environment import get_dpi_for_point

logger = logging.getLogger(__name__)

TEMPLATES_DIR = app_root() / "templates"
SAMPLES_DIR = SETUP_SAMPLES_DIR

# セットアップ画面キャプチャの保存形式バージョン（2 = BGRA→RGB 修正後）
SETUP_CAPTURE_VERSION = 2

_CAPTURE_MODE_LABELS = {
    "window": "ゲームウィンドウ",
    "monitor": "モニター全体",
}

COLORS = {
    "bg": "#1a1d23",
    "surface": "#242830",
    "surface2": "#2d323c",
    "text": "#e8eaed",
    "text_dim": "#9aa0a6",
    "accent": "#4a9eff",
}


def _bind_mousewheel(canvas: tk.Canvas) -> None:
    """スクロール領域上でのマウスホイール"""

    def _on_mousewheel(event: tk.Event) -> None:
        canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _bind(_event: tk.Event | None = None) -> None:
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

    def _unbind(_event: tk.Event | None = None) -> None:
        canvas.unbind_all("<MouseWheel>")

    canvas.bind("<Enter>", _bind)
    canvas.bind("<Leave>", _unbind)


def _make_scrollable_area(parent: tk.Misc, *, bg: str) -> tuple[tk.Frame, tk.Frame]:
    """縦スクロール可能な領域 (outer, inner) を返す"""
    outer = tk.Frame(parent, bg=bg)
    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, borderwidth=0)
    scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
    inner = tk.Frame(canvas, bg=bg)

    def _on_inner_configure(_event: tk.Event | None = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    def _on_canvas_configure(event: tk.Event) -> None:
        canvas.itemconfigure(canvas_window, width=event.width)

    inner.bind("<Configure>", _on_inner_configure)
    canvas_window = canvas.create_window((0, 0), window=inner, anchor=tk.NW)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    _bind_mousewheel(canvas)
    return outer, inner


def _place_dialog_near_parent(dialog: tk.Toplevel, parent: tk.Misc) -> None:
    """親ウィンドウ付近に、画面内に収まるサイズで配置する"""
    dialog.update_idletasks()
    screen_w = dialog.winfo_screenwidth()
    screen_h = dialog.winfo_screenheight()
    req_w = max(dialog.winfo_reqwidth(), getattr(dialog, "_min_width", 520))
    req_h = max(dialog.winfo_reqheight(), getattr(dialog, "_min_height", 520))
    width = min(req_w + 8, screen_w - 40)
    max_height = int(screen_h * 0.92)
    height = min(req_h + 12, max_height)
    x = min(parent.winfo_rootx() + 40, max(20, screen_w - width - 20))
    y = min(max(20, parent.winfo_rooty() + 20), max(20, screen_h - height - 20))
    dialog.geometry(f"{width}x{height}+{x}+{y}")
    dialog.minsize(min(width, getattr(dialog, "_min_width", 520)), min(height, 400))


@dataclass(frozen=True)
class SetupStep:
    name: str
    title: str
    required: bool
    sample_image: str | None
    prepare_lines: tuple[str, ...]
    capture_hint: str
    click_key: str | None = None
    click_hint: str | None = None


SETUP_STEPS: tuple[SetupStep, ...] = (
    SetupStep(
        name="server_list",
        title="① サーバー一覧",
        required=True,
        sample_image="01_server_list.png",
        prepare_lines=(
            "ARK で「マルチプレイサーバー一覧」を開きます。",
            "接続したいサーバーの行をクリックして選択します（行がオレンジ色になります）。",
            "画面右下に JOIN ボタンが見えている状態にしてください。",
        ),
        capture_hint="この画面をそのままキャプチャします。",
        click_key="join_server_list",
        click_hint="右下の JOIN ボタンの位置をクリックして座標登録",
    ),
    SetupStep(
        name="required_mods",
        title="② REQUIRED MODS 画面（条件付き）",
        required=False,
        sample_image="02_required_mods.png",
        prepare_lines=(
            "① の JOIN 後、サーバーによって REQUIRED MODS モーダルが表示されます。",
            "モーダル中央に REQUIRED MODS と必要な MOD 一覧が見える状態にします。",
            "モーダル左下の JOIN ボタン（オレンジ色）が見える状態にしてください。",
            "この画面が出ないサーバーの場合はスキップできます。",
        ),
        capture_hint="モーダル全体が見える状態でキャプチャします（背景のサーバー一覧も含めて可）。",
        click_key="join_mods",
        click_hint="モーダル左下の JOIN ボタンの位置をクリックして座標登録",
    ),
    SetupStep(
        name="login_movie",
        title="⑥ ログイン中ムービー",
        required=False,
        sample_image=None,
        prepare_lines=(
            "② の JOIN 後に流れるオレンジ背景のローディング画面です。",
            "任意です。スキップしても動作します。",
        ),
        capture_hint="ムービー再生中の画面をキャプチャします。",
    ),
    SetupStep(
        name="connection_failed",
        title="③-A 失敗（CONNECTION FAILED・サーバー一覧上）",
        required=True,
        sample_image="03a_connection_failed.png",
        prepare_lines=(
            "ログイン試行後、サーバー一覧の上に CONNECTION FAILED ダイアログが表示されます。",
            "本文例: This Server is full. Please try again later...",
            "ダイアログが見える状態にしてください（確定は Enter キーで行います）。",
            "背景に MULTIPLAYER SERVERS: 0 の空一覧が見えていても問題ありません。",
        ),
        capture_hint="CONNECTION FAILED ダイアログ付きの画面をキャプチャします。",
    ),
    SetupStep(
        name="network_failure",
        title="⑥ 失敗（NETWORK FAILURE・タイトル画面）",
        required=True,
        sample_image="05_network_failure.png",
        prepare_lines=(
            "② の JOIN 後、ログインムービーのあとタイトル画面に戻り、",
            "NETWORK FAILURE MESSAGE ダイアログが表示されます。",
            "本文例: Server full.",
            "ダイアログが見える状態にしてください（確定は Enter キーで行います）。",
        ),
        capture_hint="エラーダイアログ付きのタイトル画面をキャプチャします。",
    ),
    SetupStep(
        name="title_screen",
        title="⑦ タイトル画面",
        required=False,
        sample_image=None,
        prepare_lines=(
            "⑥ で Enter 確定後のタイトル画面です。",
            "エラーダイアログが消えた状態でキャプチャします。",
        ),
        capture_hint="PRESS TO START が見える画面をキャプチャします。",
    ),
    SetupStep(
        name="server_list_empty",
        title="④ 空のサーバー一覧",
        required=True,
        sample_image=None,
        prepare_lines=(
            "MULTIPLAYER SERVERS: 0 の空一覧画面を表示します。",
            "左下の BACK ボタンが見える状態にしてください。",
        ),
        capture_hint="一覧が空の画面をキャプチャします。",
        click_key="back_empty_list",
        click_hint="左下の BACK ボタンの位置をクリックして座標登録",
    ),
    SetupStep(
        name="main_menu",
        title="⑤ メインメニュー",
        required=True,
        sample_image="04_main_menu.png",
        prepare_lines=(
            "JOIN GAME カードが見えるメインメニューを表示します。",
            "④枚タイル（左から2番目が JOIN GAME）が主流です。",
            "⑤枚タイル（中央が JOIN GAME）の場合も同梱テンプレートで対応します。",
        ),
        capture_hint="メインメニュー全体をキャプチャします。",
        click_key="join_game",
        click_hint="JOIN GAME カード下部（文字部分）をクリックして座標登録",
    ),
    SetupStep(
        name="in_game",
        title="ログイン成功（ゲーム内）",
        required=False,
        sample_image=None,
        prepare_lines=(
            "サーバー参加に成功したゲーム内画面です。",
            "成功判定は templates/buttons/login_success.png（右下 HUD）を優先します。",
            "画面全体の in_game.png は未登録時のフォールバックです。",
        ),
        capture_hint="任意: ゲーム内全体をキャプチャ（login_success 未使用時のフォールバック用）",
    ),
)


def _sample_path(step: SetupStep) -> Path | None:
    if not step.sample_image:
        return None
    path = SAMPLES_DIR / step.sample_image
    return path if path.exists() else None


def _load_capture_settings(monitor_index: int) -> CaptureSettings:
    config_path = app_root() / "config.yaml"
    example_path = app_root() / "config.example.yaml"
    bundled_example = bundle_root() / "config.example.yaml"

    config: dict = {}
    for path in (config_path, example_path, bundled_example):
        if path.exists():
            with open(path, encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            break

    display = config.get("display", {})
    window = config.get("window", {})
    return CaptureSettings(
        mode=display.get("capture_mode", DEFAULT_CAPTURE_MODE),
        monitor_index=monitor_index,
        window_title=window.get("title_contains", "ARK: Survival Ascended"),
    )


def _grab_screen(capture_settings: CaptureSettings, output_path: Path) -> Image.Image:
    region = resolve_capture_region(capture_settings, strict_window=True)
    with mss.MSS() as sct:
        bbox = {
            "left": region.left,
            "top": region.top,
            "width": region.width,
            "height": region.height,
        }
        screenshot = sct.grab(bbox)
        frame = np.array(screenshot)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        img = Image.fromarray(rgb)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return img


def save_setup_config(
    ui: dict,
    monitor_index: int,
    capture_settings: CaptureSettings | None = None,
    base_config: dict | None = None,
) -> None:
    ensure_default_assets()

    config_path = app_root() / "config.yaml"
    example_path = app_root() / "config.example.yaml"
    bundled_example = bundle_root() / "config.example.yaml"

    if base_config is not None:
        config = copy.deepcopy(base_config)
    elif config_path.exists():
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    elif example_path.exists():
        shutil.copy(example_path, config_path)
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    elif bundled_example.exists():
        shutil.copy(bundled_example, config_path)
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    existing_ui = config.get("ui", {})
    for key, value in ui.items():
        cleaned = {
            "x_percent": value["x_percent"],
            "y_percent": value["y_percent"],
        }
        existing_ui[key] = cleaned
    config["ui"] = existing_ui
    display = config.setdefault("display", {})
    display["monitor_index"] = monitor_index
    if capture_settings is not None:
        display["capture_mode"] = capture_settings.mode
        config.setdefault("window", {})["title_contains"] = capture_settings.window_title
    templates = config.setdefault("templates", {})
    for step in SETUP_STEPS:
        key = step.name
        rel_path = f"templates/{key}.png"
        if (TEMPLATES_DIR / f"{key}.png").exists():
            templates[key] = rel_path
    prune_stale_template_paths(config)

    buttons = config.setdefault("buttons", {})
    captured_dir = TEMPLATES_DIR / "buttons" / "captured"
    for step in SETUP_STEPS:
        if not step.click_key:
            continue
        captured = captured_dir / f"{step.click_key}.png"
        if captured.exists():
            existing = str(buttons.get(step.click_key, ""))
            if existing and "/captured/" not in existing.replace("\\", "/"):
                logger.info("手動指定のボタン画像を維持: %s=%s", step.click_key, existing)
                continue
            buttons[step.click_key] = (
                f"templates/buttons/captured/{step.click_key}.png"
            )

    matching = config.setdefault("matching", {})
    matching.setdefault("screen_threshold", 0.75)
    matching.setdefault("button_threshold", 0.75)
    matching.setdefault("button_threshold_relaxed", 0.68)
    matching.setdefault("mods_screen_threshold", 0.55)
    matching.setdefault("mods_detect_mode", "hybrid")
    matching.setdefault("mods_screen_region", "center")
    matching.setdefault("screen_ready_margin", 0.05)
    matching.setdefault("click_mode", "image")

    meta = config.setdefault("meta", {})
    meta["setup_capture_version"] = SETUP_CAPTURE_VERSION
    if capture_settings is not None:
        meta["setup_capture_mode"] = capture_settings.mode
        try:
            region = resolve_capture_region(capture_settings, strict_window=True)
            meta["setup_capture_width"] = region.width
            meta["setup_capture_height"] = region.height
            meta["setup_capture_aspect"] = round(region.width / region.height, 6)
            meta["setup_monitor_index"] = monitor_index
            meta["setup_dpi"] = get_dpi_for_point(
                region.left + region.width // 2,
                region.top + region.height // 2,
            )
        except (WindowNotFoundError, OSError) as exc:
            logger.warning("セットアップ環境情報を保存できませんでした: %s", exc)

    from .app_service import save_config

    save_config(config, config_path)


def _step_registered(step: SetupStep) -> bool:
    return (TEMPLATES_DIR / f"{step.name}.png").exists()


def _steps_from_selection(step_names: list[str]) -> list[SetupStep]:
    name_set = set(step_names)
    return [step for step in SETUP_STEPS if step.name in name_set]


class SetupIntroDialog(tk.Toplevel):
    """モード・ステップ選択・モニター・カウントダウン設定"""

    def __init__(
        self,
        parent: tk.Misc,
        default_monitor_index: int = 1,
        capture_settings: CaptureSettings | None = None,
    ):
        super().__init__(parent)
        self.title("ASA_Login セットアップ")
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self._min_width = 520
        self._min_height = 560
        self.result: dict | None = None

        self.transient(parent)
        self.grab_set()

        monitors = list_monitors()
        self._monitor_map = {m.label: m.index for m in monitors}
        self._step_vars: dict[str, tk.BooleanVar] = {}
        self._step_checks: list[tk.Checkbutton] = []

        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill=tk.X, padx=20, pady=(16, 8))
        tk.Label(
            header,
            text="セットアップ",
            fg=COLORS["text"],
            bg=COLORS["bg"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor=tk.W)
        tk.Label(
            header,
            text="最小・フルに加え、必要な画面だけ個別に選んで登録できます。",
            fg=COLORS["text_dim"],
            bg=COLORS["bg"],
            font=("Segoe UI", 10),
            wraplength=480,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 0))
        tk.Label(
            header,
            text="初回は「最小（推奨）」で ① サーバー一覧だけ登録すれば動作します。",
            fg=COLORS["accent"],
            bg=COLORS["bg"],
            font=("Segoe UI", 10, "bold"),
            wraplength=480,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(6, 0))

        scroll_outer, scroll_inner = _make_scrollable_area(self, bg=COLORS["bg"])
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 8))

        body = tk.Frame(scroll_inner, bg=COLORS["surface"], padx=14, pady=12)
        body.pack(fill=tk.X, expand=True)

        tk.Label(body, text="モード", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        self.mode_var = tk.StringVar(value="minimal")
        for text, value in (
            ("最小（推奨）… ① サーバー一覧のみ", "minimal"),
            ("フル … すべての画面を順に登録", "full"),
            ("個別 … 下の一覧から選んで登録", "custom"),
        ):
            tk.Radiobutton(
                body,
                text=text,
                variable=self.mode_var,
                value=value,
                command=self._sync_custom_state,
                bg=COLORS["surface"],
                fg=COLORS["text"],
                selectcolor=COLORS["surface2"],
                activebackground=COLORS["surface"],
                font=("Segoe UI", 10),
            ).pack(anchor=tk.W, pady=2)

        tk.Label(
            body,
            text="登録する画面（個別モード）",
            fg=COLORS["accent"],
            bg=COLORS["surface"],
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor=tk.W, pady=(10, 4))

        list_frame = tk.Frame(body, bg=COLORS["surface2"], padx=8, pady=8)
        list_frame.pack(fill=tk.X)

        for step in SETUP_STEPS:
            registered = _step_registered(step)
            suffix = " — 登録済み" if registered else ""
            var = tk.BooleanVar(value=False)
            self._step_vars[step.name] = var
            cb = tk.Checkbutton(
                list_frame,
                text=f"{step.title}{suffix}",
                variable=var,
                bg=COLORS["surface2"],
                fg=COLORS["text"],
                selectcolor=COLORS["surface"],
                activebackground=COLORS["surface2"],
                font=("Segoe UI", 10),
                anchor=tk.W,
                wraplength=440,
                justify=tk.LEFT,
            )
            cb.pack(anchor=tk.W, pady=1)
            self._step_checks.append(cb)

        preset_row = tk.Frame(body, bg=COLORS["surface"])
        preset_row.pack(fill=tk.X, pady=(6, 0))
        self._preset_buttons: list[ttk.Button] = []
        for text, command in (
            ("すべて選択", self._select_all_steps),
            ("すべて解除", self._clear_all_steps),
        ):
            btn = ttk.Button(preset_row, text=text, command=command)
            btn.pack(side=tk.LEFT, padx=(0, 6))
            self._preset_buttons.append(btn)

        tk.Label(body, text="ARK モニター", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 4))
        default_label = next((m.label for m in monitors if m.index == default_monitor_index), monitors[0].label if monitors else "")
        self.monitor_var = tk.StringVar(value=default_label)
        monitor_menu = tk.OptionMenu(body, self.monitor_var, *[m.label for m in monitors])
        monitor_menu.configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            highlightthickness=0,
            width=28,
        )
        monitor_menu["menu"].configure(bg=COLORS["surface2"], fg=COLORS["text"])
        monitor_menu.pack(anchor=tk.W)

        if capture_settings is not None:
            capture_label = _CAPTURE_MODE_LABELS.get(capture_settings.mode, capture_settings.mode)
            tk.Label(
                body,
                text=f"キャプチャ範囲: {capture_label}（メイン画面の設定）",
                fg=COLORS["text_dim"],
                bg=COLORS["surface"],
                font=("Segoe UI", 9),
                wraplength=420,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=(8, 0))

        tk.Label(body, text="キャプチャカウントダウン (秒)", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 4))
        self.countdown_var = tk.IntVar(value=5)
        tk.Spinbox(body, from_=1, to=15, textvariable=self.countdown_var, width=6).pack(anchor=tk.W)

        footer = tk.Frame(self, bg=COLORS["bg"])
        footer.pack(fill=tk.X, padx=16, pady=14)
        ttk.Button(footer, text="キャンセル", command=self._cancel).pack(side=tk.LEFT)
        ttk.Button(footer, text="開始", command=self._ok).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._sync_custom_state()
        _place_dialog_near_parent(self, parent)

    def _sync_custom_state(self) -> None:
        enabled = self.mode_var.get() == "custom"
        state = tk.NORMAL if enabled else tk.DISABLED
        for cb in self._step_checks:
            cb.configure(state=state)
        for btn in self._preset_buttons:
            btn.state(["!disabled"] if enabled else ["disabled"])

    def _select_all_steps(self) -> None:
        for var in self._step_vars.values():
            var.set(True)

    def _clear_all_steps(self) -> None:
        for var in self._step_vars.values():
            var.set(False)

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _selected_step_names(self) -> list[str]:
        mode = self.mode_var.get()
        if mode == "minimal":
            return ["server_list"]
        if mode == "full":
            return [step.name for step in SETUP_STEPS]
        return [name for name, var in self._step_vars.items() if var.get()]

    def _ok(self) -> None:
        step_names = self._selected_step_names()
        if not step_names:
            messagebox.showwarning(
                "ステップ未選択",
                "個別モードでは、登録する画面を1つ以上選んでください。",
                parent=self,
            )
            return
        monitor_label = self.monitor_var.get()
        self.result = {
            "mode": self.mode_var.get(),
            "step_names": step_names,
            "monitor_index": self._monitor_map.get(monitor_label, 1),
            "countdown": int(self.countdown_var.get()),
        }
        self.destroy()


class StepGuideDialog(tk.Toplevel):
    """ステップ案内"""

    def __init__(
        self,
        parent: tk.Misc,
        step: SetupStep,
        step_index: int,
        total_steps: int,
        *,
        allow_skip: bool = True,
    ):
        super().__init__(parent)
        self.title("ASA_Login セットアップ")
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self._min_width = 520
        self._min_height = 420
        self.action = "cancel"

        self.transient(parent)
        self.grab_set()

        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(header, text=f"ステップ {step_index} / {total_steps}", fg=COLORS["text_dim"], bg=COLORS["bg"], font=("Segoe UI", 10)).pack(anchor=tk.W)
        tk.Label(header, text=step.title, fg=COLORS["text"], bg=COLORS["bg"], font=("Segoe UI", 16, "bold"), wraplength=640, justify=tk.LEFT).pack(anchor=tk.W, pady=(2, 0))

        scroll_outer, scroll_inner = _make_scrollable_area(self, bg=COLORS["bg"])
        scroll_outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)
        body = scroll_inner

        guide = tk.Frame(body, bg=COLORS["surface"], padx=12, pady=10)
        guide.pack(fill=tk.X, pady=(0, 10))
        tk.Label(guide, text="ARK で準備すること", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        for line in step.prepare_lines:
            tk.Label(guide, text=f"• {line}", fg=COLORS["text"], bg=COLORS["surface"], font=("Segoe UI", 10), wraplength=640, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
        tk.Label(guide, text=step.capture_hint, fg=COLORS["text_dim"], bg=COLORS["surface"], font=("Segoe UI", 10), wraplength=640, justify=tk.LEFT).pack(anchor=tk.W, pady=(8, 0))

        sample = _sample_path(step)
        if sample:
            sample_frame = tk.Frame(body, bg=COLORS["surface"], padx=10, pady=10)
            sample_frame.pack(fill=tk.X)
            tk.Label(sample_frame, text="参考イメージ", fg=COLORS["text_dim"], bg=COLORS["surface"], font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 6))
            img = Image.open(sample)
            max_w, max_h = 860, 360
            scale = min(max_w / img.width, max_h / img.height, 1.0)
            disp_w, disp_h = int(img.width * scale), int(img.height * scale)
            photo = ImageTk.PhotoImage(img.resize((disp_w, disp_h), Image.Resampling.LANCZOS))
            canvas = tk.Canvas(sample_frame, width=disp_w, height=disp_h, highlightthickness=0, bg="#000")
            canvas.pack()
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            canvas.image = photo
            if step.click_hint:
                tk.Label(sample_frame, text=f"登録するクリック: {step.click_hint}", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(8, 0))

        footer = tk.Frame(self, bg=COLORS["bg"])
        footer.pack(fill=tk.X, padx=16, pady=(4, 14))
        ttk.Button(footer, text="キャンセル", command=lambda: self._choose("cancel")).pack(side=tk.LEFT)
        if allow_skip and not step.required:
            ttk.Button(footer, text="スキップ", command=lambda: self._choose("skip")).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(footer, text="キャプチャへ進む", command=lambda: self._choose("continue")).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("cancel"))
        _place_dialog_near_parent(self, parent)

    def _choose(self, action: str) -> None:
        self.action = action
        self.destroy()


class CaptureDialog(tk.Toplevel):
    """カウントダウン付き画面キャプチャ"""

    def __init__(
        self,
        parent: tk.Misc,
        step: SetupStep,
        capture_settings: CaptureSettings,
        countdown: int,
    ):
        super().__init__(parent)
        self.title("画面キャプチャ")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.success = False
        self._capture_settings = capture_settings
        self._output_path = TEMPLATES_DIR / f"{step.name}.png"
        self._countdown = countdown
        self._timer_id: str | None = None

        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=step.title, fg=COLORS["text"], bg=COLORS["bg"], font=("Segoe UI", 14, "bold")).pack(padx=20, pady=(16, 8))
        capture_hint = (
            "ARK で該当画面を表示してから「キャプチャ開始」を押してください。"
            "（ゲームウィンドウ内のみキャプチャします）"
            if capture_settings.mode == "window"
            else "ARK で該当画面を表示してから「キャプチャ開始」を押してください。"
        )
        tk.Label(
            self,
            text=capture_hint,
            fg=COLORS["text_dim"],
            bg=COLORS["bg"],
            font=("Segoe UI", 10),
            wraplength=420,
        ).pack(padx=20, pady=(0, 12))

        self.status_label = tk.Label(self, text="", fg=COLORS["accent"], bg=COLORS["bg"], font=("Segoe UI", 12, "bold"))
        self.status_label.pack(padx=20, pady=8)

        btn_row = tk.Frame(self, bg=COLORS["bg"])
        btn_row.pack(fill=tk.X, padx=20, pady=(8, 16))
        self.start_btn = ttk.Button(btn_row, text="キャプチャ開始", command=self._start_countdown)
        self.start_btn.pack(side=tk.LEFT)
        ttk.Button(btn_row, text="キャンセル", command=self._cancel).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)

    def _cancel(self) -> None:
        if self._timer_id:
            self.after_cancel(self._timer_id)
        self.destroy()

    def _start_countdown(self) -> None:
        self.start_btn.configure(state=tk.DISABLED)
        self._tick(self._countdown)

    def _tick(self, remaining: int) -> None:
        if remaining <= 0:
            self.status_label.configure(text="キャプチャ中...")
            self.update_idletasks()
            try:
                _grab_screen(self._capture_settings, self._output_path)
                self.success = True
                self.status_label.configure(text="保存しました")
            except WindowNotFoundError as exc:
                messagebox.showerror("エラー", str(exc), parent=self)
            except Exception as exc:
                messagebox.showerror("エラー", f"キャプチャに失敗しました:\n{exc}", parent=self)
            self.after(600, self.destroy)
            return
        self.status_label.configure(text=f"{remaining} 秒後にキャプチャ...")
        self._timer_id = self.after(1000, lambda: self._tick(remaining - 1))


class ClickCalibrateDialog(tk.Toplevel):
    """キャプチャ画像上でクリック登録"""

    def __init__(
        self,
        parent: tk.Misc,
        image_path: Path,
        instruction: str,
        button_key: str | None = None,
        sample: Path | None = None,
    ):
        super().__init__(parent)
        self.title("クリック登録")
        self.configure(bg=COLORS["bg"])
        self.result: dict[str, float] | None = None

        self.transient(parent)
        self.grab_set()

        img = Image.open(image_path)
        img_w, img_h = img.size

        tk.Label(self, text=instruction, fg=COLORS["text"], bg=COLORS["bg"], font=("Segoe UI", 11, "bold"), wraplength=900, pady=8).pack()
        tk.Label(
            self,
            text="キャプチャ画像をクリックして座標を登録してください（ボタン画像認識は同梱サンプルを使用）。",
            fg=COLORS["text_dim"],
            bg=COLORS["bg"],
            font=("Segoe UI", 10),
        ).pack(pady=(0, 6))

        content = tk.Frame(self, bg=COLORS["bg"])
        content.pack(padx=10, pady=5)

        if sample and sample.exists():
            sample_col = tk.Frame(content, bg=COLORS["surface"], padx=8, pady=8)
            sample_col.pack(side=tk.LEFT, padx=(0, 10))
            tk.Label(sample_col, text="参考", fg=COLORS["text_dim"], bg=COLORS["surface"], font=("Segoe UI", 9)).pack(anchor=tk.W)
            ref = Image.open(sample)
            ref_scale = min(280 / ref.width, 200 / ref.height, 1.0)
            ref_w, ref_h = int(ref.width * ref_scale), int(ref.height * ref_scale)
            ref_photo = ImageTk.PhotoImage(ref.resize((ref_w, ref_h), Image.Resampling.LANCZOS))
            ref_canvas = tk.Canvas(sample_col, width=ref_w, height=ref_h, highlightthickness=0, bg="#000")
            ref_canvas.pack()
            ref_canvas.create_image(0, 0, anchor=tk.NW, image=ref_photo)
            ref_canvas.image = ref_photo

        capture_col = tk.Frame(content, bg=COLORS["bg"])
        capture_col.pack(side=tk.LEFT)
        tk.Label(capture_col, text="あなたのキャプチャ", fg=COLORS["text_dim"], bg=COLORS["bg"], font=("Segoe UI", 9)).pack(anchor=tk.W)

        max_w, max_h = 900, 520
        scale = min(max_w / img_w, max_h / img_h, 1.0)
        disp_w, disp_h = int(img_w * scale), int(img_h * scale)
        self._scale = scale
        self._img_w = img_w
        self._img_h = img_h
        self._image_path = image_path
        self._button_key = button_key

        self.status = tk.Label(capture_col, text="", fg=COLORS["accent"], bg=COLORS["bg"], font=("Segoe UI", 10))
        self.status.pack(anchor=tk.W, pady=(0, 4))

        canvas = tk.Canvas(capture_col, width=disp_w, height=disp_h, highlightthickness=0, bg="#000")
        canvas.pack()
        photo = ImageTk.PhotoImage(img.resize((disp_w, disp_h), Image.Resampling.LANCZOS))
        canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        canvas.image = photo
        canvas.bind("<Button-1>", self._on_click)

        ttk.Button(self, text="キャンセル", command=self.destroy).pack(pady=10)

    def _on_click(self, event) -> None:
        orig_x = int(event.x / self._scale)
        orig_y = int(event.y / self._scale)
        x_percent, y_percent = percent_from_capture_click(
            orig_x,
            orig_y,
            width=self._img_w,
            height=self._img_h,
        )
        data = {"x_percent": x_percent, "y_percent": y_percent}
        if self._button_key:
            output = TEMPLATES_DIR / "buttons" / "captured" / f"{self._button_key}.png"
            try:
                extract_and_save_button_crop(
                    self._image_path,
                    orig_x,
                    orig_y,
                    output,
                )
                score = verify_button_crop(self._image_path, output)
                logger.info("環境専用ボタン画像を保存: %s (自己テスト %.2f)", output, score)
            except RuntimeError as exc:
                logger.warning("環境専用ボタン画像を生成できませんでした: %s", exc)
        self.result = data
        self.status.configure(text=f"登録しました ({data['x_percent']}%, {data['y_percent']}%)")
        self.after(500, self.destroy)


def _validate_server_list_ui(steps: list[SetupStep], ui: dict, parent: tk.Misc) -> bool:
    ran_server_list = any(step.name == "server_list" for step in steps)
    if ran_server_list and "join_server_list" not in ui and not resolve_button_path("join_server_list"):
        messagebox.showerror("エラー", "① サーバー一覧の JOIN 座標が未登録です。", parent=parent)
        return False
    return True


def _complete_setup(
    root: tk.Misc,
    *,
    owns_root: bool,
    ui: dict,
    monitor_index: int,
    wizard_capture: CaptureSettings,
    base_config: dict | None,
    completed_steps: list[SetupStep],
    completed_titles: list[str],
    on_complete: Callable[[], None] | None,
) -> bool:
    if not _validate_server_list_ui(completed_steps, ui, root):
        if owns_root:
            root.destroy()
        return False

    capture_hint = (
        "\nキャプチャ範囲: ゲームウィンドウ"
        if wizard_capture.mode == "window"
        else "\nキャプチャ範囲: モニター全体"
    )
    step_summary = "、".join(completed_titles)
    save_setup_config(ui, monitor_index, wizard_capture, base_config=base_config)
    messagebox.showinfo(
        "セットアップ完了",
        "config.yaml を保存しました。"
        f"{capture_hint}\n\n"
        f"登録した画面: {step_summary}\n\n"
        "解像度・キャプチャ範囲・表示モードを変更した場合は、再度セットアップが必要です。",
        parent=root,
    )
    if on_complete:
        on_complete()
    if owns_root:
        root.destroy()
    return True


def _offer_partial_save(
    root: tk.Misc,
    *,
    owns_root: bool,
    ui: dict,
    monitor_index: int,
    wizard_capture: CaptureSettings,
    base_config: dict | None,
    completed_steps: list[SetupStep],
    completed_titles: list[str],
    on_complete: Callable[[], None] | None,
) -> bool:
    if not completed_titles:
        if owns_root:
            root.destroy()
        return False
    if not messagebox.askyesno(
        "セットアップ中断",
        f"完了した {len(completed_titles)} 件を保存しますか？\n\n"
        + "、".join(completed_titles),
        parent=root,
    ):
        if owns_root:
            root.destroy()
        return False
    return _complete_setup(
        root,
        owns_root=owns_root,
        ui=ui,
        monitor_index=monitor_index,
        wizard_capture=wizard_capture,
        base_config=base_config,
        completed_steps=completed_steps,
        completed_titles=completed_titles,
        on_complete=on_complete,
    )


def run_wizard_gui(
    parent: tk.Misc | None = None,
    default_monitor_index: int = 1,
    capture_settings: CaptureSettings | None = None,
    base_config: dict | None = None,
    on_complete: Callable[[], None] | None = None,
) -> bool:
    """GUI セットアップウィザード。成功時 True"""
    ensure_default_assets()
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    owns_root = parent is None
    root = tk.Tk() if owns_root else parent
    if owns_root:
        root.withdraw()

    preview_capture = capture_settings or _load_capture_settings(default_monitor_index)
    intro = SetupIntroDialog(
        root,
        default_monitor_index=default_monitor_index,
        capture_settings=preview_capture,
    )
    root.wait_window(intro)
    if not intro.result:
        if owns_root:
            root.destroy()
        return False

    monitor_index = intro.result["monitor_index"]
    countdown = intro.result["countdown"]
    base_capture = capture_settings or _load_capture_settings(monitor_index)
    wizard_capture = CaptureSettings(
        mode=base_capture.mode,
        monitor_index=monitor_index,
        window_title=base_capture.window_title,
    )
    steps = _steps_from_selection(intro.result.get("step_names", ["server_list"]))
    setup_mode = intro.result.get("mode", "minimal")
    ui: dict = {}
    completed_steps: list[SetupStep] = []
    completed_titles: list[str] = []

    for index, step in enumerate(steps, start=1):
        allow_skip = setup_mode != "custom"
        guide = StepGuideDialog(
            root,
            step,
            index,
            len(steps),
            allow_skip=allow_skip,
        )
        root.wait_window(guide)
        if guide.action == "cancel":
            return _offer_partial_save(
                root,
                owns_root=owns_root,
                ui=ui,
                monitor_index=monitor_index,
                wizard_capture=wizard_capture,
                base_config=base_config,
                completed_steps=completed_steps,
                completed_titles=completed_titles,
                on_complete=on_complete,
            )
        if guide.action == "skip":
            continue

        capture = CaptureDialog(root, step, wizard_capture, countdown)
        root.wait_window(capture)
        if not capture.success:
            if step.required and setup_mode == "custom":
                messagebox.showwarning("セットアップ中断", "選択した画面のキャプチャが必要です。", parent=root)
                return _offer_partial_save(
                    root,
                    owns_root=owns_root,
                    ui=ui,
                    monitor_index=monitor_index,
                    wizard_capture=wizard_capture,
                    base_config=base_config,
                    completed_steps=completed_steps,
                    completed_titles=completed_titles,
                    on_complete=on_complete,
                )
            if step.required:
                messagebox.showwarning("セットアップ中断", "必須ステップが完了していません。", parent=root)
                if owns_root:
                    root.destroy()
                return False
            continue

        image_path = TEMPLATES_DIR / f"{step.name}.png"
        if step.click_key and step.click_hint:
            calibrate = ClickCalibrateDialog(
                root,
                image_path,
                step.click_hint,
                button_key=step.click_key,
                sample=_sample_path(step),
            )
            root.wait_window(calibrate)
            if calibrate.result:
                ui[step.click_key] = calibrate.result
            elif step.required or setup_mode == "custom":
                completed_steps.append(step)
                completed_titles.append(step.title)
                messagebox.showwarning("セットアップ中断", "クリック登録が必要です。", parent=root)
                return _offer_partial_save(
                    root,
                    owns_root=owns_root,
                    ui=ui,
                    monitor_index=monitor_index,
                    wizard_capture=wizard_capture,
                    base_config=base_config,
                    completed_steps=completed_steps,
                    completed_titles=completed_titles,
                    on_complete=on_complete,
                )
            else:
                continue

        completed_steps.append(step)
        completed_titles.append(step.title)

    if not completed_titles:
        messagebox.showwarning("セットアップ中断", "登録された画面がありません。", parent=root)
        if owns_root:
            root.destroy()
        return False

    return _complete_setup(
        root,
        owns_root=owns_root,
        ui=ui,
        monitor_index=monitor_index,
        wizard_capture=wizard_capture,
        base_config=base_config,
        completed_steps=completed_steps,
        completed_titles=completed_titles,
        on_complete=on_complete,
    )


def run_wizard(default_monitor_index: int = 1) -> bool:
    """CLI 互換: GUI ウィザードを起動"""
    return run_wizard_gui(default_monitor_index=default_monitor_index)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_wizard_gui()
