"""Bong bóng của luồng chat theo máy (spec B3 mục 4; mvp F4, F5, mục 8, N12).

Mỗi lượt truyền của phiên là một `TransferBubble`, mỗi mục lịch sử (`history()`) một `HistoryBubble`,
mỗi lần gửi đang chờ `transfers.send` trả về một `PendingBubble` (“Đang chuẩn bị…”, spec B3 mục
9b.22). Dòng mốc thời gian giữa hai bong bóng là `TimeSeparator`. Ba hàm thuần `file_icon`,
`needs_separator`, `separator_text` không chạm widget. `ui.chat` dựng, xếp và định tuyến sự kiện tới
các bong bóng; mọi luật **theo từng lượt** (tiến độ, chữ trạng thái, bỏ sự kiện tới muộn) nằm ở đây.

**Chiều**: lượt `SEND` là `Side.OUT` (bên phải, nền `bubble_out`), `RECEIVE` là `Side.IN` (bên trái,
nền `bubble_in`, viền `border`). `widgets.Direction` trùng tên `app.transfers.Direction` nên được
import thành `Side`.

**Bố cục của `TransferBubble`**: dòng 1 icon loại file (`icon_label`, `text_muted`, chỉ trang trí),
tên file hay “n file” (`title_label`, cắt giữa theo bề ngang, tên đầy đủ ở accessibleName), cỡ
(`size_label`) và nút ✕ “Hủy” (`cancel_button`) khi chưa xong; **không có ⏸** (giao thức không có
tạm dừng). Dòng 2 thanh tiến độ mảnh `BubbleBar` (rãnh `track`, phần đã chạy `accent_strong`, thang
`BAR_MAX`), chỉ khi lượt chưa kết thúc. Dòng 3 icon trạng thái (`status_icon`, chỉ khi đã kết thúc:
`checkmark` màu `success` khi xong, `warning` màu `danger` khi lỗi, `dismiss` màu `text_muted` khi hủy
hay từ chối) và nhãn trạng thái ngắn (`status_label`); dưới đó dòng phụ (`detail_label`, xuống
dòng). Dòng 4 các nút “Hiện trong thư mục” (bên nhận đã xong; `ui.chat` gọi `ui.shell.show_in_folder`
với `saved_paths`: mọi `FileDone.path` bên nhận, tối đa `shell.REVEAL_MAX_ITEMS` cuối), “Gửi lại” và
“Đổi thư mục nhận” (bên dưới). Cuối cùng là `extension_slot`: lời mời nhận file đang chờ
(spec B4 mục 3.5) cắm ở đây một `OfferPanel`.


**Lời mời nhận file** (`TransferBubble.set_offer(entry, receive_dir, pending)`, `ui.chat` gọi theo
`ui.offer.OfferBook`): entry PENDING → dựng `OfferPanel` một lần trong `extension_slot`, **ẩn ✕
“Hủy”** (lời mời chỉ trả lời bằng Nhận / Từ chối) và viền `BubbleEmphasis.ATTENTION`; entry None hay
ANSWERED → gỡ panel, ✕ theo luật B3 (`setVisible(not finished)`). Emphasis luôn do `render_status` tự
tính (ATTENTION khi có panel, DANGER khi lỗi, còn lại NONE), vì `render_status` được gọi lại từ đổi
tên, đổi kết nối và đổi ngôn ngữ. `_on_cancel` bỏ qua khi có panel. Panel từ trên xuống: tên file
(chỉ khi > 1 file; tối đa `offer.LIST_MAX` tên nối bằng “ · ”, rồi “… và k file khác”), dòng mất
kết nối, “Lưu vào” / “Đang đổi sang …” kèm “Đổi…”, dòng “Chờ đổi thư mục nhận xong” khi đang đổi, ô
“Luôn nhận từ thiết bị này”, [Từ chối] [Nhận] (Nhận là nút chính; tắt khi đang đổi thư mục). Bấm
Nhận / Từ chối: tiêu điểm về bong bóng, tắt hai nút ngay rồi phát `offer_answer(accept)`; panel bị
gỡ khi book báo ANSWERED. Chữ dùng chung với hộp hỏi (`ui.offer`, ngữ cảnh `"Offer"`); panel tự dịch
lại khi `LanguageChange` (bẫy dưới chỉ áp cho lớp con `ChatBubble`).

Chữ trạng thái giữ nguyên chữ của `ui.transfers_view` (ví dụ “Đang gửi” + “42,0% · 85,2 MB/s · còn 1
phút”), trừ lượt đã xong: nhận “Đã lưu”, gửi “Đã gửi” (dòng phụ vẫn “Đã kiểm tra toàn vẹn” hay “Đã
lưu thành …”). Lỗi (`Kind.ERROR`): viền `BubbleEmphasis.DANGER` và câu mvp mục 8 đầy đủ
(`result_message`) màu `text`. Hủy / từ chối: không viền nhấn. Tiêu đề không còn “· tới X / · từ X”
(luồng đã thuộc một máy); tên máy vẫn có trong accessibleName.

**Tiến độ nói đúng sự thật** (spec-hackathon PR-1, dời nguyên từ `TransfersView`): mỗi bong bóng giữ
`shown_bytes`, chỉ tăng, ≤ tổng: `TransferProgress.shown_bytes`, còn ảnh chụp /
`TransferStatusChanged` / `TransferResumed` góp `done_bytes + unsynced_bytes`. Thanh và % đều theo
nó, nên bong bóng chưa kết thúc không bao giờ lùi. % làm tròn xuống và chặn ở 99,9% tới khi xong.
Dòng phụ theo trạng thái: TRANSFERRING “x% · tốc độ · còn …” (tốc độ 0 thì bỏ phần “/s”), nhưng
`idle_seconds` ≥ `STALL_TEXT_AFTER` thì câu đứng yên (bên nhận “x% · Đang chờ dữ liệu…”, bên gửi “x% ·
Đang chờ X phản hồi…”); RECONNECTING “x% · Đang chờ X nối lại…”; VERIFYING “Đang kiểm tra video.mp4…”.
Mỗi nhịp tiến độ chỉ `setValue` khi giá trị thang đổi và `setText` dòng phụ; lúc đổi loại câu (đứng
yên ↔ tốc độ) mới vẽ lại cả trạng thái. Câu tường lửa (`DataUnreachable`) và câu lượt nhận được khôi
phục (`TransferResumed`) giữ tới khi dữ liệu thật sự chảy (`shown_bytes` tăng hay về TRANSFERRING);
`TransferStatusChanged(RECONNECTING)` giữ câu tường lửa (engine báo `DataUnreachable` trước), câu
lượt khôi phục chỉ mất khi trạng thái mới là TRANSFERRING / VERIFYING. Bong bóng đã kết thúc không
đổi nữa (bỏ sự kiện tới muộn); `TransferFinished(SUSPENDED)` bị bỏ qua. Bên nhận xong mà file được
lưu khác tên gốc (`FileDone.path.name` ≠ tên trong `TransferInfo.names`): “Đã lưu thành video (1).mp4 ·
Đã kiểm tra toàn vẹn” hay “Đã lưu n file với tên mới · …”.

**“Gửi lại”** (spec B3 mục 5, 9.1): chỉ hiện khi đủ bốn điều kiện: chiều `SEND`, đã kết thúc, kết
quả khác `DONE` và `UNPAIRED`, và bên điều phối đã nhớ đường dẫn nguồn (`set_resendable(True)`). Xét
cả lúc `set_resendable` lẫn lúc kết thúc, nên thứ tự nào cũng đúng. Bấm được một lần (`resend_clicked`
rồi ẩn).

**“Đổi thư mục nhận”** (`change_dir_button`, spec D4 mục 5.2, 14.5, 14.13; mvp mục 8): chỉ hiện khi
chiều `RECEIVE`, đã kết thúc với `REJECTED_NO_SPACE`, `REJECTED_FILE_TOO_LARGE`, `DISK_FAILED` hay
`RECEIVE_DIR_MISSING`, và thư mục nhận hiện tại (`set_current_receive_dir`, `ui.chat` gọi cho mọi bong
bóng mỗi khi thư mục nhận đổi) vẫn là thư mục lúc lượt kết thúc (`finished_receive_dir`, lấy từ
`BubbleContext.receive_dir` lúc `finish`; None thì không hiện). Đổi sang thư mục khác thì nút ẩn.
Câu kết quả của bong bóng đã kết thúc nêu `finished_receive_dir`, không nêu thư mục hiện tại. Bấm →
`change_dir_clicked` (không giới hạn số lần; bên điều phối chỉ mở một hộp chọn). `HistoryBubble` không
có nút này.

**Trình đọc màn hình**: câu tóm tắt qua `ChatBubble.set_summary` (accessibleName): “Gửi tới X” /
“Nhận từ X”, tên file, cỡ, trạng thái, % nguyên (đang chạy) hay dòng phụ (chờ, kết thúc), giờ. Chỉ
đặt lại khi loại trạng thái, nhãn, % nguyên hay câu phụ không phải tiến độ đổi, không theo từng nhịp
tốc độ. Có panel lời mời thì câu tóm tắt thêm “Lời mời nhận file. Dùng Tab để tới nút Nhận hay Từ
chối.” Mọi trạng thái là icon + chữ, không chỉ màu (mvp N12). Bong bóng nhận tiêu điểm bằng chuột hay
bằng code (`ClickFocus`; Tab do `ui.chat` lo, roving tabindex: bong bóng rồi các nút của nó theo
`focus_buttons()`, với panel lời mời là Đổi…, ô tick, Từ chối, Nhận) và vẽ vòng tiêu điểm 2 px
`theme.focus_ring_color` thụt vào 3 px, sau nền và viền của `ChatBubble`.

**Bẫy**: `ChatBubble.__init__` gọi `self.retranslate()` trước khi lớp con dựng xong, nên lớp con
**không ghi đè `retranslate`**; chữ dựng trong `_render()`, gọi từ `changeEvent` sau
`super().changeEvent` (LanguageChange). Icon chỉ có cỡ 20 (`icons.SIZES`): icon trạng thái 16 px là
pixmap 20 thu vào nhãn 16×16.

**`HistoryBubble`**: chiều theo `entry.direction`; tên `file_label(names[0])` khi một file, không thì
“n file”; dòng phụ “cỡ · HH:mm”; trạng thái “Đã lưu” / “Đã gửi” khi xong, còn lại `result_status`,
giá trị `result` lạ → “Lỗi” và viền DANGER (`Kind.ERROR`). Không có “Gửi lại”. “Hiện trong thư mục” chỉ khi
`saved_path` tuyệt đối, và đường dẫn UNC chỉ khi thư mục nhận hiện tại nằm cùng `\\server\\share`
(`can_open_saved`, so chuỗi sau `normcase`, không chạm đĩa).

**`ClipboardNote`** (mvp F8): dòng mảnh báo clipboard vừa nhận từ máy kia, **không** phải
`ChatBubble` (không nền bong bóng, không hướng gửi/nhận), căn trái: icon `clipboard_paste`, dòng 1
“Clipboard · đã chép vào máy này” hay “Clipboard · chưa chép được vào máy này” (kèm nút “Thử lại”,
`retry_clicked`), dòng 2: văn bản → dòng không trắng đầu tiên của `preview` (ký tự điều khiển, vô
hình, đổi hướng chữ → U+FFFD qua `send.printable`, tối đa `NOTE_PREVIEW_CHARS`, cắt cuối “…” theo bề
ngang), ảnh → “Ảnh {w} × {h} · {cỡ}”; không có `preview` / `image_size` (ghi lỗi) → “Văn bản · {cỡ}” /
“Ảnh · {cỡ}”. `set_unavailable()` (“Thử lại” trả `NOTHING_TO_RETRY`): dòng 2 “Clipboard này không
còn để chép lại.”, ẩn nút. Tên trợ năng “Clipboard từ {tên}: {dòng 1}. {dòng 2}”. Nhận tiêu điểm như
bong bóng (`ClickFocus`, vòng tiêu điểm 2 px, `focus_buttons()`). Nội dung chỉ ở RAM của widget, không
ghi đĩa, không tooltip.

Chữ máy kia (tên máy, tên file) qua `texts.peer_label` / `texts.file_label`, mọi nhãn
`Qt.PlainText`, không tooltip chứa chữ máy kia. Chuỗi mới ở ngữ cảnh `"Chat"`, gọi lúc dùng; câu mvp
mục 8 lấy từ `ui.transfers_view` (ngữ cảnh `"Transfers"`, không chép lại).
"""

