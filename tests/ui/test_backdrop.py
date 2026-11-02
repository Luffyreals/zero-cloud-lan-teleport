"""Nền Mica cho cột trái cửa sổ chính (spec G7: mục 2 API, mục 4 T-1…T-16; mục 9 thắng khi lệch).

Viết từ spec, không từ code `ui/backdrop.py`. Mỗi test ghi mã T-.. ở docstring.

- Không bao giờ gọi DWM thật, không đọc/ghi registry thật: fixture `mica_env` vá các seam cấp module
  (`_qt_platform`, `_windows_build`, `_high_contrast`, `_transparency_enabled`, `_dwm_extend_frame`,
  `_dwm_set_backdrop`, `_dwm_set_dark`), spy DWM ghi `(tên, hwnd, giá trị)`; ca không vá nền (T-3) vẫn
  thay ba hàm DWM bằng spy để chứng minh chúng không được gọi.
- Test pixel theo mục 9 ý 11: `window.grab()` (cửa sổ translucent → nền trong suốt, alpha thật trên
  `offscreen`), `motion.finish_all()` trước khi chụp, theme qua `ui_theme`, dung sai ±2, điểm mẫu tránh
  chữ/avatar (cùng cách chọn điểm với L4 của `test_home_layout.py`).
- Fixture autouse `backdrop_reset` (conftest, do giao-dien thêm) gọi `_reset_for_tests()` sau mỗi test;
  `mica_env` gọi thêm một lần ở teardown của chính nó (spec mục 4).
"""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from hypothesis import given
from hypothesis import strategies as st
from PySide6.QtCore import QByteArray, QCoreApplication, QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QFrame, QMainWindow

# ---- Hằng của spec (mục 2.1, 2.2) ----------------------------------------------------------------
MICA_MIN_BUILD = 22621
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
WM_SETTINGCHANGE = 0x001A
WM_THEMECHANGED = 0x031A
WM_DWMCOMPOSITIONCHANGED = 0x031E
WM_MOUSEMOVE = 0x0200
MICA_TINT_ALPHA = 178
E_FAIL = -2147467259  # 0x80004005 dạng có dấu (restype c_long, mục 9 ý 9)

TOL = 2  # mục 9 ý 11
WIDE = (980, 660)
COMPACT = (760, 660)  # < COMPACT_BELOW (820), ≥ MIN_SIZE (720)

# Điểm (tọa độ trong cột trái cũ) để kiểm T-11; điểm rơi vào widget tự vẽ chỉ kiểm alpha (`self_painted_at`).
OLD_SIDEBAR_POINTS = [(x, y) for x in (4, 40, 100, 200) for y in (8, 100, 300, 450)]


# =================================================================================================
# Hàm phụ trợ (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


def settle() -> None:
    for _ in range(4):
        QApplication.processEvents()


def destroy_stale_windows() -> None:
    """Hủy hẳn cửa sổ của test trước (qtbot chỉ `deleteLater`): cửa sổ Mica cũ còn sống sẽ gọi spy DWM
    của test này khi bảng màu ứng dụng đổi (seam đọc lúc gọi), làm bẩn bản ghi."""
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def detach_backdrops(backdrop) -> None:
    """Teardown của `mica_env`: hủy mọi `MicaBackdrop` còn gắn vào cửa sổ đang sống, trước khi qtbot hủy
    cửa sổ. Đường “hủy cửa sổ đang Mica” chỉ được kiểm ở T-15; các test khác không để lỗi của đường đó
    (nếu có) lan thành lỗi setup/teardown của test sau."""
    import shiboken6

    for top in QApplication.topLevelWidgets():
        for b in top.findChildren(backdrop.MicaBackdrop):
            if shiboken6.isValid(b):
                shiboken6.delete(b)
    QApplication.processEvents()


def make_main(qtbot):
    from teleport.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    return window


def running(window) -> None:
    # Thư mục ngắn: điểm giữa `save_bar` là nền (như L4).
    window.show_running("May-A", Path("C:/T"))
    settle()


def show(window, qtbot, size: tuple[int, int] = WIDE) -> None:
    window.resize(*size)
    window.show()
    qtbot.waitExposed(window)
    settle()


def hwnd_of(window) -> int:
    assert window.testAttribute(Qt.WidgetAttribute.WA_WState_Created), "tiền đề: cửa sổ đã có HWND"
    return int(window.winId())


def snapshot(window):
    from teleport.ui import motion

    motion.finish_all()
    settle()
    return window.grab().toImage()


def pixel(image, widget, window, point: QPoint) -> QColor:
    p = widget.mapTo(window, point)
    dpr = image.devicePixelRatio()
    return image.pixelColor(round(p.x() * dpr), round(p.y() * dpr))


def window_pixel(image, x: int, y: int) -> QColor:
    dpr = image.devicePixelRatio()
    return image.pixelColor(round(x * dpr), round(y * dpr))


def assert_color(c: QColor, rgb: QColor, alpha: int, what: str) -> None:
    ok = (
        abs(c.red() - rgb.red()) <= TOL
        and abs(c.green() - rgb.green()) <= TOL
        and abs(c.blue() - rgb.blue()) <= TOL
        and abs(c.alpha() - alpha) <= TOL
    )
    assert ok, (
        f"{what}: được rgba({c.red()}, {c.green()}, {c.blue()}, {c.alpha()}), mong "
        f"rgba({rgb.red()}, {rgb.green()}, {rgb.blue()}, {alpha}) ±{TOL}"
    )


def sidebar_gap(window) -> tuple:
    """Điểm trống của cột trái (bên phải nút “＋ Ghép đôi máy mới”, như L4): (widget, QPoint)."""
    conv = window.conversations
    btn = conv.add_button
    gap = QPoint(conv.width() - 4, btn.mapTo(conv, btn.rect().center()).y())
    assert btn.mapTo(conv, QPoint(btn.width(), 0)).x() < gap.x(), "tiền đề: điểm nằm ngoài nút"
    return conv, gap


