"""Test `teleport.app.storage` (P2-5): mở thư mục nhận, thư mục tạm, `PartFile`, `remove_temp`.

Viết theo đặc tả (spec P2-5 mục 2–3, AC-4…AC-15, AC-24, AC-25, H2, H3), không theo code. Nguồn:
architecture §4 (bố cục `<thư mục nhận>/.teleport/<transfer_id>/<file_index>.part`), protocol §3.3
(`transfer_id` là 32 ký tự hex thường), §4.2 (khối 1 MiB), §4.4 (đọc lại, thử lại 5 × 50 ms).

Luật kiểm ở đây:
- `ReceiveDir.open` tạo thư mục nhận (kể cả thư mục cha), không tạo `.teleport`; thư mục nhận được
  là symlink/junction; `.teleport` có sẵn mà là link hay file → `UnsafeReceiveDirError` ngay ở `open`.
- `create_temp`: `transfer_id` sai → `ValueError`, không đụng đĩa; `<id>` đã có (có `.part`, file lạ,
  liên kết…) → `TempExistsError`, nội dung cũ còn nguyên; P3-3a (spec-p3-3a mục 4 V1, 8.1): `record`
  bắt buộc (`record_for` trong conftest), thư mục tạm luôn có `transfer.json`, part có `<i>.state`;
  ma trận H2 và đường ghi `.state` ở `test_storage_resume.py`; `.teleport` bị thay bằng link sau
  `open` → `UnsafeReceiveDirError`;
  POSIX: quyền `0o700`, chủ hợp lệ là euid hoặc chủ thư mục nhận; Windows: `.teleport` mới tạo bị ẩn.
- File nhận xong mang quyền như file tải về thường (D10): POSIX `0o666` trừ umask; Windows DACL kế
  thừa từ thư mục nhận, không bị bảo vệ, cùng ACE với file tạo thẳng trong đó.
- `PartFile.write_at`: tham số sai → `ValueError`, file không đổi; ghi tạo lỗ sau cuối phần đã ghi →
  `WriteGapError` (là `StorageError`, không phải `ValueError`) trước mọi I/O; ghi thiếu thì ghi tiếp;
  `OSError` bay ra nguyên `errno`.
- `PartFile.reread`: `bytearray` hash SHA-256 từng khối nối liền; khối đọc thiếu là 32 byte 0; file
  dài hơn `size` thì cắt rồi `fsync`; một bộ đệm cố định; dừng bằng `stop`.
- `remove_temp`: chỉ xóa `.part` do chính temp tạo (cùng danh tính) và thư mục `<id>` khi rỗng; không
  bao giờ ném `OSError`; trả `True` khi và chỉ khi `<id>` không còn.

Không test nào mở socket (spec mục 5: không gắn `integration`). Module được import trong fixture,
để thiếu module chỉ làm đỏ các test dùng nó. Mọi `ReceiveDir` được đóng (`with`) để Windows dọn được
`tmp_path`.
"""

import ast
import asyncio
import dataclasses
import errno
import hashlib
import importlib
import io
import os
import random
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tracemalloc
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from support import windows_dacl

from teleport import atomic
from teleport.core.blocks import BLOCK_SIZE, block_count, block_length
from teleport.core.merkle import merkle_root

BS = BLOCK_SIZE
ID = "0123456789abcdef0123456789abcdef"
ID2 = "fedcba9876543210fedcba9876543210"
WINDOWS = sys.platform == "win32"

posix_only = pytest.mark.skipif(WINDOWS, reason="nhánh POSIX (dir_fd)")
windows_only = pytest.mark.skipif(not WINDOWS, reason="chỉ Windows")
macos_only = pytest.mark.skipif(sys.platform != "darwin", reason="chỉ macOS")
not_macos = pytest.mark.skipif(sys.platform == "darwin", reason="macOS dùng F_FULLFSYNC")

DOCS = Path(__file__).resolve().parents[2] / "docs"


@pytest.fixture(scope="module")
def storage():
    return importlib.import_module("teleport.app.storage")


@pytest.fixture
def root(tmp_path):
    return tmp_path / "recv"


@pytest.fixture
def rd(storage, root):
    with storage.ReceiveDir.open(root) as receive_dir:
        yield receive_dir


@pytest.fixture
def quick_retry(storage, monkeypatch):
    """Rút ngắn khoảng chờ thử lại (hằng đọc lúc dùng, spec mục 2.2)."""
    monkeypatch.setattr(storage, "REPLACE_DELAY", 0.001)


# ---------------------------------------------------------------------------------------------
# Hàm phụ trợ
# ---------------------------------------------------------------------------------------------


def payload(size: int, seed: int = 1) -> bytes:
    """Dữ liệu ngẫu nhiên có rải `\\r\\n`, `\\n`, `\\x1a` để bắt lỗi thiếu `O_BINARY` trên Windows."""
    data = bytearray(random.Random(seed).randbytes(size))
    for off in range(0, max(size - 4, 0), 4093):
        data[off : off + 4] = b"\r\n\x1a\n"
    return bytes(data)


def write_all(part, data) -> None:
    view = memoryview(data)
    for i in range(block_count(len(data))):
        part.write_at(i, view[i * BS : (i + 1) * BS])


def block_hashes(data: bytes) -> bytes:
    size = len(data)
    return b"".join(
        hashlib.sha256(data[i * BS : i * BS + block_length(size, i)]).digest()
        for i in range(block_count(size))
    )


def merkle_by_hand(leaves: list[bytes]) -> bytes:
    """Merkle root theo protocol §4.4, viết độc lập: cha = SHA-256(trái ‖ phải), nút lẻ đẩy lên."""
    if not leaves:
        return hashlib.sha256(b"").digest()
    level = leaves
    while len(level) > 1:
        parents = [hashlib.sha256(level[i] + level[i + 1]).digest() for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            parents.append(level[-1])
        level = parents
    return level[0]


def make_symlink(target, link, *, is_dir: bool) -> None:
    try:
        os.symlink(target, link, target_is_directory=is_dir)
    except (OSError, NotImplementedError) as e:  # Windows cần quyền (WinError 1314)
        pytest.skip(f"không tạo được symlink: {e}")


def link_dir(kind: str, target, link) -> None:
    """Đặt một liên kết thư mục tại `link`: symlink, junction (Windows) hay symlink treo."""
    if kind == "junction":
        if not WINDOWS:
            pytest.skip("junction chỉ có trên Windows")
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    elif kind == "symlink":
        make_symlink(target, link, is_dir=True)
    elif kind == "dangling":
        make_symlink(Path(link).parent / "khong-ton-tai", link, is_dir=True)
    else:
        raise AssertionError(kind)


def snapshot(top) -> dict[str, tuple]:
    """Mọi mục dưới `top`, không theo liên kết: loại, kích thước, SHA-256 nội dung, đích của link."""
    result: dict[str, tuple] = {}

    def visit(path: str, rel: str) -> None:
        with os.scandir(path) as it:
            entries = sorted(it, key=lambda e: e.name)
        for entry in entries:
            name = f"{rel}/{entry.name}"
            if entry.is_symlink() or entry.is_junction():
                result[name] = ("link", os.readlink(entry.path))
            elif entry.is_dir(follow_symlinks=False):
                result[name] = ("dir",)
                visit(entry.path, name)
            else:
                with open(entry.path, "rb") as f:
                    content = f.read()
                result[name] = ("file", len(content), hashlib.sha256(content).hexdigest())

    visit(os.fspath(top), "")
    return result


def units(s: str) -> int:
    """Đơn vị đo đường dẫn (spec mục 3.5): Windows UTF-16 code unit, POSIX byte."""
    if WINDOWS:
        return len(s.encode("utf-16-le")) // 2
    return len(os.fsencode(s))


def stat_with_uid(st: os.stat_result, uid: int) -> os.stat_result:
    _, (seq, extra) = st.__reduce__()
    fields = list(seq)
    fields[4] = uid  # st_uid
    return os.stat_result(fields, extra)


def fake_owner(monkeypatch, uid_by_identity: dict[tuple[int, int], int]) -> None:
    """Vá `os.fstat` để chỉ các mục có (st_dev, st_ino) trong bảng mang `st_uid` giả."""
    real_fstat = os.fstat

    def fstat(fd):
        st = real_fstat(fd)
        uid = uid_by_identity.get((st.st_dev, st.st_ino))
        return st if uid is None else stat_with_uid(st, uid)

    monkeypatch.setattr(os, "fstat", fstat)


def identity(path) -> tuple[int, int]:
    st = os.stat(path)
    return st.st_dev, st.st_ino


def nested_dir(base: str, total: int) -> str:
    """Đường dẫn thư mục dưới `base` dài đúng `total` đơn vị, các thành phần ≤ 100 ký tự."""
    need = total - units(base)
    assert need >= 2
    components = []
    while need > 0:
        chunk = min(101, need)
        if need - chunk == 1:  # tránh thành phần cuối rỗng
            chunk -= 1
        components.append("d" * (chunk - 1))
        need -= chunk
    path = os.path.join(base, *components)
    assert units(path) == total
    return path


# ---------------------------------------------------------------------------------------------
# Hằng, exception, dataclass (spec mục 2.2)
# ---------------------------------------------------------------------------------------------


def test_constants_match_spec(storage):
    assert storage.FAT_MAX_FILE_SIZE == (1 << 32) - 1
    assert frozenset({"fat", "fat12", "fat16", "fat32", "vfat", "msdos", "umsdos"}) == storage.FAT_FS_TYPES
    assert storage.WINDOWS_MAX_PATH == 259
    assert storage.TEMP_PATH_RESERVE == 78  # P3-3a (đã chốt): tên tạm `transfer.json.<16 hex>.tmp`
    assert storage.MAX_NAME_CANDIDATES == 100_000


def test_retry_constants_follow_protocol(storage):
    # protocol §4.4: 5 lần, cách nhau 50 ms; cùng số với teleport.atomic.
    assert storage.REPLACE_ATTEMPTS == atomic.REPLACE_ATTEMPTS == 5
    assert storage.REPLACE_DELAY == atomic.REPLACE_DELAY == 0.05


@windows_only
def test_movefile_flags(storage):
    assert storage.MOVEFILE_REPLACE_EXISTING == 0x1
    assert storage.MOVEFILE_WRITE_THROUGH == 0x8


def test_temp_path_reserve_matches_layout(storage, resume_helpers):
    # Spec P2-5 mục 2.2 (b): `<root>\.teleport\<id>` = root + 43 ≤ 247. P3-3a (đã chốt): file dài nhất
    # của bố cục thư mục tạm (regex spec-p3 mục 2.2) là `transfer.json.<16 hex>.tmp`, root + 78 ≤ 259.
    hexes = "0" * 16
    layout_names = [
        "transfer.json",
        "999.part",
        "999.state",
        f"transfer.json.{hexes}.tmp",
        f"999.state.{hexes}.tmp",
    ]
    assert all(resume_helpers.LAYOUT_RE.fullmatch(n) for n in layout_names)
    longest = max(layout_names, key=len)
    assert longest == f"transfer.json.{hexes}.tmp"
    file_extra = len("\\.teleport\\") + 32 + len("\\") + len(longest)
    dir_extra = len("\\.teleport\\") + 32
    assert (file_extra, dir_extra) == (78, 43)
    max_root = min(storage.WINDOWS_MAX_PATH - file_extra, 247 - dir_extra)
    assert max_root == 181
    assert storage.WINDOWS_MAX_PATH - max_root == storage.TEMP_PATH_RESERVE == 78


EXCEPTIONS = [
    "UnsafeReceiveDirError",
    "PathTooLongError",
    "TempExistsError",
    "NameUnavailableError",
    "RereadStopped",
    "WriteGapError",
]


@pytest.mark.parametrize("name", EXCEPTIONS)
def test_exceptions_derive_from_storage_error_not_os_error(storage, name):
    cls = getattr(storage, name)
    assert issubclass(cls, storage.StorageError)
    assert not issubclass(cls, OSError)
    assert not issubclass(cls, ValueError)


def test_storage_error_is_plain_exception(storage):
    assert issubclass(storage.StorageError, Exception)
    # ValueError dành cho dùng sai API (spec mục 1.3); OSError là lỗi I/O thật.
    assert not issubclass(storage.StorageError, (OSError, ValueError))


def test_dataclasses_are_frozen_with_slots(storage):
    info = storage.VolumeInfo(fs_type="ntfs", max_file_size=None, free_bytes=1)
    limits = storage.PathLimits(max_path=259, max_name_bytes=255)
    for obj, field in ((info, "free_bytes"), (limits, "max_path")):
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, field, 2)
        assert not hasattr(obj, "__dict__")


