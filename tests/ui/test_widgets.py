"""Thành phần dùng chung `teleport.ui.widgets` (spec A3, mục 2.2–2.4, test W1–W9 ở mục 6; mục 10 “Áp dụng
hoi-lai” ghi đè phần trên).

Viết từ spec, không từ code:

- `safe_tooltip(text)` = `"<qt>" + html.escape(text).replace("\\n", "<br>") + "</qt>"` (mục 10, ý 4).
- Màu kiểm bằng `grab()` / vẽ vào `QImage`, so với `theme.tokens(dark)` ở cả sáng và tối (fixture
  `ui_theme` của `tests/ui/conftest.py`). Điểm lấy mẫu chọn sao cho mọi cách đặt hợp lý theo spec đều
  cho cùng một màu (ví dụ chấm trạng thái: điểm nằm trong chấm dù lệch ra ngoài 0, 1 hay 2 px).
- Tên icon kiểm bằng spy trên `icons.pixmap` / `icons.icon` (widget phải gọi qua thuộc tính module).
- W9 cài một `QTranslator` giả trả `"[x]" + nguồn` (mục 10, ý 10), không vá `QCoreApplication.translate`.

Module `teleport.ui.*` chỉ import bên trong test/fixture, để khi module chưa có chỉ test dùng nó đỏ.
"""

from __future__ import annotations

import html
import re
from collections import Counter

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import (
    QCoreApplication,
    QEvent,
    QMargins,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTranslator,
)
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

MODES = pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
PREFIX = "[x]"


# =================================================================================================
# Hàm phụ trợ (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


def _hex(color: QColor) -> str:
    return color.name().upper()


def _close(a: QColor, b: QColor, tol: int) -> bool:
    return (
        abs(a.red() - b.red()) <= tol
        and abs(a.green() - b.green()) <= tol
        and abs(a.blue() - b.blue()) <= tol
    )


def _pixel(image: QImage, x: float, y: float) -> QColor:
    """Màu tại tọa độ logic (x, y) của ảnh `grab()` (nhân `devicePixelRatio`)."""
    dpr = image.devicePixelRatio() or 1.0
    return image.pixelColor(int(x * dpr), int(y * dpr))


def _region_has(image: QImage, rect: QRect, color: QColor, tol: int) -> bool:
    dpr = image.devicePixelRatio() or 1.0
    for y in range(int(rect.top() * dpr), int((rect.bottom() + 1) * dpr)):
        for x in range(int(rect.left() * dpr), int((rect.right() + 1) * dpr)):
            if not (0 <= x < image.width() and 0 <= y < image.height()):
                continue
            px = image.pixelColor(x, y)
            if px.alpha() >= 250 and _close(px, color, tol):
                return True
    return False


def _dominant(image: QImage) -> QColor:
    counts: Counter = Counter()
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() >= 250:
                counts[(c.red(), c.green(), c.blue())] += 1
    r, g, b = counts.most_common(1)[0][0]
    return QColor(r, g, b)


def _tooltip_plain(tooltip: str) -> str:
    doc = QTextDocument()
    doc.setHtml(tooltip)
    return doc.toPlainText()


def _show(qtbot, widget: QWidget, w: int | None = None, h: int | None = None) -> QWidget:
    qtbot.addWidget(widget)
    if w is not None and h is not None:
        widget.resize(w, h)
    widget.show()
    qtbot.waitExposed(widget)
    QApplication.processEvents()
    return widget


def _activate(qtbot, widget: QWidget) -> None:
    widget.activateWindow()
    widget.raise_()
    qtbot.waitUntil(widget.isActiveWindow, timeout=3000)


def _geom_in(widget: QWidget, ancestor: QWidget) -> QRect:
    """Hình chữ nhật của `widget` theo tọa độ của `ancestor`."""
    return QRect(widget.mapTo(ancestor, QPoint(0, 0)), widget.size())


def _icon_image(icon: QIcon, mode: QIcon.Mode, size: int = 20) -> QImage:
    return icon.pixmap(QSize(size, size), mode).toImage()


def _opaque_pixels(image: QImage, min_alpha: int = 128) -> list[QColor]:
    """Điểm ảnh có alpha ≥ `min_alpha` (icon tô bằng SourceIn: các điểm này mang đúng màu tô)."""
    out = []
    for y in range(image.height()):
        for x in range(image.width()):
            c = image.pixelColor(x, y)
            if c.alpha() >= min_alpha:
                out.append(c)
    return out


_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"([^{}]*)\{([^{}]*)\}")


def _norm_selector(selector: str) -> str:
    return re.sub(r"[\s\"']", "", selector)


def find_rule(css: str, selector: str) -> dict[str, str]:
    """Gộp khai báo của mọi luật có đúng bộ chọn `selector` (bỏ nháy, khoảng trắng khi so)."""
    want = _norm_selector(selector)
    merged: dict[str, str] = {}
    found = False
    for m in _RULE.finditer(_COMMENT.sub("", css)):
        selectors = [s.strip() for s in m.group(1).split(",")]
        if any(_norm_selector(s) == want for s in selectors):
            found = True
            for part in m.group(2).split(";"):
                if ":" in part:
                    key, value = part.split(":", 1)
                    merged[key.strip().lower()] = value.strip()
    assert found, f"stylesheet không có luật cho {selector}"
    return merged


