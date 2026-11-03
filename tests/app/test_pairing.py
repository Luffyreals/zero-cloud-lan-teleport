"""Test `teleport.app.pairing` theo đặc tả PR-3 mục 2.4, 3.1–3.3, 3.8 và 4.5 (P1–P27).

Phần lớn là integration: 2–3 `Node` thật trên 127.0.0.1 (fixture `node_factory`, hằng thời gian đã
rút ngắn bằng `fast`), cộng client/server thô để thử dữ liệu độc. Mọi test kết thúc bằng `no_leaks`
(không còn task `teleport.*`, không socket nào bị bỏ rơi) và kiểm `node.lock` đã nhả (trong
`node_factory`). Ngoài ra có thêm vài ca theo đặc tả mà bảng 4.5 không đánh số (P-map, P-busy, …).
"""

import asyncio
import contextlib
import datetime
import hashlib
import logging
import os
import re
import secrets
import time

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from support import wait_until

from teleport.app.pairing import PairingFinished, PairingOutcome, PairingPrompt, PairingService
from teleport.core.framing import HEADER, encode_message
from teleport.core.messages import PROTOCOL_VERSION, Hello
from teleport.core.pairing import Outcome, Role
from teleport.core.pairing_code import format_code, pairing_code
from teleport.net.connection import ConnectionLostError
from teleport.net.stream import read_message
from teleport.trust.identity import IdentityError, load_or_create_identity, peer_cert_from_pem
from teleport.trust.store import TrustStore, TrustStoreError

pytestmark = [
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]
integration = pytest.mark.integration

LOCAL = "127.0.0.1"
INVALID = {"type": "pair_abort", "reason": "invalid"}
GARBAGE_PEM = "-----BEGIN CERTIFICATE-----\nAAAA\n-----END CERTIFICATE-----\n"


def ref_commitment(fp_responder: str, nonce: bytes) -> str:
    """Cam kết của bên trả lời, tính độc lập theo docs/protocol.md §5."""
    return hashlib.sha256(b"teleport-commit-v1" + bytes.fromhex(fp_responder) + nonce).hexdigest()


def ref_proof_payload(fp_initiator: str, fp_responder: str, n_a: bytes, commitment: str) -> bytes:
    """Payload ký trong `pair_nonce` (protocol 5.1–5.2), tính độc lập."""
    return (
        b"teleport-initiator-proof-v1"
        + bytes.fromhex(fp_initiator)
        + bytes.fromhex(fp_responder)
        + n_a
        + bytes.fromhex(commitment)
    )


def ref_sign(key_path, payload: bytes) -> bytes:
    """ECDSA P-256 + SHA-256 bằng khóa trong `key_path`, mã hóa r ‖ s (64 byte)."""
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    r, s_ = decode_dss_signature(key.sign(payload, ec.ECDSA(hashes.SHA256())))
    return r.to_bytes(32, "big") + s_.to_bytes(32, "big")


async def pair(a, b, timeout: float = 15.0) -> PairingFinished:
    return await asyncio.wait_for(a.pairing.pair_with([LOCAL], b.port), timeout)


def outcomes(rec) -> list[str]:
    return [str(f.outcome) for f in rec.finished]


def gates_idle(*nodes) -> bool:
    return all(n.pairing.gate.active is None for n in nodes)


# --- Unit: kiểu dữ liệu, tham số ----------------------------------------------------------------


def test_outcome_values_cover_core_outcome_plus_app_only():
    """`PairingOutcome` = mọi giá trị của `core.pairing.Outcome` + 8 kết quả chỉ `app` biết
    (`prompt_failed`: kế hoạch L1)."""
    core_values = {o.value for o in Outcome}
    app_only = {
        "unreachable",
        "rejected",
        "identity_mismatch",
        "version_mismatch",
        "busy",
        "self",
        "save_failed",
        "prompt_failed",
    }
    assert {o.value for o in PairingOutcome} == core_values | app_only
    for value in core_values:
        assert PairingOutcome(value).value == value


def _required(cls, name: str) -> bool:
    import dataclasses

    field = next(f for f in dataclasses.fields(cls) if f.name == name)
    return field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING


def test_prompt_and_finished_are_frozen_dataclasses():
    import dataclasses

    assert dataclasses.is_dataclass(PairingPrompt) and dataclasses.is_dataclass(PairingFinished)
    names = [f.name for f in dataclasses.fields(PairingPrompt)]
    assert set(names) == {
        "session_id",
        "role",
        "address",
        "peer_name",
        "peer_device_id",
        "code",
        "expires_at",
        "recent_codes",
        "known_name",
    }
    # Trường mới đặt cuối: recent_codes (L4 đợt trước), rồi known_name (M5).
    assert names[-2:] == ["recent_codes", "known_name"]
    assert _required(PairingPrompt, "recent_codes"), "recent_codes là trường bắt buộc"
    assert _required(PairingPrompt, "known_name"), "known_name là trường bắt buộc"
    names = [f.name for f in dataclasses.fields(PairingFinished)]
    assert set(names) == {
        "session_id",
        "role",
        "outcome",
        "address",
        "port",
        "peer_name",
        "peer_device_id",
        "peer_reason",
        "device",
        "known_name",
        "code_shown",
    }
    assert names[-1] == "code_shown"  # L4: trường mới đặt cuối
    assert _required(PairingFinished, "code_shown"), "code_shown là trường bắt buộc"
    for cls in (PairingPrompt, PairingFinished):
        assert cls.__dataclass_params__.frozen, f"{cls.__name__} phải là frozen dataclass"


@pytest.fixture
def service_parts(tmp_path):
    identity = load_or_create_identity(tmp_path / "svc")
    hello = Hello(PROTOCOL_VERSION, identity.device_id, "Svc", "0.0.0", "windows")
    store = TrustStore.load(tmp_path / "svc")
    finished: list = []
    return identity, hello, store, finished


def make_service(parts, **kwargs) -> PairingService:
    identity, hello, store, finished = parts
    return PairingService(
        identity=identity,
        hello=kwargs.pop("hello", hello),
        store=store,
        on_prompt=kwargs.pop("on_prompt", lambda p: None),
        on_finished=finished.append,
        on_trust_changed=lambda: None,
        **kwargs,
    )


async def test_service_rejects_hello_of_other_identity(service_parts, tmp_path):
    other = load_or_create_identity(tmp_path / "khac")
    bad = Hello(PROTOCOL_VERSION, other.device_id, "Svc", "0.0.0", "windows")
    with pytest.raises(ValueError):
        make_service(service_parts, hello=bad)


async def test_service_accepting_maps_to_gate(service_parts):
    svc = make_service(service_parts)
    try:
        assert svc.accepting is False and svc.gate.accepting is False
        svc.accepting = True
        assert svc.gate.accepting is True
        svc2 = make_service(service_parts, accepting=True)
        assert svc2.accepting is True
        await svc2.close()
        assert svc2.accepting is False
    finally:
        await svc.close()


@pytest.mark.parametrize(
    ("addresses", "port"),
    [
        ("127.0.0.1", 47474),
        (b"127.0.0.1", 47474),
        ([], 47474),
        (["localhost"], 47474),
        (["0.0.0.0"], 47474),
        (["224.0.0.251"], 47474),
        (["255.255.255.255"], 47474),
        (["01.2.3.4"], 47474),
        (["127.0.0.1", "0.0.0.0"], 47474),
        ([f"10.0.0.{i}" for i in range(1, 18)], 47474),
        ([None], 47474),
        (["127.0.0.1"], 0),
        (["127.0.0.1"], 65536),
        (["127.0.0.1"], True),
        (["127.0.0.1"], "47474"),
        (["127.0.0.1"], 47474.0),
    ],
)
async def test_pair_with_validates_arguments_before_io(service_parts, monkeypatch, addresses, port):
    """3.1 bước 1: sai → ValueError trước mọi I/O và trước khi giữ slot; không gọi on_finished."""
    from teleport.app import pairing as app_pairing

    async def no_io(*args, **kwargs):
        raise AssertionError("không được mở kết nối khi tham số sai")

    if hasattr(app_pairing, "open_pairing"):
        monkeypatch.setattr(app_pairing, "open_pairing", no_io)
    svc = make_service(service_parts)
    try:
        with pytest.raises(ValueError):
            await svc.pair_with(addresses, port)
        assert service_parts[3] == []
        assert svc.gate.active is None
    finally:
        await svc.close()


async def test_pair_with_after_close_returns_cancelled_without_connecting(service_parts, monkeypatch):
    """2.4 `close()`: sau đó `pair_with` trả ngay CANCELLED, session_id None, vẫn gọi on_finished."""
    from teleport.app import pairing as app_pairing

    async def no_io(*args, **kwargs):
        raise AssertionError("không được mở kết nối sau close()")

    if hasattr(app_pairing, "open_pairing"):
        monkeypatch.setattr(app_pairing, "open_pairing", no_io)
    svc = make_service(service_parts, accepting=True)
    await svc.close()
    await svc.close()  # gọi nhiều lần không lỗi
    result = await asyncio.wait_for(svc.pair_with([LOCAL], 47474), 2)
    assert result.outcome == PairingOutcome.CANCELLED
    assert result.session_id is None
    assert result.role == Role.INITIATOR
    assert result.address == LOCAL and result.port == 47474
    assert service_parts[3] == [result]
    assert svc.accepting is False


def test_decide_rejects_non_bool(service_parts):
    """P24 (phần unit): `accepted` không phải bool → ValueError; id lạ → False."""

    async def run():
        svc = make_service(service_parts)
        try:
            assert svc.decide(12345, True) is False
            with pytest.raises(ValueError):
                svc.decide(12345, 1)
            with pytest.raises(ValueError):
                svc.decide(12345, None)
        finally:
            await svc.close()

    asyncio.run(run())


# --- L1: thiếu `on_prompt` (kế hoạch L1, "Thiếu on_prompt") -------------------------------------------


async def test_service_without_prompt_cannot_be_created_accepting(service_parts):
    with pytest.raises(ValueError):
        make_service(service_parts, on_prompt=None, accepting=True)


async def test_service_without_prompt_rejects_accepting_setter(service_parts):
    svc = make_service(service_parts, on_prompt=None)
    try:
        assert svc.accepting is False
        with pytest.raises(ValueError):
            svc.accepting = True
        assert svc.accepting is False and svc.gate.accepting is False
        svc.accepting = False  # tắt thì luôn được
        assert svc.accepting is False
    finally:
        await svc.close()


async def test_pair_with_without_prompt_raises_before_io(service_parts, monkeypatch):
    from teleport.app import pairing as app_pairing

    async def no_io(*args, **kwargs):
        raise AssertionError("không được mở kết nối khi không có on_prompt")

    if hasattr(app_pairing, "open_pairing"):
        monkeypatch.setattr(app_pairing, "open_pairing", no_io)
    svc = make_service(service_parts, on_prompt=None)
    try:
        with pytest.raises(ValueError):
            await svc.pair_with([LOCAL], 47474)
        assert service_parts[3] == []  # không gọi on_finished
        assert svc.gate.active is None
    finally:
        await svc.close()


# --- P1, P2: đường thành công ---------------------------------------------------------------------


@pytest.mark.demo
@integration
async def test_p1_pairing_success_saves_both_sides(node_factory, fast):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    t0 = time.monotonic()
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    elapsed = time.monotonic() - t0

    assert result.outcome == PairingOutcome.PAIRED
    assert outcomes(B.rec) == ["paired"]
    assert elapsed < 3.0

    # Mỗi bên đúng 1 lời hỏi, mã trùng nhau, 6 chữ số.
    assert len(A.rec.prompts) == 1 and len(B.rec.prompts) == 1
    pa, pb = A.rec.prompts[0], B.rec.prompts[0]
    assert re.fullmatch(r"[0-9]{6}", pa.code)
    assert pa.code == pb.code
    assert pa.role == Role.INITIATOR and pb.role == Role.RESPONDER
    assert (pa.peer_name, pa.peer_device_id, pa.address) == ("B", B.id, LOCAL)
    assert (pb.peer_name, pb.peer_device_id, pb.address) == ("A", A.id, LOCAL)
    # expires_at = deadline ngay sau ShowCode = lúc hiện mã + CONFIRM_TIMEOUT (giờ của loop).
    for rec in (A.rec, B.rec):
        left = rec.prompts[0].expires_at - rec.prompt_loop_times[0]
        assert 0.8 * fast.CONFIRM_TIMEOUT <= left <= fast.CONFIRM_TIMEOUT + 0.05, left
    assert A.rec.decide_results == [True] and B.rec.decide_results == [True]

    # on_finished đúng một lần mỗi bên; bên khởi xướng nhận đúng object pair_with trả về.
    assert A.rec.finished == [result]
    rb = B.rec.finished[0]
    assert result.role == Role.INITIATOR
    assert (result.address, result.port) == (LOCAL, B.port)
    assert (result.peer_name, result.peer_device_id) == ("B", B.id)
    assert result.peer_reason is None and result.known_name is None
    assert result.device is not None and result.device.device_id == B.id
    assert isinstance(result.session_id, int)
    assert result.session_id == pa.session_id
    assert rb.role == Role.RESPONDER
    assert rb.port is None
    assert (rb.address, rb.peer_name, rb.peer_device_id) == (LOCAL, "A", A.id)
    assert rb.device is not None and rb.device.device_id == A.id
    assert rb.session_id == pb.session_id

    # Kho trong RAM và trên đĩa.
    da, db = A.store.get(B.id), B.store.get(A.id)
    assert da is not None and da.fingerprint == B.identity.fingerprint and da.name == "B"
    assert db is not None and db.fingerprint == A.identity.fingerprint and db.name == "A"
    assert TrustStore.load(A.dir).get(B.id).fingerprint == B.identity.fingerprint
    assert TrustStore.load(B.dir).get(A.id).fingerprint == A.identity.fingerprint

    # Gate: rảnh hai bên, và đã finish trước on_finished (thứ tự mục 2.4).
    assert gates_idle(A, B)
    assert A.rec.gate_active_at_finish == [None] and B.rec.gate_active_at_finish == [None]
    assert B.pairing.gate.failures(LOCAL) == 0


@integration
async def test_p2_control_connections_work_after_pairing_and_after_restart(node_factory, control_client):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    await B.rec.wait_finished(1)

    # Không khởi động lại: listener đã đổi context theo kho mới (on_trust_changed).
    ab = await control_client(A, B)
    ba = await control_client(B, A)
    await wait_until(lambda: A.id in B.connected_devices() and B.id in A.connected_devices(), 2)
    await wait_until(lambda: ab.pongs() >= 1 and ba.pongs() >= 1, 3, "chưa trao ping/pong")

    await A.close()
    await B.close()
    await asyncio.wait_for(asyncio.gather(ab.task, ba.task, return_exceptions=True), 5)

    # Khởi động lại trên cùng thư mục: hai máy tự nhận ra nhau, không có lời hỏi nào.
    B2 = await node_factory("B", accept_pairing=True)
    A2 = await node_factory("A")
    ab2 = await control_client(A2, B2)
    ba2 = await control_client(B2, A2)
    await wait_until(lambda: A2.id in B2.connected_devices() and B2.id in A2.connected_devices(), 2)
    await wait_until(lambda: ab2.pongs() >= 1 and ba2.pongs() >= 1, 3, "chưa trao ping/pong")
    assert A2.rec.prompts == [] and B2.rec.prompts == []
    assert A2.rec.finished == [] and B2.rec.finished == []


# --- P3–P8: từ chối, hết giờ, bận, thời gian chờ ----------------------------------------------------


@pytest.mark.demo
@integration
async def test_p3_responder_rejects(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=False)
    A = await node_factory("A", answer=True)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.PEER_REJECTED
    assert result.peer_reason == "user"
    assert outcomes(B.rec) == ["user_rejected"]
    assert A.store.devices() == [] and B.store.devices() == []
    assert not (A.dir / "trusted.json").exists() or TrustStore.load(A.dir).devices() == []
    assert B.pairing.gate.failures(LOCAL) == 1
    assert gates_idle(A, B)


@integration
async def test_p4_initiator_rejects(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=False)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.USER_REJECTED
    assert outcomes(B.rec) == ["peer_rejected"]
    assert B.rec.finished[0].peer_reason == "user"
    assert A.store.devices() == [] and B.store.devices() == []
    assert gates_idle(A, B)