# ---------------------------------------------------------------------------------------------
# Mã nguồn và tài liệu (AC-30, AC-31, spec mục 2.3)
# ---------------------------------------------------------------------------------------------


def _storage_ast(storage) -> ast.Module:
    return ast.parse(Path(storage.__file__).read_text(encoding="utf-8"))


def test_source_does_not_use_os_readinto(storage):
    # D28: os.readinto chỉ có từ Python 3.14, CI chạy cả 3.12.
    for node in ast.walk(_storage_ast(storage)):
        if isinstance(node, ast.Attribute) and node.attr == "readinto":
            assert not (isinstance(node.value, ast.Name) and node.value.id == "os"), node.lineno
        if isinstance(node, ast.ImportFrom) and node.module == "os":
            assert all(alias.name != "readinto" for alias in node.names), node.lineno


SEAM_FUNCTIONS = {
    "os": {
        "open",
        "close",
        "mkdir",
        "rmdir",
        "unlink",
        "replace",
        "stat",
        "lstat",
        "fstat",
        "fchmod",
        "fsync",
        "ftruncate",
        "lseek",
        "write",
        "pwrite",
        "utime",
        "scandir",
        "listdir",
        "geteuid",
        "pathconf",
    },
    "fcntl": {"fcntl"},
    "shutil": {"disk_usage"},
    "time": {"sleep"},
    "io": {"FileIO"},
}


def test_stdlib_seams_are_called_through_module(storage):
    # Spec mục 2.3: không `from os import …`, để test vá được qua module.
    for node in ast.walk(_storage_ast(storage)):
        if isinstance(node, ast.ImportFrom) and node.module in SEAM_FUNCTIONS:
            names = {alias.name for alias in node.names}
            assert not names & SEAM_FUNCTIONS[node.module], (node.module, names)


@pytest.mark.parametrize(
    ("const", "module"),
    [
        ("TEMP_PATH_RESERVE", "teleport.app.storage"),
        ("WINDOWS_MAX_PATH", "teleport.app.storage"),
        ("FALLBACK_MAX_BYTES", "teleport.core.filenames"),
    ],
)
def test_architecture_doc_states_same_numbers(const, module):
    # Spec mục 4.2: architecture §4 “Thư mục nhận” nắm các số này; code và tài liệu không được lệch.
    value = getattr(importlib.import_module(module), const)
    text = (DOCS / "architecture.md").read_text(encoding="utf-8")
    found = re.findall(rf"`?{const}`?\s*=\s*`?(\d+)", text)
    assert found, f"architecture.md mục 4 phải ghi `{const}` = <số>"
    assert {int(x) for x in found} == {value}


# ---------------------------------------------------------------------------------------------
# AC-4 Mở thư mục nhận
# ---------------------------------------------------------------------------------------------


def test_open_creates_root_and_parents(storage, tmp_path):
    root = tmp_path / "a" / "b" / "recv"
    with storage.ReceiveDir.open(root) as rd:
        assert root.is_dir()
        assert rd.root == Path(os.path.abspath(root))
        assert not rd.closed
    assert rd.closed


def test_open_accepts_relative_str_path(storage, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    expected = Path(os.path.abspath("recv"))
    with storage.ReceiveDir.open("recv") as rd:
        assert rd.root.is_absolute()
        assert rd.root == expected
        assert expected.is_dir()


def test_open_existing_root_keeps_its_content(storage, root):
    root.mkdir()
    (root / "cu.txt").write_bytes(b"cu")
    with storage.ReceiveDir.open(root):
        pass
    assert sorted(os.listdir(root)) == ["cu.txt"]
    assert (root / "cu.txt").read_bytes() == b"cu"


def test_open_does_not_create_temp_dir(rd):
    assert os.listdir(rd.root) == []


def test_open_root_is_file_raises_not_a_directory(storage, root):
    root.write_bytes(b"khong phai thu muc")
    with pytest.raises(NotADirectoryError), storage.ReceiveDir.open(root):
        pass
    assert root.read_bytes() == b"khong phai thu muc"


def test_open_root_under_a_file_raises_os_error(storage, tmp_path):
    (tmp_path / "f").write_bytes(b"x")
    with pytest.raises(OSError) as exc, storage.ReceiveDir.open(tmp_path / "f" / "recv"):
        pass
    assert not isinstance(exc.value, storage.StorageError)


def test_open_root_through_symlink(storage, tmp_path, record_for):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    make_symlink(real, link, is_dir=True)
    with storage.ReceiveDir.open(link) as rd:
        assert rd.root == Path(os.path.abspath(link))  # không resolve symlink
        temp = rd.create_temp(ID, record_for(ID, [0]))
        assert (real / ".teleport" / ID).is_dir()
        assert rd.remove_temp(temp) is True


@windows_only
def test_open_root_through_junction(storage, tmp_path, record_for):
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "junction"
    link_dir("junction", real, link)
    with storage.ReceiveDir.open(link) as rd:
        assert rd.root == Path(os.path.abspath(link))
        temp = rd.create_temp(ID, record_for(ID, [0]))
        assert (real / ".teleport" / ID).is_dir()
        assert rd.remove_temp(temp) is True


def test_limits_follow_platform(storage, rd):
    limits = rd.limits
    assert isinstance(limits, storage.PathLimits)
    if WINDOWS:
        assert limits == storage.PathLimits(max_path=259, max_name_bytes=255)
    else:
        try:
            max_path = os.pathconf(rd.root, "PC_PATH_MAX") - 1
        except OSError:
            max_path = 1023
        try:
            max_name = min(255, os.pathconf(rd.root, "PC_NAME_MAX"))
        except OSError:
            max_name = 255
        assert limits == storage.PathLimits(max_path=max_path, max_name_bytes=max_name)


def test_path_limits_seam_receives_absolute_root(storage, root, monkeypatch):
    seen = []

    def fake(r):
        seen.append(r)
        return storage.PathLimits(10_000, 255)

    monkeypatch.setattr(storage, "_path_limits", fake)
    with storage.ReceiveDir.open(root) as rd:
        assert rd.limits == storage.PathLimits(10_000, 255)
    assert seen
    assert all(type(s) is str and s == os.path.abspath(root) for s in seen)


def test_close_is_idempotent_and_context_manager_returns_self(storage, root):
    rd = storage.ReceiveDir.open(root)
    with rd as entered:
        assert entered is rd
    assert rd.closed
    rd.close()
    assert rd.closed


def test_close_closes_temps_and_parts_without_deleting(storage, root, record_for):
    rd = storage.ReceiveDir.open(root)
    temp = rd.create_temp(ID, record_for(ID, [10, 1]))
    part = temp.create_part(0, 10)
    part.write_at(0, b"0123456789")
    rd.close()
    rd.close()
    assert temp.closed
    assert part.closed
    assert part.path.read_bytes() == b"0123456789"
    assert temp.path.is_dir()
    # Windows chỉ xóa được file khi không còn handle nào mở: chứng minh fd đã đóng, kể cả handle
    # nối thêm của `0.state` (P3-3a: thư mục tạm có thêm `transfer.json` và `<i>.state`).
    assert sorted(os.listdir(temp.path)) == ["0.part", "0.state", "transfer.json"]
    for name in ("0.part", "0.state", "transfer.json"):
        os.unlink(temp.path / name)
    os.rmdir(temp.path)
    with pytest.raises(ValueError):
        part.write_at(0, b"0123456789")
    with pytest.raises(ValueError):
        temp.create_part(1, 1)


# ---------------------------------------------------------------------------------------------
# AC-5 `.teleport` có sẵn sai loại
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["symlink", "junction", "dangling", "file"])
def test_open_rejects_existing_temp_dir_of_wrong_kind(storage, tmp_path, kind, record_for):
    root = tmp_path / "recv"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "giu.txt").write_bytes(b"cua nan nhan")
    temp_dir = root / ".teleport"
    if kind == "file":
        temp_dir.write_bytes(b"khong phai thu muc")
    else:
        link_dir(kind, victim, temp_dir)
    before = snapshot(tmp_path)
    with pytest.raises(storage.UnsafeReceiveDirError), storage.ReceiveDir.open(root) as rd:
        rd.create_temp(ID, record_for(ID, [0]))  # chỉ chạy tới đây nếu `open` không báo lỗi như spec
    assert snapshot(tmp_path) == before