def region_samples(window, image) -> dict[str, QColor]:
    """Các điểm mẫu của T-5 trên ảnh `image` ở RUNNING."""
    conv, gap = sidebar_gap(window)
    bar = window.save_bar
    edge = window.sidebar.width() - 1
    return {
        "giữa khung phải": pixel(image, window.stream_pane, window, QPoint(8, 8)),
        "đầu cột trái": pixel(image, window.sidebar, window, QPoint(200, 4)),
        "chỗ trống cột trái": pixel(image, conv, window, gap),
        "viền phải cột trái": pixel(
            image, window.sidebar, window, QPoint(edge, window.sidebar.height() // 2)
        ),
        "giữa save_bar": pixel(image, bar, window, QPoint(bar.width() // 2, bar.height() // 2)),
    }


def assert_mica_pixels(window, image, tok) -> None:
    s = region_samples(window, image)
    assert_color(s["giữa khung phải"], tok.surface, 255, "giữa khung phải")
    assert_color(s["đầu cột trái"], tok.sidebar, MICA_TINT_ALPHA, "đầu cột trái")
    assert_color(s["chỗ trống cột trái"], tok.sidebar, MICA_TINT_ALPHA, "chỗ trống cột trái")
    assert_color(s["viền phải cột trái"], tok.border, 255, "viền phải cột trái")
    assert_color(s["giữa save_bar"], tok.sidebar, 255, "giữa save_bar (mục 9 ý 1)")


def assert_solid_pixels(window, image, tok) -> None:
    s = region_samples(window, image)
    assert_color(s["giữa khung phải"], tok.surface, 255, "giữa khung phải")
    assert_color(s["đầu cột trái"], tok.sidebar, 255, "đầu cột trái")
    assert_color(s["chỗ trống cột trái"], tok.sidebar, 255, "chỗ trống cột trái")
    assert_color(s["viền phải cột trái"], tok.border, 255, "viền phải cột trái")
    assert_color(s["giữa save_bar"], tok.sidebar, 255, "giữa save_bar")


def find_watcher(backdrop):
    """Singleton `_SettingsWatcher` mà module giữ ở biến cấp module (mục 9 ý 7)."""
    found = [v for v in vars(backdrop).values() if isinstance(v, backdrop._SettingsWatcher)]
    assert len(found) == 1, f"module phải giữ đúng một `_SettingsWatcher`, thấy {len(found)}"
    return found[0]


def native_msg(backdrop, message: int):
    """MSG Windows giả trong bộ nhớ (cấu trúc `_MSG` của module); trả (đối tượng giữ bộ nhớ, địa chỉ)."""
    msg = backdrop._MSG()
    msg.message = message
    return msg, ctypes.addressof(msg)


def send_native(watcher, event_type: bytes, message: int, backdrop):
    keep, address = native_msg(backdrop, message)
    result = watcher.nativeEventFilter(QByteArray(event_type), address)
    del keep
    return result


# =================================================================================================
# Fixture
# =================================================================================================


class MicaEnv:
    """Môi trường giả của `mica_env`: trạng thái seam đọc lúc gọi (đổi được giữa test) và spy DWM.

    `calls`: `(tên, hwnd, giá trị)` với tên `set_dark` / `extend` / `set_backdrop`; `results`: HRESULT
    mỗi hàm trả; `glass`: đặt thì mỗi lời gọi DWM ghi thêm property `backdrop` của kính lúc gọi vào
    `props` (kiểm thứ tự property ↔ DWM, mục 9 ý 5).
    """

    def __init__(self, build, hc, transparency, platform) -> None:
        self.build = build
        self.hc = hc
        self.transparency = transparency
        self.platform = platform
        self.calls: list[tuple[str, int, object]] = []
        self.props: list[tuple[str, object, object]] = []
        self.results: dict[str, int] = {"set_dark": 0, "extend": 0, "set_backdrop": 0}
        self.glass = None

    def dwm(self, name: str):
        def call(hwnd, value):
            v = bool(value) if name == "set_dark" else int(value)
            self.calls.append((name, int(hwnd), v))
            if self.glass is not None:
                self.props.append((name, v, self.glass.property("backdrop")))
            return self.results[name]

        return call


def _install_dwm_spy(monkeypatch, backdrop, env: MicaEnv) -> None:
    monkeypatch.setattr(backdrop, "_dwm_set_dark", env.dwm("set_dark"))
    monkeypatch.setattr(backdrop, "_dwm_extend_frame", env.dwm("extend"))
    monkeypatch.setattr(backdrop, "_dwm_set_backdrop", env.dwm("set_backdrop"))


@pytest.fixture
def mica_env(monkeypatch):
    """`mica_env(build=22621, hc=False, transparency=True, platform="windows") -> MicaEnv` (spec mục 4).

    Gọi **trước** khi dựng cửa sổ. Teardown: `backdrop._reset_for_tests()`.
    """
    from teleport.ui import backdrop

    destroy_stale_windows()

    def make(build=MICA_MIN_BUILD, hc=False, transparency=True, platform="windows") -> MicaEnv:
        env = MicaEnv(build, hc, transparency, platform)
        monkeypatch.setattr(backdrop, "_qt_platform", lambda: env.platform)
        monkeypatch.setattr(backdrop, "_windows_build", lambda: env.build)
        monkeypatch.setattr(backdrop, "_high_contrast", lambda: env.hc)
        monkeypatch.setattr(backdrop, "_transparency_enabled", lambda: env.transparency)
        _install_dwm_spy(monkeypatch, backdrop, env)
        return env

    yield make
    detach_backdrops(backdrop)
    backdrop._reset_for_tests()


@pytest.fixture
def dwm_spy(monkeypatch) -> MicaEnv:
    """Chỉ thay ba hàm DWM bằng spy; nền, build, cài đặt để nguyên (T-3: offscreen thật)."""
    from teleport.ui import backdrop

    destroy_stale_windows()
    env = MicaEnv(None, False, True, None)
    _install_dwm_spy(monkeypatch, backdrop, env)
    return env


@pytest.fixture
def refresh_counter(monkeypatch):
    """Đếm lời gọi `MicaBackdrop.refresh` (vẫn chạy bản thật)."""
    from teleport.ui import backdrop

    counter = SimpleNamespace(n=0)
    real = backdrop.MicaBackdrop.refresh

    def counted(self, *args, **kwargs):
        counter.n += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(backdrop.MicaBackdrop, "refresh", counted)
    return counter


# =================================================================================================
# API, hằng
# =================================================================================================


def test_public_constants_and_enums_match_spec():
    from teleport.ui import backdrop

    assert backdrop.MICA_MIN_BUILD == MICA_MIN_BUILD
    assert backdrop.DWMWA_USE_IMMERSIVE_DARK_MODE == DWMWA_USE_IMMERSIVE_DARK_MODE
    assert backdrop.DWMWA_SYSTEMBACKDROP_TYPE == DWMWA_SYSTEMBACKDROP_TYPE
    assert (backdrop.DWMSBT_NONE, backdrop.DWMSBT_MAINWINDOW) == (DWMSBT_NONE, DWMSBT_MAINWINDOW)
    assert (backdrop.WM_SETTINGCHANGE, backdrop.WM_THEMECHANGED, backdrop.WM_DWMCOMPOSITIONCHANGED) == (
        WM_SETTINGCHANGE,
        WM_THEMECHANGED,
        WM_DWMCOMPOSITIONCHANGED,
    )
    assert {m.name for m in backdrop.Backdrop} == {"SOLID", "MICA"}
    assert {r.name: r.value for r in backdrop.Reason} == {
        "OK": "ok",
        "PLATFORM": "platform",
        "OLD_BUILD": "old_build",
        "HIGH_CONTRAST": "high_contrast",
        "TRANSPARENCY_OFF": "transparency_off",
        "DWM_ERROR": "dwm_error",
        "CREATED": "created",
    }
    assert isinstance(backdrop.Reason.OK, str)  # StrEnum


def test_decision_is_frozen_value_object():
    from teleport.ui import backdrop

    d = backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    assert d == backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    with pytest.raises(AttributeError):
        d.reason = backdrop.Reason.PLATFORM  # type: ignore[misc]


# =================================================================================================
# T-1 — decide / capable
# =================================================================================================


def _expected(platform: str, build: int | None, hc: bool, transparency: bool) -> tuple[str, str]:
    """Bảng của spec mục 2.1: (backdrop, reason) theo đúng thứ tự lý do."""
    if platform != "windows":
        return "SOLID", "PLATFORM"
    if build is None or build < MICA_MIN_BUILD:
        return "SOLID", "OLD_BUILD"
    if hc:
        return "SOLID", "HIGH_CONTRAST"
    if not transparency:
        return "SOLID", "TRANSPARENCY_OFF"
    return "MICA", "OK"


T1_CASES = [
    # (platform, build, hc, transparency, reason)
    ("offscreen", 26300, False, True, "PLATFORM"),
    ("offscreen", None, True, False, "PLATFORM"),  # nền thắng mọi lý do khác
    ("xcb", 26300, False, True, "PLATFORM"),
    ("cocoa", 26300, False, True, "PLATFORM"),
    ("wayland", 26300, False, True, "PLATFORM"),
    ("Windows", 26300, False, True, "PLATFORM"),  # đúng chuỗi "windows"
    ("windows", None, False, True, "OLD_BUILD"),
    ("windows", 19045, False, True, "OLD_BUILD"),  # Windows 10
    ("windows", 22000, False, True, "OLD_BUILD"),  # Windows 11 21H2
    ("windows", 22620, False, True, "OLD_BUILD"),  # sát dưới ngưỡng 1
    ("windows", 22000, True, False, "OLD_BUILD"),  # build thắng tương phản cao, tắt trong suốt
    ("windows", 22621, True, False, "HIGH_CONTRAST"),  # tương phản cao thắng tắt trong suốt
    ("windows", 22621, True, True, "HIGH_CONTRAST"),
    ("windows", 22621, False, False, "TRANSPARENCY_OFF"),
    ("windows", 22621, False, True, "OK"),  # đúng ngưỡng
    ("windows", 26300, False, True, "OK"),
]


@pytest.mark.parametrize(("platform", "build", "hc", "transparency", "reason"), T1_CASES)
def test_t1_decide_follows_reason_order(platform, build, hc, transparency, reason):
    from teleport.ui import backdrop

    d = backdrop.decide(qt_platform=platform, build=build, high_contrast=hc, transparency=transparency)
    want = backdrop.Backdrop.MICA if reason == "OK" else backdrop.Backdrop.SOLID
    assert d == backdrop.Decision(want, backdrop.Reason[reason])


@pytest.mark.parametrize(
    ("platform", "build", "capable"),
    [
        ("offscreen", 26300, False),
        ("xcb", 26300, False),
        ("windows", None, False),
        ("windows", 19045, False),
        ("windows", 22000, False),
        ("windows", 22620, False),
        ("windows", 22621, True),
        ("windows", 26300, True),
    ],
)
def test_t1_capable_only_checks_platform_and_build(platform, build, capable):
    from teleport.ui import backdrop

    assert backdrop.capable(qt_platform=platform, build=build) is capable


@given(
    platform=st.sampled_from(["windows", "offscreen", "xcb", "cocoa", "wayland", "minimal", ""]),
    build=st.one_of(st.none(), st.integers(min_value=0, max_value=40000)),
    hc=st.booleans(),
    transparency=st.booleans(),
)
def test_t1_decide_matches_spec_table_for_any_input(platform, build, hc, transparency):
    from teleport.ui import backdrop

    d = backdrop.decide(qt_platform=platform, build=build, high_contrast=hc, transparency=transparency)
    kind, reason = _expected(platform, build, hc, transparency)
    assert (d.backdrop.name, d.reason.name) == (kind, reason)
    # `capable` chỉ xét (1)(2): đúng khi và chỉ khi lý do không phải PLATFORM/OLD_BUILD.
    assert backdrop.capable(qt_platform=platform, build=build) is (reason not in ("PLATFORM", "OLD_BUILD"))


# =================================================================================================
# T-2 — current_decision không ném; seam thật rơi về đúng giá trị
# =================================================================================================


def _raise(error: BaseException):
    def f():
        raise error

    return f


@pytest.mark.parametrize(
    ("seam", "error", "reason"),
    [
        ("_windows_build", OSError("build"), "OLD_BUILD"),
        ("_windows_build", AttributeError("getwindowsversion"), "OLD_BUILD"),
        ("_high_contrast", OSError("SPI"), "HIGH_CONTRAST"),
        ("_transparency_enabled", FileNotFoundError("EnableTransparency"), "OK"),
        ("_transparency_enabled", PermissionError("HKCU"), "TRANSPARENCY_OFF"),
        ("_transparency_enabled", OSError("khác"), "TRANSPARENCY_OFF"),
    ],
)
def test_t2_current_decision_never_raises(mica_env, monkeypatch, seam, error, reason):
    from teleport.ui import backdrop

    mica_env(build=26300)
    monkeypatch.setattr(backdrop, seam, _raise(error))
    d = backdrop.current_decision()
    want = backdrop.Backdrop.MICA if reason == "OK" else backdrop.Backdrop.SOLID
    assert d == backdrop.Decision(want, backdrop.Reason[reason])


def test_t2_current_decision_reads_seams_at_call_time(mica_env):
    from teleport.ui import backdrop

    env = mica_env(build=26300)
    assert backdrop.current_decision().reason is backdrop.Reason.OK
    env.transparency = False
    assert backdrop.current_decision().reason is backdrop.Reason.TRANSPARENCY_OFF
    env.hc = True
    assert backdrop.current_decision().reason is backdrop.Reason.HIGH_CONTRAST
    env.build = 22000
    assert backdrop.current_decision().reason is backdrop.Reason.OLD_BUILD
    env.platform = "offscreen"
    assert backdrop.current_decision().reason is backdrop.Reason.PLATFORM


def test_t2_qt_platform_seam_is_platform_name(qapp):
    from teleport.ui import backdrop

    assert backdrop._qt_platform() == qapp.platformName() == "offscreen"


def test_t2_windows_build_reads_platform_version_not_build(monkeypatch):
    """Mục 9 ý 16: `platform_version[2]` (build thật), không phải `.build` (bị app-compat nói dối)."""
    from teleport.ui import backdrop

    fake = SimpleNamespace(major=10, minor=0, build=19041, platform_version=(10, 0, 26300))
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "getwindowsversion", lambda: fake, raising=False)
    assert backdrop._windows_build() == 26300


def test_t2_windows_build_error_gives_old_build(monkeypatch):
    """Bảng seam: `_windows_build` lỗi → None. Spec không nói fallback nằm trong seam hay trong
    `current_decision`, nên kiểm qua `current_decision` với seam build **thật**: ra OLD_BUILD, không ném."""
    from teleport.ui import backdrop

    monkeypatch.setattr(backdrop, "_qt_platform", lambda: "windows")
    monkeypatch.setattr(backdrop, "_high_contrast", lambda: False)
    monkeypatch.setattr(backdrop, "_transparency_enabled", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "getwindowsversion", _raise(OSError("lỗi")), raising=False)
    assert backdrop.current_decision() == backdrop.Decision(
        backdrop.Backdrop.SOLID, backdrop.Reason.OLD_BUILD
    )


def test_t2_windows_build_outside_win32_gives_none(monkeypatch):
    from teleport.ui import backdrop

    monkeypatch.setattr(sys, "platform", "linux")
    # Có gọi nhầm cũng không ra số: build thật của máy test không được lọt ra.
    monkeypatch.setattr(sys, "getwindowsversion", _raise(AttributeError("không có")), raising=False)
    assert backdrop._windows_build() is None


class FakeWinreg:
    """`winreg` giả: không bao giờ chạm registry thật. `value` hay `error` (ném ở `OpenKey`)."""

    HKEY_CURRENT_USER = object()
    KEY_READ = 0x20019
    KEY_QUERY_VALUE = 0x0001
    KEY_WRITE = 0x20006
    KEY_ALL_ACCESS = 0xF003F
    KEY_SET_VALUE = 0x0002
    REG_DWORD = 4

    def __init__(self, value=1, error: BaseException | None = None, query_error=None) -> None:
        self.value = value
        self.error = error
        self.query_error = query_error
        self.opened: list[tuple] = []
        self.queried: list[str] = []
        self.wrote = False

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def Close(self):
            pass

    def OpenKey(self, key, sub_key, reserved=0, access=0x20019):
        self.opened.append((key, sub_key, access))
        if self.error is not None:
            raise self.error
        return self._Key()

    OpenKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        self.queried.append(name)
        if self.query_error is not None:
            raise self.query_error
        return (self.value, self.REG_DWORD)

    def CloseKey(self, key):
        pass

    def SetValueEx(self, *args):
        self.wrote = True

    def CreateKey(self, *args):
        self.wrote = True
        return self._Key()

    CreateKeyEx = CreateKey


def _patch_winreg(monkeypatch, fake: FakeWinreg) -> None:
    from teleport.ui import backdrop

    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(backdrop, "winreg", fake, raising=False)


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"value": 1}, "OK"),
        ({"value": 0}, "TRANSPARENCY_OFF"),
        ({"error": FileNotFoundError("không có khóa")}, "OK"),
        ({"query_error": FileNotFoundError("không có giá trị")}, "OK"),
        ({"error": PermissionError("cấm")}, "TRANSPARENCY_OFF"),
        ({"query_error": OSError("lỗi khác")}, "TRANSPARENCY_OFF"),
    ],
    ids=["bat", "tat", "khong-co-khoa", "khong-co-gia-tri", "cam", "loi-khac"],
)
def test_t2_transparency_seam_reads_hkcu_personalize_read_only(monkeypatch, kwargs, reason):
    """Bảng seam: `FileNotFoundError` → True, lỗi khác → False. Kiểm qua `current_decision` với seam
    trong suốt **thật** và `winreg` giả (spec không nói fallback nằm ở seam hay ở `current_decision`)."""
    from teleport.ui import backdrop

    fake = FakeWinreg(**kwargs)
    monkeypatch.setattr(sys, "platform", "win32")
    _patch_winreg(monkeypatch, fake)
    monkeypatch.setattr(backdrop, "_qt_platform", lambda: "windows")
    monkeypatch.setattr(backdrop, "_windows_build", lambda: 26300)
    monkeypatch.setattr(backdrop, "_high_contrast", lambda: False)
    want = backdrop.Backdrop.MICA if reason == "OK" else backdrop.Backdrop.SOLID
    assert backdrop.current_decision() == backdrop.Decision(want, backdrop.Reason[reason])
    assert fake.opened, "seam phải đọc qua `winreg` (giả), không chạm registry thật"
    key, sub_key, access = fake.opened[0]
    assert key is FakeWinreg.HKEY_CURRENT_USER
    assert sub_key.replace("/", "\\").lower().endswith(r"themes\personalize")
    assert not access & (FakeWinreg.KEY_SET_VALUE | 0x0004), "chỉ đọc (spec mục 2.1)"
    assert not fake.wrote
    if fake.error is None:
        assert fake.queried == ["EnableTransparency"]


