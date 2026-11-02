"""Luồng chat theo máy ở khung phải cửa sổ chính (spec B3; mvp F4, F5, mục 7.1, mục 8, N12).

`ChatView` (objectName `chatView`) thay danh sách lượt truyền cũ: `ui.transfers.TransfersController`
dựng nó, đặt vào `MainWindow.transfers_area`. Từ trên xuống: `info_bar` (thông báo chung:
`widgets.InfoBar`, ẩn khi không có), `header` (`ChatHeader`: avatar, tên máy font điểm nhấn, dòng
“Trực tuyến · Windows · 192.168.1.20” / “Ngoại tuyến · Windows” / nhãn lỗi kết nối ngắn của B2; theo
model thiết bị dùng chung `devices`), `threads` (`QStackedWidget`: `placeholder` khi chưa chọn máy,
`empty_state` khi luồng rỗng, hay `ChatThread` của máy đang chọn), nút “↓ Mới” (`new_button`), và
`composer` (`ChatComposer`: nút “Gửi file”, câu “hoặc kéo file vào đây” hay câu máy ngoại tuyến).

**Luồng** (`ChatThread`, mỗi máy một luồng, dựng lười khi có bong bóng đầu tiên hay khi được mở):
`QScrollArea` không thanh cuộn ngang; mỗi bong bóng (`ui.chat_bubbles`) nằm trong một `BubbleRow`
(gửi đi sát phải, nhận vào sát trái), xếp theo `at` (lượt của phiên: `max(_wall_now(), at của bong
bóng phiên cuối)` lúc thấy lần đầu, nên đồng hồ lùi không chèn vào giữa; lịch sử:
`finished_at.timestamp()`), tìm nhị phân, bằng nhau đứng sau. Dòng mốc `TimeSeparator` trước bong bóng
i khi `needs_separator(at[i-1], at[i])`; chèn/gỡ ở giữa thì tính lại mốc của i và i+1; chữ mốc tính lại
khi luồng hiện và khi thêm bong bóng (không hẹn giờ qua nửa đêm). Không có mốc sự kiện. Trần
`MAX_THREAD_BUBBLES` bong bóng mỗi luồng: vượt thì gỡ bong bóng **đã kết thúc** cũ nhất, không bao giờ
gỡ lượt đang chạy.

**Cuộn**: `pinned` = thanh cuộn ở cuối (trong `PIN_SLACK` px), cập nhật ở `valueChanged`; khoảng cuộn
đổi mà đang `pinned` thì kéo xuống cuối. Bong bóng **mới của phiên** (và bong bóng tạm) chèn cuối:
không `pinned` thì đếm “lượt mới” và hiện `new_button` (“↓ Mới”, tên trợ năng “Có n lượt mới. Bấm để
cuộn xuống cuối”); bấm hay tự cuộn tới cuối thì ẩn. Bong bóng đang được đếm mà bị gỡ thì bớt đếm, nên
bong bóng tạm rồi bong bóng thật của một lần gửi chỉ là một lượt mới. Nhịp tiến độ và nạp lịch sử
không bật nút. Mở luồng thì `pinned`.

**Định tuyến**: `handle(update)` theo `key.device_id` tới luồng của máy đó (luồng không được chọn vẫn
cập nhật widget); luật theo từng lượt nằm ở `chat_bubbles.TransferBubble`, luật theo máy
(`DataUnreachable`, `set_connected`) chạy trên các bong bóng của máy đó. Mỗi `TransferProgress` tra
dict O(1), không dựng widget, không phát `content_changed`. API cũ của danh sách lượt truyền giữ
nguyên: `handle`, `load_snapshot`, `remove`, `clear`, `rows` (bong bóng của phiên ở mọi luồng, cũ
trước), `row` (chỉ bong bóng của phiên: `ui.transfers` dựa vào `row(key) is None`), `has_content`
(thông báo đang hiện hay đang chọn một máy), `active_count` (mọi luồng), `show_notice` (kèm `level`),
`hide_notice`, `notice_text` (“” khi không có), `notice_action_text`, `set_device_names`,
`set_connected`, `set_receive_dir`, `cancel_requested`, `change_receive_dir_requested` (nút “Đổi thư
mục nhận” của bong bóng nhận, spec D4 mục 5.2; `ui.app` mở hộp chọn như “Đổi…”), `content_changed`
(gộp: phát một lần mỗi lời gọi ngoài cùng có thay đổi cấu trúc: thêm/gỡ bong bóng kể cả lịch sử và
bong bóng tạm, lượt kết thúc, thông báo, đổi máy). Chữ của `show_notice` là `texts.Text`: đổi ngôn ngữ
thì câu dựng bằng hàm được dịch lại, câu dịch sẵn thì thông báo bị ẩn (không còn câu của ngôn ngữ cũ).

**Lời mời nhận file** (spec B4 mục 3.5): `set_offer_book(book)` nối `ui.offer.OfferBook`. `added` →
`_ensure` bong bóng của key rồi `TransferBubble.set_offer` (panel Nhận / Từ chối, viền ATTENTION, ẩn
✕); `changed` / `removed` chỉ cập nhật bong bóng đã có (không có thì bỏ qua, nên `book.clear()` trước
`clear()` không dựng lại bong bóng). Thêm/gỡ panel phát `content_changed`. Panel phát ý định qua
`offer_answer_requested(key, accept)`, `offer_always_toggled(key, on)` và
`change_receive_dir_requested()`; quyết định do book chốt. `cancel_requested` không bao giờ phát cho
bong bóng đang có panel. Lời mời mới ở luồng đang mở (khi `ChatView` đang hiện) phát `QAccessible`
Alert trên bong bóng, không cướp tiêu điểm. Luồng không được mở vẫn có panel. `set_receive_dir` /
`set_receive_dir_pending` cập nhật dòng “Lưu vào” của các panel. `is_pinned(id)`: luồng của máy đó
đang ở cuối (chưa dựng → True), cho `ui.transfers` quyết định có bật hộp hỏi không.

**Gửi**: nút “Gửi file” và phím Chọn file (`_pick_action`, `QAction` `WindowShortcut` trên `ChatView`
từ `ui.shortcuts`, chỉ bật khi có máy được chọn; widget ẩn thì không chạy) phát
`pick_files_requested(id)`. Thả file vào bất cứ đâu trong `ChatView` (luồng, màn rỗng, thanh dưới):
chỉ URL file cục bộ (`send.local_paths`, không `stat`), đang kéo thì `_DropOverlay` viền nét đứt 2 px
`accent_strong` và “Thả để gửi n file tới X”; thả → `drop_paths`: `send_files_requested(id, paths)`,
chưa chọn máy → `drop_hint_requested(radar.drop_hint_text())`; phòng hờ: máy có trong model mà
`radar.can_receive_files` sai thì bỏ qua (trả False). `preview_drop(n)` đi cùng đường (ảnh chụp,
test). Máy ngoại tuyến vẫn gửi được (lượt chờ kết nối, mvp mục 8); thanh dưới đổi câu gợi ý thành câu
ngoại tuyến kèm icon `cloud_off`. Bong bóng tạm “Đang chuẩn bị…” (`add_pending` / `remove_pending`)
hiện từ lúc chọn xong tới khi `transfers.send` trả về; không nằm trong `rows`, `row`, `active_count`.

**Dán file** (mvp F4): phím Dán (`_paste_action`, phím Dán chuẩn của hệ điều hành, StandardKey Paste;
`WindowShortcut`, không tự lặp) → `paste_from_clipboard()`: `ChatView` không hiện → None (không làm
gì; kể cả khi chưa ghép máy nào và khung phải là màn rỗng của cửa sổ: phím Dán im lặng), còn lại
`paste_mime(_clipboard_mime())` trả `PasteOutcome`: chưa chọn máy → `drop_hint_requested` với
`paste_no_device_text()`, NO_DEVICE (bất kể clipboard có gì); clipboard không phải toàn file cục bộ
(`send.clipboard_paths`: chữ, ảnh, URL web, rỗng, None, hay lẫn URL web) → thông báo INFO
`paste_not_files_text` kèm nút “Mở Cài đặt” phát `clipboard_settings_requested(id)` (`ui.app` mở Cài
đặt ▸ Thiết bị tin cậy, tiêu điểm vào “Đồng bộ clipboard” của máy đó), NOT_FILES; còn lại
`drop_paths` như thả file: SENT, hay BLOCKED khi máy không gửi tới được. Gửi ngay, không hỏi. Chỉ đọc
URL của clipboard trên luồng Qt (không đọc chữ, ảnh, không `stat`). File “Cắt” trong File Explorer
cũng chỉ được gửi một bản sao: Teleport không xóa hay di chuyển file nguồn. Ô nhập sửa được trong
cửa sổ tự nhận `ShortcutOverride` cho Paste nên phím Dán ở đó vẫn dán chữ.

**Clipboard** (mvp F8): `show_clipboard(device_id, ok=…, kind=…, size=…, preview=…,
image_size=…)` (từ `ui.app`, sự kiện `RECEIVED` / `WRITE_FAILED` của `app.clipboard`) đặt một
`chat_bubbles.ClipboardNote` vào luồng của máy đó (dựng luồng nếu chưa có). Mỗi luồng tối đa **một**
note, mới nhất: note cũ bị gỡ, note mới chèn cuối (`at` = `session_at()`); có tính “↓ Mới” và
`content_changed`, nhưng không nằm trong `rows`, `row`, `active_count`, lịch sử (`keys`, `bubble_for`
bỏ qua nó), không bị `MAX_THREAD_BUBBLES` gỡ. “Thử lại” của note → `retry_clipboard_requested(id)`
(note tắt nút tới khi `finish_clipboard_retry(id, available=…)`; False → câu “không còn để chép
lại”; kết quả áp cho note của lần bấm cũ nhất còn chờ, note đó đã bị thay thì bỏ). Nội dung chỉ ở RAM
của widget, chỉ trong phiên; `clear()` (host mới) gỡ hết.

**Lịch sử theo máy** (F5): mở luồng mà `history_state` là NONE thì sau `HISTORY_DEBOUNCE_MS` (đổi máy
liên tiếp chỉ gọi một lần) đặt LOADING và phát `history_needed(id)`; chưa ai nối signal thì coi như
không có lịch sử (LOADED). `load_history(id, entries)` chỉ áp khi luồng đó đang mở và đang LOADING;
mục trùng khóa với bất kỳ bong bóng nào bị bỏ; còn lại dựng `HistoryBubble` theo `at`, không bật “↓
Mới”, chèn hàng loạt (`ChatThread.add_many`: nội dung ẩn trong lúc chèn, chữ mốc tính một lần). Sự
kiện của phiên tới cho khóa đang có `HistoryBubble` thì bong bóng của phiên thay nó.
`history_failed(id)` → dòng mờ “Không đọc được lịch sử với máy này.” Rời luồng thì gỡ mọi
`HistoryBubble` của nó (tối đa một luồng giữ widget lịch sử, mvp N3), bong bóng của phiên giữ.
`invalidate_history(id | None)` gỡ lịch sử của một hay mọi máy rồi nạp lại luồng đang mở;
`showEvent` của `ChatView` nạp lại lịch sử của luồng đang mở (bong bóng đã có giữ nguyên).
“Hiện trong thư mục” của bong bóng nhận xong và của mục lịch sử đi qua `ui.shell.show_in_folder`
(bong bóng: `saved_paths`, không có thì `last_path`, với `finished_receive_dir` làm `root`; mục lịch
sử: `saved_path` với thư mục nhận hiện tại làm `root`, nên mục nhận trước khi đổi thư mục nhận chỉ mở
thư mục cha); không mở được (kể cả dự phòng `open_url`) → `info_bar` WARNING với thư mục cha.

**Màn rỗng** (spec B3 mục 9b.21): máy đang chọn chưa có bong bóng nào và không đang nạp lịch sử →
`empty_state` (icon `attach`, “Kéo file vào đây để gửi cho X”, “Hoặc bấm Gửi file ở dưới, hay nhấn
{phím Dán} để dán file đã chép.” (tên phím từ `ui.shortcuts`), không nút). Đang nạp (kể cả trong
lúc chờ debounce) thì luồng trống, không chớp màn rỗng; lịch sử lỗi thì hiện luồng với dòng lỗi.

**Bàn phím** (N12; spec B3 mục 9.10): widget nhận Tab của `ChatView` dựng trong `__init__` theo thứ tự
các ô của `info_bar` → nhãn của `empty_state` → `threads` (điểm dừng Tab duy nhất của luồng,
`TabFocus`, tắt khi luồng không có bong bóng) → `new_button` → `composer.send_button`. `threads`
không có `ClickFocus`: bấm thanh cuộn hay chỗ trống trong luồng không kéo tiêu điểm về đó (nhận tiêu
điểm sẽ cuộn tới bong bóng hiện hành, giật khung cuộn khỏi chỗ đang đọc). Mọi widget dựng lười (luồng,
bong bóng, nút trong bong bóng, mốc) là `ClickFocus` / `NoFocus`. `threads` nhận tiêu điểm (từ bàn
phím) thì chuyển sang bong bóng hiện hành (mặc định mới nhất); ↑/↓/Home/End/PageUp/PageDown đổi bong
bóng hiện hành và cuộn tới nó; Tab từ bong bóng đi qua các nút của chính nó rồi sang `new_button` (nếu
hiện) hay `send_button`; Shift+Tab từ bong bóng ra widget trước `threads`
(`ChatThread.focusNextPrevChild`). `scroll_area` có tên trợ năng “Các lượt gửi nhận với X”.

**Chữ máy kia** qua `texts.peer_label` / `texts.file_label`, nhãn `Qt.PlainText`; hệ điều hành (từ
mDNS) chỉ hiện khi là giá trị đã biết (`texts.os_label`). Màu tự vẽ lấy từ `theme.tokens_for`. Chuỗi
mới ở ngữ cảnh `"Chat"`, gọi lúc dùng, dựng lại khi `LanguageChange`. Không chạm đĩa trên luồng Qt.

Seam cho test (biến cấp module, đọc lúc gọi): `open_url`, `_wall_now`, `_clipboard_mime`.
"""

