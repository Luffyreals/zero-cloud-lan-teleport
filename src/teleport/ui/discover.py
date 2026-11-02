"""Trang “Tìm máy mới” (`Page.DISCOVER`, mvp F2, F3, N12): radar vòng tròn, ô “Nhập IP…”, dạng danh sách.

**Nguồn dữ liệu**: đúng một `radar.DeviceListModel` (cửa sổ chính truyền `window.devices`). Trang
chỉ đọc model và theo signal của nó (`modelReset`, `rowsInserted`, `rowsRemoved`, `rowsMoved`,
`dataChanged`, `layoutChanged`), mỗi lần đồng bộ lại toàn bộ (`_sync`), không giữ bản sao danh sách.
Máy hiện ở đây (`discover_devices`, hàm thuần): đang trong mạng hay đang kết nối; máy đã ghép đôi
ngoại tuyến không hiện. Thứ tự (dùng chung cho Tab, đặt bong bóng, hàng danh sách): máy chưa ghép đôi
trước, rồi theo NFC(tên).casefold(), rồi `device_id`.

**Dạng hiển thị** (`view_mode`, `list_reason`): xét theo thứ tự, gặp đúng đầu tiên thì dừng: quá
`RADAR_MAX` máy → danh sách (TOO_MANY); không đặt được mọi bong bóng ở cỡ khung hiện tại → danh sách
(NO_ROOM); người dùng chọn `"list"` → danh sách (PREFERENCE); còn lại radar. Bị ép sang danh sách thì
ẩn `view_button`, hiện câu lý do (`mode_reason_label`) cùng hàng câu gợi ý; lựa chọn người dùng giữ
nguyên, nên số máy giảm hay cửa sổ rộng ra thì tự về dạng đã chọn. Trước lần đổi cỡ thật đầu tiên của
khung (`stack`) coi như đủ chỗ. Thanh thông báo (`info_bar`) nằm trong layout, nên cửa sổ nhỏ mà thanh
lỗi hiện thì có thể sang danh sách. Lựa chọn lưu ở `radar_view` của `settings.json` qua `ui.app`
(`view_preference_changed` chỉ phát khi người dùng bấm `view_button`; `set_view_preference` không
phát). Mặc định là radar.

**Bố cục bong bóng** (`place_bubbles`, hàm thuần, xác định): ứng viên là `Slot(vòng, góc)` trên ba
elip đồng tâm (`RING_FRACTIONS` của bán trục `rx = area.w/2 − bubble.w/2`, `ry` tương tự), `ANGLES`
góc đều từ đỉnh, thử góc theo `ANGLE_ORDER` (đỉnh, đáy, phải, trái, rồi các góc chéo). Một chỗ hợp lệ
khi nằm trọn trong `area`, cách tâm (`core`) và mọi bong bóng đã đặt ít nhất `BUBBLE_GAP`; hình chữ
nhật có góc trên trái số nguyên, kiểm trên hình đã làm tròn. Máy đã ghép đôi thử vòng trong trước
(ưu tiên, không bảo đảm), máy chưa ghép thử vòng ngoài trước. **Giữ chỗ**: bước 1 giữ mọi chỗ cũ
(`previous`) còn hợp lệ theo thứ tự `items`, bước 2 đặt các máy còn lại vào ứng viên hợp lệ đầu tiên;
không đặt được mà `previous` khác rỗng thì làm lại một lần với `{}` rồi mới trả `None`. Mục `previous`
hỏng (không phải `Slot`, vòng hay góc ngoài miền) bị bỏ qua như máy mới. `RadarCanvas` bỏ chỗ cũ của máy
vừa đổi trạng thái ghép đôi; đánh đổi đã chấp nhận: máy đã ghép đang ở vòng ngoài không tự dời vào
trong. **Không bao giờ đặt theo băm `device_id`**: chỗ chỉ phụ thuộc thứ tự, chỗ cũ và hình học (máy kia
chọn được `device_id` thì cũng không chọn được chỗ). Va chạm thì lấy ứng viên kế, đổi tức thì, không
hoạt ảnh. Mọi bong bóng cùng cỡ (`bubble_size`), không theo tên; tính lại khi font đổi.

**Bong bóng** (`RadarBubble`, tự vẽ bằng `QPainter`, màu từ `theme.tokens_for` lúc vẽ):
- Chưa ghép đôi: nền `surface_raised`, viền 1 px `border_strong`, bo `RADIUS_BLOCK`; avatar 40 px
  (`paint_avatar`, không chấm trạng thái); tên (font điểm nhấn cỡ BODY) màu `text`, cắt “…”; dòng phụ
  “Chưa ghép đôi” CAPTION màu `accent_text`.
- Đã ghép đôi (“mờ”): không tô nền, viền 1 px `border`; chỉ avatar mờ (opacity 0,6); tên và “Đã ghép”
  màu `text_muted`. Chữ không bao giờ vẽ mờ.
- Rê chuột: nền `selected`. Nhấn: viền 2 px `accent_strong`. Tiêu điểm: viền 2 px `focus_ring_color`.
- Lỗi kết nối gần nhất (`FAILURE_ROLE` của model) chỉ hiện ở dạng danh sách, không trên bong bóng.

**Tâm “Bạn”**: avatar 56 px nhấn màu + nhãn “Bạn”, giữa canvas; chỉ trang trí (không nhận tiêu điểm).
Nền canvas: hai elip tĩnh ở vòng trong và vòng ngoài, nét 1 px `border`.

**Vòng sóng** (trang trí): ba elip nở từ viền tâm ra vòng ngoài, lệch pha 1/3, nét 2 px
`accent_strong`, alpha 0,45 → 0. Một `QVariantAnimation` dài `WAVE_TOTAL_MS` (đọc lại mỗi lần chạy,
cùng `WAVE_CYCLE_MS`), tự dừng (mvp N3, WCAG 2.2.2). Chạy lại khi trang hiện, cửa sổ thôi thu nhỏ, danh
sách từ rỗng thành có hay ngược lại; dừng ngay khi trang ẩn (kể cả xuống khay), cửa sổ thu nhỏ (event
filter trên `window()` cài ở lần hiện đầu, bắt `WindowStateChange`), đang ở dạng danh sách; không chạy
khi `motion.animations_enabled()` là False (đọc mỗi lần chạy).

**Ô “Nhập IP…”** (`_AddressField`, trong `PageHeader`): Esc khi ô **có chữ**: ô nhận `ShortcutOverride`
(nên `_back_action` của cửa sổ không chạy) rồi `keyPressEvent` xóa chữ, kéo theo ẩn lỗi địa chỉ. Ô
**rỗng**: không nhận `ShortcutOverride`, Esc tới `_back_action`, trang quay về. Enter = `submit_address`:
sai → thanh lỗi với câu mvp mục 8 (`radar.invalid_address_text`, không hiện `str(e)` của
`parse_manual_address`), giữ tiêu điểm và chọn hết chữ, không signal; đúng → xóa ô, phát
`manual_address_entered(ip, cổng)`, trang vẫn mở. Gõ chữ thì ẩn lỗi địa chỉ đang hiện; thông báo
SUCCESS (`show_notice`) không ẩn theo. Trang bị ẩn không do hệ điều hành (đổi trang, xuống khay) thì
xóa thanh thông báo.

**Kích hoạt một máy** (bấm, bấm đúp, Enter, Space, trên bong bóng hay hàng danh sách) đều qua
`_activate(device_id)`: đọc lại view mới nhất của model (không còn thì thôi); **chặn phát hai lần**:
cùng máy vừa kích hoạt trong `QApplication.doubleClickInterval()` thì bỏ (một lần bấm đúp là press,
release, press, dblclick, release nên có thể sinh hai `clicked`; đo bằng seam cấp module `_now`, đọc
lúc gọi; mốc ghi sau khi phát). Chưa ghép đôi và đang trong mạng → `pair_requested(view)`; đã ghép đôi
→ `open_device_requested(device_id)`; còn lại không làm gì. Enter tự lặp khi giữ phím bị bỏ.

**Bàn phím và trình đọc màn hình** (mvp N12): Tab đi “Quay lại” → ô nhập → “Ghép đôi” → thanh thông
báo (khi hiện) → câu gợi ý → `view_button` / `wait_button` (khi hiện) → từng bong bóng theo thứ tự
`discover_devices` (radar) hoặc danh sách → câu “chưa thấy máy” (khi hiện); đặt lại sau mỗi lần đồng
bộ. Trên bong bóng: Trái/Lên, Phải/Xuống sang bong bóng trước/sau (không vòng), Home/End về đầu/cuối.
Tiêu điểm khi mở trang (`setFocusProxy`): bong bóng chưa ghép đôi đầu tiên; dạng danh sách có hàng →
danh sách; còn lại ô nhập. Bong bóng đang có tiêu điểm bị bỏ → tiêu điểm sang bong bóng kế, không có
thì bong bóng trước, không còn thì ô nhập; tự sang danh sách khi đang ở một bong bóng → danh sách, đúng
hàng máy đó. Tên trợ năng của bong bóng có tên và trạng thái bằng chữ; tooltip chỉ dựng qua
`widgets.safe_tooltip`. Chữ của máy khác luôn qua `texts.peer_label`, vẽ/hiện dạng chữ thuần.

**Nút “Chờ ghép đôi”** (`wait_button`): ẩn tới khi `set_wait_pairing_available(True)`;
`ui.wait_pairing.WaitPairingController` gọi nó và nối `wait_pairing_requested` → mở trang “Chờ ghép
đôi” (mvp mục 7.5), nên khi chạy qua `GuiApp` nút luôn hiện.

Câu chữ ở ngữ cảnh `"Discover"`, gọi `QCoreApplication.translate` lúc dùng; `retranslate()` khi nhận
`LanguageChange`.
"""

