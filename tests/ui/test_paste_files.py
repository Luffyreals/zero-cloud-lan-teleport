"""Dán file đã chép trong trình quản lý file để gửi (spec “phím tắt và dán file”, `plan-f-ux-hang-ngay F2`:
mục 2.3, 2.7, 4, 6 S4–S9, S15; mục 10 H1, H2, H5, H9, H11, H12 ghi đè khi khác).

Viết từ spec, không từ code.

- `ChatView.paste_mime(mime) -> PasteOutcome`, `paste_from_clipboard() -> PasteOutcome | None`,
  `send.clipboard_paths(mime)`, signal `clipboard_settings_requested(device_id)`.
- Clipboard đọc qua seam cấp module `teleport.ui.chat._clipboard_mime` (đọc lúc gọi): test vá nó, không
  bao giờ đọc/ghi clipboard thật của máy. Riêng S5 (ô nhập tự dán chữ) dùng clipboard của nền `offscreen`
  (trong tiến trình) và khôi phục lại; nền khác thì bỏ qua.
- Phím Paste lấy từ `QKeySequence.keyBindings(StandardKey.Paste)` lúc chạy (H11).
"""

from __future__ import annotations

import os
import pathlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QByteArray, QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent, QGuiApplication, QImage, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton, QVBoxLayout, QWidget

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
STRANGER_ID = "5a5a5a5a" + "2" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"

# Câu chữ (mục 4; H2, H9 thắng).
HINT = (
    "{key} ở đây chỉ gửi file đã chép trong {file_manager}. Chữ và ảnh đi qua “Đồng bộ clipboard” với "
    "{name} (Cài đặt ▸ Thiết bị tin cậy, cần bật ở cả hai máy): chép ở máy này rồi dán thẳng ở máy kia."
)
OPEN_SETTINGS = "Mở Cài đặt"
NO_DEVICE = "Ghép đôi một máy trước ({discover_key}), rồi nhấn {key} để gửi file đã chép."
EMPTY_TEXT = "Hoặc bấm Gửi file ở dưới, hay nhấn {key} để dán file đã chép."


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def paste_key() -> QKeySequence:
    return QKeySequence.keyBindings(QKeySequence.StandardKey.Paste)[0]


def press(target: QWidget, seq: QKeySequence) -> None:
    combo = QKeySequence(seq)[0]
    QTest.keyClick(target, combo.key(), combo.keyboardModifiers())
    settle()


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
    if qtbot is not None and ms:
        qtbot.wait(ms)


def activate(qtbot, window: QWidget) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    settle()


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def dview(
    device_id: str = PEER_ID,
    name: str = PEER,
    *,
    online: bool = True,
    paired: bool = True,
):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=paired,
        online=online,
        connected=online and paired,
        addresses=("192.168.1.20",) if online else (),
        port=47474 if online else None,
    )


def peer(name: str | None, device_id: str = PEER_ID) -> str:
    from teleport.ui.texts import peer_label

    return peer_label(name, device_id)


def file_mime(*paths: Path) -> QMimeData:
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    return m


def text_mime(text: str = "xin chào") -> QMimeData:
    m = QMimeData()
    m.setText(text)
    return m


def image_mime() -> QMimeData:
    m = QMimeData()
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0x336699)
    m.setImageData(img)
    return m


def https_mime() -> QMimeData:
    m = QMimeData()
    m.setUrls([QUrl("https://example.com/x.zip")])
    return m


def mixed_mime(path: Path) -> QMimeData:
    """H12: một URL file cục bộ + một URL https → tất cả hoặc không."""
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(str(path)), QUrl("https://example.com/x.zip")])
    return m


def hint_text(name: str) -> str:
    from teleport.ui import shortcuts, texts
    from teleport.ui.shortcuts import Shortcut

    return (
        HINT.replace("{key}", shortcuts.key_text(Shortcut.PASTE_FILES))
        .replace("{file_manager}", texts.file_manager_name())
        .replace("{name}", name)
    )


def no_device_text() -> str:
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut

    return NO_DEVICE.replace("{discover_key}", shortcuts.key_text(Shortcut.DISCOVER)).replace(
        "{key}", shortcuts.key_text(Shortcut.PASTE_FILES)
    )