@pytest.mark.slow
@integration
async def test_p5_nobody_answers_times_out(node_factory, fast):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    both = {str(result.outcome), *outcomes(B.rec)}
    assert both <= {"timeout", "peer_timeout"}
    assert "timeout" in both
    assert A.store.devices() == [] and B.store.devices() == []
    limit = fast.CONFIRM_TIMEOUT + fast.CONFIRM_GRACE + 2
    for rec in (A.rec, B.rec):
        waited = rec.finished_times[0] - rec.prompt_times[0]
        assert 0.8 * fast.CONFIRM_TIMEOUT <= waited <= limit, waited
    assert gates_idle(A, B)


@pytest.mark.slow
@integration
async def test_p6_initiator_accepts_responder_silent(node_factory):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A", answer=True)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["timeout"]
    assert result.outcome == PairingOutcome.PEER_TIMEOUT
    assert A.store.get(B.id) is None
    assert B.store.get(A.id) is None


@integration
async def test_p7_responder_not_accepting_is_busy(node_factory):
    B = await node_factory("B", accept_pairing=False, answer=True)
    A = await node_factory("A", answer=True)
    result = await pair(A, B)
    assert result.outcome == PairingOutcome.PEER_BUSY
    assert result.peer_reason == "busy"
    await asyncio.sleep(0.3)
    assert B.rec.prompts == [] and B.rec.finished == []
    assert A.rec.prompts == []
    assert B.pairing.gate.failures(LOCAL) == 0
    assert gates_idle(A, B)


@pytest.mark.slow
@integration
async def test_p8_backoff_after_failure_then_admitted_again(node_factory, fast):
    B = await node_factory("B", accept_pairing=True, answer=False)
    A = await node_factory("A", answer=True)
    assert (await pair(A, B)).outcome == PairingOutcome.PEER_REJECTED
    await B.rec.wait_finished(1)
    finished_at = B.rec.finished_times[0]

    retry = await pair(A, B)
    retry_done = time.monotonic()
    assert retry_done - finished_at < fast.BACKOFF_BASE, "máy test quá chậm để kiểm thời gian chờ"
    assert retry.outcome == PairingOutcome.PEER_BUSY
    assert len(B.rec.prompts) == 1 and len(B.rec.finished) == 1  # BUSY: không prompt, không on_finished

    await asyncio.sleep(max(0.0, finished_at + fast.BACKOFF_BASE + 0.15 - time.monotonic()))
    B.rec.answer = True
    again = await pair(A, B)
    assert len(B.rec.prompts) == 2
    assert again.outcome == PairingOutcome.PAIRED


@integration
async def test_p9_one_session_at_a_time(node_factory):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    C = await node_factory("C", answer=True)
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()

    rc = await pair(C, B)
    assert rc.outcome == PairingOutcome.PEER_BUSY
    assert C.rec.prompts == []
    assert len(B.rec.prompts) == 1

    assert A.pairing.decide(A.rec.prompts[0].session_id, True) is True
    assert B.pairing.decide(B.rec.prompts[0].session_id, True) is True
    ra = await asyncio.wait_for(task, 10)
    await B.rec.wait_finished(1)
    assert ra.outcome == PairingOutcome.PAIRED
    assert outcomes(B.rec) == ["paired"]
    assert B.store.get(C.id) is None


@pytest.mark.slow
@integration
async def test_p10_closed_port_is_unreachable(node_factory, app_helpers):
    A = await node_factory("A")
    port = app_helpers.free_port()
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.UNREACHABLE
    assert A.rec.finished == [result]
    assert (result.address, result.port) == (LOCAL, port)
    assert result.peer_name is None and result.peer_device_id is None
    assert result.role == Role.INITIATOR
    assert A.rec.prompts == []
    assert A.pairing.gate.active is None


@integration
async def test_p11_pairing_with_self(node_factory):
    A = await node_factory("A", accept_pairing=True, answer=True)
    result = await pair(A, A)
    assert result.outcome == PairingOutcome.SELF
    await asyncio.sleep(0.3)
    assert A.rec.prompts == []
    assert A.rec.finished == [result]  # không có phiên trả lời nào được tạo
    assert A.store.devices() == []
    assert A.pairing.gate.active is None
    assert A.pairing.gate.failures(LOCAL) == 0


# --- P12, P13: danh tính --------------------------------------------------------------------------


@integration
async def test_p12a_initiator_knows_other_identity_for_device_id(node_factory, app_helpers):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    fake = peer_cert_from_pem(app_helpers.fake_cert_with_cn(B.id)[0])
    assert fake.fingerprint != B.identity.fingerprint
    A.store.add(fake, "B-cũ")

    result = await pair(A, B)
    assert result.outcome == PairingOutcome.IDENTITY_CONFLICT
    assert result.known_name == "B-cũ"
    assert result.peer_device_id == B.id
    await asyncio.sleep(0.3)
    # A không gửi pair_request: B không có phiên nào.
    assert B.rec.prompts == [] and B.rec.finished == []
    assert B.pairing.gate.failures(LOCAL) == 0
    assert A.rec.prompts == []
    assert A.store.get(B.id).fingerprint == fake.fingerprint
    assert gates_idle(A, B)


@integration
async def test_p12b_responder_knows_other_identity_for_device_id(node_factory, app_helpers):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    fake = peer_cert_from_pem(app_helpers.fake_cert_with_cn(A.id)[0])
    B.store.add(fake, "A-cũ")

    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["identity_conflict"]
    assert B.rec.finished[0].known_name == "A-cũ"
    assert result.outcome == PairingOutcome.PEER_INVALID
    assert A.rec.prompts == [] and B.rec.prompts == []
    assert A.store.get(B.id) is None
    assert B.store.get(A.id).fingerprint == fake.fingerprint
    assert gates_idle(A, B)


@integration
async def test_p13_repair_same_identity_and_name_update(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    await B.rec.wait_finished(1)
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    await B.rec.wait_finished(2)
    assert outcomes(B.rec) == ["paired", "paired"]

    await B.close()
    B2 = await node_factory("B", accept_pairing=True, answer=True, name="B2")
    assert B2.hello.name == "B2"
    result = await pair(A, B2)
    assert result.outcome == PairingOutcome.PAIRED
    assert result.peer_name == "B2"
    assert A.store.get(B2.id).name == "B2"
    assert TrustStore.load(A.dir).get(B2.id).name == "B2"
    assert len(A.store.devices()) == 1


# --- P14, P15: đóng node khi đang hỏi -----------------------------------------------------------------


@integration
async def test_p14_initiator_node_close_while_asking(node_factory):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()

    t0 = time.monotonic()
    await asyncio.wait_for(A.close(), 10)
    result = await asyncio.wait_for(task, 5)
    assert result.outcome == PairingOutcome.CANCELLED
    assert A.rec.finished == [result]
    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["peer_rejected"]
    assert B.rec.finished_times[0] - t0 <= 1.0
    assert B.store.devices() == []


@integration
async def test_p15_responder_node_close_while_asking(node_factory):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()

    t0 = time.monotonic()
    await asyncio.wait_for(B.close(), 10)
    assert outcomes(B.rec) == ["cancelled"]
    result = await asyncio.wait_for(task, 5)
    assert result.outcome == PairingOutcome.PEER_REJECTED
    assert time.monotonic() - t0 <= 2.0
    assert A.rec.finished == [result]
    assert A.pairing.gate.active is None


# --- P16, P17: client thô bỏ dở ---------------------------------------------------------------------


@integration
async def test_p16_raw_client_closes_after_commit_gets_no_n_b_and_no_prompt(
    node_factory, raw_pairing_client, tmp_path
):
    """Client thô lấy `pair_commit` rồi bỏ đi: B không hiện lời hỏi, không bao giờ gửi n_B."""
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    commitment = await c.read_commit()
    # Chưa gửi pair_nonce thì B không gửi gì thêm (đặc biệt không có pair_reveal).
    with pytest.raises(TimeoutError):
        await c.read(timeout=0.1)
    t0 = time.monotonic()
    c.abort()
    await B.rec.wait_finished(1, timeout=2)
    assert outcomes(B.rec) == ["connection_lost"]
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)
    assert time.monotonic() - t0 <= 1.0 + 0.5
    assert B.pairing.gate.failures(LOCAL) == 1
    assert B.rec.prompts == []
    assert re.fullmatch(r"[0-9a-f]{64}", commitment)


@integration
async def test_raw_client_reads_reveal_then_aborts_was_prompted_and_backs_off(
    node_factory, raw_pairing_client, tmp_path
):
    """Kẻ lấy n_B rồi bỏ đi ngay: B đã hiện lời hỏi cho đúng phiên đó (có dấu vết), IP bị tính
    một lần thất bại (chịu backoff), không lưu gì."""
    B = await node_factory("B", accept_pairing=True)  # không trả lời lời hỏi
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    code = await c.run_to_code(B.identity.fingerprint)
    c.abort()
    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["connection_lost"]
    assert len(B.rec.prompts) == 1, "B phải hiện lời hỏi trước khi tiết lộ n_B"
    prompt = B.rec.prompts[0]
    assert prompt.session_id == B.rec.finished[0].session_id
    assert prompt.code == code
    assert B.rec.prompt_times[0] <= B.rec.finished_times[0]
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)
    assert B.pairing.gate.failures(LOCAL) == 1
    assert B.store.devices() == []


def _blocking_pairing_client(port: int, identity, out: dict) -> None:
    """Client ghép đôi thô chạy trong **luồng riêng** (socket chặn), đóng vai A tới hết `pair_reveal`.

    Ghi `out["reveal_read_at"]` = `time.monotonic()` ngay khi đọc xong `pair_reveal`. Vì không chung
    event loop với node, nó đọc được reveal ngay khi reveal lên dây, kể cả khi loop của node đang bận.
    """
    import json
    import socket as socket_mod

    from teleport.net import tls

    def read_frame(s) -> dict:
        def exact(n: int) -> bytes:
            buf = b""
            while len(buf) < n:
                chunk = s.recv(n - len(buf))
                if not chunk:
                    raise ConnectionError("đóng giữa chừng")
                buf += chunk
            return buf

        (length,) = HEADER.unpack(exact(HEADER.size))
        assert length <= 16 * 1024
        return json.loads(exact(length))

    n_a = secrets.token_bytes(32)
    raw = socket_mod.create_connection((LOCAL, port), timeout=5)
    s = tls.client_context().wrap_socket(raw)
    try:
        s.settimeout(5)
        hello = read_frame(s)
        assert hello["type"] == "hello"
        s.sendall(
            encode_message(
                {
                    "type": "hello",
                    "protocol": PROTOCOL_VERSION,
                    "device_id": identity.device_id,
                    "name": "Raw",
                    "app_version": "0.0.0",
                    "os": "windows",
                }
            )
        )
        s.sendall(encode_message({"type": "pair_request", "cert": identity.cert_pem()}))
        commit = read_frame(s)
        assert commit["type"] == "pair_commit", commit
        server_fp = hashlib.sha256(s.getpeercert(binary_form=True)).hexdigest()
        payload = ref_proof_payload(identity.fingerprint, server_fp, n_a, commit["commitment"])
        signature = ref_sign(identity.key_path, payload)
        out["sent_nonce_at"] = time.monotonic()
        s.sendall(encode_message({"type": "pair_nonce", "nonce": n_a.hex(), "signature": signature.hex()}))
        reveal = read_frame(s)
        out["reveal_read_at"] = time.monotonic()
        assert reveal["type"] == "pair_reveal", reveal
        n_b = bytes.fromhex(reveal["nonce"])
        assert ref_commitment(out["responder_fp"], n_b) == commit["commitment"]
        out["code"] = pairing_code(identity.fingerprint, out["responder_fp"], n_a, n_b)
    finally:
        with contextlib.suppress(OSError):
            s.close()


PROMPT_HOLD = 0.2  # lời hỏi ở B "chiếm" chừng này giây; reveal gửi trước lời hỏi sẽ bị đọc trong lúc đó


@integration
async def test_responder_prompt_happens_before_pair_reveal_reaches_the_wire(node_factory, tmp_path):
    """B phải gọi `on_prompt` (hiện mã) **xong** rồi mới gửi `pair_reveal`.

    `on_prompt` của B giữ PROMPT_HOLD giây rồi ghi mốc kết thúc. Client ở luồng riêng ghi mốc lúc
    đọc được `pair_reveal`. Thứ tự đúng: mốc kết thúc lời hỏi < mốc đọc reveal. Nếu app gửi reveal
    trước (đảo ShowCode/SendMessage), client đọc được reveal trong lúc lời hỏi đang giữ → fail.
    """
    prompt_done: list[float] = []

    def hold_prompt(prompt) -> None:
        time.sleep(PROMPT_HOLD)  # cố ý chặn loop của B: chỉ client ở luồng khác còn chạy
        prompt_done.append(time.monotonic())

    B = await node_factory("B", accept_pairing=True, answer=hold_prompt)
    raw_id = load_or_create_identity(tmp_path / "raw")
    out: dict = {"responder_fp": B.identity.fingerprint}
    await asyncio.wait_for(asyncio.to_thread(_blocking_pairing_client, B.port, raw_id, out), 10)

    await B.rec.wait_finished(1, timeout=3)  # client đã đóng → connection_lost
    assert len(B.rec.prompts) == 1
    assert B.rec.prompts[0].code == out["code"]
    assert len(prompt_done) == 1
    assert B.rec.prompt_times[0] >= out["sent_nonce_at"]
    assert prompt_done[0] <= out["reveal_read_at"], (
        f"pair_reveal tới client lúc {out['reveal_read_at']:.3f}, trước khi lời hỏi xong lúc "
        f"{prompt_done[0]:.3f}: n_B lộ trước khi B hiện mã"
    )
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)


@pytest.mark.slow
@integration
async def test_p17_save_only_after_both_confirm(node_factory, raw_pairing_client, tmp_path, fast, caplog):
    """P17: client thô (vai A) nhận mã nhưng không gửi pair_confirm; B đồng ý → B không lưu."""
    caplog.set_level(logging.DEBUG)
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id, "Raw")
    code = await c.run_to_code(B.identity.fingerprint)

    await B.rec.wait_prompts()
    assert B.rec.prompts[0].code == code  # mã của B đúng công thức protocol §5
    assert await c.read_type("pair_confirm") == {"type": "pair_confirm"}

    await B.rec.wait_finished(1, timeout=fast.CONFIRM_TIMEOUT + fast.CONFIRM_GRACE + fast.SLACK)
    assert outcomes(B.rec)[0] in ("timeout", "connection_lost")
    assert B.store.get(raw_id.device_id) is None
    assert TrustStore.load(B.dir).get(raw_id.device_id) is None
    rest = await c.read_until_closed(3)
    assert rest in ([], [{"type": "pair_abort", "reason": "timeout"}])

    # N9: log không chứa mã, nonce hai bên, cam kết.
    text = caplog.text
    assert not re.search(rf"(?<!\d){code}(?!\d)", text)
    assert format_code(code) not in text
    assert c.nonce.hex() not in text
    assert c.responder_nonce.hex() not in text
    assert c.commitment not in text
    assert c.last_signature is not None
    assert c.last_signature.hex() not in text  # không ghi chữ ký, payload (mvp N9)
    assert c.last_payload.hex() not in text


# --- P18: hai bên cùng chủ động ------------------------------------------------------------------------


P18_ROUNDS = 10