def css_color(value: str) -> QColor:
    m = re.search(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b", value)
    assert m, f"giá trị CSS không có mã màu #…: {value!r}"
    return QColor(m.group(0))


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        # Qt chỉ phát `LanguageChange` khi cài/gỡ một translator không rỗng.
        return False

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def icon_calls(monkeypatch):
    """Spy trên `icons.pixmap` và `icons.icon`: danh sách (tên, cỡ) của mọi lần gọi."""
    from teleport.ui import icons

    calls: list[tuple[str, int]] = []
    real_pixmap, real_icon = icons.pixmap, icons.icon

    def pixmap(name, size, *args, **kwargs):
        calls.append((name, size))
        return real_pixmap(name, size, *args, **kwargs)

    def icon(name, size, *args, **kwargs):
        calls.append((name, size))
        return real_icon(name, size, *args, **kwargs)

    monkeypatch.setattr(icons, "pixmap", pixmap)
    monkeypatch.setattr(icons, "icon", icon)
    return calls


@pytest.fixture
def translator():
    """Cài `PrefixTranslator` khi gọi; luôn gỡ khi test xong."""
    installed: list[QTranslator] = []

    def install() -> QTranslator:
        t = PrefixTranslator()
        QCoreApplication.installTranslator(t)
        installed.append(t)
        return t

    yield install
    for t in installed:
        QCoreApplication.removeTranslator(t)
    QApplication.processEvents()


# =================================================================================================
# Fixture `ui_theme` (việc #4): khôi phục palette, stylesheet, style
# =================================================================================================

# Hai test dưới chạy liền nhau theo thứ tự trong file: test đầu dùng `sentinel_state` (đặt trạng thái mốc)
# rồi `ui_theme` (lấy bằng `getfixturevalue`, nên được dọn trước `sentinel_state`); teardown của
# `sentinel_state` ghi lại trạng thái `ui_theme` trả về, test sau kiểm nó là trạng thái mốc. Ghi lại trong
# teardown chứ không để trạng thái rò sang test sau, vì fixture autouse `theme_state_reset` (spec-d6 mục 12
# ý 5) khôi phục palette + stylesheet của trước mỗi test. Trạng thái gốc được trả ở teardown của
# `sentinel_state`, hoặc ở teardown của module.
_SENTINEL: dict = {}
_SENTINEL_CSS = 'QLabel[teleportSentinel="true"] { color: #123456; }'


def _restore_original(qapp) -> None:
    original = _SENTINEL.pop("original", None)
    if original is None:
        return
    palette, css, style_name = original
    qapp.setStyleSheet("")
    if style_name:
        qapp.setStyle(style_name)
    qapp.setPalette(palette)
    qapp.setStyleSheet(css)


@pytest.fixture(scope="module", autouse=True)
def _restore_app_after_module():
    yield
    app = QApplication.instance()
    if app is not None:
        _restore_original(app)


@pytest.fixture
def sentinel_state(qapp):
    """Đặt trạng thái mốc trước `ui_theme`; teardown (chạy **sau** teardown của `ui_theme`, trước fixture
    autouse `theme_state_reset` khôi phục trạng thái trước test) ghi lại cái `ui_theme` để lại vào
    `_SENTINEL["seen"]` cho test sau kiểm, rồi trả trạng thái gốc."""
    from PySide6.QtGui import QPalette

    css = qapp.styleSheet()
    qapp.setStyleSheet("")
    _SENTINEL["original"] = (QPalette(qapp.palette()), css, qapp.style().name())
    qapp.setStyle("windows")
    pal = QPalette(qapp.palette())
    pal.setColor(QPalette.ColorRole.Window, QColor("#010203"))
    qapp.setPalette(pal)
    qapp.setStyleSheet(_SENTINEL_CSS)
    yield
    seen_css = qapp.styleSheet()
    seen_window = _hex(qapp.palette().color(QPalette.ColorRole.Window))
    qapp.setStyleSheet("")  # tên style thật chỉ đọc được khi không có stylesheet
    _SENTINEL["seen"] = (seen_css, seen_window, qapp.style().name())
    _SENTINEL["ready"] = True
    _restore_original(qapp)


def test_ui_theme_applies_scheme_and_returns_tokens(qapp, request, sentinel_state):
    from PySide6.QtGui import QPalette

    from teleport.ui import theme

    ui_theme = request.getfixturevalue("ui_theme")
    tok = ui_theme(True)
    assert _hex(tok.surface) == _hex(theme.tokens(True).surface)
    assert _hex(qapp.palette().color(QPalette.ColorRole.Window)) == _hex(theme.tokens(True).surface)
    ui_theme(False)
    assert _hex(qapp.palette().color(QPalette.ColorRole.Window)) == _hex(theme.tokens(False).surface)
    assert qapp.styleSheet() != _SENTINEL_CSS


def test_ui_theme_teardown_restored_palette_stylesheet_and_style():
    if not _SENTINEL.pop("ready", False):
        pytest.skip("chỉ chạy ngay sau test_ui_theme_applies_scheme_and_returns_tokens")
    css, window, style_name = _SENTINEL.pop("seen")
    assert css == _SENTINEL_CSS
    assert window == "#010203"
    assert style_name.lower() == "windows"


# =================================================================================================
# theme: is_dark_palette, tokens_for, ICON_BUTTON_PROPERTY (mục 2.3, mục 10 ý 6)
# =================================================================================================


def test_is_dark_palette_follows_window_vs_window_text_luminance():
    from teleport.ui import theme

    assert theme.is_dark_palette(theme.palette(True)) is True
    assert theme.is_dark_palette(theme.palette(False)) is False


@MODES
def test_tokens_for_reads_application_palette_even_with_transparent_stylesheet(ui_theme, qtbot, dark):
    from teleport.ui import theme

    tok = ui_theme(dark)
    w = QWidget()
    # QStyleSheetStyle ghi màu nền trong suốt vào palette của widget; tokens_for không được đọc palette đó.
    w.setStyleSheet("background: transparent;")
    _show(qtbot, w, 40, 40)
    assert _hex(theme.tokens_for(w).surface) == _hex(tok.surface)


def test_tokens_for_defaults_to_light_without_apply(qtbot):
    from teleport.ui import theme

    w = QWidget()
    qtbot.addWidget(w)
    if theme.is_dark_palette(QApplication.palette()):
        pytest.skip("palette mặc định của nền đang chạy là tối")
    assert _hex(theme.tokens_for(w).surface) == _hex(theme.tokens(False).surface)


def test_icon_button_property_name():
    from teleport.ui import theme

    assert theme.ICON_BUTTON_PROPERTY == "iconButton"


# =================================================================================================
# safe_tooltip
# =================================================================================================


@pytest.mark.parametrize(
    "text",
    ["", "May-A", "<b>x</b>", "a & b <c>", "nháy \"kép\" 'đơn'", "dòng 1\ndòng 2", "<img src=x>"],
)
def test_safe_tooltip_matches_spec_formula(text):
    from teleport.ui import widgets

    assert widgets.safe_tooltip(text) == "<qt>" + html.escape(text).replace("\n", "<br>") + "</qt>"


@pytest.mark.parametrize("text", ["<b>x</b>", "a & b", "<i>nghiêng</i> &amp;", "<script>x</script>"])
def test_safe_tooltip_shows_markup_as_literal_text(text):
    from teleport.ui import widgets

    assert _tooltip_plain(widgets.safe_tooltip(text)) == text


def test_safe_tooltip_keeps_line_breaks():
    from teleport.ui import widgets

    assert _tooltip_plain(widgets.safe_tooltip("một\nhai")).splitlines() == ["một", "hai"]


# =================================================================================================
# W1 IconButton
# =================================================================================================


def test_icon_button_size_constant():
    from teleport.ui import widgets

    assert widgets.ICON_BUTTON_SIZE == 32


@pytest.mark.parametrize("label", ["", " ", "\t\n "])
def test_icon_button_rejects_blank_label(qtbot, label):
    from teleport.ui.widgets import IconButton

    with pytest.raises(ValueError):
        IconButton("search", label)


def test_icon_button_rejects_unknown_icon_name(qtbot):
    from teleport.ui.widgets import IconButton

    with pytest.raises(KeyError):
        IconButton("khong_co_icon_nay", "Tìm")


def test_icon_button_accessible_name_and_tooltip_from_label(qtbot):
    from teleport.ui.widgets import IconButton, safe_tooltip

    btn = IconButton("search", "Tìm máy mới")
    qtbot.addWidget(btn)
    assert btn.accessibleName() == "Tìm máy mới"
    assert btn.toolTip() == safe_tooltip("Tìm máy mới")
    assert btn.icon_name == "search"


def test_icon_button_tooltip_includes_native_shortcut(qtbot):
    from teleport.ui.widgets import IconButton, safe_tooltip

    seq = QKeySequence("Ctrl+F")
    native = seq.toString(QKeySequence.SequenceFormat.NativeText)
    btn = IconButton("search", "Tìm", shortcut=seq)
    qtbot.addWidget(btn)
    assert btn.toolTip() == safe_tooltip(f"Tìm ({native})")
    assert native in _tooltip_plain(btn.toolTip())
    assert btn.accessibleName() == "Tìm"


def test_icon_button_shortcut_is_display_only(qtbot):
    """Phím tắt chỉ để hiện: nút không tự đăng ký phím tắt (QAction do bên gọi tạo)."""
    from teleport.ui.widgets import IconButton

    clicked: list[bool] = []
    host = QWidget()
    btn = IconButton("search", "Tìm", host, shortcut=QKeySequence("Ctrl+F"))
    btn.clicked.connect(lambda: clicked.append(True))
    _show(qtbot, host, 120, 60)
    _activate(qtbot, host)
    QTest.keyClick(host, Qt.Key.Key_F, Qt.KeyboardModifier.ControlModifier)
    QApplication.processEvents()
    assert clicked == []


def test_icon_button_markup_label_tooltip_is_literal(qtbot):
    from teleport.ui.widgets import IconButton

    btn = IconButton("search", "<b>x</b>")
    qtbot.addWidget(btn)
    assert _tooltip_plain(btn.toolTip()) == "<b>x</b>"
    assert btn.accessibleName() == "<b>x</b>"


def test_icon_only_button_is_fixed_32_square(qtbot):
    from teleport.ui.widgets import IconButton

    btn = IconButton("settings", "Cài đặt")
    _show(qtbot, btn)
    btn.resize(80, 80)  # cỡ cố định: resize không đổi được
    QApplication.processEvents()
    assert btn.size() == QSize(32, 32)
    assert btn.minimumSize() == QSize(32, 32)
    assert btn.maximumSize() == QSize(32, 32)
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonIconOnly


def test_icon_button_with_text_shows_label_beside_icon_32_high(qtbot):
    from teleport.ui.widgets import IconButton

    btn = IconButton("chevron_left", "Quay lại", show_text=True)
    _show(qtbot, btn)
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    assert btn.text() == "Quay lại"
    assert btn.height() == 32
    assert btn.width() > 32


def test_icon_button_flags(qtbot):
    from teleport.ui import theme
    from teleport.ui.widgets import IconButton

    btn = IconButton("add", "Thêm")
    qtbot.addWidget(btn)
    assert btn.property(theme.ICON_BUTTON_PROPERTY) is True
    assert btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert btn.autoRaise() is True
    assert btn.iconSize() == QSize(20, 20)


def test_icon_button_is_reachable_by_tab_and_space_clicks(qtbot):
    from teleport.ui.widgets import IconButton

    host = QWidget()
    lay = QVBoxLayout(host)
    edit = QLineEdit()
    btn = IconButton("add", "Thêm")
    lay.addWidget(edit)
    lay.addWidget(btn)
    _show(qtbot, host, 200, 100)
    _activate(qtbot, host)
    edit.setFocus()
    qtbot.waitUntil(lambda: host.focusWidget() is edit, timeout=1000)
    QTest.keyClick(edit, Qt.Key.Key_Tab)
    qtbot.waitUntil(lambda: host.focusWidget() is btn, timeout=1000)
    with qtbot.waitSignal(btn.clicked, timeout=1000):
        QTest.keyClick(btn, Qt.Key.Key_Space)


@MODES
def test_icon_button_icon_tinted_text_and_disabled_text_muted(ui_theme, qtbot, dark):
    from teleport.ui.widgets import IconButton

    tok = ui_theme(dark)
    btn = IconButton("settings", "Cài đặt")
    qtbot.addWidget(btn)
    for mode, want in ((QIcon.Mode.Normal, tok.text), (QIcon.Mode.Disabled, tok.text_muted)):
        opaque = _opaque_pixels(_icon_image(btn.icon(), mode))
        assert opaque, f"icon {mode.name} không có điểm ảnh đục"
        wrong = {_hex(c) for c in opaque if not _close(c, want, 3)}
        assert not wrong, f"icon {mode.name} phải màu {_hex(want)}, thấy {sorted(wrong)[:5]}"


def test_icon_button_retints_icon_when_palette_changes(ui_theme, qtbot):
    from teleport.ui.widgets import IconButton

    ui_theme(False)
    btn = IconButton("settings", "Cài đặt")
    _show(qtbot, btn)
    dark_tok = ui_theme(True)
    QApplication.processEvents()
    opaque = _opaque_pixels(_icon_image(btn.icon(), QIcon.Mode.Normal))
    assert opaque
    assert all(_close(c, dark_tok.text, 3) for c in opaque), "icon không tô lại theo bảng màu tối"


def test_icon_button_set_icon_name_and_set_label(qtbot, icon_calls):
    from teleport.ui.widgets import IconButton, safe_tooltip

    btn = IconButton("pause", "Tạm dừng")
    qtbot.addWidget(btn)
    icon_calls.clear()
    btn.set_icon_name("play")
    assert btn.icon_name == "play"
    assert any(name == "play" for name, _ in icon_calls), "set_icon_name phải dựng lại icon"
    btn.set_label("Tiếp tục")
    assert btn.accessibleName() == "Tiếp tục"
    assert btn.toolTip() == safe_tooltip("Tiếp tục")
    with pytest.raises(ValueError):
        btn.set_label("  ")


def test_icon_button_icon_name_is_read_only(qtbot):
    from teleport.ui.widgets import IconButton

    btn = IconButton("pause", "Tạm dừng")
    qtbot.addWidget(btn)
    with pytest.raises(AttributeError):
        btn.icon_name = "play"  # type: ignore[misc]


@MODES
def test_icon_button_stylesheet_rules(dark):
    from teleport.ui import theme

    css = theme.stylesheet(dark)
    tok = theme.tokens(dark)
    sel = 'QToolButton[iconButton="true"]'
    base = find_rule(css, sel)
    assert "transparent" in base.get("background", base.get("background-color", ""))
    assert re.search(r"\b2px\b", base.get("border", "")), base
    assert "transparent" in base.get("border", ""), base
    assert base.get("border-radius") == f"{theme.RADIUS_CONTROL}px"
    focus = find_rule(css, f"{sel}:focus")
    assert _hex(css_color(focus["border-color"])) == _hex(theme.focus_ring_color(dark))
    hover = find_rule(css, f"{sel}:hover")
    assert _hex(css_color(hover.get("background", hover.get("background-color", "")))) == _hex(tok.selected)
    pressed = find_rule(css, f"{sel}:pressed")
    assert _hex(css_color(pressed.get("background", pressed.get("background-color", "")))) == _hex(tok.border)
    disabled = find_rule(css, f"{sel}:disabled")
    assert _hex(css_color(disabled["color"])) == _hex(tok.text_muted)
    indicator = find_rule(css, f"{sel}::menu-indicator")
    assert indicator.get("image") == "none"


# =================================================================================================
# W2 StatusBadge
# =================================================================================================

BADGE_TABLE = {
    # tone: (thuộc tính `tone` của QLabel, token tô ruột chấm)
    "SUCCESS": ("success", "success"),
    "BUSY": ("accent", "accent_strong"),
    "WARNING": ("warning", "warning"),
    "MUTED": ("muted", None),
}


def test_badge_tone_values():
    from teleport.ui.widgets import BadgeTone

    assert {t.name for t in BadgeTone} == set(BADGE_TABLE)


@pytest.mark.parametrize("tone_name", list(BADGE_TABLE))
def test_status_badge_label_tone_and_accessible_name(qtbot, tone_name):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    badge = StatusBadge()
    qtbot.addWidget(badge)
    tone = BadgeTone[tone_name]
    badge.set_status(tone, "Sẵn sàng nhận")
    assert badge.label.property("tone") == BADGE_TABLE[tone_name][0]
    assert badge.label.text() == "Sẵn sàng nhận"
    assert badge.label.textFormat() == Qt.TextFormat.PlainText
    assert badge.tone is tone
    assert badge.text == "Sẵn sàng nhận"
    assert badge.accessibleName() == "Sẵn sàng nhận"
    assert badge.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_status_badge_empty_text_hides_badge(qtbot):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    host = QWidget()
    badge = StatusBadge(host)
    badge.set_status(BadgeTone.SUCCESS, "Sẵn sàng nhận")
    _show(qtbot, host, 200, 40)
    assert badge.isVisibleTo(host)
    badge.set_status(BadgeTone.SUCCESS, "")
    assert not badge.isVisibleTo(host)
    badge.set_status(BadgeTone.BUSY, "Đang truyền")
    assert badge.isVisibleTo(host)


def test_status_badge_markup_text_is_plain(qtbot):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    badge = StatusBadge()
    qtbot.addWidget(badge)
    badge.set_status(BadgeTone.WARNING, "<b>x</b>")
    assert badge.label.text() == "<b>x</b>"
    assert badge.label.textFormat() == Qt.TextFormat.PlainText


def test_status_badge_label_font_is_caption_demibold(qtbot):
    from teleport.ui import theme
    from teleport.ui.widgets import BadgeTone, StatusBadge

    badge = StatusBadge()
    qtbot.addWidget(badge)
    badge.set_status(BadgeTone.SUCCESS, "Sẵn sàng nhận")
    want = theme.font_for(theme.TextStyle.CAPTION)
    got = badge.label.font()
    assert got.weight() == QFont.Weight.DemiBold
    if want.pointSizeF() > 0:
        assert got.pointSizeF() == pytest.approx(want.pointSizeF())
    else:
        assert got.pixelSize() == want.pixelSize()


@MODES
@pytest.mark.parametrize("tone_name", ["SUCCESS", "BUSY", "WARNING"])
def test_status_badge_dot_center_has_tone_color(ui_theme, qtbot, dark, tone_name):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    tok = ui_theme(dark)
    badge = StatusBadge()
    badge.set_status(BadgeTone[tone_name], "Trạng thái")
    _show(qtbot, badge)
    dot = badge.dot
    assert dot.width() >= 8 and dot.height() >= 8
    img = dot.grab().toImage()
    want = getattr(tok, BADGE_TABLE[tone_name][1])
    center = _pixel(img, dot.width() / 2, dot.height() / 2)
    assert _close(center, want, 3), f"tâm chấm {_hex(center)} ≠ {_hex(want)}"


@MODES
def test_status_badge_muted_dot_is_hollow_offline_ring(ui_theme, qtbot, dark):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    tok = ui_theme(dark)
    badge = StatusBadge()
    badge.set_status(BadgeTone.MUTED, "Đang ẩn")
    _show(qtbot, badge)
    dot = badge.dot
    img = dot.grab().toImage()
    center = _pixel(img, dot.width() / 2, dot.height() / 2)
    assert not _close(center, tok.offline, 16), "MUTED: giữa chấm phải rỗng, không tô offline"
    assert _region_has(img, QRect(0, 0, dot.width(), dot.height()), tok.offline, 16), "thiếu vành offline"


# =================================================================================================
# W3 paint_avatar / DeviceAvatar
# =================================================================================================

# Với d = 64: chấm đường kính max(9, round(64 * 0.29)) = 19 ở góc dưới phải. Điểm (51, 51) nằm trong ruột
# chấm dù chấm lệch ra ngoài 0, 1 hay 2 px, có hay không tính vành, và nằm trong hình tròn (cách tâm
# ~27,6 < 31,5), ngoài icon (cỡ 24, đặt giữa: 20..44).
D = 64
DOT_PROBE = (51, 51)
DOT_REGION = QRect(40, 40, 24, 24)
# Điểm trong hình tròn, ngoài icon và chấm: nền của hình tròn.
BG_PROBES = ((32, 9), (9, 32))


def _avatar_image(tok, *, presence, emphasis=False, ring=None, kind=None, d=D) -> QImage:
    from teleport.ui.widgets import AvatarKind, paint_avatar

    img = QImage(d, d, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(tok.surface)  # nền đục sau avatar, như trên màn thật: điểm ảnh mép (khử răng cưa) vẫn đục
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint_avatar(
        painter,
        QRectF(0, 0, d, d),
        kind=kind if kind is not None else AvatarKind.DESKTOP,
        presence=presence,
        emphasis=emphasis,
        ring=ring if ring is not None else tok.surface,
        tokens=tok,
        dpr=1.0,
    )
    painter.end()
    return img


def test_avatar_enums():
    from teleport.ui import icons
    from teleport.ui.widgets import AvatarKind, Presence

    assert {p.name for p in Presence} == {"ONLINE", "BUSY", "OFFLINE", "NONE"}
    assert AvatarKind.DESKTOP.value == "desktop"
    assert AvatarKind.LAPTOP.value == "laptop"
    assert {k.value for k in AvatarKind} <= set(icons.NAMES)


@MODES
@pytest.mark.parametrize(("presence", "token"), [("ONLINE", "success"), ("BUSY", "accent_strong")])
def test_paint_avatar_dot_fill_color(dark, presence, token):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    img = _avatar_image(tok, presence=Presence[presence])
    got = img.pixelColor(*DOT_PROBE)
    assert _close(got, getattr(tok, token), 3), f"tâm chấm {_hex(got)} ≠ {token} {_hex(getattr(tok, token))}"


@MODES
def test_paint_avatar_offline_dot_is_ring_inside_offline_ring(dark):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    img = _avatar_image(tok, presence=Presence.OFFLINE, ring=tok.selected)
    got = img.pixelColor(*DOT_PROBE)
    assert _close(got, tok.selected, 3), (
        f"OFFLINE: ruột chấm {_hex(got)} phải là màu ring {_hex(tok.selected)}"
    )
    assert _region_has(img, DOT_REGION, tok.offline, 12), "OFFLINE: thiếu vành màu offline"
    assert not _region_has(img, DOT_REGION, tok.success, 3)


@MODES
def test_paint_avatar_none_has_no_dot(dark):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    ring = QColor("#FF00FF")  # màu không trùng token nào: có vành chấm là thấy ngay
    img = _avatar_image(tok, presence=Presence.NONE, ring=ring)
    got = img.pixelColor(*DOT_PROBE)
    assert _close(got, tok.surface_raised, 3), f"NONE: chỗ chấm {_hex(got)} phải là nền hình tròn"
    for name in ("success", "accent_strong", "offline"):
        assert not _region_has(img, DOT_REGION, getattr(tok, name), 3), f"NONE vẽ màu {name}"
    assert not _region_has(img, DOT_REGION, ring, 40), "NONE vẽ vành chấm"


@MODES
def test_paint_avatar_ring_surrounds_dot(dark):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    ring = QColor("#FF00FF")
    img = _avatar_image(tok, presence=Presence.ONLINE, ring=ring)
    assert _region_has(img, DOT_REGION, ring, 3), "thiếu vành 2 px màu ring quanh chấm"


@MODES
@pytest.mark.parametrize("presence", ["ONLINE", "OFFLINE", "NONE"])
def test_paint_avatar_background_plain_vs_emphasis(dark, presence):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    plain_img = _avatar_image(tok, presence=Presence[presence])
    emph_img = _avatar_image(tok, presence=Presence[presence], emphasis=True)
    for x, y in BG_PROBES:
        assert _close(plain_img.pixelColor(x, y), tok.surface_raised, 3), "nền thường phải surface_raised"
        assert _close(emph_img.pixelColor(x, y), tok.accent, 3), "emphasis: nền phải accent"


@MODES
def test_paint_avatar_plain_has_border_emphasis_has_none(dark):
    from teleport.ui import theme
    from teleport.ui.widgets import Presence

    tok = theme.tokens(dark)
    top = QRect(28, 0, 8, 2)  # mép trên của hình tròn
    assert _region_has(_avatar_image(tok, presence=Presence.NONE), top, tok.border, 24)
    assert not _region_has(_avatar_image(tok, presence=Presence.NONE, emphasis=True), top, tok.border, 3)


def test_device_avatar_rejects_small_diameter_and_unknown_ring(qtbot):
    from teleport.ui.widgets import DeviceAvatar

    with pytest.raises(ValueError):
        DeviceAvatar(diameter=23)
    with pytest.raises(ValueError):
        DeviceAvatar(ring="window")
    ok = DeviceAvatar(diameter=24)  # biên dưới hợp lệ
    qtbot.addWidget(ok)


@pytest.mark.parametrize("ring", ["surface", "sidebar", "surface_raised", "selected"])
def test_device_avatar_accepts_spec_rings(qtbot, ring):
    from teleport.ui.widgets import DeviceAvatar

    av = DeviceAvatar(ring=ring)
    qtbot.addWidget(av)


@pytest.mark.parametrize("diameter", [24, 38, 64])
def test_device_avatar_fixed_size_and_no_focus(qtbot, diameter):
    from teleport.ui.widgets import DeviceAvatar

    av = DeviceAvatar(diameter=diameter)
    _show(qtbot, av)
    av.resize(200, 200)
    QApplication.processEvents()
    assert av.size() == QSize(diameter, diameter)
    assert av.minimumSize() == av.maximumSize() == QSize(diameter, diameter)
    assert av.focusPolicy() == Qt.FocusPolicy.NoFocus


@MODES
def test_device_avatar_setters_repaint_with_widget_tokens(ui_theme, qtbot, dark):
    from teleport.ui.widgets import DeviceAvatar, Presence

    tok = ui_theme(dark)
    av = DeviceAvatar(diameter=D, ring="selected")
    _show(qtbot, av)
    assert _close(_pixel(av.grab().toImage(), *DOT_PROBE), tok.surface_raised, 3), "mặc định NONE"
    av.set_presence(Presence.ONLINE)
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *DOT_PROBE), tok.success, 3)
    av.set_presence(Presence.BUSY)
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *DOT_PROBE), tok.accent_strong, 3)
    av.set_presence(Presence.OFFLINE)
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *DOT_PROBE), tok.selected, 3), "OFFLINE: ruột là màu ring"
    av.set_ring("sidebar")
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *DOT_PROBE), tok.sidebar, 3), "set_ring phải đổi màu vành"
    av.set_emphasis(True)
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *BG_PROBES[0]), tok.accent, 3)


