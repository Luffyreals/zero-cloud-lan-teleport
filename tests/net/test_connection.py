"""Test `teleport.net.connection` theo đặc tả PR-2 (mục 2.3, 3, 4.4).

Nhóm ID: U (unit), S (đường thành công), R (server từ chối), L (giới hạn), T (đổi danh sách
tin cậy), C (phía client), A (API `Connection`), K- (`ControlChannel`), LC (vòng đời `Listener`).
Mọi test mở socket mang `@pytest.mark.integration` và chỉ bind 127.0.0.1. Hằng thời gian được patch
qua module `teleport.net.connection` (fixture `fast`) trước khi tạo Listener hay gọi `open_*`.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import socket
import ssl
import struct
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from support import wait_until

from teleport.core import admission
from teleport.core.framing import HEADER, MAX_PAIRING_MESSAGE_SIZE, FramingError, decode_body, encode_message
from teleport.core.messages import (
    MAX_SAFE_INTEGER,
    PROTOCOL_VERSION,
    Clipboard,
    ConnectionKind,
    ControlOpen,
    DataOpen,
    Hello,
    MessageError,
    PairAbort,
    PairCommit,
    PairNonce,
    PairRequest,
    PairReveal,
    Ping,
    Pong,
    UnknownMessageType,
    WrongConnectionKind,
    parse_message,
    to_dict,
)
from teleport.net import connection, tls
from teleport.net.connection import (
    CloseReason,
    ConnectError,
    ConnectionLostError,
    ControlChannel,
    IdentityMismatch,
    IdleTimeout,
    Listener,
    Rejected,
    Unreachable,
    VersionMismatch,
    most_relevant_error,
    open_control,
    open_pairing,
)
from teleport.trust.identity import CERT_FILE, KEY_FILE, Identity, load_or_create_identity

# Kiểm rò rỉ (mục 4.1): `no_leaks` bắt task còn sót; socket bị giải phóng mà chưa đóng phát
# ResourceWarning ngay trong `__del__`, nên biến cảnh báo đó thành lỗi để test đỏ.
pytestmark = [
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]

LOCAL = "127.0.0.1"
TEST_NET = "192.0.2.1"  # TEST-NET-1 (RFC 5737): không ai trả lời
HEX64 = "ab" * 32
CLOSED = (ConnectionError, ssl.SSLError)
DATA_OPEN = {"type": "data_open", "transfer_id": "0123456789abcdef" * 2, "file_index": 0, "resume_seq": 1}
PI, DA = 0.2, 0.6  # ping_interval, dead_after cho test ControlChannel (mục 4.4)


# --- Hàm phụ trợ ---------------------------------------------------------------------------------


def hello_of(identity, name: str = "B", **overrides) -> Hello:
    fields = {
        "protocol": PROTOCOL_VERSION,
        "device_id": identity.device_id,
        "name": name,
        "app_version": "0.0.0",
        "os": "windows",
    }
    fields.update(overrides)
    return Hello(**fields)


def wire_hello(identity_or_id, name: str = "B", **overrides) -> dict:
    device_id = identity_or_id if isinstance(identity_or_id, str) else identity_or_id.device_id
    d = {
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "device_id": device_id,
        "name": name,
        "app_version": "0.0.0",
        "os": "windows",
    }
    d.update(overrides)
    return d


def pair_request(identity) -> PairRequest:
    return PairRequest(cert=identity.cert_pem())


def frame(body: bytes) -> bytes:
    return HEADER.pack(len(body)) + body


@pytest.fixture(scope="module")
def ids(tmp_path_factory):
    """Danh tính dùng chung cho cả module (chỉ đọc, nên chia sẻ được): server A, B tin cậy, X lạ."""
    base = tmp_path_factory.mktemp("conn-ids")
    return SimpleNamespace(
        server=load_or_create_identity(base / "server"),
        b=load_or_create_identity(base / "b"),
        x=load_or_create_identity(base / "stranger"),
        anon=load_or_create_identity(base / "anon"),
    )


@pytest.fixture
def slow_opening(fast, monkeypatch):
    """OPENING_TIMEOUT = 5 s: đóng nhanh thì chắc chắn là bị từ chối ngay, không phải hết giờ."""
    monkeypatch.setattr(fast, "OPENING_TIMEOUT", 5.0)
    return fast


async def b_control(h, ids, *, identity=None, expected: str | None = None, addresses=(LOCAL,)):
    identity = identity if identity is not None else ids.b
    return await open_control(
        list(addresses), h.port, identity, hello_of(identity, "B"), expected or h.identity.cert_pem()
    )


async def anon_pairing(h, ids):
    return await open_pairing([LOCAL], h.port, hello_of(ids.anon, "Anon"))


async def raw_opening(raw_client, h, identity, hello: dict, opening: dict | None):
    """Client thô: TLS (có chứng chỉ `identity` hoặc ẩn danh), đọc hello server, gửi hello rồi `opening`."""
    peer = await raw_client(h.port, identity)
    await peer.read_hello()
    peer.send_dict(hello)
    if opening is not None:
        peer.send_dict(opening)
    await peer.drain()
    return peer


async def raw_control(raw_client, h, ids):
    peer = await raw_opening(raw_client, h, ids.b, wire_hello(ids.b), {"type": "control_open"})
    return peer, await h.next()


async def raw_pairing(raw_client, h, ids):
    peer = await raw_opening(
        raw_client, h, None, wire_hello(ids.anon, "Anon"), to_dict(pair_request(ids.anon))
    )
    return peer, await h.next()


async def read_messages_for(peer, duration: float) -> list[dict]:
    """Đọc mọi message tới trong `duration` giây."""
    out: list[dict] = []
    deadline = time.monotonic() + duration
    while (left := deadline - time.monotonic()) > 0:
        try:
            msg = await peer.read(timeout=left)
        except TimeoutError:
            break
        if msg is None:
            break
        out.append(msg)
    return out


async def read_until_type(peer, type_name: str, timeout: float = 2.0) -> dict:
    async with asyncio.timeout(timeout):
        while True:
            msg = await peer.read(timeout=timeout)
            assert msg is not None, f"kết nối đóng trước khi nhận {type_name}"
            if msg.get("type") == type_name:
                return msg


async def cancel_wait(*tasks: asyncio.Task) -> None:
    for t in tasks:
        t.cancel()
    for t in tasks:
        with contextlib.suppress(BaseException):
            await t


async def receive_closed(conn, timeout: float = 2.0) -> None:
    """Phía client thấy kết nối đã bị máy kia đóng: `receive` trả None hoặc raise ConnectionLostError."""
    try:
        msg = await asyncio.wait_for(conn.receive(), timeout)
    except ConnectionLostError:
        return
    assert msg is None, f"còn nhận được message: {msg!r}"


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCAL, 0))
        return s.getsockname()[1]
    finally:
        s.close()


# --- Client ssl đồng bộ (cho A5, A6, T4: máy kia không bao giờ đọc / dùng lại session) -------------


def _recv_exact(sock: ssl.SSLSocket, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            if not buf:
                return None
            raise ConnectionError("đóng giữa chừng")
        buf += chunk
    return bytes(buf)


def sync_read_frame(sock: ssl.SSLSocket) -> dict | None:
    header = _recv_exact(sock, HEADER.size)
    if header is None:
        return None
    (n,) = HEADER.unpack(header)
    body = _recv_exact(sock, n)
    if body is None:
        raise ConnectionError("đóng giữa chừng")
    return decode_body(body)


def sync_connect(port: int, ctx: ssl.SSLContext, *, session=None, rcvbuf: int | None = None) -> ssl.SSLSocket:
    raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if rcvbuf is not None:
            raw.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        raw.settimeout(5)
        raw.connect((LOCAL, port))
        return ctx.wrap_socket(raw, session=session)
    except BaseException:
        raw.close()
        raise


def cert_client_context(identity) -> ssl.SSLContext:
    """Client gửi chứng chỉ của `identity` nhưng KHÔNG kiểm chứng chỉ server (`CERT_NONE`).

    Chỉ để thử phía server. Sản phẩm không còn đường nào như vậy (`docs/protocol.md` mục 2.1:
    chứng chỉ client chỉ đi tới server đã được kiểm bằng `tls.trusted_client_context`).
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(identity.cert_path, identity.key_path)
    return ctx


def sync_open_control(port: int, identity, *, rcvbuf: int | None = None) -> ssl.SSLSocket:
    sock = sync_connect(port, cert_client_context(identity), rcvbuf=rcvbuf)
    try:
        hello = sync_read_frame(sock)
        assert hello is not None and hello["type"] == "hello"
        sock.sendall(encode_message(wire_hello(identity)) + encode_message({"type": "control_open"}))
    except BaseException:
        sock.close()
        raise
    return sock


# =================================================================================================
# U: unit, không socket
# =================================================================================================


def test_constants_match_spec():
    assert connection.DEFAULT_PORT == 47474
    assert connection.OPENING_TIMEOUT == 10.0
    assert connection.DRAIN_TIMEOUT == 30.0
    assert connection.CLOSE_TIMEOUT == 5.0
    assert connection.IDLE_TIMEOUT == 30.0
    assert connection._SEND_CHUNK == 64 * 1024
    assert connection._READ_CHUNK == 64 * 1024


def test_close_reason_values():
    assert {r.value for r in CloseReason} == {
        "peer_closed",
        "keepalive",
        "connection_lost",
        "protocol_error",
        "local",
    }


def _errors():
    return SimpleNamespace(
        u=Unreachable("u", address="10.0.0.1"),
        u2=Unreachable("u2", address="10.0.0.5"),
        r=Rejected("r", address="10.0.0.2"),
        r2=Rejected("r2", address="10.0.0.6"),
        v=VersionMismatch("v", address="10.0.0.3", peer_protocol=2),
        i=IdentityMismatch("i", address="10.0.0.4", actual_fingerprint=HEX64),
        i2=IdentityMismatch("i2", address="10.0.0.7"),
    )


def test_most_relevant_error_priority():
    e = _errors()
    assert most_relevant_error([e.u, e.v, e.r, e.i]) is e.i
    assert most_relevant_error([e.u, e.v, e.r]) is e.r
    assert most_relevant_error([e.r, e.v, e.u]) is e.r
    assert most_relevant_error([e.u, e.v]) is e.v
    assert most_relevant_error([e.v, e.u]) is e.v
    assert most_relevant_error([e.u]) is e.u


def test_most_relevant_error_same_level_takes_first():
    e = _errors()
    assert most_relevant_error([e.u, e.u2]) is e.u
    assert most_relevant_error([e.u2, e.u]) is e.u2
    assert most_relevant_error([e.r2, e.u, e.r]) is e.r2
    assert most_relevant_error([e.u, e.i2, e.r, e.i]) is e.i2


def test_most_relevant_error_accepts_any_iterable():
    e = _errors()
    assert most_relevant_error(iter([e.u, e.r])) is e.r
    assert most_relevant_error(x for x in (e.v, e.u)) is e.v


def test_most_relevant_error_of_nothing_is_value_error():
    with pytest.raises(ValueError):
        most_relevant_error([])


def test_exception_hierarchy():
    for cls in (Unreachable, Rejected, IdentityMismatch, VersionMismatch):
        assert issubclass(cls, ConnectError)
    assert not issubclass(ConnectionLostError, ConnectError)
    assert not issubclass(ConnectionLostError, OSError)
    assert issubclass(ConnectError, Exception)
    # IdleTimeout chỉ kế thừa ConnectionLostError, để `except OSError` không nuốt mất nó.
    assert issubclass(IdleTimeout, ConnectionLostError)
    for cls in (TimeoutError, OSError, ConnectError):
        assert not issubclass(IdleTimeout, cls)


def test_exception_attributes():
    assert Unreachable("x").address is None
    assert Rejected("x", address="1.2.3.4").address == "1.2.3.4"
    e = IdentityMismatch("x", address="1.2.3.4", actual_fingerprint=HEX64)
    assert (e.address, e.actual_fingerprint) == ("1.2.3.4", HEX64)
    assert IdentityMismatch("x").actual_fingerprint is None
    v = VersionMismatch("x", peer_protocol=2)
    assert (v.address, v.peer_protocol) == (None, 2)
    assert "x" in str(v)


# --- U3: kiểm tham số trước mọi I/O --------------------------------------------------------------


@pytest.fixture
def no_io(monkeypatch):
    """Mở socket trong test kiểm tham số là lỗi: tham số sai phải bị chặn trước mọi I/O."""

    async def forbidden(*args, **kwargs):
        raise AssertionError("không được mở socket khi tham số sai")

    monkeypatch.setattr(asyncio, "open_connection", forbidden)
    monkeypatch.setattr(asyncio, "start_server", forbidden)


BAD_ADDRESSES = [
    [],
    ["::1"],
    ["localhost"],
    ["0.0.0.0"],
    ["224.0.0.251"],
    ["255.255.255.255"],
    ["01.2.3.4"],
    ["1.2.3"],
    ["1.2.3.256"],
    [" 127.0.0.1"],
    ["127.0.0.1", "::1"],
    [f"10.0.0.{i}" for i in range(1, 18)],  # 17 địa chỉ
    "127.0.0.1",  # chuỗi trần, không phải danh sách
    [127],
    [None],
]


# Các loại kết nối mà máy này mở được (P2-3 AC-6: test client sẵn có tham số hóa theo loại thêm `data`).
OPEN_KINDS = ["pairing", "control", "data"]
DATA_OPEN_MSG = DataOpen(transfer_id="0123456789abcdef" * 2, file_index=0, resume_seq=1)


async def _call_open(kind: str, ids, addresses, port, **overrides):
    if kind == "pairing":
        return await open_pairing(addresses, port, overrides.get("hello", hello_of(ids.anon)))
    if kind == "data":
        # open_data nhận **một** địa chỉ; danh sách một phần tử được mở ra (danh sách là sai, ở test riêng
        # trong test_data_connection.py).
        address = addresses[0] if isinstance(addresses, list) and len(addresses) == 1 else addresses
        return await connection.open_data(
            address,
            port,
            overrides.get("identity", ids.b),
            overrides.get("hello", hello_of(ids.b)),
            overrides.get("expected", ids.server.cert_pem()),
            DATA_OPEN_MSG,
        )
    return await open_control(
        addresses,
        port,
        overrides.get("identity", ids.b),
        overrides.get("hello", hello_of(ids.b)),
        overrides.get("expected", ids.server.cert_pem()),
    )


@pytest.mark.parametrize("kind", ["pairing", "control"])
@pytest.mark.parametrize("addresses", BAD_ADDRESSES, ids=repr)
async def test_open_rejects_bad_addresses_before_io(no_io, ids, kind, addresses):
    with pytest.raises(ValueError):
        await _call_open(kind, ids, addresses, 47474)


@pytest.mark.parametrize("kind", OPEN_KINDS)
@pytest.mark.parametrize("port", [0, 65536, -1, True, False, "47474", 47474.0, None], ids=repr)
async def test_open_rejects_bad_port_before_io(no_io, ids, kind, port):
    with pytest.raises(ValueError):
        await _call_open(kind, ids, [LOCAL], port)


@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_open_rejects_hello_with_other_protocol(no_io, ids, kind):
    identity = ids.anon if kind == "pairing" else ids.b
    with pytest.raises(ValueError):
        await _call_open(kind, ids, [LOCAL], 47474, hello=hello_of(identity, protocol=2))


async def test_open_control_rejects_hello_of_other_identity(no_io, ids):
    with pytest.raises(ValueError):
        await _call_open("control", ids, [LOCAL], 47474, hello=hello_of(ids.x))


