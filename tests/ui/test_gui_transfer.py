"""Gửi / nhận file qua GUI, hai node thật trên 127.0.0.1 (spec PR3 pha 2a, mục “Test”, ca (a)–(g)).

Viết từ spec, không từ code. A là GUI (`teleport.ui.app.main` trong tiến trình, fixture `gui`); B là
một `Node` thật chạy loop riêng trong thread (lớp `Peer` dưới đây: như `peer_node` của
`tests/ui/conftest.py` nhưng có thư mục nhận và tự nhận, để B nhận được file ở ca (d), (e)). Hai bên tin
nhau sẵn bằng cách ghi trust (`trust_each_other`), B nối kết nối điều khiển tới A bằng `connect_hint`.

Đường vào GUI: controller là `GuiApp.transfers` (GuiApp là cha của `Tray`), danh sách lượt là
`controller.view`, hộp hỏi là `controller.offers`. Kết quả cuối của A đọc từ chính `NodeHost.transfer_event`
(test tự nối thêm), không từ thuộc tính nội bộ của thẻ.

Tiến độ: `teleport.app.transfers.PROGRESS_INTERVAL` rút còn 0,2 s để ca có giới hạn tốc độ vẫn ngắn;
tốc độ chậm đặt bằng `rate_limit` của `TransferManager` bên gửi. Chờ bằng điều kiện có hạn (`gui_wait`),
không `sleep` cứng.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import itertools
import os
import re
import threading
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

pytestmark = pytest.mark.integration

LOCAL = "127.0.0.1"
KiB = 1024
MiB = 1024 * 1024

SHORT_SAVED = "Đã lưu"  # spec B3 9.8 (ii): nhãn DONE bên nhận (thay “Xong ✓”)
SHORT_SENT = "Đã gửi"  # spec B3 9.8 (ii): nhãn DONE bên gửi
# Dòng phụ khi xong (mvp mục 7.3 GUI, dòng 3: “khi xong “Đã kiểm tra toàn vẹn””). Kiểm “chứa”, không
# “bằng”: câu xong có thể thêm phần đầu (ví dụ tên file đã lưu khác tên gốc).
VERIFIED = "Đã kiểm tra toàn vẹn"
SHORT_REJECTED = "Đã từ chối"
SHORT_CANCELLED = "Đã hủy"
SHORT_RECONNECTING = "Đang nối lại…"  # mvp F6
# Dòng phụ khi đang truyền (mvp 7.3, spec mục `docs/mvp.md` §7.3 GUI: “45% · 120 MB/s · còn 2 phút”).
PROGRESS_RE = re.compile(r"\d+(,\d)?% · .+/s · (còn .+|đang tính thời gian còn lại)")
RECEIVED_ONE = "Đã nhận {name} từ {peer}."  # câu mới (spec PR3 pha 2a)
PEER_STOPPED_RECEIVING = (
    "{peer} đã dừng nhận giữa chừng. Các file đã gửi xong vẫn nằm trên máy đó."  # mvp mục 8
)


# =================================================================================================
# Máy B
# =================================================================================================


class Peer:
    """`Node` thật (máy B) trong thread riêng; có thư mục nhận, tự nhận file."""

    def __init__(self, config: Path, receive_dir: Path) -> None:
        self.config = config
        self.receive_dir = receive_dir
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="test-peer-b", daemon=True)
        self.node = None
        self.updates: list = []
        self.events: list = []  # `NodeEvent` của B (ca (i), (j): `ConnectFailed`)
        self._lock = threading.Lock()

    def _on_update(self, update) -> None:
        with self._lock:
            self.updates.append(update)

    def _on_event(self, event) -> None:
        with self._lock:
            self.events.append(event)

    def start(self) -> Peer:
        from teleport.app.node import Node

        self.thread.start()

        async def go():
            self.node = Node(
                self.config,
                name="May-B",
                host=LOCAL,
                port=0,
                receive_dir=self.receive_dir,
                auto_accept=True,
                on_event=self._on_event,
                on_transfer_event=self._on_update,
            )
            await self.node.start()

        self.run(go(), 20)
        return self

    def run(self, coro, timeout: float = 10.0):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def soon(self, fn, *args) -> None:
        self.loop.call_soon_threadsafe(fn, *args)

    @property
    def device_id(self) -> str:
        return self.node.identity.device_id

    def connected_to(self, device_id: str) -> bool:
        async def check() -> bool:
            return device_id in self.node.connected_devices()

        return self.run(check(), 5)

    def set_rate(self, rate: int | None) -> None:
        async def go() -> None:
            self.node.transfers.rate_limit = rate

        self.run(go(), 5)

    def send(self, device_id: str, *paths: Path):
        """Không chờ: `concurrent.futures.Future` của `transfers.send`."""
        return asyncio.run_coroutine_threadsafe(self.node.transfers.send(device_id, list(paths)), self.loop)

    def cancel(self, key) -> None:
        self.soon(self.node.transfers.cancel, key)

    def sent_bytes(self, transfer_id: str) -> int:
        """`done_bytes` lớn nhất trong các `TransferProgress` của B cho lượt (bên gửi đếm byte đã gửi)."""
        with self._lock:
            return max(
                (
                    u.info.done_bytes
                    for u in self.updates
                    if type(u).__name__ == "TransferProgress" and u.info.key.transfer_id == transfer_id
                ),
                default=0,
            )

    def connect_failures(self, device_id: str) -> list[str]:
        """Giá trị `ConnectResult` của mọi `ConnectFailed` B thấy với `device_id`, theo thứ tự."""
        with self._lock:
            return [
                str(e.result)
                for e in self.events
                if type(e).__name__ == "ConnectFailed" and e.device.device_id == device_id
            ]

    def trusts(self, device_id: str) -> bool:
        async def check() -> bool:
            return self.node.store.get(device_id) is not None

        return self.run(check(), 5)

    def finished(self, transfer_id: str):
        with self._lock:
            for u in self.updates:
                if type(u).__name__ == "TransferFinished" and u.info.key.transfer_id == transfer_id:
                    return u
        return None

    def close(self) -> None:
        if self.node is not None:
            with contextlib.suppress(Exception):
                self.run(asyncio.wait_for(self.node.close(), 30), 35)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(10)
        if not self.thread.is_alive():
            self.loop.close()


@pytest.fixture
def peer(tmp_path):
    made: list[Peer] = []

    def make(config: Path) -> Peer:
        p = Peer(config, tmp_path / "nhan-B")
        made.append(p)
        return p.start()

    yield make
    for p in reversed(made):
        p.close()


@pytest.fixture
def pair(config_dir, trust_each_other, tmp_path):
    """Hai thư mục cấu hình tin nhau: (a, b, a_id, b_id, src)."""

    def make():
        a, b = config_dir("A"), config_dir("B")
        id_a, id_b = trust_each_other(a, b, name_a="May-A", name_b="May-B")
        src = tmp_path / "nguon"
        src.mkdir(exist_ok=True)
        return a, b, id_a.device_id, id_b.device_id, src

    return make


@pytest.fixture
def fast_progress(monkeypatch):
    from teleport.app import transfers

    monkeypatch.setattr(transfers, "PROGRESS_INTERVAL", 0.2)


# =================================================================================================
# Hàm phụ trợ
# =================================================================================================


def make_file(directory: Path, name: str, size: int) -> Path:
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


def controller(run):
    """`GuiApp.transfers` (GuiApp là cha của khay)."""
    app = run.tray.parent()
    assert app is not None and hasattr(app, "transfers"), (
        "GuiApp phải có thuộc tính transfers (spec PR3 pha 2a)"
    )
    return app.transfers


def find_row(ctl, transfer_id: str, direction: str | None = None):
    for r in ctl.view.rows():
        if r.key.transfer_id == transfer_id and (direction is None or str(r.key.direction) == direction):
            return r
    return None


def rows_of(ctl, direction: str) -> list:
    return [r for r in ctl.view.rows() if str(r.key.direction) == direction]


def a_finished(updates: list, transfer_id: str):
    for u in updates:
        if (
            type(u).__name__ == "TransferFinished"
            and u.info.key.transfer_id == transfer_id
            and str(u.result) != "suspended"
        ):
            return u
    return None


def a_port(run, gui_wait):
    """Kịch bản con: cổng của node A (qua `NodeHost.call`)."""
    got: list = []
    run.host.call(lambda node: node.port, got.append)
    yield gui_wait(lambda: got, 5, "cổng của A")
    assert isinstance(got[0], int), got[0]
    return got[0]


def start_gui(run, gui_wait, updates: list | None = None):
    """Kịch bản con: chờ node A chạy; nối thêm bộ ghi `transfer_event` nếu cần."""
    yield gui_wait(lambda: run.hosts and run.host.running, 15, "node A chạy")
    if updates is not None:
        run.host.transfer_event.connect(updates.append)


def connect_b(peer: Peer, gui_wait, a_id: str, port: int):
    peer.soon(peer.node.connect_hint, a_id, [LOCAL], port)
    yield gui_wait(lambda: peer.connected_to(a_id), 10, "B nối tới A")


def click(ui_helpers, box, text: str) -> None:
    buttons = ui_helpers.buttons_with_text(box, text)
    assert len(buttons) == 1, f"hộp hỏi cần đúng một nút “{text}”"
    buttons[0].click()


def answer_offer(ctl, ui_helpers, accept: bool, known: set | None = None):
    """Bấm Nhận / Từ chối trên hộp hỏi mới (không thuộc `known`); trả `TransferKey` của A."""
    keys = [k for k in list(ctl.offers.keys()) if known is None or k not in known]
    assert len(keys) == 1, keys
    key = keys[0]
    box = ctl.offers.box(key)
    click(ui_helpers, box, ui_helpers.M6_ACCEPT if accept else ui_helpers.M6_REJECT)
    return key


def temp_dir(receive_dir: Path, transfer_id: str) -> Path:
    from teleport.core.filenames import TEMP_DIR_NAME

    return receive_dir / TEMP_DIR_NAME / transfer_id


# =================================================================================================
# (a) Nhận 64 MiB
# =================================================================================================


@pytest.mark.slow
@pytest.mark.demo
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_a_gui_receives_64_mib_after_accept_and_row_shows_done(
    gui, gui_wait, pair, peer, tmp_path, ui_helpers
):
    a, b, a_id, _, src = pair()
    p = peer(b)
    f = make_file(src, "video.bin", 64 * MiB)
    want = sha256_of(f)
    receive_dir = tmp_path / "nhan-gui"
    updates: list = []
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        fut = p.send(a_id, f)
        yield gui_wait(lambda: ctl.offers.keys(), 10, "hộp hỏi nhận file")
        key = answer_offer(ctl, ui_helpers, True)
        tid = key.transfer_id
        yield gui_wait(
            lambda: (r := find_row(ctl, tid)) is not None and r.finished, 60, "thẻ của lượt kết thúc"
        )
        row = find_row(ctl, tid)
        seen["status"] = row.status_label.text()
        seen["detail"] = row.detail_label.text()
        seen["bar"] = (row.progress_bar.value(), row.progress_bar.maximum())
        yield gui_wait(lambda: a_finished(updates, tid), 5, "A thấy TransferFinished")
        seen["a"] = str(a_finished(updates, tid).result)
        yield gui_wait(fut.done, 10, "send() của B trả khóa")
        yield gui_wait(lambda: p.finished(tid), 15, "B thấy lượt kết thúc")
        seen["b"] = str(p.finished(tid).result)
        seen["messages"] = [m for _, m in run.messages]
        run.tray.quit_requested.emit()

    run = gui(["--config-dir", str(a)], script)
    assert run.exec_calls == [], f"không exec() hộp nào: {run.exec_calls}"
    assert seen["a"] == "done" and seen["b"] == "done"
    assert sha256_of(receive_dir / "video.bin") == want
    assert SHORT_SAVED in seen["status"], seen["status"]
    assert VERIFIED in seen["detail"], seen["detail"]
    assert seen["bar"][0] == seen["bar"][1]
    assert RECEIVED_ONE.format(name="video.bin", peer="May-B") in seen["messages"], seen["messages"]


# =================================================================================================
# (b) Nhận lại cùng tên
# =================================================================================================


@pytest.mark.demo
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_b_same_name_again_is_saved_numbered_and_old_file_unchanged(
    gui, gui_wait, pair, peer, tmp_path, ui_helpers
):
    a, b, a_id, _, src = pair()
    p = peer(b)
    f = make_file(src, "bao-cao.txt", 200 * KiB)
    first = sha256_of(f)
    receive_dir = tmp_path / "nhan-gui"
    updates: list = []
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        done_keys: set = set()
        for _ in range(2):
            p.send(a_id, f)
            yield gui_wait(lambda: [k for k in list(ctl.offers.keys()) if k not in done_keys], 10, "hộp hỏi")
            key = answer_offer(ctl, ui_helpers, True, done_keys)
            done_keys.add(key)
            yield gui_wait(lambda k=key: a_finished(updates, k.transfer_id), 30, "A nhận xong")
            seen.setdefault("results", []).append(str(a_finished(updates, key.transfer_id).result))
            if len(done_keys) == 1:
                f.write_bytes(os.urandom(150 * KiB))  # nội dung mới, cùng tên
                seen["second"] = sha256_of(f)
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["results"] == ["done", "done"]
    assert sha256_of(receive_dir / "bao-cao.txt") == first, "file cũ không được bị ghi đè"
    assert sha256_of(receive_dir / "bao-cao (1).txt") == seen["second"]


# =================================================================================================
# (c) Từ chối
# =================================================================================================


@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_c_reject_makes_sender_see_rejected_user(gui, gui_wait, pair, peer, tmp_path, ui_helpers):
    a, b, a_id, _, src = pair()
    p = peer(b)
    f = make_file(src, "a.bin", 100 * KiB)
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        p.send(a_id, f)
        yield gui_wait(lambda: ctl.offers.keys(), 10, "hộp hỏi")
        key = answer_offer(ctl, ui_helpers, False)
        yield gui_wait(lambda: p.finished(key.transfer_id), 15, "B thấy lượt kết thúc")
        fin = p.finished(key.transfer_id)
        seen["b"], seen["by_peer"] = str(fin.result), fin.by_peer
        yield gui_wait(
            lambda: (r := find_row(ctl, key.transfer_id)) is not None and r.finished, 5, "thẻ kết thúc"
        )
        seen["status"] = find_row(ctl, key.transfer_id).status_label.text()
        seen["boxes"] = ctl.offers.keys()
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["b"] == "rejected_user"
    assert seen["by_peer"] is True
    assert SHORT_REJECTED in seen["status"], seen["status"]
    assert seen["boxes"] == []
    assert not (tmp_path / "nhan-gui" / "a.bin").exists()


# =================================================================================================
# (d) GUI gửi tới B
# =================================================================================================


@pytest.mark.slow
def test_d_gui_sends_to_peer_with_progress_on_row_then_done(
    gui, gui_wait, pair, peer, tmp_path, fast_progress, ui_helpers
):
    a, b, a_id, b_id, src = pair()
    p = peer(b)
    f = make_file(src, "gui-gui.bin", 6 * MiB)
    want = sha256_of(f)
    updates: list = []
    seen: dict = {"progress": [], "bars": []}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        yield gui_wait(lambda: run.window.devices.device(b_id) is not None, 10, "B trên radar")
        rate_set: list = []
        run.host.call(lambda n: setattr(n.transfers, "rate_limit", 2 * MiB), rate_set.append)
        yield gui_wait(lambda: rate_set, 5, "đặt rate_limit cho A")
        ctl.request_send(b_id, [f])

        def watch() -> bool:
            rows = rows_of(ctl, "send")
            if not rows:
                return False
            row = rows[0]
            text = row.detail_label.text()
            if PROGRESS_RE.search(text):
                seen["progress"].append(text)
            seen["bars"].append(row.progress_bar.value())
            return row.finished

        yield gui_wait(watch, 30, "thẻ gửi kết thúc")
        [row] = rows_of(ctl, "send")
        tid = row.key.transfer_id
        seen["status"] = row.status_label.text()
        seen["detail"] = row.detail_label.text()
        seen["notice"] = ctl.view.notice_text() or None
        yield gui_wait(lambda: a_finished(updates, tid), 5, "A thấy TransferFinished")
        seen["a"] = str(a_finished(updates, tid).result)
        yield gui_wait(lambda: p.finished(tid), 15, "B thấy lượt kết thúc")
        seen["b"] = str(p.finished(tid).result)
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["notice"] is None
    assert seen["a"] == "done" and seen["b"] == "done"
    assert seen["progress"], "thẻ phải hiện dòng tiến độ (%/tốc độ/còn lại) khi đang gửi"
    assert any(0 < v < 1000 for v in seen["bars"]), (
        f"thanh tiến độ phải có giá trị giữa chừng: {set(seen['bars'])}"
    )
    assert SHORT_SENT in seen["status"], seen["status"]
    assert VERIFIED in seen["detail"], seen["detail"]
    assert sha256_of(tmp_path / "nhan-B" / f.name) == want


# =================================================================================================
# (e) Hủy từ mỗi bên
# =================================================================================================


@pytest.mark.parametrize("who", ["gui_receiver", "peer_sender", "gui_sender", "peer_receiver"])
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_e_cancel_from_either_side_is_cancelled_user_and_temp_removed(
    gui, gui_wait, pair, peer, tmp_path, fast_progress, ui_helpers, who
):
    a, b, a_id, b_id, src = pair()
    p = peer(b)
    f = make_file(src, "huy.bin", 8 * MiB)
    gui_receives = who in ("gui_receiver", "peer_sender")
    receive_dir = tmp_path / ("nhan-gui" if gui_receives else "nhan-B")
    rate = 256 * KiB
    updates: list = []
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        b_key = None
        if gui_receives:
            p.set_rate(rate)
            fut = p.send(a_id, f)
            yield gui_wait(lambda: ctl.offers.keys(), 10, "hộp hỏi")
            key = answer_offer(ctl, ui_helpers, True)
            yield gui_wait(fut.done, 10, "send() của B trả khóa")
            b_key = fut.result()
        else:
            yield gui_wait(lambda: run.window.devices.device(b_id) is not None, 10, "B trên radar")
            rate_set: list = []
            run.host.call(lambda n: setattr(n.transfers, "rate_limit", rate), rate_set.append)
            yield gui_wait(lambda: rate_set, 5, "đặt rate_limit cho A")
            ctl.request_send(b_id, [f])
            yield gui_wait(lambda: rows_of(ctl, "send"), 10, "thẻ gửi")
            key = rows_of(ctl, "send")[0].key
        tid = key.transfer_id
        tmp = temp_dir(receive_dir, tid)
        # Bên gửi đã gửi được một phần (bên nhận chỉ cộng `done_bytes` sau mỗi lô `fsync`).
        if gui_receives:
            yield gui_wait(lambda: p.sent_bytes(tid) > 0, 20, "B đã gửi một phần")
        else:
            yield gui_wait(
                lambda: (r := find_row(ctl, tid)) is not None and r.progress_bar.value() > 0,
                20,
                "A đã gửi một phần",
            )
        yield gui_wait(lambda: tmp.is_dir(), 10, "có thư mục tạm bên nhận")
        assert find_row(ctl, tid) is not None and not find_row(ctl, tid).finished
        if who == "peer_sender":
            p.cancel(b_key)
        elif who == "peer_receiver":
            from teleport.core.transfer import Direction, TransferKey

            p.cancel(TransferKey(a_id, Direction.RECEIVE, tid))  # B (bên nhận) tự hủy
        else:
            row = find_row(ctl, tid)
            assert row.cancel_button.isVisible() and row.cancel_button.isEnabled()
            row.cancel_button.click()
        yield gui_wait(lambda: a_finished(updates, tid) and p.finished(tid), 15, "hai bên kết thúc")
        seen["a"] = str(a_finished(updates, tid).result)
        seen["b"] = str(p.finished(tid).result)
        yield gui_wait(lambda: find_row(ctl, tid).finished, 5, "thẻ kết thúc")
        seen["status"] = find_row(ctl, tid).status_label.text()
        seen["detail"] = find_row(ctl, tid).detail_label.text()
        yield gui_wait(lambda: not tmp.exists(), 15, "thư mục tạm bên nhận bị xóa")
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["a"] == "cancelled_user", seen
    assert seen["b"] == "cancelled_user", seen
    assert SHORT_CANCELLED in seen["status"], seen["status"]
    assert not (receive_dir / f.name).exists(), "file nhận dở không được thành file thật"
    if who == "peer_receiver":
        # mvp mục 8 “Người nhận hủy giữa chừng”, câu máy gửi.
        assert seen["detail"] == PEER_STOPPED_RECEIVING.format(peer="May-B"), seen["detail"]


# =================================================================================================
# (f) Mạng rớt giữa chừng
# =================================================================================================


@pytest.mark.slow
@pytest.mark.demo
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_f_network_cut_shows_reconnecting_then_finishes_without_going_back(
    gui, gui_wait, pair, peer, tmp_path, tcp_proxy, fast_progress, ui_helpers
):
    a, b, a_id, _, src = pair()
    p = peer(b)
    f = make_file(src, "rot-mang.bin", 6 * MiB)
    want = sha256_of(f)
    updates: list = []
    seen: dict = {"bars": [], "statuses": []}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        proxy = tcp_proxy(port)
        yield from connect_b(p, gui_wait, a_id, proxy.port)
        ctl = controller(run)
        p.set_rate(1 * MiB)
        p.send(a_id, f)
        yield gui_wait(lambda: ctl.offers.keys(), 10, "hộp hỏi")
        key = answer_offer(ctl, ui_helpers, True)
        tid = key.transfer_id

        def sampled(pred):
            def check() -> bool:
                row = find_row(ctl, tid)
                if row is not None:
                    seen["bars"].append(row.progress_bar.value())
                    seen["statuses"].append(row.status_label.text())
                return bool(pred(row))

            return check

        yield gui_wait(
            sampled(lambda r: r is not None and p.sent_bytes(tid) >= f.stat().st_size * 3 // 10),
            20,
            "B gửi tới 30 %",
        )
        proxy.block()
        seen["resets"] = proxy.rst()
        yield gui_wait(
            sampled(lambda r: r.status_label.text() == SHORT_RECONNECTING), 15, "thẻ hiện “Đang nối lại…”"
        )
        proxy.resume()
        yield gui_wait(sampled(lambda r: r.finished), 40, "thẻ kết thúc sau khi nối lại")
        seen["status"] = find_row(ctl, tid).status_label.text()
        seen["detail"] = find_row(ctl, tid).detail_label.text()
        yield gui_wait(lambda: a_finished(updates, tid), 5, "A thấy TransferFinished")
        seen["a"] = str(a_finished(updates, tid).result)
        seen["done_bytes"] = [
            u.info.done_bytes
            for u in updates
            if type(u).__name__ == "TransferProgress" and u.info.key.transfer_id == tid
        ]
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["resets"] >= 1, "proxy phải cắt được ít nhất một kết nối"
    assert seen["a"] == "done", seen["a"]
    assert SHORT_RECONNECTING in seen["statuses"]
    bars = seen["bars"]
    assert all(x <= y for x, y in itertools.pairwise(bars)), f"thanh tiến độ bị lùi: {bars}"
    db = seen["done_bytes"]
    assert db and all(x <= y for x, y in itertools.pairwise(db)), f"done_bytes giảm: {db}"
    assert SHORT_SAVED in seen["status"], seen["status"]
    assert VERIFIED in seen["detail"], seen["detail"]
    assert sha256_of(tmp_path / "nhan-gui" / f.name) == want


# =================================================================================================
# (g) Tắt GUI giữa chừng rồi mở lại
# =================================================================================================


@pytest.mark.slow
@pytest.mark.demo
@pytest.mark.usefixtures("offers_as_boxes")  # spec-b4 11.3: test chờ hộp hỏi nhận file
def test_g_restart_gui_mid_transfer_resumes_row_and_finishes(
    gui, gui_wait, pair, peer, tmp_path, fast_progress, ui_helpers
):
    a, b, a_id, _, src = pair()
    p = peer(b)
    f = make_file(src, "khoi-phuc.bin", 6 * MiB)
    want = sha256_of(f)
    updates: list = []
    seen: dict = {}

    def first(run):
        yield from start_gui(run, gui_wait)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        p.set_rate(1 * MiB)
        p.send(a_id, f)
        yield gui_wait(lambda: ctl.offers.keys(), 10, "hộp hỏi")
        key = answer_offer(ctl, ui_helpers, True)
        seen["tid"] = key.transfer_id
        yield gui_wait(
            lambda: (
                find_row(ctl, key.transfer_id) is not None
                and p.sent_bytes(key.transfer_id) >= f.stat().st_size // 5
            ),
            20,
            "B gửi tới 20 %",
        )
        seen["bar_before"] = find_row(ctl, key.transfer_id).progress_bar.value()
        run.tray.quit_requested.emit()  # thoát GUI có trật tự giữa lượt

    gui(["--config-dir", str(a)], first)
    tid = seen["tid"]
    assert p.finished(tid) is None, "B không được kết thúc lượt chỉ vì A tắt"

    def second(run):
        yield from start_gui(run, gui_wait, updates)
        ctl = controller(run)
        yield gui_wait(
            lambda: find_row(ctl, tid) is not None, 10, "thẻ của lượt dở (TransferResumed/ảnh chụp)"
        )
        from teleport.ui.chat_bubbles import TransferBubble

        # Đếm widget thẻ thật (không qua `rows()`): ảnh chụp và `TransferResumed` không được dựng hai thẻ.
        # Spec B3 9.11: đếm `TransferBubble` (bong bóng thay thẻ cũ).
        seen["rows_after_start"] = [r.key.transfer_id for r in ctl.view.findChildren(TransferBubble)]
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        yield gui_wait(lambda: find_row(ctl, tid).finished, 40, "thẻ kết thúc sau khi khôi phục")
        seen["status"] = find_row(ctl, tid).status_label.text()
        seen["detail"] = find_row(ctl, tid).detail_label.text()
        yield gui_wait(lambda: a_finished(updates, tid), 5, "A thấy TransferFinished")
        seen["a"] = str(a_finished(updates, tid).result)
        yield gui_wait(lambda: p.finished(tid), 15, "B thấy lượt kết thúc")
        seen["b"] = str(p.finished(tid).result)
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], second)
    assert seen["rows_after_start"].count(tid) == 1, "một lượt một thẻ (không nhân đôi)"
    assert seen["a"] == "done" and seen["b"] == "done", seen
    assert SHORT_SAVED in seen["status"], seen["status"]
    assert VERIFIED in seen["detail"], seen["detail"]
    assert sha256_of(tmp_path / "nhan-gui" / f.name) == want


# =================================================================================================
# (i), (j) Máy đã hủy ghép đôi (mvp H5, F2 “Hủy ghép đôi có hiệu lực ngay”, mục 8 “Máy kia từ chối máy này”)
# =================================================================================================

REPAIR = "Ghép đôi lại"  # mvp mục 8, cột hành động của dòng “Máy kia từ chối máy này”
UNPAIR_ACCEPT = "Hủy ghép đôi"  # mvp mục 8 “Giao diện: hủy ghép đôi”, nút của hộp xác nhận
REFUSED = "{name} từ chối kết nối từ máy này. Có thể máy đó đã hủy ghép đôi."  # mvp mục 8, cùng dòng


def files_under(directory: Path) -> list[Path]:
    """Mọi file (kể cả file tạm trong thư mục tạm) dưới `directory`; thư mục chưa có → []."""
    if not directory.exists():
        return []
    return [x for x in directory.rglob("*") if x.is_file()]


def quit_confirm_boxes() -> list:
    """Hộp hỏi lại khi Thoát (objectName `quitConfirmBox`) đang hiện."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    return [
        w
        for w in QApplication.topLevelWidgets()
        if isinstance(w, QMessageBox) and w.isVisible() and w.objectName() == "quitConfirmBox"
    ]


