"""Test `teleport.app.transfers` (`TransferManager`) và phần truyền file của `Node` (P2-6b).

Viết theo đặc tả, không theo code: `specs/plan-p2-6.md` mục 2.6–2.10, 3, 5 (6b, AC-1…AC-34) và
`specs/spec-p2-6.md` mục B, D (spec thắng kế hoạch khi khác). Quy ước: hai node thật trên
127.0.0.1 (fixture `transfer_nodes`), **A nhận, B gửi**; “hai chiều” = kết nối điều khiển do B mở
(`client="sender"`) và do A mở (`client="receiver"`); kết nối dữ liệu đi theo chiều đó (protocol §4.1).

Hằng thời gian rút ngắn bằng `fast` (RECONNECT_GRACE 4 s, DATA_OPEN_WAIT 2 s, DATA_RETRY 0,2–1 s,
IDLE_TIMEOUT 5 s); `transfer_nodes` đặt `DRAIN_TIMEOUT` 10 s. File lớn dùng byte ngẫu nhiên tạo trong
`tmp_path`. Chờ bằng `wait_until` có hạn rộng; test đếm dùng spy trên các seam công khai
(spec-p2-6 B12). `teleport.app.transfers` chỉ được import trong fixture `T`: module chưa có thì
từng test đỏ, không làm hỏng cả lần chạy.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import dataclasses
import errno
import hashlib
import inspect
import itertools
import logging
import os
import shutil
import threading
import time
import unicodedata
from enum import StrEnum
from pathlib import Path
from types import SimpleNamespace

import pytest
from support import wait_until

from teleport.app import node as node_mod
from teleport.app import sources, storage
from teleport.app.node import DeviceConnected, DeviceDisconnected, MdnsOptions
from teleport.core import links as core_links
from teleport.core import ratelimit
from teleport.core import resume_state as rs
from teleport.core import transfer as core_transfer
from teleport.core.discovery import DeviceAdded, DeviceRemoved
from teleport.core.messages import Cancel, DataOpen, FileEntry
from teleport.net import connection

pytestmark = [
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
integration = pytest.mark.integration

LOCAL = "127.0.0.1"
MiB = 1024 * 1024
SLOW_RATE = 4 * MiB  # B gửi chậm để có thời gian chen ngang giữa lượt
TRANSFER_TYPES = frozenset({"offer", "accept", "reject", "resume", "complete", "verified", "cancel"})


# --- Hàm phụ trợ ---------------------------------------------------------------------------------


def make_file(directory: Path, name: str, size: int, *, mtime_ns: int | None = None) -> Path:
    """File `size` byte ngẫu nhiên; `mtime_ns` cho trước thì đặt mtime đó."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with open(path, "wb") as f:
        left = size
        while left:
            chunk = os.urandom(min(left, 4 * MiB))
            f.write(chunk)
            left -= len(chunk)
    if mtime_ns is not None:
        os.utime(path, ns=(mtime_ns, mtime_ns))
    return path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(4 * MiB):
            h.update(chunk)
    return h.hexdigest()


def mtime_ms_of(path: Path) -> int:
    return os.stat(path).st_mtime_ns // 1_000_000


def received_names(net) -> set[str]:
    """Tên (NFC) các mục trong thư mục nhận, trừ `.teleport`."""
    return {unicodedata.normalize("NFC", p.name) for p in net.receive_dir.iterdir() if p.name != ".teleport"}


def temp_dir(net, tid: str) -> Path:
    return net.receive_dir / ".teleport" / tid


def only_done_record(net, tid: str) -> bool:
    """P3-3b (spec-p3-3b mục 5.2, `RemoveTemp.keep_record`): sau DONE thư mục tạm chỉ còn `transfer.json`,
    đọc lại được, đủ `verified` và có `done_at` (protocol §6.3, “Nhớ lượt đã kết thúc”)."""
    d = temp_dir(net, tid)
    try:
        names = os.listdir(d)
    except FileNotFoundError:
        return False
    if names != ["transfer.json"]:
        return False
    rec = rs.decode_transfer_record((d / "transfer.json").read_bytes(), dir_name=tid)
    return rec.done_at is not None and rec.verified == len(rec.offer.files)


async def wait_done_record(net, tid: str, timeout: float = 10.0) -> None:
    """Dọn thư mục tạm là việc nền: dò có hạn tới khi chỉ còn `transfer.json` của lượt đã xong."""
    await wait_until(
        lambda: only_done_record(net, tid),
        timeout,
        f"thư mục tạm {tid[:8]} chưa chỉ còn transfer.json có done_at",
    )


def describe(fin) -> str:
    if fin is None:
        return "chưa có TransferFinished"
    return f"result={fin.result} by_peer={fin.by_peer} reason={fin.reason} file_index={fin.file_index}"


def assert_finished(fin, expected, *, by_peer: bool | None = None) -> None:
    assert fin is not None, "chưa có TransferFinished"
    assert fin.result == expected, describe(fin)
    if by_peer is not None:
        assert fin.by_peer is by_peer, describe(fin)


async def run_transfer(net, paths, *, timeout: float = 30.0):
    """B gửi `paths` cho A; chờ TransferFinished cả hai phía. Trả (key, fin_A, fin_B)."""
    key = await net.B.transfers.send(net.A.id, list(paths))
    fin_b = await net.B.trec.wait_finished(key.transfer_id, timeout)
    fin_a = await net.A.trec.wait_finished(key.transfer_id, timeout)
    return key, fin_a, fin_b


class Gate:
    """Chặn một thread đĩa ở đúng chỗ: `wait()` (trong thread) báo `hit` rồi chờ `open` (≤ 30 s)."""

    def __init__(self) -> None:
        self.hit = threading.Event()
        self.open = threading.Event()

    def wait(self) -> None:
        self.hit.set()
        if not self.open.wait(30):
            raise AssertionError("cổng chặn của test không được mở")


def teleport_records(caplog, min_level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("teleport") and r.levelno >= min_level]


# --- Fixture -------------------------------------------------------------------------------------


@pytest.fixture
def T():
    """Module `teleport.app.transfers` (import muộn: chưa có thì chỉ test dùng nó đỏ)."""
    from teleport.app import transfers

    return transfers


@pytest.fixture
def write_spy(monkeypatch):
    """Spy trên seam `storage.PartFile.write_at` (spec-p2-6 B12).

    `calls`: (transfer_id, file_index, index) mỗi lần bắt đầu ghi; `done`: lần ghi xong không lỗi.
    `hooks`: hàm `(part, index)` chạy **trong thread đĩa** trước khi ghi thật (chặn hay ném được).
    """
    spy = SimpleNamespace(calls=[], done=[], hooks=[], lock=threading.Lock())
    real = storage.PartFile.write_at

    def write_at(self, index, data):
        rec = (self.path.parent.name, self.file_index, index)
        with spy.lock:
            spy.calls.append(rec)
        for hook in list(spy.hooks):
            hook(self, index)
        real(self, index, data)
        with spy.lock:
            spy.done.append(rec)

    def count(tid: str, *, done: bool = False) -> int:
        with spy.lock:
            return sum(1 for r in (spy.done if done else spy.calls) if r[0] == tid)

    spy.count = count
    monkeypatch.setattr(storage.PartFile, "write_at", write_at)
    return spy


@pytest.fixture
def frame_spy(monkeypatch):
    """Spy trên seam `connection.Connection.write_block` (bên gửi ghi khung khối).

    `frames`: mỗi khung một `SimpleNamespace(conn, index, t0, t1)` theo thứ tự bắt đầu ghi.
    `mutate(index, payload) -> payload`: đổi payload trước khi ghi (header giữ `sha256` gốc).
    """
    spy = SimpleNamespace(frames=[], mutate=None)
    real = connection.Connection.write_block

    async def write_block(self, index, sha256, payload, *args, **kwargs):
        if spy.mutate is not None:
            payload = spy.mutate(index, payload)
        rec = SimpleNamespace(conn=self, index=index, t0=time.monotonic(), t1=None)
        spy.frames.append(rec)
        try:
            return await real(self, index, sha256, payload, *args, **kwargs)
        finally:
            rec.t1 = time.monotonic()

    monkeypatch.setattr(connection.Connection, "write_block", write_block)
    return spy


@pytest.fixture
def open_data_spy(T, monkeypatch):
    """Spy trên seam `teleport.app.transfers.open_data` (đọc lúc dùng, kế hoạch 2.7).

    `calls`: `SimpleNamespace(t, address, port, opening)`; `fail(n) -> exception | None`: lần gọi thứ
    `n` (đếm từ 0) ném lỗi đó thay vì mở kết nối thật.
    """
    real = T.open_data
    sig = inspect.signature(connection.open_data)
    spy = SimpleNamespace(calls=[], fail=None, real=real)

    async def open_data(*args, **kwargs):
        a = sig.bind(*args, **kwargs).arguments
        n = len(spy.calls)
        spy.calls.append(
            SimpleNamespace(t=time.monotonic(), address=a["address"], port=a["port"], opening=a["opening"])
        )
        if spy.fail is not None:
            exc = spy.fail(n)
            if exc is not None:
                raise exc
        return await real(*args, **kwargs)

    def of(tid: str) -> list:
        return [c for c in spy.calls if c.opening.transfer_id == tid]

    spy.of = of
    monkeypatch.setattr(T, "open_data", open_data)
    return spy


@pytest.fixture
def send_spy(monkeypatch):
    """Spy trên `connection.Connection.send`: ghi (conn, msg); `hang(conn, msg) -> bool` → treo lời gửi đó
    tới khi `release` được đặt (hoặc task bị hủy)."""
    spy = SimpleNamespace(sent=[], hang=None, release=asyncio.Event())
    real = connection.Connection.send

    async def send(self, msg):
        spy.sent.append((self, msg))
        if spy.hang is not None and spy.hang(self, msg):
            await spy.release.wait()
        return await real(self, msg)

    def cancels(tid: str) -> list:
        return [m for _, m in spy.sent if isinstance(m, Cancel) and m.transfer_id == tid]

    spy.cancels = cancels
    monkeypatch.setattr(connection.Connection, "send", send)
    yield spy
    spy.release.set()


@pytest.fixture
def read_spy(monkeypatch):
    """Spy trên `connection.Connection.read_block` (bên nhận đọc khung): `reads` = (conn, chỉ số khối)
    của mọi khung đọc được, theo thứ tự. Chỉ có khung trên kết nối bên nhận đã chấp nhận (kết nối bị từ
    chối sau `data_open` không bao giờ được đọc)."""
    spy = SimpleNamespace(reads=[])
    real = connection.Connection.read_block

    async def read_block(self, *args, **kwargs):
        result = await real(self, *args, **kwargs)
        if result is not None:
            spy.reads.append((self, result[0].index))
        return result

    monkeypatch.setattr(connection.Connection, "read_block", read_block)
    return spy


@pytest.fixture
def engine_spy(monkeypatch):
    """Đếm lời gọi `TransferEngine.block_bad` (bên nhận gặp khối sai)."""
    spy = SimpleNamespace(block_bad=0)
    real = core_transfer.TransferEngine.block_bad

    def block_bad(self, *args, **kwargs):
        spy.block_bad += 1
        return real(self, *args, **kwargs)

    monkeypatch.setattr(core_transfer.TransferEngine, "block_bad", block_bad)
    return spy


