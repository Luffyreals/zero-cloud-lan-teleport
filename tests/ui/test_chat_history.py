"""Lịch sử trong luồng chat (spec B3 mục 5 “Lịch sử (F5)”, 9.12–9.14 thắng): T-H, H1–H8 (+ 9.14).

Viết từ spec, không từ code. Mức view: `ChatView` đứng riêng, `DeviceListModel` thật, `HistoryEntry` thật
của `teleport.core.history` (đã kiểm hợp lệ trong `__post_init__`). Luồng nạp lịch sử theo đúng vòng đời
của spec: `set_device` → (sau `HISTORY_DEBOUNCE_MS`) `history_needed` + LOADING → `load_history` → LOADED.

Seam: `teleport.ui.chat._wall_now` (9.13), `teleport.ui.chat.open_url` (mục 2).
"""

from __future__ import annotations

import datetime
import os
import pathlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
THIRD_ID = "5a5a5a5a" + "2" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"
UTC = datetime.UTC

SAVED = "Đã lưu"
SENT = "Đã gửi"
OPEN_FOLDER = "Hiện trong thư mục"  # spec-f4 mục 2.4 (trước: “Mở thư mục”)
HISTORY_FAILED = "Không đọc được lịch sử với máy này."
OPEN_FAILED = "Không mở được thư mục {path}. Thư mục có thể đã bị xóa, đổi tên hay nằm trên ổ đã rút ra."

NOW = datetime.datetime(2026, 10, 31, 10, 40).timestamp()


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def tid(i: int) -> str:
    return f"{i:032x}"


def hentry(
    i: int = 1,
    direction: str = "send",
    result: str = "done",
    *,
    names: tuple[str, ...] = ("video.mp4",),
    file_count: int | None = None,
    total: int = 3 * 2**20,
    at: datetime.datetime = datetime.datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
    saved_path: str | None = None,
    device_id: str = PEER_ID,
    device_name: str | None = PEER,
):
    from teleport.core.history import HistoryEntry

    return HistoryEntry(
        direction=direction,
        device_id=device_id,
        device_name=device_name,
        transfer_id=tid(i),
        file_count=file_count if file_count is not None else max(1, len(names)),
        total_bytes=total,
        done_bytes=total if result == "done" else 0,
        names=names,
        result=result,
        finished_at=at,
        saved_path=saved_path,
    )


def hkey(e):
    from teleport.core.transfer import TransferKey

    return TransferKey(e.device_id, e.direction, e.transfer_id)


def info(k, status="transferring"):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=(FileEntry("video.mp4", 1000, 0),),
        names=("video.mp4",),
        file_index=0,
        done_bytes=0,
        total_bytes=1000,
    )


def status_changed(k, status: str = "transferring"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(info(k, status))


def finished(k, result: str = "done"):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info(k, "verifying"),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=0,
        reject=None,
    )


def skey(direction: str, i: int, device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), tid(i))


def dview(device_id: str, name: str):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=True,
        online=True,
        connected=True,
        addresses=("192.0.2.7",),
        port=47474,
    )


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
    if qtbot is not None and ms:
        qtbot.wait(ms)


def history_bubbles(view, device_id: str = PEER_ID) -> list:
    from teleport.ui.chat_bubbles import HistoryBubble

    thread = view.thread_for(device_id)
    return [] if thread is None else [b for b in thread.bubbles() if isinstance(b, HistoryBubble)]


def bubbles_for(view, k, device_id: str = PEER_ID) -> list:
    thread = view.thread_for(device_id)
    return [] if thread is None else [b for b in thread.bubbles() if getattr(b, "key", None) == k]


def texts_of(widget) -> str:
    parts = [lb.text() for lb in widget.findChildren(QLabel) if lb.isVisibleTo(widget) and lb.text()]
    title = getattr(widget, "title_label", None)
    if title is not None and title.accessibleName():
        parts.append(title.accessibleName())
    return "\n".join(parts)