def test_device_avatar_repaints_after_palette_change(ui_theme, qtbot):
    from teleport.ui.widgets import DeviceAvatar

    ui_theme(False)
    av = DeviceAvatar(diameter=D)
    _show(qtbot, av)
    dark_tok = ui_theme(True)
    QApplication.processEvents()
    assert _close(_pixel(av.grab().toImage(), *BG_PROBES[0]), dark_tok.surface_raised, 3)


def test_device_avatar_label_sets_name_and_safe_tooltip(qtbot):
    from teleport.ui.widgets import DeviceAvatar, safe_tooltip

    av = DeviceAvatar()
    qtbot.addWidget(av)
    assert av.accessibleName() == ""
    assert av.toolTip() == ""
    av.set_label("<b>PC-Nhà</b>")
    assert av.accessibleName() == "<b>PC-Nhà</b>"
    assert av.toolTip() == safe_tooltip("<b>PC-Nhà</b>")
    assert _tooltip_plain(av.toolTip()) == "<b>PC-Nhà</b>"


def test_device_avatar_laptop_kind_uses_laptop_icon(qtbot, icon_calls):
    from teleport.ui.widgets import AvatarKind, DeviceAvatar

    av = DeviceAvatar(kind=AvatarKind.LAPTOP)
    _show(qtbot, av)
    av.grab()
    names = {name for name, _ in icon_calls}
    assert "laptop" in names
    assert "desktop" not in names


