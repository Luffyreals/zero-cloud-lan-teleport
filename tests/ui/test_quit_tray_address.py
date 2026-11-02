"""PR-6: dòng “Địa chỉ” (B1), hỏi lại khi Thoát còn lượt gửi dở (B2), khay và bóng thoại (B5).

Viết từ spec PR-6 (mục “Tiêu chí xong” 1–6), không từ code. Ba cách dựng:

- `MainWindow`, `Tray`, `TransfersController` đứng riêng (không node, không socket).
- `GuiApp` dựng thẳng (fixture `gapp`): máy chưa có danh tính, không gọi `start()`, nên không có node;
  lượt gửi/nhận giả bằng cách đẩy `TransferUpdate` vào `gapp.transfers.on_transfer`.
- `main()` trong tiến trình (fixture `gui` của conftest): khi cần luồng thật (SIGINT, khay, đóng cửa
  sổ, `commitDataRequest`); ca có node chạy thật mở socket 127.0.0.1 nên gắn `integration`.

Không mở hộp thoại bằng `exec()`. Nền `offscreen` không tin được `QApplication.activeWindow()`: test vá
seam `app_active` hay chính `QApplication.activeWindow`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

integration = pytest.mark.integration

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"

# Câu chữ của spec PR-6 (nguyên văn).
ADDRESS = "Địa chỉ: {address}"
ADDRESS_A11Y = "Địa chỉ của máy này"
ADDRESS_OTHERS = "Các địa chỉ khác của máy này: {list}"
QUIT_TITLE = "Thoát Teleport?"
QUIT_ONE = "Đang gửi file tới {name}. Thoát bây giờ sẽ hủy lượt gửi."
QUIT_MANY = "Đang gửi file tới {n} máy. Thoát bây giờ sẽ hủy các lượt gửi."
QUIT_YES = "Thoát"
QUIT_NO = "Không"
OFFER_WAITING = "Có file đang chờ bạn nhận."
PAIR_NOTE = "Có yêu cầu ghép đôi"
OPEN = "Mở Teleport"


# =================================================================================================
# Dữ liệu giả
# =================================================================================================


def dview(device_id: str = PEER_ID, name: str | None = PEER):
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


def tkey(direction: str = "send", device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), uuid.uuid4().hex)


def tinfo(key, *, status: str = "transferring", names=("video.mp4",)):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    files = tuple(FileEntry(n, 1000, 0) for n in names)
    return TransferInfo(
        key=key,
        status=TransferStatus(status),
        files=files,
        names=tuple(names),
        file_index=0,
        done_bytes=0,
        total_bytes=1000 * len(names),
    )


def changed(key, status: str = "transferring"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(tinfo(key, status=status))


def finished(key, result: str = "done", *, names=("video.mp4",)):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=tinfo(key, status="verifying", names=names),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=None,
        reject=None,
    )


def offer(key, *, name: str | None = PEER, names=("video.mp4",), auto: bool = False):
    from teleport.app.transfers import OfferReceived
    from teleport.core.messages import FileEntry

    files = tuple(FileEntry(n, 1000, 0) for n in names)
    return OfferReceived(
        key=key,
        device_name=name,
        files=files,
        names=tuple(names),
        total_bytes=1000 * len(names),
        auto_accepted=auto,
    )


def file_done(key, path: Path, name: str = "video.mp4"):
    from teleport.app.transfers import FileDone

    return FileDone(key=key, file_index=0, name=name, path=path)


def online(device_id: str = PEER_ID, name: str | None = PEER):
    from teleport.app.node import DeviceOnline

    return DeviceOnline(dview(device_id, name))


def pair_prompt(sid: int = 7):
    from teleport.app.pairing import PairingPrompt
    from teleport.core.pairing import Role

    return PairingPrompt(
        session_id=sid,
        role=Role("responder"),
        address="192.168.1.5",
        peer_name="MacBook",
        peer_device_id=PEER_ID,
        code="905617",
        expires_at=time.monotonic() + 60.0,
        recent_codes=1,
        known_name=None,
    )


def fake_host(receive_dir: Path):
    """Host tối thiểu cho `TransfersController.attach` (chỉ đọc `options.receive_dir`)."""
    return SimpleNamespace(
        options=SimpleNamespace(receive_dir=receive_dir),
        calls=[],
        submits=[],
        call=lambda fn, on_done=None: None,
        submit=lambda fn, on_done=None: None,
        running=True,
        is_stopped=False,
        node_name="May-A",
    )


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def quit_boxes() -> list:
    """Hộp xác nhận thoát đang hiện: `QMessageBox` cấp cao nhất đang hiện (objectName `quitConfirmBox`
    nếu có, không thì mọi `QMessageBox` đang hiện, vì test không mở hộp nào khác)."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    boxes = [w for w in QApplication.topLevelWidgets() if isinstance(w, QMessageBox) and w.isVisible()]
    named = [b for b in boxes if b.objectName() == "quitConfirmBox"]
    return named or boxes


