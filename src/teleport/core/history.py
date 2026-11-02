"""Lịch sử truyền (sans-IO): các mục của `history.json` (mvp F5, docs/architecture.md mục 4).

Module chỉ dựng, kiểm, mã hóa và giải mã mục lịch sử: không mở file, không xem đồng hồ (giờ
tường do bên gọi đưa vào). Đọc/ghi file, gộp ghi và móc vào lượt truyền ở `app/history.py` và
`app/transfers.py`.

- `HistoryEntry`: metadata một lượt đã kết thúc (chỉ metadata, mvp N9: tên file, kích thước,
  đường dẫn đã lưu; không bao giờ nội dung file). Khóa là (`direction`, `device_id`,
  `transfer_id`).
- `entry_from_info`: dựng mục từ bản chụp cuối `TransferInfo` của lượt.
- `add_entry`: chèn mục mới lên đầu, bỏ mục cũ cùng khóa, cắt theo hai trần (`trim_history`).
- `trim_history`: giữ mục theo thứ tự, bỏ mục trùng khóa đứng sau, tối đa
  `MAX_HISTORY_PER_DEVICE` mục mỗi `device_id` và `MAX_HISTORY_TOTAL` mục tổng (bỏ mục cũ nhất).
- `remove_device`: bỏ mọi mục của một `device_id`.
- `encode_history` / `decode_history`: nội dung `history.json`; thứ tự là thứ tự ghi (mới nhất
  trước), không sắp theo `finished_at` (đồng hồ có thể lùi).

Mọi lỗi, cả tham số sai lẫn dữ liệu hỏng, là `HistoryError` (lớp con của ValueError). File trên
đĩa của chính máy này vẫn được kiểm như dữ liệu không tin cậy. Thông điệp lỗi chỉ nêu tên trường,
không bao giờ chứa tên file hay đường dẫn (mvp N9).
"""

from __future__ import annotations

import datetime
import json
import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from teleport.core.messages import (
    MAX_OFFER_FILES,
    MAX_SAFE_INTEGER,
    MessageError,
    validate_device_id,
    validate_device_name,
    validate_file_name,
    validate_transfer_id,
)
from teleport.core.numbers import is_finite
from teleport.core.resume_state import StateError, check_time, format_time, parse_time
from teleport.core.transfer import Direction, TransferInfo

MAX_HISTORY_PER_DEVICE = 100  # mvp F5: số lượt gần nhất được giữ với mỗi thiết bị
MAX_HISTORY_TOTAL = 1000  # mvp F5: số lượt tối đa của cả bảng (mọi thiết bị)
MAX_HISTORY_NAMES = 10  # số tên file đầu tiên giữ trong mỗi mục
MAX_HISTORY_FILE = 4 * 1024 * 1024  # trần `history.json`, byte
HISTORY_VERSION = 1
MAX_SAVED_PATH_LEN = 32767  # ký tự: đường dẫn dài nhất của Windows
MAX_RESULT_LEN = 64

# `result`: giá trị của `TransferResult`; giá trị lạ đúng dạng (bản mới hơn) vẫn được giữ.
_RESULT_RE = re.compile(r"[ -~]{1,64}")
# `saved_path` không được chứa ký tự loại Cc hay Cs (Cs không mã hóa được UTF-8).
_PATH_FORBIDDEN_RE = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\ud800-\\udfff]")
_DIRECTIONS = frozenset(d.value for d in Direction)

_ENTRY_KEYS = (
    "direction",
    "device_id",
    "device_name",
    "transfer_id",
    "file_count",
    "total_bytes",
    "done_bytes",
    "names",
    "result",
    "finished_at",
    "saved_path",
)
_HEAD = f'{{\n  "version": {HISTORY_VERSION},\n  "entries": ['
_EMPTY = f'{{\n  "version": {HISTORY_VERSION},\n  "entries": []\n}}\n'
_LEAD = "\n    "
_TAIL = "\n  ]\n}\n"
_SEP = ",\n    "


