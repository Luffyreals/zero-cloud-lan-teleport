"""Nối màn “Tìm máy mới” vào cửa sổ chính và app: spec B5 mục 2.10, test T-H, T-W (mục 6), H1, H2, H5
(mục 11).

Viết từ spec, không từ code:

- T-H (`MainWindow`): trang DISCOVER có sẵn, `discover_button` (objectName `discoverButton`, icon `search`,
  nhãn “Tìm máy mới”) chỉ hiện ở RUNNING, bấm → DISCOVER; nút “Quay lại” của header về HOME (H2); trang
  dùng **cùng** `DeviceListModel` với `window.devices` (spec B2 mục 2.1); Tab `discover_button` →
  `settings_button`.
- T-W (`GuiApp`): `pair_requested` → `PairingController.pair_device`, `manual_address_entered` →
  `pair_address`, `open_device_requested` → HOME + chọn cuộc trò chuyện của máy (spec B2 2.7),
  `pairing.notice` → `info_bar` của trang; `wait_pairing_requested` (nút “Chờ ghép đôi”, hiện) mở trang
  WAIT_PAIRING (spec D3 mục 2.2; phần còn lại ở tests/ui/test_wait_pairing.py). `radar_view` trong
  `settings.json` được đọc lúc `started` (H1: `Node.settings` là property) và ghi khi người dùng bấm
  `view_button` — chạy qua fixture `gui` (node thật trên 127.0.0.1 → `integration`).
"""

from __future__ import annotations

import hashlib
import json

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import SIGNAL, QCoreApplication, Qt, QTranslator
from PySide6.QtWidgets import QApplication

integration = pytest.mark.integration

HOME_BUTTON = "Tìm máy mới"
PREFIX = "[x]"


def view(name: str, *, paired: bool = False, online: bool = True, connected: bool = False):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=hashlib.sha256(name.encode()).hexdigest(),
        name=name,
        os="windows",
        paired=paired,
        online=online,
        connected=connected,
        addresses=("127.0.0.1",) if online else (),
        port=47474 if online else None,
    )


def settle(qtbot, ms: int = 30) -> None:
    QApplication.processEvents()
    qtbot.wait(ms)


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


@pytest.fixture
def window(qtbot):
    from teleport.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    return w


@pytest.fixture
def gui_app(qapp, tmp_path):
    """`GuiApp` dựng thẳng (không node, không mạng), như tests/ui/test_pairing_wiring.py."""
    from teleport.ui import app as ui_app

    g = ui_app.GuiApp(qapp, tmp_path)
    yield g
    g.tray.dispose()
    g.window.deleteLater()


# =================================================================================================
# T-H MainWindow
# =================================================================================================


def test_discover_page_is_registered_and_shares_window_devices(window):
    from teleport.ui.discover import DiscoverPage
    from teleport.ui.main_window import Page

    assert window.pages.has_page(Page.DISCOVER)
    assert isinstance(window.discover, DiscoverPage)
    assert window.discover.objectName() == "discoverPage"
    assert window.discover.list_view.model().sourceModel() is window.devices, "cùng một model (is)"
    assert window.discover.model is window.devices
    assert window.conversations.model.sourceModel() is window.devices, "spec B2 12.32"


def test_discover_page_follows_window_devices_changes(window, qtbot):
    window.devices.reset([view("May-X"), view("May-P", paired=True)])
    settle(qtbot)
    shown = {b.device_id for b in window.discover.canvas.bubbles()}
    assert shown == {view("May-X").device_id, view("May-P").device_id}


def test_discover_button_is_named_icon_button(window):
    from teleport.ui.widgets import IconButton

    b = window.discover_button
    assert isinstance(b, IconButton)
    assert b.objectName() == "discoverButton"
    assert b.icon_name == "search"
    assert b.label == HOME_BUTTON
    assert b.accessibleName() == HOME_BUTTON
    assert window.sidebar_header.isAncestorOf(b), "B1: nút ở đầu cột trái"


@pytest.mark.parametrize("state", ["welcome", "starting", "error", "running"])
def test_discover_button_visible_only_when_running(window, tmp_path, state):
    show = {
        "welcome": lambda: window.show_welcome("May-A"),
        "starting": window.show_starting,
        "error": lambda: window.show_error("other", ""),
        "running": lambda: window.show_running("May-A", tmp_path / "nhan"),
    }
    window.show_running("May-A", tmp_path / "nhan")
    show[state]()
    assert window.discover_button.isVisibleTo(window) is (state == "running")


def test_discover_button_opens_page_and_back_button_returns_home(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    window.show_running("May-A", tmp_path / "nhan")
    window.show()
    qtbot.waitExposed(window)
    window.discover_button.click()
    settle(qtbot)
    assert window.current_page is Page.DISCOVER
    window.discover.header.back_button.click()  # H2
    settle(qtbot)
    assert window.current_page is Page.HOME


def test_discover_page_cannot_open_outside_running(window):
    from teleport.ui.main_window import Page

    window.show_starting()
    window.discover_button.click()
    assert window.current_page is Page.HOME


def test_tab_chain_discover_button_then_settings_then_conversations(window):
    """B1: ở RUNNING, “Tìm máy mới” đứng đầu chuỗi Tab của khung hai cột."""
    assert window.discover_button.nextInFocusChain() is window.settings_button


def test_discover_button_label_is_retranslated(window, qtbot, tmp_path):
    window.show_running("May-A", tmp_path / "nhan")
    translator = PrefixTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        qtbot.waitUntil(lambda: window.discover_button.label.startswith(PREFIX), timeout=3000)
        assert window.discover_button.accessibleName().startswith(PREFIX)
    finally:
        QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: window.discover_button.label == HOME_BUTTON, timeout=3000)


