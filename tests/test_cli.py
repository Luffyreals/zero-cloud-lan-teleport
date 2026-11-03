import asyncio
import contextlib
import datetime
import hashlib
import io
import json
import logging
import os
import re
import secrets
import signal
import socket
import ssl
import struct
import sys
import threading
import time
import unicodedata

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from teleport import __version__
from teleport.cli import build_parser, main
from teleport.lock import NodeLock, NodeLockedError
from teleport.paths import ENV_HOME
from teleport.trust.identity import load_or_create_identity, peer_cert_from_pem
from teleport.trust.store import TrustStore


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_command_is_required(capsys):
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code == 2


def test_identity_is_created_once_and_stays_stable(tmp_path, capsys):
    assert main(["--config-dir", str(tmp_path), "identity"]) == 0
    first = capsys.readouterr().out
    assert main(["--config-dir", str(tmp_path), "identity"]) == 0
    assert capsys.readouterr().out == first
    assert "Fingerprint:" in first


def test_identity_uses_teleport_home(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(ENV_HOME, str(tmp_path))
    assert main(["identity"]) == 0
    assert str(tmp_path) in capsys.readouterr().out
    assert (tmp_path / "device.crt").exists()


def test_corrupt_identity_exits_1_with_message_not_traceback(tmp_path, capsys):
    assert main(["--config-dir", str(tmp_path), "identity"]) == 0
    (tmp_path / "device.crt").write_bytes(b"garbage")
    assert main(["--config-dir", str(tmp_path), "identity"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Lỗi: Danh tính thiết bị")
    assert "Traceback" not in err


# =================================================================================================
# PR-3: `listen`, `pair`, `unpair` (đặc tả PR-3 mục 2.6, 3.4, 3.7 và 4.7, CL1–CL15).
#
# Viết theo đặc tả: thông báo so nguyên văn với mục 3.4 / mvp mục 8; mã thoát 0/1/2; `--json`
# in JSON Lines (lệnh chạy lâu) hoặc một object (`unpair`). Các tên mới của `teleport.cli`
# (`run_listen`, `run_pair`, `StdinReader`) được import trong từng test để các test cũ ở trên vẫn
# chạy khi chúng chưa có.
# =================================================================================================

LOCAL = "127.0.0.1"
TIME_RE = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")
MVP_NOT_DONE = "Ghép đôi với {x} chưa xong. Nếu mã trên hai máy khác nhau, có thể có người đang giả mạo."
# `unpair` khi khóa node bận (spec-p2-8 mục B “8a”): cùng gợi ý như `send`/`receive` (mvp §8, dòng “CLI:
# `send` / `receive` khi một node khác đang chạy cùng thư mục cấu hình”), nhắc cả `receive` lẫn `listen`.
LOCKED = "Teleport đang chạy với thư mục cấu hình này"
# P4-3 (spec-p4-3 mục 5 M1 + mục 10): nhắc thêm lối thoát của GUI (menu khay).
LOCKED_HINT = (
    "Hãy dừng `teleport receive` hoặc `teleport listen` đang chạy, hoặc chọn Thoát trong menu khay của "
    "Teleport, rồi thử lại."
)
LOCKED_UNPAIR_OLD = "hãy dừng `teleport listen` trước"


def assert_unpair_locked_text(err: str) -> None:
    """Câu báo khóa bận của `unpair` (text, ra stderr): câu chính + đúng gợi ý của mvp §8."""
    assert err.startswith(f"Lỗi: {LOCKED}"), err
    assert LOCKED_HINT in err, err
    assert LOCKED_UNPAIR_OLD not in err, err
    assert "Traceback" not in err, err


BAD_ADDRESS = (  # PR-4 mục 3.10 (đổi theo mục 4.8)
    "“{target}” không phải địa chỉ IPv4 hợp lệ. Hãy nhập địa chỉ IP, ví dụ 192.168.1.5 hoặc "
    "192.168.1.5:47474, hoặc tên / mã thiết bị như `teleport list` hiện."
)
NODE_OPTS = ["--host", LOCAL, "--port", "0"]
CODE_LINE_RE = r"^Mã ghép đôi:   (\d{3} \d{3})$"  # H1: dòng mã chỉ gồm nhãn cố định và mã


def run_main(argv: list[str]) -> int:
    """`main(argv)`; lỗi argparse (SystemExit) cũng đổi thành mã thoát."""
    try:
        return main(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1


def run_main_guarded(argv: list[str], timeout: float = 15.0) -> int:
    """Như `run_main` nhưng trong thread có hạn chót: lệnh lẽ ra phải thoát ngay mà treo → test đỏ."""
    result: list[int] = []
    errors: list[BaseException] = []

    def target() -> None:
        try:
            result.append(run_main(argv))
        except BaseException as e:
            errors.append(e)

    t = threading.Thread(target=target, daemon=True, name="test-cli-main")
    t.start()
    t.join(timeout)
    assert not t.is_alive(), f"lệnh {argv} không thoát sau {timeout} s"
    if errors:
        raise errors[0]
    return result[0]


def lock_is_free(directory) -> bool:
    lock = NodeLock(directory)
    try:
        lock.acquire()
    except NodeLockedError:
        return False
    lock.release()
    return True


@pytest.fixture
def trusted_cfg(tmp_path):
    """Thư mục cấu hình có danh tính và 3 thiết bị tin cậy: "B", "pc", "PC" (hai tên sau trùng nhau)."""
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    store = TrustStore.load(d)
    ids = {}
    for label, name in (("B", "B"), ("C", "pc"), ("D", "PC")):
        ident = load_or_create_identity(tmp_path / f"peer-{label}")
        store.add(peer_cert_from_pem(ident.cert_pem()), name)
        ids[label] = ident.device_id
    return d, ids


# --- CL1–CL4: unpair (trong tiến trình, không socket) ---------------------------------------------


def test_cl1_unpair_by_name(trusted_cfg, capsys):
    d, ids = trusted_cfg
    assert run_main(["--config-dir", str(d), "unpair", "B"]) == 0
    out = capsys.readouterr().out
    assert f"Đã hủy ghép đôi với B ({ids['B'][:8]})." in out
    assert TrustStore.load(d).get(ids["B"]) is None
    assert len(TrustStore.load(d).devices()) == 2
    assert lock_is_free(d)


def test_cl1_unpair_json_prints_one_object(trusted_cfg, capsys):
    d, ids = trusted_cfg
    assert run_main(["--config-dir", str(d), "unpair", ids["B"][:6], "--json"]) == 0
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, captured.out
    obj = json.loads(lines[0])
    assert obj["removed"] is True
    assert obj["device_id"] == ids["B"]
    assert obj["name"] == "B"
    assert TIME_RE.match(obj["time"]), obj["time"]
    assert captured.err == ""


def test_cl2_unpair_not_found_lists_devices(trusted_cfg, capsys):
    d, ids = trusted_cfg
    before = (d / "trusted.json").read_bytes()
    assert run_main(["--config-dir", str(d), "unpair", "khong-co"]) == 1
    err = capsys.readouterr().err
    assert "Lỗi: Không có thiết bị tin cậy nào khớp “khong-co”." in err
    assert "Các thiết bị tin cậy:" in err
    for label, name in (("B", "B"), ("C", "pc"), ("D", "PC")):
        assert re.search(rf"^  {ids[label][:8]}  {name}$", err, re.M), err
    assert (d / "trusted.json").read_bytes() == before


def test_cl2_unpair_not_found_with_empty_store(tmp_path, capsys):
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    assert run_main(["--config-dir", str(d), "unpair", "B"]) == 1
    assert "(chưa ghép đôi với thiết bị nào)" in capsys.readouterr().err


def test_cl2_unpair_not_found_json(trusted_cfg, capsys):
    d, ids = trusted_cfg
    assert run_main(["--config-dir", str(d), "unpair", "khong-co", "--json"]) == 1
    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, captured.out
    obj = json.loads(lines[0])
    assert obj["error"] == "not_found"
    assert isinstance(obj["message"], str) and obj["message"]
    assert TIME_RE.match(obj["time"])
    assert {c["device_id"] for c in obj["candidates"]} == set(ids.values())
    assert all(set(c) == {"device_id", "name"} for c in obj["candidates"])
    assert captured.err == ""


def test_cl3_unpair_ambiguous_lists_full_ids(trusted_cfg, capsys):
    d, ids = trusted_cfg
    before = (d / "trusted.json").read_bytes()
    assert run_main(["--config-dir", str(d), "unpair", "Pc"]) == 1
    err = capsys.readouterr().err
    assert "Lỗi: “Pc” khớp nhiều thiết bị; hãy nhập mã thiết bị dài hơn:" in err
    assert re.search(rf"^  {ids['C']}  pc$", err, re.M), err
    assert re.search(rf"^  {ids['D']}  PC$", err, re.M), err
    assert ids["B"] not in err
    assert (d / "trusted.json").read_bytes() == before


def test_cl3_unpair_ambiguous_json(trusted_cfg, capsys):
    d, ids = trusted_cfg
    assert run_main(["--config-dir", str(d), "unpair", "pc", "--json"]) == 1
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["error"] == "ambiguous"
    assert sorted(c["device_id"] for c in obj["candidates"]) == sorted([ids["C"], ids["D"]])


def test_cl4_unpair_while_node_lock_held(trusted_cfg, capsys, monkeypatch):
    from teleport.app import node as node_mod

    monkeypatch.setattr(node_mod, "LOCK_TIMEOUT", 0.2)
    d, _ids = trusted_cfg
    before = (d / "trusted.json").read_bytes()
    holder = NodeLock(d)
    holder.acquire()
    try:
        t0 = time.monotonic()
        assert run_main(["--config-dir", str(d), "unpair", "B"]) == 1
        assert time.monotonic() - t0 < 2.0
        assert_unpair_locked_text(capsys.readouterr().err)
        assert run_main(["--config-dir", str(d), "unpair", "B", "--json"]) == 1
        obj = json.loads(capsys.readouterr().out.strip())
        assert obj["error"] == "node_locked"
    finally:
        holder.release()
    assert (d / "trusted.json").read_bytes() == before


def test_unpair_corrupt_store_exits_1(tmp_path, capsys):
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    (d / "trusted.json").write_bytes(b"rac")
    assert run_main(["--config-dir", str(d), "unpair", "B"]) == 1
    err = capsys.readouterr().err
    assert err.startswith("Lỗi: ")
    assert "Traceback" not in err
    assert (d / "trusted.json").read_bytes() == b"rac"


# --- Sửa F6/F7: thư mục cấu hình không dùng được ----------------------------------------------------

CONFIG_DIR_ERROR = "Không dùng được thư mục cấu hình"
PORT_ERROR = "Không mở được cổng để lắng nghe"


@pytest.fixture
def config_is_file(tmp_path):
    """`--config-dir` trỏ vào một file thường (không phải thư mục)."""
    f = tmp_path / "cfg-la-file"
    f.write_bytes(b"khong phai thu muc")
    return f


@pytest.mark.parametrize("command", ["listen", "pair"])
def test_node_command_with_config_dir_that_is_a_file_exits_1(config_is_file, capsys, command):
    """F6: lỗi thư mục cấu hình không bị báo nhầm là lỗi cổng; mã 1, không traceback."""
    target = [f"{LOCAL}:47474"] if command == "pair" else []
    argv = ["--config-dir", str(config_is_file), command, *target, "--name", "B", *NODE_OPTS]
    assert run_main_guarded(argv) == 1
    captured = capsys.readouterr()
    assert f"Lỗi: {CONFIG_DIR_ERROR} {config_is_file}" in captured.err, captured.err
    assert PORT_ERROR not in captured.err
    assert "Traceback" not in captured.err
    assert config_is_file.read_bytes() == b"khong phai thu muc"


def test_listen_with_config_dir_that_is_a_file_json(config_is_file, capsys):
    argv = ["--config-dir", str(config_is_file), "listen", "--json", "--name", "B", *NODE_OPTS]
    assert run_main_guarded(argv) == 1
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines() if line.strip()]
    assert len(events) == 1, captured.out
    obj = events[0]
    assert obj["event"] == "error"
    assert isinstance(obj["error"], str) and obj["error"] != "port_unavailable"
    assert CONFIG_DIR_ERROR in obj["message"]
    assert TIME_RE.match(obj["time"])
    assert "Traceback" not in captured.err


@pytest.mark.integration
def test_listen_on_busy_port_still_reports_port_error(tmp_path, capsys):
    """F6: lỗi mở cổng vẫn là câu về cổng (mục 3.7), không phải câu về thư mục cấu hình."""
    s = socket.socket()
    try:
        s.bind((LOCAL, 0))
        s.listen(1)
        busy = s.getsockname()[1]
        opts = ["--name", "B", "--host", LOCAL, "--port", str(busy)]
        argv = ["--config-dir", str(tmp_path / "B"), "listen", *opts]
        assert run_main_guarded(argv) == 1
    finally:
        s.close()
    err = capsys.readouterr().err
    assert f"Lỗi: {PORT_ERROR}" in err, err
    assert CONFIG_DIR_ERROR not in err
    assert "Traceback" not in err
    assert lock_is_free(tmp_path / "B")


@pytest.mark.parametrize("command", ["listen", "pair"])
def test_listen_and_pair_print_tray_hint_when_node_lock_held(tmp_path, capsys, monkeypatch, command):
    """P4-3 (spec-p4-3 mục 10, M1 phủ cả `listen`/`pair`): khóa node bận (ví dụ GUI đang chạy) → mã 1,
    câu khóa bận kèm đúng gợi ý M1 (nhắc menu khay), không traceback; khóa của bên giữ không bị đụng."""
    from teleport.app import node as node_mod

    monkeypatch.setattr(node_mod, "LOCK_TIMEOUT", 0.2)
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    target = [f"{LOCAL}:47474"] if command == "pair" else []
    holder = NodeLock(d)
    holder.acquire()
    try:
        argv = ["--config-dir", str(d), command, *target, "--name", "B", *NODE_OPTS]
        assert run_main_guarded(argv) == 1
        err = capsys.readouterr().err
        assert f"Lỗi: {LOCKED}" in err, err
        assert LOCKED_HINT in err, err
        assert "Traceback" not in err
        assert holder.held
    finally:
        holder.release()


@pytest.mark.parametrize("command", ["listen", "pair"])
def test_listen_and_pair_json_report_node_locked(tmp_path, capsys, monkeypatch, command):
    from teleport.app import node as node_mod

    monkeypatch.setattr(node_mod, "LOCK_TIMEOUT", 0.2)
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    target = [f"{LOCAL}:47474"] if command == "pair" else []
    with NodeLock(d):
        argv = ["--config-dir", str(d), command, *target, "--json", "--name", "B", *NODE_OPTS]
        assert run_main_guarded(argv) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert [e["error"] for e in events if e.get("event") == "error"] == ["node_locked"], events


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_unpair_with_config_dir_that_is_a_file_exits_1(config_is_file, capsys, json_mode):
    """F6: `unpair` bắt OSError → mã 1, không traceback; `--json` → một object `error`."""
    argv = ["--config-dir", str(config_is_file), "unpair", "B", *(["--json"] if json_mode else [])]
    assert run_main_guarded(argv) == 1
    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    if json_mode:
        obj = json.loads(captured.out.strip())
        assert isinstance(obj["error"], str) and obj["error"]
        assert isinstance(obj["message"], str) and obj["message"]
        assert captured.err == ""
    else:
        assert captured.err.startswith("Lỗi: "), captured.err
    assert config_is_file.read_bytes() == b"khong phai thu muc"


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_unpair_with_missing_config_dir_creates_nothing(tmp_path, capsys, json_mode):
    """F7: thư mục cấu hình chưa có → “không tìm thấy”, mã 1; không tạo thư mục hay `node.lock`."""
    d = tmp_path / "chua-co"
    argv = ["--config-dir", str(d), "unpair", "B", *(["--json"] if json_mode else [])]
    assert run_main_guarded(argv) == 1
    captured = capsys.readouterr()
    if json_mode:
        obj = json.loads(captured.out.strip())
        assert obj["error"] == "not_found"
        assert obj["candidates"] == []
    else:
        assert "Lỗi: Không có thiết bị tin cậy nào khớp “B”." in captured.err
        assert "(chưa ghép đôi với thiết bị nào)" in captured.err
    assert not d.exists()


# --- CL5, CL6: lỗi cú pháp → mã 2, không chạy node -------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "1.2.3.4:0",
        "::1",
        "1.2.3.4:65536",
        "0.0.0.0",
        "192.168.1",
        "1.2.3.4:080",
        "12.5",
        "fe80::1",
        "[::1]:80",
    ],
)
def test_cl5_pair_bad_address_exits_2_without_side_effects(tmp_path, capsys, address):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), "pair", address, *NODE_OPTS]) == 2
    assert BAD_ADDRESS.format(target=address) in capsys.readouterr().err
    assert not (d / "node.lock").exists()
    assert not (d / "settings.json").exists()
    assert not (d / "device.crt").exists()


def test_cl5_pair_bad_address_json(tmp_path, capsys):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), "pair", "1.2.3.4:0", "--json", *NODE_OPTS]) == 2
    captured = capsys.readouterr()
    obj = json.loads(captured.out.strip())
    assert obj["error"] == "invalid_address"
    assert captured.err == ""


@pytest.mark.parametrize("name", ["  x", "a\u202eb", "x" * 65])
def test_cl6_listen_bad_name_exits_2(tmp_path, capsys, name):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), "listen", "--name", name, *NODE_OPTS]) == 2
    assert "Tên thiết bị không hợp lệ" in capsys.readouterr().err
    assert not (d / "node.lock").exists()


@pytest.mark.parametrize(
    "extra",
    [
        ["--host", "localhost", "--port", "0"],
        ["--host", LOCAL, "--port", "70000"],
        ["--host", LOCAL, "--port", "x"],
    ],
)
def test_listen_bad_hidden_options_exit_2(tmp_path, extra):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), "listen", *extra]) == 2
    assert not (d / "node.lock").exists()


def test_hidden_options_are_not_in_help(capsys):
    for cmd in ("listen", "pair"):
        with pytest.raises(SystemExit):
            main([cmd, "--help"])
        out = capsys.readouterr().out
        assert "--host" not in out and "--port" not in out
        assert "--json" in out and "--name" in out


# --- Trong tiến trình, có socket (CL7–CL12) --------------------------------------------------------


# `fast_cli`, `cli_no_leaks`, `cli_runs` (`CliRun`) nằm ở tests/conftest.py (P2-7, spec-p2-7 mục A5).


def listen_argv(d, *, json_mode: bool = True, name: str = "B") -> list[str]:
    return ["--config-dir", str(d), "listen", *(["--json"] if json_mode else []), "--name", name, *NODE_OPTS]


def pair_argv(d, port: int, *, json_mode: bool = True, name: str = "A") -> list[str]:
    mode = ["--json"] if json_mode else []
    return ["--config-dir", str(d), "pair", f"{LOCAL}:{port}", *mode, "--name", name, *NODE_OPTS]


async def listen_port_text(run) -> int:
    await run.wait_text("Nhấn Ctrl+C để dừng.")
    m = re.search(r"Cổng:\s+(\d+)", run.text())
    assert m, run.text()
    return int(m.group(1))


