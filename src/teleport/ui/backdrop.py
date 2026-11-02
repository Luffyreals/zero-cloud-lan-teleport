"""Nền Mica cho cột trái của cửa sổ chính (Windows 11 ≥ `MICA_MIN_BUILD`; spec G7; mvp N3, N11, N12).

Trên Windows 11 build ≥ 22621, cột trái (`glass`, khung `sidebar` của `ui.main_window`) để lộ chất
liệu Mica của hệ điều hành dưới lớp màu `sidebar` bán trong suốt (`theme.mica_tint`, alpha
`theme.MICA_TINT_ALPHA`). Mọi trường hợp khác rơi về nền đặc, trông y như khi không có module này.
Module chỉ dùng QtCore/QtGui/QtWidgets và `ctypes`; không timer nền, không polling.

**Quyết định** (`decide`, hàm thuần; `Decision(backdrop, reason)`), xét theo thứ tự, lý do đầu tiên khớp
thắng: (1) nền tảng Qt khác `"windows"` → `PLATFORM`; (2) build None hay < `MICA_MIN_BUILD` (Windows 10,
Windows 11 21H2 = 22000) → `OLD_BUILD`; (3) tương phản cao → `HIGH_CONTRAST`; (4) tắt hiệu ứng trong suốt
→ `TRANSPARENCY_OFF`; (5) `MICA` / `OK`. `capable` chỉ xét (1)(2). `current_decision()` đọc các seam
và không bao giờ ném: nền tảng lỗi → `""`; build lỗi → None; khi đã không `capable` thì không đọc tương
phản cao hay sổ đăng ký; tương phản cao lỗi → bật (về nền đặc); `EnableTransparency` không có
(`FileNotFoundError`) → bật trong suốt, lỗi khác → tắt.

**`MicaBackdrop(window, glass)`** (QObject, con của `window`; `ui.main_window` tạo ở cuối `__init__`):
- Gắn: `capable` sai → không làm gì (quyết định `PLATFORM` / `OLD_BUILD`; CI offscreen, Windows 10).
  `window` đã có HWND (`WA_WState_Created`) → `SOLID` / `CREATED`, log debug, không làm gì: đặt
  `WA_TranslucentBackground` sau khi đã tạo cửa sổ native không có tác dụng đúng, và không bao giờ gọi
  `winId()` để ép tạo HWND. Còn lại: đặt `WA_TranslucentBackground`, cài bộ lọc sự kiện lên `window`
  (Paint, Show, WinIdChange, ApplicationPaletteChange) và `glass` (Show, Hide, Move, Resize →
  `window.update()`), đăng ký với bộ theo dõi cài đặt, tính quyết định đầu (`decision` = quyết định
  mong muốn; `active` False tới khi DWM nhận).
- Vẽ (Paint của `window`, chỉ khi đã translucent): tô `theme.tokens_for(window).surface` lên vùng cần vẽ
  trừ hình chữ nhật của `glass` (`QRect(glass.mapTo(window, QPoint(0, 0)), glass.size())`, tính lúc vẽ;
  chỉ trừ khi `active` và `glass.isVisible()`), rồi để `window` vẽ tiếp như thường. Vì vậy mọi vùng
  ngoài cột trái (khung phải, `save_bar`, trang DISCOVER/SETTINGS, khối căn giữa WELCOME/STARTING/ERROR,
  phần cửa sổ ngay phải cột trái thu gọn) luôn đặc; trang khác HOME hay khối căn giữa ẩn `glass` (ẩn
  cha thì `glass.isVisible()` False) nên không cần nghe `page_changed`. Khi translucent mà nền đặc
  (`SOLID`) thì cả cửa sổ được tô kín, cột trái tô `sidebar` đặc bằng luật gốc của stylesheet.
- Áp DWM (`_sync`): ở Show (HWND đã có; áp lần đầu), WinIdChange (dự phòng HWND tạo lại; Qt có gửi hay
  không gửi sự kiện này lúc tạo đầu cũng được, vì chỉ áp khi HWND khác HWND đã áp) và `refresh()`.
  HWND = `int(window.winId())` chỉ khi `WA_WState_Created`. Chỉ gọi DWM khi có HWND và (quyết định đổi
  hoặc HWND mới); `refresh()` không đổi gì thì không gọi DWM.
  - Sang `MICA`: `_dwm_set_dark(hwnd, is_dark_palette(app.palette()))` (gọi dù Qt có thể đã đặt attr
    20; lỗi chỉ log debug, Mica vẫn chạy) → `_dwm_extend_frame(hwnd, -1)` → `_dwm_set_backdrop(hwnd,
    DWMSBT_MAINWINDOW)`. Bước extend hay backdrop trả HRESULT < 0 (hay ném) → dừng, hoàn tác (`extend
    0`, `backdrop DWMSBT_NONE`), quyết định `SOLID` / `DWM_ERROR`, log warning một lần cho mỗi
    backdrop; giữ vậy tới lần `refresh()` sau hoặc HWND mới (lần đó thử lại; Show không thử lại).
    Thành công: `active` True, đặt `theme.BACKDROP_PROPERTY = "mica"` lên `glass`, unpolish/polish,
    `window.update()`. DWM trước, property sau.
  - Sang `SOLID`: gỡ property, polish lại, `window.repaint()` (đồng bộ: cột trái đặc trước khi DWM
    tắt Mica, không nháy vùng trong suốt) rồi, nếu HWND đang Mica, `extend 0` + `backdrop
    DWMSBT_NONE`. Property trước, DWM sau.
  - ApplicationPaletteChange khi đang Mica: chỉ gọi lại `_dwm_set_dark` (tông Mica theo chế độ sáng/tối
    của app, kể cả khi người dùng ép khác hệ điều hành) và `window.update()`.
- `refresh()`: đọc lại `current_decision()` và áp ngay, đồng bộ, không bao giờ ném.

**Theo dõi cài đặt** (`_SettingsWatcher`, `QAbstractNativeEventFilter`, một bản cấp module, cài vào ứng
dụng khi backdrop đầu tiên đăng ký): chỉ xét `bytes(event_type) == b"windows_generic_MSG"`, đọc MSG
bằng `_MSG.from_address(int(message))`; `WM_SETTINGCHANGE` (tương phản cao, trong suốt),
`WM_THEMECHANGED`, `WM_DWMCOMPOSITIONCHANGED` → nếu chưa chờ thì `QTimer.singleShot(0)` gọi `refresh()`
mọi backdrop còn sống (nhiều tin trong một vòng sự kiện → một lần). Không gọi DWM hay đọc sổ đăng ký
trong bộ lọc; toàn thân trong `try/except Exception`; luôn trả `(False, 0)`. Tập backdrop là `WeakSet`,
bỏ qua phần tử `not shiboken6.isValid`, gỡ khi `destroyed`.

**Seam cho test** (biến cấp module, đọc lúc gọi): `_qt_platform`, `_windows_build`, `_high_contrast`,
`_transparency_enabled`, `_dwm_extend_frame(hwnd, margin) -> int`, `_dwm_set_backdrop(hwnd, kind) -> int`,
`_dwm_set_dark(hwnd, on) -> int` (HRESULT; ngoài Windows trả `E_FAIL`); `_reset_for_tests()` gỡ bộ lọc
native và xóa tập theo dõi (fixture autouse `backdrop_reset` của `tests/ui/conftest.py`). Hàm DWM thật
dùng `ctypes.WinDLL("dwmapi")` riêng của module (không đặt `argtypes` lên `ctypes.windll` dùng chung),
`restype = c_long` (không `HRESULT`, kiểu đó tự ném); `hr >= 0` là thành công.

Không được làm cửa sổ chính thành cửa sổ layered (`windowOpacity` khác 1, `motion.fade_in_window`): Mica
hỏng. Thanh cuộn của `sidebar_scroll` vẽ đặc khi danh sách tràn (chấp nhận).
"""

