"""`teleport.ui.transfers.TransfersController` (spec PR3 pha 2a, mục “`ui/transfers.py`” và “Test”).

Viết từ spec, không từ code. Không socket: `NodeHost` giả ghi lại mọi `call(fn, on_done)` /
`submit(fn, on_done)`; test tự chạy `fn` trên một node giả để biết controller định gọi gì, rồi tự gọi
`on_done` (như `NodeHost` làm trên thread Qt). Cửa sổ, khay, radar, `ChatView` (spec B3: thay danh sách
lượt cũ), `OfferPrompts` là widget thật (offscreen).

Câu chữ: câu lỗi đã có ở `ui/send.py` (pha 1, mvp mục 8) so bằng chính hàm của pha 1 kèm một mẩu câu
mvp để chắc câu đúng loại; câu “đang chờ ghép đôi để gửi” và “chưa ghép đôi” đọc lại từ `docs/mvp.md`
mục 8 (dòng “Giao diện: gửi tiếp khi đang chờ ghép đôi…”, “Giao diện: gửi tới thiết bị không (còn) ghép
đôi”); câu mới của pha 2a (bóng thoại “Đã nhận …”, gợi ý thả file) chép từ spec.
"""

from __future__ import annotations

import dataclasses
import os
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

PEER_ID = "a71c04d2" + "e" * 24
OTHER_ID = "0f0f0f0f" + "1" * 24
PEER = "PC-Nha"
OTHER = "Laptop-Minh"
_MVP = Path(__file__).resolve().parents[2] / "docs" / "mvp.md"

# Câu mới của pha 2a (spec PR3 pha 2a, `on_transfer` và `ui/radar.py`).
RECEIVED_ONE = "Đã nhận {name} từ {peer}."
RECEIVED_MANY = "Đã nhận {n} file từ {peer}."
DROP_HINT = "Thả file lên một thiết bị để gửi."
OFFER_WAITING = "Có file đang chờ bạn nhận."  # texts.offer_waiting (như cũ)
WAIT_OFFLINE_SEND = "Đang chờ kết nối tới {p}…"  # transfers_view, mục 10 A2
CLOSE = "Đóng"
REPAIR = "Ghép đôi lại"  # nút của mvp mục 8 “Máy kia từ chối máy này”
UNPAIR = "Hủy ghép đôi"  # nút của mvp mục 8 “Danh tính thiết bị thay đổi”


# =================================================================================================
# Đọc docs/mvp.md
# =================================================================================================


def mvp_message(situation_prefix: str) -> str:
    """Câu (trong “…”) của hàng bảng mvp mục 8 có cột 1 bắt đầu bằng `situation_prefix`."""
    text = _MVP.read_text(encoding="utf-8")
    start = text.index("## 8.")
    nxt = text.find("\n## ", start + 5)
    table = text[start : nxt if nxt != -1 else len(text)]
    rows = [line for line in table.splitlines() if line.startswith("| " + situation_prefix)]
    assert len(rows) == 1, f"mvp mục 8: cần đúng một hàng {situation_prefix!r}, thấy {len(rows)}"
    m = re.search(r"“(.*?)”", rows[0].split(" | ")[1])
    assert m, f"mvp mục 8: hàng {situation_prefix!r} không có câu trong “…”"
    return m.group(1)


def busy_sentence(name: str) -> str:
    """Câu khi thả thêm file lúc đang chờ ghép đôi; `name` là máy **đang chờ ghép**."""
    return mvp_message("Giao diện: gửi tiếp khi đang chờ ghép đôi").replace("*PC-Nha*", name).replace("*", "")


def not_paired_sentence(name: str) -> str:
    return (
        mvp_message("Giao diện: gửi tới thiết bị không (còn) ghép đôi")
        .replace("*PC-Nha*", name)
        .replace("*", "")
    )


# =================================================================================================
# Dữ liệu giả
# =================================================================================================


def dview(
    device_id: str = PEER_ID,
    name: str = PEER,
    *,
    paired: bool = True,
    online: bool = True,
    connected: bool = True,
):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows" if online else None,
        paired=paired,
        online=online,
        connected=connected and paired,
        addresses=("192.0.2.7",) if online else (),
        port=47474 if online else None,
    )


def tkey(direction: str = "receive", device_id: str = PEER_ID, transfer_id: str | None = None):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), transfer_id or uuid.uuid4().hex)


def tinfo(key, *, status: str = "waiting", names=("video.mp4",), size: int = 1000, done: int = 0):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    files = tuple(FileEntry(n, size, 0) for n in names)
    return TransferInfo(
        key=key,
        status=TransferStatus(status),
        files=files,
        names=tuple(names),
        file_index=0,
        done_bytes=done,
        total_bytes=size * len(names),
    )


def offer(key, *, name: str | None = PEER, names=("video.mp4",), auto: bool = False):
    from teleport.app.transfers import OfferReceived
    from teleport.core.messages import FileEntry

    files = tuple(FileEntry(n, 1000, 0) for n in names)
    return OfferReceived(
        key=key,
        device_name=name,
        files=files,
        names=tuple(names),
        total_bytes=1000 * len(names),
        auto_accepted=auto,
    )


def finished(key, result: str = "done", *, names=("video.mp4",)):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=tinfo(key, status="verifying", names=names, done=1000 * len(names)),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=None,
        reject=None,
    )


class FakeTransfers:
    def __init__(self, infos=()) -> None:
        self.sent: list[tuple[str, list[Path]]] = []
        self.cancelled: list = []
        self.decided: list = []
        self.infos = tuple(infos)

    def send(self, device_id, paths):
        self.sent.append((device_id, [Path(p) for p in paths]))
        return SimpleNamespace(kind="coroutine giả")

    def cancel(self, key):
        self.cancelled.append(key)

    def decide(self, key, accept):
        self.decided.append((key, accept))

    def get(self, key):
        """spec-b4 11.7: `_apply_answer` hỏi `get(key)` trước `decide`; lượt giả luôn còn, ở pha hỏi
        người dùng (WAITING)."""
        from teleport.core.transfer import TransferStatus

        return SimpleNamespace(key=key, status=TransferStatus.WAITING)

    def transfers(self):
        return self.infos

    def history(self, device_id=None):
        """Spec B2 12.22: `on_started` đọc thêm lịch sử."""
        return ()


class FakeNode:
    def __init__(self, devices=(), infos=()) -> None:
        self._devices = tuple(devices)
        self.transfers = FakeTransfers(infos)
        self.name = "May-A"
        self.port = 47474

    def devices(self):
        return self._devices