socket_test = [
    pytest.mark.integration,
    pytest.mark.usefixtures("cli_no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
]


def with_marks(marks):
    def deco(fn):
        for mark in reversed(marks):
            fn = mark(fn)
        return fn

    return deco


@with_marks(socket_test)
async def test_cl7_listen_and_pair_json_end_to_end(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    assert TIME_RE.match(ev["time"])
    assert ev["name"] == "B"
    assert re.fullmatch(r"[0-9a-f]{32}", ev["device_id"])
    assert isinstance(ev["port"], int) and ev["port"] > 0
    assert ev["addresses"] == [LOCAL]

    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    pb = await listen.wait_event("pair_prompt")
    pa = await pair.wait_event("pair_prompt")
    assert re.fullmatch(r"[0-9]{6}", pa["code"]) and pa["code"] == pb["code"]
    for p, role, peer in ((pa, "initiator", "B"), (pb, "responder", "A")):
        assert p["role"] == role
        assert p["peer_name"] == peer
        assert re.fullmatch(r"[0-9a-f]{32}", p["peer_device_id"])
        assert p["address"] == LOCAL
        assert isinstance(p["expires_in"], float) and 0 < p["expires_in"] <= 2.0
        assert TIME_RE.match(p["time"])
        assert "session_id" in p
        assert p["known_name"] is None  # M5: chưa từng ghép đôi
    assert pa["peer_device_id"] == ev["device_id"]

    pair.say("c")
    listen.say("c")
    assert await asyncio.wait_for(pair.task, 10) == 0
    rb = await listen.wait_event("pair_result")
    ra = pair.events_of("pair_result")[0]
    for r, peer in ((ra, "B"), (rb, "A")):
        assert r["outcome"] == "paired"
        assert r["message"] == f"Đã ghép đôi với {peer}."
        assert r["peer_name"] == peer
        assert TIME_RE.match(r["time"])
        assert {"session_id", "role", "peer_device_id", "address"} <= set(r)
    assert TrustStore.load(tmp_path / "A").get(ev["device_id"]) is not None
    assert TrustStore.load(tmp_path / "B").get(pb["peer_device_id"]) is not None

    listen.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(listen.task, 10)
    assert lock_is_free(tmp_path / "B")
    assert lock_is_free(tmp_path / "A")
    assert listen.err.getvalue() == "" and pair.err.getvalue() == ""


@with_marks(socket_test)
async def test_cl8_text_mode_reject_messages(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=False))
    port = await listen_port_text(listen)
    head = listen.text()
    assert "Teleport đang chờ ghép đôi." in head
    assert re.search(r"Tên:\s+B$", head, re.M)
    assert re.search(r"Mã máy:\s+[0-9a-f]{8}$", head, re.M)
    assert re.search(r"Địa chỉ:\s+127\.0\.0\.1$", head, re.M)
    assert f"Trên máy kia, chạy: teleport pair 127.0.0.1:{port}" in head

    pair = cli_runs("pair", pair_argv(tmp_path / "A", port, json_mode=False))
    await pair.wait_text("Trùng khớp? [c/k]:")
    await listen.wait_text("Trùng khớp? [c/k]:")
    assert f"Đang kết nối tới 127.0.0.1:{port}…" in pair.text()
    # H1 (mvp mục 7.2): mã đứng riêng một dòng, tên máy kia ở dòng sau, trong ngoặc.
    assert re.search(r"^Máy kia tự xưng là “B” \(mã máy [0-9a-f]{8}, 127\.0\.0\.1\)\.$", pair.text(), re.M)
    assert re.search(r"^Máy kia tự xưng là “A” \(mã máy [0-9a-f]{8}, 127\.0\.0\.1\)\.$", listen.text(), re.M)
    codes_a = re.findall(CODE_LINE_RE, pair.text(), re.M)
    codes_b = re.findall(CODE_LINE_RE, listen.text(), re.M)
    assert len(codes_a) == 1 and codes_a == codes_b, (pair.text(), listen.text())

    pair.say("k")
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert MVP_NOT_DONE.format(x="B") in pair.text()
    await listen.wait_text(MVP_NOT_DONE.format(x="A"))
    await listen.wait_text("Tiếp tục chờ ghép đôi…")


@with_marks(socket_test)
async def test_listen_cancelled_while_asking_does_not_say_keep_waiting(tmp_path, fast_cli, cli_runs):
    """Sửa F9: Ctrl+C (hủy task) khi `listen` đang hỏi → in “Đã hủy ghép đôi.” nhưng không in
    “Tiếp tục chờ ghép đôi…” (node đang đóng, không chờ tiếp)."""
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=False))
    port = await listen_port_text(listen)
    pair = cli_runs("pair", pair_argv(tmp_path / "A", port))
    await listen.wait_text("Trùng khớp? [c/k]:")
    await pair.wait_event("pair_prompt")

    listen.task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(listen.task, 10)
    after_prompt = listen.text().split("Trùng khớp? [c/k]:", 1)[1]
    assert "Đã hủy ghép đôi." in after_prompt
    assert "Tiếp tục chờ ghép đôi" not in listen.text(), after_prompt
    assert lock_is_free(tmp_path / "B")
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert pair.events_of("pair_result")[0]["outcome"] == "peer_rejected"


@with_marks(socket_test)
async def test_cl9_line_typed_before_prompt_is_ignored(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    t_before = time.perf_counter()
    listen.say("c", ts=t_before)  # gõ sẵn trước khi có lời hỏi
    await asyncio.sleep(0.05)

    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt")
    await pair.wait_event("pair_prompt")
    listen.say("c", ts=t_before)  # dòng đọc trước lúc hiện mã nhưng tới hàng đợi muộn
    await asyncio.sleep(0.1)
    pair.say("c")
    await asyncio.sleep(0.1)
    assert listen.events_of("pair_result") == [], "dòng gõ trước lúc hiện mã đã được dùng để xác nhận"
    listen.say("k")
    assert await asyncio.wait_for(pair.task, 10) == 1
    rb = await listen.wait_event("pair_result")
    assert rb["outcome"] == "user_rejected"
    assert TrustStore.load(tmp_path / "B").devices() == []
    assert pair.events_of("pair_result")[0]["outcome"] == "peer_rejected"


@with_marks(socket_test)
@pytest.mark.parametrize("before", [0.001, 0.0002], ids=["1ms", "0.2ms"])
async def test_line_read_just_before_prompt_is_ignored(tmp_path, fast_cli, cli_runs, monkeypatch, before):
    """Sửa F2: dòng đọc **trước** lúc hiện mã dù chỉ 1 ms (hoặc ít hơn) cũng bị bỏ.

    Trên Python 3.12 Windows `time.monotonic()` chỉ chính xác 15,6 ms nên dòng như vậy từng được
    nhận. Hợp đồng mới: mốc đọc và mốc hiện mã đều là `time.perf_counter()`, so bằng `<`. Test
    ghi `perf_counter()` ngay **trước** khi lời hỏi được giao cho CLI, nên mốc hiện mã ≥ mốc đó.
    """
    from teleport import cli

    called_at: dict[str, float] = {}  # vai → perf_counter() ngay trước khi CLI nhận lời hỏi
    real_on_prompt = cli._Prompter.on_prompt

    def on_prompt(self, prompt):
        called_at[prompt.role.value] = time.perf_counter()
        return real_on_prompt(self, prompt)

    monkeypatch.setattr(cli._Prompter, "on_prompt", on_prompt)

    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt")
    await pair.wait_event("pair_prompt")
    assert set(called_at) == {"initiator", "responder"}
    listen.say("c", ts=called_at["responder"] - before)  # `listen` là bên trả lời
    pair.say("c")
    await asyncio.sleep(0.3)
    assert listen.events_of("pair_result") == [], "dòng đọc trước lúc hiện mã đã được dùng để xác nhận"
    assert TrustStore.load(tmp_path / "B").devices() == []

    listen.say("k")  # dòng đọc sau lúc hiện mã vẫn được nhận
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert (await listen.wait_event("pair_result"))["outcome"] == "user_rejected"


@pytest.mark.slow
@with_marks(socket_test)
async def test_cl10_answer_after_prompt_expired_does_nothing(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await pair.wait_event("pair_prompt")
    await listen.wait_event("pair_prompt")
    pair.say("c")
    assert await asyncio.wait_for(pair.task, 10) == 1
    rb = await listen.wait_event("pair_result", timeout=2.0 + 0.5 + 2.5)
    assert rb["outcome"] == "timeout"
    assert rb["message"] == MVP_NOT_DONE.format(x="A")

    n_events = len(listen.events())
    listen.say("c")
    await asyncio.sleep(0.3)
    assert len(listen.events()) == n_events
    assert not listen.task.done()
    assert TrustStore.load(tmp_path / "B").devices() == []
    assert listen.err.getvalue() == ""


@pytest.mark.slow
@with_marks(socket_test)
async def test_cl11_stdin_eof_rejects_immediately_and_later(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt")
    await pair.wait_event("pair_prompt")
    t0 = time.monotonic()
    listen.say(None)
    rb = await listen.wait_event("pair_result", timeout=1.0)
    assert time.monotonic() - t0 < 1.0
    assert rb["outcome"] == "user_rejected"
    assert await asyncio.wait_for(pair.task, 10) == 1

    # Lời hỏi sau cũng bị từ chối ngay (stdin đã đóng). Chờ hết thời gian chờ 0,5 s của IP trước.
    await asyncio.sleep(0.7)
    pair2 = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt", n=2)
    t1 = time.monotonic()
    rb2 = await listen.wait_event("pair_result", n=2, timeout=1.0)
    assert time.monotonic() - t1 < 1.0
    assert rb2["outcome"] == "user_rejected"
    assert await asyncio.wait_for(pair2.task, 10) == 1


@with_marks(socket_test)
async def test_cl12_invalid_answer_prints_hint(tmp_path, fast_cli, cli_runs):
    hint = "Hãy gõ c (trùng) hoặc k (không trùng)."
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=False))
    port = await listen_port_text(listen)
    pair = cli_runs("pair", pair_argv(tmp_path / "A", port))
    await listen.wait_text("Trùng khớp? [c/k]:")
    await pair.wait_event("pair_prompt")
    listen.say("x")
    await listen.wait_text(hint)
    listen.say("có")  # chỉ nhận câu trả lời ASCII
    await listen.wait_text(hint, n=2)
    pair.say("c")
    listen.say("  YES ")
    assert await asyncio.wait_for(pair.task, 10) == 0
    await listen.wait_text("Đã ghép đôi với A.")


@with_marks(socket_test)
async def test_cl12_json_mode_invalid_answer_is_silent(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    pair = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt")
    await pair.wait_event("pair_prompt")
    listen.say("x")
    await asyncio.sleep(0.2)
    assert "Hãy gõ" not in listen.text()
    for line in listen.out.getvalue().splitlines():
        json.loads(line)  # chỉ có JSON Lines trên stdout
    listen.say("No")
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert (await listen.wait_event("pair_result"))["outcome"] == "user_rejected"


@pytest.mark.slow
@with_marks(socket_test)
async def test_pair_unreachable_message(tmp_path, fast_cli, cli_runs):
    s = socket.socket()
    s.bind((LOCAL, 0))
    port = s.getsockname()[1]
    s.close()
    pair = cli_runs("pair", pair_argv(tmp_path / "A", port, json_mode=False))
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert (
        f"Không kết nối được tới 127.0.0.1:{port}. Hãy kiểm tra Teleport đang chạy trên máy đó, "
        "hai máy dùng chung một mạng, và tường lửa cho phép Teleport."
    ) in pair.text()


@with_marks(socket_test)
async def test_pair_peer_busy_message(tmp_path, fast_cli, cli_runs):
    """`peer_busy` (mục 3.4): máy kia đang ghép đôi với máy khác → câu mvp 8 + gợi ý `teleport listen`."""
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    first = cli_runs("pair", pair_argv(tmp_path / "A", ev["port"]))
    await listen.wait_event("pair_prompt")
    await first.wait_event("pair_prompt")
    second = cli_runs("pair", pair_argv(tmp_path / "C", ev["port"], json_mode=False, name="C"))
    assert await asyncio.wait_for(second.task, 10) == 1
    text = second.text()
    assert (
        "B chưa sẵn sàng ghép đôi: máy đó đang ẩn, đang ghép đôi với máy khác, "
        "chưa mở chế độ chờ ghép đôi, hoặc cần chờ một lát sau lần thử trước. Hãy thử lại sau."
    ) in text
    assert "Trên máy đó, hãy chạy: `teleport listen`" in text
    first.say("k")
    assert await asyncio.wait_for(first.task, 10) == 1


@with_marks(socket_test)
async def test_pair_with_self_message(tmp_path, fast_cli, cli_runs):
    """`self` (mục 3.4): `pair` tới chính cổng node của nó."""
    s = socket.socket()
    s.bind((LOCAL, 0))
    port = s.getsockname()[1]
    s.close()
    argv = ["--config-dir", str(tmp_path / "A"), "pair", f"{LOCAL}:{port}", "--name", "A"]
    pair = cli_runs("pair", [*argv, "--host", LOCAL, "--port", str(port)])
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert "Đó là chính máy này. Hãy nhập địa chỉ của máy kia." in pair.text()


# --- Subprocess (CL13–CL15) ----------------------------------------------------------------------------


# `procs` (`Proc`) nằm ở tests/conftest.py (P2-7, spec-p2-7 mục A5).


def listen_cmd(d) -> list[str]:
    return ["--config-dir", str(d), "listen", "--json", "--name", "B", *NODE_OPTS]


def pair_cmd(d, port: int, *, json_mode: bool = True) -> list[str]:
    mode = ["--json"] if json_mode else []
    return ["--config-dir", str(d), "pair", f"{LOCAL}:{port}", *mode, "--name", "A", *NODE_OPTS]


@pytest.mark.slow
@pytest.mark.integration
def test_cl13_subprocess_end_to_end(tmp_path, procs):
    listen = procs(listen_cmd(tmp_path / "B"))
    ev = listen.wait_json("listening")
    pair = procs(pair_cmd(tmp_path / "A", ev["port"]))
    pa = pair.wait_json("pair_prompt")
    pb = listen.wait_json("pair_prompt")
    assert pa["code"] == pb["code"]
    pair.write("c\n")
    listen.write("c\n")
    assert pair.finish(30) == 0, pair.err_text()
    assert listen.wait_json("pair_result")["outcome"] == "paired"
    assert TrustStore.load(tmp_path / "A").get(ev["device_id"]) is not None
    assert (tmp_path / "B" / "trusted.json").exists()
    assert len(TrustStore.load(tmp_path / "B").devices()) == 1
    listen.interrupt()
    assert listen.finish(30) == 0


@pytest.mark.slow
@pytest.mark.integration
def test_cl14_interrupt_stops_listen_cleanly(tmp_path, procs):
    d = tmp_path / "B"
    listen = procs(listen_cmd(d))
    listen.wait_json("listening")
    time.sleep(0.3)  # để thread đọc stdin đã chặn trong os.read
    listen.interrupt()
    code = listen.finish(30)
    err = listen.err_text()
    assert code == 0, err
    last = json.loads([line for line in listen.out if line.strip()][-1])
    assert last["event"] == "stopped"
    assert TIME_RE.match(last["time"])
    lock = NodeLock(d)
    lock.acquire(timeout=2)
    lock.release()
    assert "Fatal Python error" not in err
    assert "Traceback" not in err


@pytest.mark.slow
@pytest.mark.integration
def test_cl14_interrupt_while_prompt_is_open(tmp_path, procs):
    """3.9 mục 2: Ctrl+C khi đang hỏi → listen thoát 0, máy kia nhận pair_abort{user}."""
    listen = procs(listen_cmd(tmp_path / "B"))
    ev = listen.wait_json("listening")
    pair = procs(pair_cmd(tmp_path / "A", ev["port"]))
    pair.wait_json("pair_prompt")
    listen.wait_json("pair_prompt")
    listen.interrupt()
    assert listen.finish(30) == 0
    result = pair.wait_json("pair_result")
    assert result["outcome"] == "peer_rejected"
    assert pair.finish(30) == 1
    err = listen.err_text()
    assert "Fatal Python error" not in err and "Traceback" not in err


@pytest.mark.slow
@pytest.mark.integration
def test_cl14_interrupt_pair_while_waiting(tmp_path, procs):
    """`pair` bị Ctrl+C khi đang chờ người dùng → in “Đã hủy ghép đôi.”, mã 1; máy kia PEER_REJECTED."""
    listen = procs(listen_cmd(tmp_path / "B"))
    ev = listen.wait_json("listening")
    pair = procs(pair_cmd(tmp_path / "A", ev["port"], json_mode=False))
    listen.wait_json("pair_prompt")
    time.sleep(0.3)
    pair.interrupt()
    assert pair.finish(30) == 1
    text = "\n".join(pair.out) + pair.err_text()
    assert "Đã hủy ghép đôi." in text
    assert "Traceback" not in text and "Fatal Python error" not in text
    assert listen.wait_json("pair_result")["outcome"] == "peer_rejected"


@pytest.mark.slow
@pytest.mark.integration
def test_cl15_unpair_while_listen_runs(tmp_path, procs, capsys, monkeypatch):
    from teleport.app import node as node_mod

    monkeypatch.setattr(node_mod, "LOCK_TIMEOUT", 0.2)
    d = tmp_path / "B"
    listen = procs(listen_cmd(d))
    listen.wait_json("listening")
    assert run_main(["--config-dir", str(d), "unpair", "B"]) == 1
    assert_unpair_locked_text(capsys.readouterr().err)
    listen.interrupt()
    assert listen.finish(30) == 0


@pytest.mark.slow
@pytest.mark.integration
def test_unpair_while_receive_runs_names_receive_and_listen(tmp_path, procs, capsys, monkeypatch):
    """spec-p2-8 mục B “8a”: `teleport receive` đang giữ khóa → `unpair` mã 1, gợi ý nhắc cả
    `teleport receive` lẫn `teleport listen`; `--json` → `error` `node_locked`; trusted.json không đổi;
    `receive` chạy tiếp."""
    from teleport.app import node as node_mod

    monkeypatch.setattr(node_mod, "LOCK_TIMEOUT", 0.2)
    d = tmp_path / "B"
    load_or_create_identity(d)
    peer = load_or_create_identity(tmp_path / "peer-B")
    TrustStore.load(d).add(peer_cert_from_pem(peer.cert_pem()), "B")
    before = (d / "trusted.json").read_bytes()
    recv_dir = tmp_path / "nhan"
    receive = procs(
        [
            "--config-dir",
            str(d),
            "receive",
            "--json",
            "--yes",
            "--dir",
            str(recv_dir),
            "--name",
            "R",
            *NODE_OPTS,
        ]
    )
    receive.wait_json("receiving")
    assert run_main(["--config-dir", str(d), "unpair", "B"]) == 1
    assert_unpair_locked_text(capsys.readouterr().err)
    assert run_main(["--config-dir", str(d), "unpair", "B", "--json"]) == 1
    obj = json.loads(capsys.readouterr().out.strip())
    assert obj["error"] == "node_locked"
    assert (d / "trusted.json").read_bytes() == before
    assert receive.p.poll() is None, "receive phải chạy tiếp"
    receive.interrupt()
    assert receive.finish(30) == 0


# --- StdinReader (mục 2.6, 0 điểm 12) -------------------------------------------------------------------


async def test_stdin_reader_without_stdin_sends_eof(monkeypatch):
    from teleport.cli import StdinReader

    monkeypatch.setattr(sys, "stdin", None)
    lines: asyncio.Queue = asyncio.Queue()
    StdinReader(asyncio.get_running_loop(), lines).start()
    ts, line = await asyncio.wait_for(lines.get(), 2)
    assert line is None
    assert isinstance(ts, float)


def _stdin_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "teleport-stdin"]


async def test_stdin_reader_reads_lines_from_pipe(monkeypatch):
    from teleport.cli import StdinReader

    r, w = os.pipe()
    fake_stdin = os.fdopen(r, "rb", buffering=0)
    try:
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        lines: asyncio.Queue = asyncio.Queue()
        t0 = time.perf_counter()
        StdinReader(asyncio.get_running_loop(), lines).start()
        threads = _stdin_threads()
        assert threads and all(t.daemon for t in threads)
        os.write(w, b"c\nx y\n\xff\n" + "không\n".encode())
        os.close(w)
        w = None
        got = []
        while True:
            ts, line = await asyncio.wait_for(lines.get(), 3)
            got.append((ts, line))
            if line is None:
                break
        assert [line for _, line in got] == ["c", "x y", "\ufffd", "không", None]
        stamps = [ts for ts, _ in got]
        # Mốc là `time.perf_counter()` lúc đọc (sửa F2): nằm giữa lúc bắt đầu và bây giờ.
        assert stamps == sorted(stamps) and stamps[0] >= t0
        assert stamps[-1] <= time.perf_counter()
        for t in threads:
            t.join(2)
            assert not t.is_alive()
    finally:
        if w is not None:
            os.close(w)
        fake_stdin.close()


async def test_stdin_reader_queue_is_bounded(monkeypatch):
    from teleport.cli import StdinReader

    r, w = os.pipe()
    fake_stdin = os.fdopen(r, "rb", buffering=0)
    try:
        monkeypatch.setattr(sys, "stdin", fake_stdin)
        lines: asyncio.Queue = asyncio.Queue()
        StdinReader(asyncio.get_running_loop(), lines).start()
        threads = _stdin_threads()
        os.write(w, b"".join(f"{i}\n".encode() for i in range(300)))
        os.close(w)
        w = None
        deadline = time.monotonic() + 5
        while any(t.is_alive() for t in threads) and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        await asyncio.sleep(0.05)
        assert lines.qsize() <= 101
        assert lines.get_nowait()[1] == "0"
    finally:
        if w is not None:
            os.close(w)
        fake_stdin.close()


# =================================================================================================
# PR-4: `identity` (cổng, thư mục là file), `list`, `pair <tên>`, `listen` với mDNS
# (đặc tả PR-4 mục 2.7, 3.10, 4.8: CL16–CL30). `MdnsDiscovery` được thay bằng bản giả: fixture của
# tests/app/conftest.py không dùng được ở đây (mỗi thư mục một conftest), nên bản giả gọn được chép lại.
# =================================================================================================

MVP_NO_DEVICES = (
    "Chưa thấy thiết bị nào. Hãy mở Teleport trên máy kia và kiểm tra hai máy dùng chung một mạng Wi-Fi."
)
MVP_REINSTALL = "Có một {x} mới chưa ghép đôi. Nếu máy đó vừa cài lại Teleport, hãy ghép đôi lại."
MVP_SEEN_UNREACHABLE = (
    "Thấy {x} nhưng không kết nối được. Mạng Wi-Fi này có thể đang chặn các thiết bị nói chuyện với nhau "
    "(hay gặp ở quán cà phê, khách sạn)."
)
HOTSPOT_HINT = (
    "Hãy thử dùng điểm phát Wi-Fi từ điện thoại, và kiểm tra tường lửa trên máy kia đã cho phép Teleport."
)
MVP_REJECTED = "{x} từ chối kết nối từ máy này. Có thể máy đó đã hủy ghép đôi."
MVP_IDENTITY = (
    "{x} đang dùng một danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy này. "
    "Kết nối đã bị chặn."
)
MDNS_OFF = (
    "Không tìm được thiết bị theo tên vì khám phá mDNS đang tắt. "
    "Hãy nhập địa chỉ IP: teleport pair <ip[:cổng]>"
)
MDNS_HINT = "Nếu mạng chặn mDNS, hãy nhập địa chỉ IP: teleport pair <ip[:cổng]>"
LISTEN_DISCOVERY = "Máy khác trong mạng thấy máy này qua `teleport list` và tự kết nối nếu đã ghép đôi."
MDNS_OPTS = ["--mdns-interface", LOCAL]


def new_identity(directory):
    return load_or_create_identity(directory)


def discovered(device_id: str, name: str, port: int, *, addresses=(LOCAL,), os: str = "windows"):
    from teleport.core.discovery import DiscoveredDevice
    from teleport.core.messages import PROTOCOL_VERSION

    return DiscoveredDevice(
        device_id=device_id, name=name, os=os, proto=PROTOCOL_VERSION, port=port, addresses=tuple(addresses)
    )


# `cli_mdns` (mDNS giả) nằm ở tests/conftest.py (P2-7, spec-p2-7 mục A5).


@pytest.fixture
def open_control_calls(monkeypatch):
    """Đếm lời gọi `teleport.app.node.open_control` (node tự mở kết nối điều khiển)."""
    from teleport.app import node as node_mod

    calls: list = []
    real = node_mod.open_control

    async def counting(*args, **kwargs):
        calls.append(args)
        return await real(*args, **kwargs)

    monkeypatch.setattr(node_mod, "open_control", counting)
    return calls


@pytest.fixture
def fast_links(fast_cli, monkeypatch):
    """`fast_cli` + hằng của `teleport.core.links` và `NETWORK_CHECK_INTERVAL` (như `fast` của tests/app)."""
    from teleport.app import node as node_mod
    from teleport.core import links

    for name, value in {
        "RETRY_BASE": 0.2,
        "RETRY_MAX": 1.0,
        "EVENT_RETRY_GAP": 0.2,
        "REPLACE_AFTER": 2.0,
    }.items():
        monkeypatch.setattr(links, name, value)
    monkeypatch.setattr(node_mod, "NETWORK_CHECK_INTERVAL", 0.2)


@pytest.fixture
def browse_fast(monkeypatch):
    from teleport import cli

    monkeypatch.setattr(cli, "_PAIR_BROWSE_TIMEOUT", 0.3)


async def run_list_capture(argv: list[str]) -> tuple[int, str, str]:
    from teleport.cli import run_list

    out, err = io.StringIO(), io.StringIO()
    code = await asyncio.wait_for(run_list(build_parser().parse_args(argv), out, err), 15)
    return code, out.getvalue(), err.getvalue()


def list_argv(d, *extra: str) -> list[str]:
    return ["--config-dir", str(d), "list", *MDNS_OPTS, "--timeout", "0.3", *extra]


def name_pair_argv(d, target: str, *, json_mode: bool = False, name: str = "A") -> list[str]:
    mode = ["--json"] if json_mode else []
    return ["--config-dir", str(d), "pair", target, *mode, "--name", name, *NODE_OPTS, *MDNS_OPTS]


def mdns_listen_argv(d, *, json_mode: bool = True, name: str = "A") -> list[str]:
    mode = ["--json"] if json_mode else []
    return ["--config-dir", str(d), "listen", *mode, "--name", name, *NODE_OPTS, *MDNS_OPTS]


# --- CL16, CL17: identity ------------------------------------------------------------------------------


def test_cl16_identity_with_config_dir_that_is_a_file(config_is_file, capsys):
    assert run_main_guarded(["--config-dir", str(config_is_file), "identity"]) == 1
    captured = capsys.readouterr()
    assert f"Lỗi: {CONFIG_DIR_ERROR} {config_is_file}" in captured.err, captured.err
    assert "Traceback" not in captured.err + captured.out
    assert config_is_file.read_bytes() == b"khong phai thu muc"


def test_cl17_identity_shows_port(tmp_path, capsys):
    d = tmp_path / "cfg"
    assert run_main(["--config-dir", str(d), "identity"]) == 0
    assert re.search(r"^Cổng:\s+47474$", capsys.readouterr().out, re.M)
    from teleport.app.settings import Settings

    Settings(port=47480).save(d)
    assert run_main(["--config-dir", str(d), "identity"]) == 0
    out = capsys.readouterr().out
    assert re.search(r"^Cổng:\s+47480$", out, re.M), out
    assert "Fingerprint:" in out


# --- CL18: tham số của list ----------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["0", "abc", "61", "nan", "inf", "-1", "60.5"])
def test_cl18_list_bad_timeout_exits_2(tmp_path, value):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), "list", "--timeout", value]) == 2
    assert not d.exists() or not (d / "node.lock").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["list", "--mdns-interface", "localhost"],
        ["list", "--mdns-interface", "1.2.3"],
        ["listen", "--mdns-interface", "::1", *NODE_OPTS],
        ["listen", "--advertise-address", "192.168.1", *NODE_OPTS],
        ["pair", "B", "--mdns-interface", "x", *NODE_OPTS],
    ],
)
def test_hidden_mdns_options_must_be_ipv4(tmp_path, argv):
    d = tmp_path / "cfg"
    assert run_main_guarded(["--config-dir", str(d), *argv]) == 2
    assert not (d / "node.lock").exists()


