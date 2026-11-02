"""Test bia mộ bền (`tombstones.json`) ở tầng app (P3-3b, việc V2 (a)).

Viết từ đặc tả, không từ code: `specs/spec-p3-3b.md` mục 2.1 (module `teleport.app.tombstones`: `load`,
`save`, `to_restored`, `to_records`), 2.3 (ghi gộp: `call_soon`, tối đa một lần ghi đang chạy, luôn chờ
`settled()`, `TOMBSTONE_MIN_INTERVAL`, xả lúc đóng trong `TOMBSTONE_FLUSH_TIMEOUT`), 5 (V2 (a)), 8.1 mục
7 (giữ job, không ghi lần hai trên cùng `.tmp`); architecture mục 4 (`tombstones.json`).

Phần đầu không mở socket (hàm của module). Phần sau chạy `Node` thật (cổng trên 127.0.0.1, nên có marker
`integration`) nhưng không nối với máy nào: B gửi tới A đang tắt, rồi hủy (`cancel_all`) → mỗi lượt một
bia mộ `send`/`user`, `unsent` (chưa gửi được `cancel`). Số lần ghi đếm bằng spy trên
`teleport.app.tombstones.save` (seam: `transfers` gọi qua thuộc tính module).
"""

from __future__ import annotations

import asyncio
import datetime
import gc
import logging
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from support import wait_until

from teleport.core import resume_state as rs
from teleport.core import transfer as core_transfer

pytestmark = [
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
integration = pytest.mark.integration

UTC = datetime.UTC
DEV_A = "a" * 32
DEV_B = "b" * 32
TID = [f"{k:032x}" for k in range(1, 40)]
# Giá trị thật của hạn chờ nối lại, đọc lúc import (trước khi `fast` vá 4 s): lượt gửi tới máy đang tắt
# không được hết hạn (và sinh thêm bia mộ `expired`) giữa test.
REAL_GRACE = core_transfer.RECONNECT_GRACE


@pytest.fixture
def TB():
    """Module `teleport.app.tombstones` (import muộn: chưa có thì chỉ test dùng nó đỏ)."""
    from teleport.app import tombstones

    return tombstones


@pytest.fixture
def T():
    from teleport.app import transfers

    return transfers


def record(device_id=DEV_A, direction="send", tid=TID[0], reason="user", unsent=False, at=None):
    if at is None:
        at = datetime.datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)
    return rs.TombstoneRecord(device_id, direction, tid, reason, unsent, at)


def teleport_warnings(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("teleport") and r.levelno >= logging.WARNING]


# =================================================================================================
# Module `teleport.app.tombstones` (không socket)
# =================================================================================================


def test_file_name_constant(TB):
    assert TB.TOMBSTONES_NAME == "tombstones.json"


def test_load_missing_file_is_empty_and_creates_nothing(TB, tmp_path):
    assert TB.load(tmp_path) == []
    assert list(tmp_path.iterdir()) == []


def test_save_writes_exact_encoding_and_load_reads_it_back_in_order(TB, tmp_path):
    records = [
        record(tid=TID[2], at=datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)),
        record(
            DEV_B, "receive", TID[1], "expired", True, datetime.datetime(2026, 10, 27, 9, 0, 0, tzinfo=UTC)
        ),
        record(tid=TID[3], reason="source_changed"),
    ]
    TB.save(tmp_path, records)
    assert (tmp_path / "tombstones.json").read_bytes() == rs.encode_tombstones(records)
    assert TB.load(tmp_path) == records
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tombstones.json"]  # không còn file tạm


def test_save_empty_list_writes_valid_empty_file(TB, tmp_path):
    TB.save(tmp_path, [])
    assert rs.decode_tombstones((tmp_path / "tombstones.json").read_bytes()) == []
    assert TB.load(tmp_path) == []


def test_save_overwrites_previous_file(TB, tmp_path):
    TB.save(tmp_path, [record(tid=TID[1])])
    TB.save(tmp_path, [record(tid=TID[2])])
    assert [r.transfer_id for r in TB.load(tmp_path)] == [TID[2]]