class FakeHost:
    """Thay `NodeHost`: ghi lại `call`/`submit`, không chạy gì cho tới khi test gọi `run_*`."""

    def __init__(self, receive_dir: Path) -> None:
        from teleport.ui.bridge import NodeOptions

        self.options = NodeOptions(config_dir=receive_dir.parent / "cfg", receive_dir=receive_dir, mdns=None)
        self.calls: list = []
        self.submits: list = []
        self.running = True
        self.is_stopped = False
        self.node_name = "May-A"

    def call(self, fn, on_done=None) -> None:
        self.calls.append((fn, on_done))

    def submit(self, fn, on_done=None) -> None:
        self.submits.append((fn, on_done))

    def run_calls(self, node: FakeNode) -> None:
        """Chạy mọi `call` đang chờ trên `node` và trả kết quả về `on_done`."""
        pending, self.calls = self.calls, []
        for fn, on_done in pending:
            try:
                result = fn(node)
            except Exception as e:
                result = e
            if on_done is not None:
                on_done(result)

    def sent(self) -> list[tuple[str, list[Path]]]:
        """(device_id, paths) của mọi `submit` (chạy `fn` trên node giả, không gọi `on_done`)."""
        node = FakeNode()
        for fn, _ in self.submits:
            fn(node)
        return node.transfers.sent


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def env(qtbot, monkeypatch, tmp_path):
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    messages: list[str] = []
    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: messages.append(text))
    window = MainWindow()
    qtbot.addWidget(window)
    tray = Tray()
    ctl = mod.TransfersController(window, tray, parent=None)
    host = FakeHost(tmp_path / "nhan")
    ctl.attach(host)
    ns = SimpleNamespace(
        mod=mod,
        window=window,
        tray=tray,
        ctl=ctl,
        host=host,
        messages=messages,
        conversations=window.conversations,  # spec B2 12.34: thay `radar`
        model=window.devices,
        tmp=tmp_path,
    )
    yield ns
    ctl.close_all()
    tray.dispose()


def label(name: str | None, device_id: str = PEER_ID) -> str:
    from teleport.ui import texts

    return texts.peer_label(name, device_id)


def notice(env) -> str | None:
    """Chữ thông báo đang hiện, None khi không có (spec B3 9.7: `notice_text()` trả “” khi ẩn)."""
    return env.ctl.view.notice_text() or None


def files(env, n: int = 2) -> list[Path]:
    """Đường dẫn chưa có trên đĩa: controller không được stat (thread Qt)."""
    return [env.tmp / "nguon" / f"tep-{i}.bin" for i in range(n)]


# =================================================================================================
# Dựng
# =================================================================================================


def test_controller_places_chat_view_in_window_area_and_owns_offer_prompts(env):
    from teleport.ui.chat import ChatView
    from teleport.ui.offer import OfferPrompts

    assert isinstance(env.ctl.view, ChatView)  # spec B3 mục 2: `TransfersController.view` là `ChatView`
    assert env.window.transfers_area.isAncestorOf(env.ctl.view), "view phải nằm trong window.transfers_area"
    assert isinstance(env.ctl.offers, OfferPrompts)


def test_notice_strip_replaces_old_notice_and_close_button_hides_it(env):
    # Spec B3 9.7: thông báo ở `info_bar` (`InfoBar`), `notice_text()` trả “” khi ẩn.
    from PySide6.QtCore import Qt

    view = env.ctl.view
    assert view.notice_text() == ""
    view.show_notice("Câu một.")
    view.show_notice("Câu hai <b>không HTML</b>.")
    assert view.notice_text() == "Câu hai <b>không HTML</b>."
    assert view.notice_label.textFormat() == Qt.TextFormat.PlainText
    close = view.info_bar.close_button
    assert close.accessibleName().replace("&", "").startswith(CLOSE)  # InfoBar: “Đóng thông báo”
    close.click()
    assert view.notice_text() == ""


# =================================================================================================
# request_send: kiểm trước, không chạm đĩa
# =================================================================================================


def test_request_send_with_no_paths_does_nothing(env):
    env.model.reset([dview()])
    env.ctl.request_send(PEER_ID, [])
    assert env.host.submits == []
    assert notice(env) is None


def test_request_send_over_file_limit_shows_notice_and_does_not_submit(env):
    from teleport.core.messages import MAX_OFFER_FILES
    from teleport.ui import send

    env.model.reset([dview()])
    paths = [env.tmp / f"f{i}.bin" for i in range(MAX_OFFER_FILES + 1)]
    env.ctl.request_send(PEER_ID, paths)
    assert env.host.submits == []
    assert notice(env) == send.selection_error(paths)
    assert str(MAX_OFFER_FILES) in notice(env)


def test_request_send_at_exact_file_limit_submits(env):
    from teleport.core.messages import MAX_OFFER_FILES

    env.model.reset([dview()])
    paths = [env.tmp / f"f{i}.bin" for i in range(MAX_OFFER_FILES)]
    env.ctl.request_send(PEER_ID, paths)
    assert notice(env) is None
    assert env.host.sent() == [(PEER_ID, paths)]


def test_request_send_with_same_file_twice_shows_notice_and_does_not_submit(env):
    from teleport.ui import send

    env.model.reset([dview()])
    a = env.tmp / "nguon" / "a.bin"
    paths = [a, env.tmp / "nguon" / "." / "a.bin"]
    env.ctl.request_send(PEER_ID, paths)
    assert env.host.submits == []
    assert notice(env) == send.selection_error(paths)
    assert "hai lần" in notice(env)


def test_request_send_does_not_stat_files_on_qt_thread(env):
    """Như fixture `no_disk` của `test_send.py`: mọi lời hỏi đĩa về file người dùng đều bị ghi lại."""
    import pathlib

    env.model.reset([dview()])
    paths = files(env)
    wanted = {os.fspath(p) for p in paths}
    touched: list[str] = []

    def spy(real):
        def wrapper(path, *args, **kwargs):
            if os.fspath(path) in wanted:
                touched.append(f"{real.__name__}({os.fspath(path)})")
            return real(path, *args, **kwargs)

        return wrapper

    with pytest.MonkeyPatch.context() as m:
        for name in ("stat", "lstat"):
            m.setattr(os, name, spy(getattr(os, name)))
        for name in ("isdir", "isfile", "exists", "lexists", "getsize"):
            m.setattr(os.path, name, spy(getattr(os.path, name)))
        for name in ("is_dir", "is_file", "exists", "stat", "lstat"):
            m.setattr(pathlib.Path, name, spy(getattr(pathlib.Path, name)))
        env.ctl.request_send(PEER_ID, paths)
    assert touched == [], f"thread Qt không được chạm đĩa với file người dùng: {touched}"
    assert env.host.sent() == [(PEER_ID, paths)]


def test_request_send_to_paired_device_submits_transfers_send_with_device_and_paths(env):
    env.model.reset([dview()])
    paths = files(env)
    env.ctl.request_send(PEER_ID, paths)
    assert len(env.host.submits) == 1
    assert env.host.sent() == [(PEER_ID, paths)]
    assert env.host.calls == [], "gửi đi bằng submit (coroutine), không bằng call"


