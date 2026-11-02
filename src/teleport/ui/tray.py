"""Biểu tượng ở khay hệ thống (mvp F9; spec D4) và menu của nó.

**Menu** (thứ tự M5, `actions()` trả đúng bốn mục, không kể dòng kẻ):
1. “Mở Teleport” (mục mặc định). Bấm vào biểu tượng (một lần hay hai lần) cũng như chọn mục này.
2. “Gửi file…”: **menu con** (`send_menu`, cha là menu chính; mục trong `actions()` là `menuAction()`
   của nó) gồm các máy đã ghép đôi theo thứ tự danh sách cuộc trò chuyện. Danh sách đọc lại ở
   `aboutToShow` của **cả** menu chính lẫn menu con, qua hàm cung cấp `set_send_targets_provider`
   (`ui.app` tiêm vào; khay không giữ model thiết bị). Trên Linux (StatusNotifierItem) menu con có thể
   không phát `aboutToShow`, nên danh sách có thể cũ tới lần mở menu chính sau: chấp nhận. Chữ mỗi mục
   là `SendTarget.label` (đã qua `texts.peer_label`), máy ngoại tuyến thêm “ (ngoại tuyến)” (lượt gửi
   vẫn tạo được, tự gửi khi máy đó lên mạng); `&` đổi thành `&&` **sau** khi điền (tên do máy kia đặt
   không thành phím tắt). Chọn một máy → `send_to_requested(device_id)`. Chưa ghép đôi máy nào: một mục
   tắt “Chưa ghép đôi với máy nào” và mục “Tìm máy mới…” (`discover_requested`).
3. “Tạm dừng nhận”: mục `checkable`, có dấu = đang tạm dừng. Bấm → `pause_toggled(bool)` (nối
   `QAction.triggered`, không `toggled`); dấu chọn đổi ngay khi bấm, còn trạng thái khay (`state.paused`,
   dấu biểu tượng, tooltip) chỉ đổi khi `ui.app` gọi `set_receiving_paused` sau khi node xác nhận (lệnh
   đó cũng đặt lại dấu chọn, dưới `QSignalBlocker`, không phát `pause_toggled`). Tạm dừng chặn
   `offer` file **mới** (lượt đang nhận vẫn tiếp tục) và bỏ clipboard gửi tới (mvp F8), chỉ trong
   phiên; không chặn việc gửi clipboard đi.
4. Dòng kẻ, “Thoát”.

“Gửi file…” và “Tạm dừng nhận” bật/tắt **chỉ** theo `TrayState.running` (`set_running`): node chưa
chạy (lần chạy đầu, đang khởi động, lỗi) thì hiện mà tắt.

**Trạng thái** (`TrayState`, dataclass thuần; `ui.app` đẩy vào bằng `set_running`, `set_activity`,
`set_receiving_paused`, `set_receiving_unavailable`, `flash_clipboard`), gom về một chỗ `_render()`:
- Dấu biểu tượng `tray_badge` (hàm thuần), ưu tiên UNAVAILABLE > PAUSED > CLIPBOARD > TRANSFERRING >
  NONE; node chưa chạy thì NONE. CLIPBOARD chỉ khi thông báo clipboard đang hiện là `received`. Thứ
  tự này khác có chủ ý với huy hiệu thẻ máy này (`ui.home`: đang truyền đứng đầu): khay cảnh báo trước
  việc người dùng dễ quên (không nhận file, đang tạm dừng).
- Biểu tượng (`make_icon(badge)`): logo + dấu tròn góc dưới phải, đường kính nửa cỡ icon, viền 1 px
  (2 px khi cỡ ≥ 32) màu `surface`. Khác cả hình lẫn màu (không chỉ bằng màu, mvp N12): TRANSFERRING
  chấm `accent_strong`; CLIPBOARD nền `accent_strong` hình tờ giấy có kẹp `surface`; PAUSED nền
  `warning` hai vạch dừng `surface`; UNAVAILABLE nền `danger` dấu “!” `surface`. Màu từ
  `theme.tokens(dark=False, accent=None)` (bộ mint cố định, không theo màu nhấn của người dùng). Vẽ bằng
  `QPainter`; icon có dấu thêm cỡ 20 và 40. Mỗi dấu dựng **một lần** lúc gọi đầu tiên (không lúc import)
  rồi cache; `_render()` chỉ `setIcon` khi dấu đổi. Không polling; hẹn giờ duy nhất là của thông báo
  clipboard (bên dưới).
- Tooltip `tray_tooltip` (hàm thuần, dịch lúc gọi, ngữ cảnh “Tray”): dòng 1 `texts.APP_NAME`; node chạy
  thì thêm dòng clipboard (nếu đang có, bên dưới), “Đang truyền n lượt” (có % tổng thì “Đang truyền n
  lượt · 60%”: `set_progress`, do `ui.transfers` đẩy cùng giá trị với tiêu đề cửa sổ, `ui.progress`;
  không có % hay không còn lượt nào thì câu cũ), rồi “Không nhận file: …” hay (nếu không) “Đã tạm
  dừng nhận file mới và clipboard”, không dòng nào thì “Sẵn sàng nhận”.
- **Chữ máy kia trong tooltip** (chỉ tên máy của dòng clipboard, mvp F8): tooltip khay là
  rich text trên X11 và Windows cắt nó ở `TOOLTIP_MAX_UNITS` đơn vị UTF-16. Tên đã qua
  `texts.peer_label` rồi `tray_safe` (`<` → `‹`, `>` → `›`, `&` → `＆`; không dùng
  `widgets.safe_tooltip` vì tooltip khay Windows là chữ thuần, thực thể HTML sẽ hiện nguyên văn), rồi
  bị cắt (thêm `…`) sao cho cả tooltip ≤ `TOOLTIP_MAX_UNITS` đơn vị UTF-16 (tên toàn emoji hay dấu kết
  hợp dài hơn số cột nhiều lần). Dòng cảnh báo (“Không nhận file: …” / “Đã tạm dừng…”) **không bao giờ**
  bị cắt: tên không còn chỗ cho ít nhất một ký tự thì bỏ cả dòng clipboard, vẫn quá thì bỏ dòng “Đang
  truyền”. Ngoài tên đó không có chữ nào của máy kia.
- **Clipboard** (`flash_clipboard(ClipNotice)`, mvp F8): `received` (“Vừa nhận clipboard từ
  X”), `write_failed` (“Chưa chép được clipboard từ X”), `too_large` (“Clipboard quá lớn nên không gửi.
  Hãy gửi dạng file.”). Hiện `CLIP_FLASH_MS` (đọc lúc dùng) bằng một `QTimer` một lần; thông báo mới
  thay thông báo cũ và đếm lại; node thôi chạy (`set_running(False)`) thì xóa. Không bóng thoại.

**Bóng thoại** (`show_message(text, folder=None)`, chỗ duy nhất hiện bóng thoại; gộp thông báo nhận xong
nằm ở `ui.notify` / `ui.transfers`): chỉ hiện khi có khay và biểu tượng đang hiện; khi thật sự hiện thì
nhớ `folder` của bóng thoại đó (None cũng nhớ). `folder` là `Path`, `shell.Reveal` (file vừa nhận, để
chọn sẵn trong Explorer) hay None. Người dùng bấm vào bóng thoại (`QSystemTrayIcon.messageClicked`) →
phát lại nguyên giá trị của bóng thoại gần nhất qua `message_clicked(object)`; `ui.app` quyết định hiện
file, mở thư mục hay đưa cửa sổ lên trước.
Bóng thoại luôn mang logo **không dấu** (`make_icon()`, cache), không đọc biểu tượng đang hiện và không
dùng icon chuẩn “i” của hệ thống.

**Không có khay** (`is_available()` False: một số môi trường Linux, `offscreen`): `show()` không làm gì,
đóng cửa sổ là thoát app; không có lối vào “Tạm dừng nhận” / “Gửi file…” (chấp nhận), mọi setter vẫn
chạy không lỗi. `is_available()` (hàm của module, `Tray.is_available` gọi lại nó) là seam cho test: mọi
chỗ trong `ui` hỏi qua `Tray.is_available()`, nên vá hàm module hay vá thuộc tính lớp đều có tác dụng.

Logo là của dự án (`ui/logo.py`, SVG nhúng trong mã), không tải gì. Menu nhận `LanguageChange` (qua event
filter) thì `retranslate()`: chữ menu, menu con và tooltip.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRectF, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from teleport.ui import logo, texts, theme
from teleport.ui.shell import Reveal

log = logging.getLogger(__name__)

_ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
_BADGE_EXTRA_SIZES = (20, 40)  # cỡ khay thường gặp ở 125 % / 250 %
CLIP_FLASH_MS = 5000  # ms hiện thông báo clipboard ở khay (đọc lúc dùng, test chỉnh được)
TOOLTIP_MAX_UNITS = 127  # đơn vị UTF-16 tối đa của tooltip khay (Windows cắt phần sau)
_ELLIPSIS = "…"
_ZWJ = "\u200d"
_TRAY_SAFE = str.maketrans({"<": "‹", ">": "›", "&": "＆"})


class ClipNoticeKind(StrEnum):
    """Loại thông báo clipboard ở khay."""

    RECEIVED = "received"  # vừa chép clipboard từ máy kia
    TOO_LARGE = "too_large"  # nội dung vừa sao chép quá lớn nên không gửi
    WRITE_FAILED = "write_failed"  # nhận được mà chưa chép được vào máy này


@dataclass(frozen=True, slots=True)
class ClipNotice:
    """Một thông báo clipboard: `label` là tên máy kia đã qua `texts.peer_label` (rỗng với `too_large`).

    Khay tự đưa `label` qua `tray_safe` và cắt theo ngân sách tooltip."""

    kind: ClipNoticeKind
    label: str = ""


@dataclass(frozen=True, slots=True)
class TrayState:
    """Trạng thái khay, tính ra dấu biểu tượng và tooltip."""

    running: bool = False
    active: int = 0  # số lượt chưa kết thúc (= `ChatView.active_count()`)
    paused: bool = False  # người dùng tạm dừng nhận (node đã xác nhận)
    unavailable: bool = False  # thư mục nhận hỏng: không nhận file
    clipboard: ClipNotice | None = None  # thông báo clipboard đang hiện (`flash_clipboard`)
    progress: int | None = None  # % tổng đang truyền (`set_progress`, cùng giá trị với tiêu đề cửa sổ)


class TrayBadge(StrEnum):
    """Dấu nhỏ ở góc biểu tượng khay."""

    NONE = "none"
    TRANSFERRING = "transferring"
    PAUSED = "paused"
    UNAVAILABLE = "unavailable"
    CLIPBOARD = "clipboard"


@dataclass(frozen=True, slots=True)
class SendTarget:
    """Một mục của menu con “Gửi file…”: `label` đã qua `texts.peer_label`."""

    device_id: str
    label: str
    online: bool


def tray_badge(state: TrayState) -> TrayBadge:
    """Dấu biểu tượng: UNAVAILABLE > PAUSED > CLIPBOARD > TRANSFERRING > NONE; node chưa chạy → NONE.

    CLIPBOARD chỉ khi thông báo clipboard đang hiện là `received`."""
    if not state.running:
        return TrayBadge.NONE
    if state.unavailable:
        return TrayBadge.UNAVAILABLE
    if state.paused:
        return TrayBadge.PAUSED
    if state.clipboard is not None and state.clipboard.kind is ClipNoticeKind.RECEIVED:
        return TrayBadge.CLIPBOARD
    if state.active > 0:
        return TrayBadge.TRANSFERRING
    return TrayBadge.NONE


def tray_safe(text: str) -> str:
    """Chữ do máy kia đặt để đưa vào tooltip khay: `<` → `‹`, `>` → `›`, `&` → `＆`.

    Tooltip khay là rich text trên X11 mà là chữ thuần trên Windows: đổi ký tự thay vì escape HTML để
    hiện đúng ở cả hai nơi. Không cắt độ dài (`tray_tooltip` lo ngân sách)."""
    return text.translate(_TRAY_SAFE)


def utf16_units(text: str) -> int:
    """Số đơn vị UTF-16 của `text` (cách Windows đếm độ dài tooltip khay)."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