class HistoryError(ValueError):
    """Tham số sai, hoặc `history.json` (cả file hay một mục) hỏng hay vượt trần."""


def _check_int(value: object, field: str, lo: int, hi: int) -> int:
    # bool là lớp con của int: bị từ chối như mọi kiểu khác.
    if type(value) is not int or not lo <= value <= hi:
        raise HistoryError(f"{field} phải là số nguyên {lo}…{hi}")
    return value


def _check_time(value: object) -> datetime.datetime:
    """`resume_state.check_time` cho `finished_at`; StateError → HistoryError."""
    try:
        return check_time(value, "finished_at")
    except StateError as e:
        raise HistoryError(str(e)) from None


def _check_names(value: object) -> tuple[str, ...]:
    if not isinstance(value, tuple | list):
        raise HistoryError("names phải là một dãy tên")
    if len(value) > MAX_HISTORY_NAMES:
        raise HistoryError(f"names có quá {MAX_HISTORY_NAMES} tên")
    names: list[str] = []
    for name in value:
        try:
            names.append(validate_file_name(name))
        except MessageError:
            # Không chép thông điệp của MessageError: chỉ nêu tên trường (mvp N9).
            raise HistoryError("names có tên file không hợp lệ") from None
    return tuple(names)


def _check_saved_path(value: object, direction: Direction) -> str | None:
    if value is None:
        return None
    if direction is not Direction.RECEIVE:
        raise HistoryError("saved_path chỉ có ở chiều nhận")
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_SAVED_PATH_LEN:
        raise HistoryError(f"saved_path phải là chuỗi 1–{MAX_SAVED_PATH_LEN} ký tự")
    if _PATH_FORBIDDEN_RE.search(value) is not None:
        raise HistoryError("saved_path chứa ký tự không được phép")
    return str.__str__(value)


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    """Một lượt đã kết thúc trong lịch sử. Kiểm mọi trường trong `__post_init__`; sai → HistoryError.

    - `direction`: chiều nhìn từ máy này (nhận cả `str` `"send"` / `"receive"`, lưu `Direction`).
    - `device_id`, `transfer_id`: 32 ký tự hex thường; cùng `direction` là khóa của mục.
    - `device_name`: tên trong `trusted.json` lúc ghi; None khi thiết bị không còn trong kho
      (ví dụ lượt kết thúc vì hủy ghép đôi).
    - `file_count`: số file của `offer` (1…`MAX_OFFER_FILES`, không bị cắt).
    - `total_bytes`, `done_bytes`: 0 ≤ `done_bytes` ≤ `total_bytes` ≤ 2^53 − 1.
    - `names`: tối đa `MAX_HISTORY_NAMES` tên đầu theo thứ tự `offer`, mỗi tên qua
      `validate_file_name`.
    - `result`: giá trị `TransferResult` (1–64 ký tự ASCII in được; giá trị lạ vẫn giữ).
    - `finished_at`: UTC, làm tròn xuống giây.
    - `saved_path`: chỉ chiều nhận; ≤ `MAX_SAVED_PATH_LEN` ký tự, không có ký tự Cc/Cs.
    """

    direction: Direction
    device_id: str
    device_name: str | None
    transfer_id: str
    file_count: int
    total_bytes: int
    done_bytes: int
    names: tuple[str, ...]
    result: str
    finished_at: datetime.datetime
    saved_path: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.direction, str) or self.direction not in _DIRECTIONS:
            raise HistoryError("direction phải là send hoặc receive")
        direction = Direction(str.__str__(self.direction))
        try:
            # Lớp con của str đổi về str thuần để so sánh và mã hóa nhất quán.
            device_id = str.__str__(validate_device_id(self.device_id))
        except MessageError:
            raise HistoryError("device_id phải là đúng 32 ký tự hex thường") from None
        try:
            transfer_id = str.__str__(validate_transfer_id(self.transfer_id))
        except MessageError:
            raise HistoryError("transfer_id phải là đúng 32 ký tự hex thường") from None
        device_name = self.device_name
        if device_name is not None:
            try:
                device_name = str.__str__(validate_device_name(device_name))
            except MessageError:
                raise HistoryError("device_name không hợp lệ") from None
        _check_int(self.file_count, "file_count", 1, MAX_OFFER_FILES)
        _check_int(self.total_bytes, "total_bytes", 0, MAX_SAFE_INTEGER)
        _check_int(self.done_bytes, "done_bytes", 0, self.total_bytes)
        names = _check_names(self.names)
        if not isinstance(self.result, str) or not _RESULT_RE.fullmatch(self.result):
            raise HistoryError(f"result phải là 1–{MAX_RESULT_LEN} ký tự ASCII in được")
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "device_id", device_id)
        object.__setattr__(self, "transfer_id", transfer_id)
        object.__setattr__(self, "device_name", device_name)
        object.__setattr__(self, "names", names)
        object.__setattr__(self, "result", str.__str__(self.result))
        object.__setattr__(self, "finished_at", _check_time(self.finished_at))
        object.__setattr__(self, "saved_path", _check_saved_path(self.saved_path, direction))

    def _to_line(self) -> str:
        return json.dumps(
            {
                "direction": str.__str__(self.direction),
                "device_id": self.device_id,
                "device_name": self.device_name,
                "transfer_id": self.transfer_id,
                "file_count": self.file_count,
                "total_bytes": self.total_bytes,
                "done_bytes": self.done_bytes,
                "names": list(self.names),
                "result": self.result,
                "finished_at": format_time(self.finished_at),
                "saved_path": self.saved_path,
            },
            ensure_ascii=False,
        )


