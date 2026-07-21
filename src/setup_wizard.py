"""初回セットアップ: サンプル画像ナビ + 画面キャプチャ + クリック登録（GUI）"""

from __future__ import annotations

import logging
import shutil
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Callable

import mss
import numpy as np
import yaml
from PIL import Image, ImageTk

from .display import list_monitors
from .default_assets import resolve_button_path
from .default_assets import ensure_default_assets
from .paths import app_root, bundle_root

logger = logging.getLogger(__name__)

TEMPLATES_DIR = app_root() / "templates"
SAMPLES_DIR = bundle_root() / "docs" / "setup_samples"

COLORS = {
    "bg": "#1a1d23",
    "surface": "#242830",
    "surface2": "#2d323c",
    "text": "#e8eaed",
    "text_dim": "#9aa0a6",
    "accent": "#4a9eff",
}


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
            "ダイアログ右側の CANCEL ボタンが見える状態にしてください（ACCEPT は使いません）。",
            "背景に MULTIPLAYER SERVERS: 0 の空一覧が見えていても問題ありません。",
        ),
        capture_hint="CONNECTION FAILED ダイアログ付きの画面をキャプチャします。",
        click_key="cancel_failed",
        click_hint="CANCEL ボタンの位置をクリックして座標登録",
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
            "ダイアログ内の ACCEPT ボタンが見える状態にしてください。",
        ),
        capture_hint="エラーダイアログ付きのタイトル画面をキャプチャします。",
        click_key="accept_network_failure",
        click_hint="ACCEPT ボタンの位置をクリックして座標登録",
    ),
    SetupStep(
        name="title_screen",
        title="⑦ タイトル画面",
        required=False,
        sample_image=None,
        prepare_lines=(
            "⑥ で ACCEPT を押した直後のタイトル画面です。",
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
            "成功判定に使います。推奨ですがスキップ可能です。",
        ),
        capture_hint="ゲーム内の画面をキャプチャします。",
    ),
)


def _sample_path(step: SetupStep) -> Path | None:
    if not step.sample_image:
        return None
    path = SAMPLES_DIR / step.sample_image
    return path if path.exists() else None


def _grab_screen(monitor_index: int, output_path: Path) -> Image.Image:
    with mss.mss() as sct:
        monitor = sct.monitors[monitor_index]
        screenshot = sct.grab(monitor)
        frame = np.array(screenshot)
        img = Image.fromarray(frame)
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    return img


def save_setup_config(ui: dict, monitor_index: int) -> None:
    ensure_default_assets()

    config_path = app_root() / "config.yaml"
    example_path = app_root() / "config.example.yaml"
    bundled_example = bundle_root() / "config.example.yaml"

    if config_path.exists():
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
    config.setdefault("display", {})["monitor_index"] = monitor_index
    templates = config.setdefault("templates", {})
    for step in SETUP_STEPS:
        path = TEMPLATES_DIR / f"{step.name}.png"
        if path.exists():
            templates[step.name] = f"templates/{step.name}.png"

    config.pop("buttons", None)

    matching = config.setdefault("matching", {})
    matching.setdefault("screen_threshold", 0.75)
    matching.setdefault("button_threshold", 0.75)
    matching.setdefault("button_threshold_relaxed", 0.68)
    matching.setdefault("mods_screen_threshold", 0.55)
    matching.setdefault("screen_ready_margin", 0.05)
    matching.setdefault("click_mode", "image")

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


