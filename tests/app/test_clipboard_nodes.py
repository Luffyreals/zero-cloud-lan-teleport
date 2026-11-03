"""Đồng bộ clipboard giữa các `Node` thật trên 127.0.0.1 (P5-1), theo spec-d5 mục 2.4–2.5, ca test #2
ở mục 5 và mục 9 (thắng khi khác).

Viết từ đặc tả, không từ code. Mỗi node có một `FakeClipboard` (spec 2.2) bọc trong `EchoClipboard`:
lớp con chỉ thêm (1) đếm số lần `read`, (2) gọi `on_change` sau mỗi lần ghi thành công, như clipboard
thật báo `dataChanged` cho chính lần ghi của mình (gọi thừa một lần cũng vô hại vì có gộp), (3) treo
ghi theo yêu cầu (`hang_write`).

Kiểm “không vọng” không bằng ngủ cố định mà bằng **mốc**: sau ca cần kiểm, lần lượt mỗi máy sao chép một
nội dung mới và chờ các máy kia nhận; kết nối điều khiển giữ thứ tự, nên tiếng vọng (nếu có) phải tới
trước mốc. Số clip gửi đi được đếm bằng spy trên `Connection.send` (mọi node trong tiến trình).

Giả định về API (spec chưa nói đủ cụ thể, báo lại nếu lệch): `Node(clipboard=..., on_clipboard_event=...)`,
`Node.clipboard`, `Node.set_clipboard(device_id, enabled)`, `Node.device_settings(id).clipboard`;
`FakeClipboard()` không đối số, có `set_text`, `writes`, `transform`, `fail_write`; khóa
`settings.json` là `"clipboard"` (đã có ở `app/settings.py`).
"""

from __future__ import annotations

import asyncio
import contextlib
import gc
import itertools
import json
import logging
import time
import tracemalloc
import uuid
from types import SimpleNamespace

import pytest
from support import wait_until

from teleport.app import clipboard as app_clip
from teleport.app.clipboard import ClipOutcome, FakeClipboard
from teleport.core import clipboard as core_clip
from teleport.core.clipboard import MAX_TEXT_BYTES, PNG_SIGNATURE, ClipAssembler, split_clip
from teleport.core.messages import Clipboard, ClipKind, MessageError
from teleport.net import connection

pytestmark = [
    pytest.mark.integration,
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]

LOCAL = "127.0.0.1"
MiB = 1024 * 1024
DEBOUNCE = 0.02
SETTLE = 0.4


class EchoClipboard(FakeClipboard):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.test_reads = 0  # tên riêng: không dựa vào bộ đếm (nếu có) của FakeClipboard
        self.write_calls = 0
        self.hang_write: asyncio.Event | None = None
        self._echo = None

    def start(self, on_change) -> None:
        self._echo = on_change
        super().start(on_change)

    async def read(self):
        self.test_reads += 1
        return await super().read()

    async def write(self, kind, data):
        self.write_calls += 1
        if self.hang_write is not None:
            await self.hang_write.wait()
        result = await super().write(kind, data)
        if str(result.status) == "ok" and self._echo is not None:
            self._echo()
        return result

    def written(self) -> list:
        return [content.data for _, content in self.writes]


def on_disk(directory) -> dict:
    return json.loads((directory / "settings.json").read_text(encoding="utf-8"))


def assembler_of(sync) -> ClipAssembler:
    for name in dir(sync):
        with contextlib.suppress(Exception):
            value = getattr(sync, name)
            if isinstance(value, ClipAssembler):
                return value
    raise AssertionError("ClipboardSync không giữ ClipAssembler nào đọc được qua thuộc tính")


@pytest.fixture
def sent_clips(monkeypatch):
    """Spy `Connection.send`: mọi message `clipboard` mảnh 0 gửi đi, theo thứ tự."""
    log: list[Clipboard] = []
    real = connection.Connection.send

    async def send(self, msg):
        if isinstance(msg, Clipboard) and msg.index == 0:
            log.append(msg)
        return await real(self, msg)

    monkeypatch.setattr(connection.Connection, "send", send)
    return log