from __future__ import annotations

import datetime
import ntpath
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePath

from PySide6.QtCore import QCoreApplication, QDate, QEvent, QRectF, QSignalBlocker, QSize, Qt, QTime, Signal
from PySide6.QtGui import QFocusEvent, QFont, QFontMetrics, QPainter, QPaintEvent, QPen, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from teleport.app.transfers import (
    Direction,
    FileDone,
    OfferReceived,
    TransferFinished,
    TransferInfo,
    TransferKey,
    TransferProgress,
    TransferResult,
    TransferStatus,
)
from teleport.core.history import HistoryEntry
from teleport.core.messages import ClipKind
from teleport.ui import icons, offer, shell, texts, theme
from teleport.ui.offer import OfferEntry, OfferPhase
from teleport.ui.send import printable
from teleport.ui.transfers_view import (
    _FLOWING_STATUSES,
    _WAITING_STATUSES,
    BAR_MAX,
    STALL_TEXT_AFTER,
    Kind,
    bar_value,
    done_text,
    percent_text,
    progress_text,
    reconnecting_text,
    result_kind,
    result_message,
    result_status,
    resumed_text,
    saved_as_text,
    short_status,
    stalled_text,
    status_kind,
    unreachable_text,
    verifying_text,
    waiting_detail,
)
from teleport.ui.widgets import BubbleEmphasis, ChatBubble, IconButton, bubble_path
from teleport.ui.widgets import Direction as Side

SEPARATOR_GAP = 3600.0  # giây; cách bong bóng trước ≥ mức này thì có dòng mốc
BUBBLE_MIN_WIDTH = 220  # px
_ICON = 20  # px, icon loại file
_STATUS_ICON = 16  # px, icon trạng thái (pixmap 20 thu vào)
_FOCUS_INSET = 3  # px, vòng tiêu điểm thụt vào trong bong bóng
NOTE_PREVIEW_CHARS = 200  # code point tối đa của dòng xem trước clipboard
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)

_VIDEO = frozenset({"mp4", "mkv", "mov", "avi", "webm", "wmv", "m4v", "flv", "mpg", "mpeg", "3gp", "ts"})
_IMAGE = frozenset(
    {"jpg", "jpeg", "png", "gif", "bmp", "webp", "heic", "heif", "tif", "tiff", "svg", "ico", "raw", "avif"}
)
_AUDIO = frozenset({"mp3", "m4a", "wav", "flac", "aac", "ogg", "opus", "wma", "aiff"})
_ARCHIVE = frozenset({"zip", "rar", "7z", "tar", "gz", "bz2", "xz", "tgz", "zst", "cab"})
# Kết quả bên nhận có nút “Đổi thư mục nhận” (mvp mục 8; spec D4 mục 5.2, 14.13).
_CHANGE_DIR_RESULTS = frozenset(
    {
        TransferResult.REJECTED_NO_SPACE,
        TransferResult.REJECTED_FILE_TOO_LARGE,
        TransferResult.DISK_FAILED,
        TransferResult.RECEIVE_DIR_MISSING,
    }
)


# ---- Hàm thuần --------------------------------------------------------------------------------


def file_icon(names: Sequence[str], file_count: int) -> str:
    """Tên icon theo loại file (chỉ trang trí): nhiều file hay không biết tên → “document”."""
    if file_count > 1 or not names:
        return "document"
    _, dot, ext = names[0].rpartition(".")
    ext = ext.casefold() if dot else ""
    if ext in _VIDEO:
        return "video"
    if ext in _IMAGE:
        return "image"
    if ext in _AUDIO:
        return "music_note_2"
    if ext == "pdf":
        return "document_pdf"
    if ext in _ARCHIVE:
        return "folder_zip"
    return "document"


def needs_separator(prev_at: float | None, at: float) -> bool:
    """Có dòng mốc trước bong bóng ở `at` không: không có bong bóng trước, khác ngày (giờ địa phương),
    hay cách bong bóng trước ≥ `SEPARATOR_GAP` giây. Giờ không đổi được → có mốc."""
    if prev_at is None:
        return True
    try:
        if datetime.datetime.fromtimestamp(prev_at).date() != datetime.datetime.fromtimestamp(at).date():
            return True
    except (OverflowError, OSError, ValueError):
        return True
    return at - prev_at >= SEPARATOR_GAP