@pytest.mark.slow
@integration
@pytest.mark.parametrize("accept_pairing", [True, False], ids=["listen", "pair"])
async def test_p18_yield_rule_always_gives_one_paired_result_per_side(node_factory, accept_pairing):
    """Sửa F1 (review PR-3): luật nhường phải chạy **mỗi lần**, không chỉ khi may mắn.

    Hai node cùng `pair_with` nhau, lặp `P18_ROUNDS` lần. `accept_pairing=False` mô phỏng hai
    `teleport pair` chạy cùng lúc (luật nhường xét trước `accepting`, protocol §5.3). Mỗi lần:
    - cả hai `pair_with` trả `PAIRED`: bên nhỏ hơn với vai `INITIATOR`, bên lớn hơn với vai
      `RESPONDER` (kết quả của phiên trả lời đã thay phiên khởi xướng của nó), không bao giờ
      `PEER_BUSY` hay `CANCELLED`;
    - `on_finished` của mỗi bên được gọi **đúng một lần**, và chính là kết quả `pair_with` trả;
    - `trusted.json` của mỗi bên có máy kia; mỗi bên đúng một lời hỏi, cùng mã.
    """
    tally: list[str] = []
    for i in range(P18_ROUNDS):
        A = await node_factory(f"A{i}", accept_pairing=accept_pairing, answer=True)
        B = await node_factory(f"B{i}", accept_pairing=accept_pairing, answer=True)
        lo, hi = sorted([A, B], key=lambda n: n.id)
        r_lo, r_hi = await asyncio.wait_for(
            asyncio.gather(lo.pairing.pair_with([LOCAL], hi.port), hi.pairing.pair_with([LOCAL], lo.port)),
            20,
        )
        await asyncio.sleep(0.1)  # để lộ lời gọi on_finished thừa tới muộn (nếu có)
        tally.append(f"{r_lo.outcome}/{r_hi.outcome}/{r_hi.role}")
        where = f"lần {i + 1}/{P18_ROUNDS}, các lần đến giờ: {tally}"

        assert r_lo.outcome == PairingOutcome.PAIRED, where
        assert r_lo.role == Role.INITIATOR, where
        assert r_lo.peer_device_id == hi.id, where
        assert r_hi.outcome == PairingOutcome.PAIRED, where
        assert r_hi.role == Role.RESPONDER, where
        assert r_hi.peer_device_id == lo.id, where

        assert lo.rec.finished == [r_lo], (where, outcomes(lo.rec))
        assert hi.rec.finished == [r_hi], (where, outcomes(hi.rec))

        assert TrustStore.load(lo.dir).get(hi.id) is not None, where
        assert TrustStore.load(hi.dir).get(lo.id) is not None, where
        assert len(lo.rec.prompts) == 1 and len(hi.rec.prompts) == 1, where
        assert lo.rec.prompts[0].code == hi.rec.prompts[0].code, where
        assert gates_idle(A, B), where

        await A.close()
        await B.close()


# --- P19–P23: dữ liệu độc ------------------------------------------------------------------------------


# Message sai gửi tới B khi B đang chờ `pair_nonce` (AWAIT_NONCE).
BAD_AFTER_COMMIT = {
    "rac": lambda c, ident: c.send_bytes(HEADER.pack(9) + b"khong-json"[:9]),
    "hello_lan_hai": lambda c, ident: c.send_dict(
        {
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "device_id": ident.device_id,
            "name": "Raw",
            "app_version": "0.0.0",
            "os": "windows",
        }
    ),
    # pair_reveal / pair_commit chỉ bên trả lời được gửi.
    "reveal_sai_vai": lambda c, ident: c.send_dict({"type": "pair_reveal", "nonce": secrets.token_hex(32)}),
    "commit_sai_vai": lambda c, ident: c.send_dict(
        {"type": "pair_commit", "commitment": secrets.token_hex(32)}
    ),
    "request_lan_hai": lambda c, ident: c.send_dict({"type": "pair_request", "cert": ident.cert_pem()}),
    "confirm_truoc_nonce": lambda c, ident: c.send_dict({"type": "pair_confirm"}),
    "type_la": lambda c, ident: c.send_dict({"type": "chao_tu_tuong_lai"}),
    "challenge_cu": lambda c, ident: c.send_dict({"type": "pair_challenge", "nonce": secrets.token_hex(32)}),
    "nonce_sai_kieu": lambda c, ident: c.send_dict({**c.nonce_message(), "nonce": 5}),
    "nonce_hoa": lambda c, ident: c.send_dict({**c.nonce_message(), "nonce": "AB" * 32}),
    "nonce_ngan": lambda c, ident: c.send_dict({**c.nonce_message(), "nonce": "ab" * 31}),
    "header_qua_lon": lambda c, ident: c.send_bytes(HEADER.pack(16 * 1024 + 1)),
    # Protocol 5.1: chữ ký trong pair_nonce sai dạng hoặc không qua kiểm → invalid, không hiện mã.
    "thieu_chu_ky": lambda c, ident: c.send_dict({"type": "pair_nonce", "nonce": c.nonce.hex()}),
    "chu_ky_hoa": lambda c, ident: c.send_dict(
        {**c.nonce_message(), "signature": c.nonce_message()["signature"].upper()}
    ),
    "chu_ky_ngan": lambda c, ident: c.send_dict({**c.nonce_message(), "signature": "ab" * 63}),
    "chu_ky_dai": lambda c, ident: c.send_dict({**c.nonce_message(), "signature": "ab" * 65}),
    "chu_ky_sai_kieu": lambda c, ident: c.send_dict({**c.nonce_message(), "signature": 5}),
    "chu_ky_rac": lambda c, ident: c.send_dict(c.nonce_message(signature_hex="ab" * 64)),
    "chu_ky_r_s_0": lambda c, ident: c.send_dict(c.nonce_message(signature_hex="00" * 64)),
    "chu_ky_khoa_khac": lambda c, ident: _send_signed_with(c, ec.generate_private_key(ec.SECP256R1())),
    "chu_ky_cho_n_a_khac": lambda c, ident: c.send_dict(
        {**c.nonce_message(secrets.token_hex(32)), "nonce": c.nonce.hex()}
    ),
    "chu_ky_cam_ket_khac": lambda c, ident: c.send_dict(
        c.nonce_message(
            signature_hex=_sign_payload(
                ident, ref_proof_payload(ident.fingerprint, c.server_fingerprint, c.nonce, "00" * 32)
            )
        )
    ),
    "chu_ky_dao_vai": lambda c, ident: c.send_dict(
        c.nonce_message(
            signature_hex=_sign_payload(
                ident, ref_proof_payload(c.server_fingerprint, ident.fingerprint, c.nonce, c.commitment)
            )
        )
    ),
}


def _sign_payload(identity, payload: bytes) -> str:
    return ref_sign(identity.key_path, payload).hex()


def _send_signed_with(c, key) -> None:
    """Ký `pair_nonce` bằng một khóa khác khóa trong chứng chỉ đã gửi ở `pair_request`."""
    c.signing_key = key
    c.send_dict(c.nonce_message())


@integration
@pytest.mark.parametrize("case", list(BAD_AFTER_COMMIT))
async def test_p19_responder_bad_message_after_commit(node_factory, raw_pairing_client, tmp_path, case):
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    BAD_AFTER_COMMIT[case](c, raw_id)
    await c.drain()

    msgs = await c.read_until_closed(5)
    # Không bao giờ có pair_reveal: n_B không lộ khi chưa có pair_nonce hợp lệ.
    assert all(m.get("type") != "pair_reveal" for m in msgs), msgs
    if case != "header_qua_lon":
        assert msgs == [INVALID], msgs
    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["protocol_error"]
    assert B.pairing.gate.failures(LOCAL) == 1
    assert B.rec.prompts == []
    assert B.store.devices() == []
    assert B.pairing.gate.active is None


def _serve_pairing_script(identity, bad_bytes: bytes, received: list):
    """Kịch bản FakeServer: hello thật, đọc hello + pair_request của client, gửi `bad_bytes`, ghi phản hồi."""

    async def script(reader, writer):
        try:
            writer.write(
                encode_message(
                    {
                        "type": "hello",
                        "protocol": PROTOCOL_VERSION,
                        "device_id": identity.device_id,
                        "name": "Srv",
                        "app_version": "0.0.0",
                        "os": "linux",
                    }
                )
            )
            await writer.drain()
            await read_message(reader, 16384)  # hello của client
            await read_message(reader, 16384)  # pair_request
            writer.write(bad_bytes)
            await writer.drain()
            while (msg := await read_message(reader, 16384)) is not None:
                received.append(msg)
        except Exception:
            pass

    return script


# Message sai gửi tới A khi A đang chờ `pair_commit` (AWAIT_COMMIT).
BAD_FOR_INITIATOR = {
    "commit_hong": encode_message({"type": "pair_commit", "commitment": "zz"}),
    "commit_hoa": encode_message({"type": "pair_commit", "commitment": "AB" * 32}),
    "confirm_som": encode_message({"type": "pair_confirm"}),
    "rac": HEADER.pack(4) + b"\xff\x00ab",
    "reveal_truoc_commit": encode_message({"type": "pair_reveal", "nonce": "ab" * 32}),
    "nonce_sai_vai": encode_message({"type": "pair_nonce", "nonce": "ab" * 32}),
    "challenge_cu": encode_message({"type": "pair_challenge", "nonce": "ab" * 32}),
}


@integration
@pytest.mark.parametrize("case", list(BAD_FOR_INITIATOR))
async def test_p20_initiator_bad_message_from_server(node_factory, fake_server, tmp_path, case):
    A = await node_factory("A", answer=True)
    srv = load_or_create_identity(tmp_path / "srv")
    received: list = []
    port = await fake_server(srv, _serve_pairing_script(srv, BAD_FOR_INITIATOR[case], received))
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.PROTOCOL_ERROR
    await wait_until(lambda: INVALID in received, 3, "server chưa nhận pair_abort{invalid}")
    # A chưa nhận pair_commit hợp lệ thì không được gửi n_A.
    assert all(m.get("type") != "pair_nonce" for m in received), received
    assert A.rec.prompts == []
    assert A.rec.finished == [result]
    assert A.pairing.gate.active is None


def _fake_responder_script(identity, mode: str, log: list, initiator_fp: str | None = None):
    """Bên trả lời giả (FakeServer) theo luồng mới; `log` ghi mọi message nó nhận sau hello của mình.

    mode:
    - "honest": cam kết n_B bằng fp của mình, tiết lộ đúng n_B (đối chứng).
    - "doi_n_b": cam kết n_B, thấy n_A rồi tiết lộ n_B khác (lái mã).
    - "cam_ket_fp_khoi_xuong": cam kết bằng fp của A thay vì fp của mình, tiết lộ đúng nonce.
    - "reveal_truoc_commit": gửi pair_reveal ngay sau pair_request, không có pair_commit.
    """
    n_b = secrets.token_bytes(32)
    n_b_other = secrets.token_bytes(32)
    state: dict = {"n_b": n_b, "n_b_other": n_b_other}

    async def script(reader, writer):
        try:
            writer.write(
                encode_message(
                    {
                        "type": "hello",
                        "protocol": PROTOCOL_VERSION,
                        "device_id": identity.device_id,
                        "name": "Srv",
                        "app_version": "0.0.0",
                        "os": "linux",
                    }
                )
            )
            await writer.drain()
            hello = await read_message(reader, 16384)
            log.append(hello)
            request = await read_message(reader, 16384)
            log.append(request)
            if mode == "reveal_truoc_commit":
                writer.write(encode_message({"type": "pair_reveal", "nonce": n_b.hex()}))
            else:
                fp = identity.fingerprint
                if mode == "cam_ket_fp_khoi_xuong":
                    fp = initiator_fp
                commitment = ref_commitment(fp, n_b)
                state["commitment"] = commitment
                writer.write(encode_message({"type": "pair_commit", "commitment": commitment}))
                await writer.drain()
                nonce_msg = await read_message(reader, 16384)
                log.append(nonce_msg)
                state["n_a"] = nonce_msg["nonce"]
                state["signature"] = nonce_msg.get("signature")
                revealed = n_b_other if mode == "doi_n_b" else n_b
                writer.write(encode_message({"type": "pair_reveal", "nonce": revealed.hex()}))
            await writer.drain()
            while (msg := await read_message(reader, 16384)) is not None:
                log.append(msg)
        except Exception:
            pass

    script.state = state  # type: ignore[attr-defined]
    return script


@integration
@pytest.mark.parametrize("mode", ["doi_n_b", "cam_ket_fp_khoi_xuong", "reveal_truoc_commit"])
async def test_initiator_rejects_fake_responder_without_prompt(
    node_factory, fake_server, tmp_path, caplog, mode
):
    """Bên trả lời giả lái mã (đổi n_B sau khi thấy n_A, cam kết sai fp, reveal trước commit):
    `pair_with` → protocol_error, A không hiện lời hỏi, bên giả nhận `pair_abort{invalid}`.
    `pair_request` A gửi chỉ có `cert`; log không chứa nonce hay cam kết."""
    caplog.set_level(logging.DEBUG)
    A = await node_factory("A", answer=True)
    srv = load_or_create_identity(tmp_path / "srv")
    log: list = []
    script = _fake_responder_script(srv, mode, log, initiator_fp=A.identity.fingerprint)
    port = await fake_server(srv, script)
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.PROTOCOL_ERROR
    await wait_until(lambda: INVALID in log, 3, "bên giả chưa nhận pair_abort{invalid}")
    assert A.rec.prompts == []
    assert A.rec.finished == [result]
    assert A.store.devices() == []
    assert A.pairing.gate.active is None

    # Message đầu tiên sau hello: pair_request chỉ có cert (không nonce, không cam kết).
    assert log[0]["type"] == "hello"
    assert log[1] == {"type": "pair_request", "cert": A.identity.cert_pem()}
    if mode == "reveal_truoc_commit":
        # Chưa có pair_commit thì A không gửi n_A.
        assert all(m.get("type") != "pair_nonce" for m in log), log
    else:
        assert log[2]["type"] == "pair_nonce"

    text = caplog.text
    secrets_seen = [script.state["n_b"].hex(), script.state["n_b_other"].hex()]
    if "commitment" in script.state:
        secrets_seen.append(script.state["commitment"])
    if "n_a" in script.state:
        secrets_seen.append(script.state["n_a"])
    if script.state.get("signature"):
        secrets_seen.append(script.state["signature"])  # mvp N9: không ghi chữ ký vào log
    for value in secrets_seen:
        assert value not in text


@integration
async def test_initiator_with_honest_fake_responder_prompts_with_spec_code(
    node_factory, fake_server, tmp_path, app_helpers
):
    """Đối chứng cho bên giả ở trên: cùng kịch bản nhưng trung thực → A hiện mã đúng công thức."""
    A = await node_factory("A", answer=False)
    srv = load_or_create_identity(tmp_path / "srv")
    log: list = []
    script = _fake_responder_script(srv, "honest", log)
    port = await fake_server(srv, script)
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.USER_REJECTED
    assert len(A.rec.prompts) == 1
    n_a = bytes.fromhex(script.state["n_a"])
    expected = pairing_code(A.identity.fingerprint, srv.fingerprint, n_a, script.state["n_b"])
    assert A.rec.prompts[0].code == expected
    assert log[1] == {"type": "pair_request", "cert": A.identity.cert_pem()}
    await wait_until(lambda: {"type": "pair_abort", "reason": "user"} in log, 3, "chưa nhận pair_abort{user}")

    # Protocol 5.2: pair_nonce mang đúng hai trường; chữ ký là ECDSA P-256 + SHA-256 bằng khóa của A
    # trên payload (fp_A ‖ fp_B từ TLS ‖ n_A ‖ C_B), kiểm độc lập bằng chứng chỉ A gửi.
    nonce_msg = log[2]
    assert set(nonce_msg) == {"type", "nonce", "signature"}, nonce_msg
    assert re.fullmatch(r"[0-9a-f]{128}", nonce_msg["signature"])
    payload = ref_proof_payload(A.identity.fingerprint, srv.fingerprint, n_a, script.state["commitment"])
    assert app_helpers.ref_verify(A.identity.cert_pem(), payload, bytes.fromhex(nonce_msg["signature"]))
    wrong = ref_proof_payload(srv.fingerprint, A.identity.fingerprint, n_a, script.state["commitment"])
    assert not app_helpers.ref_verify(A.identity.cert_pem(), wrong, bytes.fromhex(nonce_msg["signature"]))


@integration
@pytest.mark.parametrize("cert_kind", ["ca", "pem_rac"])
async def test_p21_bad_cert_in_pair_request(node_factory, raw_pairing_client, app_helpers, cert_kind):
    B = await node_factory("B", accept_pairing=True, answer=True)
    device_id = app_helpers.new_device_id()
    pem = app_helpers.fake_cert_with_cn(device_id, ca=True)[0] if cert_kind == "ca" else GARBAGE_PEM
    c = await raw_pairing_client(B.port)
    c.send_dict(app_helpers.hello_dict(device_id))
    c.send_dict({"type": "pair_request", "cert": pem})
    await c.drain()
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["protocol_error"]
    assert B.rec.prompts == []
    assert B.store.devices() == []