@pytest.mark.parametrize("result", ["rejected", "identity_mismatch", "version_mismatch"])
def test_blocked_device_shows_notice_and_creates_no_transfer(env, result):
    from teleport.app.node import ConnectFailed
    from teleport.core.links import ConnectResult
    from teleport.ui import send

    v = dview(connected=False)
    env.model.reset([v])
    env.model.apply(ConnectFailed(v, ConnectResult(result)))
    env.ctl.request_send(PEER_ID, files(env))
    assert env.host.submits == [], "thiết bị đang bị chặn: không tạo lượt (mục 10 A2)"
    expected = send.blocked_message(ConnectResult(result), label(PEER))
    assert expected is not None
    assert notice(env) == expected
    assert PEER in notice(env)


def _blocked(env, result: str) -> None:
    from teleport.app.node import ConnectFailed
    from teleport.core.links import ConnectResult

    v = dview(connected=False)
    env.model.reset([v])
    env.model.apply(ConnectFailed(v, ConnectResult(result)))
    env.ctl.request_send(PEER_ID, files(env))


def _notice_action_button(env, text: str):
    from PySide6.QtWidgets import QPushButton

    found = [
        b
        for b in env.ctl.view.findChildren(QPushButton)
        if b.text() == text and not b.isHidden() and b.isVisibleTo(env.ctl.view)
    ]
    assert len(found) == 1, f"dải thông báo cần đúng một nút “{text}”, thấy {len(found)}"
    return found[0]


def test_rejected_notice_has_repair_button_that_emits_repair_requested(env):
    """Mục 10 A2 / mvp mục 8 “Máy kia từ chối máy này”: nút “Ghép đôi lại”."""
    got: list = []
    env.ctl.repair_requested.connect(lambda v: got.append(v))
    _blocked(env, "rejected")
    assert env.ctl.view.notice_action_text() == REPAIR
    button = _notice_action_button(env, REPAIR)
    assert button.accessibleName() == REPAIR
    button.click()
    assert [v.device_id for v in got] == [PEER_ID]
    assert env.host.submits == []
    assert notice(env) is None, "bấm nút hành động thì dải thông báo ẩn"


def test_identity_mismatch_notice_has_unpair_button_that_emits_conversations_unpair_requested(env):
    """mvp mục 8 “Danh tính thiết bị thay đổi”: nút “Hủy ghép đôi” → `conversations.unpair_requested(id)`."""
    got: list = []
    env.conversations.unpair_requested.connect(lambda i: got.append(i))
    _blocked(env, "identity_mismatch")
    assert env.ctl.view.notice_action_text() == UNPAIR
    _notice_action_button(env, UNPAIR).click()
    assert got == [PEER_ID]
    assert env.host.submits == []


def test_version_mismatch_notice_has_no_action_button(env):
    _blocked(env, "version_mismatch")
    assert notice(env) is not None
    assert env.ctl.view.notice_action_text() is None


def test_new_notice_without_action_removes_old_action_button(env):
    got: list = []
    env.ctl.repair_requested.connect(lambda v: got.append(v))
    _blocked(env, "rejected")
    env.ctl.view.show_notice("Câu khác.")
    assert env.ctl.view.notice_action_text() is None
    env.ctl.view.notice_action.click()  # nút đã ẩn và không còn việc gì gắn vào
    assert got == []


def test_unreachable_disconnected_device_is_not_blocked_and_still_submits(env):
    """Mục 10 A2: chưa kết nối mà không bị chặn → vẫn gửi (hàng hiện “Đang chờ kết nối tới …”)."""
    from teleport.app.node import ConnectFailed
    from teleport.core.links import ConnectResult

    v = dview(connected=False, online=False)
    env.model.reset([v])
    env.model.apply(ConnectFailed(v, ConnectResult.UNREACHABLE))
    paths = files(env, 1)
    env.ctl.request_send(PEER_ID, paths)
    assert notice(env) is None
    assert env.host.sent() == [(PEER_ID, paths)]


# =================================================================================================
# on_done của submit
# =================================================================================================


def _submit_and_finish(env, error):
    env.model.reset([dview()])
    env.ctl.request_send(PEER_ID, files(env))
    [(_, on_done)] = env.host.submits
    assert on_done is not None, "submit phải có on_done để báo lỗi"
    on_done(error)


def test_on_done_source_error_shows_mvp_sentence(env):
    from teleport.app.sources import SourceError, SourceErrorKind
    from teleport.ui import send

    error = SourceError(env.tmp / "nguon" / "mat.bin", SourceErrorKind.NOT_FOUND)
    _submit_and_finish(env, error)
    assert notice(env) == send.send_error_message(error, label(PEER))
    assert notice(env).startswith("Không tìm thấy file")


def test_on_done_key_error_says_not_paired(env):
    from teleport.ui import send

    _submit_and_finish(env, KeyError(PEER_ID))
    assert notice(env) == send.send_error_message(KeyError(PEER_ID), label(PEER))
    assert notice(env).startswith(f"Chưa ghép đôi với {PEER}")


def test_on_done_runtime_error_is_silent(env):
    """Node đang dừng: `send_error_message` trả None → không thông báo."""
    _submit_and_finish(env, RuntimeError("node chưa chạy hoặc đang đóng"))
    assert notice(env) is None


def test_on_done_success_shows_nothing(env):
    _submit_and_finish(env, tkey("send"))
    assert notice(env) is None


# =================================================================================================
# Ghép rồi gửi (thiết bị chưa ghép đôi)
# =================================================================================================


def _pair_spy(env) -> list:
    got: list = []
    env.ctl.pair_needed.connect(lambda v: got.append(v))
    return got


def test_unpaired_device_emits_pair_needed_and_does_not_submit(env):
    v = dview(paired=False, connected=False)
    env.model.reset([v])
    got = _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    assert env.host.submits == []
    assert len(got) == 1
    assert got[0].device_id == PEER_ID
    assert notice(env) is None


def test_second_pair_then_send_while_one_pending_names_the_device_being_paired(env):
    env.model.reset(
        [dview(paired=False, connected=False), dview(OTHER_ID, OTHER, paired=False, connected=False)]
    )
    got = _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    env.ctl.request_send(OTHER_ID, files(env, 1))
    assert len(got) == 1, "chỉ một việc “ghép rồi gửi” cùng lúc"
    assert env.host.submits == []
    assert notice(env) == busy_sentence(label(PEER)), (
        "câu nêu tên máy đang chờ ghép đôi, không phải máy vừa chọn"
    )
    assert "chưa sẵn sàng ghép đôi" not in notice(env), "không dùng câu PEER_BUSY cho trường hợp này"