class SpyMime(QMimeData):
    """Mime ghi lại lời gọi `text`/`html`/`imageData` (spec 2.3: `clipboard_paths` không đọc chúng)."""

    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def text(self) -> str:
        self.reads.append("text")
        return super().text()

    def html(self) -> str:
        self.reads.append("html")
        return super().html()

    def imageData(self):
        self.reads.append("imageData")
        return super().imageData()


class Harness:
    """`ChatView` đứng riêng (như `test_chat.Harness`), ghi lại các signal liên quan."""

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
        self.sends: list[tuple[str, list[Path]]] = []
        self.hints: list[str] = []
        self.settings: list[str] = []
        v.send_files_requested.connect(lambda i, p: self.sends.append((i, [Path(x) for x in p])))
        v.drop_hint_requested.connect(self.hints.append)
        v.clipboard_settings_requested.connect(self.settings.append)

    def show(self, qtbot, *, active: bool = False) -> None:
        self.host.show()
        qtbot.waitExposed(self.host)
        if active:
            activate(qtbot, self.host)
        settle()


@pytest.fixture
def no_clipboard(monkeypatch):
    """Seam `_clipboard_mime` mặc định ném lỗi: test nào lỡ đọc clipboard mà không vá thì đỏ rõ ràng."""
    from teleport.ui import chat

    def boom():
        raise AssertionError("test đọc clipboard mà chưa vá `_clipboard_mime`")

    monkeypatch.setattr(chat, "_clipboard_mime", boom)


@pytest.fixture
def h(qtbot, no_clipboard):
    harness = Harness(qtbot)
    harness.show(qtbot)
    return harness


def use_clipboard(monkeypatch, data: QMimeData | None) -> list[int]:
    """Vá seam trả `data`; trả danh sách đếm số lần đọc."""
    from teleport.ui import chat

    reads: list[int] = []

    def read():
        reads.append(1)
        return data

    monkeypatch.setattr(chat, "_clipboard_mime", read)
    return reads


# =================================================================================================
# `send.clipboard_paths` (2.3 bước 1, H12)
# =================================================================================================


def test_clipboard_paths_returns_local_files_in_order(tmp_path):
    from teleport.ui import send

    files = [tmp_path / "b.txt", tmp_path / "a c.txt"]
    assert send.clipboard_paths(file_mime(*files)) == files


@pytest.mark.parametrize("kind", ["text", "image", "https", "empty", "mixed"])
def test_clipboard_paths_not_files_is_empty(kind, tmp_path):
    from teleport.ui import send

    data = {
        "text": text_mime,
        "image": image_mime,
        "https": https_mime,
        "empty": QMimeData,
        "mixed": lambda: mixed_mime(tmp_path / "a.txt"),
    }[kind]()
    assert send.clipboard_paths(data) == []


def test_clipboard_paths_does_not_read_text_or_image():
    from teleport.ui import send

    data = SpyMime()
    data.setText("bí mật")
    assert send.clipboard_paths(data) == []
    assert data.reads == []
    files = SpyMime()
    files.setUrls([QUrl.fromLocalFile("C:/x/a.txt" if sys.platform == "win32" else "/x/a.txt")])
    files.setText("C:/x/a.txt")
    assert len(send.clipboard_paths(files)) == 1
    assert files.reads == []


def _watch_stat(monkeypatch, files: list[Path]) -> list[str]:
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
    return calls


def test_clipboard_paths_and_paste_do_not_stat(h, monkeypatch, tmp_path):
    from teleport.ui import send

    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for f in files:
        f.write_bytes(b"x")
    calls = _watch_stat(monkeypatch, files)
    assert send.clipboard_paths(file_mime(*files)) == files
    h.view.set_device(PEER_ID)
    h.view.paste_mime(file_mime(*files))
    assert calls == []
    assert h.sends == [(PEER_ID, files)]


# =================================================================================================
# S4: dán file gửi đúng một lần
# =================================================================================================


def test_paste_outcome_values():
    from teleport.ui.chat import PasteOutcome

    assert {o.name: o.value for o in PasteOutcome}.keys() == {"SENT", "NO_DEVICE", "NOT_FILES", "BLOCKED"}


def test_s4_paste_mime_with_two_files_sends_once(h, tmp_path):
    from teleport.ui.chat import PasteOutcome

    v = h.view
    v.set_device(PEER_ID)
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    assert v.paste_mime(file_mime(*files)) is PasteOutcome.SENT
    assert h.sends == [(PEER_ID, files)]
    assert v.notice_text() == ""
    assert h.hints == []