@integration
async def test_p22_cert_cn_differs_from_hello(node_factory, raw_pairing_client, app_helpers, tmp_path):
    B = await node_factory("B", accept_pairing=True, answer=True)
    real = load_or_create_identity(tmp_path / "x")
    c = await raw_pairing_client(B.port)
    c.send_dict(app_helpers.hello_dict(app_helpers.new_device_id()))
    c.send_dict({"type": "pair_request", "cert": real.cert_pem()})
    await c.drain()
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["protocol_error"]
    assert B.rec.prompts == []


@integration
async def test_p23_silent_after_request_times_out(node_factory, raw_pairing_client, tmp_path, fast):
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    t0 = time.monotonic()
    # Bên trả lời chờ pair_nonce theo hạn riêng NONCE_TIMEOUT. Test phân biệt hạn này với
    # MESSAGE_TIMEOUT là test_stranger_after_commit_holds_gate_only_until_nonce_timeout.
    msg = await c.read(timeout=fast.NONCE_TIMEOUT + fast.SLACK)
    waited = time.monotonic() - t0
    assert msg == {"type": "pair_abort", "reason": "timeout"}
    assert 0.8 * fast.NONCE_TIMEOUT <= waited <= fast.NONCE_TIMEOUT + fast.SLACK
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["timeout"]
    assert B.rec.prompts == []
    await wait_until(lambda: B.pairing.gate.active is None, 1)


# --- Kẻ lạ nhận pair_commit rồi im lặng / nhỏ giọt: không giữ slot duy nhất của gate lâu ---------
#
# Đặc tả: bên trả lời chờ pair_nonce tối đa NONCE_TIMEOUT kể từ lúc gửi pair_commit; byte tới
# không gia hạn. Trong lúc đó node bị chiếm slot (một phiên tại một thời điểm), nên `pair_with`
# từ chính node đó trả `busy` ngay (không thể thử bằng client ẩn danh thứ hai cùng 127.0.0.1 vì
# giới hạn 1 kết nối ẩn danh mỗi IP chặn nó trước gate). Sau NONCE_TIMEOUT + FAILED_CLOSE_TIMEOUT
# gate phải trống và ghép đôi thật được.
#
# MESSAGE_TIMEOUT được nâng lên quá NONCE_TIMEOUT + SLACK: với FAST (0,5 / 1,0) hai hạn đều nằm gọn
# trong SLACK nên không phân biệt được; nâng lên thì nếu bên trả lời dùng nhầm MESSAGE_TIMEOUT,
# pair_abort đến muộn và test hỏng.

NONCE_DRIP_INTERVAL = 0.05  # nhỏ giọt pair_nonce: một byte mỗi 50 ms (~100 byte → ~5 s, quá hạn xa)


async def _drip(c, data: bytes, sent: list[int]) -> None:
    """Gửi `data` từng byte, mỗi byte cách NONCE_DRIP_INTERVAL; đếm số byte đã gửi vào `sent`."""
    for i in range(len(data)):
        with contextlib.suppress(Exception):
            c.writer.write(data[i : i + 1])
            await c.writer.drain()
        sent[0] = i + 1
        await asyncio.sleep(NONCE_DRIP_INTERVAL)


@pytest.mark.slow
@integration
@pytest.mark.parametrize("case", ["im_lang", "nho_giot_nonce"])
async def test_stranger_after_commit_holds_gate_only_until_nonce_timeout(
    node_factory, raw_pairing_client, tmp_path, fast, monkeypatch, case
):
    from teleport.app import pairing as app_pairing
    from teleport.core import pairing as core_pairing

    long_message_timeout = fast.NONCE_TIMEOUT + fast.SLACK + 2.0
    monkeypatch.setattr(core_pairing, "MESSAGE_TIMEOUT", long_message_timeout)
    B = await node_factory("B", accept_pairing=True, answer=True)
    C = await node_factory("C", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    # Mốc trước khi gửi pair_request: bên trả lời chỉ đặt hạn (loop.time(), cùng đồng hồ với
    # time.monotonic()) sau khi nhận nó, nên pair_abort không thể tới trước t_req + NONCE_TIMEOUT
    # dù vòng lặp bị dừng (GC, máy bận) giữa lúc gửi pair_commit và lúc test đọc được nó.
    t_req = time.monotonic()
    await c.begin(raw_id)
    await c.read_commit()
    t0 = time.monotonic()

    drip: asyncio.Task | None = None
    sent = [0]
    frame_len = 0
    if case == "nho_giot_nonce":
        data = encode_message(c.nonce_message())
        frame_len = len(data)
        drip = asyncio.create_task(_drip(c, data, sent), name="test.drip")
    try:
        # Slot của gate bị phiên này chiếm → node B không khởi xướng được phiên khác. Phiên của
        # kẻ lạ chưa kết thúc (B chỉ báo đúng kết quả BUSY này), nên BUSY là do nó, không cần
        # đo giờ để biết.
        busy = await asyncio.wait_for(B.pairing.pair_with([LOCAL], C.port), fast.SLACK)
        assert busy.outcome == PairingOutcome.BUSY
        assert [f.outcome for f in B.rec.finished] == [PairingOutcome.BUSY]
        assert B.pairing.gate.active is not None
        assert C.rec.prompts == [] and C.rec.finished == []

        msg = await c.read(timeout=fast.NONCE_TIMEOUT + fast.SLACK)
        t_msg = time.monotonic()
    finally:
        if drip is not None:
            drip.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await drip
    assert msg == {"type": "pair_abort", "reason": "timeout"}, msg
    # Không bỏ cuộc sớm (so với mốc trước pair_request, không cần biên dưới nới tay), và byte nhỏ
    # giọt không gia hạn (so với lúc đọc được pair_commit, mốc muộn hơn lúc bên trả lời đặt hạn).
    assert t_msg >= t_req + fast.NONCE_TIMEOUT, f"pair_abort tới sớm: {t_msg - t_req:.2f} s sau pair_request"
    waited = t_msg - t0
    assert waited <= fast.NONCE_TIMEOUT + fast.SLACK, f"chờ {waited:.2f} s"
    if case == "nho_giot_nonce":
        assert 0 < sent[0] < frame_len, "pair_nonce phải bị cắt khi còn đang nhỏ giọt"

    limit = fast.NONCE_TIMEOUT + app_pairing.FAILED_CLOSE_TIMEOUT + fast.SLACK
    await wait_until(lambda: B.pairing.gate.active is None, limit, "gate chưa được nhả")
    assert time.monotonic() - t0 <= limit
    await c.read_until_closed(app_pairing.FAILED_CLOSE_TIMEOUT + fast.SLACK)
    await wait_until(lambda: "timeout" in outcomes(B.rec), 1, "phiên trả lời chưa kết thúc TIMEOUT")
    assert B.rec.prompts == [], "chưa nhận pair_nonce thì không được hiện mã"
    assert B.pairing.gate.recent_codes(asyncio.get_running_loop().time()) == 0, "không được đếm mã"
    assert B.store.devices() == []

    # Hết bị chiếm: không còn busy, ghép đôi thật B → C thành công.
    result = await asyncio.wait_for(B.pairing.pair_with([LOCAL], C.port), 15)
    assert result.outcome == PairingOutcome.PAIRED
    assert B.store.get(C.id) is not None and C.store.get(B.id) is not None


@integration
async def test_real_pairing_succeeds_with_short_nonce_timeout(node_factory, fast):
    from teleport.core import pairing as core_pairing

    assert core_pairing.NONCE_TIMEOUT == fast.NONCE_TIMEOUT < core_pairing.MESSAGE_TIMEOUT
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    result = await pair(A, B)
    assert result.outcome == PairingOutcome.PAIRED
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["paired"]
    assert A.store.get(B.id) is not None and B.store.get(A.id) is not None


GATE_FREE_AFTER_FAILURE = 1.5  # sửa F4: gửi pair_abort + đóng tổng 1 s, cộng 0,5 s cho máy chậm


@pytest.mark.slow
@integration
@pytest.mark.parametrize("case", ["confirm_truoc_nonce", "rac"])
async def test_failed_session_frees_gate_quickly_when_peer_never_closes(
    node_factory, raw_pairing_client, tmp_path, monkeypatch, case
):
    """Sửa F4 (tan-cong PR-3): phiên hỏng mà máy kia không đọc, không đóng socket.

    Trước đây node đóng gọn chờ tới `CLOSE_TIMEOUT` (5 s) nên gate bị giữ thêm 5 s. Kết quả
    ≠ PAIRED thì gửi `pair_abort` rồi đóng với giới hạn tổng 1 s, quá thì abort: gate phải
    trống trong ≤ 1,5 s kể từ lúc gửi message sai. Dùng hằng thời gian thật của kết nối
    (`CLOSE_TIMEOUT = 5.0`), vì `fast` rút nó còn 0,5 s và che mất lỗi.
    """
    from teleport.app import pairing as app_pairing
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    monkeypatch.setattr(app_pairing, "BUSY_REPLY_TIMEOUT", 1.0)
    monkeypatch.setattr(app_pairing, "ABORT_ON_CANCEL_TIMEOUT", 1.0)
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    c.writer.transport.pause_reading()  # từ đây không đọc gì nữa (kể cả close_notify), không đóng
    BAD_AFTER_COMMIT[case](c, raw_id)
    await c.drain()
    t0 = time.monotonic()
    await wait_until(
        lambda: B.pairing.gate.active is None, GATE_FREE_AFTER_FAILURE + 1.0, "gate chưa được nhả"
    )
    freed_after = time.monotonic() - t0
    assert freed_after <= GATE_FREE_AFTER_FAILURE, f"gate bị giữ {freed_after:.2f} s sau phiên hỏng"
    await B.rec.wait_finished(1, timeout=1)
    assert outcomes(B.rec) == ["protocol_error"]
    assert B.store.devices() == []


# --- P24–P27: decide, callback, lỗi lưu, log ----------------------------------------------------------


@integration
async def test_p24_decide_rules(node_factory):
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()
    sid = B.rec.prompts[0].session_id

    assert B.pairing.decide(sid + 1000, True) is False
    assert B.pairing.decide(A.rec.prompts[0].session_id + 1000, False) is False
    with pytest.raises(ValueError):
        B.pairing.decide(sid, 1)
    assert B.pairing.decide(sid, True) is True
    assert B.pairing.decide(sid, True) is False  # đã quyết rồi
    assert B.pairing.decide(sid, False) is False  # không đổi ý được
    assert A.pairing.decide(A.rec.prompts[0].session_id, True) is True

    result = await asyncio.wait_for(task, 10)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.PAIRED
    assert outcomes(B.rec) == ["paired"]
    assert B.pairing.decide(sid, True) is False  # phiên đã xong
    assert A.pairing.decide(A.rec.prompts[0].session_id, False) is False


def _app_errors(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("teleport.app") and r.levelno >= logging.ERROR]


def _no_trusted_devices(directory) -> bool:
    return not (directory / "trusted.json").exists() or TrustStore.load(directory).devices() == []


@integration
async def test_p25_responder_prompt_raises_cancels_session(node_factory, caplog, fast):
    """L1: `on_prompt` của B raise (sau khi đã gọi `decide(True)`) → B hủy phiên, không tiết lộ n_B.

    B: `prompt_failed`, `decide` vẫn trả True nhưng quyết định bị bỏ; A: `peer_busy` (B gửi
    `pair_abort{busy}`), A không hiện lời hỏi; không bên nào ghi `trusted.json`; phiên B tự hủy nên
    không tính vào chờ tăng dần (`failures == 0`, thử lại ngay được); log ERROR không chứa mã.
    """
    caplog.set_level(logging.DEBUG)
    B = await node_factory("B", accept_pairing=True, answer=True, raise_in_prompt=True)
    A = await node_factory("A", answer=True)
    t0 = time.monotonic()
    result = await pair(A, B)
    took = time.monotonic() - t0
    await B.rec.wait_finished(1)

    assert result.outcome == PairingOutcome.PEER_BUSY
    assert result.peer_reason == "busy"
    assert A.rec.prompts == []
    assert A.rec.finished == [result]
    assert took < fast.CONFIRM_TIMEOUT, f"A chờ {took:.2f} s: B không hủy phiên ngay"

    assert outcomes(B.rec) == ["prompt_failed"]
    rb = B.rec.finished[0]
    assert rb.role == Role.RESPONDER and rb.device is None
    assert (rb.peer_name, rb.peer_device_id) == ("A", A.id)
    assert len(B.rec.prompts) == 1
    assert B.rec.decide_results == [True]  # decide trước khi raise vẫn nhận, nhưng phiên đã DONE

    assert A.store.devices() == [] and B.store.devices() == []
    assert _no_trusted_devices(A.dir) and _no_trusted_devices(B.dir)
    assert B.pairing.gate.failures(LOCAL) == 0
    assert B.pairing.gate.blocked_until(LOCAL) is None
    assert gates_idle(A, B)

    errors = _app_errors(caplog)
    assert errors, "on_prompt raise phải được ghi log mức ERROR"
    code = B.rec.prompts[0].code
    assert not re.search(rf"(?<!\d){code}(?!\d)", caplog.text)
    assert format_code(code) not in caplog.text

    # Không bị chờ tăng dần: thử lại ngay (trong BACKOFF_BASE) thì được hỏi và ghép đôi được.
    B.rec.raise_in_prompt = False
    again = await pair(A, B)
    assert again.outcome == PairingOutcome.PAIRED
    assert len(B.rec.prompts) == 2


@integration
async def test_p25_raising_on_finished_does_not_break_pairing(node_factory, caplog):
    caplog.set_level(logging.DEBUG)
    B = await node_factory("B", accept_pairing=True, answer=True, raise_in_finished=True)
    A = await node_factory("A", answer=True, raise_in_finished=True)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.PAIRED
    assert outcomes(B.rec) == ["paired"]
    assert len(A.rec.finished) == 1 and len(B.rec.finished) == 1
    assert A.store.get(B.id) is not None and B.store.get(A.id) is not None
    logged = [r for r in _app_errors(caplog) if r.exc_info is not None]
    assert len(logged) >= 2, [r.getMessage() for r in logged]
    assert gates_idle(A, B)


@integration
@pytest.mark.parametrize("answer", [None, True], ids=["khong_quyet", "quyet_roi_raise"])
async def test_responder_prompt_raises_raw_client_never_gets_reveal(
    node_factory, raw_pairing_client, tmp_path, answer
):
    """L1 (mấu chốt): B không hiện được mã thì KHÔNG frame `pair_reveal` nào lên dây.

    Client thô (vai A) gửi `pair_nonce` hợp lệ rồi đọc mọi frame tới khi kết nối đóng: chỉ có
    đúng một `pair_abort{busy}`; kết nối đóng trong FAILED_CLOSE_TIMEOUT (1 s) + 0,5 s.
    """
    B = await node_factory("B", accept_pairing=True, answer=answer, raise_in_prompt=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    await c.send_nonce()
    t0 = time.monotonic()
    msgs = await c.read_until_closed(5)
    took = time.monotonic() - t0
    assert all(m.get("type") != "pair_reveal" for m in msgs), f"n_B bị lộ: {msgs!r}"
    assert msgs == [{"type": "pair_abort", "reason": "busy"}], msgs
    assert took <= 1.0 + 0.5, f"kết nối đóng sau {took:.2f} s"

    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["prompt_failed"]
    assert len(B.rec.prompts) == 1
    assert B.store.devices() == []
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)
    assert B.pairing.gate.failures(LOCAL) == 0


@pytest.mark.slow
@integration
async def test_responder_prompt_raises_frees_gate_quickly_when_peer_never_reads(
    node_factory, raw_pairing_client, tmp_path, monkeypatch
):
    """L1: hủy vì không hiện được mã cũng gửi `pair_abort` + đóng trong FAILED_CLOSE_TIMEOUT, kể cả
    khi máy kia không đọc, không đóng (dùng CLOSE_TIMEOUT thật 5 s như test F4)."""
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    B = await node_factory("B", accept_pairing=True, raise_in_prompt=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    c.writer.transport.pause_reading()
    await c.send_nonce()
    t0 = time.monotonic()
    await wait_until(
        lambda: B.pairing.gate.active is None, GATE_FREE_AFTER_FAILURE + 1.0, "gate chưa được nhả"
    )
    freed_after = time.monotonic() - t0
    assert freed_after <= GATE_FREE_AFTER_FAILURE, f"gate bị giữ {freed_after:.2f} s"
    await B.rec.wait_finished(1, timeout=1)
    assert outcomes(B.rec) == ["prompt_failed"]


@integration
async def test_initiator_prompt_raises_cancels_with_user_abort(node_factory, caplog, fast):
    """L1: `on_prompt` của A (vai khởi xướng) raise → A `prompt_failed` ngay (không đợi hết giờ),
    B nhận `pair_abort{user}` → `peer_rejected`; không ai lưu gì."""
    caplog.set_level(logging.DEBUG)
    B = await node_factory("B", accept_pairing=True)  # B không trả lời
    A = await node_factory("A", answer=True, raise_in_prompt=True)
    t0 = time.monotonic()
    result = await pair(A, B)
    took = time.monotonic() - t0
    assert result.outcome == PairingOutcome.PROMPT_FAILED
    assert result.role == Role.INITIATOR
    assert result.device is None
    assert A.rec.finished == [result]
    assert len(A.rec.prompts) == 1
    assert A.rec.decide_results == [True]
    assert took < fast.CONFIRM_TIMEOUT, f"A mất {took:.2f} s: phiên không bị hủy ngay"

    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["peer_rejected"]
    assert B.rec.finished[0].peer_reason == "user"
    assert A.store.devices() == [] and B.store.devices() == []
    assert _no_trusted_devices(A.dir) and _no_trusted_devices(B.dir)
    assert A.pairing.gate.failures(LOCAL) == 0
    assert gates_idle(A, B)
    assert _app_errors(caplog)


@integration
async def test_initiator_prompt_raises_sends_user_abort_and_never_confirms(
    node_factory, fake_server, tmp_path
):
    """L1, trên dây: bên trả lời giả trung thực; A không hiện được mã → gửi `pair_abort{user}`,
    không bao giờ gửi `pair_confirm`."""
    A = await node_factory("A", answer=True, raise_in_prompt=True)
    srv = load_or_create_identity(tmp_path / "srv")
    log: list = []
    port = await fake_server(srv, _fake_responder_script(srv, "honest", log))
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.PROMPT_FAILED
    await wait_until(lambda: {"type": "pair_abort", "reason": "user"} in log, 3, "chưa nhận pair_abort{user}")
    assert all(m.get("type") != "pair_confirm" for m in log), log
    assert log[-1] == {"type": "pair_abort", "reason": "user"}
    assert A.store.devices() == []
    assert A.pairing.gate.active is None


@integration
async def test_replacement_responder_prompt_failure_is_returned_by_pair_with(node_factory):
    """L1, ca biên: hai bên cùng chủ động, bên lớn nhường; phiên trả lời thay thế của nó không hiện
    được mã → `pair_with` của bên lớn trả `prompt_failed` (vai RESPONDER), bên nhỏ `peer_busy`."""
    A = await node_factory("A", answer=True)
    B = await node_factory("B", answer=True)
    lo, hi = sorted([A, B], key=lambda n: n.id)
    hi.rec.raise_in_prompt = True
    r_lo, r_hi = await asyncio.wait_for(
        asyncio.gather(lo.pairing.pair_with([LOCAL], hi.port), hi.pairing.pair_with([LOCAL], lo.port)),
        20,
    )
    await asyncio.sleep(0.1)
    assert r_hi.outcome == PairingOutcome.PROMPT_FAILED, (r_lo.outcome, r_hi.outcome, r_hi.role)
    assert r_hi.role == Role.RESPONDER
    assert r_lo.outcome == PairingOutcome.PEER_BUSY
    assert hi.rec.finished == [r_hi], outcomes(hi.rec)
    assert lo.rec.finished == [r_lo], outcomes(lo.rec)
    assert len(hi.rec.prompts) == 1 and lo.rec.prompts == []
    assert TrustStore.load(lo.dir).get(hi.id) is None
    assert TrustStore.load(hi.dir).get(lo.id) is None
    assert gates_idle(A, B)


# --- L4: số mã đã hiện gần đây (`PairingPrompt.recent_codes`) và giới hạn 5 mã / 60 s -----------------


@integration
async def test_prompt_recent_codes_counts_responder_codes_only(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", accept_pairing=True, answer=True)
    for n in range(1, 4):
        assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
        await B.rec.wait_finished(n)
    assert [p.recent_codes for p in B.rec.prompts] == [1, 2, 3]
    assert all(type(p.recent_codes) is int for p in B.rec.prompts)
    assert [p.recent_codes for p in A.rec.prompts] == [0, 0, 0]

    # Đổi vai: B khởi xướng (vẫn 0 dù B đã hiện 3 mã ở vai trả lời); A trả lời lần đầu → 1.
    assert (await pair(B, A)).outcome == PairingOutcome.PAIRED
    await A.rec.wait_finished(4)
    assert B.rec.prompts[-1].role == Role.INITIATOR and B.rec.prompts[-1].recent_codes == 0
    assert A.rec.prompts[-1].role == Role.RESPONDER and A.rec.prompts[-1].recent_codes == 1


@integration
async def test_code_is_counted_even_when_prompt_raises(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=True, raise_in_prompt=True)
    A = await node_factory("A", answer=True)
    assert (await pair(A, B)).outcome == PairingOutcome.PEER_BUSY
    await B.rec.wait_finished(1)
    loop = asyncio.get_running_loop()
    assert B.pairing.gate.recent_codes(loop.time()) == 1
    B.rec.raise_in_prompt = False
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    assert [p.recent_codes for p in B.rec.prompts] == [1, 2]


@pytest.mark.slow
@integration
async def test_sixth_code_in_window_is_busy_without_prompt(node_factory, raw_pairing_client, tmp_path):
    """L4: B đã hiện 5 mã trong 60 s → yêu cầu kế tiếp nhận `pair_abort{busy}`, B không hỏi, không
    gọi `on_finished`, không tính vào bộ đếm theo IP. Hằng số thật (5 mã / 60 s)."""
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    for n in range(1, 6):
        assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
        await B.rec.wait_finished(n)
    assert [p.recent_codes for p in B.rec.prompts] == [1, 2, 3, 4, 5]

    sixth = await pair(A, B)
    assert sixth.outcome == PairingOutcome.PEER_BUSY
    assert sixth.peer_reason == "busy"

    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    msgs = await c.read_until_closed(3)
    assert msgs == [{"type": "pair_abort", "reason": "busy"}], msgs

    await asyncio.sleep(0.2)
    assert len(B.rec.prompts) == 5 and len(B.rec.finished) == 5
    assert B.pairing.gate.failures(LOCAL) == 0
    assert B.store.get(raw_id.device_id) is None
    assert B.pairing.gate.active is None


@pytest.mark.slow
@integration
async def test_code_limit_frees_after_window_on_loop_clock(node_factory, monkeypatch):
    """L4: cửa sổ tính theo `loop.time()` của node; hết cửa sổ thì lại được nhận (hằng số rút ngắn)."""
    from teleport.core import pairing as core_pairing

    window = 3.0  # đủ rộng để 2,5 lần ghép đôi xong trong cửa sổ cả trên CI chậm
    monkeypatch.setattr(core_pairing, "MAX_CODES_PER_WINDOW", 2)
    monkeypatch.setattr(core_pairing, "CODE_WINDOW", window)
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    for n in (1, 2):
        assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
        await B.rec.wait_finished(n)
    loop = asyncio.get_running_loop()
    assert loop.time() < B.rec.prompt_loop_times[0] + window, "máy test quá chậm: mã đầu đã ra khỏi cửa sổ"
    assert (await pair(A, B)).outcome == PairingOutcome.PEER_BUSY
    assert len(B.rec.prompts) == 2

    wait = B.rec.prompt_loop_times[1] + window + 0.1 - loop.time()
    await asyncio.sleep(max(0.0, wait))
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    assert [p.recent_codes for p in B.rec.prompts] == [1, 2, 1]


@integration
async def test_p26_store_add_failure_gives_save_failed(node_factory, monkeypatch):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)

    def failing_add(*args, **kwargs):
        raise TrustStoreError("giả lập không ghi được trusted.json")

    monkeypatch.setattr(B.store, "add", failing_add)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["save_failed"]
    assert B.rec.finished[0].device is None
    assert result.outcome == PairingOutcome.PAIRED
    assert B.pairing.gate.failures(LOCAL) == 0  # gate finish với PAIRED
    assert B.store.get(A.id) is None
    assert gates_idle(A, B)


@integration
async def test_p27_logs_never_contain_code_or_pem(node_factory, caplog):
    caplog.set_level(logging.DEBUG)
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    assert (await pair(A, B)).outcome == PairingOutcome.PAIRED
    await B.rec.wait_finished(1)
    await asyncio.sleep(0.1)
    text = caplog.text
    code = A.rec.prompts[0].code
    assert not re.search(rf"(?<!\d){code}(?!\d)", text)
    assert format_code(code) not in text
    assert "BEGIN CERTIFICATE" not in text
    for ident in (A.identity, B.identity):
        body_line = ident.cert_pem().splitlines()[1]
        assert body_line not in text
    # Có log INFO kết thúc phiên (3.3), chỉ ghi device_id[:8].
    infos = [
        r.getMessage()
        for r in caplog.records
        if r.levelno == logging.INFO and r.name.startswith("teleport.app")
    ]
    assert any(B.id[:8] in m for m in infos), infos
    assert not any(B.id in m for m in infos), "log chỉ được ghi device_id[:8]"


# --- Các ca thêm theo đặc tả (không đánh số trong bảng 4.5) -------------------------------------------


async def _close_after_tls(reader, writer):
    writer.close()


def _hello_script(identity, **overrides):
    async def script(reader, writer):
        hello = {
            "type": "hello",
            "protocol": PROTOCOL_VERSION,
            "device_id": identity.device_id,
            "name": "Srv",
            "app_version": "0.0.0",
            "os": "linux",
        }
        hello.update(overrides)
        writer.write(encode_message(hello))
        await writer.drain()
        try:
            await asyncio.sleep(10)
        finally:
            writer.close()

    return script


@integration
@pytest.mark.parametrize("case", ["rejected", "version_mismatch", "identity_mismatch"])
async def test_connect_errors_map_to_outcomes(node_factory, fake_server, tmp_path, app_helpers, case):
    """3.1 bước 5: Rejected / VersionMismatch / IdentityMismatch → kết quả tương ứng."""
    A = await node_factory("A")
    srv = load_or_create_identity(tmp_path / "srv")
    if case == "rejected":
        script = _close_after_tls
    elif case == "version_mismatch":
        script = _hello_script(srv, protocol=PROTOCOL_VERSION + 1)
    else:
        script = _hello_script(srv, device_id=app_helpers.new_device_id())
    port = await fake_server(srv, script)
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome(case)
    assert A.rec.finished == [result]
    assert A.rec.prompts == []
    assert A.pairing.gate.active is None


@integration
async def test_pair_with_while_busy_returns_busy_without_connecting(node_factory, fake_server, tmp_path):
    """3.1 bước 3: đang có phiên → BUSY, session_id None, không kết nối, vẫn gọi on_finished."""
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()

    connections = []

    async def count(reader, writer):
        connections.append(1)
        writer.close()

    srv = load_or_create_identity(tmp_path / "srv")
    port = await fake_server(srv, count)
    busy = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 5)
    assert busy.outcome == PairingOutcome.BUSY
    assert busy.session_id is None
    assert busy.role == Role.INITIATOR
    assert (busy.address, busy.port) == (LOCAL, port)
    await asyncio.sleep(0.2)
    assert connections == []
    assert busy in A.rec.finished

    A.pairing.decide(A.rec.prompts[0].session_id, False)
    first = await asyncio.wait_for(task, 5)
    assert first.outcome == PairingOutcome.USER_REJECTED
    assert len(A.rec.finished) == 2


@integration
async def test_incoming_after_service_close_is_busy(node_factory):
    """2.4 `close()`: sau đó `handle_incoming` trả lời BUSY."""
    A = await node_factory("A", accept_pairing=True, answer=True)
    B = await node_factory("B", answer=True)
    await A.pairing.close()
    result = await pair(B, A)
    assert result.outcome == PairingOutcome.PEER_BUSY
    await asyncio.sleep(0.2)
    assert A.rec.prompts == [] and A.rec.finished == []


@integration
async def test_hard_cancel_of_pair_with(node_factory):
    """3.1 bước 8: task bị hủy → pair_abort{user}, on_finished(CANCELLED), rồi CancelledError."""
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()
    t0 = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert outcomes(A.rec) == ["cancelled"]
    assert A.pairing.gate.active is None
    await B.rec.wait_finished(1, timeout=3)
    assert outcomes(B.rec) == ["peer_rejected"]
    assert B.rec.finished_times[0] - t0 <= 1.5


@integration
async def test_cancel_all_while_connecting(node_factory, fake_server, tmp_path, fast):
    """2.4 `cancel_all`: hủy cả phiên khởi xướng đang open_pairing → CANCELLED, nhanh hơn hết giờ."""
    A = await node_factory("A")

    async def silent(reader, writer):
        await asyncio.sleep(30)

    port = await fake_server(None, silent, use_tls=False)  # TCP nhận nhưng không bao giờ bắt tay TLS
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], port), name="test.pair")
    await asyncio.sleep(0.2)
    assert not task.done()
    t0 = time.monotonic()
    await asyncio.wait_for(A.pairing.cancel_all(), 5)
    result = await asyncio.wait_for(task, 5)
    assert result.outcome == PairingOutcome.CANCELLED
    assert time.monotonic() - t0 < fast.OPENING_TIMEOUT * 0.8
    assert A.rec.finished == [result]
    assert A.pairing.gate.active is None


