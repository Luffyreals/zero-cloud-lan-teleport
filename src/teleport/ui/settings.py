"""Trang “Cài đặt” (`Page.SETTINGS`, mvp F10, mục 7.4, N9, N12; spec D2).

Hai phần, theo mẫu `ui.discover`:

- **`SettingsPage`** (view, objectName `settingsPage`): không bao giờ gọi node; người dùng đổi gì thì
  phát signal, còn `set_*` đặt giá trị mà **không** phát signal. Bố cục: `PageHeader("Cài đặt")`; cột
  trái `nav` (`QListWidget` `settingsNav`, rộng `NAV_WIDTH`, icon cỡ 20 + chữ) chọn mục; bên phải một
  `info_bar` cho cả trang rồi `sections` (`QStackedWidget`, mỗi `Section` một `QScrollArea` không viền,
  lề `SECTION_MARGIN`, khoảng hàng `ROW_SPACING`). Mỗi hàng là một `SettingsRow`.
- **`SettingsController`** (`GuiApp.settings`): nối signal của trang với node qua `NodeHost.call`
  (thread node), registry tự khởi động (`app.autostart`, thread Qt), hộp xác nhận và hộp lưu file
  (mở bằng `open()`, không `exec()`), việc xuất log (thread riêng).

**Các mục** (`Section`, thứ tự cố định): Chung (tên thiết bị, thư mục nhận, khởi động cùng Windows) ·
Giao diện (`ui.appearance.AppearanceSection`, spec D6: chế độ màu, màu nhấn, ngôn ngữ) · Quyền
riêng tư (cho máy chưa ghép đôi thấy máy này, xóa toàn bộ lịch sử) · Thiết bị tin cậy (mỗi máy đã
ghép đôi một `TrustedDeviceRow`: “Hỏi trước khi nhận”, “Đồng bộ clipboard” (objectName
`syncClipboard`, mặc định tắt; clip chỉ đi khi cả hai máy cùng bật, mvp F8), “Hủy ghép
đôi…”; không máy nào thì `EmptyState` + “Tìm máy mới”) · Truyền file (giới hạn tốc độ gửi, ngưỡng
dọn phần nhận dở) · Nâng cao (xuất log, bảng “Phím tắt” chỉ để xem, phiên bản, giấy phép, “Thông báo
bên thứ ba” khi có file `THIRD-PARTY-NOTICES.txt` cạnh `sys.executable`). Chưa có “Kiểm tra cập
nhật” (GĐ6). Hàng thư mục nhận: chữ theo ba trạng thái của `ui.receive_dir` (đang đổi sang / thư mục
nhận / thư mục đã lưu hỏng), “Mở” (chỉ khi có thư mục nhận) và “Đổi…” (ẩn tới
`set_change_available(True)`; `ui.app` bật và nối vào `ReceiveDirController.choose`).

**Hàng** (`widgets.SettingsRow`, `QFrame[surface="raised"]`, bo `RADIUS_CARD`): nhãn đậm vừa, gợi ý
màu dịu xuống dòng, control bên phải; hàng hẹp tới mức cột chữ còn dưới `widgets.LABEL_MIN_WIDTH` thì control
xuống hàng dưới (cửa sổ `MIN_SIZE` không cuộn ngang). Control mang tên trợ năng = nhãn hàng và mô tả =
gợi ý.

**Số** (spec D2 mục 9.1, không viết cứng): ngưỡng dọn tạm mặc định = `storage.TEMP_RETENTION / 86400`
(đọc lúc dùng), khoảng `settings.MIN_RETENTION_DAYS`–`MAX_RETENTION_DAYS`; tốc độ hiện theo MB/s
(MB = `MB` = 1 048 576 byte, một số lẻ, 0,1–100 000; dấu thập phân theo ngôn ngữ giao diện), gửi
`round(MB/s × MB)` kẹp trong `app.transfers.MIN_RATE_LIMIT`–`settings.MAX_RATE_LIMIT`. Giá trị bằng
mặc định → gửi None. Hậu tố của ô ngày theo số (English “1 day” / “2 days”). Hai ô số chỉ phát khi
**chốt** (spec D2 mục 9.4): Enter hay rời ô (`editingFinished`), hoặc `SPIN_COMMIT_MS`
không đổi sau khi bấm mũi tên; không phát khi bằng giá trị đã biết.

**Ô tên** (`_NameField`): Enter / rời ô thì kiểm (`core.messages.validate_device_name` sau `strip`);
sai thì hiện lỗi ngay dưới ô (`name_error`, màu `danger` kèm chữ), giữ chữ, không phát; đúng và khác tên
đã lưu thì phát `name_submitted`. Esc khi chữ khác tên đã lưu: ô nhận `ShortcutOverride` rồi trả tên
cũ; trùng tên đã lưu thì Esc tới cửa sổ (Quay lại).

**Danh sách thiết bị**: đọc `radar.DeviceListModel` dùng chung (`MainWindow.devices`), theo signal
của model như `DiscoverPage._sync`; chỉ máy `paired`, sắp NFC(tên).casefold() rồi `device_id`; máy
ngoại tuyến vẫn hiện; hàng dùng lại theo `device_id`. Hàng đang có tiêu điểm bị bỏ → tiêu điểm sang
hàng kế, không có thì hàng trước, không còn thì nút của màn rỗng. Tên qua `texts.peer_label`,
chữ thuần, tooltip qua `widgets.safe_tooltip`; tên trợ năng của hàng “{tên}, {HĐH}, {trạng thái}”.

**Bàn phím** (mvp N12): Tab: Quay lại → `nav` → thanh thông báo (khi hiện) → control của mục đang mở
(mục Giao diện: trong mỗi nhóm chỉ phần tử đang chọn nhận Tab, mũi tên đi giữa các phần tử) → hàng
thiết bị → nút màn rỗng; mục Nâng cao: “Xuất log…” → bảng Phím tắt → “Thông báo bên thứ ba”. Lên/Xuống
trong `nav` đổi mục; trang hiện thì tiêu điểm vào `nav` (`setFocusProxy`). Không hoạt ảnh.
`show_section(section, device_id, focus=…)`: mục Thiết bị tin cậy với `device_id` → tiêu điểm vào ô
“Hỏi trước khi nhận” của máy đó, hay ô “Đồng bộ clipboard” khi `focus="clipboard"` và trang đã có ảnh
chụp cài đặt (gợi ý khi dán không phải file ở luồng chat, qua `ui.app`).

**Bảng Phím tắt** (`shortcuts_table`, `_ShortcutTable`, `QTableWidget` objectName `shortcutsTable`,
nằm dưới gợi ý của hàng `shortcutsRow`): hai cột “Thao tác” | “Phím” từ `ui.shortcuts.table_rows()`
(không chép danh sách phím ra đây), không sửa được, chọn một hàng, không tô xen kẽ, không tiêu đề
dọc, không thanh cuộn: cột 0 giãn và xuống dòng (không cắt chữ), cột 1 vừa nội dung, cao vừa đúng số
hàng (tính lại khi đổi bề ngang, font, kiểu, ngôn ngữ). Bánh xe chuột trên bảng cuộn mục chứa nó.
Tab không đi giữa các ô (`tabKeyNavigation` tắt): một điểm dừng Tab, mũi tên đổi hàng. Trợ năng: tên
“Phím tắt”, mô tả là gợi ý của hàng; ô cột 0 đọc “{mô tả}: {phím}”, ô cột 1 đọc phím. Đổi ngôn ngữ thì
dựng lại chữ, giữ hàng đang chọn.

**Controller** (bảng ở spec D2 mục 1.6, 9): lưu trước, áp sau; lỗi thì trả control về giá trị đã xác
nhận gần nhất của trường đó, nhưng chỉ khi đó là lời gọi mới nhất của trường (`_seq`); kết quả của host
cũ hay về sau `close_all` bị bỏ (`_generation`). `SettingsSaveError` → câu SETTINGS; `MessageError` của
tên → lỗi ngay dưới ô (không trả chữ về); `KeyError` của “Hỏi trước khi nhận” và “Đồng bộ clipboard”
(`node.set_clipboard`) → im lặng, đọc lại;
`RuntimeError` (node không chạy) / `CancelledError` → im lặng (DEBUG); lỗi khác → câu OTHER, log ERROR chỉ
tên loại lỗi (mvp N9). Ẩn/hiện: `node.set_visible(v)` và `host.apply_pairing_policy(node)` trong **cùng
một** `call` (hợp đồng ở docstring `ui.bridge`). Ngôn ngữ: lưu xong mới `i18n.apply_preference`; chế độ
màu và màu nhấn: lưu xong (`set_ui_preferences(theme=…)` / `(accent=…)` trên thread node) mới
`theme.set_preference` trên thread Qt. Mỗi ảnh chụp cài đặt khác lựa chọn đang áp thì cũng áp theo ảnh
chụp.

**Tự khởi động** (registry thắng, spec D2 mục 1.2): lúc `started` và mỗi lần trang hiện, đọc
`autostart.state` trên thread Qt; khác `settings.autostart` thì chỉ ghi `set_ui_preferences(autostart=…)`
(không bao giờ tự ghi registry). Bấm công tắc: ghi registry trước (lỗi → trả công tắc, báo, không lưu),
rồi lưu cài đặt (lỗi chỉ WARNING), rồi đọc lại trạng thái.

**Xuất log**: hộp lưu (`dialog_factory`, seam cấp module đọc lúc gọi) mặc định
`teleport-log-YYYYMMDD-HHMMSS.zip` trong thư mục Tài liệu; chọn xong thì `export_fn` (seam, mặc định
`app.logexport.export_logs`) chạy trong `ThreadPoolExecutor(1, "teleport-logexport")`, ngoài thread Qt
và loop node; kết quả về qua signal `QueuedConnection` của một `QObject` sống cùng controller. Worker chỉ
giữ `Path`/`str`. Rủi ro chấp nhận: xuất đúng lúc file log xoay vòng có thể thiếu vài dòng.

**Xóa toàn bộ lịch sử**: hộp xác nhận (mặc định và Esc là “Không”) → `node.transfers.clear_history()`;
báo “Đã xóa…” khi lời gọi trả về (việc ghi `history.json` lỗi chỉ WARNING ở `app`), phát
`history_cleared(None)`.

Câu chữ ở ngữ cảnh `"Settings"`, gọi `QCoreApplication.translate` lúc dùng; `retranslate()` khi nhận
`LanguageChange` (giữ lựa chọn đang có).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import functools
import itertools
import logging
import sys
import time
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QLocale,
    QObject,
    QRect,
    QSize,
    QStandardPaths,
    Qt,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QDesktopServices,
    QFontMetrics,
    QHideEvent,
    QKeyEvent,
    QResizeEvent,
    QShowEvent,
    QValidator,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QBoxLayout,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

import teleport
from teleport.app import autostart, logexport, storage
from teleport.app import settings as app_settings
from teleport.app import transfers as app_transfers
from teleport.app.devices import DeviceView
from teleport.app.node import Node
from teleport.app.settings import DeviceSettings, SettingsSaveError
from teleport.core.messages import PROTOCOL_VERSION, MessageError, validate_device_name
from teleport.ui import i18n, icons, shortcuts, texts, theme
from teleport.ui.appearance import AppearanceSection
from teleport.ui.appearance import section_title as appearance_title
from teleport.ui.radar import DeviceListModel
from teleport.ui.send import printable
from teleport.ui.widgets import (
    DeviceAvatar,
    EmptyState,
    InfoBar,
    InfoLevel,
    PageHeader,
    Presence,
    SettingsRow,
    ToggleSwitch,
    safe_tooltip,
)

log = logging.getLogger(__name__)

NAV_WIDTH = 184  # px, cột chọn mục
SECTION_MARGIN = theme.SPACING[4]  # 24 px, lề nội dung của mỗi mục
ROW_SPACING = theme.SPACING[1]  # 8 px, khoảng giữa hai hàng
DEVICE_ROW_WIDE = 560  # px: hàng thiết bị hẹp hơn thì ô và nút xuống hàng dưới
SPIN_COMMIT_MS = 600  # ms không đổi sau khi bấm mũi tên thì chốt giá trị ô số
MB = 1024 * 1024  # byte của “MB” trong ô tốc độ
RATE_MIN_MB = 0.1
RATE_MAX_MB = 100_000.0
RATE_DEFAULT_MB = 10.0  # số hiện sẵn khi chưa giới hạn
NAME_MAX_INPUT = 256  # ký tự tối đa gõ được vào ô tên (luật thật: `validate_device_name`)
NOTICES_FILE = "THIRD-PARTY-NOTICES.txt"
EXPORT_THREAD = "teleport-logexport"
_NAV_ICON = 20  # px (`shield_checkmark` có cỡ 20)
_NAV_ROW_HEIGHT = 36  # px
_AVATAR = 32  # px
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
_FIT_PASSES = 4  # số lượt tối đa tính lại chiều cao bảng Phím tắt tới khi đứng yên
_TABLE_ROW_PADDING = 6  # px, trên và dưới chữ mỗi hàng của bảng Phím tắt
_TABLE_CELL_PADDING = 8  # px, hai bên chữ mỗi ô của bảng Phím tắt

# Seam (đọc lúc gọi): hộp chọn file lưu log và hàm xuất log.
dialog_factory: Callable[[QWidget | None], QFileDialog] = QFileDialog
export_fn: Callable[[Sequence[Path], Path], Path] = logexport.export_logs


class Section(StrEnum):
    """Các mục của trang, đúng thứ tự trong `nav`."""

    GENERAL = "general"
    APPEARANCE = "appearance"
    PRIVACY = "privacy"
    DEVICES = "devices"
    TRANSFER = "transfer"
    ADVANCED = "advanced"


SECTION_ICONS = {
    Section.GENERAL: "settings",
    Section.APPEARANCE: "color",
    Section.PRIVACY: "eye_off",
    Section.DEVICES: "shield_checkmark",
    Section.TRANSFER: "arrow_swap",
    Section.ADVANCED: "wrench",
}


# ---- Câu chữ -----------------------------------------------------------------------------------


def page_title() -> str:
    return QCoreApplication.translate("Settings", "Cài đặt")


def section_title(section: Section) -> str:
    t = QCoreApplication.translate
    return {
        Section.GENERAL: t("Settings", "Chung"),
        Section.APPEARANCE: appearance_title(),
        Section.PRIVACY: t("Settings", "Quyền riêng tư"),
        Section.DEVICES: t("Settings", "Thiết bị tin cậy"),
        Section.TRANSFER: t("Settings", "Truyền file"),
        Section.ADVANCED: t("Settings", "Nâng cao"),
    }[Section(section)]


def name_hint(visible: bool) -> str:
    """Gợi ý dưới ô tên: máy đang hiện → nguyên câu mvp F1; đang ẩn → chỉ máy đã ghép đôi thấy."""
    if visible:
        return texts.device_name_notice()
    return QCoreApplication.translate("Settings", "Máy này đang ẩn nên chỉ máy đã ghép đôi thấy tên này.")


def name_empty_text() -> str:
    return QCoreApplication.translate("Settings", "Hãy nhập tên thiết bị.")


def name_invalid_text() -> str:
    return QCoreApplication.translate(
        "Settings", "Tên thiết bị cần từ 1 đến 64 ký tự và không có ký tự điều khiển."
    )


def autostart_state_hint(state: autostart.AutostartState | None) -> str:
    """Câu thêm của hàng khởi động theo trạng thái registry; None = đọc lỗi."""
    t = QCoreApplication.translate
    if state is None:
        return t("Settings", "Không đọc được cài đặt khởi động của Windows.")
    if state is autostart.AutostartState.BLOCKED:
        return t(
            "Settings",
            "Windows đang tắt Teleport trong danh sách ứng dụng khởi động. Bật công tắc này để cho phép lại.",
        )
    if state is autostart.AutostartState.OTHER:
        return t(
            "Settings",
            "Teleport đang được đặt khởi động cùng Windows từ một thư mục cài hoặc thư mục cấu hình "
            "khác. Bật công tắc để dùng bản này.",
        )
    return ""


def autostart_write_error_text() -> str:
    return QCoreApplication.translate(
        "Settings",
        "Chưa đổi được việc khởi động cùng Windows vì Windows không cho ghi cài đặt khởi động. Hãy thử lại.",
    )


def hidden_text() -> str:
    return QCoreApplication.translate(
        "Settings",
        "Đang ẩn: máy chưa ghép đôi không thấy máy này và không gửi được yêu cầu ghép đôi tới. "
        "Muốn ghép đôi với máy mới, hãy mở Tìm máy mới trên máy này rồi bấm vào máy kia.",
    )


def settings_error_text() -> str:
    """Lưu cài đặt lỗi (`SettingsSaveError`)."""
    return QCoreApplication.translate(
        "Settings",
        "Chưa lưu được cài đặt vì không ghi được vào thư mục cấu hình của Teleport. "
        "Hãy kiểm tra quyền ghi rồi thử lại.",
    )


def other_error_text() -> str:
    return QCoreApplication.translate(
        "Settings", "Chưa lưu được cài đặt vì một lỗi không mong đợi. Hãy thử lại."
    )


def snapshot_error_text() -> str:
    return QCoreApplication.translate("Settings", "Không đọc được cài đặt hiện tại.")


def history_cleared_text() -> str:
    return QCoreApplication.translate("Settings", "Đã xóa toàn bộ lịch sử truyền file.")


def history_clear_failed_text() -> str:
    return QCoreApplication.translate("Settings", "Chưa xóa được lịch sử truyền file. Hãy thử lại.")


def clear_history_title() -> str:
    return QCoreApplication.translate("Settings", "Xóa toàn bộ lịch sử")


def clear_history_question() -> str:
    return QCoreApplication.translate(
        "Settings",
        "Xóa lịch sử truyền file với mọi máy, kể cả máy đã hủy ghép đôi? "
        "File đã nhận vẫn còn nguyên trong thư mục nhận.",
    )


def export_saved_text(path: Path) -> str:
    return texts.fill(
        QCoreApplication.translate("Settings", "Đã lưu log vào {path}."), path=printable(str(path))
    )


def export_write_error_text(path: Path) -> str:
    return texts.fill(
        QCoreApplication.translate(
            "Settings",
            "Không lưu được file log vào {path}. Hãy chọn thư mục khác mà bạn có quyền ghi.",
        ),
        path=printable(str(path)),
    )


def export_other_error_text() -> str:
    return QCoreApplication.translate(
        "Settings", "Không xuất được log vì một lỗi không mong đợi. Hãy thử lại."
    )


def device_status_text(view: DeviceView) -> str:
    t = QCoreApplication.translate
    if view.connected:
        return t("Settings", "đã kết nối")
    if view.online:
        return t("Settings", "đang trong mạng")
    return t("Settings", "không thấy trong mạng")


def default_export_dir() -> str:
    """Thư mục mở sẵn của hộp “Xuất log…”: Documents nếu có thật, không thì thư mục nhà.

    Qt vẫn trả đường dẫn Documents khi thư mục đó chưa được tạo (máy Linux mới), và
    `QFileDialog.setDirectory` bỏ qua thư mục không tồn tại.
    """
    docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    if docs and Path(docs).is_dir():
        return docs
    return str(Path.home())


def default_export_name(now: float | None = None) -> str:
    """`teleport-log-YYYYMMDD-HHMMSS.zip` theo giờ máy."""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    return f"teleport-log-{stamp}.zip"


def notices_path() -> Path | None:
    """`THIRD-PARTY-NOTICES.txt` cạnh `sys.executable` nếu có (bản đóng gói), không thì None."""
    try:
        path = Path(sys.executable).resolve().parent / NOTICES_FILE
        return path if path.is_file() else None
    except (OSError, ValueError):
        return None


# ---- Số ----------------------------------------------------------------------------------------


def default_retention_days() -> int:
    """Ngưỡng dọn tạm mặc định (ngày), đọc `storage.TEMP_RETENTION` lúc gọi."""
    return max(1, round(storage.TEMP_RETENTION / 86400))


def rate_to_bytes(mb_per_s: float) -> int:
    """MB/s của ô → byte/giây gửi cho node, kẹp trong khoảng node nhận."""
    value = round(mb_per_s * MB)
    return max(app_transfers.MIN_RATE_LIMIT, min(app_settings.MAX_RATE_LIMIT, value))


def bytes_to_rate(value: int) -> float:
    """byte/giây → MB/s hiện trên ô (một số lẻ, kẹp trong khoảng của ô)."""
    return max(RATE_MIN_MB, min(RATE_MAX_MB, round(value / MB, 1)))


def _nfc_key(view: DeviceView) -> tuple[str, str]:
    return (unicodedata.normalize("NFC", view.name or "").casefold(), view.device_id)


def trusted_devices(views: Sequence[DeviceView]) -> list[DeviceView]:
    """Máy đã ghép đôi (kể cả ngoại tuyến), sắp NFC(tên).casefold() rồi `device_id`."""
    return sorted((v for v in views if isinstance(v, DeviceView) and v.paired), key=_nfc_key)


# ---- Thành phần --------------------------------------------------------------------------------


def _plain(parent: QWidget | None = None, *, object_name: str = "", wrap: bool = True) -> QLabel:
    label = QLabel(parent)
    if object_name:
        label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(wrap)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return label


def _repolish(widget: QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class _ElidedLabel(QLabel):
    """Nhãn một dòng tự cắt chữ theo bề ngang (giữa hay cuối); chữ đầy đủ ở `full_text`."""

    def __init__(self, mode: Qt.TextElideMode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = mode
        self._full = ""
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    @property
    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def minimumSizeHint(self) -> QSize:
        return QSize(0, super().minimumSizeHint().height())

    def _elide(self) -> None:
        width = self.contentsRect().width()
        text = self._full
        if text and width > 0:
            text = QFontMetrics(self.font()).elidedText(text, self._mode, width)
        if self.text() != text:
            self.setText(text)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self._elide()


class _NameField(QLineEdit):
    """Ô tên thiết bị: Esc trả tên đã lưu khi chữ khác tên đó; trùng thì để Esc cho cửa sổ."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.saved = ""
        self.setMaxLength(NAME_MAX_INPUT)

    @staticmethod
    def _is_plain_escape(event: QEvent) -> bool:
        return (
            isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        )

    def event(self, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.ShortcutOverride
            and self._is_plain_escape(event)
            and self.text() != self.saved
        ):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._is_plain_escape(event) and self.text() != self.saved:
            self.setText(self.saved)
            self.reverted.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    reverted = Signal()


