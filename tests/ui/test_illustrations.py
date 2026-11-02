"""Minh họa trạng thái trống `teleport.ui.illustrations` (spec G6 mục 2, 5; mục 6 và 7 thắng).

Viết từ spec, không từ code:

- `Scene` (StrEnum, bốn cảnh), `scene_for_icon` (`arrow_swap`, `shield_checkmark` → NOT_PAIRED,
  `attach` → NO_TRANSFERS, còn lại None).
- `paint_scene(painter, scene, rect, tokens, progress)`: hàm vẽ thuần, `progress` kẹp vào [0, 1],
  `progress == 1` là khung cuối; chỉ màu từ `tokens` (tiêu chí 1).
- `Illustration`: một vòng `PLAY_MS` qua `motion.Loop` (≤ `MAX_LOOP_MS`) rồi đứng ở khung cuối; mỗi cảnh
  chạy **một lần** trong đời widget, kể cả khi lần hiện đầu không được hoạt ảnh (A5); `set_scene` cùng
  cảnh không làm gì; `play()` gọi tay thì chạy lại; `progress < 1` chỉ khi Loop đang chạy (tiêu chí 2–6).
- B2: `CONTRAST_PAIRS` (chi tiết mang nghĩa, nền thật phía sau) ≥ 3:1 ở mọi `ACCENTS` × sáng/tối.
- B4: màu đọc lúc vẽ (`tokens_for`): đổi màu nhấn không còn điểm ảnh của màu cũ.
- B5 (mục 7): `render()` vào `QImage` DPR 1 cùng nền; chạy thật xong và chế độ tức thì lệch ≤ 2/kênh.

Test chạy thật xin `real_motion` và vá `PLAY_MS` ngắn (đọc lúc chạy); chỉ kiểm giá trị cuối, không kiểm
giữa chừng. Dựng `Illustration(parent=...)` (từ khóa) rồi `set_scene(...)`: đúng với cả
`Illustration(parent=None)` của kế hoạch lẫn `Illustration(scene, parent)` của spec mục 3.
Module `teleport.ui.*` chỉ import bên trong test/fixture.
"""

from __future__ import annotations

import math
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QRegion
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

SCENE_NAMES = ("NOT_PAIRED", "NO_DEVICES", "NO_TRANSFERS", "WELCOME")
MODES = pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
ACCENT_IDS = ("mint", "ocean", "violet", "rose", "amber", "graphite")  # theme.ACCENTS (kiểm khớp ở dưới)
SHORT_PLAY_MS = 1500
LONG_PLAY_MS = 4000
WAIT_MS = 5000
CANVAS = QSize(240, 144)  # ảnh của `paint_scene` (đủ rộng cho mọi cảnh, kể cả WELCOME)


# =================================================================================================
# Hàm phụ trợ (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


def scene(name: str):
    from teleport.ui.illustrations import Scene

    return Scene[name]


def size_of(value) -> QSize:
    """`ILLUSTRATION_SIZE` là `QSize` hay `(w, h)`: đổi về `QSize`."""
    if isinstance(value, QSize):
        return value
    w, h = value
    return QSize(int(w), int(h))


def rgba_bytes(image: QImage) -> bytes:
    img = image.convertToFormat(QImage.Format.Format_RGBA8888)
    assert img.bytesPerLine() == img.width() * 4
    return bytes(img.constBits())[: img.width() * img.height() * 4]


def has_color(image: QImage, color: QColor, tol: int) -> bool:
    data = rgba_bytes(image)
    r, g, b = color.red(), color.green(), color.blue()
    for i in range(0, len(data), 4):
        if (
            data[i + 3] >= 250
            and abs(data[i] - r) <= tol
            and abs(data[i + 1] - g) <= tol
            and abs(data[i + 2] - b) <= tol
        ):
            return True
    return False


def count_unlike(image: QImage, color: QColor, tol: int = 8) -> int:
    data = rgba_bytes(image)
    r, g, b = color.red(), color.green(), color.blue()
    n = 0
    for i in range(0, len(data), 4):
        if abs(data[i] - r) > tol or abs(data[i + 1] - g) > tol or abs(data[i + 2] - b) > tol:
            n += 1
    return n