@integration
async def test_all_background_tasks_are_named(node_factory):
    """3.8 "Mọi task có tên (`teleport.pairing*`, `teleport.node*`)"; kết nối là `teleport.connection*`."""
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()
    await asyncio.sleep(0.05)
    me = asyncio.current_task()
    asyncio_dir = os.path.dirname(asyncio.__file__)

    def internal(t: asyncio.Task) -> bool:
        # Task của chính asyncio (ví dụ IocpProactor.accept trên Windows), không phải của Teleport.
        code = getattr(t.get_coro(), "cr_code", None)
        return code is not None and os.path.dirname(code.co_filename) == asyncio_dir

    tasks = [
        t
        for t in asyncio.all_tasks()
        if t is not me and not t.get_name().startswith("test.") and not internal(t)
    ]
    assert tasks, "phải có task của phiên đang chạy"
    unnamed = [f"{t.get_name()}: {t.get_coro()!r}" for t in tasks if not t.get_name().startswith("teleport.")]
    assert unnamed == [], unnamed
    A.pairing.decide(A.rec.prompts[0].session_id, False)
    await asyncio.wait_for(task, 5)


@integration
async def test_pair_confirm_flood_is_rejected_after_second_frame(node_factory, raw_pairing_client, tmp_path):
    """3.3/3.8: message kế tiếp chỉ đọc khi message trước xử lý xong; `pair_confirm` thứ hai → invalid."""
    B = await node_factory("B", accept_pairing=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.run_to_code(B.identity.fingerprint)
    c.send_bytes(encode_message({"type": "pair_confirm"}) * 500)
    await c.drain()
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs
    await B.rec.wait_finished(1)
    assert outcomes(B.rec) == ["protocol_error"]
    assert B.store.devices() == []
    assert B.pairing.gate.active is None


# =================================================================================================
# PR-4 (đặc tả PR-4 mục 4.7 PA1; mục 4.5 NL13 = backlog b)
# =================================================================================================

PA1_ROUNDS = 5
TEST_NET = "192.0.2.1"  # TEST-NET-1: không có máy nào; kết nối treo hoặc lỗi ngay tùy mạng


@pytest.mark.slow
@integration
async def test_pa1_yield_rule_with_several_addresses(node_factory, fast):
    """Backlog d: bên lớn hơn thử `[192.0.2.1, 127.0.0.1]`, yêu cầu của bên nhỏ tới từ 127.0.0.1
    (địa chỉ phụ của phiên khởi xướng) → vẫn coi là hai bên cùng chủ động và bên lớn nhường.

    Kỳ vọng như P18: mỗi bên đúng một lời hỏi, cùng mã, hai kho có nhau, mỗi bên đúng một kết quả
    PAIRED. Không phải đợi hết OPENING_TIMEOUT của địa chỉ treo.
    """
    tally: list[str] = []
    for i in range(PA1_ROUNDS):
        A = await node_factory(f"A{i}", accept_pairing=True, answer=True)
        B = await node_factory(f"B{i}", accept_pairing=True, answer=True)
        lo, hi = sorted([A, B], key=lambda n: n.id)
        t0 = time.monotonic()
        r_lo, r_hi = await asyncio.wait_for(
            asyncio.gather(
                lo.pairing.pair_with([LOCAL], hi.port),
                hi.pairing.pair_with([TEST_NET, LOCAL], lo.port),
            ),
            20,
        )
        took = time.monotonic() - t0
        await asyncio.sleep(0.1)
        tally.append(f"{r_lo.outcome}/{r_hi.outcome}/{r_hi.role}")
        where = f"lần {i + 1}/{PA1_ROUNDS}, các lần đến giờ: {tally}"
        assert r_lo.outcome == PairingOutcome.PAIRED, where
        assert r_hi.outcome == PairingOutcome.PAIRED, where
        assert r_lo.role == Role.INITIATOR, where
        assert r_hi.role == Role.RESPONDER, where
        assert lo.rec.finished == [r_lo], (where, outcomes(lo.rec))
        assert hi.rec.finished == [r_hi], (where, outcomes(hi.rec))
        assert len(lo.rec.prompts) == 1 and len(hi.rec.prompts) == 1, where
        assert lo.rec.prompts[0].code == hi.rec.prompts[0].code, where
        assert TrustStore.load(lo.dir).get(hi.id) is not None, where
        assert TrustStore.load(hi.dir).get(lo.id) is not None, where
        assert gates_idle(A, B), where
        assert took < fast.OPENING_TIMEOUT, f"{where}: mất {took:.2f} s (đợi hết thời gian của {TEST_NET}?)"
        await A.close()
        await B.close()


NL13_TRIES = 5


@integration
async def test_nl13_cancel_pair_with_while_waiting_for_replacement(node_factory):
    """Backlog b: task `pair_with` của bên lớn hơn đã nhường (gate có slot RESPONDER) bị hủy.

    → task raise CancelledError; phiên thay thế kết thúc CANCELLED (đúng một on_finished); bên nhỏ
    hơn nhận PEER_REJECTED với `peer_reason == "user"`. Cuộc đua đã biết (bên lớn nhận `busy` trước
    khi kịp nhường) thì thử lại, tối đa NL13_TRIES lần.
    """
    races: list[str] = []
    for i in range(NL13_TRIES):
        A = await node_factory(f"A{i}", accept_pairing=True)
        B = await node_factory(f"B{i}", accept_pairing=True)
        lo, hi = sorted([A, B], key=lambda n: n.id)
        t_lo = asyncio.create_task(lo.pairing.pair_with([LOCAL], hi.port), name="test.pair-lo")
        t_hi = asyncio.create_task(hi.pairing.pair_with([LOCAL], lo.port), name="test.pair-hi")
        await wait_until(
            lambda hi=hi, t_hi=t_hi: (
                t_hi.done()
                or (hi.pairing.gate.active is not None and hi.pairing.gate.active.role == Role.RESPONDER)
            ),
            5,
            "bên lớn chưa nhường",
        )
        if t_hi.done():
            races.append(str(t_hi.result().outcome))
            t_lo.cancel()
            await asyncio.gather(t_lo, return_exceptions=True)
            await A.close()
            await B.close()
            continue
        await hi.rec.wait_prompts()
        await lo.rec.wait_prompts()
        assert not t_hi.done(), "pair_with của bên đã nhường phải chờ phiên thay thế"
        t_hi.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(t_hi, 5)
        await hi.rec.wait_finished(1, timeout=3)
        await asyncio.sleep(0.2)
        assert outcomes(hi.rec) == ["cancelled"], outcomes(hi.rec)
        assert hi.rec.finished[0].role == Role.RESPONDER
        r_lo = await asyncio.wait_for(t_lo, 5)
        assert r_lo.outcome == PairingOutcome.PEER_REJECTED
        assert r_lo.peer_reason == "user"
        assert lo.rec.finished == [r_lo]
        assert TrustStore.load(hi.dir).get(lo.id) is None
        assert TrustStore.load(lo.dir).get(hi.id) is None
        assert gates_idle(A, B)
        return
    pytest.skip(f"cuộc đua đã biết xảy ra cả {NL13_TRIES} lần: {races}")


# =================================================================================================
# Nhóm (a) của đợt kiểm tra PR #10: M1, M4, M5, L2, L3, L4 ở tầng app (tiêu chí xong của kế hoạch)
# =================================================================================================

# CLOSE_TIMEOUT khi máy kia cố ý không trả close_notify: đủ dài để hủy rơi vào bước đóng gọn.
STALL_CLOSE_TIMEOUT = 2.0
OLD_PAIRED_AT = datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC)