def test_pair_then_send_without_pairing_flow_connected_says_not_paired_and_keeps_no_pending(env):
    """Chưa ai nối `pair_needed` (trước PR2): không giữ việc chờ (sẽ kẹt), báo “Chưa ghép đôi…”."""
    env.model.reset([dview(paired=False, connected=False)])
    env.ctl.request_send(PEER_ID, files(env))
    assert env.ctl.pending is None
    assert env.host.submits == []
    assert notice(env) == not_paired_sentence(label(PEER))
    env.ctl.request_send(PEER_ID, files(env, 1))
    assert notice(env) == not_paired_sentence(label(PEER)), (
        "lần sau cũng vậy, không bị câu “đang chờ ghép đôi”"
    )


def test_pending_pair_job_is_dropped_silently_after_timeout(env, monkeypatch, qtbot):
    monkeypatch.setattr(env.mod, "PENDING_PAIR_TIMEOUT", 0.05)
    env.model.reset([dview(paired=False, connected=False)])
    got = _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    assert env.ctl.pending is not None
    qtbot.waitUntil(lambda: env.ctl.pending is None, timeout=2000)
    assert notice(env) is None, "bỏ việc chờ vì quá hạn thì im lặng (luồng ghép đôi tự báo lỗi)"
    env.ctl.on_pairing_finished(PEER_ID, True)
    assert env.host.submits == [], "việc chờ đã bỏ thì ghép xong muộn cũng không gửi"
    env.ctl.request_send(PEER_ID, files(env, 1))
    assert len(got) == 2, "hết hạn: yêu cầu mới lại xin ghép đôi, không bị câu “đang chờ”"


def test_pending_pair_timeout_default_covers_confirm_timeout():
    from teleport.core import pairing
    from teleport.ui import transfers

    longest_session = 2 * pairing.MESSAGE_TIMEOUT + pairing.CONFIRM_TIMEOUT + pairing.CONFIRM_GRACE
    assert longest_session < transfers.PENDING_PAIR_TIMEOUT


@pytest.mark.parametrize("how", ["attach", "close_all", "paired", "failed"])
def test_pending_timer_stops_when_pending_job_ends(env, monkeypatch, qtbot, how):
    """`attach`, `close_all`, `on_pairing_finished` dừng hẹn: hết hạn sau đó không đụng việc chờ mới."""
    monkeypatch.setattr(env.mod, "PENDING_PAIR_TIMEOUT", 0.2)
    env.model.reset([dview(paired=False, connected=False)])
    _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    timer = env.ctl._pending_timer
    assert timer.isActive()
    if how == "attach":
        env.ctl.attach(FakeHost(env.tmp / "nhan2"))
    elif how == "close_all":
        env.ctl.close_all()
    else:
        env.ctl.on_pairing_finished(PEER_ID, how == "paired")
    assert not timer.isActive()
    assert env.ctl.pending is None


def test_pairing_finished_for_pending_device_sends_its_paths(env):
    env.model.reset([dview(paired=False, connected=False)])
    _pair_spy(env)
    paths = files(env)
    env.ctl.request_send(PEER_ID, paths)
    env.ctl.on_pairing_finished(PEER_ID, True)
    assert env.host.sent() == [(PEER_ID, paths)]


def test_pairing_finished_for_other_device_does_not_send(env):
    env.model.reset([dview(paired=False, connected=False)])
    _pair_spy(env)
    paths = files(env)
    env.ctl.request_send(PEER_ID, paths)
    env.ctl.on_pairing_finished(OTHER_ID, True)
    env.ctl.on_pairing_finished(None, True)
    assert env.host.submits == [], "khớp theo peer_device_id (9.2)"
    env.ctl.on_pairing_finished(PEER_ID, True)
    assert env.host.sent() == [(PEER_ID, paths)], "việc chờ vẫn còn sau sự kiện của máy khác"


def test_pairing_failed_drops_pending_job(env):
    env.model.reset([dview(paired=False, connected=False)])
    got = _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    env.ctl.on_pairing_finished(PEER_ID, False)
    env.ctl.on_pairing_finished(PEER_ID, True)
    assert env.host.submits == [], "ghép đôi thất bại → bỏ việc chờ"
    env.ctl.request_send(PEER_ID, files(env, 1))
    assert len(got) == 2, "việc chờ đã bỏ: yêu cầu mới lại xin ghép đôi, không báo BUSY"
    assert notice(env) is None


def test_pending_job_is_sent_only_once(env):
    env.model.reset([dview(paired=False, connected=False)])
    _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    env.ctl.on_pairing_finished(PEER_ID, True)
    env.ctl.on_pairing_finished(PEER_ID, True)
    assert len(env.host.submits) == 1


def test_pair_then_send_key_error_says_not_paired(env):
    env.model.reset([dview(paired=False, connected=False)])
    _pair_spy(env)
    env.ctl.request_send(PEER_ID, files(env))
    env.ctl.on_pairing_finished(PEER_ID, True)
    [(_, on_done)] = env.host.submits
    on_done(KeyError(PEER_ID))
    assert notice(env).startswith(f"Chưa ghép đôi với {PEER}")


# =================================================================================================
# Host mới / host cũ
# =================================================================================================


def test_results_of_old_host_are_ignored_after_attach(env):
    env.model.reset([dview()])
    env.ctl.request_send(PEER_ID, files(env))
    [(_, old_done)] = env.host.submits
    new_host = FakeHost(env.tmp / "nhan2")
    env.ctl.attach(new_host)
    old_done(KeyError(PEER_ID))
    assert notice(env) is None, "kết quả của host cũ phải bị bỏ"


def test_attach_new_host_clears_rows_closes_offers_and_drops_pending_pair_job(env):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    env.ctl.on_transfer(tinfo_changed(tkey("send")))
    assert env.ctl.offers.keys() == [key]
    assert len(env.ctl.view.rows()) == 2
    env.model.reset([dview(OTHER_ID, OTHER, paired=False, connected=False)])
    _pair_spy(env)
    env.ctl.request_send(OTHER_ID, files(env))
    assert env.ctl.pending is not None

    new_host = FakeHost(env.tmp / "nhan2")
    env.ctl.attach(new_host)
    assert env.ctl.view.rows() == []
    assert env.ctl.offers.keys() == []
    env.ctl.on_pairing_finished(OTHER_ID, True)
    assert new_host.submits == [] and env.host.submits == [], "việc “ghép rồi gửi” của host cũ phải bỏ"


def test_on_started_of_old_host_is_ignored(env):
    new_host = FakeHost(env.tmp / "nhan2")
    env.ctl.attach(new_host)
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[tinfo(tkey("receive"))]))
    assert env.ctl.view.rows() == []


