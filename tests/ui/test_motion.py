"""Test `ui/motion.py`: nền tảng chuyển động (spec-g1 mục 2, 3 và 9; mvp N3, N12).

Viết từ spec, không từ code. Mọi test ở chế độ tức thì (autouse `motion_instant`) trừ khi xin
`real_motion`. Chỉ kiểm giá trị cuối (không giá trị giữa chừng): token ngắn `SHORT` và
`qtbot.waitUntil` với hạn rộng; token dài `LONG` cho `finish_all` và các ca “đang chạy”.
"""

from __future__ import annotations

import dataclasses
import shutil
import subprocess
import sys
import time

import pytest
from PySide6.QtCore import Property, QCoreApplication, QEasingCurve, QObject, QPropertyAnimation, Qt
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

QWIDGETSIZE_MAX = (1 << 24) - 1
WAIT_MS = 3000


_HOLDER: list[QObject] = []


def _holder() -> QObject:
    if not _HOLDER:
        _HOLDER.append(QObject())
    return _HOLDER[0]


class Box(QObject):
    """Đích hoạt ảnh có thuộc tính Qt `value` (float).

    Mặc định là con của một QObject sống suốt tiến trình (như widget trong cây của app): khi test bỏ
    tham chiếu Python cuối, C++ không bị xóa. Ca đích do Python sở hữu bị bỏ tham chiếu (lỗi đã thấy)
    chạy trong tiến trình con: `test_dropping_last_reference_to_target_does_not_crash`.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent if parent is not None else _holder())
        self._value = 0.0

    def _get_value(self) -> float:
        return self._value

    def _set_value(self, v: float) -> None:
        self._value = float(v)

    value = Property(float, _get_value, _set_value)


def is_valid(obj) -> bool:
    import shiboken6

    return shiboken6.isValid(obj)


@pytest.fixture
def motion():
    from teleport.ui import motion as m

    return m


@pytest.fixture(autouse=True)
def drain_animations(qtbot):
    """Sau mỗi test, khi qtbot còn giữ widget: dừng mọi hoạt ảnh (không callback) rồi xử lý hết
    `deleteLater` đang chờ, để hoạt ảnh `DeleteWhenStopped` không bị hủy sau khi đích đã mất chủ."""
    yield
    from PySide6.QtCore import QEvent

    from teleport.ui import motion as m

    m._stop_all_for_tests()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qtbot.wait(1)


@pytest.fixture
def SHORT(motion):
    return motion.Token(30, QEasingCurve.Type.OutCubic)


@pytest.fixture
def LONG(motion):
    return motion.Token(10_000, QEasingCurve.Type.OutCubic)


@pytest.fixture
def shown(qtbot):
    """`shown(w=None, size=(240, 120)) -> QWidget`: cửa sổ cấp cao đã hiện.

    qtbot chỉ giữ tham chiếu yếu: bên gọi phải giữ cửa sổ."""

    def make(w: QWidget | None = None, size: tuple[int, int] = (240, 120)) -> QWidget:
        if w is None:
            w = QWidget()
        qtbot.addWidget(w)
        w.resize(*size)
        w.show()
        qtbot.waitExposed(w)
        return w

    return make


def overlays(container: QWidget) -> list[QWidget]:
    return [w for w in container.findChildren(QWidget, "motionOverlay") if is_valid(w)]


# =================================================================================================
# (a) Token và hằng số
# =================================================================================================


def test_tokens_have_spec_durations_and_curves(motion):
    T = QEasingCurve.Type
    assert (motion.INSTANT.ms, motion.INSTANT.curve) == (0, T.Linear)
    assert (motion.FAST.ms, motion.FAST.curve) == (120, T.OutCubic)
    assert (motion.NORMAL.ms, motion.NORMAL.curve) == (200, T.OutCubic)
    assert (motion.SLOW.ms, motion.SLOW.curve) == (280, T.InOutCubic)
    assert (motion.EMPHASIS.ms, motion.EMPHASIS.curve) == (450, T.OutBack)
    assert motion.EMPHASIS.overshoot == pytest.approx(1.2)
    for token in (motion.INSTANT, motion.FAST, motion.NORMAL, motion.SLOW):
        assert token.overshoot is None


def test_token_easing_builds_curve_with_overshoot(motion):
    curve = motion.EMPHASIS.easing()
    assert isinstance(curve, QEasingCurve)
    assert curve.type() == QEasingCurve.Type.OutBack
    assert curve.overshoot() == pytest.approx(1.2)
    plain = motion.Token(50, QEasingCurve.Type.InOutCubic).easing()
    assert plain.type() == QEasingCurve.Type.InOutCubic
    custom = motion.Token(50, QEasingCurve.Type.OutBack, 2.5).easing()
    assert custom.overshoot() == pytest.approx(2.5)


def test_token_is_frozen(motion):
    with pytest.raises(dataclasses.FrozenInstanceError):
        motion.NORMAL.ms = 1  # type: ignore[misc]
    assert motion.Token(10, QEasingCurve.Type.Linear) == motion.Token(10, QEasingCurve.Type.Linear)


def test_motion_limits_are_spec_values(motion):
    assert motion.MAX_SHIFT_PX == 8
    assert abs(motion.MAX_SCALE_DELTA - 0.02) < 1e-9
    assert motion.MAX_LOOP_MS == 5000


# =================================================================================================
# (b) Cổng bật/tắt
# =================================================================================================


def test_should_animate_is_false_in_test_instant_mode(motion):
    assert motion.should_animate() is False


def test_instant_mode_does_not_touch_animations_enabled(motion, monkeypatch):
    """Chế độ tức thì chỉ đổi `should_animate`, `animations_enabled` vẫn đọc cài đặt HĐH."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(motion, "_query_client_area_animation", lambda: True)
    assert motion.animations_enabled() is True
    assert motion.should_animate() is False