def _errors_logged(caplog) -> list[str]:
    """Mọi bản ghi log mức ERROR trở lên (mọi logger, kể cả asyncio)."""
    return [f"{r.name}: {r.getMessage()}" for r in caplog.records if r.levelno >= logging.ERROR]


def _srv_hello(identity, name: str = "Srv") -> dict:
    return {
        "type": "hello",
        "protocol": PROTOCOL_VERSION,
        "device_id": identity.device_id,
        "name": name,
        "app_version": "0.0.0",
        "os": "linux",
    }


def _stalling_responder_script(identity, state: dict):
    """Bên trả lời giả trung thực tới khi hai bên xác nhận, rồi không bao giờ trả close_notify.

    Đọc `pair_confirm` của A, ngừng đọc (`pause_reading`: close_notify của A nằm yên trong bộ
    đệm), gửi `pair_confirm` của mình rồi giữ kết nối mở. Bước đóng gọn sau PAIRED của A vì thế
    treo tới CLOSE_TIMEOUT (kịch bản M4 trong báo cáo kiểm tra).
    """
    n_b = secrets.token_bytes(32)

    async def script(reader, writer):
        writer.write(encode_message(_srv_hello(identity)))
        await writer.drain()
        await read_message(reader, 16384)  # hello của A
        await read_message(reader, 16384)  # pair_request
        commitment = ref_commitment(identity.fingerprint, n_b)
        writer.write(encode_message({"type": "pair_commit", "commitment": commitment}))
        await writer.drain()
        await read_message(reader, 16384)  # pair_nonce
        writer.write(encode_message({"type": "pair_reveal", "nonce": n_b.hex()}))
        await writer.drain()
        state["confirm"] = await read_message(reader, 16384)
        writer.transport.pause_reading()
        writer.write(encode_message({"type": "pair_confirm"}))
        await writer.drain()
        await asyncio.sleep(60)  # fake_server hủy task này khi test xong

    return script


def _target_script(identity, seen: asyncio.Event, log: list, *, stall: bool):
    """Máy đích giả của `pair_with` (bên nhỏ hơn khi hai bên cùng chủ động).

    Gửi hello, đọc hello + `pair_request`, đặt `seen`, rồi không trả lời gì. `stall=True`: ngừng
    đọc luôn (không trả close_notify, bước đóng của bên khởi xướng treo tới hạn); False: đọc tiếp,
    ghi mọi message vào `log`, thêm "eof" khi kết nối đóng.
    """

    async def script(reader, writer):
        writer.write(encode_message(_srv_hello(identity, "Lo")))
        await writer.drain()
        log.append(await read_message(reader, 16384))  # hello
        log.append(await read_message(reader, 16384))  # pair_request
        seen.set()
        if stall:
            writer.transport.pause_reading()
            await asyncio.sleep(60)
            return
        while (msg := await read_message(reader, 16384)) is not None:
            log.append(msg)
        log.append("eof")

    return script


# --- M1: chứng chỉ có SAN `cryptography` không đọc được --------------------------------------------


@integration
@pytest.mark.parametrize("san", ["x400Address", "EDIPartyName"])
async def test_m1_responder_rejects_cert_with_unreadable_san(
    node_factory, raw_pairing_client, app_helpers, tmp_path, monkeypatch, caplog, san
):
    """M1, vai trả lời: `pair_request` mang chứng chỉ có SAN x400Address/EDIPartyName là chứng chỉ
    không hợp lệ như mọi chứng chỉ hỏng khác (protocol §5.1).

    → máy kia nhận `pair_abort{invalid}`; phiên PROTOCOL_ERROR, chưa hiện mã (`code_shown` False);
    IP bị tính một lần thất bại, nên yêu cầu kế tiếp trong 10 s nhận `pair_abort{busy}`; không có
    log ERROR nào, log không chứa PEM (mvp N9).
    """
    from teleport.core import pairing as core_pairing

    caplog.set_level(logging.DEBUG)
    # Thời gian chờ thật của lần thất bại đầu (10 s); `fast` rút còn 0,5 s.
    monkeypatch.setattr(core_pairing, "BACKOFF_BASE", 10.0)
    monkeypatch.setattr(core_pairing, "BACKOFF_MAX", 600.0)
    B = await node_factory("B", accept_pairing=True, answer=True)
    device_id = app_helpers.new_device_id()
    raw_san = app_helpers.SAN_X400 if san == "x400Address" else app_helpers.SAN_EDI
    pem, _ = app_helpers.cert_with_raw_san(device_id, raw_san)

    c = await raw_pairing_client(B.port)
    c.send_dict(app_helpers.hello_dict(device_id))
    c.send_dict({"type": "pair_request", "cert": pem})
    await c.drain()
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs

    await B.rec.wait_finished(1)
    result = B.rec.finished[0]
    assert result.outcome == PairingOutcome.PROTOCOL_ERROR
    assert result.role == Role.RESPONDER
    assert result.code_shown is False
    assert result.device is None
    assert B.rec.prompts == []
    await wait_until(lambda: B.pairing.gate.active is None, 1, "gate chưa được nhả")
    assert B.pairing.gate.failures(LOCAL) == 1
    assert B.store.devices() == []

    # Yêu cầu kế tiếp từ cùng IP (máy khác, chứng chỉ hợp lệ) trong thời gian chờ → busy.
    await asyncio.sleep(0.1)  # để listener nhả chỗ ẩn danh của kết nối trước (1 mỗi IP)
    other = load_or_create_identity(tmp_path / "other")
    c2 = await raw_pairing_client(B.port)
    await c2.begin(other)
    assert await c2.read_until_closed(3) == [{"type": "pair_abort", "reason": "busy"}]
    await asyncio.sleep(0.1)
    assert len(B.rec.finished) == 1 and B.rec.prompts == []
    assert B.pairing.gate.failures(LOCAL) == 1

    assert _errors_logged(caplog) == []
    assert "BEGIN CERTIFICATE" not in caplog.text
    assert pem.splitlines()[1] not in caplog.text


@integration
async def test_m1_initiator_server_cert_with_unreadable_san_is_identity_mismatch(
    node_factory, fake_server, app_helpers, tmp_path, caplog
):
    """M1, vai khởi xướng: server TLS mang chứng chỉ có SAN x400Address → `pair_with` trả
    IDENTITY_MISMATCH (không ném), `on_finished` đúng một lần, không hiện mã, không log ERROR."""
    caplog.set_level(logging.DEBUG)
    A = await node_factory("A", answer=True)
    device_id = app_helpers.new_device_id()
    pem, key = app_helpers.cert_with_raw_san(device_id, app_helpers.SAN_X400)
    srv = app_helpers.identity_from_pem(tmp_path / "srv", device_id, pem, key)
    port = await fake_server(srv, _hello_script(srv))

    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], port), 10)
    assert result.outcome == PairingOutcome.IDENTITY_MISMATCH
    assert result.role == Role.INITIATOR
    assert result.device is None
    assert result.code_shown is False
    await asyncio.sleep(0.1)
    assert A.rec.finished == [result]
    assert A.rec.prompts == []
    assert A.store.devices() == []
    assert A.pairing.gate.active is None
    assert _errors_logged(caplog) == []


# --- M4: bị hủy sau khi đã chốt thì `pair_with` trả kết quả thật ---------------------------------


@integration
async def test_m4_cancel_while_closing_after_paired_returns_paired(
    node_factory, fake_server, tmp_path, monkeypatch, fast
):
    """M4: hai bên đã xác nhận, A đã lưu máy kia và đang đóng gọn (máy kia không trả close_notify)
    thì task `pair_with` bị hủy → `pair_with` trả PAIRED thay vì ném CancelledError, lệnh hủy được
    gỡ (`cancelling() == 0`), `on_finished` đúng một lần với PAIRED, kho có thiết bị."""
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", STALL_CLOSE_TIMEOUT)
    A = await node_factory("A", answer=True)
    srv = load_or_create_identity(tmp_path / "srv")
    state: dict = {}
    port = await fake_server(srv, _stalling_responder_script(srv, state))

    async def run():
        result = await A.pairing.pair_with([LOCAL], port)
        return result, asyncio.current_task().cancelling()

    task = asyncio.create_task(run(), name="test.pair")
    await wait_until(lambda: A.store.get(srv.device_id) is not None, 5, "A chưa lưu máy kia")
    await asyncio.sleep(0.1)
    assert state.get("confirm") == {"type": "pair_confirm"}
    assert not task.done(), "bước đóng gọn sau PAIRED phải đang chờ close_notify"

    task.cancel()
    try:
        result, cancelling = await asyncio.wait_for(task, STALL_CLOSE_TIMEOUT + fast.SLACK)
    except asyncio.CancelledError:
        pytest.fail("pair_with ném CancelledError dù hai bên đã xác nhận và trusted.json đã lưu")
    assert result.outcome == PairingOutcome.PAIRED
    assert cancelling == 0, "trả kết quả đã chốt thì phải gỡ lệnh hủy (uncancel)"
    assert A.rec.finished == [result]
    assert result.device is not None and result.device.device_id == srv.device_id
    assert result.code_shown is True
    assert TrustStore.load(A.dir).get(srv.device_id).fingerprint == srv.fingerprint
    assert A.pairing.gate.active is None


@integration
async def test_m4_cancel_while_closing_after_save_failed_returns_save_failed(
    node_factory, fake_server, tmp_path, monkeypatch, fast
):
    """M4, biến thể: hai bên đã xác nhận nhưng `store.add` lỗi (SAVE_FAILED cũng là kết quả đã chốt)
    → hủy trong lúc đóng gọn vẫn trả SAVE_FAILED, không ném, `on_finished` đúng một lần."""
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", STALL_CLOSE_TIMEOUT)
    A = await node_factory("A", answer=True)
    srv = load_or_create_identity(tmp_path / "srv")
    port = await fake_server(srv, _stalling_responder_script(srv, {}))
    add_calls: list[str] = []

    def failing_add(peer, name, **kwargs):
        add_calls.append(peer.device_id)
        raise TrustStoreError("giả lập không ghi được trusted.json")

    monkeypatch.setattr(A.store, "add", failing_add)

    async def run():
        result = await A.pairing.pair_with([LOCAL], port)
        return result, asyncio.current_task().cancelling()

    task = asyncio.create_task(run(), name="test.pair")
    await wait_until(lambda: add_calls == [srv.device_id], 5, "A chưa thử lưu máy kia")
    await asyncio.sleep(0.1)
    assert not task.done(), "bước đóng gọn sau khi chốt phải đang chờ close_notify"

    task.cancel()
    try:
        result, cancelling = await asyncio.wait_for(task, STALL_CLOSE_TIMEOUT + fast.SLACK)
    except asyncio.CancelledError:
        pytest.fail("pair_with ném CancelledError dù hai bên đã xác nhận (SAVE_FAILED)")
    assert result.outcome == PairingOutcome.SAVE_FAILED
    assert result.device is None
    assert cancelling == 0
    assert A.rec.finished == [result]
    assert A.pairing.gate.active is None