def local_hhmm(at: datetime.datetime) -> str:
    return datetime.datetime.fromtimestamp(at.timestamp()).strftime("%H:%M")


def plain(text: str) -> str:
    return text.replace("&", "")


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, s: float) -> None:
        self.now += s


@pytest.fixture
def clock(monkeypatch):
    from teleport.ui import chat

    c = Clock(NOW)
    monkeypatch.setattr(chat, "_wall_now", c)
    return c


@pytest.fixture
def view(qtbot, clock):
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    devices = DeviceListModel()
    devices.reset([dview(PEER_ID, PEER), dview(OTHER_ID, OTHER), dview(THIRD_ID, "May-Ba")])
    v = ChatView(devices)
    v._test_devices = devices  # type: ignore[attr-defined]
    qtbot.addWidget(v)
    v.set_device_names({PEER_ID: PEER, OTHER_ID: OTHER, THIRD_ID: "May-Ba"})
    v.resize(720, 560)
    v.show()
    qtbot.waitExposed(v)
    v.needed = []  # type: ignore[attr-defined]
    v.history_needed.connect(v.needed.append)
    return v


def open_thread(view, qtbot, device_id: str = PEER_ID) -> None:
    """Mở luồng và chờ `history_needed` (luồng sang LOADING)."""
    from teleport.ui.chat import HistoryState

    with qtbot.waitSignal(view.history_needed, timeout=2000) as blocker:
        view.set_device(device_id)
    assert blocker.args == [device_id]
    assert view.thread_for(device_id).history_state is HistoryState.LOADING


def open_and_load(view, qtbot, entries, device_id: str = PEER_ID) -> None:
    from teleport.ui.chat import HistoryState

    open_thread(view, qtbot, device_id)
    view.load_history(device_id, list(entries))
    assert view.thread_for(device_id).history_state is HistoryState.LOADED


# =================================================================================================
# H1 dựng theo finished_at, đúng chiều và chữ
# =================================================================================================


def test_h1_history_bubbles_sorted_by_finished_at_with_direction_and_text(view, qtbot, tmp_path):
    from teleport.app.transfers import TransferResult
    from teleport.core.display import format_size
    from teleport.ui.chat_bubbles import HistoryBubble
    from teleport.ui.texts import file_label
    from teleport.ui.transfers_view import result_status
    from teleport.ui.widgets import BubbleEmphasis
    from teleport.ui.widgets import Direction as Side

    t1 = datetime.datetime(2026, 10, 29, 8, 15, tzinfo=UTC)
    t2 = datetime.datetime(2026, 10, 30, 14, 2, tzinfo=UTC)
    t3 = datetime.datetime(2026, 10, 30, 20, 47, tzinfo=UTC)
    sent = hentry(1, "send", "done", names=("bao-cao.pdf",), at=t1)
    got = hentry(
        2, "receive", "done", names=("anh.jpg",), at=t2, saved_path=str(tmp_path / "nhan" / "anh.jpg")
    )
    cancelled = hentry(3, "send", "cancelled_user", names=("phim.mkv",), at=t3)
    # `history()` trả mới nhất trước: dựng phải theo `at`, cũ trên cùng.
    open_and_load(view, qtbot, [cancelled, got, sent])
    bubbles = history_bubbles(view)
    assert [b.entry for b in bubbles] == [sent, got, cancelled]
    for b, e in zip(bubbles, [sent, got, cancelled], strict=True):
        assert isinstance(b, HistoryBubble)
        assert b.key == hkey(e)
        assert b.at == e.finished_at.timestamp()
        text = texts_of(b)
        assert file_label(e.names[0]) in text, text
        assert format_size(e.total_bytes) in text and local_hhmm(e.finished_at) in text, text
    assert bubbles[0].direction is Side.OUT and bubbles[1].direction is Side.IN
    assert bubbles[0].status_label.text() == SENT
    assert bubbles[1].status_label.text() == SAVED
    assert bubbles[2].status_label.text() == result_status(TransferResult.CANCELLED_USER)
    assert all(b.emphasis is BubbleEmphasis.NONE for b in bubbles)