def test_list_help_hides_mdns_options(capsys):
    with pytest.raises(SystemExit):
        main(["list", "--help"])
    out = capsys.readouterr().out
    assert "--timeout" in out and "--json" in out
    assert "--mdns-interface" not in out
    with pytest.raises(SystemExit):
        main(["listen", "--help"])
    out = capsys.readouterr().out
    assert "--mdns-interface" not in out and "--advertise-address" not in out


# --- CL19–CL22: list (FakeMdns, không socket TCP) ------------------------------------------------------


@pytest.fixture
def list_cfg(tmp_path):
    """Máy này + B (đã ghép đôi, thấy), C (chưa ghép đôi, thấy), D (đã ghép đôi, không thấy)."""
    d = tmp_path / "cfg"
    me = load_or_create_identity(d)
    peers = {k: load_or_create_identity(tmp_path / f"peer-{k}") for k in "BCD"}
    store = TrustStore.load(d)
    store.add(peer_cert_from_pem(peers["B"].cert_pem()), "B")
    store.add(peer_cert_from_pem(peers["D"].cert_pem()), "D")
    seed = {
        peers["B"].device_id: discovered(
            peers["B"].device_id, "B-ten-txt", 47474, addresses=("192.0.2.10", "192.0.2.11")
        ),
        peers["C"].device_id: discovered(
            peers["C"].device_id, "C", 50000, addresses=("192.0.2.20",), os="macos"
        ),
    }
    return d, me, peers, seed


async def test_cl19_list_text(list_cfg, cli_mdns):
    from teleport.app.node import default_device_name
    from teleport.core.display import display_name

    d, me, peers, seed = list_cfg
    cli_mdns.seed = seed
    code, out, err = await run_list_capture(list_argv(d))
    assert code == 0, err
    b8, c8, d8 = (peers[k].device_id[:8] for k in "BCD")
    lines = out.splitlines()
    # Tên máy này lấy từ hostname, có thể dài hơn giới hạn hiện của `display_name` (máy macOS của CI).
    assert f"Máy này: {display_name(default_device_name(me))} ({me.device_id[:8]}), cổng 47474" in lines, out
    i = lines.index("Thiết bị trong mạng:")
    assert lines[i + 1] == f"  B  {b8}  Windows  đã ghép đôi  192.0.2.10:47474, 192.0.2.11:47474", out
    assert lines[i + 2] == f"  C  {c8}  macOS  chưa ghép đôi  192.0.2.20:50000", out
    j = lines.index("Thiết bị đã ghép đôi nhưng không thấy trong mạng:")
    assert j > i + 2
    assert lines[j + 1] == f"  D  {d8}", out
    assert "B-ten-txt" not in out, "tên mDNS không được thay tên đã ghép đôi"
    m = cli_mdns.last
    assert "advertise" not in m.calls, "list không được quảng bá"
    assert m.closing
    assert not (d / "node.lock").exists(), "list không được đụng node.lock"
    assert lock_is_free(d)


async def test_cl20_list_json_single_object(list_cfg, cli_mdns):
    d, me, peers, seed = list_cfg
    cli_mdns.seed = seed
    code, out, err = await run_list_capture(list_argv(d, "--json"))
    assert code == 0 and err == ""
    lines = [line for line in out.splitlines() if line.strip()]
    assert len(lines) == 1, out
    obj = json.loads(lines[0])
    assert TIME_RE.match(obj["time"]), obj["time"]
    assert obj["self"]["device_id"] == me.device_id
    assert obj["self"]["port"] == 47474
    assert isinstance(obj["self"]["name"], str) and obj["self"]["name"]
    devs = {x["device_id"]: x for x in obj["devices"]}
    assert set(devs) == {peers[k].device_id for k in "BCD"}
    keys = {"device_id", "name", "os", "paired", "online", "addresses", "port"}
    assert all(set(x) == keys for x in obj["devices"]), obj["devices"]
    b, c, dd = (devs[peers[k].device_id] for k in "BCD")
    assert b == {
        "device_id": peers["B"].device_id,
        "name": "B",
        "os": "windows",
        "paired": True,
        "online": True,
        "addresses": ["192.0.2.10", "192.0.2.11"],
        "port": 47474,
    }
    assert (c["paired"], c["online"], c["os"], c["port"]) == (False, True, "macos", 50000)
    assert (dd["paired"], dd["online"], dd["os"], dd["addresses"], dd["port"]) == (
        True,
        False,
        None,
        [],
        None,
    )


async def test_cl21_list_nothing_seen(tmp_path, cli_mdns):
    code, out, err = await run_list_capture(list_argv(tmp_path / "cfg"))
    assert code == 0, err
    assert MVP_NO_DEVICES in out
    assert "Thiết bị trong mạng:" not in out
    assert "không thấy trong mạng" not in out


async def test_cl21_list_reinstall_hint(tmp_path, cli_mdns):
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    old = load_or_create_identity(tmp_path / "cu")
    new = load_or_create_identity(tmp_path / "moi")
    TrustStore.load(d).add(peer_cert_from_pem(old.cert_pem()), "PC-Nha")
    cli_mdns.seed = {new.device_id: discovered(new.device_id, "PC-Nha", 47474, addresses=("192.0.2.30",))}
    code, out, err = await run_list_capture(list_argv(d))
    assert code == 0, err
    assert MVP_REINSTALL.format(x="PC-Nha") in out, out
    assert "*" not in out


async def test_list_shows_invisible_name_chars_as_dots(tmp_path, cli_mdns):
    """Tên máy có ký tự trông như khoảng trắng (U+3164) hiện thành `·` ở `list`, như ở `listen`
    (mvp mục 7.2); JSON giữ tên gốc."""
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    peer = load_or_create_identity(tmp_path / "la")
    name = "PC-Nhaㅤ"
    cli_mdns.seed = {peer.device_id: discovered(peer.device_id, name, 47474, addresses=("192.0.2.30",))}
    code, out, err = await run_list_capture(list_argv(d))
    assert code == 0, err
    assert f"  PC-Nha·  {peer.device_id[:8]}  " in out, out
    assert "ㅤ" not in out
    code, out, err = await run_list_capture(list_argv(d, "--json"))
    assert code == 0, err
    assert [x["name"] for x in json.loads(out)["devices"]] == [name]


def test_unpair_shows_invisible_name_chars_as_dots(tmp_path, capsys):
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    peer = load_or_create_identity(tmp_path / "la")
    TrustStore.load(d).add(peer_cert_from_pem(peer.cert_pem()), "PC-Nhaㅤ")
    assert run_main(["--config-dir", str(d), "unpair", "khong-co"]) == 1
    err = capsys.readouterr().err
    assert f"  {peer.device_id[:8]}  PC-Nha·" in err.splitlines(), err
    assert run_main(["--config-dir", str(d), "unpair", peer.device_id[:8]]) == 0
    out = capsys.readouterr().out
    assert f"Đã hủy ghép đôi với PC-Nha· ({peer.device_id[:8]})." in out, out
    assert "ㅤ" not in out


async def test_cl21_no_reinstall_hint_when_paired_device_is_online(tmp_path, cli_mdns):
    d = tmp_path / "cfg"
    load_or_create_identity(d)
    old = load_or_create_identity(tmp_path / "cu")
    other = load_or_create_identity(tmp_path / "khac")
    TrustStore.load(d).add(peer_cert_from_pem(old.cert_pem()), "PC-Nha")
    cli_mdns.seed = {
        old.device_id: discovered(old.device_id, "PC-Nha", 47474, addresses=("192.0.2.31",)),
        other.device_id: discovered(other.device_id, "Laptop", 47474, addresses=("192.0.2.30",)),
    }
    code, out, _ = await run_list_capture(list_argv(d))
    assert code == 0
    assert "mới chưa ghép đôi" not in out


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_cl22_list_discovery_error(tmp_path, cli_mdns, json_mode):
    cli_mdns.fail_start = OSError("giả lập không mở được socket mDNS")
    code, out, err = await run_list_capture(list_argv(tmp_path / "cfg", *(["--json"] if json_mode else [])))
    assert code == 1
    assert "Traceback" not in out + err
    if json_mode:
        obj = json.loads(out.strip())
        assert obj["error"] == "discovery_error"
        assert isinstance(obj["message"], str) and obj["message"]
    else:
        assert err.startswith("Lỗi: "), err


@pytest.mark.parametrize("case", ["config_file", "corrupt_store", "corrupt_identity"])
async def test_list_runtime_errors_exit_1(tmp_path, cli_mdns, case):
    expected = {
        "config_file": "config_dir_error",
        "corrupt_store": "trust_store_error",
        "corrupt_identity": "identity_error",
    }[case]
    d = tmp_path / "cfg"
    if case == "config_file":
        d.write_bytes(b"x")
    else:
        load_or_create_identity(d)
        target = d / ("trusted.json" if case == "corrupt_store" else "device.crt")
        target.write_bytes(b"rac")
    code, out, err = await run_list_capture(list_argv(d, "--json"))
    assert code == 1
    assert json.loads(out.strip())["error"] == expected
    code, out, err = await run_list_capture(list_argv(d))
    assert code == 1 and err.startswith("Lỗi: ") and "Traceback" not in err


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.mdns
def test_list_interrupted_prints_cancelled(tmp_path, procs):
    """`cmd_list`: Ctrl+C → “Đã hủy.”, mã 1, không traceback (mDNS thật chỉ trên loopback).

    Chờ tín hiệu sẵn sàng thay cho ngủ cố định: `list` tạo danh tính (`device.crt`) bên trong vòng lặp
    sự kiện, sau khi đã cài xử lý Ctrl+C/Ctrl+Break, nên lúc đó gửi Ctrl+C là đúng lúc lệnh đang chạy.
    """
    cfg = tmp_path / "cfg"
    proc = procs(["--config-dir", str(cfg), "list", "--timeout", "20", *MDNS_OPTS])
    deadline = time.monotonic() + 30.0
    while not (cfg / "device.crt").exists():
        assert proc.p.poll() is None, f"list đã thoát sớm: {proc.err_text()}"
        assert time.monotonic() < deadline, "hết 30 s mà list chưa tạo danh tính"
        time.sleep(0.05)
    time.sleep(0.2)  # cho lệnh đi tiếp vào phần duyệt mDNS
    assert proc.p.poll() is None, proc.err_text()
    proc.interrupt()
    code = proc.finish(30)
    text = "\n".join(proc.out) + proc.err_text()
    assert code == 1, text
    assert "Đã hủy." in text
    assert "Traceback" not in text


# --- CL23–CL26: pair theo tên ------------------------------------------------------------------------------


@pytest.mark.slow
@with_marks(socket_test)
async def test_cl23_pair_by_name_then_by_prefix(
    tmp_path, fast_links, cli_mdns, browse_fast, open_control_calls, cli_runs
):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))  # B: 127.0.0.1, không mDNS
    ev = await listen.wait_event("listening")
    b_id, port = ev["device_id"], ev["port"]
    cli_mdns.seed = {b_id: discovered(b_id, "B", port)}

    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "B"))
    await pair.wait_text("Trùng khớp? [c/k]:")
    await listen.wait_event("pair_prompt")
    text = pair.text()
    assert "Đang tìm “B” trong mạng…" in text
    assert f"Đang kết nối tới “B” ({b_id[:8]}) tại 127.0.0.1:{port}…" in text
    pair.say("c")
    listen.say("c")
    assert await asyncio.wait_for(pair.task, 10) == 0, pair.text()
    assert TrustStore.load(tmp_path / "A").get(b_id) is not None
    assert cli_mdns.instances and all(m.advertised == [] for m in cli_mdns.instances), (
        "pair <tên> không quảng bá"
    )
    assert all("advertise" not in m.calls for m in cli_mdns.instances)

    n = len(cli_mdns.instances)
    pair2 = cli_runs("pair", name_pair_argv(tmp_path / "A", b_id[:6], json_mode=True))
    p2 = await pair2.wait_event("pair_prompt")
    assert p2["peer_device_id"] == b_id
    await listen.wait_event("pair_prompt", n=2)
    pair2.say("c")
    listen.say("c")
    assert await asyncio.wait_for(pair2.task, 10) == 0, pair2.text()
    assert pair2.events_of("pair_result")[0]["outcome"] == "paired"
    assert len(cli_mdns.instances) == n + 1
    assert open_control_calls == [], "pair <tên> không được tự mở kết nối điều khiển"