def _ca_cert_pem() -> str:
    """Chứng chỉ P-256 tự ký đúng mọi điều kiện của Teleport trừ BasicConstraints CA=true."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teleport-" + "ab" * 16)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(9999, 12, 31, tzinfo=datetime.UTC))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


BAD_EXPECTED_PEMS = {
    "fingerprint-instead-of-pem": HEX64,
    "empty": "",
    "ascii-text": "not a PEM",
    "non-ascii": "không phải PEM",
    "broken-base64": "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n",
    "ca-cert": _ca_cert_pem(),
    "none": None,
    "bytes": b"-----BEGIN CERTIFICATE-----",
}


@pytest.mark.parametrize("expected", list(BAD_EXPECTED_PEMS.values()), ids=list(BAD_EXPECTED_PEMS))
async def test_open_control_rejects_bad_expected_cert_pem_before_io(no_io, ids, expected):
    """`docs/protocol.md` mục 2.1: `expected_cert_pem` qua `peer_cert_from_pem`; lỗi (kể cả
    InvalidCertificate) → ValueError, trước mọi I/O."""
    with pytest.raises(ValueError):
        await _call_open("control", ids, [LOCAL], 47474, expected=expected)


def test_open_control_has_no_expected_fingerprint_parameter():
    import inspect

    params = list(inspect.signature(open_control).parameters)
    assert params == ["addresses", "port", "identity", "hello", "expected_cert_pem"]


async def _noop_handler(conn):
    return None


async def test_listener_rejects_hello_of_other_identity(ids):
    with pytest.raises(ValueError):
        Listener(ids.server, hello_of(ids.x), [], lambda fp: False, _noop_handler)


async def test_listener_rejects_hello_with_other_protocol(ids):
    with pytest.raises(ValueError):
        Listener(ids.server, hello_of(ids.server, protocol=2), [], lambda fp: False, _noop_handler)


# Đặc tả chỉ nói "raise" mà không nói lớp lỗi; chuỗi không phải ASCII làm `ssl` báo TypeError.
PEM_ERRORS = (ssl.SSLError, ValueError, TypeError)
BAD_PEMS = ["không phải PEM", "not a PEM", "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"]
BAD_PEM_IDS = ["non-ascii-text", "ascii-text", "broken-pem"]


@pytest.mark.parametrize("bad_pem", BAD_PEMS, ids=BAD_PEM_IDS)
async def test_listener_rejects_bad_trusted_pem_at_construction(ids, bad_pem):
    with pytest.raises(PEM_ERRORS):
        Listener(ids.server, hello_of(ids.server), [bad_pem], lambda fp: False, _noop_handler)


@pytest.mark.parametrize("host", ["::", "::1", "localhost", "", "0", "127.1", None], ids=repr)
async def test_listener_start_rejects_non_ipv4_host(no_io, ids, host):
    listener = Listener(ids.server, hello_of(ids.server), [], lambda fp: False, _noop_handler)
    try:
        with pytest.raises(ValueError):
            await listener.start(host, 0)
    finally:
        await listener.close()


@pytest.mark.parametrize("port", [-1, 65536, True, "0", 1.5], ids=repr)
async def test_listener_start_rejects_bad_port(no_io, ids, port):
    listener = Listener(ids.server, hello_of(ids.server), [], lambda fp: False, _noop_handler)
    try:
        with pytest.raises((ValueError, TypeError)):
            await listener.start(LOCAL, port)
    finally:
        await listener.close()


async def test_listener_port_is_none_before_start(ids):
    listener = Listener(ids.server, hello_of(ids.server), [], lambda fp: False, _noop_handler)
    assert listener.port is None
    assert listener.opening_count == 0
    assert listener.connection_count == 0
    await listener.close()


# =================================================================================================
# S: đường thành công
# =================================================================================================


@pytest.mark.integration
async def test_open_pairing_end_to_end(fast, listener_factory, ids):
    h = await listener_factory(ids.server)
    loop = asyncio.get_running_loop()
    before = loop.time()
    conn = await anon_pairing(h, ids)
    try:
        assert conn.kind is ConnectionKind.PAIRING
        assert conn.is_server is False
        assert conn.opening is None
        assert conn.closed is False
        assert conn.peer.address == LOCAL
        assert conn.peer.port == h.port
        assert conn.peer.cert is not None
        assert conn.peer.cert.fingerprint == ids.server.fingerprint
        assert conn.peer.fingerprint == ids.server.fingerprint
        assert conn.peer.hello == h.hello
        assert before <= conn.opened_at <= loop.time()

        request = pair_request(ids.anon)
        await conn.send(request)
        server = await h.next()
        assert server.kind is ConnectionKind.PAIRING
        assert server.is_server is True
        assert server.opening == request
        assert server.peer.cert is None
        assert server.peer.fingerprint is None
        assert server.peer.address == LOCAL
        assert server.peer.hello == hello_of(ids.anon, "Anon")
        assert before <= server.opened_at <= loop.time()
        assert h.listener.connection_count == 1
        assert h.listener.opening_count == 0

        # Luồng ghép đôi (protocol §5): commit (B→A), nonce (A→B), reveal (B→A) đi qua kết nối.
        commit = PairCommit(commitment=HEX64)
        await server.send(commit)
        assert await asyncio.wait_for(conn.receive(), 2) == commit
        nonce = PairNonce(nonce=HEX64, signature=HEX64 + HEX64)
        await conn.send(nonce)
        assert await asyncio.wait_for(server.receive(), 2) == nonce
        reveal = PairReveal(nonce=HEX64)
        await server.send(reveal)
        assert await asyncio.wait_for(conn.receive(), 2) == reveal
        abort = PairAbort(reason="user")
        await conn.send(abort)
        assert await asyncio.wait_for(server.receive(), 2) == abort
    finally:
        await conn.close()


@pytest.mark.integration
async def test_open_control_end_to_end(fast, listener_factory, ids):
    h = await listener_factory(ids.server, trusted=[ids.b])
    start = time.monotonic()
    conn = await b_control(h, ids)
    elapsed = time.monotonic() - start
    try:
        assert elapsed < 1.0
        assert conn.kind is ConnectionKind.CONTROL
        assert conn.is_server is False
        assert conn.opening is None
        assert conn.peer.fingerprint == ids.server.fingerprint
        assert conn.peer.hello == h.hello

        server = await h.next()
        assert server.kind is ConnectionKind.CONTROL
        assert server.is_server is True
        assert server.opening == ControlOpen()
        assert server.peer.fingerprint == ids.b.fingerprint
        assert server.peer.cert.device_id == ids.b.device_id
        assert server.peer.hello.device_id == ids.b.device_id
        assert server.peer.address == LOCAL

        await conn.send(Ping(t=42))
        assert await asyncio.wait_for(server.receive(), 2) == Ping(t=42)
        await server.send(Pong(t=42))
        assert await asyncio.wait_for(conn.receive(), 2) == Pong(t=42)
        await server.send(Ping(t=7))
        assert await asyncio.wait_for(conn.receive(), 2) == Ping(t=7)
    finally:
        await conn.close()


@pytest.mark.integration
async def test_tls12_client_is_refused(fast, listener_factory, raw_client, ids):
    h = await listener_factory(ids.server)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    try:
        peer = await raw_client(h.port, ctx=ctx)
    except CLOSED:
        pass  # bắt tay thất bại ngay: đúng
    else:
        _, data = await peer.expect_closed(3.0)
        assert data == b""
    await h.wait_idle()
    assert h.calls == 0


@pytest.mark.integration
async def test_start_returns_real_port_and_busy_port_raises(fast, listener_factory, ids):
    h = await listener_factory(ids.server, start=False)
    assert h.listener.port is None
    port = await h.listener.start(LOCAL, 0)
    assert isinstance(port, int) and port > 0
    assert h.listener.port == port

    other = await listener_factory(ids.server, start=False)
    with pytest.raises(OSError):
        await other.listener.start(LOCAL, port)


@pytest.mark.integration
async def test_start_twice_raises(fast, listener_factory, ids):
    h = await listener_factory(ids.server)
    with pytest.raises(RuntimeError):
        await h.listener.start(LOCAL, 0)


@pytest.mark.integration
async def test_many_concurrent_openings_all_succeed(fast, monkeypatch, listener_factory, ids):
    """S5 (mục 3.6): start_tls là await đầu tiên, ClientHello tới sớm không làm treo bắt tay."""
    for name in (
        "MAX_OPENING_PER_IP",
        "MAX_OPENING_TOTAL",
        "MAX_ANONYMOUS_PER_IP",
        "MAX_ANONYMOUS_TOTAL",
        "PRIORITY_OPENING_PER_IP",
        "PRIORITY_OPENING_TOTAL",
    ):
        monkeypatch.setattr(admission, name, 1000)
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])

    async def pairing():
        conn = await anon_pairing(h, ids)
        await conn.send(pair_request(ids.anon))
        return conn

    results = await asyncio.gather(
        *(b_control(h, ids) for _ in range(20)), *(pairing() for _ in range(20)), return_exceptions=True
    )
    conns = [r for r in results if not isinstance(r, BaseException)]
    try:
        errors = [r for r in results if isinstance(r, BaseException)]
        assert not errors, f"{len(errors)} lần mở thất bại: {errors[:3]!r}"
        await wait_until(lambda: h.calls == 40, 5.0, "on_connection được gọi đủ 40 lần")
        await asyncio.sleep(0.1)
        assert h.calls == 40
        kinds = [h.accepted.get_nowait().kind for _ in range(40)]
        assert kinds.count(ConnectionKind.CONTROL) == 20
        assert kinds.count(ConnectionKind.PAIRING) == 20
    finally:
        await asyncio.gather(*(c.close() for c in conns))


# =================================================================================================
# R: server từ chối
# =================================================================================================


async def assert_rejected(h, peer, within: float = 2.0) -> float:
    """Server đóng kết nối, không gửi gì ngoài hello (đã đọc trước), không gọi on_connection."""
    elapsed, data = await peer.expect_closed(within)
    assert data == b"", f"server gửi thêm {len(data)} byte trước khi đóng (protocol §2.1)"
    await h.wait_idle()
    assert h.calls == 0
    assert h.listener.connection_count == 0
    return elapsed


# Mỗi kịch bản: client xấu làm đúng một việc sai, trả về RawPeer (đã đọc hello server nếu có).


async def sc_anon_control_open(env):
    return await raw_opening(env.raw_client, env.h, None, wire_hello(env.ids.anon), {"type": "control_open"})


async def sc_anon_data_open(env):
    return await raw_opening(env.raw_client, env.h, None, wire_hello(env.ids.anon), DATA_OPEN)


async def sc_trusted_pair_request(env):
    return await raw_opening(
        env.raw_client, env.h, env.ids.b, wire_hello(env.ids.b), to_dict(pair_request(env.ids.b))
    )


async def sc_hello_device_id_not_cn(env):
    return await raw_opening(
        env.raw_client, env.h, env.ids.b, wire_hello(env.ids.x), {"type": "control_open"}
    )


async def sc_hello_protocol_2_anon(env):
    return await raw_opening(
        env.raw_client, env.h, None, wire_hello(env.ids.anon, protocol=2), to_dict(pair_request(env.ids.anon))
    )


async def sc_hello_protocol_2_trusted(env):
    return await raw_opening(
        env.raw_client, env.h, env.ids.b, wire_hello(env.ids.b, protocol=2), {"type": "control_open"}
    )


async def sc_oversized_hello_header(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    peer.send_bytes(HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1))  # chỉ header, không có thân
    await peer.drain()
    return peer


async def sc_oversized_opening_header(env):
    peer = await raw_opening(env.raw_client, env.h, env.ids.b, wire_hello(env.ids.b), None)
    peer.send_bytes(HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1))
    await peer.drain()
    return peer


async def sc_oversized_hello_header_trusted(env):
    """PR-1 D1: máy tin cậy (sẽ mở kết nối điều khiển, trần 1 MiB) vẫn chỉ được gửi `hello` ≤ 16 KiB."""
    peer = await env.raw_client(env.h.port, env.ids.b)
    await peer.read_hello()
    peer.send_bytes(HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1) + b"x" * 8)  # header + vài byte thân
    await peer.drain()
    return peer


async def sc_control_open_instead_of_hello(env):
    peer = await env.raw_client(env.h.port, env.ids.b)
    await peer.read_hello()
    peer.send_dict({"type": "control_open"})
    peer.send_dict({"type": "control_open"})
    await peer.drain()
    return peer


async def sc_garbage_instead_of_hello(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    peer.send_bytes(frame(b"\xff\xfe{]\x00garbage"))
    await peer.drain()
    return peer


async def sc_json_array_instead_of_hello(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    peer.send_bytes(frame(b"[1, 2, 3]"))
    await peer.drain()
    return peer


async def sc_json_string_instead_of_hello(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    peer.send_bytes(frame(json.dumps("hello").encode()))
    await peer.drain()
    return peer


async def sc_second_hello_anon(env):
    return await raw_opening(env.raw_client, env.h, None, wire_hello(env.ids.anon), wire_hello(env.ids.anon))


async def sc_second_hello_trusted(env):
    return await raw_opening(env.raw_client, env.h, env.ids.b, wire_hello(env.ids.b), wire_hello(env.ids.b))


async def sc_name_with_bidi_override(env):
    return await raw_opening(
        env.raw_client,
        env.h,
        None,
        wire_hello(env.ids.anon, name="PC‮Nha"),
        to_dict(pair_request(env.ids.anon)),
    )


IMMEDIATE_REJECTIONS = {
    "R2-anon-control_open": sc_anon_control_open,
    "R3-anon-data_open": sc_anon_data_open,
    "R4-trusted-pair_request": sc_trusted_pair_request,
    # R5 (data_open từ máy tin cậy) không còn là lần từ chối: kết nối dữ liệu được giao (P2-3 AC-1).
    "R6-hello-device_id-not-CN": sc_hello_device_id_not_cn,
    "R7-protocol-2-anon": sc_hello_protocol_2_anon,
    "R7-protocol-2-trusted": sc_hello_protocol_2_trusted,
    "R11-hello-header-16385": sc_oversized_hello_header,
    "R11-opening-header-16385": sc_oversized_opening_header,
    "R11-trusted-hello-header-16385": sc_oversized_hello_header_trusted,
    "R12-control_open-first": sc_control_open_instead_of_hello,
    "R12-garbage-first": sc_garbage_instead_of_hello,
    "R12-json-array-first": sc_json_array_instead_of_hello,
    "R12-json-string-first": sc_json_string_instead_of_hello,
    "R13-second-hello-anon": sc_second_hello_anon,
    "R13-second-hello-trusted": sc_second_hello_trusted,
    "R14-name-U+202E": sc_name_with_bidi_override,
}


@pytest.mark.integration
@pytest.mark.parametrize("case", list(IMMEDIATE_REJECTIONS))
async def test_server_closes_bad_opening_immediately(slow_opening, listener_factory, raw_client, ids, case):
    """Với OPENING_TIMEOUT = 5 s, đóng trong < 1 s nghĩa là server từ chối ngay, không chờ hết giờ."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    env = SimpleNamespace(h=h, ids=ids, raw_client=raw_client)
    peer = await IMMEDIATE_REJECTIONS[case](env)
    elapsed = await assert_rejected(h, peer, within=3.0)
    assert elapsed < 1.0, f"đóng sau {elapsed:.2f} s: có vẻ chờ hết giờ thay vì từ chối ngay"


@pytest.mark.integration
async def test_unknown_client_cert_is_rejected(fast, listener_factory, ids):
    """R1: chứng chỉ lạ → bắt tay TLS 1.3 xong phía client, rồi thất bại khi đọc hello → Rejected."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    with pytest.raises(Rejected) as exc:
        await b_control(h, ids, identity=ids.x)
    assert exc.value.address == LOCAL
    await h.wait_idle()
    assert h.calls == 0


@pytest.mark.integration
@pytest.mark.parametrize("san", ["x400", "edi"])
async def test_m1_listener_rejects_client_cert_with_unsupported_general_name_quietly(
    fast, listener_factory, make_san_identity, ids, caplog, san
):
    """Chứng chỉ client có SAN lạ lọt vào danh sách tin cậy (không qua TrustStore) và qua được OpenSSL:
    server vẫn coi là chứng chỉ không hợp lệ, từ chối như mọi kết nối xấu, không ghi log ERROR."""
    caplog.set_level(logging.DEBUG, logger="teleport")
    evil = make_san_identity(san)
    h = await listener_factory(ids.server, trusted=[evil])
    with pytest.raises(Rejected):
        await b_control(h, ids, identity=evil)
    await h.wait_idle()
    assert h.calls == 0
    assert h.listener.connection_count == 0
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, [r.getMessage() for r in errors]


@pytest.mark.integration
async def test_silence_after_handshake_times_out(fast, listener_factory, raw_client, ids):
    """R8: im lặng sau bắt tay → đóng sau ≈ OPENING_TIMEOUT (0,5 s)."""
    h = await listener_factory(ids.server)
    peer = await raw_client(h.port, None)
    await peer.read_hello()
    await assert_rejected(h, peer, within=5.0)
    total = time.monotonic() - peer.started
    assert 0.4 <= total <= 0.5 + 2.5


@pytest.mark.integration
async def test_silent_tcp_without_tls_times_out(fast, listener_factory, raw_client, ids):
    """R9: TCP thô không gửi byte nào → đóng sau ≈ OPENING_TIMEOUT."""
    h = await listener_factory(ids.server)
    peer = await raw_client(h.port, use_tls=False)
    _, data = await peer.expect_closed(5.0)
    assert data == b""
    total = time.monotonic() - peer.started
    assert 0.4 <= total <= 0.5 + 2.5
    await h.wait_idle()
    assert h.calls == 0


@pytest.mark.slow
@pytest.mark.integration
async def test_slowloris_deadline_is_not_extended(fast, monkeypatch, listener_factory, raw_client, ids):
    """R10: hello gửi 1 byte mỗi 100 ms → đóng ở ≈ 1 s tính từ lúc kết nối, không gia hạn."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 1.0)
    h = await listener_factory(ids.server)
    peer = await raw_client(h.port, None)
    await peer.read_hello()
    payload = encode_message(wire_hello(ids.anon)) + encode_message(to_dict(pair_request(ids.anon)))

    async def drip():
        for i in range(len(payload)):
            peer.send_bytes(payload[i : i + 1])
            await peer.drain()
            await asyncio.sleep(0.1)

    dripper = asyncio.create_task(drip())
    try:
        await peer.expect_closed(6.0)
    finally:
        await cancel_wait(dripper)
    total = time.monotonic() - peer.started
    assert 0.8 <= total <= 1.0 + 2.5
    await h.wait_idle()
    assert h.calls == 0


# --- R15: fuzz message mở đầu ------------------------------------------------------------------


KNOWN_TYPES = [
    "hello",
    "pair_request",
    "pair_commit",
    "pair_nonce",
    "pair_reveal",
    "pair_challenge",  # type của luồng cũ, nay lạ
    "pair_confirm",
    "pair_abort",
    "control_open",
    "data_open",
    "ping",
    "pong",
    "offer",
]
FUZZ_FIELDS = [
    "protocol",
    "device_id",
    "name",
    "app_version",
    "os",
    "cert",
    "commitment",
    "nonce",
    "signature",
    "reason",
    "t",
    "transfer_id",
    "file_index",
    "resume_seq",
    "x",
]
FAKE_CERT = "-----BEGIN CERTIFICATE-----\nMIIBfake\n-----END CERTIFICATE-----\n"
fuzz_values = st.recursive(
    st.none()
    | st.booleans()
    | st.integers()
    | st.floats(allow_nan=False, allow_infinity=False)
    | st.text(max_size=40)
    | st.sampled_from([HEX64, HEX64 + HEX64, FAKE_CERT, "0123456789abcdef" * 2, "user", 1]),
    lambda children: (
        st.lists(children, max_size=3) | st.dictionaries(st.text(max_size=5), children, max_size=3)
    ),
    max_leaves=8,
)
fuzz_dicts = st.builds(
    lambda t, extra: {"type": t, **extra},
    st.sampled_from(KNOWN_TYPES) | st.text(max_size=12),
    st.dictionaries(st.sampled_from(FUZZ_FIELDS), fuzz_values, max_size=4),
)
valid_openings = st.sampled_from(
    [
        {"type": "pair_request", "cert": FAKE_CERT},
        {"type": "pair_request", "cert": FAKE_CERT, "x": [1]},
        # `commitment` của luồng cũ giờ là trường lạ, bị bỏ qua.
        {"type": "pair_request", "cert": FAKE_CERT, "commitment": HEX64},
        {"type": "control_open"},
        {"type": "control_open", "future": True},
        {"type": "data_open", "transfer_id": "0123456789abcdef" * 2, "file_index": 0, "resume_seq": 1},
        {
            "type": "data_open",
            "transfer_id": "f" * 32,
            "file_index": 999,
            "resume_seq": MAX_SAFE_INTEGER,
            "x": 1,
        },
    ]
)


def _json_body(d: dict) -> bytes:
    return json.dumps(d, ensure_ascii=False).encode("utf-8", "surrogatepass")


fuzz_bodies = (
    fuzz_dicts.map(_json_body) | valid_openings.map(_json_body) | st.binary(max_size=MAX_PAIRING_MESSAGE_SIZE)
)


def _expected_kind(body: bytes, trusted_client: bool):
    """Oracle theo đặc tả: chỉ pair_request hợp lệ (ẩn danh), control_open / data_open (tin cậy) được giao."""
    try:
        msg = parse_message(decode_body(body))
    except (FramingError, MessageError):
        return None
    if isinstance(msg, PairRequest) and not trusted_client:
        return ConnectionKind.PAIRING
    if isinstance(msg, ControlOpen) and trusted_client:
        return ConnectionKind.CONTROL
    if isinstance(msg, DataOpen) and trusted_client:
        # Handler của test trả về ngay, nên Listener cắt kết nối dữ liệu (P2-3 mục 3.1 bước 8).
        return ConnectionKind.DATA
    return None


async def _fuzz_one(helpers, server_id, client_id, body: bytes, trusted_client: bool) -> None:
    before = asyncio.all_tasks()
    accepted = []

    async def on_conn(conn):
        accepted.append(conn)

    listener = Listener(
        server_id,
        helpers.make_hello(server_id, "Server"),
        [client_id.cert_pem()],
        lambda fp: fp == client_id.fingerprint,
        on_conn,
    )
    port = await listener.start(LOCAL, 0)
    peers = []
    try:
        peer = await helpers.RawPeer.connect(port, client_id if trusted_client else None)
        peers.append(peer)
        await peer.read_hello()
        peer.send_dict(helpers.hello_dict(client_id))
        peer.send_bytes(frame(body))
        await peer.drain()
        expected = _expected_kind(body, trusted_client)
        if expected is None:
            _, data = await peer.expect_closed(2.0)
            assert data == b""
            assert accepted == []
        else:
            await helpers.wait_until(lambda: len(accepted) == 1, 2.0, "kết nối hợp lệ được giao")
            assert accepted[0].kind is expected
        await helpers.wait_until(lambda: listener.opening_count == 0, 2.0, "opening_count về 0")

        # Listener vẫn sống và vẫn nhận kết nối hợp lệ.
        n = len(accepted)
        conn = await open_pairing([LOCAL], port, helpers.make_hello(client_id))
        try:
            await conn.send(pair_request(client_id))
            await helpers.wait_until(lambda: len(accepted) == n + 1, 2.0, "kết nối sau fuzz được giao")
        finally:
            await conn.close()
    finally:
        for p in peers:
            p.abort()
        await listener.close()
    await asyncio.sleep(0.05)
    leftover = [t for t in asyncio.all_tasks() if t not in before and t is not asyncio.current_task()]
    assert not leftover, f"task còn sót: {[t.get_name() for t in leftover]}"


@pytest.fixture(scope="module")
def fuzz_ids(tmp_path_factory):
    base = tmp_path_factory.mktemp("fuzz-ids")
    return load_or_create_identity(base / "server"), load_or_create_identity(base / "client")


@pytest.mark.slow
@pytest.mark.integration
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
@given(body=fuzz_bodies, trusted_client=st.booleans())
def test_fuzz_opening_message_never_crashes_listener(net_helpers, fuzz_ids, body, trusted_client):
    server_id, client_id = fuzz_ids
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(connection, "OPENING_TIMEOUT", 3.0)
        mp.setattr(connection, "CLOSE_TIMEOUT", 0.5)
        asyncio.run(_fuzz_one(net_helpers, server_id, client_id, body, trusted_client))


# =================================================================================================
# L: giới hạn kết nối đang mở đầu (Q2) và kết nối ẩn danh
# =================================================================================================


async def open_silent_tcp(raw_client, h, n: int):
    return [await raw_client(h.port, use_tls=False) for _ in range(n)]


@pytest.mark.slow
@pytest.mark.integration
async def test_fifth_opening_from_same_ip_is_refused(fast, monkeypatch, listener_factory, raw_client, ids):
    """L1: 4 kết nối đang mở đầu mỗi IP; cái thứ 5 bị đóng ngay; trả chỗ khi một cái đóng."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    h = await listener_factory(ids.server)
    peers = await open_silent_tcp(raw_client, h, 4)
    await wait_until(lambda: h.listener.opening_count == 4, 2.0, "4 kết nối đang mở đầu")

    fifth = await raw_client(h.port, use_tls=False)
    elapsed, _ = await fifth.expect_closed(2.0)
    assert elapsed < 0.5
    for p in peers:
        assert await p.stays_open(0.05)

    peers[0].abort()
    await wait_until(lambda: h.listener.opening_count == 3, 2.0, "trả chỗ sau khi đóng một kết nối")
    sixth = await raw_client(h.port, use_tls=False)
    assert await sixth.stays_open(0.5)
    assert h.listener.opening_count == 4


@pytest.mark.integration
async def test_total_opening_limit(fast, monkeypatch, listener_factory, raw_client, ids):
    """L2: MAX_OPENING_PER_IP = 100, MAX_OPENING_TOTAL = 3 → kết nối thứ 4 bị đóng ngay."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    monkeypatch.setattr(admission, "MAX_OPENING_PER_IP", 100)
    monkeypatch.setattr(admission, "MAX_OPENING_TOTAL", 3)
    h = await listener_factory(ids.server)
    await open_silent_tcp(raw_client, h, 3)
    await wait_until(lambda: h.listener.opening_count == 3, 2.0, "3 kết nối đang mở đầu")
    fourth = await raw_client(h.port, use_tls=False)
    elapsed, _ = await fourth.expect_closed(2.0)
    assert elapsed < 0.5