def _key(entry: HistoryEntry) -> tuple[str, str, str]:
    return (entry.direction.value, entry.device_id, entry.transfer_id)


def entry_from_info(
    info: TransferInfo,
    *,
    result: str,
    device_name: str | None,
    wall_now: float,
    saved_path: str | None,
) -> HistoryEntry:
    """Mục lịch sử từ bản chụp cuối `info` của lượt (`TransferEnded.info`).

    `names` = `MAX_HISTORY_NAMES` tên đầu của `info.names`; `file_count` = số file của `offer`;
    `done_bytes` / `total_bytes` lấy từ `info`; `finished_at` = UTC(⌊`wall_now`⌋). Chiều gửi mà
    `saved_path` khác None, hay bất kỳ trường nào sai → HistoryError.
    """
    if not isinstance(info, TransferInfo):
        raise HistoryError("info phải là TransferInfo")
    if isinstance(wall_now, bool) or not isinstance(wall_now, int | float) or not is_finite(wall_now):
        raise HistoryError("wall_now phải là số giây hữu hạn")
    try:
        finished_at = datetime.datetime.fromtimestamp(math.floor(wall_now), datetime.UTC)
    except (OverflowError, OSError, ValueError):
        raise HistoryError("wall_now ngoài khoảng biểu diễn được") from None
    return HistoryEntry(
        direction=info.key.direction,
        device_id=info.key.device_id,
        device_name=device_name,
        transfer_id=info.key.transfer_id,
        file_count=len(info.files),
        total_bytes=info.total_bytes,
        done_bytes=info.done_bytes,
        names=tuple(info.names[:MAX_HISTORY_NAMES]),
        result=result,
        finished_at=finished_at,
        saved_path=saved_path,
    )


