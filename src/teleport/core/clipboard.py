"""Lõi đồng bộ clipboard (sans-IO): chia, ráp, chống vòng lặp, giới hạn tốc độ, lọc nhạy cảm.

Đặc tả trên dây ở docs/protocol.md mục 3.2, 3.3 (message `clipboard`); thiết kế ở
docs/ke_hoach.md mục 3.6. Module này không đọc clipboard, không gửi gì: `app`
(`ClipboardSync`, `app.clipboard`) đưa nội dung, `clip_id` (UUID4 hex) và `now` (đồng hồ monotonic)
vào, rồi gửi/ghi theo kết quả; `ui` (`ui.clipboard_qt`) đọc/ghi clipboard thật.

- **Văn bản trên dây** (`normalize_text`): surrogate ghép cặp, surrogate lẻ thành U+FFFD,
  `"\\r\\n"` thành `"\\n"`; `\\r` đứng một mình, NUL và mọi ký tự điều khiển khác giữ
  nguyên. Chuẩn hóa **không lũy đẳng**: `"\\r\\r\\n"` → `"\\r\\n"` → `"\\n"`. Chỉ bên gửi
  chuẩn hóa; bên nhận giữ nguyên văn bản đã ráp (`ClipReady.content` khớp `sha256`).
- **Hợp đồng chống vòng lặp với `app.clipboard`:** `LoopGuard` dùng `text_fingerprint(content)` hoặc
  fingerprint đọc lại sau khi ghi, không bao giờ dùng `ClipReady.sha256` (bên gửi khác có
  thể gửi văn bản chưa chuẩn hóa, có `\\r\\n`).
- **Chia** (`split_clip`): mỗi khung (gồm header 4 byte) ≤ `MAX_CLIP_MESSAGE_SIZE`. Ảnh cắt
  theo `PNG_FRAGMENT_BYTES` byte thô; văn bản cắt theo cỡ **sau mã hóa JSON**, ở biên code
  point. Gọi được ngoài event loop (hàm thuần, không giữ trạng thái).
- **Ráp** (`ClipAssembler`): mỗi thiết bị ≤ 1 clip dở; mọi lỗi do máy kia gây ra thành
  `ClipDropped`, không bao giờ ném, không đóng kết nối (bảng ở docstring của lớp).
- **Chống vòng lặp** (`LoopGuard`, `text_fingerprint`, `image_fingerprint`).
- **Lọc nhạy cảm** (`is_sensitive`).

Không lớp nào ở đây chép nội dung clip vào `repr` hay thông điệp lỗi (mvp N9).
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from teleport.core.bitfield import decode_base64
from teleport.core.messages import Clipboard, ClipKind
from teleport.core.ratelimit import TokenBucket

MAX_TEXT_BYTES = 1024 * 1024  # byte UTF-8 sau chuẩn hóa
MAX_PNG_BYTES = 10 * 1024 * 1024  # byte PNG
MAX_CLIP_BYTES: Mapping[str, int] = {ClipKind.TEXT: MAX_TEXT_BYTES, ClipKind.PNG: MAX_PNG_BYTES}
MAX_IMAGE_SIDE = 8192  # cạnh ảnh tối đa, px (`ui.clipboard_qt` kiểm qua QImageReader trước khi giải mã)
MAX_CLIP_MESSAGE_SIZE = 768 * 1024  # cả khung: header 4 byte + JSON; vừa trần 1 MiB của framing
PNG_FRAGMENT_BYTES = 512 * 1024  # byte thô mỗi mảnh ảnh (base64 ≈ 683 KiB)
CLIP_ASSEMBLY_TIMEOUT = 15.0  # giây, tính từ mảnh index 0
CLIP_RATE = 5.0  # clip mới / giây / thiết bị
CLIP_BURST = 5
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_ENVELOPE_RESERVE = 1024  # chỗ cho header khung và mọi trường ngoài `data` (≈ 250 byte thật)
_TEXT_BUDGET = MAX_CLIP_MESSAGE_SIZE - _ENVELOPE_RESERVE  # byte của `data` sau mã hóa JSON

_SURROGATE_RE = re.compile("[\\ud800-\\udfff]")
_SURROGATE_FIX_RE = re.compile("[\\ud800-\\udbff][\\udc00-\\udfff]|[\\ud800-\\udfff]")

# Cỡ mã hóa JSON (`ensure_ascii=False`, như `framing.encode_message`) của từng **byte UTF-8**:
# `"` và `\` → 2; `\b \f \n \r \t` → 2; C0 khác → 6 (`\u00XX`); mọi byte khác → 1 (U+007F,
# U+2028, U+2029 không bị thoát). Ký tự cần thoát đều là ASCII một byte, nên cộng theo byte
# UTF-8 ra đúng cỡ của cả chuỗi (test đối chiếu với `json.dumps`).
_JSON_SHORT_ESCAPES = b'"\\\b\f\n\r\t'
_JSON_COST = bytes(2 if b in _JSON_SHORT_ESCAPES else 6 if b < 0x20 else 1 for b in range(256))


def normalize_text(text: str) -> str:
    """Văn bản đúng như gửi trên dây (protocol mục 3.3).

    1. Cặp surrogate cao + thấp liền nhau ghép thành một code point; surrogate lẻ còn lại
       thành U+FFFD (chuỗi Python từ clipboard Windows có thể chứa cả hai).
    2. `"\\r\\n"` thành `"\\n"`; `\\r` đứng một mình giữ nguyên.

    NUL và mọi ký tự điều khiển khác giữ nguyên (không hỏng dữ liệu). Không lũy đẳng với
    chuỗi có `"\\r\\r\\n"` (xem docstring module). `text` không phải `str` → TypeError.
    """
    if not isinstance(text, str):
        raise TypeError("text phải là str")
    if _SURROGATE_RE.search(text) is not None:
        text = _SURROGATE_FIX_RE.sub(_fix_surrogates, text)
    return text.replace("\r\n", "\n")


def _fix_surrogates(m: re.Match[str]) -> str:
    s = m.group()
    if len(s) == 2:
        return chr(0x10000 + ((ord(s[0]) - 0xD800) << 10) + (ord(s[1]) - 0xDC00))
    return "�"


# ---- Chia clip -----------------------------------------------------------------------------


class ClipTooLarge(ValueError):
    """Nội dung vượt trần của kind. `size` là byte (hoặc số code point, khi kiểm nhanh trước
    chuẩn hóa), `limit` là trần byte."""

    def __init__(self, kind: str, size: int, limit: int) -> None:
        super().__init__(f"clip {kind} quá lớn: {size} > {limit}")
        self.kind = kind
        self.size = size
        self.limit = limit


def split_clip(clip_id: str, kind: ClipKind | str, content: str | bytes) -> list[Clipboard]:
    """Chia một clip thành các message `clipboard`, theo thứ tự gửi.

    Kind `text` cần `content: str` (tự chuẩn hóa bằng `normalize_text`; `sha256` và
    `total` tính trên byte UTF-8 sau chuẩn hóa); `image/png` cần `bytes` mở đầu bằng
    `PNG_SIGNATURE`. Sai kiểu, kind khác hai kind trên, nội dung rỗng (sau chuẩn hóa) hay
    thiếu chữ ký PNG → ValueError; quá trần → `ClipTooLarge`; `clip_id` sai dạng →
    `MessageError`. Mọi message trả về mã hóa thành khung ≤ `MAX_CLIP_MESSAGE_SIZE`.
    """
    if kind == ClipKind.TEXT:
        if not isinstance(content, str):
            raise ValueError("clip text cần nội dung str")
        # Kiểm nhanh trước khi chuẩn hóa: chuẩn hóa chỉ bớt tối đa một nửa số code point
        # (`\r\n` → `\n`) và mỗi code point còn lại ≥ 1 byte, nên chuỗi này chắc chắn quá trần.
        if len(content) > 2 * MAX_TEXT_BYTES:
            raise ClipTooLarge(ClipKind.TEXT.value, len(content), MAX_TEXT_BYTES)
        text = normalize_text(content)
        raw = text.encode("utf-8")
        if not raw:
            raise ValueError("clip rỗng")
        if len(raw) > MAX_TEXT_BYTES:
            raise ClipTooLarge(ClipKind.TEXT.value, len(raw), MAX_TEXT_BYTES)
        pieces = _split_text(raw)
    elif kind == ClipKind.PNG:
        if not isinstance(content, bytes):
            raise ValueError("clip image/png cần nội dung bytes")
        raw = content
        if not raw:
            raise ValueError("clip rỗng")
        if len(raw) > MAX_PNG_BYTES:
            raise ClipTooLarge(ClipKind.PNG.value, len(raw), MAX_PNG_BYTES)
        if not raw.startswith(PNG_SIGNATURE):
            raise ValueError("nội dung image/png không mở đầu bằng chữ ký PNG")
        pieces = [
            base64.b64encode(raw[i : i + PNG_FRAGMENT_BYTES]).decode("ascii")
            for i in range(0, len(raw), PNG_FRAGMENT_BYTES)
        ]
    else:
        raise ValueError("chỉ chia được kind text và image/png")
    kind_str = ClipKind(kind).value
    digest = hashlib.sha256(raw).hexdigest()
    return [
        Clipboard(
            clip_id=clip_id,
            kind=kind_str,
            sha256=digest,
            total=len(raw),
            index=i,
            count=len(pieces),
            data=piece,
        )
        for i, piece in enumerate(pieces)
    ]


_SCAN_STEP = 4096  # byte mỗi bước cộng cỡ theo khối trong `_split_text`


def _split_text(raw: bytes) -> list[str]:
    """Cắt byte UTF-8 `raw` (không rỗng, không surrogate) thành các đoạn có cỡ mã hóa JSON
    ≤ `_TEXT_BUDGET`, ở biên code point. O(n), không thử lại.

    Cỡ mã hóa của một đoạn byte bằng tổng `_JSON_COST` của các byte trong đó. Mỗi đoạn cộng
    cỡ theo khối `_SCAN_STEP` byte (`sum` trên bytes chạy trong C) tới khi khối kế tiếp làm
    vượt, rồi từng byte, rồi lùi về biên code point (≤ 3 byte). Đoạn không bắt buộc lớn
    nhất có thể. Mỗi byte tốn ≤ 6 nên một đoạn luôn có hàng trăm nghìn byte, lùi không về 0.
    """
    costs = raw.translate(_JSON_COST)
    pieces: list[str] = []
    n = len(raw)
    pos = 0
    while pos < n:
        end = pos
        size = 0
        while end < n:
            block = sum(costs[end : end + _SCAN_STEP])
            if size + block > _TEXT_BUDGET:
                break
            size += block
            end = min(n, end + _SCAN_STEP)
        while end < n and size + costs[end] <= _TEXT_BUDGET:
            size += costs[end]
            end += 1
        # Byte tại `end` là byte nối (0b10xxxxxx) thì `end` nằm giữa một code point.
        while end < n and 0x80 <= raw[end] <= 0xBF:
            end -= 1
        pieces.append(raw[pos:end].decode("utf-8"))
        pos = end
    return pieces


def _json_text_len(text: str) -> int:
    """Cỡ tính bằng `_JSON_COST` của `text` (không surrogate) trong JSON, không tính hai dấu
    nháy; bằng `len(json.dumps(text, ensure_ascii=False).encode("utf-8")) - 2` (có test)."""
    return sum(text.encode("utf-8").translate(_JSON_COST))


# ---- Ráp clip ------------------------------------------------------------------------------


class DropReason(StrEnum):
    """Lý do `ClipAssembler` bỏ một clip. Không bao giờ gửi cho máy kia."""

    DUPLICATE = "duplicate"  # index 0 lặp lại clip_id của clip dở
    RATE_LIMITED = "rate_limited"
    REPLACED = "replaced"  # clip dở bị clip mới thay
    UNSUPPORTED_KIND = "unsupported_kind"
    TOO_LARGE = "too_large"  # total > trần của kind
    INCONSISTENT = "inconsistent"  # trường khác mảnh đầu; count > total
    ORPHAN = "orphan"  # mảnh index > 0 không thuộc clip dở
    OUT_OF_ORDER = "out_of_order"  # index ≠ mảnh kế tiếp (thiếu hoặc trùng)
    SIZE_MISMATCH = "size_mismatch"  # tổng byte vượt hoặc khác total
    HASH_MISMATCH = "hash_mismatch"
    INVALID_CONTENT = "invalid_content"  # image/png không mở đầu bằng chữ ký PNG
    EXPIRED = "expired"
    LINK_LOST = "link_lost"


@dataclass(frozen=True, slots=True)
class ClipReady:
    """Clip đã ráp xong và đúng `sha256`. `content`: `str` (text) hay `bytes` (image/png).

    Text: `content` đúng là byte nhận được giải mã UTF-8, **không** chuẩn hóa lại; `sha256`
    là hash của chính các byte đó. Bên gửi khác có thể không chuẩn hóa (gửi cả `\\r\\n`),
    nên `sha256` có thể khác `text_fingerprint(content)`. Hợp đồng với `app.clipboard`: `LoopGuard`
    dùng `text_fingerprint(content)` hoặc fingerprint đọc lại sau khi ghi, **không** dùng
    `sha256`.
    """

    device_id: str
    clip_id: str
    kind: ClipKind
    content: str | bytes = field(repr=False)  # N9: repr/log không lộ nội dung
    sha256: str


@dataclass(frozen=True, slots=True)
class ClipDropped:
    """Clip bị bỏ; mang `clip_id` và `kind` của clip đó, không chứa nội dung (mvp N9)."""

    device_id: str
    clip_id: str
    kind: str
    reason: DropReason


ClipEvent = ClipReady | ClipDropped


@dataclass(slots=True)
class _Partial:
    """Clip đang ráp của một thiết bị."""

    clip_id: str
    kind: str
    sha256: str
    total: int
    count: int
    started_at: float
    progress_at: float  # `now` lúc nhận mảnh hợp lệ gần nhất (mảnh 0: bằng `started_at`)
    next_index: int = 0
    received: int = 0
    # Ráp vào một bytearray, không giữ list mảnh: mỗi `bytes` tốn thêm vài chục byte, nên
    # mảnh rất nhỏ làm RAM thật vượt xa `reserved_bytes` (= `total`).
    buf: bytearray = field(default_factory=bytearray)
    hasher: hashlib._Hash = field(default_factory=hashlib.sha256)


@dataclass(frozen=True, slots=True)
class PartialInfo:
    """Thông tin một clip dở (`ClipAssembler.partials`), không có nội dung (mvp N9).

    `started_at`: `now` của mảnh `index 0`; `progress_at`: `now` của mảnh hợp lệ gần nhất.
    """

    device_id: str
    clip_id: str
    total: int
    received: int
    started_at: float
    progress_at: float


@dataclass(slots=True)
class _Device:
    bucket: TokenBucket
    partial: _Partial | None = None
    # `clip_id` của clip vừa bỏ gần nhất: mảnh `index > 0` còn lại của nó bị bỏ im lặng.
    last_dropped: str | None = None


class ClipAssembler:
    """Ráp các mảnh `clipboard` nhận từ mọi thiết bị tin cậy (một đối tượng cho cả node).

    `feed(device_id, msg, now)` với `msg` đã qua `core.messages` (không kiểm lại); `now`
    lùi so với giá trị lớn nhất đã thấy thì được kẹp lại. Không bao giờ ném vì dữ liệu máy
    kia; tham số sai của bên gọi (constructor, `now` không phải số) thì ném.

    Mỗi thiết bị có ≤ 1 clip dở và một token bucket đếm **clip mới** (`burst` clip, nạp
    `rate` clip/s): chỉ mảnh `index == 0` mở clip mới mới tốn 1 token, xét trước kind, trần
    và nhất quán (clip sai cũng tốn token). `feed` xét theo thứ tự:

    0. Clip dở đã quá hạn (`now ≥ started_at + timeout`) → `EXPIRED`, rồi xét tiếp `msg`.
    1. `index == 0` cùng `clip_id` với clip dở → `DUPLICATE`; bỏ clip dở, không mở mới.
    2. `index == 0`, bucket < 1 → `RATE_LIMITED` cho `msg`; clip dở giữ nguyên.
    3. `index == 0`, lấy token; clip dở khác `clip_id` → `REPLACED` cho clip cũ.
    4–6. Kind ∉ `limits` → `UNSUPPORTED_KIND`; `total` > trần → `TOO_LARGE`; `count` >
       `total` → `INCONSISTENT`. Qua hết thì mở clip dở và nối mảnh (bước 11).
    8. `index > 0` của clip vừa bỏ gần nhất → im lặng `()`; của `clip_id` khác clip dở (hoặc
       không có clip dở) → `ORPHAN`, clip dở giữ nguyên.
    9–10. Cùng `clip_id` mà `kind`/`sha256`/`total`/`count` khác → `INCONSISTENT`; `index`
       ≠ mảnh kế tiếp → `OUT_OF_ORDER`.
    11–15. Nối mảnh: vượt `total` → `SIZE_MISMATCH`; mảnh cuối mà tổng ≠ `total` →
       `SIZE_MISMATCH`, sai hash → `HASH_MISMATCH`, PNG sai chữ ký → `INVALID_CONTENT`;
       đúng hết → `ClipReady`. Mảnh giữa hợp lệ → `()`.

    Clip bị bỏ ở bất kỳ bước nào được nhớ là "clip vừa bỏ" của thiết bị (một giá trị).
    `tick` bỏ clip quá hạn và xóa trạng thái (kể cả clip vừa bỏ) của thiết bị không còn
    clip dở mà bucket đã đầy lại; thiết bị vừa bị bỏ clip ở chính lần `tick` đó chỉ được
    dọn ở lần sau. `forget_device` xóa ngay; `discard` bỏ im lặng clip dở (trần RAM chung
    của `app`, xem `reserved_bytes` và `partials`). `next_wakeup` chỉ tính hạn của clip dở; trạng
    thái rảnh được dọn ở lần `tick` sau (số thiết bị có trạng thái ≤ số thiết bị tin cậy đã
    gửi clip).
    """

    def __init__(
        self,
        *,
        timeout: float = CLIP_ASSEMBLY_TIMEOUT,
        rate: float = CLIP_RATE,
        burst: int = CLIP_BURST,
        limits: Mapping[str, int] = MAX_CLIP_BYTES,
    ) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, int | float) or not timeout > 0:
            raise ValueError("timeout phải là số > 0")
        TokenBucket(rate, burst)  # kiểm `rate`, `burst` (TypeError / ValueError)
        checked: dict[str, int] = {}
        for kind, limit in limits.items():
            if kind not in (ClipKind.TEXT, ClipKind.PNG):
                raise ValueError("limits chỉ được có khóa text và image/png")
            if type(limit) is not int or limit < 1:
                raise ValueError("mỗi trần trong limits phải là số nguyên ≥ 1")
            checked[str.__str__(kind)] = limit
        self._timeout = float(timeout)
        self._rate = rate
        self._burst = burst
        self._limits = checked
        self._devices: dict[str, _Device] = {}
        self._now: float | None = None

    def feed(self, device_id: str, msg: Clipboard, now: float) -> tuple[ClipEvent, ...]:
        """Xử lý một mảnh nhận từ `device_id`; trả về các sự kiện theo thứ tự (có thể rỗng)."""
        now = self._clamp(now)
        events: list[ClipEvent] = []
        dev = self._devices.get(device_id)
        if dev is not None and dev.partial is not None and self._expired(dev.partial, now):
            events.append(self._drop(device_id, dev, DropReason.EXPIRED))
        if msg.index == 0:
            if dev is None:
                dev = self._devices[device_id] = _Device(TokenBucket(self._rate, self._burst))
            self._feed_first(device_id, dev, msg, now, events)
        elif dev is not None and dev.partial is not None and dev.partial.clip_id == msg.clip_id:
            self._feed_next(device_id, dev, dev.partial, msg, now, events)
        elif dev is None or dev.last_dropped != msg.clip_id:
            events.append(ClipDropped(device_id, msg.clip_id, msg.kind, DropReason.ORPHAN))
        return tuple(events)

    def tick(self, now: float) -> tuple[ClipDropped, ...]:
        """Bỏ clip dở đã quá hạn; dọn trạng thái của thiết bị rảnh mà bucket đã đầy lại."""
        now = self._clamp(now)
        events: list[ClipDropped] = []
        for device_id, dev in list(self._devices.items()):
            if dev.partial is not None:
                if self._expired(dev.partial, now):
                    # Chưa dọn ở lần này: còn nhớ clip vừa bỏ, để các mảnh còn lại của nó
                    # tới ngay sau đó bị bỏ im lặng thay vì thành `ORPHAN`.
                    events.append(self._drop(device_id, dev, DropReason.EXPIRED))
            elif dev.bucket.available(now) >= dev.bucket.burst:
                del self._devices[device_id]
        return tuple(events)

    def next_wakeup(self) -> float | None:
        """Mốc `now` sớm nhất mà `tick` có việc (hạn của clip dở); không có clip dở → None."""
        deadlines = [
            dev.partial.started_at + self._timeout
            for dev in self._devices.values()
            if dev.partial is not None
        ]
        return min(deadlines, default=None)

    def link_lost(self, device_id: str) -> tuple[ClipDropped, ...]:
        """Mất kết nối điều khiển với `device_id`: bỏ clip dở (`LINK_LOST`), giữ bucket."""
        dev = self._devices.get(device_id)
        if dev is None or dev.partial is None:
            return ()
        return (self._drop(device_id, dev, DropReason.LINK_LOST),)

    def forget_device(self, device_id: str) -> None:
        """Hủy ghép đôi: xóa mọi trạng thái của `device_id`, không phát sự kiện."""
        self._devices.pop(device_id, None)

    def discard(self, device_id: str) -> None:
        """Bỏ im lặng clip dở của `device_id` (nếu có), không phát sự kiện; giữ bucket.

        Clip bị bỏ được nhớ là "clip vừa bỏ": mảnh `index > 0` còn lại của nó bị bỏ im lặng.
        `app` gọi khi bỏ clip để giữ trần RAM chung (`reserved_bytes`).
        """
        dev = self._devices.get(device_id)
        if dev is not None and dev.partial is not None:
            self._drop(device_id, dev, DropReason.REPLACED)

    def buffered_bytes(self, device_id: str | None = None) -> int:
        """Số byte đang giữ trong clip dở của `device_id` (None: mọi thiết bị)."""
        if device_id is not None:
            dev = self._devices.get(device_id)
            return 0 if dev is None or dev.partial is None else dev.partial.received
        return sum(d.partial.received for d in self._devices.values() if d.partial is not None)

    def reserved_bytes(self, device_id: str | None = None) -> int:
        """Tổng `total` (cỡ khi ráp xong) của clip dở của `device_id` (None: mọi thiết bị).

        Là số byte RAM tối đa các clip dở có thể chiếm, kể cả phần chưa nhận; `app` dùng để
        giữ trần RAM chung trước khi cho một clip mới vào ráp.
        """
        if device_id is not None:
            dev = self._devices.get(device_id)
            return 0 if dev is None or dev.partial is None else dev.partial.total
        return sum(d.partial.total for d in self._devices.values() if d.partial is not None)

    def partials(self) -> tuple[PartialInfo, ...]:
        """Mọi clip dở, mỗi thiết bị ≤ 1, theo thứ tự thiết bị gửi mảnh đầu tiên.

        `app` dùng để chọn clip dở đã đứng (không có mảnh mới) hay đã giữ chỗ lâu mà bỏ đi
        (`discard`) khi clip mới không vừa trần RAM chung. Không tính hạn: clip đã quá hạn mà
        chưa có `tick` vẫn có mặt.
        """
        return tuple(
            PartialInfo(device_id, p.clip_id, p.total, p.received, p.started_at, p.progress_at)
            for device_id, dev in self._devices.items()
            if (p := dev.partial) is not None
        )

    # ---- Nội bộ --------------------------------------------------------------------------

    def _clamp(self, now: float) -> float:
        if self._now is not None and now < self._now:
            return self._now
        self._now = now
        return now

    def _expired(self, partial: _Partial, now: float) -> bool:
        return now >= partial.started_at + self._timeout

    def _drop(self, device_id: str, dev: _Device, reason: DropReason) -> ClipDropped:
        """Bỏ clip dở của `dev` và nhớ nó là clip vừa bỏ."""
        partial = dev.partial
        assert partial is not None
        dev.partial = None
        dev.last_dropped = partial.clip_id
        return ClipDropped(device_id, partial.clip_id, partial.kind, reason)

    def _reject(self, device_id: str, dev: _Device, msg: Clipboard, reason: DropReason) -> ClipDropped:
        """Bỏ clip mới `msg` (chưa mở) và nhớ nó là clip vừa bỏ."""
        dev.last_dropped = msg.clip_id
        return ClipDropped(device_id, msg.clip_id, msg.kind, reason)

    def _feed_first(
        self, device_id: str, dev: _Device, msg: Clipboard, now: float, events: list[ClipEvent]
    ) -> None:
        if dev.partial is not None and dev.partial.clip_id == msg.clip_id:
            events.append(self._drop(device_id, dev, DropReason.DUPLICATE))
            return
        if dev.bucket.available(now) < 1:
            events.append(self._reject(device_id, dev, msg, DropReason.RATE_LIMITED))
            return
        dev.bucket.take(1, now)
        if dev.partial is not None:
            events.append(self._drop(device_id, dev, DropReason.REPLACED))
        limit = self._limits.get(msg.kind)
        if limit is None:
            events.append(self._reject(device_id, dev, msg, DropReason.UNSUPPORTED_KIND))
            return
        if msg.total > limit:
            events.append(self._reject(device_id, dev, msg, DropReason.TOO_LARGE))
            return
        if msg.count > msg.total:
            events.append(self._reject(device_id, dev, msg, DropReason.INCONSISTENT))
            return
        partial = _Partial(msg.clip_id, msg.kind, msg.sha256, msg.total, msg.count, now, now)
        dev.partial = partial
        self._append(device_id, dev, partial, msg, now, events)

    def _feed_next(
        self,
        device_id: str,
        dev: _Device,
        partial: _Partial,
        msg: Clipboard,
        now: float,
        events: list[ClipEvent],
    ) -> None:
        if (msg.kind, msg.sha256, msg.total, msg.count) != (
            partial.kind,
            partial.sha256,
            partial.total,
            partial.count,
        ):
            events.append(self._drop(device_id, dev, DropReason.INCONSISTENT))
            return
        if msg.index != partial.next_index:
            events.append(self._drop(device_id, dev, DropReason.OUT_OF_ORDER))
            return
        self._append(device_id, dev, partial, msg, now, events)

    def _append(
        self,
        device_id: str,
        dev: _Device,
        partial: _Partial,
        msg: Clipboard,
        now: float,
        events: list[ClipEvent],
    ) -> None:
        # `msg` đã qua `core.messages`: text không có surrogate, PNG là base64 chuẩn.
        chunk = msg.data.encode("utf-8") if partial.kind == ClipKind.TEXT else decode_base64(msg.data)
        if partial.received + len(chunk) > partial.total:
            events.append(self._drop(device_id, dev, DropReason.SIZE_MISMATCH))
            return
        partial.buf += chunk
        partial.hasher.update(chunk)
        partial.received += len(chunk)
        partial.progress_at = now
        partial.next_index += 1
        if partial.next_index < partial.count:
            return
        if partial.received != partial.total:
            events.append(self._drop(device_id, dev, DropReason.SIZE_MISMATCH))
            return
        if partial.hasher.hexdigest() != partial.sha256:
            events.append(self._drop(device_id, dev, DropReason.HASH_MISMATCH))
            return
        raw = bytes(partial.buf)
        if partial.kind == ClipKind.PNG and not raw.startswith(PNG_SIGNATURE):
            events.append(self._drop(device_id, dev, DropReason.INVALID_CONTENT))
            return
        dev.partial = None
        # Text không chuẩn hóa lại: `content` khớp đúng `sha256` đã kiểm (docstring `ClipReady`).
        content: str | bytes = raw.decode("utf-8") if partial.kind == ClipKind.TEXT else raw
        events.append(ClipReady(device_id, partial.clip_id, ClipKind(partial.kind), content, partial.sha256))


# ---- Fingerprint và chống vòng lặp ---------------------------------------------------------


def text_fingerprint(text: str) -> str:
    """SHA-256 hex của `normalize_text(text)` mã hóa UTF-8.

    Bằng đúng `sha256` trên dây của clip text tạo từ `text`, và không đổi khi hệ điều hành
    đổi `\\n` thành `\\r\\n` lúc ghi clipboard.
    """
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


_IMAGE_FINGERPRINT_PREFIX = b"teleport-image-v1\0"


def image_fingerprint(width: int, height: int, pixel_format: str, pixels: bytes) -> str:
    """Fingerprint của ảnh theo **pixel**, không theo byte PNG (mã hóa lại PNG ra byte khác).

    Hợp đồng với `ui.clipboard_qt`: `pixels` là ảnh đã giải mã, đổi về **một** định dạng pixel cố định
    (ghi tên ở `pixel_format`, chuỗi ASCII không rỗng, không có NUL), các hàng nối liền nhau
    không đệm. Hai máy dùng cùng định dạng thì cùng ảnh cho cùng fingerprint. `width` hay
    `height` không phải số nguyên 1…`MAX_IMAGE_SIDE` → ValueError.
    """
    for name, side in (("width", width), ("height", height)):
        if type(side) is not int or not 1 <= side <= MAX_IMAGE_SIDE:
            raise ValueError(f"{name} phải là số nguyên 1…{MAX_IMAGE_SIDE}")
    if not isinstance(pixel_format, str) or not pixel_format or "\0" in pixel_format:
        raise ValueError("pixel_format phải là chuỗi ASCII không rỗng, không có NUL")
    h = hashlib.sha256(_IMAGE_FINGERPRINT_PREFIX)
    h.update(width.to_bytes(4, "big"))
    h.update(height.to_bytes(4, "big"))
    h.update(pixel_format.encode("ascii"))  # không phải ASCII → UnicodeEncodeError (ValueError)
    h.update(b"\0")
    h.update(pixels)
    return h.hexdigest()


class LoopGuard:
    """Chống vòng lặp clipboard: **một** đối tượng cho cả node, không hạn thời gian.

    Giữ tập fingerprint "hiện tại": nội dung clipboard máy này đang có mà không do người
    dùng máy này tạo ra.

    - Ghi clip nhận được vào clipboard → `remote_written(fp, ...)` với `fp =
      text_fingerprint(ClipReady.content)` (không phải `ClipReady.sha256`) hay fingerprint
      ảnh theo pixel; `app.clipboard` truyền cả fingerprint đọc lại sau khi ghi, phòng hệ điều hành đổi
      nội dung (ví dụ cắt NUL). Ghi thất bại → `restore` tập đã `snapshot` trước
      `remote_written`: clipboard vẫn giữ nội dung cũ, nên nội dung cũ vẫn không được gửi lại.
    - Clipboard đổi → `local_changed(fp)`: thuộc tập hiện tại → False (đó là clip vừa ghi,
      không gửi); không thì tập = {fp} và True (người dùng sao chép mới, gửi đi).

    Mô hình 3 máy A, B, C ghép đôi đôi một: A sao chép X → gửi B và C. B ghi X,
    `remote_written(X)`; clipboard B đổi → `local_changed(X)` False, nên B **không chuyển
    tiếp** X cho C (C đã nhận thẳng từ A). Máy chỉ gửi nội dung do chính người dùng nó tạo
    ra; clip nhận được không bao giờ được gửi tiếp. Sao chép lại đúng X trên B cũng không
    gửi (X vẫn là "hiện tại"), cho tới khi B có nội dung khác.
    """

    __slots__ = ("_current",)

    def __init__(self) -> None:
        self._current: frozenset[str] = frozenset()

    def local_changed(self, fingerprint: str) -> bool:
        """Clipboard máy này vừa đổi thành nội dung `fingerprint`; True nếu cần gửi đi."""
        if fingerprint in self._current:
            return False
        self._current = frozenset((fingerprint,))
        return True

    def remote_written(self, *fingerprints: str) -> None:
        """Vừa ghi clip nhận được vào clipboard: tập hiện tại = `fingerprints`."""
        self._current = frozenset(fingerprints)

    def is_current(self, fingerprint: str) -> bool:
        return fingerprint in self._current

    def reset(self) -> None:
        self._current = frozenset()

    def snapshot(self) -> frozenset[str]:
        """Tập hiện tại, để `restore` lại (ví dụ ghi clipboard thất bại sau `remote_written`)."""
        return self._current

    def restore(self, snapshot: frozenset[str]) -> None:
        """Trả tập hiện tại về `snapshot` đã lấy bằng `snapshot()`."""
        self._current = frozenset(snapshot)


# ---- Lọc nội dung nhạy cảm -----------------------------------------------------------------

# Có mặt là nhạy cảm (Windows; macOS NSPasteboard; KDE Klipper/KeePassXC trên Linux).
SENSITIVE_PRESENCE_FORMATS = frozenset(
    {
        "ExcludeClipboardContentFromMonitorProcessing",
        "org.nspasteboard.ConcealedType",
        "x-kde-passwordManagerHint",
    }
)
# Windows: nhạy cảm khi giá trị DWORD (4 byte little-endian) bằng 0.
SENSITIVE_DWORD_ZERO_FORMATS = frozenset({"CanIncludeInClipboardHistory", "CanUploadToCloudClipboard"})

_PRESENCE_CF = frozenset(n.casefold() for n in SENSITIVE_PRESENCE_FORMATS)
_DWORD_ZERO_CF = frozenset(n.casefold() for n in SENSITIVE_DWORD_ZERO_FORMATS)
# Qt đổi tên định dạng gốc của hệ điều hành thành kiểu MIME này (ví dụ trên Windows:
# `application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"`). So trên tên đã casefold.
_QT_NATIVE_MIME_RE = re.compile(r'application/x-qt-[a-z]+-mime;value="([^"]*)"', re.ASCII)


def _format_root(name: str) -> str:
    folded = name.casefold()
    m = _QT_NATIVE_MIME_RE.fullmatch(folded)
    return m.group(1) if m is not None else folded


def is_sensitive(formats: Iterable[str], value_of: Callable[[str], bytes | None]) -> bool:
    """Clipboard có định dạng mà trình quản lý mật khẩu dùng để đánh dấu "đừng đồng bộ" không.

    `formats`: tên định dạng như backend thấy (tên trần hoặc dạng
    `application/x-qt-<os>-mime;value="<tên>"` của Qt), so không phân biệt hoa thường.
    Có định dạng trong `SENSITIVE_PRESENCE_FORMATS` → True, không gọi `value_of`. Có định
    dạng trong `SENSITIVE_DWORD_ZERO_FORMATS` → `value_of(tên đúng như trong formats)`;
    `None`, < 4 byte hay DWORD little-endian bằng 0 → True (không đọc được thì coi là nhạy
    cảm). `value_of` chỉ được gọi cho các định dạng đó; nó ném thì lỗi đi thẳng ra ngoài.

    Tên trên macOS/Linux theo tài liệu của NSPasteboard và KDE, chưa kiểm tay (ke_hoach mục 3.6).
    """
    dword_names: list[str] = []
    for name in formats:
        root = _format_root(name)
        if root in _PRESENCE_CF:
            return True
        if root in _DWORD_ZERO_CF:
            dword_names.append(name)
    for name in dword_names:
        value = value_of(name)
        if value is None or len(value) < 4 or int.from_bytes(value[:4], "little") == 0:
            return True
    return False
