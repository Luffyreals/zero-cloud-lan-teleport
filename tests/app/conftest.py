"""Fixture dùng chung cho test tầng app (đặc tả PR-3 mục 4.1).

`tests/net/conftest.py` không dùng chung được (`--import-mode=importlib`), nên các phần cần dùng
được chép lại ở đây. Module `teleport.app.*` chỉ được import **bên trong** fixture: nếu một module
chưa có, chỉ các test dùng tới nó hỏng (ví dụ `test_settings.py` vẫn chạy khi `node.py` chưa có).

Hàm phụ trợ (không phải fixture) lấy qua fixture `app_helpers`, vì test không import được conftest.
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import gc
import hashlib
import inspect
import secrets
import socket
import ssl
import time
import uuid
import warnings
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.x509.oid import ExtensionOID, NameOID
from support import wait_until

from teleport.core.framing import HEADER, MAX_PAIRING_MESSAGE_SIZE, FramingError, encode_message
from teleport.core.messages import PROTOCOL_VERSION
from teleport.core.pairing_code import NONCE_SIZE, pairing_code
from teleport.lock import NodeLock
from teleport.net import tls
from teleport.net.stream import read_message
from teleport.trust.identity import Identity, load_or_create_identity, peer_cert_from_pem
from teleport.trust.store import TrustStore

LOCAL = "127.0.0.1"
# Các cách một kết nối bị đóng mà phía đọc có thể thấy (Windows hay báo reset thay cho EOF).
CLOSED_ERRORS: tuple[type[BaseException], ...] = (ConnectionError, ssl.SSLError)

# `FAST` và fixture `fast` nằm ở tests/conftest.py (P2-7, spec-p2-7 mục A5); test đọc giá trị qua
# fixture `fast` (vá rồi trả `FAST`) hoặc `fast_values` (chỉ trả `FAST`).


# --- Hàm phụ trợ ---------------------------------------------------------------------------------


async def expect_closed(reader: asyncio.StreamReader, within: float) -> tuple[float, bytes]:
    """Đọc tới khi thấy kết nối đóng (EOF, reset, lỗi SSL) trong `within` giây; trả (thời gian, byte)."""
    start = time.monotonic()
    data = bytearray()
    try:
        async with asyncio.timeout(within):
            while True:
                try:
                    chunk = await reader.read(65536)
                except CLOSED_ERRORS:
                    break
                if not chunk:
                    break
                data += chunk
    except TimeoutError:
        raise AssertionError(f"kết nối vẫn mở sau {within} s (đã nhận {len(data)} byte)") from None
    return time.monotonic() - start, bytes(data)


def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCAL, 0))
        return s.getsockname()[1]
    finally:
        s.close()


@contextlib.contextmanager
def busy_port():
    """Một socket đang listen trên 127.0.0.1; trả cổng của nó."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind((LOCAL, 0))
        s.listen(1)
        yield s.getsockname()[1]
    finally:
        s.close()


def hello_dict(identity_or_id: Identity | str, name: str = "Raw", **overrides: object) -> dict:
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


def frame(body: bytes) -> bytes:
    return HEADER.pack(len(body)) + body


def fake_cert_with_cn(device_id: str, *, ca: bool = False) -> tuple[str, bytes]:
    """Chứng chỉ tự ký P-256 mới, CN `teleport-<device_id>`: danh tính khác, cùng device_id (P12).

    Trả (PEM chứng chỉ, PEM khóa riêng PKCS8): có khóa thì ký được `pair_nonce` bằng danh tính này
    (protocol 5.1–5.2), hoặc dựng `Identity` qua `identity_from_pem`.
    `ca=True` thêm BasicConstraints CA=true (P21: phải bị từ chối).
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teleport-" + device_id)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(9999, 12, 31, tzinfo=datetime.UTC))
    )
    if ca:
        builder = builder.add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
    cert = builder.sign(key, hashes.SHA256())
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), key_pem


# SAN thô mà `cryptography` không đọc được (UnsupportedGeneralNameType, không phải ValueError):
# GeneralNames chứa một x400Address [3] hoặc một EDIPartyName [5] rỗng (kế hoạch M1).
SAN_X400 = b"\x30\x02\xa3\x00"
SAN_EDI = b"\x30\x02\xa5\x00"


def cert_with_raw_san(device_id: str, san_der: bytes) -> tuple[str, bytes]:
    """Chứng chỉ tự ký P-256, CN `teleport-<device_id>`, hiệu lực 2000–9999, ký ECDSA-SHA256, chỉ
    thêm extension SAN mang `san_der` thô. Trả (PEM chứng chỉ, PEM khóa riêng PKCS8).

    Đúng mọi điều kiện của chứng chỉ thiết bị Teleport trừ SAN: lỗi nào xảy ra là do SAN.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teleport-" + device_id)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC))
        .not_valid_after(datetime.datetime(9999, 12, 31, tzinfo=datetime.UTC))
        .add_extension(
            x509.UnrecognizedExtension(ExtensionOID.SUBJECT_ALTERNATIVE_NAME, san_der), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), key_pem


def identity_from_pem(directory: Path, device_id: str, cert_pem: str, key_pem: bytes) -> Identity:
    """`Identity` dựng thẳng từ chứng chỉ và khóa cho trước (không qua `load_or_create_identity`,
    không kiểm gì), để chạy một server TLS giả mang chứng chỉ đó."""
    directory.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = directory / "device.crt", directory / "device.key"
    cert_path.write_text(cert_pem, encoding="ascii")
    key_path.write_bytes(key_pem)
    der = x509.load_pem_x509_certificate(cert_pem.encode("ascii")).public_bytes(serialization.Encoding.DER)
    return Identity(device_id, cert_path, key_path, hashlib.sha256(der).hexdigest())


def identity_below(directory: Path, device_id: str) -> Identity:
    """Một danh tính mới (trong `directory`) có `device_id` nhỏ hơn `device_id` cho trước.

    Dùng để dựng "bên nhỏ hơn" trong luật hai bên cùng chủ động (protocol §5.3). `device_id` được
    chọn thẳng (bằng `device_id` − 1) thay vì sinh ngẫu nhiên tới khi gặp số nhỏ hơn: với
    `device_id` như `02…`, 64 lần sinh ngẫu nhiên vẫn hỏng khoảng một nửa số lần chạy.
    """
    value = int(device_id, 16)
    if value == 0:
        raise AssertionError("không có device_id nào nhỏ hơn 000…0")
    below = f"{value - 1:032x}"
    cert_pem, key_pem = fake_cert_with_cn(below)
    return identity_from_pem(directory, below, cert_pem, key_pem)


def ensure_identity(directory: Path) -> Identity:
    return load_or_create_identity(directory)


def seed_trust(directory: Path, pem: str, name: str) -> None:
    """Thêm một mục vào `trusted.json` của `directory` khi node chưa chạy (tạo danh tính trước)."""
    ensure_identity(directory)
    TrustStore.load(directory).add(peer_cert_from_pem(pem), name)


def lock_is_free(directory: Path) -> bool:
    lock = NodeLock(directory)
    try:
        lock.acquire()
    except Exception:
        return False
    lock.release()
    return True