class _Caps:
    """Bộ đếm hai trần khi duyệt mục từ mới nhất tới cũ nhất (dùng chung cho cắt và giải mã)."""

    __slots__ = ("per_device", "seen", "total")

    def __init__(self) -> None:
        self.seen: set[tuple[str, str, str]] = set()
        self.per_device: dict[str, int] = {}
        self.total = 0

    @property
    def full(self) -> bool:
        return self.total >= MAX_HISTORY_TOTAL

    def admit(self, entry: HistoryEntry) -> bool:
        """Giữ `entry` không: chưa gặp khóa, máy đó chưa đủ trần, tổng chưa đủ trần."""
        key = _key(entry)
        count = self.per_device.get(entry.device_id, 0)
        if key in self.seen or count >= MAX_HISTORY_PER_DEVICE or self.full:
            return False
        self.seen.add(key)
        self.per_device[entry.device_id] = count + 1
        self.total += 1
        return True


def _check_entries(entries: Iterable[HistoryEntry]) -> list[HistoryEntry]:
    items = list(entries)
    if not all(isinstance(e, HistoryEntry) for e in items):
        raise HistoryError("entries phải là các HistoryEntry")
    return items


def trim_history(entries: Iterable[HistoryEntry]) -> tuple[HistoryEntry, ...]:
    """Giữ thứ tự (mới nhất trước), bỏ mục trùng khóa đứng sau, cắt theo hai trần.

    Mục bị bỏ khi máy của nó đã có `MAX_HISTORY_PER_DEVICE` mục đứng trước, hay bảng đã có
    `MAX_HISTORY_TOTAL` mục: tức là bỏ mục cũ nhất của máy đó, rồi mục cũ nhất toàn bảng.
    Phần tử không phải HistoryEntry → HistoryError.
    """
    caps = _Caps()
    return tuple(e for e in _check_entries(entries) if caps.admit(e))


def add_entry(entries: Sequence[HistoryEntry], entry: HistoryEntry) -> tuple[HistoryEntry, ...]:
    """`entry` lên đầu, bỏ mục cũ cùng khóa, cắt theo hai trần (`trim_history`).

    Vượt trần theo máy thì bỏ mục cũ nhất **của cùng `device_id`**, nên máy khác không mất mục;
    vượt trần tổng thì bỏ mục cũ nhất toàn bảng. Phần tử không phải HistoryEntry → HistoryError.
    """
    if not isinstance(entry, HistoryEntry):
        raise HistoryError("entries và entry phải là HistoryEntry")
    return trim_history((entry, *_check_entries(entries)))


def remove_device(entries: Iterable[HistoryEntry], device_id: str) -> tuple[HistoryEntry, ...]:
    """Mọi mục không thuộc `device_id`, giữ thứ tự. `device_id` sai dạng hay phần tử không phải
    HistoryEntry → HistoryError."""
    try:
        device_id = str.__str__(validate_device_id(device_id))
    except MessageError:
        raise HistoryError("device_id phải là đúng 32 ký tự hex thường") from None
    return tuple(e for e in _check_entries(entries) if e.device_id != device_id)


def encode_history(entries: Iterable[HistoryEntry]) -> bytes:
    """Nội dung `history.json`: UTF-8, giữ nguyên ký tự Unicode, mỗi mục một dòng, giữ thứ tự.

    Không cắt theo số mục (việc của `add_entry` / `trim_history`). Vượt `MAX_HISTORY_FILE` thì
    bỏ mục cuối (cũ nhất toàn bảng) tới khi vừa. Phần tử không phải HistoryEntry → HistoryError.
    """
    items = _check_entries(entries)
    lines = [item._to_line().encode("utf-8") for item in items]
    sep = len(_SEP.encode("utf-8"))
    # Mỗi mục tốn độ dài dòng + một dấu phân cách; mục đầu dùng `_LEAD` thay dấu phân cách.
    base = len(_HEAD) + len(_LEAD) + len(_TAIL) - sep
    total = base + sum(len(line) + sep for line in lines)
    while lines and total > MAX_HISTORY_FILE:
        total -= len(lines.pop()) + sep
    if not lines:
        data = _EMPTY.encode("utf-8")
    else:
        data = (_HEAD + _LEAD).encode("utf-8") + _SEP.encode("utf-8").join(lines) + _TAIL.encode("utf-8")
    if len(data) > MAX_HISTORY_FILE:  # không xảy ra: phòng sai sót khi tính độ dài
        raise HistoryError(f"history.json dài quá {MAX_HISTORY_FILE} byte")
    return data