def test_save_os_error_propagates(TB, tmp_path):
    not_dir = tmp_path / "file"
    not_dir.write_bytes(b"x")
    with pytest.raises(OSError):
        TB.save(not_dir, [record()])


SECRET = "noi-dung-bi-mat-123"


@pytest.mark.parametrize(
    "content",
    [
        f"{{khong phai json {SECRET}".encode(),
        b"\xff\xfe" + SECRET.encode("utf-16-le"),
        b'["' + SECRET.encode() + b'"]',
        b'{"version": 2, "entries": []}',
        b'{"version": 1, "entries": {"x": "' + SECRET.encode() + b'"}}',
    ],
    ids=["json-hong", "khong-utf8", "khong-phai-object", "sai-version", "entries-khong-phai-mang"],
)
def test_load_corrupt_file_warns_with_error_type_only_and_returns_empty(TB, tmp_path, caplog, content):
    (tmp_path / "tombstones.json").write_bytes(content)
    caplog.set_level(logging.DEBUG)
    assert TB.load(tmp_path) == []
    warned = teleport_warnings(caplog)
    assert warned, "phải có WARNING khi tombstones.json hỏng"
    for r in caplog.records:
        assert SECRET not in r.getMessage(), "log không được chép nội dung file"


def test_load_file_over_ceiling_warns_and_returns_empty(TB, tmp_path, caplog):
    body = b'{"version": 1, "entries": []}'
    (tmp_path / "tombstones.json").write_bytes(body + b" " * (rs.MAX_TOMBSTONE_FILE + 1 - len(body)))
    caplog.set_level(logging.WARNING)
    assert TB.load(tmp_path) == []
    assert teleport_warnings(caplog)


def test_load_file_exactly_at_ceiling_is_read(TB, tmp_path):
    good = rs.encode_tombstones([record()])
    (tmp_path / "tombstones.json").write_bytes(good[:-1] + b" " * (rs.MAX_TOMBSTONE_FILE - len(good)) + b"\n")
    assert len((tmp_path / "tombstones.json").read_bytes()) == rs.MAX_TOMBSTONE_FILE
    assert TB.load(tmp_path) == [record()]


def test_load_skips_bad_entries_only(TB, tmp_path):
    good = record(tid=TID[5])
    text = rs.encode_tombstones([good]).decode("utf-8")
    at = '"at": "2026-10-27T10:00:00Z"'
    bad_entries = [
        f'{{"device_id": "x", "direction": "send", "transfer_id": "{TID[6]}", "reason": "user",'
        f' "unsent": false, {at}}}',
        f'{{"device_id": "{DEV_A}", "direction": "sideways", "transfer_id": "{TID[7]}", "reason": "user",'
        f' "unsent": false, {at}}}',
        f'{{"device_id": "{DEV_A}", "direction": "send", "transfer_id": "{TID[8]}", "reason": "user"}}',
        "42",
    ]
    text = text.replace('"entries": [', '"entries": [' + ", ".join(bad_entries) + ",", 1)
    (tmp_path / "tombstones.json").write_text(text, encoding="utf-8")
    assert TB.load(tmp_path) == [good]


def test_load_never_raises_when_path_is_a_directory(TB, tmp_path, caplog):
    (tmp_path / "tombstones.json").mkdir()
    caplog.set_level(logging.WARNING)
    assert TB.load(tmp_path) == []
    assert teleport_warnings(caplog)


def test_to_restored_keeps_only_trusted_devices_and_maps_fields(TB):
    wall = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC).timestamp()
    records = [
        record(DEV_A, "send", TID[1], "user", True, datetime.datetime(2026, 10, 27, 11, 0, 0, tzinfo=UTC)),
        record(
            DEV_B, "receive", TID[2], "expired", False, datetime.datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)
        ),
        record("c" * 32, "send", TID[3]),
    ]
    out = TB.to_restored(records, {DEV_A, DEV_B}, wall)
    assert out == [
        core_transfer.RestoredTombstone(DEV_A, core_transfer.Direction.SEND, TID[1], "user", True, 3600.0),
        core_transfer.RestoredTombstone(
            DEV_B, core_transfer.Direction.RECEIVE, TID[2], "expired", False, 7200.0
        ),
    ]
    assert all(isinstance(t.direction, core_transfer.Direction) for t in out)