# =================================================================================================
# T-3 — không vá nền (offscreen thật): không làm gì
# =================================================================================================


def test_t3_unpatched_offscreen_window_does_nothing(qtbot, dwm_spy, ui_theme):
    from teleport.ui import backdrop, theme

    tok = ui_theme(False)
    window = make_main(qtbot)
    assert isinstance(window.backdrop, backdrop.MicaBackdrop)
    assert window.backdrop.parent() is window, "MicaBackdrop là con của window"
    running(window)
    show(window, qtbot)
    window.backdrop.refresh()
    settle()

    assert window.backdrop.decision.reason is backdrop.Reason.PLATFORM
    assert window.backdrop.decision.backdrop is backdrop.Backdrop.SOLID
    assert window.backdrop.active is False
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) is None
    assert dwm_spy.calls == []
    assert_solid_pixels(window, snapshot(window), tok)


def test_t3_decision_and_active_are_read_only(qtbot, dwm_spy):
    from teleport.ui import backdrop

    window = make_main(qtbot)
    with pytest.raises(AttributeError):
        window.backdrop.decision = backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    with pytest.raises(AttributeError):
        window.backdrop.active = True


# =================================================================================================
# T-4 — bật Mica: thứ tự DWM, HWND, property
# =================================================================================================


def test_t4_does_not_force_hwnd_creation(qtbot, mica_env):
    """Mục 2.1: không bao giờ gọi `winId()` để ép tạo HWND; chưa show thì chưa gọi DWM."""
    env = mica_env()
    window = make_main(qtbot)
    settle()
    assert not window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert env.calls == []


