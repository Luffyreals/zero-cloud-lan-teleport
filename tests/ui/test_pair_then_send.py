"""“Ghép rồi gửi” ở mức `GuiApp`: nối `TransfersController` với `PairingController` (spec hackathon PR3,
“Xong khi” (2): thả vào máy chưa ghép → ghép, PAIRED xong tự gửi; bị hủy ghép giữa chừng → `KeyError`
ra câu).

Viết từ spec và hợp đồng PR3 → PR2 (không từ code):

- `transfers.pair_needed` → ghép đôi; không bắt đầu được (offline, đang bận) → bỏ ngay việc chờ.
- Việc ghép chủ động kết thúc mà không PAIRED (mọi đường: từ chối, lỗi, người dùng hủy) → bỏ việc chờ.
- PAIRED → gửi đúng các đường dẫn đã thả.
- `transfers.repair_requested` → ghép đôi; `conversations.unpair_requested` → hộp xác nhận hủy ghép đôi.
- mvp mục 8: “Đang chờ ghép đôi với *A* để gửi file…” chỉ khi đang có việc chờ thật; “Chưa ghép đôi
  với *X* nên chưa gửi được…” khi `send` báo `KeyError`.

Ba phần:

1. Dây nối: `GuiApp` dựng bằng fixture `gui` (`main()` thật), kiểm `isSignalConnected`.
2. Đơn vị: `GuiApp` dựng trực tiếp, `PairingController` thật trên một host giả (`FakeHost`), nên đi
   đúng đường `pair_device` → `submit` → `on_done` → `job_done` / `paired` → `TransfersController`.
3. Integration (`integration`): GUI A (`main()` trong tiến trình) và Node B thật trên 127.0.0.1. Không
   có mDNS thật: A dùng một `MdnsDiscovery` giả (seam cấp module `teleport.app.node.MdnsDiscovery`) để
   B hiện trên radar A dạng “chưa ghép”; B nhận ghép đôi và tự xác nhận mã, tự nhận file.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import inspect
import os
import threading
import time
from pathlib import Path
from types import MappingProxyType, SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QMetaMethod, QObject, Signal

from teleport.app.devices import DeviceView
from teleport.app.pairing import PairingFinished, PairingOutcome
from teleport.core.pairing import Role

LOCAL = "127.0.0.1"
B_ID = "b" * 64
OTHER_ID = "c" * 64
# mvp mục 8 (nguyên văn, tên máy không có ngoặc).
PAIR_WAIT_PREFIX = "Đang chờ ghép đôi với"
NOT_PAIRED = "Chưa ghép đôi với {name} nên chưa gửi được. Hãy ghép đôi rồi gửi lại."


# =================================================================================================
# Hàm phụ trợ chung
# =================================================================================================


def _view(
    device_id: str = B_ID,
    name: str = "May-B",
    *,
    paired: bool = False,
    online: bool = True,
    addresses: tuple[str, ...] = (LOCAL,),
    port: int | None = 47474,
) -> DeviceView:
    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=paired,
        online=online,
        connected=False,
        addresses=addresses,
        port=port,
    )


def _finished(outcome: PairingOutcome, device_id: str = B_ID, **kw) -> PairingFinished:
    values = {
        "session_id": 1,
        "role": Role.INITIATOR,
        "outcome": outcome,
        "address": LOCAL,
        "port": 47474,
        "peer_name": "May-B",
        "peer_device_id": device_id,
        "peer_reason": None,
        "device": None,
        "known_name": None,
        "code_shown": True,
    }
    values.update(kw)
    return PairingFinished(**values)


def _connected(obj: QObject, signal) -> bool:
    return obj.isSignalConnected(QMetaMethod.fromSignal(signal))


# =================================================================================================
# 1. Dây nối trong GuiApp (qua `main()` thật)
# =================================================================================================


def test_gui_app_connects_pair_then_send_signals(gui, gui_wait, config_dir):
    """Hợp đồng PR3 → PR2: đã nối `pair_needed`, `repair_requested`, `job_done`, `paired`,
    `conversations.unpair_requested` (spec B2 12.29)."""
    a = config_dir("A", identity=False)  # màn “Bắt đầu”: GuiApp đủ dây nối, không chạy node
    seen: dict = {}

    def script(run):
        yield gui_wait(lambda: run.trays and run.tray.parent() is not None, 5, "GuiApp dựng xong")
        app = run.tray.parent()
        seen["pair_needed"] = _connected(app.transfers, app.transfers.pair_needed)
        seen["repair_requested"] = _connected(app.transfers, app.transfers.repair_requested)
        seen["job_done"] = _connected(app.pairing, app.pairing.job_done)
        seen["paired"] = _connected(app.pairing, app.pairing.paired)
        conversations = app.window.conversations
        seen["unpair_requested"] = _connected(conversations, conversations.unpair_requested)
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script, timeout=20)
    assert seen == {
        "pair_needed": True,
        "repair_requested": True,
        "job_done": True,
        "paired": True,
        "unpair_requested": True,
    }


# =================================================================================================
# 2. Đơn vị: GuiApp + PairingController thật trên host giả
# =================================================================================================


class _Job:
    def __init__(self) -> None:
        self.cancelled = False
        self.done = False

    def cancel(self) -> None:
        self.cancelled = True


class FakeHost(QObject):
    """Phần `NodeHost` mà `PairingController` và `TransfersController` dùng; không chạy gì."""

    pairing_prompt = Signal(object)
    pairing_finished = Signal(object)

    def __init__(self, receive_dir: Path) -> None:
        super().__init__()
        self.options = SimpleNamespace(receive_dir=receive_dir)
        self.calls: list = []
        self.submits: list = []  # (fn, on_done, job)

    def call(self, fn, on_done=None) -> None:
        self.calls.append((fn, on_done))

    def submit(self, fn, on_done=None):
        job = _Job()
        self.submits.append((fn, on_done, job))
        return job


class _FakeTransfers:
    def __init__(self) -> None:
        self.sent: list[tuple[str, list[Path]]] = []

    def history(self, device_id=None):
        """Spec B2 12.22: `TransfersController.on_started` đọc thêm lịch sử."""
        return ()

    def send(self, device_id, paths):
        self.sent.append((device_id, list(paths)))
        return None


class _FakePairing:
    def __init__(self) -> None:
        self.pair_calls: list = []

    def pair_with(self, addresses, port):
        self.pair_calls.append((list(addresses), port))
        return None


class _FakeNode:
    def __init__(self) -> None:
        self.transfers = _FakeTransfers()
        self.pairing = _FakePairing()

    def devices(self):
        return ()


@pytest.fixture
def env(qapp, tmp_path):
    """`GuiApp` dựng trực tiếp; `PairingController` và `TransfersController` dùng chung một `FakeHost`."""
    from teleport.ui import app as ui_app

    gui_app = ui_app.GuiApp(qapp, tmp_path / "cfg")
    host = FakeHost(tmp_path / "nhan")
    gui_app.transfers.attach(host)
    gui_app.pairing.set_host(host)
    src = tmp_path / "nguon"
    src.mkdir()
    files = [src / "a.bin", src / "b.bin"]
    for f in files:
        f.write_bytes(b"x")
    node = _FakeNode()
    kinds: dict[int, str] = {}  # id(job) → "pair" / "send"

    def classify() -> None:
        """Phân loại mỗi `submit` theo việc nó làm trên node giả (chạy đúng một lần mỗi việc)."""
        for fn, _on_done, job in host.submits:
            if id(job) in kinds:
                continue
            if inspect.iscoroutinefunction(fn):
                kinds[id(job)] = "pair"  # ghép đôi từ radar: coroutine, không chạy ở đây
                continue
            before = len(node.transfers.sent)
            fn(node)
            kinds[id(job)] = "send" if len(node.transfers.sent) > before else "pair"

    def pair_jobs() -> list:
        classify()
        return [s for s in host.submits if kinds[id(s[2])] == "pair"]

    def send_jobs() -> list:
        classify()
        return [s for s in host.submits if kinds[id(s[2])] == "send"]

    def run_sends() -> list:
        """Các lời gọi `transfers.send` mà controller đã gửi xuống node."""
        classify()
        return node.transfers.sent

    def notice() -> str | None:
        return gui_app.transfers.view.notice_text()

    yield SimpleNamespace(
        app=gui_app,
        host=host,
        files=files,
        node=node,
        pair_jobs=pair_jobs,
        send_jobs=send_jobs,
        run_sends=run_sends,
        notice=notice,
        model=gui_app.window.devices,
    )
    gui_app.pairing.close_all()
    gui_app.transfers.close_all()
    gui_app.tray.dispose()
    gui_app.window.deleteLater()
    qapp.processEvents()


def test_drop_on_unpaired_device_starts_pairing_with_that_device(env):
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    assert env.app.transfers.pending == (B_ID, env.files)
    assert env.app.pairing.busy, "pair_needed phải mở luồng ghép đôi"
    assert env.app.pairing.progress_box is not None
    assert "May-B" in env.app.pairing.progress_box.text()
    assert len(env.pair_jobs()) == 1
    assert env.run_sends() == [], "chưa PAIRED thì chưa gửi"


def test_job_done_not_paired_drops_pending(env):
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    assert env.app.transfers.pending is not None
    env.app.pairing.job_done.emit(B_ID, False)
    assert env.app.transfers.pending is None
    env.app.pairing.paired.emit(B_ID)  # PAIRED muộn (phiên khác) không được gửi việc đã bỏ
    assert env.run_sends() == []


def test_job_done_without_device_id_not_paired_drops_pending(env):
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    env.app.pairing.job_done.emit(None, False)
    assert env.app.transfers.pending is None


def test_job_done_paired_keeps_pending_until_paired_then_sends_dropped_paths(env):
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    env.app.pairing.job_done.emit(B_ID, True)
    assert env.app.transfers.pending == (B_ID, env.files), "PAIRED: chờ `paired` (sau khi đọc lại devices)"
    assert env.run_sends() == []
    env.app.pairing.paired.emit(B_ID)
    assert env.app.transfers.pending is None
    assert env.run_sends() == [(B_ID, env.files)]


@pytest.mark.parametrize(
    "outcome", [PairingOutcome.USER_REJECTED, PairingOutcome.PEER_REJECTED, PairingOutcome.TIMEOUT]
)
def test_pairing_job_ending_unpaired_drops_pending_and_never_sends(env, outcome):
    """Đường thật: `on_done` của `submit(pair_with)` trả kết quả không PAIRED → việc chờ bị bỏ."""
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    [(_fn, on_done, _job)] = env.pair_jobs()
    env.host.pairing_finished.emit(_finished(outcome))
    on_done(_finished(outcome))
    assert env.app.transfers.pending is None
    assert not env.app.pairing.busy
    assert env.run_sends() == []


def test_pairing_job_paired_with_another_device_drops_pending(env):
    """Địa chỉ cũ của radar giờ là máy C: PAIRED với C không giữ việc chờ của B, không gửi tới ai."""
    other = "c" * 64
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    [(_fn, on_done, _job)] = env.pair_jobs()
    on_done(_finished(PairingOutcome.PAIRED, other))
    assert env.app.transfers.pending is None
    env.app.pairing.paired.emit(other)
    assert env.run_sends() == []


@pytest.mark.parametrize(
    "result",
    [None, ValueError("địa chỉ sai"), RuntimeError("node đang dừng"), OSError("lỗi lạ")],
    ids=["device-gone", "value-error", "runtime-error", "other-error"],
)
def test_pairing_job_error_paths_drop_pending(env, result):
    """Hợp đồng: `on_pairing_finished(…, False)` ở **mọi** đường thoát (kể cả lỗi tham số, RuntimeError)."""
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    [(_fn, on_done, _job)] = env.pair_jobs()
    on_done(result)
    assert env.app.transfers.pending is None
    assert env.run_sends() == []


def test_user_cancels_pairing_from_progress_box_drops_pending(env):
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    box = env.app.pairing.progress_box
    assert box is not None
    box.cancel_button.click()
    [(_fn, on_done, job)] = env.pair_jobs()
    assert job.cancelled, "nút “Hủy” phải hủy việc ghép đôi"
    on_done(asyncio.CancelledError())  # host thật báo hủy về `on_done`
    assert env.app.transfers.pending is None
    assert env.run_sends() == []


def test_paired_then_send_reports_key_error_as_not_paired_sentence(env):
    """Spec PR3 (2): bị hủy ghép đôi sau PAIRED, trước khi gửi → `send` báo KeyError → câu mvp mục 8."""
    env.model.reset((_view(),))
    env.app.transfers.request_send(B_ID, env.files)
    [(_fn, on_done, _job)] = env.pair_jobs()
    env.host.pairing_finished.emit(_finished(PairingOutcome.PAIRED))
    on_done(_finished(PairingOutcome.PAIRED))
    env.app.pairing.paired.emit(B_ID)
    sends = env.send_jobs()
    assert len(sends) == 1
    _send_fn, send_done, _ = sends[0]
    send_done(KeyError(B_ID))
    assert env.notice() == NOT_PAIRED.format(name="May-B")


@pytest.mark.parametrize(
    "view",
    [_view(port=None), _view(addresses=())],
    ids=["no-port", "no-address"],
)
def test_pair_device_refusing_offline_like_device_drops_pending_and_next_drop_is_not_waiting(env, view):
    """`pair_device` trả False (radar không còn địa chỉ/cổng) → bỏ việc chờ ngay; lần sau không
    “Đang chờ…”."""
    env.model.reset((view,))
    env.app.transfers.request_send(B_ID, env.files)
    assert env.app.transfers.pending is None
    assert env.pair_jobs() == []
    env.app.transfers.request_send(B_ID, env.files[:1])
    assert not (env.notice() or "").startswith(PAIR_WAIT_PREFIX), env.notice()
    assert env.app.transfers.pending is None


def test_pair_device_busy_drops_pending_and_next_drop_pairs_normally(env):
    """Đang có một việc ghép đôi khác (nhập IP) → `pair_device` False → bỏ việc chờ; xong việc kia
    thì ghép bình thường."""
    env.model.reset((_view(),))
    assert env.app.pairing.pair_address("192.168.1.9", 47474)
    env.app.transfers.request_send(B_ID, env.files)
    assert env.app.transfers.pending is None, "không bắt đầu được ghép đôi thì không giữ việc chờ"
    env.app.transfers.request_send(B_ID, env.files)
    assert not (env.notice() or "").startswith(PAIR_WAIT_PREFIX), env.notice()
    assert env.app.transfers.pending is None
    # Việc nhập IP kết thúc → lần thả sau mở ghép đôi với B bình thường.
    [(_fn, on_done, _job)] = env.pair_jobs()
    on_done(_finished(PairingOutcome.UNREACHABLE, device_id=None, peer_name=None))
    assert not env.app.pairing.busy
    env.app.transfers.request_send(B_ID, env.files)
    assert env.app.transfers.pending == (B_ID, env.files)
    assert env.app.pairing.busy and len(env.pair_jobs()) == 2


def test_pair_needed_without_host_drops_pending(qapp, tmp_path):
    """GuiApp chưa có node (host None): `pair_device` False → không giữ việc chờ."""
    from teleport.ui import app as ui_app

    gui_app = ui_app.GuiApp(qapp, tmp_path)
    try:
        gui_app.window.devices.reset((_view(),))
        gui_app.transfers.request_send(B_ID, [tmp_path / "a.bin"])
        assert gui_app.transfers.pending is None
        gui_app.transfers.request_send(B_ID, [tmp_path / "a.bin"])
        notice = gui_app.transfers.view.notice_text() or ""
        assert not notice.startswith(PAIR_WAIT_PREFIX), notice
    finally:
        gui_app.pairing.close_all()
        gui_app.tray.dispose()
        gui_app.window.deleteLater()


def test_paired_with_other_device_keeps_pending(env):
    env.model.reset((_view(), _view(OTHER_ID, "May-C")))
    env.app.transfers.request_send(B_ID, env.files)
    env.app.pairing.paired.emit(OTHER_ID)  # máy khác ghép đôi với máy này (vai trả lời)
    assert env.app.transfers.pending == (B_ID, env.files)
    assert env.run_sends() == []


def test_repair_button_starts_pairing(env):
    view = _view(paired=True)
    env.model.reset((view,))
    env.app.transfers.repair_requested.emit(view)
    assert env.app.pairing.busy and len(env.pair_jobs()) == 1


def test_unpair_requested_opens_confirmation_box(env):
    env.model.reset((_view(paired=True),))
    env.app.window.conversations.unpair_requested.emit(B_ID)
    box = env.app.pairing.unpair_box
    assert box is not None and box.isVisible()
    assert "May-B" in box.text()


# =================================================================================================
# 3. Integration: GUI A ↔ Node B trên 127.0.0.1
# =================================================================================================


class _FakeMdns:
    """`MdnsDiscovery` giả của A: không socket; test phát sự kiện bằng `emit` (trên loop của node A)."""

    def __init__(self, registry: list, **kwargs) -> None:
        self.on_event = None
        self._devices: dict = {}
        registry.append(self)

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        self.on_event = None

    async def advertise(self, **kw) -> None:
        pass

    async def stop_advertising(self) -> None:
        pass

    async def start_browsing(self, *, self_device_id, on_event, max_services: int = 256) -> None:
        self.on_event = on_event

    def set_priority(self, device_ids) -> None:
        pass

    @property
    def devices(self):
        return MappingProxyType(dict(self._devices))

    def emit(self, event) -> None:
        self._devices[event.device.device_id] = event.device
        if self.on_event is not None:
            self.on_event(event)


class PeerB:
    """Node B thật (thread riêng): nhận ghép đôi, tự xác nhận mã, tự nhận file."""

    def __init__(self, config: Path, receive_dir: Path) -> None:
        self.config = config
        self.receive_dir = receive_dir
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="test-peer-b", daemon=True)
        self.node = None
        self.updates: list = []
        self.prompts: list = []
        self.pair_results: list = []
        self._lock = threading.Lock()

    def _on_update(self, update) -> None:
        with self._lock:
            self.updates.append(update)

    def _on_prompt(self, prompt) -> None:
        with self._lock:
            self.prompts.append(prompt)
        self.loop.call_soon(self.node.pairing.decide, prompt.session_id, True)

    def _on_pair_finished(self, result) -> None:
        with self._lock:
            self.pair_results.append(result)

    def start(self) -> PeerB:
        from teleport.app.node import Node

        self.thread.start()

        async def go():
            self.node = Node(
                self.config,
                name="May-B",
                host=LOCAL,
                port=0,
                accept_pairing=True,
                on_pairing_prompt=self._on_prompt,
                on_pairing_finished=self._on_pair_finished,
                receive_dir=self.receive_dir,
                auto_accept=True,
                on_transfer_event=self._on_update,
            )
            await self.node.start()

        self.run(go(), 20)
        return self

    def run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    @property
    def device_id(self) -> str:
        return self.node.identity.device_id

    @property
    def port(self) -> int:
        async def get() -> int:
            return self.node.port

        return self.run(get(), 5)

    def kinds(self, name: str) -> list:
        with self._lock:
            return [u for u in self.updates if type(u).__name__ == name]

    def results(self) -> list:
        with self._lock:
            return list(self.pair_results)

    def trusts(self, device_id: str) -> bool:
        async def check() -> bool:
            return self.node.store.get(device_id) is not None

        return self.run(check(), 5)

    def close(self) -> None:
        if self.node is not None:
            with contextlib.suppress(Exception):
                self.run(asyncio.wait_for(self.node.close(), 30), 35)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)
        if not self.thread.is_alive():
            self.loop.close()


@pytest.fixture
def peer_b(tmp_path):
    made: list[PeerB] = []

    def make(config: Path) -> PeerB:
        p = PeerB(config, tmp_path / "nhan-B")
        made.append(p)
        return p.start()

    yield make
    for p in reversed(made):
        p.close()


@pytest.fixture
def fake_mdns_for_gui(monkeypatch):
    """Node của GUI dùng `MdnsDiscovery` giả (chỉ duyệt, không quảng bá); trả danh sách instance.

    Fixture `gui` ép `mdns=None` trong `NodeHost.__init__` (bọc hàm đang có lúc gọi `gui(...)`), nên
    bọc thêm một lớp trước đó để đặt lại `MdnsOptions(advertise=False)` cho node A.
    """
    from teleport.app import node as app_node
    from teleport.ui import bridge

    instances: list[_FakeMdns] = []
    monkeypatch.setattr(app_node, "MdnsDiscovery", lambda **kw: _FakeMdns(instances, **kw))
    real_init = bridge.NodeHost.__init__

    def host_init(self, options, *rest, **kwargs):
        options = dataclasses.replace(options, mdns=app_node.MdnsOptions(advertise=False))
        real_init(self, options, *rest, **kwargs)

    monkeypatch.setattr(bridge.NodeHost, "__init__", host_init)
    return instances


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _a_finished(updates: list, transfer_id: str | None = None):
    for u in updates:
        if (
            type(u).__name__ == "TransferFinished"
            and str(u.result) != "suspended"
            and (transfer_id is None or u.info.key.transfer_id == transfer_id)
        ):
            return u
    return None


def _start_a(run, gui_wait, updates: list | None = None):
    yield gui_wait(lambda: run.hosts and run.host.running, 15, "node A chạy")
    if updates is not None:
        run.host.transfer_event.connect(updates.append)


def _show_b_on_radar(run, gui_wait, instances: list, peer: PeerB):
    """mDNS giả của A thấy B (chưa ghép) → radar A có B online, chưa ghép đôi."""
    from teleport.core.discovery import DeviceAdded, DiscoveredDevice
    from teleport.core.messages import PROTOCOL_VERSION

    yield gui_wait(lambda: instances and instances[-1].on_event is not None, 10, "A đang duyệt mDNS giả")
    device = DiscoveredDevice(
        device_id=peer.device_id,
        name="May-B",
        os="windows",
        proto=PROTOCOL_VERSION,
        port=peer.port,
        addresses=(LOCAL,),
    )
    fake = instances[-1]
    done: list = []
    run.host.call(lambda _node: fake.emit(DeviceAdded(device)), done.append)
    yield gui_wait(lambda: done, 5, "phát DeviceAdded trên loop của A")
    model = run.window.devices
    yield gui_wait(
        lambda: (v := model.device(peer.device_id)) is not None and v.online and not v.paired,
        10,
        "B hiện trên radar A, chưa ghép đôi",
    )


def _drop(run, device_id: str, *paths: Path) -> bool:
    """Spec B2 mục 8(f): danh sách cuộc trò chuyện chỉ có máy đã ghép đôi, nên không còn thả lên máy
    chưa ghép từ giao diện; gọi thẳng `TransfersController.request_send` (“ghép rồi gửi” còn tới B2c)."""
    run.tray.parent().transfers.request_send(device_id, list(paths))
    return True


def _make_file(directory: Path, name: str, size: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(os.urandom(size))
    return path


def _a_sends(run, gui_wait, out: list):
    """Kịch bản con: các lượt gửi của A (qua `transfers.transfers()` trên thread node)."""
    got: list = []
    run.host.call(lambda n: n.transfers.transfers(), got.append)
    yield gui_wait(lambda: got, 5, "đọc các lượt của A")
    out[:] = [i for i in got[0] if str(i.key.direction) == "send"]


@pytest.mark.demo
@pytest.mark.integration
def test_a_drop_on_unpaired_peer_pairs_then_sends_automatically(
    gui, gui_wait, config_dir, peer_b, fake_mdns_for_gui, tmp_path
):
    a, b = config_dir("A"), config_dir("B")
    p = peer_b(b)
    f = _make_file(tmp_path / "nguon", "ghep-roi-gui.bin", 512 * 1024)
    want = _sha256(f)
    updates: list = []
    seen: dict = {}

    def script(run):
        started = time.monotonic()
        yield from _start_a(run, gui_wait, updates)
        yield from _show_b_on_radar(run, gui_wait, fake_mdns_for_gui, p)
        app = run.tray.parent()
        assert _drop(run, p.device_id, f), "radar phải nhận thả lên thiết bị chưa ghép đang online"
        seen["pending"] = app.transfers.pending
        yield gui_wait(lambda: app.pairing.dialogs(), 10, "hộp mã ghép đôi mở ở A")
        [dialog] = app.pairing.dialogs()
        dialog.accept_button.click()  # A: “Trùng khớp”; B tự xác nhận
        yield gui_wait(lambda: _a_finished(updates), 15, "A gửi xong (tự gửi sau PAIRED)")
        fin = _a_finished(updates)
        seen["a"] = str(fin.result)
        seen["direction"] = str(fin.info.key.direction)
        tid = fin.info.key.transfer_id
        yield gui_wait(
            lambda: any(u.info.key.transfer_id == tid for u in p.kinds("TransferFinished")),
            10,
            "B nhận xong",
        )
        seen["b"] = [str(u.result) for u in p.kinds("TransferFinished") if u.info.key.transfer_id == tid]
        seen["paired_on_radar"] = run.window.devices.device(p.device_id).paired
        seen["notice"] = app.transfers.view.notice_text() or None
        seen["elapsed"] = time.monotonic() - started
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script, timeout=40)
    assert seen["pending"] is not None and seen["pending"][0] == p.device_id
    assert seen["a"] == "done" and seen["direction"] == "send", seen
    assert seen["b"] == ["done"], seen
    assert seen["paired_on_radar"] is True
    # PR-7 B4: ghép đôi xong chỉ báo ở dải thông báo (không hộp); không có câu lỗi nào khác.
    assert seen["notice"] in (None, "Đã ghép đôi với “May-B”."), seen["notice"]
    assert _sha256(tmp_path / "nhan-B" / f.name) == want
    assert seen["elapsed"] < 20, seen["elapsed"]


@pytest.mark.slow
@pytest.mark.integration
def test_b_code_mismatch_drops_pending_no_offer_and_next_drop_pairs_again(
    gui, gui_wait, config_dir, peer_b, fake_mdns_for_gui, tmp_path, monkeypatch
):
    """Lần thả sau: B có thời gian chờ tăng dần sau lần ghép hỏng (protocol, `BACKOFF_BASE`), rút
    ngắn ở đây; trong lúc B còn chờ, A nhận “chưa sẵn sàng” và bỏ việc chờ, nên thả lại tới khi hộp mã
    mở (có hạn). Lần nào cũng không được hiện câu “Đang chờ ghép đôi…”."""
    from teleport.core import pairing as core_pairing

    monkeypatch.setattr(core_pairing, "BACKOFF_BASE", 0.3)
    monkeypatch.setattr(core_pairing, "BACKOFF_MAX", 1.0)
    a, b = config_dir("A"), config_dir("B")
    a_id = _a_id(a)
    p = peer_b(b)
    f = _make_file(tmp_path / "nguon", "khong-trung.bin", 4096)
    want = _sha256(f)
    updates: list = []
    seen: dict = {"notices_after": [], "pendings_after": []}

    def script(run):
        started = time.monotonic()
        yield from _start_a(run, gui_wait, updates)
        yield from _show_b_on_radar(run, gui_wait, fake_mdns_for_gui, p)
        app = run.tray.parent()
        assert _drop(run, p.device_id, f)
        yield gui_wait(lambda: app.pairing.dialogs(), 10, "hộp mã ghép đôi mở ở A")
        [dialog] = app.pairing.dialogs()
        dialog.reject_button.click()  # A: “Không trùng”
        yield gui_wait(lambda: app.transfers.pending is None and not app.pairing.busy, 10, "việc chờ bị bỏ")
        yield gui_wait(lambda: p.results(), 10, "B biết phiên đã kết thúc")
        seen["b_outcome"] = [str(r.outcome) for r in p.results()]
        seen["b_trusts_a"] = p.trusts(a_id)
        sends: list = []
        yield from _a_sends(run, gui_wait, sends)
        seen["a_sends"] = sends
        seen["b_offers"] = p.kinds("OfferReceived")
        seen["paired_on_radar"] = run.window.devices.device(p.device_id).paired
        # Lần thả sau: mở lại ghép đôi bình thường (không phải câu “Đang chờ ghép đôi…”).
        retry_until = time.monotonic() + 10
        while True:
            assert _drop(run, p.device_id, f)
            seen["notices_after"].append(app.transfers.view.notice_text() or None)
            seen["pendings_after"].append(app.transfers.pending)
            yield gui_wait(
                lambda: app.pairing.dialogs() or not app.pairing.busy, 10, "lần thả sau: hộp mã hay kết quả"
            )
            if app.pairing.dialogs():
                break
            seen.setdefault("retry_pending", []).append(app.transfers.pending)
            assert time.monotonic() < retry_until, "hết 10 s mà B vẫn chưa nhận ghép đôi lại"
            yield gui_wait(lambda: not app.transfers.pending, 5, "bỏ việc chờ của lần bị từ chối")
        app.pairing.dialogs()[0].accept_button.click()
        yield gui_wait(lambda: _a_finished(updates), 15, "lần sau ghép được và tự gửi")
        seen["a_after"] = str(_a_finished(updates).result)
        tid = _a_finished(updates).info.key.transfer_id
        yield gui_wait(
            lambda: any(u.info.key.transfer_id == tid for u in p.kinds("TransferFinished")), 10, "B nhận xong"
        )
        seen["elapsed"] = time.monotonic() - started
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script, timeout=40)
    assert seen["b_trusts_a"] is False
    assert seen["a_sends"] == [], "không ghép được thì không có lượt gửi nào"
    assert seen["b_offers"] == [], "B không được nhận OfferReceived"
    assert seen["paired_on_radar"] is False
    for notice in seen["notices_after"]:
        assert not (notice or "").startswith(PAIR_WAIT_PREFIX), notice
    for pending in seen["pendings_after"]:
        assert pending is not None and pending[0] == p.device_id, "mỗi lần thả lại phải mở ghép đôi"
    assert seen.get("retry_pending", []) == [None] * len(seen.get("retry_pending", []))
    assert seen["a_after"] == "done"
    assert _sha256(tmp_path / "nhan-B" / f.name) == want
    assert seen["elapsed"] < 20, seen["elapsed"]


def _a_id(config: Path) -> str:
    from teleport.trust.identity import load_or_create_identity

    return load_or_create_identity(config).device_id


@pytest.mark.integration
def test_c_cancel_pairing_from_progress_box_drops_pending_and_sends_nothing(
    gui, gui_wait, config_dir, peer_b, fake_mdns_for_gui, tmp_path
):
    a, b = config_dir("A"), config_dir("B")
    a_id = _a_id(a)
    p = peer_b(b)
    f = _make_file(tmp_path / "nguon", "huy-ghep.bin", 4096)
    seen: dict = {}

    def script(run):
        started = time.monotonic()
        yield from _start_a(run, gui_wait)
        yield from _show_b_on_radar(run, gui_wait, fake_mdns_for_gui, p)
        app = run.tray.parent()
        assert _drop(run, p.device_id, f)
        box = app.pairing.progress_box
        assert box is not None, "thả vào máy chưa ghép phải mở hộp “Đang ghép đôi…”"
        # Cùng nhịp sự kiện Qt với lúc thả: lời hỏi mã (nếu node đã kịp) chưa thể tới thread Qt.
        box.cancel_button.click()
        yield gui_wait(
            lambda: app.transfers.pending is None and not app.pairing.busy, 10, "việc chờ bị bỏ sau Hủy"
        )
        seen["dialogs"] = len(app.pairing.dialogs())
        sends: list = []
        yield from _a_sends(run, gui_wait, sends)
        seen["a_sends"] = sends
        seen["b_offers"] = p.kinds("OfferReceived")
        seen["b_trusts_a"] = p.trusts(a_id)
        seen["elapsed"] = time.monotonic() - started
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script, timeout=40)
    assert seen["a_sends"] == []
    assert seen["b_offers"] == []
    assert seen["b_trusts_a"] is False
    assert seen["elapsed"] < 20, seen["elapsed"]


@pytest.mark.integration
def test_d_unpaired_right_after_paired_before_send_shows_not_paired(
    gui, gui_wait, config_dir, peer_b, fake_mdns_for_gui, tmp_path
):
    """PAIRED rồi bị hủy ghép đôi trước khi `send` chạy → `KeyError` → câu mvp mục 8 “Chưa ghép đôi…”.

    Dựng thứ tự: ngắt `paired` khỏi slot của GuiApp, nối một slot hủy ghép đôi (qua `NodeHost.submit`)
    rồi mới báo `on_pairing_finished(id, True)` khi hủy xong.
    """
    a, b = config_dir("A"), config_dir("B")
    p = peer_b(b)
    f = _make_file(tmp_path / "nguon", "huy-sau-ghep.bin", 4096)
    seen: dict = {}

    def script(run):
        yield from _start_a(run, gui_wait)
        yield from _show_b_on_radar(run, gui_wait, fake_mdns_for_gui, p)
        app = run.tray.parent()
        assert app.pairing.paired.disconnect(app._on_paired)
        unpaired: list = []

        def unpair_then_report(device_id: str) -> None:
            def report(result: object) -> None:
                unpaired.append(result)
                app.transfers.on_pairing_finished(device_id, True)

            run.host.submit(lambda node: node.unpair(device_id), report)

        app.pairing.paired.connect(unpair_then_report)
        assert _drop(run, p.device_id, f)
        yield gui_wait(lambda: app.pairing.dialogs(), 10, "hộp mã ghép đôi mở ở A")
        app.pairing.dialogs()[0].accept_button.click()
        yield gui_wait(lambda: unpaired, 15, "A ghép xong rồi bị hủy ghép đôi")
        seen["unpaired"] = unpaired[0]
        yield gui_wait(lambda: app.transfers.view.notice_text(), 10, "câu báo lỗi gửi")
        seen["notice"] = app.transfers.view.notice_text() or None
        seen["b_offers"] = p.kinds("OfferReceived")
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script, timeout=40)
    assert not isinstance(seen["unpaired"], BaseException), seen["unpaired"]
    assert seen["notice"] == NOT_PAIRED.format(name="May-B"), seen["notice"]
    assert seen["b_offers"] == []
