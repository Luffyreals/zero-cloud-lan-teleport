"""`teleport.app.clipboard` (P5-1): `ClipboardSync` không socket, theo spec-d5 mục 2.1–2.4, ca test #2 ở
mục 5 và **mục 9** (thắng các mục trước khi khác).

Viết từ đặc tả, không từ code. Mỗi test dựng `ClipboardSync` thật trên loop của test với:

- `ScriptBackend`: backend giả viết ngay ở đây theo `ClipboardBackend` (spec 2.2), để điều khiển từng
  bước (chặn đọc/ghi bằng `asyncio.Event`, đếm, ghi thứ tự thao tác, giả OS đổi `\\n` → `\\r\\n`).
  Sau mỗi lần ghi thành công nó gọi `on_change` như clipboard thật (`dataChanged` do chính lần ghi).
- `FakeConn`: kết nối điều khiển giả có `send` async (khóa FIFO như `Connection._send_lock`), chặn
  được giữa một khung và ghi lại lần gửi bị hủy giữa khung (= kết nối sống bị abort, spec 9.2 điểm 1).
- `LinkConn`: nối hai `ClipboardSync` với nhau, `send` chuyển message sang `on_message` của bên kia.

`FakeClipboard` (spec 2.2, trong `src`) có test riêng ở cuối file và được dùng ở test nhiều node.

Giả định về API (spec chưa nói đủ cụ thể, báo lại nếu lệch):
- Hằng `CLIP_DEBOUNCE`, `CLIP_READ_TIMEOUT`, `CLIP_WRITE_TIMEOUT`, `CLIP_RAM_BUDGET`, `uuid4` vá trên
  `teleport.app.clipboard` (đọc lúc dùng); `CLIP_RATE`, `CLIP_BURST` vá ở cả `core.clipboard` và
  `app.clipboard` trước khi dựng (9.3 điểm 12).
- `retry_write` ghi lại thành công trả `ClipOutcome.RECEIVED`.
- “`buffered_bytes == 0`” (ca #3) đọc qua `ClipAssembler` mà `ClipboardSync` giữ (tìm bằng thuộc tính).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import dataclasses
import hashlib
import logging
import os
import threading
import time
import uuid

import pytest
from support import wait_until

from teleport.app import clipboard as app_clip
from teleport.app.clipboard import (
    ClipboardEvent,
    ClipboardSync,
    ClipContent,
    ClipOutcome,
    ClipRead,
    ClipWrite,
    ReadStatus,
    WriteStatus,
)
from teleport.core import clipboard as core_clip
from teleport.core.clipboard import (
    MAX_TEXT_BYTES,
    PNG_FRAGMENT_BYTES,
    PNG_SIGNATURE,
    ClipAssembler,
    split_clip,
    text_fingerprint,
)
from teleport.core.messages import Cancel, Clipboard, ClipKind
from teleport.net.connection import ConnectionLostError

pytestmark = [
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]

MiB = 1024 * 1024
D1, D2, D3, D4 = "a1" * 16, "b2" * 16, "c3" * 16, "d4" * 16
DEBOUNCE = 0.02  # CLIP_DEBOUNCE trong test (thật: 0,15 s)
SETTLE = 0.25  # chờ “không có gì xảy ra thêm” (> 10 lần DEBOUNCE)


def new_id() -> str:
    return uuid.uuid4().hex


def text_msgs(text: str, clip_id: str | None = None) -> list[Clipboard]:
    return split_clip(clip_id or new_id(), ClipKind.TEXT, text)


def png_bytes(size: int, seed: int = 0) -> bytes:
    body = hashlib.sha256(str(seed).encode()).digest() * (size // 32 + 1)
    return PNG_SIGNATURE + body[: size - len(PNG_SIGNATURE)]


def png_msgs(png: bytes, clip_id: str | None = None) -> list[Clipboard]:
    return split_clip(clip_id or new_id(), ClipKind.PNG, png)


def image_fp(png: bytes) -> str:
    """Fingerprint ảnh của backend giả (backend thật tính theo pixel; ở đây chỉ cần ổn định)."""
    return "img-" + hashlib.sha256(png).hexdigest()


def assembler_of(sync: ClipboardSync) -> ClipAssembler:
    for name in dir(sync):
        with contextlib.suppress(Exception):
            value = getattr(sync, name)
            if isinstance(value, ClipAssembler):
                return value
    raise AssertionError("ClipboardSync không giữ ClipAssembler nào đọc được qua thuộc tính")


def index0(msgs) -> list:
    return [m for m in msgs if isinstance(m, Clipboard) and m.index == 0]


def clip_ids(msgs) -> list[str]:
    out: list[str] = []
    for m in msgs:
        if isinstance(m, Clipboard) and (not out or out[-1] != m.clip_id):
            out.append(m.clip_id)
    return out


def assemble_text(msgs) -> str:
    return "".join(m.data for m in msgs)


# --- Backend và kết nối giả ----------------------------------------------------------------------


class ScriptBackend:
    """`ClipboardBackend` giả, theo hợp đồng spec 2.2."""

    def __init__(self) -> None:
        self.on_change = None
        self.started = 0
        self.stopped = 0
        self.current: ClipRead = ClipRead(ReadStatus.EMPTY)
        self.reads = 0
        self.writes: list[tuple[str, object]] = []  # (kind, data) đã ghi xong
        self.write_calls = 0
        self.read_gate: asyncio.Event | None = None
        self.write_gate: asyncio.Event | None = None
        self.read_status: ReadStatus | None = None  # ép kết quả đọc (FAILED, TOO_LARGE…)
        self.write_status: WriteStatus = WriteStatus.OK
        self.transform = None  # str → str, giả OS đổi văn bản khi ghi
        self.image_size = (3, 2)
        self.echo = True  # gọi on_change sau khi ghi (như dataChanged)
        self.active = 0
        self.max_active = 0
        self.ops: list[str] = []
        self.read_cancelled = 0
        self.write_cancelled = 0
        self.late_results = 0

    # Hợp đồng
    def start(self, on_change) -> None:
        self.started += 1
        self.on_change = on_change

    def stop(self) -> None:
        self.stopped += 1

    async def read(self) -> ClipRead:
        self.reads += 1
        self._enter("read")
        try:
            if self.read_gate is not None:
                await self.read_gate.wait()
            if self.read_status is not None:
                return ClipRead(self.read_status, None, 0)
            return self.current
        except asyncio.CancelledError:
            self.read_cancelled += 1
            raise
        finally:
            self._exit("read")

    async def write(self, kind, data) -> ClipWrite:
        self.write_calls += 1
        self._enter("write")
        try:
            if self.write_gate is not None:
                await self.write_gate.wait()
            if self.write_status is not WriteStatus.OK:
                return ClipWrite(self.write_status)
            kind = ClipKind(kind)
            if kind == ClipKind.TEXT:
                stored = self.transform(data) if self.transform else data
                fp = text_fingerprint(stored)
                result = ClipWrite(WriteStatus.OK, (fp,), None)
                size = len(stored.encode("utf-8"))
            else:
                stored = data
                fp = image_fp(data)
                result = ClipWrite(WriteStatus.OK, (fp, fp), self.image_size)
                size = len(data)
            self.current = ClipRead(ReadStatus.OK, ClipContent(kind, stored, fp), size)
            self.writes.append((kind, stored))
        except asyncio.CancelledError:
            self.write_cancelled += 1
            raise
        finally:
            self._exit("write")
        if self.echo and self.on_change is not None:
            self.on_change()
        return result

    def _enter(self, op: str) -> None:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.ops.append(op + "+")

    def _exit(self, op: str) -> None:
        self.active -= 1
        self.ops.append(op + "-")

    # Giả người dùng máy này
    def copy_text(self, text: str, *, sensitive: bool = False) -> None:
        if sensitive:
            self.current = ClipRead(ReadStatus.SENSITIVE, None, 0)
        else:
            self.current = ClipRead(
                ReadStatus.OK, ClipContent(ClipKind.TEXT, text, text_fingerprint(text)), len(text.encode())
            )
        self.on_change()

    def copy_image(self, png: bytes) -> None:
        self.current = ClipRead(ReadStatus.OK, ClipContent(ClipKind.PNG, png, image_fp(png)), len(png))
        self.on_change()

    def texts(self) -> list[str]:
        return [d for k, d in self.writes if k == ClipKind.TEXT]


class FakeConn:
    """Kết nối điều khiển giả. `send` giữ khóa FIFO suốt một khung (như `Connection._send_lock`)."""

    def __init__(self, name: str = "conn") -> None:
        self.name = name
        self.sent: list = []  # message gửi xong
        self.started: list = []  # message đã bắt đầu ghi
        self.closed = False
        self.aborted = False
        self.cancelled_mid_send = 0
        self.fail: BaseException | None = None
        self.gate = asyncio.Event()
        self.gate.set()
        self._lock = asyncio.Lock()

    def hold(self) -> None:
        self.gate.clear()

    def release(self) -> None:
        self.gate.set()

    async def send(self, msg) -> None:
        if self.closed:
            raise ConnectionLostError("kết nối đã đóng")
        async with self._lock:
            if self.fail is not None:
                raise self.fail
            self.started.append(msg)
            try:
                await self.gate.wait()
            except asyncio.CancelledError:
                # Hủy giữa khung: `Connection` thật abort kết nối (connection.py, `_send_frame`).
                self.cancelled_mid_send += 1
                self.abort()
                raise
            self.sent.append(msg)

    def abort(self) -> None:
        self.aborted = True
        self.closed = True

    async def close(self) -> None:
        self.closed = True

    def clips(self) -> list[Clipboard]:
        return [m for m in self.sent if isinstance(m, Clipboard)]


class LinkConn:
    """`send` chuyển message tới `on_message(from_id, conn_id, msg)` của `ClipboardSync` bên kia."""

    def __init__(self, target: ClipboardSync, from_id: str, conn_id: int) -> None:
        self.target = target
        self.from_id = from_id
        self.conn_id = conn_id
        self.closed = False
        self.sent: list = []

    async def send(self, msg) -> None:
        if self.closed:
            raise ConnectionLostError("kết nối đã đóng")
        await asyncio.sleep(0)
        self.sent.append(msg)
        asyncio.get_running_loop().call_soon(self.target.on_message, self.from_id, self.conn_id, msg)

    def abort(self) -> None:
        self.closed = True

    async def close(self) -> None:
        self.closed = True


class Harness:
    def __init__(self, backend: ScriptBackend | None = None, label: str = "H", control_idle=None) -> None:
        self.label = label
        self.backend = backend or ScriptBackend()
        self.enabled_ids: set[str] = set()
        self.conn_ids: dict[str, int] = {}
        self.paused = False
        self.events: list[ClipboardEvent] = []
        self.sync = ClipboardSync(
            backend=self.backend,
            enabled=lambda d: d in self.enabled_ids,
            paused=lambda: self.paused,
            on_event=self.events.append,
            control_idle=control_idle,
        )

    def enable(self, device_id: str, on: bool = True) -> None:
        if on:
            self.enabled_ids.add(device_id)
        else:
            self.enabled_ids.discard(device_id)
        self.sync.set_enabled(device_id, on)

    def connect(self, device_id: str, conn, conn_id: int = 1, *, enable: bool = True) -> None:
        self.conn_ids[device_id] = conn_id
        self.sync.link_up(device_id, conn_id, conn)
        if enable:
            self.enable(device_id)

    def feed(self, device_id: str, msgs, conn_id: int | None = None) -> None:
        """Mảnh tới từ `device_id`; mặc định trên kết nối đã `connect` gần nhất của máy đó."""
        if conn_id is None:
            conn_id = self.conn_ids.get(device_id, 1)
        for m in msgs:
            self.sync.on_message(device_id, conn_id, m)

    def of(self, outcome: ClipOutcome) -> list[ClipboardEvent]:
        return [e for e in self.events if e.outcome == outcome]


@pytest.fixture
def fast_clip(monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", DEBOUNCE)


@pytest.fixture
def clip_const(monkeypatch):
    """`clip_const(name, value)`: vá hằng ở `core.clipboard` và (nếu có) ở `app.clipboard`."""

    def patch(name: str, value) -> None:
        monkeypatch.setattr(core_clip, name, value)
        if hasattr(app_clip, name):
            monkeypatch.setattr(app_clip, name, value)

    return patch


@pytest.fixture
async def make(fast_clip):
    """`make(backend=None)` → `Harness` đã `start()`; luôn `close()` khi test xong."""
    made: list[Harness] = []

    def build(
        backend: ScriptBackend | None = None, label: str = "H", *, start: bool = True, control_idle=None
    ) -> Harness:
        h = Harness(backend, label, control_idle)
        made.append(h)
        if start:
            h.sync.start()
        return h

    yield build
    for h in made:
        h.sync.close()
    await asyncio.sleep(0)


# --- Hằng, kiểu dữ liệu (2.1–2.3) ----------------------------------------------------------------


def test_constants_match_spec():
    assert app_clip.CLIP_DEBOUNCE == 0.15
    assert app_clip.CLIP_READ_TIMEOUT == 10
    assert app_clip.CLIP_WRITE_TIMEOUT == 10
    assert app_clip.CLIP_RAM_BUDGET == 24 * 1024 * 1024
    assert app_clip.PREVIEW_CHARS == 200
    assert callable(app_clip.uuid4)


def test_status_and_outcome_values_match_spec():
    assert {s.value for s in ReadStatus} == {"ok", "empty", "unsupported", "sensitive", "too_large", "failed"}
    assert {s.value for s in WriteStatus} == {"ok", "rejected", "failed"}
    assert {o.value for o in ClipOutcome} == {
        "sent",
        "received",
        "too_large",
        "write_failed",
        "nothing_to_retry",
    }


def test_content_fields_are_hidden_from_repr():
    """N9: `repr` của nội dung và sự kiện không lộ nội dung."""
    secret = "mat-khau-bi-mat-123"
    content = ClipContent(ClipKind.TEXT, secret, text_fingerprint(secret))
    assert secret not in repr(content)
    assert secret not in repr(ClipRead(ReadStatus.OK, content, len(secret)))
    png = png_bytes(64)
    assert repr(png) not in repr(ClipContent(ClipKind.PNG, png, "fp"))
    event = ClipboardEvent(ClipOutcome.RECEIVED, D1, ClipKind.TEXT, len(secret), new_id(), secret, None)
    assert secret not in repr(event)
    assert secret not in str(event)


def test_dataclasses_are_frozen():
    content = ClipContent(ClipKind.TEXT, "a", text_fingerprint("a"))
    for obj in (
        content,
        ClipRead(ReadStatus.EMPTY),
        ClipWrite(WriteStatus.FAILED),
        ClipboardEvent(ClipOutcome.SENT, D1, ClipKind.TEXT, 1),
    ):
        with pytest.raises(dataclasses.FrozenInstanceError):
            obj.__setattr__(dataclasses.fields(obj)[0].name, None)


def test_dataclass_defaults_match_spec():
    r = ClipRead(ReadStatus.EMPTY)
    assert (r.content, r.size) == (None, 0)
    w = ClipWrite(WriteStatus.FAILED)
    assert (w.fingerprints, w.image_size) == ((), None)
    e = ClipboardEvent(ClipOutcome.TOO_LARGE, None, ClipKind.TEXT, 5)
    assert (e.clip_id, e.preview, e.image_size) == (None, None, None)


def test_module_does_not_import_qt():
    """`app/clipboard.py` không import PySide6 (spec 2.1; luật tầng ở architecture §1)."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(app_clip))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    assert not [n for n in names if n.split(".")[0] == "PySide6" or n.startswith("teleport.ui")]


