"""Khôi phục khi `Node.start` (P3-3b, việc V2 (c) và V3 trong tiến trình).

Viết từ đặc tả, không từ code: `specs/spec-p3-3b.md` mục 2.2 (`TransferManager.restore`: bia mộ, quét,
xếp loại, mở lại song song có hạn, một khối đồng bộ, `TransferResumed`), 2.6 (`Node.start`: khôi phục
trước khi mở cổng; hẹn giờ dọn tạm với `skip` chụp đồng bộ), 3 (Q4, Q6), 5 (V2 (c), V3), 8.1 mục 6
(hạn tổng của bước mở lại), 8 (lỗi `engine.restore` → gọi lại một lần với `receives=()`); `specs/spec-p3.md`
mục P3-3b (“Xong khi”); protocol §6.2, §6.3; architecture mục 4 (“Khôi phục”, “Dọn tạm”).
`specs/spec-fix-app.md` (1a: `Node.start` bị hủy lúc đang mở lại → handle và `ReceiveDir` đóng sau khi
việc đĩa treo xong; 1d: máy gửi không còn tin cậy; mục 9 thắng 1–8).

Hai cách dựng trạng thái: (1) chạy lượt thật B → A rồi đóng A có trật tự (tạm dừng), mở lại A bằng
`node_factory` cùng nhãn; (2) dựng thẳng thư mục nhận bằng API `teleport.app.storage` (lượt nhận dở của
máy gửi giả C, D…; mtime đặt bằng `os.utime`). Máy gửi giả nói chuyện với A qua `control_client` (kết nối
điều khiển thật, danh tính của node C). Đổi đích của proxy (`TcpProxy.target`, đọc lúc nối) khi A mở lại
trên cổng mới. Hạn chờ nối lại đặt lại giá trị thật (fixture `fast` đặt 4 s).
"""

from __future__ import annotations

import asyncio
import errno
import gc
import hashlib
import logging
import os
import random
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from support import wait_until

from teleport.app import storage
from teleport.core import resume_state as rs
from teleport.core import transfer as core_transfer
from teleport.core.bitfield import Bitfield
from teleport.core.blocks import BLOCK_SIZE
from teleport.core.merkle import merkle_root
from teleport.core.messages import Accept, Cancel, Complete, Resume, Verified
from teleport.trust.store import TrustStore