def cert_client_context(identity: Identity) -> ssl.SSLContext:
    """Client gửi chứng chỉ của `identity` nhưng KHÔNG kiểm chứng chỉ server (`CERT_NONE`).

    Chỉ để thử phía server. Sản phẩm không còn đường nào như vậy (`docs/protocol.md` mục 2.1:
    chứng chỉ client chỉ đi tới server đã được kiểm bằng `tls.trusted_client_context`). Bản chép
    của `tests/net/conftest.py`.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_3
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.load_cert_chain(identity.cert_path, identity.key_path)
    return ctx


def fingerprint_of_pem(pem: str) -> str:
    der = x509.load_pem_x509_certificate(pem.encode("ascii")).public_bytes(serialization.Encoding.DER)
    return hashlib.sha256(der).hexdigest()


class RawPeer:
    """Client TLS (ẩn danh hoặc có chứng chỉ) hay TCP trần, tự soạn từng byte gửi đi."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self.reader = reader
        self.writer = writer
        self.server_hello: dict | None = None

    @classmethod
    async def connect(
        cls, port: int, identity: Identity | None = None, *, use_tls: bool = True, timeout: float = 5.0
    ) -> RawPeer:
        ctx = None
        if use_tls:
            ctx = tls.client_context() if identity is None else cert_client_context(identity)
        reader, writer = await asyncio.wait_for(asyncio.open_connection(LOCAL, port, ssl=ctx), timeout)
        return cls(reader, writer)

    def send_bytes(self, data: bytes) -> None:
        with contextlib.suppress(*CLOSED_ERRORS, RuntimeError):
            self.writer.write(data)

    def send_dict(self, msg: dict) -> None:
        self.send_bytes(encode_message(msg))

    async def drain(self) -> None:
        with contextlib.suppress(*CLOSED_ERRORS, RuntimeError):
            await self.writer.drain()

    async def read(self, timeout: float = 3.0) -> dict | None:
        return await asyncio.wait_for(read_message(self.reader, MAX_PAIRING_MESSAGE_SIZE), timeout)

    async def read_hello(self, timeout: float = 3.0) -> dict:
        msg = await self.read(timeout)
        assert msg is not None and msg.get("type") == "hello", f"server không gửi hello trước: {msg!r}"
        self.server_hello = msg
        return msg

    async def read_type(self, type_name: str, timeout: float = 3.0) -> dict:
        msg = await self.read(timeout)
        assert msg is not None, f"kết nối đóng trước khi nhận {type_name}"
        assert msg.get("type") == type_name, f"cần {type_name}, nhận {msg!r}"
        return msg

    async def read_until_closed(self, timeout: float = 5.0) -> list[dict]:
        """Đọc mọi message tới khi kết nối đóng (EOF/reset/lỗi khung), tối đa `timeout`."""
        out: list[dict] = []
        try:
            async with asyncio.timeout(timeout):
                while True:
                    try:
                        msg = await read_message(self.reader, MAX_PAIRING_MESSAGE_SIZE)
                    except (*CLOSED_ERRORS, asyncio.IncompleteReadError, FramingError, ValueError):
                        break
                    if msg is None:
                        break
                    out.append(msg)
        except TimeoutError:
            raise AssertionError(f"kết nối vẫn mở sau {timeout} s; đã nhận {out!r}") from None
        return out

    async def expect_closed(self, within: float) -> tuple[float, bytes]:
        return await expect_closed(self.reader, within)

    def abort(self) -> None:
        with contextlib.suppress(Exception):
            self.writer.transport.abort()
        with contextlib.suppress(Exception):
            self.writer.close()


def ref_commitment(fp_responder: str, nonce: bytes) -> str:
    """Cam kết của bên trả lời, tính độc lập theo docs/protocol.md §5 (không dùng code `core`)."""
    return hashlib.sha256(b"teleport-commit-v1" + bytes.fromhex(fp_responder) + nonce).hexdigest()


PROOF_LABEL = b"teleport-initiator-proof-v1"


def ref_proof_payload(fp_initiator: str, fp_responder: str, n_a: bytes, commitment: str) -> bytes:
    """Payload bên khởi xướng ký trong `pair_nonce` (protocol 5.2), tính độc lập."""
    return (
        PROOF_LABEL
        + bytes.fromhex(fp_initiator)
        + bytes.fromhex(fp_responder)
        + n_a
        + bytes.fromhex(commitment)
    )


def _private_key(key) -> ec.EllipticCurvePrivateKey:
    """`key`: Identity, đường dẫn file khóa, PEM khóa (bytes) hoặc đối tượng khóa."""
    if isinstance(key, ec.EllipticCurvePrivateKey):
        return key
    if isinstance(key, Identity):
        key = key.key_path
    data = key.read_bytes() if isinstance(key, Path) else key
    return serialization.load_pem_private_key(data, password=None)


