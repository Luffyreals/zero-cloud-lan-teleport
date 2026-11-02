"""Chụp ảnh các màn chính ở sáng/tối, 980x660 và 720x460 (spec A3 mục 2.6, S1; spec B1 mục 7).

Trên CI (offscreen) đây là kiểm tra khói: dựng được mọi cảnh ở cả hai chế độ, ảnh đúng cỡ, cửa sổ
không phình quá cỡ đã đặt, ảnh sáng khác ảnh tối, và điểm (4,4) của cảnh có token góc đúng màu token
đó ở chế độ đó (`surface` cho khối căn giữa và trang, `sidebar` cho khung hai cột vì cột trái nằm ở
góc).

Ảnh để duyệt: đặt `TELEPORT_UI_SNAPSHOT_DIR` thì mỗi cảnh ghi
`<cảnh>_<light|dark>_<w>x<h>.png` vào thư mục đó (tạo nếu chưa có); không đặt thì không ghi gì. Chụp
bằng nền thật của Windows để font và hinting giống thật (conftest chỉ `setdefault` nền offscreen,
nên biến môi trường thắng)::

    $env:QT_QPA_PLATFORM="windows"; $env:TELEPORT_UI_SNAPSHOT_DIR="<thư mục ngoài repo>"
    pytest tests/ui/test_snapshots.py

Ngôn ngữ: mặc định chuỗi nguồn tiếng Việt; đặt `TELEPORT_SNAPSHOT_LANG` (ví dụ `en`) thì mọi cảnh
dựng sau khi `i18n.set_language(<mã>)` (phải có `teleport_<mã>.qm`), để soát chữ dài có tràn không.
Nên ghi ảnh mỗi ngôn ngữ vào một thư mục riêng vì tên file không có mã ngôn ngữ.

Ảnh không commit vào repo: đính vào PR. Các PR của đợt B thêm cảnh của mình vào `SCENES`.

Cảnh: `welcome` (màn lần chạy đầu, có công tắc khởi động cùng Windows; spec D1),
`welcome_no_autostart` (hệ điều hành không hỗ trợ: không có hàng công tắc), `welcome_name_error` (gợi
ý rỗng, bấm “Bắt đầu”: lỗi dưới ô tên), `welcome_dir_error` (thư mục đã chọn không dùng được),
`starting`, `running` (một địa chỉ, chưa có máy đã ghép đôi → “Ghép đôi máy đầu tiên”),
`running_full` (ba thiết bị, thẻ đang gửi, thẻ đã nhận xong, một thông báo),
`running_unavailable` (thư mục nhận đã lưu không mở được, spec B1b), `error`, `widgets` (trang
mẫu mọi thành phần của `ui/widgets.py` trong `QScrollArea`, kể cả `SegmentedControl` của spec D6),
`page` (RUNNING, mở một trang mẫu có
`PageHeader` ở chỗ SETTINGS, vì DISCOVER đã là trang thật), `discover` (trang “Tìm máy mới”: 4 máy
chưa ghép đôi, một tên dài bị cắt “…”, 2 máy đã ghép đôi), `discover_list` (9 máy: tự sang dạng danh
sách), `discover_list_empty` (spec G6: không máy nào, dạng danh sách chọn sẵn: minh họa “không thấy
máy” trên câu rỗng), `conversations` (spec B2 mục 7: 4 máy đã ghép đôi ở cột trái — đang gửi 62% và đang chọn,
trực tuyến đã nhận một file, ngoại tuyến đã gửi hôm qua, trực tuyến bị từ chối kết nối — và luồng
của PC-Nha có bong bóng đang gửi ở khung phải), `conversations_drop` (như trên, đang kéo 3 file qua
hàng đang chọn).

Trang “Cài đặt” (spec D2): `settings_general`, `settings_appearance` (spec D6: chế độ Tối, màu Đại
dương chọn sẵn; ảnh sáng và tối dựng bằng `ui_theme` nên chỉ thấy lựa chọn, không thấy màu đại
dương), `settings_privacy_hidden` (máy đang ẩn),
`settings_devices` (bốn máy đã ghép đôi: đã kết nối, trong mạng, ngoại tuyến, tên lạ dài; một máy
chưa ghép đôi không hiện), `settings_devices_empty` (spec G6: chưa ghép đôi máy nào, minh họa
“chưa ghép máy”), `settings_advanced` (kèm thông báo xuất log xong),
`settings_receive_dir_unavailable` (thư mục nhận đã lưu không mở được).

Luồng chat (spec B3, `ui.chat`): `chat` (luồng của PC-Nha: nhận xong “Đã lưu” + “Hiện trong thư mục”, gửi lỗi
viền đỏ + “Gửi lại”, đang gửi 62%, bong bóng tạm “Đang chuẩn bị…”, dòng mốc), `chat_new` (cuộn lên
rồi có lượt mới: nút “↓ Mới”), `chat_drop` (đang kéo 3 file vào luồng), `chat_offline` (máy ngoại
tuyến: lượt chờ kết nối, câu ngoại tuyến ở thanh dưới), `chat_history` (lịch sử hai ngày trước, hôm
qua và lượt của phiên hôm nay), `chat_empty` (máy chưa có lượt nào: màn rỗng “Kéo file vào đây…”).

Lời mời nhận file và hộp mã (spec B4): `offer_box` (hộp hỏi nhận 3 file từ PC-Nha: “Đổi…”, ô “Luôn
nhận”, Từ chối / Nhận), `chat_offer` (luồng của PC-Nha có bong bóng lời mời đang chờ với panel Nhận /
Từ chối, viền nhấn, không có ✕), `pairing_countdown` (hộp mã ghép đôi còn 8 giây: mã vẽ thành hai
nhóm ô, thanh đếm ngược ngắn, chữ màu cảnh báo). Hai hộp được nhúng (cờ `Qt.Widget`) giữa một nền
`surface` cỡ cảnh để ảnh dễ duyệt; không kiểm góc.

Giờ cố định bằng seam `_wall_now` của `ui.conversations`, `ui.transfers` (`NOW`) và `ui.chat` (cảnh
luồng chat đổi giờ giữa các bong bóng qua `_CLOCK`). Tổng 32 cảnh × 2 chế độ × 2 cỡ = 128 ảnh.
"""