def test_s4_explorer_cut_sends_copy_and_keeps_sources(h, tmp_path):
    """Explorer “Cắt” (Preferred DropEffect = move) cũng chỉ gửi, không xóa/di chuyển nguồn."""
    from teleport.ui.chat import PasteOutcome

    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for f in files:
        f.write_bytes(b"noi dung")
    data = file_mime(*files)
    data.setData(
        'application/x-qt-windows-mime;value="Preferred DropEffect"', QByteArray(b"\x02\x00\x00\x00")
    )
    h.view.set_device(PEER_ID)
    assert h.view.paste_mime(data) is PasteOutcome.SENT
    assert h.sends == [(PEER_ID, files)]
    assert all(f.read_bytes() == b"noi dung" for f in files)


def test_paste_from_clipboard_reads_seam_at_call_time(h, monkeypatch, tmp_path):
    from teleport.ui.chat import PasteOutcome

    h.view.set_device(PEER_ID)
    files = [tmp_path / "a.txt"]
    reads = use_clipboard(monkeypatch, file_mime(*files))  # vá sau khi ChatView đã dựng
    assert h.view.paste_from_clipboard() is PasteOutcome.SENT
    assert reads == [1]
    assert h.sends == [(PEER_ID, files)]


def test_paste_from_clipboard_hidden_view_returns_none(h, monkeypatch, tmp_path):
    h.view.set_device(PEER_ID)
    h.view.hide()
    use_clipboard(monkeypatch, file_mime(tmp_path / "a.txt"))
    assert h.view.paste_from_clipboard() is None
    assert h.sends == []
    assert h.view.notice_text() == ""


def test_s4_ctrl_v_in_standalone_view_sends_once(qtbot, monkeypatch, tmp_path):
    harness = Harness(qtbot)
    harness.show(qtbot, active=True)
    files = [tmp_path / "a.txt", tmp_path / "b.txt"]
    use_clipboard(monkeypatch, file_mime(*files))
    harness.view.set_device(PEER_ID)
    harness.before.setFocus()
    settle()
    press(harness.before, paste_key())
    assert harness.sends == [(PEER_ID, files)]
    assert harness.view._paste_action.autoRepeat() is False


# =================================================================================================
# S6: không phải file → gợi ý, nút “Mở Cài đặt”
# =================================================================================================


@pytest.mark.parametrize("kind", ["text", "image", "https", "empty", "none", "mixed"])
def test_s6_not_files_shows_hint_with_name_and_key(h, kind, tmp_path):
    from teleport.ui.chat import PasteOutcome
    from teleport.ui.widgets import InfoLevel

    data = {
        "text": text_mime,
        "image": image_mime,
        "https": https_mime,
        "empty": QMimeData,
        "none": lambda: None,
        "mixed": lambda: mixed_mime(tmp_path / "a.txt"),
    }[kind]()
    v = h.view
    v.set_device(PEER_ID)
    assert v.paste_mime(data) is PasteOutcome.NOT_FILES
    assert h.sends == []
    assert h.hints == []
    assert v.notice_text() == hint_text(peer(PEER))
    assert v.info_bar.level is InfoLevel.INFO
    assert plain(v.notice_action_text() or "") == OPEN_SETTINGS


def test_s6_open_settings_button_emits_device_id(h):
    v = h.view
    v.set_device(OTHER_ID)
    v.paste_mime(text_mime())
    assert v.notice_text() == hint_text(peer(OTHER, OTHER_ID))
    v.notice_action.click()
    settle()
    assert h.settings == [OTHER_ID]
    assert v.notice_text() == "", "bấm nút thì thông báo ẩn"


def test_s6_hint_follows_language(h, qapp):
    from teleport.ui import i18n

    v = h.view
    v.set_device(PEER_ID)
    v.paste_mime(text_mime())
    vi = v.notice_text()
    i18n.set_language("en")
    settle()
    assert i18n.current_language() == "en"
    en = v.notice_text()
    assert en, "câu gợi ý phải còn hiện sau khi đổi ngôn ngữ"
    assert en != vi, "câu gợi ý phải được dịch lại"
    assert peer(PEER) in en


# =================================================================================================
# S7: máy ngoại tuyến vẫn gửi; máy không nhận được file thì chặn (dán lẫn thả)
# =================================================================================================