from __future__ import annotations

import bisect
import contextlib
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from enum import StrEnum
from itertools import pairwise
from pathlib import Path

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMetaMethod,
    QMimeData,
    QObject,
    QPoint,
    QRectF,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAccessible,
    QAccessibleEvent,
    QDesktopServices,
    QDragEnterEvent,
    QDragLeaveEvent,
    QDragMoveEvent,
    QDropEvent,
    QFocusEvent,
    QGuiApplication,
    QKeyEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from teleport.app.devices import DeviceView
from teleport.app.transfers import (
    DataUnreachable,
    FileDone,
    OfferReceived,
    TransferFinished,
    TransferInfo,
    TransferKey,
    TransferProgress,
    TransferResult,
    TransferResumed,
    TransferStatusChanged,
    TransferUpdate,
)
from teleport.core.history import HistoryEntry
from teleport.core.messages import ClipKind
from teleport.ui import i18n, icons, send, shell, shortcuts, texts, theme
from teleport.ui.chat_bubbles import (
    BubbleContext,
    ClipboardNote,
    HistoryBubble,
    PendingBubble,
    TimeSeparator,
    TransferBubble,
    needs_separator,
    separator_text,
)
from teleport.ui.conversations import failure_text
from teleport.ui.offer import OfferBook
from teleport.ui.radar import DeviceListModel, can_receive_files, drop_hint_text
from teleport.ui.send import printable
from teleport.ui.shortcuts import Shortcut
from teleport.ui.widgets import (
    BubbleRow,
    ChatBubble,
    DeviceAvatar,
    EmptyState,
    IconButton,
    InfoBar,
    InfoLevel,
    Presence,
)

# Seam: mở thư mục bằng ứng dụng mặc định của hệ điều hành (test thay bằng hàm ghi lại URL).
open_url = QDesktopServices.openUrl
# Seam: giờ tường (giây epoch) cho `at` của lượt phiên và chữ dòng mốc; đọc lúc gọi.
_wall_now: Callable[[], float] = time.time


def _system_clipboard_mime() -> QMimeData | None:
    clipboard = QGuiApplication.clipboard()
    return None if clipboard is None else clipboard.mimeData()


# Seam: nội dung clipboard khi dán file (test thay bằng hàm trả `QMimeData` tự dựng); đọc lúc gọi.
_clipboard_mime: Callable[[], QMimeData | None] = _system_clipboard_mime

HISTORY_DEBOUNCE_MS = 120
MAX_THREAD_BUBBLES = 200
PIN_SLACK = 24  # px
_AVATAR = 36  # px, avatar ở đầu luồng
_ICON = 20  # px
_PAGE_STEP = 5  # bong bóng mỗi lần PageUp / PageDown
_MARGIN = theme.SPACING[3]
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
_NAV_KEYS = frozenset(
    {
        Qt.Key.Key_Up,
        Qt.Key.Key_Down,
        Qt.Key.Key_Home,
        Qt.Key.Key_End,
        Qt.Key.Key_PageUp,
        Qt.Key.Key_PageDown,
    }
)
# Lý do tiêu điểm làm khung cuộn đi theo bong bóng (điều hướng phím); các lý do khác thì không.
_SCROLL_FOCUS_REASONS = frozenset(
    {
        Qt.FocusReason.TabFocusReason,
        Qt.FocusReason.BacktabFocusReason,
        Qt.FocusReason.OtherFocusReason,
    }
)

Bubble = TransferBubble | HistoryBubble | PendingBubble | ClipboardNote


class PasteOutcome(StrEnum):
    """Kết quả của `ChatView.paste_mime` (dán file đã chép)."""

    SENT = "sent"  # đã phát `send_files_requested`
    NO_DEVICE = "no_device"  # chưa chọn máy: gợi ý ghép đôi
    NOT_FILES = "not_files"  # clipboard không phải file cục bộ: gợi ý “Đồng bộ clipboard”
    BLOCKED = "blocked"  # máy đang chọn không gửi tới được


def paste_no_device_text() -> str:
    """Gợi ý khi dán file mà chưa chọn máy nào (mvp mục 8)."""
    return texts.fill(
        QCoreApplication.translate(
            "Chat", "Ghép đôi một máy trước ({discover_key}), rồi nhấn {key} để gửi file đã chép."
        ),
        discover_key=shortcuts.key_text(Shortcut.DISCOVER),
        key=shortcuts.key_text(Shortcut.PASTE_FILES),
    )


def paste_not_files_text(name: str) -> str:
    """Gợi ý khi dán mà clipboard không phải file (mvp mục 8); `name` đã qua `texts.peer_label`."""
    return texts.fill(
        QCoreApplication.translate(
            "Chat",
            "{key} ở đây chỉ gửi file đã chép trong {file_manager}. Chữ và ảnh đi qua “Đồng bộ clipboard” "
            "với {name} (Cài đặt ▸ Thiết bị tin cậy, cần bật ở cả hai máy): chép ở máy này rồi dán thẳng "
            "ở máy kia.",
        ),
        key=shortcuts.key_text(Shortcut.PASTE_FILES),
        file_manager=texts.file_manager_name(),
        name=name,
    )


def paste_settings_text() -> str:
    """Nút của gợi ý khi dán không phải file."""
    return QCoreApplication.translate("Chat", "Mở Cài đặt")


class HistoryState(StrEnum):
    """Trạng thái lịch sử của một luồng."""

    NONE = "none"
    LOADING = "loading"
    LOADED = "loaded"
    FAILED = "failed"


def _key_of(update: TransferUpdate) -> TransferKey | None:
    key = getattr(update, "key", None)
    if isinstance(key, TransferKey):
        return key
    info = getattr(update, "info", None)
    return info.key if isinstance(info, TransferInfo) else None


