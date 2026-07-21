"""画面キャプチャとテンプレートマッチング"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import mss
import numpy as np

from .app_logging import detail_log
from .display import MonitorInfo, get_monitor

# 画面内の矩形（幅・高さに対する比率 0.0〜1.0）
SearchRegion = tuple[float, float, float, float]


@dataclass
class MatchResult:
    found: bool
    confidence: float
    center_x: int
    center_y: int
    top_left: tuple[int, int]
    bottom_right: tuple[int, int]


class Vision:
    def __init__(self, threshold: float = 0.8, monitor_index: int = 1):
        self.threshold = threshold
        self.monitor_index = monitor_index
        self._sct = mss.mss()
        self._monitor = get_monitor(monitor_index)

    def set_monitor(self, monitor_index: int) -> None:
        self.monitor_index = monitor_index
        self._monitor = get_monitor(monitor_index)
        detail_log.info("キャプチャモニターを変更: %s", self._monitor.label)

    @property
    def monitor(self) -> MonitorInfo:
        return self._monitor

    def to_absolute(self, x: int, y: int) -> tuple[int, int]:
        return self._monitor.left + x, self._monitor.top + y

    def capture_screen(self) -> np.ndarray:
        monitor = self._sct.monitors[self.monitor_index]
        screenshot = self._sct.grab(monitor)
        frame = np.array(screenshot)
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    def load_template(self, path: str | Path) -> np.ndarray | None:
        template_path = Path(path)
        cache_key = str(template_path.resolve())
        cached = getattr(self, "_template_cache", None)
        if cached is not None and cache_key in cached:
            return cached[cache_key]

        if not template_path.exists():
            detail_log.warning("テンプレートが見つかりません: %s", template_path)
            return None
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None:
            detail_log.warning("テンプレートの読み込みに失敗: %s", template_path)
            return None

        if not hasattr(self, "_template_cache"):
            self._template_cache: dict[str, np.ndarray] = {}
        self._template_cache[cache_key] = template
        return template

    def find_template(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float | None = None,
    ) -> MatchResult:
        threshold = self.threshold if threshold is None else threshold
        result_h, result_w = template.shape[:2]
        match = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(match)

        if max_val < threshold:
            return MatchResult(False, float(max_val), 0, 0, (0, 0), (0, 0))

        top_left = max_loc
        bottom_right = (top_left[0] + result_w, top_left[1] + result_h)
        rel_x = top_left[0] + result_w // 2
        rel_y = top_left[1] + result_h // 2
        abs_x, abs_y = self.to_absolute(rel_x, rel_y)

        return MatchResult(
            found=True,
            confidence=float(max_val),
            center_x=abs_x,
            center_y=abs_y,
            top_left=top_left,
            bottom_right=bottom_right,
        )

    def find_button_on_screen(
        self,
        template_path: str | Path,
        threshold: float | None = None,
        screen: np.ndarray | None = None,
        extra_scales: tuple[float, ...] = (0.92, 0.96, 1.04, 1.08),
        region: SearchRegion | None = None,
    ) -> MatchResult:
        """ボタン検索（1回のキャプチャ・段階的スケールで高速化）"""
        template = self.load_template(template_path)
        if template is None:
            return MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))

        if screen is None:
            screen = self.capture_screen()

        search_screen = screen
        offset_x = 0
        offset_y = 0
        if region is not None:
            height, width = screen.shape[:2]
            x1 = max(0, int(width * region[0]))
            y1 = max(0, int(height * region[1]))
            x2 = min(width, int(width * region[2]))
            y2 = min(height, int(height * region[3]))
            if x2 > x1 and y2 > y1:
                search_screen = screen[y1:y2, x1:x2]
                offset_x, offset_y = x1, y1

        match_threshold = self.threshold if threshold is None else threshold
        result = self._find_template_with_offset(
            search_screen, template, match_threshold, offset_x, offset_y
        )
        if result.found:
            return result

        best = result
        for scale in extra_scales:
            width = max(10, int(template.shape[1] * scale))
            height = max(10, int(template.shape[0] * scale))
            interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
            scaled = cv2.resize(template, (width, height), interpolation=interpolation)
            scaled_result = self._find_template_with_offset(
                search_screen, scaled, match_threshold, offset_x, offset_y
            )
            if scaled_result.confidence > best.confidence:
                best = scaled_result
            if scaled_result.found:
                return scaled_result

        return best

    def _find_template_with_offset(
        self,
        screen: np.ndarray,
        template: np.ndarray,
        threshold: float,
        offset_x: int,
        offset_y: int,
    ) -> MatchResult:
        result_h, result_w = template.shape[:2]
        match = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(match)

        if max_val < threshold:
            return MatchResult(False, float(max_val), 0, 0, (0, 0), (0, 0))

        top_left = (max_loc[0] + offset_x, max_loc[1] + offset_y)
        bottom_right = (top_left[0] + result_w, top_left[1] + result_h)
        rel_x = top_left[0] + result_w // 2
        rel_y = top_left[1] + result_h // 2
        abs_x, abs_y = self.to_absolute(rel_x, rel_y)

        return MatchResult(
            found=True,
            confidence=float(max_val),
            center_x=abs_x,
            center_y=abs_y,
            top_left=top_left,
            bottom_right=bottom_right,
        )

    def find_on_screen(
        self,
        template_path: str | Path,
        threshold: float | None = None,
    ) -> MatchResult:
        template = self.load_template(template_path)
        if template is None:
            return MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))
        screen = self.capture_screen()
        return self.find_template(screen, template, threshold)

    def find_on_screen_multiscale(
        self,
        template_path: str | Path,
        threshold: float | None = None,
        scales: tuple[float, ...] = (0.85, 0.9, 0.95, 1.0, 1.05, 1.1, 1.15),
    ) -> MatchResult:
        """後方互換: find_button_on_screen へ委譲"""
        _ = scales
        return self.find_button_on_screen(template_path, threshold=threshold)

    def find_any_on_screen(
        self,
        template_paths: list[str | Path],
        threshold: float | None = None,
    ) -> tuple[MatchResult, str | None]:
        screen = self.capture_screen()
        best = MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))
        best_path: str | None = None

        for path in template_paths:
            template = self.load_template(path)
            if template is None:
                continue
            result = self.find_template(screen, template, threshold)
            if result.found and result.confidence > best.confidence:
                best = result
                best_path = str(path)

        return best, best_path

    def compare_with_reference(
        self,
        reference_path: str | Path,
        threshold: float | None = None,
        compare_size: tuple[int, int] = (320, 180),
        screen: np.ndarray | None = None,
    ) -> MatchResult:
        """画面全体と参照画像の類似度を比較（フルスクリーンテンプレート用）"""
        threshold = self.threshold if threshold is None else threshold
        reference = self.load_template(reference_path)
        if reference is None:
            return MatchResult(False, 0.0, 0, 0, (0, 0), (0, 0))

        if screen is None:
            screen = self.capture_screen()
        score = self._screen_similarity(screen, reference, compare_size)
        found = score >= threshold
        if found:
            detail_log.debug("画面一致: %s (類似度: %.2f)", reference_path, score)
        return MatchResult(found, score, 0, 0, (0, 0), (0, 0))

    @staticmethod
    def _screen_similarity(
        screen: np.ndarray,
        reference: np.ndarray,
        size: tuple[int, int],
    ) -> float:
        s = cv2.resize(screen, size).astype(np.float32)
        r = cv2.resize(reference, size).astype(np.float32)
        s = (s - s.mean()) / (s.std() + 1e-6)
        r = (r - r.mean()) / (r.std() + 1e-6)
        return float(np.mean(s * r))

    def detect_best_screen(
        self,
        screens: dict[str, str | Path],
        threshold: float,
        compare_size: tuple[int, int] = (320, 180),
        screen: np.ndarray | None = None,
    ) -> tuple[str | None, float]:
        """複数の参照画像と比較し、最も類似度が高い画面名を返す"""
        if screen is None:
            screen = self.capture_screen()
        best_name: str | None = None
        best_score = 0.0

        for name, path in screens.items():
            reference = self.load_template(path)
            if reference is None:
                continue
            score = self._screen_similarity(screen, reference, compare_size)
            if score > best_score:
                best_score = score
                best_name = name

        if best_name and best_score >= threshold:
            return best_name, best_score
        return None, best_score