def test_s7_offline_paired_device_still_sends(qtbot, no_clipboard, tmp_path):
    from teleport.ui.chat import PasteOutcome

    harness = Harness(qtbot, [dview(online=False)])
    harness.show(qtbot)
    v = harness.view
    v.set_device(PEER_ID)
    files = [tmp_path / "a.txt"]
    assert v.paste_mime(file_mime(*files)) is PasteOutcome.SENT
    assert harness.sends == [(PEER_ID, files)]
    assert v.drop_paths(files) is True


def test_s7_device_that_cannot_receive_is_blocked(qtbot, no_clipboard, tmp_path):
    from teleport.ui.chat import PasteOutcome
    from teleport.ui.radar import can_receive_files

    stranger = dview(STRANGER_ID, "La", online=False, paired=False)
    assert not can_receive_files(stranger)
    harness = Harness(qtbot, [dview(), stranger])
    harness.show(qtbot)
    v = harness.view
    v.set_device(STRANGER_ID)
    files = [tmp_path / "a.txt"]
    assert v.paste_mime(file_mime(*files)) is PasteOutcome.BLOCKED
    assert v.drop_paths(files) is False
    data = file_mime(*files)
    QApplication.sendEvent(
        v,
        QDropEvent(
            QPointF(v.rect().center()),
            Qt.DropAction.CopyAction,
            data,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        ),
    )
    settle()
    assert harness.sends == []


def test_s7_unknown_device_view_is_not_blocked(qtbot, no_clipboard, tmp_path):
    """`devices.device(id)` là None (máy chưa có trong model) → không chặn (2.3: chỉ chặn khi có view)."""
    from teleport.ui.chat import PasteOutcome

    harness = Harness(qtbot, [dview()])
    harness.show(qtbot)
    v = harness.view
    v.set_device(OTHER_ID)
    files = [tmp_path / "a.txt"]
    assert v.paste_mime(file_mime(*files)) is PasteOutcome.SENT
    assert harness.sends == [(OTHER_ID, files)]


# =================================================================================================
# S8 / H2: chưa chọn máy
# =================================================================================================


@pytest.mark.parametrize("kind", ["files", "text", "none"])
def test_s8_no_device_asks_to_pair_first_whatever_clipboard_has(h, kind, tmp_path):
    from teleport.ui.chat import PasteOutcome

    data = {"files": lambda: file_mime(tmp_path / "a.txt"), "text": text_mime, "none": lambda: None}[kind]()
    v = h.view
    v.set_device(None)
    assert v.paste_mime(data) is PasteOutcome.NO_DEVICE
    assert h.hints == [no_device_text()]
    assert h.sends == []
    assert v.notice_text() == "", "H2: chưa có máy thì không hiện gợi ý D5 (không có nút)"


def test_drop_without_device_still_uses_drop_hint(h, tmp_path):
    """Thả file giữ đường cũ (mvp mục 8): chưa chọn máy → `radar.drop_hint_text()`."""
    from teleport.ui.radar import drop_hint_text

    h.view.set_device(None)
    assert h.view.drop_paths([tmp_path / "a.txt"]) is False
    assert h.hints == [drop_hint_text()]


# =================================================================================================
# S15: luồng rỗng nhắc phím dán
# =================================================================================================


def test_s15_empty_state_mentions_paste_key(h, qtbot):
    from teleport.ui import shortcuts
    from teleport.ui.shortcuts import Shortcut
    from teleport.ui.widgets import EmptyState

    v = h.view
    with qtbot.waitSignal(v.history_needed, timeout=2000):
        v.set_device(PEER_ID)
    v.load_history(PEER_ID, [])
    [es] = v.findChildren(EmptyState)
    assert es.isVisibleTo(v)
    assert es.text_label.text() == EMPTY_TEXT.replace("{key}", shortcuts.key_text(Shortcut.PASTE_FILES))


