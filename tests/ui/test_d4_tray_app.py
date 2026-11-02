"""Khay nối vào `GuiApp` (spec D4 mục 4.1–4.3, mục 12 A1, A4–A8, mục 14 thắng).

Viết từ spec, không từ code. Hai cách dựng:

- `GuiApp` dựng thẳng (fixture `gapp`, như `test_quit_tray_address.py`): máy chưa có danh tính, không
  node, không socket. Dùng cho hàm cung cấp danh sách máy của menu con (14.1), đường “Gửi file…” → B3
  (A7) với host giả gắn vào `TransfersController`, và ca “chưa có host” của tạm dừng nhận.
- `main()` trong tiến trình (fixture `gui`), node thật trên 127.0.0.1 → `integration`. Để kiểm thứ tự kết
  quả (14.10) và ca lỗi, test **chặn** đúng lời `NodeHost.call` mà cú bấm “Tạm dừng nhận” sinh ra (vá
  `NodeHost.call` trong khoảng một lệnh `trigger()` đồng bộ), chạy `fn` trên node giả để biết app định gọi
  gì, rồi tự trả kết quả về `on_done` theo thứ tự test chọn.

Phủ: A1 (bật/tắt theo `running` ở app), A4, A5 (gui + integration + slow, 14.19), A6, A7, A8, 14.10, 14.12.

Giả định API (theo spec, mục 4.2/14): `Tray.state`, `Tray.badge`, `Tray.tooltip()`, `Tray.send_menu`,
`Tray.actions()[2]` là “Tạm dừng nhận”; `MainWindow.badge` là huy hiệu thẻ máy này (đã có); GuiApp là cha
của `Tray` (đã có).
"""

from __future__ import annotations

import contextlib
import logging
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

integration = pytest.mark.integration

LOCAL = "127.0.0.1"
PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
THIRD_ID = "5c5c5c5c" + "2" * 24

PAUSED_BADGE = "Đã tạm dừng nhận"
READY_BADGE = "Sẵn sàng nhận"
TIP_PAUSED = "Đã tạm dừng nhận file mới"
TIP_ACTIVE = "Đang truyền {n} lượt"
TIP_UNAVAILABLE = "Không nhận file: không mở được thư mục nhận"
PICK_TITLE = "Chọn file gửi tới {name}"
PREPARING = "Đang chuẩn bị…"
OFFLINE = "{name} (ngoại tuyến)"
NO_PAIRED = "Chưa ghép đôi với máy nào"
FIND = "Tìm máy mới…"
HIDDEN_PAUSED_VI = (
    "Teleport vẫn chạy ở khay hệ thống nhưng đang tạm dừng nhận file mới và clipboard. "
    "Chọn Thoát trong menu khay để tắt hẳn."
)
HIDDEN_PAUSED_EN_PART = "paused receiving new files"
NOT_RECEIVING_VI = (
    "{name} đang không nhận file mới (có thể đã tạm dừng nhận, hoặc chưa mở được thư mục nhận). "
    "Hãy nhờ bật lại việc nhận file trên máy đó rồi gửi lại."
)


# =================================================================================================
# Dữ liệu giả
# =================================================================================================


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def dview(device_id: str, name: str, *, online: bool = True, connected: bool = False, paired: bool = True):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=paired,
        online=online,
        connected=connected,
        addresses=("192.0.2.7",) if online else (),
        port=47474 if online else None,
    )


def tkey(direction: str = "receive", device_id: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), uuid.uuid4().hex)


def tinfo(key, status: str = "transferring"):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    return TransferInfo(
        key=key,
        status=TransferStatus(status),
        files=(FileEntry("video.mp4", 1000, 0),),
        names=("video.mp4",),
        file_index=0,
        done_bytes=0,
        total_bytes=1000,
    )


def changed(key, status: str = "transferring"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(tinfo(key, status))


def finished(key, result: str = "done"):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=tinfo(key, "verifying"),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=None,
        reject=None,
    )


class FakeHost:
    """Host tối thiểu cho `TransfersController.attach`: ghi lại `call`/`submit`, không chạy gì."""

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

    def submit(self, fn, on_done=None):
        self.submits.append((fn, on_done))
        return SimpleNamespace(cancel=lambda: None, done=False)


