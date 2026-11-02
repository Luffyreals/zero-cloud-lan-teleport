"""Trang “Cài đặt” (`teleport.ui.settings.SettingsPage`, `teleport.ui.widgets.ToggleSwitch`): spec D2 mục
1.5, 1.6, 1.9, test 4.2; mục 9 (sau hoi-lai) thắng các mục trên khi khác.

Viết từ spec, không từ code. Trang là view thuần: không gọi node, đặt giá trị (`set_*`) không phát
signal; signal chỉ phát khi người dùng thao tác. Ô số chỉ phát khi chốt (9.4). Giá trị mặc định đọc từ
hằng của app lúc chạy (9.1), không viết cứng. Câu chữ chép nguyên văn từ bảng 1.9 (câu OTHER theo 9.7);
câu F1 và câu F10 đọc thẳng từ `docs/mvp.md`.

Giả định tên chưa có trong spec (giao-dien khớp, hay báo để sửa test):
- `TrustedDeviceRow.device_id` (mã máy của hàng).
- `SettingsPage.header` là `PageHeader` (có `back_button`), như `DiscoverPage.header`.
- `set_autostart(None)` = đọc registry lỗi; `set_autostart(AutostartState.UNSUPPORTED)` ẩn hàng.
- Mục đang mở đọc qua `page.sections.currentIndex()` (thứ tự theo `Section`) và `page.nav.currentRow()`.
- Thư mục nhận: `unavailable` (khi không có `receive_dir`) ẩn hay tắt nút “Mở” (theo `SaveBar` của B1b).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt, QTranslator
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QWidget,
)

_DOCS = Path(__file__).resolve().parents[2] / "docs"

# ---- Câu chữ (spec D2 1.9; OTHER theo 9.7) -----------------------------------------------------
TITLE = "Cài đặt"
# Spec D6 thêm “Giao diện” (icon `color`) ở vị trí thứ 2.
NAV = ("Chung", "Giao diện", "Quyền riêng tư", "Thiết bị tin cậy", "Truyền file", "Nâng cao")
NAV_ICONS = ("settings", "color", "eye_off", "shield_checkmark", "arrow_swap", "wrench")
NAME_LABEL = "Tên thiết bị"
NAME_HIDDEN = "Máy này đang ẩn nên chỉ máy đã ghép đôi thấy tên này."
NAME_EMPTY = "Hãy nhập tên thiết bị."
NAME_INVALID = "Tên thiết bị cần từ 1 đến 64 ký tự và không có ký tự điều khiển."
RECEIVE_DIR = "Thư mục nhận"
OPEN = "Mở"
CHANGE = "Đổi…"
LANGUAGE = "Ngôn ngữ"
SYSTEM_LANGUAGE = "Theo hệ điều hành"
AUTOSTART = "Khởi động cùng Windows"
AUTOSTART_HINT = "Teleport chạy ở khay hệ thống khi bạn đăng nhập Windows, sẵn sàng nhận file."
AUTOSTART_BLOCKED = (
    "Windows đang tắt Teleport trong danh sách ứng dụng khởi động. Bật công tắc này để cho phép lại."
)
AUTOSTART_OTHER = (
    "Teleport đang được đặt khởi động cùng Windows từ một thư mục cài hoặc thư mục cấu hình khác. "
    "Bật công tắc để dùng bản này."
)
AUTOSTART_READ_ERROR = "Không đọc được cài đặt khởi động của Windows."
VISIBLE = "Cho máy chưa ghép đôi thấy máy này"
HIDDEN_LINE = (
    "Đang ẩn: máy chưa ghép đôi không thấy máy này và không gửi được yêu cầu ghép đôi tới. Muốn ghép đôi "
    "với máy mới, hãy mở Tìm máy mới trên máy này rồi bấm vào máy kia."
)
HISTORY = "Lịch sử truyền file"
HISTORY_HINT = (
    "Teleport chỉ lưu tên file, cỡ và kết quả của các lượt truyền trên máy này, không lưu nội dung."
)
CLEAR_HISTORY = "Xóa toàn bộ lịch sử…"
DEVICES_INTRO = "Các máy đã ghép đôi với máy này. Bỏ chọn “Hỏi trước khi nhận” để tự nhận file từ máy đó."
ASK = "Hỏi trước khi nhận"
UNPAIR = "Hủy ghép đôi…"
ST_CONNECTED = "đã kết nối"
ST_ONLINE = "đang trong mạng"
ST_OFFLINE = "không thấy trong mạng"
EMPTY_TITLE = "Chưa ghép đôi với máy nào"
EMPTY_TEXT = "Ghép đôi để gửi file qua lại với máy khác trong mạng."
DISCOVER = "Tìm máy mới"
RATE = "Giới hạn tốc độ gửi"
RATE_CHECK = "Giới hạn"
RATE_HINT = "Áp dụng cho mọi lượt gửi từ máy này."
RETENTION = "Dọn phần nhận dở sau"
EXPORT = "Xuất log…"
EXPORTING = "Đang xuất…"
VERSION = "Phiên bản"
LICENSE = "Phần mềm tự do theo GNU GPL phiên bản 3."
NOTICES = "Thông báo bên thứ ba"

MB = 1048576
PREFIX = "[x]"


def _mvp_quote(pattern: str) -> str:
    """Câu trong ngoặc “…” của `docs/mvp.md` ngay sau `pattern` (tài liệu là nguồn của câu)."""
    text = (_DOCS / "mvp.md").read_text(encoding="utf-8")
    m = re.search(re.escape(pattern) + r"[^“]*“([^”]+)”", text)
    assert m, f"không thấy câu sau {pattern!r} trong docs/mvp.md"
    return m.group(1)


F1 = _mvp_quote("Ngay dưới ô tên thiết bị có dòng:")
F10 = _mvp_quote("Ngay dưới công tắc có dòng:")


# =================================================================================================
# Phụ trợ
# =================================================================================================


def view(
    name: str,
    *,
    paired: bool = True,
    online: bool = True,
    connected: bool = False,
    os: str | None = "windows",
    device_id: str | None = None,
):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id or hashlib.sha256(name.encode()).hexdigest()[:32],
        name=name,
        os=os,
        paired=paired,
        online=online,
        connected=connected,
        addresses=("192.168.1.9",) if online else (),
        port=47474 if online else None,
    )


def snapshot(**kw):
    from teleport.ui.settings import SettingsSnapshot

    values = {
        "name": "May-A",
        "visible": True,
        "rate_limit": None,
        "temp_retention_days": None,
        "language": None,
        "autostart": False,
        "devices": {},
    }
    values.update(kw)
    return SettingsSnapshot(**values)


def default_retention_days() -> int:
    from teleport.app import storage

    return int(storage.TEMP_RETENTION / 86400)


def settle(qtbot, ms: int = 30) -> None:
    QApplication.processEvents()
    qtbot.wait(ms)


def activate(qtbot, window: QWidget) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    QApplication.processEvents()


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def shown_texts(root: QWidget) -> list[str]:
    """Chữ đang hiện dưới `root`: nhãn, nút, ô nhập (chỉ widget hiện được)."""
    out: list[str] = []
    for w in root.findChildren(QLabel):
        if w.isVisibleTo(root) and w.text():
            out.append(w.text())
    for w in root.findChildren(QAbstractButton):
        if w.isVisibleTo(root) and w.text():
            out.append(plain(w.text()))
    return out


def joined(root: QWidget) -> str:
    return "\n".join(shown_texts(root))


def buttons_with_text(root: QWidget, text: str) -> list:
    return [b for b in root.findChildren(QAbstractButton) if plain(b.text()) == text and b.isVisibleTo(root)]


def section_index(name: str) -> int:
    from teleport.ui.settings import Section

    return list(Section).index(Section[name])


def open_section(page, name: str) -> QWidget:
    """Mở mục `name` (tên thành viên của `Section`), trả widget của mục đó trong `sections`."""
    from teleport.ui.settings import Section

    page.show_section(Section[name])
    QApplication.processEvents()
    assert page.sections.currentIndex() == section_index(name)
    return page.sections.currentWidget()


def device_rows(page) -> list:
    """Các `TrustedDeviceRow` đang hiện, theo thứ tự từ trên xuống."""
    from teleport.ui.settings import TrustedDeviceRow

    rows = [r for r in page.findChildren(TrustedDeviceRow) if r.isVisibleTo(page)]
    return sorted(rows, key=lambda r: r.mapTo(page, QPoint(0, 0)).y())


def row_of(page, device_id: str):
    found = [r for r in device_rows(page) if r.device_id == device_id]
    assert len(found) == 1, f"cần đúng một hàng cho {device_id[:8]}, thấy {len(found)}"
    return found[0]


def press_tab(times: int = 1) -> list:
    seen = []
    for _ in range(times):
        focus = QApplication.focusWidget()
        assert focus is not None, "không widget nào có tiêu điểm"
        QTest.keyClick(focus, Qt.Key.Key_Tab)
        seen.append(QApplication.focusWidget())
    return seen


def is_alive(obj) -> bool:
    import shiboken6

    return shiboken6.isValid(obj)


def contrast(a, b) -> float:
    """Tỉ lệ tương phản WCAG 2.x, tính độc lập với `theme.contrast_ratio`."""

    def lum(c) -> float:
        def ch(v: float) -> float:
            v /= 255
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Spy:
    """Ghi mọi signal công khai của `SettingsPage` (spec 1.6)."""

    NAMES = (
        "name_submitted",
        "visible_toggled",
        "language_selected",
        "autostart_toggled",
        "rate_limit_changed",
        "retention_changed",
        "ask_toggled",
        "unpair_requested",
        "clear_history_requested",
        "export_logs_requested",
        "open_receive_dir_requested",
        "change_receive_dir_requested",
        "discover_requested",
        "open_notices_requested",
        "notice_action",
    )

    def __init__(self, page) -> None:
        self.log: list[tuple] = []
        for name in self.NAMES:
            getattr(page, name).connect(lambda *a, _n=name: self.log.append((_n, *a)))

    def of(self, name: str) -> list[tuple]:
        return [e[1:] for e in self.log if e[0] == name]

    def clear(self) -> None:
        self.log.clear()


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture(autouse=True)
def autostart_supported(monkeypatch):
    """Trang dựng như trên một máy hỗ trợ tự khởi động (hàng hiện), trừ test tự vá lại."""
    from teleport.app import autostart

    monkeypatch.setattr(autostart, "supported", lambda: True)


@pytest.fixture
def ui(qtbot):
    """`SettingsPage` đứng riêng 980x660, đang hiện, `DeviceListModel` thật, đã nạp giá trị mặc định."""
    from teleport.app.autostart import AutostartState
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import SettingsPage

    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.resize(980, 660)
    page.show()
    qtbot.waitExposed(page)

    def load(snap=None, *, autostart=AutostartState.OFF) -> None:
        page.set_loaded(True)
        page.set_values(snap or snapshot())
        page.set_language(None, ("vi",))
        page.set_autostart(autostart)
        settle(qtbot)

    def devices(views) -> None:
        model.reset(views)
        settle(qtbot)

    load()
    spy = Spy(page)
    return SimpleNamespace(page=page, model=model, qtbot=qtbot, load=load, devices=devices, spy=spy)


@pytest.fixture
def win(qtbot, tmp_path):
    """`MainWindow` ở RUNNING có trang SETTINGS (dựng như `GuiApp`, 1.7), 980x660, active."""
    from teleport.app.autostart import AutostartState
    from teleport.ui.main_window import MainWindow, Page
    from teleport.ui.settings import SettingsPage

    w = MainWindow()
    qtbot.addWidget(w)
    page = SettingsPage(w.devices, w.pages)  # B2: `radar` → `devices`
    w.add_page(Page.SETTINGS, page)
    w.show_running("May-A", tmp_path / "nhan")
    page.set_loaded(True)
    page.set_values(snapshot())
    page.set_autostart(AutostartState.OFF)
    w.resize(980, 660)
    activate(qtbot, w)
    return SimpleNamespace(window=w, page=page)


def open_settings(qtbot, w) -> None:
    from teleport.ui.main_window import Page

    w.settings_button.setFocus(Qt.FocusReason.OtherFocusReason)
    w.settings_button.click()
    settle(qtbot)
    assert w.current_page is Page.SETTINGS


# =================================================================================================
# Bố cục, điều hướng
# =================================================================================================


def test_nav_six_sections_order_icons_names(qtbot, monkeypatch):
    from teleport.ui import icons
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import Section, SettingsPage

    requested: list[tuple[str, int]] = []
    real_pixmap, real_icon = icons.pixmap, icons.icon

    def spy_pixmap(name, size, *a, **k):
        requested.append((name, size))
        return real_pixmap(name, size, *a, **k)

    def spy_icon(name, size, *a, **k):
        requested.append((name, size))
        return real_icon(name, size, *a, **k)

    monkeypatch.setattr(icons, "pixmap", spy_pixmap)
    monkeypatch.setattr(icons, "icon", spy_icon)
    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.show()
    settle(qtbot)

    assert page.objectName() == "settingsPage"
    assert page.nav.objectName() == "settingsNav"
    names = ["GENERAL", "APPEARANCE", "PRIVACY", "DEVICES", "TRANSFER", "ADVANCED"]
    assert [s.name for s in Section] == names
    assert page.nav.count() == 6
    assert [page.nav.item(i).text() for i in range(6)] == list(NAV)
    assert all(not page.nav.item(i).icon().isNull() for i in range(6))
    for name in NAV_ICONS:
        assert (name, 20) in requested, f"icon {name!r} cỡ 20 của nav (9.2)"
    assert page.sections.count() == 6
    assert page.nav.width() == 184 or page.nav.maximumWidth() == 184 or page.nav.minimumWidth() == 184
    assert TITLE in joined(page)


def test_nav_arrow_keys_switch_section(ui):
    page = ui.page
    activate(ui.qtbot, page)
    page.nav.setCurrentRow(0)
    page.nav.setFocus(Qt.FocusReason.TabFocusReason)
    for want in (1, 2, 3, 4, 5, 5):
        QTest.keyClick(page.nav, Qt.Key.Key_Down)
        assert page.nav.currentRow() == want
        assert page.sections.currentIndex() == want
    QTest.keyClick(page.nav, Qt.Key.Key_Up)
    assert page.sections.currentIndex() == 4


def test_show_section_selects_nav_row(ui):
    for name in ("ADVANCED", "DEVICES", "GENERAL"):
        open_section(ui.page, name)
        assert ui.page.nav.currentRow() == section_index(name)


def test_focus_proxy_is_nav_on_open(win, qtbot):
    open_settings(qtbot, win.window)
    assert QApplication.focusWidget() is win.page.nav


def test_settings_page_escape_on_nav_goes_back(win, qtbot):
    from teleport.ui.main_window import Page

    open_settings(qtbot, win.window)
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    settle(qtbot)
    assert win.window.current_page is Page.HOME


# =================================================================================================
# Nạp giá trị, signal
# =================================================================================================


def _controls(page) -> list[QWidget]:
    return [
        page.name_edit,
        page.language_combo,
        page.visible_switch,
        page.clear_history_button,
        page.rate_checkbox,
        page.retention_spin,
    ]


def test_controls_disabled_until_loaded(ui):
    page = ui.page
    page.set_loaded(False)
    assert all(not w.isEnabled() for w in _controls(page)), [w.objectName() for w in _controls(page)]
    page.set_loaded(True)
    assert all(w.isEnabled() for w in _controls(page))


def test_set_values_emits_nothing(ui):
    from teleport.app.autostart import AutostartState
    from teleport.app.settings import DeviceSettings

    page = ui.page
    b = view("May-B")
    ui.devices([b])
    page.set_values(
        snapshot(
            name="Khác",
            visible=False,
            rate_limit=5 * MB,
            temp_retention_days=30,
            language="vi",
            autostart=True,
            devices={b.device_id: DeviceSettings(ask_before_receive=False)},
        )
    )
    page.set_name("Tên mới")
    page.set_visible(True)
    page.set_visible(False)
    page.set_language("vi", ("vi",))
    page.set_language(None, ("vi",))
    for state in (AutostartState.ON, AutostartState.OFF, AutostartState.BLOCKED, None):
        page.set_autostart(state)
    page.set_rate_limit(3 * MB)
    page.set_rate_limit(None)
    page.set_retention(12)
    page.set_retention(None)
    page.set_device_settings({b.device_id: DeviceSettings(ask_before_receive=True)})
    page.set_export_running(True)
    page.set_export_running(False)
    settle(ui.qtbot, 700)  # quá hạn 600 ms của ô số (9.4)
    assert ui.spy.log == []


# =================================================================================================
# Tên thiết bị
# =================================================================================================


def test_name_enter_emits_stripped(ui):
    page = ui.page
    open_section(page, "GENERAL")
    page.name_edit.setFocus()
    page.name_edit.setText("  May Moi  ")
    QTest.keyClick(page.name_edit, Qt.Key.Key_Return)
    assert ui.spy.of("name_submitted") == [("May Moi",)]
    assert not page.name_error.isVisibleTo(page)


@pytest.mark.parametrize(
    ("text", "error"), [("", NAME_EMPTY), ("   ", NAME_EMPTY), ("Ma\x07y", NAME_INVALID)]
)
def test_name_invalid_inline_error_no_signal(ui, text, error):
    page = ui.page
    open_section(page, "GENERAL")
    page.name_edit.setText(text)
    QTest.keyClick(page.name_edit, Qt.Key.Key_Return)
    assert ui.spy.of("name_submitted") == []
    assert page.name_error.isVisibleTo(page)
    assert page.name_error.text() == error
    assert page.name_edit.text() == text, "giữ chữ người dùng đã gõ"


def test_set_name_error_shows_and_clears(ui):
    page = ui.page
    open_section(page, "GENERAL")
    page.set_name_error(NAME_INVALID)
    assert page.name_error.isVisibleTo(page) and page.name_error.text() == NAME_INVALID
    assert page.name_error.textFormat() == Qt.TextFormat.PlainText
    page.set_name_error(None)
    assert not page.name_error.isVisibleTo(page)


def _escape_override(edit) -> bool:
    ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    ev.ignore()
    QApplication.sendEvent(edit, ev)
    return ev.isAccepted()


def test_name_escape_with_edit_reverts_and_stays(win, qtbot):
    from teleport.ui.main_window import Page

    open_settings(qtbot, win.window)
    edit = win.page.name_edit
    edit.setFocus(Qt.FocusReason.TabFocusReason)
    assert not _escape_override(edit), "chữ trùng tên đã lưu: Esc để cửa sổ quay lại"
    edit.setText("May-Dang-Sua")
    assert _escape_override(edit), "chữ khác tên đã lưu: ô tên giữ Esc"
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    settle(qtbot)
    assert edit.text() == "May-A"
    assert win.window.current_page is Page.SETTINGS


def test_name_escape_unedited_goes_back(win, qtbot):
    from teleport.ui.main_window import Page

    open_settings(qtbot, win.window)
    edit = win.page.name_edit
    edit.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(edit, Qt.Key.Key_Escape)
    settle(qtbot)
    assert win.window.current_page is Page.HOME


def test_name_hint_visible_vs_hidden(ui):
    page = ui.page
    general = open_section(page, "GENERAL")
    page.set_visible(True)
    text = joined(general)
    assert NAME_LABEL in text
    assert F1 in text, "gợi ý = nguyên câu F1 (docs/mvp.md)"
    assert NAME_HIDDEN not in text
    page.set_visible(False)
    text = joined(general)
    assert NAME_HIDDEN in text
    assert F1 not in text


# =================================================================================================
# Quyền riêng tư, công tắc
# =================================================================================================


def test_visible_switch_emits_and_f10_line_always_shown(ui):
    page = ui.page
    privacy = open_section(page, "PRIVACY")
    assert page.visible_switch.isChecked()
    assert VISIBLE in joined(privacy)
    assert F10 in joined(privacy)
    page.visible_switch.click()
    assert ui.spy.of("visible_toggled") == [(False,)]
    page.set_visible(False)
    assert F10 in joined(privacy), "câu F10 hiện ở cả hai trạng thái"
    page.visible_switch.click()
    assert ui.spy.of("visible_toggled") == [(False,), (True,)]
    assert page.visible_switch.accessibleName() == VISIBLE


def test_hidden_extra_line_only_when_off(ui):
    page = ui.page
    privacy = open_section(page, "PRIVACY")
    page.set_visible(True)
    assert HIDDEN_LINE not in joined(privacy)
    page.set_visible(False)
    assert HIDDEN_LINE in joined(privacy)
    assert not page.visible_switch.isChecked()


def test_history_row_texts_and_clear_button(ui):
    page = ui.page
    privacy = open_section(page, "PRIVACY")
    text = joined(privacy)
    assert HISTORY in text and HISTORY_HINT in text
    assert plain(page.clear_history_button.text()) == CLEAR_HISTORY
    page.clear_history_button.click()
    assert ui.spy.of("clear_history_requested") == [()]


def test_toggle_switch_space_toggles_and_state_text(qtbot):
    from teleport.ui.widgets import ToggleSwitch

    sw = ToggleSwitch()
    qtbot.addWidget(sw)
    sw.setAccessibleName("Thử")
    activate(qtbot, sw)
    assert sw.isCheckable()
    assert sw.focusPolicy() == Qt.FocusPolicy.StrongFocus
    seen: list[bool] = []
    sw.toggled.connect(seen.append)
    assert not sw.isChecked() and sw.state_text() == "Tắt"
    sw.setFocus()
    QTest.keyClick(sw, Qt.Key.Key_Space)
    assert sw.isChecked() and sw.state_text() == "Bật"
    QTest.keyClick(sw, Qt.Key.Key_Return)
    assert not sw.isChecked()
    QTest.keyClick(sw, Qt.Key.Key_Enter)
    assert sw.isChecked()
    assert seen == [True, False, True]
    sw.setEnabled(False)
    QTest.keyClick(sw, Qt.Key.Key_Space)
    assert sw.isChecked(), "công tắc tắt hẳn không đảo"
    assert sw.width() >= 40 and sw.height() >= 20


@pytest.mark.parametrize("dark", [False, True])
def test_toggle_switch_contrast_light_dark(qtbot, ui_theme, dark):
    from PySide6.QtGui import QColor

    from teleport.ui.widgets import ToggleSwitch

    t = ui_theme(dark)
    assert contrast(t.border_strong, t.surface) >= 3.0, "viền khi tắt ≥ 3:1 với surface"
    assert contrast(t.accent_strong, t.surface) >= 3.0, "nền khi bật ≥ 3:1 với surface"

    host = QWidget()
    qtbot.addWidget(host)
    host.setAutoFillBackground(True)
    sw = ToggleSwitch(host)
    host.resize(200, 60)
    host.show()
    qtbot.waitExposed(host)

    def colors(checked: bool) -> set[int]:
        sw.setChecked(checked)
        settle(qtbot, 10)
        img = sw.grab().toImage()
        return {img.pixel(x, y) for x in range(img.width()) for y in range(img.height())}

    off, on = colors(False), colors(True)
    assert QColor(t.border_strong).rgb() in off, "khi tắt phải vẽ viền border_strong"
    assert QColor(t.accent_strong).rgb() in on, "khi bật phải tô nền accent_strong"


# =================================================================================================
# Ngôn ngữ, tự khởi động
# =================================================================================================


def combo_items(combo: QComboBox) -> list[tuple[str, object]]:
    return [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]


def test_language_combo_system_plus_available_endonyms(ui):
    page = ui.page
    open_section(page, "GENERAL")
    combo = page.language_combo
    page.set_language(None, ("vi",))
    assert combo_items(combo) == [(SYSTEM_LANGUAGE, None), ("Tiếng Việt", "vi")]
    assert combo.currentIndex() == 0
    page.set_language("en", ("en", "vi"))
    assert [t for t, _ in combo_items(combo)] == [SYSTEM_LANGUAGE, "English", "Tiếng Việt"]
    assert combo.currentText() == "English"
    assert ui.spy.log == []
    combo.setCurrentIndex([d for _, d in combo_items(combo)].index("vi"))
    combo.activated.emit(combo.currentIndex())
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert ui.spy.of("language_selected") == [("vi",), (None,)]
    assert page.language_combo.accessibleName() == LANGUAGE


def test_language_unknown_saved_code_shown_as_code(ui):
    page = ui.page
    page.set_language("fr", ("vi",))
    combo = page.language_combo
    assert combo.currentText() == "fr"
    assert combo.currentData() == "fr"
    assert ("Tiếng Việt", "vi") in combo_items(combo)
    assert ui.spy.log == []


def test_autostart_row_hidden_when_unsupported(qtbot, monkeypatch):
    from teleport.app import autostart
    from teleport.app.autostart import AutostartState
    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import SettingsPage

    monkeypatch.setattr(autostart, "supported", lambda: False)
    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.show()
    page.set_loaded(True)
    page.set_values(snapshot())
    page.set_autostart(AutostartState.UNSUPPORTED)
    general = open_section(page, "GENERAL")
    assert not page.autostart_switch.isVisibleTo(page)
    assert AUTOSTART not in joined(general)


def test_autostart_row_shown_and_toggle_emits(ui):
    from teleport.app.autostart import AutostartState

    page = ui.page
    general = open_section(page, "GENERAL")
    page.set_autostart(AutostartState.OFF)
    assert page.autostart_switch.isVisibleTo(page)
    assert AUTOSTART in joined(general) and AUTOSTART_HINT in joined(general)
    assert not page.autostart_switch.isChecked()
    page.set_autostart(AutostartState.ON)
    assert page.autostart_switch.isChecked()
    page.autostart_switch.click()
    assert ui.spy.of("autostart_toggled") == [(False,)]
    assert page.autostart_switch.accessibleName() == AUTOSTART


def test_autostart_blocked_other_and_read_error_hints(ui):
    from teleport.app.autostart import AutostartState

    page = ui.page
    general = open_section(page, "GENERAL")
    cases = {
        AutostartState.BLOCKED: AUTOSTART_BLOCKED,
        AutostartState.OTHER: AUTOSTART_OTHER,
        None: AUTOSTART_READ_ERROR,
    }
    for state, text in cases.items():
        page.set_autostart(state)
        shown = joined(general)
        assert text in shown, f"{state}: thiếu câu {text!r}"
        others = [t for s, t in cases.items() if s != state]
        assert not any(t in shown for t in others), f"{state}: còn câu của trạng thái khác"
        assert not page.autostart_switch.isChecked(), f"{state}: công tắc tắt (bật để sửa)"
    page.set_autostart(AutostartState.ON)
    shown = joined(general)
    assert not any(t in shown for t in cases.values())


# =================================================================================================
# Truyền file: ô số (9.1, 9.4)
# =================================================================================================


def _type_into(spin, text: str) -> None:
    spin.setFocus()
    line = spin.lineEdit()
    line.selectAll()
    QTest.keyClicks(line, text)


def test_rate_limit_checkbox_and_spin_emit_bytes(ui):
    from teleport.app.transfers import MIN_RATE_LIMIT

    page = ui.page
    activate(ui.qtbot, page)
    open_section(page, "TRANSFER")
    assert RATE in joined(page.sections.currentWidget())
    assert plain(page.rate_checkbox.text()) == RATE_CHECK
    spin = page.rate_spin
    assert spin.decimals() == 1
    assert spin.suffix() == " MB/s"
    assert spin.minimum() == pytest.approx(0.1)
    assert not page.rate_checkbox.isChecked()

    page.rate_checkbox.click()
    [(value,)] = ui.spy.of("rate_limit_changed")
    assert value == max(round(spin.value() * MB), MIN_RATE_LIMIT)
    assert isinstance(value, int)
    ui.spy.clear()

    _type_into(spin, "25")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ui.spy.of("rate_limit_changed") == [(25 * MB,)]
    ui.spy.clear()

    page.rate_checkbox.click()
    assert ui.spy.of("rate_limit_changed") == [(None,)]


def test_rate_limit_minimum_is_clamped_to_app_minimum(ui):
    from teleport.app.transfers import MIN_RATE_LIMIT

    page = ui.page
    page.set_rate_limit(5 * MB)
    activate(ui.qtbot, page)
    open_section(page, "TRANSFER")
    spin = page.rate_spin
    spin.setFocus()
    spin.setValue(spin.minimum())  # như người dùng kéo xuống mức thấp nhất rồi Enter
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    settle(ui.qtbot, 700)
    sent = [v for (v,) in ui.spy.of("rate_limit_changed")]
    assert sent == [max(round(spin.minimum() * MB), MIN_RATE_LIMIT)], "đổi từ 5 MB/s xuống mức tối thiểu"
    assert sent[0] >= MIN_RATE_LIMIT


def test_rate_limit_display_rounds_without_emitting(ui):
    page = ui.page
    page.set_rate_limit(1_500_000)  # 1,43 MB/s
    assert page.rate_checkbox.isChecked()
    assert page.rate_spin.value() == pytest.approx(1.4)
    page.set_rate_limit(None)
    assert not page.rate_checkbox.isChecked()
    settle(ui.qtbot, 700)
    assert ui.spy.of("rate_limit_changed") == []


def test_spin_typing_emits_once_on_commit(ui):
    """9.4: gõ từng ký tự không phát; Enter/mất tiêu điểm phát đúng một lần; bằng giá trị đã xác nhận thì
    không phát; mũi tên phát một lần sau 600 ms không đổi."""
    page = ui.page
    page.set_rate_limit(2 * MB)
    page.set_retention(10)
    activate(ui.qtbot, page)
    open_section(page, "TRANSFER")

    spin = page.rate_spin
    _type_into(spin, "123")
    settle(ui.qtbot, 700)
    assert ui.spy.of("rate_limit_changed") == [], "đang gõ: chưa phát"
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    settle(ui.qtbot, 700)
    assert ui.spy.of("rate_limit_changed") == [(123 * MB,)]
    page.retention_spin.setFocus()  # mất tiêu điểm sau khi đã chốt: không phát lại
    settle(ui.qtbot, 700)
    assert ui.spy.of("rate_limit_changed") == [(123 * MB,)]

    days = page.retention_spin
    _type_into(days, "3")
    _type_into(days, "30")
    settle(ui.qtbot, 50)
    assert ui.spy.of("retention_changed") == []
    page.rate_spin.setFocus()  # mất tiêu điểm = chốt
    settle(ui.qtbot, 50)
    assert ui.spy.of("retention_changed") == [(30,)]

    ui.spy.clear()
    page.set_retention(10)
    days.setFocus()
    for _ in range(3):
        QTest.keyClick(days, Qt.Key.Key_Up)
    settle(ui.qtbot, 200)
    assert ui.spy.of("retention_changed") == [], "mũi tên: chờ 600 ms không đổi"
    ui.qtbot.waitUntil(lambda: ui.spy.of("retention_changed") != [], timeout=3000)
    settle(ui.qtbot, 700)
    assert ui.spy.of("retention_changed") == [(13,)]

    ui.spy.clear()
    _type_into(days, "13")
    QTest.keyClick(days.lineEdit(), Qt.Key.Key_Return)
    settle(ui.qtbot, 700)
    assert ui.spy.of("retention_changed") == [], "bằng giá trị đã xác nhận: không phát"


def test_retention_seven_maps_to_none(ui):
    from teleport.app import settings as app_settings

    page = ui.page
    default = default_retention_days()
    spin = page.retention_spin
    assert spin.minimum() == app_settings.MIN_RETENTION_DAYS
    assert spin.maximum() == app_settings.MAX_RETENTION_DAYS
    assert spin.suffix() == " ngày"
    page.set_retention(None)
    assert spin.value() == default
    page.set_retention(20)
    activate(ui.qtbot, page)
    open_section(page, "TRANSFER")
    assert RETENTION in joined(page.sections.currentWidget())
    _type_into(spin, str(default))
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ui.spy.of("retention_changed") == [(None,)], "bằng mặc định → None"
    page.set_retention(None)
    _type_into(spin, "45")
    QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return)
    assert ui.spy.of("retention_changed") == [(None,), (45,)]


# =================================================================================================
# Thiết bị tin cậy
# =================================================================================================


def test_device_rows_paired_only_sorted_offline_kept(ui):
    page = ui.page
    open_section(page, "DEVICES")
    zeta = view("zeta")
    alpha_off = view("Alpha", online=False)
    e_nfd = view(unicodedata.normalize("NFD", "Émile"))
    e_nfc_same = view("émile", device_id="0" * 32)
    unpaired = view("Bbb", paired=False)
    ui.devices([zeta, unpaired, alpha_off, e_nfd, e_nfc_same])
    got = [r.device_id for r in device_rows(page)]
    want = sorted(
        [zeta, alpha_off, e_nfd, e_nfc_same],
        key=lambda v: (unicodedata.normalize("NFC", v.name).casefold(), v.device_id),
    )
    assert got == [v.device_id for v in want]
    assert unpaired.device_id not in got
    assert DEVICES_INTRO in joined(page.sections.currentWidget())


def test_device_rows_are_reused_by_device_id(ui):
    page = ui.page
    open_section(page, "DEVICES")
    a, b = view("a"), view("b")
    ui.devices([a, b])
    row_a = row_of(page, a.device_id)
    ui.devices([a, b, view("c")])
    assert row_of(page, a.device_id) is row_a


def test_device_row_accessible_name_name_os_status(ui):
    page = ui.page
    open_section(page, "DEVICES")
    c = view("May-C", connected=True, os="windows")
    o = view("May-O", os="macos")
    f = view("May-F", online=False, os="linux")
    u = view("May-U", os=None)
    ui.devices([c, o, f, u])
    assert row_of(page, c.device_id).accessibleName() == f"May-C, Windows, {ST_CONNECTED}"
    assert row_of(page, o.device_id).accessibleName() == f"May-O, macOS, {ST_ONLINE}"
    assert row_of(page, f.device_id).accessibleName() == f"May-F, Linux, {ST_OFFLINE}"
    name_u = row_of(page, u.device_id).accessibleName()
    assert name_u.startswith("May-U") and ST_ONLINE in name_u and "None" not in name_u
    row_c = row_of(page, c.device_id)
    assert f"Windows · {ST_CONNECTED}" in joined(row_c)
    assert ASK in joined(row_c) and UNPAIR in joined(row_c)


@pytest.mark.parametrize("name", ["<b>html</b>", "<img src=x>", "PC‮gnp.exe", "A\nB", "M" * 300])
def test_device_row_hostile_name_plain_and_safe_tooltip(ui, name):
    page = ui.page
    open_section(page, "DEVICES")
    v = view(name)
    ui.devices([v])
    row = row_of(page, v.device_id)
    for label in row.findChildren(QLabel):
        if label.text():
            assert label.textFormat() == Qt.TextFormat.PlainText
    for w in [row, *row.findChildren(QWidget)]:
        tip = w.toolTip()
        if tip and "<" in name:
            assert "<b>" not in tip and "<img" not in tip, f"tooltip chứa thẻ thô của tên máy: {tip!r}"
        if tip and "M" * 50 in tip:
            assert tip.startswith("<qt>"), "tooltip chứa chữ của máy khác phải qua safe_tooltip"
    assert row.width() <= page.width(), "tên rất dài không làm hàng rộng hơn trang"


def test_ask_checkbox_emits_id_and_value(ui):
    from teleport.app.settings import DeviceSettings

    page = ui.page
    open_section(page, "DEVICES")
    b, c = view("May-B"), view("May-C")
    ui.devices([b, c])
    page.set_device_settings({b.device_id: DeviceSettings(ask_before_receive=False)})
    row_b, row_c = row_of(page, b.device_id), row_of(page, c.device_id)
    assert not row_b.ask_checkbox.isChecked()
    assert row_c.ask_checkbox.isChecked(), "không có mục → mặc định hỏi"
    assert ui.spy.log == []
    row_b.ask_checkbox.click()
    row_c.ask_checkbox.click()
    assert ui.spy.of("ask_toggled") == [(b.device_id, True), (c.device_id, False)]


def test_unpair_button_emits_id(ui):
    page = ui.page
    open_section(page, "DEVICES")
    b = view("May-B", online=False)
    ui.devices([b])
    row = row_of(page, b.device_id)
    assert plain(row.unpair_button.text()) == UNPAIR
    row.unpair_button.click()
    assert ui.spy.of("unpair_requested") == [(b.device_id,)]


def _unpaired(v):
    import dataclasses

    return dataclasses.replace(v, paired=False, connected=False)


def test_removed_row_focus_moves_next_then_prev_then_empty(ui):
    page = ui.page
    activate(ui.qtbot, page)
    open_section(page, "DEVICES")
    a, b, c = view("a"), view("b"), view("c")
    ui.devices([a, b, c])
    row_of(page, b.device_id).unpair_button.setFocus(Qt.FocusReason.TabFocusReason)
    ui.devices([a, _unpaired(b), c])
    focus = QApplication.focusWidget()
    assert focus is not None and is_alive(focus)
    assert row_of(page, c.device_id).isAncestorOf(focus) or focus is row_of(page, c.device_id)
    ui.devices([a])
    focus = QApplication.focusWidget()
    assert row_of(page, a.device_id).isAncestorOf(focus) or focus is row_of(page, a.device_id)
    ui.devices([])
    focus = QApplication.focusWidget()
    assert focus is not None and plain(getattr(focus, "text", lambda: "")()) == DISCOVER


def test_devices_empty_state_requests_discover(ui):
    page = ui.page
    devices = open_section(page, "DEVICES")
    ui.devices([view("x", paired=False)])
    text = joined(devices)
    assert EMPTY_TITLE in text and EMPTY_TEXT in text
    [button] = buttons_with_text(devices, DISCOVER)
    button.click()
    assert ui.spy.of("discover_requested") == [()]
    ui.devices([view("May-B")])
    assert EMPTY_TITLE not in joined(devices)


def test_devices_empty_state_shows_not_paired_illustration(ui):
    """Spec G6 tiêu chí 8: Cài đặt › Thiết bị rỗng (`trustedEmpty`) có minh họa NOT_PAIRED."""
    from teleport.ui.illustrations import Scene
    from teleport.ui.widgets import EmptyState

    page = ui.page
    devices = open_section(page, "DEVICES")
    ui.devices([])
    empty = page.findChild(EmptyState, "trustedEmpty")
    assert empty is not None and empty.isVisibleTo(devices)
    assert empty.illustration.isVisibleTo(devices)
    assert empty.illustration.scene is Scene.NOT_PAIRED
    assert not empty.icon_badge.isVisibleTo(devices)


def test_no_check_updates_control(ui):
    """Ô “Đồng bộ clipboard” đã có từ D5 (test ở `test_clipboard_ui.py`); “Kiểm tra cập nhật” vẫn chưa."""
    page = ui.page
    ui.devices([view("May-B")])
    for name in ("GENERAL", "PRIVACY", "DEVICES", "TRANSFER", "ADVANCED"):
        section = open_section(page, name)
        text = " | ".join(
            plain(b.text()) for b in section.findChildren(QAbstractButton) if b.isVisibleTo(section)
        ).casefold()
        assert "kiểm tra cập nhật" not in text, f"{name}: “Kiểm tra cập nhật” thuộc GĐ6"


# =================================================================================================
# Thư mục nhận, nâng cao
# =================================================================================================


def test_receive_dir_row_normal_pending_unavailable(ui, tmp_path):
    from teleport.ui.send import printable
    from teleport.ui.widgets import safe_tooltip

    page = ui.page
    general = open_section(page, "GENERAL")
    d = tmp_path / "Nhận file"
    page.set_receive_dir(d)
    assert RECEIVE_DIR in joined(general)
    label = page.receive_dir_label
    assert label.toolTip() == safe_tooltip(printable(str(d))) or printable(str(d)) in label.toolTip()
    assert page.open_dir_button.isVisibleTo(page) and page.open_dir_button.isEnabled()
    assert plain(page.open_dir_button.text()) == OPEN
    page.open_dir_button.click()
    [(arg,)] = ui.spy.of("open_receive_dir_requested")
    assert Path(arg) == d

    pending = tmp_path / "Thư mục mới"
    page.set_receive_dir(d, pending=pending)
    assert printable(str(pending)) in label.toolTip() or pending.name in label.text()

    bad = tmp_path / "Ổ đã rút"
    page.set_receive_dir(None, unavailable=bad)
    assert printable(str(bad)) in label.toolTip() or bad.name in label.text()
    assert not (page.open_dir_button.isVisibleTo(page) and page.open_dir_button.isEnabled()), (
        "không có thư mục nhận: không mở được"
    )


def test_receive_dir_label_elides_middle_for_long_path(ui, tmp_path):
    page = ui.page
    open_section(page, "GENERAL")
    d = tmp_path / ("rất-dài-" * 40) / "cuối"
    page.set_receive_dir(d)
    settle(ui.qtbot)
    label = page.receive_dir_label
    assert label.width() <= page.width()
    assert label.text().endswith("cuối") or "…" in label.text()


def test_change_dir_button_hidden_until_available(ui, tmp_path):
    page = ui.page
    open_section(page, "GENERAL")
    page.set_receive_dir(tmp_path)
    assert not page.change_dir_button.isVisibleTo(page)
    page.set_change_available(True)
    assert page.change_dir_button.isVisibleTo(page)
    assert plain(page.change_dir_button.text()) == CHANGE
    page.change_dir_button.click()
    assert ui.spy.of("change_receive_dir_requested") == [()]
    page.set_change_available(False)
    assert not page.change_dir_button.isVisibleTo(page)


def test_export_button_disabled_while_running(ui):
    page = ui.page
    advanced = open_section(page, "ADVANCED")
    assert plain(page.export_button.text()) == EXPORT
    page.export_button.click()
    assert ui.spy.of("export_logs_requested") == [()]
    page.set_export_running(True)
    assert not page.export_button.isEnabled()
    assert EXPORTING in joined(advanced)
    page.set_export_running(False)
    assert page.export_button.isEnabled()
    assert plain(page.export_button.text()) == EXPORT


def test_advanced_shows_version_protocol_and_license(ui):
    import teleport
    from teleport.core.messages import PROTOCOL_VERSION

    text = joined(open_section(ui.page, "ADVANCED"))
    assert VERSION in text
    assert f"Teleport {teleport.__version__} · giao thức {PROTOCOL_VERSION}" in text
    assert LICENSE in text


@pytest.mark.parametrize("exists", [False, True])
def test_notices_button_only_when_file_exists(qtbot, monkeypatch, tmp_path, exists):
    import sys

    from teleport.ui.radar import DeviceListModel
    from teleport.ui.settings import SettingsPage

    exe = tmp_path / "Teleport.exe"
    exe.write_bytes(b"")
    if exists:
        (tmp_path / "THIRD-PARTY-NOTICES.txt").write_text("x", encoding="utf-8")
    monkeypatch.setattr(sys, "executable", str(exe))
    model = DeviceListModel()
    page = SettingsPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.show()
    open_section(page, "ADVANCED")
    assert page.notices_button.isVisibleTo(page) is exists
    if exists:
        assert plain(page.notices_button.text()) == NOTICES
        seen: list = []
        page.open_notices_requested.connect(seen.append)
        page.notices_button.click()
        assert len(seen) == 1
        target = seen[0].toLocalFile() if hasattr(seen[0], "toLocalFile") else str(seen[0])
        assert Path(target) == tmp_path / "THIRD-PARTY-NOTICES.txt"


# =================================================================================================
# Bàn phím, ngôn ngữ, thông báo, cỡ
# =================================================================================================


def test_tab_order_back_nav_then_section_controls(ui):
    page = ui.page
    activate(ui.qtbot, page)
    open_section(page, "GENERAL")
    page.header.back_button.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(2)
    assert seen[0] is page.nav
    assert seen[1] is page.name_edit, "info_bar ẩn: sau nav là control đầu của mục đang mở"

    page.show_notice(_level("ERROR"), "Lỗi thử")
    settle(ui.qtbot)
    page.header.back_button.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(4)
    assert seen[0] is page.nav
    assert page.info_bar.isAncestorOf(seen[1]) or seen[1] is page.info_bar, "nav → info_bar"


def test_tab_reaches_device_rows_then_empty_button(ui):
    page = ui.page
    activate(ui.qtbot, page)
    open_section(page, "DEVICES")
    ui.devices([view("a"), view("b")])
    page.nav.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(8)
    rows = device_rows(page)
    hit = [next((i for i, w in enumerate(seen) if r.isAncestorOf(w) or w is r), None) for r in rows]
    assert None not in hit, "Tab phải tới mọi hàng thiết bị"
    assert hit == sorted(hit), "theo thứ tự hàng"


def _level(name: str):
    from teleport.ui.widgets import InfoLevel

    return InfoLevel[name]


def test_language_change_retranslates_keeps_selection(ui):
    page = ui.page
    page.set_language("vi", ("vi",))
    open_section(page, "PRIVACY")
    translator = PrefixTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        ui.qtbot.waitUntil(lambda: page.nav.item(0).text().startswith(PREFIX), timeout=3000)
        assert page.language_combo.currentData() == "vi", "giữ lựa chọn"
        assert page.language_combo.itemText(0).startswith(PREFIX)
        assert page.sections.currentIndex() == section_index("PRIVACY")
        assert page.visible_switch.isChecked()
    finally:
        QCoreApplication.removeTranslator(translator)
    ui.qtbot.waitUntil(lambda: page.nav.item(0).text() == NAV[0], timeout=3000)
    assert ui.spy.log == [], "dịch lại không phát signal"


def test_info_bar_cleared_on_nonspontaneous_hide(ui):
    page = ui.page
    page.show_notice(_level("ERROR"), "Lỗi thử")
    assert not page.info_bar.isHidden()
    page.hide()
    settle(ui.qtbot)
    page.show()
    settle(ui.qtbot)
    assert page.info_bar.isHidden()


def test_show_notice_action_emits_notice_action(ui):
    page = ui.page
    page.show_notice(_level("SUCCESS"), "Đã lưu log vào x.", action="Mở thư mục")
    [button] = buttons_with_text(page.info_bar, "Mở thư mục")
    button.click()
    assert ui.spy.of("notice_action") == [()]


def test_fits_720x460_without_horizontal_scroll(ui):
    page = ui.page
    ui.devices([view("M" * 64), view("May-B", online=False)])
    page.set_receive_dir(Path("C:/") / ("thư-mục-rất-dài-" * 10))
    page.set_change_available(True)
    page.resize(720, 460)
    settle(ui.qtbot, 60)
    for name in ("GENERAL", "APPEARANCE", "PRIVACY", "DEVICES", "TRANSFER", "ADVANCED"):
        w = open_section(page, name)
        settle(ui.qtbot, 30)
        areas = [w] if isinstance(w, QScrollArea) else w.findChildren(QScrollArea)
        assert areas, f"{name}: mỗi mục là một QScrollArea"
        for area in areas:
            bar = area.horizontalScrollBar()
            assert bar.maximum() == 0 or not bar.isVisible(), f"{name}: cuộn ngang ở 720x460"


def test_line_edit_and_spin_are_real_controls(ui):
    assert isinstance(ui.page.name_edit, QLineEdit)
    assert isinstance(ui.page.rate_spin, QAbstractSpinBox)
    assert isinstance(ui.page.retention_spin, QAbstractSpinBox)
