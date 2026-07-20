"""ログイン（サーバー参加）フローとリトライ制御"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Callable

from . import input_handler
from .button_templates import ButtonConfig, ui_point_for_key
from .default_assets import ensure_default_assets, resolve_screen_path
from .ui_positions import Point, UiPositions
from .vision import MatchResult, Vision

logger = logging.getLogger(__name__)

# ② MODS モーダルの JOIN は画面左側、① の一覧 JOIN は右下（X で区別）
MODS_JOIN_SEARCH_REGION = (0.0, 0.0, 0.58, 1.0)
MODS_SCREEN_LOOSE_THRESHOLD = 0.55


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
    click_mode: str = "image"  # image | image_only | coordinates


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
        logger.info("自動ログインを停止しました")

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

        thresholds = (self.buttons.threshold,) if strict else (self.buttons.threshold, 0.68)
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
                    logger.debug(
                        "ボタン %s を検出: %s (類似度: %.2f)",
                        button_key,
                        path,
                        result.confidence,
                    )
                    return result

        return best

    def _mods_screen_score(self, screen=None) -> float:
        return self._screen_score("required_mods", screen=screen)

    def _is_mods_dialog_visible(self, screen=None) -> bool:
        """② MODS 画面の表示判定（クリック位置の妥当性は見ない）"""
        if screen is None:
            screen = self.vision.capture_screen()

        score = self._mods_screen_score(screen=screen)
        if score >= MODS_SCREEN_LOOSE_THRESHOLD:
            return True

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
                    logger.info("② MODS 画面が閉じました")
                    return True
            time.sleep(self.retry.poll_seconds)

        if self._is_mods_dialog_still_open():
            logger.warning("② MODS 画面が閉じませんでした")
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
        return self._find_button("cancel_failed", screen=screen, strict=True).found

    def _has_network_failure_dialog(self, screen=None) -> bool:
        return self._find_button("accept_network_failure", screen=screen, strict=True).found

    def _is_server_list_ready(self, screen=None) -> tuple[bool, float]:
        """サーバー選択済み・JOIN 可能な一覧（エラーダイアログなし）"""
        if screen is None:
            screen = self.vision.capture_screen()

        if self._has_connection_failed_dialog(screen):
            return False, 0.0
        if self._has_network_failure_dialog(screen):
            return False, 0.0

        join = self._find_button("join_server_list", screen=screen, strict=True)
        if not join.found:
            return False, 0.0
        score = self._screen_score("server_list", screen=screen)
        ready = score >= self.templates.screen_threshold - 0.05
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
            logger.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
            return True

        if self._has_connection_failed_dialog():
            logger.info("③-A を検出。CANCEL → ④ BACK → ⑤ JOIN GAME → ① を実行します")
            if not self._recover_after_connection_failed():
                return False

        if self._has_network_failure_dialog():
            logger.info("⑥ を検出。ACCEPT → ⑦ → ⑤ JOIN GAME → ① を実行します")
            if not self._recover_after_network_failure():
                return False

        empty_list, _ = self._match_screen("server_list_empty")
        if empty_list and self._find_button("back_empty_list", strict=True).found:
            logger.info("④ を検出。BACK → ⑤ JOIN GAME → ① を実行します")
            self._set_state(LoginState.RECOVERING)
            if not self._click_target_when_ready("back_empty_list", "④ BACK"):
                return False
            self._wait_after_click()
            if not self._return_to_server_list_via_main_menu():
                return False

        main_menu, _ = self._match_screen("main_menu")
        if main_menu:
            logger.info("⑤ を検出。JOIN GAME → ① を実行します")
            if not self._return_to_server_list_via_main_menu():
                return False

        ready, score = self._is_server_list_ready()
        if ready:
            logger.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
            return True

        logger.error(
            "① の状態にありません。サーバーを選択した一覧画面にしてから開始してください"
        )
        return False

    def _wait_for_button(self, button_key: str, timeout: float) -> bool:
        deadline = time.time() + timeout
        best_confidence = 0.0
        while self._running and time.time() < deadline:
            result = self._find_button(button_key, strict=True)
            if result.confidence > best_confidence:
                best_confidence = result.confidence
            if result.found:
                logger.info("ボタン検出: %s (類似度: %.2f)", button_key, result.confidence)
                return True
            time.sleep(self.retry.poll_seconds)

        if best_confidence > 0:
            logger.info(
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
                logger.info("① サーバー一覧の状態を確認しました (類似度: %.2f)", score)
                return True
            time.sleep(self.retry.poll_seconds)

        threshold = self.templates.screen_threshold - 0.05
        if best_score > 0:
            logger.info(
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
            join = self._find_button("join_game", screen=screen, strict=True)
            if join.confidence > best_join:
                best_join = join.confidence
            if join.found:
                logger.info("ボタン検出: join_game (類似度: %.2f)", join.confidence)
                return True

            menu_matched, menu_score = self._match_screen("main_menu", screen=screen)
            if menu_score > best_menu:
                best_menu = menu_score
            if menu_matched:
                logger.info("画面検出: main_menu (類似度: %.2f)", menu_score)
                return True

            time.sleep(self.retry.poll_seconds)

        if best_join > 0 or best_menu > 0:
            logger.info(
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
        if self.buttons.get(button_key) or ui_point_for_key(self.ui, button_key):
            if not self._wait_for_button(button_key, wait_timeout):
                logger.warning("%s が %d 秒以内に表示されませんでした", label, int(wait_timeout))
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
                logger.info("画面検出: %s (類似度: %.2f)", screen_name, score)
                return True
            time.sleep(self.retry.poll_seconds)
        return False

    def _click(self, point: Point, label: str) -> None:
        abs_x, abs_y = self.ui.click_pixels(point)
        logger.info("%s を座標クリック (%d, %d)", label, abs_x, abs_y)
        input_handler.click(abs_x, abs_y)

    def _click_target(self, button_key: str, label: str) -> bool:
        """ボタン画像を優先してクリック。見つからなければ座標にフォールバック（image_only 除く）"""
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
                    logger.info(
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
            logger.warning(
                "%s のボタン画像を検出できませんでした（候補: %s）",
                label,
                ", ".join(paths),
            )

        if self.click_mode == "image_only":
            logger.error("%s のボタン画像が見つかりません（click_mode: image_only）", label)
            return False

        fallback = ui_point_for_key(self.ui, button_key)
        if fallback:
            self._click(fallback, f"{label}（座標フォールバック）")
            return True

        logger.error("%s のクリック先が未設定です（ボタン画像・座標ともに無し）", label)
        return False

    def _step1_join_server_list(self) -> bool:
        """① サーバー一覧で右下 JOIN"""
        self._set_state(LoginState.JOINING_SERVER)
        logger.info("① サーバー一覧 JOIN を実行します")
        if not self._click_target_when_ready("join_server_list", "① サーバー一覧 JOIN"):
            return False
        self._wait_after_click()
        return True

    def _step2_maybe_join_mods(self) -> bool:
        """② REQUIRED MODS（表示時のみ JOIN）"""
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
            logger.info(
                "② MODS 画面を検出 (画面: %s)",
                f"{score:.2f}" if score > 0 else "なし",
            )

            for attempt in range(2):
                self._focus_game()
                if not self._click_target_when_ready("join_mods", "② MODS JOIN"):
                    logger.warning("② MODS JOIN に失敗しました")
                    return False
                self._wait_after_click()
                if self._wait_for_mods_dismissed():
                    return True
                logger.warning("② MODS JOIN 後も画面が残っています（%d/2 回目）", attempt + 1)

            logger.warning("② MODS JOIN を実行しましたが画面が閉じませんでした")
            return False

        logger.info("② MODS 画面は表示されませんでした（スキップ）")
        return False

    def _step3_wait_for_login(self) -> str:
        """③ ログイン試行（待機のみ。失敗は ③-A / ⑥ のボタンで判定）"""
        self._set_state(LoginState.WAITING_LOGIN)
        started_at = time.time()
        deadline = started_at + self.retry.result_timeout
        movie_seen = False
        logger.info("③ ログイン試行を待機します")

        while self._running and time.time() < deadline:
            screen = self.vision.capture_screen()

            in_game, score = self._match_screen("in_game", screen=screen)
            if in_game:
                logger.info("ログイン成功画面を検出 (類似度: %.2f)", score)
                return "success"

            movie, movie_score = self._match_screen("login_movie", screen=screen)
            if movie:
                if not movie_seen:
                    movie_seen = True
                    movie_deadline = time.time() + self.retry.login_movie_timeout
                    deadline = max(deadline, movie_deadline)
                    logger.info(
                        "ログインムービー再生中。成功・失敗判定まで最大 %.0f 秒待機します",
                        self.retry.login_movie_timeout,
                    )
                else:
                    logger.debug("ログインムービー再生中 (類似度: %.2f)", movie_score)
                time.sleep(self.retry.poll_seconds)
                continue

            if self._has_network_failure_dialog(screen):
                logger.info("⑥ NETWORK FAILURE を検出（ACCEPT ボタン）")
                return "failure_network"

            if self._has_connection_failed_dialog(screen):
                logger.info("③-A CONNECTION FAILED を検出（CANCEL ボタン）")
                return "failure_browser"

            time.sleep(self.retry.poll_seconds)

        if not self._running:
            logger.info("ログイン試行を中断しました")
            return "stopped"

        logger.warning(
            "ログイン試行がタイムアウトしました（%.0f 秒経過）",
            time.time() - started_at,
        )
        return "timeout"

    def _recover_after_connection_failed(self) -> bool:
        """③-A CANCEL → ④ BACK → ⑤ JOIN GAME → ①"""
        self._set_state(LoginState.HANDLING_FAILURE)

        if not self._has_connection_failed_dialog():
            logger.warning("③-A: CANCEL ボタンが見えません")
            return False

        if not self._click_target_when_ready("cancel_failed", "③-A CANCEL"):
            return False
        self._wait_after_click()

        self._set_state(LoginState.RECOVERING)

        if not self._wait_for_button("back_empty_list", self.retry.recovery_timeout):
            logger.warning("④: BACK ボタンを検出できませんでした")
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
            logger.warning("メインメニュー / JOIN GAME を検出できませんでした")
            return False

        time.sleep(self.retry.transition_settle)
        if not self._click_target("join_game", "⑤ JOIN GAME"):
            return False
        self._wait_after_click()

        if not self._wait_for_step1_ready(self.retry.recovery_timeout):
            logger.warning("サーバー一覧画面に戻れませんでした")
            return False

        logger.info("リカバリー完了。① の状態に戻りました")
        return True

    def _wait_for_title_screen(self, timeout: float) -> bool:
        """⑦ タイトル画面（⑥ のダイアログ消去後）を待つ"""
        if Path(self.templates.title_screen).exists():
            return self._wait_for_screen("title_screen", timeout)

        deadline = time.time() + timeout
        while self._running and time.time() < deadline:
            if not self._has_network_failure_dialog():
                logger.info("⑦ タイトル画面に遷移しました（エラーダイアログ消失）")
                return True
            time.sleep(self.retry.poll_seconds)
        return False

    def _proceed_from_title_screen_to_main_menu(self) -> bool:
        """⑦ Space キー → ⑤ メインメニュー"""
        time.sleep(self.retry.transition_settle)
        input_handler.press_key("space")
        logger.info("⑦ Space キー押下")
        self._wait_after_click()
        return self._wait_for_step5_ready(self.retry.recovery_timeout)

    def _has_network_failure_setup(self) -> bool:
        return self.buttons.has("accept_network_failure") or self.ui.has_point(
            "accept_network_failure"
        )

    def _recover_after_network_failure(self) -> bool:
        """⑥ ACCEPT → ⑦ Space → ⑤ JOIN GAME → ① へ戻る"""
        self._set_state(LoginState.HANDLING_NETWORK_FAILURE)

        if not self._has_network_failure_setup():
            logger.error(
                "⑥ のリカバリーに必要な ACCEPT ボタン画像がありません。"
                "セットアップで⑥を登録するか、config の ui.accept_network_failure を設定してください"
            )
            return False

        if not self._has_network_failure_dialog():
            logger.warning("⑥: ACCEPT ボタンが見えません")
            return False

        if not self._click_target_when_ready("accept_network_failure", "⑥ ACCEPT"):
            return False
        self._wait_after_click()

        if not self._wait_for_title_screen(self.retry.recovery_timeout):
            logger.warning("⑦ タイトル画面を検出できませんでした")
            return False
        logger.info("⑦ タイトル画面を検出しました")

        if not self._proceed_from_title_screen_to_main_menu():
            logger.warning("⑤ メインメニューへ遷移できませんでした")
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
        logger.info("自動ログインを開始します")

        if not resolve_screen_path("server_list", self.templates.server_list):
            logger.error("server_list.png が未設定です。セットアップを実行してください")
            self._set_state(LoginState.FAILED)
            return LoginState.FAILED

        if not self.buttons.is_configured(self.ui):
            logger.error("ボタン画像または UI 座標が未設定です。セットアップを実行してください")
            self._set_state(LoginState.FAILED)
            return LoginState.FAILED

        while self._running:
            if not self._should_retry():
                logger.error("最大リトライ回数 (%d) に達しました", self.retry.max_attempts)
                self._set_state(LoginState.FAILED)
                return LoginState.FAILED

            self._stats.attempts += 1
            logger.info("=== 試行 %d回目 ===", self._stats.attempts)

            if not self._focus_game():
                logger.warning("ゲームウィンドウが見つかりません。続行します...")

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
                    logger.warning("② MODS 画面が残っています。③ には進みません")
                    self._stats.failures += 1
                    time.sleep(self.retry.delay_seconds)
                    continue

            result = self._step3_wait_for_login()

            if not self._running or result == "stopped":
                return LoginState.STOPPED

            if result == "success":
                self._set_state(LoginState.SUCCESS)
                logger.info(
                    "ログイン成功！ 試行回数: %d, 所要時間: %.0f秒",
                    self._stats.attempts,
                    self._stats.elapsed_seconds,
                )
                return LoginState.SUCCESS

            if result == "failure_browser":
                logger.info("③-A CONNECTION FAILED。③-A → ④ → ⑤ → ① の復帰を開始します")
                if not self._recover_after_connection_failed():
                    self._stats.failures += 1
                    logger.warning("③-A → ④ → ⑤ → ① の復帰に失敗しました")
            elif result == "failure_network":
                logger.info("⑥ NETWORK FAILURE。⑥ → ⑦ → ⑤ → ① の復帰を開始します")
                if not self._recover_after_network_failure():
                    self._stats.failures += 1
                    logger.warning("⑥ → ⑦ → ⑤ → ① の復帰に失敗しました")
            else:
                self._stats.failures += 1
                logger.warning("③ がタイムアウトしました。次の試行まで待機します")

            time.sleep(self.retry.delay_seconds)

        return LoginState.STOPPED
