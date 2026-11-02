"""Trang “Chờ ghép đôi” (spec D3 mục 2, 3; test mục 5; mvp 7.5, F3, F10).

Viết từ spec, không từ code:

- “Đang mở” = trang đang hiện (`isVisible()`), tính lại ở mọi show/hide. Mở → node nhận yêu cầu ghép
  đôi (`accept_pairing` True kể cả máy **ẩn**); rời trang (Esc, “Quay lại”, “Đóng”, xuống khay, mở trang
  khác, lỗi khởi động) → về luật thường (`accept_pairing = visible`). Thu nhỏ không đóng; hiện lại từ
  khay khi trang vẫn là trang hiện tại thì mở lại.
- Dòng “Đang chờ…” chỉ khi lần mở mới nhất đã áp xong trên node; lỗi → InfoBar lỗi, không “Đang chờ…”,
  và cờ chờ ghép đôi được trả về False. Kết quả của lần mở cũ không đè lần mới.
- Câu “đang ẩn” chỉ khi ẩn và đổi theo `settings.visibility_changed`.
- Địa chỉ: mỗi địa chỉ một hàng + nút “Chép” (accessibleName có địa chỉ), `:cổng` khi cổng khác
  `DEFAULT_PORT`; None → “Đang lấy địa chỉ…”; rỗng → cảnh báo, có lại → cảnh báo mất.
- `pairing.notice` chỉ hiện ở InfoBar của trang khi trang mở; mở lại trang thì InfoBar cũ đã xóa.

Đọc `node.accept_pairing` qua `host.call` (thread node), lặp tới hạn. Không dựa vào tên thuộc tính nội bộ
của trang: tìm trang theo lớp `WaitPairingPage`, nút theo chữ / accessibleName, InfoBar theo lớp.

Giả định ngoài spec (ghi rõ để giao-dien khớp hoặc sửa test): `_enter_wait` trả đúng bộ ba
`(name, device_id, visible)` (spec 2.2) — test nhận ra kết quả của lần mở bằng bộ ba đó để giữ/đổi kết
quả; `display_name(printable(...))` áp ở `WaitPairingPage.set_identity` (spec 2.1 xếp vào trang);
`GuiApp._refresh_addresses` đọc địa chỉ qua hàm module `ui.app._read_addresses` (đã có trước D3).
"""

from __future__ import annotations

import contextlib
import json
import time

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QScrollBar, QSystemTrayIcon

integration = pytest.mark.integration

# ---- Câu chữ (spec D3 mục 2) ---------------------------------------------------------------------
TITLE = "Chờ ghép đôi"
STATUS = "Đang chờ máy khác gửi yêu cầu ghép đôi."
HIDDEN = "Máy này đang ẩn nên máy kia không tự thấy. Hãy nhập IP của máy này ở máy kia."
LOADING = "Đang lấy địa chỉ…"
NO_ADDRESS = "Không tìm thấy địa chỉ mạng nào của máy này. Hãy kiểm tra máy đã nối Wi-Fi hoặc dây mạng."
OPEN_FAILED = "Chưa mở được chế độ chờ ghép đôi. Hãy đóng màn này rồi thử lại."
BACK = "Quay lại"
CLOSE = "Đóng"
COPY = "Chép"
NOTICE = "Đã ghép đôi với May-B."


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def settle(qtbot, ms: int = 30) -> None:
    QApplication.processEvents()
    qtbot.wait(ms)


def host_call(qtbot, host, fn, timeout_ms: int = 5_000):
    box: dict = {}
    host.call(fn, lambda r: box.setdefault("r", r))
    qtbot.waitUntil(lambda: "r" in box, timeout=timeout_ms)
    if isinstance(box["r"], BaseException):
        raise box["r"]
    return box["r"]


def accept_pairing(qtbot, host) -> bool:
    return host_call(qtbot, host, lambda n: n.accept_pairing)


def wait_accept(qtbot, host, want: bool, timeout: float = 5.0) -> None:
    """Lặp đọc `accept_pairing` qua `host.call` tới khi bằng `want` (hết hạn → AssertionError)."""
    deadline = time.monotonic() + timeout
    seen = None
    while time.monotonic() < deadline:
        seen = accept_pairing(qtbot, host)
        if seen is want:
            return
        qtbot.wait(30)
    raise AssertionError(f"accept_pairing = {seen}, mong {want}")


def stays_accept(qtbot, host, want: bool, ms: int = 300) -> None:
    """`accept_pairing` giữ `want` suốt `ms` (đọc vài lần)."""
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        assert accept_pairing(qtbot, host) is want
        qtbot.wait(50)


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def wait_page(window):
    from teleport.ui.wait_pairing import WaitPairingPage

    pages = window.findChildren(WaitPairingPage)
    assert len(pages) == 1, f"đúng một WaitPairingPage trong cửa sổ, có {len(pages)}"
    return pages[0]