# ---------------------------------------------------------------------------------------------
# AC-6 `create_temp` tạo đúng thư mục
# ---------------------------------------------------------------------------------------------


def test_create_temp_creates_transfer_dir(rd, record_for):
    from teleport.core.resume_state import encode_transfer_record

    record = record_for(ID, [0])
    temp = rd.create_temp(ID, record)
    assert temp.transfer_id == ID
    assert temp.path == rd.root / ".teleport" / ID
    assert temp.path.is_dir()
    assert not temp.closed
    # P3-3a: `transfer.json` bền ngay khi `create_temp` trả về (spec-p3-3a mục 2.3 ý 1).
    assert os.listdir(temp.path) == ["transfer.json"]
    assert (temp.path / "transfer.json").read_bytes() == encode_transfer_record(record)
    assert temp.record == record
    assert os.listdir(rd.root) == [".teleport"]


def test_create_temp_for_two_transfers_shares_temp_dir(rd, record_for):
    t1 = rd.create_temp(ID, record_for(ID, [0]))
    t2 = rd.create_temp(ID2, record_for(ID2, [0]))
    assert t1.path.parent == t2.path.parent == rd.root / ".teleport"
    assert sorted(os.listdir(rd.root / ".teleport")) == sorted([ID, ID2])


@posix_only
def test_temp_dirs_are_private(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [0]))
    assert stat.S_IMODE(os.stat(rd.root / ".teleport").st_mode) == 0o700
    assert stat.S_IMODE(os.stat(temp.path).st_mode) == 0o700


@posix_only
def test_existing_temp_dir_permissions_are_tightened_on_create_temp(storage, root, record_for):
    temp_dir = root / ".teleport"
    temp_dir.mkdir(parents=True)
    os.chmod(temp_dir, 0o755)
    with storage.ReceiveDir.open(root) as rd:
        assert stat.S_IMODE(os.stat(temp_dir).st_mode) == 0o755  # `open` không fchmod
        rd.create_temp(ID, record_for(ID, [0]))
        assert stat.S_IMODE(os.stat(temp_dir).st_mode) == 0o700


@windows_only
def test_new_temp_dir_is_hidden_on_windows(rd, record_for):
    rd.create_temp(ID, record_for(ID, [0]))
    attrs = os.stat(rd.root / ".teleport").st_file_attributes
    assert attrs & stat.FILE_ATTRIBUTE_HIDDEN


@windows_only
def test_existing_temp_dir_is_not_made_hidden(storage, root, record_for):
    # Spec mục 3.2 bước 1: chỉ đặt HIDDEN khi vừa tạo `.teleport`.
    (root / ".teleport").mkdir(parents=True)
    with storage.ReceiveDir.open(root) as rd:
        rd.create_temp(ID, record_for(ID, [0]))
    assert not os.stat(root / ".teleport").st_file_attributes & stat.FILE_ATTRIBUTE_HIDDEN


# ---------------------------------------------------------------------------------------------
# AC-7 `transfer_id` sai
# ---------------------------------------------------------------------------------------------

BAD_TRANSFER_IDS = [
    "../x",
    "..",
    ".",
    "",
    "0" * 31,
    "0" * 33,
    ID.upper(),
    "0123456789ABCDEF0123456789abcdef",
    "0" * 31 + "\x00",
    "\x00" + "0" * 31,
    ID[:16] + "/" + ID[17:],
    ID[:16] + "\\" + ID[17:],
    "../" + ID[3:],
    "g" * 32,
    ID + "\n",
    ID[:-1] + "\n",
    " " + ID[1:],
    "０" * 32,  # chữ số toàn chiều rộng: `\d` khớp, `[0-9a-f]` thì không
    "٠" * 32,  # chữ số Ả Rập
    ID.encode(),
    int(ID, 16),
    None,
    [ID],
]


@pytest.mark.parametrize("bad", BAD_TRANSFER_IDS)
def test_create_temp_rejects_bad_transfer_id_without_touching_disk(rd, tmp_path, bad, record_for):
    before = snapshot(tmp_path)
    with pytest.raises(ValueError):
        rd.create_temp(bad, record_for(ID, [0]))
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize(
    "bad",
    [ID.upper(), ID[:31], ID.encode(), int(ID, 16), None, "0" * 31 + "\x00", ID + "\n"],
    ids=["hoa", "31-ky-tu", "bytes", "so", "none", "nul", "xuong-dong"],
)
def test_create_temp_bad_transfer_id_uses_message_validator(rd, tmp_path, bad, record_for):
    """P2-6a ST1 (plan-p2-6 mục 2.3): `create_temp` kiểm id bằng `core.messages.validate_transfer_id`.

    Vẫn là `ValueError` như cũ (`MessageError` là lớp con), thông điệp là của `MessageError`, không đụng đĩa.
    """
    from teleport.core.messages import MessageError, validate_transfer_id

    with pytest.raises(MessageError) as expected:
        validate_transfer_id(bad)
    before = snapshot(tmp_path)
    with pytest.raises(ValueError) as got:
        rd.create_temp(bad, record_for(ID, [0]))
    assert isinstance(got.value, MessageError)
    assert str(got.value) == str(expected.value)
    assert snapshot(tmp_path) == before


def test_storage_docstring_no_longer_promises_validator_switch(storage):
    """Plan-p2-6 mục 2.3: câu “đổi sang … khi P2-4 merge” đã hết hiệu lực, phải được xóa."""
    import inspect

    text = inspect.getsource(storage)
    assert "khi P2-4 đã merge" not in text and "khi P2-4 merge" not in text


# ---------------------------------------------------------------------------------------------
# AC-8 `<id>` đã có
# ---------------------------------------------------------------------------------------------


def test_existing_transfer_dir_raises_temp_exists(storage, root, record_for):
    old = root / ".teleport" / ID
    old.mkdir(parents=True)
    sentinel = old / "0.part"
    sentinel.write_bytes(payload(5000, seed=7))
    before = snapshot(old)
    with storage.ReceiveDir.open(root) as rd:
        with pytest.raises(storage.TempExistsError):
            rd.create_temp(ID, record_for(ID, [0]))
        other = rd.create_temp(ID2, record_for(ID2, [0]))  # lượt khác vẫn tạo được
        assert rd.remove_temp(other) is True
    assert snapshot(old) == before
    assert sentinel.read_bytes() == payload(5000, seed=7)


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_existing_transfer_entry_of_other_kind_raises_temp_exists(storage, tmp_path, kind, record_for):
    root = tmp_path / "recv"
    (root / ".teleport").mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"nan nhan")
    entry = root / ".teleport" / ID
    if kind == "file":
        entry.write_bytes(b"file cu")
    else:
        make_symlink(victim, entry, is_dir=False)
    before = snapshot(tmp_path)
    with storage.ReceiveDir.open(root) as rd, pytest.raises(storage.TempExistsError):
        rd.create_temp(ID, record_for(ID, [0]))
    assert snapshot(tmp_path) == before


# ---------------------------------------------------------------------------------------------
# Thư mục nhận bị xóa sau `open` (người dùng xóa khi app đang chạy)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("recreated_by_user", [False, True], ids=["mat-han", "nguoi-dung-tao-lai"])
def test_create_temp_recreates_deleted_receive_dir_and_finalize_lands_there(
    storage, root, record_for, recreated_by_user
):
    """Lỗi demo 2026-10-29: xóa `Downloads\\Teleport` khi app chạy → mọi lượt sau báo lỗi ghi đĩa.

    Giờ `create_temp` tạo lại thư mục nhận, và file nhận xong nằm đúng trong thư mục mới (POSIX:
    fd cũ trỏ vào thư mục đã xóa, phải mở lại; kể cả khi người dùng đã tự tạo lại thư mục).
    """
    with storage.ReceiveDir.open(root) as rd:
        first = rd.create_temp(ID, record_for(ID, [0]))
        assert rd.remove_temp(first) is True
        shutil.rmtree(root)
        if recreated_by_user:
            root.mkdir()
        temp = rd.create_temp(ID2, record_for(ID2, [10]))
        assert (root / ".teleport" / ID2 / "transfer.json").is_file()
        part = temp.create_part(0, 10)
        part.write_at(0, b"0123456789")
        final = rd.finalize(part, "a.txt")
        assert rd.remove_temp(temp) is True
    assert final == root / "a.txt"
    assert final.read_bytes() == b"0123456789"