from __future__ import annotations

import ctypes
import functools
import logging
import sys
import weakref
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Any

import shiboken6
from PySide6.QtCore import (
    QAbstractNativeEventFilter,
    QByteArray,
    QCoreApplication,
    QEvent,
    QObject,
    QPoint,
    QRect,
    Qt,
    QTimer,
)
from PySide6.QtGui import QGuiApplication, QPainter, QPaintEvent, QRegion
from PySide6.QtWidgets import QApplication, QWidget

from teleport.ui import theme

log = logging.getLogger(__name__)

MICA_MIN_BUILD = 22621  # Windows 11 22H2: DWMWA_SYSTEMBACKDROP_TYPE có tài liệu
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMSBT_NONE = 1
DWMSBT_MAINWINDOW = 2
WM_SETTINGCHANGE = 0x001A
WM_THEMECHANGED = 0x031A
WM_DWMCOMPOSITIONCHANGED = 0x031E
SPI_GETHIGHCONTRAST = 0x0042
HCF_HIGHCONTRASTON = 0x0001
E_FAIL = -0x7FFFBFFB  # 0x80004005 dạng có dấu
_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_WATCHED_MESSAGES = frozenset((WM_SETTINGCHANGE, WM_THEMECHANGED, WM_DWMCOMPOSITIONCHANGED))
_NATIVE_EVENT_TYPE = b"windows_generic_MSG"