from __future__ import annotations

import functools
import itertools
import math
import time
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any

from PySide6.QtCore import (
    QAbstractAnimation,
    QCoreApplication,
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QPersistentModelIndex,
    QPointF,
    QRectF,
    QSize,
    QSizeF,
    QSortFilterProxyModel,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QHideEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QResizeEvent,
    QShowEvent,
    QWindowStateChangeEvent,
)
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from teleport.app.devices import DeviceView, parse_manual_address
from teleport.ui import motion, texts, theme
from teleport.ui.radar import (
    DEVICE_ID_ROLE,
    DEVICE_ROLE,
    DeviceListModel,
    invalid_address_text,
    no_devices_text,
)
from teleport.ui.widgets import (
    AvatarKind,
    DeviceAvatar,
    InfoBar,
    InfoLevel,
    PageHeader,
    Presence,
    paint_avatar,
    safe_tooltip,
)

RADAR_MAX = 8  # quá số máy này thì luôn hiện dạng danh sách
ANGLES = 16  # θ_k = −90° + k·360°/ANGLES (k = 0 là đỉnh)
ANGLE_ORDER = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
RING_FRACTIONS = (0.5, 0.75, 1.0)  # phần bán trục của vòng INNER, MIDDLE, OUTER
BUBBLE_GAP = theme.SPACING[1]  # px, khoảng cách tối thiểu giữa hai bong bóng, giữa bong bóng và tâm
BUBBLE_WIDTH = 136  # px
BUBBLE_PADDING = theme.SPACING[1]  # px, đệm trên và dưới của bong bóng
BUBBLE_AVATAR = 40  # px
_AVATAR_TEXT_GAP = 4  # px, từ avatar tới dòng tên
_BUBBLE_TEXT_MARGIN = theme.SPACING[1]  # px, lề trái/phải của chữ trong bong bóng
_CORE_AVATAR = 56  # px, avatar “Bạn” ở tâm
_CORE_GAP = 4  # px, từ avatar “Bạn” tới nhãn
_PAIRED_AVATAR_OPACITY = 0.6
WAVE_CYCLE_MS = 2400  # một vòng sóng nở hết
WAVE_TOTAL_MS = 4800  # mỗi lần chạy (hai chu kỳ) rồi tự dừng
_WAVE_COUNT = 3
_WAVE_ALPHA = 0.45
_ADDRESS_MAX_LENGTH = 64
_ADDRESS_WIDTH = 220  # px, ô “Nhập IP…”
_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)
_ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)
_PLAIN_MODIFIERS = (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier)
_Index = QModelIndex | QPersistentModelIndex

_now = time.monotonic  # seam test: đồng hồ của việc chặn kích hoạt hai lần (đọc lúc gọi)


# ---- Câu chữ -----------------------------------------------------------------------------------


def page_title() -> str:
    """Tiêu đề trang, cũng là tên trợ năng của trang."""
    return QCoreApplication.translate("Discover", "Tìm máy mới")


def _paired_caption(paired: bool) -> str:
    """Dòng phụ của bong bóng."""
    if paired:
        return QCoreApplication.translate("Discover", "Đã ghép")
    return QCoreApplication.translate("Discover", "Chưa ghép đôi")


def _bubble_accessible_name(name: str, paired: bool) -> str:
    if paired:
        template = QCoreApplication.translate("Discover", "{name}, đã ghép đôi")
    else:
        template = QCoreApplication.translate("Discover", "{name}, chưa ghép đôi")
    return texts.fill(template, name=name)


def _bubble_hint(paired: bool) -> str:
    if paired:
        return QCoreApplication.translate("Discover", "Đã ghép đôi. Nhấn Enter để mở.")
    return QCoreApplication.translate("Discover", "Nhấn Enter để ghép đôi.")


def _status_text(view: DeviceView) -> str:
    """Trạng thái bằng chữ cho tooltip của bong bóng."""
    t = QCoreApplication.translate
    if not view.paired:
        return t("Discover", "Chưa ghép đôi, đang trong mạng")
    if view.connected:
        return t("Discover", "Đã ghép đôi, đã kết nối")
    return t("Discover", "Đã ghép đôi, đang trong mạng")


def _mode_reason_text(reason: ListReason, count: int) -> str:
    t = QCoreApplication.translate
    if reason is ListReason.TOO_MANY:
        return t("Discover", "Có %n máy trong mạng nên hiện dạng danh sách.", None, count)
    if reason is ListReason.NO_ROOM:
        return t("Discover", "Cửa sổ chưa đủ rộng cho dạng vòng tròn nên hiện dạng danh sách.")
    return ""