def test_h1_history_labels_are_plain_text(view, qtbot):
    open_and_load(view, qtbot, [hentry(1, names=("x.txt",))])
    [b] = history_bubbles(view)
    for lb in b.findChildren(QLabel):
        if lb.text():  # nhãn icon chỉ có pixmap
            assert lb.textFormat() == Qt.TextFormat.PlainText, lb.text()


def test_h1_history_before_session_bubbles(view, qtbot):
    k = skey("send", 50)
    view.handle(status_changed(k))
    open_and_load(view, qtbot, [hentry(1), hentry(2, at=datetime.datetime(2026, 10, 29, 1, 0, tzinfo=UTC))])
    keys = [b.key for b in view.thread_for(PEER_ID).bubbles()]
    assert keys[-1] == k
    assert keys[:2] == [skey("send", 2), skey("send", 1)]


def test_h1_history_not_in_rows_or_row(view, qtbot):
    """9.11: `rows()` / `row(key)` chỉ trả bong bóng của phiên."""
    e = hentry(1)
    open_and_load(view, qtbot, [e])
    assert view.rows() == []
    assert view.row(hkey(e)) is None
    assert view.active_count() == 0


def test_h1_history_has_no_resend(view, qtbot):
    from PySide6.QtWidgets import QAbstractButton

    open_and_load(view, qtbot, [hentry(1, "send", "expired")])
    [b] = history_bubbles(view)
    texts = [plain(x.text()) for x in b.findChildren(QAbstractButton) if x.isVisibleTo(view)]
    assert "Gửi lại" not in texts


# =================================================================================================
# H2 khóa trùng
# =================================================================================================


def test_h2_session_bubble_wins_over_history_entry_with_same_key(view, qtbot):
    from teleport.ui.chat_bubbles import TransferBubble

    e = hentry(7, "send", "done")
    k = hkey(e)
    view.handle(status_changed(k))
    view.handle(finished(k, "done"))
    open_and_load(view, qtbot, [e, hentry(8)])
    found = bubbles_for(view, k)
    assert len(found) == 1 and isinstance(found[0], TransferBubble)
    assert len(history_bubbles(view)) == 1


def test_h2_session_event_replaces_history_bubble(view, qtbot):
    from teleport.ui.chat_bubbles import TransferBubble

    e = hentry(7, "receive", "done", saved_path=None)
    k = hkey(e)
    open_and_load(view, qtbot, [e])
    assert len(bubbles_for(view, k)) == 1
    view.handle(finished(k, "done"))
    found = bubbles_for(view, k)
    assert len(found) == 1 and isinstance(found[0], TransferBubble), found
    assert view.row(k) is found[0]


def test_h2_duplicate_history_entries_give_one_bubble(view, qtbot):
    e = hentry(7)
    open_and_load(view, qtbot, [e, e])
    assert len(bubbles_for(view, hkey(e))) == 1


def test_h2_same_transfer_id_other_direction_is_a_different_key(view, qtbot):
    a, b = hentry(7, "send"), hentry(7, "receive")
    open_and_load(view, qtbot, [a, b])
    assert len(history_bubbles(view)) == 2


def test_h2_entries_of_other_device_are_ignored(view, qtbot):
    open_and_load(view, qtbot, [hentry(1), hentry(2, device_id=OTHER_ID, device_name=OTHER)])
    assert [b.key for b in history_bubbles(view)] == [skey("send", 1)]


# =================================================================================================
# H3 rời luồng gỡ lịch sử; mở lại nạp lại
# =================================================================================================