def button_named(root, name: str) -> QAbstractButton:
    """Nút đang hiện (so với `root`) có chữ hay accessibleName đúng `name`."""
    found = [
        b
        for b in root.findChildren(QAbstractButton)
        if b.isVisibleTo(root) and name in (plain(b.text()), b.accessibleName())
    ]
    assert found, f"không có nút “{name}”"
    return found[0]


def info_bars(page) -> list:
    from teleport.ui.widgets import InfoBar

    return [b for b in page.findChildren(InfoBar) if b.isVisibleTo(page)]


def info_bar_with(page, text: str):
    for bar in info_bars(page):
        if text in (bar.title, bar.text) or text in f"{bar.title} {bar.text}":
            return bar
    return None


def page_text(page, ui_helpers) -> str:
    QApplication.processEvents()
    return ui_helpers.all_text(page)


def label_texts(page) -> list[str]:
    # Widget thêm vào layout của cha đang hiện chỉ hiện sau một vòng sự kiện (như người dùng thấy).
    QApplication.processEvents()
    return [w.text() for w in page.findChildren(QLabel) if w.isVisibleTo(page) and w.text()]


def copy_buttons(page) -> list[QAbstractButton]:
    QApplication.processEvents()
    return [
        b
        for b in page.findChildren(QAbstractButton)
        if b.isVisibleTo(page) and (plain(b.text()) == COPY or b.accessibleName().startswith(COPY))
    ]


def activate(window, qtbot) -> None:
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)


def open_wait_page(app, qtbot):
    """Như người dùng: “Tìm máy mới” → “Chờ ghép đôi”."""
    from teleport.ui.main_window import Page

    window = app.window
    if window.current_page is not Page.DISCOVER:
        window.discover_button.click()
        settle(qtbot)
    assert window.current_page is Page.DISCOVER
    button = window.discover.wait_button
    assert button.isVisibleTo(window), "nút “Chờ ghép đôi” phải hiện khi chạy qua GuiApp"
    button.click()
    settle(qtbot)
    assert window.current_page is Page.WAIT_PAIRING
    return wait_page(window)


def wait_status(qtbot, page, ui_helpers, timeout: int = 5_000) -> None:
    qtbot.waitUntil(lambda: STATUS in page_text(page, ui_helpers), timeout=timeout)


class CallTap:
    """Bọc `host.call` của một host: nhận ra kết quả của lần mở (bộ ba `(name, device_id, visible)`) và
    giữ lại (`hold`) hay đổi thành lỗi (`fail`) trước khi giao cho controller. Hàm vẫn chạy thật trên
    node (cờ chờ ghép đôi của host vẫn được đặt)."""

    def __init__(self, host, device_id: str, monkeypatch) -> None:
        self.real = host.call
        self.device_id = device_id
        self.mode = "pass"
        self.held: list[tuple] = []
        self.entered = 0
        monkeypatch.setattr(host, "call", self.call)

    def _is_enter(self, result) -> bool:
        return isinstance(result, tuple) and len(result) == 3 and result[1] == self.device_id

    def call(self, fn, on_done=None):
        if on_done is None:
            return self.real(fn)

        def done(result):
            if not self._is_enter(result):
                on_done(result)
                return
            self.entered += 1
            if self.mode == "hold":
                self.held.append((on_done, result))
            elif self.mode == "fail":
                on_done(RuntimeError("giả lỗi lúc mở chế độ chờ"))
            else:
                on_done(result)

        return self.real(fn, done)


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def make_app(qapp, qtbot, config_dir, node_options, monkeypatch):
    """`make(hidden=True, addresses=None) -> GuiApp` đã chạy node thật (127.0.0.1), cửa sổ đã hiện,
    có khay (giả). `addresses=(tuple, port)` thay kết quả đọc địa chỉ của máy này."""
    from teleport.ui import app as ui_app
    from teleport.ui import tray as tray_mod
    from teleport.ui.main_window import ViewState

    monkeypatch.setattr(tray_mod, "is_available", lambda: True)
    shown: dict[int, bool] = {}
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: shown.__setitem__(id(self), True))
    monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: shown.__setitem__(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "setVisible", lambda self, v: shown.__setitem__(id(self), bool(v)))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: shown.get(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *a, **k: None)
    apps: list = []

    def make(*, hidden: bool = True, addresses=None, label: str = "A"):
        d = config_dir(label)
        if hidden:
            (d / "settings.json").write_text(json.dumps({"visible": False}), encoding="utf-8")
        if addresses is not None:

            async def fake_read(node):
                return addresses

            monkeypatch.setattr(ui_app, "_read_addresses", fake_read)
        app = ui_app.GuiApp(qapp, d, make_options=lambda c: node_options(c))
        apps.append(app)
        app.window.resize(980, 660)
        app.start()
        qtbot.waitUntil(
            lambda: app.host is not None and app.host.running and app.window.view_state is ViewState.RUNNING,
            timeout=20_000,
        )
        qtbot.waitExposed(app.window)
        return app

    yield make

    for app in apps:
        hosts = [h for h in (app.host,) if h is not None]
        for host in hosts:
            with contextlib.suppress(Exception):
                host.stop()
        deadline = time.monotonic() + 30
        for host in hosts:
            while not host.join(0.05) and time.monotonic() < deadline:
                qtbot.wait(20)
        with contextlib.suppress(Exception):
            app.shutdown()
        app.window.hide()
        app.window.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def page(qtbot):
    """`WaitPairingPage` đứng riêng (không node), đã hiện."""
    from teleport.ui.wait_pairing import WaitPairingPage

    p = WaitPairingPage()
    qtbot.addWidget(p)
    p.resize(980, 660)
    p.show()
    qtbot.waitExposed(p)
    return p