def separator_text(at: float, now: float) -> str:
    """Chữ dòng mốc (giờ địa phương): “Hôm nay 10:40”, “Hôm qua 21:03”, “28/10 21:03” (cùng năm),
    “28/10/2025 21:03”; ngày sau hôm nay theo hai dạng ngày. Giờ không đổi được → chuỗi rỗng."""
    t = QCoreApplication.translate
    try:
        moment = datetime.datetime.fromtimestamp(at)
        today = datetime.datetime.fromtimestamp(now).date()
        day = moment.date()
        clock = QTime(moment.hour, moment.minute).toString(t("Chat", "HH:mm"))
        if day == today:
            return texts.fill(t("Chat", "Hôm nay {time}"), time=clock)
        if day < today and day == today - datetime.timedelta(days=1):
            return texts.fill(t("Chat", "Hôm qua {time}"), time=clock)
    except (OverflowError, OSError, ValueError):
        return ""
    date = QDate(day.year, day.month, day.day)
    shown = date.toString(t("Chat", "dd/MM") if day.year == today.year else t("Chat", "dd/MM/yyyy"))
    return texts.fill(t("Chat", "{date} {time}"), date=shown, time=clock)


def clock_text(at: float) -> str:
    """Giờ địa phương “HH:mm” của `at`; giờ không đổi được → chuỗi rỗng."""
    try:
        moment = datetime.datetime.fromtimestamp(at)
    except (OverflowError, OSError, ValueError):
        return ""
    return QTime(moment.hour, moment.minute).toString(QCoreApplication.translate("Chat", "HH:mm"))


def change_dir_text() -> str:
    """Nút “Đổi thư mục nhận” của bong bóng nhận bị từ chối / lỗi vì ổ đĩa (spec D4 mục 5.2)."""
    return QCoreApplication.translate("Chat", "Đổi thư mục nhận")


def files_text(file_count: int) -> str:
    """“n file” (tiêu đề khi nhiều file hay không biết tên)."""
    return QCoreApplication.translate("Chat", "%n file", None, max(0, file_count))


def _unc_share(path: str) -> str | None:
    r"""Ổ mạng hay thiết bị (đã `normcase`) của `path`; ổ chữ cái `X:` hay không bắt đầu bằng `\\` → None.

    Bỏ tiền tố `\\?\UNC\` (không phân biệt hoa thường) như `transfers_view._drive_label`, và `\\?\`
    khi phía sau là ổ chữ cái; `\\?\` với phần sau khác (`GLOBALROOT\…`, `Volume{…}`) → "" (không bao
    giờ trùng, kể cả khi thư mục nhận cùng dạng). Mọi dạng còn bắt đầu bằng `\\` hay `//` sau chuẩn
    hóa (UNC, `\\.\`) coi là mạng/thiết bị: trả ổ của nó, hay "" khi không tách được ổ (không bao giờ
    trùng thư mục nhận). Chỉ xử lý chuỗi.
    """
    text = path
    if text[:8].lower() in ("\\\\?\\unc\\", "//?/unc/"):
        text = "\\\\" + text[8:]
    elif text[:4] in ("\\\\?\\", "//?/"):
        rest = text[4:]
        if len(rest) >= 2 and rest[1] == ":" and rest[0].isascii() and rest[0].isalpha():
            text = rest
        else:
            # `\\?\GLOBALROOT\…`, `\\?\Volume{…}\…`: không tách được ổ đáng tin → không bao giờ trùng.
            return ""
    if not text.startswith(("\\\\", "//")):
        return None
    return ntpath.normcase(ntpath.splitdrive(text)[0])


def can_open_saved(saved_path: str | None, receive_dir: Path | None) -> bool:
    """“Hiện trong thư mục” của mục lịch sử được không (spec B3 mục 5, 9.12): `saved_path` tuyệt đối; ổ mạng
    hay thiết bị (`_unc_share`) chỉ khi thư mục nhận hiện tại nằm trên cùng ổ đó. Không chạm đĩa."""
    if not saved_path:
        return False
    share = _unc_share(saved_path)
    if share is not None:
        return bool(share) and receive_dir is not None and _unc_share(str(receive_dir)) == share
    if os.name == "nt":
        return ntpath.isabs(saved_path) and bool(ntpath.splitdrive(saved_path)[0])
    return PurePath(saved_path).is_absolute()


# ---- Widget nhỏ -------------------------------------------------------------------------------


def _label(*, wrap: bool = False, caption: bool = False, tone: str | None = None) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    if wrap:
        label.setWordWrap(True)
        label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    if caption:
        label.setFont(theme.font_for(theme.TextStyle.CAPTION, label.font()))
    if tone is not None:
        label.setProperty(theme.TONE_PROPERTY, tone)
    return label


def _peer_text(object_name: str) -> offer.PeerTextLabel:
    """Nhãn phụ xuống dòng (CAPTION, `tone=muted`) cho chữ máy kia trong panel lời mời."""
    label = offer.PeerTextLabel(wrap=True, object_name=object_name)
    label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    label.setFont(theme.font_for(theme.TextStyle.CAPTION, label.font()))
    label.setProperty(theme.TONE_PROPERTY, "muted")
    return label


def set_tone(label: QLabel, tone: str | None) -> None:
    """Đổi `TONE_PROPERTY` của nhãn (chỉ khi khác) và áp lại stylesheet (dùng chung với `ui.pairing`)."""
    if label.property(theme.TONE_PROPERTY) == tone:
        return
    label.setProperty(theme.TONE_PROPERTY, tone)
    style = label.style()
    style.unpolish(label)
    style.polish(label)


class _ElidedLabel(QLabel):
    """Nhãn một dòng cắt theo bề ngang (mặc định cắt giữa); `full_text()` là chữ đầy đủ (cũng ở
    accessibleName)."""

    def __init__(self, mode: Qt.TextElideMode = Qt.TextElideMode.ElideMiddle) -> None:
        super().__init__()
        self._full = ""
        self._mode = mode
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def full_text(self) -> str:
        return self._full

    def set_full_text(self, text: str) -> None:
        if text == self._full and self.text():
            return
        self._full = text
        self.setAccessibleName(text)
        self._elide()
        self.updateGeometry()

    def sizeHint(self) -> QSize:
        metrics = QFontMetrics(self.font())
        return QSize(metrics.horizontalAdvance(self._full) + 2, super().sizeHint().height())

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        width = max(0, self.width())
        metrics = QFontMetrics(self.font())
        shown = (
            self._full
            if metrics.horizontalAdvance(self._full) <= width
            else (metrics.elidedText(self._full, self._mode, width))
        )
        if shown != self.text():
            self.setText(shown)


class _IconLabel(QLabel):
    """Icon tô màu token (`icons.pixmap`), vẽ lại khi đổi sáng/tối; chỉ trang trí (NoFocus)."""

    def __init__(self, size: int) -> None:
        super().__init__()
        self._size = size
        self._name: str | None = None
        self._token = "text_muted"
        self.setFixedSize(size, size)
        self.setScaledContents(size != _ICON)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    @property
    def icon_name(self) -> str | None:
        return self._name

    @property
    def token(self) -> str:
        return self._token

    def set_icon(self, name: str | None, token: str = "text_muted") -> None:
        if name == self._name and token == self._token and (name is None or not self.pixmap().isNull()):
            return
        self._name, self._token = name, token
        self.refresh()

    def refresh(self) -> None:
        if self._name is None:
            self.clear()
            self.setVisible(False)
            return
        color = getattr(theme.tokens_for(self), self._token)
        self.setPixmap(icons.pixmap(self._name, _ICON, color, self.devicePixelRatioF()))
        self.setVisible(True)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in (*_PALETTE_EVENTS, QEvent.Type.DevicePixelRatioChange):
            self.refresh()


class BubbleBar(QProgressBar):
    """Thanh tiến độ mảnh 6 px của bong bóng: rãnh `track`, phần đã chạy `accent_strong`, thang
    `BAR_MAX`; vẫn là `QProgressBar` nên giữ vai trò trợ năng ProgressBar."""

    HEIGHT = 6

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, BAR_MAX)
        self.setValue(0)
        self.setTextVisible(False)
        self.setFixedHeight(self.HEIGHT)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def paintEvent(self, event: QPaintEvent) -> None:
        span = max(1, self.maximum() - self.minimum())
        paint_thin_bar(self, max(0, self.value() - self.minimum()) / span)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()


