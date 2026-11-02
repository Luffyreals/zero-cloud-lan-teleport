"""Theo dõi tiến độ khi chạy nền: nối dây (spec-f4 mục 2.3–2.7; mục 8 S1–S20 thắng khi khác). Tiêu chí
R3, R4, R9–R14 và phần thêm của S18.

Viết từ spec, không từ code. `MainWindow`, `Tray`, `ChatView`, `TransfersController` thật (offscreen),
`NodeHost` giả (chỉ đọc `options.receive_dir`, ghi `call`/`submit`). Sự kiện giả dựng bằng dataclass thật
của `teleport.app.transfers`.

Seam: `ui.transfers._monotonic` (đồng hồ của tiêu đề, fixture `clock`), `ui.transfers.default_window_active`
(“cửa sổ chính active”), `ui.progress.TITLE_MIN_INTERVAL`, `ui.notify.NOTIFY_QUIET`/`NOTIFY_MAX_WAIT`
(đọc lúc dùng), `ui.shell.show_in_folder` (bấm nút/bóng thoại), `ui.shell._select_native` (fixture
autouse `fake_select_native`), `ui.chat.open_url`, `ui.app.open_url`.

Mặc định fixture autouse `notify_immediate` đặt hằng gộp về 0 (flush đồng bộ); test gộp thật gắn
`real_notify_delay`, dùng đồng hồ giả và phát `timeout` của `_notify_timer` thay vì chờ giờ thật (chỉ
`test_two_receives_one_message_in_real_time` chờ QTimer thật, biên rộng).
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

A_ID = "a71c04d2" + "e" * 24
B_ID = "0f0f0f0f" + "1" * 24
A_NAME = "PC-Nha"
B_NAME = "Laptop-Minh"
APP = "ZCL Teleport"
SHOW_IN_FOLDER = "Hiện trong thư mục"
SHOW_IN_FOLDER_EN = "Show in folder"
OFFER_WAITING = "Có file đang chờ bạn nhận."
OPEN_FAILED = "Không mở được thư mục {path}. Thư mục có thể đã bị xóa, đổi tên hay nằm trên ổ đã rút ra."
real_notify_delay = pytest.mark.real_notify_delay


# =================================================================================================
# Dữ liệu giả (định nghĩa tại chỗ: không import conftest)
# =================================================================================================


def settle(qtbot=None, ms: int = 0) -> None:
    for _ in range(3):
        QApplication.processEvents()
    if qtbot is not None and ms:
        qtbot.wait(ms)


def plain(text: str) -> str:
    return text.replace("&&", "\0").replace("&", "").replace("\0", "&")


def tkey(direction: str = "receive", device_id: str = A_ID):
    from teleport.core.transfer import Direction, TransferKey

    return TransferKey(device_id, Direction(direction), uuid.uuid4().hex)


def dview(device_id: str = A_ID, name: str = A_NAME):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id=device_id,
        name=name,
        os="windows",
        paired=True,
        online=True,
        connected=True,
        addresses=("192.0.2.7",),
        port=47474,
    )


def tinfo(key, status: str = "transferring", *, names=("video.mp4",), size: int = 1000, done: int = 0):
    from teleport.core.messages import FileEntry
    from teleport.core.transfer import TransferInfo, TransferStatus

    return TransferInfo(
        key=key,
        status=TransferStatus(status),
        files=tuple(FileEntry(n, size, 0) for n in names),
        names=tuple(names),
        file_index=0,
        done_bytes=done,
        total_bytes=size * len(names),
    )


def status(key, st: str = "transferring", **kw):
    from teleport.app.transfers import TransferStatusChanged

    return TransferStatusChanged(tinfo(key, st, **kw))


def progress(key, shown: int, *, size: int = 1000, names=("video.mp4",)):
    from teleport.app.transfers import TransferProgress

    return TransferProgress(
        tinfo(key, "transferring", names=names, size=size, done=shown),
        bytes_per_second=1000.0,
        eta=1.0,
        shown_bytes=shown,
        idle_seconds=0.0,
    )


def offer(key, *, names=("video.mp4",), auto: bool = True):
    from teleport.app.transfers import OfferReceived
    from teleport.core.messages import FileEntry

    name = A_NAME if key.device_id == A_ID else B_NAME
    return OfferReceived(
        key=key,
        device_name=name,
        files=tuple(FileEntry(n, 1000, 0) for n in names),
        names=tuple(names),
        total_bytes=1000 * len(names),
        auto_accepted=auto,
    )


def file_done(key, path: Path | None, index: int = 0, name: str = "video.mp4"):
    from teleport.app.transfers import FileDone

    return FileDone(key=key, file_index=index, name=name, path=path)


def finished(key, result: str = "done", *, names=("video.mp4",)):
    from teleport.app.transfers import TransferFinished, TransferResult

    return TransferFinished(
        info=tinfo(key, "verifying", names=names, done=1000 * len(names)),
        result=TransferResult(result),
        by_peer=False,
        reason=None,
        file_index=None,
        reject=None,
    )


class FakeHost:
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


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# =================================================================================================
# Fixture
# =================================================================================================


@pytest.fixture
def env(qtbot, monkeypatch, tmp_path):
    """Cửa sổ chính RUNNING, hiện, trang HOME, đang mở luồng của A (rỗng nên ở cuối), “active” theo
    `flags.window_active`; mọi bóng thoại khay ghi vào `shown` dạng (chữ, folder)."""
    from teleport.ui import transfers as mod
    from teleport.ui.main_window import MainWindow
    from teleport.ui.tray import Tray

    shown: list[tuple[str, object]] = []
    monkeypatch.setattr(Tray, "show_message", lambda self, text, folder=None: shown.append((text, folder)))
    flags = SimpleNamespace(window_active=True, app_active=True)
    monkeypatch.setattr(mod, "default_window_active", lambda: flags.window_active)
    window = MainWindow()
    qtbot.addWidget(window)
    tray = Tray()
    ctl = mod.TransfersController(window, tray, parent=None, app_active=lambda: flags.app_active)
    receive_dir = tmp_path / "nhan"
    host = FakeHost(receive_dir)
    ctl.attach(host)
    window.show_running("May-A", receive_dir)
    window.devices.reset([dview(A_ID, A_NAME), dview(B_ID, B_NAME)])
    window.resize(980, 660)
    window.show()
    qtbot.waitExposed(window)
    window.conversations.select_device(A_ID)
    settle(qtbot, 20)
    ns = SimpleNamespace(
        mod=mod,
        window=window,
        tray=tray,
        ctl=ctl,
        host=host,
        flags=flags,
        shown=shown,
        receive_dir=receive_dir,
        tmp=tmp_path,
    )
    assert ctl.view.device_id() == A_ID, "tiền đề: luồng A đang mở"
    yield ns
    ctl.close_all()
    tray.dispose()
    settle()


@pytest.fixture
def clock(monkeypatch):
    from teleport.ui import transfers as mod

    c = Clock()
    monkeypatch.setattr(mod, "_monotonic", c)
    return c


def push(env, update, clock: Clock | None = None, dt: float = 6.0) -> None:
    """Đưa `update` vào controller; có `clock` thì đồng hồ tiến `dt` giây trước (mặc định quá nhịp)."""
    if clock is not None:
        clock.advance(dt)
    env.ctl.on_transfer(update)
    settle()


def receive(env, key, paths: list[Path], *, names=None) -> None:
    """Một lượt nhận tự nhận, đủ `FileDone` rồi `TransferFinished` DONE."""
    names = tuple(names or [p.name for p in paths] or ["video.mp4"])
    push(env, offer(key, names=names))
    push(env, status(key, "transferring", names=names))
    for i, p in enumerate(paths):
        push(env, file_done(key, p, i, names[i]))
    push(env, finished(key, "done", names=names))


def received(env) -> list[tuple[str, object]]:
    return [(t, f) for t, f in env.shown if str(t).startswith("Đã nhận")]


def title(env) -> str:
    return env.window.windowTitle()


# =================================================================================================
# R3: tiêu đề cửa sổ
# =================================================================================================


def test_window_title_text_function():
    from teleport.ui import texts

    assert texts.window_title(None) == texts.APP_NAME == APP
    assert texts.window_title(40) == f"40% · {APP}"
    assert texts.window_title(0) == f"0% · {APP}"
    assert texts.window_title(150) == f"100% · {APP}"
    assert texts.window_title(-3) == f"0% · {APP}"


def test_title_shows_percent_of_receiving_transfer(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    assert title(env) == f"40% · {APP}"


def test_title_back_to_app_name_when_transfer_finishes(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    push(env, finished(k, "done"), clock, dt=0.1)
    assert title(env) == APP, "kết thúc áp ngay, không chờ nhịp"


def test_title_back_to_app_name_when_transfer_fails(env, clock):
    k = tkey("send")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    push(env, finished(k, "cancelled_user"), clock, dt=0.1)
    assert title(env) == APP


def test_title_merges_send_and_receive_by_bytes(env, clock):
    s, r = tkey("send", B_ID), tkey("receive")
    push(env, status(s, "transferring"), clock)
    push(env, status(r, "transferring", size=3000), clock)
    push(env, progress(s, 1000), clock)
    push(env, progress(r, 1000, size=3000), clock)
    assert title(env) == f"50% · {APP}", "(1000 + 1000) / (1000 + 3000)"


def test_title_rounds_down_to_step_and_never_100(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 629), clock)
    assert title(env) == f"60% · {APP}"
    push(env, progress(k, 1000), clock)
    assert title(env) == f"95% · {APP}"


def test_title_change_within_interval_is_held(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    push(env, progress(k, 800), clock, dt=1.0)
    assert title(env) == f"40% · {APP}", "đổi trong TITLE_MIN_INTERVAL bị giữ"


def test_held_title_applied_by_timer(env, clock, qtbot, monkeypatch):
    from teleport.ui import progress as prog

    monkeypatch.setattr(prog, "TITLE_MIN_INTERVAL", 0.3)
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    push(env, progress(k, 800), clock, dt=0.1)
    assert title(env) == f"40% · {APP}"
    clock.advance(1.0)  # hẹn giờ thật (~0,2 s) chạy khi đồng hồ giả đã quá nhịp
    qtbot.waitUntil(lambda: title(env) == f"80% · {APP}", timeout=3000)
    assert env.tray.state.progress == 80


def test_waiting_and_queued_receive_do_not_set_title(env, clock):
    push(env, status(tkey("receive"), "waiting"), clock)
    push(env, status(tkey("receive", B_ID), "queued"), clock)
    assert title(env) == APP


def test_reconnecting_clears_title(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    push(env, status(k, "reconnecting", done=400), clock)
    assert title(env) == APP, "không thành viên nào đang chạy → None"


def test_retranslate_keeps_percent(env, clock):
    from teleport.ui import i18n

    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    env.window.retranslate()
    assert title(env) == f"40% · {APP}"
    i18n.set_language("en")
    settle()
    assert title(env) == f"40% · {APP}"


def test_title_label_and_brand_stay_app_name(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    assert env.window.title_label.text() == APP
    assert env.window.brand_label.text() == APP


def test_attach_new_host_restores_title_and_tray(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    env.ctl.attach(FakeHost(env.tmp / "moi"))
    assert title(env) == APP
    assert env.tray.state.progress is None
    # Đợt mới bắt đầu trống, nhịp đặt lại: lượt mới áp ngay.
    k2 = tkey("receive")
    push(env, status(k2, "transferring"), clock, dt=0.1)
    push(env, progress(k2, 200), clock, dt=0.1)
    assert title(env) in (f"0% · {APP}", f"20% · {APP}")


def test_close_all_restores_title_and_ignores_later_updates(env, clock):
    k = tkey("receive")
    push(env, status(k, "transferring"), clock)
    push(env, progress(k, 400), clock)
    env.ctl.close_all()
    assert title(env) == APP
    assert env.tray.state.progress is None
    push(env, progress(k, 800), clock)
    assert title(env) == APP, "S13: `_update_progress` thoát sớm khi đang đóng"


def test_title_and_tray_share_same_value(env, clock):
    env.tray.set_running(True)
    s, r = tkey("send", B_ID), tkey("receive")
    push(env, status(s, "transferring"), clock)
    push(env, status(r, "transferring"), clock)
    push(env, progress(s, 300), clock)
    push(env, progress(r, 500), clock)
    assert title(env) == f"40% · {APP}"
    assert env.tray.state.progress == 40
    assert "Đang truyền 2 lượt · 40%" in env.tray.tooltip()


# =================================================================================================
# R4, S18: khay
# =================================================================================================


def test_tray_state_progress_defaults_none():
    from teleport.ui.tray import TrayState

    assert TrayState().progress is None


def test_tray_tooltip_with_progress(qapp):
    from teleport.ui.tray import TrayState, tray_tooltip

    tip = tray_tooltip(TrayState(running=True, active=2, progress=40))
    assert "Đang truyền 2 lượt · 40%" in tip


def test_tray_tooltip_without_progress_is_old_line(qapp):
    from teleport.ui.tray import TrayState, tray_tooltip

    tip = tray_tooltip(TrayState(running=True, active=2, progress=None))
    assert tip == tray_tooltip(TrayState(running=True, active=2))
    assert "Đang truyền 2 lượt" in tip and "%" not in tip


def test_tray_tooltip_progress_ignored_when_no_active(qapp):
    from teleport.ui.tray import TrayState, tray_tooltip

    assert tray_tooltip(TrayState(running=True, active=0, progress=40)) == tray_tooltip(
        TrayState(running=True)
    )


def test_tray_tooltip_progress_ignored_when_not_running(qapp):
    from teleport.ui import texts
    from teleport.ui.tray import TrayState, tray_tooltip

    assert tray_tooltip(TrayState(running=False, active=2, progress=40)) == texts.APP_NAME


def test_tray_tooltip_progress_english(qapp):
    from teleport.ui import i18n
    from teleport.ui.tray import TrayState, tray_tooltip

    i18n.set_language("en")
    assert "1 transfer in progress · 40%" in tray_tooltip(TrayState(running=True, active=1, progress=40))
    assert "3 transfers in progress · 40%" in tray_tooltip(TrayState(running=True, active=3, progress=40))


@pytest.mark.parametrize("lang", ["vi", "en"])
@pytest.mark.parametrize("unavailable", [False, True])
def test_tray_tooltip_with_progress_within_budget(qapp, lang, unavailable):
    from teleport.ui import i18n
    from teleport.ui.tray import (
        TOOLTIP_MAX_UNITS,
        ClipNotice,
        ClipNoticeKind,
        TrayState,
        tray_tooltip,
        utf16_units,
    )

    if lang == "en":
        i18n.set_language("en")
    long_name = "Máy-tính-có-tên-rất-dài-" * 8 + "😀" * 20
    for active in (1, 99, 99_999):
        state = TrayState(
            running=True,
            active=active,
            progress=95,
            paused=not unavailable,
            unavailable=unavailable,
            clipboard=ClipNotice(ClipNoticeKind.RECEIVED, long_name),
        )
        tip = tray_tooltip(state)
        assert utf16_units(tip) <= TOOLTIP_MAX_UNITS, (lang, active, utf16_units(tip), tip)


def test_tray_badge_unchanged_by_progress():
    from teleport.ui.tray import TrayState, tray_badge

    assert tray_badge(TrayState(running=True, active=1, progress=40)) is tray_badge(
        TrayState(running=True, active=1)
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (40, 40),
        (0, 0),
        (100, 100),
        (None, None),
        (101, None),
        (-1, None),
        (True, None),
        (False, None),
        (40.0, None),
        ("40", None),
    ],
)
def test_tray_set_progress_accepts_only_int_0_to_100(qapp, value, expected):
    from teleport.ui.tray import Tray

    tray = Tray()
    try:
        tray.set_running(True)
        tray.set_progress(40)
        tray.set_progress(value)
        assert tray.state.progress == expected
    finally:
        tray.dispose()


def test_tray_set_progress_updates_tooltip(qapp):
    from teleport.ui.tray import Tray

    tray = Tray()
    try:
        tray.set_running(True)
        tray.set_activity(1)
        tray.set_progress(35)
        assert "Đang truyền 1 lượt · 35%" in tray.tooltip()
        tray.set_progress(None)
        assert "%" not in tray.tooltip()
    finally:
        tray.dispose()


# =================================================================================================
# R9: gộp thông báo nhận xong
# =================================================================================================
#
# Đồng hồ giả (`transfers._monotonic`, fixture `clock`) và hằng thật (3 s / 10 s): test tiến đồng hồ rồi
# phát `timeout` của `_notify_timer` thay vì chờ giờ thật. Chỉ một test chờ giờ thật, biên rộng.


def fire_notify_timer(env) -> None:
    """Hẹn giờ gộp “tới giờ” (như QTimer chạy): controller đọc lại `due` theo đồng hồ giả."""
    env.ctl._notify_timer.timeout.emit()
    settle()


@real_notify_delay
def test_two_receives_close_together_give_one_message(env, clock):
    from teleport.ui.shell import Reveal

    env.flags.window_active = False
    a, b = env.receive_dir / "a.txt", env.receive_dir / "b (1).txt"
    receive(env, tkey("receive"), [a], names=["a.txt"])
    clock.advance(1.0)
    receive(env, tkey("receive"), [b], names=["b.txt"])
    assert received(env) == [], "chưa hiện: còn trong khoảng lặng"
    assert env.ctl._notify_timer.isActive(), "đang hẹn hiện nhóm"
    clock.advance(2.0)  # mới 2 s từ lượt cuối < NOTIFY_QUIET
    fire_notify_timer(env)
    assert received(env) == [], "tới giờ mà còn trong khoảng lặng: hẹn lại, chưa hiện"
    assert env.ctl._notify_timer.isActive()
    clock.advance(1.1)
    fire_notify_timer(env)
    [(text, folder)] = received(env)
    assert text == "Đã nhận 2 file từ PC-Nha."
    assert isinstance(folder, Reveal)
    assert tuple(folder.files) == (a, b)
    assert folder.root == env.receive_dir
    fire_notify_timer(env)
    assert len(received(env)) == 1, "nhóm đã hiện không hiện lại"


@real_notify_delay
def test_two_devices_give_one_message_with_device_count(env, clock):
    env.flags.window_active = False
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"], names=["a.txt"])
    clock.advance(0.5)
    receive(env, tkey("receive", B_ID), [env.receive_dir / "b.txt", env.receive_dir / "c.txt"])
    clock.advance(3.5)
    fire_notify_timer(env)
    assert [t for t, _ in received(env)] == ["Đã nhận 3 file từ 2 máy."]


@real_notify_delay
def test_continuous_receives_still_notify_at_max_wait(env, clock):
    from teleport.ui import notify

    env.flags.window_active = False
    shown_at: list[float] = []
    start = clock.now
    for i in range(30):
        receive(env, tkey("receive"), [env.receive_dir / f"f{i}.bin"])
        fire_notify_timer(env)
        if len(received(env)) > len(shown_at):
            shown_at.append(clock.now - start)
        clock.advance(1.0)  # < NOTIFY_QUIET: khoảng lặng không bao giờ tới
    assert shown_at, "lượt xong liên tục: phải có thông báo trước khi hết chuỗi"
    assert shown_at[0] <= notify.NOTIFY_MAX_WAIT, shown_at
    assert shown_at[0] >= notify.NOTIFY_MAX_WAIT - 1.0, f"không hiện sớm hơn MAX_WAIT: {shown_at}"


@real_notify_delay
def test_receive_due_now_flushes_synchronously(env, clock, monkeypatch):
    """Sau `add` mà `due` ≤ 0 → flush đồng bộ, không cần hẹn giờ."""
    from teleport.ui import notify

    monkeypatch.setattr(notify, "NOTIFY_QUIET", 0)
    env.flags.window_active = False
    receive(env, tkey("receive"), [env.receive_dir / "a.txt"], names=["a.txt"])
    assert [t for t, _ in received(env)] == ["Đã nhận a.txt từ PC-Nha."]
    assert not env.ctl._notify_timer.isActive()


@real_notify_delay
def test_two_receives_one_message_in_real_time(env, qtbot, monkeypatch):
    """Một test giờ thật (biên rộng): QTimer thật hiện đúng một bóng thoại cho hai lượt gần nhau."""
    from teleport.ui import notify

    monkeypatch.setattr(notify, "NOTIFY_QUIET", 1.0)
    monkeypatch.setattr(notify, "NOTIFY_MAX_WAIT", 5.0)
    env.flags.window_active = False
    receive(env, tkey("receive"), [env.receive_dir / "a.txt"], names=["a.txt"])
    receive(env, tkey("receive"), [env.receive_dir / "b.txt"], names=["b.txt"])
    assert received(env) == []
    qtbot.waitUntil(lambda: bool(received(env)), timeout=15000)
    qtbot.wait(300)
    assert [t for t, _ in received(env)] == ["Đã nhận 2 file từ PC-Nha."]


@real_notify_delay
def test_offer_waiting_message_is_not_delayed(env, clock):
    """R14: “Có file đang chờ bạn nhận.” không bị hoãn/gộp."""
    env.flags.window_active = False
    env.flags.app_active = False
    push(env, offer(tkey("receive", B_ID), auto=False))
    assert [t for t, _ in env.shown] == [OFFER_WAITING]


@real_notify_delay
def test_flush_notifications_shows_pending_group_now_and_once(env, clock):
    env.flags.window_active = False
    receive(env, tkey("receive"), [env.receive_dir / "a.txt"], names=["a.txt"])
    assert received(env) == []
    env.ctl.flush_notifications()
    assert [t for t, _ in received(env)] == ["Đã nhận a.txt từ PC-Nha."]
    assert not env.ctl._notify_timer.isActive()
    clock.advance(20.0)
    fire_notify_timer(env)
    assert len(received(env)) == 1, "hẹn giờ không hiện lại nhóm đã flush"


def test_immediate_mode_single_receive_carries_reveal(env):
    """Với `notify_immediate` (hằng = 0): flush đồng bộ; `folder` là `Reveal`, không còn `Path` cha."""
    from teleport.ui.shell import Reveal

    env.flags.window_active = False
    saved = env.receive_dir / "con" / "a (1).txt"
    receive(env, tkey("receive"), [saved], names=["a.txt"])
    [(text, folder)] = received(env)
    assert text == "Đã nhận a (1).txt từ PC-Nha."
    assert isinstance(folder, Reveal)
    assert tuple(folder.files) == (saved,)
    assert folder.root == env.receive_dir


def test_receive_without_file_done_reveals_receive_dir(env):
    env.flags.window_active = False
    receive(env, tkey("receive"), [])
    [(_, folder)] = received(env)
    assert tuple(folder.files) == ()
    assert folder.root == env.receive_dir
    assert folder.folder == env.receive_dir


def test_receive_without_any_folder_has_no_payload(env):
    """S12: không file, không thư mục nhận → `folder=None` (bấm thì đưa cửa sổ lên)."""
    env.flags.window_active = False
    env.ctl.set_receive_dir(None)
    receive(env, tkey("receive"), [])
    [(_, folder)] = received(env)
    assert folder is None


def test_reveal_files_are_capped(env):
    from teleport.ui import shell

    env.flags.window_active = False
    cap = shell.REVEAL_MAX_ITEMS
    paths = [env.receive_dir / f"f{i:02}.bin" for i in range(cap + 5)]
    receive(env, tkey("receive"), paths)
    [(_, folder)] = received(env)
    assert tuple(folder.files) == tuple(paths[-cap:])


# =================================================================================================
# R10: không báo khi đang mở đúng cuộc trò chuyện đó
# =================================================================================================


def test_thread_in_view_true_for_open_thread_only(env):
    assert env.ctl.thread_in_view(A_ID) is True
    assert env.ctl.thread_in_view(B_ID) is False
    assert env.ctl.offer_in_view(A_ID) is env.ctl.thread_in_view(A_ID)


def test_no_received_message_when_thread_in_view(env):
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert received(env) == []


def test_received_message_for_other_device(env):
    receive(env, tkey("receive", B_ID), [env.receive_dir / "a.txt"], names=["a.txt"])
    assert [t for t, _ in received(env)] == [f"Đã nhận a.txt từ {B_NAME}."]


def test_received_message_when_window_not_active(env):
    env.flags.window_active = False
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert len(received(env)) == 1


def test_received_message_when_window_minimized(env, qtbot):
    env.window.showMinimized()
    qtbot.waitUntil(env.window.isMinimized, timeout=2000)
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert len(received(env)) == 1


def test_received_message_when_window_hidden(env, qtbot):
    env.window.hide()
    settle(qtbot, 10)
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert len(received(env)) == 1


def test_received_message_when_on_settings_page(env, qtbot):
    from PySide6.QtWidgets import QWidget

    from teleport.ui.main_window import Page

    if not env.window.pages.has_page(Page.SETTINGS):
        env.window.add_page(Page.SETTINGS, QWidget())
    assert env.window.open_page(Page.SETTINGS)
    settle(qtbot, 10)
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert len(received(env)) == 1


def test_received_message_when_thread_scrolled_up(env, qtbot):
    view = env.ctl.view
    for _ in range(30):
        view.handle(finished(tkey("send", A_ID), "done"))
    settle(qtbot, 50)
    bar = view.thread_for(A_ID).scroll_area.verticalScrollBar()
    assert bar.maximum() > 0, "cần đủ bong bóng để cuộn"
    bar.setValue(0)
    settle()
    assert not view.is_pinned(A_ID)
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    assert len(received(env)) == 1


@real_notify_delay
def test_in_view_receive_is_not_added_to_group(env, clock):
    """Lượt của luồng đang xem không vào nhóm: nhóm chỉ đếm lượt của máy khác."""
    receive(env, tkey("receive", A_ID), [env.receive_dir / "a.txt"])
    receive(env, tkey("receive", B_ID), [env.receive_dir / "b.txt"], names=["b.txt"])
    clock.advance(20.0)
    fire_notify_timer(env)
    assert [t for t, _ in received(env)] == [f"Đã nhận b.txt từ {B_NAME}."]


# =================================================================================================
# R13: attach / close_all bỏ nhóm đang chờ
# =================================================================================================


@real_notify_delay
def test_attach_drops_pending_group_and_stops_timer(env, clock):
    env.flags.window_active = False
    receive(env, tkey("receive"), [env.receive_dir / "a.txt"])
    assert received(env) == []
    env.ctl.attach(FakeHost(env.tmp / "moi"))
    assert not env.ctl._notify_timer.isActive()
    clock.advance(20.0)
    fire_notify_timer(env)
    env.ctl.flush_notifications()
    assert received(env) == []


@real_notify_delay
def test_close_all_drops_pending_group_and_stops_timer(env, clock):
    env.flags.window_active = False
    receive(env, tkey("receive"), [env.receive_dir / "a.txt"])
    assert received(env) == []
    env.ctl.close_all()
    assert not env.ctl._notify_timer.isActive()
    clock.advance(20.0)
    fire_notify_timer(env)
    env.ctl.flush_notifications()
    assert received(env) == []


# =================================================================================================
# R12: nút “Hiện trong thư mục” của bong bóng nhận và mục lịch sử
# =================================================================================================


@pytest.fixture
def shell_calls(monkeypatch):
    """Thay `shell.show_in_folder`: ghi (files, root, folder) và trả `result["value"]`."""
    from teleport.ui import shell

    calls: list = []
    calls_open: list = []
    result = {"value": True}

    def fake(files, root, *, open_url, folder=None):
        calls.append((tuple(files), root, folder))
        calls_open.append(open_url)
        return result["value"]

    monkeypatch.setattr(shell, "show_in_folder", fake)
    return SimpleNamespace(calls=calls, open_urls=calls_open, result=result)


def done_bubble(env, paths: list[Path]):
    env.flags.window_active = False
    k = tkey("receive", A_ID)
    receive(env, k, paths)
    b = env.ctl.view.row(k)
    assert b is not None and b.finished
    return b


def test_done_receive_bubble_has_show_in_folder_button(env):
    b = done_bubble(env, [env.receive_dir / "a.txt"])
    assert b.open_button.isVisibleTo(env.window)
    assert plain(b.open_button.text()) == SHOW_IN_FOLDER
    assert plain(b.open_button.accessibleName()) == SHOW_IN_FOLDER


def test_done_receive_bubble_button_english(env):
    from teleport.ui import i18n

    b = done_bubble(env, [env.receive_dir / "a.txt"])
    i18n.set_language("en")
    settle()
    assert plain(b.open_button.text()) == SHOW_IN_FOLDER_EN


def test_bubble_keeps_saved_paths_and_receive_dir(env):
    a, c = env.receive_dir / "a.txt", env.receive_dir / "con" / "c (1).txt"
    b = done_bubble(env, [a, c])
    assert tuple(b.saved_paths) == (a, c)
    assert b.last_path == c
    assert b.finished_receive_dir == env.receive_dir


def test_bubble_saved_paths_are_capped(env):
    from teleport.ui import shell

    paths = [env.receive_dir / f"f{i:02}.bin" for i in range(shell.REVEAL_MAX_ITEMS + 8)]
    b = done_bubble(env, paths)
    assert tuple(b.saved_paths) == tuple(paths[-shell.REVEAL_MAX_ITEMS :])


def test_bubble_button_calls_shell_with_saved_paths_and_root(env, shell_calls):
    a, c = env.receive_dir / "a.txt", env.receive_dir / "c.txt"
    b = done_bubble(env, [a, c])
    b.open_button.click()
    assert shell_calls.calls == [((a, c), env.receive_dir, None)]


def test_bubble_open_url_passed_to_shell_reaches_chat_seam(env, shell_calls, monkeypatch):
    from PySide6.QtCore import QUrl

    from teleport.ui import chat

    got: list = []
    monkeypatch.setattr(chat, "open_url", lambda url: got.append(Path(QUrl(url).toLocalFile())) or True)
    b = done_bubble(env, [env.receive_dir / "a.txt"])
    b.open_button.click()
    [open_url] = shell_calls.open_urls
    open_url(QUrl.fromLocalFile(str(env.receive_dir)))
    assert got == [env.receive_dir], "open_url của shell phải đọc seam `chat.open_url` lúc gọi"


def test_bubble_selects_natively_when_files_in_receive_dir(env, fake_select_native, monkeypatch):
    from teleport.ui import chat, shell

    monkeypatch.setattr(shell, "_is_windows", lambda: True)
    opened: list = []
    monkeypatch.setattr(chat, "open_url", lambda url: opened.append(url) or True)
    fake_select_native.result = True
    a, c = env.receive_dir / "a.txt", env.receive_dir / "c.txt"
    b = done_bubble(env, [a, c])
    b.open_button.click()
    assert fake_select_native.calls == [(env.receive_dir, (a, c))]
    assert opened == []
    assert env.ctl.view.notice_text() == ""


def test_bubble_fallback_failure_shows_old_warning_with_parent(env, monkeypatch):
    from teleport.ui import chat, send
    from teleport.ui.widgets import InfoLevel

    monkeypatch.setattr(chat, "open_url", lambda url: False)
    saved = env.receive_dir / "con" / "a.txt"
    b = done_bubble(env, [saved])
    b.open_button.click()
    assert env.ctl.view.info_bar.level is InfoLevel.WARNING
    assert env.ctl.view.notice_text() == OPEN_FAILED.format(path=send.printable(str(saved.parent)))


def test_bubble_without_saved_file_has_no_button(env):
    b = done_bubble(env, [])
    assert not b.open_button.isVisibleTo(env.window)


def test_send_bubble_has_no_button(env):
    k = tkey("send", A_ID)
    push(env, status(k, "transferring"))
    push(env, finished(k, "done"))
    assert not env.ctl.view.row(k).open_button.isVisibleTo(env.window)


# ---- Mục lịch sử -------------------------------------------------------------------------------


def hentry(saved_path: str | None, *, i: int = 1):
    import datetime

    from teleport.core.history import HistoryEntry

    return HistoryEntry(
        direction="receive",
        device_id=A_ID,
        device_name=A_NAME,
        transfer_id=f"{i:032x}",
        file_count=1,
        total_bytes=1000,
        done_bytes=1000,
        names=("anh.jpg",),
        result="done",
        finished_at=datetime.datetime(2026, 10, 30, 9, 0, tzinfo=datetime.UTC),
        saved_path=saved_path,
    )


@pytest.fixture
def history_view(qtbot, tmp_path):
    from teleport.ui.chat import ChatView, HistoryState
    from teleport.ui.radar import DeviceListModel

    devices = DeviceListModel()
    devices.reset([dview(A_ID, A_NAME)])
    v = ChatView(devices)
    qtbot.addWidget(v)
    v.set_device_names({A_ID: A_NAME})
    receive_dir = tmp_path / "nhan"
    v.set_receive_dir(receive_dir)
    v.resize(720, 560)
    v.show()
    qtbot.waitExposed(v)

    def load(entries) -> list:
        from teleport.ui.chat_bubbles import HistoryBubble

        with qtbot.waitSignal(v.history_needed, timeout=2000):
            v.set_device(A_ID)
        v.load_history(A_ID, list(entries))
        thread = v.thread_for(A_ID)
        assert thread.history_state is HistoryState.LOADED
        return [b for b in thread.bubbles() if isinstance(b, HistoryBubble)]

    return SimpleNamespace(view=v, load=load, receive_dir=receive_dir)


def test_history_entry_button_text_and_name(history_view):
    saved = history_view.receive_dir / "anh.jpg"
    [b] = history_view.load([hentry(str(saved))])
    assert b.open_button.isVisibleTo(history_view.view)
    assert plain(b.open_button.text()) == SHOW_IN_FOLDER
    assert plain(b.open_button.accessibleName()) == SHOW_IN_FOLDER


def test_history_entry_button_calls_shell_with_saved_path_and_receive_dir(history_view, shell_calls):
    saved = history_view.receive_dir / "anh.jpg"
    [b] = history_view.load([hentry(str(saved))])
    b.open_button.click()
    assert shell_calls.calls == [((saved,), history_view.receive_dir, None)]


def test_history_entry_fallback_failure_shows_warning(history_view, monkeypatch):
    from teleport.ui import chat, send

    monkeypatch.setattr(chat, "open_url", lambda url: False)
    saved = history_view.receive_dir / "con" / "anh.jpg"
    [b] = history_view.load([hentry(str(saved))])
    b.open_button.click()
    assert history_view.view.notice_text() == OPEN_FAILED.format(path=send.printable(str(saved.parent)))


def test_history_entry_without_visible_button_does_not_call_shell(history_view, shell_calls):
    [b] = history_view.load([hentry("tuong-doi/anh.jpg")])
    assert not b.open_button.isVisibleTo(history_view.view)
    b.open_clicked.emit()
    assert shell_calls.calls == [], "S4: vẫn qua cổng nút đang hiện"


# =================================================================================================
# R11: bấm bóng thoại (GuiApp)
# =================================================================================================


@pytest.fixture
def gapp(qapp, qtbot, monkeypatch, config_dir):
    """`GuiApp` dựng thẳng, không node; khay giả “có thật”, không `exec()` hộp thoại nào."""
    from PySide6.QtWidgets import QDialog, QMessageBox, QSystemTrayIcon

    from teleport.ui import tray
    from teleport.ui.app import GuiApp

    visible: dict[int, bool] = {}
    monkeypatch.setattr(tray, "is_available", lambda: True)
    monkeypatch.setattr(QSystemTrayIcon, "show", lambda self: visible.__setitem__(id(self), True))
    monkeypatch.setattr(QSystemTrayIcon, "hide", lambda self: visible.__setitem__(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "setVisible", lambda self, v: visible.__setitem__(id(self), bool(v)))
    monkeypatch.setattr(QSystemTrayIcon, "isVisible", lambda self: visible.get(id(self), False))
    monkeypatch.setattr(QSystemTrayIcon, "showMessage", lambda self, *a, **k: None)
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **k: 0)
    monkeypatch.setattr(QDialog, "exec", lambda self, *a, **k: 0)

    controller = GuiApp(qapp, config_dir("A", identity=False))
    controller.tray.show()
    controller.window.show()
    yield controller
    with contextlib.suppress(Exception):
        controller.shutdown()
    with contextlib.suppress(Exception):
        controller.window.hide()
        controller.window.deleteLater()
    qapp.processEvents()


@pytest.fixture
def app_opened(monkeypatch):
    from teleport.ui import app as ui_app

    urls: list[Path] = []
    monkeypatch.setattr(ui_app, "open_url", lambda url: urls.append(Path(url.toLocalFile())) or True)
    return urls


def click_message(controller, payload) -> None:
    from PySide6.QtWidgets import QSystemTrayIcon

    controller.tray.show_message("Đã nhận 2 file từ PC-Nha.", folder=payload)
    controller.tray.findChild(QSystemTrayIcon).messageClicked.emit()


def test_click_reveal_message_calls_shell_with_payload(gapp, shell_calls, app_opened, tmp_path):
    from PySide6.QtCore import QUrl

    from teleport.ui.shell import Reveal

    root = tmp_path / "nhan"
    files = (root / "a.txt", root / "b.txt")
    click_message(gapp, Reveal(files=files, root=root, folder=None))
    assert shell_calls.calls == [(files, root, None)]
    [open_url] = shell_calls.open_urls
    open_url(QUrl.fromLocalFile(str(root)))
    assert app_opened == [root], "open_url của shell phải đọc seam `app.open_url` lúc gọi"


def test_click_reveal_without_files_passes_folder(gapp, shell_calls, tmp_path):
    from teleport.ui.shell import Reveal

    root = tmp_path / "nhan"
    click_message(gapp, Reveal(files=(), root=root, folder=root))
    assert shell_calls.calls == [((), root, root)]


def test_click_reveal_failure_logs_warning(gapp, shell_calls, caplog, tmp_path):
    from teleport.ui.shell import Reveal

    shell_calls.result["value"] = False
    with caplog.at_level(logging.WARNING):
        click_message(gapp, Reveal(files=(tmp_path / "a.txt",), root=tmp_path, folder=None))
    assert any(r.levelno >= logging.WARNING for r in caplog.records), caplog.records


def test_click_reveal_end_to_end_falls_back_to_parent(gapp, app_opened, fake_select_native, tmp_path):
    from teleport.ui.shell import Reveal

    root = tmp_path / "nhan"
    click_message(gapp, Reveal(files=(root / "con" / "a.txt",), root=root, folder=None))
    assert app_opened == [root / "con"]


def test_click_path_message_opens_path_as_before(gapp, shell_calls, app_opened, tmp_path):
    click_message(gapp, tmp_path / "nhan")
    assert app_opened == [tmp_path / "nhan"]
    assert shell_calls.calls == []


def test_click_message_without_payload_brings_window_to_front(gapp, shell_calls, app_opened, qtbot):
    gapp.window.hide()
    settle(qtbot, 10)
    click_message(gapp, None)
    assert gapp.window.isVisible()
    assert shell_calls.calls == [] and app_opened == []


def test_received_transfer_click_selects_file_natively(
    gapp, app_opened, fake_select_native, monkeypatch, tmp_path
):
    """Từ đầu tới cuối: lượt nhận xong → bóng thoại `Reveal` → bấm → chọn sẵn file (Windows giả)."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from teleport.app.node import DeviceOnline
    from teleport.ui import shell

    monkeypatch.setattr(shell, "_is_windows", lambda: True)
    fake_select_native.result = True
    receive_dir = tmp_path / "nhan"
    gapp.transfers.attach(FakeHost(receive_dir))
    saved = receive_dir / "video (1).mp4"
    k = tkey("receive", A_ID)
    gapp.transfers.on_node_event(DeviceOnline(dview()))
    gapp.transfers.on_transfer(offer(k))
    gapp.transfers.on_transfer(file_done(k, saved))
    gapp.transfers.on_transfer(finished(k, "done"))
    gapp.tray.findChild(QSystemTrayIcon).messageClicked.emit()
    assert fake_select_native.calls == [(receive_dir, (saved,))]
    assert app_opened == []