class FakePauseTransfers:
    """`node.transfers` giả: ghi lại `pause_receiving` và thread gọi."""

    def __init__(self) -> None:
        self.calls: list[bool] = []
        self._paused = False

    def pause_receiving(self, paused: bool) -> None:
        self.calls.append(paused)
        self._paused = paused

    @property
    def receiving_paused(self) -> bool:
        return self._paused


def send_items(tray, *, main: bool = False) -> list:
    if main:
        tray.menu.aboutToShow.emit()
    else:
        tray.send_menu.aboutToShow.emit()
    return [a for a in tray.send_menu.actions() if not a.isSeparator()]


def pause_action(tray):
    return tray.actions()[2]


# =================================================================================================
# Fixture không node
# =================================================================================================


@pytest.fixture
def fake_tray_icon(monkeypatch):
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.ui import tray

    shown: dict[int, bool] = {}
    messages: list[tuple[str, str]] = []
    monkeypatch.setattr(tray, "is_available", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.__setitem__(id(self), True))
    monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: shown.__setitem__(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "setVisible", lambda self, v: shown.__setitem__(id(self), bool(v)))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: shown.get(id(self), False))
    monkeypatch.setattr(
        QSystemTrayIcon, "showMessage", lambda self, *a, **k: messages.append((str(a[0]), str(a[1])))
    )
    return SimpleNamespace(messages=messages)


@pytest.fixture
def offers_as_boxes(monkeypatch):
    """spec-b4 11.3: đang nhìn đúng luồng của máy gửi thì lời mời chỉ ở bong bóng; test chờ hộp hỏi
    vá `ui.transfers.default_window_active` thành False để hộp luôn bật."""
    from teleport.ui import transfers

    monkeypatch.setattr(transfers, "default_window_active", lambda: False)


@pytest.fixture
def no_exec(monkeypatch):
    from PySide6.QtWidgets import QDialog, QMessageBox

    calls: list[str] = []

    def fake(self, *args, **kwargs):
        calls.append(type(self).__name__)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake)
    monkeypatch.setattr(QDialog, "exec", fake)
    return calls


@pytest.fixture
def gapp(qapp, qtbot, config_dir, fake_tray_icon, no_exec):
    """`GuiApp` dựng thẳng, không node (máy chưa có danh tính, không gọi `start()`); khay hiện."""
    from teleport.ui.app import GuiApp

    controller = GuiApp(qapp, config_dir("A", identity=False))
    controller.tray.show()
    yield controller
    with contextlib.suppress(Exception):
        controller.shutdown()
    with contextlib.suppress(Exception):
        controller.window.hide()
        controller.window.deleteLater()
    qapp.processEvents()


class FileDialogs:
    """Seam `teleport.ui.transfers.file_dialog_factory`: hộp con không mở thật, ghi lại `open()`."""

    def __init__(self) -> None:
        self.made: list = []

    def factory(self, parent=None, *args, **kwargs):
        from PySide6.QtWidgets import QFileDialog

        made = self.made

        class FakeDialog(QFileDialog):
            def __init__(self) -> None:
                super().__init__(parent)
                self.opened = 0
                made.append(self)

            def open(self, *a, **k):
                self.opened += 1

            def exec(self, *a, **k):
                raise AssertionError("hộp chọn file không được exec()")

        return FakeDialog()


@pytest.fixture
def file_dialogs(monkeypatch):
    from teleport.ui import transfers as mod

    d = FileDialogs()
    monkeypatch.setattr(mod, "file_dialog_factory", d.factory)
    return d


# =================================================================================================
# A1, 14.20 (không node): WELCOME thì hai mục giữa tắt
# =================================================================================================


def test_welcome_state_send_and_pause_shown_but_disabled(gapp):
    actions = gapp.tray.actions()
    assert len(actions) == 4
    assert all(a.isVisible() for a in actions)
    assert [a.isEnabled() for a in actions] == [True, False, False, True]
    assert gapp.tray.state.running is False


# =================================================================================================
# 14.1, A7: danh sách máy của menu con lấy từ cuộc trò chuyện
# =================================================================================================