class Relay:
    """Relay TCP trong test (spec-p2-6 B12, AC-16): mỗi kết nối vào nối tới `127.0.0.1:target`.

    `cut_client_side(pair)`: cắt phía B (bên mở) nhưng giữ phía A mở, không chuyển EOF sang A, bỏ
    mọi byte A gửi tiếp.
    """

    def __init__(self, target_port: int) -> None:
        self.target_port = target_port
        self.pairs: list[SimpleNamespace] = []
        self.tasks: set[asyncio.Task] = set()
        self.server: asyncio.Server | None = None
        self.port: int | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, LOCAL, 0)
        self.port = self.server.sockets[0].getsockname()[1]

    async def _handle(self, r_b: asyncio.StreamReader, w_b: asyncio.StreamWriter) -> None:
        me = asyncio.current_task()
        self.tasks.add(me)
        try:
            try:
                r_a, w_a = await asyncio.open_connection(LOCAL, self.target_port)
            except OSError:
                w_b.transport.abort()
                return
            pair = SimpleNamespace(w_b=w_b, w_a=w_a, cut=False)
            self.pairs.append(pair)
            await asyncio.gather(
                self._pipe(r_b, w_a, pair, to_a=True), self._pipe(r_a, w_b, pair, to_a=False)
            )
        finally:
            self.tasks.discard(me)

    async def _pipe(self, reader, writer, pair, *, to_a: bool) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                if pair.cut:
                    continue  # đã cắt phía B: bỏ byte
                writer.write(data)
                await writer.drain()
        except (OSError, RuntimeError):
            pass
        finally:
            if not (pair.cut and to_a):  # đã cắt: giữ phía A mở
                writer.transport.abort()

    def cut_client_side(self, pair: SimpleNamespace) -> None:
        pair.cut = True
        pair.w_b.transport.abort()

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
        for pair in self.pairs:
            pair.w_a.transport.abort()
            pair.w_b.transport.abort()
        if self.tasks:
            await asyncio.wait(list(self.tasks), timeout=5)
        if self.server is not None:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self.server.wait_closed(), 5)


@pytest.fixture
async def relay_factory(transfer_nodes):
    """`await relay_factory(port)` → `Relay` đang chạy; dọn **trước** khi node đóng."""
    relays: list[Relay] = []

    async def make(port: int) -> Relay:
        relay = Relay(port)
        await relay.start()
        relays.append(relay)
        return relay

    yield make
    for relay in relays:
        await relay.close()


# =================================================================================================
# Hằng số và API công khai (không socket)
# =================================================================================================


def test_constants_match_plan(T):
    """Kế hoạch mục 2.10: các con số mới, là biến cấp module (đọc lúc dùng); P3-3b (spec-p3-3b mục 2.1):
    `TOMBSTONE_FLUSH_TIMEOUT`, `TOMBSTONE_MIN_INTERVAL`, `CLEANUP_INTERVAL`."""
    from teleport.app import diskio

    assert T.DISK_OP_TIMEOUT == 60
    assert T.DISK_SYNC_TIMEOUT == 120
    assert T.REREAD_BLOCK_TIMEOUT == 1
    assert T.CONTROL_SEND_QUEUE_MAX == 4096
    assert T.CANCEL_FLUSH_TIMEOUT == 0.5
    assert T.CLOSE_DISK_WAIT == 2
    assert T.MAX_LIMITED_SENDS == 8
    assert T.MIN_RATE_LIMIT == ratelimit.CHUNK_SIZE == 64 * 1024
    assert T.PROGRESS_INTERVAL == 1
    assert T.SPEED_WINDOW == 5
    assert T.WRITE_QUEUE_BLOCKS == 8
    assert T.TOMBSTONE_FLUSH_TIMEOUT == 2
    assert T.TOMBSTONE_MIN_INTERVAL == 1
    assert T.CLEANUP_INTERVAL == 24 * 3600
    assert diskio.DISK_THREADS == 4


def test_public_api_is_exported(T):
    """Kế hoạch mục 3: `__all__` và các lớp re-export từ `core`/`sources`; P3-3b: `TransferResumed`."""
    expected = {
        "TransferManager",
        "TransferResumed",
        "TransferResult",
        "TransferUpdate",
        "OfferReceived",
        "TransferStatusChanged",
        "TransferProgress",
        "FileDone",
        "TransferFinished",
        "DataUnreachable",
        "TransferKey",
        "TransferInfo",
        "TransferStatus",
        "Direction",
        "FileEntry",
        "SourceError",
        "SourceErrorKind",
        "MIN_RATE_LIMIT",
    }
    assert expected <= set(T.__all__), sorted(expected - set(T.__all__))
    for name in expected:
        assert hasattr(T, name), name
    assert T.TransferKey is core_transfer.TransferKey
    assert T.TransferInfo is core_transfer.TransferInfo
    assert T.TransferStatus is core_transfer.TransferStatus
    assert T.Direction is core_transfer.Direction
    assert T.FileEntry is FileEntry
    assert T.SourceError is sources.SourceError
    assert T.SourceErrorKind is sources.SourceErrorKind


def test_data_unreachable_is_reexport_of_core_class(T):
    """Spec B9: cùng dữ liệu (`device_id`) → re-export đúng lớp của `core.transfer`, không có hai lớp
    khác nhau cùng tên `DataUnreachable`."""
    assert T.DataUnreachable is core_transfer.DataUnreachable
    assert [f.name for f in dataclasses.fields(T.DataUnreachable)] == ["device_id"]


def test_transfer_result_has_exactly_planned_members(T):
    """Kế hoạch mục 3, bảng `TransferResult`; P3-3b (spec-p3-3b mục 2.1): thêm `SUSPENDED = "suspended"`."""
    assert issubclass(T.TransferResult, StrEnum)
    assert {m.name for m in T.TransferResult} == {
        "DONE",
        "REJECTED_USER",
        "REJECTED_NO_SPACE",
        "REJECTED_FILE_TOO_LARGE",
        "REJECTED_BUSY",
        "REJECTED_NOT_RECEIVING",
        "REJECTED_OTHER",
        "UNPAIRED",
        "CANCELLED_USER",
        "SOURCE_CHANGED",
        "EXPIRED",
        "DISK_FAILED",
        "TEMP_EXISTS",
        "RECEIVE_DIR_MISSING",
        "CORRUPT",
        "PROTOCOL_ERROR",
        "SOURCE_READ_FAILED",
        "PEER_ERROR",
        "UNKNOWN_TRANSFER",
        "CANCELLED_OTHER",
        "SUSPENDED",
    }
    assert T.TransferResult.SUSPENDED == "suspended"


@pytest.mark.parametrize(
    ("cls", "fields"),
    [
        ("OfferReceived", ["key", "device_name", "files", "names", "total_bytes", "auto_accepted"]),
        ("TransferStatusChanged", ["info"]),
        ("TransferProgress", ["info", "bytes_per_second", "eta", "shown_bytes", "idle_seconds"]),
        ("FileDone", ["key", "file_index", "name", "path"]),
        (
            "TransferFinished",
            ["info", "result", "by_peer", "reason", "file_index", "reject", "payload_sent"],
        ),
        ("TransferResumed", ["info"]),
    ],
)
def test_event_classes_are_frozen_dataclasses_with_planned_fields(T, cls, fields):
    klass = getattr(T, cls)
    assert dataclasses.is_dataclass(klass)
    assert klass.__dataclass_params__.frozen
    assert [f.name for f in dataclasses.fields(klass)] == fields


# =================================================================================================
# AC-1…AC-4: đường đi đúng
# =================================================================================================


@pytest.mark.demo
@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac1_single_file_arrives_intact_with_name_and_mtime(T, transfer_nodes, client):
    """AC-1: một file 5 MiB + 1, hai chiều: SHA khớp, tên giữ, mtime = offer (ms), thư mục tạm chỉ còn
    `transfer.json` có `done_at` (P3-3b), hai phía DONE, `FileDone.path` của A đúng; `OfferReceived` mang
    đủ thông tin."""
    R = T.TransferResult
    net = await transfer_nodes(client=client)
    A, B = net.A, net.B
    name = unicodedata.normalize("NFC", "Ảnh chuyến đi.bin")
    size = 5 * MiB + 1
    src = make_file(net.src, name, size, mtime_ns=1_600_000_000_123_456_789)
    key, fin_a, fin_b = await run_transfer(net, [src])
    tid = key.transfer_id

    assert key == T.TransferKey(A.id, T.Direction.SEND, tid)
    assert len(tid) == 32 and tid == tid.lower()
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    rkey = T.TransferKey(B.id, T.Direction.RECEIVE, tid)
    assert fin_a.info.key == rkey and fin_b.info.key == key

    dst = net.receive_dir / name
    assert dst.is_file()
    assert sha256_of(dst) == sha256_of(src)
    assert mtime_ms_of(dst) == 1_600_000_000_123
    assert received_names(net) == {name}
    await wait_done_record(net, tid)

    offers = A.trec.of("OfferReceived", tid)
    assert len(offers) == 1
    offer = offers[0]
    assert offer.key == rkey
    assert offer.device_name == "B"  # tên trong trusted.json của A
    assert offer.files == (FileEntry(name, size, 1_600_000_000_123),)
    assert offer.names == (name,)
    assert offer.total_bytes == size
    assert offer.auto_accepted is True

    done = A.trec.of("FileDone", tid)
    assert len(done) == 1
    assert (done[0].key, done[0].file_index, done[0].name) == (rkey, 0, name)
    assert done[0].path == dst
    assert len(B.trec.of("FileDone", tid)) == 1

    assert A.transfers.get(rkey) is None and B.transfers.get(key) is None
    assert A.transfers.transfers() == () and B.transfers.transfers() == ()


@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac2_three_files_with_empty_one_open_data_only_for_non_empty(
    T, transfer_nodes, open_data_spy, client
):
    """AC-2 (spec B12): ba file (0, 1 MiB, 3 MiB + 7) hai chiều; file rỗng không có `data_open`, mỗi
    file khác rỗng có ≥ 1 kết nối dữ liệu."""
    R = T.TransferResult
    net = await transfer_nodes(client=client)
    files = [
        make_file(net.src, "rong.txt", 0),
        make_file(net.src, "mot.bin", MiB),
        make_file(net.src, "ba.bin", 3 * MiB + 7),
    ]
    key, fin_a, fin_b = await run_transfer(net, files)
    tid = key.transfer_id
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    for f in files:
        dst = net.receive_dir / f.name
        assert dst.is_file(), f.name
        assert dst.stat().st_size == f.stat().st_size
        assert sha256_of(dst) == sha256_of(f)
    assert [d.file_index for d in net.A.trec.of("FileDone", tid)] == [0, 1, 2]
    opened = collections.Counter(c.opening.file_index for c in open_data_spy.of(tid))
    assert set(opened) == {1, 2}, f"data_open theo file: {dict(opened)} (file rỗng không được mở)"
    await wait_done_record(net, tid)


@pytest.mark.slow
@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac3_64_mib_random_file_two_directions(T, transfer_nodes, client):
    """AC-3: 64 MiB ngẫu nhiên, hai chiều."""
    R = T.TransferResult
    net = await transfer_nodes(client=client)
    src = make_file(net.src, "lon.bin", 64 * MiB)
    key, fin_a, fin_b = await run_transfer(net, [src], timeout=120)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "lon.bin") == sha256_of(src)
    await wait_done_record(net, key.transfer_id)