# =================================================================================================
# Cả cửa sổ: S4 (phím), S5, S9
# =================================================================================================


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
def win(qtbot, monkeypatch, tmp_path, no_clipboard):
    """`MainWindow` RUNNING + `TransfersController` (NodeHost giả), một máy đã ghép đôi, đang active."""
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: None)
    window = MainWindow()
    qtbot.addWidget(window)
    tray = Tray()
    ctl = mod.TransfersController(window, tray, parent=None)
    ctl.attach(FakeHost(tmp_path / "nhan"))
    view = ctl.view
    sends: list[tuple[str, list[Path]]] = []
    view.send_files_requested.connect(lambda i, p: sends.append((i, [Path(x) for x in p])))
    window.show_running("May-A", tmp_path / "nhan")
    window.devices.reset([dview()])
    window.resize(980, 660)
    activate(qtbot, window)
    assert view.device_id() == PEER_ID, "tự chọn hàng 0 → luồng mở"
    yield SimpleNamespace(window=window, ctl=ctl, view=view, sends=sends, tmp=tmp_path)
    ctl.close_all()
    tray.dispose()


def test_s4_ctrl_v_in_window_sends_once(win, monkeypatch):
    files = [win.tmp / "a.txt", win.tmp / "b.txt"]
    reads = use_clipboard(monkeypatch, file_mime(*files))
    win.window.conversations.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    press(QApplication.focusWidget(), paste_key())
    assert win.sends == [(PEER_ID, files)]
    assert reads == [1]
    assert win.view.notice_text() == ""


def test_s4_every_platform_paste_key_sends(win, monkeypatch):
    """H11: mọi phím Paste của nền (Windows: Ctrl+V và Shift+Ins) đều gửi, mỗi lần bấm một lần."""
    files = [win.tmp / "a.txt"]
    use_clipboard(monkeypatch, file_mime(*files))
    bindings = QKeySequence.keyBindings(QKeySequence.StandardKey.Paste)
    win.window.conversations.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    for seq in bindings:
        press(QApplication.focusWidget(), seq)
    assert win.sends == [(PEER_ID, files)] * len(bindings)


def test_s4_ctrl_v_with_text_shows_hint_in_window(win, monkeypatch):
    use_clipboard(monkeypatch, text_mime())
    win.window.conversations.list_view.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    press(QApplication.focusWidget(), paste_key())
    assert win.sends == []
    assert win.view.notice_text() == hint_text(peer(PEER))


@pytest.fixture
def offscreen_clipboard(qapp):
    """Clipboard của nền `offscreen` (trong tiến trình, không phải clipboard thật); khôi phục sau test."""
    if QGuiApplication.platformName() != "offscreen":
        pytest.skip("chỉ chạy trên nền offscreen: không chạm clipboard thật của máy")
    board = QApplication.clipboard()
    yield board
    board.clear()


def test_s5_line_edit_in_window_pastes_text_not_send(win, monkeypatch, offscreen_clipboard):
    """H5: ô nhập sửa được tự nhận ShortcutOverride cho Paste → dán chữ, không gửi, không thông báo."""
    offscreen_clipboard.setText("xin chào")
    use_clipboard(monkeypatch, text_mime("xin chào"))
    edit = QLineEdit()
    edit.setObjectName("testEdit")
    win.window.home_page.layout().addWidget(edit)
    edit.show()
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    assert QApplication.focusWidget() is edit
    press(edit, paste_key())
    assert edit.text() == "xin chào"
    assert win.sends == []
    assert win.view.notice_text() == ""


def test_s5_line_edit_with_file_clipboard_still_does_not_send(win, monkeypatch, offscreen_clipboard):
    data = file_mime(win.tmp / "a.txt")
    offscreen_clipboard.setMimeData(file_mime(win.tmp / "a.txt"))
    use_clipboard(monkeypatch, data)
    edit = QLineEdit()
    win.window.home_page.layout().addWidget(edit)
    edit.show()
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    settle()
    press(edit, paste_key())
    assert win.sends == []
    assert win.view.notice_text() == ""


@pytest.mark.parametrize("where", ["discover", "settings"])
def test_s9_ctrl_v_on_other_pages_does_nothing(win, monkeypatch, where):
    from teleport.ui.main_window import Page

    if where == "settings":
        page = QWidget()
        button = QPushButton("Nút của trang S", page)
        QVBoxLayout(page).addWidget(button)
        page.setFocusProxy(button)
        win.window.add_page(Page.SETTINGS, page)
    use_clipboard(monkeypatch, file_mime(win.tmp / "a.txt"))
    assert win.window.open_page(Page(where))
    settle()
    focus = QApplication.focusWidget() or win.window
    if isinstance(focus, QLineEdit):  # ô nhập của trang tự dán chữ (S5); kiểm bằng widget không soạn thảo
        win.window.discover.header.back_button.setFocus(Qt.FocusReason.OtherFocusReason)
        settle()
        focus = QApplication.focusWidget() or win.window
    press(focus, paste_key())
    assert win.sends == []
    assert win.view.notice_text() == ""
    assert win.window.current_page is Page(where)


