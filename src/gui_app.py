"""ASA_Login グラフィカルユーザーインターフェース"""

from __future__ import annotations

import copy
import json
import queue
import sys
import threading
import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from .app_logging import CHANNEL_DETAIL, CHANNEL_USER, detail_log, setup_logging, teardown_logging, user_log

from .app_service import (
    CAPTURE_MODE_LABEL_TO_VALUE,
    CAPTURE_MODE_OPTIONS,
    CAPTURE_MODE_VALUE_TO_LABEL,
    CLICK_MODE_COORDINATES_ONLY,
    CLICK_MODE_LABEL_TO_VALUE,
    CLICK_MODE_OPTIONS,
    CLICK_MODE_VALUE_TO_LABEL,
    MATCHING_FIELDS,
    MODS_DETECT_MODE_LABEL_TO_VALUE,
    MODS_DETECT_MODE_OPTIONS,
    MODS_DETECT_MODE_VALUE_TO_LABEL,
    MODS_SCREEN_REGION_LABEL_TO_VALUE,
    MODS_SCREEN_REGION_OPTIONS,
    MODS_SCREEN_REGION_VALUE_TO_LABEL,
    RETRY_TIMING_FIELDS,
    STATE_LABELS,
    UI_CLICK_FIELDS,
    SettingField,
    apply_ui_overrides,
    build_automator,
    load_config,
    load_default_config,
    restore_config_backup,
    save_config,
)
from .capture import CaptureSettings, DEFAULT_CAPTURE_MODE, WindowNotFoundError, resolve_capture_region
from .coordinate_preview import pick_coordinate_on_screen, show_coordinate_preview
from .display import list_monitors
from .login_flow import LoginState
from .notifier import (
    DEFAULT_ATTACH_SCREENSHOT,
    DEFAULT_STUCK_REPEAT_THRESHOLD,
    format_mention_user_ids_for_form,
    notify_loop_finished,
    parse_mention_user_ids,
    send_discord_test,
    validate_webhook_url,
)
from .paths import app_root, bundle_root, prepare_runtime
from .preflight_diagnostics import PreflightReport, run_preflight
from .settings_migration import (
    format_migration_confirm_message,
    format_migration_help_text,
    format_migration_summary,
    format_migration_summary_detail,
    import_from_legacy_exe,
    preview_legacy_import,
)
from .setup_wizard import SETUP_CAPTURE_VERSION, _place_dialog_near_parent, run_wizard_gui
from .ui_positions import UiPositions

START_SAMPLE_IMAGE = bundle_root() / "docs" / "setup_samples" / "01_server_list.png"

COLORS = {
    "bg": "#1a1d23",
    "surface": "#242830",
    "surface2": "#2d323c",
    "border": "#3a4150",
    "text": "#e8eaed",
    "text_dim": "#9aa0a6",
    "accent": "#4a9eff",
    "accent_hover": "#3d8ce6",
    "success": "#34c759",
    "warning": "#ff9f0a",
    "danger": "#ff453a",
    "idle": "#6c757d",
}

QUICK_START_GUIDE = """1. 右下の「セットアップ」で ① サーバー一覧を登録（初回のみ・最小モードで OK）
2. ARK で接続先サーバーを選択した状態にする
3. 「▶ 開始」を押す

詳細は「取扱説明書」、うまくいかないときは「画像認識」「待ち時間」タブを調整してください。"""