class Backdrop(Enum):
    """Nền của cột trái."""

    SOLID = "solid"
    MICA = "mica"


class Reason(StrEnum):
    """Lý do của quyết định (xem thứ tự ở docstring module)."""

    OK = "ok"
    PLATFORM = "platform"
    OLD_BUILD = "old_build"
    HIGH_CONTRAST = "high_contrast"
    TRANSPARENCY_OFF = "transparency_off"
    DWM_ERROR = "dwm_error"
    CREATED = "created"


@dataclass(frozen=True, slots=True)
class Decision:
    """Nền được chọn và lý do."""

    backdrop: Backdrop
    reason: Reason


_MICA = Decision(Backdrop.MICA, Reason.OK)


def capable(*, qt_platform: str, build: int | None) -> bool:
    """Nền tảng Qt là `"windows"` và build ≥ `MICA_MIN_BUILD` (điều kiện (1)(2) của `decide`)."""
    return qt_platform == "windows" and build is not None and build >= MICA_MIN_BUILD


def decide(*, qt_platform: str, build: int | None, high_contrast: bool, transparency: bool) -> Decision:
    """Quyết định nền theo thứ tự lý do ở docstring module (hàm thuần)."""
    if qt_platform != "windows":
        return Decision(Backdrop.SOLID, Reason.PLATFORM)
    if build is None or build < MICA_MIN_BUILD:
        return Decision(Backdrop.SOLID, Reason.OLD_BUILD)
    if high_contrast:
        return Decision(Backdrop.SOLID, Reason.HIGH_CONTRAST)
    if not transparency:
        return Decision(Backdrop.SOLID, Reason.TRANSPARENCY_OFF)
    return _MICA


# ---- Seam đọc hệ thống ---------------------------------------------------------------------------


def _default_qt_platform() -> str:
    return QGuiApplication.platformName()


def _default_windows_build() -> int | None:
    """Số build của Windows (`platform_version[2]`, không bị giới hạn bởi manifest); ngoài Windows → None."""
    if sys.platform == "win32":
        return int(sys.getwindowsversion().platform_version[2])
    return None