@pytest.fixture
def arrivals(monkeypatch):
    """Spy `ClipboardSync.on_message`: `(sync, device_id, msg)` mỗi mảnh node nhận được, trước khi xử lý."""
    log: list[tuple] = []
    real = app_clip.ClipboardSync.on_message

    def on_message(self, *args, **kwargs):
        msg = args[-1] if args else kwargs.get("msg")
        device_id = args[0] if args else kwargs.get("device_id")
        log.append((self, device_id, msg))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(app_clip.ClipboardSync, "on_message", on_message)
    return log


def arrived(log, node, sha256: str) -> bool:
    return any(sync is node.clipboard and m.sha256 == sha256 for sync, _, m in log)


@pytest.fixture
async def clip_net(node_factory, trust_each_other, monkeypatch):
    """`await clip_net(labels=("A","B"), enable=True, connect=True)` → `SimpleNamespace` theo nhãn.

    Mỗi máy: `node` (AppNode), `cb` (EchoClipboard), `events` (ClipboardEvent). Mọi cặp tin nhau,
    nối kết nối điều khiển và (nếu `enable`) bật đồng bộ clipboard ở cả hai đầu.
    """
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", DEBOUNCE)

    async def make(labels=("A", "B"), *, enable: bool = True, connect: bool = True, backend: bool = True):
        for x, y in itertools.combinations(labels, 2):
            trust_each_other(x, y, name_a=x, name_b=y)
        peers: dict[str, SimpleNamespace] = {}
        for label in labels:
            cb = EchoClipboard()
            events: list = []
            kw = {"clipboard": cb, "on_clipboard_event": events.append} if backend else {}
            node = await node_factory(label, node_kwargs=kw)
            peers[label] = SimpleNamespace(node=node, cb=cb, events=events, id=node.id, label=label)
        if connect:
            for x, y in itertools.combinations(labels, 2):
                await link(peers[x], peers[y])
        if enable:
            for x, y in itertools.permutations(labels, 2):
                peers[x].node.set_clipboard(peers[y].id, True)
        return SimpleNamespace(**peers, all=peers)

    return make


async def link(p, q) -> None:
    p.node.connect_hint(q.id, [LOCAL], q.node.port)
    # 15 s: runner Windows của CI chạy -n auto có lúc mất quá 5 s mới xong bắt tay TLS hai chiều.
    await wait_until(
        lambda: q.id in p.node.connected_devices() and p.id in q.node.connected_devices(),
        15,
        f"{p.label} chưa nối được với {q.label}",
    )


def received(p) -> list:
    return [e for e in p.events if e.outcome == ClipOutcome.RECEIVED]


async def checkpoint(net, *labels) -> None:
    """Mốc: lần lượt mỗi máy sao chép một nội dung mới, chờ mọi máy kia ghi nó."""
    for who in labels:
        mark = f"mốc {who} {uuid.uuid4().hex[:8]}"
        net.all[who].cb.set_text(mark)
        for other in labels:
            if other != who:
                await wait_until(
                    lambda other=other, mark=mark: mark in net.all[other].cb.written(),
                    10,
                    f"{other} chưa nhận mốc của {who}",
                )


# --- Node: tham số, cài đặt (2.5) ---------------------------------------------------------------


async def test_node_without_backend_has_no_clipboard_sync(node_factory):
    A = await node_factory("A")
    assert A.clipboard is None


async def test_node_with_backend_exposes_clipboard_sync(clip_net):
    net = await clip_net(("A",), connect=False, enable=False)
    assert isinstance(net.A.node.clipboard, app_clip.ClipboardSync)


async def test_set_clipboard_saves_and_validates(clip_net):
    net = await clip_net(enable=False, connect=False)
    A, B = net.A, net.B
    assert A.node.device_settings(B.id).clipboard is False, "mặc định tắt"
    A.node.set_clipboard(B.id, True)
    assert A.node.device_settings(B.id).clipboard is True
    assert on_disk(A.node.dir)["devices"][B.id]["clipboard"] is True
    A.node.set_clipboard(B.id, False)
    assert A.node.device_settings(B.id).clipboard is False
    with pytest.raises(MessageError):
        A.node.set_clipboard("khong-phai-id", True)
    with pytest.raises(KeyError):
        A.node.set_clipboard(uuid.uuid4().hex, True)
    with pytest.raises(TypeError):
        A.node.set_clipboard(B.id, 1)