def test_should_animate_true_with_real_motion(real_motion):
    assert real_motion.should_animate() is True


def test_should_animate_follows_animations_enabled_by_global_name(real_motion, monkeypatch):
    monkeypatch.setattr(real_motion, "animations_enabled", lambda: False)
    assert real_motion.should_animate() is False


def test_force_instant_toggles_and_reset_turns_it_off(motion, monkeypatch):
    monkeypatch.setattr(motion, "animations_enabled", lambda: True)
    motion._force_instant(False)
    assert motion.should_animate() is True
    motion._force_instant(True)
    assert motion.should_animate() is False
    motion._reset_for_tests()
    assert motion.should_animate() is True
    motion._force_instant(True)


def test_should_animate_false_without_qt_application(real_motion, monkeypatch):
    """Q18: chưa có `QCoreApplication` thì không chạy hoạt ảnh."""
    from PySide6.QtGui import QGuiApplication

    with monkeypatch.context() as m:
        for cls in (QCoreApplication, QGuiApplication, QApplication):
            m.setattr(cls, "instance", staticmethod(lambda: None))
        assert QApplication.instance() is None
        result = real_motion.should_animate()
    assert result is False
    assert real_motion.should_animate() is True


# =================================================================================================
# (c) `animate` / `animate_value` tức thì
# =================================================================================================


def test_instant_animate_sets_end_and_calls_on_finished_before_return(motion):
    box = Box()
    order: list[str] = []
    result = motion.animate(box, "value", 42.0, motion.SLOW, on_finished=lambda: order.append("done"))
    order.append("returned")
    assert result is None
    assert box.value == pytest.approx(42.0)
    assert order == ["done", "returned"]
    assert motion.running_count() == 0


def test_instant_animate_on_widget_property(motion, qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    assert motion.animate(w, "maximumHeight", 37) is None
    assert w.maximumHeight() == 37


def test_zero_ms_token_is_instant_even_with_real_motion(real_motion):
    box = Box()
    done: list[int] = []
    result = real_motion.animate(box, "value", 9.0, real_motion.INSTANT, on_finished=lambda: done.append(1))
    assert result is None
    assert box.value == pytest.approx(9.0)
    assert done == [1]
    assert real_motion.running_count() == 0


def test_instant_animate_value_calls_on_value_end_then_on_finished(motion):
    owner = Box()
    order: list[object] = []
    result = motion.animate_value(
        owner, 0.0, 1.0, motion.NORMAL, order.append, on_finished=lambda: order.append("done")
    )
    order.append("returned")
    assert result is None
    assert order == [1.0, "done", "returned"]
    assert motion.running_count() == 0


def test_instant_animate_stops_running_animation_on_same_key(motion, LONG):
    box = Box()
    old_done: list[int] = []
    motion._force_instant(False)
    with pytest.MonkeyPatch.context() as m:
        m.setattr(motion, "animations_enabled", lambda: True)
        assert motion.animate(box, "value", 100.0, LONG, on_finished=lambda: old_done.append(1)) is not None
        assert motion.running_count() == 1
        motion._force_instant(True)
        assert motion.animate(box, "value", 5.0) is None
    assert box.value == pytest.approx(5.0)
    assert motion.running_count() == 0
    assert old_done == []


@pytest.mark.parametrize("instant", [True, False], ids=["tuc-thi", "that"])
def test_animate_rejects_unknown_property(motion, monkeypatch, instant):
    """Q5: tên thuộc tính sai → ValueError ở cả hai chế độ."""
    monkeypatch.setattr(motion, "animations_enabled", lambda: True)
    motion._force_instant(instant)
    box = Box()
    with pytest.raises(ValueError):
        motion.animate(box, "khongCoThuocTinhNay", 1.0, motion.NORMAL)
    assert motion.running_count() == 0
    motion._force_instant(True)


# =================================================================================================
# (d) `animate` / `animate_value` chạy thật
# =================================================================================================


def test_real_animate_reaches_end_and_running_count_returns_to_zero(real_motion, qtbot, SHORT):
    box = Box()
    done: list[int] = []
    anim = real_motion.animate(box, "value", 50.0, SHORT, on_finished=lambda: done.append(1))
    assert isinstance(anim, QPropertyAnimation)
    assert anim.duration() == 30
    assert anim.easingCurve().type() == QEasingCurve.Type.OutCubic
    assert anim.targetObject() is box
    assert bytes(anim.propertyName()) == b"value"
    assert real_motion.running_count() == 1
    assert done == []  # chạy thật: chưa xong lúc trả về
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert box.value == pytest.approx(50.0)
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)


def test_real_animate_with_explicit_start(real_motion, qtbot, SHORT):
    box = Box()
    box.value = 3.0
    anim = real_motion.animate(box, "value", 8.0, SHORT, start=20.0)
    assert anim is not None
    assert anim.startValue() == pytest.approx(20.0)
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)
    assert box.value == pytest.approx(8.0)


def test_real_animate_value_reaches_end(real_motion, qtbot, SHORT):
    owner = Box()
    values: list[float] = []
    done: list[int] = []
    anim = real_motion.animate_value(
        owner, 0.0, 1.0, SHORT, values.append, on_finished=lambda: done.append(1)
    )
    assert anim is not None
    assert real_motion.running_count() == 1
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert values and values[-1] == pytest.approx(1.0)
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)