@pytest.mark.integration
async def test_delivered_connections_do_not_count_toward_opening_limit(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """L3: 4 kết nối điều khiển đã giao + 4 kết nối thô im lặng: cả 4 kết nối thô đều được nhận."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    conns = [await b_control(h, ids) for _ in range(4)]
    try:
        await wait_until(lambda: h.calls == 4, 2.0, "4 kết nối điều khiển được giao")
        assert h.listener.connection_count == 4
        assert h.listener.opening_count == 0
        peers = await open_silent_tcp(raw_client, h, 4)
        for p in peers:
            assert await p.stays_open(0.1)
        await wait_until(lambda: h.listener.opening_count == 4, 2.0, "4 kết nối thô đang mở đầu")
    finally:
        await asyncio.gather(*(c.close() for c in conns))


@pytest.mark.integration
async def test_one_waiting_anonymous_connection_per_ip(fast, monkeypatch, listener_factory, raw_client, ids):
    """L4: ẩn danh chờ vào phiên 1/IP; kết nối tin cậy không bị ảnh hưởng; giao xong thì trả chỗ."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    anon1 = await raw_opening(raw_client, h, None, wire_hello(ids.anon), None)

    with pytest.raises(Rejected):
        await anon_pairing(h, ids)
    over = await raw_client(h.port, None)
    _, data = await over.expect_closed(2.0)
    assert data == b"", "kết nối ẩn danh vượt giới hạn không được nhận hello (mục 3.1 bước 4)"

    control = await b_control(h, ids)
    try:
        anon1.send_dict(to_dict(pair_request(ids.anon)))
        await anon1.drain()
        await wait_until(lambda: h.calls == 2, 2.0, "anon1 được giao sau khi gửi pair_request")
        second = await anon_pairing(h, ids)
        await second.close()
    finally:
        await control.close()


@pytest.mark.integration
async def test_anonymous_slot_is_freed_when_waiting_client_leaves(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """L4 (ca riêng): anon1 đóng trước khi được giao cũng trả chỗ."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    h = await listener_factory(ids.server)
    anon1 = await raw_opening(raw_client, h, None, wire_hello(ids.anon), None)
    with pytest.raises(Rejected):
        await anon_pairing(h, ids)
    anon1.abort()
    await h.wait_idle()
    conn = await anon_pairing(h, ids)
    await conn.close()
    assert h.calls == 0


@pytest.mark.integration
async def test_total_anonymous_limit(fast, monkeypatch, listener_factory, raw_client, ids):
    """L5: MAX_ANONYMOUS_PER_IP = 100, MAX_ANONYMOUS_TOTAL = 2 → kết nối ẩn danh thứ 3 → Rejected."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    monkeypatch.setattr(admission, "MAX_ANONYMOUS_PER_IP", 100)
    monkeypatch.setattr(admission, "MAX_ANONYMOUS_TOTAL", 2)
    h = await listener_factory(ids.server)
    await raw_opening(raw_client, h, None, wire_hello(ids.anon), None)
    await raw_opening(raw_client, h, None, wire_hello(ids.anon), None)
    with pytest.raises(Rejected):
        await anon_pairing(h, ids)


async def sc_unknown_cert(env):
    with pytest.raises(Rejected):
        await b_control(env.h, env.ids, identity=env.ids.x)


async def sc_silent_after_handshake(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    return peer


async def sc_silent_tcp(env):
    return await env.raw_client(env.h.port, use_tls=False)


async def sc_slowloris(env):
    peer = await env.raw_client(env.h.port, None)
    await peer.read_hello()
    peer.send_bytes(encode_message(wire_hello(env.ids.anon))[:3])
    await peer.drain()
    return peer


def assert_no_counter_entries(listener) -> None:
    """Bất biến mục 3.5: không còn vé nào đang mở đầu (chỗ ẩn danh được kiểm bằng hành vi ở dưới)."""
    assert listener.opening_count == 0


ALL_REJECTIONS = {
    "R1-unknown-cert": sc_unknown_cert,
    **IMMEDIATE_REJECTIONS,
    "R8-silent-after-handshake": sc_silent_after_handshake,
    "R9-silent-tcp": sc_silent_tcp,
    "R10-partial-hello": sc_slowloris,
}


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("case", list(ALL_REJECTIONS))
async def test_counters_are_released_after_every_rejection(
    fast, monkeypatch, listener_factory, raw_client, ids, case
):
    """L6: sau mỗi lý do từ chối, opening_count về 0 và Listener vẫn nhận đủ 4 kết nối mới."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 1.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    env = SimpleNamespace(h=h, ids=ids, raw_client=raw_client)
    peer = await ALL_REJECTIONS[case](env)
    if peer is not None:
        await peer.expect_closed(4.0)
        peer.abort()
    await h.wait_idle()
    assert h.calls == 0
    assert_no_counter_entries(h.listener)

    # Chỗ ẩn danh cũng đã được trả.
    conn = await anon_pairing(h, ids)
    await conn.close()
    await h.wait_idle()
    assert_no_counter_entries(h.listener)

    fresh = await open_silent_tcp(raw_client, h, 4)
    for p in fresh:
        assert await p.stays_open(0.1)
    await wait_until(lambda: h.listener.opening_count == 4, 2.0, "4 kết nối mới đang mở đầu")


# =================================================================================================
# T: đổi danh sách tin cậy
# =================================================================================================


@pytest.mark.integration
async def test_update_trusted_takes_effect_without_reopening(fast, listener_factory, ids):
    """T1."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    port = h.port
    old = await b_control(h, ids)
    try:
        old_server = await h.next()
        h.listener.update_trusted([])
        h.trusted_fps.clear()

        with pytest.raises(Rejected):
            await b_control(h, ids)
        assert h.listener.port == port

        # Kết nối cũ vẫn dùng được: Listener không tự đóng nó.
        await old.send(Ping(t=1))
        assert await asyncio.wait_for(old_server.receive(), 2) == Ping(t=1)
        await old_server.send(Pong(t=1))
        assert await asyncio.wait_for(old.receive(), 2) == Pong(t=1)
        assert h.calls == 1
    finally:
        await old.close()


@pytest.mark.integration
async def test_unpair_during_handshake_is_caught_at_control_open(
    slow_opening, listener_factory, raw_client, ids
):
    """T2: bắt tay xong bằng context cũ, rồi bị hủy ghép đôi, rồi mới gửi control_open → bị đóng."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer = await raw_opening(raw_client, h, ids.b, wire_hello(ids.b), None)
    await asyncio.sleep(0.1)  # server đã đọc hello và đang chờ message mở đầu
    h.listener.update_trusted([])
    h.trusted_fps.clear()
    peer.send_dict({"type": "control_open"})
    await peer.drain()
    await assert_rejected(h, peer)


@pytest.mark.integration
async def test_is_trusted_raising_counts_as_untrusted(slow_opening, listener_factory, raw_client, ids):
    """Mục 3.1 bước 7: `is_trusted` raise → coi như False."""

    def broken(fp):
        raise RuntimeError("kho tin cậy hỏng")

    h = await listener_factory(ids.server, trusted=[ids.b], is_trusted=broken)
    peer = await raw_opening(raw_client, h, ids.b, wire_hello(ids.b), {"type": "control_open"})
    await assert_rejected(h, peer)
    # Listener vẫn sống.
    conn = await anon_pairing(h, ids)
    await conn.close()


@pytest.mark.integration
async def test_newly_trusted_device_connects_without_restart(fast, listener_factory, ids):
    """T3."""
    h = await listener_factory(ids.server, trusted=[])
    port = h.port
    with pytest.raises(Rejected):
        await b_control(h, ids)
    h.listener.update_trusted([ids.b.cert_pem()])
    h.trusted_fps.add(ids.b.fingerprint)
    conn = await b_control(h, ids)
    try:
        assert (await h.next()).peer.fingerprint == ids.b.fingerprint
        assert h.listener.port == port
    finally:
        await conn.close()


@pytest.mark.integration
async def test_tls_session_is_never_resumed(fast, listener_factory, ids):
    """T4: không có session ticket, nên session cũ không đưa máy vừa bị hủy ghép đôi vào lại."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    port = h.port
    ctx = tls.trusted_client_context(ids.b, ids.server.cert_pem())

    def first():
        s = sync_connect(port, ctx)
        try:
            hello = sync_read_frame(s)
            return s.session, hello
        finally:
            s.close()

    def again():
        s = sync_connect(port, ctx, session=s1)
        try:
            return s.session_reused, sync_read_frame(s)
        finally:
            s.close()

    def after_unpair():
        try:
            s = sync_connect(port, ctx, session=s1)
        except (ssl.SSLError, OSError):
            return "handshake-failed"
        try:
            reused = s.session_reused
            try:
                msg = sync_read_frame(s)
            except (ssl.SSLError, OSError):
                return "closed" if not reused else "reused-then-closed"
            if msg is None:
                return "eof" if not reused else "reused-then-eof"
            return msg
        finally:
            s.close()

    s1, hello1 = await asyncio.to_thread(first)
    assert hello1 is not None and hello1["type"] == "hello"
    reused, hello2 = await asyncio.to_thread(again)
    assert reused is False
    assert hello2 is not None and hello2["type"] == "hello"

    h.listener.update_trusted([])
    h.trusted_fps.clear()
    result = await asyncio.to_thread(after_unpair)
    assert result in ("handshake-failed", "closed", "eof"), f"máy đã hủy ghép đôi vẫn đọc được: {result!r}"
    await h.wait_idle()
    assert h.calls == 0


@pytest.mark.integration
@pytest.mark.parametrize("bad_pem", BAD_PEMS, ids=BAD_PEM_IDS)
async def test_bad_update_keeps_old_context(fast, listener_factory, ids, bad_pem):
    """T5."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    with pytest.raises(PEM_ERRORS):
        h.listener.update_trusted([bad_pem])
    conn = await b_control(h, ids)
    try:
        assert (await h.next()).peer.fingerprint == ids.b.fingerprint
    finally:
        await conn.close()


@pytest.mark.integration
async def test_update_trusted_after_close_is_noop(fast, listener_factory, ids):
    h = await listener_factory(ids.server)
    await h.listener.close()
    h.listener.update_trusted([ids.b.cert_pem()])


# =================================================================================================
# C: phía client
# =================================================================================================


async def _hold(server, reader, writer):
    """Kịch bản server giả: nhận kết nối, không gửi gì, giữ tới khi bị đóng."""
    await server.record_until_closed(reader, timeout=30)


def send_then_hold(data: bytes):
    async def script(server, reader, writer):
        writer.write(data)
        await writer.drain()
        await server.record_until_closed(reader)

    return script


async def _open_kind(kind: str, port: int, ids, expected: str | None = None):
    if kind == "pairing":
        return await open_pairing([LOCAL], port, hello_of(ids.anon))
    if kind == "data":
        return await connection.open_data(
            LOCAL, port, ids.b, hello_of(ids.b), expected or ids.server.cert_pem(), DATA_OPEN_MSG
        )
    return await open_control([LOCAL], port, ids.b, hello_of(ids.b), expected or ids.server.cert_pem())


@pytest.mark.integration
async def test_wrong_server_identity_fails_handshake_and_sends_nothing(slow_opening, fake_server, ids):
    """C1 (`docs/protocol.md` mục 2.2): server mang danh tính khác ở địa chỉ máy tin cậy, lại tin
    chứng chỉ client → client từ chối ngay trong bắt tay: IdentityMismatch (không có fingerprint
    thật); phía server bắt tay không xong nên handler không bao giờ chạy và không nhận được byte ứng
    dụng nào."""

    async def record(server, reader, writer):
        await server.record_until_closed(reader, timeout=5)

    server = await fake_server(ids.server, record, trusted_certs=[ids.b.cert_pem()])
    start = time.monotonic()
    with pytest.raises(IdentityMismatch) as exc:
        await open_control([LOCAL], server.port, ids.b, hello_of(ids.b), ids.x.cert_pem())
    assert time.monotonic() - start < 2.0, "phải báo ngay khi bắt tay, không chờ hết giờ"
    assert exc.value.actual_fingerprint is None
    assert exc.value.address == LOCAL
    await asyncio.sleep(0.2)
    assert server.connections == 0, "server giả đã bắt tay xong (đã nhận chứng chỉ client)"
    assert bytes(server.received) == b""


def forge_same_name_identity(real, directory):
    """Danh tính giả mạo `real`: cùng subject, issuer (CN `teleport-<device_id>`), serial, hạn và
    extension, nhưng khóa khác. Chép ở `tests/net/test_tls.py` (không import được giữa file test)."""
    directory.mkdir(parents=True, exist_ok=True)
    real_cert = x509.load_pem_x509_certificate(real.cert_path.read_bytes())
    key = ec.generate_private_key(ec.SECP256R1())
    builder = (
        x509.CertificateBuilder()
        .subject_name(real_cert.subject)
        .issuer_name(real_cert.issuer)
        .public_key(key.public_key())
        .serial_number(real_cert.serial_number)
        .not_valid_before(real_cert.not_valid_before_utc)
        .not_valid_after(real_cert.not_valid_after_utc)
    )
    for ext in real_cert.extensions:
        builder = builder.add_extension(ext.value, ext.critical)
    cert = builder.sign(key, hashes.SHA256())
    cert_path, key_path = directory / CERT_FILE, directory / KEY_FILE
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return Identity(real.device_id, cert_path, key_path, hashlib.sha256(der).hexdigest())


@pytest.mark.integration
async def test_impostor_with_same_cn_and_serial_but_other_key_is_identity_mismatch(
    slow_opening, fake_server, ids, tmp_path
):
    """Server giả dùng chứng chỉ cùng subject/issuer/serial (cùng CN `teleport-<device_id>`) với máy tin
    cậy, khóa khác, và tin chứng chỉ client: `open_control` → IdentityMismatch ngay trong bắt tay (không
    có fingerprint thật); server giả không bắt tay xong nên handler không chạy, không nhận byte nào."""
    fake = forge_same_name_identity(ids.server, tmp_path / "fake")
    assert fake.device_id == ids.server.device_id
    assert fake.fingerprint != ids.server.fingerprint

    async def record(server, reader, writer):
        await server.record_until_closed(reader, timeout=5)

    server = await fake_server(fake, record, trusted_certs=[ids.b.cert_pem()])
    start = time.monotonic()
    with pytest.raises(IdentityMismatch) as exc:
        await open_control([LOCAL], server.port, ids.b, hello_of(ids.b), ids.server.cert_pem())
    assert time.monotonic() - start < 2.0, "phải báo ngay khi bắt tay, không chờ hết giờ"
    assert exc.value.actual_fingerprint is None
    assert exc.value.address == LOCAL
    await asyncio.sleep(0.2)
    assert server.connections == 0, "server giả đã bắt tay xong (đã nhận chứng chỉ client)"
    assert bytes(server.received) == b""


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_server_hello_device_id_must_match_cn(slow_opening, fake_server, ids, kind):
    """C2."""
    server = await fake_server(
        ids.server, send_then_hold(encode_message(wire_hello(ids.x))), trusted_certs=[ids.b.cert_pem()]
    )
    start = time.monotonic()
    with pytest.raises(IdentityMismatch):
        await _open_kind(kind, server.port, ids)
    assert time.monotonic() - start < 2.0


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_newer_protocol_is_version_mismatch(slow_opening, fake_server, ids, kind):
    """C3: hello bản mới (protocol 2, có trường lạ) → VersionMismatch, không phải lỗi parse."""
    hello = wire_hello(ids.server, protocol=2, capabilities={"quic": True}, name="")
    server = await fake_server(
        ids.server, send_then_hold(encode_message(hello)), trusted_certs=[ids.b.cert_pem()]
    )
    with pytest.raises(VersionMismatch) as exc:
        await _open_kind(kind, server.port, ids)
    assert exc.value.peer_protocol == 2
    assert exc.value.address == LOCAL


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
@pytest.mark.parametrize("how", ["graceful", "abort"])
async def test_close_after_handshake_is_rejected(slow_opening, fake_server, ids, kind, how):
    """C4: server đóng ngay sau bắt tay, không gửi hello → Rejected (không phải Unreachable)."""

    async def close_now(server, reader, writer):
        if how == "abort":
            writer.transport.abort()
        else:
            writer.close()
        await asyncio.sleep(0)

    server = await fake_server(ids.server, close_now, trusted_certs=[ids.b.cert_pem()])
    start = time.monotonic()
    with pytest.raises(Rejected) as exc:
        await _open_kind(kind, server.port, ids)
    assert exc.value.address == LOCAL
    assert time.monotonic() - start < 2.0


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_closed_port_is_unreachable(fast, ids, kind):
    """C5a."""
    port = free_port()
    with pytest.raises(Unreachable) as exc:
        await _open_kind(kind, port, ids)
    assert exc.value.address == LOCAL


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_server_that_never_handshakes_is_unreachable(fast, fake_server, ids, kind):
    """C5b: TCP nhận nhưng không bao giờ bắt tay TLS → Unreachable sau ≈ OPENING_TIMEOUT."""
    server = await fake_server(None, _hold, use_tls=False)
    start = time.monotonic()
    with pytest.raises(Unreachable) as exc:
        await _open_kind(kind, server.port, ids)
    elapsed = time.monotonic() - start
    assert 0.4 <= elapsed <= 0.5 + 2.5
    assert exc.value.address == LOCAL


@pytest.mark.integration
@pytest.mark.parametrize(
    "data",
    [
        HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1) + b"x" * 64,
        b"HTTP/1.1 400 Bad Request\r\n\r\n",
        frame(b"\xff\xfe\xfd\xfc"),
        frame(b"[1, 2]"),
        encode_message({"type": "ping", "t": 1}),
        encode_message({"type": "hello"}),
    ],
    ids=["header>16KiB", "http", "bad-utf8", "json-array", "ping", "hello-missing-fields"],
)
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_non_teleport_server_is_unreachable(slow_opening, fake_server, ids, kind, data):
    """C6: máy kia không nói giao thức Teleport → Unreachable, ngay khi đọc (không chờ hết giờ)."""
    server = await fake_server(ids.server, send_then_hold(data), trusted_certs=[ids.b.cert_pem()])
    start = time.monotonic()
    with pytest.raises(Unreachable):
        await _open_kind(kind, server.port, ids)
    assert time.monotonic() - start < 2.0


@pytest.mark.integration
async def test_dead_address_next_to_good_one_does_not_delay(monkeypatch, listener_factory, ids):
    """C7: OPENING_TIMEOUT để mặc định 10 s; địa chỉ câm không được kéo dài lần mở."""
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 0.5)
    assert connection.OPENING_TIMEOUT == 10.0
    h = await listener_factory(ids.server, trusted=[ids.b])
    start = time.monotonic()
    conn = await b_control(h, ids, addresses=(TEST_NET, LOCAL))
    try:
        assert time.monotonic() - start < 2.0
        assert conn.peer.address == LOCAL
        await h.next()
    finally:
        await conn.close()


@pytest.mark.slow
@pytest.mark.integration
async def test_all_addresses_fail_reports_most_relevant_error(fast, monkeypatch, listener_factory, ids):
    """C8: TEST-NET (Unreachable/treo) + 127.0.0.1 sai fingerprint → IdentityMismatch trong ≤ 2,5 s."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 1.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    start = time.monotonic()
    with pytest.raises(IdentityMismatch) as exc:
        await b_control(h, ids, expected=ids.x.cert_pem(), addresses=(TEST_NET, LOCAL))
    assert time.monotonic() - start <= 2.5
    assert exc.value.address == LOCAL
    assert exc.value.actual_fingerprint is None  # lỗi ngay trong bắt tay (protocol mục 2.2)
    assert h.calls == 0


@pytest.mark.integration
async def test_cancelling_open_leaves_nothing_behind(fast, monkeypatch, fake_server, ids):
    """C9: hủy task open_control giữa chừng → không còn task hay socket (kiểm bởi no_leaks)."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 10.0)
    server = await fake_server(None, _hold, use_tls=False)
    task = asyncio.create_task(
        open_control([TEST_NET, LOCAL], server.port, ids.b, hello_of(ids.b), ids.server.cert_pem())
    )
    await wait_until(lambda: server.connections == 1, 2.0, "client đã nối TCP tới server câm")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # Server câm thấy kết nối của client bị đóng.
    await wait_until(lambda: not server._tasks, 2.0, "socket phía client đã đóng")


# --- M1: chứng chỉ server không phân tích được → IdentityMismatch --------------------------------


async def _record(server, reader, writer):
    await server.record_until_closed(reader, timeout=5)


@pytest.mark.integration
@pytest.mark.parametrize("san", ["x400", "edi"])
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_m1_server_cert_with_unsupported_general_name_is_identity_mismatch(
    slow_opening, fake_server, make_san_identity, ids, kind, san
):
    """Chứng chỉ server có SAN x400Address/EDIPartyName → IdentityMismatch ngay, không lọt lỗi lạ.

    Kết nối điều khiển và dữ liệu: chứng chỉ mong đợi chính là chứng chỉ đó, nên `open_control` /
    `open_data` từ chối nó bằng ValueError trước mọi I/O (`peer_cert_from_pem`, protocol mục 2.1).
    """
    evil = make_san_identity(san)
    server = await fake_server(evil, _record, trusted_certs=[ids.b.cert_pem()])
    start = time.monotonic()
    if kind in ("control", "data"):
        with pytest.raises(ValueError):
            await _open_kind(kind, server.port, ids, expected=evil.cert_pem())
        await asyncio.sleep(0.1)
        assert server.connections == 0
        return
    with pytest.raises(IdentityMismatch) as exc:
        await _open_kind(kind, server.port, ids)
    assert time.monotonic() - start < 2.0, "phải báo ngay, không chờ hết giờ"
    assert exc.value.address == LOCAL
    assert exc.value.actual_fingerprint == evil.fingerprint
    await wait_until(lambda: not server._tasks, 3.0, "server giả thấy client đóng")
    assert server.connections == 1, "server giả không thấy kết nối nào: phép kiểm vô nghĩa"


@pytest.mark.integration
@pytest.mark.parametrize("kind", OPEN_KINDS)
async def test_m1_unexpected_error_parsing_server_cert_is_identity_mismatch(
    slow_opening, monkeypatch, fake_server, ids, kind
):
    """Lớp phòng thủ ở net: phân tích chứng chỉ server ném lỗi lạ bất kỳ → vẫn là IdentityMismatch."""

    class OddError(Exception):
        pass

    calls: list[bytes] = []

    def broken(der):
        calls.append(der)
        raise OddError("lỗi lạ khi phân tích chứng chỉ")

    monkeypatch.setattr(connection, "peer_cert_from_der", broken)
    server = await fake_server(ids.server, _record, trusted_certs=[ids.b.cert_pem()])
    with pytest.raises(IdentityMismatch) as exc:
        await _open_kind(kind, server.port, ids)
    assert calls, "peer_cert_from_der bị thay chưa được gọi: phép thử vô nghĩa"
    assert exc.value.address == LOCAL
    assert exc.value.actual_fingerprint == ids.server.fingerprint
    assert isinstance(exc.value.__cause__, OddError)


# =================================================================================================
# A: API của Connection
# =================================================================================================


@pytest.mark.integration
@pytest.mark.parametrize(
    "msg",
    [
        hello_of(SimpleNamespace(device_id="0" * 32)),
        ControlOpen(),
        PairCommit(commitment=HEX64),
        PairNonce(nonce=HEX64, signature=HEX64 + HEX64),
        PairReveal(nonce=HEX64),
    ],
    ids=lambda m: type(m).__name__,
)
async def test_send_rejects_type_not_allowed_on_control(fast, listener_factory, ids, msg):
    """A1 (CONTROL): ValueError, không có byte nào đi ra."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    try:
        server = await h.next()
        with pytest.raises(ValueError):
            await conn.send(msg)
        with pytest.raises(ValueError):
            await server.send(msg)
        assert not conn.closed
        await conn.send(Ping(t=3))
        assert await asyncio.wait_for(server.receive(), 2) == Ping(t=3)
    finally:
        await conn.close()


@pytest.mark.integration
async def test_send_rejects_pair_request_on_control(fast, listener_factory, ids):
    """A1 (CONTROL): PairRequest."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    try:
        server = await h.next()
        with pytest.raises(ValueError):
            await conn.send(pair_request(ids.b))
        await conn.send(Pong(t=9))
        assert await asyncio.wait_for(server.receive(), 2) == Pong(t=9)
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.parametrize("msg", [Ping(t=1), Pong(t=1), ControlOpen()], ids=lambda m: type(m).__name__)
async def test_send_rejects_type_not_allowed_on_pairing(fast, listener_factory, ids, msg):
    """A1 (PAIRING): ValueError; byte không đi ra, nên pair_request gửi sau vẫn là message mở đầu."""
    h = await listener_factory(ids.server)
    conn = await anon_pairing(h, ids)
    try:
        with pytest.raises(ValueError):
            await conn.send(msg)
        request = pair_request(ids.anon)
        await conn.send(request)
        server = await h.next()
        assert server.opening == request
    finally:
        await conn.close()


@pytest.mark.integration
async def test_receive_on_control_reports_wrong_kind_and_unknown_type(
    fast, listener_factory, raw_client, ids
):
    """A2 (CONTROL)."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    peer.send_dict({"type": "pair_commit", "commitment": HEX64})
    await peer.drain()
    with pytest.raises(WrongConnectionKind):
        await asyncio.wait_for(server.receive(), 2)
    peer.send_dict({"type": "pair_nonce", "nonce": HEX64, "signature": HEX64 + HEX64})
    await peer.drain()
    with pytest.raises(WrongConnectionKind):
        await asyncio.wait_for(server.receive(), 2)
    # Type của luồng cũ không còn tồn tại: là type lạ, không phải sai loại kết nối.
    peer.send_dict({"type": "pair_challenge", "nonce": HEX64})
    await peer.drain()
    with pytest.raises(UnknownMessageType):
        await asyncio.wait_for(server.receive(), 2)
    peer.send_dict({"type": "future_thing", "x": 1})
    await peer.drain()
    with pytest.raises(UnknownMessageType):
        await asyncio.wait_for(server.receive(), 2)
    peer.send_dict({"type": "ping", "t": 5})
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 2) == Ping(t=5)


@pytest.mark.integration
async def test_receive_on_pairing_enforces_16_kib(fast, listener_factory, raw_client, ids):
    """A2 (PAIRING): header > 16 KiB → FramingError."""
    h = await listener_factory(ids.server)
    peer, server = await raw_pairing(raw_client, h, ids)
    peer.send_bytes(HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1))
    await peer.drain()
    with pytest.raises(FramingError):
        await asyncio.wait_for(server.receive(), 2)


@pytest.mark.integration
async def test_receive_aborts_after_framing_error(fast, listener_factory, raw_client, ids):
    """Header vượt trần → kết nối bị đóng, lần sau ConnectionLostError (không đọc thân lệch khung)."""
    h = await listener_factory(ids.server)
    peer, server = await raw_pairing(raw_client, h, ids)
    body = HEADER.pack(5) + b'{"a":'  # thân "trông như" một khung khác nếu đọc tiếp
    peer.send_bytes(HEADER.pack(MAX_PAIRING_MESSAGE_SIZE + 1) + body)
    await peer.drain()
    with pytest.raises(FramingError):
        await asyncio.wait_for(server.receive(), 2)
    assert server.closed
    with pytest.raises(ConnectionLostError):
        await asyncio.wait_for(server.receive(), 2)


@pytest.mark.integration
async def test_receive_on_control_allows_more_than_16_kib(fast, listener_factory, raw_client, ids):
    """CONTROL đọc với MAX_MESSAGE_SIZE: message 20 KiB (trường lạ) vẫn nhận được."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    peer.send_dict({"type": "ping", "t": 1, "pad": "x" * 20_000})
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 2) == Ping(t=1)


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["pairing", "control"])
async def test_receive_returns_none_on_clean_eof(fast, listener_factory, raw_client, ids, kind):
    """A2: EOF gọn ở ranh giới message → None."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    if kind == "pairing":
        peer, server = await raw_pairing(raw_client, h, ids)
    else:
        peer, server = await raw_control(raw_client, h, ids)
    await peer.close_gracefully()
    assert await asyncio.wait_for(server.receive(), 2) is None


@pytest.mark.integration
async def test_concurrent_receive_is_runtime_error(fast, listener_factory, ids):
    """A3."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    try:
        server = await h.next()
        first = asyncio.create_task(conn.receive())
        await asyncio.sleep(0.05)
        with pytest.raises(RuntimeError):
            await conn.receive()
        await server.send(Ping(t=11))
        assert await asyncio.wait_for(first, 2) == Ping(t=11)
    finally:
        await conn.close()


@pytest.mark.integration
async def test_use_after_close_and_double_close(fast, listener_factory, ids):
    """A4."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    server = await h.next()

    await conn.close()
    assert conn.closed
    with pytest.raises(ConnectionLostError):
        await conn.send(Ping(t=1))
    with pytest.raises(ConnectionLostError):
        await conn.receive()
    await conn.close()

    assert await asyncio.wait_for(server.receive(), 2) is None
    await asyncio.gather(server.close(), server.close())
    assert server.closed
    with pytest.raises(ConnectionLostError):
        await server.send(Pong(t=1))
    with pytest.raises(ConnectionLostError):
        await server.receive()


@pytest.mark.integration
async def test_close_wakes_pending_receive(fast, listener_factory, ids):
    """Một `receive` đang chờ thì bị close() → ConnectionLostError (kết nối đã đóng)."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    await h.next()
    pending = asyncio.create_task(conn.receive())
    await asyncio.sleep(0.05)
    await conn.close()
    with pytest.raises(ConnectionLostError):
        await asyncio.wait_for(pending, 2)


@pytest.mark.integration
async def test_close_is_bounded_when_peer_never_answers(fast, listener_factory, ids):
    """A5: máy kia không bao giờ đọc nên không trả close_notify → close() ≤ CLOSE_TIMEOUT + 1 s."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    try:
        server = await h.next()
        start = time.monotonic()
        await server.close()
        assert time.monotonic() - start <= 0.5 + 1.0
        assert server.closed
    finally:
        sock.close()


@pytest.mark.slow
@pytest.mark.integration
async def test_send_gives_up_when_peer_never_reads(fast, listener_factory, ids):
    """A6: DRAIN_TIMEOUT = 0,5 s; máy kia không đọc; gửi Ping liên tục → ConnectionLostError ≤ 10 s."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b, rcvbuf=4096)
    try:
        server = await h.next()
        start = time.monotonic()
        with pytest.raises(ConnectionLostError):
            async with asyncio.timeout(15):
                while True:
                    await server.send(Ping(t=1))
        assert time.monotonic() - start <= 10.0
        assert server.closed
    finally:
        sock.close()


@pytest.mark.integration
async def test_concurrent_sends_do_not_interleave(fast, listener_factory, raw_client, ids):
    """Mục 2.3: send chạy dưới lock, nên các lần gửi đồng thời ra đúng từng khung nguyên vẹn."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    await asyncio.gather(*(server.send(Ping(t=i)) for i in range(200)))
    got = [await peer.read() for _ in range(200)]
    assert sorted(m["t"] for m in got) == list(range(200))


# =================================================================================================
# K-: ControlChannel (ping_interval = 0.2, dead_after = 0.6)
# =================================================================================================


def start_channel(conn, received: list, **kwargs):
    kwargs.setdefault("ping_interval", PI)
    kwargs.setdefault("dead_after", DA)
    channel = ControlChannel(conn, **kwargs)
    task = asyncio.create_task(channel.run(received.append))
    return channel, task


@pytest.mark.integration
async def test_channel_answers_ping_with_same_t(fast, listener_factory, raw_client, ids):
    """K-1."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    channel, task = start_channel(server, received)
    try:
        assert channel.connection is server
        peer.send_dict({"type": "ping", "t": 12345})
        await peer.drain()
        pong = await read_until_type(peer, "pong")
        assert pong["t"] == 12345
        await wait_until(lambda: Ping(t=12345) in received, 1.0, "on_message nhận Ping")
    finally:
        await cancel_wait(task)


@pytest.mark.integration
async def test_channel_dies_after_silence(fast, listener_factory, raw_client, ids):
    """K-2: máy kia giữ kết nối nhưng im lặng → KEEPALIVE trong 0,48–3 s."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    start = time.monotonic()
    _, task = start_channel(server, [])
    reason = await asyncio.wait_for(task, 5)
    elapsed = time.monotonic() - start
    assert reason is CloseReason.KEEPALIVE
    assert 0.48 <= elapsed <= 3.0
    assert server.closed
    await peer.expect_closed(2.0)


@pytest.mark.slow
@pytest.mark.integration
async def test_two_channels_keep_each_other_alive(fast, listener_factory, ids):
    """K-3: hai ControlChannel ở hai đầu chạy 2 s, không bên nào kết thúc."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    client = await b_control(h, ids)
    server = await h.next()
    got_client: list = []
    got_server: list = []
    _, t1 = start_channel(client, got_client)
    _, t2 = start_channel(server, got_server)
    try:
        done, _ = await asyncio.wait({t1, t2}, timeout=2.0)
        assert not done, f"kênh kết thúc sớm: {[t.result() for t in done if not t.exception()]}"
        pings = sum(isinstance(m, Ping) for m in got_client + got_server)
        assert pings >= 3
        # Mỗi bên đều thấy lưu lượng keepalive của bên kia.
        assert len(got_client) >= 3
        assert len(got_server) >= 3
    finally:
        await cancel_wait(t1, t2)


@pytest.mark.slow
@pytest.mark.integration
async def test_partial_message_counts_as_alive(fast, listener_factory, raw_client, ids):
    """K-4: một message lớn tới từng mẩu 1 KB mỗi 20 ms, lâu hơn dead_after nhiều lần → không chết.

    Độ dài lần gửi được khẳng định bằng cận dưới lý thuyết (số mẩu × khoảng nghỉ), không bằng
    đồng hồ thực đo: `asyncio.sleep` không bao giờ ngủ ít hơn khoảng đã hẹn.
    """
    piece, gap = 1024, 0.02
    data = encode_message({"type": "ping", "t": 1, "pad": "x" * 102_400})
    pieces = -(-len(data) // piece)
    assert pieces >= 100
    assert pieces * gap > 2 * DA, "phép thử quá ngắn: không vượt được 2 × dead_after"

    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received)
    try:
        start = time.monotonic()
        for i in range(0, len(data), piece):
            assert not task.done(), f"kênh kết thúc sau {time.monotonic() - start:.2f} s: {task.result()!r}"
            peer.send_bytes(data[i : i + piece])
            await peer.drain()
            await asyncio.sleep(gap)
        await wait_until(lambda: Ping(t=1) in received, 0.5, "on_message nhận Ping(t=1)")
        assert not task.done()
    finally:
        await cancel_wait(task)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("peer_closed", CloseReason.PEER_CLOSED),
        ("garbage", CloseReason.PROTOCOL_ERROR),
        ("oversized", CloseReason.PROTOCOL_ERROR),
        ("pair_commit", CloseReason.PROTOCOL_ERROR),
        ("ping_missing_t", CloseReason.PROTOCOL_ERROR),
        ("local_close", CloseReason.LOCAL),
    ],
)
async def test_channel_close_reasons(fast, listener_factory, raw_client, ids, case, expected):
    """K-5."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], dead_after=5.0)
    try:
        await asyncio.sleep(0.05)
        if case == "peer_closed":
            await peer.close_gracefully()
        elif case == "garbage":
            peer.send_bytes(frame(b"\xff\xfe\xfd\xfc\xfb"))
        elif case == "oversized":
            peer.send_bytes(HEADER.pack(0xFFFFFFFF))
        elif case == "pair_commit":
            peer.send_dict({"type": "pair_commit", "commitment": HEX64})
        elif case == "ping_missing_t":
            peer.send_dict({"type": "ping"})
        else:
            await server.close()
        await peer.drain()
        assert await asyncio.wait_for(task, 3) is expected
        assert server.closed
    finally:
        await cancel_wait(task)


@pytest.mark.integration
async def test_channel_ignores_unknown_type(fast, listener_factory, raw_client, ids):
    """K-5: `type` lạ → bỏ qua, kênh chạy tiếp và vẫn trả lời ping."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received, dead_after=5.0)
    try:
        peer.send_dict({"type": "offer_v9", "files": [1, 2]})
        peer.send_dict({"type": "ping", "t": 77})
        await peer.drain()
        assert (await read_until_type(peer, "pong"))["t"] == 77
        assert not task.done()
        assert received == [Ping(t=77)]
    finally:
        await cancel_wait(task)


@pytest.mark.integration
async def test_idle_channel_sends_valid_ping(fast, listener_factory, raw_client, ids):
    """K-6: khi rảnh, máy kia nhận Ping trong ≤ ping_interval + 1 s, 0 ≤ t ≤ 2⁵³ − 1."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [])
    try:
        msg = await peer.read(timeout=PI + 1.0)
        assert msg is not None and msg["type"] == "ping"
        t = msg["t"]
        assert isinstance(t, int) and not isinstance(t, bool)
        assert 0 <= t <= MAX_SAFE_INTEGER
    finally:
        await cancel_wait(task)


@pytest.mark.slow
@pytest.mark.integration
async def test_app_sends_suppress_pings(fast, listener_factory, raw_client, ids):
    """K-7: app gửi Pong mỗi 0,1 s qua conn.send, ping_interval = 0,3 → máy kia không nhận Ping nào."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], ping_interval=0.3, dead_after=5.0)

    async def app_traffic():
        while True:
            await server.send(Pong(t=1))
            await asyncio.sleep(0.1)

    sender = asyncio.create_task(app_traffic())
    try:
        msgs = await read_messages_for(peer, 1.0)
        assert [m for m in msgs if m["type"] == "ping"] == []
        assert sum(m["type"] == "pong" for m in msgs) >= 5
        assert not task.done()
    finally:
        await cancel_wait(sender, task)


@pytest.mark.integration
async def test_channel_misuse(fast, listener_factory, raw_client, ids):
    """K-8: run gọi lần hai → RuntimeError; kênh trên kết nối PAIRING / tham số sai → ValueError."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    _, server = await raw_control(raw_client, h, ids)
    with pytest.raises(ValueError):
        ControlChannel(server, ping_interval=1.0, dead_after=1.0)
    with pytest.raises(ValueError):
        ControlChannel(server, ping_interval=0.0, dead_after=1.0)
    channel, task = start_channel(server, [], dead_after=5.0)
    try:
        await asyncio.sleep(0.05)
        with pytest.raises(RuntimeError):
            await channel.run(lambda m: None)
        assert not task.done()
    finally:
        await cancel_wait(task)

    _, pairing = await raw_pairing(raw_client, h, ids)
    with pytest.raises(ValueError):
        ControlChannel(pairing)


@pytest.mark.integration
async def test_channel_on_closed_connection_returns_local(fast, listener_factory, raw_client, ids):
    """Mục 3.4 bước 1: kết nối đã đóng → run trả LOCAL ngay."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    _, server = await raw_control(raw_client, h, ids)
    await server.close()
    channel = ControlChannel(server, ping_interval=PI, dead_after=DA)
    assert await asyncio.wait_for(channel.run(lambda m: None), 1) is CloseReason.LOCAL


class Boom(Exception):
    pass


@pytest.mark.integration
async def test_on_message_error_closes_and_propagates(fast, listener_factory, raw_client, ids):
    """K-9."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)

    def explode(msg):
        raise Boom(msg)

    channel = ControlChannel(server, ping_interval=PI, dead_after=5.0)
    task = asyncio.create_task(channel.run(explode))
    peer.send_dict({"type": "pong", "t": 7})
    await peer.drain()
    with pytest.raises(Boom):
        await asyncio.wait_for(task, 3)
    assert server.closed
    await peer.expect_closed(2.0)


@pytest.mark.integration
async def test_cancelling_run_closes_connection(fast, listener_factory, raw_client, ids):
    """K-10: hủy run → kết nối đóng, không còn task (no_leaks kiểm)."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], dead_after=5.0)
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert server.closed
    await peer.expect_closed(2.0)


# =================================================================================================
# LC: vòng đời Listener
# =================================================================================================


@pytest.mark.integration
async def test_listener_close_cleans_up_everything(fast, monkeypatch, listener_factory, raw_client, ids):
    """LC1."""
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    cancelled: list = []
    delivered: list = []

    async def on_connection(conn):
        delivered.append(conn.kind)
        try:
            if conn.kind is ConnectionKind.CONTROL:
                await ControlChannel(conn).run(lambda m: None)
            else:
                await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(conn.kind)
            raise

    h = await listener_factory(ids.server, trusted=[ids.b], on_connection=on_connection)
    opening = await raw_client(h.port, use_tls=False)
    pairing = await anon_pairing(h, ids)
    await pairing.send(pair_request(ids.anon))
    control = await b_control(h, ids)
    try:
        await wait_until(lambda: len(delivered) == 2, 2.0, "hai kết nối được giao")
        await wait_until(lambda: h.listener.opening_count == 1, 2.0, "một kết nối đang mở đầu")
        assert h.listener.connection_count == 2

        start = time.monotonic()
        await h.listener.close()
        assert time.monotonic() - start <= 0.5 + 1.0

        leftover = [
            t.get_name() for t in asyncio.all_tasks() if t.get_name().startswith("teleport.connection")
        ]
        assert leftover == []
        assert sorted(cancelled) == sorted([ConnectionKind.CONTROL, ConnectionKind.PAIRING])
        assert h.listener.opening_count == 0
        assert h.listener.connection_count == 0
        await opening.expect_closed(2.0)
        await receive_closed(pairing)
        await receive_closed(control)

        await h.listener.close()
        with pytest.raises(RuntimeError):
            await h.listener.start(LOCAL, 0)
    finally:
        await pairing.close()
        await control.close()


@pytest.mark.integration
async def test_concurrent_listener_close(fast, listener_factory, ids):
    """Mục 2.3: close gọi đồng thời không lỗi."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    try:
        await h.next()
        await asyncio.gather(h.listener.close(), h.listener.close(), h.listener.close())
        assert h.listener.connection_count == 0
    finally:
        await conn.close()


@pytest.mark.integration
async def test_failing_handler_does_not_stop_listener(fast, listener_factory, ids):
    """LC2: on_connection raise → kết nối đó bị đóng; kết nối kế tiếp vẫn được nhận."""
    calls: list = []
    release = asyncio.Event()

    async def on_connection(conn):
        calls.append(conn)
        if len(calls) == 1:
            raise RuntimeError("handler hỏng")
        await release.wait()

    h = await listener_factory(ids.server, on_connection=on_connection)
    first = await anon_pairing(h, ids)
    try:
        await first.send(pair_request(ids.anon))
        await receive_closed(first)
        await wait_until(lambda: h.listener.connection_count == 0, 2.0, "kết nối lỗi được bỏ khỏi tập")
        assert calls[0].closed
    finally:
        await first.close()

    second = await anon_pairing(h, ids)
    try:
        await second.send(pair_request(ids.anon))
        await wait_until(lambda: len(calls) == 2, 2.0, "kết nối thứ hai được giao")
        assert not calls[1].closed
    finally:
        release.set()
        await second.close()


@pytest.mark.integration
async def test_listener_closes_connection_when_handler_returns(fast, listener_factory, ids):
    """LC3: on_connection trả về → Listener đóng kết nối, client thấy EOF."""
    handled: list = []

    async def on_connection(conn):
        handled.append(conn)

    h = await listener_factory(ids.server, trusted=[ids.b], on_connection=on_connection)
    conn = await b_control(h, ids)
    try:
        assert await asyncio.wait_for(conn.receive(), 3) is None
        await wait_until(lambda: h.listener.connection_count == 0, 2.0, "kết nối đã bị bỏ khỏi tập")
        assert handled[0].closed
    finally:
        await conn.close()


# =================================================================================================
# Bất biến bổ sung (mục 2.3, 3.1, 3.4, 3.5)
# =================================================================================================


@pytest.mark.integration
async def test_connection_tasks_are_named(slow_opening, listener_factory, raw_client, ids):
    """Mục 3.1 bước 0: task xử lý kết nối có tên bắt đầu bằng `teleport.connection`."""
    h = await listener_factory(ids.server)
    await raw_client(h.port, use_tls=False)
    await wait_until(lambda: h.listener.opening_count == 1, 2.0, "một kết nối đang mở đầu")
    names = [t.get_name() for t in asyncio.all_tasks()]
    assert any(n.startswith("teleport.connection") for n in names), names


@pytest.mark.integration
async def test_no_suspension_between_trust_check_and_handler(slow_opening, listener_factory, ids):
    """Mục 3.1 bước 8: giữa lần kiểm `is_trusted` **cuối** và phần đồng bộ đầu `on_connection` không có
    điểm dừng.

    Một callback xếp bằng `call_soon` trong `is_trusted` chỉ chạy được khi vòng lặp được nhường;
    nếu nó đã chạy lúc handler bắt đầu thì có một `await` thật ở giữa. `is_trusted` có thể được gọi
    nhiều lần cho một kết nối (sau bắt tay để quyết hoàn token, rồi lúc `control_open`; protocol mục 2.3),
    nên mỗi lần gọi đặt cờ mới; chỉ cờ của lần gọi cuối được xét.
    """
    loop = asyncio.get_running_loop()
    flags: list[dict] = []
    seen: list = []

    def is_trusted(fp):
        flag = {"ran": False}
        flags.append(flag)
        loop.call_soon(flag.__setitem__, "ran", True)
        return fp == ids.b.fingerprint

    async def on_connection(conn):
        seen.append((len(flags), flags[-1]["ran"]))

    h = await listener_factory(
        ids.server, trusted=[ids.b], is_trusted=is_trusted, on_connection=on_connection
    )
    conn = await b_control(h, ids)
    try:
        await wait_until(lambda: seen, 2.0, "on_connection được gọi")
        [(calls, ran)] = seen
        assert calls >= 1, "is_trusted chưa từng được gọi trước on_connection"
        assert ran is False, "có await thật giữa lần kiểm is_trusted cuối và on_connection"
    finally:
        await conn.close()


@pytest.mark.integration
async def test_logs_never_contain_message_content(slow_opening, listener_factory, raw_client, ids, caplog):
    """Mục 2.3 / N9: log chỉ ghi `type`, địa chỉ, lý do; không ghi nội dung message hay PEM."""
    caplog.set_level(logging.DEBUG)
    marker = "BIMAT-7f3a"
    h = await listener_factory(ids.server, trusted=[ids.b])

    # Ghép đôi hợp lệ có tên máy đánh dấu, gửi kèm chứng chỉ PEM.
    conn = await open_pairing([LOCAL], h.port, hello_of(ids.anon, f"PC {marker}"))
    await conn.send(pair_request(ids.anon))
    await h.next()
    await conn.close()
    await h.wait_idle()
    # Bị từ chối: hello bản khác có trường đánh dấu; message mở đầu sai có trường đánh dấu.
    p1 = await raw_opening(raw_client, h, None, wire_hello(ids.anon, protocol=2, note=marker), None)
    await p1.expect_closed(2.0)
    p2 = await raw_opening(raw_client, h, None, wire_hello(ids.anon, f"X {marker}"), {"type": marker})
    await p2.expect_closed(2.0)
    # Trên kênh điều khiển: type lạ mang dữ liệu đánh dấu.
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], dead_after=5.0)
    try:
        peer.send_dict({"type": "future_thing", "secret": marker})
        peer.send_dict({"type": "ping", "t": 1})
        await peer.drain()
        await read_until_type(peer, "pong")
    finally:
        await cancel_wait(task)

    assert marker not in caplog.text
    assert "BEGIN CERTIFICATE" not in caplog.text
    assert ids.anon.cert_pem().splitlines()[1] not in caplog.text


