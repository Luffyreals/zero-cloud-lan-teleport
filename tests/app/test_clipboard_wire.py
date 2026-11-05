"""Message `clipboard` trên mạng với node hiện tại (spec P5-0 việc 7, tiêu chí 5.7, sửa 9.9).

Node chưa đồng bộ clipboard (P5-1 mới nối `app`), nên:
(a) `clipboard` hợp lệ trên kết nối điều khiển bị bỏ qua: kết nối không đóng, lượt gửi file sau đó
    xong trên **cùng** kết nối;
(b) `clipboard` sai dạng (một message tự cho thấy sai) → kết nối điều khiển đóng `protocol_error`
    (protocol §3.3, loại lỗi thứ nhất), rồi nối lại được;
(c) giả node cũ chưa biết `clipboard` (`_MESSAGE_TYPES` không có nó) → bỏ qua, không đóng;
(d) `clipboard` trên kết nối ghép đôi → `pair_abort{invalid}` rồi đóng.

(b), (c) gửi **khung thô** (`Connection._send_frame`), vì `Clipboard` sai không dựng được và ở (c)
`to_dict` bên gửi cũng không còn biết `clipboard`.
"""

import asyncio
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

import pytest

from teleport.core import messages
from teleport.core.framing import HEADER, encode_message
from teleport.trust.identity import load_or_create_identity

pytestmark = [
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
integration = pytest.mark.integration

LOCAL = "127.0.0.1"
INVALID = {"type": "pair_abort", "reason": "invalid"}
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def clip_dict(text: str = "xin chào", **over) -> dict:
    raw = text.encode("utf-8")
    d = {
        "type": "clipboard",
        "clip_id": "0123456789abcdef" * 2,
        "kind": "text",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "total": len(raw),
        "index": 0,
        "count": 1,
        "data": text,
    }
    d.update(over)
    return d


def valid_clipboards() -> list:
    """Vài `Clipboard` hợp lệ: text một mảnh, PNG hai mảnh, kind lạ đúng dạng."""
    from teleport.core.messages import Clipboard

    png = PNG_SIGNATURE + b"pixels"
    png_sha = hashlib.sha256(png).hexdigest()
    common = {"clip_id": "f" * 32, "kind": "image/png", "sha256": png_sha, "total": len(png), "count": 2}
    fields = {k: v for k, v in clip_dict().items() if k != "type"}
    return [
        Clipboard(**fields),
        Clipboard(index=0, data=base64.b64encode(png[:8]).decode(), **common),
        Clipboard(index=1, data=base64.b64encode(png[8:]).decode(), **common),
        Clipboard(clip_id="e" * 32, kind="text/html", sha256="0" * 64, total=3, index=0, count=1, data="<b>"),
    ]


def raw_frame(d: dict) -> bytes:
    """Khung với JSON thoát ASCII: chở được cả surrogate lẻ dạng `\\ud800` như máy độc gửi."""
    body = json.dumps(d, separators=(",", ":")).encode("ascii")
    return HEADER.pack(len(body)) + body


def make_file(directory: Path, name: str, size: int) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_bytes(os.urandom(size))
    return path


async def run_transfer(net, paths, timeout: float = 30.0):
    key = await net.B.transfers.send(net.A.id, list(paths))
    fin_b = await net.B.trec.wait_finished(key.transfer_id, timeout)
    fin_a = await net.A.trec.wait_finished(key.transfer_id, timeout)
    return fin_a, fin_b


def teleport_records(caplog, min_level: int) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("teleport") and r.levelno >= min_level]


async def assert_transfer_done(net, name: str = "f.bin", size: int = 300_000) -> None:
    src = make_file(net.src, name, size)
    fin_a, fin_b = await run_transfer(net, [src])
    assert str(fin_a.result) == "done", fin_a
    assert str(fin_b.result) == "done", fin_b
    assert (net.receive_dir / name).read_bytes() == src.read_bytes()


def control_pair(net):
    conn_a = net.A.control_connection(net.B.id)
    conn_b = net.B.control_connection(net.A.id)
    assert conn_a is not None and conn_b is not None
    return conn_a, conn_b


# --- (a) clipboard hợp lệ bị bỏ qua --------------------------------------------------------------


@pytest.mark.slow
@integration
async def test_valid_clipboard_on_control_is_ignored_and_same_connection_carries_transfer(
    transfer_nodes, app_helpers, caplog
):
    caplog.set_level(logging.DEBUG, logger="teleport")
    net = await transfer_nodes()
    conn_a, conn_b = control_pair(net)
    for m in valid_clipboards():
        await conn_b.send(m)  # B → A
        await conn_a.send(m)  # và chiều ngược lại
    await asyncio.sleep(0.5)
    assert not conn_a.closed and not conn_b.closed
    assert control_pair(net) == (conn_a, conn_b)
    await assert_transfer_done(net)
    assert control_pair(net) == (conn_a, conn_b), "lượt gửi phải chạy trên cùng kết nối điều khiển"
    assert not conn_a.closed and not conn_b.closed
    assert not [r for r in teleport_records(caplog, logging.DEBUG) if "protocol_error" in r.getMessage()]
    errors = teleport_records(caplog, logging.ERROR)
    assert errors == [], [r.getMessage() for r in errors]