def _event_paths(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[Path]:
    mime = event.mimeData()
    if mime is None or not mime.hasUrls():
        return []
    return send.local_paths(mime.urls())


# ---- Luồng của một máy --------------------------------------------------------------------------


class _Item:
    """Một bong bóng trong luồng: dòng mốc (ẩn khi không cần) + hàng của bong bóng."""

    __slots__ = ("at", "bubble", "separator", "seq", "wrapper")

    def __init__(self, bubble: Bubble, at: float, seq: int, parent: QWidget) -> None:
        self.bubble = bubble
        self.at = at
        self.seq = seq
        self.wrapper = QWidget(parent)
        layout = QVBoxLayout(self.wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(theme.SPACING[1])
        self.separator = TimeSeparator(self.wrapper)
        self.separator.setVisible(False)
        layout.addWidget(self.separator)
        if isinstance(bubble, ChatBubble):
            layout.addWidget(BubbleRow(bubble, self.wrapper))
        else:  # `ClipboardNote`: dòng mảnh căn trái
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(bubble, 3)
            row.addStretch(2)
            layout.addLayout(row)

    @property
    def order(self) -> tuple[float, int]:
        return (self.at, self.seq)


class ChatThread(QWidget):
    """Luồng bong bóng của một máy (xem docstring module, “Luồng”, “Cuộn”, “Bàn phím”)."""

    unseen_changed = Signal(int)  # số bong bóng mới chưa thấy (0: đã ở cuối)

    def __init__(
        self,
        device_id: str,
        parent: QWidget | None = None,
        *,
        exit_next: Callable[[], QWidget | None] | None = None,
        exit_prev: Callable[[], QWidget | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("chatThread")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.device_id = device_id
        self.history_state = HistoryState.NONE
        self._items: list[_Item] = []
        self._current: Bubble | None = None
        self._pinned = True
        self._unseen = 0
        self._counted: set[Bubble] = set()  # bong bóng đang nằm trong số đếm “lượt mới”
        self._last_session_at = float("-inf")
        self._exit_next = exit_next
        self._exit_prev = exit_prev

        self._container = QWidget()
        self._container.setObjectName("chatThreadContent")
        self._container.setAutoFillBackground(False)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(_MARGIN, theme.SPACING[2], _MARGIN, theme.SPACING[2])
        self._layout.setSpacing(theme.SPACING[1])
        self.history_note = TimeSeparator(self._container)
        self.history_note.setVisible(False)
        self._layout.addWidget(self.history_note)
        self._layout.addStretch(1)

        self.scroll_area = QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Lề trên cố định của khung nhìn: cuộn tới đâu, bong bóng hay dòng mốc trên cùng cũng không dính
        # sát đường kẻ dưới đầu luồng.
        self.scroll_area.setViewportMargins(0, theme.SPACING[1], 0, 0)
        self.scroll_area.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll_area.setWidget(self._container)
        viewport = self.scroll_area.viewport()
        if viewport is not None:
            viewport.setAutoFillBackground(False)  # nền `surface` của khung phải
        self._container.setAutoFillBackground(False)
        bar = self.scroll_area.verticalScrollBar()
        bar.valueChanged.connect(self._on_scrolled)
        bar.rangeChanged.connect(self._on_range)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.scroll_area)

    # -- API ------------------------------------------------------------------------------------

    def bubbles(self) -> list[Bubble]:
        """Bong bóng (kể cả note clipboard) theo thứ tự hiển thị, cũ trên cùng."""
        return [item.bubble for item in self._items]

    def has_bubbles(self) -> bool:
        return bool(self._items)

    def bubble_for(self, key: TransferKey) -> Bubble | None:
        for item in self._items:
            bubble = item.bubble
            if isinstance(bubble, TransferBubble | HistoryBubble) and bubble.key == key:
                return bubble
        return None

    def keys(self) -> set[TransferKey]:
        """Khóa của mọi bong bóng có lượt (của phiên và lịch sử; bỏ bong bóng tạm và note clipboard)."""
        return {i.bubble.key for i in self._items if isinstance(i.bubble, TransferBubble | HistoryBubble)}

    def history_bubbles(self) -> list[HistoryBubble]:
        return [i.bubble for i in self._items if isinstance(i.bubble, HistoryBubble)]

    def separators(self) -> list[TimeSeparator]:
        """Các dòng mốc đang hiện, theo thứ tự (test)."""
        return [i.separator for i in self._items if not i.separator.isHidden()]

    def is_pinned(self) -> bool:
        return self._pinned

    def unseen(self) -> int:
        return self._unseen

    def scroll_to_bottom(self) -> None:
        """Cuộn xuống cuối, ghim lại và bỏ đếm “lượt mới”."""
        self._pinned = True
        bar = self.scroll_area.verticalScrollBar()
        bar.setValue(bar.maximum())
        self._set_unseen(0)

    def session_at(self) -> float:
        """`at` cho bong bóng mới của phiên: không bao giờ trước bong bóng phiên cuối (đồng hồ lùi)."""
        at = max(_wall_now(), self._last_session_at)
        self._last_session_at = at
        return at

    def add(self, bubble: Bubble, seq: int, *, new: bool) -> None:
        """Chèn `bubble` theo (`at`, `seq`); `new`: bong bóng mới của phiên (có thể bật “↓ Mới”)."""
        item = _Item(bubble, bubble.at, seq, self._container)
        index = bisect.bisect_right([i.order for i in self._items], item.order)
        self._items.insert(index, item)
        self._layout.insertWidget(index + 1, item.wrapper)
        bubble.installEventFilter(self)
        item.wrapper.show()
        now = _wall_now()
        for i in (index, index + 1):
            self._fix_separator(i, now)
        if new and index == len(self._items) - 1 and not self._pinned:
            self._counted.add(bubble)
            self._set_unseen(self._unseen + 1)

    def add_many(self, bubbles: Sequence[tuple[Bubble, int]]) -> None:
        """Chèn hàng loạt (lịch sử; không bật “↓ Mới”): ẩn nội dung trong lúc chèn để Qt không hiện,
        đánh bóng và sắp lại từng hàng; chữ mốc tính một lần sau khi chèn xong.

        Đang ghim thì `_on_range` giữ ở cuối; đang cuộn giữa chừng thì giữ nội dung đang xem: nhớ
        bong bóng đầu tiên còn trong khung và khoảng cách của nó tới mép trên, chèn xong thì dựng lại
        bố cục ngay (không chờ vòng lặp) và đặt lại `value` cho đúng khoảng cách đó."""
        if not bubbles:
            return
        container = self._container
        bar = self.scroll_area.verticalScrollBar()
        anchor: QWidget | None = None
        offset = 0
        if not self._pinned and container.isVisible():
            value = bar.value()
            # Neo vào chính bong bóng, không vào hàng bọc: dòng mốc phía trên nó có thể hiện/ẩn.
            anchor = next((it.bubble for it in self._items if it.wrapper.geometry().bottom() >= value), None)
            if anchor is not None:
                offset = anchor.mapTo(container, QPoint(0, 0)).y() - value
        focus = self.window().focusWidget()
        # Ẩn nội dung đang chứa tiêu điểm sẽ đẩy tiêu điểm đi: khi đó chỉ tắt vẽ lại.
        hide = container.isVisible() and not (focus is not None and container.isAncestorOf(focus))
        container.setUpdatesEnabled(False)
        if hide:
            container.hide()
        try:
            orders = [item.order for item in self._items]
            for bubble, seq in bubbles:
                item = _Item(bubble, bubble.at, seq, container)
                index = bisect.bisect_right(orders, item.order)
                orders.insert(index, item.order)
                self._items.insert(index, item)
                self._layout.insertWidget(index + 1, item.wrapper)
                bubble.installEventFilter(self)
                if not hide:
                    item.wrapper.show()
            self.refresh_separators()
        finally:
            if hide:
                container.show()
            container.setUpdatesEnabled(True)
        if anchor is not None:
            # Chạy ngay bố cục đang chờ (chỉ LayoutRequest, không DeferredDelete) để đọc vị trí mới của
            # bong bóng neo; an toàn trong slot: chỉ `resizeEvent` và signal thanh cuộn chạy lại.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            bar.setValue(anchor.mapTo(container, QPoint(0, 0)).y() - offset)

    def remove(self, bubble: Bubble) -> bool:
        """Gỡ `bubble` (không có → False); tính lại mốc của bong bóng đứng sau nó."""
        index = next((i for i, it in enumerate(self._items) if it.bubble is bubble), -1)
        if index < 0:
            return False
        item = self._items.pop(index)
        bubble.removeEventFilter(self)
        if self._current is bubble:
            self._current = None
        if bubble in self._counted:
            self._counted.discard(bubble)
            self._set_unseen(self._unseen - 1)
        self._layout.removeWidget(item.wrapper)
        item.wrapper.setParent(None)
        item.wrapper.deleteLater()
        self._fix_separator(index, _wall_now())
        return True

    def trim(self, limit: int) -> list[Bubble]:
        """Gỡ bong bóng đã kết thúc cũ nhất tới khi còn ≤ `limit`; không gỡ lượt đang chạy."""
        removed: list[Bubble] = []
        while len(self._items) > limit:
            victim = next((i.bubble for i in self._items if getattr(i.bubble, "finished", False)), None)
            if victim is None:
                break
            self.remove(victim)
            removed.append(victim)
        return removed

    def unload_history(self) -> bool:
        """Gỡ mọi `HistoryBubble`, đặt NONE; bong bóng của phiên giữ. True nếu có gỡ."""
        bubbles = self.history_bubbles()
        for bubble in bubbles:
            self.remove(bubble)
        self.history_state = HistoryState.NONE
        self.history_note.setVisible(False)
        return bool(bubbles)

    def set_history_failed(self) -> None:
        self.history_state = HistoryState.FAILED
        self.history_note.setText(QCoreApplication.translate("Chat", "Không đọc được lịch sử với máy này."))
        self.history_note.setVisible(True)

    def refresh_separators(self) -> None:
        """Tính lại chữ mọi dòng mốc (luồng hiện, đổi ngôn ngữ)."""
        now = _wall_now()
        for index in range(len(self._items)):
            self._fix_separator(index, now)
        if self.history_state is HistoryState.FAILED:
            self.history_note.setText(
                QCoreApplication.translate("Chat", "Không đọc được lịch sử với máy này.")
            )

    def focus_current(self, reason: Qt.FocusReason = Qt.FocusReason.OtherFocusReason) -> bool:
        """Đặt tiêu điểm vào bong bóng hiện hành (mặc định mới nhất); không có bong bóng → False."""
        if not self._items:
            return False
        current = self._current if self._current is not None else self._items[-1].bubble
        current.setFocus(reason)
        return True

    def current_bubble(self) -> Bubble | None:
        return self._current

    # -- Bên trong ------------------------------------------------------------------------------

    def _fix_separator(self, index: int, now: float) -> None:
        if not 0 <= index < len(self._items):
            return
        item = self._items[index]
        prev = self._items[index - 1].at if index > 0 else None
        shown = needs_separator(prev, item.at)
        if shown:
            item.separator.setText(separator_text(item.at, now))
        item.separator.setVisible(shown)

    def _set_unseen(self, count: int) -> None:
        count = max(count, 0)
        if count == 0:
            self._counted.clear()
        if count != self._unseen:
            self._unseen = count
            self.unseen_changed.emit(count)

    def _on_scrolled(self, value: int) -> None:
        bar = self.scroll_area.verticalScrollBar()
        self._pinned = value >= bar.maximum() - PIN_SLACK
        if self._pinned:
            self._set_unseen(0)

    def _on_range(self, _minimum: int, maximum: int) -> None:
        if self._pinned:
            self.scroll_area.verticalScrollBar().setValue(maximum)

    def _index_of(self, widget: QWidget | None) -> int:
        """Chỉ số của bong bóng chứa `widget` (chính nó hay con của nó); không có → -1."""
        while widget is not None and widget is not self:
            for index, item in enumerate(self._items):
                if item.bubble is widget:
                    return index
            widget = widget.parentWidget()
        return -1

    def _move_current(self, index: int) -> None:
        if not self._items:
            return
        index = min(max(index, 0), len(self._items) - 1)
        self._items[index].bubble.setFocus(Qt.FocusReason.OtherFocusReason)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if isinstance(watched, QWidget) and event.type() == QEvent.Type.FocusIn:
            index = self._index_of(watched)
            if index >= 0:
                self._current = self._items[index].bubble
                # Chỉ cuộn theo tiêu điểm khi điều hướng bằng phím (Tab/Backtab/Other từ
                # `_move_current`, `focus_current`); cửa sổ được kích hoạt lại, hộp thoại/menu đóng
                # hay bấm chuột không được giật khung cuộn khỏi chỗ đang đọc.
                if isinstance(event, QFocusEvent) and event.reason() in _SCROLL_FOCUS_REASONS:
                    self.scroll_area.ensureWidgetVisible(self._items[index].wrapper, 0, theme.SPACING[1])
        elif event.type() == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            key = event.key()
            index = self._index_of(watched if isinstance(watched, QWidget) else None)
            if (
                index >= 0
                and key in _NAV_KEYS
                and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
            ):
                target = {
                    Qt.Key.Key_Up: index - 1,
                    Qt.Key.Key_Down: index + 1,
                    Qt.Key.Key_Home: 0,
                    Qt.Key.Key_End: len(self._items) - 1,
                    Qt.Key.Key_PageUp: index - _PAGE_STEP,
                    Qt.Key.Key_PageDown: index + _PAGE_STEP,
                }[Qt.Key(key)]
                self._move_current(target)
                return True
        return super().eventFilter(watched, event)

    def focusNextPrevChild(self, next: bool) -> bool:
        focus = self.window().focusWidget()
        index = self._index_of(focus)
        if index < 0:
            return super().focusNextPrevChild(next)
        bubble = self._items[index].bubble
        chain: list[QWidget] = [bubble, *bubble.focus_buttons()]
        position = chain.index(focus) if focus in chain else 0
        step = 1 if next else -1
        if 0 <= position + step < len(chain):
            reason = Qt.FocusReason.TabFocusReason if next else Qt.FocusReason.BacktabFocusReason
            chain[position + step].setFocus(reason)
            return True
        exit_to = self._exit_next if next else self._exit_prev
        target = exit_to() if exit_to is not None else None
        if target is not None:
            target.setFocus(Qt.FocusReason.TabFocusReason if next else Qt.FocusReason.BacktabFocusReason)
            return True
        return super().focusNextPrevChild(next)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self.refresh_separators()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.refresh_separators()


class _ThreadStack(QStackedWidget):
    """`threads`: điểm dừng Tab duy nhất của luồng; nhận tiêu điểm thì chuyển sang bong bóng hiện hành."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatThreads")
        # Chỉ Tab, không ClickFocus: bấm thanh cuộn hay chỗ trống trong luồng không được kéo tiêu điểm
        # về đây (focusInEvent sẽ cuộn tới bong bóng hiện hành, giật khung cuộn khỏi chỗ đang đọc).
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        if event.reason() is Qt.FocusReason.MouseFocusReason:
            return
        thread = self.currentWidget()
        if isinstance(thread, ChatThread):
            thread.focus_current(event.reason())


# ---- Đầu luồng, thanh dưới, lớp thả -------------------------------------------------------------


class ChatHeader(QWidget):
    """Đầu luồng: avatar, tên máy, dòng trạng thái; đường kẻ dưới 1 px `border`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatHeader")
        self.avatar = DeviceAvatar(self, diameter=_AVATAR, presence=Presence.OFFLINE, ring="surface")
        self.name_label = QLabel(self)
        self.name_label.setTextFormat(Qt.TextFormat.PlainText)
        self.name_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.name_label.font()))
        self.status_label = QLabel(self)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.status_label.font()))
        self.status_label.setProperty(theme.TONE_PROPERTY, "muted")
        for label in (self.name_label, self.status_label):
            label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.name_label)
        column.addWidget(self.status_label)
        self.action_row = QHBoxLayout()  # chỗ cho nút đầu luồng (B3c)
        self.action_row.setContentsMargins(0, 0, 0, 0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(_MARGIN, theme.SPACING[2], _MARGIN, theme.SPACING[2])
        layout.setSpacing(theme.SPACING[2])
        layout.addWidget(self.avatar, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(column, 1)
        layout.addLayout(self.action_row)

    def set_device(self, name: str, status: str, presence: Presence) -> None:
        self.name_label.setText(name)
        self.status_label.setText(status)
        self.status_label.setVisible(bool(status))
        self.avatar.set_presence(presence)
        self.setAccessibleName(f"{name}. {status}" if status else name)

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(0, self.height() - 1, self.width(), 1, theme.tokens_for(self).border)
        finally:
            painter.end()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()


class ChatComposer(QWidget):
    """Thanh dưới luồng: nút “Gửi file” và câu gợi ý; đường kẻ trên 1 px `border`."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatComposer")
        self.send_button = IconButton(
            "attach",
            QCoreApplication.translate("Chat", "Gửi file"),
            self,
            shortcut=shortcuts.sequence(Shortcut.PICK_FILES),
            show_text=True,
        )
        self.send_button.setObjectName("chatSendButton")
        self.hint_icon = QLabel(self)
        self.hint_icon.setFixedSize(_ICON, _ICON)
        self.hint_icon.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hint_icon.setVisible(False)
        self.hint_label = QLabel(self)
        self.hint_label.setTextFormat(Qt.TextFormat.PlainText)
        self.hint_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.hint_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.hint_label.font()))
        self.hint_label.setWordWrap(True)
        self.hint_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.hint_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._offline = False
        layout = QHBoxLayout(self)
        layout.setContentsMargins(_MARGIN, theme.SPACING[1] + 2, _MARGIN, theme.SPACING[1] + 2)
        layout.setSpacing(theme.SPACING[2])
        layout.addWidget(self.send_button, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.hint_icon, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.hint_label, 1)

    @property
    def offline(self) -> bool:
        return self._offline

    def set_hint(self, text: str, *, offline: bool) -> None:
        self._offline = offline
        self.hint_label.setText(text)
        self.hint_label.setAccessibleName(text)
        align = Qt.AlignmentFlag.AlignLeft if offline else Qt.AlignmentFlag.AlignRight
        self.hint_label.setAlignment(align | Qt.AlignmentFlag.AlignVCenter)
        self.hint_icon.setVisible(offline)
        self._refresh_icon()
        # Trình đọc màn hình: nút “Gửi file” nói luôn máy kia đang ngoại tuyến.
        self.send_button.setAccessibleDescription(text if offline else "")

    def _refresh_icon(self) -> None:
        if self._offline:
            color = theme.tokens_for(self).text_muted
            self.hint_icon.setPixmap(icons.pixmap("cloud_off", _ICON, color, self.devicePixelRatioF()))

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            painter.fillRect(0, 0, self.width(), 1, theme.tokens_for(self).border)
        finally:
            painter.end()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (*_PALETTE_EVENTS, QEvent.Type.DevicePixelRatioChange):
            self._refresh_icon()
            self.update()


class _DropOverlay(QWidget):
    """Lớp phủ khi đang kéo file vào luồng: viền nét đứt 2 px `accent_strong`, câu giữa vùng."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("chatDropOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.label = QLabel(self)
        self.label.setTextFormat(Qt.TextFormat.PlainText)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setWordWrap(True)
        self.label.setProperty(theme.TONE_PROPERTY, "accent")
        self.label.setFont(theme.font_for(theme.TextStyle.SECTION, self.label.font()))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(_MARGIN * 2, _MARGIN * 2, _MARGIN * 2, _MARGIN * 2)
        layout.addWidget(self.label)
        self.setVisible(False)

    def text(self) -> str:
        return self.label.text() if not self.isHidden() else ""

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_for(self)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            background = t.surface
            background.setAlphaF(0.88)
            painter.setBrush(background)
            pen = QPen(t.accent_strong, 2)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            rect = QRectF(self.rect()).adjusted(_MARGIN / 2, _MARGIN / 2, -_MARGIN / 2, -_MARGIN / 2)
            painter.drawRoundedRect(rect, theme.RADIUS_BLOCK, theme.RADIUS_BLOCK)
        finally:
            painter.end()


# ---- ChatView -----------------------------------------------------------------------------------


class ChatView(QWidget):
    """Khung phải: thông báo, đầu luồng, luồng của máy đang chọn, thanh dưới (xem docstring module)."""

    cancel_requested = Signal(object)  # TransferKey
    resend_requested = Signal(object)  # TransferKey
    pick_files_requested = Signal(str)  # nút “Gửi file”, phím Chọn file
    send_files_requested = Signal(str, list)  # thả hay dán vào luồng: device_id, list[Path]
    drop_hint_requested = Signal(str)  # thả hay dán khi chưa chọn máy
    clipboard_settings_requested = Signal(str)  # “Mở Cài đặt” của gợi ý khi dán không phải file
    history_needed = Signal(str)  # mở luồng mà chưa có lịch sử (sau HISTORY_DEBOUNCE_MS)
    change_receive_dir_requested = Signal()  # nút “Đổi thư mục nhận” của bong bóng nhận (spec D4)
    retry_clipboard_requested = Signal(str)  # “Thử lại” của note clipboard: device_id (mvp F8)
    content_changed = Signal()
    offer_answer_requested = Signal(object, bool)  # TransferKey, accept: Nhận / Từ chối ở panel
    offer_always_toggled = Signal(object, bool)  # TransferKey, on: ô “Luôn nhận” ở panel
    change_receive_dir_requested = Signal()  # “Đổi…” ở panel

    def __init__(self, devices: DeviceListModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("chatView")
        self.setAcceptDrops(True)
        self._devices = devices
        self._device_id: str | None = None
        self._threads: dict[str, ChatThread] = {}
        self._bubbles: dict[TransferKey, TransferBubble] = {}
        self._pending: dict[int, tuple[str, PendingBubble]] = {}
        self._clip_notes: dict[str, ClipboardNote] = {}  # device_id → note clipboard mới nhất
        # device_id → các note đã bấm “Thử lại”, đang chờ kết quả, theo thứ tự bấm
        self._clip_retrying: dict[str, list[ClipboardNote]] = {}
        self._next_token = 1
        self._seq = 0
        self._names: dict[str, str | None] = {}
        self._connected: dict[str, bool] = {}
        self._receive_dir: Path | None = None
        self._receive_dir_pending: Path | None = None
        self._offer_book: OfferBook | None = None
        self._notice_callback: Callable[[], None] | None = None
        self._notice_sources: tuple[texts.Text, texts.Text | None] = ("", None)  # câu đang hiện
        self._notice_language = ""  # ngôn ngữ lúc hiện câu đang có
        self._change_depth = 0
        self._changed = False

        # Dựng theo thứ tự Tab (spec B3 mục 9.10): info_bar → empty_state → threads → new_button → nút gửi.
        self.info_bar = InfoBar(self)
        self.info_bar.setObjectName("chatInfoBar")
        self.info_bar.action_triggered.connect(self._on_notice_action)
        self.info_bar.dismissed.connect(self._on_notice_dismissed)
        self.header = ChatHeader(self)
        self.threads = _ThreadStack(self)
        self.placeholder = QLabel(self.threads)
        self.placeholder.setObjectName("chatPlaceholder")
        self.placeholder.setTextFormat(Qt.TextFormat.PlainText)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setWordWrap(True)
        self.placeholder.setProperty(theme.TONE_PROPERTY, "muted")
        self.placeholder.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.placeholder.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        self.empty_state = EmptyState(self.threads)
        self.empty_state.setObjectName("chatEmpty")
        self.threads.addWidget(self.placeholder)
        self.threads.addWidget(self.empty_state)
        self.new_button = IconButton(
            "arrow_down", QCoreApplication.translate("Chat", "Mới"), self, show_text=True
        )
        self.new_button.setObjectName("chatNewButton")
        self.new_button.setVisible(False)
        self.new_button.clicked.connect(self._on_new_clicked)
        self.composer = ChatComposer(self)
        self.composer.send_button.clicked.connect(self._request_pick)
        self._drop_overlay = _DropOverlay(self)

        info_wrap = QVBoxLayout()
        info_wrap.setContentsMargins(_MARGIN, theme.SPACING[2], _MARGIN, 0)
        info_wrap.addWidget(self.info_bar)
        new_row = QHBoxLayout()
        new_row.setContentsMargins(0, theme.SPACING[0], 0, theme.SPACING[0])
        new_row.addStretch(1)
        new_row.addWidget(self.new_button)
        new_row.addStretch(1)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(info_wrap)
        layout.addWidget(self.header)
        layout.addWidget(self.threads, 1)
        layout.addLayout(new_row)
        layout.addWidget(self.composer)

        info = self.info_bar
        chain: list[QWidget] = [
            info.title_label,
            info.text_label,
            info.action_button,
            info.close_button,
            self.empty_state.title_label,
            self.empty_state.text_label,
            self.threads,
            self.new_button,
            self.composer.send_button,
        ]
        for first, second in pairwise(chain):
            QWidget.setTabOrder(first, second)

        self._pick_action = shortcuts.make_action(self, Shortcut.PICK_FILES, self._on_pick_shortcut)
        self._paste_action = shortcuts.make_action(self, Shortcut.PASTE_FILES, self._on_paste_shortcut)

        self._history_timer = QTimer(self)
        self._history_timer.setSingleShot(True)
        self._history_timer.setInterval(HISTORY_DEBOUNCE_MS)
        self._history_timer.timeout.connect(self._request_history)

        for signal in (
            devices.dataChanged,
            devices.rowsInserted,
            devices.rowsRemoved,
            devices.rowsMoved,
            devices.modelReset,
            devices.layoutChanged,
        ):
            signal.connect(self._on_devices_changed)
        self.retranslate()
        self._update_page()

    # ---- Máy đang chọn --------------------------------------------------------------------------

    def device_id(self) -> str | None:
        return self._device_id

    def set_device(self, device_id: str | None) -> None:
        """Mở luồng của `device_id` (None: không máy nào); rời luồng cũ thì gỡ lịch sử của nó."""
        with self._changes():
            old = self._device_id
            if old is not None and old != device_id:
                thread = self._threads.get(old)
                if thread is not None and thread.unload_history():
                    self._mark_changed()
            self._device_id = device_id
            self._mark_changed()
            if device_id is not None:
                thread = self._thread(device_id)
                thread.scroll_to_bottom()
                self._schedule_history()
            else:
                self._history_timer.stop()
            self._update_header()
            self._update_page()

    def focus_composer(self) -> None:
        """Tiêu điểm vào nút “Gửi file” (Enter / bấm đúp ở cột trái)."""
        self.composer.send_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def thread_for(self, device_id: str) -> ChatThread | None:
        return self._threads.get(device_id)

    # ---- Lượt truyền (API cũ) -------------------------------------------------------------------

    def rows(self) -> list[TransferBubble]:
        """Bong bóng của phiên ở mọi luồng, cũ trước (theo `at`, rồi thứ tự tạo)."""
        return sorted(self._bubbles.values(), key=lambda b: (b.at, self._bubble_seq(b)))

    def row(self, key: TransferKey) -> TransferBubble | None:
        """Bong bóng **của phiên** cho `key` (không tính `HistoryBubble`)."""
        return self._bubbles.get(key)

    def has_content(self) -> bool:
        """Thông báo đang hiện hay đang chọn một máy (đúng cả khi cửa sổ đang ẩn xuống khay)."""
        return not self.info_bar.isHidden() or self._device_id is not None

    def active_count(self) -> int:
        """Số bong bóng của phiên chưa kết thúc, ở mọi luồng."""
        return sum(1 for bubble in self._bubbles.values() if not bubble.finished)

    def set_resendable(self, key: TransferKey, on: bool) -> None:
        bubble = self._bubbles.get(key)
        if bubble is not None:
            bubble.set_resendable(on)

    def set_device_names(self, names: Mapping[str, str | None]) -> None:
        """Bảng tên máy (device_id → tên từ `devices()`); vẽ lại chữ các bong bóng và đầu luồng."""
        self._names = dict(names)
        for bubble in self._bubbles.values():
            bubble.render_status()
        for thread in self._threads.values():
            peer = self._peer(thread.device_id, None)
            for history in thread.history_bubbles():
                history.set_peer(peer)
        for device_id, note in self._clip_notes.items():
            note.set_peer(self._peer(device_id, None))
        self._update_header()

    def set_connected(self, device_id: str, connected: bool) -> None:
        """Máy có kết nối điều khiển hay không (câu chờ của lượt gửi)."""
        self._connected[device_id] = connected
        for bubble in self._bubbles.values():
            if bubble.key.device_id == device_id and not bubble.finished:
                bubble.render_status()

    def set_receive_dir(self, receive_dir: Path | None) -> None:
        """Thư mục nhận: câu lỗi của bên nhận đang chạy, nút “Đổi thư mục nhận” của bong bóng đã kết
        thúc, luật “Mở thư mục” UNC của mục lịch sử, dòng “Lưu vào” của panel lời mời."""
        self._receive_dir = receive_dir
        for transfer in self._bubbles.values():
            transfer.set_current_receive_dir(receive_dir)
        for thread in self._threads.values():
            for bubble in thread.history_bubbles():
                bubble.set_receive_dir(receive_dir)
        self._update_offer_dirs()

    def set_receive_dir_pending(self, path: Path | None) -> None:
        """Thư mục nhận đang đổi sang (None: không đổi): panel lời mời tắt “Nhận” và “Đổi…”."""
        self._receive_dir_pending = path
        self._update_offer_dirs()

    def _update_offer_dirs(self) -> None:
        for bubble in self._bubbles.values():
            bubble.set_offer_dir(self._receive_dir, self._receive_dir_pending)

    def is_pinned(self, device_id: str) -> bool:
        """Luồng của `device_id` đang ở cuối (chưa dựng → True)."""
        thread = self._threads.get(device_id)
        return True if thread is None else thread.is_pinned()

    # ---- Lời mời nhận file ----------------------------------------------------------------------

    def set_offer_book(self, book: OfferBook) -> None:
        """Nối các lời mời của `book` vào bong bóng (xem docstring module, “Lời mời nhận file”)."""
        old = self._offer_book
        if old is book:
            return
        if old is not None:
            for signal, slot in (
                (old.added, self._on_offer_added),
                (old.changed, self._on_offer_changed),
                (old.removed, self._on_offer_removed),
            ):
                with contextlib.suppress(RuntimeError, TypeError):
                    signal.disconnect(slot)
        self._offer_book = book
        book.added.connect(self._on_offer_added)
        book.changed.connect(self._on_offer_changed)
        book.removed.connect(self._on_offer_removed)

    def _apply_offer(self, bubble: TransferBubble, key: TransferKey) -> None:
        book = self._offer_book
        entry = None if book is None else book.entry(key)
        if bubble.set_offer(entry, self._receive_dir, self._receive_dir_pending):
            self._mark_changed()

    def _on_offer_added(self, key: TransferKey) -> None:
        with self._changes():
            bubble = self._ensure(key)
            self._apply_offer(bubble, key)
        if bubble.offer_panel is not None and key.device_id == self._device_id and self.isVisible():
            # Trình đọc màn hình báo có lời mời mới, không cướp tiêu điểm.
            with contextlib.suppress(Exception):
                QAccessible.updateAccessibility(QAccessibleEvent(bubble, QAccessible.Event.Alert))

    def _on_offer_changed(self, key: TransferKey) -> None:
        bubble = self._bubbles.get(key)
        if bubble is not None:
            with self._changes():
                self._apply_offer(bubble, key)

    def _on_offer_removed(self, key: TransferKey) -> None:
        bubble = self._bubbles.get(key)
        if bubble is not None:
            with self._changes():
                if bubble.set_offer(None):
                    self._mark_changed()

    def _offer_answer(self, bubble: TransferBubble, accept: bool) -> None:
        if self._bubbles.get(bubble.key) is bubble:
            self.offer_answer_requested.emit(bubble.key, bool(accept))

    def _offer_always(self, bubble: TransferBubble, on: bool) -> None:
        if self._bubbles.get(bubble.key) is bubble:
            self.offer_always_toggled.emit(bubble.key, bool(on))

    def load_snapshot(self, infos: Iterable[TransferInfo]) -> None:
        """Ảnh chụp `transfers()`: thêm bong bóng cho lượt chưa có, bong bóng đã có giữ nguyên."""
        with self._changes():
            self._mark_changed()
            for info in infos:
                if info.key in self._bubbles:
                    continue
                bubble = self._add_bubble(info.key)
                bubble.set_info(info)
                bubble.raise_shown(info.done_bytes + info.unsynced_bytes, info.total_bytes)
                bubble.refresh_text()

    def remove(self, key: TransferKey) -> None:
        """Gỡ bong bóng của `key` (không có → bỏ qua). Sự kiện tới sau sẽ dựng lại: bên gọi tự lọc."""
        with self._changes():
            self._mark_changed()
            bubble = self._bubbles.pop(key, None)
            if bubble is None:
                return
            thread = self._threads.get(key.device_id)
            if thread is not None:
                thread.remove(bubble)
            self._update_page()

    def clear(self) -> None:
        """Xóa mọi luồng, bong bóng (kể cả tạm), thông báo, trạng thái kết nối (host mới)."""
        with self._changes():
            self._mark_changed()
            self.hide_notice()
            self._connected.clear()
            self._bubbles.clear()
            self._pending.clear()
            self._clip_notes.clear()
            self._clip_retrying.clear()
            for thread in self._threads.values():
                self.threads.removeWidget(thread)
                thread.setParent(None)
                thread.deleteLater()
            self._threads.clear()
            self._set_new_count(0)
            if self._device_id is not None:
                self._thread(self._device_id)
                self._schedule_history()
            self._update_page()

    def handle(self, update: TransferUpdate) -> None:
        """Nhận một `TransferUpdate` của node (đã về thread Qt), định tuyến theo máy."""
        with self._changes():
            self._handle(update)

    def _handle(self, update: TransferUpdate) -> None:
        if isinstance(update, TransferProgress):
            bubble = self._bubbles.get(update.info.key)
            if bubble is None:
                bubble = self._add_bubble(update.info.key)
                bubble.set_info(update.info)
                bubble.refresh_text()
            bubble.apply_progress(update)
        elif isinstance(update, TransferStatusChanged):
            self._ensure(update.info.key).apply_status(update.info)
        elif isinstance(update, OfferReceived):
            self._ensure(update.key).apply_offer(update)
        elif isinstance(update, FileDone):
            existing = self._bubbles.get(update.key)
            if existing is not None:
                existing.apply_file_done(update)
        elif isinstance(update, TransferFinished):
            if update.result is TransferResult.SUSPENDED:
                return  # chỉ khi host dừng: giữ bong bóng như cũ
            bubble = self._ensure(update.info.key)
            if bubble.finish(update):
                self._mark_changed()
                self._trim(update.info.key.device_id)
        elif isinstance(update, TransferResumed):
            self._ensure(update.info.key).apply_resumed(update.info)
        elif isinstance(update, DataUnreachable):
            for bubble in self._bubbles.values():
                if bubble.key.device_id == update.device_id:
                    bubble.apply_unreachable()

    # ---- Bong bóng tạm “Đang chuẩn bị…” ---------------------------------------------------------

    def add_pending(self, device_id: str, paths: Sequence[Path]) -> int:
        """Hiện bong bóng tạm cho lần gửi `paths` tới `device_id`; trả mã tạm (tăng dần)."""
        with self._changes():
            token = self._next_token
            self._next_token += 1
            thread = self._thread(device_id)
            names = [path.name or str(path) for path in paths]
            bubble = PendingBubble(token, names, at=thread.session_at())
            self._pending[token] = (device_id, bubble)
            thread.add(bubble, self._next_seq(), new=True)
            self._mark_changed()
            self._update_page()
            return token

    def remove_pending(self, token: int) -> None:
        """Gỡ bong bóng tạm `token` (không có → bỏ qua)."""
        with self._changes():
            entry = self._pending.pop(token, None)
            if entry is None:
                return
            device_id, bubble = entry
            thread = self._threads.get(device_id)
            if thread is not None:
                thread.remove(bubble)
            self._mark_changed()
            self._update_page()

    def pending_bubbles(self) -> list[PendingBubble]:
        return [bubble for _, bubble in self._pending.values()]

    # ---- Clipboard (mvp F8) --------------------------------------------------------------------

    def show_clipboard(
        self,
        device_id: str,
        *,
        ok: bool,
        kind: ClipKind | str | None,
        size: int,
        preview: str | None = None,
        image_size: tuple[int, int] | None = None,
    ) -> ClipboardNote:
        """Note clipboard mới nhất của `device_id` (`ok`: đã chép vào máy này); thay note cũ của luồng đó."""
        with self._changes():
            thread = self._thread(device_id)
            old = self._clip_notes.pop(device_id, None)
            focus = self.window().focusWidget()
            had_focus = old is not None and focus is not None and (focus is old or old.isAncestorOf(focus))
            if old is not None:
                thread.remove(old)
            note = ClipboardNote(
                device_id,
                ok=ok,
                kind=kind,
                size=size,
                preview=preview,
                image_size=image_size,
                peer=self._peer(device_id, None),
                at=thread.session_at(),
            )
            note.retry_clicked.connect(lambda n=note: self._clipboard_retry_clicked(n))
            self._clip_notes[device_id] = note
            thread.add(note, self._next_seq(), new=True)
            self._mark_changed()
            self._update_page()
            if had_focus:  # tiêu điểm đang ở note cũ: sang note mới, không rơi khỏi luồng
                note.setFocus(Qt.FocusReason.OtherFocusReason)
            return note

    def clipboard_note(self, device_id: str) -> ClipboardNote | None:
        """Note clipboard đang hiện trong luồng của `device_id` (không có → None)."""
        return self._clip_notes.get(device_id)

    def finish_clipboard_retry(self, device_id: str, *, available: bool) -> None:
        """Kết quả “Thử lại”: False (`NOTHING_TO_RETRY`) → câu “không còn để chép lại”; True → bật lại nút
        (kết quả RECEIVED / WRITE_FAILED đã tới bằng `show_clipboard`).

        Kết quả thuộc lần bấm cũ nhất còn chờ của máy đó; note của lần bấm ấy đã bị note mới thay thì bỏ
        (không áp lên note mới)."""
        waiting = self._clip_retrying.get(device_id)
        if not waiting:
            return
        note = waiting.pop(0)
        if not waiting:
            del self._clip_retrying[device_id]
        if self._clip_notes.get(device_id) is not note:
            return
        if available:
            note.set_busy(False)
        else:
            note.set_unavailable()

    def _clipboard_retry_clicked(self, note: ClipboardNote) -> None:
        if self._clip_notes.get(note.device_id) is not note or note.ok or note.unavailable:
            return
        note.set_busy(True)
        self._clip_retrying.setdefault(note.device_id, []).append(note)
        self.retry_clipboard_requested.emit(note.device_id)

    # ---- Lịch sử --------------------------------------------------------------------------------

    def load_history(self, device_id: str, entries: Sequence[HistoryEntry]) -> None:
        """Lịch sử của `device_id` (mới nhất trước hay bất kỳ thứ tự); chỉ áp khi luồng đang mở và đang
        LOADING. Mục trùng khóa với bất kỳ bong bóng nào bị bỏ."""
        thread = self._threads.get(device_id)
        if device_id != self._device_id or thread is None or thread.history_state is not HistoryState.LOADING:
            return
        with self._changes():
            peer = self._peer(device_id, None)
            seen = thread.keys()
            fresh: list[HistoryEntry] = []
            for entry in entries:
                if not isinstance(entry, HistoryEntry) or entry.device_id != device_id:
                    continue
                key = TransferKey(entry.device_id, entry.direction, entry.transfer_id)
                if key in seen:
                    continue  # trùng khóa với bong bóng đã có (của phiên hay lịch sử)
                seen.add(key)
                fresh.append(entry)
            # Chỉ dựng phần còn chỗ dưới `MAX_THREAD_BUBBLES` (mới nhất trước): mục cũ hơn sẽ bị `_trim`
            # gỡ ngay, mà gỡ ở phía trên chỗ neo của `add_many` thì luồng đang cuộn lên bị kéo xuống cuối.
            room = max(0, MAX_THREAD_BUBBLES - len(thread.bubbles()))
            fresh.sort(key=lambda e: e.finished_at, reverse=True)
            batch: list[tuple[Bubble, int]] = []
            for entry in fresh[:room]:
                bubble = HistoryBubble(entry, peer=peer, receive_dir=self._receive_dir)
                bubble.open_clicked.connect(lambda b=bubble: self._open_history(b))
                batch.append((bubble, self._next_seq()))
            if batch:
                thread.add_many(batch)
                self._mark_changed()
            thread.history_state = HistoryState.LOADED
            self._trim(device_id)
            self._update_page()

    def history_failed(self, device_id: str) -> None:
        """Không đọc được lịch sử của `device_id`: dòng mờ ở đầu luồng."""
        thread = self._threads.get(device_id)
        if device_id != self._device_id or thread is None or thread.history_state is not HistoryState.LOADING:
            return
        thread.set_history_failed()
        self._update_page()

    def invalidate_history(self, device_id: str | None) -> None:
        """Gỡ lịch sử của một máy (None: mọi máy), đặt NONE; luồng đang mở thì nạp lại."""
        with self._changes():
            for thread_id, thread in self._threads.items():
                if (device_id is None or thread_id == device_id) and thread.unload_history():
                    self._mark_changed()
            if self._device_id is not None and device_id in (None, self._device_id):
                self._schedule_history()
            self._update_page()

    # ---- Thông báo ------------------------------------------------------------------------------

    def show_notice(
        self,
        text: texts.Text,
        action_text: texts.Text | None = None,
        on_action: Callable[[], None] | None = None,
        *,
        level: InfoLevel = InfoLevel.INFO,
    ) -> None:
        """Hiện `text` ở `info_bar` (thay thông báo cũ); rỗng → ẩn. `action_text` và `on_action` cùng có
        → nút hành động; bấm thì ẩn thông báo rồi gọi `on_action`.

        `text`, `action_text` là `texts.Text`: đổi ngôn ngữ thì câu dựng bằng hàm được dịch lại, câu dịch
        sẵn (chuỗi) thì thanh bị ẩn, không còn câu của ngôn ngữ cũ (như `widgets.InfoBar`)."""
        with self._changes():
            self._mark_changed()
            if not texts.resolve(text):
                self.hide_notice()
                return
            has_action = bool(action_text) and on_action is not None
            self._notice_callback = on_action if has_action else None
            self._notice_sources = (text, action_text if has_action else None)
            self._notice_language = i18n.current_language()
            self.info_bar.show_message(level, text, action=action_text if has_action else None)
            self._apply_notice_accessibility()

    def _apply_notice_accessibility(self) -> None:
        """Tên/mô tả trợ năng cho các ô nhận Tab của thanh (InfoBar chỉ đặt tên cho chính nó)."""
        source, action_source = self._notice_sources
        text = texts.resolve(source)
        action_text = texts.resolve(action_source) if action_source else ""
        bar = self.info_bar
        bar.title_label.setAccessibleName(QCoreApplication.translate("Chat", "Thông báo"))
        bar.title_label.setAccessibleDescription(text)
        bar.action_button.setAccessibleName(action_text)
        bar.action_button.setAccessibleDescription(text if action_text else "")

    def _retranslate_notice(self) -> None:
        """Sau `LanguageChange`: câu dựng bằng hàm thì dịch lại tên trợ năng (chữ do `InfoBar` tự dịch);
        câu dịch sẵn của ngôn ngữ cũ thì ẩn thông báo (`InfoBar` cũng tự ẩn, thứ tự sự kiện không quan
        trọng)."""
        language = i18n.current_language()
        if not self._notice_sources[0] or self._notice_language == language:
            return
        if all(callable(source) or not source for source in self._notice_sources):
            self._notice_language = language
            self._apply_notice_accessibility()
        else:
            self.hide_notice()

    def hide_notice(self) -> None:
        with self._changes():
            self._mark_changed()
            self._notice_callback = None
            self._notice_sources = ("", None)
            self.info_bar.clear()

    def notice_text(self) -> str:
        """Chữ của thông báo đang hiện; không có → “”."""
        return self.info_bar.title if not self.info_bar.isHidden() else ""

    def notice_action_text(self) -> str | None:
        """Chữ của nút hành động của thông báo đang hiện; không có → None."""
        if not self.notice_text() or self.info_bar.action_button.isHidden():
            return None
        return self.info_bar.action_button.text()

    @property
    def notice_action(self) -> QWidget:
        return self.info_bar.action_button

    @property
    def notice_label(self) -> QLabel:
        return self.info_bar.title_label

    # ---- Thả file -------------------------------------------------------------------------------

    def preview_drop(self, count: int | None) -> None:
        """Hiện lớp thả như đang kéo `count` file (None: ẩn); cùng đường với kéo thật."""
        if count is None or self._device_id is None:
            self._drop_overlay.setVisible(False)
            return
        name = self._peer(self._device_id, None)
        self._drop_overlay.label.setText(
            texts.fill(
                QCoreApplication.translate("Chat", "Thả để gửi %n file tới {name}", None, max(0, count)),
                name=name,
            )
        )
        self._drop_overlay.setGeometry(self.threads.geometry())
        self._drop_overlay.raise_()
        self._drop_overlay.setVisible(True)

    @property
    def drop_overlay(self) -> _DropOverlay:
        return self._drop_overlay

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        paths = _event_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.preview_drop(len(paths))

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if _event_paths(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self.preview_drop(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self.preview_drop(None)
        paths = _event_paths(event)
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        self.drop_paths(paths)

    def drop_paths(self, paths: list[Path]) -> bool:
        """Thả (hay dán) `paths` vào luồng đang mở; True nếu đã phát `send_files_requested`.

        Chưa chọn máy → gợi ý thả; máy có trong model mà không gửi tới được → bỏ qua."""
        if not paths:
            return False
        device_id = self._device_id
        if device_id is None:
            self.drop_hint_requested.emit(drop_hint_text())
            return False
        view = self._devices.device(device_id)
        if view is not None and not can_receive_files(view):
            return False
        self.send_files_requested.emit(device_id, list(paths))
        return True

    # ---- Dán file -------------------------------------------------------------------------------

    def paste_from_clipboard(self) -> PasteOutcome | None:
        """Dán file đã chép (phím Dán): `ChatView` không hiện → None; còn lại `paste_mime` với nội
        dung clipboard."""
        if not self.isVisible():
            return None
        return self.paste_mime(_clipboard_mime())

    def paste_mime(self, mime: QMimeData | None) -> PasteOutcome:
        """Gửi các file trong `mime` tới máy đang chọn (xem docstring module, “Dán file”)."""
        device_id = self._device_id
        if device_id is None:
            self.drop_hint_requested.emit(paste_no_device_text())
            return PasteOutcome.NO_DEVICE
        paths = send.clipboard_paths(mime)
        if not paths:
            self.show_notice(
                lambda: paste_not_files_text(self._peer(device_id, None)),
                paste_settings_text,
                lambda: self.clipboard_settings_requested.emit(device_id),
                level=InfoLevel.INFO,
            )
            return PasteOutcome.NOT_FILES
        return PasteOutcome.SENT if self.drop_paths(paths) else PasteOutcome.BLOCKED

    # ---- Chữ ------------------------------------------------------------------------------------

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        self.setAccessibleName(t("Chat", "Lượt gửi nhận"))
        self.placeholder.setText(t("Chat", "Chọn một máy ở cột trái để xem file đã gửi và nhận."))
        self.composer.send_button.set_label(t("Chat", "Gửi file"))
        shortcuts.retranslate_actions(self)
        self.threads.setAccessibleName(t("Chat", "Lượt gửi nhận"))
        self._set_new_count(self._new_count(), force=True)
        self._update_header()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
            self._retranslate_notice()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Ví dụ từ trang Cài đặt về HOME: nạp lại lịch sử của luồng đang mở (bong bóng đã có giữ nguyên).
        thread = self._current_thread()
        if thread is not None and thread.history_state in (HistoryState.LOADED, HistoryState.FAILED):
            thread.history_state = HistoryState.NONE
            thread.history_note.setVisible(False)
            self._schedule_history()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        if not self._drop_overlay.isHidden():
            self._drop_overlay.setGeometry(self.threads.geometry())

    # ---- Bên trong ------------------------------------------------------------------------------

    @contextmanager
    def _changes(self) -> Iterator[None]:
        """Gộp thay đổi: `content_changed` phát đúng một lần khi lời gọi ngoài cùng xong, nếu có đổi."""
        self._change_depth += 1
        try:
            yield
        finally:
            self._change_depth -= 1
            if self._change_depth == 0 and self._changed:
                self._changed = False
                self.content_changed.emit()

    def _mark_changed(self) -> None:
        if self._change_depth:
            self._changed = True
        else:
            self.content_changed.emit()

    def _next_seq(self) -> int:
        self._seq += 1
        return self._seq

    def _bubble_seq(self, bubble: TransferBubble) -> int:
        return int(bubble.property("teleport_seq") or 0)

    def _thread(self, device_id: str) -> ChatThread:
        thread = self._threads.get(device_id)
        if thread is None:
            thread = ChatThread(
                device_id,
                self.threads,
                exit_next=self._focus_after_thread,
                exit_prev=self._focus_before_thread,
            )
            thread.unseen_changed.connect(lambda count, i=device_id: self._on_unseen(i, count))
            self._threads[device_id] = thread
            self.threads.addWidget(thread)
            self._apply_thread_names(thread)
        return thread

    def _current_thread(self) -> ChatThread | None:
        return None if self._device_id is None else self._threads.get(self._device_id)

    def _ensure(self, key: TransferKey) -> TransferBubble:
        bubble = self._bubbles.get(key)
        return bubble if bubble is not None else self._add_bubble(key)

    def _add_bubble(self, key: TransferKey) -> TransferBubble:
        thread = self._thread(key.device_id)
        old = thread.bubble_for(key)
        if isinstance(old, HistoryBubble):
            thread.remove(old)  # bong bóng của phiên thay mục lịch sử cùng khóa
        bubble = TransferBubble(key, at=thread.session_at(), context=self._context)
        seq = self._next_seq()
        bubble.setProperty("teleport_seq", seq)
        bubble.cancel_clicked.connect(lambda b=bubble: self._cancel_clicked(b))
        bubble.open_clicked.connect(lambda b=bubble: self._open_transfer(b))
        bubble.resend_clicked.connect(lambda b=bubble: self._resend_clicked(b))
        bubble.offer_answer.connect(lambda accept, b=bubble: self._offer_answer(b, accept))
        bubble.offer_always.connect(lambda on, b=bubble: self._offer_always(b, on))
        bubble.offer_change.connect(self.change_receive_dir_requested)
        bubble.change_dir_clicked.connect(self.change_receive_dir_requested)
        self._bubbles[key] = bubble
        thread.add(bubble, seq, new=True)
        self._mark_changed()
        self._trim(key.device_id)
        self._update_page()
        return bubble

    def _trim(self, device_id: str) -> None:
        thread = self._threads.get(device_id)
        if thread is None:
            return
        for bubble in thread.trim(MAX_THREAD_BUBBLES):
            if isinstance(bubble, TransferBubble) and self._bubbles.get(bubble.key) is bubble:
                del self._bubbles[bubble.key]
            self._mark_changed()

    def _context(self, bubble: TransferBubble) -> BubbleContext:
        device_id = bubble.key.device_id
        return BubbleContext(
            peer=self._peer(device_id, bubble.offer_name),
            connected=self._connected.get(device_id, True),
            receive_dir=self._receive_dir,
        )

    def _peer(self, device_id: str, fallback: str | None) -> str:
        view = self._devices.device(device_id)
        name = self._names.get(device_id) or (view.name if view is not None else None) or fallback
        return texts.peer_label(name, device_id)

    def _cancel_clicked(self, bubble: TransferBubble) -> None:
        if not bubble.finished and bubble.offer_panel is None and self._bubbles.get(bubble.key) is bubble:
            self.cancel_requested.emit(bubble.key)

    def _resend_clicked(self, bubble: TransferBubble) -> None:
        if self._bubbles.get(bubble.key) is bubble:
            self.resend_requested.emit(bubble.key)

    def _open_transfer(self, bubble: TransferBubble) -> None:
        """“Hiện trong thư mục” của bong bóng nhận xong: chọn sẵn các file đã lưu (`ui.shell`)."""
        if bubble.last_path is None:
            return
        files = bubble.saved_paths or (bubble.last_path,)
        self._reveal(files, bubble.finished_receive_dir)

    def _open_history(self, bubble: HistoryBubble) -> None:
        """“Hiện trong thư mục” của mục lịch sử (nút chỉ hiện khi `can_open_saved`)."""
        saved = bubble.entry.saved_path
        if saved and bubble.folder() is not None and not bubble.open_button.isHidden():
            self._reveal((Path(saved),), self._receive_dir)

    def _reveal(self, files: Sequence[Path], root: Path | None) -> None:
        """`shell.show_in_folder`; không mở được (kể cả dự phòng) → câu cảnh báo với thư mục cha."""
        if shell.show_in_folder(files, root, open_url=lambda url: open_url(url)):
            return
        self._folder_warning(files[-1].parent)

    def _folder_warning(self, folder: Path) -> None:
        self.show_notice(
            texts.fill(
                QCoreApplication.translate(
                    "Chat",
                    "Không mở được thư mục {path}. Thư mục có thể đã bị xóa, đổi tên hay nằm trên ổ "
                    "đã rút ra.",
                ),
                path=printable(str(folder)),
            ),
            level=InfoLevel.WARNING,
        )

    def _on_notice_action(self) -> None:
        with self._changes():
            callback = self._notice_callback
            self.hide_notice()
            if callback is not None:
                callback()

    def _on_notice_dismissed(self) -> None:
        self._notice_callback = None
        self._notice_sources = ("", None)
        self._mark_changed()

    def _schedule_history(self) -> None:
        thread = self._current_thread()
        if thread is not None and thread.history_state is HistoryState.NONE:
            self._history_timer.start()

    def _history_pending(self) -> bool:
        """Đang chờ debounce để nạp lịch sử và có người nạp (không chớp màn rỗng)."""
        return self._history_timer.isActive() and self.isSignalConnected(
            QMetaMethod.fromSignal(self.history_needed)
        )

    def _request_history(self) -> None:
        thread = self._current_thread()
        if thread is None or thread.history_state is not HistoryState.NONE:
            return
        if not self.isSignalConnected(QMetaMethod.fromSignal(self.history_needed)):
            thread.history_state = HistoryState.LOADED  # không ai nạp: coi như không có lịch sử
            self._update_page()
            return
        thread.history_state = HistoryState.LOADING
        self.history_needed.emit(thread.device_id)
        self._update_page()

    def _update_page(self) -> None:
        """Chọn trang của `threads`, bật/tắt nút gửi, phím Chọn file, điểm dừng Tab của luồng."""
        device_id = self._device_id
        thread = self._current_thread()
        if device_id is None or thread is None:
            target: QWidget = self.placeholder
        elif (
            thread.has_bubbles()
            or thread.history_state in (HistoryState.LOADING, HistoryState.FAILED)
            or self._history_pending()
        ):
            target = thread
        else:
            target = self.empty_state
        if self.threads.currentWidget() is not target:
            self.threads.setCurrentWidget(target)
        has_bubbles = thread is not None and thread.has_bubbles() and target is thread
        self.threads.setFocusPolicy(Qt.FocusPolicy.TabFocus if has_bubbles else Qt.FocusPolicy.NoFocus)
        enabled = device_id is not None
        self.composer.send_button.setEnabled(enabled)
        self._pick_action.setEnabled(enabled)
        self._set_new_count(thread.unseen() if thread is not None else 0)

    def _apply_thread_names(self, thread: ChatThread) -> None:
        name = self._peer(thread.device_id, None)
        thread.scroll_area.setAccessibleName(
            texts.fill(QCoreApplication.translate("Chat", "Các lượt gửi nhận với {name}"), name=name)
        )

    def _on_devices_changed(self, *_args: object) -> None:
        self._update_header()

    def _update_header(self) -> None:
        t = QCoreApplication.translate
        for thread in self._threads.values():
            self._apply_thread_names(thread)
        device_id = self._device_id
        self.header.setVisible(device_id is not None)
        if device_id is None:
            self.composer.set_hint(t("Chat", "hoặc kéo file vào đây"), offline=False)
            return
        view = self._devices.device(device_id)
        name = self._peer(device_id, None)
        status, presence = self._header_status(view)
        self.header.set_device(name, status, presence)
        offline = view is not None and not view.online and not view.connected
        if offline:
            hint = texts.fill(
                t(
                    "Chat",
                    "{name} đang ngoại tuyến. File gửi lúc này sẽ chờ và tự gửi khi máy đó mở Teleport trong "
                    "cùng mạng, nếu Teleport trên máy này vẫn chạy (kể cả khi chỉ còn ở khay).",
                ),
                name=name,
            )
        else:
            hint = t("Chat", "hoặc kéo file vào đây")
        self.composer.set_hint(hint, offline=offline)
        self.empty_state.set_content(
            "attach",
            texts.fill(t("Chat", "Kéo file vào đây để gửi cho {name}"), name=name),
            texts.fill(
                t("Chat", "Hoặc bấm Gửi file ở dưới, hay nhấn {key} để dán file đã chép."),
                key=shortcuts.key_text(Shortcut.PASTE_FILES),
            ),
        )
        self.empty_state.setAccessibleName(
            f"{self.empty_state.title_label.text()}. {self.empty_state.text_label.text()}"
        )
        self.empty_state.title_label.setAccessibleName(self.empty_state.title_label.text())
        self.empty_state.text_label.setAccessibleName(self.empty_state.text_label.text())

    def _header_status(self, view: DeviceView | None) -> tuple[str, Presence]:
        t = QCoreApplication.translate
        if view is None:
            return "", Presence.NONE
        online = view.online or view.connected
        failure = self._devices.shown_failure(view)
        if failure is not None:
            head = failure_text(failure)
        elif online:
            head = t("Chat", "Trực tuyến")
        else:
            head = t("Chat", "Ngoại tuyến")
        parts = [head]
        os_label = texts.os_label(view.os)
        if os_label:
            parts.append(os_label)
        if online and view.addresses:
            parts.append(printable(str(view.addresses[0])))
        return " · ".join(parts), Presence.ONLINE if online else Presence.OFFLINE

    # -- Nút “↓ Mới”, phím tắt, Tab ----------------------------------------------------------------

    def _new_count(self) -> int:
        thread = self._current_thread()
        return thread.unseen() if thread is not None else 0

    def _set_new_count(self, count: int, *, force: bool = False) -> None:
        shown = count > 0
        if shown or force:
            t = QCoreApplication.translate
            self.new_button.set_label(t("Chat", "Mới"))
            self.new_button.setAccessibleName(
                t("Chat", "Có %n lượt mới. Bấm để cuộn xuống cuối", None, max(1, count))
            )
        if self.new_button.isHidden() == shown:
            self.new_button.setVisible(shown)

    def _on_unseen(self, device_id: str, count: int) -> None:
        if device_id == self._device_id:
            self._set_new_count(count)

    def _on_new_clicked(self) -> None:
        thread = self._current_thread()
        if thread is not None:
            thread.scroll_to_bottom()
        self._set_new_count(0)
        self.composer.send_button.setFocus(Qt.FocusReason.OtherFocusReason)

    def _request_pick(self) -> None:
        if self._device_id is not None:
            self.pick_files_requested.emit(self._device_id)

    def _on_pick_shortcut(self) -> None:
        if self._device_id is not None and self.isVisible():
            self.pick_files_requested.emit(self._device_id)

    def _on_paste_shortcut(self) -> None:
        self.paste_from_clipboard()

    def _focus_after_thread(self) -> QWidget | None:
        if not self.new_button.isHidden() and self.new_button.isVisible():
            return self.new_button
        button = self.composer.send_button
        return button if button.isVisible() and button.isEnabled() else None

    def _focus_before_thread(self) -> QWidget | None:
        """Widget nhận Tab đứng trước `threads` trong chuỗi Tab (Shift+Tab từ bong bóng)."""
        widget = self.threads.previousInFocusChain()
        window = self.window()
        for _ in range(512):
            if widget is None or widget is window or widget is self.threads:
                return None
            if (
                not self.threads.isAncestorOf(widget)
                and widget.focusPolicy() & Qt.FocusPolicy.TabFocus
                and widget.isVisible()
                and widget.isEnabled()
            ):
                return widget
            widget = widget.previousInFocusChain()
        return None