@pytest.mark.integration
async def test_duplicate_addresses_are_tried_once(fast, listener_factory, ids):
    """Mục 2.3: địa chỉ trùng được bỏ, không phải lỗi."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids, addresses=(LOCAL, LOCAL, LOCAL))
    try:
        assert conn.peer.address == LOCAL
        await h.next()
        await asyncio.sleep(0.2)
        assert h.calls == 1
    finally:
        await conn.close()


@pytest.mark.integration
async def test_on_message_sees_messages_in_order(fast, listener_factory, raw_client, ids):
    """Mục 3.4 bước 3: mọi message hợp lệ, gồm Pong, tới on_message đúng thứ tự nhận."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received, dead_after=5.0)
    try:
        sent = [Ping(t=1), Pong(t=2), Ping(t=3), Pong(t=4), Pong(t=5)]
        for m in sent:
            peer.send_dict(to_dict(m))
        await peer.drain()
        await wait_until(lambda: len(received) >= len(sent), 2.0, "on_message nhận đủ")
        assert received == sent
    finally:
        await cancel_wait(task)


@pytest.mark.integration
async def test_ping_reply_is_scheduled_before_on_message_and_flushed_on_close(
    fast, listener_factory, raw_client, ids
):
    """PR-1 D3 (thay cho “Pong đã gửi xong trước on_message”): Pong được *xếp lịch* trước on_message.

    on_message raise ngay khi nhận Ping: kênh đóng, nhưng Pong đã xếp lịch và kết nối còn tốt,
    nên lúc dọn Pong phải được gửi nốt trước khi đóng (tối đa CLOSE_TIMEOUT).
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)

    def explode(msg):
        raise Boom(msg)

    task = asyncio.create_task(ControlChannel(server, ping_interval=5.0, dead_after=10.0).run(explode))
    peer.send_dict({"type": "ping", "t": 31})
    await peer.drain()
    with pytest.raises(Boom):
        await asyncio.wait_for(task, 3)
    _, data = await peer.expect_closed(2.0)
    msgs = []
    while data:
        (n,) = HEADER.unpack(data[:4])
        msgs.append(decode_body(data[4 : 4 + n]))
        data = data[4 + n :]
    assert {"type": "pong", "t": 31} in msgs


# =================================================================================================
# Sửa sau review vòng 1 (F1, F3, F4, F5): hủy giữa chừng, lần thử thua, lý do đóng
# =================================================================================================


def frames_in(data: bytes) -> list[dict]:
    """Các khung trọn vẹn trong `data` (phần cuối dở dang bị bỏ qua)."""
    out: list[dict] = []
    while len(data) >= HEADER.size:
        (n,) = HEADER.unpack(data[: HEADER.size])
        if len(data) < HEADER.size + n:
            break
        out.append(decode_body(data[HEADER.size : HEADER.size + n]))
        data = data[HEADER.size + n :]
    return out


def types_in(data: bytes) -> list[str]:
    return [f.get("type") for f in frames_in(bytes(data))]


async def control_pair(side: str, h, ids, raw_client):
    """Kết nối điều khiển phía `side` (client: open_control; server: Listener giao) và hàm
    `other_side_sees_close()` khẳng định máy kia thấy kết nối bị đóng.

    Trước lúc đóng máy kia chỉ được thấy `ping` keepalive: máy bận (GC thế hệ 2 khi chạy cả bộ,
    thiếu CPU) làm vòng lặp dừng lâu hơn PI ngay trước lần hủy, nên `run` gửi `ping` một cách
    hợp lệ trước khi bị hủy. Mọi message khác, hoặc kết nối không đóng trong 2 s, đều là lỗi.
    """
    if side == "server":
        peer, conn = await raw_control(raw_client, h, ids)

        async def other_side_sees_close() -> None:
            _, data = await peer.expect_closed(2.0)
            assert set(types_in(data)) <= {"ping"}, f"còn nhận được message: {frames_in(data)!r}"

        return conn, other_side_sees_close

    conn = await b_control(h, ids)
    server = await h.next()

    async def other_side_sees_close() -> None:
        async with asyncio.timeout(2.0):
            while True:
                try:
                    msg = await server.receive()
                except ConnectionLostError:
                    return
                if msg is None:
                    return
                assert isinstance(msg, Ping), f"còn nhận được message: {msg!r}"

    return conn, other_side_sees_close


def new_live_tasks(before: set[asyncio.Task]) -> list[str]:
    current = asyncio.current_task()
    return [
        t.get_name() for t in asyncio.all_tasks() if t is not current and t not in before and not t.done()
    ]


# --- F1: run bị hủy lần hai trong lúc dọn --------------------------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("yields", [1, 2, 3, 5])
@pytest.mark.parametrize("side", ["client", "server"])
async def test_cancelling_run_twice_still_closes_connection(
    fast, monkeypatch, listener_factory, raw_client, ids, side, yields
):
    """F1 / mục 3.4 bước 5: hủy `run`, rồi hủy lần nữa khi nó đang dọn → kết nối vẫn đóng.

    Móc keepalive phải được gỡ, máy kia thấy EOF/reset, không task nào sống lâu hơn `run`,
    và gửi tiếp qua kết nối chỉ ra ConnectionLostError.
    """
    # Test này không kiểm hạn mở kết nối: 0,5 s của `fast` hụt khi GC dừng vòng lặp lúc dựng kết nối.
    monkeypatch.setattr(connection, "OPENING_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn, other_side_sees_close = await control_pair(side, h, ids, raw_client)
    before = asyncio.all_tasks()
    _, task = start_channel(conn, [], dead_after=5.0)
    await asyncio.sleep(0.1)
    assert not task.done()

    task.cancel()
    for _ in range(yields):
        await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 3)

    assert conn.closed, "run bị hủy hai lần mà kết nối chưa đóng"
    # White-box: móc keepalive đã gỡ (không còn gọi vào Keepalive của một run đã chết).
    assert conn._on_sent is None
    assert conn._on_received is None
    with pytest.raises(ConnectionLostError):
        await conn.send(Ping(t=1))
    await other_side_sees_close()
    await wait_until(lambda: not new_live_tasks(before), 0.5, "task của run đã kết thúc")


@pytest.mark.integration
async def test_cancelling_run_again_while_it_closes_aborts_at_once(fast, monkeypatch, listener_factory, ids):
    """F1: lần hủy thứ hai rơi vào lúc `run` đang đóng gọn (máy kia không bao giờ trả close_notify).

    CLOSE_TIMEOUT = 5 s, nên `run` chỉ kết thúc nhanh nếu lần hủy thứ hai abort transport ngay.
    """
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    try:
        server = await h.next()
        raw = server._writer.get_extra_info("socket")
        _, task = start_channel(server, [], ping_interval=5.0, dead_after=10.0)
        await asyncio.sleep(0.1)
        task.cancel()
        await asyncio.sleep(0.2)
        start = time.monotonic()
        if not task.done():  # đang chờ close_notify: hủy lần hai
            task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 3)
        assert time.monotonic() - start < 1.0
        assert server.closed
        assert server._on_sent is None and server._on_received is None
        await wait_until(lambda: raw.fileno() == -1, 1.0, "socket phía server đã bị abort")
    finally:
        sock.close()


# --- F3: receive bị hủy sau khi đã đọc một phần khung ---------------------------------------------


def _valid_inbound(kind: str) -> tuple[dict, object]:
    """Một message hợp lệ client gửi được tới server trên loại kết nối `kind` (dict trên dây, message)."""
    if kind == "pairing":
        return {"type": "pair_abort", "reason": "user"}, PairAbort(reason="user")
    return {"type": "ping", "t": 5}, Ping(t=5)


async def _server_conn(kind: str, h, ids, raw_client):
    if kind == "pairing":
        return await raw_pairing(raw_client, h, ids)
    return await raw_control(raw_client, h, ids)


@pytest.mark.integration
@pytest.mark.parametrize("cut", ["header-2-bytes", "header-and-5-body-bytes"])
@pytest.mark.parametrize("kind", ["pairing", "control"])
async def test_receive_cancelled_mid_frame_aborts_connection(
    fast, listener_factory, raw_client, ids, kind, cut
):
    """F3: hết giờ của bên gọi khi đã đọc một phần khung → kết nối bị abort, không đọc lệch khung."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await _server_conn(kind, h, ids, raw_client)
    wire, _ = _valid_inbound(kind)
    data = encode_message(wire)
    n = 2 if cut == "header-2-bytes" else HEADER.size + 5
    peer.send_bytes(data[:n])
    await peer.drain()

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(server.receive(), 0.3)
    assert server.closed, "receive bị hủy giữa khung mà kết nối vẫn mở (lần đọc sau sẽ lệch khung)"

    # Phần còn lại tới muộn, kèm một khung trọn: không được đọc thành message nào.
    peer.send_bytes(data[n:] + data)
    await peer.drain()
    with pytest.raises(ConnectionLostError):
        await asyncio.wait_for(server.receive(), 2)
    await peer.expect_closed(2.0)


