"""Khung hai cột của cửa sổ chính (spec B1, mục 6: L1–L18; mục 12 thắng khi khác).

Viết từ spec, không từ code. Mỗi test ghi mã L.. ở tên hàm. Cửa sổ dựng riêng (không `main()`), trừ L11
(`gui`, chạy node thật trên 127.0.0.1).

Hai cách hiện cửa sổ (`show_window`):
- `WA_DontShowOnScreen` + `show` + `waitExposed` cho test bố cục và màu (spec 12.14);
- cửa sổ không có cờ đó khi test cần cửa sổ active (tiêu điểm, Tab, phím tắt, `focusChanged`): trên
  nền `offscreen`, cửa sổ `WA_DontShowOnScreen` không bao giờ thành active (đã thử), nên `setFocus` và
  phím tắt `WindowShortcut` không chạy.
"""

from __future__ import annotations

import contextlib
import hashlib
import re
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QPoint, QSize, Qt, QTranslator, QUrl
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

# ---- Chữ của spec (2.6, 2.7, 2.8) -----------------------------------------------------------------
THIS_MACHINE = "Máy này"
READY = "Sẵn sàng nhận"
BUSY = "Đang truyền {n} lượt"
COPY = "Chép địa chỉ"
SAVE_PREFIX = "Lưu vào: "
OPEN_DIR = "Mở thư mục"
RECEIVE_DIR = "Thư mục nhận"
DISCOVER = "Tìm máy mới"
SETTINGS = "Cài đặt"
DEVICES = "Thiết bị"
EMPTY_TITLE = "Ghép đôi máy đầu tiên"
EMPTY_TEXT_DISCOVER = "Mở Teleport trên máy kia, trong cùng mạng với máy này, rồi bấm Tìm máy mới."
STARTING_BAR = "Đang khởi động"
TRANSFERS = "Lượt truyền"
ADDRESS_A11Y = "Địa chỉ của máy này"

# ---- Hằng của spec (2.3) --------------------------------------------------------------------------
SIDEBAR_WIDTH = 288
SIDEBAR_COMPACT_WIDTH = 80  # spec B2 mục 12.5 (B1 là 248)
COMPACT_BELOW = 820
START_PANEL_MAX_WIDTH = 460
MIN_W, MIN_H = 720, 460

PEER_ID = "a71c04d2" + "e" * 24


# =================================================================================================
# Dữ liệu giả
# =================================================================================================


def device_id(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()[:32]


def dview(label: str = "PC-Nha", *, paired: bool = False, online: bool = True, connected: bool = False):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id(label),
        name=label,
        os="windows" if online else None,
        paired=paired,
        online=online,
        connected=connected and paired,
        addresses=("192.0.2.7",) if online else (),
        port=47474 if online else None,
    )


def tkey(direction: str = "send", transfer_id: str = "a" * 32, dev: str = PEER_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(dev, Direction(direction), transfer_id)


def tinfo(k, status: str = "transferring"):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    return TransferInfo(
        key=k,
        status=TransferStatus(status),
        files=(FileEntry("video.mp4", 1000, 0),),
        names=("video.mp4",),
        file_index=0,
        done_bytes=0,
        total_bytes=1000,
    )


def status_changed(k, status: str = "transferring"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(tinfo(k, status))


def finished(k, result: str = "done"):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=tinfo(k, "verifying"),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=None,
        reject=None,
    )


def make_page(label: str = "D") -> QWidget:
    """Trang mẫu: một nút, `setFocusProxy` tới nút (như trang thật)."""
    page = QWidget()
    button = QPushButton(f"Nút của trang {label}")
    QVBoxLayout(page).addWidget(button)
    page.setFocusProxy(button)
    return page


def shout(text: str) -> str:
    """Chữ in hoa, giữ nguyên chỗ giữ chỗ `{…}` và `%n`."""
    return "".join(
        p if re.fullmatch(r"\{\w+\}|%n", p) else p.upper() for p in re.split(r"(\{\w+\}|%n)", text)
    )


class ShoutTranslator(QTranslator):
    """Translator giả trả chữ in hoa (như `test_i18n_theme.py`, spec L14)."""

    def isEmpty(self):
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        return shout(source_text) if source_text else source_text


# =================================================================================================
# Fixture, hàm phụ trợ
# =================================================================================================


@pytest.fixture
def make_window(qtbot):
    def make():
        from teleport.ui.main_window import MainWindow

        w = MainWindow()
        qtbot.addWidget(w)
        return w

    return make


@pytest.fixture
def window(make_window):
    return make_window()


@pytest.fixture
def tray(monkeypatch):
    from teleport.ui.tray import Tray

    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: None)
    t = Tray()
    yield t
    t.dispose()


@pytest.fixture
def make_ctl(tray):
    """`make_ctl(window) -> TransfersController` (spec 12.6: không dựng view lượt truyền bằng tay)."""
    made: list = []

    def make(window):
        from teleport.ui.transfers import TransfersController

        ctl = TransfersController(window, tray, parent=None)
        made.append(ctl)
        return ctl

    yield make
    for ctl in made:
        ctl.close_all()


def show_window(window, qtbot, width: int = 980, height: int = 660, *, active: bool = False) -> None:
    """Hiện cửa sổ ở cỡ `width`x`height` (xem docstring module về `active`)."""
    if not active:
        window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    window.resize(width, height)
    window.show()
    qtbot.waitExposed(window)
    if active:
        window.activateWindow()
        window.raise_()
        qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    settle()


def settle() -> None:
    for _ in range(3):
        QApplication.processEvents()


def resize_to(window, width: int, height: int) -> None:
    window.resize(width, height)
    settle()


def layout_holding(layout, widget):
    """Layout (trong cây layout `layout`) chứa trực tiếp `widget`; không có → None."""
    if layout is None:
        return None
    if layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        found = layout_holding(layout.itemAt(i).layout(), widget)
        if found is not None:
            return found
    return None


def visible(widget, window) -> bool:
    return widget.isVisibleTo(window)


def focusable(widget) -> bool:
    return bool(widget.focusPolicy().value & Qt.FocusPolicy.TabFocus.value)


def running(window, tmp_path: Path, name: str | None = "May-A", receive_dir: Path | None = None):
    window.show_running(name, tmp_path / "nhan" if receive_dir is None else receive_dir)
    settle()


def color_at(image, widget, window, point: QPoint) -> str:
    """Màu (dạng #rrggbb) của điểm `point` (tọa độ của `widget`) trên ảnh `window.grab()`."""
    p = widget.mapTo(window, point)
    dpr = image.devicePixelRatio()
    return QColor(image.pixel(round(p.x() * dpr), round(p.y() * dpr))).name()


def fill_l12(window, ctl, tmp_path: Path) -> None:
    """Dựng như L12: trang DISCOVER (luôn có từ B5), máy đã ghép đôi, hai thẻ, một thông báo, có địa chỉ."""
    running(window, tmp_path)
    window.set_addresses(["192.0.2.5"], None)
    window.devices.reset([dview("PC-Nha", paired=True, connected=True)])
    ctl.view.set_device_names({PEER_ID: "PC-Nha"})
    ctl.view.handle(status_changed(tkey("send", "a" * 32)))
    ctl.view.handle(status_changed(tkey("receive", "b" * 32)))
    ctl.view.show_notice("Một thông báo.", "Làm gì đó", lambda: None)
    settle()


def fill_l3_full(window, ctl, tmp_path: Path) -> None:
    """RUNNING đầy đủ của L3: 6 thiết bị, 3 thẻ + thông báo, 3 địa chỉ, thư mục nhận dài 200 ký tự (spec
    B2 mục 8(d): khung nhập IP không còn ở cột trái)."""
    long_dir = Path("C:/" + "r" * 197)
    assert len(str(long_dir)) == 200
    window.show_running("May-A", long_dir)
    window.set_addresses(["192.0.2.5", "192.0.2.6", "192.0.2.7"], 50000)
    window.devices.reset(
        [dview(f"May-{i}", paired=i < 2, connected=i == 0) for i in range(6)],
    )
    ctl.view.set_device_names({PEER_ID: "PC-Nha"})
    for c in "abc":
        ctl.view.handle(status_changed(tkey("send", c * 32)))
    ctl.view.show_notice(
        "Một thông báo khá dài để chiếm vài dòng trong khung lượt truyền.", "Làm", lambda: None
    )
    settle()


# =================================================================================================
# L1 — Cấu trúc
# =================================================================================================


def test_l1_running_shows_shell_and_hides_start_view(window, tmp_path):
    running(window, tmp_path)
    assert window.home_stack.currentWidget() is window.shell
    assert not visible(window.start_view, window)
    assert visible(window.shell, window)