def paint_thin_bar(widget: QWidget, fraction: float) -> None:
    """Vẽ thanh mảnh bo tròn trên cả `widget`: rãnh `track`, phần `fraction` (0…1) màu `accent_strong`.

    Dùng chung cho `BubbleBar` và thanh đếm ngược của hộp ghép đôi (`ui.pairing`)."""
    t = theme.tokens_for(widget)
    rect = QRectF(widget.rect())
    radius = rect.height() / 2
    done = rect.width() * min(1.0, max(0.0, fraction))
    painter = QPainter(widget)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.track)
        painter.drawRoundedRect(rect, radius, radius)
        if done > 0:
            painter.setBrush(t.accent_strong)
            painter.drawRoundedRect(
                QRectF(rect.left(), rect.top(), max(done, rect.height()), rect.height()), radius, radius
            )
    finally:
        painter.end()


class TimeSeparator(QLabel):
    """Dòng mốc thời gian giữa hai bong bóng: căn giữa, CAPTION, `tone=muted`, không nhận tiêu điểm."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.setFont(theme.font_for(theme.TextStyle.CAPTION, self.font()))
        self.setProperty(theme.TONE_PROPERTY, "muted")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setWordWrap(True)


# ---- Nền chung của bong bóng ------------------------------------------------------------------


class _Bubble(ChatBubble):
    """Phần chung: dòng 1 (icon, tên, cỡ, chỗ nút), vòng tiêu điểm, vẽ lại chữ khi đổi ngôn ngữ."""

    focus_entered = Signal()

    def __init__(self, side: Side, parent: QWidget | None, *, at: float) -> None:
        super().__init__(side, parent)
        self.at = at
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumWidth(BUBBLE_MIN_WIDTH)
        self.icon_label = _IconLabel(_ICON)
        self.title_label = _ElidedLabel()
        title_font = self.title_label.font()
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.size_label = _label(caption=True, tone="muted")
        self.status_icon = _IconLabel(_STATUS_ICON)
        self.status_icon.setVisible(False)
        self.status_label = _label(caption=True)
        status_font = self.status_label.font()
        status_font.setWeight(QFont.Weight.DemiBold)
        self.status_label.setFont(status_font)
        self.detail_label = _label(wrap=True, caption=True, tone="muted")

        names = QVBoxLayout()
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addWidget(self.title_label)
        names.addWidget(self.size_label)
        self.head = QHBoxLayout()
        self.head.setContentsMargins(0, 0, 0, 0)
        self.head.setSpacing(theme.SPACING[1])
        self.head.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        self.head.addLayout(names, 1)
        self.status_row = QHBoxLayout()
        self.status_row.setContentsMargins(0, 0, 0, 0)
        self.status_row.setSpacing(theme.SPACING[0])
        self.status_row.addWidget(self.status_icon, 0, Qt.AlignmentFlag.AlignTop)
        self.status_row.addWidget(self.status_label, 0, Qt.AlignmentFlag.AlignTop)
        self.status_row.addStretch(1)
        self.body().addLayout(self.head)

    def focus_buttons(self) -> list[QWidget]:
        """Các nút của bong bóng đang hiện và bật, theo thứ tự Tab."""
        return []

    def _render(self) -> None:
        """Dựng lại mọi chữ (lớp con)."""

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._render()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.update()
        self.focus_entered.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.hasFocus():
            return
        dark = theme.is_dark_palette(QApplication.palette())
        inset = _FOCUS_INSET
        path = bubble_path(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), self.direction)
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.focus_ring_color(dark), 2))
            painter.drawPath(path)
        finally:
            painter.end()


def _button(parent: QWidget) -> QPushButton:
    button = QPushButton(parent)
    button.setAutoDefault(False)
    button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Tab do `ui.chat` (roving tabindex)
    button.setVisible(False)
    return button


# ---- OfferPanel -------------------------------------------------------------------------------


class OfferPanel(QWidget):
    """Phần trả lời lời mời nhận file trong bong bóng (xem docstring module, “Lời mời nhận file”)."""

    answer_clicked = Signal(bool)  # accept
    always_toggled = Signal(bool)
    change_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("offerPanel")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._entry: OfferEntry | None = None
        self._receive_dir: Path | None = None
        self._pending: Path | None = None
        self._answered = False  # đã bấm Nhận / Từ chối: hai nút tắt tới khi panel bị gỡ
        # Chữ máy kia (tên file, tên máy) và đường dẫn: không ép bong bóng rộng quá luồng
        # (`offer.PeerTextLabel`).
        self.files_label = _peer_text("offerPanelFiles")
        self.note_label = _peer_text("offerPanelDisconnected")
        self.save_label = _peer_text("offerPanelSaveTo")
        self.change_button = QPushButton(self)
        self.change_button.setObjectName("offerChangeDir")
        self.dir_note = _label(wrap=True, caption=True, tone="muted")
        self.dir_note.setObjectName("offerPanelDirNote")
        self.always_check = QCheckBox(self)
        self.always_check.setObjectName("offerAlways")
        self.reject_button = QPushButton(self)
        self.reject_button.setObjectName("offerReject")
        self.accept_button = QPushButton(self)
        self.accept_button.setObjectName("offerAccept")
        self.accept_button.setProperty(theme.PRIMARY_PROPERTY, True)
        for button in (self.change_button, self.reject_button, self.accept_button):
            button.setAutoDefault(False)
        for widget in (self.change_button, self.always_check, self.reject_button, self.accept_button):
            widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Tab do `ui.chat` (roving tabindex)
        self.change_button.clicked.connect(self.change_clicked)
        self.always_check.toggled.connect(lambda on: self.always_toggled.emit(bool(on)))
        self.reject_button.clicked.connect(lambda: self._on_answer(False))
        self.accept_button.clicked.connect(lambda: self._on_answer(True))

        save_row = QHBoxLayout()
        save_row.setContentsMargins(0, 0, 0, 0)
        save_row.setSpacing(theme.SPACING[1])
        save_row.addWidget(self.save_label, 1)
        save_row.addWidget(self.change_button, 0, Qt.AlignmentFlag.AlignVCenter)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, theme.SPACING[0], 0, 0)
        buttons.setSpacing(theme.SPACING[1])
        buttons.addStretch(1)
        buttons.addWidget(self.reject_button)
        buttons.addWidget(self.accept_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, theme.SPACING[0], 0, 0)
        layout.setSpacing(theme.SPACING[0])
        layout.addWidget(self.files_label)
        layout.addWidget(self.note_label)
        layout.addLayout(save_row)
        layout.addWidget(self.dir_note)
        layout.addWidget(self.always_check)
        layout.addLayout(buttons)
        for label in (self.files_label, self.note_label, self.dir_note):
            label.setVisible(False)
        self.retranslate()

    @property
    def entry(self) -> OfferEntry | None:
        return self._entry

    def set_entry(self, entry: OfferEntry, receive_dir: Path | None, pending: Path | None) -> None:
        """Lời mời (`entry`), thư mục nhận và thư mục đang đổi sang (None: không đổi)."""
        self._entry = entry
        self._receive_dir = receive_dir
        self._pending = pending
        self.retranslate()

    def set_receive_dir(self, receive_dir: Path | None, pending: Path | None) -> None:
        """Thư mục nhận và thư mục đang đổi sang (dòng “Lưu vào”, nút Nhận / Đổi…)."""
        self._receive_dir = receive_dir
        self._pending = pending
        self._refresh_state()

    def focus_widgets(self) -> list[QWidget]:
        """Các ô nhận Tab đang hiện và bật, theo thứ tự: Đổi…, ô tick, Từ chối, Nhận."""
        widgets: list[QWidget] = [
            self.change_button,
            self.always_check,
            self.reject_button,
            self.accept_button,
        ]
        return [w for w in widgets if not w.isHidden() and w.isEnabled()]

    def retranslate(self) -> None:
        """Dựng lại mọi chữ theo lời mời, thư mục và trạng thái đã lưu."""
        self.change_button.setText(offer.change_text())
        self.change_button.setAccessibleName(offer.change_name())
        always = offer.always_text()
        self.always_check.setText(always)
        self.always_check.setAccessibleName(always)
        for button, text in (
            (self.reject_button, offer.reject_text()),
            (self.accept_button, offer.accept_text()),
        ):
            button.setText(text)
            button.setAccessibleName(text)
        entry = self._entry
        if entry is not None:
            item = entry.offer
            count = len(item.files)
            if count > 1:
                text = " · ".join(texts.file_label(name) for name in item.names[: offer.LIST_MAX])
                rest = count - min(count, offer.LIST_MAX)
                if rest > 0:
                    text = f"{text} {offer.more_text(rest)}" if text else offer.more_text(rest)
                self.files_label.setText(text)
            self.files_label.setVisible(count > 1)
            peer = texts.peer_label(item.device_name, item.key.device_id)
            self.note_label.setText(offer.disconnected_text(peer))
        self._refresh_state()

    def _refresh_state(self) -> None:
        save = offer.save_line(self._receive_dir, self._pending)
        self.save_label.setText(save or "")
        self.save_label.setVisible(save is not None)
        changing = self._pending is not None
        self.change_button.setVisible(self._receive_dir is not None)
        self.change_button.setEnabled(not changing)
        hint = offer.pending_accept_hint() if changing else ""
        self.dir_note.setText(hint)
        self.dir_note.setVisible(changing)
        self.accept_button.setAccessibleDescription(hint)
        self.accept_button.setEnabled(not changing and not self._answered)
        self.reject_button.setEnabled(not self._answered)
        entry = self._entry
        if entry is None:
            return
        self.note_label.setVisible(not entry.connected)
        if self.always_check.isChecked() != entry.always:
            with QSignalBlocker(self.always_check):
                self.always_check.setChecked(entry.always)

    def _on_answer(self, accept: bool) -> None:
        if self._answered:
            return
        self._answered = True
        bubble = self.parentWidget()
        if bubble is not None:
            bubble.setFocus(Qt.FocusReason.OtherFocusReason)  # nút sắp tắt rồi bị gỡ
        self.accept_button.setEnabled(False)
        self.reject_button.setEnabled(False)
        self.answer_clicked.emit(accept)

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()


# ---- TransferBubble ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BubbleContext:
    """Những gì bong bóng cần từ luồng để dựng chữ: tên máy kia (đã qua `peer_label`), có kết nối điều
    khiển không, thư mục nhận (câu lỗi ghi đĩa)."""

    peer: str
    connected: bool = True
    receive_dir: Path | None = None


class TransferBubble(_Bubble):
    """Bong bóng của một lượt trong phiên (xem docstring module)."""

    cancel_clicked = Signal()
    open_clicked = Signal()
    resend_clicked = Signal()
    offer_answer = Signal(bool)  # Nhận / Từ chối trong panel lời mời
    offer_always = Signal(bool)  # ô “Luôn nhận” trong panel
    offer_change = Signal()  # “Đổi…” trong panel
    change_dir_clicked = Signal()  # “Đổi thư mục nhận” (spec D4 mục 5.2)

    def __init__(
        self,
        key: TransferKey,
        parent: QWidget | None = None,
        *,
        at: float = 0.0,
        context: Callable[[TransferBubble], BubbleContext] | None = None,
    ) -> None:
        super().__init__(Side.OUT if key.direction is Direction.SEND else Side.IN, parent, at=at)
        self.key = key
        self.finished = False
        self.kind = Kind.WAITING
        self.status = TransferStatus.WAITING
        self.info: TransferInfo | None = None
        self.file_count = 0
        self.total_bytes = 0
        self.first_name: str | None = None  # tên file đầu (chưa qua `file_label`)
        self.offer_name: str | None = None  # tên máy trong `OfferReceived` (dự phòng)
        self.offer_names: tuple[str, ...] = ()
        self.resumed = False
        self.unreachable = False
        self.progress: TransferProgress | None = None
        self.shown_bytes = 0  # byte hiển thị (thanh, %), chỉ tăng
        self.stalled_shown = False
        self.result: TransferFinished | None = None
        self.last_path: Path | None = None  # `FileDone.path` cuối (bên nhận)
        # Mọi `FileDone.path` bên nhận, tối đa `shell.REVEAL_MAX_ITEMS` cuối (“Hiện trong thư mục”).
        self.saved_paths: tuple[Path, ...] = ()
        self.renamed: dict[int, str] = {}
        self._resend_known = False
        self._resend_used = False
        self.finished_receive_dir: Path | None = None  # thư mục nhận lúc lượt kết thúc
        self._current_receive_dir: Path | None = None
        self._summary_key: tuple[object, ...] | None = None
        self._context = context
        self.offer_panel: OfferPanel | None = None

        self.cancel_button = IconButton("dismiss", QCoreApplication.translate("Chat", "Hủy"), self)
        self.cancel_button.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.cancel_button.clicked.connect(self._on_cancel)
        self.head.addWidget(self.cancel_button, 0, Qt.AlignmentFlag.AlignTop)
        self.progress_bar = BubbleBar(self)
        self.open_button = _button(self)
        self.open_button.clicked.connect(self.open_clicked)
        self.resend_button = _button(self)
        self.resend_button.clicked.connect(self._on_resend)
        self.change_dir_button = _button(self)
        self.change_dir_button.setObjectName("changeReceiveDirBubbleButton")
        self.change_dir_button.clicked.connect(self.change_dir_clicked)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, theme.SPACING[0], 0, 0)
        buttons.setSpacing(theme.SPACING[1])
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.resend_button)
        buttons.addWidget(self.change_dir_button)
        buttons.addStretch(1)
        self.extension_slot = QVBoxLayout()
        self.extension_slot.setContentsMargins(0, 0, 0, 0)
        body = self.body()
        body.addWidget(self.progress_bar)
        body.addLayout(self.status_row)
        body.addWidget(self.detail_label)
        body.addLayout(buttons)
        body.addLayout(self.extension_slot)
        self.icon_label.set_icon("document")
        self._render()

    # -- Dữ liệu ----------------------------------------------------------------------------------

    def context(self) -> BubbleContext:
        if self._context is not None:
            return self._context(self)
        return BubbleContext(texts.peer_label(self.offer_name, self.key.device_id))

    def set_info(self, info: TransferInfo) -> None:
        self.info = info
        self.status = info.status
        self.file_count = len(info.files)
        self.total_bytes = info.total_bytes
        self.first_name = info.names[0] if info.names else None

    def original_name(self, index: int) -> str | None:
        """Tên gốc (đã làm sạch) của file thứ `index`: `info.names`, không có thì tên trong `offer`."""
        names = self.info.names if self.info is not None and self.info.names else self.offer_names
        return names[index] if 0 <= index < len(names) else None

    def raise_shown(self, shown: int, total: int) -> None:
        """Nâng `shown_bytes` lên `shown` (kẹp trong 0…`total`); không bao giờ hạ, thanh không lùi."""
        self.shown_bytes = max(self.shown_bytes, min(max(0, shown), max(0, total)))
        value = bar_value(self.shown_bytes, total)
        if value > self.progress_bar.value():
            self.progress_bar.setValue(value)

    def set_resendable(self, on: bool) -> None:
        """Bên điều phối đã nhớ (True) hay bỏ (False) đường dẫn nguồn của lượt này cho “Gửi lại”."""
        self._resend_known = bool(on)
        self._update_resend()

    def resendable(self) -> bool:
        """Nút “Gửi lại” đang được phép hiện (đủ bốn điều kiện, chưa bấm)."""
        result = None if self.result is None else self.result.result
        return (
            self.key.direction is Direction.SEND
            and self.finished
            and result not in (None, TransferResult.DONE, TransferResult.UNPAIRED)
            and self._resend_known
            and not self._resend_used
        )

    def set_current_receive_dir(self, path: Path | None) -> None:
        """Thư mục nhận hiện tại: quyết định nút “Đổi thư mục nhận” (xem docstring module)."""
        self._current_receive_dir = path
        self._update_change_dir()

    def change_dir_available(self) -> bool:
        """Nút “Đổi thư mục nhận” đang được phép hiện."""
        return (
            self.key.direction is Direction.RECEIVE
            and self.finished
            and self.result is not None
            and self.result.result in _CHANGE_DIR_RESULTS
            and self.finished_receive_dir is not None
            and self.finished_receive_dir == self._current_receive_dir
        )

    def focus_buttons(self) -> list[QWidget]:
        candidates: list[QWidget] = [
            self.cancel_button,
            self.open_button,
            self.resend_button,
            self.change_dir_button,
        ]
        for i in range(self.extension_slot.count()):
            item = self.extension_slot.itemAt(i)
            widget = item.widget() if item is not None else None
            if widget is None or widget.isHidden():
                continue
            focus_widgets = getattr(widget, "focus_widgets", None)
            if callable(focus_widgets):
                candidates.extend(focus_widgets())
            else:
                candidates.append(widget)
        return [w for w in candidates if not w.isHidden() and w.isEnabled()]

    # -- Lời mời nhận file ------------------------------------------------------------------------

    def set_offer(
        self, entry: OfferEntry | None, receive_dir: Path | None = None, pending: Path | None = None
    ) -> bool:
        """Lời mời của bong bóng (xem docstring module); True nếu vừa thêm hay gỡ panel."""
        changed = False
        if entry is not None and entry.phase is OfferPhase.PENDING and not self.finished:
            panel = self.offer_panel
            if panel is None:
                panel = OfferPanel(self)
                panel.answer_clicked.connect(self.offer_answer)
                panel.always_toggled.connect(self.offer_always)
                panel.change_clicked.connect(self.offer_change)
                self.extension_slot.addWidget(panel)
                self.offer_panel = panel
                changed = True
            panel.set_entry(entry, receive_dir, pending)
            self.cancel_button.setVisible(False)
        else:
            panel = self.offer_panel
            if panel is not None:
                self.offer_panel = None
                self.extension_slot.removeWidget(panel)
                panel.hide()
                panel.setParent(None)
                panel.deleteLater()
                changed = True
            self.cancel_button.setVisible(not self.finished)
        if changed:
            self.render_status()
        return changed

    def set_offer_dir(self, receive_dir: Path | None, pending: Path | None) -> None:
        """Thư mục nhận / đang đổi sang cho dòng “Lưu vào” của panel (không có panel → bỏ qua)."""
        if self.offer_panel is not None:
            self.offer_panel.set_receive_dir(receive_dir, pending)

    # -- Sự kiện của lượt -------------------------------------------------------------------------

    def apply_status(self, info: TransferInfo) -> None:
        """`TransferStatusChanged`."""
        if self.finished:
            return
        self.set_info(info)
        self.raise_shown(info.done_bytes + info.unsynced_bytes, info.total_bytes)
        # Engine báo `DataUnreachable` TRƯỚC `StatusChanged(RECONNECTING)` của cùng lần thất bại:
        # RECONNECTING không xóa câu tường lửa. Câu lượt khôi phục chỉ mất khi dữ liệu chảy lại.
        if info.status is not TransferStatus.RECONNECTING:
            self.unreachable = False
        if info.status in _FLOWING_STATUSES:
            self.resumed = False
        self._render()

    def apply_offer(self, update: OfferReceived) -> None:
        if self.finished:
            return
        self.offer_name = update.device_name
        self.offer_names = tuple(update.names)
        if self.info is None:
            self.status = TransferStatus.WAITING
            self.file_count = len(update.files)
            self.total_bytes = update.total_bytes
            self.first_name = update.names[0] if update.names else None
        self._render()

    def apply_file_done(self, update: FileDone) -> None:
        if self.finished or update.path is None:
            return
        self.last_path = update.path
        if self.key.direction is Direction.RECEIVE:
            limit = max(1, int(shell.REVEAL_MAX_ITEMS))
            self.saved_paths = (*self.saved_paths, update.path)[-limit:]
        # Trùng tên có sẵn thì file được lưu với tên khác (protocol.md §4.4). `FileDone.name` bên nhận
        # ĐÃ là tên lưu cuối: so với tên gốc (đã làm sạch) trong `info.names`, dự phòng tên của `offer`.
        original = self.original_name(update.file_index)
        if original is not None and update.path.name != original:
            self.renamed[update.file_index] = update.path.name
        else:
            self.renamed.pop(update.file_index, None)

    def apply_resumed(self, info: TransferInfo) -> None:
        if self.finished:
            return
        self.set_info(info)
        self.resumed = True
        self.raise_shown(info.done_bytes + info.unsynced_bytes, info.total_bytes)
        self._render()

    def apply_unreachable(self) -> None:
        if self.finished:
            return
        self.unreachable = True
        self.render_status()

    def apply_progress(self, update: TransferProgress) -> None:
        """Một nhịp tiến độ: chỉ `setValue` / `setText` tại chỗ (xem docstring module)."""
        if self.finished:
            return
        info = update.info
        self.info = info
        self.progress = update
        old_shown = self.shown_bytes
        self.raise_shown(update.shown_bytes, info.total_bytes)
        # App phát tiến độ mỗi nhịp cả khi RECONNECTING đứng yên: chỉ khi dữ liệu thật sự chảy mới bỏ
        # câu tường lửa / câu lượt khôi phục.
        flowing = self.shown_bytes > old_shown or info.status is TransferStatus.TRANSFERRING
        cleared = flowing and (self.resumed or self.unreachable)
        if cleared:
            self.resumed = False
            self.unreachable = False
        if cleared or info.status is not self.status:
            self.status = info.status
            self.render_status()
        elif self.status not in _WAITING_STATUSES and not (self.resumed or self.unreachable):
            if self._is_stalled() is not self.stalled_shown:
                self.render_status()  # đổi loại câu: cập nhật cả trình đọc màn hình
            else:
                detail = self._active_detail(self.context().peer)
                if detail != self.detail_label.text():
                    self.detail_label.setText(detail)
                if self.detail_label.isHidden() == bool(detail):
                    self.detail_label.setVisible(bool(detail))
                self._update_summary()

    def finish(self, update: TransferFinished) -> bool:
        """`TransferFinished`; True nếu bong bóng vừa kết thúc (SUSPENDED và sự kiện muộn → False)."""
        if update.result is TransferResult.SUSPENDED or self.finished:
            return False
        self.set_info(update.info)
        self.finished = True
        self.result = update
        receive_dir = self.context().receive_dir
        self.finished_receive_dir = receive_dir
        self._current_receive_dir = receive_dir
        if update.result is TransferResult.DONE:
            self.progress_bar.setValue(BAR_MAX)
        self.progress_bar.setVisible(False)
        self.cancel_button.setEnabled(False)
        self.cancel_button.setVisible(False)
        self.open_button.setVisible(
            update.result is TransferResult.DONE
            and self.key.direction is Direction.RECEIVE
            and self.last_path is not None
        )
        self.set_offer(None)  # lượt kết thúc: lời mời (nếu còn) không còn gì để trả lời
        self._render()
        return True

    # -- Vẽ chữ -----------------------------------------------------------------------------------

    def _title(self) -> str:
        if self.file_count == 1 and self.first_name is not None:
            return texts.file_label(self.first_name)
        return files_text(self.file_count)

    def _status(self, ctx: BubbleContext) -> tuple[Kind, str, str]:
        """(loại, nhãn ngắn, dòng phụ)."""
        peer = ctx.peer
        direction = self.key.direction
        if self.result is not None:
            result = self.result.result
            if result is TransferResult.DONE:
                t = QCoreApplication.translate
                if direction is Direction.RECEIVE:
                    detail = (
                        saved_as_text([self.renamed[i] for i in sorted(self.renamed)])
                        if self.renamed
                        else done_text()
                    )
                    return Kind.DONE, t("Chat", "Đã lưu"), detail
                return Kind.DONE, t("Chat", "Đã gửi"), done_text()
            return (
                result_kind(result),
                result_status(result),
                result_message(self.result, peer, self.finished_receive_dir),
            )
        if self.unreachable:
            return (
                Kind.RECONNECTING,
                short_status(direction, TransferStatus.RECONNECTING),
                unreachable_text(peer),
            )
        if self.resumed:
            return Kind.WAITING, short_status(direction, TransferStatus.WAITING), resumed_text(peer)
        waiting = waiting_detail(direction, self.status, peer, connected=ctx.connected)
        detail = waiting if waiting is not None else self._active_detail(peer)
        return status_kind(self.status), short_status(direction, self.status), detail

    def _active_detail(self, peer: str) -> str:
        status = self.status
        if status is TransferStatus.VERIFYING:
            return verifying_text(self.info)
        percent = percent_text(self.shown_bytes, self.total_bytes)
        if status is TransferStatus.RECONNECTING:
            return reconnecting_text(percent, peer)
        progress = self.progress
        if progress is None:
            return ""
        if self._is_stalled():
            return stalled_text(percent, self.key.direction, peer)
        return progress_text(progress, self.shown_bytes)

    def _is_stalled(self) -> bool:
        progress = self.progress
        return (
            self.status is TransferStatus.TRANSFERRING
            and progress is not None
            and progress.idle_seconds >= STALL_TEXT_AFTER
        )

    def render_status(self) -> None:
        """Vẽ lại icon, nhãn trạng thái, dòng phụ và câu tóm tắt."""
        ctx = self.context()
        self.stalled_shown = self._is_stalled()
        kind, status, detail = self._status(ctx)
        self.kind = kind
        if kind is Kind.ERROR:
            emphasis = BubbleEmphasis.DANGER
        elif self.offer_panel is not None:
            emphasis = BubbleEmphasis.ATTENTION
        else:
            emphasis = BubbleEmphasis.NONE
        self.set_emphasis(emphasis)
        if kind is Kind.DONE:
            self.status_icon.set_icon("checkmark", "success")
        elif kind is Kind.ERROR:
            self.status_icon.set_icon("warning", "danger")
        elif kind is Kind.CANCELLED:
            self.status_icon.set_icon("dismiss", "text_muted")
        else:
            self.status_icon.set_icon(None)
        set_tone(self.status_label, "accent" if kind in (Kind.ACTIVE, Kind.RECONNECTING) else None)
        set_tone(self.detail_label, None if kind is Kind.ERROR else "muted")
        self.status_label.setText(status)
        self.detail_label.setText(detail)
        self.detail_label.setVisible(bool(detail))
        self.progress_bar.setAccessibleDescription(status)
        self._update_summary(ctx, kind, status, detail)

    def _update_summary(
        self,
        ctx: BubbleContext | None = None,
        kind: Kind | None = None,
        status: str | None = None,
        detail: str | None = None,
    ) -> None:
        """Câu tóm tắt cho trình đọc màn hình; chỉ đặt khi phần không theo nhịp tốc độ đổi."""
        if ctx is None or kind is None or status is None or detail is None:
            ctx = self.context()
            kind, status, detail = self._status(ctx)
        t = QCoreApplication.translate
        moving = (
            not self.finished
            and kind in (Kind.ACTIVE, Kind.RECONNECTING)
            and not (self.unreachable or self.resumed)
        )
        percent = None
        if moving and self.total_bytes > 0 and self.status is not TransferStatus.VERIFYING:
            percent = min(99, self.shown_bytes * 100 // self.total_bytes)
        # Câu tốc độ theo nhịp không vào tên; câu đứng yên (“Đang chờ dữ liệu…”) thì vào, vì đó là đổi
        # loại câu và không đổi theo nhịp (dữ liệu không chạy nên % không đổi).
        tail = detail if not moving or self.stalled_shown else ""
        asking = self.offer_panel is not None
        key = (kind, status, percent, tail, ctx.peer, self._title(), self.total_bytes, asking)
        if key == self._summary_key:
            return
        self._summary_key = key
        if self.key.direction is Direction.SEND:
            who = texts.fill(t("Chat", "Gửi tới {name}"), name=ctx.peer)
        else:
            who = texts.fill(t("Chat", "Nhận từ {name}"), name=ctx.peer)
        parts = [who, f"{self._title()}, {texts.format_size(max(0, self.total_bytes))}", status]
        if percent is not None:
            parts.append(f"{percent}%")
        if tail:
            parts.append(tail)
        when = clock_text(self.at)
        if when:
            parts.append(when)
        if asking:
            parts.append(t("Chat", "Lời mời nhận file. Dùng Tab để tới nút Nhận hay Từ chối."))
        self.set_summary(". ".join(p.rstrip(".") for p in parts if p) + ".")

    def refresh_text(self) -> None:
        """Dựng lại mọi chữ (tiêu đề, cỡ, nút, trạng thái)."""
        self._render()

    def _render(self) -> None:
        t = QCoreApplication.translate
        if not hasattr(self, "key"):
            return  # `ChatBubble.__init__` gọi trước khi lớp con dựng xong
        title = self._title()
        self.title_label.set_full_text(title)
        self.size_label.setText(texts.format_size(max(0, self.total_bytes)))
        names = self.info.names if self.info is not None else self.offer_names
        self.icon_label.set_icon(file_icon(names, self.file_count))
        self.progress_bar.setAccessibleName(t("Chat", "Tiến độ"))
        self.cancel_button.set_label(t("Chat", "Hủy"))
        self.cancel_button.setAccessibleDescription(title)
        for button, text in (
            (self.open_button, t("Chat", "Hiện trong thư mục")),
            (self.resend_button, t("Chat", "Gửi lại")),
            (self.change_dir_button, change_dir_text()),
        ):
            button.setText(text)
            button.setAccessibleName(text)
            button.setAccessibleDescription(title)
        self._summary_key = None
        self.render_status()
        self._update_resend()
        self._update_change_dir()

    def _update_resend(self) -> None:
        self.resend_button.setVisible(self.resendable())

    def _update_change_dir(self) -> None:
        self.change_dir_button.setVisible(self.change_dir_available())

    def _on_cancel(self) -> None:
        if not self.finished and self.offer_panel is None:  # lời mời chỉ trả lời bằng Nhận / Từ chối
            self.cancel_clicked.emit()

    def _on_resend(self) -> None:
        if not self.resendable():
            return
        self._resend_used = True
        self._update_resend()
        self.resend_clicked.emit()


# ---- HistoryBubble ----------------------------------------------------------------------------


def _result_of(value: str) -> TransferResult | None:
    try:
        return TransferResult(value)
    except ValueError:
        return None


class HistoryBubble(_Bubble):
    """Bong bóng của một mục lịch sử (xem docstring module); không có “Gửi lại”."""

    open_clicked = Signal()

    def __init__(
        self,
        entry: HistoryEntry,
        parent: QWidget | None = None,
        *,
        peer: str | None = None,
        receive_dir: Path | None = None,
    ) -> None:
        direction = Direction(entry.direction)
        try:
            at = entry.finished_at.timestamp()
        except (OverflowError, OSError, ValueError):
            at = 0.0
        super().__init__(Side.OUT if direction is Direction.SEND else Side.IN, parent, at=at)
        self.entry = entry
        self.key = TransferKey(entry.device_id, direction, entry.transfer_id)
        self.finished = True
        result = _result_of(entry.result)
        self.kind = Kind.ERROR if result is None else result_kind(result)
        self._peer = peer
        self.open_button = _button(self)
        self.open_button.clicked.connect(self.open_clicked)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, theme.SPACING[0], 0, 0)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        self.body().addLayout(self.status_row)
        self.body().addWidget(self.detail_label)
        self.body().addLayout(buttons)
        self.set_emphasis(BubbleEmphasis.DANGER if self.kind is Kind.ERROR else BubbleEmphasis.NONE)
        self.set_receive_dir(receive_dir)
        self._render()

    def folder(self) -> Path | None:
        """Thư mục cha của `saved_path` (để mở), hay None."""
        saved = self.entry.saved_path
        return Path(saved).parent if saved else None

    def set_receive_dir(self, receive_dir: Path | None) -> None:
        """Thư mục nhận hiện tại: quyết định “Hiện trong thư mục” của đường dẫn UNC (`can_open_saved`)."""
        self.open_button.setVisible(can_open_saved(self.entry.saved_path, receive_dir))

    def set_peer(self, peer: str | None) -> None:
        self._peer = peer
        self._render()

    def focus_buttons(self) -> list[QWidget]:
        return [self.open_button] if not self.open_button.isHidden() else []

    def _render(self) -> None:
        if not hasattr(self, "entry"):
            return
        t = QCoreApplication.translate
        entry = self.entry
        if entry.file_count == 1 and entry.names:
            title = texts.file_label(entry.names[0])
        else:
            title = files_text(entry.file_count)
        self.title_label.set_full_text(title)
        when = clock_text(self.at)
        size = texts.format_size(max(0, entry.total_bytes))
        self.size_label.setText(f"{size} · {when}" if when else size)
        self.icon_label.set_icon(file_icon(entry.names, entry.file_count))
        result = _result_of(entry.result)
        if result is TransferResult.DONE:
            status = t("Chat", "Đã lưu") if self.key.direction is Direction.RECEIVE else t("Chat", "Đã gửi")
            self.status_icon.set_icon("checkmark", "success")
        else:
            status = t("Transfers", "Lỗi") if result is None else result_status(result)
            if self.kind is Kind.ERROR:
                self.status_icon.set_icon("warning", "danger")
            else:
                self.status_icon.set_icon("dismiss", "text_muted")
        self.status_label.setText(status)
        self.detail_label.setVisible(False)
        open_text = t("Chat", "Hiện trong thư mục")
        self.open_button.setText(open_text)
        self.open_button.setAccessibleName(open_text)
        self.open_button.setAccessibleDescription(title)
        peer = self._peer if self._peer is not None else texts.peer_label(entry.device_name, entry.device_id)
        if self.key.direction is Direction.SEND:
            who = texts.fill(t("Chat", "Gửi tới {name}"), name=peer)
        else:
            who = texts.fill(t("Chat", "Nhận từ {name}"), name=peer)
        parts = [who, f"{title}, {size}", status, when]
        self.set_summary(". ".join(p for p in parts if p) + ".")


# ---- PendingBubble ----------------------------------------------------------------------------


class PendingBubble(_Bubble):
    """Bong bóng tạm “Đang chuẩn bị…” của một lần gửi chưa có lượt (spec B3 mục 9b.22): OUT, icon
    theo loại file, tên hay “n file”, không cỡ (chưa `stat`), không thanh, không nút."""

    def __init__(
        self, token: int, names: Sequence[str], parent: QWidget | None = None, *, at: float = 0.0
    ) -> None:
        super().__init__(Side.OUT, parent, at=at)
        self.token = token
        self.names = tuple(names)
        self.finished = False
        self.size_label.setVisible(False)
        self.body().addLayout(self.status_row)
        self.body().addWidget(self.detail_label)
        set_tone(self.status_label, "muted")
        self.detail_label.setVisible(False)
        self._render()

    def _render(self) -> None:
        if not hasattr(self, "token"):
            return
        t = QCoreApplication.translate
        count = len(self.names)
        title = texts.file_label(self.names[0]) if count == 1 else files_text(count)
        self.title_label.set_full_text(title)
        self.icon_label.set_icon(file_icon(self.names, count))
        status = t("Chat", "Đang chuẩn bị…")
        self.status_label.setText(status)
        self.set_summary(f"{title}. {status}")


# ---- ClipboardNote ----------------------------------------------------------------------------


def clipboard_title(ok: bool) -> str:
    """Dòng 1 của `ClipboardNote`."""
    t = QCoreApplication.translate
    if ok:
        return t("Chat", "Clipboard · đã chép vào máy này")
    return t("Chat", "Clipboard · chưa chép được vào máy này")


def clipboard_unavailable_text() -> str:
    """Dòng 2 sau khi “Thử lại” không còn clip để chép (`NOTHING_TO_RETRY`)."""
    return QCoreApplication.translate("Chat", "Clipboard này không còn để chép lại.")


def preview_line(preview: str | None) -> str:
    """Dòng không trắng đầu tiên của `preview`, ký tự lạ thành U+FFFD, tối đa `NOTE_PREVIEW_CHARS`
    code point; không có → ""."""
    if not preview:
        return ""
    for line in preview[:NOTE_PREVIEW_CHARS].splitlines():
        shown = printable(line.strip())
        if shown:
            return shown
    return ""


def clipboard_detail(
    kind: ClipKind | str | None, size: int, preview: str | None, image_size: tuple[int, int] | None
) -> str:
    """Dòng 2 của `ClipboardNote` (xem docstring module)."""
    t = QCoreApplication.translate
    shown_size = texts.format_size(max(0, int(size)))
    if kind == ClipKind.PNG:
        if image_size is not None:
            width, height = image_size
            return texts.fill(
                t("Chat", "Ảnh {width} × {height} · {size}"),
                width=str(int(width)),
                height=str(int(height)),
                size=shown_size,
            )
        return texts.fill(t("Chat", "Ảnh · {size}"), size=shown_size)
    line = preview_line(preview)
    if line:
        return line
    return texts.fill(t("Chat", "Văn bản · {size}"), size=shown_size)


class ClipboardNote(QFrame):
    """Dòng mảnh báo clipboard vừa nhận trong luồng chat (xem docstring module)."""

    retry_clicked = Signal()
    focus_entered = Signal()

    def __init__(
        self,
        device_id: str,
        *,
        ok: bool,
        kind: ClipKind | str | None,
        size: int,
        preview: str | None = None,
        image_size: tuple[int, int] | None = None,
        peer: str = "",
        at: float = 0.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("clipboardNote")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)  # Tab do `ui.chat` (roving tabindex)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.device_id = device_id
        self.at = at
        self.ok = bool(ok)
        self.kind = kind
        self.byte_size = max(0, int(size))
        self._preview = preview[:NOTE_PREVIEW_CHARS] if isinstance(preview, str) else None
        self.image_size = image_size
        self._peer = peer
        self._unavailable = False

        self.icon_label = _IconLabel(_ICON)
        self.title_label = _label(caption=True)
        title_font = self.title_label.font()
        title_font.setWeight(QFont.Weight.DemiBold)
        self.title_label.setFont(title_font)
        self.title_label.setObjectName("clipboardNoteTitle")
        self.detail_label = _ElidedLabel(Qt.TextElideMode.ElideRight)
        self.detail_label.setObjectName("clipboardNoteDetail")
        self.detail_label.setFont(theme.font_for(theme.TextStyle.CAPTION, self.detail_label.font()))
        self.detail_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.retry_button = _button(self)
        self.retry_button.setObjectName("clipboardRetryButton")
        self.retry_button.clicked.connect(self.retry_clicked)

        lines = QVBoxLayout()
        lines.setContentsMargins(0, 0, 0, 0)
        lines.setSpacing(0)
        lines.addWidget(self.title_label)
        lines.addWidget(self.detail_label)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(theme.SPACING[1], theme.SPACING[0], theme.SPACING[1], theme.SPACING[0])
        layout.setSpacing(theme.SPACING[1])
        layout.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(lines, 1)
        layout.addWidget(self.retry_button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.retry_button.setVisible(not self.ok)
        self.icon_label.set_icon("clipboard_paste", "text_muted")
        self._render()

    @property
    def unavailable(self) -> bool:
        """“Thử lại” đã báo không còn clip để chép lại."""
        return self._unavailable

    def title(self) -> str:
        return self.title_label.text()

    def detail(self) -> str:
        return self.detail_label.full_text()

    def focus_buttons(self) -> list[QWidget]:
        button = self.retry_button
        return [button] if not button.isHidden() and button.isEnabled() else []

    def set_peer(self, peer: str) -> None:
        if peer != self._peer:
            self._peer = peer
            self._render()

    def set_busy(self, busy: bool) -> None:
        """Đang chờ kết quả “Thử lại”: tắt nút (bấm thêm không gửi yêu cầu nữa)."""
        self.retry_button.setEnabled(not busy)

    def set_unavailable(self) -> None:
        """“Thử lại” trả `NOTHING_TO_RETRY`: câu “không còn để chép lại”, ẩn nút."""
        self._unavailable = True
        if self.retry_button.hasFocus():
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.retry_button.setVisible(False)
        self._render()

    def _render(self) -> None:
        title = clipboard_title(self.ok)
        detail = (
            clipboard_unavailable_text()
            if self._unavailable
            else clipboard_detail(self.kind, self.byte_size, self._preview, self.image_size)
        )
        self.title_label.setText(title)
        self.detail_label.set_full_text(detail)
        self.retry_button.setText(texts.retry())
        t = QCoreApplication.translate
        self.retry_button.setAccessibleName(texts.retry())
        self.retry_button.setAccessibleDescription(title)
        summary = t("Chat", "Clipboard từ {name}: {title}. {detail}")
        self.setAccessibleName(texts.fill(summary, name=self._peer, title=title, detail=detail))

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self._render()

    def focusInEvent(self, event: QFocusEvent) -> None:
        super().focusInEvent(event)
        self.update()
        self.focus_entered.emit()

    def focusOutEvent(self, event: QFocusEvent) -> None:
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        super().paintEvent(event)
        if not self.hasFocus():
            return
        dark = theme.is_dark_palette(QApplication.palette())
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(theme.focus_ring_color(dark), 2))
            radius = theme.RADIUS_CONTROL
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), radius, radius)
        finally:
            painter.end()