@pytest.mark.integration
@pytest.mark.parametrize("kind", ["pairing", "control"])
async def test_receive_cancelled_before_any_byte_keeps_connection(
    fast, listener_factory, raw_client, ids, kind
):
    """F3, ca đối chứng: hết giờ khi chưa có byte nào của khung → kết nối vẫn dùng được."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await _server_conn(kind, h, ids, raw_client)
    wire, expected = _valid_inbound(kind)

    for _ in range(2):
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(server.receive(), 0.2)
    assert not server.closed
    peer.send_dict(wire)
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 2) == expected
    assert not server.closed


# --- F4: send bị hủy -----------------------------------------------------------------------------


class DrainGate:
    """Giữ `StreamWriter.drain` (vá ở mức lớp) từ lần gọi thứ `block_from` khi `armed`.

    Dùng để dựng một lần gửi đang dở một cách tất định. Chỉ bật trong lúc kết nối dưới thử gửi:
    client thô cũng dùng `StreamWriter.drain`.
    """

    def __init__(self, monkeypatch, block_from: int) -> None:
        self.armed = False
        self.calls = 0
        self.block_from = block_from
        self.blocked = asyncio.Event()
        self.opened = asyncio.Event()
        original = asyncio.StreamWriter.drain
        gate = self

        async def drain(writer):
            if gate.armed:
                gate.calls += 1
                if gate.calls >= gate.block_from and not gate.opened.is_set():
                    gate.blocked.set()
                    await gate.opened.wait()
            await original(writer)

        monkeypatch.setattr(asyncio.StreamWriter, "drain", drain)

    def open(self) -> None:
        self.armed = False
        self.opened.set()


@pytest.mark.integration
async def test_send_cancelled_while_waiting_for_lock_keeps_connection(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """F4: lần gửi bị hủy khi đang chờ lock, hoặc trước khi chạy → không ghi gì, kết nối vẫn dùng được."""
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    gate = DrainGate(monkeypatch, block_from=1)

    gate.armed = True
    first = asyncio.create_task(server.send(Ping(t=1)))
    await asyncio.wait_for(gate.blocked.wait(), 2)  # lần gửi đầu giữ lock, kẹt ở drain
    waiting = asyncio.create_task(server.send(Ping(t=2)))
    await asyncio.sleep(0.05)
    assert not waiting.done()
    never_started = asyncio.create_task(server.send(Ping(t=3)))
    waiting.cancel()
    never_started.cancel()
    for t in (waiting, never_started):
        with pytest.raises(asyncio.CancelledError):
            await t

    gate.open()
    await asyncio.wait_for(first, 2)
    assert not server.closed
    await server.send(Ping(t=4))
    got = [await peer.read(), await peer.read()]
    assert got == [{"type": "ping", "t": 1}, {"type": "ping", "t": 4}]
    assert not server.closed


@pytest.mark.integration
async def test_send_cancelled_between_chunks_aborts_connection(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """F4: hủy sau khi đã ghi một phần khung → kết nối bị abort; lần gửi sau → ConnectionLostError.

    Message hợp lệ nào hiện cũng < 64 KiB, nên `_SEND_CHUNK` (đọc lúc dùng, mục 2.3) được hạ xuống
    8 byte để một `ping` thành nhiều đoạn; drain của đoạn thứ hai bị giữ rồi hủy.
    """
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    full = encode_message(to_dict(Ping(t=1)))
    assert len(full) > 2 * 8
    monkeypatch.setattr(connection, "_SEND_CHUNK", 8)
    gate = DrainGate(monkeypatch, block_from=2)

    gate.armed = True
    task = asyncio.create_task(server.send(Ping(t=1)))
    await asyncio.wait_for(gate.blocked.wait(), 2)  # đã ghi 2 đoạn đầu, khung còn dở
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    gate.open()

    assert server.closed, "send bị hủy giữa khung mà kết nối vẫn mở (máy kia sẽ đọc lệch khung)"
    with pytest.raises(ConnectionLostError):
        await server.send(Ping(t=2))
    _, data = await peer.expect_closed(2.0)
    assert len(data) < len(full) and full.startswith(data), "máy kia nhận được nhiều hơn một phần khung"


# --- F5: chỉ kết nối thắng nhận control_open -------------------------------------------------------

OTHER_ADDRESS = "198.51.100.7"  # TEST-NET-2: được chuyển hướng về server giả thứ hai trên 127.0.0.1


async def _hello_then_record(server, reader, writer):
    writer.write(encode_message(wire_hello(server.identity, "Server")))
    await writer.drain()
    await server.record_until_closed(reader)


@pytest.mark.integration
async def test_losing_attempt_never_sends_control_open(slow_opening, monkeypatch, fake_server, ids):
    """F5: hai địa chỉ cùng trao xong `hello` trong một vòng lặp → chỉ kết nối thắng nhận `control_open`.

    Hai server giả cùng danh tính (đúng fingerprint). `asyncio.open_connection` được bọc để
    (1) chuyển địa chỉ thứ hai về server giả thứ hai và (2) trả về cho cả hai lần thử cùng lúc,
    khi `hello` của cả hai server đã nằm sẵn trong bộ đệm: hai lần thử xong `hello` liền nhau.
    """
    s1 = await fake_server(ids.server, _hello_then_record, trusted_certs=[ids.b.cert_pem()])
    s2 = await fake_server(ids.server, _hello_then_record, trusted_certs=[ids.b.cert_pem()])
    real_open = asyncio.open_connection
    opened: list = []
    both_ready = asyncio.Event()

    async def open_connection(host=None, port=None, **kwargs):
        if host == OTHER_ADDRESS:
            host, port = LOCAL, s2.port
        streams = await real_open(host, port, **kwargs)
        opened.append(streams)
        if len(opened) == 2:
            await asyncio.sleep(0.3)  # hello của cả hai server đã tới bộ đệm
            both_ready.set()
        else:
            await both_ready.wait()
        return streams

    monkeypatch.setattr(asyncio, "open_connection", open_connection)
    conn = await open_control([LOCAL, OTHER_ADDRESS], s1.port, ids.b, hello_of(ids.b), ids.server.cert_pem())
    try:
        assert len(opened) == 2, "phép thử vô nghĩa: không có hai lần thử song song"
        winner, loser = (s1, s2) if conn.peer.address == LOCAL else (s2, s1)
        await wait_until(lambda: not loser._tasks, 3.0, "lần thử thua bị đóng")
        await wait_until(lambda: len(types_in(winner.received)) >= 2, 2.0, "kết nối thắng nhận control_open")
        assert types_in(winner.received) == ["hello", "control_open"]
        assert "control_open" not in types_in(loser.received), "lần thử thua đã gửi control_open"
    finally:
        await conn.close()


@pytest.mark.integration
async def test_error_sending_control_open_is_unreachable(slow_opening, monkeypatch, fake_server, ids):
    """F5 (quyết định đã duyệt): OSError khi gửi `control_open` trên kết nối thắng → abort, Unreachable."""
    server = await fake_server(ids.server, _hello_then_record, trusted_certs=[ids.b.cert_pem()])
    real_write = asyncio.StreamWriter.write
    real_drain = asyncio.StreamWriter.drain
    failing: set[int] = set()

    def write(writer, data):
        if b'"control_open"' in bytes(data):
            failing.add(id(writer))  # giả lập: socket hỏng đúng lúc gửi control_open
            return None
        return real_write(writer, data)

    async def drain(writer):
        if id(writer) in failing:
            raise ConnectionResetError("giả lập lỗi gửi control_open")
        await real_drain(writer)

    monkeypatch.setattr(asyncio.StreamWriter, "write", write)
    monkeypatch.setattr(asyncio.StreamWriter, "drain", drain)
    with pytest.raises(Unreachable) as exc:
        await open_control([LOCAL], server.port, ids.b, hello_of(ids.b), ids.server.cert_pem())
    assert exc.value.address == LOCAL
    assert failing, "phép thử vô nghĩa: control_open chưa từng được gửi"
    await wait_until(lambda: not server._tasks, 3.0, "server giả thấy kết nối bị đóng")
    assert "control_open" not in types_in(server.received)


# --- CloseReason.CONNECTION_LOST -----------------------------------------------------------------


def _close_with_rst(sock: socket.socket) -> None:
    """Đóng socket bằng RST (SO_LINGER = 0) thay cho FIN: phía kia thấy lỗi socket, không phải EOF.

    Dùng socket đồng bộ: `transport.abort()` của asyncio gọi `shutdown()` trước khi đóng (Proactor),
    nên phía kia chỉ thấy EOF.
    """
    linger = struct.pack("HH", 1, 0) if sys.platform == "win32" else struct.pack("ii", 1, 0)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
    sock.close()


@pytest.mark.integration
async def test_peer_reset_during_run_is_connection_lost(fast, listener_factory, ids):
    """Mục 3.4: kết nối bị reset (lỗi socket) trong lúc `run` chạy → CONNECTION_LOST, không PEER_CLOSED."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    try:
        server = await h.next()
        _, task = start_channel(server, [], dead_after=5.0)
        await asyncio.sleep(0.1)
        assert not task.done()
        _close_with_rst(sock)
        assert await asyncio.wait_for(task, 3) is CloseReason.CONNECTION_LOST
        assert server.closed
    finally:
        sock.close()


# --- Connection.close() bị hủy giữa chừng ----------------------------------------------------------


@pytest.mark.integration
async def test_cancelled_close_aborts_transport(fast, monkeypatch, listener_factory, ids):
    """Mục 2.3 `close()`: bị hủy khi đang chờ close_notify → abort transport rồi CancelledError bay ra.

    Máy kia không bao giờ đọc (không trả close_notify) và CLOSE_TIMEOUT = 5 s, nên close() đang
    treo ở bước chờ khi bị hủy. Sau đó socket đã đóng thật, và close() lần sau trả về ngay.
    """
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    try:
        server = await h.next()
        raw = server._writer.get_extra_info("socket")
        task = asyncio.create_task(server.close())
        await asyncio.sleep(0.2)
        assert not task.done(), "close() phải đang chờ close_notify (máy kia không đọc)"
        start = time.monotonic()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert time.monotonic() - start < 1.0
        assert server.closed
        await wait_until(lambda: raw.fileno() == -1, 1.0, "socket phía server đã bị abort")
        await asyncio.wait_for(server.close(), 1.0)
        with pytest.raises(ConnectionLostError):
            await server.send(Ping(t=1))
    finally:
        sock.close()


# --- Listener.start() bị hủy hoặc bị close() chen ngang ở từng nhịp (sửa G1, review PR-4 vòng 2) ----
#
# Hợp đồng kiểm ở đây:
# - `start()` raise (CancelledError khi bị hủy, RuntimeError khi close() chen ngang) thì cổng đã
#   đóng ngay lúc đó, KHÔNG cần ai gọi `close()` (bên gọi như `Node.start` nhả `node.lock` ngay sau).
# - `start()` bị hủy vẫn gọi lại được (như mọi lần `start()` thất bại, PR-2); `close()` đóng được.
# - `close()` trả về thì cổng đã đóng, kể cả khi `start()` đang chạy dở.
# Cổng “đã đóng” đo bằng cách bind lại đúng cổng đó (không SO_REUSEADDR): nhanh, không phụ thuộc
# việc Windows mất ~2 s mới báo kết nối bị từ chối.

