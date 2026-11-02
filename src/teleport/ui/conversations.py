"""Danh sách cuộc trò chuyện ở cột trái cửa sổ chính (spec B2; mvp F2, F4, F5, N12).

Mỗi máy **đã ghép đôi** là một hàng: avatar kèm chấm trạng thái, tên máy (font điểm nhấn), dòng phụ
“trạng thái · hoạt động gần nhất”, giờ ở bên phải. Cuối danh sách là nút “＋ Ghép đôi máy mới” (mở
trang “Tìm máy mới”). Ghép đôi máy mới và nhập IP chỉ ở trang đó (`ui.discover`).

**Model** (`ConversationModel`, một `QSortFilterProxyModel` trên `radar.DeviceListModel` dùng chung
với trang “Tìm máy mới”; sắp động): chỉ giữ hàng có `DeviceView.paired`. Thứ tự theo
`conversation_sort_key`: máy đang truyền → máy trực tuyến (đang kết nối hay mDNS thấy) → còn lại;
trong nhóm, hoạt động gần nhất trước; rồi NFC(tên).casefold(), rồi `device_id`. Hoạt động
(`ui.activity.DeviceActivity`) do `ui.transfers` đẩy vào bằng `set_activity`: khóa sắp đổi →
`invalidate()` (lựa chọn, hàng hiện hành và chỉ mục bền giữ nguyên, Qt phát `layoutChanged`); chỉ chữ
đổi (ví dụ phần trăm nguyên) → `dataChanged` đúng một hàng; không đổi gì → không phát. Nhờ vậy mỗi
nhịp tiến độ chỉ vẽ lại một hàng khi phần trăm nguyên đổi. `clear_activity()` khi host mới.

**Role**: `DEVICE_ROLE`, `DEVICE_ID_ROLE`, `FAILURE_ROLE` (từ nguồn; lỗi là
`DeviceListModel.shown_failure`), `PRESENCE_ROLE` (`widgets.Presence`), `STATUS_ROLE` (chữ dòng
phụ), `TONE_ROLE` (`StatusTone`), `TIME_ROLE` (chữ giờ). `DisplayRole` = `texts.peer_label(tên)` (gõ chữ
nhảy theo tên); `AccessibleTextRole` = “{tên}. {dòng phụ}” (+ “. {giờ}”), tới UIA thành Name;
`AccessibleDescriptionRole` = hệ điều hành bằng chữ, câu lỗi kết nối đầy đủ (`radar.connect_failed_text`),
số lượt khi nhiều hơn một, tới UIA thành Description; `ToolTipRole` = các dòng đó qua
`widgets.safe_tooltip`. Dòng phụ là `status_line` (hàm thuần, bảng ở spec B2 mục 2.4): chữ trạng thái
luôn đứng đầu; không truyền gì thì nối “ · ” + hoạt động gần nhất (`activity_text`) hay hệ điều hành.
Giờ là `time_text` (giờ địa phương: “10:42”, “Hôm qua”, “28/10”, “28/10/2025”), tính lúc vẽ qua seam
module `_wall_now` (đọc lúc gọi). Không có hẹn giờ qua nửa đêm: chữ giờ đổi ở lần vẽ lại kế tiếp.

**Delegate** (`ConversationDelegate`, tự vẽ, màu lấy bằng `theme.tokens_for(option.widget)` lúc vẽ)
- Cao `row_height()` = max(`MIN_ROW_HEIGHT`, lineSpacing(tên) + lineSpacing(CAPTION) + 16) + khe 2 px
  giữa hai hàng (nền chừa 1 px trên, 1 px dưới), tính lại khi font của danh sách đổi.
- Lề trong 8; avatar 40 (`widgets.paint_avatar`, luôn `AvatarKind.DESKTOP`: giao thức không có loại
  máy, hệ điều hành ghi bằng chữ; ngoại tuyến thì chỉ icon mờ, chữ không mờ; vành chấm theo màu nền
  hàng); khoảng 12; tên (font của SECTION cỡ bằng thân, DemiBold, `text`, cắt “…”); giờ (CAPTION,
  `text_muted`, căn phải ngang dòng tên); dòng phụ (CAPTION, cắt “…”): NORMAL `text_muted`, BUSY
  `accent_text`, WARNING/DANGER chữ `text` kèm icon `warning` tô `warning`/`danger` ở đầu dòng.
- Nền: thường trong suốt (thấy `sidebar` của cột); rê chuột trộn 50% `sidebar`/`selected`; hàng được
  chọn `selected`; bo `RADIUS_CARD`. Tiêu điểm (danh sách có tiêu điểm, hàng hiện hành): viền 2 px
  `theme.focus_ring_color`. Đang kéo file qua hàng: viền nét đứt 2 px, màu `accent_strong` khi hàng
  không được chọn và `text` khi hàng đang được chọn (không trùng nền chọn), dòng phụ thay bằng
  “Thả để gửi n file” (`accent_text`); n = số URL file cục bộ, không `stat` file nào (không có tổng
  cỡ trong câu).
- Dạng thu gọn (`compact`, cột trái chỉ còn avatar): ô bo 48 px quanh avatar mang nền, tiêu điểm, viền
  thả; máy đang truyền thêm vòng 2 px `accent_strong` quanh avatar, có lỗi kết nối thì icon `warning`
  16 px ở góc trên phải (trạng thái không chỉ nói bằng màu, WCAG 1.4.1). Chữ ở tooltip và tên trợ năng.
- Bẫy: icon chỉ có cỡ trong `icons.SIZES` (`warning` chỉ có 20): icon 16 px là pixmap 20 vẽ thu vào ô
  16×16, gọi cỡ 16 sẽ `KeyError`.

**View** (`_ConversationView`, `QListView` objectName `conversationList`): bấm trái một lần chỉ chọn;
bấm đúp phát `row_double_clicked` một lần mỗi sự kiện dblclick; Enter/Return phát `row_entered` (bỏ
phím tự lặp); cả hai thành `ConversationList.open_requested`; phím Menu, Shift+F10, chuột phải phát
`menu_requested`. Tab / Shift+Tab đi qua **từng** hàng rồi mới ra khỏi danh sách (vào bằng Tab tới
hàng đầu, Shift+Tab tới hàng cuối), chỉ dời hàng hiện hành, không đổi máy được chọn (đổi bằng chuột
hay phím mũi tên). Không thanh cuộn riêng: cao cố định đúng `rowCount × row_height() + 2×frameWidth`,
cột trái (`sidebar_scroll`) cuộn cả danh sách lẫn nút “＋”. Kéo thả tự xử lý (model không hỗ trợ
mime): chỉ nhận URL file cục bộ (`send.local_paths`, không chạm đĩa), tô hàng dưới con trỏ mà không
đổi hàng đang chọn; hàng không gửi tới được (`radar.can_receive_files` sai; phòng hờ, vì mọi hàng
đã ghép đôi) thì từ chối thả.
`preview_drop(device_id, n)` đi cùng đường với `dragMoveEvent` (ảnh chụp, test).

**`ConversationList`** (objectName `conversations`): signal `send_files_requested(id, list[Path])`
(thả), `pick_files_requested(id)` (menu “Gửi file…”), `drop_hint_requested(câu)` (thả vào chỗ không
có máy: `radar.drop_hint_text()`), `unpair_requested(id)`, `add_device_requested()`,
`current_changed(id | None)`, `open_requested(id)` (Enter, bấm đúp: chọn máy đó rồi mở cuộc trò
chuyện, `ui.chat` đặt tiêu điểm vào nút “Gửi file”). `device_id_at(row)` và `neighbor_id(step)` (so với
máy được chọn, kẹp hai đầu, không vòng; chưa chọn: `step` > 0 → hàng đầu, < 0 → hàng cuối) cho phím
tắt của cửa sổ (`ui.main_window`); tooltip của “＋” ghi kèm phím Tìm máy mới (`ui.shortcuts`).
**Máy hiện hành = máy được chọn** (`current_device`): giữ qua `modelReset` (nhớ id rồi chọn lại) và qua
lúc sắp lại. **Luôn có một cuộc trò chuyện được chọn khi danh sách có hàng** (spec B3 mục 6): sau
`rowsInserted`, `modelReset`, `layoutChanged` và khi hàng đang chọn bị bỏ, chưa máy nào được chọn thì
chọn hàng hiện hành nếu có, không thì hàng 0 (phát `current_changed`). Tab qua hàng vẫn không đổi máy
được chọn. Không có máy đã ghép đôi thì ẩn danh sách, nút “＋” vẫn hiện. Menu ngữ cảnh mở bằng
`popup()` (không `exec()`), tên trợ năng “Thao tác với {tên}”.

Bẫy dời từ radar cũ: nối `rowsAboutToBeRemoved` **trước** `setModel` (phải thấy lựa chọn trước khi view
dời nó sang hàng kế); `setTabKeyNavigation(False)` (Tab do `focusNextPrevChild` xử lý); không thanh
cuộn ngang; `refresh_drop_target` nối `layoutChanged`, `rowsInserted`, `rowsRemoved`, `modelReset`
**của proxy** (proxy sắp lại bằng `layoutChanged`, không `rowsMoved`), để viền thả luôn là hàng dưới
con trỏ, đúng máy nhận khi thả.

**Chữ của máy khác**: tên qua `texts.peer_label`, tên file qua `texts.file_label`, vẽ bằng `drawText`
(chữ thuần); tooltip chỉ qua `safe_tooltip`. Chữ đặt sẵn ở ngữ cảnh `"Conversations"`, gọi lúc dùng,
dựng lại khi `LanguageChange`.
"""

