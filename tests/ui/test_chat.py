"""Khung chat cột phải `teleport.ui.chat.ChatView` (spec B3 mục 5–7, mục 9 và 9b thắng): T-V, T-S, T-D, T-F.

Viết từ spec, không từ code.

- T-V (V1–V7): định tuyến theo máy, đổi máy, `rows()` cũ trước, thông báo (`info_bar`), header, luồng
  rỗng (`EmptyState`, 9b.21) và thả lên nó.
- T-S (S1–S4): cuộn ghim cuối, nút “↓ Mới” của `ChatView` (9.10), 1000 nhịp tiến độ, dòng mốc.
- T-D (D1–D4): thả file, gợi ý khi chưa chọn máy, lớp phủ khi kéo, không `stat`.
- T-F (F1–F5): Ctrl+O, Tab / roving trong luồng, máy ngoại tuyến, Enter / bấm đúp ở cột trái mở cuộc
  trò chuyện, tự chọn hàng (mục 6).

`ChatView` đứng riêng dựng với `DeviceListModel` thật. Các ca cần cả cửa sổ (F1 trang DISCOVER, F4) dựng
`MainWindow` + `TransfersController` với `NodeHost` giả (không socket), như `test_transfers_controller.py`.

Seam: `teleport.ui.chat._wall_now` (9.13), `teleport.ui.transfers.file_dialog_factory` (không mở hộp thật).
"""

from __future__ import annotations

import datetime
import os
import pathlib
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QLabel,
    QPushButton,
    QScrollBar,
    QVBoxLayout,
    QWidget,
)

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"
MiB = 2**20

# ---- Chữ của spec B3 ----------------------------------------------------------------------------
PLACEHOLDER = "Chọn một máy ở cột trái để xem file đã gửi và nhận."
SEND_FILE = "Gửi file"
DROP_TO = "Thả để gửi {n} file tới {name}"
ONLINE_HEADER = "Trực tuyến · Windows · {address}"
OFFLINE_HEADER = "Ngoại tuyến · Windows"
OFFLINE_HINT = (
    "{name} đang ngoại tuyến. File gửi lúc này sẽ chờ và tự gửi khi máy đó mở Teleport trong cùng mạng, "
    "nếu Teleport trên máy này vẫn chạy (kể cả khi chỉ còn ở khay)."
)  # 9.9 (thắng câu ở mục 5)
DRAG_HINT = "kéo file vào đây"  # “hoặc kéo file vào đây” (mục 5, 8.1)
EMPTY_TITLE = "Kéo file vào đây để gửi cho {name}"  # 9b.21
# Spec “phím tắt và dán file” mục 4 (S15): {key} là NativeText của phím Paste đầu (macOS: ⌘V).
EMPTY_TEXT = "Hoặc bấm Gửi file ở dưới, hay nhấn {key} để dán file đã chép.".format(
    key="⌘V" if sys.platform == "darwin" else "Ctrl+V"
)
NEW_NAME = "Có {n} lượt mới. Bấm để cuộn xuống cuối"
LIST_DESCRIPTION = (
    "Mũi tên để chọn máy, Tab để đi qua từng máy, Enter để mở cuộc trò chuyện, phím Menu để mở thao tác."
)
SCROLL_NAME = "Các lượt gửi nhận với {name}"

NOW = datetime.datetime(2026, 10, 31, 10, 40).timestamp()


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def key(direction: str = "send", transfer_id: str = "c" * 32, device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), transfer_id)


def tid(i: int) -> str:
    return f"{i:032x}"


def info(k, status="transferring", files=(("video.mp4", 1000 * MiB),), done=0, total=None):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    entries = tuple(FileEntry(n, s, 1_700_000_000_000) for n, s in files)
    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=entries,
        names=tuple(n for n, _ in files),
        file_index=0,
        done_bytes=done,
        total_bytes=sum(s for _, s in files) if total is None else total,
    )


def status_changed(k, status: str = "transferring", **kw):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(info(k, status, **kw))


def progress(k, shown: int, total: int = 1000 * MiB, bps: float = 50 * MiB, eta=10.0):
    from teleport.app.transfers import TransferProgress

    return TransferProgress(info(k, total=total), bps, eta, shown_bytes=shown, idle_seconds=0.0)


def finished(k, result: str = "done", status: str = "verifying"):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info(k, status),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=0,
        reject=None,
    )


def dview(
    device_id: str = PEER_ID,
    name: str = PEER,
    *,
    online: bool = True,
    connected: bool = True,
    os_name: str | None = "windows",
    addresses: tuple[str, ...] = ("192.168.1.20",),
    paired: bool = True,
):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os=os_name,
        paired=paired,
        online=online,
        connected=connected and paired,
        addresses=addresses if online else (),
        port=47474 if online else None,
    )


def peer(name: str | None, device_id: str = PEER_ID) -> str:
    from teleport.ui.texts import peer_label

    return peer_label(name, device_id)


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
    if qtbot is not None and ms:
        qtbot.wait(ms)


def visible_texts(root) -> list[str]:
    out = [lb.text() for lb in root.findChildren(QLabel) if lb.isVisibleTo(root) and lb.text()]
    out += [plain(b.text()) for b in root.findChildren(QAbstractButton) if b.isVisibleTo(root) and b.text()]
    return out


def session_bubbles(view, device_id: str = PEER_ID) -> list:
    from teleport.ui.chat_bubbles import TransferBubble

    thread = view.thread_for(device_id)
    return [] if thread is None else [b for b in thread.bubbles() if isinstance(b, TransferBubble)]


def separators(thread) -> list:
    from teleport.ui.chat_bubbles import TimeSeparator

    return [s for s in thread.findChildren(TimeSeparator) if s.isVisibleTo(thread)]


def urls(*paths: Path) -> list[QUrl]:
    return [QUrl.fromLocalFile(str(p)) for p in paths]


def mime(*qurls) -> QMimeData:
    m = QMimeData()
    m.setUrls(list(qurls))
    return m


_COPY = Qt.DropAction.CopyAction
_LEFT = Qt.MouseButton.LeftButton
_NOMOD = Qt.KeyboardModifier.NoModifier


def drag_enter(target, data, pos: QPoint | None = None) -> bool:
    pos = pos or target.rect().center()
    ev = QDragEnterEvent(pos, _COPY, data, _LEFT, _NOMOD)
    ev.setAccepted(False)
    QApplication.sendEvent(target, ev)
    return ev.isAccepted()


