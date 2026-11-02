"""`teleport.ui.shell`: “Hiện trong thư mục” (spec-f4 mục 2.4; mục 8 S6, S8, S9 thắng khi khác). Tiêu chí
R5, R6, R7.

Viết từ spec, không từ code. Tên file khác `test_shell.py` (file đó là test khung GUI có sẵn từ
spec-p4-3, không liên quan).

Seam: `shell._is_windows` (vá để chạy cùng một kịch bản trên mọi hệ điều hành), `shell._select_native`
(fixture autouse `fake_select_native` của tests/ui/conftest.py: không bao giờ mở Explorer thật; test đọc
`calls`, đặt `result`/`error`). `open_url` là tham số. R7 gọi `_pidl`/`_free_pidl` thật, chỉ trên Windows,
không bao giờ gọi `SHOpenFolderAndSelectItems`.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

WIN = sys.platform == "win32"
windows_only = pytest.mark.skipif(not WIN, reason="đường dẫn ổ đĩa/UNC và shell32 chỉ có trên Windows")


class OpenSpy:
    """`open_url` giả: ghi lại đường dẫn của mỗi QUrl, trả `result` nguyên vẹn."""

    def __init__(self, result: object = True) -> None:
        self.paths: list[Path] = []
        self.result = result

    def __call__(self, url) -> object:
        assert url.isLocalFile(), url
        self.paths.append(Path(url.toLocalFile()))
        return self.result


@pytest.fixture
def shell(monkeypatch):
    from teleport.ui import shell as mod

    monkeypatch.setattr(mod, "_is_windows", lambda: True)
    return mod


@pytest.fixture
def root(tmp_path) -> Path:
    return tmp_path / "nhan"


# =================================================================================================
# Reveal, hằng, seam
# =================================================================================================


def test_reveal_is_frozen_with_folder_default_none(tmp_path):
    import dataclasses

    from teleport.ui.shell import Reveal

    r = Reveal(files=(tmp_path / "a.txt",), root=tmp_path)
    assert r.folder is None
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.root = None  # type: ignore[misc]


def test_reveal_max_items_is_32():
    from teleport.ui import shell

    assert shell.REVEAL_MAX_ITEMS == 32


def test_is_windows_default_follows_platform():
    from teleport.ui import shell

    assert shell._is_windows() is (sys.platform == "win32")


# =================================================================================================
# R5: is_within
# =================================================================================================


def test_is_within_direct_and_deep_child(root):
    from teleport.ui.shell import is_within

    assert is_within(root / "a.txt", root) is True
    assert is_within(root / "x" / "y" / "z.bin", root) is True


def test_is_within_rejects_root_itself(root):
    from teleport.ui.shell import is_within

    assert is_within(root, root) is False


def test_is_within_rejects_sibling_with_same_prefix(root):
    from teleport.ui.shell import is_within

    assert is_within(root.parent / (root.name + "2") / "a.txt", root) is False


def test_is_within_rejects_dotdot_escape(root):
    from teleport.ui.shell import is_within

    assert is_within(Path(str(root) + os.sep + ".." + os.sep + "x"), root) is False
    assert is_within(Path(os.sep.join([str(root), "con", "..", "..", "x", "a.txt"])), root) is False


def test_is_within_accepts_dotdot_that_stays_inside(root):
    from teleport.ui.shell import is_within

    assert is_within(Path(os.sep.join([str(root), "con", "..", "a.txt"])), root) is True


def test_is_within_rejects_relative_paths(root):
    from teleport.ui.shell import is_within

    assert is_within(Path("nhan") / "a.txt", root) is False
    assert is_within(root / "a.txt", Path("nhan")) is False
    assert is_within(Path("nhan") / "a.txt", Path("nhan")) is False


@windows_only
@pytest.mark.parametrize(
    ("path", "root", "expected"),
    [
        (r"C:\nhan\a.txt", r"C:\nhan", True),
        (r"C:\nhan\x\y\a.txt", r"C:\nhan", True),
        (r"C:\nhan", r"C:\nhan", False),
        (r"C:\nhan\\", r"C:\nhan", False),
        (r"C:\nhan2\a", r"C:\nhan", False),
        (r"C:\nhan\..\x", r"C:\nhan", False),
        (r"D:\nhan\a.txt", r"C:\nhan", False),
        (r"nhan\a.txt", r"C:\nhan", False),
        (r"C:nhan\a.txt", r"C:\nhan", False),  # ổ có mà không có gốc: tương đối
        (r"\nhan\a.txt", r"C:\nhan", False),  # gốc mà không có ổ: tương đối
        (r"\\srv\share\nhan\a.txt", r"\\srv\share\nhan", True),
        (r"\\srv\other\nhan\a.txt", r"\\srv\share\nhan", False),
        (r"\\other\share\nhan\a.txt", r"\\srv\share\nhan", False),
        (r"\\srv\share\nhan\a.txt", r"C:\nhan", False),
        (r"C:\NHAN\A.TXT", r"c:\nhan", True),
        (r"c:/nhan/a.txt", r"C:\Nhan", True),
    ],
)
def test_is_within_windows_cases(path, root, expected):
    from teleport.ui.shell import is_within

    assert is_within(Path(path), Path(root)) is expected


def test_is_within_does_not_touch_disk(tmp_path):
    from teleport.ui.shell import is_within

    root = tmp_path / "khong-ton-tai-f4" / "nhan"
    touched: list[str] = []

    def spy(name, real):
        def wrapper(*args, **kwargs):
            touched.append(name)
            return real(*args, **kwargs)

        return wrapper

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(os, "stat", spy("os.stat", os.stat))
        mp.setattr(os, "lstat", spy("os.lstat", os.lstat))
        mp.setattr(os.path, "exists", spy("os.path.exists", os.path.exists))
        mp.setattr(os.path, "realpath", spy("os.path.realpath", os.path.realpath))
        mp.setattr(pathlib.Path, "stat", spy("Path.stat", pathlib.Path.stat))
        mp.setattr(pathlib.Path, "exists", spy("Path.exists", pathlib.Path.exists))
        mp.setattr(pathlib.Path, "resolve", spy("Path.resolve", pathlib.Path.resolve))
        inside = is_within(root / "a.txt", root)
        outside = is_within(root.parent / "khac" / "a.txt", root)
    assert (inside, outside) == (True, False)
    assert touched == []


# =================================================================================================
# R6: show_in_folder
# =================================================================================================


def test_files_in_root_select_natively_once_without_open_url(shell, root, fake_select_native):
    fake_select_native.result = True
    files = [root / "a.txt", root / "b.txt"]
    opened = OpenSpy()
    assert shell.show_in_folder(files, root, open_url=opened) is True
    assert fake_select_native.calls == [(root, tuple(files))]
    assert opened.paths == []


def test_picks_only_files_in_parent_of_last_file(shell, root, fake_select_native):
    fake_select_native.result = True
    files = [root / "a.txt", root / "con" / "b.txt", root / "c.txt"]
    shell.show_in_folder(files, root, open_url=OpenSpy())
    assert fake_select_native.calls == [(root, (root / "a.txt", root / "c.txt"))]


def test_target_is_parent_of_last_file_even_in_subfolder(shell, root, fake_select_native):
    fake_select_native.result = True
    files = [root / "a.txt", root / "con" / "b.txt"]
    shell.show_in_folder(files, root, open_url=OpenSpy())
    assert fake_select_native.calls == [(root / "con", (root / "con" / "b.txt",))]


def test_picks_are_capped_keeping_last_files(shell, root, fake_select_native):
    fake_select_native.result = True
    files = [root / f"f{i:02}.bin" for i in range(40)]
    shell.show_in_folder(files, root, open_url=OpenSpy())
    [(target, picks)] = fake_select_native.calls
    assert target == root
    assert picks == tuple(files[-shell.REVEAL_MAX_ITEMS :])


def test_picks_cap_read_at_call_time(shell, root, fake_select_native, monkeypatch):
    fake_select_native.result = True
    monkeypatch.setattr(shell, "REVEAL_MAX_ITEMS", 2)
    files = [root / f"f{i}.bin" for i in range(5)]
    shell.show_in_folder(files, root, open_url=OpenSpy())
    assert fake_select_native.calls == [(root, tuple(files[-2:]))]


def test_native_false_falls_back_to_open_parent(shell, root, fake_select_native):
    fake_select_native.result = False
    sentinel = object()
    opened = OpenSpy(result=sentinel)
    got = shell.show_in_folder([root / "con" / "a.txt"], root, open_url=opened)
    assert len(fake_select_native.calls) == 1
    assert opened.paths == [root / "con"]
    assert got is sentinel


@pytest.mark.parametrize("error", [OSError("bí mật C:\\x"), ValueError("bí mật"), RuntimeError("bí mật")])
def test_native_error_falls_back_and_logs_only_type_name(shell, root, fake_select_native, caplog, error):
    fake_select_native.error = error
    opened = OpenSpy(result=True)
    with caplog.at_level(logging.DEBUG):
        got = shell.show_in_folder([root / "a.txt"], root, open_url=opened)
    assert got is True
    assert opened.paths == [root]
    logs = "\n".join(r.getMessage() for r in caplog.records)
    assert type(error).__name__ in logs, "spec 2.4 bước 3: log DEBUG tên loại lỗi"
    assert "bí mật" not in logs, "chỉ ghi tên loại lỗi, không ghi nội dung"


def test_file_outside_root_skips_native_and_opens_parent(shell, root, fake_select_native):
    fake_select_native.result = True
    outside = root.parent / (root.name + "2") / "a.txt"
    opened = OpenSpy()
    shell.show_in_folder([outside], root, open_url=opened)
    assert fake_select_native.calls == []
    assert opened.paths == [outside.parent]


def test_dotdot_escape_skips_native(shell, root, fake_select_native):
    fake_select_native.result = True
    sneaky = Path(os.sep.join([str(root), "..", "khac", "a.txt"]))
    opened = OpenSpy()
    shell.show_in_folder([sneaky], root, open_url=opened)
    assert fake_select_native.calls == []
    assert len(opened.paths) == 1


def test_root_none_skips_native_and_opens_parent(shell, root, fake_select_native):
    fake_select_native.result = True
    opened = OpenSpy()
    shell.show_in_folder([root / "a.txt"], None, open_url=opened)
    assert fake_select_native.calls == []
    assert opened.paths == [root]


def test_not_windows_skips_native_and_opens_parent(shell, root, fake_select_native, monkeypatch):
    monkeypatch.setattr(shell, "_is_windows", lambda: False)
    fake_select_native.result = True
    opened = OpenSpy()
    shell.show_in_folder([root / "a.txt"], root, open_url=opened)
    assert fake_select_native.calls == []
    assert opened.paths == [root]


def test_select_native_read_at_call_time(shell, root, monkeypatch):
    calls: list = []
    monkeypatch.setattr(shell, "_select_native", lambda target, picks: calls.append(target) or True)
    opened = OpenSpy()
    assert shell.show_in_folder([root / "a.txt"], root, open_url=opened) is True
    assert calls == [root] and opened.paths == []


def test_empty_files_open_folder_first(shell, root, tmp_path, fake_select_native):
    folder = tmp_path / "rieng"
    sentinel = object()
    opened = OpenSpy(result=sentinel)
    assert shell.show_in_folder([], root, open_url=opened, folder=folder) is sentinel
    assert opened.paths == [folder]
    assert fake_select_native.calls == []


def test_empty_files_without_folder_open_root(shell, root, fake_select_native):
    opened = OpenSpy()
    shell.show_in_folder((), root, open_url=opened)
    assert opened.paths == [root]
    assert fake_select_native.calls == []


def test_empty_files_without_folder_or_root_returns_false(shell, fake_select_native):
    opened = OpenSpy()
    assert shell.show_in_folder([], None, open_url=opened) is False
    assert opened.paths == []
    assert fake_select_native.calls == []


def test_relative_and_non_path_entries_are_dropped(shell, root, fake_select_native):
    fake_select_native.result = True
    opened = OpenSpy()
    shell.show_in_folder([Path("tuong-doi") / "a.txt", str(root / "chuoi.txt")], root, open_url=opened)
    assert fake_select_native.calls == [], "không còn Path tuyệt đối nào: không chọn file"
    assert opened.paths == [root]


def test_relative_last_entry_ignored_for_target(shell, root, fake_select_native):
    fake_select_native.result = True
    shell.show_in_folder([root / "a.txt", Path("b.txt")], root, open_url=OpenSpy())
    assert fake_select_native.calls == [(root, (root / "a.txt",))]


def test_show_in_folder_does_not_touch_disk(shell, tmp_path, fake_select_native, monkeypatch):
    root = tmp_path / "khong-ton-tai-f4"
    touched: list[str] = []
    real_stat, real_exists = pathlib.Path.stat, pathlib.Path.exists

    def stat(self, *a, **k):
        touched.append(str(self))
        return real_stat(self, *a, **k)

    def exists(self, *a, **k):
        touched.append(str(self))
        return real_exists(self, *a, **k)

    monkeypatch.setattr(pathlib.Path, "stat", stat)
    monkeypatch.setattr(pathlib.Path, "exists", exists)
    shell.show_in_folder([root / "a.txt"], root, open_url=OpenSpy())
    assert [t for t in touched if "khong-ton-tai-f4" in t] == []


# =================================================================================================
# R7: shell32 thật (chỉ Windows), không mở Explorer
# =================================================================================================


@windows_only
def test_pidl_of_real_file_is_not_none_and_free_is_ok(tmp_path):
    from teleport.ui import shell

    f = tmp_path / "that.txt"
    f.write_bytes(b"x")
    pidl = shell._pidl(f)
    assert pidl is not None
    shell._free_pidl(pidl)


@windows_only
def test_pidl_of_folder_is_not_none(tmp_path):
    from teleport.ui import shell

    pidl = shell._pidl(tmp_path)
    assert pidl is not None
    shell._free_pidl(pidl)


@windows_only
def test_pidl_of_missing_file_is_none(tmp_path):
    from teleport.ui import shell

    assert shell._pidl(tmp_path / "khong-co.txt") is None


@pytest.mark.skipif(WIN, reason="nhánh không phải Windows")
def test_non_windows_native_helpers_are_inert(tmp_path):
    from teleport.ui import shell

    f = tmp_path / "a.txt"
    f.write_bytes(b"x")
    assert shell._pidl(f) is None


# ---- Nhánh native với `SHOpenFolderAndSelectItems` giả (chỉ Windows) ---------------------------
# `shell._dlls` trả bản bọc shell32 thật, chỉ thay `SHOpenFolderAndSelectItems` bằng hàm ghi tham số
# (không bao giờ mở Explorer); `SHParseDisplayName`, `ILFindLastID`, `CoTaskMemFree` vẫn là hàm thật. ID
# con được đối chiếu lại thành đường dẫn bằng `ILCombine` + `SHGetPathFromIDListW` (bản WinDLL riêng).


@pytest.fixture
def native(monkeypatch):
    import ctypes
    from ctypes import c_int, c_void_p, c_wchar_p
    from types import SimpleNamespace

    from teleport.ui import shell

    real_shell32, real_ole32 = shell._dlls()
    probe = ctypes.WinDLL("shell32")
    probe.ILCombine.argtypes = [c_void_p, c_void_p]
    probe.ILCombine.restype = c_void_p
    probe.SHGetPathFromIDListW.argtypes = [c_void_p, c_wchar_p]
    probe.SHGetPathFromIDListW.restype = c_int
    ole = ctypes.WinDLL("ole32")
    ole.CoTaskMemFree.argtypes = [c_void_p]
    ole.CoTaskMemFree.restype = None

    def path_of(pidl) -> Path:
        buf = ctypes.create_unicode_buffer(32768)
        assert probe.SHGetPathFromIDListW(pidl, buf), "PIDL không đổi được ra đường dẫn"
        return Path(buf.value)

    rec = SimpleNamespace(calls=[], created=[], freed=[], hr=0, init=[], uninit=0)

    class FakeShell32:
        def __getattr__(self, name):
            return getattr(real_shell32, name)

        def SHOpenFolderAndSelectItems(self, parent, cidl, apidl, flags):
            children = []
            if apidl is not None:
                for i in range(cidl):
                    full = probe.ILCombine(parent, apidl[i])
                    try:
                        children.append(path_of(full))
                    finally:
                        ole.CoTaskMemFree(full)
            rec.calls.append((path_of(parent), cidl, apidl is None, children, flags))
            return rec.hr

    class FakeOle32:
        def __getattr__(self, name):
            return getattr(real_ole32, name)

        def CoInitializeEx(self, reserved, flags):
            hr = real_ole32.CoInitializeEx(reserved, flags)
            rec.init.append(hr)
            return hr

        def CoUninitialize(self):
            rec.uninit += 1
            real_ole32.CoUninitialize()

    real_pidl, real_free = shell._pidl, shell._free_pidl

    def pidl(path):
        value = real_pidl(path)
        if value is not None:
            rec.created.append(value)
        return value

    def free(value):
        rec.freed.append(value)
        real_free(value)

    monkeypatch.setattr(shell, "_dlls", lambda: (FakeShell32(), FakeOle32()))
    monkeypatch.setattr(shell, "_pidl", pidl)
    monkeypatch.setattr(shell, "_free_pidl", free)
    return rec


def same(a: Path, b: Path) -> bool:
    return os.path.samefile(a, b)


@pytest.fixture
def real_files(tmp_path):
    d = tmp_path / "nhan"
    d.mkdir()
    files = [d / f"f{i}.txt" for i in range(3)]
    for f in files:
        f.write_bytes(b"x")
    return d, files


@windows_only
def test_native_single_file_uses_absolute_pidl_and_no_children(native, real_files):
    from teleport.ui import shell

    d, files = real_files
    assert shell._open_and_select(d, files[:1]) is True
    [(parent, cidl, no_array, children, flags)] = native.calls
    assert same(parent, files[0]), "một file: PIDL tuyệt đối của chính file"
    assert (cidl, no_array, children, flags) == (0, True, [], 0)
    assert len(native.created) == 1
    assert sorted(native.freed) == sorted(native.created)


@windows_only
def test_native_many_files_pass_folder_and_child_ids(native, real_files):
    from teleport.ui import shell

    d, files = real_files
    assert shell._open_and_select(d, files) is True
    [(parent, cidl, no_array, children, flags)] = native.calls
    assert same(parent, d)
    assert (cidl, no_array, flags) == (3, False, 0)
    assert len(children) == 3
    assert all(same(c, f) for c, f in zip(children, files, strict=True)), children
    assert len(native.created) == 4, "PIDL thư mục + 3 PIDL file"
    assert sorted(native.freed) == sorted(native.created), "mọi PIDL tuyệt đối được giải phóng"


@windows_only
def test_native_missing_last_file_returns_false_and_frees_all(native, real_files):
    from teleport.ui import shell

    d, files = real_files
    assert shell._open_and_select(d, [*files, d / "khong-co.txt"]) is False
    assert native.calls == [], "PIDL nào không dựng được thì không gọi shell"
    assert len(native.created) == 4
    assert sorted(native.freed) == sorted(native.created)


@windows_only
def test_native_missing_single_file_returns_false(native, real_files):
    from teleport.ui import shell

    d, _ = real_files
    assert shell._open_and_select(d, [d / "khong-co.txt"]) is False
    assert native.calls == [] and native.created == [] and native.freed == []


@windows_only
@pytest.mark.parametrize("count", [1, 3])
def test_native_failed_hresult_returns_false_and_frees_all(native, real_files, count):
    from teleport.ui import shell

    native.hr = -2147467259  # E_FAIL
    d, files = real_files
    assert shell._open_and_select(d, files[:count]) is False
    assert len(native.calls) == 1
    assert sorted(native.freed) == sorted(native.created) and native.created


@windows_only
def test_default_select_native_balances_com_init(native, real_files):
    from teleport.ui import shell

    d, files = real_files
    assert shell._default_select_native(d, files) is True
    assert len(native.init) == 1
    owned = native.init[0] in (0, 1)  # S_OK / S_FALSE
    assert native.uninit == (1 if owned else 0)
    assert len(native.calls) == 1
    assert sorted(native.freed) == sorted(native.created)


@windows_only
def test_default_select_native_without_files_does_nothing(native, real_files):
    from teleport.ui import shell

    d, _ = real_files
    assert shell._default_select_native(d, []) is False
    assert native.calls == [] and native.created == []