def test_create_temp_does_not_recreate_parent_of_receive_dir(storage, tmp_path, record_for):
    """Cha cũng mất (ổ đã rút, hay cả `Downloads` bị xóa): không tạo cả cây, báo lỗi riêng."""
    root = tmp_path / "o-usb" / "Teleport"
    with storage.ReceiveDir.open(root) as rd:
        shutil.rmtree(tmp_path / "o-usb")
        with pytest.raises(storage.ReceiveDirMissingError):
            rd.create_temp(ID, record_for(ID, [0]))
        assert not (tmp_path / "o-usb").exists()
        # Lỗi không giữ `transfer_id`: cắm lại ổ thì lượt đó tạo được.
        root.mkdir(parents=True)
        temp = rd.create_temp(ID, record_for(ID, [0]))
        assert rd.remove_temp(temp) is True


def test_create_temp_when_receive_dir_name_is_taken_by_a_file(storage, root, record_for):
    with storage.ReceiveDir.open(root) as rd:
        shutil.rmtree(root)
        root.write_bytes(b"khong phai thu muc")
        with pytest.raises(storage.ReceiveDirMissingError):
            rd.create_temp(ID, record_for(ID, [0]))
    assert root.read_bytes() == b"khong phai thu muc"


def test_receive_dir_missing_error_is_a_storage_error_not_oserror(storage):
    assert issubclass(storage.ReceiveDirMissingError, storage.StorageError)
    assert not issubclass(storage.ReceiveDirMissingError, OSError)


# ---------------------------------------------------------------------------------------------
# AC-9 Liên kết và chủ của `.teleport`
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("existed", [False, True], ids=["chua-co", "da-co"])
@pytest.mark.parametrize("kind", ["symlink", "junction", "dangling"])
def test_temp_dir_swapped_for_link_after_open_is_rejected(storage, tmp_path, kind, existed, record_for):
    root = tmp_path / "recv"
    root.mkdir()
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "giu.txt").write_bytes(b"cua nan nhan")
    if existed:
        (root / ".teleport").mkdir()
    with storage.ReceiveDir.open(root) as rd:
        if existed:
            os.rmdir(root / ".teleport")
        link_dir(kind, victim, root / ".teleport")
        before = snapshot(tmp_path)
        with pytest.raises(storage.UnsafeReceiveDirError):
            rd.create_temp(ID, record_for(ID, [0]))
        assert snapshot(tmp_path) == before
    assert sorted(os.listdir(victim)) == ["giu.txt"]


@posix_only
def test_temp_dir_owned_by_stranger_is_rejected(storage, root, monkeypatch, record_for):
    temp_dir = root / ".teleport"
    temp_dir.mkdir(parents=True, mode=0o700)
    stranger = os.geteuid() + 4242  # khác euid và khác chủ thư mục nhận (chính là euid)
    fake_owner(monkeypatch, {identity(temp_dir): stranger})
    with pytest.raises(storage.UnsafeReceiveDirError), storage.ReceiveDir.open(root) as rd:
        rd.create_temp(ID, record_for(ID, [0]))
    monkeypatch.undo()
    assert os.listdir(temp_dir) == []


@posix_only
def test_temp_dir_owned_by_receive_dir_owner_is_accepted(storage, root, monkeypatch, record_for):
    # USB mount theo uid cố định: `.teleport` mang uid của chủ thư mục nhận, khác euid (D23).
    temp_dir = root / ".teleport"
    temp_dir.mkdir(parents=True, mode=0o700)
    owner = os.geteuid() + 4242
    fake_owner(monkeypatch, {identity(root): owner, identity(temp_dir): owner})
    with storage.ReceiveDir.open(root) as rd:
        temp = rd.create_temp(ID, record_for(ID, [0]))
        assert temp.path.is_dir()
        assert rd.remove_temp(temp) is True


@posix_only
@pytest.mark.parametrize("err", [errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EROFS, errno.EINVAL])
def test_unsupported_fchmod_is_ignored(storage, root, monkeypatch, err, record_for):
    temp_dir = root / ".teleport"
    temp_dir.mkdir(parents=True)
    os.chmod(temp_dir, 0o755)

    def fchmod(fd, mode):
        raise OSError(err, os.strerror(err))

    monkeypatch.setattr(os, "fchmod", fchmod)
    with storage.ReceiveDir.open(root) as rd:
        temp = rd.create_temp(ID, record_for(ID, [0]))
        assert temp.path.is_dir()
        assert rd.remove_temp(temp) is True


@posix_only
def test_other_fchmod_error_propagates(storage, root, monkeypatch, record_for):
    temp_dir = root / ".teleport"
    temp_dir.mkdir(parents=True)
    os.chmod(temp_dir, 0o755)

    def fchmod(fd, mode):
        raise OSError(errno.EIO, "loi I/O")

    monkeypatch.setattr(os, "fchmod", fchmod)
    with storage.ReceiveDir.open(root) as rd, pytest.raises(OSError) as exc:
        rd.create_temp(ID, record_for(ID, [0]))
    assert exc.value.errno == errno.EIO


# ---------------------------------------------------------------------------------------------
# AC-10 Giới hạn đường dẫn ở `open`
# ---------------------------------------------------------------------------------------------


def _limit_root(storage, monkeypatch, root, extra: int) -> int:
    max_path = units(os.path.abspath(root)) + extra
    monkeypatch.setattr(storage, "_path_limits", lambda r: storage.PathLimits(max_path, 255))
    return max_path


def test_open_rejects_root_without_room_for_temp_files(storage, root, monkeypatch):
    _limit_root(storage, monkeypatch, root, storage.TEMP_PATH_RESERVE - 1)
    with pytest.raises(storage.PathTooLongError), storage.ReceiveDir.open(root):
        pass


def _record_temp_paths(storage, monkeypatch) -> list[str]:
    """Ghi đường dẫn đầy đủ của mọi file trong thư mục tạm lúc `_write_atomic_in` sắp đổi tên (P3-3a):
    gồm cả tên tạm `<name>.<16 hex>.tmp`, file dài nhất của bố cục."""
    seen: list[str] = []
    real = storage._before_atomic_replace

    def spy(temp_path, name):
        seen.extend(os.path.join(str(temp_path), entry) for entry in os.listdir(temp_path))
        return real(temp_path, name)

    monkeypatch.setattr(storage, "_before_atomic_replace", spy)
    return seen


def test_root_at_exact_reserve_allows_whole_chain(storage, root, monkeypatch, record_for):
    # P3-3a: `finalize` chỉ nhận file kế tiếp (`record.verified == file_index`), nên file 999 (tên
    # `.part`/`.state` dài nhất) chỉ dùng để đo thư mục tạm; file cuối đi qua file 0.
    max_path = _limit_root(storage, monkeypatch, root, storage.TEMP_PATH_RESERVE)
    temp_paths = _record_temp_paths(storage, monkeypatch)
    with storage.ReceiveDir.open(root) as rd:
        temp = rd.create_temp(ID, record_for(ID, {0: 1, 999: 1}))
        last = temp.create_part(999, 1)
        assert units(str(last.path)) <= max_path
        last.write_at(0, b"\n")
        assert bytes(last.reread()) == hashlib.sha256(b"\n").digest()
        part = temp.create_part(0, 1)
        part.write_at(0, b"\n")
        final = rd.finalize(part, "a" * 246 + ".mp4")
        assert units(str(final)) <= max_path
        assert final.name.endswith(".mp4")
        assert final.read_bytes() == b"\n"
        assert rd.remove_temp(temp) is True
    # Mọi file của thư mục tạm, kể cả `transfer.json.<16 hex>.tmp`, phải vừa phần chừa `TEMP_PATH_RESERVE`
    # (architecture mục 4 “Độ dài đường dẫn”): không thì thư mục nhận đã được nhận ở `open` lại không
    # nhận được file.
    assert any(p.endswith(".tmp") for p in temp_paths)
    too_long = [p for p in temp_paths if units(p) > max_path]
    assert too_long == [], f"đường dẫn trong thư mục tạm vượt giới hạn: {too_long}"


@windows_only
def test_windows_real_root_of_181_units_works(storage, tmp_path, monkeypatch, record_for):
    base = str(tmp_path)
    if units(base) > 150:
        pytest.skip("tmp_path quá dài để dựng thư mục 181 đơn vị")
    root = nested_dir(base, 181)
    temp_paths = _record_temp_paths(storage, monkeypatch)
    with storage.ReceiveDir.open(root) as rd:
        temp = rd.create_temp(ID, record_for(ID, {0: 1, 999: 1}))
        last = temp.create_part(999, 1)
        # Spec P2-5 mục 2.2, D22: `<root>\.teleport\<id>` = root + 43 ≤ 247 (CreateDirectoryW khi chưa
        # bật long path); P3-3a (đã chốt): file dài nhất `transfer.json.<16 hex>.tmp` = root + 78 ≤ 259.
        # Kiểm trên đường dẫn thật, vì máy đã bật LongPathsEnabled thì Windows không tự chặn ở 247/259
        # và test chạy được cũng chưa chứng minh gì.
        assert units(str(temp.path)) == 181 + 43 <= 247
        assert units(str(last.path)) == 181 + 52 <= storage.WINDOWS_MAX_PATH
        last.write_at(0, b"x")
        assert bytes(last.reread()) == hashlib.sha256(b"x").digest()
        part = temp.create_part(0, 1)
        part.write_at(0, b"x")
        final = rd.finalize(part, "a" * 246 + ".mp4")
        assert units(str(final)) <= 259
        assert final.read_bytes() == b"x"
        assert rd.remove_temp(temp) is True
    assert any(p.endswith(".tmp") and "transfer.json." in p for p in temp_paths)
    assert max(units(p) for p in temp_paths) == 181 + 78 == storage.WINDOWS_MAX_PATH
    too_long = [p for p in temp_paths if units(p) > storage.WINDOWS_MAX_PATH]
    assert too_long == [], f"đường dẫn trong thư mục tạm vượt MAX_PATH: {too_long}"


