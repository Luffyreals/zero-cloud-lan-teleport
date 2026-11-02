"""Màn “Tìm máy mới” (`teleport.ui.discover`, `teleport.ui.motion`): spec B5, test T-L1…T-L6, T-P1…T-P14,
T-M (mục 6). Mục 11 (“Quyết định sau hoi-lai”) thắng các mục trên khi khác nhau.

Viết từ spec, không từ code:

- T-L: hàm thuần `discover_devices`, `place_bubbles` (luật giữ chỗ theo H3: giữ **mọi** chỗ cũ còn hợp lệ ở
  bất kỳ vòng nào, theo thứ tự `items`; mục `previous` hỏng cấu trúc thì coi như máy mới; `None` mà
  `previous` khác rỗng thì chạy lại với `{}`). Bất biến “không chồng nhau” đúng như định nghĩa đo được
  của mục 2.4; góc trên trái số nguyên (L1).
- T-P: `DiscoverPage` với `DeviceListModel` thật, Qt `offscreen`. Thứ tự chọn dạng theo M4: TOO_MANY →
  NO_ROOM → PREFERENCE → RADAR. Câu gợi ý theo M5. Bấm đúp theo M3: các cách bấm đúp chép từ
  `DCLICK_WAYS` của `tests/ui/test_conversations.py` (không import được file test khác), giữa các kiểu bấm vá
  `discover._now` tiến quá `doubleClickInterval`.
- T-P6 (AC7) theo H5: mở trang bằng `discover_button`.
- T-M: vá seam `motion._query_client_area_animation` (M6) và `sys.platform`.

Câu chữ ở đầu file chép nguyên văn từ bảng mục 2.9 (và M5, L5): spec là nguồn của câu.
Module `teleport.ui.*` chỉ import bên trong test/fixture.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import random
import sys
import time
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QRectF, QSizeF, Qt, QTranslator
from PySide6.QtGui import QKeyEvent, QMouseEvent, QTextDocument
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

# ---- Câu chữ (spec B5 mục 2.9, M5, L5) ----------------------------------------------------------
TITLE = "Tìm máy mới"
PLACEHOLDER = "Nhập IP…"
ADDRESS_NAME = "Địa chỉ IP của máy kia"
ADDRESS_DESC = "Dùng khi máy kia không hiện ở đây. Ví dụ 192.168.1.5 hoặc 192.168.1.5:47474."
SUBMIT = "Ghép đôi"
SUBMIT_NAME = "Ghép đôi theo địa chỉ IP"
HINT = "Bấm vào một máy để ghép đôi. Máy đã ghép đôi hiện mờ."  # M5 thay câu của bảng 2.9
TO_LIST = "Dạng danh sách"
TO_RADAR = "Dạng vòng tròn"
TOO_MANY = "Có {n} máy trong mạng nên hiện dạng danh sách."
NO_ROOM = "Cửa sổ chưa đủ rộng cho dạng vòng tròn nên hiện dạng danh sách."
WAIT = "Chờ ghép đôi"
CENTER = "Bạn"
CANVAS_NAME = "Máy trong mạng"
CANVAS_DESC = "{n} máy. Tab hoặc phím mũi tên để chọn, Enter để ghép đôi."
LIST_NAME = "Máy trong mạng"
LIST_DESC = "Phím mũi tên để chọn, Enter để ghép đôi hoặc mở máy đã ghép đôi."
BUBBLE_NAME_UNPAIRED = "{name}, chưa ghép đôi"
BUBBLE_NAME_PAIRED = "{name}, đã ghép đôi"
BUBBLE_DESC_UNPAIRED = "Nhấn Enter để ghép đôi."
BUBBLE_DESC_PAIRED = "Đã ghép đôi. Nhấn Enter để mở."
TIP_UNPAIRED = "Chưa ghép đôi"  # L5
TIP_PAIRED = "Đã ghép đôi"
TIP_CONNECTED = "đã kết nối"
TIP_ONLINE = "đang trong mạng"

# tests/ui/test_conversations.py, `DCLICK_WAYS` (spec M3): ba chuỗi sự kiện của một lần bấm đúp.
DCLICK_WAYS = ("qtest_click_then_dclick", "manual_press_dblclick", "manual_dblclick_without_second_press")

PREFIX = "[x]"  # translator giả, như tests/ui/test_i18n_theme.py


# =================================================================================================
# Hàm phụ trợ (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


def view(
    name: str,
    *,
    paired: bool = False,
    online: bool = True,
    connected: bool = False,
    os: str | None = "windows",
    device_id: str | None = None,
):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id or hashlib.sha256(name.encode()).hexdigest(),
        name=name,
        os=os,
        paired=paired,
        online=online,
        connected=connected,
        addresses=("192.168.1.9",) if online else (),
        port=47474 if online else None,
    )


def online(v):
    from teleport.app.node import DeviceOnline

    return DeviceOnline(v)


def offline(v):
    import dataclasses

    from teleport.app.node import DeviceOffline

    return DeviceOffline(dataclasses.replace(v, online=False, addresses=(), port=None))


def settle(qtbot, ms: int = 30) -> None:
    QApplication.processEvents()
    qtbot.wait(ms)


def activate(qtbot, window: QWidget) -> None:
    window.show()
    qtbot.waitExposed(window)
    window.activateWindow()
    window.raise_()
    qtbot.waitUntil(window.isActiveWindow, timeout=3000)
    QApplication.processEvents()


def ids(page) -> list[str]:
    return [b.device_id for b in page.canvas.bubbles()]


def bubble_of(page, device_id: str):
    found = [b for b in page.canvas.bubbles() if b.device_id == device_id]
    assert len(found) == 1, f"cần đúng một bong bóng cho {device_id[:8]}, thấy {len(found)}"
    return found[0]


def expected_order(model) -> list[str]:
    from teleport.ui.discover import discover_devices

    return [v.device_id for v in discover_devices(model.devices())]


def norm_radius(page, bubble) -> float:
    """Bán kính chuẩn hóa (elip) của tâm bong bóng quanh tâm `core_rect()`: ~f của vòng (0,5 / 0,75 / 1)."""
    canvas = page.canvas
    c = canvas.core_rect().center()
    p = QRectF(bubble.geometry()).center()
    a = canvas.width() / 2 - bubble.width() / 2
    b = canvas.height() / 2 - bubble.height() / 2
    return math.hypot((p.x() - c.x()) / a, (p.y() - c.y()) / b)


def assert_no_overlap(page) -> None:
    """Định nghĩa đo được của “không chồng nhau” (mục 2.4) trên các bong bóng thật của canvas."""
    from teleport.ui import discover

    g = discover.BUBBLE_GAP / 2
    canvas = page.canvas
    area = QRectF(canvas.rect())
    core = canvas.core_rect()
    rects = [(b.device_id, QRectF(b.geometry())) for b in canvas.bubbles()]
    for did, r in rects:
        assert area.contains(r), f"bong bóng {did[:8]} {r} ra ngoài canvas {area}"
        assert not r.intersects(core), f"bong bóng {did[:8]} {r} đè tâm {core}"
    for (da, a), (db, b) in itertools.combinations(rects, 2):
        assert not a.adjusted(-g, -g, g, g).intersects(b.adjusted(-g, -g, g, g)), (
            f"{da[:8]} {a} chồng {db[:8]} {b}"
        )


class Spy:
    """Ghi mọi signal của `DiscoverPage`."""

    def __init__(self, page) -> None:
        self.pairs: list = []
        self.opens: list[str] = []
        self.addresses: list[tuple[str, int]] = []
        self.prefs: list[str] = []
        self.waits = 0
        page.pair_requested.connect(lambda v: self.pairs.append(v))
        page.open_device_requested.connect(lambda i: self.opens.append(i))
        page.manual_address_entered.connect(lambda ip, port: self.addresses.append((ip, port)))
        page.view_preference_changed.connect(lambda v: self.prefs.append(v))
        page.wait_pairing_requested.connect(self._wait)

    def _wait(self) -> None:
        self.waits += 1


def send_mouse(target, kind, pos, button, buttons) -> None:
    """Gửi thẳng một `QMouseEvent` tới `target` (không qua bộ sinh dblclick của QGuiApplication)."""
    ev = QMouseEvent(
        kind, QPointF(pos), QPointF(target.mapToGlobal(pos)), button, buttons, Qt.KeyboardModifier.NoModifier
    )
    QApplication.sendEvent(target, ev)


def double_click(target, pos, way: str) -> None:
    """Một lần bấm đúp chuột trái tại `pos` của `target`, theo một trong `DCLICK_WAYS`
    (`test_conversations.py`)."""
    left, none = Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton
    if way == "qtest_click_then_dclick":
        QTest.mouseClick(target, left, Qt.KeyboardModifier.NoModifier, pos)
        QTest.mouseDClick(target, left, Qt.KeyboardModifier.NoModifier, pos)
    else:
        t = QEvent.Type
        seq = [(t.MouseButtonPress, left), (t.MouseButtonRelease, none)]
        if way == "manual_press_dblclick":
            seq.append((t.MouseButtonPress, left))
        seq += [(t.MouseButtonDblClick, left), (t.MouseButtonRelease, none)]
        for kind, buttons in seq:
            send_mouse(target, kind, pos, left, buttons)
    QApplication.processEvents()


def key_event(target, key, *, auto_repeat: bool = False, modifiers=Qt.KeyboardModifier.NoModifier) -> None:
    text = "\r" if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) else ""
    for kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
        QApplication.sendEvent(target, QKeyEvent(kind, key, modifiers, text, auto_repeat))


def press_tab(times: int = 1, backward: bool = False) -> list:
    seen = []
    for _ in range(times):
        focus = QApplication.focusWidget()
        assert focus is not None, "không widget nào có tiêu điểm"
        QTest.keyClick(focus, Qt.Key.Key_Backtab if backward else Qt.Key.Key_Tab)
        seen.append(QApplication.focusWidget())
    return seen


def plain_tooltip(widget) -> str:
    doc = QTextDocument()
    doc.setHtml(widget.toolTip())
    return doc.toPlainText()


def is_alive(obj) -> bool:
    import shiboken6

    return shiboken6.isValid(obj)


class PrefixTranslator(QTranslator):
    def isEmpty(self):
        return False  # Qt chỉ phát `LanguageChange` khi cài/gỡ một translator không rỗng

    def translate(self, context, source_text, disambiguation=None, n=-1):
        if not source_text:
            return source_text
        return PREFIX + source_text


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def ui(qtbot):
    """`DiscoverPage` đứng riêng 980x660, đang hiện, với `DeviceListModel` thật (model sống cùng trang)."""
    from teleport.ui.discover import DiscoverPage
    from teleport.ui.radar import DeviceListModel

    model = DeviceListModel()
    page = DiscoverPage(model)
    model.setParent(page)
    qtbot.addWidget(page)
    page.resize(980, 660)
    page.show()
    qtbot.waitExposed(page)

    def load(views) -> None:
        model.reset(views)
        settle(qtbot)

    return SimpleNamespace(page=page, model=model, qtbot=qtbot, load=load)


@pytest.fixture
def clock(monkeypatch):
    """Đồng hồ giả cho seam `discover._now` (đọc lúc gọi); `advance()` tiến quá `doubleClickInterval`."""
    from teleport.ui import discover

    state = {"t": 1000.0}
    monkeypatch.setattr(discover, "_now", lambda: state["t"])

    def advance() -> None:
        state["t"] += QApplication.doubleClickInterval() / 1000 + 1

    return SimpleNamespace(state=state, advance=advance)


@pytest.fixture
def win(qtbot, tmp_path):
    """`MainWindow` ở RUNNING, 980x660, đang hiện và active (trang HOME)."""
    from teleport.ui.main_window import MainWindow

    w = MainWindow()
    qtbot.addWidget(w)
    w.show_running("May-A", tmp_path / "nhan")
    w.resize(980, 660)
    activate(qtbot, w)
    return w


def open_discover(qtbot, window) -> None:
    """Mở trang như người dùng (H5): tiêu điểm vào `discover_button` rồi bấm."""
    from teleport.ui.main_window import Page

    window.discover_button.setFocus(Qt.FocusReason.OtherFocusReason)
    window.discover_button.click()
    settle(qtbot)
    assert window.current_page is Page.DISCOVER


# =================================================================================================
# T-L1 bất biến của place_bubbles (500 bộ ngẫu nhiên, seed cố định; L1, L2, H3)
# =================================================================================================


def _raw_slot(ring, angle):
    """`Slot` hỏng cấu trúc (bỏ qua mọi kiểm tra của lớp nếu có)."""
    from teleport.ui.discover import Slot

    s = object.__new__(Slot)
    object.__setattr__(s, "ring", ring)
    object.__setattr__(s, "angle", angle)
    return s


def _broken_entries():
    from teleport.ui.discover import ANGLES

    return [
        "khong-phai-slot",
        None,
        (0, 1),
        _raw_slot(7, 0),
        _raw_slot("INNER", 0),
        _raw_slot(0, ANGLES),
        _raw_slot(0, -1),
        _raw_slot(0, 2.5),
    ]


def _random_case(rng: random.Random):
    from teleport.ui.discover import ANGLES, Ring, Slot

    w, h = rng.randint(300, 1400), rng.randint(200, 900)
    area = QRectF(rng.randint(0, 40), rng.randint(0, 40), w, h)
    cw, ch = rng.randint(80, 140), rng.randint(80, 120)
    c = area.center()
    core = QRectF(c.x() - cw / 2, c.y() - ch / 2, cw, ch)
    size = QSizeF(136, 96)
    n = rng.randint(0, 8)
    items = [(f"may-{i}-{rng.getrandbits(48):012x}", rng.random() < 0.5) for i in range(n)]
    previous: dict = {}
    broken = _broken_entries()
    for did, _ in items:
        roll = rng.random()
        if roll < 0.4:
            previous[did] = Slot(rng.choice(list(Ring)), rng.randrange(ANGLES))  # có thể sai hình học
        elif roll < 0.55:
            previous[did] = rng.choice(broken)  # hỏng cấu trúc
    if rng.random() < 0.3:
        previous["may-cu-khong-con"] = Slot(Ring.OUTER, 0)  # máy đã rời: phải bị bỏ qua
    return area, core, size, items, previous


def _check_layout(result, area, core, size, items) -> None:
    from teleport.ui.discover import ANGLES, BUBBLE_GAP, Ring, Slot

    g = BUBBLE_GAP / 2
    assert isinstance(result, dict)
    assert sorted(result) == sorted(d for d, _ in items), "mỗi device_id đúng một chỗ, không thừa"
    slots = []
    for did, (slot, rect) in result.items():
        assert isinstance(slot, Slot) and slot.ring in list(Ring) and 0 <= slot.angle < ANGLES, slot
        assert isinstance(rect, QRectF)
        assert rect.x() == int(rect.x()) and rect.y() == int(rect.y()), f"góc trên trái không nguyên: {rect}"
        assert (rect.width(), rect.height()) == (size.width(), size.height()), rect
        assert area.contains(rect), f"{did}: {rect} ra ngoài {area}"
        assert not rect.intersects(core), f"{did}: {rect} đè tâm {core}"
        slots.append(slot)
    assert len(set(slots)) == len(slots), f"hai máy cùng một chỗ: {slots}"
    rects = [r for _, r in result.values()]
    for a, b in itertools.combinations(rects, 2):
        assert not a.adjusted(-g, -g, g, g).intersects(b.adjusted(-g, -g, g, g)), f"{a} chồng {b}"


def test_place_bubbles_never_overlaps_on_500_random_cases():
    """T-L1 (AC2): kết quả khác None thỏa định nghĩa đo được của mục 2.4; `previous` có slot hỏng cấu trúc
    lẫn sai hình học; ≥ 30% bộ cho kết quả khác None (L2)."""
    from teleport.ui.discover import place_bubbles

    rng = random.Random(20261031)
    placed = 0
    for i in range(500):
        area, core, size, items, previous = _random_case(rng)
        result = place_bubbles(area, core, size, items, previous)
        fresh = place_bubbles(area, core, size, items, {})
        if not items:
            assert result == {} and fresh == {}, f"bộ {i}: không item phải là {{}}"
        if fresh is not None:
            # H3: None mà previous khác rỗng thì chạy lại với {} → chỉ None khi bản không previous cũng None.
            assert result is not None, f"bộ {i}: đặt được khi không có chỗ cũ mà có chỗ cũ lại None"
        if result is None:
            continue
        placed += 1
        _check_layout(result, area, core, size, items)
    assert placed >= 150, f"chỉ {placed}/500 bộ đặt được: bộ sinh không kiểm được gì"


def test_place_bubbles_rect_center_follows_slot_geometry():
    """Mục 2.4 “Ứng viên”: tâm `Slot(r, k)` = c + (f_r·rx·cos θ_k, f_r·ry·sin θ_k), θ_k = −90° + k·360°/ANGLES
    (sai số ≤ 1 px vì góc trên trái được làm tròn, L1)."""
    from teleport.ui.discover import ANGLES, RING_FRACTIONS, place_bubbles

    rng = random.Random(7)
    checked = 0
    for _ in range(200):
        area, core, size, items, _prev = _random_case(rng)
        result = place_bubbles(area, core, size, items, {})
        if not result:
            continue
        c = area.center()
        rx = area.width() / 2 - size.width() / 2
        ry = area.height() / 2 - size.height() / 2
        for slot, rect in result.values():
            f = RING_FRACTIONS[int(slot.ring)]
            theta = math.radians(-90 + slot.angle * 360 / ANGLES)
            want = QPointF(c.x() + f * rx * math.cos(theta), c.y() + f * ry * math.sin(theta))
            got = rect.center()
            assert abs(got.x() - want.x()) <= 1 and abs(got.y() - want.y()) <= 1, (slot, got, want)
            checked += 1
    assert checked > 100


# =================================================================================================
# T-L2 ổn định (luật giữ chỗ H3)
# =================================================================================================


def _roomy():
    area = QRectF(0, 0, 1200, 800)
    core = QRectF(600 - 50, 400 - 50, 100, 100)
    return area, core, QSizeF(136, 96)


def _as_previous(result) -> dict:
    return {did: slot for did, (slot, _rect) in result.items()}


def test_same_input_gives_same_layout():
    from teleport.ui.discover import place_bubbles

    rng = random.Random(11)
    for _ in range(100):
        area, core, size, items, previous = _random_case(rng)
        assert place_bubbles(area, core, size, items, previous) == place_bubbles(
            area, core, size, items, previous
        )


@pytest.mark.parametrize("seed", range(30))
def test_adding_one_item_keeps_every_old_slot_and_rect(seed):
    """T-L2: kết quả lần 1 làm `previous`, thêm một item (ở vị trí bất kỳ) → item cũ giữ slot và rect."""
    from teleport.ui.discover import place_bubbles

    rng = random.Random(seed)
    area, core, size = _roomy()
    items = [(f"cu-{i}", rng.random() < 0.5) for i in range(rng.randint(1, 7))]
    first = place_bubbles(area, core, size, items, {})
    assert first is not None
    new_items = list(items)
    new_items.insert(rng.randint(0, len(items)), ("moi", rng.random() < 0.5))
    second = place_bubbles(area, core, size, new_items, _as_previous(first))
    assert second is not None
    for did, _ in items:
        assert second[did] == first[did], f"{did} bị dời khi thêm máy mới"


@pytest.mark.parametrize("seed", range(30))
def test_removing_one_item_keeps_every_other_slot_and_rect(seed):
    from teleport.ui.discover import place_bubbles

    rng = random.Random(1000 + seed)
    area, core, size = _roomy()
    items = [(f"cu-{i}", rng.random() < 0.5) for i in range(rng.randint(2, 8))]
    first = place_bubbles(area, core, size, items, {})
    assert first is not None
    gone = rng.randrange(len(items))
    rest = items[:gone] + items[gone + 1 :]
    second = place_bubbles(area, core, size, rest, _as_previous(first))
    assert second is not None
    for did, _ in rest:
        assert second[did] == first[did], f"{did} bị dời khi bỏ một máy"


def test_valid_previous_slot_is_kept_even_outside_preferred_ring():
    """H3: bước 1 giữ mọi chỗ cũ còn hợp lệ ở bất kỳ vòng nào (máy đã ghép ở vòng ngoài không tự dời vào)."""
    from teleport.ui.discover import Ring, Slot, place_bubbles

    area, core, size = _roomy()
    result = place_bubbles(area, core, size, [("p", True)], {"p": Slot(Ring.OUTER, 4)})
    assert result is not None and result["p"][0] == Slot(Ring.OUTER, 4)
    result = place_bubbles(area, core, size, [("u", False)], {"u": Slot(Ring.INNER, 4)})
    assert result is not None and result["u"][0] == Slot(Ring.INNER, 4)


def test_conflicting_previous_slots_first_item_in_order_wins():
    """H3: bước 1 theo thứ tự `items`; chỗ cũ của máy sau trùng chỗ máy trước thì không còn hợp lệ."""
    from teleport.ui.discover import Ring, Slot, place_bubbles

    area, core, size = _roomy()
    same = Slot(Ring.OUTER, 4)
    result = place_bubbles(area, core, size, [("a", False), ("b", False)], {"a": same, "b": same})
    assert result is not None
    assert result["a"][0] == same
    assert result["b"][0] != same
    result = place_bubbles(area, core, size, [("b", False), ("a", False)], {"a": same, "b": same})
    assert result is not None and result["b"][0] == same and result["a"][0] != same


def test_geometrically_invalid_previous_slot_is_replaced():
    """Chỗ cũ không còn hợp lệ (đè tâm) → xử lý như máy mới. 900x440, tâm 80x80: INNER đỉnh đè tâm."""
    from teleport.ui.discover import Ring, Slot, place_bubbles

    area = QRectF(0, 0, 900, 440)
    core = QRectF(450 - 40, 220 - 40, 80, 80)
    size = QSizeF(136, 96)
    bad = Slot(Ring.INNER, 0)
    result = place_bubbles(area, core, size, [("p", True)], {"p": bad})
    assert result is not None and result["p"][0] != bad
    _check_layout(result, area, core, size, [("p", True)])


@pytest.mark.parametrize("index", range(8))
def test_structurally_broken_previous_entry_is_treated_as_new(index):
    """H3: mục `previous` không phải `Slot`, `ring ∉ Ring`, `angle ∉ range(ANGLES)` → bỏ qua (như máy mới)."""
    from teleport.ui.discover import Ring, Slot, place_bubbles

    area, core, size = _roomy()
    items = [("a", False), ("b", True), ("c", False)]
    keep = {"a": Slot(Ring.OUTER, 4), "c": Slot(Ring.MIDDLE, 12)}
    want = place_bubbles(area, core, size, items, keep)
    broken = _broken_entries()[index]
    got = place_bubbles(area, core, size, items, {**keep, "b": broken})
    assert got == want, f"mục hỏng {broken!r} phải bị bỏ qua"


def test_none_with_previous_retries_with_empty_previous():
    """H3: kết quả None mà `previous` khác rỗng → chạy lại một lần với {} (tìm bộ có chỗ cũ gây kẹt)."""
    from teleport.ui.discover import ANGLES, Ring, Slot, place_bubbles

    rng = random.Random(5)
    area = QRectF(0, 0, 700, 380)
    core = QRectF(350 - 45, 190 - 45, 90, 90)
    size = QSizeF(136, 96)
    for _ in range(300):
        items = [(f"m{i}", rng.random() < 0.5) for i in range(rng.randint(3, 8))]
        fresh = place_bubbles(area, core, size, items, {})
        previous = {d: Slot(rng.choice(list(Ring)), rng.randrange(ANGLES)) for d, _ in items}
        got = place_bubbles(area, core, size, items, previous)
        if fresh is not None:
            assert got is not None, f"có chỗ khi đặt mới mà chỗ cũ làm kết quả None: {items} {previous}"


# =================================================================================================
# Thứ tự thử (mục 2.4), T-L3 vòng, T-L4 không theo mã máy, T-L5 thiếu chỗ
# =================================================================================================


def test_first_unpaired_item_takes_outer_ring_first_angle():
    from teleport.ui.discover import ANGLE_ORDER, Ring, Slot, place_bubbles

    area, core, size = _roomy()
    result = place_bubbles(area, core, size, [("u", False)], {})
    assert result is not None and result["u"][0] == Slot(Ring.OUTER, ANGLE_ORDER[0])


def test_first_paired_item_takes_inner_ring_first_angle_when_room():
    from teleport.ui.discover import ANGLE_ORDER, Ring, Slot, place_bubbles

    area = QRectF(0, 0, 1400, 900)
    core = QRectF(700 - 50, 450 - 50, 100, 100)
    result = place_bubbles(area, core, QSizeF(136, 96), [("p", True)], {})
    assert result is not None and result["p"][0] == Slot(Ring.INNER, ANGLE_ORDER[0])


def test_second_item_takes_next_valid_angle_in_angle_order():
    from teleport.ui.discover import ANGLE_ORDER, Ring, Slot, place_bubbles

    area, core, size = _roomy()
    result = place_bubbles(area, core, size, [("a", False), ("b", False)], {})
    assert result is not None
    assert result["a"][0] == Slot(Ring.OUTER, ANGLE_ORDER[0])
    assert result["b"][0] == Slot(Ring.OUTER, ANGLE_ORDER[1])


def test_paired_devices_get_inner_ring_unpaired_outer():
    """T-L3: area 900x440, 2 đã ghép + 2 chưa ghép → vòng máy đã ghép < vòng máy chưa ghép."""
    from teleport.ui.discover import place_bubbles

    area = QRectF(0, 0, 900, 440)
    core = QRectF(450 - 40, 220 - 40, 80, 80)
    items = [("u1", False), ("u2", False), ("p1", True), ("p2", True)]
    result = place_bubbles(area, core, QSizeF(136, 96), items, {})
    assert result is not None
    paired = [result[d][0].ring for d in ("p1", "p2")]
    unpaired = [result[d][0].ring for d in ("u1", "u2")]
    assert max(paired) < min(unpaired), f"đã ghép {paired}, chưa ghép {unpaired}"


@pytest.mark.parametrize("seed", range(20))
def test_layout_does_not_depend_on_device_id(seed):
    """T-L4: cùng thứ tự `paired`, khác `device_id` → cùng danh sách slot theo vị trí (không góc băm)."""
    from teleport.ui.discover import place_bubbles

    rng = random.Random(seed)
    area = QRectF(0, 0, rng.randint(500, 1400), rng.randint(350, 900))
    c = area.center()
    core = QRectF(c.x() - 50, c.y() - 45, 100, 90)
    flags = [rng.random() < 0.5 for _ in range(rng.randint(1, 8))]
    a = [(hashlib.sha256(f"a{i}".encode()).hexdigest(), p) for i, p in enumerate(flags)]
    b = [(f"khac-{rng.getrandbits(64):x}-{i}", p) for i, p in enumerate(flags)]
    ra = place_bubbles(area, core, QSizeF(136, 96), a, {})
    rb = place_bubbles(area, core, QSizeF(136, 96), b, {})
    assert (ra is None) == (rb is None)
    if ra is not None:
        assert [ra[d] for d, _ in a] == [rb[d] for d, _ in b]


def test_too_small_area_gives_none_and_empty_items_give_empty_dict():
    """T-L5: area 200x150, tâm 80x80, 1 item → None; 0 item → {} (cả khi rx ≤ 0)."""
    from teleport.ui.discover import place_bubbles

    area = QRectF(0, 0, 200, 150)
    core = QRectF(100 - 40, 75 - 40, 80, 80)
    size = QSizeF(136, 96)
    assert place_bubbles(area, core, size, [("a", False)], {}) is None
    assert place_bubbles(area, core, size, [], {}) == {}
    tiny = QRectF(0, 0, 100, 80)  # rx, ry ≤ 0
    tiny_core = QRectF(30, 20, 40, 40)
    assert place_bubbles(tiny, tiny_core, size, [("a", True)], {}) is None
    assert place_bubbles(tiny, tiny_core, size, [], {}) == {}


# =================================================================================================
# T-L6 discover_devices
# =================================================================================================


def test_discover_devices_filters_offline_paired_and_keeps_connected():
    from teleport.ui.discover import discover_devices

    gone = view("Da-ghep-ngoai-tuyen", paired=True, online=False)
    conn = view("Ket-noi", paired=True, online=False, connected=True)
    seen = view("Thay", paired=True)
    stranger = view("La")
    stale = view("La-roi-mang", online=False)
    result = discover_devices([gone, conn, seen, stranger, stale])
    assert isinstance(result, list)
    assert {v.device_id for v in result} == {conn.device_id, seen.device_id, stranger.device_id}


def test_discover_devices_sorts_unpaired_first_then_nfc_casefold_name_then_id():
    from teleport.ui.discover import discover_devices

    p_a = view("Aaa", paired=True)  # tên đứng đầu nhưng đã ghép → sau mọi máy chưa ghép
    u_b = view("B")
    u_a = view("a")  # casefold: a trước B
    u_f = view("f")
    u_e = view("é")  # NFC → U+00E9, sau "f"; không NFC thì đứng trước "f"
    t2 = view("Trung", device_id="1" * 64)
    t1 = view("Trung", device_id="0" * 64)
    p_z = view("zz", paired=True, connected=True)
    got = [v.device_id for v in discover_devices([p_z, t2, u_f, p_a, u_e, u_b, t1, u_a])]
    want = [v.device_id for v in (u_a, u_b, u_f, t1, t2, u_e, p_a, p_z)]
    assert got == want


def test_discover_devices_empty():
    from teleport.ui.discover import discover_devices

    assert discover_devices([]) == []
    assert discover_devices(iter([view("x", paired=True, online=False)])) == []


# =================================================================================================
# Hằng và enum (mục 2.3, 2.4)
# =================================================================================================


def test_view_mode_and_list_reason_values():
    from teleport.app.settings import RADAR_VIEWS
    from teleport.ui.discover import RADAR_MAX, ListReason, ViewMode

    assert RADAR_MAX == 8
    assert {m.name: m.value for m in ViewMode} == {"RADAR": "radar", "LIST": "list"}
    assert set(RADAR_VIEWS) == {m.value for m in ViewMode}
    assert {r.name: r.value for r in ListReason} == {
        "NONE": "",
        "PREFERENCE": "preference",
        "TOO_MANY": "too_many",
        "NO_ROOM": "no_room",
    }


def test_angle_order_is_a_permutation_and_gap_is_8():
    from teleport.ui.discover import ANGLE_ORDER, ANGLES, BUBBLE_GAP, Ring

    assert sorted(ANGLE_ORDER) == list(range(ANGLES))
    assert ANGLE_ORDER[0] == 0
    assert BUBBLE_GAP == 8
    assert [int(r) for r in Ring] == [0, 1, 2]


# =================================================================================================
# T-M motion
# =================================================================================================


def test_animations_enabled_is_true_off_windows(monkeypatch):
    """spec-g1 Q16: ngoài Windows đọc seam macOS/GNOME (vá, tất định trên mọi HĐH), mỗi seam đúng 1 lần."""
    from teleport.ui import motion

    calls = {"macos": 0, "gnome": 0}

    def macos_reduce_motion() -> bool:
        calls["macos"] += 1
        return False

    def gnome_animations() -> bool:
        calls["gnome"] += 1
        return True

    monkeypatch.setattr(motion, "_query_macos_reduce_motion", macos_reduce_motion)
    monkeypatch.setattr(motion, "_query_gnome_animations", gnome_animations)
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is True
    assert calls == {"macos": 0, "gnome": 1}
    monkeypatch.setattr(sys, "platform", "darwin")
    assert motion.animations_enabled() is True
    assert calls == {"macos": 1, "gnome": 1}
    monkeypatch.setattr(sys, "platform", "freebsd14")
    assert motion.animations_enabled() is True
    assert calls == {"macos": 1, "gnome": 1}


@pytest.mark.parametrize(
    ("seam", "want"),
    [("raises", True), ("false", False), ("true", True)],
    ids=["loi-thi-true", "co-0-thi-false", "co-1-thi-true"],
)
def test_animations_enabled_on_windows_follows_system_setting(monkeypatch, seam, want):
    from teleport.ui import motion

    def query() -> bool:
        if seam == "raises":
            raise OSError("SystemParametersInfoW hỏng")
        return seam == "true"

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(motion, "_query_client_area_animation", query)
    assert motion.animations_enabled() is want


@pytest.mark.skipif(sys.platform != "win32", reason="chỉ Windows có SystemParametersInfoW")
def test_real_windows_query_returns_bool():
    from teleport.ui import motion

    assert isinstance(motion._query_client_area_animation(), bool)
    assert isinstance(motion.animations_enabled(), bool)


# =================================================================================================
# T-P1 thành phần
# =================================================================================================


def test_page_has_every_named_part(ui):
    from PySide6.QtWidgets import QLabel, QLineEdit, QListView, QPushButton

    from teleport.ui import theme
    from teleport.ui.discover import RadarCanvas
    from teleport.ui.widgets import InfoBar, PageHeader

    page = ui.page
    assert page.objectName() == "discoverPage"
    assert page.accessibleName() == TITLE
    parts = {
        "address_edit": (QLineEdit, "discoverAddress"),
        "address_submit": (QPushButton, "discoverAddressSubmit"),
        "info_bar": (InfoBar, "discoverInfo"),
        "hint_label": (QLabel, "discoverHint"),
        "view_button": (QPushButton, "discoverViewButton"),
        "wait_button": (QPushButton, "waitPairingButton"),
        "mode_reason_label": (QLabel, "discoverModeReason"),
        "canvas": (RadarCanvas, "radarCanvas"),
        "empty_label": (QLabel, "discoverEmpty"),
        "list_view": (QListView, "discoverList"),
    }
    for attr, (cls, name) in parts.items():
        widget = getattr(page, attr)
        assert isinstance(widget, cls), f"{attr}: {type(widget)}"
        assert widget.objectName() == name, f"{attr}: objectName {widget.objectName()!r}"
        assert page.isAncestorOf(widget), attr
    assert isinstance(page.header, PageHeader)
    assert page.header.title_label.text() == TITLE
    assert page.header.isAncestorOf(page.address_edit), "ô nhập qua header.add_trailing"
    assert page.header.isAncestorOf(page.address_submit)
    assert page.address_submit.property(theme.PRIMARY_PROPERTY) is True


def test_texts_and_accessible_names(ui):
    from teleport.ui import theme
    from teleport.ui.radar import no_devices_text

    page = ui.page
    edit = page.address_edit
    assert edit.placeholderText() == PLACEHOLDER
    assert edit.accessibleName() == ADDRESS_NAME
    assert edit.accessibleDescription() == ADDRESS_DESC
    assert plain_tooltip(edit) == ADDRESS_DESC
    assert edit.maxLength() == 64
    assert edit.inputMethodHints() & Qt.InputMethodHint.ImhPreferNumbers
    assert page.address_submit.text().replace("&", "") == SUBMIT
    assert page.address_submit.accessibleName() == SUBMIT_NAME
    hint = page.hint_label
    assert hint.text() == HINT
    assert hint.property(theme.TONE_PROPERTY) == "muted"
    assert hint.textFormat() == Qt.TextFormat.PlainText
    assert hint.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert hint.textInteractionFlags() & Qt.TextInteractionFlag.TextSelectableByMouse
    assert page.wait_button.text().replace("&", "") == WAIT
    assert page.empty_label.text() == no_devices_text()
    assert page.list_view.accessibleName() == LIST_NAME
    assert page.list_view.accessibleDescription() == LIST_DESC
    assert page.canvas.accessibleName() == CANVAS_NAME


def test_center_shows_ban_label_without_focus(ui):
    from PySide6.QtWidgets import QLabel

    labels = [w for w in ui.page.canvas.findChildren(QLabel) if w.text() == CENTER]
    assert len(labels) == 1, "tâm phải có nhãn “Bạn”"
    assert labels[0].textFormat() == Qt.TextFormat.PlainText
    assert labels[0].focusPolicy() == Qt.FocusPolicy.NoFocus
    core = ui.page.canvas.core_rect()
    assert core.contains(QRectF(labels[0].geometry())), "core_rect() phải bao nhãn “Bạn”"


def test_wait_button_hidden_until_available_and_emits(ui):
    page = ui.page
    spy = Spy(page)
    assert page.wait_button.isHidden(), "nút “Chờ ghép đôi” ẩn mặc định (mục 2.11)"
    page.set_wait_pairing_available(True)
    assert page.wait_button.isVisibleTo(page)
    page.wait_button.click()
    assert spy.waits == 1
    page.set_wait_pairing_available(False)
    assert page.wait_button.isHidden()


def test_empty_label_only_when_no_device_is_shown(ui):
    page = ui.page
    ui.load([view("Ngoai-tuyen", paired=True, online=False)])  # n = 0 sau lọc
    assert page.empty_label.isVisibleTo(page)
    assert page.canvas.accessibleDescription() == CANVAS_DESC.format(n=0)
    ui.load([view("May-1")])
    assert not page.empty_label.isVisibleTo(page)
    assert page.canvas.accessibleDescription() == CANVAS_DESC.format(n=1)


def test_empty_label_is_reachable_by_tab(ui):
    """Mục 2.8: `empty_label` nằm trong chuỗi Tab khi hiện (QLabel chọn được bằng chuột mặc định chỉ
    ClickFocus: phải đặt StrongFocus **sau** `setTextInteractionFlags`)."""
    assert ui.page.empty_label.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_page_does_not_accept_drops(ui):
    ui.load([view("May-1")])
    assert not ui.page.list_view.dragEnabled()
    assert not ui.page.list_view.acceptDrops()
    assert not bubble_of(ui.page, view("May-1").device_id).acceptDrops()


# =================================================================================================
# RadarBubble (mục 2.5, 2.8, L5, L7)
# =================================================================================================


def test_bubble_properties_names_and_tooltip_for_unpaired(qtbot):
    from teleport.ui import texts
    from teleport.ui.discover import RadarBubble

    v = view("May-X", os="windows")
    b = RadarBubble(v)
    qtbot.addWidget(b)
    assert b.objectName() == "radarBubble"
    assert b.device_id == v.device_id and b.view == v
    assert b.property("paired") is False
    assert b.focusPolicy() == Qt.FocusPolicy.StrongFocus
    name = texts.peer_label(v.name, v.device_id)
    assert b.accessibleName() == BUBBLE_NAME_UNPAIRED.format(name=name)
    assert BUBBLE_DESC_UNPAIRED in b.accessibleDescription()
    tip = plain_tooltip(b)
    assert tip.splitlines()[0] == name
    assert TIP_UNPAIRED in tip and TIP_ONLINE in tip
    assert "Windows" in tip, "HĐH bằng chữ trong tooltip (L7)"
    assert "Windows" in b.accessibleDescription(), "HĐH bằng chữ trong accessibleDescription (L7)"


def test_bubble_set_view_switches_to_paired_texts(qtbot):
    from teleport.ui import texts
    from teleport.ui.discover import RadarBubble

    v = view("May-X", os="macos")
    b = RadarBubble(v)
    qtbot.addWidget(b)
    paired = view("May-X", paired=True, connected=True, os="linux")
    b.set_view(paired)
    assert b.view == paired
    assert b.property("paired") is True
    name = texts.peer_label("May-X", paired.device_id)
    assert b.accessibleName() == BUBBLE_NAME_PAIRED.format(name=name)
    assert BUBBLE_DESC_PAIRED in b.accessibleDescription()
    tip = plain_tooltip(b)
    assert TIP_PAIRED in tip and TIP_CONNECTED in tip and "Linux" in tip
    assert "macOS" not in tip


def test_bubble_tooltip_has_no_unknown_os():
    from teleport.ui.discover import RadarBubble

    b = RadarBubble(view("May-X", os="beos"))
    try:
        assert "beos" not in plain_tooltip(b).lower()
        b.set_view(view("May-X", os=None))
        assert len(plain_tooltip(b).splitlines()) == 2, "chỉ tên + trạng thái khi HĐH lạ/không có"
    finally:
        b.deleteLater()


# =================================================================================================
# T-P5 chữ máy khác
# =================================================================================================


@pytest.mark.parametrize(
    "name",
    ["<b>x</b>", "漢" * 40, "\x1b[31mDo\x07", "a&b <i>"],
    ids=["html", "cjk-dai", "ky-tu-dieu-khien", "dau-va"],
)
def test_peer_name_is_plain_text_everywhere(ui, name):
    from teleport.ui import texts

    v = view(name)
    ui.load([v, view("Ngan")])
    b = bubble_of(ui.page, v.device_id)
    shown = texts.peer_label(name, v.device_id)
    assert b.accessibleName() == BUBBLE_NAME_UNPAIRED.format(name=shown)
    assert plain_tooltip(b).splitlines()[0] == shown, "tooltip phải hiện nguyên chữ (safe_tooltip)"
    other = bubble_of(ui.page, view("Ngan").device_id)
    assert b.size() == other.size(), "cỡ bong bóng không phụ thuộc tên"


def test_bubble_size_is_fixed_and_uses_bubble_width(ui):
    from teleport.ui.discover import BUBBLE_WIDTH

    ui.load([view("A"), view("B" * 60), view("Đã-ghép", paired=True)])
    sizes = {(b.width(), b.height()) for b in ui.page.canvas.bubbles()}
    assert len(sizes) == 1, sizes
    assert next(iter(sizes))[0] == BUBBLE_WIDTH


# =================================================================================================
# T-P2 đồng bộ model
# =================================================================================================


def test_model_events_add_and_remove_bubbles(ui):
    a, b = view("May-A"), view("May-B")
    ui.load([a])
    assert ids(ui.page) == [a.device_id]
    ui.model.apply(online(b))
    settle(ui.qtbot)
    assert set(ids(ui.page)) == {a.device_id, b.device_id}
    ui.model.apply(offline(a))
    settle(ui.qtbot)
    assert ids(ui.page) == [b.device_id]
    assert_no_overlap(ui.page)


def test_bubbles_follow_discover_order(ui):
    views = [view("c"), view("A", paired=True), view("b"), view("Z", paired=True, online=False)]
    ui.load(views)
    assert ids(ui.page) == expected_order(ui.model)
    assert len(ids(ui.page)) == 3


def test_reset_keeps_geometry_of_remaining_bubbles(ui):
    views = [view(f"May-{i}") for i in range(5)] + [view("P", paired=True)]
    ui.load(views)
    before = {b.device_id: b.geometry() for b in ui.page.canvas.bubbles()}
    gone = views[2]
    ui.load([v for v in views if v is not gone] + [view("Moi")])
    after = {b.device_id: b.geometry() for b in ui.page.canvas.bubbles()}
    for did, rect in before.items():
        if did != gone.device_id:
            assert after[did] == rect, f"{did[:8]} bị dời khi reset"
    assert gone.device_id not in after
    assert_no_overlap(ui.page)


def test_newly_paired_device_moves_inward_others_stay(ui):
    views = [view(f"May-{i}") for i in range(4)]
    ui.load(views)
    target = views[1]
    old = bubble_of(ui.page, target.device_id)
    r_before = norm_radius(ui.page, old)
    others = {b.device_id: b.geometry() for b in ui.page.canvas.bubbles() if b.device_id != target.device_id}
    paired = view(target.name, paired=True, connected=True)
    ui.load([v for v in views if v is not target] + [paired])
    b = bubble_of(ui.page, target.device_id)
    assert b.property("paired") is True
    assert b.view == paired
    r_after = norm_radius(ui.page, b)
    unpaired_r = [norm_radius(ui.page, x) for x in ui.page.canvas.bubbles() if x is not b]
    assert r_after < r_before and r_after < min(unpaired_r), (r_before, r_after, unpaired_r)
    for did, rect in others.items():
        assert bubble_of(ui.page, did).geometry() == rect, "bong bóng khác không dời"
    assert_no_overlap(ui.page)


def test_resize_keeps_bubbles_inside_and_non_overlapping(ui):
    ui.load([view(f"May-{i}", paired=i % 3 == 0) for i in range(8)])
    for w, h in ((980, 660), (1300, 860), (900, 620), (980, 660)):
        ui.page.resize(w, h)
        settle(ui.qtbot)
        if ui.page.view_mode.value == "radar":
            assert len(ui.page.canvas.bubbles()) == 8
            assert_no_overlap(ui.page)


# =================================================================================================
# T-P3 bấm máy chưa ghép, T-P4 máy đã ghép (AC6)
# =================================================================================================


def test_every_activation_way_emits_one_pair_request(ui, clock):
    """M3: chuột một lần, ba kiểu bấm đúp, Enter, Space; giữa các kiểu `_now` tiến quá doubleClickInterval."""
    x = view("May-X")
    ui.load([x, view("May-P", paired=True)])
    spy = Spy(ui.page)
    activate(ui.qtbot, ui.page)
    ways = ["click", *DCLICK_WAYS, "enter", "return", "space"]
    for i, way in enumerate(ways, start=1):
        clock.advance()
        b = bubble_of(ui.page, x.device_id)
        b.setFocus(Qt.FocusReason.OtherFocusReason)
        pos = b.rect().center()
        if way == "click":
            QTest.mouseClick(b, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        elif way in DCLICK_WAYS:
            double_click(b, pos, way)
        elif way == "enter":
            QTest.keyClick(b, Qt.Key.Key_Enter)
        elif way == "return":
            QTest.keyClick(b, Qt.Key.Key_Return)
        else:
            QTest.keyClick(b, Qt.Key.Key_Space)
        settle(ui.qtbot)
        assert len(spy.pairs) == i, f"{way}: {len(spy.pairs) - (i - 1)} lần pair_requested"
        assert spy.pairs[-1] == x
    assert spy.opens == []


def test_second_click_within_interval_is_dropped_after_interval_counts(ui, clock):
    x = view("May-X")
    ui.load([x])
    spy = Spy(ui.page)
    b = bubble_of(ui.page, x.device_id)
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    settle(ui.qtbot)
    assert len(spy.pairs) == 1, "cùng máy trong doubleClickInterval: chỉ một lần"
    clock.advance()
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    settle(ui.qtbot)
    assert len(spy.pairs) == 2


def test_dedup_is_per_device(ui, clock):
    a, b = view("May-A"), view("May-B")
    ui.load([a, b])
    spy = Spy(ui.page)
    QTest.mouseClick(bubble_of(ui.page, a.device_id), Qt.MouseButton.LeftButton)
    QTest.mouseClick(bubble_of(ui.page, b.device_id), Qt.MouseButton.LeftButton)
    settle(ui.qtbot)
    assert [v.device_id for v in spy.pairs] == [a.device_id, b.device_id]


def test_auto_repeat_enter_does_not_activate(ui, clock):
    x = view("May-X")
    ui.load([x])
    spy = Spy(ui.page)
    b = bubble_of(ui.page, x.device_id)
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
        key_event(b, key, auto_repeat=True)
    settle(ui.qtbot)
    assert spy.pairs == []


def test_double_click_on_bubble_is_one_clicked(ui):
    """Mục 2.5: `mouseDoubleClickEvent` nhận rồi bỏ qua (chuỗi không có lần nhấn thứ hai = một `clicked`)."""
    x = view("May-X")
    ui.load([x])
    b = bubble_of(ui.page, x.device_id)
    clicks: list[bool] = []
    b.clicked.connect(lambda *_: clicks.append(True))
    double_click(b, b.rect().center(), "manual_dblclick_without_second_press")
    assert len(clicks) == 1


def test_signal_carries_latest_view(ui, clock):
    import dataclasses

    x = view("May-X")
    ui.load([x])
    spy = Spy(ui.page)
    b = bubble_of(ui.page, x.device_id)
    newer = dataclasses.replace(x, name="May-X-moi", addresses=("192.168.1.77",), port=50000)
    ui.model.apply(online(newer))  # đổi ngay trước khi bấm, chưa cho vòng sự kiện chạy
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    settle(ui.qtbot)
    assert spy.pairs == [newer]


def test_device_gone_from_model_is_not_activated(ui, clock):
    x = view("May-X")
    ui.load([x])
    spy = Spy(ui.page)
    b = bubble_of(ui.page, x.device_id)
    ui.model.apply(offline(x))  # máy vừa rời mạng, bong bóng chưa kịp bỏ
    QTest.mouseClick(b, Qt.MouseButton.LeftButton)
    settle(ui.qtbot)
    assert spy.pairs == [] and spy.opens == []


@pytest.mark.parametrize("way", ["click", *DCLICK_WAYS, "enter", "space"])
def test_paired_device_opens_and_never_pairs(ui, clock, way):
    """T-P4: máy đã ghép → đúng một `open_device_requested(id)`, không `pair_requested`."""
    p = view("May-P", paired=True, online=False, connected=True)
    ui.load([p, view("May-U")])
    spy = Spy(ui.page)
    b = bubble_of(ui.page, p.device_id)
    pos = b.rect().center()
    if way == "click":
        QTest.mouseClick(b, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    elif way in DCLICK_WAYS:
        double_click(b, pos, way)
    elif way == "enter":
        QTest.keyClick(b, Qt.Key.Key_Return)
    else:
        QTest.keyClick(b, Qt.Key.Key_Space)
    settle(ui.qtbot)
    assert spy.opens == [p.device_id]
    assert spy.pairs == []


# =================================================================================================
# T-P6 Esc (AC7, H5)
# =================================================================================================


def test_escape_clears_text_then_goes_back_to_discover_button(win, qtbot):
    from teleport.ui.main_window import Page

    open_discover(qtbot, win)
    page = win.discover
    edit = page.address_edit
    assert QApplication.focusWidget() is edit, "không có máy chưa ghép: tiêu điểm vào ô nhập (mục 2.8)"
    QTest.keyClicks(edit, "192.168")
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    settle(qtbot)
    assert edit.text() == ""
    assert win.current_page is Page.DISCOVER, "Esc lần đầu chỉ xóa chữ"
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    settle(qtbot)
    assert win.current_page is Page.HOME
    assert QApplication.focusWidget() is win.discover_button


def test_escape_also_hides_address_error(win, qtbot):
    from teleport.ui.main_window import Page

    open_discover(qtbot, win)
    page = win.discover
    QTest.keyClicks(page.address_edit, "abc")
    QTest.keyClick(page.address_edit, Qt.Key.Key_Return)
    assert not page.info_bar.isHidden()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    settle(qtbot)
    assert page.address_edit.text() == ""
    assert page.info_bar.isHidden(), "Esc xóa cả lỗi địa chỉ đang hiện"
    assert win.current_page is Page.DISCOVER


def test_escape_on_bubble_goes_back(win, qtbot):
    from teleport.ui.main_window import Page

    win.devices.reset([view("May-X")])
    open_discover(qtbot, win)
    assert isinstance(QApplication.focusWidget(), type(win.discover.canvas.bubbles()[0]))
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    settle(qtbot)
    assert win.current_page is Page.HOME


def test_shortcut_override_only_accepted_when_field_has_text(ui):
    edit = ui.page.address_edit

    def override(modifiers=Qt.KeyboardModifier.NoModifier) -> bool:
        ev = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_Escape, modifiers)
        ev.ignore()
        QApplication.sendEvent(edit, ev)
        return ev.isAccepted()

    assert not override(), "ô rỗng: Esc phải tới _back_action của cửa sổ"
    edit.setText("1")
    assert override()
    assert not override(Qt.KeyboardModifier.ShiftModifier), "Esc có phím bổ trợ không bị ô nhập giữ"


# =================================================================================================
# T-P7 nhập IP
# =================================================================================================


def test_submit_button_enabled_only_with_text(ui):
    page = ui.page
    assert not page.address_submit.isEnabled()
    page.address_edit.setText("   ")
    assert not page.address_submit.isEnabled()
    page.address_edit.setText(" 1 ")
    assert page.address_submit.isEnabled()
    page.address_edit.clear()
    assert not page.address_submit.isEnabled()


def test_invalid_address_shows_error_without_signal_then_typing_hides_it(ui):
    from teleport.ui.radar import invalid_address_text
    from teleport.ui.widgets import InfoLevel

    page = ui.page
    spy = Spy(page)
    activate(ui.qtbot, page)
    edit = page.address_edit
    edit.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClicks(edit, "abc")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    bar = page.info_bar
    assert not bar.isHidden()
    assert bar.level is InfoLevel.ERROR
    want = invalid_address_text("abc")
    assert want in (bar.title, bar.text)
    assert "không hợp lệ:" not in bar.title + bar.text, "không hiện str(e) của parse_manual_address"
    assert spy.addresses == []
    assert QApplication.focusWidget() is edit, "giữ tiêu điểm ở ô nhập"
    assert edit.selectedText() == "abc", "chọn hết chữ"
    QTest.keyClicks(edit, "d")
    assert bar.isHidden(), "gõ chữ thì ẩn lỗi địa chỉ"


def test_valid_address_emits_and_clears_field(ui):
    from teleport.app.devices import parse_manual_address

    page = ui.page
    spy = Spy(page)
    QTest.keyClicks(page.address_edit, "192.168.1.5:47474")
    QTest.keyClick(page.address_edit, Qt.Key.Key_Return)
    assert spy.addresses == [("192.168.1.5", 47474)]
    assert page.address_edit.text() == ""
    assert page.info_bar.isHidden()
    page.address_edit.setText("10.0.0.7")
    page.address_submit.click()
    assert spy.addresses[-1] == parse_manual_address("10.0.0.7")
    assert page.isVisible(), "trang vẫn mở"


def test_submit_address_return_values(ui):
    page = ui.page
    spy = Spy(page)
    assert page.submit_address() is False  # rỗng
    assert page.info_bar.isHidden()
    page.address_edit.setText("999.1.1.1")
    assert page.submit_address() is False
    page.address_edit.setText("192.168.1.5")
    assert page.submit_address() is True
    assert len(spy.addresses) == 1


def test_long_input_is_capped_and_error_text_is_safe(ui):
    from teleport.ui.radar import invalid_address_text

    page = ui.page
    page.address_edit.setText("<b>" + "9" * 500)
    assert len(page.address_edit.text()) == 64
    assert page.submit_address() is False
    want = invalid_address_text(page.address_edit.text())
    assert want in (page.info_bar.title, page.info_bar.text)


def test_success_notice_is_not_hidden_by_typing(ui):
    from teleport.ui.widgets import InfoLevel

    page = ui.page
    page.show_notice("x")
    assert not page.info_bar.isHidden()
    assert page.info_bar.level is InfoLevel.SUCCESS
    assert "x" in (page.info_bar.title, page.info_bar.text)
    QTest.keyClicks(page.address_edit, "1")
    assert not page.info_bar.isHidden(), "thông báo SUCCESS không ẩn khi gõ"


# =================================================================================================
# T-P8 Tab và phím mũi tên
# =================================================================================================


def test_tab_order_reaches_every_bubble_in_discover_order(ui):
    views = [view("c"), view("A", paired=True), view("b"), view("D")]
    ui.load(views)
    page = ui.page
    activate(ui.qtbot, page)
    page.header.back_button.setFocus(Qt.FocusReason.TabFocusReason)
    assert press_tab()[-1] is page.address_edit
    page.address_edit.setText("1")  # address_submit chỉ bật khi có chữ
    seen = press_tab(3 + len(views))
    want = [page.address_submit, page.hint_label, page.view_button, *page.canvas.bubbles()]
    assert seen == want
    assert [b.device_id for b in page.canvas.bubbles()] == expected_order(ui.model)


def test_tab_order_is_rebuilt_after_sync(ui):
    a, c = view("a"), view("c")
    ui.load([a, c])
    page = ui.page
    activate(ui.qtbot, page)
    ui.model.apply(online(view("b")))
    settle(ui.qtbot)
    page.view_button.setFocus(Qt.FocusReason.TabFocusReason)
    seen = [w.device_id for w in press_tab(3)]
    assert seen == expected_order(ui.model)


def test_tab_reaches_wait_button_and_empty_label_when_shown(ui):
    page = ui.page
    page.set_wait_pairing_available(True)
    activate(ui.qtbot, page)
    page.address_edit.setFocus(Qt.FocusReason.TabFocusReason)  # rỗng: address_submit tắt, bị bỏ qua
    seen = press_tab(4)
    assert seen == [page.hint_label, page.view_button, page.wait_button, page.empty_label]


def test_tab_goes_through_info_bar_before_hint(ui):
    """M9: address_submit → info_bar (chữ, nút) → hint_label."""
    page = ui.page
    ui.load([view("May-1")])
    page.show_notice("Đã ghép đôi.")
    activate(ui.qtbot, page)
    page.address_edit.setText("1")
    page.address_submit.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(6)
    inside = [w for w in seen if page.info_bar.isAncestorOf(w)]
    assert inside, "Tab phải vào info_bar khi nó hiện"
    assert page.hint_label in seen
    assert seen.index(page.hint_label) > max(seen.index(w) for w in inside)
    assert seen[0] is inside[0], "ngay sau address_submit là info_bar"


def test_arrow_keys_move_between_bubbles_without_wrapping(ui):
    ui.load([view(n) for n in ("a", "b", "c", "d")])
    page = ui.page
    activate(ui.qtbot, page)
    bubbles = page.canvas.bubbles()
    bubbles[0].setFocus(Qt.FocusReason.TabFocusReason)
    steps = [
        (Qt.Key.Key_Left, 0),
        (Qt.Key.Key_Up, 0),
        (Qt.Key.Key_Right, 1),
        (Qt.Key.Key_Down, 2),
        (Qt.Key.Key_Left, 1),
        (Qt.Key.Key_End, 3),
        (Qt.Key.Key_Right, 3),
        (Qt.Key.Key_Down, 3),
        (Qt.Key.Key_Up, 2),
        (Qt.Key.Key_Home, 0),
    ]
    for key, index in steps:
        QTest.keyClick(QApplication.focusWidget(), key)
        assert QApplication.focusWidget() is bubbles[index], f"{key}: muốn bong bóng {index}"


def test_list_mode_tab_skips_bubbles(ui):
    from teleport.ui.discover import RadarBubble

    ui.load([view(n) for n in ("a", "b", "c")])
    page = ui.page
    page.set_view_preference("list")
    settle(ui.qtbot)
    activate(ui.qtbot, page)
    page.address_edit.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(10)
    assert not any(isinstance(w, RadarBubble) for w in seen)
    assert page.list_view in seen


def test_removing_focused_bubble_moves_focus_next_then_previous_then_address(ui):
    a, b, c = view("a"), view("b"), view("c")
    ui.load([a, b, c])
    page = ui.page
    activate(ui.qtbot, page)
    bubble_of(page, b.device_id).setFocus(Qt.FocusReason.OtherFocusReason)
    ui.model.apply(offline(b))
    settle(ui.qtbot)
    focus = QApplication.focusWidget()
    assert focus is not None and is_alive(focus)
    assert focus is bubble_of(page, c.device_id), "bỏ bong bóng có tiêu điểm → sang bong bóng kế"
    ui.model.apply(offline(c))
    settle(ui.qtbot)
    assert QApplication.focusWidget() is bubble_of(page, a.device_id), "không có kế → bong bóng trước"
    ui.model.apply(offline(a))
    settle(ui.qtbot)
    assert QApplication.focusWidget() is page.address_edit, "không còn bong bóng → ô nhập"


def test_switching_to_list_keeps_focus_on_same_device(ui):
    """L4: tiêu điểm trên bong bóng mà tự sang danh sách → `list_view`, đúng hàng máy đó."""
    from teleport.ui.radar import DEVICE_ID_ROLE

    views = [view(f"May-{i}") for i in range(8)]
    ui.load(views)
    page = ui.page
    activate(ui.qtbot, page)
    target = views[5]
    bubble_of(page, target.device_id).setFocus(Qt.FocusReason.OtherFocusReason)
    ui.model.apply(online(view("May-9")))
    settle(ui.qtbot)
    assert page.view_mode.value == "list"
    assert QApplication.focusWidget() is page.list_view
    assert page.list_view.currentIndex().data(DEVICE_ID_ROLE) == target.device_id


# =================================================================================================
# T-P9 tiêu điểm khi mở
# =================================================================================================


def test_focus_on_open_goes_to_first_unpaired_bubble(ui):
    views = [view("A", paired=True), view("c"), view("b")]
    ui.load(views)
    page = ui.page
    activate(ui.qtbot, page)
    page.setFocus(Qt.FocusReason.OtherFocusReason)
    assert QApplication.focusWidget() is bubble_of(page, view("b").device_id)


def test_focus_on_open_with_only_paired_goes_to_address(ui):
    ui.load([view("A", paired=True), view("B", paired=True, connected=True)])
    page = ui.page
    activate(ui.qtbot, page)
    page.setFocus(Qt.FocusReason.OtherFocusReason)
    assert QApplication.focusWidget() is page.address_edit


def test_focus_on_open_in_list_mode_goes_to_first_row(ui):
    ui.load([view("b"), view("a")])
    page = ui.page
    page.set_view_preference("list")
    settle(ui.qtbot)
    activate(ui.qtbot, page)
    page.setFocus(Qt.FocusReason.OtherFocusReason)
    assert QApplication.focusWidget() is page.list_view
    assert page.list_view.currentIndex().row() == 0


def test_focus_proxy_follows_sync(ui):
    page = ui.page
    ui.load([view("A", paired=True)])
    assert page.focusProxy() is page.address_edit
    ui.model.apply(online(view("b")))
    settle(ui.qtbot)
    assert page.focusProxy() is bubble_of(page, view("b").device_id)


# =================================================================================================
# T-P10 dạng hiển thị (thứ tự luật M4)
# =================================================================================================


def test_view_button_toggles_preference_and_emits_once(ui):
    from teleport.ui.discover import ListReason, ViewMode

    page = ui.page
    ui.load([view("a"), view("b")])
    spy = Spy(page)
    assert page.view_mode is ViewMode.RADAR, "mặc định là radar (L8)"
    assert page.list_reason is ListReason.NONE
    assert page.view_preference is None
    assert page.view_button.isVisibleTo(page) and page.view_button.text().replace("&", "") == TO_LIST
    assert not page.mode_reason_label.isVisibleTo(page)
    page.view_button.click()
    settle(ui.qtbot)
    assert (page.view_mode, page.list_reason) == (ViewMode.LIST, ListReason.PREFERENCE)
    assert spy.prefs == ["list"] and page.view_preference == "list"
    assert page.view_button.text().replace("&", "") == TO_RADAR
    assert page.view_button.isVisibleTo(page)
    page.view_button.click()
    settle(ui.qtbot)
    assert page.view_mode is ViewMode.RADAR
    assert spy.prefs == ["list", "radar"] and page.view_preference == "radar"


def test_set_view_preference_is_silent_and_ignores_unknown(ui):
    from teleport.ui.discover import ViewMode

    page = ui.page
    ui.load([view("a")])
    spy = Spy(page)
    page.set_view_preference("list")
    settle(ui.qtbot)
    assert page.view_preference == "list" and page.view_mode is ViewMode.LIST
    for bad in ("abc", "Radar", "", 1):
        page.set_view_preference(bad)
        assert page.view_preference == "list", f"{bad!r} phải bị bỏ qua"
    page.set_view_preference(None)
    settle(ui.qtbot)
    assert page.view_preference is None and page.view_mode is ViewMode.RADAR
    assert spy.prefs == []


def test_more_than_eight_devices_forces_list_and_back(ui):
    """AC5: 9 máy → LIST (TOO_MANY), không bong bóng, list_view 9 hàng; về 8 → RADAR."""
    from teleport.ui.discover import ListReason, RadarBubble, ViewMode

    page = ui.page
    nine = [view(f"May-{i}", paired=i < 3) for i in range(9)]
    ui.load(nine)
    assert (page.view_mode, page.list_reason) == (ViewMode.LIST, ListReason.TOO_MANY)
    assert page.canvas.bubbles() == []
    settle(ui.qtbot, 50)  # deleteLater
    assert page.canvas.findChildren(RadarBubble) == []
    assert page.list_view.model().rowCount() == 9
    assert not page.view_button.isVisibleTo(page)
    assert page.mode_reason_label.isVisibleTo(page)
    assert page.mode_reason_label.text() == TOO_MANY.format(n=9)
    assert page.mode_reason_label.property("tone") == "muted"
    ui.load(nine[:8])
    assert page.view_mode is ViewMode.RADAR
    assert len(page.canvas.bubbles()) == 8
    assert page.view_button.isVisibleTo(page)
    assert not page.mode_reason_label.isVisibleTo(page)
    assert_no_overlap(page)


def test_back_to_radar_fits_when_button_is_taller_than_reason_label(ui):
    """Nút cao hơn câu lý do (macOS/Linux): về dạng vòng tròn, bong bóng vẫn nằm trong khung ngay."""
    from teleport.ui.discover import ViewMode

    page = ui.page
    page.view_button.setStyleSheet("padding: 14px")  # giả nút cao hơn nhãn như trên macOS/Linux
    nine = [view(f"May-{i}", paired=i < 3) for i in range(9)]
    ui.load(nine)
    ui.load(nine[:8])
    assert page.view_mode is ViewMode.RADAR
    assert_no_overlap(page)


def test_count_uses_filtered_devices(ui):
    from teleport.ui.discover import ViewMode

    views = [view(f"May-{i}") for i in range(8)] + [
        view(f"Cu-{i}", paired=True, online=False) for i in range(3)
    ]
    ui.load(views)
    assert ui.page.view_mode is ViewMode.RADAR, "máy đã ghép ngoại tuyến không tính vào n"


def test_too_many_wins_over_preference_and_preference_survives(ui):
    """M4: TOO_MANY trước PREFERENCE; bị ép sang danh sách thì ẩn view_button; lựa chọn giữ nguyên."""
    from teleport.ui.discover import ListReason, ViewMode

    page = ui.page
    page.set_view_preference("list")
    nine = [view(f"May-{i}") for i in range(9)]
    ui.load(nine)
    assert page.list_reason is ListReason.TOO_MANY
    assert not page.view_button.isVisibleTo(page)
    assert page.view_preference == "list"
    ui.load(nine[:4])
    assert (page.view_mode, page.list_reason) == (ViewMode.LIST, ListReason.PREFERENCE)
    page.set_view_preference("radar")
    ui.load(nine)
    assert page.list_reason is ListReason.TOO_MANY and page.view_preference == "radar"
    ui.load(nine[:4])
    assert page.view_mode is ViewMode.RADAR


def test_small_area_falls_back_to_list_no_room_and_back(qtbot):
    """NO_ROOM đo theo cỡ stack (H4); rộng ra thì tự về dạng đã chọn. Trang là con (không bị kẹp min size)."""
    from teleport.ui.discover import DiscoverPage, ListReason, ViewMode
    from teleport.ui.radar import DeviceListModel

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1000, 700)
    model = DeviceListModel(host)
    page = DiscoverPage(model, host)
    page.setGeometry(0, 0, 980, 660)
    host.show()
    qtbot.waitExposed(host)
    model.reset([view("a"), view("b"), view("c", paired=True)])
    settle(qtbot)
    assert page.view_mode is ViewMode.RADAR
    page.setGeometry(0, 0, 420, 250)
    settle(qtbot)
    assert (page.view_mode, page.list_reason) == (ViewMode.LIST, ListReason.NO_ROOM)
    assert not page.view_button.isVisibleTo(page)
    assert page.mode_reason_label.isVisibleTo(page)
    assert page.mode_reason_label.text() == NO_ROOM
    assert page.view_preference is None
    page.setGeometry(0, 0, 980, 660)
    settle(qtbot)
    assert page.view_mode is ViewMode.RADAR
    assert len(page.canvas.bubbles()) == 3
    assert_no_overlap(page)


@pytest.mark.parametrize("paired_count", range(9))
def test_capacity_eight_devices_at_default_window_size(win, qtbot, paired_count):
    """AC4: 980x660, 8 máy, số máy đã ghép 0–8 → RADAR, 8 bong bóng, không chồng (info_bar ẩn)."""
    from teleport.ui.discover import ViewMode

    win.devices.reset([view(f"May-{i}", paired=i < paired_count) for i in range(8)])
    open_discover(qtbot, win)
    page = win.discover
    assert page.info_bar.isHidden()
    assert page.view_mode is ViewMode.RADAR, page.list_reason
    assert len(page.canvas.bubbles()) == 8
    assert all(b.isVisibleTo(page) for b in page.canvas.bubbles())
    assert_no_overlap(page)


@pytest.mark.parametrize("count", [1, 2, 3])
def test_capacity_three_devices_at_minimum_window_size(win, qtbot, count):
    """AC4: 720x460 với ≤ 3 máy → RADAR."""
    from teleport.ui.discover import ViewMode
    from teleport.ui.main_window import MIN_SIZE

    win.resize(MIN_SIZE)
    settle(qtbot)
    win.devices.reset([view(f"May-{i}", paired=i == 0) for i in range(count)])
    open_discover(qtbot, win)
    assert win.discover.view_mode is ViewMode.RADAR, win.discover.list_reason
    assert_no_overlap(win.discover)


def test_eight_devices_at_minimum_window_size_is_radar_or_no_room(win, qtbot):
    from teleport.ui.discover import ListReason, ViewMode
    from teleport.ui.main_window import MIN_SIZE

    win.resize(MIN_SIZE)
    settle(qtbot)
    win.devices.reset([view(f"May-{i}") for i in range(8)])
    open_discover(qtbot, win)
    page = win.discover
    if page.view_mode is ViewMode.RADAR:
        assert len(page.canvas.bubbles()) == 8
        assert_no_overlap(page)
    else:
        assert page.list_reason is ListReason.NO_ROOM


# =================================================================================================
# T-P11 dạng danh sách
# =================================================================================================


def _list_ids(page) -> list[str]:
    from teleport.ui.radar import DEVICE_ID_ROLE

    m = page.list_view.model()
    return [m.index(r, 0).data(DEVICE_ID_ROLE) for r in range(m.rowCount())]


def test_list_proxy_filters_and_sorts_like_discover_devices(ui):
    from PySide6.QtCore import QSortFilterProxyModel
    from PySide6.QtWidgets import QAbstractItemView

    from teleport.ui.discover import DiscoverProxyModel

    page = ui.page
    page.set_view_preference("list")
    views = [view("c"), view("A", paired=True), view("Z", paired=True, online=False), view("b")]
    ui.load(views)
    proxy = page.list_view.model()
    assert isinstance(proxy, DiscoverProxyModel) and isinstance(proxy, QSortFilterProxyModel)
    assert proxy.sourceModel() is ui.model, "dùng chung model, không bản sao"
    assert proxy.dynamicSortFilter()
    assert _list_ids(page) == expected_order(ui.model)
    ui.model.apply(online(view("a0")))
    settle(ui.qtbot)
    assert _list_ids(page) == expected_order(ui.model)
    lv = page.list_view
    assert lv.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    assert lv.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers


def test_list_rows_reuse_model_texts(ui):
    page = ui.page
    page.set_view_preference("list")
    ui.load([view("<b>x</b>"), view("P", paired=True, connected=True)])
    proxy = page.list_view.model()
    for r in range(proxy.rowCount()):
        source = proxy.mapToSource(proxy.index(r, 0))
        for role in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.AccessibleTextRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            assert proxy.index(r, 0).data(role) == source.data(role)


def _row_of(page, device_id: str) -> int:
    return _list_ids(page).index(device_id)


def test_enter_in_list_pairs_unpaired_and_opens_paired(ui, clock):
    page = ui.page
    page.set_view_preference("list")
    u, p = view("May-U"), view("May-P", paired=True)
    ui.load([u, p])
    spy = Spy(page)
    lv = page.list_view
    lv.setCurrentIndex(lv.model().index(_row_of(page, u.device_id), 0))
    QTest.keyClick(lv, Qt.Key.Key_Return)
    settle(ui.qtbot)
    assert spy.pairs == [u] and spy.opens == []
    clock.advance()
    lv.setCurrentIndex(lv.model().index(_row_of(page, p.device_id), 0))
    QTest.keyClick(lv, Qt.Key.Key_Enter)
    settle(ui.qtbot)
    assert spy.opens == [p.device_id] and spy.pairs == [u]
    clock.advance()
    key_event(lv, Qt.Key.Key_Return, auto_repeat=True)
    settle(ui.qtbot)
    assert spy.opens == [p.device_id], "Enter tự lặp không kích hoạt"


@pytest.mark.parametrize("way", ["click", *DCLICK_WAYS])
def test_click_or_double_click_row_pairs_once(ui, way):
    page = ui.page
    page.set_view_preference("list")
    u = view("May-U")
    ui.load([u, view("May-P", paired=True)])
    spy = Spy(page)
    lv = page.list_view
    pos = lv.visualRect(lv.model().index(_row_of(page, u.device_id), 0)).center()
    if way == "click":
        QTest.mouseClick(lv.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    else:
        double_click(lv.viewport(), pos, way)
    settle(ui.qtbot, 60)
    assert spy.pairs == [u], f"{way}: {len(spy.pairs)} lần"
    assert spy.opens == []


def test_list_single_click_activation_style_still_once(ui):
    """M8: không nối `activated` (style kích hoạt khi bấm một lần không làm phát hai lần)."""
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class SingleClickActivates(QProxyStyle):
        def styleHint(self, hint, option=None, widget=None, return_data=None):
            if hint == QStyle.StyleHint.SH_ItemView_ActivateItemOnSingleClick:
                return 1
            return super().styleHint(hint, option, widget, return_data)

    page = ui.page
    page.set_view_preference("list")
    u = view("May-U")
    ui.load([u])
    style = SingleClickActivates()
    style.setParent(page)
    page.list_view.setStyle(style)
    spy = Spy(page)
    lv = page.list_view
    pos = lv.visualRect(lv.model().index(0, 0)).center()
    for way in DCLICK_WAYS:
        double_click(lv.viewport(), pos, way)
    settle(ui.qtbot, 60)
    assert len(spy.pairs) == 1


# =================================================================================================
# T-P12 ngập mDNS (M10)
# =================================================================================================


def test_three_hundred_devices_use_list_without_bubble_widgets(ui):
    from teleport.ui.discover import ListReason, RadarBubble, ViewMode

    views = [view(f"La-{i:03d}") for i in range(300)]
    t0 = time.perf_counter()
    ui.model.reset(views)
    QApplication.processEvents()
    elapsed = time.perf_counter() - t0
    settle(ui.qtbot)
    page = ui.page
    assert (page.view_mode, page.list_reason) == (ViewMode.LIST, ListReason.TOO_MANY)
    assert page.canvas.bubbles() == []
    assert page.canvas.findChildren(RadarBubble) == []
    assert page.list_view.model().rowCount() == 300
    assert elapsed < 2.0, f"reset 300 máy mất {elapsed:.2f} s"
    assert page.mode_reason_label.text() == TOO_MANY.format(n=300)


# =================================================================================================
# T-P13 vòng sóng (AC8)
# =================================================================================================


@pytest.fixture
def waves(real_motion, monkeypatch):
    """Vòng sóng chạy thật qua `motion.Loop` (spec G6 mục 6 A1, A2): `real_motion`, vá lại
    `animations_enabled` theo `state["enabled"]`, và nới `motion.MAX_LOOP_MS` lên 60 s để tổng 30 s của
    test không bị trần 5 s cắt (tổng thật ≤ `MAX_LOOP_MS` kiểm ở `test_illustrations.py`)."""
    from teleport.ui import discover, motion

    state = {"enabled": True}
    monkeypatch.setattr(motion, "animations_enabled", lambda: state["enabled"])
    monkeypatch.setattr(motion, "MAX_LOOP_MS", 60_000)
    monkeypatch.setattr(discover, "WAVE_CYCLE_MS", 400)
    monkeypatch.setattr(discover, "WAVE_TOTAL_MS", 30_000)

    def set_total(cycle: int, total: int) -> None:
        monkeypatch.setattr(discover, "WAVE_CYCLE_MS", cycle)
        monkeypatch.setattr(discover, "WAVE_TOTAL_MS", total)

    return SimpleNamespace(state=state, set_total=set_total)


def test_waves_run_on_open_and_stop_on_minimize_back_and_list(win, qtbot, waves):
    win.devices.reset([view("May-1")])
    open_discover(qtbot, win)
    canvas = win.discover.canvas
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)
    win.showMinimized()
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=2000)
    win.showNormal()
    activate(qtbot, win)
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)
    win.go_back()
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=2000)
    open_discover(qtbot, win)
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)
    win.discover.set_view_preference("list")
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=2000)


def test_waves_stop_when_window_hidden_to_tray(win, qtbot, waves):
    open_discover(qtbot, win)
    canvas = win.discover.canvas
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)
    win.hide()
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=2000)


def test_waves_stop_by_themselves_and_restart_when_list_empties_or_fills(win, qtbot, waves):
    waves.set_total(40, 80)
    model = win.devices
    model.reset([view("May-1")])
    open_discover(qtbot, win)
    canvas = win.discover.canvas
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=3000)  # hết WAVE_TOTAL_MS
    waves.set_total(400, 30_000)  # M7: đọc lại mỗi lần start_waves()
    model.reset([])
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)
    canvas.stop_waves()
    model.reset([view("May-2")])
    qtbot.waitUntil(lambda: canvas.wave_running, timeout=2000)


def test_waves_never_run_when_system_disables_animations(win, qtbot, waves):
    waves.state["enabled"] = False
    canvas = win.discover.canvas
    seen: list[bool] = []
    open_discover(qtbot, win)
    for step in range(6):
        seen.append(canvas.wave_running)
        win.devices.reset([view("May-1")] if step % 2 == 0 else [])
        settle(qtbot)
        seen.append(canvas.wave_running)
    win.showMinimized()
    settle(qtbot)
    win.showNormal()
    settle(qtbot)
    seen.append(canvas.wave_running)
    assert not any(seen)


def test_start_and_stop_waves_are_idempotent(ui, waves):
    canvas = ui.page.canvas
    canvas.start_waves()
    canvas.start_waves()
    assert canvas.wave_running
    canvas.stop_waves()
    canvas.stop_waves()
    assert not canvas.wave_running


def test_waves_run_through_motion_loop_registry(ui, waves):
    """Spec G6 tiêu chí 9: sóng là một `Loop` trong sổ đăng ký của `motion`."""
    from teleport.ui import motion

    canvas = ui.page.canvas
    canvas.start_waves()
    assert canvas.wave_running
    assert motion.running_count() >= 1


def test_finish_all_stops_waves(ui, waves):
    from teleport.ui import motion

    canvas = ui.page.canvas
    canvas.start_waves()
    assert canvas.wave_running
    motion.finish_all()
    assert not canvas.wave_running


def test_waves_do_not_run_in_instant_mode(ui, waves):
    """`Loop` theo `should_animate()`: chế độ tức thì của test (không chỉ `animations_enabled`)."""
    from teleport.ui import motion

    assert waves.state["enabled"]
    motion._force_instant(True)
    canvas = ui.page.canvas
    canvas.start_waves()
    assert not canvas.wave_running


@pytest.mark.parametrize("how", ["page_hidden", "list_view"])
def test_start_waves_while_canvas_hidden_does_not_run(ui, waves, how):
    """Spec G6 A3: `start_waves()` khi canvas không hiện thì không chạy."""
    page = ui.page
    canvas = page.canvas
    canvas.stop_waves()
    if how == "page_hidden":
        page.hide()
    else:
        page.set_view_preference("list")
    settle(ui.qtbot)
    assert not canvas.isVisible(), "tiền đề: canvas đang ẩn"
    canvas.start_waves()
    assert not canvas.wave_running


def test_wave_restart_creates_fresh_run_with_new_total(ui, waves, qtbot):
    """Mục 6 A1: mỗi `start_waves()` đọc lại `WAVE_TOTAL_MS`: vòng cũ dài dừng, vòng mới ngắn tự hết."""
    canvas = ui.page.canvas
    canvas.start_waves()
    assert canvas.wave_running
    canvas.stop_waves()
    waves.set_total(40, 120)
    canvas.start_waves()
    assert canvas.wave_running
    qtbot.waitUntil(lambda: not canvas.wave_running, timeout=3000)


def test_hidden_page_clears_info_bar(win, qtbot):
    """M9: trang bị ẩn không tự phát → `info_bar.clear()`."""
    open_discover(qtbot, win)
    win.discover.show_notice("x")
    win.go_back()
    settle(qtbot)
    open_discover(qtbot, win)
    assert win.discover.info_bar.isHidden()


def test_notice_while_page_hidden_is_not_shown_on_open(win, qtbot):
    """Câu báo tới lúc đang ở HOME (vd. hủy ghép đôi từ radar) không còn khi mở trang sau đó."""
    open_discover(qtbot, win)
    win.go_back()
    settle(qtbot)
    win.discover.show_notice("Đã hủy ghép đôi.")
    open_discover(qtbot, win)
    assert win.discover.info_bar.isHidden()


def test_maximize_does_not_restart_waves(win, qtbot, real_motion):
    """Sóng chỉ chạy lại khi cửa sổ thôi thu nhỏ, không khi phóng to (spec G6 mục 7: `real_motion`, sóng
    chạy thật sau khi mở rồi mới dừng)."""
    open_discover(qtbot, win)
    qtbot.waitUntil(lambda: win.discover.canvas.wave_running, timeout=2000)
    win.discover.canvas.stop_waves()
    assert not win.discover.canvas.wave_running
    win.setWindowState(Qt.WindowState.WindowMaximized)
    settle(qtbot)
    assert not win.discover.canvas.wave_running


# =================================================================================================
# Minh họa dạng danh sách rỗng (spec G6 mục 3, mục 6 A6; tiêu chí 6, 8)
# =================================================================================================


def test_empty_illustration_is_no_devices_in_list_viewport(ui):
    from teleport.ui.illustrations import Illustration, Scene

    page = ui.page
    ill = page.empty_illustration
    assert isinstance(ill, Illustration)
    assert ill.scene is Scene.NO_DEVICES
    assert ill.parent() is page.list_view.viewport()
    assert ill.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert ill.accessibleName() == ""


def test_empty_illustration_only_in_list_view_with_no_device(ui):
    from teleport.ui.discover import ViewMode

    page = ui.page
    ui.load([])
    assert page.view_mode is ViewMode.RADAR
    assert not page.empty_illustration.isVisibleTo(page), "radar trống đã là minh họa"
    page.set_view_preference("list")
    settle(ui.qtbot)
    assert page.view_mode is ViewMode.LIST
    assert page.empty_illustration.isVisibleTo(page)
    assert page.empty_label.isVisibleTo(page), "empty_label giữ nguyên"
    ui.load([view("May-1")])
    assert not page.empty_illustration.isVisibleTo(page)
    ui.load([])
    assert page.empty_illustration.isVisibleTo(page)
    page.set_view_preference("radar")
    settle(ui.qtbot)
    assert not page.empty_illustration.isVisibleTo(page)


def test_empty_illustration_centered_in_viewport_after_resize(ui):
    page = ui.page
    page.set_view_preference("list")
    ui.load([])
    viewport = page.list_view.viewport()
    for width, height in ((980, 660), (760, 520), (1200, 800)):
        page.resize(width, height)
        settle(ui.qtbot)
        g = page.empty_illustration.geometry()
        assert viewport.rect().contains(g), (g, viewport.rect())
        assert abs(g.center().x() - viewport.width() / 2) <= 2, (
            f"{width}x{height}: {g} trong {viewport.size()}"
        )


def test_empty_illustration_not_in_tab_chain(ui):
    page = ui.page
    page.set_view_preference("list")
    page.set_wait_pairing_available(True)
    ui.load([])
    activate(ui.qtbot, page)
    assert page.empty_illustration.isVisibleTo(page)
    page.address_edit.setFocus(Qt.FocusReason.TabFocusReason)
    seen = press_tab(12)
    assert page.empty_illustration not in seen
    assert page.empty_label in seen, "đối chứng: Tab vẫn tới empty_label"


# =================================================================================================
# T-P14 dịch
# =================================================================================================


def test_language_change_retranslates_page_and_bubbles(ui):
    page = ui.page
    ui.load([view("May-X")])
    translator = PrefixTranslator()
    QCoreApplication.installTranslator(translator)
    try:
        ui.qtbot.waitUntil(lambda: page.header.title_label.text().startswith(PREFIX), timeout=3000)
        settle(ui.qtbot)
        b = page.canvas.bubbles()[0]
        assert page.address_edit.placeholderText().startswith(PREFIX)
        assert PREFIX in page.view_button.text()
        assert PREFIX in page.hint_label.text()
        assert PREFIX in b.accessibleName()
        assert PREFIX in b.accessibleDescription()
        assert PREFIX in plain_tooltip(b), "dòng trạng thái của bong bóng phải dịch"
    finally:
        QCoreApplication.removeTranslator(translator)
    ui.qtbot.waitUntil(lambda: page.header.title_label.text() == TITLE, timeout=3000)
    assert PREFIX not in page.canvas.bubbles()[0].accessibleName()