def test_l1_widget_tree_matches_spec(window):
    from teleport.ui import home, widgets

    assert isinstance(window.home_stack, QStackedWidget)
    assert isinstance(window.start_view, home.StartPanel)
    assert isinstance(window.sidebar, QFrame)
    assert isinstance(window.sidebar_scroll, QScrollArea)
    assert isinstance(window.machine_card, home.MachineCard)
    assert isinstance(window.stream_pane, QStackedWidget)
    assert isinstance(window.empty_state, widgets.EmptyState)
    assert isinstance(window.save_bar, home.SaveBar)
    assert isinstance(window.discover_button, widgets.IconButton)
    assert isinstance(window.settings_button, widgets.IconButton)

    assert window.home_page.isAncestorOf(window.home_stack)
    assert window.home_stack.indexOf(window.start_view) >= 0
    assert window.home_stack.indexOf(window.shell) >= 0
    assert window.body.isAncestorOf(window.sidebar)
    assert window.body.isAncestorOf(window.stream_pane)
    for w in (window.conversations, window.machine_card, window.discover_button, window.settings_button):
        assert window.sidebar.isAncestorOf(w), w.objectName()
    assert window.sidebar.isAncestorOf(window.sidebar_header)
    assert window.sidebar_header.isAncestorOf(window.discover_button)
    assert window.sidebar_header.isAncestorOf(window.brand_label)
    assert window.sidebar_header.isAncestorOf(window.brand_logo)
    assert window.sidebar_scroll.widget().isAncestorOf(window.conversations)
    assert window.stream_pane.indexOf(window.empty_state) >= 0
    assert window.stream_pane.indexOf(window.transfers_area) >= 0
    assert not window.body.isAncestorOf(window.save_bar)
    assert window.shell.isAncestorOf(window.save_bar)


def test_l1_shortcut_attributes_point_into_machine_card_and_start_view(window):
    assert window.name_label is window.machine_card.name_label
    assert window.copy_button is window.machine_card.copy_button
    assert window.badge is window.machine_card.badge
    assert window.address_label is window.machine_card.address_label
    assert window.status_icon is window.start_view.status_icon
    assert window.starting_bar is window.start_view.starting_bar
    card = window.start_view.card
    for name in ("title_label", "status_label", "detail_label", "hint_label", "start_button", "retry_button"):
        assert card.isAncestorOf(getattr(window, name)), name


@pytest.mark.parametrize(
    ("attr", "object_name"),
    [
        ("home_stack", "homeStack"),
        ("start_view", "startView"),
        ("shell", "runningShell"),
        ("body", "runningBody"),
        ("sidebar", "sidebar"),
        ("sidebar_header", "sidebarHeader"),
        ("brand_logo", "brandLogo"),
        ("brand_label", "brandLabel"),
        ("sidebar_scroll", "sidebarScroll"),
        ("machine_card", "machineCard"),
        ("stream_pane", "streamPane"),
        ("empty_state", "streamEmpty"),
        ("transfers_area", "transfersArea"),
        ("save_bar", "saveBar"),
        ("address_label", "addressLabel"),
        ("name_label", "machineName"),
        ("copy_button", "copyAddressButton"),
        ("badge", "machineBadge"),
    ],
)
def test_l1_object_names(window, attr, object_name):
    assert getattr(window, attr).objectName() == object_name


def test_l1_surfaces_of_sidebar_and_start_card(window):
    assert window.sidebar.property("surface") == "sidebar"
    card = window.start_view.card
    assert isinstance(card, QFrame)
    assert card.objectName() == "startCard"
    assert card.property("surface") == "card"


def test_l1_save_bar_spans_full_width_below_body(window, qtbot, tmp_path):
    running(window, tmp_path)
    show_window(window, qtbot, 980, 660)
    assert window.save_bar.width() == window.home_page.width()
    assert window.save_bar.geometry().top() >= window.body.geometry().bottom()


def test_l1_old_public_attributes_live_in_home_page_with_same_types(window):
    from teleport.ui.conversations import ConversationList

    labels = ("status_label", "detail_label", "hint_label", "title_label", "address_label")
    for name in labels:
        assert isinstance(getattr(window, name), QLabel), name
    for name in ("start_button", "retry_button"):
        assert isinstance(getattr(window, name), QPushButton), name
    assert isinstance(window.conversations, ConversationList)  # spec B2: thay `radar` (`RadarView`)
    assert not hasattr(window, "radar")
    for name in (*labels, "start_button", "retry_button", "conversations", "transfers_area", "body"):
        assert window.home_page.isAncestorOf(getattr(window, name)), name


# =================================================================================================
# L2 — Bề ngang cột trái
# =================================================================================================


@pytest.mark.parametrize(
    ("width", "expected", "compact"),
    [
        (980, SIDEBAR_WIDTH, False),
        (820, SIDEBAR_WIDTH, False),
        (819, SIDEBAR_COMPACT_WIDTH, True),
        (720, SIDEBAR_COMPACT_WIDTH, True),
    ],
)
def test_l2_sidebar_width_on_show(window, qtbot, tmp_path, width, expected, compact):
    running(window, tmp_path)
    show_window(window, qtbot, width, 660)
    assert window.width() == width
    assert window.sidebar.width() == expected
    assert window.sidebar_compact is compact
    # 12.1: viền phải 1 px nằm trong bề ngang của `sidebar`.
    assert window.sidebar.width() + window.stream_pane.width() == window.body.width()


def test_l2_sidebar_width_follows_resizes(window, qtbot, tmp_path):
    running(window, tmp_path)
    show_window(window, qtbot, 980, 660)
    for width, expected, compact in (
        (720, SIDEBAR_COMPACT_WIDTH, True),
        (820, SIDEBAR_WIDTH, False),
        (819, SIDEBAR_COMPACT_WIDTH, True),
        (1100, SIDEBAR_WIDTH, False),
        (720, SIDEBAR_COMPACT_WIDTH, True),
    ):
        resize_to(window, width, 660)
        assert window.sidebar.width() == expected, width
        assert window.sidebar_compact is compact, width
        assert window.sidebar.width() + window.stream_pane.width() == window.body.width(), width


def test_l2_resize_moves_focus_between_address_label_and_compact_machine(window, qtbot, tmp_path):
    """Spec B2 mục 2.6, 12.25: thu gọn thì `machine_card` ẩn → tiêu điểm sang `compact_machine`; mở rộng
    lại → `name_label`."""
    running(window, tmp_path)
    window.set_addresses(["192.0.2.5"], None)
    show_window(window, qtbot, 980, 660, active=True)
    window.address_label.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(lambda: window.focusWidget() is window.address_label, timeout=1000)
    resize_to(window, 720, 660)
    assert window.sidebar_compact
    assert window.focusWidget() is window.compact_machine
    resize_to(window, 980, 660)
    assert window.focusWidget() is window.name_label


# =================================================================================================
# L3 — Không phình quá 720x460
# =================================================================================================


def _assert_fits(window) -> None:
    assert window.size() == QSize(MIN_W, MIN_H), window.size()
    hint = window.minimumSizeHint()
    assert hint.width() <= MIN_W and hint.height() <= MIN_H, f"nội dung cần tối thiểu {hint}"


@pytest.mark.parametrize("state", ["welcome", "starting", "error"])
def test_l3_start_states_do_not_grow_window(window, qtbot, state):
    {
        "welcome": lambda: window.show_welcome("Laptop-Minh"),
        "starting": window.show_starting,
        "error": lambda: window.show_error("config_dir", "C:\\" + "a" * 200 + "\nAccess denied"),
    }[state]()
    show_window(window, qtbot, MIN_W, MIN_H)
    _assert_fits(window)


def test_l3_full_running_does_not_grow_window(window, qtbot, make_ctl, tmp_path):
    ctl = make_ctl(window)
    show_window(window, qtbot, MIN_W, MIN_H)
    fill_l3_full(window, ctl, tmp_path)
    _assert_fits(window)
    assert_conversations_fit_sidebar(window)


def test_l3_error_with_long_path_scrolls_start_panel_instead(window, qtbot):
    window.show_error("config_dir", "C:\\" + "a" * 200 + "\nAccess denied")
    show_window(window, qtbot, MIN_W, MIN_H)
    scroll = window.start_view.start_scroll
    assert isinstance(scroll, QScrollArea)
    assert window.size() == QSize(MIN_W, MIN_H)
    # 12.15: thanh cuộn ngang AsNeeded (không tắt): đường dẫn dài không dấu cách vẫn xem được.
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