@with_marks(socket_test)
async def test_cl24_pair_by_name_not_found(tmp_path, fast_links, cli_mdns, browse_fast, cli_runs):
    c = load_or_create_identity(tmp_path / "peer-C")
    cli_mdns.seed = {c.device_id: discovered(c.device_id, "C", 47474, addresses=("192.0.2.20",))}
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "khong-co"))
    assert await asyncio.wait_for(pair.task, 10) == 1
    text = pair.text()
    assert "Lỗi: Không thấy thiết bị nào khớp “khong-co” trong mạng." in text, text
    assert "Thiết bị đang thấy:" in text
    assert re.search(rf"^  {c.device_id[:8]}  C$", text, re.M), text
    assert MDNS_HINT in text

    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "khong-co", json_mode=True))
    assert await asyncio.wait_for(pair.task, 10) == 1
    [obj] = pair.events_of("error")
    assert obj["error"] == "not_found"
    assert obj["candidates"] == [{"device_id": c.device_id, "name": "C"}]


@with_marks(socket_test)
async def test_cl24_pair_by_name_nothing_seen(tmp_path, fast_links, cli_mdns, browse_fast, cli_runs):
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "B"))
    assert await asyncio.wait_for(pair.task, 10) == 1
    text = pair.text()
    assert "(chưa thấy thiết bị nào)" in text
    assert MDNS_HINT in text


@with_marks(socket_test)
async def test_cl24_pair_by_name_ambiguous(tmp_path, fast_links, cli_mdns, browse_fast, cli_runs):
    x = load_or_create_identity(tmp_path / "peer-X")
    y = load_or_create_identity(tmp_path / "peer-Y")
    cli_mdns.seed = {
        x.device_id: discovered(x.device_id, "pc", 47474, addresses=("192.0.2.21",)),
        y.device_id: discovered(y.device_id, "PC", 47474, addresses=("192.0.2.22",)),
    }
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "Pc"))
    assert await asyncio.wait_for(pair.task, 10) == 1
    text = pair.text()
    assert "Lỗi: “Pc” khớp nhiều thiết bị; hãy nhập mã thiết bị dài hơn:" in text, text
    assert re.search(rf"^  {x.device_id}  pc$", text, re.M), text
    assert re.search(rf"^  {y.device_id}  PC$", text, re.M), text

    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "pc", json_mode=True))
    assert await asyncio.wait_for(pair.task, 10) == 1
    [obj] = pair.events_of("error")
    assert obj["error"] == "ambiguous"
    assert sorted(c["device_id"] for c in obj["candidates"]) == sorted([x.device_id, y.device_id])


@with_marks(socket_test)
async def test_cl24_pair_by_name_paired_but_offline(tmp_path, fast_links, cli_mdns, browse_fast, cli_runs):
    d = tmp_path / "A"
    load_or_create_identity(d)
    dd = load_or_create_identity(tmp_path / "peer-D")
    TrustStore.load(d).add(peer_cert_from_pem(dd.cert_pem()), "D")
    pair = cli_runs("pair", name_pair_argv(d, "D"))
    assert await asyncio.wait_for(pair.task, 10) == 1
    text = pair.text()
    assert f"Lỗi: “D” ({dd.device_id[:8]}) không có trong mạng lúc này. {MDNS_HINT}" in text, text

    pair = cli_runs("pair", name_pair_argv(d, "D", json_mode=True))
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert pair.events_of("error")[0]["error"] == "offline"


@pytest.mark.slow
@with_marks(socket_test)
async def test_cl25_seen_but_unreachable(tmp_path, fast_links, cli_mdns, browse_fast, cli_runs):
    b = load_or_create_identity(tmp_path / "peer-B")
    s = socket.socket()
    s.bind((LOCAL, 0))
    closed_port = s.getsockname()[1]
    s.close()
    cli_mdns.seed = {b.device_id: discovered(b.device_id, "B", closed_port)}
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "B"))
    assert await asyncio.wait_for(pair.task, 15) == 1
    text = pair.text()
    assert MVP_SEEN_UNREACHABLE.format(x="B") in text, text
    assert HOTSPOT_HINT in text


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_cl26_pair_by_name_without_mdns(tmp_path, capsys, json_mode):
    d = tmp_path / "cfg"
    argv = ["--config-dir", str(d), "pair", "B", *(["--json"] if json_mode else []), *NODE_OPTS]
    assert run_main_guarded(argv) == 1
    captured = capsys.readouterr()
    if json_mode:
        obj = json.loads(captured.out.strip())
        assert obj["error"] == "discovery_error"
        assert obj["message"] == MDNS_OFF
    else:
        assert MDNS_OFF in captured.err, captured.err
    assert not (d / "node.lock").exists()


@with_marks(socket_test)
async def test_pair_by_name_when_mdns_cannot_start(tmp_path, fast_links, cli_mdns, cli_runs):
    cli_mdns.fail_start = OSError("giả lập")
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "B"))
    assert await asyncio.wait_for(pair.task, 10) == 1
    text = pair.text()
    assert "Không tìm được thiết bị theo tên vì không bật được khám phá mDNS (" in text, text
    assert "teleport pair <ip[:cổng]>" in text
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", "B", json_mode=True))
    assert await asyncio.wait_for(pair.task, 10) == 1
    assert pair.events_of("error")[0]["error"] == "discovery_error"


def test_pair_by_name_bad_name_option_exits_2(tmp_path):
    d = tmp_path / "cfg"
    argv = ["--config-dir", str(d), "pair", "B", "--name", "  x", *NODE_OPTS, *MDNS_OPTS]
    assert run_main_guarded(argv) == 2
    assert not (d / "node.lock").exists()


@pytest.mark.slow
@with_marks(socket_test)
async def test_pair_by_ip_does_not_use_mdns(tmp_path, fast_links, cli_mdns, cli_runs):
    """Chốt thêm 8: `pair <ip>` không bật mDNS, kể cả khi có `--mdns-interface`."""
    s = socket.socket()
    s.bind((LOCAL, 0))
    port = s.getsockname()[1]
    s.close()
    argv = [
        "--config-dir",
        str(tmp_path / "A"),
        "pair",
        f"{LOCAL}:{port}",
        "--name",
        "A",
        *NODE_OPTS,
        *MDNS_OPTS,
    ]
    pair = cli_runs("pair", argv)
    assert await asyncio.wait_for(pair.task, 15) == 1
    assert cli_mdns.instances == []


@pytest.fixture
def fake_open_pairing(monkeypatch):
    """Thay `open_pairing` của `teleport.app.pairing`: ghi (địa chỉ, cổng) rồi báo không kết nối được.

    Nhờ vậy `pair 1.2.3.4…` không gửi gói nào ra mạng thật."""
    from teleport.app import pairing as app_pairing
    from teleport.net.connection import Unreachable

    calls: list[tuple[list[str], int]] = []

    async def fake(addresses, port, hello):
        calls.append((list(addresses), port))
        raise Unreachable("giả lập: không kết nối được", address=next(iter(addresses)))

    monkeypatch.setattr(app_pairing, "open_pairing", fake)
    return calls


@with_marks(socket_test)
@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("1.2.3.4\xa0:47474", (["1.2.3.4"], 47474)),
        ("1.2.3.4\xa0", (["1.2.3.4"], 47474)),
        ("\xa01.2.3.4:50000\xa0", (["1.2.3.4"], 50000)),
        ("\N{EM SPACE}1.2.3.4\t", (["1.2.3.4"], 47474)),
    ],
    ids=["nbsp-before-port", "nbsp-trailing", "nbsp-both-ends", "unicode-space"],
)
async def test_pair_target_with_unicode_whitespace_is_an_address(
    tmp_path, fast_links, cli_mdns, fake_open_pairing, cli_runs, target, expected
):
    """Sửa F6: dán địa chỉ từ web (NBSP, khoảng trắng Unicode) vẫn được hiểu là địa chỉ, không duyệt mDNS."""
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", target))
    t0 = time.monotonic()
    assert await asyncio.wait_for(pair.task, 15) == 1, pair.text()
    assert fake_open_pairing == [expected], pair.text()
    assert cli_mdns.instances == [], "đích là địa chỉ: không được bật mDNS để tìm theo tên"
    assert "Đang tìm" not in pair.text()
    assert time.monotonic() - t0 < 3.0


@pytest.mark.parametrize(
    "target", ["", "   ", "\xa0", " \t\N{IDEOGRAPHIC SPACE} "], ids=["empty", "spaces", "nbsp", "mixed"]
)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_pair_empty_target_exits_2_immediately(tmp_path, cli_mdns, target, json_mode):
    """Sửa F6: `pair ""` / chỉ khoảng trắng → lỗi cú pháp, mã 2 ngay (không duyệt mDNS 3 s,
    không chạy node)."""
    d = tmp_path / "cfg"
    argv = [
        "--config-dir",
        str(d),
        "pair",
        target,
        *(["--json"] if json_mode else []),
        *NODE_OPTS,
        *MDNS_OPTS,
    ]
    t0 = time.monotonic()
    assert run_main_guarded(argv) == 2
    assert time.monotonic() - t0 < 1.0
    assert cli_mdns.instances == []
    assert not (d / "node.lock").exists()


# --- Sửa G2, G3 (review PR-4 vòng 2): đích có khoảng trắng bên trong; Ctrl+C khi `pair` ------------
#
# G2: bỏ khoảng trắng hai đầu; còn khoảng trắng bên trong thì chỉ là địa chỉ khi bỏ hết khoảng trắng
# ra được IPv4[:cổng] HỢP LỆ, ngược lại là tên (tìm theo tên, không phải lỗi cú pháp mã 2).
# Không có khoảng trắng bên trong thì như cũ (trông như địa chỉ mà sai → mã 2: CL5).

G2_ADDRESSES = [
    ("1.2.3.4\xa0:47474", (["1.2.3.4"], 47474)),
    ("1.2.3. 4", (["1.2.3.4"], 47474)),
    ("192.168.1.5\N{IDEOGRAPHIC SPACE}", (["192.168.1.5"], 47474)),
    ("1 . 2 . 3 . 4 : 50000", (["1.2.3.4"], 50000)),
]
G2_NAMES = [
    "PC Nha",
    "a 1",
    "dead beef",
    "1 2",
    "Laptop 2.0",
    "Phòng 2:30",
    "12 . 5",
    "2024 . 1",
    "Cafe 2:1",
    "Bed 1:2",
    "Dad 10:30",
    "Cafe: 2",
    "A: B",
]


@pytest.fixture
def browse_instant(monkeypatch):
    from teleport import cli

    monkeypatch.setattr(cli, "_PAIR_BROWSE_TIMEOUT", 0.05)


@with_marks(socket_test)
@pytest.mark.parametrize(("target", "expected"), G2_ADDRESSES, ids=repr)
async def test_g2_target_with_inner_space_that_compacts_to_valid_ipv4_is_an_address(
    tmp_path, fast_links, cli_mdns, fake_open_pairing, cli_runs, target, expected
):
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", target, json_mode=True))
    assert await asyncio.wait_for(pair.task, 15) == 1, pair.text()
    assert fake_open_pairing == [expected], pair.text()
    assert cli_mdns.instances == [], "đích là địa chỉ: không được bật mDNS để tìm theo tên"
    assert [e["error"] for e in pair.events_of("error")] == []


@with_marks(socket_test)
@pytest.mark.parametrize("name", G2_NAMES, ids=repr)
async def test_g2_name_with_inner_space_is_searched_by_name(
    tmp_path, fast_links, cli_mdns, fake_open_pairing, browse_instant, cli_runs, name
):
    """Tên thiết bị hợp lệ có khoảng trắng bên trong không bị coi là địa chỉ sai (mã 2)."""
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", f"\xa0{name} ", json_mode=True))
    code = await asyncio.wait_for(pair.task, 15)
    [err] = pair.events_of("error")
    assert err["error"] == "not_found", pair.text()
    assert f"“{name}”" in err["message"], "tìm theo tên đã bỏ khoảng trắng hai đầu"
    assert code == 1
    assert cli_mdns.instances, "tìm theo tên phải bật mDNS"
    assert fake_open_pairing == []


@with_marks(socket_test)
@pytest.mark.parametrize("name", ["Cafe 2:1", "Laptop 2.0", "12 . 5"], ids=repr)
async def test_g2_name_with_inner_space_reaches_the_device_seen_under_that_name(
    tmp_path, fast_links, cli_mdns, fake_open_pairing, browse_instant, cli_runs, name
):
    c = load_or_create_identity(tmp_path / "peer-C")
    cli_mdns.seed = {c.device_id: discovered(c.device_id, name, 47474, addresses=("192.0.2.30",))}
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", name, json_mode=True))
    assert await asyncio.wait_for(pair.task, 15) == 1, pair.text()
    assert fake_open_pairing == [(["192.0.2.30"], 47474)], pair.text()


def _sigint_soon() -> None:
    """Ctrl+C thật trong tiến trình: SIGINT tới handler mà `asyncio.Runner` của lệnh đã cài."""
    asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("target", "port"),
    [
        ("1.2.3.4\xa0:47474", 47474),
        ("\xa01.2.3.4:50000 ", 50000),
        ("1.2.3. 4", 47474),
    ],
    ids=repr,
)
def test_g3_ctrl_c_during_pair_by_address_reports_normalized_address(
    tmp_path, capsys, fast_cli, monkeypatch, target, port
):
    """G3: Ctrl+C khi `pair <địa chỉ> --json` đang kết nối → `pair_result.address` là IPv4 đã chuẩn
    hóa, không kèm cổng (như `pair_result` của đường thường, `PairingFinished.address`), không phải
    chuỗi thô người dùng gõ (còn NBSP, khoảng trắng)."""
    from teleport.app import pairing as app_pairing

    calls: list = []

    async def hang(addresses, port, hello):
        calls.append((list(addresses), port))
        _sigint_soon()
        await asyncio.Event().wait()

    monkeypatch.setattr(app_pairing, "open_pairing", hang)
    d = tmp_path / "A"
    argv = ["--config-dir", str(d), "pair", target, "--json", "--name", "A", *NODE_OPTS]
    assert run_main(argv) == 1
    out = capsys.readouterr().out
    assert calls == [(["1.2.3.4"], port)], f"lệnh chưa tới bước kết nối đúng địa chỉ: {out!r}"
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    [result] = [e for e in events if e.get("event") == "pair_result"]
    assert result["outcome"] == "cancelled"
    assert result["address"] == "1.2.3.4"
    assert lock_is_free(d)


@pytest.mark.integration
def test_g3_ctrl_c_during_pair_by_name_reports_stripped_name(
    tmp_path, capsys, fast_links, cli_mdns, monkeypatch
):
    """G3: Ctrl+C lúc đang tìm theo tên → `pair_result.address` là tên đã bỏ khoảng trắng hai đầu."""
    from teleport import cli
    from teleport.app import node as node_mod

    monkeypatch.setattr(cli, "_PAIR_BROWSE_TIMEOUT", 10.0)
    fake_factory = node_mod.MdnsDiscovery  # `cli_mdns` đã cài: tạo `CliFakeMdns`

    def factory(**kwargs):
        m = fake_factory(**kwargs)
        real = m.start_browsing

        async def start_browsing(**kw):
            await real(**kw)
            _sigint_soon()

        m.start_browsing = start_browsing
        return m

    monkeypatch.setattr(node_mod, "MdnsDiscovery", factory)
    d = tmp_path / "A"
    t0 = time.monotonic()
    assert run_main(name_pair_argv(d, "\xa0 PC Nha\N{IDEOGRAPHIC SPACE}", json_mode=True)) == 1
    assert time.monotonic() - t0 < 5.0, "Ctrl+C phải dừng ngay, không chờ hết thời gian duyệt"
    out = capsys.readouterr().out
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    [result] = [e for e in events if e.get("event") == "pair_result"]
    assert result["outcome"] == "cancelled"
    assert result["address"] == "PC Nha"
    assert lock_is_free(d)


# --- CL27–CL30: listen với mDNS ----------------------------------------------------------------------


async def start_plain_node(directory, name: str):
    from teleport.app.node import Node

    node = Node(directory, name=name, host=LOCAL, port=0)
    await node.start()
    return node


def trust_dirs(a, b, name_a: str = "A", name_b: str = "B"):
    ia, ib = load_or_create_identity(a), load_or_create_identity(b)
    TrustStore.load(a).add(peer_cert_from_pem(ib.cert_pem()), name_b)
    TrustStore.load(b).add(peer_cert_from_pem(ia.cert_pem()), name_a)
    return ia, ib


@with_marks(socket_test)
async def test_cl27_listen_text_with_discovery(tmp_path, fast_links, cli_mdns, cli_runs):
    from teleport.core.discovery import DeviceAdded, DeviceRemoved

    _ia, ib = trust_dirs(tmp_path / "A", tmp_path / "B")
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A", json_mode=False))
    await listen.wait_text("Nhấn Ctrl+C để dừng.")
    head = listen.text()
    assert LISTEN_DISCOVERY in head
    assert head.index(LISTEN_DISCOVERY) < head.index("Nhấn Ctrl+C để dừng.")
    m = cli_mdns.last
    assert m.advertised, "listen phải quảng bá"
    x = load_or_create_identity(tmp_path / "peer-X")
    m.emit(DeviceAdded(discovered(x.device_id, "X", 47474, addresses=("192.0.2.30",))))
    await listen.wait_text(f"Thấy “X” ({x.device_id[:8]}, Windows, chưa ghép đôi) tại 192.0.2.30:47474.")
    m.emit(DeviceRemoved(discovered(x.device_id, "X", 47474, addresses=("192.0.2.30",))))
    await listen.wait_text(f"“X” ({x.device_id[:8]}) đã rời mạng.")

    b = await start_plain_node(tmp_path / "B", "B")
    try:
        m.emit(DeviceAdded(discovered(ib.device_id, "B", b.port)))
        await listen.wait_text(f"Thấy “B” ({ib.device_id[:8]}, Windows, đã ghép đôi) tại 127.0.0.1:{b.port}.")
        await listen.wait_text(f"Đã kết nối với “B” ({ib.device_id[:8]}).")
    finally:
        await b.close()
    await listen.wait_text(f"Mất kết nối với “B” ({ib.device_id[:8]}). Đang nối lại…")


@with_marks(socket_test)
async def test_listen_reprints_pair_question_after_discovery_line_until_answered(
    tmp_path, fast_cli, cli_mdns, cli_runs
):
    """`listen` đang hỏi “Trùng khớp? [c/k]: ” mà mDNS báo thấy một máy (dòng “Thấy …” in chen) → câu
    hỏi được in lại ngay sau dòng đó; trả lời `k` xong thì dòng “Thấy …” sau không kéo theo câu hỏi."""
    from teleport.core.discovery import DeviceAdded

    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "B", json_mode=False, name="B"))
    port = await listen_port_text(listen)
    pair = cli_runs("pair", pair_argv(tmp_path / "A", port))
    await listen.wait_text(ASK)
    await pair.wait_event("pair_prompt")
    m = cli_mdns.last
    x = load_or_create_identity(tmp_path / "peer-X")
    seen_x = f"Thấy “X” ({x.device_id[:8]}, Windows, chưa ghép đôi) tại 192.0.2.30:47474."
    m.emit(DeviceAdded(discovered(x.device_id, "X", 47474, addresses=("192.0.2.30",))))
    await listen.wait_text(seen_x)
    await asyncio.sleep(0.1)
    out = listen.out.getvalue()
    assert seen_x + "\n" + ASK in out, out
    assert out.endswith(ASK), out

    listen.say("k")
    assert await asyncio.wait_for(pair.task, 10) == 1
    await listen.wait_text("Tiếp tục chờ ghép đôi…")
    y = load_or_create_identity(tmp_path / "peer-Y")
    seen_y = f"Thấy “Y” ({y.device_id[:8]}, Windows, chưa ghép đôi) tại 192.0.2.31:47474."
    asks = listen.out.getvalue().count(ASK)
    m.emit(DeviceAdded(discovered(y.device_id, "Y", 47474, addresses=("192.0.2.31",))))
    await listen.wait_text(seen_y)
    await asyncio.sleep(0.1)
    out = listen.out.getvalue()
    assert out.count(ASK) == asks, out
    assert out.endswith(seen_y + "\n"), out