# =================================================================================================
# (e) Thay hoạt ảnh trên cùng khóa
# =================================================================================================


def test_new_animation_replaces_old_without_calling_old_on_finished(real_motion, qtbot, SHORT, LONG):
    """Q3: cũ dừng, không gọi `on_finished` cũ; sổ không đếm thừa; mới chạy từ giá trị hiện tại."""
    box = Box()
    old_done: list[int] = []
    new_done: list[int] = []
    real_motion.animate(box, "value", 100.0, LONG, on_finished=lambda: old_done.append(1))
    assert real_motion.running_count() == 1
    box.value = 42.0  # giá trị hiện tại khác điểm đầu (0) của hoạt ảnh cũ
    current = box.value
    new = real_motion.animate(box, "value", 50.0, SHORT, on_finished=lambda: new_done.append(1))
    assert real_motion.running_count() == 1
    assert new is not None and new.startValue() == pytest.approx(current)
    qtbot.waitUntil(lambda: new_done == [1], timeout=WAIT_MS)
    assert box.value == pytest.approx(50.0)
    qtbot.wait(50)
    assert old_done == []
    assert real_motion.running_count() == 0


def test_different_properties_and_keys_run_side_by_side(real_motion, qtbot, LONG):
    w = QWidget()
    qtbot.addWidget(w)
    real_motion.animate(w, "maximumHeight", 10, LONG)
    real_motion.animate(w, "maximumWidth", 10, LONG)
    owner = Box()
    real_motion.animate_value(owner, 0.0, 1.0, LONG, lambda v: None, key="a")
    real_motion.animate_value(owner, 0.0, 1.0, LONG, lambda v: None, key="b")
    assert real_motion.running_count() == 4
    real_motion.animate_value(owner, 0.0, 2.0, LONG, lambda v: None, key="a")
    assert real_motion.running_count() == 4
    assert real_motion.finish_all() == 4
    assert real_motion.running_count() == 0


def test_animate_value_replacement_skips_old_on_finished(real_motion, qtbot, SHORT, LONG):
    owner = Box()
    old_done: list[int] = []
    new_values: list[float] = []
    real_motion.animate_value(owner, 0.0, 1.0, LONG, lambda v: None, on_finished=lambda: old_done.append(1))
    real_motion.animate_value(owner, 0.0, 3.0, SHORT, new_values.append)
    assert real_motion.running_count() == 1
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)
    assert new_values[-1] == pytest.approx(3.0)
    assert old_done == []


# =================================================================================================
# (f) `finish_all`
# =================================================================================================


def test_finish_all_jumps_to_end_and_stops_loops(real_motion, shown, LONG):
    box = Box()
    owner = Box()
    w = shown()
    events: list[object] = []
    real_motion.animate(box, "value", 70.0, LONG, on_finished=lambda: events.append("anim"))
    values: list[float] = []
    real_motion.animate_value(
        owner, 0.0, 4.0, LONG, values.append, on_finished=lambda: events.append("value")
    )
    loop = real_motion.Loop(w, 1000, lambda t: None, on_stop=lambda: events.append("loop"))
    loop.start()
    assert loop.running
    assert real_motion.running_count() == 3

    assert real_motion.finish_all() == 3

    assert box.value == pytest.approx(70.0)
    assert values and values[-1] == pytest.approx(4.0)
    assert sorted(map(str, events)) == ["anim", "loop", "value"]
    assert not loop.running
    assert real_motion.running_count() == 0
    assert real_motion.finish_all() == 0


def test_finish_all_keeps_loop_restarted_by_on_stop_in_registry(real_motion, shown):
    """Vòng được `on_stop` chạy lại vẫn nằm trong sổ: `finish_all` dừng nó ở vòng sau, không mất dấu."""
    w = shown()
    starts: list[int] = []
    loop_ref: list[object] = []

    def on_stop() -> None:
        if len(starts) < 1:
            starts.append(1)
            loop_ref[0].start()

    loop = real_motion.Loop(w, 1000, lambda t: None, on_stop=on_stop)
    loop_ref.append(loop)
    loop.start()
    real_motion.finish_all()
    assert starts == [1]
    assert not loop.running
    assert real_motion.running_count() == 0


def test_fader_show_hide_default_to_normal_token(motion, monkeypatch):
    seen: list[object] = []
    fader = motion.Fader(QWidget())
    monkeypatch.setattr(fader, "crossfade", lambda change, token=None, **k: seen.append(token))
    child = QWidget()
    fader.show(child)
    fader.hide(child)
    assert seen == [motion.NORMAL, motion.NORMAL]


def test_finish_all_completes_animations_started_in_on_finished(real_motion, LONG):
    """Q10: hoạt ảnh nối tiếp mở trong `on_finished` cũng được hoàn tất; trả tổng số đã xử lý."""
    first, second = Box(), Box()
    order: list[str] = []

    def first_done() -> None:
        order.append("first")
        real_motion.animate(second, "value", 7.0, LONG, on_finished=lambda: order.append("second"))

    real_motion.animate(first, "value", 5.0, LONG, on_finished=first_done)
    assert real_motion.finish_all() == 2
    assert order == ["first", "second"]
    assert (first.value, second.value) == (pytest.approx(5.0), pytest.approx(7.0))
    assert real_motion.running_count() == 0


def test_finish_all_in_instant_mode_with_nothing_running(motion):
    assert motion.finish_all() == 0


# =================================================================================================
# (g) Đích bị hủy giữa chừng
# =================================================================================================