@pytest.mark.demo
@integration
async def test_ac4_duplicate_names_never_overwrite(T, transfer_nodes):
    """AC-4: `a.txt` canh gác không đổi, file nhận thành `a (1).txt`; offer hai `x.bin` → `x.bin`,
    `x (1).bin` (protocol §4.4: không bao giờ ghi đè file đã có)."""
    R = T.TransferResult
    net = await transfer_nodes()
    A = net.A
    net.receive_dir.mkdir(parents=True, exist_ok=True)
    guard = net.receive_dir / "a.txt"
    guard.write_bytes(b"canh gac")
    src = make_file(net.src, "a.txt", 2 * MiB)
    key, fin_a, _ = await run_transfer(net, [src])
    assert_finished(fin_a, R.DONE)
    assert guard.read_bytes() == b"canh gac"
    assert sha256_of(net.receive_dir / "a (1).txt") == sha256_of(src)
    [done] = A.trec.of("FileDone", key.transfer_id)
    assert done.name == "a (1).txt" and done.path == net.receive_dir / "a (1).txt"

    x1 = make_file(net.src / "d1", "x.bin", MiB + 3)
    x2 = make_file(net.src / "d2", "x.bin", 2 * MiB + 5)
    key2, fin_a2, fin_b2 = await run_transfer(net, [x1, x2])
    assert_finished(fin_b2, R.DONE)
    assert_finished(fin_a2, R.DONE)
    [offer] = A.trec.of("OfferReceived", key2.transfer_id)
    assert offer.names == ("x.bin", "x (1).bin")
    assert sha256_of(net.receive_dir / "x.bin") == sha256_of(x1)
    assert sha256_of(net.receive_dir / "x (1).bin") == sha256_of(x2)
    assert received_names(net) == {"a.txt", "a (1).txt", "x.bin", "x (1).bin"}


# =================================================================================================
# AC-5…AC-8: từ chối
# =================================================================================================


@integration
async def test_ac5_user_rejects_offer(T, transfer_nodes):
    """AC-5: người dùng A từ chối → `reject{user}`: A `REJECTED_USER` (by_peer False), B
    `REJECTED_USER` (by_peer True); không file, không thư mục tạm."""
    R = T.TransferResult
    net = await transfer_nodes({"auto_accept": False})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", MiB)])
    tid = key.transfer_id
    offer = await A.trec.wait_kind("OfferReceived", tid)
    assert offer.auto_accepted is False
    assert A.transfers.get(offer.key).status == T.TransferStatus.WAITING
    A.transfers.decide(offer.key, False)
    fin_b = await B.trec.wait_finished(tid)
    fin_a = await A.trec.wait_finished(tid)
    assert_finished(fin_b, R.REJECTED_USER, by_peer=True)
    assert fin_b.reject is not None and fin_b.reject.reason == "user"
    assert_finished(fin_a, R.REJECTED_USER, by_peer=False)
    assert received_names(net) == set()
    assert not temp_dir(net, tid).exists()


@integration
async def test_ac6_no_space_rejects_before_asking_user(T, transfer_nodes, monkeypatch):
    """AC-6: chỗ trống giả lập (seam `storage.shutil.disk_usage`) nhỏ hơn tổng → `reject{no_space}`
    kèm `needed`/`available`; A không hỏi người dùng (không có `OfferReceived`)."""
    R = T.TransferResult
    net = await transfer_nodes({"auto_accept": False})
    A, B = net.A, net.B
    usage = collections.namedtuple("usage", "total used free")
    monkeypatch.setattr(storage.shutil, "disk_usage", lambda path: usage(10 * MiB, 9 * MiB, MiB))
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 2 * MiB)])
    fin_b = await B.trec.wait_finished(key.transfer_id)
    fin_a = await A.trec.wait_finished(key.transfer_id)
    assert_finished(fin_b, R.REJECTED_NO_SPACE, by_peer=True)
    assert (fin_b.reject.reason, fin_b.reject.needed, fin_b.reject.available) == ("no_space", 2 * MiB, MiB)
    assert_finished(fin_a, R.REJECTED_NO_SPACE, by_peer=False)
    assert A.trec.of("OfferReceived") == []
    assert received_names(net) == set()


@integration
async def test_ac7_fat32_rejects_file_too_large(T, transfer_nodes, monkeypatch):
    """AC-7: FAT32 giả lập (seam `storage._fs_type_of`, `storage.FAT_MAX_FILE_SIZE`) →
    `reject{file_too_large}` cho file vi phạm đầu tiên (`file_index`, `max_size`)."""
    R = T.TransferResult
    net = await transfer_nodes()
    A, B = net.A, net.B
    monkeypatch.setattr(storage, "_fs_type_of", lambda path: "vfat")
    monkeypatch.setattr(storage, "FAT_MAX_FILE_SIZE", MiB)
    files = [make_file(net.src, "nho.bin", 10), make_file(net.src, "lon.bin", MiB + 1)]
    key = await B.transfers.send(A.id, files)
    fin_b = await B.trec.wait_finished(key.transfer_id)
    fin_a = await A.trec.wait_finished(key.transfer_id)
    assert_finished(fin_b, R.REJECTED_FILE_TOO_LARGE, by_peer=True)
    assert (fin_b.reject.reason, fin_b.reject.file_index, fin_b.reject.max_size) == ("file_too_large", 1, MiB)
    assert fin_b.file_index == 1
    assert_finished(fin_a, R.REJECTED_FILE_TOO_LARGE, by_peer=False)
    assert received_names(net) == set()


@pytest.mark.slow
@integration
async def test_ac8_node_without_receive_dir_rejects_not_receiving(T, transfer_nodes):
    """AC-8: A không có thư mục nhận → không nhận file (`receiving` False) → `reject{not_receiving}`."""
    R = T.TransferResult
    net = await transfer_nodes({"receive_dir": None, "auto_accept": False})
    A, B = net.A, net.B
    assert A.transfers.receiving is False
    assert A.transfers.receive_dir is None
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 1000)])
    fin_b = await B.trec.wait_finished(key.transfer_id)
    assert_finished(fin_b, R.REJECTED_NOT_RECEIVING, by_peer=True)
    assert fin_b.reject.reason == "not_receiving"
    await asyncio.sleep(0.2)
    assert A.trec.of("OfferReceived") == []


@integration
async def test_receiving_node_reports_receive_dir_and_sender_does_not(T, transfer_nodes):
    net = await transfer_nodes()
    assert net.A.transfers.receiving is True
    assert net.A.transfers.receive_dir == Path(os.path.abspath(net.receive_dir))
    assert net.B.transfers.receiving is False
    assert net.B.transfers.receive_dir is None


# =================================================================================================
# AC-9…AC-12: lỗi đĩa, thư mục tạm có sẵn, file nguồn đổi, lỗi đọc nguồn
# =================================================================================================


@integration
async def test_ac9_write_error_on_second_file_cancels_with_disk_failed(T, transfer_nodes, write_spy):
    """AC-9: `PartFile.write_at` ném `OSError(ENOSPC)` ở khối 3 của file 2 → A `DISK_FAILED`
    (file_index 1), B `PEER_ERROR`; file 1 đã xong được giữ, không còn `.part` hay thư mục tạm."""
    R = T.TransferResult
    net = await transfer_nodes()

    def fail(part, index):
        if part.file_index == 1 and index == 3:
            raise OSError(errno.ENOSPC, "giả lập đầy đĩa")

    write_spy.hooks.append(fail)
    files = [
        make_file(net.src, "f0.bin", 2 * MiB),
        make_file(net.src, "f1.bin", 5 * MiB),
        make_file(net.src, "f2.bin", 2 * MiB),
    ]
    key, fin_a, fin_b = await run_transfer(net, files)
    tid = key.transfer_id
    assert_finished(fin_a, R.DISK_FAILED, by_peer=False)
    assert fin_a.file_index == 1
    assert_finished(fin_b, R.PEER_ERROR, by_peer=True)
    assert fin_b.reason == "error"
    await wait_until(lambda: not temp_dir(net, tid).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == {"f0.bin"}
    assert sha256_of(net.receive_dir / "f0.bin") == sha256_of(files[0])


@integration
async def test_ac10_existing_temp_dir_gives_temp_exists_and_is_left_untouched(T, transfer_nodes, monkeypatch):
    """AC-10: thư mục tạm `.teleport/<tid>` đã có (sót lại) → A `TEMP_EXISTS`, B `PEER_ERROR`; thư mục
    và nội dung cũ không bị đụng tới (spec A4, protocol §4.4)."""
    R = T.TransferResult
    tid = "ab" * 16
    monkeypatch.setattr(T, "uuid4", lambda: SimpleNamespace(hex=tid))
    net = await transfer_nodes()
    old = temp_dir(net, tid)
    old.mkdir(parents=True)
    (old / "0.part").write_bytes(b"du lieu cu")
    key, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 2 * MiB)])
    assert key.transfer_id == tid
    assert_finished(fin_a, R.TEMP_EXISTS, by_peer=False)
    assert_finished(fin_b, R.PEER_ERROR, by_peer=True)
    await asyncio.sleep(0.3)
    assert (old / "0.part").read_bytes() == b"du lieu cu"
    assert sorted(p.name for p in old.iterdir()) == ["0.part"]
    assert received_names(net) == set()


@pytest.mark.slow
@integration
async def test_receive_dir_deleted_while_running_is_recreated(T, transfer_nodes):
    """Lỗi demo 2026-10-29: người dùng xóa thư mục nhận khi node đang chạy → lượt sau vẫn nhận được
    (thư mục được tạo lại), không báo `DISK_FAILED`."""
    R = T.TransferResult
    net = await transfer_nodes()
    shutil.rmtree(net.receive_dir)
    files = [make_file(net.src, "f.bin", 2 * MiB)]
    _, fin_a, fin_b = await run_transfer(net, files)
    assert_finished(fin_a, R.DONE, by_peer=False)
    assert_finished(fin_b, R.DONE, by_peer=False)
    assert received_names(net) == {"f.bin"}
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(files[0])


@integration
async def test_receive_dir_replaced_by_file_gives_receive_dir_missing(T, transfer_nodes):
    """Thư mục nhận mất và không tạo lại được → A `RECEIVE_DIR_MISSING` (không phải `DISK_FAILED`),
    B `PEER_ERROR`; file chiếm tên không bị đụng tới."""
    R = T.TransferResult
    net = await transfer_nodes()
    shutil.rmtree(net.receive_dir)
    net.receive_dir.write_bytes(b"chiem ten")
    _, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 2 * MiB)])
    assert_finished(fin_a, R.RECEIVE_DIR_MISSING, by_peer=False)
    assert_finished(fin_b, R.PEER_ERROR, by_peer=True)
    assert net.receive_dir.read_bytes() == b"chiem ten"