def test_t4_show_applies_mica_in_order_on_right_hwnd(qtbot, mica_env, ui_theme):
    from teleport.ui import backdrop, theme

    ui_theme(False)
    env = mica_env()
    window = make_main(qtbot)
    env.glass = window.sidebar
    running(window)
    show(window, qtbot)
    h = hwnd_of(window)

    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert env.calls == [("set_dark", h, False), ("extend", h, -1), ("set_backdrop", h, DWMSBT_MAINWINDOW)]
    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    assert window.backdrop.active is True
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) == "mica"
    # Mục 9 ý 5: SOLID → MICA gọi DWM trước, đặt property sau.
    assert all(prop != "mica" for _, _, prop in env.props)


def test_t4_does_not_reapply_on_same_hwnd(qtbot, mica_env, ui_theme):
    """Mục 9 ý 6: áp theo HWND mới, không áp lặp cùng HWND (ẩn/hiện, `refresh` không đổi)."""
    ui_theme(False)
    env = mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    env.calls.clear()
    window.hide()
    settle()
    window.show()
    qtbot.waitExposed(window)
    settle()
    window.update()
    settle()
    assert env.calls == []
    assert window.backdrop.active is True


# =================================================================================================
# T-5 — pixel ở RUNNING
# =================================================================================================


@pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
def test_t5_running_pixels_with_mica(qtbot, mica_env, ui_theme, dark):
    tok = ui_theme(dark)
    mica_env()
    window = make_main(qtbot)
    running(window)
    window.set_addresses(["192.0.2.5"], None)
    show(window, qtbot)
    assert window.backdrop.active
    assert_mica_pixels(window, snapshot(window), tok)


# =================================================================================================
# T-6 — tắt trong suốt / tương phản cao: nền đặc, không DWM
# =================================================================================================


@pytest.mark.parametrize(
    ("setting", "reason"),
    [({"transparency": False}, "TRANSPARENCY_OFF"), ({"hc": True}, "HIGH_CONTRAST")],
    ids=["tat-trong-suot", "tuong-phan-cao"],
)
@pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
def test_t6_setting_off_keeps_solid_without_dwm(qtbot, mica_env, ui_theme, setting, reason, dark):
    from teleport.ui import backdrop, theme

    tok = ui_theme(dark)
    env = mica_env(**setting)
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)

    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.SOLID, backdrop.Reason[reason])
    assert window.backdrop.active is False
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) is None
    assert env.calls == []
    assert_solid_pixels(window, snapshot(window), tok)


# =================================================================================================
# T-7 — đổi lúc chạy
# =================================================================================================


