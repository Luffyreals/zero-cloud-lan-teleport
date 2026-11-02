"""Minh họa của màn trống và màn lần chạy đầu (spec G6, mvp N3, N12): `Scene`, `paint_scene`, `Illustration`.

**Cảnh** (`Scene`) và nơi dùng: `NOT_PAIRED` (chưa ghép máy nào: khung phải cửa sổ chính, Cài đặt ›
Thiết bị), `NO_TRANSFERS` (luồng chat rỗng của một máy), `NO_DEVICES` (trang Tìm máy mới, dạng danh
sách, 0 máy), `WELCOME` (màn lần chạy đầu). `widgets.EmptyState` chọn cảnh theo icon qua
`scene_for_icon`; module này không import `widgets` (tránh vòng import), chỉ `theme` và `motion`.

**Vẽ** (`paint_scene`, hàm thuần): từng lớp bằng `QPainter` (không SVG, không ảnh, lệch plan có chủ ý:
không thêm QtSvg), khử răng cưa, chỉ màu của `tokens` nên tự theo sáng/tối và màu nhấn. Mỗi cảnh vẽ
trong khung gốc riêng (`_BASE`) rồi co giãn giữ tỉ lệ, căn giữa `rect`. Nền chung là một khối mềm
`accent_subtle`; thân máy `surface_raised` viền `text_muted`, màn `accent`; chi tiết mang nghĩa (nét
nối, sóng, mũi tên, viền file, dấu tích) là `accent_strong`. Chấm nét đứt `border_strong` (chỗ máy khác
sẽ hiện) nằm ngoài khối nền. Mọi cặp màu mang nghĩa và nền thật phía sau nằm trong `CONTRAST_PAIRS`
(≥ 3:1 với mọi màu nhấn × sáng/tối, WCAG 1.4.11; test kiểm).

**Chuyển động** (`progress` 0→1): các lớp hiện dần lệch pha (mờ 0→1 và dịch ≤ `motion.MAX_SHIFT_PX`,
đường cong OutCubic), rồi một chuyển động chính: `NOT_PAIRED` nét đứt vẽ dần từ trái sang phải rồi dấu
“+” hiện; `NO_DEVICES` ba cung sóng nở ra một lần rồi đứng mờ; `NO_TRANSFERS` tờ file hạ xuống khay
theo đường cong; `WELCOME` một file bay theo đường cong giữa hai máy, để lại vệt nét đứt, tới nơi hiện
dấu tích. Không phóng to/thu nhỏ, không nhấp nháy. `progress == 1` là **khung cuối**, không phụ thuộc
thời gian: dùng khi tắt hiệu ứng và sau khi chạy xong. `progress` được kẹp vào [0, 1] (không hữu hạn →
1).

**`Illustration`** (widget trang trí): cỡ cố định theo cảnh (`ILLUSTRATION_SIZE`, `WELCOME` rộng hơn:
`WELCOME_SIZE`), `Qt.NoFocus`, `WA_TransparentForMouseEvents`, không tên/mô tả trợ năng (chữ cạnh bên đã
nói đủ, như vòng tròn icon cũ của `EmptyState` và tâm “Bạn” của radar). Màu lấy `theme.tokens_for(self)`
lúc vẽ; `PaletteChange` / `ApplicationPaletteChange` → `update()`.
- Chạy một vòng `PLAY_MS` (đọc lúc chạy) qua một `motion.Loop` tạo mới mỗi lần chạy (`max_ms` = cùng
  thời lượng: lặp đúng một lần), rồi đứng ở khung cuối. Loop lo cổng `should_animate`, dừng khi widget
  hay cửa sổ ẩn/thu nhỏ, sổ đăng ký (`running_count`, `finish_all`); dừng theo đường nào cũng về
  khung cuối. Không timer nào khi rảnh (N3).
- Chạy khi: widget hiện lần đầu với cảnh hiện tại (`showEvent`), hay `set_scene` đổi sang cảnh chưa
  chạy khi đang hiện. Mỗi cảnh chạy **một lần** trong đời widget: đánh dấu “đã chạy” ở lần hiện đầu
  tiên kể cả khi lúc đó không được hoạt ảnh; bị ngắt giữa chừng thì đứng ở khung cuối, không chạy lại.
  `play()` gọi tay thì chạy lại. `set_scene` cùng cảnh không làm gì. `progress < 1` chỉ khi Loop đang
  chạy.
- Callback nối vào Loop chỉ giữ tham chiếu yếu tới widget (lý do: chú thích sổ đăng ký của `motion`).
"""