def test_destroyed_target_leaves_registry_and_finish_all_skips_it(real_motion, LONG):
    import shiboken6

    box = Box()
    done: list[int] = []
    real_motion.animate(box, "value", 10.0, LONG, on_finished=lambda: done.append(1))
    owner = Box()
    real_motion.animate_value(owner, 0.0, 1.0, LONG, lambda v: None)
    assert real_motion.running_count() == 2
    shiboken6.delete(box)
    shiboken6.delete(owner)
    QApplication.processEvents()
    assert real_motion.running_count() == 0
    assert real_motion.finish_all() == 0


def test_widget_deleted_later_mid_animation(real_motion, qtbot, LONG):
    w = QWidget()
    real_motion.animate(w, "maximumHeight", 10, LONG)
    assert real_motion.running_count() == 1
    w.deleteLater()
    qtbot.waitUntil(lambda: not is_valid(w), timeout=WAIT_MS)
    assert real_motion.running_count() == 0
    real_motion.finish_all()  # không ném


_DROP_TARGET_SCRIPT = r"""
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtCore import Property, QEasingCurve, QEventLoop, QObject, QTimer
from PySide6.QtWidgets import QApplication

from teleport.ui import motion

class Box(QObject):
    def __init__(self):
        super().__init__()
        self._v = 0.0
    def _g(self):
        return self._v
    def _s(self, v):
        self._v = float(v)
    value = Property(float, _g, _s)

app = QApplication([])
motion.animations_enabled = lambda: True
LONG = motion.Token(10_000, QEasingCurve.Type.OutCubic)

def spin():
    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()

def replaced_then_dropped():
    box = Box()
    motion._force_instant(False)
    motion.animate(box, "value", 100.0, LONG)
    motion._force_instant(True)
    motion.animate(box, "value", 5.0)

def finished_all_then_dropped():
    box = Box()
    motion._force_instant(False)
    motion.animate(box, "value", 100.0, LONG)
    motion.finish_all()

def value_owner_dropped():
    owner = QObject()
    motion._force_instant(False)
    motion.animate_value(owner, 0.0, 1.0, LONG, lambda v: None)
    motion.finish_all()

for case in (replaced_then_dropped, finished_all_then_dropped, value_owner_dropped):
    case()
    spin()
    print("ok", case.__name__, flush=True)
"""


@pytest.mark.slow
def test_dropping_last_reference_to_target_does_not_crash(tmp_path):
    """Đích (QObject do Python sở hữu, không cha) bị bỏ tham chiếu Python cuối sau khi hoạt ảnh của nó
    đã dừng/xong: tiến trình không được sập khi `deleteLater` của hoạt ảnh chạy.

    Chạy trong tiến trình con: nếu sập (segfault) thì chỉ test này đỏ.
    """
    import os

    script = tmp_path / "drop_target.py"
    script.write_text(_DROP_TARGET_SCRIPT, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        check=False,
    )
    assert proc.returncode == 0, (
        f"tiến trình con thoát mã {proc.returncode}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr[-2000:]}"
    )
    assert proc.stdout.count("ok ") == 3


# =================================================================================================
# (h) Fader và fade_in_window
# =================================================================================================


@pytest.fixture
def container(shown):
    c = QWidget()
    layout = QVBoxLayout(c)
    layout.addWidget(QLabel("Nội dung cũ"))
    return shown(c, (240, 120))


def test_instant_crossfade_only_calls_change_and_leaves_no_overlay(motion, container):
    """Q1: chế độ tức thì không tạo con `motionOverlay` nào."""
    fader = motion.Fader(container)
    calls: list[int] = []
    fader.crossfade(lambda: calls.append(1))
    assert calls == [1]
    QApplication.processEvents()
    assert container.findChildren(QWidget, "motionOverlay") == []


def test_real_crossfade_changes_now_and_overlay_removes_itself(real_motion, qtbot, container, SHORT):
    fader = real_motion.Fader(container)
    order: list[str] = []
    fader.crossfade(lambda: order.append("change"), SHORT)
    order.append("returned")
    assert order == ["change", "returned"]
    found = overlays(container)
    assert len(found) == 1
    overlay = found[0]
    assert overlay.parentWidget() is container
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert overlay.isVisible()
    widget_children = [c for c in container.children() if isinstance(c, QWidget)]
    assert widget_children[-1].objectName() == "motionOverlay"  # raise: nằm trên cùng
    qtbot.waitUntil(lambda: overlays(container) == [], timeout=WAIT_MS)
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)


def test_overlay_follows_container_resize(real_motion, qtbot, container, LONG):
    """Q12: overlay theo `Resize` của container."""
    fader = real_motion.Fader(container)
    fader.crossfade(lambda: None, LONG)
    (overlay,) = overlays(container)
    container.resize(320, 180)
    QApplication.processEvents()
    assert overlay.geometry() == container.rect()
    real_motion.finish_all()
    qtbot.waitUntil(lambda: overlays(container) == [], timeout=WAIT_MS)


def test_second_crossfade_replaces_previous_overlay(real_motion, qtbot, container, LONG):
    fader = real_motion.Fader(container)
    fader.crossfade(lambda: None, LONG)
    fader.crossfade(lambda: None, LONG)
    qtbot.waitUntil(lambda: len(overlays(container)) == 1, timeout=WAIT_MS)
    real_motion.finish_all()
    qtbot.waitUntil(lambda: overlays(container) == [], timeout=WAIT_MS)
    assert real_motion.running_count() == 0


