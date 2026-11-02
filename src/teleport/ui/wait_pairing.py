"""Trang “Chờ ghép đôi” (`Page.WAIT_PAIRING`, mvp F3, F10, mục 7.5) và bộ điều khiển nối nó với node.

**Trang** (`WaitPairingPage`, objectName `waitPairingPage`), từ trên xuống: đầu trang “Chờ ghép đôi”
có “Quay lại” (Esc); thanh thông báo của trang (`info_bar`, ngay dưới đầu trang như các trang D2/B5);
dòng trạng thái “Đang chờ máy khác gửi yêu cầu ghép đôi.” (chỉ khi lần mở mới nhất đã được node xác
nhận, `set_waiting(True)`); khối thông tin: tên máy này (`display_name(printable(tên))`), mã máy (8 ký tự
đầu `device_id`), địa chỉ; câu “đang ẩn” (`hidden_label`, đúng chữ mvp F10, chỉ khi máy đang ẩn); nút
“Đóng” căn phải (= quay lại). Nội dung nằm trong một `QScrollArea`, nên cửa sổ tối thiểu vẫn dùng được.

**Địa chỉ** (`set_addresses(addresses, port)`): mỗi địa chỉ IPv4 một hàng, nhãn chọn được bằng chuột
(không nhận tiêu điểm: nút cạnh nó đã mang địa chỉ trong tên trợ năng) và nút “Chép” (tên trợ năng
“Chép địa chỉ <chuỗi>”). Chuỗi = địa chỉ, thêm `:cổng` khi cổng khác `DEFAULT_PORT` (như dòng địa chỉ
của cửa sổ chính và `teleport listen`). “Chép” theo mẫu `home.MachineCard._copy`: đặt clipboard, tooltip
“Đã chép địa chỉ …” `_COPIED_TOOLTIP_MS`, sự kiện trợ năng Alert (cố gắng tốt nhất). None (chưa có lần
đọc nào) → “Đang lấy địa chỉ…”, không cảnh báo. Đọc xong mà rỗng → InfoBar WARNING (câu mvp mục 8);
lần sau có địa chỉ thì gỡ cảnh báo đó (chỉ khi thanh vẫn đang hiện đúng câu ấy). Cảnh báo chỉ hiện khi
thanh đang trống hay đang là chính nó: không đè câu lỗi mở chế độ chờ hay câu kết quả ghép đôi. Cùng địa
chỉ và cổng thì không dựng lại hàng (timer đọc lại định kỳ không làm mất tiêu điểm đang ở một nút
“Chép”); dựng lại mà tiêu điểm đang ở một nút cũ thì tiêu điểm sang nút “Chép” đầu tiên, không còn
thì nút “Đóng”.

**“Đang mở”** (`is_open`, signal `open_changed(bool)`; định nghĩa: mvp F3): cài đặt bằng
`self.isVisible()`, **tính lại ở mọi `showEvent` và `hideEvent`** (kể cả sự kiện tự phát) và chỉ phát khi
giá trị đổi. Bẫy: thu nhỏ trên Windows gửi Hide tự phát nhưng `isVisible()` vẫn True, nên không được
suy “đóng” từ chính sự kiện Hide; `reset` của `PageStack` (`show_starting` / `show_error`) cũng là đổi
trang. Mở mới (False→True): xóa thanh thông
báo trước (câu của lần mở trước hay câu tới lúc trang đóng là câu cũ), rồi mới hiện câu của lần mở này
(cảnh báo không có địa chỉ nếu vẫn rỗng). Ẩn không tự phát cũng xóa thanh thông báo.

**Bộ điều khiển** (`WaitPairingController`, `GuiApp.wait_pairing`): đăng ký trang ở `MainWindow`
(`add_page`), nối `discover.wait_pairing_requested` → `open_page(WAIT_PAIRING)` và hiện nút đó,
`back_requested` → `go_back`, `open_changed` → `_on_open_changed`. Mọi phương thức chạy trên thread Qt;
`Node` chỉ được chạm trong hàm chạy qua `NodeHost.call` (`_enter_wait`, `_leave_wait`).
- **Số thứ tự lần mở** (`_open_seq`): tăng ở mỗi lần mở, mỗi lần đóng và mỗi host mới. Kết quả mở chỉ
  được áp khi còn đúng host (`host is self._host`), đúng số thứ tự, trang chưa bị hủy
  (`shiboken6.isValid`), app không đang thoát (`quitting()`) và trang vẫn mở: mở → đóng → mở nhanh thì
  kết quả của lần mở cũ không đè lần mới.
- **Mở**: phát `refresh_addresses_requested` (GuiApp đọc lại địa chỉ ngay), rồi `host.call` chạy
  `_enter_wait` trên thread node trong **một khối đồng bộ**: `host.set_wait_pairing_open(node, True)`
  (đặt cờ rồi áp lại luật `accept_pairing`, `ui.bridge`) và đọc `(node.name, node.identity.device_id,
  node.visible)`. Xong → `set_identity`, `set_hidden(not visible)`, `set_waiting(True)`. Lỗi (kể cả
  `host.call` tự ném) → InfoBar ERROR (câu mvp mục 8), **không** hiện “Đang chờ…”, và gửi best-effort
  `_leave_wait` (cờ của host có thể đã True mà đọc sau đó mới lỗi).
- **Đóng**: `set_waiting(False)`; host đang chạy thì `host.call(_leave_wait)` **không có `on_done`**
  (lỗi chỉ ghi log ngay trên thread node). Không có host hay host không chạy → không gọi: node đang dừng
  thì `PairingManager.close()` đã thôi nhận.
- **Host mới** (`attach`): nhớ host, tăng số thứ tự và đưa địa chỉ về “chưa đọc” (`set_addresses(None,
  None)`: “Đang lấy địa chỉ…”, gỡ địa chỉ và cảnh báo của host cũ). Host mới bắt đầu với cờ “đang chờ
  ghép đôi” False (`NodeHost._wait_pairing_open`). Không cần nhánh `on_started`: `GuiApp.start_node` luôn gọi
  `show_starting()` → `pages.reset()` nên trang đã đóng (và lệnh đóng gửi cho host cũ đã bị bỏ vì host
  cũ không chạy) trước khi host mới phát `started`; muốn mở lại thì người dùng bấm nút lần nữa.
- `set_visible(visible)` (nối `SettingsController.visibility_changed`) → câu “đang ẩn”;
  `set_addresses` (GuiApp gọi từ `_on_addresses`); `show_notice(câu)` (nối `PairingController.notice`)
  chỉ hiện ở thanh thông báo của trang khi trang đang mở (ghép xong thì ở lại trang, thanh báo kết quả).

**Khoảng hở chấp nhận được**: giữa `hideEvent` và lúc loop áp False (một vòng `call_soon_threadsafe`),
một yêu cầu ghép đôi lọt vào vẫn hiện hộp mã, đúng mvp F3 (“đóng màn không hủy phiên đã nhận”). Chiều
mở: yêu cầu tới trước khi True được áp bị báo “chưa sẵn sàng”. Các lối hiện cửa sổ rồi chuyển trang ngay
(`GuiApp._on_tray_send`, `_on_tray_discover`, `_on_message_clicked` khi trang này đang là trang hiện tại
lúc cửa sổ ở khay) có thể gửi một cặp bật/tắt liền nhau: trong khoảng đó máy ẩn nhận yêu cầu ghép đôi
một thoáng; trạng thái cuối vẫn đúng (đóng). Đóng cửa sổ khi không có khay đi đường
`quit_requested`; người dùng chọn “Không” ở hộp hỏi Thoát thì cửa sổ vẫn hiện nên chế độ chờ vẫn mở
(đúng).

Chữ của máy này hiện dạng chữ thuần (`PlainText`), tên qua `display_name`; tooltip chỉ qua
`widgets.safe_tooltip`. Câu chữ ở ngữ cảnh `"WaitPairing"`, gọi `QCoreApplication.translate` lúc dùng;
`retranslate()` khi nhận `LanguageChange`.
"""

