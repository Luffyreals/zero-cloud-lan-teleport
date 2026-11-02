"""Chữ và luật theo từng lượt của các lượt truyền (spec PR3 pha 1, `ui/transfers_view.py`; mvp F5, F6, mục
7.3 hàng “Tiến độ”, mục 8; spec-hackathon PR3 “Xong khi” (6), (7), (8), 9.7, mục 10 A2).

Spec B3 (mục 2, 9.7, 9.8): widget danh sách cũ đã gỡ; luật theo từng lượt dời nguyên vào
`ui.chat_bubbles.TransferBubble`, API công khai giữ ở `ui.chat.ChatView`. Fixture `view` là
`ChatView(DeviceListModel())` đã `set_device(PEER_ID)`; `view.row(k)` là `TransferBubble`. Hàm chữ thuần
(`result_message`, `STALL_TEXT_AFTER`, …) vẫn ở `ui.transfers_view`. Chữ đổi cố ý theo 9.8: tiêu đề bỏ
“· tới/· từ X” (tên máy nằm ở accessibleName “Gửi tới X” / “Nhận từ X”), nhãn DONE “Đã lưu” / “Đã gửi”,
`rows()` cũ trước. Test bố cục của danh sách cũ (gợi ý rỗng, dải thông báo riêng) đã bỏ: `ChatView` dùng
`InfoBar` (9.7) và `EmptyState` (9b.21), có test riêng trong `test_chat.py`.

Đã cập nhật theo chỉnh câu chữ của điều phối (2026-10-29, kiểu AirDrop/LocalSend, thắng spec pha 1):
`status_label` là nhãn ngắn (“Đang gửi”, “Đang nhận”, “Đang chờ”, “Đang nối lại…”, “Đang kiểm tra”,
“Xong ✓”, “Lỗi”, “Đã hủy”); câu chờ cụ thể, câu lỗi mvp mục 8 và tiến độ nằm ở `detail_label`. Nhãn ngắn
kiểm theo ý nghĩa (không so nguyên văn); câu lỗi mục 8 so nguyên văn.

Sự kiện giả dựng bằng dataclass thật của `teleport.app.transfers` / `teleport.core.transfer` (không socket).
`test_section8_sentences_match_mvp_doc` đọc lại mvp.md để hằng mục 8 không lệch tài liệu.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, Qt, QTranslator

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
_MVP = Path(__file__).resolve().parents[2] / "docs" / "mvp.md"

# ---- Nhãn trạng thái ngắn (câu mới, đề xuất; chỉ dùng để kiểm theo ý nghĩa) ----
SHORT_SENDING = "Đang gửi"
SHORT_RECEIVING = "Đang nhận"
SHORT_WAITING = "Đang chờ"
SHORT_RECONNECTING = "Đang nối lại…"  # mvp F6, mục 8
SHORT_VERIFYING = "Đang kiểm tra"
SHORT_DONE_RECEIVE = "Đã lưu"  # spec B3 9.8 (ii)
SHORT_DONE_SEND = "Đã gửi"
SHORT_FAILED = "Lỗi"
SHORT_CANCELLED = "Đã hủy"

# ---- Câu chờ ở `detail_label` ----
WAIT_QUEUED_SEND = "Đang chờ {p} nhận xong lượt trước…"  # mvp 8
WAIT_ANSWER_SEND = "Đang chờ {p} trả lời…"  # mvp 7.3 (CLI)
WAIT_OFFLINE_SEND = "Đang chờ kết nối tới {p}…"  # mới (mục 10 A2)
WAIT_RESUMED = "Đang chờ {p} nối lại…"  # mới (9.7)
DONE_DETAIL = "Đã kiểm tra toàn vẹn"  # mới
CANCEL = "Hủy"
OPEN_FOLDER = "Hiện trong thư mục"  # spec-f4 mục 2.4 (trước: “Mở thư mục”)
ETA_UNKNOWN = "đang tính thời gian còn lại"  # mvp 7.3

# ---- Kết quả (mvp mục 8, nguyên văn; GUI: tên lệnh trong “…”, không backtick) ----
R_REJECTED_SEND = "{p} đã từ chối nhận file."
R_CANCEL_SEND_SELF = "Đã hủy lượt gửi tới {p}. Các file đã gửi xong vẫn nằm trên máy đó."
R_CANCEL_SEND_PEER = "{p} đã dừng nhận giữa chừng. Các file đã gửi xong vẫn nằm trên máy đó."
R_CANCEL_RECEIVE_SELF = "Đã hủy nhận từ {p}. File đã nhận xong vẫn giữ nguyên."
R_CANCEL_RECEIVE_PEER = (
    "{p} đã hủy lượt gửi. Các file chưa nhận xong đã được xóa; file đã nhận xong vẫn giữ nguyên."
)
R_CANCEL_RECEIVE_PEER_ASKING = "{p} đã hủy lượt gửi."
R_EXPIRED_SEND = "Mất kết nối với {p} quá lâu nên lượt gửi đã dừng. Hãy gửi lại."
R_EXPIRED_RECEIVE = (
    "Mất kết nối với {p} quá lâu nên đã dừng nhận. Các file chưa nhận xong đã được xóa; "
    "file đã nhận xong vẫn giữ nguyên."
)
R_SOURCE_CHANGED_SEND = "{f} đã bị thay đổi trên máy gửi nên không thể gửi tiếp. Hãy gửi lại."
R_SOURCE_CHANGED_RECEIVE = (
    "{f} đã bị thay đổi trên {p} nên không nhận tiếp được. Các file đã nhận xong vẫn giữ nguyên; "
    "hãy nhờ gửi lại."
)
# Câu giao diện (spec D4 mục 5.3, 14.14): máy nhận có thể đang tạm dừng nhận hay có thư mục nhận hỏng.
R_NOT_RECEIVING_SEND = (
    "{p} đang không nhận file mới (có thể đã tạm dừng nhận, hoặc chưa mở được thư mục nhận). "
    "Hãy nhờ bật lại việc nhận file trên máy đó rồi gửi lại."
)
# Câu CLI (mvp mục 8, “Máy nhận chưa bật nhận file”): giao diện không còn dùng, vẫn phải có trong mvp.
R_NOT_RECEIVING_CLI = "{p} chưa bật nhận file. Trên máy đó hãy chạy `teleport receive` rồi gửi lại."
DATA_UNREACHABLE = (
    "Không mở được kết nối truyền dữ liệu tới {p}; tường lửa trên máy đó có thể đang chặn Teleport. "
    "Teleport vẫn đang thử lại."
)

PREFIX = "[x]"


def fill(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def percent_values(text: str) -> list[float]:
    """Mọi số phần trăm trong chữ (“42%”, “42,0%”) dạng số thực."""
    return [float(m.replace(",", ".")) for m in re.findall(r"(\d+(?:,\d+)?)\s*%", text)]


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


# =================================================================================================
# Dựng sự kiện giả
# =================================================================================================


def key(direction: str = "send", transfer_id: str = "c" * 32, device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), transfer_id)


def entry(index: int, name: str, size: int):
    """`FileEntry` thật. Tên độc không hợp lệ ở mức giao thức thì mục mang tên thay thế; tên độc chỉ
    nằm trong `names` (tên để hiện)."""
    from teleport.core.messages import FileEntry, MessageError

    try:
        return FileEntry(name, size, 1_700_000_000_000)
    except MessageError:
        return FileEntry(f"raw{index}.bin", size, 1_700_000_000_000)


def info(
    k,
    status: str = "transferring",
    files=(("video.mp4", 8 * 2**30),),
    done: int = 0,
    total: int | None = None,
    file_index: int = 0,
    unsynced: int = 0,
):
    from teleport.core.transfer import TransferInfo, TransferStatus

    entries = tuple(entry(i, name, size) for i, (name, size) in enumerate(files))
    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=entries,
        names=tuple(name for name, _ in files),
        file_index=file_index,
        done_bytes=done,
        total_bytes=sum(s for _, s in files) if total is None else total,
        unsynced_bytes=unsynced,
    )


def status_changed(k, status: str, **kw):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(info(k, status, **kw))


def progress(
    k,
    done: int,
    total: int,
    bps: float = 85.2 * 2**20,
    eta: float | None = 62.0,
    *,
    shown: int | None = None,
    idle: float = 0.0,
    status: str = "transferring",
    **kw,
):
    """`TransferProgress` giả; `shown` mặc định = `done` (spec PR-1: `shown_bytes`, `idle_seconds`)."""
    from teleport.app.transfers import TransferProgress

    return TransferProgress(
        info(k, status, done=done, total=total, **kw),
        bps,
        eta,
        shown_bytes=done if shown is None else shown,
        idle_seconds=idle,
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


def offer_received(k, device_name: str | None = PEER, files=(("video.mp4", 8 * 2**30),)):
    from teleport.app.transfers import OfferReceived

    entries = tuple(entry(i, name, size) for i, (name, size) in enumerate(files))
    return OfferReceived(
        key=k,
        device_name=device_name,
        files=entries,
        names=tuple(n for n, _ in files),
        total_bytes=sum(s for _, s in files),
        auto_accepted=False,
    )


def resumed(k, **kw):
    from teleport.app.transfers import TransferResumed

    return TransferResumed(info(k, "reconnecting", **kw))


def file_done(k, path: Path | None, index: int = 0, name: str = "video.mp4"):
    from teleport.app.transfers import FileDone

    return FileDone(key=k, file_index=index, name=name, path=path)


def data_unreachable(device_id: str = PEER_ID):
    from teleport.app.transfers import DataUnreachable

    return DataUnreachable(device_id)


def row_texts(row) -> str:
    return "\n".join(
        lb.text()
        for lb in (row.title_label, row.size_label, row.status_label, row.detail_label)
        if lb is not None and lb.text()
    )


def make_view(qtbot, names: dict | None = None):
    """`ChatView` đứng riêng (spec B3 mục 2), đã mở luồng của `PEER_ID`."""
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    v = ChatView(DeviceListModel())
    qtbot.addWidget(v)
    v.cancels = []  # type: ignore[attr-defined]
    v.cancel_requested.connect(lambda k: v.cancels.append(k))
    if names is not None:
        v.set_device_names(names)
    v.set_device(PEER_ID)
    v.resize(720, 460)
    v.show()
    return v


def shown(widget, root) -> bool:
    return widget.isVisibleTo(root)


@pytest.fixture
def view(qtbot):
    return make_view(qtbot, {PEER_ID: PEER})


@pytest.fixture
def translator():
    t = PrefixTranslator()
    yield t
    QCoreApplication.removeTranslator(t)


# =================================================================================================
# Trạng thái theo TransferStatus × chiều (F5, mục 8)
# =================================================================================================

# (chiều, trạng thái, chữ thường phải có trong nhãn ngắn, câu phải có trong `detail_label` hoặc None)
STATUS_CASES = [
    ("send", "queued", "chờ", WAIT_QUEUED_SEND),
    ("receive", "queued", "chờ", None),
    ("send", "waiting", "chờ", WAIT_ANSWER_SEND),
    ("receive", "waiting", "chờ", None),
    ("send", "transferring", "gửi", None),
    ("receive", "transferring", "nhận", None),
    ("send", "verifying", "kiểm tra", None),
    ("receive", "verifying", "kiểm tra", None),
    ("send", "reconnecting", "nối lại", None),
    ("receive", "reconnecting", "nối lại", None),
]


@pytest.mark.parametrize(("direction", "status", "short_word", "detail"), STATUS_CASES)
def test_status_label_and_detail_per_status_and_direction(view, direction, status, short_word, detail):
    k = key(direction)
    view.set_connected(PEER_ID, True)
    view.handle(status_changed(k, status))
    row = view.row(k)
    assert row is not None
    short = row.status_label.text()
    assert short_word in short.lower(), short
    assert len(short) <= 20, f"nhãn trạng thái phải ngắn: {short!r}"
    if detail is not None:
        assert fill(detail, p=PEER) in row.detail_label.text()


def test_every_transfer_status_is_covered_by_this_table():
    from teleport.core.transfer import Direction, TransferStatus

    covered = {(d, s) for d, s, _, _ in STATUS_CASES}
    assert covered == {(d.value, s.value) for d in Direction for s in TransferStatus}


def test_send_and_receive_transferring_labels_differ(view):
    s, r = key("send"), key("receive", "d" * 32)
    view.handle(status_changed(s, "transferring"))
    view.handle(status_changed(r, "transferring"))
    assert view.row(s).status_label.text() != view.row(r).status_label.text()


def test_send_waiting_while_not_connected(view):
    k = key("send")
    view.set_connected(PEER_ID, False)
    view.handle(status_changed(k, "waiting"))
    assert fill(WAIT_OFFLINE_SEND, p=PEER) in view.row(k).detail_label.text()
    view.set_connected(PEER_ID, True)
    detail = view.row(k).detail_label.text()
    assert fill(WAIT_ANSWER_SEND, p=PEER) in detail
    assert fill(WAIT_OFFLINE_SEND, p=PEER) not in detail
    view.set_connected(PEER_ID, False)
    assert fill(WAIT_OFFLINE_SEND, p=PEER) in view.row(k).detail_label.text()


def test_clear_forgets_connection_state(view):
    """Host mới: trạng thái “chưa kết nối” của host cũ không được dính sang thẻ mới."""
    view.set_connected(PEER_ID, False)
    view.clear()
    k = key("send")
    view.handle(status_changed(k, "waiting"))
    detail = view.row(k).detail_label.text()
    assert fill(WAIT_OFFLINE_SEND, p=PEER) not in detail
    assert fill(WAIT_ANSWER_SEND, p=PEER) in detail


def test_notice_action_button_tab_order_and_hidden_without_action(view):
    calls: list[int] = []
    view.show_notice("Câu có nút.", "Làm gì đó", lambda: calls.append(1))
    assert view.notice_action_text() == "Làm gì đó"
    assert view.notice_action.accessibleName() == "Làm gì đó"
    # Thứ tự Tab: nút hành động → “Đóng” của `info_bar` (9.7: `notice_close` bỏ, dùng `InfoBar.close_button`).
    assert view.notice_action.nextInFocusChain() is view.info_bar.close_button
    view.notice_action.click()
    assert calls == [1]
    assert view.notice_text() == ""  # 9.7: “” khi ẩn
    view.show_notice("Câu không nút.")
    assert view.notice_action_text() is None
    view.show_notice("Câu thiếu hàm.", "Nút", None)
    assert view.notice_action_text() is None


def test_not_connected_does_not_change_transferring_or_receive_rows(view):
    view.set_connected(PEER_ID, False)
    offline = fill(WAIT_OFFLINE_SEND, p=PEER)
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    assert offline not in row_texts(view.row(k))
    r = key("receive", "d" * 32)
    view.handle(status_changed(r, "waiting"))
    assert offline not in row_texts(view.row(r))


def test_status_change_updates_same_row(view):
    k = key("send")
    view.set_connected(PEER_ID, True)
    view.handle(status_changed(k, "waiting"))
    row = view.row(k)
    view.handle(status_changed(k, "transferring"))
    view.handle(status_changed(k, "reconnecting"))
    assert view.row(k) is row
    assert len(view.rows()) == 1
    assert "nối lại" in row.status_label.text().lower()
    assert fill(WAIT_ANSWER_SEND, p=PEER) not in row.detail_label.text(), "câu chờ cũ phải được xóa"


def test_offer_received_adds_receive_row_waiting(view):
    k = key("receive")
    view.handle(offer_received(k))
    view.handle(offer_received(k))
    assert len(view.rows()) == 1
    row = view.row(k)
    assert row.key == k
    assert "chờ" in row.status_label.text().lower()
    assert f"Nhận từ {PEER}" in row.accessibleName()  # 9.8 (i): tên máy rời tiêu đề, còn ở accessibleName


# =================================================================================================
# Tiêu đề hàng, tên máy
# =================================================================================================


def test_title_send_many_files_shows_count_and_size(view):
    from teleport.core.display import format_size

    files = (("a.bin", 2**20), ("b.bin", 3 * 2**20), ("c.bin", 5))
    k = key("send")
    view.handle(status_changed(k, "transferring", files=files))
    row = view.row(k)
    # 9.8 (i) + mục 4 dòng 1: tiêu đề “3 file” không “· tới X”, cỡ ở `size_label`.
    assert row.title_label.full_text() == "3 file"
    assert row.size_label.text() == format_size(sum(s for _, s in files))
    assert f"Gửi tới {PEER}" in row.accessibleName()


def test_title_single_file_shows_file_name(view):
    from teleport.ui.texts import file_label

    name = "bao-cao-" * 20 + ".docx"
    k = key("receive")
    view.handle(status_changed(k, "transferring", files=((name, 10),)))
    row = view.row(k)
    text = row_texts(row)
    assert f"Nhận từ {PEER}" in row.accessibleName()  # 9.8 (i)
    assert row.title_label.full_text() == file_label(name)  # tiêu đề cắt giữa theo bề ngang (mục 4)
    assert name not in text


def test_unknown_device_shows_first_8_chars_of_id(qtbot):
    v = make_view(qtbot)
    k = key("receive")
    v.handle(status_changed(k, "transferring"))
    row = v.row(k)
    assert f"Nhận từ {PEER_ID[:8]}" in row.accessibleName()  # 9.8 (i)
    assert PEER_ID not in row_texts(row) and PEER_ID not in row.accessibleName()


def test_set_device_names_redraws_existing_rows(view):
    k = key("send")
    view.set_device_names({})
    view.set_connected(PEER_ID, True)
    view.handle(status_changed(k, "waiting"))
    # 9.8 (i): tên máy ở accessibleName (“Gửi tới X”) và câu chờ, không ở tiêu đề.
    assert f"Gửi tới {PEER_ID[:8]}" in view.row(k).accessibleName()
    view.set_device_names({PEER_ID: "May-Moi"})
    assert "Gửi tới May-Moi" in view.row(k).accessibleName()
    assert fill(WAIT_ANSWER_SEND, p="May-Moi") in view.row(k).detail_label.text()
    view.set_device_names({PEER_ID: None})
    assert f"Gửi tới {PEER_ID[:8]}" in view.row(k).accessibleName()


def test_hostile_device_and_file_names_shown_as_plain_text(view):
    from PySide6.QtWidgets import QLabel, QWidget

    from teleport.ui.texts import file_label, peer_label

    device = "<b>X</b>‮\n"
    name = "<i>f</i>‮\ngnp.exe"
    view.set_device_names({PEER_ID: device})
    k = key("receive")
    view.handle(status_changed(k, "transferring", files=((name, 10),)))
    d = key("receive", "d" * 32)
    view.handle(status_changed(d, "transferring", files=((name, 10),)))
    view.handle(finished(d, "cancelled_user", by_peer=True, files=((name, 10),)))
    text = "\n".join(lb.text() for lb in view.findChildren(QLabel))
    assert peer_label(device, PEER_ID) in text  # tên máy ở đầu luồng (mục 5)
    assert view.row(k).title_label.full_text() == file_label(name)  # tiêu đề cắt giữa (mục 4)
    assert "<i>f</i>‮" not in text  # BiDi trong tên file thành `·` (mvp 7.3)
    for lb in view.findChildren(QLabel):
        if "<b>" in lb.text() or "<i>" in lb.text():
            assert lb.textFormat() == Qt.TextFormat.PlainText, lb.text()
    for w in [view, *view.findChildren(QWidget)]:
        assert "<b>X" not in w.toolTip() and "<i>f" not in w.toolTip()


def test_all_row_labels_are_plain_text(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    row = view.row(k)
    for lb in (row.title_label, row.size_label, row.status_label, row.detail_label):
        assert lb.textFormat() == Qt.TextFormat.PlainText


# =================================================================================================
# Tiến độ (mvp 7.3 hàng “Tiến độ”; Xong khi (6), (8))
# =================================================================================================


def test_progress_shows_percent_speed_and_eta(view):
    from teleport.core.display import format_duration, format_size

    total = 1000 * 2**20
    done = 420 * 2**20
    bps = 85.2 * 2**20
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, done, total, bps=bps, eta=62.0))
    row = view.row(k)
    assert row.progress_bar.minimum() == 0 and row.progress_bar.maximum() == 1000
    assert row.progress_bar.value() == 420
    detail = row.detail_label.text()
    assert [int(p) for p in percent_values(detail)] == [42], detail
    assert f"{format_size(int(bps))}/s" in detail
    assert format_size(int(bps)) == "85,2 MB"
    assert f"còn {format_duration(62.0)}" in detail
    assert ETA_UNKNOWN not in detail


def test_progress_without_eta_says_still_estimating(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 10, 1000, bps=0.0, eta=None))
    detail = view.row(k).detail_label.text()
    assert ETA_UNKNOWN in detail
    assert "còn " not in detail.replace(ETA_UNKNOWN, "")


def test_progress_never_shows_100_percent_before_done(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 999_999, 1_000_000))
    row = view.row(k)
    assert row.progress_bar.value() == 999
    values = percent_values(row.detail_label.text())
    assert values and all(99 <= v < 100 for v in values), row.detail_label.text()


def test_progress_four_terabytes_half_way_is_500(view):
    k = key("send")
    view.handle(status_changed(k, "transferring", files=(("disk.img", 2**42),)))
    view.handle(progress(k, 2**41, 2**42, files=(("disk.img", 2**42),)))
    row = view.row(k)
    assert row.progress_bar.value() == 500
    assert [int(p) for p in percent_values(row.detail_label.text())] == [50]


def test_progress_total_zero_gives_zero(view):
    k = key("send")
    view.handle(status_changed(k, "transferring", files=(("rong.txt", 0),)))
    view.handle(progress(k, 0, 0, files=(("rong.txt", 0),)))
    assert view.row(k).progress_bar.value() == 0


def test_thousand_progress_updates_in_place_and_fast(view):
    from PySide6.QtWidgets import QWidget

    k = key("send")
    total = 2**42
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 0, total))
    row = view.row(k)
    bar, status, detail = row.progress_bar, row.status_label, row.detail_label
    widgets_before = len(view.findChildren(QWidget))
    updates = [progress(k, total * i // 1000, total, eta=float(1000 - i)) for i in range(1, 1001)]
    start = time.perf_counter()
    for u in updates:
        view.handle(u)
    elapsed = time.perf_counter() - start
    assert elapsed < 1.0, elapsed
    assert len(view.rows()) == 1
    assert view.row(k) is row
    assert row.progress_bar is bar and row.status_label is status and row.detail_label is detail
    assert len(view.findChildren(QWidget)) == widgets_before
    assert bar.value() == 1000


# =================================================================================================
# Kết thúc (Xong khi (7))
# =================================================================================================

ALL_DIRECTIONS = ("send", "receive")


def test_done_shows_done_label_verified_detail_and_full_bar(view):
    # 9.8 (ii): nhãn DONE là “Đã lưu” (nhận) / “Đã gửi” (gửi); dòng phụ giữ `done_text()`.
    for direction, label in (("send", SHORT_DONE_SEND), ("receive", SHORT_DONE_RECEIVE)):
        k = key(direction)
        view.handle(status_changed(k, "transferring"))
        view.handle(finished(k, "done", status="verifying", done=8 * 2**30))
        row = view.row(k)
        assert row.status_label.text() == label
        assert DONE_DETAIL in row.detail_label.text()
        assert row.progress_bar.value() == 1000
        assert row.finished is True


def test_every_result_and_direction_has_a_sentence(qtbot):
    """Mỗi `TransferResult` × chiều ra nhãn ngắn không rỗng; câu chi tiết không backtick (trừ SUSPENDED:
    giữ hàng như cũ). Câu chi tiết bắt buộc trừ khi máy này là bên nhận và lượt bị từ chối (máy này tự
    từ chối: nhãn ngắn “Đã từ chối” đã đủ, như CLI chỉ in “Đã từ chối.”)."""
    from teleport.app.transfers import TransferResult

    v = make_view(qtbot, {PEER_ID: PEER})
    missing = []
    for i, result in enumerate(TransferResult):
        if result is TransferResult.SUSPENDED:
            continue
        for direction in ALL_DIRECTIONS:
            for by_peer in (False, True):
                k = key(direction, f"{i:02}{direction[0]}{int(by_peer)}" + "0" * 28)
                v.handle(status_changed(k, "transferring"))
                v.handle(finished(k, result.value, by_peer=by_peer))
                row = v.row(k)
                short, detail = row.status_label.text().strip(), row.detail_label.text().strip()
                self_reject = direction == "receive" and result.value.startswith("rejected_")
                if not short or (not detail and not self_reject) or "`" in detail:
                    missing.append((result.value, direction, by_peer, short, detail))
    assert not missing, missing


def test_failed_and_cancelled_short_labels_differ_from_done(view):
    ok, bad, cancelled = key("send"), key("send", "d" * 32), key("send", "e" * 32)
    for k in (ok, bad, cancelled):
        view.handle(status_changed(k, "transferring"))
    view.handle(finished(ok, "done"))
    view.handle(finished(bad, "disk_failed"))
    view.handle(finished(cancelled, "cancelled_user"))
    labels = {view.row(k).status_label.text() for k in (ok, bad, cancelled)}
    assert len(labels) == 3, labels


@pytest.mark.parametrize(
    ("direction", "result", "by_peer", "status", "template"),
    [
        ("send", "rejected_user", True, "waiting", R_REJECTED_SEND),
        ("send", "cancelled_user", False, "transferring", R_CANCEL_SEND_SELF),
        ("send", "cancelled_user", True, "transferring", R_CANCEL_SEND_PEER),
        ("receive", "cancelled_user", False, "transferring", R_CANCEL_RECEIVE_SELF),
        ("receive", "cancelled_user", True, "transferring", R_CANCEL_RECEIVE_PEER),
        ("receive", "cancelled_user", True, "waiting", R_CANCEL_RECEIVE_PEER_ASKING),
        ("send", "expired", False, "reconnecting", R_EXPIRED_SEND),
        ("receive", "expired", False, "reconnecting", R_EXPIRED_RECEIVE),
        ("send", "source_changed", False, "transferring", R_SOURCE_CHANGED_SEND),
        ("receive", "source_changed", True, "transferring", R_SOURCE_CHANGED_RECEIVE),
        ("send", "rejected_not_receiving", True, "waiting", R_NOT_RECEIVING_SEND),
    ],
)
def test_result_sentences_match_section_8(view, direction, result, by_peer, status, template):
    k = key(direction)
    view.handle(status_changed(k, status))
    view.handle(finished(k, result, by_peer=by_peer, status=status))
    assert view.row(k).detail_label.text() == fill(template, p=PEER, f="video.mp4")


def test_receive_dir_missing_names_the_folder_not_a_disk_error():
    """Thư mục nhận mất mà không tạo lại được: câu nói đúng nguyên nhân, không đổ cho ổ đĩa lỗi."""
    from teleport.ui.transfers_view import result_message

    fin = finished(key("receive"), "receive_dir_missing")
    text = result_message(fin, PEER, Path(r"C:\Users\A\Downloads\Teleport"))
    assert "thư mục nhận" in text and r"C:\Users\A\Downloads\Teleport" in text
    assert PEER in text
    assert "ổ đĩa báo lỗi" not in text


def test_finished_row_hides_or_disables_cancel(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    row = view.row(k)
    assert shown(row.cancel_button, view) and row.cancel_button.isEnabled()
    assert row.finished is False
    view.handle(finished(k, "cancelled_user", by_peer=True))
    assert row.finished is True
    assert not (shown(row.cancel_button, view) and row.cancel_button.isEnabled())


def test_finished_row_ignores_late_updates(view):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    view.handle(progress(k, 300, 1000))
    view.handle(finished(k, "expired", status="reconnecting"))
    row = view.row(k)
    status, value, detail = row.status_label.text(), row.progress_bar.value(), row.detail_label.text()
    assert detail == fill(R_EXPIRED_SEND, p=PEER)
    view.handle(progress(k, 900, 1000))
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "done"))
    view.handle(data_unreachable())
    assert view.row(k) is row and len(view.rows()) == 1
    assert row.status_label.text() == status
    assert row.progress_bar.value() == value
    assert row.detail_label.text() == detail


def test_suspended_keeps_row_as_it_was(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    before = (view.row(k).status_label.text(), view.row(k).detail_label.text())
    view.handle(finished(k, "suspended"))
    row = view.row(k)
    assert row is not None
    assert (row.status_label.text(), row.detail_label.text()) == before


# =================================================================================================
# Nút Hủy, Hiện trong thư mục
# =================================================================================================


def test_cancel_button_emits_cancel_requested_with_key(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    row = view.row(k)
    # Mục 4: `cancel_button` là `IconButton("dismiss", "Hủy")` chỉ có icon: chữ ở tên trợ năng.
    assert row.cancel_button.accessibleName().replace("&", "") == CANCEL
    row.cancel_button.click()
    assert view.cancels == [k]


def test_open_folder_opens_parent_of_last_received_file(view, monkeypatch, tmp_path):
    from PySide6.QtCore import QUrl

    from teleport.ui import chat

    opened: list = []
    # Spec B3 mục 2: seam `open_url` dời sang `ui/chat.py`.
    monkeypatch.setattr(chat, "open_url", lambda url: opened.append(QUrl(url)) or True)
    folder = tmp_path / "nhan"
    files = (("a.bin", 5), ("b.bin", 5))
    k = key("receive")
    view.handle(status_changed(k, "transferring", files=files))
    row = view.row(k)
    assert not shown(row.open_button, view), "“Hiện trong thư mục” ẩn tới khi nhận xong"
    view.handle(file_done(k, tmp_path / "cu" / "a.bin", 0, "a.bin"))
    view.handle(file_done(k, folder / "b (1).bin", 1, "b.bin"))
    assert not shown(row.open_button, view)
    view.handle(finished(k, "done", status="verifying", files=files))
    assert shown(row.open_button, view)
    assert row.open_button.text().replace("&", "") == OPEN_FOLDER
    row.open_button.click()
    assert len(opened) == 1
    assert opened[0].isLocalFile()
    assert Path(opened[0].toLocalFile()) == folder


def test_open_folder_not_shown_for_send_or_receive_without_file(view):
    s = key("send")
    view.handle(status_changed(s, "transferring"))
    view.handle(file_done(s, None))
    view.handle(finished(s, "done"))
    assert not shown(view.row(s).open_button, view)
    r = key("receive", "d" * 32)
    view.handle(status_changed(r, "transferring"))
    view.handle(finished(r, "done"))
    assert not shown(view.row(r).open_button, view)


def test_open_folder_not_shown_when_receive_fails(view, tmp_path):
    k = key("receive")
    view.handle(status_changed(k, "transferring", files=(("a.bin", 5), ("b.bin", 5))))
    view.handle(file_done(k, tmp_path / "a.bin"))
    view.handle(finished(k, "cancelled_user", by_peer=True))
    assert not shown(view.row(k).open_button, view)


def test_buttons_reachable_by_tab_and_have_accessible_names(view):
    # 9.10: nút trong bong bóng là ClickFocus; Tab tới chúng qua roving tabindex của luồng
    # (`focus_buttons()` của bong bóng hiện hành; đường Tab thật kiểm ở test_chat.py F2).
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    row = view.row(k)
    button = row.cancel_button
    assert button in row.focus_buttons()
    assert button.focusPolicy() & Qt.FocusPolicy.ClickFocus
    assert (button.accessibleName() or button.text()).replace("&", "")


# =================================================================================================
# Ảnh chụp lúc `started`, khôi phục (9.7)
# =================================================================================================


def test_snapshot_after_resumed_does_not_duplicate(view):
    k = key("receive")
    view.handle(resumed(k, done=4 * 2**30))
    row = view.row(k)
    assert fill(WAIT_RESUMED, p=PEER) in row.detail_label.text()
    other = key("send", "d" * 32)
    view.load_snapshot([info(k, "reconnecting", done=4 * 2**30), info(other, "queued")])
    keys = [r.key for r in view.rows()]
    assert keys == [k, other]  # 9.8 (iii): `rows()` cũ trước; không nhân đôi
    assert view.row(k) is row
    assert fill(WAIT_RESUMED, p=PEER) in row.detail_label.text()


def test_snapshot_twice_and_resumed_after_snapshot_do_not_duplicate(view):
    a, b = key("receive"), key("send", "d" * 32)
    view.load_snapshot([info(a, "reconnecting"), info(b, "transferring")])
    view.load_snapshot([info(a, "reconnecting"), info(b, "transferring")])
    view.handle(resumed(a))
    assert [r.key for r in view.rows()] == [a, b]  # 9.8 (iii): `rows()` cũ trước; không nhân đôi


def test_snapshot_rows_show_status_text(view):
    a = key("send")
    view.set_connected(PEER_ID, True)
    view.load_snapshot([info(a, "queued")])
    assert fill(WAIT_QUEUED_SEND, p=PEER) in view.row(a).detail_label.text()


def test_resumed_without_device_name_uses_id_prefix(qtbot):
    v = make_view(qtbot)
    k = key("receive")
    v.handle(resumed(k))
    assert fill(WAIT_RESUMED, p=PEER_ID[:8]) in v.row(k).detail_label.text()


# =================================================================================================
# DataUnreachable
# =================================================================================================


def test_data_unreachable_marks_unfinished_rows_of_that_device_only(view):
    view.set_device_names({PEER_ID: PEER, OTHER_ID: "May-Khac"})
    live = key("send")
    done = key("send", "d" * 32)
    other = key("send", "e" * 32, device_id=OTHER_ID)
    view.handle(status_changed(live, "reconnecting"))
    view.handle(status_changed(done, "transferring"))
    view.handle(finished(done, "cancelled_user"))
    view.handle(status_changed(other, "transferring"))
    view.handle(data_unreachable(PEER_ID))
    sentence = fill(DATA_UNREACHABLE, p=PEER)
    assert sentence in view.row(live).detail_label.text()
    assert sentence not in row_texts(view.row(done))
    assert "Không mở được kết nối truyền dữ liệu" not in row_texts(view.row(other))


# =================================================================================================
# clear() (gợi ý “Kéo file vào một thiết bị để gửi” của danh sách cũ đã bỏ: 9.7 bỏ `empty_label`; luồng
# rỗng là `EmptyState` theo 9b.21, test V6 trong test_chat.py)
# =================================================================================================


def test_clear_forgets_rows_and_new_events_rebuild(view):
    a, b = key("send"), key("receive", "d" * 32)
    assert view.rows() == []
    view.handle(status_changed(a, "transferring"))
    view.handle(offer_received(b))
    assert len(view.rows()) == 2
    view.clear()
    assert view.rows() == []
    assert view.row(a) is None and view.row(b) is None
    view.handle(status_changed(a, "transferring"))
    assert len(view.rows()) == 1


def test_unknown_key_row_is_none(view):
    assert view.row(key("send", "9" * 32)) is None


# =================================================================================================
# Đổi ngôn ngữ
# =================================================================================================


def test_language_change_retranslates_rows(qtbot, view, translator):
    k = key("send")
    view.handle(status_changed(k, "transferring"))
    row = view.row(k)
    before = row.status_label.text()
    assert PREFIX not in before
    QCoreApplication.installTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX in row.status_label.text(), timeout=3_000)
    assert PREFIX in row.cancel_button.accessibleName()  # nút ✕ chỉ có icon: chữ ở tên trợ năng
    QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: PREFIX not in row.status_label.text(), timeout=3_000)
    assert row.status_label.text() == before


# =================================================================================================
# Câu mục 8 trong file này khớp mvp.md
# =================================================================================================


def test_section8_sentences_match_mvp_doc():
    doc = _MVP.read_text(encoding="utf-8")
    p = {"p": "*PC-Nha*", "f": "*video.mp4*"}
    samples = [
        fill(WAIT_QUEUED_SEND, **p),
        fill(R_REJECTED_SEND, **p),
        fill(R_CANCEL_SEND_SELF, **p),
        fill(R_CANCEL_SEND_PEER, **p),
        fill(R_CANCEL_RECEIVE_SELF, p="*Laptop-Minh*"),
        fill(R_CANCEL_RECEIVE_PEER, p="*Laptop-Minh*"),
        fill(R_CANCEL_RECEIVE_PEER_ASKING, p="*Laptop-Minh*"),
        fill(R_EXPIRED_SEND, **p),
        fill(R_EXPIRED_RECEIVE, p="*Laptop-Minh*"),
        fill(R_SOURCE_CHANGED_SEND, **p),
        fill(R_SOURCE_CHANGED_RECEIVE, p="*Laptop-Minh*", f="*video.mp4*"),
        fill(R_NOT_RECEIVING_CLI, **p),
        fill(DATA_UNREACHABLE, **p),
        SHORT_RECONNECTING,
        ETA_UNKNOWN,
    ]
    for sample in samples:
        assert sample in doc, sample


# =================================================================================================
# Từ chối vì ổ nhận: không đủ chỗ / FAT32 (mvp F4 “Hủy và từ chối”, mục 8 hai dòng “Không đủ dung
# lượng”, “Thư mục nhận nằm trên ổ không chứa được file lớn như vậy”, dòng “Cách gọi ổ…”)
# =================================================================================================

# Nguyên văn mvp mục 8 (phần in nghiêng thay bằng {chỗ}).
R_NO_SPACE_RECEIVE = "Đã từ chối {n} file từ {p}: không đủ chỗ trống, cần {needed}, {drive} còn {available}."
R_NO_SPACE_SEND = "{p} không đủ chỗ trống để nhận: cần {needed}, ổ lưu file trên máy đó còn {available}."
R_TOO_LARGE_RECEIVE = (
    "Đã từ chối {n} file từ {p}: {drive} chỉ chứa được file nhỏ hơn {limit}, mà {f} nặng {size}."
)
R_TOO_LARGE_SEND = (
    "{p} không nhận được {f} ({size}): ổ lưu file trên máy đó chỉ chứa được file nhỏ hơn {limit}."
)
# Số liệu của ví dụ trong mvp mục 8: cần 12,4 GB, còn 8,1 GB; FAT32: file < 4 GB, video.mp4 8,0 GB.
NEEDED = int(12.4 * 2**30)
AVAILABLE = int(8.1 * 2**30)
FAT32_MAX = 4 * 2**30 - 1  # `max_size`: file lớn nhất hệ file chứa được (protocol `reject{file_too_large}`)
BIG = 8 * 2**30
THREE_FILES = (("anh.jpg", 2 * 2**20), ("video.mp4", BIG), ("ghi-chu.txt", 300))
_UNC_PREFIX = "\\\\?\\UNC\\"  # tiền tố đường dẫn dài của ổ mạng Windows: \\?\UNC\


def _expected_drive(receive_dir: str | None) -> str:
    """Cách gọi ổ theo mvp mục 8 dòng “Cách gọi ổ của thư mục nhận”, viết lại độc lập với code."""
    import sys

    if receive_dir is None:
        return "ổ lưu file"
    if sys.platform == "win32":
        if receive_dir.startswith(_UNC_PREFIX):
            share = "\\\\" + receive_dir[len(_UNC_PREFIX) :]
            return "ổ mạng " + "\\".join(share.split("\\")[:4])
        return f"ổ {receive_dir[:2].upper()}"
    return f"ổ chứa {receive_dir}"


def rejected(k, result: str, reject_fields: dict, files=THREE_FILES, by_peer: bool = True):
    """`TransferFinished` của lượt bị từ chối với `Reject` thật (protocol `reject`)."""
    from teleport.app.transfers import TransferFinished, TransferResult
    from teleport.core.messages import Reject

    reason = {"rejected_no_space": "no_space", "rejected_file_too_large": "file_too_large"}[result]
    return TransferFinished(
        info=info(k, "waiting", files=files),
        result=TransferResult(result),
        by_peer=by_peer,
        reason=reason,
        file_index=0,
        reject=Reject(k.transfer_id, reason, **reject_fields),
    )


@pytest.mark.parametrize("receive_dir", [r"D:\x", r"\\?\UNC\srv\share", None])
@pytest.mark.parametrize(
    ("direction", "result"),
    [
        ("receive", "rejected_no_space"),
        ("send", "rejected_no_space"),
        ("receive", "rejected_file_too_large"),
        ("send", "rejected_file_too_large"),
    ],
)
def test_no_space_and_file_too_large_sentences_both_directions(view, direction, result, receive_dir):
    from teleport.core.display import format_size

    k = key(direction)
    view.set_receive_dir(None if receive_dir is None else Path(receive_dir))
    view.handle(status_changed(k, "waiting", files=THREE_FILES))
    if result == "rejected_no_space":
        fields = {"needed": NEEDED, "available": AVAILABLE}
    else:
        fields = {"file_index": 1, "max_size": FAT32_MAX}
    # Bên nhận tự từ chối (không hỏi người dùng); bên gửi nhận `reject` từ máy kia.
    view.handle(rejected(k, result, fields, by_peer=direction == "send"))
    detail = view.row(k).detail_label.text()

    values = {
        "p": PEER,
        "n": "3",
        "needed": format_size(NEEDED),
        "available": format_size(AVAILABLE),
        "f": "video.mp4",
        "size": format_size(BIG),
        "limit": format_size(FAT32_MAX + 1, trim=True),
        "drive": _expected_drive(receive_dir),
    }
    template = {
        ("receive", "rejected_no_space"): R_NO_SPACE_RECEIVE,
        ("send", "rejected_no_space"): R_NO_SPACE_SEND,
        ("receive", "rejected_file_too_large"): R_TOO_LARGE_RECEIVE,
        ("send", "rejected_file_too_large"): R_TOO_LARGE_SEND,
    }[(direction, result)]
    assert detail == fill(template, **values)
    # Số liệu của ví dụ mvp, kiểm độc lập với `format_size`.
    if result == "rejected_no_space":
        assert "12,4 GB" in detail and "8,1 GB" in detail, detail
    else:
        assert "nhỏ hơn 4 GB" in detail and "8,0 GB" in detail, detail
    if direction == "send" and receive_dir is not None:
        # Câu của máy gửi nói về ổ của máy kia: không lộ thư mục nhận của chính máy này.
        assert _expected_drive(receive_dir) not in detail, detail
    assert not any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in detail), repr(detail)
    assert "`" not in detail


@pytest.mark.parametrize("direction", ALL_DIRECTIONS)
@pytest.mark.parametrize("result", ["rejected_no_space", "rejected_file_too_large"])
def test_disk_reject_sentences_have_no_control_chars_from_peer_or_path(qtbot, direction, result):
    """Tên máy kia, tên file (đến từ máy khác) và thư mục nhận có ký tự điều khiển → câu không chứa ký tự
    điều khiển nào (mvp N8: chữ của máy khác hiện như chữ thuần)."""
    v = make_view(qtbot, {PEER_ID: "PC\x1b[31m-Nha\r\n"})
    v.set_receive_dir(Path("/tmp/nhan\x07\x1b/Teleport"))
    k = key(direction)
    files = (("a.txt", 10), ("vi\x1b[2Jdeo\n.mp4", BIG))
    v.handle(status_changed(k, "waiting", files=files))
    fields = (
        {"needed": NEEDED, "available": AVAILABLE}
        if result == "rejected_no_space"
        else {"file_index": 1, "max_size": FAT32_MAX}
    )
    v.handle(rejected(k, result, fields, files=files, by_peer=direction == "send"))
    detail = v.row(k).detail_label.text()
    assert detail, "phải có câu lý do ở cả hai chiều"
    assert not any(ord(ch) < 0x20 or 0x7F <= ord(ch) < 0xA0 for ch in detail), repr(detail)


def test_disk_reject_sentences_match_mvp_doc():
    """Bốn câu trên khớp nguyên văn ví dụ trong mvp mục 8 (để hằng của test không lệch tài liệu)."""
    doc = _MVP.read_text(encoding="utf-8")
    samples = [
        fill(
            R_NO_SPACE_RECEIVE,
            n="*3*",
            p="*Laptop-Minh*",
            needed="*12,4 GB*",
            drive="*ổ D:*",
            available="*8,1 GB*",
        ),
        fill(R_NO_SPACE_SEND, p="*PC-Nha*", needed="*12,4 GB*", available="*8,1 GB*"),
        fill(
            R_TOO_LARGE_RECEIVE,
            n="3",
            p="*Laptop-Minh*",
            drive="ổ *E:*",
            limit="4 GB",
            f="*video.mp4*",
            size="8,0 GB",
        ),
        fill(R_TOO_LARGE_SEND, p="*PC-Nha*", f="*video.mp4*", size="8,0 GB", limit="4 GB"),
        r"Windows: “ổ *D:*”; ổ mạng Windows: “ổ mạng *\\máy\chia-sẻ*”",
    ]
    for sample in samples:
        assert sample in doc, sample


# =================================================================================================
# Spec hackathon PR-1 (mục 1 “ui/transfers_view.py”, mục 2, mục 3 ý 6–7): thẻ nói đúng sự thật khi
# dữ liệu ngừng chảy; thanh không lùi; dải thông báo hai hàng.
# =================================================================================================

MiB = 2**20
RECONNECT_DETAIL = "{x}% · Đang chờ {p} nối lại…"  # mới (spec PR-1 mục 2)
STALLED_DETAIL = "{x}% · Đang chờ dữ liệu…"  # mới (spec PR-1 mục 2), chiều nhận
STALLED_DETAIL_SEND = "{x}% · Đang chờ {p} phản hồi…"  # chiều gửi (soát PR-1: bên gửi không có VERIFYING)
P1_TOTAL = 1000 * MiB


def assert_no_speed_or_eta(detail: str) -> None:
    assert "/s" not in detail, detail
    assert "còn" not in detail, detail
    assert ETA_UNKNOWN not in detail, detail


@pytest.mark.parametrize("direction", ALL_DIRECTIONS)
def test_reconnecting_after_progress_shows_percent_and_waiting_sentence(view, direction):
    k = key(direction)
    view.set_connected(PEER_ID, True)
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 400 * MiB, P1_TOTAL, shown=420 * MiB))
    view.handle(status_changed(k, "reconnecting", done=400 * MiB, total=P1_TOTAL))
    detail = view.row(k).detail_label.text()
    assert detail == fill(RECONNECT_DETAIL, x="42,0", p=PEER), detail
    assert_no_speed_or_eta(detail)


def test_reconnecting_without_progress_shows_zero_percent(view):
    k = key("send")
    view.handle(status_changed(k, "reconnecting", total=P1_TOTAL))
    detail = view.row(k).detail_label.text()
    assert detail == fill(RECONNECT_DETAIL, x="0,0", p=PEER), detail


@pytest.mark.parametrize(("bps", "eta"), [(0.0, None), (3.5 * MiB, 120.0)])
def test_progress_while_reconnecting_keeps_waiting_sentence(view, bps, eta):
    """App phát `TransferProgress` mỗi nhịp khi RECONNECTING (tốc độ có thể còn > 0 trong cửa sổ đo):
    dòng phụ vẫn là câu chờ nối lại, % theo `shown_bytes` mới, không tốc độ, không ETA."""
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=100 * MiB))
    view.handle(status_changed(k, "reconnecting", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=bps, eta=eta, shown=250 * MiB, idle=3.0, status="reconnecting"))
    detail = view.row(k).detail_label.text()
    assert detail == fill(RECONNECT_DETAIL, x="25,0", p=PEER), detail
    assert_no_speed_or_eta(detail)


def test_stall_text_threshold_is_five_seconds():
    from teleport.ui import transfers_view

    assert transfers_view.STALL_TEXT_AFTER == 5.0


@pytest.mark.parametrize("direction", ALL_DIRECTIONS)
def test_transferring_idle_at_threshold_says_waiting_for_data(view, direction):
    from teleport.ui.transfers_view import STALL_TEXT_AFTER

    k = key(direction)
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=420 * MiB, idle=STALL_TEXT_AFTER))
    expected = fill(STALLED_DETAIL_SEND if direction == "send" else STALLED_DETAIL, x="42,0", p=PEER)
    detail = view.row(k).detail_label.text()
    assert detail == expected, detail
    assert_no_speed_or_eta(detail)
    # 9.6: câu dài vào accessibleName (không accessibleDescription); câu đứng yên vẫn phải tới trình đọc.
    assert expected in view.row(k).accessibleName()
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=420 * MiB, idle=STALL_TEXT_AFTER + 20))
    assert view.row(k).detail_label.text() == expected


def test_transferring_idle_below_threshold_keeps_progress_text(view):
    from teleport.core.display import format_size
    from teleport.ui.transfers_view import STALL_TEXT_AFTER

    k = key("send")
    bps = 85.2 * MiB
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=bps, eta=62.0, shown=420 * MiB, idle=STALL_TEXT_AFTER - 0.1))
    detail = view.row(k).detail_label.text()
    assert "Đang chờ" not in detail
    assert detail.startswith("42,0%"), detail
    assert f"{format_size(int(bps))}/s" in detail


def test_stalled_card_returns_to_progress_text_when_data_flows_again(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=420 * MiB, idle=9.0))
    assert "Đang chờ dữ liệu" in view.row(k).detail_label.text()
    assert "Đang chờ dữ liệu" in view.row(k).accessibleName()  # 9.6: tóm tắt ở accessibleName
    view.handle(progress(k, 0, P1_TOTAL, bps=5 * MiB, eta=100.0, shown=430 * MiB, idle=0.0))
    detail = view.row(k).detail_label.text()
    assert "Đang chờ dữ liệu" not in detail and "/s" in detail, detail
    # Trình đọc màn hình theo kịp lúc đổi loại câu (đứng yên → tốc độ). Mục 4: tên không theo nhịp tốc
    # độ, nên không còn đòi “/s” trong tên.
    assert "Đang chờ dữ liệu" not in view.row(k).accessibleName()


def test_send_stalled_while_receiver_verifies_says_waiting_for_peer(view):
    """Bên gửi không có VERIFYING: lúc máy nhận đọc lại file lớn, thẻ gửi nói đang chờ máy kia phản
    hồi, không “Đang chờ dữ liệu…” (máy gửi không chờ dữ liệu nào)."""
    k = key("send")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=P1_TOTAL - 1, idle=12.0))
    detail = view.row(k).detail_label.text()
    assert detail == fill(STALLED_DETAIL_SEND, x="99,9", p=PEER), detail
    assert "Đang chờ dữ liệu" not in detail


# ---- Câu tường lửa / lượt khôi phục không bị tiến độ đứng yên thay (soát PR-1) -----------------


def test_data_unreachable_survives_idle_reconnecting_progress(view):
    k = key("send")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=400 * MiB))
    view.handle(status_changed(k, "reconnecting", done=400 * MiB, total=P1_TOTAL))
    view.handle(data_unreachable())
    sentence = fill(DATA_UNREACHABLE, p=PEER)
    row = view.row(k)
    assert sentence in row.detail_label.text()
    for idle in (1.0, 2.0, 30.0):
        view.handle(
            progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=400 * MiB, idle=idle, status="reconnecting")
        )
        assert sentence in row.detail_label.text(), row.detail_label.text()
        assert row.status_label.text() == SHORT_RECONNECTING


def test_resumed_survives_idle_reconnecting_progress(view):
    k = key("receive")
    view.handle(resumed(k, done=300 * MiB, total=P1_TOTAL))
    row = view.row(k)
    before = (row.status_label.text(), row.detail_label.text())
    assert fill(WAIT_RESUMED, p=PEER) in before[1]
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=300 * MiB, idle=1.0, status="reconnecting"))
    assert (row.status_label.text(), row.detail_label.text()) == before


@pytest.mark.parametrize("status", ["reconnecting", "transferring"])
def test_unreachable_cleared_when_data_flows(view, status):
    k = key("send")
    view.handle(status_changed(k, "reconnecting", done=400 * MiB, total=P1_TOTAL))
    view.handle(data_unreachable())
    view.handle(progress(k, 0, P1_TOTAL, shown=410 * MiB, status=status))
    detail = view.row(k).detail_label.text()
    assert "Không mở được kết nối truyền dữ liệu" not in detail, detail
    assert detail.startswith("41,0%"), detail


def test_resumed_cleared_when_shown_grows(view):
    k = key("receive")
    view.handle(resumed(k, done=300 * MiB, total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=310 * MiB, status="reconnecting"))
    detail = view.row(k).detail_label.text()
    assert detail == fill(RECONNECT_DETAIL, x="31,0", p=PEER), detail


# ---- Thứ tự thật của engine: `DataUnreachable` trước `StatusChanged(RECONNECTING)` -----------
# `_finish` trả hành động, rồi báo cáo, rồi trạng thái (tests/core/test_transfer_data.py).


def _unreachable_in_real_order(view, k):
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=400 * MiB))
    view.handle(data_unreachable())
    view.handle(status_changed(k, "reconnecting", done=400 * MiB, total=P1_TOTAL))


def test_data_unreachable_survives_following_status_reconnecting(view):
    k = key("send")
    _unreachable_in_real_order(view, k)
    sentence = fill(DATA_UNREACHABLE, p=PEER)
    row = view.row(k)
    assert sentence in row.detail_label.text(), row.detail_label.text()
    assert row.status_label.text() == SHORT_RECONNECTING
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=400 * MiB, idle=2.0, status="reconnecting"))
    assert sentence in row.detail_label.text(), row.detail_label.text()


def test_data_unreachable_cleared_by_status_transferring(view):
    k = key("send")
    _unreachable_in_real_order(view, k)
    view.handle(status_changed(k, "transferring", done=400 * MiB, total=P1_TOTAL))
    assert "Không mở được kết nối truyền dữ liệu" not in view.row(k).detail_label.text()


def test_data_unreachable_cleared_by_growing_shown_after_real_order(view):
    k = key("send")
    _unreachable_in_real_order(view, k)
    view.handle(progress(k, 0, P1_TOTAL, shown=410 * MiB, status="reconnecting"))
    detail = view.row(k).detail_label.text()
    assert "Không mở được kết nối truyền dữ liệu" not in detail, detail
    assert detail.startswith("41,0%"), detail


@pytest.mark.parametrize("status", ["reconnecting", "waiting"])
def test_resumed_survives_status_reconnecting_or_waiting(view, status):
    k = key("receive")
    view.handle(resumed(k, done=300 * MiB, total=P1_TOTAL))
    view.handle(status_changed(k, status, done=300 * MiB, total=P1_TOTAL))
    assert fill(WAIT_RESUMED, p=PEER) in view.row(k).detail_label.text()


@pytest.mark.parametrize("status", ["transferring", "verifying"])
def test_resumed_cleared_by_status_transferring_or_verifying(view, status):
    k = key("receive")
    view.handle(resumed(k, done=300 * MiB, total=P1_TOTAL))
    view.handle(status_changed(k, status, done=300 * MiB, total=P1_TOTAL))
    assert fill(WAIT_RESUMED, p=PEER) not in view.row(k).detail_label.text()


def test_percent_and_bar_follow_shown_bytes_not_done_bytes(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=420 * MiB))
    row = view.row(k)
    assert row.progress_bar.value() == 420
    assert row.detail_label.text().startswith("42,0%"), row.detail_label.text()


def test_percent_from_shown_is_rounded_down_and_never_100_before_done(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=1_000_000))
    view.handle(progress(k, 0, 1_000_000, shown=999_999))
    row = view.row(k)
    assert row.progress_bar.value() == 999
    assert row.detail_label.text().startswith("99,9%"), row.detail_label.text()


def test_bar_never_goes_back_on_smaller_progress_or_status(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=500 * MiB))
    row = view.row(k)
    assert row.progress_bar.value() == 500
    view.handle(progress(k, 0, P1_TOTAL, shown=300 * MiB))
    assert row.progress_bar.value() == 500, "thanh lùi khi progress mới có shown nhỏ hơn"
    view.handle(status_changed(k, "transferring", done=100 * MiB, total=P1_TOTAL))
    assert row.progress_bar.value() == 500, "thanh lùi khi status mang done nhỏ hơn"
    view.handle(status_changed(k, "reconnecting", done=0, total=P1_TOTAL))
    assert row.progress_bar.value() == 500, "thanh lùi khi sang RECONNECTING"
    view.handle(status_changed(k, "verifying", done=200 * MiB, total=P1_TOTAL))
    assert row.progress_bar.value() == 500, "thanh lùi khi sang VERIFYING"


def test_status_uses_done_plus_unsynced_for_bar(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", done=600 * MiB, unsynced=100 * MiB, total=P1_TOTAL))
    assert view.row(k).progress_bar.value() == 700


def test_snapshot_and_resumed_use_done_plus_unsynced(view):
    a, b = key("receive"), key("receive", "d" * 32)
    view.load_snapshot([info(a, "transferring", done=300 * MiB, unsynced=50 * MiB, total=P1_TOTAL)])
    assert view.row(a).progress_bar.value() == 350
    view.handle(resumed(b, done=200 * MiB, unsynced=10 * MiB, total=P1_TOTAL))
    assert view.row(b).progress_bar.value() == 210


def test_done_after_stalled_progress_fills_bar(view):
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, bps=0.0, eta=None, shown=900 * MiB, idle=30.0))
    view.handle(finished(k, "done", status="verifying", done=P1_TOTAL, total=P1_TOTAL))
    row = view.row(k)
    assert row.progress_bar.value() == 1000
    assert DONE_DETAIL in row.detail_label.text()


def test_verifying_card_is_not_overwritten_by_progress(view):
    """VERIFYING giữ câu “Đang kiểm tra” dù có `TransferProgress` (trạng thái VERIFYING) tới sau: app
    phát khi `shown_bytes` còn đổi lúc đang kiểm tra (lô sync cuối của file)."""
    k = key("receive")
    view.handle(status_changed(k, "transferring", total=P1_TOTAL))
    view.handle(progress(k, 0, P1_TOTAL, shown=990 * MiB))
    view.handle(status_changed(k, "verifying", done=P1_TOTAL, total=P1_TOTAL))
    row = view.row(k)
    before = (row.status_label.text(), row.detail_label.text())
    assert SHORT_VERIFYING.lower() in " ".join(before).lower(), before
    view.handle(
        progress(k, P1_TOTAL, P1_TOTAL, bps=7 * MiB, eta=1.0, shown=P1_TOTAL, idle=0.0, status="verifying")
    )
    after = (row.status_label.text(), row.detail_label.text())
    assert after == before, f"progress ghi đè thẻ đang kiểm tra: {before} → {after}"
    assert "/s" not in after[1]


def test_new_sentences_are_in_mvp_doc():
    doc = _MVP.read_text(encoding="utf-8")
    # mvp viết chỗ thay bằng ví dụ in nghiêng: {x} → *45,0*, {p} → *PC-Nha*.
    for sample in (RECONNECT_DETAIL, STALLED_DETAIL, STALLED_DETAIL_SEND):
        written = sample.replace("{x}", "*45,0*").replace("{p}", "*PC-Nha*")
        assert written in doc, f"mvp.md mục 8 thiếu câu {written!r}"


# =================================================================================================
# V1 (spec B1 mục 2.5, 6 V1, 12.10, 12.11): `content_changed`, `has_content`, `active_count`
# =================================================================================================


@pytest.fixture
def bare(qtbot):
    """`ChatView` chưa chọn máy: 9.15 `has_content()` = thông báo đang hiện hoặc đang chọn một máy."""
    from teleport.ui.chat import ChatView
    from teleport.ui.radar import DeviceListModel

    v = ChatView(DeviceListModel())
    qtbot.addWidget(v)
    v.set_device_names({PEER_ID: PEER})
    v.show()
    return v


@pytest.fixture
def changes(bare):
    """Số lần `content_changed` đã phát (đếm từ lúc dựng fixture)."""
    seen: list[int] = []
    bare.content_changed.connect(lambda: seen.append(1))
    return seen


def _snapshot_infos():
    return [info(key("send", "1" * 32), "transferring"), info(key("receive", "2" * 32), "waiting")]


def test_v1_empty_view_has_no_content(bare):
    assert bare.has_content() is False
    assert bare.active_count() == 0


def test_v1_selected_device_counts_as_content(view):
    # 9.15: đang chọn một máy là có nội dung (để “Ghép đôi máy đầu tiên” chỉ hiện khi cột trái trống).
    assert view.has_content() is True
    view.set_device(None)
    assert view.has_content() is False


# (tên, thao tác trên view rỗng chưa chọn máy, has_content sau đó, active_count sau đó).
# 9.15: bong bóng không tính là nội dung (chỉ thông báo đang hiện hay máy đang chọn).
V1_FROM_EMPTY = [
    ("status_changed tạo thẻ", lambda v: v.handle(status_changed(key("send"), "transferring")), False, 1),
    ("offer tạo thẻ nhận", lambda v: v.handle(offer_received(key("receive"))), False, 1),
    ("progress tạo thẻ", lambda v: v.handle(progress(key("send"), 10, 1000)), False, 1),
    (
        "finished tạo thẻ đã kết thúc",
        lambda v: v.handle(finished(key("send"), "done", status="verifying")),
        False,
        0,
    ),
    ("show_notice", lambda v: v.show_notice("Một thông báo."), True, 0),
    ("hide_notice", lambda v: v.hide_notice(), False, 0),
    ("clear", lambda v: v.clear(), False, 0),
    ("load_snapshot", lambda v: v.load_snapshot(_snapshot_infos()), False, 2),
]


@pytest.mark.parametrize(
    ("what", "action", "content", "active"), V1_FROM_EMPTY, ids=[c[0] for c in V1_FROM_EMPTY]
)
def test_v1_each_public_call_emits_content_changed_once(bare, changes, what, action, content, active):
    action(bare)
    assert len(changes) == 1, f"{what}: content_changed phát {len(changes)} lần"
    assert bare.has_content() is content
    assert bare.active_count() == active


def test_v1_card_finishing_emits_once_and_lowers_active_count(bare, changes):
    view = bare
    a, b = key("send", "a" * 32), key("receive", "b" * 32)
    view.handle(status_changed(a, "transferring"))
    view.handle(status_changed(b, "transferring"))
    assert (len(changes), view.active_count()) == (2, 2)
    view.handle(finished(a, "done", status="verifying"))
    assert len(changes) == 3
    assert view.active_count() == 1
    view.handle(finished(b, "cancelled_user"))
    assert len(changes) == 4
    assert view.active_count() == 0


def test_v1_suspended_does_not_lower_active_count(bare, changes):
    view = bare
    k = key("receive")
    view.handle(status_changed(k, "transferring"))
    view.handle(finished(k, "suspended"))
    assert view.active_count() == 1
    assert view.row(k) is not None and view.row(k).finished is False


def test_v1_notice_close_button_emits_once(bare, changes):
    view = bare
    view.show_notice("Một thông báo.", "Làm gì đó", lambda: None)
    assert len(changes) == 1
    view.info_bar.close_button.click()  # 9.7: `notice_close` bỏ, nút Đóng của `InfoBar`
    assert len(changes) == 2
    assert view.has_content() is False


def test_v1_clear_with_rows_and_notice_emits_once(bare, changes):
    view = bare
    view.handle(status_changed(key("send", "a" * 32), "transferring"))
    view.handle(status_changed(key("send", "b" * 32), "transferring"))
    view.show_notice("Một thông báo.")
    before = len(changes)
    view.clear()
    assert len(changes) == before + 1
    assert view.has_content() is False
    assert view.active_count() == 0


def test_v1_load_snapshot_with_many_rows_emits_once(bare, changes):
    view = bare
    infos = [info(key("send", c * 32), "transferring") for c in "abcde"]
    view.load_snapshot(infos)
    assert len(changes) == 1
    assert view.active_count() == 5


def test_v1_remove_emits_once_and_updates_counts(bare, changes):
    view = bare
    a, b = key("send", "a" * 32), key("send", "b" * 32)
    view.handle(status_changed(a, "transferring"))
    view.handle(status_changed(b, "transferring"))
    before = len(changes)
    view.remove(a)
    assert len(changes) == before + 1
    assert view.active_count() == 1
    view.remove(b)
    assert view.has_content() is False
    assert view.active_count() == 0


def test_v1_has_content_counts_notice_while_view_hidden(bare):
    view = bare
    # 12.11: cửa sổ ẩn xuống khay thì dải thông báo vẫn tính là nội dung.
    view.hide()
    view.show_notice("Một thông báo.")
    assert view.has_content() is True
    view.hide_notice()
    assert view.has_content() is False
