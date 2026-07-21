"""解像度非依存のUI座標管理"""

from __future__ import annotations

from dataclasses import dataclass

from .display import get_monitor


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
    cancel_failed: Point
    back_empty_list: Point
    join_game: Point
    accept_network_failure: Point
    join_mods: Point | None = None
    monitor_index: int = 1

    @classmethod
    def from_dict(cls, data: dict, monitor_index: int = 1) -> UiPositions:
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

        return cls(
            join_server_list=point("join_server_list", "join_button", (92.0, 92.0)),
            join_mods=join_mods_point,
            cancel_failed=point("cancel_failed", default=(55.0, 55.0)),
            accept_network_failure=point("accept_network_failure", default=(0.0, 0.0)),
            back_empty_list=point("back_empty_list", default=(5.0, 92.0)),
            join_game=point("join_game", default=(29.0, 91.0)),
            monitor_index=monitor_index,
        )

    def is_configured(self) -> bool:
        required = (
            self.join_server_list,
            self.cancel_failed,
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
            ("cancel_failed", self.cancel_failed),
            ("back_empty_list", self.back_empty_list),
            ("join_game", self.join_game),
            ("accept_network_failure", self.accept_network_failure),
        ]
        if self.join_mods is not None:
            points.insert(1, ("join_mods", self.join_mods))
        return points

    def get_screen_size(self) -> tuple[int, int]:
        monitor = get_monitor(self.monitor_index)
        return monitor.width, monitor.height

    def click_pixels(self, point: Point) -> tuple[int, int]:
        w, h = self.get_screen_size()
        return self.to_absolute(*point.to_pixels(w, h))

    def to_absolute(self, x: int, y: int) -> tuple[int, int]:
        monitor = get_monitor(self.monitor_index)
        return monitor.left + x, monitor.top + y

    def to_dict(self) -> dict:
        data = {
            "join_server_list": {
                "x_percent": self.join_server_list.x_percent,
                "y_percent": self.join_server_list.y_percent,
            },
            "cancel_failed": {
                "x_percent": self.cancel_failed.x_percent,
                "y_percent": self.cancel_failed.y_percent,
            },
            "accept_network_failure": {
                "x_percent": self.accept_network_failure.x_percent,
                "y_percent": self.accept_network_failure.y_percent,
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
