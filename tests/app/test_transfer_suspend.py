"""Tạm dừng lượt nhận khi đóng node có trật tự, `keep_record`, `payload_sent` (P3-3b, việc V2 (b), (d), V3).

Viết từ đặc tả, không từ code: `specs/spec-p3-3b.md` mục 2.1 (`TransferResult.SUSPENDED`,
`TransferFinished.payload_sent`, `TransferResumed`), 2.4 (tạm dừng: `begin_close` gọi
`suspend_receiving` trước rồi mới hủy lượt gửi và `offer` chờ; `SuspendTemp` chạy sau các thao tác đứng
trước trong hàng đĩa; `close_temp` thay `remove_temp`; `RemoveTemp.keep_record`), 2.5 (`payload_sent`), 5
(V2 (b), (d); V3: đóng trật tự giữa lượt → mở lại → hoàn tất trong ngưỡng mvp N4; S1), 8.1 mục 2, 5;
`specs/spec-p3.md` mục P3-3b (“Xong khi”, S1); protocol §6.2 (“Tắt app nhận”).

Quy ước như `test_transfers.py`: hai node thật trên 127.0.0.1 (`transfer_nodes`), **A nhận, B gửi**. Mở
lại một node = `node_factory` cùng nhãn (cùng thư mục cấu hình) với `TransferRecorder` mới. Hạn chờ nối
lại đặt lại giá trị thật (24 giờ) để lượt không hết hạn trong lúc A tắt (fixture `fast` đặt 4 s).

P3-5 (`specs/spec-p3-5.md` V5, V6, V7, V8 (ii); mục 9 thắng 1–8): đóng trật tự lúc proxy chặn ở 85 % của
96 MiB rồi mở lại, trong ngưỡng mvp N4 (`n4_extra`, đọc từ `docs/mvp.md`; tiền đề `byte lúc cắt >
n4_extra`); lật một byte `.part` của khối đã `MARK` khi tạm dừng → đúng khối đó được gửi lại (mvp F7 AC3,
N5); lật một byte `.state` (MARK đầu, MARK cuối, header; mục 9.2 C4); nguồn đổi lúc bên nhận tạm dừng
(mvp F6 AC4). Byte payload bên gửi và chỉ số khối được đếm qua `payload_meter` (`tests/app/conftest.py`).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import random
import struct
import threading
import time
import uuid
import zlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from support import wait_until

from teleport.app import storage
from teleport.core import transfer as core_transfer
from teleport.core.blocks import BLOCK_SIZE
from teleport.core.merkle import merkle_root
from teleport.core.messages import Cancel, Complete, DataOpen, FileEntry, Offer, Reject, Resume
from teleport.net import connection

pytestmark = [
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
integration = pytest.mark.integration
leakcheck = pytest.mark.usefixtures("no_leaks")


LOCAL = "127.0.0.1"
MiB = 1024 * 1024
REAL_GRACE = core_transfer.RECONNECT_GRACE  # đọc lúc import, trước khi `fast` vá


# --- Hàm phụ trợ ---------------------------------------------------------------------------------


def make_file(directory: Path, name: str, size: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    with open(path, "wb") as f:
        left = size
        while left:
            chunk = os.urandom(min(left, 4 * MiB))
            f.write(chunk)
            left -= len(chunk)
    return path


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(4 * MiB):
            h.update(chunk)
    return h.hexdigest()


async def wait_gone(path: Path, timeout: float = 20.0) -> None:
    """Chờ tới khi thư mục tạm `path` không còn; quá hạn thì báo các file còn lại (để chẩn đoán)."""
    deadline = time.monotonic() + timeout
    while path.exists():
        if time.monotonic() > deadline:
            try:
                left = sorted(os.listdir(path))
            except OSError as e:
                left = [f"<không liệt kê được: {type(e).__name__}>"]
            raise AssertionError(f"hết {timeout} s mà thư mục tạm của lượt chưa bị xóa; còn: {left}")
        await asyncio.sleep(0.05)


# Cảnh báo của `TransferManager.close` khi hàng đĩa chưa xong trong `CLOSE_DISK_WAIT` (thư mục nhận chỉ
# được đóng sau, khi thread đĩa xong: spec-fix-app 1b): test mở lại ngay sau `close` thì đụng file còn mở
# (Windows giữ khóa file), nên `close_cleanly` coi đó là lỗi.
CLOSE_WARNINGS = ("việc dọn đĩa chưa xong", "đóng thư mục nhận sau khi thread đĩa xong")


async def close_cleanly(node, caplog, timeout: float = 45.0) -> None:
    """Đóng `node` (test đã nới `transfers.CLOSE_DISK_WAIT`) rồi khẳng định hàng đĩa xong trước hạn: không
    có cảnh báo `CLOSE_WARNINGS` của `teleport.app.transfers`."""
    caplog.set_level(logging.WARNING, logger="teleport.app.transfers")
    start = len(caplog.records)
    await asyncio.wait_for(node.close(), timeout)
    bad = [
        r.getMessage()
        for r in caplog.records[start:]
        if r.name == "teleport.app.transfers" and any(w in r.getMessage() for w in CLOSE_WARNINGS)
    ]
    assert not bad, f"đóng node mà hàng đĩa chưa xong: {bad}"


def temp_dir(receive_dir: Path, tid: str) -> Path:
    return receive_dir / ".teleport" / tid


def describe(fin) -> str:
    if fin is None:
        return "chưa có TransferFinished"
    return f"result={fin.result} by_peer={fin.by_peer} reason={fin.reason} file_index={fin.file_index}"


def marked_blocks(resume_helpers, state: Path) -> set[int]:
    """Các khối đang được đánh dấu trong `.state` (MARK trừ CLEAR/CLEAR_ALL sau đó), đọc độc lập."""
    _, records = resume_helpers.parse_state(state.read_bytes())
    marked: set[int] = set()
    for r in records:
        if r[0] == "mark":
            marked |= {i for i, _ in r[1]}
        elif r[0] == "clear":
            marked -= set(r[1])
        elif r[0] == "clear_all":
            marked.clear()
    return marked


@pytest.fixture
def T():
    from teleport.app import transfers

    return transfers


@pytest.fixture
def grace_real(monkeypatch):
    """Hạn chờ nối lại thật (24 giờ): lượt không hết hạn trong lúc một bên tắt."""
    monkeypatch.setattr(core_transfer, "RECONNECT_GRACE", REAL_GRACE)


@pytest.fixture
def restart(node_factory, app_helpers):
    """`await restart(label, **node_kwargs)` → `AppNode` mới cùng thư mục cấu hình, có `trec` mới."""

    async def make(label: str, **node_kwargs):
        trec = app_helpers.TransferRecorder(f"{label}'")
        node_kwargs.setdefault("on_transfer_event", trec.on_update)
        node = await node_factory(label, node_kwargs=node_kwargs)
        node.trec = trec
        return node

    return make


@pytest.fixture
def write_spy(monkeypatch):
    """Spy trên `storage.PartFile.write_at`: `done` = (transfer_id, file_index, index) mỗi lần ghi xong;
    `hooks`: hàm `(part, index)` chạy trong thread đĩa trước khi ghi thật."""
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
def temp_spy(monkeypatch):
    """Spy trên `ReceiveDir.close_temp` / `remove_temp`: (tên lệnh, transfer_id, keep_record)."""
    calls: list[tuple[str, str, bool | None]] = []
    real_close, real_remove = storage.ReceiveDir.close_temp, storage.ReceiveDir.remove_temp

    def close_temp(self, temp):
        calls.append(("close_temp", temp.path.name, None))
        return real_close(self, temp)

    def remove_temp(self, temp, *, keep_record=False):
        calls.append(("remove_temp", temp.path.name, keep_record))
        return real_remove(self, temp, keep_record=keep_record)

    monkeypatch.setattr(storage.ReceiveDir, "close_temp", close_temp)
    monkeypatch.setattr(storage.ReceiveDir, "remove_temp", remove_temp)
    return calls


@pytest.fixture
def wire_spy(monkeypatch):
    """Spy trên `Connection.send`: mọi (kết nối, message) đã đưa ra kết nối điều khiển, cả hai node."""
    sent: list[tuple[object, object]] = []
    real = connection.Connection.send

    async def send(self, msg):
        sent.append((self, msg))
        return await real(self, msg)

    monkeypatch.setattr(connection.Connection, "send", send)
    return sent


def cancels_or_rejects(sent, tid: str) -> list:
    return [m for _, m in sent if isinstance(m, Cancel | Reject) and m.transfer_id == tid]


# =================================================================================================
# API (không socket)
# =================================================================================================


def test_transfer_finished_payload_sent_defaults_to_zero(T):
    info = core_transfer.TransferInfo(
        key=core_transfer.TransferKey("a" * 32, core_transfer.Direction.SEND, "b" * 32),
        status=core_transfer.TransferStatus.TRANSFERRING,
        files=(FileEntry("x.bin", 1, 0),),
        names=("x.bin",),
        file_index=0,
        done_bytes=0,
        total_bytes=1,
    )
    fin = T.TransferFinished(info, T.TransferResult.DONE, False, None, None, None)
    assert fin.payload_sent == 0
    assert T.TransferResumed(info).info is info


def test_transfer_resumed_is_part_of_transfer_update(T):
    assert T.TransferResumed in T.TransferUpdate.__args__


def test_wall_time_seam_defaults_to_time_time(T):
    """Seam giờ tường (spec-p3-3b mục 2.1): tuổi lượt khôi phục, `at` của bia mộ, `wall_now` của dọn tạm."""
    assert T._wall_time is time.time


# =================================================================================================
# V2 (d): `payload_sent`
# =================================================================================================


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("rate", [None, 16 * MiB], ids=["khong-gioi-han", "gioi-han"])
async def test_payload_sent_of_clean_transfer_is_size_within_one_chunk_receiver_zero(T, transfer_nodes, rate):
    sizes = [0, MiB, 3 * MiB + 7]
    net = await transfer_nodes(sender_opts={"rate_limit": rate} if rate else None)
    A, B = net.A, net.B
    files = [make_file(net.src, f"f{k}.bin", size) for k, size in enumerate(sizes)]
    key = await B.transfers.send(A.id, files)
    fin_b = await B.trec.wait_finished(key.transfer_id, 60)
    fin_a = await A.trec.wait_finished(key.transfer_id, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    total = sum(sizes)
    assert total <= fin_b.payload_sent <= total + connection._SEND_CHUNK, fin_b.payload_sent
    assert fin_a.payload_sent == 0


@pytest.mark.slow
@integration
@leakcheck
async def test_payload_sent_after_sender_cancel_counts_at_least_what_receiver_wrote(
    T, transfer_nodes, write_spy
):
    net = await transfer_nodes(sender_opts={"rate_limit": 4 * MiB})
    A, B = net.A, net.B
    size = 16 * MiB
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", size)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid, done=True) >= 3, 20, "A chưa ghi khối nào")
    B.transfers.cancel(key)
    fin_b = await B.trec.wait_finished(tid, 10)
    assert fin_b.result == T.TransferResult.CANCELLED_USER
    written = write_spy.count(tid, done=True) * BLOCK_SIZE
    assert written <= fin_b.payload_sent <= size + connection._SEND_CHUNK, (written, fin_b.payload_sent)


# =================================================================================================
# V2 (b): tạm dừng, `keep_record`
# =================================================================================================


@integration
@leakcheck
async def test_done_transfer_removes_temp_with_keep_record_and_keeps_only_transfer_json(
    T, transfer_nodes, temp_spy
):
    net = await transfer_nodes()
    A, B = net.A, net.B
    src = make_file(net.src, "f.bin", 2 * MiB + 1)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    assert (await A.trec.wait_finished(tid, 30)).result == T.TransferResult.DONE
    await wait_until(lambda: any(c[1] == tid for c in temp_spy), 10, "chưa dọn thư mục tạm")
    assert [c for c in temp_spy if c[1] == tid] == [("remove_temp", tid, True)]
    d = temp_dir(net.receive_dir, tid)
    await wait_until(lambda: d.is_dir() and os.listdir(d) == ["transfer.json"], 10, "chỉ còn transfer.json")
    from teleport.core import resume_state as rs

    rec = rs.decode_transfer_record((d / "transfer.json").read_bytes(), dir_name=tid)
    assert rec.verified == 1 and rec.done_at is not None
    assert (rec.receiver, rec.sender) == (A.id, B.id)


@pytest.mark.slow
@integration
@leakcheck
async def test_cancelled_transfer_removes_temp_without_keep_record(T, transfer_nodes, temp_spy, write_spy):
    net = await transfer_nodes(sender_opts={"rate_limit": 4 * MiB})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa nhận khối nào")
    A.transfers.cancel(core_transfer.TransferKey(B.id, core_transfer.Direction.RECEIVE, tid))
    await wait_until(lambda: not temp_dir(net.receive_dir, tid).exists(), 10, "thư mục tạm chưa bị xóa")
    assert [c for c in temp_spy if c[1] == tid] == [("remove_temp", tid, False)]


@pytest.mark.slow
@integration
@leakcheck
async def test_suspend_runs_queued_writes_and_sync_then_only_closes_handles(
    T, transfer_nodes, write_spy, temp_spy, resume_helpers, grace_real, monkeypatch
):
    """Hàng đĩa đang kẹt ở một lần ghi khi node đóng: các `WriteBlock` và `SyncPart` đứng trước `SuspendTemp`
    vẫn chạy (không bị bỏ), nên mọi khối đã ghi xong đều có `MARK` bền trong `.state`; rồi chỉ `close_temp`,
    không `remove_temp`; `.part`, `.state`, `transfer.json` còn.

    `CLOSE_DISK_WAIT` nới rộng: ca này kiểm thao tác không bị bỏ, không kiểm thời gian (hàng đĩa chạy nốt
    quá `CLOSE_DISK_WAIT` thì mất `MARK` lô cuối là rủi ro R5 đã chấp nhận, spec-p3-3b mục 6)."""
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 24 * MiB)])
    tid = key.transfer_id
    gate = threading.Event()
    hit = threading.Event()

    def hold_block_5(part, index):
        if part.path.parent.name == tid and index == 5 and not hit.is_set():
            hit.set()
            gate.wait(30)

    read: list[int] = []  # chỉ số các khung A đã đọc được (mỗi khung → một `WriteBlock` xếp hàng)
    real_read = connection.Connection.read_block

    async def read_block(self, *args, **kwargs):
        result = await real_read(self, *args, **kwargs)
        if result is not None:
            read.append(result[0].index)
        return result

    monkeypatch.setattr(connection.Connection, "read_block", read_block)
    write_spy.hooks.append(hold_block_5)
    await wait_until(hit.is_set, 20, "chưa tới khối 5")
    await wait_until(lambda: max(read, default=0) >= 8, 10, "chưa có khối nào xếp sau khối 5")
    closing = asyncio.create_task(A.close())
    try:
        await A.trec.wait_kind("TransferFinished", tid, timeout=5)
        assert A.trec.finished(tid).result == T.TransferResult.SUSPENDED
        gate.set()  # trong CLOSE_DISK_WAIT: hàng đĩa chạy nốt
        await asyncio.wait_for(closing, 15)
    finally:
        gate.set()
    d = temp_dir(net.receive_dir, tid)
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(d))
    written = {r[2] for r in write_spy.done if r[0] == tid and r[1] == 0}
    assert 5 in written and max(written) > 5
    assert marked_blocks(resume_helpers, d / "0.state") == written, "mọi khối đã ghi phải có MARK bền"
    mine = [c for c in temp_spy if c[1] == tid]
    assert mine == [("close_temp", tid, None)], mine


@pytest.mark.slow
@integration
@leakcheck
async def test_begin_close_suspends_receiving_before_cancelling_sends_and_pending_offers(
    T, transfer_nodes, node_factory, app_helpers, wire_spy, write_spy, grace_real, tmp_path
):
    """A vừa nhận (từ B, đang chạy) vừa gửi (cho B) và có `offer` chờ hỏi (từ C): đóng A → lượt nhận
    `SUSPENDED` (không `cancel`), lượt gửi `cancel{user}`, `offer` chờ hỏi `reject{user}` (spec mục 8.1.4);
    `SUSPENDED` được báo trước các kết quả kia."""
    net = await transfer_nodes(
        receiver_opts={"auto_accept": False, "rate_limit": MiB},
        sender_opts={"rate_limit": 4 * MiB, "receive_dir": tmp_path / "nhan-B", "auto_accept": True},
        extra_trusted=("C",),
    )
    A, B = net.A, net.B
    crec = app_helpers.TransferRecorder("C")
    C = await node_factory("C", node_kwargs={"on_transfer_event": crec.on_update})
    C.connect_hint(A.id, [LOCAL], A.port)
    # 15 s: runner CI chạy -n auto có lúc mất quá 5 s mới xong bắt tay TLS hai chiều.
    await wait_until(lambda: C.id in A.connected_devices(), 15, "C chưa nối tới A")
    recv_key = await B.transfers.send(A.id, [make_file(net.src, "lon.bin", 16 * MiB)])
    offer = await A.trec.wait_kind("OfferReceived", recv_key.transfer_id)
    A.transfers.decide(offer.key, True)
    await wait_until(lambda: write_spy.count(recv_key.transfer_id) >= 2, 20, "A chưa nhận khối nào")
    waiting_key = await C.transfers.send(A.id, [make_file(net.src / "c", "c.bin", MiB)])
    await A.trec.wait_kind("OfferReceived", waiting_key.transfer_id)
    send_key = await A.transfers.send(B.id, [make_file(net.src / "a", "a.bin", 8 * MiB)])

    await asyncio.wait_for(A.close(), 15)
    results = {u.info.key.transfer_id: u for u in A.trec.of("TransferFinished")}
    assert results[recv_key.transfer_id].result == T.TransferResult.SUSPENDED
    assert results[send_key.transfer_id].result == T.TransferResult.CANCELLED_USER
    assert results[waiting_key.transfer_id].result in (
        T.TransferResult.REJECTED_USER,
        T.TransferResult.CANCELLED_USER,
    ), describe(results[waiting_key.transfer_id])
    order = [u.info.key.transfer_id for u in A.trec.of("TransferFinished")]
    assert order.index(recv_key.transfer_id) < order.index(send_key.transfer_id)
    assert order.index(recv_key.transfer_id) < order.index(waiting_key.transfer_id)
    assert cancels_or_rejects(wire_spy, recv_key.transfer_id) == []
    sent_to_c = [m for _, m in wire_spy if getattr(m, "transfer_id", None) == waiting_key.transfer_id]
    assert any(isinstance(m, Reject) and m.reason == "user" for m in sent_to_c), sent_to_c
    assert any(
        isinstance(m, Cancel) and m.reason == "user" and m.transfer_id == send_key.transfer_id
        for _, m in wire_spy
    )


# =================================================================================================
# S1: message của lượt tạm dừng tới giữa `begin_close` và lúc đóng kết nối
# =================================================================================================


class RawSender:
    """Bên gửi giả (danh tính của node C) trên kết nối điều khiển `cc` (fixture `control_client`): gửi
    `offer`, chờ `resume`, mở kết nối dữ liệu và ghi khung khối thật (`Connection.write_block`)."""

    def __init__(self, cc, C, A, size: int) -> None:
        self.cc, self.C, self.A = cc, C, A
        self.data = os.urandom(size)
        self.tid = uuid.uuid4().hex
        self.entry = FileEntry("s1.bin", size, 1_600_000_000_000)
        self.offer = Offer(self.tid, BLOCK_SIZE, (self.entry,))
        n = -(-size // BLOCK_SIZE)
        self.blocks = [self.data[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE] for i in range(n)]
        self.leaves = b"".join(hashlib.sha256(b).digest() for b in self.blocks)
        self.data_conns: list = []

    def received(self, cls) -> list:
        return [
            m for m in self.cc.received if isinstance(m, cls) and getattr(m, "transfer_id", None) == self.tid
        ]

    async def wait(self, cls, timeout: float = 10.0):
        await wait_until(lambda: self.received(cls), timeout, f"C chưa nhận {cls.__name__}")
        return self.received(cls)[-1]

    async def open_data(self, seq: int):
        conn = await connection.open_data(
            LOCAL,
            self.A.port,
            self.C.identity,
            self.C.hello,
            self.A.identity.cert_pem(),
            DataOpen(self.tid, 0, seq),
        )
        self.data_conns.append(conn)
        return conn

    def close(self) -> None:
        for conn in self.data_conns:
            conn.abort()


@pytest.mark.slow
@integration
@leakcheck
async def test_s1_complete_offer_and_data_open_during_close_do_not_cancel_suspended_transfer(
    T, transfer_nodes, node_factory, control_client, wire_spy, write_spy, monkeypatch, grace_real
):
    """S1 (spec-p3 mục P3-3b; spec-p3-3b mục 5): giữa `begin_close` và lúc đóng kết nối (giữ cửa sổ bằng
    cách chặn `flush_control`, bước 3 của `Node.close`), C gửi `complete`, `offer` gửi lại và mở thêm một
    kết nối dữ liệu cho lượt đang tạm dừng → A không gửi `cancel`/`reject` nào của lượt đó, kết nối dữ liệu
    mới bị đóng, thư mục tạm còn đủ, `TransferFinished(SUSPENDED)` đúng một lần."""
    net = await transfer_nodes(connect=False, extra_trusted=("C",))
    A = net.A
    C = await node_factory("C", auto_connect=False)
    cc = await control_client(C, A)
    await wait_until(lambda: C.id in A.connected_devices(), 5, "A chưa ghi nhận C")
    sender = RawSender(cc, C, A, 20 * MiB)
    try:
        await cc.conn.send(sender.offer)
        resume = await sender.wait(Resume)
        data = await sender.open_data(resume.seq)
        for i in range(18):
            await data.write_block(i, hashlib.sha256(sender.blocks[i]).digest(), sender.blocks[i])
        await wait_until(lambda: write_spy.count(sender.tid, done=True) >= 17, 20, "A chưa ghi đủ khối")

        began, proceed = asyncio.Event(), asyncio.Event()
        real_flush = T.TransferManager.flush_control

        async def flush_control(self, timeout):
            if self is A.transfers:
                began.set()
                await proceed.wait()
            return await real_flush(self, timeout)

        monkeypatch.setattr(T.TransferManager, "flush_control", flush_control)
        closing = asyncio.create_task(A.close())
        try:
            await asyncio.wait_for(began.wait(), 5)
            assert A.trec.finished(sender.tid).result == T.TransferResult.SUSPENDED
            await cc.conn.send(Complete(sender.tid, 0, merkle_root(sender.leaves).hex()))
            await cc.conn.send(sender.offer)
            try:
                late = await sender.open_data(resume.seq)
            except (connection.ConnectionLostError, OSError):
                late = None
            if late is not None:
                try:
                    got = await asyncio.wait_for(late.read_raw(1, at_boundary=True, idle_timeout=5), 6)
                except connection.ConnectionLostError:
                    got = None
                assert got is None, "A gửi dữ liệu trên kết nối dữ liệu của lượt tạm dừng"
            await asyncio.sleep(0.3)  # cho A xử lý các message trên
        finally:
            proceed.set()
        await asyncio.wait_for(closing, 15)
    finally:
        sender.close()

    assert cancels_or_rejects(wire_spy, sender.tid) == []
    assert sender.received(Cancel) == [] and sender.received(Reject) == []
    finished = A.trec.of("TransferFinished", sender.tid)
    assert len(finished) == 1 and finished[0].result == T.TransferResult.SUSPENDED
    left = set(os.listdir(temp_dir(net.receive_dir, sender.tid)))
    assert {"transfer.json", "0.part", "0.state"} <= left, left


# =================================================================================================
# V3: đóng trật tự giữa lượt → mở lại → hoàn tất, trong ngưỡng mvp N4
# =================================================================================================


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_orderly_close_mid_transfer_then_reopen_finishes(
    T, transfer_nodes, restart, write_spy, grace_real, n4_extra, monkeypatch, caplog, client
):
    """Test chức năng: file 24 MiB nhỏ hơn ngưỡng N4 nên chưa chứng minh N4 (gửi lại từ đầu vẫn qua).
    N4 thật: `test_orderly_close_while_network_blocked_at_85_percent_then_reopen_finishes_within_n4`."""
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB}, client=client)
    A, B = net.A, net.B
    size = 24 * MiB + 3
    src = make_file(net.src, "lon.bin", size)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid, done=True) >= 20, 30, "A chưa ghi đủ 20 khối")
    # Máy bận / macOS `F_FULLFSYNC`: `SyncPart` lúc đóng có thể quá `CLOSE_DISK_WAIT` thật (rủi ro R5 đã
    # chấp nhận); test này kiểm mở lại, không kiểm thời gian đóng.
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
    await close_cleanly(A, caplog)
    d = temp_dir(net.receive_dir, tid)
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(d))
    assert A.trec.finished(tid).result == T.TransferResult.SUSPENDED
    assert B.trec.finished(tid) is None

    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    [resumed] = A2.trec.of("TransferResumed", tid)
    rkey = core_transfer.TransferKey(B.id, core_transfer.Direction.RECEIVE, tid)
    assert resumed.info.key == rkey
    assert resumed.info.status == core_transfer.TransferStatus.RECONNECTING
    assert [(f.name, f.size) for f in resumed.info.files] == [("lon.bin", size)]
    assert resumed.info.total_bytes == size
    assert A2.transfers.get(rkey) is not None
    if client == "sender":
        B.connect_hint(A2.id, [LOCAL], A2.port)
    else:
        A2.connect_hint(B.id, [LOCAL], B.port)

    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert A2.trec.of("OfferReceived", tid) == [], "lượt khôi phục không được hỏi lại"
    assert sha256_of(net.receive_dir / "lon.bin") == sha256_of(src)
    excess = fin_b.payload_sent - size
    assert 0 <= excess <= n4_extra, (
        f"gửi thừa {excess / MiB:.1f} MiB (phần cộng thêm mvp N4 {n4_extra // MiB} MiB)"
    )
    assert fin_a.payload_sent == 0


@pytest.mark.slow
@integration
@leakcheck
async def test_suspend_drops_queued_finalize_of_last_file_then_reopen_finishes(
    T, transfer_nodes, restart, resume_helpers, monkeypatch, grace_real
):
    """F1 (spec-p3-3b mục 8.4, thắng 8.1.10): `Finalize` của file cuối đã giao cho hàng đĩa nhưng **chưa
    bắt đầu** khi node nhận đóng → lượt `SUSPENDED` một lần và trên đĩa lượt **chưa** xong: `.part`,
    `.state` còn, `transfer.json` chưa có `done_at`, file chưa mang tên thật. Mở lại → `TransferResumed`
    một lần; máy gửi nối lại (gửi lại `complete`) → đọc lại, đổi tên → hai bên DONE, file khớp nguồn.

    Cách giữ `Finalize` ở trạng thái “chưa bắt đầu”: `DiskExecutor` của node một thread (thay
    `teleport.app.node.DiskExecutor`); lúc đọc lại, hẹn giờ dọn tạm (rút ngắn `CLEANUP_INTERVAL`) xếp một
    việc `cleanup` vào sau, việc đó chặn thread ở cổng của test, nên `Finalize` giao sau nó phải chờ. Đóng
    A rồi mới mở cổng (trong `CLOSE_DISK_WAIT` đã nới rộng, để `Finalize` còn kịp chạy nếu không bị bỏ).
    """
    from teleport.app import diskio
    from teleport.app import node as node_mod
    from teleport.core import resume_state as rs

    real_executor = diskio.DiskExecutor
    monkeypatch.setattr(node_mod, "DiskExecutor", lambda *a, **kw: real_executor(1, **kw))
    monkeypatch.setattr(T, "CLEANUP_INTERVAL", 0.05)
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 10.0)
    armed, cleanup_hit, gate = threading.Event(), threading.Event(), threading.Event()
    finalize_calls: list[str] = []
    real_reread, real_cleanup, real_finalize = (
        storage.PartFile.reread,
        storage.ReceiveDir.cleanup,
        storage.ReceiveDir.finalize,
    )

    def reread(self, *, stop=None):
        result = real_reread(self, stop=stop)
        if not armed.is_set():
            armed.set()
            time.sleep(0.5)  # nhiều chu kỳ CLEANUP_INTERVAL: một việc `cleanup` xếp hàng sau việc này
        return result

    def cleanup(self, wall_now, *, own_device_id, skip, retention):
        if armed.is_set() and not cleanup_hit.is_set():
            cleanup_hit.set()
            gate.wait(30)
        return real_cleanup(self, wall_now, own_device_id=own_device_id, skip=skip, retention=retention)

    def finalize(self, part, name, **kwargs):
        finalize_calls.append(part.path.parent.name)
        return real_finalize(self, part, name, **kwargs)

    monkeypatch.setattr(storage.PartFile, "reread", reread)
    monkeypatch.setattr(storage.ReceiveDir, "cleanup", cleanup)
    monkeypatch.setattr(storage.ReceiveDir, "finalize", finalize)

    net = await transfer_nodes()
    A, B = net.A, net.B
    src = make_file(net.src, "f.bin", 3 * MiB + 5)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    try:
        await wait_until(cleanup_hit.is_set, 30, "việc cleanup chưa chặn thread đĩa sau lượt đọc lại")
        await asyncio.sleep(0.3)  # `reread_done` → `Finalize` đã được giao, đang chờ thread
        assert finalize_calls == [], "Finalize không được chạy trước khi thread rảnh"
        closing = asyncio.create_task(A.close())
        await A.trec.wait_kind("TransferFinished", tid, timeout=5)
        gate.set()
        await asyncio.wait_for(closing, 30)
    finally:
        gate.set()

    finished = A.trec.of("TransferFinished", tid)
    assert len(finished) == 1 and finished[0].result == T.TransferResult.SUSPENDED, [
        describe(f) for f in finished
    ]
    assert finalize_calls == [], "Finalize chưa bắt đầu phải bị bỏ khi tạm dừng"
    d = temp_dir(net.receive_dir, tid)
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(d))
    rec = rs.decode_transfer_record((d / "transfer.json").read_bytes(), dir_name=tid)
    assert rec.done_at is None and rec.verified == 0
    assert not (net.receive_dir / "f.bin").exists()
    assert B.trec.finished(tid) is None

    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    assert len(A2.trec.of("TransferResumed", tid)) == 1
    B.connect_hint(A2.id, [LOCAL], A2.port)
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


# =================================================================================================
# spec-fix-app (1b): đóng quá `CLOSE_DISK_WAIT` khi `SyncPart` chậm; `Node.close` bị hủy lúc `SyncPart`
# đang chạy. Thread đĩa chạy xong thì handle của lượt và thư mục nhận vẫn được đóng (“đuôi đĩa”).
# =================================================================================================


class DiskOrder:
    """Nhật ký có thứ tự (an toàn giữa các thread): `("rd_close", rd)` lúc một `ReceiveDir` còn mở bắt đầu
    `close()`, `("close_temp", transfer_id)`, `("remove_temp", transfer_id)`, `("commit_start" /
    "commit_end", transfer_id)` của lần `commit` bị giữ. `opened`: mọi `ReceiveDir` mở qua
    `ReceiveDir.open` sau khi cài."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[tuple[str, object]] = []
        self.opened: list[storage.ReceiveDir] = []

    def add(self, kind: str, what: object) -> None:
        with self.lock:
            self.events.append((kind, what))

    def index(self, kind: str, what: object) -> int | None:
        with self.lock:
            for i, (k, w) in enumerate(self.events):
                if k == kind and (w is what or w == what):
                    return i
        return None

    def of(self, kind: str, what: object = None) -> list[object]:
        with self.lock:
            return [w for k, w in self.events if k == kind and (what is None or w is what or w == what)]