def test_crossfade_with_shift_still_finishes(real_motion, qtbot, container, SHORT):
    from PySide6.QtCore import QPoint

    fader = real_motion.Fader(container)
    calls: list[int] = []
    fader.crossfade(lambda: calls.append(1), SHORT, shift=QPoint(100, -100))
    assert calls == [1]
    qtbot.waitUntil(lambda: overlays(container) == [], timeout=WAIT_MS)


def test_crossfade_on_hidden_container_only_changes(real_motion, qtbot):
    c = QWidget()
    qtbot.addWidget(c)
    c.resize(200, 100)
    fader = real_motion.Fader(c)
    calls: list[int] = []
    fader.crossfade(lambda: calls.append(1), real_motion.NORMAL)
    assert calls == [1]
    assert c.findChildren(QWidget, "motionOverlay") == []
    assert real_motion.running_count() == 0


def test_crossfade_on_empty_container_only_changes(real_motion, shown):
    host = shown()
    c = QWidget(host)
    c.setFixedSize(0, 0)
    c.show()
    QApplication.processEvents()
    fader = real_motion.Fader(c)
    calls: list[int] = []
    fader.crossfade(lambda: calls.append(1), real_motion.NORMAL)
    assert calls == [1]
    assert c.findChildren(QWidget, "motionOverlay") == []
    assert real_motion.running_count() == 0


@pytest.mark.parametrize("real", [False, True], ids=["tuc-thi", "that"])
def test_fader_show_and_hide_toggle_visibility_now(motion, monkeypatch, qtbot, container, real):
    if real:
        monkeypatch.setattr(motion, "animations_enabled", lambda: True)
        motion._force_instant(False)
    child = QLabel("Con", container)
    child.hide()
    fader = motion.Fader(container)
    fader.show(child, motion.Token(30, QEasingCurve.Type.OutCubic))
    assert child.isVisibleTo(container)
    qtbot.waitUntil(lambda: motion.running_count() == 0, timeout=WAIT_MS)
    fader.hide(child, motion.Token(30, QEasingCurve.Type.OutCubic))
    assert not child.isVisibleTo(container)
    qtbot.waitUntil(lambda: motion.running_count() == 0, timeout=WAIT_MS)
    qtbot.waitUntil(lambda: overlays(container) == [], timeout=WAIT_MS)
    motion._force_instant(True)


def test_fade_in_window_instant_sets_full_opacity(motion, shown):
    w = shown()
    w.setWindowOpacity(0.3)
    motion.fade_in_window(w)
    assert w.windowOpacity() == 1.0


def test_fade_in_window_real_ends_at_full_opacity(real_motion, qtbot, shown, SHORT):
    """Q11: offscreen đặt ngay 1.0; mọi đường thoát để 1.0."""
    w = shown()
    real_motion.fade_in_window(w, SHORT)
    qtbot.waitUntil(lambda: real_motion.running_count() == 0, timeout=WAIT_MS)
    assert w.windowOpacity() == 1.0


@pytest.mark.parametrize("exit_path", ["finish_all", "stop_all", "replaced"])
def test_fade_in_window_real_path_every_exit_ends_at_full_opacity(
    real_motion, monkeypatch, shown, LONG, exit_path
):
    """Q11 trên nhánh chạy thật (nền có hỗ trợ độ mờ cửa sổ): mọi đường thoát để `windowOpacity` 1.0."""
    monkeypatch.setattr(real_motion, "_PLATFORMS_WITHOUT_WINDOW_OPACITY", frozenset())
    w = shown()
    real_motion.fade_in_window(w, LONG)
    assert real_motion.running_count() == 1
    if exit_path == "finish_all":
        real_motion.finish_all()
    elif exit_path == "stop_all":
        real_motion._stop_all_for_tests()
    else:
        real_motion.fade_in_window(w, LONG)
        real_motion.finish_all()
    assert w.windowOpacity() == pytest.approx(1.0)
    assert real_motion.running_count() == 0


def test_fade_in_window_then_finish_all_ends_at_full_opacity(real_motion, shown, LONG):
    w = shown()
    real_motion.fade_in_window(w, LONG)
    real_motion.finish_all()
    assert w.windowOpacity() == 1.0
    assert real_motion.running_count() == 0


# =================================================================================================
# (i) HeightAnimator
# =================================================================================================


@pytest.fixture
def panel(shown):
    host = QWidget()
    layout = QVBoxLayout(host)
    p = QWidget()
    inner = QVBoxLayout(p)
    inner.addWidget(QLabel("Dòng một"))
    inner.addWidget(QLabel("Dòng hai"))
    layout.addWidget(p)
    layout.addStretch(1)
    shown(host, (300, 300))
    yield p  # giữ `host`: qtbot chỉ giữ tham chiếu yếu


def assert_expanded(p: QWidget, animator) -> None:
    assert animator.expanded is True
    assert p.isVisibleTo(p.parentWidget())
    assert p.maximumHeight() == QWIDGETSIZE_MAX


def assert_collapsed(p: QWidget, animator) -> None:
    assert animator.expanded is False
    assert p.isHidden()
    assert p.maximumHeight() == QWIDGETSIZE_MAX


def test_height_animator_instant_expand_and_collapse(motion, panel):
    panel.hide()
    animator = motion.HeightAnimator(panel)
    done: list[str] = []
    animator.expand(on_finished=lambda: done.append("expand"))
    assert done == ["expand"]
    assert_expanded(panel, animator)
    animator.collapse(on_finished=lambda: done.append("collapse"))
    assert done == ["expand", "collapse"]
    assert_collapsed(panel, animator)
    assert motion.running_count() == 0


