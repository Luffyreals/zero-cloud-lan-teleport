"""Gộp bóng thoại “Đã nhận…” khi nhiều lượt nhận xong gần nhau (theo dõi tiến độ khi chạy nền,
`plan-f-ux-hang-ngay` F4; mvp F9, mục 8 “Giao diện: nhận xong một lượt”).

`ReceivedBatch` là phần thuần (nhận `now` monotonic do bên gọi đưa, giây): mỗi lượt nhận DONE mà người
dùng không đang xem đúng cuộc trò chuyện đó (`TransfersController.thread_in_view`) được `add` vào một
nhóm. Nhóm hiện **một** bóng thoại sau `NOTIFY_QUIET` giây không có lượt nào xong thêm, nhưng không
chờ quá `NOTIFY_MAX_WAIT` giây tính từ lượt đầu của nhóm (`due(now)`). `ui.transfers` hẹn một `QTimer`
một lần theo `due`, rồi `take()` → `received_batch_text` + `batch_reveal` → `Tray.show_message`.
`due` ≤ 0 ngay sau `add` (ví dụ hai hằng bằng 0, như fixture tự động của `tests/ui/conftest.py`) thì
bên gọi hiện đồng bộ. Bóng thoại “Có file đang chờ bạn nhận.” không đi qua đây (không bị gộp).

Nhóm giữ: số lượt, tổng số file, các máy (`device_id` → tên đã qua `texts.peer_label`, thứ tự lần đầu
gặp, tên mới nhất), tên file khi nhóm chỉ có một lượt, tối đa `shell.REVEAL_MAX_ITEMS` đường dẫn đã lưu
cuối cùng (cắt lại mỗi lần `add`, đọc hằng lúc dùng) và thư mục nhận của lượt cuối (`root`).

Câu (`received_batch_text`, ngữ cảnh `"Transfers"`, chuỗi nguồn giữ nguyên câu cũ của mvp mục 8):
một lượt một file có tên → “Đã nhận {file} từ {name}.” (`texts.file_label`); một máy → “Đã nhận %n
file từ {name}.”; từ hai máy → “Đã nhận %n file từ {devices} máy.” (`%n` là tổng số file). Bóng thoại
khay là chữ thuần.

`batch_reveal`: `shell.Reveal(files, root, folder=root khi không có đường dẫn)`; không đường dẫn và
không `root` → None (bấm bóng thoại thì chỉ đưa cửa sổ lên trước).

Hằng là biến cấp module, **đọc lúc dùng** (test vá được).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from teleport.ui import shell, texts

NOTIFY_QUIET = 3.0  # giây không có lượt nào xong thêm thì hiện bóng thoại
NOTIFY_MAX_WAIT = 10.0  # giây tối đa tính từ lượt đầu của nhóm


@dataclass(frozen=True, slots=True)
class ReceivedSummary:
    """Một nhóm lượt nhận xong, lấy ra bằng `ReceivedBatch.take()`."""

    transfers: int  # số lượt
    files: int  # tổng số file
    peers: tuple[str, ...]  # tên các máy (đã qua `texts.peer_label`), thứ tự lần đầu gặp
    single_name: str | None  # tên file khi nhóm chỉ có một lượt (chưa qua `file_label`)
    paths: tuple[Path, ...]  # đường dẫn đã lưu, tối đa `shell.REVEAL_MAX_ITEMS` cuối
    root: Path | None  # thư mục nhận của lượt cuối


class ReceivedBatch:
    """Nhóm lượt nhận xong đang chờ hiện bóng thoại (xem docstring module)."""

    def __init__(self) -> None:
        self.transfers = 0  # số lượt
        self.files = 0  # tổng số file
        self.peers: dict[str, str] = {}  # device_id → tên (thứ tự lần đầu gặp, tên mới nhất)
        self.single_name: str | None = None  # tên file khi chỉ có một lượt
        self.paths: list[Path] = []  # đường dẫn đã lưu, tối đa `shell.REVEAL_MAX_ITEMS` cuối
        self.root: Path | None = None  # thư mục nhận của lượt cuối
        self._first: float | None = None  # `now` của lượt đầu
        self._last: float | None = None  # `now` của lượt cuối

    def __len__(self) -> int:
        return self.transfers

    def clear(self) -> None:
        self.transfers = 0
        self.files = 0
        self.peers = {}
        self.single_name = None
        self.paths = []
        self.root = None
        self._first = None
        self._last = None

    def add(
        self,
        device_id: str,
        peer: str,
        file_count: int,
        saved_paths: Iterable[Path],
        single_name: str | None,
        root: Path | None,
        now: float,
    ) -> None:
        """Thêm một lượt nhận DONE lúc `now`. `peer` đã qua `texts.peer_label`; `single_name` là tên
        file thật đã lưu (hay tên trong `offer`) khi lượt có một file, không thì None."""
        self.transfers += 1
        self.files += max(0, int(file_count))
        self.peers[device_id] = peer  # máy đã có giữ chỗ cũ, tên mới nhất
        self.single_name = single_name if self.transfers == 1 else None
        limit = max(1, int(shell.REVEAL_MAX_ITEMS))
        self.paths = [*self.paths, *saved_paths][-limit:]
        self.root = root
        if self._first is None:
            self._first = now
        self._last = now

    def due(self, now: float) -> float | None:
        """Giây còn tới lúc hiện bóng thoại (≥ 0); nhóm rỗng → None."""
        if self._first is None or self._last is None:
            return None
        at = min(self._last + float(NOTIFY_QUIET), self._first + float(NOTIFY_MAX_WAIT))
        return max(0.0, at - now)

    def take(self) -> ReceivedSummary | None:
        """Lấy nhóm hiện tại rồi xóa; rỗng → None."""
        if not self.transfers:
            return None
        summary = ReceivedSummary(
            transfers=self.transfers,
            files=self.files,
            peers=tuple(self.peers.values()),
            single_name=self.single_name,
            paths=tuple(self.paths),
            root=self.root,
        )
        self.clear()
        return summary


def received_batch_text(summary: ReceivedSummary) -> str:
    """Câu của bóng thoại “Đã nhận…” cho một nhóm (xem docstring module)."""
    t = QCoreApplication.translate
    name = summary.peers[-1] if summary.peers else ""
    if summary.transfers == 1 and summary.files == 1 and summary.single_name:
        return texts.fill(
            t("Transfers", "Đã nhận {file} từ {name}."), file=texts.file_label(summary.single_name), name=name
        )
    if len(summary.peers) <= 1:
        return texts.fill(t("Transfers", "Đã nhận %n file từ {name}.", None, summary.files), name=name)
    return texts.fill(
        t("Transfers", "Đã nhận %n file từ {devices} máy.", None, summary.files),
        devices=str(len(summary.peers)),
    )


def batch_reveal(summary: ReceivedSummary) -> shell.Reveal | None:
    """Payload bấm bóng thoại của nhóm: `Reveal`, hay None khi không có đường dẫn lẫn thư mục nhận."""
    if not summary.paths and summary.root is None:
        return None
    return shell.Reveal(
        files=summary.paths, root=summary.root, folder=summary.root if not summary.paths else None
    )