def test_open_drive_root_without_writing(storage, tmp_path):
    # Ca biên spec mục 5: thư mục nhận là gốc ổ đĩa (`C:\`, `/`). Test không được ghi vào gốc ổ, nên
    # chỉ kiểm các bước không ghi gì: `open` (không tạo `.teleport`), `limits`, `volume_info`.
    # Ngân sách tên sát giới hạn được giả bằng `_path_limits` ở các test AC-10 và AC-22.
    anchor = Path(tmp_path).anchor
    temp_dir = os.path.join(anchor, ".teleport")
    if os.path.lexists(temp_dir):
        pytest.skip("gốc ổ đã có .teleport")
    with storage.ReceiveDir.open(anchor) as rd:
        assert rd.root == Path(anchor)
        assert units(str(rd.root)) + storage.TEMP_PATH_RESERVE <= rd.limits.max_path
        assert rd.volume_info().free_bytes >= 0
    assert not os.path.lexists(temp_dir)


@windows_only
def test_windows_real_root_of_182_units_rejected(storage, tmp_path):
    base = str(tmp_path)
    if units(base) > 150:
        pytest.skip("tmp_path quá dài để dựng thư mục 182 đơn vị")
    root = nested_dir(base, 182)
    # Với 182, `<root>\.teleport\<id>\transfer.json.<16 hex>.tmp` dài 260 > 259 (MAX_PATH).
    assert units(os.path.join(root, ".teleport", ID, "transfer.json." + "0" * 16 + ".tmp")) == 260
    with pytest.raises(storage.PathTooLongError), storage.ReceiveDir.open(root):
        pass
    assert not os.path.lexists(os.path.join(root, ".teleport"))


# ---------------------------------------------------------------------------------------------
# AC-11 POSIX dùng dir_fd
# ---------------------------------------------------------------------------------------------

TRACKED_OS = ("open", "mkdir", "unlink", "remove", "rmdir", "replace", "rename", "stat", "lstat", "utime")
TRACKED_LISTING = ("scandir", "listdir")


def _install_recorder(monkeypatch, phase: list[str]) -> list[tuple]:
    calls: list[tuple] = []
    for name in TRACKED_OS + TRACKED_LISTING:
        real = getattr(os, name)

        def wrapper(*args, _real=real, _name=name, **kwargs):
            calls.append((phase[0], _name, args, kwargs))
            return _real(*args, **kwargs)

        monkeypatch.setattr(os, name, wrapper)
    return calls


def _path_args(name: str, args: tuple, kwargs: dict) -> list[tuple[object, object]]:
    if name in ("replace", "rename"):
        return [(args[0], kwargs.get("src_dir_fd")), (args[1], kwargs.get("dst_dir_fd"))]
    if not args:
        return [(kwargs.get("path", "."), kwargs.get("dir_fd"))]
    return [(args[0], kwargs.get("dir_fd"))]


def _violations(calls, roots: set[str], *, exempt: set[str] = frozenset()) -> list[str]:
    bad = []
    for phase, name, args, kwargs in calls:
        for path, dir_fd in _path_args(name, args, kwargs):
            if isinstance(path, int):
                continue
            s = os.fsdecode(os.fspath(path))
            if os.path.isabs(s):
                if s in exempt:
                    continue
                if any(s == r or s.startswith(r + os.sep) for r in roots):
                    bad.append(f"{phase}: os.{name}({s!r}) dùng đường dẫn tuyệt đối trong thư mục nhận")
            elif type(dir_fd) is not int:
                bad.append(f"{phase}: os.{name}({s!r}) tương đối mà không có dir_fd")
    return bad


@posix_only
def test_posix_operations_inside_root_use_dir_fd(storage, root, monkeypatch, record_for):
    roots = {os.path.abspath(root), os.path.realpath(root)}
    with storage.ReceiveDir.open(root) as rd:
        phase = ["create_temp"]
        calls = _install_recorder(monkeypatch, phase)
        temp = rd.create_temp(ID, record_for(ID, [10, 5]))
        phase[0] = "create_part"
        part = temp.create_part(0, 10)
        part.write_at(0, b"0123456789")
        leftover = temp.create_part(1, 5)
        leftover.write_at(0, b"abcde")
        phase[0] = "finalize"
        final = rd.finalize(part, "a.txt", mtime_ms=1_700_000_000_000)
        phase[0] = "remove_temp"
        assert rd.remove_temp(temp) is True
        monkeypatch.undo()
    assert final.read_bytes() == b"0123456789"
    assert _violations(calls, roots) == []
    listing_opens = [
        c
        for c in calls
        if c[0] == "finalize" and c[1] == "open" and c[2][0] == "." and type(c[3].get("dir_fd")) is int
    ]
    assert listing_opens, "finalize phải liệt kê qua một os.open('.', …, dir_fd=…) mới (D25)"
    phases = {c[0] for c in calls}
    assert {"create_temp", "create_part", "finalize", "remove_temp"} <= phases


@posix_only
def test_posix_open_checks_existing_temp_dir_through_dir_fd(storage, root, monkeypatch):
    (root / ".teleport").mkdir(parents=True, mode=0o700)
    roots = {os.path.abspath(root), os.path.realpath(root)}
    # Bước mở chính thư mục nhận (và các thư mục cha) được dùng đường dẫn tuyệt đối.
    exempt = {os.path.abspath(root), os.path.realpath(root)}
    calls = _install_recorder(monkeypatch, ["open"])
    with storage.ReceiveDir.open(root):
        pass
    monkeypatch.undo()
    assert _violations(calls, roots, exempt=exempt) == []
    assert any(
        c[1] in ("open", "stat", "lstat")
        and c[2]
        and c[2][0] == ".teleport"
        and type(c[3].get("dir_fd")) is int
        for c in calls
    ), "open phải kiểm `.teleport` có sẵn qua dir_fd"


# ---------------------------------------------------------------------------------------------
# AC-12 `create_part`
# ---------------------------------------------------------------------------------------------


def test_create_part_creates_empty_file(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, {3: 10}))
    part = temp.create_part(3, 10)
    assert part.path == temp.path / "3.part"
    assert part.path.is_file()
    assert os.path.getsize(part.path) == 0
    assert (part.file_index, part.size, part.block_count) == (3, 10, 1)
    assert not part.closed


@pytest.mark.parametrize("size", [0, 1, BS, BS + 1, 1 << 42])
def test_create_part_block_count_matches_core(rd, size, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
    assert part.block_count == block_count(size)
    assert os.path.getsize(part.path) == 0  # không cấp trước dung lượng


@posix_only
def test_part_and_final_file_follow_umask(rd, record_for):
    # D10: `.part` tạo với 0o666 và umask vẫn áp, nên file cuối mang quyền như file tải về thường
    # (thư mục `0o700` mới là thứ che dữ liệu đang nhận).
    mask = os.umask(0o022)
    os.umask(mask)
    expected = 0o666 & ~mask
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    assert stat.S_IMODE(os.stat(part.path).st_mode) == expected
    part.write_at(0, b"abc")
    final = rd.finalize(part, "a.txt")
    assert stat.S_IMODE(os.stat(final).st_mode) == expected


@windows_only
def test_finalized_file_inherits_receive_dir_acl_on_windows(storage, root, record_for):
    # D10 (“file đã xong phải dùng được như file trình duyệt tải về”), architecture §4 “Thư mục
    # nhận”: trên Windows, file nhận xong mang DACL kế thừa từ thư mục nhận y như một file tạo thẳng
    # trong đó: DACL không bị bảo vệ khỏi kế thừa, cùng các ACE. Thư mục nhận được cấp thêm quyền
    # đọc cho BUILTIN\Users như một thư mục chia sẻ; file nhận xong phải mang ACE đó.
    # Hồi quy soat-code (trung bình): `os.mkdir(path, 0o700)` từ Python 3.12.4 gắn DACL được bảo vệ
    # (chỉ SYSTEM, Administrators, OWNER RIGHTS), `.part` kế thừa nó và `MoveFileExW` giữ nguyên.
    root.mkdir()
    icacls = os.path.join(os.environ.get("SYSTEMROOT", r"C:\Windows"), "System32", "icacls.exe")
    subprocess.run(
        [icacls, str(root), "/grant", "*S-1-5-32-545:(OI)(CI)(RX)"], check=True, capture_output=True
    )
    normal = root / "normal.txt"
    normal.write_bytes(b"x")
    expected_protected, expected = windows_dacl(normal)
    # Đối chứng: file tạo thẳng trong thư mục nhận kế thừa ACL, kể cả ACE vừa cấp cho Users (BU).
    assert not expected_protected
    assert ";;;BU)" in expected
    with storage.ReceiveDir.open(root) as rd:
        part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
        part.write_at(0, b"abc")
        final = rd.finalize(part, "a.txt")
        protected, actual = windows_dacl(final)
    assert not protected, actual
    assert actual == expected


def test_create_part_accepts_last_file_index(rd, record_for):
    part = rd.create_temp(ID, record_for(ID, {999: 0})).create_part(999, 0)
    assert part.path.name == "999.part"


def test_create_part_same_index_twice_raises_value_error(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [1]))
    part = temp.create_part(0, 1)
    with pytest.raises(ValueError):
        temp.create_part(0, 1)
    part.close()
    with pytest.raises(ValueError):
        temp.create_part(0, 1)
    # P3-3a: `create_part` tạo thêm header `0.state`; thư mục tạm luôn có `transfer.json`.
    assert sorted(os.listdir(temp.path)) == ["0.part", "0.state", "transfer.json"]


def test_create_part_over_existing_file_raises_file_exists(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [3]))
    planted = temp.path / "0.part"
    planted.write_bytes(b"cu")
    with pytest.raises(FileExistsError):
        temp.create_part(0, 3)
    assert planted.read_bytes() == b"cu"
    assert not os.path.lexists(temp.path / "0.state")  # `.part` tạo trước, lỗi thì không có header