def test_send_menu_lists_paired_devices_in_conversation_order(gapp):
    from teleport.ui import texts

    gapp.window.devices.reset(
        [
            dview(PEER_ID, "Zeta", online=True),
            dview(OTHER_ID, "Alpha", online=False),
            dview(THIRD_ID, "Beta & Co", online=False, connected=True),  # 14.1: connected = trực tuyến
            dview("9" * 32, "Chua-ghep", online=True, paired=False),
        ]
    )
    order = [v.device_id for v in gapp.window.conversations.model.devices()]
    items = send_items(gapp.tray)
    names = {PEER_ID: "Zeta", OTHER_ID: "Alpha", THIRD_ID: "Beta & Co"}
    assert order and "9" * 32 not in order
    expected = []
    for device_id in order:
        label = texts.peer_label(names[device_id], device_id)
        if device_id == OTHER_ID:
            label = texts.fill(OFFLINE, name=label)
        expected.append(label.replace("&", "&&"))
    assert [a.text() for a in items] == expected
    assert order != [PEER_ID, OTHER_ID, THIRD_ID], (
        "dữ liệu thử phải làm thứ tự cuộc trò chuyện khác thứ tự nạp"
    )


def test_send_menu_is_read_again_each_time(gapp):
    gapp.window.devices.reset([dview(PEER_ID, "PC-Nha")])
    assert [plain(a.text()) for a in send_items(gapp.tray)] == ["PC-Nha"]
    gapp.window.devices.reset([dview(PEER_ID, "PC-Nha"), dview(OTHER_ID, "Laptop", online=False)])
    items = send_items(gapp.tray, main=True)
    assert len(items) == 2
    gapp.window.devices.reset([])
    assert [plain(a.text()) for a in send_items(gapp.tray)] == [NO_PAIRED, FIND]


def test_tray_send_opens_window_selects_conversation_and_file_dialog(gapp, file_dialogs, qtbot, tmp_path):
    """A7: chọn máy → cửa sổ hiện → cuộc của máy đó được chọn → hộp “Chọn file gửi tới X” (qua seam);
    chọn file → bong bóng “Đang chuẩn bị…” (đường gửi B3)."""
    from teleport.ui import texts
    from teleport.ui.main_window import Page

    host = FakeHost(tmp_path / "nhan")
    gapp.transfers.attach(host)
    gapp.window.devices.reset([dview(PEER_ID, "PC-Nha"), dview(OTHER_ID, "Laptop", online=False)])
    gapp.window.hide()
    items = send_items(gapp.tray)
    [laptop] = [a for a in items if "Laptop" in a.text()]
    laptop.trigger()
    qtbot.waitUntil(lambda: len(file_dialogs.made) == 1, timeout=2000)
    assert gapp.window.isVisible(), "cửa sổ lên trước để mọi phản hồi của B3 thấy được"
    assert gapp.window.current_page is Page.HOME
    current = gapp.window.conversations.current_device()
    assert current is not None and current.device_id == OTHER_ID
    dialog = file_dialogs.made[0]
    assert dialog.opened == 1
    assert dialog.windowTitle() == PICK_TITLE.format(name=texts.peer_label("Laptop", OTHER_ID))
    src = tmp_path / "nguon.bin"
    dialog.filesSelected.emit([str(src)])
    qtbot.waitUntil(lambda: len(gapp.transfers.view.pending_bubbles()) == 1, timeout=2000)
    assert len(host.submits) == 1, "máy ngoại tuyến vẫn tạo được lượt gửi"


def test_tray_send_to_device_gone_only_shows_window(gapp, file_dialogs, qtbot):
    """`open_conversation` trả False (máy vừa bị hủy ghép đôi) → chỉ hiện cửa sổ, không mở hộp chọn file."""
    gapp.window.devices.reset([dview(PEER_ID, "PC-Nha")])
    [item] = send_items(gapp.tray)
    gapp.window.devices.reset([])
    gapp.window.hide()
    item.trigger()
    qtbot.wait(50)
    assert gapp.window.isVisible()
    assert file_dialogs.made == []


def test_activity_count_reaches_tray(gapp):
    """`_update_summary` gọi thêm `tray.set_activity(view.active_count())`."""
    k1, k2 = tkey("receive"), tkey("send", OTHER_ID)
    gapp.transfers.on_transfer(changed(k1))
    assert gapp.tray.state.active == 1
    gapp.transfers.on_transfer(changed(k2))
    assert gapp.tray.state.active == 2
    gapp.transfers.on_transfer(finished(k1, "done"))
    assert gapp.tray.state.active == 1
    assert gapp.tray.state.active == gapp.transfers.view.active_count()


# =================================================================================================
# 4.3: tạm dừng khi chưa có host
# =================================================================================================