_SWEEP_TICKS = 12  # đủ phủ toàn bộ start() (thực tế chỉ vài nhịp); nhịp cuối phải là start() đã xong


def _port_is_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCAL, port))
    except OSError:
        return False
    else:
        return True
    finally:
        s.close()


@pytest.fixture
async def server_tracker(monkeypatch):
    """Ghi mọi `asyncio.Server` tạo trong test (kể cả server bị rò khi hủy) để dọn khi test xong.

    Chỉ dùng để dọn và in chẩn đoán, không để khẳng định: `loop.create_server` được bọc bằng phiên
    bản tương đương (bind với start_serving=False, ghi lại, rồi `start_serving()` nếu bên gọi muốn).
    """
    loop = asyncio.get_running_loop()
    real = loop.create_server
    servers: list[asyncio.Server] = []

    async def create_server(*args, **kwargs):
        serving = kwargs.pop("start_serving", True)
        server = await real(*args, start_serving=False, **kwargs)
        servers.append(server)
        if serving:
            await server.start_serving()
        return server

    monkeypatch.setattr(loop, "create_server", create_server)
    yield servers
    for server in servers:
        server.close()
    for server in servers:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(server.wait_closed(), 2)


def _serving(servers) -> list[str]:
    return [repr(s) for s in servers if s.is_serving()]


@pytest.mark.integration
async def test_start_cancelled_at_any_tick_leaves_no_listening_port(
    fast, listener_factory, server_tracker, ids
):
    outcomes: list[str] = []
    for k in range(_SWEEP_TICKS):
        h = await listener_factory(ids.server, start=False)
        port = free_port()
        task = asyncio.create_task(h.listener.start(LOCAL, port), name="test.listener-start")
        for _ in range(k):
            await asyncio.sleep(0)
        if task.done():
            outcomes.append("done")
            assert task.result() == port
            assert not _port_is_free(port), f"k={k}: start() xong mà cổng chưa nghe"
            await h.listener.close()
            assert _port_is_free(port), f"k={k}: close() xong mà cổng còn nghe"
            continue
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        outcomes.append("cancelled")
        assert _port_is_free(port), (
            f"k={k}: start() đã raise CancelledError mà cổng {port} vẫn bị giữ "
            f"(server rò, close() không đóng được): {_serving(server_tracker)}"
        )
        # start() bị hủy là một lần start() thất bại: gọi lại được, rồi close() đóng được.
        again = await asyncio.wait_for(h.listener.start(LOCAL, port), 2)
        assert again == port
        await h.listener.close()
        assert _port_is_free(port), f"k={k}: close() sau lần start() thứ hai mà cổng còn nghe"
    assert "cancelled" in outcomes, outcomes
    assert outcomes[-1] == "done", f"{_SWEEP_TICKS} nhịp chưa phủ hết start(): {outcomes}"
    assert _serving(server_tracker) == []


@pytest.mark.integration
async def test_close_during_start_at_any_tick_closes_port(fast, listener_factory, server_tracker, ids):
    outcomes: list[str] = []
    for k in range(_SWEEP_TICKS):
        h = await listener_factory(ids.server, start=False)
        port = free_port()
        task = asyncio.create_task(h.listener.start(LOCAL, port), name="test.listener-start")
        for _ in range(k):
            await asyncio.sleep(0)
        started = task.done()
        await asyncio.wait_for(h.listener.close(), 3)
        assert _port_is_free(port), (
            f"k={k}: close() đã trả về mà cổng {port} vẫn nghe: {_serving(server_tracker)}"
        )
        try:
            got = await asyncio.wait_for(task, 2)
        except RuntimeError:
            outcomes.append("refused")
        else:
            assert started, f"k={k}: start() trả về {got} dù close() đã chạy trước khi nó xong"
            outcomes.append("done")
        assert _port_is_free(port), f"k={k}: start() kết thúc mà cổng {port} vẫn nghe"
        with pytest.raises(RuntimeError):
            await h.listener.start(LOCAL, 0)  # sau close(): không start lại được
    assert "refused" in outcomes, outcomes
    assert outcomes[-1] == "done", f"{_SWEEP_TICKS} nhịp chưa phủ hết start(): {outcomes}"
    assert _serving(server_tracker) == []


# =================================================================================================
# PR-1: trần khung điều khiển 1 MiB (D1) và `pong` không chặn vòng đọc (D3)
# =================================================================================================
#
# Con số lấy từ đặc tả, không từ hằng số của code: kết nối điều khiển 1 MiB (1024 × 1024 byte),
# `hello` / message mở đầu / kết nối ghép đôi 16 KiB (protocol mục 2.3).

ONE_MIB = 1024 * 1024
SIXTEEN_KIB = 16 * 1024


def raw_frame(obj: dict) -> bytes:
    """Khung `[uint32][JSON]` dựng tay, không qua `encode_message` (để dựng được khung vượt trần)."""
    return frame(json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode())


def padded(obj: dict, body_size: int) -> dict:
    """`obj` thêm trường lạ `pad` sao cho thân JSON dài đúng `body_size` byte (trường lạ bị bỏ qua)."""
    overhead = len(raw_frame({**obj, "pad": ""})) - HEADER.size
    out = {**obj, "pad": "x" * (body_size - overhead)}
    assert len(raw_frame(out)) - HEADER.size == body_size
    return out


@pytest.mark.integration
async def test_control_receive_accepts_frame_of_exactly_one_mib(fast, listener_factory, raw_client, ids):
    """D1: kết nối điều khiển nhận khung có thân đúng 1 MiB."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    peer.send_bytes(raw_frame(padded({"type": "ping", "t": 21}, ONE_MIB)))
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 5) == Ping(t=21)
    assert not server.closed


@pytest.mark.integration
@pytest.mark.parametrize("length", [ONE_MIB + 1, 16 * ONE_MIB, 0xFFFFFFFF], ids=["1MiB+1", "16MiB", "4GiB-1"])
async def test_control_receive_rejects_oversized_header_without_reading_body(
    fast, listener_factory, raw_client, ids, length
):
    """D1: header > 1 MiB (kể cả 16 MiB, trần cũ) → FramingError ngay khi đọc header.

    Chỉ có header + vài byte thân, kết nối vẫn mở: nếu bên nhận chờ đọc thân thì `receive` treo.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    peer.send_bytes(HEADER.pack(length) + b'{"type":"pi')
    await peer.drain()
    with pytest.raises(FramingError):
        await asyncio.wait_for(server.receive(), 1.0)


@pytest.mark.integration
async def test_client_side_control_receive_rejects_header_over_one_mib(slow_opening, fake_server, ids):
    """D1, chiều ngược lại: phía client (`open_control`) cũng cắt khung > 1 MiB ở header."""
    data = encode_message(wire_hello(ids.server, "Server")) + HEADER.pack(ONE_MIB + 1) + b"xxxxxxxx"
    server = await fake_server(ids.server, send_then_hold(data), trusted_certs=[ids.b.cert_pem()])
    conn = await open_control([LOCAL], server.port, ids.b, hello_of(ids.b), ids.server.cert_pem())
    try:
        with pytest.raises(FramingError):
            await asyncio.wait_for(conn.receive(), 1.0)
    finally:
        await conn.close()


@pytest.mark.integration
async def test_channel_closes_on_header_over_one_mib_without_waiting_for_body(
    fast, listener_factory, raw_client, ids
):
    """D1: trong `ControlChannel`, header 1 MiB + 1 → PROTOCOL_ERROR ngay và kết nối bị đóng."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], ping_interval=5.0, dead_after=10.0)
    try:
        peer.send_bytes(HEADER.pack(ONE_MIB + 1) + b"x" * 16)
        await peer.drain()
        assert await asyncio.wait_for(task, 1.5) is CloseReason.PROTOCOL_ERROR
        assert server.closed
        await peer.expect_closed(2.0)
    finally:
        await cancel_wait(task)


@pytest.mark.integration
async def test_pairing_receive_still_accepts_exactly_16_kib(fast, listener_factory, raw_client, ids):
    """D1: kết nối ghép đôi giữ trần 16 KiB: đúng 16 KiB nhận được (16 KiB + 1 ở test A2 ở trên)."""
    h = await listener_factory(ids.server)
    peer, server = await raw_pairing(raw_client, h, ids)
    peer.send_bytes(raw_frame(padded({"type": "pair_abort", "reason": "user"}, SIXTEEN_KIB)))
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 2) == PairAbort(reason="user")


@pytest.mark.integration
async def test_hello_and_control_open_of_exactly_16_kib_are_accepted(
    slow_opening, listener_factory, raw_client, ids
):
    """D1: trần 16 KiB của `hello` / message mở đầu là bao gồm (16 KiB + 1 bị từ chối ở R11)."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer = await raw_client(h.port, ids.b)
    await peer.read_hello()
    peer.send_bytes(raw_frame(padded(wire_hello(ids.b), SIXTEEN_KIB)))
    peer.send_bytes(raw_frame(padded({"type": "control_open"}, SIXTEEN_KIB)))
    await peer.drain()
    server = await h.next(3.0)
    assert server.kind is ConnectionKind.CONTROL


@pytest.mark.integration
async def test_control_receive_hands_read_buffer_to_decoder_without_copy(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """D1: đường đọc không chép thân sang `bytes` trước khi giải mã: decoder nhận `bytearray`.

    Thân 200 KB để phải ghép từ nhiều lần đọc. Patch sau khi mở đầu xong, nên chỉ ghi thân của
    message đọc qua `Connection.receive`.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    real = connection.decode_body
    seen: list[type] = []

    def spy(body):
        seen.append(type(body))
        return real(body)

    monkeypatch.setattr(connection, "decode_body", spy)
    peer.send_bytes(raw_frame(padded({"type": "ping", "t": 3}, 200_000)))
    await peer.drain()
    assert await asyncio.wait_for(server.receive(), 3) == Ping(t=3)
    assert seen, "Connection.receive không còn gọi decode_body: không kiểm được đường đọc"
    assert seen == [bytearray], f"decoder nhận {seen}: thân đã bị chép sang bytes"


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        b"\xff\xfe\xfd\xfc\xfb",
        b'{"type":"ping","t":1,"x":"\xc3"}',
        b"[1,2,3]",
        b'"ping"',
        b'{"type":"ping","t":1,"a":' + b"[" * 64 + b"]" * 64 + b"}",
        b'{"type":"ping","t":' + b"1" * 5000 + b"}",
        b'\xef\xbb\xbf{"type":"ping","t":1}',
        b'{"type":"ping","t":1,"a":"\xed\xa0\x80"}',
        '{"type":"ping","t":1}'.encode("utf-16"),
    ],
    ids=[
        "rac",
        "utf8-dang-do",
        "mang",
        "chuoi",
        "long-65-cap",
        "so-5000-chu-so",
        "bom-utf8",
        "surrogate",
        "utf16",
    ],
)
async def test_control_receive_keeps_body_checks_on_bytearray_path(
    fast, listener_factory, raw_client, ids, body
):
    """D1: bỏ bản chép `bytes(buf)` mà vẫn giữ mọi kiểm tra thân (UTF-8, object, độ sâu, số quá dài)."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    peer.send_bytes(frame(body))
    await peer.drain()
    with pytest.raises(FramingError):
        await asyncio.wait_for(server.receive(), 2)


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [b'\xef\xbb\xbf{"type":"ping","t":1}', b'{"type":"ping","t":1,"a":"\xed\xa0\x80"}'],
    ids=["bom-utf8", "surrogate-byte"],
)
async def test_channel_closes_with_protocol_error_on_body_not_strict_utf8(
    fast, listener_factory, raw_client, ids, body
):
    """protocol §3.1: thân có BOM UTF-8 hay surrogate mã hóa thành byte là lỗi khung → PROTOCOL_ERROR.

    Ping hợp lệ đi trước để chắc kênh đang chạy bình thường; message xấu không được tới on_message.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received, ping_interval=5.0, dead_after=10.0)
    try:
        peer.send_dict({"type": "ping", "t": 2})
        peer.send_bytes(frame(body))
        await peer.drain()
        assert await asyncio.wait_for(task, 3) is CloseReason.PROTOCOL_ERROR
        assert received == [Ping(t=2)]
        assert server.closed
    finally:
        await cancel_wait(task)


# --- D3: `pong` ở task riêng ---------------------------------------------------------------------


async def hold_send_lock(server, gate: DrainGate) -> asyncio.Task:
    """Một lần gửi của app (`Ping(t=1)`) kẹt ở drain, giữ khóa gửi tới khi `gate.open()`.

    Gỡ cò ngay sau khi kẹt, để drain của client thô và các lần gửi sau không bị giữ nữa (chúng vẫn
    phải chờ khóa gửi).
    """
    gate.armed = True
    task = asyncio.create_task(server.send(Ping(t=1)))
    await asyncio.wait_for(gate.blocked.wait(), 2)
    gate.armed = False
    return task


async def pong_ts_until(peer, last_t: int, timeout: float = 3.0) -> list[int]:
    """`t` của mọi `pong` máy kia nhận, theo thứ tự, tới và gồm `pong` có `t == last_t`."""
    out: list[int] = []
    async with asyncio.timeout(timeout):
        while not out or out[-1] != last_t:
            msg = await peer.read(timeout=timeout)
            assert msg is not None, f"kết nối đóng trước pong t={last_t}; đã nhận {out}"
            if msg["type"] == "pong":
                out.append(msg["t"])
    return out


@pytest.mark.integration
async def test_reader_keeps_delivering_while_send_lock_is_held(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """D3: một lần gửi đang giữ khóa gửi không chặn vòng đọc.

    Ping tới trong lúc đó: message đến sau nó vẫn tới on_message dù pong còn chờ khóa; khi khóa
    được nhả, pong mang đúng `t` đi ra sau lần gửi đang dở.
    """
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received, ping_interval=5.0, dead_after=10.0)
    gate = DrainGate(monkeypatch, block_from=1)
    app_send = await hold_send_lock(server, gate)
    try:
        peer.send_bytes(encode_message({"type": "ping", "t": 7}) + encode_message({"type": "pong", "t": 8}))
        await wait_until(lambda: len(received) >= 2, 2.0, "on_message nhận message tới sau Ping")
        assert received == [Ping(t=7), Pong(t=8)]
        assert not app_send.done(), "phép thử vô nghĩa: khóa gửi đã được nhả"
        assert not task.done()

        gate.open()
        await asyncio.wait_for(app_send, 2)
        assert await peer.read() == {"type": "ping", "t": 1}
        assert await pong_ts_until(peer, 7) == [7]
    finally:
        gate.open()
        await cancel_wait(task, app_send)


@pytest.mark.slow
@pytest.mark.integration
async def test_reader_keeps_delivering_under_real_backpressure(fast, monkeypatch, listener_factory, ids):
    """D3 trên socket thật: máy kia không đọc nên lần gửi của app kẹt ở drain (không vá drain).

    Trong lúc đó máy kia vẫn gửi `ping` + `pong`: cả hai phải tới on_message.

    Bộ đệm được giữ nhỏ ở cả hai đầu (SO_RCVBUF của máy kia đặt trước khi kết nối, SO_SNDBUF của
    socket phía server) để Linux/macOS không tự giãn bộ đệm: lượng byte cần để làm đầy có cận rõ
    (`FILL_LIMIT`), và việc làm đầy có hạn thời gian. “Kẹt” nghĩa là 0,5 s liền không lần gửi nào xong,
    rồi thêm `STUCK_CONFIRM` giây nữa vẫn không lần nào xong: máy CI chậm (Windows) có lúc chỉ trễ
    hơn 0,5 s chứ chưa kẹt, khi đó lần gửi “kẹt” xong muộn và phép thử thành vô nghĩa.
    """
    FILL_LIMIT = 8 * 1024 * 1024  # bộ đệm nhỏ + mức cao 64 KiB của asyncio: thực tế chỉ vài trăm KiB
    STUCK_CONFIRM = 2.0
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b, rcvbuf=4096)
    stuck: asyncio.Task | None = None
    task = None
    inflight: dict[asyncio.Task, int] = {}
    try:
        server = await h.next()
        server._writer.get_extra_info("socket").setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
        received: list = []
        _, task = start_channel(server, received, ping_interval=5.0, dead_after=10.0)
        frame_size = len(encode_message(to_dict(Ping(t=1))))
        created = completed = 0
        async with asyncio.timeout(20):
            while stuck is None:
                while len(inflight) < 256:
                    inflight[asyncio.create_task(server.send(Ping(t=1)))] = created
                    created += 1
                done, _ = await asyncio.wait(inflight, timeout=0.5)
                if not done:
                    done, _ = await asyncio.wait(inflight, timeout=STUCK_CONFIRM)
                for t in done:
                    del inflight[t]
                    t.result()
                completed += len(done)
                assert completed * frame_size <= FILL_LIMIT, "đã gửi quá FILL_LIMIT mà chưa kẹt"
                if not done:
                    # Khóa gửi FIFO: lần gửi tạo sớm nhất đang giữ khóa (đã ghi xuống transport); các
                    # lần khác chỉ đang chờ khóa nên hủy được mà kết nối không sao (F4).
                    stuck = min(inflight, key=inflight.__getitem__)
                    del inflight[stuck]
                    await cancel_wait(*inflight)
                    inflight.clear()
        assert not server.closed
        await asyncio.to_thread(
            sock.sendall, encode_message({"type": "ping", "t": 7}) + encode_message({"type": "pong", "t": 8})
        )
        await wait_until(lambda: Pong(t=8) in received, 3.0, "on_message nhận message tới sau Ping")
        assert [m for m in received if m in (Ping(t=7), Pong(t=8))] == [Ping(t=7), Pong(t=8)]
        assert not stuck.done(), "phép thử vô nghĩa: lần gửi kẹt đã xong"
        assert not task.done()
    finally:
        await cancel_wait(*inflight, *(t for t in (task, stuck) if t is not None))
        sock.close()


@pytest.mark.slow
@pytest.mark.integration
@pytest.mark.parametrize("arrival", ["mot-lan-ghi", "tung-cai"])
@pytest.mark.parametrize("n", [2, 50])
async def test_queued_pings_are_answered_by_one_pong_with_latest_t(
    fast, monkeypatch, listener_factory, raw_client, ids, n, arrival
):
    """D3: `ping` dồn khi pong chưa gửi được → đúng một pong, mang `t` của ping mới nhất.

    `mot-lan-ghi`: mọi ping tới trong một lần ghi. `tung-cai`: ping tới lần lượt, mỗi cái sau khi
    on_message đã nhận cái trước và vòng lặp đã được nhường, nên bên gửi pong đã kịp thấy ping đầu
    và đang chờ khóa gửi khi các ping sau tới; pong vẫn phải mang `t` mới nhất lúc được gửi.
    Sau đó một ping mốc (t = 999) chứng minh không còn pong nào khác đang chờ: mọi pong của đợt
    dồn phải tới trước pong mốc.
    """
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    received: list = []
    _, task = start_channel(server, received, ping_interval=5.0, dead_after=10.0)
    gate = DrainGate(monkeypatch, block_from=1)
    app_send = await hold_send_lock(server, gate)
    try:
        ts = [100 + i for i in range(1, n + 1)]
        if arrival == "mot-lan-ghi":
            peer.send_bytes(b"".join(encode_message({"type": "ping", "t": t}) for t in ts))
        else:
            for i, t in enumerate(ts, 1):
                peer.send_dict({"type": "ping", "t": t})
                await peer.drain()
                await wait_until(lambda i=i: len(received) >= i, 2.0, f"on_message nhận Ping thứ {i}")
                for _ in range(5):
                    await asyncio.sleep(0)  # nhường vòng lặp: bên gửi pong chạy tới chỗ chờ khóa
        await wait_until(lambda: len(received) >= n, 2.0, "on_message nhận đủ các Ping dồn")
        assert received == [Ping(t=t) for t in ts]
        assert not app_send.done(), "phép thử vô nghĩa: khóa gửi đã được nhả"

        gate.open()
        await asyncio.wait_for(app_send, 2)
        first = await pong_ts_until(peer, ts[-1])
        peer.send_dict({"type": "ping", "t": 999})
        await peer.drain()
        rest = await pong_ts_until(peer, 999)
        assert first + rest == [ts[-1], 999], f"pong nhận được: {first + rest}"
    finally:
        gate.open()
        await cancel_wait(task, app_send)


def fail_pongs_on(monkeypatch, conn) -> list[bytes]:
    """Làm mọi lần gửi `pong` trên `conn` thất bại như socket hỏng (drain → ConnectionResetError)."""
    real_write = asyncio.StreamWriter.write
    real_drain = asyncio.StreamWriter.drain
    failing: list[bytes] = []

    def write(writer, data):
        if writer is conn._writer and b'"pong"' in bytes(data):
            failing.append(bytes(data))
            return None
        return real_write(writer, data)

    async def drain(writer):
        if writer is conn._writer and failing:
            raise ConnectionResetError("giả lập socket hỏng khi gửi pong")
        await real_drain(writer)

    monkeypatch.setattr(asyncio.StreamWriter, "write", write)
    monkeypatch.setattr(asyncio.StreamWriter, "drain", drain)
    return failing


@pytest.mark.integration
async def test_pong_send_failure_ends_run_as_connection_lost(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """D3: lỗi gửi pong → `run` trả CONNECTION_LOST (không LOCAL, không treo), đóng kết nối, không rò task."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    failing = fail_pongs_on(monkeypatch, server)
    before = asyncio.all_tasks()
    received: list = []
    _, task = start_channel(server, received, ping_interval=5.0, dead_after=10.0)
    peer.send_dict({"type": "ping", "t": 5})
    await peer.drain()
    assert await asyncio.wait_for(task, 3) is CloseReason.CONNECTION_LOST
    assert failing, "phép thử vô nghĩa: pong chưa từng được gửi"
    assert received == [Ping(t=5)]
    assert server.closed
    await peer.expect_closed(2.0)
    await wait_until(lambda: not new_live_tasks(before), 0.5, "task con của run đã kết thúc")