# ---- Máy nào hiện ------------------------------------------------------------------------------


def _discover_key(view: DeviceView) -> tuple[bool, str, str]:
    """Chưa ghép đôi trước, rồi NFC(tên).casefold(), rồi `device_id`."""
    return (view.paired, unicodedata.normalize("NFC", view.name or "").casefold(), view.device_id)


def _shown(view: DeviceView) -> bool:
    return view.online or view.connected


def discover_devices(views: Iterable[DeviceView]) -> list[DeviceView]:
    """Các máy hiện trên trang (đang trong mạng hay đang kết nối), theo thứ tự `_discover_key`."""
    return sorted((v for v in views if isinstance(v, DeviceView) and _shown(v)), key=_discover_key)


# ---- Bố cục bong bóng --------------------------------------------------------------------------


class Ring(IntEnum):
    INNER = 0
    MIDDLE = 1
    OUTER = 2


@dataclass(frozen=True)
class Slot:
    """Một chỗ trên radar: vòng và chỉ số góc (`0 ≤ angle < ANGLES`)."""

    ring: Ring
    angle: int


def _ring_order(paired: bool) -> tuple[Ring, ...]:
    if paired:
        return (Ring.INNER, Ring.MIDDLE, Ring.OUTER)
    return (Ring.OUTER, Ring.MIDDLE, Ring.INNER)


def _clean_slot(value: object) -> Slot | None:
    """`value` nếu là một `Slot` dùng được, không thì None (mục `previous` hỏng = máy mới)."""
    if not isinstance(value, Slot):
        return None
    try:
        ring = Ring(value.ring)
    except (ValueError, TypeError):
        return None
    angle = value.angle
    if isinstance(angle, bool) or not isinstance(angle, int) or not 0 <= angle < ANGLES:
        return None
    return Slot(ring, angle)


def _slot_rect(center: QPointF, rx: float, ry: float, size: QSizeF, slot: Slot) -> QRectF:
    """Hình chữ nhật cỡ `size` quanh tâm của `slot`, góc trên trái làm tròn về số nguyên."""
    fraction = RING_FRACTIONS[slot.ring]
    theta = math.radians(-90.0 + slot.angle * 360.0 / ANGLES)
    x = center.x() + fraction * rx * math.cos(theta)
    y = center.y() + fraction * ry * math.sin(theta)
    return QRectF(round(x - size.width() / 2), round(y - size.height() / 2), size.width(), size.height())


def _place_once(
    area: QRectF,
    core: QRectF,
    size: QSizeF,
    items: Sequence[tuple[str, bool]],
    previous: Mapping[str, Slot],
) -> dict[str, tuple[Slot, QRectF]] | None:
    center = area.center()
    rx = area.width() / 2 - size.width() / 2
    ry = area.height() / 2 - size.height() / 2
    gap = BUBBLE_GAP
    blocked = core.adjusted(-gap, -gap, gap, gap)
    placed: dict[str, tuple[Slot, QRectF]] = {}

    def fits(slot: Slot, rect: QRectF) -> bool:
        if not area.contains(rect) or rect.intersects(blocked):
            return False
        for other_slot, other in placed.values():
            if other_slot == slot or rect.intersects(other.adjusted(-gap, -gap, gap, gap)):
                return False
        return True

    # Bước 1: giữ chỗ cũ còn hợp lệ, theo thứ tự `items`.
    for device_id, _paired in items:
        slot = _clean_slot(previous.get(device_id))
        if slot is None or device_id in placed:
            continue
        rect = _slot_rect(center, rx, ry, size, slot)
        if fits(slot, rect):
            placed[device_id] = (slot, rect)
    # Bước 2: các máy còn lại, ứng viên hợp lệ đầu tiên.
    for device_id, paired in items:
        if device_id in placed:
            continue
        found = False
        for ring in _ring_order(paired):
            for angle in ANGLE_ORDER:
                slot = Slot(ring, angle)
                rect = _slot_rect(center, rx, ry, size, slot)
                if fits(slot, rect):
                    placed[device_id] = (slot, rect)
                    found = True
                    break
            if found:
                break
        if not found:
            return None
    return {device_id: placed[device_id] for device_id, _ in items if device_id in placed}


def place_bubbles(
    area: QRectF,
    core: QRectF,
    size: QSizeF,
    items: Sequence[tuple[str, bool]],
    previous: Mapping[str, Slot],
) -> dict[str, tuple[Slot, QRectF]] | None:
    """Đặt mỗi `(device_id, paired)` của `items` vào một chỗ không chồng nhau (xem docstring module).

    `items` theo thứ tự `discover_devices`; `previous` là chỗ cũ theo `device_id`. Trả
    `{device_id: (Slot, QRectF)}` theo thứ tự `items`; không item → `{}`; thiếu chỗ → None.
    """
    if not items:
        return {}
    if area.width() / 2 - size.width() / 2 <= 0 or area.height() / 2 - size.height() / 2 <= 0:
        return None
    result = _place_once(area, core, size, items, previous)
    if result is None and previous:
        result = _place_once(area, core, size, items, {})
    return result


def _name_font(base: QFont) -> QFont:
    """Font tên trên bong bóng: font điểm nhấn (bậc SECTION) ở cỡ BODY."""
    font = theme.font_for(theme.TextStyle.SECTION, base)
    body = theme.font_for(theme.TextStyle.BODY, base)
    if body.pointSizeF() > 0:
        font.setPointSizeF(body.pointSizeF())
    elif body.pixelSize() > 0:
        font.setPixelSize(body.pixelSize())
    return font


def bubble_size(base: QFont) -> QSize:
    """Cỡ chung của mọi bong bóng với font gốc `base` (không phụ thuộc tên máy)."""
    name = QFontMetrics(_name_font(base)).lineSpacing()
    caption = QFontMetrics(theme.font_for(theme.TextStyle.CAPTION, base)).lineSpacing()
    height = BUBBLE_PADDING + BUBBLE_AVATAR + _AVATAR_TEXT_GAP + name + caption + BUBBLE_PADDING
    return QSize(BUBBLE_WIDTH, height)


# ---- Bong bóng ---------------------------------------------------------------------------------


