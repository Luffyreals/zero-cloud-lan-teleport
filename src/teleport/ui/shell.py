"""“Hiện trong thư mục”: mở trình quản lý file với file vừa nhận được chọn sẵn (theo dõi tiến độ khi chạy
nền, `plan-f-ux-hang-ngay` F4; mvp F5, F9).

`show_in_folder(files, root, *, open_url, folder=None)`:
1. Chỉ giữ `Path` tuyệt đối. Không còn file: mở `folder` (không có thì `root`) bằng `open_url`; cả hai
   None → False.
2. `target` = thư mục cha của file cuối; `picks` = các file có cha là `target`, tối đa
   `REVEAL_MAX_ITEMS` file **cuối**.
3. Chọn sẵn bằng `_select_native(target, picks)` chỉ khi `_is_windows()`, `root` khác None và **mọi**
   `picks` nằm trong `root` (`is_within`): Explorer không bao giờ được mời mở đường dẫn ngoài thư mục
   nhận. True → trả True. False hay ném lỗi (mọi `Exception`, log DEBUG tên loại lỗi) → bước 4.
4. Dự phòng: trả nguyên `open_url(QUrl.fromLocalFile(target))` (mở thư mục cha, không chọn file). Linux
   và macOS luôn đi đường này.

`is_within(path, root)` chỉ so chuỗi, không chạm đĩa: cả hai tuyệt đối, chuẩn hóa
`os.path.normcase(os.path.normpath(...))`, `path` khác `root` và `os.path.commonpath` là `root`; khác
ổ, khác share UNC (`ValueError`) → False. `..` thoát ra ngoài, `C:\\nhan2\\a` với root `C:\\nhan`,
đường dẫn tương đối → False.

**`_select_native` thật** (chỉ Windows; `ctypes` import trong hàm): `CoInitializeEx(None,
COINIT_APARTMENTTHREADED)`; `S_OK` / `S_FALSE` → `CoUninitialize` trong `finally`;
`RPC_E_CHANGED_MODE` → chạy tiếp, không gỡ; lỗi khác → False. `_pidl(path)` dựng PIDL tuyệt đối bằng
`SHParseDisplayName` (lỗi → None). Một file: `SHOpenFolderAndSelectItems(pidl_file, 0, NULL, 0)`. Nhiều
file: PIDL của thư mục + mảng ID con tương đối, mỗi ID là `ILFindLastID(pidl_file)` (con trỏ nằm trong
PIDL tuyệt đối, không giải phóng riêng). Mọi PIDL tuyệt đối giải phóng bằng `_free_pidl`
(`CoTaskMemFree`) trong `finally`, sau khi `SHOpenFolderAndSelectItems` trả về. PIDL nào không dựng
được → False (về dự phòng). `hr >= 0` → True. Dùng `ctypes.WinDLL("shell32")` / `WinDLL("ole32")`
riêng của module (không đặt `argtypes` lên `ctypes.windll` dùng chung), `argtypes` / `restype` đủ cho
64-bit.

Chạy trên thread Qt như `QDesktopServices.openUrl` hiện có: ổ mạng chậm có thể làm giao diện khựng lúc
bấm (chấp nhận; gọi trên thread riêng nằm ngoài phạm vi).

Seam cho test (biến cấp module, đọc lúc gọi): `_select_native`, `_is_windows`, `_pidl`, `_free_pidl`;
hằng `REVEAL_MAX_ITEMS` cũng đọc lúc dùng. Fixture tự động của `tests/ui/conftest.py` thay
`_select_native` để không test nào mở Explorer thật (`architecture.md` §6).
"""

from __future__ import annotations

import functools
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QUrl

log = logging.getLogger(__name__)

REVEAL_MAX_ITEMS = 32  # số file tối đa được chọn sẵn (và được nhớ cho một bóng thoại / bong bóng)

_COINIT_APARTMENTTHREADED = 0x2
_S_OK = 0
_S_FALSE = 1
_RPC_E_CHANGED_MODE = 0x80010106


@dataclass(frozen=True, slots=True)
class Reveal:
    """Payload của bóng thoại “Đã nhận…” (`Tray.show_message(folder=...)`)."""

    files: tuple[Path, ...]  # file đã lưu (≤ `REVEAL_MAX_ITEMS`)
    root: Path | None  # thư mục nhận lúc lượt kết thúc
    folder: Path | None = None  # mở thư mục này khi không có file nào


def _default_is_windows() -> bool:
    return sys.platform == "win32"


# Seam: đang chạy trên Windows không (chỉ Windows mới chọn sẵn file); đọc lúc gọi.
_is_windows: Callable[[], bool] = _default_is_windows