def _default_high_contrast() -> bool:
    """Cờ `HCF_HIGHCONTRASTON` của `SystemParametersInfoW(SPI_GETHIGHCONTRAST)`; gọi lỗi → OSError."""
    if sys.platform == "win32":
        from ctypes import wintypes

        class _HighContrast(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwFlags", wintypes.DWORD),
                ("lpszDefaultScheme", wintypes.LPWSTR),
            ]

        info = _HighContrast()
        info.cbSize = ctypes.sizeof(_HighContrast)
        if not _user32().SystemParametersInfoW(SPI_GETHIGHCONTRAST, info.cbSize, ctypes.byref(info), 0):
            raise OSError("SystemParametersInfoW(SPI_GETHIGHCONTRAST) lỗi")
        return bool(info.dwFlags & HCF_HIGHCONTRASTON)
    return False


def _default_transparency_enabled() -> bool:
    """`EnableTransparency` (chỉ đọc) của `HKCU\\...\\Themes\\Personalize`; không có → `FileNotFoundError`."""
    if sys.platform == "win32":
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY, 0, winreg.KEY_READ) as key:
            value, _kind = winreg.QueryValueEx(key, "EnableTransparency")
        return bool(value)
    return True


@functools.cache
def _user32() -> Any:
    """user32 riêng của module, đã đặt `argtypes` / `restype` (chỉ gọi trên Windows)."""
    if sys.platform == "win32":
        from ctypes import c_uint, c_void_p, wintypes

        user32 = ctypes.WinDLL("user32")
        user32.SystemParametersInfoW.argtypes = [c_uint, c_uint, c_void_p, c_uint]
        user32.SystemParametersInfoW.restype = wintypes.BOOL
        return user32
    raise OSError("chỉ có trên Windows")


@functools.cache
def _dwmapi() -> Any:
    """dwmapi riêng của module, `restype = c_long` (không `HRESULT`: kiểu đó tự ném)."""
    if sys.platform == "win32":
        from ctypes import c_long, c_uint32, c_void_p

        dwmapi = ctypes.WinDLL("dwmapi")
        dwmapi.DwmExtendFrameIntoClientArea.argtypes = [c_void_p, c_void_p]
        dwmapi.DwmExtendFrameIntoClientArea.restype = c_long
        dwmapi.DwmSetWindowAttribute.argtypes = [c_void_p, c_uint32, c_void_p, c_uint32]
        dwmapi.DwmSetWindowAttribute.restype = c_long
        return dwmapi
    raise OSError("chỉ có trên Windows")


def _default_dwm_extend_frame(hwnd: int, margin: int) -> int:
    """`DwmExtendFrameIntoClientArea` với bốn lề bằng `margin` (-1: cả cửa sổ; 0: gỡ); trả HRESULT."""
    if sys.platform == "win32":

        class _Margins(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int) for name in ("left", "right", "top", "bottom")]

        margins = _Margins(margin, margin, margin, margin)
        return int(_dwmapi().DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins)))
    return E_FAIL


def _set_attribute(hwnd: int, attribute: int, value: int) -> int:
    if sys.platform == "win32":
        data = ctypes.c_int(value)  # DWORD / BOOL: 4 byte
        return int(_dwmapi().DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), ctypes.sizeof(data)))
    return E_FAIL


def _default_dwm_set_backdrop(hwnd: int, kind: int) -> int:
    """`DWMWA_SYSTEMBACKDROP_TYPE` = `kind`; trả HRESULT."""
    return _set_attribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, kind)


def _default_dwm_set_dark(hwnd: int, on: bool) -> int:
    """`DWMWA_USE_IMMERSIVE_DARK_MODE` = `on` (BOOL); trả HRESULT."""
    return _set_attribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if on else 0)


# Seam (đọc lúc gọi): thay trong test để giả Windows 11 và ghi lại lời gọi DWM.
_qt_platform: Callable[[], str] = _default_qt_platform
_windows_build: Callable[[], int | None] = _default_windows_build
_high_contrast: Callable[[], bool] = _default_high_contrast
_transparency_enabled: Callable[[], bool] = _default_transparency_enabled
_dwm_extend_frame: Callable[[int, int], int] = _default_dwm_extend_frame
_dwm_set_backdrop: Callable[[int, int], int] = _default_dwm_set_backdrop
_dwm_set_dark: Callable[[int, bool], int] = _default_dwm_set_dark