def test_pause_without_started_host_returns_check_to_old_value(gapp, qtbot):
    pause = pause_action(gapp.tray)
    pause.setChecked(True)  # như người dùng vừa bấm
    gapp.tray.pause_toggled.emit(True)
    qtbot.wait(20)
    assert not pause.isChecked(), "không có host đã started: trả dấu chọn về giá trị cũ"
    assert gapp.tray.state.paused is False


def test_window_set_receiving_paused_exists_and_sets_badge_only_when_running(qtbot, tmp_path):
    """14.8: `MainWindow.set_receiving_paused` → thẻ máy này + `compact_machine`."""
    from teleport.ui.main_window import MainWindow
    from teleport.ui.widgets import BadgeTone

    w = MainWindow()
    qtbot.addWidget(w)
    rd = tmp_path / "nhan"
    rd.mkdir()
    w.show_running("May-A", rd)
    w.set_receiving_paused(True)
    assert (w.badge.text, w.badge.tone) == (PAUSED_BADGE, BadgeTone.WARNING)
    assert PAUSED_BADGE in w.compact_machine.accessibleDescription()
    w.set_receiving_paused(False)
    assert w.badge.text == READY_BADGE
    assert PAUSED_BADGE not in w.compact_machine.accessibleDescription()


# =================================================================================================
# Node thật: hàm phụ trợ
# =================================================================================================


def app_of(run):
    app = run.tray.parent()
    assert app is not None and hasattr(app, "transfers"), "GuiApp là cha của Tray"
    return app


def wait_running(run, gui_wait):
    from teleport.ui.main_window import ViewState

    yield gui_wait(
        lambda: run.windows and run.hosts and run.host.running and run.window.view_state is ViewState.RUNNING,
        20,
        "node chạy, cửa sổ RUNNING",
    )


def quit_now(run) -> None:
    run.tray.actions()[3].trigger()


class CallTrap:
    """Chặn mọi `NodeHost.call` trong khối `with` (khối phải đồng bộ: một `trigger()`)."""

    def __init__(self) -> None:
        self.calls: list = []

    @contextlib.contextmanager
    def catching(self):
        from teleport.ui import bridge

        real = bridge.NodeHost.call
        start = len(self.calls)

        def trap(host, fn, on_done=None):
            self.calls.append(SimpleNamespace(host=host, fn=fn, on_done=on_done))

        bridge.NodeHost.call = trap
        try:
            yield
        finally:
            bridge.NodeHost.call = real
        self.last_new = self.calls[start:]


def run_on_fake_node(captured):
    """Chạy `fn` của một lời `call` đã chặn trên node giả; trả (kết quả, các lần `pause_receiving`)."""
    transfers = FakePauseTransfers()
    result = captured.fn(SimpleNamespace(transfers=transfers))
    return result, transfers.calls


def node_value(run, fn, gui_wait, out: list):
    run.host.call(fn, out.append)
    yield gui_wait(lambda: out, 5, "đọc giá trị trên node")


# =================================================================================================
# A1, A6 với node thật
# =================================================================================================


@integration
def test_running_enables_items_and_quit_resets_state(gui, gui_wait, config_dir):
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        seen["running"] = t.state.running
        seen["enabled"] = [a.isEnabled() for a in t.actions()]
        seen["len"] = len(t.actions())
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "node xác nhận tạm dừng")
        quit_now(run)
        seen["after_quit"] = (t.state.paused, t.state.running, pause_action(t).isChecked())

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["running"] is True
    assert seen["len"] == 4
    assert seen["enabled"] == [True, True, True, True]
    assert seen["after_quit"] == (False, False, False), "Thoát: paused False, running False"


@integration
def test_start_failed_resets_paused_and_running(gui, gui_wait, config_dir):
    """A6: `start_failed` → paused False, running False, hai mục giữa tắt. Giả `start_failed` bằng cách
    phát chính signal của host hiện tại sau khi đã tạm dừng (không có cách thật để node đang chạy rồi lỗi
    khởi động)."""
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "node xác nhận tạm dừng")
        run.host.start_failed.emit("other", "")
        yield
        seen["state"] = (t.state.paused, t.state.running)
        seen["check"] = pause_action(t).isChecked()
        seen["enabled"] = [a.isEnabled() for a in t.actions()]
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["state"] == (False, False)
    assert seen["check"] is False
    assert seen["enabled"] == [True, False, False, True]