pytestmark = [
    pytest.mark.integration,
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
leakcheck = pytest.mark.usefixtures("no_leaks")

LOCAL = "127.0.0.1"
MiB = 1024 * 1024
REAL_GRACE = core_transfer.RECONNECT_GRACE  # đọc lúc import, trước khi `fast` vá
SIZE = 5 * MiB + 3  # 6 khối, khối cuối ngắn
RECEIVE = core_transfer.Direction.RECEIVE


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


def leaves_of(data: bytes) -> bytes:
    n = max(1, -(-len(data) // BLOCK_SIZE))
    return b"".join(hashlib.sha256(data[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]).digest() for i in range(n))


def temp_dir(receive_dir: Path, tid: str) -> Path:
    return receive_dir / ".teleport" / tid


def content_of(d: Path) -> dict[str, tuple[int, str]]:
    """Tên → (cỡ, SHA-256) của các file trong thư mục (không tính mtime)."""
    return {
        p.name: (p.stat().st_size, hashlib.sha256(p.read_bytes()).hexdigest()) for p in sorted(d.iterdir())
    }


def describe(fin) -> str:
    if fin is None:
        return "chưa có TransferFinished"
    return f"result={fin.result} by_peer={fin.by_peer} reason={fin.reason} file_index={fin.file_index}"


def messages(cc, cls, tid: str | None = None) -> list:
    return [m for m in cc.received if isinstance(m, cls) and (tid is None or m.transfer_id == tid)]


def build_running(
    storage_mod, root: Path, record_for, h, tid: str, *, sender: str, receiver: str, blocks, age: float
):
    """Lượt nhận dở trên đĩa: `transfer.json` (máy nhận `receiver`, máy gửi `sender`, một file `SIZE`),
    `0.part` với các khối `blocks` đã ghi và `MARK` bền; mọi file và thư mục có mtime = bây giờ − `age`."""
    data = random.Random(tid).randbytes(SIZE)
    with storage_mod.ReceiveDir.open(root) as rd:
        temp = rd.create_temp(tid, record_for(tid, [SIZE], receiver=receiver, sender=sender))
        part = temp.create_part(0, SIZE)
        if blocks:
            part.commit(h.write_blocks(part, data, blocks))
        rd.close_temp(temp)
    d = temp_dir(root, tid)
    t = time.time() - age
    for p in d.iterdir():
        os.utime(p, (t, t))
    os.utime(d, (t, t))
    return d


@pytest.fixture
def T():
    from teleport.app import transfers

    return transfers


@pytest.fixture
def grace_real(monkeypatch):
    monkeypatch.setattr(core_transfer, "RECONNECT_GRACE", REAL_GRACE)


@pytest.fixture
def restart(node_factory, app_helpers):
    """`await restart(label, **node_kwargs)` → `AppNode` (mới) cùng thư mục cấu hình, có `trec` mới."""

    async def make(label: str, **node_kwargs):
        trec = app_helpers.TransferRecorder(f"{label}'")
        node_kwargs.setdefault("on_transfer_event", trec.on_update)
        node = await node_factory(label, node_kwargs=node_kwargs)
        node.trec = trec
        return node

    return make


@pytest.fixture
def world(trust_each_other, tmp_path, app_helpers):
    """`world(*senders)` → (device_id của A, {nhãn: device_id}); A và mỗi máy gửi tin nhau."""

    def make(*senders: str):
        ids = {}
        for label in senders:
            _, ident = trust_each_other("A", label, name_b=label)
            ids[label] = ident.device_id
        return app_helpers.ensure_identity(tmp_path / "A").device_id, ids

    return make


@pytest.fixture
def restore_spy(monkeypatch):
    """Mọi lời gọi `TransferEngine.restore`: đối số (dãy đã chép thành tuple) và lỗi nếu có."""
    calls: list[SimpleNamespace] = []
    real = core_transfer.TransferEngine.restore

    def restore(self, *args, **kwargs):
        rec = SimpleNamespace(
            args=args,
            receives=tuple(kwargs.get("receives", ())),
            tombstones=tuple(kwargs.get("tombstones", ())),
            done=tuple(kwargs.get("done", ())),
            error=None,
        )
        calls.append(rec)
        try:
            return real(self, *args, **kwargs)
        except BaseException as e:
            rec.error = e
            raise

    monkeypatch.setattr(core_transfer.TransferEngine, "restore", restore)
    return calls


@pytest.fixture
def cleanup_spy(monkeypatch):
    """Mọi lần `ReceiveDir.cleanup` chạy xong: `(wall_now, skip, retention, số thư mục đã xóa)`."""
    calls: list[SimpleNamespace] = []
    real = storage.ReceiveDir.cleanup

    def cleanup(self, wall_now, *, own_device_id, skip, retention):
        n = real(self, wall_now, own_device_id=own_device_id, skip=skip, retention=retention)
        calls.append(SimpleNamespace(wall_now=wall_now, skip=frozenset(skip), retention=retention, removed=n))
        return n

    monkeypatch.setattr(storage.ReceiveDir, "cleanup", cleanup)
    return calls


@pytest.fixture
def write_spy(monkeypatch):
    spy = SimpleNamespace(done=[], lock=threading.Lock())
    real = storage.PartFile.write_at

    def write_at(self, index, data):
        real(self, index, data)
        with spy.lock:
            spy.done.append((self.path.parent.name, self.file_index, index))

    def count(tid: str) -> int:
        with spy.lock:
            return sum(1 for r in spy.done if r[0] == tid)

    spy.count = count
    monkeypatch.setattr(storage.PartFile, "write_at", write_at)
    return spy


class DiskOrder:
    """Nhật ký có thứ tự (an toàn giữa các thread) của các bước đóng: `("rd_close", rd)` lúc một
    `ReceiveDir` còn mở bắt đầu `close()`, `("close_temp", transfer_id)`, `("remove_temp", transfer_id)`,
    và các mốc test tự thêm (`add`). `opened`: mọi `ReceiveDir` mở qua `ReceiveDir.open` sau `install`."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.events: list[tuple[str, object]] = []
        self.opened: list[storage.ReceiveDir] = []

    def add(self, kind: str, what: object) -> None:
        with self.lock:
            self.events.append((kind, what))

    def reset(self) -> None:
        """Quên mọi thứ đã ghi (gọi sau khi test tự dựng thư mục nhận, trước khi mở node)."""
        with self.lock:
            self.events.clear()
            self.opened.clear()

    def index(self, kind: str, what: object) -> int | None:
        """Vị trí lần đầu có `(kind, what)` (so `rd` bằng `is`), không có → None."""
        with self.lock:
            for i, (k, w) in enumerate(self.events):
                if k == kind and (w is what or w == what):
                    return i
        return None

    def of(self, kind: str) -> list[object]:
        with self.lock:
            return [w for k, w in self.events if k == kind]

    def install(self, monkeypatch) -> None:
        spy = self
        real_open = storage.ReceiveDir.open
        real_close = storage.ReceiveDir.close
        real_close_temp = storage.ReceiveDir.close_temp
        real_remove = storage.ReceiveDir.remove_temp

        def open_(cls, root):
            rd = real_open(root)
            with spy.lock:
                spy.opened.append(rd)
            return rd

        def close(rd):
            if not rd.closed:
                spy.add("rd_close", rd)
            return real_close(rd)

        def close_temp(rd, temp):
            spy.add("close_temp", temp.transfer_id)
            return real_close_temp(rd, temp)

        def remove_temp(rd, temp, *, keep_record=False):
            spy.add("remove_temp", temp.transfer_id)
            return real_remove(rd, temp, keep_record=keep_record)

        monkeypatch.setattr(storage.ReceiveDir, "open", classmethod(open_))
        monkeypatch.setattr(storage.ReceiveDir, "close", close)
        monkeypatch.setattr(storage.ReceiveDir, "close_temp", close_temp)
        monkeypatch.setattr(storage.ReceiveDir, "remove_temp", remove_temp)


@pytest.fixture
def disk_order(monkeypatch):
    order = DiskOrder()
    order.install(monkeypatch)
    return order


class HangingOpen:
    """Thay `ReceiveDir.open_for_resume`: lượt trong `hung` chặn ở cổng (trong thread đĩa) rồi mới gọi bản
    thật với đúng `stop` nó nhận; ghi lại `stop` để kiểm nó đã được đặt khi quá hạn.

    `ignore_stop=True`: sau cổng gọi bản thật với `stop=None`, nên việc treo trả một `ResumeHandle` thật
    (kết quả tới muộn mà bên gọi phải tự đóng); `returned` giữ các handle đã trả như thế. `order`
    (`DiskOrder`): thêm `("open_done", transfer_id)` khi bản thật của việc treo trả về hay ném lỗi."""

    def __init__(self, hung, *, ignore_stop: bool = False, order: DiskOrder | None = None) -> None:
        self.hung = set(hung)
        self.gate = threading.Event()
        self.stops: dict[str, object] = {}
        self.real = storage.ReceiveDir.open_for_resume
        self.ignore_stop = ignore_stop
        self.order = order
        self.returned: dict[str, storage.ResumeHandle] = {}

    def install(self, monkeypatch) -> None:
        spy = self

        def open_for_resume(rd, scan, *, stop=None):
            tid = scan.transfer_id
            if tid not in spy.hung:
                return spy.real(rd, scan, stop=stop)
            spy.stops[tid] = stop
            spy.gate.wait(30)
            try:
                if spy.ignore_stop:
                    handle = spy.real(rd, scan, stop=None)
                    spy.returned[tid] = handle
                    return handle
                return spy.real(rd, scan, stop=stop)
            finally:
                if spy.order is not None:
                    spy.order.add("open_done", tid)

        monkeypatch.setattr(storage.ReceiveDir, "open_for_resume", open_for_resume)


# =================================================================================================
# V2 (c): `engine.restore` đúng một lần
# =================================================================================================


@leakcheck
@pytest.mark.parametrize("with_dir", [False, True], ids=["khong-thu-muc-nhan", "co-thu-muc-nhan"])
async def test_engine_restore_is_called_exactly_once_and_first(restore_spy, node_factory, tmp_path, with_dir):
    kwargs = {"receive_dir": tmp_path / "nhan", "auto_accept": True} if with_dir else {}
    A = await node_factory("A", node_kwargs=kwargs)
    assert len(restore_spy) == 1
    call = restore_spy[0]
    assert call.error is None, f"engine.restore ném {call.error!r} (không phải lời gọi đầu tiên?)"
    assert call.receives == () and call.done == () and call.tombstones == ()
    await A.close()
    assert len(restore_spy) == 1


@leakcheck
async def test_tombstones_of_node_without_receive_dir_survive_restart(
    restore_spy, node_factory, trust_each_other, tmp_path, app_helpers, grace_real
):
    _, id_b = trust_each_other("A", "B")
    a_id = app_helpers.ensure_identity(tmp_path / "A").device_id
    src = make_file(tmp_path / "nguon", "f.bin", 10)
    B = await node_factory("B")
    key = await B.transfers.send(a_id, [src])
    B.transfers.cancel(key)
    await B.close()
    B2 = await node_factory("B")
    assert B2.id == id_b.device_id
    call = restore_spy[-1]
    assert call.error is None
    assert [(t.device_id, t.direction, t.transfer_id, t.reason, t.unsent) for t in call.tombstones] == [
        (a_id, core_transfer.Direction.SEND, key.transfer_id, "user", True)
    ]
    assert all(0 <= t.age < 60 for t in call.tombstones)


# =================================================================================================
# V2 (c): nhiều lượt RUNNING của cùng một máy gửi → giữ lượt gần nhất
# =================================================================================================


@pytest.mark.slow
@leakcheck
@pytest.mark.parametrize("tie", [False, True], ids=["moi-nhat", "bang-nhau"])
async def test_several_running_from_one_sender_keep_latest_discard_others_and_cancel_expired(
    T, world, restart, node_factory, control_client, record_for, resume_helpers, tmp_path, grace_real, tie
):
    a_id, ids = world("C")
    c_id = ids["C"]
    root = tmp_path / "nhan"
    tids = sorted(uuid.uuid4().hex for _ in range(3))
    ages = [100.0, 100.0, 100.0] if tie else [300.0, 100.0, 200.0]
    for tid, age in zip(tids, ages, strict=True):
        build_running(
            storage,
            root,
            record_for,
            resume_helpers,
            tid,
            sender=c_id,
            receiver=a_id,
            blocks=(0, 1, 2),
            age=age,
        )
    keep = max(tids) if tie else tids[1]
    others = [t for t in tids if t != keep]

    A = await restart("A", receive_dir=root, auto_accept=True)
    resumed = A.trec.of("TransferResumed")
    assert [u.info.key.transfer_id for u in resumed] == [keep]
    info = resumed[0].info
    assert info.key == core_transfer.TransferKey(c_id, RECEIVE, keep)
    assert info.status == core_transfer.TransferStatus.RECONNECTING
    assert info.file_index == 0
    assert [(f.name, f.size) for f in info.files] == [("f0.bin", SIZE)]
    assert info.total_bytes == SIZE
    assert info.done_bytes == 3 * BLOCK_SIZE
    assert [i.key.transfer_id for i in A.transfers.transfers()] == [keep]
    await wait_until(
        lambda: all(not temp_dir(root, t).exists() for t in others),
        10,
        "lượt thừa chưa bị xóa (discard_temp)",
    )
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(temp_dir(root, keep)))

    C = await node_factory("C", auto_connect=False)
    cc = await control_client(C, A)
    await wait_until(
        lambda: all(messages(cc, Cancel, t) for t in others) and messages(cc, Resume, keep),
        10,
        "C chưa nhận cancel{expired} của lượt thừa và resume của lượt giữ lại",
    )
    for t in others:
        assert [m.reason for m in messages(cc, Cancel, t)] == ["expired"]
    assert messages(cc, Cancel, keep) == []
    order = [m for m in cc.received if getattr(m, "transfer_id", None) in tids]
    first_accept = next(i for i, m in enumerate(order) if isinstance(m, Accept | Resume))
    assert all(isinstance(m, Cancel) for m in order[:first_accept]) and first_accept == len(others), order
    [resume] = messages(cc, Resume, keep)
    assert resume.file_index == 0
    bits = Bitfield.from_base64(resume.bitfield, 6)
    assert {i for i in range(6) if i in bits} == {0, 1, 2}

    def saved() -> dict[str, rs.TombstoneRecord]:
        try:
            return {e.transfer_id: e for e in rs.decode_tombstones((A.dir / "tombstones.json").read_bytes())}
        except (FileNotFoundError, PermissionError, rs.StateError):
            return {}

    # Đọc file một lần mỗi lượt: trên Windows lần đọc thứ hai có thể rơi đúng lúc file đang được thay
    # (PermissionError → {}), nên giữ lại bản đọc đạt điều kiện để kiểm tiếp.
    snap: dict[str, rs.TombstoneRecord] = {}

    def all_sent() -> bool:
        nonlocal snap
        snap = saved()
        return all(t in snap and not snap[t].unsent for t in others)

    await wait_until(all_sent, 5, "tombstones.json chưa ghi bia mộ expired đã gửi")
    for t in others:
        e = snap[t]
        assert (e.device_id, e.direction, e.reason) == (c_id, "receive", "expired")


# =================================================================================================
# V2 (c): mở lại treo, hạn tổng
# =================================================================================================


@pytest.mark.slow
@leakcheck
async def test_hanging_open_for_resume_skips_only_that_transfer_and_start_stays_bounded(
    T, world, restart, record_for, resume_helpers, tmp_path, monkeypatch, grace_real
):
    deadline = 0.5
    monkeypatch.setattr(T, "DISK_SYNC_TIMEOUT", deadline)
    a_id, ids = world("C", "D")
    root = tmp_path / "nhan"
    hung, ok = uuid.uuid4().hex, uuid.uuid4().hex
    hung_dir = build_running(
        storage, root, record_for, resume_helpers, hung, sender=ids["C"], receiver=a_id, blocks=(0,), age=50
    )
    build_running(
        storage, root, record_for, resume_helpers, ok, sender=ids["D"], receiver=a_id, blocks=(0, 1), age=50
    )
    before = resume_helpers.snapshot(hung_dir)
    fake = HangingOpen([hung])
    fake.install(monkeypatch)
    try:
        t0 = time.monotonic()
        A = await restart("A", receive_dir=root, auto_accept=True)
        elapsed = time.monotonic() - t0
        assert elapsed <= deadline + 3.0, f"Node.start mất {elapsed:.2f} s dù chỉ một lượt treo"
        assert [u.info.key.transfer_id for u in A.trec.of("TransferResumed")] == [ok]
        assert [i.key.transfer_id for i in A.transfers.transfers()] == [ok]
        stop = fake.stops.get(hung)
        assert isinstance(stop, threading.Event), "open_for_resume phải nhận `stop`"
        assert stop.is_set(), "quá hạn mở lại phải đặt `stop`"
    finally:
        fake.gate.set()
    await asyncio.sleep(0.5)  # lượt treo chạy nốt (bị `stop` chặn) và kết quả muộn được dọn
    assert resume_helpers.snapshot(hung_dir) == before, "lượt quá hạn phải để nguyên trên đĩa"


@pytest.mark.slow
@leakcheck
async def test_more_hanging_restores_than_disk_threads_still_bound_start_by_total_deadline(
    T, world, restart, record_for, resume_helpers, tmp_path, monkeypatch, grace_real
):
    """spec-p3-3b mục 8.1.6: > `DISK_THREADS` lượt cùng treo → `Node.start` xong trong
    `DISK_SYNC_TIMEOUT × ⌈k / DISK_THREADS⌉` + ε; mọi lượt để nguyên, không lượt nào được khôi phục."""
    from teleport.app import diskio

    deadline = 0.5
    monkeypatch.setattr(T, "DISK_SYNC_TIMEOUT", deadline)
    k = diskio.DISK_THREADS + 1
    labels = [f"S{i}" for i in range(k)]
    a_id, ids = world(*labels)
    root = tmp_path / "nhan"
    tids = [uuid.uuid4().hex for _ in labels]
    dirs = [
        build_running(
            storage,
            root,
            record_for,
            resume_helpers,
            tid,
            sender=ids[label],
            receiver=a_id,
            blocks=(0,),
            age=50,
        )
        for tid, label in zip(tids, labels, strict=True)
    ]
    before = [resume_helpers.snapshot(d) for d in dirs]
    fake = HangingOpen(tids)
    fake.install(monkeypatch)
    try:
        t0 = time.monotonic()
        A = await restart("A", receive_dir=root, auto_accept=True)
        elapsed = time.monotonic() - t0
        total = deadline * -(-k // diskio.DISK_THREADS)
        assert elapsed <= total + 3.0, f"Node.start mất {elapsed:.2f} s (hạn tổng {total} s)"
        assert A.trec.of("TransferResumed") == []
        assert A.transfers.transfers() == ()
    finally:
        fake.gate.set()
    await asyncio.sleep(0.5)
    assert [resume_helpers.snapshot(d) for d in dirs] == before


# =================================================================================================
# V2 (c): lượt quá hạn nối lại, máy gửi không còn tin cậy, engine lỗi
# =================================================================================================


@leakcheck
async def test_restored_transfer_older_than_reconnect_grace_expires_without_transfer_resumed(
    T, world, restart, node_factory, control_client, record_for, resume_helpers, tmp_path, monkeypatch
):
    """Q4 + spec-p3 P3-2: tuổi ≥ `RECONNECT_GRACE` → không `TransferResumed`; hết hạn ngay (thư mục tạm bị
    xóa, bia mộ `expired`), máy gửi nối vào thì nhận `cancel{expired}`."""
    monkeypatch.setattr(core_transfer, "RECONNECT_GRACE", 600.0)
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=ids["C"], receiver=a_id, blocks=(0,), age=3600
    )
    A = await restart("A", receive_dir=root, auto_accept=True)
    assert A.trec.of("TransferResumed") == []
    fin = await A.trec.wait_finished(tid, 10)
    assert fin.result == T.TransferResult.EXPIRED, describe(fin)
    await wait_until(lambda: not d.exists(), 10, "thư mục tạm của lượt quá hạn chưa bị xóa")
    C = await node_factory("C", auto_connect=False)
    cc = await control_client(C, A)
    await wait_until(lambda: messages(cc, Cancel, tid), 10, "C chưa nhận cancel")
    assert [m.reason for m in messages(cc, Cancel, tid)] == ["expired"]


@leakcheck
async def test_engine_restore_error_retries_once_without_receives_and_keeps_temp(
    T, world, restart, record_for, resume_helpers, tmp_path, monkeypatch, caplog, grace_real
):
    """spec-p3-3b mục 8.1.8: `engine.restore` ném ValueError → `log.exception`, gọi lại đúng một lần với
    `receives=()` (bia mộ, lượt xong giữ nguyên); lượt vừa mở được đóng kiểu tạm dừng (`close_temp`), đĩa
    không mất gì; node vẫn chạy."""
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=ids["C"], receiver=a_id, blocks=(0, 1), age=50
    )
    before = content_of(d)
    calls: list[dict] = []
    real = core_transfer.TransferEngine.restore

    def restore(self, **kwargs):
        calls.append({k: tuple(v) if k != "now" else v for k, v in kwargs.items()})
        if len(calls) == 1:
            raise ValueError("lỗi giả của engine.restore")
        return real(self, **kwargs)

    removed: list[str] = []
    real_remove = storage.ReceiveDir.remove_temp

    def remove_temp(self, temp, *, keep_record=False):
        removed.append(temp.path.name)
        return real_remove(self, temp, keep_record=keep_record)

    monkeypatch.setattr(core_transfer.TransferEngine, "restore", restore)
    monkeypatch.setattr(storage.ReceiveDir, "remove_temp", remove_temp)
    caplog.set_level(logging.ERROR)
    A = await restart("A", receive_dir=root, auto_accept=True)
    assert len(calls) == 2
    assert len(calls[0]["receives"]) == 1 and calls[1]["receives"] == ()
    assert calls[1]["tombstones"] == calls[0]["tombstones"] and calls[1]["done"] == calls[0]["done"]
    assert A.trec.of("TransferResumed") == [] and A.transfers.transfers() == ()
    assert any(r.levelno >= logging.ERROR and r.name.startswith("teleport") for r in caplog.records)
    await asyncio.sleep(0.3)
    assert removed == []
    assert content_of(d) == before


@pytest.mark.slow
@leakcheck
async def test_sender_unpaired_while_receiver_was_off_is_not_restored_and_dir_untouched(
    T, transfer_nodes, restart, write_spy, cleanup_spy, resume_helpers, grace_real
):
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 4, 20, "A chưa ghi khối nào")
    tm = A.transfers
    await asyncio.wait_for(A.close(), 15)
    # Việc đĩa đang chạy (vd. `commit` nối `MARK` vào `.state`) vẫn chạy ở đuôi đĩa sau `close()`;
    # thư mục nhận chỉ đóng khi chúng đã xong, nên chờ nó rồi mới chụp.
    rd = tm._receive_dir
    await wait_until(lambda: rd is None or rd.closed, 15, "đuôi đĩa của A chưa xong")
    TrustStore.load(A.dir).remove(B.id)
    d = temp_dir(net.receive_dir, tid)
    before = resume_helpers.snapshot(d)
    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    await wait_until(lambda: len(cleanup_spy) >= 1, 5, "hẹn giờ dọn chưa chạy lần đầu")
    assert A2.trec.of("TransferResumed") == [] and A2.transfers.transfers() == ()
    assert resume_helpers.snapshot(d) == before


# =================================================================================================
# V2 (c): `VERIFY_TARGET` mà file đích sai → nhận lại vào tên mới, file đích không đổi
# =================================================================================================


@pytest.mark.slow
@leakcheck
async def test_restored_verify_target_with_wrong_target_is_received_again_under_new_name(
    T, transfer_nodes, restart, tcp_proxy, resume_helpers, monkeypatch, tmp_path, grace_real
):
    """“Sập” ngay sau khi đổi tên file 0 (seam `_after_replace`: chép cây thư mục nhận, đồng thời chặn proxy
    để `verified` không tới B). Mở A trên bản chép với file đích bị sửa 1 byte → lượt khôi phục ở
    `VERIFY_TARGET`; B gửi lại `complete`, A đọc lại file đích, thấy sai → nhận lại cả file vào tên mới;
    file đích sai để nguyên; lượt DONE, cả hai file khớp nguồn."""
    net = await transfer_nodes(connect=False, sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    proxy = tcp_proxy(A.port)
    B.connect_hint(A.id, [LOCAL], proxy.port)
    await wait_until(lambda: A.id in B.connected_devices(), 5, "B chưa nối qua proxy")
    f0 = make_file(net.src, "a.bin", 3 * MiB + 5)
    f1 = make_file(net.src, "b.bin", 4 * MiB)
    crash = tmp_path / "sap"
    copied = threading.Event()

    def after_replace(target):
        if not copied.is_set() and Path(target).name == "a.bin":
            proxy.block()
            resume_helpers.crash_copy(net.receive_dir, crash)
            copied.set()

    monkeypatch.setattr(storage, "_after_replace", after_replace)
    key = await B.transfers.send(A.id, [f0, f1])
    tid = key.transfer_id
    await wait_until(copied.is_set, 30, "chưa tới bước đổi tên file 0")
    await asyncio.wait_for(A.close(), 15)
    proxy.rst()
    target = crash / "a.bin"
    wrong = bytearray(target.read_bytes())
    wrong[MiB + 1] ^= 0xFF
    target.write_bytes(bytes(wrong))

    A2 = await restart("A", receive_dir=crash, auto_accept=True)
    [resumed] = A2.trec.of("TransferResumed", tid)
    assert resumed.info.file_index == 0
    proxy.target = (LOCAL, A2.port)
    proxy.resume()
    fin_b = await B.trec.wait_finished(tid, 60)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_b.result == T.TransferResult.DONE, describe(fin_b)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert target.read_bytes() == bytes(wrong), "file đích sai phải để nguyên"
    done = {u.file_index: u for u in A2.trec.of("FileDone", tid)}
    assert set(done) == {0, 1}
    assert done[0].path is not None and done[0].path != target
    assert sha256_of(done[0].path) == sha256_of(f0)
    assert sha256_of(done[1].path) == sha256_of(f1)


# =================================================================================================
# V3: các ca trong tiến trình
# =================================================================================================


@pytest.mark.slow
@leakcheck
async def test_sender_that_lost_its_state_answers_unknown_transfer_and_receiver_cleans_up(
    T, transfer_nodes, restart, write_spy, grace_real
):
    """Bên gửi đã khởi động lại mà không còn biết lượt (như bị giết trước khi kịp lưu bia mộ) → A khôi phục
    lượt, gửi `accept`/`resume`, nhận `cancel{unknown_transfer}` → `UNKNOWN_TRANSFER`, dọn thư mục tạm."""
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 4, 20, "A chưa ghi khối nào")
    await asyncio.wait_for(A.close(), 15)
    await asyncio.wait_for(B.close(), 15)
    (B.dir / "tombstones.json").unlink(missing_ok=True)
    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    assert len(A2.trec.of("TransferResumed", tid)) == 1
    B2 = await restart("B")
    B2.connect_hint(A2.id, [LOCAL], A2.port)
    fin = await A2.trec.wait_finished(tid, 20)
    assert fin.result == T.TransferResult.UNKNOWN_TRANSFER and fin.by_peer is True, describe(fin)
    await wait_until(lambda: not temp_dir(net.receive_dir, tid).exists(), 10, "thư mục tạm chưa bị dọn")


@pytest.mark.slow
@leakcheck
async def test_receiver_tombstone_survives_restart_sender_gets_cancel_user_and_no_new_offer_prompt(
    T, transfer_nodes, restart, tcp_proxy, write_spy, grace_real
):
    net = await transfer_nodes(connect=False, sender_opts={"rate_limit": 4 * MiB})
    A, B = net.A, net.B
    proxy = tcp_proxy(A.port)
    B.connect_hint(A.id, [LOCAL], proxy.port)
    await wait_until(lambda: A.id in B.connected_devices() and B.id in A.connected_devices(), 5)
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa ghi khối nào")
    proxy.block()
    proxy.rst()
    await wait_until(
        lambda: B.id not in A.connected_devices() and A.id not in B.connected_devices(),
        10,
        "chưa mất kết nối",
    )
    A.transfers.cancel(core_transfer.TransferKey(B.id, RECEIVE, tid))
    fin_a = await A.trec.wait_finished(tid, 5)
    assert fin_a.result == T.TransferResult.CANCELLED_USER and fin_a.by_peer is False
    await asyncio.wait_for(A.close(), 15)
    stones = rs.decode_tombstones((A.dir / "tombstones.json").read_bytes())
    assert [(e.device_id, e.direction, e.transfer_id, e.reason, e.unsent) for e in stones] == [
        (B.id, "receive", tid, "user", True)
    ]

    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    proxy.target = (LOCAL, A2.port)
    proxy.resume()
    fin_b = await B.trec.wait_finished(tid, 30)
    assert fin_b.result == T.TransferResult.CANCELLED_USER and fin_b.by_peer is True, describe(fin_b)
    await asyncio.sleep(0.5)
    assert A2.trec.of("OfferReceived", tid) == [], "lượt có bia mộ không được hỏi lại"
    assert not temp_dir(net.receive_dir, tid).exists()


@pytest.mark.slow
@leakcheck
async def test_sender_closed_while_disconnected_sends_unsent_cancel_after_restart_and_new_send_works(
    T, transfer_nodes, restart, tcp_proxy, write_spy, grace_real
):
    """`send` Ctrl+C khi mất kết nối (B đóng lúc không có kết nối điều khiển) rồi `send` mới (B mở lại):
    `cancel{user}` chưa gửi tới được A ngay khi nối lại; A dọn thư mục tạm; lượt mới chạy bình thường."""
    net = await transfer_nodes(connect=False, sender_opts={"rate_limit": 4 * MiB})
    A, B = net.A, net.B
    proxy = tcp_proxy(A.port)
    B.connect_hint(A.id, [LOCAL], proxy.port)
    await wait_until(lambda: A.id in B.connected_devices() and B.id in A.connected_devices(), 5)
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa ghi khối nào")
    proxy.block()
    proxy.rst()
    await wait_until(lambda: A.id not in B.connected_devices(), 10, "B chưa mất kết nối")
    await asyncio.wait_for(B.close(), 15)
    assert B.trec.finished(tid).result == T.TransferResult.CANCELLED_USER
    stones = rs.decode_tombstones((B.dir / "tombstones.json").read_bytes())
    assert [(e.device_id, e.direction, e.transfer_id, e.reason, e.unsent) for e in stones] == [
        (A.id, "send", tid, "user", True)
    ]
    assert A.trec.finished(tid) is None

    proxy.resume()
    B2 = await restart("B")
    B2.connect_hint(A.id, [LOCAL], proxy.port)
    fin_a = await A.trec.wait_finished(tid, 30)
    assert fin_a.result == T.TransferResult.CANCELLED_USER and fin_a.by_peer is True, describe(fin_a)
    await wait_until(lambda: not temp_dir(net.receive_dir, tid).exists(), 10, "thư mục tạm chưa bị dọn")

    src2 = make_file(net.src, "moi.bin", MiB + 1)
    key2 = await B2.transfers.send(A.id, [src2])
    assert (await B2.trec.wait_finished(key2.transfer_id, 30)).result == T.TransferResult.DONE
    assert sha256_of(net.receive_dir / "moi.bin") == sha256_of(src2)


@leakcheck
async def test_done_transfer_answers_verified_after_restart_and_record_is_cleaned_after_remember_ttl(
    T, transfer_nodes, restart, control_client, cleanup_spy, monkeypatch, grace_real
):
    net = await transfer_nodes()
    A, B = net.A, net.B
    src = make_file(net.src, "f.bin", 3 * MiB + 1)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    assert (await A.trec.wait_finished(tid, 30)).result == T.TransferResult.DONE
    d = temp_dir(net.receive_dir, tid)
    await wait_until(lambda: d.is_dir() and os.listdir(d) == ["transfer.json"], 10, "chỉ còn transfer.json")
    peer_b = SimpleNamespace(identity=B.identity, hello=B.hello)
    await asyncio.wait_for(B.close(), 15)
    await asyncio.wait_for(A.close(), 15)

    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    assert A2.trec.of("TransferResumed") == []
    await wait_until(lambda: len(cleanup_spy) >= 1, 5, "hẹn giờ dọn chưa chạy lần đầu")
    assert os.listdir(d) == ["transfer.json"], "lượt xong còn trong hạn nhớ không được dọn"
    cc = await control_client(peer_b, A2)
    await cc.conn.send(Complete(tid, 0, merkle_root(leaves_of(src.read_bytes())).hex()))
    await wait_until(lambda: messages(cc, Verified, tid), 10, "A không trả verified sau khởi động lại")
    assert [m.file_index for m in messages(cc, Verified, tid)] == [0]
    assert messages(cc, Cancel, tid) == []
    await asyncio.wait_for(A2.close(), 15)

    monkeypatch.setattr(T, "_wall_time", lambda: time.time() + core_transfer.REMEMBER_TTL + 3600)
    n = len(cleanup_spy)
    await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    await wait_until(lambda: len(cleanup_spy) > n, 5, "hẹn giờ dọn chưa chạy")
    await wait_until(lambda: not d.exists(), 10, "transfer.json quá hạn nhớ chưa bị dọn")
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src), "file đã nhận không được đụng"
    assert (net.receive_dir / ".teleport").is_dir()


@pytest.mark.slow
@leakcheck
async def test_two_configs_sharing_receive_dir_do_not_touch_each_other(
    T, transfer_nodes, restart, write_spy, cleanup_spy, resume_helpers, app_helpers, tmp_path, grace_real
):
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    src = make_file(net.src, "f.bin", 16 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 4, 20, "A chưa ghi khối nào")
    await asyncio.wait_for(A.close(), 15)
    d = temp_dir(net.receive_dir, tid)
    before = resume_helpers.snapshot(d)

    app_helpers.ensure_identity(tmp_path / "C")
    app_helpers.seed_trust(tmp_path / "C", B.identity.cert_pem(), "B")  # C cũng tin máy gửi B
    n = len(cleanup_spy)
    C = await restart("C", receive_dir=net.receive_dir, auto_accept=True)
    await wait_until(lambda: len(cleanup_spy) > n, 5, "hẹn giờ dọn của C chưa chạy")
    assert C.trec.of("TransferResumed") == [] and C.transfers.transfers() == ()
    assert resume_helpers.snapshot(d) == before, (
        "node khác dùng chung thư mục nhận không được đụng lượt của A"
    )
    await asyncio.wait_for(C.close(), 15)
    assert resume_helpers.snapshot(d) == before

    A2 = await restart("A", receive_dir=net.receive_dir, auto_accept=True)
    B.connect_hint(A2.id, [LOCAL], A2.port)
    fin_a = await A2.trec.wait_finished(tid, 60)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


@pytest.mark.slow
@leakcheck
async def test_cleanup_timer_never_removes_running_transfer(
    T, transfer_nodes, write_spy, cleanup_spy, monkeypatch, grace_real
):
    """Hẹn giờ dọn (rút ngắn `CLEANUP_INTERVAL`) chạy nhiều lần trong lúc lượt đang nhận, với giờ tường
    vá xa hơn mọi ngưỡng: `skip` luôn có lượt đó, thư mục tạm còn, lượt DONE."""
    monkeypatch.setattr(T, "CLEANUP_INTERVAL", 0.2)
    net = await transfer_nodes(sender_opts={"rate_limit": 4 * MiB})
    A, B = net.A, net.B
    src = make_file(net.src, "f.bin", 12 * MiB)
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: write_spy.count(tid) >= 2, 20, "A chưa ghi khối nào")
    future = time.time() + 10 * core_transfer.REMEMBER_TTL
    monkeypatch.setattr(T, "_wall_time", lambda: future)
    n = len(cleanup_spy)
    await wait_until(lambda: len(cleanup_spy) >= n + 2, 5, "hẹn giờ dọn không chạy lặp lại")
    assert temp_dir(net.receive_dir, tid).is_dir()
    fin_a = await A.trec.wait_finished(tid, 60)
    assert fin_a.result == T.TransferResult.DONE, describe(fin_a)
    during = [c for c in cleanup_spy[n:] if c.wall_now == future]
    assert during and all(tid in c.skip for c in during[:2]), [sorted(c.skip) for c in during]
    assert all(c.retention == storage.TEMP_RETENTION for c in cleanup_spy)
    assert sha256_of(net.receive_dir / "f.bin") == sha256_of(src)


# =================================================================================================
# P3-5 V10: dọn tạm 7 ngày qua `Node.start` (mvp F6; architecture mục 4 “Dọn tạm”)
# =================================================================================================


def newest_mtime(d: Path) -> float:
    """mtime lớn nhất của thư mục `d` và mọi file trong nó (giây)."""
    return max([d.stat().st_mtime, *(p.stat().st_mtime for p in d.iterdir())])


@leakcheck
@pytest.mark.parametrize(
    ("offset", "removed"), [(3600.0, True), (-3600.0, False)], ids=["qua-han", "con-han"]
)
async def test_node_start_cleans_orphan_and_other_node_temps_only_past_temp_retention(
    T,
    world,
    restart,
    cleanup_spy,
    record_for,
    resume_helpers,
    tmp_path,
    monkeypatch,
    grace_real,
    offset,
    removed,
):
    """spec-p3-5 V10 (mục 3, 9.2): thư mục tạm không thuộc lượt nào còn sống (mồ côi: không có
    `transfer.json`; hỏng: `transfer.json` không đọc được; node khác dùng chung thư mục nhận) bị dọn ở lần
    dọn đầu tiên sau `Node.start` khi hoạt động cuối cách giờ tường hơn `TEMP_RETENTION` (+1 giờ); còn hạn
    (−1 giờ) thì giữ nguyên từng byte. Giờ tường vá qua `_wall_time` (mẫu ở test REMEMBER_TTL).

    Không có ca “máy gửi không còn tin cậy” (`receiver` là máy này): `ReceiveDir.cleanup` xếp nó vào lượt
    của máy này, ngưỡng `RECONNECT_GRACE` (architecture mục 4); ca đó có ở
    `test_running_transfer_of_untrusted_sender_is_not_reopened_and_is_cleaned_after_reconnect_grace` (qua
    `Node.start`, cuối file này) và
    `test_storage_cleanup.py::test_cleanup_running_with_untrusted_sender_is_still_this_nodes`."""
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    other_node = uuid.uuid4().hex
    tids = {kind: uuid.uuid4().hex for kind in ("mo-coi", "hong", "node-khac")}
    owners = {"mo-coi": a_id, "hong": a_id, "node-khac": other_node}
    dirs = {}
    for kind, tid in tids.items():
        dirs[kind] = build_running(
            storage,
            root,
            record_for,
            resume_helpers,
            tid,
            sender=ids["C"],
            receiver=owners[kind],
            blocks=(0, 1),
            age=0,
        )
    (dirs["mo-coi"] / "transfer.json").unlink()
    (dirs["hong"] / "transfer.json").write_bytes(b"{khong phai json")
    before = {kind: resume_helpers.snapshot(d) for kind, d in dirs.items()}
    wall = max(newest_mtime(d) for d in dirs.values()) + storage.TEMP_RETENTION + offset
    monkeypatch.setattr(T, "_wall_time", lambda: wall)

    A = await restart("A", receive_dir=root, auto_accept=True)
    await wait_until(lambda: len(cleanup_spy) >= 1, 5, "lần dọn đầu sau Node.start chưa chạy")
    first = cleanup_spy[0]
    assert first.wall_now == wall and first.retention == storage.TEMP_RETENTION
    assert A.trec.of("TransferResumed") == [] and A.transfers.transfers() == ()
    if removed:
        assert first.removed == len(dirs)
        assert {kind for kind, d in dirs.items() if d.exists()} == set()
    else:
        assert first.removed == 0
        assert {kind: resume_helpers.snapshot(d) for kind, d in dirs.items()} == before
    assert (root / ".teleport").is_dir(), ".teleport không bao giờ bị xóa"


# =================================================================================================
# P3-5 V11d: `skip` gồm hàng đĩa còn sống của lượt engine đã quên (transfers.py `cleanup_temps`)
# =================================================================================================


@leakcheck
async def test_cleanup_skips_transfer_forgotten_by_engine_while_its_disk_lane_still_runs(
    T, transfer_nodes, cleanup_spy, monkeypatch, grace_real
):
    """spec-p3-5 V11d (mục 3, 9.2 N8): hàng đĩa của lượt nhận kẹt ở một lần ghi (cổng trong
    `PartFile.write_at`); A hủy lượt → engine quên lượt (`get` → None) nhưng hàng đĩa chưa dọn xong. Lần
    dọn tạm lúc đó (giờ tường vá xa hơn mọi ngưỡng) phải nhận `skip` có `transfer_id` của lượt (spy tham
    số: `ReceiveDir.cleanup` tự bỏ thư mục đang mở nên chỉ nhìn đĩa thì không phân biệt được); thư mục
    còn. Mở cổng → `RemoveTemp` của hàng đĩa xóa nó."""
    net = await transfer_nodes(sender_opts={"rate_limit": 8 * MiB})
    A, B = net.A, net.B
    gate, hit = threading.Event(), threading.Event()
    real_write = storage.PartFile.write_at

    def write_at(self, index, data):
        if index == 1 and not gate.is_set():
            hit.set()
            gate.wait(30)
        real_write(self, index, data)

    monkeypatch.setattr(storage.PartFile, "write_at", write_at)
    key = await B.transfers.send(A.id, [make_file(net.src, "f.bin", 16 * MiB)])
    tid = key.transfer_id
    rkey = core_transfer.TransferKey(B.id, RECEIVE, tid)
    d = temp_dir(net.receive_dir, tid)
    future = time.time() + 10 * max(core_transfer.REMEMBER_TTL, storage.TEMP_RETENTION)
    try:
        await asyncio.wait_for(asyncio.to_thread(hit.wait, 20), 25)
        assert A.transfers.get(rkey) is not None
        A.transfers.cancel(rkey)
        await wait_until(lambda: A.transfers.get(rkey) is None, 5, "engine chưa quên lượt đã hủy")
        monkeypatch.setattr(T, "_wall_time", lambda: future)
        n = len(cleanup_spy)
        while True:
            assert A.transfers.get(rkey) is None  # không `await` giữa kiểm này và lúc chụp `skip`
            result = await A.transfers.cleanup_temps()
            if result is not None:
                break
            await asyncio.sleep(0.05)  # lần dọn lúc khởi động chưa xong
        calls = [c for c in cleanup_spy[n:] if c.wall_now == future]
        assert len(calls) == 1, calls
        assert tid in calls[0].skip, f"skip = {sorted(calls[0].skip)} thiếu lượt có hàng đĩa còn sống"
        assert d.is_dir(), "thư mục tạm của lượt có hàng đĩa còn sống bị dọn"
        assert not gate.is_set()
    finally:
        gate.set()
    await wait_until(lambda: not d.exists(), 10, "RemoveTemp chưa xóa thư mục tạm sau khi mở cổng")
    fin_b = await B.trec.wait_finished(tid, 10)
    assert fin_b.result == T.TransferResult.CANCELLED_USER and fin_b.by_peer is True, describe(fin_b)


# =================================================================================================
# P3-5 V11e: lỗi của `open_for_resume` khi khôi phục (transfers.py `_restore_open`)
# =================================================================================================


def open_error(kind: str, tid: str, path: Path) -> BaseException:
    """Lỗi giả của `open_for_resume`, mang `transfer_id` đầy đủ và đường dẫn trong thông điệp."""
    text = f"lỗi giả {tid} {path}"
    if kind == "OSError":
        return OSError(errno.EIO, text, str(path))
    return {
        "NotResumableError": storage.NotResumableError,
        "StorageError": storage.StorageError,
        "ValueError": ValueError,
        "RuntimeError": RuntimeError,
    }[kind](text)


@pytest.mark.slow
@leakcheck
@pytest.mark.parametrize(
    "kind", ["NotResumableError", "StorageError", "ValueError", "OSError", "RuntimeError"]
)
async def test_open_for_resume_error_logs_label_only_and_other_transfer_still_resumes(
    T,
    world,
    restart,
    cleanup_spy,
    record_for,
    resume_helpers,
    tmp_path,
    monkeypatch,
    caplog,
    grace_real,
    kind,
):
    """spec-p3-5 V11e (mục 3): `open_for_resume` của một lượt ném lỗi khi `Node.start`.

    `NotResumableError` / `StorageError` / `ValueError` / `OSError` → đúng một INFO có `transfer_id[:8]` và
    tên loại lỗi, không `transfer_id` đầy đủ, tên file hay đường dẫn (mvp N9, kế hoạch mục 3.7), không
    WARNING+ nào.
    `RuntimeError` (không lường trước) → một ERROR kèm traceback. Cả hai: node chạy, thư mục tạm của lượt
    lỗi giữ nguyên từng byte, lượt của máy gửi khác vẫn `TransferResumed`."""
    caplog.set_level(logging.INFO)
    a_id, ids = world("C", "D")
    root = tmp_path / "nhan"
    bad, ok = uuid.uuid4().hex, uuid.uuid4().hex
    d_bad = build_running(
        storage, root, record_for, resume_helpers, bad, sender=ids["C"], receiver=a_id, blocks=(0,), age=50
    )
    build_running(
        storage, root, record_for, resume_helpers, ok, sender=ids["D"], receiver=a_id, blocks=(0, 1), age=50
    )
    before = resume_helpers.snapshot(d_bad)
    error = open_error(kind, bad, d_bad / "0.part")
    real_open = storage.ReceiveDir.open_for_resume
    raised: list[str] = []

    def open_for_resume(rd, scan, *, stop=None):
        if scan.transfer_id == bad:
            raised.append(bad)
            raise error
        return real_open(rd, scan, stop=stop)

    monkeypatch.setattr(storage.ReceiveDir, "open_for_resume", open_for_resume)
    A = await restart("A", receive_dir=root, auto_accept=True)
    assert raised == [bad]
    assert A.node.port is not None
    assert [u.info.key.transfer_id for u in A.trec.of("TransferResumed")] == [ok]
    assert [i.key.transfer_id for i in A.transfers.transfers()] == [ok]
    await wait_until(lambda: len(cleanup_spy) >= 1, 5, "lần dọn đầu sau Node.start chưa chạy")
    assert resume_helpers.snapshot(d_bad) == before

    records = [r for r in caplog.records if r.name.startswith("teleport")]
    about = [r for r in records if bad[:8] in r.getMessage()]
    assert len(about) == 1, [(r.levelname, r.getMessage()) for r in about]
    [rec] = about
    if kind == "RuntimeError":
        assert rec.levelno == logging.ERROR, rec.levelname
        assert rec.exc_info is not None and rec.exc_info[1] is error, "ERROR phải kèm traceback"
    else:
        assert rec.levelno == logging.INFO, rec.levelname
        assert type(error).__name__ in rec.getMessage(), rec.getMessage()
        loud = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert loud == [], [(r.name, r.levelname, r.getMessage()) for r in loud]
        assert rec.exc_info is None
    for r in records:
        text = r.getMessage()
        assert bad not in text and str(root) not in text and "f0.bin" not in text, text


# =================================================================================================
# API của `TransferManager`: `restore` một lần, `cleanup_temps`, `abort_now` giữa lúc khôi phục
# =================================================================================================


@leakcheck
async def test_transfer_manager_restore_twice_raises_runtime_error(node_factory, tmp_path):
    A = await node_factory("A", node_kwargs={"receive_dir": tmp_path / "nhan", "auto_accept": True})
    with pytest.raises(RuntimeError):
        await A.transfers.restore()


@leakcheck
async def test_cleanup_temps_is_none_without_receive_dir_or_when_closing(node_factory, tmp_path):
    B = await node_factory("B")
    assert await B.transfers.cleanup_temps() is None
    A = await node_factory("A", node_kwargs={"receive_dir": tmp_path / "nhan", "auto_accept": True})
    results: list[int | None] = []

    async def until_ran() -> None:
        while True:
            n = await A.transfers.cleanup_temps()  # None khi lần dọn trước (lúc khởi động) chưa xong
            if n is not None:
                results.append(n)
                return
            await asyncio.sleep(0.05)

    await asyncio.wait_for(until_ran(), 5)
    assert results == [0]
    A.transfers.begin_close()
    assert await A.transfers.cleanup_temps() is None


@pytest.fixture
def submit_spy(monkeypatch, T):
    """Mọi lời gọi `DiskExecutor.submit`: tên hàm được giao, có ném `RuntimeError` không, và đã có
    `TransferManager.abort_now` trước đó chưa (spy `abort_now` đếm số lần)."""
    from teleport.app import diskio

    spy = SimpleNamespace(calls=[], aborts=0)
    real_submit = diskio.DiskExecutor.submit
    real_abort = T.TransferManager.abort_now

    def submit(self, fn, /, *args):
        name = getattr(getattr(fn, "func", fn), "__name__", repr(fn))
        rec = SimpleNamespace(name=name, raised=None, after_abort=spy.aborts > 0)
        spy.calls.append(rec)
        try:
            return real_submit(self, fn, *args)
        except RuntimeError as e:
            rec.raised = e
            raise

    def abort_now(self):
        spy.aborts += 1
        return real_abort(self)

    def rejected_after_abort() -> list[SimpleNamespace]:
        return [c for c in spy.calls if c.after_abort and c.raised is not None]

    spy.rejected_after_abort = rejected_after_abort
    monkeypatch.setattr(diskio.DiskExecutor, "submit", submit)
    monkeypatch.setattr(T.TransferManager, "abort_now", abort_now)
    return spy


def errors_logged(caplog) -> list[logging.LogRecord]:
    """Bản ghi ERROR+ của mọi logger (kể cả `asyncio`: “Task exception was never retrieved”)."""
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


async def cancel_start_during_restore(node_factory, root: Path, tid: str, fake: HangingOpen, submit_spy):
    """Mở A với thư mục nhận `root`, hủy `Node.start` khi việc mở lại lượt `tid` đang treo ở cổng của
    `fake`, rồi mở cổng. Trả `stop` mà việc mở lại đã nhận (đã kiểm là `threading.Event`, đã đặt)."""
    A = await node_factory("A", start=False, node_kwargs={"receive_dir": root, "auto_accept": True})
    starting = asyncio.create_task(A.node.start())
    try:
        await wait_until(lambda: tid in fake.stops, 10, "chưa tới bước mở lại")
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        stop = fake.stops[tid]
        assert isinstance(stop, threading.Event) and stop.is_set()
        assert submit_spy.aborts == 1, f"abort_now chạy {submit_spy.aborts} lần"
    finally:
        fake.gate.set()
    return stop


@pytest.mark.slow
@leakcheck
async def test_start_cancelled_during_restore_sets_stop_and_leaves_disk_untouched(
    world,
    node_factory,
    app_helpers,
    record_for,
    resume_helpers,
    submit_spy,
    tmp_path,
    monkeypatch,
    caplog,
    grace_real,
):
    """`Node.start` bị hủy khi đang mở lại một lượt (thread đĩa treo) → `abort_now` (đúng một lần) đặt
    `stop` của việc mở lại; lượt đó để nguyên trên đĩa, `node.lock` được nhả; không có ERROR nào, kể cả
    ngoại lệ task không ai lấy (V11c, spec-p3-5 mục 3)."""
    caplog.set_level(logging.WARNING)
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=ids["C"], receiver=a_id, blocks=(0,), age=50
    )
    before = resume_helpers.snapshot(d)
    fake = HangingOpen([tid])
    fake.install(monkeypatch)
    await cancel_start_during_restore(node_factory, root, tid, fake, submit_spy)
    await asyncio.sleep(0.5)  # việc treo chạy nốt (bị `stop` chặn), không được đụng đĩa
    gc.collect()  # ngoại lệ task không ai lấy chỉ được báo khi task bị thu gom
    await asyncio.sleep(0)
    assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]
    assert resume_helpers.snapshot(d) == before
    await wait_until(lambda: app_helpers.lock_is_free(tmp_path / "A"), 5, "node.lock chưa được nhả")


def receive_dir_of_node(order: DiskOrder) -> storage.ReceiveDir:
    """`ReceiveDir` duy nhất mở qua `ReceiveDir.open` từ lần `order.reset()` cuối (của node đang thử)."""
    assert len(order.opened) == 1, f"mong đúng một ReceiveDir được node mở, có {len(order.opened)}"
    return order.opened[0]


def assert_closed_after(order: DiskOrder, rd: storage.ReceiveDir, *steps: tuple[str, object]) -> None:
    """`rd` được đóng đúng một lần và sau mọi mốc `steps` (mỗi mốc phải có trong nhật ký)."""
    closes = [w for w in order.of("rd_close") if w is rd]
    assert len(closes) == 1, f"ReceiveDir đóng {len(closes)} lần"
    at = order.index("rd_close", rd)
    for step in steps:
        i = order.index(*step)
        assert i is not None, f"thiếu mốc {step} trong nhật ký {order.events}"
        assert i < at, f"ReceiveDir đóng trước mốc {step}: {order.events}"


@leakcheck
async def test_late_resume_handle_after_cancelled_start_is_closed_and_shutdown_submit_is_swallowed(
    world,
    node_factory,
    app_helpers,
    record_for,
    resume_helpers,
    submit_spy,
    disk_order,
    tmp_path,
    monkeypatch,
    caplog,
    grace_real,
):
    """V11c (1) (spec-p3-5 mục 3, 9.2 N8) và spec-fix-app (1a): việc mở lại treo trả handle thật sau khi
    `Node.start` đã bị hủy (kết quả tới muộn) → bên gọi phải đóng nó (`_close_late_handle` → `_close_temp`):
    `submit` sau `abort_now` ném `RuntimeError` (executor đã shutdown, ít nhất một lần, spec-fix-app S8),
    bên gọi nuốt lỗi đó và đóng handle ngay trên loop; rồi `ReceiveDir` của node được đóng (đuôi đĩa)
    trong 3 s, **sau** khi việc treo trả về và sau `close_temp` của đúng lượt đó (spy có thứ tự,
    spec-fix-app S7); không có ERROR, kể cả ngoại lệ task không ai lấy; đĩa để nguyên."""
    caplog.set_level(logging.WARNING)
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=ids["C"], receiver=a_id, blocks=(0,), age=50
    )
    before = resume_helpers.snapshot(d)
    fake = HangingOpen([tid], ignore_stop=True, order=disk_order)
    fake.install(monkeypatch)
    disk_order.reset()
    await cancel_start_during_restore(node_factory, root, tid, fake, submit_spy)
    rd = receive_dir_of_node(disk_order)
    await wait_until(lambda: tid in fake.returned, 10, "việc mở lại treo chưa trả handle")
    handle = fake.returned[tid]
    try:
        await wait_until(lambda: handle.temp.closed, 3, "handle mở lại tới muộn không được đóng")
        await wait_until(lambda: rd.closed, 3, "ReceiveDir không được đóng sau khi việc treo xong")
        assert submit_spy.rejected_after_abort(), (
            "không lần `submit` nào sau abort_now ném RuntimeError: chưa đi qua nhánh executor đã shutdown"
        )
        assert disk_order.of("close_temp") == [tid], disk_order.events
        assert disk_order.index("open_done", tid) < disk_order.index("close_temp", tid), disk_order.events
        assert_closed_after(disk_order, rd, ("open_done", tid), ("close_temp", tid))
        assert disk_order.of("remove_temp") == []
        gc.collect()
        await asyncio.sleep(0)
        assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]
        assert resume_helpers.snapshot(d) == before
    finally:
        if not handle.temp.closed:  # lỗi đang kiểm: đóng giùm để không giữ file trên Windows
            handle.temp._close_quietly()
        if not rd.closed:
            rd.close()
    await wait_until(lambda: app_helpers.lock_is_free(tmp_path / "A"), 5, "node.lock chưa được nhả")


@leakcheck
async def test_receive_dir_is_closed_only_after_hanging_restore_returns_when_start_is_cancelled(
    world,
    node_factory,
    app_helpers,
    record_for,
    resume_helpers,
    disk_order,
    tmp_path,
    monkeypatch,
    caplog,
    grace_real,
):
    """spec-fix-app (1a): `Node.start` bị hủy khi một lần mở lại đang treo trong thread đĩa (việc đó tôn
    trọng `stop`, không trả handle). Lúc `start` ném `CancelledError` thì `ReceiveDir` chưa được đóng (thread
    còn dùng nó); mở cổng → trong 3 s `ReceiveDir` được đóng, và lần đóng xảy ra sau khi việc treo trả
    về; không ERROR; không xóa gì (`remove_temp` không được gọi), lượt để nguyên trên đĩa."""
    caplog.set_level(logging.WARNING)
    a_id, ids = world("C")
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=ids["C"], receiver=a_id, blocks=(0,), age=50
    )
    before = resume_helpers.snapshot(d)
    fake = HangingOpen([tid], order=disk_order)
    fake.install(monkeypatch)
    disk_order.reset()
    A = await node_factory("A", start=False, node_kwargs={"receive_dir": root, "auto_accept": True})
    starting = asyncio.create_task(A.node.start())
    rd = None
    try:
        await wait_until(lambda: tid in fake.stops, 10, "chưa tới bước mở lại")
        rd = receive_dir_of_node(disk_order)
        starting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not rd.closed, "ReceiveDir bị đóng khi thread đĩa còn đang dùng nó"
        assert disk_order.of("rd_close") == []
        fake.gate.set()
        await wait_until(lambda: disk_order.index("open_done", tid) is not None, 10, "việc treo chưa trả về")
        await wait_until(lambda: rd.closed, 3, "ReceiveDir không được đóng sau khi việc treo xong")
        assert_closed_after(disk_order, rd, ("open_done", tid))
        assert disk_order.of("remove_temp") == []
        gc.collect()
        await asyncio.sleep(0)
        assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]
        assert resume_helpers.snapshot(d) == before
    finally:
        fake.gate.set()
        if rd is not None and not rd.closed:
            await asyncio.sleep(0.5)
            if not rd.closed:  # lỗi đang kiểm: đóng giùm để không giữ file trên Windows
                rd.close()
    await wait_until(lambda: app_helpers.lock_is_free(tmp_path / "A"), 5, "node.lock chưa được nhả")


# =================================================================================================
# spec-fix-app (1d): `receiver` là máy này, `sender` không còn tin cậy, qua `Node.start`
# =================================================================================================


@pytest.fixture
def resume_open_spy(monkeypatch):
    """`transfer_id` của mọi lời gọi `ReceiveDir.open_for_resume` (bản thật vẫn chạy)."""
    calls: list[str] = []
    real = storage.ReceiveDir.open_for_resume

    def open_for_resume(rd, scan, *, stop=None):
        calls.append(scan.transfer_id)
        return real(rd, scan, stop=stop)

    monkeypatch.setattr(storage.ReceiveDir, "open_for_resume", open_for_resume)
    return calls


@leakcheck
@pytest.mark.parametrize("scan_stale", [False, True], ids=["quet-dung", "quet-con-tin"])
@pytest.mark.parametrize(
    ("offset", "removed"), [(-3600.0, False), (3600.0, True)], ids=["con-han-noi-lai", "qua-han-noi-lai"]
)
async def test_running_transfer_of_untrusted_sender_is_not_reopened_and_is_cleaned_after_reconnect_grace(
    T,
    world,
    restart,
    cleanup_spy,
    resume_open_spy,
    record_for,
    resume_helpers,
    tmp_path,
    monkeypatch,
    grace_real,
    offset,
    removed,
    scan_stale,
):
    """spec-fix-app (1d), architecture mục 4 (“Dọn tạm”, `transfer.json`): lượt nhận dở có `receiver` là
    máy này, `sender` là một `device_id` hợp lệ không có trong `trusted.json`. `Node.start` không mở lại nó
    (không lời gọi `open_for_resume` nào cho lượt đó, không `TransferResumed`); lần dọn đầu sau
    `Node.start` dùng ngưỡng `RECONNECT_GRACE` của lượt máy này: hoạt động cuối + `RECONNECT_GRACE` − 1 giờ
    → giữ nguyên từng byte; + `RECONNECT_GRACE` + 1 giờ (vẫn dưới `TEMP_RETENTION`) → bị xóa.

    `quet-con-tin`: bước quét (`scan_temps`) còn thấy máy gửi trong danh sách tin cậy nó nhận (như khi máy
    gửi bị bỏ ghép đôi giữa lúc quét và lúc xếp loại), nên lượt hiện là RUNNING; `restore` vẫn phải đối
    chiếu danh sách tin cậy hiện tại và bỏ lượt đó (spec-fix-app mục 4, dòng 1d `:846`)."""
    assert REAL_GRACE + 3600 < storage.TEMP_RETENTION, "tiền đề: ca quá hạn phải dưới TEMP_RETENTION"
    a_id, _ = world()
    stranger = uuid.uuid4().hex
    assert stranger not in {dev.device_id for dev in TrustStore.load(tmp_path / "A").devices()}
    root = tmp_path / "nhan"
    tid = uuid.uuid4().hex
    d = build_running(
        storage, root, record_for, resume_helpers, tid, sender=stranger, receiver=a_id, blocks=(0, 1), age=0
    )
    before = resume_helpers.snapshot(d)
    wall = newest_mtime(d) + REAL_GRACE + offset
    monkeypatch.setattr(T, "_wall_time", lambda: wall)
    kinds: list[storage.TempKind] = []
    if scan_stale:
        real_scan = storage.ReceiveDir.scan_temps

        def scan_temps(rd, own_device_id, trusted_ids):
            scans = real_scan(rd, own_device_id, {*trusted_ids, stranger})
            kinds.extend(s.kind for s in scans if s.transfer_id == tid)
            return scans

        monkeypatch.setattr(storage.ReceiveDir, "scan_temps", scan_temps)

    A = await restart("A", receive_dir=root, auto_accept=True)
    if scan_stale:
        assert kinds == [storage.TempKind.RUNNING], f"tiền đề: bước quét phải thấy lượt RUNNING, có {kinds}"
    assert tid not in resume_open_spy, "lượt của máy gửi không còn tin cậy không được mở lại"
    assert A.trec.of("TransferResumed") == [] and A.transfers.transfers() == ()
    await wait_until(lambda: len(cleanup_spy) >= 1, 5, "lần dọn đầu sau Node.start chưa chạy")
    first = cleanup_spy[0]
    assert first.wall_now == wall
    if removed:
        assert first.removed == 1
        assert not d.exists()
    else:
        assert first.removed == 0
        assert resume_helpers.snapshot(d) == before
    assert tid not in resume_open_spy
    assert (root / ".teleport").is_dir()