# =================================================================================================
# 5.1 Nút “Chờ ghép đôi” → trang, máy ẩn nhận ghép đôi
# =================================================================================================


@integration
def test_wait_button_opens_page_and_hidden_machine_accepts_pairing(make_app, qtbot, ui_helpers):
    from teleport.ui.main_window import Page

    app = make_app(hidden=True)
    assert accept_pairing(qtbot, app.host) is False, "máy ẩn, chưa chờ: không nhận"
    page = open_wait_page(app, qtbot)
    assert app.window.current_page is Page.WAIT_PAIRING
    assert page.is_open is True
    wait_accept(qtbot, app.host, True)
    wait_status(qtbot, page, ui_helpers)
    assert TITLE in page_text(page, ui_helpers)


def test_gui_app_exposes_wait_pairing_controller(qapp, tmp_path):
    from teleport.ui import app as ui_app
    from teleport.ui.main_window import Page
    from teleport.ui.wait_pairing import WaitPairingController

    g = ui_app.GuiApp(qapp, tmp_path)
    try:
        assert isinstance(g.wait_pairing, WaitPairingController)
        assert g.window.pages.has_page(Page.WAIT_PAIRING)
    finally:
        g.tray.dispose()
        g.window.deleteLater()


# =================================================================================================
# 5.2 Rời trang → accept_pairing False (máy ẩn)
# =================================================================================================


def _leave_escape(app, page, qtbot):
    activate(app.window, qtbot)
    target = QApplication.focusWidget() or app.window
    QTest.keyClick(target, Qt.Key.Key_Escape)


def _leave_back(app, page, qtbot):
    button_named(page, BACK).click()


def _leave_close(app, page, qtbot):
    button_named(page, CLOSE).click()


def _leave_tray(app, page, qtbot):
    app.window.close()  # có khay: xuống khay


def _leave_settings(app, page, qtbot):
    app.window.settings_button.click()


def _leave_conversation(app, page, qtbot):
    import hashlib

    from teleport.app.devices import DeviceView

    v = DeviceView(
        device_id=hashlib.sha256(b"May-P").hexdigest(),
        name="May-P",
        os="windows",
        paired=True,
        online=True,
        connected=False,
        addresses=("192.0.2.9",),
        port=47474,
    )
    app.window.devices.reset([v])
    settle(qtbot)
    assert app.window.open_conversation(v.device_id)


def _leave_error(app, page, qtbot):
    app.window.show_error("other", "")


LEAVES = {
    "esc": _leave_escape,
    "quay-lai": _leave_back,
    "dong": _leave_close,
    "xuong-khay": _leave_tray,
    "cai-dat": _leave_settings,
    "mo-cuoc-tro-chuyen": _leave_conversation,
    "loi-khoi-dong": _leave_error,
}


@integration
@pytest.mark.parametrize("how", list(LEAVES))
def test_leaving_page_stops_accepting_pairing_when_hidden(make_app, qtbot, ui_helpers, how):
    from teleport.ui.main_window import Page

    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    LEAVES[how](app, page, qtbot)
    settle(qtbot)
    if how == "xuong-khay":
        assert not app.window.isVisible(), "đóng cửa sổ khi có khay: xuống khay"
    else:
        assert app.window.current_page is not Page.WAIT_PAIRING
    assert page.is_open is False
    wait_accept(qtbot, app.host, False)
    stays_accept(qtbot, app.host, False)


@integration
def test_close_button_goes_back_like_back_button(make_app, qtbot):
    from teleport.ui.main_window import Page

    app = make_app(hidden=True)
    open_wait_page(app, qtbot)
    button_named(wait_page(app.window), CLOSE).click()
    settle(qtbot)
    assert app.window.current_page is Page.DISCOVER, "“Đóng” = quay lại trang trước (Tìm máy mới)"


# =================================================================================================
# 5.3 Thu nhỏ giữ mở; hiện lại từ khay mở lại
# =================================================================================================


@integration
def test_minimize_keeps_waiting(make_app, qtbot, ui_helpers):
    from teleport.ui.main_window import Page

    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    app.window.setWindowState(Qt.WindowState.WindowMinimized)
    settle(qtbot, 100)
    assert app.window.current_page is Page.WAIT_PAIRING
    assert page.is_open is True
    stays_accept(qtbot, app.host, True)
    assert STATUS in page_text(page, ui_helpers)