def test_device_avatar_set_kind_switches_icon(qtbot, icon_calls):
    from teleport.ui.widgets import AvatarKind, DeviceAvatar

    av = DeviceAvatar()
    _show(qtbot, av)
    av.grab()
    icon_calls.clear()
    av.set_kind(AvatarKind.LAPTOP)
    QApplication.processEvents()
    av.grab()
    assert "laptop" in {name for name, _ in icon_calls}


@pytest.mark.parametrize(("diameter", "size"), [(44, 24), (43, 20), (38, 20), (64, 24)])
def test_device_avatar_icon_size_by_diameter(qtbot, icon_calls, diameter, size):
    from teleport.ui.widgets import DeviceAvatar

    av = DeviceAvatar(diameter=diameter)
    _show(qtbot, av)
    av.grab()
    sizes = {s for name, s in icon_calls if name == "desktop"}
    assert sizes == {size}, f"d={diameter}: cỡ icon {sizes}, spec {size}"


# =================================================================================================
# W4 bubble_path
# =================================================================================================


def test_bubble_path_tail_corner_follows_direction():
    from teleport.ui.widgets import Direction, bubble_path

    w, h = 200.0, 80.0
    rect = QRectF(0, 0, w, h)
    out_path = bubble_path(rect, Direction.OUT)
    in_path = bubble_path(rect, Direction.IN)
    assert out_path.contains(QPointF(w - 2, h - 2))
    assert not out_path.contains(QPointF(2, h - 2))
    assert in_path.contains(QPointF(2, h - 2))
    assert not in_path.contains(QPointF(w - 2, h - 2))
    for path in (out_path, in_path):
        assert not path.contains(QPointF(2, 2))
        assert not path.contains(QPointF(w - 2, 2))
        assert path.contains(QPointF(w / 2, h / 2))


def test_bubble_path_respects_rect_offset():
    from teleport.ui.widgets import Direction, bubble_path

    path = bubble_path(QRectF(10, 20, 100, 50), Direction.OUT)
    assert path.boundingRect() == QRectF(10, 20, 100, 50)


def test_direction_values():
    from teleport.ui.widgets import BubbleEmphasis, Direction

    assert Direction.OUT.value == "out"
    assert Direction.IN.value == "in"
    assert {e.name for e in BubbleEmphasis} == {"NONE", "ATTENTION", "DANGER"}


# =================================================================================================
# W5 ChatBubble / BubbleRow
# =================================================================================================


def test_chat_bubble_direction_is_read_only(qtbot):
    from teleport.ui.widgets import ChatBubble, Direction

    b = ChatBubble(Direction.OUT)
    qtbot.addWidget(b)
    assert b.direction is Direction.OUT
    with pytest.raises(AttributeError):
        b.direction = Direction.IN  # type: ignore[misc]


def test_chat_bubble_summary_and_description(qtbot):
    from teleport.ui.widgets import ChatBubble, Direction

    out_b = ChatBubble(Direction.OUT)
    in_b = ChatBubble(Direction.IN)
    qtbot.addWidget(out_b)
    qtbot.addWidget(in_b)
    out_b.set_summary("Đang gửi phim-4k.mkv, 62%")
    assert out_b.accessibleName() == "Đang gửi phim-4k.mkv, 62%"
    assert out_b.accessibleDescription() == "Gửi đi"
    assert in_b.accessibleDescription() == "Nhận vào"