@integration
async def test_valid_clipboard_during_transfer_does_not_disturb_it(transfer_nodes):
    net = await transfer_nodes()
    conn_a, conn_b = control_pair(net)
    src = make_file(net.src, "lon.bin", 4 * 1024 * 1024)
    key = await net.B.transfers.send(net.A.id, [src])
    for _ in range(5):
        for m in valid_clipboards():
            await conn_b.send(m)
        await asyncio.sleep(0.01)
    fin_a = await net.A.trec.wait_finished(key.transfer_id, 30)
    assert str(fin_a.result) == "done", fin_a
    assert control_pair(net) == (conn_a, conn_b)


# --- (b) clipboard sai dạng → đóng protocol_error, rồi nối lại -----------------------------------

MALFORMED = {
    "clip-id-uppercase": clip_dict(clip_id=("0123456789abcdef" * 2).upper()),
    "kind-uppercase": clip_dict(kind="Text"),
    "count-zero": clip_dict(count=0),
    "index-not-below-count": clip_dict(index=1, count=1),
    "png-non-canonical-base64": clip_dict(kind="image/png", data="AB=="),
    "text-lone-surrogate": clip_dict(data="a\ud800b"),
    "data-empty": clip_dict(data=""),
    "missing-sha256": {k: v for k, v in clip_dict().items() if k != "sha256"},
}


@integration
@pytest.mark.parametrize("name", list(MALFORMED))
async def test_malformed_clipboard_closes_control_with_protocol_error_then_reconnects(
    transfer_nodes, app_helpers, caplog, name
):
    caplog.set_level(logging.DEBUG, logger="teleport")
    net = await transfer_nodes()
    A, B = net.A, net.B
    conn_a, conn_b = control_pair(net)
    await conn_b._send_frame(raw_frame(MALFORMED[name]))
    await app_helpers.wait_until(lambda: conn_a.closed, 3, "A chưa đóng kết nối điều khiển")
    await app_helpers.wait_until(
        lambda: A.control_connection(B.id) is not conn_a, 3, "A vẫn giữ kết nối điều khiển cũ"
    )
    # Bên đóng là A (nhận message sai), lý do protocol_error.
    closed_by_a = [
        r
        for r in teleport_records(caplog, logging.DEBUG)
        if "protocol_error" in r.getMessage() and B.id[:8] in r.getMessage()
    ]
    assert closed_by_a, "không thấy A ghi kết nối điều khiển kết thúc vì protocol_error"
    # N9: log không chứa nội dung clipboard.
    assert not [r for r in caplog.records if "xin chào" in r.getMessage()]

    # Nối lại: kết nối mới dùng được, cả cho clipboard hợp lệ lẫn lượt gửi file.
    B.connect_hint(A.id, [LOCAL], A.port)
    # 15 s: runner macOS của CI chạy -n auto có lúc mất quá 5 s mới xong bắt tay TLS hai chiều.
    await app_helpers.wait_until(
        lambda: (
            A.control_connection(B.id) not in (None, conn_a)
            and B.control_connection(A.id) not in (None, conn_b)
        ),
        15,
        "chưa nối lại được kết nối điều khiển",
    )
    new_a, new_b = control_pair(net)
    for m in valid_clipboards():
        await new_b.send(m)
    await assert_transfer_done(net)
    assert control_pair(net) == (new_a, new_b)


# --- (c) node cũ chưa biết `clipboard` ----------------------------------------------------------


@pytest.mark.slow
@integration
async def test_old_node_ignores_clipboard_as_unknown_type(transfer_nodes, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    net = await transfer_nodes()
    conn_a, conn_b = control_pair(net)
    monkeypatch.delitem(messages._MESSAGE_TYPES, "clipboard")  # A (và B) giờ như bản chưa có `clipboard`
    await conn_b._send_frame(encode_message(clip_dict()))
    # Bản cũ không kiểm được trường: kể cả `clipboard` sai dạng theo bản mới cũng chỉ là type lạ.
    await conn_b._send_frame(raw_frame(clip_dict(clip_id="X" * 32, data="a\ud800")))
    await asyncio.sleep(0.5)
    assert not conn_a.closed and not conn_b.closed
    assert control_pair(net) == (conn_a, conn_b)
    await assert_transfer_done(net)
    assert control_pair(net) == (conn_a, conn_b)
    assert not [r for r in teleport_records(caplog, logging.DEBUG) if "protocol_error" in r.getMessage()]


# --- (d) clipboard trên kết nối ghép đôi --------------------------------------------------------


@integration
async def test_clipboard_on_pairing_connection_gets_pair_abort_invalid(
    node_factory, raw_pairing_client, tmp_path
):
    from teleport.app.pairing import PairingOutcome

    B = await node_factory("B", accept_pairing=True, answer=True)
    other = load_or_create_identity(tmp_path / "other")
    c = await raw_pairing_client(B.port)
    await c.begin(other)
    await c.read_commit()
    c.send_dict(clip_dict())  # đúng lúc B chờ `pair_nonce`
    await c.drain()
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs
    await B.rec.wait_finished(1)
    assert B.rec.finished[0].outcome == PairingOutcome.PROTOCOL_ERROR
    assert B.rec.prompts == []
    assert B.store.devices() == []