async def test_set_clipboard_works_without_backend(clip_net):
    """CLI (không backend) vẫn lưu được lựa chọn, như `set_ask_before_receive`."""
    net = await clip_net(enable=False, connect=False, backend=False)
    net.A.node.set_clipboard(net.B.id, True)
    assert net.A.node.device_settings(net.B.id).clipboard is True


# --- Ca #1: hai node, văn bản, `\r\n` không vọng --------------------------------------------------


async def test_two_nodes_text_arrives_and_crlf_transform_is_not_echoed(clip_net, sent_clips):
    net = await clip_net()
    A, B = net.A, net.B
    B.cb.transform = lambda t: t.replace("\n", "\r\n")
    A.cb.set_text("dòng 1\ndòng 2")
    await wait_until(lambda: B.cb.written() == ["dòng 1\r\ndòng 2"], 5, "B chưa ghi")
    await wait_until(lambda: B.cb.test_reads >= 1, 5, "B chưa đọc lại sau khi ghi")
    (ev,) = received(B)
    assert ev.device_id == A.id
    assert ev.kind == ClipKind.TEXT
    await checkpoint(net, "B", "A")
    assert received(A)[0].preview.startswith("mốc B"), "A nhận lại clip của chính nó (vọng)"
    assert A.cb.written()[0].startswith("mốc B")
    first = sent_clips[0]
    assert sum(1 for m in sent_clips if m.sha256 == first.sha256) == 1


# --- Ca #2: ba node bật hai chiều đôi một -------------------------------------------------------


@pytest.mark.slow
async def test_three_nodes_each_change_written_once_per_machine_no_echo(clip_net, sent_clips):
    net = await clip_net(("A", "B", "C"))
    order = [("A", "X từ A"), ("B", "Y từ B"), ("C", "Z từ C")]
    for who, text in order:
        net.all[who].cb.set_text(text)
        for other in net.all:
            if other != who:
                await wait_until(
                    lambda other=other, text=text: text in net.all[other].cb.written(),
                    10,
                    f"{other} chưa ghi {text!r}",
                )
    await checkpoint(net, "A", "B", "C")
    for who, text in order:
        for name, p in net.all.items():
            n = p.cb.written().count(text)
            assert n == (0 if name == who else 1), f"{name} ghi {text!r} {n} lần"
        sha = core_clip.text_fingerprint(text)
        n_sent = sum(1 for m in sent_clips if m.sha256 == sha)
        assert n_sent == 2, f"{text!r} được gửi {n_sent} lần (đúng: 2, chỉ từ máy gốc)"


# --- Ca #3: một đầu tắt ---------------------------------------------------------------------------


async def test_receiver_disabled_does_not_write_or_buffer(clip_net, arrivals):
    net = await clip_net(enable=False)
    A, B = net.A, net.B
    A.node.set_clipboard(B.id, True)  # chỉ A bật: A vẫn gửi (không biết B tắt)
    msgs = split_clip(uuid.uuid4().hex, ClipKind.TEXT, "B chưa bật " + "x" * 900_000)
    assert len(msgs) >= 2
    await A.node.control_connection(B.id).send(msgs[0])
    await wait_until(lambda: arrived(arrivals, B.node, msgs[0].sha256), 5, "B chưa nhận mảnh 0")
    assert assembler_of(B.node.clipboard).buffered_bytes() == 0
    assert assembler_of(B.node.clipboard).reserved_bytes() == 0
    A.cb.set_text("A sao chép khi B tắt")
    await wait_until(lambda: any(e.outcome == ClipOutcome.SENT for e in A.events), 10, "A chưa gửi")
    # `SENT` chỉ là đã ghi xuống socket: chờ B xử lý xong mảnh đó (lúc còn tắt) rồi mới bật.
    off_sha = core_clip.text_fingerprint("A sao chép khi B tắt")
    await wait_until(lambda: arrived(arrivals, B.node, off_sha), 5, "B chưa nhận clip lúc tắt")
    B.node.set_clipboard(A.id, True)
    for m in msgs[1:]:
        await A.node.control_connection(B.id).send(m)
    A.cb.set_text("sau khi B bật")
    await wait_until(lambda: B.cb.written() == ["sau khi B bật"], 5, "B chưa nhận sau khi bật")
    assert B.cb.write_calls == 1