@integration
def test_new_host_after_locked_error_runs_unpaused(gui, gui_wait, config_dir, fast_lock):
    """A6: lỗi khởi động (node.lock bị giữ) → running False; Thử lại → host mới, running True, không tạm
    dừng (trên cả khay lẫn node)."""
    from teleport.lock import NodeLock
    from teleport.ui.main_window import ViewState

    d = config_dir("A")
    holder = NodeLock(d, "node.lock")
    holder.acquire()
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and run.window.view_state is ViewState.ERROR, 15, "màn lỗi")
        t = run.tray
        seen["error"] = (t.state.running, [a.isEnabled() for a in t.actions()])
        holder.release()
        app_of(run).window.retry_requested.emit()
        yield gui_wait(lambda: len(run.hosts) >= 2 and run.host.running, 15, "host mới chạy")
        yield gui_wait(lambda: t.state.running, 5, "khay biết node đang chạy")
        got: list = []
        yield from node_value(run, lambda node: node.transfers.receiving_paused, gui_wait, got)
        seen["new"] = (t.state.running, t.state.paused, pause_action(t).isChecked(), got[0])
        quit_now(run)

    try:
        run = gui(["--config-dir", str(d)], script)
    finally:
        with contextlib.suppress(Exception):
            holder.release()
    assert run.code == 0
    assert seen["error"] == (False, [True, False, False, True])
    assert seen["new"] == (True, False, False, False)


# =================================================================================================
# A4 với node thật
# =================================================================================================


@integration
def test_pause_runs_on_node_thread_then_badges_follow_and_unpause_restores(
    gui, gui_wait, config_dir, monkeypatch
):
    from teleport.app.transfers import TransferManager
    from teleport.ui.tray import TrayBadge
    from teleport.ui.widgets import BadgeTone

    threads: list[tuple[bool, str]] = []
    real = TransferManager.pause_receiving

    def spy(self, paused):
        threads.append((paused, threading.current_thread().name))
        return real(self, paused)

    monkeypatch.setattr(TransferManager, "pause_receiving", spy)
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t, w = run.tray, run.window
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "node xác nhận tạm dừng")
        got: list = []
        yield from node_value(run, lambda node: node.transfers.receiving_paused, gui_wait, got)
        seen["paused"] = (
            got[0],
            pause_action(t).isChecked(),
            t.badge,
            TIP_PAUSED in t.tooltip(),
            (w.badge.text, w.badge.tone),
        )
        pause_action(t).trigger()
        yield gui_wait(lambda: not t.state.paused, 5, "node xác nhận nhận lại")
        got2: list = []
        yield from node_value(run, lambda node: node.transfers.receiving_paused, gui_wait, got2)
        seen["resumed"] = (
            got2[0],
            pause_action(t).isChecked(),
            t.badge,
            w.badge.text,
            TIP_PAUSED in t.tooltip(),
        )
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["paused"] == (True, True, TrayBadge.PAUSED, True, (PAUSED_BADGE, BadgeTone.WARNING))
    assert seen["resumed"] == (False, False, TrayBadge.NONE, READY_BADGE, False)
    assert [p for p, _ in threads] == [True, False], "mỗi lần bấm đúng một pause_receiving"
    main_name = threading.main_thread().name
    assert all(name != main_name for _, name in threads), (
        f"pause_receiving phải chạy trên thread node: {threads}"
    )


@integration
def test_pause_click_makes_one_call_and_state_changes_only_on_confirmation(gui, gui_wait, config_dir):
    """A4 + 14.10: một `host.call`; `fn` gọi `pause_receiving(True)` và trả `receiving_paused`; dấu chọn
    đổi ngay, còn `state.paused` / dấu biểu tượng / huy hiệu chỉ đổi khi `on_done` trả về."""
    from teleport.ui.tray import TrayBadge

    d = config_dir("A")
    trap = CallTrap()
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t, w = run.tray, run.window
        with trap.catching():
            pause_action(t).trigger()
        seen["calls"] = len(trap.last_new)
        [c] = trap.last_new
        seen["host_is_current"] = c.host is run.host
        seen["before"] = (pause_action(t).isChecked(), t.state.paused, t.badge, w.badge.text)
        result, pause_calls = run_on_fake_node(c)
        seen["fn"] = (result, pause_calls)
        c.on_done(True)
        seen["after"] = (pause_action(t).isChecked(), t.state.paused, t.badge, w.badge.text)
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["calls"] == 1 and seen["host_is_current"]
    assert seen["fn"] == (True, [True])
    assert seen["before"] == (True, False, TrayBadge.NONE, READY_BADGE)
    assert seen["after"] == (True, True, TrayBadge.PAUSED, PAUSED_BADGE)