def test_height_animator_set_expanded(motion, panel):
    panel.hide()
    animator = motion.HeightAnimator(panel)
    animator.set_expanded(True)
    assert_expanded(panel, animator)
    animator.set_expanded(False)
    assert_collapsed(panel, animator)


def test_height_animator_real_expand_shows_now_and_resets_max(real_motion, qtbot, panel, SHORT):
    panel.hide()
    animator = real_motion.HeightAnimator(panel)
    done: list[int] = []
    animator.expand(SHORT, on_finished=lambda: done.append(1))
    assert panel.isVisibleTo(panel.parentWidget())  # show() ngay
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert_expanded(panel, animator)
    qtbot.waitUntil(lambda: panel.height() > 0, timeout=WAIT_MS)
    assert real_motion.running_count() == 0


def test_height_animator_real_collapse_hides_and_resets_max(real_motion, qtbot, panel, SHORT):
    animator = real_motion.HeightAnimator(panel)
    done: list[int] = []
    animator.collapse(SHORT, on_finished=lambda: done.append(1))
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert_collapsed(panel, animator)
    assert real_motion.running_count() == 0


def test_height_animator_restores_minimum_height(real_motion, qtbot, panel, SHORT):
    """Q6: `minimumHeight` được trả lại khi xong."""
    panel.setMinimumHeight(12)
    panel.hide()
    animator = real_motion.HeightAnimator(panel)
    done: list[str] = []
    animator.expand(SHORT, on_finished=lambda: done.append("e"))
    qtbot.waitUntil(lambda: done == ["e"], timeout=WAIT_MS)
    assert panel.minimumHeight() == 12
    animator.collapse(SHORT, on_finished=lambda: done.append("c"))
    qtbot.waitUntil(lambda: done == ["e", "c"], timeout=WAIT_MS)
    assert panel.minimumHeight() == 12
    assert_collapsed(panel, animator)


def test_height_animator_reverse_expand_to_collapse(real_motion, qtbot, panel, SHORT, LONG):
    panel.setMinimumHeight(12)
    panel.hide()
    animator = real_motion.HeightAnimator(panel)
    animator.expand(LONG)
    done: list[int] = []
    animator.collapse(SHORT, on_finished=lambda: done.append(1))
    assert real_motion.running_count() == 1
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert_collapsed(panel, animator)
    assert panel.minimumHeight() == 12
    assert real_motion.running_count() == 0


def test_height_animator_reverse_collapse_to_expand(real_motion, qtbot, panel, SHORT, LONG):
    panel.setMinimumHeight(12)
    animator = real_motion.HeightAnimator(panel)
    animator.collapse(LONG)
    done: list[int] = []
    animator.expand(SHORT, on_finished=lambda: done.append(1))
    assert real_motion.running_count() == 1
    qtbot.waitUntil(lambda: done == [1], timeout=WAIT_MS)
    assert_expanded(panel, animator)
    assert panel.minimumHeight() == 12
    assert real_motion.running_count() == 0


def test_height_animator_finish_all_completes_expand(real_motion, panel, LONG):
    panel.hide()
    animator = real_motion.HeightAnimator(panel)
    done: list[int] = []
    animator.expand(LONG, on_finished=lambda: done.append(1))
    assert real_motion.finish_all() >= 1
    assert done == [1]
    assert_expanded(panel, animator)


# =================================================================================================
# (j) Loop
# =================================================================================================


class Recorder:
    def __init__(self) -> None:
        self.steps: list[float] = []
        self.stops = 0

    def step(self, t: float) -> None:
        self.steps.append(t)

    def stop(self) -> None:
        self.stops += 1


@pytest.fixture
def window_with_child(shown):
    win = QWidget()
    child = QLabel("Sóng", win)
    shown(win, (240, 120))
    child.show()
    QApplication.processEvents()
    return win, child


def test_loop_runs_steps_in_unit_range_and_stops_by_itself(real_motion, qtbot, window_with_child):
    _win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 40, rec.step, max_ms=200, on_stop=rec.stop)
    loop.start()
    assert loop.running
    assert real_motion.running_count() == 1
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)
    assert rec.stops == 1
    assert rec.steps and all(0.0 <= t <= 1.0 for t in rec.steps)
    assert real_motion.running_count() == 0


def test_loop_period_longer_than_cap_is_clamped(real_motion, qtbot, monkeypatch, window_with_child):
    """Q4: period 7000 bị kẹp về cap; `MAX_LOOP_MS` đọc lúc dùng."""
    _win, child = window_with_child
    monkeypatch.setattr(real_motion, "MAX_LOOP_MS", 150)
    loop = real_motion.Loop(child, 7000, lambda t: None)
    loop.start()
    assert loop.running
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)


def test_loop_max_ms_cannot_exceed_module_cap(real_motion, qtbot, monkeypatch, window_with_child):
    _win, child = window_with_child
    monkeypatch.setattr(real_motion, "MAX_LOOP_MS", 150)
    loop = real_motion.Loop(child, 50, lambda t: None, max_ms=60_000)
    loop.start()
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)


@pytest.mark.slow
def test_loop_with_7000_ms_period_stops_within_5_seconds(real_motion, qtbot, window_with_child):
    """mvp N12, Q4: tổng ≤ `MAX_LOOP_MS` (5 s) với giá trị thật."""
    _win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 7000, rec.step, on_stop=rec.stop)
    t0 = time.monotonic()
    loop.start()
    assert loop.running
    qtbot.waitUntil(lambda: not loop.running, timeout=8000)
    elapsed = time.monotonic() - t0
    assert elapsed <= 5.0 + 0.8, f"Loop chạy {elapsed:.2f} s"
    assert rec.stops == 1


