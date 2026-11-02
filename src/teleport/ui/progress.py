"""% tổng của các lượt đang truyền cho tiêu đề cửa sổ và tooltip khay (theo dõi tiến độ khi chạy nền,
`plan-f-ux-hang-ngay` F4; mvp F9, N12).

Module thuần, **không import PySide6** và không import module `ui` nào khác (test kiểm): `ui.transfers`
dựng `ProgressItem` từ các bong bóng của phiên (`ChatView.rows()`), đưa vào `ProgressBatch` rồi
`ProgressThrottle`, và đẩy cùng một giá trị vào `MainWindow.set_progress` và `Tray.set_progress`.
Không gọi node, không polling.

**Đợt** (`ProgressBatch.update(items) -> int | None`): % tính theo **byte**, gộp gửi lẫn nhận, trên
một “đợt” lượt:
- Lượt `moving` (chưa kết thúc, TRANSFERRING hay VERIFYING) vào đợt. Lượt `queued_send` (QUEUED chiều
  gửi, nối sau lượt trước cùng máy) vào đợt khi đợt đang có thành viên. WAITING, RECONNECTING và
  QUEUED chiều nhận không tự vào đợt (tránh tiêu đề treo khi chờ trả lời hay chờ nối lại).
- Thành viên kết thúc DONE: nhớ `total` lúc thấy DONE, ở lại tới khi cả đợt xong (bong bóng DONE bị
  luồng chat gỡ vẫn tính). Thành viên kết thúc khác DONE: bỏ khỏi cả tử lẫn mẫu. Thành viên chưa kết
  thúc mà không còn bong bóng: bỏ.
- Không còn thành viên chưa kết thúc → xóa đợt, trả None (đợt sau bắt đầu trống).
- Không thành viên nào đang `moving` (ví dụ RECONNECTING giữa chừng) → None nhưng **giữ** đợt; chạy lại
  thì tính tiếp.
- Còn lại: tử = Σ(`total` nếu DONE, không thì `shown` kẹp 0…`total`), mẫu = Σ`total`; kết quả
  `min(99, tử * 100 // mẫu)`, mẫu 0 → 0. Lượt mới vào giữa chừng có thể làm % giảm: chấp nhận.

**Mốc và nhịp** (`ProgressThrottle`, mvp N12): giá trị hiển thị làm tròn xuống bội của `TITLE_STEP`
(`quantize`, 0…95: lượt chưa xong không bao giờ hiện 100%), đổi số cách nhau ít nhất
`TITLE_MIN_INTERVAL` giây. Kết thúc (đích None) áp ngay; bắt đầu chỉ áp ngay khi lần đổi trước đã quá
`TITLE_MIN_INTERVAL` (hay chưa đổi lần nào); còn lại giữ đích, `pending_delay(now)` cho bên gọi hẹn
giờ áp sau. `now` là đồng hồ monotonic do bên gọi đưa (giây).

**Trình đọc màn hình**: `setWindowTitle` tự phát `QAccessible::NameChanged`; code không phát event nào
**thêm**, nhịp ≥ `TITLE_MIN_INTERVAL` là chặn duy nhất. Kiểm tay E1 (NVDA, Narrator): trình đọc có đọc
tiêu đề mỗi lần đổi khi cửa sổ đang active không. Dự phòng, chỉ làm nếu E1 thấy bị đọc: khi cửa sổ
chính đang active thì tiêu đề giữ `APP_NAME` (tooltip khay vẫn có %).

Hằng là biến cấp module, **đọc lúc dùng** (test vá được).
"""

from __future__ import annotations

from collections.abc import Hashable, Iterable
from dataclasses import dataclass

TITLE_STEP = 5  # % hiển thị làm tròn xuống bội của số này
TITLE_MIN_INTERVAL = 5.0  # giây tối thiểu giữa hai lần đổi số trên tiêu đề / tooltip