def test_to_restored_clamps_future_at_to_zero_age(TB):
    wall = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC).timestamp()
    future = record(at=datetime.datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC))
    [item] = TB.to_restored([future], {DEV_A}, wall)
    assert item.age == 0.0


def test_to_restored_does_not_filter_age_or_count(TB):
    """Lọc tuổi (`REMEMBER_TTL`) và trần 1024 mục/thiết bị là việc của `engine.restore`."""
    wall = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC).timestamp()
    old = record(at=datetime.datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC))
    [item] = TB.to_restored([old], {DEV_A}, wall)
    assert item.age > core_transfer.REMEMBER_TTL


def test_to_records_rounds_at_down_to_the_second(TB):
    wall = datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC).timestamp() + 0.9
    items = [
        core_transfer.RestoredTombstone(DEV_A, core_transfer.Direction.SEND, TID[1], "user", True, 10.5),
        core_transfer.RestoredTombstone(DEV_B, core_transfer.Direction.RECEIVE, TID[2], "error", False, 0.0),
    ]
    out = TB.to_records(items, wall)
    assert out == [
        rs.TombstoneRecord(
            DEV_A, "send", TID[1], "user", True, datetime.datetime(2026, 10, 27, 11, 59, 50, tzinfo=UTC)
        ),
        rs.TombstoneRecord(
            DEV_B, "receive", TID[2], "error", False, datetime.datetime(2026, 10, 27, 12, 0, 0, tzinfo=UTC)
        ),
    ]


def test_to_records_then_to_restored_round_trip_keeps_order_and_age_within_a_second(TB):
    wall = 1_800_000_000.25
    items = [
        core_transfer.RestoredTombstone(
            DEV_A, core_transfer.Direction.SEND, TID[k], "user", k % 2 == 0, 100.0 * k
        )
        for k in range(1, 6)
    ]
    back = TB.to_restored(TB.to_records(items, wall), {DEV_A}, wall)
    assert [(t.transfer_id, t.unsent, t.direction) for t in back] == [
        (t.transfer_id, t.unsent, t.direction) for t in items
    ]
    for got, want in zip(back, items, strict=True):
        assert want.age <= got.age < want.age + 1.0


# =================================================================================================
# Ghi gộp trong `TransferManager` (node thật, không nối máy nào)
# =================================================================================================


class SaveSpy:
    """Spy trên `tombstones.save` (chạy trong thread đĩa): thời điểm bắt đầu / kết thúc, số lần chạy
    chồng nhau; `gate` (nếu đặt) chặn lần ghi thứ `gate_call` (đếm từ 1) tới khi mở."""

    def __init__(self, real) -> None:
        self.real = real
        self.lock = threading.Lock()
        self.calls: list[SimpleNamespace] = []
        self.running = 0
        self.max_running = 0
        self.gate: threading.Event | None = None
        self.gate_call = 1
        self.hit = threading.Event()

    def __call__(self, config_dir, records):
        rec = SimpleNamespace(t0=time.monotonic(), t1=None, n=len(list(records)))
        with self.lock:
            self.calls.append(rec)
            number = len(self.calls)
            self.running += 1
            self.max_running = max(self.max_running, self.running)
        try:
            if self.gate is not None and number == self.gate_call:
                self.hit.set()
                if not self.gate.wait(30):
                    raise AssertionError("cổng chặn của test không được mở")
            return self.real(config_dir, records)
        finally:
            with self.lock:
                self.running -= 1
            rec.t1 = time.monotonic()


@pytest.fixture
def save_spy(TB, monkeypatch):
    spy = SaveSpy(TB.save)
    monkeypatch.setattr(TB, "save", spy)
    yield spy
    if spy.gate is not None:
        spy.gate.set()


