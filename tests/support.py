"""Helper dùng chung cho test, import bằng `from support import …` (`pythonpath` trong `pyproject.toml`).

Fixture vẫn ở các `conftest.py`; file này chỉ chứa hàm thường mà nhiều file test cần gọi trực tiếp.
"""

import asyncio
import os
import time
from collections.abc import Callable


async def wait_until(
    predicate: Callable[[], bool], timeout: float = 5.0, what: str = "điều kiện", *, poll: float = 0.01
) -> None:
    """Chờ tới khi `predicate()` đúng, hỏi lại mỗi `poll` giây; quá `timeout` giây thì `AssertionError`."""
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"hết {timeout} s mà {what} vẫn chưa đúng")
        await asyncio.sleep(poll)


def windows_dacl(path) -> tuple[bool, str]:
    """(DACL có bị bảo vệ khỏi kế thừa không, DACL dạng SDDL) của `path`, đọc thẳng bằng Win32 API.

    Kiểm độc lập với code: `GetNamedSecurityInfoW` lấy security descriptor, cờ `SE_DACL_PROTECTED`
    lấy từ `GetSecurityDescriptorControl`, SDDL từ `ConvertSecurityDescriptorToStringSecurityDescriptorW`.
    """
    import ctypes
    from ctypes import wintypes

    se_file_object = 1
    dacl_security_information = 0x4
    sddl_revision_1 = 1
    se_dacl_protected = 0x1000

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_info = advapi32.GetNamedSecurityInfoW
    get_info.argtypes = [
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_info.restype = wintypes.DWORD
    get_control = advapi32.GetSecurityDescriptorControl
    get_control.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD), ctypes.POINTER(wintypes.DWORD)]
    get_control.restype = wintypes.BOOL
    to_sddl = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    to_sddl.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG),
    ]
    to_sddl.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    rc = get_info(
        os.fspath(path),
        se_file_object,
        dacl_security_information,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if rc != 0:
        raise ctypes.WinError(rc)
    try:
        control = wintypes.WORD()
        revision = wintypes.DWORD()
        if not get_control(descriptor, ctypes.byref(control), ctypes.byref(revision)):
            raise ctypes.WinError(ctypes.get_last_error())
        text = ctypes.c_void_p()
        if not to_sddl(descriptor, sddl_revision_1, dacl_security_information, ctypes.byref(text), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            sddl = ctypes.wstring_at(text.value)
        finally:
            local_free(text)
    finally:
        local_free(descriptor)
    return bool(control.value & se_dacl_protected), sddl