@integration
async def test_ac11_source_modified_during_transfer_is_source_changed(T, transfer_nodes, monkeypatch):
    """AC-11: mtime file nguồn đổi giữa lượt (sau khi đọc khối 2) → `cancel{source_changed}`: B
    `SOURCE_CHANGED` (by_peer False), A `SOURCE_CHANGED` (by_peer True); A không giữ file nào."""
    R = T.TransferResult
    net = await transfer_nodes()
    real = sources.SourceReader.read_block

    def read_block(self, index):
        result = real(self, index)
        if index == 2:
            st = os.stat(self.path)
            os.utime(self.path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        return result

    monkeypatch.setattr(sources.SourceReader, "read_block", read_block)
    key, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 5 * MiB)])
    assert_finished(fin_b, R.SOURCE_CHANGED, by_peer=False)
    assert_finished(fin_a, R.SOURCE_CHANGED, by_peer=True)
    assert fin_a.reason == "source_changed"
    await wait_until(lambda: not temp_dir(net, key.transfer_id).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()


@integration
async def test_ac12_source_read_error_is_source_read_failed(T, transfer_nodes, monkeypatch):
    """AC-12: đọc file nguồn lỗi (`OSError(EIO)` ở khối 2) → B `SOURCE_READ_FAILED`, A `PEER_ERROR`."""
    R = T.TransferResult
    net = await transfer_nodes()
    real = sources.SourceReader.read_block

    def read_block(self, index):
        if index == 2:
            raise OSError(errno.EIO, "giả lập lỗi đọc", str(self.path))
        return real(self, index)

    monkeypatch.setattr(sources.SourceReader, "read_block", read_block)
    key, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 5 * MiB)])
    assert_finished(fin_b, R.SOURCE_READ_FAILED, by_peer=False)
    assert_finished(fin_a, R.PEER_ERROR, by_peer=True)
    await wait_until(lambda: not temp_dir(net, key.transfer_id).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()


# =================================================================================================
# AC-13: ma trận hủy {B, A} × {đang chờ quyết, ngay sau accept, giữa file 2 của 3, lúc VERIFYING,
# sau DONE}
# =================================================================================================

AC13_PHASES = ["dang-cho-quyet", "ngay-sau-accept", "giua-file-2", "dang-xac-minh", "sau-done"]


def ac13_expected(R, phase: str, canceller: str):
    """Kết quả mong đợi của từng ô (spec-p2-6 B8), trả (kết quả A, kết quả B).

    - đang chờ quyết, A hủy: `engine.cancel` với lượt nhận chưa RUNNING là `reject{user}` →
      hai bên `REJECTED_USER` (A by_peer False, B by_peer True).
    - đang chờ quyết, B hủy: `cancel{user}` → hai bên `CANCELLED_USER` (B False, A True).
    - ngay sau accept / giữa file 2 / lúc VERIFYING, bên nào hủy: hai bên `CANCELLED_USER`
      (bên hủy by_peer False, bên kia True).
    - sau DONE: hủy là no-op, hai bên vẫn `DONE`, không có sự kiện mới.
    """
    if phase == "sau-done":
        return R.DONE, R.DONE
    if phase == "dang-cho-quyet" and canceller == "A":
        return R.REJECTED_USER, R.REJECTED_USER
    return R.CANCELLED_USER, R.CANCELLED_USER


@integration
# "sau-done" chờ tới khi lượt xong rồi mới hủy: đo được 0,7–3 s (PR-9, T7), nên gắn slow riêng ca đó.
@pytest.mark.parametrize(
    "phase", [pytest.param(p, marks=pytest.mark.slow) if p == "sau-done" else p for p in AC13_PHASES]
)
@pytest.mark.parametrize("canceller", ["A", "B"])
async def test_ac13_cancel_matrix(T, transfer_nodes, write_spy, monkeypatch, phase, canceller):
    R = T.TransferResult
    asks = phase in ("dang-cho-quyet", "ngay-sau-accept")
    net = await transfer_nodes({"auto_accept": not asks})
    A, B = net.A, net.B
    gate = Gate()
    try:
        if phase == "giua-file-2":
            files = [make_file(net.src, f"f{i}.bin", 3 * MiB) for i in range(3)]
            write_spy.hooks.append(
                lambda part, index: gate.wait() if (part.file_index, index) == (1, 1) else None
            )
        elif phase == "dang-xac-minh":
            files = [make_file(net.src, "f.bin", 3 * MiB)]
            real_reread = storage.PartFile.reread

            def reread(self, *, stop=None):
                gate.wait()
                return real_reread(self, stop=stop)

            monkeypatch.setattr(storage.PartFile, "reread", reread)
        else:
            files = [make_file(net.src, "f.bin", 2 * MiB)]

        if phase == "ngay-sau-accept" and canceller == "B":
            # Hủy ngay trong callback, đúng lúc B biết lượt được nhận (TRANSFERRING): lời gọi trong lúc
            # dispatch được xếp hàng (kế hoạch 2.7), không gọi engine lồng.
            done_once: list[bool] = []

            def on_accept(u):
                if (
                    not done_once
                    and type(u).__name__ == "TransferStatusChanged"
                    and u.info.key.direction == T.Direction.SEND
                    and u.info.status == T.TransferStatus.TRANSFERRING
                ):
                    done_once.append(True)
                    B.transfers.cancel(u.info.key)

            B.trec.hooks.append(on_accept)

        key = await B.transfers.send(A.id, files)
        tid = key.transfer_id
        rkey = T.TransferKey(B.id, T.Direction.RECEIVE, tid)

        if asks:
            offer = await A.trec.wait_kind("OfferReceived", tid)
            assert offer.key == rkey
            if phase == "dang-cho-quyet":
                assert A.transfers.get(rkey).status == T.TransferStatus.WAITING
                if canceller == "A":
                    A.transfers.cancel(rkey)
                else:
                    B.transfers.cancel(key)
            elif canceller == "A":
                A.transfers.decide(rkey, True)
                A.transfers.cancel(rkey)
            else:
                A.transfers.decide(rkey, True)  # B hủy trong callback khi thấy TRANSFERRING
        elif phase in ("giua-file-2", "dang-xac-minh"):
            await wait_until(gate.hit.is_set, 30, "chưa tới điểm hủy")
            if phase == "giua-file-2":
                assert [d.file_index for d in A.trec.of("FileDone", tid)] == [0]
            else:
                assert A.transfers.get(rkey).status == T.TransferStatus.VERIFYING
            (A.transfers.cancel(rkey) if canceller == "A" else B.transfers.cancel(key))
        else:  # sau-done
            assert_finished(await B.trec.wait_finished(tid), R.DONE)
            assert_finished(await A.trec.wait_finished(tid), R.DONE)
            n_a, n_b = len(A.trec.updates), len(B.trec.updates)
            (A.transfers.cancel(rkey) if canceller == "A" else B.transfers.cancel(key))
            await asyncio.sleep(0.3)
            assert len(A.trec.updates) == n_a and len(B.trec.updates) == n_b, "hủy sau DONE sinh sự kiện"

        fin_a = await A.trec.wait_finished(tid)
        fin_b = await B.trec.wait_finished(tid)
    finally:
        gate.open.set()

    exp_a, exp_b = ac13_expected(R, phase, canceller)
    if phase == "sau-done":
        assert_finished(fin_a, exp_a)
        assert_finished(fin_b, exp_b)
        assert len(A.trec.of("TransferFinished", tid)) == 1 == len(B.trec.of("TransferFinished", tid))
        assert received_names(net) == {"f.bin"}
        return
    assert_finished(fin_a, exp_a, by_peer=canceller != "A")
    assert_finished(fin_b, exp_b, by_peer=canceller != "B")
    if exp_a == R.REJECTED_USER:
        assert fin_b.reject is not None and fin_b.reject.reason == "user"
    await wait_until(lambda: not temp_dir(net, tid).exists(), 10, "thư mục tạm chưa được xóa")
    if phase == "giua-file-2":
        assert received_names(net) == {"f0.bin"}
        assert sha256_of(net.receive_dir / "f0.bin") == sha256_of(files[0])
    else:
        assert received_names(net) == set()
    assert A.transfers.get(rkey) is None and B.transfers.get(key) is None


# =================================================================================================
# AC-14, AC-15: khối sai
# =================================================================================================


@integration
async def test_ac14_corrupted_block_is_resent_alone(
    T, transfer_nodes, frame_spy, write_spy, engine_spy, read_spy
):
    """AC-14 (spec B12): lật một byte payload khối 5 lần đầu (seam `Connection.write_block`) → khối sai
    bị phát hiện đúng một lần; mỗi chỉ số được ghi xuống đĩa đúng một lần; lượt vẫn DONE, SHA khớp.

    “Chỉ khối sai được gửi lại” kiểm ở **bên nhận** (khung mà A thật sự đọc, spy `Connection.read_block`):
    sau khối sai, khung đầu A đọc trên kết nối mới là khối 5 và không khối nào < 5 được đọc lại. Không
    kiểm theo khung bên gửi ghi: B là client, kết nối dữ liệu đứt thì B thử mở lại cho `resume` cũ
    (lịch protocol §4.1); A từ chối `data_open` của `resume` cũ (đang chờ `fsync` trước `resume` mới,
    docstring `core/transfer.py`), nhưng server không xác nhận `data_open` (protocol §4.1) nên B có thể
    đã ghi một khung (khối 0) trước khi thấy kết nối bị đóng. Khung đó bị bỏ, không phải gửi lại.
    """
    R = T.TransferResult
    reads = read_spy.reads
    net = await transfer_nodes()
    flipped: list[object] = []

    def mutate(index, payload):
        if index == 5 and not flipped:
            bad = bytearray(payload)
            bad[0] ^= 0xFF
            flipped.append(True)
            return bad
        return payload

    frame_spy.mutate = mutate
    src = make_file(net.src, "f.bin", 10 * MiB)
    key, fin_a, fin_b = await run_transfer(net, [src])
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)
    assert engine_spy.block_bad == 1

    written = collections.Counter(i for tid, f, i in write_spy.done if tid == key.transfer_id and f == 0)
    assert written == collections.Counter(range(10)), f"số lần ghi mỗi khối: {dict(written)}"

    order = [i for _, i in reads]
    bad_pos = order.index(5)  # khung khối 5 đầu tiên A đọc là khung bị lật
    bad_conn = reads[bad_pos][0]
    assert order[:bad_pos] == [0, 1, 2, 3, 4], f"khung A đọc: {order}"
    after = reads[bad_pos + 1 :]
    assert after, "A không đọc khung nào sau khối sai"
    assert all(c is not bad_conn for c, _ in after), "A còn đọc tiếp trên kết nối có khối sai"
    assert [i for _, i in after] == [5, 6, 7, 8, 9], f"khung A đọc sau khối sai: {[i for _, i in after]}"
    assert len(flipped) == 1 and sum(1 for fr in frame_spy.frames if fr.index == 5) >= 2