@integration
def test_show_from_tray_reopens_wait_mode(make_app, qtbot, ui_helpers):
    from teleport.ui.main_window import Page

    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    app.window.close()
    settle(qtbot)
    wait_accept(qtbot, app.host, False)
    assert STATUS not in page_text(page, ui_helpers), "đã đóng: không còn “Đang chờ…”"
    app.tray.open_requested.emit()  # “Mở Teleport” trong menu khay → bring_to_front
    settle(qtbot)
    assert app.window.isVisible()
    assert app.window.current_page is Page.WAIT_PAIRING
    assert page.is_open is True
    wait_accept(qtbot, app.host, True)
    wait_status(qtbot, page, ui_helpers)


@integration
def test_bring_to_front_after_minimize_keeps_waiting(make_app, qtbot):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    app.window.setWindowState(Qt.WindowState.WindowMinimized)
    settle(qtbot, 50)
    app.window.bring_to_front()
    settle(qtbot)
    assert page.is_open is True
    stays_accept(qtbot, app.host, True)


# =================================================================================================
# 5.4 Máy hiện: rời trang vẫn nhận
# =================================================================================================


@integration
@pytest.mark.parametrize("how", ["quay-lai", "xuong-khay", "cai-dat"])
def test_visible_machine_keeps_accepting_after_leaving(make_app, qtbot, how):
    app = make_app(hidden=False)
    assert accept_pairing(qtbot, app.host) is True
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    LEAVES[how](app, page, qtbot)
    settle(qtbot)
    assert page.is_open is False
    stays_accept(qtbot, app.host, True)


# =================================================================================================
# 5.5 Câu “đang ẩn”
# =================================================================================================


@integration
def test_hidden_sentence_shown_only_when_hidden(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    assert HIDDEN in page_text(page, ui_helpers)


@integration
def test_hidden_sentence_absent_when_visible(make_app, qtbot, ui_helpers):
    app = make_app(hidden=False)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    assert HIDDEN not in page_text(page, ui_helpers)


@integration
def test_hidden_sentence_follows_visibility_changed_while_open(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    app.settings.visibility_changed.emit(True)
    settle(qtbot)
    assert HIDDEN not in page_text(page, ui_helpers)
    app.settings.visibility_changed.emit(False)
    settle(qtbot)
    assert HIDDEN in page_text(page, ui_helpers)


def test_page_set_hidden_toggles_sentence(page, ui_helpers):
    page.set_hidden(True)
    assert HIDDEN in page_text(page, ui_helpers)
    page.set_hidden(False)
    assert HIDDEN not in page_text(page, ui_helpers)


# =================================================================================================
# 5.6 Địa chỉ
# =================================================================================================


def test_each_address_on_own_row_with_port_when_not_default(page):
    from teleport.net.connection import DEFAULT_PORT

    port = DEFAULT_PORT + 1
    page.set_addresses(["192.168.1.20", "10.0.0.5"], port)
    labels = label_texts(page)
    assert f"192.168.1.20:{port}" in labels
    assert f"10.0.0.5:{port}" in labels
    assert len(copy_buttons(page)) == 2


def test_address_without_port_when_default(page):
    from teleport.net.connection import DEFAULT_PORT

    page.set_addresses(["192.168.1.20"], DEFAULT_PORT)
    labels = label_texts(page)
    assert "192.168.1.20" in labels
    assert not any(t.startswith("192.168.1.20:") for t in labels)


def test_address_without_port_when_port_unknown(page):
    page.set_addresses(["192.168.1.20"], None)
    assert "192.168.1.20" in label_texts(page)


def test_copy_button_copies_exact_address_and_names_it(page, qtbot):
    port = 50123
    page.set_addresses(["192.168.1.20", "10.0.0.5"], port)
    buttons = copy_buttons(page)
    assert len(buttons) == 2
    for address in ("192.168.1.20", "10.0.0.5"):
        shown = f"{address}:{port}"
        [button] = [b for b in buttons if address in b.accessibleName()]
        assert button.accessibleName().startswith(COPY), "accessibleName kiểu “Chép địa chỉ …”"
        QGuiApplication.clipboard().setText("không đổi")
        button.click()
        settle(qtbot)
        assert QGuiApplication.clipboard().text() == shown


def test_address_label_selectable_by_mouse_not_keyboard(page):
    page.set_addresses(["192.168.1.20"], None)
    QApplication.processEvents()
    [label] = [w for w in page.findChildren(QLabel) if w.isVisibleTo(page) and w.text() == "192.168.1.20"]
    flags = label.textInteractionFlags()
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    assert not flags & Qt.TextInteractionFlag.TextSelectableByKeyboard


def test_addresses_none_shows_loading_without_warning(page, ui_helpers):
    from teleport.ui.widgets import InfoLevel

    page.set_addresses(None, None)
    assert LOADING in page_text(page, ui_helpers)
    assert not copy_buttons(page)
    assert info_bar_with(page, NO_ADDRESS) is None
    assert not any(b.level is InfoLevel.WARNING for b in info_bars(page))


def test_empty_addresses_warn_then_warning_clears_when_addresses_return(page, ui_helpers):
    from teleport.ui.widgets import InfoLevel

    page.set_addresses([], None)
    bar = info_bar_with(page, NO_ADDRESS)
    assert bar is not None, "đọc xong mà rỗng: cảnh báo"
    assert bar.level is InfoLevel.WARNING
    assert LOADING not in page_text(page, ui_helpers)
    page.set_addresses(["192.168.1.20"], None)
    assert info_bar_with(page, NO_ADDRESS) is None, "có địa chỉ lại: cảnh báo tự gỡ"
    assert "192.168.1.20" in label_texts(page)


def test_new_addresses_replace_old_rows(page):
    page.set_addresses(["192.168.1.20", "10.0.0.5"], None)
    page.set_addresses(["172.16.0.3"], None)
    labels = label_texts(page)
    assert "172.16.0.3" in labels
    assert "192.168.1.20" not in labels and "10.0.0.5" not in labels
    assert len(copy_buttons(page)) == 1


@integration
def test_gui_app_forwards_addresses_to_page(make_app, qtbot):
    port = 50123
    app = make_app(hidden=True, addresses=(("192.0.2.7", "198.51.100.4"), port))
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: f"192.0.2.7:{port}" in label_texts(page), timeout=5_000)
    assert f"198.51.100.4:{port}" in label_texts(page)
    [button] = [b for b in copy_buttons(page) if "192.0.2.7" in b.accessibleName()]
    button.click()
    settle(qtbot)
    assert QGuiApplication.clipboard().text() == f"192.0.2.7:{port}"


@integration
def test_no_address_warning_shown_again_on_reopen(make_app, qtbot):
    from teleport.ui.widgets import InfoLevel

    app = make_app(hidden=True, addresses=((), 50123))
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: info_bar_with(page, NO_ADDRESS) is not None, timeout=5_000)
    button_named(page, BACK).click()
    settle(qtbot)
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: info_bar_with(page, NO_ADDRESS) is not None, timeout=5_000)
    assert info_bar_with(page, NO_ADDRESS).level is InfoLevel.WARNING