def notice_buttons(ctl, text: str) -> list:
    """Nút đang hiện trên dải thông báo của danh sách lượt có chữ `text` (như test_transfers_controller)."""
    from PySide6.QtWidgets import QPushButton

    return [
        b
        for b in ctl.view.findChildren(QPushButton)
        if b.text() == text and not b.isHidden() and b.isVisibleTo(ctl.view)
    ]


@pytest.mark.demo
def test_i_unpaired_sender_cannot_send_no_offer_box_no_file(gui, gui_wait, pair, peer, tmp_path, ui_helpers):
    """H5: A (GUI) hủy ghép đôi B qua luồng ghép đôi của GUI; B (vẫn tin A) gửi tới A → A không hỏi,
    không có thẻ nhận, không có file (kể cả file tạm); B bị A từ chối kết nối (`ConnectFailed(REJECTED)`)."""
    a, b, a_id, b_id, src = pair()
    p = peer(b)
    f = make_file(src, "sau-khi-huy.bin", 200 * KiB)
    receive_dir = tmp_path / "nhan-gui"
    updates: list = []
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait, updates)
        port = yield from a_port(run, gui_wait)
        yield from connect_b(p, gui_wait, a_id, port)
        ctl = controller(run)
        app = run.tray.parent()
        messages: list[str] = []
        app.pairing.message.connect(messages.append)
        yield gui_wait(lambda: run.window.devices.device(b_id) is not None, 10, "B trên radar của A")
        # Đường của người dùng (mvp mục 8 “Giao diện: hủy ghép đôi”): chuột phải → “Hủy ghép đôi…” phát
        # `conversations.unpair_requested`; hộp xác nhận → nút “Hủy ghép đôi”.
        run.window.conversations.unpair_requested.emit(b_id)
        yield gui_wait(lambda: app.pairing.unpair_box is not None, 5, "hộp xác nhận hủy ghép đôi")
        [accept] = ui_helpers.buttons_with_text(app.pairing.unpair_box, UNPAIR_ACCEPT)
        accept.click()
        yield gui_wait(lambda: messages, 15, "GUI báo kết quả hủy ghép đôi")
        seen["unpair_message"] = messages[0]
        forgot: list = []
        run.host.call(lambda n: n.store.get(b_id) is None, forgot.append)
        yield gui_wait(lambda: forgot, 5, "đọc kho tin cậy của A")
        seen["a_forgot_b"] = forgot[0]
        yield gui_wait(lambda: not p.connected_to(a_id), 10, "kết nối B–A bị đóng")
        seen["b_still_trusts_a"] = p.trusts(a_id)
        fut = p.send(a_id, f)
        yield gui_wait(fut.done, 10, "send() của B trả về")
        try:
            seen["send"] = fut.result()
        except Exception as e:  # ghi lại để báo
            seen["send"] = e
        yield gui_wait(lambda: "rejected" in p.connect_failures(a_id), 15, "B bị A từ chối kết nối")
        # Từ chối ở bắt tay TLS: sau đó không còn đường nào để offer tới A. Vẫn cho thêm vài nhịp để một
        # hộp hỏi (nếu có lỗi) kịp hiện: đây là kiểm phủ định nên chờ một cửa sổ cố định (~0,5 s) có chủ ý.
        for _ in range(25):
            yield
        seen["offers"] = list(ctl.offers.keys())
        seen["receive_rows"] = [r.key.transfer_id for r in rows_of(ctl, "receive")]
        seen["a_offer_events"] = [type(u).__name__ for u in updates if type(u).__name__ == "OfferReceived"]
        seen["files"] = files_under(receive_dir)
        key = seen["send"] if not isinstance(seen["send"], BaseException) else None
        seen["b_finished"] = None if key is None else p.finished(key.transfer_id)
        seen["boxes"] = list(run.exec_calls)
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    # mvp mục 8 “Giao diện: hủy ghép đôi”, câu khi xong.
    assert seen["unpair_message"] == "Đã hủy ghép đôi với “May-B”.", seen["unpair_message"]
    assert seen["a_forgot_b"] is True
    assert seen["b_still_trusts_a"] is True, "ca này kiểm A từ chối, B phải vẫn tin A"
    assert seen["offers"] == [], "A đã hủy ghép đôi B: không được có hộp hỏi nhận file"
    assert seen["receive_rows"] == [], "không có thẻ lượt nhận mới"
    assert seen["a_offer_events"] == []
    assert seen["files"] == [], f"thư mục nhận của A phải trống: {seen['files']}"
    assert seen["boxes"] == [], f"A không được bật hộp nào: {seen['boxes']}"
    # Hành vi thật: B vẫn tin A nên `send` tạo lượt (trả TransferKey), rồi lần nối tới A bị từ chối
    # ở bắt tay (`ConnectFailed(REJECTED)`); lượt của B không bao giờ xong.
    assert not isinstance(seen["send"], BaseException), seen["send"]
    fin = seen["b_finished"]
    assert fin is None or str(fin.result) != "done", fin