def test_loop_stops_when_widget_hidden_and_does_not_restart(real_motion, qtbot, window_with_child):
    _win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 100, rec.step, on_stop=rec.stop)
    loop.start()
    assert loop.running
    child.hide()
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)
    assert rec.stops == 1
    child.show()
    qtbot.wait(50)
    assert not loop.running
    assert real_motion.running_count() == 0


def test_loop_stops_when_window_hidden(real_motion, qtbot, window_with_child):
    win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 100, rec.step, on_stop=rec.stop)
    loop.start()
    win.hide()
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)
    assert rec.stops == 1


def test_loop_stops_when_window_minimized(real_motion, qtbot, window_with_child):
    win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 100, rec.step, on_stop=rec.stop)
    loop.start()
    assert loop.running
    win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
    assert win.isMinimized()
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)
    assert rec.stops == 1
    assert real_motion.running_count() == 0


def test_loop_on_top_level_widget_stops_once_on_hide(real_motion, qtbot, shown):
    """Q13: widget là cửa sổ → filter không cài hai lần; `on_stop` một lần."""
    w = shown()
    rec = Recorder()
    loop = real_motion.Loop(w, 100, rec.step, on_stop=rec.stop)
    loop.start()
    assert loop.running
    w.hide()
    qtbot.waitUntil(lambda: not loop.running, timeout=WAIT_MS)
    qtbot.wait(30)
    assert rec.stops == 1


def test_loop_does_not_start_when_widget_hidden(real_motion, qtbot):
    w = QWidget()
    qtbot.addWidget(w)
    loop = real_motion.Loop(w, 100, lambda t: None)
    loop.start()
    assert not loop.running
    assert real_motion.running_count() == 0


def test_loop_does_not_start_when_window_minimized(real_motion, window_with_child):
    win, child = window_with_child
    win.setWindowState(win.windowState() | Qt.WindowState.WindowMinimized)
    assert win.isMinimized()
    loop = real_motion.Loop(child, 100, lambda t: None)
    loop.start()
    assert not loop.running
    assert real_motion.running_count() == 0


def test_loop_does_not_start_in_instant_mode(motion, window_with_child):
    _win, child = window_with_child
    rec = Recorder()
    loop = motion.Loop(child, 100, rec.step)
    loop.start()
    assert not loop.running
    assert rec.steps == []
    assert motion.running_count() == 0


def test_loop_does_not_start_when_system_disables_animations(real_motion, monkeypatch, window_with_child):
    _win, child = window_with_child
    monkeypatch.setattr(real_motion, "animations_enabled", lambda: False)
    loop = real_motion.Loop(child, 100, lambda t: None)
    loop.start()
    assert not loop.running
    assert real_motion.running_count() == 0


def test_loop_stop_calls_on_stop_once_and_restart_works(real_motion, window_with_child):
    _win, child = window_with_child
    rec = Recorder()
    loop = real_motion.Loop(child, 1000, rec.step, on_stop=rec.stop)
    loop.start()
    loop.start()  # đang chạy: không làm gì
    assert loop.running
    assert rec.stops == 0
    assert real_motion.running_count() == 1
    loop.stop()
    assert not loop.running
    assert rec.stops == 1
    loop.stop()
    assert rec.stops == 1
    assert real_motion.running_count() == 0
    loop.start()
    assert loop.running
    loop.stop()
    assert rec.stops == 2


def test_loop_removed_from_registry_when_widget_destroyed(real_motion, qtbot, window_with_child):
    _win, child = window_with_child
    loop = real_motion.Loop(child, 1000, lambda t: None)
    loop.start()
    assert real_motion.running_count() == 1
    child.deleteLater()
    qtbot.waitUntil(lambda: not is_valid(child), timeout=WAIT_MS)
    assert real_motion.running_count() == 0
    real_motion.finish_all()  # không ném


def test_stop_all_for_tests_skips_callbacks(real_motion, window_with_child, LONG):
    """Q9: dọn test dừng mọi thứ, không gọi `on_finished`/`on_stop`."""
    _win, child = window_with_child
    box = Box()
    called: list[str] = []
    real_motion.animate(box, "value", 1.0, LONG, on_finished=lambda: called.append("anim"))
    loop = real_motion.Loop(child, 1000, lambda t: None, on_stop=lambda: called.append("loop"))
    loop.start()
    real_motion._stop_all_for_tests()
    assert called == []
    assert not loop.running
    assert real_motion.running_count() == 0


# =================================================================================================
# (k) Seam macOS / GNOME
# =================================================================================================