from __future__ import annotations

import math
import weakref
from collections.abc import Callable
from enum import StrEnum

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen, QShowEvent
from PySide6.QtWidgets import QWidget
from shiboken6 import isValid

from teleport.ui import motion, theme

ILLUSTRATION_SIZE = QSize(160, 96)  # px logic, cảnh trong `EmptyState` và Discover
# px logic, cảnh WELCOME: không hẹp hơn cảnh khác (khung gốc rộng, hai máy), thấp hơn để thẻ khởi
# động vẫn vừa cửa sổ mặc định không cuộn (`tests/ui/test_home_layout.py`); vẽ giữ tỉ lệ khung gốc
# nên chỉ co lại, không méo.
WELCOME_SIZE = QSize(168, 64)
PLAY_MS = 2400  # một lần chạy (≤ `motion.MAX_LOOP_MS`), đọc lúc chạy

# (chi tiết mang nghĩa, nền thật phía sau): tên token của `theme.Tokens`, ≥ 3:1 ở mọi màu nhấn ×
# sáng/tối. `surface` / `surface_raised`: nền màn (EmptyState, Discover, thẻ khởi động) và thân máy, tờ
# file, vòng “+”.
CONTRAST_PAIRS: tuple[tuple[str, str], ...] = (
    ("accent_strong", "accent_subtle"),  # nét nối, sóng, mũi tên, khay, viền file, dấu tích trên khối nền
    ("accent_strong", "surface_raised"),  # dấu “+” trong vòng; nét tích trên nền nhấn
    ("accent_strong", "surface"),  # phần chi tiết chạm mép khối nền
    ("text_muted", "accent_subtle"),  # viền thân máy trên khối nền
    ("border_strong", "surface"),  # chấm nét đứt quanh khối nền
    ("border_strong", "surface_raised"),  # dòng chữ trên tờ file; chấm nét đứt trên nền thẻ
)

_PALETTE_EVENTS = (QEvent.Type.PaletteChange, QEvent.Type.ApplicationPaletteChange)


class Scene(StrEnum):
    NOT_PAIRED = "not_paired"
    NO_DEVICES = "no_devices"
    NO_TRANSFERS = "no_transfers"
    WELCOME = "welcome"


_ICON_SCENES = {
    "arrow_swap": Scene.NOT_PAIRED,
    "shield_checkmark": Scene.NOT_PAIRED,
    "attach": Scene.NO_TRANSFERS,
}

# Khung gốc (rộng, cao) của từng cảnh; `paint_scene` co giãn giữ tỉ lệ vào `rect`.
_BASE: dict[Scene, tuple[float, float]] = {
    Scene.NOT_PAIRED: (160.0, 96.0),
    Scene.NO_DEVICES: (160.0, 96.0),
    Scene.NO_TRANSFERS: (160.0, 96.0),
    Scene.WELCOME: (224.0, 96.0),
}


def scene_for_icon(icon_name: str) -> Scene | None:
    """Cảnh minh họa của icon `EmptyState`: `arrow_swap` (khung phải cửa sổ chính, `streamEmpty`) và
    `shield_checkmark` (Cài đặt › Thiết bị, `trustedEmpty`) → `NOT_PAIRED`; `attach` (luồng chat rỗng,
    `chatEmpty`) → `NO_TRANSFERS`; còn lại None (giữ vòng tròn icon)."""
    return _ICON_SCENES.get(icon_name)


def size_for(scene: Scene) -> QSize:
    """Cỡ cố định của `Illustration` cho `scene`."""
    return QSize(WELCOME_SIZE) if scene is Scene.WELCOME else QSize(ILLUSTRATION_SIZE)


# ---- Thời gian ----------------------------------------------------------------------------------


def _clamp(value: float) -> float:
    return 0.0 if value <= 0.0 else 1.0 if value >= 1.0 else value