@pytest.fixture
def held_commit(monkeypatch):
    """Giữ lần `PartFile.commit` **đầu tiên** của lượt `held.tid` (đặt sau khi có `transfer_id`) ở cổng
    `held.gate` (trong thread đĩa) rồi mới chạy bản thật; mọi lần khác chạy thẳng. `held.started` /
    `held.ended`: lần bị giữ đã bắt đầu / đã trả về. Kèm `held.order` (`DiskOrder`) đã cài spy
    `ReceiveDir.open` / `close` / `close_temp` / `remove_temp`."""
    order = DiskOrder()
    held = SimpleNamespace(
        tid=None,
        used=False,
        gate=threading.Event(),
        started=threading.Event(),
        ended=threading.Event(),
        order=order,
    )
    real_open = storage.ReceiveDir.open
    real_close = storage.ReceiveDir.close
    real_close_temp = storage.ReceiveDir.close_temp
    real_remove = storage.ReceiveDir.remove_temp
    real_commit = storage.PartFile.commit

    def open_(cls, root):
        rd = real_open(root)
        with order.lock:
            order.opened.append(rd)
        return rd

    def close(rd):
        if not rd.closed:
            order.add("rd_close", rd)
        return real_close(rd)

    def close_temp(rd, temp):
        order.add("close_temp", temp.transfer_id)
        return real_close_temp(rd, temp)

    def remove_temp(rd, temp, *, keep_record=False):
        order.add("remove_temp", temp.transfer_id)
        return real_remove(rd, temp, keep_record=keep_record)

    def commit(part, blocks):
        tid = part.path.parent.name
        if tid != held.tid or held.used:
            return real_commit(part, blocks)
        held.used = True
        order.add("commit_start", tid)
        held.started.set()
        try:
            held.gate.wait(30)
            return real_commit(part, blocks)
        finally:
            order.add("commit_end", tid)
            held.ended.set()

    monkeypatch.setattr(storage.ReceiveDir, "open", classmethod(open_))
    monkeypatch.setattr(storage.ReceiveDir, "close", close)
    monkeypatch.setattr(storage.ReceiveDir, "close_temp", close_temp)
    monkeypatch.setattr(storage.ReceiveDir, "remove_temp", remove_temp)
    monkeypatch.setattr(storage.PartFile, "commit", commit)
    yield held
    held.gate.set()