def test_chat_bubble_frame_flags(qtbot):
    from PySide6.QtWidgets import QFrame

    from teleport.ui.widgets import BubbleEmphasis, ChatBubble, Direction

    b = ChatBubble(Direction.IN, emphasis=BubbleEmphasis.ATTENTION)
    qtbot.addWidget(b)
    assert b.emphasis is BubbleEmphasis.ATTENTION
    b.set_emphasis(BubbleEmphasis.DANGER)
    assert b.emphasis is BubbleEmphasis.DANGER
    assert b.frameShape() == QFrame.Shape.NoFrame
    assert not b.testAttribute(Qt.WidgetAttribute.WA_StyledBackground)
    assert b.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_chat_bubble_body_margins_and_content(qtbot):
    from teleport.ui.widgets import ChatBubble, Direction

    b = ChatBubble(Direction.OUT)
    body = b.body()
    assert isinstance(body, QVBoxLayout)
    assert body.contentsMargins() == QMargins(12, 8, 12, 8)
    assert body.spacing() == 4
    label = QLabel("phim-4k.mkv")
    body.addWidget(label)
    _show(qtbot, b, 240, 80)
    assert b.isAncestorOf(label)
    assert label.isVisibleTo(b)
    assert b.rect().contains(_geom_in(label, b))


@MODES
@pytest.mark.parametrize(("direction", "token"), [("OUT", "bubble_out"), ("IN", "bubble_in")])
def test_chat_bubble_paints_background_by_direction(ui_theme, qtbot, dark, direction, token):
    from teleport.ui.widgets import ChatBubble, Direction

    tok = ui_theme(dark)
    b = ChatBubble(Direction[direction])
    _show(qtbot, b, 240, 80)
    center = _pixel(b.grab().toImage(), 120, 40)
    assert _close(center, getattr(tok, token), 3), f"{_hex(center)} ≠ {token} {_hex(getattr(tok, token))}"


def _left_edge(b) -> list[QColor]:
    img = b.grab().toImage()
    return [_pixel(img, x, b.height() / 2) for x in (0, 1)]


@MODES
@pytest.mark.parametrize("direction", ["OUT", "IN"])
@pytest.mark.parametrize(("emphasis", "token"), [("ATTENTION", "accent_strong"), ("DANGER", "danger")])
def test_chat_bubble_emphasis_border(ui_theme, qtbot, dark, direction, emphasis, token):
    from teleport.ui.widgets import BubbleEmphasis, ChatBubble, Direction

    tok = ui_theme(dark)
    b = ChatBubble(Direction[direction], emphasis=BubbleEmphasis[emphasis])
    _show(qtbot, b, 240, 80)
    edge = _left_edge(b)
    assert any(_close(c, getattr(tok, token), 10) for c in edge), (
        f"viền trái {[_hex(c) for c in edge]} phải có {token} {_hex(getattr(tok, token))}"
    )


@MODES
def test_chat_bubble_plain_borders(ui_theme, qtbot, dark):
    """OUT không viền (mép trái là nền bong bóng); IN viền 1 px `border`."""
    from teleport.ui.widgets import ChatBubble, Direction

    tok = ui_theme(dark)
    out_b = ChatBubble(Direction.OUT)
    in_b = ChatBubble(Direction.IN)
    _show(qtbot, out_b, 240, 80)
    _show(qtbot, in_b, 240, 80)
    out_edge = _left_edge(out_b)
    assert not any(_close(c, tok.border, 3) for c in out_edge if not _close(tok.border, tok.bubble_out, 3))
    assert _close(out_edge[1], tok.bubble_out, 10), f"OUT mép trái {_hex(out_edge[1])}"
    in_edge = _left_edge(in_b)
    assert _close(in_edge[0], tok.border, 12), f"IN viền {_hex(in_edge[0])} ≠ border {_hex(tok.border)}"


def test_chat_bubble_set_emphasis_repaints(ui_theme, qtbot):
    from teleport.ui.widgets import BubbleEmphasis, ChatBubble, Direction

    tok = ui_theme(False)
    b = ChatBubble(Direction.OUT)
    _show(qtbot, b, 240, 80)
    b.set_emphasis(BubbleEmphasis.DANGER)
    QApplication.processEvents()
    assert any(_close(c, tok.danger, 10) for c in _left_edge(b))


def test_chat_bubble_repaints_after_palette_change(ui_theme, qtbot):
    from teleport.ui.widgets import ChatBubble, Direction

    ui_theme(False)
    b = ChatBubble(Direction.OUT)
    _show(qtbot, b, 240, 80)
    dark_tok = ui_theme(True)
    QApplication.processEvents()
    assert _close(_pixel(b.grab().toImage(), 120, 40), dark_tok.bubble_out, 3)


def test_bubble_max_ratio_constant():
    from teleport.ui import widgets

    assert widgets.BUBBLE_MAX_RATIO == 0.62


@pytest.mark.parametrize("direction", ["OUT", "IN"])
def test_bubble_row_aligns_by_direction_and_caps_width(qtbot, direction):
    from teleport.ui.widgets import BubbleRow, ChatBubble, Direction

    b = ChatBubble(Direction[direction])
    b.body().addWidget(QLabel("phim-4k.mkv"))
    row = BubbleRow(b)
    assert row.bubble is b
    _show(qtbot, row, 600, 120)
    qtbot.waitUntil(lambda: b.maximumWidth() == 372, timeout=1000)
    geo = b.geometry()
    if direction == "OUT":
        assert abs(geo.right() - 599) <= 1, geo
    else:
        assert geo.left() == 0, geo
    assert geo.width() <= 372


def test_bubble_row_long_content_is_capped_at_ratio(qtbot):
    from teleport.ui.widgets import BubbleRow, ChatBubble, Direction

    b = ChatBubble(Direction.IN)
    wide = QLabel("phim-4k " * 80)  # chữ dài xuống dòng được (B3 tự cắt/xuống dòng nội dung)
    wide.setWordWrap(True)
    b.body().addWidget(wide)
    row = BubbleRow(b)
    _show(qtbot, row, 600, 120)
    qtbot.waitUntil(lambda: b.maximumWidth() == 372, timeout=1000)
    assert b.width() <= 372
    row.resize(300, 120)
    qtbot.waitUntil(lambda: b.maximumWidth() == 186, timeout=1000)


# =================================================================================================
# W6 InfoBar
# =================================================================================================

LEVELS = {
    # mức: (tên mức, token nền, token viền/icon, tên icon)
    "INFO": ("Thông tin", "accent_subtle", "accent_strong", "info"),
    "SUCCESS": ("Thành công", "success_bg", "success", "checkmark_circle"),
    "WARNING": ("Cảnh báo", "warning_bg", "warning", "warning"),
    "ERROR": ("Lỗi", "danger_bg", "danger", "error_circle"),
}


def _infobar(qtbot, width: int = 520):
    from teleport.ui.widgets import InfoBar

    bar = InfoBar()
    qtbot.addWidget(bar)
    bar.resize(width, 120)
    return bar


def test_info_level_values():
    from teleport.ui.widgets import InfoLevel

    assert {lv.name for lv in InfoLevel} == set(LEVELS)


@pytest.mark.parametrize("level", list(LEVELS))
def test_info_bar_show_message_sets_accessible_name_with_level(qtbot, level):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel[level], "Mất kết nối", "Đang thử nối lại.")
    bar.show()
    assert bar.isVisible()
    assert bar.accessibleName() == f"{LEVELS[level][0]}: Mất kết nối"
    assert bar.accessibleDescription() == "Đang thử nối lại."
    assert bar.level is InfoLevel[level]
    assert bar.title == "Mất kết nối"
    assert bar.text == "Đang thử nối lại."
    assert bar.title_label.text() == "Mất kết nối"
    assert bar.text_label.text() == "Đang thử nối lại."


def test_info_bar_show_message_makes_hidden_bar_visible(qtbot):
    from teleport.ui.widgets import InfoLevel

    host = QWidget()
    lay = QVBoxLayout(host)
    from teleport.ui.widgets import InfoBar

    bar = InfoBar()
    lay.addWidget(bar)
    _show(qtbot, host, 520, 200)
    bar.clear()
    assert not bar.isVisibleTo(host)
    bar.show_message(InfoLevel.ERROR, "Lỗi đĩa")
    assert bar.isVisibleTo(host)


def test_info_bar_texts_are_plain(qtbot):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.INFO, "<i>x</i>", "<b>y</b> &amp;")
    assert bar.title_label.text() == "<i>x</i>"
    assert bar.title_label.textFormat() == Qt.TextFormat.PlainText
    assert bar.text_label.text() == "<b>y</b> &amp;"
    assert bar.text_label.textFormat() == Qt.TextFormat.PlainText
    assert bar.title_label.wordWrap() and bar.text_label.wordWrap()
    assert bar.title_label.font().weight() == QFont.Weight.DemiBold


def test_info_bar_action_button_visibility_and_signal(qtbot):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.WARNING, "Đĩa sắp đầy")
    bar.show()
    assert isinstance(bar.action_button, QPushButton)
    assert not bar.action_button.isVisibleTo(bar)
    bar.show_message(InfoLevel.WARNING, "Đĩa sắp đầy", action="Mở thư mục")
    assert bar.action_button.isVisibleTo(bar)
    assert bar.action_button.text().replace("&", "") == "Mở thư mục"
    dismissed: list[bool] = []
    bar.dismissed.connect(lambda: dismissed.append(True))
    with qtbot.waitSignal(bar.action_triggered, timeout=1000):
        qtbot.mouseClick(bar.action_button, Qt.MouseButton.LeftButton)
    assert bar.isVisible(), "bấm nút hành động: thanh không tự ẩn"
    assert dismissed == []