@integration
async def test_ac15_block_always_corrupt_cancels_with_corrupt_at_fourth(
    T, transfer_nodes, frame_spy, engine_spy, read_spy
):
    """AC-15: khối 5 luôn sai → lần thứ 4 (`MAX_BAD_BLOCKS` + 1) hủy: A `CORRUPT` (file 0), B `PEER_ERROR`.

    Số lần khối 5 tới đếm ở bên nhận (`read_spy`): B có thể ghi thêm khung lên kết nối mở lại cho
    `resume` cũ mà A đã từ chối (xem AC-14), khung đó không được đọc.
    """
    R = T.TransferResult
    net = await transfer_nodes()

    def mutate(index, payload):
        if index == 5:
            bad = bytearray(payload)
            bad[-1] ^= 0x01
            return bad
        return payload

    frame_spy.mutate = mutate
    key, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 8 * MiB)])
    assert_finished(fin_a, R.CORRUPT, by_peer=False)
    assert fin_a.file_index == 0
    assert_finished(fin_b, R.PEER_ERROR, by_peer=True)
    assert engine_spy.block_bad == core_transfer.MAX_BAD_BLOCKS + 1 == 4
    assert [i for _, i in read_spy.reads if i == 5] == [5] * 4
    assert [i for _, i in read_spy.reads if i != 5] == [0, 1, 2, 3, 4], "khối đã có bit bị gửi lại"
    assert sum(1 for fr in frame_spy.frames if fr.index == 5) >= 4
    await wait_until(lambda: not temp_dir(net, key.transfer_id).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()


# =================================================================================================
# AC-16…AC-18 (+ AC-32): đổi / mất kết nối điều khiển, hold
# =================================================================================================


@pytest.mark.slow
@integration
async def test_ac16_control_replaced_mid_transfer_still_done(T, transfer_nodes, relay_factory, write_spy):
    """AC-16 (spec B12): B nối tới A qua relay TCP; relay cắt phía B nhưng giữ phía A; B nối lại qua
    relay; A đổi sang kết nối mới (`LinkSwitched`, không `DeviceDisconnected`) và lượt vẫn DONE."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE}, connect=False)
    A, B = net.A, net.B
    relay = await relay_factory(A.port)
    B.connect_hint(A.id, [LOCAL], relay.port)
    await wait_until(lambda: A.id in B.connected_devices() and B.id in A.connected_devices(), 5)
    old_on_a = A.control_connection(B.id)
    control_pair = relay.pairs[0]

    src = make_file(net.src, "f.bin", 16 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 3, 20, "A chưa nhận khối nào")
    relay.cut_client_side(control_pair)
    await B.rec.wait_event(DeviceDisconnected, A.id, timeout=5)
    await wait_until(
        lambda: A.control_connection(B.id) not in (None, old_on_a), 10, "A chưa đổi sang kết nối mới"
    )
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A.trec.wait_finished(tid, 60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)
    assert A.rec.events_of(DeviceDisconnected, B.id) == [], "A đổi kết nối mà lại báo mất kết nối"
    assert len(A.rec.events_of(DeviceConnected, B.id)) == 1


@pytest.mark.slow
@pytest.mark.demo
@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac17_control_lost_mid_transfer_reconnects_and_finishes(T, transfer_nodes, write_spy, client):
    """AC-17 (A2): kết nối điều khiển đứt giữa lượt (không mDNS, chỉ hint) → bên mở nối lại nhờ `hold`
    trong `RECONNECT_GRACE`; hai phía thấy RECONNECTING rồi DONE, SHA khớp."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE}, client=client)
    A, B = net.A, net.B
    opener, other = (B, A) if client == "sender" else (A, B)
    src = make_file(net.src, "f.bin", 12 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")
    opener.control_connection(other.id).abort()
    await opener.rec.wait_event(DeviceDisconnected, other.id, timeout=5)
    await opener.rec.wait_event(DeviceConnected, other.id, n=2, timeout=10)
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A.trec.wait_finished(tid, 60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)
    assert "reconnecting" in B.trec.statuses(tid)
    assert "reconnecting" in A.trec.statuses(tid)


@pytest.mark.slow
@integration
async def test_ac17_mdns_gone_mid_transfer_still_reconnects_thanks_to_hold(
    T, transfer_nodes, write_spy, fake_mdns, app_helpers, count_open_control, fast
):
    """AC-17 + AC-32: B thấy A qua mDNS; giữa lượt mDNS báo A đi rồi kết nối đứt → B vẫn nối lại tới
    địa chỉ cuối (nhờ `hold`) và lượt DONE. Sau DONE hết `hold`: đứt lần nữa thì không tự thử lại."""
    R = T.TransferResult
    counter = count_open_control()
    net = await transfer_nodes(
        {"mdns": MdnsOptions()}, {"mdns": MdnsOptions(), "rate_limit": SLOW_RATE}, connect=False
    )
    A, B = net.A, net.B
    fake_mdns.of(B).emit(DeviceAdded(app_helpers.dev(A)))
    await wait_until(lambda: A.id in B.connected_devices() and B.id in A.connected_devices(), 5)
    src = make_file(net.src, "f.bin", 12 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")
    fake_mdns.of(B).emit(DeviceRemoved(app_helpers.dev(A)))
    B.control_connection(A.id).abort()
    await B.rec.wait_event(DeviceDisconnected, A.id, timeout=5)
    await B.rec.wait_event(DeviceConnected, A.id, n=2, timeout=10)
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A.trec.wait_finished(tid, 60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)

    # Hết lượt dở → thả `hold`: mDNS đã báo đi, không hint → đứt lần nữa thì không thử lại theo lịch.
    await asyncio.sleep(0.3)
    B.control_connection(A.id).abort()
    await B.rec.wait_event(DeviceDisconnected, A.id, n=2, timeout=5)
    n = counter.count(caller=B)
    await asyncio.sleep(5 * fast.RETRY_BASE + 0.5)
    assert counter.count(caller=B) == n, "không còn lượt dở mà vẫn tự nối lại"
    assert A.id not in B.connected_devices()


@pytest.mark.slow
@integration
async def test_ac18_reconnect_grace_expires_and_hold_is_released(
    T, transfer_nodes, write_spy, monkeypatch, fast
):
    """AC-18 + AC-32: không nối lại được trong `RECONNECT_GRACE` → hai phía `EXPIRED`, A xóa thư mục tạm;
    trong lúc chờ B vẫn thử nối lại (hold), hết lượt dở thì thôi thử."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 12 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")

    attempts: list[float] = []

    async def unreachable(*args, **kwargs):
        attempts.append(time.monotonic())
        raise connection.Unreachable("giả lập không nối được")

    monkeypatch.setattr(node_mod, "open_control", unreachable)
    t_cut = time.monotonic()
    B.control_connection(A.id).abort()
    fin_b = await B.trec.wait_finished(tid, fast.RECONNECT_GRACE + 10)
    fin_a = await A.trec.wait_finished(tid, fast.RECONNECT_GRACE + 10)
    assert_finished(fin_b, R.EXPIRED, by_peer=False)
    assert_finished(fin_a, R.EXPIRED, by_peer=False)
    expired_after = B.trec.timed("TransferFinished", tid)[0][0] - t_cut
    assert expired_after >= 0.8 * fast.RECONNECT_GRACE, expired_after
    assert len(attempts) >= 2, f"B chỉ thử nối lại {len(attempts)} lần trong lúc chờ (hold)"
    await wait_until(lambda: not temp_dir(net, tid).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()

    await asyncio.sleep(0.5)
    n = len(attempts)
    await asyncio.sleep(2 * fast.RETRY_MAX + 0.5)
    assert len(attempts) == n, "đã hết lượt dở mà B vẫn thử nối lại theo lịch"


@integration
async def test_ac32_hold_follows_unfinished_transfers_and_never_returns_notify(
    T, transfer_nodes, monkeypatch
):
    """AC-32 / spec D: Node gọi `links.hold(D, True)` khi có lượt dở với D và `hold(D, False)` khi hết,
    chỉ khi tập đổi; `hold` (được gọi trong lúc dispatch) không bao giờ trả `Notify`/`CloseConnection`."""
    R = T.TransferResult
    calls: list[tuple[str, bool, list]] = []
    real = core_links.LinkTracker.hold

    def hold(self, device_id, held, now):
        acts = real(self, device_id, held, now)
        calls.append((device_id, held, list(acts)))
        return acts

    monkeypatch.setattr(core_links.LinkTracker, "hold", hold)
    net = await transfer_nodes()
    A, B = net.A, net.B
    _, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 3 * MiB)])
    assert_finished(fin_a, R.DONE)
    assert_finished(fin_b, R.DONE)

    def seq(device_id: str) -> list[bool]:
        return [h for d, h, _ in calls if d == device_id]

    await wait_until(lambda: seq(A.id)[-1:] == [False] and seq(B.id)[-1:] == [False], 5, "chưa thả hold")
    assert seq(A.id) == [True, False], seq(A.id)  # B giữ A
    assert seq(B.id) == [True, False], seq(B.id)  # A giữ B
    for _, _, acts in calls:
        assert not any(isinstance(a, core_links.Notify | core_links.CloseConnection) for a in acts), acts


# =================================================================================================
# AC-19: thiết bị khác chen `data_open`
# =================================================================================================


async def _read_until_closed(conn, within: float) -> tuple[float, object]:
    start = time.monotonic()
    try:
        got = await asyncio.wait_for(conn.read_raw(1, at_boundary=True, idle_timeout=within + 2), within + 3)
    except connection.IdleTimeout:
        pytest.fail("A không đóng kết nối dữ liệu: bên mở chỉ thấy hết hạn chờ")
    except connection.ConnectionLostError:
        got = None
    return time.monotonic() - start, got


@pytest.mark.slow
@integration
@pytest.mark.parametrize("variant", ["c-mo-control", "khong-control", "a-mo-control"])
async def test_ac19_foreign_data_open_is_closed_and_transfer_unaffected(
    T, transfer_nodes, node_factory, control_client, send_spy, variant
):
    """AC-19 (spec B12): C (tin cậy với A) mở `data_open` mang đúng `transfer_id` của lượt A↔B.

    - 19a `c-mo-control`: C có kết nối điều khiển mà A là server → A gửi `cancel{unknown_transfer}`
      cho C rồi đóng kết nối dữ liệu ≤ 1 s.
    - 19b `khong-control` / `a-mo-control` (A mở control tới C, sai chiều): chỉ đóng ≤ 1 s, không
      gửi `cancel` nào.
    Lượt A↔B vẫn DONE.
    """
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE}, extra_trusted=("C",))
    A, B = net.A, net.B
    C = await node_factory("C")
    cc = None
    if variant == "c-mo-control":
        cc = await control_client(C, A)
        await wait_until(lambda: C.id in A.connected_devices(), 3, "A chưa ghi nhận C")
    elif variant == "a-mo-control":
        A.connect_hint(C.id, [LOCAL], C.port)
        await wait_until(lambda: C.id in A.connected_devices() and A.id in C.connected_devices(), 5)
        assert A.control_connection(C.id).is_server is False

    src = make_file(net.src, "f.bin", 8 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    conn = await connection.open_data(
        LOCAL, A.port, C.identity, C.hello, A.identity.cert_pem(), DataOpen(tid, 0, 1)
    )
    try:
        elapsed, got = await _read_until_closed(conn, 1.0)
    finally:
        conn.abort()
    assert got is None, f"A gửi dữ liệu cho C: {got!r}"
    assert elapsed <= 1.0, f"A đóng kết nối dữ liệu của C sau {elapsed:.2f} s"

    if cc is not None:
        await wait_until(
            lambda: any(
                isinstance(m, Cancel) and m.transfer_id == tid and m.reason == "unknown_transfer"
                for m in cc.received
            ),
            2,
            "C không nhận cancel{unknown_transfer}",
        )
    else:
        await asyncio.sleep(0.5)
        assert [m for m in send_spy.cancels(tid) if m.reason == "unknown_transfer"] == []

    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A.trec.wait_finished(tid, 60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


# =================================================================================================
# AC-21/22: close() giữa lượt; AC-23: unpair
# =================================================================================================


@pytest.mark.slow
@integration
async def test_ac22_sender_close_mid_transfer_cancels_receiver_quickly(
    T, transfer_nodes, write_spy, app_helpers
):
    """AC-22 (B gửi đóng): `close()` giữa lượt → A `CANCELLED_USER` (by_peer True) ≤ 1 s; B nhận
    `TransferFinished(CANCELLED_USER)` trước khi `close()` trả về và không còn sự kiện nào sau đó; A không
    giữ `.part` hay thư mục tạm; `node.lock` nhả. (P3-3b: phía gửi không đổi; phía nhận đóng thì tạm dừng,
    `test_ac21_receiver_close_mid_transfer_suspends`.)"""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")

    t0 = time.monotonic()
    await asyncio.wait_for(B.close(), 15)
    t_ret = time.monotonic()
    timed = B.trec.timed("TransferFinished", tid)
    assert timed, "bên đóng không nhận TransferFinished trong close()"
    assert timed[0][0] <= t_ret
    assert_finished(timed[0][1], R.CANCELLED_USER, by_peer=False)
    n = len(B.trec.updates)

    fin_a = await A.trec.wait_finished(tid, 5)
    assert_finished(fin_a, R.CANCELLED_USER, by_peer=True)
    t_other = A.trec.timed("TransferFinished", tid)[0][0]
    assert t_other - t0 <= 1.0, f"bên kia biết lượt bị hủy sau {t_other - t0:.2f} s"

    await asyncio.sleep(0.3)
    assert len(B.trec.updates) == n, "còn sự kiện sau khi close() trả về"
    assert app_helpers.lock_is_free(B.dir)
    await wait_until(lambda: not temp_dir(net, tid).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()


@pytest.mark.slow
@integration
async def test_ac21_receiver_close_mid_transfer_suspends(T, transfer_nodes, write_spy, send_spy, app_helpers):
    """AC-21 sửa ở P3-3b (spec-p3-3b mục 2.4, 5.2; protocol §6.2 “Tắt app nhận”): A nhận `close()` giữa
    lượt → A nhận đúng một `TransferFinished(SUSPENDED)` (by_peer False) trước khi `close()` trả về, không
    còn sự kiện nào sau đó; A không gửi `cancel`/`reject` nào của lượt; B thấy mất kết nối và chuyển sang
    “Đang nối lại…” (không kết thúc); thư mục tạm của A còn `transfer.json`, `0.part`, `0.state`; `node.lock`
    nhả."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": SLOW_RATE})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")

    await asyncio.wait_for(A.close(), 15)
    t_ret = time.monotonic()
    timed = A.trec.timed("TransferFinished", tid)
    assert len(timed) == 1, [describe(u) for _, u in timed]
    assert timed[0][0] <= t_ret
    assert_finished(timed[0][1], R.SUSPENDED, by_peer=False)
    n = len(A.trec.updates)

    await wait_until(lambda: "reconnecting" in B.trec.statuses(tid), 5, "B chưa chuyển sang “Đang nối lại…”")
    assert B.trec.finished(tid) is None, describe(B.trec.finished(tid))
    on_wire = [
        m for _, m in send_spy.sent if type(m).__name__ in ("Cancel", "Reject") and m.transfer_id == tid
    ]
    assert on_wire == [], f"A gửi {on_wire!r} cho lượt đang tạm dừng"

    await asyncio.sleep(0.3)
    assert len(A.trec.updates) == n, "còn sự kiện sau khi close() trả về"
    assert app_helpers.lock_is_free(A.dir)
    left = set(os.listdir(temp_dir(net, tid)))
    assert {"transfer.json", "0.part", "0.state"} <= left, left
    assert received_names(net) == set()


@pytest.mark.slow
@integration
@pytest.mark.parametrize(
    ("unpairer", "phase"),
    [("A", "running"), ("B", "running"), ("A", "asking"), ("B", "asking")],
)
async def test_ac23_unpair_during_transfer(T, transfer_nodes, write_spy, fast, unpairer, phase):
    """AC-23 (kế hoạch mục 7.7, spec B8): bên hủy ghép đôi → `UNPAIRED` (cả khi lượt đang chờ quyết:
    xét `_unpaired` trước `outcome`); bên kia mất kết nối, không nối lại được → `EXPIRED` sau
    `RECONNECT_GRACE`. A không giữ thư mục tạm."""
    R = T.TransferResult
    net = await transfer_nodes({"auto_accept": phase == "running"}, {"rate_limit": SLOW_RATE})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 12 * MiB)])
    tid = key.transfer_id
    if phase == "running":
        await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")
    else:
        await A.trec.wait_kind("OfferReceived", tid)
    X, Y = (A, B) if unpairer == "A" else (B, A)
    await X.unpair(Y.id)
    fin_x = await X.trec.wait_finished(tid, 5)
    assert_finished(fin_x, R.UNPAIRED, by_peer=False)
    assert all(info.key.device_id != Y.id for info in X.transfers.transfers())
    fin_y = await Y.trec.wait_finished(tid, fast.RECONNECT_GRACE + 10)
    assert_finished(fin_y, R.EXPIRED, by_peer=False)
    await wait_until(lambda: not temp_dir(net, tid).exists(), 10, "thư mục tạm chưa được xóa")
    assert received_names(net) == set()