def drag_move(target, data, pos: QPoint | None = None) -> bool:
    pos = pos or target.rect().center()
    ev = QDragMoveEvent(pos, _COPY, data, _LEFT, _NOMOD)
    ev.setAccepted(False)
    QApplication.sendEvent(target, ev)
    return ev.isAccepted()


def drop(target, data, pos: QPoint | None = None) -> None:
    pos = pos or target.rect().center()
    drag_enter(target, data, pos)
    drag_move(target, data, pos)
    QApplication.sendEvent(target, QDropEvent(QPointF(pos), _COPY, data, _LEFT, _NOMOD))


def drag_leave(target) -> None:
    QApplication.sendEvent(target, QDragLeaveEvent())


def empty_state_of(view):
    """`EmptyState` duy nhất của `ChatView` (9b.21: một cái, dựng trong `__init__`)."""
    from teleport.ui.widgets import EmptyState

    found = view.findChildren(EmptyState)
    assert len(found) == 1, f"ChatView cần đúng một EmptyState, thấy {len(found)}"
    return found[0]


def open_and_load(view, qtbot, device_id: str, entries=()) -> None:
    """Mở luồng, chờ `history_needed` (LOADING) rồi nạp `entries`."""
    with qtbot.waitSignal(view.history_needed, timeout=2000) as blocker:
        view.set_device(device_id)
    assert blocker.args == [device_id]
    view.load_history(device_id, list(entries))


@pytest.fixture
def clock(monkeypatch):
    from teleport.ui import chat

    c = Clock(NOW)
    monkeypatch.setattr(chat, "_wall_now", c)
    return c


class Harness:
    """`ChatView` đứng riêng giữa một nút “Trước” (để Tab vào/ra), ghi lại mọi signal."""

    def __init__(self, qtbot, devices_list=None) -> None:
        from teleport.ui.chat import ChatView
        from teleport.ui.radar import DeviceListModel

        self.host = QWidget()
        qtbot.addWidget(self.host)
        self.devices = DeviceListModel(self.host)
        self.devices.reset(devices_list if devices_list is not None else [dview(), dview(OTHER_ID, OTHER)])
        self.before = QPushButton("Trước", self.host)
        self.view = ChatView(self.devices, self.host)
        lay = QVBoxLayout(self.host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.before)
        lay.addWidget(self.view, 1)
        self.host.resize(720, 460)
        v = self.view
        v.set_device_names({PEER_ID: PEER, OTHER_ID: OTHER})
        v.set_connected(PEER_ID, True)
        v.set_connected(OTHER_ID, True)
        self.picks: list[str] = []
        self.sends: list[tuple[str, list[Path]]] = []
        self.hints: list[str] = []
        self.history: list[str] = []
        self.changes: list[int] = []
        v.pick_files_requested.connect(self.picks.append)
        v.send_files_requested.connect(lambda i, p: self.sends.append((i, [Path(x) for x in p])))
        v.drop_hint_requested.connect(self.hints.append)
        v.history_needed.connect(self.history.append)
        v.content_changed.connect(lambda: self.changes.append(1))

    def show(self, qtbot, *, active: bool = False) -> None:
        self.host.show()
        qtbot.waitExposed(self.host)
        if active:
            self.host.activateWindow()
            self.host.raise_()
            qtbot.waitUntil(self.host.isActiveWindow, timeout=3000)
        settle()


@pytest.fixture
def h(qtbot, clock):
    harness = Harness(qtbot)
    harness.show(qtbot)
    return harness


# =================================================================================================
# Dựng
# =================================================================================================


def test_chat_view_parts_and_object_names(h):
    from PySide6.QtWidgets import QStackedWidget

    from teleport.ui.chat import HISTORY_DEBOUNCE_MS, MAX_THREAD_BUBBLES, PIN_SLACK, ChatComposer, ChatHeader
    from teleport.ui.widgets import IconButton, InfoBar

    v = h.view
    assert v.objectName() == "chatView"
    assert isinstance(v.header, ChatHeader)
    assert isinstance(v.info_bar, InfoBar)
    assert isinstance(v.threads, QStackedWidget)
    assert isinstance(v.placeholder, QLabel)
    assert isinstance(v.composer, ChatComposer)
    assert isinstance(v.new_button, IconButton), "9.10: new_button thuộc ChatView"
    assert v.new_button.icon_name == "arrow_down"
    assert (HISTORY_DEBOUNCE_MS, MAX_THREAD_BUBBLES, PIN_SLACK) == (120, 200, 24)
    assert v.header.action_row.count() == 0, "B3 không có nút 📂 / ⋯ ở header"


def test_send_button_is_attach_icon_button_with_shortcut_in_tooltip_only(h):
    from teleport.ui.widgets import IconButton

    b = h.view.composer.send_button
    assert isinstance(b, IconButton) and b.icon_name == "attach"
    assert b.label == SEND_FILE and plain(b.text()) == SEND_FILE
    assert "Ctrl+O" not in b.label and "(Ctrl" not in b.text()
    tip = re.sub(r"<[^>]+>", "", b.toolTip())  # safe_tooltip bọc <qt>…</qt>
    assert tip.startswith(SEND_FILE) and "O" in tip.removeprefix(SEND_FILE), tip


def test_ctrl_o_registered_once(h):
    """9.2: Ctrl+O chỉ một QAction WindowShortcut (không đăng ký hai lần)."""
    from PySide6.QtGui import QAction, QKeySequence

    ctrl_o = QKeySequence("Ctrl+O")
    actions = [
        a
        for w in [h.view, *h.view.findChildren(QWidget)]
        for a in w.actions()
        if isinstance(a, QAction) and any(s == ctrl_o for s in a.shortcuts())
    ]
    assert len(actions) == 1, actions
    assert actions[0].shortcutContext() == Qt.ShortcutContext.WindowShortcut


# =================================================================================================
# V1 định tuyến
# =================================================================================================


def test_v1_handle_routes_to_device_thread_and_hidden_thread_still_updates(h):
    v = h.view
    v.set_device(PEER_ID)
    a, b = key("send", tid(1)), key("receive", tid(2), OTHER_ID)
    v.handle(status_changed(a))
    v.handle(status_changed(b))
    assert [x.key for x in session_bubbles(v, PEER_ID)] == [a]
    assert [x.key for x in session_bubbles(v, OTHER_ID)] == [b]
    assert v.threads.currentWidget() is v.thread_for(PEER_ID)
    other = v.row(b)
    v.handle(progress(b, 600 * MiB))
    assert other.progress_bar.value() == 600, "luồng không được chọn vẫn cập nhật widget"
    assert v.thread_for(OTHER_ID).isAncestorOf(other)