# =================================================================================================
# T-W GuiApp (không node)
# =================================================================================================


def test_discover_signals_reach_pairing_controller(gui_app, monkeypatch):
    from teleport.ui.pairing import PairingController

    calls: list[tuple] = []
    monkeypatch.setattr(PairingController, "pair_device", lambda self, v: calls.append(("pair", v)) or True)
    monkeypatch.setattr(
        PairingController, "pair_address", lambda self, ip, port: calls.append(("addr", ip, port)) or True
    )
    page = gui_app.window.discover
    v = view("May-X")
    page.pair_requested.emit(v)
    page.manual_address_entered.emit("192.168.1.5", 47474)
    assert calls == [("pair", v), ("addr", "192.168.1.5", 47474)]


def test_open_device_goes_home_and_selects_device(gui_app, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    window = gui_app.window
    p = view("May-P", paired=True, connected=True)
    window.devices.reset([view("May-U"), p])
    window.show_running("May-A", tmp_path / "nhan")
    assert window.open_page(Page.DISCOVER)
    window.discover.open_device_requested.emit(p.device_id)
    settle(qtbot)
    assert window.current_page is Page.HOME
    selected = window.conversations.current_device()
    assert selected is not None and selected.device_id == p.device_id


def test_pairing_notice_shows_on_discover_info_bar(gui_app):
    from teleport.ui.widgets import InfoLevel

    page = gui_app.window.discover
    gui_app.pairing.notice.emit("Đã ghép đôi với May-B.")
    assert not page.info_bar.isHidden()
    assert page.info_bar.level is InfoLevel.SUCCESS
    assert "Đã ghép đôi với May-B." in (page.info_bar.title, page.info_bar.text)


def test_wait_pairing_signal_opens_wait_pairing_page(gui_app, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    window = gui_app.window
    page = window.discover
    assert page.receivers(SIGNAL("wait_pairing_requested()")) >= 1, "D3 nối nút “Chờ ghép đôi”"
    window.show_running("May-A", tmp_path / "nhan")
    assert window.open_page(Page.DISCOVER)
    assert not page.wait_button.isHidden(), "nút “Chờ ghép đôi” hiện (set_wait_pairing_available(True))"
    page.wait_pairing_requested.emit()
    settle(qtbot)
    assert window.current_page is Page.WAIT_PAIRING


# =================================================================================================
# T-W qua `main` (node thật): radar_view trong settings.json
# =================================================================================================


def _host_started(run) -> bool:
    return bool(run.hosts) and run.hosts[-1].running


def _quit(run, plain) -> None:
    [action] = [a for a in run.tray.actions() if not a.isSeparator() and plain(a.text()) == "Thoát"]
    action.trigger()


_UNREADABLE = object()


def _radar_view_on_disk(config) -> object:
    """`radar_view` trong `settings.json`; file đang được thay nguyên tử (Windows khóa tạm) → `_UNREADABLE`
    để `gui_wait` thử lại."""
    path = config / "settings.json"
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("radar_view")
    except (OSError, ValueError):
        return _UNREADABLE


@integration
def test_started_reads_radar_view_from_settings(gui, gui_wait, config_dir, ui_helpers):
    from teleport.ui.discover import ListReason, ViewMode

    d = config_dir("A")
    (d / "settings.json").write_text(json.dumps({"radar_view": "list"}), encoding="utf-8")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and _host_started(run), 15, "node chạy")
        page = run.window.discover
        yield gui_wait(lambda: page.view_preference == "list", 5, "đọc radar_view lúc started")
        seen["mode"] = (page.view_mode, page.list_reason)
        _quit(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert seen["mode"] == (ViewMode.LIST, ListReason.PREFERENCE)
    assert run.code == 0


@integration
def test_view_button_writes_radar_view_to_settings(gui, gui_wait, config_dir, ui_helpers):
    d = config_dir("A")
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.windows and _host_started(run), 15, "node chạy")
        window = run.window
        window.discover_button.setFocus(Qt.FocusReason.OtherFocusReason)
        window.discover_button.click()
        yield
        page = window.discover
        seen["before"] = page.view_preference
        page.view_button.click()
        yield gui_wait(lambda: _radar_view_on_disk(d) == "list", 5, "settings.json có radar_view = list")
        page.view_button.click()
        yield gui_wait(lambda: _radar_view_on_disk(d) == "radar", 5, "settings.json có radar_view = radar")
        seen["after"] = page.view_preference
        _quit(run, ui_helpers.plain)

    run = gui(["--config-dir", str(d)], script)
    assert seen["before"] is None
    assert seen["after"] == "radar"
    assert run.code == 0
