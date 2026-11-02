"""Bong bóng của luồng chat `teleport.ui.chat_bubbles` (spec B3 mục 4, mục 9 thắng; T-B: B1–B7).

Viết từ spec, không từ code.

- B1: ba hàm thuần `file_icon`, `needs_separator`, `separator_text`.
- B2–B7: `TransferBubble` dựng qua `ChatView.handle` (mục 5: `ChatView` giữ API của `TransfersView`;
  `view.row(key)` chỉ trả bong bóng của phiên, 9.11). Sự kiện giả dựng bằng dataclass thật của
  `teleport.app.transfers` / `teleport.core.transfer` (không socket).

Seam: `teleport.ui.chat._wall_now` (9.13, đọc lúc gọi) cho `at` của bong bóng phiên;
`teleport.ui.chat.open_url`
(mục 2: seam dời từ `transfers_view` sang `chat`).

Chữ: câu mvp mục 8 lấy bằng chính hàm chữ thuần còn lại trong `ui/transfers_view.py` (`result_message`,
`result_status`, `done_text`) vì spec nói “giữ nguyên chữ”; chữ mới của B3 (“Đã lưu”, “Đã gửi”, “Gửi lại”,
“Hôm nay …”) chép từ spec.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"

# ---- Chữ mới của B3 (spec mục 4, 9.8) -----------------------------------------------------------
SAVED = "Đã lưu"
SENT = "Đã gửi"
OPEN_FOLDER = "Hiện trong thư mục"  # spec-f4 mục 2.4 (trước: “Mở thư mục”)
RESEND = "Gửi lại"
CANCEL = "Hủy"

# Giờ địa phương cố định cho các bong bóng của phiên.
NOW = datetime.datetime(2026, 10, 31, 10, 40).timestamp()
MiB = 2**20


# =================================================================================================
# Hàm phụ trợ (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


class Clock:
    """Đồng hồ treo tường giả cho seam `chat._wall_now`."""

    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def key(direction: str = "send", transfer_id: str = "c" * 32, device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), transfer_id)


def entry(index: int, name: str, size: int):
    from teleport.core.messages import FileEntry, MessageError

    try:
        return FileEntry(name, size, 1_700_000_000_000)
    except MessageError:
        return FileEntry(f"raw{index}.bin", size, 1_700_000_000_000)


def info(k, status="transferring", files=(("video.mp4", 1000 * MiB),), done=0, total=None, unsynced=0):
    from teleport.core.transfer import TransferInfo, TransferStatus

    entries = tuple(entry(i, n, s) for i, (n, s) in enumerate(files))
    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=entries,
        names=tuple(n for n, _ in files),
        file_index=0,
        done_bytes=done,
        total_bytes=sum(s for _, s in files) if total is None else total,
        unsynced_bytes=unsynced,
    )


def status_changed(k, status: str, **kw):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(info(k, status, **kw))


def progress(k, shown: int, total: int = 1000 * MiB, bps: float = 85.2 * MiB, eta=62.0, **kw):
    from teleport.app.transfers import TransferProgress

    return TransferProgress(
        info(k, kw.pop("status", "transferring"), total=total, **kw),
        bps,
        eta,
        shown_bytes=shown,
        idle_seconds=0.0,
    )


def finished(k, result: str, *, by_peer: bool = False, status: str = "transferring", **kw):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info(k, status, **kw),
        result=TransferResult(result),
        by_peer=by_peer,
        reason=None,
        file_index=0,
        reject=None,
    )


def file_done(k, path: Path | None, index: int = 0, name: str = "video.mp4"):
    from teleport.app.transfers import FileDone

    return FileDone(key=k, file_index=index, name=name, path=path)


def dview(device_id: str, name: str, *, online: bool = True, connected: bool = True):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=True,
        online=online,
        connected=connected,
        addresses=("192.0.2.7",) if online else (),
        port=47474 if online else None,
    )


def label_texts(widget) -> list[str]:
    """Chữ mọi `QLabel` đang hiện (so với `widget`) bên trong `widget`."""
    return [lb.text() for lb in widget.findChildren(QLabel) if lb.isVisibleTo(widget) and lb.text()]


def bubble_text(bubble) -> str:
    """Mọi chữ hiện trên bong bóng, cộng tên đầy đủ của tiêu đề (tiêu đề có thể bị cắt giữa)."""
    parts = label_texts(bubble)
    full = bubble.title_label.accessibleName()
    if full:
        parts.append(full)
    return "\n".join(parts)


def shown(widget, root) -> bool:
    return widget.isVisibleTo(root)


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def settle() -> None:
    for _ in range(3):
        QApplication.processEvents()


@pytest.fixture
def clock(monkeypatch):
    from teleport.ui import chat

    c = Clock(NOW)
    monkeypatch.setattr(chat, "_wall_now", c)
    return c


@pytest.fixture
def view(qtbot, clock):
    """`ChatView` đứng riêng, hai máy đã ghép đôi trong `DeviceListModel`, đang mở luồng của PC-Nha."""
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    devices = DeviceListModel()
    devices.reset([dview(PEER_ID, PEER), dview(OTHER_ID, OTHER)])
    v = ChatView(devices)
    v._test_devices = devices  # type: ignore[attr-defined]  # giữ model sống cùng view
    qtbot.addWidget(v)
    v.set_device_names({PEER_ID: PEER, OTHER_ID: OTHER})
    v.set_connected(PEER_ID, True)
    v.set_device(PEER_ID)
    v.resize(720, 560)
    v.show()
    qtbot.waitExposed(v)
    v.cancels = []  # type: ignore[attr-defined]
    v.resends = []  # type: ignore[attr-defined]
    v.cancel_requested.connect(v.cancels.append)
    v.resend_requested.connect(v.resends.append)
    return v


# =================================================================================================
# B1 hàm thuần
# =================================================================================================


@pytest.mark.parametrize(
    ("names", "count", "expected"),
    [
        (["phim.mp4"], 1, "video"),
        (["anh.jpg"], 1, "image"),
        (["anh.png"], 1, "image"),
        (["bai-hat.mp3"], 1, "music_note_2"),
        (["bao-cao.pdf"], 1, "document_pdf"),
        (["du-an.zip"], 1, "folder_zip"),
        (["ghi-chu.txt"], 1, "document"),
        (["khong-duoi"], 1, "document"),
        (["phim.mp4", "anh.jpg"], 2, "document"),
        (["phim.mp4"], 3, "document"),  # >1 file (names có thể bị cắt) → document
        ([], 1, "document"),
    ],
)
def test_b1_file_icon_by_extension_and_count(names, count, expected):
    from teleport.ui.chat_bubbles import file_icon

    assert file_icon(names, count) == expected


def test_b1_file_icon_names_exist_at_20_px():
    """Mọi icon `file_icon` trả về đều có sẵn ở cỡ 20 (9.18: cỡ khác → KeyError)."""
    from teleport.ui import icons
    from teleport.ui.chat_bubbles import file_icon

    for name in ("a.mp4", "a.jpg", "a.mp3", "a.pdf", "a.zip", "a.txt"):
        icon = file_icon([name], 1)
        assert 20 in icons.SIZES[icon], icon


def _local(y, mo, d, h, mi) -> float:
    return datetime.datetime(y, mo, d, h, mi).timestamp()


def test_b1_separator_gap_is_one_hour():
    from teleport.ui.chat_bubbles import SEPARATOR_GAP

    assert SEPARATOR_GAP == 3600.0


@pytest.mark.parametrize(
    ("prev", "at", "expected"),
    [
        (None, _local(2026, 10, 31, 10, 0), True),
        (_local(2026, 10, 31, 10, 0), _local(2026, 10, 31, 10, 59), False),  # 59 phút
        (_local(2026, 10, 31, 10, 0), _local(2026, 10, 31, 11, 0), True),  # đúng 60 phút
        (_local(2026, 10, 31, 10, 0), _local(2026, 10, 31, 11, 1), True),  # 61 phút
        (_local(2026, 10, 31, 23, 50), _local(2026, 11, 1, 0, 5), True),  # qua ngày, 15 phút
        (_local(2026, 10, 31, 0, 0), _local(2026, 10, 31, 0, 0), False),  # cùng lúc
    ],
)
def test_b1_needs_separator(prev, at, expected):
    from teleport.ui.chat_bubbles import needs_separator

    assert needs_separator(prev, at) is expected


@pytest.mark.parametrize(
    ("at", "expected"),
    [
        (_local(2026, 10, 31, 10, 40), "Hôm nay 10:40"),
        (_local(2026, 10, 31, 0, 5), "Hôm nay 00:05"),
        (_local(2026, 10, 30, 21, 3), "Hôm qua 21:03"),
        (_local(2026, 10, 28, 21, 3), "28/10 21:03"),
        (_local(2025, 10, 28, 21, 3), "28/10/2025 21:03"),
        (_local(2026, 11, 2, 8, 0), "02/11 08:00"),  # ngày sau hôm nay → dạng ngày
        (_local(2027, 1, 2, 8, 0), "02/01/2027 08:00"),
    ],
)
def test_b1_separator_text(at, expected):
    from teleport.ui.chat_bubbles import separator_text

    now = _local(2026, 10, 31, 10, 45)
    assert separator_text(at, now) == expected


@pytest.mark.parametrize("bad", [1e20, -1e20, float("nan")])
def test_b1_separator_text_bad_time_is_empty(bad):
    from teleport.ui.chat_bubbles import separator_text

    assert separator_text(bad, NOW) == ""
    assert separator_text(NOW, bad) == ""


# =================================================================================================
# Dựng bong bóng: chiều, tên thuộc tính, nút
# =================================================================================================


def test_send_bubble_is_out_receive_bubble_is_in(view):
    from teleport.ui.chat_bubbles import TransferBubble
    from teleport.ui.widgets import Direction as Side

    s, r = key("send"), key("receive", "d" * 32)
    view.handle(status_changed(s, "transferring"))
    view.handle(status_changed(r, "transferring"))
    assert isinstance(view.row(s), TransferBubble) and isinstance(view.row(r), TransferBubble)
    assert view.row(s).direction is Side.OUT
    assert view.row(r).direction is Side.IN


def test_bubble_has_spec_attributes_and_cancel_but_no_pause(view):
    from PySide6.QtWidgets import QAbstractButton, QVBoxLayout

    from teleport.ui.widgets import IconButton

    k = key("send")
    view.handle(status_changed(k, "transferring"))
    b = view.row(k)
    assert b.key == k and b.finished is False
    for name in ("icon_label", "title_label", "size_label", "status_label", "detail_label"):
        assert isinstance(getattr(b, name), QLabel), name
    assert isinstance(b.cancel_button, IconButton) and b.cancel_button.icon_name == "dismiss"
    assert plain(b.cancel_button.label) == CANCEL
    assert shown(b.cancel_button, view)
    assert isinstance(b.extension_slot, QVBoxLayout) and b.extension_slot.count() == 0
    visible = [
        plain(x.text() or x.accessibleName()) for x in b.findChildren(QAbstractButton) if shown(x, view)
    ]
    assert all("dừng" not in t.lower() and "⏸" not in t for t in visible), visible  # 8.7, 9b.23
    b.cancel_button.click()
    assert view.cancels == [k]


def test_title_has_no_peer_suffix_and_full_name_in_accessible_name(view):
    """9.8 (i): tiêu đề bỏ “· tới X / · từ X”; tên đầy đủ ở accessibleName của tiêu đề."""
    from teleport.ui.texts import file_label

    name = "bao-cao-" * 20 + ".docx"
    s, r = key("send"), key("receive", "d" * 32)
    view.handle(status_changed(s, "transferring", files=((name, 10),)))
    view.handle(status_changed(r, "transferring", files=((name, 10),)))
    for k in (s, r):
        b = view.row(k)
        assert b.title_label.accessibleName() == file_label(name)
        assert f"tới {PEER}" not in b.title_label.text() and f"từ {PEER}" not in b.title_label.text()
        assert b.title_label.textFormat() == Qt.TextFormat.PlainText


def test_title_many_files_is_count(view):
    files = (("a.bin", 10), ("b.bin", 10), ("c.bin", 10))
    k = key("send")
    view.handle(status_changed(k, "transferring", files=files))
    assert view.row(k).title_label.accessibleName() == "3 file"


def test_transferring_status_and_detail_keep_existing_text(view):
    """Dòng 3 giữ chữ hiện có: “Đang gửi” + “42,0% · 85,2 MB/s · còn 1 phút”."""
    from teleport.core.transfer import Direction, TransferStatus
    from teleport.ui.transfers_view import short_status

    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 420 * MiB))
    b = view.row(k)
    assert b.status_label.text() == short_status(Direction.SEND, TransferStatus.TRANSFERRING)
    assert b.detail_label.text().startswith("42,0% · 85,2 MB/s · còn "), b.detail_label.text()


def test_queued_send_shows_waiting(view):
    k = key("send")
    view.handle(status_changed(k, "queued"))
    assert "Đang chờ" in bubble_text(view.row(k))


def test_offer_waiting_for_answer_shows_waiting_for_you(view):
    """Mục 4: lời mời chưa trả lời → bong bóng IN “Đang chờ bạn trả lời”, không có nút Nhận/Từ chối."""
    from PySide6.QtWidgets import QAbstractButton

    from teleport.app.transfers import OfferReceived
    from teleport.ui.widgets import Direction as Side

    k = key("receive")
    files = (entry(0, "video.mp4", 1000),)
    view.handle(OfferReceived(k, PEER, files, ("video.mp4",), 1000, False))
    b = view.row(k)
    assert b.direction is Side.IN
    assert "Đang chờ bạn trả lời" in bubble_text(b)
    texts = [plain(x.text()) for x in b.findChildren(QAbstractButton) if shown(x, view)]
    assert "Nhận" not in texts and "Từ chối" not in texts
    assert b.extension_slot.count() == 0


# =================================================================================================
# B2 tiến độ không lùi, chặn 99,9%, thanh ẩn khi kết thúc
# =================================================================================================


def test_b2_progress_never_goes_back(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 500 * MiB))
    b = view.row(k)
    assert b.progress_bar.value() == 500
    view.handle(progress(k, 300 * MiB))
    assert b.progress_bar.value() == 500, "thanh lùi khi progress mới nhỏ hơn"
    view.handle(status_changed(k, "reconnecting", done=0))
    assert b.progress_bar.value() == 500, "thanh lùi khi sang RECONNECTING"
    view.handle(status_changed(k, "verifying", done=100 * MiB))
    assert b.progress_bar.value() == 500, "thanh lùi khi sang VERIFYING"


def test_b2_progress_capped_at_99_9_before_done(view):
    k = key("send")
    view.handle(status_changed(k, "transferring", total=1_000_000))
    view.handle(progress(k, 1_000_000, total=1_000_000))
    b = view.row(k)
    assert b.detail_label.text().startswith("99,9%"), b.detail_label.text()
    assert "100" not in re.findall(r"\d+", b.detail_label.text().split("%")[0])


def test_b2_bar_scale_is_bar_max_and_bubble_bar(view):
    from PySide6.QtWidgets import QProgressBar

    from teleport.ui.chat_bubbles import BubbleBar
    from teleport.ui.transfers_view import BAR_MAX

    k = key("send")
    view.handle(status_changed(k, "transferring"))
    settle()
    bar = view.row(k).progress_bar
    assert isinstance(bar, BubbleBar) and isinstance(bar, QProgressBar)
    assert (bar.minimum(), bar.maximum()) == (0, BAR_MAX)
    assert bar.height() == 6, bar.height()  # mục 4: cao 6 px


@pytest.mark.parametrize("result", ["done", "disk_failed", "cancelled_user"])
def test_b2_bar_and_cancel_hidden_when_finished(view, result):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    b = view.row(k)
    assert shown(b.progress_bar, view)
    view.handle(finished(k, result, status="verifying"))
    assert b.finished is True
    assert not shown(b.progress_bar, view), "dòng 2 chỉ khi chưa kết thúc"
    assert not shown(b.cancel_button, view), "nút ✕ chỉ khi chưa xong"


def test_b2_finished_bubble_ignores_late_events(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "expired", status="reconnecting"))
    b = view.row(k)
    before = (b.status_label.text(), b.detail_label.text())
    view.handle(progress(k, 900 * MiB))
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "done"))
    assert view.row(k) is b
    assert (b.status_label.text(), b.detail_label.text()) == before


def test_b2_suspended_keeps_bubble(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    b = view.row(k)
    before = (b.status_label.text(), b.detail_label.text())
    view.handle(finished(k, "suspended"))
    assert view.row(k) is b and b.finished is False
    assert (b.status_label.text(), b.detail_label.text()) == before


# =================================================================================================
# B3 DONE nhận / gửi
# =================================================================================================


def test_b3_done_receive_says_saved_and_opens_parent_folder(view, monkeypatch, tmp_path):
    from PySide6.QtCore import QUrl

    from teleport.ui import chat
    from teleport.ui.transfers_view import done_text

    opened: list = []
    monkeypatch.setattr(chat, "open_url", lambda url: opened.append(QUrl(url)) or True)
    folder = tmp_path / "nhan"
    files = (("a.bin", 5), ("b.bin", 5))
    k = key("receive")
    view.handle(status_changed(k, "transferring", files=files))
    b = view.row(k)
    assert not shown(b.open_button, view)
    view.handle(file_done(k, tmp_path / "cu" / "a.bin", 0, "a.bin"))
    view.handle(file_done(k, folder / "b.bin", 1, "b.bin"))
    view.handle(finished(k, "done", status="verifying", files=files))
    assert b.status_label.text() == SAVED
    assert done_text() in b.detail_label.text()
    assert shown(b.open_button, view) and plain(b.open_button.text()) == OPEN_FOLDER
    b.open_button.click()
    assert len(opened) == 1 and opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == folder


def test_b3_done_receive_renamed_keeps_saved_as_sentence(view, tmp_path):
    from teleport.ui.transfers_view import saved_as_text

    k = key("receive")
    files = (("video.mp4", 5),)
    view.handle(status_changed(k, "transferring", files=files))
    view.handle(file_done(k, tmp_path / "video (1).mp4", 0, "video.mp4"))
    view.handle(finished(k, "done", status="verifying", files=files))
    b = view.row(k)
    assert b.status_label.text() == SAVED
    assert saved_as_text(["video (1).mp4"]) in bubble_text(b)


def test_b3_done_send_says_sent_without_open_folder(view):
    from teleport.ui.transfers_view import done_text

    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "done", status="verifying"))
    b = view.row(k)
    assert b.status_label.text() == SENT
    assert done_text() in b.detail_label.text()
    assert not shown(b.open_button, view)


def test_b3_done_has_no_danger_border(view):
    from teleport.ui.widgets import BubbleEmphasis

    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "done", status="verifying"))
    assert view.row(k).emphasis is BubbleEmphasis.NONE


# =================================================================================================
# B4 ERROR / CANCELLED
# =================================================================================================


@pytest.mark.parametrize(
    ("direction", "result", "by_peer"),
    [
        ("send", "source_changed", False),
        ("send", "expired", False),
        ("receive", "disk_failed", False),
        ("receive", "corrupt", False),
        ("send", "peer_error", True),
    ],
)
def test_b4_error_has_danger_border_and_full_section_8_sentence(view, direction, result, by_peer):
    from teleport.app.transfers import TransferResult
    from teleport.ui.texts import peer_label
    from teleport.ui.transfers_view import Kind, result_kind, result_message
    from teleport.ui.widgets import BubbleEmphasis

    assert result_kind(TransferResult(result)) is Kind.ERROR  # ca kiểm đúng loại ERROR
    k = key(direction)
    view.handle(status_changed(k, "transferring"))
    fin = finished(k, result, by_peer=by_peer)
    view.handle(fin)
    b = view.row(k)
    assert b.emphasis is BubbleEmphasis.DANGER
    sentence = result_message(fin, peer_label(PEER, PEER_ID), None)
    assert sentence and sentence in bubble_text(b), bubble_text(b)


@pytest.mark.parametrize(
    ("direction", "result", "by_peer", "status"),
    [
        ("send", "cancelled_user", False, "transferring"),
        ("send", "cancelled_user", True, "transferring"),
        ("receive", "cancelled_user", True, "transferring"),
        ("send", "rejected_user", True, "waiting"),
        ("receive", "rejected_user", False, "waiting"),
    ],
)
def test_b4_cancelled_or_rejected_has_no_emphasis(view, direction, result, by_peer, status):
    from teleport.app.transfers import TransferResult
    from teleport.ui.transfers_view import Kind, result_kind
    from teleport.ui.widgets import BubbleEmphasis

    assert result_kind(TransferResult(result)) is Kind.CANCELLED
    k = key(direction)
    view.handle(status_changed(k, status))
    view.handle(finished(k, result, by_peer=by_peer, status=status))
    b = view.row(k)
    assert b.emphasis is BubbleEmphasis.NONE, "viền DANGER chỉ cho Kind.ERROR (8.11)"
    assert b.kind is Kind.CANCELLED


# =================================================================================================
# B5 “Gửi lại”: đủ 4 điều kiện, mọi thứ tự
# =================================================================================================

RESEND_CASES = [
    # (chiều, kết quả, set_resendable(True)?, nút phải hiện?)
    ("send", "cancelled_user", True, True),
    ("send", "rejected_user", True, True),
    ("send", "expired", True, True),
    ("send", "source_changed", True, True),
    ("send", "rejected_not_receiving", True, True),
    ("send", "done", True, False),
    ("send", "unpaired", True, False),
    ("send", "expired", False, False),
    ("receive", "expired", True, False),
    ("receive", "cancelled_user", True, False),
]


@pytest.mark.parametrize(("direction", "result", "resendable", "expected"), RESEND_CASES)
@pytest.mark.parametrize("order", ["resendable_first", "finished_first"])
def test_b5_resend_button_only_when_all_four_conditions(view, direction, result, resendable, expected, order):
    k = key(direction)
    view.handle(status_changed(k, "transferring"))
    b = view.row(k)
    if order == "resendable_first" and resendable:
        view.set_resendable(k, True)
        assert not shown(b.resend_button, view), "chưa kết thúc: không có “Gửi lại”"
    view.handle(finished(k, result, by_peer=result.startswith("rejected_")))
    if order == "finished_first" and resendable:
        view.set_resendable(k, True)
    assert shown(b.resend_button, view) is expected
    if expected:
        assert plain(b.resend_button.text()) == RESEND


def test_b5_resend_not_shown_while_running_even_if_resendable(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.set_resendable(k, True)
    assert not shown(view.row(k).resend_button, view)


def test_b5_resend_click_emits_once_then_hidden_when_turned_off(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "expired", status="reconnecting"))
    view.set_resendable(k, True)
    b = view.row(k)
    b.resend_button.click()
    assert view.resends == [k]
    view.set_resendable(k, False)
    assert not shown(b.resend_button, view)
    assert view.resends == [k]


def test_b5_set_resendable_for_unknown_key_is_harmless(view):
    view.set_resendable(key("send", "9" * 32), True)
    assert view.rows() == []


# =================================================================================================
# B6 tên độc
# =================================================================================================

HOSTILE_DEVICE = "<b>x</b>‮\x1b[31m\n" + "M" * 40
HOSTILE_FILES = [
    "<b>x</b>.txt",
    "a\x07b\x1b[2J.txt",
    "‮gnp.exe",
    "x" * 251 + ".bin",  # 255 ký tự
]


@pytest.mark.parametrize("name", HOSTILE_FILES)
@pytest.mark.parametrize("direction", ["send", "receive"])
def test_b6_hostile_names_are_plain_text_and_grab_works(qtbot, view, name, direction):
    from teleport.ui.texts import file_label, peer_label

    view.set_device_names({PEER_ID: HOSTILE_DEVICE})
    k = key(direction)
    view.handle(status_changed(k, "transferring", files=((name, 10),)))
    view.handle(progress(k, 3, total=10, files=((name, 10),)))
    d = key(direction, "d" * 32)
    view.handle(status_changed(d, "transferring", files=((name, 10),)))
    view.handle(finished(d, "cancelled_user", by_peer=True, files=((name, 10),)))
    settle()
    for b in (view.row(k), view.row(d)):
        assert b.title_label.accessibleName() == file_label(name)
        for lb in b.findChildren(QLabel):
            if lb.text():  # nhãn chỉ có pixmap (icon) không mang chữ
                assert lb.textFormat() == Qt.TextFormat.PlainText, lb.text()
            assert not any(ord(c) < 0x20 for c in lb.text()), repr(lb.text())
            assert "‮" not in lb.text()
        assert "‮" not in b.accessibleName()
        assert peer_label(HOSTILE_DEVICE, PEER_ID) in b.accessibleName(), b.accessibleName()
        for w in [b, *b.findChildren(QWidget)]:
            assert "<b>" not in w.toolTip(), w.toolTip()
        image = b.grab()
        assert not image.isNull()
    assert not view.grab().isNull()


# =================================================================================================
# B7 accessibleName
# =================================================================================================


@pytest.mark.parametrize(("direction", "phrase"), [("send", "Gửi tới"), ("receive", "Nhận từ")])
def test_b7_accessible_name_has_direction_peer_status_percent_and_time(view, direction, phrase):
    from teleport.core.transfer import Direction, TransferStatus
    from teleport.ui.transfers_view import short_status

    k = key(direction)
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 420 * MiB))
    name = view.row(k).accessibleName()
    assert f"{phrase} {PEER}" in name, name
    assert short_status(Direction(direction), TransferStatus.TRANSFERRING) in name, name
    assert "42%" in name, name
    assert "10:40" in name, name  # giờ của bong bóng (`_wall_now` lúc thấy lần đầu)


def test_b7_accessible_name_not_updated_on_speed_ticks(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 420 * MiB, bps=10 * MiB, eta=100.0))
    b = view.row(k)
    first = b.accessibleName()
    view.handle(progress(k, 420 * MiB, bps=90 * MiB, eta=10.0))
    view.handle(progress(k, 425 * MiB, bps=50 * MiB, eta=30.0))  # 42,5% → vẫn 42% nguyên
    assert b.accessibleName() == first, "tốc độ / ETA đổi: không cập nhật tên trợ năng"
    view.handle(progress(k, 431 * MiB, bps=50 * MiB, eta=30.0))
    assert b.accessibleName() != first and "43%" in b.accessibleName()


def test_b7_accessible_name_updates_on_status_kind_change(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    before = view.row(k).accessibleName()
    view.handle(finished(k, "done", status="verifying"))
    after = view.row(k).accessibleName()
    assert after != before and SENT in after, after


def test_b7_accessible_name_has_long_status_not_description(view):
    """9.6: trạng thái dài vào accessibleName (qua `set_summary`), không vào accessibleDescription."""
    from teleport.ui.texts import peer_label
    from teleport.ui.transfers_view import result_message

    k = key("send")
    view.handle(status_changed(k, "transferring"))
    fin = finished(k, "source_changed")
    view.handle(fin)
    b = view.row(k)
    sentence = result_message(fin, peer_label(PEER, PEER_ID), None)
    assert sentence not in b.accessibleDescription()


# =================================================================================================
# Trợ năng của bong bóng (mục 7, 9.5, 9.10)
# =================================================================================================


def test_bubbles_and_their_buttons_are_not_tab_stops(view):
    from PySide6.QtWidgets import QAbstractButton

    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    b = view.row(k)
    assert not (b.focusPolicy() & Qt.FocusPolicy.TabFocus)
    for btn in b.findChildren(QAbstractButton):
        assert not (btn.focusPolicy() & Qt.FocusPolicy.TabFocus), btn
    assert b.cancel_button.accessibleName()


def test_time_separator_is_caption_muted_no_focus(view):
    from teleport.ui import theme
    from teleport.ui.chat_bubbles import TimeSeparator

    view.handle(status_changed(key("send"), "transferring"))
    seps = view.thread_for(PEER_ID).findChildren(TimeSeparator)
    assert seps, "bong bóng đầu tiên của luồng có dòng mốc (prev None)"
    for s in seps:
        assert s.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert s.property(theme.TONE_PROPERTY) == "muted"
        assert s.alignment() & Qt.AlignmentFlag.AlignHCenter
        assert s.textFormat() == Qt.TextFormat.PlainText


@pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
def test_bubble_bar_paints_track_and_accent_strong(qtbot, ui_theme, dark):
    """9.3: rãnh token `track`, phần đã chạy `accent_strong`."""
    from teleport.ui.chat_bubbles import BubbleBar
    from teleport.ui.transfers_view import BAR_MAX

    tok = ui_theme(dark)
    bar = BubbleBar()
    qtbot.addWidget(bar)
    bar.setRange(0, BAR_MAX)
    bar.setValue(BAR_MAX // 2)
    bar.resize(200, 6)
    bar.show()
    qtbot.waitExposed(bar)
    image = bar.grab().toImage()
    y = image.height() // 2

    def close(a, b) -> bool:
        return (
            abs(a.red() - b.red()) <= 12
            and abs(a.green() - b.green()) <= 12
            and abs(a.blue() - b.blue()) <= 12
        )

    left = image.pixelColor(image.width() // 4, y)
    right = image.pixelColor(image.width() * 3 // 4, y)
    assert close(left, tok.accent_strong), left.name()
    assert close(right, tok.track), right.name()