@pytest.mark.slow
@integration
async def test_m4_cancel_while_waiting_for_confirmed_replacement_returns_its_result(
    node_factory, fake_server, raw_pairing_client, app_helpers, tmp_path, monkeypatch, fast
):
    """M4, nhánh nhường phiên: `pair_with` của bên lớn đã nhường và đang chờ phiên trả lời thay thế;
    phiên đó đã chốt (hai bên xác nhận, đã lưu) và đang đóng gọn thì task bị hủy → `pair_with` chờ
    phiên đó xong rồi trả kết quả PAIRED của nó (vai RESPONDER), không ném CancelledError."""
    from teleport.core import pairing as core_pairing
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", STALL_CLOSE_TIMEOUT)
    monkeypatch.setattr(core_pairing, "MESSAGE_TIMEOUT", 10.0)  # phiên khởi xướng không tự hết giờ
    hi = await node_factory("H", answer=True)
    lo = app_helpers.identity_below(tmp_path / "lo", hi.id)
    seen = asyncio.Event()
    target_log: list = []
    port = await fake_server(lo, _target_script(lo, seen, target_log, stall=False))

    async def run():
        result = await hi.pairing.pair_with([LOCAL], port)
        return result, asyncio.current_task().cancelling()

    task = asyncio.create_task(run(), name="test.pair-hi")
    await asyncio.wait_for(seen.wait(), 5)
    outgoing = hi.pairing.gate.active
    assert outgoing is not None and outgoing.role == Role.INITIATOR

    # Bên nhỏ hơn (client thô, cùng 127.0.0.1) gửi yêu cầu tới hi: hi nhường, chuyển sang trả lời.
    c = await raw_pairing_client(hi.port)
    await c.begin(lo, "Lo")
    code = await c.run_to_code(hi.identity.fingerprint)
    assert await c.read_type("pair_confirm") == {"type": "pair_confirm"}  # hi đã bấm “Trùng”
    await wait_until(
        lambda: outgoing.id not in hi.pairing._runs and "eof" in target_log,
        3,
        "pair_with chưa tới bước chờ phiên thay thế",
    )
    assert {"type": "pair_abort", "reason": "busy"} in target_log
    c.writer.transport.pause_reading()  # không bao giờ trả close_notify: bước đóng của hi treo
    c.send_dict({"type": "pair_confirm"})
    await c.drain()
    await wait_until(lambda: hi.store.get(lo.device_id) is not None, 3, "hi chưa lưu máy kia")
    await asyncio.sleep(0.1)
    assert not task.done(), "phiên thay thế phải đang đóng gọn"

    task.cancel()
    try:
        result, cancelling = await asyncio.wait_for(task, STALL_CLOSE_TIMEOUT + fast.SLACK)
    except asyncio.CancelledError:
        pytest.fail("pair_with ném CancelledError dù phiên thay thế đã chốt PAIRED")
    assert result.outcome == PairingOutcome.PAIRED
    assert result.role == Role.RESPONDER
    assert result.peer_device_id == lo.device_id
    assert cancelling == 0
    assert hi.rec.finished == [result]
    assert [p.code for p in hi.rec.prompts] == [code]
    assert TrustStore.load(hi.dir).get(lo.device_id).fingerprint == lo.fingerprint
    assert hi.pairing.gate.active is None


# --- L2: hủy `pair_with` trong cửa sổ nhường phiên ------------------------------------------------


@integration
@pytest.mark.parametrize("nonce_at", ["sau_khi_huy", "cung_luc_huy"])
async def test_l2_cancel_pair_with_while_yielding_cancels_replacement(
    node_factory, fake_server, raw_pairing_client, app_helpers, tmp_path, monkeypatch, fast, nonce_at
):
    """L2: task `pair_with` bị hủy khi đang nhường phiên (đã có phiên trả lời thay thế, phiên khởi
    xướng còn đang đóng) → phiên thay thế cũng bị hủy: máy kia nhận `pair_abort{user}`, phiên đó
    kết thúc CANCELLED trong ≤ ABORT_ON_CANCEL_TIMEOUT + 1 s, không hiện mã sau lúc hủy (kể cả khi
    máy kia gửi `pair_nonce`); gate rảnh, không còn phiên nào.

    `nonce_at`: máy kia gửi `pair_nonce` sau khi `pair_with` đã ném CancelledError, hoặc ghi nó
    xuống socket ngay trước lệnh hủy (cùng một bước của loop). Ca sau: `pair_nonce` có thể tới
    trước lệnh hủy, khi đó mã được hiện TRƯỚC lúc hủy (cho phép); không bao giờ được hiện sau.
    """
    from teleport.app import pairing as app_pairing
    from teleport.core import pairing as core_pairing
    from teleport.net import connection

    # Máy đích không trả close_notify: phiên khởi xướng đã nhường còn đóng tới FAILED_CLOSE_TIMEOUT,
    # đủ rộng để lệnh hủy rơi đúng vào cửa sổ đó. Bên trả lời chờ pair_nonce lâu (không tự hết giờ).
    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    monkeypatch.setattr(app_pairing, "FAILED_CLOSE_TIMEOUT", 3.0)
    monkeypatch.setattr(core_pairing, "MESSAGE_TIMEOUT", 10.0)
    monkeypatch.setattr(core_pairing, "NONCE_TIMEOUT", 10.0)
    hi = await node_factory("H", answer=True)
    lo = app_helpers.identity_below(tmp_path / "lo", hi.id)
    seen = asyncio.Event()
    port = await fake_server(lo, _target_script(lo, seen, [], stall=True))
    task = asyncio.create_task(hi.pairing.pair_with([LOCAL], port), name="test.pair-hi")
    await asyncio.wait_for(seen.wait(), 5)
    outgoing = hi.pairing.gate.active
    assert outgoing is not None and outgoing.role == Role.INITIATOR

    c = await raw_pairing_client(hi.port)
    await c.begin(lo, "Lo")
    await c.read_commit()  # phiên trả lời thay thế đã chạy, đang chờ pair_nonce
    active = hi.pairing.gate.active
    assert active is not None and active.role == Role.RESPONDER
    assert outgoing.id in hi.pairing._runs and not task.done(), "phải đang trong cửa sổ nhường phiên"

    if nonce_at == "cung_luc_huy":
        c.send_dict(c.nonce_message())  # chưa nhường loop
    t0 = time.monotonic()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    if nonce_at == "sau_khi_huy":
        # Sau lúc hủy, máy kia vẫn gửi pair_nonce: phiên thay thế không được hiện mã hay tiết lộ n_B.
        await c.send_nonce()
    msgs = await c.read_until_closed(fast.ABORT_ON_CANCEL_TIMEOUT + 1 + fast.SLACK)

    await hi.rec.wait_finished(1, timeout=fast.ABORT_ON_CANCEL_TIMEOUT + 1)
    took = hi.rec.finished_times[0] - t0
    assert took <= fast.ABORT_ON_CANCEL_TIMEOUT + 1, f"phiên thay thế kết thúc sau {took:.2f} s"
    replacement = hi.rec.finished[0]
    assert replacement.outcome == PairingOutcome.CANCELLED
    assert replacement.role == Role.RESPONDER
    assert replacement.peer_device_id == lo.device_id
    late = [t - t0 for t in hi.rec.prompt_times if t >= t0]
    assert late == [], f"hiện mã sau lúc hủy (+{late} s)"
    assert msgs[-1:] == [{"type": "pair_abort", "reason": "user"}], msgs
    if nonce_at == "sau_khi_huy" or not hi.rec.prompts:
        assert msgs == [{"type": "pair_abort", "reason": "user"}], msgs
        assert hi.rec.prompts == []
    await wait_until(lambda: hi.pairing.gate.active is None and not hi.pairing._runs, 2, "còn phiên chưa dọn")
    await asyncio.sleep(0.1)
    assert len(hi.rec.finished) == 1
    assert hi.store.get(lo.device_id) is None


def _hold_after_close(monkeypatch, task_name: str, *, close_branch: bool) -> tuple[asyncio.Event, list]:
    """Giữ task `task_name` lại (ngủ dài, lệnh hủy cắt ngang) ngay sau lần `_perform` đầu tiên trả `Close`.

    `close_branch=True`: lần gọi ở nhánh Close của vòng `_drive` (có hạn chót): phiên đã DONE, đã
    gửi `pair_abort` nhưng chưa bắt đầu `conn.close()`. False: lần gọi trong nhánh hủy cứng (không
    hạn chót), nên ABORT_ON_CANCEL_TIMEOUT hết trước khi `conn.close()` kịp chạy.
    Trả (`held`: đặt khi bắt đầu giữ, `states`: trạng thái phiên lúc đó).
    """
    from teleport.app import pairing as app_pairing

    real = app_pairing.PairingService._perform
    held = asyncio.Event()
    states: list = []

    async def perform(self, run, conn, actions, deadline=None):
        close = await real(self, run, conn, actions, deadline)
        task = asyncio.current_task()
        if (
            close is not None
            and not held.is_set()
            and task is not None
            and task.get_name() == task_name
            and (deadline is not None) == close_branch
        ):
            states.append(run.session.state)
            held.set()
            await asyncio.sleep(60)
        return close

    monkeypatch.setattr(app_pairing.PairingService, "_perform", perform)
    return held, states


@integration
async def test_l2_cancel_after_yielded_session_closed_is_bounded(
    node_factory, fake_server, raw_pairing_client, app_helpers, tmp_path, monkeypatch, fast
):
    """L2, thứ tự CI macOS gặp: phiên khởi xướng đã nhường (DONE, đã gửi `pair_abort{busy}`) nhưng
    chưa bắt đầu đóng kết nối thì `pair_with` bị hủy → task kết thúc trong ABORT_ON_CANCEL_TIMEOUT
    (+ SLACK), không chờ máy đích (không trả close_notify) tới CLOSE_TIMEOUT của net; phiên thay thế
    vẫn bị hủy (CANCELLED), gate rảnh.
    """
    from teleport.app import pairing as app_pairing
    from teleport.core import pairing as core_pairing
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    monkeypatch.setattr(app_pairing, "FAILED_CLOSE_TIMEOUT", 3.0)
    monkeypatch.setattr(core_pairing, "MESSAGE_TIMEOUT", 10.0)
    monkeypatch.setattr(core_pairing, "NONCE_TIMEOUT", 10.0)
    held, states = _hold_after_close(monkeypatch, "test.pair-hi", close_branch=True)
    hi = await node_factory("H", answer=True)
    lo = app_helpers.identity_below(tmp_path / "lo", hi.id)
    seen = asyncio.Event()
    port = await fake_server(lo, _target_script(lo, seen, [], stall=True))
    task = asyncio.create_task(hi.pairing.pair_with([LOCAL], port), name="test.pair-hi")
    await asyncio.wait_for(seen.wait(), 5)
    c = await raw_pairing_client(hi.port)
    await c.begin(lo, "Lo")
    await c.read_commit()
    await asyncio.wait_for(held.wait(), 2)
    assert states == [core_pairing.State.DONE]
    assert not task.done()

    t0 = time.monotonic()
    task.cancel()
    limit = fast.ABORT_ON_CANCEL_TIMEOUT + fast.SLACK
    assert limit < connection.CLOSE_TIMEOUT
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, limit)
    took = time.monotonic() - t0
    assert took <= limit, f"hủy pair_with mất {took:.2f} s"

    await hi.rec.wait_finished(1, timeout=fast.ABORT_ON_CANCEL_TIMEOUT + 1)
    assert [(f.role, f.outcome) for f in hi.rec.finished] == [(Role.RESPONDER, PairingOutcome.CANCELLED)]
    await wait_until(lambda: hi.pairing.gate.active is None and not hi.pairing._runs, 2, "còn phiên chưa dọn")


@integration
async def test_hard_cancel_cleanup_over_budget_still_aborts_connection(
    node_factory, fake_server, app_helpers, tmp_path, monkeypatch, fast
):
    """`pair_with` bị hủy khi đang chờ máy kia, và phần dọn dẹp hủy cứng (gửi `pair_abort{user}`)
    dùng hết ABORT_ON_CANCEL_TIMEOUT trước khi `conn.close()` kịp chạy → kết nối bị abort, task
    kết thúc trong ABORT_ON_CANCEL_TIMEOUT (+ SLACK), không đóng gọn tới CLOSE_TIMEOUT của net.
    """
    from teleport.net import connection

    monkeypatch.setattr(connection, "CLOSE_TIMEOUT", 5.0)
    held, _ = _hold_after_close(monkeypatch, "test.pair-hi", close_branch=False)
    hi = await node_factory("H")
    lo = app_helpers.identity_below(tmp_path / "lo", hi.id)
    seen = asyncio.Event()
    port = await fake_server(lo, _target_script(lo, seen, [], stall=True))
    task = asyncio.create_task(hi.pairing.pair_with([LOCAL], port), name="test.pair-hi")
    await asyncio.wait_for(seen.wait(), 5)

    t0 = time.monotonic()
    task.cancel()
    limit = fast.ABORT_ON_CANCEL_TIMEOUT + fast.SLACK
    assert limit < connection.CLOSE_TIMEOUT
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, limit)
    took = time.monotonic() - t0
    assert held.is_set(), "phần dọn dẹp hủy cứng chưa chạy"
    assert took <= limit, f"hủy pair_with mất {took:.2f} s"
    await hi.rec.wait_finished(1, timeout=1)
    assert [(f.role, f.outcome) for f in hi.rec.finished] == [(Role.INITIATOR, PairingOutcome.CANCELLED)]
    assert hi.pairing.gate.active is None and not hi.pairing._runs


# --- M5 lật lại (protocol 5.1, 5.5): máy lạ bị chặn trước khi hiện mã; ghép đôi lại thì đổi tên ---


@integration
@pytest.mark.parametrize("forgery", ["khoa_may_la", "chu_ky_rac"])
async def test_m5_stranger_with_public_cert_of_trusted_device_is_invalid_before_code(
    node_factory, raw_pairing_client, tmp_path, forgery
):
    """B tin V tên “PC-Nha”. Một máy lạ M (kết nối ẩn danh) gửi chứng chỉ công khai của V với tên
    “Laptop-Bob” nhưng không có khóa riêng của V: ký bằng khóa của chính M, hoặc chữ ký rác.

    → B kết thúc `protocol_error` ngay khi nhận `pair_nonce`: không hiện mã (`code_shown=False`,
    không có lời hỏi), không gửi `pair_reveal`, M nhận `pair_abort{invalid}`; `trusted.json` không
    đổi (tên, fingerprint, `paired_at`); IP của M bị tính một lần thất bại (chờ tăng dần)."""
    victim = load_or_create_identity(tmp_path / "V")
    stranger = load_or_create_identity(tmp_path / "M")
    load_or_create_identity(tmp_path / "B")
    TrustStore.load(tmp_path / "B").add(peer_cert_from_pem(victim.cert_pem()), "PC-Nha", now=OLD_PAIRED_AT)
    trusted = tmp_path / "B" / "trusted.json"
    before = trusted.read_bytes()
    B = await node_factory("B", accept_pairing=True, answer=True)

    c = await raw_pairing_client(B.port)
    await c.begin(victim, "Laptop-Bob", signing_key=stranger)
    await c.read_commit()
    if forgery == "khoa_may_la":
        await c.send_nonce()
    else:
        await c.send_nonce(signature_hex=secrets.token_hex(64))
    msgs = await c.read_until_closed(5)
    assert msgs == [INVALID], msgs
    assert all(m.get("type") != "pair_reveal" for m in msgs)

    await B.rec.wait_finished(1)
    result = B.rec.finished[0]
    assert result.outcome == PairingOutcome.PROTOCOL_ERROR
    assert result.code_shown is False
    assert result.device is None
    assert B.rec.prompts == []
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)
    assert B.pairing.gate.failures(LOCAL) == 1
    assert B.pairing.gate.blocked_until(LOCAL) is not None
    assert B.pairing.gate.recent_codes(asyncio.get_running_loop().time()) == 0, "không có mã nào được hiện"
    assert trusted.read_bytes() == before, "trusted.json bị ghi"
    for store in (B.store, TrustStore.load(B.dir)):
        device = store.get(victim.device_id)
        assert (device.name, device.fingerprint, device.paired_at) == (
            "PC-Nha",
            victim.fingerprint,
            OLD_PAIRED_AT,
        )
        assert len(store.devices()) == 1


@integration
async def test_m5_stranger_after_bad_signature_is_backed_off(node_factory, raw_pairing_client, tmp_path):
    """Sau một chữ ký sai, IP đó nhận `pair_abort{busy}` trong thời gian chờ tăng dần (protocol 5.3)."""
    victim = load_or_create_identity(tmp_path / "V")
    stranger = load_or_create_identity(tmp_path / "M")
    B = await node_factory("B", accept_pairing=True, answer=True)
    c = await raw_pairing_client(B.port)
    await c.begin(victim, "Laptop-Bob", signing_key=stranger)
    await c.read_commit()
    await c.send_nonce()
    assert await c.read_until_closed(5) == [INVALID]
    await wait_until(lambda: B.pairing.gate.active is None, 1.0)
    assert B.pairing.gate.failures(LOCAL) == 1

    again = await raw_pairing_client(B.port)
    await again.begin(stranger, "M")
    assert await again.read_until_closed(5) == [{"type": "pair_abort", "reason": "busy"}]
    assert B.rec.prompts == []