# --- Gửi (2.4 “Gửi”) -----------------------------------------------------------------------------


async def test_copy_is_sent_to_connected_enabled_device(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("xin chào")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa có SENT")
    msgs = conn.clips()
    assert len(index0(msgs)) == 1
    assert assemble_text(msgs) == "xin chào"
    (ev,) = h.of(ClipOutcome.SENT)
    assert ev.device_id == D1
    assert ev.kind == ClipKind.TEXT
    assert ev.clip_id == msgs[0].clip_id
    assert ev.preview is None


async def test_clip_id_comes_from_uuid4_seam(make, monkeypatch):
    fixed = uuid.UUID(int=0x1234)
    monkeypatch.setattr(app_clip, "uuid4", lambda: fixed)
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("abc")
    await wait_until(lambda: conn.clips(), 3, "chưa gửi")
    assert {m.clip_id for m in conn.clips()} == {fixed.hex}


async def test_text_is_normalized_on_the_wire(make):
    """Văn bản gửi đi là `normalize_text` (core): `\\r\\n` thành `\\n`."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("a\r\nb")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    assert assemble_text(conn.clips()) == "a\nb"


async def test_rapid_changes_are_coalesced_into_one_read(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    for i in range(5):
        h.backend.copy_text(f"lần {i}")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 1
    assert [assemble_text([m]) for m in conn.clips()] == ["lần 4"]


async def test_debounce_restarts_on_each_change(make, monkeypatch):
    """Báo mới đặt lại hẹn giờ: đổi liên tục nhanh hơn `CLIP_DEBOUNCE` thì chưa đọc."""
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", 0.5)
    h = make()
    h.connect(D1, FakeConn())
    start = time.monotonic()
    for i in range(6):
        h.backend.copy_text(f"x{i}")
        await asyncio.sleep(0.05)
    assert h.backend.reads == 0, "đọc trước khi hết gộp"
    await wait_until(lambda: h.backend.reads == 1, 3, "không đọc sau khi hết gộp")
    assert time.monotonic() - start >= 0.25 + 0.5 - 0.05


async def test_on_change_from_another_thread_is_handled(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.current = ClipRead(
        ReadStatus.OK, ClipContent(ClipKind.TEXT, "từ thread khác", text_fingerprint("từ thread khác")), 10
    )
    t = threading.Thread(target=h.backend.on_change)
    t.start()
    t.join()
    await wait_until(lambda: conn.clips(), 3, "on_change từ thread khác không được xử lý")
    assert assemble_text(conn.clips()) == "từ thread khác"


async def test_same_content_copied_again_is_not_resent(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("một lần")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    h.backend.copy_text("một lần")
    await asyncio.sleep(SETTLE)
    assert len(index0(conn.clips())) == 1


async def test_same_messages_go_to_every_target_and_sent_once_per_device(make):
    h = make()
    c1, c2, c3 = FakeConn("1"), FakeConn("2"), FakeConn("3")
    h.connect(D1, c1)
    h.connect(D2, c2, conn_id=2)
    h.connect(D3, c3, conn_id=3, enable=False)  # kết nối nhưng chưa bật → không phải máy đích
    h.backend.copy_text("cho mọi máy")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 2, 3, "chưa có SENT cho cả hai máy")
    await asyncio.sleep(SETTLE)
    assert c1.clips() == c2.clips()
    assert c3.clips() == []
    assert sorted(e.device_id for e in h.of(ClipOutcome.SENT)) == sorted([D1, D2])


async def test_image_is_sent(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    png = png_bytes(PNG_FRAGMENT_BYTES + 100)
    h.backend.copy_image(png)
    await wait_until(lambda: h.of(ClipOutcome.SENT), 5, "chưa gửi ảnh")
    msgs = conn.clips()
    assert [m.index for m in msgs] == [0, 1]
    assert b"".join(base64.b64decode(m.data) for m in msgs) == png
    assert h.of(ClipOutcome.SENT)[0].kind == ClipKind.PNG


# --- Ca #5, #3: không máy đích → không đọc ------------------------------------------------------


async def test_no_connected_device_means_no_read(make):
    h = make()
    h.enable(D1)  # bật nhưng chưa kết nối
    h.backend.copy_text("không ai nhận")
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 0
    assert h.events == []


async def test_connected_but_not_enabled_means_no_read(make):
    """Máy gửi tắt (ca #3): không gửi, không `read`."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn, enable=False)
    h.backend.copy_text("chưa bật")
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 0
    assert conn.sent == []


async def test_enabling_later_does_not_send_backlog(make):
    """Bật lại không gửi bù; kết nối nhận lúc còn tắt vẫn được nhớ (9.3 điểm 3) nên lần sao chép sau đi."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn, enable=False)
    h.backend.copy_text("sao chép lúc chưa bật")
    await asyncio.sleep(SETTLE)
    h.enable(D1)
    await asyncio.sleep(SETTLE)
    assert conn.sent == []
    assert h.backend.reads == 0
    h.backend.copy_text("sau khi bật")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "kết nối có từ lúc tắt phải dùng được khi bật")
    assert assemble_text(conn.clips()) == "sau khi bật"


async def test_link_down_removes_target(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.sync.link_down(D1, 1)
    h.backend.copy_text("đã mất kết nối")
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 0
    assert conn.sent == []


async def test_no_target_resets_loop_guard(make):
    """9.3 điểm 4: không có máy đích → `guard.reset()`: nội dung đã gửi, sao chép lại sau khi có máy
    đích trở lại, được gửi lại (không bị coi là “vừa ghi”/“đã gửi”)."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 1, 3, "chưa gửi X")
    h.enable(D1, False)
    h.backend.copy_text("X")  # không có máy đích: reset, không đọc
    await asyncio.sleep(SETTLE)
    reads = h.backend.reads
    h.enable(D1)
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 2, 3, "X không được gửi lại sau reset")
    assert h.backend.reads == reads + 1


async def test_target_lost_during_read_does_not_block_same_content_after_reconnect(make):
    """Máy đích mất kết nối trong lúc đang đọc: không gửi, và `LoopGuard` không ghi nhận nội dung đó,
    nên sao chép lại đúng nội dung ấy sau khi nối lại vẫn được gửi (như khi không có máy đích)."""
    h = make()
    first = FakeConn("cu")
    h.connect(D1, first)
    h.backend.read_gate = asyncio.Event()
    h.backend.copy_text("X")
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc clipboard")
    h.sync.link_down(D1, 1)
    h.backend.read_gate.set()
    await asyncio.sleep(SETTLE)
    assert first.sent == []
    assert h.of(ClipOutcome.SENT) == []
    h.backend.read_gate = None
    second = FakeConn("moi")
    h.connect(D1, second, conn_id=2)
    h.backend.copy_text("X")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "X không được gửi sau khi nối lại")
    assert assemble_text(second.clips()) == "X"


# --- Ca #4: nhạy cảm, quá trần, đọc lỗi ---------------------------------------------------------