# =================================================================================================
# L4 — Màu (sáng, tối)
# =================================================================================================


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_l4_region_colors(make_window, qtbot, ui_theme, tmp_path, dark):
    t = ui_theme(dark)
    window = make_window()
    running(window, tmp_path, receive_dir=Path("C:/T"))  # thư mục ngắn: điểm giữa `save_bar` là nền
    window.set_addresses(["192.0.2.5"], None)
    show_window(window, qtbot, 980, 660)
    image = window.grab().toImage()

    sidebar, border, surface = t.sidebar.name(), t.border.name(), t.surface.name()
    assert color_at(image, window.sidebar, window, QPoint(200, 4)) == sidebar, "đầu cột"
    assert window.stream_pane.currentWidget() is window.empty_state
    assert color_at(image, window.stream_pane, window, QPoint(8, 8)) == surface, "khung phải"
    bar = window.save_bar
    assert color_at(image, bar, window, QPoint(bar.width() // 2, bar.height() // 2)) == sidebar, (
        "giữa save_bar"
    )
    assert color_at(image, bar, window, QPoint(bar.width() // 2, 0)) == border, "đường kẻ trên save_bar"
    edge = window.sidebar.width() - 1
    wrong = [
        y
        for y in range(window.sidebar.height())
        if color_at(image, window.sidebar, window, QPoint(edge, y)) != border
    ]
    assert not wrong, f"mép phải cột trái không phải `border` ở y = {wrong[:5]}…"
    card = window.machine_card
    assert color_at(image, card, window, QPoint(card.width() // 2, 0)) == border, "đường kẻ trên machine_card"
    # 12.2 (B2 mục 8(d)): nền trong suốt của vùng cuộn và danh sách: điểm trống bên phải nút “＋ Ghép đôi
    # máy mới” (căn trái) là `sidebar`.
    conv = window.conversations
    btn = conv.add_button
    gap = QPoint(conv.width() - 4, btn.mapTo(conv, btn.rect().center()).y())
    assert btn.mapTo(conv, QPoint(btn.width(), 0)).x() < gap.x(), "tiền đề: điểm nằm ngoài nút"
    assert color_at(image, conv, window, gap) == sidebar, "điểm trống của cột trái"


# =================================================================================================
# L5 — Trạng thái
# =================================================================================================


def _apply(window, tmp_path, state: str) -> None:
    {
        "welcome": lambda: window.show_welcome("Laptop-Minh"),
        "starting": window.show_starting,
        "running": lambda: running(window, tmp_path),
        "error": lambda: window.show_error("locked", ""),
    }[state]()
    settle()


@pytest.mark.parametrize("state", ["welcome", "starting", "error"])
def test_l5_start_states_show_start_view_only(window, tmp_path, state):
    _apply(window, tmp_path, "running")
    _apply(window, tmp_path, state)
    assert window.home_stack.currentWidget() is window.start_view
    assert visible(window.start_view, window)
    assert not visible(window.shell, window)
    assert not visible(window.save_bar, window)
    assert visible(window.starting_bar, window) is (state == "starting")


@pytest.mark.parametrize(("width", "height", "check_vertical"), [(980, 660, True), (720, 460, False)])
def test_l5_start_card_is_centered_and_capped(window, qtbot, width, height, check_vertical):
    window.show_welcome("Laptop-Minh")
    show_window(window, qtbot, width, height)
    card, view = window.start_view.card, window.start_view
    viewport = window.start_view.start_scroll.viewport()
    available = viewport.width()
    assert card.width() == min(START_PANEL_MAX_WIDTH, available)
    # Bề ngang: căn giữa vùng thấy (form lần chạy đầu cao hơn 460 px nên có thanh cuộn dọc, spec D1).
    assert abs(card.mapTo(viewport, card.rect().center()).x() - viewport.rect().center().x()) <= 2
    center = card.mapTo(view, card.rect().center())
    if check_vertical:
        assert abs(center.y() - view.rect().center().y()) <= 2


def test_l5_error_state_icon_and_primary_retry(window, tmp_path):
    from teleport.ui import theme

    _apply(window, tmp_path, "error")
    assert visible(window.status_icon, window)
    assert visible(window.retry_button, window)
    assert window.retry_button.property(theme.PRIMARY_PROPERTY) is True
    assert not visible(window.start_button, window)
    assert not visible(window.starting_bar, window)


def test_l5_welcome_state_primary_start_without_icon(window, tmp_path):
    from teleport.ui import theme

    _apply(window, tmp_path, "welcome")
    assert visible(window.start_button, window)
    assert window.start_button.property(theme.PRIMARY_PROPERTY) is True
    assert not visible(window.status_icon, window)
    assert not visible(window.retry_button, window)


def test_l5_starting_state_has_bar_and_no_buttons(window, tmp_path):
    _apply(window, tmp_path, "starting")
    assert visible(window.starting_bar, window)
    assert not visible(window.status_icon, window)
    assert not visible(window.start_button, window)
    assert not visible(window.retry_button, window)


def test_l5_state_sequence_switches_stack_and_focus(window, qtbot, tmp_path):
    show_window(window, qtbot, 980, 660, active=True)
    steps = [
        ("welcome", lambda: window.start_view, lambda: window.first_run.name_edit),  # spec D1 mục 4
        ("starting", lambda: window.start_view, lambda: window.status_label),
        ("running", lambda: window.shell, lambda: window.conversations.add_button),  # chưa có máy
        ("error", lambda: window.start_view, lambda: window.retry_button),
        ("starting", lambda: window.start_view, lambda: window.status_label),
    ]
    for state, page, focus in steps:
        _apply(window, tmp_path, state)
        assert window.home_stack.currentWidget() is page(), state
        assert window.focusWidget() is focus(), (state, window.focusWidget())
    # RUNNING khi có máy đã ghép đôi: tiêu điểm vào danh sách.
    window.devices.reset([dview("PC-Nha", paired=True)])
    _apply(window, tmp_path, "running")
    assert window.home_stack.currentWidget() is window.shell
    assert window.focusWidget() is window.conversations.list_view


# =================================================================================================
# L6 — Nút đầu cột
# =================================================================================================


def test_l6_header_buttons_hidden_without_pages(window, tmp_path):
    """Trang DISCOVER luôn có từ B5 nên nút “Tìm máy mới” luôn hiện; “Cài đặt” chờ trang của nó."""
    from teleport.ui.main_window import Page

    running(window, tmp_path)
    assert visible(window.discover_button, window)
    assert not visible(window.settings_button, window)
    window.discover_button.click()
    assert window.current_page is Page.DISCOVER


@pytest.mark.parametrize("add_first", [True, False], ids=["add-then-run", "run-then-add"])
def test_l6_header_button_appears_with_page_and_opens_it(window, tmp_path, add_first):
    from teleport.ui.main_window import Page

    if add_first:
        window.add_page(Page.SETTINGS, make_page())
        running(window, tmp_path)
    else:
        running(window, tmp_path)
        window.add_page(Page.SETTINGS, make_page())
    assert visible(window.settings_button, window)
    assert visible(window.discover_button, window)
    window.settings_button.click()
    assert window.current_page is Page.SETTINGS


def test_l6_header_buttons_names_and_tooltips(window):
    assert window.discover_button.accessibleName() == DISCOVER
    assert window.settings_button.accessibleName() == SETTINGS
    assert window.discover_button.toolTip()
    assert window.settings_button.toolTip()


# =================================================================================================
# L7 — EmptyState của khung phải
# =================================================================================================


def test_l7_empty_state_when_nothing_paired_and_no_content(window, tmp_path):
    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    assert window.stream_pane.currentWidget() is window.empty_state
    assert window.empty_state.title_label.text() == EMPTY_TITLE
    # B5: trang DISCOVER luôn có, nên màn rỗng luôn có nút “Tìm máy mới”.
    assert window.empty_state.text_label.text() == EMPTY_TEXT_DISCOVER
    assert not window.empty_state.action_button.isHidden()


def test_l7_paired_device_switches_to_transfers_area(window, tmp_path):
    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    window.devices.reset([dview(paired=True)])
    assert window.stream_pane.currentWidget() is window.transfers_area
    window.devices.clear()
    assert window.stream_pane.currentWidget() is window.empty_state


def test_l7_only_unpaired_devices_keep_empty_state(window, tmp_path):
    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    window.devices.reset([dview("May-1"), dview("May-2")])
    assert window.stream_pane.currentWidget() is window.empty_state


def test_l7_model_signals_recompute_paired_flag(window, tmp_path):
    from teleport.app.node import DeviceOffline, DeviceOnline

    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    model = window.devices
    model.apply(DeviceOnline(dview("May-1")))  # rowsInserted, chưa ghép đôi
    assert window.stream_pane.currentWidget() is window.empty_state
    model.apply(DeviceOnline(dview("May-1", paired=True)))  # cùng máy, nay đã ghép đôi
    assert window.stream_pane.currentWidget() is window.transfers_area
    model.reset([dview("May-3")])  # modelReset: chỉ còn máy chưa ghép đôi
    assert window.stream_pane.currentWidget() is window.empty_state
    model.apply(DeviceOffline(dview("May-3", online=False)))  # rowsRemoved
    assert model.rowCount() == 0
    assert window.stream_pane.currentWidget() is window.empty_state


def test_l7_content_without_paired_device_shows_transfers_area(window, tmp_path):
    running(window, tmp_path)
    window.set_transfer_summary(True, 0)
    assert window.stream_pane.currentWidget() is window.transfers_area
    window.set_transfer_summary(False, 0)
    assert window.stream_pane.currentWidget() is window.empty_state


def test_l7_discover_page_adds_action_button(window, tmp_path):
    from teleport.ui.main_window import Page

    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    state = window.empty_state
    assert not state.action_button.isHidden()
    assert state.action_button.text().replace("&", "") == DISCOVER
    assert state.text_label.text() == EMPTY_TEXT_DISCOVER
    state.action_button.click()
    assert window.current_page is Page.DISCOVER


def test_l7_empty_state_shows_not_paired_illustration(window, tmp_path):
    """Spec G6 tiêu chí 8: khung phải (`streamEmpty`) có minh họa NOT_PAIRED thay vòng icon."""
    from teleport.ui.illustrations import Scene

    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    state = window.empty_state
    assert state.objectName() == "streamEmpty"
    assert visible(state.illustration, window)
    assert state.illustration.scene is Scene.NOT_PAIRED
    assert not visible(state.icon_badge, window)


def test_l3_running_without_devices_with_illustration_does_not_grow_window(window, qtbot, tmp_path):
    """Spec G6 mục 7: RUNNING 0 máy (`streamEmpty` có minh họa) ở 720x460 không vượt `MIN_SIZE`."""
    show_window(window, qtbot, MIN_W, MIN_H)
    running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    settle()
    assert window.stream_pane.currentWidget() is window.empty_state
    assert visible(window.empty_state.illustration, window)
    _assert_fits(window)


def test_l3_empty_chat_with_illustration_does_not_grow_window(window, qtbot, make_ctl, tmp_path):
    """Spec G6 mục 7: luồng chat rỗng (`chatEmpty`, minh họa NO_TRANSFERS) ở 720x460 không vượt `MIN_SIZE`."""
    from teleport.ui.illustrations import Scene
    from teleport.ui.widgets import EmptyState

    ctl = make_ctl(window)
    show_window(window, qtbot, MIN_W, MIN_H)
    running(window, tmp_path)
    window.devices.reset([dview("PC-Nha", paired=True, connected=True)])
    ctl.view.set_device_names({PEER_ID: "PC-Nha"})
    settle()
    selected = device_id("PC-Nha")
    assert ctl.view.device_id() == selected, "tiền đề: máy đã ghép đôi duy nhất tự được chọn"
    from teleport.ui.chat import HistoryState

    # Lịch sử chỉ nhận khi luồng đang LOADING (sau `HISTORY_DEBOUNCE_MS`); không node nên tự nạp rỗng.
    qtbot.waitUntil(lambda: ctl.view.thread_for(selected).history_state is HistoryState.LOADING, timeout=3000)
    ctl.view.load_history(selected, [])
    settle()
    chat_empty = window.findChild(EmptyState, "chatEmpty")
    assert chat_empty is not None and visible(chat_empty, window)
    assert visible(chat_empty.illustration, window)
    assert chat_empty.illustration.scene is Scene.NO_TRANSFERS
    _assert_fits(window)


# =================================================================================================
# L8 — Thẻ “máy này”
# =================================================================================================


def test_l8_name_and_caption(window, tmp_path):
    from teleport.ui.home import MachineCard

    running(window, tmp_path, name="May-A")
    assert isinstance(window.machine_card, MachineCard)
    assert window.name_label.text() == "May-A"
    assert window.name_label.textFormat() == Qt.TextFormat.PlainText
    assert window.name_label.accessibleName() == THIS_MACHINE
    assert window.machine_card.caption_label.text() == THIS_MACHINE


def test_l8_hostile_name_shown_through_display_name(window, tmp_path):
    running(window, tmp_path, name="<b>X</b>\x07")
    assert window.name_label.text() == "<b>X</b>\ufffd"  # 12.12
    assert window.name_label.textFormat() == Qt.TextFormat.PlainText


def test_l8_no_name_hides_name_label(window, tmp_path):
    running(window, tmp_path, name=None)
    assert not visible(window.name_label, window)


def test_l8_badge_follows_transfer_summary(window, tmp_path):
    from teleport.ui.widgets import BadgeTone

    running(window, tmp_path, name="May-A")
    window.set_transfer_summary(False, 0)
    assert (window.badge.text, window.badge.tone) == (READY, BadgeTone.SUCCESS)
    window.set_transfer_summary(True, 2)
    assert (window.badge.text, window.badge.tone) == (BUSY.format(n=2), BadgeTone.BUSY)
    desc = window.name_label.accessibleDescription()
    assert "May-A" in desc and BUSY.format(n=2) in desc
    window.set_transfer_summary(True, 1)
    assert window.badge.text == BUSY.format(n=1)
    window.set_transfer_summary(True, 0)
    assert (window.badge.text, window.badge.tone) == (READY, BadgeTone.SUCCESS)
    desc = window.name_label.accessibleDescription()
    assert "May-A" in desc and READY in desc


def test_l8_description_follows_rename(window, tmp_path):
    running(window, tmp_path, name="May-A")
    running(window, tmp_path, name="May-Moi")
    assert "May-Moi" in window.name_label.accessibleDescription()


def test_l8_negative_active_count_raises(window, tmp_path):
    running(window, tmp_path)
    with pytest.raises(ValueError):
        window.set_transfer_summary(True, -1)


# =================================================================================================
# L9 — Chép địa chỉ
# =================================================================================================


@pytest.mark.parametrize(("port", "expected"), [(50000, "192.0.2.5:50000"), ("default", "192.0.2.5")])
def test_l9_copy_button_copies_shown_address(window, tmp_path, port, expected):
    from teleport.net.connection import DEFAULT_PORT

    running(window, tmp_path)
    window.set_addresses(["192.0.2.5"], DEFAULT_PORT if port == "default" else port)
    assert visible(window.copy_button, window)
    got: list[str] = []
    window.machine_card.address_copied.connect(got.append)
    QGuiApplication.clipboard().setText("")
    window.copy_button.click()
    assert QGuiApplication.clipboard().text() == expected
    assert got == [expected]


def test_l9_copy_button_hidden_without_address_or_outside_running(window, tmp_path):
    running(window, tmp_path)
    assert not visible(window.copy_button, window)
    window.set_addresses(["192.0.2.5"], 50000)
    assert visible(window.copy_button, window)
    window.set_addresses([], 50000)
    assert not visible(window.copy_button, window)
    window.set_addresses(["192.0.2.5"], 50000)
    window.show_error("locked", "")
    assert not visible(window.copy_button, window)
    running(window, tmp_path)
    assert not visible(window.copy_button, window)  # rời RUNNING đã quên địa chỉ


def test_l9_copy_button_name_and_row(window):
    assert window.copy_button.accessibleName() == COPY
    # 12.4: nút chép nằm cùng hàng (QHBoxLayout) với `address_label`, ngay sau nhãn.
    row = layout_holding(window.machine_card.layout(), window.address_label)
    assert isinstance(row, QHBoxLayout), f"address_label phải nằm trong một hàng ngang, thấy {row!r}"
    assert row.indexOf(window.copy_button) > row.indexOf(window.address_label)
    name_column = layout_holding(window.machine_card.layout(), window.name_label)
    assert name_column is not row, "nút chép không làm cột riêng cạnh tên"


# =================================================================================================
# L10 — Chân “Lưu vào”
# =================================================================================================


def test_l10_long_receive_dir_elided_with_full_text_in_tooltip(window, qtbot):
    path = Path("C:/x/" + "d" * 200)
    window.show_running("A", path)
    show_window(window, qtbot, MIN_W, MIN_H)
    label = window.save_bar.save_label
    assert label.text().startswith(SAVE_PREFIX)
    assert "…" in label.text()
    doc = QTextDocument()
    doc.setHtml(label.toolTip())
    assert str(path) in doc.toPlainText()
    assert str(path) in label.accessibleDescription()
    assert label.accessibleName() == RECEIVE_DIR
    assert window.save_bar.receive_dir == path
    assert window.receive_dir == path


def test_l10_markup_in_path_shown_as_text(window, qtbot):
    path = Path("C:/x") / "<i>nghieng&amp;"  # không có “/” trong tên: Windows coi “/” là dấu phân cách
    window.show_running("A", path)
    show_window(window, qtbot, 980, 660)
    label = window.save_bar.save_label
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert label.text() == SAVE_PREFIX + str(path)
    doc = QTextDocument()
    doc.setHtml(label.toolTip())
    assert str(path) in doc.toPlainText()


def test_l10_open_button_emits_path_once(window, tmp_path):
    path = tmp_path / "nhan"
    window.show_running("A", path)
    got: list = []
    window.open_receive_dir_requested.connect(got.append)
    button = window.save_bar.open_button
    assert button.accessibleName() == OPEN_DIR
    button.click()
    assert got == [path]
    assert isinstance(got[0], Path)


def test_l10_no_receive_dir_hides_save_bar(window, tmp_path):
    window.show_running("A", None)
    assert not visible(window.save_bar, window)
    assert window.receive_dir is None
    window.show_running("A", tmp_path)
    assert visible(window.save_bar, window)


def test_l10_widening_window_shows_more_of_path(window, qtbot):
    path = Path("C:/x/" + "d" * 200)
    window.show_running("A", path)
    show_window(window, qtbot, MIN_W, MIN_H)
    label = window.save_bar.save_label
    narrow = label.text()
    resize_to(window, 980, 660)
    wide = label.text()
    assert len(wide) > len(narrow)
    full = SAVE_PREFIX + str(path)
    if QFontMetrics(label.font()).horizontalAdvance(full) <= label.contentsRect().width():
        assert wide == full


def test_l10_short_path_not_elided_when_it_fits(window, qtbot):
    path = Path("C:/T")
    window.show_running("A", path)
    show_window(window, qtbot, 980, 660)
    assert window.save_bar.save_label.text() == SAVE_PREFIX + str(path)


# =================================================================================================
# L11 — GuiApp mở thư mục nhận (node thật)
# =================================================================================================


@pytest.mark.integration
def test_l11_gui_app_opens_receive_dir_via_open_url(
    gui, gui_wait, config_dir, monkeypatch, tmp_path, ui_helpers
):
    from teleport.ui import app as ui_app
    from teleport.ui.main_window import ViewState

    calls: list = []
    reply = {"value": True}

    def fake_open_url(url):
        calls.append(QUrl(url))
        return reply["value"]

    monkeypatch.setattr(ui_app, "open_url", fake_open_url)
    d = config_dir("A")
    receive_dir = tmp_path / "nhan-gui"  # thư mục nhận mà fixture `gui` ép cho node
    seen: dict = {}

    def script(run):
        yield gui_wait(
            lambda: (
                run.windows
                and run.hosts
                and run.hosts[-1].running
                and run.window.view_state is ViewState.RUNNING
            ),
            15,
            "node chạy, cửa sổ RUNNING",
        )
        run.window.save_bar.open_button.click()
        for _ in range(5):
            yield
        seen["first"] = list(calls)
        reply["value"] = False
        run.window.save_bar.open_button.click()  # open_url trả False: chỉ ghi log, không hộp
        for _ in range(5):
            yield
        seen["second"] = list(calls)
        seen["boxes"] = ui_helpers.visible_message_boxes()
        run.tray.quit_requested.emit()

    run = gui(["--config-dir", str(d)], script)
    assert seen["first"] == [QUrl.fromLocalFile(str(receive_dir))]
    assert len(seen["second"]) == 2
    assert seen["boxes"] == []
    assert run.exec_calls == []
    assert run.code == 0


# =================================================================================================
# L12 — Thứ tự Tab ở RUNNING
# =================================================================================================


def tab_cycle(window, start, key=Qt.Key.Key_Tab, steps: int = 120) -> tuple[list, bool]:
    """Bấm `key` từ `start` tới khi quay về `start` (tối đa `steps`).

    Trả (các widget theo thứ tự lần đầu gặp, đã quay vòng hay chưa)."""
    start.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert window.focusWidget() is start
    order = [start]
    for _ in range(steps):
        current = window.focusWidget()
        if key == Qt.Key.Key_Backtab:
            QTest.keyClick(current, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        else:
            QTest.keyClick(current, key)
        QApplication.processEvents()
        focus = window.focusWidget()
        if focus is start:
            return order, True
        if focus is not None and all(focus is not w for w in order):
            order.append(focus)
    return order, False


def index_of(order: list, widget) -> int:
    for i, w in enumerate(order):
        if w is widget:
            return i
    raise AssertionError(f"{widget.objectName() or type(widget).__name__} không có trong chuỗi Tab")


def check_running_order(window, order: list) -> None:
    i_discover = index_of(order, window.discover_button)
    i_ip = index_of(order, window.conversations.add_button)
    i_name = index_of(order, window.name_label)
    i_addr = index_of(order, window.address_label)
    i_copy = index_of(order, window.copy_button)
    i_open = index_of(order, window.save_bar.open_button)
    assert i_discover < i_ip < i_name < i_addr < i_copy < i_open
    in_area = [i for i, w in enumerate(order) if window.transfers_area.isAncestorOf(w)]
    assert in_area, "Tab không vào được widget nào của transfers_area"
    assert all(i_copy < i < i_open for i in in_area), (i_copy, in_area, i_open)
    assert not any(window.start_view.isAncestorOf(w) for w in order), "Tab vào widget của start_view"


def test_l12_tab_order_in_running(window, qtbot, make_ctl, tmp_path):
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    assert visible(window.discover_button, window)
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed, f"Tab không quay vòng về discover_button sau {len(forward)} widget"
    check_running_order(window, forward)


def test_l12_shift_tab_is_reverse_order(window, qtbot, make_ctl, tmp_path):
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    backward, closed = tab_cycle(window, window.discover_button, Qt.Key.Key_Backtab)
    assert closed, "Shift+Tab không quay vòng về discover_button"
    rows = window.conversations.list_view

    # Danh sách giữ Tab giữa các hàng (12.6, B2 2.6): bỏ mục của `list_view` khỏi phép so.
    def key_widgets(seq):
        return [w for w in seq if w is not rows]

    fwd = key_widgets(forward)
    back = key_widgets(backward)
    assert [fwd[0], *reversed(fwd[1:])] == back


def _chat_thread_order(window, ctl, forward: list, current) -> None:
    """Spec B3 mục 7 + 9.10: … `info_bar` → luồng (một điểm dừng: bong bóng hiện hành) → nút của nó →
    `new_button` (khi hiện) → `composer.send_button` → “Mở thư mục” → “Đổi…”."""
    view = ctl.view
    i_action = index_of(forward, view.info_bar.action_button)
    i_bubble = index_of(forward, current)
    i_cancel = index_of(forward, current.cancel_button)
    i_send = index_of(forward, view.composer.send_button)
    i_open = index_of(forward, window.save_bar.open_button)
    i_change = index_of(forward, window.save_bar.change_button)
    assert i_action < i_bubble < i_cancel < i_send < i_open < i_change, [
        w.objectName() or type(w).__name__ for w in forward
    ]
    if view.new_button.isVisibleTo(window):
        assert i_cancel < index_of(forward, view.new_button) < i_send
    else:
        assert all(w is not view.new_button for w in forward)


def test_l12_chat_thread_is_one_tab_stop_before_send_and_open_button(window, qtbot, make_ctl, tmp_path):
    """Spec B3 mục 7, 9.10 (thay “thẻ mới đứng trước Mở thư mục” của danh sách cũ): luồng của máy đang chọn
    là một điểm dừng Tab (bong bóng hiện hành, mặc định mới nhất), Tab đi qua nút của bong bóng đó rồi
    tới `send_button`, “Mở thư mục”, “Đổi…”; bong bóng khác và nút của chúng không nằm trong chuỗi Tab."""
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    selected = device_id("PC-Nha")
    show_window(window, qtbot, 980, 660, active=True)
    assert ctl.view.device_id() == selected, "tiền đề: máy đã ghép đôi duy nhất tự được chọn (mục 6)"
    old_key = tkey("receive", "e" * 32, dev=selected)
    new_key = tkey("send", "f" * 32, dev=selected)
    ctl.view.handle(status_changed(old_key))
    ctl.view.handle(status_changed(new_key))
    settle()
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    check_running_order(window, forward)
    newest, older = ctl.view.row(new_key), ctl.view.row(old_key)
    _chat_thread_order(window, ctl, forward, newest)
    assert all(w is not older and w is not older.cancel_button for w in forward), "luồng chỉ một điểm dừng"
    check_change_last(window, forward)


def test_l12_new_button_sits_between_thread_and_send_button(window, qtbot, make_ctl, tmp_path):
    """Spec B3 9.10: “↓ Mới” (của `ChatView`) nằm sau luồng, trước `send_button`, khi hiện."""
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    selected = device_id("PC-Nha")
    show_window(window, qtbot, 980, 660, active=True)
    for i in range(30):
        ctl.view.handle(status_changed(tkey("send", f"{i:032x}", dev=selected)))
    settle()
    thread = ctl.view.thread_for(selected)
    bar = thread.scroll_area.verticalScrollBar()
    qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=2000)
    bar.setValue(0)
    settle()
    newest_key = tkey("send", "f" * 32, dev=selected)
    ctl.view.handle(status_changed(newest_key))
    settle()
    assert ctl.view.new_button.isVisibleTo(window), "tiền đề: cuộn lên rồi có lượt mới → “↓ Mới” hiện"
    ctl.view.row(newest_key).setFocus(Qt.FocusReason.OtherFocusReason)  # bong bóng hiện hành
    settle()
    current = ctl.view.row(newest_key)
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    _chat_thread_order(window, ctl, forward, current)


@pytest.mark.parametrize("state", ["welcome", "error"])
def test_l12_tab_order_on_start_screens(window, qtbot, state):
    """Spec 2.7: ERROR đi `status_label` → `detail_label` → `hint_label` → nút. WELCOME (spec D1 mục 4):
    ô tên → “Đổi…” → “Bắt đầu”, dòng trạng thái ẩn."""
    if state == "welcome":
        window.show_welcome("Laptop-Minh")
        button = window.start_button
        first = window.first_run.name_edit
        labels: tuple = (first, window.first_run.dir_button)
    else:
        window.show_error("port", "[WinError 10048]")
        button = window.retry_button
        first = window.status_label
        labels = (window.status_label, window.detail_label, window.hint_label)
    show_window(window, qtbot, 980, 660, active=True)
    order, closed = tab_cycle(window, first)
    assert closed
    shown = [w for w in labels if visible(w, window)]
    indexes = [index_of(order, w) for w in (*shown, button)]
    assert indexes == sorted(indexes), [w.objectName() for w in order]
    assert not any(window.shell.isAncestorOf(w) for w in order), "Tab vào widget của khung RUNNING"


# =================================================================================================
# L13 — Tên cho trình đọc màn hình
# =================================================================================================


def unnamed_focusable(window) -> list[str]:
    return [
        f"{type(w).__name__} {w.objectName()!r}"
        for w in window.findChildren(QWidget)
        if w.isVisibleTo(window) and focusable(w) and not w.accessibleName()
    ]


def icon_buttons_without_tooltip(window) -> list[str]:
    from teleport.ui.widgets import IconButton

    return [
        b.objectName() for b in window.findChildren(IconButton) if b.isVisibleTo(window) and not b.toolTip()
    ]


@pytest.mark.parametrize("state", ["running", "welcome", "error"])
def test_l13_every_focusable_widget_has_a_name(window, qtbot, make_ctl, tmp_path, state):
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    if state == "welcome":
        window.show_welcome("Laptop-Minh")
    elif state == "error":
        window.show_error("port", "[WinError 10048]")
    show_window(window, qtbot, 980, 660)
    assert unnamed_focusable(window) == []
    assert icon_buttons_without_tooltip(window) == []


def test_l13_names_of_new_regions(window):
    assert window.sidebar.accessibleName() == DEVICES
    assert window.stream_pane.accessibleName() == TRANSFERS
    assert window.transfers_area.accessibleName() == TRANSFERS
    assert window.brand_label.accessibleName() == "ZCL Teleport"
    assert window.brand_label.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.brand_logo.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.starting_bar.accessibleName() == STARTING_BAR
    assert window.address_label.accessibleName() == ADDRESS_A11Y
    assert window.badge.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.status_icon.accessibleName() == ""


# =================================================================================================
# L14 — Đổi ngôn ngữ
# =================================================================================================


def test_l14_language_change_retranslates_new_texts(window, qtbot, tmp_path):
    window.show_running("May-A", Path("C:/T"))
    window.set_addresses(["192.0.2.5"], None)
    window.set_transfer_summary(False, 0)
    show_window(window, qtbot, 980, 660)
    translator = ShoutTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        qtbot.waitUntil(lambda: window.machine_card.caption_label.text() == shout(THIS_MACHINE), timeout=3000)
        assert window.badge.text == shout(READY)
        assert window.copy_button.accessibleName() == shout(COPY)
        assert window.save_bar.save_label.text().startswith(shout(SAVE_PREFIX))
        assert window.save_bar.open_button.accessibleName() == shout(OPEN_DIR)
        assert window.save_bar.open_button.text().replace("&", "") == shout(OPEN_DIR)
        assert window.empty_state.title_label.text() == shout(EMPTY_TITLE)
        assert window.discover_button.accessibleName() == shout(DISCOVER)
        window.set_transfer_summary(True, 2)
        assert window.badge.text == shout(BUSY).format(n=2)
    finally:
        QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: window.machine_card.caption_label.text() == THIS_MACHINE, timeout=3000)
    assert window.badge.text == BUSY.format(n=2)


# =================================================================================================
# L15 — Nhãn
# =================================================================================================


def test_l15_labels_are_plain_and_not_keyboard_selectable(window, tmp_path):
    running(window, tmp_path)
    window.set_addresses(["192.0.2.5"], None)
    bad = []
    for root in (window.machine_card, window.save_bar, window.sidebar_header, window.start_view):
        for label in root.findChildren(QLabel):
            if label.textFormat() != Qt.TextFormat.PlainText:
                bad.append(f"{label.objectName()}: textFormat {label.textFormat()}")
            if label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByKeyboard:
                bad.append(f"{label.objectName()}: TextSelectableByKeyboard")
    assert bad == []
    for label in (window.name_label, window.address_label):
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse, label.objectName()
        assert label.focusPolicy() == Qt.FocusPolicy.StrongFocus, label.objectName()


# =================================================================================================
# L16 — Vùng cuộn
# =================================================================================================


def assert_conversations_fit_sidebar(window) -> None:
    """Spec 12.22 B1 → B2 mục 12.25: không cuộn ngang được, và danh sách cuộc trò chuyện cần không quá bề
    ngang vùng cuộn trừ lề trái/phải (12 + 12 dạng đầy đủ, 4 + 4 dạng thu gọn, spec B2 mục 2.6)."""
    settle()
    scroll = window.sidebar_scroll
    assert scroll.horizontalScrollBar().maximum() == 0, "cột trái cuộn ngang được: danh sách rộng quá chỗ"
    margins = 8 if window.sidebar_compact else 24
    need = window.conversations.minimumSizeHint().width()
    room = scroll.viewport().width() - margins
    assert need <= room, f"danh sách cần {need} px, chỗ {room}"


def test_l16_conversations_fit_sidebar_at_full_width(window, qtbot, tmp_path):
    running(window, tmp_path)
    window.devices.reset([dview(f"May-{i}", paired=True) for i in range(12)])
    show_window(window, qtbot, 980, MIN_H)
    assert not window.sidebar_compact
    assert_conversations_fit_sidebar(window)


def _scrolled_sidebar(window, qtbot, tmp_path):
    """720x460, 12 máy đã ghép đôi (spec B2 12.25): cột trái cao hơn vùng thấy, cuộn xuống cuối."""
    running(window, tmp_path)
    window.devices.reset([dview(f"May-{i:02d}", paired=True) for i in range(12)])
    show_window(window, qtbot, MIN_W, MIN_H, active=True)
    bar = window.sidebar_scroll.verticalScrollBar()
    assert bar.maximum() > 0, "cột trái phải cuộn được (ca của test)"
    bar.setValue(bar.maximum())
    settle()
    return window.sidebar_scroll.viewport(), window.conversations.list_view, bar


def test_l16_click_on_partly_hidden_row_is_not_lost(window, qtbot, tmp_path):
    """12.22 (B1) dời sang B2: nhấn rồi nhả chuột trên phần đang thấy của một hàng bị che một phần → máy
    của hàng đó thành máy hiện hành, cột trái không tự cuộn (cuộn sẽ dời hàng khỏi con trỏ)."""
    viewport, lv, bar = _scrolled_sidebar(window, qtbot, tmp_path)
    model = lv.model()
    view_rect = viewport.rect()
    target = None
    for r in range(model.rowCount()):
        rect = lv.visualRect(model.index(r, 0)).translated(lv.viewport().mapTo(viewport, QPoint(0, 0)))
        if rect.intersects(view_rect) and not view_rect.contains(rect):
            target = (r, rect.intersected(view_rect))
            break
    assert target is not None, "không có hàng nào bị che một phần"
    row, visible_part = target
    expected = window.conversations.model.devices()[row].device_id
    point = lv.viewport().mapFrom(viewport, visible_part.center())
    before = bar.value()
    QTest.mousePress(lv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    settle()
    QTest.mouseRelease(lv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    settle()
    current = window.conversations.current_device()
    assert current is not None and current.device_id == expected
    assert bar.value() == before, "cú bấm chuột không làm cột trái cuộn"


def test_l16_keyboard_focus_on_hidden_row_still_scrolls(window, qtbot, tmp_path):
    """12.22 (B1) dời sang B2: Shift+Tab từ “＋ Ghép đôi máy mới” đi ngược qua từng hàng; hàng hiện hành
    luôn nằm trong vùng thấy (cột trái tự cuộn lên)."""
    viewport, lv, bar = _scrolled_sidebar(window, qtbot, tmp_path)
    add = window.conversations.add_button
    add.setFocus(Qt.FocusReason.OtherFocusReason)
    qtbot.waitUntil(lambda: window.focusWidget() is add, timeout=1000)
    before = bar.value()
    rows = lv.model().rowCount()
    for _ in range(rows):
        QTest.keyClick(window.focusWidget(), Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        settle()
        assert window.focusWidget() is lv, "Shift+Tab không tới được danh sách"
        rect = lv.visualRect(lv.currentIndex()).translated(lv.viewport().mapTo(viewport, QPoint(0, 0)))
        assert rect.top() >= 0 and rect.bottom() < viewport.height(), (
            f"hàng {lv.currentIndex().row()} {rect} ngoài vùng thấy {viewport.rect()}"
        )
    assert lv.currentIndex().row() == 0
    assert bar.value() < before, "cột trái không tự cuộn lên"


def test_l16_scroll_areas_take_no_focus(window):
    assert window.sidebar_scroll.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert window.start_view.start_scroll.focusPolicy() == Qt.FocusPolicy.NoFocus


# =================================================================================================
# L17 — Đổi sáng/tối
# =================================================================================================


def has_color(pixmap, color: QColor, tolerance: int = 6) -> bool:
    """Pixmap có điểm ảnh (alpha ≥ 128, đã bỏ nhân trước alpha) mang màu `color` (lệch ≤ `tolerance`).

    Icon 20 px là nét viền khử răng cưa: không có điểm ảnh nào alpha 255, và `pixel()` của ảnh nhân
    trước alpha trả màu đã tối đi, nên đổi sang ARGB32 trước (như `test_icons.py`)."""
    from PySide6.QtGui import QImage

    image = pixmap.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    for y in range(image.height()):
        for x in range(image.width()):
            c = QColor.fromRgba(image.pixel(x, y))
            if (
                c.alpha() >= 128
                and max(
                    abs(c.red() - color.red()), abs(c.green() - color.green()), abs(c.blue() - color.blue())
                )
                <= tolerance
            ):
                return True
    return False


def test_l17_status_icon_recolors_on_theme_change(window, ui_theme):
    light = ui_theme(False)
    window.show_error("locked", "")
    settle()
    assert has_color(window.status_icon.pixmap(), light.danger), "icon lỗi không tô `danger` (sáng)"
    dark = ui_theme(True)
    settle()
    assert has_color(window.status_icon.pixmap(), dark.danger), "icon lỗi không tô lại `danger` (tối)"
    assert not has_color(window.status_icon.pixmap(), light.danger), (
        "icon lỗi còn màu `danger` của chế độ sáng"
    )


# =================================================================================================
# L18 — Lối tắt cũ
# =================================================================================================


def test_l18_f5_in_error_emits_retry(window, qtbot):
    window.show_error("locked", "")
    show_window(window, qtbot, 980, 660, active=True)
    got: list = []
    window.retry_requested.connect(lambda: got.append(True))
    QTest.keyClick(window, Qt.Key.Key_F5)
    assert got == [True]


def test_l18_ctrl_w_hides_window_to_tray(window, qtbot, tmp_path, monkeypatch):
    from teleport.ui import tray

    monkeypatch.setattr(tray, "is_available", lambda: True)
    running(window, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    hidden: list = []
    window.hidden_to_tray.connect(lambda: hidden.append(True))
    QTest.keyClick(window, Qt.Key.Key_W, Qt.KeyboardModifier.ControlModifier)
    settle()
    assert not window.isVisible()
    assert hidden == [True]


def test_l18_escape_on_home_does_nothing(window, qtbot, tmp_path):
    from teleport.ui.main_window import Page

    running(window, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    focus = window.focusWidget()
    changes: list = []
    window.page_changed.connect(changes.append)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    settle()
    assert window.current_page is Page.HOME
    assert window.isVisible()
    assert changes == []
    assert window.focusWidget() is focus


# =================================================================================================
# B1b — nút [Đổi…] ở chân “Lưu vào” (spec-b1b mục 2.3, 2.4, 2.9, 6.3; mục 11 thắng khi khác)
# =================================================================================================

CHANGE = "Đổi…"
CHANGE_A11Y = "Đổi thư mục nhận"
CHANGING = "Đang đổi sang {path}…"
NOT_RECEIVING_BAR = "Không nhận file: không mở được {path}"
NOT_RECEIVING = "Không nhận file"


def tooltip_text(widget) -> str:
    doc = QTextDocument()
    doc.setHtml(widget.toolTip())
    return doc.toPlainText()


def unavailable_running(window, tmp_path: Path, name: str | None = "May-A") -> Path:
    """RUNNING mà thư mục đã lưu hỏng: không có thư mục nhận, có `unavailable`."""
    broken = tmp_path / "o-da-rut"
    window.show_running(name, None, broken)
    settle()
    return broken


def test_save_bar_has_change_button_after_open_button(window):
    from teleport.ui.widgets import IconButton

    bar = window.save_bar
    button = bar.change_button
    assert isinstance(button, IconButton)
    assert button.objectName() == "changeReceiveDirButton"
    assert button.icon_name == "folder"
    assert button.text().replace("&", "") == CHANGE
    assert button.accessibleName() == CHANGE_A11Y
    assert CHANGE_A11Y in tooltip_text(button), "tooltip nói rõ nút làm gì (spec 11.10)"
    row = layout_holding(bar.layout(), bar.open_button)
    assert row is not None and row.indexOf(button) > row.indexOf(bar.open_button)
    assert focusable(button), "nút nhận Tab"


def test_change_button_emits_change_requested(window, tmp_path):
    running(window, tmp_path)
    got: list = []
    window.save_bar.change_requested.connect(lambda: got.append(True))
    window.save_bar.change_button.click()
    assert got == [True]


def test_window_forwards_change_receive_dir_requested(window, tmp_path):
    running(window, tmp_path)
    got: list = []
    window.change_receive_dir_requested.connect(lambda: got.append(True))
    window.save_bar.change_button.click()
    assert got == [True]


def test_change_button_full_text_in_accessible_description(window, tmp_path):
    path = tmp_path / "nhan"
    window.show_running("A", path)
    assert str(path) in window.save_bar.change_button.accessibleDescription()


def test_save_bar_unavailable_shows_warning_text_hides_open_keeps_change(window, tmp_path):
    broken = unavailable_running(window, tmp_path)
    bar = window.save_bar
    assert visible(bar, window), "thư mục hỏng vẫn hiện thanh (để còn nút Đổi…)"
    expected = NOT_RECEIVING_BAR.format(path=str(broken))
    assert bar.full_text == expected
    assert bar.save_label.text() == expected
    assert bar.save_label.property("tone") == "warning"
    assert expected in bar.save_label.accessibleDescription()
    assert expected in tooltip_text(bar.save_label)
    assert not visible(bar.open_button, window), "không có thư mục để mở"
    assert visible(bar.change_button, window) and bar.change_button.isEnabled()
    assert bar.unavailable == broken
    assert bar.receive_dir is None
    assert window.receive_dir is None
    assert window.receive_dir_unavailable == broken


def test_save_bar_unavailable_never_uses_danger(window, tmp_path):
    unavailable_running(window, tmp_path)
    tones = {label.property("tone") for label in window.save_bar.findChildren(QLabel)}
    assert "danger" not in tones


def test_save_bar_receive_dir_wins_over_unavailable(window, tmp_path):
    path = tmp_path / "nhan"
    window.show_running("A", path, tmp_path / "hong")
    bar = window.save_bar
    assert bar.full_text == SAVE_PREFIX + str(path)
    assert bar.save_label.property("tone") == "muted"
    assert visible(bar.open_button, window)


def test_save_bar_pending_text(window, tmp_path):
    path = tmp_path / "nhan"
    new = tmp_path / "moi"
    window.show_running("A", path)
    window.set_receive_dir_pending(new)
    bar = window.save_bar
    assert bar.pending == new
    assert bar.full_text == CHANGING.format(path=str(new))
    assert bar.save_label.property("tone") == "muted"
    assert visible(bar.open_button, window), "đang đổi: vẫn còn thư mục cũ để mở"
    window.set_receive_dir_pending(None)
    assert bar.full_text == SAVE_PREFIX + str(path)
    # Đang đổi từ trạng thái hỏng: chữ “đang đổi” thắng chữ warning.
    broken = unavailable_running(window, tmp_path)
    window.set_receive_dir_pending(new)
    assert bar.full_text == CHANGING.format(path=str(new))
    assert bar.save_label.property("tone") == "muted"
    window.set_receive_dir_pending(None)
    assert bar.full_text == NOT_RECEIVING_BAR.format(path=str(broken))


def test_window_set_receive_dir_after_change(window, tmp_path):
    unavailable_running(window, tmp_path)
    new = tmp_path / "moi"
    window.set_receive_dir(new)
    bar = window.save_bar
    assert window.receive_dir == new
    assert window.receive_dir_unavailable is None
    assert bar.full_text == SAVE_PREFIX + str(new)
    assert visible(bar.open_button, window)
    assert window.badge.text == READY


def test_hostile_unavailable_path_is_plain_text(window, tmp_path):
    from teleport.ui.send import printable

    broken = tmp_path / "<b>x</b>‮y"
    window.show_running("A", None, broken)
    label = window.save_bar.save_label
    assert label.textFormat() == Qt.TextFormat.PlainText
    assert "‮" not in label.text()
    assert window.save_bar.full_text == NOT_RECEIVING_BAR.format(path=printable(str(broken)))


def test_change_button_stays_enabled_and_focused_while_changing(window, qtbot, tmp_path):
    running(window, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    button = window.save_bar.change_button
    button.setFocus(Qt.FocusReason.TabFocusReason)
    settle()
    assert window.focusWidget() is button
    window.set_receive_dir_pending(tmp_path / "moi")
    settle()
    assert button.isEnabled()
    assert window.focusWidget() is button, "đổi chữ thanh không được làm mất tiêu điểm"
    window.set_receive_dir_pending(None)
    window.set_receive_dir(tmp_path / "moi")
    settle()
    assert window.focusWidget() is button


def test_fixing_unavailable_keeps_change_focus_and_bar_never_hidden(window, qtbot, tmp_path):
    """Soát B1b: UNAVAILABLE → đang đổi → READY theo thứ tự của `GuiApp` (thư mục trước, rồi
    xóa `pending`) không được ẩn thanh thoáng qua, nên “Đổi…” giữ tiêu điểm bàn phím."""
    unavailable_running(window, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    bar = window.save_bar
    button = bar.change_button
    button.setFocus(Qt.FocusReason.TabFocusReason)
    settle()
    assert window.focusWidget() is button
    hidden: list[bool] = []
    original = bar.setVisible

    def spy(visible: bool) -> None:
        if not visible:
            hidden.append(True)
        original(visible)

    bar.setVisible = spy  # type: ignore[method-assign]
    window.set_receive_dir_pending(tmp_path / "moi")
    window.set_receive_dir(tmp_path / "moi", None)
    window.set_receive_dir_pending(None)
    settle()
    assert hidden == [], "thanh không được ẩn giữa chừng"
    assert window.focusWidget() is button


def test_machine_badge_not_receiving_warning(window, tmp_path):
    from teleport.ui.widgets import BadgeTone

    unavailable_running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    assert (window.badge.text, window.badge.tone) == (NOT_RECEIVING, BadgeTone.WARNING)
    assert window.machine_card.receiving_unavailable is True
    assert NOT_RECEIVING in window.name_label.accessibleDescription(), "trạng thái bằng chữ (N12)"
    window.set_receive_dir(tmp_path / "moi")
    assert (window.badge.text, window.badge.tone) == (READY, BadgeTone.SUCCESS)
    assert window.machine_card.receiving_unavailable is False


def test_badge_priority_active_over_not_receiving(window, tmp_path):
    from teleport.ui.widgets import BadgeTone

    unavailable_running(window, tmp_path)
    window.set_transfer_summary(True, 2)
    assert (window.badge.text, window.badge.tone) == (BUSY.format(n=2), BadgeTone.BUSY)
    window.set_transfer_summary(True, 0)
    assert (window.badge.text, window.badge.tone) == (NOT_RECEIVING, BadgeTone.WARNING)


def test_machine_card_set_receiving_unavailable(qtbot):
    from teleport.ui.home import MachineCard
    from teleport.ui.widgets import BadgeTone

    card = MachineCard()
    qtbot.addWidget(card)
    card.set_receiving_unavailable(True)
    assert card.receiving_unavailable is True
    assert (card.badge.text, card.badge.tone) == (NOT_RECEIVING, BadgeTone.WARNING)
    card.set_activity(1)
    assert card.badge.tone == BadgeTone.BUSY
    card.set_activity(0)
    card.set_receiving_unavailable(False)
    assert (card.badge.text, card.badge.tone) == (READY, BadgeTone.SUCCESS)


def test_leaving_running_clears_unavailable_pending_and_badge(window, tmp_path):
    """Spec-b1b 11.7: ngoài RUNNING thanh ẩn, không còn warning; quay lại RUNNING không mang trạng thái cũ."""
    from teleport.ui.widgets import BadgeTone

    unavailable_running(window, tmp_path)
    window.set_receive_dir_pending(tmp_path / "moi")
    window.show_error("locked", "")
    bar = window.save_bar
    assert not visible(bar, window)
    assert (bar.receive_dir, bar.unavailable, bar.pending) == (None, None, None)
    assert window.machine_card.receiving_unavailable is False
    window.show_starting()
    assert not visible(bar, window)
    path = tmp_path / "nhan"
    window.set_receive_dir_pending(None)  # app xóa `pending` qua `state_changed` khi attach host mới
    window.show_running("A", path)
    assert bar.unavailable is None and bar.pending is None
    assert bar.full_text == SAVE_PREFIX + str(path)
    assert window.badge.tone == BadgeTone.SUCCESS


def check_change_last(window, order: list) -> None:
    i_change = index_of(order, window.save_bar.change_button)
    assert i_change == len(order) - 1, (
        f"“Đổi…” phải cuối chuỗi Tab, thấy sau nó: {[w.objectName() for w in order[i_change + 1 :]]}"
    )
    in_area = [i for i, w in enumerate(order) if window.transfers_area.isAncestorOf(w)]
    assert all(i < i_change for i in in_area)
    if window.save_bar.open_button.isVisibleTo(window):
        assert index_of(order, window.save_bar.open_button) == i_change - 1, "Mở thư mục → Đổi…"


def test_l12_change_button_is_last_in_tab_order(window, qtbot, make_ctl, tmp_path):
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    show_window(window, qtbot, 980, 660, active=True)
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    check_running_order(window, forward)
    check_change_last(window, forward)

    # Thêm bong bóng lượt mới vào luồng đang mở (widget tạo sau cửa sổ): “Đổi…” vẫn cuối. Spec B3 9.10:
    # nút trong bong bóng chỉ tới được qua bong bóng hiện hành, nên so `send_button` thay nút “Hủy”.
    new_key = tkey("send", "f" * 32, dev=device_id("PC-Nha"))
    ctl.view.handle(status_changed(new_key))
    settle()
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    check_running_order(window, forward)
    check_change_last(window, forward)
    assert index_of(forward, ctl.view.composer.send_button) < index_of(forward, window.save_bar.change_button)

    # `open_button` ẩn (thư mục hỏng): “Đổi…” vẫn cuối, sau khung phải.
    window.show_running("May-A", None, tmp_path / "hong")
    ctl.view.handle(status_changed(tkey("send", "e" * 32)))
    settle()
    assert not window.save_bar.open_button.isVisibleTo(window)
    forward, closed = tab_cycle(window, window.discover_button)
    assert closed
    check_change_last(window, forward)
    assert index_of(forward, window.copy_button) < index_of(forward, window.save_bar.change_button)


def test_l13_change_button_named_in_every_running_state(window, qtbot, make_ctl, tmp_path):
    ctl = make_ctl(window)
    fill_l12(window, ctl, tmp_path)
    window.show_running("May-A", None, tmp_path / "hong")
    show_window(window, qtbot, 980, 660)
    assert unnamed_focusable(window) == []
    assert icon_buttons_without_tooltip(window) == []


def test_unavailable_state_language_change_retranslates(window, qtbot, tmp_path):
    from teleport.ui.widgets import BadgeTone

    broken = unavailable_running(window, tmp_path)
    window.set_transfer_summary(False, 0)
    show_window(window, qtbot, 980, 660)
    translator = ShoutTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        qtbot.waitUntil(lambda: window.badge.text == shout(NOT_RECEIVING), timeout=3000)
        assert window.badge.tone == BadgeTone.WARNING
        bar = window.save_bar
        assert bar.full_text == shout(NOT_RECEIVING_BAR).format(path=str(broken))
        assert bar.change_button.accessibleName() == shout(CHANGE_A11Y)
        assert bar.change_button.text().replace("&", "") == shout(CHANGE)
        assert shout(CHANGE_A11Y) in tooltip_text(bar.change_button)
        window.set_receive_dir_pending(tmp_path / "moi")
        assert bar.full_text == shout(CHANGING).format(path=str(tmp_path / "moi"))
    finally:
        QCoreApplication.removeTranslator(translator)
    qtbot.waitUntil(lambda: window.badge.text == NOT_RECEIVING, timeout=3000)
    assert window.save_bar.full_text == CHANGING.format(path=str(tmp_path / "moi"))


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_save_bar_icon_follows_state(window, ui_theme, tmp_path, dark):
    """Spec-b1b 11.12: icon `warning` màu `warning` khi hỏng, `arrow_download` màu `text_muted` khi ổn."""
    t = ui_theme(dark)
    unavailable_running(window, tmp_path)
    settle()
    icon = window.save_bar.icon_label
    assert has_color(icon.pixmap(), t.warning), "thư mục hỏng: icon tô `warning`"
    window.set_receive_dir(tmp_path / "moi")
    settle()
    assert has_color(icon.pixmap(), t.text_muted)
    assert not has_color(icon.pixmap(), t.warning)


def test_save_bar_warning_icon_recolors_on_theme_change(window, ui_theme, tmp_path):
    light = ui_theme(False)
    unavailable_running(window, tmp_path)
    settle()
    assert has_color(window.save_bar.icon_label.pixmap(), light.warning)
    dark = ui_theme(True)
    settle()
    if dark.warning != light.warning:
        assert has_color(window.save_bar.icon_label.pixmap(), dark.warning)
        assert not has_color(window.save_bar.icon_label.pixmap(), light.warning)


def test_save_bar_state_change_sends_accessibility_alert(window, tmp_path, monkeypatch):
    """Spec-b1b 11.11: chữ thanh chuyển giữa ba trạng thái → sự kiện Alert trên SaveBar."""
    from PySide6.QtGui import QAccessible

    alerts: list = []
    real = QAccessible.updateAccessibility

    def spy(event):
        with contextlib.suppress(Exception):
            if event.type() == QAccessible.Event.Alert:
                alerts.append(event.object())
        return real(event)

    monkeypatch.setattr(QAccessible, "updateAccessibility", staticmethod(spy))
    bar = window.save_bar
    window.show_running("A", tmp_path / "nhan")
    alerts.clear()
    window.set_receive_dir_pending(tmp_path / "moi")  # ổn → đang đổi
    assert any(o is bar or bar.isAncestorOf(o) for o in alerts), "đang đổi: phải có Alert"
    alerts.clear()
    window.set_receive_dir_pending(None)
    window.set_receive_dir(None, tmp_path / "hong")  # → hỏng
    assert any(o is bar or bar.isAncestorOf(o) for o in alerts), "hỏng: phải có Alert"