def test_create_part_over_planted_symlink_raises_and_keeps_victim(rd, tmp_path, record_for):
    temp = rd.create_temp(ID, record_for(ID, [8]))
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"nan nhan")
    make_symlink(victim, temp.path / "0.part", is_dir=False)
    with pytest.raises(FileExistsError):
        temp.create_part(0, 8)
    assert victim.read_bytes() == b"nan nhan"
    assert os.path.islink(temp.path / "0.part")


@pytest.mark.parametrize(
    ("file_index", "size"),
    [
        (-1, 1),
        (1000, 1),
        (True, 1),
        (False, 1),
        (1.0, 1),
        ("1", 1),
        (None, 1),
        (0, -1),
        (0, (1 << 42) + 1),
        (0, True),
        (0, 1.0),
        (0, "1"),
        (0, None),
    ],
)
def test_create_part_rejects_bad_arguments(rd, file_index, size, record_for):
    temp = rd.create_temp(ID, record_for(ID, [1]))
    with pytest.raises(ValueError):
        temp.create_part(file_index, size)
    assert os.listdir(temp.path) == ["transfer.json"]  # P3-3a: chỉ có bản ghi lượt, không `.part`/`.state`


# ---------------------------------------------------------------------------------------------
# AC-13 `write_at`
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_writes_in_allowed_random_order_give_exact_file(rd, seed, record_for):
    size = 4 * BS + 777  # 5 khối, khối cuối ngắn
    data = payload(size, seed)
    count = block_count(size)
    part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
    rng = random.Random(seed)
    end = 0
    written: set[int] = set()
    steps = 0
    while len(written) < count or steps < 3 * count:
        allowed = [i for i in range(count) if i * BS <= end]
        i = rng.choice(allowed)
        if rng.random() < 0.3:
            part.write_at(i, b"\x00" * block_length(size, i))  # ghi rác rồi ghi lại đúng
        part.write_at(i, data[i * BS : i * BS + block_length(size, i)])
        end = max(end, i * BS + block_length(size, i))
        written.add(i)
        steps += 1
    assert part.path.read_bytes() == data


@pytest.mark.parametrize("kind", ["bytes", "bytearray", "memoryview"])
def test_write_at_accepts_bytes_like(rd, kind, record_for):
    data = payload(BS + 10)
    part = rd.create_temp(ID, record_for(ID, {0: len(data)})).create_part(0, len(data))
    convert = {"bytes": bytes, "bytearray": bytearray, "memoryview": lambda b: memoryview(bytearray(b))}[kind]
    part.write_at(0, convert(data[:BS]))
    part.write_at(1, convert(data[BS:]))
    assert part.path.read_bytes() == data


def test_write_at_memoryview_length_is_nbytes(rd, record_for):
    # Spec mục 3.3: với memoryview, độ dài là `nbytes` chứ không phải số phần tử.
    data = b"\r\n\x1a\nABCD"
    part = rd.create_temp(ID, record_for(ID, {0: len(data)})).create_part(0, len(data))
    view = memoryview(bytearray(data)).cast("I")
    assert len(view) != view.nbytes == len(data)
    part.write_at(0, view)
    assert part.path.read_bytes() == data


def _bad_write_cases():
    noncontiguous = memoryview(bytearray(2 * BS))[::2]
    assert noncontiguous.nbytes == BS and not noncontiguous.c_contiguous
    return [
        ("short-block0", 0, BS - 1),
        ("long-block0", 0, BS + 1),
        ("short-last", 2, 99),
        ("long-last", 2, 101),
        ("empty", 1, 0),
        ("index-negative", -1, BS),
        ("index-too-big", 3, 100),
        ("index-bool", True, BS),
        ("index-float", 1.0, BS),
        ("index-str", "1", BS),
        ("index-none", None, BS),
        ("noncontiguous", 1, noncontiguous),
        ("str", 1, "x" * BS),
        ("list", 1, [0] * BS),
        ("none", 1, None),
    ]


@pytest.mark.parametrize("case", _bad_write_cases(), ids=lambda c: c[0])
def test_write_at_rejects_bad_arguments_and_leaves_file_unchanged(rd, case, record_for):
    _, index, spec = case
    size = 2 * BS + 100
    data = payload(size)
    part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
    # _end = 2·BS: mọi chỉ số 0…2 hợp lệ về vị trí, nên lỗi chỉ có thể đến từ tham số đang thử.
    part.write_at(0, data[:BS])
    part.write_at(1, data[BS : 2 * BS])
    before = part.path.read_bytes()
    bad = b"\n" * spec if isinstance(spec, int) else spec
    with pytest.raises(ValueError):
        part.write_at(index, bad)
    assert part.path.read_bytes() == before
    part.write_at(2, data[2 * BS :])  # vẫn dùng được
    assert part.path.read_bytes() == data


def _write_seam() -> str:
    return "write" if WINDOWS else "pwrite"


