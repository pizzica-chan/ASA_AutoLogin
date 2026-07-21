"""ボタン画像テンプレート（ハイブリッドクリック用）"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .default_assets import USER_BUTTONS_DIR, list_button_paths, resolve_button_path
from .ui_positions import Point, UiPositions

BUTTONS_DIR = USER_BUTTONS_DIR

REQUIRED_BUTTONS = (
    "join_server_list",
    "cancel_failed",
    "back_empty_list",
    "join_game",
)

OPTIONAL_BUTTONS = (
    "join_mods",
    "accept_network_failure",
)


@dataclass
class ButtonConfig:
    """ボタン画像のパスとマッチング閾値"""

    paths: dict[str, str] = field(default_factory=dict)
    threshold: float = 0.75
    threshold_relaxed: float = 0.68

    @classmethod
    def from_dict(cls, data: dict, matching: dict | None = None) -> ButtonConfig:
        matching = matching or {}
        paths = {k: str(v) for k, v in (data or {}).items()}
        threshold = float(matching.get("button_threshold", matching.get("threshold", 0.75)))
        threshold_relaxed = float(matching.get("button_threshold_relaxed", 0.68))
        return cls(paths=paths, threshold=threshold, threshold_relaxed=threshold_relaxed)

    def get(self, key: str) -> str | None:
        user_path = self.paths.get(key)
        return resolve_button_path(key, user_path)

    def list_paths(self, key: str) -> list[str]:
        return list_button_paths(key, self.paths.get(key))

    def has(self, key: str) -> bool:
        return self.get(key) is not None

    def is_configured(self, ui: UiPositions) -> bool:
        """① の JOIN が使えれば開始可能（エラー系は同梱デフォルトで補完）"""
        return self.has("join_server_list") or ui.has_point("join_server_list")

    def to_dict(self) -> dict[str, str]:
        return {
            key: path
            for key in (*REQUIRED_BUTTONS, *OPTIONAL_BUTTONS)
            if (path := self.get(key))
        }


def extract_and_save_button_crop(
    image_path: Path,
    click_x: int,
    click_y: int,
    output_path: Path,
    width_ratio: float = 0.10,
    height_ratio: float = 0.06,
    min_width: int = 80,
    min_height: int = 36,
) -> Path:
    """クリック位置を中心にボタン領域を切り出して保存"""
    import cv2

    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"画像の読み込みに失敗しました: {image_path}")

    img_h, img_w = image.shape[:2]
    crop_w = min(img_w, max(min_width, int(img_w * width_ratio)))
    crop_h = min(img_h, max(min_height, int(img_h * height_ratio)))

    left = max(0, min(click_x - crop_w // 2, img_w - crop_w))
    top = max(0, min(click_y - crop_h // 2, img_h - crop_h))
    right = left + crop_w
    bottom = top + crop_h

    crop = image[top:bottom, left:right]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), crop)
    return output_path


def ui_point_for_key(ui: UiPositions, key: str) -> Point | None:
    point = getattr(ui, key, None)
    if point is None or not ui.has_point(key):
        return None
    return point