# =================================================================================================
# AC-24: hàng gửi điều khiển tràn
# =================================================================================================


@pytest.mark.slow
@integration
async def test_ac24_control_send_queue_overflow_closes_that_connection(
    T, transfer_nodes, send_spy, monkeypatch, caplog
):
    """AC-24 (spec B12): `CONTROL_SEND_QUEUE_MAX` nhỏ và `send` của đúng kết nối điều khiển B→A treo →
    hàng tràn → B cắt kết nối đó (WARNING, `DeviceDisconnected`); nối lại rồi mọi lượt vẫn DONE."""
    R = T.TransferResult
    caplog.set_level(logging.WARNING, logger="teleport")
    monkeypatch.setattr(T, "CONTROL_SEND_QUEUE_MAX", 2)
    net = await transfer_nodes()
    A, B = net.A, net.B
    target = B.control_connection(A.id)
    send_spy.hang = lambda conn, msg: conn is target and getattr(msg, "TYPE", None) in TRANSFER_TYPES
    keys = []
    for i in range(6):
        keys.append(await B.transfers.send(A.id, [make_file(net.src, f"f{i}.bin", 100_000 + i)]))
    await wait_until(lambda: target.closed, 5, "kết nối có hàng gửi tràn chưa bị cắt")
    await B.rec.wait_event(DeviceDisconnected, A.id, timeout=5)
    warnings_ = [r for r in teleport_records(caplog, logging.WARNING) if r.name.startswith("teleport.app")]
    assert warnings_, "không có WARNING khi hàng gửi tràn"
    for key in keys:
        assert_finished(await B.trec.wait_finished(key.transfer_id, 60), R.DONE)
        assert_finished(await A.trec.wait_finished(key.transfer_id, 60), R.DONE)
    assert received_names(net) == {f"f{i}.bin" for i in range(6)}


# =================================================================================================
# AC-26: lỗi của send(); decide/cancel sai kiểu; sau close
# =================================================================================================


@integration
async def test_ac26_send_errors_raise_before_anything_is_sent(T, transfer_nodes, app_helpers):
    """AC-26: lỗi bay ra trước khi gửi gì: máy này / `device_id` sai → ValueError; không tin cậy →
    KeyError; 0 hay > 1000 path, trùng path → ValueError; file thiếu / thư mục → `SourceError`; một
    chuỗi đơn → TypeError (spec A2)."""
    net = await transfer_nodes()
    A, B = net.A, net.B
    f = make_file(net.src, "f.bin", 10)
    tm = B.transfers
    with pytest.raises(ValueError):
        await tm.send(B.id, [f])
    with pytest.raises(ValueError):
        await tm.send("khong-phai-device-id", [f])
    with pytest.raises(KeyError):
        await tm.send(app_helpers.new_device_id(), [f])
    with pytest.raises(ValueError):
        await tm.send(A.id, [])
    with pytest.raises(ValueError):
        await tm.send(A.id, [net.src / f"x{i}" for i in range(1001)])
    with pytest.raises(ValueError):
        await tm.send(A.id, [f, f])
    with pytest.raises(ValueError):
        await tm.send(A.id, [f, str(f)])
    with pytest.raises(T.SourceError) as e:
        await tm.send(A.id, [net.src / "khong-co.bin"])
    assert e.value.kind == T.SourceErrorKind.NOT_FOUND
    with pytest.raises(T.SourceError) as e:
        await tm.send(A.id, [net.src])
    assert e.value.kind == T.SourceErrorKind.NOT_A_FILE
    with pytest.raises(TypeError):
        await tm.send(A.id, str(f))
    await asyncio.sleep(0.3)
    assert tm.transfers() == ()
    assert B.trec.updates == []
    assert A.trec.of("OfferReceived") == []


@integration
@pytest.mark.parametrize(("event", "error"), [("unpair", KeyError), ("close", RuntimeError)])
async def test_b5_send_rechecks_trust_and_closing_after_prepare_sources(
    T, transfer_nodes, monkeypatch, event, error
):
    """Spec B5: `send()` kiểm lại (đang chạy, không đang đóng, còn tin cậy) **sau** `await prepare_sources`,
    cùng khối đồng bộ với `engine.send`. Trong lúc `prepare_sources` (seam `sources.prepare_sources`)
    còn chạy, B hủy ghép đôi A → `KeyError`; hoặc B đóng → `RuntimeError`. Không `offer` nào tới A,
    B không còn lượt nào."""
    gate = Gate()
    real = sources.prepare_sources

    def slow_prepare(paths):
        gate.wait()
        return real(paths)

    monkeypatch.setattr(sources, "prepare_sources", slow_prepare)
    net = await transfer_nodes()
    A, B = net.A, net.B
    f = make_file(net.src, "f.bin", 1000)
    tm = B.transfers
    sending = asyncio.create_task(tm.send(A.id, [f]))
    closing = None
    try:
        await wait_until(gate.hit.is_set, 10, "send() chưa gọi prepare_sources")
        if event == "unpair":
            await B.unpair(A.id)
        else:
            closing = asyncio.create_task(B.close())
            await asyncio.sleep(0.2)  # để close() kịp bắt đầu đóng (begin_close)
    finally:
        gate.open.set()
    with pytest.raises(error):
        await asyncio.wait_for(sending, 15)
    if closing is not None:
        await asyncio.wait_for(closing, 15)
    await asyncio.sleep(0.3)
    assert A.trec.of("OfferReceived") == []
    assert tm.transfers() == ()
    assert B.trec.of("TransferFinished") == []


@integration
async def test_ac26_send_regenerates_transfer_id_in_use(T, transfer_nodes, monkeypatch):
    """Kế hoạch mục 3: `transfer_id = uuid4().hex` (seam `transfers.uuid4`), gặp `TransferIdInUse` thì
    sinh lại.

    Engine chỉ báo `TransferIdInUse` khi lượt cùng mã **chưa kết thúc** (lượt gửi đã xong không được nhớ,
    docstring `core/transfer.py`), nên A không tự nhận và chưa `decide`: lượt một chắc chắn còn chờ
    khi gọi `send` lần hai.
    """
    R = T.TransferResult
    ids = iter(["11" * 16, "11" * 16, "22" * 16])
    monkeypatch.setattr(T, "uuid4", lambda: SimpleNamespace(hex=next(ids)))
    net = await transfer_nodes({"auto_accept": False})
    A, B = net.A, net.B
    k1 = await B.transfers.send(A.id, [make_file(net.src, "a.bin", 1000)])
    assert B.transfers.get(k1) is not None, "lượt một phải còn chờ trả lời"
    k2 = await B.transfers.send(A.id, [make_file(net.src, "b.bin", 1000)])
    assert (k1.transfer_id, k2.transfer_id) == ("11" * 16, "22" * 16)
    assert A.trec.finished(k1.transfer_id) is None and B.trec.finished(k1.transfer_id) is None
    for k in (k1, k2):
        offer = await A.trec.wait_kind("OfferReceived", k.transfer_id, timeout=30)
        A.transfers.decide(offer.key, True)
    for k in (k1, k2):
        assert_finished(await B.trec.wait_finished(k.transfer_id), R.DONE)
        assert_finished(await A.trec.wait_finished(k.transfer_id), R.DONE)


@integration
async def test_decide_and_cancel_check_types_and_ignore_unknown_keys(T, transfer_nodes):
    """Kế hoạch mục 3: `key` không phải `TransferKey` hay `accept` không phải bool → TypeError; lượt
    không biết hay sai pha → bỏ qua."""
    net = await transfer_nodes()
    A, B = net.A, net.B
    unknown = T.TransferKey(B.id, T.Direction.RECEIVE, "cd" * 16)
    with pytest.raises(TypeError):
        A.transfers.decide("khong-phai-key", True)
    with pytest.raises(TypeError):
        A.transfers.decide(unknown, 1)
    with pytest.raises(TypeError):
        A.transfers.decide(unknown, None)
    with pytest.raises(TypeError):
        B.transfers.cancel(("x", "send", "cd" * 16))
    A.transfers.decide(unknown, True)
    A.transfers.cancel(unknown)
    B.transfers.cancel(T.TransferKey(A.id, T.Direction.SEND, "cd" * 16))
    A.transfers.cancel_all()
    assert A.transfers.get(unknown) is None
    assert A.transfers.get("khong-phai-key") is None


@integration
async def test_after_close_public_calls_are_noops_and_send_raises(T, transfer_nodes):
    """Spec B10: sau `close()` mọi lời gọi công khai là no-op, riêng `send` → RuntimeError; gọi `send`
    khi node đang đóng → RuntimeError, không gửi `offer`."""
    net = await transfer_nodes()
    A, B = net.A, net.B
    f = make_file(net.src, "f.bin", 10)
    tm = B.transfers
    closing = asyncio.create_task(B.close())
    await asyncio.sleep(0)
    with pytest.raises(RuntimeError):
        await tm.send(A.id, [f])
    await asyncio.wait_for(closing, 15)
    with pytest.raises(RuntimeError):
        await tm.send(A.id, [f])
    key = T.TransferKey(A.id, T.Direction.SEND, "ef" * 16)
    tm.cancel(key)
    tm.decide(T.TransferKey(A.id, T.Direction.RECEIVE, "ef" * 16), True)
    tm.cancel_all()
    assert tm.get(key) is None
    await asyncio.sleep(0.2)
    assert A.trec.of("OfferReceived") == []