@integration
def test_pause_error_restores_confirmed_value_and_logs_one_warning(gui, gui_wait, config_dir, caplog):
    d = config_dir("A")
    trap = CallTrap()
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        with trap.catching():
            pause_action(t).trigger()
        [c] = trap.last_new
        start = len(caplog.records)
        c.on_done(RuntimeError("bi-mat-khong-vao-log"))
        yield
        records = caplog.records[start:]
        seen["warnings"] = [r.getMessage() for r in records if r.levelno == logging.WARNING]
        seen["state"] = (pause_action(t).isChecked(), t.state.paused)
        # Lỗi sau một lần đã xác nhận: áp lại giá trị đã xác nhận (True).
        with trap.catching():
            pause_action(t).trigger()  # → True
        [c2] = trap.last_new
        c2.on_done(True)
        with trap.catching():
            pause_action(t).trigger()  # → False
        [c3] = trap.last_new
        c3.on_done(OSError("x"))
        yield
        seen["confirmed"] = (pause_action(t).isChecked(), t.state.paused)
        quit_now(run)

    with caplog.at_level(logging.WARNING):
        run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["state"] == (False, False), "lỗi: dấu chọn về giá trị đã xác nhận"
    errors = [m for m in seen["warnings"] if "RuntimeError" in m]
    assert len(errors) == 1, seen["warnings"]
    assert not any("bi-mat" in m for m in seen["warnings"]), "chỉ ghi tên loại lỗi"
    assert seen["confirmed"] == (True, True)


@integration
def test_pause_two_clicks_latest_request_wins(gui, gui_wait, config_dir):
    """14.10: kết quả của yêu cầu cũ chỉ cập nhật giá trị đã xác nhận; yêu cầu mới nhất mới áp mọi nơi."""
    from teleport.ui.tray import TrayBadge

    d = config_dir("A")
    trap = CallTrap()
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t, w = run.tray, run.window
        with trap.catching():
            pause_action(t).trigger()  # True
        with trap.catching():
            pause_action(t).trigger()  # False
        with trap.catching():
            pause_action(t).trigger()  # True
        c1, c2, c3 = trap.calls
        assert [run_on_fake_node(c)[1] for c in (c1, c2, c3)] == [[True], [False], [True]]
        c1.on_done(True)
        seen["after1"] = (pause_action(t).isChecked(), t.state.paused, t.badge)
        c2.on_done(False)
        seen["after2"] = (pause_action(t).isChecked(), t.state.paused, t.badge)
        c3.on_done(True)
        seen["after3"] = (pause_action(t).isChecked(), t.state.paused, t.badge, w.badge.text)
        # Hai lần: True rồi False; kết quả cuối (False) thắng.
        with trap.catching():
            pause_action(t).trigger()  # False
        with trap.catching():
            pause_action(t).trigger()  # True
        with trap.catching():
            pause_action(t).trigger()  # False
        c4, c5, c6 = trap.calls[3:]
        c4.on_done(False)
        c5.on_done(True)
        seen["stale"] = (pause_action(t).isChecked(), t.state.paused)
        c6.on_done(False)
        seen["final"] = (pause_action(t).isChecked(), t.state.paused, t.badge, w.badge.text)
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["after1"] == (True, False, TrayBadge.NONE), "kết quả cũ không áp lên giao diện"
    assert seen["after2"] == (True, False, TrayBadge.NONE)
    assert seen["after3"] == (True, True, TrayBadge.PAUSED, PAUSED_BADGE)
    assert seen["stale"] == (False, True), "đang chờ yêu cầu mới nhất: giữ trạng thái đã áp"
    assert seen["final"] == (False, False, TrayBadge.NONE, READY_BADGE)


# =================================================================================================
# A8 với node thật
# =================================================================================================