from __future__ import annotations

import contextlib
import functools
import itertools
import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QAccessible, QAccessibleEvent, QGuiApplication, QHideEvent, QShowEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from teleport.core.display import display_name
from teleport.net.connection import DEFAULT_PORT
from teleport.ui import texts, theme
from teleport.ui.main_window import MainWindow, Page
from teleport.ui.send import printable
from teleport.ui.widgets import InfoBar, InfoLevel, PageHeader, safe_tooltip

if TYPE_CHECKING:
    from teleport.app.node import Node
    from teleport.ui.bridge import NodeHost

log = logging.getLogger(__name__)

_COPIED_TOOLTIP_MS = 2000
_CONTENT_MAX_WIDTH = 560  # px, cột nội dung (dòng chữ dài khó đọc trên cửa sổ rộng)
# Chọn bằng chuột để chép; không `TextSelectableByKeyboard`: Tab tới nhãn sẽ hiện con trỏ chữ nhấp nháy.
_TEXT_FLAGS = Qt.TextInteractionFlag.TextSelectableByMouse


# ---- Câu chữ -----------------------------------------------------------------------------------


def page_title() -> str:
    return QCoreApplication.translate("WaitPairing", "Chờ ghép đôi")


def waiting_text() -> str:
    return QCoreApplication.translate("WaitPairing", "Đang chờ máy khác gửi yêu cầu ghép đôi.")