def test_short_writes_are_continued(rd, monkeypatch, record_for):
    size = BS + 1000
    data = payload(size)
    part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
    name = _write_seam()
    real = getattr(os, name)
    calls = []

    def short(fd, buf, *rest):
        view = memoryview(buf)
        calls.append(view.nbytes)
        return real(fd, view[: max(1, view.nbytes // 3)], *rest)

    monkeypatch.setattr(os, name, short)
    part.write_at(0, data[:BS])
    part.write_at(1, data[BS:])
    monkeypatch.undo()
    assert len(calls) > 2
    assert part.path.read_bytes() == data


def test_disk_full_error_propagates_and_part_stays_open(rd, monkeypatch, record_for):
    data = payload(100)
    part = rd.create_temp(ID, record_for(ID, {0: 100})).create_part(0, 100)

    def full(*args, **kwargs):
        raise OSError(errno.ENOSPC, "het cho")

    monkeypatch.setattr(os, _write_seam(), full)
    with pytest.raises(OSError) as exc:
        part.write_at(0, data)
    monkeypatch.undo()
    assert exc.value.errno == errno.ENOSPC
    assert not part.closed
    part.write_at(0, data)
    assert part.path.read_bytes() == data


SIZE4 = 3 * BS + 100  # 4 khối, khối cuối ngắn


def _spy_writes(monkeypatch) -> list[str]:
    calls: list[str] = []
    for name in ("write", "pwrite", "pwritev", "writev"):
        if not hasattr(os, name):
            continue
        real = getattr(os, name)

        def spy(*args, _real=real, _name=name, **kwargs):
            calls.append(_name)
            return _real(*args, **kwargs)

        monkeypatch.setattr(os, name, spy)
    return calls


def test_gap_write_on_empty_file_rejected_before_io(storage, rd, monkeypatch, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: SIZE4})).create_part(0, SIZE4)
    writes = _spy_writes(monkeypatch)
    with pytest.raises(storage.WriteGapError) as exc:
        part.write_at(2, payload(BS))
    monkeypatch.undo()
    assert isinstance(exc.value, storage.StorageError)
    assert not isinstance(exc.value, ValueError)
    assert writes == []
    assert os.path.getsize(part.path) == 0
    assert not part.closed


def test_gap_after_two_blocks_rejected(storage, rd, record_for):
    data = payload(SIZE4)
    part = rd.create_temp(ID, record_for(ID, {0: SIZE4})).create_part(0, SIZE4)
    part.write_at(0, data[:BS])
    part.write_at(1, data[BS : 2 * BS])
    with pytest.raises(storage.WriteGapError):
        part.write_at(3, data[3 * BS :])
    assert part.path.read_bytes() == data[: 2 * BS]


def test_sequential_writes_and_rewrite_allowed(rd, record_for):
    data = payload(SIZE4)
    part = rd.create_temp(ID, record_for(ID, {0: SIZE4})).create_part(0, SIZE4)
    for i in range(4):
        part.write_at(i, data[i * BS : i * BS + block_length(SIZE4, i)])
    part.write_at(1, data[BS : 2 * BS])
    assert part.path.read_bytes() == data


def test_write_after_close_raises_value_error(rd, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    part.close()
    part.close()  # gọi lại được
    assert part.closed
    with pytest.raises(ValueError):
        part.write_at(0, b"abc")


# ---------------------------------------------------------------------------------------------
# H2 Chốt chặn lỗ (thuộc tính)
# ---------------------------------------------------------------------------------------------


@pytest.mark.slow
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    nblocks=st.integers(min_value=1, max_value=6),
    last=st.integers(min_value=1, max_value=BS - 1),
    ops=st.lists(st.integers(min_value=0, max_value=5), min_size=1, max_size=10),
)
def test_property_write_succeeds_iff_no_gap(storage, nblocks, last, ops, record_for):
    size = (nblocks - 1) * BS + last
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, storage.ReceiveDir.open(d) as rd:
        part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
        model = bytearray()
        end = 0
        for step, raw in enumerate(ops):
            i = raw % nblocks
            length = block_length(size, i)
            block = bytes([(step * 31 + i) % 251 + 1]) * length
            offset = i * BS
            if offset <= end:
                part.write_at(i, block)
                model[offset : offset + length] = block
                end = max(end, offset + length)
            else:
                with pytest.raises(storage.WriteGapError):
                    part.write_at(i, block)
            assert os.path.getsize(part.path) == end
        part.close()
        assert part.path.read_bytes() == bytes(model)


# ---------------------------------------------------------------------------------------------
# AC-14 `sync`
# ---------------------------------------------------------------------------------------------


def _same_file(fd: int, path) -> bool:
    return os.path.samestat(os.fstat(fd), os.stat(path))


@not_macos
def test_sync_fsyncs_the_part_fd(rd, monkeypatch, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    part.write_at(0, b"abc")
    real = os.fsync
    synced = []

    def spy(fd):
        synced.append(_same_file(fd, part.path))
        return real(fd)

    monkeypatch.setattr(os, "fsync", spy)
    part.sync()
    monkeypatch.undo()
    assert any(synced)


def test_sync_goes_through_full_fsync_seam(storage, rd, monkeypatch, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    seen = []
    monkeypatch.setattr(storage, "_full_fsync", lambda fd: seen.append(_same_file(fd, part.path)))
    part.sync()
    assert seen == [True]


def test_sync_error_propagates(storage, rd, monkeypatch, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)

    def boom(fd):
        raise OSError(errno.EIO, "loi fsync")

    monkeypatch.setattr(storage, "_full_fsync", boom)
    with pytest.raises(OSError) as exc:
        part.sync()
    assert exc.value.errno == errno.EIO


def test_sync_after_close_raises_value_error(rd, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    part.close()
    with pytest.raises(ValueError):
        part.sync()


@macos_only
def test_macos_sync_uses_f_fullfsync(rd, monkeypatch, record_for):
    import fcntl

    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    real = fcntl.fcntl
    commands = []

    def spy(fd, cmd, *args):
        commands.append((cmd, _same_file(fd, part.path)))
        return real(fd, cmd, *args)

    monkeypatch.setattr(fcntl, "fcntl", spy)
    part.sync()
    assert (fcntl.F_FULLFSYNC, True) in commands


@macos_only
def test_macos_unsupported_full_fsync_falls_back_to_fsync(rd, monkeypatch, record_for):
    import fcntl

    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    real_fcntl = fcntl.fcntl
    real_fsync = os.fsync
    fsynced = []

    def no_full(fd, cmd, *args):
        if cmd == fcntl.F_FULLFSYNC:
            raise OSError(errno.ENOTSUP, "khong ho tro")
        return real_fcntl(fd, cmd, *args)

    def spy_fsync(fd):
        fsynced.append(_same_file(fd, part.path))
        return real_fsync(fd)

    monkeypatch.setattr(fcntl, "fcntl", no_full)
    monkeypatch.setattr(os, "fsync", spy_fsync)
    part.sync()
    assert any(fsynced)


@macos_only
def test_macos_full_fsync_io_error_propagates(rd, monkeypatch, record_for):
    import fcntl

    part = rd.create_temp(ID, record_for(ID, {0: 3})).create_part(0, 3)
    real_fcntl = fcntl.fcntl

    def broken(fd, cmd, *args):
        if cmd == fcntl.F_FULLFSYNC:
            raise OSError(errno.EIO, "loi I/O")
        return real_fcntl(fd, cmd, *args)

    monkeypatch.setattr(fcntl, "fcntl", broken)
    with pytest.raises(OSError) as exc:
        part.sync()
    assert exc.value.errno == errno.EIO


# ---------------------------------------------------------------------------------------------
# AC-15 `reread`
# ---------------------------------------------------------------------------------------------

SIZE_R = 3 * BS + 123


@pytest.fixture
def full_part(rd, record_for):
    data = payload(SIZE_R, seed=5)
    part = rd.create_temp(ID, record_for(ID, {0: SIZE_R})).create_part(0, SIZE_R)
    write_all(part, data)
    return part, data


def test_reread_returns_concatenated_block_hashes(full_part):
    part, data = full_part
    digests = part.reread()
    assert type(digests) is bytearray
    assert len(digests) == 32 * 4
    expected = block_hashes(data)
    assert bytes(digests) == expected
    leaves = [expected[i : i + 32] for i in range(0, len(expected), 32)]
    assert merkle_root(digests) == merkle_by_hand(leaves)


@pytest.mark.parametrize("k", [0, 1, 2, 3])
def test_reread_detects_one_flipped_byte_in_block(full_part, k):
    part, data = full_part
    pos = k * BS + 7
    with open(part.path, "r+b") as f:  # handle riêng, không qua PartFile
        f.seek(pos)
        f.write(bytes([data[pos] ^ 0xFF]))
    digests = part.reread()
    good = block_hashes(data)
    for i in range(4):
        same = digests[32 * i : 32 * i + 32] == good[32 * i : 32 * i + 32]
        assert same == (i != k), i


def test_reread_cuts_trailing_garbage_then_syncs(storage, full_part, monkeypatch):
    part, data = full_part
    with open(part.path, "ab") as f:
        f.write(b"rac" * 1000)
    events: list[tuple] = []
    real_truncate = os.ftruncate
    real_full = storage._full_fsync

    def spy_truncate(fd, length):
        events.append(("truncate", length))
        return real_truncate(fd, length)

    def spy_full(fd):
        events.append(("sync",))
        return real_full(fd)

    monkeypatch.setattr(os, "ftruncate", spy_truncate)
    monkeypatch.setattr(storage, "_full_fsync", spy_full)
    digests = part.reread()
    monkeypatch.undo()
    assert bytes(digests) == block_hashes(data)
    assert os.path.getsize(part.path) == SIZE_R
    assert ("truncate", SIZE_R) in events
    assert ("sync",) in events[events.index(("truncate", SIZE_R)) + 1 :]


def test_reread_short_file_gives_zero_hashes_and_resets_end(storage, full_part):
    part, data = full_part
    with open(part.path, "r+b") as f:
        f.truncate(BS + 10)
    digests = part.reread()
    assert digests[:32] == block_hashes(data)[:32]
    assert digests[32:] == bytes(96)
    assert os.path.getsize(part.path) == BS + 10
    part.write_at(1, data[BS : 2 * BS])
    with pytest.raises(storage.WriteGapError):
        part.write_at(3, data[3 * BS :])


def test_reread_empty_file(rd, record_for):
    part = rd.create_temp(ID, record_for(ID, {0: 0})).create_part(0, 0)
    digests = part.reread()
    assert type(digests) is bytearray
    assert digests == bytearray()


def test_reread_with_stop_already_set(storage, full_part):
    part, _ = full_part
    ev = threading.Event()
    ev.set()
    with pytest.raises(storage.RereadStopped):
        part.reread(stop=ev)


def test_reread_unset_stop_reads_everything(full_part):
    part, data = full_part
    assert bytes(part.reread(stop=threading.Event())) == block_hashes(data)


class LateStop(threading.Event):
    """`is_set()` trả True từ lần gọi thứ 3."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def is_set(self) -> bool:
        self.calls += 1
        return self.calls >= 3


def test_reread_stops_midway_within_a_block(storage, rd, monkeypatch, record_for):
    block = payload(BS, seed=9)
    part = rd.create_temp(ID, record_for(ID, {0: 32 * BS})).create_part(0, 32 * BS)
    for i in range(32):
        part.write_at(i, block)
    read = [0]

    class CountingFileIO(io.FileIO):
        def readinto(self, buffer):
            n = super().readinto(buffer)
            read[0] += n or 0
            return n

    real_read = os.read

    def counting_read(fd, n):
        out = real_read(fd, n)
        read[0] += len(out)
        return out

    monkeypatch.setattr(io, "FileIO", CountingFileIO)
    monkeypatch.setattr(os, "read", counting_read)
    part.reread()  # đối chứng: bộ đếm thấy đủ mọi byte của một lượt đọc trọn vẹn
    assert read[0] == 32 * BS
    read[0] = 0
    with pytest.raises(storage.RereadStopped):
        part.reread(stop=LateStop())
    monkeypatch.undo()
    assert read[0] < 32 * BS
    # `stop` được xét trước mỗi khối: lần gọi thứ 3 đến muộn nhất trước khối 2.
    assert read[0] <= 2 * BS


@pytest.mark.parametrize(
    "stop",
    [object(), True, 1, "dung", lambda: True, asyncio.Event()],
    ids=["object", "bool", "int", "str", "callable", "asyncio-event"],
)
def test_reread_rejects_non_event_stop(full_part, stop):
    part, _ = full_part
    with pytest.raises(ValueError):
        part.reread(stop=stop)


def test_reread_after_close_raises_value_error(full_part):
    part, _ = full_part
    part.close()
    with pytest.raises(ValueError):
        part.reread()


def test_reread_memory_peak_is_bounded(rd, record_for):
    block = payload(BS, seed=11)
    part = rd.create_temp(ID, record_for(ID, {0: 32 * BS})).create_part(0, 32 * BS)
    for i in range(32):
        part.write_at(i, block)
    tracemalloc.start()
    try:
        tracemalloc.reset_peak()
        digests = part.reread()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 4 * BS, peak
    assert bytes(digests) == hashlib.sha256(block).digest() * 32


@posix_only
def test_reread_reads_own_fd_not_the_path(full_part, tmp_path):
    part, data = full_part
    other = tmp_path / "khac"
    other.write_bytes(b"x" * SIZE_R)
    os.replace(other, part.path)  # mục thư mục đổi giữa chừng
    assert bytes(part.reread()) == block_hashes(data)


# ---------------------------------------------------------------------------------------------
# H3 `reread` (thuộc tính)
# ---------------------------------------------------------------------------------------------


@pytest.mark.slow
@settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    nblocks=st.integers(min_value=1, max_value=3),
    last=st.integers(min_value=1, max_value=BS),
    flips=st.sets(st.integers(min_value=0, max_value=2), max_size=3),
    tail=st.one_of(
        st.none(),
        st.tuples(st.just("cut"), st.integers(min_value=0, max_value=3 * BS)),
        st.tuples(st.just("append"), st.integers(min_value=1, max_value=5000)),
    ),
)
def test_property_reread_reports_each_block(storage, nblocks, last, flips, tail, record_for):
    size = (nblocks - 1) * BS + last
    data = random.Random(size).randbytes(size)
    flips = {k for k in flips if k < nblocks}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d, storage.ReceiveDir.open(d) as rd:
        part = rd.create_temp(ID, record_for(ID, {0: size})).create_part(0, size)
        write_all(part, data)
        mutated = bytearray(data)
        for k in flips:
            pos = k * BS + (k * 7919) % block_length(size, k)
            mutated[pos] ^= 0x5A
        if tail is not None and tail[0] == "cut":
            mutated = mutated[: tail[1] % (size + 1)]
        elif tail is not None:
            mutated += b"\xee" * tail[1]
        with open(part.path, "r+b") as f:
            f.write(mutated)
            f.truncate(len(mutated))
        digests = part.reread()
        assert len(digests) == 32 * nblocks
        for i in range(nblocks):
            start = i * BS
            end = start + block_length(size, i)
            got = bytes(digests[32 * i : 32 * i + 32])
            if end > len(mutated):
                assert got == bytes(32), i
            elif i in flips:
                assert got != hashlib.sha256(data[start:end]).digest(), i
                assert got == hashlib.sha256(mutated[start:end]).digest(), i
            else:
                assert got == hashlib.sha256(data[start:end]).digest(), i
        assert os.path.getsize(part.path) == min(len(mutated), size)


# ---------------------------------------------------------------------------------------------
# AC-24, AC-25 `remove_temp`
# ---------------------------------------------------------------------------------------------


def test_remove_temp_deletes_own_parts_even_when_open(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [10, 0]))
    p0 = temp.create_part(0, 10)
    p0.write_at(0, b"0123456789")
    p1 = temp.create_part(1, 0)
    assert rd.remove_temp(temp) is True
    assert not os.path.lexists(temp.path)
    assert temp.closed and p0.closed and p1.closed
    assert (rd.root / ".teleport").is_dir()  # không xóa `.teleport` (D7)
    assert rd.remove_temp(temp) is True  # gọi lại


def test_remove_temp_of_empty_temp(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [0]))
    assert rd.remove_temp(temp) is True
    assert os.listdir(rd.root / ".teleport") == []


def test_remove_temp_keeps_finalized_file(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [3, 3]))
    done = temp.create_part(0, 3)
    done.write_at(0, b"xon")
    final = rd.finalize(done, "a.txt")
    pending = temp.create_part(1, 3)
    pending.write_at(0, b"dan")
    assert rd.remove_temp(temp) is True
    assert final.read_bytes() == b"xon"
    assert sorted(os.listdir(rd.root)) == sorted([".teleport", "a.txt"])


def test_remove_temp_leaves_foreign_file_and_dir(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [3]))
    part = temp.create_part(0, 3)
    part.write_at(0, b"abc")
    foreign = temp.path / "la.bin"
    foreign.write_bytes(b"file la")
    assert rd.remove_temp(temp) is False
    assert foreign.read_bytes() == b"file la"
    assert temp.path.is_dir()
    assert not os.path.lexists(part.path)
    assert temp.closed
    # Gọi lại: chỉ kiểm lại `<id>` còn hay không, không xóa gì thêm.
    foreign.unlink()
    assert rd.remove_temp(temp) is False
    assert temp.path.is_dir()
    os.rmdir(temp.path)
    assert rd.remove_temp(temp) is True


def test_remove_temp_keeps_part_replaced_by_other_file(rd, record_for):
    temp = rd.create_temp(ID, record_for(ID, [4]))
    part = temp.create_part(0, 4)
    part.write_at(0, b"mine")
    part.close()
    other = temp.path / "khac.tmp"
    other.write_bytes(b"ours")  # cùng kích thước, khác danh tính
    os.replace(other, part.path)
    assert rd.remove_temp(temp) is False
    assert part.path.read_bytes() == b"ours"


def test_remove_temp_keeps_part_replaced_by_symlink(rd, tmp_path, record_for):
    temp = rd.create_temp(ID, record_for(ID, [4]))
    part = temp.create_part(0, 4)
    part.write_at(0, b"mine")
    part.close()
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"nan nhan")
    os.unlink(part.path)
    make_symlink(victim, part.path, is_dir=False)
    assert rd.remove_temp(temp) is False
    assert os.path.islink(part.path)
    assert victim.read_bytes() == b"nan nhan"


def test_remove_temp_does_not_touch_other_transfer(rd, record_for):
    t1 = rd.create_temp(ID, record_for(ID, [3]))
    t2 = rd.create_temp(ID2, record_for(ID2, [3 + BS]))
    p1 = t1.create_part(0, 3)
    p1.write_at(0, b"one")
    p2 = t2.create_part(0, 3 + BS)
    p2.write_at(0, b"t" * BS)
    assert rd.remove_temp(t1) is True
    assert t2.path.is_dir()
    assert not t2.closed and not p2.closed
    p2.write_at(1, b"two")  # vẫn ghi được
    assert p2.path.read_bytes() == b"t" * BS + b"two"


def test_remove_temp_of_other_receive_dir_raises(storage, tmp_path, record_for):
    with storage.ReceiveDir.open(tmp_path / "a") as rd1, storage.ReceiveDir.open(tmp_path / "b") as rd2:
        temp = rd2.create_temp(ID, record_for(ID, [0]))
        with pytest.raises(ValueError):
            rd1.remove_temp(temp)
        assert temp.path.is_dir() and not temp.closed
        assert rd2.remove_temp(temp) is True
        with pytest.raises(ValueError):
            rd1.remove_temp(temp)  # kể cả khi temp đã bị xóa


@pytest.mark.parametrize("not_temp", [None, ID, object()], ids=["none", "str", "object"])
def test_remove_temp_rejects_non_temp(rd, not_temp):
    with pytest.raises(ValueError):
        rd.remove_temp(not_temp)


def _flaky_unlink(monkeypatch, suffix: str, failures: int | None) -> list[str]:
    """Vá os.unlink/os.remove: mục tên kết thúc bằng `suffix` ném PermissionError `failures` lần đầu
    (None = mãi mãi)."""
    calls: list[str] = []
    for name in ("unlink", "remove"):
        real = getattr(os, name)

        def flaky(path, *args, _real=real, **kwargs):
            base = os.path.basename(os.fsdecode(path)) if not isinstance(path, int) else ""
            if base.endswith(suffix):
                calls.append(base)
                if failures is None or len(calls) <= failures:
                    raise PermissionError(errno.EACCES, "dang bi giu")
            return _real(path, *args, **kwargs)

        monkeypatch.setattr(os, name, flaky)
    return calls


def test_remove_temp_retries_unlink_permission_error(rd, monkeypatch, quick_retry, record_for):
    temp = rd.create_temp(ID, record_for(ID, [3]))
    part = temp.create_part(0, 3)
    part.write_at(0, b"abc")
    calls = _flaky_unlink(monkeypatch, ".part", failures=2)
    assert rd.remove_temp(temp) is True
    monkeypatch.undo()
    assert len(calls) >= 3
    assert not os.path.lexists(temp.path)


# spec-fix-app (1c): mọi file của bố cục lượt (không chỉ `.part`) được thử lại khi `unlink` gặp
# `PermissionError` (chương trình ngoài như trình quét virus giữ file một lúc; architecture mục 4).
LAYOUT_SUFFIXES = pytest.mark.parametrize("suffix", [".part", ".state", "transfer.json"])


@LAYOUT_SUFFIXES
def test_remove_temp_retries_permission_error_once_for_each_layout_file(
    rd, monkeypatch, quick_retry, record_for, suffix
):
    temp = rd.create_temp(ID, record_for(ID, [3]))
    part = temp.create_part(0, 3)
    part.write_at(0, b"abc")
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(temp.path))
    calls = _flaky_unlink(monkeypatch, suffix, failures=1)
    assert rd.remove_temp(temp) is True
    monkeypatch.undo()
    assert len(calls) == 2, calls  # lần đầu bị từ chối, lần thử lại xóa được
    assert not os.path.lexists(temp.path)


@LAYOUT_SUFFIXES
def test_cleanup_retries_permission_error_once_for_each_layout_file(
    rd, root, monkeypatch, quick_retry, record_for, suffix
):
    """`cleanup` xóa lượt quá ngưỡng qua cùng đường xóa theo bố cục: thử lại như `remove_temp`."""
    other = "c" * 32  # lượt của node khác: ngưỡng `retention`
    temp = rd.create_temp(ID, record_for(ID, [3], receiver=other))
    part = temp.create_part(0, 3)
    part.write_at(0, b"abc")
    rd.close_temp(temp)
    calls = _flaky_unlink(monkeypatch, suffix, failures=1)
    wall = time.time() + 3600
    removed = rd.cleanup(wall, own_device_id="e" * 32, skip=frozenset(), retention=60.0)
    monkeypatch.undo()
    assert removed == 1
    assert len(calls) == 2, calls
    assert not os.path.lexists(temp.path)
    assert (root / ".teleport").is_dir()


def test_remove_temp_retries_rmdir_permission_error(rd, monkeypatch, quick_retry, record_for):
    temp = rd.create_temp(ID, record_for(ID, [0]))
    real = os.rmdir
    calls = []

    def flaky(path, *args, **kwargs):
        calls.append(path)
        if len(calls) <= 2:
            raise PermissionError(errno.EACCES, "dang bi giu")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, "rmdir", flaky)
    assert rd.remove_temp(temp) is True
    monkeypatch.undo()
    assert len(calls) >= 3
    assert not os.path.lexists(temp.path)


def test_remove_temp_never_raises_os_error(rd, monkeypatch, quick_retry, record_for):
    temp = rd.create_temp(ID, record_for(ID, [3]))
    part = temp.create_part(0, 3)
    part.write_at(0, b"abc")
    _flaky_unlink(monkeypatch, ".part", failures=None)

    def broken_rmdir(*args, **kwargs):
        raise OSError(errno.EIO, "loi I/O")

    monkeypatch.setattr(os, "rmdir", broken_rmdir)
    assert rd.remove_temp(temp) is False
    monkeypatch.undo()
    assert temp.closed and part.closed
    assert part.path.read_bytes() == b"abc"