def test_v1_thread_is_built_lazily(h):
    v = h.view
    assert v.thread_for(OTHER_ID) is None
    v.handle(status_changed(key("send", tid(1), OTHER_ID)))
    assert v.thread_for(OTHER_ID) is not None
    assert v.thread_for(OTHER_ID).device_id == OTHER_ID
    assert v.thread_for(OTHER_ID).objectName() == "chatThread"


def test_v1_data_unreachable_only_marks_that_device_thread(h):
    from teleport.app.transfers import DataUnreachable

    v = h.view
    a, b = key("send", tid(1)), key("send", tid(2), OTHER_ID)
    v.handle(status_changed(a, "reconnecting"))
    v.handle(status_changed(b, "reconnecting"))
    v.handle(DataUnreachable(PEER_ID))
    assert "tường lửa" in v.row(a).detail_label.text()
    assert "tường lửa" not in v.row(b).detail_label.text()


# =================================================================================================
# V2 set_device
# =================================================================================================


def test_v2_set_device_switches_header_and_thread_none_shows_placeholder(h):
    v = h.view
    assert v.device_id() is None
    assert v.placeholder.isVisibleTo(v) and v.placeholder.text() == PLACEHOLDER
    v.set_device(PEER_ID)
    assert v.device_id() == PEER_ID
    assert v.header.name_label.text() == peer(PEER)
    assert v.threads.currentWidget() is v.thread_for(PEER_ID)
    assert not v.placeholder.isVisibleTo(v)
    v.set_device(OTHER_ID)
    assert v.header.name_label.text() == peer(OTHER, OTHER_ID)
    assert v.threads.currentWidget() is v.thread_for(OTHER_ID)
    v.set_device(None)
    assert v.device_id() is None
    assert v.placeholder.isVisibleTo(v) and v.placeholder.text() == PLACEHOLDER


def test_v2_scroll_accessible_name_names_device(h):
    v = h.view
    v.set_device(PEER_ID)
    assert v.thread_for(PEER_ID).scroll_area.accessibleName() == SCROLL_NAME.format(name=peer(PEER))


def test_v2_header_name_label_is_plain_text_with_hostile_name(qtbot, clock):
    hostile = "<b>X</b>‮\x1b[31m"
    harness = Harness(qtbot, [dview(name=hostile)])
    harness.show(qtbot)
    v = harness.view
    v.set_device_names({PEER_ID: hostile})
    v.set_device(PEER_ID)
    assert v.header.name_label.textFormat() == Qt.TextFormat.PlainText
    assert v.header.name_label.text() == peer(hostile)
    assert "<b>" not in v.header.toolTip()


# =================================================================================================
# V3 rows() cũ trước
# =================================================================================================


def test_v3_rows_old_first_across_devices(h, clock):
    v = h.view
    ks = [
        key("send", tid(1), OTHER_ID),
        key("receive", tid(2)),
        key("send", tid(3), OTHER_ID),
        key("send", tid(4)),
    ]
    for k in ks:
        v.handle(status_changed(k))
        clock.advance(5)
    assert [r.key for r in v.rows()] == ks


def test_v3_rows_same_time_keeps_creation_order(h):
    v = h.view
    ks = [key("send", tid(i)) for i in range(4)]
    for k in ks:
        v.handle(status_changed(k))
    assert [r.key for r in v.rows()] == ks


def test_v3_clock_going_back_still_appends_at_end(h, clock):
    """9.13: `at` = max(_wall_now(), at của bong bóng phiên cuối) → đồng hồ lùi không chèn vào giữa."""
    v = h.view
    v.set_device(PEER_ID)
    a, b = key("send", tid(1)), key("send", tid(2))
    v.handle(status_changed(a))
    clock.advance(-7200)
    v.handle(status_changed(b))
    assert [x.key for x in session_bubbles(v)] == [a, b]
    assert v.row(b).at >= v.row(a).at


def test_v3_row_returns_session_bubble_and_clear_empties(h):
    v = h.view
    a = key("send", tid(1))
    v.handle(status_changed(a))
    assert v.row(a) is not None and v.row(a).key == a
    v.clear()
    assert v.rows() == [] and v.row(a) is None


def test_v3_remove_takes_bubble_out(h):
    v = h.view
    a, b = key("send", tid(1)), key("send", tid(2))
    v.handle(status_changed(a))
    v.handle(status_changed(b))
    v.remove(a)
    assert v.row(a) is None and [r.key for r in v.rows()] == [b]


def test_v3_active_count_counts_every_thread(h):
    v = h.view
    v.set_device(PEER_ID)
    v.handle(status_changed(key("send", tid(1))))
    v.handle(status_changed(key("send", tid(2), OTHER_ID)))
    v.handle(finished(key("receive", tid(3), OTHER_ID)))
    assert v.active_count() == 2


# =================================================================================================
# V4 thông báo
# =================================================================================================


def test_v4_show_notice_with_action_calls_callback_then_hides(h):
    from teleport.ui.widgets import InfoLevel

    v = h.view
    calls: list[int] = []
    v.show_notice("Câu có nút.", "Làm gì đó", lambda: calls.append(1))
    assert v.info_bar.isVisibleTo(v)
    assert v.notice_text() == "Câu có nút."
    assert v.notice_action_text() == "Làm gì đó"
    assert v.info_bar.level is InfoLevel.INFO
    assert v.notice_action is v.info_bar.action_button
    assert v.notice_label is v.info_bar.title_label
    v.info_bar.action_button.click()
    assert calls == [1]
    assert not v.info_bar.isVisibleTo(v)
    assert v.notice_text() == ""


def test_v4_hide_runs_before_callback(h):
    """9.7: `action_triggered` → `hide_notice()` trước rồi gọi callback (callback hiện thông báo mới được)."""
    v = h.view
    v.show_notice("Một.", "Nút", lambda: v.show_notice("Hai."))
    v.info_bar.action_button.click()
    assert v.notice_text() == "Hai."


@pytest.mark.parametrize("level", ["info", "warning", "error", "success"])
def test_v4_show_notice_level_is_keyword(h, level):
    from teleport.ui.widgets import InfoLevel

    h.view.show_notice("Câu.", level=InfoLevel(level))
    assert h.view.info_bar.level is InfoLevel(level)