def hidden_text() -> str:
    """Câu khi máy này đang ẩn (mvp F10, đúng chữ)."""
    return QCoreApplication.translate(
        "WaitPairing", "Máy này đang ẩn nên máy kia không tự thấy. Hãy nhập IP của máy này ở máy kia."
    )


def no_address_text() -> str:
    """Đã đọc địa chỉ mà không có địa chỉ IPv4 nào (mvp mục 8)."""
    return QCoreApplication.translate(
        "WaitPairing",
        "Không tìm thấy địa chỉ mạng nào của máy này. Hãy kiểm tra máy đã nối Wi-Fi hoặc dây mạng.",
    )


def open_failed_text() -> str:
    """Node không mở được chế độ chờ ghép đôi (mvp mục 8)."""
    return QCoreApplication.translate(
        "WaitPairing", "Chưa mở được chế độ chờ ghép đôi. Hãy đóng màn này rồi thử lại."
    )


def _copy_name(address: str) -> str:
    return texts.fill(QCoreApplication.translate("WaitPairing", "Chép địa chỉ {address}"), address=address)


def _copied_text(address: str) -> str:
    return texts.fill(QCoreApplication.translate("WaitPairing", "Đã chép địa chỉ {address}"), address=address)


def address_strings(addresses: Sequence[str], port: int | None) -> tuple[str, ...]:
    """Chuỗi hiện và chép của từng địa chỉ: thêm `:cổng` khi cổng khác `DEFAULT_PORT`."""
    suffix = f":{port}" if port is not None and port != DEFAULT_PORT else ""
    return tuple(f"{address}{suffix}" for address in addresses)


# ---- Trang -------------------------------------------------------------------------------------


def _plain_label(object_name: str, parent: QWidget, *, focusable: bool = True) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    # Cờ trước, chính sách tiêu điểm sau: `setTextInteractionFlags` tự đặt lại chính sách tiêu điểm.
    label.setTextInteractionFlags(_TEXT_FLAGS)
    label.setFocusPolicy(Qt.FocusPolicy.StrongFocus if focusable else Qt.FocusPolicy.NoFocus)
    return label