class RadarBubble(QAbstractButton):
    """Một máy trên radar; bấm (chuột, Enter, Space) phát `clicked` (xem docstring module)."""

    def __init__(self, view: DeviceView, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("radarBubble")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAcceptDrops(False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover)  # vẽ lại khi chuột vào/ra (nền `selected`)
        self._view = view
        self.setFixedSize(bubble_size(self.font()))
        self.set_view(view)

    @property
    def device_id(self) -> str:
        return self._view.device_id

    @property
    def view(self) -> DeviceView:
        return self._view

    def set_view(self, view: DeviceView) -> None:
        """Cập nhật theo view mới nhất: chữ, tooltip, tên trợ năng, property `paired`, vẽ lại."""
        self._view = view
        self.setProperty("paired", bool(view.paired))
        name = self._name()
        self.setAccessibleName(_bubble_accessible_name(name, view.paired))
        os_label = texts.os_label(view.os)
        hint = _bubble_hint(view.paired)
        self.setAccessibleDescription(f"{os_label}. {hint}" if os_label else hint)
        lines = [name, _status_text(view)]
        if os_label:
            lines.append(os_label)
        self.setToolTip(safe_tooltip("\n".join(lines)))
        self.update()

    def _name(self) -> str:
        return texts.peer_label(self._view.name, self._view.device_id)

    def _canvas(self) -> RadarCanvas | None:
        parent = self.parentWidget()
        return parent if isinstance(parent, RadarCanvas) else None

    # -- Vẽ ----------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_for(self)
        dark = theme.is_dark_palette(QApplication.palette())
        paired = self._view.paired
        background: QColor | None = t.surface_raised
        if self.underMouse():
            background = t.selected
        elif paired:
            background = None
        if self.isDown():
            pen = QPen(t.accent_strong, 2)
        elif self.hasFocus():
            pen = QPen(theme.focus_ring_color(dark), 2)
        else:
            pen = QPen(t.border if paired else t.border_strong, 1)
        width = self.width()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            inset = pen.widthF() / 2
            painter.setPen(pen)
            painter.setBrush(background if background is not None else Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(
                QRectF(self.rect()).adjusted(inset, inset, -inset, -inset),
                theme.RADIUS_BLOCK,
                theme.RADIUS_BLOCK,
            )

            avatar = QRectF((width - BUBBLE_AVATAR) / 2, BUBBLE_PADDING, BUBBLE_AVATAR, BUBBLE_AVATAR)
            painter.save()
            if paired:
                painter.setOpacity(_PAIRED_AVATAR_OPACITY)  # chỉ avatar mờ, chữ không bao giờ mờ
            paint_avatar(
                painter,
                avatar,
                kind=AvatarKind.DESKTOP,
                presence=Presence.NONE,
                emphasis=False,
                ring=t.surface_raised,
                tokens=t,
                dpr=self.devicePixelRatioF(),
            )
            painter.restore()

            text_width = width - 2 * _BUBBLE_TEXT_MARGIN
            y = float(BUBBLE_PADDING + BUBBLE_AVATAR + _AVATAR_TEXT_GAP)
            name_font = _name_font(self.font())
            name_metrics = QFontMetrics(name_font)
            painter.setFont(name_font)
            painter.setPen(t.text_muted if paired else t.text)
            painter.drawText(
                QRectF(_BUBBLE_TEXT_MARGIN, y, text_width, name_metrics.lineSpacing()),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                name_metrics.elidedText(self._name(), Qt.TextElideMode.ElideRight, text_width),
            )
            y += name_metrics.lineSpacing()
            caption_font = theme.font_for(theme.TextStyle.CAPTION, self.font())
            caption_metrics = QFontMetrics(caption_font)
            painter.setFont(caption_font)
            painter.setPen(t.text_muted if paired else t.accent_text)
            painter.drawText(
                QRectF(_BUBBLE_TEXT_MARGIN, y, text_width, caption_metrics.lineSpacing()),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter),
                caption_metrics.elidedText(_paired_caption(paired), Qt.TextElideMode.ElideRight, text_width),
            )
        finally:
            painter.end()

    # -- Sự kiện -----------------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        canvas = self._canvas()
        if canvas is not None and event.modifiers() in _PLAIN_MODIFIERS:
            step = {
                Qt.Key.Key_Left: -1,
                Qt.Key.Key_Up: -1,
                Qt.Key.Key_Right: 1,
                Qt.Key.Key_Down: 1,
            }.get(Qt.Key(key))
            if step is not None:
                canvas.focus_step(self, step)
                event.accept()
                return
            if key in (Qt.Key.Key_Home, Qt.Key.Key_End):
                canvas.focus_edge(last=key == Qt.Key.Key_End)
                event.accept()
                return
        if key in _ENTER_KEYS:
            if not event.isAutoRepeat():  # giữ phím: mỗi lần nhấn thật chỉ một lần
                self.click()
            event.accept()
            return
        super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # Bấm đúp = một lần bấm: không coi dblclick là một lần nhấn nữa (`_activate` chặn phần còn lại).
        event.accept()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()
        elif event.type() == QEvent.Type.LanguageChange:
            self.set_view(self._view)
        elif event.type() == QEvent.Type.FontChange:
            self.setFixedSize(bubble_size(self.font()))
            self.update()


# ---- Canvas ------------------------------------------------------------------------------------


class RadarCanvas(QWidget):
    """Tâm “Bạn”, hai elip tĩnh, vòng sóng và các `RadarBubble` con (đặt bằng `setGeometry`)."""

    bubble_activated = Signal(str)  # device_id của bong bóng được bấm

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("radarCanvas")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.center_avatar = DeviceAvatar(self, diameter=_CORE_AVATAR, emphasis=True, ring="surface")
        self.center_label = QLabel(self)
        self.center_label.setObjectName("radarCenterLabel")
        self.center_label.setTextFormat(Qt.TextFormat.PlainText)
        self.center_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.center_label.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.center_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.center_label.font()))
        self.fallback_focus: QWidget | None = None  # tiêu điểm khi bỏ bong bóng cuối cùng
        self._bubbles: list[RadarBubble] = []
        self._slots: dict[str, Slot] = {}  # chỗ cũ, giữ cả khi đang ở dạng danh sách
        self._slot_paired: dict[str, bool] = {}  # trạng thái ghép đôi lúc nhận chỗ đó
        self._count = 0
        self._wave = QVariantAnimation(self)
        self._wave.setStartValue(0.0)
        self._wave.setEndValue(1.0)
        self._wave.valueChanged.connect(self._on_wave_step)
        self._wave.finished.connect(self.update)
        self._wave_cycles = WAVE_TOTAL_MS / WAVE_CYCLE_MS
        self.retranslate()

    # -- API ---------------------------------------------------------------------------------

    def bubbles(self) -> list[RadarBubble]:
        """Các bong bóng theo thứ tự Tab (thứ tự `discover_devices`)."""
        return list(self._bubbles)

    def bubble(self, device_id: str) -> RadarBubble | None:
        return next((b for b in self._bubbles if b.device_id == device_id), None)

    def bubble_size(self) -> QSize:
        return bubble_size(self.font())

    def core_rect(self) -> QRectF:
        """Hình bao avatar “Bạn” và nhãn, giữa canvas."""
        return self._core_rect_for(self.size())

    def layout_for(
        self, items: Sequence[tuple[str, bool]], size: QSize
    ) -> dict[str, tuple[Slot, QRectF]] | None:
        """`place_bubbles` cho canvas cỡ `size`, dùng chỗ cũ của máy chưa đổi trạng thái ghép đôi."""
        paired_now = dict(items)
        previous = {
            device_id: slot
            for device_id, slot in self._slots.items()
            if device_id in paired_now and self._slot_paired.get(device_id) == paired_now[device_id]
        }
        area = QRectF(0, 0, size.width(), size.height())
        return place_bubbles(area, self._core_rect_for(size), QSizeF(self.bubble_size()), items, previous)

    def apply(self, views: Sequence[DeviceView], placement: Mapping[str, tuple[Slot, QRectF]]) -> None:
        """Dựng/cập nhật/bỏ bong bóng cho `views` (theo thứ tự) và đặt chỗ theo `placement`.

        Bong bóng dùng lại theo `device_id`; bong bóng bị bỏ mà đang có tiêu điểm thì tiêu điểm sang
        bong bóng kế, không có thì trước, không còn thì `fallback_focus`.
        """
        old = list(self._bubbles)
        by_id = {b.device_id: b for b in old}
        wanted = {v.device_id for v in views}
        new: list[RadarBubble] = []
        for view in views:
            bubble = by_id.get(view.device_id)
            if bubble is None:
                bubble = RadarBubble(view, self)
                bubble.clicked.connect(lambda _=False, i=view.device_id: self.bubble_activated.emit(i))
            else:
                bubble.set_view(view)
            new.append(bubble)
        self._bubbles = new
        removed = [b for b in old if b.device_id not in wanted]
        self._move_focus_off(old, removed)
        for bubble in removed:
            self._drop(bubble)
        for bubble in new:
            entry = placement.get(bubble.device_id)
            if entry is not None:
                slot, rect = entry
                bubble.setGeometry(rect.toRect())
                self._slots[bubble.device_id] = slot
                self._slot_paired[bubble.device_id] = bubble.view.paired
            bubble.show()
        for device_id in [i for i in self._slots if i not in wanted]:
            self._slots.pop(device_id, None)
            self._slot_paired.pop(device_id, None)

    def clear_bubbles(self) -> None:
        """Bỏ mọi bong bóng (dạng danh sách); giữ chỗ cũ để quay lại radar (bên gọi lo tiêu điểm)."""
        old, self._bubbles = self._bubbles, []
        for bubble in old:
            self._drop(bubble)

    def focused_device_id(self) -> str | None:
        """device_id của bong bóng đang là widget tiêu điểm của cửa sổ, nếu có."""
        focus = self.window().focusWidget()
        for bubble in self._bubbles:
            if bubble is focus:
                return bubble.device_id
        return None

    def focus_step(self, bubble: RadarBubble, step: int) -> None:
        """Sang bong bóng trước (`step` < 0) hay sau, không vòng."""
        if bubble not in self._bubbles:
            return
        target = self._bubbles.index(bubble) + step
        if 0 <= target < len(self._bubbles):
            self._bubbles[target].setFocus(Qt.FocusReason.OtherFocusReason)

    def focus_edge(self, *, last: bool) -> None:
        if self._bubbles:
            self._bubbles[-1 if last else 0].setFocus(Qt.FocusReason.OtherFocusReason)

    def set_count(self, count: int) -> None:
        """Số máy cho câu mô tả trợ năng."""
        self._count = count
        self.retranslate()

    @property
    def wave_running(self) -> bool:
        return self._wave.state() == QAbstractAnimation.State.Running

    def start_waves(self) -> None:
        """Chạy vòng sóng một lần (≤ `WAVE_TOTAL_MS`); đang chạy thì thôi; hiệu ứng HĐH tắt thì không chạy."""
        if not motion.animations_enabled():
            self.stop_waves()
            return
        if self.wave_running:
            return
        cycle = max(1, int(WAVE_CYCLE_MS))
        total = max(1, int(WAVE_TOTAL_MS))
        self._wave_cycles = total / cycle
        self._wave.setDuration(total)
        self._wave.start()

    def stop_waves(self) -> None:
        if self._wave.state() != QAbstractAnimation.State.Stopped:
            self._wave.stop()
            self.update()

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        self.center_label.setText(t("Discover", "Bạn"))
        self.setAccessibleName(t("Discover", "Máy trong mạng"))
        self.setAccessibleDescription(
            t("Discover", "%n máy. Tab hoặc phím mũi tên để chọn, Enter để ghép đôi.", None, self._count)
        )
        self._place_core()

    # -- Nội bộ ------------------------------------------------------------------------------

    def _core_parts(self) -> tuple[QSize, QSize]:
        label = self.center_label.sizeHint()
        return QSize(_CORE_AVATAR, _CORE_AVATAR), label

    def _core_rect_for(self, size: QSize) -> QRectF:
        avatar, label = self._core_parts()
        width = max(avatar.width(), label.width())
        height = avatar.height() + _CORE_GAP + label.height()
        return QRectF(round((size.width() - width) / 2), round((size.height() - height) / 2), width, height)

    def _place_core(self) -> None:
        core = self.core_rect()
        avatar, label = self._core_parts()
        left = round(core.center().x() - avatar.width() / 2)
        self.center_avatar.move(left, round(core.top()))
        self.center_label.setGeometry(
            round(core.left()),
            round(core.top()) + avatar.height() + _CORE_GAP,
            round(core.width()),
            label.height(),
        )

    def _radii(self) -> tuple[float, float]:
        size = self.bubble_size()
        return self.width() / 2 - size.width() / 2, self.height() / 2 - size.height() / 2

    def _move_focus_off(self, old: list[RadarBubble], removed: list[RadarBubble]) -> None:
        focus = self.window().focusWidget()
        if not any(b is focus for b in removed):
            return
        index = next(i for i, b in enumerate(old) if b is focus)
        survivors = set(map(id, self._bubbles))
        after = [b for b in old[index + 1 :] if id(b) in survivors]
        before = [b for b in old[:index] if id(b) in survivors]
        target: QWidget | None = after[0] if after else (before[-1] if before else self.fallback_focus)
        if target is not None:
            target.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def _drop(bubble: RadarBubble) -> None:
        bubble.hide()
        bubble.setParent(None)  # ra khỏi `findChildren` ngay, không đợi `deleteLater`
        bubble.deleteLater()

    def _on_wave_step(self, _value: Any) -> None:
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        t = theme.tokens_for(self)
        rx, ry = self._radii()
        if rx <= 0 or ry <= 0:
            return
        center = QRectF(self.rect()).center()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(t.border, 1))
            for ring in (Ring.INNER, Ring.OUTER):
                fraction = RING_FRACTIONS[ring]
                painter.drawEllipse(center, fraction * rx, fraction * ry)
            if self.wave_running:
                value = self._wave.currentValue()
                elapsed = (float(value) if isinstance(value, (int, float)) else 0.0) * self._wave_cycles
                # Sóng cùng dạng với các vòng: bắt đầu từ elip nhỏ nhất bao trọn tâm, nở ra vòng ngoài.
                core = self.core_rect()
                start = min(1.0, max(core.width() / 2 / rx, core.height() / 2 / ry))
                for wave in range(_WAVE_COUNT):
                    local = elapsed - wave / _WAVE_COUNT
                    if local < 0:
                        continue
                    phase = local % 1.0
                    scale = start + (1.0 - start) * phase
                    color = QColor(t.accent_strong)
                    color.setAlphaF(_WAVE_ALPHA * (1.0 - phase))
                    painter.setPen(QPen(color, 2))
                    painter.drawEllipse(center, scale * rx, scale * ry)
        finally:
            painter.end()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._place_core()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()
        elif event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        elif event.type() == QEvent.Type.FontChange:
            self.center_label.setFont(theme.font_for(theme.TextStyle.SECTION, self.font()))
            self._place_core()
            self.update()