def _norm(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def is_within(path: Path, root: Path) -> bool:
    """`path` nằm trong `root` (không phải chính `root`); chỉ so chuỗi, không chạm đĩa."""
    try:
        p, r = os.fspath(path), os.fspath(root)
        if not (os.path.isabs(p) and os.path.isabs(r)):
            return False
        p, r = _norm(p), _norm(r)
        if p == r:
            return False
        return os.path.commonpath([p, r]) == r
    except (TypeError, ValueError):
        return False


def show_in_folder(
    files: Sequence[Path],
    root: Path | None,
    *,
    open_url: Callable[[QUrl], object],
    folder: Path | None = None,
) -> object:
    """Hiện `files` trong trình quản lý file (xem docstring module). Trả True (đã chọn sẵn), giá trị
    của `open_url` (dự phòng), hay False (không có gì để mở)."""
    paths = [p for p in files if isinstance(p, Path) and p.is_absolute()]
    if not paths:
        fallback = folder if folder is not None else root
        if fallback is None:
            return False
        return open_url(QUrl.fromLocalFile(str(fallback)))
    target = paths[-1].parent
    limit = max(1, int(REVEAL_MAX_ITEMS))
    picks = [p for p in paths if p.parent == target][-limit:]
    if _is_windows() and root is not None and all(is_within(p, root) for p in picks):
        try:
            if _select_native(target, picks):
                return True
        except Exception as e:
            log.debug("không chọn sẵn được file trong thư mục: %s", type(e).__name__)
    return open_url(QUrl.fromLocalFile(str(target)))


# ---- Windows: SHOpenFolderAndSelectItems ------------------------------------------------------------


@functools.cache
def _dlls() -> tuple[Any, Any]:
    """(shell32, ole32) riêng của module, đã đặt `argtypes` / `restype` (chỉ gọi trên Windows)."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import POINTER, c_long, c_uint, c_ulong, c_void_p, c_wchar_p

        shell32 = ctypes.WinDLL("shell32")
        ole32 = ctypes.WinDLL("ole32")
        shell32.SHParseDisplayName.argtypes = [
            c_wchar_p,
            c_void_p,
            POINTER(c_void_p),
            c_ulong,
            POINTER(c_ulong),
        ]
        shell32.SHParseDisplayName.restype = c_long
        shell32.SHOpenFolderAndSelectItems.argtypes = [c_void_p, c_uint, POINTER(c_void_p), c_ulong]
        shell32.SHOpenFolderAndSelectItems.restype = c_long
        shell32.ILFindLastID.argtypes = [c_void_p]
        shell32.ILFindLastID.restype = c_void_p
        ole32.CoInitializeEx.argtypes = [c_void_p, c_ulong]
        ole32.CoInitializeEx.restype = c_long
        ole32.CoUninitialize.argtypes = []
        ole32.CoUninitialize.restype = None
        ole32.CoTaskMemFree.argtypes = [c_void_p]
        ole32.CoTaskMemFree.restype = None
        return shell32, ole32
    raise OSError("chỉ có trên Windows")


def _pidl(path: Path) -> int | None:
    """PIDL tuyệt đối của `path` (địa chỉ, giải phóng bằng `_free_pidl`); không dựng được → None."""
    if sys.platform == "win32":
        import ctypes

        shell32, _ole32 = _dlls()
        pidl = ctypes.c_void_p()
        hr = shell32.SHParseDisplayName(str(path), None, ctypes.byref(pidl), 0, None)
        if hr < 0 or not pidl.value:
            return None
        return int(pidl.value)
    return None


def _free_pidl(pidl: int | None) -> None:
    """Giải phóng PIDL do `_pidl` dựng (None → không làm gì)."""
    if sys.platform == "win32":
        if pidl:
            _shell32, ole32 = _dlls()
            ole32.CoTaskMemFree(pidl)


def _open_and_select(folder: Path, files: Sequence[Path]) -> bool:
    """`SHOpenFolderAndSelectItems` cho `files` trong `folder` (COM đã khởi tạo trên thread này)."""
    if sys.platform == "win32":
        import ctypes

        shell32, _ole32 = _dlls()
        pidls: list[int] = []
        try:
            if len(files) == 1:
                pidl = _pidl(files[0])
                if pidl is None:
                    return False
                pidls.append(pidl)
                hr = shell32.SHOpenFolderAndSelectItems(pidl, 0, None, 0)
            else:
                parent = _pidl(folder)
                if parent is None:
                    return False
                pidls.append(parent)
                children: list[int] = []
                for path in files:
                    pidl = _pidl(path)
                    if pidl is None:
                        return False
                    pidls.append(pidl)
                    child = shell32.ILFindLastID(pidl)  # nằm trong `pidl`: không giải phóng riêng
                    if not child:
                        return False
                    children.append(child)
                array = (ctypes.c_void_p * len(children))(*children)
                hr = shell32.SHOpenFolderAndSelectItems(parent, len(children), array, 0)
            return bool(hr >= 0)
        finally:
            for pidl in pidls:
                _free_pidl(pidl)
    return False


def _default_select_native(folder: Path, files: Sequence[Path]) -> bool:
    """Mở `folder` trong Explorer với `files` được chọn sẵn; True nếu Windows nhận lệnh."""
    if sys.platform == "win32":
        if not files:
            return False
        _shell32, ole32 = _dlls()
        hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        owned = hr in (_S_OK, _S_FALSE)
        if not owned and (hr & 0xFFFFFFFF) != _RPC_E_CHANGED_MODE:
            return False
        try:
            return _open_and_select(folder, files)
        finally:
            if owned:
                ole32.CoUninitialize()
    return False


# Seam: chọn sẵn file trong Explorer (thư mục, các file); đọc lúc gọi. Test thay để không mở Explorer.
_select_native: Callable[[Path, Sequence[Path]], bool] = _default_select_native