@with_marks(socket_test)
async def test_cl27_listen_json_with_discovery(tmp_path, fast_links, cli_mdns, cli_runs):
    from teleport.core.discovery import DeviceAdded, DeviceRemoved

    _ia, ib = trust_dirs(tmp_path / "A", tmp_path / "B")
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A"))
    ev = await listen.wait_event("listening")
    assert ev["discovery"] is True
    assert ev["discovery_error"] is None
    m = cli_mdns.last
    x = load_or_create_identity(tmp_path / "peer-X")
    m.emit(DeviceAdded(discovered(x.device_id, "X", 47474, addresses=("192.0.2.30",), os="linux")))
    on = await listen.wait_event("device_online")
    assert {"device_id", "name", "os", "paired", "addresses", "port", "time"} <= set(on)
    assert (on["device_id"], on["name"], on["os"], on["paired"]) == (x.device_id, "X", "linux", False)
    assert (on["addresses"], on["port"]) == (["192.0.2.30"], 47474)
    assert TIME_RE.match(on["time"])

    b = await start_plain_node(tmp_path / "B", "B")
    try:
        m.emit(DeviceAdded(discovered(ib.device_id, "B", b.port)))
        conn = await listen.wait_event("device_connected")
        assert (conn["device_id"], conn["name"], conn["outgoing"]) == (ib.device_id, "B", True)
        m.emit(DeviceRemoved(discovered(ib.device_id, "B", b.port)))
        off = await listen.wait_event("device_offline")
        assert (off["device_id"], off["name"]) == (ib.device_id, "B")
        await asyncio.sleep(0.3)
        assert listen.events_of("device_disconnected") == [], "mất mDNS không đóng kết nối đang sống"
    finally:
        await b.close()
    disc = await listen.wait_event("device_disconnected")
    assert (disc["device_id"], disc["name"]) == (ib.device_id, "B")
    for line in listen.out.getvalue().splitlines():
        json.loads(line)


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_cl28_listen_advertise_failure_warns_and_keeps_running(
    tmp_path, fast_links, cli_mdns, cli_runs, json_mode
):
    from teleport.net.discovery import DiscoveryError

    cli_mdns.fail_advertise = DiscoveryError("không có địa chỉ để quảng bá")
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A", json_mode=json_mode))
    if json_mode:
        ev = await listen.wait_event("listening")
        assert ev["discovery"] is True
        assert isinstance(ev["discovery_error"], str) and ev["discovery_error"]
    else:
        await listen.wait_text("Nhấn Ctrl+C để dừng.")
        warning = (
            "Cảnh báo: chưa quảng bá được qua mDNS (không có địa chỉ để quảng bá); "
            "máy khác vẫn ghép đôi được bằng IP."
        )
        assert warning in listen.text(), listen.text()
        assert LISTEN_DISCOVERY not in listen.text()
    await asyncio.sleep(0.2)
    assert not listen.task.done()


@with_marks(socket_test)
async def test_cl28_listen_mdns_start_failure_warns(tmp_path, fast_links, cli_mdns, cli_runs):
    cli_mdns.fail_start = OSError("giả lập socket")
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A", json_mode=False))
    await listen.wait_text("Nhấn Ctrl+C để dừng.")
    assert "Cảnh báo: chưa quảng bá được qua mDNS (" in listen.text()
    assert not listen.task.done()


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_cl29_listen_on_loopback_without_mdns_interface(
    tmp_path, fast_cli, cli_mdns, cli_runs, json_mode
):
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=json_mode))
    if json_mode:
        ev = await listen.wait_event("listening")
        assert ev["discovery"] is False
        assert ev["discovery_error"] is None
    else:
        await listen.wait_text("Nhấn Ctrl+C để dừng.")
        assert LISTEN_DISCOVERY not in listen.text()
        assert "Cảnh báo" not in listen.text()
    assert cli_mdns.instances == []


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_cl30_listen_reports_rejected(tmp_path, fast_links, cli_mdns, cli_runs, json_mode):
    from teleport.core.discovery import DeviceAdded

    a = load_or_create_identity(tmp_path / "A")
    b_dir = tmp_path / "B"
    ib = load_or_create_identity(b_dir)
    TrustStore.load(tmp_path / "A").add(peer_cert_from_pem(ib.cert_pem()), "B")  # B không tin A
    del a
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A", json_mode=json_mode))
    if json_mode:
        await listen.wait_event("listening")
    else:
        await listen.wait_text("Nhấn Ctrl+C để dừng.")
    b = await start_plain_node(b_dir, "B")
    try:
        cli_mdns.last.emit(DeviceAdded(discovered(ib.device_id, "B", b.port)))
        if json_mode:
            ev = await listen.wait_event("connect_failed")
            assert (ev["device_id"], ev["name"], ev["result"]) == (ib.device_id, "B", "rejected")
            assert MVP_REJECTED.format(x="B") in ev["message"]
        else:
            await listen.wait_text(MVP_REJECTED.format(x="B"))
            await listen.wait_text(f"Để ghép đôi lại: `teleport pair {ib.device_id[:8]}`")
        await asyncio.sleep(0.5)
        assert listen.text().count(MVP_REJECTED.format(x="B")) == 1
    finally:
        await b.close()


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_cl30_listen_reports_identity_mismatch(tmp_path, fast_links, cli_mdns, cli_runs, json_mode):
    from teleport.core.discovery import DeviceAdded

    load_or_create_identity(tmp_path / "A")
    ib = load_or_create_identity(tmp_path / "peer-B")
    TrustStore.load(tmp_path / "A").add(peer_cert_from_pem(ib.cert_pem()), "B")
    listen = cli_runs("listen", mdns_listen_argv(tmp_path / "A", json_mode=json_mode))
    if json_mode:
        await listen.wait_event("listening")
    else:
        await listen.wait_text("Nhấn Ctrl+C để dừng.")
    c = await start_plain_node(tmp_path / "C", "C")  # máy khác trả lời ở “địa chỉ của B”
    try:
        cli_mdns.last.emit(DeviceAdded(discovered(ib.device_id, "B", c.port)))
        if json_mode:
            ev = await listen.wait_event("connect_failed")
            assert (ev["device_id"], ev["name"], ev["result"]) == (ib.device_id, "B", "identity_mismatch")
            assert MVP_IDENTITY.format(x="B") in ev["message"]
        else:
            await listen.wait_text(MVP_IDENTITY.format(x="B"))
            await listen.wait_text(f"teleport unpair {ib.device_id[:8]}")
    finally:
        await c.close()


# =================================================================================================
# L1/L4 (kế hoạch "L1 và L4", mục cli.py): cảnh báo khi máy đang chờ đã hiện nhiều mã, `--json` có
# `recent_codes` + `warning`, câu báo `prompt_failed`. Câu chữ so nguyên văn với kế hoạch.
# =================================================================================================

WARN_CODES = (
    "Cảnh báo: máy này đã hiện {n} mã ghép đôi trong 1 phút qua. Nếu bạn không tự ghép đôi nhiều lần "
    "như vậy, có thể có người đang thử giả mạo: hãy từ chối (gõ k)."
)
MVP_PROMPT_FAILED = "Không hiện được mã ghép đôi trên máy này nên đã hủy ghép đôi. Hãy thử lại."
ASK = "Trùng khớp? [c/k]: "


def _prompt(
    role: str,
    recent_codes: int,
    *,
    peer_name: str = "A",
    known_name: str | None = None,
    code: str = "123456",
    peer_device_id: str = "ab" * 16,
    address: str = "192.168.1.5",
    expires_at: float | None = None,
):
    from teleport.app.pairing import PairingPrompt
    from teleport.core.pairing import Role

    return PairingPrompt(
        session_id=7,
        role=Role(role),
        address=address,
        peer_name=peer_name,
        peer_device_id=peer_device_id,
        code=code,
        expires_at=asyncio.get_running_loop().time() + 60 if expires_at is None else expires_at,
        recent_codes=recent_codes,
        known_name=known_name,
    )


def _prompter(*, json_mode: bool, listening: bool = True):
    from teleport.cli import _Output, _Prompter

    out, err = io.StringIO(), io.StringIO()
    return _Prompter(_Output(out, err, json_mode), listening=listening), out, err


@pytest.mark.parametrize("n", [0, 1, 2])
async def test_responder_prompt_below_threshold_has_no_warning(n):
    p, out, err = _prompter(json_mode=False)
    p.on_prompt(_prompt("responder", n))
    text = out.getvalue()
    assert "Cảnh báo" not in text and "mã ghép đôi trong 1 phút qua" not in text
    lines = text.split("\n")
    assert lines[-1] == ASK
    i = lines.index("Mã ghép đôi:   123 456")
    assert lines[i + 1].startswith("Máy kia tự xưng là “A”")
    assert err.getvalue() == ""


@pytest.mark.parametrize("n", [3, 5, 64])
async def test_responder_prompt_at_threshold_warns_between_code_and_question(n):
    """H1: cảnh báo nằm ngay dưới dòng mã (mvp mục 7.2), trước tên máy kia và câu hỏi."""
    p, out, err = _prompter(json_mode=False)
    p.on_prompt(_prompt("responder", n))
    lines = out.getvalue().split("\n")
    assert lines[-1] == ASK
    i = lines.index("Mã ghép đôi:   123 456")
    assert lines[i + 1] == WARN_CODES.format(n=n)
    assert lines[i + 2].startswith("Máy kia tự xưng là “A”")
    assert out.getvalue().count("Cảnh báo") == 1
    assert err.getvalue() == ""


async def test_warning_mentions_exactly_three_codes():
    p, out, _ = _prompter(json_mode=False)
    p.on_prompt(_prompt("responder", 3))
    assert "đã hiện 3 mã ghép đôi trong 1 phút qua" in out.getvalue()


@pytest.mark.parametrize("listening", [False, True], ids=["pair", "listen"])
@pytest.mark.parametrize("n", [0, 3, 10])
async def test_initiator_prompt_never_warns(n, listening):
    p, out, _ = _prompter(json_mode=False, listening=listening)
    p.on_prompt(_prompt("initiator", n))
    text = out.getvalue()
    assert "Cảnh báo" not in text and "mã ghép đôi trong 1 phút qua" not in text
    assert text.endswith(ASK)


@pytest.mark.parametrize(
    ("role", "n", "warn"),
    [
        ("responder", 0, False),
        ("responder", 2, False),
        ("responder", 3, True),
        ("responder", 7, True),
        ("initiator", 0, False),
        ("initiator", 5, False),
    ],
)
async def test_json_pair_prompt_has_recent_codes_and_warning(role, n, warn):
    p, out, err = _prompter(json_mode=True)
    p.on_prompt(_prompt(role, n))
    events = [json.loads(line) for line in out.getvalue().splitlines() if line.strip()]
    assert [e["event"] for e in events] == ["pair_prompt"]
    ev = events[0]
    assert type(ev["recent_codes"]) is int and ev["recent_codes"] == n
    assert "warning" in ev
    assert ev["warning"] == (WARN_CODES.format(n=n) if warn else None)
    assert ev["code"] == "123456" and ev["role"] == role
    assert err.getvalue() == ""


# --- In lại “Trùng khớp? [c/k]: ” khi có dòng chen vào (spec-p2-7 mục E1 cho listen/pair; plan-p2-8 a2) ---

INTERJECT = "Thấy “X” (abababab, Windows, chưa ghép đôi) tại 192.0.2.30:47474."
INTERJECT_AFTER = "Thấy “Y” (cdcdcdcd, Linux, chưa ghép đôi) tại 192.0.2.31:47474."


class _DecideNode:
    """Node giả cho `_Prompter`: chỉ ghi lại `pairing.decide`."""

    def __init__(self) -> None:
        self.decided: list[tuple[int, bool]] = []
        self.pairing = self

    def decide(self, session_id: int, accepted: bool) -> bool:
        self.decided.append((session_id, accepted))
        return True


def _text_prompter(*, listening: bool):
    from teleport.cli import _Output, _Prompter

    out, err = io.StringIO(), io.StringIO()
    output = _Output(out, err, False)
    prompter = _Prompter(output, listening=listening)
    prompter.node = _DecideNode()
    return prompter, output, out, err


def _pair_finished(outcome: str, *, role: str = "responder", session_id: int = 7):
    from teleport.app.pairing import PairingFinished, PairingOutcome
    from teleport.core.pairing import Role

    return PairingFinished(
        session_id=session_id,
        role=Role(role),
        outcome=PairingOutcome(outcome),
        address="192.168.1.5",
        port=None if role == "responder" else 47474,
        peer_name="A",
        peer_device_id="ab" * 16,
        peer_reason=None,
        device=None,
        known_name=None,
        code_shown=True,
    )


@pytest.mark.parametrize("listening", [True, False], ids=["listen", "pair"])
async def test_pair_question_is_reprinted_after_interjected_line(listening):
    """Lời hỏi đang mở mà có dòng khác in chen (ví dụ “Thấy …” của mDNS) → dòng đó in trên dòng riêng
    rồi “Trùng khớp? [c/k]: ” được in lại ngay sau, con trỏ ở cuối câu hỏi."""
    p, output, out, err = _text_prompter(listening=listening)
    role = "responder" if listening else "initiator"
    p.on_prompt(_prompt(role, 0))
    assert out.getvalue().endswith("\n" + ASK)
    output.text(INTERJECT)
    assert out.getvalue().endswith(ASK + "\n" + INTERJECT + "\n" + ASK), out.getvalue()
    output.text(INTERJECT_AFTER)
    assert out.getvalue().endswith(ASK + "\n" + INTERJECT_AFTER + "\n" + ASK), out.getvalue()
    assert out.getvalue().count(ASK) == 3
    assert err.getvalue() == ""


@pytest.mark.parametrize("listening", [True, False], ids=["listen", "pair"])
async def test_pair_question_is_reprinted_after_interjected_error_line(listening):
    """Dòng lỗi (ra stderr) chen vào lúc đang hỏi: câu hỏi vẫn được in lại trên stdout."""
    p, output, out, err = _text_prompter(listening=listening)
    p.on_prompt(_prompt("responder" if listening else "initiator", 0))
    before = out.getvalue().count(ASK)
    output.error("x", "giả lập lỗi chen vào")
    assert "Lỗi: giả lập lỗi chen vào" in err.getvalue()
    assert out.getvalue().endswith("\n" + ASK) and out.getvalue().count(ASK) == before + 1


@pytest.mark.parametrize("listening", [True, False], ids=["listen", "pair"])
async def test_pair_question_is_reprinted_after_wrong_answer_then_interjected_line(listening):
    """Gõ sai → gợi ý + hỏi lại; câu hỏi mới vẫn mở nên dòng chen sau đó cũng được in lại câu hỏi."""
    p, output, out, _ = _text_prompter(listening=listening)
    p.on_prompt(_prompt("responder" if listening else "initiator", 0))
    p.feed(time.perf_counter(), "có lẽ")
    assert "Hãy gõ c (trùng) hoặc k (không trùng)." in out.getvalue()
    assert out.getvalue().endswith(ASK)
    output.text(INTERJECT)
    assert out.getvalue().endswith(INTERJECT + "\n" + ASK), out.getvalue()
    assert p.node.decided == []


@pytest.mark.parametrize("listening", [True, False], ids=["listen", "pair"])
@pytest.mark.parametrize("closing", ["c", "k", "eof", "peer_aborted", "timeout"])
async def test_pair_question_is_not_reprinted_after_answer_or_cancel(listening, closing):
    """Sau khi đã trả lời (c/k), đầu vào đóng, hoặc phiên tự kết thúc (máy kia hủy, hết giờ): dòng chen
    vào sau đó không kéo theo “Trùng khớp? [c/k]: ” nữa."""
    p, output, out, _ = _text_prompter(listening=listening)
    role = "responder" if listening else "initiator"
    p.on_prompt(_prompt(role, 0))
    if closing in ("c", "k"):
        p.feed(time.perf_counter(), closing)
        assert p.node.decided == [(7, closing == "c")]
    elif closing == "eof":
        p.feed(time.perf_counter(), None)
        assert p.node.decided == [(7, False)]
    else:
        p.on_finished(_pair_finished(closing, role=role))
        assert p.node.decided == []
    asks = out.getvalue().count(ASK)
    output.text(INTERJECT_AFTER)
    value = out.getvalue()
    assert value.count(ASK) == asks, value
    assert value.endswith(INTERJECT_AFTER + "\n"), value


MVP_PAIR_STDIN_CLOSED = "Không đọc được câu trả lời (đầu vào đã đóng) nên đã từ chối ghép đôi."


@pytest.mark.parametrize("listening", [True, False], ids=["listen", "pair"])
async def test_pair_stdin_closed_says_why_once(listening):
    """stdin đóng lúc đang hỏi → từ chối và in lý do (mvp mục 8); lời hỏi tới sau khi đóng cũng bị
    từ chối, nhưng câu báo chỉ in một lần."""
    p, _, out, _ = _text_prompter(listening=listening)
    role = "responder" if listening else "initiator"
    p.on_prompt(_prompt(role, 0))
    p.feed(time.perf_counter(), None)
    assert p.node.decided == [(7, False)]
    assert MVP_PAIR_STDIN_CLOSED in out.getvalue().splitlines(), out.getvalue()
    p.on_prompt(_prompt(role, 0))
    assert p.node.decided == [(7, False), (7, False)]
    assert out.getvalue().count(MVP_PAIR_STDIN_CLOSED) == 1, out.getvalue()


async def test_pair_stdin_closed_before_prompt_says_why():
    """`listen < /dev/null`: đầu vào đóng trước khi có lời hỏi → lời hỏi đầu tiên bị từ chối kèm lý do."""
    p, _, out, _ = _text_prompter(listening=True)
    p.feed(time.perf_counter(), None)
    assert MVP_PAIR_STDIN_CLOSED not in out.getvalue()
    p.on_prompt(_prompt("responder", 0))
    assert p.node.decided == [(7, False)]
    assert out.getvalue().count(MVP_PAIR_STDIN_CLOSED) == 1, out.getvalue()


@pytest.mark.parametrize("role", ["responder", "initiator"])
def test_outcome_message_prompt_failed(role):
    from teleport.app.pairing import PairingFinished, PairingOutcome
    from teleport.cli import outcome_message
    from teleport.core.pairing import Role

    result = PairingFinished(
        session_id=3,
        role=Role(role),
        outcome=PairingOutcome.PROMPT_FAILED,
        address="192.168.1.5",
        port=None if role == "responder" else 47474,
        peer_name="A",
        peer_device_id="ab" * 16,
        peer_reason=None,
        device=None,
        known_name=None,
        code_shown=False,
    )
    assert outcome_message(result) == [MVP_PROMPT_FAILED]


async def _pair_once(cli_runs, a_dir, port: int, *, json_mode: bool = True):
    """Một lần `pair` tới `listen` ở `port`, hai bên trả lời “c”; trả lần chạy `pair` (đã xong)."""
    pair = cli_runs("pair", pair_argv(a_dir, port, json_mode=json_mode))
    if json_mode:
        await pair.wait_event("pair_prompt")
    else:
        await pair.wait_text(ASK)
    pair.say("c")
    return pair