@pytest.fixture
async def lone_sender(node_factory, trust_each_other, tmp_path, monkeypatch, fast, app_helpers):
    """B chạy một mình (A tin B, B tin A, nhưng A không chạy). `make(**node_kwargs)` → `AppNode` B."""
    monkeypatch.setattr(core_transfer, "RECONNECT_GRACE", REAL_GRACE)
    trust_each_other("A", "B")
    src = tmp_path / "nguon"
    src.mkdir()
    files = []
    for k in range(40):
        p = src / f"f{k}.bin"
        p.write_bytes(b"x" * (k + 1))
        files.append(p)

    async def make(**node_kwargs) -> SimpleNamespace:
        trec = app_helpers.TransferRecorder("B")
        node_kwargs.setdefault("on_transfer_event", trec.on_update)
        B = await node_factory("B", node_kwargs=node_kwargs)
        B.trec = trec
        a_id = app_helpers.ensure_identity(tmp_path / "A").device_id
        return SimpleNamespace(B=B, a_id=a_id, files=files, config=tmp_path / "B")

    return make


async def send_and_cancel(net, files) -> list[str]:
    """B gửi mỗi file một lượt tới A (đang tắt), rồi hủy tất cả trong một khối đồng bộ."""
    keys = [await net.B.transfers.send(net.a_id, [f]) for f in files]
    net.B.transfers.cancel_all()
    return [k.transfer_id for k in keys]


def read_replaced(path: Path, budget: float = 1.0) -> bytes:
    """Đọc file node có thể đang thay nguyên tử (`os.replace` trên thread đĩa): trên Windows mở đúng lúc
    thay báo `PermissionError`, nên thử lại mỗi 20 ms trong `budget` giây rồi mới ném lại lỗi thật."""
    deadline = time.monotonic() + budget
    while True:
        try:
            return path.read_bytes()
        except PermissionError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.02)


def saved_ids(config: Path) -> list[str]:
    path = config / "tombstones.json"
    try:
        return [r.transfer_id for r in rs.decode_tombstones(path.read_bytes())]
    except (FileNotFoundError, PermissionError, rs.StateError):
        return []


async def wait_saved(config: Path, tids, timeout: float = 5.0) -> None:
    want = set(tids)
    await wait_until(
        lambda: want <= set(saved_ids(config)), timeout, f"tombstones.json chưa có {len(want)} mục"
    )


@integration
async def test_burst_of_tombstones_is_written_at_most_twice_never_overlapping(lone_sender, save_spy):
    net = await lone_sender()
    tids = await send_and_cancel(net, net.files[:20])
    await wait_saved(net.config, tids)
    await asyncio.sleep(0.3)
    assert 1 <= len(save_spy.calls) <= 2, [c.n for c in save_spy.calls]
    assert save_spy.max_running == 1
    entries = rs.decode_tombstones(read_replaced(net.config / "tombstones.json"))
    assert {(e.device_id, e.direction, e.reason, e.unsent) for e in entries} == {
        (net.a_id, "send", "user", True)
    }
    assert [e.transfer_id for e in entries] == tids, "giữ thứ tự lập bia mộ"


@pytest.mark.slow
@integration
async def test_second_write_waits_for_overdue_first_write_to_settle(lone_sender, save_spy, T, monkeypatch):
    """Lần ghi quá `DISK_OP_TIMEOUT` vẫn chạy trong thread: lần ghi sau chỉ bắt đầu khi nó đã xong (tên
    `.tmp` cố định), và chỉ một lần cho cả loạt bia mộ mới."""
    monkeypatch.setattr(T, "DISK_OP_TIMEOUT", 0.2)
    monkeypatch.setattr(T, "TOMBSTONE_MIN_INTERVAL", 0.0)
    save_spy.gate = threading.Event()
    net = await lone_sender()
    first = await send_and_cancel(net, net.files[:5])
    await wait_until(save_spy.hit.is_set, 5, "chưa có lần ghi nào")
    second = await send_and_cancel(net, net.files[5:10])
    await asyncio.sleep(0.8)  # quá DISK_OP_TIMEOUT nhiều lần
    assert len(save_spy.calls) == 1, "không được ghi lần hai khi lần ghi trước chưa xong"
    save_spy.gate.set()
    await wait_saved(net.config, first + second)
    await asyncio.sleep(0.3)
    assert len(save_spy.calls) == 2, [c.n for c in save_spy.calls]
    assert save_spy.max_running == 1
    assert save_spy.calls[1].t0 >= save_spy.calls[0].t1