def test_attach_sets_receive_dir_for_offer_prompts(env):
    from PySide6.QtWidgets import QLabel

    from teleport.ui.send import printable

    new_host = FakeHost(env.tmp / "thu-muc-moi")
    env.ctl.attach(new_host)
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    box = env.ctl.offers.box(key)
    assert box is not None
    text = " ".join(w.text() for w in box.findChildren(QLabel))
    assert printable(str(new_host.options.receive_dir)) in text, "hộp hỏi phải hiện thư mục nhận của host mới"


def _offer_box_text(env, key) -> str:
    from PySide6.QtWidgets import QLabel

    box = env.ctl.offers.box(key)
    assert box is not None
    return " ".join(w.text() for w in box.findChildren(QLabel) if w.isVisibleTo(box))


def _record_tray(monkeypatch) -> list:
    """Bóng thoại khay kèm thư mục: [(chữ, folder)]."""
    from teleport.ui.tray import Tray

    got: list = []
    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: got.append((text, folder)))
    return got


def test_transfers_set_receive_dir_used_as_tray_folder_fallback(env, monkeypatch):
    """Spec-b1b 2.5: `set_receive_dir` thay `host.options.receive_dir` làm thư mục của bóng thoại
    “Đã nhận…” khi không có `FileDone.path`, và đặt thư mục cho hộp hỏi. Spec-f4 mục 2.5: thư mục đó
    nằm trong `shell.Reveal` (không file nào → `root` = `folder` = thư mục nhận)."""
    from teleport.ui.send import printable
    from teleport.ui.shell import Reveal

    shown = _record_tray(monkeypatch)
    new_dir = env.tmp / "doi-sang"
    env.ctl.set_receive_dir(new_dir)
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    assert printable(str(new_dir)) in _offer_box_text(env, key)
    env.ctl.on_transfer(finished(key))
    done = [f for t, f in shown if t == RECEIVED_ONE.format(name="video.mp4", peer=PEER)]
    assert len(done) == 1, shown
    assert isinstance(done[0], Reveal)
    assert (tuple(done[0].files), done[0].root, done[0].folder) == ((), new_dir, new_dir)


def test_attach_with_saved_choice_has_no_receive_dir_until_set(env, monkeypatch):
    from teleport.app.node import ReceiveDirChoice
    from teleport.ui.send import printable

    shown = _record_tray(monkeypatch)
    host = FakeHost(env.tmp / "nhan-x")
    host.options = dataclasses.replace(host.options, receive_dir=ReceiveDirChoice.SAVED)
    env.ctl.attach(host)
    env.ctl.on_started(host)
    host.run_calls(FakeNode(devices=[dview()], infos=[]))
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    text = _offer_box_text(env, key)
    assert "Lưu vào" not in text, f"SAVED chưa biết thư mục: không hiện dòng “Lưu vào” ({text!r})"
    assert "saved" not in text.lower()
    env.ctl.on_transfer(finished(key))
    done = [f for t, f in shown if t == RECEIVED_ONE.format(name="video.mp4", peer=PEER)]
    assert done == [None], shown

    later = env.tmp / "da-biet"
    env.ctl.set_receive_dir(later)
    key2 = tkey("receive")
    env.ctl.on_transfer(offer(key2))
    assert printable(str(later)) in _offer_box_text(env, key2)


def tinfo_changed(key, status: str = "waiting"):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(tinfo(key, status=status))


# =================================================================================================
# on_started, on_node_event
# =================================================================================================


def test_on_started_loads_snapshot_with_device_names(env):
    key = tkey("send", transfer_id="c" * 32)
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[tinfo(key, status="transferring", done=500)]))
    rows = env.ctl.view.rows()
    assert [r.key for r in rows] == [key]
    # Spec B3 9.8 (i): tên máy rời tiêu đề, còn ở accessibleName “Gửi tới X”.
    assert f"Gửi tới {PEER}" in rows[0].accessibleName()


def test_snapshot_merges_with_transfer_resumed_that_came_first(env):
    """9.7: `TransferResumed` có thể tới trước `started`; ảnh chụp không nhân đôi thẻ."""
    from teleport.app.transfers import TransferResumed

    key = tkey("receive", transfer_id="d" * 32)
    env.ctl.on_transfer(TransferResumed(tinfo(key, status="reconnecting", done=300)))
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[tinfo(key, status="reconnecting", done=300)]))
    assert [r.key for r in env.ctl.view.rows()] == [key]


def test_on_started_marks_disconnected_device_on_waiting_send_row(env):
    key = tkey("send")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview(connected=False)], infos=[tinfo(key, status="waiting")]))
    [row] = env.ctl.view.rows()
    assert row.detail_label.text() == WAIT_OFFLINE_SEND.format(p=PEER)


def test_node_events_update_connected_state_of_rows(env):
    from teleport.app.node import DeviceConnected, DeviceDisconnected

    key = tkey("send")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    env.ctl.on_transfer(tinfo_changed(key, "waiting"))
    [row] = env.ctl.view.rows()
    env.ctl.on_node_event(DeviceDisconnected(dview(connected=False)))
    assert row.detail_label.text() == WAIT_OFFLINE_SEND.format(p=PEER)
    env.ctl.on_node_event(DeviceConnected(dview(connected=True), outgoing=True))
    assert row.detail_label.text() != WAIT_OFFLINE_SEND.format(p=PEER)


def test_device_online_with_new_name_renames_rows(env):
    from teleport.app.node import DeviceOnline

    key = tkey("send")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    env.ctl.on_transfer(tinfo_changed(key, "waiting"))
    [row] = env.ctl.view.rows()
    # Spec B3 9.8 (i): tên máy ở accessibleName (“Gửi tới X”), không ở tiêu đề.
    assert f"Gửi tới {PEER}" in row.accessibleName()
    env.ctl.on_node_event(DeviceOnline(dview(name="PC-Moi")))
    assert "Gửi tới PC-Moi" in row.accessibleName()


# =================================================================================================
# on_transfer: hộp hỏi, bóng thoại khay
# =================================================================================================


def test_offer_not_auto_accepted_opens_prompt_adds_row_and_tray_message(env):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    assert env.ctl.offers.keys() == [key]
    assert [r.key for r in env.ctl.view.rows()] == [key]
    assert OFFER_WAITING in env.messages


def test_auto_accepted_offer_has_no_prompt_and_no_waiting_message(env):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key, auto=True))
    assert env.ctl.offers.keys() == []
    assert OFFER_WAITING not in env.messages


def test_receive_done_one_file_shows_received_name_in_tray(env):
    key = tkey("receive")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    env.ctl.on_transfer(offer(key, names=("video.mp4",)))
    env.ctl.on_transfer(finished(key, names=("video.mp4",)))
    assert RECEIVED_ONE.format(name="video.mp4", peer=PEER) in env.messages, env.messages
    assert env.ctl.offers.keys() == [], "lượt kết thúc thì hộp hỏi đóng"