def ref_sign(key, payload: bytes) -> bytes:
    """Chữ ký theo đặc tả: ECDSA P-256 + SHA-256, r ‖ s mỗi số 32 byte big-endian (64 byte)."""
    der = _private_key(key).sign(payload, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def ref_verify(cert_pem: str, payload: bytes, signature: bytes) -> bool:
    """Kiểm chữ ký r ‖ s bằng khóa công khai trong `cert_pem`, độc lập với code của trust."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

    if not isinstance(signature, bytes) or len(signature) != 64:
        return False
    r, s = int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big")
    public = x509.load_pem_x509_certificate(cert_pem.encode("ascii")).public_key()
    try:
        public.verify(encode_dss_signature(r, s), payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature:
        return False
    return True


class PairingClient(RawPeer):
    """Client ghép đôi thô (đóng vai bên khởi xướng A), theo luồng bên trả lời cam kết trước:

    `begin` (hello + `pair_request{cert}`) → `read_commit` → `send_nonce` (ký payload, protocol 5.2)
    → `read_reveal` (tự kiểm cam kết bằng fp của server, tính mã). `run_to_code` làm cả chuỗi sau
    `begin`.

    `begin(..., signing_key=...)`: khóa dùng để ký `pair_nonce` (mặc định khóa của `identity`).
    Máy lạ gửi chứng chỉ công khai của máy khác thì truyền khóa của chính nó ở đây.
    """

    identity: Identity
    nonce: bytes
    commitment: str | None = None
    responder_nonce: bytes | None = None
    signing_key: object = None
    last_signature: bytes | None = None
    last_payload: bytes | None = None

    async def begin(
        self, identity: Identity, name: str = "Raw", *, nonce: bytes | None = None, signing_key: object = None
    ) -> None:
        """Đọc hello server, gửi hello và `pair_request` hợp lệ (chỉ có `cert`)."""
        self.identity = identity
        self.nonce = nonce if nonce is not None else secrets.token_bytes(NONCE_SIZE)
        self.commitment = None
        self.responder_nonce = None
        self.signing_key = identity if signing_key is None else signing_key
        self.last_signature = None
        self.last_payload = None
        if self.server_hello is None:
            await self.read_hello()
        self.send_dict(hello_dict(identity, name))
        self.send_dict({"type": "pair_request", "cert": identity.cert_pem()})
        await self.drain()

    @property
    def server_fingerprint(self) -> str:
        """fp của server lấy từ bắt tay TLS của chính kết nối này."""
        der = self.writer.get_extra_info("ssl_object").getpeercert(binary_form=True)
        return hashlib.sha256(der).hexdigest()

    def proof_payload(self, nonce: bytes | None = None) -> bytes:
        commitment = self.commitment if self.commitment is not None else "00" * 32
        n_a = self.nonce if nonce is None else nonce
        return ref_proof_payload(self.identity.fingerprint, self.server_fingerprint, n_a, commitment)

    def nonce_message(self, nonce_hex: str | None = None, *, signature_hex: str | None = None) -> dict:
        """`pair_nonce` đã ký bằng `signing_key` (trên payload của chính n_A gửi đi)."""
        nonce_hex = nonce_hex if nonce_hex is not None else self.nonce.hex()
        if signature_hex is None:
            try:
                n_a = bytes.fromhex(nonce_hex)
            except (ValueError, TypeError):
                n_a = self.nonce
            if len(n_a) != NONCE_SIZE:
                n_a = self.nonce
            payload = self.proof_payload(n_a)
            signature = ref_sign(self.signing_key, payload)
            self.last_payload, self.last_signature = payload, signature
            signature_hex = signature.hex()
        return {"type": "pair_nonce", "nonce": nonce_hex, "signature": signature_hex}

    async def read_commit(self, timeout: float = 3.0) -> str:
        """Đọc `pair_commit` của bên trả lời; trả và nhớ `commitment`."""
        msg = await self.read_type("pair_commit", timeout)
        assert set(msg) == {"type", "commitment"}, f"pair_commit có trường lạ: {msg!r}"
        self.commitment = msg["commitment"]
        return self.commitment

    async def send_nonce(self, nonce_hex: str | None = None, *, signature_hex: str | None = None) -> None:
        """Gửi `pair_nonce` (mặc định n_A của client, ký bằng `signing_key`)."""
        self.send_dict(self.nonce_message(nonce_hex, signature_hex=signature_hex))
        await self.drain()

    async def read_reveal(self, responder_fingerprint: str, timeout: float = 3.0) -> str:
        """Đọc `pair_reveal`, kiểm nó khớp cam kết đã nhận (với fp của server), trả mã 6 số."""
        msg = await self.read_type("pair_reveal", timeout)
        n_b = bytes.fromhex(msg["nonce"])
        assert self.commitment is not None, "nhận pair_reveal trước pair_commit"
        assert ref_commitment(responder_fingerprint, n_b) == self.commitment, "n_B không khớp cam kết"
        self.responder_nonce = n_b
        return self.code_for(responder_fingerprint, msg["nonce"])

    async def run_to_code(self, responder_fingerprint: str, timeout: float = 3.0) -> str:
        """Sau `begin`: commit → nonce → reveal; trả mã."""
        await self.read_commit(timeout)
        await self.send_nonce()
        return await self.read_reveal(responder_fingerprint, timeout)

    def code_for(self, responder_fingerprint: str, reveal_nonce_hex: str) -> str:
        return pairing_code(
            self.identity.fingerprint, responder_fingerprint, self.nonce, bytes.fromhex(reveal_nonce_hex)
        )


class Recorder:
    """Ghi lại callback của một Node: lời hỏi, kết quả, sự kiện `NodeEvent`, kèm thời điểm."""

    def __init__(
        self,
        answer=None,
        *,
        raise_in_prompt: bool = False,
        raise_in_finished: bool = False,
        raise_in_event: bool = False,
    ) -> None:
        self.answer = answer
        self.raise_in_prompt = raise_in_prompt
        self.raise_in_finished = raise_in_finished
        self.raise_in_event = raise_in_event
        self.events: list = []  # NodeEvent theo thứ tự nhận (PR-4)
        self.event_times: list[float] = []  # time.monotonic()
        self.node = None
        self.prompts: list = []
        self.finished: list = []
        self.prompt_times: list[float] = []  # time.monotonic()
        self.prompt_loop_times: list[float] = []  # loop.time()
        self.finished_times: list[float] = []
        self.gate_active_at_finish: list = []
        self.decide_results: list[bool] = []
        self.prompt_event = asyncio.Event()
        self.finished_event = asyncio.Event()

    def on_prompt(self, prompt) -> None:
        self.prompts.append(prompt)
        self.prompt_times.append(time.monotonic())
        self.prompt_loop_times.append(asyncio.get_running_loop().time())
        self.prompt_event.set()
        if callable(self.answer):
            self.answer(prompt)
        elif isinstance(self.answer, bool):
            self.decide_results.append(self.node.pairing.decide(prompt.session_id, self.answer))
        if self.raise_in_prompt:
            raise RuntimeError("lỗi giả lập trong on_prompt")

    def on_finished(self, result) -> None:
        self.finished.append(result)
        self.finished_times.append(time.monotonic())
        with contextlib.suppress(Exception):
            self.gate_active_at_finish.append(self.node.pairing.gate.active)
        self.finished_event.set()
        if self.raise_in_finished:
            raise RuntimeError("lỗi giả lập trong on_finished")

    def on_event(self, event) -> None:
        self.events.append(event)
        self.event_times.append(time.monotonic())
        if self.raise_in_event:
            raise RuntimeError("lỗi giả lập trong on_event")

    def events_of(self, kind: type, device_id: str | None = None) -> list:
        return [
            e
            for e in self.events
            if isinstance(e, kind) and (device_id is None or e.device.device_id == device_id)
        ]

    async def wait_event(
        self, kind: type, device_id: str | None = None, n: int = 1, timeout: float = 5.0
    ) -> object:
        name = getattr(kind, "__name__", str(kind))
        await wait_until(
            lambda: len(self.events_of(kind, device_id)) >= n, timeout, f"chưa có {n} sự kiện {name}"
        )
        return self.events_of(kind, device_id)[n - 1]

    async def wait_prompts(self, n: int = 1, timeout: float = 5.0) -> None:
        await wait_until(lambda: len(self.prompts) >= n, timeout, f"chưa có {n} lời hỏi")

    async def wait_finished(self, n: int = 1, timeout: float = 5.0) -> None:
        await wait_until(lambda: len(self.finished) >= n, timeout, f"chưa có {n} kết quả")


class TransferRecorder:
    """Ghi lại `TransferUpdate` (P2-6b) của một Node theo thứ tự nhận, kèm `time.monotonic()`.

    So loại sự kiện theo **tên lớp** (`"TransferFinished"`…), để conftest không phải import
    `teleport.app.transfers` (module có thể chưa có). `hooks`: hàm gọi đồng bộ với mỗi sự kiện,
    ngay trong callback của Node (test gọi API của `TransferManager` từ đây được: kế hoạch 2.7,
    lời gọi trong lúc dispatch được xếp hàng). Sự kiện của một lượt có thể tới **trước** khi
    `send()` trả `key` (spec-p2-6 B12), nên test lọc theo `transfer_id`, không theo thứ tự.
    """

    def __init__(self, label: str) -> None:
        self.label = label
        self.updates: list = []
        self.times: list[float] = []
        self.hooks: list[Callable[[object], None]] = []
        self.raise_in_event = False

    def on_update(self, update) -> None:
        self.updates.append(update)
        self.times.append(time.monotonic())
        for hook in list(self.hooks):
            hook(update)
        if self.raise_in_event:
            raise RuntimeError("lỗi giả lập trong on_transfer_event")

    @staticmethod
    def key_of(update):
        """`TransferKey` của một sự kiện (`key`, hoặc `info.key`); `DataUnreachable` → None."""
        key = getattr(update, "key", None)
        if key is None:
            key = getattr(getattr(update, "info", None), "key", None)
        return key

    def timed(self, kind: str | type, transfer_id: str | None = None) -> list[tuple[float, object]]:
        name = kind if isinstance(kind, str) else kind.__name__
        out: list[tuple[float, object]] = []
        for t, u in zip(self.times, self.updates, strict=True):
            if type(u).__name__ != name:
                continue
            if transfer_id is not None:
                key = self.key_of(u)
                if key is None or key.transfer_id != transfer_id:
                    continue
            out.append((t, u))
        return out

    def of(self, kind: str | type, transfer_id: str | None = None) -> list:
        return [u for _, u in self.timed(kind, transfer_id)]

    def finished(self, transfer_id: str):
        """`TransferFinished` của lượt (None nếu chưa có)."""
        found = self.of("TransferFinished", transfer_id)
        return found[0] if found else None

    def statuses(self, transfer_id: str) -> list[str]:
        return [str(u.info.status) for u in self.of("TransferStatusChanged", transfer_id)]

    async def wait_kind(
        self, kind: str | type, transfer_id: str | None = None, n: int = 1, timeout: float = 10.0
    ):
        name = kind if isinstance(kind, str) else kind.__name__
        await wait_until(
            lambda: len(self.of(kind, transfer_id)) >= n,
            timeout,
            f"{self.label}: chưa có {n} sự kiện {name} (lượt {transfer_id and transfer_id[:8]})",
        )
        return self.of(kind, transfer_id)[n - 1]

    async def wait_finished(self, transfer_id: str | None = None, timeout: float = 30.0):
        return await self.wait_kind("TransferFinished", transfer_id, 1, timeout)


class AppNode:
    """Bọc một `Node` thật: chuyển mọi thuộc tính tới node, thêm `rec`, `dir`, `label`, `id`.

    `trec`: `TransferRecorder` khi node được tạo qua `transfer_nodes` (P2-6b), không thì None.
    """

    _OWN = frozenset({"node", "rec", "dir", "label", "trec"})

    def __init__(self, node, rec: Recorder, directory: Path, label: str) -> None:
        object.__setattr__(self, "node", node)
        object.__setattr__(self, "rec", rec)
        object.__setattr__(self, "dir", directory)
        object.__setattr__(self, "label", label)
        object.__setattr__(self, "trec", None)

    @property
    def id(self) -> str:
        return self.node.identity.device_id

    def __getattr__(self, name: str):
        return getattr(self.node, name)

    def __setattr__(self, name: str, value) -> None:
        if name in self._OWN:
            object.__setattr__(self, name, value)
        else:
            setattr(self.node, name, value)

    def __repr__(self) -> str:
        return f"<AppNode {self.label}>"


class ControlClient:
    """Kết nối điều khiển phía client, chạy `ControlChannel` trong một task."""

    def __init__(self, conn, task: asyncio.Task, received: list) -> None:
        self.conn = conn
        self.task = task
        self.received = received

    def __iter__(self):
        return iter((self.conn, self.task))

    def pongs(self) -> int:
        return sum(1 for m in self.received if getattr(m, "TYPE", None) == "pong")


class FakeMdnsControl:
    """Bộ điều khiển `FakeMdns` (đặc tả PR-4 mục 4.1).

    - `instances`: mọi `FakeMdns` theo thứ tự tạo; `last`: cái mới nhất.
    - `fail_start` / `fail_advertise`: ngoại lệ ném ra ở `start()` / `advertise()` (giữ tới khi gán None).
    - `close_delay`: `close()` chờ chừng ấy giây (không che chắn khỏi hủy, như yêu cầu nghiêm nhất).
    - `seed`: thiết bị “đã thấy sẵn”, được báo `DeviceAdded` ngay sau `start_browsing` (vòng lặp kế).
    - `local_addresses`: giá trị `teleport.net.discovery.local_ipv4_addresses()` trả về; `addr_reads`
      đếm số lần đọc. Gán một exception để giả lỗi đọc card mạng.
    - `log`: (số thứ tự instance, tên phương thức) theo thứ tự toàn cục (NF6).
    """

    def __init__(self) -> None:
        self.instances: list[FakeMdns] = []
        self.fail_start: BaseException | None = None
        self.fail_advertise: BaseException | None = None
        self.close_delay: float = 0.0
        self.seed: dict = {}
        self.local_addresses: tuple[str, ...] | BaseException = ("192.0.2.5",)
        self.addr_reads = 0
        self.log: list[tuple[int, str]] = []
        self.hang: str | None = None  # tên phương thức async treo mãi (tới khi bị hủy)

    @property
    def last(self) -> FakeMdns:
        assert self.instances, "chưa có FakeMdns nào được tạo"
        return self.instances[-1]

    def of(self, node) -> FakeMdns:
        """Instance đang sống mới nhất mà `node` đã `start_browsing` (theo `self_device_id`)."""
        device_id = node.identity.device_id
        mine = [m for m in self.instances if m.self_device_id == device_id and not m.closing]
        assert mine, f"node {device_id[:8]} không có FakeMdns đang duyệt"
        return mine[-1]

    def read_addresses(self) -> tuple[str, ...]:
        self.addr_reads += 1
        value = self.local_addresses
        if isinstance(value, BaseException):
            raise value
        return tuple(value)


class FakeMdns:
    """Bản giả `teleport.net.discovery.MdnsDiscovery`: không socket, sự kiện do test phát (`emit`)."""

    def __init__(self, ctl: FakeMdnsControl, **kwargs) -> None:
        self.ctl = ctl
        self.kwargs = kwargs
        self.index = len(ctl.instances)
        self.calls: list[str] = []
        self.advertised: list[dict] = []
        self.priorities: list[frozenset[str]] = []
        self.started = False
        self.closing = False  # đã gọi close(): không phát sự kiện nữa
        self.closed = False  # close() đã chạy xong
        self.self_device_id: str | None = None
        self.on_event = None
        self.max_services: int | None = None
        self._devices: dict = {}
        ctl.instances.append(self)

    def _call(self, name: str) -> None:
        self.calls.append(name)
        self.ctl.log.append((self.index, name))

    async def _maybe_hang(self, name: str) -> None:
        if self.ctl.hang == name:
            await asyncio.Event().wait()

    async def start(self) -> None:
        self._call("start")
        await self._maybe_hang("start")
        if self.ctl.fail_start is not None:
            raise self.ctl.fail_start
        self.started = True

    async def close(self) -> None:
        self._call("close")
        self.closing = True
        if self.closed:
            return
        if self.ctl.close_delay:
            await asyncio.sleep(self.ctl.close_delay)
        self.closed = True
        self.ctl.log.append((self.index, "closed"))

    async def advertise(self, **kw) -> None:
        self._call("advertise")
        await self._maybe_hang("advertise")
        if self.ctl.fail_advertise is not None:
            raise self.ctl.fail_advertise
        self.advertised.append(dict(kw))

    async def stop_advertising(self) -> None:
        self._call("stop_advertising")

    async def start_browsing(self, *, self_device_id: str, on_event, max_services: int = 256) -> None:
        self._call("start_browsing")
        await self._maybe_hang("start_browsing")
        self.self_device_id = self_device_id
        self.on_event = on_event
        self.max_services = max_services
        if self.ctl.seed:
            from teleport.core.discovery import DeviceAdded

            seeded = [d for d in self.ctl.seed.values() if d.device_id != self_device_id]
            loop = asyncio.get_running_loop()
            for device in seeded:
                loop.call_soon(self.emit, DeviceAdded(device))

    def set_priority(self, device_ids) -> None:
        self._call("set_priority")
        self.priorities.append(frozenset(device_ids))

    @property
    def devices(self):
        from types import MappingProxyType

        return MappingProxyType(dict(self._devices))

    def emit(self, event) -> None:
        """Cập nhật `devices` rồi gọi `on_event` (như MdnsDiscovery); sau `close()` thì im lặng."""
        from teleport.core.discovery import DeviceRemoved

        if self.closing:
            return
        if isinstance(event, DeviceRemoved):
            self._devices.pop(event.device.device_id, None)
        else:
            self._devices[event.device.device_id] = event.device
        if self.on_event is not None:
            self.on_event(event)


class OpenControlCounter:
    """Bọc `teleport.app.node.open_control`: ghi mọi lời gọi (đặc tả PR-4 mục 4.1).

    Mỗi bản ghi: `SimpleNamespace(t, caller, fingerprint, cert_pem, addresses, port)`; `t` =
    time.monotonic(); `fingerprint` tính từ `expected_cert_pem` (`docs/protocol.md` mục 2.1).
    `rewrite_to="127.0.0.1"` → gọi hàm thật với địa chỉ đó thay cho địa chỉ mDNS (M2).
    """

    def __init__(self, real, rewrite_to: str | None) -> None:
        self.real = real
        self.rewrite_to = rewrite_to
        self.calls: list[SimpleNamespace] = []
        self._sig = inspect.signature(real)

    async def __call__(self, *args, **kwargs):
        bound = self._sig.bind(*args, **kwargs)
        a = bound.arguments
        self.calls.append(
            SimpleNamespace(
                t=time.monotonic(),
                caller=a["identity"].device_id,
                fingerprint=fingerprint_of_pem(a["expected_cert_pem"]),
                cert_pem=a["expected_cert_pem"],
                addresses=tuple(a["addresses"]),
                port=a["port"],
            )
        )
        if self.rewrite_to is not None:
            bound.arguments["addresses"] = [self.rewrite_to]
        return await self.real(*bound.args, **bound.kwargs)

    def count(self, *, to=None, caller=None) -> int:
        return len(self.of(to=to, caller=caller))

    def of(self, *, to=None, caller=None) -> list[SimpleNamespace]:
        """`to`: AppNode / Identity / fingerprint của máy đích; `caller`: AppNode / device_id của máy gọi."""
        if to is None or isinstance(to, str):
            fp = to
        elif isinstance(to, AppNode):
            fp = to.identity.fingerprint
        else:
            fp = to.fingerprint  # Identity
        cid = None if caller is None else (caller if isinstance(caller, str) else caller.identity.device_id)
        return [
            c for c in self.calls if (fp is None or c.fingerprint == fp) and (cid is None or c.caller == cid)
        ]


def make_discovered(
    target,
    *,
    addresses: tuple[str, ...] = (LOCAL,),
    port: int | None = None,
    name: str | None = None,
    os: str = "windows",
    device_id: str | None = None,
):
    """`DiscoveredDevice` trỏ tới `target` (AppNode thật, hoặc Identity khi có `port`)."""
    from teleport.core.discovery import DiscoveredDevice

    if isinstance(target, AppNode):
        did = target.id
        default_name = target.name
        default_port = target.port
    else:
        did = target.device_id
        default_name = "B"
        default_port = None
    return DiscoveredDevice(
        device_id=device_id or did,
        name=name or default_name,
        os=os,
        proto=PROTOCOL_VERSION,
        port=port if port is not None else default_port,
        addresses=tuple(addresses),
    )


async def find_leaks(before: set[asyncio.Task]) -> list[str]:
    problems: list[str] = []
    await asyncio.sleep(0.05)
    current = asyncio.current_task()
    leftover = [t for t in asyncio.all_tasks() if t is not current and t not in before and not t.done()]
    named = [t for t in leftover if t.get_name().startswith(("teleport.pairing", "teleport.node"))]
    problems += [f"task của app còn chạy: {t.get_name()} {t.get_coro()!r}" for t in named]
    problems += [f"task còn chạy: {t.get_name()} {t.get_coro()!r}" for t in leftover if t not in named]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        gc.collect()
    problems += [f"ResourceWarning: {w.message}" for w in caught if issubclass(w.category, ResourceWarning)]
    return problems


# --- Lưu trạng thái nối lại (P3-3a, specs/spec-p3-3a.md) -----------------------------------------

# `device_id` mặc định của `record_for`: máy nhận (máy này) và máy gửi.
RECORD_RECEIVER = "e" * 32
RECORD_SENDER = "a" * 32
RECORD_MTIME = 1_700_000_000_000
RECORD_DONE_AT = datetime.datetime(2026, 10, 27, 10, 0, 0, tzinfo=datetime.UTC)
# Bố cục thư mục tạm một lượt, chép nguyên văn từ spec-p3 mục 2.2 (luôn dùng `fullmatch`).
LAYOUT_PATTERN = (
    r"^(transfer\.json|(0|[1-9][0-9]{0,2})\.(part|state)"
    r"|(transfer\.json|(0|[1-9][0-9]{0,2})\.state)\.[0-9a-f]{16}\.tmp)$"
)
_STATE_HEADER_LEN = 41  # architecture mục 4: header `.state` 41 byte


def record_for(
    tid: str,
    sizes,
    *,
    verified: int = 0,
    receiver: str = RECORD_RECEIVER,
    sender: str = RECORD_SENDER,
    names=None,
    done_at: datetime.datetime | None = None,
):
    """`TransferRecord` của lượt `tid` khớp các `size` của part (spec-p3-3a mục 8.1 (c)).

    `sizes`: list `size` theo `file_index`, hoặc dict `{file_index: size}` (các index khác có size 0,
    số file = index lớn nhất + 1). `verified` = số file → `done_at` mặc định `RECORD_DONE_AT`.
    """
    from teleport.core.blocks import BLOCK_SIZE
    from teleport.core.messages import FileEntry, Offer
    from teleport.core.resume_state import TransferRecord

    if isinstance(sizes, dict):
        count = max(sizes) + 1
        sizes = [sizes.get(i, 0) for i in range(count)]
    sizes = list(sizes)
    if names is None:
        names = [f"f{i}.bin" for i in range(len(sizes))]
    files = tuple(FileEntry(name, size, RECORD_MTIME) for name, size in zip(names, sizes, strict=True))
    offer = Offer(transfer_id=tid, block_size=BLOCK_SIZE, files=files)
    if done_at is None and verified == len(files):
        done_at = RECORD_DONE_AT
    return TransferRecord(receiver=receiver, sender=sender, offer=offer, verified=verified, done_at=done_at)


def parse_state(data: bytes) -> tuple[bytes, list[tuple]]:
    """Tách `.state` thành (header 41 byte, các bản ghi) theo architecture mục 4, độc lập với code.

    Bản ghi: `("mark", [(index, sha256), …])`, `("clear", [index, …])`, `("clear_all",)`,
    `("target", tên)`, `("reserved", tên)`. Bản ghi cụt, sai crc32 hay loại lạ → AssertionError.
    """
    import struct
    import zlib

    assert len(data) >= _STATE_HEADER_LEN, f".state ngắn hơn header: {len(data)} byte"
    header = data[:_STATE_HEADER_LEN]
    records: list[tuple] = []
    pos = _STATE_HEADER_LEN
    while pos < len(data):
        kind = data[pos]
        if kind == 0x03:
            length = 5
        else:
            assert kind in (0x01, 0x02, 0x04, 0x05), f"loại bản ghi lạ {kind:#x} ở byte {pos}"
            assert pos + 3 <= len(data), f"bản ghi cụt ở byte {pos}"
            (n,) = struct.unpack_from("!H", data, pos + 1)
            length = 7 + n * {0x01: 36, 0x02: 4, 0x04: 1, 0x05: 1}[kind]
        assert pos + length <= len(data), f"bản ghi cụt ở byte {pos}"
        body = data[pos : pos + length - 4]
        (crc,) = struct.unpack_from("!I", data, pos + length - 4)
        assert crc == zlib.crc32(body), f"sai crc32 ở byte {pos}"
        payload = body[3:]
        if kind == 0x01:
            records.append(("mark", [(i, h) for i, h in struct.iter_unpack("!I32s", payload)]))
        elif kind == 0x02:
            records.append(("clear", [i for (i,) in struct.iter_unpack("!I", payload)]))
        elif kind == 0x03:
            records.append(("clear_all",))
        else:
            records.append(("target" if kind == 0x04 else "reserved", payload.decode("utf-8")))
        pos += length
    return header, records


def tree_snapshot(top) -> dict[str, tuple]:
    """Mọi mục dưới `top`, không theo liên kết: loại, kích thước, SHA-256, `st_mtime_ns` (file), đích link."""
    import os

    result: dict[str, tuple] = {}

    def visit(path: str, rel: str) -> None:
        with os.scandir(path) as it:
            found = sorted(it, key=lambda e: e.name)
        for entry in found:
            name = f"{rel}/{entry.name}"
            if entry.is_symlink() or entry.is_junction():
                result[name] = ("link", os.readlink(entry.path))
            elif entry.is_dir(follow_symlinks=False):
                result[name] = ("dir",)
                visit(entry.path, name)
            else:
                with open(entry.path, "rb") as f:
                    content = f.read()
                st = os.lstat(entry.path)
                result[name] = ("file", len(content), hashlib.sha256(content).hexdigest(), st.st_mtime_ns)

    visit(os.fspath(top), "")
    return result


def crash_copy(root, dest) -> Path:
    """“Sập” (spec-p3-3a mục 4): chép cây thư mục nhận `root` sang `dest`, giữ mtime, không theo link.

    Gọi trong seam: bản chép là đĩa sau khi sập đúng ở điểm đó. Test mở bản chép bằng `ReceiveDir` mới.
    """
    import shutil

    shutil.copytree(root, dest, symlinks=True, copy_function=shutil.copy2)
    return Path(dest)


def block_hashes(data: bytes) -> list[bytes]:
    """SHA-256 từng khối 1 MiB của `data` (khối cuối có thể ngắn)."""
    from teleport.core.blocks import BLOCK_SIZE, block_count

    return [
        hashlib.sha256(data[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]).digest()
        for i in range(block_count(len(data)))
    ]


def write_blocks(part, data: bytes, indices=None) -> list[tuple[int, bytes]]:
    """Ghi các khối `indices` (mặc định mọi khối) của `data` vào `part`; trả `(index, sha256)` để `commit`."""
    from teleport.core.blocks import BLOCK_SIZE, block_count

    if indices is None:
        indices = range(block_count(len(data)))
    out = []
    for i in indices:
        chunk = data[i * BLOCK_SIZE : (i + 1) * BLOCK_SIZE]
        part.write_at(i, chunk)
        out.append((i, hashlib.sha256(chunk).digest()))
    return out


# --- Fixture -------------------------------------------------------------------------------------


@pytest.fixture(name="record_for", scope="session")
def record_for_fixture():
    """`record_for(tid, sizes, *, verified=0, receiver=…, sender=…, names=None, done_at=None)`.

    Bản ghi `transfer.json` cho `ReceiveDir.create_temp(tid, record)` (spec-p3-3a mục 4 V1, 8.1).
    Phạm vi session (hàm thuần) để dùng được trong test `hypothesis`.
    """
    return record_for


@pytest.fixture(scope="session")
def resume_helpers():
    """Hàm và hằng phụ trợ cho test `.state` / `transfer.json` / dọn tạm (P3-3a)."""
    import re

    return SimpleNamespace(
        RECEIVER=RECORD_RECEIVER,
        SENDER=RECORD_SENDER,
        MTIME=RECORD_MTIME,
        DONE_AT=RECORD_DONE_AT,
        LAYOUT_PATTERN=LAYOUT_PATTERN,
        LAYOUT_RE=re.compile(LAYOUT_PATTERN),
        record_for=record_for,
        parse_state=parse_state,
        snapshot=tree_snapshot,
        crash_copy=crash_copy,
        block_hashes=block_hashes,
        write_blocks=write_blocks,
    )


class PayloadMeter:
    """Đếm byte payload bên gửi giao cho kết nối dữ liệu, qua seam `Connection.write_block` (fixture
    `payload_meter`). Đếm payload của mỗi lần gọi **ngay khi gọi** (kể cả lần ghi bị cắt giữa chừng hay
    thất bại), nên `sent` là cận trên của byte thật sự đã đi: kiểm mvp N4 theo số này là kiểm chặt hơn.

    `sent`, `calls`; `log`: chỉ số khối của mỗi lần gọi, theo thứ tự (mọi kết nối, mọi node trong tiến
    trình; test một file nên chỉ số khối đủ phân biệt); `hooks`: hàm `(meter)` gọi đồng bộ (trong event
    loop của node) sau mỗi lần cộng. `pos()` → vị trí hiện tại của `log`; `counts(since=0)` → `Counter`
    chỉ số khối → số lần gửi kể từ vị trí đó.
    """

    def __init__(self) -> None:
        self.sent = 0
        self.calls = 0
        self.log: list[int] = []
        self.hooks: list[Callable[[PayloadMeter], None]] = []

    def pos(self) -> int:
        return len(self.log)

    def counts(self, since: int = 0):
        from collections import Counter

        return Counter(self.log[since:])


@pytest.fixture
def payload_meter(monkeypatch):
    """`PayloadMeter` đếm payload bên gửi qua `Connection.write_block` (spec-p3-5 V3; trước ở
    `tests/app/test_transfer_reconnect.py`)."""
    from teleport.net import connection

    meter = PayloadMeter()
    real = connection.Connection.write_block

    async def write_block(self, index, sha256, payload, *args, **kwargs):
        meter.sent += memoryview(payload).nbytes
        meter.calls += 1
        meter.log.append(index)
        for hook in list(meter.hooks):
            hook(meter)
        return await real(self, index, sha256, payload, *args, **kwargs)

    monkeypatch.setattr(connection.Connection, "write_block", write_block)
    return meter


@pytest.fixture
def short_keepalive(monkeypatch):
    """`short_keepalive(dead_after=1.5, ping_interval=None)` → `SimpleNamespace(dead_after, ping_interval)`.

    Keepalive rút ngắn cho test nối lại (spec-p3-5 V3, N2): thay `teleport.app.node.ControlChannel` bằng
    lớp con có `ping_interval`/`dead_after` cho trước (hằng keepalive là giá trị mặc định của tham số nên
    vá hằng không có tác dụng, `architecture.md` §6). `ping_interval` mặc định `dead_after / 6`. Gọi
    trước khi node nối kết nối điều khiển; gọi lại thì giá trị mới thay giá trị cũ.
    """
    from teleport.app import node as node_mod
    from teleport.net import connection

    def install(dead_after: float = 1.5, ping_interval: float | None = None) -> SimpleNamespace:
        ping = dead_after / 6 if ping_interval is None else ping_interval

        class ShortKeepaliveChannel(connection.ControlChannel):
            def __init__(self, conn, *, ping_interval: float = ping, dead_after: float = dead_after) -> None:
                super().__init__(conn, ping_interval=ping_interval, dead_after=dead_after)

        monkeypatch.setattr(node_mod, "ControlChannel", ShortKeepaliveChannel)
        return SimpleNamespace(dead_after=dead_after, ping_interval=ping)

    return install


@pytest.fixture
def fake_mdns(monkeypatch):
    """Thay `teleport.app.node.MdnsDiscovery` bằng `FakeMdns`; trả `FakeMdnsControl`.

    Cũng thay `teleport.net.discovery.local_ipv4_addresses` (node đọc qua thuộc tính module) bằng
    `ctl.read_addresses`, để việc theo dõi mạng không phụ thuộc card mạng thật của máy chạy test.
    """
    from teleport.app import node as app_node
    from teleport.net import discovery as net_discovery

    ctl = FakeMdnsControl()

    def factory(*args, **kwargs):
        assert not args, f"MdnsDiscovery phải được tạo bằng đối số từ khóa, nhận {args!r}"
        return FakeMdns(ctl, **kwargs)

    monkeypatch.setattr(app_node, "MdnsDiscovery", factory)
    monkeypatch.setattr(net_discovery, "local_ipv4_addresses", ctl.read_addresses)
    return ctl


@pytest.fixture
def count_open_control(monkeypatch):
    """`count_open_control(rewrite_to=None)` → `OpenControlCounter` đã cài vào `teleport.app.node`."""
    from teleport.app import node as app_node

    installed: list[OpenControlCounter] = []

    def install(rewrite_to: str | None = None) -> OpenControlCounter:
        real = installed[0].real if installed else app_node.open_control
        counter = OpenControlCounter(real, rewrite_to)
        monkeypatch.setattr(app_node, "open_control", counter)
        installed.append(counter)
        return counter

    return install


_LABEL = object()


@pytest.fixture
async def node_factory(fast, tmp_path):
    """`await node_factory("A", accept_pairing=False, name=None, answer=None, ...)` → `AppNode`.

    Node ở `tmp_path / label`, nghe `127.0.0.1`, cổng 0 (mặc định), luôn được `close()` khi test
    xong; sau đó kiểm `node.lock` của mọi thư mục đã chạy đều lấy lại được ngay.
    `answer=True/False` → trong `on_prompt` gọi `decide`; `answer=callable` → gọi với prompt.
    `hostname=True` → truyền `name=None` cho Node (tên lấy từ hostname).
    `prompt=False` → truyền `on_pairing_prompt=None` (node không ghép đôi được; kế hoạch L1).
    `auto_connect_to=device_id` → chỉ tự nối tới thiết bị đó (P2-6a; chỉ truyền khi khác None).
    `node_kwargs={...}` → truyền thêm cho `Node` (P2-6b: `receive_dir`, `auto_accept`, `rate_limit`,
    `on_transfer_event`); ghi đè các đối số trên nếu trùng tên.
    """
    from teleport.app.node import Node

    created: list[AppNode] = []
    started_dirs: set[Path] = set()

    async def make(
        label: str,
        *,
        accept_pairing: bool = False,
        name: str | None = None,
        answer=None,
        port: int | None = 0,
        host: str = LOCAL,
        start: bool = True,
        hostname: bool = False,
        raise_in_prompt: bool = False,
        raise_in_finished: bool = False,
        mdns=None,
        auto_connect: bool = True,
        raise_in_event: bool = False,
        prompt: bool = True,
        auto_connect_to: str | None = None,
        node_kwargs: dict | None = None,
    ) -> AppNode:
        directory = tmp_path / label
        rec = Recorder(
            answer,
            raise_in_prompt=raise_in_prompt,
            raise_in_finished=raise_in_finished,
            raise_in_event=raise_in_event,
        )
        # PR-4: `mdns`/`auto_connect` chỉ truyền khi khác mặc định; `on_event` luôn ghi vào `rec.events`.
        extra: dict = {"on_event": rec.on_event}
        if mdns is not None:
            extra["mdns"] = mdns
        if auto_connect is not True:
            extra["auto_connect"] = auto_connect
        if auto_connect_to is not None:
            extra["auto_connect_to"] = auto_connect_to
        extra.update(node_kwargs or {})
        node = Node(
            directory,
            name=None if hostname else (name or label),
            port=port,
            host=host,
            accept_pairing=accept_pairing,
            on_pairing_prompt=rec.on_prompt if prompt else None,
            on_pairing_finished=rec.on_finished,
            **extra,
        )
        rec.node = node
        handle = AppNode(node, rec, directory, label)
        created.append(handle)
        if start:
            await node.start()
            started_dirs.add(directory)
        return handle

    yield make

    for handle in reversed(created):
        await asyncio.wait_for(handle.node.close(), 20)
    still_locked = [str(d) for d in started_dirs if not lock_is_free(d)]
    assert not still_locked, f"node.lock chưa được nhả sau close(): {still_locked}"


@pytest.fixture
def trust_each_other(tmp_path):
    """`trust_each_other(a, b, name_a="A", name_b="B")`: hai thư mục (Path hoặc nhãn) tin nhau.

    Gọi **trước** khi start node: tạo danh tính hai bên rồi ghi `trusted.json` của từng bên.
    """

    def run(a: Path | str, b: Path | str, name_a: str = "A", name_b: str = "B") -> tuple[Identity, Identity]:
        dir_a = a if isinstance(a, Path) else tmp_path / a
        dir_b = b if isinstance(b, Path) else tmp_path / b
        id_a, id_b = ensure_identity(dir_a), ensure_identity(dir_b)
        TrustStore.load(dir_a).add(peer_cert_from_pem(id_b.cert_pem()), name_b)
        TrustStore.load(dir_b).add(peer_cert_from_pem(id_a.cert_pem()), name_a)
        return id_a, id_b

    return run


# Khóa của `transfer_nodes(receiver_opts, sender_opts)` đi vào `node_factory`; còn lại là đối số của `Node`.
_FACTORY_KEYS = frozenset(
    {"mdns", "auto_connect", "auto_connect_to", "name", "port", "accept_pairing", "answer", "prompt", "start"}
)


@pytest.fixture
async def transfer_nodes(node_factory, trust_each_other, tmp_path, monkeypatch, fast):
    """P2-6b (kế hoạch mục 4, việc 6b-T0): hai node tin nhau, A **nhận**, B **gửi**.

    `net = await transfer_nodes(receiver_opts=None, sender_opts=None, client="sender")`:

    - Node `A` mặc định `receive_dir=tmp_path/"nhan-A"`, `auto_accept=True`; `B` không có thư mục
      nhận. `receiver_opts` / `sender_opts` ghi đè (vd. `{"receive_dir": None}`, `{"rate_limit": n}`,
      `{"mdns": MdnsOptions()}`); khóa của `node_factory` (`mdns`, `auto_connect`…) đi vào đó.
    - Cả hai có `on_transfer_event` ghi vào `node.trec` (`TransferRecorder`), trừ khi opts tự đưa.
    - `mdns=None` (mặc định của `node_factory`): nối bằng `connect_hint` theo chiều `client`:
      `"sender"` → B mở kết nối điều khiển tới A; `"receiver"` → A mở tới B. Kết nối dữ liệu đi theo
      chiều đó (protocol §4.1). `connect=False` → chưa nối; gọi `await net.connect()` sau.
    - `extra_trusted=("C",)` → A và C tin nhau (ghi trước khi start; test tự tạo C bằng `node_factory`).
    - `connection.DRAIN_TIMEOUT` = 10 s (spec-p2-6 B12), vá trước khi tạo node.

    `net`: `A`, `B` (`AppNode`), `receive_dir`, `src` (thư mục tạo file nguồn), `client`, `connect`.
    """
    from teleport.net import connection

    monkeypatch.setattr(connection, "DRAIN_TIMEOUT", fast.TRANSFER_DRAIN_TIMEOUT)

    async def start(label: str, opts: dict) -> AppNode:
        trec = TransferRecorder(label)
        factory_kw = {k: v for k, v in opts.items() if k in _FACTORY_KEYS}
        node_kw = {k: v for k, v in opts.items() if k not in _FACTORY_KEYS}
        node_kw.setdefault("on_transfer_event", trec.on_update)
        handle = await node_factory(label, node_kwargs=node_kw, **factory_kw)
        handle.trec = trec
        return handle

    async def make(
        receiver_opts: dict | None = None,
        sender_opts: dict | None = None,
        client: str = "sender",
        *,
        connect: bool = True,
        extra_trusted: tuple[str, ...] = (),
    ) -> SimpleNamespace:
        if client not in ("sender", "receiver"):
            raise ValueError("client phải là 'sender' hoặc 'receiver'")
        trust_each_other("A", "B")
        for label in extra_trusted:
            trust_each_other("A", label, name_b=label)
        r_opts: dict = {"receive_dir": tmp_path / "nhan-A", "auto_accept": True}
        r_opts.update(receiver_opts or {})
        s_opts: dict = dict(sender_opts or {})
        A = await start("A", r_opts)
        B = await start("B", s_opts)
        src = tmp_path / "nguon"
        src.mkdir(exist_ok=True)

        async def do_connect() -> None:
            opener, other = (B, A) if client == "sender" else (A, B)
            opener.connect_hint(other.id, [LOCAL], other.port)
            # 15 s: runner CI chạy -n auto có lúc mất quá 5 s mới xong bắt tay TLS hai chiều.
            await wait_until(
                lambda: other.id in opener.connected_devices() and opener.id in other.connected_devices(),
                15,
                f"{opener.label} chưa nối được kết nối điều khiển tới {other.label}",
            )

        net = SimpleNamespace(
            A=A, B=B, receive_dir=r_opts.get("receive_dir"), src=src, client=client, connect=do_connect
        )
        if connect:
            await do_connect()
        return net

    return make


@pytest.fixture
async def raw_pairing_client():
    """`await raw_pairing_client(port, read_hello=True)` → `PairingClient` ẩn danh; tự abort khi xong."""
    peers: list[RawPeer] = []

    async def connect(port: int, *, read_hello: bool = True) -> PairingClient:
        peer = await PairingClient.connect(port)
        peers.append(peer)
        if read_hello:
            await peer.read_hello()
        return peer

    yield connect

    for peer in peers:
        peer.abort()
    await asyncio.sleep(0)


@pytest.fixture
async def raw_client():
    """`await raw_client(port, identity=None, use_tls=True)` → `RawPeer` (chưa đọc gì)."""
    peers: list[RawPeer] = []

    async def connect(port: int, identity: Identity | None = None, *, use_tls: bool = True) -> RawPeer:
        peer = await RawPeer.connect(port, identity, use_tls=use_tls)
        peers.append(peer)
        return peer

    yield connect

    for peer in peers:
        peer.abort()
    await asyncio.sleep(0)


@pytest.fixture
async def control_client(node_factory):
    """`await control_client(node_from, node_to, ping_interval=0.2)` → `ControlClient`.

    `open_control` từ danh tính của `node_from` tới cổng của `node_to`, rồi chạy `ControlChannel`
    phía client trong một task. Phụ thuộc `node_factory` để được dọn **trước** khi node đóng.
    """
    from teleport.net.connection import ControlChannel, open_control

    clients: list[ControlClient] = []

    async def make(
        node_from, node_to, *, ping_interval: float = 0.2, dead_after: float = 5.0
    ) -> ControlClient:
        conn = await open_control(
            [LOCAL], node_to.port, node_from.identity, node_from.hello, node_to.identity.cert_pem()
        )
        received: list = []
        channel = ControlChannel(conn, ping_interval=ping_interval, dead_after=dead_after)
        task = asyncio.create_task(channel.run(received.append), name="test.control-client")
        client = ControlClient(conn, task, received)
        clients.append(client)
        return client

    yield make

    for client in clients:
        client.task.cancel()
    for client in clients:
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(client.task, 5)
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(client.conn.close(), 5)


@pytest.fixture
async def fake_server():
    """`await fake_server(identity, script)` → cổng của server TLS giả chạy `script(reader, writer)`."""
    servers: list[asyncio.Server] = []
    writers: list[asyncio.StreamWriter] = []
    tasks: set[asyncio.Task] = set()

    async def make(
        identity: Identity | None,
        script: Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]],
        *,
        use_tls: bool = True,
    ) -> int:
        ctx = tls.server_context(identity, [], allow_anonymous=True) if use_tls else None

        async def handle(reader, writer):
            writers.append(writer)
            task = asyncio.current_task()
            tasks.add(task)
            try:
                await script(reader, writer)
            except (*CLOSED_ERRORS, asyncio.IncompleteReadError):
                pass
            finally:
                tasks.discard(task)

        server = await asyncio.start_server(handle, LOCAL, 0, ssl=ctx)
        servers.append(server)
        return server.sockets[0].getsockname()[1]

    yield make

    for server in servers:
        server.close()
    for task in list(tasks):
        task.cancel()
    for writer in writers:
        with contextlib.suppress(Exception):
            writer.transport.abort()
        with contextlib.suppress(Exception):
            writer.close()
    if tasks:
        await asyncio.wait(list(tasks), timeout=2)
    for server in servers:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(server.wait_closed(), 2)


@pytest.fixture
def app_helpers(fast_values):
    """Hàm và lớp phụ trợ (test không import được conftest)."""
    return SimpleNamespace(
        FAST=fast_values,
        LOCAL=LOCAL,
        CLOSED_ERRORS=CLOSED_ERRORS,
        wait_until=wait_until,
        expect_closed=expect_closed,
        free_port=free_port,
        busy_port=busy_port,
        hello_dict=hello_dict,
        frame=frame,
        fake_cert_with_cn=fake_cert_with_cn,
        SAN_X400=SAN_X400,
        SAN_EDI=SAN_EDI,
        cert_with_raw_san=cert_with_raw_san,
        cert_client_context=cert_client_context,
        fingerprint_of_pem=fingerprint_of_pem,
        identity_from_pem=identity_from_pem,
        identity_below=identity_below,
        ensure_identity=ensure_identity,
        seed_trust=seed_trust,
        lock_is_free=lock_is_free,
        find_leaks=find_leaks,
        new_device_id=lambda: uuid.uuid4().hex,
        read_message=read_message,
        encode_message=encode_message,
        dev=make_discovered,
        ref_commitment=ref_commitment,
        ref_proof_payload=ref_proof_payload,
        ref_sign=ref_sign,
        ref_verify=ref_verify,
        TransferRecorder=TransferRecorder,
    )


@pytest.fixture
async def no_leaks(request):
    """Sau test async: không còn task mới nào (kể cả `teleport.pairing*`, `teleport.node*`,
    `teleport.connection*`), không có socket chưa đóng. Test đồng bộ thì bỏ qua."""
    if not inspect.iscoroutinefunction(request.function):
        yield
        return
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", ResourceWarning)
        gc.collect()
    before = asyncio.all_tasks()
    yield
    problems = await find_leaks(before)
    assert not problems, "rò rỉ sau test:\n" + "\n".join(problems)