class SetupIntroDialog(tk.Toplevel):
    """モード・モニター・カウントダウン設定"""

    def __init__(self, parent: tk.Misc, default_monitor_index: int = 1):
        super().__init__(parent)
        self.title("ASA_Login セットアップ")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.result: dict | None = None

        self.transient(parent)
        self.grab_set()

        monitors = list_monitors()
        self._monitor_map = {m.label: m.index for m in monitors}

        tk.Label(
            self,
            text="セットアップ",
            fg=COLORS["text"],
            bg=COLORS["bg"],
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor=tk.W, padx=20, pady=(16, 4))

        tk.Label(
            self,
            text="最小モードでは ① サーバー一覧だけ登録します。",
            fg=COLORS["text_dim"],
            bg=COLORS["bg"],
            font=("Segoe UI", 10),
        ).pack(anchor=tk.W, padx=20, pady=(0, 12))

        body = tk.Frame(self, bg=COLORS["surface"], padx=14, pady=12)
        body.pack(fill=tk.X, padx=16, pady=(0, 8))

        tk.Label(body, text="モード", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W)
        self.mode_var = tk.StringVar(value="minimal")
        tk.Radiobutton(
            body,
            text="最小（推奨）… サーバー一覧のみ",
            variable=self.mode_var,
            value="minimal",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            selectcolor=COLORS["surface2"],
            activebackground=COLORS["surface"],
            font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=2)
        tk.Radiobutton(
            body,
            text="フル … すべての画面を登録",
            variable=self.mode_var,
            value="full",
            bg=COLORS["surface"],
            fg=COLORS["text"],
            selectcolor=COLORS["surface2"],
            activebackground=COLORS["surface"],
            font=("Segoe UI", 10),
        ).pack(anchor=tk.W, pady=2)

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

        tk.Label(body, text="キャプチャカウントダウン (秒)", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(10, 4))
        self.countdown_var = tk.IntVar(value=5)
        tk.Spinbox(body, from_=1, to=15, textvariable=self.countdown_var, width=6).pack(anchor=tk.W)

        footer = tk.Frame(self, bg=COLORS["bg"])
        footer.pack(fill=tk.X, padx=16, pady=14)
        ttk.Button(footer, text="キャンセル", command=self._cancel).pack(side=tk.LEFT)
        ttk.Button(footer, text="開始", command=self._ok).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.update_idletasks()
        self.geometry(f"+{parent.winfo_rootx() + 40}+{parent.winfo_rooty() + 40}")

    def _cancel(self) -> None:
        self.result = None
        self.destroy()

    def _ok(self) -> None:
        monitor_label = self.monitor_var.get()
        self.result = {
            "mode": self.mode_var.get(),
            "monitor_index": self._monitor_map.get(monitor_label, 1),
            "countdown": int(self.countdown_var.get()),
        }
        self.destroy()


class StepGuideDialog(tk.Toplevel):
    """ステップ案内"""

    def __init__(self, parent: tk.Misc, step: SetupStep, step_index: int, total_steps: int):
        super().__init__(parent)
        self.title("ASA_Login セットアップ")
        self.configure(bg=COLORS["bg"])
        self.minsize(520, 400)
        self.action = "cancel"

        self.transient(parent)
        self.grab_set()

        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill=tk.X, padx=16, pady=(14, 6))
        tk.Label(header, text=f"ステップ {step_index} / {total_steps}", fg=COLORS["text_dim"], bg=COLORS["bg"], font=("Segoe UI", 10)).pack(anchor=tk.W)
        tk.Label(header, text=step.title, fg=COLORS["text"], bg=COLORS["bg"], font=("Segoe UI", 16, "bold")).pack(anchor=tk.W, pady=(2, 0))

        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill=tk.BOTH, expand=True, padx=16, pady=8)

        guide = tk.Frame(body, bg=COLORS["surface"], padx=12, pady=10)
        guide.pack(fill=tk.X, pady=(0, 10))
        tk.Label(guide, text="ARK で準備すること", fg=COLORS["accent"], bg=COLORS["surface"], font=("Segoe UI", 11, "bold")).pack(anchor=tk.W)
        for line in step.prepare_lines:
            tk.Label(guide, text=f"• {line}", fg=COLORS["text"], bg=COLORS["surface"], font=("Segoe UI", 10), wraplength=640, justify=tk.LEFT).pack(anchor=tk.W, pady=2)
        tk.Label(guide, text=step.capture_hint, fg=COLORS["text_dim"], bg=COLORS["surface"], font=("Segoe UI", 10), wraplength=640, justify=tk.LEFT).pack(anchor=tk.W, pady=(8, 0))

        sample = _sample_path(step)
        if sample:
            sample_frame = tk.Frame(body, bg=COLORS["surface"], padx=10, pady=10)
            sample_frame.pack(fill=tk.BOTH, expand=True)
            tk.Label(sample_frame, text="参考イメージ", fg=COLORS["text_dim"], bg=COLORS["surface"], font=("Segoe UI", 10)).pack(anchor=tk.W, pady=(0, 6))
            img = Image.open(sample)
            max_w, max_h = 900, 420
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
        if not step.required:
            ttk.Button(footer, text="スキップ", command=lambda: self._choose("skip")).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(footer, text="キャプチャへ進む", command=lambda: self._choose("continue")).pack(side=tk.RIGHT)

        self.protocol("WM_DELETE_WINDOW", lambda: self._choose("cancel"))

    def _choose(self, action: str) -> None:
        self.action = action
        self.destroy()