@pytest.mark.integration
async def test_reader_result_wins_over_failed_pong(fast, monkeypatch, listener_factory, raw_client, ids):
    """D3, thứ tự ưu tiên: vòng đọc thấy lỗi giao thức ngay sau Ping, còn gửi pong thì hỏng.

    Ping và khung rác tới trong cùng một lần ghi, nên vòng đọc xử lý cả hai liền một mạch; lần gửi
    pong hỏng ngay sau đó. Kết quả phải là lý do của vòng đọc (PROTOCOL_ERROR).
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    fail_pongs_on(monkeypatch, server)
    before = asyncio.all_tasks()
    _, task = start_channel(server, [], ping_interval=5.0, dead_after=10.0)
    peer.send_bytes(encode_message({"type": "ping", "t": 5}) + frame(b"\xff\xfe\xfd"))
    await peer.drain()
    assert await asyncio.wait_for(task, 3) is CloseReason.PROTOCOL_ERROR
    assert server.closed
    await wait_until(lambda: not new_live_tasks(before), 0.5, "task con của run đã kết thúc")


@pytest.mark.integration
async def test_pending_pong_is_flushed_before_close_on_protocol_error(
    fast, listener_factory, raw_client, ids
):
    """D3, dọn dẹp: Ping rồi khung rác ngay sau → run kết thúc vì lỗi giao thức khi pong còn chờ.

    Kết nối chưa hỏng nên pong phải được gửi nốt trước khi đóng.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    _, task = start_channel(server, [], ping_interval=5.0, dead_after=10.0)
    peer.send_bytes(encode_message({"type": "ping", "t": 41}) + frame(b"\xff\xfe\xfd"))
    await peer.drain()
    assert await asyncio.wait_for(task, 3) is CloseReason.PROTOCOL_ERROR
    _, data = await peer.expect_closed(2.0)
    assert {"type": "pong", "t": 41} in frames_in(data)


@pytest.mark.slow
@pytest.mark.integration
async def test_pong_flush_and_close_share_one_close_timeout(fast, monkeypatch, listener_factory, ids):
    """D3, dọn dẹp: gửi nốt pong và đóng gọn dùng **chung một** hạn CLOSE_TIMEOUT, quá thì abort.

    Pong còn chờ mà khóa gửi bị giữ mãi (lần gửi của app kẹt ở drain), và máy kia không bao giờ
    đọc nên cũng không trả close_notify: cả hai bước dọn đều treo nếu không có hạn. CLOSE_TIMEOUT =
    1 s, DRAIN_TIMEOUT = 10 s: từ lúc on_message raise tới khi `run` kết thúc phải ≤ CLOSE_TIMEOUT
    cộng biên nhỏ (không phải 2 × CLOSE_TIMEOUT, cũng không chờ tới DRAIN_TIMEOUT).
    """
    # Biên rộng cho CI chậm; cài sai (hai hạn riêng) thì mất ~2 × close_timeout, vẫn bắt được.
    close_timeout, margin = 1.0, 0.7
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", close_timeout)
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    raised_at: list[float] = []

    def explode(msg):
        raised_at.append(time.monotonic())
        raise Boom(msg)

    gate = DrainGate(monkeypatch, block_from=1)
    task = app_send = None
    try:
        server = await h.next()
        raw = server._writer.get_extra_info("socket")
        task = asyncio.create_task(ControlChannel(server, ping_interval=5.0, dead_after=10.0).run(explode))
        app_send = await hold_send_lock(server, gate)
        await asyncio.to_thread(sock.sendall, encode_message({"type": "ping", "t": 9}))
        with pytest.raises(Boom):
            await asyncio.wait_for(task, 5)
        cleanup = time.monotonic() - raised_at[0]
        assert cleanup <= close_timeout + margin, (
            f"dọn mất {cleanup:.2f} s > CLOSE_TIMEOUT ({close_timeout} s) + {margin} s: "
            "gửi nốt pong và đóng gọn không dùng chung một hạn"
        )
        assert server.closed
        await wait_until(lambda: raw.fileno() == -1, 1.0, "socket phía server đã bị abort")
    finally:
        gate.open()
        await cancel_wait(*(t for t in (task, app_send) if t is not None))
        sock.close()


# =================================================================================================
# C1 (spec-dot-c mục 1.2.2): `Listener.set_hello` (máy này đổi tên lúc chạy)
# =================================================================================================


@pytest.mark.integration
async def test_listener_set_hello_new_connections_get_new_name(fast, listener_factory, ids):
    """Kết nối mở sau `set_hello` nhận `hello` mới; kết nối đã mở giữ `hello` đã gửi."""
    h = await listener_factory(ids.server, trusted=[ids.b], name="Ten-Cu")
    old = await b_control(h, ids)
    try:
        assert old.peer.hello.name == "Ten-Cu"
        new_hello = hello_of(ids.server, "Ten-Moi")
        assert h.listener.set_hello(new_hello) is None
        pairing = await anon_pairing(h, ids)
        try:
            assert pairing.peer.hello == new_hello
        finally:
            await pairing.close()
        control = await b_control(h, ids)
        try:
            assert control.peer.hello == new_hello
        finally:
            await control.close()
        assert old.peer.hello.name == "Ten-Cu"
        assert h.listener.port == h.port  # cổng không đổi
    finally:
        await old.close()


@pytest.mark.parametrize(
    "bad",
    ["thiet-bi-khac", "giao-thuc-khac", "khong-phai-hello"],
)
@pytest.mark.integration
async def test_set_hello_rejects_other_device_or_protocol(fast, listener_factory, ids, bad):
    """Kiểm như `__init__`: sai thì `ValueError` và vẫn giữ `hello` cũ cho kết nối sau."""
    h = await listener_factory(ids.server, name="Giu-Nguyen")
    value = {
        "thiet-bi-khac": hello_of(ids.x, "Ke-Gia"),
        "giao-thuc-khac": hello_of(ids.server, "Ke-Gia", protocol=PROTOCOL_VERSION + 1),
        "khong-phai-hello": {"type": "hello", "name": "Ke-Gia"},
    }[bad]
    with pytest.raises(ValueError):
        h.listener.set_hello(value)
    conn = await anon_pairing(h, ids)
    try:
        assert conn.peer.hello.name == "Giu-Nguyen"
    finally:
        await conn.close()


# =================================================================================================
# C2 = P4-1: chế độ ẩn (F10), `Listener(..., allow_anonymous=...)` (spec-dot-c mục 5.2, 5.3, 5.5 và
# mục 11: M4, L7). Kết nối không có chứng chỉ client còn tin cậy: ngay sau bắt tay TLS, trước khi gửi
# `hello`, Listener gọi `allow_anonymous(ip)`; không trả đúng `True` (hoặc ném lỗi) → hủy kết nối,
# 0 byte ứng dụng. Kết nối có chứng chỉ client còn tin cậy không bị ảnh hưởng. Viết theo đặc tả.
# =================================================================================================


class AllowRecorder:
    """`allow_anonymous` giả: ghi mọi IP được hỏi, trả `result` (hoặc ném `error`)."""

    def __init__(self, result: object = False, error: BaseException | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[object] = []

    def __call__(self, ip):
        self.calls.append(ip)
        if self.error is not None:
            raise self.error
        return self.result


async def assert_zero_bytes_after_tls(h, peer, within: float = 3.0) -> float:
    """Bắt tay TLS đã xong (có chứng chỉ server), rồi server đóng mà không gửi một byte ứng dụng nào."""
    ssl_object = peer.writer.get_extra_info("ssl_object")
    assert ssl_object is not None, "bắt tay TLS chưa xong"
    der = ssl_object.getpeercert(binary_form=True)
    assert der is not None and hashlib.sha256(der).hexdigest() == h.identity.fingerprint
    elapsed, data = await peer.expect_closed(within)
    assert data == b"", f"máy đang ẩn gửi {len(data)} byte ứng dụng cho kết nối ẩn danh: {data[:80]!r}"
    await h.wait_idle()
    assert h.calls == 0
    assert h.listener.connection_count == 0
    return elapsed


@pytest.mark.integration
async def test_hidden_anonymous_gets_zero_bytes_after_tls(slow_opening, listener_factory, raw_client, ids):
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    peer = await raw_client(h.port, None)
    elapsed = await assert_zero_bytes_after_tls(h, peer)
    # OPENING_TIMEOUT = 5 s: đóng trong < 1 s nghĩa là từ chối ngay, không chờ hết giờ.
    assert elapsed < 1.0, f"đóng sau {elapsed:.2f} s: có vẻ chờ hết giờ thay vì từ chối ngay"
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_hidden_anonymous_never_sees_name_even_if_it_sends_hello_first(
    slow_opening, listener_factory, raw_client, ids
):
    """Máy lạ không chờ `hello` mà gửi luôn `hello` + `pair_request`: vẫn không nhận được gì."""
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, allow_anonymous=allow, name="Ten-Bi-Mat")
    peer = await raw_client(h.port, None)
    peer.send_dict(wire_hello(ids.anon, "Anon"))
    peer.send_dict(to_dict(pair_request(ids.anon)))
    await peer.drain()
    await assert_zero_bytes_after_tls(h, peer)
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_hidden_open_pairing_is_refused(fast, listener_factory, ids):
    """Client thật (`open_pairing`) tới máy đang ẩn: không lấy được `hello` của server → lỗi kết nối."""
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, allow_anonymous=allow)
    with pytest.raises(ConnectError):
        await anon_pairing(h, ids)
    await h.wait_idle()
    assert h.calls == 0
    assert allow.calls and set(allow.calls) == {LOCAL}


@pytest.mark.integration
async def test_hidden_trusted_control_ok(fast, listener_factory, ids):
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    conn = await b_control(h, ids)
    try:
        assert conn.kind is ConnectionKind.CONTROL
        assert conn.peer.hello == h.hello
        server = await h.next()
        assert server.kind is ConnectionKind.CONTROL
        assert server.peer.fingerprint == ids.b.fingerprint
        await conn.send(Ping(t=5))
        assert await asyncio.wait_for(server.receive(), 2) == Ping(t=5)
    finally:
        await conn.close()
    # Kết nối có chứng chỉ client còn tin cậy không đi qua luật ẩn danh.
    assert allow.calls == []


@pytest.mark.integration
async def test_hidden_trusted_data_connection_ok(fast, listener_factory, raw_client, ids):
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    peer = await raw_opening(raw_client, h, ids.b, wire_hello(ids.b), DATA_OPEN)
    server = await h.next()
    assert server.kind is ConnectionKind.DATA
    assert server.peer.fingerprint == ids.b.fingerprint
    peer.abort()
    assert allow.calls == []


@pytest.mark.integration
async def test_hidden_untrusted_client_cert_asks_allow_anonymous(
    slow_opening, listener_factory, raw_client, ids
):
    """M4 (spec-dot-c mục 11): bắt tay bằng context cũ với chứng chỉ của máy vừa bị hủy ghép đôi
    (context còn chấp nhận, `is_trusted` thì không): Listener vẫn hỏi `allow_anonymous`, và máy
    đang ẩn không gửi `hello` cho nó."""
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    h.trusted_fps.clear()  # thôi tin cậy, nhưng chưa `update_trusted`: context bắt tay vẫn nhận B
    peer = await raw_client(h.port, ids.b)
    elapsed = await assert_zero_bytes_after_tls(h, peer)
    assert elapsed < 1.0, f"đóng sau {elapsed:.2f} s: có vẻ chờ hết giờ thay vì từ chối ngay"
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_untrusted_client_cert_allowed_anonymous_gets_hello(fast, listener_factory, raw_client, ids):
    """Ca đối chứng của M4: `allow_anonymous` trả True thì kết nối đó đi như ẩn danh thường (nhận `hello`)."""
    allow = AllowRecorder(True)
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    h.trusted_fps.clear()
    peer = await raw_client(h.port, ids.b)
    hello = await peer.read_hello()
    assert hello["device_id"] == ids.server.device_id
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_allow_anonymous_raise_refuses(slow_opening, listener_factory, raw_client, ids, caplog):
    caplog.set_level(logging.DEBUG, logger="teleport")
    allow = AllowRecorder(error=RuntimeError("lỗi giả lập trong allow_anonymous"))
    h = await listener_factory(ids.server, trusted=[ids.b], allow_anonymous=allow)
    for i in range(3):
        peer = await raw_client(h.port, None)
        elapsed = await assert_zero_bytes_after_tls(h, peer)
        assert elapsed < 1.0, f"lần {i}: đóng sau {elapsed:.2f} s thay vì từ chối ngay"
    assert allow.calls == [LOCAL] * 3
    # L7: ghi ở mức DEBUG, không WARNING/ERROR hay traceback mỗi kết nối (lũ kết nối không làm ngập log).
    loud = [r for r in caplog.records if r.name.startswith("teleport") and r.levelno >= logging.WARNING]
    assert loud == [], [f"{r.levelname} {r.getMessage()}" for r in loud]
    tracebacks = [r for r in caplog.records if r.name.startswith("teleport") and r.exc_info]
    assert tracebacks == [], [r.getMessage() for r in tracebacks]
    # Listener vẫn sống: thiết bị tin cậy vẫn vào được.
    conn = await b_control(h, ids)
    try:
        assert (await h.next()).peer.fingerprint == ids.b.fingerprint
    finally:
        await conn.close()


@pytest.mark.integration
@pytest.mark.parametrize(
    "result", [False, None, 1, "True", object()], ids=["False", "None", "1", "str", "object"]
)
async def test_allow_anonymous_only_exact_true_admits(
    slow_opening, listener_factory, raw_client, ids, result
):
    allow = AllowRecorder(result)
    h = await listener_factory(ids.server, allow_anonymous=allow)
    peer = await raw_client(h.port, None)
    await assert_zero_bytes_after_tls(h, peer)
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_allow_anonymous_true_lets_pairing_through(fast, listener_factory, ids):
    allow = AllowRecorder(True)
    h = await listener_factory(ids.server, allow_anonymous=allow)
    conn = await anon_pairing(h, ids)
    try:
        assert conn.peer.hello == h.hello
        await conn.send(pair_request(ids.anon))
        server = await h.next()
        assert server.kind is ConnectionKind.PAIRING
    finally:
        await conn.close()
    assert allow.calls == [LOCAL]


@pytest.mark.integration
async def test_allow_anonymous_is_asked_per_connection_and_change_takes_effect(
    slow_opening, listener_factory, raw_client, ids
):
    """Kết quả không bị nhớ: đổi giá trị trả về thì kết nối kế tiếp theo giá trị mới (bật/tắt lúc chạy)."""
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, allow_anonymous=allow)
    await assert_zero_bytes_after_tls(h, await raw_client(h.port, None))
    allow.result = True
    peer = await raw_client(h.port, None)
    await peer.read_hello()
    peer.abort()
    await h.wait_idle()
    allow.result = False
    await assert_zero_bytes_after_tls(h, await raw_client(h.port, None))
    assert allow.calls == [LOCAL] * 3


@pytest.mark.integration
async def test_allow_anonymous_not_asked_without_finished_tls(fast, listener_factory, raw_client, ids):
    """TCP trần (không bắt tay TLS) không bao giờ tới bước hỏi `allow_anonymous`."""
    allow = AllowRecorder(False)
    h = await listener_factory(ids.server, allow_anonymous=allow)
    peer = await raw_client(h.port, None, use_tls=False)
    peer.send_bytes(b"GET / HTTP/1.0\r\n\r\n")
    await peer.drain()
    await peer.expect_closed(5.0)
    await h.wait_idle()
    assert allow.calls == []


@pytest.mark.integration
async def test_allow_anonymous_none_keeps_old_behaviour(fast, listener_factory, raw_client, ids):
    """`allow_anonymous=None` (mặc định) là luôn cho: kết nối ẩn danh vẫn nhận `hello` như trước."""
    h = await listener_factory(ids.server)
    peer = await raw_client(h.port, None)
    assert (await peer.read_hello())["device_id"] == ids.server.device_id
    explicit = Listener(ids.server, h.hello, [], h.is_trusted, h.on_connection, allow_anonymous=None)
    await explicit.close()


# =================================================================================================
# CN: đóng TLS khi máy kia còn gửi sau close_notify (spec-close-notify, (a)–(f))
# =================================================================================================
#
# Khi `Connection.close` của kết nối ghép đôi / điều khiển đã gửi close_notify và đang chờ close_notify
# của máy kia, dữ liệu máy kia gửi trong lúc đó (ping, message) phải bị đọc bỏ, không làm hỏng lần đóng:
# nếu không, asyncio ném APPLICATION_DATA_AFTER_CLOSE_NOTIFY, cắt socket (RST) và máy kia mất phần
# đuôi ta đã gửi. Kết nối dữ liệu giữ hành vi cũ.

_CN_CLIP_DATA = 256 * 1024  # mỗi clip 256 KiB văn bản: 8 clip = 2 MiB, máy kia đọc chậm mất vài giây
_CN_CLIPS = 8
_CN_TAIL = Ping(t=424242)  # message cuối cùng ta gửi trước close(): máy kia phải nhận được


def _cn_clip(index: int) -> Clipboard:
    return Clipboard(
        clip_id="cd" * 16,
        kind="text",
        sha256="ef" * 32,
        total=_CN_CLIP_DATA * _CN_CLIPS,
        index=index,
        count=_CN_CLIPS,
        data="x" * _CN_CLIP_DATA,
    )


class _SlowChattyPeer:
    """Máy kia (client thô) đọc chậm và gửi `ping` đều đặn, kể cả sau khi ta đã gửi close_notify.

    Đọc tới EOF thì thôi gửi và đóng gọn (gửi close_notify của nó). `clean_eof` True nghĩa là kết thúc
    bằng EOF gọn, không phải lỗi (reset, lỗi SSL).
    """

    def __init__(self, peer, *, chunk: int = 16 * 1024, read_pause: float = 0.02, ping_every: float = 0.01):
        self.peer = peer
        self.chunk = chunk
        self.read_pause = read_pause
        self.ping_every = ping_every
        self.data = bytearray()
        self.clean_eof = False
        self.read_error: BaseException | None = None
        self.pings_sent = 0
        self._stop = asyncio.Event()
        self._pinger = asyncio.create_task(self._ping_loop())
        self.done = asyncio.create_task(self._read_loop())

    async def _ping_loop(self) -> None:
        t = 0
        while not self._stop.is_set():
            t += 1
            try:
                self.peer.writer.write(encode_message({"type": "ping", "t": t}))
                await self.peer.writer.drain()
            except (*CLOSED, RuntimeError):
                return
            self.pings_sent += 1
            await asyncio.sleep(self.ping_every)

    async def _read_loop(self) -> None:
        try:
            while True:
                try:
                    chunk = await self.peer.reader.read(self.chunk)
                except CLOSED as e:
                    self.read_error = e
                    return
                if not chunk:
                    self.clean_eof = True
                    return
                self.data += chunk
                if self.read_pause:
                    await asyncio.sleep(self.read_pause)
        finally:
            self._stop.set()
            await cancel_wait(self._pinger)
            await self.peer.close_gracefully()

    async def cancel(self) -> None:
        self._stop.set()
        await cancel_wait(self._pinger, self.done)


@pytest.mark.integration
async def test_control_close_delivers_tail_while_peer_keeps_pinging(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """(a) Máy kia đọc chậm và gửi ping liên tục: close() vẫn đóng gọn, máy kia nhận đủ phần đuôi.

    Ta gửi 2 MiB clip + một `ping` đánh dấu rồi close(). Lúc close_notify của ta đi, máy kia còn nhiều
    dữ liệu chưa đọc và vẫn gửi ping. Phải: close() xong trước CLOSE_TIMEOUT, máy kia nhận đủ mọi
    khung theo đúng thứ tự (khung cuối là `ping` đánh dấu) rồi thấy EOF gọn, không reset.
    """
    close_timeout = 5.0
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", close_timeout)
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)  # máy kia đọc chậm: gửi không được bỏ cuộc
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    chatty = _SlowChattyPeer(peer)
    try:
        for i in range(_CN_CLIPS):
            await server.send(_cn_clip(i))
        await server.send(_CN_TAIL)
        pings_before_close = chatty.pings_sent
        start = time.monotonic()
        await asyncio.wait_for(server.close(), close_timeout + 2.0)
        elapsed = time.monotonic() - start
        await asyncio.wait_for(asyncio.shield(chatty.done), 10.0)
    finally:
        await chatty.cancel()

    assert server.closed
    assert chatty.pings_sent > pings_before_close, "phép thử vô nghĩa: máy kia không gửi gì sau close()"
    assert chatty.read_error is None, (
        f"máy kia thấy lỗi thay cho EOF gọn: {chatty.read_error!r} (đã nhận {len(chatty.data)} byte)"
    )
    assert chatty.clean_eof
    frames = frames_in(bytes(chatty.data))
    assert [f["type"] for f in frames] == ["clipboard"] * _CN_CLIPS + ["ping"], (
        f"thiếu phần đuôi: nhận {len(frames)} khung, {len(chatty.data)} byte"
    )
    assert [f["index"] for f in frames[:-1]] == list(range(_CN_CLIPS))
    assert parse_message(frames[-1]) == _CN_TAIL
    assert elapsed < close_timeout, f"close() mất {elapsed:.2f} s: đóng gọn phải xong trước CLOSE_TIMEOUT"


def _flood_until(sock: ssl.SSLSocket, stop: threading.Event) -> None:
    """Gửi `ping` liên tục, không bao giờ đọc (nên không bao giờ trả close_notify), tới khi `stop` hay lỗi."""
    batch = b"".join(encode_message({"type": "ping", "t": i}) for i in range(64))
    with contextlib.suppress(OSError, ValueError):
        while not stop.is_set():
            sock.sendall(batch)
            time.sleep(0.002)