class WaitPairingPage(QWidget):
    """Trang “Chờ ghép đôi” (xem docstring module)."""

    open_changed = Signal(bool)  # “đang mở” (= isVisible()) vừa đổi
    back_requested = Signal()  # “Quay lại” hay “Đóng”

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("waitPairingPage")
        self._open = False
        self._waiting = False
        self._hidden = False
        self._name = ""
        self._short_id = ""
        self._addresses: tuple[str, ...] | None = None  # chuỗi đang hiện (đã kèm `:cổng`)
        self._address_warning = False  # thanh thông báo đang hiện cảnh báo không có địa chỉ
        self._address_rows: list[QWidget] = []
        self.address_labels: list[QLabel] = []
        self.copy_buttons: list[QPushButton] = []

        self.header = PageHeader(page_title(), self)
        self.header.back_requested.connect(self.back_requested)

        scroll = QScrollArea(self)
        scroll.setObjectName("waitPairingScroll")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content = QWidget()
        content.setObjectName("waitPairingContent")
        content.setAutoFillBackground(False)
        self._content = content

        self.info_bar = InfoBar(content)
        self.info_bar.setObjectName("waitPairingInfo")
        self.status_label = _plain_label("waitPairingStatus", content)
        self.status_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.status_label.font()))
        self.status_label.setVisible(False)

        self.details = QFrame(content)
        self.details.setObjectName("waitPairingDetails")
        self.details.setProperty(theme.SURFACE_PROPERTY, "raised")
        self._name_caption = _plain_label("waitPairingNameCaption", self.details, focusable=False)
        self._id_caption = _plain_label("waitPairingIdCaption", self.details, focusable=False)
        self._address_caption = _plain_label("waitPairingAddressCaption", self.details, focusable=False)
        for caption in (self._name_caption, self._id_caption, self._address_caption):
            caption.setProperty(theme.TONE_PROPERTY, "muted")
        self.name_label = _plain_label("waitPairingName", self.details)
        self.id_label = _plain_label("waitPairingId", self.details)
        self.address_pending_label = _plain_label("waitPairingAddressPending", self.details)
        self.address_pending_label.setProperty(theme.TONE_PROPERTY, "muted")
        self._address_box = QVBoxLayout()
        self._address_box.setContentsMargins(0, 0, 0, 0)
        self._address_box.setSpacing(theme.SPACING[1])
        self._address_box.addWidget(self.address_pending_label)
        grid = QGridLayout(self.details)
        grid.setContentsMargins(theme.SPACING[3], theme.SPACING[2], theme.SPACING[3], theme.SPACING[2])
        grid.setHorizontalSpacing(theme.SPACING[3])
        grid.setVerticalSpacing(theme.SPACING[2])
        top = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        grid.addWidget(self._name_caption, 0, 0, top)
        grid.addWidget(self.name_label, 0, 1)
        grid.addWidget(self._id_caption, 1, 0, top)
        grid.addWidget(self.id_label, 1, 1)
        grid.addWidget(self._address_caption, 2, 0, top)
        grid.addLayout(self._address_box, 2, 1)
        grid.setColumnStretch(1, 1)

        self.hidden_label = _plain_label("waitPairingHidden", content)
        self.hidden_label.setVisible(False)
        self.close_button = QPushButton(content)
        self.close_button.setObjectName("waitPairingClose")
        self.close_button.clicked.connect(self.back_requested)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(theme.SPACING[3])
        column.addWidget(self.info_bar)
        column.addWidget(self.status_label)
        column.addWidget(self.details)
        column.addWidget(self.hidden_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        column.addLayout(buttons)
        column.addStretch(1)
        holder = QWidget(content)
        holder.setMaximumWidth(_CONTENT_MAX_WIDTH)
        holder.setLayout(column)
        margin = theme.SPACING[3]
        body = QHBoxLayout(content)
        body.setContentsMargins(margin, theme.SPACING[3], margin, margin)
        body.addWidget(holder, 1)
        body.addStretch(0)
        scroll.setWidget(content)
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addWidget(scroll, 1)

        self.retranslate()
        self._update_tab_order()

    # ---- API -----------------------------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        """Trang đang mở (= `isVisible()` ở lần show/hide gần nhất; xem docstring module)."""
        return self._open

    @property
    def waiting(self) -> bool:
        """Dòng “Đang chờ…” đang bật (lần mở mới nhất đã được node xác nhận)."""
        return self._waiting

    @property
    def addresses(self) -> tuple[str, ...] | None:
        """Chuỗi địa chỉ đang hiện (đã kèm `:cổng`); None khi chưa có lần đọc nào."""
        return self._addresses

    def set_identity(self, name: str, short_id: str) -> None:
        """Tên máy này (chưa qua `display_name`) và mã máy rút gọn."""
        self._name = name
        self._short_id = short_id
        self.name_label.setText(display_name(printable(name)) if name else "")
        self.id_label.setText(printable(short_id))

    def set_hidden(self, hidden: bool) -> None:
        """Máy này đang ẩn (mvp F10): hiện câu “Máy này đang ẩn…”."""
        self._hidden = bool(hidden)
        self.hidden_label.setVisible(self._hidden)

    def set_waiting(self, waiting: bool) -> None:
        """Bật/tắt dòng “Đang chờ máy khác gửi yêu cầu ghép đôi.”."""
        self._waiting = bool(waiting)
        self.status_label.setVisible(self._waiting)

    def set_addresses(self, addresses: Sequence[str] | None, port: int | None) -> None:
        """Địa chỉ IPv4 của máy này và cổng; None = chưa đọc lần nào (xem docstring module)."""
        shown = None if addresses is None else address_strings(addresses, port)
        if shown == self._addresses:
            return
        self._addresses = shown
        self._rebuild_addresses()
        if shown is not None and not shown:
            if self._address_warning or self.info_bar.isHidden():  # không đè câu khác đang hiện
                self._show_address_warning()
        elif self._address_warning:
            self._address_warning = False
            self.info_bar.clear()

    def show_notice(self, text: texts.Text, level: InfoLevel = InfoLevel.INFO) -> None:
        """Hiện `text` ở thanh thông báo của trang (thay câu đang có).

        `text` là hàm thì câu được dịch lại khi đổi ngôn ngữ (`widgets.InfoBar`)."""
        self._address_warning = False
        self.info_bar.show_message(level, text)
        self._update_tab_order()

    def clear_notice(self) -> None:
        self._address_warning = False
        self.info_bar.clear()

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        title = page_title()
        self.header.set_title(title)
        self.setAccessibleName(title)
        status = waiting_text()
        self.status_label.setText(status)
        self.status_label.setAccessibleName(status)
        name_caption = t("WaitPairing", "Tên")
        id_caption = t("WaitPairing", "Mã máy")
        address_caption = t("WaitPairing", "Địa chỉ")
        self._name_caption.setText(name_caption)
        self._id_caption.setText(id_caption)
        self._address_caption.setText(address_caption)
        self.name_label.setAccessibleName(name_caption)
        self.id_label.setAccessibleName(id_caption)
        self.details.setAccessibleName(t("WaitPairing", "Thông tin của máy này"))
        pending = t("WaitPairing", "Đang lấy địa chỉ…")
        self.address_pending_label.setText(pending)
        self.address_pending_label.setAccessibleName(pending)
        hidden = hidden_text()
        self.hidden_label.setText(hidden)
        self.hidden_label.setAccessibleName(hidden)
        close = t("WaitPairing", "Đóng")
        self.close_button.setText(close)
        self.close_button.setAccessibleName(close)
        self.close_button.setAccessibleDescription(
            t("WaitPairing", "Đóng màn này; máy đang ẩn thì thôi nhận yêu cầu ghép đôi.")
        )
        for label, button in zip(self.address_labels, self.copy_buttons, strict=True):
            self._label_copy_button(button, label.text())

    # ---- Địa chỉ -------------------------------------------------------------------------------

    def _rebuild_addresses(self) -> None:
        had_focus = any(button.hasFocus() for button in self.copy_buttons)
        if had_focus:
            self.close_button.setFocus(Qt.FocusReason.OtherFocusReason)  # trước khi nút cũ bị gỡ
        self.setFocusProxy(self.close_button)  # không trỏ vào nút sắp bị gỡ
        for row in self._address_rows:
            self._address_box.removeWidget(row)
            row.hide()
            row.deleteLater()
        self._address_rows = []
        self.address_labels = []
        self.copy_buttons = []
        shown = self._addresses
        self.address_pending_label.setVisible(shown is None)
        for address in shown or ():
            row = QWidget(self.details)
            row.setObjectName("waitPairingAddressRow")
            label = _plain_label("waitPairingAddress", row, focusable=False)
            label.setWordWrap(False)
            label.setText(address)
            label.setAccessibleName(QCoreApplication.translate("WaitPairing", "Địa chỉ"))
            label.setAccessibleDescription(address)
            button = QPushButton(row)
            button.setObjectName("waitPairingCopy")
            button.setProperty("address", address)
            self._label_copy_button(button, address)
            button.clicked.connect(functools.partial(self._copy, button, address))
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            line.setSpacing(theme.SPACING[2])
            line.addWidget(label)
            line.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            line.addStretch(1)
            self._address_box.addWidget(row)
            row.show()  # không chờ lượt hiện trễ của layout: hàng có ngay khi trang đang hiện
            self._address_rows.append(row)
            self.address_labels.append(label)
            self.copy_buttons.append(button)
        self._align_copy_buttons()
        self._update_tab_order()
        if had_focus and self.copy_buttons:
            self.copy_buttons[0].setFocus(Qt.FocusReason.OtherFocusReason)

    def _align_copy_buttons(self) -> None:
        """Các nút “Chép” thẳng một cột: nhãn địa chỉ rộng bằng nhãn dài nhất (tính lại khi đổi font)."""
        widest = max((label.sizeHint().width() for label in self.address_labels), default=0)
        for label in self.address_labels:
            label.setMinimumWidth(widest)

    @staticmethod
    def _label_copy_button(button: QPushButton, address: str) -> None:
        button.setText(QCoreApplication.translate("WaitPairing", "Chép"))
        button.setAccessibleName(_copy_name(address))
        button.setToolTip(safe_tooltip(_copy_name(address)))

    def _copy(self, button: QPushButton, address: str) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(address)
        QToolTip.showText(
            button.mapToGlobal(QPoint(0, button.height())),
            safe_tooltip(_copied_text(address)),
            button,
            QRect(),
            _COPIED_TOOLTIP_MS,
        )
        # Cố gắng tốt nhất: có HĐH không chuyển Alert tới trình đọc màn hình.
        with contextlib.suppress(Exception):
            QAccessible.updateAccessibility(QAccessibleEvent(button, QAccessible.Event.Alert))

    def _show_address_warning(self) -> None:
        # Hàm: `InfoBar` tự dịch lại câu khi đổi ngôn ngữ.
        self.info_bar.show_message(InfoLevel.WARNING, no_address_text)
        self._address_warning = True
        self._update_tab_order()

    # ---- Bàn phím ------------------------------------------------------------------------------

    def _update_tab_order(self) -> None:
        bar = self.info_bar
        chain: list[QWidget] = [
            self.header.back_button,
            bar.title_label,
            bar.text_label,
            bar.action_button,
            bar.close_button,
            self.status_label,
            self.name_label,
            self.id_label,
            self.address_pending_label,
            *self.copy_buttons,
            self.hidden_label,
            self.close_button,
        ]
        for first, second in itertools.pairwise(chain):
            QWidget.setTabOrder(first, second)
        # Mở trang: tiêu điểm vào nút “Chép” đầu tiên (việc hay làm nhất ở đây), không có thì “Đóng”.
        self.setFocusProxy(self.copy_buttons[0] if self.copy_buttons else self.close_button)

    # ---- Hiện/ẩn -------------------------------------------------------------------------------

    def _update_open(self) -> None:
        """Tính lại “đang mở” (= `isVisible()`); chỉ phát `open_changed` khi đổi."""
        is_open = self.isVisible()
        if is_open == self._open:
            return
        self._open = is_open
        if is_open:
            # Mở mới: câu cũ đi trước, rồi mới tới câu của lần mở này.
            self.clear_notice()
            if self._addresses is not None and not self._addresses:
                self._show_address_warning()
        else:
            self.clear_notice()
        self.open_changed.emit(is_open)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._update_open()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        # Lúc cửa sổ bị hủy, PySide có thể đã xóa thuộc tính Python mà Qt vẫn gửi sự kiện: bỏ qua.
        if "info_bar" not in self.__dict__:
            return
        if not event.spontaneous():  # đổi trang, xuống khay (thu nhỏ thì giữ)
            self.clear_notice()
        self._update_open()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        elif event.type() == QEvent.Type.FontChange:
            self._align_copy_buttons()


# ---- Bộ điều khiển -----------------------------------------------------------------------------


def _enter_wait(host: NodeHost, node: Node) -> tuple[str, str, bool]:
    """**Thread node**, một khối đồng bộ: bật “đang chờ ghép đôi” rồi đọc tên, `device_id`, `visible`."""
    host.set_wait_pairing_open(node, True)
    return (node.name, node.identity.device_id, node.visible)


def _leave_wait(host: NodeHost, node: Node) -> None:
    """**Thread node**: tắt “đang chờ ghép đôi”; lỗi chỉ ghi log (lệnh đóng không có `on_done`)."""
    try:
        host.set_wait_pairing_open(node, False)
    except Exception as e:
        log.warning("không tắt được chế độ chờ ghép đôi: %s", type(e).__name__)


def _call_enter(host: NodeHost, node: Node) -> tuple[str, str, bool]:
    return _enter_wait(host, node)  # đọc `_enter_wait` lúc gọi: test vá được


class WaitPairingController(QObject):
    """Nối trang “Chờ ghép đôi” với cửa sổ chính và node (xem docstring module)."""

    refresh_addresses_requested = Signal()  # vừa mở trang: đọc lại địa chỉ máy này ngay

    def __init__(
        self,
        window: MainWindow,
        parent: QObject | None = None,
        *,
        quitting: Callable[[], bool] = lambda: False,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._quitting = quitting
        self._host: NodeHost | None = None
        self._open_seq = 0
        self.page = WaitPairingPage(window.pages)
        window.add_page(Page.WAIT_PAIRING, self.page)
        window.discover.wait_pairing_requested.connect(self._open)
        window.discover.set_wait_pairing_available(True)
        self.page.back_requested.connect(window.go_back)
        self.page.open_changed.connect(self._on_open_changed)

    @property
    def host(self) -> NodeHost | None:
        return self._host

    def attach(self, host: NodeHost | None) -> None:
        """Host mới (cờ “đang chờ ghép đôi” của nó là False); kết quả của host cũ bị bỏ."""
        self._host = host
        self._open_seq += 1
        self.page.set_addresses(None, None)

    def set_addresses(self, addresses: Sequence[str] | None, port: int | None) -> None:
        self.page.set_addresses(addresses, port)

    def set_visible(self, visible: bool) -> None:
        """Đổi ẩn/hiện trong Cài đặt xong (`SettingsController.visibility_changed`)."""
        self.page.set_hidden(not visible)

    def show_notice(self, text: str) -> None:
        """Câu kết quả ghép đôi (`PairingController.notice`): chỉ hiện khi trang đang mở."""
        if self.page.is_open:
            self.page.show_notice(text, InfoLevel.SUCCESS)

    # ---- Nội bộ --------------------------------------------------------------------------------

    def _open(self) -> None:
        self._window.open_page(Page.WAIT_PAIRING)

    def _on_open_changed(self, is_open: bool) -> None:
        self._open_seq += 1
        seq = self._open_seq
        host = self._host
        self.page.set_waiting(False)
        if not is_open:
            if host is not None and host.running:
                host.call(functools.partial(_leave_wait, host))  # không `on_done` (docstring module)
            return
        self.refresh_addresses_requested.emit()
        if host is None:
            self._on_entered(None, seq, RuntimeError("chưa có node"))
            return
        try:
            host.call(functools.partial(_call_enter, host), functools.partial(self._on_entered, host, seq))
        except Exception as e:
            self._on_entered(host, seq, e)

    def _on_entered(
        self, host: NodeHost | None, seq: int, result: tuple[str, str, bool] | BaseException
    ) -> None:
        """Kết quả của một lần mở; chỉ áp khi vẫn đúng host, đúng lần mở và trang còn mở."""
        if (
            host is not self._host
            or seq != self._open_seq
            or not isValid(self.page)
            or self._quitting()
            or not self.page.is_open
        ):
            return
        if isinstance(result, BaseException):
            log.warning("không mở được chế độ chờ ghép đôi: %s", type(result).__name__)
            self.page.set_waiting(False)
            self.page.show_notice(open_failed_text, InfoLevel.ERROR)
            if host is not None and host.running:
                # Best-effort: cờ của host có thể đã True mà luật chưa áp xong.
                with contextlib.suppress(Exception):
                    host.call(functools.partial(_leave_wait, host))
            return
        name, device_id, visible = result
        self.page.set_identity(name, device_id[:8])
        self.page.set_hidden(not visible)
        self.page.set_waiting(True)
