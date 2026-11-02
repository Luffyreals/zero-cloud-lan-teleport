"""Đổi ngôn ngữ trong khung chat (spec B3 mục 1: mọi chuỗi qua `tr()`, gọi lúc dùng, dựng lại khi
`LanguageChange`; mục 9.6: lớp con của `ChatBubble` dựng chữ trong `_render()` gọi từ `changeEvent`).

Viết từ spec, không từ code. Một `QTranslator` giả thêm tiền tố `[x]` vào mọi chuỗi: cài vào thì Qt gửi
`LanguageChange` tới mọi widget, chữ của bong bóng (`TransferBubble`, `HistoryBubble`, bong bóng tạm
“Đang chuẩn bị…”), dòng mốc, đầu luồng, thanh dưới, màn rỗng và nút “↓ Mới” phải mang tiền tố; gỡ ra thì
về đúng chữ cũ. Thêm một ca gửi thẳng `QEvent(LanguageChange)` (không translator) vào từng widget: dựng lại
không lỗi, chữ không đổi, `grab()` vẫn chạy.
"""

from __future__ import annotations

import datetime
from datetime import UTC
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QTranslator
from PySide6.QtWidgets import QApplication

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"
PREFIX = "[x]"
NOW = datetime.datetime(2026, 10, 31, 10, 40).timestamp()


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


# =================================================================================================
# Dữ liệu giả
# =================================================================================================


def tid(i: int) -> str:
    return f"{i:032x}"


def key(direction: str, i: int, device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), tid(i))


def info(k, status: str = "transferring", files=(("video.mp4", 1000),)):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=tuple(FileEntry(n, s, 1_700_000_000_000) for n, s in files),
        names=tuple(n for n, _ in files),
        file_index=0,
        done_bytes=0,
        total_bytes=sum(s for _, s in files),
    )


def status_changed(k, status: str = "transferring"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(info(k, status))


def finished(k, result: str):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info(k, "verifying"),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=0,
        reject=None,
    )


def file_done(k, path: Path):
    from teleport.app.transfers import FileDone

    return FileDone(key=k, file_index=0, name=path.name, path=path)


def hentry(i: int, direction: str = "send", result: str = "done"):
    from teleport.core.history import HistoryEntry

    return HistoryEntry(
        direction=direction,
        device_id=PEER_ID,
        device_name=PEER,
        transfer_id=tid(i),
        file_count=1,
        total_bytes=3000,
        done_bytes=3000 if result == "done" else 0,
        names=("bao-cao.pdf",),
        result=result,
        finished_at=datetime.datetime(2026, 10, 30, 9, 0, tzinfo=UTC),
        saved_path=None,
    )


def dview(device_id: str, name: str, *, online: bool = True):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=True,
        online=online,
        connected=online,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def settle() -> None:
    for _ in range(3):
        QApplication.processEvents()


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def clock(monkeypatch):
    from teleport.ui import chat

    monkeypatch.setattr(chat, "_wall_now", lambda: NOW)


@pytest.fixture
def translator():
    t = PrefixTranslator()
    yield t
    QCoreApplication.removeTranslator(t)


@pytest.fixture
def scene(qtbot, clock, tmp_path):
    """`ChatView` đang mở luồng của PC-Nha, có đủ loại bong bóng và dòng mốc."""
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    devices = DeviceListModel()
    devices.reset([dview(PEER_ID, PEER), dview(OTHER_ID, OTHER, online=False)])
    v = ChatView(devices)
    v._test_devices = devices  # type: ignore[attr-defined]  # giữ model sống cùng view
    qtbot.addWidget(v)
    v.set_device_names({PEER_ID: PEER, OTHER_ID: OTHER})
    v.resize(720, 560)
    v.show()
    qtbot.waitExposed(v)
    with qtbot.waitSignal(v.history_needed, timeout=2000):
        v.set_device(PEER_ID)
    v.load_history(PEER_ID, [hentry(90, "receive", "done"), hentry(91, "send", "cancelled_user")])

    running = key("send", 1)
    v.handle(status_changed(running))
    received = key("receive", 2)
    v.handle(status_changed(received))
    v.handle(file_done(received, tmp_path / "nhan" / "video.mp4"))
    v.handle(finished(received, "done"))
    failed = key("send", 3)
    v.handle(status_changed(failed))
    v.handle(finished(failed, "source_changed"))
    v.set_resendable(failed, True)
    v.add_pending(PEER_ID, [tmp_path / "a.bin", tmp_path / "b.bin"])
    settle()
    thread = v.thread_for(PEER_ID)
    assert thread is not None
    [history_done, history_cancelled] = thread.history_bubbles()
    return v, {
        "running": v.row(running),
        "received": v.row(received),
        "failed": v.row(failed),
        "history_done": history_done,
        "history_cancelled": history_cancelled,
        "pending": v.pending_bubbles()[0],
    }