def max_channel_diff(a: QImage, b: QImage) -> int:
    assert (a.width(), a.height()) == (b.width(), b.height()), (a.size(), b.size())
    da, db = rgba_bytes(a), rgba_bytes(b)
    return max((abs(x - y) for x, y in zip(da, db, strict=True)), default=0)


def painted(scene_value, size: QSize, tokens, progress: float, background: QColor) -> QImage:
    """Ảnh `paint_scene` vào `QImage` DPR 1, nền `background`, rect = cả ảnh."""
    from teleport.ui import illustrations

    image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(1.0)
    image.fill(background)
    painter = QPainter(image)
    try:
        illustrations.paint_scene(
            painter, scene_value, QRectF(0, 0, size.width(), size.height()), tokens, progress
        )
    finally:
        painter.end()
    return image


def rendered(widget: QWidget, background: QColor) -> QImage:
    """`widget.render()` vào `QImage` DPR 1 đã tô `background` (không vẽ nền cửa sổ)."""
    image = QImage(widget.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(1.0)
    image.fill(background)
    widget.render(image, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
    return image


def final_frame_of(ill) -> QImage:
    """Ảnh mong đợi của `ill` ở khung cuối: `paint_scene(progress=1)` cùng cỡ, cảnh, màu (tiêu chí 3)."""
    from teleport.ui import theme

    tokens = theme.tokens_for(ill)
    return painted(ill.scene, ill.size(), tokens, 1.0, tokens.surface)


def assert_final_frame(ill) -> None:
    from teleport.ui import theme

    bg = theme.tokens_for(ill).surface
    diff = max_channel_diff(rendered(ill, bg), final_frame_of(ill))
    assert diff <= 2, f"ảnh của widget lệch khung cuối {diff}/kênh"


def wcag_ratio(a: QColor, b: QColor) -> float:
    """Tỉ lệ tương phản WCAG 2.x, tính độc lập với `theme.contrast_ratio`."""

    def lum(c: QColor) -> float:
        def ch(v: int) -> float:
            s = v / 255
            return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

        return 0.2126 * ch(c.red()) + 0.7152 * ch(c.green()) + 0.0722 * ch(c.blue())

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class Host:
    """Cửa sổ nhỏ chứa một `Illustration` (con trong layout) và một nút (để Tab có chỗ đi)."""

    def __init__(self, qtbot, scene_name: str = "NOT_PAIRED", *, show: bool = True) -> None:
        from teleport.ui.illustrations import Illustration

        self.window = QWidget()
        qtbot.addWidget(self.window)
        layout = QVBoxLayout(self.window)
        self.ill = Illustration(parent=self.window)
        self.ill.set_scene(scene(scene_name))
        layout.addWidget(self.ill, 0, Qt.AlignmentFlag.AlignCenter)
        self.button = QPushButton("Nút", self.window)
        layout.addWidget(self.button)
        self.window.resize(320, 240)
        self.qtbot = qtbot
        if show:
            self.show()

    def show(self) -> None:
        self.window.show()
        self.qtbot.waitExposed(self.window)


@pytest.fixture
def play_ms(monkeypatch):
    """`play_ms(ms)`: vá `illustrations.PLAY_MS` (đọc lúc chạy, A5)."""
    from teleport.ui import illustrations

    def set_ms(ms: int) -> None:
        monkeypatch.setattr(illustrations, "PLAY_MS", ms)

    set_ms(SHORT_PLAY_MS)
    return set_ms


# =================================================================================================
# Hằng, Scene, scene_for_icon
# =================================================================================================


def test_scene_has_exactly_the_four_scenes():
    from enum import StrEnum

    from teleport.ui.illustrations import Scene

    assert issubclass(Scene, StrEnum)
    assert {s.name for s in Scene} == set(SCENE_NAMES)


@pytest.mark.parametrize(
    ("icon", "want"),
    [("arrow_swap", "NOT_PAIRED"), ("shield_checkmark", "NOT_PAIRED"), ("attach", "NO_TRANSFERS")],
)
def test_scene_for_icon_maps_empty_state_icons(icon, want):
    from teleport.ui.illustrations import scene_for_icon

    assert scene_for_icon(icon) is scene(want)


@pytest.mark.parametrize("icon", ["search", "laptop", "send", "", "ARROW_SWAP", "arrow_swap "])
def test_scene_for_icon_returns_none_for_other_icons(icon):
    from teleport.ui.illustrations import scene_for_icon

    assert scene_for_icon(icon) is None


def test_play_ms_fits_motion_loop_cap():
    from teleport.ui import illustrations, motion

    assert 0 < illustrations.PLAY_MS <= motion.MAX_LOOP_MS


def test_wave_total_fits_motion_loop_cap():
    """Mục 6 A2: tổng vòng sóng radar ≤ `MAX_LOOP_MS` (giá trị thật của module)."""
    from teleport.ui import discover, motion

    assert 0 < discover.WAVE_TOTAL_MS <= motion.MAX_LOOP_MS


def test_illustration_size_fits_empty_state_block():
    """Mục 7: `ILLUSTRATION_SIZE` 160×96 (giảm được nếu vỡ 720×460, không tăng); khối EmptyState rộng 360."""
    from teleport.ui import illustrations

    size = size_of(illustrations.ILLUSTRATION_SIZE)
    assert 0 < size.width() <= 160 and 0 < size.height() <= 96, size


@pytest.mark.parametrize("name", ["NOT_PAIRED", "NO_DEVICES", "NO_TRANSFERS"])
def test_illustration_has_fixed_size_for_empty_state_scenes(qtbot, name):
    from teleport.ui import illustrations

    host = Host(qtbot, name, show=False)
    want = size_of(illustrations.ILLUSTRATION_SIZE)
    assert host.ill.minimumSize() == want and host.ill.maximumSize() == want
    host.show()
    assert host.ill.size() == want


def test_welcome_illustration_is_fixed_and_at_most_240_wide(qtbot):
    from teleport.ui import illustrations

    host = Host(qtbot, "WELCOME")
    ill = host.ill
    assert ill.minimumSize() == ill.maximumSize(), "cỡ cố định"
    assert ill.width() <= 240, ill.size()
    assert ill.width() >= size_of(illustrations.ILLUSTRATION_SIZE).width(), "WELCOME không hẹp hơn cảnh khác"


def test_accent_ids_match_theme():
    from teleport.ui import theme

    assert tuple(theme.ACCENTS) == ACCENT_IDS


# =================================================================================================
# Tiêu chí 1: paint_scene
# =================================================================================================


@pytest.mark.parametrize("accent", ACCENT_IDS)
@pytest.mark.parametrize("name", SCENE_NAMES)
def test_paint_scene_draws_accent_and_differs_light_dark(name, accent):
    from teleport.ui import theme

    images = {}
    for dark in (False, True):
        tok = theme.tokens(dark, accent)
        image = painted(scene(name), CANVAS, tok, 1.0, tok.surface)
        assert has_color(image, tok.accent_strong, 6), (
            f"{name}/{accent}/{'tối' if dark else 'sáng'}: không có điểm màu accent_strong"
        )
        unlike = count_unlike(image, tok.surface)
        assert unlike >= 200, f"{name}/{accent}: ảnh gần như trống ({unlike} điểm khác nền)"
        images[dark] = image
    assert max_channel_diff(images[False], images[True]) > 16, f"{name}/{accent}: sáng = tối"


@pytest.mark.parametrize("name", SCENE_NAMES)
def test_paint_scene_colors_follow_accent(name):
    """Chỉ màu từ `tokens`: hai màu nhấn khác nhau cho hai ảnh khác nhau."""
    from teleport.ui import theme

    a, b = theme.tokens(False, "mint"), theme.tokens(False, "rose")
    image_a = painted(scene(name), CANVAS, a, 1.0, a.surface)
    image_b = painted(scene(name), CANVAS, b, 1.0, b.surface)
    assert max_channel_diff(image_a, image_b) > 16
    assert not has_color(image_b, a.accent_strong, 1), "ảnh màu rose còn điểm accent_strong của mint"


@pytest.mark.parametrize("name", SCENE_NAMES)
@pytest.mark.parametrize(
    ("raw", "clamped"),
    [(-1.0, 0.0), (-1e9, 0.0), (-1e-9, 0.0), (2.0, 1.0), (1e9, 1.0), (1.0 + 1e-9, 1.0)],
)
def test_paint_scene_clamps_progress(name, raw, clamped):
    """`progress` ngoài [0, 1] không ném và vẽ như giá trị đã kẹp."""
    from teleport.ui import theme

    tok = theme.tokens(True)
    got = painted(scene(name), CANVAS, tok, raw, tok.surface)
    want = painted(scene(name), CANVAS, tok, clamped, tok.surface)
    assert max_channel_diff(got, want) == 0


@pytest.mark.parametrize("name", SCENE_NAMES)
@pytest.mark.parametrize("raw", [math.inf, -math.inf, math.nan])
def test_paint_scene_non_finite_progress_does_not_raise(name, raw):
    """Tiêu chí 1: `progress` ngoài [0, 1] không ném, kể cả vô cực / NaN (spec không nói vẽ khung nào)."""
    from teleport.ui import theme

    tok = theme.tokens(False)
    painted(scene(name), CANVAS, tok, raw, tok.surface)


@pytest.mark.parametrize("name", SCENE_NAMES)
def test_paint_scene_final_frame_is_deterministic(name):
    """Khung cuối không phụ thuộc thời gian hay lần gọi trước (hàm thuần)."""
    from teleport.ui import theme

    tok = theme.tokens(False)
    first = painted(scene(name), CANVAS, tok, 1.0, tok.surface)
    painted(scene(name), CANVAS, tok, 0.3, tok.surface)  # gọi xen một khung khác
    time.sleep(0.02)
    again = painted(scene(name), CANVAS, tok, 1.0, tok.surface)
    assert max_channel_diff(first, again) == 0


@pytest.mark.parametrize("name", SCENE_NAMES)
def test_paint_scene_in_small_rect_does_not_raise(name):
    from teleport.ui import theme

    tok = theme.tokens(False)
    for size in (QSize(1, 1), QSize(8, 4), QSize(40, 24)):
        painted(scene(name), size, tok, 1.0, tok.surface)
        painted(scene(name), size, tok, 0.0, tok.surface)


# =================================================================================================
# B2: tương phản của chi tiết mang nghĩa
# =================================================================================================


def _pairs():
    from teleport.ui import illustrations

    out = []
    for pair in illustrations.CONTRAST_PAIRS:
        fg, bg, *rest = pair
        minimum = rest[0] if rest else 3.0
        out.append((fg, bg, minimum))
    return out


def test_contrast_pairs_cover_detail_on_accent_subtle():
    from teleport.ui import theme

    pairs = _pairs()
    assert pairs, "CONTRAST_PAIRS rỗng"
    fields = set(theme.Tokens.__dataclass_fields__)
    for fg, bg, minimum in pairs:
        assert fg in fields and bg in fields, (fg, bg)
        assert minimum >= 3.0, (fg, bg, minimum)
        assert bg in {"accent_subtle", "surface", "surface_raised"}, f"nền lạ: {bg}"
    assert ("accent_strong", "accent_subtle") in {(fg, bg) for fg, bg, _ in pairs}, (
        "chi tiết trên khối nền accent_subtle dùng accent_strong (mục 7)"
    )


@MODES
@pytest.mark.parametrize("accent", ACCENT_IDS)
def test_contrast_pairs_every_accent(accent, dark):
    from teleport.ui import theme

    t = theme.tokens(dark, accent)
    for fg, bg, minimum in _pairs():
        a, b = getattr(t, fg), getattr(t, bg)
        ratio = theme.contrast_ratio(a, b)
        assert ratio >= minimum, (accent, dark, fg, bg, round(ratio, 2))
        assert wcag_ratio(a, b) >= minimum - 0.01, (accent, dark, fg, bg)


# =================================================================================================
# Tiêu chí 6: trang trí
# =================================================================================================


def test_illustration_is_decorative(qtbot):
    host = Host(qtbot)
    ill = host.ill
    assert ill.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert ill.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert ill.accessibleName() == ""
    assert ill.accessibleDescription() == ""


def test_illustration_never_takes_tab_focus(qtbot):
    host = Host(qtbot)
    host.window.activateWindow()
    host.window.raise_()
    qtbot.waitUntil(host.window.isActiveWindow, timeout=3000)
    host.button.setFocus(Qt.FocusReason.TabFocusReason)
    seen = []
    for _ in range(4):
        QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Tab)
        seen.append(QApplication.focusWidget())
    assert host.ill not in seen
    QTest.mouseClick(host.ill, Qt.MouseButton.LeftButton)
    assert QApplication.focusWidget() is not host.ill


# =================================================================================================
# Tiêu chí 3: không được hoạt ảnh → khung cuối
# =================================================================================================


@MODES
@pytest.mark.parametrize("name", SCENE_NAMES)
def test_instant_mode_shows_final_frame(qtbot, ui_theme, name, dark):
    from teleport.ui import motion

    ui_theme(dark)
    host = Host(qtbot, name)
    QApplication.processEvents()
    ill = host.ill
    assert ill.scene is scene(name)
    assert not ill.playing
    assert ill.progress == 1.0
    assert motion.running_count() == 0
    assert_final_frame(ill)


def test_system_disables_animations_shows_final_frame(qtbot, real_motion, play_ms, monkeypatch):
    monkeypatch.setattr(real_motion, "animations_enabled", lambda: False)
    host = Host(qtbot, "NO_DEVICES")
    QApplication.processEvents()
    qtbot.wait(30)
    assert not host.ill.playing
    assert host.ill.progress == 1.0
    assert real_motion.running_count() == 0
    assert_final_frame(host.ill)


def test_progress_is_one_before_first_show(qtbot, real_motion, play_ms):
    """A5: `progress < 1` chỉ khi Loop đang chạy; chưa hiện thì chưa chạy."""
    host = Host(qtbot, "NO_TRANSFERS", show=False)
    assert host.ill.progress == 1.0
    assert not host.ill.playing


# =================================================================================================
# Tiêu chí 2: chạy thật một vòng rồi tự dừng
# =================================================================================================


@pytest.mark.parametrize("name", SCENE_NAMES)
def test_real_motion_plays_once_then_stops_at_final_frame(qtbot, real_motion, play_ms, name):
    host = Host(qtbot, name)
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    assert real_motion.running_count() >= 1
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    assert ill.progress == 1.0
    assert real_motion.running_count() == 0, "không timer nào còn chạy khi rảnh (N3)"
    assert_final_frame(ill)


@pytest.mark.slow
def test_real_play_ms_stops_within_five_seconds(qtbot, real_motion):
    """Tiêu chí 2 với `PLAY_MS` thật: tự dừng trong ≤ 5 s."""
    host = Host(qtbot, "WELCOME", show=False)
    t0 = time.monotonic()
    host.show()
    qtbot.waitUntil(lambda: host.ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not host.ill.playing, timeout=7000)
    assert time.monotonic() - t0 <= 5.0 + 0.8
    assert host.ill.progress == 1.0
    assert real_motion.running_count() == 0


@MODES
def test_real_run_matches_instant_render(qtbot, ui_theme, real_motion, play_ms, dark):
    """B5: ảnh sau khi chạy thật xong = ảnh ở chế độ tức thì (cùng cỡ/cảnh/màu), lệch ≤ 2/kênh."""
    from teleport.ui import theme

    ui_theme(dark)
    played = Host(qtbot, "NOT_PAIRED")
    qtbot.waitUntil(lambda: played.ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not played.ill.playing, timeout=WAIT_MS)
    bg = theme.tokens_for(played.ill).surface
    after_run = rendered(played.ill, bg)

    real_motion._force_instant(True)
    instant = Host(qtbot, "NOT_PAIRED")
    QApplication.processEvents()
    assert not instant.ill.playing
    assert instant.ill.size() == played.ill.size()
    diff = max_channel_diff(after_run, rendered(instant.ill, bg))
    assert diff <= 2, f"chạy thật xong lệch tức thì {diff}/kênh"


# =================================================================================================
# Tiêu chí 4, 5: ngắt giữa chừng
# =================================================================================================


@pytest.mark.parametrize("how", ["widget_hidden", "window_hidden", "window_minimized"])
def test_interrupted_run_stops_at_final_frame_and_never_replays(qtbot, real_motion, play_ms, how):
    play_ms(LONG_PLAY_MS)
    host = Host(qtbot, "NOT_PAIRED")
    ill, win = host.ill, host.window
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    if how == "widget_hidden":
        ill.hide()
    elif how == "window_hidden":
        win.hide()
    else:
        win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
        assert win.isMinimized()
    qtbot.waitUntil(lambda: not ill.playing, timeout=2000)
    assert ill.progress == 1.0
    assert real_motion.running_count() == 0

    if how == "widget_hidden":
        ill.show()
    elif how == "window_hidden":
        host.show()
    else:
        win.showNormal()
        qtbot.waitExposed(win)
    QApplication.processEvents()
    qtbot.wait(50)
    assert not ill.playing, "hiện lại không chạy lại"
    assert ill.progress == 1.0
    assert_final_frame(ill)


def test_finish_all_mid_run_jumps_to_final_frame(qtbot, real_motion, play_ms):
    play_ms(LONG_PLAY_MS)
    host = Host(qtbot, "WELCOME")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    real_motion.finish_all()
    assert not ill.playing
    assert ill.progress == 1.0
    assert real_motion.running_count() == 0
    assert_final_frame(ill)


# =================================================================================================
# A5: khi nào chạy
# =================================================================================================


def test_show_again_after_finished_does_not_replay(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NO_DEVICES")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    ill.hide()
    ill.show()
    QApplication.processEvents()
    qtbot.wait(50)
    assert not ill.playing


def test_set_same_scene_does_nothing(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NO_TRANSFERS")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    ill.set_scene(scene("NO_TRANSFERS"))
    QApplication.processEvents()
    assert not ill.playing
    assert ill.progress == 1.0


def test_set_same_scene_mid_run_does_not_restart_or_stop(qtbot, real_motion, play_ms):
    play_ms(LONG_PLAY_MS)
    host = Host(qtbot, "NO_TRANSFERS")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    ill.set_scene(scene("NO_TRANSFERS"))
    assert ill.playing, "cùng cảnh: không làm gì (không dừng)"


def test_set_new_scene_while_shown_plays_once_per_scene(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NOT_PAIRED")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)

    ill.set_scene(scene("NO_DEVICES"))
    assert ill.scene is scene("NO_DEVICES")
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    assert ill.progress == 1.0

    ill.set_scene(scene("NOT_PAIRED"))  # đã chạy trong đời widget
    QApplication.processEvents()
    qtbot.wait(50)
    assert ill.scene is scene("NOT_PAIRED")
    assert not ill.playing, "mỗi cảnh chạy một lần trong đời widget"
    assert ill.progress == 1.0
    assert_final_frame(ill)


def test_set_scene_while_hidden_plays_on_first_show(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NOT_PAIRED", show=False)
    ill = host.ill
    ill.set_scene(scene("WELCOME"))
    QApplication.processEvents()
    assert not ill.playing
    assert ill.progress == 1.0
    host.show()
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    assert ill.scene is scene("WELCOME")


def test_scene_counts_as_played_when_first_shown_without_animation(qtbot, real_motion, play_ms):
    """A5: cảnh đánh dấu “đã chạy” ở lần hiện đầu tiên kể cả khi lúc đó không được hoạt ảnh."""
    real_motion._force_instant(True)
    host = Host(qtbot, "NOT_PAIRED")
    ill = host.ill
    QApplication.processEvents()
    assert not ill.playing
    host.window.hide()
    real_motion._force_instant(False)
    host.show()
    QApplication.processEvents()
    qtbot.wait(50)
    assert not ill.playing, "đã hiện một lần (dù không hoạt ảnh) thì không chạy lại"
    assert ill.progress == 1.0


def test_scene_counts_as_played_when_system_disabled_animations(qtbot, real_motion, play_ms, monkeypatch):
    state = {"on": False}
    monkeypatch.setattr(real_motion, "animations_enabled", lambda: state["on"])
    host = Host(qtbot, "NO_DEVICES")
    QApplication.processEvents()
    assert not host.ill.playing
    host.ill.hide()
    state["on"] = True
    host.ill.show()
    QApplication.processEvents()
    qtbot.wait(50)
    assert not host.ill.playing


def test_play_replays_on_demand(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NO_TRANSFERS")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    ill.play()
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    assert real_motion.running_count() >= 1
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    assert ill.progress == 1.0
    assert real_motion.running_count() == 0


def test_play_reads_play_ms_each_run(qtbot, real_motion, play_ms):
    """A5: `PLAY_MS` đọc lúc chạy, Loop tạo mới mỗi lần: vòng sau theo giá trị mới."""
    play_ms(LONG_PLAY_MS)
    host = Host(qtbot, "NOT_PAIRED")
    ill = host.ill
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    real_motion.finish_all()
    assert not ill.playing
    play_ms(150)
    t0 = time.monotonic()
    ill.play()
    qtbot.waitUntil(lambda: ill.playing, timeout=1000)
    qtbot.waitUntil(lambda: not ill.playing, timeout=WAIT_MS)
    assert time.monotonic() - t0 < 2.5, "vòng mới phải dùng PLAY_MS mới (150 ms), không 4000 ms"


def test_play_while_hidden_or_instant_does_nothing(qtbot, real_motion, play_ms):
    host = Host(qtbot, "NOT_PAIRED", show=False)
    host.ill.play()
    assert not host.ill.playing and host.ill.progress == 1.0
    real_motion._force_instant(True)
    host.show()
    host.ill.play()
    QApplication.processEvents()
    assert not host.ill.playing and host.ill.progress == 1.0
    assert real_motion.running_count() == 0


# =================================================================================================
# B4: đổi màu nhấn không còn điểm ảnh cũ
# =================================================================================================


@pytest.fixture
def fake_os(qapp, monkeypatch):
    """Hệ điều hành giả (như `test_theme_preference.py`): `colorScheme` cố định Light, `setColorScheme` /
    `unsetColorScheme` không gọi thật."""
    from PySide6.QtGui import QStyleHints

    state = SimpleNamespace(scheme=Qt.ColorScheme.Light)
    monkeypatch.setattr(QStyleHints, "colorScheme", lambda self: state.scheme)
    monkeypatch.setattr(QStyleHints, "setColorScheme", lambda self, scheme: None)
    monkeypatch.setattr(QStyleHints, "unsetColorScheme", lambda self: None)
    return state


@MODES
def test_no_stale_accent_pixels_after_accent_switch(qapp, qtbot, fake_os, dark):
    from teleport.ui import theme
    from teleport.ui.illustrations import Illustration

    mode = theme.Mode.DARK if dark else theme.Mode.LIGHT
    theme.set_preference(qapp, mode, "mint")
    root = QWidget()
    qtbot.addWidget(root)
    root.setAutoFillBackground(True)
    column = QVBoxLayout(root)
    for name in SCENE_NAMES:
        ill = Illustration(parent=root)
        ill.set_scene(scene(name))
        column.addWidget(ill, 0, Qt.AlignmentFlag.AlignHCenter)
    root.resize(300, 560)
    root.show()
    qtbot.waitExposed(root)
    QApplication.processEvents()
    mint = theme.tokens(dark, "mint")
    first = root.grab().toImage()
    assert has_color(first, mint.accent_strong, 2), "đối chứng: lúc đầu phải có accent_strong của bạc hà"

    theme.set_preference(qapp, mode, "ocean")
    QApplication.processEvents()
    image = root.grab().toImage()
    ocean = theme.tokens(dark, "ocean")
    stale = [n for n in ("accent_strong", "accent_subtle") if has_color(image, getattr(mint, n), 1)]
    assert not stale, f"còn điểm ảnh bạc hà sau khi đổi sang ocean: {stale}"
    assert has_color(image, ocean.accent_strong, 2)


def test_light_dark_switch_repaints_with_new_tokens(qapp, qtbot, fake_os):
    """`PaletteChange` / `ApplicationPaletteChange` → vẽ lại: đổi sáng→tối thì ảnh là khung cuối của tối."""
    from teleport.ui import theme

    theme.set_preference(qapp, theme.Mode.LIGHT, None)
    host = Host(qtbot, "NO_DEVICES")
    QApplication.processEvents()
    assert_final_frame(host.ill)
    theme.set_preference(qapp, theme.Mode.DARK, None)
    QApplication.processEvents()
    assert theme.tokens_for(host.ill).surface.name() == theme.tokens(True).surface.name()
    assert_final_frame(host.ill)
    assert has_color(host.ill.grab().toImage(), theme.tokens(True).accent_strong, 6)