async def test_sensitive_content_is_not_sent_and_emits_nothing(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("mat-khau", sensitive=True)
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    assert conn.sent == []
    assert h.events == []


async def test_sensitive_resets_guard_so_previous_content_is_sent_again(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 1, 3, "chưa gửi X")
    h.backend.copy_text("pw", sensitive=True)
    await wait_until(lambda: h.backend.reads == 2, 3, "chưa đọc lần 2")
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 2, 3, "X phải được gửi lại sau nội dung nhạy cảm")


@pytest.mark.parametrize("status", [ReadStatus.EMPTY, ReadStatus.UNSUPPORTED])
async def test_empty_or_unsupported_is_not_sent_and_resets_guard(make, status):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 1, 3, "chưa gửi X")
    h.backend.read_status = status
    h.backend.on_change()
    await wait_until(lambda: h.backend.reads == 2, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    assert len(index0(conn.clips())) == 1
    assert len(h.events) == 1
    h.backend.read_status = None
    h.backend.copy_text("X")
    await wait_until(lambda: len(h.of(ClipOutcome.SENT)) == 2, 3, "X phải được gửi lại sau reset")


async def test_read_too_large_emits_too_large_without_device(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.read_status = ReadStatus.TOO_LARGE
    h.backend.on_change()
    await wait_until(lambda: h.of(ClipOutcome.TOO_LARGE), 3, "chưa có TOO_LARGE")
    await asyncio.sleep(SETTLE)
    (ev,) = h.events
    assert ev.device_id is None
    assert conn.sent == []


async def test_text_over_limit_after_read_is_too_large(make):
    """Backend trả OK mà `split_clip` ném `ClipTooLarge` → coi như `TOO_LARGE`."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("a" * (MAX_TEXT_BYTES + 1))
    await wait_until(lambda: h.of(ClipOutcome.TOO_LARGE), 5, "chưa có TOO_LARGE")
    await asyncio.sleep(SETTLE)
    assert [e.device_id for e in h.events] == [None]
    assert conn.sent == []


async def test_text_exactly_at_limit_is_sent(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("a" * MAX_TEXT_BYTES)
    await wait_until(lambda: h.of(ClipOutcome.SENT), 10, "chưa gửi clip đúng trần")
    assert sum(len(m.data) for m in conn.clips()) == MAX_TEXT_BYTES
    assert not h.of(ClipOutcome.TOO_LARGE)


async def test_too_large_without_target_emits_nothing(make):
    h = make()
    h.backend.read_status = ReadStatus.TOO_LARGE
    h.backend.on_change()
    await asyncio.sleep(SETTLE)
    assert h.events == []
    assert h.backend.reads == 0


async def test_read_failed_only_logs_warning(make, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.read_status = ReadStatus.FAILED
    h.backend.on_change()
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    assert h.events == []
    assert conn.sent == []
    assert any(r.levelno == logging.WARNING and r.name.startswith("teleport") for r in caplog.records)


async def test_read_timeout_only_logs_and_next_change_still_works(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_READ_TIMEOUT", 0.1)
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.read_gate = asyncio.Event()  # đọc treo
    h.backend.copy_text("treo")
    await wait_until(lambda: h.backend.read_cancelled == 1, 3, "đọc quá hạn không bị hủy")
    assert h.events == []
    h.backend.read_gate = None
    h.backend.copy_text("sau khi treo")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "không gửi được sau lần đọc quá hạn")
    assert assemble_text(conn.clips()) == "sau khi treo"


# --- Hàng gửi `_ClipSender` (2.4, 9.2 điểm 1–3), ca #6 ----------------------------------------


async def test_new_clip_replaces_pending_and_cuts_clip_in_flight_after_current_fragment(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    big = png_bytes(3 * PNG_FRAGMENT_BYTES)  # 3 mảnh
    h.backend.copy_image(big)
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.backend.copy_text("B")
    await wait_until(lambda: h.backend.reads == 2, 3, "chưa đọc B")
    h.backend.copy_text("C")
    await wait_until(lambda: h.backend.reads == 3, 3, "chưa đọc C")
    await asyncio.sleep(SETTLE)  # B, C đã vào hàng
    conn.release()
    await wait_until(lambda: h.of(ClipOutcome.SENT), 5, "C chưa gửi xong")
    await asyncio.sleep(SETTLE)
    msgs = conn.clips()
    assert msgs[0].kind == "image/png" and msgs[0].index == 0
    assert [m.kind for m in msgs[1:]] == ["text"], "phần còn lại của ảnh và clip B không được gửi"
    assert msgs[1].data == "C"
    assert conn.cancelled_mid_send == 0 and not conn.aborted, "mảnh đang gửi phải được gửi xong"
    sent = h.of(ClipOutcome.SENT)
    assert [e.kind for e in sent] == [ClipKind.TEXT], "ảnh bị cắt không được báo SENT"


async def test_other_messages_interleave_between_clip_fragments(make):
    """`cancel` của lượt file không phải xếp sau mọi mảnh của clip: hàng gửi gửi từng mảnh một."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(4 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    cancel = Cancel(transfer_id=new_id(), reason="user")
    task = asyncio.create_task(conn.send(cancel))
    await asyncio.sleep(0)
    conn.release()
    await task
    await wait_until(lambda: h.of(ClipOutcome.SENT), 5, "ảnh chưa gửi xong")
    pos = conn.sent.index(cancel)
    assert pos <= 1, f"cancel phải đi ngay sau mảnh đang gửi, đang ở vị trí {pos}/{len(conn.sent)}"


async def test_set_enabled_false_does_not_abort_live_connection(make):
    """9.2 điểm 1: đóng hàng gửi khi tắt: mảnh đang gửi gửi xong, không hủy giữa khung."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.enable(D1, False)
    await asyncio.sleep(SETTLE)
    assert conn.cancelled_mid_send == 0 and not conn.aborted
    conn.release()
    await wait_until(lambda: len(conn.sent) == 1, 3, "mảnh đang gửi phải gửi xong")
    await asyncio.sleep(SETTLE)
    assert len(conn.sent) == 1, "không gửi thêm mảnh sau khi tắt"
    assert not conn.aborted
    assert not h.of(ClipOutcome.SENT)


async def test_close_does_not_abort_live_connection(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.sync.close()
    await asyncio.sleep(SETTLE)
    assert conn.cancelled_mid_send == 0 and not conn.aborted
    conn.release()
    await wait_until(lambda: len(conn.sent) == 1, 3, "mảnh đang gửi phải gửi xong")
    await asyncio.sleep(SETTLE)
    assert len(conn.sent) == 1
    assert h.events == [], "sau close() không phát sự kiện"


async def test_link_down_cancels_sending_on_dead_connection(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.sync.link_down(D1, 1)
    await wait_until(lambda: conn.cancelled_mid_send == 1, 3, "task gửi trên kết nối đã chết phải bị hủy")
    assert conn.sent == []
    assert not h.of(ClipOutcome.SENT)


async def test_link_switch_drops_clip_in_flight_and_does_not_resend(make):
    """9.2 điểm 2: `link_up` sang `conn_id` khác: đóng hàng cũ, bỏ clip đang gửi và chờ, không gửi lại."""
    h = make()
    old, new = FakeConn("cũ"), FakeConn("mới")
    h.connect(D1, old)
    old.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(old.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.backend.copy_text("đang chờ")
    await wait_until(lambda: h.backend.reads == 2, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    h.sync.link_up(D1, 2, new)
    await wait_until(lambda: old.cancelled_mid_send == 1, 3, "hàng trên kết nối cũ phải dừng")
    await asyncio.sleep(SETTLE)
    assert new.sent == [], "không gửi lại clip dở hay clip chờ trên kết nối mới"
    h.backend.copy_text("sau khi đổi")
    await wait_until(lambda: new.clips(), 3, "clip mới không đi trên kết nối mới")
    assert assemble_text(new.clips()) == "sau khi đổi"


async def test_connection_lost_error_stops_sender_quietly(make, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    h = make()
    conn = FakeConn()
    conn.fail = ConnectionLostError("mất")
    h.connect(D1, conn)
    h.backend.copy_text("X")
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    assert not h.of(ClipOutcome.SENT)
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    new = FakeConn("mới")
    h.sync.link_up(D1, 2, new)
    h.backend.copy_text("Y")
    await wait_until(lambda: new.clips(), 3, "kết nối mới không gửi được")


async def test_sender_rate_limit_keeps_only_latest_clip(make, clip_const):
    """9.2 điểm 3: bucket bên gửi `CLIP_RATE * 0.8`, `CLIP_BURST`; hết token thì clip sau thay clip trước
    ở chỗ chờ và được gửi khi có token."""
    clip_const("CLIP_RATE", 2.5)  # 2 clip/s bên gửi
    clip_const("CLIP_BURST", 2)
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    for i in range(2):
        h.backend.copy_text(f"c{i}")
        await wait_until(lambda i=i: len(index0(conn.clips())) == i + 1, 3, f"c{i} phải đi ngay (burst 2)")
    t_burst = time.monotonic()
    for i in range(2, 5):
        h.backend.copy_text(f"c{i}")
        await wait_until(lambda i=i: h.backend.reads == i + 1, 3, f"chưa đọc c{i}")
    await wait_until(lambda: len(index0(conn.clips())) == 3, 3, "clip mới nhất phải được gửi khi có token")
    assert time.monotonic() - t_burst >= 0.25, "clip thứ ba đi trước khi có token"
    await asyncio.sleep(0.8)
    assert [m.data for m in index0(conn.clips())] == ["c0", "c1", "c4"]


# --- Nhận (2.4 “Nhận”) --------------------------------------------------------------------------


async def test_received_text_is_written_and_reported_with_preview(make):
    h = make()
    h.connect(D1, FakeConn())
    msgs = text_msgs("xin chào\ndòng 2")
    h.feed(D1, msgs)
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 3, "chưa có RECEIVED")
    assert h.backend.texts() == ["xin chào\ndòng 2"]
    (ev,) = h.of(ClipOutcome.RECEIVED)
    assert ev.device_id == D1
    assert ev.kind == ClipKind.TEXT
    assert ev.clip_id == msgs[0].clip_id
    assert ev.preview == "xin chào\ndòng 2"
    assert ev.image_size is None
    assert ev.size == len("xin chào\ndòng 2".encode())


async def test_preview_is_at_most_200_code_points(make):
    h = make()
    h.connect(D1, FakeConn())
    text = "😀" * 150 + "a" * 300
    h.feed(D1, text_msgs(text))
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 3, "chưa có RECEIVED")
    preview = h.of(ClipOutcome.RECEIVED)[0].preview
    assert preview == text[: app_clip.PREVIEW_CHARS]


async def test_received_image_reports_size_without_preview(make):
    h = make()
    h.connect(D1, FakeConn())
    png = png_bytes(PNG_FRAGMENT_BYTES * 2 + 5)
    h.feed(D1, png_msgs(png))
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 5, "chưa có RECEIVED")
    assert h.backend.writes == [(ClipKind.PNG, png)]
    (ev,) = h.of(ClipOutcome.RECEIVED)
    assert ev.kind == ClipKind.PNG
    assert ev.preview is None
    assert ev.image_size == h.backend.image_size
    assert ev.size == len(png)


async def test_disabled_device_clip_is_dropped_before_assembly(make):
    """Ca #3 / Q12: máy nhận tắt → không ghi, `buffered_bytes == 0`; mảnh đầu không được ráp, nên bật
    lên giữa chừng cũng không ráp được phần còn lại."""
    h = make()
    h.connect(D1, FakeConn(), enable=False)
    msgs = text_msgs("x" * 1000 + "y" * 800_000)
    assert len(msgs) >= 2
    h.feed(D1, msgs[:1])
    assert assembler_of(h.sync).buffered_bytes() == 0
    assert assembler_of(h.sync).reserved_bytes() == 0
    h.enable(D1)
    h.feed(D1, msgs[1:])
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    assert h.events == []


async def test_paused_receiving_drops_clip(make):
    """Ca #4 / Q8: tạm dừng nhận → bỏ trước khi ráp."""
    h = make()
    h.connect(D1, FakeConn())
    h.paused = True
    msgs = text_msgs("x" * 900_000)
    h.feed(D1, msgs[:1])
    assert assembler_of(h.sync).buffered_bytes() == 0
    h.paused = False
    h.feed(D1, msgs[1:])
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    h.feed(D1, text_msgs("sau khi tiếp tục"))
    await wait_until(lambda: h.backend.texts() == ["sau khi tiếp tục"], 3, "không nhận lại sau khi tiếp tục")


async def test_fragments_from_other_conn_id_are_dropped(make):
    """9.2 điểm 2: bỏ mảnh có `conn_id` khác kết nối hiện tại."""
    h = make()
    h.connect(D1, FakeConn(), conn_id=5)
    h.feed(D1, text_msgs("kết nối cũ"), conn_id=4)
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    h.feed(D1, text_msgs("kết nối hiện tại"), conn_id=5)
    await wait_until(lambda: h.backend.texts() == ["kết nối hiện tại"], 3, "không nhận trên kết nối hiện tại")


async def test_fragments_without_link_up_are_dropped(make):
    h = make()
    h.enable(D1)
    h.feed(D1, text_msgs("chưa link_up"))
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0


async def test_received_clip_is_not_echoed_back(make):
    """Ca #1 (một tiến trình): ghi X, `on_change` do chính lần ghi (OS đổi `\\n` → `\\r\\n`) không gửi
    lại X cho máy gửi."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.transform = lambda t: t.replace("\n", "\r\n")
    h.feed(D1, text_msgs("dòng 1\ndòng 2"))
    await wait_until(lambda: h.backend.texts() == ["dòng 1\r\ndòng 2"], 3, "chưa ghi")
    await wait_until(lambda: h.backend.reads >= 1, 3, "on_change sau khi ghi phải dẫn tới một lần đọc")
    await asyncio.sleep(SETTLE)
    assert conn.sent == [], "clip vừa nhận bị gửi ngược lại"


async def test_os_truncated_text_is_not_echoed(make):
    """OS cắt ở NUL: fingerprint đọc lại sau khi ghi (`ClipWrite.fingerprints`) chặn vọng."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.transform = lambda t: t.split("\0", 1)[0]
    h.feed(D1, text_msgs("trước\0sau"))
    await wait_until(lambda: h.backend.texts() == ["trước"], 3, "chưa ghi")
    await wait_until(lambda: h.backend.reads >= 1, 3, "chưa đọc lại")
    await asyncio.sleep(SETTLE)
    assert conn.sent == []


async def test_received_clip_is_not_forwarded_to_third_device(make):
    """Không chuyển tiếp: clip từ D1 không đi sang D2 (LoopGuard)."""
    h = make()
    c1, c2 = FakeConn("1"), FakeConn("2")
    h.connect(D1, c1)
    h.connect(D2, c2, conn_id=2)
    h.feed(D1, text_msgs("từ D1"))
    await wait_until(lambda: h.backend.texts() == ["từ D1"], 3, "chưa ghi")
    await wait_until(lambda: h.backend.reads >= 1, 3, "chưa đọc lại")
    await asyncio.sleep(SETTLE)
    assert c1.sent == [] and c2.sent == []


async def test_clip_equal_to_current_content_is_not_written(make):
    """`guard.is_current(fp)` → không ghi (clip trùng nội dung vừa ghi)."""
    h = make()
    h.connect(D1, FakeConn())
    h.connect(D2, FakeConn(), conn_id=2)
    h.feed(D1, text_msgs("giống nhau"))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi")
    h.feed(D2, text_msgs("giống nhau"))
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 1
    assert len(h.of(ClipOutcome.RECEIVED)) == 1


async def test_clip_equal_to_local_copy_is_not_written(make):
    """Người dùng máy này vừa sao chép X (đã gửi), máy kia gửi đúng X → không ghi."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("X\n")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    h.feed(D1, text_msgs("X\r\n"))  # cùng nội dung sau chuẩn hóa
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0


async def test_text_fingerprint_not_wire_sha_is_used(make):
    """Bên gửi khác gửi văn bản chưa chuẩn hóa (`\\r\\n` trên dây, sha256 khớp byte đó): vẫn ráp, vẫn
    ghi, và lần đọc lại sau ghi không gửi ngược (hợp đồng `ClipReady`: dùng `text_fingerprint`)."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    raw = b"a\r\nb"
    msg = Clipboard(
        clip_id=new_id(),
        kind="text",
        sha256=hashlib.sha256(raw).hexdigest(),
        total=len(raw),
        index=0,
        count=1,
        data="a\r\nb",
    )
    h.feed(D1, [msg])
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi")
    await wait_until(lambda: h.backend.reads >= 1, 3, "chưa đọc lại")
    await asyncio.sleep(SETTLE)
    assert conn.sent == []


async def test_write_rejected_only_logs_info(make, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.REJECTED
    h.feed(D1, png_msgs(png_bytes(100)))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi")
    await asyncio.sleep(SETTLE)
    assert h.events == []
    assert any(r.levelno == logging.INFO and r.name.startswith("teleport") for r in caplog.records)
    assert await h.sync.retry_write(D1) == ClipOutcome.NOTHING_TO_RETRY, "REJECTED không giữ để thử lại"


# --- Hàng ghi và tuần tự hóa backend (2.4 bước 2, 4; 9.2 điểm 5) --------------------------------


async def test_write_queue_keeps_one_pending_newest_wins(make, clip_const):
    clip_const("CLIP_RATE", 100.0)
    clip_const("CLIP_BURST", 100)
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_gate = asyncio.Event()
    h.feed(D1, text_msgs("c1"))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi c1")
    for t in ("c2", "c3", "c4"):
        h.feed(D1, text_msgs(t))
    await asyncio.sleep(SETTLE)
    h.backend.write_gate.set()
    await wait_until(lambda: len(h.backend.texts()) >= 2, 3, "clip chờ chưa được ghi")
    await asyncio.sleep(SETTLE)
    assert h.backend.texts() == ["c1", "c4"]


async def test_backend_runs_one_operation_at_a_time(make):
    """9.2 điểm 5: ghi chờ đọc đang chạy."""
    h = make()
    h.connect(D1, FakeConn())
    h.backend.read_gate = asyncio.Event()
    h.backend.copy_text("đang đọc")
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    h.feed(D1, text_msgs("tới lúc đang đọc"))
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0, "ghi bắt đầu khi đọc chưa xong"
    h.backend.read_gate.set()
    await wait_until(lambda: h.backend.texts() == ["tới lúc đang đọc"], 3, "ghi không chạy sau khi đọc xong")
    assert h.backend.max_active == 1


async def test_change_during_write_is_read_after_write(make):
    """2.4 bước 2: đang ghi → chỉ đánh dấu “bẩn”, đọc sau khi ghi xong."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.write_gate = asyncio.Event()
    h.backend.echo = False
    h.feed(D1, text_msgs("đang ghi"))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi")
    h.backend.on_change()
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 0, "đọc trong lúc đang ghi"
    h.backend.write_gate.set()
    await wait_until(lambda: h.backend.reads == 1, 3, "không đọc lại sau khi ghi xong")
    assert h.backend.ops.index("read+") > h.backend.ops.index("write-")
    await asyncio.sleep(SETTLE)
    assert conn.sent == [], "lần đọc do chính lần ghi gây ra không được gửi"
    assert h.backend.max_active == 1


# --- Ghi lỗi và “Thử lại” (ca #9) ---------------------------------------------------------------


async def test_write_failed_emits_event_and_retry_writes_again(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    msgs = text_msgs("chép lại giúp")
    h.feed(D1, msgs)
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    (ev,) = h.of(ClipOutcome.WRITE_FAILED)
    assert ev.device_id == D1
    assert ev.kind == ClipKind.TEXT
    assert ev.clip_id == msgs[0].clip_id
    h.backend.write_status = WriteStatus.OK
    assert await asyncio.wait_for(h.sync.retry_write(D1), 5) == ClipOutcome.RECEIVED
    assert h.backend.texts() == ["chép lại giúp"]


async def test_write_timeout_counts_as_failed(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_WRITE_TIMEOUT", 0.1)
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_gate = asyncio.Event()  # ghi treo
    h.feed(D1, text_msgs("treo"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "ghi quá hạn phải thành WRITE_FAILED")
    h.backend.write_gate = None
    assert await asyncio.wait_for(h.sync.retry_write(D1), 5) == ClipOutcome.RECEIVED
    assert h.backend.texts() == ["treo"]


async def test_retry_for_other_device_or_without_failure_is_nothing_to_retry(make):
    h = make()
    h.connect(D1, FakeConn())
    h.connect(D2, FakeConn(), conn_id=2)
    assert await h.sync.retry_write(D1) == ClipOutcome.NOTHING_TO_RETRY
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("lỗi"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    assert await h.sync.retry_write(D2) == ClipOutcome.NOTHING_TO_RETRY


async def test_text_write_failure_restores_guard(make):
    """Ghi văn bản lỗi → `LoopGuard` về tập trước lần ghi **cộng** fingerprint của clip đó (soát vòng 2:
    backend có thể đã ghi xong rồi mới báo lỗi/quá hạn): X không bị gửi đi như nội dung của người dùng
    máy này; nội dung khác vẫn gửi bình thường."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("X"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.backend.copy_text("X")
    await asyncio.sleep(SETTLE)
    assert not h.of(ClipOutcome.SENT), "X (clip nhận từ máy khác) không được gửi tiếp"
    h.backend.copy_text("Y")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "nội dung mới của người dùng phải được gửi")


@pytest.mark.parametrize("how", ["new_clip_other_device", "disable", "forget", "local_copy", "close"])
async def test_failed_clip_is_forgotten(make, how):
    h = make()
    h.connect(D1, FakeConn())
    h.connect(D2, FakeConn(), conn_id=2)
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("lỗi"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    if how == "new_clip_other_device":
        h.feed(D2, text_msgs("mới"))
        await wait_until(lambda: h.backend.texts() == ["mới"], 3, "chưa ghi clip mới")
    elif how == "disable":
        h.enable(D1, False)
    elif how == "forget":
        h.sync.forget_device(D1)
    elif how == "local_copy":
        h.backend.copy_text("người dùng sao chép")
        await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    else:
        h.sync.close()
    n = len(h.events)
    assert await asyncio.wait_for(h.sync.retry_write(D1), 5) == ClipOutcome.NOTHING_TO_RETRY
    assert "lỗi" not in h.backend.texts()
    if how == "close":
        assert len(h.events) == n, "sau close() không phát sự kiện"


async def test_pause_does_not_forget_failed_clip(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("giữ khi tạm dừng"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.paused = True
    await asyncio.sleep(SETTLE)
    h.paused = False
    assert await asyncio.wait_for(h.sync.retry_write(D1), 5) == ClipOutcome.RECEIVED
    assert h.backend.texts() == ["giữ khi tạm dừng"]


async def test_retry_goes_through_write_queue(make):
    """9.2 điểm 5: `retry_write` không chạy song song với lần đọc đang chạy."""
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("thử lại"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.backend.read_gate = asyncio.Event()
    h.backend.on_change()
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    task = asyncio.create_task(h.sync.retry_write(D1))
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 1, "ghi lại chạy khi đọc chưa xong"
    h.backend.read_gate.set()
    assert await asyncio.wait_for(task, 5) == ClipOutcome.RECEIVED
    assert h.backend.max_active == 1


# --- Ca #7: link_down, đổi kết nối, hủy ghép đôi ------------------------------------------------


async def test_link_down_drops_clip_being_assembled(make):
    h = make()
    h.connect(D1, FakeConn())
    msgs = text_msgs("x" * 900_000)
    assert len(msgs) >= 2
    h.feed(D1, msgs[:1])
    assert assembler_of(h.sync).buffered_bytes(D1) > 0
    h.sync.link_down(D1, 1)
    assert assembler_of(h.sync).buffered_bytes(D1) == 0
    h.sync.link_up(D1, 2, FakeConn())
    h.feed(D1, msgs[1:], conn_id=2)
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    h.feed(D1, text_msgs("đủ"), conn_id=2)
    await wait_until(lambda: h.backend.texts() == ["đủ"], 3, "clip mới sau khi nối lại không được nhận")


async def test_link_switched_drops_clip_being_assembled(make):
    """9.1 điểm 4, 9.2 điểm 2: `link_up` sang `conn_id` khác cũng bỏ clip đang ráp."""
    h = make()
    h.connect(D1, FakeConn())
    msgs = text_msgs("y" * 900_000)
    h.feed(D1, msgs[:1])
    h.sync.link_up(D1, 2, FakeConn())
    assert assembler_of(h.sync).buffered_bytes(D1) == 0
    h.feed(D1, msgs[1:], conn_id=2)  # phần còn lại trên kết nối mới
    h.feed(D1, msgs[1:], conn_id=1)  # hoặc trên kết nối cũ
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0


async def test_forget_device_clears_everything(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    msgs = text_msgs("z" * 900_000)
    h.feed(D1, msgs[:1])
    h.enabled_ids.discard(D1)  # Node: store.get(id) là None sau unpair
    h.sync.forget_device(D1)
    assert assembler_of(h.sync).buffered_bytes(D1) == 0
    assert assembler_of(h.sync).reserved_bytes(D1) == 0
    h.feed(D1, msgs[1:])
    h.backend.copy_text("sau khi hủy ghép đôi")
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    assert h.backend.reads == 0
    assert conn.sent == []


# --- Ca #8: trần RAM chung (2.4 “Nhận” bước 2, 9.2 điểm 4) ----------------------------------


async def test_ram_budget_is_shared_by_four_devices(make):
    """24 MiB chung: D1, D2 giữ 10 MiB mỗi máy; D3 xin 4 MiB + 1 → bỏ; đúng 4 MiB → nhận (biên);
    D4 thêm 2 byte lúc đầy → bỏ; khi D3 xong, D4 gửi lại được; D1 ráp xong vẫn đúng."""
    h = make()
    for i, d in enumerate((D1, D2, D3, D4), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    budget = app_clip.CLIP_RAM_BUDGET
    big1 = png_msgs(png_bytes(10 * MiB, 1))
    big2 = png_msgs(png_bytes(10 * MiB, 2))
    over = png_msgs(png_bytes(budget - 20 * MiB + 1, 3))
    exact = png_msgs(png_bytes(budget - 20 * MiB, 4))
    h.feed(D1, big1[:1], 1)
    h.feed(D2, big2[:1], 2)
    assert assembler_of(h.sync).reserved_bytes() == 20 * MiB
    h.feed(D3, over, 3)  # cả clip: mảnh 0 bị bỏ, mảnh sau cũng bị bỏ
    assert assembler_of(h.sync).reserved_bytes() == 20 * MiB
    h.feed(D3, exact[:1], 3)
    assert assembler_of(h.sync).reserved_bytes() == budget
    small = text_msgs("hi")
    h.feed(D4, small, 4)
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0
    h.feed(D3, exact[1:], 3)
    await wait_until(lambda: h.backend.write_calls == 1, 5, "clip đúng biên trần phải được nhận")
    h.feed(D4, text_msgs("hi lần hai"), 4)
    await wait_until(lambda: "hi lần hai" in h.backend.texts(), 5, "D4 phải nhận được khi còn chỗ")
    h.feed(D1, big1[1:], 1)
    await wait_until(lambda: h.backend.write_calls == 3, 10, "D1 ráp xong phải được ghi")
    written = [d for _, d in h.backend.writes]
    assert png_bytes(budget - 20 * MiB + 1, 3) not in written
    assert "hi" not in written


async def test_ram_budget_excludes_own_clip_being_replaced(make):
    """`reserved() - reserved(id) + total`: clip mới thay clip cũ của chính máy đó không bị tính hai lần."""
    h = make()
    h.connect(D1, FakeConn(), conn_id=1)
    h.connect(D2, FakeConn(), conn_id=2)
    h.feed(D1, png_msgs(png_bytes(10 * MiB, 1))[:1], 1)
    h.feed(D2, png_msgs(png_bytes(10 * MiB, 2))[:1], 2)
    replacement = png_msgs(png_bytes(10 * MiB, 3))
    h.feed(D1, replacement, 1)
    await wait_until(lambda: h.backend.write_calls == 1, 10, "clip thay thế phải được nhận")
    assert h.backend.writes[0][1] == png_bytes(10 * MiB, 3)


async def test_ram_budget_drop_discards_device_clip_in_progress(make):
    """9.2 điểm 4: bỏ vì quá trần → bỏ luôn clip đang ráp của thiết bị đó."""
    h = make()
    h.connect(D1, FakeConn(), conn_id=1)
    h.connect(D2, FakeConn(), conn_id=2)
    h.connect(D3, FakeConn(), conn_id=3)
    h.feed(D1, png_msgs(png_bytes(10 * MiB, 1))[:1], 1)
    h.feed(D2, png_msgs(png_bytes(10 * MiB, 2))[:1], 2)
    partial = text_msgs("p" * 900_000)
    h.feed(D3, partial[:1], 3)
    h.feed(D3, png_msgs(png_bytes(10 * MiB, 3))[:1], 3)  # 20 + 10 > 24 → bỏ
    assert assembler_of(h.sync).reserved_bytes(D3) == 0
    h.feed(D3, partial[1:], 3)
    await asyncio.sleep(SETTLE)
    assert h.backend.write_calls == 0


async def test_ram_budget_read_at_use_time(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_RAM_BUDGET", 1000)
    h = make()
    h.connect(D1, FakeConn())
    h.feed(D1, text_msgs("a" * 1001))
    h.feed(D1, text_msgs("b" * 1000))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "clip đúng trần phải được nhận")
    await asyncio.sleep(SETTLE)
    assert h.backend.texts() == ["b" * 1000]


async def test_ram_budget_info_log_at_most_once_per_device_per_minute(make, monkeypatch, caplog):
    monkeypatch.setattr(app_clip, "CLIP_RAM_BUDGET", 100)
    caplog.set_level(logging.DEBUG, logger="teleport")
    h = make()
    h.connect(D1, FakeConn())
    for i in range(4):
        h.feed(D1, text_msgs(f"{i}" * 200))
    infos = [r for r in caplog.records if r.levelno == logging.INFO and r.name.startswith("teleport")]
    assert len(infos) <= 1, [r.getMessage() for r in infos]


# --- Ca #10: close() --------------------------------------------------------------------------


async def test_close_does_not_wait_for_hung_backend_read(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.read_gate = asyncio.Event()  # treo mãi
    h.backend.copy_text("treo")
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    start = time.monotonic()
    result = h.sync.close()
    assert result is None or not asyncio.iscoroutine(result), "close() phải đồng bộ"
    assert time.monotonic() - start < 0.5
    assert h.backend.stopped == 1
    await wait_until(lambda: h.backend.read_cancelled == 1, 3, "task chờ đọc phải bị hủy")
    assert h.events == []


async def test_close_does_not_wait_for_hung_backend_write(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_gate = asyncio.Event()
    h.feed(D1, text_msgs("ghi treo"))
    await wait_until(lambda: h.backend.write_calls == 1, 3, "chưa ghi")
    start = time.monotonic()
    h.sync.close()
    assert time.monotonic() - start < 0.5
    await wait_until(lambda: h.backend.write_cancelled == 1, 3, "task chờ ghi phải bị hủy")
    assert h.events == []


async def test_after_close_changes_and_messages_are_ignored(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.sync.close()
    h.backend.copy_text("sau close")
    h.feed(D1, text_msgs("tới sau close"))
    await asyncio.sleep(SETTLE)
    assert h.backend.reads == 0
    assert h.backend.write_calls == 0
    assert conn.sent == []
    assert h.events == []
    h.sync.close()  # gọi lại không lỗi


def test_on_change_after_loop_closed_does_not_raise(monkeypatch):
    """9.3 điểm 6: `on_change` nuốt `RuntimeError` khi loop đã đóng (backend Qt gọi từ thread khác)."""
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", DEBOUNCE)
    backend = ScriptBackend()
    loop = asyncio.new_event_loop()
    holder: list[Harness] = []

    async def setup() -> None:
        h = Harness(backend)
        h.sync.start()
        holder.append(h)

    try:
        loop.run_until_complete(setup())
    finally:
        loop.close()
    assert backend.on_change is not None
    backend.on_change()  # loop đã đóng: không ném
    t = threading.Thread(target=backend.on_change)
    t.start()
    t.join()
    with contextlib.suppress(RuntimeError):
        holder[0].sync.close()


async def test_start_registers_on_change_and_close_stops_backend(make):
    h = make(start=False)
    assert h.backend.started == 0
    h.sync.start()
    assert h.backend.started == 1
    assert callable(h.backend.on_change)
    h.sync.close()
    assert h.backend.stopped == 1


# --- Hai `ClipboardSync` nối với nhau (ca #1, #2 không socket) ----------------------------------


async def test_two_syncs_round_trip_without_echo(make):
    a = make(label="A")
    b = make(label="B")
    b.backend.transform = lambda t: t.replace("\n", "\r\n")
    a.connect(D2, LinkConn(b.sync, D1, 1))
    b.connect(D1, LinkConn(a.sync, D2, 1))
    a.backend.copy_text("một\nhai")
    await wait_until(lambda: b.backend.texts() == ["một\r\nhai"], 3, "B chưa ghi")
    # Mốc: B sao chép Y; mọi tiếng vọng X từ B (nếu có) phải tới A trước Y.
    await wait_until(lambda: b.backend.reads >= 1, 3, "B chưa đọc lại sau khi ghi")
    b.backend.copy_text("Y")
    await wait_until(lambda: a.backend.texts() == ["Y"], 3, "A chưa nhận Y")
    assert a.backend.write_calls == 1, "A nhận lại X (vọng)"
    assert len(a.of(ClipOutcome.SENT)) == 1
    assert len(b.of(ClipOutcome.SENT)) == 1


async def test_three_syncs_each_change_written_once_per_machine(make):
    ids = {"A": D1, "B": D2, "C": D3}
    hs = {k: make(label=k) for k in ids}
    for x, hx in hs.items():
        for y, hy in hs.items():
            if x != y:
                hx.connect(ids[y], LinkConn(hy.sync, ids[x], 1))
    order = [("A", "X"), ("B", "Y"), ("C", "Z")]
    for who, text in order:
        hs[who].backend.copy_text(text)
        for other in hs:
            if other != who:
                await wait_until(
                    lambda other=other, text=text: text in hs[other].backend.texts(),
                    3,
                    f"{other} chưa có {text}",
                )
    # Mốc: mỗi máy sao chép một nội dung mới lần lượt, chờ hai máy kia nhận.
    for who in hs:
        hs[who].backend.copy_text("mốc " + who)
        for other in hs:
            if other != who:
                await wait_until(
                    lambda other=other, who=who: "mốc " + who in hs[other].backend.texts(), 3, "mốc chưa tới"
                )
    for who, text in order:
        for name, h in hs.items():
            count = h.backend.texts().count(text)
            assert count == (0 if name == who else 1), f"{name} ghi {text} {count} lần"
    for name, h in hs.items():
        sent = [e for e in h.of(ClipOutcome.SENT)]
        assert len(sent) == 4, f"{name} gửi {len(sent)} lần (đúng: 2 clip × 2 máy)"


# --- N9 (ca #11) ------------------------------------------------------------------------------


async def test_logs_never_contain_clip_content_or_full_device_id(make, caplog, monkeypatch):
    caplog.set_level(logging.DEBUG)
    monkeypatch.setattr(app_clip, "CLIP_RAM_BUDGET", 3000)
    secret = "BI-MAT-" + os.urandom(6).hex()
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.connect(D2, FakeConn(), conn_id=2)
    # Gửi, nhạy cảm, quá trần, đọc lỗi.
    h.backend.copy_text(secret + " gửi")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    h.backend.copy_text(secret + " nhạy cảm", sensitive=True)
    await wait_until(lambda: h.backend.reads == 2, 3, "chưa đọc")
    h.backend.copy_text(secret * 200000)
    await wait_until(lambda: h.of(ClipOutcome.TOO_LARGE), 5, "chưa TOO_LARGE")
    # Nhận, ghi lỗi, thử lại, bị từ chối, quá trần RAM.
    h.feed(D1, text_msgs(secret + " nhận"))
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 3, "chưa nhận")
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D2, text_msgs(secret + " lỗi ghi"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    await h.sync.retry_write(D2)
    h.backend.write_status = WriteStatus.REJECTED
    h.feed(D1, png_msgs(PNG_SIGNATURE + secret.encode()))
    await asyncio.sleep(SETTLE)
    h.feed(D2, text_msgs(secret * 1000))  # quá trần RAM 3000
    h.backend.read_status = ReadStatus.FAILED
    h.backend.on_change()
    await asyncio.sleep(SETTLE)
    assert caplog.records, "không có log nào: không kiểm được N9"
    for r in caplog.records:
        text = r.getMessage() + (r.exc_text or "")
        assert "BI-MAT" not in text, f"log lộ nội dung: {r.name} {text[:120]!r}"
        if r.name.startswith("teleport.app.clipboard"):
            assert D1 not in text and D2 not in text, f"log có device_id đầy đủ: {text[:120]!r}"
    for e in h.events:
        assert "BI-MAT" not in repr(e)


# --- FakeClipboard (2.2) --------------------------------------------------------------------------


async def test_fake_clipboard_set_text_notifies_and_reads_back():
    fake = app_clip.FakeClipboard()
    calls: list[int] = []
    fake.start(lambda: calls.append(1))
    fake.set_text("xin chào")
    assert calls == [1]
    r = await fake.read()
    assert r.status == ReadStatus.OK
    assert r.content.kind == ClipKind.TEXT
    assert r.content.data == "xin chào"
    assert r.content.fingerprint == text_fingerprint("xin chào")
    fake.stop()


async def test_fake_clipboard_sensitive_and_image():
    fake = app_clip.FakeClipboard()
    fake.start(lambda: None)
    fake.set_text("pw", sensitive=True)
    assert (await fake.read()).status == ReadStatus.SENSITIVE
    png = png_bytes(100)
    fake.set_image(png, "fp-anh")
    r = await fake.read()
    assert r.status == ReadStatus.OK
    assert (r.content.kind, r.content.data, r.content.fingerprint) == (ClipKind.PNG, png, "fp-anh")
    fake.stop()


async def test_fake_clipboard_write_applies_transform_and_records():
    fake = app_clip.FakeClipboard()
    fake.start(lambda: None)
    fake.transform = lambda t: t.replace("\n", "\r\n")
    before = time.monotonic()
    w = await fake.write(ClipKind.TEXT, "a\nb")
    assert w.status == WriteStatus.OK
    assert text_fingerprint("a\r\nb") in w.fingerprints
    assert len(fake.writes) == 1
    at, content = fake.writes[0]
    assert before <= at <= time.monotonic()
    assert content.data == "a\r\nb"
    r = await fake.read()
    assert r.content.data == "a\r\nb"
    fake.stop()


async def test_fake_clipboard_failures():
    fake = app_clip.FakeClipboard()
    fake.start(lambda: None)
    fake.set_text("x")
    fake.fail_read = True
    assert (await fake.read()).status == ReadStatus.FAILED
    fake.fail_write = True
    assert (await fake.write(ClipKind.TEXT, "y")).status == WriteStatus.FAILED
    assert fake.writes == []
    fake.stop()


# --- Sửa sau soat-code / tan-cong (P5-1) ----------------------------------------------------------


def parts_text(text: str, count: int) -> list[Clipboard]:
    """Clip văn bản ASCII chia đúng `count` mảnh (bên gửi thật chỉ chia khi > ~767 KB)."""
    raw = text.encode("ascii")
    step = -(-len(text) // count)
    pieces = [text[i : i + step] for i in range(0, len(text), step)]
    assert len(pieces) == count
    clip_id = new_id()
    digest = hashlib.sha256(raw).hexdigest()
    return [
        Clipboard(clip_id=clip_id, kind="text", sha256=digest, total=len(raw), index=i, count=count, data=p)
        for i, p in enumerate(pieces)
    ]


@pytest.fixture
def evict(monkeypatch):
    """`evict(stall, hold, budget=1000)`: vá `CLIP_STALL_EVICT`, `CLIP_HOLD_EVICT`, `CLIP_RAM_BUDGET`."""

    def patch(stall: float, hold: float, budget: int = 1000) -> None:
        monkeypatch.setattr(app_clip, "CLIP_STALL_EVICT", stall)
        monkeypatch.setattr(app_clip, "CLIP_HOLD_EVICT", hold)
        monkeypatch.setattr(app_clip, "CLIP_RAM_BUDGET", budget)

    return patch


def test_new_constants_have_expected_values():
    assert app_clip.CLIP_STALL_EVICT == 1.0
    assert app_clip.CLIP_HOLD_EVICT == 3.0
    assert app_clip.CLIP_YIELD_TIMEOUT == 2.0
    assert app_clip.CLIP_CLOSE_WAIT == 1.0


async def test_ram_budget_evicts_stalled_clips_of_other_devices_oldest_first(make, evict):
    """A3 (tan-cong): hai máy giữ mỗi máy một clip dở lớn không tiến triển; clip của máy thứ ba
    không còn bị bỏ mãi: clip dở đứng cũ nhất bị đẩy ra, vừa đủ chỗ."""
    evict(stall=0.1, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    hold1, hold2 = parts_text("a" * 400, 4), parts_text("b" * 400, 4)
    h.feed(D1, hold1[:2], 1)
    await asyncio.sleep(0.02)
    h.feed(D2, hold2[:2], 2)
    await asyncio.sleep(0.3)  # cả hai đứng > CLIP_STALL_EVICT
    honest = parts_text("c" * 500, 2)  # 400 + 400 + 500 > 1000; bỏ D1 thì 900 ≤ 1000
    h.feed(D3, honest, 3)
    await wait_until(lambda: h.backend.texts() == ["c" * 500], 3, "clip của máy thật phải được nhận")
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D1) == 0, "clip đứng cũ nhất bị đẩy ra"
    assert asm.reserved_bytes(D2) == 400, "chỉ đẩy vừa đủ chỗ"
    h.feed(D1, hold1[2:], 1)  # phần còn lại của clip bị đẩy: bỏ im lặng
    await asyncio.sleep(SETTLE)
    assert h.backend.texts() == ["c" * 500]


async def test_ram_budget_does_not_evict_clips_that_progress(make, evict):
    evict(stall=0.2, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    hold1, hold2 = parts_text("a" * 400, 4), parts_text("b" * 400, 4)
    h.feed(D1, hold1[:1], 1)
    h.feed(D2, hold2[:1], 2)
    await asyncio.sleep(0.3)
    h.feed(D1, hold1[1:2], 1)  # cả hai vừa có mảnh mới
    h.feed(D2, hold2[1:2], 2)
    h.feed(D3, parts_text("c" * 500, 2), 3)
    await asyncio.sleep(SETTLE)
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D1) == 400 and asm.reserved_bytes(D2) == 400
    assert h.backend.write_calls == 0, "không có clip dở nào đứng: clip mới bị bỏ như cũ"


async def test_ram_budget_evicts_nothing_unless_that_makes_room(make, evict):
    evict(stall=0.1, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    stalled, fresh = parts_text("a" * 300, 3), parts_text("b" * 400, 4)
    h.feed(D1, stalled[:1], 1)
    await asyncio.sleep(0.3)
    h.feed(D2, fresh[:1], 2)
    h.feed(D3, parts_text("c" * 700, 2), 3)  # bỏ D1 vẫn 400 + 700 > 1000
    await asyncio.sleep(SETTLE)
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D1) == 300, "không đẩy clip ra khi đẩy rồi vẫn không vừa"
    assert asm.reserved_bytes(D3) == 0
    assert h.backend.write_calls == 0


async def test_ram_budget_evicts_clip_held_too_long_even_if_progressing(make, evict):
    evict(stall=100, hold=0.2)
    h = make()
    h.connect(D1, FakeConn("a"), conn_id=1)
    h.connect(D2, FakeConn("b"), conn_id=2)
    slow = parts_text("a" * 900, 9)
    h.feed(D1, slow[:1], 1)
    for i in range(1, 4):
        await asyncio.sleep(0.1)
        h.feed(D1, slow[i : i + 1], 1)  # vẫn tiến triển, nhưng đã giữ chỗ > CLIP_HOLD_EVICT
    h.feed(D2, parts_text("b" * 200, 2), 2)
    await wait_until(lambda: h.backend.texts() == ["b" * 200], 3, "clip mới phải được nhận")
    assert assembler_of(h.sync).reserved_bytes(D1) == 0


async def test_failed_text_write_then_spurious_change_does_not_resend_old_content(make):
    """Soát code: ghi lỗi không được làm mất fingerprint nội dung cũ L; `dataChanged` thừa sau đó không
    gửi lại L (L sẽ đè X của máy kia)."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("L")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "L chưa gửi")
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("X"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.on_change()  # dataChanged thừa: clipboard vẫn là L
    await asyncio.sleep(SETTLE)
    assert [m.data for m in index0(conn.clips())] == ["L"], "L bị gửi lại"


async def test_retry_write_twice_in_a_row_writes_once(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("một lần thôi"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.backend.write_gate = asyncio.Event()
    calls = h.backend.write_calls
    both = asyncio.gather(h.sync.retry_write(D1), h.sync.retry_write(D1))
    await wait_until(lambda: h.backend.write_calls == calls + 1, 3, "chưa ghi lại")
    third = asyncio.create_task(h.sync.retry_write(D1))  # bấm lần ba khi đang ghi
    await asyncio.sleep(SETTLE)
    h.backend.write_gate.set()
    assert await asyncio.wait_for(both, 5) == [ClipOutcome.RECEIVED, ClipOutcome.RECEIVED]
    assert await asyncio.wait_for(third, 5) == ClipOutcome.RECEIVED
    assert h.backend.write_calls == calls + 1
    assert h.backend.texts() == ["một lần thôi"]
    assert len(h.of(ClipOutcome.RECEIVED)) == 1


async def test_cancelled_retry_caller_does_not_cancel_the_write(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("vẫn ghi"))
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.backend.write_gate = asyncio.Event()
    first = asyncio.create_task(h.sync.retry_write(D1))
    await wait_until(lambda: h.backend.active == 1, 3, "chưa ghi lại")
    first.cancel()
    second = asyncio.create_task(h.sync.retry_write(D1))
    await asyncio.sleep(0.05)
    h.backend.write_gate.set()
    assert await asyncio.wait_for(second, 5) == ClipOutcome.RECEIVED
    assert h.backend.texts() == ["vẫn ghi"]
    with contextlib.suppress(asyncio.CancelledError):
        await first


@pytest.mark.parametrize("how", ["disable", "forget", "pause"])
async def test_change_during_write_suppresses_result(make, how):
    """Tắt đồng bộ, hủy ghép đôi hay tạm dừng nhận trong lúc đang ghi: không báo `RECEIVED`."""
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_gate = asyncio.Event()
    h.feed(D1, text_msgs("đang ghi"))
    await wait_until(lambda: h.backend.active == 1, 3, "chưa bắt đầu ghi")
    if how == "disable":
        h.enable(D1, False)
    elif how == "forget":
        h.enabled_ids.discard(D1)
        h.sync.forget_device(D1)
    else:
        h.paused = True
    h.backend.write_gate.set()
    await asyncio.sleep(SETTLE)
    assert not h.of(ClipOutcome.RECEIVED)
    assert not h.of(ClipOutcome.WRITE_FAILED)


async def test_disable_during_failed_write_keeps_nothing_to_retry(make):
    h = make()
    h.connect(D1, FakeConn())
    h.backend.write_status = WriteStatus.FAILED
    h.backend.write_gate = asyncio.Event()
    h.feed(D1, text_msgs("lỗi khi đã tắt"))
    await wait_until(lambda: h.backend.active == 1, 3, "chưa bắt đầu ghi")
    h.enable(D1, False)
    h.backend.write_gate.set()
    await asyncio.sleep(SETTLE)
    assert not h.of(ClipOutcome.WRITE_FAILED)
    h.enable(D1)
    assert await h.sync.retry_write(D1) == ClipOutcome.NOTHING_TO_RETRY


async def test_clip_fragments_yield_to_transfer_control_queue(make, monkeypatch):
    """A5 (tan-cong): trước mỗi mảnh clip, chờ hàng gửi điều khiển của truyền file trống; `cancel`
    xếp sau tối đa một mảnh clip (mảnh đang gửi dở)."""
    monkeypatch.setattr(app_clip, "CLIP_YIELD_TIMEOUT", 30.0)
    idle = asyncio.Event()
    idle.set()
    asked: list[tuple[str, int]] = []

    def control_idle(device_id: str, conn_id: int) -> asyncio.Event:
        asked.append((device_id, conn_id))
        return idle

    h = make(control_idle=control_idle)
    conn = FakeConn()
    h.connect(D1, conn, conn_id=7)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    idle.clear()  # truyền file vừa xếp `cancel` vào hàng của nó
    cancel = Cancel(transfer_id=new_id(), reason="user")
    task = asyncio.create_task(conn.send(cancel))
    await asyncio.sleep(0)
    conn.release()
    await asyncio.wait_for(task, 3)
    await asyncio.sleep(SETTLE)
    assert [type(m).__name__ for m in conn.sent] == ["Clipboard", "Cancel"], "mảnh sau phải chờ hàng trống"
    idle.set()
    await wait_until(lambda: h.of(ClipOutcome.SENT), 5, "ảnh chưa gửi xong")
    assert len(conn.clips()) == 3
    assert asked and set(asked) == {(D1, 7)}


async def test_first_fragment_also_waits_for_transfer_queue(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_YIELD_TIMEOUT", 30.0)
    idle = asyncio.Event()
    h = make(control_idle=lambda d, c: idle)
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("chờ lượt")
    await wait_until(lambda: h.backend.reads == 1, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    assert conn.started == []
    idle.set()
    await wait_until(lambda: conn.clips(), 3, "clip phải đi khi hàng trống")


async def test_yield_is_bounded_so_clip_is_not_starved(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_YIELD_TIMEOUT", 0.05)
    idle = asyncio.Event()  # hàng truyền file không bao giờ trống
    h = make(control_idle=lambda d, c: idle)
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_image(png_bytes(2 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "clip phải đi sau hạn nhường")
    assert len(conn.clips()) == 2


async def test_no_transfer_queue_means_no_waiting(make, monkeypatch):
    monkeypatch.setattr(app_clip, "CLIP_YIELD_TIMEOUT", 30.0)
    h = make(control_idle=lambda d, c: None)
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("không có hàng")
    await wait_until(lambda: conn.clips(), 3, "clip phải đi ngay")


async def test_close_stops_sending_before_next_fragment_and_drain_waits_for_current(make):
    """A6 (tan-cong): sau `close()` không gửi thêm mảnh nào; `drain` chờ mảnh đang gửi dở xong."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.sync.close()
    drain = asyncio.create_task(h.sync.drain(5))
    await asyncio.sleep(0.1)
    assert not drain.done(), "drain phải chờ mảnh đang gửi"
    conn.release()
    await asyncio.wait_for(drain, 3)
    assert len(conn.sent) == 1 and not conn.aborted


async def test_drain_is_bounded_and_abort_cancels_the_rest(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    h.sync.close()
    start = time.monotonic()
    await h.sync.drain(0.1)
    assert time.monotonic() - start < 1
    h.sync.abort()
    await wait_until(lambda: conn.cancelled_mid_send == 1, 3, "abort phải hủy mảnh còn treo")


async def test_close_cancels_idle_sender_at_once(make):
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    h.backend.copy_text("xong")
    await wait_until(lambda: h.of(ClipOutcome.SENT), 3, "chưa gửi")
    h.sync.close()
    start = time.monotonic()
    await h.sync.drain(5)
    assert time.monotonic() - start < 0.5, "task gửi đang rảnh phải dừng ngay khi close()"


async def test_abort_also_cancels_sender_replaced_while_closing(make):
    """tan-cong (nghi ngờ): tắt rồi bật lại khi máy kia không đọc để lại hàng cũ đang đóng; `abort()`
    phải hủy cả nó."""
    h = make()
    conn = FakeConn()
    h.connect(D1, conn)
    conn.hold()  # máy kia không đọc
    h.backend.copy_image(png_bytes(3 * PNG_FRAGMENT_BYTES))
    await wait_until(lambda: len(conn.started) == 1, 5, "mảnh đầu chưa bắt đầu gửi")
    for i in range(3):
        h.enable(D1, False)
        h.enable(D1, True)
        h.backend.copy_text(f"mới {i}")
        await wait_until(lambda i=i: h.backend.reads == i + 2, 3, "chưa đọc")
    await asyncio.sleep(SETTLE)
    h.sync.abort()
    await wait_until(lambda: conn.cancelled_mid_send == 1, 3, "mảnh đang treo của hàng cũ phải bị hủy")
    await asyncio.sleep(0)
    left = [
        t for t in asyncio.all_tasks() if t.get_name().startswith("teleport.clipboard.send") and not t.done()
    ]
    assert left == [], left


# --- Ảnh vọng: backend trả ảnh OK với data rỗng (hợp đồng `ClipboardBackend`) ---------------------


class EchoImageClipboard(app_clip.FakeClipboard):
    """Như backend Qt: đọc lại đúng ảnh vừa ghi → `ClipContent(PNG, b"", fp)` (không mã hóa lại PNG)."""

    def __init__(self) -> None:
        super().__init__()
        self.written_fp: str | None = None

    async def write(self, kind, data) -> ClipWrite:
        result = await super().write(kind, data)
        if result.status is WriteStatus.OK and kind == ClipKind.PNG:
            self.written_fp = result.fingerprints[0]
        return result

    async def read(self) -> ClipRead:
        result = await super().read()
        c = result.content
        echo = c is not None and c.kind == ClipKind.PNG and c.fingerprint == self.written_fp
        if result.status is ReadStatus.OK and c is not None and echo:
            return ClipRead(ReadStatus.OK, ClipContent(ClipKind.PNG, b"", c.fingerprint), 0)
        return result

    def poke(self) -> None:
        """`dataChanged` thừa."""
        self._changed()


def ihdr_png(width: int = 4, height: int = 3, size: int = 2 * PNG_FRAGMENT_BYTES) -> bytes:
    head = PNG_SIGNATURE + b"\0\0\0\rIHDR" + width.to_bytes(4, "big") + height.to_bytes(4, "big")
    return head + bytes(size - len(head))


async def test_echoed_image_with_empty_data_is_not_sent_nor_warned(make, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    fake = EchoImageClipboard()
    h = make(fake)
    conn = FakeConn()
    h.connect(D1, conn)
    h.feed(D1, png_msgs(ihdr_png()))
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 5, "ảnh chưa được ghi")
    await wait_until(lambda: fake.reads >= 1, 3, "chưa đọc lại sau khi ghi")
    await asyncio.sleep(SETTLE)
    assert conn.sent == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


async def test_echoed_image_after_guard_reset_is_still_not_sent(make, caplog):
    """Guard đã bị `reset()` (không có máy đích lúc clipboard đổi): ảnh vọng vẫn không được gửi và
    được ghi nhận là nội dung hiện tại; không dựa vào `split_clip(b"")` ném lỗi."""
    caplog.set_level(logging.DEBUG, logger="teleport")
    fake = EchoImageClipboard()
    h = make(fake)
    h.connect(D1, FakeConn())
    h.feed(D1, png_msgs(ihdr_png()))
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 5, "ảnh chưa được ghi")
    await asyncio.sleep(SETTLE)
    h.sync.link_down(D1, 1)
    fake.poke()  # không có máy đích: không đọc, guard.reset()
    await asyncio.sleep(SETTLE)
    reads = fake.reads
    conn = FakeConn("mới")
    h.connect(D1, conn, conn_id=2)
    fake.poke()
    await wait_until(lambda: fake.reads == reads + 1, 3, "chưa đọc ảnh vọng")
    await asyncio.sleep(SETTLE)
    assert conn.sent == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
    fake.poke()  # lần nữa: vẫn không gửi
    await asyncio.sleep(SETTLE)
    assert conn.sent == []
    fake.set_text("người dùng sao chép")
    await wait_until(lambda: conn.clips(), 3, "nội dung người dùng tự sao chép vẫn phải đi")


# --- Luật phạt “bỏ dở” cho trần RAM chung (A3 đầy đủ) ----------------------------------------------

D5, D6 = "e5" * 16, "f6" * 16


def declared_png(total: int = 10 * MiB, count: int = 20) -> Clipboard:
    """Mảnh 0 khai `total` lớn mà gửi ít byte (máy tấn công giữ chỗ trần RAM rẻ)."""
    return Clipboard(
        clip_id=new_id(), kind="image/png", sha256="0" * 64, total=total, index=0, count=count, data="AAAA"
    )


class FakeClock:
    def __init__(self) -> None:
        self.t = 0.0


@pytest.fixture
async def clock(monkeypatch):
    """Đồng hồ giả của phần nhận (`ClipboardSync._now`), đặt xa phía trước giờ loop để hẹn `tick`
    không bao giờ chạy trong test."""
    c = FakeClock()
    c.t = asyncio.get_running_loop().time() + 1000.0
    monkeypatch.setattr(app_clip.ClipboardSync, "_now", lambda self: c.t)
    return c


def test_abandon_constants_have_expected_values():
    assert app_clip.CLIP_ABANDON_WINDOW == 10.0
    assert app_clip.CLIP_HOLD_EVICT == 3.0


async def test_a3_holders_and_hammers_do_not_starve_honest_device(make, clock):
    """A3 (tan-cong) đầy đủ với đồng hồ giả: D1, D2 giữ mỗi máy một clip 10 MiB dở (mảnh mới mỗi 0,5 s,
    mở clip mới mỗi 10 s); D3–D5 dội mảnh 0 của clip 10 MiB mỗi 0,05 s; máy thật D6 gửi ảnh 5 MiB mỗi
    4 s. Ảnh của D6 được nhận, trừ đúng một lần: máy giữ chỗ bị đẩy ra (lúc chưa bỏ dở) thì clip mới
    kế tiếp của nó không bị tính là bỏ dở (soát vòng 2), nên lần mở clip mới ở t = 10 s trông như máy
    gửi thật và giữ chỗ tới khi quá `CLIP_HOLD_EVICT`; ảnh của D6 ở t = 12 s bị bỏ. Từ t = 20 s máy giữ
    chỗ lại bị tính là bỏ dở. Không clip nào của máy tấn công được ghi."""
    h = make()
    devices = (D1, D2, D3, D4, D5, D6)
    for i, d in enumerate(devices, start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    start = clock.t
    holders: dict[str, tuple[Clipboard, int]] = {}
    honest_sent = 0
    missed: list[float] = []
    for step in range(int(41 / 0.05)):
        t = round(step * 0.05, 2)
        clock.t = start + t
        for d in (D1, D2):
            if t % 10 == 0:
                first = declared_png()
                holders[d] = (first, 1)
                h.feed(d, [first], devices.index(d) + 1)
            elif round(t * 2) == t * 2:  # mỗi 0,5 s một mảnh mới
                first, i = holders[d]
                if i < first.count - 1:
                    h.feed(d, [dataclasses.replace(first, index=i)], devices.index(d) + 1)
                    holders[d] = (first, i + 1)
        for d in (D3, D4, D5):
            h.feed(d, [declared_png()], devices.index(d) + 1)
        if t >= 4 and t % 4 == 0:
            honest_sent += 1
            h.feed(D6, png_msgs(png_bytes(5 * MiB, honest_sent)), 6)
            expected = honest_sent - len(missed)
            try:
                await wait_until(lambda n=expected: h.backend.write_calls == n, 1)
            except AssertionError:
                missed.append(t)
    assert honest_sent == 10
    assert missed == [12.0], f"ảnh của máy thật bị bỏ lúc t = {missed}"
    assert all(len(data) == 5 * MiB for _, data in h.backend.writes)


async def test_abandoning_device_cannot_evict_other_devices(make, evict):
    evict(stall=0.1, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    stalled = parts_text("a" * 600, 3)
    h.feed(D1, stalled[:1], 1)
    await asyncio.sleep(0.3)  # D1 đứng
    h.feed(D2, parts_text("b" * 300, 3)[:1], 2)
    h.feed(D2, parts_text("c" * 500, 2), 2)  # thay clip dở của chính nó: đang bỏ dở, không được đẩy D1
    await asyncio.sleep(SETTLE)
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D1) == 600
    assert h.backend.write_calls == 0
    h.feed(D3, parts_text("d" * 500, 2), 3)  # máy không bỏ dở thì đẩy được D1
    await wait_until(lambda: h.backend.texts() == ["d" * 500], 3, "D3 phải được nhận")
    assert asm.reserved_bytes(D1) == 0


async def test_abandoning_device_is_evicted_before_stalled_one(make, evict):
    evict(stall=0.1, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    h.feed(D1, parts_text("a" * 400, 4)[:1], 1)
    await asyncio.sleep(0.3)  # D1 đứng
    h.feed(D2, parts_text("b" * 300, 3)[:1], 2)
    h.feed(D2, parts_text("c" * 400, 4)[:1], 2)  # D2 bỏ dở clip trước; clip mới vẫn vừa trần
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D2) == 400
    h.feed(D3, parts_text("d" * 500, 2), 3)  # 800 + 500 > 1000: đẩy một clip
    await wait_until(lambda: h.backend.texts() == ["d" * 500], 3, "D3 phải được nhận")
    assert asm.reserved_bytes(D2) == 0, "máy đang bỏ dở bị đẩy trước"
    assert asm.reserved_bytes(D1) == 400


async def test_expired_clip_marks_device_as_abandoning(make, evict, clock):
    evict(stall=100, hold=100)
    h = make()
    for i, d in enumerate((D1, D2, D3), start=1):
        h.connect(d, FakeConn(d[:2]), conn_id=i)
    t0 = clock.t
    h.feed(D1, [declared_png(total=600, count=3)], 1)
    clock.t = t0 + core_clip.CLIP_ASSEMBLY_TIMEOUT + 1
    h.feed(D1, [declared_png(total=600, count=3)], 1)  # clip trước hết hạn → D1 đang bỏ dở
    h.feed(D2, [declared_png(total=300, count=3)], 2)
    h.feed(D3, parts_text("d" * 400, 2), 3)  # 900 + 400 > 1000: đẩy D1 (bỏ dở), dù chưa đứng
    await wait_until(lambda: h.backend.texts() == ["d" * 400], 3, "D3 phải được nhận")
    asm = assembler_of(h.sync)
    assert asm.reserved_bytes(D1) == 0
    assert asm.reserved_bytes(D2) == 300


# --- Soát vòng 2: ghi xong rồi mới báo lỗi; đẩy ra vì trần không tính là bỏ dở -------------------


class LateFailBackend(ScriptBackend):
    """Ghi vào clipboard, báo `on_change`, rồi treo tới khi quá `CLIP_WRITE_TIMEOUT` (lỗi muộn)."""

    async def write(self, kind, data) -> ClipWrite:
        self.write_calls += 1
        stored = data
        self.current = ClipRead(
            ReadStatus.OK, ClipContent(ClipKind.TEXT, stored, text_fingerprint(stored)), len(stored)
        )
        self.writes.append((ClipKind(kind), stored))
        if self.on_change is not None:
            self.on_change()
        await asyncio.Event().wait()  # treo: `ClipboardSync` hủy khi quá hạn
        raise AssertionError("không tới được")


async def test_write_that_lands_then_times_out_is_not_forwarded(make, monkeypatch):
    """Soát vòng 2: backend đã chép clip vào clipboard rồi mới quá hạn; clip đó không được gửi tiếp
    cho máy khác (trước khi sửa: ['write_failed', 'sent', 'sent'])."""
    monkeypatch.setattr(app_clip, "CLIP_WRITE_TIMEOUT", 0.1)
    h = make(LateFailBackend())
    c1, c2 = FakeConn("1"), FakeConn("2")
    h.connect(D1, c1, conn_id=1)
    h.connect(D2, c2, conn_id=2)
    h.feed(D1, text_msgs("từ máy 1"), 1)
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    await wait_until(lambda: h.backend.reads >= 1, 3, "chưa đọc lại sau lần ghi")
    await asyncio.sleep(SETTLE)
    assert [e.outcome for e in h.events] == [ClipOutcome.WRITE_FAILED]
    assert c1.clips() == [] and c2.clips() == []


async def test_device_evicted_for_budget_is_not_marked_abandoning(make, evict):
    """Soát vòng 2: máy bị máy này đẩy clip ra vì trần, rồi mở clip mới, không bị coi là bỏ dở: clip mới
    của nó vẫn đẩy được clip đã đứng của máy khác."""
    evict(stall=0.1, hold=100, budget=1_500_000)
    h = make()
    h.connect(D1, FakeConn("a"), conn_id=1)  # A
    h.connect(D2, FakeConn("b"), conn_id=2)  # B
    asm = assembler_of(h.sync)
    h.feed(D2, [declared_png(total=1_000_000)], 2)
    await asyncio.sleep(0.3)  # B đứng
    h.feed(D1, [declared_png(total=1_000_000)], 1)  # A đẩy B ra
    assert asm.reserved_bytes(D2) == 0 and asm.reserved_bytes(D1) == 1_000_000
    await asyncio.sleep(0.3)  # A đứng
    h.feed(D2, [declared_png(total=1_000_000)], 2)  # B mở clip mới: không bỏ dở nên đẩy được A
    assert asm.reserved_bytes(D2) == 1_000_000, "B bị coi là bỏ dở"
    assert asm.reserved_bytes(D1) == 0


async def test_same_text_sent_again_after_failed_write_is_written(make):
    """Ghi X lỗi; máy kia gửi lại đúng X → X được ghi (fingerprint của lần ghi lỗi không chặn ghi), và
    không có `SENT` chuyển tiếp X đi."""
    h = make()
    c1, c2 = FakeConn("1"), FakeConn("2")
    h.connect(D1, c1, conn_id=1)
    h.connect(D2, c2, conn_id=2)
    h.backend.write_status = WriteStatus.FAILED
    h.feed(D1, text_msgs("X"), 1)
    await wait_until(lambda: h.of(ClipOutcome.WRITE_FAILED), 3, "chưa có WRITE_FAILED")
    h.backend.write_status = WriteStatus.OK
    h.feed(D1, text_msgs("X"), 1)
    await wait_until(lambda: h.of(ClipOutcome.RECEIVED), 3, "X gửi lại phải được ghi")
    assert h.backend.texts() == ["X"]
    await asyncio.sleep(SETTLE)
    assert not h.of(ClipOutcome.SENT)
    assert c1.clips() == [] and c2.clips() == []
    h.feed(D2, text_msgs("X"), 2)  # đã ghi thành công: lần sau đúng là “clipboard đã có X”
    await asyncio.sleep(SETTLE)
    assert h.backend.texts() == ["X"]