def test_v4_action_without_callback_has_no_button(h):
    v = h.view
    v.show_notice("Câu thiếu hàm.", "Nút", None)
    assert not v.info_bar.action_button.isVisibleTo(v)
    v.show_notice("Câu không nút.")
    assert not v.info_bar.action_button.isVisibleTo(v)
    assert v.notice_text() == "Câu không nút."


def test_v4_has_content_is_notice_or_selected_device(h):
    """9.15: has_content = info_bar hiện hoặc đang chọn máy."""
    v = h.view
    v.handle(status_changed(key("send", tid(1))))
    assert v.has_content() is False, "còn bong bóng phiên nhưng không chọn máy"
    v.show_notice("Câu.")
    assert v.has_content() is True
    v.hide_notice()
    assert v.has_content() is False
    v.set_device(PEER_ID)
    assert v.has_content() is True


def test_v4_content_changed_on_structure_changes(h):
    v = h.view
    h.changes.clear()
    v.handle(status_changed(key("send", tid(1))))
    assert h.changes, "thêm bong bóng phát content_changed"
    h.changes.clear()
    v.show_notice("Câu.")
    assert h.changes
    h.changes.clear()
    v.hide_notice()
    assert h.changes


# =================================================================================================
# V5 header
# =================================================================================================


def test_v5_header_online_offline_and_updates_with_model(h):
    v = h.view
    v.set_device(PEER_ID)
    assert v.header.status_label.text() == ONLINE_HEADER.format(address="192.168.1.20")
    h.devices.reset([dview(online=False, connected=False), dview(OTHER_ID, OTHER)])
    settle()
    assert v.header.status_label.text() == OFFLINE_HEADER
    h.devices.reset([dview(addresses=("10.0.0.9", "10.0.0.10")), dview(OTHER_ID, OTHER)])
    settle()
    assert v.header.status_label.text() == ONLINE_HEADER.format(address="10.0.0.9")


def test_v5_header_connect_failure_uses_b2_short_label(h):
    from teleport.app.node import ConnectFailed
    from teleport.core.links import ConnectResult

    v = h.view
    off = dview(online=False, connected=False)
    h.devices.reset([off, dview(OTHER_ID, OTHER)])
    v.set_device(PEER_ID)
    h.devices.apply(ConnectFailed(off, ConnectResult.REJECTED))
    settle()
    assert v.header.status_label.text().startswith("Bị từ chối kết nối"), v.header.status_label.text()


def test_v5_header_os_from_mdns_is_never_printed_raw(qtbot, clock):
    harness = Harness(qtbot, [dview(os_name="<b>evil</b>\x1b")])
    harness.show(qtbot)
    v = harness.view
    v.set_device(PEER_ID)
    text = v.header.status_label.text()
    assert "evil" not in text and "<b>" not in text, text
    assert text.startswith("Trực tuyến")


# =================================================================================================
# V6 / V7 luồng rỗng (9b.21)
# =================================================================================================


def test_v6_empty_thread_shows_empty_state_not_while_loading_hidden_with_bubble(h, qtbot):
    v = h.view
    es = empty_state_of(v)
    with qtbot.waitSignal(v.history_needed, timeout=2000):
        v.set_device(PEER_ID)
    from teleport.ui.chat import HistoryState

    assert v.thread_for(PEER_ID).history_state is HistoryState.LOADING
    assert not es.isVisibleTo(v), "LOADING: không hiện EmptyState (tránh chớp)"
    v.load_history(PEER_ID, [])
    assert es.isVisibleTo(v)
    assert es.title_label.text() == EMPTY_TITLE.format(name=peer(PEER))
    assert es.text_label.text() == EMPTY_TEXT
    assert not es.action_button.isVisibleTo(v), "không nút hành động (thanh dưới đã có)"
    assert EMPTY_TITLE.format(name=peer(PEER)) in es.accessibleName()
    v.handle(status_changed(key("send", tid(1))))
    assert not es.isVisibleTo(v), "có bong bóng đầu tiên → thay ngay bằng luồng"


def test_v6_empty_state_follows_selected_device_name(h, qtbot):
    v = h.view
    open_and_load(v, qtbot, OTHER_ID)
    es = empty_state_of(v)
    assert es.isVisibleTo(v)
    assert es.title_label.text() == EMPTY_TITLE.format(name=peer(OTHER, OTHER_ID))


def test_v6_empty_state_hidden_without_selected_device(h):
    v = h.view
    v.set_device(None)
    assert not empty_state_of(v).isVisibleTo(v)


def test_v6_empty_state_is_built_once(h, qtbot):
    v = h.view
    es = empty_state_of(v)
    open_and_load(v, qtbot, PEER_ID)
    open_and_load(v, qtbot, OTHER_ID)
    assert empty_state_of(v) is es


def test_v6_empty_state_shows_no_transfers_illustration(h, qtbot):
    """Spec G6 tiêu chí 8 (mục 7): luồng rỗng (`chatEmpty`) có minh họa NO_TRANSFERS thay vòng icon."""
    from teleport.ui.illustrations import Scene

    v = h.view
    open_and_load(v, qtbot, PEER_ID)
    es = empty_state_of(v)
    assert es.objectName() == "chatEmpty"
    assert es.illustration.isVisibleTo(v)
    assert es.illustration.scene is Scene.NO_TRANSFERS
    assert not es.icon_badge.isVisibleTo(v)


def test_v6_empty_illustration_does_not_replay_when_switching_device(h, qtbot, real_motion, monkeypatch):
    """Spec G6 mục 7: đổi máy (cùng cảnh NO_TRANSFERS) không chạy lại minh họa."""
    from teleport.ui import illustrations

    monkeypatch.setattr(illustrations, "PLAY_MS", 1500)
    v = h.view
    ill = empty_state_of(v).illustration
    open_and_load(v, qtbot, PEER_ID)
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)  # đối chứng: lần hiện đầu có chạy
    qtbot.waitUntil(lambda: not ill.playing, timeout=5000)
    assert ill.progress == 1.0
    open_and_load(v, qtbot, OTHER_ID)
    assert empty_state_of(v).illustration is ill
    assert ill.isVisibleTo(v)
    QApplication.processEvents()
    qtbot.wait(50)
    assert not ill.playing
    assert ill.progress == 1.0


def test_v7_drop_on_empty_state_sends_files(h, qtbot, tmp_path):
    v = h.view
    open_and_load(v, qtbot, PEER_ID)
    es = empty_state_of(v)
    assert es.isVisibleTo(v)
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    drop(es.title_label, mime(*urls(*files)))
    assert h.sends == [(PEER_ID, files)]


# =================================================================================================
# T-S cuộn
# =================================================================================================


