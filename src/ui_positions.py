"""解像度非依存のUI座標管理"""

from __future__ import annotations

from dataclasses import dataclass

from .capture import CaptureSettings, resolve_capture_region


@dataclass
class Point:
    x_percent: float
    y_percent: float

    def to_pixels(self, width: int, height: int) -> tuple[int, int]:
        return int(width * self.x_percent / 100), int(height * self.y_percent / 100)


@dataclass
class UiPositions:
    """①〜⑤ループのクリック位置（パーセント座標）"""

    join_server_list: Point
    back_empty_list: Point
    join_game: Point
    join_mods: Point | None = None
    monitor_index: int = 1
    capture_settings: CaptureSettings | None = None

    @classmethod
    def from_dict(
        cls,
        data: dict,
        monitor_index: int = 1,
        *,
        capture_settings: CaptureSettings | None = None,
    ) -> UiPositions:
        def point(key: str, fallback_key: str | None = None, default: tuple[float, float] = (0, 0)) -> Point:
            src = data.get(key) or (data.get(fallback_key) if fallback_key else None) or {}
            return Point(
                x_percent=float(src.get("x_percent", default[0])),
                y_percent=float(src.get("y_percent", default[1])),
            )

        join_mods = data.get("join_mods")
        join_mods_point = None
        if join_mods:
            join_mods_point = Point(
                x_percent=float(join_mods.get("x_percent", 0)),
                y_percent=float(join_mods.get("y_percent", 0)),
            )

        settings = capture_settings or CaptureSettings(monitor_index=monitor_index)

        return cls(
            join_server_list=point("join_server_list", "join_button", (92.0, 92.0)),
            join_mods=join_mods_point,
            back_empty_list=point("back_empty_list", default=(5.0, 92.0)),
            join_game=point("join_game", default=(29.0, 91.0)),
            monitor_index=monitor_index,
            capture_settings=settings,
        )

    def is_configured(self, *, coordinates_only: bool = False) -> bool:
        required: tuple[Point, ...] = (
            self.join_server_list,
            self.back_empty_list,
            self.join_game,
        )
        return all(p.x_percent > 0 and p.y_percent > 0 for p in required)

    def has_point(self, key: str) -> bool:
        point = getattr(self, key, None)
        if point is None:
            return False
        return point.x_percent > 0 and point.y_percent > 0

    def iter_click_points(self) -> list[tuple[str, Point]]:
        points: list[tuple[str, Point]] = [
            ("join_server_list", self.join_server_list),
            ("back_empty_list", self.back_empty_list),
            ("join_game", self.join_game),
        ]
        if self.join_mods is not None:
            points.insert(1, ("join_mods", self.join_mods))
        return points

    def get_screen_size(self) -> tuple[int, int]:
        region = resolve_capture_region(
            self._capture_settings(),
            strict_window=self._capture_settings().mode == "window",
        )
        return region.width, region.height

    def click_pixels(self, point: Point) -> tuple[int, int]:
        region = resolve_capture_region(
            self._capture_settings(),
            strict_window=self._capture_settings().mode == "window",
        )
        rel_x, rel_y = point.to_pixels(region.width, region.height)
        return region.to_absolute(rel_x, rel_y)

    def _capture_settings(self) -> CaptureSettings:
        if self.capture_settings is not None:
            return self.capture_settings
        return CaptureSettings(monitor_index=self.monitor_index)

    def to_dict(self) -> dict:
        data = {
            "join_server_list": {
                "x_percent": self.join_server_list.x_percent,
                "y_percent": self.join_server_list.y_percent,
            },
            "back_empty_list": {
                "x_percent": self.back_empty_list.x_percent,
                "y_percent": self.back_empty_list.y_percent,
            },
            "join_game": {
                "x_percent": self.join_game.x_percent,
                "y_percent": self.join_game.y_percent,
            },
        }
        if self.join_mods:
            data["join_mods"] = {
                "x_percent": self.join_mods.x_percent,
                "y_percent": self.join_mods.y_percent,
            }
        return data
