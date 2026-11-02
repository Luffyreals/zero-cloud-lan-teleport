"""Thành phần riêng của trang HOME trong cửa sổ chính (spec B1): `StartPanel`, `MachineCard`, `SaveBar`.

Chỉ ghép từ `ui/widgets.py` và `ui/theme.py` (cùng `icons`, `texts`, `send`, `tray`, `first_run`,
`core.display`); không import `main_window`. Mỗi lớp **tạo** mọi nhãn và nút của mình; `MainWindow`
gán tên tắt (`status_label`, `address_label`, `copy_button`…), nối signal và giữ trạng thái. Chữ đặt
sẵn đi qua `QCoreApplication.translate("Home", …)` gọi lúc dùng; chỉ `MainWindow.retranslate()` gọi
`retranslate()` của các lớp này (chúng không tự bắt `LanguageChange`).

**Bố cục**
- `StartPanel` (`startView`, màn lần chạy đầu / Đang khởi động / Lỗi): `start_scroll` (không khung, không
  nhận tiêu điểm, thanh cuộn ngang khi cần cho đường dẫn dài không dấu cách) bọc một widget căn giữa
  hai chiều bằng stretch; trong đó `card` (`startCard`, `QFrame[surface="card"]`, rộng tối đa
  `START_PANEL_MAX_WIDTH`, lề trong 32, khoảng cách 12). Từ trên xuống: hàng logo 40 px +
  `title_label`; hàng `status_icon` 20 px + `status_label` (SECTION); `detail_label`; `hint_label`;
  `first_run` (`ui.first_run.FirstRunForm`, form lần chạy đầu: chỉ hiện ở WELCOME, khi đó dòng trạng
  thái, chi tiết, gợi ý ẩn); `starting_bar` (bận, 160x4, căn trái); hàng nút căn phải `retry_button`,
  `start_button` (cả hai là nút chính, mỗi lúc chỉ hiện một). Tab: `status_label` → `detail_label` →
  `hint_label` → form (ô tên → “Đổi…” → công tắc) → `retry_button` → `start_button`. Không có chữ
  đặt sẵn ngoài tên của `starting_bar` (chữ của form do chính form đặt).
- `MachineCard` (`machineCard`, chân cột trái): avatar máy này | cột chữ: “Máy này” (CAPTION, muted),
  `name_label` (SECTION), hàng `address_label` (CAPTION, muted) + `copy_button`, `badge`. Lề
  16/12/12/12.
- `SaveBar` (`saveBar`, chân “Lưu vào” toàn chiều ngang): icon + `save_label` (cắt giữa theo bề
  ngang còn lại) + nút “Mở thư mục” (`open_button`, tooltip kèm phím Mở thư mục nhận của
  `ui.shortcuts`) + nút “Đổi…” (`change_button`,
  `changeReceiveDirButton`, phát `change_requested`; spec B1b). Lề 16/6/12/6. Ba trạng thái chữ, ưu
  tiên từ trên xuống: đang đổi (`set_pending`) “Đang đổi sang {path}…”; có thư mục nhận
  (`set_receive_dir`) “Lưu vào: {path}”; chỉ có thư mục đã lưu không mở được (`set_unavailable`)
  “Không nhận file: không mở được {path}”. Thanh hiện khi có thư mục nhận hay thư mục hỏng; “Mở thư
  mục” chỉ hiện khi có thư mục nhận; “Đổi…” luôn hiện và không bị tắt khi đang đổi (bấm lúc đó
  không làm gì: `ReceiveDirController.choose` trả False).
- `MachineCard` huy hiệu, ưu tiên: “Đang truyền n lượt” (BUSY) > “Không nhận file” (WARNING,
  `set_receiving_unavailable`) > “Đã tạm dừng nhận” (WARNING, `set_receiving_paused`, spec D4 mục 4.3:
  người dùng chọn “Tạm dừng nhận” ở menu khay; mô tả trợ năng `paused_badge_description()`) > “Đang ẩn”
  (MUTED, `set_hidden`, spec D2 mục 1.8; mô tả trợ năng “Máy chưa ghép đôi không thấy máy này. Vẫn nhận
  file từ máy đã ghép đôi.”) > “Sẵn sàng nhận” (SUCCESS). Bảng này khác có chủ ý với dấu của biểu tượng
  khay (`ui.tray`, ở đó “không nhận file” và “tạm dừng” đứng trước “đang truyền”): thẻ nói việc đang
  diễn ra, khay cảnh báo việc người dùng dễ quên.

**Token**: `MachineCard` trong suốt (thấy nền `sidebar` của cột trái), đường kẻ trên 1 px `border`
tự vẽ; avatar nền `accent`, icon `accent_text`, vành `sidebar`. `SaveBar` tự vẽ nền `sidebar` và
đường kẻ trên `border`; icon ↓ `text_muted`, trạng thái hỏng thì icon `warning` màu `warning` và chữ
`QLabel[tone="warning"]` (không dùng `danger`; đổi tone thì `unpolish`/`polish`). Chữ phụ dùng
`QLabel[tone="muted"]` (`text_muted` và `warning` trên `sidebar` đủ tương phản,
`tests/ui/test_tokens.py`). Màu lấy bằng `theme.tokens_for` lúc vẽ; đổi sáng/tối thì vẽ lại và tô lại
icon theo trạng thái. Không thêm luật stylesheet, không `setPalette`.

**Trợ năng (mvp N12)**: mọi nhãn là `Qt.PlainText`, không `TextSelectableByKeyboard`. `name_label` và
`address_label` nhận tiêu điểm bằng Tab (chọn bằng chuột được); `name_label` tên “Máy này”, mô tả là
tên + chữ huy hiệu. Huy hiệu luôn có chữ (“Sẵn sàng nhận”, “Đang truyền n lượt”, “Không nhận
file”, “Đã tạm dừng nhận”). Tooltip dựng từ địa chỉ hay đường dẫn đi qua `widgets.safe_tooltip`. Chép địa chỉ:
clipboard, tooltip “Đã chép địa chỉ …” 2 giây và sự kiện trợ năng Alert (cố gắng tốt nhất). Nút
“Đổi…” có tên và tooltip “Đổi thư mục nhận”, mô tả là chữ đầy đủ của thanh; Tab: “Mở thư mục” →
“Đổi…”. Chữ `save_label` chuyển giữa ba trạng thái thì phát Alert trên `SaveBar` (tên “Thư mục
nhận”, mô tả là chữ đầy đủ).
"""