def box_button(box, text: str):
    [button] = [b for b in box.buttons() if plain(b.text()) == text]
    return button


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def fake_tray_icon(monkeypatch):
    """Khay “có thật”: `is_available` True, `QSystemTrayIcon` nhớ hiện/ẩn, ghi lại mọi `showMessage`."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.ui import tray

    shown: dict[int, bool] = {}
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "is_available", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.__setitem__(id(self), True))
    monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: shown.__setitem__(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "setVisible", lambda self, v: shown.__setitem__(id(self), bool(v)))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: shown.get(id(self), False))

    def show_message(self, *args, **kwargs):
        title = args[0] if args else kwargs.get("title", "")
        body = args[1] if len(args) > 1 else kwargs.get("msg", kwargs.get("message", ""))
        messages.append((str(title), str(body)))

    monkeypatch.setattr(QSystemTrayIcon, "showMessage", show_message)
    return SimpleNamespace(messages=messages, shown=shown)


@pytest.fixture
def no_exec(monkeypatch):
    """Ghi lại mọi `exec()` của hộp thoại (không được dùng) và trả 0 ngay."""
    from PySide6.QtWidgets import QDialog, QMessageBox

    calls: list[str] = []

    def fake(self, *args, **kwargs):
        calls.append(type(self).__name__)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake)
    monkeypatch.setattr(QDialog, "exec", fake)
    return calls


@pytest.fixture
def gapp(qapp, qtbot, monkeypatch, config_dir, fake_tray_icon, no_exec):
    """`GuiApp` dựng thẳng, không node (máy chưa có danh tính, không gọi `start()`); khay hiện."""
    from teleport.ui.app import GuiApp

    controller = GuiApp(qapp, config_dir("A", identity=False))
    controller.tray.show()
    controller.window.show()
    yield controller
    for box in quit_boxes():
        with contextlib.suppress(Exception):
            box.close()
    with contextlib.suppress(Exception):
        controller.shutdown()
    with contextlib.suppress(Exception):
        controller.window.hide()
        controller.window.deleteLater()
    qapp.processEvents()


def add_send_row(controller, device_id: str = PEER_ID, name: str | None = PEER):
    """Một lượt gửi đang chạy tới `device_id` (tên máy qua `DeviceOnline`)."""
    controller.transfers.on_node_event(online(device_id, name))
    key = tkey("send", device_id)
    controller.transfers.on_transfer(changed(key, "transferring"))
    return key


# =================================================================================================
# B1. Dòng “Địa chỉ” của MainWindow (tiêu chí 1)
# =================================================================================================


@pytest.fixture
def window(qtbot):
    from teleport.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


def running(window):
    window.show_running("May-A", Path("nhan"))
    return window


def test_address_label_shows_first_address_without_default_port(window):
    from teleport.net.connection import DEFAULT_PORT

    running(window).set_addresses(["192.0.2.5"], DEFAULT_PORT)
    label = window.address_label
    assert label.objectName() == "addressLabel"
    assert label.isVisibleTo(window)
    assert label.text() == ADDRESS.format(address="192.0.2.5")
    assert label.toolTip() == ""


def test_address_label_without_port_has_no_suffix(window):
    running(window).set_addresses(["192.0.2.5"], None)
    assert window.address_label.text() == ADDRESS.format(address="192.0.2.5")


def test_address_label_appends_non_default_port(window):
    running(window).set_addresses(["192.0.2.5"], 50000)
    assert window.address_label.isVisibleTo(window)
    assert window.address_label.text() == ADDRESS.format(address="192.0.2.5:50000")


def test_address_label_many_addresses_text_has_first_tooltip_has_others(window):
    running(window).set_addresses(["192.0.2.5", "10.0.0.7", "172.16.0.9"], None)
    label = window.address_label
    assert label.text() == ADDRESS.format(address="192.0.2.5")
    others = ADDRESS_OTHERS.format(list="10.0.0.7, 172.16.0.9")
    assert label.toolTip() == others
    assert label.accessibleDescription() == others


def test_address_label_tooltip_others_carry_port_suffix(window):
    running(window).set_addresses(["192.0.2.5", "10.0.0.7"], 50000)
    assert window.address_label.text() == ADDRESS.format(address="192.0.2.5:50000")
    assert window.address_label.toolTip() == ADDRESS_OTHERS.format(list="10.0.0.7:50000")


def test_address_label_hidden_when_no_addresses(window):
    running(window).set_addresses(["192.0.2.5"], None)
    window.set_addresses([], None)
    assert not window.address_label.isVisibleTo(window)


def test_address_label_hidden_while_starting_even_with_addresses(window):
    window.show_starting()
    window.set_addresses(["192.0.2.5"], None)
    assert not window.address_label.isVisibleTo(window)


@pytest.mark.parametrize("leave", ["starting", "error", "welcome"])
def test_leaving_running_hides_and_forgets_addresses(window, leave):
    running(window).set_addresses(["192.0.2.5"], 50000)
    assert window.address_label.isVisibleTo(window)
    if leave == "starting":
        window.show_starting()
    elif leave == "error":
        window.show_error("locked", "")
    else:
        window.show_welcome("May-A")
    assert not window.address_label.isVisibleTo(window)
    running(window)  # quay lại RUNNING mà chưa đọc lại: địa chỉ cũ đã bị xóa
    assert not window.address_label.isVisibleTo(window), "rời RUNNING phải xóa địa chỉ đã nhớ"


def test_address_label_survives_retranslate(window):
    running(window).set_addresses(["192.0.2.5", "10.0.0.7"], 50000)
    window.retranslate()
    assert window.address_label.isVisibleTo(window)
    assert window.address_label.text() == ADDRESS.format(address="192.0.2.5:50000")
    assert window.address_label.toolTip() == ADDRESS_OTHERS.format(list="10.0.0.7:50000")


def test_address_label_is_plain_selectable_tab_focusable_and_named(window):
    from PySide6.QtCore import Qt

    running(window).set_addresses(["<b>192.0.2.5</b>"], None)
    label = window.address_label
    assert label.textFormat() == Qt.TextFormat.PlainText
    flags = label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    # PR-7: không con trỏ chữ khi Tab tới nhãn (chỉ chọn bằng chuột), Tab vẫn đi qua.
    assert not flags & Qt.TextInteractionFlag.TextSelectableByKeyboard
    assert label.focusPolicy() & Qt.FocusPolicy.TabFocus
    assert label.accessibleName() == ADDRESS_A11Y


def _layout_holding(layout, widget):
    """Layout (trong cây layout `layout`) chứa trực tiếp `widget`; không có → None."""
    if layout is None:
        return None
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        found = _layout_holding(layout.itemAt(i).layout(), widget)
        if found is not None:
            return found
    return None


def test_address_label_sits_right_below_name_label_in_machine_card(window):
    # Spec B1 mục 8b + 12.4: dòng địa chỉ chuyển từ cột trạng thái (dưới `detail_label`) vào thẻ “máy
    # này”, ngay dưới tên máy; nó nằm chung một hàng con với nút “Chép địa chỉ”.
    card = window.machine_card
    assert card.isAncestorOf(window.address_label)
    column = _layout_holding(card.layout(), window.name_label)
    assert column is not None, "name_label phải nằm trong layout của machine_card"
    below = column.itemAt(column.indexOf(window.name_label) + 1)
    assert below is not None
    assert below.widget() is window.address_label or (
        below.layout() is not None and below.layout().indexOf(window.address_label) >= 0
    ), "address_label không nằm ngay dưới name_label"


# =================================================================================================
# B1. GuiApp đọc địa chỉ từ node thật (tiêu chí 2)
# =================================================================================================


def host_started(run) -> bool:
    return bool(run.hosts) and run.hosts[-1].running


def tray_action(run, text: str):
    [action] = [a for a in run.tray.actions() if plain(a.text()) == text]
    return action


@pytest.fixture
def address_spy(monkeypatch):
    """Vá `Node.local_addresses`: ghi thread gọi, cổng của node; `behaviour(n, real, node)` tùy chỉnh."""
    from teleport.app import node as app_node

    real = app_node.Node.local_addresses
    spy = SimpleNamespace(calls=0, on_qt_thread=[], port=None, behaviour=None)

    async def local_addresses(self):
        spy.calls += 1
        spy.on_qt_thread.append(threading.current_thread() is threading.main_thread())
        spy.port = self.port
        if spy.behaviour is not None:
            return await spy.behaviour(spy.calls, real, self)
        return await real(self)

    monkeypatch.setattr(app_node.Node, "local_addresses", local_addresses)
    return spy


@integration
def test_gui_shows_loopback_address_reads_off_qt_thread_and_refreshes(gui, gui_wait, config_dir, address_spy):
    from teleport.ui import app as ui_app

    d = config_dir("A")
    seen: dict = {}

    def expected() -> str:
        return ADDRESS.format(address=f"127.0.0.1:{address_spy.port}")

    def script(run):
        yield gui_wait(lambda: run.windows and host_started(run), 15, "node chạy")
        win = run.window
        win.resize(980, 660)  # spec B2 2.6: hẹp hơn 820 px thì cột trái thu gọn, `machine_card` ẩn
        yield gui_wait(
            lambda: (
                address_spy.port is not None
                and win.address_label.isVisibleTo(win)
                and win.address_label.text() == expected()
            ),
            5,
            "nhãn địa chỉ 127.0.0.1:<cổng>",
        )
        controller = run.tray.parent()
        seen["controller"] = controller
        timer = controller.address_timer
        seen["interval"] = timer.interval()
        seen["active"] = timer.isActive()
        seen["constant"] = ui_app.ADDRESS_REFRESH_MS
        first = address_spy.calls
        timer.setInterval(50)  # thấy lần đọc lại mà không chờ 10 s
        yield gui_wait(lambda: address_spy.calls >= first + 1, 5, "lần đọc lại theo hẹn giờ")
        tray_action(run, QUIT_YES).trigger()
        seen["active_after_quit"] = timer.isActive()

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["constant"] == 10_000
    assert seen["interval"] == 10_000
    assert seen["active"], "timer địa chỉ phải chạy ở RUNNING"
    assert not seen["active_after_quit"], "Thoát phải dừng timer địa chỉ"
    assert address_spy.calls >= 2
    assert not any(address_spy.on_qt_thread), "Node.local_addresses không được chạy trên thread Qt"


@integration
def test_gui_address_read_error_keeps_old_address_and_logs_type(
    gui, gui_wait, config_dir, address_spy, caplog
):
    d = config_dir("A")
    seen: dict = {}

    async def behaviour(n, real, node):
        if n == 1:
            return await real(node)
        raise OSError("bí mật không được vào log")

    address_spy.behaviour = behaviour

    def script(run):
        yield gui_wait(lambda: run.windows and host_started(run), 15, "node chạy")
        win = run.window
        win.resize(980, 660)  # spec B2 2.6: hẹp hơn 820 px thì cột trái thu gọn, `machine_card` ẩn
        yield gui_wait(lambda: win.address_label.isVisibleTo(win), 5, "nhãn địa chỉ")
        before = win.address_label.text()
        run.tray.parent().address_timer.setInterval(30)
        yield gui_wait(lambda: address_spy.calls >= 3, 5, "các lần đọc lỗi")
        for _ in range(5):
            yield
        seen["before"], seen["after"] = before, win.address_label.text()
        seen["visible"] = win.address_label.isVisibleTo(win)
        tray_action(run, QUIT_YES).trigger()

    with caplog.at_level(logging.WARNING):
        run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["visible"] and seen["after"] == seen["before"], "lỗi đọc giữ địa chỉ cũ"
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("OSError" in m for m in warnings), warnings
    assert not any("bí mật" in m for m in warnings), "chỉ ghi tên loại lỗi"


@integration
def test_gui_address_read_in_flight_is_not_stacked(gui, gui_wait, config_dir, address_spy):
    d = config_dir("A")
    seen: dict = {}

    async def behaviour(n, real, node):
        if n == 1:
            return await real(node)
        await asyncio.sleep(60)  # lần đọc thứ hai treo: bị hủy khi node dừng
        return ()

    address_spy.behaviour = behaviour

    def script(run):
        yield gui_wait(lambda: run.windows and host_started(run), 15, "node chạy")
        win = run.window
        win.resize(980, 660)  # spec B2 2.6: hẹp hơn 820 px thì cột trái thu gọn, `machine_card` ẩn
        yield gui_wait(lambda: win.address_label.isVisibleTo(win), 5, "nhãn địa chỉ")
        run.tray.parent().address_timer.setInterval(30)
        yield gui_wait(lambda: address_spy.calls >= 2, 5, "lần đọc thứ hai")
        t0 = time.monotonic()
        yield gui_wait(lambda: time.monotonic() - t0 > 0.6, 3, "chờ ~20 chu kỳ hẹn")
        seen["calls"] = address_spy.calls
        tray_action(run, QUIT_YES).trigger()

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["calls"] == 2, f"lần đọc chưa xong thì không chồng việc: {seen['calls']} lần"


@integration
def test_gui_start_failed_stops_address_timer_and_hides_label(gui, gui_wait, config_dir, address_spy):
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and host_started(run), 15, "node chạy")
        win = run.window
        win.resize(980, 660)  # spec B2 2.6: hẹp hơn 820 px thì cột trái thu gọn, `machine_card` ẩn
        yield gui_wait(lambda: win.address_label.isVisibleTo(win), 5, "nhãn địa chỉ")
        timer = run.tray.parent().address_timer
        seen["before"] = timer.isActive()
        run.host.start_failed.emit("locked", "")  # giả lập start_failed của host hiện tại
        yield
        seen["after"] = timer.isActive()
        seen["label"] = win.address_label.isVisibleTo(win)
        tray_action(run, QUIT_YES).trigger()

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["before"]
    assert not seen["after"], "start_failed phải dừng timer địa chỉ"
    assert not seen["label"], "ERROR thì ẩn địa chỉ"


@integration
def test_gui_retry_after_locked_shows_address_of_new_host(gui, gui_wait, config_dir, address_spy, fast_lock):
    from teleport.lock import NodeLock

    d = config_dir("A")
    holder = NodeLock(d)
    holder.acquire()
    seen: dict = {}

    def script(run):
        from teleport.ui.main_window import ViewState

        yield gui_wait(lambda: run.windows and run.window.view_state is ViewState.ERROR, 15, "lỗi locked")
        timer = run.tray.parent().address_timer
        seen["error_active"] = timer.isActive()
        seen["error_label"] = run.window.address_label.isVisibleTo(run.window)
        holder.release()
        run.window.retry_requested.emit()
        yield gui_wait(lambda: len(run.hosts) >= 2 and host_started(run), 15, "node chạy sau Thử lại")
        win = run.window
        win.resize(980, 660)  # spec B2 2.6: hẹp hơn 820 px thì cột trái thu gọn, `machine_card` ẩn
        yield gui_wait(
            lambda: (
                win.address_label.text() == ADDRESS.format(address=f"127.0.0.1:{address_spy.port}")
                and win.address_label.isVisibleTo(win)
            ),
            5,
            "địa chỉ của host mới",
        )
        seen["running_active"] = timer.isActive()
        tray_action(run, QUIT_YES).trigger()

    try:
        run = gui(["--config-dir", str(d)], script)
    finally:
        holder.release()
    assert run.code == 0
    assert not seen["error_active"] and not seen["error_label"]
    assert seen["running_active"]


# =================================================================================================
# B2. TransfersController.active_sends
# =================================================================================================


@pytest.fixture
def ctl_env(qtbot, monkeypatch, tmp_path):
    """`make(**kw) -> SimpleNamespace(ctl, window, tray, messages)`; `messages`: chữ của mọi bóng thoại,
    `folders`: thư mục kèm theo."""
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    messages: list[str] = []
    folders: list = []

    def record(self, text, folder=None):
        messages.append(text)
        folders.append(folder)

    monkeypatch.setattr(Tray, "show_message", record)
    made: list = []

    def make(**kw):
        window = MainWindow()
        qtbot.addWidget(window)
        tray = Tray()
        ctl = mod.TransfersController(window, tray, None, **kw)
        ctl.attach(fake_host(tmp_path / "nhan"))
        ns = SimpleNamespace(ctl=ctl, window=window, tray=tray, messages=messages, folders=folders)
        made.append(ns)
        return ns

    yield make
    for ns in made:
        ns.ctl.close_all()
        ns.tray.dispose()


def test_active_sends_empty_without_rows(ctl_env):
    assert ctl_env().ctl.active_sends() == []


def test_active_sends_lists_peer_label_of_unfinished_send(ctl_env):
    ns = ctl_env()
    ns.ctl.on_node_event(online(PEER_ID, PEER))
    ns.ctl.on_transfer(changed(tkey("send"), "transferring"))
    assert ns.ctl.active_sends() == [PEER]


def test_active_sends_without_name_uses_device_id_prefix(ctl_env):
    from teleport.ui import texts

    ns = ctl_env()
    ns.ctl.on_transfer(changed(tkey("send", OTHER_ID), "waiting"))
    assert ns.ctl.active_sends() == [texts.peer_label(None, OTHER_ID)]


def test_active_sends_ignores_receive_rows(ctl_env):
    ns = ctl_env()
    ns.ctl.on_node_event(online())
    ns.ctl.on_transfer(changed(tkey("receive"), "transferring"))
    assert ns.ctl.active_sends() == []


def test_active_sends_ignores_finished_send(ctl_env):
    ns = ctl_env()
    ns.ctl.on_node_event(online())
    key = tkey("send")
    ns.ctl.on_transfer(changed(key, "transferring"))
    ns.ctl.on_transfer(finished(key, "done"))
    assert ns.ctl.active_sends() == []


def test_active_sends_no_duplicates_and_keeps_row_order(ctl_env):
    ns = ctl_env()
    ns.ctl.on_node_event(online(PEER_ID, PEER))
    ns.ctl.on_node_event(online(OTHER_ID, OTHER))
    ns.ctl.on_transfer(changed(tkey("send", PEER_ID)))
    ns.ctl.on_transfer(changed(tkey("send", OTHER_ID)))
    ns.ctl.on_transfer(changed(tkey("send", PEER_ID), "waiting"))
    ns.ctl.on_transfer(changed(tkey("receive", OTHER_ID)))
    rows = [r.key.device_id for r in ns.ctl.view.rows() if r.key.direction.value == "send"]
    order = list(dict.fromkeys(rows))
    expected = [{PEER_ID: PEER, OTHER_ID: OTHER}[i] for i in order]
    assert ns.ctl.active_sends() == expected
    assert sorted(expected) == sorted([PEER, OTHER])


# =================================================================================================
# B2. GuiApp.request_quit hỏi lại (tiêu chí 3)
# =================================================================================================


def test_quit_with_active_send_opens_confirm_box_and_does_not_quit(gapp, qtbot, no_exec):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QMessageBox

    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    [box] = quit_boxes()
    assert not gapp.quitting
    assert gapp.window.isVisible(), "cửa sổ chính được đưa lên trước"
    assert box.parent() is gapp.window
    # macOS bỏ tiêu đề của QMessageBox (hướng dẫn giao diện Apple), nên ở đó `windowTitle()` rỗng.
    if sys.platform != "darwin":
        assert box.windowTitle() == QUIT_TITLE
    assert box.accessibleName() == QUIT_TITLE
    assert box.text() == QUIT_ONE.format(name=PEER)
    assert box.textFormat() == Qt.TextFormat.PlainText
    yes, no = box_button(box, QUIT_YES), box_button(box, QUIT_NO)
    assert box.buttonRole(yes) == QMessageBox.ButtonRole.DestructiveRole
    assert box.buttonRole(no) == QMessageBox.ButtonRole.RejectRole
    assert box.defaultButton() is no, "nút mặc định là “Không”"
    assert no_exec == [], "hộp xác nhận mở bằng open(), không exec()"


def test_quit_box_names_count_when_many_devices(gapp, qtbot):
    add_send_row(gapp, PEER_ID, PEER)
    add_send_row(gapp, OTHER_ID, OTHER)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    assert quit_boxes()[0].text() == QUIT_MANY.format(n=2)


def test_quit_box_no_keeps_app_running(gapp, qtbot):
    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    box_button(quit_boxes()[0], QUIT_NO).click()
    qtbot.waitUntil(lambda: not quit_boxes(), timeout=2_000)
    qtbot.wait(50)
    assert not gapp.quitting
    assert gapp.window.isVisible()


def test_quit_box_escape_means_no(gapp, qtbot):
    from PySide6.QtCore import Qt

    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    qtbot.keyClick(quit_boxes()[0], Qt.Key.Key_Escape)
    qtbot.waitUntil(lambda: not quit_boxes(), timeout=2_000)
    qtbot.wait(50)
    assert not gapp.quitting


def test_second_request_quit_while_box_open_does_not_open_second_box(gapp, qtbot):
    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    first = quit_boxes()[0]
    gapp.request_quit()
    qtbot.wait(50)
    assert quit_boxes() == [first]
    assert not gapp.quitting


def test_quit_box_quit_button_runs_quit_flow(gapp, qtbot):
    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    box_button(quit_boxes()[0], QUIT_YES).click()
    qtbot.waitUntil(lambda: gapp.quitting, timeout=2_000)
    assert not gapp.window.isVisible(), "luồng thoát ẩn cửa sổ"
    assert not quit_boxes()


def test_quit_without_any_transfer_quits_at_once(gapp):
    gapp.request_quit()
    assert gapp.quitting
    assert not quit_boxes()


def test_quit_with_only_receive_in_progress_quits_without_asking(gapp):
    gapp.transfers.on_node_event(online())
    gapp.transfers.on_transfer(changed(tkey("receive"), "transferring"))
    gapp.request_quit()
    assert gapp.quitting
    assert not quit_boxes()


def test_quit_after_send_finished_does_not_ask(gapp):
    key = add_send_row(gapp)
    gapp.transfers.on_transfer(finished(key, "done"))
    gapp.request_quit()
    assert gapp.quitting
    assert not quit_boxes()


def test_request_quit_confirm_false_does_not_ask(gapp):
    add_send_row(gapp)
    gapp.request_quit(confirm=False)
    assert gapp.quitting
    assert not quit_boxes()


def test_quit_without_confirm_closes_open_confirm_box(gapp, qtbot):
    add_send_row(gapp)
    gapp.request_quit()
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    gapp.request_quit(confirm=False)
    assert gapp.quitting
    qtbot.waitUntil(lambda: not quit_boxes(), timeout=2_000)


def test_ctrl_q_goes_through_confirm(gapp, qtbot):
    add_send_row(gapp)
    gapp.window.quit_requested.emit()  # Ctrl+Q
    qtbot.waitUntil(lambda: len(quit_boxes()) == 1, timeout=2_000)
    assert not gapp.quitting


def test_saving_session_does_not_ask(gapp, monkeypatch):
    from PySide6.QtGui import QGuiApplication

    monkeypatch.setattr(QGuiApplication, "isSavingSession", lambda self: True)
    add_send_row(gapp)
    gapp.request_quit()
    assert gapp.quitting, "Windows đang tắt máy/đăng xuất: không hỏi"
    assert not quit_boxes()


class FakeSessionManager:
    """Đứng thay `QSessionManager` (không dựng được từ Python); ghi lại mọi lời gọi."""

    def __init__(self) -> None:
        self.called: list[str] = []

    def __getattr__(self, name):
        def method(*args, **kwargs):
            self.called.append(name)
            return True

        return method


@pytest.fixture
def commit_data_slots(monkeypatch):
    """Ghi lại các slot nối vào `commitDataRequest` (phát tín hiệu với `None` làm sập PySide)."""
    from PySide6.QtCore import SignalInstance

    real = SignalInstance.connect
    slots: list = []

    def connect(self, slot, *args, **kwargs):
        if "commitDataRequest" in str(self):
            slots.append(slot)
        return real(self, slot, *args, **kwargs)

    monkeypatch.setattr(SignalInstance, "connect", connect)
    return slots


def test_commit_data_request_closes_box_and_next_quit_does_not_ask(
    gui, gui_wait, config_dir, commit_data_slots
):
    """Qua `main()` (nối tín hiệu ở đâu cũng bắt được): đang hỏi mà Windows tắt phiên → hộp đóng,
    “Thoát” sau đó không hỏi, không bao giờ `cancel()`."""
    d = config_dir("A", identity=False)
    manager = FakeSessionManager()
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.trays and run.windows, 10, "có khay và cửa sổ")
        controller = run.tray.parent()
        add_send_row(controller)
        tray_action(run, QUIT_YES).trigger()
        yield gui_wait(lambda: len(quit_boxes()) == 1, 3, "hộp xác nhận")
        seen["slots"] = len(commit_data_slots)
        assert commit_data_slots, "không có slot nào nối vào commitDataRequest"
        for slot in commit_data_slots:
            slot(manager)
        yield gui_wait(lambda: not quit_boxes(), 3, "hộp xác nhận đóng khi phiên kết thúc")
        seen["quit_on_close"] = controller.quitting
        tray_action(run, QUIT_YES).trigger()
        seen["box_after"] = len(quit_boxes())
        seen["quitting"] = controller.quitting

    run = gui(["--config-dir", str(d)], script, timeout=20)
    assert run.code == 0
    assert not seen["quit_on_close"], "đóng hộp vì phiên kết thúc không được tự thoát"
    assert seen["box_after"] == 0 and seen["quitting"], "phiên đang kết thúc: Thoát không hỏi"
    assert "cancel" not in manager.called, "không bao giờ QSessionManager.cancel()"


def test_tray_quit_with_active_send_asks_then_quit_button_exits(gui, gui_wait, config_dir):
    d = config_dir("A", identity=False)
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.trays and run.windows, 10, "có khay và cửa sổ")
        controller = run.tray.parent()
        add_send_row(controller)
        tray_action(run, QUIT_YES).trigger()
        yield gui_wait(lambda: len(quit_boxes()) == 1, 3, "hộp xác nhận")
        seen["quitting"] = controller.quitting
        box_button(quit_boxes()[0], QUIT_YES).click()

    run = gui(["--config-dir", str(d)], script, timeout=20)
    assert seen["quitting"] is False
    assert run.code == 0


def test_close_window_without_tray_with_active_send_asks(gui, gui_wait, config_dir):
    d = config_dir("A", identity=False)
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and run.window.isVisible(), 10, "cửa sổ hiện")
        controller = run.trays[-1].parent()
        add_send_row(controller)
        run.window.close()
        yield gui_wait(lambda: len(quit_boxes()) == 1, 3, "hộp xác nhận")
        seen["quitting"] = controller.quitting
        box_button(quit_boxes()[0], QUIT_YES).click()

    run = gui(["--config-dir", str(d)], script, tray_available=False, timeout=20)
    assert seen["quitting"] is False
    assert run.code == 0


def test_sigint_quits_without_asking_even_with_active_send(gui, gui_wait, config_dir, monkeypatch):
    """Ctrl+C → `request_quit(confirm=False)`: còn lượt gửi dở vẫn thoát, không mở hộp nào. Nếu hỏi lại
    thì app không thoát và watchdog của `gui` báo lỗi."""
    from PySide6.QtWidgets import QMessageBox

    opened: list = []
    real_open = QMessageBox.open

    def spy_open(self, *args):
        opened.append(self)
        return real_open(self, *args)

    monkeypatch.setattr(QMessageBox, "open", spy_open)
    d = config_dir("A", identity=False)
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.trays and run.windows, 10, "có khay và cửa sổ")
        controller = run.tray.parent()
        seen["controller"] = controller
        add_send_row(controller)
        seen["sends"] = controller.transfers.active_sends()
        signal.raise_signal(signal.SIGINT)
        # Luồng thoát xong thì `main` trả về ngay: kịch bản không chạy tới cuối.
        yield gui_wait(lambda: False, 15, "main phải trả về sau Ctrl+C")

    run = gui(["--config-dir", str(d)], script, timeout=20, require_script_done=False)
    assert seen["sends"] == [PEER]
    assert seen["controller"].quitting
    assert opened == [], "Ctrl+C ở cửa sổ dòng lệnh không hỏi"
    assert run.code == 0


# =================================================================================================
# B5. Khay (tiêu chí 4, 5)
# =================================================================================================


def test_tray_menu_shows_four_actions_send_and_pause_follow_running(qapp):
    """Spec D4: cả bốn mục đều hiện; “Gửi file…” và “Tạm dừng nhận” chỉ bật khi node đang chạy."""
    from teleport.ui.tray import Tray

    tray = Tray()
    try:
        actions = tray.actions()
        assert len(actions) == 4
        texts = [plain(a.text()) for a in actions]
        assert texts[0] == OPEN and texts[3] == QUIT_YES
        assert [a.isVisible() for a in actions] == [True, True, True, True]
        assert [a.isEnabled() for a in actions] == [True, False, False, True]
        assert actions[1] is tray.send_menu.menuAction()
        assert actions[2].isCheckable()
        tray.set_running(True)
        assert [a.isEnabled() for a in actions] == [True, True, True, True]
        tray.set_running(False)
        assert [a.isEnabled() for a in actions] == [True, False, False, True]
    finally:
        tray.dispose()


def test_tray_message_clicked_emits_folder_of_last_message(qtbot, fake_tray_icon, tmp_path):
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.ui.tray import Tray

    tray = Tray()
    try:
        tray.show()
        got: list = []
        tray.message_clicked.connect(got.append)
        icon = tray.findChild(QSystemTrayIcon)
        tray.show_message("Đã nhận a.txt từ PC-Nha.", folder=tmp_path / "nhan")
        icon.messageClicked.emit()
        tray.show_message("Có file đang chờ bạn nhận.")
        icon.messageClicked.emit()
        assert got == [tmp_path / "nhan", None]
    finally:
        tray.dispose()


def test_tray_message_not_shown_does_not_change_remembered_folder(qtbot, fake_tray_icon, tmp_path):
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.ui.tray import Tray

    tray = Tray()
    try:
        tray.show()
        got: list = []
        tray.message_clicked.connect(got.append)
        tray.show_message("Đã nhận a.txt từ PC-Nha.", folder=tmp_path / "mot")
        tray.hide()
        tray.show_message("Đã nhận b.txt từ PC-Nha.", folder=tmp_path / "hai")  # không hiện được
        tray.findChild(QSystemTrayIcon).messageClicked.emit()
        assert got == [tmp_path / "mot"]
        assert len(fake_tray_icon.messages) == 1
    finally:
        tray.dispose()


@pytest.fixture
def opened_urls(monkeypatch):
    from teleport.ui import app as ui_app

    urls: list = []
    monkeypatch.setattr(ui_app, "open_url", lambda url: urls.append(url) or True)
    return urls


def click_message(controller) -> None:
    from PySide6.QtWidgets import QSystemTrayIcon

    controller.tray.findChild(QSystemTrayIcon).messageClicked.emit()


def received_with_file_done(controller, saved: Path) -> None:
    key = tkey("receive")
    controller.transfers.on_node_event(online())
    controller.transfers.on_transfer(offer(key, auto=True))
    controller.transfers.on_transfer(file_done(key, saved))
    controller.transfers.on_transfer(finished(key, "done"))


def test_click_received_message_opens_parent_folder_of_saved_file(
    gapp, opened_urls, fake_tray_icon, tmp_path
):
    gapp.transfers.attach(fake_host(tmp_path / "nhan"))
    saved = tmp_path / "nhan" / "thu-muc-con" / "video (1).mp4"
    received_with_file_done(gapp, saved)
    assert any(body.startswith("Đã nhận") for _t, body in fake_tray_icon.messages), fake_tray_icon.messages
    click_message(gapp)
    assert len(opened_urls) == 1
    assert opened_urls[0].isLocalFile()
    assert Path(opened_urls[0].toLocalFile()) == saved.parent


def test_click_received_message_without_file_done_opens_receive_dir(
    gapp, opened_urls, fake_tray_icon, tmp_path
):
    receive_dir = tmp_path / "nhan-cua-host"
    gapp.transfers.attach(fake_host(receive_dir))
    key = tkey("receive")
    gapp.transfers.on_node_event(online())
    gapp.transfers.on_transfer(offer(key, auto=True))
    gapp.transfers.on_transfer(finished(key, "done"))
    click_message(gapp)
    assert [Path(u.toLocalFile()) for u in opened_urls] == [receive_dir]


def test_click_other_message_brings_window_and_raises_offer_box(gapp, opened_urls, monkeypatch, qtbot):
    from PySide6.QtWidgets import QApplication, QDialog

    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    key = tkey("receive")
    gapp.transfers.on_transfer(offer(key))  # app không active → bóng thoại “Có file đang chờ…”
    box = gapp.transfers.offers.box(key)
    assert box is not None and box.isVisible()
    gapp.window.hide()
    raised: list = []
    real_raise = QDialog.raise_

    def spy_raise(self):
        raised.append(self)
        return real_raise(self)

    monkeypatch.setattr(QDialog, "raise_", spy_raise)
    click_message(gapp)
    assert opened_urls == [], "bóng thoại không có thư mục: không mở thư mục"
    assert gapp.window.isVisible(), "cửa sổ chính hiện lại"
    assert box in raised, "hộp offer đang mở phải được đưa lên trước"


def test_click_after_newer_message_without_folder_does_not_open_old_folder(
    gapp, opened_urls, monkeypatch, tmp_path
):
    from PySide6.QtWidgets import QApplication

    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: None))
    gapp.transfers.attach(fake_host(tmp_path / "nhan"))
    received_with_file_done(gapp, tmp_path / "nhan" / "a.txt")
    gapp.transfers.on_transfer(offer(tkey("receive")))  # bóng thoại mới, không thư mục
    click_message(gapp)
    assert opened_urls == []


def test_click_message_while_quitting_is_ignored(gapp, opened_urls, tmp_path):
    gapp.transfers.attach(fake_host(tmp_path / "nhan"))
    received_with_file_done(gapp, tmp_path / "nhan" / "a.txt")
    gapp.request_quit(confirm=False)
    click_message(gapp)
    assert opened_urls == []
    assert not gapp.window.isVisible()


def test_open_url_seam_defaults_to_qdesktopservices():
    from PySide6.QtGui import QDesktopServices

    from teleport.ui import app as ui_app

    assert ui_app.open_url is QDesktopServices.openUrl or ui_app.open_url == QDesktopServices.openUrl


# =================================================================================================
# B5. Bóng thoại chỉ khi app không được dùng (tiêu chí 6)
# =================================================================================================


def test_offer_when_app_active_has_no_tray_message(ctl_env):
    ns = ctl_env(app_active=lambda: True)
    ns.ctl.on_transfer(offer(tkey("receive")))
    assert OFFER_WAITING not in ns.messages


def test_offer_when_app_not_active_shows_tray_message(ctl_env):
    ns = ctl_env(app_active=lambda: False)
    ns.ctl.on_transfer(offer(tkey("receive")))
    assert OFFER_WAITING in ns.messages


def test_app_active_is_read_before_offer_box_opens(ctl_env):
    """Hộp offer mới mở có thể giành active: phải hỏi `app_active` trước khi mở hộp."""
    state: dict = {}

    def app_active() -> bool:
        state.setdefault("open_boxes", len(ns.ctl.offers.keys()))
        return len(ns.ctl.offers.keys()) > 0  # “active” chỉ vì hộp vừa mở

    ns = ctl_env(app_active=app_active)
    ns.ctl.on_transfer(offer(tkey("receive")))
    assert state.get("open_boxes") == 0
    assert OFFER_WAITING in ns.messages


def test_received_message_shows_even_when_app_active(ctl_env):
    ns = ctl_env(app_active=lambda: True)
    key = tkey("receive")
    ns.ctl.on_node_event(online())
    ns.ctl.on_transfer(offer(key, auto=True))
    ns.ctl.on_transfer(finished(key, "done"))
    assert any(m.startswith("Đã nhận") for m in ns.messages), ns.messages


def test_received_message_carries_reveal_of_saved_file(ctl_env, tmp_path):
    """Spec-f4 mục 2.4/2.5: bóng thoại mang `shell.Reveal` (file đã lưu + thư mục nhận), không còn `Path`
    thư mục cha."""
    from teleport.ui.shell import Reveal

    ns = ctl_env(app_active=lambda: True)
    key = tkey("receive")
    saved = tmp_path / "nhan" / "con" / "a (1).txt"
    ns.ctl.on_node_event(online())
    ns.ctl.on_transfer(offer(key, auto=True, names=("a.txt",)))
    ns.ctl.on_transfer(file_done(key, saved, "a.txt"))
    ns.ctl.on_transfer(finished(key, "done", names=("a.txt",)))
    [folder] = [f for m, f in zip(ns.messages, ns.folders, strict=True) if m.startswith("Đã nhận")]
    assert isinstance(folder, Reveal)
    assert tuple(folder.files) == (saved,)
    assert folder.root == tmp_path / "nhan"


@pytest.mark.parametrize("active", [True, False])
def test_default_app_active_follows_qapplication_active_window(ctl_env, monkeypatch, active):
    from PySide6.QtWidgets import QApplication

    ns = ctl_env()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: ns.window if active else None))
    ns.ctl.on_transfer(offer(tkey("receive")))
    assert (OFFER_WAITING in ns.messages) is (not active)


@pytest.mark.parametrize("active", [True, False])
def test_gui_app_offer_message_follows_app_active_seam(gapp, fake_tray_icon, monkeypatch, active):
    """GuiApp truyền `_app_active` cho TransfersController: active → không bóng thoại offer."""
    from teleport.ui.app import GuiApp

    monkeypatch.setattr(GuiApp, "_app_active", lambda self: active)
    gapp.transfers.on_transfer(offer(tkey("receive")))
    shown = [body for _t, body in fake_tray_icon.messages if body == OFFER_WAITING]
    assert bool(shown) is (not active), fake_tray_icon.messages


@pytest.mark.parametrize("active", [True, False])
def test_transfers_default_app_active_seam_is_read_at_call_time(ctl_env, monkeypatch, active):
    from teleport.ui import transfers as mod

    ns = ctl_env()
    monkeypatch.setattr(mod, "default_app_active", lambda: active)
    ns.ctl.on_transfer(offer(tkey("receive")))
    assert (OFFER_WAITING in ns.messages) is (not active)


class PairingHost:
    """Host giả cho `PairingController.set_host`: chỉ cần hai tín hiệu ghép đôi."""

    def __new__(cls):
        from PySide6.QtCore import QObject, Signal

        class _Host(QObject):
            pairing_prompt = Signal(object)
            pairing_finished = Signal(object)

            def call(self, fn, on_done=None):
                pass

            def submit(self, fn, on_done=None):
                return SimpleNamespace(cancel=lambda: None, done=False)

        return _Host()


@pytest.mark.parametrize("active", [True, False])
def test_pairing_request_notifies_only_when_app_not_active(gapp, fake_tray_icon, monkeypatch, qtbot, active):
    """Cửa sổ chính đang hiện nhưng app không active (bị che) vẫn phải có bóng thoại ghép đôi."""
    from PySide6.QtWidgets import QApplication

    assert gapp.window.isVisible()
    monkeypatch.setattr(QApplication, "activeWindow", staticmethod(lambda: gapp.window if active else None))
    host = PairingHost()
    gapp.pairing.set_host(host)
    host.pairing_prompt.emit(pair_prompt())
    qtbot.waitUntil(lambda: gapp.pairing.dialog(7) is not None, timeout=2_000)
    notes = [body for _t, body in fake_tray_icon.messages if PAIR_NOTE in body]
    assert bool(notes) is (not active), fake_tray_icon.messages
    gapp.pairing.close_all()