def test_t7_runtime_toggle_mica_solid_mica(qtbot, mica_env, ui_theme):
    from teleport.ui import backdrop, theme

    tok = ui_theme(False)
    env = mica_env()
    window = make_main(qtbot)
    env.glass = window.sidebar
    running(window)
    show(window, qtbot)
    h = hwnd_of(window)
    assert window.backdrop.active

    # refresh không đổi gì: không gọi DWM.
    env.calls.clear()
    env.props.clear()
    window.backdrop.refresh()
    settle()
    assert env.calls == []

    # MICA → SOLID.
    env.transparency = False
    window.backdrop.refresh()
    settle()
    assert env.calls == [("extend", h, 0), ("set_backdrop", h, DWMSBT_NONE)]
    # Mục 9 ý 5: gỡ property (và vẽ lại) trước khi gọi DWM.
    assert all(prop is None for _, _, prop in env.props), env.props
    assert window.backdrop.decision == backdrop.Decision(
        backdrop.Backdrop.SOLID, backdrop.Reason.TRANSPARENCY_OFF
    )
    assert window.backdrop.active is False
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) is None
    assert_solid_pixels(window, snapshot(window), tok)

    env.calls.clear()
    window.backdrop.refresh()
    settle()
    assert env.calls == [], "SOLID không đổi: không gọi DWM"

    # SOLID → MICA.
    env.props.clear()
    env.transparency = True
    window.backdrop.refresh()
    settle()
    assert env.calls == [("set_dark", h, False), ("extend", h, -1), ("set_backdrop", h, DWMSBT_MAINWINDOW)]
    assert all(prop != "mica" for _, _, prop in env.props), "DWM trước, property sau"
    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    assert window.backdrop.active is True
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) == "mica"
    assert_mica_pixels(window, snapshot(window), tok)


def test_t7_refresh_never_raises_even_when_seams_fail(qtbot, mica_env, monkeypatch, ui_theme):
    from teleport.ui import backdrop

    ui_theme(False)
    mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    monkeypatch.setattr(backdrop, "_high_contrast", _raise(OSError("SPI hỏng")))
    window.backdrop.refresh()
    settle()
    assert window.backdrop.decision.reason is backdrop.Reason.HIGH_CONTRAST
    assert window.backdrop.active is False


# =================================================================================================
# T-8 — DWM trả HRESULT âm
# =================================================================================================


@pytest.mark.parametrize("failing", ["set_backdrop", "extend"])
def test_t8_dwm_error_falls_back_to_solid_then_recovers(qtbot, mica_env, ui_theme, caplog, failing):
    import logging

    from teleport.ui import backdrop, theme

    tok = ui_theme(False)
    env = mica_env()
    env.results[failing] = E_FAIL
    window = make_main(qtbot)
    running(window)
    with caplog.at_level(logging.DEBUG):
        show(window, qtbot)  # không ném
    h = hwnd_of(window)

    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.SOLID, backdrop.Reason.DWM_ERROR)
    assert window.backdrop.active is False
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) is None
    # Hoàn tác (mục 2.1): `extend 0`, `backdrop 1` sau lời gọi hỏng.
    failed_at = next(i for i, c in enumerate(env.calls) if c[0] == failing)
    after = env.calls[failed_at + 1 :]
    assert ("extend", h, 0) in after, env.calls
    assert ("set_backdrop", h, DWMSBT_NONE) in after, env.calls
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "backdrop" in r.name]
    assert len(warnings) == 1, [r.getMessage() for r in warnings]
    assert_solid_pixels(window, snapshot(window), tok)

    # DWM hết lỗi: `refresh` bật lại Mica.
    env.results[failing] = 0
    env.calls.clear()
    window.backdrop.refresh()
    settle()
    assert env.calls == [("set_dark", h, False), ("extend", h, -1), ("set_backdrop", h, DWMSBT_MAINWINDOW)]
    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    assert window.backdrop.active is True
    assert window.sidebar.property(theme.BACKDROP_PROPERTY) == "mica"
    assert_mica_pixels(window, snapshot(window), tok)


# =================================================================================================
# T-9 — bộ lọc native
# =================================================================================================


def test_t9_native_filter_coalesces_and_filters(qtbot, mica_env, refresh_counter):
    from teleport.ui import backdrop

    mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    settle()
    watcher = find_watcher(backdrop)
    assert isinstance(watcher, backdrop._SettingsWatcher)
    refresh_counter.n = 0

    # Ba WM_SETTINGCHANGE trong một vòng → đúng một refresh, và không refresh ngay trong bộ lọc.
    for _ in range(3):
        assert send_native(watcher, b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop) == (False, 0)
    assert refresh_counter.n == 0, "không refresh đồng bộ trong bộ lọc native"
    settle()
    assert refresh_counter.n == 1

    # Vòng sau lại kích hoạt được (cờ chờ đã xóa).
    assert send_native(watcher, b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop) == (False, 0)
    settle()
    assert refresh_counter.n == 2

    # Message khác: không.
    assert send_native(watcher, b"windows_generic_MSG", WM_MOUSEMOVE, backdrop) == (False, 0)
    settle()
    assert refresh_counter.n == 2

    # event_type khác: không (kể cả message trùng mã).
    for other in (b"windows_dispatcher_MSG", b"xcb_generic_event_t", b"mac_generic_NSEvent"):
        assert send_native(watcher, other, WM_SETTINGCHANGE, backdrop) == (False, 0)
    settle()
    assert refresh_counter.n == 2

    # WM_THEMECHANGED, WM_DWMCOMPOSITIONCHANGED: có.
    assert send_native(watcher, b"windows_generic_MSG", WM_THEMECHANGED, backdrop) == (False, 0)
    settle()
    assert refresh_counter.n == 3
    assert send_native(watcher, b"windows_generic_MSG", WM_DWMCOMPOSITIONCHANGED, backdrop) == (False, 0)
    settle()
    assert refresh_counter.n == 4


def test_t9_native_filter_calls_no_dwm_or_seam_itself(qtbot, mica_env, monkeypatch):
    """Mục 2.1: không DWM/registry trong bộ lọc (chỉ hẹn `refresh` qua vòng sự kiện)."""
    from teleport.ui import backdrop

    env = mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    watcher = find_watcher(backdrop)
    env.calls.clear()
    touched: list[str] = []

    def recorder(seam: str, value):
        def f():
            touched.append(seam)
            return value

        return f

    monkeypatch.setattr(backdrop, "_windows_build", recorder("_windows_build", env.build))
    monkeypatch.setattr(backdrop, "_high_contrast", recorder("_high_contrast", False))
    monkeypatch.setattr(backdrop, "_transparency_enabled", recorder("_transparency_enabled", True))
    send_native(watcher, b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop)
    assert touched == [] and env.calls == []