def test_info_bar_close_hides_then_emits_dismissed(qtbot):
    from teleport.ui.widgets import IconButton, InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.ERROR, "Lỗi")
    bar.show()
    qtbot.waitExposed(bar)
    assert isinstance(bar.close_button, IconButton)
    assert bar.close_button.accessibleName() == "Đóng thông báo"
    assert bar.close_button.icon_name == "dismiss"
    assert bar.close_button.isVisibleTo(bar)
    seen: list[bool] = []
    bar.dismissed.connect(lambda: seen.append(bar.isVisible()))
    qtbot.mouseClick(bar.close_button, Qt.MouseButton.LeftButton)
    assert seen == [False], "phải ẩn trước rồi mới phát dismissed (đúng một lần)"
    assert not bar.isVisible()


def test_info_bar_not_closable_hides_close_button(qtbot):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.INFO, "Đang tìm máy", closable=False)
    bar.show()
    assert not bar.close_button.isVisibleTo(bar)
    bar.show_message(InfoLevel.INFO, "Đang tìm máy")
    assert bar.close_button.isVisibleTo(bar)


def test_info_bar_clear_hides_without_dismissed(qtbot):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.INFO, "Thông báo")
    bar.show()
    seen: list[bool] = []
    bar.dismissed.connect(lambda: seen.append(True))
    bar.clear()
    QApplication.processEvents()
    assert not bar.isVisible()
    assert seen == []


def test_info_bar_action_button_sits_below_text_aligned_with_text_column(qtbot):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot, 520)
    bar.show_message(InfoLevel.ERROR, "Không gửi được", "Máy kia đã từ chối.", action="Thử lại")
    _show(qtbot, bar)
    action = _geom_in(bar.action_button, bar)
    text = _geom_in(bar.text_label, bar)
    title = _geom_in(bar.title_label, bar)
    icon = _geom_in(bar.icon_label, bar)
    close = _geom_in(bar.close_button, bar)
    assert action.top() >= text.bottom(), f"nút {action} phải ở hàng dưới chữ {text}"
    assert abs(action.left() - text.left()) <= 1, "nút căn trái thẳng cột chữ"
    assert abs(title.left() - text.left()) <= 1
    assert icon.right() < title.left(), "icon bên trái cột chữ"
    assert close.left() > title.right(), "nút đóng ở góc phải"
    assert close.top() < action.top()


@pytest.mark.parametrize("level", list(LEVELS))
def test_info_bar_icon_name_by_level(qtbot, icon_calls, level):
    from teleport.ui.widgets import InfoLevel

    bar = _infobar(qtbot)
    icon_calls.clear()
    bar.show_message(InfoLevel[level], "Tiêu đề")
    _show(qtbot, bar)
    names = {name for name, _ in icon_calls}
    want = LEVELS[level][3]
    assert want in names
    others = {LEVELS[lv][3] for lv in LEVELS if lv != level} - {want}
    assert not (names & others), f"mức {level} dùng icon của mức khác: {names & others}"
    assert (want, 20) in icon_calls, "icon của InfoBar cỡ 20"


@MODES
@pytest.mark.parametrize("level", list(LEVELS))
def test_info_bar_paints_level_background_and_border(ui_theme, qtbot, dark, level):
    from teleport.ui.widgets import InfoLevel

    tok = ui_theme(dark)
    bar = _infobar(qtbot)
    bar.show_message(InfoLevel[level], "Tiêu đề", closable=False)
    _show(qtbot, bar, 520, 80)
    img = bar.grab().toImage()
    bg = getattr(tok, LEVELS[level][1])
    border = getattr(tok, LEVELS[level][2])
    dom = _dominant(img)
    assert _close(dom, bg, 3), f"nền {_hex(dom)} ≠ {LEVELS[level][1]} {_hex(bg)}"
    top_mid = _pixel(img, bar.width() / 2, 0)
    assert _close(top_mid, border, 16), f"viền trên {_hex(top_mid)} ≠ {LEVELS[level][2]} {_hex(border)}"
    pm = bar.icon_label.pixmap()
    assert not pm.isNull(), "icon_label phải có pixmap"
    opaque = _opaque_pixels(pm.toImage())
    assert opaque, "icon không có điểm ảnh đục"
    assert all(_close(c, border, 3) for c in opaque), f"icon phải màu {LEVELS[level][2]} {_hex(border)}"


def test_info_bar_repaints_after_palette_change(ui_theme, qtbot):
    from teleport.ui.widgets import InfoLevel

    ui_theme(False)
    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.SUCCESS, "Xong", closable=False)
    _show(qtbot, bar, 520, 80)
    dark_tok = ui_theme(True)
    QApplication.processEvents()
    assert _close(_dominant(bar.grab().toImage()), dark_tok.success_bg, 3)


def test_info_bar_alert_failure_does_not_break_show_message(qtbot, monkeypatch):
    """`QAccessible.updateAccessibility` chỉ là cố gắng tốt nhất: lỗi không lan ra."""
    from PySide6.QtGui import QAccessible

    from teleport.ui.widgets import InfoLevel

    def boom(*args, **kwargs):
        raise RuntimeError("không có trình đọc màn hình")

    monkeypatch.setattr(QAccessible, "updateAccessibility", staticmethod(boom))
    bar = _infobar(qtbot)
    bar.show_message(InfoLevel.ERROR, "Lỗi")
    assert bar.title == "Lỗi"


# =================================================================================================
# W7 EmptyState
# =================================================================================================


def _empty_state(qtbot, *, action: str | None = "Ghép đôi máy đầu tiên"):
    from teleport.ui.widgets import EmptyState

    es = EmptyState()
    es.set_content("search", "Chưa có máy nào", "Mở Teleport trên máy kia rồi bấm Tìm.", action=action)
    return _show(qtbot, es, 800, 600)


def test_empty_state_sets_plain_texts(qtbot):
    es = _empty_state(qtbot)
    assert es.title_label.text() == "Chưa có máy nào"
    assert es.text_label.text() == "Mở Teleport trên máy kia rồi bấm Tìm."
    assert es.action_button.text().replace("&", "") == "Ghép đôi máy đầu tiên"
    for label in (es.title_label, es.text_label):
        assert label.textFormat() == Qt.TextFormat.PlainText
        assert label.focusPolicy() == Qt.FocusPolicy.StrongFocus
        assert label.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert es.text_label.property("tone") == "muted"
    assert es.text_label.wordWrap()
    assert es.text_label.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert es.accessibleName() == "Chưa có máy nào"


def test_empty_state_markup_is_literal(qtbot):
    from teleport.ui.widgets import EmptyState

    es = EmptyState()
    qtbot.addWidget(es)
    es.set_content("search", "<b>t</b>", "<i>m</i>")
    assert es.title_label.text() == "<b>t</b>"
    assert es.text_label.text() == "<i>m</i>"


def test_empty_state_action_button_primary_hidden_without_action(qtbot):
    from teleport.ui import theme

    es = _empty_state(qtbot)
    assert isinstance(es.action_button, QPushButton)
    assert es.action_button.property(theme.PRIMARY_PROPERTY) is True
    assert es.action_button.isVisibleTo(es)
    es.set_content("search", "Chưa có máy nào", action=None)
    assert not es.action_button.isVisibleTo(es)


def test_empty_state_click_emits_action_triggered(qtbot):
    es = _empty_state(qtbot)
    with qtbot.waitSignal(es.action_triggered, timeout=1000):
        qtbot.mouseClick(es.action_button, Qt.MouseButton.LeftButton)


def test_empty_state_title_font_is_section(qtbot):
    from teleport.ui import theme

    es = _empty_state(qtbot)
    want = theme.font_for(theme.TextStyle.SECTION)
    got = es.title_label.font()
    assert got.family() == want.family()
    assert got.weight() == want.weight()


def test_empty_state_content_block_is_centered(qtbot):
    es = _empty_state(qtbot)
    parts = [es.icon_badge, es.title_label, es.text_label, es.action_button]
    block = QRect()
    for w in parts:
        block = block.united(_geom_in(w, es))
    center = block.center()
    assert abs(center.x() - es.width() / 2) <= 2, f"lệch ngang: khối {block} trong {es.size()}"
    assert abs(center.y() - es.height() / 2) <= 2, f"lệch dọc: khối {block} trong {es.size()}"
    assert block.width() <= 360


def test_empty_state_vertical_order_and_spacing(qtbot):
    es = _empty_state(qtbot)
    icon, title = _geom_in(es.icon_badge, es), _geom_in(es.title_label, es)
    text, button = _geom_in(es.text_label, es), _geom_in(es.action_button, es)
    assert title.top() - icon.bottom() - 1 == 16
    assert text.top() - title.bottom() - 1 == 8
    assert button.top() - text.bottom() - 1 == 16


