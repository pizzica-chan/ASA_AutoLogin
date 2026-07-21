"""ディスプレイ・モニター情報"""

from __future__ import annotations

from dataclasses import dataclass

import mss


@dataclass
class MonitorInfo:
    index: int
    left: int
    top: int
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"モニター {self.index} ({self.width}x{self.height})"


def list_monitors() -> list[MonitorInfo]:
    with mss.MSS() as sct:
        monitors = []
        for i, mon in enumerate(sct.monitors[1:], start=1):
            monitors.append(
                MonitorInfo(
                    index=i,
                    left=mon["left"],
                    top=mon["top"],
                    width=mon["width"],
                    height=mon["height"],
                )
            )
        return monitors


def get_monitor(index: int) -> MonitorInfo:
    monitors = list_monitors()
    for mon in monitors:
        if mon.index == index:
            return mon
    if monitors:
        return monitors[0]
    raise RuntimeError("利用可能なモニターがありません")