@integration
def test_active_transfer_shows_transferring_badge_and_tooltip(gui, gui_wait, config_dir):
    from teleport.ui.tray import TrayBadge

    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        ctl = app_of(run).transfers
        k = tkey("receive")
        ctl.on_transfer(changed(k))
        # Spec-f4 mục 2.3: lượt đang chạy thì dòng có thêm “ · {percent}%” (ở đây 0%).
        line = TIP_ACTIVE.format(n=1)
        lines = t.tooltip().split("\n")
        seen["active"] = (
            t.badge,
            t.state.active,
            any(x == line or x.startswith(line + " · ") for x in lines),
        )
        ctl.on_transfer(finished(k, "done"))
        seen["done"] = (t.badge, t.state.active)
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["active"] == (TrayBadge.TRANSFERRING, 1, True)
    assert seen["done"] == (TrayBadge.NONE, 0)


@integration
def test_broken_receive_dir_shows_unavailable_badge_and_tooltip_line(gui, gui_wait, config_dir, tmp_path):
    from teleport.app.settings import Settings
    from teleport.ui.tray import TrayBadge

    d = config_dir("A")
    broken = tmp_path / "da-luu-la-file"
    broken.write_bytes(b"khong phai thu muc")
    Settings(receive_dir=str(broken)).save(d)
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        yield gui_wait(lambda: t.state.unavailable, 5, "khay biết thư mục nhận hỏng")
        seen["state"] = (t.badge, TIP_UNAVAILABLE in t.tooltip().split("\n"))
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "tạm dừng")
        seen["both"] = (t.badge, TIP_PAUSED in t.tooltip(), TIP_UNAVAILABLE in t.tooltip())
        quit_now(run)

    run = gui(["--config-dir", str(d)], script, keep_receive_dir=True)
    assert run.code == 0
    assert seen["state"] == (TrayBadge.UNAVAILABLE, True)
    assert seen["both"] == (TrayBadge.UNAVAILABLE, False, True), "UNAVAILABLE thắng PAUSED, chỉ một dòng"


# =================================================================================================
# A7 với node thật: menu con, “Tìm máy mới…”
# =================================================================================================


@integration
def test_tray_send_to_offline_paired_device_runs_b3_send_path(
    gui, gui_wait, config_dir, trust_each_other, file_dialogs, tmp_path
):
    from teleport.ui import texts
    from teleport.ui.main_window import Page

    a, b = config_dir("A"), config_dir("B")
    _, id_b = trust_each_other(a, b, name_a="May-A", name_b="May-B")
    b_id = id_b.device_id
    src = tmp_path / "gui-di.bin"
    src.write_bytes(b"x" * 1000)
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t, w = run.tray, run.window
        yield gui_wait(lambda: w.devices.device(b_id) is not None, 5, "danh sách thiết bị có B")
        items = send_items(t)
        seen["items"] = [a.text() for a in items]
        w.hide()
        items[0].trigger()
        yield gui_wait(lambda: file_dialogs.made, 3, "hộp chọn file")
        current = w.conversations.current_device()
        seen["window"] = (w.isVisible(), w.current_page, current.device_id if current else None)
        dialog = file_dialogs.made[0]
        seen["title"] = dialog.windowTitle()
        view = app_of(run).transfers.view
        dialog.filesSelected.emit([str(src)])
        seen["pending"] = len(view.pending_bubbles())
        yield gui_wait(lambda: view.rows(), 10, "lượt gửi chờ máy B lên mạng")
        app_of(run).request_quit(confirm=False)  # còn lượt gửi dở: Thoát qua khay sẽ hỏi lại

    run = gui(["--config-dir", str(a)], script)
    label = texts.peer_label("May-B", b_id)
    assert run.code == 0
    assert seen["items"] == [texts.fill(OFFLINE, name=label).replace("&", "&&")]
    assert seen["window"] == (True, Page.HOME, b_id)
    assert seen["title"] == PICK_TITLE.format(name=label)
    assert seen["pending"] == 1, "chọn file xong hiện ngay bong bóng “Đang chuẩn bị…”"


@integration
def test_tray_find_devices_opens_discover_page(gui, gui_wait, config_dir):
    from teleport.ui.main_window import Page

    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t, w = run.tray, run.window
        items = send_items(t)
        seen["items"] = [(plain(a.text()), a.isEnabled()) for a in items]
        w.hide()
        items[-1].trigger()
        yield gui_wait(lambda: w.isVisible() and w.current_page is Page.DISCOVER, 3, "trang Tìm máy mới")
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert seen["items"] == [(NO_PAIRED, False), (FIND, True)]


