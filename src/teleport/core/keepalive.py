"""Keepalive của kết nối điều khiển (sans-IO): khi nào gửi `ping`, khi nào coi là mất kết nối.

Đặc tả ở docs/protocol.md mục 2.3. Module không xem đồng hồ: bên gọi (`teleport.net.connection`)
đưa thời gian monotonic `now` (giây) vào mọi lời gọi, báo mỗi lần gửi/nhận được dữ liệu,
rồi hỏi `poll(now)` xem phải làm gì.

Tính theo **byte**, không theo message: mỗi lần đọc được dữ liệu, kể cả một phần message,
đều là “nhận”. Nhờ vậy một message lớn đi chậm trên mạng yếu không bị coi là mất kết nối.
"""

from __future__ import annotations

import math
from enum import StrEnum

from teleport.core.numbers import is_finite

PING_INTERVAL = 10.0  # protocol §2.3: không gửi gì trong 10 s → gửi ping
DEAD_AFTER = 30.0  # protocol §2.3: không nhận byte nào trong 30 s → mất kết nối


class KeepaliveAction(StrEnum):
    """Việc bên gọi phải làm sau `poll`."""

    NONE = "none"
    SEND_PING = "send_ping"
    DEAD = "dead"  # mất kết nối: đóng


def _check_seconds(name: str, value: object) -> float:
    """Tham số thời gian: số hữu hạn > 0 (giây), không phải bool."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} phải là số giây")
    if not is_finite(value) or value <= 0:
        raise ValueError(f"{name} phải là số hữu hạn > 0")
    return float(value)


def _check_now(now: object, last: float | None) -> float:
    """`now` phải là số hữu hạn và không nhỏ hơn lần gọi trước của cùng đối tượng."""
    if isinstance(now, bool) or not isinstance(now, int | float):
        raise TypeError("now phải là số giây (đồng hồ monotonic)")
    if not is_finite(now):
        raise ValueError("now phải là số hữu hạn")
    if last is not None and now < last:
        raise ValueError("now không được nhỏ hơn lần gọi trước")
    return float(now)


class Keepalive:
    """Theo dõi lần gửi/nhận gần nhất của một kết nối điều khiển.

    `poll(now)`: không nhận gì trong `dead_after` → DEAD (dính: từ đó luôn DEAD); không
    gửi gì trong `ping_interval` → SEND_PING (và tính như vừa gửi, để gọi lại ngay không
    ra ping trùng); còn lại → NONE. DEAD được xét trước SEND_PING.
    """

    def __init__(
        self, now: float, *, ping_interval: float = PING_INTERVAL, dead_after: float = DEAD_AFTER
    ) -> None:
        """Tham số sai → TypeError / ValueError; cần `0 < ping_interval < dead_after`."""
        self._ping_interval = _check_seconds("ping_interval", ping_interval)
        self._dead_after = _check_seconds("dead_after", dead_after)
        if self._ping_interval >= self._dead_after:
            raise ValueError("ping_interval phải nhỏ hơn dead_after")
        self._last_now = _check_now(now, None)
        self._last_sent = self._last_now
        self._last_received = self._last_now
        self._dead = False

    @property
    def dead(self) -> bool:
        """Đã coi là mất kết nối (sau một lần `poll` trả DEAD)."""
        return self._dead

    def sent(self, now: float) -> None:
        """Vừa gửi được dữ liệu."""
        self._last_now = _check_now(now, self._last_now)
        self._last_sent = self._last_now

    def received(self, now: float) -> None:
        """Vừa nhận được dữ liệu (kể cả một phần message). Không làm “sống lại” khi đã DEAD."""
        self._last_now = _check_now(now, self._last_now)
        self._last_received = self._last_now

    def poll(self, now: float) -> KeepaliveAction:
        """Việc cần làm tại thời điểm `now`."""
        self._last_now = _check_now(now, self._last_now)
        if self._dead:
            return KeepaliveAction.DEAD
        if self._last_now - self._last_received >= self._dead_after:
            self._dead = True
            return KeepaliveAction.DEAD
        if self._last_now - self._last_sent >= self._ping_interval:
            # Bên gọi phải gửi ping ngay; tính luôn là đã gửi để không trả SEND_PING lần nữa.
            self._last_sent = self._last_now
            return KeepaliveAction.SEND_PING
        return KeepaliveAction.NONE

    def next_wakeup(self) -> float:
        """Thời điểm sớm nhất `poll` có thể trả khác NONE; `math.inf` khi đã DEAD."""
        if self._dead:
            return math.inf
        return min(self._last_sent + self._ping_interval, self._last_received + self._dead_after)