def current_decision() -> Decision:
    """Quyết định theo hệ thống lúc gọi (đọc seam); không bao giờ ném (quy ước lỗi ở docstring module)."""
    try:
        platform = _qt_platform()
    except Exception:
        platform = ""
    try:
        build = _windows_build()
    except Exception:
        build = None
    if not capable(qt_platform=platform, build=build):
        return decide(qt_platform=platform, build=build, high_contrast=False, transparency=True)
    try:
        high_contrast = bool(_high_contrast())
    except Exception:
        high_contrast = True
    try:
        transparency = bool(_transparency_enabled())
    except FileNotFoundError:
        transparency = True
    except Exception:
        transparency = False
    return decide(qt_platform=platform, build=build, high_contrast=high_contrast, transparency=transparency)


def _hresult(call: Callable[[], int]) -> int:
    """HRESULT của `call`; ném → `E_FAIL`."""
    try:
        return int(call())
    except Exception:
        log.debug("Lời gọi DWM ném lỗi", exc_info=True)
        return E_FAIL


# ---- Theo dõi cài đặt của hệ điều hành -----------------------------------------------------------


class _MSG(ctypes.Structure):
    """Đầu của `MSG` (Win32) đủ để đọc mã tin. Khai báo ở mọi nền tảng (chỉ kiểu `ctypes` cơ bản) để
    test bộ lọc native chạy được trên Linux/macOS; chỉ Qt trên Windows gửi `windows_generic_MSG`."""

    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("message", ctypes.c_uint),
        ("wParam", ctypes.c_size_t),
        ("lParam", ctypes.c_ssize_t),
    ]


def _message_id(message: int) -> int:
    """Mã tin của con trỏ `MSG*` (chỉ gọi khi loại sự kiện là `windows_generic_MSG`)."""
    return int(_MSG.from_address(int(message)).message)


class _SettingsWatcher(QAbstractNativeEventFilter):
    """Bộ lọc native: tin đổi cài đặt → một lần `refresh()` cho mọi backdrop ở vòng sự kiện sau."""

    def __init__(self) -> None:
        super().__init__()
        self.backdrops: weakref.WeakSet[MicaBackdrop] = weakref.WeakSet()
        self.pending = False

    def nativeEventFilter(
        self, event_type: QByteArray | bytes | bytearray | memoryview, message: int
    ) -> tuple[bool, int]:
        try:
            raw = event_type.data() if isinstance(event_type, QByteArray) else bytes(event_type)
            if raw == _NATIVE_EVENT_TYPE and not self.pending and _message_id(message) in _WATCHED_MESSAGES:
                self.pending = True
                QTimer.singleShot(0, self.flush)
        except Exception:
            log.debug("Đọc tin native lỗi", exc_info=True)
        return False, 0

    def flush(self) -> None:
        """Gọi `refresh()` mọi backdrop còn sống (sau một lượt gom tin)."""
        self.pending = False
        for backdrop in list(self.backdrops):
            if shiboken6.isValid(backdrop):
                backdrop.refresh()


_watcher: _SettingsWatcher | None = None


def _watch(backdrop: MicaBackdrop) -> None:
    """Đăng ký `backdrop` với bộ theo dõi (cài bộ lọc native vào ứng dụng ở lần đầu)."""
    global _watcher
    if _watcher is None:
        app = QCoreApplication.instance()
        if app is None:
            return
        _watcher = _SettingsWatcher()
        app.installNativeEventFilter(_watcher)
    _watcher.backdrops.add(backdrop)
    ref = weakref.ref(backdrop)
    backdrop.destroyed.connect(lambda *_args: _forget(ref))


def _forget(ref: weakref.ref[MicaBackdrop]) -> None:
    backdrop = ref()
    if _watcher is not None and backdrop is not None:
        _watcher.backdrops.discard(backdrop)