# ---- Dạng danh sách ----------------------------------------------------------------------------


class DiscoverProxyModel(QSortFilterProxyModel):
    """Lọc và sắp `DeviceListModel` như `discover_devices` (đọc `DEVICE_ROLE`); chữ giữ nguyên."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, source_row: int, source_parent: _Index) -> bool:
        model = self.sourceModel()
        if model is None:
            return False
        view = model.index(source_row, 0, source_parent).data(DEVICE_ROLE)
        return isinstance(view, DeviceView) and _shown(view)

    def lessThan(self, source_left: _Index, source_right: _Index) -> bool:
        left, right = source_left.data(DEVICE_ROLE), source_right.data(DEVICE_ROLE)
        if not isinstance(left, DeviceView) or not isinstance(right, DeviceView):
            return False
        return _discover_key(left) < _discover_key(right)


class _DiscoverList(QListView):
    """Danh sách máy; Enter/Return (không tính tự lặp) trên hàng hiện hành phát `row_entered`."""

    row_entered = Signal(QModelIndex)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in _ENTER_KEYS and self.currentIndex().isValid():
            if not event.isAutoRepeat():
                self.row_entered.emit(self.currentIndex())
            event.accept()
            return
        super().keyPressEvent(event)


# ---- Ô nhập IP ---------------------------------------------------------------------------------


class _AddressField(QLineEdit):
    """Ô “Nhập IP…”: Esc xóa chữ khi ô có chữ; ô rỗng thì để Esc cho cửa sổ (quay lại)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMaxLength(_ADDRESS_MAX_LENGTH)
        self.setInputMethodHints(Qt.InputMethodHint.ImhPreferNumbers)

    @staticmethod
    def _is_plain_escape(event: QEvent) -> bool:
        return (
            isinstance(event, QKeyEvent)
            and event.key() == Qt.Key.Key_Escape
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        )

    def event(self, event: QEvent) -> bool:
        # Có chữ: nhận ShortcutOverride để `_back_action` (Esc, WindowShortcut) không chạy, Esc tới
        # `keyPressEvent`. Ô rỗng: không nhận, Esc là “Quay lại”.
        if event.type() == QEvent.Type.ShortcutOverride and self._is_plain_escape(event) and self.text():
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if self._is_plain_escape(event) and self.text():
            self.clear()  # `textChanged` ẩn lỗi địa chỉ đang hiện
            event.accept()
            return
        super().keyPressEvent(event)