# =================================================================================================
# 5.7 Tên, mã máy
# =================================================================================================


@integration
def test_page_shows_display_name_and_short_device_id(make_app, qtbot, ui_helpers):
    from teleport.core.display import display_name
    from teleport.ui.send import printable

    app = make_app(hidden=True)
    name, device_id = host_call(qtbot, app.host, lambda n: (n.name, n.identity.device_id))
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    text = page_text(page, ui_helpers)
    assert display_name(printable(name)) in text
    assert device_id[:8] in text
    assert device_id not in text, "chỉ 8 ký tự đầu của mã máy"


def test_set_identity_sanitizes_name(page, ui_helpers):
    from teleport.core.display import display_name
    from teleport.ui.send import printable

    raw = "May\x07‮-" + "X" * 120
    page.set_identity(raw, "abcd1234")
    text = page_text(page, ui_helpers)
    assert display_name(printable(raw)) in text
    assert raw not in text
    assert "abcd1234" in text


# =================================================================================================
# 5.8 Mở → đóng → mở nhanh; kết quả cũ không đè
# =================================================================================================


@integration
def test_open_close_open_fast_ends_waiting(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    window = app.window
    window.discover_button.click()
    settle(qtbot)
    wait_button = window.discover.wait_button
    for _ in range(5):
        wait_button.click()
        window.go_back()
    wait_button.click()
    page = wait_page(window)
    assert page.is_open is True
    wait_accept(qtbot, app.host, True)
    wait_status(qtbot, page, ui_helpers)
    assert info_bar_with(page, OPEN_FAILED) is None


@integration
def test_open_close_fast_ends_closed(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    window = app.window
    window.discover_button.click()
    settle(qtbot)
    for _ in range(5):
        window.discover.wait_button.click()
        window.go_back()
    page = wait_page(window)
    assert page.is_open is False
    wait_accept(qtbot, app.host, False)
    stays_accept(qtbot, app.host, False)
    assert STATUS not in page_text(page, ui_helpers)


@integration
def test_stale_open_failure_does_not_override_newer_open(make_app, qtbot, ui_helpers, monkeypatch):
    app = make_app(hidden=True)
    device_id = host_call(qtbot, app.host, lambda n: n.identity.device_id)
    tap = CallTap(app.host, device_id, monkeypatch)
    window = app.window
    window.discover_button.click()
    settle(qtbot)
    tap.mode = "hold"
    window.discover.wait_button.click()  # lần mở 1
    window.go_back()
    window.discover.wait_button.click()  # lần mở 2
    qtbot.waitUntil(lambda: len(tap.held) == 2, timeout=5_000)
    page = wait_page(window)
    (done_1, _r1), (done_2, r2) = tap.held
    done_2(r2)  # lần mới nhất xong trước
    done_1(RuntimeError("kết quả cũ"))  # lần cũ tới muộn, lỗi
    settle(qtbot)
    assert STATUS in page_text(page, ui_helpers), "lần mở mới nhất đã OK"
    assert info_bar_with(page, OPEN_FAILED) is None, "lỗi của lần mở cũ không được hiện"
    stays_accept(qtbot, app.host, True)


@integration
def test_late_open_result_after_close_does_not_show_waiting(make_app, qtbot, ui_helpers, monkeypatch):
    app = make_app(hidden=True)
    device_id = host_call(qtbot, app.host, lambda n: n.identity.device_id)
    tap = CallTap(app.host, device_id, monkeypatch)
    window = app.window
    window.discover_button.click()
    settle(qtbot)
    tap.mode = "hold"
    window.discover.wait_button.click()
    window.go_back()
    qtbot.waitUntil(lambda: len(tap.held) == 1, timeout=5_000)
    page = wait_page(window)
    [(done, result)] = tap.held
    done(result)
    settle(qtbot)
    assert page.is_open is False
    assert STATUS not in page_text(page, ui_helpers)
    wait_accept(qtbot, app.host, False)


# =================================================================================================
# 5.9 Mở thất bại
# =================================================================================================


@integration
def test_open_failure_shows_error_and_no_waiting(make_app, qtbot, ui_helpers, monkeypatch):
    from teleport.ui.widgets import InfoLevel

    app = make_app(hidden=True)
    device_id = host_call(qtbot, app.host, lambda n: n.identity.device_id)
    tap = CallTap(app.host, device_id, monkeypatch)
    tap.mode = "fail"
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: info_bar_with(page, OPEN_FAILED) is not None, timeout=5_000)
    assert info_bar_with(page, OPEN_FAILED).level is InfoLevel.ERROR
    assert STATUS not in page_text(page, ui_helpers)
    # Cờ chờ ghép đôi của host đã True (hàm đã chạy) mà kết quả báo lỗi: controller trả về False.
    wait_accept(qtbot, app.host, False)


@integration
def test_open_succeeds_again_after_failure(make_app, qtbot, ui_helpers, monkeypatch):
    app = make_app(hidden=True)
    device_id = host_call(qtbot, app.host, lambda n: n.identity.device_id)
    tap = CallTap(app.host, device_id, monkeypatch)
    tap.mode = "fail"
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: info_bar_with(page, OPEN_FAILED) is not None, timeout=5_000)
    button_named(page, CLOSE).click()
    settle(qtbot)
    tap.mode = "pass"
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    assert info_bar_with(page, OPEN_FAILED) is None, "mở mới xóa InfoBar cũ"
    wait_accept(qtbot, app.host, True)