@with_marks(socket_test)
async def test_listen_json_recent_codes_and_warning_end_to_end(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    for n in (1, 2, 3):
        pair = await _pair_once(cli_runs, tmp_path / "A", ev["port"])
        await listen.wait_event("pair_prompt", n=n)
        listen.say("c")
        assert await asyncio.wait_for(pair.task, 10) == 0
        await listen.wait_event("pair_result", n=n)
        pa = pair.events_of("pair_prompt")[0]
        assert pa["recent_codes"] == 0 and pa["warning"] is None
    prompts = listen.events_of("pair_prompt")
    assert [p["recent_codes"] for p in prompts] == [1, 2, 3]
    assert [p["warning"] for p in prompts] == [None, None, WARN_CODES.format(n=3)]
    assert [r["outcome"] for r in listen.events_of("pair_result")] == ["paired"] * 3
    assert not listen.task.done()  # listen không dừng sau một mã


@with_marks(socket_test)
async def test_listen_text_warns_on_third_code(tmp_path, fast_cli, cli_runs):
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=False))
    port = await listen_port_text(listen)
    for n in (1, 2, 3):
        pair = await _pair_once(cli_runs, tmp_path / "A", port, json_mode=False)
        await listen.wait_text(ASK, n=n)
        listen.say("c")
        assert await asyncio.wait_for(pair.task, 10) == 0
        await listen.wait_text("Đã ghép đôi với A.", n=n)
        assert "Cảnh báo" not in pair.text()
    text = listen.text()
    assert text.count("mã ghép đôi trong 1 phút qua") == 1
    # H1: cảnh báo ngay dưới dòng mã, trước dòng tên máy kia.
    pattern = CODE_LINE_RE[:-1] + r"\n" + re.escape(WARN_CODES.format(n=3)) + r"\nMáy kia tự xưng là “A” "
    assert re.search(pattern, text, re.M), text


@with_marks(socket_test)
async def test_listen_over_code_limit_answers_busy_without_prompt(tmp_path, fast_cli, cli_runs, monkeypatch):
    """L4: quá giới hạn mã thì `listen` không hỏi, không in kết quả, vẫn chạy; `pair` nhận câu
    “chưa sẵn sàng” (mã thoát 1). Giới hạn rút còn 1 mã để test nhanh."""
    from teleport.core import pairing as core_pairing

    monkeypatch.setattr(core_pairing, "MAX_CODES_PER_WINDOW", 1)
    listen = cli_runs("listen", listen_argv(tmp_path / "B"))
    ev = await listen.wait_event("listening")
    first = await _pair_once(cli_runs, tmp_path / "A", ev["port"])
    await listen.wait_event("pair_prompt")
    listen.say("c")
    assert await asyncio.wait_for(first.task, 10) == 0
    await listen.wait_event("pair_result")

    second = cli_runs("pair", pair_argv(tmp_path / "C", ev["port"], json_mode=False, name="C"))
    assert await asyncio.wait_for(second.task, 10) == 1
    assert "B chưa sẵn sàng ghép đôi" in second.text()
    assert ASK not in second.text()
    await asyncio.sleep(0.3)
    assert len(listen.events_of("pair_prompt")) == 1
    assert len(listen.events_of("pair_result")) == 1
    assert not listen.task.done()


# =================================================================================================
# Nhóm (a) PR #10, việc VT-3 (kế hoạch nhóm (a), mục “Tiêu chí xong” H1, M1, M4, M5, L4).
#
# H1: lời hỏi theo bố cục mvp mục 7.2: dòng `Mã ghép đôi:   382 104` đứng riêng, trước mọi chữ do máy
# kia đặt; tên máy kia chỉ nằm trong “…” ở dòng `Máy kia tự xưng là …` (qua `display_name`: ≤ 32 cột,
# ký tự trống thành `·`). M1/M4/M5/L4: câu báo, mã thoát và JSON của CLI. Câu chữ so nguyên văn với
# kế hoạch. Độ rộng và ký tự trống được tính lại độc lập (`_columns`, `_BLANKS`).
# =================================================================================================

HEADER_LISTEN = "Có yêu cầu ghép đôi. Hãy so mã dưới đây với mã trên màn hình máy kia."
HEADER_PAIR = "Hãy so mã dưới đây với mã trên màn hình máy kia."
# mvp mục 7.2: một dòng chung cho cả hai vai khi đã ghép đôi trước đây; thêm dòng đổi tên
# khi tên đã lưu khác tên máy kia tự xưng (ghép đôi lại ở cả hai vai cập nhật tên, D2).
KNOWN = "Máy này đã ghép đôi với mã máy {id8} trước đây, tên đã lưu: “{name}”."
RENAME = "Ghép đôi xong, tên sẽ đổi thành “{name}”."
NOT_SHOWN_INITIATOR = "Ghép đôi với {x} chưa xong vì phiên dừng trước khi hiện mã. Hãy thử lại."
NOT_SHOWN_RESPONDER = "Một máy tự xưng là {x} đã yêu cầu ghép đôi nhưng phiên dừng trước khi hiện mã."
CONFLICT_RESPONDER = (
    "Một máy chưa xác minh tự xưng là {known} nhưng dùng danh tính khác với lúc ghép đôi. "
    "Có thể có người đang giả mạo máy đó. Yêu cầu ghép đôi đã bị chặn."
)
CONFLICT_INITIATOR = (
    "{known} đang dùng một danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy này. "
    "Kết nối đã bị chặn.",
    "Nếu chắc chắn máy đó đã đổi danh tính, hãy hủy ghép đôi mục cũ trước: `teleport unpair {id8}`",
)
MVP_INVALID_IDENTITY = (
    "Thiết bị ở {target} gửi danh tính không hợp lệ nên kết nối đã bị chặn. Có thể có người đang giả mạo."
)
CANCELLED_TEXT = "Đã hủy ghép đôi."
NAME_LINE_RE = re.compile(r"^Máy kia tự xưng là “(.*)” \(mã máy ([0-9a-f]{8}), ([0-9.]+)\)\.$")
# Các kết quả “chưa xong” (mvp mục 8, dòng “Mã ghép đôi không trùng / hết giờ”).
UNFINISHED = (
    "user_rejected",
    "timeout",
    "peer_rejected",
    "peer_timeout",
    "protocol_error",
    "peer_invalid",
    "peer_aborted",
    "connection_lost",
)
# Tên chứa mã giả (kế hoạch H1; kịch bản tan-cong 1). Mã thật trong các test là 123 456.
FAKE_CODE_NAMES = [
    "PC-A:   382 104",
    "PC-A" + "\u2800" * 20 + "382 104",
    "PC-A\u3164\u3164\u3164382 104",
    "Mã ghép đôi:   111 222",
    "PC-A\u3000\u3000\uff13\uff18\uff12 \uff11\uff10\uff14",  # U+3000 và chữ số toàn chiều rộng
    "PC-A:   382 104 " + "x" * 48,  # đúng 64 ký tự
    "B" * 64,
]
FAKE_CODE_IDS = [
    "colon-spaces",
    "braille-blank",
    "hangul-filler",
    "code-label",
    "ideographic-space-fullwidth-digits",
    "64-chars-fake-code",
    "64-chars",
]
# Vai và lệnh: `listen` luôn là bên trả lời; `pair` thường là bên khởi xướng, chuyển sang vai trả lời
# khi hai máy cùng ghép đôi với nhau (protocol mục 5.3). Dòng đầu xét theo lệnh, cảnh báo và dòng tên
# đã lưu xét theo vai (mvp mục 7.2).
PROMPT_MODES = [(True, "responder"), (False, "initiator"), (False, "responder")]
PROMPT_MODE_IDS = ["listen", "pair", "pair-yielded"]

_ZWJ = "\u200d"
_BLANKS = frozenset(
    [chr(c) for c in range(0x110000) if unicodedata.category(chr(c)) == "Zs" and c != 0x20]
    + ["\u2800", "\u3164", "\u115f", "\u1160", "\uffa0"]
)
# Vừa là dấu kết hợp vừa rộng: đặc tả không nói luật nào thắng, nên hypothesis không sinh.
_AMBIGUOUS_WIDTH = frozenset(
    chr(c)
    for c in range(0x110000)
    if unicodedata.category(chr(c)) in ("Mn", "Me") and unicodedata.east_asian_width(chr(c)) in ("W", "F")
)


def _columns(text: str) -> int:
    """Độ rộng theo cột, tính độc lập theo đặc tả (W/F = 2; Mn, Me, U+200D = 0; còn lại 1)."""
    total = 0
    for ch in text:
        if ch == _ZWJ or unicodedata.category(ch) in ("Mn", "Me"):
            continue
        total += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return total


def _spaced(code: str) -> str:
    return f"{code[:3]} {code[3:]}"


def _valid_name(name: str) -> bool:
    from teleport.core.messages import MessageError, validate_device_name

    try:
        validate_device_name(name)
    except MessageError:
        return False
    return True


def render_prompt(prompt, *, listening: bool, json_mode: bool = False) -> tuple[str, str]:
    """Cho `_Prompter` hiện một lời hỏi; trả (stdout, stderr). Cần vòng lặp đang chạy."""
    p, out, err = _prompter(json_mode=json_mode, listening=listening)
    p.on_prompt(prompt)
    return out.getvalue(), err.getvalue()


def expected_prompt_lines(prompt, *, listening: bool) -> list[str]:
    """Các dòng lời hỏi đúng theo kế hoạch H1 / mvp mục 7.2; dòng cuối là câu hỏi (không xuống dòng)."""
    from teleport.core.display import display_name

    responder = prompt.role.value == "responder"
    id8 = prompt.peer_device_id[:8]
    lines = [HEADER_LISTEN if listening else HEADER_PAIR, f"Mã ghép đôi:   {_spaced(prompt.code)}"]
    if responder and prompt.recent_codes >= 3:
        lines.append(WARN_CODES.format(n=prompt.recent_codes))
    lines.append(f"Máy kia tự xưng là “{display_name(prompt.peer_name)}” (mã máy {id8}, {prompt.address}).")
    if prompt.known_name is not None:
        lines.append(KNOWN.format(id8=id8, name=display_name(prompt.known_name)))
        if prompt.known_name != prompt.peer_name:
            lines.append(RENAME.format(name=display_name(prompt.peer_name)))
    lines.append(ASK)
    return lines


def check_code_first(lines: list[str], code: str, *, name_is_distinctive: bool = False) -> str:
    """Bất biến H1, kiểm độc lập với `display_name`; trả phần tên nằm trong “…”.

    - Đúng một dòng bắt đầu bằng “Mã ghép đôi”, và đó là `Mã ghép đôi:   <mã thật>`.
    - Trước dòng mã chỉ có tiêu đề cố định: không chữ số, không chữ nào do máy kia đặt.
    - Tên máy kia nằm trong “…” ở đúng một dòng `Máy kia tự xưng là …`, sau dòng mã; phần trong
      ngoặc ≤ 32 cột và không còn ký tự trống.
    - `name_is_distinctive`: phần tên đó không xuất hiện ở dòng nào khác (trừ dòng tên đã lưu và
      dòng “tên sẽ đổi thành”, cả hai đều sau dòng mã).
    """
    code_line = f"Mã ghép đôi:   {_spaced(code)}"
    assert [line for line in lines if line.startswith("Mã ghép đôi")] == [code_line], lines
    i = lines.index(code_line)
    for line in lines[:i]:
        assert not any(ch.isdigit() for ch in line), f"chữ số trước dòng mã: {line!r}"
        assert line in (HEADER_LISTEN, HEADER_PAIR), f"chữ lạ trước dòng mã: {line!r}"
    named = [(j, m) for j, line in enumerate(lines) if (m := NAME_LINE_RE.match(line))]
    assert len(named) == 1, lines
    j, m = named[0]
    assert j > i, "tên máy kia phải ở sau dòng mã"
    shown = m.group(1)
    assert _columns(shown) <= 32, shown
    assert not set(shown) & _BLANKS, shown
    for k, line in enumerate(lines):
        if line.startswith(("Máy này đã ghép đôi", "Ghép đôi xong, tên sẽ đổi thành")):
            assert k > i, f"dòng có tên đứng trước dòng mã: {line!r}"
    if name_is_distinctive:
        for k, line in enumerate(lines):
            if k != j and not line.startswith(("Máy này đã ghép đôi", "Ghép đôi xong, tên sẽ đổi thành")):
                assert shown not in line, f"tên máy kia ở ngoài “…”: {line!r}"
    return shown


# --- H1: bố cục lời hỏi (trong tiến trình, không socket) ---------------------------------------------


@pytest.mark.parametrize(("listening", "role"), PROMPT_MODES, ids=PROMPT_MODE_IDS)
@pytest.mark.parametrize("recent", [0, 4])
@pytest.mark.parametrize("name", FAKE_CODE_NAMES, ids=FAKE_CODE_IDS)
async def test_h1_prompt_shows_code_line_before_any_peer_text(name, recent, listening, role):
    assert _valid_name(name), "máy kia gửi được tên này trong hello"
    prompt = _prompt(role, recent, peer_name=name)
    text, err = render_prompt(prompt, listening=listening)
    lines = text.split("\n")
    assert lines == expected_prompt_lines(prompt, listening=listening)
    check_code_first(lines, "123456", name_is_distinctive=True)
    if recent >= 3 and role == "responder":
        assert lines[lines.index("Mã ghép đôi:   123 456") + 1] == WARN_CODES.format(n=recent)
    assert err == ""


async def test_h1_prompt_for_plain_name_matches_spec_example():
    """Ví dụ của mvp mục 7.2 (bỏ cảnh báo và tên đã lưu), so nguyên văn."""
    prompt = _prompt("responder", 1, peer_name="MacBook", peer_device_id="3f2a9c1e" + "0" * 24, code="382104")
    text, _ = render_prompt(prompt, listening=True)
    assert text == (
        f"{HEADER_LISTEN}\n"
        "Mã ghép đôi:   382 104\n"
        "Máy kia tự xưng là “MacBook” (mã máy 3f2a9c1e, 192.168.1.5).\n"
        "Trùng khớp? [c/k]: "
    )


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("PC-A" + "\u2800" * 20 + "382 104", "PC-A" + "·" * 20 + "382 104"),
        ("PC-A\u3164\u3164\u3164382 104", "PC-A···382 104"),
        ("B" * 64, "B" * 31 + "…"),
    ],
    ids=["braille-blank", "hangul-filler", "64-chars"],
)
async def test_h1_prompt_name_is_shown_with_blank_marks_and_cut(name, shown):
    text, _ = render_prompt(_prompt("responder", 0, peer_name=name), listening=True)
    assert f"Máy kia tự xưng là “{shown}” (mã máy abababab, 192.168.1.5)." in text.split("\n")


_PROMPT_NAME_CHARS = st.one_of(
    st.characters(exclude_categories=("Cc", "Cs")).filter(lambda ch: ch not in _AMBIGUOUS_WIDTH),
    st.sampled_from(
        [*sorted(_BLANKS), "3", " ", ":", "中", "\U0001f468", _ZWJ, "\u0301", "\uff13", "“", "”"]
    ),
)


@pytest.mark.slow
@settings(
    max_examples=150,
    deadline=None,
    suppress_health_check=[HealthCheck.filter_too_much, HealthCheck.too_slow],
)
@given(
    name=st.text(_PROMPT_NAME_CHARS, min_size=1, max_size=64),
    known=st.none() | st.text(_PROMPT_NAME_CHARS, min_size=1, max_size=64),
    code=st.from_regex(r"[0-9]{6}", fullmatch=True),
    recent=st.integers(min_value=0, max_value=10),
    mode=st.sampled_from(PROMPT_MODES),
)
def test_h1_prompt_layout_holds_for_any_valid_name(name, known, code, recent, mode):
    assume(_valid_name(name) and (known is None or _valid_name(known)))
    listening, role = mode

    async def show():
        prompt = _prompt(role, recent, peer_name=name, known_name=known, code=code)
        return prompt, render_prompt(prompt, listening=listening)

    prompt, (text, err) = asyncio.run(show())
    lines = text.split("\n")
    assert lines == expected_prompt_lines(prompt, listening=listening)
    check_code_first(lines, code)
    assert err == ""


@pytest.mark.parametrize("known", [None, "PC-Nha"])
async def test_h1_json_prompt_keeps_raw_fields_and_adds_known_name(known):
    name = "PC-A\u2800\u2800382 104"
    prompt = _prompt("responder", 0, peer_name=name, known_name=known)
    text, err = render_prompt(prompt, listening=True, json_mode=True)
    events = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert [e["event"] for e in events] == ["pair_prompt"], text
    ev = events[0]
    fields = {"session_id", "role", "peer_name", "peer_device_id", "address", "code", "expires_in"}
    assert fields | {"recent_codes", "warning", "known_name", "time"} <= set(ev)
    assert ev["peer_name"] == name, "JSON giữ tên gốc; giao diện tự hiện"
    assert ev["known_name"] == known
    assert ev["code"] == "123456"
    assert err == ""


# --- Bên khởi xướng / bên trả lời thô cho các test đầu-cuối -------------------------------------------


def _hello(device_id: str, name: str) -> dict:
    from teleport.core.messages import PROTOCOL_VERSION

    return {
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "device_id": device_id,
        "name": name,
        "app_version": "0.0.0",
        "os": "windows",
    }


def _commitment(fp_responder: str, nonce: bytes) -> str:
    """Cam kết của bên trả lời, tính lại theo protocol mục 5.2."""
    return hashlib.sha256(b"teleport-commit-v1" + bytes.fromhex(fp_responder) + nonce).hexdigest()


def _proof_payload(fp_initiator: str, fp_responder: str, n_a: bytes, commitment: str) -> bytes:
    """Payload ký trong `pair_nonce` (protocol 5.2), tính độc lập."""
    return (
        b"teleport-initiator-proof-v1"
        + bytes.fromhex(fp_initiator)
        + bytes.fromhex(fp_responder)
        + n_a
        + bytes.fromhex(commitment)
    )