def test_receive_done_one_file_uses_saved_name_from_file_done(env):
    """File thật có thể đã thành `video (1).mp4` (không ghi đè): bóng thoại dùng `FileDone.path.name` cuối."""
    from teleport.app.transfers import FileDone

    key = tkey("receive")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    env.ctl.on_transfer(offer(key, names=("video.mp4",)))
    saved = env.tmp / "nhan" / "video (1).mp4"
    env.ctl.on_transfer(FileDone(key=key, file_index=0, name="video.mp4", path=saved))
    env.ctl.on_transfer(finished(key, names=("video.mp4",)))
    assert RECEIVED_ONE.format(name="video (1).mp4", peer=PEER) in env.messages, env.messages
    assert RECEIVED_ONE.format(name="video.mp4", peer=PEER) not in env.messages


def test_saved_name_of_one_transfer_does_not_leak_into_next(env):
    from teleport.app.transfers import FileDone

    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    first, second = tkey("receive"), tkey("receive")
    env.ctl.on_transfer(FileDone(key=first, file_index=0, name="a.txt", path=env.tmp / "a (1).txt"))
    env.ctl.on_transfer(finished(first, "cancelled_user", names=("a.txt",)))
    env.ctl.on_transfer(finished(second, names=("b.txt",)))
    assert RECEIVED_ONE.format(name="b.txt", peer=PEER) in env.messages, env.messages


def test_receive_done_many_files_shows_count_in_tray(env):
    key = tkey("receive")
    names = ("a.txt", "b.txt", "c.txt")
    env.ctl.on_started(env.host)
    env.host.run_calls(FakeNode(devices=[dview()], infos=[]))
    env.ctl.on_transfer(offer(key, names=names))
    env.ctl.on_transfer(finished(key, names=names))
    assert RECEIVED_MANY.format(n=3, peer=PEER) in env.messages, env.messages


@pytest.mark.parametrize(
    ("direction", "result"), [("send", "done"), ("receive", "cancelled_user"), ("receive", "suspended")]
)
def test_no_received_message_unless_receive_done(env, direction, result):
    key = tkey(direction)
    env.ctl.on_transfer(tinfo_changed(key, "transferring"))
    env.ctl.on_transfer(finished(key, result))
    assert not [m for m in env.messages if m.startswith("Đã nhận")], env.messages


# =================================================================================================
# Hủy, trả lời, chọn file
# =================================================================================================


def test_cancel_button_calls_transfers_cancel_with_key(env):
    key = tkey("send")
    env.ctl.on_transfer(tinfo_changed(key, "transferring"))
    [row] = env.ctl.view.rows()
    row.cancel_button.click()
    node = FakeNode()
    env.host.run_calls(node)
    assert node.transfers.cancelled == [key]


def test_cancel_method_calls_transfers_cancel(env):
    key = tkey("receive")
    env.ctl.cancel(key)
    node = FakeNode()
    env.host.run_calls(node)
    assert node.transfers.cancelled == [key]


@pytest.mark.parametrize("accept", [True, False])
def test_offer_decision_calls_transfers_decide(env, accept):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    env.ctl.offers.decided.emit(key, accept)
    node = FakeNode()
    env.host.run_calls(node)
    assert node.transfers.decided == [(key, accept)]


def test_decide_method_calls_transfers_decide(env):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))  # spec-b4 3.3/11.15: `decide` nay đi qua book, cần offer trước
    env.ctl.decide(key, True)
    node = FakeNode()
    env.host.run_calls(node)
    assert node.transfers.decided == [(key, True)]


def test_conversations_send_files_requested_goes_to_request_send(env):
    env.model.reset([dview()])
    paths = files(env)
    env.conversations.send_files_requested.emit(PEER_ID, paths)
    assert env.host.sent() == [(PEER_ID, paths)]


class _Dialogs:
    """Seam `file_dialog_factory`: trả một `QFileDialog` con ghi lại `open()` / `exec()`."""

    def __init__(self) -> None:
        self.made: list = []
        self.factory_args: list = []

    def factory(self, *args, **kwargs):
        from PySide6.QtWidgets import QFileDialog

        made = self.made

        class FakeDialog(QFileDialog):
            def __init__(self) -> None:
                super().__init__()
                self.open_calls = 0
                self.exec_calls = 0
                made.append(self)

            def open(self, *a, **k):
                self.open_calls += 1

            def exec(self, *a, **k):
                self.exec_calls += 1
                return 0

            def exec_(self, *a, **k):
                self.exec_calls += 1
                return 0

        self.factory_args.append((args, kwargs))
        return FakeDialog()


@pytest.fixture
def dialogs(env, monkeypatch):
    d = _Dialogs()
    monkeypatch.setattr(env.mod, "file_dialog_factory", d.factory)
    return d


def test_pick_and_send_opens_file_dialog_with_open_not_exec(env, dialogs):
    from PySide6.QtWidgets import QFileDialog

    env.model.reset([dview()])
    env.ctl.pick_and_send(PEER_ID)
    assert len(dialogs.made) == 1, "pick_and_send phải lấy hộp chọn file qua seam file_dialog_factory"
    dlg = dialogs.made[0]
    assert dlg.open_calls == 1
    assert dlg.exec_calls == 0, "không exec() (chặn vòng sự kiện)"
    assert dlg.fileMode() == QFileDialog.FileMode.ExistingFiles
    assert dlg.parent() in (None, env.window)


def test_files_selected_in_dialog_are_sent_to_device(env, dialogs):
    env.model.reset([dview()])
    env.ctl.pick_and_send(PEER_ID)
    paths = files(env)
    dialogs.made[0].filesSelected.emit([str(p) for p in paths])
    assert env.host.sent() == [(PEER_ID, paths)]


def test_conversations_pick_files_requested_opens_dialog_for_that_device(env, dialogs):
    env.model.reset([dview()])
    env.conversations.pick_files_requested.emit(PEER_ID)
    assert len(dialogs.made) == 1
    paths = files(env, 1)
    dialogs.made[0].filesSelected.emit([str(paths[0])])
    assert env.host.sent() == [(PEER_ID, paths)]


def test_drop_on_empty_conversations_space_shows_hint(env, ui_helpers):
    from PySide6.QtCore import QUrl

    env.model.reset([dview()])
    env.conversations.drop_files(None, [QUrl.fromLocalFile(str(p)) for p in files(env)])
    shown = (notice(env) or "") + "\n" + ui_helpers.all_text(env.window)
    assert DROP_HINT in shown
    assert env.host.submits == []


# =================================================================================================
# Thoát
# =================================================================================================


def test_close_all_closes_prompts_and_drops_pending_pair_job(env):
    key = tkey("receive")
    env.ctl.on_transfer(offer(key))
    env.model.reset([dview(OTHER_ID, OTHER, paired=False, connected=False)])
    _pair_spy(env)
    env.ctl.request_send(OTHER_ID, files(env))
    assert env.ctl.pending is not None
    env.ctl.close_all()
    assert env.ctl.offers.keys() == []
    env.ctl.on_pairing_finished(OTHER_ID, True)
    assert env.host.submits == []