@integration
async def test_writes_are_spaced_by_tombstone_min_interval(lone_sender, save_spy, T, monkeypatch):
    interval = 0.6
    monkeypatch.setattr(T, "TOMBSTONE_MIN_INTERVAL", interval)
    net = await lone_sender()
    first = await send_and_cancel(net, net.files[:3])
    await wait_saved(net.config, first)
    second = await send_and_cancel(net, net.files[3:6])
    await wait_saved(net.config, first + second, timeout=5 + interval)
    assert len(save_spy.calls) == 2
    gap = save_spy.calls[1].t0 - save_spy.calls[0].t1
    assert gap >= interval - 0.05, f"hai lần ghi cách nhau {gap:.3f} s < {interval} s"


@pytest.fixture
async def tomb_timers(monkeypatch):
    """Mọi lần hẹn chụp bia mộ bằng `loop.call_later` (bọc `call_later` của loop đang chạy): danh sách
    `asyncio.TimerHandle` có callback `_snapshot_tombstones`, theo thứ tự hẹn."""
    loop = asyncio.get_running_loop()
    real = loop.call_later
    handles: list[asyncio.TimerHandle] = []

    def call_later(delay, callback, *args, **kwargs):
        handle = real(delay, callback, *args, **kwargs)
        if getattr(callback, "__name__", "") == "_snapshot_tombstones":
            handles.append(handle)
        return handle

    monkeypatch.setattr(loop, "call_later", call_later)
    return handles


def errors_logged(caplog) -> list[logging.LogRecord]:
    """Bản ghi ERROR+ của mọi logger (kể cả `asyncio`: “Task exception was never retrieved”)."""
    return [r for r in caplog.records if r.levelno >= logging.ERROR]


async def burst_waiting_for_interval(net, save_spy, tomb_timers):
    """Loạt bia mộ đầu được ghi; loạt sau chờ `TOMBSTONE_MIN_INTERVAL` (đã vá 60 s) ở một `TimerHandle`.
    Trả (loạt đầu, loạt sau, handle đang chờ)."""
    first = await send_and_cancel(net, net.files[:3])
    await wait_saved(net.config, first)
    await wait_until(lambda: save_spy.calls and save_spy.calls[-1].t1 is not None, 5, "lần ghi đầu chưa xong")
    second = await send_and_cancel(net, net.files[3:6])
    await wait_until(lambda: tomb_timers, 5, "lần ghi sau chưa được hẹn bằng call_later")
    assert len(save_spy.calls) == 1  # lần ghi sau đang chờ khoảng cách 60 s
    [handle] = tomb_timers
    assert not handle.cancelled()
    assert handle.when() - asyncio.get_running_loop().time() > 30, "lần hẹn phải chờ khoảng cách 60 s"
    return first, second, handle


@integration
async def test_close_flushes_last_snapshot_without_waiting_for_interval(
    lone_sender, save_spy, tomb_timers, T, monkeypatch
):
    """Kèm V11b (spec-p3-5 mục 3): lần hẹn `call_later` đang chờ bị hủy khi `close()` xả bia mộ."""
    monkeypatch.setattr(T, "TOMBSTONE_MIN_INTERVAL", 60.0)
    net = await lone_sender()
    first, second, handle = await burst_waiting_for_interval(net, save_spy, tomb_timers)
    t0 = time.monotonic()
    await asyncio.wait_for(net.B.close(), 10)
    assert time.monotonic() - t0 < 5.0
    assert saved_ids(net.config) == first + second
    assert save_spy.max_running == 1
    assert handle.cancelled(), "close() phải hủy lần hẹn ghi bia mộ đang chờ (TimerHandle)"