async def test_sender_disabled_does_not_read_or_send(clip_net, sent_clips):
    net = await clip_net(enable=False)
    A, B = net.A, net.B
    B.node.set_clipboard(A.id, True)  # chỉ B bật
    A.cb.set_text("A chưa bật")
    await asyncio.sleep(SETTLE)
    assert A.cb.test_reads == 0
    assert sent_clips == []
    assert B.cb.written() == []


async def test_disabling_at_runtime_stops_sending(clip_net, sent_clips):
    net = await clip_net()
    A, B = net.A, net.B
    A.cb.set_text("lần 1")
    await wait_until(lambda: B.cb.written() == ["lần 1"], 5, "B chưa nhận")
    A.node.set_clipboard(B.id, False)
    reads = A.cb.test_reads
    A.cb.set_text("lần 2")
    await asyncio.sleep(SETTLE)
    assert A.cb.test_reads == reads
    assert len(sent_clips) == 1


# --- Ca #4: tạm dừng, nhạy cảm, quá trần ----------------------------------------------------------


async def test_paused_receiver_drops_clipboard(clip_net, arrivals):
    net = await clip_net()
    A, B = net.A, net.B
    B.node.transfers.pause_receiving(True)
    text = "lúc B tạm dừng"
    A.cb.set_text(text)
    sha = core_clip.text_fingerprint(text)
    await wait_until(lambda: arrived(arrivals, B.node, sha), 5, "B chưa nhận message")
    assert assembler_of(B.node.clipboard).buffered_bytes() == 0
    B.node.transfers.pause_receiving(False)
    A.cb.set_text("sau tạm dừng")
    await wait_until(lambda: B.cb.written() == ["sau tạm dừng"], 5, "B chưa nhận sau khi tiếp tục")


async def test_paused_receiver_still_sends(clip_net):
    """9.4: “Tạm dừng nhận” chỉ chặn nhận clipboard, không chặn gửi."""
    net = await clip_net()
    A, B = net.A, net.B
    A.node.transfers.pause_receiving(True)
    A.cb.set_text("A tạm dừng nhận nhưng vẫn gửi")
    await wait_until(lambda: B.cb.written() == ["A tạm dừng nhận nhưng vẫn gửi"], 5, "B chưa nhận")


async def test_sensitive_content_is_not_sent(clip_net, sent_clips):
    net = await clip_net()
    A, B = net.A, net.B
    A.cb.set_text("mat-khau-123", sensitive=True)
    await wait_until(lambda: A.cb.test_reads >= 1, 5, "A chưa đọc")
    A.cb.set_text("không nhạy cảm")
    await wait_until(lambda: B.cb.written() == ["không nhạy cảm"], 5, "B chưa nhận")
    assert len(sent_clips) == 1
    assert A.events and all(e.outcome == ClipOutcome.SENT for e in A.events)


async def test_too_large_clip_emits_event_and_is_not_sent(clip_net, sent_clips):
    net = await clip_net()
    A, B = net.A, net.B
    A.cb.set_text("a" * (MAX_TEXT_BYTES + 1))
    await wait_until(lambda: any(e.outcome == ClipOutcome.TOO_LARGE for e in A.events), 10, "chưa TOO_LARGE")
    (ev,) = [e for e in A.events if e.outcome == ClipOutcome.TOO_LARGE]
    assert ev.device_id is None
    A.cb.set_text("nhỏ")
    await wait_until(lambda: B.cb.written() == ["nhỏ"], 5, "B chưa nhận clip nhỏ")
    assert len(sent_clips) == 1


# --- Ca #5: không có máy đích ---------------------------------------------------------------------


async def test_no_connected_target_means_zero_reads(clip_net):
    net = await clip_net(connect=False)
    A = net.A
    A.cb.set_text("không ai nghe")
    A.cb.set_text("vẫn không ai")
    await asyncio.sleep(SETTLE)
    assert A.cb.test_reads == 0
    assert A.events == []


# --- Ca #6: clip mới chiếm chỗ clip đang gửi ------------------------------------------------------