@integration
async def test_m5_real_repair_by_trusted_device_updates_name_as_responder(
    node_factory, raw_pairing_client, tmp_path
):
    """Ngược lại với máy lạ: chính V (có khóa riêng) ghép đôi lại với tên mới “Laptop-Mới” → B hiện
    mã, hai bên xác nhận, B cập nhật tên thành “Laptop-Mới” (RAM và đĩa), fingerprint giữ nguyên,
    `paired_at` mới; lời hỏi vẫn cho thấy tên đã lưu cũ (`known_name`)."""
    victim = load_or_create_identity(tmp_path / "V")
    load_or_create_identity(tmp_path / "B")
    TrustStore.load(tmp_path / "B").add(peer_cert_from_pem(victim.cert_pem()), "PC-Nha", now=OLD_PAIRED_AT)
    B = await node_factory("B", accept_pairing=True, answer=True)

    c = await raw_pairing_client(B.port)
    await c.begin(victim, "Laptop-Mới")
    code = await c.run_to_code(B.identity.fingerprint)
    assert await c.read_type("pair_confirm") == {"type": "pair_confirm"}
    c.send_dict({"type": "pair_confirm"})
    await c.drain()
    await c.read_until_closed(5)
    await B.rec.wait_finished(1)

    prompt = B.rec.prompts[0]
    assert prompt.code == code
    assert (prompt.peer_name, prompt.known_name) == ("Laptop-Mới", "PC-Nha")
    result = B.rec.finished[0]
    assert result.outcome == PairingOutcome.PAIRED
    assert result.code_shown is True
    assert (result.device.name, result.device.fingerprint) == ("Laptop-Mới", victim.fingerprint)
    for store in (B.store, TrustStore.load(B.dir)):
        device = store.get(victim.device_id)
        assert (device.name, device.fingerprint) == ("Laptop-Mới", victim.fingerprint)
        assert device.paired_at > OLD_PAIRED_AT
        assert len(store.devices()) == 1


@integration
@pytest.mark.parametrize("known_by", ["responder", "initiator", "both"])
async def test_m5_repair_updates_name_in_both_roles(node_factory, app_helpers, tmp_path, known_by):
    """D2: ghép đôi lại với máy thật (cùng danh tính) thì bên nào đã lưu cũng cập nhật tên theo
    `hello` (“A-cũ” → “A”, “B-cũ” → “B”) và `paired_at`. `PairingPrompt.known_name` = tên đã lưu ở bên
    đã ghép đôi, None ở bên ghép đôi lần đầu. Hai bên thật vẫn ghép đôi được (chữ ký đúng)."""
    id_a = app_helpers.ensure_identity(tmp_path / "A")
    id_b = app_helpers.ensure_identity(tmp_path / "B")
    if known_by in ("responder", "both"):
        TrustStore.load(tmp_path / "B").add(peer_cert_from_pem(id_a.cert_pem()), "A-cũ", now=OLD_PAIRED_AT)
    if known_by in ("initiator", "both"):
        TrustStore.load(tmp_path / "A").add(peer_cert_from_pem(id_b.cert_pem()), "B-cũ", now=OLD_PAIRED_AT)
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    assert (A.id, B.id) == (id_a.device_id, id_b.device_id)

    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.PAIRED
    rb = B.rec.finished[0]
    assert rb.outcome == PairingOutcome.PAIRED
    pa, pb = A.rec.prompts[0], B.rec.prompts[0]
    assert (pa.peer_name, pb.peer_name) == ("B", "A")
    assert pb.known_name == ("A-cũ" if known_by in ("responder", "both") else None)
    assert pa.known_name == ("B-cũ" if known_by in ("initiator", "both") else None)
    assert rb.device.name == "A" and result.device.name == "B"
    for store in (B.store, TrustStore.load(B.dir)):
        assert store.get(A.id).name == "A"
        assert store.get(A.id).paired_at > OLD_PAIRED_AT
    for store in (A.store, TrustStore.load(A.dir)):
        assert store.get(B.id).name == "B"
        assert store.get(B.id).paired_at > OLD_PAIRED_AT
    assert "A-cũ" not in (B.dir / "trusted.json").read_text(encoding="utf-8")
    assert "B-cũ" not in (A.dir / "trusted.json").read_text(encoding="utf-8")


@integration
async def test_fake_cert_helper_key_signs_valid_pair_nonce(
    node_factory, raw_pairing_client, app_helpers, tmp_path
):
    """`fake_cert_with_cn` trả kèm khóa: danh tính dựng từ đó ký được `pair_nonce` hợp lệ, nên B
    (chưa từng ghép đôi với nó) hiện mã."""
    B = await node_factory("B", accept_pairing=True)
    pem, key_pem = app_helpers.fake_cert_with_cn(app_helpers.new_device_id())
    own = app_helpers.identity_from_pem(tmp_path / "own", peer_cert_from_pem(pem).device_id, pem, key_pem)
    c = await raw_pairing_client(B.port)
    await c.begin(own, "Own")
    code = await c.run_to_code(B.identity.fingerprint)
    await B.rec.wait_prompts(1)
    assert B.rec.prompts[0].code == code
    c.abort()
    await B.rec.wait_finished(1, timeout=3)
    assert B.rec.finished[0].code_shown is True


# --- Danh tính hỏng ở `PairingService` (`load_pairing_signer` khi khởi tạo) -----------------------


async def test_service_with_key_not_matching_cert_raises_identity_error(service_parts, tmp_path):
    import dataclasses

    identity, hello, store, finished = service_parts
    other = load_or_create_identity(tmp_path / "khac")
    broken = dataclasses.replace(identity, key_path=other.key_path)
    with pytest.raises(IdentityError):
        make_service((broken, hello, store, finished))


async def test_service_with_corrupt_key_file_raises_identity_error(service_parts):
    identity, hello, store, finished = service_parts
    identity.key_path.write_bytes(b"rac")
    with pytest.raises(IdentityError):
        make_service((identity, hello, store, finished))


# --- L3: gửi `pair_confirm` lỗi thì không lưu -----------------------------------------------------

L3_CASES = [
    pytest.param(Role.RESPONDER, "tu_truoc", ConnectionLostError, id="tra-loi-tu-xac-nhan-truoc"),
    pytest.param(Role.RESPONDER, "may_kia_truoc", ConnectionLostError, id="tra-loi-may-kia-truoc"),
    pytest.param(Role.INITIATOR, "tu_truoc", ConnectionLostError, id="khoi-xuong-tu-xac-nhan-truoc"),
    pytest.param(Role.INITIATOR, "may_kia_truoc", ConnectionLostError, id="khoi-xuong-may-kia-truoc"),
    pytest.param(Role.RESPONDER, "tu_truoc", TimeoutError, id="tra-loi-gui-qua-han"),
    pytest.param(Role.INITIATOR, "may_kia_truoc", TimeoutError, id="khoi-xuong-gui-qua-han"),
]


@integration
@pytest.mark.parametrize(("failing_role", "order", "error"), L3_CASES)
async def test_l3_failed_pair_confirm_send_does_not_save(
    node_factory, app_helpers, monkeypatch, tmp_path, failing_role, order, error
):
    """L3: máy này gửi `pair_confirm` không xong (ConnectionLostError, hoặc quá hạn gửi) thì không
    được lưu, dù máy kia xác nhận trước hay sau (protocol §5.1: chỉ lưu khi đã GỬI xong và đã NHẬN).

    → `trusted.json` giữ nguyên nội dung và mtime; `on_trust_changed` không được gọi; kết quả
    CONNECTION_LOST; ở vai trả lời IP bị tính một lần thất bại. Máy kia cũng không lưu.
    Lỗi gửi được giả lập ở `Connection.send`, chỉ cho `pair_confirm` của bên `failing_role`
    (kết nối vẫn mở, như khi gửi quá SEND_TIMEOUT).
    """
    from teleport.net import connection as net_connection

    other = load_or_create_identity(tmp_path / "khac")
    for label in ("A", "B"):
        app_helpers.seed_trust(tmp_path / label, other.cert_pem(), "Khác")  # trusted.json có sẵn
    B = await node_factory("B", accept_pairing=True)
    A = await node_factory("A")
    failing, peer = (B, A) if failing_role == Role.RESPONDER else (A, B)
    failing_is_server = failing_role == Role.RESPONDER  # kết nối của bên trả lời là phía server

    real_send = net_connection.Connection.send
    real_receive = net_connection.Connection.receive
    attempts: list[str] = []
    received: list[tuple[bool, str | None]] = []

    async def flaky_send(self, msg):
        if self.is_server == failing_is_server and getattr(msg, "TYPE", None) == "pair_confirm":
            attempts.append(msg.TYPE)
            raise error("giả lập: gửi pair_confirm không xong")
        return await real_send(self, msg)

    async def logging_receive(self):
        msg = await real_receive(self)
        received.append((self.is_server, getattr(msg, "TYPE", None)))
        return msg

    monkeypatch.setattr(net_connection.Connection, "send", flaky_send)
    monkeypatch.setattr(net_connection.Connection, "receive", logging_receive)

    trusted = failing.dir / "trusted.json"
    before = (trusted.read_bytes(), trusted.stat().st_mtime_ns)
    trust_calls: list[int] = []
    real_changed = failing.pairing._on_trust_changed

    def counting_trust_changed() -> None:
        trust_calls.append(1)
        real_changed()

    monkeypatch.setattr(failing.pairing, "_on_trust_changed", counting_trust_changed)

    task = asyncio.create_task(A.pairing.pair_with([LOCAL], B.port), name="test.pair")
    await A.rec.wait_prompts()
    await B.rec.wait_prompts()
    failing_sid = failing.rec.prompts[0].session_id
    peer_sid = peer.rec.prompts[0].session_id
    if order == "tu_truoc":
        assert failing.pairing.decide(failing_sid, True) is True
        await wait_until(lambda: attempts == ["pair_confirm"], 2, "chưa thử gửi pair_confirm")
        peer.pairing.decide(peer_sid, True)
    else:
        assert peer.pairing.decide(peer_sid, True) is True
        await wait_until(
            lambda: (failing_is_server, "pair_confirm") in received, 2, "pair_confirm của máy kia chưa tới"
        )
        assert failing.pairing.decide(failing_sid, True) is True

    result_a = await asyncio.wait_for(task, 10)
    await B.rec.wait_finished(1, timeout=5)
    mine = failing.rec.finished[0]
    assert attempts == ["pair_confirm"]
    assert mine.outcome == PairingOutcome.CONNECTION_LOST, mine.outcome
    assert mine.device is None
    assert (trusted.read_bytes(), trusted.stat().st_mtime_ns) == before, "trusted.json bị ghi"
    assert failing.store.get(peer.id) is None
    assert trust_calls == [], "on_trust_changed không được gọi khi không lưu"
    assert peer.store.get(failing.id) is None
    assert TrustStore.load(peer.dir).get(failing.id) is None
    assert A.rec.finished == [result_a]
    if failing_role == Role.RESPONDER:
        await wait_until(lambda: B.pairing.gate.active is None, 1, "gate chưa được nhả")
        assert B.pairing.gate.failures(LOCAL) == 1
    assert gates_idle(A, B)


# --- L4: `PairingFinished.code_shown` --------------------------------------------------------------


@integration
async def test_l4_code_shown_true_when_both_sides_saw_code(node_factory):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    assert result.outcome == PairingOutcome.PAIRED
    assert result.code_shown is True
    assert B.rec.finished[0].code_shown is True


@integration
async def test_l4_code_shown_false_when_peer_leaves_before_code(node_factory, raw_pairing_client, tmp_path):
    """Máy kia đóng ngay sau `pair_commit`: phiên dừng trước khi hiện mã → `code_shown` False."""
    B = await node_factory("B", accept_pairing=True, answer=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.read_commit()
    c.abort()
    await B.rec.wait_finished(1, timeout=3)
    result = B.rec.finished[0]
    assert result.outcome == PairingOutcome.CONNECTION_LOST
    assert result.code_shown is False
    assert B.rec.prompts == []


@integration
async def test_l4_code_shown_true_when_peer_leaves_after_code(node_factory, raw_pairing_client, tmp_path):
    """Máy kia lấy `pair_reveal` rồi bỏ đi: B đã hiện mã → `code_shown` True dù kết quả không phải PAIRED."""
    B = await node_factory("B", accept_pairing=True)
    raw_id = load_or_create_identity(tmp_path / "raw")
    c = await raw_pairing_client(B.port)
    await c.begin(raw_id)
    await c.run_to_code(B.identity.fingerprint)
    c.abort()
    await B.rec.wait_finished(1, timeout=3)
    result = B.rec.finished[0]
    assert result.outcome == PairingOutcome.CONNECTION_LOST
    assert result.code_shown is True
    assert len(B.rec.prompts) == 1


@integration
@pytest.mark.parametrize("raising", ["responder", "initiator"])
async def test_l4_code_shown_false_when_prompt_raises(node_factory, raising):
    """`on_prompt` raise thì mã chưa hiện được ở bên đó (`code_shown` False); bên kia đã hiện mã
    (vai trả lời, khi bên khởi xướng hỏng) thì `code_shown` True, còn chưa hiện thì False."""
    B = await node_factory("B", accept_pairing=True, raise_in_prompt=raising == "responder")
    A = await node_factory("A", answer=True, raise_in_prompt=raising == "initiator")
    result = await pair(A, B)
    await B.rec.wait_finished(1)
    rb = B.rec.finished[0]
    if raising == "responder":
        assert rb.outcome == PairingOutcome.PROMPT_FAILED and rb.code_shown is False
        assert result.outcome == PairingOutcome.PEER_BUSY and result.code_shown is False
    else:
        assert result.outcome == PairingOutcome.PROMPT_FAILED and result.code_shown is False
        assert rb.outcome == PairingOutcome.PEER_REJECTED and rb.code_shown is True


@integration
@pytest.mark.parametrize("known_by", ["initiator", "responder"])
async def test_l4_code_shown_false_for_identity_conflict(node_factory, app_helpers, known_by):
    B = await node_factory("B", accept_pairing=True, answer=True)
    A = await node_factory("A", answer=True)
    if known_by == "initiator":
        A.store.add(peer_cert_from_pem(app_helpers.fake_cert_with_cn(B.id)[0]), "B-cũ")
    else:
        B.store.add(peer_cert_from_pem(app_helpers.fake_cert_with_cn(A.id)[0]), "A-cũ")
    result = await pair(A, B)
    assert result.code_shown is False
    if known_by == "initiator":
        assert result.outcome == PairingOutcome.IDENTITY_CONFLICT
    else:
        await B.rec.wait_finished(1)
        assert B.rec.finished[0].outcome == PairingOutcome.IDENTITY_CONFLICT
        assert B.rec.finished[0].code_shown is False
        assert result.outcome == PairingOutcome.PEER_INVALID


@pytest.mark.slow
@integration
async def test_l4_code_shown_false_when_unreachable(node_factory, app_helpers):
    A = await node_factory("A")
    result = await asyncio.wait_for(A.pairing.pair_with([LOCAL], app_helpers.free_port()), 10)
    assert result.outcome == PairingOutcome.UNREACHABLE
    assert result.code_shown is False


async def test_l4_code_shown_false_for_early_results(service_parts, monkeypatch):
    """Kết quả trả sớm, chưa có phiên (`_report_early`): BUSY và CANCELLED sau `close()` → False."""
    from teleport.app import pairing as app_pairing

    async def no_io(*args, **kwargs):
        raise AssertionError("không được mở kết nối")

    monkeypatch.setattr(app_pairing, "open_pairing", no_io)
    svc = make_service(service_parts)
    held = svc.gate.begin_outgoing("192.0.2.9")  # giữ slot: pair_with kế tiếp nhận BUSY ngay
    assert held is not None
    busy = await svc.pair_with([LOCAL], 47474)
    assert busy.outcome == PairingOutcome.BUSY
    assert busy.code_shown is False
    svc.gate.finish(held, Outcome.CANCELLED, asyncio.get_running_loop().time())
    await svc.close()
    cancelled = await svc.pair_with([LOCAL], 47474)
    assert cancelled.outcome == PairingOutcome.CANCELLED
    assert cancelled.code_shown is False
    assert service_parts[3] == [busy, cancelled]