def test_h3_leaving_thread_unloads_history_keeps_session_and_reopen_asks_again(view, qtbot):
    from teleport.ui.chat import HistoryState

    k = skey("send", 50)
    view.handle(status_changed(k))
    open_and_load(view, qtbot, [hentry(1), hentry(2)])
    assert len(history_bubbles(view)) == 2
    open_thread(view, qtbot, OTHER_ID)
    thread = view.thread_for(PEER_ID)
    assert history_bubbles(view) == []
    assert thread.history_state is HistoryState.NONE
    assert [b.key for b in thread.bubbles()] == [k], "bong bóng phiên giữ"
    open_thread(view, qtbot, PEER_ID)
    assert view.needed.count(PEER_ID) == 2


def test_h3_at_most_one_thread_holds_history_widgets(view, qtbot):
    from teleport.ui.chat_bubbles import HistoryBubble

    open_and_load(view, qtbot, [hentry(1), hentry(2)])
    open_and_load(view, qtbot, [hentry(3, device_id=OTHER_ID, device_name=OTHER)], OTHER_ID)
    threads = {d: view.thread_for(d) for d in (PEER_ID, OTHER_ID, THIRD_ID)}
    holders = {
        d
        for d, t in threads.items()
        if t is not None and any(isinstance(b, HistoryBubble) for b in t.bubbles())
    }
    assert holders == {OTHER_ID}


def test_h3_unload_history_directly(view, qtbot):
    from teleport.ui.chat import HistoryState

    open_and_load(view, qtbot, [hentry(1)])
    view.thread_for(PEER_ID).unload_history()
    assert history_bubbles(view) == []
    assert view.thread_for(PEER_ID).history_state is HistoryState.NONE


# =================================================================================================
# H4 kết quả tới muộn
# =================================================================================================


def test_h4_load_history_for_thread_no_longer_open_is_dropped(view, qtbot):
    from teleport.ui.chat import HistoryState

    open_thread(view, qtbot, PEER_ID)
    view.set_device(OTHER_ID)
    view.load_history(PEER_ID, [hentry(1)])
    assert history_bubbles(view) == []
    assert view.thread_for(PEER_ID).history_state is HistoryState.NONE


def test_h4_second_load_after_loaded_is_ignored(view, qtbot):
    """9.12: chỉ áp khi LOADING; kết quả tới sau bị bỏ."""
    open_and_load(view, qtbot, [hentry(1)])
    view.load_history(PEER_ID, [hentry(2)])
    assert [b.key for b in history_bubbles(view)] == [skey("send", 1)]


def test_h4_load_before_history_needed_is_ignored(view):
    from teleport.ui.chat import HistoryState

    view.set_device(PEER_ID)
    view.load_history(PEER_ID, [hentry(1)])  # chưa LOADING (đang chờ debounce)
    assert history_bubbles(view) == []
    assert view.thread_for(PEER_ID).history_state is not HistoryState.LOADED


def test_h4_history_failed_shows_muted_line_and_failed_state(view, qtbot):
    from teleport.ui.chat import HistoryState

    open_thread(view, qtbot)
    view.history_failed(PEER_ID)
    thread = view.thread_for(PEER_ID)
    assert thread.history_state is HistoryState.FAILED
    labels = [
        lb for lb in thread.findChildren(QLabel) if lb.isVisibleTo(thread) and lb.text() == HISTORY_FAILED
    ]
    assert len(labels) == 1
    assert labels[0].focusPolicy() == Qt.FocusPolicy.NoFocus


# =================================================================================================
# H5 trần 200
# =================================================================================================


def test_h5_cap_removes_oldest_finished_never_running(view, qtbot, clock):
    from teleport.ui.chat import MAX_THREAD_BUBBLES

    view.set_device(PEER_ID)
    running = skey("send", 1)
    view.handle(status_changed(running))
    done_keys = []
    for i in range(MAX_THREAD_BUBBLES + 5):
        clock.advance(1)
        k = skey("receive", 1000 + i)
        view.handle(finished(k, "done"))
        done_keys.append(k)
    settle()
    bubbles = view.thread_for(PEER_ID).bubbles()
    assert len(bubbles) == MAX_THREAD_BUBBLES
    assert view.row(running) is not None, "không bao giờ gỡ lượt đang chạy"
    assert all(view.row(k) is None for k in done_keys[:6]), "gỡ bong bóng đã kết thúc cũ nhất"
    assert all(view.row(k) is not None for k in done_keys[6:])