async def start_held_transfer(transfer_nodes, held_commit, size: int):
    """B gửi `size` byte cho A; chờ tới khi `commit` đầu tiên của lượt bị giữ trong thread đĩa của A. Trả
    `(net, src, tid, rd)`; `rd` là `ReceiveDir` của A."""
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    assert len(held_commit.order.opened) == 1, "mong đúng một ReceiveDir (của A)"
    rd = held_commit.order.opened[0]
    src = make_file(net.src, "lon.bin", size)
    key = await net.B.transfers.send(net.A.id, [src])
    held_commit.tid = key.transfer_id
    await asyncio.wait_for(asyncio.to_thread(held_commit.started.wait, 30), 35)
    return net, src, key.transfer_id, rd


async def finish_tail(held_commit, rd, tid: str) -> None:
    """Mở cổng `commit`; chờ nó trả về rồi chờ thư mục nhận được đóng (đuôi đĩa xong)."""
    held_commit.gate.set()
    await asyncio.wait_for(asyncio.to_thread(held_commit.ended.wait, 30), 35)
    await wait_until(lambda: rd.closed, 10, "ReceiveDir không được đóng sau khi thread đĩa xong")


def assert_handles_closed_after_commit(order: DiskOrder, rd, tid: str) -> None:
    """`commit` bị giữ trả về → `close_temp` đúng một lần cho lượt → `ReceiveDir.close` đúng một lần;
    không `remove_temp` nào cho lượt (tạm dừng chỉ đóng handle)."""
    events = order.events
    assert order.of("close_temp", tid) == [tid], f"close_temp của lượt không được gọi đúng một lần: {events}"
    assert order.of("remove_temp", tid) == [], events
    assert len(order.of("rd_close", rd)) == 1, events
    end, closed_temp, closed_rd = (
        order.index("commit_end", tid),
        order.index("close_temp", tid),
        order.index("rd_close", rd),
    )
    assert end is not None and end < closed_temp < closed_rd, events