def _sign(key_path, payload: bytes) -> bytes:
    """ECDSA P-256 + SHA-256, r ‖ s (64 byte), bằng khóa PEM ở `key_path`."""
    from pathlib import Path

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    key = serialization.load_pem_private_key(Path(key_path).read_bytes(), password=None)
    r, s_ = decode_dss_signature(key.sign(payload, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s_.to_bytes(32, "big")


def _verify(cert_pem: str, payload: bytes, signature: bytes) -> bool:
    """Kiểm chữ ký r ‖ s bằng khóa công khai trong `cert_pem` (độc lập với trust)."""
    from cryptography import x509
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    if len(signature) != 64:
        return False
    r, s_ = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    public = x509.load_pem_x509_certificate(cert_pem.encode("ascii")).public_key()
    try:
        public.verify(encode_dss_signature(r, s_), payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


class RawInitiator:
    """Bên khởi xướng thô (TLS ẩn danh, asyncio) gửi tới `listen`: tự đặt `hello.name` và chứng chỉ
    trong `pair_request` (có thể là chứng chỉ công khai của máy khác, như ở M5)."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        der = writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        self.server_fp = hashlib.sha256(der).hexdigest()
        self.nonce = secrets.token_bytes(32)

    @classmethod
    async def connect(cls, port: int) -> "RawInitiator":
        from teleport.net import tls

        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(LOCAL, port, ssl=tls.client_context()), 5
        )
        return cls(reader, writer)

    def send(self, msg: dict) -> None:
        from teleport.core.framing import encode_message

        self.writer.write(encode_message(msg))

    async def recv_type(self, type_name: str, timeout: float = 5.0) -> dict:
        from teleport.core.framing import MAX_PAIRING_MESSAGE_SIZE
        from teleport.net.stream import read_message

        msg = await asyncio.wait_for(read_message(self.reader, MAX_PAIRING_MESSAGE_SIZE), timeout)
        assert msg is not None and msg.get("type") == type_name, f"cần {type_name}, nhận {msg!r}"
        return msg

    async def start(self, device_id: str, name: str, cert_pem: str) -> None:
        """Đọc hello của server; gửi hello và `pair_request{cert}`."""
        await self.recv_type("hello")
        self.send(_hello(device_id, name))
        self.send({"type": "pair_request", "cert": cert_pem})
        await self.writer.drain()

    async def send_signed_nonce(self, own_fingerprint: str, key_path) -> dict:
        """Đọc `pair_commit`, gửi `pair_nonce` ký bằng khóa ở `key_path` (protocol 5.2); trả pair_commit."""
        commit = await self.recv_type("pair_commit")
        payload = _proof_payload(own_fingerprint, self.server_fp, self.nonce, commit["commitment"])
        self.send(
            {"type": "pair_nonce", "nonce": self.nonce.hex(), "signature": _sign(key_path, payload).hex()}
        )
        await self.writer.drain()
        return commit

    async def to_code(self, own_fingerprint: str, key_path) -> str:
        """`pair_commit` → gửi `pair_nonce` (ký bằng `key_path`) → `pair_reveal` (kiểm cam kết); trả mã."""
        from teleport.core.pairing_code import pairing_code

        commit = await self.send_signed_nonce(own_fingerprint, key_path)
        reveal = await self.recv_type("pair_reveal")
        n_b = bytes.fromhex(reveal["nonce"])
        assert _commitment(self.server_fp, n_b) == commit["commitment"]
        return pairing_code(own_fingerprint, self.server_fp, self.nonce, n_b)

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.transport.abort()
        with contextlib.suppress(Exception):
            self.writer.close()


class ThreadResponder:
    """Bên trả lời thô trong thread riêng (socket TLS chặn): dùng được cả với `main()` chạy ở thread
    chính (vòng lặp riêng của lệnh) lẫn với `cli_runs`.

    - `pair=False`: chỉ bắt tay TLS và gửi `hello` (M1: chứng chỉ server không hợp lệ).
    - `pair=True`: ghép đôi đúng giao thức: cam kết → nonce → reveal (tính `code`) → chờ
      `pair_confirm` của máy kia rồi gửi `pair_confirm`.
    - Sau đó chờ máy kia đóng kết nối (close_notify hoặc reset), gọi `on_peer_closing` (trong thread
      này). `close_notify=False`: không bao giờ trả close_notify, giữ kết nối tới khi test xong.
    """

    def __init__(
        self,
        cert_path,
        key_path,
        device_id: str,
        *,
        name: str = "M",
        pair: bool = True,
        close_notify: bool = True,
        on_peer_closing=None,
    ) -> None:
        self.device_id = device_id
        self.name = name
        self.pair = pair
        self.close_notify = close_notify
        self.on_peer_closing = on_peer_closing
        with open(cert_path, encoding="ascii") as f:
            self.fingerprint = hashlib.sha256(ssl.PEM_cert_to_DER_cert(f.read())).hexdigest()
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        self.ctx.load_cert_chain(cert_path, key_path)
        self.ctx.num_tickets = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind((LOCAL, 0))
        self.sock.listen(4)
        self.sock.settimeout(0.1)
        self.port: int = self.sock.getsockname()[1]
        self.code: str | None = None
        self.proof_ok: bool | None = None  # chữ ký trong pair_nonce của máy kia có hợp lệ không
        self.received: list[dict] = []
        self.errors: list[BaseException] = []
        self.stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="test-responder", daemon=True)

    def __enter__(self) -> "ThreadResponder":
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop.set()
        self._thread.join(15)
        self.sock.close()

    def _run(self) -> None:
        conn = None
        try:
            while conn is None:
                if self.stop.is_set():
                    return
                with contextlib.suppress(TimeoutError):
                    conn, _ = self.sock.accept()
            conn.settimeout(15)
            conn = self.ctx.wrap_socket(conn, server_side=True)
            self._send(conn, _hello(self.device_id, self.name))
            if self.pair:
                self._pair(conn)
            self._wait_peer_close(conn)
            if self.on_peer_closing is not None:
                self.on_peer_closing()
            if self.close_notify:
                with contextlib.suppress(OSError, ValueError):
                    conn = conn.unwrap()
            else:
                self.stop.wait(30)
        except Exception as e:
            self.errors.append(e)
        finally:
            if conn is not None:
                with contextlib.suppress(OSError):
                    conn.close()

    def _pair(self, conn) -> None:
        from teleport.core.pairing_code import pairing_code

        assert self._recv(conn)["type"] == "hello"
        request = self._recv(conn)
        assert request["type"] == "pair_request", request
        fp_initiator = hashlib.sha256(ssl.PEM_cert_to_DER_cert(request["cert"])).hexdigest()
        n_b = secrets.token_bytes(32)
        self._send(conn, {"type": "pair_commit", "commitment": _commitment(self.fingerprint, n_b)})
        nonce = self._recv(conn)
        assert nonce["type"] == "pair_nonce", nonce
        commitment = _commitment(self.fingerprint, n_b)
        payload = _proof_payload(fp_initiator, self.fingerprint, bytes.fromhex(nonce["nonce"]), commitment)
        self.proof_ok = _verify(request["cert"], payload, bytes.fromhex(nonce.get("signature", "")))
        self.code = pairing_code(fp_initiator, self.fingerprint, bytes.fromhex(nonce["nonce"]), n_b)
        self._send(conn, {"type": "pair_reveal", "nonce": n_b.hex()})
        confirm = self._recv(conn)
        assert confirm["type"] == "pair_confirm", confirm
        self._send(conn, {"type": "pair_confirm"})

    @staticmethod
    def _wait_peer_close(conn) -> None:
        while True:
            try:
                data = conn.recv(65536)
            except OSError:  # reset, abort, lỗi SSL
                return
            if not data:  # close_notify
                return

    @staticmethod
    def _send(conn, msg: dict) -> None:
        from teleport.core.framing import encode_message

        conn.sendall(encode_message(msg))

    def _recv(self, conn) -> dict:
        (size,) = struct.unpack("!I", self._exact(conn, 4))
        msg = json.loads(self._exact(conn, size))
        self.received.append(msg)
        return msg

    @staticmethod
    def _exact(conn, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = conn.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("máy kia đóng kết nối giữa chừng")
            buf += chunk
        return buf


def write_x400_san_cert(directory) -> tuple[str, str, str]:
    """Chứng chỉ tự ký P-256, CN đúng dạng `teleport-<device_id>` nhưng SAN chứa x400Address (M1).

    `cryptography` ném lỗi không phải ValueError khi đọc SAN này. Trả (file cert, file khóa, device_id).
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtensionOID, NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    device_id = secrets.token_hex(16)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teleport-" + device_id)])
    san = x509.UnrecognizedExtension(ExtensionOID.SUBJECT_ALTERNATIVE_NAME, b"\x30\x02\xa3\x00")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(9999, 12, 31, tzinfo=datetime.UTC))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "x400.crt", directory / "x400.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    return str(cert_path), str(key_path), device_id


def _ctrl_c_if_running(task: asyncio.Task, sent: list[bool]) -> None:
    """Chạy trong vòng lặp của lệnh (thread chính): Ctrl+C thật nếu lệnh còn chạy."""
    if task.done():
        sent.append(False)
        return
    sent.append(True)
    signal.raise_signal(signal.SIGINT)


class StdinStub:
    """Thay `teleport.cli.StdinReader` cho test gọi `main()`: không đọc stdin thật; nhớ vòng lặp, task
    chính và hàng đợi dòng của lệnh; tự gõ `answer` ngay sau khi lời hỏi hiện ra."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.task: asyncio.Task | None = None
        self.lines: asyncio.Queue | None = None
        self.answer: str | None = "c"
        self.ctrl_c_sent: list[bool] = []

    def ctrl_c_from_thread(self) -> None:
        """Gọi từ thread khác: Ctrl+C tới lệnh (bỏ qua nếu vòng lặp đã đóng)."""
        try:
            self.loop.call_soon_threadsafe(_ctrl_c_if_running, self.task, self.ctrl_c_sent)
        except RuntimeError:
            self.ctrl_c_sent.append(False)


@pytest.fixture
def stdin_stub(monkeypatch):
    from teleport import cli

    stub = StdinStub()

    class Reader:
        def __init__(self, loop, lines) -> None:
            stub.loop, stub.lines, stub.task = loop, lines, asyncio.current_task()

        def start(self) -> None:
            pass

    real_on_prompt = cli._Prompter.on_prompt

    def on_prompt(self, prompt):
        real_on_prompt(self, prompt)
        if stub.answer is not None:
            stub.lines.put_nowait((time.perf_counter(), stub.answer))

    monkeypatch.setattr(cli, "StdinReader", Reader)
    monkeypatch.setattr(cli._Prompter, "on_prompt", on_prompt)
    return stub


def pair_results(out: str) -> list[dict]:
    events = [json.loads(line) for line in out.splitlines() if line.strip()]
    return [e for e in events if e.get("event") == "pair_result"]


def main_pair_argv(d, port: int, *, json_mode: bool) -> list[str]:
    mode = ["--json"] if json_mode else []
    return ["--config-dir", str(d), "pair", f"{LOCAL}:{port}", *mode, "--name", "A", *NODE_OPTS]


# --- H1: đầu-cuối --------------------------------------------------------------------------------------


@with_marks(socket_test)
async def test_h1_listen_shows_real_code_before_name_with_fake_code(tmp_path, fast_cli, cli_runs):
    """Kế hoạch H1, E2E: raw client tên “PC-A:   382 104” tới `listen`: dòng mã thật đứng trước mọi
    dòng có “PC-A”, mã giả chỉ nằm trong “…” ở dòng tên."""
    b_dir = tmp_path / "B"
    load_or_create_identity(b_dir)
    listen = cli_runs("listen", listen_argv(b_dir, json_mode=False))
    port = await listen_port_text(listen)
    head = len(listen.text())
    raw = load_or_create_identity(tmp_path / "R")
    name = "PC-A:   382 104"
    client = await RawInitiator.connect(port)
    try:
        await client.start(raw.device_id, name, raw.cert_pem())
        code = await client.to_code(raw.fingerprint, raw.key_path)
        await listen.wait_text(ASK)
        lines = listen.text()[head:].split("\n")
        code_line = f"Mã ghép đôi:   {_spaced(code)}"
        name_line = f"Máy kia tự xưng là “{name}” (mã máy {raw.device_id[:8]}, 127.0.0.1)."
        assert lines == [HEADER_LISTEN, code_line, name_line, ASK]
        check_code_first(lines, code, name_is_distinctive=True)
        code_at = lines.index(code_line)
        assert all(k > code_at for k, line in enumerate(lines) if "PC-A" in line)
        if code != "382104":
            assert [line for line in lines if "382 104" in line] == [name_line]
    finally:
        client.abort()


@with_marks(socket_test)
async def test_h1_pair_shows_real_code_before_name_with_fake_code(tmp_path, fast_cli, cli_runs):
    """H1 ở vai khởi xướng: máy trả lời (kẻ đứng giữa) tự xưng “PC-A:   382 104” với `teleport pair`."""
    m = load_or_create_identity(tmp_path / "M")
    name = "PC-A:   382 104"
    with ThreadResponder(m.cert_path, m.key_path, m.device_id, name=name) as peer:
        pair = cli_runs("pair", pair_argv(tmp_path / "A", peer.port, json_mode=False))
        await pair.wait_text(ASK)
        assert peer.code is not None
        text = pair.text()
        code_line = f"Mã ghép đôi:   {_spaced(peer.code)}"
        lines = text[text.index(HEADER_PAIR) :].split("\n")
        assert lines == [
            HEADER_PAIR,
            code_line,
            f"Máy kia tự xưng là “{name}” (mã máy {m.device_id[:8]}, 127.0.0.1).",
            ASK,
        ]
        assert "PC-A" not in text[: text.index(code_line)]
        assert peer.proof_ok is True, "chữ ký của `teleport pair` trong pair_nonce phải hợp lệ"
        pair.say("k")
        assert await asyncio.wait_for(pair.task, 10) == 1


# --- M5: tên đã lưu ------------------------------------------------------------------------------------


@pytest.mark.parametrize(("listening", "role"), PROMPT_MODES, ids=PROMPT_MODE_IDS)
async def test_m5_prompt_shows_saved_name_and_rename_lines_in_both_roles(listening, role):
    """mvp mục 7.2: cùng một dòng tên đã lưu cho cả hai vai, rồi dòng đổi tên."""
    prompt = _prompt(role, 0, peer_name="Laptop-Bob", known_name="PC-Nha")
    text, err = render_prompt(prompt, listening=listening)
    assert text.split("\n") == [
        HEADER_LISTEN if listening else HEADER_PAIR,
        "Mã ghép đôi:   123 456",
        "Máy kia tự xưng là “Laptop-Bob” (mã máy abababab, 192.168.1.5).",
        "Máy này đã ghép đôi với mã máy abababab trước đây, tên đã lưu: “PC-Nha”.",
        "Ghép đôi xong, tên sẽ đổi thành “Laptop-Bob”.",
        ASK,
    ]
    assert "giữ nguyên tên" not in text
    assert err == ""


@pytest.mark.parametrize(("listening", "role"), PROMPT_MODES, ids=PROMPT_MODE_IDS)
async def test_m5_prompt_without_rename_line_when_saved_name_equals_claimed(listening, role):
    prompt = _prompt(role, 0, peer_name="PC-Nha", known_name="PC-Nha")
    text, err = render_prompt(prompt, listening=listening)
    assert text.split("\n") == [
        HEADER_LISTEN if listening else HEADER_PAIR,
        "Mã ghép đôi:   123 456",
        "Máy kia tự xưng là “PC-Nha” (mã máy abababab, 192.168.1.5).",
        KNOWN.format(id8="abababab", name="PC-Nha"),
        ASK,
    ]
    assert "tên sẽ đổi thành" not in text
    assert err == ""


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        ("PC-A" + "\u2800" * 20 + "382 104", "PC-A" + "·" * 20 + "382 104"),
        ("B" * 64, "B" * 31 + "…"),
        ("Mã ghép đôi:   111 222", "Mã ghép đôi:   111 222"),
    ],
    ids=["braille-blank", "64-chars", "code-label"],
)
async def test_m5_rename_line_shows_claimed_name_through_display_name(name, shown):
    prompt = _prompt("responder", 0, peer_name=name, known_name="PC-Nha")
    text, _ = render_prompt(prompt, listening=True)
    lines = text.split("\n")
    assert RENAME.format(name=shown) in lines
    # Dòng đổi tên (tên do máy kia chọn) vẫn nằm sau dòng mã; chỉ có đúng một dòng mã thật.
    check_code_first(lines, "123456")
    assert lines.index(RENAME.format(name=shown)) > lines.index("Mã ghép đôi:   123 456")


@pytest.mark.parametrize(("listening", "role"), PROMPT_MODES, ids=PROMPT_MODE_IDS)
async def test_m5_prompt_without_saved_name_has_no_saved_name_line(listening, role):
    text, _ = render_prompt(_prompt(role, 0, peer_name="Laptop-Bob"), listening=listening)
    assert "tên đã lưu" not in text
    assert "Máy này đã ghép đôi" not in text


@pytest.mark.parametrize(
    ("known", "shown"),
    [("PC\u2800\u2800Nha 382 104", "PC··Nha 382 104"), ("K" * 64, "K" * 31 + "…")],
    ids=["blank-chars", "64-chars"],
)
async def test_m5_saved_name_is_shown_like_peer_name(known, shown):
    text, _ = render_prompt(_prompt("responder", 0, known_name=known), listening=True)
    assert KNOWN.format(id8="abababab", name=shown) in text.split("\n")


@pytest.mark.parametrize("known", [None, "PC-Nha"])
async def test_m5_json_prompt_has_known_name(known):
    text, _ = render_prompt(_prompt("initiator", 0, known_name=known), listening=False, json_mode=True)
    [ev] = [json.loads(line) for line in text.splitlines() if line.strip()]
    assert "known_name" in ev
    assert ev["known_name"] == known


def _finished(
    role: str,
    outcome: str,
    *,
    code_shown: bool,
    peer_name: str | None = "A",
    known_name: str | None = None,
    device=None,
    address: str = "192.168.1.5",
):
    from teleport.app.pairing import PairingFinished, PairingOutcome
    from teleport.core.pairing import Role

    return PairingFinished(
        session_id=3,
        role=Role(role),
        outcome=PairingOutcome(outcome),
        address=address,
        port=None if role == "responder" else 47474,
        peer_name=peer_name,
        peer_device_id="ab" * 16,
        peer_reason=None,
        device=device,
        known_name=known_name,
        code_shown=code_shown,
    )


def _trusted(name: str):
    from teleport.trust.store import TrustedDevice

    return TrustedDevice(
        device_id="ab" * 16,
        name=name,
        fingerprint="cd" * 32,
        cert_pem="-----BEGIN CERTIFICATE-----\n-----END CERTIFICATE-----\n",
        paired_at=datetime.datetime(2026, 10, 23, tzinfo=datetime.UTC),
    )


@pytest.mark.parametrize("role", ["responder", "initiator"])
def test_m5_paired_message_uses_saved_device_name(role):
    from teleport.cli import outcome_message

    result = _finished(role, "paired", code_shown=True, peer_name="Laptop-Bob", device=_trusted("PC-Nha"))
    assert outcome_message(result) == ["Đã ghép đôi với PC-Nha."]


def test_m5_paired_message_without_device_uses_peer_name():
    from teleport.cli import outcome_message

    assert outcome_message(_finished("initiator", "paired", code_shown=True)) == ["Đã ghép đôi với A."]


def test_outcome_message_shows_peer_name_through_display_name():
    """Tên do máy kia gửi trong câu kết quả ghép đôi cũng qua `_name_label`, như ở `list`."""
    from teleport.cli import outcome_message

    sneaky = "PC-Nhaㅤ"
    paired = _finished("initiator", "paired", code_shown=True, device=_trusted(sneaky))
    assert outcome_message(paired) == ["Đã ghép đôi với PC-Nha·."]
    not_done = _finished("responder", "user_rejected", code_shown=True, peer_name=sneaky)
    assert "PC-Nha·" in outcome_message(not_done)[0]


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_m5_listen_stranger_with_stolen_public_cert_is_rejected_before_code(
    tmp_path, fast_cli, cli_runs, json_mode
):
    """Protocol 5.1, 5.5: B tin V tên “PC-Nha”; máy lạ M gửi chứng chỉ CÔNG KHAI của V với tên “Laptop-Bob”
    nhưng chỉ ký được bằng khóa của chính nó → `listen` không hiện mã, không hỏi, báo phiên dừng
    trước khi hiện mã; M nhận `pair_abort{invalid}`; `trusted.json` không đổi; `listen` vẫn chạy."""
    b_dir = tmp_path / "B"
    load_or_create_identity(b_dir)
    v = load_or_create_identity(tmp_path / "V")
    m = load_or_create_identity(tmp_path / "M")
    TrustStore.load(b_dir).add(peer_cert_from_pem(v.cert_pem()), "PC-Nha")
    before = (b_dir / "trusted.json").read_bytes()
    listen = cli_runs("listen", listen_argv(b_dir, json_mode=json_mode))
    if json_mode:
        port = (await listen.wait_event("listening"))["port"]
    else:
        port = await listen_port_text(listen)
    head = len(listen.text())
    client = await RawInitiator.connect(port)
    try:
        await client.start(v.device_id, "Laptop-Bob", v.cert_pem())  # không có khóa riêng của V
        await client.send_signed_nonce(v.fingerprint, m.key_path)
        abort = await client.recv_type("pair_abort")
        assert abort == {"type": "pair_abort", "reason": "invalid"}
    finally:
        client.abort()
    if json_mode:
        result = await listen.wait_event("pair_result")
        assert result["outcome"] == "protocol_error"
        assert "đã yêu cầu ghép đôi nhưng phiên dừng trước khi hiện mã" in result["message"]
        assert listen.events_of("pair_prompt") == []
    else:
        await listen.wait_text("đã yêu cầu ghép đôi nhưng phiên dừng trước khi hiện mã.")
        tail = listen.text()[head:]
        assert ASK not in tail
        assert "Mã ghép đôi:" not in tail
        assert "Nếu mã trên hai máy khác nhau" not in tail
    assert not listen.task.done()
    assert (b_dir / "trusted.json").read_bytes() == before
    saved = TrustStore.load(b_dir).get(v.device_id)
    assert (saved.name, saved.fingerprint) == ("PC-Nha", v.fingerprint)


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_m5_listen_real_repair_with_new_name_updates_saved_name(
    tmp_path, fast_cli, cli_runs, json_mode
):
    """Chính V (có khóa riêng) ghép đôi lại với tên mới “Laptop-Mới”: lời hỏi có dòng tên đã lưu và
    dòng “tên sẽ đổi thành”; xác nhận xong B lưu tên mới (cả trên đĩa) và báo “Đã ghép đôi với Laptop-Mới.”"""
    b_dir = tmp_path / "B"
    load_or_create_identity(b_dir)
    v = load_or_create_identity(tmp_path / "V")
    TrustStore.load(b_dir).add(peer_cert_from_pem(v.cert_pem()), "PC-Nha")
    listen = cli_runs("listen", listen_argv(b_dir, json_mode=json_mode))
    if json_mode:
        port = (await listen.wait_event("listening"))["port"]
    else:
        port = await listen_port_text(listen)
    v8 = v.device_id[:8]
    client = await RawInitiator.connect(port)
    try:
        await client.start(v.device_id, "Laptop-Mới", v.cert_pem())
        code = await client.to_code(v.fingerprint, v.key_path)
        if json_mode:
            prompt = await listen.wait_event("pair_prompt")
            assert (prompt["peer_name"], prompt["known_name"]) == ("Laptop-Mới", "PC-Nha")
            assert (prompt["peer_device_id"], prompt["code"]) == (v.device_id, code)
        else:
            await listen.wait_text(ASK)
            lines = listen.text().split("\n")
            i = lines.index(f"Mã ghép đôi:   {_spaced(code)}")
            assert lines[i + 1 :] == [
                f"Máy kia tự xưng là “Laptop-Mới” (mã máy {v8}, 127.0.0.1).",
                KNOWN.format(id8=v8, name="PC-Nha"),
                RENAME.format(name="Laptop-Mới"),
                ASK,
            ]
        listen.say("c")
        await client.recv_type("pair_confirm")
        client.send({"type": "pair_confirm"})
        await client.writer.drain()
        if json_mode:
            result = await listen.wait_event("pair_result")
            assert result["outcome"] == "paired"
            assert result["message"] == "Đã ghép đôi với Laptop-Mới."
        else:
            await listen.wait_text("Đã ghép đôi với Laptop-Mới.")
    finally:
        client.abort()
    saved = TrustStore.load(b_dir).get(v.device_id)
    assert (saved.name, saved.fingerprint) == ("Laptop-Mới", v.fingerprint)
    assert "PC-Nha" not in (b_dir / "trusted.json").read_text("utf-8")


# --- Chứng minh giữ khóa: danh tính có khóa không khớp chứng chỉ → `listen` / `pair` thoát 1 ----------


def _break_key(directory, tmp_path) -> None:
    other = load_or_create_identity(tmp_path / "khoa-khac")
    (directory / "device.key").write_bytes(other.key_path.read_bytes())


@pytest.mark.integration
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("command", ["listen", "pair"])
async def test_key_not_matching_cert_makes_listen_and_pair_exit_1(
    tmp_path, fast_cli, cli_runs, command, json_mode
):
    d = tmp_path / "X"
    load_or_create_identity(d)
    _break_key(d, tmp_path)
    argv = (
        listen_argv(d, json_mode=json_mode) if command == "listen" else pair_argv(d, 9, json_mode=json_mode)
    )
    run = cli_runs(command, argv)
    assert await asyncio.wait_for(run.task, 10) == 1
    text = run.text()
    assert "Traceback" not in text
    if json_mode:
        errors = [e for e in run.events() if "error" in e]
        assert errors and errors[-1]["error"] == "identity_error", text
    else:
        assert run.err.getvalue().startswith("Lỗi: "), text
    assert lock_is_free(d)


@pytest.mark.integration
@pytest.mark.parametrize("command", ["listen", "pair"])
async def test_signer_identity_error_at_node_start_exits_1(
    tmp_path, fast_cli, cli_runs, monkeypatch, command
):
    """`load_pairing_signer` ném IdentityError (khóa bị thay sau khi danh tính đã nạp) → xử lý như
    lỗi danh tính hiện có: in câu lỗi, thoát 1, nhả `node.lock`. Hàm thật được gọi với một khóa khác
    để lỗi là lỗi thật của trust."""
    import dataclasses

    from teleport.trust import identity as trust_identity

    real = trust_identity.load_pairing_signer
    foreign = load_or_create_identity(tmp_path / "khoa-khac")
    calls: list[int] = []

    def broken(identity):
        calls.append(1)
        return real(dataclasses.replace(identity, key_path=foreign.key_path))

    monkeypatch.setattr(trust_identity, "load_pairing_signer", broken)
    from teleport.app import pairing as app_pairing

    if hasattr(app_pairing, "load_pairing_signer"):
        monkeypatch.setattr(app_pairing, "load_pairing_signer", broken)
    d = tmp_path / "X"
    argv = listen_argv(d, json_mode=True) if command == "listen" else pair_argv(d, 9, json_mode=True)
    run = cli_runs(command, argv)
    assert await asyncio.wait_for(run.task, 10) == 1
    assert calls, "PairingService phải nạp bộ ký lúc khởi tạo node"
    errors = [e for e in run.events() if "error" in e]
    assert errors and errors[-1]["error"] == "identity_error", run.text()
    assert "Traceback" not in run.text()
    assert lock_is_free(d)


# --- L4: câu báo đúng ngữ cảnh ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", UNFINISHED)
@pytest.mark.parametrize("role", ["initiator", "responder"])
def test_l4_unfinished_after_code_was_shown_keeps_mismatch_warning(role, outcome):
    from teleport.cli import outcome_message

    assert outcome_message(_finished(role, outcome, code_shown=True)) == [MVP_NOT_DONE.format(x="A")]


@pytest.mark.parametrize("outcome", UNFINISHED)
def test_l4_initiator_stopped_before_code_asks_to_retry(outcome):
    from teleport.cli import outcome_message

    msg = outcome_message(_finished("initiator", outcome, code_shown=False))
    assert msg == [NOT_SHOWN_INITIATOR.format(x="A")]


@pytest.mark.parametrize("outcome", UNFINISHED)
def test_l4_responder_stopped_before_code_names_unverified_peer(outcome):
    from teleport.cli import outcome_message

    msg = outcome_message(_finished("responder", outcome, code_shown=False, peer_name="Raw-X"))
    assert msg == [NOT_SHOWN_RESPONDER.format(x="Raw-X")]


@pytest.mark.parametrize("code_shown", [False, True])
def test_l4_identity_conflict_as_responder_is_one_line_without_unpair(code_shown):
    from teleport.cli import outcome_message

    result = _finished(
        "responder", "identity_conflict", code_shown=code_shown, peer_name="Laptop-Bob", known_name="PC-Nha"
    )
    msg = outcome_message(result)
    assert msg == [CONFLICT_RESPONDER.format(known="PC-Nha")]
    assert "unpair" not in " ".join(msg)


def test_l4_identity_conflict_as_initiator_keeps_unpair_hint():
    from teleport.cli import outcome_message

    result = _finished(
        "initiator", "identity_conflict", code_shown=False, peer_name="PC-Moi", known_name="PC-Nha"
    )
    assert outcome_message(result) == [
        CONFLICT_INITIATOR[0].format(known="PC-Nha"),
        CONFLICT_INITIATOR[1].format(id8="abababab"),
    ]


@with_marks(socket_test)
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
async def test_l4_listen_session_closed_before_code_says_code_was_not_shown(
    tmp_path, fast_cli, cli_runs, json_mode
):
    """Kế hoạch L4, E2E: raw client đóng ngay sau `pair_commit` → `listen` in câu vai trả lời, không
    có “Nếu mã trên hai máy khác nhau”."""
    listen = cli_runs("listen", listen_argv(tmp_path / "B", json_mode=json_mode))
    if json_mode:
        port = (await listen.wait_event("listening"))["port"]
    else:
        port = await listen_port_text(listen)
    raw = load_or_create_identity(tmp_path / "R")
    client = await RawInitiator.connect(port)
    try:
        await client.start(raw.device_id, "Raw-X", raw.cert_pem())
        await client.recv_type("pair_commit")
    finally:
        client.abort()
    expected = NOT_SHOWN_RESPONDER.format(x="Raw-X")
    if json_mode:
        result = await listen.wait_event("pair_result")
        assert result["message"] == expected
        assert result["outcome"] in UNFINISHED
        assert listen.events_of("pair_prompt") == []
    else:
        await listen.wait_text(expected)
        assert "Nếu mã trên hai máy khác nhau" not in listen.text()
        assert ASK not in listen.text()
    assert not listen.task.done()


# --- M1: máy kia gửi chứng chỉ có SAN lạ ------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_m1_pair_with_server_sending_x400_san_cert_reports_invalid_identity(
    tmp_path, capsys, caplog, fast_cli, json_mode
):
    """Kế hoạch M1 (CLI): `teleport pair` tới server mang chứng chỉ SAN x400Address → mã 1, câu mvp
    mục 8 “gửi danh tính không hợp lệ”, không traceback, không lưu gì."""
    cert_path, key_path, device_id = write_x400_san_cert(tmp_path / "evil")
    d = tmp_path / "A"
    with ThreadResponder(cert_path, key_path, device_id, pair=False) as evil:
        with caplog.at_level(logging.WARNING):
            code = run_main(main_pair_argv(d, evil.port, json_mode=json_mode))
        port = evil.port
    captured = capsys.readouterr()
    text = captured.out + captured.err
    expected = MVP_INVALID_IDENTITY.format(target=f"{LOCAL}:{port}")
    assert code == 1, text
    assert "Traceback" not in text and "Traceback" not in caplog.text
    assert [r for r in caplog.records if r.levelno >= logging.ERROR or r.exc_info] == []
    assert CANCELLED_TEXT not in text
    if json_mode:
        [result] = pair_results(captured.out)
        assert (result["outcome"], result["message"]) == ("identity_mismatch", expected)
    else:
        assert expected in text, text
    assert TrustStore.load(d).devices() == []
    assert lock_is_free(d)


@pytest.mark.slow
@pytest.mark.integration
def test_m1_pair_subprocess_with_x400_san_cert_has_no_traceback_on_stderr(tmp_path, procs):
    """Như trên nhưng với tiến trình thật: stderr thật không có “Traceback”."""
    cert_path, key_path, device_id = write_x400_san_cert(tmp_path / "evil")
    with ThreadResponder(cert_path, key_path, device_id, pair=False) as evil:
        proc = procs(main_pair_argv(tmp_path / "A", evil.port, json_mode=False))
        code = proc.finish(30)
        port = evil.port
    out = "\n".join(proc.out)
    err = proc.err_text()
    assert code == 1, out + err
    assert MVP_INVALID_IDENTITY.format(target=f"{LOCAL}:{port}") in out, out + err
    assert "Traceback" not in err and "Traceback" not in out


# --- M4: Ctrl+C sau khi đã có kết quả ---------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_m4_ctrl_c_while_closing_after_paired_reports_paired(
    tmp_path, capsys, fast_cli, monkeypatch, stdin_stub, json_mode
):
    """Kế hoạch M4 (CLI): hai bên đã xác nhận, máy kia không trả close_notify nên lệnh đang chờ đóng gọn;
    Ctrl+C lúc đó → mã 0, “Đã ghép đôi với …”, không có “Đã hủy ghép đôi.”; `--json` đúng một
    `pair_result` `paired`."""
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 3.0)  # cửa sổ đóng gọn đủ rộng để Ctrl+C rơi vào
    m = load_or_create_identity(tmp_path / "M")
    d = tmp_path / "A"
    responder = ThreadResponder(
        m.cert_path,
        m.key_path,
        m.device_id,
        close_notify=False,
        on_peer_closing=stdin_stub.ctrl_c_from_thread,
    )
    with responder as peer:
        code = run_main(main_pair_argv(d, peer.port, json_mode=json_mode))
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert peer.errors == [], peer.errors
    assert stdin_stub.ctrl_c_sent == [True], "Ctrl+C phải tới lúc lệnh còn chạy (đang đóng kết nối)"
    assert TrustStore.load(d).get(m.device_id) is not None, "hai bên đã xác nhận: A đã lưu M"
    assert code == 0, text
    assert CANCELLED_TEXT not in text
    if json_mode:
        assert [r["outcome"] for r in pair_results(captured.out)] == ["paired"], captured.out
    else:
        assert text.count("Đã ghép đôi với M.") == 1, text
    assert "Traceback" not in text
    assert lock_is_free(d)


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
@pytest.mark.parametrize("outcome", ["paired", "unreachable"])
def test_m4_ctrl_c_in_node_close_after_result_prints_nothing_more(
    tmp_path, capsys, fast_cli, monkeypatch, stdin_stub, outcome, json_mode
):
    """Kế hoạch M4 (CLI, cửa sổ K4 gốc): Ctrl+C trong `node.close()` sau khi đã in kết quả → mã theo kết
    quả, không in thêm dòng nào."""
    from teleport.app import node as node_mod

    real_close = node_mod.Node.close
    sent: list[bool] = []

    async def close(self):
        if not sent:
            asyncio.get_running_loop().call_soon(_ctrl_c_if_running, stdin_stub.task, sent)
        return await real_close(self)

    monkeypatch.setattr(node_mod.Node, "close", close)
    d = tmp_path / "A"
    if outcome == "paired":
        m = load_or_create_identity(tmp_path / "M")
        with ThreadResponder(m.cert_path, m.key_path, m.device_id) as peer:
            code = run_main(main_pair_argv(d, peer.port, json_mode=json_mode))
        last = "Đã ghép đôi với M."
    else:
        s = socket.socket()
        s.bind((LOCAL, 0))
        port = s.getsockname()[1]
        s.close()
        code = run_main(main_pair_argv(d, port, json_mode=json_mode))
        last = (
            f"Không kết nối được tới 127.0.0.1:{port}. Hãy kiểm tra Teleport đang chạy trên máy đó, "
            "hai máy dùng chung một mạng, và tường lửa cho phép Teleport."
        )
    captured = capsys.readouterr()
    assert sent == [True], "Ctrl+C phải tới lúc node.close() đang chạy"
    assert code == (0 if outcome == "paired" else 1), captured.out + captured.err
    assert CANCELLED_TEXT not in captured.out + captured.err
    if json_mode:
        [result] = pair_results(captured.out)
        assert result["outcome"] == outcome
        assert json.loads(captured.out.splitlines()[-1])["event"] == "pair_result"
    else:
        assert captured.out.splitlines()[-1] == last, captured.out
        assert captured.out.count(last) == 1
    assert lock_is_free(d)


def _fake_run_pair(monkeypatch, *, result, seen_name=None, emitted=False):
    """Thay `teleport.cli.run_pair`: ghi `_PairState` như kế hoạch M4 rồi nhận Ctrl+C thật.

    `emitted=True`: giả như `run_pair` đã in kết quả (in một dòng đánh dấu)."""
    from teleport import cli

    async def fake(args, lines, out, err, *, state=None):
        assert state is not None, "cmd_pair phải truyền _PairState cho run_pair (kế hoạch M4)"
        state.seen_name = seen_name
        state.result = result
        if emitted:
            print("<đã in kết quả>", file=out, flush=True)
            state.emitted = True
        asyncio.get_running_loop().call_soon(_ctrl_c_if_running, asyncio.current_task(), [])
        await asyncio.Event().wait()

    monkeypatch.setattr(cli, "run_pair", fake)


@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_m4_cmd_pair_prints_result_recorded_before_ctrl_c(capsys, monkeypatch, tmp_path, json_mode):
    _fake_run_pair(monkeypatch, result=_finished("initiator", "paired", code_shown=True, peer_name="B"))
    argv = ["--config-dir", str(tmp_path), "pair", f"{LOCAL}:47474", *(["--json"] if json_mode else [])]
    assert run_main(argv) == 0
    captured = capsys.readouterr()
    assert CANCELLED_TEXT not in captured.out + captured.err
    if json_mode:
        [result] = pair_results(captured.out)
        assert (result["outcome"], result["message"]) == ("paired", "Đã ghép đôi với B.")
    else:
        assert captured.out.count("Đã ghép đôi với B.") == 1


def test_m4_cmd_pair_uses_seen_name_for_recorded_failure(capsys, monkeypatch, tmp_path):
    result = _finished("initiator", "unreachable", code_shown=False, peer_name=None, address="192.0.2.10")
    _fake_run_pair(monkeypatch, result=result, seen_name="B")
    assert run_main(["--config-dir", str(tmp_path), "pair", "B"]) == 1
    out = capsys.readouterr().out
    assert MVP_SEEN_UNREACHABLE.format(x="B") in out
    assert HOTSPOT_HINT in out
    assert CANCELLED_TEXT not in out


@pytest.mark.parametrize("outcome", ["paired", "unreachable"])
def test_m4_cmd_pair_after_result_was_printed_adds_nothing(capsys, monkeypatch, tmp_path, outcome):
    _fake_run_pair(monkeypatch, result=_finished("initiator", outcome, code_shown=True), emitted=True)
    code = run_main(["--config-dir", str(tmp_path), "pair", f"{LOCAL}:47474"])
    assert code == (0 if outcome == "paired" else 1)
    captured = capsys.readouterr()
    assert captured.out == "<đã in kết quả>\n"
    assert captured.err == ""


@pytest.mark.parametrize("recorded", [None, "cancelled"])
@pytest.mark.parametrize("json_mode", [False, True], ids=["text", "json"])
def test_m4_cmd_pair_without_real_result_still_says_cancelled(
    capsys, monkeypatch, tmp_path, recorded, json_mode
):
    result = None if recorded is None else _finished("initiator", recorded, code_shown=False)
    _fake_run_pair(monkeypatch, result=result)
    argv = ["--config-dir", str(tmp_path), "pair", f"{LOCAL}:47474", *(["--json"] if json_mode else [])]
    assert run_main(argv) == 1
    captured = capsys.readouterr()
    if json_mode:
        [obj] = pair_results(captured.out)
        assert (obj["outcome"], obj["message"]) == ("cancelled", CANCELLED_TEXT)
    else:
        assert captured.out.count(CANCELLED_TEXT) == 1


# --- H1 (nên làm thêm trong kế hoạch): tên trong sự kiện của `listen` và dòng “Đang kết nối tới” ---


WEIRD_NAME = "PC-A" + chr(0x2800) * 3 + "382 104" + "x" * 50  # 64 ký tự
WEIRD_SHOWN = "PC-A" + "·" * 3 + "382 104" + "x" * 17 + "…"  # 31 cột + …


def _view(name: str, *, online: bool = True):
    from teleport.app.devices import DeviceView

    return DeviceView(
        device_id="ab" * 16,
        name=name,
        os="windows",
        paired=False,
        online=online,
        connected=False,
        addresses=("192.0.2.30",) if online else (),
        port=47474 if online else None,
    )


@pytest.mark.parametrize("kind", ["online", "offline", "connected", "disconnected"])
def test_h1_listen_device_events_show_name_through_display_name(kind):
    from teleport.app.node import DeviceConnected, DeviceDisconnected, DeviceOffline, DeviceOnline
    from teleport.cli import _Output, _print_event

    assert _valid_name(WEIRD_NAME) and len(WEIRD_NAME) == 64
    view = _view(WEIRD_NAME, online=kind != "offline")
    event = {
        "online": lambda: DeviceOnline(view),
        "offline": lambda: DeviceOffline(view),
        "connected": lambda: DeviceConnected(view, outgoing=True),
        "disconnected": lambda: DeviceDisconnected(view),
    }[kind]()
    out, err = io.StringIO(), io.StringIO()
    _print_event(_Output(out, err, False), event)
    text = out.getvalue()
    assert f"“{WEIRD_SHOWN}” (abababab" in text, text
    assert WEIRD_NAME not in text
    assert not set(text) & _BLANKS


@with_marks(socket_test)
async def test_h1_pair_by_name_connecting_line_shows_name_through_display_name(
    tmp_path, fast_links, cli_mdns, fake_open_pairing, browse_instant, cli_runs
):
    c = load_or_create_identity(tmp_path / "peer-C")
    cli_mdns.seed = {c.device_id: discovered(c.device_id, WEIRD_NAME, 47474, addresses=("192.0.2.30",))}
    pair = cli_runs("pair", name_pair_argv(tmp_path / "A", c.device_id[:8]))
    assert await asyncio.wait_for(pair.task, 15) == 1, pair.text()
    expected = f"Đang kết nối tới “{WEIRD_SHOWN}” ({c.device_id[:8]}) tại 192.0.2.30:47474…"
    assert expected in pair.text().split("\n"), pair.text()
    assert fake_open_pairing == [(["192.0.2.30"], 47474)]