from __future__ import annotations

import contextlib
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QPainter,
    QPaintEvent,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from teleport.core.display import display_name
from teleport.ui import icons, shortcuts, texts, theme
from teleport.ui.first_run import FirstRunForm
from teleport.ui.send import printable
from teleport.ui.tray import make_icon
from teleport.ui.widgets import (
    AvatarKind,
    BadgeTone,
    DeviceAvatar,
    IconButton,
    Presence,
    StatusBadge,
    safe_tooltip,
)

# Chọn bằng chuột để chép; không `TextSelectableByKeyboard`: Tab tới nhãn sẽ hiện con trỏ chữ nhấp nháy.
_TEXT_FLAGS = Qt.TextInteractionFlag.TextSelectableByMouse
START_PANEL_MAX_WIDTH = 460  # px, khối căn giữa của màn Bắt đầu / Lỗi
_STATUS_ICON = 20  # px
_LOGO_SIZE = 40  # px, logo trong khối căn giữa
_STARTING_BAR = (160, 4)  # px
_COPIED_TOOLTIP_MS = 2000
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)


def _label(object_name: str, *, size_delta: int = 0, bold: bool = False) -> QLabel:
    """Nhãn chữ thuần, xuống dòng, chọn bằng chuột, nhận tiêu điểm bằng Tab (trình đọc màn hình đọc được)."""
    label = QLabel()
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    label.setTextInteractionFlags(_TEXT_FLAGS)
    label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
    if size_delta or bold:
        font = QFont(label.font())
        if size_delta:
            font.setPointSizeF(font.pointSizeF() + size_delta)
        font.setBold(bold)
        label.setFont(font)
    return label


def _static_label(object_name: str, parent: QWidget | None = None) -> QLabel:
    """Nhãn chữ thuần không nhận tiêu điểm, không chọn chữ (chú thích, logo, icon)."""
    label = QLabel(parent)
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label


# ---- StartPanel --------------------------------------------------------------------------------