# =================================================================================================
# Lượt mới bị chặn ngay lần nối đầu (docstring `ui/transfers.py`, bước 3 của “Gửi”)
# =================================================================================================

BLOCKING = ["rejected", "identity_mismatch", "version_mismatch"]


def _new_send(env, *, device_id: str = PEER_ID):
    """Một lượt gửi, thẻ dựng qua `on_transfer`; radar lúc đó báo thế nào là do test đặt trước."""
    key = tkey("send", device_id)
    env.ctl.on_transfer(tinfo_changed(key, "waiting"))
    assert env.ctl.view.row(key) is not None
    return key


def _radar(env, *views) -> None:
    env.model.reset(list(views) or [dview(connected=False)])


def _connect_failed(env, result: str, view=None) -> None:
    from teleport.app.node import ConnectFailed
    from teleport.core.links import ConnectResult

    env.ctl.on_node_event(ConnectFailed(view or dview(connected=False), ConnectResult(result)))


def _cancelled(env) -> list:
    """Các khóa controller đã xin hủy qua host (chạy mọi `call` đang chờ trên node giả)."""
    node = FakeNode()
    env.host.run_calls(node)
    return node.transfers.cancelled


def _progress(key):
    from teleport.app.transfers import TransferProgress

    return TransferProgress(
        tinfo(key, status="transferring", done=100),
        bytes_per_second=0.0,
        eta=None,
        shown_bytes=100,
        idle_seconds=0.0,
    )


@pytest.mark.parametrize("result", BLOCKING)
def test_blocked_connect_failed_removes_new_send_row_cancels_it_and_shows_notice(env, result):
    from teleport.core.links import ConnectResult
    from teleport.ui import send

    _radar(env)
    key = _new_send(env)
    _connect_failed(env, result)
    assert env.ctl.view.row(key) is None, "lượt mới bị chặn: gỡ thẻ"
    assert _cancelled(env) == [key], "lượt mới bị chặn: hủy qua host (node.transfers.cancel)"
    expected = send.blocked_message(ConnectResult(result), label(PEER))
    assert expected is not None
    assert notice(env) == expected


@pytest.mark.parametrize(("result", "action"), [("rejected", REPAIR), ("identity_mismatch", UNPAIR)])
def test_blocked_new_send_notice_has_action_button(env, result, action):
    _radar(env)
    _new_send(env)
    _connect_failed(env, result)
    assert env.ctl.view.notice_action_text() == action


def test_blocked_new_send_version_mismatch_notice_has_no_action(env):
    _radar(env)
    _new_send(env)
    _connect_failed(env, "version_mismatch")
    assert notice(env) is not None
    assert env.ctl.view.notice_action_text() is None


def test_blocked_new_send_repair_button_emits_repair_requested(env):
    got: list = []
    env.ctl.repair_requested.connect(lambda v: got.append(v))
    _radar(env)
    _new_send(env)
    _connect_failed(env, "rejected")
    _notice_action_button(env, REPAIR).click()
    assert [v.device_id for v in got] == [PEER_ID]


def test_blocked_new_send_unpair_button_emits_conversations_unpair_requested(env):
    got: list = []
    env.conversations.unpair_requested.connect(lambda i: got.append(i))
    _radar(env)
    _new_send(env)
    _connect_failed(env, "identity_mismatch")
    _notice_action_button(env, UNPAIR).click()
    assert got == [PEER_ID]


def test_new_send_to_device_missing_from_radar_counts_as_new(env):
    """Radar chưa biết máy (`device(id)` None) cũng là “chưa kết nối”."""
    env.model.reset([])
    key = _new_send(env)
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(key) is None
    assert _cancelled(env) == [key]


def test_all_new_sends_to_blocked_device_are_removed_and_cancelled(env):
    _radar(env)
    a, b = _new_send(env), _new_send(env)
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(a) is None and env.ctl.view.row(b) is None
    assert sorted(_cancelled(env), key=str) == sorted([a, b], key=str)


@pytest.mark.parametrize("late", ["progress", "status", "finished"])
def test_late_event_of_removed_send_does_not_rebuild_row(env, late):
    _radar(env)
    key = _new_send(env)
    _connect_failed(env, "rejected")
    if late == "progress":
        env.ctl.on_transfer(_progress(key))
    elif late == "status":
        env.ctl.on_transfer(tinfo_changed(key, "reconnecting"))
    else:
        env.ctl.on_transfer(finished(key, "cancelled_user"))
    assert env.ctl.view.row(key) is None, f"sự kiện tới sau ({late}) không dựng lại thẻ đã gỡ"


def test_progress_then_cancel_finished_of_removed_send_do_not_rebuild_row(env):
    _radar(env)
    key = _new_send(env)
    _connect_failed(env, "rejected")
    env.ctl.on_transfer(_progress(key))
    env.ctl.on_transfer(tinfo_changed(key, "reconnecting"))
    env.ctl.on_transfer(finished(key, "cancelled_user"))
    assert env.ctl.view.row(key) is None
    assert env.ctl.view.rows() == []


def test_active_sends_does_not_list_removed_send(env):
    _radar(env)
    _new_send(env)
    assert env.ctl.active_sends() == [label(PEER)]
    _connect_failed(env, "rejected")
    assert env.ctl.active_sends() == []


def test_unreachable_does_not_remove_new_send(env):
    _radar(env, dview(connected=False, online=False))
    key = _new_send(env)
    _connect_failed(env, "unreachable", dview(connected=False, online=False))
    assert env.ctl.view.row(key) is not None
    assert _cancelled(env) == []
    assert notice(env) is None


def test_unreachable_then_blocked_still_removes_new_send(env):
    """UNREACHABLE không làm lượt hết “mới”: lần nối sau bị chặn vẫn gỡ."""
    _radar(env)
    key = _new_send(env)
    _connect_failed(env, "unreachable")
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(key) is None
    assert _cancelled(env) == [key]


@pytest.mark.parametrize("result", BLOCKING)
def test_send_created_while_connected_is_kept_when_blocked_later(env, result):
    """Lượt dở (offer đã đi): bị chặn sau đó vẫn giữ thẻ, không hủy, không thông báo của bước 3."""
    from teleport.app.node import DeviceDisconnected

    _radar(env, dview(connected=True))
    key = _new_send(env)
    env.ctl.on_node_event(DeviceDisconnected(dview(connected=False)))
    _radar(env, dview(connected=False))
    _connect_failed(env, result)
    assert env.ctl.view.row(key) is not None
    assert _cancelled(env) == []
    assert notice(env) is None


