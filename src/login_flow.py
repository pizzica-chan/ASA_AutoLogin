"""ログイン（サーバー参加）フローとリトライ制御"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from . import input_handler
from .app_logging import detail_log, user_log
from .button_templates import ButtonConfig, ui_point_for_key
from .default_assets import ensure_default_assets, resolve_screen_path
from .ui_positions import Point, UiPositions
from .vision import MatchResult, Vision

# ② MODS モーダルの JOIN は画面左側、① の一覧 JOIN は右下（X で区別）
MODS_JOIN_SEARCH_REGION = (0.0, 0.0, 0.58, 1.0)
# ⑤ JOIN GAME は左寄り4枚レイアウトが主流のため、右側の別カード誤検出を避ける
JOIN_GAME_SEARCH_REGION = (0.0, 0.0, 0.72, 1.0)


class LoginState(Enum):
    IDLE = auto()
    JOINING_SERVER = auto()       # ①
    JOINING_MODS = auto()         # ②
    WAITING_LOGIN = auto()        # ③
    HANDLING_FAILURE = auto()     # ③-A → ④ → ⑤
    HANDLING_NETWORK_FAILURE = auto()  # ⑥ → ⑦
    RECOVERING = auto()
    SUCCESS = auto()
    FAILED = auto()
    STOPPED = auto()


@dataclass
class RetryConfig:
    max_attempts: int = 0
    delay_seconds: float = 3.0
    join_click_delay: float = 1.5  # 後方互換（after_click_delay 未設定時）
    check_interval: float = 0.5  # 後方互換（poll_interval 未設定時）
    poll_interval: float = 0.5  # UI 検出のポーリング間隔
    transition_settle: float = 0.4  # ボタン検出後、クリック前の安定待ち
    after_click_delay: float = 1.5  # クリック後（画面遷移開始を待つ）
    transition_timeout: float = 20.0  # 次の UI が出るまでの最大待機
    result_timeout: float = 120.0  # ③ ログイン試行の待機（秒）
    login_movie_timeout: float = 120.0  # ムービー検出後の追加待機（秒）
    mods_wait_seconds: float = 8.0
    recovery_timeout: float = 45.0
    stuck_server_list_seconds: float = 30.0
    start_countdown_seconds: int = 3

    @property
    def poll_seconds(self) -> float:
        return self.poll_interval if self.poll_interval > 0 else self.check_interval


@dataclass
class TemplateConfig:
    server_list: str = "templates/server_list.png"
    required_mods: str = "templates/required_mods.png"
    connection_failed: str = "templates/connection_failed.png"
    login_movie: str = "templates/login_movie.png"
    network_failure: str = "templates/network_failure.png"
    title_screen: str = "templates/title_screen.png"
    server_list_empty: str = "templates/server_list_empty.png"
    main_menu: str = "templates/main_menu.png"
    in_game: str = "templates/in_game.png"
    screen_threshold: float = 0.75
    mods_screen_threshold: float = 0.55
    screen_ready_margin: float = 0.05
    click_mode: str = "image"  # image | image_only | coordinates | coordinates_only


@dataclass
class LoginStats:
    attempts: int = 0
    failures: int = 0
    start_time: float = field(default_factory=time.time)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self.start_time


class LoginAutomator:
    def __init__(
        self,
        vision: Vision,
        templates: TemplateConfig,
        retry: RetryConfig,
        ui: UiPositions,
        buttons: ButtonConfig | None = None,
        window_title: str = "ARK: Survival Ascended",
        bring_to_front: bool = True,
        on_state_change: Callable[[LoginState, LoginStats], None] | None = None,
    ):
        self.vision = vision
        self.templates = templates
        self.retry = retry
        self.ui = ui
        self.buttons = buttons or ButtonConfig()
        self.window_title = window_title
        self.bring_to_front = bring_to_front
        self.on_state_change = on_state_change
        self.click_mode = templates.click_mode

        self._state = LoginState.IDLE
        self._stats = LoginStats()
        self._running = False

    @property
    def state(self) -> LoginState:
        return self._state

    @property
    def stats(self) -> LoginStats:
        return self._stats

    def _set_state(self, state: LoginState) -> None:
        self._state = state
        if self.on_state_change:
            self.on_state_change(state, self._stats)

    def stop(self) -> None:
        self._running = False
        self._set_state(LoginState.STOPPED)
        user_log.info("自動ログインを停止しました")
        detail_log.info("自動ログインを停止しました")

    def _is_coordinates_only(self) -> bool:
        return self.click_mode == "coordinates_only"

    def _focus_game(self) -> bool:
        if not self.bring_to_front:
            return True
        return input_handler.bring_window_to_front(self.window_title)

    def _screen_map(self) -> dict[str, str]:
        raw = {
            "server_list": self.templates.server_list,
            "required_mods": self.templates.required_mods,
            "connection_failed": self.templates.connection_failed,
            "login_movie": self.templates.login_movie,
            "network_failure": self.templates.network_failure,
            "title_screen": self.templates.title_screen,
            "server_list_empty": self.templates.server_list_empty,
            "main_menu": self.templates.main_menu,
            "in_game": self.templates.in_game,
        }
        screens: dict[str, str] = {}
        for name, user_path in raw.items():
            resolved = resolve_screen_path(name, user_path)
            if resolved:
                screens[name] = resolved
        return screens

    def _find_button(
        self,
        button_key: str,
        screen=None,
        *,
        strict: bool = False,
        region: tuple[float, float, float, float] | None = None,
    ) -> MatchResult:
        """ボタン画像を検索（1回の画面キャプチャを共有）"""
        paths = self.buttons.list_paths(button_key)
        if not paths:
            return MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))

        if screen is None:
            screen = self.vision.capture_screen()

        search_region = region
        if search_region is None and button_key == "join_mods":
            search_region = MODS_JOIN_SEARCH_REGION
        if search_region is None and button_key == "join_game":
            search_region = JOIN_GAME_SEARCH_REGION

        use_strict = strict
        if button_key == "join_game":
            use_strict = False
        thresholds = (
            (self.buttons.threshold,)
            if use_strict
            else (self.buttons.threshold, self.buttons.threshold_relaxed)
        )
        best = MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))

        for path in paths:
            for threshold in thresholds:
                result = self.vision.find_button_on_screen(
                    path,
                    threshold=threshold,
                    screen=screen,
                    region=search_region,
                )
                if result.confidence > best.confidence:
                    best = result
                if result.found:
                    detail_log.debug(
                        "ボタン %s を検出: %s (類似度: %.2f)",
                        button_key,
                        path,
                        result.confidence,
                    )
                    return result

        return best

    def _log_button_miss(self, button_key: str, best: MatchResult, paths: list[str], region) -> None:
        detail_log.info(
            "ボタン未検出: %s paths=%s region=%s 最高類似度=%.2f 閾値=%.2f/%.2f",
            button_key,
            paths,
            region,
            best.confidence,
            self.buttons.threshold,
            self.buttons.threshold_relaxed,
        )

    def _mods_screen_score(self, screen=None) -> float:
        return self._screen_score("required_mods", screen=screen)

    def _is_mods_dialog_visible(self, screen=None) -> bool:
        """② MODS 画面の表示判定（クリック位置の妥当性は見ない）"""
        if screen is None:
            screen = self.vision.capture_screen()

        score = self._mods_screen_score(screen=screen)
        if score >= self.templates.mods_screen_threshold:
            return True

        if self._is_coordinates_only():
            return False

        return self._find_button("join_mods", screen=screen, strict=True).found

    def _is_mods_dialog_still_open(self, screen=None) -> bool:
        """② クリック後も MODS 画面に残っているか（誤判定で閉じた扱いにしない）"""
        return self._is_mods_dialog_visible(screen=screen)

    def _wait_for_mods_dismissed(self) -> bool:
        deadline = time.time() + self.retry.transition_timeout
        settled_closed = 0
        while self._running and time.time() < deadline:
            if self._is_mods_dialog_still_open(self.vision.capture_screen()):
                settled_closed = 0
            else:
                settled_closed += 1
                if settled_closed >= 2:
                    detail_log.info("② MODS 画面が閉じました")
                    return True
            time.sleep(self.retry.poll_seconds)

        if self._is_mods_dialog_still_open():
            detail_log.warning("② MODS 画面が閉じませんでした")
        return False

    def _button_visible(self, button_key: str, *, strict: bool = True) -> bool:
        return self._find_button(button_key, strict=strict).found

    def _screen_score(self, screen_name: str, screen=None) -> float:
        path = resolve_screen_path(screen_name, getattr(self.templates, screen_name, None))
        if not path:
            return 0.0
        result = self.vision.compare_with_reference(
            path,
            threshold=0.0,
            screen=screen,
        )
        return result.confidence

    def _has_connection_failed_dialog(self, screen=None) -> bool:
        if self._is_coordinates_only():
            matched, score = self._match_screen("connection_failed", screen=screen)
            if matched:
                detail_log.debug("画面検出: connection_failed (類似度: %.2f)", score)
            return matched
        return self._find_button("cancel_failed", screen=screen, strict=True).found

    def _has_network_failure_dialog(self, screen=None) -> bool:
        if self._is_coordinates_only():
            matched, score = self._match_screen("network_failure", screen=screen)
            if matched:
                detail_log.debug("画面検出: network_failure (類似度: %.2f)", score)
            return matched
        return self._find_button("accept_network_failure", screen=screen, strict=True).found

    def _is_server_list_ready(self, screen=None) -> tuple[bool, float]:
        """サーバー選択済み・JOIN 可能な一覧（エラーダイアログなし）"""
        if screen is None:
            screen = self.vision.capture_screen()

        if self._has_connection_failed_dialog(screen):
            return False, 0.0
        if self._has_network_failure_dialog(screen):
            return False, 0.0

        if not self._is_coordinates_only():
            join = self._find_button("join_server_list", screen=screen, strict=True)
            if not join.found:
                return False, 0.0

        score = self._screen_score("server_list", screen=screen)
        ready = score >= self.templates.screen_threshold - self.templates.screen_ready_margin
        return ready, score

    def _match_screen(self, screen_name: str, screen=None) -> tuple[bool, float]:
        """画面テンプレート一致（エラー系はボタンで別判定）"""
        path = resolve_screen_path(screen_name, getattr(self.templates, screen_name, None))
        if not path:
            return False, 0.0
        result = self.vision.compare_with_reference(
            path,
            threshold=self.templates.screen_threshold,
            screen=screen,
        )
        return result.found, result.confidence

    def _ensure_at_step1(self) -> bool:
        """フロー仕様どおり ① の状態になるまで、決められた手順だけで復帰する"""
        ready, score = self._is_server_list_ready()
        if ready:
            user_log.info("サーバー一覧の準備ができています")
            detail_log.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
            return True

        if self._has_connection_failed_dialog():
            user_log.info("接続に失敗しました。やり直します…")
            detail_log.info("③-A を検出。CANCEL → ④ BACK → ⑤ JOIN GAME → ① を実行します")
            if not self._recover_after_connection_failed():
                return False

        if self._has_network_failure_dialog():
            user_log.info("ネットワークエラーです。タイトル画面からやり直します…")
            detail_log.info("⑥ を検出。ACCEPT → ⑦ → ⑤ JOIN GAME → ① を実行します")
            if not self._recover_after_network_failure():
                return False

        empty_list, _ = self._match_screen("server_list_empty")
        if empty_list and (
            self._is_coordinates_only() or self._find_button("back_empty_list", strict=True).found
        ):
            user_log.info("サーバー一覧が空です。メインメニューに戻ります…")
            detail_log.info("④ を検出。BACK → ⑤ JOIN GAME → ① を実行します")
            self._set_state(LoginState.RECOVERING)
            if not self._click_target_when_ready("back_empty_list", "④ BACK"):
                return False
            self._wait_after_click()
            if not self._return_to_server_list_via_main_menu():
                return False

        main_menu, _ = self._match_screen("main_menu")
        if main_menu:
            user_log.info("メインメニューです。サーバー一覧に戻ります…")
            detail_log.info("⑤ を検出。JOIN GAME → ① を実行します")
            if not self._return_to_server_list_via_main_menu():
                return False

        ready, score = self._is_server_list_ready()
        if ready:
            user_log.info("サーバー一覧の準備ができています")
            detail_log.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
            return True

        user_log.error("サーバー一覧の準備ができていません。サーバーを選択してから開始してください")
        detail_log.error(
            "① の状態にありません。サーバーを選択した一覧画面にしてから開始してください"
        )
        return False

    def _wait_for_screen_before_click(self, button_key: str, timeout: float) -> bool:
        """座標のみモード: クリック前に画面テンプレートで待機"""
        if button_key == "join_server_list":
            return self._wait_for_step1_ready(timeout)
        if button_key == "join_mods":
            deadline = time.time() + timeout
            while self._running and time.time() < deadline:
                if self._is_mods_dialog_visible():
                    return True
                time.sleep(self.retry.poll_seconds)
            return False
        screen_map = {
            "cancel_failed": "connection_failed",
            "back_empty_list": "server_list_empty",
            "join_game": "main_menu",
            "accept_network_failure": "network_failure",
        }
        screen_name = screen_map.get(button_key)
        if screen_name:
            return self._wait_for_screen(screen_name, timeout)
        return True

    def _wait_for_button(self, button_key: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        best_confidence = 0.0
        while self._running and time.time() < deadline:
            result = self._find_button(button_key, strict=True)
            if result.confidence > best_confidence:
                best_confidence = result.confidence
            if result.found:
                detail_log.info("ボタン検出: %s (類似度: %.2f)", button_key, result.confidence)
                return True
            time.sleep(self.retry.poll_seconds)

        if best_confidence > 0:
            detail_log.info(
                "ボタン %s は未検出（最高類似度: %.2f / 閾値: %.2f）",
                button_key,
                best_confidence,
                self.buttons.threshold,
            )
        return False

    def _wait_for_step1_ready(self, timeout: float) -> bool:
        """① サーバー一覧到達を待つ（_is_server_list_ready と同じ基準）"""
        deadline = time.time() + timeout
        best_score = 0.0
        while self._running and time.time() < deadline:
            ready, score = self._is_server_list_ready()
            if score > best_score:
                best_score = score
            if ready:
                detail_log.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
                return True
            time.sleep(self.retry.poll_seconds)

        threshold = self.templates.screen_threshold - self.templates.screen_ready_margin
        if best_score > 0:
            detail_log.info(
                "① 未検出（server_list 最高: %.2f / 閾値: %.2f）",
                best_score,
                threshold,
            )
        return False

    def _wait_for_step5_ready(self, timeout: float) -> bool:
        """⑤ メインメニュー到達を待つ（JOIN GAME ボタン or main_menu 画面のどちらか先）"""
        deadline = time.time() + timeout
        best_join = 0.0
        best_menu = 0.0
        while self._running and time.time() < deadline:
            screen = self.vision.capture_screen()

            if not self._is_coordinates_only():
                join = self._find_button("join_game", screen=screen, strict=True)
                if join.confidence > best_join:
                    best_join = join.confidence
                if join.found:
                    detail_log.info("ボタン検出: join_game (類似度: %.2f)", join.confidence)
                    return True

            menu_matched, menu_score = self._match_screen("main_menu", screen=screen)
            if menu_score > best_menu:
                best_menu = menu_score
            if menu_matched:
                detail_log.info("画面検出: main_menu (類似度: %.2f)", menu_score)
                return True

            time.sleep(self.retry.poll_seconds)

        if best_join > 0 or best_menu > 0:
            detail_log.info(
                "⑤ 未検出（join_game 最高: %.2f, main_menu 最高: %.2f / 閾値: %.2f）",
                best_join,
                best_menu,
                self.buttons.threshold,
            )
        return False

    def _wait_after_click(self) -> None:
        delay = self.retry.after_click_delay or self.retry.join_click_delay
        time.sleep(delay)

    def _click_target_when_ready(
        self,
        button_key: str,
        label: str,
        timeout: float | None = None,
    ) -> bool:
        """ボタンが表示されるまで待ってからクリック"""
        wait_timeout = timeout if timeout is not None else self.retry.transition_timeout
        should_wait = self._is_coordinates_only() or self.buttons.get(button_key) or ui_point_for_key(self.ui, button_key)
        if should_wait:
            wait_fn = (
                self._wait_for_screen_before_click
                if self._is_coordinates_only()
                else self._wait_for_button
            )
            if not wait_fn(button_key, wait_timeout):
                user_log.warning("%s が見つかりませんでした（%d 秒待機）", label, int(wait_timeout))
                detail_log.warning("%s が %d 秒以内に表示されませんでした", label, int(wait_timeout))
        time.sleep(self.retry.transition_settle)
        return self._click_target(button_key, label)

    def _wait_for_screen(
        self,
        screen_name: str,
        timeout: float,
    ) -> bool:
        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            matched, score = self._match_screen(screen_name)
            if matched:
                detail_log.info("画面検出: %s (類似度: %.2f)", screen_name, score)
                return True
            time.sleep(self.retry.poll_seconds)
        return False

    def _click(self, point: Point, label: str) -> None:
        abs_x, abs_y = self.ui.click_pixels(point)
        detail_log.info("%s を座標クリック (%d, %d)", label, abs_x, abs_y)
        input_handler.click(abs_x, abs_y)

    def _click_target(self, button_key: str, label: str) -> bool:
        """ボタン画像を優先してクリック。見つからなければ座標にフォールバック（image_only 除く）"""
        if self._is_coordinates_only():
            fallback = ui_point_for_key(self.ui, button_key)
            if fallback:
                user_log.info("%s を座標でクリックします", label)
                self._click(fallback, label)
                return True
            user_log.error("%s の座標が未設定です", label)
            detail_log.error("%s の座標が未設定です（coordinates_only）", label)
            return False

        if self.click_mode == "coordinates":
            fallback = ui_point_for_key(self.ui, button_key)
            if fallback:
                self._click(fallback, label)
                return True

        paths = self.buttons.list_paths(button_key)
        if paths:
            screen = self.vision.capture_screen()
            for attempt in range(3):
                result = self._find_button(button_key, screen=screen, strict=True)
                if result.found:
                    user_log.info("%s をクリックしました", label)
                    detail_log.info(
                        "%s を画像認識でクリック (類似度: %.2f, %d, %d)",
                        label,
                        result.confidence,
                        result.center_x,
                        result.center_y,
                    )
                    input_handler.click(result.center_x, result.center_y)
                    return True
                if attempt < 2:
                    time.sleep(0.15)
                    screen = self.vision.capture_screen()
            user_log.warning("%s を画面上で見つけられませんでした", label)
            detail_log.warning(
                "%s のボタン画像を検出できませんでした（候補: %s）",
                label,
                ", ".join(paths),
            )
            best = self._find_button(button_key, strict=False)
            self._log_button_miss(button_key, best, paths, None)

        if self.click_mode == "image_only":
            user_log.error("%s をクリックできませんでした（画像のみモード）", label)
            detail_log.error("%s のボタン画像が見つかりません（click_mode: image_only）", label)
            return False

        fallback = ui_point_for_key(self.ui, button_key)
        if fallback:
            user_log.info("%s を登録座標でクリックしました", label)
            self._click(fallback, f"{label}（座標フォールバック）")
            return True

        user_log.error("%s のクリック先が未設定です", label)
        detail_log.error("%s のクリック先が未設定です（ボタン画像・座標ともに無し）", label)
        return False

    def _step1_join_server_list(self) -> bool:
        """① サーバー一覧で右下 JOIN"""
        self._set_state(LoginState.JOINING_SERVER)
        user_log.info("サーバー一覧で JOIN を押します")
        detail_log.info("① サーバー一覧 JOIN を実行します")
        if not self._click_target_when_ready("join_server_list", "① サーバー一覧 JOIN"):
            return False
        self._wait_after_click()
        return True

    def _step2_maybe_join_mods(self) -> bool:
        """② REQUIRED MODS（表示時のみ JOIN）"""
        if self._is_coordinates_only():
            has_mods_button = self.ui.has_point("join_mods")
        else:
            has_mods_button = self.buttons.has("join_mods") or self.ui.has_point("join_mods")
        if not has_mods_button:
            return False

        deadline = time.time() + self.retry.mods_wait_seconds
        while self._running and time.time() < deadline:
            screen = self.vision.capture_screen()
            if not self._is_mods_dialog_visible(screen):
                time.sleep(self.retry.poll_seconds)
                continue

            self._set_state(LoginState.JOINING_MODS)
            mods_screen, score = self._match_screen("required_mods", screen=screen)
            user_log.info("MODS 画面で JOIN を押します")
            detail_log.info(
                "② MODS 画面を検出 (画面: %s)",
                f"{score:.2f}" if score > 0 else "なし",
            )

            for attempt in range(2):
                self._focus_game()
                if not self._click_target_when_ready("join_mods", "② MODS JOIN"):
                    user_log.warning("MODS 画面の JOIN に失敗しました")
                    detail_log.warning("② MODS JOIN に失敗しました")
                    return False
                self._wait_after_click()
                if self._wait_for_mods_dismissed():
                    return True
                detail_log.warning("② MODS JOIN 後も画面が残っています（%d/2 回目）", attempt + 1)

            user_log.warning("MODS 画面が閉じませんでした")
            detail_log.warning("② MODS JOIN を実行しましたが画面が閉じませんでした")
            return False

        detail_log.info("② MODS 画面は表示されませんでした（スキップ）")
        return False

    def _step3_wait_for_login(self) -> str:
        """③ ログイン試行（待機のみ。失敗は ③-A / ⑥ のボタンで判定）"""
        self._set_state(LoginState.WAITING_LOGIN)
        started_at = time.time()
        deadline = started_at + self.retry.result_timeout
        movie_seen = False
        user_log.info("ログイン結果を待っています…")
        detail_log.info("③ ログイン試行を待機します")

        while self._running and time.time() < deadline:
            screen = self.vision.capture_screen()

            in_game, score = self._match_screen("in_game", screen=screen)
            if in_game:
                user_log.info("ゲーム内画面を検出しました")
                detail_log.info("ログイン成功画面を検出 (類似度: %.2f)", score)
                return "success"

            movie, movie_score = self._match_screen("login_movie", screen=screen)
            if movie:
                if not movie_seen:
                    movie_seen = True
                    movie_deadline = time.time() + self.retry.login_movie_timeout
                    deadline = max(deadline, movie_deadline)
                    user_log.info("ログイン動画を再生中です。しばらく待ちます…")
                    detail_log.info(
                        self.retry.login_movie_timeout,
                    )
                else:
                    detail_log.debug("ログインムービー再生中 (類似度: %.2f)", movie_score)
                time.sleep(self.retry.poll_seconds)
                continue

            if self._has_network_failure_dialog(screen):
                user_log.info("ネットワークエラーを検出しました")
                detail_log.info("⑥ NETWORK FAILURE を検出（ACCEPT ボタン）")
                return "failure_network"

            if self._has_connection_failed_dialog(screen):
                user_log.info("接続失敗を検出しました")
                detail_log.info("③-A CONNECTION FAILED を検出（CANCEL ボタン）")
                return "failure_browser"

            time.sleep(self.retry.poll_seconds)

        if not self._running:
            user_log.info("ログイン待機を中断しました")
            detail_log.info("ログイン試行を中断しました")
            return "stopped"

        user_log.warning("ログイン結果が出ませんでした（タイムアウト）")
        detail_log.warning(
            time.time() - started_at,
        )
        return "timeout"

    def _recover_after_connection_failed(self) -> bool:
        """③-A CANCEL → ④ BACK → ⑤ JOIN GAME → ①"""
        self._set_state(LoginState.HANDLING_FAILURE)

        if not self._has_connection_failed_dialog():
            detail_log.warning("③-A: CANCEL ボタンが見えません")
            return False

        if not self._click_target_when_ready("cancel_failed", "③-A CANCEL"):
            return False
        self._wait_after_click()

        self._set_state(LoginState.RECOVERING)

        if not self._wait_for_button("back_empty_list", self.retry.recovery_timeout):
            detail_log.warning("④: BACK ボタンを検出できませんでした")
            return False

        time.sleep(self.retry.transition_settle)
        if not self._click_target("back_empty_list", "④ BACK"):
            return False
        self._wait_after_click()

        return self._return_to_server_list_via_main_menu()

    def _return_to_server_list_via_main_menu(self) -> bool:
        """⑤ JOIN GAME → ① サーバー一覧へ戻る"""
        self._set_state(LoginState.RECOVERING)

        if not self._wait_for_step5_ready(self.retry.recovery_timeout):
            user_log.warning("メインメニューまたは JOIN GAME が見つかりませんでした")
            detail_log.warning("メインメニュー / JOIN GAME を検出できませんでした")
            return False

        time.sleep(self.retry.transition_settle)
        if not self._click_target("join_game", "⑤ JOIN GAME"):
            return False
        self._wait_after_click()

        if not self._wait_for_step1_ready(self.retry.recovery_timeout):
            user_log.warning("サーバー一覧に戻れませんでした")
            detail_log.warning("サーバー一覧画面に戻れませんでした")
            return False

        user_log.info("サーバー一覧に戻りました")
        detail_log.info("リカバリー完了。① の状態に戻りました")
        return True

    def _wait_for_title_screen(self, timeout: float) -> bool:
        """⑦ タイトル画面（⑥ のダイアログ消去後）を待つ"""
        if Path(self.templates.title_screen).exists():
            return self._wait_for_screen("title_screen", timeout)

        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            if not self._has_network_failure_dialog():
                detail_log.info("⑦ タイトル画面に遷移しました（エラーダイアログ消失）")
                return True
            time.sleep(self.retry.poll_seconds)
        return False

    def _proceed_from_title_screen_to_main_menu(self) -> bool:
        """⑦ Space キー → ⑤ メインメニュー"""
        time.sleep(self.retry.transition_settle)
        input_handler.press_key("space")
        detail_log.info("⑦ Space キー押下")
        self._wait_after_click()
        return self._wait_for_step5_ready(self.retry.recovery_timeout)

    def _has_network_failure_setup(self) -> bool:
        if self._is_coordinates_only():
            return self.ui.has_point("accept_network_failure")
        return self.buttons.has("accept_network_failure") or self.ui.has_point(
            "accept_network_failure"
        )

    def _recover_after_network_failure(self) -> bool:
        """⑥ ACCEPT → ⑦ Space → ⑤ JOIN GAME → ① へ戻る"""
        self._set_state(LoginState.HANDLING_NETWORK_FAILURE)

        if not self._has_network_failure_setup():
            if self._is_coordinates_only():
                detail_log.error(
                    "⑥ のリカバリーに必要な ACCEPT 座標がありません。"
                    "クリック座標タブで ui.accept_network_failure を設定してください"
                )
            else:
                detail_log.error(
                    "⑥ のリカバリーに必要な ACCEPT ボタン画像がありません。"
                    "セットアップで⑥を登録するか、config の ui.accept_network_failure を設定してください"
                )
            return False

        if not self._has_network_failure_dialog():
            detail_log.warning("⑥: ACCEPT ボタンが見えません")
            return False

        if not self._click_target_when_ready("accept_network_failure", "⑥ ACCEPT"):
            return False
        self._wait_after_click()

        if not self._wait_for_title_screen(self.retry.recovery_timeout):
            detail_log.warning("⑦ タイトル画面を検出できませんでした")
            return False
        detail_log.info("⑦ タイトル画面を検出しました")

        if not self._proceed_from_title_screen_to_main_menu():
            detail_log.warning("⑤ メインメニューへ遷移できませんでした")
            return False

        return self._return_to_server_list_via_main_menu()

    def _should_retry(self) -> bool:
        if self.retry.max_attempts == 0:
            return True
        return self._stats.attempts < self.retry.max_attempts

    def run(self) -> LoginState:
        self._running = True
        self._stats = LoginStats()
        ensure_default_assets()
        user_log.info("自動ログインを開始します")
        detail_log.info("自動ログインを開始します")
        detail_log.info(
            "設定: click_mode=%s monitor=%s screen_threshold=%.2f button_threshold=%.2f "
            "button_relaxed=%.2f mods_threshold=%.2f ready_margin=%.2f",
            self.click_mode,
            self.vision.monitor.label,
            self.templates.screen_threshold,
            self.buttons.threshold,
            self.buttons.threshold_relaxed,
            self.templates.mods_screen_threshold,
            self.templates.screen_ready_margin,
        )

        if not resolve_screen_path("server_list", self.templates.server_list):
            user_log.error("サーバー一覧の画像が未設定です。セットアップを実行してください")
            detail_log.error("server_list.png が未設定です。セットアップを実行してください")
            self._set_state(LoginState.FAILED)
            return LoginState.FAILED

        if self._is_coordinates_only():
            if not self.ui.is_configured():
                user_log.error("クリック座標が未設定です。クリック座標タブで入力してください")
                detail_log.error("coordinates_only ですが ui 座標が未設定です")
                self._set_state(LoginState.FAILED)
                return LoginState.FAILED
        elif not self.buttons.is_configured(self.ui):
            user_log.error("ボタン画像または座標が未設定です。セットアップを実行してください")
            detail_log.error("ボタン画像または UI 座標が未設定です。セットアップを実行してください")
            self._set_state(LoginState.FAILED)
            return LoginState.FAILED

        while self._running:
            if not self._should_retry():
                user_log.error("リトライ上限に達しました")
                detail_log.error("最大リトライ回数 (%d) に達しました", self.retry.max_attempts)
                self._set_state(LoginState.FAILED)
                return LoginState.FAILED

            self._stats.attempts += 1
            user_log.info("── 試行 %d回目 ──", self._stats.attempts)
            detail_log.info("=== 試行 %d回目 ===", self._stats.attempts)

            if not self._focus_game():
                user_log.warning("ARK のウィンドウが見つかりません。続行します…")
                detail_log.warning("ゲームウィンドウが見つかりません。続行します...")

            if not self._ensure_at_step1():
                self._stats.failures += 1
                time.sleep(self.retry.delay_seconds)
                continue

            if not self._step1_join_server_list():
                self._stats.failures += 1
                time.sleep(self.retry.delay_seconds)
                continue
            if not self._step2_maybe_join_mods():
                if self._is_mods_dialog_still_open():
                    user_log.warning("MODS 画面が残っているため、次に進めません")
                    detail_log.warning("② MODS 画面が残っています。③ には進みません")
                    self._stats.failures += 1
                    time.sleep(self.retry.delay_seconds)
                    continue

            result = self._step3_wait_for_login()

            if not self._running or result == "stopped":
                return LoginState.STOPPED

            if result == "success":
                self._set_state(LoginState.SUCCESS)
                user_log.info(
                    "ログインに成功しました！（試行 %d回 / %.0f秒）",
                    self._stats.attempts,
                    self._stats.elapsed_seconds,
                )
                detail_log.info(
                    "ログイン成功！ 試行回数: %d, 所要時間: %.0f秒",
                    self._stats.attempts,
                    self._stats.elapsed_seconds,
                )
                return LoginState.SUCCESS

            if result == "failure_browser":
                user_log.info("接続失敗から復帰します…")
                detail_log.info("③-A CONNECTION FAILED。③-A → ④ → ⑤ → ① の復帰を開始します")
                if not self._recover_after_connection_failed():
                    self._stats.failures += 1
                    user_log.warning("接続失敗からの復帰に失敗しました")
                    detail_log.warning("③-A → ④ → ⑤ → ① の復帰に失敗しました")
            elif result == "failure_network":
                user_log.info("ネットワークエラーから復帰します…")
                detail_log.info("⑥ NETWORK FAILURE。⑥ → ⑦ → ⑤ → ① の復帰を開始します")
                if not self._recover_after_network_failure():
                    self._stats.failures += 1
                    user_log.warning("ネットワークエラーからの復帰に失敗しました")
                    detail_log.warning("⑥ → ⑦ → ⑤ → ① の復帰に失敗しました")
            else:
                self._stats.failures += 1
                user_log.warning("結果が出なかったため、もう一度試します")
                detail_log.warning("③ がタイムアウトしました。次の試行まで待機します")

            time.sleep(self.retry.delay_seconds)

        return LoginState.STOPPED