class _CommitSpin:
    """Chốt giá trị của ô số (spec D2 mục 9.4): `editingFinished`, hay `SPIN_COMMIT_MS` sau mũi tên."""

    def __init__(self, spin: QSpinBox | QDoubleSpinBox, commit: Callable[[], None]) -> None:
        spin.setKeyboardTracking(False)  # gõ phím không phát `valueChanged` tới khi chốt
        self._timer = QTimer(spin)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(commit)
        spin.valueChanged.connect(lambda _v: self._timer.start(SPIN_COMMIT_MS))
        self._commit = commit
        spin.editingFinished.connect(self._finished)

    def _finished(self) -> None:
        self._timer.stop()
        self._commit()

    def stop(self) -> None:
        self._timer.stop()


class _DecimalSpin(QDoubleSpinBox):
    """Ô số lẻ nhận cả “,” lẫn “.” làm dấu thập phân, không có dấu nhóm hàng nghìn.

    `QDoubleSpinBox` theo locale lặng lẽ bỏ dấu nhóm: giao diện English gõ “2,5” thành 25. Ở đây cả
    hai dấu đổi thành dấu thập phân của locale trước khi kiểm, nên “2,5” và “2.5” đều là 2,5, còn
    “1,000” (quá số chữ số lẻ) bị từ chối.
    """

    def _normalized(self, text: str) -> str:
        point = self.locale().decimalPoint()
        return text.replace(",", point).replace(".", point)

    def validate(self, text: str, pos: int) -> tuple[QValidator.State, str, int]:
        return super().validate(self._normalized(text), pos)

    def valueFromText(self, text: str) -> float:
        return super().valueFromText(self._normalized(text))