# =================================================================================================
# AC-27: tiến độ; AC-28: giới hạn tốc độ; thuộc tính đọc/ghi
# =================================================================================================


@pytest.mark.slow
@integration
async def test_ac27_progress_events_are_periodic_monotonic_with_speed_and_eta(T, transfer_nodes, monkeypatch):
    """AC-27: `TransferProgress` theo chu kỳ `PROGRESS_INTERVAL` (vá 0,25 s), tốc độ ≥ 0 (có lúc > 0),
    không có sau `TransferFinished`. Spec hackathon PR-1 mục 1: phát khi `shown_bytes` đổi, hoặc mỗi nhịp
    khi lượt TRANSFERRING / RECONNECTING đứng yên (nên hai sự kiện liền nhau có thể cùng `shown_bytes`,
    chỉ ở hai trạng thái đó); `shown_bytes` không giảm, `done_bytes` không giảm; `eta = (total − shown) /
    speed` khi speed > 0."""
    R = T.TransferResult
    monkeypatch.setattr(T, "PROGRESS_INTERVAL", 0.25)
    monkeypatch.setattr(T, "SPEED_WINDOW", 1.0)
    rate = 8 * MiB
    net = await transfer_nodes(sender_opts={"rate_limit": rate})
    B = net.B
    key, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 24 * MiB)], timeout=60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    tid = key.transfer_id
    prog = B.trec.timed("TransferProgress", tid)
    assert len(prog) >= 3, f"chỉ có {len(prog)} sự kiện tiến độ cho lượt ~3 s"
    t_fin = B.trec.timed("TransferFinished", tid)[0][0]
    assert all(t <= t_fin for t, _ in prog), "còn tiến độ sau TransferFinished"
    done = [p.info.done_bytes for _, p in prog]
    assert all(b >= a for a, b in itertools.pairwise(done)), done
    shown = [p.shown_bytes for _, p in prog]
    assert all(b >= a for a, b in itertools.pairwise(shown)), shown
    assert shown[-1] > shown[0], shown
    for (_, a), (_, b) in itertools.pairwise(prog):
        if b.shown_bytes == a.shown_bytes:
            assert str(b.info.status) in ("transferring", "reconnecting"), (
                f"phát lại cùng shown_bytes ở trạng thái {b.info.status}"
            )
    gaps = [b - a for (a, _), (b, _) in itertools.pairwise(prog)]
    assert min(gaps) >= 0.1, f"tiến độ không theo chu kỳ: khoảng cách {gaps}"
    speeds = [p.bytes_per_second for _, p in prog]
    assert all(s >= 0 for s in speeds)
    assert any(s > 0 for s in speeds)
    assert max(speeds) <= 3 * rate, speeds
    for _, p in prog:
        assert p.info.key == key
        assert p.info.total_bytes == 24 * MiB
        if p.bytes_per_second > 0:
            assert p.eta == pytest.approx((p.info.total_bytes - p.shown_bytes) / p.bytes_per_second, rel=1e-6)
        else:
            assert p.eta is None