class CaptureDialog(tk.Toplevel):
    """カウントダウン付き画面キャプチャ"""

    def __init__(self, parent: tk.Misc, step: SetupStep, monitor_index: int, countdown: int):
        super().__init__(parent)
        self.title("画面キャプチャ")
        self.configure(bg=COLORS["bg"])
        self.resizable(False, False)
        self.success = False
        self._monitor_index = monitor_index
        self._output_path = TEMPLATES_DIR / f"{step.name}.png"
        self._countdown = countdown
        self._timer_id: str | None = None

        self.transient(parent)
        self.grab_set()

        tk.Label(self, text=step.title, fg=COLORS["text"], bg=COLORS["bg"], font=("Segoe UI", 14, "bold")).pack(padx=20, pady=(16, 8))
        tk.Label(
            self,
            text="ARK で該当画面を表示してから「キャプチャ開始」を押してください。",
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
                _grab_screen(self._monitor_index, self._output_path)
                self.success = True
                self.status_label.configure(text="保存しました")
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
        data = {
            "x_percent": round(orig_x / self._img_w * 100, 2),
            "y_percent": round(orig_y / self._img_h * 100, 2),
        }
        self.result = data
        self.status.configure(text=f"登録しました ({data['x_percent']}%, {data['y_percent']}%)")
        self.after(500, self.destroy)


def run_wizard_gui(
    parent: tk.Misc | None = None,
    default_monitor_index: int = 1,
    on_complete: Callable[[], None] | None = None,
) -> bool:
    """GUI セットアップウィザード。成功時 True"""
    ensure_default_assets()
    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)

    owns_root = parent is None
    root = tk.Tk() if owns_root else parent
    if owns_root:
        root.withdraw()

    intro = SetupIntroDialog(root, default_monitor_index=default_monitor_index)
    root.wait_window(intro)
    if not intro.result:
        if owns_root:
            root.destroy()
        return False

    mode = intro.result["mode"]
    monitor_index = intro.result["monitor_index"]
    countdown = intro.result["countdown"]
    steps = list(SETUP_STEPS) if mode == "full" else [SETUP_STEPS[0]]
    ui: dict = {}

    for index, step in enumerate(steps, start=1):
        guide = StepGuideDialog(root, step, index, len(steps))
        root.wait_window(guide)
        if guide.action == "cancel":
            if owns_root:
                root.destroy()
            return False
        if guide.action == "skip":
            continue

        capture = CaptureDialog(root, step, monitor_index, countdown)
        root.wait_window(capture)
        if not capture.success:
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
            elif step.required:
                messagebox.showwarning("セットアップ中断", "クリック登録が必要です。", parent=root)
                if owns_root:
                    root.destroy()
                return False

    if "join_server_list" not in ui and not resolve_button_path("join_server_list"):
        messagebox.showerror("エラー", "① サーバー一覧の JOIN 座標が未登録です。", parent=root)
        if owns_root:
            root.destroy()
        return False

    save_setup_config(ui, monitor_index)
    messagebox.showinfo("セットアップ完了", "config.yaml を保存しました。", parent=root)

    if on_complete:
        on_complete()

    if owns_root:
        root.destroy()
    return True


def run_wizard(default_monitor_index: int = 1) -> bool:
    """CLI 互換: GUI ウィザードを起動"""
    return run_wizard_gui(default_monitor_index=default_monitor_index)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_wizard_gui()