# =================================================================================================
# 5.10 pairing.notice
# =================================================================================================


@integration
def test_pairing_notice_shows_on_page_when_open(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    app.pairing.notice.emit(NOTICE)
    settle(qtbot)
    assert info_bar_with(page, NOTICE) is not None
    from teleport.ui.main_window import Page

    assert app.window.current_page is Page.WAIT_PAIRING, "ghép xong ở lại trang"


@integration
def test_pairing_notice_not_shown_on_page_when_closed(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    button_named(page, BACK).click()
    settle(qtbot)
    app.pairing.notice.emit(NOTICE)
    settle(qtbot)
    assert info_bar_with(page, NOTICE) is None


@integration
def test_reopening_page_clears_old_notice(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    app.pairing.notice.emit(NOTICE)
    settle(qtbot)
    assert info_bar_with(page, NOTICE) is not None
    button_named(page, BACK).click()
    settle(qtbot)
    page = open_wait_page(app, qtbot)
    assert info_bar_with(page, NOTICE) is None


def test_page_show_notice_and_clear(page):
    from teleport.ui.widgets import InfoLevel

    page.show_notice(NOTICE, InfoLevel.SUCCESS)
    bar = info_bar_with(page, NOTICE)
    assert bar is not None and bar.level is InfoLevel.SUCCESS
    page.clear_notice()
    assert info_bar_with(page, NOTICE) is None


# =================================================================================================
# 5.11 Thoát khi trang mở
# =================================================================================================


@integration
def test_quit_while_page_open_stops_cleanly(gui, gui_wait, config_dir):
    from teleport.ui.main_window import Page

    d = config_dir("A")
    (d / "settings.json").write_text(json.dumps({"visible": False}), encoding="utf-8")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and run.hosts and run.host.running, 20, "node chạy")
        window = run.window
        window.discover_button.click()
        yield
        window.discover.wait_button.click()
        yield
        seen["page"] = window.current_page
        box: dict = {}
        run.host.call(lambda n: n.accept_pairing, lambda r: box.setdefault("r", r))
        yield gui_wait(lambda: "r" in box, 5, "đọc accept_pairing")
        seen["accept"] = box["r"]
        run.tray.quit_requested.emit()

    run = gui(["--config-dir", str(d)], script)
    assert seen["page"] is Page.WAIT_PAIRING
    assert seen["accept"] is True
    assert run.code == 0
    assert run.host.is_stopped, "`stopped` đã tới"


# =================================================================================================
# 5.12 Host mới (“Thử lại”)
# =================================================================================================


@integration
def test_new_host_starts_with_accept_pairing_equal_visible(make_app, qtbot, ui_helpers):
    from teleport.ui.main_window import Page, ViewState

    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, app.host, True)
    old = app.host
    old.stop()
    qtbot.waitUntil(lambda: old.is_stopped, timeout=15_000)
    app.window.show_error("other", "")  # trang đóng khi host không chạy: không lỗi
    settle(qtbot)
    assert page.is_open is False
    app.start_node()  # “Thử lại”
    new = app.host
    assert new is not old
    qtbot.waitUntil(lambda: new.running and app.window.view_state is ViewState.RUNNING, timeout=20_000)
    assert app.window.current_page is not Page.WAIT_PAIRING
    stays_accept(qtbot, new, False)
    page = open_wait_page(app, qtbot)
    wait_accept(qtbot, new, True)
    wait_status(qtbot, page, ui_helpers)


# =================================================================================================
# 5.13 Bản English, bố cục, trợ năng
# =================================================================================================


def test_page_strings_have_english_translation(qtbot, qapp):
    import re

    from teleport.ui import i18n
    from teleport.ui.wait_pairing import WaitPairingPage

    vietnamese = re.compile(
        r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.IGNORECASE
    )
    i18n.set_language("en")
    try:
        qapp.processEvents()
        p = WaitPairingPage()
        qtbot.addWidget(p)
        p.show()
        qtbot.waitExposed(p)
        p.set_identity("May-A", "abcd1234")
        p.set_hidden(True)
        p.set_waiting(True)
        p.set_addresses(None, None)
        strings: list[str] = []

        def collect() -> None:
            for w in p.findChildren(QLabel) + p.findChildren(QAbstractButton):
                if w.isVisibleTo(p):
                    strings.extend(s for s in (w.text(), w.accessibleName(), w.toolTip()) if s)
            for bar in info_bars(p):
                strings.extend(s for s in (bar.title, bar.text) if s)

        collect()
        p.set_addresses([], None)  # cảnh báo không có địa chỉ
        collect()
        p.set_addresses(["192.168.1.20"], None)
        collect()
        left = [s for s in strings if vietnamese.search(s)]
        assert not left, f"còn chữ tiếng Việt khi chạy English: {left}"
    finally:
        i18n.set_language(i18n.SOURCE_LANGUAGE)
        qapp.processEvents()


@integration
@pytest.mark.parametrize("size", ["980x660", "minimum"])
def test_page_fits_without_horizontal_scroll(make_app, qtbot, size):
    app = make_app(
        hidden=True,
        addresses=(("192.168.100.200", "10.200.200.200", "172.16.254.254", "192.0.2.77"), 50123),
    )
    window = app.window
    if size == "minimum":
        window.resize(window.minimumSize())
    else:
        window.resize(980, 660)
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: len(copy_buttons(page)) == 4, timeout=5_000)
    settle(qtbot, 50)
    bars = [
        s
        for s in page.findChildren(QScrollBar)
        if s.orientation() == Qt.Orientation.Horizontal and s.isVisible()
    ]
    assert not bars, "không có thanh cuộn ngang"
    for b in page.findChildren(QAbstractButton):
        if b.isVisible():
            assert b.width() >= b.sizeHint().width(), f"nút bị cắt: {b.accessibleName()!r}"


