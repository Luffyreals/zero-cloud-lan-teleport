"""Đồng bộ clipboard của một node (mvp F8): chạy lõi `core.clipboard` trên kết nối điều khiển thật.

`ClipboardSync` (chỉ `Node` tạo khi có `ClipboardBackend`, lấy qua `node.clipboard`) chạy trên
loop của node. Đặc tả trên dây ở docs/protocol.md mục 3.3 (message `clipboard`); thiết kế ở
docs/ke_hoach.md mục 3.6; vị trí trong `Node` và thứ tự đóng ở docs/architecture.md mục 5. Đồng
bộ theo từng thiết bị tin cậy, mặc định tắt: `enabled(device_id)` (cài đặt “Đồng bộ clipboard”)
quyết định cả gửi lẫn nhận, nên clip chỉ đi khi **cả hai máy** cùng bật cho nhau.

- **Gửi:** backend báo clipboard đổi (`on_change`, từ thread bất kỳ) → hẹn đọc sau
  `CLIP_DEBOUNCE` (báo mới đặt lại hẹn giờ). Không có máy đích (đang kết nối và đã bật) thì không
  đọc và `LoopGuard.reset()`; xét lại trước `local_changed` và trước khi vào hàng gửi: máy đích
  mất hết trong lúc đọc hay tách clip → `reset()`, không gửi. Đọc (hạn `CLIP_READ_TIMEOUT`); nội
  dung nhạy cảm, rỗng, không hỗ trợ → `reset()`; quá trần → `reset()` + `TOO_LARGE`. Fingerprint
  văn bản và `split_clip` chạy trong executor một worker riêng. `LoopGuard.local_changed` False
  (clip vừa ghi từ máy khác) → không gửi: máy chỉ gửi nội dung do chính người dùng nó tạo ra. Cùng
  một tuple message vào hàng gửi của từng máy đích.
- **Hàng gửi** (`_ClipSender`, mỗi kết nối điều khiển một hàng, dựng khi có clip để gửi): một
  task gửi từng mảnh bằng `Connection.send`; ≤ 1 clip đang gửi + 1 clip chờ, clip mới thay clip
  chờ và cắt clip đang gửi sau mảnh hiện tại (bên nhận thấy `REPLACED`). Không đi qua `_Outbox`
  của truyền file, không tính `CONTROL_SEND_QUEUE_MAX`, nhưng **nhường** nó: trước mỗi mảnh chờ
  hàng gửi điều khiển của truyền file trên cùng kết nối trống (`control_idle`, tối đa
  `CLIP_YIELD_TIMEOUT`, hết hạn thì vẫn gửi để clip không đói mãi), nên một `cancel` hay `offer`
  chỉ phải xếp sau tối đa một mảnh clip đang gửi dở. Mỗi thiết bị một `TokenBucket` của bên gửi
  (`SENDER_RATE_FACTOR` × `CLIP_RATE`, `CLIP_BURST`) tính clip mới, trừ khi mảnh `index 0` thật
  sự được gửi; hết token thì clip mới nhất đợi ở chỗ chờ (bên nhận không phải bỏ vì
  `RATE_LIMITED`).
- **Nhận** (`on_message`, đồng bộ): bỏ trước khi ráp nếu mảnh không thuộc kết nối hiện tại, thiết
  bị chưa bật, đang tạm dừng nhận, hay thuộc clip đã bỏ vì trần RAM chung (`CLIP_RAM_BUDGET`, xét
  ở `index 0` theo `ClipAssembler.partials`). Thiết bị “đang bỏ dở” khi trong `CLIP_ABANDON_WINDOW`
  nó đã gửi mảnh `index 0` của clip mới lúc clip trước của chính nó chưa ráp xong (kể cả clip
  trước bị bỏ vì sai hay vì hết token; trừ khi máy này bỏ nó vì trần RAM lúc máy kia chưa bỏ
  dở) hay để clip hết hạn.
  Clip mới không vừa trần, và thiết bị của nó không đang bỏ dở, thì đẩy ra clip dở của máy khác
  đang bỏ dở, đã đứng (không có mảnh mới trong `CLIP_STALL_EVICT`) hay đã giữ chỗ quá
  `CLIP_HOLD_EVICT`, theo thứ tự: máy bỏ dở, rồi đứng lâu nhất, rồi cũ nhất, vừa đủ chỗ, nếu nhờ
  vậy vừa; không thì bỏ clip mới và cả clip đang ráp của thiết bị đó. Còn lại →
  `ClipAssembler.feed`, hẹn `tick` theo `next_wakeup`. `ClipReady` vào hàng ghi (1 đang ghi + 1
  chờ, mới thay chờ).
- **Ghi** (hạn `CLIP_WRITE_TIMEOUT`): văn bản `fp = text_fingerprint(content)` (executor, không
  dùng `ClipReady.sha256`); `is_current(fp)` → không ghi (trừ khi `fp` là của lần ghi văn bản lỗi
  gần nhất: máy kia gửi lại đúng nội dung đó thì vẫn ghi); `remote_written(fp)` **trước** khi ghi,
  xong `remote_written(fp, *fingerprint đọc lại)`. Ảnh luôn ghi, xong `remote_written(*fingerprint
  đọc lại)`. Thành công → `RECEIVED`; lỗi/quá hạn → giữ làm “clip ghi lỗi gần nhất” (một cho cả
  node) + `WRITE_FAILED` (văn bản thì `LoopGuard.restore` về tập trước lần ghi: clipboard vẫn là
  nội dung cũ, một `on_change` thừa không gửi lại nội dung đó); `REJECTED` (ảnh quá cạnh, hỏng)
  chỉ log INFO. Ngay trước khi gọi backend và trước khi báo kết quả, kiểm lại `enabled` (và
  `paused`, trừ “Thử lại”): tắt đồng bộ, hủy ghép đôi hay tạm dừng trong lúc đó → không ghi
  (đã ghi thì vẫn cập nhật `LoopGuard`), không báo gì.
- **Tuần tự hóa backend:** mỗi lúc một thao tác, đọc hoặc ghi. Clipboard đổi trong lúc đang
  đọc/ghi chỉ đánh dấu “bẩn”, xong việc hẹn đọc lại: nhờ vậy `remote_written` luôn chạy trước lần
  đọc do chính lần ghi gây ra. Ghi chờ đọc đang chạy; ghi chờ được ưu tiên hơn lần đọc hẹn lại.
- **“Thử lại”** (`retry_write`): ghi lại clip lỗi gần nhất nếu của thiết bị đó, qua hàng ghi;
  gọi lại khi lần trước chưa xong thì chờ chung kết quả đó, không ghi thêm lần nào.
  Clip lỗi bị xóa khi có clip mới từ máy bất kỳ, khi người dùng máy này sao chép nội dung mới, khi
  tắt đồng bộ với máy đó, hủy ghép đôi, `close()`. Tạm dừng nhận không xóa nó.
- **Đổi/mất kết nối:** `link_up` sang `conn_id` khác (`LinkSwitched`) và `link_down` bỏ clip đang
  ráp (`link_lost`), hủy hàng gửi của kết nối cũ (kết nối đó đã chết) và bỏ clip đang gửi, chờ gửi
  (không gửi lại). Tắt đồng bộ, hủy ghép đôi, `close()` chỉ **đóng gọn** hàng gửi: mảnh đang gửi
  được gửi xong rồi task dừng, vì hủy giữa khung làm `Connection` abort cả kết nối điều khiển
  đang sống. Bật lại không gửi bù.

Sự kiện cho giao diện: callback `on_event` (`ClipboardEvent`, mã kết quả `ClipOutcome`), gọi đồng bộ
trên loop; raise thì chỉ ghi log; sau `close()` không phát nữa. Nhạy cảm, đọc lỗi, ảnh bị từ chối,
clip bị bỏ chỉ ghi log. **mvp N9:** log chỉ có kind, số byte và 8 ký tự đầu `device_id`; lỗi backend
chỉ ghi tên loại; mọi trường mang nội dung có `repr=False`.

**Hợp đồng `ClipboardBackend`** (`ui.clipboard_qt` viết bản Qt; `FakeClipboard` ở đây cho test và đo):

- `start(on_change)` gọi trên loop; `on_change` gọi được từ **mọi** thread, không bao giờ raise,
  có thể gọi thừa (kể cả ngay sau lần `write` của chính nó). `stop()` trên loop; sau đó
  `on_change` thôi được gọi.
- `read()` trả `ClipRead`. `OK` cần `content`: văn bản là `str` (`fingerprint` bị bỏ qua:
  `ClipboardSync` tự tính `text_fingerprint`), ảnh là byte PNG với `fingerprint =
  image_fingerprint(...)` theo pixel (hợp đồng ở `core.clipboard`). Văn bản dài hơn 2 ×
  `MAX_TEXT_BYTES` code point hay ảnh cạnh > `MAX_IMAGE_SIDE` → `TOO_LARGE` (`size` là cỡ đo
  được). Định dạng nhạy cảm (`core.clipboard.is_sensitive`) → `SENSITIVE`. **Ảnh `OK` với `data`
  rỗng (`b""`) = ảnh vọng của lần `write` ảnh gần nhất** (backend nhận ra đúng ảnh nó vừa ghi):
  chỉ có `fingerprint`, backend khỏi mã hóa lại PNG; `ClipboardSync` chỉ cập nhật `LoopGuard`
  (`local_changed`) và không bao giờ gửi nó.
- `write(kind, data)` trả `ClipWrite`; `fingerprints` là fingerprint của nội dung **đọc lại** sau
  khi ghi (hệ điều hành có thể đổi `\\n` thành `\\r\\n` hay cắt ở NUL); ảnh trả cả `image_size`.
  Ảnh hỏng, quá cạnh hay vượt trần giải mã → `REJECTED`; clipboard đang bị giữ → `FAILED`.
- Có thể chậm hay treo: `ClipboardSync` chỉ chờ trong hạn, bị hủy thì bỏ kết quả; `close()` không
  chờ backend. Mọi lỗi (exception) của backend được coi như `FAILED`.

Bẫy: `close()` đồng bộ, không chờ gì: task gửi không ở trong `Connection.send` bị hủy ngay (chưa
ghi gì, kết nối vẫn dùng được), task đang gửi một mảnh thì gửi xong mảnh đó rồi dừng. `Node.close`
chờ các task đó tối đa `CLIP_CLOSE_WAIT` (`drain`) rồi mới đẩy `cancel` (`transfers.flush_control`);
task còn lại chỉ bị hủy cứng ở `abort()` (gọi sau `flush_control`, khi kết nối sắp đóng). Mọi hàng
gửi đã đóng mà task chưa dừng (kể cả hàng đã bị thay) đều được `drain` chờ và `abort()` hủy.
`ClipboardSync._now` là seam đồng hồ của phần nhận (test vá được). Hằng cấp module đọc lúc dùng
(test vá được); `CLIP_ASSEMBLY_TIMEOUT`, `CLIP_RATE`, `CLIP_BURST`
của `core.clipboard` đọc lúc dựng `ClipboardSync`.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import logging
import time
import uuid
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, TypeVar

from teleport.core import clipboard as core_clipboard
from teleport.core.clipboard import (
    MAX_CLIP_BYTES,
    MAX_TEXT_BYTES,
    PNG_SIGNATURE,
    ClipAssembler,
    ClipDropped,
    ClipReady,
    ClipTooLarge,
    DropReason,
    LoopGuard,
    PartialInfo,
    split_clip,
    text_fingerprint,
)
from teleport.core.messages import Clipboard, ClipKind
from teleport.core.ratelimit import TokenBucket
from teleport.net.connection import Connection, ConnectionLostError

CLIP_DEBOUNCE = 0.15  # giây: gộp các lần clipboard đổi liên tiếp
CLIP_READ_TIMEOUT = 10.0  # giây chờ backend đọc
CLIP_WRITE_TIMEOUT = 10.0  # giây chờ backend ghi (ảnh 8192² có thể mất vài giây)
CLIP_RAM_BUDGET = 24 * 1024 * 1024  # byte: trần chung cho clip đang ráp của mọi thiết bị
CLIP_STALL_EVICT = 1.0  # giây không có mảnh mới: clip dở của máy khác bị đẩy ra cho clip mới vừa trần
CLIP_HOLD_EVICT = 3.0  # giây từ mảnh 0: clip dở của máy khác giữ chỗ quá lâu, cũng bị đẩy ra được
CLIP_ABANDON_WINDOW = 10.0  # giây: thiết bị vừa bỏ dở clip của chính nó bị coi là “đang bỏ dở”
CLIP_YIELD_TIMEOUT = 2.0  # giây tối đa một mảnh clip chờ hàng gửi truyền file trống (rồi vẫn gửi)
CLIP_CLOSE_WAIT = 1.0  # giây `Node.close` chờ mảnh clip đang gửi dở xong, trước khi đẩy `cancel`
PREVIEW_CHARS = 200  # code point tối đa của `ClipboardEvent.preview`
SENDER_RATE_FACTOR = 0.8  # bên gửi tự giới hạn ở 0,8 × CLIP_RATE (protocol §3.3, “Bên gửi”)
BUDGET_INFO_INTERVAL = 60.0  # giây: tối đa một dòng INFO “bỏ vì trần RAM” mỗi thiết bị
uuid4 = uuid.uuid4  # seam: sinh `clip_id`

_TASK_NAME = "teleport.clipboard"

log = logging.getLogger(__name__)

_T = TypeVar("_T")


# ---- Kiểu dữ liệu với backend --------------------------------------------------------------


class ReadStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    UNSUPPORTED = "unsupported"
    SENSITIVE = "sensitive"
    TOO_LARGE = "too_large"
    FAILED = "failed"


class WriteStatus(StrEnum):
    OK = "ok"
    REJECTED = "rejected"  # ảnh quá cạnh, hỏng hay vượt trần giải mã: thử lại cũng không được
    FAILED = "failed"  # không ghi được lúc này (ví dụ ứng dụng khác đang giữ clipboard)


@dataclass(frozen=True, slots=True)
class ClipContent:
    """Nội dung clipboard: văn bản (`str`) hay ảnh PNG (`bytes`) kèm fingerprint (`core.clipboard`)."""

    kind: ClipKind
    data: str | bytes = field(repr=False)  # N9: repr/log không lộ nội dung
    fingerprint: str


@dataclass(frozen=True, slots=True)
class ClipRead:
    """Kết quả `ClipboardBackend.read`. `content` chỉ có khi `OK`; `size`: số byte (hay code point)."""

    status: ReadStatus
    content: ClipContent | None = None
    size: int = 0


@dataclass(frozen=True, slots=True)
class ClipWrite:
    """Kết quả `ClipboardBackend.write`: fingerprint đọc lại sau khi ghi, cỡ ảnh (rộng, cao)."""

    status: WriteStatus
    fingerprints: tuple[str, ...] = ()
    image_size: tuple[int, int] | None = None


class ClipboardBackend(Protocol):
    """Clipboard thật của hệ điều hành (hợp đồng ở docstring module)."""

    def start(self, on_change: Callable[[], None]) -> None: ...

    def stop(self) -> None: ...

    async def read(self) -> ClipRead: ...

    async def write(self, kind: ClipKind, data: str | bytes) -> ClipWrite: ...


# ---- Sự kiện cho giao diện -----------------------------------------------------------------


class ClipOutcome(StrEnum):
    SENT = "sent"  # đã ghi xuống socket (máy kia vẫn có thể bỏ, ví dụ chưa bật đồng bộ)
    RECEIVED = "received"  # đã chép vào clipboard máy này
    TOO_LARGE = "too_large"  # nội dung vừa sao chép vượt trần nên không gửi
    WRITE_FAILED = "write_failed"  # nhận được mà không chép được: “Thử lại”
    NOTHING_TO_RETRY = "nothing_to_retry"  # `retry_write`: không còn clip để chép lại


@dataclass(frozen=True, slots=True)
class ClipboardEvent:
    """Một kết quả cho giao diện. `device_id` None với `TOO_LARGE` (không gắn với máy nào).

    `SENT`: mỗi thiết bị một lần, khi mảnh cuối đã gửi xong. `preview`: chỉ `RECEIVED` văn bản, ≤
    `PREVIEW_CHARS` code point đầu; `image_size` (rộng, cao): `RECEIVED` ảnh.
    """

    outcome: ClipOutcome
    device_id: str | None
    kind: ClipKind | None
    size: int
    clip_id: str | None = None
    preview: str | None = field(default=None, repr=False)
    image_size: tuple[int, int] | None = None


# ---- Clipboard giả -------------------------------------------------------------------------


def _fake_image_fingerprint(png: bytes) -> str:
    return hashlib.sha256(b"fake-image\0" + png).hexdigest()


def _png_size(png: bytes) -> tuple[int, int] | None:
    """(rộng, cao) trong chunk IHDR của PNG; không đọc được → None."""
    if len(png) < 24 or not png.startswith(PNG_SIGNATURE) or png[12:16] != b"IHDR":
        return None
    return int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")


class FakeClipboard:
    """`ClipboardBackend` giả trong RAM, cho test và do-dac (không cần Qt).

    `set_text` / `set_image` giả người dùng sao chép rồi gọi `on_change`; `write` cũng gọi
    `on_change` như clipboard thật. Ảnh không giải mã: fingerprint mặc định là hash của byte PNG,
    `image_size` đọc từ IHDR (không đọc được → `REJECTED`).

    - `transform`: hàm đổi văn bản lúc ghi, giả hệ điều hành (ví dụ `\\n` → `\\r\\n`, cắt ở NUL).
    - `fail_read`, `fail_write`: trả `FAILED`. `delay`: giây chờ trước mỗi lần đọc/ghi.
    - `writes`: `(time.monotonic(), ClipContent)` của mỗi lần ghi thành công; `reads`: số lần đọc.
    """

    def __init__(self) -> None:
        self.transform: Callable[[str], str] | None = None
        self.fail_read = False
        self.fail_write = False
        self.delay = 0.0
        self.writes: list[tuple[float, ClipContent]] = []
        self.reads = 0
        self._content: ClipContent | None = None
        self._sensitive = False
        self._on_change: Callable[[], None] | None = None

    @property
    def content(self) -> ClipContent | None:
        """Nội dung clipboard giả hiện tại."""
        return self._content

    def start(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change

    def stop(self) -> None:
        self._on_change = None

    def set_text(self, text: str, *, sensitive: bool = False) -> None:
        """Giả người dùng sao chép văn bản (`sensitive`: có định dạng của trình quản lý mật khẩu)."""
        self._content = ClipContent(ClipKind.TEXT, text, text_fingerprint(text))
        self._sensitive = sensitive
        self._changed()

    def set_image(self, png: bytes, fingerprint: str | None = None) -> None:
        """Giả người dùng sao chép ảnh; `fingerprint` None → hash của byte PNG."""
        fp = _fake_image_fingerprint(png) if fingerprint is None else fingerprint
        self._content = ClipContent(ClipKind.PNG, png, fp)
        self._sensitive = False
        self._changed()

    def clear(self) -> None:
        """Giả clipboard rỗng."""
        self._content = None
        self._sensitive = False
        self._changed()

    async def read(self) -> ClipRead:
        self.reads += 1
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.fail_read:
            return ClipRead(ReadStatus.FAILED)
        content = self._content
        if content is None:
            return ClipRead(ReadStatus.EMPTY)
        if self._sensitive:
            return ClipRead(ReadStatus.SENSITIVE)
        size = len(content.data)
        if content.kind == ClipKind.TEXT and size > 2 * MAX_TEXT_BYTES:
            return ClipRead(ReadStatus.TOO_LARGE, size=size)
        return ClipRead(ReadStatus.OK, content, size)

    async def write(self, kind: ClipKind, data: str | bytes) -> ClipWrite:
        if self.delay > 0:
            await asyncio.sleep(self.delay)
        if self.fail_write:
            return ClipWrite(WriteStatus.FAILED)
        image_size: tuple[int, int] | None = None
        if kind == ClipKind.TEXT and isinstance(data, str):
            stored = data if self.transform is None else self.transform(data)
            content = ClipContent(ClipKind.TEXT, stored, text_fingerprint(stored))
        elif kind == ClipKind.PNG and isinstance(data, bytes):
            image_size = _png_size(data)
            if image_size is None:
                return ClipWrite(WriteStatus.REJECTED)
            content = ClipContent(ClipKind.PNG, data, _fake_image_fingerprint(data))
        else:
            return ClipWrite(WriteStatus.REJECTED)
        self._content = content
        self._sensitive = False
        self.writes.append((time.monotonic(), content))
        self._changed()
        return ClipWrite(WriteStatus.OK, (content.fingerprint,), image_size)

    def _changed(self) -> None:
        callback = self._on_change
        if callback is not None:
            callback()


# ---- Hàng gửi ------------------------------------------------------------------------------


class _ClipSender:
    """Hàng gửi clip trên một kết nối điều khiển: ≤ 1 clip đang gửi + 1 clip chờ, một task.

    `put` thay clip chờ và làm clip đang gửi dừng sau mảnh hiện tại. `close` đóng gọn: mảnh đang
    gửi được gửi xong rồi task dừng (không abort kết nối); không đang gửi thì hủy task ngay. `abort`
    hủy task ngay: chỉ dùng khi kết nối đã chết hay sắp đóng (hủy giữa khung thì `Connection` abort
    kết nối). `idle(device_id, conn_id)`: sự kiện “hàng gửi truyền file trên kết nối này trống” để
    nhường (None: không nhường).
    """

    def __init__(
        self,
        device_id: str,
        conn_id: int,
        conn: Connection,
        bucket: TokenBucket,
        on_sent: Callable[[str, tuple[Clipboard, ...]], None],
        idle: Callable[[str, int], asyncio.Event | None] | None = None,
    ) -> None:
        self.device_id = device_id
        self.conn_id = conn_id
        self._conn = conn
        self._bucket = bucket  # của thiết bị (giữ qua các lần dựng lại hàng)
        self._on_sent = on_sent
        self._idle = idle
        self._pending: tuple[Clipboard, ...] | None = None
        self._wake = asyncio.Event()
        self.closing = False
        self._sending = False  # đang ở trong `Connection.send`: hủy lúc này có thể cắt giữa khung
        self.task = asyncio.create_task(self._run(), name=f"{_TASK_NAME}.send {device_id[:8]}")

    def put(self, msgs: tuple[Clipboard, ...]) -> None:
        if self.closing:
            return
        self._pending = msgs
        self._wake.set()

    def close(self) -> None:
        self.closing = True
        self._pending = None
        self._wake.set()
        if not self._sending:
            self.task.cancel()  # đang chờ (clip, token, lượt nhường): chưa ghi gì, hủy an toàn

    def abort(self) -> None:
        self.close()
        self.task.cancel()

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        try:
            while not self.closing:
                if self._pending is None:
                    self._wake.clear()
                    await self._wake.wait()
                    continue
                delay = self._bucket.delay(1, loop.time())
                if delay > 0:
                    # Hết token: chờ, clip mới tới trong lúc đó thay clip chờ.
                    self._wake.clear()
                    with contextlib.suppress(TimeoutError):
                        async with asyncio.timeout(delay):
                            await self._wake.wait()
                    continue
                await self._yield_to_transfers()
                # Lấy clip mới nhất và token ngay trước mảnh 0, không có await ở giữa.
                msgs = self._pending
                if self.closing or msgs is None or self._bucket.delay(1, loop.time()) > 0:
                    continue
                self._pending = None
                self._bucket.take(1, loop.time())
                if await self._send(msgs):
                    self._on_sent(self.device_id, msgs)
        except ConnectionLostError:
            return

    async def _send(self, msgs: tuple[Clipboard, ...]) -> bool:
        """Gửi các mảnh của một clip; False nếu bị cắt (clip mới, đóng) hay lỗi lập trình.

        Kiểm `closing` ngay trước **mỗi** mảnh; mảnh `index > 0` nhường hàng gửi truyền file trước.
        """
        for msg in msgs:
            if msg.index > 0:
                if self.closing or self._pending is not None:
                    return False
                await self._yield_to_transfers()
            if self.closing or (msg.index > 0 and self._pending is not None):
                return False
            self._sending = True
            try:
                await self._conn.send(msg)
            except ValueError:
                log.exception("không gửi được clipboard tới %s", self.device_id[:8])
                return False
            finally:
                self._sending = False
        return True

    async def _yield_to_transfers(self) -> None:
        """Chờ hàng gửi truyền file trên kết nối này trống, tối đa `CLIP_YIELD_TIMEOUT`."""
        event = None if self._idle is None else self._idle(self.device_id, self.conn_id)
        if event is None or event.is_set():
            return
        with contextlib.suppress(TimeoutError):
            async with asyncio.timeout(CLIP_YIELD_TIMEOUT):
                await event.wait()


# ---- ClipboardSync -------------------------------------------------------------------------


@dataclass(eq=False)
class _WriteJob:
    """Một clip chờ ghi vào clipboard máy này. `future`: kết quả cho `retry_write`."""

    clip: ClipReady
    generation: int  # `ClipboardSync._generation` lúc xếp: clip mới hơn tới thì lỗi không được giữ
    retry: bool = False
    future: asyncio.Future[ClipOutcome] | None = None

    def resolve(self, outcome: ClipOutcome) -> None:
        if self.future is not None and not self.future.done():
            self.future.set_result(outcome)


class ClipboardSync:
    """Đồng bộ clipboard của một node; chỉ `Node` tạo. Xem docstring module.

    `enabled(device_id)`: đồng bộ với thiết bị đó không (đọc lúc dùng); `paused()`: đang tạm dừng
    nhận (bỏ clip tới, vẫn gửi). `control_idle(device_id, conn_id)`: sự kiện đặt khi hàng gửi
    điều khiển của truyền file trên kết nối đó trống (`TransferManager.control_idle`), None: không
    có hàng nào để nhường. Mọi phương thức chạy trên loop của node; sau `close()` không làm gì.
    """

    def __init__(
        self,
        *,
        backend: ClipboardBackend,
        enabled: Callable[[str], bool],
        paused: Callable[[], bool],
        on_event: Callable[[ClipboardEvent], None],
        control_idle: Callable[[str, int], asyncio.Event | None] | None = None,
    ) -> None:
        self._backend = backend
        self._enabled = enabled
        self._paused = paused
        self._on_event = on_event
        self._control_idle = control_idle
        self._rate = core_clipboard.CLIP_RATE
        self._burst = core_clipboard.CLIP_BURST
        self._assembler = ClipAssembler(
            timeout=core_clipboard.CLIP_ASSEMBLY_TIMEOUT, rate=self._rate, burst=self._burst
        )
        self._guard = LoopGuard()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="teleport-clip")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._closed = False
        self._links: dict[str, tuple[int, Connection]] = {}  # device_id → kết nối điều khiển hiện tại
        self._senders: dict[str, _ClipSender] = {}
        self._retired: set[_ClipSender] = set()  # hàng đã đóng, đã rời `_senders`, task chưa dừng
        self._buckets: dict[str, TokenBucket] = {}  # bucket clip mới của bên gửi, theo thiết bị
        self._debounce: asyncio.TimerHandle | None = None
        self._tick_handle: asyncio.TimerHandle | None = None
        self._op: asyncio.Task[None] | None = None  # thao tác backend đang chạy (đọc hoặc ghi)
        self._dirty = False  # clipboard đổi trong lúc đang đọc/ghi: đọc lại khi xong
        self._write_pending: _WriteJob | None = None
        self._writing: _WriteJob | None = None  # lần ghi đang chạy (`_op` là task của nó)
        self._failed: ClipReady | None = None  # clip ghi lỗi gần nhất (“Thử lại”)
        # (device_id, fingerprint) văn bản của lần ghi lỗi/quá hạn gần nhất: fingerprint đó nằm trong
        # `LoopGuard` (chặn chuyển tiếp) nhưng không chặn ghi lại khi máy kia gửi lại đúng nội dung đó.
        self._failed_fp: tuple[str, str] | None = None
        self._generation = 0  # tăng khi có clip mới từ máy khác hay người dùng máy này sao chép mới
        self._over_budget: dict[str, str] = {}  # device_id → clip_id đã bỏ vì trần RAM chung
        self._budget_logged: dict[str, float] = {}  # device_id → lần ghi INFO gần nhất (giờ loop)
        self._abandoned: dict[str, float] = {}  # device_id → lần gần nhất bỏ dở clip của chính nó
        self._open_clip: dict[str, str] = {}  # device_id → clip_id của mảnh 0 gần nhất chưa ráp xong

    # ---- Vòng đời --------------------------------------------------------------------------

    def start(self) -> None:
        """Bắt đầu theo dõi clipboard (`backend.start`), trên loop. Backend lỗi thì chỉ WARNING:
        vẫn nhận được clip, chỉ không gửi."""
        if self._closed or self._loop is not None:
            return
        self._loop = asyncio.get_running_loop()
        try:
            self._backend.start(self._on_change)
        except Exception as e:
            log.warning("không theo dõi được clipboard (%s)", type(e).__name__)

    def close(self) -> None:
        """Dừng (đồng bộ, không chờ backend): `backend.stop()`, hủy hẹn giờ và thao tác đang chạy,
        đóng gọn mọi hàng gửi, bỏ clip chờ ghi và clip lỗi, tắt executor. Gọi lại không làm gì."""
        if self._closed:
            return
        self._closed = True
        if self._loop is not None:
            try:
                self._backend.stop()
            except Exception as e:
                log.warning("lỗi khi dừng theo dõi clipboard (%s)", type(e).__name__)
        for handle in (self._debounce, self._tick_handle):
            if handle is not None:
                handle.cancel()
        self._debounce = self._tick_handle = None
        if self._op is not None:
            self._op.cancel()
        self._drop_pending_write()
        self._failed = None
        self._failed_fp = None
        for sender in self._senders.values():
            sender.close()
        self._links.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)

    async def drain(self, timeout: float) -> None:
        """Chờ tối đa `timeout` giây cho mọi task gửi đã đóng dừng (mảnh đang gửi dở gửi xong).

        `Node.close` gọi sau `close()`, trước khi đẩy `cancel`: mảnh clip không còn chiếm khóa gửi
        của kết nối điều khiển khi `cancel` cần nó.
        """
        tasks = [s.task for s in (*self._senders.values(), *self._retired) if not s.task.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)

    def abort(self) -> None:
        """`close()` rồi hủy cứng các task gửi còn lại (kết nối sắp bị đóng). Gọi lại không làm gì."""
        self.close()
        for sender in [*self._senders.values(), *self._retired]:
            sender.abort()

    # ---- Kết nối ---------------------------------------------------------------------------

    def link_up(self, device_id: str, conn_id: int, conn: Connection) -> None:
        """Kết nối điều khiển hiện tại của thiết bị là `conn` (`LinkUp` hay `LinkSwitched`).

        Kết nối cũ (nếu khác) coi như đã mất: bỏ clip đang ráp, hủy hàng gửi của nó.
        """
        if self._closed:
            return
        old = self._links.get(device_id)
        self._links[device_id] = (conn_id, conn)
        if old is not None and old[0] != conn_id:
            self._lost(device_id)

    def link_down(self, device_id: str, conn_id: int) -> None:
        """Mất kết nối điều khiển `conn_id` (`LinkDown`); kết nối khác kết nối hiện tại thì bỏ qua."""
        if self._closed:
            return
        old = self._links.get(device_id)
        if old is None or old[0] != conn_id:
            return
        del self._links[device_id]
        self._lost(device_id)

    def _lost(self, device_id: str) -> None:
        self._log_drops(self._assembler.link_lost(device_id))
        self._over_budget.pop(device_id, None)
        self._open_clip.pop(device_id, None)
        sender = self._senders.pop(device_id, None)
        if sender is not None:
            sender.abort()  # kết nối cũ đã chết: bỏ clip đang gửi và chờ, không gửi lại
        for old in [s for s in self._retired if s.device_id == device_id]:
            old.abort()

    # ---- Cài đặt ---------------------------------------------------------------------------

    def set_enabled(self, device_id: str, enabled: bool) -> None:
        """Đồng bộ với thiết bị vừa bật/tắt (bên gọi đã lưu cài đặt; `enabled` đọc lại lúc dùng).

        Tắt: đóng gọn hàng gửi, bỏ clip đang ráp, clip chờ ghi và clip lỗi của máy đó. Bật: không
        gửi bù.
        """
        if self._closed or enabled:
            return
        self._forget(device_id)

    def forget_device(self, device_id: str) -> None:
        """Hủy ghép đôi (đồng bộ, trong `Node.unpair`): như tắt, và quên bucket của thiết bị."""
        if self._closed:
            return
        self._forget(device_id)
        self._buckets.pop(device_id, None)
        self._budget_logged.pop(device_id, None)
        self._abandoned.pop(device_id, None)
        self._open_clip.pop(device_id, None)

    def _forget(self, device_id: str) -> None:
        sender = self._senders.pop(device_id, None)
        if sender is not None:
            self._retire(sender)
        self._assembler.forget_device(device_id)
        self._over_budget.pop(device_id, None)
        self._open_clip.pop(device_id, None)
        pending = self._write_pending
        if pending is not None and pending.clip.device_id == device_id:
            self._write_pending = None
            pending.resolve(ClipOutcome.NOTHING_TO_RETRY)
        if self._failed is not None and self._failed.device_id == device_id:
            self._failed = None
        if self._failed_fp is not None and self._failed_fp[0] == device_id:
            self._failed_fp = None

    # ---- Gửi -------------------------------------------------------------------------------

    def _on_change(self) -> None:
        """Backend: clipboard vừa đổi. Gọi được từ mọi thread, không raise."""
        loop = self._loop
        if loop is None or self._closed:
            return
        with contextlib.suppress(RuntimeError):  # loop đã đóng
            loop.call_soon_threadsafe(self._changed)

    def _changed(self) -> None:
        if self._closed:
            return
        if self._op is not None:
            self._dirty = True
            return
        self._arm_debounce()

    def _arm_debounce(self) -> None:
        assert self._loop is not None
        if self._debounce is not None:
            self._debounce.cancel()
        self._debounce = self._loop.call_later(CLIP_DEBOUNCE, self._debounce_fired)

    def _debounce_fired(self) -> None:
        self._debounce = None
        if self._closed:
            return
        if self._op is not None:
            self._dirty = True
            return
        if not self._targets():
            self._guard.reset()  # không đọc: lần sau sao chép lại cùng nội dung vẫn được gửi
            return
        self._start_op(self._read_and_send(), "read")

    def _targets(self) -> list[str]:
        """Máy đích: đang có kết nối điều khiển và đã bật đồng bộ (đọc lúc gọi)."""
        return [device_id for device_id in self._links if self._enabled(device_id)]

    async def _read_and_send(self) -> None:
        read = await self._read()
        if read is None or self._closed:
            return
        content = read.content
        if read.status is ReadStatus.FAILED:
            log.warning("không đọc được clipboard")
            return
        if read.status is not ReadStatus.OK:
            self._guard.reset()
            if read.status is ReadStatus.TOO_LARGE:
                self._too_large(None if content is None else content.kind, read.size)
            else:
                log.debug("clipboard máy này không gửi (%s)", read.status.value)
            return
        if content is None or not _content_ok(content.kind, content.data):
            log.warning("backend clipboard trả nội dung sai kiểu")
            return
        if content.kind == ClipKind.PNG and not content.data:
            # Ảnh vọng của lần ghi gần nhất (hợp đồng backend): đó là clip nhận từ máy khác, không
            # phải người dùng máy này sao chép, nên chỉ ghi nhận fingerprint, không gửi.
            self._guard.local_changed(content.fingerprint)
            log.debug("clipboard máy này là ảnh vừa ghi, không gửi")
            return
        if content.kind == ClipKind.TEXT:
            fingerprint = await self._offload(text_fingerprint, content.data)
            if fingerprint is None:
                return
        else:
            fingerprint = content.fingerprint
        if not self._targets():
            # Máy đích mất kết nối (hay bị tắt) trong lúc đọc: như `_debounce_fired`, không ghi
            # nhận nội dung, để sao chép lại sau khi nối lại vẫn được gửi.
            self._guard.reset()
            return
        if not self._guard.local_changed(fingerprint):
            return  # clip vừa ghi từ máy khác (hay vẫn là nội dung đã gửi): không gửi
        self._generation += 1
        self._failed = None  # người dùng máy này vừa sao chép mới
        self._failed_fp = None
        try:
            msgs = await self._offload(split_clip, uuid4().hex, content.kind, content.data)
        except ClipTooLarge as e:
            self._guard.reset()
            self._too_large(content.kind, e.size)
            return
        except ValueError as e:
            log.debug("clipboard máy này không gửi được (%s)", type(e).__name__)
            return
        if msgs is None or self._closed:
            return
        clip = tuple(msgs)
        targets = self._targets()
        if not targets:
            self._guard.reset()  # máy đích mất trong lúc tách clip: như trên
            return
        for device_id in targets:
            self._enqueue_send(device_id, clip)
        log.debug("gửi clipboard %s, %d byte", content.kind.value, clip[0].total)

    async def _read(self) -> ClipRead | None:
        try:
            async with asyncio.timeout(CLIP_READ_TIMEOUT):
                return await self._backend.read()
        except TimeoutError:
            log.warning("đọc clipboard quá %.0f s", CLIP_READ_TIMEOUT)
        except Exception as e:
            log.warning("không đọc được clipboard (%s)", type(e).__name__)
        return None

    def _too_large(self, kind: ClipKind | None, size: int) -> None:
        if not self._targets():
            return
        log.info("clipboard máy này quá lớn nên không gửi (%d byte)", size)
        self._emit(ClipboardEvent(ClipOutcome.TOO_LARGE, None, kind, size))

    def _enqueue_send(self, device_id: str, clip: tuple[Clipboard, ...]) -> None:
        link = self._links.get(device_id)
        if link is None:
            return
        conn_id, conn = link
        sender = self._senders.get(device_id)
        if sender is None or sender.closing or sender.conn_id != conn_id:
            if sender is not None:
                self._retire(sender)
            bucket = self._buckets.get(device_id)
            if bucket is None:
                bucket = self._buckets[device_id] = TokenBucket(self._rate * SENDER_RATE_FACTOR, self._burst)
            sender = _ClipSender(device_id, conn_id, conn, bucket, self._sent, self._control_idle)
            self._senders[device_id] = sender
            sender.task.add_done_callback(functools.partial(self._sender_done, sender))
        sender.put(clip)

    def _retire(self, sender: _ClipSender) -> None:
        """Đóng gọn một hàng vừa rời `_senders`; task chưa dừng thì giữ để `drain`/`abort` tới được."""
        sender.close()
        if not sender.task.done():
            self._retired.add(sender)

    def _sender_done(self, sender: _ClipSender, task: asyncio.Task[None]) -> None:
        self._retired.discard(sender)
        if self._senders.get(sender.device_id) is sender:
            del self._senders[sender.device_id]
        error = None if task.cancelled() else task.exception()
        if error is not None:
            log.error("hàng gửi clipboard tới %s dừng vì lỗi", sender.device_id[:8], exc_info=error)

    def _sent(self, device_id: str, clip: tuple[Clipboard, ...]) -> None:
        first = clip[0]
        kind = ClipKind(first.kind)
        log.debug("đã gửi clipboard %s tới %s, %d byte", first.kind, device_id[:8], first.total)
        self._emit(ClipboardEvent(ClipOutcome.SENT, device_id, kind, first.total, first.clip_id))

    # ---- Nhận ------------------------------------------------------------------------------

    def on_message(self, device_id: str, conn_id: int, msg: Clipboard) -> None:
        """Một mảnh `clipboard` tới trên kết nối điều khiển `conn_id` (đồng bộ)."""
        loop = self._loop
        if self._closed or loop is None:
            return
        link = self._links.get(device_id)
        if link is None or link[0] != conn_id:
            return  # mảnh của kết nối cũ (sau `LinkSwitched`)
        if not self._enabled(device_id) or self._paused():
            if self._assembler.reserved_bytes(device_id):
                self._assembler.discard(device_id)
            self._open_clip.pop(device_id, None)  # máy này bỏ, không phải máy kia bỏ dở
            return
        if self._over_budget.get(device_id) == msg.clip_id:
            return
        now = self._now()
        if msg.index == 0:
            # Mảnh 0 của clip mới khi clip trước của chính máy đó chưa ráp xong (đã nhận hay bị bỏ
            # vì lỗi, trừ khi bỏ vì trần RAM): máy đó đang bỏ dở.
            previous = self._open_clip.get(device_id)
            if previous is not None and previous != msg.clip_id:
                self._abandoned[device_id] = now
            self._open_clip[device_id] = msg.clip_id
            if not self._fits_budget(device_id, msg, now):
                if not self._abandoning(device_id, now):
                    # Máy này bỏ clip đó vì trần RAM: không tính là máy kia bỏ dở. Máy đang bỏ dở
                    # thì vẫn nhớ, để clip mới tiếp theo của nó lại tính là bỏ dở.
                    self._open_clip.pop(device_id, None)
                return
        events = self._assembler.feed(device_id, msg, now)
        self._schedule_tick()
        for event in events:
            if isinstance(event, ClipReady):
                if self._open_clip.get(device_id) == event.clip_id:
                    del self._open_clip[device_id]
                self._ready(event)
            else:
                self._note_abandon(event, now)
                self._log_drops((event,))

    def _now(self) -> float:
        """Đồng hồ của phần nhận (giờ loop); seam cho test."""
        assert self._loop is not None
        return self._loop.time()

    def _note_abandon(self, event: ClipDropped, now: float) -> None:
        """Clip dở bị chính thiết bị gửi bỏ (`REPLACED` bởi clip mới của nó, `EXPIRED`): nhớ mốc."""
        if event.reason in (DropReason.REPLACED, DropReason.EXPIRED):
            self._abandoned[event.device_id] = now

    def _abandoning(self, device_id: str, now: float) -> bool:
        last = self._abandoned.get(device_id)
        return last is not None and now - last < CLIP_ABANDON_WINDOW

    def _fits_budget(self, device_id: str, msg: Clipboard, now: float) -> bool:
        """Trần RAM chung ở mảnh `index 0` (docstring module, “Nhận”).

        Không vừa: thiết bị không đang bỏ dở thì đẩy ra clip dở của máy khác đang bỏ dở, đã đứng hay
        giữ chỗ lâu (thứ tự ở `_eviction_order`), nếu nhờ vậy vừa (đẩy vừa đủ); không thì bỏ cả clip
        đang ráp của thiết bị và nhớ clip này.
        """
        limit = MAX_CLIP_BYTES.get(msg.kind)
        if limit is None or msg.total > limit:
            return True  # assembler bỏ (`UNSUPPORTED_KIND` / `TOO_LARGE`), có trừ token
        assembler = self._assembler
        partials = assembler.partials()
        others = [p for p in partials if p.device_id != device_id]
        used = sum(p.total for p in others)
        if used + msg.total <= CLIP_RAM_BUDGET:
            return True
        replacing = any(p.device_id == device_id and p.clip_id != msg.clip_id for p in partials)
        if replacing or self._abandoning(device_id, now):
            evictable: list[PartialInfo] = []  # máy đang bỏ dở không được đẩy clip máy khác
        else:
            evictable = self._eviction_order(others, now)
        if evictable and used - sum(p.total for p in evictable) + msg.total <= CLIP_RAM_BUDGET:
            for p in evictable:
                if used + msg.total <= CLIP_RAM_BUDGET:
                    break
                assembler.discard(p.device_id)
                if not self._abandoning(p.device_id, now):
                    self._open_clip.pop(p.device_id, None)  # máy này bỏ, máy kia không bỏ dở
                used -= p.total
                self._log_budget_drop(p.device_id, p.total, now)
            self._schedule_tick()
            return True
        assembler.discard(device_id)
        self._over_budget[device_id] = msg.clip_id
        self._log_budget_drop(device_id, msg.total, now)
        self._schedule_tick()
        return False

    def _eviction_order(self, others: list[PartialInfo], now: float) -> list[PartialInfo]:
        """Clip dở của máy khác đẩy ra được, theo thứ tự đẩy: máy đang bỏ dở (cũ nhất trước), rồi đã
        đứng (đứng lâu nhất trước), rồi đã giữ chỗ quá `CLIP_HOLD_EVICT` (cũ nhất trước)."""
        ranked: list[tuple[int, float, PartialInfo]] = []
        for p in others:
            if self._abandoning(p.device_id, now):
                ranked.append((0, p.started_at, p))
            elif now - p.progress_at >= CLIP_STALL_EVICT:
                ranked.append((1, p.progress_at, p))
            elif now - p.started_at >= CLIP_HOLD_EVICT:
                ranked.append((2, p.started_at, p))
        ranked.sort(key=lambda r: (r[0], r[1]))
        return [p for _, _, p in ranked]

    def _log_budget_drop(self, device_id: str, size: int, now: float) -> None:
        log.debug("bỏ clipboard từ %s vì trần RAM chung, %d byte", device_id[:8], size)
        last = self._budget_logged.get(device_id)
        if last is None or now - last >= BUDGET_INFO_INTERVAL:
            self._budget_logged[device_id] = now
            log.info("bỏ clipboard từ %s vì đang ráp quá nhiều clip cùng lúc", device_id[:8])

    def _schedule_tick(self) -> None:
        loop = self._loop
        if loop is None or self._closed:
            return
        wake = self._assembler.next_wakeup()
        handle = self._tick_handle
        if handle is not None:
            if wake is not None and handle.when() == wake:
                return
            handle.cancel()
            self._tick_handle = None
        if wake is not None:
            self._tick_handle = loop.call_at(wake, self._tick)

    def _tick(self) -> None:
        self._tick_handle = None
        if self._closed or self._loop is None:
            return
        now = self._now()
        for event in self._assembler.tick(now):
            self._note_abandon(event, now)
            self._log_drops((event,))
        self._schedule_tick()

    @staticmethod
    def _log_drops(events: tuple[ClipDropped, ...]) -> None:
        for event in events:
            log.debug("bỏ clipboard %s từ %s: %s", event.kind[:64], event.device_id[:8], event.reason.value)

    def _ready(self, clip: ClipReady) -> None:
        if not self._enabled(clip.device_id) or self._paused():
            return
        self._generation += 1
        self._failed = None  # clip mới từ máy khác thay clip lỗi
        self._queue_write(_WriteJob(clip, self._generation))

    # ---- Ghi -------------------------------------------------------------------------------

    def _queue_write(self, job: _WriteJob) -> None:
        """Hàng ghi: 1 đang ghi + 1 chờ, mới thay chờ. Rảnh thì ghi ngay."""
        self._drop_pending_write()
        self._write_pending = job
        if self._op is None:
            self._start_next()

    def _drop_pending_write(self) -> None:
        pending = self._write_pending
        self._write_pending = None
        if pending is not None:
            pending.resolve(ClipOutcome.NOTHING_TO_RETRY)

    async def retry_write(self, device_id: str) -> ClipOutcome:
        """“Thử lại”: ghi lại clip ghi lỗi gần nhất nếu nó của `device_id`, qua hàng ghi.

        Trả `RECEIVED` / `WRITE_FAILED` (cũng phát sự kiện như lần ghi thường); không có clip của
        máy đó, đã tắt đồng bộ, bị clip mới thay trong hàng hay node đóng → `NOTHING_TO_RETRY`.
        Lần “Thử lại” trước của chính clip đó còn đang chờ hay đang ghi → chờ chung kết quả của
        lần đó (không ghi thêm). Bên gọi bị hủy không hủy lần ghi.
        """
        failed = self._failed
        if self._closed or self._loop is None or failed is None or failed.device_id != device_id:
            return ClipOutcome.NOTHING_TO_RETRY
        if not self._enabled(device_id):
            return ClipOutcome.NOTHING_TO_RETRY
        for job in (self._writing, self._write_pending):
            if job is not None and job.retry and job.clip is failed and job.future is not None:
                return await asyncio.shield(job.future)
        future: asyncio.Future[ClipOutcome] = self._loop.create_future()
        self._queue_write(_WriteJob(failed, self._generation, retry=True, future=future))
        return await asyncio.shield(future)

    async def _write(self, job: _WriteJob) -> None:
        clip = job.clip
        outcome = ClipOutcome.NOTHING_TO_RETRY
        try:
            if not self._wanted(job):
                return
            if clip.kind == ClipKind.TEXT:
                outcome = await self._write_text(job)
            else:
                outcome = await self._write_image(job)
        finally:
            job.resolve(outcome)

    def _wanted(self, job: _WriteJob) -> bool:
        """Còn ghi/báo clip này không: chưa đóng, còn bật đồng bộ, không tạm dừng (trừ “Thử lại”)."""
        device_id = job.clip.device_id
        return not self._closed and self._enabled(device_id) and (job.retry or not self._paused())

    async def _write_text(self, job: _WriteJob) -> ClipOutcome:
        clip = job.clip
        assert isinstance(clip.content, str)
        info = await self._offload(_text_info, clip.content)
        if info is None:
            return ClipOutcome.NOTHING_TO_RETRY
        fingerprint, size = info
        if not self._wanted(job):
            return ClipOutcome.NOTHING_TO_RETRY  # tắt/tạm dừng trong lúc tính fingerprint
        failed_fp = self._failed_fp is not None and self._failed_fp[1] == fingerprint
        if not job.retry and not failed_fp and self._guard.is_current(fingerprint):
            return ClipOutcome.NOTHING_TO_RETRY  # clipboard đã có đúng nội dung này
        before = self._guard.snapshot()
        self._guard.remote_written(fingerprint)  # trước khi ghi: `on_change` có thể tới ngay
        result = await self._backend_write(clip)
        if result is not None and result.status is WriteStatus.OK:
            self._guard.remote_written(fingerprint, *result.fingerprints)
            self._failed_fp = None
            if not self._wanted(job):
                return ClipOutcome.NOTHING_TO_RETRY
            return self._received(job, size, preview=clip.content[:PREVIEW_CHARS])
        # Clipboard có thể vẫn là nội dung cũ: trả tập về như trước để `on_change` thừa không gửi lại
        # nó; giữ cả `fingerprint` vì backend có thể đã ghi rồi mới báo lỗi/quá hạn (không chuyển tiếp).
        self._guard.restore(before | {fingerprint})
        self._failed_fp = (clip.device_id, fingerprint)
        return self._write_error(job, result, size)

    async def _write_image(self, job: _WriteJob) -> ClipOutcome:
        clip = job.clip
        size = len(clip.content)
        result = await self._backend_write(clip)
        if result is not None and result.status is WriteStatus.OK:
            self._guard.remote_written(*result.fingerprints)
            if not self._wanted(job):
                return ClipOutcome.NOTHING_TO_RETRY
            return self._received(job, size, image_size=result.image_size)
        return self._write_error(job, result, size)

    async def _backend_write(self, clip: ClipReady) -> ClipWrite | None:
        try:
            async with asyncio.timeout(CLIP_WRITE_TIMEOUT):
                return await self._backend.write(clip.kind, clip.content)
        except TimeoutError:
            log.warning("ghi clipboard quá %.0f s", CLIP_WRITE_TIMEOUT)
        except Exception as e:
            log.warning("không ghi được clipboard (%s)", type(e).__name__)
        return None

    def _received(
        self,
        job: _WriteJob,
        size: int,
        *,
        preview: str | None = None,
        image_size: tuple[int, int] | None = None,
    ) -> ClipOutcome:
        clip = job.clip
        if self._failed is clip:
            self._failed = None
        log.info("đã chép clipboard %s từ %s, %d byte", clip.kind.value, clip.device_id[:8], size)
        self._emit(
            ClipboardEvent(
                ClipOutcome.RECEIVED,
                clip.device_id,
                clip.kind,
                size,
                clip.clip_id,
                preview=preview,
                image_size=image_size,
            )
        )
        return ClipOutcome.RECEIVED

    def _write_error(self, job: _WriteJob, result: ClipWrite | None, size: int) -> ClipOutcome:
        clip = job.clip
        if not self._wanted(job):
            return ClipOutcome.NOTHING_TO_RETRY  # tắt/tạm dừng trong lúc ghi: không giữ, không báo
        if result is not None and result.status is WriteStatus.REJECTED:
            device = clip.device_id[:8]
            log.info("clipboard %s từ %s bị từ chối khi ghi, %d byte", clip.kind.value, device, size)
            if self._failed is clip:
                self._failed = None
            return ClipOutcome.NOTHING_TO_RETRY
        if result is not None:
            log.warning("không chép được clipboard từ %s (%s)", clip.device_id[:8], result.status.value)
        if job.generation == self._generation and self._enabled(clip.device_id):
            self._failed = clip
        elif self._failed is clip:
            self._failed = None
        self._emit(ClipboardEvent(ClipOutcome.WRITE_FAILED, clip.device_id, clip.kind, size, clip.clip_id))
        return ClipOutcome.WRITE_FAILED

    # ---- Thao tác backend tuần tự ------------------------------------------------------------

    def _start_op(self, coro: Coroutine[Any, Any, None], what: str) -> None:
        task = asyncio.create_task(coro, name=f"{_TASK_NAME}.{what}")
        self._op = task
        task.add_done_callback(self._op_done)

    def _start_next(self) -> None:
        """Rảnh: ghi clip chờ (ưu tiên), không thì đọc lại nếu clipboard đã đổi trong lúc bận."""
        if self._closed or self._op is not None:
            return
        job = self._write_pending
        if job is not None:
            self._write_pending = None
            self._writing = job  # đặt ngay (không chờ task chạy): `retry_write` gọi liền thấy được
            self._start_op(self._write(job), "write")
        elif self._dirty:
            self._dirty = False
            self._arm_debounce()

    def _op_done(self, task: asyncio.Task[None]) -> None:
        if self._op is task:
            self._op = None
            job, self._writing = self._writing, None
            if job is not None:
                job.resolve(ClipOutcome.NOTHING_TO_RETRY)  # task bị hủy trước khi chạy: không qua `finally`
        if not task.cancelled() and task.exception() is not None:
            log.error("lỗi khi đồng bộ clipboard", exc_info=task.exception())
        self._start_next()

    async def _offload(self, fn: Callable[..., _T], *args: Any) -> _T | None:
        """Chạy `fn` trong executor riêng; executor đã tắt (`close`) → None."""
        loop = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(self._executor, fn, *args)
        except RuntimeError:
            return None
        return await future

    def _emit(self, event: ClipboardEvent) -> None:
        if self._closed:
            return
        try:
            self._on_event(event)
        except Exception:
            log.exception("on_clipboard_event raise")


def _content_ok(kind: ClipKind, data: object) -> bool:
    if kind == ClipKind.TEXT:
        return isinstance(data, str)
    return kind == ClipKind.PNG and isinstance(data, bytes)


def _text_info(text: str) -> tuple[str, int]:
    """(fingerprint, số byte UTF-8) của văn bản đã ráp; chạy trong executor."""
    return text_fingerprint(text), len(text.encode("utf-8"))
