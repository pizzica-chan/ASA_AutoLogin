"""ASA_Login グラフィカルユーザーインターフェース"""

from __future__ import annotations

import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

from .app_logging import CHANNEL_DETAIL, CHANNEL_USER, setup_logging, teardown_logging, user_log

from .app_service import (
    CLICK_MODE_LABEL_TO_VALUE,
    CLICK_MODE_OPTIONS,
    CLICK_MODE_VALUE_TO_LABEL,
    MATCHING_FIELDS,
    RETRY_TIMING_FIELDS,
    STATE_LABELS,
    UI_CLICK_FIELDS,
    SettingField,
    apply_ui_overrides,
    build_automator,
    load_config,
    save_config,
)
from .coordinate_preview import show_coordinate_preview
from .display import list_monitors
from .login_flow import LoginState
from .paths import bundle_root, prepare_runtime
from .setup_wizard import run_wizard_gui

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

OPERATION_NOTES = """【動作前の準備】
• 「開始」を押すと確認画面が出ます。サンプル画像の状態にしてください
• ログイン対象のサーバー行をクリックして選択（オレンジ色にハイライト）
• 初回は GUI の「セットアップ」ボタンから登録

【自動化の流れ】
• サーバー一覧で JOIN →（必要なら）MODS で JOIN → ログイン待ち
• 失敗したら CANCEL や BACK で戻り、自動で再試行します

【サブモニター運用】
• ARK をサブモニターに表示し「ARKモニター」で選択
• 操作時に ARK が一瞬前面に出ます

【待機時間】
• 「待ち時間」タブで、各場面の待ち時間を調整できます

【画像認識】
• うまく動かない場合は「画像認識」タブで一致度やクリック方式を調整
• 解像度や UI が違う環境では、セットアップの再実行も検討してください

【クリック座標】
• 「クリック座標」タブで各ボタンの％座標を数値入力できます
• 「座標のみ」モードではクリックはすべて座標、画像は画面判定のみ
• 「座標プレビュー」で設定位置をモニター上に点表示できます

【ログ】
• 「ログ」タブ … 進行状況のわかりやすい表示（通常はこちらを見てください）
• 「詳細ログ」タブ … 画像認識の類似度や座標など、原因調査用の技術情報
• ファイル: logs/asa_login_user.log / logs/asa_login_detail.log

【その他】
• 解像度・モニター変更時は再セットアップが必要
• 利用規約に違反する可能性があります。自己責任でご使用ください"""