from __future__ import annotations

import contextlib
import datetime
import math
import time
import unicodedata
from enum import StrEnum
from typing import Any

from PySide6.QtCore import (
    QAbstractItemModel,
    QCoreApplication,
    QDate,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QSortFilterProxyModel,
    Qt,
    QTime,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QContextMenuEvent,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QFont,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFrame,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QVBoxLayout,
    QWidget,
)

from teleport.app.devices import DeviceView
from teleport.app.transfers import Direction, TransferResult, TransferStatus
from teleport.core.links import ConnectResult
from teleport.ui import icons, send, shortcuts, texts, theme
from teleport.ui.activity import EMPTY_ACTIVITY, ActiveTransfer, DeviceActivity, FinishedTransfer
from teleport.ui.radar import (
    DEVICE_ID_ROLE,
    DEVICE_ROLE,
    FAILURE_ROLE,
    DeviceListModel,
    can_receive_files,
    connect_failed_text,
    drop_hint_text,
)
from teleport.ui.widgets import ICON_BUTTON_SIZE, AvatarKind, IconButton, Presence, paint_avatar, safe_tooltip

__all__ = [
    "DEVICE_ID_ROLE",
    "DEVICE_ROLE",
    "FAILURE_ROLE",
    "MIN_ROW_HEIGHT",
    "PRESENCE_ROLE",
    "STATUS_ROLE",
    "TIME_ROLE",
    "TONE_ROLE",
    "ConversationDelegate",
    "ConversationList",
    "ConversationModel",
    "StatusTone",
    "activity_text",
    "conversation_sort_key",
    "drop_text",
    "status_line",
    "time_text",
]

# Seam: giờ tường (giây epoch) lúc vẽ chữ giờ; đọc lúc gọi, test vá được.
_wall_now = time.time

PRESENCE_ROLE = Qt.ItemDataRole.UserRole + 20  # widgets.Presence của chấm avatar
STATUS_ROLE = Qt.ItemDataRole.UserRole + 21  # chữ dòng phụ
TONE_ROLE = Qt.ItemDataRole.UserRole + 22  # StatusTone của dòng phụ
TIME_ROLE = Qt.ItemDataRole.UserRole + 23  # chữ giờ (rỗng nếu chưa có hoạt động)

MIN_ROW_HEIGHT = 56  # px, nền của một hàng (chưa tính khe giữa hai hàng)
ROW_GAP = 2  # px, khe giữa hai hàng, nằm trong sizeHint (nền chừa 1 px trên, 1 px dưới)
AVATAR_SIZE = 40  # px
COMPACT_CELL = 48  # px, ô bo quanh avatar ở dạng thu gọn
_PADDING = 8  # px, lề trong của hàng
_AVATAR_GAP = 12  # px, avatar → khối chữ
_TIME_GAP = 8  # px, tên → giờ
_LINE_GAP = 2  # px, dòng tên → dòng phụ
_WARNING_ICON = 16  # px, icon cảnh báo đầu dòng phụ / góc ô thu gọn
_WARNING_SOURCE = 20  # px, cỡ có trong `icons.SIZES` (vẽ thu vào ô 16×16)
_PERCENT_CAP = 99  # chưa xong thì không hiện 100%
_LIST_SPACING = 4  # px, danh sách → nút “＋”

_Index = QModelIndex | QPersistentModelIndex
_ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
_REJECTED = frozenset(r for r in TransferResult if r.value.startswith("rejected_"))
_CANCELLED = frozenset(
    {
        TransferResult.CANCELLED_USER,
        TransferResult.CANCELLED_OTHER,
        TransferResult.UNKNOWN_TRANSFER,
        TransferResult.UNPAIRED,
    }
)
_BLOCKING = frozenset(
    {ConnectResult.REJECTED, ConnectResult.IDENTITY_MISMATCH, ConnectResult.VERSION_MISMATCH}
)


class StatusTone(StrEnum):
    """Mức của dòng phụ: màu chữ (và icon cảnh báo) do delegate chọn."""

    NORMAL = "normal"
    BUSY = "busy"
    WARNING = "warning"
    DANGER = "danger"


# ---- Câu chữ (hàm thuần) ---------------------------------------------------------------------


def _files_text(file_count: int, first_name: str | None) -> str:
    """`{what}` của `activity_text`: tên file khi đúng một file và biết tên, không thì “n file”."""
    if file_count == 1 and first_name is not None:
        return texts.file_label(first_name)
    return QCoreApplication.translate("Conversations", "%n file", None, max(0, file_count))