@integration
def test_tab_reaches_copy_buttons_before_close(make_app, qtbot):
    app = make_app(hidden=True, addresses=(("192.0.2.7", "198.51.100.4"), 50123))
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: len(copy_buttons(page)) == 2, timeout=5_000)
    order: list = []
    start = button_named(page, BACK)
    w = start
    for _ in range(200):
        if w.isVisible() and w.focusPolicy() & Qt.FocusPolicy.TabFocus and page.isAncestorOf(w):
            order.append(w)
        w = w.nextInFocusChain()
        if w is start:
            break
    copies = copy_buttons(page)
    close = button_named(page, CLOSE)
    assert all(c in order for c in copies), "nút Chép nhận tiêu điểm bằng Tab"
    assert close in order
    assert max(order.index(c) for c in copies) < order.index(close)
    assert order.index(start) < min(order.index(c) for c in copies)


# =================================================================================================
# Bổ sung sau soat-code: Hide tự phát, host mới, cảnh báo địa chỉ không đè câu khác
# =================================================================================================


def _hide_event(spontaneous: bool):
    """`QHideEvent` có `spontaneous()` cho trước. PySide6 không có `setSpontaneous` (chỉ Qt mới đặt cờ
    này, qua `sendSpontaneousEvent` riêng tư), nên dùng lớp con và gọi thẳng `page.hideEvent`."""
    from PySide6.QtGui import QHideEvent

    class FakeHide(QHideEvent):
        def spontaneous(self) -> bool:  # type: ignore[override]
            return spontaneous

    return FakeHide()