def test_t9_native_filter_swallows_garbage(qtbot, mica_env):
    """Mục 9 ý 7: toàn thân trong try/except, luôn trả (False, 0) — kể cả message không phải số."""
    from teleport.ui import backdrop

    mica_env()
    window = make_main(qtbot)
    running(window)
    watcher = find_watcher(backdrop)
    assert watcher.nativeEventFilter(QByteArray(b"windows_generic_MSG"), "không phải địa chỉ") == (False, 0)


def test_t9_settings_change_reaches_backdrop_end_to_end(qtbot, mica_env):
    """WM_SETTINGCHANGE sau khi người dùng tắt trong suốt → cột trái về nền đặc (không timer, không poll)."""
    from teleport.ui import backdrop

    env = mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    assert window.backdrop.active
    env.transparency = False
    send_native(find_watcher(backdrop), b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop)
    settle()
    assert window.backdrop.decision.reason is backdrop.Reason.TRANSPARENCY_OFF
    assert window.backdrop.active is False


# =================================================================================================
# T-10 — đổi chế độ màu khi đang Mica
# =================================================================================================


def test_t10_palette_change_updates_dark_flag_and_tint(qtbot, mica_env, ui_theme):
    from teleport.ui import backdrop

    ui_theme(False)
    env = mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    h = hwnd_of(window)
    assert window.backdrop.active
    env.calls.clear()

    dark = ui_theme(True)
    settle()
    assert env.calls == [("set_dark", h, True)], "chỉ gọi lại `_dwm_set_dark` (mục 2.1)"
    assert window.backdrop.decision == backdrop.Decision(backdrop.Backdrop.MICA, backdrop.Reason.OK)
    assert_mica_pixels(window, snapshot(window), dark)

    env.calls.clear()
    light = ui_theme(False)
    settle()
    assert env.calls == [("set_dark", h, False)]
    assert_mica_pixels(window, snapshot(window), light)


def test_t10_palette_change_when_solid_calls_no_dwm(qtbot, mica_env, ui_theme):
    ui_theme(False)
    env = mica_env(transparency=False)
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    ui_theme(True)
    settle()
    assert env.calls == []


# =================================================================================================
# T-11 — kính ẩn / đổi cỡ
# =================================================================================================


def self_painted_at(window, point: QPoint) -> bool:
    """Điểm `point` (tọa độ cửa sổ) nằm trong một widget của app tự vẽ (`paintEvent` viết trong
    `teleport.*`, ví dụ RadarCanvas): màu ở đó là nội dung của widget, không phải nền cửa sổ. Tính động
    từ cây widget lúc chụp, không ghim tọa độ của từng trang. (`autoFillBackground` không tính: nó tô
    `Window` của palette, tức chính `surface`.)"""
    w = window.childAt(point)
    while w is not None and w is not window:
        for cls in type(w).__mro__:
            if "paintEvent" in vars(cls):
                if cls.__module__.startswith("teleport."):
                    return True
                break
        w = w.parentWidget()
    return False


def _old_sidebar_points(window) -> list[tuple[int, int]]:
    origin = window.sidebar.mapTo(window, QPoint(0, 0))
    return [(origin.x() + x, origin.y() + y) for x, y in OLD_SIDEBAR_POINTS]


@pytest.mark.parametrize("state", ["starting", "welcome", "discover"])
@pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
def test_t11_hidden_glass_leaves_no_transparent_area(qtbot, mica_env, ui_theme, state, dark):
    from teleport.ui.main_window import Page

    tok = ui_theme(dark)
    mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    assert window.backdrop.active
    points = _old_sidebar_points(window)

    if state == "starting":
        window.show_starting()
    elif state == "welcome":
        window.show_welcome("Laptop-Minh")
    else:
        assert window.open_page(Page.DISCOVER)
    settle()
    assert not window.sidebar.isVisible(), "tiền đề: kính đã ẩn"
    image = snapshot(window)
    color_checked = 0
    for x, y in points:
        px = window_pixel(image, x, y)
        where = f"{state}: cột trái cũ tại ({x}, {y})"
        if self_painted_at(window, QPoint(x, y)):
            # Widget tự vẽ nền (ví dụ RadarCanvas của Discover): màu là nội dung của nó, chỉ cần kín.
            assert px.alpha() == 255, f"{where}: alpha {px.alpha()} (lộ vùng trong suốt)"
        else:
            assert_color(px, tok.surface, 255, where)
            color_checked += 1
    # Discover: phần lớn điểm rơi vào PageHeader/RadarCanvas (tự vẽ); vẫn phải còn điểm nền trống.
    assert color_checked >= 2, "tiền đề: đủ điểm nền trống để kiểm màu `surface`"


def test_t11_back_to_running_restores_glass(qtbot, mica_env, ui_theme):
    from teleport.ui.main_window import Page

    tok = ui_theme(False)
    mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    assert window.open_page(Page.DISCOVER)
    settle()
    assert window.go_back()
    settle()
    assert_mica_pixels(window, snapshot(window), tok)


