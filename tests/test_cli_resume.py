"""`teleport receive` bị giết hay dừng có trật tự giữa lượt, chạy lại → lượt hoàn tất (P3-3b, việc V4).

Viết từ đặc tả, không từ code: `specs/spec-p3-3b.md` mục 4 (V4), 5 (“giết tiến trình nhận lúc nhận và lúc
đọc lại → mở lại → hoàn tất”; “đóng trật tự giữa lượt → `.part`, `.state`, `transfer.json` còn → mở lại →
hoàn tất”); `specs/spec-p3.md` mục P3-3b; protocol §6.2 (“Tắt app nhận”); mvp F6, F7.

Mỗi node là một tiến trình con `python -m teleport` (fixture `procs`, `tests/conftest.py`; tự giết khi test
xong). `send` nối tới máy nhận qua proxy TCP (`tcp_proxy`) để khi `receive` chạy lại trên cổng mới chỉ cần
đổi đích của proxy (`TcpProxy.target`, đọc lúc nối); `send` tự nối lại theo lịch thật của nó. Giết bằng
`Popen.kill()` (Windows: TerminateProcess; POSIX: SIGKILL). Ca “lúc đọc lại”: một `sitecustomize.py` trong
thư mục riêng (chỉ nạp khi có biến môi trường của test) làm `PartFile.reread` của tiến trình nhận báo một
dấu lên stderr rồi treo, để test giết đúng lúc đang đọc lại.

P3-4 (`specs/spec-p3-4.md` việc V3, mục 9 S4): giữ `--json`; lần chạy lại phải có `restored` của lượt dở,
`result` của `send` có `payload_sent`, Ctrl+C có `message` = câu (a). Bản text của `receive` và phần lớn
câu (e) của `send` được kiểm trong tiến trình (`tests/test_cli_transfer.py`, mục P3-4, P3-5), vì
`receive` bản text không in cổng để dựng proxy; ở đây chỉ `send` chạy bản text (V12c bên dưới).

P3-5 (`specs/spec-p3-5.md`, mục 9 thắng): ngưỡng mvp N4 lấy từ fixture `n4_extra` (không chép số).
- V5: giết / Ctrl+C `receive` ở 85 % của file 96 MiB, vị trí cắt do proxy tự chặn (`TcpProxy.block_at`,
  chiều c2s vì `send` là bên mở kết nối); tiền đề `byte_lúc_cắt > n4_extra`, rồi `payload_sent − cỡ file
  ≤ n4_extra`. Ctrl+C lúc proxy đang chặn: `receive` chờ thêm tới `CLOSE_TIMEOUT` khi đóng (N10).
  fix(app) 1e (`specs/spec-fix-app.md` mục 2 (1e), 9 S10): ca Ctrl+C còn chạy `sitecustomize` với cổng
  `TRACE_ENV` (log mỗi `write_at`, `commit`), rồi khẳng định lô dở lúc Ctrl+C đã có `MARK` bền: tập khối
  `MARK` trong `.state` (đọc độc lập, fixture `read_state`) = tập khối đã ghi. Hook nạp tiếp
  `sitecustomize` kế tiếp trên `sys.path` (nó che), để kiểm đột biến bằng hook riêng.
- V9: bên **gửi** khởi động lại (bị giết, rồi một `send` mới gửi file khác) → `receive` kết thúc lượt cũ
  bằng `unknown_transfer` (by_peer), xóa tạm của nó, lượt mới xong.
- V12c: câu (e) của `send` bản text theo lịch thử lại thật: `receive` (JSON, in cổng) dừng, proxy chuyển
  tiếp bình thường tới cổng đã đóng (mỗi lần thử: proxy accept rồi RST → “không kết nối được”).
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleport.lock import NodeLock
from teleport.trust.identity import load_or_create_identity, peer_cert_from_pem
from teleport.trust.store import TrustStore

pytestmark = [pytest.mark.integration]

LOCAL = "127.0.0.1"
SENDER = "Laptop-Minh"
RECEIVER = "PC-Nha"
MiB = 1024 * 1024
# Câu (a) của P3-4 (spec-p3-4 mục 9.1 Q3), lượt một file
R_SUSPENDED = (
    "Đã tạm dừng nhận {what} từ {s}. Chạy lại `teleport receive` (cùng thư mục nhận) để nhận tiếp phần "
    "còn thiếu, miễn là máy gửi vẫn đang chờ; quá 24 giờ kể từ lúc mất kết nối thì lần chạy sau sẽ xóa "
    "phần nhận dở."
)
# Câu `UNKNOWN_TRANSFER` của bên nhận (mvp §8)
R_UNKNOWN = "{s} đã hủy lượt gửi {file}. Hãy nhờ gửi lại."
# Câu (e) của `send` (spec-p3-4 mục 9.1 Q2) và phần đầu câu “mạng chặn”, không được in khi chờ nối lại
S_NOT_RECONNECTED_YET = (
    "Chưa nối lại được với {p}. Teleport vẫn đang thử lại (tối đa 24 giờ). Hãy kiểm tra máy đó vẫn đang "
    "chạy `teleport receive` và hai máy còn chung một mạng."
)
WIFI_BLOCKING = "Mạng Wi-Fi này có thể đang chặn"
N4_SIZE = 96 * MiB  # spec-p3-5 quyết định 6: file 96 MiB, cắt ở 85 %
CUT_AT = 0.85
HANG_MARK = "TEST-REREAD-HANG"
HANG_ENV = "TELEPORT_TEST_HANG_REREAD"
# fix(app) 1e: giá trị là đường dẫn file log. Mỗi dòng `<perf_counter_ns> <loại> …`:
#   W <file_index> <index>                      `PartFile.write_at` thành công
#   CS <file_index> <n> <i1,i2,…|->             `PartFile.commit` bắt đầu (n khối)
#   CE <file_index> <n> ok|err:<lỗi>            `PartFile.commit` kết thúc
#   SUSP <số khối mỗi SyncPart, ',' | ->        `TransferEngine.suspend_receiving` trả (chỉ để chẩn đoán)
#   INT                                         test gửi Ctrl+C (test tự ghi, sau khi tiến trình đã thoát)
# `perf_counter` dùng chung cho mọi tiến trình trên một máy (QPC / CLOCK_MONOTONIC / mach), nên so được.
TRACE_ENV = "TELEPORT_TEST_DISK_TRACE"

SITECUSTOMIZE = f'''
import os, sys, time
if os.environ.get("{HANG_ENV}"):
    from teleport.app import storage as _storage

    _real = _storage.PartFile.reread

    def _reread(self, *, stop=None):
        sys.stderr.write("{HANG_MARK}\\n")
        sys.stderr.flush()
        time.sleep(600)
        return _real(self, stop=stop)

    _storage.PartFile.reread = _reread

_trace_path = os.environ.get("{TRACE_ENV}")
if _trace_path:
    import threading
    from teleport.app import storage as _tstorage
    from teleport.core import transfer as _ttransfer

    _trace_lock = threading.Lock()
    _trace_fd = os.open(_trace_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_BINARY", 0))

    def _trace(*parts):
        with _trace_lock:
            line = " ".join(str(p) for p in (time.perf_counter_ns(), *parts)) + "\\n"
            os.write(_trace_fd, line.encode("ascii"))

    _real_write_at = _tstorage.PartFile.write_at
    _real_commit = _tstorage.PartFile.commit
    _real_suspend = _ttransfer.TransferEngine.suspend_receiving

    def _write_at(self, index, data):
        _real_write_at(self, index, data)
        _trace("W", self.file_index, index)

    def _commit(self, blocks):
        idx = [i for i, _ in blocks]
        _trace("CS", self.file_index, len(idx), ",".join(map(str, idx)) or "-")
        try:
            _real_commit(self, blocks)
        except BaseException as exc:
            _trace("CE", self.file_index, len(idx), "err:" + type(exc).__name__)
            raise
        _trace("CE", self.file_index, len(idx), "ok")

    def _suspend_receiving(self, now):
        actions = _real_suspend(self, now)
        sizes = [len(a.blocks) for a in actions if isinstance(a, _ttransfer.SyncPart)]
        _trace("SUSP", ",".join(map(str, sizes)) or "-")
        return actions

    _tstorage.PartFile.write_at = _write_at
    _tstorage.PartFile.commit = _commit
    _ttransfer.TransferEngine.suspend_receiving = _suspend_receiving

# Hook này che `sitecustomize` kế tiếp trên `sys.path` (của môi trường, hay hook đột biến khi kiểm chính
# test này): nạp tiếp nó, sau các vá ở trên.
import importlib.util as _ilu
_here = os.path.dirname(os.path.abspath(__file__))
for _d in sys.path:
    _p = os.path.join(_d or os.getcwd(), "sitecustomize.py")
    if os.path.abspath(os.path.dirname(_p)) != _here and os.path.isfile(_p):
        _spec = _ilu.spec_from_file_location("_teleport_test_chained_sitecustomize", _p)
        _spec.loader.exec_module(_ilu.module_from_spec(_spec))
        break
'''


def hook_env(tmp_path: Path, **env: str) -> dict[str, str]:
    """Ghi `sitecustomize.py` (SITECUSTOMIZE) vào `tmp_path/hook`; trả `env` cho `procs` (PYTHONPATH có
    thư mục hook đứng đầu, cộng các biến cổng `env`)."""
    hook = tmp_path / "hook"
    hook.mkdir(exist_ok=True)
    (hook / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    pythonpath = os.pathsep.join(p for p in (str(hook), os.environ.get("PYTHONPATH", "")) if p)
    return {"PYTHONPATH": pythonpath, **env}


# --- Hàm phụ trợ ---------------------------------------------------------------------------------


@pytest.fixture
def pair_dirs(tmp_path):
    """S (gửi) và R (nhận) tin nhau: S lưu R là “PC-Nha”, R lưu S là “Laptop-Minh”."""
    s_dir, r_dir = tmp_path / "S", tmp_path / "R"
    ident_s, ident_r = load_or_create_identity(s_dir), load_or_create_identity(r_dir)
    TrustStore.load(s_dir).add(peer_cert_from_pem(ident_r.cert_pem()), RECEIVER)
    TrustStore.load(r_dir).add(peer_cert_from_pem(ident_s.cert_pem()), SENDER)
    return SimpleNamespace(S=s_dir, R=r_dir, recv=tmp_path / "nhan", src=tmp_path / "nguon", tmp=tmp_path)


def receive_cmd(net) -> list[str]:
    return [
        "--config-dir",
        str(net.R),
        "receive",
        "--json",
        "--yes",
        "--dir",
        str(net.recv),
        "--name",
        RECEIVER,
        "--host",
        LOCAL,
        "--port",
        "0",
    ]


def send_cmd(net, files, port: int, *, extra=(), json_mode: bool = True) -> list[str]:
    return [
        "--config-dir",
        str(net.S),
        "send",
        *(str(f) for f in files),
        "--to",
        RECEIVER,
        "--address",
        f"{LOCAL}:{port}",
        *(["--json"] if json_mode else []),
        "--name",
        SENDER,
        "--host",
        LOCAL,
        *extra,
    ]


def make_file(directory: Path, name: str, size: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(os.urandom(size))
    return path


def sha256_of(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def wait_status(proc, status: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        ev = proc.wait_json("status", max(0.1, deadline - time.monotonic()))
        if ev["status"] == status:
            return ev


def poll(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError(f"hết {timeout} s mà {what} vẫn chưa đúng")
        time.sleep(0.02)


def wait_lock_free(directory: Path) -> None:
    """Khóa của tiến trình bị giết được nhả không đồng bộ trên Windows: chờ có hạn (architecture §4)."""
    lock = NodeLock(directory)
    lock.acquire(timeout=10)
    lock.release()


def state_size(net, tid: str) -> int:
    try:
        return (net.recv / ".teleport" / tid / "0.state").stat().st_size
    except OSError:
        return 0


def statuses_seen(proc) -> list[str]:
    """Mọi `status` JSON tiến trình đã in tới giờ (chuyển hết dòng đang chờ sang `proc.out`)."""
    while not proc.lines.empty():
        proc.out.append(proc.lines.get())
    return [e["status"] for e in proc.events() if e.get("event") == "status"]


def assert_clean_exit(proc) -> None:
    err = proc.err_text()
    assert "Traceback" not in err and "Fatal Python error" not in err, err


def restart_receive(net, procs, proxy, tid: str):
    """Chạy lại `receive`, chờ `restored` của lượt dở `tid` (P3-4, spec-p3-4 mục 3.2), rồi đổi đích proxy.
    Sự kiện `restored` giữ ở `recv2.restored`."""
    recv2 = procs(receive_cmd(net))
    port2 = recv2.wait_json("receiving")["port"]
    restored = recv2.wait_json("restored", 30)
    assert (restored["transfer_id"], restored["direction"]) == (tid, "receive"), restored
    assert restored["device_name"] == SENDER and "message" not in restored, restored
    proxy.target = (LOCAL, port2)
    recv2.restored = restored
    return recv2


def finish_send_and_receive(net, send, recv2, src: Path, n4_extra: int) -> int:
    """`send` nối lại tới `receive` mới, lượt xong ở cả hai bên, file khớp nguồn; rồi dừng `receive`. Trả
    `payload_sent − cỡ file`.

    P3-4 (mục 3.2): `result` của `send` có `payload_sent` (int, ≥ cỡ file, phần thừa trong ngưỡng mvp N4);
    `result` của `receive` không có; `receive` chạy lại không phát `offer` cho lượt khôi phục.
    """
    assert send.finish(180) == 0, f"{send.out!r} {send.err_text()}"
    results = [e for e in send.events() if e["event"] == "result"]
    assert [r["result"] for r in results] == ["done"], results
    size = src.stat().st_size
    sent = results[0]["payload_sent"]
    assert type(sent) is int and size <= sent <= size + n4_extra, results
    res = recv2.wait_json("result", 60)
    assert res["result"] == "done", res
    assert "payload_sent" not in res
    assert sha256_of(net.recv / src.name) == sha256_of(src)
    recv2.interrupt()
    assert recv2.finish(30) == 0
    assert not [e for e in recv2.events() if e["event"] == "offer"], recv2.out
    assert_clean_exit(send)
    assert_clean_exit(recv2)
    return sent - size


# --- Test -----------------------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.demo
def test_killed_receive_mid_transfer_then_restarted_finishes(pair_dirs, procs, tcp_proxy, n4_extra):
    net = pair_dirs
    recv = procs(receive_cmd(net))
    proxy = tcp_proxy(recv.wait_json("receiving")["port"])
    src = make_file(net.src, "lon.bin", 24 * MiB)
    send = procs(send_cmd(net, [src], proxy.port, extra=["--limit-rate", "4M"]))
    tid = wait_status(recv, "transferring")["transfer_id"]
    # Có ít nhất một `MARK` bền (header `.state` 41 byte): một phần đã nhận sống qua lần giết.
    poll(lambda: state_size(net, tid) > 41, 30, "chưa có MARK nào trong .state")
    recv.kill()
    tdir = net.recv / ".teleport" / tid
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(tdir))
    wait_lock_free(net.R)

    recv2 = restart_receive(net, procs, proxy, tid)
    finish_send_and_receive(net, send, recv2, src, n4_extra)


@pytest.mark.slow
def test_killed_receive_during_reread_then_restarted_finishes(
    pair_dirs, procs, tcp_proxy, tmp_path, n4_extra
):
    net = pair_dirs
    recv = procs(receive_cmd(net), env=hook_env(tmp_path, **{HANG_ENV: "1"}))
    proxy = tcp_proxy(recv.wait_json("receiving")["port"])
    src = make_file(net.src, "f.bin", 6 * MiB + 9)
    send = procs(send_cmd(net, [src], proxy.port))
    tid = wait_status(recv, "transferring")["transfer_id"]
    poll(lambda: HANG_MARK in recv.err_text(), 60, "tiến trình nhận chưa tới bước đọc lại")
    recv.kill()
    tdir = net.recv / ".teleport" / tid
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(tdir))
    assert not (net.recv / src.name).exists()
    wait_lock_free(net.R)

    recv2 = restart_receive(net, procs, proxy, tid)
    finish_send_and_receive(net, send, recv2, src, n4_extra)


@pytest.mark.slow
def test_ctrl_c_receive_mid_transfer_suspends_then_restarted_finishes(pair_dirs, procs, tcp_proxy, n4_extra):
    """Ctrl+C khi đã có `MARK` bền mà lượt chưa sang đọc lại (spec-p3-3b mục 8.4 F2): file dài hơn hẳn
    `SYNC_EVERY` khối, để `MARK` đầu tới giữa lượt chứ không phải lúc đã đủ file."""
    from teleport.core.blocks import BLOCK_SIZE
    from teleport.core.transfer import SYNC_EVERY

    net = pair_dirs
    recv = procs(receive_cmd(net))
    proxy = tcp_proxy(recv.wait_json("receiving")["port"])
    src = make_file(net.src, "lon.bin", (2 * SYNC_EVERY + 8) * BLOCK_SIZE)
    send = procs(send_cmd(net, [src], proxy.port, extra=["--limit-rate", "4M"]))
    tid = wait_status(recv, "transferring")["transfer_id"]
    poll(lambda: state_size(net, tid) > 41, 30, "chưa có MARK nào trong .state")
    assert "verifying" not in statuses_seen(recv), "lượt đã sang đọc lại trước khi Ctrl+C"
    recv.interrupt()
    assert recv.finish(30) == 0, recv.err_text()
    results = [e for e in recv.events() if e["event"] == "result"]
    assert [(r["result"], r["by_peer"]) for r in results] == [("suspended", False)], results
    assert results[0]["message"] == R_SUSPENDED.format(what="lon.bin", s=SENDER), results
    assert "payload_sent" not in results[0]
    assert recv.events()[-1]["event"] == "stopped"
    tdir = net.recv / ".teleport" / tid
    left = set(os.listdir(tdir))
    assert {"transfer.json", "0.part", "0.state"} <= left, (left, recv.out, recv.err_text())
    assert send.p.poll() is None, "send phải còn chờ nối lại"
    assert_clean_exit(recv)

    recv2 = restart_receive(net, procs, proxy, tid)
    finish_send_and_receive(net, send, recv2, src, n4_extra)


# --- P3-5 V5: N4 ở 85 % của 96 MiB, tiến trình con --------------------------------------------------------


def text_of(proc) -> str:
    """Mọi dòng tiến trình đã in ra stdout tới giờ (chuyển hết dòng đang chờ sang `proc.out`)."""
    while not proc.lines.empty():
        proc.out.append(proc.lines.get())
    return "\n".join(proc.out)


def results_of(proc) -> list[dict]:
    return [e for e in proc.events() if e.get("event") == "result"]


def transfer_cut_at_85_percent(net, procs, tcp_proxy, n4_extra, *, env=None):
    """`receive` (JSON, biến môi trường thêm `env`) ← proxy ← `send` file 96 MiB; proxy tự chặn khi chiều
    c2s (payload) chạm 85 % cỡ file. Trả `(recv, proxy, send, src, tid)` sau khi đã chặn; kiểm hai tiền đề
    N4 (spec-p3-5 mục 8.4)."""
    assert n4_extra < CUT_AT * N4_SIZE, "tiền đề: gửi lại từ đầu ở 85 % phải vượt ngưỡng mvp N4"
    recv = procs(receive_cmd(net), env=env)
    proxy = tcp_proxy(recv.wait_json("receiving")["port"])
    proxy.block_at("c2s", int(CUT_AT * N4_SIZE))
    src = make_file(net.src, "lon.bin", N4_SIZE)
    send = procs(send_cmd(net, [src], proxy.port))
    tid = wait_status(recv, "transferring", 60)["transfer_id"]
    assert proxy.wait_fired(120), f"proxy chưa tới 85 %: {proxy.forwarded}"
    cut = proxy.fired_forwarded["c2s"]
    assert cut > n4_extra, f"tiền đề byte_lúc_cắt > n4_extra: {cut} ≤ {n4_extra}"
    assert send.p.poll() is None and recv.p.poll() is None
    return recv, proxy, send, src, tid


def reconnect_through_proxy(proxy) -> None:
    """Mạng có lại: cắt RST mọi kết nối cũ đang treo trong proxy (bên gửi thấy reset, tự nối lại theo
    lịch thật) rồi cho proxy chuyển tiếp lại, tới đích mới."""
    proxy.rst()
    proxy.resume()


@pytest.mark.slow
def test_killed_receive_at_85_percent_of_96_mib_resends_within_n4(pair_dirs, procs, tcp_proxy, n4_extra):
    """V5 (spec-p3-5, mvp N4 “tắt app nhận ở bất kỳ điểm nào”): giết `receive` khi proxy chặn ở 85 % →
    chạy lại `receive` (có `restored`), mạng có lại → lượt hoàn tất, file khớp, `payload_sent − cỡ file
    ≤ n4_extra`. Phần chưa `MARK` (tối đa một lô `SYNC_EVERY` khối) mất theo lần giết."""
    net = pair_dirs
    recv, proxy, send, src, tid = transfer_cut_at_85_percent(net, procs, tcp_proxy, n4_extra)
    recv.kill()
    assert {"transfer.json", "0.part", "0.state"} <= set(os.listdir(net.recv / ".teleport" / tid))
    wait_lock_free(net.R)

    recv2 = restart_receive(net, procs, proxy, tid)
    assert 0 <= recv2.restored["done_bytes"] < N4_SIZE, recv2.restored
    reconnect_through_proxy(proxy)
    excess = finish_send_and_receive(net, send, recv2, src, n4_extra)
    print(f"V5 kill: cut_c2s={proxy.fired_forwarded['c2s']} excess_bytes={excess}")


def parse_disk_trace(path: Path) -> SimpleNamespace:
    """Đọc log của hook `TRACE_ENV` (file 0): `written` (tập khối `write_at` xong), `commits` (danh sách
    `SimpleNamespace(start, end, blocks, outcome)`; `end`/`outcome` None nếu không có dòng kết thúc),
    `suspend` (các dòng SUSP), `interrupt` (mốc INT hay None). Mốc là `perf_counter_ns`."""
    written: set[int] = set()
    commits: list[SimpleNamespace] = []
    suspend: list[tuple[int, str]] = []
    interrupt = None
    for line in path.read_text(encoding="ascii").split("\n")[:-1]:  # bỏ dòng cuối đang ghi dở
        stamp, kind, *rest = line.rstrip("\r").split(" ")
        ts = int(stamp)
        if kind == "W" and rest[0] == "0":
            written.add(int(rest[1]))
        elif kind == "CS" and rest[0] == "0":
            blocks = () if rest[2] == "-" else tuple(int(i) for i in rest[2].split(","))
            commits.append(SimpleNamespace(start=ts, end=None, blocks=blocks, outcome=None))
        elif kind == "CE" and rest[0] == "0":
            # Lần commit kết thúc là lần mở cũ nhất chưa kết thúc cùng số khối (commit chạy tuần tự
            # trong một hàng đĩa, nên thực tế chỉ có một lần mở).
            c = next(c for c in commits if c.end is None and len(c.blocks) == int(rest[1]))
            c.end, c.outcome = ts, rest[2]
        elif kind == "SUSP":
            suspend.append((ts, rest[0]))
        elif kind == "INT":
            interrupt = ts
    return SimpleNamespace(written=written, commits=commits, suspend=suspend, interrupt=interrupt)


def wait_disk_quiet(trace: Path, *, quiet: float, timeout: float) -> None:
    """Chờ tới khi log `TRACE_ENV` không thêm khối ghi hay commit nào trong `quiet` giây và mọi commit đã
    bắt đầu đều đã kết thúc."""
    deadline = time.monotonic() + timeout
    last, since = None, time.monotonic()
    while True:
        log = parse_disk_trace(trace) if trace.exists() else None
        key = (
            None
            if log is None
            else (len(log.written), len(log.commits), sum(c.end is None for c in log.commits))
        )
        now = time.monotonic()
        if key != last:
            last, since = key, now
        elif key is not None and key[2] == 0 and now - since >= quiet:
            return
        if now > deadline:
            raise AssertionError(f"hết {timeout} s mà tiến trình nhận vẫn còn ghi/commit: {key}")
        time.sleep(0.05)


@pytest.mark.slow
def test_ctrl_c_receive_at_85_percent_of_96_mib_resends_within_n4(
    pair_dirs, procs, tcp_proxy, n4_extra, tmp_path, read_state
):
    """V5 (spec-p3-5, mvp N4; N10 của mục 9.2): Ctrl+C `receive` khi proxy đang chặn ở 85 % → `receive`
    thoát 0 (đóng có trật tự, chờ thêm tới `CLOSE_TIMEOUT` vì kết nối không đi được), lượt `suspended`;
    chạy lại, mạng có lại → hoàn tất, file khớp, `payload_sent − cỡ file ≤ n4_extra`.

    fix(app) 1e (spec-fix-app mục 2 (1e), 9 S10): đóng có trật tự làm bền cả lô dở. Hook `TRACE_ENV`
    ghi mỗi `write_at` xong và mỗi `commit` bắt đầu/kết thúc; test chờ đĩa yên (đã ghi hết phần qua proxy,
    mọi commit đã bắt đầu đều xong) rồi mới Ctrl+C, và ghi mốc lúc gửi Ctrl+C. Tiền đề: có
    khối đã ghi không thuộc `commit` nào bắt đầu trước Ctrl+C (lô dở khác rỗng). Khẳng định: tập khối có
    `MARK` trong `.state` (đọc độc lập, `read_state`) đúng bằng tập khối đã ghi, hash `MARK` khớp nguồn,
    và `restored.done_bytes` bằng tổng byte các khối đó (> `n4_extra`)."""
    from teleport.core.transfer import SYNC_EVERY

    # Tiền đề lô dở chỉ ổn định khi số khối ở mốc cắt không là bội của SYNC_EVERY: đổi CUT_AT/N4_SIZE
    # mà rơi vào bội thì phải chọn lại mốc, đừng để test đỏ ở tiền đề.
    assert int(CUT_AT * N4_SIZE) // MiB % SYNC_EVERY != 0, "mốc cắt rơi vào biên lô: chọn lại CUT_AT"
    net = pair_dirs
    trace = tmp_path / "disk-trace.log"
    env = hook_env(tmp_path, **{TRACE_ENV: str(trace)})
    recv, proxy, send, src, tid = transfer_cut_at_85_percent(net, procs, tcp_proxy, n4_extra, env=env)
    # Proxy đã chặn: chờ tiến trình nhận ghi hết phần đã tới và xong mọi commit đã bắt đầu, để lô dở lúc
    # Ctrl+C đúng là phần dư của số khối đã nhận chia SYNC_EVERY (không còn lô thường xếp hàng trên đĩa).
    # Hạn ngắn hơn hẳn `IDLE_TIMEOUT` của kết nối dữ liệu (tự cắt thì lô dở bị đẩy trước Ctrl+C).
    wait_disk_quiet(trace, quiet=1.0, timeout=15.0)
    interrupt_at = time.perf_counter_ns()
    recv.interrupt()
    assert recv.finish(60) == 0, recv.err_text()
    exited_at = time.perf_counter_ns()
    with open(trace, "a", encoding="ascii") as f:  # tiến trình nhận đã thoát: không ghi chen
        f.write(f"{interrupt_at} INT\n")
    results = results_of(recv)
    assert [(r["result"], r["by_peer"]) for r in results] == [("suspended", False)], results
    assert recv.events()[-1]["event"] == "stopped"
    assert_clean_exit(recv)
    assert send.p.poll() is None, "send phải còn chờ nối lại"

    log = parse_disk_trace(trace)
    before = {i for c in log.commits if c.start < log.interrupt for i in c.blocks}
    unbatched = log.written - before

    def ms(ts: int | None) -> str:
        return "-" if ts is None else f"{(ts - log.interrupt) / 1e6:+.1f}ms"

    # Mỗi commit bắt đầu từ Ctrl+C trở đi: (số khối, kết quả, bắt đầu, kết thúc) so với mốc Ctrl+C.
    late = [
        (len(c.blocks), c.outcome, ms(c.start), ms(c.end)) for c in log.commits if c.start >= log.interrupt
    ]
    summary = (
        f"written={len(log.written)} committed_before_int={len(before)} unbatched={len(unbatched)} "
        f"commits_from_int={late} susp={[(s, ms(t)) for t, s in log.suspend]} exit={ms(exited_at)}"
    )
    assert log.written, f"hook không ghi được dòng nào (PYTHONPATH/cổng sai?): {summary}"
    assert unbatched, (
        "tiền đề 1e không đạt: mọi khối đã ghi đều thuộc một commit bắt đầu trước Ctrl+C, test không "
        f"kiểm được lô dở: {summary}"
    )

    state = read_state(net.recv / ".teleport" / tid / "0.state")
    marked = set(state.marks)
    assert state.size == N4_SIZE, state.size
    assert marked == log.written, (
        f"MARK ≠ khối đã ghi: thiếu {sorted(log.written - marked)}, thừa {sorted(marked - log.written)}; "
        f"{summary}"
    )
    data = src.read_bytes()
    bs = state.block_size
    wrong = [
        i for i in sorted(marked) if hashlib.sha256(data[i * bs : (i + 1) * bs]).digest() != state.marks[i]
    ]
    assert not wrong, f"hash MARK khác nguồn ở khối {wrong}"
    marked_bytes = sum(min(bs, N4_SIZE - i * bs) for i in marked)

    recv2 = restart_receive(net, procs, proxy, tid)
    done = recv2.restored["done_bytes"]
    assert done == marked_bytes, (done, marked_bytes, summary)
    assert n4_extra < done < N4_SIZE, (done, n4_extra, proxy.fired_forwarded)
    reconnect_through_proxy(proxy)
    excess = finish_send_and_receive(net, send, recv2, src, n4_extra)
    print(f"V5 ctrl-c: cut_c2s={proxy.fired_forwarded['c2s']} restored_done={done} excess_bytes={excess}")
    print(f"1e: {summary}")


# --- P3-5 V9: bên gửi khởi động lại -------------------------------------------------------------------------


def new_send_ends_old_transfer_as_unknown(net, procs, recv, port: int, tid: str, old: Path) -> None:
    """Một `send` mới (cùng thư mục cấu hình, file khác) tới `recv`: lượt mới xong; lượt cũ `tid` kết
    thúc ở `recv` bằng `unknown_transfer` (by_peer) với câu `UNKNOWN_TRANSFER`, thư mục tạm của nó bị
    xóa, không có file tên thật của nó."""
    new = make_file(net.src, "moi.bin", 3 * MiB + 5)
    send2 = procs(send_cmd(net, [new], port))
    assert send2.finish(90) == 0, f"{send2.out!r} {send2.err_text()}"
    assert [r["result"] for r in results_of(send2)] == ["done"], send2.out
    got: dict[str, dict] = {}
    while len(got) < 2:
        ev = recv.wait_json("result", 60)
        got[ev["transfer_id"]] = ev
    stale = got.pop(tid)
    assert (stale["result"], stale["by_peer"]) == ("unknown_transfer", True), stale
    assert stale["message"] == R_UNKNOWN.format(s=SENDER, file=old.name), stale
    [fresh] = got.values()
    assert fresh["result"] == "done", fresh
    poll(lambda: not (net.recv / ".teleport" / tid).exists(), 15, "thư mục tạm của lượt cũ chưa bị xóa")
    assert not (net.recv / old.name).exists()
    assert sha256_of(net.recv / new.name) == sha256_of(new)
    recv.interrupt()
    assert recv.finish(30) == 0, recv.err_text()
    assert_clean_exit(send2)
    assert_clean_exit(recv)


@pytest.mark.slow
def test_killed_send_then_new_send_receiver_drops_old_transfer_as_unknown(pair_dirs, procs):
    """V9 (i): `receive` vẫn chạy; `send` bị giết sau `MARK` đầu, rồi một `send` mới gửi file khác."""
    net = pair_dirs
    recv = procs(receive_cmd(net))
    port = recv.wait_json("receiving")["port"]
    old = make_file(net.src, "cu.bin", 24 * MiB)
    send1 = procs(send_cmd(net, [old], port, extra=["--limit-rate", "4M"]))
    tid = wait_status(recv, "transferring")["transfer_id"]
    poll(lambda: state_size(net, tid) > 41, 30, "chưa có MARK nào trong .state")
    send1.kill()
    wait_lock_free(net.S)
    new_send_ends_old_transfer_as_unknown(net, procs, recv, port, tid, old)


@pytest.mark.slow
def test_send_killed_while_receive_restored_then_new_send_drops_old_transfer_as_unknown(pair_dirs, procs):
    """V9 (ii): Ctrl+C `receive` (lượt tạm dừng), chạy lại `receive` (`restored`), `send` bị giết, rồi
    một `send` mới gửi file khác tới `receive` đang chạy lại."""
    net = pair_dirs
    recv = procs(receive_cmd(net))
    port = recv.wait_json("receiving")["port"]
    old = make_file(net.src, "cu.bin", 24 * MiB)
    send1 = procs(send_cmd(net, [old], port, extra=["--limit-rate", "4M"]))
    tid = wait_status(recv, "transferring")["transfer_id"]
    poll(lambda: state_size(net, tid) > 41, 30, "chưa có MARK nào trong .state")
    recv.interrupt()
    assert recv.finish(30) == 0, recv.err_text()
    assert [r["result"] for r in results_of(recv)] == ["suspended"], recv.out

    recv2 = procs(receive_cmd(net))
    port2 = recv2.wait_json("receiving")["port"]
    restored = recv2.wait_json("restored", 30)
    assert restored["transfer_id"] == tid, restored
    send1.kill()
    wait_lock_free(net.S)
    new_send_ends_old_transfer_as_unknown(net, procs, recv2, port2, tid, old)


# --- P3-5 V12c: câu (e) của `send` theo lịch thử lại thật ------------------------------------------------


@pytest.mark.slow
def test_text_send_prints_not_reconnected_sentence_once_on_real_retry_schedule(pair_dirs, procs, tcp_proxy):
    """V12c (spec-p3-5, N6 của mục 9.2): `send` bản text nối qua proxy; `receive` (JSON) bị Ctrl+C giữa
    lượt, proxy vẫn chuyển tiếp tới cổng đã đóng → mỗi lần thử: proxy accept rồi RST. Câu (e) in trong
    ≤ 60 s, đúng một lần kể cả sau ít nhất một lần thử hỏng nữa; không câu Wi-Fi. Chạy lại `receive` →
    `send` thoát 0, vẫn đúng một câu (e)."""
    net = pair_dirs
    recv = procs(receive_cmd(net))
    proxy = tcp_proxy(recv.wait_json("receiving")["port"])
    src = make_file(net.src, "lon.bin", 24 * MiB)
    send = procs(send_cmd(net, [src], proxy.port, extra=["--limit-rate", "4M"], json_mode=False))
    tid = wait_status(recv, "transferring")["transfer_id"]
    poll(lambda: state_size(net, tid) > 41, 30, "chưa có MARK nào trong .state")
    recv.interrupt()
    assert recv.finish(30) == 0, recv.err_text()
    assert [r["result"] for r in results_of(recv)] == ["suspended"], recv.out

    e_line = S_NOT_RECONNECTED_YET.format(p=RECEIVER)
    poll(lambda: e_line in text_of(send), 60, "send chưa in câu (e)")
    tried = proxy.accepted
    poll(lambda: proxy.accepted >= tried + 1, 60, "send không thử nối lại thêm lần nào sau câu (e)")
    poll(lambda: proxy.live() == 0, 15, "lần thử thêm chưa kết thúc")
    text = text_of(send)
    assert text.count(e_line) == 1, text
    assert WIFI_BLOCKING not in text, text
    assert send.p.poll() is None, "send phải còn chờ nối lại"

    recv2 = restart_receive(net, procs, proxy, tid)
    assert send.finish(120) == 0, f"{text_of(send)} {send.err_text()}"
    text = text_of(send)
    assert text.count(e_line) == 1, text
    assert WIFI_BLOCKING not in text, text
    res = recv2.wait_json("result", 60)
    assert res["result"] == "done", res
    assert sha256_of(net.recv / src.name) == sha256_of(src)
    recv2.interrupt()
    assert recv2.finish(30) == 0
    assert_clean_exit(send)
    assert_clean_exit(recv2)