# ---- Trang -------------------------------------------------------------------------------------


class ViewMode(StrEnum):
    RADAR = "radar"
    LIST = "list"


class ListReason(StrEnum):
    NONE = ""
    PREFERENCE = "preference"
    TOO_MANY = "too_many"
    NO_ROOM = "no_room"


def _plain_label(object_name: str, parent: QWidget) -> QLabel:
    label = QLabel(parent)
    label.setObjectName(object_name)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setWordWrap(True)
    return label


class DiscoverPage(QWidget):
    """Trang “Tìm máy mới” trên `model` dùng chung với radar (xem docstring module)."""

    pair_requested = Signal(object)  # DeviceView mới nhất: chưa ghép đôi và đang trong mạng
    manual_address_entered = Signal(str, int)  # ip, cổng (qua `app.devices.parse_manual_address`)
    open_device_requested = Signal(str)  # device_id của máy đã ghép đôi được bấm
    view_preference_changed = Signal(str)  # "radar" | "list", chỉ khi người dùng bấm `view_button`
    wait_pairing_requested = Signal()  # nút “Chờ ghép đôi” (`ui.wait_pairing` nối)

    def __init__(self, model: DeviceListModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("discoverPage")
        self.model = model
        self._preference: str | None = None
        self._mode = ViewMode.RADAR
        self._reason = ListReason.NONE
        self._count = 0
        self._sized = False  # khung đã có lần đổi cỡ thật đầu tiên
        self._syncing = False
        self._last: tuple[str, float] | None = None  # (device_id, _now()) của lần kích hoạt gần nhất
        self._address_error: str | None = None  # chữ đã nhập khi thanh thông báo đang hiện lỗi địa chỉ
        self._watched_window: QWidget | None = None

        self.header = PageHeader(page_title(), self)
        self.address_edit = _AddressField(self.header)
        self.address_edit.setObjectName("discoverAddress")
        self.address_edit.setFixedWidth(_ADDRESS_WIDTH)
        self.address_submit = QPushButton(self.header)
        self.address_submit.setObjectName("discoverAddressSubmit")
        self.address_submit.setProperty(theme.PRIMARY_PROPERTY, True)
        self.address_submit.setEnabled(False)
        self.header.add_trailing(self.address_edit)
        self.header.add_trailing(self.address_submit)

        self.info_bar = InfoBar(self)
        self.info_bar.setObjectName("discoverInfo")
        self.hint_label = _plain_label("discoverHint", self)
        self.hint_label.setProperty(theme.TONE_PROPERTY, "muted")
        # Cờ trước, chính sách tiêu điểm sau: `setTextInteractionFlags` tự đặt lại chính sách tiêu điểm.
        self.hint_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.hint_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.mode_reason_label = _plain_label("discoverModeReason", self)
        self.mode_reason_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.mode_reason_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.mode_reason_label.setVisible(False)
        self.view_button = QPushButton(self)
        self.view_button.setObjectName("discoverViewButton")
        self.wait_button = QPushButton(self)
        self.wait_button.setObjectName("waitPairingButton")
        self.wait_button.setVisible(False)

        self.stack = QStackedWidget(self)
        self.stack.setObjectName("discoverStack")
        self.canvas = RadarCanvas(self.stack)
        self.canvas.fallback_focus = self.address_edit
        self.proxy = DiscoverProxyModel(self)
        self.proxy.setSourceModel(model)
        self.proxy.sort(0, Qt.SortOrder.AscendingOrder)
        self.list_view = _DiscoverList(self.stack)
        self.list_view.setObjectName("discoverList")
        self.list_view.setModel(self.proxy)
        self.list_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_view.setDragEnabled(False)
        self.list_view.setAcceptDrops(False)
        self.list_view.setWordWrap(True)
        self.list_view.setUniformItemSizes(False)
        self.list_view.setSpacing(theme.SPACING[0])
        self.list_view.setIconSize(QSize(32, 32))
        self.stack.addWidget(self.canvas)
        self.stack.addWidget(self.list_view)
        self.stack.installEventFilter(self)

        self.empty_label = _plain_label("discoverEmpty", self)
        self.empty_label.setProperty(theme.TONE_PROPERTY, "muted")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        # Cờ trước, chính sách tiêu điểm sau: `setTextInteractionFlags` tự đặt lại chính sách tiêu điểm.
        self.empty_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.empty_label.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.empty_label.setVisible(False)

        margin = theme.SPACING[3]
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.header)
        body = QVBoxLayout()
        body.setContentsMargins(margin, theme.SPACING[2], margin, margin)
        body.setSpacing(theme.SPACING[2])
        body.addWidget(self.info_bar)
        row = QHBoxLayout()
        row.setSpacing(theme.SPACING[2])
        row.addWidget(self.hint_label, 1)
        row.addWidget(self.mode_reason_label, 1)
        row.addWidget(self.view_button, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.wait_button, 0, Qt.AlignmentFlag.AlignVCenter)
        body.addLayout(row)
        body.addWidget(self.stack, 1)
        body.addWidget(self.empty_label)
        outer.addLayout(body, 1)

        self.address_edit.textChanged.connect(self._on_address_changed)
        self.address_edit.returnPressed.connect(self.submit_address)
        self.address_submit.clicked.connect(self.submit_address)
        self.view_button.clicked.connect(self._on_view_button)
        self.wait_button.clicked.connect(self.wait_pairing_requested)
        self.canvas.bubble_activated.connect(self._activate)
        self.list_view.clicked.connect(self._on_list_index)
        self.list_view.row_entered.connect(self._on_list_index)
        for signal in (
            model.modelReset,
            model.rowsInserted,
            model.rowsRemoved,
            model.rowsMoved,
            model.dataChanged,
            model.layoutChanged,
        ):
            signal.connect(self._sync)

        self.retranslate()
        self._sync()

    # ---- API -----------------------------------------------------------------------------------

    @property
    def view_mode(self) -> ViewMode:
        return self._mode

    @property
    def list_reason(self) -> ListReason:
        return self._reason

    @property
    def view_preference(self) -> str | None:
        """Lựa chọn của người dùng: `"radar"`, `"list"` hay None (chưa chọn: radar)."""
        return self._preference

    def set_view_preference(self, value: str | None) -> None:
        """Đặt lựa chọn (đọc từ `settings.json`); không phát signal; giá trị lạ bị bỏ qua."""
        if value is not None and value not in (ViewMode.RADAR.value, ViewMode.LIST.value):
            return
        self._preference = value
        self._sync()

    def set_wait_pairing_available(self, available: bool) -> None:
        """Hiện/ẩn nút “Chờ ghép đôi” (`ui.wait_pairing` bật khi đăng ký trang)."""
        self.wait_button.setVisible(bool(available))
        self._update_tab_order()

    def show_notice(self, text: texts.Text) -> None:
        """Thông báo thành công (ví dụ “Đã ghép đôi với …”); gõ chữ vào ô nhập không ẩn nó."""
        self.show_info(text, InfoLevel.SUCCESS)

    def show_info(self, text: texts.Text, level: InfoLevel = InfoLevel.INFO) -> None:
        """Hiện `text` ở thanh thông báo của trang (thay lỗi địa chỉ nếu đang có: gõ chữ không ẩn nó).

        `text` là hàm thì câu được dịch lại khi đổi ngôn ngữ; chuỗi thì bị ẩn (`widgets.InfoBar`)."""
        self._address_error = None
        self.info_bar.show_message(level, text)

    def submit_address(self) -> bool:
        """Đọc ô nhập; đúng → phát `manual_address_entered`, xóa ô, True; sai → thanh lỗi, False."""
        text = self.address_edit.text()
        if not text.strip():
            return False
        try:
            ip, port = parse_manual_address(text)
        except ValueError:
            self._address_error = text
            # Hàm: `InfoBar` tự dịch lại câu lỗi khi đổi ngôn ngữ.
            self.info_bar.show_message(InfoLevel.ERROR, functools.partial(invalid_address_text, text))
            self.address_edit.setFocus(Qt.FocusReason.OtherFocusReason)
            self.address_edit.selectAll()
            return False
        self.address_edit.clear()
        self._hide_address_error()
        self.manual_address_entered.emit(ip, port)
        return True

    def retranslate(self) -> None:
        t = QCoreApplication.translate
        title = page_title()
        self.header.set_title(title)
        self.setAccessibleName(title)
        self.address_edit.setPlaceholderText(t("Discover", "Nhập IP…"))
        self.address_edit.setAccessibleName(t("Discover", "Địa chỉ IP của máy kia"))
        help_text = t(
            "Discover",
            "Dùng khi máy kia không hiện ở đây. Ví dụ 192.168.1.5 hoặc 192.168.1.5:47474.",
        )
        self.address_edit.setAccessibleDescription(help_text)
        self.address_edit.setToolTip(safe_tooltip(help_text))
        self.address_submit.setText(t("Discover", "Ghép đôi"))
        self.address_submit.setAccessibleName(t("Discover", "Ghép đôi theo địa chỉ IP"))
        hint = t("Discover", "Bấm vào một máy để ghép đôi. Máy đã ghép đôi hiện mờ.")
        self.hint_label.setText(hint)
        self.hint_label.setAccessibleName(hint)
        wait = t("Discover", "Chờ ghép đôi")
        self.wait_button.setText(wait)
        self.wait_button.setAccessibleName(wait)
        self.list_view.setAccessibleName(t("Discover", "Máy trong mạng"))
        self.list_view.setAccessibleDescription(
            t("Discover", "Phím mũi tên để chọn, Enter để ghép đôi hoặc mở máy đã ghép đôi.")
        )
        empty = no_devices_text()
        self.empty_label.setText(empty)
        self.empty_label.setAccessibleName(empty)
        self._update_mode_widgets()

    # ---- Đồng bộ với model ---------------------------------------------------------------------

    def _sync(self) -> None:
        """Dựng lại dạng hiển thị, bong bóng, Tab, tiêu điểm từ model (xem docstring module)."""
        if self._syncing:
            return
        self._syncing = True
        try:
            self._sync_now()
        finally:
            self._syncing = False

    def _sync_now(self) -> None:
        views = discover_devices(self.model.devices())
        count = len(views)
        was_empty = self._count == 0
        old_mode = self._mode
        self._count = count
        items = [(v.device_id, v.paired) for v in views]
        size = self.stack.contentsRect().size()

        placement: Mapping[str, tuple[Slot, QRectF]] | None = None
        if count > RADAR_MAX:
            mode, reason = ViewMode.LIST, ListReason.TOO_MANY
        else:
            placement = self.canvas.layout_for(items, size)
            if placement is None and self._sized:
                mode, reason = ViewMode.LIST, ListReason.NO_ROOM
            elif self._preference == ViewMode.LIST.value:
                mode, reason = ViewMode.LIST, ListReason.PREFERENCE
            else:
                mode, reason = ViewMode.RADAR, ListReason.NONE
        self._mode, self._reason = mode, reason

        if mode is ViewMode.RADAR:
            self.stack.setCurrentWidget(self.canvas)
            self.canvas.setGeometry(self.stack.contentsRect())
            self.canvas.apply(views, placement or {})
        else:
            focused = self.canvas.focused_device_id()
            self.stack.setCurrentWidget(self.list_view)
            if focused is not None:
                self._focus_list_row(focused)
            self.canvas.clear_bubbles()
            self._ensure_list_current()
        self.canvas.set_count(count)
        self.empty_label.setVisible(count == 0)
        self._update_mode_widgets()
        self._update_tab_order()
        self._update_focus_proxy()

        if mode is ViewMode.LIST:
            self.canvas.stop_waves()
        elif old_mode is not ViewMode.RADAR or was_empty != (count == 0):
            self._restart_waves()

    def _update_mode_widgets(self) -> None:
        t = QCoreApplication.translate
        forced = self._reason in (ListReason.TOO_MANY, ListReason.NO_ROOM)
        if self._mode is ViewMode.RADAR:
            label = t("Discover", "Dạng danh sách")
        else:
            label = t("Discover", "Dạng vòng tròn")
        self.view_button.setText(label)
        self.view_button.setAccessibleName(label)
        self.view_button.setVisible(not forced)
        reason = _mode_reason_text(self._reason, self._count)
        # Câu lý do thay chỗ nút trên cùng hàng: không thấp hơn nút, để khung radar ở dạng vòng tròn
        # không bao giờ nhỏ hơn lúc đang ở dạng danh sách (macOS/Linux: nút cao hơn nhãn). Không thì
        # bố cục vừa đặt lúc về dạng vòng tròn tràn khỏi khung cho tới lần đổi cỡ kế tiếp.
        self.mode_reason_label.setMinimumHeight(self.view_button.sizeHint().height())
        self.mode_reason_label.setText(reason)
        self.mode_reason_label.setAccessibleName(reason)
        self.mode_reason_label.setVisible(forced)

    def _update_tab_order(self) -> None:
        bar = self.info_bar
        chain: list[QWidget] = [
            self.header.back_button,
            self.address_edit,
            self.address_submit,
            bar.title_label,
            bar.text_label,
            bar.action_button,
            bar.close_button,
            self.hint_label,
            self.view_button,
            self.wait_button,
            *self.canvas.bubbles(),
            self.list_view,
            self.empty_label,
        ]
        for first, second in itertools.pairwise(chain):
            QWidget.setTabOrder(first, second)

    def _update_focus_proxy(self) -> None:
        target: QWidget = self.address_edit
        if self._mode is ViewMode.RADAR:
            unpaired = next((b for b in self.canvas.bubbles() if not b.view.paired), None)
            if unpaired is not None:
                target = unpaired
        elif self.proxy.rowCount() > 0:
            target = self.list_view
        self.setFocusProxy(target)

    def _ensure_list_current(self) -> None:
        selection = self.list_view.selectionModel()
        if selection is None or self.proxy.rowCount() == 0 or self.list_view.currentIndex().isValid():
            return
        selection.setCurrentIndex(self.proxy.index(0, 0), QItemSelectionModel.SelectionFlag.NoUpdate)

    def _focus_list_row(self, device_id: str) -> None:
        """Tiêu điểm vào danh sách, hàng hiện hành là máy `device_id` (nếu có)."""
        selection = self.list_view.selectionModel()
        for row in range(self.proxy.rowCount()):
            index = self.proxy.index(row, 0)
            if index.data(DEVICE_ID_ROLE) == device_id and selection is not None:
                selection.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
                break
        self.list_view.setFocus(Qt.FocusReason.OtherFocusReason)

    # ---- Kích hoạt -----------------------------------------------------------------------------

    def _activate(self, device_id: str) -> None:
        """Mọi đường bấm vào một máy (xem docstring module, “Kích hoạt một máy”)."""
        view = self.model.device(device_id)
        if view is None:
            return
        last = self._last
        if last is not None and last[0] == device_id:
            elapsed = _now() - last[1]
            if 0 <= elapsed < QApplication.doubleClickInterval() / 1000:
                return
        if not view.paired and view.online:
            self.pair_requested.emit(view)
        elif view.paired:
            self.open_device_requested.emit(device_id)
        else:
            return
        self._last = (device_id, _now())

    def _on_list_index(self, index: QModelIndex) -> None:
        device_id = index.data(DEVICE_ID_ROLE) if index.isValid() else None
        if isinstance(device_id, str):
            self._activate(device_id)

    def _on_view_button(self) -> None:
        if self._mode is ViewMode.RADAR:
            value = ViewMode.LIST.value
        elif self._reason is ListReason.PREFERENCE:
            value = ViewMode.RADAR.value
        else:
            return
        self._preference = value
        self._sync()
        self.view_preference_changed.emit(value)

    # ---- Ô nhập --------------------------------------------------------------------------------

    def _on_address_changed(self, text: str) -> None:
        self.address_submit.setEnabled(bool(text.strip()))
        self._hide_address_error()

    def _hide_address_error(self) -> None:
        if self._address_error is None:
            return
        self._address_error = None
        if self.info_bar.level is InfoLevel.ERROR:
            self.info_bar.clear()

    # ---- Vòng sóng, hiện/ẩn --------------------------------------------------------------------

    def _window_minimized(self) -> bool:
        return self.window().isMinimized()

    def _restart_waves(self) -> None:
        if self._mode is ViewMode.RADAR and self.isVisible() and not self._window_minimized():
            self.canvas.start_waves()
        else:
            self.canvas.stop_waves()

    def _watch_window(self) -> None:
        window = self.window()
        if window is self or window is self._watched_window:
            return
        old = self._watched_window
        if old is not None and isValid(old):
            old.removeEventFilter(self)
        window.installEventFilter(self)
        self._watched_window = window

    def _on_window_state(self, event: QEvent) -> None:
        if self._window_minimized():
            self.canvas.stop_waves()
        elif (
            isinstance(event, QWindowStateChangeEvent)
            and event.oldState() & Qt.WindowState.WindowMinimized
            and self.isVisible()
        ):
            self._restart_waves()  # chỉ khi thôi thu nhỏ; phóng to/toàn màn hình không chạy lại sóng

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        # Lúc cửa sổ bị hủy, PySide có thể đã xóa thuộc tính Python của trang mà Qt vẫn gửi sự kiện
        # (đổi cỡ `stack`) tới bộ lọc (CI macOS): khi đó bỏ qua.
        if "stack" not in self.__dict__:
            return False
        if watched is self.stack and event.type() == QEvent.Type.Resize:
            self._sized = True
            self._sync()
        elif watched is self._watched_window and event.type() == QEvent.Type.WindowStateChange:
            self._on_window_state(event)
        return False

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not event.spontaneous():  # câu báo tới lúc trang đang ẩn (vd. ghép đôi từ HOME) là câu cũ
            self._address_error = None
            self.info_bar.clear()
        self._watch_window()
        self._restart_waves()

    def hideEvent(self, event: QHideEvent) -> None:
        super().hideEvent(event)
        self.canvas.stop_waves()
        if not event.spontaneous():  # đổi trang, xuống khay (thu nhỏ thì giữ)
            self._address_error = None
            self.info_bar.clear()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslate()
        elif event.type() == QEvent.Type.FontChange:
            # Cỡ bong bóng theo font: đặt lại sau khi font đã lan xuống mọi widget con.
            QTimer.singleShot(0, self, self._sync)
        elif event.type() == QEvent.Type.WindowStateChange and self.isWindow():
            self._on_window_state(event)