# =================================================================================================
# H1: show_section(..., focus=), qua GuiApp (S6 phần cuối)
# =================================================================================================


def _settings_page(qtbot, views):
    from teleport.app.autostart import AutostartState
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import SettingsPage, SettingsSnapshot

    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.resize(980, 660)
    page.set_loaded(True)
    page.set_values(
        SettingsSnapshot(
            name="May-A",
            visible=True,
            rate_limit=None,
            temp_retention_days=None,
            language=None,
            autostart=False,
            devices={},
        )
    )
    page.set_autostart(AutostartState.OFF)
    model.reset(views)
    activate(qtbot, page)
    return page


def test_h1_show_section_focus_clipboard_checkbox(qtbot):
    from teleport.ui.settings import Section

    page = _settings_page(qtbot, [dview(), dview(OTHER_ID, OTHER)])
    page.show_section(Section.DEVICES, OTHER_ID, focus="clipboard")
    settle()
    assert page.sections.currentIndex() == list(Section).index(Section.DEVICES)
    assert QApplication.focusWidget() is page.device_row(OTHER_ID).clipboard_checkbox


def test_h1_show_section_default_focus_is_ask(qtbot):
    from teleport.ui.settings import Section

    page = _settings_page(qtbot, [dview(), dview(OTHER_ID, OTHER)])
    page.show_section(Section.DEVICES, OTHER_ID)
    settle()
    assert QApplication.focusWidget() is page.device_row(OTHER_ID).ask_checkbox


@pytest.fixture
def apps(monkeypatch):
    from teleport.ui import app as ui_app

    made: list = []
    real_init = ui_app.GuiApp.__init__

    def init(self, *args, **kwargs):
        real_init(self, *args, **kwargs)
        made.append(self)

    monkeypatch.setattr(ui_app.GuiApp, "__init__", init)
    return made


@pytest.mark.integration
def test_s6_open_settings_from_hint_opens_devices_on_clipboard_checkbox(
    gui, gui_wait, config_dir, trust_each_other, ui_helpers, apps, monkeypatch
):
    """S6 + H1 qua `GuiApp`: dán chữ → nút “Mở Cài đặt” → trang SETTINGS, mục Thiết bị tin cậy, tiêu điểm
    ở ô “Đồng bộ clipboard” của máy đó. B không chạy (máy đã ghép đôi, ngoại tuyến)."""
    from teleport.ui import chat
    from teleport.ui.chat import PasteOutcome
    from teleport.ui.main_window import Page
    from teleport.ui.settings import Section

    monkeypatch.setattr(chat, "_clipboard_mime", lambda: text_mime())
    a, b = config_dir("A"), config_dir("B")
    _, id_b = trust_each_other(a, b)
    b_id = id_b.device_id
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.hosts and run.host.running and apps, 15, "node chạy")
        app = apps[-1]
        page = app.settings.page
        yield gui_wait(
            lambda: page.loaded and page.device_row(b_id) is not None, 10, "trang Cài đặt nạp xong"
        )
        view = app.transfers.view
        yield gui_wait(lambda: view.device_id() == b_id, 10, "luồng của B mở")
        seen["outcome"] = view.paste_mime(text_mime())
        seen["notice"] = view.notice_text()
        view.notice_action.click()
        yield gui_wait(lambda: run.window.current_page is Page.SETTINGS, 5, "mở Cài đặt")
        yield gui_wait(
            lambda: run.window.focusWidget() is page.device_row(b_id).clipboard_checkbox,
            5,
            "tiêu điểm ở ô Đồng bộ clipboard của B",
        )
        seen["section"] = page.sections.currentIndex()
        [action] = [
            x for x in run.tray.actions() if not x.isSeparator() and ui_helpers.plain(x.text()) == "Thoát"
        ]
        action.trigger()

    run = gui(["--config-dir", str(a)], script)
    assert seen["outcome"] is PasteOutcome.NOT_FILES
    assert seen["notice"] == hint_text(peer("May-B", b_id))
    assert seen["section"] == list(Section).index(Section.DEVICES)
    assert run.code == 0