def test_spontaneous_hide_while_visible_keeps_open_and_notice(page):
    """Thu nhỏ trên Windows: Hide **tự phát** mà `isVisible()` vẫn True → không đổi “đang mở”, không
    xóa thanh thông báo (spec 2.1). Offscreen không gửi Hide tự phát khi thu nhỏ nên nhánh này chỉ kiểm
    được bằng cách gọi thẳng `hideEvent` với sự kiện giả; trên máy thật cần thử tay (thu nhỏ cửa sổ)."""
    from teleport.ui.widgets import InfoLevel

    assert page.isVisible() and page.is_open is True
    page.show_notice(NOTICE, InfoLevel.SUCCESS)
    changes: list = []
    page.open_changed.connect(changes.append)
    page.hideEvent(_hide_event(True))
    QApplication.processEvents()
    assert changes == [], "open_changed không phát"
    assert page.is_open is True
    assert info_bar_with(page, NOTICE) is not None, "Hide tự phát không xóa thanh thông báo"


def test_non_spontaneous_hide_event_clears_notice_control(page):
    """Đối chứng cho ca trên: cùng sự kiện giả nhưng không tự phát thì thanh thông báo bị xóa — chứng tỏ
    gọi thẳng `hideEvent` đúng là đi vào nhánh phân biệt `spontaneous()`."""
    from teleport.ui.widgets import InfoLevel

    page.show_notice(NOTICE, InfoLevel.SUCCESS)
    changes: list = []
    page.open_changed.connect(changes.append)
    page.hideEvent(_hide_event(False))
    QApplication.processEvents()
    assert info_bar_with(page, NOTICE) is None
    assert changes == [], "trang vẫn hiện (isVisible True): không phát open_changed"


def test_attach_new_host_resets_addresses_to_loading(qapp, tmp_path, ui_helpers):
    """Host mới (“Thử lại”): địa chỉ của host cũ không còn đúng → trang về “Đang lấy địa chỉ…”."""
    from types import SimpleNamespace

    from teleport.ui import app as ui_app

    g = ui_app.GuiApp(qapp, tmp_path)
    try:
        controller = g.wait_pairing
        page = controller.page
        controller.set_addresses(["192.168.1.20"], None)
        assert "192.168.1.20" in label_texts(page)
        controller.attach(SimpleNamespace(running=False))
        assert "192.168.1.20" not in label_texts(page)
        assert not copy_buttons(page)
        assert LOADING in page_text(page, ui_helpers)
        assert info_bar_with(page, NO_ADDRESS) is None
    finally:
        g.tray.dispose()
        g.window.deleteLater()


def test_attach_new_host_clears_no_address_warning(qapp, tmp_path, ui_helpers):
    from types import SimpleNamespace

    from teleport.ui import app as ui_app

    g = ui_app.GuiApp(qapp, tmp_path)
    try:
        controller = g.wait_pairing
        page = controller.page
        controller.set_addresses([], None)
        controller.attach(SimpleNamespace(running=False))
        assert info_bar_with(page, NO_ADDRESS) is None, "chưa đọc địa chỉ của host mới: chưa cảnh báo"
        assert LOADING in page_text(page, ui_helpers)
    finally:
        g.tray.dispose()
        g.window.deleteLater()


@pytest.mark.parametrize(
    ("text", "level"),
    [(OPEN_FAILED, "ERROR"), (NOTICE, "SUCCESS")],
    ids=["loi-mo", "pairing-notice"],
)
def test_no_address_warning_does_not_replace_other_notice(page, text, level):
    from teleport.ui.widgets import InfoLevel

    page.show_notice(text, InfoLevel[level])
    page.set_addresses([], None)
    bar = info_bar_with(page, text)
    assert bar is not None, "cảnh báo không có địa chỉ không đè câu đang hiện"
    assert bar.level is InfoLevel[level]


@integration
def test_no_address_warning_does_not_replace_open_error(make_app, qtbot, monkeypatch):
    from teleport.ui.widgets import InfoLevel

    app = make_app(hidden=True)
    device_id = host_call(qtbot, app.host, lambda n: n.identity.device_id)
    tap = CallTap(app.host, device_id, monkeypatch)
    tap.mode = "fail"
    page = open_wait_page(app, qtbot)
    qtbot.waitUntil(lambda: info_bar_with(page, OPEN_FAILED) is not None, timeout=5_000)
    app.wait_pairing.set_addresses([], None)  # như GuiApp._on_addresses khi đọc xong mà rỗng
    settle(qtbot)
    bar = info_bar_with(page, OPEN_FAILED)
    assert bar is not None and bar.level is InfoLevel.ERROR


@integration
def test_no_address_warning_does_not_replace_pairing_notice(make_app, qtbot, ui_helpers):
    app = make_app(hidden=True)
    page = open_wait_page(app, qtbot)
    wait_status(qtbot, page, ui_helpers)
    app.pairing.notice.emit(NOTICE)
    settle(qtbot)
    app.wait_pairing.set_addresses([], None)
    settle(qtbot)
    assert info_bar_with(page, NOTICE) is not None