def activity_text(last: FinishedTransfer) -> str:
    """Hoạt động gần nhất (lượt đã kết thúc), bảng ở spec B2 mục 2.4."""
    t = QCoreApplication.translate
    what = _files_text(last.file_count, last.first_name)
    send_side = last.direction is Direction.SEND
    result = last.result
    if result is TransferResult.DONE:
        template = t("Conversations", "Đã gửi {what}") if send_side else t("Conversations", "Đã nhận {what}")
    elif result in _REJECTED:
        if send_side:
            template = t("Conversations", "Bị từ chối · {what}")
        else:
            template = t("Conversations", "Đã từ chối · {what}")
    elif result in _CANCELLED:
        template = t("Conversations", "Đã hủy · {what}")
    elif send_side:
        template = t("Conversations", "Lỗi khi gửi · {what}")
    else:
        template = t("Conversations", "Lỗi khi nhận · {what}")
    return texts.fill(template, what=what)


def _percent(shown: int, total: int) -> str | None:
    """“62%”, chặn ở 99 tới khi xong; `total` = 0 → None (không hiện phần trăm)."""
    if total <= 0:
        return None
    value = min(_PERCENT_CAP, max(0, shown) * 100 // total)
    return f"{value}%"


def _active_text(view_active: ActiveTransfer) -> str:
    """Chữ của một lượt đang chạy (`activity.ActiveTransfer`)."""
    t = QCoreApplication.translate
    status = view_active.status
    sending = view_active.key.direction is Direction.SEND
    percent = _percent(view_active.shown_bytes, view_active.total_bytes)
    if status is TransferStatus.TRANSFERRING:
        if percent is None:
            return t("Conversations", "Đang gửi") if sending else t("Conversations", "Đang nhận")
        template = (
            t("Conversations", "Đang gửi · {percent}")
            if sending
            else t("Conversations", "Đang nhận · {percent}")
        )
        return texts.fill(template, percent=percent)
    if status is TransferStatus.VERIFYING:
        return t("Conversations", "Đang kiểm tra")
    if status is TransferStatus.RECONNECTING:
        if percent is None:
            return t("Conversations", "Đang nối lại")
        return texts.fill(t("Conversations", "Đang nối lại · {percent}"), percent=percent)
    if status is TransferStatus.WAITING:
        return (
            t("Conversations", "Đang chờ trả lời") if sending else t("Conversations", "Đang chờ bạn trả lời")
        )
    return t("Conversations", "Đang chờ")


def failure_text(failure: ConnectResult) -> str:
    """Chữ ngắn cho lần kết nối thất bại (dùng chung danh sách hội thoại và luồng chat)."""
    t = QCoreApplication.translate
    if failure is ConnectResult.REJECTED:
        return t("Conversations", "Bị từ chối kết nối")
    if failure is ConnectResult.IDENTITY_MISMATCH:
        return t("Conversations", "Danh tính đã đổi")
    if failure is ConnectResult.VERSION_MISMATCH:
        return t("Conversations", "Khác phiên bản")
    return t("Conversations", "Không kết nối được")


def is_online(view: DeviceView) -> bool:
    """Máy đang trực tuyến: có kết nối điều khiển hay mDNS đang thấy (dùng chung với menu khay)."""
    return view.connected or view.online


def status_line(
    view: DeviceView, activity: DeviceActivity, failure: ConnectResult | None
) -> tuple[Presence, StatusTone, str]:
    """(chấm, mức, chữ) của dòng phụ, bảng ở spec B2 mục 2.4. Chữ trạng thái luôn đứng đầu."""
    t = QCoreApplication.translate
    if activity.busy:
        if len(activity.active) == 1:
            text = _active_text(activity.active[0])
        else:
            text = t("Conversations", "Đang truyền %n lượt", None, len(activity.active))
        return Presence.BUSY, StatusTone.BUSY, text
    if failure is not None and failure is not ConnectResult.OK:
        presence = Presence.ONLINE if is_online(view) else Presence.OFFLINE
        tone = StatusTone.DANGER if failure in _BLOCKING else StatusTone.WARNING
        head = failure_text(failure)
    elif is_online(view):
        presence, tone, head = Presence.ONLINE, StatusTone.NORMAL, t("Conversations", "Trực tuyến")
    else:
        presence, tone, head = Presence.OFFLINE, StatusTone.NORMAL, t("Conversations", "Ngoại tuyến")
    if activity.last is not None:
        tail: str | None = activity_text(activity.last)
    else:
        tail = texts.os_label(view.os)
    return presence, tone, f"{head} · {tail}" if tail else head


def time_text(at: float | None, now: float) -> str:
    """Giờ của hoạt động gần nhất (giờ địa phương): cùng ngày “10:42”, hôm trước “Hôm qua”, cùng năm
    “28/10”, khác năm “28/10/2025”; ngày sau hôm nay cũng theo hai dạng ngày. None hay giờ không đổi
    được → chuỗi rỗng."""
    if at is None:
        return ""
    t = QCoreApplication.translate
    try:
        moment = datetime.datetime.fromtimestamp(at)
        today = datetime.datetime.fromtimestamp(now).date()
        day = moment.date()
        if day == today:
            return QTime(moment.hour, moment.minute).toString(t("Conversations", "HH:mm"))
        if day < today and day == today - datetime.timedelta(days=1):
            return t("Conversations", "Hôm qua")
    except (OverflowError, OSError, ValueError):
        return ""
    date = QDate(day.year, day.month, day.day)
    if day.year == today.year:
        return date.toString(t("Conversations", "dd/MM"))
    return date.toString(t("Conversations", "dd/MM/yyyy"))


def drop_text(count: int) -> str:
    """Dòng phụ của hàng đang có file kéo qua."""
    return QCoreApplication.translate("Conversations", "Thả để gửi %n file", None, max(0, count))


def conversation_sort_key(view: DeviceView, activity: DeviceActivity) -> tuple[int, float, str, str]:
    """Đang truyền → trực tuyến → còn lại; trong nhóm hoạt động gần nhất trước; rồi tên, mã máy."""
    group = 0 if activity.busy else (1 if is_online(view) else 2)
    at = activity.at
    return (
        group,
        -(at if at is not None else -math.inf),
        unicodedata.normalize("NFC", view.name or "").casefold(),
        view.device_id,
    )


# ---- Model ---------------------------------------------------------------------------------------


class ConversationModel(QSortFilterProxyModel):
    """Các máy đã ghép đôi, sắp theo `conversation_sort_key` (xem docstring module)."""

    def __init__(
        self, source: DeviceListModel | QObject | None = None, parent: QObject | None = None
    ) -> None:
        if isinstance(source, DeviceListModel):
            super().__init__(parent)
        else:
            super().__init__(source if parent is None else parent)
        self._activity: dict[str, DeviceActivity] = {}
        self.setDynamicSortFilter(True)
        if isinstance(source, DeviceListModel):
            self.setSourceModel(source)

    def setSourceModel(self, model: QAbstractItemModel) -> None:
        super().setSourceModel(model)
        self.sort(0, Qt.SortOrder.AscendingOrder)

    # -- API ------------------------------------------------------------------------------------

    def activity(self, device_id: str) -> DeviceActivity:
        return self._activity.get(device_id, EMPTY_ACTIVITY)

    def set_activity(self, device_id: str, activity: DeviceActivity) -> None:
        """Đặt hoạt động của một máy: khóa sắp đổi → `invalidate()`; chỉ chữ đổi → `dataChanged`."""
        old = self.activity(device_id)
        if old == activity:
            return
        if activity == EMPTY_ACTIVITY:
            self._activity.pop(device_id, None)
        else:
            self._activity[device_id] = activity
        row = self.row_of(device_id)
        if row < 0:
            return
        index = self.index(row, 0)
        view = index.data(DEVICE_ROLE)
        if not isinstance(view, DeviceView):
            return
        if conversation_sort_key(view, old) != conversation_sort_key(view, activity):
            self.invalidate()
            return
        failure = self._failure(index)
        if self._signature(view, old, failure) != self._signature(view, activity, failure):
            self.dataChanged.emit(index, index)

    def clear_activity(self) -> None:
        """Quên mọi hoạt động (host mới)."""
        self._activity.clear()
        self.invalidate()

    def device(self, device_id: str) -> DeviceView | None:
        """View của máy nếu đang có trong danh sách (đã ghép đôi), không thì None."""
        row = self.row_of(device_id)
        if row < 0:
            return None
        view = self.index(row, 0).data(DEVICE_ROLE)
        return view if isinstance(view, DeviceView) else None

    def row_of(self, device_id: str) -> int:
        """Hàng (của proxy) của máy; -1 nếu không có."""
        for row in range(self.rowCount()):
            if self.index(row, 0).data(DEVICE_ID_ROLE) == device_id:
                return row
        return -1

    def devices(self) -> tuple[DeviceView, ...]:
        """Các máy theo thứ tự hiển thị."""
        views = (self.index(row, 0).data(DEVICE_ROLE) for row in range(self.rowCount()))
        return tuple(view for view in views if isinstance(view, DeviceView))

    def refresh(self) -> None:
        """Vẽ lại mọi hàng (đổi ngôn ngữ)."""
        rows = self.rowCount()
        if rows:
            self.dataChanged.emit(self.index(0, 0), self.index(rows - 1, 0))

    # -- Qt -------------------------------------------------------------------------------------

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        view = model.index(source_row, 0, source_parent).data(DEVICE_ROLE)
        return isinstance(view, DeviceView) and view.paired

    def lessThan(self, source_left: _Index, source_right: _Index) -> bool:
        left, right = source_left.data(DEVICE_ROLE), source_right.data(DEVICE_ROLE)
        if not isinstance(left, DeviceView) or not isinstance(right, DeviceView):
            return False
        return conversation_sort_key(left, self.activity(left.device_id)) < conversation_sort_key(
            right, self.activity(right.device_id)
        )

    def data(self, index: _Index, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid():
            return None
        if role == FAILURE_ROLE:
            return self._failure(index)
        if role in (DEVICE_ROLE, DEVICE_ID_ROLE):
            return super().data(index, role)
        view = super().data(index, DEVICE_ROLE)
        if not isinstance(view, DeviceView):
            return None
        name = texts.peer_label(view.name, view.device_id)
        if role == Qt.ItemDataRole.DisplayRole:
            return name
        activity = self.activity(view.device_id)
        if role == TIME_ROLE:
            return time_text(activity.at, _wall_now())
        failure = self._failure(index)
        presence, tone, status = status_line(view, activity, failure)
        if role == PRESENCE_ROLE:
            return presence
        if role == TONE_ROLE:
            return tone
        if role == STATUS_ROLE:
            return status
        if role == Qt.ItemDataRole.AccessibleTextRole:
            when = time_text(activity.at, _wall_now())
            return ". ".join(part for part in (name, status, when) if part)
        if role == Qt.ItemDataRole.AccessibleDescriptionRole:
            return "\n".join(self._details(view, activity, failure))
        if role == Qt.ItemDataRole.ToolTipRole:
            when = time_text(activity.at, _wall_now())
            lines = [name, status, *([when] if when else []), *self._details(view, activity, failure)]
            return safe_tooltip("\n".join(lines))
        return None

    def flags(self, index: _Index) -> Qt.ItemFlag:
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # -- Bên trong ------------------------------------------------------------------------------

    def _failure(self, index: _Index) -> ConnectResult | None:
        """Lỗi kết nối đang hiện của hàng (`DeviceListModel.shown_failure`).

        Đọc thẳng từ model nguồn: đi qua `QVariant` của proxy, `StrEnum` thành `str` thường."""
        source = self.sourceModel()
        view = super().data(index, DEVICE_ROLE)
        if isinstance(source, DeviceListModel) and isinstance(view, DeviceView):
            return source.shown_failure(view)
        value = super().data(index, FAILURE_ROLE)
        try:
            return None if value is None else ConnectResult(value)
        except ValueError:
            return None

    @staticmethod
    def _signature(
        view: DeviceView, activity: DeviceActivity, failure: ConnectResult | None
    ) -> tuple[Any, ...]:
        """Những gì hàng hiện ra từ hoạt động (đổi thì vẽ lại hàng)."""
        return (status_line(view, activity, failure), activity.at, len(activity.active))

    @staticmethod
    def _details(view: DeviceView, activity: DeviceActivity, failure: ConnectResult | None) -> list[str]:
        """Các dòng của mô tả trợ năng: hệ điều hành, câu lỗi kết nối đầy đủ, số lượt (khi > 1)."""
        lines: list[str] = []
        os_label = texts.os_label(view.os)
        if os_label:
            lines.append(os_label)
        if failure is not None and failure is not ConnectResult.OK:
            lines.append(connect_failed_text(view, failure))
        if len(activity.active) > 1:
            lines.append(
                QCoreApplication.translate("Conversations", "Đang truyền %n lượt", None, len(activity.active))
            )
        return lines


# ---- Delegate ------------------------------------------------------------------------------------


def _role_presence(index: _Index) -> Presence:
    # Qua `QVariant`, `StrEnum` có thể về thành `str` thường: dựng lại enum.
    try:
        return Presence(index.data(PRESENCE_ROLE))
    except ValueError:
        return Presence.NONE


def _role_tone(index: _Index) -> StatusTone:
    try:
        return StatusTone(index.data(TONE_ROLE))
    except ValueError:
        return StatusTone.NORMAL


def _mix(a: QColor, b: QColor) -> QColor:
    return QColor((a.red() + b.red()) // 2, (a.green() + b.green()) // 2, (a.blue() + b.blue()) // 2)


class ConversationDelegate(QStyledItemDelegate):
    """Vẽ một hàng của danh sách cuộc trò chuyện (xem docstring module)."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.compact = False
        self._name_font = QFont()
        self._caption_font = QFont()
        self._row_height = MIN_ROW_HEIGHT + ROW_GAP
        self.set_base_font(QFont())

    def set_base_font(self, base: QFont) -> None:
        """Dựng font tên, font dòng phụ và chiều cao hàng từ font thân `base` (font của danh sách)."""
        name = theme.font_for(theme.TextStyle.SECTION, base)
        if base.pointSizeF() > 0:
            name.setPointSizeF(base.pointSizeF())
        elif base.pixelSize() > 0:
            name.setPixelSize(base.pixelSize())
        name.setWeight(QFont.Weight.DemiBold)
        self._name_font = name
        self._caption_font = theme.font_for(theme.TextStyle.CAPTION, base)
        text = QFontMetrics(name).lineSpacing() + QFontMetrics(self._caption_font).lineSpacing() + 16
        self._row_height = max(MIN_ROW_HEIGHT, text) + ROW_GAP

    def row_height(self) -> int:
        """Chiều cao một hàng, kể cả khe giữa hai hàng."""
        return self._row_height

    @property
    def name_font(self) -> QFont:
        return QFont(self._name_font)

    @property
    def caption_font(self) -> QFont:
        return QFont(self._caption_font)

    def sizeHint(self, option: QStyleOptionViewItem, index: _Index) -> QSize:
        return QSize(COMPACT_CELL, self._row_height)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: _Index) -> None:
        widget = option.widget
        t = theme.tokens_for(widget)
        dark = theme.is_dark_palette(QApplication.palette())
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        focused = bool(state & QStyle.StateFlag.State_HasFocus)
        drop_count = 0
        if isinstance(widget, _ConversationView) and widget.is_drop_index(index):
            drop_count = max(1, widget.drop_count())
        if selected:
            background: QColor | None = t.selected
        elif hovered:
            background = _mix(t.sidebar, t.selected)
        else:
            background = None
        ring = background if background is not None else t.sidebar

        rect = QRectF(option.rect).adjusted(0, ROW_GAP / 2, 0, -ROW_GAP / 2)
        if self.compact:
            cell = QRectF(
                rect.center().x() - COMPACT_CELL / 2,
                rect.center().y() - COMPACT_CELL / 2,
                COMPACT_CELL,
                COMPACT_CELL,
            )
        else:
            cell = rect
        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            if background is not None:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(background)
                painter.drawRoundedRect(cell, theme.RADIUS_CARD, theme.RADIUS_CARD)
            presence = _role_presence(index)
            dpr = widget.devicePixelRatioF() if widget is not None else 1.0
            if self.compact:
                self._paint_compact(painter, cell, index, presence, ring, t, dpr)
            else:
                self._paint_full(painter, cell, index, presence, ring, t, dpr, drop_count)
            if drop_count:
                pen = QPen(t.text if selected else t.accent_strong, 2)
                pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(cell.adjusted(1, 1, -1, -1), theme.RADIUS_CARD, theme.RADIUS_CARD)
            elif focused:
                painter.setPen(QPen(theme.focus_ring_color(dark), 2))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(cell.adjusted(1, 1, -1, -1), theme.RADIUS_CARD, theme.RADIUS_CARD)
        finally:
            painter.restore()

    # -- Bên trong ------------------------------------------------------------------------------

    @staticmethod
    def _avatar(
        painter: QPainter, rect: QRectF, presence: Presence, ring: QColor, t: theme.Tokens, dpr: float
    ) -> None:
        paint_avatar(
            painter,
            rect,
            kind=AvatarKind.DESKTOP,
            presence=presence,
            emphasis=False,
            ring=ring,
            tokens=t,
            dpr=dpr,
        )

    @staticmethod
    def _warning_icon(painter: QPainter, rect: QRectF, color: QColor, dpr: float) -> None:
        # `warning` chỉ có cỡ 20 trong `icons.SIZES`: vẽ pixmap 20 thu vào ô 16×16.
        pm = icons.pixmap("warning", _WARNING_SOURCE, color, dpr)
        if not pm.isNull():
            painter.drawPixmap(rect, pm, QRectF(pm.rect()))

    def _paint_full(
        self,
        painter: QPainter,
        rect: QRectF,
        index: _Index,
        presence: Presence,
        ring: QColor,
        t: theme.Tokens,
        dpr: float,
        drop_count: int,
    ) -> None:
        avatar = QRectF(rect.left() + _PADDING, rect.center().y() - AVATAR_SIZE / 2, AVATAR_SIZE, AVATAR_SIZE)
        self._avatar(painter, avatar, presence, ring, t, dpr)

        name_metrics = QFontMetrics(self._name_font)
        caption_metrics = QFontMetrics(self._caption_font)
        name_h = name_metrics.lineSpacing()
        caption_h = caption_metrics.lineSpacing()
        left = avatar.right() + _AVATAR_GAP
        right = rect.right() - _PADDING
        top = rect.center().y() - (name_h + _LINE_GAP + caption_h) / 2

        when = index.data(TIME_ROLE)
        when = when if isinstance(when, str) else ""
        name_right = right
        if when:
            width = caption_metrics.horizontalAdvance(when)
            painter.setFont(self._caption_font)
            painter.setPen(t.text_muted)
            painter.drawText(
                QRectF(right - width, top, width, name_h),
                int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
                when,
            )
            name_right = right - width - _TIME_GAP
        name = index.data(Qt.ItemDataRole.DisplayRole)
        name = name if isinstance(name, str) else ""
        name_width = max(0.0, name_right - left)
        painter.setFont(self._name_font)
        painter.setPen(t.text)
        painter.drawText(
            QRectF(left, top, name_width, name_h),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            name_metrics.elidedText(name, Qt.TextElideMode.ElideRight, int(name_width)),
        )

        line = QRectF(left, top + name_h + _LINE_GAP, max(0.0, right - left), caption_h)
        if drop_count:
            text, color, icon_color = drop_text(drop_count), t.accent_text, None
        else:
            status = index.data(STATUS_ROLE)
            text = status if isinstance(status, str) else ""
            tone = _role_tone(index)
            if tone is StatusTone.BUSY:
                color, icon_color = t.accent_text, None
            elif tone is StatusTone.WARNING:
                color, icon_color = t.text, t.warning
            elif tone is StatusTone.DANGER:
                color, icon_color = t.text, t.danger
            else:
                color, icon_color = t.text_muted, None
        if icon_color is not None:
            icon = QRectF(line.left(), line.center().y() - _WARNING_ICON / 2, _WARNING_ICON, _WARNING_ICON)
            self._warning_icon(painter, icon, icon_color, dpr)
            line.setLeft(line.left() + _WARNING_ICON + 4)
        painter.setFont(self._caption_font)
        painter.setPen(color)
        painter.drawText(
            line,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            caption_metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(max(0.0, line.width()))),
        )

    def _paint_compact(
        self,
        painter: QPainter,
        cell: QRectF,
        index: _Index,
        presence: Presence,
        ring: QColor,
        t: theme.Tokens,
        dpr: float,
    ) -> None:
        avatar = QRectF(
            cell.center().x() - AVATAR_SIZE / 2, cell.center().y() - AVATAR_SIZE / 2, AVATAR_SIZE, AVATAR_SIZE
        )
        if presence is Presence.BUSY:
            painter.setPen(QPen(t.accent_strong, 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(avatar.adjusted(-2, -2, 2, 2))
        self._avatar(painter, avatar, presence, ring, t, dpr)
        tone = _role_tone(index)
        if tone in (StatusTone.WARNING, StatusTone.DANGER):
            color = t.danger if tone is StatusTone.DANGER else t.warning
            icon = QRectF(cell.right() - _WARNING_ICON, cell.top(), _WARNING_ICON, _WARNING_ICON)
            self._warning_icon(painter, icon, color, dpr)


# ---- View ----------------------------------------------------------------------------------------


class _ConversationView(QListView):
    """`QListView` của danh sách cuộc trò chuyện (xem docstring module, “View”)."""

    menu_requested = Signal(QModelIndex, QPoint)  # hàng (có thể không hợp lệ), vị trí toàn màn hình
    files_dropped = Signal(QModelIndex, list)  # hàng (có thể không hợp lệ), list[QUrl]
    row_double_clicked = Signal(QModelIndex)  # bấm đúp chuột trái lên hàng
    row_entered = Signal(QModelIndex)  # Enter / Return trên hàng hiện hành (không tính phím tự lặp)
    metrics_changed = Signal()  # font đổi: chiều cao hàng có thể đổi

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conversationList")
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setAutoFillBackground(False)
        self.viewport().setAutoFillBackground(False)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setTabKeyNavigation(False)  # Tab do `focusNextPrevChild` xử lý
        self.setUniformItemSizes(True)
        self.setSpacing(0)
        # Bề ngang tối thiểu là ô thu gọn, không phải `minimumSizeHint` của QAbstractScrollArea (rộng hơn
        # chỗ của cột trái thu gọn khi `sidebar_scroll` hiện thanh cuộn dọc).
        self.setMinimumWidth(COMPACT_CELL)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        self._drop_index = QPersistentModelIndex()  # hàng đang được kéo file qua (tô viền)
        self._drop_count = 0
        self._drag_pos: QPoint | None = None  # vị trí kéo cuối (viewport) khi đang có file kéo qua

    # -- Kéo thả --------------------------------------------------------------------------------

    def drop_target(self) -> str | None:
        """device_id của hàng đang được tô vì có file kéo qua; không có → None."""
        if not self._drop_index.isValid():
            return None
        device_id = self._drop_index.data(DEVICE_ID_ROLE)
        return device_id if isinstance(device_id, str) else None

    def drop_count(self) -> int:
        """Số file đang kéo qua hàng được tô (0 khi không có)."""
        return self._drop_count if self._drop_index.isValid() else 0

    def is_drop_index(self, index: _Index) -> bool:
        return self._drop_index.isValid() and QPersistentModelIndex(index) == self._drop_index

    def preview_drop(self, device_id: str | None, count: int) -> None:
        """Tô hàng của `device_id` như đang có `count` file kéo qua (None: bỏ tô); cùng đường với kéo."""
        index = QModelIndex()
        model = self.model()
        if device_id is not None and model is not None:
            for row in range(model.rowCount()):
                candidate = model.index(row, 0)
                if candidate.data(DEVICE_ID_ROLE) == device_id:
                    index = candidate
                    break
        if index.isValid():
            view = index.data(DEVICE_ROLE)
            if not isinstance(view, DeviceView) or not can_receive_files(view):
                index = QModelIndex()
        self._set_drop(index, count)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _has_local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        count = len(send.local_paths(_event_urls(event)))
        if not count:
            self._drag_pos = None
            self._set_drop(QModelIndex(), 0)
            event.ignore()
            return
        self._drag_pos = event.position().toPoint()
        self._drop_count = count
        if not self._update_drop_index():
            # Không truyền vùng cho `ignore`: hàng có thể dời chỗ trong lúc kéo (danh sách sắp theo hoạt
            # động), nên mỗi lần chuột di đều phải xét lại.
            event.ignore()
            return
        event.acceptProposedAction()

    def refresh_drop_target(self) -> None:
        """Model đổi hàng trong lúc đang kéo (sắp lại, thêm, bỏ): tô lại đúng hàng dưới con trỏ."""
        if self._drag_pos is not None:
            self.executeDelayedItemsLayout()  # vị trí hàng mới, trước khi `indexAt`
            self._update_drop_index()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._drag_pos = None
        self._set_drop(QModelIndex(), 0)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._drag_pos = None
        self._set_drop(QModelIndex(), 0)
        urls = _event_urls(event)
        if not send.local_paths(urls):
            event.ignore()
            return
        index = self.indexAt(event.position().toPoint())
        event.acceptProposedAction()
        self.files_dropped.emit(QModelIndex(index), urls)

    def _update_drop_index(self) -> bool:
        """Tô hàng dưới `_drag_pos` (không đổi hàng đang chọn); False nếu hàng đó không nhận thả được."""
        index = self.indexAt(self._drag_pos) if self._drag_pos is not None else QModelIndex()
        if index.isValid():
            view = index.data(DEVICE_ROLE)
            if not isinstance(view, DeviceView) or not can_receive_files(view):
                self._set_drop(QModelIndex(), self._drop_count)
                return False
        self._set_drop(index, self._drop_count)
        return True

    def _set_drop(self, index: _Index, count: int) -> None:
        persistent = QPersistentModelIndex(index)
        if persistent == self._drop_index and count == self._drop_count:
            return
        self._drop_index = persistent
        self._drop_count = count if persistent.isValid() else 0
        self.viewport().update()

    # -- Chuột, phím ----------------------------------------------------------------------------

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        super().mouseDoubleClickEvent(event)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        index = self.indexAt(event.position().toPoint())
        if index.isValid():
            self.row_double_clicked.emit(index)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key, modifiers = event.key(), event.modifiers()
        if key in _ENTER_KEYS and self.currentIndex().isValid():
            if not event.isAutoRepeat():  # giữ phím: mỗi lần nhấn thật chỉ một lần
                self.row_entered.emit(self.currentIndex())
            event.accept()
            return
        # Phím Menu / Shift+F10 xử lý ngay (nhận rồi thì Qt không sinh thêm QContextMenuEvent), để chạy
        # giống nhau trên mọi hệ điều hành và cả khi phím được gửi thẳng tới widget.
        if key == Qt.Key.Key_Menu or (
            key == Qt.Key.Key_F10 and modifiers & Qt.KeyboardModifier.ShiftModifier
        ):
            self._request_keyboard_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:
        if event.reason() == QContextMenuEvent.Reason.Keyboard:
            self._request_keyboard_menu()
        else:
            pos = event.pos()
            index = self.indexAt(pos)
            if index.isValid():
                self.setCurrentIndex(index)
            self.menu_requested.emit(QModelIndex(index), self.viewport().mapToGlobal(pos))
        event.accept()

    def _request_keyboard_menu(self) -> None:
        index = self.currentIndex()
        pos = self.visualRect(index).center() if index.isValid() else QPoint(0, 0)
        self.menu_requested.emit(QModelIndex(index), self.viewport().mapToGlobal(pos))

    def focusNextPrevChild(self, next: bool) -> bool:
        model = self.model()
        current = self.currentIndex()
        # Qt gọi hàm này trên widget đang có tiêu điểm khi nhấn Tab (không dùng `hasFocus()`: cửa sổ chưa
        # được kích hoạt thì `hasFocus()` là False dù danh sách đang là widget tiêu điểm của nó).
        if self.window().focusWidget() is self and model is not None and current.isValid():
            target = current.row() + (1 if next else -1)
            if 0 <= target < model.rowCount():
                self._move_current(model.index(target, 0))
                return True
        return super().focusNextPrevChild(next)

    def _move_current(self, index: QModelIndex) -> None:
        """Đổi hàng hiện hành mà không đổi lựa chọn: Tab chỉ đi qua, máy được chọn chỉ đổi bằng chuột,
        mũi tên hay thả file (nếu không, Tab đi ngang cột trái là đổi cuộc trò chuyện)."""
        selection = self.selectionModel()
        if selection is not None:
            selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        model = self.model()
        if model is None or model.rowCount() == 0:
            return
        if event.reason() == Qt.FocusReason.TabFocusReason:
            self._move_current(model.index(0, 0))
        elif event.reason() == Qt.FocusReason.BacktabFocusReason:
            self._move_current(model.index(model.rowCount() - 1, 0))
        elif not self.currentIndex().isValid():
            self._move_current(model.index(0, 0))

    def row_rect(self, index: QModelIndex) -> QRect:
        """`visualRect` sau khi chạy layout đang hoãn (hàng vừa dời chỗ)."""
        self.executeDelayedItemsLayout()
        return self.visualRect(index)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.FontChange:
            self.metrics_changed.emit()
        elif event.type() in _PALETTE_EVENTS:
            self.viewport().update()


def _event_urls(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[QUrl]:
    mime = event.mimeData()
    return list(mime.urls()) if mime is not None and mime.hasUrls() else []


def _has_local_files(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> bool:
    return bool(send.local_paths(_event_urls(event)))


# ---- ConversationList ----------------------------------------------------------------------------


class ConversationList(QWidget):
    """Cột trái: danh sách cuộc trò chuyện và nút “Ghép đôi máy mới” (xem docstring module)."""

    send_files_requested = Signal(str, list)  # device_id, list[Path] (thả)
    pick_files_requested = Signal(str)  # menu “Gửi file…”
    open_requested = Signal(str)  # Enter, bấm đúp: mở cuộc trò chuyện (tiêu điểm vào thanh gửi)
    drop_hint_requested = Signal(str)  # thả chỗ không có máy: radar.drop_hint_text()
    unpair_requested = Signal(str)
    add_device_requested = Signal()  # “＋ Ghép đôi máy mới”
    current_changed = Signal(object)  # device_id đang chọn (str) hay None; phát khi đổi thật

    def __init__(self, devices: DeviceListModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("conversations")
        self.setAutoFillBackground(False)
        self.setAcceptDrops(True)  # thả vào chỗ trống, nút “＋” → gợi ý
        self._menu: QMenu | None = None
        self._compact = False
        self._current_id: str | None = None
        self._restore_id: str | None = None
        self._restore_selected = False
        self._selected_before_remove: str | None = None

        self.model = ConversationModel(devices, self)
        self.delegate = ConversationDelegate(self)
        self.list_view = _ConversationView(self)
        self.delegate.set_base_font(self.list_view.font())
        # Nối trước `setModel`: phải thấy lựa chọn trước khi view dời nó sang hàng kế tiếp.
        self.model.rowsAboutToBeRemoved.connect(self._remember_removed_selection)
        self.list_view.setModel(self.model)
        self.list_view.setItemDelegate(self.delegate)
        for signal in (
            self.model.layoutChanged,
            self.model.rowsInserted,
            self.model.rowsRemoved,
            self.model.modelReset,
        ):
            signal.connect(self.list_view.refresh_drop_target)
        self.list_view.row_double_clicked.connect(self._on_row_activated)
        self.list_view.row_entered.connect(self._on_row_activated)
        self.list_view.menu_requested.connect(self._on_menu_requested)
        self.list_view.files_dropped.connect(self._on_files_dropped)
        self.list_view.metrics_changed.connect(self._on_metrics_changed)

        self.add_button = IconButton(
            "add",
            QCoreApplication.translate("Conversations", "Ghép đôi máy mới"),
            self,
            shortcut=shortcuts.sequence(shortcuts.Shortcut.DISCOVER),
            show_text=True,
        )
        self.add_button.setObjectName("addDeviceButton")
        self.add_button.clicked.connect(self.add_device_requested)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(_LIST_SPACING)
        self._layout.addWidget(self.list_view)
        self._layout.addWidget(self.add_button, 0, Qt.AlignmentFlag.AlignLeft)
        self._layout.addStretch(1)
        QWidget.setTabOrder(self.list_view, self.add_button)

        self.model.modelAboutToBeReset.connect(self._remember_current)
        self.model.modelReset.connect(self._restore_current)
        self.model.rowsRemoved.connect(self._keep_selection_after_remove)
        for signal in (
            self.model.modelReset,
            self.model.rowsInserted,
            self.model.rowsRemoved,
            self.model.layoutChanged,
        ):
            signal.connect(self._on_rows_changed)
        selection = self.list_view.selectionModel()
        if selection is not None:
            selection.selectionChanged.connect(self._emit_current)

        self.retranslate()
        self._on_rows_changed()

    # ---- API -------------------------------------------------------------------------------------

    @property
    def compact(self) -> bool:
        return self._compact

    @property
    def last_menu(self) -> QMenu | None:
        """Menu ngữ cảnh mở gần nhất (test, trợ năng)."""
        return self._menu

    def first_focus_widget(self) -> QWidget:
        return self.list_view

    def last_focus_widget(self) -> QWidget:
        return self.add_button

    def current_device(self) -> DeviceView | None:
        """View mới nhất của máy **được chọn**; không có → None."""
        device_id = self._selected_id()
        return None if device_id is None else self.model.device(device_id)

    def device_id_at(self, row: int) -> str | None:
        """Mã máy ở hàng `row` (thứ tự đang hiện); không có hàng đó → None."""
        if not 0 <= row < self.model.rowCount():
            return None
        value = self.model.index(row, 0).data(DEVICE_ID_ROLE)
        return value if isinstance(value, str) else None

    def neighbor_id(self, step: int) -> str | None:
        """Mã máy cách máy được chọn `step` hàng (âm: lên trên); ra ngoài danh sách → None (không
        vòng). Chưa chọn máy nào: `step` > 0 → hàng đầu, `step` < 0 → hàng cuối, 0 → None."""
        rows = self.model.rowCount()
        selected = self._selected_id()
        current = -1 if selected is None else self.model.row_of(selected)
        if current < 0:
            if step == 0 or rows == 0:
                return None
            return self.device_id_at(0 if step > 0 else rows - 1)
        return self.device_id_at(current + step) if step else selected

    def select_device(self, device_id: str) -> bool:
        """Chọn máy (làm máy hiện hành); không có trong danh sách → False."""
        row = self.model.row_of(device_id)
        if row < 0:
            return False
        self.list_view.setCurrentIndex(self.model.index(row, 0))
        return True

    def context_menu_for(self, device_id: str) -> QMenu | None:
        """Menu của một máy (“Gửi file…”, “Hủy ghép đôi…”); không có máy → None. Menu có cha là danh
        sách; người gọi tự `deleteLater()` khi không dùng nữa."""
        view = self.model.device(device_id)
        if view is None:
            return None
        t = QCoreApplication.translate
        menu = QMenu(self)
        menu.setAccessibleName(
            texts.fill(
                t("Conversations", "Thao tác với {name}"), name=texts.peer_label(view.name, view.device_id)
            )
        )
        if can_receive_files(view):
            action = QAction(t("Conversations", "Gửi file…"), menu)
            action.triggered.connect(lambda _=False, i=view.device_id: self._request_pick(i))
            menu.addAction(action)
        if view.paired:
            action = QAction(t("Conversations", "Hủy ghép đôi…"), menu)
            action.triggered.connect(lambda _=False, i=view.device_id: self._request_unpair(i))
            menu.addAction(action)
        if not menu.actions():
            menu.deleteLater()
            return None
        return menu

    def drop_files(self, device_id: str | None, urls: list[QUrl]) -> bool:
        """Thả `urls` lên máy `device_id` (None: chỗ trống); True nếu đã phát `send_files_requested`.

        Chỉ lấy URL file cục bộ (không chạm đĩa); không có cái nào → bỏ qua. Chỗ trống hay máy không
        còn trong danh sách → `drop_hint_requested`. Máy không gửi tới được → bỏ qua.
        """
        paths = send.local_paths(urls)
        if not paths:
            return False
        view = None if device_id is None else self.model.device(device_id)
        if view is None:
            self.drop_hint_requested.emit(drop_hint_text())
            return False
        if not can_receive_files(view):
            return False
        self.select_device(view.device_id)
        self.send_files_requested.emit(view.device_id, paths)
        return True

    def set_compact(self, compact: bool) -> None:
        """Dạng thu gọn (cột trái chỉ còn avatar) hay đầy đủ."""
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.delegate.compact = compact
        button = self.add_button
        if compact:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setFixedSize(ICON_BUTTON_SIZE, ICON_BUTTON_SIZE)
            self._layout.setAlignment(button, Qt.AlignmentFlag.AlignHCenter)
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setMinimumWidth(0)
            button.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
            button.setFixedHeight(ICON_BUTTON_SIZE)
            self._layout.setAlignment(button, Qt.AlignmentFlag.AlignLeft)
        self.list_view.doItemsLayout()
        self.list_view.viewport().update()
        self.updateGeometry()

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        self.list_view.setAccessibleName(t("Conversations", "Máy đã ghép đôi"))
        self.list_view.setAccessibleDescription(
            t(
                "Conversations",
                "Mũi tên để chọn máy, Tab để đi qua từng máy, Enter để mở cuộc trò chuyện, "
                "phím Menu để mở thao tác.",
            )
        )
        self.add_button.set_label(t("Conversations", "Ghép đôi máy mới"))
        self.model.refresh()

    # ---- Kéo thả vào phần còn lại ----------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _has_local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _has_local_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = _event_urls(event)
        if not send.local_paths(urls):
            event.ignore()
            return
        event.acceptProposedAction()
        self.drop_files(None, urls)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()

    # ---- Bên trong -------------------------------------------------------------------------------

    def _selected_id(self) -> str | None:
        selection = self.list_view.selectionModel()
        if selection is None:
            return None
        for index in selection.selectedIndexes():
            device_id = index.data(DEVICE_ID_ROLE)
            if isinstance(device_id, str):
                return device_id
        return None

    def _emit_current(self) -> None:
        device_id = self._selected_id()
        if device_id != self._current_id:
            self._current_id = device_id
            self.current_changed.emit(device_id)

    def _on_rows_changed(self) -> None:
        rows = self.model.rowCount()
        self.list_view.setVisible(rows > 0)
        self._update_height()
        selection = self.list_view.selectionModel()
        if rows and selection is not None and self._selected_id() is None:
            # Luôn có một cuộc trò chuyện được chọn khi có hàng (spec B3 mục 6): hàng hiện hành nếu có,
            # không thì hàng 0.
            current = self.list_view.currentIndex()
            index = current if current.isValid() else self.model.index(0, 0)
            selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.ClearAndSelect)
        self._emit_current()

    def _update_height(self) -> None:
        rows = self.model.rowCount()
        height = rows * self.delegate.row_height() + 2 * self.list_view.frameWidth()
        if self.list_view.height() != height or self.list_view.minimumHeight() != height:
            self.list_view.setFixedHeight(height)

    def _on_metrics_changed(self) -> None:
        self.delegate.set_base_font(self.list_view.font())
        self.list_view.doItemsLayout()
        self._update_height()

    def _remember_current(self) -> None:
        index = self.list_view.currentIndex()
        device_id = index.data(DEVICE_ID_ROLE) if index.isValid() else None
        self._restore_id = device_id if isinstance(device_id, str) else None
        self._restore_selected = self._restore_id is not None and self._selected_id() == self._restore_id

    def _restore_current(self) -> None:
        device_id, self._restore_id = self._restore_id, None
        if device_id is None:
            return
        if self._restore_selected:
            self.select_device(device_id)
            return
        row = self.model.row_of(device_id)
        selection = self.list_view.selectionModel()
        if row >= 0 and selection is not None:
            selection.setCurrentIndex(self.model.index(row, 0), QItemSelectionModel.SelectionFlag.NoUpdate)

    def _remember_removed_selection(self) -> None:
        self._selected_before_remove = self._selected_id()

    def _keep_selection_after_remove(self) -> None:
        # Bỏ một hàng mà máy đang chọn vẫn còn: giữ đúng máy đó (Qt có thể dời lựa chọn sang hàng kế).
        # Hàng đang chọn bị bỏ: `_on_rows_changed` chọn hàng hiện hành hay hàng 0.
        device_id, self._selected_before_remove = self._selected_before_remove, None
        if device_id is not None and self.model.row_of(device_id) >= 0 and self._selected_id() != device_id:
            self.select_device(device_id)

    def _device_at(self, index: QModelIndex) -> DeviceView | None:
        device_id = index.data(DEVICE_ID_ROLE) if index.isValid() else None
        return self.model.device(device_id) if isinstance(device_id, str) else None

    def _on_row_activated(self, index: QModelIndex) -> None:
        view = self._device_at(index)
        if view is not None:
            self.select_device(view.device_id)
            self.open_requested.emit(view.device_id)

    def _on_menu_requested(self, index: QModelIndex, global_pos: QPoint) -> None:
        device_id = index.data(DEVICE_ID_ROLE) if index.isValid() else None
        if not isinstance(device_id, str):
            return
        menu = self.context_menu_for(device_id)
        if menu is None:
            return
        old, self._menu = self._menu, menu
        if old is not None:
            with contextlib.suppress(RuntimeError):  # menu cũ có thể đã bị Qt hủy
                old.close()
                old.deleteLater()
        menu.popup(global_pos)

    def _on_files_dropped(self, index: QModelIndex, urls: list[QUrl]) -> None:
        device_id = index.data(DEVICE_ID_ROLE) if index.isValid() else None
        self.drop_files(device_id if isinstance(device_id, str) else None, urls)

    def _request_pick(self, device_id: str) -> bool:
        """Phát `pick_files_requested` nếu máy vẫn còn trong danh sách và gửi tới được."""
        view = self.model.device(device_id)
        if view is not None and can_receive_files(view):
            self.pick_files_requested.emit(device_id)
            return True
        return False

    def _request_unpair(self, device_id: str) -> None:
        view = self.model.device(device_id)
        if view is not None and view.paired:
            self.unpair_requested.emit(device_id)