class StartPanel(QWidget):
    """Khối căn giữa của màn Bắt đầu / Đang khởi động / Lỗi (chỉ bố cục; chữ do `MainWindow` đặt)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("startView")
        self.start_scroll = QScrollArea(self)
        self.start_scroll.setObjectName("startScroll")
        self.start_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.start_scroll.setWidgetResizable(True)
        self.start_scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.start_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        center = QWidget()
        center.setObjectName("startCenter")
        self.card = QFrame(center)
        self.card.setObjectName("startCard")
        self.card.setProperty(theme.SURFACE_PROPERTY, "card")
        self.card.setMaximumWidth(START_PANEL_MAX_WIDTH)
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.logo_label = _static_label("startLogo", self.card)
        self.logo_label.setFixedSize(_LOGO_SIZE, _LOGO_SIZE)
        self.logo_label.setPixmap(make_icon().pixmap(_LOGO_SIZE))
        self.title_label = _label("titleLabel")
        self.title_label.setWordWrap(False)
        self.title_label.setFont(theme.font_for(theme.TextStyle.TITLE, self.title_label.font()))
        self.title_label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.title_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # chỉ là tên app; tiêu đề cửa sổ đã có

        self.status_icon = _static_label("statusIcon", self.card)
        self.status_icon.setFixedSize(_STATUS_ICON, _STATUS_ICON)
        self.status_label = _label("statusLabel")
        self.status_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.status_label.font()))
        self.detail_label = _label("detailLabel")
        self.hint_label = _label("hintLabel")
        self.first_run = FirstRunForm(self.card)
        self.first_run.setVisible(False)

        self.starting_bar = QProgressBar(self.card)
        self.starting_bar.setObjectName("startingBar")
        self.starting_bar.setRange(0, 0)
        self.starting_bar.setTextVisible(False)
        self.starting_bar.setFixedSize(*_STARTING_BAR)
        self.starting_bar.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self.retry_button = QPushButton(self.card)
        self.retry_button.setObjectName("retryButton")
        self.retry_button.setProperty(theme.PRIMARY_PROPERTY, True)  # màn Lỗi: hành động chính
        self.start_button = QPushButton(self.card)
        self.start_button.setObjectName("startButton")
        self.start_button.setDefault(True)
        self.start_button.setProperty(theme.PRIMARY_PROPERTY, True)

        column = QVBoxLayout(self.card)
        column.setContentsMargins(*(theme.SPACING[5],) * 4)
        column.setSpacing(theme.SPACING[2])
        brand = QHBoxLayout()
        brand.setSpacing(theme.SPACING[2])
        brand.addWidget(self.logo_label, 0, Qt.AlignmentFlag.AlignVCenter)
        brand.addWidget(self.title_label, 1, Qt.AlignmentFlag.AlignVCenter)
        column.addLayout(brand)
        status_row = QHBoxLayout()
        status_row.setSpacing(theme.SPACING[1])
        status_row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        status_row.addWidget(self.status_label, 1)
        column.addLayout(status_row)
        column.addWidget(self.detail_label)
        column.addWidget(self.hint_label)
        column.addWidget(self.first_run)
        column.addWidget(self.starting_bar, 0, Qt.AlignmentFlag.AlignLeft)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.retry_button)
        buttons.addWidget(self.start_button)
        column.addLayout(buttons)

        # Căn giữa bằng stretch, không bằng cờ căn lề: có cờ thì Qt đặt khối theo sizeHint và bỏ qua
        # heightForWidth của nhãn xuống dòng (như `widgets.EmptyState`).
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addStretch(1)
        row.addWidget(self.card, 1000)
        row.addStretch(1)
        outer = QVBoxLayout(center)
        outer.setContentsMargins(*(theme.SPACING[4],) * 4)
        outer.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)
        self.start_scroll.setWidget(center)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.start_scroll)

        QWidget.setTabOrder(self.status_label, self.detail_label)
        QWidget.setTabOrder(self.detail_label, self.hint_label)
        QWidget.setTabOrder(self.hint_label, self.first_run.name_edit)
        QWidget.setTabOrder(self.first_run.autostart_switch, self.retry_button)
        QWidget.setTabOrder(self.retry_button, self.start_button)
        self.refresh_icon()
        self.status_icon.setVisible(False)
        self.retranslate()

    def set_error_icon(self, shown: bool) -> None:
        """Hiện/ẩn icon lỗi (màu `danger`, tô lại theo chế độ hiện tại)."""
        self.refresh_icon()
        self.status_icon.setVisible(shown)

    def refresh_icon(self) -> None:
        """Dựng lại pixmap của `status_icon` theo token hiện tại (sau khi đổi sáng/tối)."""
        color = theme.tokens_for(self).danger
        self.status_icon.setPixmap(
            icons.pixmap("error_circle", _STATUS_ICON, color, self.status_icon.devicePixelRatioF())
        )

    def retranslate(self) -> None:
        self.starting_bar.setAccessibleName(QCoreApplication.translate("Home", "Đang khởi động"))
        self.first_run.retranslate()


# ---- MachineCard -------------------------------------------------------------------------------


def paused_badge_description() -> str:
    """Mô tả trợ năng của huy hiệu “Đã tạm dừng nhận” (spec D4 mục 14.6)."""
    return texts.fill(
        QCoreApplication.translate(
            "Home",
            "File mới gửi tới sẽ bị từ chối, clipboard gửi tới sẽ bị bỏ qua; lượt đang nhận vẫn "
            "tiếp tục. Bỏ chọn “{menu}” trong menu khay để nhận lại.",
        ),
        menu=texts.menu_pause(),
    )


def hidden_badge_description() -> str:
    """Mô tả trợ năng của huy hiệu “Đang ẩn”."""
    return QCoreApplication.translate(
        "Home", "Máy chưa ghép đôi không thấy máy này. Vẫn nhận file từ máy đã ghép đôi."
    )


class MachineCard(QFrame):
    """Chân cột trái: máy này (tên, địa chỉ, nút chép, huy hiệu trạng thái)."""

    address_copied = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("machineCard")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._name: str | None = None
        self._active = 0
        self._receiving_unavailable = False
        self._receiving_paused = False
        self._hidden = False
        self._copy_value: str | None = None

        self.avatar = DeviceAvatar(
            self,
            diameter=38,
            kind=AvatarKind.DESKTOP,
            presence=Presence.NONE,
            emphasis=True,
            ring="sidebar",
        )
        self.avatar.setObjectName("machineAvatar")
        self.caption_label = _static_label("machineCaption", self)
        self.caption_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.caption_label.font()))
        self.caption_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.name_label = _label("machineName")
        self.name_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.name_label.font()))
        self.address_label = _label("addressLabel")
        self.address_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.address_label.font()))
        self.address_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.copy_button = IconButton("copy", QCoreApplication.translate("Home", "Chép địa chỉ"), self)
        self.copy_button.setObjectName("copyAddressButton")
        self.copy_button.clicked.connect(self._copy)
        self.copy_button.setVisible(False)
        self.badge = StatusBadge(self)
        self.badge.setObjectName("machineBadge")

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        text_column.addWidget(self.caption_label)
        text_column.addWidget(self.name_label)
        address_row = QHBoxLayout()
        address_row.setContentsMargins(0, 0, 0, 0)
        address_row.setSpacing(theme.SPACING[0])
        address_row.addWidget(self.address_label, 1)
        address_row.addWidget(self.copy_button, 0, Qt.AlignmentFlag.AlignTop)
        text_column.addLayout(address_row)
        text_column.addWidget(self.badge)
        self.text_column = text_column
        self.address_row = address_row

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACING[3], theme.SPACING[2], theme.SPACING[2], theme.SPACING[2])
        layout.setSpacing(theme.SPACING[2])
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(text_column, 1)

        QWidget.setTabOrder(self.name_label, self.address_label)
        QWidget.setTabOrder(self.address_label, self.copy_button)
        self.retranslate()

    @property
    def copy_value(self) -> str | None:
        return self._copy_value

    @property
    def active(self) -> int:
        return self._active

    @property
    def receiving_unavailable(self) -> bool:
        """Node chạy mà không nhận file vì thư mục nhận đã lưu không mở được."""
        return self._receiving_unavailable

    def set_name(self, name: str | None) -> None:
        """Tên máy này (chưa qua `display_name`); None thì ẩn dòng tên."""
        self._name = name
        self._update_name()

    def set_activity(self, active: int) -> None:
        """Số lượt chưa kết thúc: n ≥ 1 → “Đang truyền n lượt”; 0 → “Sẵn sàng nhận” / “Không nhận file”."""
        if active < 0:
            raise ValueError(f"số lượt phải ≥ 0: {active}")
        self._active = active
        self._update_badge()

    def set_receiving_unavailable(self, unavailable: bool) -> None:
        """Không nhận file (thư mục nhận hỏng): huy hiệu “Không nhận file” khi không có lượt nào."""
        self._receiving_unavailable = bool(unavailable)
        self._update_badge()

    @property
    def receiving_paused(self) -> bool:
        """Người dùng đang tạm dừng nhận file (menu khay)."""
        return self._receiving_paused

    def set_receiving_paused(self, paused: bool) -> None:
        """Đang tạm dừng nhận: huy hiệu “Đã tạm dừng nhận” khi không có lượt nào và thư mục nhận ổn."""
        self._receiving_paused = bool(paused)
        self._update_badge()

    @property
    def machine_hidden(self) -> bool:
        """Máy này đang ẩn với máy chưa ghép đôi (cài đặt “Cho máy chưa ghép đôi thấy máy này” tắt)."""
        return self._hidden

    def set_hidden(self, hidden: bool) -> None:
        """Máy này đang ẩn: huy hiệu “Đang ẩn” khi không có lượt nào và vẫn nhận file."""
        self._hidden = bool(hidden)
        self._update_badge()

    def set_copy_value(self, value: str | None) -> None:
        """Chuỗi mà “Chép địa chỉ” chép; None thì ẩn nút."""
        self._copy_value = value or None
        self.copy_button.setVisible(self._copy_value is not None)

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        caption = t("Home", "Máy này")
        self.caption_label.setText(caption)
        self.name_label.setAccessibleName(caption)
        self.copy_button.set_label(t("Home", "Chép địa chỉ"))
        self._update_badge()

    # ---- Bên trong -----------------------------------------------------------------------------

    def _update_name(self) -> None:
        shown = display_name(printable(self._name)) if self._name else ""
        self.name_label.setText(shown)
        self.name_label.setVisible(bool(shown))
        self._update_description()

    def _update_badge(self) -> None:
        t = QCoreApplication.translate
        description = ""
        if self._active > 0:
            self.badge.set_status(BadgeTone.BUSY, t("Home", "Đang truyền %n lượt", None, self._active))
        elif self._receiving_unavailable:
            self.badge.set_status(BadgeTone.WARNING, t("Home", "Không nhận file"))
        elif self._receiving_paused:
            self.badge.set_status(BadgeTone.WARNING, t("Home", "Đã tạm dừng nhận"))
            description = paused_badge_description()
        elif self._hidden:
            self.badge.set_status(BadgeTone.MUTED, t("Home", "Đang ẩn"))
            description = hidden_badge_description()
        else:
            self.badge.set_status(BadgeTone.SUCCESS, t("Home", "Sẵn sàng nhận"))
        self.badge.setAccessibleDescription(description)
        self._update_description()

    def _update_description(self) -> None:
        parts = [part for part in (self.name_label.text(), self.badge.text) if part]
        if self.badge.accessibleDescription():
            parts.append(self.badge.accessibleDescription().rstrip("."))
        self.name_label.setAccessibleDescription(". ".join(parts))

    def _copy(self) -> None:
        value = self._copy_value
        if value is None:
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(value)
        message = texts.fill(QCoreApplication.translate("Home", "Đã chép địa chỉ {address}"), address=value)
        button = self.copy_button
        QToolTip.showText(
            button.mapToGlobal(QPoint(0, button.height())),
            safe_tooltip(message),
            button,
            QRect(),
            _COPIED_TOOLTIP_MS,
        )
        # Cố gắng tốt nhất: có HĐH không chuyển Alert tới trình đọc màn hình.
        with contextlib.suppress(Exception):
            QAccessible.updateAccessibility(QAccessibleEvent(button, QAccessible.Event.Alert))
        self.address_copied.emit(value)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(0, 0, self.width(), 1, theme.tokens_for(self).border)
        finally:
            painter.end()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()


# ---- SaveBar -----------------------------------------------------------------------------------


class _SaveState(StrEnum):
    """Ba trạng thái chữ của `SaveBar` (ưu tiên từ trên xuống)."""

    PENDING = "pending"  # đang đổi sang thư mục khác
    READY = "ready"  # có thư mục nhận
    UNAVAILABLE = "unavailable"  # chỉ có thư mục đã lưu không mở được


class _FooterButton(IconButton):
    """`IconButton` có tên cho trình đọc màn hình và tooltip riêng, khác chữ trên nút (“Đổi…”)."""

    def __init__(self, icon_name: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(icon_name, label, parent, show_text=True)
        self._hint = ""

    def set_hint(self, hint: str) -> None:
        """Tên cho trình đọc màn hình và tooltip (gọi sau `set_label`, vì `set_label` đặt lại tên)."""
        self._hint = hint
        self.setAccessibleName(hint)
        self._update_tooltip()

    def _update_tooltip(self) -> None:
        hint = getattr(self, "_hint", "")  # `IconButton.__init__` gọi trước khi có `_hint`
        if hint:
            self.setToolTip(safe_tooltip(hint))
        else:
            super()._update_tooltip()


class SaveBar(QFrame):
    """Chân “Lưu vào: …” toàn chiều ngang cửa sổ, kèm nút “Mở thư mục” và “Đổi…”."""

    open_requested = Signal(object)  # Path
    change_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("saveBar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._receive_dir: Path | None = None
        self._unavailable: Path | None = None
        self._pending: Path | None = None
        self._state: _SaveState | None = None
        self._full_text = ""

        self.icon_label = _static_label("saveIcon", self)
        self.icon_label.setFixedSize(_STATUS_ICON, _STATUS_ICON)
        self.save_label = _static_label("saveLabel", self)
        self.save_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.save_label.font()))
        self.save_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.save_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.save_label.installEventFilter(self)  # cắt lại chữ mỗi khi nhãn đổi bề ngang
        self.open_button = IconButton(
            "folder_open",
            QCoreApplication.translate("Home", "Mở thư mục"),
            self,
            shortcut=shortcuts.sequence(shortcuts.Shortcut.OPEN_RECEIVE_DIR),
            show_text=True,
        )
        self.open_button.setObjectName("openReceiveDirButton")
        self.open_button.clicked.connect(self._open)
        self.change_button = _FooterButton("folder", QCoreApplication.translate("Home", "Đổi…"), self)
        self.change_button.setObjectName("changeReceiveDirButton")
        self.change_button.clicked.connect(self.change_requested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACING[3], 6, theme.SPACING[2], 6)
        layout.setSpacing(theme.SPACING[1])
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.save_label, 1)
        layout.addWidget(self.open_button)
        layout.addWidget(self.change_button)
        QWidget.setTabOrder(self.open_button, self.change_button)
        self._refresh_icon()
        self.setVisible(False)
        self.retranslate()

    @property
    def receive_dir(self) -> Path | None:
        return self._receive_dir

    @property
    def unavailable(self) -> Path | None:
        """Thư mục nhận đã lưu không mở được (node không nhận file), hay None."""
        return self._unavailable

    @property
    def pending(self) -> Path | None:
        """Thư mục đang đổi sang, hay None."""
        return self._pending

    @property
    def full_text(self) -> str:
        """Chữ đầy đủ của nhãn (trước khi cắt giữa)."""
        return self._full_text

    def set_receive_dir(self, path: Path | None) -> None:
        """Thư mục nhận đang dùng; cả nó và `unavailable` là None thì ẩn cả thanh."""
        self._receive_dir = path
        self._update_text()

    def set_unavailable(self, path: Path | None) -> None:
        """Thư mục nhận đã lưu không mở được: không có thư mục nhận thì thanh báo “Không nhận file”."""
        self._unavailable = path
        self._update_text()

    def set_pending(self, path: Path | None) -> None:
        """Thư mục đang đổi sang (“Đang đổi sang …”); None khi không đổi."""
        self._pending = path
        self._update_text()

    def set_state(self, receive_dir: Path | None, unavailable: Path | None, pending: Path | None) -> None:
        """Đặt cả ba giá trị rồi cập nhật một lần: thanh không bị ẩn thoáng qua giữa hai trạng thái
        (ẩn rồi hiện lại làm “Đổi…” mất tiêu điểm bàn phím)."""
        self._receive_dir, self._unavailable, self._pending = receive_dir, unavailable, pending
        self._update_text()

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        name = t("Home", "Thư mục nhận")
        self.setAccessibleName(name)
        self.save_label.setAccessibleName(name)
        self.open_button.set_label(t("Home", "Mở thư mục"))
        self.change_button.set_label(t("Home", "Đổi…"))
        self.change_button.set_hint(t("Home", "Đổi thư mục nhận"))
        self._update_text()

    # ---- Bên trong -----------------------------------------------------------------------------

    def _current_state(self) -> _SaveState | None:
        if self._pending is not None and (self._receive_dir is not None or self._unavailable is not None):
            return _SaveState.PENDING
        if self._receive_dir is not None:
            return _SaveState.READY
        if self._unavailable is not None:
            return _SaveState.UNAVAILABLE
        return None

    def _update_text(self) -> None:
        t = QCoreApplication.translate
        state = self._current_state()
        if state is _SaveState.PENDING:
            full = texts.fill(t("Home", "Đang đổi sang {path}…"), path=_shown(self._pending))
        elif state is _SaveState.READY:
            full = texts.fill(t("Home", "Lưu vào: {path}"), path=_shown(self._receive_dir))
        elif state is _SaveState.UNAVAILABLE:
            full = texts.fill(
                t("Home", "Không nhận file: không mở được {path}"), path=_shown(self._unavailable)
            )
        else:
            full = ""
        self._full_text = full
        self.save_label.setToolTip(safe_tooltip(full) if full else "")
        self.save_label.setAccessibleDescription(full)
        self.setAccessibleDescription(full)
        self.open_button.setAccessibleDescription(full)
        self.change_button.setAccessibleDescription(full)
        self.open_button.setVisible(self._receive_dir is not None)
        self._set_state(state)
        self._elide()
        self._sync_visible()

    def _set_state(self, state: _SaveState | None) -> None:
        """Đổi tone và icon theo trạng thái; chuyển giữa ba trạng thái thì báo trình đọc màn hình."""
        tone = "warning" if state is _SaveState.UNAVAILABLE else "muted"
        if self.save_label.property(theme.TONE_PROPERTY) != tone:
            self.save_label.setProperty(theme.TONE_PROPERTY, tone)
            style = self.save_label.style()
            style.unpolish(self.save_label)
            style.polish(self.save_label)
        previous, self._state = self._state, state
        if previous is state:
            return
        self._refresh_icon()
        if previous is not None and state is not None:
            # Cố gắng tốt nhất: có HĐH không chuyển Alert tới trình đọc màn hình.
            with contextlib.suppress(Exception):
                QAccessible.updateAccessibility(QAccessibleEvent(self, QAccessible.Event.Alert))

    def _sync_visible(self) -> None:
        self.setVisible(self._receive_dir is not None or self._unavailable is not None)

    def _elide(self) -> None:
        width = self.save_label.contentsRect().width()
        text = self._full_text
        # Thanh chưa hiện thì bề ngang nhãn chưa đúng: để nguyên chữ, `showEvent`/`resizeEvent` cắt lại.
        if text and width > 0 and self.isVisible():
            text = QFontMetrics(self.save_label.font()).elidedText(text, Qt.TextElideMode.ElideMiddle, width)
        if self.save_label.text() != text:
            self.save_label.setText(text)

    def _open(self) -> None:
        if self._receive_dir is not None:
            self.open_requested.emit(self._receive_dir)

    def _refresh_icon(self) -> None:
        t = theme.tokens_for(self)
        if self._state is _SaveState.UNAVAILABLE:
            name, color = "warning", t.warning
        else:
            name, color = "arrow_download", t.text_muted
        self.icon_label.setPixmap(
            icons.pixmap(name, _STATUS_ICON, color, self.icon_label.devicePixelRatioF())
        )

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self.save_label and event.type() == QEvent.Type.Resize:
            self._elide()
        return super().eventFilter(watched, event)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_for(self)
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), t.sidebar)
            painter.fillRect(0, 0, self.width(), 1, t.border)
        finally:
            painter.end()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self._refresh_icon()
            self.update()


def _shown(path: Path | None) -> str:
    """Đường dẫn để chèn vào câu: ký tự điều khiển/vô hình thành U+FFFD (`send.printable`)."""
    return "" if path is None else printable(str(path))