def errors_logged(caplog) -> list[logging.LogRecord]:
    """Bản ghi ERROR+ của mọi logger (kể cả `asyncio`: “Task exception was never retrieved”)."""
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


@pytest.mark.slow
@integration
@leakcheck
async def test_close_past_close_disk_wait_closes_handles_after_slow_sync_and_reopen_finishes(
    T, transfer_nodes, restart, write_spy, held_commit, resume_helpers, grace_real, monkeypatch, caplog
):
    """spec-fix-app (1b): `CLOSE_DISK_WAIT` = 0,3 s; `commit` (`SyncPart`) của lượt đang nhận kẹt trong
    thread đĩa suốt lúc A đóng (cổng chỉ mở sau khi `close` trả về). `A.close()` trả về trong hạn
    `close_time_limit()` với WARNING “việc dọn đĩa chưa xong”, thư mục nhận chưa đóng (thread còn dùng nó).
    Mở cổng → `commit` trả về, rồi `close_temp` của lượt, rồi `ReceiveDir.close` (spy có thứ tự); `MARK` của
    lô chậm bền (`marked == written`); không ERROR. Mở lại A cùng tiến trình, cùng thư mục nhận (sau khi
    `commit` xong) → nối lại DONE, file khớp nguồn (handle cũ còn mở thì Windows từ chối đổi tên)."""
    from teleport.app import node as node_mod

    size = 24 * MiB + 3
    net, src, tid, rd = await start_held_transfer(transfer_nodes, held_commit, size)
    A, B = net.A, net.B
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 0.3)
    caplog.set_level(logging.WARNING)
    try:
        limit = node_mod.close_time_limit()
        t0 = time.monotonic()
        await asyncio.wait_for(A.close(), limit + 5)
        elapsed = time.monotonic() - t0
        assert elapsed <= limit, f"A.close() mất {elapsed:.2f} s (hạn {limit:.1f} s)"
        assert not held_commit.ended.is_set(), "tiền đề: commit phải còn kẹt khi close trả về"
        slow = [
            r.getMessage()
            for r in caplog.records
            if r.name == "teleport.app.transfers" and "việc dọn đĩa chưa xong" in r.getMessage()
        ]
        assert slow, "đóng quá CLOSE_DISK_WAIT phải có WARNING “việc dọn đĩa chưa xong”"
        assert not rd.closed, "ReceiveDir bị đóng khi thread đĩa còn đang dùng nó"
        fin = A.trec.finished(tid)
        assert fin is not None and fin.result == T.TransferResult.SUSPENDED, describe(fin)
    finally:
        held_commit.gate.set()
    await finish_tail(held_commit, rd, tid)
    assert_handles_closed_after_commit(held_commit.order, rd, tid)
    d = temp_dir(net.receive_dir, tid)
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(d))
    written = {r[2] for r in write_spy.done if r[0] == tid and r[1] == 0}
    assert written, "tiền đề: A đã ghi khối trước lần commit bị giữ"
    assert marked_blocks(resume_helpers, d / "0.state") == written, "MARK của lô chậm phải bền"
    assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]

    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    assert len(A2.trec.of("TransferResumed", tid)) == 1
    B.connect_hint(A2.id, [LOCAL], A2.port)
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(net.receive_dir / "lon.bin") == sha256_of(src)