async def test_new_clip_supersedes_big_image_on_real_connection(clip_net, sent_clips):
    net = await clip_net()
    A, B = net.A, net.B
    conn_a = A.node.control_connection(B.id)
    png = PNG_SIGNATURE + bytes(range(256)) * (10 * MiB // 256 - 1)
    A.cb.set_image(png, "fp-anh-" + uuid.uuid4().hex)
    await wait_until(lambda: any(m.kind == "image/png" for m in sent_clips), 10, "A chưa bắt đầu gửi ảnh")
    A.cb.set_text("văn bản sau ảnh")
    await wait_until(lambda: "văn bản sau ảnh" in B.cb.written(), 10, "B chưa nhận văn bản")
    assert B.cb.written()[-1] == "văn bản sau ảnh"
    assert A.node.control_connection(B.id) is conn_a, "kết nối điều khiển không được bị cắt"
    assert not conn_a.closed


# --- Ca #7: mất kết nối, hủy ghép đôi, ghép lại -------------------------------------------------


async def test_link_down_drops_clip_being_assembled(clip_net):
    net = await clip_net()
    A, B = net.A, net.B
    msgs = split_clip(uuid.uuid4().hex, ClipKind.TEXT, "y" * 900_000)
    assert len(msgs) >= 2
    conn_b = B.node.control_connection(A.id)
    await conn_b.send(msgs[0])
    await wait_until(lambda: assembler_of(A.node.clipboard).buffered_bytes(B.id) > 0, 5, "A chưa ráp mảnh 0")
    conn_b.abort()
    await wait_until(lambda: B.id not in A.node.connected_devices(), 5, "A chưa thấy mất kết nối")
    assert assembler_of(A.node.clipboard).buffered_bytes() == 0
    await link(B, A)
    new_b = B.node.control_connection(A.id)
    for m in msgs[1:]:
        await new_b.send(m)
    B.cb.set_text("mốc sau khi nối lại")
    await wait_until(lambda: "mốc sau khi nối lại" in A.cb.written(), 5, "A chưa nhận mốc")
    assert A.cb.written() == ["mốc sau khi nối lại"]


async def test_unpair_forgets_clipboard_state(clip_net):
    net = await clip_net()
    A, B = net.A, net.B
    A.cb.fail_write = True
    B.cb.set_text("ghi lỗi")
    await wait_until(
        lambda: any(e.outcome == ClipOutcome.WRITE_FAILED for e in A.events), 5, "A chưa báo WRITE_FAILED"
    )
    A.cb.fail_write = False
    msgs = split_clip(uuid.uuid4().hex, ClipKind.TEXT, "z" * 900_000)
    await B.node.control_connection(A.id).send(msgs[0])
    await wait_until(lambda: assembler_of(A.node.clipboard).buffered_bytes(B.id) > 0, 5, "A chưa ráp mảnh 0")
    await A.node.unpair(B.id)
    sync = A.node.clipboard
    assert assembler_of(sync).buffered_bytes(B.id) == 0
    assert assembler_of(sync).reserved_bytes(B.id) == 0
    assert await sync.retry_write(B.id) == ClipOutcome.NOTHING_TO_RETRY
    reads = A.cb.test_reads
    A.cb.set_text("sau khi hủy ghép đôi")
    await asyncio.sleep(SETTLE)
    assert A.cb.test_reads == reads, "không còn máy đích sau khi hủy ghép đôi"


@pytest.mark.slow
async def test_repairing_resets_clipboard_to_off(node_factory, monkeypatch):
    """9.3 điểm 1: ghép đôi lại (chưa hủy) → đồng bộ clipboard về tắt, ở cả hai máy."""
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", DEBOUNCE)
    cb_a, cb_b = EchoClipboard(), EchoClipboard()
    B = await node_factory("B", accept_pairing=True, answer=True, node_kwargs={"clipboard": cb_b})
    A = await node_factory("A", answer=True, node_kwargs={"clipboard": cb_a})
    assert str((await asyncio.wait_for(A.pairing.pair_with([LOCAL], B.port), 15)).outcome) == "paired"
    await B.rec.wait_finished(1)
    A.set_clipboard(B.id, True)
    B.set_clipboard(A.id, True)
    assert str((await asyncio.wait_for(A.pairing.pair_with([LOCAL], B.port), 15)).outcome) == "paired"
    await B.rec.wait_finished(2)
    assert A.device_settings(B.id).clipboard is False
    assert B.device_settings(A.id).clipboard is False
    # Hành vi: B (tắt sau khi ghép lại) không ghi dù A bật lại.
    A.connect_hint(B.id, [LOCAL], B.port)
    await wait_until(lambda: B.id in A.connected_devices() and A.id in B.connected_devices(), 5, "chưa nối")
    A.set_clipboard(B.id, True)
    cb_a.set_text("sau khi ghép lại")
    await wait_until(lambda: cb_a.test_reads >= 1, 5, "A chưa đọc")
    await asyncio.sleep(SETTLE)
    assert cb_b.written() == []


# --- Ca #9: ghi lỗi rồi “Thử lại” -----------------------------------------------------------------


async def test_write_failed_then_retry_write(clip_net):
    net = await clip_net()
    A, B = net.A, net.B
    B.cb.fail_write = True
    A.cb.set_text("chép lại giúp")
    await wait_until(
        lambda: any(e.outcome == ClipOutcome.WRITE_FAILED for e in B.events), 5, "B chưa báo WRITE_FAILED"
    )
    (ev,) = [e for e in B.events if e.outcome == ClipOutcome.WRITE_FAILED]
    assert ev.device_id == A.id
    B.cb.fail_write = False
    assert await asyncio.wait_for(B.node.clipboard.retry_write(A.id), 5) == ClipOutcome.RECEIVED
    assert B.cb.written() == ["chép lại giúp"]
    assert await B.node.clipboard.retry_write(A.id) == ClipOutcome.NOTHING_TO_RETRY


# --- Ca #10: close() không chờ backend treo -------------------------------------------------------


async def test_node_close_does_not_wait_for_hung_clipboard_write(clip_net):
    net = await clip_net()
    A, B = net.A, net.B
    B.cb.hang_write = asyncio.Event()  # ghi treo mãi
    A.cb.set_text("treo ở B")
    await wait_until(lambda: B.cb.write_calls == 1, 5, "B chưa bắt đầu ghi")
    start = time.monotonic()
    await asyncio.wait_for(B.node.close(), 10)
    assert time.monotonic() - start < 5
    assert B.events == [], "không phát sự kiện cho lần ghi bị bỏ khi đóng"


# --- 9.3 điểm 10, N9 (ca #11) -------------------------------------------------------------------


async def test_exception_in_clipboard_handler_is_logged_and_connection_kept(clip_net, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    net = await clip_net()
    A, B = net.A, net.B
    conn_a = A.node.control_connection(B.id)

    def boom(self, *args, **kwargs):
        raise RuntimeError("lỗi giả lập")

    monkeypatch.setattr(app_clip.ClipboardSync, "on_message", boom)
    B.cb.set_text("BI-MAT-handler")
    await wait_until(
        lambda: any(r.levelno >= logging.ERROR and B.id[:8] in r.getMessage() for r in caplog.records),
        5,
        "không có log lỗi nhắc 8 ký tự đầu device_id",
    )
    assert not [r for r in caplog.records if "BI-MAT" in r.getMessage()]
    assert A.node.control_connection(B.id) is conn_a and not conn_a.closed


async def test_logs_never_contain_clip_content(clip_net, caplog):
    caplog.set_level(logging.DEBUG)
    net = await clip_net()
    A, B = net.A, net.B
    secret = "BI-MAT-" + uuid.uuid4().hex[:8]
    A.cb.set_text(secret + " 1")
    await wait_until(lambda: B.cb.written() == [secret + " 1"], 5, "B chưa nhận")
    A.cb.set_text(secret + " nhạy cảm", sensitive=True)
    A.cb.set_text(secret * (MAX_TEXT_BYTES // len(secret) + 1))
    await wait_until(lambda: any(e.outcome == ClipOutcome.TOO_LARGE for e in A.events), 10, "chưa TOO_LARGE")
    B.cb.fail_write = True
    A.cb.set_text(secret + " lỗi ghi")
    await wait_until(lambda: any(e.outcome == ClipOutcome.WRITE_FAILED for e in B.events), 5, "chưa lỗi ghi")
    B.cb.fail_write = False
    await B.node.clipboard.retry_write(A.id)
    for r in caplog.records:
        text = r.getMessage() + (r.exc_text or "")
        assert "BI-MAT" not in text, f"log lộ nội dung: {r.name}: {text[:120]!r}"
        if r.name.startswith("teleport.app.clipboard"):
            assert A.id not in text and B.id not in text, f"log có device_id đầy đủ: {text[:120]!r}"


# --- Ca #12: RAM phẳng sau 1000 clip ------------------------------------------------------------


@pytest.mark.slow
async def test_memory_is_flat_after_1000_clips(clip_net, monkeypatch):
    """Đo `tracemalloc` sau `gc` (như do-dac M3): 1000 clip văn bản 100 KB từ A sang B, tăng < 10 MB."""
    for name, value in (("CLIP_RATE", 10_000.0), ("CLIP_BURST", 10_000)):
        monkeypatch.setattr(core_clip, name, value)
        if hasattr(app_clip, name):
            monkeypatch.setattr(app_clip, name, value)
    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", 0.001)
    net = await clip_net()
    A, B = net.A, net.B

    total = 0

    async def run(n: int) -> None:
        nonlocal total
        for _ in range(n):
            text = f"{total:06d}" + "x" * 100_000
            total += 1
            A.cb.set_text(text)
            await wait_until(
                lambda text=text: B.cb.writes and B.cb.writes[-1][1].data == text, 10, "B chưa nhận"
            )
            B.cb.writes.clear()

    await run(100)  # khởi động
    gc.collect()
    tracemalloc.start()
    try:
        gc.collect()
        before = tracemalloc.get_traced_memory()[0]
        await run(900)
        gc.collect()
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    assert after - before < 10 * 1024 * 1024, f"RAM tăng {(after - before) / MiB:.1f} MiB sau 900 clip"
    assert assembler_of(B.node.clipboard).buffered_bytes() == 0


# --- A6 (tan-cong): đóng node khi đang gửi clip lớn trên đường chậm vẫn đẩy được `cancel` ----------


@pytest.mark.slow
async def test_close_while_sending_big_clip_still_delivers_cancel(transfer_nodes, tmp_path, monkeypatch):
    """B gửi file cho A và đang gửi một ảnh 10 MiB qua kết nối điều khiển mà A đọc chậm (~1 MB/s với
    khung `clipboard`); `B.close()` → A vẫn nhận `cancel{user}` (lượt kết thúc `CANCELLED_USER`, by_peer),
    không phải mất kết nối rồi “Đang nối lại…”.

    `CLOSE_TIMEOUT` về lại 5 s thật (fixture `fast` rút còn 0,5 s), vá trước khi tạo node vì
    `ssl_shutdown_timeout` đặt lúc mở kết nối: A đọc phần đuôi còn trong bộ đệm socket ~1 MB/s nên
    lần đóng gọn của B cần hơn 0,5 s; hết hạn thì B abort (RST) và A mất `cancel` dù tầng net đúng."""
    from teleport.app.transfers import TransferResult

    monkeypatch.setattr(app_clip, "CLIP_DEBOUNCE", DEBOUNCE)
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    real_receive = connection.Connection.receive
    started: list[Clipboard] = []
    real_send = connection.Connection.send

    async def slow_receive(self):
        msg = await real_receive(self)
        if isinstance(msg, Clipboard):
            await asyncio.sleep(len(msg.data) / 1e6)  # máy nhận đọc khung clip ~1 MB/s
        return msg

    async def spy_send(self, msg):
        if isinstance(msg, Clipboard):
            started.append(msg)
        return await real_send(self, msg)

    monkeypatch.setattr(connection.Connection, "receive", slow_receive)
    monkeypatch.setattr(connection.Connection, "send", spy_send)
    cb = EchoClipboard()
    net = await transfer_nodes(sender_opts={"rate_limit": 4 * MiB, "clipboard": cb})
    A, B = net.A, net.B
    B.set_clipboard(A.id, True)
    src = net.src / "f.bin"
    src.write_bytes(b"\0" * (64 * MiB))
    key = await B.transfers.send(A.id, [src])
    tid = key.transfer_id
    await wait_until(lambda: "transferring" in A.trec.statuses(tid), 10, "A chưa bắt đầu nhận")
    head = PNG_SIGNATURE + b"\0\0\0\rIHDR" + (64).to_bytes(4, "big") + (64).to_bytes(4, "big")
    cb.set_image(head + bytes(10 * MiB - len(head)), "fp-anh-" + uuid.uuid4().hex)
    await wait_until(lambda: len(started) >= 3, 15, "B chưa gửi tới mảnh clip thứ ba")
    await asyncio.wait_for(B.close(), 20)
    fin = await A.trec.wait_finished(tid, 20)
    assert fin.result == TransferResult.CANCELLED_USER and fin.by_peer is True, fin