@pytest.fixture
def clock(motion, monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(motion, "_monotonic", lambda: now["t"])
    motion._reset_for_tests()
    motion._force_instant(True)
    return now


def counting(result):
    calls = {"n": 0}

    def query() -> bool:
        calls["n"] += 1
        if isinstance(result, BaseException):
            raise result
        return result

    return query, calls


@pytest.mark.parametrize(
    ("result", "want"),
    [(True, False), (False, True), (OSError("objc hỏng"), True)],
    ids=["giam-chuyen-dong-thi-false", "khong-giam-thi-true", "loi-thi-true"],
)
def test_macos_follows_reduce_motion_without_cache(motion, monkeypatch, result, want):
    query, calls = counting(result)
    monkeypatch.setattr(motion, "_query_macos_reduce_motion", query)
    monkeypatch.setattr(sys, "platform", "darwin")
    assert motion.animations_enabled() is want
    assert motion.animations_enabled() is want
    assert calls["n"] == 2  # đọc mỗi lần, không cache


@pytest.mark.parametrize(
    ("result", "want"),
    [(True, True), (False, False), (ValueError("'abc'"), True), (OSError("dbus treo"), True)],
    ids=["bat-thi-true", "tat-thi-false", "gia-tri-la-thi-true", "loi-thi-true"],
)
def test_gnome_follows_setting(motion, monkeypatch, clock, result, want):
    query, calls = counting(result)
    monkeypatch.setattr(motion, "_query_gnome_animations", query)
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is want
    assert calls["n"] == 1


def test_gnome_result_is_cached_for_ttl(motion, monkeypatch, clock):
    assert motion._GNOME_CACHE_TTL == 5.0
    state = {"value": False}
    calls = {"n": 0}

    def query() -> bool:
        calls["n"] += 1
        return state["value"]

    monkeypatch.setattr(motion, "_query_gnome_animations", query)
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is False
    state["value"] = True
    clock["t"] += motion._GNOME_CACHE_TTL - 0.1
    assert motion.animations_enabled() is False  # còn trong cache
    assert calls["n"] == 1
    clock["t"] += 0.2
    assert motion.animations_enabled() is True  # hết hạn: đọc lại
    assert calls["n"] == 2
    assert motion.animations_enabled() is True
    assert calls["n"] == 2


def test_gnome_error_is_cached_too(motion, monkeypatch, clock):
    query, calls = counting(OSError("dbus treo"))
    monkeypatch.setattr(motion, "_query_gnome_animations", query)
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is True
    clock["t"] += 1.0
    assert motion.animations_enabled() is True
    assert calls["n"] == 1
    clock["t"] += motion._GNOME_CACHE_TTL
    assert motion.animations_enabled() is True
    assert calls["n"] == 2


def test_reset_for_tests_clears_gnome_cache(motion, monkeypatch, clock):
    query, calls = counting(False)
    monkeypatch.setattr(motion, "_query_gnome_animations", query)
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is False
    motion._reset_for_tests()
    motion._force_instant(True)
    assert motion.animations_enabled() is False
    assert calls["n"] == 2


def test_other_platforms_are_true_without_queries(motion, monkeypatch):
    mac, mac_calls = counting(True)
    gnome, gnome_calls = counting(False)
    monkeypatch.setattr(motion, "_query_macos_reduce_motion", mac)
    monkeypatch.setattr(motion, "_query_gnome_animations", gnome)
    monkeypatch.setattr(sys, "platform", "freebsd14")
    assert motion.animations_enabled() is True
    assert (mac_calls["n"], gnome_calls["n"]) == (0, 0)


# `_query_gnome_animations` thật, với `subprocess.run` giả.


@pytest.fixture
def fake_gsettings(monkeypatch):
    """`fake_gsettings(stdout="true\\n", returncode=0, raises=None) -> list[(args, kwargs)]`."""
    calls: list[tuple[tuple, dict]] = []

    def install(stdout: str = "true\n", returncode: int = 0, raises: BaseException | None = None):
        def run(*args, **kwargs):
            calls.append((args, kwargs))
            if raises is not None:
                raise raises
            cmd = args[0] if args else kwargs.get("args")
            return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

        monkeypatch.setattr(subprocess, "run", run)
        return calls

    return install


@pytest.mark.parametrize(("stdout", "want"), [("true\n", True), ("false\n", False)])
def test_gnome_query_reads_gsettings_with_timeout(motion, fake_gsettings, stdout, want):
    assert motion._GSETTINGS_TIMEOUT == 0.5
    calls = fake_gsettings(stdout=stdout)
    assert motion._query_gnome_animations() is want
    assert len(calls) == 1
    args, kwargs = calls[0]
    cmd = args[0] if args else kwargs["args"]
    assert list(cmd) == ["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"]
    assert kwargs.get("timeout") == motion._GSETTINGS_TIMEOUT


def test_gnome_query_unexpected_output_raises_value_error(motion, fake_gsettings):
    fake_gsettings(stdout="'co le'\n")
    with pytest.raises(ValueError):
        motion._query_gnome_animations()


@pytest.mark.parametrize(
    "case",
    ["khong-co-gsettings", "ma-thoat-khac-0", "het-han", "gia-tri-la"],
)
def test_gnome_failures_mean_animations_enabled(motion, monkeypatch, clock, fake_gsettings, case):
    """Không có `gsettings`, mã thoát ≠ 0 (Q15), quá hạn, kết quả lạ → `animations_enabled()` True."""
    if case == "khong-co-gsettings":
        fake_gsettings(raises=FileNotFoundError("gsettings"))
    elif case == "ma-thoat-khac-0":
        fake_gsettings(stdout="false\n", returncode=1)
    elif case == "het-han":
        fake_gsettings(raises=subprocess.TimeoutExpired(["gsettings"], 0.5))
    else:
        fake_gsettings(stdout="'abc'\n")
    monkeypatch.setattr(sys, "platform", "linux")
    assert motion.animations_enabled() is True


@pytest.mark.skipif(sys.platform != "darwin", reason="chỉ macOS có NSWorkspace")
def test_real_macos_query_returns_bool(motion):
    assert isinstance(motion._query_macos_reduce_motion(), bool)
    assert isinstance(motion.animations_enabled(), bool)


@pytest.mark.skipif(
    not (sys.platform.startswith("linux") and shutil.which("gsettings")),
    reason="chỉ Linux có gsettings",
)
def test_real_gnome_query_returns_bool_or_raises(motion):
    try:
        value = motion._query_gnome_animations()
    except Exception:
        pass
    else:
        assert isinstance(value, bool)
    assert isinstance(motion.animations_enabled(), bool)