@pytest.mark.parametrize("dark", [False, True], ids=["sang", "toi"])
def test_t11_compact_sidebar_resize_keeps_right_side_opaque(qtbot, mica_env, ui_theme, dark):
    tok = ui_theme(dark)
    mica_env()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot, WIDE)
    wide_point = window.sidebar.mapTo(window, QPoint(200, 8))  # trong cột rộng, ngoài cột thu gọn

    window.resize(*COMPACT)
    settle()
    assert window.sidebar_compact, "tiền đề: cột trái thu gọn"
    image = snapshot(window)
    sb = window.sidebar
    right = sb.mapTo(window, QPoint(sb.width() + 4, 8))
    assert_color(window_pixel(image, right.x(), right.y()), tok.surface, 255, "ngay phải cột thu gọn")
    assert_color(window_pixel(image, wide_point.x(), wide_point.y()), tok.surface, 255, "chỗ cột rộng cũ")
    inside = sb.mapTo(window, QPoint(2, sb.height() // 2))
    assert_color(
        window_pixel(image, inside.x(), inside.y()), tok.sidebar, MICA_TINT_ALPHA, "trong cột thu gọn"
    )

    # Mở rộng lại: chỗ cũ lại bán trong suốt.
    window.resize(*WIDE)
    settle()
    assert not window.sidebar_compact
    assert_mica_pixels(window, snapshot(window), tok)


# =================================================================================================
# T-14 — cửa sổ đã có HWND trước khi gắn
# =================================================================================================


def test_t14_window_with_hwnd_gets_created_reason_and_nothing_else(qtbot, mica_env):
    from teleport.ui import backdrop, theme

    env = mica_env()
    window = QMainWindow()
    qtbot.addWidget(window)
    glass = QFrame()
    glass.setProperty(theme.SURFACE_PROPERTY, "sidebar")
    window.setCentralWidget(glass)
    window.winId()
    assert window.testAttribute(Qt.WidgetAttribute.WA_WState_Created)

    mb = backdrop.MicaBackdrop(window, glass)
    assert mb.decision == backdrop.Decision(backdrop.Backdrop.SOLID, backdrop.Reason.CREATED)
    assert mb.active is False
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.resize(300, 200)
    window.show()
    qtbot.waitExposed(window)
    mb.refresh()
    settle()
    assert env.calls == []
    assert glass.property(theme.BACKDROP_PROPERTY) is None
    assert mb.decision.reason is backdrop.Reason.CREATED


def test_t14_platform_not_capable_on_plain_window(qtbot, mica_env):
    """`capable` sai (Windows 10): không đặt translucent dù cửa sổ chưa có HWND."""
    from teleport.ui import backdrop

    env = mica_env(build=19045)
    window = QMainWindow()
    qtbot.addWidget(window)
    glass = QFrame()
    window.setCentralWidget(glass)
    mb = backdrop.MicaBackdrop(window, glass)
    assert mb.decision == backdrop.Decision(backdrop.Backdrop.SOLID, backdrop.Reason.OLD_BUILD)
    assert not window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    window.show()
    qtbot.waitExposed(window)
    settle()
    assert env.calls == []


# =================================================================================================
# T-15 — cửa sổ đã hủy; gỡ bộ lọc
# =================================================================================================


def test_t15_destroyed_window_then_settings_change_is_harmless(qtbot, mica_env, ui_helpers):
    from teleport.ui import backdrop
    from teleport.ui.main_window import MainWindow

    env = mica_env()
    window = MainWindow()  # không qua qtbot.addWidget: test tự hủy
    window.show_running("May-A", Path("C:/T"))
    window.resize(*WIDE)
    window.show()
    qtbot.waitExposed(window)
    settle()
    watcher = find_watcher(backdrop)
    mb = window.backdrop
    window.close()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    settle()
    assert not ui_helpers.is_alive(mb)
    env.calls.clear()

    assert send_native(watcher, b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop) == (False, 0)
    settle()  # QTimer.singleShot(0) chạy: không được chạm backdrop đã hủy
    assert env.calls == []


def test_t15_reset_for_tests_removes_native_filter(qtbot, mica_env, monkeypatch, qapp):
    from teleport.ui import backdrop

    installed: list = []
    removed: list = []
    real_install = QCoreApplication.installNativeEventFilter
    real_remove = QCoreApplication.removeNativeEventFilter

    def install(self, f):
        installed.append(f)
        return real_install(self, f)

    def remove(self, f):
        removed.append(f)
        return real_remove(self, f)

    monkeypatch.setattr(QCoreApplication, "installNativeEventFilter", install)
    monkeypatch.setattr(QCoreApplication, "removeNativeEventFilter", remove)

    mica_env()
    window = make_main(qtbot)
    watcher = find_watcher(backdrop)
    assert any(f is watcher for f in installed), "bộ lọc native phải được cài vào ứng dụng"
    backdrop._reset_for_tests()
    assert any(f is watcher for f in removed), "`_reset_for_tests()` phải gỡ bộ lọc native"
    del window


def test_t15_one_watcher_for_many_windows(qtbot, mica_env, refresh_counter):
    """Singleton: hai cửa sổ dùng chung một bộ lọc; một message → mỗi backdrop sống refresh một lần."""
    from teleport.ui import backdrop

    mica_env()
    a = make_main(qtbot)
    b = make_main(qtbot)
    watcher = find_watcher(backdrop)
    refresh_counter.n = 0
    send_native(watcher, b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop)
    settle()
    assert refresh_counter.n == 2
    del a, b


# =================================================================================================
# T-16 — N3: rảnh không thêm tải
# =================================================================================================


def _active_timers(root) -> set[int]:
    return {id(t) for t in root.findChildren(QTimer) if t.isActive()}


def test_t16_no_running_timer_or_animation_from_backdrop(qtbot, mica_env, refresh_counter):
    from teleport.ui import backdrop, motion

    mica_env()
    before_anims = motion.running_count()
    window = make_main(qtbot)
    running(window)
    show(window, qtbot)
    motion.finish_all()
    settle()
    base_anims = motion.running_count()
    base_timers = _active_timers(window)
    assert [t for t in window.backdrop.findChildren(QTimer) if t.isActive()] == []

    window.backdrop.refresh()
    send_native(find_watcher(backdrop), b"windows_generic_MSG", WM_SETTINGCHANGE, backdrop)
    settle()
    assert _active_timers(window) <= base_timers, "G7 không để lại QTimer đang chạy"
    assert [t for t in window.backdrop.findChildren(QTimer) if t.isActive()] == []
    assert motion.running_count() == base_anims == before_anims

    # Không polling: rảnh 300 ms không có refresh nào.
    refresh_counter.n = 0
    qtbot.wait(300)
    assert refresh_counter.n == 0


def test_t16_reset_for_tests_is_idempotent():
    from teleport.ui import backdrop

    backdrop._reset_for_tests()
    backdrop._reset_for_tests()