# =================================================================================================
# 14.12: thu xuống khay khi đang tạm dừng
# =================================================================================================


@integration
@pytest.mark.parametrize("lang", ["vi", "en"])
def test_hidden_to_tray_while_paused_says_paused(gui, gui_wait, config_dir, monkeypatch, lang):
    from teleport.ui import i18n, texts

    monkeypatch.setattr(i18n, "system_language", lambda: lang)
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "tạm dừng")
        seen["still_running"] = texts.still_running()
        run.window.close()
        yield gui_wait(lambda: run.messages, 3, "bóng thoại thu xuống khay")
        seen["messages"] = [m for _, m in run.messages]
        quit_now(run)

    run = gui(["--config-dir", str(d)], script)
    assert run.code == 0
    assert len(seen["messages"]) == 1
    message = seen["messages"][0]
    assert message != seen["still_running"], "đang tạm dừng: không nói “vẫn nhận file”"
    if lang == "vi":
        assert message == HIDDEN_PAUSED_VI
    else:
        assert HIDDEN_PAUSED_EN_PART in message
        assert "Teleport" in message


# =================================================================================================
# A5: hai node thật (gui + integration + slow, 14.19)
# =================================================================================================


@pytest.mark.gui
@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_a5_paused_gui_rejects_then_resumed_gui_receives(
    gui, gui_wait, config_dir, trust_each_other, peer_node, tmp_path, ui_helpers
):
    """A tạm dừng qua khay, B gửi → `rejected_not_receiving` và câu 5.3 (14.14) cho B; A bỏ tạm dừng, B gửi
    lại thành công. Chỉ kiểm phía B và lần gửi lại (14.19)."""
    import asyncio

    from teleport.app.transfers import TransferResult
    from teleport.ui import texts
    from teleport.ui.transfers_view import result_message

    a, b = config_dir("A"), config_dir("B")
    id_a, _ = trust_each_other(a, b, name_a="May-A", name_b="May-B")
    a_id = id_a.device_id
    src = tmp_path / "nguon"
    src.mkdir()
    f = src / "a5.bin"
    f.write_bytes(b"d4" * 50_000)
    p = peer_node(b, "May-B")
    seen: dict = {}

    def b_send():
        return asyncio.run_coroutine_threadsafe(p.node.transfers.send(a_id, [f]), p.loop)

    def script(run):
        yield from wait_running(run, gui_wait)
        t = run.tray
        port: list = []
        yield from node_value(run, lambda node: node.port, gui_wait, port)
        p.soon(p.node.connect_hint, a_id, [LOCAL], port[0])
        yield gui_wait(lambda: p.connected_to(a_id), 10, "B nối tới A")
        pause_action(t).trigger()
        yield gui_wait(lambda: t.state.paused, 5, "A tạm dừng nhận")
        fut = b_send()
        yield gui_wait(fut.done, 10, "B tạo lượt gửi")
        key = fut.result()
        yield gui_wait(lambda: p.finished(key.transfer_id) is not None, 10, "B nhận kết quả lượt 1")
        first = p.finished(key.transfer_id)
        seen["first"] = first.result
        peer = texts.peer_label("May-A", a_id)
        seen["first_text"] = (result_message(first, peer), peer)
        pause_action(t).trigger()
        yield gui_wait(lambda: not t.state.paused, 5, "A nhận lại")
        ctl = app_of(run).transfers
        fut2 = b_send()
        yield gui_wait(fut2.done, 10, "B tạo lượt gửi lại")
        key2 = fut2.result()
        yield gui_wait(
            lambda: ctl.offers.keys() or p.finished(key2.transfer_id), 10, "A hỏi nhận (hay tự nhận)"
        )
        for k in list(ctl.offers.keys()):
            [accept] = ui_helpers.buttons_with_text(ctl.offers.box(k), ui_helpers.M6_ACCEPT)
            accept.click()
        yield gui_wait(lambda: p.finished(key2.transfer_id) is not None, 20, "B nhận kết quả lượt 2")
        seen["second"] = p.finished(key2.transfer_id).result
        quit_now(run)

    run = gui(["--config-dir", str(a)], script, timeout=90)
    assert run.code == 0
    assert seen["first"] is TransferResult.REJECTED_NOT_RECEIVING
    text, peer = seen["first_text"]
    assert text == NOT_RECEIVING_VI.format(name=peer)
    assert seen["second"] is TransferResult.DONE