def test_h5_cap_never_removes_running_even_above_limit(view, clock):
    from teleport.ui.chat import MAX_THREAD_BUBBLES

    keys = []
    for i in range(MAX_THREAD_BUBBLES + 1):
        clock.advance(1)
        k = skey("send", 2000 + i)
        view.handle(status_changed(k))
        keys.append(k)
    assert all(view.row(k) is not None for k in keys)
    assert view.active_count() == MAX_THREAD_BUBBLES + 1


def test_h5_cap_counts_history_too(view, qtbot, clock):
    from teleport.ui.chat import MAX_THREAD_BUBBLES

    entries = [
        hentry(i, at=datetime.datetime(2026, 10, 1, tzinfo=UTC) + datetime.timedelta(minutes=i))
        for i in range(1, MAX_THREAD_BUBBLES + 1)
    ]
    open_and_load(view, qtbot, entries)
    running = skey("send", 9999)
    view.handle(status_changed(running))
    bubbles = view.thread_for(PEER_ID).bubbles()
    assert len(bubbles) <= MAX_THREAD_BUBBLES
    assert view.row(running) is not None
    assert skey("send", 1) not in [b.key for b in bubbles], "mục lịch sử cũ nhất bị gỡ"


# =================================================================================================
# ChatThread.add_many: nạp lịch sử khi đang cuộn giữa chừng, khi có tiêu điểm
# =================================================================================================


def _session_thread(view, qtbot, clock, n: int = 14):
    """Luồng PC-Nha đang chờ lịch sử, có `n` bong bóng phiên (đủ để cuộn)."""
    open_thread(view, qtbot)
    for i in range(n):
        clock.advance(30)
        view.handle(finished(skey("send", 3000 + i)))
    settle(qtbot, 30)
    thread = view.thread_for(PEER_ID)
    bar = thread.scroll_area.verticalScrollBar()
    assert bar.maximum() > 0, "cần đủ bong bóng để có thanh cuộn"
    return thread, bar


def _history_entries(n: int = 10) -> list:
    return [
        hentry(i, at=datetime.datetime(2026, 10, 30, 9, 0, tzinfo=UTC) + datetime.timedelta(minutes=i))
        for i in range(1, n + 1)
    ]