def _reset_for_tests() -> None:
    """Gỡ bộ lọc native khỏi ứng dụng và xóa tập theo dõi; chỉ cho test."""
    global _watcher
    if _watcher is not None:
        app = QCoreApplication.instance()
        if app is not None:
            app.removeNativeEventFilter(_watcher)
        _watcher.backdrops.clear()
        _watcher.pending = False
        _watcher = None


# ---- Backdrop của một cửa sổ ---------------------------------------------------------------------

_WINDOW_EVENTS = frozenset(
    (QEvent.Type.Paint, QEvent.Type.Show, QEvent.Type.WinIdChange, QEvent.Type.ApplicationPaletteChange)
)
_GLASS_EVENTS = frozenset((QEvent.Type.Show, QEvent.Type.Hide, QEvent.Type.Move, QEvent.Type.Resize))


class MicaBackdrop(QObject):
    """Nền Mica của `glass` trong `window` (hành vi ở docstring module)."""

    def __init__(self, window: QWidget, glass: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._glass = glass
        self._translucent = False
        self._active = False
        self._hwnd: int | None = None  # HWND đã áp quyết định
        self._warned = False
        wanted = current_decision()
        self._wanted = wanted
        self._decision = wanted
        if wanted.reason in (Reason.PLATFORM, Reason.OLD_BUILD):
            return
        if window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            log.debug("Cửa sổ đã có HWND trước khi gắn Mica: giữ nền đặc")
            self._wanted = self._decision = Decision(Backdrop.SOLID, Reason.CREATED)
            return
        window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._translucent = True
        window.installEventFilter(self)
        glass.installEventFilter(self)
        _watch(self)

    @property
    def decision(self) -> Decision:
        """Quyết định đang có hiệu lực (trước khi có HWND: quyết định mong muốn)."""
        return self._decision

    @property
    def active(self) -> bool:
        """Mica đang bật thật (DWM đã nhận)."""
        return self._active

    def refresh(self) -> None:
        """Đọc lại cài đặt và áp ngay, đồng bộ; không bao giờ ném."""
        if not self._translucent or not shiboken6.isValid(self._window):
            return
        try:
            self._wanted = current_decision()
            self._sync(retry=True)
        except Exception:
            log.debug("Áp lại nền Mica lỗi", exc_info=True)

    # ---- Sự kiện ------------------------------------------------------------------------------

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind not in _WINDOW_EVENTS and kind not in _GLASS_EVENTS:
            return False
        if not shiboken6.isValid(self._window):
            return False  # cửa sổ đang bị hủy: kính còn nhận Hide trong hàm hủy của cửa sổ
        if watched is self._window:
            if kind not in _WINDOW_EVENTS:
                return False
            if kind == QEvent.Type.Paint:
                assert isinstance(event, QPaintEvent)
                try:
                    self._paint(event)
                except Exception:
                    log.debug("Tô nền cửa sổ lỗi", exc_info=True)
            elif kind == QEvent.Type.ApplicationPaletteChange:
                self._palette_changed()
            else:
                self._safe_sync()
        elif watched is self._glass and kind in _GLASS_EVENTS:
            self._window.update()
        return False

    def _paint(self, event: QPaintEvent) -> None:
        """Tô `surface` lên vùng cần vẽ của `window`, trừ kính khi Mica đang bật và kính đang hiện."""
        region = QRegion(event.region())
        glass = self._glass
        if self._active and glass.isVisible():
            region = region.subtracted(QRegion(QRect(glass.mapTo(self._window, QPoint(0, 0)), glass.size())))
        if region.isEmpty():
            return
        painter = QPainter(self._window)
        try:
            painter.setClipRegion(region)
            painter.fillRect(region.boundingRect(), theme.tokens_for(self._window).surface)
        finally:
            painter.end()

    def _palette_changed(self) -> None:
        if self._active and self._hwnd is not None:
            hwnd = self._hwnd
            hr = _hresult(lambda: _dwm_set_dark(hwnd, _app_is_dark()))
            if hr < 0:
                log.debug("DwmSetWindowAttribute(dark) lỗi 0x%08X", hr & 0xFFFFFFFF)
        self._window.update()

    def _safe_sync(self) -> None:
        try:
            self._sync()
        except Exception:
            log.debug("Áp nền Mica lỗi", exc_info=True)

    # ---- Áp DWM -------------------------------------------------------------------------------

    def _current_hwnd(self) -> int | None:
        """HWND của `window` khi đã tạo (không bao giờ ép tạo)."""
        if not self._window.testAttribute(Qt.WidgetAttribute.WA_WState_Created):
            return None
        hwnd = int(self._window.winId())
        return hwnd or None

    def _sync(self, *, retry: bool = False) -> None:
        """Áp `_wanted` lên HWND hiện tại khi quyết định đổi hoặc HWND mới; sau `DWM_ERROR` chỉ thử lại
        khi `retry` (từ `refresh()`) hoặc HWND mới."""
        hwnd = self._current_hwnd()
        if hwnd is None:
            if not self._active:
                self._decision = self._wanted  # chưa có HWND: quyết định mong muốn
            return
        new_hwnd = hwnd != self._hwnd
        if not new_hwnd and (
            self._wanted == self._decision or (self._decision.reason is Reason.DWM_ERROR and not retry)
        ):
            return
        if new_hwnd:
            self._hwnd = hwnd
            self._active = False  # HWND mới chưa có thuộc tính DWM nào
        if self._wanted.backdrop is Backdrop.MICA:
            self._enable(hwnd)
        else:
            self._disable(hwnd, self._wanted)

    def _enable(self, hwnd: int) -> None:
        hr = _hresult(lambda: _dwm_set_dark(hwnd, _app_is_dark()))
        if hr < 0:
            log.debug("DwmSetWindowAttribute(dark) lỗi 0x%08X", hr & 0xFFFFFFFF)
        hr = _hresult(lambda: _dwm_extend_frame(hwnd, -1))
        if hr >= 0:
            hr = _hresult(lambda: _dwm_set_backdrop(hwnd, DWMSBT_MAINWINDOW))
        if hr < 0:
            _hresult(lambda: _dwm_extend_frame(hwnd, 0))
            _hresult(lambda: _dwm_set_backdrop(hwnd, DWMSBT_NONE))
            if not self._warned:
                self._warned = True
                log.warning("Không bật được nền Mica (HRESULT 0x%08X), dùng nền đặc", hr & 0xFFFFFFFF)
            self._active = False
            self._decision = Decision(Backdrop.SOLID, Reason.DWM_ERROR)
            self._set_glass_property(None)
            self._window.update()
            return
        self._active = True
        self._decision = self._wanted
        self._set_glass_property("mica")
        self._window.update()

    def _disable(self, hwnd: int, decision: Decision) -> None:
        was_active = self._active
        self._active = False
        self._decision = decision
        self._set_glass_property(None)
        self._window.repaint()  # cột trái đặc trước khi DWM tắt Mica
        if was_active:
            _hresult(lambda: _dwm_extend_frame(hwnd, 0))
            _hresult(lambda: _dwm_set_backdrop(hwnd, DWMSBT_NONE))

    def _set_glass_property(self, value: str | None) -> None:
        glass = self._glass
        if glass.property(theme.BACKDROP_PROPERTY) == value:
            return
        glass.setProperty(theme.BACKDROP_PROPERTY, value)
        style = glass.style()
        style.unpolish(glass)
        style.polish(glass)
        glass.update()


def _app_is_dark() -> bool:
    """Ứng dụng đang ở chế độ tối (theo bảng màu của ứng dụng, như `theme.tokens_for`)."""
    return theme.is_dark_palette(QApplication.palette())