def texts_of(view, bubbles: dict) -> dict[str, str]:
    """Mọi chữ do khung chat dựng (nhãn, nút, tên trợ năng) mà test này theo dõi."""
    out: dict[str, str] = {}
    for name, b in bubbles.items():
        out[f"{name}.status"] = b.status_label.text()
        out[f"{name}.summary"] = b.accessibleName()
    out["running.cancel"] = bubbles["running"].cancel_button.accessibleName()
    out["received.open"] = bubbles["received"].open_button.text()
    out["failed.resend"] = bubbles["failed"].resend_button.text()
    out["failed.detail"] = bubbles["failed"].detail_label.text()
    thread = view.thread_for(PEER_ID)
    out["separators"] = "|".join(s.text() for s in thread.separators())
    out["scroll"] = thread.scroll_area.accessibleName()
    out["header.status"] = view.header.status_label.text()
    out["send_button"] = view.composer.send_button.accessibleName()
    out["hint"] = view.composer.hint_label.text()
    out["new_button"] = view.new_button.accessibleName()
    return out


# =================================================================================================
# Cài / gỡ translator
# =================================================================================================


def test_installing_translator_rebuilds_every_chat_string_and_removing_restores(qtbot, scene, translator):
    view, bubbles = scene
    before = texts_of(view, bubbles)
    for name, text in before.items():
        assert text, f"tiền đề: {name} phải có chữ"
        assert PREFIX not in text, name
    assert bubbles["received"].open_button.isVisibleTo(view), "tiền đề: “Hiện trong thư mục” hiện"
    assert bubbles["failed"].resend_button.isVisibleTo(view), "tiền đề: “Gửi lại” hiện"

    QCoreApplication.installTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX in bubbles["pending"].status_label.text(), timeout=3000)
    settle()
    after = texts_of(view, bubbles)
    missing = [name for name, text in after.items() if PREFIX not in text]
    assert not missing, f"chưa dựng lại khi LanguageChange: {missing}"

    QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX not in bubbles["pending"].status_label.text(), timeout=3000)
    settle()
    assert texts_of(view, bubbles) == before


def test_language_change_rebuilds_placeholder_and_empty_state(qtbot, clock, translator):
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    devices = DeviceListModel()
    devices.reset([dview(PEER_ID, PEER)])
    v = ChatView(devices)
    v._test_devices = devices  # type: ignore[attr-defined]
    qtbot.addWidget(v)
    v.resize(720, 560)
    v.show()
    placeholder = v.placeholder.text()
    assert placeholder and PREFIX not in placeholder
    v.set_device(PEER_ID)
    qtbot.waitUntil(lambda: v.empty_state.title_label.text() != "", timeout=2000)
    empty = (v.empty_state.title_label.text(), v.empty_state.text_label.text())

    QCoreApplication.installTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX in v.empty_state.title_label.text(), timeout=3000)
    assert PREFIX in v.empty_state.text_label.text()
    v.set_device(None)
    assert PREFIX in v.placeholder.text()

    QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX not in v.placeholder.text(), timeout=3000)
    assert v.placeholder.text() == placeholder
    v.set_device(PEER_ID)
    settle()
    assert (v.empty_state.title_label.text(), v.empty_state.text_label.text()) == empty


# =================================================================================================
# Gửi thẳng QEvent(LanguageChange) (không translator)
# =================================================================================================


def test_sending_language_change_event_directly_keeps_text_and_does_not_fail(qtbot, scene):
    """Bẫy 9.6: `ChatBubble.__init__` gọi `retranslate()` trước khi lớp con dựng xong; `_render()` gọi từ
    `changeEvent` phải chạy được bất cứ lúc nào. Gửi `LanguageChange` cho từng bong bóng, luồng, đầu luồng,
    thanh dưới và cả `ChatView`: không ngoại lệ, chữ giữ nguyên, `grab()` vẫn vẽ được."""
    view, bubbles = scene
    before = texts_of(view, bubbles)
    targets = [*bubbles.values(), view.thread_for(PEER_ID), view.header, view.composer, view]
    for widget in targets:
        QApplication.sendEvent(widget, QEvent(QEvent.Type.LanguageChange))
    settle()
    assert texts_of(view, bubbles) == before
    for b in bubbles.values():
        assert not b.grab().isNull()
    assert not view.grab().isNull()


def test_language_change_on_fresh_bubbles_before_any_event(qtbot):
    """Bong bóng vừa dựng (chưa có sự kiện nào) nhận `LanguageChange` không lỗi."""
    from teleport.ui.chat_bubbles import HistoryBubble, PendingBubble, TransferBubble

    made = [
        TransferBubble(key("send", 7)),
        TransferBubble(key("receive", 8)),
        HistoryBubble(hentry(9, "receive", "made_up_result")),
        PendingBubble(1, ["x.mp4"]),
    ]
    for b in made:
        qtbot.addWidget(b)
        QApplication.sendEvent(b, QEvent(QEvent.Type.LanguageChange))
        assert b.status_label.text(), type(b).__name__
        assert not b.grab().isNull()