def _fill_thread(view, clock, n: int = 14, device_id: str = PEER_ID) -> None:
    for i in range(n):
        view.handle(finished(key("send", tid(1000 + i), device_id)))
        clock.advance(30)


def _bar(view, device_id: str = PEER_ID):
    return view.thread_for(device_id).scroll_area.verticalScrollBar()


@pytest.fixture
def scrolled(h, qtbot, clock):
    """Luồng PC-Nha có đủ bong bóng để cuộn, đang ghim cuối."""
    v = h.view
    v.set_device(PEER_ID)
    _fill_thread(v, clock)
    settle(qtbot, 50)
    bar = _bar(v)
    assert bar.maximum() > 0, "cần đủ bong bóng để có thanh cuộn"
    qtbot.waitUntil(lambda: bar.value() == bar.maximum(), timeout=2000)
    return h


def test_s1_pinned_new_bubble_keeps_bottom(scrolled, qtbot):
    v = scrolled.view
    thread = v.thread_for(PEER_ID)
    assert thread.is_pinned()
    v.handle(status_changed(key("send", tid(1))))
    bar = _bar(v)
    qtbot.waitUntil(lambda: bar.value() == bar.maximum(), timeout=2000)
    assert not v.new_button.isVisibleTo(v)


def test_s1_opening_thread_pins_it(scrolled, qtbot):
    v = scrolled.view
    _bar(v).setValue(0)
    settle()
    v.set_device(OTHER_ID)
    v.set_device(PEER_ID)
    settle(qtbot, 30)
    assert v.thread_for(PEER_ID).is_pinned()


def test_s2_scrolled_up_new_bubble_shows_new_button_click_scrolls_down(scrolled, qtbot):
    v = scrolled.view
    bar = _bar(v)
    bar.setValue(0)
    settle()
    assert not v.thread_for(PEER_ID).is_pinned()
    v.handle(status_changed(key("send", tid(1))))
    settle(qtbot, 30)
    assert bar.value() == 0, "không tự cuộn khi đang cuộn lên"
    assert v.new_button.isVisibleTo(v)
    assert v.new_button.accessibleName().startswith(NEW_NAME.format(n=1))
    v.handle(status_changed(key("send", tid(2))))
    settle()
    assert v.new_button.accessibleName().startswith(NEW_NAME.format(n=2))
    v.new_button.click()
    qtbot.waitUntil(lambda: bar.value() == bar.maximum(), timeout=2000)
    assert not v.new_button.isVisibleTo(v)


def test_s2_scrolling_to_bottom_by_hand_hides_new_button(scrolled, qtbot):
    v = scrolled.view
    bar = _bar(v)
    bar.setValue(0)
    settle()
    v.handle(status_changed(key("send", tid(1))))
    settle(qtbot, 30)
    assert v.new_button.isVisibleTo(v)
    bar.setValue(bar.maximum())
    settle()
    assert not v.new_button.isVisibleTo(v)


def test_s2_new_bubble_in_hidden_thread_does_not_show_new_button(scrolled, qtbot):
    v = scrolled.view
    _bar(v).setValue(0)
    settle()
    v.handle(status_changed(key("send", tid(1), OTHER_ID)))
    settle(qtbot, 30)
    assert not v.new_button.isVisibleTo(v)