class StartReadyDialog(tk.Toplevel):
    """開始前: サーバー選択済みの状態であることを確認"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("開始前の確認")
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self._min_width = 520
        self._min_height = 420
        self.confirmed = False

        self.grab_set()

        tk.Label(
            self,
            text="開始前に ARK を次の状態にしてください",
            fg=COLORS["text"],
            bg=COLORS["bg"],
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor=tk.W, padx=20, pady=(16, 8))

        guide = tk.Frame(self, bg=COLORS["surface"], padx=14, pady=12)
        guide.pack(fill=tk.X, padx=16, pady=(0, 10))

        for line in (
            "マルチプレイのサーバー一覧を表示します。",
            "ログインしたいサーバーの行をクリックして選択します（行がオレンジ色になります）。",
            "画面右下に JOIN ボタンが見えていることを確認してください。",
        ):
            tk.Label(
                guide,
                text=f"• {line}",
                fg=COLORS["text"],
                bg=COLORS["surface"],
                font=("Segoe UI", 10),
                wraplength=640,
                justify=tk.LEFT,
            ).pack(anchor=tk.W, pady=2)

        tk.Label(
            guide,
            text="下の参考画像と同じ状態になってから開始してください。",
            fg=COLORS["accent"],
            bg=COLORS["surface"],
            font=("Segoe UI", 10, "bold"),
            wraplength=640,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 0))

        if START_SAMPLE_IMAGE.exists():
            img_frame = tk.Frame(self, bg=COLORS["surface"], padx=10, pady=10)
            img_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 10))
            tk.Label(
                img_frame,
                text="参考イメージ（サーバー選択済み）",
                fg=COLORS["text_dim"],
                bg=COLORS["surface"],
                font=("Segoe UI", 9),
            ).pack(anchor=tk.W, pady=(0, 6))

            image = Image.open(START_SAMPLE_IMAGE)
            max_w, max_h = 900, 480
            scale = min(max_w / image.width, max_h / image.height, 1.0)
            disp_w, disp_h = int(image.width * scale), int(image.height * scale)
            photo = ImageTk.PhotoImage(image.resize((disp_w, disp_h), Image.Resampling.LANCZOS))
            canvas = tk.Canvas(img_frame, width=disp_w, height=disp_h, highlightthickness=0, bg="#000")
            canvas.pack()
            canvas.create_image(0, 0, anchor=tk.NW, image=photo)
            canvas.image = photo

        footer = tk.Frame(self, bg=COLORS["bg"])
        footer.pack(fill=tk.X, padx=16, pady=(0, 16))
        ttk.Button(footer, text="キャンセル", command=self._on_cancel).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(
            footer,
            text="準備できたので開始",
            style="Accent.TButton",
            command=self._on_confirm,
        ).pack(side=tk.RIGHT)

        self.update_idletasks()
        self.minsize(520, 400)
        _place_dialog_near_parent(self, parent)
        self.attributes("-topmost", True)

        def _restack(_event: tk.Event | None = None) -> None:
            if hasattr(parent, "_apply_start_window_stack"):
                parent._apply_start_window_stack(self)

        self.bind("<Map>", _restack, add="+")
        self.after_idle(_restack)

    def _clear_topmost(self) -> None:
        try:
            self.attributes("-topmost", False)
        except tk.TclError:
            pass

    def _on_cancel(self) -> None:
        self._clear_topmost()
        self.confirmed = False
        self.destroy()

    def _on_confirm(self) -> None:
        self._clear_topmost()
        self.confirmed = True
        self.destroy()


class LoginApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASA_Login")
        self.geometry("680x780")
        self.minsize(560, 640)
        self.configure(bg=COLORS["bg"])

        self._config = {}
        self._saved_config_snapshot: str | None = None
        self._automator = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._timing_vars: dict[str, tk.Variable] = {}
        self._matching_vars: dict[str, tk.Variable] = {}
        self._ui_coord_vars: dict[str, tuple[tk.DoubleVar, tk.DoubleVar]] = {}
        self._start_config: dict = {}
        self._preflight_cache: tuple[str, float, PreflightReport] | None = None
        self.click_mode_var = tk.StringVar(value=CLICK_MODE_OPTIONS[0][1])
        self.mods_detect_mode_var = tk.StringVar(value=MODS_DETECT_MODE_OPTIONS[0][1])
        self.mods_screen_region_var = tk.StringVar(value=MODS_SCREEN_REGION_OPTIONS[0][1])
        self.skip_required_mods_var = tk.BooleanVar(value=False)
        self.capture_mode_var = tk.StringVar(value=CAPTURE_MODE_OPTIONS[0][1])
        self.window_title_var = tk.StringVar()
        self.bring_to_front_var = tk.BooleanVar(value=True)
        self.show_click_indicator_var = tk.BooleanVar(value=True)
        self.discord_notify_enabled_var = tk.BooleanVar(value=False)
        self.discord_webhook_var = tk.StringVar()
        self.discord_mention_users_var = tk.StringVar()
        self.discord_stuck_repeat_var = tk.IntVar(value=DEFAULT_STUCK_REPEAT_THRESHOLD)
        self.discord_mention_everyone_var = tk.BooleanVar(value=False)
        self.discord_attach_screenshot_var = tk.BooleanVar(value=DEFAULT_ATTACH_SCREENSHOT)
        self._capture_mode_trace_guard = False
        self._disk_capture_mode = DEFAULT_CAPTURE_MODE

        self._setup_styles()
        self._build_ui()
        self._load_settings()
        self.capture_mode_var.trace_add("write", self._on_capture_mode_changed)
        self.capture_mode_var.trace_add("write", lambda *_: self.after_idle(self._refresh_chrome))
        self.click_mode_var.trace_add("write", lambda *_: self.after_idle(self._refresh_chrome))
        self._poll_queue()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(300, self._show_startup_notices)
        self._register_click_indicator()

    def _register_click_indicator(self) -> None:
        from .click_indicator import set_display_handler

        set_display_handler(self._schedule_click_effect)

    def _schedule_click_effect(self, x: int, y: int, kind: str = "primary") -> None:
        self.after(0, lambda: self._render_click_effect(x, y, kind))

    def _render_click_effect(self, x: int, y: int, kind: str = "primary") -> None:
        from .click_indicator import spawn_click_effect

        if kind == "primary":
            spawn_click_effect(None, x, y)
        else:
            spawn_click_effect(None, x, y, kind)

    def _preview_click_indicator(self) -> None:
        from .click_indicator import spawn_click_effect_burst

        try:
            region = resolve_capture_region(
                self._get_capture_settings(),
                strict_window=self._get_capture_settings().mode == "window",
            )
        except Exception as exc:
            messagebox.showwarning("プレビュー", f"キャプチャ領域を取得できませんでした。\n{exc}", parent=self)
            return
        x = region.left + region.width // 2
        y = region.top + region.height // 2
        spawn_click_effect_burst(self, x, y, count=3, interval_ms=600)
        self._append_log(
            f"クリック表示プレビュー: キャプチャ領域中央 ({x}, {y}) に3回表示"
        )
        messagebox.showinfo(
            "クリック表示プレビュー",
            f"キャプチャ領域の中央 ({x}, {y}) に\n"
            "控えめな青いリップルを 3 回表示しました。\n\n"
            "• 見えない場合: フルスクリーン排他表示ではオーバーレイが隠れることがあります\n"
            "• 詳細ログに「クリック表示: (x, y)」が出ていれば自動ログイン中も動作しています",
            parent=self,
        )

    def _setup_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure(".", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["bg"], foreground=COLORS["text"])
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("Dim.TLabel", background=COLORS["bg"], foreground=COLORS["text_dim"])
        style.configure("CardDim.TLabel", background=COLORS["surface"], foreground=COLORS["text_dim"])
        style.configure("Title.TLabel", background=COLORS["bg"], foreground=COLORS["text"], font=("Segoe UI", 16, "bold"))
        style.configure("Status.TLabel", background=COLORS["surface"], foreground=COLORS["text"], font=("Segoe UI", 11, "bold"))

        field_opts = {
            "fieldbackground": COLORS["surface2"],
            "foreground": COLORS["text"],
            "background": COLORS["surface2"],
            "bordercolor": COLORS["border"],
            "lightcolor": COLORS["border"],
            "darkcolor": COLORS["border"],
            "insertcolor": COLORS["text"],
            "selectbackground": COLORS["accent"],
            "selectforeground": "#ffffff",
        }

        style.configure("Dark.TEntry", **field_opts)
        style.map("Dark.TEntry", fieldbackground=[("disabled", COLORS["surface"])])

        style.configure("Dark.TSpinbox", **field_opts, arrowcolor=COLORS["text"])
        style.map("Dark.TSpinbox", fieldbackground=[("disabled", COLORS["surface"])])

        self._configure_checkbutton_style(style, "Dark.TCheckbutton", background=COLORS["surface"])
        # 後方互換: 明示 style 未指定の Checkbutton も同じ見た目にする
        self._configure_checkbutton_style(style, "TCheckbutton", background=COLORS["surface"])

        style.configure("TScrollbar", background=COLORS["surface2"], troughcolor=COLORS["bg"], bordercolor=COLORS["bg"], arrowcolor=COLORS["text"])
        style.map("TScrollbar", background=[("active", COLORS["border"])])
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"])])
        style.configure("Danger.TButton", background=COLORS["danger"], foreground="white")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface"], foreground=COLORS["text"], padding=(10, 4))
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface2"])])

    def _configure_checkbutton_style(self, style: ttk.Style, name: str, *, background: str) -> None:
        """clam テーマの Checkbutton がホバー時に白フラッシュするのを防ぐ。"""
        surface2 = COLORS["surface2"]
        style.configure(
            name,
            background=background,
            foreground=COLORS["text"],
            focuscolor=background,
            bordercolor=background,
            lightcolor=background,
            darkcolor=background,
        )
        style.map(
            name,
            background=[
                ("active", background),
                ("selected", background),
                ("!disabled", background),
            ],
            foreground=[
                ("active", COLORS["text"]),
                ("disabled", COLORS["text_dim"]),
            ],
            indicatorcolor=[
                ("selected", COLORS["accent"]),
                ("!selected", COLORS["text_dim"]),
            ],
            indicatorbackground=[
                ("active", surface2),
                ("!active", surface2),
                ("selected", surface2),
                ("!selected", surface2),
            ],
            focuscolor=[
                ("focus", background),
                ("!focus", background),
            ],
        )

    def _init_timing_vars(self) -> None:
        for field in RETRY_TIMING_FIELDS:
            if field.value_type == "int":
                self._timing_vars[field.key] = tk.IntVar(value=int(field.default))
            else:
                self._timing_vars[field.key] = tk.DoubleVar(value=field.default)

    def _init_matching_vars(self) -> None:
        for field in MATCHING_FIELDS:
            self._matching_vars[field.key] = tk.DoubleVar(value=field.default)

    def _init_ui_coord_vars(self) -> None:
        for field in UI_CLICK_FIELDS:
            self._ui_coord_vars[field.key] = (
                tk.DoubleVar(value=field.default_x),
                tk.DoubleVar(value=field.default_y),
            )

    def _card(self, parent, title: str | None = None, *, compact: bool = False) -> ttk.Frame:
        pad = 8 if compact else 10
        outer = ttk.Frame(parent, style="Card.TFrame", padding=pad)
        outer.pack(fill=tk.X, pady=(0, 6 if compact else 8))
        body = ttk.Frame(outer, style="Card.TFrame")
        if title:
            ttk.Label(
                outer,
                text=title,
                style="Card.TLabel",
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor=tk.W, pady=(0, 4))
            body.pack(fill=tk.X)
        else:
            body.pack(fill=tk.X)
        return body

    def _build_ui(self) -> None:
        self._init_timing_vars()
        self._init_matching_vars()
        self._init_ui_coord_vars()

        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, text="ASA_Login", style="Title.TLabel", font=("Segoe UI", 14, "bold")).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="ARK 自動ログイン",
            style="Dim.TLabel",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(10, 0), pady=(4, 0))

        control = ttk.Frame(main, style="Card.TFrame", padding=8)
        control.pack(fill=tk.X, pady=(0, 6))

        status_row = ttk.Frame(control, style="Card.TFrame")
        status_row.pack(fill=tk.X)
        self.status_label = ttk.Label(status_row, text="待機中", style="Card.TLabel", font=("Segoe UI", 10, "bold"))
        self.status_label.pack(side=tk.LEFT)
        self.attempts_label = ttk.Label(status_row, text="試行: 0", style="CardDim.TLabel", font=("Segoe UI", 9))
        self.attempts_label.pack(side=tk.LEFT, padx=(16, 0))
        self.failures_label = ttk.Label(status_row, text="失敗: 0", style="CardDim.TLabel", font=("Segoe UI", 9))
        self.failures_label.pack(side=tk.LEFT, padx=(12, 0))
        self.elapsed_label = ttk.Label(status_row, text="経過: 0秒", style="CardDim.TLabel", font=("Segoe UI", 9))
        self.elapsed_label.pack(side=tk.LEFT, padx=(12, 0))

        btn_row = ttk.Frame(control, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(6, 0))
        self.start_btn = ttk.Button(btn_row, text="▶  開始", style="Accent.TButton", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 6))
        self.stop_btn = ttk.Button(
            btn_row, text="■  停止", style="Danger.TButton", command=self._on_stop, state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="保存", command=self._on_save).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="初期値", command=self._on_reset_defaults).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="取扱説明書", command=self._on_open_manual).pack(side=tk.RIGHT, padx=(6, 0))
        self.setup_btn = ttk.Button(btn_row, text="セットアップ", command=self._on_setup)
        self.setup_btn.pack(side=tk.RIGHT)

        self._paned = ttk.Panedwindow(main, orient=tk.VERTICAL)
        self._paned.pack(fill=tk.BOTH, expand=True)
        self._pane_split_applied = False

        settings_host = ttk.Frame(self._paned)
        log_host = ttk.Frame(self._paned)
        self._paned.add(settings_host, weight=2)
        self._paned.add(log_host, weight=5)

        notebook = ttk.Notebook(settings_host)
        notebook.pack(fill=tk.BOTH, expand=True)

        tab_main = ttk.Frame(notebook, padding=2)
        tab_timing = ttk.Frame(notebook, padding=2)
        tab_matching = ttk.Frame(notebook, padding=2)
        tab_coordinates = ttk.Frame(notebook, padding=2)
        tab_discord = ttk.Frame(notebook, padding=2)
        notebook.add(tab_main, text="メイン")
        notebook.add(tab_timing, text="待ち時間")
        notebook.add(tab_matching, text="画像認識")
        notebook.add(tab_coordinates, text="クリック座標")
        notebook.add(tab_discord, text="Discord 通知")

        self._build_main_tab(tab_main)
        self._build_timing_tab(tab_timing)
        self._build_matching_tab(tab_matching)
        self._build_coordinates_tab(tab_coordinates)
        self._build_discord_tab(tab_discord)

        log_header = ttk.Frame(log_host)
        log_header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(log_header, text="ログ", style="TLabel", font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        ttk.Label(
            log_header,
            text="区切りをドラッグしてログ領域の高さを調整できます",
            style="Dim.TLabel",
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.log_notebook = ttk.Notebook(log_host)
        self.log_notebook.pack(fill=tk.BOTH, expand=True)

        user_tab = ttk.Frame(self.log_notebook)
        detail_tab = ttk.Frame(self.log_notebook)
        self.log_notebook.add(user_tab, text="ログ")
        self.log_notebook.add(detail_tab, text="詳細ログ")

        self.user_log_text = self._create_log_text(user_tab, font=("Segoe UI", 9))
        self.detail_log_text = self._create_log_text(detail_tab, font=("Consolas", 9))
        self.log_notebook.select(user_tab)

        self.after_idle(self._apply_default_pane_split)
        self._paned.bind("<Configure>", self._apply_default_pane_split, add="+")

    def _apply_default_pane_split(self, _event: tk.Event | None = None) -> None:
        """設定エリアとログの初期分割（上 35% / 下 65% 目安）"""
        if getattr(self, "_pane_split_applied", False):
            return
        try:
            height = self._paned.winfo_height()
            if height > 120:
                self._paned.sashpos(0, max(140, int(height * 0.35)))
                self._pane_split_applied = True
        except tk.TclError:
            pass

    def _create_log_text(self, parent: tk.Misc, *, font: tuple[str, int]) -> scrolledtext.ScrolledText:
        widget = scrolledtext.ScrolledText(
            parent,
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            font=font,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        widget.pack(fill=tk.BOTH, expand=True)
        return widget

    def _build_main_tab(self, parent: ttk.Frame) -> None:
        scroll_body = self._build_scrollable_tab(parent)

        overview = self._card(scroll_body, "準備状況", compact=True)
        self.readiness_label = tk.Label(
            overview,
            text="確認中…",
            fg=COLORS["text"],
            bg=COLORS["surface"],
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=560,
        )
        self.readiness_label.pack(fill=tk.X, anchor=tk.W)
        ttk.Button(
            overview,
            text="診断情報をコピー",
            command=self._copy_diagnostics,
        ).pack(anchor=tk.E, pady=(6, 0))
        ttk.Separator(overview, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Label(
            overview,
            text=QUICK_START_GUIDE,
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W)

        display_card = self._card(scroll_body, "モニター・キャプチャ", compact=True)
        display_row = ttk.Frame(display_card, style="Card.TFrame")
        display_row.pack(fill=tk.X)
        ttk.Label(display_row, text="モニター", style="Card.TLabel", width=10).pack(side=tk.LEFT)
        self._monitors = list_monitors()
        self._monitor_label_to_index = {m.label: m.index for m in self._monitors}
        self._monitor_index_to_label = {m.index: m.label for m in self._monitors}
        default_label = self._monitors[0].label if self._monitors else "モニター 1"
        self.monitor_var = tk.StringVar(value=default_label)
        monitor_menu = tk.OptionMenu(
            display_row,
            self.monitor_var,
            *[m.label for m in self._monitors],
        )
        self._style_option_menu(monitor_menu, width=18)
        monitor_menu.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(display_row, text="キャプチャ", style="Card.TLabel", width=10).pack(side=tk.LEFT)
        capture_menu = tk.OptionMenu(
            display_row,
            self.capture_mode_var,
            *[label for _value, label in CAPTURE_MODE_OPTIONS],
        )
        self._style_option_menu(capture_menu, width=22)
        capture_menu.pack(side=tk.LEFT)

        retry_card = self._card(scroll_body, "リトライ", compact=True)
        retry_row = ttk.Frame(retry_card, style="Card.TFrame")
        retry_row.pack(fill=tk.X)
        ttk.Label(retry_row, text="最大試行", style="Card.TLabel", width=10).pack(side=tk.LEFT)
        self.max_attempts_var = tk.IntVar(value=0)
        ttk.Spinbox(
            retry_row,
            from_=0,
            to=9999,
            textvariable=self.max_attempts_var,
            width=6,
            style="Dark.TSpinbox",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(retry_row, text="0=無制限", style="CardDim.TLabel", font=("Segoe UI", 8)).pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(retry_row, text="間隔", style="Card.TLabel", width=6).pack(side=tk.LEFT)
        self.delay_var = tk.DoubleVar(value=3.0)
        ttk.Spinbox(
            retry_row,
            from_=0.5,
            to=60.0,
            increment=0.5,
            textvariable=self.delay_var,
            width=6,
            style="Dark.TSpinbox",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(retry_row, text="秒", style="CardDim.TLabel", font=("Segoe UI", 8)).pack(side=tk.LEFT)

        migrate_card = self._card(scroll_body, "旧版から引き継ぎ", compact=True)
        self._migration_help_label = tk.Label(
            migrate_card,
            text=format_migration_help_text(),
            fg=COLORS["text_dim"],
            bg=COLORS["surface"],
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=560,
        )
        self._migration_help_label.pack(fill=tk.X, anchor=tk.W, pady=(0, 6))
        ttk.Button(
            migrate_card,
            text="旧版 exe を指定して引き継ぐ…",
            command=self._on_import_legacy_settings,
        ).pack(anchor=tk.W)

    def _build_discord_tab(self, parent: ttk.Frame) -> None:
        scroll_body = self._build_scrollable_tab(parent)

        overview = self._card(scroll_body, "Discord 通知（任意）", compact=True)
        ttk.Label(
            overview,
            text=(
                "自動ログインのループが終了したとき（成功・失敗・エラー）に、"
                "Discord チャンネルへメッセージを送ります。\n"
                "Webhook URL は Discord のチャンネル設定 → 連携サービス → Webhook から取得してください。"
            ),
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
            font=("Segoe UI", 9),
        ).pack(anchor=tk.W, pady=(0, 8))

        ttk.Checkbutton(
            overview,
            text="Discord 通知を有効にする",
            variable=self.discord_notify_enabled_var,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W, pady=(0, 8))

        url_row = ttk.Frame(overview, style="Card.TFrame")
        url_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(url_row, text="Webhook URL", style="Card.TLabel", width=12).pack(side=tk.LEFT, anchor=tk.N)
        self.discord_webhook_entry = ttk.Entry(
            url_row,
            textvariable=self.discord_webhook_var,
            style="Dark.TEntry",
            font=("Segoe UI", 9),
        )
        self.discord_webhook_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        mention_row = ttk.Frame(overview, style="Card.TFrame")
        mention_row.pack(fill=tk.X, pady=(8, 4))
        ttk.Label(mention_row, text="メンション", style="Card.TLabel", width=12).pack(side=tk.LEFT, anchor=tk.N)
        mention_body = ttk.Frame(mention_row, style="Card.TFrame")
        mention_body.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Entry(
            mention_body,
            textvariable=self.discord_mention_users_var,
            style="Dark.TEntry",
            font=("Segoe UI", 9),
        ).pack(fill=tk.X)
        ttk.Label(
            mention_body,
            text=(
                "通知時にメンションする Discord ユーザー ID（カンマ区切り、任意）。"
                "ユーザー設定 → 詳細設定 → 開発者モード を ON にし、"
                "ユーザー名を右クリック → ID をコピー"
            ),
            style="CardDim.TLabel",
            wraplength=520,
            justify=tk.LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(4, 0))

        ttk.Checkbutton(
            mention_body,
            text="@everyone をメンションする",
            variable=self.discord_mention_everyone_var,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W, pady=(6, 0))
        ttk.Checkbutton(
            mention_body,
            text="通知時にゲーム画面のスクショを添付する",
            variable=self.discord_attach_screenshot_var,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W, pady=(4, 0))

        stuck_row = ttk.Frame(overview, style="Card.TFrame")
        stuck_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(stuck_row, text="停滞通知", style="Card.TLabel", width=12).pack(side=tk.LEFT)
        stuck_body = ttk.Frame(stuck_row, style="Card.TFrame")
        stuck_body.pack(side=tk.LEFT, fill=tk.X, expand=True)
        stuck_input = ttk.Frame(stuck_body, style="Card.TFrame")
        stuck_input.pack(fill=tk.X)
        ttk.Spinbox(
            stuck_input,
            from_=0,
            to=999,
            textvariable=self.discord_stuck_repeat_var,
            width=6,
            style="Dark.TSpinbox",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Label(
            stuck_input,
            text="回連続で同じフェーズが進まないとき通知（0=無効）",
            style="CardDim.TLabel",
            font=("Segoe UI", 8),
        ).pack(side=tk.LEFT)
        ttk.Label(
            stuck_body,
            text="例: ① に戻れない状態が続く、⑥ からの復帰に失敗し続ける、など",
            style="CardDim.TLabel",
            wraplength=520,
            justify=tk.LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(4, 0))

        btn_row = ttk.Frame(overview, style="Card.TFrame")
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="テスト送信", command=self._on_discord_test).pack(side=tk.LEFT)

        ttk.Label(
            scroll_body,
            text="※ Webhook URL は config.yaml に保存されます。他人に見せないでください。",
            style="Dim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(4, 0))

    def _on_discord_test(self) -> None:
        url = self.discord_webhook_var.get().strip()
        validation = validate_webhook_url(url)
        if validation:
            messagebox.showwarning("Discord 通知", validation, parent=self)
            return
        ok, message = send_discord_test(
            url,
            mention_user_ids=parse_mention_user_ids(self.discord_mention_users_var.get()),
            mention_everyone=bool(self.discord_mention_everyone_var.get()),
            attach_screenshot=bool(self.discord_attach_screenshot_var.get()),
            config=self._get_form_config(),
        )
        if ok:
            messagebox.showinfo("Discord 通知", message, parent=self)
            self._append_log(message)
        else:
            messagebox.showerror("Discord 通知", message, parent=self)
            self._append_log(message, CHANNEL_DETAIL)

    @staticmethod
    def _text_display_width(text: str) -> int:
        """tk Menubutton の width（半角単位）の目安。"""
        width = 0
        for ch in text:
            width += 2 if ord(ch) > 0xFF else 1
        return width

    @classmethod
    def _option_menu_width(cls, *labels: str, padding: int = 2) -> int:
        if not labels:
            return 24
        return max(cls._text_display_width(label) for label in labels) + padding

    def _style_option_menu(self, menu: tk.OptionMenu, *, width: int) -> None:
        menu.configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            width=width,
        )
        menu["menu"].configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 9),
        )

    def _build_scrollable_tab(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scroll_body = ttk.Frame(canvas)
        scroll_body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas_window = canvas.create_window((0, 0), window=scroll_body, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_canvas_configure(event: tk.Event) -> None:
            canvas.itemconfigure(canvas_window, width=event.width)

        canvas.bind("<Configure>", _on_canvas_configure)

        def _on_mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_wheel(_event: tk.Event | None = None) -> None:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_wheel(_event: tk.Event | None = None) -> None:
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        return scroll_body

    def _add_numeric_setting_rows(
        self,
        parent: ttk.Frame,
        fields: tuple[SettingField, ...],
        vars_map: dict[str, tk.Variable],
    ) -> None:
        grid = ttk.Frame(parent, style="Card.TFrame")
        grid.pack(fill=tk.X)

        current_group = ""
        row = 0
        for field in fields:
            if field.group != current_group:
                current_group = field.group
                tk.Label(
                    grid,
                    text=current_group,
                    fg=COLORS["accent"],
                    bg=COLORS["surface"],
                    font=("Segoe UI", 9, "bold"),
                ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(6 if row else 0, 2))
                row += 1

            ttk.Label(
                grid,
                text=field.label,
                style="Card.TLabel",
                wraplength=240,
                justify=tk.LEFT,
                font=("Segoe UI", 9),
            ).grid(row=row, column=0, sticky=tk.W, pady=2, padx=(0, 8))

            var = vars_map[field.key]
            if field.value_type == "int":
                widget = ttk.Spinbox(
                    grid,
                    from_=int(field.vmin),
                    to=int(field.vmax),
                    increment=int(field.increment),
                    textvariable=var,
                    width=7,
                    style="Dark.TSpinbox",
                    font=("Segoe UI", 9),
                )
            else:
                widget = ttk.Spinbox(
                    grid,
                    from_=field.vmin,
                    to=field.vmax,
                    increment=field.increment,
                    textvariable=var,
                    width=7,
                    style="Dark.TSpinbox",
                    font=("Segoe UI", 9),
                )
            widget.grid(row=row, column=1, sticky=tk.W, pady=2)
            row += 1
            tk.Label(
                grid,
                text=f"  {field.help}",
                fg=COLORS["text_dim"],
                bg=COLORS["surface"],
                font=("Segoe UI", 8),
                wraplength=430,
                justify=tk.LEFT,
            ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(0, 3))
            row += 1

    def _add_option_row(
        self,
        parent: ttk.Frame,
        label: str,
        variable: tk.StringVar,
        options: tuple[tuple[str, str], ...],
        *,
        menu_width: int = 28,
    ) -> None:
        row_frame = ttk.Frame(parent, style="Card.TFrame")
        row_frame.pack(fill=tk.X, pady=3)
        ttk.Label(
            row_frame,
            text=label,
            style="Card.TLabel",
            width=14,
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT)
        option_menu = tk.OptionMenu(row_frame, variable, *[opt_label for _opt_value, opt_label in options])
        self._style_option_menu(option_menu, width=menu_width)
        option_menu.pack(side=tk.LEFT)

    def _build_timing_tab(self, parent: ttk.Frame) -> None:
        scroll_body = self._build_scrollable_tab(parent)
        timing_card = self._card(scroll_body, "場面ごとの待ち時間", compact=True)
        self._add_numeric_setting_rows(timing_card, RETRY_TIMING_FIELDS, self._timing_vars)

    def _build_matching_tab(self, parent: ttk.Frame) -> None:
        scroll_body = self._build_scrollable_tab(parent)
        matching_card = self._card(scroll_body, "画像認識の感度", compact=True)
        self._add_numeric_setting_rows(matching_card, MATCHING_FIELDS, self._matching_vars)

        mods_card = self._card(scroll_body, "② MODS 画面", compact=True)
        self._add_option_row(mods_card, "検出方式", self.mods_detect_mode_var, MODS_DETECT_MODE_OPTIONS, menu_width=24)
        self._add_option_row(
            mods_card,
            "比較範囲",
            self.mods_screen_region_var,
            MODS_SCREEN_REGION_OPTIONS,
            menu_width=24,
        )
        ttk.Checkbutton(
            mods_card,
            text="② REQUIRED MODS をスキップ（① の直後に ③ ログイン待機へ）",
            variable=self.skip_required_mods_var,
            style="Dark.TCheckbutton",
        ).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(
            mods_card,
            text="MODS 不要のサーバー向け。有効にすると MODS 画面の検出・JOIN を行いません。",
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(4, 0))

        window_card = self._card(scroll_body, "ウィンドウ", compact=True)
        title_row = ttk.Frame(window_card, style="Card.TFrame")
        title_row.pack(fill=tk.X, pady=2)
        ttk.Label(title_row, text="タイトル", style="Card.TLabel", width=10).pack(side=tk.LEFT)
        ttk.Entry(
            title_row,
            textvariable=self.window_title_var,
            width=42,
            style="Dark.TEntry",
            font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, ipady=1)

        flags_row = ttk.Frame(window_card, style="Card.TFrame")
        flags_row.pack(fill=tk.X, pady=2)
        ttk.Checkbutton(
            flags_row,
            text="操作前に ARK を前面に出す",
            variable=self.bring_to_front_var,
            style="Dark.TCheckbutton",
        ).pack(side=tk.LEFT, padx=(0, 16))
        ttk.Checkbutton(
            flags_row,
            text="クリック位置を表示",
            variable=self.show_click_indicator_var,
            style="Dark.TCheckbutton",
        ).pack(side=tk.LEFT)
        ttk.Button(
            flags_row,
            text="プレビュー",
            command=self._preview_click_indicator,
        ).pack(side=tk.LEFT, padx=(8, 0))

    def _build_coordinates_tab(self, parent: ttk.Frame) -> None:
        scroll_body = self._build_scrollable_tab(parent)

        mode_card = self._card(scroll_body, "クリック方式", compact=True)
        ttk.Label(mode_card, text="モード", style="Card.TLabel", font=("Segoe UI", 9)).pack(anchor=tk.W)
        click_menu = tk.OptionMenu(
            mode_card,
            self.click_mode_var,
            *[label for _value, label in CLICK_MODE_OPTIONS],
        )
        self._style_option_menu(
            click_menu,
            width=self._option_menu_width(*(label for _value, label in CLICK_MODE_OPTIONS)),
        )
        click_menu.pack(anchor=tk.W, fill=tk.X, pady=(4, 0))

        coord_card = self._card(scroll_body, "クリック座標（％）", compact=True)
        grid = ttk.Frame(coord_card, style="Card.TFrame")
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="操作", style="Card.TLabel", font=("Segoe UI", 9)).grid(row=0, column=0, sticky=tk.W, pady=2)
        ttk.Label(grid, text="X", style="Card.TLabel", font=("Segoe UI", 9)).grid(row=0, column=1, sticky=tk.W, padx=(8, 4))
        ttk.Label(grid, text="Y", style="Card.TLabel", font=("Segoe UI", 9)).grid(row=0, column=2, sticky=tk.W, padx=(8, 4))
        ttk.Label(grid, text="", style="Card.TLabel").grid(row=0, column=3, sticky=tk.W, padx=(8, 0))

        for row, field in enumerate(UI_CLICK_FIELDS, start=1):
            label = field.label + ("" if field.required else "（任意）")
            ttk.Label(grid, text=label, style="Card.TLabel", wraplength=180, font=("Segoe UI", 9)).grid(
                row=row, column=0, sticky=tk.W, pady=2, padx=(0, 8),
            )
            x_var, y_var = self._ui_coord_vars[field.key]
            ttk.Spinbox(
                grid, from_=0.0, to=100.0, increment=0.5, textvariable=x_var, width=7,
                style="Dark.TSpinbox", font=("Segoe UI", 9),
            ).grid(row=row, column=1, sticky=tk.W)
            ttk.Spinbox(
                grid, from_=0.0, to=100.0, increment=0.5, textvariable=y_var, width=7,
                style="Dark.TSpinbox", font=("Segoe UI", 9),
            ).grid(row=row, column=2, sticky=tk.W, padx=(8, 0))
            ttk.Button(
                grid,
                text="画面で設定",
                command=lambda key=field.key, op_label=field.label: self._on_pick_ui_coordinate(key, op_label),
            ).grid(row=row, column=3, sticky=tk.W, padx=(8, 0))

        preview_card = self._card(scroll_body, None, compact=True)
        ttk.Button(
            preview_card,
            text="座標プレビューを表示",
            command=self._on_preview_coordinates,
        ).pack(anchor=tk.W)

    def _collect_ui_coords(self) -> dict[str, dict[str, float]]:
        ui: dict[str, dict[str, float]] = {}
        for field in UI_CLICK_FIELDS:
            x_var, y_var = self._ui_coord_vars[field.key]
            ui[field.key] = {
                "x_percent": float(x_var.get()),
                "y_percent": float(y_var.get()),
            }
        return ui

    def _on_preview_coordinates(self) -> None:
        capture_settings = self._get_capture_settings()
        points: list[tuple[str, float, float]] = []
        for field in UI_CLICK_FIELDS:
            x_var, y_var = self._ui_coord_vars[field.key]
            points.append((field.label, float(x_var.get()), float(y_var.get())))
        try:
            show_coordinate_preview(
                self,
                capture_settings=capture_settings,
                points=points,
                bring_to_front=bool(self.bring_to_front_var.get()),
            )
        except WindowNotFoundError as exc:
            messagebox.showerror("ウィンドウ未検出", str(exc), parent=self)

    def _on_pick_ui_coordinate(self, key: str, label: str) -> None:
        if self._running:
            messagebox.showwarning("実行中", "自動ログイン実行中は座標を設定できません。", parent=self)
            return

        x_var, y_var = self._ui_coord_vars[key]

        def on_pick(x_percent: float, y_percent: float) -> None:
            x_var.set(x_percent)
            y_var.set(y_percent)
            self._append_log(f"{label} の座標を設定しました ({x_percent:.1f}%, {y_percent:.1f}%)")

        try:
            pick_coordinate_on_screen(
                self,
                capture_settings=self._get_capture_settings(),
                label=label,
                on_pick=on_pick,
                bring_to_front=bool(self.bring_to_front_var.get()),
            )
        except WindowNotFoundError as exc:
            messagebox.showerror("ウィンドウ未検出", str(exc), parent=self)

    def _append_log(self, message: str, channel: str = CHANNEL_USER) -> None:
        widget = self.user_log_text if channel == CHANNEL_USER else self.detail_log_text
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, message + "\n")
        line_count = int(widget.index("end-1c").split(".")[0])
        if line_count > 2000:
            widget.delete("1.0", f"{line_count - 2000 + 1}.0")
        widget.see(tk.END)
        widget.configure(state=tk.DISABLED)

    def _set_status(self, text: str, color: str = COLORS["text"]) -> None:
        self.status_label.configure(text=text, foreground=color)

    def _update_stats(self, attempts: int, failures: int, elapsed: float) -> None:
        self.attempts_label.configure(text=f"試行: {attempts}")
        self.failures_label.configure(text=f"失敗: {failures}")
        self.elapsed_label.configure(text=f"経過: {elapsed:.0f}秒")

    def _load_settings(self) -> None:
        try:
            self._apply_config_to_form(load_config())
        except FileNotFoundError:
            try:
                self._apply_config_to_form(load_default_config())
                self._append_log("設定ファイルが見つかりません。初期値を表示しています。")
            except FileNotFoundError:
                self._append_log("設定ファイルが見つかりません。セットアップを実行してください。")
                return
        except (ValueError, TypeError) as exc:
            self._append_log(f"設定ファイルを読み込めません: {exc}")
            restored = messagebox.askyesno(
                "設定ファイルのエラー",
                f"{exc}\n\n正常なバックアップがあれば復元しますか？\n"
                "「いいえ」では元ファイルを変更せず初期値を表示します。",
                parent=self,
            )
            if restored:
                try:
                    if restore_config_backup():
                        self._apply_config_to_form(load_config())
                        self._append_log("config.yaml.bak から設定を復元しました")
                        self._mark_config_saved()
                        self._refresh_chrome()
                        return
                except Exception as restore_exc:
                    self._append_log(f"バックアップ復元に失敗しました: {restore_exc}")
            try:
                self._apply_config_to_form(load_default_config())
            except Exception:
                return
        self._mark_config_saved()
        self._refresh_chrome()

    def _apply_config_to_form(self, config: dict) -> None:
        self._config = copy.deepcopy(config)

        retry = self._config.get("retry", {})
        display = self._config.get("display", {})
        matching = self._config.get("matching", {})
        window = self._config.get("window", {})
        ui = self._config.get("ui", {})

        monitor_index = int(display.get("monitor_index", 1))
        label = self._monitor_index_to_label.get(monitor_index)
        if label:
            self.monitor_var.set(label)

        capture_mode = display.get("capture_mode", DEFAULT_CAPTURE_MODE)
        self._capture_mode_trace_guard = True
        try:
            self.capture_mode_var.set(
                CAPTURE_MODE_VALUE_TO_LABEL.get(capture_mode, CAPTURE_MODE_OPTIONS[0][1])
            )
        finally:
            self._capture_mode_trace_guard = False
        self._disk_capture_mode = capture_mode

        self.max_attempts_var.set(retry.get("max_attempts", 0))
        self.delay_var.set(retry.get("delay_seconds", 3.0))

        for field in RETRY_TIMING_FIELDS:
            value = retry.get(field.key, field.default)
            if field.value_type == "int":
                self._timing_vars[field.key].set(int(value))
            else:
                self._timing_vars[field.key].set(float(value))

        for field in MATCHING_FIELDS:
            fallback = matching.get("threshold", field.default) if field.key == "button_threshold" else field.default
            value = matching.get(field.key, fallback)
            self._matching_vars[field.key].set(float(value))

        click_mode = matching.get("click_mode", "image")
        self.click_mode_var.set(CLICK_MODE_VALUE_TO_LABEL.get(click_mode, CLICK_MODE_OPTIONS[0][1]))

        mods_detect_mode = matching.get("mods_detect_mode", "hybrid")
        self.mods_detect_mode_var.set(
            MODS_DETECT_MODE_VALUE_TO_LABEL.get(mods_detect_mode, MODS_DETECT_MODE_OPTIONS[0][1])
        )
        mods_screen_region = matching.get("mods_screen_region", "center")
        self.mods_screen_region_var.set(
            MODS_SCREEN_REGION_VALUE_TO_LABEL.get(mods_screen_region, MODS_SCREEN_REGION_OPTIONS[0][1])
        )
        self.skip_required_mods_var.set(bool(matching.get("skip_required_mods", False)))

        self.window_title_var.set(window.get("title_contains", "ARK: Survival Ascended"))
        self.bring_to_front_var.set(bool(window.get("bring_to_front", True)))
        self.show_click_indicator_var.set(bool(display.get("show_click_indicator", True)))

        for field in UI_CLICK_FIELDS:
            entry = ui.get(field.key, {})
            x_var, y_var = self._ui_coord_vars[field.key]
            x_var.set(float(entry.get("x_percent", field.default_x)))
            y_var.set(float(entry.get("y_percent", field.default_y)))

        notifications = self._config.get("notifications", {})
        discord = notifications.get("discord", {}) if isinstance(notifications, dict) else {}
        self.discord_notify_enabled_var.set(bool(discord.get("enabled", False)))
        self.discord_webhook_var.set(str(discord.get("webhook_url") or ""))
        mention_ids = parse_mention_user_ids(discord.get("mention_user_ids"))
        self.discord_mention_users_var.set(format_mention_user_ids_for_form(mention_ids))
        self.discord_mention_everyone_var.set(bool(discord.get("mention_everyone", False)))
        self.discord_attach_screenshot_var.set(
            bool(discord.get("attach_screenshot", DEFAULT_ATTACH_SCREENSHOT)),
        )
        try:
            self.discord_stuck_repeat_var.set(
                max(0, int(discord.get("stuck_repeat_threshold", DEFAULT_STUCK_REPEAT_THRESHOLD))),
            )
        except (TypeError, ValueError):
            self.discord_stuck_repeat_var.set(DEFAULT_STUCK_REPEAT_THRESHOLD)

    def _collect_notifications(self) -> dict:
        return {
            "discord": {
                "enabled": bool(self.discord_notify_enabled_var.get()),
                "webhook_url": self.discord_webhook_var.get().strip(),
                "mention_user_ids": list(parse_mention_user_ids(self.discord_mention_users_var.get())),
                "mention_everyone": bool(self.discord_mention_everyone_var.get()),
                "attach_screenshot": bool(self.discord_attach_screenshot_var.get()),
                "stuck_repeat_threshold": max(0, int(self.discord_stuck_repeat_var.get())),
            },
        }

    def _has_setup_templates(self) -> bool:
        return (app_root() / "templates" / "server_list.png").exists()

    def _is_coordinates_only_mode(self) -> bool:
        label = self.click_mode_var.get()
        return CLICK_MODE_LABEL_TO_VALUE.get(label, "image") == CLICK_MODE_COORDINATES_ONLY

    def _assess_readiness(self) -> tuple[bool, list[str]]:
        """開始可能かと、ユーザー向けの準備メッセージ一覧"""
        messages: list[str] = []
        ready = True

        if self._has_setup_templates():
            messages.append("✓ サーバー一覧の画面キャプチャ: 登録済み")
        else:
            messages.append("✗ サーバー一覧の画面キャプチャ: 未登録 →「セットアップ」を実行")
            ready = False

        if self._is_coordinates_only_mode():
            ui = UiPositions.from_dict(
                self._collect_ui_coords(),
                monitor_index=self._get_monitor_index(),
                capture_settings=self._get_capture_settings(),
            )
            if ui.is_configured(coordinates_only=True):
                messages.append("✓ 座標のみモード: 必須クリック座標は設定済み")
            else:
                missing = [
                    field.label
                    for field in UI_CLICK_FIELDS
                    if field.required and not ui.has_point(field.key)
                ]
                messages.append(
                    "✗ 座標のみモード: 未設定の座標があります →「クリック座標」タブで登録"
                )
                if missing:
                    messages.append(f"   未設定: {', '.join(missing)}")
                ready = False
        else:
            messages.append("✓ クリック方式: 画像優先（同梱ボタン画像を使用）")

        if self._has_unsaved_changes():
            messages.append("⚠ 設定が未保存です →「設定を保存」を推奨")

        return ready, messages

    def _refresh_readiness(self) -> None:
        ready, messages = self._assess_readiness()
        color = COLORS["success"] if ready else COLORS["warning"]
        self.readiness_label.configure(text="\n".join(messages), fg=color)
        if hasattr(self, "setup_btn"):
            if self._has_setup_templates():
                self.setup_btn.configure(text="セットアップ")
            else:
                self.setup_btn.configure(text="セットアップ（要）")
        if hasattr(self, "start_btn") and not self._running:
            self.start_btn.configure(state=tk.NORMAL if ready else tk.DISABLED)

    def _update_window_title(self) -> None:
        title = "ASA_Login"
        if self._has_unsaved_changes():
            title += " — 未保存"
        if self._running:
            title += " — 実行中"
        self.title(title)

    def _refresh_chrome(self) -> None:
        self._refresh_readiness()
        self._update_window_title()

    def _resolve_manual_path(self) -> Path | None:
        for candidate in (
            app_root() / "取扱説明書.html",
            app_root() / "docs" / "manual.html",
            bundle_root() / "docs" / "manual.html",
        ):
            if candidate.exists():
                return candidate
        return None

    def _on_open_manual(self) -> None:
        manual = self._resolve_manual_path()
        if manual is None:
            messagebox.showwarning(
                "取扱説明書",
                "取扱説明書が見つかりません。",
                parent=self,
            )
            return
        webbrowser.open(manual.resolve().as_uri())

    def _copy_diagnostics(self, report: PreflightReport | None = None) -> None:
        try:
            config = self._get_form_config()
            report = report or self._run_preflight_with_progress(config)
            if report is None:
                return
            text = report.to_support_text(config)
            self.clipboard_clear()
            self.clipboard_append(text)
            self.update_idletasks()
            self._append_log("診断情報をクリップボードへコピーしました")
            if report is not None:
                messagebox.showinfo(
                    "診断情報",
                    "開始前診断をクリップボードへコピーしました。",
                    parent=self,
                )
        except Exception as exc:
            messagebox.showerror("診断エラー", f"診断情報を作成できませんでした。\n{exc}", parent=self)

    def _game_window_title(self) -> str:
        return self.window_title_var.get().strip() or "ARK: Survival Ascended"

    def _enter_start_flow(self) -> None:
        """開始確認中は本体 UI を隠し、ARK が見えるようにする"""
        self.update_idletasks()
        self.withdraw()

    def _messagebox_while_hidden(self, func, *args, **kwargs):
        """開始確認中（本体非表示）でもメッセージを出し、本体を前面に戻さない"""
        hidden = not self.winfo_viewable()
        kwargs.setdefault("parent", self)
        result = func(*args, **kwargs)
        if hidden:
            self.withdraw()
            self.update_idletasks()
        return result

    def _exit_start_flow(self, *, behind_game: bool = False) -> None:
        """開始確認フロー終了後に本体 UI を復帰"""
        self.deiconify()
        self.update_idletasks()
        if behind_game:
            try:
                self.lower()
            except tk.TclError:
                pass
            self._apply_start_window_stack(None)
        else:
            self.lift()
            try:
                self.focus_force()
            except tk.TclError:
                pass

    def _apply_start_window_stack(self, dialog: tk.Misc | None = None) -> bool:
        """開始前確認・診断中: 確認ダイアログ > ARK > 本体 GUI"""
        from . import input_handler

        try:
            self.lower()
        except tk.TclError:
            pass
        self.update_idletasks()
        dialog_hwnd = input_handler.hwnd_from_tk(dialog) if dialog is not None else None
        ok = input_handler.stack_windows_for_start_capture(
            game_title_contains=self._game_window_title(),
            tool_hwnd=input_handler.hwnd_from_tk(self),
            dialog_hwnd=dialog_hwnd,
        )
        if not ok:
            self._append_log("ARK ウィンドウが見つからないため、前面整列をスキップしました")
        return ok

    def _run_preflight_with_progress(
        self,
        config: dict,
        *,
        use_cache: bool = True,
    ) -> PreflightReport | None:
        cache_key = self._config_snapshot(config)
        if use_cache and self._preflight_cache:
            saved_key, saved_at, saved_report = self._preflight_cache
            if saved_key == cache_key and time.monotonic() - saved_at < 5.0:
                return saved_report
        result_queue: queue.Queue = queue.Queue()
        dialog = tk.Toplevel(self)
        dialog.title("開始前診断")
        dialog.grab_set()
        dialog.resizable(False, False)
        ttk.Label(dialog, text="環境と画面を診断中…").pack(padx=30, pady=(20, 8))
        progress = ttk.Progressbar(dialog, mode="indeterminate", length=260)
        progress.pack(padx=30, pady=(0, 20))
        progress.start(12)
        dialog.update_idletasks()
        dialog.attributes("-topmost", True)
        self._apply_start_window_stack(dialog)

        from . import input_handler

        tool_hwnd = input_handler.hwnd_from_tk(self)
        dialog_hwnd = input_handler.hwnd_from_tk(dialog)
        game_title = self._game_window_title()
        bring_game = bool(config.get("window", {}).get("bring_to_front", True))

        def worker() -> None:
            try:
                input_handler.prepare_game_visible_for_capture(
                    game_title_contains=game_title,
                    tool_hwnd=tool_hwnd,
                    bring_game_to_front=bring_game,
                    dialog_hwnd=dialog_hwnd,
                )
                result_queue.put(("ok", run_preflight(config)))
            except Exception as exc:
                result_queue.put(("error", exc))

        def poll() -> None:
            try:
                kind, value = result_queue.get_nowait()
            except queue.Empty:
                dialog.after(50, poll)
                return
            try:
                dialog.attributes("-topmost", False)
            except tk.TclError:
                pass
            dialog.result = (kind, value)
            dialog.destroy()

        dialog.result = None
        threading.Thread(target=worker, daemon=True, name="Preflight").start()
        dialog.after(50, poll)
        self.wait_window(dialog)
        if not dialog.result:
            return None
        kind, value = dialog.result
        if kind == "error":
            raise value
        self._preflight_cache = (cache_key, time.monotonic(), value)
        return value

    def _confirm_environment_preflight(self) -> bool:
        self._preflight_cache = None
        try:
            report = self._run_preflight_with_progress(
                self._get_form_config(),
                use_cache=False,
            )
            if report is None:
                return False
        except Exception as exc:
            self._messagebox_while_hidden(
                messagebox.showerror,
                "開始前診断",
                f"診断を実行できませんでした。\n{exc}",
            )
            return False

        detail_log.info("\n%s", report.to_text())
        if not report.can_start:
            if self._messagebox_while_hidden(
                messagebox.askyesno,
                "開始できません",
                report.to_text()
                + "\n\n診断情報をコピーしますか？\n"
                "必須キャプチャがない場合は「セットアップ」を実行してください。",
            ):
                self._copy_diagnostics(report)
            return False
        if report.has_warnings:
            return self._messagebox_while_hidden(
                messagebox.askyesno,
                "環境差を検出しました",
                report.to_text()
                + "\n\n再セットアップを推奨します。\n"
                "内容を確認したうえで、このまま開始しますか？",
            )
        self._append_log("開始前診断: 問題は見つかりませんでした")
        return True

    def _preflight_start(self) -> bool:
        if not self._has_setup_templates():
            if messagebox.askyesno(
                "セットアップが必要です",
                "サーバー一覧の画面キャプチャが未登録です。\n"
                "自動ログインを開始する前にセットアップが必要です。\n\n"
                "今すぐセットアップを開きますか？",
                parent=self,
            ):
                self._on_setup()
            return False

        if self._is_coordinates_only_mode():
            ui = UiPositions.from_dict(
                self._collect_ui_coords(),
                monitor_index=self._get_monitor_index(),
                capture_settings=self._get_capture_settings(),
            )
            if not ui.is_configured(coordinates_only=True):
                messagebox.showwarning(
                    "座標が未設定です",
                    "座標のみモードでは、① JOIN / ④ BACK / ⑤ JOIN GAME の座標が必要です。\n"
                    "（③-A / ⑥ は Enter キーで確定するため座標は不要です。）\n\n"
                    "「クリック座標」タブで設定するか、セットアップで登録してください。",
                    parent=self,
                )
                return False

        if self._has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "未保存の設定",
                "設定が保存されていません。\n\n"
                "開始前に保存しますか？\n"
                "（いいえ = 未保存のまま開始、キャンセル = 中止）",
                parent=self,
            )
            if answer is None:
                return False
            if answer:
                try:
                    self._persist_config()
                except Exception as exc:
                    messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{exc}", parent=self)
                    return False

        return True

    def _show_startup_notices(self) -> None:
        if not self._has_setup_templates():
            if messagebox.askyesno(
                "初回セットアップ",
                "サーバー一覧の画面キャプチャがまだ登録されていません。\n\n"
                "初回は「セットアップ」（最小モード）で ① サーバー一覧だけ登録すれば動作します。\n\n"
                "今すぐセットアップを開きますか？",
                parent=self,
            ):
                self._on_setup()
            else:
                self._append_log("セットアップ未完了です。「セットアップ（要）」から登録してください。")
            self._refresh_chrome()
            return
        version = int(self._config.get("meta", {}).get("setup_capture_version", 0))
        if version >= SETUP_CAPTURE_VERSION:
            return
        messagebox.showinfo(
            "セットアップ画像の再登録を推奨",
            "以前のバージョンで保存した画面キャプチャが検出されました。\n\n"
            "色の保存方法が修正されたため、templates/ の画像が実画面と色味が大きく"
            "違う場合は「セットアップ」から再キャプチャしてください。\n\n"
            "再セットアップ後はこの通知は表示されません。",
            parent=self,
        )
        self._append_log(
            "以前のセットアップ画像を検出しました。色ずれがある場合は再セットアップを推奨します。"
        )
        self._refresh_chrome()

    def _on_capture_mode_changed(self, *_args) -> None:
        if self._capture_mode_trace_guard:
            return
        new_mode = CAPTURE_MODE_LABEL_TO_VALUE.get(
            self.capture_mode_var.get(),
            DEFAULT_CAPTURE_MODE,
        )
        if new_mode == self._disk_capture_mode or not self._has_setup_templates():
            return
        current_label = CAPTURE_MODE_VALUE_TO_LABEL.get(new_mode, new_mode)
        saved_label = CAPTURE_MODE_VALUE_TO_LABEL.get(self._disk_capture_mode, self._disk_capture_mode)
        messagebox.showwarning(
            "キャプチャ範囲の変更",
            f"キャプチャ範囲を「{current_label}」に変更しました。\n"
            f"（保存済み: {saved_label}）\n\n"
            "座標と画面テンプレートの基準が変わるため、"
            "「セットアップ」から再キャプチャすることを推奨します。\n\n"
            "変更を確定するには「設定を保存」を押してください。",
            parent=self,
        )
        self._append_log(
            f"キャプチャ範囲を変更しました（{current_label}）。再セットアップを推奨します。"
        )

    def _confirm_capture_mode_matches_setup(self, capture_settings: CaptureSettings) -> bool:
        setup_mode = self._config.get("meta", {}).get("setup_capture_mode")
        if not setup_mode or not self._has_setup_templates():
            return True
        if capture_settings.mode == setup_mode:
            return True
        current_label = CAPTURE_MODE_VALUE_TO_LABEL.get(capture_settings.mode, capture_settings.mode)
        setup_label = CAPTURE_MODE_VALUE_TO_LABEL.get(setup_mode, setup_mode)
        return self._messagebox_while_hidden(
            messagebox.askyesno,
            "キャプチャ範囲がセットアップ時と異なります",
            f"現在: {current_label}\nセットアップ時: {setup_label}\n\n"
            "このまま開始すると画面判定やクリック位置がずれる可能性があります。\n"
            "「セットアップ」の再実行を推奨します。\n\n"
            "このまま開始しますか？",
        )

    def _on_reset_defaults(self) -> None:
        if self._running:
            messagebox.showwarning(
                "実行中",
                "自動ログイン実行中は設定を変更できません。",
                parent=self,
            )
            return

        if not messagebox.askyesno(
            "初期値に戻す",
            "config.yaml の設定を config.example.yaml の初期値に戻します。\n\n"
            "• templates/ の画像ファイルは削除されません\n"
            "• セットアップで登録した座標も初期値に戻ります\n\n"
            "よろしいですか？",
            parent=self,
        ):
            return

        try:
            self._apply_config_to_form(load_default_config())
            self._persist_config()
            self._append_log("設定を初期値に戻しました")
            self._refresh_chrome()
            messagebox.showinfo(
                "完了",
                "設定を初期値に戻し、config.yaml に保存しました。\n"
                "templates/ の画像はそのまま残っています。",
                parent=self,
            )
        except Exception as exc:
            messagebox.showerror("エラー", f"初期値への復元に失敗しました:\n{exc}", parent=self)

    def _on_import_legacy_settings(self) -> None:
        if self._running:
            messagebox.showwarning(
                "旧版から引き継ぎ",
                "自動ログイン実行中は引き継ぎできません。",
                parent=self,
            )
            return

        if self._has_unsaved_changes():
            proceed = messagebox.askyesno(
                "旧版から引き継ぎ",
                "未保存の設定があります。\n"
                "引き継ぎを実行すると、ディスク上の config.yaml が上書きされ、"
                "フォームの未保存内容は失われます。\n\n続行しますか？",
                parent=self,
            )
            if not proceed:
                return

        exe_path = filedialog.askopenfilename(
            title="旧版 ASA_Login.exe を選択",
            filetypes=[("実行ファイル", "*.exe"), ("すべて", "*.*")],
        )
        if not exe_path:
            return

        try:
            preview = preview_legacy_import(exe_path)
        except (FileNotFoundError, ValueError) as exc:
            messagebox.showerror("旧版から引き継ぎ", str(exc), parent=self)
            return

        if not messagebox.askyesno(
            "旧版から引き継ぎ",
            format_migration_confirm_message(preview),
            parent=self,
        ):
            return

        try:
            result = import_from_legacy_exe(exe_path)
            self._apply_config_to_form(load_config())
            self._mark_config_saved()
            self._refresh_chrome()
            summary = format_migration_summary(result)
            self._append_log("旧版から引き継ぎました")
            self._append_log(summary)
            self._append_log(format_migration_summary_detail(result), CHANNEL_DETAIL)
            messagebox.showinfo("引き継ぎ完了", summary, parent=self)
        except Exception as exc:
            messagebox.showerror("旧版から引き継ぎ", f"引き継ぎに失敗しました:\n{exc}", parent=self)

    def _config_snapshot(self, config: dict) -> str:
        return json.dumps(config, sort_keys=True, ensure_ascii=False, default=str)

    def _mark_config_saved(self) -> None:
        self._saved_config_snapshot = self._config_snapshot(self._get_form_config())

    def _has_unsaved_changes(self) -> bool:
        if self._saved_config_snapshot is None:
            return False
        return self._config_snapshot(self._get_form_config()) != self._saved_config_snapshot

    def _persist_config(self) -> None:
        self._config = self._get_form_config()
        save_config(self._config)
        self._mark_config_saved()
        display = self._config.get("display", {})
        self._disk_capture_mode = display.get("capture_mode", DEFAULT_CAPTURE_MODE)

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askokcancel(
                "実行中",
                "自動ログインが実行中です。停止して終了しますか？",
                parent=self,
            ):
                return
            self._on_stop()

        if self._has_unsaved_changes():
            answer = messagebox.askyesnocancel(
                "未保存の設定",
                "設定が保存されていません。終了前に保存しますか？",
                parent=self,
            )
            if answer is None:
                return
            if answer:
                try:
                    self._persist_config()
                except Exception as exc:
                    messagebox.showerror(
                        "エラー",
                        f"設定の保存に失敗しました:\n{exc}",
                        parent=self,
                    )
                    return

        self.destroy()

    def _collect_retry_timing(self) -> dict[str, float | int]:
        timing: dict[str, float | int] = {}
        for field in RETRY_TIMING_FIELDS:
            if field.value_type == "int":
                timing[field.key] = int(self._timing_vars[field.key].get())
            else:
                timing[field.key] = float(self._timing_vars[field.key].get())
        return timing

    def _collect_matching(self) -> dict[str, float | str]:
        matching: dict[str, float | str] = {}
        for field in MATCHING_FIELDS:
            matching[field.key] = float(self._matching_vars[field.key].get())
        click_label = self.click_mode_var.get()
        matching["click_mode"] = CLICK_MODE_LABEL_TO_VALUE.get(click_label, "image")
        mods_detect_label = self.mods_detect_mode_var.get()
        matching["mods_detect_mode"] = MODS_DETECT_MODE_LABEL_TO_VALUE.get(
            mods_detect_label,
            "hybrid",
        )
        mods_region_label = self.mods_screen_region_var.get()
        matching["mods_screen_region"] = MODS_SCREEN_REGION_LABEL_TO_VALUE.get(
            mods_region_label,
            "center",
        )
        matching["skip_required_mods"] = bool(self.skip_required_mods_var.get())
        return matching

    def _collect_window(self) -> dict[str, str | bool]:
        return {
            "title_contains": self.window_title_var.get().strip() or "ARK: Survival Ascended",
            "bring_to_front": bool(self.bring_to_front_var.get()),
        }

    def _get_monitor_index(self) -> int:
        return self._monitor_label_to_index.get(self.monitor_var.get(), 1)

    def _get_capture_settings(self) -> CaptureSettings:
        capture_label = self.capture_mode_var.get()
        return CaptureSettings(
            mode=CAPTURE_MODE_LABEL_TO_VALUE.get(capture_label, "window"),
            monitor_index=self._get_monitor_index(),
            window_title=self.window_title_var.get().strip() or "ARK: Survival Ascended",
        )

    def _get_form_config(self) -> dict:
        capture_label = self.capture_mode_var.get()
        config = apply_ui_overrides(
            self._config,
            max_attempts=int(self.max_attempts_var.get()),
            delay_seconds=float(self.delay_var.get()),
            monitor_index=self._get_monitor_index(),
            capture_mode=CAPTURE_MODE_LABEL_TO_VALUE.get(capture_label, "window"),
            show_click_indicator=bool(self.show_click_indicator_var.get()),
            retry_timing=self._collect_retry_timing(),
            matching_overrides=self._collect_matching(),
            window_overrides=self._collect_window(),
            ui_overrides=self._collect_ui_coords(),
        )
        config["notifications"] = self._collect_notifications()
        return config

    def _on_save(self) -> None:
        try:
            self._persist_config()
            self._append_log("設定を config.yaml に保存しました")
            self._refresh_chrome()
            messagebox.showinfo("保存完了", "設定を保存しました。")
        except Exception as exc:
            messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{exc}")

    def _on_setup(self) -> None:
        if self._running:
            messagebox.showwarning(
                "実行中",
                "自動ログイン実行中はセットアップできません。",
                parent=self,
            )
            return

        if self._has_unsaved_changes():
            if not messagebox.askyesno(
                "未保存の設定",
                "GUI に未保存の変更があります。\n\n"
                "セットアップ完了時に、現在のフォーム内容とセットアップ結果を\n"
                "まとめて config.yaml に保存します。続行しますか？",
                parent=self,
            ):
                return

        default_monitor = self._get_monitor_index()
        capture_settings = self._get_capture_settings()
        base_config = self._get_form_config()

        def on_complete() -> None:
            self._load_settings()
            self._mark_config_saved()
            self._refresh_chrome()
            self._append_log("セットアップが完了しました（設定も保存済み）")

        run_wizard_gui(
            self,
            default_monitor_index=default_monitor,
            capture_settings=capture_settings,
            base_config=base_config,
            on_complete=on_complete,
        )

    def _on_state_change(self, state: LoginState, stats) -> None:
        self._log_queue.put(("state", state, stats))

    def _on_start(self) -> None:
        if self._running:
            return

        if not self._preflight_start():
            return

        automation_started = False
        self._enter_start_flow()
        try:
            dialog = StartReadyDialog(self)
            self._apply_start_window_stack(dialog)
            self.wait_window(dialog)
            if not dialog.confirmed:
                return

            if not self._confirm_environment_preflight():
                return

            capture_settings = self._get_capture_settings()
            if capture_settings.mode == "window":
                try:
                    resolve_capture_region(capture_settings, strict_window=True)
                except WindowNotFoundError as exc:
                    self._messagebox_while_hidden(
                        messagebox.showerror,
                        "ウィンドウ未検出",
                        str(exc),
                    )
                    return

            if not self._confirm_capture_mode_matches_setup(capture_settings):
                return

            try:
                self._start_config = self._get_form_config()
                self._automator = build_automator(
                    self._start_config,
                    on_state_change=self._on_state_change,
                )
            except Exception as exc:
                self._messagebox_while_hidden(messagebox.showerror, "エラー", str(exc))
                return

            self._exit_start_flow(behind_game=True)
            automation_started = True

            self._running = True
            self.start_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.NORMAL)
            self._set_status("準備中...", COLORS["warning"])

            self._worker = threading.Thread(target=self._run_worker, daemon=True)
            self._worker.start()
        finally:
            if not automation_started:
                self._exit_start_flow()

    def _on_stop(self) -> None:
        self._running = False
        if self._automator:
            self._automator.stop()
        self._append_log("停止を要求しました...")

    def _run_worker(self) -> None:
        setup_logging(self._start_config, self._log_queue)
        loop_ran = False
        result: LoginState | None = None
        error_msg: str | None = None
        try:
            countdown = max(0, int(self._start_config.get("retry", {}).get("start_countdown_seconds", 3)))
            for i in range(countdown, 0, -1):
                if not self._running:
                    return
                self._log_queue.put(("countdown", i))
                time.sleep(1)

            if not self._running:
                return

            loop_ran = True
            result = self._automator.run()
            self._log_queue.put(("result", result))
        except WindowNotFoundError as exc:
            from .app_logging import detail_log

            loop_ran = True
            error_msg = str(exc)
            detail_log.error("ARK ウィンドウが見つかりません: %s", exc)
            user_log.error("ARK ウィンドウが見つかりません")
            self._log_queue.put(("error", str(exc)))
        except Exception as exc:
            from .app_logging import detail_log

            loop_ran = True
            error_msg = str(exc)
            detail_log.exception("実行中にエラーが発生しました")
            user_log.error("エラーが発生しました: %s", exc)
            self._log_queue.put(("error", str(exc)))
        finally:
            if loop_ran:
                stats = self._automator.stats if self._automator else None
                notify_loop_finished(
                    self._start_config,
                    result=result,
                    stats=stats,
                    error=error_msg,
                    vision=self._automator.vision if self._automator else None,
                )
            teardown_logging(close_files=False)
            self._log_queue.put(("done", None))

    def _poll_queue(self) -> None:
        try:
            while True:
                item = self._log_queue.get_nowait()
                kind = item[0]

                if kind == "log":
                    self._append_log(item[2], item[1])
                elif kind == "countdown":
                    self._set_status(f"{item[1]}秒後に開始...", COLORS["warning"])
                elif kind == "state":
                    _, state, stats = item
                    label = STATE_LABELS.get(state, str(state))
                    color = COLORS["text"]
                    if state == LoginState.SUCCESS:
                        color = COLORS["success"]
                    elif state in (LoginState.FAILED, LoginState.HANDLING_FAILURE):
                        color = COLORS["warning"]
                    elif state == LoginState.STOPPED:
                        color = COLORS["idle"]
                    self._set_status(label, color)
                    self._update_stats(stats.attempts, stats.failures, stats.elapsed_seconds)
                elif kind == "result":
                    result = item[1]
                    if result == LoginState.SUCCESS:
                        self._set_status("ログイン成功！", COLORS["success"])
                        messagebox.showinfo("成功", "サーバーへのログインに成功しました！")
                    elif result == LoginState.FAILED:
                        self._set_status("ログイン失敗", COLORS["danger"])
                        messagebox.showwarning("失敗", "リトライ上限に達しました。")
                elif kind == "error":
                    self._set_status("エラー", COLORS["danger"])
                    messagebox.showerror("エラー", item[1])
                elif kind == "done":
                    self._running = False
                    self.start_btn.configure(state=tk.NORMAL)
                    self.stop_btn.configure(state=tk.DISABLED)
                    if self.status_label.cget("text") not in ("ログイン成功！", "ログイン失敗", "エラー"):
                        self._set_status("待機中", COLORS["idle"])
        except queue.Empty:
            pass

        if not self._running:
            self._refresh_chrome()

        self.after(100, self._poll_queue)


def run_gui() -> None:
    prepare_runtime()
    try:
        setup_logging(load_config())
    except (FileNotFoundError, ValueError, TypeError):
        setup_logging()

    app = LoginApp()
    app.mainloop()