def test_empty_state_focus_proxy_follows_action(qtbot):
    es = _empty_state(qtbot)
    assert es.focus_target() is es.action_button
    assert es.focusProxy() is es.action_button
    es.set_content("search", "Luồng rỗng", action=None)
    assert es.focus_target() is es.title_label
    assert es.focusProxy() is es.title_label
    es.set_content("search", "Có nút lại", action="Tìm")
    assert es.focusProxy() is es.action_button


@MODES
def test_empty_state_icon_badge_circle_colors(ui_theme, qtbot, dark):
    tok = ui_theme(dark)
    es = _empty_state(qtbot)
    badge = es.icon_badge
    assert badge.size() == QSize(56, 56)
    img = badge.grab().toImage()
    # (7, 28): trong hình tròn (cách tâm 21), ngoài icon (cỡ ≤ 24 đặt giữa: 16..40).
    assert _close(_pixel(img, 7, 28), tok.accent_subtle, 3), "nền vòng tròn phải accent_subtle"
    assert _region_has(img, QRect(16, 16, 24, 24), tok.accent_text, 8), "icon phải màu accent_text"


def test_empty_state_icon_uses_24_when_available(qtbot, icon_calls):
    from teleport.ui import icons
    from teleport.ui.widgets import EmptyState

    # Spec G6 A4 + mục 7: `shield_checkmark` nay có minh họa (không vẽ icon), dùng `laptop` (có cỡ 24,
    # không thuộc cảnh nào).
    assert 24 in icons.SIZES["laptop"] and 24 not in icons.SIZES["search"]
    for name, size in (("laptop", 24), ("search", 20)):
        es = EmptyState()
        es.set_content(name, "Tiêu đề")
        _show(qtbot, es, 400, 300)
        es.grab()
        sizes = {s for n, s in icon_calls if n == name}
        assert sizes == {size}, f"{name}: cỡ {sizes}, spec {size}"


# -------------------------------------------------------------------------------------------------
# EmptyState có minh họa (spec G6 mục 3, tiêu chí 6, 7; mục 7)
# -------------------------------------------------------------------------------------------------

SCENE_ICONS = (("arrow_swap", "NOT_PAIRED"), ("shield_checkmark", "NOT_PAIRED"), ("attach", "NO_TRANSFERS"))


def _scene_empty_state(qtbot, icon: str = "arrow_swap", *, action: str | None = "Tìm máy mới"):
    from teleport.ui.widgets import EmptyState

    es = EmptyState()
    es.set_content(icon, "Chưa ghép đôi máy nào", "Mở Teleport trên máy kia rồi bấm Tìm.", action=action)
    return _show(qtbot, es, 800, 600)


def test_empty_state_illustration_hidden_by_default(qtbot):
    from teleport.ui.illustrations import Illustration
    from teleport.ui.widgets import EmptyState

    es = EmptyState()
    _show(qtbot, es, 400, 300)
    assert isinstance(es.illustration, Illustration)
    assert not es.illustration.isVisibleTo(es)


@pytest.mark.parametrize(("icon", "scene"), SCENE_ICONS)
def test_empty_state_icon_with_scene_shows_illustration_instead_of_badge(qtbot, icon, scene):
    from teleport.ui.illustrations import Scene

    es = _scene_empty_state(qtbot, icon)
    assert es.illustration.isVisibleTo(es)
    assert es.illustration.scene is Scene[scene]
    assert not es.icon_badge.isVisibleTo(es)


def test_empty_state_icon_without_scene_keeps_badge(qtbot):
    es = _empty_state(qtbot)  # icon `search`: không có cảnh
    assert es.icon_badge.isVisibleTo(es)
    assert not es.illustration.isVisibleTo(es)


def test_empty_state_switches_between_scene_and_badge(qtbot):
    from teleport.ui.illustrations import Scene

    es = _scene_empty_state(qtbot, "attach")
    es.set_content("search", "Không thấy")
    assert es.icon_badge.isVisibleTo(es) and not es.illustration.isVisibleTo(es)
    es.set_content("shield_checkmark", "Chưa ghép đôi")
    assert es.illustration.isVisibleTo(es) and not es.icon_badge.isVisibleTo(es)
    assert es.illustration.scene is Scene.NOT_PAIRED


def test_empty_state_with_scene_block_is_centered(qtbot):
    es = _scene_empty_state(qtbot)
    parts = [es.illustration, es.title_label, es.text_label, es.action_button]
    block = QRect()
    for w in parts:
        block = block.united(_geom_in(w, es))
    center = block.center()
    assert abs(center.x() - es.width() / 2) <= 2, f"lệch ngang: khối {block} trong {es.size()}"
    assert abs(center.y() - es.height() / 2) <= 2, f"lệch dọc: khối {block} trong {es.size()}"
    ill = _geom_in(es.illustration, es)
    assert abs(ill.center().x() - es.width() / 2) <= 2, f"minh họa lệch ngang: {ill}"
    assert block.width() <= 360


def test_empty_state_with_scene_keeps_16_px_to_title(qtbot):
    es = _scene_empty_state(qtbot)
    ill, title = _geom_in(es.illustration, es), _geom_in(es.title_label, es)
    text, button = _geom_in(es.text_label, es), _geom_in(es.action_button, es)
    assert title.top() - ill.bottom() - 1 == 16
    assert text.top() - title.bottom() - 1 == 8
    assert button.top() - text.bottom() - 1 == 16


def test_empty_state_illustration_is_not_in_tab_chain(qtbot):
    from teleport.ui.widgets import EmptyState

    host = QWidget()
    layout = QVBoxLayout(host)
    before = QPushButton("trước", host)
    es = EmptyState(host)
    es.set_content("arrow_swap", "Chưa ghép đôi máy nào", "Mở Teleport trên máy kia.", action="Tìm máy mới")
    after = QPushButton("sau", host)
    for w in (before, es, after):
        layout.addWidget(w)
    _show(qtbot, host, 800, 600)
    _activate(qtbot, host)
    assert es.illustration.isVisibleTo(host)
    assert es.illustration.focusPolicy() == Qt.FocusPolicy.NoFocus
    before.setFocus(Qt.FocusReason.TabFocusReason)
    seen = []
    for _ in range(8):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        seen.append(QApplication.focusWidget())
    assert es.illustration not in seen
    assert es.action_button in seen, "đối chứng: Tab vẫn vào nút của EmptyState"
    assert es.focus_target() is es.action_button


def test_empty_state_with_scene_has_no_extra_accessible_text(qtbot):
    es = _scene_empty_state(qtbot)
    assert es.accessibleName() == "Chưa ghép đôi máy nào"
    assert es.illustration.accessibleName() == ""
    assert es.illustration.accessibleDescription() == ""


# =================================================================================================
# W8 PageHeader
# =================================================================================================


def test_page_header_back_button_emits_back_requested(qtbot):
    from teleport.ui.widgets import IconButton, PageHeader

    header = PageHeader("Tìm máy mới")
    _show(qtbot, header, 600, 60)
    assert isinstance(header.back_button, IconButton)
    assert header.back_button.icon_name == "chevron_left"
    with qtbot.waitSignal(header.back_requested, timeout=1000):
        qtbot.mouseClick(header.back_button, Qt.MouseButton.LeftButton)


def test_page_header_back_button_name_and_esc_tooltip(qtbot):
    from teleport.ui.widgets import PageHeader

    header = PageHeader("Tìm máy mới")
    qtbot.addWidget(header)
    btn = header.back_button
    assert btn.accessibleName() == "Quay lại"
    assert btn.text() == "Quay lại"
    assert btn.toolButtonStyle() == Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    esc = QKeySequence(Qt.Key.Key_Escape).toString(QKeySequence.SequenceFormat.NativeText)
    assert esc in _tooltip_plain(btn.toolTip())