@integration
async def test_close_cancelled_before_transfers_close_aborts_without_flushing_tombstones(
    lone_sender, save_spy, tomb_timers, T, monkeypatch, caplog
):
    """V11a (spec-p3-5 mục 3, 9.2 N7): `Node.close` bị hủy khi đang giữ ở seam ngay trước
    `TransferManager.close()` → `abort_now` đúng một lần: hủy `TimerHandle` đang chờ, **không** xả bia
    mộ (sau 0,5 s vẫn chỉ một lần ghi, `tombstones.json` chỉ có loạt đầu); không có ERROR."""
    caplog.set_level(logging.WARNING)
    monkeypatch.setattr(T, "TOMBSTONE_MIN_INTERVAL", 60.0)
    aborts: list[object] = []
    real_abort = T.TransferManager.abort_now

    def abort_now(self):
        aborts.append(self)
        return real_abort(self)

    monkeypatch.setattr(T.TransferManager, "abort_now", abort_now)
    net = await lone_sender()
    first, _second, handle = await burst_waiting_for_interval(net, save_spy, tomb_timers)

    held = asyncio.Event()
    real_close = T.TransferManager.close

    async def close(self):
        if self is net.B.transfers:
            held.set()
            await asyncio.Event().wait()  # giữ tới khi bị hủy
        return await real_close(self)

    monkeypatch.setattr(T.TransferManager, "close", close)
    manager = net.B.transfers
    closing = asyncio.create_task(net.B.close())
    await asyncio.wait_for(held.wait(), 10)
    assert aborts == []
    closing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await closing
    assert aborts == [manager], f"abort_now chạy {len(aborts)} lần"
    assert handle.cancelled(), "abort_now phải hủy lần hẹn ghi bia mộ đang chờ (TimerHandle)"
    await asyncio.sleep(0.5)
    assert len(save_spy.calls) == 1, "abort_now không được xả bia mộ"
    assert saved_ids(net.config) == first
    gc.collect()  # ngoại lệ task không ai lấy chỉ được báo khi task bị thu gom
    await asyncio.sleep(0)
    assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]


@integration
async def test_tombstone_write_after_executor_shutdown_warns_once_and_close_stays_bounded(
    lone_sender, save_spy, T, monkeypatch, caplog
):
    """V11c (2) (spec-p3-5 mục 3): `DiskExecutor.submit` ném `RuntimeError` (executor đã shutdown) đúng
    lúc giao việc ghi bia mộ → một WARNING “node đã đóng”, không ngoại lệ task, không ghi gì;
    `Node.close()` xong trong `close_time_limit()`."""
    from teleport.app import diskio
    from teleport.app.node import close_time_limit

    caplog.set_level(logging.WARNING)
    injected: list[str] = []
    real_submit = diskio.DiskExecutor.submit

    def submit(self, fn, /, *args):
        if fn is T._encode_and_save:
            injected.append(fn.__name__)
            raise RuntimeError("DiskExecutor đã shutdown")
        return real_submit(self, fn, *args)

    monkeypatch.setattr(diskio.DiskExecutor, "submit", submit)
    net = await lone_sender()

    def closed_warnings() -> list[logging.LogRecord]:
        return [r for r in teleport_warnings(caplog) if "node đã đóng" in r.getMessage()]

    await send_and_cancel(net, net.files[:3])
    await wait_until(lambda: injected and closed_warnings(), 5, "chưa có WARNING “node đã đóng”")
    limit = close_time_limit()
    t0 = time.monotonic()
    await asyncio.wait_for(net.B.close(), limit + 5)
    elapsed = time.monotonic() - t0
    assert elapsed <= limit, f"close() mất {elapsed:.2f} s > close_time_limit() = {limit:.2f} s"
    gc.collect()
    await asyncio.sleep(0)
    assert len(closed_warnings()) == 1, [r.getMessage() for r in closed_warnings()]
    assert errors_logged(caplog) == [], [r.getMessage() for r in errors_logged(caplog)]
    assert save_spy.calls == []
    assert not (net.config / "tombstones.json").exists()