@pytest.mark.slow
@integration
@leakcheck
async def test_node_close_cancelled_while_sync_runs_closes_handles_after_commit_and_keeps_mark(
    T, transfer_nodes, write_spy, held_commit, resume_helpers, grace_real, monkeypatch, caplog
):
    """spec-fix-app (1b, mục 3 việc #4): `Node.close` bị hủy khi `commit` (`SyncPart`) của lượt đang nhận
    còn chạy trong thread đĩa (→ `abort_now`). Lúc đó thư mục nhận chưa đóng; mở cổng → `commit` trả về,
    rồi `close_temp` của lượt, rồi `ReceiveDir.close`; không `remove_temp`, `.part` / `.state` /
    `transfer.json` còn; `MARK` của lô đó bền (`marked == written`); không ERROR."""
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
    net, _, tid, rd = await start_held_transfer(transfer_nodes, held_commit, 24 * MiB + 3)
    A = net.A
    caplog.set_level(logging.WARNING)
    try:
        closing = asyncio.create_task(A.close())
        await A.trec.wait_kind("TransferFinished", tid, timeout=5)
        assert A.trec.finished(tid).result == T.TransferResult.SUSPENDED
        await asyncio.sleep(0.2)
        assert not closing.done(), "tiền đề: close phải còn chờ hàng đĩa (commit đang kẹt)"
        closing.cancel()
        with pytest.raises(asyncio.CancelledError):
            await closing
        assert not held_commit.ended.is_set()
        assert not rd.closed, "ReceiveDir bị đóng khi thread đĩa còn đang dùng nó"
    finally:
        held_commit.gate.set()
    await finish_tail(held_commit, rd, tid)
    assert_handles_closed_after_commit(held_commit.order, rd, tid)
    d = temp_dir(net.receive_dir, tid)
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(d))
    written = {r[2] for r in write_spy.done if r[0] == tid and r[1] == 0}
    assert written, "tiền đề: A đã ghi khối trước lần commit bị giữ"
    assert marked_blocks(resume_helpers, d / "0.state") == written, "MARK của lô đang ghi phải bền"
    assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]