def test_page_header_esc_is_not_handled_by_header(qtbot):
    """Phím Esc thuộc `MainWindow` (mục 2.5), không thuộc header."""
    from teleport.ui.widgets import PageHeader

    header = PageHeader("Tìm máy mới")
    _show(qtbot, header, 600, 60)
    _activate(qtbot, header)
    header.back_button.setFocus()
    seen: list[bool] = []
    header.back_requested.connect(lambda: seen.append(True))
    QTest.keyClick(header.back_button, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert seen == []


def test_page_header_title_plain_and_accessible(qtbot):
    from teleport.ui import theme
    from teleport.ui.widgets import PageHeader

    header = PageHeader()
    qtbot.addWidget(header)
    header.set_title("<b>Tìm máy</b>")
    lbl = header.title_label
    assert lbl.text() == "<b>Tìm máy</b>"
    assert lbl.textFormat() == Qt.TextFormat.PlainText
    assert lbl.accessibleName() == "<b>Tìm máy</b>"
    assert lbl.focusPolicy() == Qt.FocusPolicy.NoFocus
    want = theme.font_for(theme.TextStyle.SECTION)
    assert lbl.font().family() == want.family()
    assert lbl.font().weight() == want.weight()


def test_page_header_constructor_title(qtbot):
    from teleport.ui.widgets import PageHeader

    header = PageHeader("Cài đặt")
    qtbot.addWidget(header)
    assert header.title_label.text() == "Cài đặt"


def test_page_header_add_trailing_puts_widget_right_of_title(qtbot):
    from teleport.ui.widgets import PageHeader

    header = PageHeader("Tìm máy mới")
    edit = QLineEdit()
    edit.setPlaceholderText("Nhập IP…")
    header.add_trailing(edit)
    _show(qtbot, header, 700, 60)
    assert header.isAncestorOf(edit)
    assert edit.isVisibleTo(header)
    title = _geom_in(header.title_label, header)
    trail = _geom_in(edit, header)
    back = _geom_in(header.back_button, header)
    assert back.right() < title.left()
    assert trail.left() > title.right()


def test_page_header_margins(qtbot):
    from teleport.ui.widgets import PageHeader

    header = PageHeader("Tìm máy mới")
    _show(qtbot, header, 600, 80)
    back = _geom_in(header.back_button, header)
    assert back.left() == 16


@MODES
def test_page_header_paints_bottom_border(ui_theme, qtbot, dark):
    from teleport.ui.widgets import PageHeader

    tok = ui_theme(dark)
    header = PageHeader("Tìm máy mới")
    _show(qtbot, header, 600, 60)
    img = header.grab().toImage()
    bottom = _pixel(img, header.width() - 4, header.height() - 1)
    assert _close(bottom, tok.border, 12), f"đường kẻ dưới {_hex(bottom)} ≠ border {_hex(tok.border)}"


# =================================================================================================
# W9 retranslate
# =================================================================================================


def test_widgets_retranslate_on_language_change(qtbot, translator):
    from teleport.ui.widgets import ChatBubble, Direction, InfoBar, InfoLevel, PageHeader

    header = PageHeader("Tìm máy mới")
    bar = InfoBar()
    bar.show_message(InfoLevel.WARNING, "Đĩa sắp đầy")
    bubble = ChatBubble(Direction.IN)
    for w in (header, bar, bubble):
        _show(qtbot, w, 400, 80)
    assert PREFIX not in header.back_button.accessibleName()

    translator()

    def retranslated() -> bool:
        return (
            header.back_button.accessibleName() == PREFIX + "Quay lại"
            and bar.accessibleName().startswith(PREFIX + "Cảnh báo")
            and bubble.accessibleDescription() == PREFIX + "Nhận vào"
            and PREFIX + "Đóng thông báo" in _tooltip_plain(bar.close_button.toolTip())
        )

    qtbot.waitUntil(retranslated, timeout=3000)
    assert PREFIX + "Quay lại" in _tooltip_plain(header.back_button.toolTip())
    assert header.back_button.text() == PREFIX + "Quay lại"
    assert bar.close_button.accessibleName() == PREFIX + "Đóng thông báo"
    # Chữ của bên gọi (tiêu đề) không đi qua translate.
    assert bar.title == "Đĩa sắp đầy"
    assert header.title_label.text() == "Tìm máy mới"


def test_widgets_retranslate_by_direct_event(qtbot, translator):
    """Gửi `LanguageChange` thẳng tới widget (không chờ Qt tự phát) cũng dịch lại."""
    from teleport.ui.widgets import ChatBubble, Direction

    bubble = ChatBubble(Direction.OUT)
    qtbot.addWidget(bubble)
    translator()
    QCoreApplication.sendEvent(bubble, QEvent(QEvent.Type.LanguageChange))
    assert bubble.accessibleDescription() == PREFIX + "Gửi đi"


# =================================================================================================
# Hồi quy sau soát code: widget chưa có cha không tự bật thành cửa sổ; IconButton lỗi không để mồ côi
# =================================================================================================


def _parentless(name: str):
    from teleport.ui.widgets import BadgeTone, InfoBar, InfoLevel, StatusBadge

    if name == "badge":
        widget = StatusBadge()
        widget.set_status(BadgeTone.SUCCESS, "x")
    else:
        widget = InfoBar()
        widget.show_message(InfoLevel.INFO, "x")
    return widget


@pytest.mark.parametrize("name", ["badge", "infobar"])
def test_setter_without_parent_does_not_pop_up_window(qtbot, name):
    widget = _parentless(name)
    qtbot.addWidget(widget)
    QApplication.processEvents()
    assert not widget.isVisible(), "gọi setter khi chưa có cha không được hiện một cửa sổ riêng"
    assert widget not in [w for w in QApplication.topLevelWidgets() if w.isVisible()]


@pytest.mark.parametrize("name", ["badge", "infobar"])
def test_setter_without_parent_then_added_to_shown_parent_is_visible(qtbot, name):
    widget = _parentless(name)
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(widget)
    _show(qtbot, host, 520, 200)
    assert not widget.isWindow()
    assert widget.isVisible()


def test_status_badge_empty_text_hides_badge_set_before_parent(qtbot):
    from teleport.ui.widgets import BadgeTone, StatusBadge

    badge = StatusBadge()
    badge.set_status(BadgeTone.SUCCESS, "")
    host = QWidget()
    QVBoxLayout(host).addWidget(badge)
    _show(qtbot, host, 200, 40)
    assert not badge.isVisible()
    badge.set_status(BadgeTone.SUCCESS, "Sẵn sàng nhận")
    assert badge.isVisible()
    badge.set_status(BadgeTone.SUCCESS, "")
    assert not badge.isVisible()


def _tool_buttons(parent: QWidget) -> int:
    from PySide6.QtWidgets import QToolButton

    return len(parent.findChildren(QToolButton))


@pytest.mark.parametrize(
    ("icon_name", "label", "error"),
    [("khong_co_icon_nay", "Tìm", KeyError), ("search", "", ValueError), ("search", "  ", ValueError)],
    ids=["icon-la", "nhan-rong", "nhan-trang"],
)
def test_icon_button_failed_construction_leaves_no_orphan_in_parent(qtbot, icon_name, label, error):
    from teleport.ui.widgets import IconButton

    parent = QWidget()
    qtbot.addWidget(parent)
    ok = IconButton("search", "Tìm", parent)
    before = _tool_buttons(parent)
    assert before >= 1 and ok.parent() is parent
    with pytest.raises(error):
        IconButton(icon_name, label, parent)
    QApplication.processEvents()
    assert _tool_buttons(parent) == before


# =================================================================================================
# SegmentedControl, RovingGroup (spec D6 mục 2.5; tương phản theo mọi màu nhấn, mục 12 ý 14)
# =================================================================================================


def _accent_ids() -> tuple[str, ...]:
    from teleport.ui import theme

    return theme.ACCENTS


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("accent", ("mint", "ocean", "violet", "rose", "amber", "graphite"))
def test_segment_and_toggle_contrast_every_accent(accent, dark):
    from teleport.ui import theme, widgets

    assert accent in _accent_ids()
    t = theme.tokens(dark, accent)
    for fg, bg, minimum in widgets.SEGMENT_CONTRAST_PAIRS:
        ratio = theme.contrast_ratio(getattr(t, fg), getattr(t, bg))
        assert ratio >= minimum, (accent, dark, fg, bg, round(ratio, 2))
    for fg, bg in widgets.TOGGLE_CONTRAST_PAIRS:
        ratio = theme.contrast_ratio(getattr(t, fg), getattr(t, bg))
        assert ratio >= 3.0, (accent, dark, fg, bg, round(ratio, 2))


def test_segmented_control_arrows_select_and_tab_stops_on_checked(qtbot):
    from teleport.ui import widgets

    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    before = QPushButton("trước", host)
    seg = widgets.SegmentedControl(("a", "b", "c"), host)
    seg.set_texts(("A", "B", "C"))
    after = QPushButton("sau", host)
    for w in (before, seg, after):
        layout.addWidget(w)
    seen: list = []
    seg.value_selected.connect(seen.append)
    seg.set_value("b")
    assert seen == [], "set_value không phát"
    buttons = seg.buttons()
    assert [b.property("segment") for b in buttons] == ["first", "middle", "last"]
    assert [b.accessibleName() for b in buttons] == ["A", "B", "C"]
    host.show()
    qtbot.waitExposed(host)
    host.activateWindow()
    host.raise_()
    qtbot.waitUntil(host.isActiveWindow, timeout=3000)
    before.setFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(before, Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is buttons[1], "Tab vào nút đang chọn"
    QTest.keyClick(buttons[1], Qt.Key.Key_Right)
    assert seg.value() == "c" and buttons[2].isChecked() and QApplication.focusWidget() is buttons[2]
    QTest.keyClick(buttons[2], Qt.Key.Key_Right)
    assert seg.value() == "a", "vòng quanh"
    QTest.keyClick(buttons[0], Qt.Key.Key_Left)
    assert seg.value() == "c"
    QTest.keyClick(buttons[2], Qt.Key.Key_Home)
    assert seg.value() == "a"
    assert seen == ["c", "a", "c", "a"]
    QTest.keyClick(buttons[0], Qt.Key.Key_Tab)
    assert QApplication.focusWidget() is after, "Tab rời nhóm, không dừng ở nút chưa chọn"
    buttons[0].click()
    assert seen == ["c", "a", "c", "a"], "bấm lại nút đang chọn không phát"


def test_segmented_control_stylesheet_rules_are_narrow():
    from teleport.ui import theme

    css = theme.stylesheet(False, accent="ocean")
    t = theme.tokens(False, "ocean")
    assert 'QFrame[segmented="true"]' in css
    for position in ("first", "middle", "last"):
        assert f'QRadioButton[segment="{position}"]:checked' in css
    assert t.accent.name() in css and t.accent_text.name() in css
    assert "QRadioButton {" not in css and "QRadioButton:" not in css