@pytest.mark.integration
async def test_control_close_is_bounded_when_peer_floods_and_never_answers(fast, listener_factory, ids):
    """(b) Máy kia gửi mãi và không bao giờ trả close_notify → close() vẫn ≤ CLOSE_TIMEOUT + biên.

    CLOSE_TIMEOUT = 0,5 s (fixture `fast`, vá trước khi mở kết nối). Việc đọc bỏ dữ liệu tới sau
    close_notify không được kéo dài lần đóng, cũng không treo vòng lặp.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    sock = await asyncio.to_thread(sync_open_control, h.port, ids.b)
    stop = threading.Event()
    flooder = asyncio.create_task(asyncio.to_thread(_flood_until, sock, stop))
    try:
        server = await h.next()
        await asyncio.sleep(0.1)
        assert not flooder.done(), "phép thử vô nghĩa: máy kia không còn gửi"
        start = time.monotonic()
        await asyncio.wait_for(server.close(), 5.0)
        elapsed = time.monotonic() - start
        assert elapsed <= 0.5 + 1.0, f"close() mất {elapsed:.2f} s"
        assert server.closed
    finally:
        stop.set()
        await asyncio.wait_for(flooder, 10.0)
        sock.close()


async def _wait_stalled(progress, what: str, *, quiet: float = 0.5, timeout: float = 15.0) -> None:
    """Chờ tới khi `progress()` đứng yên `quiet` giây liền (bên gửi kẹt vì bên kia không đọc)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        before = progress()
        await asyncio.sleep(quiet)
        if progress() == before:
            return
    raise AssertionError(f"hết {timeout} s mà {what} vẫn chưa kẹt (đã gửi {progress()} byte)")


@pytest.mark.integration
async def test_listener_side_close_with_full_read_buffer_still_closes_cleanly(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """(f), phía Listener: tầng trên không đọc, máy kia gửi tới khi bộ đệm đọc đầy (đọc socket bị tạm
    dừng) rồi close().

    Phải: dữ liệu đã nằm trong bộ đệm bị bỏ, việc đọc socket được gỡ tạm dừng để close_notify của máy
    kia tới được: close() xong gọn trước CLOSE_TIMEOUT, máy kia nhận `ping` đánh dấu rồi EOF gọn,
    không reset.
    """
    close_timeout = 5.0
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", close_timeout)
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    batch = b"".join(encode_message({"type": "ping", "t": i}) for i in range(2048))
    drained = 0

    async def flood() -> None:
        nonlocal drained
        with contextlib.suppress(*CLOSED, RuntimeError):
            while drained < 64 * 1024 * 1024:
                peer.writer.write(batch)
                await peer.writer.drain()
                drained += len(batch)

    flooder = asyncio.create_task(flood())
    reader = None
    try:
        await _wait_stalled(lambda: drained, "máy kia gửi")
        reader = _SlowChattyPeer(peer, read_pause=0.0, ping_every=3600.0)
        await server.send(_CN_TAIL)
        start = time.monotonic()
        await asyncio.wait_for(server.close(), close_timeout + 2.0)
        elapsed = time.monotonic() - start
        await asyncio.wait_for(asyncio.shield(reader.done), 10.0)
    finally:
        await cancel_wait(flooder)
        if reader is not None:
            await reader.cancel()

    assert reader.read_error is None, f"máy kia thấy lỗi thay cho EOF gọn: {reader.read_error!r}"
    assert reader.clean_eof
    assert [parse_message(f) for f in frames_in(bytes(reader.data))] == [_CN_TAIL]
    assert elapsed < close_timeout, f"close() mất {elapsed:.2f} s: đóng gọn phải xong trước CLOSE_TIMEOUT"


@pytest.mark.integration
async def test_client_side_close_with_paused_ssl_reading_still_closes_cleanly(
    fast, monkeypatch, listener_factory, ids
):
    """(f), phía client (`open_control`): tầng trên không đọc, máy kia gửi tới khi bộ đệm đọc TLS đầy
    (`_ssl_reading_paused`) rồi close().

    Như bản phía Listener: close() xong gọn trước CLOSE_TIMEOUT, máy kia nhận `ping` đánh dấu rồi
    thấy EOF gọn (`receive` trả None), không ConnectionLostError.
    """
    close_timeout = 5.0
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", close_timeout)
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    remote = await h.next()
    stop = asyncio.Event()
    sent = 0
    got: list = []
    outcome: list = []

    async def flood() -> None:
        nonlocal sent
        with contextlib.suppress(ConnectionLostError):
            while not stop.is_set():
                await remote.send(Ping(t=sent))
                sent += 1

    async def read_until_eof() -> None:
        try:
            while (msg := await remote.receive()) is not None:
                got.append(msg)
            outcome.append("eof")
        except ConnectionLostError as e:
            outcome.append(e)
        stop.set()
        await asyncio.wait_for(asyncio.shield(flooder), 3.0)
        await remote.close()

    flooder = asyncio.create_task(flood())
    remote_reader = None
    try:
        await _wait_stalled(lambda: sent, "máy kia gửi")
        proto = conn._writer.transport._ssl_protocol
        assert getattr(proto, "_ssl_reading_paused", True), "phép thử vô nghĩa: đọc TLS chưa bị tạm dừng"
        remote_reader = asyncio.create_task(read_until_eof())
        await conn.send(_CN_TAIL)
        start = time.monotonic()
        await asyncio.wait_for(conn.close(), close_timeout + 2.0)
        elapsed = time.monotonic() - start
        await asyncio.wait_for(asyncio.shield(remote_reader), 10.0)
    finally:
        stop.set()
        await cancel_wait(*(t for t in (flooder, remote_reader) if t is not None))
        await remote.close()

    assert outcome == ["eof"], f"máy kia thấy lỗi thay cho EOF gọn: {outcome!r}"
    assert got == [_CN_TAIL]
    assert elapsed < close_timeout, f"close() mất {elapsed:.2f} s: đóng gọn phải xong trước CLOSE_TIMEOUT"


# --- (c), (e): hook chỉ cài cho kết nối ghép đôi và điều khiển, và cài được trên Python đang chạy ----


async def _server_conn_of(kind: str, h, ids, raw_client):
    if kind == "pairing":
        return await raw_pairing(raw_client, h, ids)
    if kind == "control":
        return await raw_control(raw_client, h, ids)
    peer = await raw_opening(raw_client, h, ids.b, wire_hello(ids.b), DATA_OPEN)
    return peer, await h.next()


def _hook_installed(writer) -> bool:
    """Hook đọc bỏ được bọc **trên instance** SSLProtocol (đặc tả mục 1), không sửa lớp."""
    return "_do_shutdown" in vars(writer.transport._ssl_protocol)


def _spy_discard(monkeypatch) -> list:
    calls: list = []
    real = connection._discard_after_close_notify

    def spy(writer, **kwargs):
        calls.append(writer)
        return real(writer, **kwargs)

    monkeypatch.setattr(connection, "_discard_after_close_notify", spy)
    return calls


@pytest.mark.integration
@pytest.mark.parametrize(("kind", "hooked"), [("pairing", True), ("control", True), ("data", False)])
async def test_close_installs_discard_hook_only_for_pairing_and_control(
    fast, monkeypatch, listener_factory, raw_client, ids, kind, hooked
):
    """(c) `Connection.close` gọi `_discard_after_close_notify` với kết nối ghép đôi / điều khiển;
    kết nối dữ liệu giữ hành vi cũ (không đọc bỏ: bên nhận đóng giữa chừng thì RST là đúng ý)."""
    calls = _spy_discard(monkeypatch)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await _server_conn_of(kind, h, ids, raw_client)
    assert server.kind is ConnectionKind(kind)
    writer = server._writer
    task = asyncio.create_task(server.close())
    await peer.expect_closed(3.0)
    await peer.close_gracefully()
    await asyncio.wait_for(task, 3.0)
    assert server.closed
    if hooked:
        assert calls == [writer]
        assert _hook_installed(writer)
    else:
        assert calls == []
        assert not _hook_installed(writer)


@pytest.mark.integration
async def test_client_side_control_close_installs_discard_hook(fast, monkeypatch, listener_factory, ids):
    """(c) Phía client (`open_control`) cũng được bọc: ai đóng trước cũng có thể gặp máy kia còn gửi."""
    calls = _spy_discard(monkeypatch)
    h = await listener_factory(ids.server, trusted=[ids.b])
    conn = await b_control(h, ids)
    server = await h.next()
    writer = conn._writer
    await asyncio.gather(conn.close(), server.close())
    assert writer in calls
    assert _hook_installed(writer)


@pytest.mark.integration
async def test_canary_discard_hook_installs_on_running_python(fast, listener_factory, raw_client, ids):
    """(e) Canary: trên Python đang chạy, sslproto vẫn có đủ thuộc tính nội bộ hook cần và hook cài được.

    Nâng Python mà asyncio đổi sslproto thì hook lặng lẽ thành không làm gì (fallback): test này đỏ để
    CI báo ngay, thay vì lỗi mất phần đuôi chỉ lộ ra khi chạy thật.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    writer = server._writer
    proto = writer.transport._ssl_protocol
    for name in ("_do_shutdown", "_control_ssl_reading"):
        assert callable(getattr(proto, name, None)), f"sslproto không còn {name}"
    for name in ("_sslobj", "_eof_received", "_ssl_reading_paused"):
        assert hasattr(proto, name), f"sslproto không còn {name}"
    assert callable(getattr(proto._sslobj, "read", None))
    assert not _hook_installed(writer)
    connection._discard_after_close_notify(writer)
    assert _hook_installed(writer), f"hook không cài được trên Python {sys.version.split()[0]}"
    task = asyncio.create_task(server.close())
    await peer.expect_closed(3.0)
    await peer.close_gracefully()
    await asyncio.wait_for(task, 3.0)


# --- (d): gọi lặp không bọc chồng; thiếu thuộc tính nội bộ thì giữ hành vi cũ, không raise ----------


class _FakeSSLObj:
    """`SSLObject` giả: `read` trả lần lượt các phần tử của `script` (ngoại lệ thì ném), hết thì WantRead."""

    def __init__(self, *script) -> None:
        self.script = list(script)
        self.reads = 0

    def read(self, n: int = 1024, buffer=None):
        self.reads += 1
        item = self.script.pop(0) if self.script else ssl.SSLWantReadError("hết dữ liệu")
        if isinstance(item, BaseException):
            raise item
        return item


class _FakeProto:
    """SSLProtocol giả: chỉ có các thuộc tính hook dùng; ghi lại thứ tự gọi."""

    def __init__(self, sslobj=None, *, eof_received: bool = False) -> None:
        self._sslobj = sslobj
        self._eof_received = eof_received
        self.events: list[str] = []

    def _do_shutdown(self) -> None:
        self.events.append("shutdown")

    def _control_ssl_reading(self) -> None:
        self.events.append("control")


def _writer_of(proto) -> SimpleNamespace:
    return SimpleNamespace(transport=SimpleNamespace(_ssl_protocol=proto))


def test_discard_hook_reads_until_want_read_then_calls_original():
    sslobj = _FakeSSLObj(b"p" * 100, b"q" * 100)
    proto = _FakeProto(sslobj)
    connection._discard_after_close_notify(_writer_of(proto))
    proto._do_shutdown()
    assert sslobj.reads == 3  # hai lần có dữ liệu, lần thứ ba WantRead
    assert proto.events.count("shutdown") == 1
    assert "control" in proto.events, "phải gỡ tạm dừng đọc socket sau khi đọc bỏ (Sửa 1)"


def test_discard_hook_stops_at_peer_close_notify_and_calls_original():
    sslobj = _FakeSSLObj(b"p" * 100, ssl.SSLZeroReturnError("close_notify"), b"never")
    proto = _FakeProto(sslobj)
    connection._discard_after_close_notify(_writer_of(proto))
    proto._do_shutdown()
    assert sslobj.reads == 2
    assert proto.events.count("shutdown") == 1


def test_discard_hook_leaves_other_ssl_errors_to_original():
    """Sửa 2: SSLError khác không bị nuốt thành 'đóng gọn': ngừng đọc, không raise, giao cho bản gốc."""
    sslobj = _FakeSSLObj(ssl.SSLError(1, "giả lập lỗi khác"), b"never")
    proto = _FakeProto(sslobj)
    connection._discard_after_close_notify(_writer_of(proto))
    proto._do_shutdown()
    assert sslobj.reads == 1
    assert proto.events.count("shutdown") == 1


@pytest.mark.parametrize("case", ["eof_received", "no_sslobj"])
def test_discard_hook_does_not_read_when_nothing_to_read(case):
    sslobj = _FakeSSLObj(b"never")
    proto = _FakeProto(sslobj, eof_received=True) if case == "eof_received" else _FakeProto(None)
    connection._discard_after_close_notify(_writer_of(proto))
    proto._do_shutdown()
    assert sslobj.reads == 0
    assert proto.events.count("shutdown") == 1


def test_discard_hook_installed_repeatedly_does_not_stack():
    sslobj = _FakeSSLObj(b"p" * 100)
    proto = _FakeProto(sslobj)
    writer = _writer_of(proto)
    connection._discard_after_close_notify(writer)
    first = proto._do_shutdown
    connection._discard_after_close_notify(writer)
    connection._discard_after_close_notify(writer)
    assert proto._do_shutdown is first
    proto._do_shutdown()
    assert sslobj.reads == 2  # đúng một vòng đọc bỏ
    assert proto.events.count("shutdown") == 1


class _BareProto:
    """SSLProtocol 'đời Python khác': chỉ có `_do_shutdown`, không có thuộc tính nội bộ nào khác."""

    def __init__(self) -> None:
        self.shutdowns = 0

    def _do_shutdown(self) -> None:
        self.shutdowns += 1


def test_discard_hook_without_internal_attributes_keeps_old_behaviour():
    proto = _BareProto()
    connection._discard_after_close_notify(_writer_of(proto))
    proto._do_shutdown()
    assert proto.shutdowns == 1


@pytest.mark.parametrize(
    "writer",
    [
        SimpleNamespace(transport=None),
        SimpleNamespace(transport=SimpleNamespace()),  # không phải transport TLS (không _ssl_protocol)
        SimpleNamespace(transport=SimpleNamespace(_ssl_protocol=None)),
        SimpleNamespace(transport=SimpleNamespace(_ssl_protocol=SimpleNamespace())),  # không _do_shutdown
    ],
    ids=["transport-none", "no-ssl-protocol", "ssl-protocol-none", "no-do-shutdown"],
)
def test_discard_hook_missing_internals_does_not_raise(writer):
    connection._discard_after_close_notify(writer)


@pytest.mark.integration
async def test_discard_hook_repeated_on_live_connection_then_close_still_clean(
    fast, listener_factory, raw_client, ids
):
    """(d) Trên kết nối thật: cài trước hai lần rồi close() (cài lần ba) → không bọc chồng, vẫn đóng gọn."""
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    writer = server._writer
    proto = writer.transport._ssl_protocol
    connection._discard_after_close_notify(writer)
    first = vars(proto)["_do_shutdown"]
    connection._discard_after_close_notify(writer)
    assert vars(proto)["_do_shutdown"] is first
    await server.send(_CN_TAIL)
    task = asyncio.create_task(server.close())
    _, data = await peer.expect_closed(3.0)
    await peer.close_gracefully()
    await asyncio.wait_for(task, 3.0)
    assert vars(proto)["_do_shutdown"] is first
    assert [parse_message(f) for f in frames_in(data)] == [_CN_TAIL]


async def _peer_sent_then_closed(raw_client, h, ids, pings: list[int]):
    """Máy kia gửi các `ping` rồi đóng gọn; trả `server` khi transport phía này đã đóng hẳn.

    Phía này không đọc gì: các message nằm trong bộ đệm đọc, tầng TLS đã trả close_notify.
    """
    peer, server = await raw_control(raw_client, h, ids)
    for t in pings:
        peer.send_dict({"type": "ping", "t": t})
    await peer.drain()
    await peer.close_gracefully()
    await asyncio.wait_for(server._writer.wait_closed(), 3.0)
    return server


@pytest.mark.integration
async def test_send_after_peer_closed_cleanly_only_closes_send_side(fast, listener_factory, raw_client, ids):
    """Máy kia gửi message rồi đóng gọn; `send` phía này lỗi → chỉ khóa chiều gửi.

    `closed` vẫn False, `receive` trả nốt các message đã đệm rồi None, `send` sau → ConnectionLostError
    ngay; `close()` vẫn chạy.
    """
    h = await listener_factory(ids.server, trusted=[ids.b])
    server = await _peer_sent_then_closed(raw_client, h, ids, [1, 2])
    with pytest.raises(ConnectionLostError):
        await server.send(Ping(t=9))
    assert not server.closed
    assert await asyncio.wait_for(server.receive(), 2) == Ping(t=1)
    assert await asyncio.wait_for(server.receive(), 2) == Ping(t=2)
    assert await asyncio.wait_for(server.receive(), 2) is None
    with pytest.raises(ConnectionLostError):
        await server.send(Ping(t=10))
    await asyncio.wait_for(server.close(), 3.0)
    assert server.closed


@pytest.mark.integration
async def test_control_channel_pong_failure_after_peer_closed_still_delivers_buffer(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """`pong` / `ping` gửi hỏng vì máy kia đã đóng gọn không kết thúc `run`: mọi message đã đệm tới
    `on_message`.

    Bộ đệm đã có EOF nên `receive` không bao giờ nhường loop; mỗi `receive` được cho ngủ 10 ms (bên
    nhận chậm) để task pong/keepalive kịp gửi hỏng giữa chừng.
    """
    real_receive = connection.Connection.receive

    async def slow_receive(self):
        await asyncio.sleep(0.01)
        return await real_receive(self)

    monkeypatch.setattr(connection.Connection, "receive", slow_receive)
    h = await listener_factory(ids.server, trusted=[ids.b])
    server = await _peer_sent_then_closed(raw_client, h, ids, list(range(1, 51)))
    got: list = []
    reason = await asyncio.wait_for(
        ControlChannel(server, ping_interval=PI, dead_after=DA).run(got.append), 5
    )
    assert reason is CloseReason.PEER_CLOSED
    assert got == [Ping(t=t) for t in range(1, 51)]
    assert server.closed


@pytest.mark.integration
async def test_control_channel_ping_failure_after_peer_closed_still_delivers_buffer(
    fast, monkeypatch, listener_factory, raw_client, ids
):
    """Nhánh `_keepalive_loop` → `_after_send_lost`: máy kia không ping (chỉ gửi `pong`) rồi đóng gọn;
    `ping` của keepalive gửi hỏng không kết thúc `run`: đủ message rồi `PEER_CLOSED`.

    `ping_interval` rất nhỏ nên `ping` đầu tiên được gửi (và hỏng) trước khi vòng đọc đọc xong; mỗi
    `receive` ngủ 20 ms để vòng đọc chắc chắn còn dở lúc đó.
    """
    real_receive = connection.Connection.receive

    async def slow_receive(self):
        await asyncio.sleep(0.02)
        return await real_receive(self)

    monkeypatch.setattr(connection.Connection, "receive", slow_receive)
    h = await listener_factory(ids.server, trusted=[ids.b])
    peer, server = await raw_control(raw_client, h, ids)
    for t in range(1, 21):
        peer.send_dict({"type": "pong", "t": t})
    await peer.drain()
    await peer.close_gracefully()
    await asyncio.wait_for(server._writer.wait_closed(), 3.0)
    got: list = []
    reason = await asyncio.wait_for(
        ControlChannel(server, ping_interval=0.005, dead_after=5.0).run(got.append), 5
    )
    assert reason is CloseReason.PEER_CLOSED
    assert got == [Pong(t=t) for t in range(1, 21)]


def _sync_open_pairing(port: int, anon) -> ssl.SSLSocket:
    sock = sync_connect(port, tls.client_context())
    try:
        hello = sync_read_frame(sock)
        assert hello is not None and hello["type"] == "hello"
        sock.sendall(encode_message(wire_hello(anon, "Anon")) + encode_message(to_dict(pair_request(anon))))
    except BaseException:
        sock.close()
        raise
    return sock


@pytest.mark.integration
async def test_pairing_close_aborts_quickly_when_peer_floods_past_discard_limit(
    fast, monkeypatch, listener_factory, ids
):
    """Máy ẩn danh (ghép đôi) gửi lũ sau close_notify của ta, không bao giờ trả close_notify: đọc bỏ
    dừng ở `_DISCARD_LIMIT_PAIRING` rồi kết nối bị cắt ngay, không đọc bỏ (tốn CPU) tới hết CLOSE_TIMEOUT.
    """
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", 10.0)
    h = await listener_factory(ids.server)
    sock = await asyncio.to_thread(_sync_open_pairing, h.port, ids.anon)
    stop = threading.Event()
    flooder = asyncio.create_task(asyncio.to_thread(_flood_until, sock, stop))
    try:
        server = await h.next()
        assert server.kind is ConnectionKind.PAIRING
        await asyncio.sleep(0.1)
        assert not flooder.done(), "phép thử vô nghĩa: máy kia không còn gửi"
        start = time.monotonic()
        await asyncio.wait_for(server.close(), 10.0)
        elapsed = time.monotonic() - start
        assert server.closed
        assert elapsed < 1.0, f"close() mất {elapsed:.2f} s: đọc bỏ không có trần"
    finally:
        stop.set()
        await asyncio.wait_for(flooder, 10.0)
        sock.close()


def test_discard_hook_stops_at_limit_and_leaves_rest_to_original():
    """Đọc bỏ vượt `limit` thì thôi đọc (kể cả ở các lần gọi sau) và không gỡ tạm dừng đọc socket."""
    sslobj = _FakeSSLObj(*([b"x" * 1000] * 10))
    proto = _FakeProto(sslobj)
    connection._discard_after_close_notify(_writer_of(proto), limit=2500)
    proto._do_shutdown()
    assert sslobj.reads == 3  # 3000 byte > 2500: dừng
    assert proto.events == ["shutdown"]
    proto._do_shutdown()
    assert sslobj.reads == 3
    assert proto.events == ["shutdown", "shutdown"]


def test_discard_limits_by_kind():
    assert connection._DISCARD_LIMIT_PAIRING == 64 * 1024
    limit = connection._DISCARD_LIMIT_CONTROL
    assert limit == 2 * (connection.MAX_MESSAGE_SIZE + HEADER.size)