@pytest.mark.slow
@integration
async def test_ac28_rate_limit_8_mib_at_4_mib_per_second(T, transfer_nodes, frame_spy):
    """AC-28 (spec B12): 8 MiB @ 4 MiB/s: đo từ lúc bắt đầu khung khối đầu tới lúc ghi xong khung cuối;
    cận dưới 1,9 s (burst một đoạn 64 KiB), cận trên nới cho CI."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": 4 * MiB})
    assert net.B.transfers.rate_limit == 4 * MiB
    _, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 8 * MiB)], timeout=60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    frames = frame_spy.frames
    assert len(frames) == 8, [fr.index for fr in frames]
    elapsed = max(fr.t1 for fr in frames) - min(fr.t0 for fr in frames)
    assert 1.9 <= elapsed <= 6.0, f"8 MiB @ 4 MiB/s mất {elapsed:.2f} s"


@pytest.mark.slow
@integration
async def test_rate_limit_and_auto_accept_properties(T, transfer_nodes):
    """Kế hoạch mục 3: `rate_limit` đọc/ghi (None hoặc int ≥ `MIN_RATE_LIMIT`; sai → ValueError, giữ
    giá trị cũ); `auto_accept` đọc/ghi, có hiệu lực với `offer` mới."""
    R = T.TransferResult
    net = await transfer_nodes()
    A, B = net.A, net.B
    tm = B.transfers
    assert tm.rate_limit is None
    tm.rate_limit = T.MIN_RATE_LIMIT
    assert tm.rate_limit == T.MIN_RATE_LIMIT
    for bad in (0, -1, T.MIN_RATE_LIMIT - 1, 1.5, float(T.MIN_RATE_LIMIT), True, "65536"):
        with pytest.raises(ValueError):
            tm.rate_limit = bad
        assert tm.rate_limit == T.MIN_RATE_LIMIT
    tm.rate_limit = None
    assert tm.rate_limit is None

    assert A.transfers.auto_accept is True
    A.transfers.auto_accept = False
    assert A.transfers.auto_accept is False
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 1000)])
    offer = await A.trec.wait_kind("OfferReceived", key.transfer_id)
    assert offer.auto_accepted is False
    await asyncio.sleep(0.2)
    assert A.trec.finished(key.transfer_id) is None, "auto_accept=False mà vẫn tự nhận"
    A.transfers.decide(offer.key, True)
    assert_finished(await A.trec.wait_finished(key.transfer_id), R.DONE)


# =================================================================================================
# AC-30: hai lượt liền nhau; AC-31: hàng ghi có trần
# =================================================================================================


@pytest.mark.slow
@integration
async def test_ac30_two_sends_back_to_back_queue_then_both_done(T, transfer_nodes):
    """AC-30: hai `send` liền nhau tới cùng máy → lượt hai `QUEUED` (hai phía) rồi cả hai DONE; bên nhận
    chỉ chạy lượt hai sau khi lượt một kết thúc. B gửi 8 MiB/s để lượt một chắc chắn còn chạy khi gọi
    `send` lần hai."""
    R = T.TransferResult
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    f1 = make_file(net.src, "mot.bin", 6 * MiB)
    f2 = make_file(net.src, "hai.bin", 6 * MiB)
    k1 = await B.transfers.send(A.id, [f1])
    k2 = await B.transfers.send(A.id, [f2])
    for k in (k1, k2):
        assert_finished(await B.trec.wait_finished(k.transfer_id, 60), R.DONE)
        assert_finished(await A.trec.wait_finished(k.transfer_id, 60), R.DONE)
    assert "queued" in B.trec.statuses(k2.transfer_id), B.trec.statuses(k2.transfer_id)
    assert "queued" in A.trec.statuses(k2.transfer_id), A.trec.statuses(k2.transfer_id)
    t_done_1 = A.trec.timed("TransferFinished", k1.transfer_id)[0][0]
    running_2 = [
        t
        for t, u in A.trec.timed("TransferStatusChanged", k2.transfer_id)
        if str(u.info.status) == "transferring"
    ]
    assert running_2 and min(running_2) >= t_done_1, "bên nhận chạy hai lượt cùng lúc"
    assert sha256_of(net.receive_dir / "mot.bin") == sha256_of(f1)
    assert sha256_of(net.receive_dir / "hai.bin") == sha256_of(f2)


@pytest.mark.slow
@integration
async def test_ac31_write_queue_is_bounded_when_disk_is_slow(T, transfer_nodes, write_spy, monkeypatch):
    """AC-31 (spec B12): ghi đĩa chậm (khối đầu chờ một Event) → (số khối `read_block` đã trả − số
    `write_at` đã xong) không bao giờ vượt `WRITE_QUEUE_BLOCKS` + 1, và đạt tới `WRITE_QUEUE_BLOCKS`
    (bên nhận vẫn đọc trước tới trần)."""
    R = T.TransferResult
    gate = Gate()
    state = SimpleNamespace(reads=0, max_out=0)
    real_read = connection.Connection.read_block

    async def read_block(self, *args, **kwargs):
        result = await real_read(self, *args, **kwargs)
        if result is not None:
            state.reads += 1
            with write_spy.lock:
                written = len(write_spy.done)
            state.max_out = max(state.max_out, state.reads - written)
        return result

    monkeypatch.setattr(connection.Connection, "read_block", read_block)
    first: list[bool] = []

    def slow(part, index):
        if not first:
            first.append(True)
            gate.wait()

    write_spy.hooks.append(slow)
    net = await transfer_nodes()
    src = make_file(net.src, "f.bin", 20 * MiB)
    try:
        key = await net.B.transfers.send(net.A.id, [src])
        await wait_until(gate.hit.is_set, 20, "chưa ghi khối nào")
        await asyncio.sleep(1.5)
        bound = T.WRITE_QUEUE_BLOCKS + 1
        assert state.max_out <= bound, f"{state.max_out} khối đã nhận mà chưa ghi (trần {bound})"
        assert state.max_out >= T.WRITE_QUEUE_BLOCKS, f"chỉ đọc trước {state.max_out} khối"
    finally:
        gate.open.set()
    fin_b = await net.B.trec.wait_finished(key.transfer_id, 60)
    fin_a = await net.A.trec.wait_finished(key.transfer_id, 60)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert state.max_out <= T.WRITE_QUEUE_BLOCKS + 1
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


# =================================================================================================
# AC-33: tường lửa chặn kết nối dữ liệu; AC-34: IdentityMismatch khi mở kết nối dữ liệu
# =================================================================================================


@pytest.mark.slow
@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac33_firewall_reports_data_unreachable_once_then_recovers(
    T, transfer_nodes, open_data_spy, client
):
    """AC-33: mở kết nối dữ liệu luôn lỗi (`Unreachable`) → bên mở (client) báo đúng một
    `DataUnreachable(device_id)` sau `DATA_FAIL_REPORT_AFTER` lần, lượt sang RECONNECTING và vẫn thử lại;
    hết chặn thì DONE, không báo thêm."""
    R = T.TransferResult
    open_data_spy.fail = lambda n: connection.Unreachable("giả lập tường lửa")
    net = await transfer_nodes(client=client)
    A, B = net.A, net.B
    opener, other = (B, A) if client == "sender" else (A, B)
    src = make_file(net.src, "f.bin", 3 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: len(open_data_spy.of(tid)) >= 6, 20, "chưa thử mở kết nối dữ liệu đủ 6 lần")
    reports = opener.trec.of("DataUnreachable")
    assert len(reports) == 1, reports
    assert isinstance(reports[0], T.DataUnreachable) and reports[0].device_id == other.id
    assert other.trec.of("DataUnreachable") == []
    assert "reconnecting" in opener.trec.statuses(tid)
    assert {(c.address, c.port) for c in open_data_spy.of(tid)} == {(LOCAL, other.port)}

    open_data_spy.fail = None
    fin_b = await B.trec.wait_finished(tid, 30)
    fin_a = await A.trec.wait_finished(tid, 30)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert len(opener.trec.of("DataUnreachable")) == 1
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


@integration
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_ac34_identity_mismatch_on_data_closes_control_then_reconnects(
    T, transfer_nodes, open_data_spy, caplog, client
):
    """AC-34: lần mở kết nối dữ liệu đầu ném `IdentityMismatch` → bên mở cắt kết nối điều khiển đó
    (WARNING), nối lại (còn lượt dở) và lượt vẫn DONE."""
    R = T.TransferResult
    caplog.set_level(logging.WARNING, logger="teleport")
    open_data_spy.fail = lambda n: (
        connection.IdentityMismatch("giả lập sai danh tính", actual_fingerprint="00" * 32) if n == 0 else None
    )
    net = await transfer_nodes(client=client)
    A, B = net.A, net.B
    opener, other = (B, A) if client == "sender" else (A, B)
    first = opener.control_connection(other.id)
    src = make_file(net.src, "f.bin", 3 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: first.closed, 10, "kết nối điều khiển chưa bị cắt sau IdentityMismatch")
    await opener.rec.wait_event(DeviceDisconnected, other.id, timeout=5)
    warnings_ = [r for r in teleport_records(caplog, logging.WARNING) if r.name.startswith("teleport.app")]
    assert warnings_, "không có WARNING khi sai danh tính trên kết nối dữ liệu"
    fin_b = await B.trec.wait_finished(tid, 30)
    fin_a = await A.trec.wait_finished(tid, 30)
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


# =================================================================================================
# Callback sự kiện, log (mvp N9)
# =================================================================================================


@integration
async def test_decide_called_inside_event_callback_finishes(T, transfer_nodes):
    """Kế hoạch 2.7: giao diện gọi `decide` ngay trong `on_transfer_event` (lời gọi trong lúc dispatch
    được xếp hàng, không gọi engine lồng) → lượt chạy bình thường."""
    R = T.TransferResult
    net = await transfer_nodes({"auto_accept": False})
    A = net.A

    def accept(u):
        if type(u).__name__ == "OfferReceived":
            A.transfers.decide(u.key, True)

    A.trec.hooks.append(accept)
    _, fin_a, fin_b = await run_transfer(net, [make_file(net.src, "f.bin", 2 * MiB)])
    assert_finished(fin_a, R.DONE)
    assert_finished(fin_b, R.DONE)


@integration
async def test_event_callback_raising_does_not_break_transfer(T, transfer_nodes, caplog):
    """Kế hoạch 2.7 (`Report`): callback raise thì chỉ ghi log; lượt vẫn DONE."""
    R = T.TransferResult
    net = await transfer_nodes()
    net.A.trec.raise_in_event = True
    net.B.trec.raise_in_event = True
    src = make_file(net.src, "f.bin", 2 * MiB)
    _, fin_a, fin_b = await run_transfer(net, [src])
    assert_finished(fin_a, R.DONE)
    assert_finished(fin_b, R.DONE)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


@integration
async def test_logs_never_contain_file_names_or_paths(T, transfer_nodes, monkeypatch, caplog):
    """mvp N9, kế hoạch 2.7, spec C6: log (cả DEBUG) không bao giờ chứa tên hay đường dẫn file, kể cả
    khi `OSError` mang đường dẫn (chỉ log `type(e).__name__`/`errno`)."""
    caplog.set_level(logging.DEBUG, logger="teleport")
    net = await transfer_nodes()
    secret = "BiMatQx7"
    ok = make_file(net.src, f"{secret}-ok.bin", 2 * MiB)
    _, fin_a, _ = await run_transfer(net, [ok])
    assert fin_a.result == T.TransferResult.DONE

    real = sources.SourceReader.read_block

    def read_block(self, index):
        if index == 1:
            raise OSError(errno.EIO, "giả lập lỗi đọc", str(self.path))
        return real(self, index)

    monkeypatch.setattr(sources.SourceReader, "read_block", read_block)
    bad = make_file(net.src, f"{secret}-loi.bin", 3 * MiB)
    _, _, fin_b = await run_transfer(net, [bad])
    assert fin_b.result == T.TransferResult.SOURCE_READ_FAILED
    leaks = []
    for r in caplog.records:
        text = r.getMessage() + (r.exc_text or "")
        if r.exc_info and not r.exc_text:
            text += logging.Formatter().formatException(r.exc_info)
        if secret in text or str(net.src) in text:
            leaks.append(f"{r.name} {r.levelname}: {text[:200]}")
    assert leaks == [], "log chứa tên/đường dẫn file:\n" + "\n".join(leaks)


# =================================================================================================
# P2-7 (plan-p2-7 mục 2.2 bước 3, mục 3): `preview_sources(paths)` — kiểm file nguồn trước khi lấy
# khóa/đụng mạng; chạy `sources.prepare_sources` trên một `DiskExecutor` dùng một lần (thread daemon),
# cùng lỗi như `send()`; bị hủy → bỏ việc và đóng executor.
# =================================================================================================


async def test_p27_preview_sources_returns_entries_in_order(T, tmp_path):
    a = make_file(tmp_path, "a.bin", 1000)
    empty = make_file(tmp_path, "rong.txt", 0)
    found = await T.preview_sources([a, empty])
    assert [f.entry.name for f in found] == ["a.bin", "rong.txt"]
    assert [f.entry.size for f in found] == [1000, 0]
    assert [f.path for f in found] == [Path(os.path.abspath(a)), Path(os.path.abspath(empty))]


async def test_p27_preview_sources_raises_same_errors_as_send(T, tmp_path):
    a = make_file(tmp_path, "a.bin", 10)
    with pytest.raises(T.SourceError) as e:
        await T.preview_sources([tmp_path / "khong-co.bin"])
    assert e.value.kind is T.SourceErrorKind.NOT_FOUND
    folder = tmp_path / "anh"
    folder.mkdir()
    with pytest.raises(T.SourceError) as e:
        await T.preview_sources([a, folder])
    assert e.value.kind is T.SourceErrorKind.NOT_A_FILE
    with pytest.raises(ValueError):
        await T.preview_sources([a, a])


async def test_p27_preview_sources_runs_off_the_loop_in_daemon_thread(T, tmp_path, monkeypatch):
    seen: list[threading.Thread] = []
    real = sources.prepare_sources

    def spy(paths):
        seen.append(threading.current_thread())
        return real(paths)

    monkeypatch.setattr(sources, "prepare_sources", spy)
    await T.preview_sources([make_file(tmp_path, "a.bin", 10)])
    [thread] = seen
    assert thread is not threading.main_thread() and thread.daemon


async def test_p27_preview_sources_cancel_returns_promptly(T, tmp_path, monkeypatch):
    """Ổ mạng treo: `preview_sources` không có hạn, nhưng hủy (Ctrl+C) phải trả về ngay."""
    entered = threading.Event()
    release = threading.Event()

    def stuck(paths):
        entered.set()
        release.wait(30)
        raise OSError("đã thả")

    monkeypatch.setattr(sources, "prepare_sources", stuck)
    task = asyncio.create_task(T.preview_sources([tmp_path / "a.bin"]))
    try:
        await wait_until(entered.is_set, 5, "prepare_sources chưa được gọi")
        t0 = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert time.monotonic() - t0 < 1.0
    finally:
        release.set()


# =================================================================================================
# P3-3a (specs/spec-p3-3a.md mục 2.4, việc V6): bên nhận ghi `transfer.json` và `.state` khi nhận
# =================================================================================================


def _state_of(part) -> Path:
    return part.path.with_name(f"{part.file_index}.state")


@pytest.mark.slow
@integration
async def test_p33a_transfer_json_durable_before_sender_sees_transferring_and_marks_grow(
    T, transfer_nodes, monkeypatch, resume_helpers
):
    """V6: khi B thấy TRANSFERRING (A đã `accept`), `transfer.json` của A đã có và giải mã được, đúng
    máy nhận / máy gửi / manifest; mỗi lô `SyncPart` (`PartFile.commit`) để lại `0.state` có header hợp
    lệ và số `MARK` tăng dần; xong thì `.teleport/<tid>` chỉ còn `transfer.json` có `done_at` (P3-3b)."""
    R = T.TransferResult
    net = await transfer_nodes()
    A, B = net.A, net.B
    seen: list[object] = []

    def on_transferring(u):
        if (
            not seen
            and type(u).__name__ == "TransferStatusChanged"
            and u.info.key.direction == T.Direction.SEND
            and u.info.status == T.TransferStatus.TRANSFERRING
        ):
            t = u.info.key.transfer_id
            try:
                seen.append(
                    rs.decode_transfer_record((temp_dir(net, t) / "transfer.json").read_bytes(), dir_name=t)
                )
            except Exception as e:  # ghi lại để khẳng định bên dưới
                seen.append(e)

    B.trec.hooks.append(on_transferring)
    commits: list[tuple[int, bytes, int, int]] = []
    real_commit = storage.PartFile.commit

    def commit(self, blocks):
        real_commit(self, blocks)
        header, records = resume_helpers.parse_state(_state_of(self).read_bytes())
        commits.append((self.file_index, header, sum(1 for r in records if r[0] == "mark"), len(blocks)))

    monkeypatch.setattr(storage.PartFile, "commit", commit)
    size = 40 * MiB + 5
    src = make_file(net.src, "lon.bin", size, mtime_ns=1_600_000_000_123_456_789)
    key, fin_a, fin_b = await run_transfer(net, [src])
    tid = key.transfer_id
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert sha256_of(net.receive_dir / "lon.bin") == sha256_of(src)

    assert len(seen) == 1, "B không thấy TRANSFERRING"
    rec = seen[0]
    assert isinstance(rec, rs.TransferRecord), (
        f"transfer.json chưa có hay hỏng lúc B thấy TRANSFERRING: {rec!r}"
    )
    assert (rec.receiver, rec.sender) == (A.id, B.id)
    assert rec.offer.transfer_id == tid
    assert rec.offer.files == (FileEntry("lon.bin", size, 1_600_000_000_123),)
    assert (rec.verified, rec.done_at) == (0, None)

    batches = [c for c in commits if c[3] > 0]
    assert len(batches) >= 3, commits  # 41 khối, lô 16 khối
    assert all(c[0] == 0 and c[1] == rs.encode_header(tid, 0, size) for c in batches)
    counts = [c[2] for c in batches]
    assert all(b > a for a, b in itertools.pairwise(counts)), f"số MARK không tăng: {counts}"
    await wait_done_record(net, tid)


@pytest.mark.slow
@integration
async def test_p33a_part_byte_flipped_before_reread_appends_clear(
    T, transfer_nodes, monkeypatch, resume_helpers
):
    """V6: lật 1 byte khối 2 của `.part` ngay trước lượt đọc lại → A thấy khối sai, nối `CLEAR` khối đó
    vào `0.state` (`ClearBlocks`), nhận lại khối 2 rồi xong; nội dung đúng nguồn."""
    R = T.TransferResult
    net = await transfer_nodes()
    real_reread = storage.PartFile.reread
    flipped: list[bool] = []

    def reread(self, *, stop=None):
        if not flipped and self.file_index == 0:
            flipped.append(True)
            with open(self.path, "r+b") as f:
                f.seek(2 * MiB + 3)
                b = f.read(1)
                f.seek(2 * MiB + 3)
                f.write(bytes([b[0] ^ 0xFF]))
        return real_reread(self, stop=stop)

    states: list[bytes] = []
    real_finalize = storage.ReceiveDir.finalize

    def finalize(self, part, name, **kwargs):
        states.append(_state_of(part).read_bytes())
        return real_finalize(self, part, name, **kwargs)

    monkeypatch.setattr(storage.PartFile, "reread", reread)
    monkeypatch.setattr(storage.ReceiveDir, "finalize", finalize)
    src = make_file(net.src, "f.bin", 6 * MiB)
    key, fin_a, fin_b = await run_transfer(net, [src])
    assert_finished(fin_b, R.DONE)
    assert_finished(fin_a, R.DONE)
    assert flipped
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)
    assert len(states) == 1
    _, records = resume_helpers.parse_state(states[0])
    clears = [i for i, r in enumerate(records) if r[0] == "clear"]
    assert clears and records[clears[0]] == ("clear", [2]), records
    remarked = [r for r in records[clears[0] + 1 :] if r[0] == "mark" and any(i == 2 for i, _ in r[1])]
    assert remarked, "khối 2 phải được đánh dấu lại sau CLEAR"
    await wait_done_record(net, key.transfer_id)