@pytest.mark.slow
@integration
async def test_close_flush_is_bounded_by_tombstone_flush_timeout_and_never_writes_twice(
    lone_sender, save_spy, T, monkeypatch
):
    flush = 0.5
    monkeypatch.setattr(T, "TOMBSTONE_FLUSH_TIMEOUT", flush)
    monkeypatch.setattr(T, "DISK_OP_TIMEOUT", 0.2)
    save_spy.gate = threading.Event()
    net = await lone_sender()
    await send_and_cancel(net, net.files[:3])
    await wait_until(save_spy.hit.is_set, 5, "chưa có lần ghi nào")
    await send_and_cancel(net, net.files[3:6])  # còn bẩn khi đóng
    t0 = time.monotonic()
    await asyncio.wait_for(net.B.close(), 15)
    elapsed = time.monotonic() - t0
    assert elapsed < flush + 3.0, f"close() mất {elapsed:.2f} s dù lần ghi bia mộ treo"
    assert len(save_spy.calls) == 1, "không được ghi lần hai khi lần ghi trước chưa xong (cùng file .tmp)"
    save_spy.gate.set()
    await asyncio.sleep(0.3)
    assert len(save_spy.calls) == 1
    assert save_spy.max_running == 1


@integration
async def test_failed_tombstone_write_is_retried_once_on_close(lone_sender, TB, monkeypatch, caplog):
    """Lần ghi bia mộ lỗi (OSError) → WARNING, không tự thử lại ngay; ảnh chụp đó không bị bỏ: `close()`
    ghi lại đúng một lần dù sau đó không có bia mộ mới (như `HistoryStore`)."""
    caplog.set_level(logging.WARNING)
    real = TB.save
    calls: list[int] = []

    def save(config_dir, records):
        calls.append(len(list(records)))
        if len(calls) == 1:
            raise OSError(28, "ổ đầy (giả lập)")
        return real(config_dir, records)

    monkeypatch.setattr(TB, "save", save)
    net = await lone_sender()
    tids = await send_and_cancel(net, net.files[:3])
    await wait_until(lambda: teleport_warnings(caplog), 5, "chưa có WARNING ghi lỗi")
    await asyncio.sleep(0.3)
    assert len(calls) == 1, "ghi lỗi không được tự hẹn thử lại"
    assert saved_ids(net.config) == []
    await asyncio.wait_for(net.B.close(), 10)
    assert len(calls) == 2, "close() phải ghi lại ảnh chụp đã lỗi"
    assert saved_ids(net.config) == tids


@integration
@pytest.mark.parametrize("kind", ["hong", "vuot-tran", "thu-muc"])
async def test_unreadable_tombstones_file_warns_and_node_runs(lone_sender, save_spy, caplog, kind):
    """`tombstones.json` hỏng / vượt trần / không đọc được → WARNING, `Node.start` vẫn xong; lần ghi sau
    đè file cũ (rủi ro R3 đã chấp nhận)."""
    probe = await lone_sender()  # chạy B một lần để có thư mục cấu hình, rồi đóng
    await probe.B.close()
    path = probe.config / "tombstones.json"
    if path.exists():
        path.unlink()
    if kind == "hong":
        path.write_bytes(b"{" + SECRET.encode())
    elif kind == "vuot-tran":
        path.write_bytes(b" " * (rs.MAX_TOMBSTONE_FILE + 1))
    else:
        path.mkdir()
    caplog.set_level(logging.WARNING)
    caplog.clear()
    net = await lone_sender()
    assert net.B.port is not None
    assert teleport_warnings(caplog), "phải có WARNING khi không đọc được tombstones.json"
    assert all(SECRET not in r.getMessage() for r in caplog.records)
    if kind != "thu-muc":
        tids = await send_and_cancel(net, net.files[:2])
        await wait_saved(net.config, tids)
        assert saved_ids(net.config) == tids