class StartReadyDialog(tk.Toplevel):
    """開始前: サーバー選択済みの状態であることを確認"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        self.title("開始前の確認")
        self.configure(bg=COLORS["bg"])
        self.resizable(True, True)
        self.confirmed = False

        self.transient(parent)
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
        parent_x = parent.winfo_rootx()
        parent_y = parent.winfo_rooty()
        parent_w = parent.winfo_width()
        parent_h = parent.winfo_height()
        dialog_w = self.winfo_width()
        dialog_h = self.winfo_height()
        x = parent_x + max(0, (parent_w - dialog_w) // 2)
        y = parent_y + max(0, (parent_h - dialog_h) // 2)
        self.geometry(f"+{x}+{y}")

    def _on_cancel(self) -> None:
        self.confirmed = False
        self.destroy()

    def _on_confirm(self) -> None:
        self.confirmed = True
        self.destroy()


class LoginApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("ASA_Login")
        self.geometry("660x900")
        self.minsize(580, 720)
        self.configure(bg=COLORS["bg"])

        self._config = {}
        self._automator = None
        self._worker: threading.Thread | None = None
        self._running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._timing_vars: dict[str, tk.Variable] = {}
        self._matching_vars: dict[str, tk.Variable] = {}
        self._ui_coord_vars: dict[str, tuple[tk.DoubleVar, tk.DoubleVar]] = {}
        self._start_config: dict = {}
        self.click_mode_var = tk.StringVar(value=CLICK_MODE_OPTIONS[0][1])
        self.window_title_var = tk.StringVar()
        self.bring_to_front_var = tk.BooleanVar(value=True)

        self._setup_styles()
        self._build_ui()
        self._load_settings()
        self._poll_queue()

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

        style.configure("TCheckbutton", background=COLORS["surface"], foreground=COLORS["text"])
        style.configure("TButton", padding=(12, 6))
        style.configure("Accent.TButton", background=COLORS["accent"], foreground="white")
        style.map("Accent.TButton", background=[("active", COLORS["accent_hover"])])
        style.configure("Danger.TButton", background=COLORS["danger"], foreground="white")
        style.configure("TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background=COLORS["surface"], foreground=COLORS["text"], padding=(12, 6))
        style.map("TNotebook.Tab", background=[("selected", COLORS["surface2"])])

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

    def _card(self, parent, title: str) -> ttk.Frame:
        outer = ttk.Frame(parent, style="Card.TFrame", padding=12)
        outer.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(outer, text=title, style="Card.TLabel", font=("Segoe UI", 10, "bold")).pack(anchor=tk.W, pady=(0, 8))
        body = ttk.Frame(outer, style="Card.TFrame")
        body.pack(fill=tk.X)
        return body

    def _build_ui(self) -> None:
        self._init_timing_vars()
        self._init_matching_vars()
        self._init_ui_coord_vars()

        main = ttk.Frame(self, padding=16)
        main.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(main)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="ASA_Login", style="Title.TLabel").pack(side=tk.LEFT)
        ttk.Label(header, text="ARK: Survival Ascended 自動ログイン", style="Dim.TLabel").pack(side=tk.LEFT, padx=(12, 0), pady=(6, 0))

        notebook = ttk.Notebook(main)
        notebook.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        tab_main = ttk.Frame(notebook, padding=4)
        tab_timing = ttk.Frame(notebook, padding=4)
        tab_matching = ttk.Frame(notebook, padding=4)
        tab_coordinates = ttk.Frame(notebook, padding=4)
        notebook.add(tab_main, text="メイン")
        notebook.add(tab_timing, text="待ち時間")
        notebook.add(tab_matching, text="画像認識")
        notebook.add(tab_coordinates, text="クリック座標")

        self._build_main_tab(tab_main)
        self._build_timing_tab(tab_timing)
        self._build_matching_tab(tab_matching)
        self._build_coordinates_tab(tab_coordinates)

        status_card = ttk.Frame(main, style="Card.TFrame", padding=12)
        status_card.pack(fill=tk.X, pady=(0, 10))
        self.status_label = ttk.Label(status_card, text="待機中", style="Status.TLabel")
        self.status_label.pack(anchor=tk.W)

        stats_row = ttk.Frame(status_card, style="Card.TFrame")
        stats_row.pack(fill=tk.X, pady=(6, 0))
        self.attempts_label = ttk.Label(stats_row, text="試行: 0", style="CardDim.TLabel")
        self.attempts_label.pack(side=tk.LEFT, padx=(0, 16))
        self.failures_label = ttk.Label(stats_row, text="失敗: 0", style="CardDim.TLabel")
        self.failures_label.pack(side=tk.LEFT, padx=(0, 16))
        self.elapsed_label = ttk.Label(stats_row, text="経過: 0秒", style="CardDim.TLabel")
        self.elapsed_label.pack(side=tk.LEFT)

        btn_row = ttk.Frame(main)
        btn_row.pack(fill=tk.X, pady=(0, 10))
        self.start_btn = ttk.Button(btn_row, text="▶  開始", style="Accent.TButton", command=self._on_start)
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(btn_row, text="■  停止", style="Danger.TButton", command=self._on_stop, state=tk.DISABLED)
        self.stop_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="設定を保存", command=self._on_save).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="セットアップ", command=self._on_setup).pack(side=tk.RIGHT)

        log_card = self._card(main, "ログ")
        self.log_notebook = ttk.Notebook(log_card)
        self.log_notebook.pack(fill=tk.BOTH, expand=True)

        user_tab = ttk.Frame(self.log_notebook)
        detail_tab = ttk.Frame(self.log_notebook)
        self.log_notebook.add(user_tab, text="ログ")
        self.log_notebook.add(detail_tab, text="詳細ログ")

        self.user_log_text = self._create_log_text(user_tab, font=("Segoe UI", 9))
        self.detail_log_text = self._create_log_text(detail_tab, font=("Consolas", 9))
        self.log_notebook.select(user_tab)

    def _create_log_text(self, parent: tk.Misc, *, font: tuple[str, int]) -> scrolledtext.ScrolledText:
        widget = scrolledtext.ScrolledText(
            parent,
            height=8,
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief=tk.FLAT,
            font=font,
            state=tk.DISABLED,
        )
        widget.pack(fill=tk.BOTH, expand=True)
        return widget

    def _build_main_tab(self, parent: ttk.Frame) -> None:
        notes_card = self._card(parent, "注意事項")
        self.notes_text = scrolledtext.ScrolledText(
            notes_card,
            height=9,
            bg=COLORS["surface2"],
            fg=COLORS["text_dim"],
            relief=tk.FLAT,
            font=("Segoe UI", 9),
            wrap=tk.WORD,
            state=tk.DISABLED,
            cursor="arrow",
        )
        self.notes_text.pack(fill=tk.X)
        self.notes_text.configure(state=tk.NORMAL)
        self.notes_text.insert(tk.END, OPERATION_NOTES)
        self.notes_text.configure(state=tk.DISABLED)

        display_card = self._card(parent, "モニター")
        monitor_row = ttk.Frame(display_card, style="Card.TFrame")
        monitor_row.pack(fill=tk.X, pady=3)
        ttk.Label(monitor_row, text="ARK を表示しているモニター", style="Card.TLabel", width=28).pack(side=tk.LEFT)
        self._monitors = list_monitors()
        self._monitor_label_to_index = {m.label: m.index for m in self._monitors}
        self._monitor_index_to_label = {m.index: m.label for m in self._monitors}
        default_label = self._monitors[0].label if self._monitors else "モニター 1"
        self.monitor_var = tk.StringVar(value=default_label)
        monitor_menu = tk.OptionMenu(
            monitor_row,
            self.monitor_var,
            *[m.label for m in self._monitors],
        )
        monitor_menu.configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            width=24,
        )
        monitor_menu["menu"].configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        monitor_menu.pack(side=tk.LEFT, ipady=2)

        retry_card = self._card(parent, "リトライ")
        retry_grid = ttk.Frame(retry_card, style="Card.TFrame")
        retry_grid.pack(fill=tk.X)

        ttk.Label(retry_grid, text="最大試行回数", style="Card.TLabel").grid(row=0, column=0, sticky=tk.W, pady=3)
        self.max_attempts_var = tk.IntVar(value=0)
        ttk.Spinbox(retry_grid, from_=0, to=9999, textvariable=self.max_attempts_var, width=8, style="Dark.TSpinbox", font=("Segoe UI", 10)).grid(row=0, column=1, sticky=tk.W, padx=(8, 24))
        ttk.Label(retry_grid, text="0 = 無制限", style="CardDim.TLabel").grid(row=0, column=2, sticky=tk.W)

        ttk.Label(retry_grid, text="リトライ間隔", style="Card.TLabel").grid(row=1, column=0, sticky=tk.W, pady=3)
        self.delay_var = tk.DoubleVar(value=3.0)
        ttk.Spinbox(retry_grid, from_=0.5, to=60.0, increment=0.5, textvariable=self.delay_var, width=8, style="Dark.TSpinbox", font=("Segoe UI", 10)).grid(row=1, column=1, sticky=tk.W, padx=(8, 0))
        ttk.Label(retry_grid, text="秒（失敗して①に戻ったあと、次の試行までの待ち）", style="CardDim.TLabel").grid(row=1, column=2, sticky=tk.W, padx=(8, 0))
        ttk.Label(retry_grid, text="場面ごとの待ち時間は「待ち時間」タブ、認識の調整は「画像認識」タブ", style="CardDim.TLabel").grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(6, 0))

    def _build_scrollable_tab(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, bg=COLORS["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        scroll_body = ttk.Frame(canvas)
        scroll_body.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=scroll_body, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def _on_mousewheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)
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
                    font=("Segoe UI", 10, "bold"),
                ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=(10 if row else 0, 4))
                row += 1

            label_frame = ttk.Frame(grid, style="Card.TFrame")
            label_frame.grid(row=row, column=0, sticky=tk.NW, pady=6, padx=(0, 12))
            ttk.Label(label_frame, text=field.label, style="Card.TLabel", wraplength=260, justify=tk.LEFT).pack(anchor=tk.W)
            ttk.Label(
                label_frame,
                text=field.help,
                style="CardDim.TLabel",
                wraplength=260,
                justify=tk.LEFT,
                font=("Segoe UI", 9),
            ).pack(anchor=tk.W, pady=(2, 0))

            var = vars_map[field.key]
            if field.value_type == "int":
                widget = ttk.Spinbox(
                    grid,
                    from_=int(field.vmin),
                    to=int(field.vmax),
                    increment=int(field.increment),
                    textvariable=var,
                    width=8,
                    style="Dark.TSpinbox",
                    font=("Segoe UI", 10),
                )
            else:
                widget = ttk.Spinbox(
                    grid,
                    from_=field.vmin,
                    to=field.vmax,
                    increment=field.increment,
                    textvariable=var,
                    width=8,
                    style="Dark.TSpinbox",
                    font=("Segoe UI", 10),
                )
            widget.grid(row=row, column=1, sticky=tk.NW, pady=6)
            ttk.Label(
                grid,
                text=f"既定: {field.default:g}",
                style="CardDim.TLabel",
            ).grid(row=row, column=2, sticky=tk.NW, padx=(8, 0), pady=6)
            row += 1

    def _build_timing_tab(self, parent: ttk.Frame) -> None:
        intro = ttk.Label(
            parent,
            text="①〜⑦ の各場面でどれくらい待つかを設定します。環境によっては少し長めにすると安定します。",
            style="Dim.TLabel",
            wraplength=600,
        )
        intro.pack(anchor=tk.W, pady=(0, 8))

        scroll_body = self._build_scrollable_tab(parent)
        timing_card = self._card(scroll_body, "場面ごとの待ち時間")
        self._add_numeric_setting_rows(timing_card, RETRY_TIMING_FIELDS, self._timing_vars)

    def _build_matching_tab(self, parent: ttk.Frame) -> None:
        intro = ttk.Label(
            parent,
            text="画面やボタンの認識精度を調整します。誤クリックが多い場合は一致度を上げ、見逃しが多い場合は下げてください。",
            style="Dim.TLabel",
            wraplength=600,
        )
        intro.pack(anchor=tk.W, pady=(0, 8))

        scroll_body = self._build_scrollable_tab(parent)
        matching_card = self._card(scroll_body, "画像認識の感度")
        self._add_numeric_setting_rows(matching_card, MATCHING_FIELDS, self._matching_vars)

        window_card = self._card(scroll_body, "ウィンドウ")
        title_row = ttk.Frame(window_card, style="Card.TFrame")
        title_row.pack(fill=tk.X, pady=3)
        ttk.Label(title_row, text="ARK ウィンドウのタイトル", style="Card.TLabel", width=28).pack(side=tk.LEFT)
        ttk.Entry(
            title_row,
            textvariable=self.window_title_var,
            width=36,
            style="Dark.TEntry",
            font=("Segoe UI", 10),
        ).pack(side=tk.LEFT, ipady=2)
        ttk.Label(
            window_card,
            text="ウィンドウタイトルに含まれる文字列（部分一致）。通常は変更不要です。",
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 6))

        front_row = ttk.Frame(window_card, style="Card.TFrame")
        front_row.pack(fill=tk.X, pady=3)
        ttk.Checkbutton(
            front_row,
            text="操作前に ARK を前面に出す",
            variable=self.bring_to_front_var,
            style="TCheckbutton",
        ).pack(anchor=tk.W)
        ttk.Label(
            window_card,
            text="サブモニター運用では通常オンのままにしてください。",
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

    def _build_coordinates_tab(self, parent: ttk.Frame) -> None:
        intro = ttk.Label(
            parent,
            text="クリック位置を画面の％座標で指定します。「座標のみ」モードでは、クリックはすべてここで設定した座標を使い、画像認識は画面遷移の判定だけに使います。",
            style="Dim.TLabel",
            wraplength=600,
        )
        intro.pack(anchor=tk.W, pady=(0, 8))

        scroll_body = self._build_scrollable_tab(parent)

        mode_card = self._card(scroll_body, "クリック方式")
        mode_row = ttk.Frame(mode_card, style="Card.TFrame")
        mode_row.pack(fill=tk.X, pady=3)
        ttk.Label(mode_row, text="モード", style="Card.TLabel", width=20).pack(side=tk.LEFT, anchor=tk.N)
        click_menu = tk.OptionMenu(
            mode_row,
            self.click_mode_var,
            *[label for _value, label in CLICK_MODE_OPTIONS],
        )
        click_menu.configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["accent"],
            relief=tk.FLAT,
            font=("Segoe UI", 10),
            width=48,
        )
        click_menu["menu"].configure(
            bg=COLORS["surface2"],
            fg=COLORS["text"],
            activebackground=COLORS["accent"],
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        click_menu.pack(side=tk.LEFT, ipady=2)

        coord_card = self._card(scroll_body, "クリック座標（％）")
        grid = ttk.Frame(coord_card, style="Card.TFrame")
        grid.pack(fill=tk.X)
        ttk.Label(grid, text="操作", style="Card.TLabel").grid(row=0, column=0, sticky=tk.W, pady=4)
        ttk.Label(grid, text="X (%)", style="Card.TLabel").grid(row=0, column=1, sticky=tk.W, padx=(8, 4))
        ttk.Label(grid, text="Y (%)", style="Card.TLabel").grid(row=0, column=2, sticky=tk.W, padx=(8, 4))

        for row, field in enumerate(UI_CLICK_FIELDS, start=1):
            label = field.label + ("" if field.required else "（任意）")
            ttk.Label(grid, text=label, style="Card.TLabel", wraplength=220).grid(
                row=row, column=0, sticky=tk.W, pady=3, padx=(0, 8),
            )
            x_var, y_var = self._ui_coord_vars[field.key]
            ttk.Spinbox(
                grid, from_=0.0, to=100.0, increment=0.5, textvariable=x_var, width=8,
                style="Dark.TSpinbox", font=("Segoe UI", 10),
            ).grid(row=row, column=1, sticky=tk.W)
            ttk.Spinbox(
                grid, from_=0.0, to=100.0, increment=0.5, textvariable=y_var, width=8,
                style="Dark.TSpinbox", font=("Segoe UI", 10),
            ).grid(row=row, column=2, sticky=tk.W, padx=(8, 0))

        ttk.Label(
            coord_card,
            text="左上が (0, 0)、右下が (100, 100) です。セットアップで登録した値もここに反映されます。",
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(8, 0))

        preview_card = self._card(scroll_body, "座標プレビュー")
        ttk.Label(
            preview_card,
            text="ARK を表示しているモニター上に、設定した座標を色付きの点で重ねて表示します。",
            style="CardDim.TLabel",
            wraplength=560,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 8))
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
        points: list[tuple[str, float, float]] = []
        for field in UI_CLICK_FIELDS:
            x_var, y_var = self._ui_coord_vars[field.key]
            points.append((field.label, float(x_var.get()), float(y_var.get())))
        show_coordinate_preview(
            self,
            monitor_index=self._get_monitor_index(),
            points=points,
        )

    def _append_log(self, message: str, channel: str = CHANNEL_USER) -> None:
        widget = self.user_log_text if channel == CHANNEL_USER else self.detail_log_text
        widget.configure(state=tk.NORMAL)
        widget.insert(tk.END, message + "\n")
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
            self._config = load_config()
        except FileNotFoundError:
            self._append_log("設定ファイルが見つかりません。セットアップを実行してください。")
            return

        retry = self._config.get("retry", {})
        display = self._config.get("display", {})
        matching = self._config.get("matching", {})
        window = self._config.get("window", {})
        ui = self._config.get("ui", {})

        monitor_index = int(display.get("monitor_index", 1))
        label = self._monitor_index_to_label.get(monitor_index)
        if label:
            self.monitor_var.set(label)
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

        self.window_title_var.set(window.get("title_contains", "ARK: Survival Ascended"))
        self.bring_to_front_var.set(bool(window.get("bring_to_front", True)))

        for field in UI_CLICK_FIELDS:
            entry = ui.get(field.key, {})
            x_var, y_var = self._ui_coord_vars[field.key]
            x_var.set(float(entry.get("x_percent", field.default_x)))
            y_var.set(float(entry.get("y_percent", field.default_y)))

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
        return matching

    def _collect_window(self) -> dict[str, str | bool]:
        return {
            "title_contains": self.window_title_var.get().strip() or "ARK: Survival Ascended",
            "bring_to_front": bool(self.bring_to_front_var.get()),
        }

    def _get_monitor_index(self) -> int:
        return self._monitor_label_to_index.get(self.monitor_var.get(), 1)

    def _get_form_config(self) -> dict:
        return apply_ui_overrides(
            self._config,
            max_attempts=int(self.max_attempts_var.get()),
            delay_seconds=float(self.delay_var.get()),
            monitor_index=self._get_monitor_index(),
            retry_timing=self._collect_retry_timing(),
            matching_overrides=self._collect_matching(),
            window_overrides=self._collect_window(),
            ui_overrides=self._collect_ui_coords(),
        )

    def _on_save(self) -> None:
        try:
            self._config = self._get_form_config()
            save_config(self._config)
            self._append_log("設定を config.yaml に保存しました")
            messagebox.showinfo("保存完了", "設定を保存しました。")
        except Exception as exc:
            messagebox.showerror("エラー", f"設定の保存に失敗しました:\n{exc}")

    def _on_setup(self) -> None:
        default_monitor = self._get_monitor_index()

        def on_complete() -> None:
            self._load_settings()
            self._append_log("セットアップが完了しました")

        run_wizard_gui(self, default_monitor_index=default_monitor, on_complete=on_complete)

    def _on_state_change(self, state: LoginState, stats) -> None:
        self._log_queue.put(("state", state, stats))

    def _on_start(self) -> None:
        if self._running:
            return

        dialog = StartReadyDialog(self)
        self.wait_window(dialog)
        if not dialog.confirmed:
            return

        try:
            self._start_config = self._get_form_config()
            self._automator = build_automator(
                self._start_config,
                on_state_change=self._on_state_change,
            )
        except Exception as exc:
            messagebox.showerror("エラー", str(exc))
            return

        self._running = True
        self.start_btn.configure(state=tk.DISABLED)
        self.stop_btn.configure(state=tk.NORMAL)
        self._set_status("準備中...", COLORS["warning"])

        self._worker = threading.Thread(target=self._run_worker, daemon=True)
        self._worker.start()

    def _on_stop(self) -> None:
        self._running = False
        if self._automator:
            self._automator.stop()
        self._append_log("停止を要求しました...")

    def _run_worker(self) -> None:
        setup_logging(self._start_config, self._log_queue)
        try:
            countdown = max(0, int(self._start_config.get("retry", {}).get("start_countdown_seconds", 3)))
            for i in range(countdown, 0, -1):
                if not self._running:
                    return
                self._log_queue.put(("countdown", i))
                time.sleep(1)

            if not self._running:
                return

            result = self._automator.run()
            self._log_queue.put(("result", result))
        except Exception as exc:
            from .app_logging import detail_log

            detail_log.exception("実行中にエラーが発生しました")
            user_log.error("エラーが発生しました: %s", exc)
            self._log_queue.put(("error", str(exc)))
        finally:
            teardown_logging()
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

        self.after(100, self._poll_queue)


def run_gui() -> None:
    prepare_runtime()
    try:
        setup_logging(load_config())
    except FileNotFoundError:
        setup_logging()

    app = LoginApp()
    app.mainloop()