def _cut_units(text: str, budget: int) -> str:
    """Phần đầu dài nhất của `text` ≤ `budget` đơn vị UTF-16 (không bao giờ tách cặp surrogate)."""
    used = 0
    for index, ch in enumerate(text):
        used += 2 if ord(ch) > 0xFFFF else 1
        if used > budget:
            return text[:index]
    return text


def _clip_line(notice: ClipNotice) -> tuple[str, str | None]:
    """(mẫu câu, tên) của dòng clipboard; `too_large` không có tên."""
    t = QCoreApplication.translate
    if notice.kind is ClipNoticeKind.TOO_LARGE:
        return t("Tray", "Clipboard quá lớn nên không gửi. Hãy gửi dạng file."), None
    if notice.kind is ClipNoticeKind.WRITE_FAILED:
        return t("Tray", "Chưa chép được clipboard từ {name}"), notice.label
    return t("Tray", "Vừa nhận clipboard từ {name}"), notice.label


def tray_tooltip(state: TrayState) -> str:
    """Tooltip của biểu tượng khay (xem docstring module); dịch lúc gọi; ≤ `TOOLTIP_MAX_UNITS` đơn vị
    UTF-16."""
    if not state.running:
        return texts.APP_NAME
    t = QCoreApplication.translate
    active: str | None = None
    if state.active > 0 and state.progress is not None:
        active = texts.fill(
            t("Tray", "Đang truyền %n lượt · {percent}%", None, state.active), percent=str(state.progress)
        )
    elif state.active > 0:
        active = t("Tray", "Đang truyền %n lượt", None, state.active)
    warning: str | None = None
    if state.unavailable:
        warning = t("Tray", "Không nhận file: không mở được thư mục nhận")
    elif state.paused:
        warning = t("Tray", "Đã tạm dừng nhận file mới và clipboard")

    def join(*lines: str | None) -> str:
        return "\n".join(line for line in (texts.APP_NAME, *lines) if line is not None)

    if state.clipboard is None:
        if active is None and warning is None:
            return _cut_units(join(t("Tray", "Sẵn sàng nhận")), TOOLTIP_MAX_UNITS)
    else:
        template, name = _clip_line(state.clipboard)
        clip = template if name is None else texts.fill(template, name=tray_safe(name))
        if utf16_units(join(clip, active, warning)) <= TOOLTIP_MAX_UNITS:
            return join(clip, active, warning)
        if name is not None:  # rút gọn tên trước, còn ít nhất một ký tự của tên
            name = tray_safe(name)
            bare = utf16_units(join(texts.fill(template, name=""), active, warning))
            room = TOOLTIP_MAX_UNITS - bare - utf16_units(_ELLIPSIS)
            short = _cut_units(name, max(0, room)).rstrip(_ZWJ)
            if short:
                return join(texts.fill(template, name=short + _ELLIPSIS), active, warning)
        # Không vừa: bỏ dòng clipboard (rồi dòng “Đang truyền”), không bao giờ cắt dòng cảnh báo.
    text = join(active, warning)
    if utf16_units(text) <= TOOLTIP_MAX_UNITS:
        return text
    return _cut_units(join(warning), TOOLTIP_MAX_UNITS)  # APP_NAME + cảnh báo luôn vừa ngân sách