def setup_b_unpairs_gui(run, gui_wait, p: Peer, a_id: str, b_id: str):
    """Kịch bản con của ca (j): A (GUI) nối tới B (A biết địa chỉ B, như khi radar thấy B qua mDNS hay
    người dùng nhập IP), rồi B hủy ghép đôi A. A vẫn tin B."""

    async def b_port() -> int:
        return p.node.port

    port = p.run(b_port(), 5)
    hinted: list = []
    run.host.call(lambda n: n.connect_hint(b_id, [LOCAL], port), hinted.append)
    yield gui_wait(lambda: hinted, 5, "A nối tới B")
    assert not isinstance(hinted[0], BaseException), hinted[0]
    yield gui_wait(lambda: p.connected_to(a_id), 10, "A–B đã kết nối")
    yield gui_wait(lambda: run.window.devices.device(b_id) is not None, 10, "B trên radar của A")
    p.run(p.node.unpair(a_id), 15)
    yield gui_wait(lambda: not p.connected_to(a_id), 10, "kết nối A–B bị đóng")


@pytest.mark.demo
def test_j_gui_sender_rejected_by_peer_shows_notice_with_repair_button(
    gui, gui_wait, pair, peer, tmp_path, ui_helpers
):
    """Ca ngược: B hủy ghép đôi A (GUI). A (vẫn tin B, biết địa chỉ B) gửi tới B lần đầu → trong 15 s
    dải thông báo bên gửi hiện câu mvp mục 8 “Máy kia từ chối máy này” kèm nút “Ghép đôi lại”; lượt mới
    đó không treo thẻ “Đang nối lại…” (thẻ bị gỡ, không còn lượt gửi dở)."""
    a, b, a_id, b_id, src = pair()
    p = peer(b)
    f = make_file(src, "bi-tu-choi.bin", 200 * KiB)
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait)
        ctl = controller(run)
        yield from setup_b_unpairs_gui(run, gui_wait, p, a_id, b_id)
        ctl.request_send(b_id, [f])
        yield gui_wait(lambda: notice_buttons(ctl, REPAIR), 15, "dải thông báo có nút “Ghép đôi lại”")
        seen["notice"] = ctl.view.notice_text() or None
        yield gui_wait(lambda: not rows_of(ctl, "send"), 5, "thẻ lượt mới bị gỡ")
        seen["sending"] = ctl.active_sends()
        run.tray.quit_requested.emit()

    gui(["--config-dir", str(a)], script)
    assert seen["notice"] == REFUSED.format(name="May-B"), seen["notice"]
    assert seen["sending"] == [], seen["sending"]