def _out_cubic(t: float) -> float:
    return 1.0 - (1.0 - t) ** 3


def _in_out_cubic(t: float) -> float:
    return 4.0 * t**3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0


def _phase(
    progress: float, start: float, length: float, ease: Callable[[float], float] = _out_cubic
) -> float:
    """Tiến độ đã làm mềm của một lớp chạy từ `start` trong `length` (cùng đơn vị với `progress`)."""
    return ease(_clamp((progress - start) / length))


# ---- Hình cơ bản --------------------------------------------------------------------------------


def _pen(color: QColor, width: float, *, dash: tuple[float, float] | None = None) -> QPen:
    pen = QPen(color, width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    if dash is not None:
        pen.setDashPattern([dash[0] / width, dash[1] / width])
    return pen


class _Layer:
    """Một lớp hiện dần: mờ theo `t` và dịch `(1 − t)·MAX_SHIFT_PX` theo hướng `(dx, dy)`."""

    def __init__(self, painter: QPainter, t: float, dx: float = 0.0, dy: float = 1.0) -> None:
        self._painter = painter
        self._t = t
        self._shift = (1.0 - t) * motion.MAX_SHIFT_PX
        self._dx, self._dy = dx, dy

    def __enter__(self) -> QPainter:
        painter = self._painter
        painter.save()
        painter.setOpacity(painter.opacity() * self._t)
        painter.translate(self._dx * self._shift, self._dy * self._shift)
        return painter

    def __exit__(self, *_exc: object) -> None:
        self._painter.restore()


def _blob(painter: QPainter, t: theme.Tokens, rect: QRectF, radius: float) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(t.accent_subtle)
    painter.drawRoundedRect(rect, radius, radius)


def _laptop(painter: QPainter, t: theme.Tokens, cx: float, top: float, width: float, height: float) -> None:
    """Laptop nhìn thẳng: nắp `surface_raised` viền `text_muted`, màn `accent`, đế rộng hơn nắp."""
    stroke = _pen(t.text_muted, 1.5)
    lid = QRectF(cx - width / 2, top, width, height)
    painter.setPen(stroke)
    painter.setBrush(t.surface_raised)
    painter.drawRoundedRect(lid, 4.0, 4.0)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(t.accent)
    painter.drawRoundedRect(lid.adjusted(3.5, 3.5, -3.5, -3.5), 2.0, 2.0)
    base = QRectF(cx - width / 2 - 6, top + height + 1.0, width + 12, 4.5)
    painter.setPen(stroke)
    painter.setBrush(t.surface_raised)
    painter.drawRoundedRect(base, 2.25, 2.25)


def _screen(cx: float, top: float, width: float, height: float) -> QRectF:
    return QRectF(cx - width / 2, top, width, height).adjusted(3.5, 3.5, -3.5, -3.5)


def _file_path(rect: QRectF, fold: float) -> tuple[QPainterPath, QPainterPath]:
    """Tờ file gập góc trên phải: (viền ngoài, nếp gập)."""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    outline = QPainterPath()
    outline.moveTo(x + 2.0, y)
    outline.lineTo(x + w - fold, y)
    outline.lineTo(x + w, y + fold)
    outline.lineTo(x + w, y + h - 2.0)
    outline.quadTo(x + w, y + h, x + w - 2.0, y + h)
    outline.lineTo(x + 2.0, y + h)
    outline.quadTo(x, y + h, x, y + h - 2.0)
    outline.lineTo(x, y + 2.0)
    outline.quadTo(x, y, x + 2.0, y)
    outline.closeSubpath()
    corner = QPainterPath()
    corner.moveTo(x + w - fold, y)
    corner.lineTo(x + w - fold, y + fold - 1.5)
    corner.quadTo(x + w - fold, y + fold, x + w - fold + 1.5, y + fold)
    corner.lineTo(x + w, y + fold)
    return outline, corner


def _file(painter: QPainter, t: theme.Tokens, rect: QRectF, *, width: float, lines: int) -> None:
    """Tờ file: nền `surface_raised`, viền `accent_strong`, `lines` dòng chữ `border_strong`."""
    fold = rect.width() * 0.3
    outline, corner = _file_path(rect, fold)
    painter.setPen(_pen(t.accent_strong, width))
    painter.setBrush(t.surface_raised)
    painter.drawPath(outline)
    painter.setBrush(t.accent_subtle)
    painter.drawPath(corner)
    if lines <= 0:
        return
    painter.setPen(_pen(t.border_strong, 2.0))
    left = rect.x() + rect.width() * 0.24
    gap = rect.height() * 0.17
    y = rect.y() + rect.height() * 0.46
    for index in range(lines):
        right = rect.right() - rect.width() * (0.24 if index < lines - 1 else 0.42)
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        y += gap


def _check_badge(painter: QPainter, t: theme.Tokens, center: QPointF, radius: float) -> None:
    """Huy hiệu tròn `accent_strong` có dấu tích `surface_raised`, vành `surface_raised` tách khỏi nền."""
    painter.setPen(_pen(t.surface_raised, 2.0))
    painter.setBrush(t.accent_strong)
    painter.drawEllipse(center, radius, radius)
    tick = QPainterPath()
    tick.moveTo(center.x() - radius * 0.42, center.y() + radius * 0.02)
    tick.lineTo(center.x() - radius * 0.1, center.y() + radius * 0.34)
    tick.lineTo(center.x() + radius * 0.45, center.y() - radius * 0.3)
    painter.setPen(_pen(t.surface_raised, 2.0))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(tick)


def _ghost(painter: QPainter, t: theme.Tokens, center: QPointF, radius: float) -> None:
    """Chấm tròn rỗng nét đứt: chỗ một máy khác sẽ hiện."""
    painter.setPen(_pen(t.border_strong, 1.5, dash=(2.5, 3.0)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(center, radius, radius)


def _quad(p0: QPointF, c: QPointF, p1: QPointF, s: float) -> QPointF:
    u = 1.0 - s
    return QPointF(
        u * u * p0.x() + 2 * u * s * c.x() + s * s * p1.x(),
        u * u * p0.y() + 2 * u * s * c.y() + s * s * p1.y(),
    )


# ---- Các cảnh -----------------------------------------------------------------------------------


def _paint_not_paired(painter: QPainter, t: theme.Tokens, p: float) -> None:
    with _Layer(painter, _phase(p, 0.0, 0.3), 0.0, 0.0):
        _blob(painter, t, QRectF(10, 10, 140, 76), 38.0)
    laptop_w, laptop_h, top = 30.0, 22.0, 37.0
    with _Layer(painter, _phase(p, 0.06, 0.32), -1.0, 0.0):
        _laptop(painter, t, 36.0, top, laptop_w, laptop_h)
    with _Layer(painter, _phase(p, 0.14, 0.32), 1.0, 0.0):
        _laptop(painter, t, 124.0, top, laptop_w, laptop_h)
    # Nét đứt nối hai máy, vẽ dần từ trái sang phải (cắt theo bề ngang).
    y = top + laptop_h / 2
    left, right = 58.0, 102.0
    reach = _phase(p, 0.42, 0.36, _in_out_cubic)
    if reach > 0:
        painter.save()
        painter.setClipRect(QRectF(left - 2, y - 4, (right - left + 4) * reach, 8))
        painter.setPen(_pen(t.accent_strong, 2.0, dash=(3.0, 4.0)))
        painter.drawLine(QPointF(left, y), QPointF(right, y))
        painter.restore()
    plus = _phase(p, 0.72, 0.28)
    if plus > 0:
        with _Layer(painter, plus, 0.0, 1.0):
            center = QPointF(80.0, y)
            painter.setPen(_pen(t.accent_strong, 2.0))
            painter.setBrush(t.surface_raised)
            painter.drawEllipse(center, 10.0, 10.0)
            arm = 4.5
            painter.drawLine(QPointF(center.x() - arm, center.y()), QPointF(center.x() + arm, center.y()))
            painter.drawLine(QPointF(center.x(), center.y() - arm), QPointF(center.x(), center.y() + arm))


_WAVE_RADII = (11.0, 19.0, 27.0)
_WAVE_ALPHA = (1.0, 0.7, 0.45)  # khung cuối: đứng mờ dần ra ngoài


def _paint_no_devices(painter: QPainter, t: theme.Tokens, p: float) -> None:
    center = QPointF(80.0, 50.0)
    with _Layer(painter, _phase(p, 0.0, 0.3), 0.0, 0.0):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(t.accent_subtle)
        painter.drawEllipse(center, 40.0, 40.0)
    ghosts = (
        (QPointF(24, 26), 6.5),
        (QPointF(138, 22), 5.5),
        (QPointF(30, 76), 5.0),
        (QPointF(134, 72), 6.5),
    )
    for index, (spot, radius) in enumerate(ghosts):
        with _Layer(painter, _phase(p, 0.22 + 0.08 * index, 0.3), 0.0, 1.0):
            _ghost(painter, t, spot, radius)
    laptop_w, laptop_h, top = 36.0, 24.0, 52.0
    with _Layer(painter, _phase(p, 0.08, 0.32), 0.0, 1.0):
        _laptop(painter, t, center.x(), top, laptop_w, laptop_h)
    # Ba cung sóng nở ra từ đỉnh laptop, lệch pha, rồi đứng mờ.
    origin = QPointF(center.x(), top - 4.0)
    for index, (radius, alpha) in enumerate(zip(_WAVE_RADII, _WAVE_ALPHA, strict=True)):
        grow = _phase(p, 0.36 + 0.12 * index, 0.4)
        if grow <= 0:
            continue
        r = 4.0 + (radius - 4.0) * grow
        color = QColor(t.accent_strong)
        color.setAlphaF(min(1.0, grow * 3.0) * (alpha + (1.0 - alpha) * (1.0 - grow)))
        painter.setPen(_pen(color, 2.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(origin.x() - r, origin.y() - r, 2 * r, 2 * r), 45 * 16, 90 * 16)


def _paint_no_transfers(painter: QPainter, t: theme.Tokens, p: float) -> None:
    with _Layer(painter, _phase(p, 0.0, 0.3), 0.0, 0.0):
        _blob(painter, t, QRectF(24, 8, 112, 80), 36.0)
    # Khay: hộp mở miệng, có rãnh ở giữa mép trên (như khay thư).
    tray = QRectF(50, 58, 60, 22)
    tray_t = _phase(p, 0.06, 0.32)
    # Tờ file hạ từ trên trái xuống khay theo đường cong.
    drop = _phase(p, 0.3, 0.6, _in_out_cubic)
    final = QRectF(66, 30, 28, 36)
    start = QPointF(final.x() - 14, final.y() - 18)
    control = QPointF(final.x() - 2, final.y() - 26)
    pos = _quad(start, control, final.topLeft(), drop)
    file_rect = QRectF(pos.x(), pos.y(), final.width(), final.height())
    arrow_t = _phase(p, 0.18, 0.3)
    if arrow_t > 0:
        with _Layer(painter, arrow_t, 0.0, -1.0):
            painter.setPen(_pen(t.accent_strong, 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            x = 120.0
            painter.drawLine(QPointF(x, 26), QPointF(x, 48))
            arrow = QPainterPath()
            arrow.moveTo(x - 5.5, 42.5)
            arrow.lineTo(x, 48)
            arrow.lineTo(x + 5.5, 42.5)
            painter.drawPath(arrow)
    if drop > 0:
        painter.save()
        painter.setOpacity(painter.opacity() * _clamp(drop * 2.5))
        _file(painter, t, file_rect, width=1.75, lines=2)
        painter.restore()
    if tray_t > 0:
        with _Layer(painter, tray_t, 0.0, 1.0):
            front = QPainterPath()
            x0, y0, x1, y1 = tray.left(), tray.top(), tray.right(), tray.bottom()
            notch_l, notch_r, notch_y = x0 + 18, x1 - 18, y0 + 7
            front.moveTo(x0, y0 + 4)
            front.lineTo(x0, y1 - 5)
            front.quadTo(x0, y1, x0 + 5, y1)
            front.lineTo(x1 - 5, y1)
            front.quadTo(x1, y1, x1, y1 - 5)
            front.lineTo(x1, y0 + 4)
            front.quadTo(x1, y0, x1 - 4, y0)
            front.lineTo(notch_r + 3, y0)
            front.quadTo(notch_r, y0, notch_r, y0 + 3)
            front.lineTo(notch_r, notch_y - 1)
            front.quadTo(notch_r, notch_y, notch_r - 1, notch_y)
            front.lineTo(notch_l + 1, notch_y)
            front.quadTo(notch_l, notch_y, notch_l, notch_y - 1)
            front.lineTo(notch_l, y0 + 3)
            front.quadTo(notch_l, y0, notch_l - 3, y0)
            front.lineTo(x0 + 4, y0)
            front.quadTo(x0, y0, x0, y0 + 4)
            front.closeSubpath()
            painter.setPen(_pen(t.accent_strong, 2.0))
            painter.setBrush(t.surface_raised)
            painter.drawPath(front)


def _paint_welcome(painter: QPainter, t: theme.Tokens, p: float) -> None:
    with _Layer(painter, _phase(p, 0.0, 0.25), 0.0, 0.0):
        _blob(painter, t, QRectF(10, 10, 204, 76), 38.0)
    laptop_w, laptop_h, top = 40.0, 27.0, 44.0
    left_x, right_x = 46.0, 178.0
    with _Layer(painter, _phase(p, 0.05, 0.3), -1.0, 0.0):
        _laptop(painter, t, left_x, top, laptop_w, laptop_h)
    with _Layer(painter, _phase(p, 0.12, 0.3), 1.0, 0.0):
        _laptop(painter, t, right_x, top, laptop_w, laptop_h)
    # File bay theo đường cong từ màn trái sang màn phải, để lại vệt nét đứt mờ.
    left_screen = _screen(left_x, top, laptop_w, laptop_h)
    right_screen = _screen(right_x, top, laptop_w, laptop_h)
    start = left_screen.center()
    end = right_screen.center()
    control = QPointF((start.x() + end.x()) / 2, -6.0)
    fly = _phase(p, 0.34, 0.5, _in_out_cubic)
    if fly > 0:
        trail = QPainterPath()
        trail.moveTo(_quad(start, control, end, 0.12))
        steps = 32
        for step in range(1, steps + 1):
            s = 0.12 + (fly * 0.76) * step / steps
            trail.lineTo(_quad(start, control, end, s))
        color = QColor(t.accent_strong)
        color.setAlphaF(0.55)
        painter.setPen(_pen(color, 1.75, dash=(3.0, 4.0)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(trail)
    file_w, file_h = 13.0, 16.0
    if 0 < fly < 1:
        pos = _quad(start, control, end, fly)
        rect = QRectF(pos.x() - file_w / 2, pos.y() - file_h / 2, file_w, file_h)
        painter.save()
        painter.setOpacity(painter.opacity() * _clamp(fly * 6.0))
        _file(painter, t, rect, width=1.5, lines=0)
        painter.restore()
    if fly >= 1:
        rect = QRectF(end.x() - file_w / 2, end.y() - file_h / 2, file_w, file_h)
        _file(painter, t, rect, width=1.5, lines=0)
    badge = _phase(p, 0.82, 0.18)
    if badge > 0:
        with _Layer(painter, badge, 0.0, 1.0):
            _check_badge(painter, t, QPointF(right_x + laptop_w / 2 - 1.0, top - 1.0), 8.5)


_PAINTERS: dict[Scene, Callable[[QPainter, theme.Tokens, float], None]] = {
    Scene.NOT_PAIRED: _paint_not_paired,
    Scene.NO_DEVICES: _paint_no_devices,
    Scene.NO_TRANSFERS: _paint_no_transfers,
    Scene.WELCOME: _paint_welcome,
}


def paint_scene(painter: QPainter, scene: Scene, rect: QRectF, tokens: theme.Tokens, progress: float) -> None:
    """Vẽ `scene` ở tiến độ `progress` (kẹp vào [0, 1]; 1 = khung cuối) vào `rect`, giữ tỉ lệ, căn giữa.

    Hàm thuần: chỉ đọc tham số; trạng thái của `painter` được trả lại như cũ. Cảnh lạ hay `rect` rỗng
    thì không vẽ gì.
    """
    paint = _PAINTERS.get(scene)
    base = _BASE.get(scene)
    if paint is None or base is None or rect.width() <= 0 or rect.height() <= 0:
        return
    p = float(progress) if math.isfinite(progress) else 1.0
    p = _clamp(p)
    base_w, base_h = base
    scale = min(rect.width() / base_w, rect.height() / base_h)
    painter.save()
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = rect.center()
        painter.translate(center.x() - base_w * scale / 2, center.y() - base_h * scale / 2)
        painter.scale(scale, scale)
        paint(painter, tokens, p)
    finally:
        painter.restore()


# ---- Widget -------------------------------------------------------------------------------------


def can_run(widget: QWidget) -> bool:
    """Cùng điều kiện với `motion.Loop.start()`: được hoạt ảnh, widget hiện, cửa sổ không thu nhỏ.

    Kiểm trước khi tạo `Loop`: một `Loop` chưa từng chạy mà bị hủy thì bộ dọn sổ đăng ký của `motion`
    ném TypeError (khóa giữ tham chiếu yếu đã chết, chưa từng được băm)."""
    return motion.should_animate() and widget.isVisible() and not widget.window().isMinimized()


class Illustration(QWidget):
    """Minh họa trang trí của một cảnh, chạy một lần rồi đứng ở khung cuối (xem docstring module)."""

    def __init__(self, scene: Scene = Scene.NOT_PAIRED, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("illustration")
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._scene = Scene(scene)
        self._progress = 1.0
        self._played: set[Scene] = set()
        self._loop: motion.Loop | None = None
        self.setFixedSize(size_for(self._scene))

    @property
    def scene(self) -> Scene:
        return self._scene

    @property
    def progress(self) -> float:
        return self._progress

    @property
    def playing(self) -> bool:
        loop = self._loop
        return loop is not None and isValid(loop) and loop.running

    def set_scene(self, scene: Scene) -> None:
        """Đổi cảnh; cùng cảnh thì thôi. Đang hiện mà cảnh mới chưa chạy lần nào thì chạy."""
        scene = Scene(scene)
        if scene is self._scene:
            return
        self._stop_loop()
        self._scene = scene
        self.setFixedSize(size_for(scene))
        self.update()
        if self.isVisible() and scene not in self._played:
            self._played.add(scene)
            self.play()

    def play(self) -> None:
        """Chạy lại từ đầu (một vòng `PLAY_MS`); không được hoạt ảnh hay không hiện thì đứng ở khung cuối."""
        self._stop_loop()
        if not can_run(self):
            self.update()
            return
        duration = max(1, int(PLAY_MS))
        ref = weakref.ref(self)

        def on_step(value: float) -> None:
            widget = ref()
            # Lúc hủy cây widget PySide có thể đã xóa thuộc tính Python mà Qt vẫn gửi sự kiện (xem
            # `motion.Loop.eventFilter`): khi đó bỏ qua.
            if widget is not None and isValid(widget) and "_loop" in widget.__dict__:
                widget._on_step(value)

        def on_stop() -> None:
            widget = ref()
            if widget is not None and isValid(widget) and "_loop" in widget.__dict__:
                widget._on_stop()

        loop = motion.Loop(self, duration, on_step, max_ms=duration, on_stop=on_stop)
        self._loop = loop
        loop.start()
        if loop.running:
            self._progress = 0.0
        # Không chạy được (không lường trước): giữ Loop làm con, không `deleteLater` (xem `can_run`).
        self.update()

    def _on_step(self, value: float) -> None:
        if self._loop is None:
            return
        self._progress = _clamp(value)
        self.update()

    def _on_stop(self) -> None:
        loop, self._loop = self._loop, None
        if loop is not None and isValid(loop):
            loop.deleteLater()
        self._progress = 1.0
        self.update()

    def _stop_loop(self) -> None:
        loop = self._loop
        if loop is not None and isValid(loop):
            loop.stop()  # `on_stop` → khung cuối, bỏ Loop
        self._loop = None
        self._progress = 1.0

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            paint_scene(painter, self._scene, QRectF(self.rect()), theme.tokens_for(self), self._progress)
        finally:
            painter.end()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if self._scene not in self._played:
            self._played.add(self._scene)
            self.play()

    def changeEvent(self, event: QEvent) -> None:
        super().changeEvent(event)
        if event.type() in _PALETTE_EVENTS:
            self.update()