def offline_target_text(label: str) -> str:
    """Chữ mục của máy ngoại tuyến trong menu con “Gửi file…” (chưa escape `&`)."""
    return texts.fill(QCoreApplication.translate("Tray", "{name} (ngoại tuyến)"), name=label)


def no_targets_text() -> str:
    """Mục tắt của menu con khi chưa ghép đôi máy nào."""
    return QCoreApplication.translate("Tray", "Chưa ghép đôi với máy nào")


def discover_text() -> str:
    """Mục “Tìm máy mới…” của menu con khi chưa ghép đôi máy nào."""
    return QCoreApplication.translate("Tray", "Tìm máy mới…")


def _menu_text(text: str) -> str:
    """Chữ hiện trên mục menu: `&` thành `&&` (không thành phím tắt)."""
    return text.replace("&", "&&")


def is_available() -> bool:
    """Hệ thống có khay để đặt biểu tượng không."""
    return QSystemTrayIcon.isSystemTrayAvailable()


def _draw(size: int) -> QPixmap:
    """Logo của dự án cỡ `size` px (`packaging/pyinstaller/make_icon.py` cũng dựng `teleport.ico` từ đây)."""
    return logo.pixmap(size)


def _draw_badged(size: int, badge: TrayBadge) -> QPixmap:
    """Logo cỡ `size` kèm dấu `badge` ở góc dưới phải (xem docstring module)."""
    pixmap = _draw(size)
    if badge is TrayBadge.NONE:
        return pixmap
    if pixmap.isNull():
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
    t = theme.tokens(dark=False, accent=None)
    border = 2.0 if size >= 32 else 1.0
    diameter = size / 2
    outer = QRectF(size - diameter, size - diameter, diameter, diameter)
    circle = outer.adjusted(border / 2, border / 2, -border / 2, -border / 2)
    fill = {
        TrayBadge.TRANSFERRING: t.accent_strong,
        TrayBadge.CLIPBOARD: t.accent_strong,
        TrayBadge.PAUSED: t.warning,
        TrayBadge.UNAVAILABLE: t.danger,
    }[badge]
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(t.surface, border))
        painter.setBrush(QBrush(fill))
        painter.drawEllipse(circle)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(t.surface))
        inner = circle.adjusted(border / 2, border / 2, -border / 2, -border / 2)
        cx, cy, d = inner.center().x(), inner.center().y(), inner.width()
        if badge is TrayBadge.PAUSED:
            bar_w, bar_h, gap = max(1.0, d * 0.16), d * 0.5, max(1.0, d * 0.14)
            for x in (cx - gap / 2 - bar_w, cx + gap / 2):
                painter.drawRect(QRectF(x, cy - bar_h / 2, bar_w, bar_h))
        elif badge is TrayBadge.UNAVAILABLE:
            bar_w = max(1.0, d * 0.16)
            top, stem = cy - d * 0.3, d * 0.36
            painter.drawRect(QRectF(cx - bar_w / 2, top, bar_w, stem))
            dot = max(1.0, d * 0.16)
            painter.drawRect(QRectF(cx - dot / 2, cy + d * 0.3 - dot, dot, dot))
        elif badge is TrayBadge.CLIPBOARD:
            # Tờ giấy `surface` có kẹp ở mép trên: khác hình chấm của TRANSFERRING (cùng màu nền).
            sheet_w, sheet_h = d * 0.46, d * 0.52
            sheet = QRectF(cx - sheet_w / 2, cy - sheet_h / 2 + d * 0.06, sheet_w, sheet_h)
            painter.drawRect(sheet)
            clip_w, clip_h = max(1.0, d * 0.26), max(1.0, d * 0.16)
            painter.drawRect(QRectF(cx - clip_w / 2, sheet.top() - clip_h * 0.6, clip_w, clip_h))
            painter.setBrush(QBrush(fill))  # khe dưới kẹp: kẹp tách khỏi tờ giấy
            painter.drawRect(QRectF(cx - clip_w / 2, sheet.top() + clip_h * 0.4, clip_w, max(1.0, d * 0.06)))
    finally:
        painter.end()
    return pixmap