def test_add_many_while_scrolled_mid_keeps_unpinned_and_no_new_button(view, qtbot, clock):
    thread, bar = _session_thread(view, qtbot, clock)
    bar.setValue(bar.maximum() // 2)
    settle()
    assert not thread.is_pinned()
    value = bar.value()
    viewport = thread.scroll_area.viewport()
    # Bong bóng phiên đang nằm trong khung nhìn: vị trí của nó trong khung là “nội dung đang xem”.
    seen = next(
        b for b in thread.bubbles() if 0 <= b.mapTo(viewport, b.rect().topLeft()).y() < viewport.height()
    )
    y_before = seen.mapTo(viewport, seen.rect().topLeft()).y()

    view.load_history(PEER_ID, _history_entries())
    settle(qtbot, 30)

    assert len(history_bubbles(view)) == 10
    assert not thread.is_pinned(), "nạp lịch sử không ghim xuống cuối"
    assert bar.value() != bar.maximum()
    assert thread.unseen() == 0, "nạp lịch sử không đếm lượt mới"
    assert not view.new_button.isVisibleTo(view), "nạp lịch sử không bật “↓ Mới”"
    # Lịch sử chèn phía trên; khung cuộn giữ đúng nội dung đang xem chứ không giữ con số `value`.
    assert bar.value() > value
    assert abs(seen.mapTo(viewport, seen.rect().topLeft()).y() - y_before) <= 1


def test_add_many_keeps_focus_on_focused_bubble(view, qtbot, clock):
    thread, _bar = _session_thread(view, qtbot, clock)
    target = thread.bubbles()[len(thread.bubbles()) // 2]
    target.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    assert QApplication.focusWidget() is target

    view.load_history(PEER_ID, _history_entries())
    settle(qtbot, 30)

    assert len(history_bubbles(view)) == 10
    assert QApplication.focusWidget() is target, "nạp lịch sử không đẩy tiêu điểm khỏi bong bóng"
    assert thread.current_bubble() is target


# =================================================================================================
# H6 kết quả lạ, names rỗng
# =================================================================================================


def test_h6_unknown_result_is_error_with_danger(view, qtbot):
    from teleport.ui.widgets import BubbleEmphasis

    open_and_load(view, qtbot, [hentry(1, "send", "some_future_result")])
    [b] = history_bubbles(view)
    assert b.status_label.text() == "Lỗi"
    assert b.emphasis is BubbleEmphasis.DANGER


@pytest.mark.parametrize(
    ("result", "danger"),
    [("disk_failed", True), ("expired", True), ("rejected_user", False), ("done", False)],
)
def test_h6_danger_only_for_error_kind(view, qtbot, result, danger):
    from teleport.ui.widgets import BubbleEmphasis

    open_and_load(view, qtbot, [hentry(1, "send", result)])
    [b] = history_bubbles(view)
    assert (b.emphasis is BubbleEmphasis.DANGER) is danger


@pytest.mark.parametrize(
    ("names", "count", "title"),
    [((), 3, "3 file"), (("a.txt", "b.txt"), 2, "2 file"), (("a.txt",), 5, "5 file"), ((), 1, "1 file")],
)
def test_h6_title_is_count_when_many_or_no_names(view, qtbot, names, count, title):
    open_and_load(view, qtbot, [hentry(1, names=names, file_count=count)])
    [b] = history_bubbles(view)
    assert title in (b.title_label.text(), b.title_label.accessibleName())


def test_h6_hostile_history_name_is_plain(view, qtbot):
    from teleport.ui.texts import file_label

    name = "<b>x</b>\u202egnp.exe"
    open_and_load(view, qtbot, [hentry(1, names=(name,))])
    [b] = history_bubbles(view)
    assert file_label(name) in (b.title_label.text(), b.title_label.accessibleName())
    assert b.title_label.textFormat() == Qt.TextFormat.PlainText
    assert not b.grab().isNull()


# =================================================================================================
# H7 “Hiện trong thư mục” của mục lịch sử (spec-f4: trước là “Mở thư mục”)
# =================================================================================================


@pytest.fixture
def opened(monkeypatch):
    from PySide6.QtCore import QUrl

    from teleport.ui import chat

    class Calls(list):
        result: dict

    calls = Calls()
    result = {"value": True}

    def fake(url):
        calls.append(QUrl(url))
        return result["value"]

    monkeypatch.setattr(chat, "open_url", fake)
    calls.result = result
    return calls


def test_h7_absolute_saved_path_opens_parent(view, qtbot, tmp_path, opened):
    saved = tmp_path / "nhan" / "anh.jpg"
    open_and_load(view, qtbot, [hentry(1, "receive", saved_path=str(saved))])
    [b] = history_bubbles(view)
    assert b.open_button.isVisibleTo(view) and plain(b.open_button.text()) == OPEN_FOLDER
    b.open_button.click()
    assert len(opened) == 1 and opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == saved.parent


def test_h7_open_failure_shows_warning_info_bar(view, qtbot, tmp_path, opened):
    from teleport.ui import send
    from teleport.ui.widgets import InfoLevel

    opened.result["value"] = False
    saved = tmp_path / "da-xoa" / "anh.jpg"
    open_and_load(view, qtbot, [hentry(1, "receive", saved_path=str(saved))])
    [b] = history_bubbles(view)
    b.open_button.click()
    assert view.info_bar.isVisibleTo(view)
    assert view.info_bar.level is InfoLevel.WARNING
    assert view.notice_text() == OPEN_FAILED.format(path=send.printable(str(saved.parent)))


@pytest.mark.parametrize("saved", ["nhan/anh.jpg", "anh.jpg", "./x/anh.jpg"])
def test_h7_relative_saved_path_has_no_button(view, qtbot, saved):
    open_and_load(view, qtbot, [hentry(1, "receive", saved_path=saved)])
    [b] = history_bubbles(view)
    assert not b.open_button.isVisibleTo(view)


def test_h7_send_and_no_saved_path_have_no_button(view, qtbot):
    open_and_load(view, qtbot, [hentry(1, "send"), hentry(2, "receive", saved_path=None)])
    for b in history_bubbles(view):
        assert not b.open_button.isVisibleTo(view)


UNC_CASES = [
    # (thư mục nhận hiện tại, saved_path, có nút?)
    (r"\\srv\share\Teleport", r"\\srv\share\Teleport\a.bin", True),
    (r"\\srv\share\Teleport", r"\\SRV\Share\khac\a.bin", True),  # normcase
    (r"\\?\UNC\srv\share\Teleport", r"\\srv\share\Teleport\a.bin", True),  # chuẩn hóa như _drive_label
    (r"\\srv\share\Teleport", r"\\other\share\a.bin", False),
    (r"\\srv\share\Teleport", r"\\srv\other\a.bin", False),
    (r"D:\Teleport", r"\\srv\share\a.bin", False),
    (None, r"\\srv\share\a.bin", False),
    (r"\\srv\share\Teleport", r"\\.\C:\x\a.bin", False),  # drive bắt đầu bằng \ (9.12)
    (r"D:\Teleport", r"\\?\unc\srv\share\a.txt", False),  # tiền tố không phân biệt hoa thường
    (r"D:\Teleport", r"\\?\GLOBALROOT\Device\Mup\srv\share\a.txt", False),  # thiết bị, không phải X:
    # \\?\ không phải ổ chữ cái, không phải UNC\ → không bao giờ trùng, kể cả thư mục nhận cùng dạng
    (r"\\?\GLOBALROOT\Device\HarddiskVolume3\T", r"\\?\GLOBALROOT\Device\Mup\srv\share\a.txt", False),
    (r"\\?\Volume{1234}\T", r"\\?\Volume{1234}\T\a.txt", False),
    (r"\\?\unc\srv\share\Teleport", r"\\SRV\share\a.bin", True),
    (r"D:\Teleport", r"\\?\D:\Teleport\a.bin", True),  # \\?\ trước ổ chữ cái: ổ thường
]


@pytest.mark.skipif(sys.platform != "win32", reason="đường dẫn UNC chỉ là tuyệt đối trên Windows")
@pytest.mark.parametrize(("receive_dir", "saved", "expected"), UNC_CASES)
def test_h7_unc_only_on_same_share_as_receive_dir(view, qtbot, receive_dir, saved, expected):
    view.set_receive_dir(None if receive_dir is None else Path(receive_dir))
    open_and_load(view, qtbot, [hentry(1, "receive", saved_path=saved)])
    [b] = history_bubbles(view)
    assert b.open_button.isVisibleTo(view) is expected


def test_h7_loading_history_does_not_touch_disk(view, qtbot, tmp_path, monkeypatch):
    saved = [tmp_path / "nhan" / f"f{i}.bin" for i in range(3)]
    watched = {os.path.normcase(str(p)) for p in saved} | {os.path.normcase(str(saved[0].parent))}
    calls: list[str] = []
    real_os_stat, real_path_stat = os.stat, pathlib.Path.stat

    def os_stat(path, *a, **k):
        if os.path.normcase(os.fspath(path)) in watched:
            calls.append(f"os.stat({path})")
        return real_os_stat(path, *a, **k)

    def path_stat(self, *a, **k):
        if os.path.normcase(str(self)) in watched:
            calls.append(f"Path.stat({self})")
        return real_path_stat(self, *a, **k)

    open_thread(view, qtbot)
    monkeypatch.setattr(os, "stat", os_stat)
    monkeypatch.setattr(pathlib.Path, "stat", path_stat)
    view.load_history(PEER_ID, [hentry(i, "receive", saved_path=str(p)) for i, p in enumerate(saved, 1)])
    view.repaint()
    assert calls == []


# =================================================================================================
# H8 debounce
# =================================================================================================


def test_h8_switching_five_times_within_100ms_asks_once(view, qtbot):
    from teleport.ui.chat import HISTORY_DEBOUNCE_MS

    for d in (PEER_ID, OTHER_ID, THIRD_ID, OTHER_ID, PEER_ID):
        view.set_device(d)
        qtbot.wait(15)
    qtbot.wait(HISTORY_DEBOUNCE_MS * 3)
    assert view.needed == [PEER_ID]


def test_h8_history_needed_waits_for_debounce(view, qtbot):
    from teleport.ui.chat import HISTORY_DEBOUNCE_MS

    view.set_device(PEER_ID)
    settle()
    assert view.needed == [], "chưa hết HISTORY_DEBOUNCE_MS"
    qtbot.waitUntil(lambda: view.needed == [PEER_ID], timeout=HISTORY_DEBOUNCE_MS * 10)


def test_h8_set_device_none_asks_nothing(view, qtbot):
    from teleport.ui.chat import HISTORY_DEBOUNCE_MS

    view.set_device(PEER_ID)
    view.set_device(None)
    qtbot.wait(HISTORY_DEBOUNCE_MS * 3)
    assert view.needed == []


# =================================================================================================
# 9.14 invalidate_history, showEvent
# =================================================================================================


def test_invalidate_history_all_reloads_open_thread(view, qtbot):
    from teleport.ui.chat import HistoryState

    open_and_load(view, qtbot, [hentry(1)])
    with qtbot.waitSignal(view.history_needed, timeout=2000) as blocker:
        view.invalidate_history(None)
        assert history_bubbles(view) == []
    assert blocker.args == [PEER_ID]
    assert view.thread_for(PEER_ID).history_state is HistoryState.LOADING


def test_invalidate_history_other_device_keeps_open_thread(view, qtbot):
    open_and_load(view, qtbot, [hentry(1)])
    view.invalidate_history(OTHER_ID)
    assert len(history_bubbles(view)) == 1


def test_show_event_reloads_open_thread_history(view, qtbot):
    open_and_load(view, qtbot, [hentry(1)])
    view.hide()
    settle()
    with qtbot.waitSignal(view.history_needed, timeout=2000) as blocker:
        view.show()
    assert blocker.args == [PEER_ID]


def test_add_many_over_cap_keeps_view_and_builds_only_newest(view, qtbot, clock):
    """Lịch sử dư so với `MAX_THREAD_BUBBLES` không được dựng rồi gỡ ở phía trên chỗ neo (luồng đang
    cuộn lên không bị kéo xuống cuối); chỉ dựng các mục mới nhất còn chỗ."""
    from teleport.ui.chat import MAX_THREAD_BUBBLES

    thread, bar = _session_thread(view, qtbot, clock, n=20)
    bar.setValue(bar.maximum() // 2)
    settle()
    entries = _history_entries(MAX_THREAD_BUBBLES + 100)

    view.load_history(PEER_ID, entries)
    settle(qtbot, 30)

    built = history_bubbles(view)
    assert len(thread.bubbles()) == MAX_THREAD_BUBBLES
    assert len(built) == MAX_THREAD_BUBBLES - 20
    newest = {skey("send", i) for i in range(len(entries) - len(built) + 1, len(entries) + 1)}
    assert {b.key for b in built} == newest, "chỉ dựng các mục lịch sử mới nhất"
    assert not thread.is_pinned(), "nạp lịch sử dư không kéo luồng xuống cuối"