def test_j2_gui_resend_after_peer_refused_shows_notice_repair_button_and_no_new_row(
    gui, gui_wait, pair, peer, tmp_path, ui_helpers
):
    """Ca ngược, lần gửi sau khi radar đã biết B từ chối (spec-hackathon mục 10 A2): câu mvp mục 8 “Máy
    kia từ chối máy này”, nút “Ghép đôi lại” (bấm thì phát `repair_requested`), không tạo lượt mới; B
    không có file."""
    a, b, a_id, b_id, src = pair()
    p = peer(b)
    f = make_file(src, "bi-tu-choi.bin", 200 * KiB)
    seen: dict = {}

    def script(run):
        yield from start_gui(run, gui_wait)
        ctl = controller(run)
        yield from setup_b_unpairs_gui(run, gui_wait, p, a_id, b_id)
        ctl.request_send(b_id, [f])  # lần đầu: A nối tới B và bị từ chối
        yield gui_wait(
            lambda: str(run.window.devices.failure(b_id)) == "rejected", 15, "radar của A biết B từ chối"
        )
        seen["rows_before"] = len(rows_of(ctl, "send"))
        ctl.request_send(b_id, [f])
        yield gui_wait(lambda: notice_buttons(ctl, REPAIR), 5, "dải thông báo có nút “Ghép đôi lại”")
        seen["notice"] = ctl.view.notice_text() or None
        seen["rows_after"] = len(rows_of(ctl, "send"))
        repaired: list = []
        ctl.repair_requested.connect(lambda v: repaired.append(v.device_id))
        [button] = notice_buttons(ctl, REPAIR)
        seen["button_name"] = button.accessibleName()
        button.click()
        yield gui_wait(lambda: repaired, 5, "nút “Ghép đôi lại” phát repair_requested")
        seen["repaired"] = repaired
        seen["files_b"] = files_under(tmp_path / "nhan-B")
        # Phòng khi lượt gửi đầu còn dở (test_j khóa việc nó bị gỡ): Thoát hỏi lại (`quitConfirmBox`),
        # chọn “Thoát” như người dùng.
        sending = bool(ctl.active_sends())
        run.tray.quit_requested.emit()
        if sending:
            yield gui_wait(lambda: quit_confirm_boxes(), 5, "hộp hỏi lại khi Thoát")
            [box] = quit_confirm_boxes()
            [yes] = [btn for btn in box.buttons() if ui_helpers.plain(btn.text()) == "Thoát"]
            yes.click()

    gui(["--config-dir", str(a)], script)
    assert seen["notice"] == REFUSED.format(name="May-B"), seen["notice"]
    assert seen["rows_after"] == seen["rows_before"], "thiết bị đang chặn: không tạo lượt mới"
    assert seen["button_name"] == REPAIR
    assert seen["repaired"] == [b_id]
    assert seen["files_b"] == [], seen["files_b"]


@pytest.fixture
def offers_as_boxes(monkeypatch):
    """spec-b4 11.3: đang nhìn đúng luồng của máy gửi thì lời mời chỉ ở bong bóng; test chờ hộp hỏi
    vá `ui.transfers.default_window_active` thành False để hộp luôn bật."""
    from teleport.ui import transfers

    monkeypatch.setattr(transfers, "default_window_active", lambda: False)