class TrustedDeviceRow(QFrame):
    """Một máy đã ghép đôi: avatar, tên, “HĐH · trạng thái”, “Hỏi trước khi nhận”, “Đồng bộ
    clipboard”, “Hủy ghép đôi…”."""

    ask_toggled = Signal(str, bool)
    clipboard_toggled = Signal(str, bool)
    unpair_requested = Signal(str)

    def __init__(self, view: DeviceView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("trustedDeviceRow")
        self.setProperty(theme.SURFACE_PROPERTY, "raised")
        # Không cao hơn cần: QBoxLayout chia chỗ thừa cho hàng có nhãn xuống dòng (heightForWidth).
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self._view = view
        self._narrow: bool | None = None
        self.avatar = DeviceAvatar(self, diameter=_AVATAR, ring="surface_raised")
        self.name_label = _ElidedLabel(Qt.TextElideMode.ElideRight, self)
        self.name_label.setObjectName("trustedDeviceName")
        font = self.name_label.font()
        font.setWeight(font.Weight.DemiBold)
        self.name_label.setFont(font)
        self.detail_label = _plain(self, object_name="")  # ngắn; xuống dòng thay vì cắt
        self.detail_label.setObjectName("trustedDeviceDetail")
        self.detail_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.ask_checkbox = QCheckBox(self)
        self.ask_checkbox.setObjectName("askBeforeReceive")
        self.ask_checkbox.setChecked(True)
        self.clipboard_checkbox = QCheckBox(self)
        self.clipboard_checkbox.setObjectName("syncClipboard")
        self.clipboard_checkbox.setChecked(False)
        self.unpair_button = QPushButton(self)
        self.unpair_button.setObjectName("unpairButton")
        self.ask_checkbox.clicked.connect(
            lambda checked: self.ask_toggled.emit(self.device_id, bool(checked))
        )
        self.clipboard_checkbox.clicked.connect(
            lambda checked: self.clipboard_toggled.emit(self.device_id, bool(checked))
        )
        self.unpair_button.clicked.connect(lambda: self.unpair_requested.emit(self.device_id))

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self.name_label)
        text.addWidget(self.detail_label)
        self._head = QHBoxLayout()
        self._head.setContentsMargins(0, 0, 0, 0)
        self._head.setSpacing(theme.SPACING[2])
        self._head.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        self._head.addLayout(text, 1)
        self._actions = QHBoxLayout()
        self._actions.setContentsMargins(0, 0, 0, 0)
        self._actions.setSpacing(theme.SPACING[2])
        self._actions.addWidget(self.ask_checkbox)
        self._actions.addWidget(self.clipboard_checkbox)
        self._actions.addWidget(self.unpair_button)
        self._actions.addStretch(0)
        # Rộng: [đầu hàng | ô, nút] một hàng; hẹp: ô và nút xuống dưới, thẳng cột chữ.
        self._box = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self._box.setContentsMargins(theme.SPACING[2], theme.SPACING[1], theme.SPACING[3], theme.SPACING[1])
        self._box.setSpacing(theme.SPACING[3])
        self._box.addLayout(self._head, 1)
        self._box.addLayout(self._actions, 0)
        self._place_actions()
        self.set_view(view)

    @property
    def device_id(self) -> str:
        return self._view.device_id

    @property
    def view(self) -> DeviceView:
        return self._view

    def focus_widgets(self) -> list[QWidget]:
        return [self.ask_checkbox, self.clipboard_checkbox, self.unpair_button]

    def set_view(self, view: DeviceView) -> None:
        self._view = view
        self.retranslate()

    def set_ask(self, ask: bool) -> None:
        """Đặt ô “Hỏi trước khi nhận” (không phát `ask_toggled`)."""
        self.ask_checkbox.setChecked(bool(ask))

    def set_clipboard(self, enabled: bool) -> None:
        """Đặt ô “Đồng bộ clipboard” (không phát `clipboard_toggled`)."""
        self.clipboard_checkbox.setChecked(bool(enabled))

    def retranslate(self) -> None:
        view = self._view
        name = texts.peer_label(view.name, view.device_id)
        os_name = texts.os_label(view.os)
        status = device_status_text(view)
        detail = f"{os_name} · {status}" if os_name else status
        self.name_label.set_full_text(name)
        self.detail_label.setText(detail)
        summary = ", ".join(part for part in (name, os_name, status) if part)
        self.setAccessibleName(summary)
        self.setToolTip(safe_tooltip(f"{name}\n{detail}"))
        self.avatar.set_presence(Presence.ONLINE if (view.connected or view.online) else Presence.OFFLINE)
        ask = QCoreApplication.translate("Settings", "Hỏi trước khi nhận")
        self.ask_checkbox.setText(ask)
        self.ask_checkbox.setAccessibleName(
            texts.fill(QCoreApplication.translate("Settings", "{option}: {name}"), option=ask, name=name)
        )
        clipboard = QCoreApplication.translate("Settings", "Đồng bộ clipboard")
        self.clipboard_checkbox.setText(clipboard)
        option = QCoreApplication.translate("Settings", "{option}: {name}")
        self.clipboard_checkbox.setAccessibleName(texts.fill(option, option=clipboard, name=name))
        unpair = QCoreApplication.translate("Settings", "Hủy ghép đôi…")
        self.unpair_button.setText(unpair)
        self.unpair_button.setAccessibleName(
            texts.fill(QCoreApplication.translate("Settings", "{option}: {name}"), option=unpair, name=name)
        )
        self.ask_checkbox.setAccessibleDescription(summary)
        self.clipboard_checkbox.setAccessibleDescription(summary)
        self.unpair_button.setAccessibleDescription(summary)

    def _place_actions(self) -> None:
        narrow = self.width() < DEVICE_ROW_WIDE
        if narrow == self._narrow:
            return
        self._narrow = narrow
        if narrow:
            self._box.setDirection(QBoxLayout.Direction.TopToBottom)
            self._box.setSpacing(theme.SPACING[1])
            self._actions.setContentsMargins(_AVATAR + theme.SPACING[2], 0, 0, 0)
        else:
            self._box.setDirection(QBoxLayout.Direction.LeftToRight)
            self._box.setSpacing(theme.SPACING[3])
            self._actions.setContentsMargins(0, 0, 0, 0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_actions()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


# ---- Ảnh chụp cài đặt --------------------------------------------------------------------------


@dataclass(frozen=True)
class SettingsSnapshot:
    """Cài đặt hiện tại đọc trên thread node (`read_snapshot`)."""

    name: str
    visible: bool
    rate_limit: int | None
    temp_retention_days: int | None
    language: str | None
    autostart: bool
    devices: Mapping[str, DeviceSettings]
    theme: str | None = None  # trường `theme` của settings.json (None = theo hệ điều hành)
    accent: str | None = None  # trường `accent` (None = mặc định; mã lạ giữ nguyên)


def _read_device_settings(node: Node) -> dict[str, DeviceSettings]:
    return {v.device_id: node.device_settings(v.device_id) for v in node.devices() if v.paired}


def read_snapshot(node: Node) -> SettingsSnapshot:
    """Thread node: ảnh chụp cài đặt cho trang (tên đang dùng, ẩn/hiện, cài đặt theo thiết bị)."""
    settings = node.settings
    return SettingsSnapshot(
        name=node.name,
        visible=node.visible,
        rate_limit=settings.rate_limit,
        temp_retention_days=settings.temp_retention_days,
        language=settings.language,
        autostart=settings.autostart,
        devices=_read_device_settings(node),
        theme=settings.theme,
        accent=settings.accent,
    )


# ---- Trang -------------------------------------------------------------------------------------


class _ShortcutTable(QTableWidget):
    """Bảng phím tắt chỉ để xem (xem docstring module, “Bảng Phím tắt”)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(0, 2, parent)
        self.setObjectName("shortcutsTable")
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # Tab và bấm chuột
        self.setTabKeyNavigation(False)
        self.setAlternatingRowColors(False)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.setShowGrid(False)
        self.setCornerButtonEnabled(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        vertical = self.verticalHeader()
        vertical.setVisible(False)
        vertical.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        header = self.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setHighlightSections(False)
        header.setSectionsClickable(False)
        self._fitting = False
        self._refit = False
        # Cột giãn đổi bề ngang sau khi bảng đổi cỡ (header tự hẹn lại bố cục): tính lại ở vòng lặp sau.
        self._fit_timer = QTimer(self)
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self.fit_height)
        header.sectionResized.connect(lambda *_args: self._fit_timer.start())
        # Lề ngang của ô (chữ không dính mép khung); cột 1 vừa nội dung nên tính cả lề này.
        self.setStyleSheet(
            f"QTableWidget::item {{ padding: 0px {_TABLE_CELL_PADDING}px; }}"
            f"QHeaderView::section {{ padding: 4px {_TABLE_CELL_PADDING + 1}px; }}"
        )

    def set_rows(self, rows: Sequence[tuple[str, str]], headers: tuple[str, str]) -> None:
        """Đặt chữ các hàng (mô tả, phím) và tiêu đề cột; giữ hàng đang chọn."""
        current = self.currentRow()
        self.setHorizontalHeaderLabels(list(headers))
        self.setRowCount(len(rows))
        for row, (description, key) in enumerate(rows):
            for column, text in enumerate((description, key)):
                item = self.item(row, column)
                if item is None:
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    self.setItem(row, column, item)
                item.setText(text)
                spoken = texts.fill("{description}: {key}", description=description, key=key)
                item.setData(Qt.ItemDataRole.AccessibleTextRole, spoken if column == 0 else key)
                item.setToolTip("")
        if 0 <= current < len(rows) and self.currentRow() != current:
            self.setCurrentCell(current, 0)
        self.fit_height()
        self._fit_timer.start()

    def fit_height(self) -> None:
        """Cao vừa đúng tiêu đề và mọi hàng (không thanh cuộn).

        Đổi chiều cao kéo theo đổi bề ngang cột (và chiều cao hàng xuống dòng): lời gọi tới trong lúc
        đang tính thì tính lại sau, tới khi đứng yên."""
        if self._fitting:
            self._refit = True
            return
        self._fitting = True
        try:
            for _ in range(_FIT_PASSES):
                self._refit = False
                self._fit_rows()
                header = self.horizontalHeader()
                height = max(header.height(), header.sizeHint().height()) if not header.isHidden() else 0
                height += sum(self.rowHeight(row) for row in range(self.rowCount()))
                height += 2 * self.frameWidth()
                if self.height() != height or self.minimumHeight() != height:
                    self.setFixedHeight(height)
                if not self._refit:
                    break
        finally:
            self._fitting = False

    def _fit_rows(self) -> None:
        """Chiều cao mỗi hàng theo chữ xuống dòng ở bề ngang cột hiện tại (không dùng
        `resizeRowsToContents`: tiêu đề dọc đã ẩn vẫn góp cỡ của nó vào hàng)."""
        metrics = QFontMetrics(self.font())
        style = self.style()
        frame = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin, None, self) + 1
        margin = 2 * (frame + _TABLE_CELL_PADDING)
        flags = int(Qt.TextFlag.TextWordWrap)
        header = self.horizontalHeader()
        for row in range(self.rowCount()):
            height = metrics.height()
            for column in range(self.columnCount()):
                item = self.item(row, column)
                if item is None:
                    continue
                width = max(1, header.sectionSize(column) - margin)
                rect = metrics.boundingRect(QRect(0, 0, width, 0), flags, item.text())
                height = max(height, rect.height())
            target = height + 2 * _TABLE_ROW_PADDING
            if self.rowHeight(row) != target:
                self.setRowHeight(row, target)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.fit_height()
        self._fit_timer.start()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._fit_timer.start()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (QEvent.Type.FontChange, QEvent.Type.StyleChange):
            self.fit_height()
            self._fit_timer.start()

    def wheelEvent(self, event: QWheelEvent) -> None:
        # Không có gì để cuộn trong bảng: để bánh xe tới vùng cuộn của mục chứa bảng.
        event.ignore()


class SettingsPage(QWidget):
    """Trang “Cài đặt” (xem docstring module). Không gọi node; `set_*` không phát signal."""

    name_submitted = Signal(str)
    visible_toggled = Signal(bool)
    language_selected = Signal(object)  # mã ngôn ngữ hay None (theo hệ điều hành)
    theme_selected = Signal(object)  # None (theo hệ điều hành) | "light" | "dark"
    accent_selected = Signal(object)  # None (mặc định) | mã màu nhấn
    autostart_toggled = Signal(bool)
    rate_limit_changed = Signal(object)  # byte/giây hay None
    retention_changed = Signal(object)  # ngày hay None (= mặc định)
    ask_toggled = Signal(str, bool)
    clipboard_toggled = Signal(str, bool)  # device_id, bật “Đồng bộ clipboard”
    unpair_requested = Signal(str)
    clear_history_requested = Signal()
    export_logs_requested = Signal()
    open_receive_dir_requested = Signal(object)  # Path
    change_receive_dir_requested = Signal()
    discover_requested = Signal()
    open_notices_requested = Signal(object)  # Path
    notice_action = Signal()

    def __init__(self, model: DeviceListModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("settingsPage")
        self.model = model
        self._loaded = False
        self._visible = True
        self._name = ""
        self._autostart: autostart.AutostartState | None = autostart.AutostartState.OFF
        self._rate: int | None = None  # giá trị đã biết (đặt từ ngoài hay vừa phát)
        self._retention: int | None = None
        self._device_settings: dict[str, DeviceSettings] = {}
        self._rows: dict[str, TrustedDeviceRow] = {}
        self._order: list[str] = []
        self._receive_dir: Path | None = None
        self._unavailable: Path | None = None
        self._pending: Path | None = None
        self._export_running = False
        self._notices = notices_path()
        self._name_error: str | None = None

        self.header = PageHeader(page_title(), self)
        self.nav = QListWidget(self)
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(NAV_WIDTH)
        self.nav.setFrameShape(QFrame.Shape.NoFrame)
        self.nav.setIconSize(QSize(_NAV_ICON, _NAV_ICON))
        self.nav.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.nav.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.nav.setUniformItemSizes(True)
        for section in Section:
            item = QListWidgetItem(self.nav)
            item.setData(Qt.ItemDataRole.UserRole, section.value)
            item.setSizeHint(QSize(0, _NAV_ROW_HEIGHT))
        self.info_bar = InfoBar(self)
        self.info_bar.setObjectName("settingsInfo")
        self.info_bar.action_triggered.connect(self.notice_action)
        self.sections = QStackedWidget(self)
        self.sections.setObjectName("settingsSections")
        self._section_widgets: dict[Section, QScrollArea] = {}
        self._section_titles: dict[Section, QLabel] = {}
        self._section_layouts: dict[Section, QVBoxLayout] = {}
        for section in Section:
            self._add_section(section)

        self._build_general()
        self._build_appearance()
        self._build_privacy()
        self._build_devices()
        self._build_transfer()
        self._build_advanced()

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        bar_box = QVBoxLayout()
        bar_box.setContentsMargins(SECTION_MARGIN, theme.SPACING[3], SECTION_MARGIN, 0)
        bar_box.addWidget(self.info_bar)
        right.addLayout(bar_box)
        right.addWidget(self.sections, 1)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.nav)
        body.addLayout(right, 1)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        outer.addLayout(body, 1)

        self.nav.currentRowChanged.connect(self._on_nav_row)
        self.nav.setCurrentRow(0)
        self.setFocusProxy(self.nav)
        for signal in (
            model.modelReset,
            model.rowsInserted,
            model.rowsRemoved,
            model.rowsMoved,
            model.dataChanged,
            model.layoutChanged,
        ):
            signal.connect(self._sync_devices)

        self._restyle()
        self.retranslate()
        self._sync_devices()
        self.set_loaded(False)

    # ---- Dựng các mục --------------------------------------------------------------------------

    def _add_section(self, section: Section) -> None:
        scroll = QScrollArea(self.sections)
        scroll.setObjectName(f"settingsSection_{section.value}")
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        content = QWidget()
        content.setObjectName(f"settingsContent_{section.value}")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(SECTION_MARGIN, theme.SPACING[3], SECTION_MARGIN, SECTION_MARGIN)
        layout.setSpacing(ROW_SPACING)
        title = _plain(content, object_name=f"settingsTitle_{section.value}")
        title.setFont(theme.font_for(theme.TextStyle.SECTION, title.font()))
        layout.addWidget(title)
        layout.addSpacing(theme.SPACING[0])
        scroll.setWidget(content)
        viewport = scroll.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)
        content.setAutoFillBackground(False)
        self.sections.addWidget(scroll)
        self._section_widgets[section] = scroll
        self._section_titles[section] = title
        self._section_layouts[section] = layout

    def _row(self, section: Section, object_name: str) -> SettingsRow:
        row = SettingsRow(self._section_widgets[section].widget(), object_name=object_name)
        self._section_layouts[section].addWidget(row)
        return row

    def _build_general(self) -> None:
        self.name_row = self._row(Section.GENERAL, "nameRow")
        self.name_edit = _NameField(self.name_row)
        self.name_edit.setObjectName("deviceNameEdit")
        self.name_edit.setMinimumWidth(220)
        self.name_edit.editingFinished.connect(self._on_name_finished)
        self.name_edit.textEdited.connect(lambda _text: self.set_name_error(None))
        self.name_edit.reverted.connect(lambda: self.set_name_error(None))
        self.name_row.set_control(self.name_edit)
        self.name_error = _plain(self.name_row, object_name="deviceNameError")
        self.name_error.setProperty(theme.TONE_PROPERTY, "danger")
        self.name_error.setVisible(False)
        self.name_row.add_line(self.name_error)

        self.receive_row = self._row(Section.GENERAL, "receiveDirRow")
        self.receive_dir_label = _ElidedLabel(Qt.TextElideMode.ElideMiddle, self.receive_row)
        self.receive_dir_label.setObjectName("receiveDirLabel")
        self.receive_dir_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.receive_row.add_line(self.receive_dir_label)
        buttons = QWidget(self.receive_row)
        buttons_layout = QHBoxLayout(buttons)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(theme.SPACING[1])
        self.open_dir_button = QPushButton(buttons)
        self.open_dir_button.setObjectName("openReceiveDir")
        self.change_dir_button = QPushButton(buttons)
        self.change_dir_button.setObjectName("changeReceiveDir")
        self.change_dir_button.setVisible(False)
        buttons_layout.addWidget(self.open_dir_button)
        buttons_layout.addWidget(self.change_dir_button)
        buttons.setProperty("keepAccessible", True)
        self.receive_row.set_control(buttons)
        self.open_dir_button.clicked.connect(self._on_open_dir)
        self.change_dir_button.clicked.connect(self.change_receive_dir_requested)

        self.autostart_row = self._row(Section.GENERAL, "autostartRow")
        self.autostart_switch = ToggleSwitch(self.autostart_row)
        self.autostart_switch.setObjectName("autostartSwitch")
        self.autostart_switch.clicked.connect(lambda checked: self.autostart_toggled.emit(bool(checked)))
        self.autostart_row.set_control(self.autostart_switch)
        self.autostart_state_label = _plain(self.autostart_row, object_name="autostartState")
        self.autostart_state_label.setProperty(theme.TONE_PROPERTY, "warning")
        self.autostart_state_label.setVisible(False)
        self.autostart_row.add_line(self.autostart_state_label)
        self._section_layouts[Section.GENERAL].addStretch(1)

    def _build_appearance(self) -> None:
        layout = self._section_layouts[Section.APPEARANCE]
        self.appearance = AppearanceSection(self._section_widgets[Section.APPEARANCE].widget())
        self.appearance.theme_selected.connect(self.theme_selected)
        self.appearance.accent_selected.connect(self.accent_selected)
        self.appearance.language_selected.connect(self.language_selected)
        layout.addWidget(self.appearance)
        layout.addStretch(1)

    @property
    def language_row(self) -> SettingsRow:
        return self.appearance.language_row

    @property
    def language_combo(self) -> QComboBox:
        return self.appearance.language_combo

    def _build_privacy(self) -> None:
        self.visible_row = self._row(Section.PRIVACY, "visibleRow")
        self.visible_switch = ToggleSwitch(self.visible_row)
        self.visible_switch.setObjectName("visibleSwitch")
        self.visible_switch.setChecked(True)
        self.visible_switch.clicked.connect(self._on_visible_clicked)
        self.visible_row.set_control(self.visible_switch)
        self.hidden_label = _plain(self.visible_row, object_name="hiddenNotice")
        self.hidden_label.setProperty(theme.TONE_PROPERTY, "warning")
        self.hidden_label.setVisible(False)
        self.visible_row.add_line(self.hidden_label)

        self.history_row = self._row(Section.PRIVACY, "historyRow")
        self.clear_history_button = QPushButton(self.history_row)
        self.clear_history_button.setObjectName("clearHistoryButton")
        self.clear_history_button.clicked.connect(self.clear_history_requested)
        self.history_row.set_control(self.clear_history_button)
        self._section_layouts[Section.PRIVACY].addStretch(1)

    def _build_devices(self) -> None:
        content = self._section_widgets[Section.DEVICES].widget()
        layout = self._section_layouts[Section.DEVICES]
        self.devices_intro = _plain(content, object_name="trustedIntro")
        self.devices_intro.setProperty(theme.TONE_PROPERTY, "muted")
        layout.addWidget(self.devices_intro)
        self.device_list = QWidget(content)
        self.device_list.setObjectName("trustedDeviceList")
        self._device_layout = QVBoxLayout(self.device_list)
        self._device_layout.setContentsMargins(0, 0, 0, 0)
        self._device_layout.setSpacing(ROW_SPACING)
        layout.addWidget(self.device_list)
        self.devices_empty = EmptyState(content)
        self.devices_empty.setObjectName("trustedEmpty")
        self.devices_empty.action_triggered.connect(self.discover_requested)
        layout.addWidget(self.devices_empty)
        layout.addStretch(1)

    def _build_transfer(self) -> None:
        self.rate_row = self._row(Section.TRANSFER, "rateRow")
        box = QWidget(self.rate_row)
        box_layout = QHBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(theme.SPACING[1])
        self.rate_checkbox = QCheckBox(box)
        self.rate_checkbox.setObjectName("rateCheckbox")
        self.rate_spin = _DecimalSpin(box)
        self.rate_spin.setObjectName("rateSpin")
        self.rate_spin.setDecimals(1)
        self.rate_spin.setRange(RATE_MIN_MB, RATE_MAX_MB)
        self.rate_spin.setSingleStep(1.0)
        self.rate_spin.setValue(RATE_DEFAULT_MB)
        self.rate_spin.setEnabled(False)
        self.rate_spin.setAccelerated(True)
        box_layout.addWidget(self.rate_checkbox)
        box_layout.addWidget(self.rate_spin)
        box.setProperty("keepAccessible", True)
        self.rate_row.set_control(box)
        self.rate_checkbox.clicked.connect(self._on_rate_checkbox)
        self._rate_commit = _CommitSpin(self.rate_spin, self._commit_rate)

        self.retention_row = self._row(Section.TRANSFER, "retentionRow")
        self.retention_spin = QSpinBox(self.retention_row)
        self.retention_spin.setObjectName("retentionSpin")
        self.retention_spin.setRange(app_settings.MIN_RETENTION_DAYS, app_settings.MAX_RETENTION_DAYS)
        self.retention_spin.setValue(default_retention_days())
        self.retention_spin.valueChanged.connect(self._update_retention_suffix)
        self.retention_row.set_control(self.retention_spin)
        self._retention_commit = _CommitSpin(self.retention_spin, self._commit_retention)
        self._section_layouts[Section.TRANSFER].addStretch(1)

    def _build_advanced(self) -> None:
        self.export_row = self._row(Section.ADVANCED, "exportRow")
        self.export_button = QPushButton(self.export_row)
        self.export_button.setObjectName("exportLogsButton")
        self.export_button.clicked.connect(self.export_logs_requested)
        self.export_row.set_control(self.export_button)

        self.shortcuts_row = self._row(Section.ADVANCED, "shortcutsRow")
        self.shortcuts_table = _ShortcutTable(self.shortcuts_row)
        self.shortcuts_row.add_line(self.shortcuts_table)

        self.version_row = self._row(Section.ADVANCED, "versionRow")
        self.license_row = self._row(Section.ADVANCED, "licenseRow")
        self.notices_button = QPushButton(self.license_row)
        self.notices_button.setObjectName("noticesButton")
        self.notices_button.clicked.connect(self._on_notices)
        if self._notices is not None:
            self.license_row.set_control(self.notices_button)
        else:
            self.notices_button.setVisible(False)
        self._section_layouts[Section.ADVANCED].addStretch(1)

    # ---- API -----------------------------------------------------------------------------------

    @property
    def loaded(self) -> bool:
        return self._loaded

    @property
    def current_section(self) -> Section:
        item = self.nav.currentItem()
        value = item.data(Qt.ItemDataRole.UserRole) if item is not None else Section.GENERAL.value
        return Section(value)

    def device_rows(self) -> list[TrustedDeviceRow]:
        """Hàng thiết bị theo thứ tự đang hiện."""
        return [self._rows[i] for i in self._order]

    def device_row(self, device_id: str) -> TrustedDeviceRow | None:
        return self._rows.get(device_id)

    def device_ids(self) -> list[str]:
        return list(self._order)

    def _ask_of(self, device_id: str) -> bool:
        return self._device_settings.get(device_id, DeviceSettings()).ask_before_receive

    def _clipboard_of(self, device_id: str) -> bool:
        return self._device_settings.get(device_id, DeviceSettings()).clipboard

    def set_loaded(self, loaded: bool) -> None:
        """Đã có ảnh chụp cài đặt: bật các control đọc/ghi node.

        Mục Nâng cao và hàng Thư mục nhận (theo `ReceiveDirController`, không theo ảnh chụp) luôn dùng
        được."""
        self._loaded = bool(loaded)
        for section in (Section.PRIVACY, Section.DEVICES, Section.TRANSFER):
            content = self._section_widgets[section].widget()
            if content is not None:
                content.setEnabled(self._loaded)
        for row in (self.name_row, self.autostart_row):
            row.setEnabled(self._loaded)
        self.appearance.set_loaded(self._loaded)

    def set_values(self, s: SettingsSnapshot) -> None:
        """Đặt mọi giá trị từ ảnh chụp (không phát signal)."""
        self.set_name(s.name)
        self.set_visible(s.visible)
        self.set_rate_limit(s.rate_limit)
        self.set_retention(s.temp_retention_days)
        self.set_language(s.language, i18n.available_languages())
        self.appearance.set_theme(s.theme)
        self.appearance.set_accent(s.accent)
        with _blocked(self.autostart_switch):
            self.autostart_switch.setChecked(bool(s.autostart))
        self.set_device_settings(s.devices)

    def set_name(self, name: str) -> None:
        self._name = name
        self.name_edit.saved = name
        self.name_edit.setText(name)
        self.set_name_error(None)

    def set_name_error(self, text: str | None) -> None:
        self._name_error = text
        self.name_error.setText(text or "")
        self.name_error.setVisible(bool(text))
        description = self.hint_for_name()
        self.name_edit.setAccessibleDescription(f"{text} {description}" if text else description)

    def reject_name(self, confirmed: str, error: str) -> None:
        """Node từ chối tên vừa gửi: tên đã lưu trở về `confirmed`, giữ chữ trong ô, hiện lỗi.

        Enter lần nữa gửi lại (chữ trong ô khác tên đã lưu)."""
        self._name = confirmed
        self.name_edit.saved = confirmed
        self.set_name_error(error)

    def hint_for_name(self) -> str:
        return name_hint(self._visible)

    def set_visible(self, visible: bool) -> None:
        self._visible = bool(visible)
        with _blocked(self.visible_switch):
            self.visible_switch.setChecked(self._visible)
        self._update_visibility_texts()

    def set_language(self, code: str | None, available: Sequence[str]) -> None:
        self.appearance.set_language(code, available)

    def set_theme(self, value: str | None) -> None:
        self.appearance.set_theme(value)

    def set_accent(self, value: str | None) -> None:
        self.appearance.set_accent(value)

    def set_autostart(self, state: autostart.AutostartState | None) -> None:
        """Trạng thái registry (None: đọc lỗi); UNSUPPORTED hay `autostart.supported()` False → ẩn hàng."""
        self._autostart = None if state is None else autostart.AutostartState(state)
        with _blocked(self.autostart_switch):
            self.autostart_switch.setChecked(self._autostart is autostart.AutostartState.ON)
        self._update_autostart()

    def set_rate_limit(self, value: int | None) -> None:
        self._rate_commit.stop()
        self._rate = value
        with _blocked(self.rate_checkbox), _blocked(self.rate_spin):
            self.rate_checkbox.setChecked(value is not None)
            if value is not None:
                self.rate_spin.setValue(bytes_to_rate(value))
            self.rate_spin.setEnabled(value is not None)

    def set_retention(self, days: int | None) -> None:
        self._retention_commit.stop()
        self._retention = days
        with _blocked(self.retention_spin):
            self.retention_spin.setValue(default_retention_days() if days is None else days)
        self._update_retention_suffix()

    def _update_retention_suffix(self) -> None:
        """Chữ đơn vị quanh số của ô ngày theo giá trị đang có (English “1 day” / “2 days”): dịch câu
        đếm “%n ngày” rồi tách phần trước/sau số làm tiền tố/hậu tố của ô."""
        value = self.retention_spin.value()
        full = QCoreApplication.translate("Settings", "%n ngày", "đơn vị của ô số ngày", value)
        before, found, after = full.partition(str(value))
        self.retention_spin.setPrefix(before if found else "")
        self.retention_spin.setSuffix(after if found else "")

    def set_device_settings(self, mapping: Mapping[str, DeviceSettings]) -> None:
        self._device_settings = dict(mapping)
        for device_id, row in self._rows.items():
            row.set_ask(self._ask_of(device_id))
            row.set_clipboard(self._clipboard_of(device_id))

    def set_receive_dir(
        self, path: Path | None, unavailable: Path | None = None, pending: Path | None = None
    ) -> None:
        self._receive_dir, self._unavailable, self._pending = path, unavailable, pending
        self._update_receive_dir()

    def set_change_available(self, available: bool) -> None:
        """Hiện nút “Đổi…” (sau B1b, khi đã nối `ReceiveDirController`)."""
        self.change_dir_button.setVisible(bool(available))
        self._update_tab_order()

    def set_export_running(self, running: bool) -> None:
        self._export_running = bool(running)
        self.export_button.setEnabled(not self._export_running)
        self._update_export_text()

    def show_section(
        self,
        section: Section,
        device_id: str | None = None,
        *,
        focus: Literal["ask", "clipboard"] = "ask",
    ) -> None:
        """Mở mục `section`; `device_id` (mục Thiết bị tin cậy) → tiêu điểm vào ô “Hỏi trước khi nhận”
        của máy đó, hay ô “Đồng bộ clipboard” khi `focus="clipboard"` và trang đã có ảnh chụp."""
        self.nav.setCurrentRow(list(Section).index(Section(section)))
        if device_id is not None:
            row = self._rows.get(device_id)
            if row is not None:
                use_clipboard = focus == "clipboard" and self._loaded
                target = row.clipboard_checkbox if use_clipboard else row.ask_checkbox
                target.setFocus(Qt.FocusReason.OtherFocusReason)
                self._section_widgets[Section.DEVICES].ensureWidgetVisible(row)

    def show_notice(self, level: InfoLevel, text: texts.Text, *, action: texts.Text | None = None) -> None:
        self.info_bar.show_message(InfoLevel(level), text, action=action)

    def clear_notice(self) -> None:
        self.info_bar.clear()

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        title = page_title()
        self.header.set_title(title)
        self.setAccessibleName(title)
        self.nav.setAccessibleName(t("Settings", "Các mục cài đặt"))
        for index, section in enumerate(Section):
            item = self.nav.item(index)
            if item is not None:
                item.setText(section_title(section))
            self._section_titles[section].setText(section_title(section))
            self._section_widgets[section].setAccessibleName(section_title(section))

        self.name_row.set_text(t("Settings", "Tên thiết bị"), self.hint_for_name())
        self.name_edit.setPlaceholderText(t("Settings", "Tên thiết bị"))
        if self._name_error is not None:
            self.set_name_error(self._name_error)
        self.receive_row.set_text(t("Settings", "Thư mục nhận"))
        self.open_dir_button.setText(t("Settings", "Mở"))
        self.open_dir_button.setAccessibleName(t("Settings", "Mở thư mục nhận"))
        self.change_dir_button.setText(t("Settings", "Đổi…"))
        self.change_dir_button.setAccessibleName(t("Settings", "Đổi thư mục nhận"))
        self.autostart_row.set_text(
            t("Settings", "Khởi động cùng Windows"),
            t("Settings", "Teleport chạy ở khay hệ thống khi bạn đăng nhập Windows, sẵn sàng nhận file."),
        )
        self.visible_row.set_text(
            t("Settings", "Cho máy chưa ghép đôi thấy máy này"),
            t(
                "Settings",
                "Máy đã ghép đôi tự kết nối được khi ít nhất một trong hai máy đang hiện, "
                "hoặc khi hai máy đã từng kết nối và địa chỉ không đổi.",
            ),
        )
        self.history_row.set_text(
            t("Settings", "Lịch sử truyền file"),
            t(
                "Settings",
                "Teleport chỉ lưu tên file, cỡ và kết quả của các lượt truyền trên máy này, "
                "không lưu nội dung.",
            ),
        )
        self.clear_history_button.setText(t("Settings", "Xóa toàn bộ lịch sử…"))
        intro = t(
            "Settings",
            "Các máy đã ghép đôi với máy này. Bỏ chọn “Hỏi trước khi nhận” để tự nhận file từ máy đó. "
            "Clipboard chỉ đồng bộ khi cả hai máy cùng bật “Đồng bộ clipboard”; mật khẩu chép từ trình "
            "quản lý mật khẩu không được gửi.",
        )
        self.devices_intro.setText(intro)
        self.device_list.setAccessibleName(section_title(Section.DEVICES))
        empty_action = t("Settings", "Tìm máy mới")
        self.devices_empty.set_content(
            "shield_checkmark",
            t("Settings", "Chưa ghép đôi với máy nào"),
            t("Settings", "Ghép đôi để gửi file qua lại với máy khác trong mạng."),
            action=empty_action,
        )
        self.devices_empty.action_button.setAccessibleName(empty_action)
        self.rate_row.set_text(
            t("Settings", "Giới hạn tốc độ gửi"), t("Settings", "Áp dụng cho mọi lượt gửi từ máy này.")
        )
        self.rate_checkbox.setText(t("Settings", "Giới hạn"))
        self.rate_checkbox.setAccessibleName(t("Settings", "Giới hạn tốc độ gửi"))
        self.rate_spin.setSuffix(t("Settings", " MB/s"))
        self.rate_spin.setAccessibleName(t("Settings", "Tốc độ gửi tối đa (MB/s)"))
        retention_hint = t(
            "Settings",
            "Phần nhận dở không còn lượt nào chờ nối lại, để quá số ngày này, được tự xóa khỏi thư mục nhận.",
        )
        self.retention_row.set_text(t("Settings", "Dọn phần nhận dở sau"), retention_hint)
        self._update_retention_suffix()
        # Dấu thập phân của ô tốc độ theo ngôn ngữ giao diện (“2,5” / “2.5”), không theo hệ điều hành.
        self.rate_spin.setLocale(QLocale(i18n.current_language()))
        self.export_row.set_text(
            t("Settings", "Xuất log"),
            t(
                "Settings",
                "Gói các file log của Teleport thành một file zip để gửi kèm khi báo lỗi. Log không chứa "
                "nội dung file hay clipboard, nhưng có thể có đường dẫn thư mục (kèm tên người dùng của "
                "máy), địa chỉ IP và 8 ký tự đầu của mã thiết bị.",
            ),
        )
        self._update_export_text()
        self.version_row.set_text(
            t("Settings", "Phiên bản"),
            texts.fill(
                t("Settings", "Teleport {version} · giao thức {protocol}"),
                version=teleport.__version__,
                protocol=str(PROTOCOL_VERSION),
            ),
        )
        self.license_row.set_text(
            t("Settings", "Giấy phép"), t("Settings", "Phần mềm tự do theo GNU GPL phiên bản 3.")
        )
        self.notices_button.setText(t("Settings", "Thông báo bên thứ ba"))
        self.notices_button.setAccessibleName(t("Settings", "Thông báo bên thứ ba"))
        self._update_shortcuts_table()
        self._update_visibility_texts()
        self._update_autostart()
        self._update_receive_dir()
        for row in self._rows.values():
            row.retranslate()

    # ---- Bên trong: cập nhật chữ ---------------------------------------------------------------

    def _update_visibility_texts(self) -> None:
        self.name_row.set_text(QCoreApplication.translate("Settings", "Tên thiết bị"), self.hint_for_name())
        if self._name_error is not None:
            self.set_name_error(self._name_error)
        hidden = hidden_text()
        self.hidden_label.setText(hidden)
        self.hidden_label.setVisible(not self._visible)
        base = QCoreApplication.translate(
            "Settings",
            "Máy đã ghép đôi tự kết nối được khi ít nhất một trong hai máy đang hiện, "
            "hoặc khi hai máy đã từng kết nối và địa chỉ không đổi.",
        )
        self.visible_switch.setAccessibleDescription(base if self._visible else f"{base} {hidden}")

    def _update_autostart(self) -> None:
        state = self._autostart
        try:
            supported = autostart.supported()
        except Exception:
            supported = False
        shown = supported and state is not autostart.AutostartState.UNSUPPORTED
        self.autostart_row.setVisible(shown)
        extra = autostart_state_hint(state)
        self.autostart_state_label.setText(extra)
        self.autostart_state_label.setVisible(bool(extra))
        base = QCoreApplication.translate(
            "Settings", "Teleport chạy ở khay hệ thống khi bạn đăng nhập Windows, sẵn sàng nhận file."
        )
        self.autostart_switch.setAccessibleDescription(f"{base} {extra}" if extra else base)

    def _update_receive_dir(self) -> None:
        t = QCoreApplication.translate
        label = self.receive_dir_label
        tone = "muted"
        if self._pending is not None:
            text = texts.fill(t("Settings", "Đang đổi sang {path}…"), path=printable(str(self._pending)))
        elif self._receive_dir is not None:
            text = printable(str(self._receive_dir))
        elif self._unavailable is not None:
            text = texts.fill(
                t("Settings", "Không nhận file: không mở được {path}"), path=printable(str(self._unavailable))
            )
            tone = "warning"
        else:
            text = ""
        label.set_full_text(text)
        label.setToolTip(safe_tooltip(text) if text else "")
        label.setAccessibleName(t("Settings", "Thư mục nhận"))
        label.setAccessibleDescription(text)
        label.setVisible(bool(text))
        if label.property(theme.TONE_PROPERTY) != tone:
            label.setProperty(theme.TONE_PROPERTY, tone)
            _repolish(label)
        self.open_dir_button.setVisible(self._receive_dir is not None)
        self.open_dir_button.setAccessibleDescription(text)
        self.change_dir_button.setAccessibleDescription(text)

    def _update_shortcuts_table(self) -> None:
        t = QCoreApplication.translate
        label = t("Settings", "Phím tắt")
        hint = t("Settings", "Dùng Teleport không cần chuột. Danh sách chỉ để xem, không đổi được phím.")
        self.shortcuts_row.set_text(label, hint)
        table = self.shortcuts_table
        table.setAccessibleName(label)
        table.setAccessibleDescription(hint)
        table.set_rows(shortcuts.table_rows(), (t("Settings", "Thao tác"), t("Settings", "Phím")))

    def _update_export_text(self) -> None:
        t = QCoreApplication.translate
        text = t("Settings", "Đang xuất…") if self._export_running else t("Settings", "Xuất log…")
        self.export_button.setText(text)
        self.export_button.setAccessibleName(t("Settings", "Xuất log"))

    # ---- Bên trong: thiết bị -------------------------------------------------------------------

    def _sync_devices(self) -> None:
        if "_rows" not in self.__dict__:  # đang hủy
            return
        views = trusted_devices(self.model.devices())
        new_order = [v.device_id for v in views]
        focus = QApplication.focusWidget()
        focused_id = next(
            (i for i, row in self._rows.items() if focus is not None and row.isAncestorOf(focus)), None
        )
        removed = [i for i in self._order if i not in new_order]
        move_focus = focused_id is not None and focused_id in removed
        target_id: str | None = None  # hàng nhận tiêu điểm; None (khi `move_focus`) = nút màn rỗng
        if focused_id is not None and move_focus:
            old = self._order
            position = old.index(focused_id)
            after = [i for i in old[position + 1 :] if i in new_order]
            before = [i for i in old[:position] if i in new_order]
            target_id = after[0] if after else (before[-1] if before else None)
        for device_id in removed:
            row = self._rows.pop(device_id)
            self._device_layout.removeWidget(row)
            row.hide()
            row.deleteLater()
        for view in views:
            existing = self._rows.get(view.device_id)
            if existing is None:
                created = TrustedDeviceRow(view, self.device_list)
                created.ask_toggled.connect(self.ask_toggled)
                created.clipboard_toggled.connect(self.clipboard_toggled)
                created.unpair_requested.connect(self.unpair_requested)
                created.set_ask(self._ask_of(view.device_id))
                created.set_clipboard(self._clipboard_of(view.device_id))
                self._rows[view.device_id] = created
            elif existing.view != view:
                existing.set_view(view)
        for index, device_id in enumerate(new_order):
            row = self._rows[device_id]
            if self._device_layout.indexOf(row) != index:
                self._device_layout.removeWidget(row)
                self._device_layout.insertWidget(index, row)
            row.show()
        self._order = new_order
        empty = not new_order
        self.device_list.setVisible(not empty)
        self.devices_intro.setVisible(not empty)
        self.devices_empty.setVisible(empty)
        self._update_tab_order()
        if move_focus:
            widget: QWidget = (
                self._rows[target_id].ask_checkbox
                if target_id is not None
                else self.devices_empty.focus_target()
            )
            widget.setFocus(Qt.FocusReason.OtherFocusReason)

    # ---- Bên trong: thứ tự Tab -----------------------------------------------------------------

    def _update_tab_order(self) -> None:
        bar = self.info_bar
        chain: list[QWidget] = [
            self.header.back_button,
            self.nav,
            bar.title_label,
            bar.text_label,
            bar.action_button,
            bar.close_button,
            self.name_edit,
            self.open_dir_button,
            self.change_dir_button,
            self.autostart_switch,
            *self.appearance.focus_widgets(),
            self.visible_switch,
            self.clear_history_button,
        ]
        for row in self.device_rows():
            chain.extend(row.focus_widgets())
        chain += [
            self.devices_empty.action_button,
            self.rate_checkbox,
            self.rate_spin,
            self.retention_spin,
            self.export_button,
            self.shortcuts_table,
            self.notices_button,
        ]
        for first, second in itertools.pairwise(chain):
            QWidget.setTabOrder(first, second)

    # ---- Bên trong: slot -----------------------------------------------------------------------

    def _on_nav_row(self, row: int) -> None:
        if 0 <= row < self.sections.count():
            self.sections.setCurrentIndex(row)

    def _on_name_finished(self) -> None:
        text = self.name_edit.text().strip()
        if text == self._name:
            if self.name_edit.text() != text:
                self.name_edit.setText(text)
            self.set_name_error(None)
            return
        if not text:
            self.set_name_error(name_empty_text())
            return
        try:
            validate_device_name(text)
        except (MessageError, ValueError, TypeError):
            self.set_name_error(name_invalid_text())
            return
        self.set_name_error(None)
        self.name_edit.saved = text  # Esc lúc đang lưu không trả về tên cũ
        self._name = text
        self.name_edit.setText(text)
        self.name_submitted.emit(text)

    def _on_visible_clicked(self, checked: bool) -> None:
        self._visible = bool(checked)
        self._update_visibility_texts()
        self.visible_toggled.emit(self._visible)

    def _on_rate_checkbox(self, checked: bool) -> None:
        self.rate_spin.setEnabled(bool(checked))
        self._commit_rate()

    def _current_rate(self) -> int | None:
        if not self.rate_checkbox.isChecked():
            return None
        return rate_to_bytes(self.rate_spin.value())

    def _commit_rate(self) -> None:
        self._rate_commit.stop()
        if (
            self._rate is not None
            and self.rate_checkbox.isChecked()
            and self.rate_spin.value() == bytes_to_rate(self._rate)
        ):
            return  # ô vẫn hiện đúng giá trị đã lưu (có thể lệch lưới 0,1 MB/s): không đổi gì
        value = self._current_rate()
        if value == self._rate:
            return
        self._rate = value
        self.rate_limit_changed.emit(value)

    def _commit_retention(self) -> None:
        self._retention_commit.stop()
        days = self.retention_spin.value()
        shown = default_retention_days() if self._retention is None else self._retention
        if days == shown:
            return  # ô vẫn hiện đúng giá trị đã lưu (kể cả số bằng mặc định lưu tường minh)
        value = None if days == default_retention_days() else days
        if value == self._retention:
            return
        self._retention = value
        self.retention_changed.emit(value)

    def _on_open_dir(self) -> None:
        if self._receive_dir is not None:
            self.open_receive_dir_requested.emit(self._receive_dir)

    def _on_notices(self) -> None:
        if self._notices is not None:
            self.open_notices_requested.emit(self._notices)

    # ---- Bên trong: giao diện ------------------------------------------------------------------

    def _restyle(self) -> None:
        """Màu của cột mục và icon theo token (đổi lại khi đổi sáng/tối)."""
        t = theme.tokens_for(self)
        dark = theme.is_dark_palette(QApplication.palette())
        ring = theme.focus_ring_color(dark).name()
        self.nav.setStyleSheet(
            f"QListWidget#settingsNav {{ background: {t.sidebar.name()}; border: none;"
            f" border-right: 1px solid {t.border.name()}; padding: {theme.SPACING[1]}px; outline: 0; }}"
            f" QListWidget#settingsNav::item {{ color: {t.text.name()};"
            f" border-radius: {theme.RADIUS_CONTROL}px;"
            f" padding: 0px {theme.SPACING[1]}px; border: 2px solid transparent;"
            " border-left: 4px solid transparent; }"
            f" QListWidget#settingsNav::item:hover {{ background: {t.selected.name()}; }}"
            f" QListWidget#settingsNav::item:selected {{ background: {t.selected.name()};"
            f" color: {t.text.name()}; border-left-color: {t.accent_strong.name()}; }}"
            # Tiêu điểm bàn phím: viền màu chữ quanh mục đang chọn (vạch nhấn trái giữ nguyên).
            f" QListWidget#settingsNav::item:selected:focus {{ border-color: {ring};"
            f" border-left-color: {t.accent_strong.name()}; }}"
        )
        for index, section in enumerate(Section):
            item = self.nav.item(index)
            if item is not None:
                item.setIcon(icons.icon(SECTION_ICONS[section], _NAV_ICON, t.text, t.text_muted))

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        if not event.spontaneous():  # đổi trang, xuống khay: câu báo cũ không còn đúng
            self.info_bar.clear()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        elif event.type() in _PALETTE_EVENTS and "nav" in self.__dict__:
            self._restyle()


class _blocked(contextlib.AbstractContextManager[None]):
    """`with _blocked(w):` chặn signal của `w` trong khối (giá trị đặt từ ngoài không phát signal)."""

    def __init__(self, widget: QObject) -> None:
        self._widget = widget
        self._old = False

    def __enter__(self) -> None:
        self._old = self._widget.blockSignals(True)

    def __exit__(self, *exc: object) -> None:
        self._widget.blockSignals(self._old)


# ---- Controller --------------------------------------------------------------------------------


class _ExportRelay(QObject):
    """Mang kết quả xuất log từ thread xuất về thread Qt (signal `QueuedConnection`)."""

    finished = Signal(object)  # (generation, dest: Path, result: Path | BaseException)


def _deliver_export(
    relay: _ExportRelay, generation: int, dest: Path, future: concurrent.futures.Future[Path]
) -> None:
    """Thread xuất (hay Qt nếu đã xong): đọc kết quả rồi phát về thread Qt; app đang tắt thì bỏ."""
    try:
        result: Path | BaseException = future.result()
    except BaseException as e:  # CancelledError khi `shutdown(cancel_futures=True)`
        result = e
    with contextlib.suppress(RuntimeError):  # QObject đã bị xóa
        relay.finished.emit((generation, dest, result))


class SettingsController(QObject):
    """Nối `SettingsPage` với node, registry tự khởi động, hộp thoại và việc xuất log."""

    name_changed = Signal(str)
    visibility_changed = Signal(bool)
    history_cleared = Signal(object)  # None = toàn bộ (spec D2 mục 9.9)

    def __init__(
        self,
        page: SettingsPage,
        config_dir: Path,
        parent: QObject | None = None,
        *,
        message_parent: Callable[[], QWidget | None] = lambda: None,
        open_url: Callable[[QUrl], object] = QDesktopServices.openUrl,
        log_files: Callable[[], Sequence[Path]] = lambda: (),
    ) -> None:
        super().__init__(parent)
        self.page = page
        self._config_dir = Path(config_dir)
        self._message_parent = message_parent
        self._open_url = open_url
        self._log_files = log_files
        self._host: Any = None
        self._generation = 0
        self._seq: dict[str, int] = {}
        self._writes = 0  # số lời ghi đã gửi tới node (bỏ ảnh chụp xin trước một lời ghi)
        self._confirmed: dict[str, Any] = {}
        self._devices: dict[str, DeviceSettings] = {}
        self._saved_autostart: bool | None = None
        self._notice_action: Callable[[], None] | None = None
        self._confirm_box: QMessageBox | None = None
        self._dialog: QFileDialog | None = None
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._export_running = False
        self._relay = _ExportRelay(self)
        self._relay.finished.connect(self._on_export_finished, Qt.ConnectionType.QueuedConnection)

        page.name_submitted.connect(self._on_name)
        page.visible_toggled.connect(self._on_visible)
        page.language_selected.connect(self._on_language)
        page.theme_selected.connect(self._on_theme)
        page.accent_selected.connect(self._on_accent)
        page.autostart_toggled.connect(self._on_autostart)
        page.rate_limit_changed.connect(self._on_rate)
        page.retention_changed.connect(self._on_retention)
        page.ask_toggled.connect(self._on_ask)
        page.clipboard_toggled.connect(self._on_clipboard)
        page.clear_history_requested.connect(self.request_clear_history)
        page.export_logs_requested.connect(self.request_export)
        page.open_notices_requested.connect(self._on_open_notices)
        page.notice_action.connect(self._on_notice_action)
        model = page.model
        for signal in (model.modelReset, model.rowsInserted, model.dataChanged):
            signal.connect(self._on_model_changed)
        page.installEventFilter(self)

    # ---- Thuộc tính ----------------------------------------------------------------------------

    @property
    def host(self) -> Any:
        return self._host

    @property
    def confirm_box(self) -> QMessageBox | None:
        """Hộp xác nhận “Xóa toàn bộ lịch sử” đang mở."""
        return self._confirm_box

    @property
    def dialog(self) -> QFileDialog | None:
        """Hộp lưu file log đang mở."""
        return self._dialog

    @property
    def export_running(self) -> bool:
        return self._export_running

    # ---- Vòng đời ------------------------------------------------------------------------------

    def attach(self, host: Any) -> None:
        """Host mới (lần đầu, “Thử lại”): trang chờ ảnh chụp mới, đóng mọi hộp."""
        self.close_all()
        self._host = host
        self._seq.clear()
        self._confirmed.clear()
        self._devices = {}
        self._saved_autostart = None
        self.page.set_loaded(False)

    def on_started(self, host: Any) -> None:
        if host is not self._host or host is None:
            return
        self._read_snapshot()

    def refresh(self) -> None:
        """Đọc lại ảnh chụp (trang vừa hiện)."""
        if self._host is not None:
            self._read_snapshot()

    def close_all(self) -> None:
        """Đóng hộp xác nhận và hộp lưu file; kết quả xuất log đang chạy về sau bị bỏ."""
        self._generation += 1
        box, self._confirm_box = self._confirm_box, None
        if box is not None:
            box.close()
            box.deleteLater()
        dialog, self._dialog = self._dialog, None
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        if self._export_running:
            self._export_running = False
            self.page.set_export_running(False)

    def shutdown(self) -> None:
        """Thoát: bỏ việc xuất log chưa chạy, không chờ việc đang chạy."""
        self.close_all()
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    # ---- Ảnh chụp ------------------------------------------------------------------------------

    def _read_snapshot(self) -> None:
        host = self._host
        generation = self._generation
        writes = self._writes
        host.call(read_snapshot, functools.partial(self._on_snapshot, generation, host, writes))

    def _on_snapshot(self, generation: int, host: Any, writes: int, result: object) -> None:
        if generation != self._generation or host is not self._host:
            return
        if writes != self._writes and not isinstance(result, BaseException):
            # Người dùng đã gửi lời ghi sau khi xin ảnh chụp này: ảnh chụp cũ hơn lời ghi đó, đặt vào
            # trang sẽ đè giá trị vừa chọn. Đọc lại (chạy sau lời ghi trên loop của node).
            self._read_snapshot()
            return
        if isinstance(result, BaseException):
            if isinstance(result, (RuntimeError, asyncio.CancelledError)):
                log.debug("không đọc được cài đặt: node không chạy")
                return
            log.error("không đọc được cài đặt: %s", type(result).__name__)
            self._show_notice(InfoLevel.ERROR, snapshot_error_text, action=(_retry_text, self.refresh))
            return
        if not isinstance(result, SettingsSnapshot):
            return
        self._confirmed.update(
            name=result.name,
            visible=result.visible,
            language=result.language,
            rate=result.rate_limit,
            retention=result.temp_retention_days,
            theme=result.theme,
            accent=result.accent,
        )
        self._devices = dict(result.devices)
        self._saved_autostart = result.autostart
        self.page.set_values(result)
        self.page.set_loaded(True)
        self._sync_theme(theme.mode_from_setting(result.theme), result.accent)
        if self.page.info_bar.title == snapshot_error_text():  # đọc lại được: câu lỗi cũ không còn đúng
            self.page.clear_notice()
        self._reconcile_autostart()

    def _reconcile_autostart(self) -> None:
        """Registry thắng: khác `settings.autostart` thì chỉ ghi cài đặt, không bao giờ ghi registry."""
        state = self._read_autostart()
        self.page.set_autostart(state)
        saved = self._saved_autostart
        if state is None or state is autostart.AutostartState.UNSUPPORTED or saved is None:
            return
        on = state is autostart.AutostartState.ON
        if saved == on or self._host is None:
            return
        self._saved_autostart = on
        self._host.call(lambda node: node.set_ui_preferences(autostart=on), _warn("lưu cài đặt khởi động"))

    def _read_autostart(self) -> autostart.AutostartState | None:
        try:
            return autostart.state(self._config_dir)
        except autostart.AutostartError as e:
            log.warning("không đọc được cài đặt khởi động: %s", type(e).__name__)
            return None
        except Exception as e:
            log.error("đọc cài đặt khởi động lỗi: %s", type(e).__name__)
            return None

    def _on_model_changed(self, *_args: object) -> None:
        """Máy mới được ghép đôi khi trang đang mở: đọc cài đặt theo thiết bị của nó."""
        host = self._host
        if host is None or not self.page.loaded:
            return
        if all(device_id in self._devices for device_id in self.page.device_ids()):
            return
        generation = self._generation
        host.call(_read_device_settings, functools.partial(self._on_device_settings, generation, host))

    def _on_device_settings(self, generation: int, host: Any, result: object) -> None:
        if generation != self._generation or host is not self._host:
            return
        if isinstance(result, BaseException):
            log.debug("không đọc được cài đặt theo thiết bị: %s", type(result).__name__)
            return
        if isinstance(result, dict):
            self._devices = dict(result)
            self.page.set_device_settings(self._devices)

    # ---- Ý định của người dùng -----------------------------------------------------------------

    def _call(
        self,
        field: str,
        fn: Callable[[Node], object],
        revert: Callable[[Any], None],
        on_ok: Callable[[object], None] | None = None,
        *,
        value: object = None,
        on_message_error: Callable[[], None] | None = None,
        on_key_error: Callable[[], None] | None = None,
    ) -> None:
        host = self._host
        if host is None:
            revert(self._confirmed.get(field))
            return
        seq = self._seq.get(field, 0) + 1
        self._seq[field] = seq
        self._writes += 1
        generation = self._generation

        def done(result: object) -> None:
            if generation != self._generation or host is not self._host:
                return
            latest = self._seq.get(field) == seq
            if not isinstance(result, BaseException):
                self._confirmed[field] = value
                if on_ok is not None:
                    on_ok(result)
                return
            if isinstance(result, (RuntimeError, asyncio.CancelledError)):
                log.debug("không lưu được cài đặt %s: node không chạy", field)
                if latest:
                    revert(self._confirmed.get(field))
                return
            if isinstance(result, KeyError) and on_key_error is not None:
                on_key_error()
                return
            if isinstance(result, MessageError) and on_message_error is not None:
                on_message_error()
                return
            if latest:
                revert(self._confirmed.get(field))
            if isinstance(result, SettingsSaveError):
                log.warning("không lưu được cài đặt %s: %s", field, type(result).__name__)
                self._show_notice(InfoLevel.ERROR, settings_error_text())
            else:
                log.error("lưu cài đặt %s lỗi: %s", field, type(result).__name__)
                self._show_notice(InfoLevel.ERROR, other_error_text())

        host.call(fn, done)

    def _on_name(self, name: str) -> None:
        def ok(result: object) -> None:
            final = result if isinstance(result, str) else name
            self._confirmed["name"] = final
            self.page.set_name(final)
            self.name_changed.emit(final)

        self._call(
            "name",
            lambda node: node.set_name(name),
            lambda old: self.page.set_name(old if isinstance(old, str) else ""),
            ok,
            value=name,
            on_message_error=lambda: self.page.reject_name(
                str(self._confirmed.get("name") or ""), name_invalid_text()
            ),
        )

    def _on_visible(self, visible: bool) -> None:
        host = self._host

        def run(node: Node) -> None:
            node.set_visible(visible)
            host.apply_pairing_policy(node)  # cùng một khối đồng bộ với `set_visible` (docstring `ui.bridge`)

        self._call(
            "visible",
            run,
            lambda old: self.page.set_visible(True if old is None else bool(old)),
            lambda _r: self.visibility_changed.emit(visible),
            value=visible,
        )

    def _on_language(self, code: object) -> None:
        language = code if isinstance(code, str) else None

        def ok(_result: object) -> None:
            i18n.apply_preference(language)

        self._call(
            "language",
            lambda node: node.set_ui_preferences(language=language),
            lambda old: self.page.set_language(
                old if isinstance(old, str) else None, i18n.available_languages()
            ),
            ok,
            value=language,
        )

    def _on_theme(self, value: object) -> None:
        saved = theme.mode_from_setting(value if isinstance(value, str) else None).setting_value

        def ok(_result: object) -> None:
            _apply_theme(theme.mode_from_setting(saved), theme.current_accent())

        self._call(
            "theme",
            lambda node: node.set_ui_preferences(theme=saved),
            lambda old: self.page.set_theme(old if isinstance(old, str) else None),
            ok,
            value=saved,
        )

    def _on_accent(self, value: object) -> None:
        accent = value if isinstance(value, str) else None

        def ok(_result: object) -> None:
            _apply_theme(theme.current_mode(), accent)

        self._call(
            "accent",
            lambda node: node.set_ui_preferences(accent=accent),
            lambda old: self.page.set_accent(old if isinstance(old, str) else None),
            ok,
            value=accent,
        )

    @staticmethod
    def _sync_theme(mode: theme.Mode, accent: str | None) -> None:
        """Ảnh chụp khác lựa chọn đang áp (mỗi ảnh chụp; chỉ áp khi khác): áp theo ảnh chụp."""
        if mode is not theme.current_mode() or theme.accent_from_setting(accent) != theme.current_accent():
            _apply_theme(mode, accent)

    def _on_rate(self, value: object) -> None:
        rate = value if isinstance(value, int) else None
        self._call(
            "rate",
            lambda node: node.set_rate_limit(rate),
            lambda old: self.page.set_rate_limit(old if isinstance(old, int) else None),
            value=rate,
        )

    def _on_retention(self, value: object) -> None:
        days = value if isinstance(value, int) else None
        self._call(
            "retention",
            lambda node: node.set_temp_retention_days(days),
            lambda old: self.page.set_retention(old if isinstance(old, int) else None),
            value=days,
        )

    def _on_ask(self, device_id: str, ask: bool) -> None:
        field = f"ask:{device_id}"
        self._confirmed.setdefault(field, self._devices.get(device_id, DeviceSettings()).ask_before_receive)

        def revert(old: object) -> None:
            row = self.page.device_row(device_id)
            if row is not None:
                row.set_ask(True if old is None else bool(old))

        def ok(_result: object) -> None:
            current = self._devices.get(device_id, DeviceSettings())
            self._devices[device_id] = replace(current, ask_before_receive=ask)

        self._call(
            field,
            lambda node: node.set_ask_before_receive(device_id, ask),
            revert,
            ok,
            value=ask,
            on_key_error=self.refresh,
        )

    def _on_clipboard(self, device_id: str, enabled: bool) -> None:
        """“Đồng bộ clipboard” của một máy: như `_on_ask`, với `Node.set_clipboard`."""
        field = f"clipboard:{device_id}"
        self._confirmed.setdefault(field, self._devices.get(device_id, DeviceSettings()).clipboard)

        def revert(old: object) -> None:
            row = self.page.device_row(device_id)
            if row is not None:
                row.set_clipboard(False if old is None else bool(old))

        def ok(_result: object) -> None:
            current = self._devices.get(device_id, DeviceSettings())
            self._devices[device_id] = replace(current, clipboard=enabled)

        self._call(
            field,
            lambda node: node.set_clipboard(device_id, enabled),
            revert,
            ok,
            value=enabled,
            on_key_error=self.refresh,
        )

    def _on_autostart(self, enabled: bool) -> None:
        """Ghi registry trước (thread Qt); lỗi → trả công tắc, báo, không lưu cài đặt."""
        try:
            if enabled:
                autostart.enable(self._config_dir)
            else:
                autostart.disable(self._config_dir)
        except autostart.AutostartError as e:
            log.warning("không ghi được cài đặt khởi động: %s", type(e).__name__)
            self.page.set_autostart(self._read_autostart())  # lỗi có thể tới sau khi đã ghi một phần
            self._show_notice(InfoLevel.ERROR, autostart_write_error_text())
            return
        except Exception as e:
            log.error("ghi cài đặt khởi động lỗi: %s", type(e).__name__)
            self.page.set_autostart(self._read_autostart())  # lỗi có thể tới sau khi đã ghi một phần
            self._show_notice(InfoLevel.ERROR, other_error_text())
            return
        self._saved_autostart = enabled
        host = self._host
        if host is not None:
            host.call(lambda node: node.set_ui_preferences(autostart=enabled), _warn("lưu cài đặt khởi động"))
        self.page.set_autostart(self._read_autostart())

    # ---- Xóa toàn bộ lịch sử -------------------------------------------------------------------

    def request_clear_history(self) -> None:
        """Hộp xác nhận không chặn (`open()`); “Không” là nút mặc định và Esc."""
        box = self._confirm_box
        if box is not None:
            box.raise_()
            box.activateWindow()
            return
        box = QMessageBox(self._message_parent())
        box.setObjectName("clearHistoryBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setWindowTitle(clear_history_title())
        box.setAccessibleName(clear_history_title())
        box.setText(clear_history_question())
        accept = box.addButton(
            QCoreApplication.translate("Settings", "Xóa lịch sử"), QMessageBox.ButtonRole.DestructiveRole
        )
        decline = box.addButton(
            QCoreApplication.translate("Settings", "Không"), QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(decline)
        box.setEscapeButton(decline)
        generation = self._generation
        box.finished.connect(lambda _r: self._on_confirm_finished(box, accept, generation))
        self._confirm_box = box
        box.open()

    def _on_confirm_finished(self, box: QMessageBox, accept: object, generation: int) -> None:
        if self._confirm_box is box:
            self._confirm_box = None
        clicked = box.clickedButton()
        box.deleteLater()
        if clicked is not accept or generation != self._generation:
            return
        host = self._host
        if host is None:
            return

        def done(result: object) -> None:
            if generation != self._generation or host is not self._host:
                return
            if isinstance(result, BaseException):
                if isinstance(result, (RuntimeError, asyncio.CancelledError)):
                    log.debug("không xóa được lịch sử: node không chạy")
                    return
                log.error("xóa lịch sử lỗi: %s", type(result).__name__)
                self._show_notice(InfoLevel.ERROR, history_clear_failed_text())
                return
            self._show_notice(InfoLevel.SUCCESS, history_cleared_text())
            self.history_cleared.emit(None)

        host.call(lambda node: node.transfers.clear_history(), done)

    # ---- Xuất log ------------------------------------------------------------------------------

    def request_export(self) -> None:
        """Hộp lưu file (không chặn); chọn xong thì xuất ngoài thread Qt."""
        if self._export_running:
            return
        dialog = self._dialog
        if dialog is not None:
            dialog.raise_()
            dialog.activateWindow()
            return
        dialog = dialog_factory(self._message_parent())
        dialog.setObjectName("exportLogsDialog")
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        dialog.setWindowTitle(QCoreApplication.translate("Settings", "Lưu file log"))
        dialog.setNameFilter(QCoreApplication.translate("Settings", "File zip (*.zip)"))
        dialog.setDefaultSuffix("zip")
        dialog.setDirectory(default_export_dir())
        dialog.selectFile(default_export_name())
        generation = self._generation
        dialog.fileSelected.connect(lambda path: self._on_export_path(generation, path))
        dialog.finished.connect(lambda _r, d=dialog: self._dialog_finished(d))
        self._dialog = dialog
        dialog.open()

    def _dialog_finished(self, dialog: QFileDialog) -> None:
        if self._dialog is dialog:
            self._dialog = None
        dialog.deleteLater()

    def _on_export_path(self, generation: int, path: str) -> None:
        if generation != self._generation or not path or self._export_running:
            return
        dest = Path(path)
        files = [Path(p) for p in self._log_files()]
        if self._executor is None:
            self._executor = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix=EXPORT_THREAD)
        fn = export_fn  # seam: đọc lúc gọi
        try:
            future = self._executor.submit(fn, files, dest)
        except RuntimeError as e:  # executor đã đóng (đang thoát)
            log.debug("không xuất được log: %s", type(e).__name__)
            return
        self._export_running = True
        self.page.set_export_running(True)
        future.add_done_callback(functools.partial(_deliver_export, self._relay, self._generation, dest))

    def _on_export_finished(self, payload: object) -> None:
        if not isinstance(payload, tuple) or len(payload) != 3:
            return
        generation, dest, result = payload
        if generation != self._generation:
            return
        self._export_running = False
        self.page.set_export_running(False)
        if isinstance(result, Path):
            folder = result.parent
            self._show_notice(
                InfoLevel.SUCCESS,
                export_saved_text(result),
                action=(
                    QCoreApplication.translate("Settings", "Mở thư mục"),
                    lambda: self._open_folder(folder),
                ),
            )
        elif isinstance(result, concurrent.futures.CancelledError):
            log.debug("xuất log bị hủy")
        elif isinstance(result, OSError):
            log.warning("không lưu được file log: %s", type(result).__name__)
            self._show_notice(InfoLevel.ERROR, export_write_error_text(dest))
        else:
            log.error("xuất log lỗi: %s", type(result).__name__)
            self._show_notice(InfoLevel.ERROR, export_other_error_text())

    def _open_folder(self, folder: Path) -> None:
        if self._open_url(QUrl.fromLocalFile(str(folder))) is False:
            log.warning("không mở được thư mục chứa file log")

    def _on_open_notices(self, path: object) -> None:
        if isinstance(path, Path) and self._open_url(QUrl.fromLocalFile(str(path))) is False:
            log.warning("không mở được file thông báo bên thứ ba")

    # ---- Thông báo -----------------------------------------------------------------------------

    def notice_text(self) -> str | None:
        """Câu đang hiện ở thanh thông báo của trang, hay None khi thanh ẩn."""
        bar = self.page.info_bar
        return bar.title if not bar.isHidden() else None

    def show_notice(
        self,
        level: InfoLevel,
        text: texts.Text,
        *,
        action: tuple[texts.Text, Callable[[], None]] | None = None,
    ) -> None:
        """Hiện câu ở thanh thông báo của trang; `action` = (chữ nút, hàm) chỉ gắn với câu này
        (thông báo kế tiếp thay hay xóa nó). `ui.app` dùng cho lỗi đổi thư mục nhận."""
        self._show_notice(level, text, action=action)

    def _show_notice(
        self,
        level: InfoLevel,
        text: texts.Text,
        *,
        action: tuple[texts.Text, Callable[[], None]] | None = None,
    ) -> None:
        self._notice_action = action[1] if action is not None else None
        self.page.show_notice(level, text, action=action[0] if action is not None else None)

    def _on_notice_action(self) -> None:
        action, self._notice_action = self._notice_action, None
        self.page.clear_notice()
        if action is not None:
            action()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            watched is self.page
            and event.type() == QEvent.Type.Show
            and not event.spontaneous()
            and isValid(self)
        ):
            self.refresh()
        return False


def _apply_theme(mode: theme.Mode, accent: str | None) -> None:
    """Thread Qt: áp chế độ màu và màu nhấn cho ứng dụng (`theme.set_preference`)."""
    app = QApplication.instance()
    if isinstance(app, QApplication):
        theme.set_preference(app, mode, accent)


def _retry_text() -> str:
    return texts.retry()


def _warn(what: str) -> Callable[[object], None]:
    def done(result: object) -> None:
        if isinstance(result, BaseException) and not isinstance(
            result, (RuntimeError, asyncio.CancelledError)
        ):
            log.warning("không %s được: %s", what, type(result).__name__)

    return done