@pytest.mark.parametrize("result", BLOCKING)
def test_new_send_after_device_connected_is_kept_when_blocked_later(env, result):
    from teleport.app.node import DeviceConnected, DeviceDisconnected

    _radar(env)
    key = _new_send(env)
    env.ctl.on_node_event(DeviceConnected(dview(connected=True), outgoing=True))
    env.ctl.on_node_event(DeviceDisconnected(dview(connected=False)))
    _connect_failed(env, result)
    assert env.ctl.view.row(key) is not None
    assert _cancelled(env) == []
    assert notice(env) is None


def test_device_connected_of_other_device_keeps_send_new(env):
    from teleport.app.node import DeviceConnected

    _radar(env, dview(connected=False), dview(OTHER_ID, OTHER, connected=False))
    key = _new_send(env)
    env.ctl.on_node_event(DeviceConnected(dview(OTHER_ID, OTHER, connected=True), outgoing=True))
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(key) is None
    assert _cancelled(env) == [key]


def test_connect_failed_of_other_device_does_not_remove_send(env):
    _radar(env, dview(connected=False), dview(OTHER_ID, OTHER, connected=False))
    key = _new_send(env)
    _connect_failed(env, "rejected", dview(OTHER_ID, OTHER, connected=False))
    assert env.ctl.view.row(key) is not None
    assert _cancelled(env) == []
    assert notice(env) is None


def test_blocked_only_removes_sends_of_that_device(env):
    _radar(env, dview(connected=False), dview(OTHER_ID, OTHER, connected=False))
    mine = _new_send(env)
    other = _new_send(env, device_id=OTHER_ID)
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(mine) is None
    assert env.ctl.view.row(other) is not None
    assert _cancelled(env) == [mine]


def test_blocked_keeps_old_send_but_removes_new_one_to_same_device(env):
    from teleport.app.node import DeviceDisconnected

    _radar(env, dview(connected=True))
    old = _new_send(env)
    env.ctl.on_node_event(DeviceDisconnected(dview(connected=False)))
    _radar(env, dview(connected=False))
    new = _new_send(env)
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(old) is not None, "lượt dở giữ nguyên"
    assert env.ctl.view.row(new) is None
    assert _cancelled(env) == [new]
    assert notice(env) is not None


@pytest.mark.parametrize("result", BLOCKING)
def test_blocked_without_new_send_shows_no_notice(env, result):
    """Không có lượt mới: hành vi cũ (chỉ radar), controller không hiện dải thông báo, không hủy."""
    _radar(env)
    _connect_failed(env, result)
    assert notice(env) is None
    assert _cancelled(env) == []


def test_receive_row_is_not_a_new_send(env):
    _radar(env)
    key = tkey("receive")
    env.ctl.on_transfer(offer(key, auto=True))
    _connect_failed(env, "rejected")
    assert env.ctl.view.row(key) is not None
    assert _cancelled(env) == []
    assert notice(env) is None


def test_send_finished_before_connect_failed_is_not_cancelled(env):
    _radar(env)
    key = _new_send(env)
    env.ctl.on_transfer(finished(key, "cancelled_user"))
    _connect_failed(env, "rejected")
    assert _cancelled(env) == []
    assert notice(env) is None


def test_send_first_seen_as_finished_is_not_a_new_send(env):
    _radar(env)
    key = tkey("send")
    env.ctl.on_transfer(finished(key, "cancelled_user"))
    _connect_failed(env, "rejected")
    assert _cancelled(env) == []
    assert notice(env) is None


def test_second_blocked_connect_failed_does_not_cancel_again(env):
    _radar(env)
    key = _new_send(env)
    _connect_failed(env, "rejected")
    assert _cancelled(env) == [key]
    env.ctl.view.hide_notice()
    _connect_failed(env, "rejected")
    assert _cancelled(env) == []
    assert notice(env) is None


def test_new_send_of_old_host_is_forgotten_after_attach(env):
    """`attach` host mới xóa sạch: lượt mới của host cũ không bị hủy, không thông báo."""
    _radar(env)
    _new_send(env)
    new_host = FakeHost(env.tmp / "nhan2")
    env.ctl.attach(new_host)
    _connect_failed(env, "rejected")
    node = FakeNode()
    new_host.run_calls(node)
    assert node.transfers.cancelled == []
    assert notice(env) is None


# =================================================================================================
# V2 (spec B1 mục 2.5, 6 V2): controller báo tóm tắt danh sách lượt cho cửa sổ
# =================================================================================================

READY = "Sẵn sàng nhận"
BUSY_ONE = "Đang truyền 1 lượt"


def test_v2_summary_set_right_after_construction(env):
    from teleport.ui.widgets import BadgeTone

    assert env.window.badge.text == READY
    assert env.window.badge.tone is BadgeTone.SUCCESS


def test_v2_badge_follows_transfer_updates(env):
    from teleport.ui.widgets import BadgeTone

    env.window.show_running("May-A", env.tmp / "nhan")
    # Spec B3 9.15: `has_content()` = thông báo hay đang chọn một máy; cần một máy đã ghép đôi (tự được
    # chọn, mục 6) để khung phải là `transfers_area` thay vì “Ghép đôi máy đầu tiên”.
    env.model.reset([dview()])
    key = tkey("send")
    env.ctl.on_transfer(tinfo_changed(key, "transferring"))
    assert env.window.badge.text == BUSY_ONE
    assert env.window.badge.tone is BadgeTone.BUSY
    assert env.window.stream_pane.currentWidget() is env.window.transfers_area
    env.ctl.on_transfer(finished(key, "done"))
    assert env.window.badge.text == READY
    assert env.window.badge.tone is BadgeTone.SUCCESS
    assert env.window.stream_pane.currentWidget() is env.window.transfers_area  # thẻ đã xong vẫn hiện


def test_v2_attach_none_resets_badge_and_stream_pane(env):
    env.window.show_running("May-A", env.tmp / "nhan")
    env.ctl.on_transfer(tinfo_changed(tkey("send"), "transferring"))
    assert env.window.badge.text == BUSY_ONE
    env.ctl.attach(None)
    assert env.window.badge.text == READY
    # Luật L7: RUNNING, radar không có máy đã ghép đôi, danh sách rỗng → EmptyState.
    assert env.window.stream_pane.currentWidget() is env.window.empty_state
    env.model.reset([dview(paired=True)])
    assert env.window.stream_pane.currentWidget() is env.window.transfers_area


def test_v2_notice_alone_shows_transfers_area(env):
    env.window.show_running("May-A", env.tmp / "nhan")
    assert env.window.stream_pane.currentWidget() is env.window.empty_state
    env.ctl.view.show_notice("Thả file lên một thiết bị để gửi.")
    assert env.window.stream_pane.currentWidget() is env.window.transfers_area
    assert env.window.badge.text == READY
    env.ctl.view.hide_notice()
    assert env.window.stream_pane.currentWidget() is env.window.empty_state