@pytest.mark.parametrize("target", ["scrollbar", "blank"])
def test_s2_mouse_press_in_thread_does_not_jump_to_newest(scrolled, qtbot, target):
    """Bấm thanh cuộn hay chỗ trống trong luồng không kéo tiêu điểm về `threads` (TabFocus), nên khung
    cuộn không nhảy tới bong bóng mới nhất khi người dùng đang đọc lượt cũ."""
    v = scrolled.view
    thread = v.thread_for(PEER_ID)
    bar = _bar(v)
    bar.setValue(0)
    settle()
    assert bar.value() == 0
    if target == "scrollbar":
        widget, pos = bar, QPoint(bar.width() // 2, 4)  # trên tay nắm khi đang ở đầu
    else:
        widget, pos = thread.scroll_area.viewport(), QPoint(2, 2)  # lề trái trên của nội dung
    QTest.mousePress(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    settle(qtbot, 30)
    assert bar.value() == 0
    QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    settle(qtbot, 30)
    assert bar.value() == 0
    assert QApplication.focusWidget() is not v.threads
    assert not v.threads.focusPolicy() & Qt.FocusPolicy.ClickFocus


@pytest.mark.parametrize("how", ["event", "window"])
def test_s2_reactivating_window_does_not_scroll_to_focused_bubble(scrolled, qtbot, how):
    """Tiêu điểm trở lại bong bóng vì cửa sổ được kích hoạt lại hay hộp thoại đóng
    (ActiveWindow/Popup) không được giật khung cuộn về bong bóng đó khi người dùng đang đọc chỗ khác."""
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent

    v = scrolled.view
    thread = v.thread_for(PEER_ID)
    bar = _bar(v)
    last = thread.bubbles()[-1]
    QTest.mouseClick(last, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(10, 10))
    settle(qtbot, 30)
    assert QApplication.focusWidget() is last
    bar.setValue(0)
    settle()
    assert bar.value() == 0
    if how == "event":
        for reason in (Qt.FocusReason.ActiveWindowFocusReason, Qt.FocusReason.PopupFocusReason):
            QApplication.sendEvent(last, QFocusEvent(QEvent.Type.FocusIn, reason))
            settle()
            assert bar.value() == 0, reason
    else:
        other = QWidget()
        qtbot.addWidget(other)
        other.show()
        other.activateWindow()
        settle(qtbot, 30)
        v.window().activateWindow()
        settle(qtbot, 30)
        assert bar.value() == 0
    assert thread.current_bubble() is last


def test_s2_pending_then_real_bubble_counts_one_new(scrolled, qtbot, tmp_path):
    """Bong bóng tạm rồi bong bóng thật của cùng một lần gửi chỉ là một “lượt mới”."""
    v = scrolled.view
    thread = v.thread_for(PEER_ID)
    _bar(v).setValue(0)
    settle()
    token = v.add_pending(PEER_ID, [tmp_path / "a.bin"])
    settle()
    assert thread.unseen() == 1
    v.handle(status_changed(key("send", tid(1))))
    settle()
    v.remove_pending(token)
    settle()
    assert thread.unseen() == 1
    assert v.new_button.accessibleName().startswith(NEW_NAME.format(n=1))
    # Thứ tự ngược: `send` trả về trước sự kiện đầu tiên.
    token = v.add_pending(PEER_ID, [tmp_path / "b.bin"])
    v.remove_pending(token)
    v.handle(status_changed(key("send", tid(2))))
    settle()
    assert thread.unseen() == 2


def test_s3_thousand_progress_ticks_change_nothing_structural(scrolled, qtbot):
    v = scrolled.view
    k = key("send", tid(1))
    v.handle(status_changed(k))  # đang ghim: không bật “↓ Mới”
    settle(qtbot, 30)
    _bar(v).setValue(0)
    settle()
    assert not v.new_button.isVisibleTo(v)
    b = v.row(k)
    widgets_before = len(v.findChildren(QWidget))
    scrolled.changes.clear()
    total = 1000 * MiB
    for i in range(1, 1001):
        v.handle(progress(k, total * i // 1001, total, eta=float(1001 - i)))
    settle()
    assert scrolled.changes == [], "nhịp tiến độ không phát content_changed"
    assert len(v.findChildren(QWidget)) == widgets_before, "nhịp tiến độ không dựng widget mới"
    assert v.row(k) is b
    assert not v.new_button.isVisibleTo(v), "nhịp tiến độ không bật “↓ Mới”"


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((2026, 10, 31, 9, 0), (2026, 10, 31, 9, 59), 1),
        ((2026, 10, 31, 9, 0), (2026, 10, 31, 10, 1), 2),
        ((2026, 10, 31, 23, 50), (2026, 11, 1, 0, 10), 2),
    ],
    ids=["59-phut", "61-phut", "qua-ngay"],
)
def test_s4_separators_by_gap_and_day(h, clock, first, second, expected):
    v = h.view
    v.set_device(PEER_ID)
    clock.now = datetime.datetime(*first).timestamp()
    v.handle(status_changed(key("send", tid(1))))
    clock.now = datetime.datetime(*second).timestamp()
    v.handle(status_changed(key("send", tid(2))))
    settle()
    assert len(separators(v.thread_for(PEER_ID))) == expected


def test_s4_separator_text_matches_bubble_time(h, clock):
    from teleport.ui.chat_bubbles import separator_text

    v = h.view
    v.set_device(PEER_ID)
    v.handle(status_changed(key("send", tid(1))))
    settle()
    [sep] = separators(v.thread_for(PEER_ID))
    assert sep.text() == separator_text(NOW, NOW) == "Hôm nay 10:40"


# =================================================================================================
# T-D thả
# =================================================================================================


def test_d1_drop_local_urls_sends_and_skips_remote(h, tmp_path):
    v = h.view
    v.set_device(PEER_ID)
    files = [tmp_path / "a.txt", tmp_path / "b c.txt"]
    data = mime(*urls(files[0]), QUrl("https://example.com/x.zip"), *urls(files[1]))
    for target in (v.thread_for(PEER_ID).scroll_area.viewport(), v.composer):
        h.sends.clear()
        drop(target, data)
        assert h.sends == [(PEER_ID, files)], target


def test_d1_only_remote_urls_are_refused(h):
    v = h.view
    v.set_device(PEER_ID)
    data = mime(QUrl("https://example.com/x.zip"))
    assert not drag_enter(v, data)
    QApplication.sendEvent(v, QDropEvent(QPointF(v.rect().center()), _COPY, data, _LEFT, _NOMOD))
    assert h.sends == [] and h.hints == []


def test_d2_drop_without_selected_device_asks_for_hint(h, tmp_path):
    from teleport.ui.radar import drop_hint_text

    v = h.view
    v.set_device(None)
    drop(v, mime(*urls(tmp_path / "a.txt")))
    assert h.sends == []
    assert h.hints == [drop_hint_text()]


def test_d3_preview_drop_shows_overlay_sentence(h):
    v = h.view
    v.set_device(PEER_ID)
    v.preview_drop(3)
    settle()
    assert DROP_TO.format(n=3, name=peer(PEER)) in visible_texts(v)
    v.preview_drop(None)
    settle()
    assert not any(t.startswith("Thả để gửi") for t in visible_texts(v))


def test_d3_drag_enter_shows_overlay_and_leave_hides_it(h, tmp_path):
    v = h.view
    v.set_device(PEER_ID)
    data = mime(*urls(tmp_path / "a.txt", tmp_path / "b.txt"))
    assert drag_enter(v, data)
    drag_move(v, data)
    settle()
    assert DROP_TO.format(n=2, name=peer(PEER)) in visible_texts(v)
    drag_leave(v)
    settle()
    assert not any(t.startswith("Thả để gửi") for t in visible_texts(v))


def test_d4_dragging_and_dropping_does_not_stat(h, tmp_path, monkeypatch):
    v = h.view
    v.set_device(PEER_ID)
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for f in files:
        f.write_bytes(b"x")
    watched = {os.path.normcase(str(f)) for f in files}
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

    monkeypatch.setattr(os, "stat", os_stat)
    monkeypatch.setattr(pathlib.Path, "stat", path_stat)
    data = mime(*urls(*files))
    target = v.thread_for(PEER_ID).scroll_area.viewport()
    drag_enter(target, data)
    for _ in range(3):
        drag_move(target, data)
    v.repaint()
    drag_leave(target)
    drop(target, data)
    settle()
    assert calls == []
    assert h.sends == [(PEER_ID, files)]


# =================================================================================================
# T-F bàn phím
# =================================================================================================


def test_f1_ctrl_o_requests_pick_only_with_selected_device(qtbot, clock):
    harness = Harness(qtbot)
    harness.show(qtbot, active=True)
    v = harness.view
    QTest.keyClick(harness.before, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert harness.picks == [], "chưa chọn máy: Ctrl+O không chạy"
    v.set_device(PEER_ID)
    QTest.keyClick(harness.before, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert harness.picks == [PEER_ID]


def test_f1_send_button_requests_pick(h):
    v = h.view
    v.set_device(PEER_ID)
    v.composer.send_button.click()
    assert h.picks == [PEER_ID]


def test_f1_ctrl_o_does_nothing_when_view_hidden(qtbot, clock):
    harness = Harness(qtbot)
    harness.show(qtbot, active=True)
    harness.view.set_device(PEER_ID)
    harness.view.hide()
    QTest.keyClick(harness.before, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert harness.picks == []


def _tab(backward: bool = False) -> None:
    w = QApplication.focusWidget()
    assert w is not None
    if backward:
        QTest.keyClick(w, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
    else:
        QTest.keyClick(w, Qt.Key.Key_Tab)
    settle()


def _key(k) -> None:
    QTest.keyClick(QApplication.focusWidget(), k)
    settle()


@pytest.fixture
def tabbed(qtbot, clock):
    """Ba bong bóng đang chạy ở luồng PC-Nha, cửa sổ đang active, tiêu điểm ở nút “Trước”."""
    harness = Harness(qtbot)
    harness.show(qtbot, active=True)
    v = harness.view
    v.set_device(PEER_ID)
    ks = [key("send", tid(i)) for i in range(3)]
    for k in ks:
        v.handle(status_changed(k))
        clock.advance(10)
    settle(qtbot, 30)
    harness.keys = ks  # type: ignore[attr-defined]
    harness.before.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    return harness


def test_f2_tab_enters_thread_on_newest_bubble_and_arrows_move(tabbed):
    from teleport.ui.widgets import ChatBubble

    v, ks = tabbed.view, tabbed.keys
    _tab()
    focus = QApplication.focusWidget()
    assert isinstance(focus, ChatBubble), focus
    assert focus is v.row(ks[-1]), "mặc định bong bóng mới nhất"
    _key(Qt.Key.Key_Up)
    assert QApplication.focusWidget() is v.row(ks[1])
    _key(Qt.Key.Key_Home)
    assert QApplication.focusWidget() is v.row(ks[0])
    _key(Qt.Key.Key_Down)
    assert QApplication.focusWidget() is v.row(ks[1])
    _key(Qt.Key.Key_End)
    assert QApplication.focusWidget() is v.row(ks[2])


def test_f2_tab_from_bubble_goes_through_its_buttons_then_send_button(tabbed):
    v, ks = tabbed.view, tabbed.keys
    _tab()
    _key(Qt.Key.Key_Up)
    current = v.row(ks[1])
    assert QApplication.focusWidget() is current
    _tab()
    assert QApplication.focusWidget() is current.cancel_button, "Tab đi qua nút của bong bóng hiện hành"
    _tab()
    assert QApplication.focusWidget() is v.composer.send_button, "new_button ẩn → thẳng tới send_button"


def test_f2_thread_is_a_single_tab_stop(tabbed):
    v = tabbed.view
    _tab()
    assert v.threads.isAncestorOf(QApplication.focusWidget())
    _tab()  # nút ✕ của bong bóng hiện hành
    _tab()
    assert QApplication.focusWidget() is v.composer.send_button


def test_f2_shift_tab_from_bubble_leaves_thread_backwards(tabbed):
    _tab()
    _tab(backward=True)
    assert QApplication.focusWidget() is tabbed.before


def test_f2_lazy_widgets_are_click_or_no_focus_threads_tab_only(tabbed):
    """9.10 + 9b.25: `threads` là điểm dừng Tab duy nhất của luồng, chỉ `TabFocus` (bấm chuột không kéo
    tiêu điểm về đó, xem `test_s2_mouse_press_in_thread_does_not_jump_to_newest`)."""
    from teleport.ui.chat_bubbles import TimeSeparator

    v = tabbed.view
    assert v.threads.focusPolicy() == Qt.FocusPolicy.TabFocus
    thread = v.thread_for(PEER_ID)
    lazy = [thread, *thread.findChildren(QWidget)]
    tab_stops = [
        w for w in lazy if w.focusPolicy() & Qt.FocusPolicy.TabFocus and not isinstance(w, QScrollBar)
    ]
    assert tab_stops == [], tab_stops
    for s in thread.findChildren(TimeSeparator):
        assert s.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_f3_offline_device_send_button_enabled_and_hint(qtbot, clock):
    harness = Harness(qtbot, [dview(online=False, connected=False), dview(OTHER_ID, OTHER)])
    harness.show(qtbot)
    v = harness.view
    v.set_connected(PEER_ID, False)
    v.set_device(PEER_ID)
    assert v.composer.send_button.isEnabled()
    assert v.composer.hint_label.text() == OFFLINE_HINT.format(name=peer(PEER))
    assert v.composer.hint_label.textFormat() == Qt.TextFormat.PlainText
    v.composer.send_button.click()
    assert harness.picks == [PEER_ID], "máy ngoại tuyến vẫn gửi được (mvp mục 8)"
    v.set_device(OTHER_ID)
    assert DRAG_HINT in v.composer.hint_label.text()
    assert "ngoại tuyến" not in v.composer.hint_label.text()


def test_f3_offline_hint_follows_model(qtbot, clock):
    harness = Harness(qtbot)
    harness.show(qtbot)
    v = harness.view
    v.set_device(PEER_ID)
    assert DRAG_HINT in v.composer.hint_label.text()
    harness.devices.reset([dview(online=False, connected=False), dview(OTHER_ID, OTHER)])
    settle()
    assert v.composer.hint_label.text() == OFFLINE_HINT.format(name=peer(PEER))


def test_f3_offline_hint_in_mvp_doc():
    """9.9: câu thanh dưới ghi vào mvp mục 8 dòng “đã ghép đôi nhưng chưa kết nối”."""
    doc = (Path(__file__).resolve().parents[2] / "docs" / "mvp.md").read_text(encoding="utf-8")
    sample = OFFLINE_HINT.format(name="*PC-Nha*")
    assert sample in doc or OFFLINE_HINT.format(name="PC-Nha") in doc, "câu ngoại tuyến chưa có trong mvp.md"


# ---- F4 / F5: cột trái (mục 6) -----------------------------------------------------------------


class FakeHost:
    def __init__(self, receive_dir: Path) -> None:
        from teleport.ui.bridge import NodeOptions

        self.options = NodeOptions(config_dir=receive_dir.parent / "cfg", receive_dir=receive_dir, mdns=None)
        self.calls: list = []
        self.submits: list = []
        self.running = True
        self.is_stopped = False
        self.node_name = "May-A"

    def call(self, fn, on_done=None) -> None:
        self.calls.append((fn, on_done))

    def submit(self, fn, on_done=None) -> None:
        self.submits.append((fn, on_done))


@pytest.fixture
def win(qtbot, monkeypatch, tmp_path, clock):
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: None)
    dialogs: list = []

    from PySide6.QtWidgets import QFileDialog

    class FakeDialog(QFileDialog):
        """Hộp chọn file không mở thật (seam `file_dialog_factory`)."""

        def __init__(self, *a, **k) -> None:
            super().__init__()
            dialogs.append(self)

        def open(self, *a, **k) -> None:
            pass

        def exec(self, *a, **k) -> int:
            return 0

    monkeypatch.setattr(mod, "file_dialog_factory", lambda *a, **k: FakeDialog())
    window = MainWindow()
    qtbot.addWidget(window)
    tray = Tray()
    ctl = mod.TransfersController(window, tray, parent=None)
    host = FakeHost(tmp_path / "nhan")
    ctl.attach(host)
    picks: list[str] = []
    ctl.view.pick_files_requested.connect(picks.append)
    ns = SimpleNamespace(window=window, ctl=ctl, host=host, dialogs=dialogs, picks=picks, tmp=tmp_path)
    yield ns
    ctl.close_all()
    tray.dispose()


def _show_active(window, qtbot) -> None:
    window.resize(980, 660)
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    settle()


def test_f1_ctrl_o_does_nothing_on_discover_page(win, qtbot):
    from teleport.ui.main_window import Page

    w = win.window
    w.show_running("May-A", win.tmp / "nhan")
    w.devices.reset([dview()])
    _show_active(w, qtbot)
    assert win.ctl.view.device_id() == PEER_ID, "tự chọn hàng 0 (mục 6) → luồng mở"
    QTest.keyClick(w, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert win.picks == [PEER_ID]
    assert w.open_page(Page.DISCOVER)
    settle()
    QTest.keyClick(QApplication.focusWidget() or w, Qt.Key.Key_O, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert win.picks == [PEER_ID], "trang DISCOVER: Ctrl+O không chạy"


@pytest.mark.parametrize("enter_key", [Qt.Key.Key_Return, Qt.Key.Key_Enter])
def test_f4_enter_in_list_opens_conversation_and_focuses_send_button(win, qtbot, enter_key):
    w = win.window
    w.show_running("May-A", win.tmp / "nhan")
    w.devices.reset([dview(), dview(OTHER_ID, OTHER)])
    _show_active(w, qtbot)
    conv = w.conversations
    opened: list[str] = []
    picked: list[str] = []
    conv.open_requested.connect(opened.append)
    conv.pick_files_requested.connect(picked.append)
    conv.select_device(OTHER_ID)
    conv.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    QTest.keyClick(conv.list_view, enter_key)
    settle(qtbot, 30)
    assert opened == [OTHER_ID]
    assert picked == [] and win.picks == [] and win.dialogs == [], "Enter không còn mở hộp chọn file"
    assert win.ctl.view.device_id() == OTHER_ID
    assert QApplication.focusWidget() is win.ctl.view.composer.send_button


def test_f4_double_click_opens_conversation(win, qtbot):
    w = win.window
    w.show_running("May-A", win.tmp / "nhan")
    w.devices.reset([dview(), dview(OTHER_ID, OTHER)])
    _show_active(w, qtbot)
    conv = w.conversations
    opened: list[str] = []
    picked: list[str] = []
    conv.open_requested.connect(opened.append)
    conv.pick_files_requested.connect(picked.append)
    lst = conv.list_view
    pos = lst.visualRect(conv.model.index(conv.model.row_of(OTHER_ID), 0)).center()
    QTest.mouseClick(lst.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.mouseDClick(lst.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    settle(qtbot, 40)
    assert opened == [OTHER_ID]
    assert picked == [] and win.dialogs == []
    assert QApplication.focusWidget() is win.ctl.view.composer.send_button


def test_f4_menu_send_files_still_requests_pick(win, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMenu

    monkeypatch.setattr(QMenu, "popup", lambda self, *a, **k: None)
    monkeypatch.setattr(QMenu, "exec", lambda self, *a, **k: None)
    w = win.window
    w.devices.reset([dview()])
    conv = w.conversations
    picked: list[str] = []
    opened: list[str] = []
    conv.pick_files_requested.connect(picked.append)
    conv.open_requested.connect(opened.append)
    menu = conv.context_menu_for(PEER_ID)
    [action] = [a for a in menu.actions() if plain(a.text()) == "Gửi file…"]
    action.trigger()
    assert picked == [PEER_ID] and opened == []
    menu.deleteLater()


def test_f4_list_accessible_description(win):
    assert win.window.conversations.list_view.accessibleDescription() == LIST_DESCRIPTION


def test_f4_controller_sets_view_device_from_conversations(win):
    """9.17 + mục 5: `current_changed` → `view.set_device`."""
    w = win.window
    w.devices.reset([dview(), dview(OTHER_ID, OTHER)])
    w.conversations.select_device(OTHER_ID)
    settle()
    assert win.ctl.view.device_id() == OTHER_ID
    w.conversations.select_device(PEER_ID)
    settle()
    assert win.ctl.view.device_id() == PEER_ID


class Conv:
    def __init__(self, qtbot) -> None:
        from teleport.ui.conversations import ConversationList
        from teleport.ui.radar import DeviceListModel

        self.host = QWidget()
        qtbot.addWidget(self.host)
        self.devices = DeviceListModel(self.host)
        self.widget = ConversationList(self.devices, self.host)
        QVBoxLayout(self.host).addWidget(self.widget)
        self.currents: list = []
        self.widget.current_changed.connect(self.currents.append)

    def selected(self) -> str | None:
        d = self.widget.current_device()
        return None if d is None else d.device_id


def test_f5_auto_selects_row_zero_after_reset(qtbot):
    c = Conv(qtbot)
    assert c.selected() is None
    c.devices.reset([dview(), dview(OTHER_ID, OTHER)])
    settle()
    first = c.widget.model.index(0, 0)
    from teleport.ui.conversations import DEVICE_ID_ROLE

    assert c.selected() == first.data(DEVICE_ID_ROLE)
    assert c.currents and c.currents[-1] == c.selected()


def test_f5_auto_selects_after_rows_inserted(qtbot):
    from teleport.app.node import DeviceOnline

    c = Conv(qtbot)
    c.devices.apply(DeviceOnline(dview()))
    settle()
    assert c.selected() == PEER_ID


def test_f5_removing_selected_row_selects_another(qtbot):
    c = Conv(qtbot)
    c.devices.reset([dview(), dview(OTHER_ID, OTHER)])
    settle()
    c.widget.select_device(PEER_ID)
    settle()
    assert c.selected() == PEER_ID
    c.devices.reset([dview(OTHER_ID, OTHER)])
    settle()
    assert c.selected() == OTHER_ID
    assert c.currents[-1] == OTHER_ID


def test_f5_empty_list_selects_nothing(qtbot):
    c = Conv(qtbot)
    c.devices.reset([dview()])
    settle()
    c.devices.reset([])
    settle()
    assert c.selected() is None