@dataclass(frozen=True, slots=True)
class ProgressItem:
    """Một lượt của phiên, đọc từ bong bóng của nó (`ui.transfers` dựng)."""

    key: Hashable
    shown: int  # byte đã hiển thị (không lùi)
    total: int  # tổng byte
    finished: bool  # đã kết thúc (mọi kết quả)
    done: bool  # kết thúc với `TransferResult.DONE`
    moving: bool  # chưa kết thúc và đang TRANSFERRING hay VERIFYING
    queued_send: bool = False  # chưa kết thúc, chiều gửi, QUEUED (nối sau lượt trước cùng máy)


def quantize(percent: int) -> int:
    """% để hiện: kẹp 0…99 rồi làm tròn xuống bội của `TITLE_STEP` (`quantize(62) == 60`)."""
    step = max(1, int(TITLE_STEP))
    value = min(99, max(0, int(percent)))
    return value // step * step


class ProgressBatch:
    """Đợt lượt đang tính % tổng (xem docstring module)."""

    def __init__(self) -> None:
        self._members: dict[Hashable, None] = {}  # thành viên theo thứ tự vào đợt
        self._done: dict[Hashable, int] = {}  # thành viên đã DONE → `total` lúc thấy DONE

    def __len__(self) -> int:
        return len(self._members)

    def clear(self) -> None:
        self._members = {}
        self._done = {}

    def update(self, items: Iterable[ProgressItem]) -> int | None:
        """Cập nhật đợt theo các lượt hiện có; trả % tổng (0…99) hay None (xem docstring module)."""
        by_key = {item.key: item for item in items}
        live: dict[Hashable, ProgressItem] = {}  # thành viên chưa kết thúc
        for key in list(self._members):
            if key in self._done:
                continue
            item = by_key.get(key)
            if item is None:
                del self._members[key]  # không còn bong bóng
            elif item.finished:
                if item.done:
                    self._done[key] = max(0, item.total)
                else:
                    del self._members[key]  # lỗi, hủy, từ chối: bỏ khỏi tử lẫn mẫu
            else:
                live[key] = item
        for item in by_key.values():
            if item.key not in self._members and not item.finished and item.moving:
                self._members[item.key] = None
                live[item.key] = item
        if self._members:
            for item in by_key.values():
                if item.key not in self._members and not item.finished and item.queued_send:
                    self._members[item.key] = None
                    live[item.key] = item
        if not live:
            self.clear()
            return None
        if not any(item.moving for item in live.values()):
            return None
        done_total = sum(self._done.values())
        numerator = done_total + sum(min(max(0, item.shown), max(0, item.total)) for item in live.values())
        denominator = done_total + sum(max(0, item.total) for item in live.values())
        if denominator <= 0:
            return 0
        return min(99, numerator * 100 // denominator)


class ProgressThrottle:
    """Mốc `TITLE_STEP` và nhịp `TITLE_MIN_INTERVAL` của giá trị hiển thị (xem docstring module)."""

    def __init__(self) -> None:
        self._shown: int | None = None  # giá trị đang hiển thị
        self._pending: int | None = None  # đích đang giữ để áp sau
        self._changed_at: float | None = None  # `now` của lần đổi gần nhất

    @property
    def shown(self) -> int | None:
        return self._shown

    def reset(self) -> None:
        self._shown = None
        self._pending = None
        self._changed_at = None

    def feed(self, percent: int | None, now: float) -> int | None:
        """Đưa % thô (`ProgressBatch.update`) lúc `now`; trả giá trị đang hiển thị sau lần đưa này."""
        target = None if percent is None else quantize(percent)
        if target == self._shown:
            self._pending = None
            return self._shown
        if target is None or self._interval_passed(now):
            self._shown = target
            self._changed_at = now
            self._pending = None
        else:
            self._pending = target
        return self._shown

    def pending_delay(self, now: float) -> float | None:
        """Giây còn tới lúc áp được đích đang giữ (≥ 0), hay None khi không giữ gì."""
        if self._pending is None or self._changed_at is None:
            return None
        return max(0.0, self._changed_at + float(TITLE_MIN_INTERVAL) - now)

    def _interval_passed(self, now: float) -> bool:
        return self._changed_at is None or now - self._changed_at >= float(TITLE_MIN_INTERVAL)