def _load_json(data: object) -> object:
    """Giải JSON UTF-8 (chấp nhận BOM) không quá `MAX_HISTORY_FILE` byte; hỏng → HistoryError."""
    if not isinstance(data, bytes | bytearray | memoryview):
        raise HistoryError("data phải là bytes")
    # Kiểm trần trước khi chép hay giải mã: file quá lớn không tốn công.
    with memoryview(data) as view:
        if view.nbytes > MAX_HISTORY_FILE:
            raise HistoryError(f"history.json dài quá {MAX_HISTORY_FILE} byte")
    raw = bytes(data)
    try:
        # `NaN` / `Infinity` thành float: không trường nào nhận float, nên chỉ mục chứa nó bị bỏ.
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        # ValueError gồm JSONDecodeError và số nguyên quá nhiều chữ số; RecursionError: lồng quá sâu.
        raise HistoryError("history.json không phải JSON UTF-8 hợp lệ") from None


def _entry_from_dict(obj: object) -> HistoryEntry:
    if not isinstance(obj, dict):
        raise HistoryError("mỗi mục phải là một JSON object")
    for key in _ENTRY_KEYS:
        if key not in obj:
            raise HistoryError(f"mục lịch sử thiếu trường {key}")
    try:
        finished_at = parse_time(obj["finished_at"], "finished_at")
    except StateError:
        raise HistoryError("finished_at phải có dạng YYYY-MM-DDTHH:MM:SSZ") from None
    names = obj["names"]
    if not isinstance(names, list):
        raise HistoryError("names phải là một mảng")
    return HistoryEntry(
        direction=obj["direction"],
        device_id=obj["device_id"],
        device_name=obj["device_name"],
        transfer_id=obj["transfer_id"],
        file_count=obj["file_count"],
        total_bytes=obj["total_bytes"],
        done_bytes=obj["done_bytes"],
        names=tuple(names),
        result=obj["result"],
        finished_at=finished_at,
        saved_path=obj["saved_path"],
    )


def decode_history(data: bytes | bytearray | memoryview) -> list[HistoryEntry]:
    """Đọc `history.json`; giữ thứ tự trong file (mới nhất trước), bỏ riêng từng mục hỏng.

    Cả file hỏng → HistoryError: vượt `MAX_HISTORY_FILE` byte (kiểm trước khi giải mã), không
    phải JSON UTF-8 (chấp nhận BOM), không phải object, `version` khác
    số nguyên 1, `entries` không phải mảng. Mục thiếu hay sai trường bị bỏ; trường lạ bị bỏ qua;
    trùng khóa thì giữ mục đứng trước. Duyệt theo thứ tự file và cắt theo hai trần như
    `trim_history`: tối đa `MAX_HISTORY_PER_DEVICE` mục mỗi máy, `MAX_HISTORY_TOTAL` mục tổng.
    """
    obj = _load_json(data)
    if not isinstance(obj, dict):
        raise HistoryError("history.json phải là một JSON object")
    if "version" not in obj or "entries" not in obj:
        raise HistoryError("history.json thiếu version hoặc entries")
    version = obj["version"]
    if type(version) is not int or version != HISTORY_VERSION:
        raise HistoryError(f"history.json: version phải là {HISTORY_VERSION}")
    raw_entries = obj["entries"]
    if not isinstance(raw_entries, list):
        raise HistoryError("entries phải là một mảng")
    result: list[HistoryEntry] = []
    caps = _Caps()
    for raw in raw_entries:
        if caps.full:
            break
        try:
            entry = _entry_from_dict(raw)
        except HistoryError:
            continue
        if caps.admit(entry):
            result.append(entry)
    return result