# =================================================================================================
# P3-5: đóng trật tự lúc mạng bị chặn ở 85 % rồi mở lại (V5, V7, V8 (ii)); lật byte khi tạm dừng (V6)
# =================================================================================================

CUT_AT = 0.85  # mvp N4: “ở 85 %”
BIG = 96 * MiB  # đủ lớn để gửi lại từ đầu ở 85 % vượt ngưỡng N4 (tiền đề kiểm ở từng test)


def block_len(size: int, index: int) -> int:
    return min(BLOCK_SIZE, size - index * BLOCK_SIZE)


def all_blocks(size: int) -> set[int]:
    return set(range(-(-size // BLOCK_SIZE)))


def state_records(data: bytes) -> list[SimpleNamespace]:
    """Vị trí và nội dung từng bản ghi của `.state` (architecture mục 4: header 41 byte, rồi
    `[u8 loại][u16 n][payload][u32 crc32]`; `CLEAR_ALL` 5 byte), đọc độc lập với code. Mỗi bản ghi:
    `offset`, `length`, `kind` (`"mark"`, `"clear"`, `"clear_all"`, `"target"`, `"reserved"`), `blocks`."""
    pos, out = 41, []
    names = {0x01: "mark", 0x02: "clear", 0x03: "clear_all", 0x04: "target", 0x05: "reserved"}
    while pos < len(data):
        kind = data[pos]
        if kind == 0x03:
            length, blocks = 5, []
        else:
            (n,) = struct.unpack_from("!H", data, pos + 1)
            length = 7 + n * {0x01: 36, 0x02: 4, 0x04: 1, 0x05: 1}[kind]
            payload = data[pos + 3 : pos + length - 4]
            if kind == 0x01:
                blocks = [i for i, _ in struct.iter_unpack("!I32s", payload)]
            elif kind == 0x02:
                blocks = [i for (i,) in struct.iter_unpack("!I", payload)]
            else:
                blocks = []
        (crc,) = struct.unpack_from("!I", data, pos + length - 4)
        assert crc == zlib.crc32(data[pos : pos + length - 4]), f"bản ghi hỏng sẵn ở byte {pos}"
        out.append(SimpleNamespace(offset=pos, length=length, kind=names[kind], blocks=blocks))
        pos += length
    assert pos == len(data)
    return out


def marked_by(records) -> set[int]:
    marked: set[int] = set()
    for r in records:
        if r.kind == "mark":
            marked |= set(r.blocks)
        elif r.kind == "clear":
            marked -= set(r.blocks)
        elif r.kind == "clear_all":
            marked.clear()
    return marked


def flip_byte(path: Path, offset: int) -> None:
    with open(path, "r+b") as f:
        f.seek(offset)
        b = f.read(1)
        assert len(b) == 1, f"{path.name} ngắn hơn byte {offset}"
        f.seek(offset)
        f.write(bytes([b[0] ^ 0x5A]))


async def wait_stable(
    value, quiet: float = 0.5, timeout: float = 15.0, what: str = "giá trị còn đổi"
) -> None:
    """Chờ tới khi `value()` không đổi trong `quiet` giây (hạn `timeout`)."""
    deadline = time.monotonic() + timeout
    last, since = value(), time.monotonic()
    while time.monotonic() - since < quiet:
        if time.monotonic() > deadline:
            raise AssertionError(f"hết {timeout} s mà {what}")
        await asyncio.sleep(0.05)
        if (now := value()) != last:
            last, since = now, time.monotonic()


@pytest.fixture
def suspend_blocked(T, transfer_nodes, tcp_proxy, payload_meter, write_spy, monkeypatch, caplog):
    """`await suspend_blocked(size, client="sender", cut_at=CUT_AT, name="lon.bin")`: hai node nối kết
    nối điều khiển qua proxy đặt trước node bị nối tới; B gửi `size` byte; proxy tự chặn khi chiều payload
    đã chuyển `cut_at × size` byte (`block_at`); trong lúc chặn A đóng có trật tự (lượt `SUSPENDED`); rồi
    proxy RST mọi kết nối và hết chặn. Trả `SimpleNamespace(net, A, B, proxy, src, tid, size, client,
    cut_sent, temp)`; `cut_sent` = payload bên gửi đã giao lúc thấy proxy chặn."""

    async def make(size: int, *, client: str = "sender", cut_at: float = CUT_AT, name: str = "lon.bin"):
        net = await transfer_nodes(client=client, connect=False)
        A, B = net.A, net.B
        opener, other = (B, A) if client == "sender" else (A, B)
        proxy = tcp_proxy(other.port)
        opener.connect_hint(other.id, [LOCAL], proxy.port)
        await wait_until(
            lambda: other.id in opener.connected_devices() and opener.id in other.connected_devices(),
            15,
            "chưa nối được kết nối điều khiển qua proxy",
        )
        src = make_file(net.src, name, size)
        proxy.block_at("c2s" if client == "sender" else "s2c", int(cut_at * size))
        key = await B.transfers.send(A.id, [src])
        tid = key.transfer_id
        await wait_until(lambda: proxy.fired, 60, "lượt chưa tới vị trí cắt")
        # Byte proxy đã chuyển có thể còn nằm trong bộ đệm socket của A (máy bận): chờ A ghi xong những
        # gì đã tới rồi mới đóng, để `.state` phản ánh phần đã nhận (mạng vẫn đang chặn).
        await wait_stable(lambda: write_spy.count(tid, done=True), what="A còn đang ghi khối")
        cut_sent = payload_meter.sent
        # Như `test_orderly_close_mid_transfer_then_reopen_finishes`: hàng đĩa phải xong trước khi đóng
        # thư mục nhận, kể cả trên máy bận (không thì handle của A không bao giờ đóng).
        monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
        await close_cleanly(A, caplog)
        fin = A.trec.finished(tid)
        assert fin is not None and fin.result == T.TransferResult.SUSPENDED, describe(fin)
        assert B.trec.finished(tid) is None
        proxy.rst()
        proxy.resume()
        temp = temp_dir(net.receive_dir, tid)
        assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(temp))
        return SimpleNamespace(
            net=net,
            A=A,
            B=B,
            proxy=proxy,
            src=src,
            tid=tid,
            size=size,
            client=client,
            cut_sent=cut_sent,
            temp=temp,
        )

    return make


async def reopen_and_connect(restart, s):
    """Mở lại A (cùng thư mục cấu hình và thư mục nhận) rồi nối thẳng, không qua proxy, theo chiều cũ."""
    A2 = await restart("A", receive_dir=s.net.receive_dir, auto_accept=True)
    if s.client == "sender":
        s.B.connect_hint(A2.id, [LOCAL], A2.port)
    else:
        A2.connect_hint(s.B.id, [LOCAL], s.B.port)
    return A2


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("client", ["sender", "receiver"])
async def test_orderly_close_while_network_blocked_at_85_percent_then_reopen_finishes_within_n4(
    T, suspend_blocked, restart, payload_meter, grace_real, n4_extra, client
):
    """V5 (spec-p3-5): mạng bị chặn ở 85 % của 96 MiB, A đóng trật tự lúc đó (tạm dừng), mở lại → hoàn tất,
    file khớp, `payload_sent − cỡ file ≤ n4_extra` (mvp N4 “tắt app nhận ở bất kỳ điểm nào”)."""
    assert n4_extra < CUT_AT * BIG, "tiền đề N4: 85 % của file thử phải lớn hơn phần cộng thêm của N4"
    s = await suspend_blocked(BIG, client=client)
    assert s.cut_sent > n4_extra, f"tiền đề N4: lúc cắt mới gửi {s.cut_sent / MiB:.1f} MiB"
    A2 = await reopen_and_connect(restart, s)
    assert len(A2.trec.of("TransferResumed", s.tid)) == 1
    fin_b = await s.B.trec.wait_finished(s.tid, 90)
    fin_a = await A2.trec.wait_finished(s.tid, 90)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(s.net.receive_dir / "lon.bin") == sha256_of(s.src)
    assert fin_a.payload_sent == 0
    for label, sent in (("payload_sent", fin_b.payload_sent), ("payload_meter", payload_meter.sent)):
        excess = sent - BIG
        assert 0 <= excess <= n4_extra, (
            f"{label}: gửi thừa {excess / MiB:.1f} MiB (ngưỡng mvp N4 {n4_extra // MiB} MiB; "
            f"lúc cắt đã gửi {s.cut_sent / MiB:.1f} MiB)"
        )


# --- V6: lật một byte `.part` của khối đã MARK khi tạm dừng (mvp F7 AC3, N5; spec-p3-5 mục 9.1 Q3) -------


def pick_flip(case: str, marked: set[int], size: int) -> tuple[int, int]:
    """(khối k, vị trí byte tuyệt đối) theo ca: byte đầu / byte cuối của một khối đã MARK ở giữa, hoặc
    khối và byte ngẫu nhiên theo seed `random.Random` cố định."""
    ordered = sorted(marked)
    if case == "byte-dau-khoi":
        k = ordered[len(ordered) // 2]
        return k, k * BLOCK_SIZE
    if case == "byte-cuoi-khoi":
        k = ordered[len(ordered) // 2]
        return k, k * BLOCK_SIZE + block_len(size, k) - 1
    rnd = random.Random(int(case.removeprefix("seed-")))
    k = rnd.choice(ordered)
    return k, k * BLOCK_SIZE + rnd.randrange(block_len(size, k))


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("case", ["byte-dau-khoi", "byte-cuoi-khoi", "seed-7", "seed-1234"])
async def test_flipped_byte_in_marked_block_while_suspended_resends_only_that_block(
    T, suspend_blocked, restart, payload_meter, resume_helpers, grace_real, case
):
    """V6: tạm dừng giữa lượt; lật một byte của khối k đã MARK trong `.part`; mở lại → khối k được gửi lại
    đúng một lần (đọc lại phát hiện), các khối MARK khác không gửi lại, tập khối gửi lại sau khi mở lại =
    (chưa MARK) ∪ {k}; DONE, file khớp nguồn."""
    size = 24 * MiB + 5
    s = await suspend_blocked(size, cut_at=0.5, name="v6.bin")
    marked = marked_blocks(resume_helpers, s.temp / "0.state")
    assert len(marked) >= 3 and marked != all_blocks(size), (
        f"tiền đề: cần vài khối MARK và còn khối thiếu {marked}"
    )
    k, offset = pick_flip(case, marked, size)
    flip_byte(s.temp / "0.part", offset)
    pos = payload_meter.pos()
    A2 = await reopen_and_connect(restart, s)
    fin_b = await s.B.trec.wait_finished(s.tid, 60)
    fin_a = await A2.trec.wait_finished(s.tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(s.net.receive_dir / "v6.bin") == sha256_of(s.src)
    sent = payload_meter.counts(pos)
    assert sent[k] == 1, f"khối hỏng {k} gửi {sent[k]} lần"
    assert {j: sent[j] for j in marked - {k} if sent[j]} == {}, "khối MARK còn tốt bị gửi lại"
    assert set(sent) == (all_blocks(size) - marked) | {k}
    assert max(sent.values()) == 1, sent


@integration
@leakcheck
async def test_flipped_byte_in_short_last_block_while_suspended_in_reread_resends_only_that_block(
    T, transfer_nodes, restart, payload_meter, resume_helpers, grace_real, monkeypatch
):
    """V6, ca khối cuối ngắn: mọi khối đã MARK, A đóng trật tự lúc đang đọc lại (giữ `PartFile.reread` ở
    một cổng); lật một byte ngẫu nhiên (seed cố định) trong khối cuối ngắn hơn 1 MiB; mở lại → chỉ khối cuối
    được gửi lại, đúng một lần; DONE, file khớp."""
    monkeypatch.setattr(T, "CLOSE_DISK_WAIT", 30.0)
    hit, gate = threading.Event(), threading.Event()
    real_reread = storage.PartFile.reread

    def reread(self, *, stop=None):
        if not hit.is_set():
            hit.set()
            gate.wait(30)
        return real_reread(self, stop=stop)

    monkeypatch.setattr(storage.PartFile, "reread", reread)
    size = 6 * MiB + 12345
    net = await transfer_nodes()
    A, B = net.A, net.B
    src = make_file(net.src, "ngan.bin", size)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    try:
        await wait_until(hit.is_set, 30, "chưa tới lượt đọc lại")
        closing = asyncio.create_task(A.close())
        await A.trec.wait_kind("TransferFinished", tid, timeout=5)
        assert A.trec.finished(tid).result == T.TransferResult.SUSPENDED, describe(A.trec.finished(tid))
        gate.set()
        await asyncio.wait_for(closing, 30)
    finally:
        gate.set()
    temp = temp_dir(net.receive_dir, tid)
    assert marked_blocks(resume_helpers, temp / "0.state") == all_blocks(size), "tiền đề: mọi khối đã MARK"
    last = size // BLOCK_SIZE
    assert block_len(size, last) == 12345
    flip_byte(temp / "0.part", last * BLOCK_SIZE + random.Random(5).randrange(12345))
    pos = payload_meter.pos()
    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    B.connect_hint(A2.id, [LOCAL], A2.port)
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(net.receive_dir / "ngan.bin") == sha256_of(src)
    assert dict(payload_meter.counts(pos)) == {last: 1}


# --- V7: lật một byte `.state` khi tạm dừng (mvp N5; spec-p3-5 mục 9.2 C4) ---------------------------


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("where", ["mark-dau", "mark-cuoi", "header"])
async def test_flipped_byte_in_state_resumes_from_last_good_record(
    T, suspend_blocked, restart, payload_meter, grace_real, n4_extra, where
):
    """V7: tạm dừng ở 85 % của 96 MiB; lật một byte trong bản ghi MARK đầu / MARK cuối / header của
    `.state`. Bản ghi hỏng và mọi bản ghi sau nó bị bỏ (header hỏng: như chưa có trạng thái, bitfield 0,
    architecture mục 4): `TransferResumed.info.done_bytes` = byte của các khối MARK trước bản ghi hỏng; sau
    khi mở lại, khối từ bản ghi hỏng trở đi (và khối chưa MARK) được gửi lại, khối MARK trước đó không;
    DONE, file khớp. Ca MARK cuối (mất tối đa một lô): trong ngưỡng mvp N4."""
    s = await suspend_blocked(BIG, name="v7.bin")
    state = s.temp / "0.state"
    records = state_records(state.read_bytes())
    marks = [i for i, r in enumerate(records) if r.kind == "mark"]
    assert len(marks) >= 2, f"tiền đề: cần ≥ 2 bản ghi MARK, có {len(marks)}"
    if where == "header":
        flip_byte(state, 9)
        kept = []
    else:
        bad = marks[0] if where == "mark-dau" else marks[-1]
        flip_byte(state, records[bad].offset + 3 + 4 + 5)  # một byte sha256 của khối đầu trong bản ghi
        kept = records[:bad]
    before = marked_by(kept)
    expected_done = sum(block_len(BIG, j) for j in before)
    pos = payload_meter.pos()
    A2 = await reopen_and_connect(restart, s)
    [resumed] = A2.trec.of("TransferResumed", s.tid)
    assert resumed.info.done_bytes == expected_done, (resumed.info.done_bytes, expected_done)
    fin_b = await s.B.trec.wait_finished(s.tid, 90)
    fin_a = await A2.trec.wait_finished(s.tid, 90)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(s.net.receive_dir / "v7.bin") == sha256_of(s.src)
    sent = payload_meter.counts(pos)
    assert set(sent) == all_blocks(BIG) - before, (
        f"gửi lại sai tập khối: thừa {sorted(set(sent) & before)[:5]}, "
        f"thiếu {sorted(all_blocks(BIG) - before - set(sent))[:5]}"
    )
    if where == "mark-cuoi":
        assert s.cut_sent > n4_extra, "tiền đề N4: lúc cắt phải đã gửi hơn phần cộng thêm của N4"
        excess = fin_b.payload_sent - BIG
        assert 0 <= excess <= n4_extra, (
            f"gửi thừa {excess / MiB:.1f} MiB (ngưỡng mvp N4 {n4_extra // MiB} MiB)"
        )


# --- V8 (ii): nguồn đổi trong lúc bên nhận tạm dừng (mvp F6 AC4) ---------------------------------------


def change_source(path: Path, how: str) -> None:
    st = os.stat(path)
    if how == "them-byte":
        with open(path, "ab") as f:
            f.write(b"\x00")
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns))  # chỉ cỡ đổi, mtime giữ nguyên
        after = os.stat(path)
        assert after.st_size == st.st_size + 1 and after.st_mtime_ns == st.st_mtime_ns
    else:
        os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        after = os.stat(path)
        assert after.st_size == st.st_size and after.st_mtime_ns != st.st_mtime_ns


@pytest.mark.slow
@integration
@leakcheck
@pytest.mark.parametrize("how", ["them-byte", "chi-mtime"])
async def test_source_changed_while_receiver_suspended_cancels_both_sides_and_cleans_temp(
    T, suspend_blocked, restart, payload_meter, grace_real, how
):
    """V8 (ii): A tạm dừng ở 85 %; file nguồn đổi (thêm 1 byte / chỉ mtime); mở A2 → khi nối lại, bên gửi
    phát hiện lúc mở lại nguồn: B `SOURCE_CHANGED` (`by_peer=False`), A2 `SOURCE_CHANGED` (`by_peer=True`),
    không gửi thêm payload nào sau lúc đổi, thư mục tạm bị xóa, không có file mang tên thật."""
    s = await suspend_blocked(16 * MiB + 5, name="doi.bin")
    before_change = payload_meter.sent
    change_source(s.src, how)
    A2 = await reopen_and_connect(restart, s)
    fin_b = await s.B.trec.wait_finished(s.tid, 30)
    fin_a = await A2.trec.wait_finished(s.tid, 30)
    assert (fin_b.result, fin_b.by_peer) == (T.TransferResult.SOURCE_CHANGED, False), describe(fin_b)
    assert (fin_a.result, fin_a.by_peer) == (T.TransferResult.SOURCE_CHANGED, True), describe(fin_a)
    assert payload_meter.sent == before_change, (
        f"bên gửi giao thêm {(payload_meter.sent - before_change) / MiB:.1f} MiB sau khi nguồn đổi"
    )
    await wait_gone(s.temp)
    assert not (s.net.receive_dir / "doi.bin").exists(), "có file mang tên thật dù nguồn đã đổi"