_icon_cache: dict[TrayBadge, QIcon] = {}


def make_icon(badge: TrayBadge = TrayBadge.NONE) -> QIcon:
    """Biểu tượng của app (cửa sổ, khay, bóng thoại), vẽ ở nhiều cỡ; `badge` thêm dấu trạng thái.

    Mỗi dấu dựng một lần lúc gọi đầu tiên rồi cache (QIcon chia sẻ ngầm, trả lại cùng một icon).
    """
    badge = TrayBadge(badge)
    icon = _icon_cache.get(badge)
    if icon is None:
        icon = QIcon()
        sizes = _ICON_SIZES if badge is TrayBadge.NONE else sorted((*_ICON_SIZES, *_BADGE_EXTRA_SIZES))
        for size in sizes:
            icon.addPixmap(_draw_badged(size, badge))
        _icon_cache[badge] = icon
    return icon


class Tray(QObject):
    """Biểu tượng khay và menu bốn mục (xem docstring module). Chỉ hiện khi gọi `show()` và có khay."""

    open_requested = Signal()
    quit_requested = Signal()
    message_clicked = Signal(object)  # Path | shell.Reveal | None: `folder` của bóng thoại gần nhất
    send_to_requested = Signal(str)  # device_id chọn ở menu con “Gửi file…”
    discover_requested = Signal()  # “Tìm máy mới…” của menu con (chưa ghép đôi máy nào)
    pause_toggled = Signal(bool)  # người dùng bấm “Tạm dừng nhận” (True: muốn tạm dừng)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._message_folder: Path | Reveal | None = None
        self._state = TrayState()
        self._disposed = False  # sau `dispose()` mục menu đã bị xóa: bỏ mọi lần vẽ lại
        self._targets_provider: Callable[[], Sequence[SendTarget]] | None = None
        self._menu = QMenu()
        self._menu.installEventFilter(self)
        self._send_menu = QMenu(self._menu)
        self._send_menu.setObjectName("traySendMenu")
        self._open = QAction(self._menu)
        self._send = self._send_menu.menuAction()
        self._pause = QAction(self._menu)
        self._pause.setCheckable(True)
        self._quit = QAction(self._menu)
        self._open.triggered.connect(self.open_requested)
        self._pause.triggered.connect(self._on_pause_triggered)
        self._quit.triggered.connect(self.quit_requested)
        self._menu.addAction(self._open)
        self._menu.addAction(self._send)
        self._menu.addAction(self._pause)
        self._menu.addSeparator()
        self._menu.addAction(self._quit)
        self._menu.setDefaultAction(self._open)
        self._menu.aboutToShow.connect(self._rebuild_send_menu)
        self._send_menu.aboutToShow.connect(self._rebuild_send_menu)
        self._clip_timer = QTimer(self)  # tắt thông báo clipboard sau `CLIP_FLASH_MS`
        self._clip_timer.setSingleShot(True)
        self._clip_timer.timeout.connect(self._clear_clipboard)
        self._icon_badge = TrayBadge.NONE
        self._icon = QSystemTrayIcon(make_icon(), self)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._on_activated)
        self._icon.messageClicked.connect(self._on_message_clicked)
        self.retranslate()
        self._render()

    @staticmethod
    def is_available() -> bool:
        """Seam: gọi `tray.is_available()` của module lúc dùng."""
        return is_available()

    def actions(self) -> list[QAction]:
        """Bốn mục của menu theo thứ tự (không kể dòng kẻ); “Gửi file…” là `menuAction()` của menu con."""
        return [self._open, self._send, self._pause, self._quit]

    @property
    def menu(self) -> QMenu:
        return self._menu

    @property
    def send_menu(self) -> QMenu:
        """Menu con “Gửi file…” (dựng lại mỗi lần menu chính hay menu con sắp hiện)."""
        return self._send_menu

    # ---- Trạng thái ----------------------------------------------------------------------------

    @property
    def state(self) -> TrayState:
        return self._state

    @property
    def badge(self) -> TrayBadge:
        """Dấu đang vẽ trên biểu tượng."""
        return self._icon_badge

    def tooltip(self) -> str:
        """Tooltip đang đặt cho biểu tượng."""
        return self._icon.toolTip()

    def set_running(self, running: bool) -> None:
        """Node đang chạy: bật “Gửi file…” và “Tạm dừng nhận”, tooltip có dòng trạng thái.

        Thôi chạy thì xóa thông báo clipboard đang hiện."""
        if running:
            self._apply(replace(self._state, running=True))
            return
        self._clip_timer.stop()
        self._apply(replace(self._state, running=False, clipboard=None))

    def flash_clipboard(self, notice: ClipNotice) -> None:
        """Hiện thông báo clipboard `CLIP_FLASH_MS` ms (dấu CLIPBOARD khi `received`, dòng tooltip).

        Thông báo mới thay thông báo cũ và đếm lại từ đầu. Không bóng thoại; node chưa chạy → bỏ qua."""
        if not isinstance(notice, ClipNotice) or not self._state.running:
            return
        self._apply(replace(self._state, clipboard=notice))
        self._clip_timer.start(max(0, int(CLIP_FLASH_MS)))

    def _clear_clipboard(self) -> None:
        self._apply(replace(self._state, clipboard=None))

    def set_activity(self, active: int) -> None:
        """Số lượt chưa kết thúc (âm coi là 0)."""
        self._apply(replace(self._state, active=max(0, int(active))))

    def set_progress(self, percent: int | None) -> None:
        """% tổng đang truyền cho tooltip (`ui.transfers` đẩy cùng giá trị với tiêu đề cửa sổ).

        Không phải `int` (kể cả `bool`) hay ngoài 0…100 → None (tooltip câu cũ)."""
        value = percent if type(percent) is int and 0 <= percent <= 100 else None
        self._apply(replace(self._state, progress=value))

    def set_receiving_paused(self, paused: bool) -> None:
        """Node xác nhận đang tạm dừng (True) hay đang nhận (False): dấu chọn, dấu biểu tượng, tooltip.

        Không phát `pause_toggled`."""
        paused = bool(paused)
        with QSignalBlocker(self._pause):
            self._pause.setChecked(paused)
        self._apply(replace(self._state, paused=paused))

    def set_receiving_unavailable(self, unavailable: bool) -> None:
        """Thư mục nhận hỏng, node không nhận file."""
        self._apply(replace(self._state, unavailable=bool(unavailable)))

    def set_send_targets_provider(self, provider: Callable[[], Sequence[SendTarget]] | None) -> None:
        """Hàm trả các máy cho menu con “Gửi file…”, gọi mỗi lần menu sắp hiện (None: không máy nào)."""
        self._targets_provider = provider

    def _apply(self, state: TrayState) -> None:
        if self._disposed:
            return
        if state != self._state:
            self._state = state
            self._render()

    def _render(self) -> None:
        """Áp `_state` vào mục menu, biểu tượng (chỉ khi dấu đổi) và tooltip."""
        running = self._state.running
        self._send.setEnabled(running)
        self._pause.setEnabled(running)
        badge = tray_badge(self._state)
        if badge is not self._icon_badge:
            self._icon_badge = badge
            self._icon.setIcon(make_icon(badge))
        tooltip = tray_tooltip(self._state)
        if tooltip != self._icon.toolTip():
            self._icon.setToolTip(tooltip)

    # ---- Menu ----------------------------------------------------------------------------------

    def retranslate(self) -> None:
        self._open.setText(texts.menu_open())
        self._send.setText(texts.menu_send())
        self._send_menu.setTitle(texts.menu_send())
        self._pause.setText(texts.menu_pause())
        self._quit.setText(texts.menu_quit())
        self._menu.setAccessibleName(QCoreApplication.translate("Tray", "Menu của Teleport"))
        self._send_menu.setAccessibleName(texts.menu_send())
        self._icon.setToolTip(tray_tooltip(self._state))
        self._rebuild_send_menu()

    def _targets(self) -> list[SendTarget]:
        provider = self._targets_provider
        if provider is None:
            return []
        try:
            return [t for t in provider() if isinstance(t, SendTarget)]
        except Exception as e:
            log.warning("không đọc được danh sách máy cho menu khay: %s", type(e).__name__)
            return []

    def _rebuild_send_menu(self) -> None:
        """Dựng lại menu con “Gửi file…” từ hàm cung cấp (xem docstring module)."""
        menu = self._send_menu
        menu.clear()
        targets = self._targets()
        if not targets:
            empty = menu.addAction(_menu_text(no_targets_text()))
            empty.setEnabled(False)
            discover = menu.addAction(_menu_text(discover_text()))
            discover.triggered.connect(self.discover_requested)
            return
        for target in targets:
            text = target.label if target.online else offline_target_text(target.label)
            action = menu.addAction(_menu_text(text))
            device_id = target.device_id
            action.triggered.connect(lambda _checked=False, i=device_id: self.send_to_requested.emit(i))

    def _on_pause_triggered(self, checked: bool) -> None:
        self.pause_toggled.emit(bool(checked))

    # ---- Hiện / ẩn, bóng thoại -----------------------------------------------------------------

    def show(self) -> None:
        """Hiện biểu tượng nếu hệ thống có khay."""
        if Tray.is_available():
            self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    @property
    def visible(self) -> bool:
        return self._icon.isVisible()

    def show_message(self, text: str, folder: Path | Reveal | None = None) -> None:
        """Bóng thoại từ biểu tượng khay (không làm gì nếu không có khay hay biểu tượng đang ẩn).

        `folder`: thư mục mở (`Path`) hay file cần hiện (`shell.Reveal`) khi người dùng bấm vào bóng
        thoại, phát lại nguyên qua `message_clicked`; chỉ nhớ khi bóng thoại thật sự hiện.
        """
        if Tray.is_available() and self._icon.isVisible():
            self._message_folder = folder
            self._icon.showMessage(texts.APP_NAME, text, make_icon())  # logo không dấu, không icon “i”

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._menu and event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        return super().eventFilter(watched, event)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.open_requested.emit()

    def _on_message_clicked(self) -> None:
        self.message_clicked.emit(self._message_folder)

    def dispose(self) -> None:
        """Ẩn biểu tượng và xóa menu (menu không có cha Qt; menu con là con của nó).

        Dừng hẹn giờ thông báo clipboard và bỏ mọi cập nhật sau đó: mục menu đã bị xóa. Gọi lại thì thôi."""
        if self._disposed:
            return
        self._disposed = True
        self._clip_timer.stop()
        self._icon.hide()
        self._menu.deleteLater()