from __future__ import annotations

import datetime
import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget

pytestmark = pytest.mark.slow

SIZES = ((980, 660), (720, 460))
SNAPSHOT_ENV = "TELEPORT_UI_SNAPSHOT_DIR"
LANG_ENV = "TELEPORT_SNAPSHOT_LANG"
NOW = datetime.datetime(2026, 10, 31, 10, 45).timestamp()  # giờ địa phương cố định của các cảnh
_CLOCK = [NOW]  # giờ tường của `ui.chat` (cảnh luồng chat đổi giữa các bong bóng)
RECEIVE_DIR = Path("C:/Users/Minh/Downloads/Teleport")


@pytest.fixture(scope="module", autouse=True)
def accent_font(qapp):
    """Nạp font điểm nhấn như `ui.app` (trước khi dựng cửa sổ); gỡ lại nếu trước đó chưa nạp."""
    from teleport.ui import fonts

    was_installed = fonts._installed
    fonts.install()
    yield
    if not was_installed:
        fonts._reset()


@pytest.fixture(autouse=True)
def fixed_clock(monkeypatch):
    """Giờ tường cố định (`NOW`) cho chữ giờ của danh sách cuộc trò chuyện."""
    from teleport.ui import chat, conversations, transfers

    _CLOCK[0] = NOW
    monkeypatch.setattr(conversations, "_wall_now", lambda: NOW)
    monkeypatch.setattr(transfers, "_wall_now", lambda: NOW)
    monkeypatch.setattr(chat, "_wall_now", lambda: _CLOCK[0])


# ---- Cảnh --------------------------------------------------------------------------------------


def _main_window(qtbot):
    from teleport.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def scene_welcome(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_welcome("Laptop-Minh", RECEIVE_DIR, autostart=True)
    return window


def scene_welcome_no_autostart(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_welcome("Laptop-Minh", RECEIVE_DIR, autostart=None)
    return window


def scene_welcome_name_error(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_welcome("", RECEIVE_DIR, autostart=True)
    assert window.first_run.validate() is None  # gợi ý rỗng: “Hãy nhập tên thiết bị.” dưới ô
    return window


def scene_welcome_dir_error(qtbot) -> QWidget:
    from teleport.ui.receive_dir import ChangeError, change_error_text

    chosen = Path("E:/Ổ-USB/Teleport-nhận-file-từ-máy-khác")
    window = _main_window(qtbot)
    window.show_welcome(
        "Laptop-Minh",
        RECEIVE_DIR,
        autostart=True,
        choice=_first_run_choice(chosen),
        dir_error=change_error_text(ChangeError.UNAVAILABLE, chosen),
    )
    return window


def _first_run_choice(receive_dir: Path):
    from teleport.ui.first_run import FirstRunChoice

    return FirstRunChoice(
        name_text="Laptop-Minh", name=None, receive_dir=receive_dir, receive_dir_chosen=True, autostart=True
    )


def scene_starting(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_starting()
    return window


def scene_running(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_running("Laptop-Minh", Path("C:/Users/Minh/Downloads/Teleport"))
    window.set_addresses(["192.168.1.15"], None)
    return window


def _device(label: str, *, paired: bool, online: bool, connected: bool):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=hashlib.sha256(label.encode()).hexdigest()[:32],
        name=label,
        os="windows" if online else None,
        paired=paired,
        online=online,
        connected=connected,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def _chat_view(window):
    """`ChatView` đặt vào khung phải như `TransfersController` (lề 0), chưa nối node."""
    from teleport.ui.chat import ChatView

    view = ChatView(window.devices, window.transfers_area)
    layout = window.transfers_area.layout()
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(view)
    view.content_changed.connect(lambda: window.set_transfer_summary(view.has_content(), view.active_count()))
    return view


def _transfer_info(
    device_id: str, direction: str, transfer_id: str, status: str, name: str, size: int, done: int
):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import Direction, TransferInfo, TransferKey, TransferStatus

    return TransferInfo(
        key=TransferKey(device_id, Direction(direction), transfer_id),
        status=TransferStatus(status),
        files=(FileEntry(name, size, 1_700_000_000_000),),
        names=(name,),
        file_index=0,
        done_bytes=done,
        total_bytes=size,
        unsynced_bytes=0,
    )


def scene_running_full(qtbot) -> QWidget:
    """RUNNING đầy đủ: ba thiết bị, thẻ đang gửi, thẻ đã nhận xong, một thông báo (spec B1 mục 7)."""
    from teleport.app.transfers import (
        FileDone,
        TransferFinished,
        TransferProgress,
        TransferResult,
        TransferStatusChanged,
    )

    window = _main_window(qtbot)
    nha = _device("PC-Nha", paired=True, online=True, connected=True)
    lan = _device("MacBook-Lan", paired=True, online=False, connected=False)
    guest = _device("PC-Khach", paired=False, online=True, connected=False)
    window.devices.reset([nha, lan, guest])

    view = _chat_view(window)
    window.conversations.select_device(nha.device_id)
    view.set_device(nha.device_id)
    view.set_device_names({nha.device_id: nha.name, lan.device_id: lan.name})
    size = 18 * 2**30
    sending = _transfer_info(
        nha.device_id, "send", "a" * 32, "transferring", "phim-4k.mkv", size, size * 62 // 100
    )
    view.handle(TransferStatusChanged(sending))
    view.handle(TransferProgress(sending, 94 * 2**20, 60.0, shown_bytes=sending.done_bytes, idle_seconds=0.0))
    small = 340 * 2**20
    received = _transfer_info(lan.device_id, "receive", "b" * 32, "verifying", "anh-cuoi.zip", small, small)
    view.handle(TransferStatusChanged(received))
    folder = Path("C:/Users/Minh/Downloads/Teleport")
    view.handle(FileDone(received.key, 0, "anh-cuoi.zip", folder / "anh-cuoi.zip"))
    view.handle(
        TransferFinished(
            info=received, result=TransferResult.DONE, by_peer=False, reason=None, file_index=0, reject=None
        )
    )
    view.show_notice("Đã ghép đôi với PC-Nha.")
    window.set_transfer_summary(view.has_content(), view.active_count())

    window.show_running("Laptop-Minh", folder)
    window.set_addresses(["192.168.1.15"], None)
    return window


def scene_running_unavailable(qtbot) -> QWidget:
    """RUNNING mà thư mục nhận đã lưu không mở được (spec B1b): huy hiệu “Không nhận file”, chân “Lưu
    vào” báo warning kèm “Đổi…”, dải thông báo có nút “Chọn thư mục nhận”."""
    from teleport.ui import receive_dir

    window = _main_window(qtbot)
    view = _chat_view(window)
    missing = Path("E:/Teleport")
    view.show_notice(receive_dir.unavailable_text(missing), receive_dir.choose_action_text(), lambda: None)
    window.set_transfer_summary(view.has_content(), view.active_count())
    window.show_running("Laptop-Minh", None, missing)
    window.set_addresses(["192.168.1.15"], None)
    return window


def scene_error(qtbot) -> QWidget:
    window = _main_window(qtbot)
    window.show_error("port", "[WinError 10048] Only one usage of each socket address")
    return window


def _sample_bubble(direction, emphasis, file_name: str, progress: int | None):
    from PySide6.QtWidgets import QHBoxLayout, QLabel, QProgressBar

    from teleport.ui import widgets

    bubble = widgets.ChatBubble(direction, emphasis=emphasis)
    head = QHBoxLayout()
    name = QLabel(file_name)
    name.setTextFormat(Qt.TextFormat.PlainText)
    head.addWidget(name, 1)
    head.addWidget(widgets.IconButton("pause", "Tạm dừng"))
    head.addWidget(widgets.IconButton("dismiss", "Hủy"))
    bubble.body().addLayout(head)
    if progress is not None:
        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(progress)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        bubble.body().addWidget(bar)
    detail = QLabel(f"18 GB · {progress}%" if progress is not None else "18 GB")
    detail.setTextFormat(Qt.TextFormat.PlainText)
    detail.setProperty("tone", "muted")
    bubble.body().addWidget(detail)
    bubble.set_summary(file_name)
    return widgets.BubbleRow(bubble)


def scene_widgets(qtbot) -> QWidget:
    from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout

    from teleport.ui import widgets

    area = QScrollArea()
    qtbot.addWidget(area)
    area.setWidgetResizable(True)
    page = QWidget()
    page.setObjectName("snapshotWidgets")
    column = QVBoxLayout(page)
    column.setContentsMargins(0, 0, 0, 16)
    column.setSpacing(12)
    column.addWidget(widgets.PageHeader("Thành phần dùng chung"))

    # Hai cột để một khung hình thấy được nhiều thành phần: trái InfoBar + EmptyState, phải avatar,
    # badge và bong bóng.
    inner = QHBoxLayout()
    inner.setContentsMargins(16, 0, 16, 0)
    inner.setSpacing(16)
    left = QVBoxLayout()
    left.setSpacing(12)
    right = QVBoxLayout()
    right.setSpacing(12)
    levels = (
        (widgets.InfoLevel.INFO, "Đã ghép đôi với PC-Nha", "", None),
        (widgets.InfoLevel.SUCCESS, "Đã nhận anh-cuoi.zip", "Lưu vào Downloads\\Teleport", "Mở thư mục"),
        (widgets.InfoLevel.WARNING, "Mạng chặn tìm máy", "Nhập IP thủ công để ghép đôi.", "Nhập IP"),
        (
            widgets.InfoLevel.ERROR,
            "Không mở được cổng 47474",
            "Một ứng dụng khác đang dùng cổng này.",
            "Thử lại",
        ),
    )
    for level, title, text, action in levels:
        bar = widgets.InfoBar()
        left.addWidget(bar)  # có cha trước, để show_message không mở cửa sổ riêng
        bar.show_message(level, title, text, action=action)

    right.addWidget(_sample_bubble(widgets.Direction.OUT, widgets.BubbleEmphasis.NONE, "phim-4k.mkv", 62))
    right.addWidget(_sample_bubble(widgets.Direction.IN, widgets.BubbleEmphasis.NONE, "anh-cuoi.zip", None))
    right.addWidget(
        _sample_bubble(widgets.Direction.IN, widgets.BubbleEmphasis.ATTENTION, "slide.pptx", None)
    )
    right.addWidget(_sample_bubble(widgets.Direction.OUT, widgets.BubbleEmphasis.DANGER, "bao-cao.pdf", 30))

    avatars = QHBoxLayout()
    avatars.setSpacing(16)
    for presence in widgets.Presence:
        avatar = widgets.DeviceAvatar(presence=presence)
        avatar.set_label(str(presence))
        avatars.addWidget(avatar)
    avatars.addWidget(
        widgets.DeviceAvatar(
            diameter=44, kind=widgets.AvatarKind.LAPTOP, presence=widgets.Presence.ONLINE, emphasis=True
        )
    )
    avatars.addStretch(1)
    right.insertLayout(0, avatars)

    badges = QGridLayout()  # 2x2: một hàng bốn badge làm cột phải tràn ngang ở 720x460
    badges.setHorizontalSpacing(16)
    badges.setVerticalSpacing(8)
    samples = (
        (widgets.BadgeTone.SUCCESS, "Sẵn sàng nhận"),
        (widgets.BadgeTone.BUSY, "Đang truyền"),
        (widgets.BadgeTone.WARNING, "Tạm dừng"),
        (widgets.BadgeTone.MUTED, "Đang ẩn"),
    )
    for index, (tone, text) in enumerate(samples):
        badge = widgets.StatusBadge()
        badges.addWidget(badge, index // 2, index % 2)  # có cha trước, như InfoBar
        badge.set_status(tone, text)
    badges.setColumnStretch(2, 1)
    right.insertLayout(1, badges)
    segmented = widgets.SegmentedControl(("system", "light", "dark"))
    segmented.set_texts(("Theo hệ điều hành", "Sáng", "Tối"))
    segmented.set_value("light")
    segmented_row = QHBoxLayout()
    segmented_row.addWidget(segmented)
    segmented_row.addStretch(1)
    right.insertLayout(2, segmented_row)
    right.addStretch(1)

    empty = widgets.EmptyState()
    empty.set_content(
        "desktop",
        "Ghép đôi máy đầu tiên",
        "Mở Teleport trên máy kia, rồi bấm Tìm máy mới để thấy nó ở đây.",
        action="Tìm máy mới",
    )
    empty.setMinimumHeight(240)
    left.addWidget(empty)
    left.addStretch(1)
    inner.addLayout(left, 1)
    inner.addLayout(right, 1)
    column.addLayout(inner)
    area.setWidget(page)
    return area


def scene_page(qtbot) -> QWidget:
    from PySide6.QtWidgets import QLineEdit, QVBoxLayout

    from teleport.ui import widgets
    from teleport.ui.main_window import Page

    window = scene_running(qtbot)
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 0, 0, 0)
    header = widgets.PageHeader("Tìm máy mới")
    address = QLineEdit()
    address.setPlaceholderText("Nhập IP…")
    address.setFixedWidth(180)
    header.add_trailing(address)
    layout.addWidget(header)
    empty = widgets.EmptyState()
    empty.set_content("search", "Chưa thấy máy nào", "Mở Teleport trên máy kia, cùng mạng Wi-Fi hoặc dây.")
    layout.addWidget(empty, 1)
    page.setFocusProxy(header.back_button)
    window.add_page(Page.SETTINGS, page)
    assert window.open_page(Page.SETTINGS)
    return window


def _peer(name: str, *, paired: bool = False, connected: bool = False, os_name: str | None = "windows"):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id="id-" + name.lower().replace(" ", "-"),
        name=name,
        os=os_name,
        paired=paired,
        online=True,
        connected=connected,
        addresses=("192.168.1.20",),
        port=None,
    )


def _discover_window(qtbot, views) -> QWidget:
    from teleport.ui.main_window import Page

    window = scene_running(qtbot)
    window.devices.reset(views)
    assert window.open_page(Page.DISCOVER)
    return window


def scene_discover(qtbot) -> QWidget:
    views = [
        _peer("Laptop-Lan"),
        _peer("PC-Phong-Khach"),
        _peer("MacBook của Hà", os_name="macos"),
        _peer("May-Ke-Toan-Tang-3-Phong-Hop-Lon"),  # tên dài: cắt “…”
        _peer("PC-Nha", paired=True, connected=True),
        _peer("Surface-Minh", paired=True),
    ]
    return _discover_window(qtbot, views)


def scene_discover_list(qtbot) -> QWidget:
    names = (
        "Laptop-Lan",
        "PC-Phong-Khach",
        "MacBook của Hà",
        "Ubuntu-Lab",
        "Laptop-Tuan",
        "PC-Le-Tan",
        "Mini-PC",
    )
    views = [_peer(name, os_name="linux" if name == "Ubuntu-Lab" else "windows") for name in names]
    views += [_peer("PC-Nha", paired=True, connected=True), _peer("Surface-Minh", paired=True)]
    return _discover_window(qtbot, views)


def scene_discover_list_empty(qtbot) -> QWidget:
    """Spec G6: trang “Tìm máy mới” không có máy nào, dạng danh sách: minh họa NO_DEVICES trên câu rỗng."""
    window = _discover_window(qtbot, [])
    window.discover.set_view_preference("list")
    return window


def _at(day: int, hour: int, minute: int) -> float:
    return datetime.datetime(2026, 10, day, hour, minute).timestamp()


def scene_conversations(qtbot) -> QWidget:
    """Spec B2 mục 7: bốn máy đã ghép đôi ở cột trái, PC-Nha đang gửi 62% và đang được chọn."""
    from teleport.app.devices import DeviceView
    from teleport.app.node import ConnectFailed
    from teleport.app.transfers import (
        Direction,
        TransferProgress,
        TransferResult,
        TransferStatus,
        TransferStatusChanged,
    )
    from teleport.core.links import ConnectResult
    from teleport.ui.activity import ActiveTransfer, DeviceActivity, FinishedTransfer

    def paired(label: str, os_name: str, *, online: bool, connected: bool = False) -> DeviceView:
        return DeviceView(
            device_id=hashlib.sha256(label.encode()).hexdigest()[:32],
            name=label,
            os=os_name,
            paired=True,
            online=online,
            connected=connected,
            addresses=("192.168.1.20",) if online else (),
            port=47474 if online else None,
        )

    window = _main_window(qtbot)
    nha = paired("PC-Nha", "windows", online=True, connected=True)
    lan = paired("MacBook-Lan", "macos", online=True)
    lab = paired("Ubuntu-Lab", "linux", online=False)
    old = paired("May-Cu", "windows", online=True)
    window.devices.reset([nha, lan, lab, old])
    window.devices.apply(ConnectFailed(device=old, result=ConnectResult.REJECTED))

    size = 18 * 2**30
    sending = _transfer_info(
        nha.device_id, "send", "a" * 32, "transferring", "phim-4k.mkv", size, size * 62 // 100
    )
    model = window.conversations.model
    model.set_activity(
        nha.device_id,
        DeviceActivity(
            active=(
                ActiveTransfer(
                    key=sending.key,
                    status=TransferStatus.TRANSFERRING,
                    file_count=1,
                    first_name="phim-4k.mkv",
                    shown_bytes=sending.done_bytes,
                    total_bytes=size,
                    started_at=_at(31, 10, 42),
                ),
            ),
            last=None,
        ),
    )
    model.set_activity(
        lan.device_id,
        DeviceActivity(
            active=(),
            last=FinishedTransfer(Direction.RECEIVE, TransferResult.DONE, 1, "bao-cao.pdf", _at(31, 9, 15)),
        ),
    )
    model.set_activity(
        lab.device_id,
        DeviceActivity(
            active=(),
            last=FinishedTransfer(Direction.SEND, TransferResult.DONE, 3, "slide.pptx", _at(30, 16, 30)),
        ),
    )
    window.conversations.select_device(nha.device_id)

    view = _chat_view(window)
    view.set_device(nha.device_id)
    view.set_device_names({d.device_id: d.name for d in (nha, lan, lab, old)})
    view.handle(TransferStatusChanged(sending))
    view.handle(TransferProgress(sending, 94 * 2**20, 60.0, shown_bytes=sending.done_bytes, idle_seconds=0.0))
    window.set_transfer_summary(view.has_content(), view.active_count())

    window.show_running("Laptop-Minh", RECEIVE_DIR)
    window.set_addresses(["192.168.1.15"], None)
    return window


def scene_conversations_drop(qtbot) -> QWidget:
    """Như `conversations`, đang kéo 3 file qua hàng đang chọn (PC-Nha): viền nét đứt, câu thả."""
    window = scene_conversations(qtbot)
    nha_id = hashlib.sha256(b"PC-Nha").hexdigest()[:32]
    window.conversations.list_view.preview_drop(nha_id, 3)
    return window


def _settings_window(
    qtbot, section, *, visible: bool = True, views=(), notice: str | None = None, unavailable: bool = False
):
    """RUNNING, trang “Cài đặt” (spec D2) đã có ảnh chụp cài đặt, mở ở mục `section`."""
    from teleport.app import autostart
    from teleport.app.settings import DeviceSettings
    from teleport.ui.main_window import Page
    from teleport.ui.settings import SettingsPage, SettingsSnapshot
    from teleport.ui.widgets import InfoLevel

    window = scene_running(qtbot)
    window.devices.reset(list(views))
    page = SettingsPage(window.devices, window.pages)
    window.add_page(Page.SETTINGS, page)
    page.header.back_requested.connect(window.go_back)
    devices = {v.device_id: DeviceSettings(ask_before_receive=i % 2 == 0) for i, v in enumerate(views)}
    page.set_values(
        SettingsSnapshot(
            name="Laptop-Minh",
            visible=visible,
            rate_limit=20 * 1024 * 1024,
            temp_retention_days=None,
            language=None,
            autostart=True,
            devices=devices,
        )
    )
    page.set_autostart(autostart.AutostartState.ON)
    if unavailable:
        page.set_receive_dir(None, Path("E:/Teleport-USB"))
    else:
        page.set_receive_dir(Path("C:/Users/Minh/Downloads/Teleport"))
    page.set_change_available(True)
    page.set_loaded(True)
    assert window.open_page(Page.SETTINGS)
    page.show_section(section)
    if notice is not None:
        page.show_notice(InfoLevel.SUCCESS, notice, action="Mở thư mục")
    return window


def scene_settings_general(qtbot) -> QWidget:
    from teleport.ui.settings import Section

    return _settings_window(qtbot, Section.GENERAL)


def scene_settings_appearance(qtbot) -> QWidget:
    from teleport.ui.settings import Section

    window = _settings_window(qtbot, Section.APPEARANCE)
    page = window.pages.currentWidget()
    page.set_theme("dark")
    page.set_accent("ocean")
    return window


def scene_settings_privacy_hidden(qtbot) -> QWidget:
    from teleport.ui.settings import Section

    return _settings_window(qtbot, Section.PRIVACY, visible=False)


def scene_settings_devices(qtbot) -> QWidget:
    from dataclasses import replace

    from teleport.ui.settings import Section

    views = [
        _peer("PC-Nha", paired=True, connected=True),
        _peer("MacBook của Hà", paired=True, os_name="macos"),
        replace(_peer("Ubuntu-Lab", paired=True, os_name="linux"), online=False, addresses=()),
        _peer("<b>May-Ke-Toan-Tang-3-Phong-Hop-Lon</b>", paired=True),  # tên lạ: chữ thuần, cắt “…”
        _peer("Laptop-Lan"),  # chưa ghép đôi: không hiện
    ]
    return _settings_window(qtbot, Section.DEVICES, views=views)


def scene_settings_devices_empty(qtbot) -> QWidget:
    """Spec G6: chưa ghép đôi máy nào (một máy lạ trong mạng không tính): `trustedEmpty` có minh họa."""
    from teleport.ui.settings import Section

    return _settings_window(qtbot, Section.DEVICES, views=[_peer("Laptop-Lan")])


def scene_settings_advanced(qtbot) -> QWidget:
    from teleport.ui.settings import Section

    return _settings_window(
        qtbot,
        Section.ADVANCED,
        notice="Đã lưu log vào C:\\Users\\Minh\\Documents\\teleport-log-20261031-101500.zip.",
    )


def scene_settings_receive_dir_unavailable(qtbot) -> QWidget:
    from teleport.ui.receive_dir import ChangeError, change_error_text
    from teleport.ui.settings import Section
    from teleport.ui.widgets import InfoLevel

    window = _settings_window(qtbot, Section.GENERAL, unavailable=True)
    text = change_error_text(ChangeError.UNAVAILABLE, Path("E:/Teleport-USB"))
    window.pages.currentWidget().show_notice(InfoLevel.ERROR, text)
    return window


def _paired(label: str, os_name: str, *, online: bool, connected: bool = False):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=hashlib.sha256(label.encode()).hexdigest()[:32],
        name=label,
        os=os_name,
        paired=True,
        online=online,
        connected=connected,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def _finished(info, result: str, **kw):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=info,
        result=TransferResult(result),
        by_peer=kw.get("by_peer", False),
        reason=None,
        file_index=kw.get("file_index", 0),
        reject=None,
    )


def _chat_window(qtbot, *, nha_online: bool = True):
    """Cửa sổ RUNNING có hai máy đã ghép đôi, PC-Nha đang chọn; trả (cửa sổ, luồng chat, PC-Nha)."""
    window = _main_window(qtbot)
    nha = _paired("PC-Nha", "windows", online=nha_online, connected=nha_online)
    lan = _paired("MacBook-Lan", "macos", online=True)
    window.devices.reset([nha, lan])
    view = _chat_view(window)
    view.set_device_names({nha.device_id: nha.name, lan.device_id: lan.name})
    view.set_receive_dir(RECEIVE_DIR)
    window.conversations.select_device(nha.device_id)
    view.set_device(nha.device_id)
    window.show_running("Laptop-Minh", RECEIVE_DIR)
    window.set_addresses(["192.168.1.15"], None)
    return window, view, nha


def _fill_chat(view, nha) -> None:
    """Luồng của PC-Nha: nhận xong (9:12), gửi lỗi có “Gửi lại” (10:40), đang gửi 62%, bong bóng tạm."""
    from teleport.app.transfers import FileDone, TransferProgress, TransferStatusChanged

    _CLOCK[0] = _at(31, 9, 12)
    small = 1_800 * 2**20
    received = _transfer_info(nha.device_id, "receive", "b" * 32, "verifying", "anh-cuoi.zip", small, small)
    view.handle(TransferStatusChanged(received))
    view.handle(FileDone(received.key, 0, "anh-cuoi.zip", RECEIVE_DIR / "anh-cuoi.zip"))
    view.handle(_finished(received, "done"))

    _CLOCK[0] = _at(31, 10, 40)
    report = _transfer_info(nha.device_id, "send", "c" * 32, "transferring", "bao-cao.pdf", 4 * 2**20, 2**20)
    view.handle(TransferStatusChanged(report))
    view.handle(_finished(report, "source_changed"))
    view.set_resendable(report.key, True)

    _CLOCK[0] = _at(31, 10, 42)
    size = 18 * 2**30
    sending = _transfer_info(
        nha.device_id, "send", "a" * 32, "transferring", "phim-4k.mkv", size, size * 62 // 100
    )
    view.handle(TransferStatusChanged(sending))
    view.handle(TransferProgress(sending, 94 * 2**20, 60.0, shown_bytes=sending.done_bytes, idle_seconds=0.0))

    _CLOCK[0] = _at(31, 10, 44)
    view.add_pending(nha.device_id, [Path("C:/Users/Minh/Videos/slide-thuyet-trinh.pptx")])
    _CLOCK[0] = NOW


def scene_chat(qtbot) -> QWidget:
    """Spec B3: luồng của PC-Nha với bốn loại bong bóng và dòng mốc “Hôm nay …”."""
    window, view, nha = _chat_window(qtbot)
    _fill_chat(view, nha)
    return window


def scene_chat_new(qtbot) -> QWidget:
    """Luồng dài đã cuộn lên đầu, rồi có lượt mới: nút “↓ Mới” hiện, luồng không tự cuộn."""
    from teleport.app.transfers import TransferStatusChanged

    window, view, nha = _chat_window(qtbot)
    for index in range(9):
        _CLOCK[0] = _at(31, 8, 5 * index)
        info = _transfer_info(
            nha.device_id, "send", f"{index:032x}", "transferring", f"anh-{index:02d}.jpg", 3 * 2**20, 0
        )
        view.handle(TransferStatusChanged(info))
        view.handle(_finished(info, "done"))
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.resize(980, 660)
    window.show()
    QApplication.processEvents()
    thread = view.thread_for(nha.device_id)
    thread.scroll_area.verticalScrollBar().setValue(0)
    QApplication.processEvents()
    _CLOCK[0] = _at(31, 10, 44)
    info = _transfer_info(nha.device_id, "receive", "f" * 32, "waiting", "hop-dong.docx", 2**20, 0)
    view.handle(TransferStatusChanged(info))
    _CLOCK[0] = NOW
    return window


def scene_chat_drop(qtbot) -> QWidget:
    """Như `chat`, đang kéo 3 file vào luồng: viền nét đứt và “Thả để gửi 3 file tới PC-Nha”."""
    window, view, nha = _chat_window(qtbot)
    _fill_chat(view, nha)
    window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.show()
    QApplication.processEvents()
    view.preview_drop(3)
    return window


def scene_chat_offline(qtbot) -> QWidget:
    """PC-Nha ngoại tuyến: lượt gửi đang chờ kết nối, thanh dưới có câu ngoại tuyến và icon."""
    from teleport.app.transfers import TransferStatusChanged

    window, view, nha = _chat_window(qtbot, nha_online=False)
    view.set_connected(nha.device_id, False)
    _CLOCK[0] = _at(31, 10, 43)
    info = _transfer_info(nha.device_id, "send", "d" * 32, "waiting", "video-demo.mp4", 3 * 2**30, 0)
    view.handle(TransferStatusChanged(info))
    _CLOCK[0] = NOW
    return window


def scene_chat_history(qtbot) -> QWidget:
    """Lịch sử với PC-Nha (hai ngày trước, hôm qua, lỗi, đã từ chối) và một lượt phiên hôm nay."""
    from teleport.app.transfers import TransferStatusChanged
    from teleport.core.history import HistoryEntry
    from teleport.core.transfer import Direction

    window, view, nha = _chat_window(qtbot)

    def entry(tid: str, direction: str, names, result: str, day: int, hour: int, minute: int, saved=None):
        return HistoryEntry(
            direction=Direction(direction),
            device_id=nha.device_id,
            device_name="PC-Nha",
            transfer_id=tid * 32,
            file_count=len(names),
            total_bytes=len(names) * 420 * 2**20,
            done_bytes=len(names) * 420 * 2**20 if result == "done" else 0,
            names=tuple(names),
            result=result,
            finished_at=datetime.datetime(2026, 10, day, hour, minute).astimezone(datetime.UTC),
            saved_path=saved,
        )

    entries = [
        entry("1", "receive", ["slide.pptx"], "done", 29, 15, 2, str(RECEIVE_DIR / "slide.pptx")),
        entry("2", "send", ["a.jpg", "b.jpg", "c.jpg"], "done", 29, 15, 20),
        entry("3", "send", ["phim-cu.mkv"], "rejected_user", 30, 21, 3),
        entry("4", "receive", ["nhac.mp3"], "disk_failed", 30, 21, 40),
    ]
    view.history_needed.connect(lambda device_id: view.load_history(device_id, entries))
    view._history_timer.stop()
    view._request_history()
    _CLOCK[0] = _at(31, 10, 41)
    info = _transfer_info(nha.device_id, "send", "e" * 32, "transferring", "ghi-chu.txt", 12 * 2**10, 0)
    view.handle(TransferStatusChanged(info))
    view.handle(_finished(info, "done"))
    _CLOCK[0] = NOW
    return window


def scene_chat_empty(qtbot) -> QWidget:
    """PC-Nha chưa có lượt nào (không có lịch sử): màn rỗng “Kéo file vào đây để gửi cho PC-Nha”."""
    window, _view, _nha = _chat_window(qtbot)
    return window


def _offer(device_id: str, names_sizes, transfer_id: str = "d" * 32):
    from teleport.app.transfers import OfferReceived
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import Direction, TransferKey

    files = tuple(FileEntry(name, size, 1_700_000_000_000) for name, size in names_sizes)
    return OfferReceived(
        key=TransferKey(device_id, Direction.RECEIVE, transfer_id),
        device_name="PC-Nha",
        files=files,
        names=tuple(name for name, _ in names_sizes),
        total_bytes=sum(size for _, size in names_sizes),
        auto_accepted=False,
    )


_OFFER_FILES = (
    ("video-dam-cuoi.mp4", 8 * 2**30),
    ("anh-bia.png", int(2.1 * 2**20)),
    ("ke-hoach.docx", 380 * 1024),
)


def _framed(qtbot, dialog) -> QWidget:
    """Nhúng hộp `dialog` (cờ `Qt.Widget`) giữa một nền `surface` để chụp như ảnh duyệt."""
    from PySide6.QtWidgets import QGridLayout

    frame = QWidget()
    qtbot.addWidget(frame)
    frame.setObjectName("snapshotDialogFrame")
    frame.setAutoFillBackground(True)  # nền Window của bảng màu theme (`surface`)
    dialog.setWindowFlags(Qt.WindowType.Widget)
    layout = QGridLayout(frame)
    layout.addWidget(dialog, 0, 0, Qt.AlignmentFlag.AlignCenter)
    return frame


def scene_offer_box(qtbot) -> QWidget:
    """Hộp hỏi nhận 3 file từ PC-Nha (spec B4 mục 3.4): “Đổi…”, ô “Luôn nhận”, Từ chối / Nhận."""
    from teleport.ui.offer import OfferBook, OfferPrompts

    book = OfferBook()
    prompts = OfferPrompts(book, RECEIVE_DIR)
    nha = _paired("PC-Nha", "windows", online=True, connected=True)
    item = _offer(nha.device_id, _OFFER_FILES)
    assert book.add(item)
    box = prompts.preview(item.key)
    assert box is not None
    frame = _framed(qtbot, box)
    frame._snapshot_keep = (book, prompts)  # giữ sống tới khi chụp xong
    return frame


def scene_chat_offer(qtbot) -> QWidget:
    """Luồng của PC-Nha có lời mời đang chờ trả lời: panel Nhận / Từ chối trong bong bóng (spec B4)."""
    from teleport.ui.offer import OfferBook

    window, view, nha = _chat_window(qtbot)
    _fill_chat(view, nha)
    book = OfferBook(window)
    view.set_offer_book(book)
    _CLOCK[0] = _at(31, 10, 45)
    item = _offer(nha.device_id, _OFFER_FILES)
    view.handle(item)
    assert book.add(item)
    _CLOCK[0] = NOW
    return window


def scene_pairing_countdown(qtbot) -> QWidget:
    """Hộp mã ghép đôi còn 8 giây (spec B4 mục 3.7): mã thành ô, thanh ngắn, chữ màu cảnh báo."""
    from teleport.app.pairing import PairingPrompt
    from teleport.core.pairing import Role
    from teleport.ui.pairing import PairingDialog

    prompt = PairingPrompt(
        session_id=1,
        role=Role.RESPONDER,
        address="192.168.1.20",
        peer_name="PC-Nha",
        peer_device_id=hashlib.sha256(b"PC-Nha").hexdigest()[:32],
        code="382104",
        expires_at=100.0,
        recent_codes=1,
        known_name=None,
    )
    dialog = PairingDialog(prompt, clock=lambda: 92.0)
    return _framed(qtbot, dialog)


SCENES: dict[str, tuple[Callable[..., QWidget], bool, str | None]] = {
    # tên cảnh: (hàm dựng, là cửa sổ chính, token mà điểm (4,4) phải bằng; None: không kiểm góc)
    "welcome": (scene_welcome, True, "surface"),
    "welcome_no_autostart": (scene_welcome_no_autostart, True, "surface"),
    "welcome_name_error": (scene_welcome_name_error, True, "surface"),
    "welcome_dir_error": (scene_welcome_dir_error, True, "surface"),
    "starting": (scene_starting, True, "surface"),
    "running": (scene_running, True, "sidebar"),
    "running_full": (scene_running_full, True, "sidebar"),
    "running_unavailable": (scene_running_unavailable, True, "sidebar"),
    "error": (scene_error, True, "surface"),
    "widgets": (scene_widgets, False, None),
    "page": (scene_page, True, "surface"),
    "discover": (scene_discover, True, "surface"),
    "discover_list": (scene_discover_list, True, "surface"),
    "discover_list_empty": (scene_discover_list_empty, True, "surface"),
    "conversations": (scene_conversations, True, "sidebar"),
    "conversations_drop": (scene_conversations_drop, True, "sidebar"),
    "settings_general": (scene_settings_general, True, "surface"),
    "settings_appearance": (scene_settings_appearance, True, "surface"),
    "settings_privacy_hidden": (scene_settings_privacy_hidden, True, "surface"),
    "settings_devices": (scene_settings_devices, True, "surface"),
    "settings_devices_empty": (scene_settings_devices_empty, True, "surface"),
    "settings_advanced": (scene_settings_advanced, True, "surface"),
    "settings_receive_dir_unavailable": (scene_settings_receive_dir_unavailable, True, "surface"),
    "chat": (scene_chat, True, "sidebar"),
    "chat_new": (scene_chat_new, True, "sidebar"),
    "chat_drop": (scene_chat_drop, True, "sidebar"),
    "chat_offline": (scene_chat_offline, True, "sidebar"),
    "chat_history": (scene_chat_history, True, "sidebar"),
    "chat_empty": (scene_chat_empty, True, "sidebar"),
    "offer_box": (scene_offer_box, False, None),
    "chat_offer": (scene_chat_offer, True, "sidebar"),
    "pairing_countdown": (scene_pairing_countdown, False, None),
}


# ---- Chụp --------------------------------------------------------------------------------------


def _grab(widget: QWidget, width: int, height: int) -> QImage:
    widget.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    widget.resize(width, height)
    widget.show()
    for _ in range(3):  # hàng đổi bố cục theo bề ngang (trang Cài đặt) cần thêm một lượt layout
        QApplication.processEvents()
    image = widget.grab().toImage()
    widget.hide()
    return image


def _save(image: QImage, scene: str, mode: str, width: int, height: int) -> None:
    folder = os.environ.get(SNAPSHOT_ENV)
    if not folder:
        return
    path = Path(folder)
    path.mkdir(parents=True, exist_ok=True)
    assert image.save(str(path / f"{scene}_{mode}_{width}x{height}.png"))


@pytest.mark.parametrize(("width", "height"), SIZES, ids=[f"{w}x{h}" for w, h in SIZES])
@pytest.mark.parametrize("scene", list(SCENES))
def test_snapshot(qtbot, ui_theme, scene, width, height):
    build, is_window, corner_token = SCENES[scene]
    language = os.environ.get(LANG_ENV)
    if language:
        from teleport.ui import i18n

        i18n.set_language(language)  # autouse `ui_language_reset` trả về chuỗi nguồn sau test
        assert i18n.current_language() == language, f"không nạp được bản dịch {language!r}"
    images: dict[str, QImage] = {}
    for dark, mode in ((False, "light"), (True, "dark")):
        tokens = ui_theme(dark)
        widget = build(qtbot)
        image = _grab(widget, width, height)
        dpr = widget.devicePixelRatioF()
        assert (image.width(), image.height()) == (round(width * dpr), round(height * dpr)), mode
        if is_window:
            assert (widget.width(), widget.height()) == (width, height), (mode, widget.size())
        if corner_token is not None:
            corner = QColor(image.pixel(round(4 * dpr), round(4 * dpr)))
            expected = getattr(tokens, corner_token)
            assert corner.name() == expected.name(), (mode, corner_token, corner.name())
        _save(image, scene, mode, width, height)
        images[mode] = image
    assert images["light"] != images["dark"]
