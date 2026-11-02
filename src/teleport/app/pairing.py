"""Dịch vụ ghép đôi: chạy máy trạng thái `core.pairing` trên một `Connection` thật.

Đặc tả ở docs/protocol.md mục 5. Logic (thứ tự `pair_*`, hết giờ, chống làm phiền)
nằm ở `teleport.core.pairing`; module này chỉ:

- sinh nonce (`secrets.token_bytes`), phân tích chứng chỉ máy kia (qua `trust`);
- mở kết nối ghép đôi (bên khởi xướng) hoặc nhận kết nối từ `Listener` (bên trả lời);
- đưa sự kiện vào phiên (message, hết giờ, quyết định của người dùng, lệnh hủy) và
  thực hiện các hành động nó trả về (gửi, hiện mã, lưu thiết bị, đóng);
- giữ `PairingGate` (một phiên tại một thời điểm, chờ tăng dần theo IP, giới hạn số mã
  hiện ra, nhường phiên khi hai bên cùng chủ động).

Không hiện được mã (`on_prompt` raise) thì hủy phiên ngay, không để n_B rời máy: vai
trả lời gửi `pair_abort{busy}`, vai khởi xướng gửi `pair_abort{user}`; kết quả là
`PROMPT_FAILED` và không tính vào chờ tăng dần theo IP (protocol mục 5.1, 5.3).

`pair_confirm` của máy này chưa ghi xong vào kết nối thì không lưu thiết bị, kết quả là
`CONNECTION_LOST` (protocol mục 5.1). Ghép đôi lại ở cả hai vai cập nhật tên theo `hello`
của máy kia và thời điểm ghép đôi (protocol mục 5.5).

Vai khởi xướng ký payload chứng minh giữ khóa bằng `trust.PairingSigner`; vai trả lời kiểm
bằng `trust.verify_pairing_proof` với chứng chỉ trong `pair_request` (protocol mục 5.1).

Mỗi phiên chỉ có tối đa **một** `conn.receive()` đang chờ: message kế tiếp chỉ được đọc
khi message trước đã xử lý xong, nên máy kia gửi dồn cũng không làm phình RAM.

Câu chữ cho người dùng không nằm ở đây: `app` chỉ trả mã kết quả (`PairingOutcome`).
Không bao giờ ghi mã 6 số, nonce, chữ ký, payload, PEM hay nội dung message vào log (mvp N9).
"""

from __future__ import annotations

import asyncio
import functools
import ipaddress
import logging
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from teleport.core.framing import FramingError
from teleport.core.messages import AbortReason, Hello, MessageError, PairAbort, PairConfirm, PairRequest
from teleport.core.pairing import (
    Action,
    BadMessage,
    Cancel,
    Close,
    ConnectionLost,
    DeviceCert,
    Event,
    InitiatorSession,
    MessageReceived,
    Outcome,
    PairingGate,
    PairingSession,
    ProofVerifier,
    ResponderSession,
    Role,
    SavePeer,
    SendMessage,
    ShowCode,
    Slot,
    Start,
    State,
    Tick,
    UserDecision,
)
from teleport.core.pairing_code import NONCE_SIZE
from teleport.net.connection import (
    Connection,
    ConnectionLostError,
    IdentityMismatch,
    Rejected,
    Unreachable,
    VersionMismatch,
    open_pairing,
)
from teleport.trust.identity import (
    Identity,
    PeerCert,
    load_pairing_signer,
    peer_cert_from_pem,
    verify_pairing_proof,
)
from teleport.trust.store import TrustedDevice, TrustStore, TrustStoreError

# Thời gian tính bằng giây; đọc lúc dùng để test rút ngắn được bằng monkeypatch.
SEND_TIMEOUT = 10.0  # mỗi lần gửi một message của phiên
BUSY_REPLY_TIMEOUT = 1.0  # gửi pair_abort{busy} + đóng, tổng cộng
ABORT_ON_CANCEL_TIMEOUT = 1.0  # bị hủy cứng: gửi pair_abort{user} + đóng, tổng cộng
FAILED_CLOSE_TIMEOUT = 1.0  # phiên kết thúc mà không ghép đôi: gửi pair_abort (nếu có) + đóng, tổng cộng
CLOSE_SESSIONS_TIMEOUT = 2.0  # cancel_all/close chờ các phiên tự kết thúc
_MIN_WAIT = 0.01  # chờ tối thiểu khi chưa tới hạn chót (tránh vòng lặp bận)

_MAX_ADDRESSES = 16  # như net.connection: số địa chỉ tối đa cho một lần mở kết nối
_BROADCAST = ipaddress.IPv4Address("255.255.255.255")
_TASK_NAME = "teleport.pairing"

log = logging.getLogger(__name__)


class PairingOutcome(StrEnum):
    """Kết quả một lần ghép đôi, như `app` báo cho giao diện."""

    # Trùng giá trị với core.pairing.Outcome:
    PAIRED = "paired"
    USER_REJECTED = "user_rejected"
    TIMEOUT = "timeout"
    PROTOCOL_ERROR = "protocol_error"
    IDENTITY_CONFLICT = "identity_conflict"
    PEER_REJECTED = "peer_rejected"
    PEER_BUSY = "peer_busy"
    PEER_TIMEOUT = "peer_timeout"
    PEER_INVALID = "peer_invalid"
    PEER_ABORTED = "peer_aborted"
    CONNECTION_LOST = "connection_lost"
    CANCELLED = "cancelled"
    # Chỉ ở app:
    UNREACHABLE = "unreachable"  # net.Unreachable
    REJECTED = "rejected"  # net.Rejected
    IDENTITY_MISMATCH = "identity_mismatch"  # net.IdentityMismatch
    VERSION_MISMATCH = "version_mismatch"  # net.VersionMismatch
    BUSY = "busy"  # máy này đang có phiên khác (begin_outgoing → None)
    SELF = "self"  # máy kia chính là máy này
    SAVE_FAILED = "save_failed"  # hai bên đã xác nhận nhưng `before_save` hay `store.add` lỗi
    PROMPT_FAILED = "prompt_failed"  # on_prompt raise: không hiện được mã nên đã hủy phiên


_CONFIRMED = frozenset({PairingOutcome.PAIRED, PairingOutcome.SAVE_FAILED})  # hai bên đã xác nhận

# Lý do gửi cho máy kia khi máy này không hiện được mã (protocol mục 5.1).
_PROMPT_FAILED_REASONS: dict[Role, str] = {
    Role.RESPONDER: AbortReason.BUSY,
    Role.INITIATOR: AbortReason.USER,
}

_CONNECT_OUTCOMES: tuple[tuple[type[Exception], PairingOutcome], ...] = (
    (Unreachable, PairingOutcome.UNREACHABLE),
    (Rejected, PairingOutcome.REJECTED),
    (IdentityMismatch, PairingOutcome.IDENTITY_MISMATCH),
    (VersionMismatch, PairingOutcome.VERSION_MISMATCH),
)


@dataclass(frozen=True, slots=True)
class PairingPrompt:
    """Lời hỏi người dùng: so mã trên hai máy rồi gọi `PairingService.decide`."""

    session_id: int  # Slot.id
    role: Role
    address: str  # IPv4 máy kia
    peer_name: str  # hello.name của máy kia (đã kiểm)
    peer_device_id: str
    code: str  # 6 chữ số thô; giao diện tự gọi format_code
    expires_at: float  # loop.time(): hạn người dùng phải quyết (= session.deadline ngay sau ShowCode)
    # Số mã máy này đã hiện ở vai trả lời trong CODE_WINDOW giây qua, kể cả mã này
    # (`PairingGate.code_shown`); vai khởi xướng luôn 0. Giao diện cảnh báo khi ≥ WARN_RECENT_CODES.
    recent_codes: int
    # Tên đã lưu trong trusted.json cho peer_device_id lúc phiên bắt đầu; khác None nghĩa là
    # máy này đã ghép đôi với máy đó (ghép đôi lại). Ghép đôi xong thì tên đổi thành peer_name.
    known_name: str | None


@dataclass(frozen=True, slots=True)
class PairingFinished:
    """Kết quả cuối của một phiên (hoặc một lời gọi `pair_with` chưa tới được phiên)."""

    session_id: int | None  # None khi chưa có slot (BUSY)
    role: Role
    outcome: PairingOutcome
    address: str  # IPv4 máy kia; bên khởi xướng chưa kết nối được thì là địa chỉ đầu tiên
    port: int | None  # cổng máy kia (bên khởi xướng); None ở bên trả lời
    peer_name: str | None  # None nếu chưa có hello
    peer_device_id: str | None
    peer_reason: str | None  # reason của pair_abort nhận được (Close.peer_reason)
    device: TrustedDevice | None  # mục vừa lưu, chỉ khi PAIRED
    known_name: str | None  # tên đã lưu trong trusted.json cho peer_device_id (IDENTITY_CONFLICT cần)
    code_shown: bool  # on_prompt của phiên này đã chạy xong không lỗi (người dùng đã thấy mã)


class _Run:
    """Trạng thái của một phiên đang chạy (một slot của gate)."""

    def __init__(self, slot: Slot, address: str, port: int | None) -> None:
        self.slot = slot
        self.address = address
        self.port = port
        self.queue: asyncio.Queue[Event] = asyncio.Queue()  # chỉ UserDecision (1 lần) và Cancel (1 lần)
        self.task = asyncio.current_task()  # task chạy phiên: cancel_all hủy cứng task này
        self.done = asyncio.Event()  # đặt sau on_finished; `result` đã có
        self.session: PairingSession | None = None
        self.peer_name: str | None = None
        self.peer_device_id: str | None = None
        self.known_name: str | None = None
        self.peer_reason: str | None = None
        self.outcome: PairingOutcome | None = None  # có giá trị khi phiên đã ra kết quả
        self.decided = False
        # Lệnh hủy đã đưa vào hàng đợi (tối đa một); `_drive` xét nó trước message mạng.
        self.cancel_event: Cancel | None = None
        self.save_failed = False
        self.prompt_failed = False  # on_prompt raise: phiên bị hủy, kết quả PROMPT_FAILED
        self.confirm_send_failed = False  # pair_confirm của máy này chưa ghi xong: không lưu
        self.code_shown = False  # on_prompt đã chạy xong không lỗi
        self.device: TrustedDevice | None = None
        self.replaced_by: _Run | None = None  # phiên trả lời thay phiên khởi xướng này
        self.result: PairingFinished | None = None

    def cancel(self, reason: str) -> None:
        """Đưa `Cancel(reason)` vào hàng đợi, tối đa một lần."""
        if self.cancel_event is None and not self.done.is_set():
            self.cancel_event = Cancel(reason)
            self.queue.put_nowait(self.cancel_event)

    def cancel_replacement(self) -> None:
        """Phiên khởi xướng này bị hủy trước khi chốt: hủy luôn phiên trả lời đã thay nó.

        Gọi càng sớm càng tốt (trước mọi `await` dọn dẹp), để phiên thay thế không kịp
        hiện mã sau lúc người dùng đã hủy. Đã chốt (PAIRED, SAVE_FAILED) thì không làm gì.
        """
        if self.replaced_by is not None and self.outcome not in _CONFIRMED:
            self.replaced_by.cancel(AbortReason.USER)


def _check_addresses(addresses: object) -> list[str]:
    """1–16 IPv4 dạng chấm viết chuẩn, không phải 0.0.0.0, multicast hay broadcast."""
    if isinstance(addresses, str | bytes) or not isinstance(addresses, Sequence):
        raise ValueError("addresses phải là một dãy địa chỉ, không phải một chuỗi")
    items = list(addresses)
    if not 1 <= len(items) <= _MAX_ADDRESSES:
        raise ValueError(f"addresses phải có 1–{_MAX_ADDRESSES} địa chỉ")
    for value in items:
        if not isinstance(value, str):
            raise ValueError("địa chỉ phải là chuỗi IPv4 dạng chấm")
        try:
            ip = ipaddress.IPv4Address(value)
        except ValueError as e:
            raise ValueError(f"địa chỉ phải là IPv4 dạng chấm: {value!r}") from e
        if str(ip) != value:
            raise ValueError(f"địa chỉ phải là IPv4 dạng chấm: {value!r}")
        if ip.is_unspecified or ip.is_multicast or ip == _BROADCAST:
            raise ValueError(f"{value} không phải địa chỉ của một máy")
    return items


def _device_cert(peer: PeerCert) -> DeviceCert:
    """PeerCert (trust) → DeviceCert (core); PEM quá dài sau khi chuẩn hóa → ValueError."""
    return DeviceCert(peer.device_id, peer.fingerprint, peer.pem)


async def _send_and_close(conn: Connection, msg: PairAbort | None, budget: float) -> None:
    """Gửi `msg` (nếu có) rồi đóng, tổng cộng tối đa `budget` giây; không raise trừ khi bị hủy.

    Hết giờ khi đang đóng thì `close()` tự abort, nên socket không bị giữ quá `budget`.
    """
    deadline = asyncio.get_running_loop().time() + budget
    if msg is not None:
        try:
            async with asyncio.timeout_at(deadline):
                await conn.send(msg)
        except (ConnectionLostError, TimeoutError):
            pass
    try:
        async with asyncio.timeout_at(deadline):
            await conn.close()
    except TimeoutError:
        pass


class PairingService:
    """Ghép đôi của một node: khởi xướng (`pair_with`) và trả lời (`handle_incoming`).

    Mọi phương thức phải gọi trên thread của event loop. Callback được gọi đồng bộ trên
    loop; callback raise thì ghi log, phiên vẫn chạy tiếp, trừ `on_prompt`: không hiện
    được mã thì phiên bị hủy (`PROMPT_FAILED`).
    """

    def __init__(
        self,
        *,
        identity: Identity,
        hello: Hello,
        store: TrustStore,
        on_prompt: Callable[[PairingPrompt], None] | None,
        on_finished: Callable[[PairingFinished], None],
        on_trust_changed: Callable[[], object],  # giá trị trả về bị bỏ qua
        accepting: bool = False,
        before_save: Callable[[str], None] | None = None,
    ) -> None:
        """`hello.device_id` khác danh tính → ValueError.

        `on_prompt=None`: node không hiện mã được nên không ghép đôi được; khi đó
        `accepting=True` → ValueError, và `pair_with` → ValueError.

        `before_save(device_id)`: gọi đồng bộ ngay trước `store.add`, trong cùng khối (Node đặt
        lại cài đặt theo thiết bị). Raise thì không ghi `trusted.json`, kết quả `SAVE_FAILED`.

        Đọc khóa riêng để ký khi ghép đôi (`load_pairing_signer`): không đọc được, hỏng hay
        không khớp chứng chỉ → IdentityError.
        """
        self._check_hello(identity, hello)
        if on_prompt is None and accepting is True:
            raise ValueError("không có on_prompt thì không nhận ghép đôi được (accepting=True)")
        own = peer_cert_from_pem(identity.cert_pem())  # PEM đã chuẩn hóa, giống bản máy kia nhận
        self._local = _device_cert(own)
        self._signer = load_pairing_signer(identity)
        self._identity = identity
        self._hello = hello
        self._store = store
        self._on_prompt = on_prompt
        self._on_finished = on_finished
        self._on_trust_changed = on_trust_changed
        self._gate = PairingGate(identity.device_id, accepting=accepting)
        self._runs: dict[int, _Run] = {}  # slot.id → phiên đang chạy
        self._closed = False
        self._aborted = False  # abort_all đã chạy: không bao giờ ghi trusted.json nữa
        self._before_save = before_save

    @staticmethod
    def _check_hello(identity: Identity, hello: object) -> None:
        if not isinstance(hello, Hello):
            raise ValueError("hello phải là Hello")
        if hello.device_id != identity.device_id:
            raise ValueError("hello.device_id phải là device_id của danh tính này")

    def set_hello(self, hello: Hello) -> None:
        """Thay `hello` cho các phiên khởi xướng từ giờ (máy này đổi tên). Kiểm như constructor.

        Phiên đang chạy giữ `hello` đã gửi. Vai trả lời gửi `hello` của `Listener` (`Listener.set_hello`).
        """
        self._check_hello(self._identity, hello)
        self._hello = hello

    @property
    def gate(self) -> PairingGate:
        """Cửa vào của các phiên (chẩn đoán, test)."""
        return self._gate

    @property
    def accepting(self) -> bool:
        """Có nhận yêu cầu ghép đôi tới không (= `gate.accepting`).

        Đặt True khi không có `on_prompt` → ValueError (giữ nguyên giá trị cũ).
        """
        return self._gate.accepting

    @accepting.setter
    def accepting(self, value: bool) -> None:
        if value is True and self._on_prompt is None:
            raise ValueError("không có on_prompt thì không nhận ghép đôi được (accepting=True)")
        self._gate.accepting = value

    def expects_anonymous_from(self, ip: str) -> bool:
        """Máy này đang khởi xướng ghép đôi tới `ip` (`PairingGate.initiating_to`); `ip` sai → ValueError.

        Node đang ẩn vẫn nhận kết nối ẩn danh từ địa chỉ này (yêu cầu ghép đôi của máy kia khi hai
        bên cùng chủ động).
        """
        return self._gate.initiating_to(ip)

    # ---- Bên khởi xướng --------------------------------------------------------------------

    async def pair_with(self, addresses: Sequence[str], port: int) -> PairingFinished:
        """Ghép đôi với máy ở `addresses:port` (máy này khởi xướng); trả kết quả cuối.

        Tham số sai, hoặc không có `on_prompt` → ValueError (trước mọi I/O, không gọi
        `on_finished`). `on_finished` được gọi đúng một lần với cùng kết quả, trừ khi
        phiên bị nhường cho phiên trả lời của cùng máy kia (hai bên cùng chủ động): khi
        đó trả kết quả của phiên thay thế.

        Bị hủy (task bị `cancel()`) trước khi kết quả được chốt → gửi `pair_abort{user}`,
        đóng, `on_finished(CANCELLED)` rồi để CancelledError bay ra; đã có phiên thay thế
        thì hủy luôn phiên đó (`pair_abort{user}`), và chính phiên đó gọi `on_finished`.

        Bị hủy sau khi kết quả đã chốt (hai bên đã xác nhận: PAIRED hoặc SAVE_FAILED, tức
        đã chạy `SavePeer`) → không ném: gỡ lệnh hủy (`Task.uncancel()`), gọi `on_finished`
        đúng một lần với kết quả thật và trả kết quả đó. Phiên thay thế đã chốt cũng vậy:
        chờ nó đóng xong (chỉ còn bước đóng kết nối, tối đa cỡ `CLOSE_TIMEOUT` của `net`)
        rồi trả kết quả của nó; bị hủy thêm lần nữa trong lúc chờ thì ném CancelledError.
        """
        addrs = _check_addresses(addresses)
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError("port phải là số nguyên 1–65535")
        if self._on_prompt is None:
            raise ValueError("không có on_prompt thì không ghép đôi được")
        ip = addrs[0]
        if self._closed:
            return self._report_early(PairingOutcome.CANCELLED, ip, port)
        # Các địa chỉ còn lại của cùng máy: luật hai bên cùng chủ động vẫn áp khi máy kia
        # gửi yêu cầu từ một địa chỉ khác địa chỉ đầu (protocol §5.3).
        slot = self._gate.begin_outgoing(ip, also=addrs[1:])
        if slot is None:
            return self._report_early(PairingOutcome.BUSY, ip, port)

        task = asyncio.current_task()
        assert task is not None
        run = self._register(slot, ip, port)
        try:
            run.outcome = await self._initiate(run, addrs, port)
        except asyncio.CancelledError:
            if run.outcome not in _CONFIRMED:
                run.cancel_replacement()  # phiên thay thế không được chạy tiếp và hiện mã
                raise
            # Kết quả đã chốt (SavePeer đã chạy): lệnh hủy tới muộn, thường khi đang đóng gọn
            # kết nối, nên trả kết quả thật thay vì báo hủy.
            task.uncancel()
        finally:
            outcome = run.outcome or PairingOutcome.CANCELLED
            # Phiên bị nhường thường nhận pair_abort{busy} của máy kia trước lệnh hủy cục bộ
            # (→ PEER_BUSY), nên mọi kết quả chưa ghép đôi đều tính là đã nhường.
            yielded = run.replaced_by is not None and outcome not in _CONFIRMED
            self._end(run, outcome, report=not yielded)
        if yielded:
            replacement = run.replaced_by
            assert replacement is not None
            try:
                await replacement.done.wait()
            except asyncio.CancelledError:
                if replacement.outcome not in _CONFIRMED:
                    # Hủy pair_with thì hủy luôn phiên đã thay nó; phiên đó tự báo on_finished.
                    replacement.cancel(AbortReason.USER)
                    raise
                # Phiên thay thế đã chốt, chỉ còn đóng kết nối: chờ nó xong rồi trả kết quả
                # thật. Bị hủy thêm lần nữa ở đây thì để CancelledError bay ra.
                task.uncancel()
                await replacement.done.wait()
            assert replacement.result is not None
            return replacement.result
        assert run.result is not None
        return run.result

    async def _initiate(self, run: _Run, addrs: list[str], port: int) -> PairingOutcome:
        """Mở kết nối rồi chạy phiên khởi xướng; trả kết quả (chưa gọi finish/on_finished)."""
        opener = asyncio.create_task(open_pairing(addrs, port, self._hello), name=f"{_TASK_NAME}.open")
        local = asyncio.create_task(run.queue.get(), name=f"{_TASK_NAME}.local")
        waited = False
        try:
            await asyncio.wait({opener, local}, return_when=asyncio.FIRST_COMPLETED)
            waited = True
        finally:
            if not waited:
                run.cancel_replacement()  # bị hủy khi đang mở kết nối: trước mọi await dọn dẹp
            local.cancel()
            if not opener.done():
                opener.cancel()  # PR-2 bảo đảm hủy giữa chừng không để lại socket
            await asyncio.wait({opener, local})
            if not waited and not opener.cancelled() and opener.exception() is None:
                # Bị hủy đúng lúc kết nối vừa mở xong: không để lại socket.
                await _send_and_close(opener.result(), None, ABORT_ON_CANCEL_TIMEOUT)

        if opener.cancelled():
            return PairingOutcome.CANCELLED
        error = opener.exception()
        if error is not None:
            for cls, outcome in _CONNECT_OUTCOMES:
                if isinstance(error, cls):
                    log.debug(
                        "ghép đôi: không mở được kết nối tới %s:%d: %s",
                        run.address,
                        port,
                        type(error).__name__,
                    )
                    return outcome
            raise error  # lỗi lập trình: không che đi
        conn = opener.result()
        if local.done() and not local.cancelled():
            # Lệnh hủy tới cùng lúc với kết nối: chưa gửi gì cho máy kia nên chỉ đóng.
            await conn.close()
            return PairingOutcome.CANCELLED

        try:
            return await self._initiate_on(run, conn)
        finally:
            if not conn.closed:
                await conn.close()

    async def _initiate_on(self, run: _Run, conn: Connection) -> PairingOutcome:
        peer = conn.peer
        assert peer.cert is not None  # phía client luôn có chứng chỉ server
        run.address = peer.address
        run.peer_name = peer.hello.name
        run.peer_device_id = peer.hello.device_id
        if (
            peer.cert.fingerprint == self._identity.fingerprint
            or peer.hello.device_id == self._identity.device_id
        ):
            # Đóng trước message mở đầu: listener của chính máy này thấy EOF, không tạo phiên.
            await conn.close()
            return PairingOutcome.SELF
        known = self._store.get(peer.cert.device_id)
        run.known_name = known.name if known is not None else None
        try:
            remote = _device_cert(peer.cert)
        except ValueError:
            log.debug("ghép đôi: chứng chỉ của %s không dùng được", peer.address)
            await conn.close()
            return PairingOutcome.PROTOCOL_ERROR
        session = InitiatorSession(
            local=self._local,
            peer=remote,
            peer_hello=peer.hello,
            nonce=secrets.token_bytes(NONCE_SIZE),
            sign_proof=self._signer.sign,
            known_fingerprint=known.fingerprint if known is not None else None,
        )
        return await self._drive(run, conn, session)

    # ---- Bên trả lời -----------------------------------------------------------------------

    async def handle_incoming(self, conn: Connection) -> None:
        """Trả lời một kết nối ghép đôi `Listener` vừa nhận (`conn.opening` là `PairRequest`).

        Không nhận (đang có phiên, IP đang bị chờ, không ở chế độ chờ ghép đôi, đã đóng)
        → gửi `pair_abort{busy}` rồi đóng trong tối đa BUSY_REPLY_TIMEOUT, không callback.
        """
        loop = asyncio.get_running_loop()
        ip = conn.peer.address
        hello = conn.peer.hello
        request = conn.opening
        if not isinstance(request, PairRequest):
            raise ValueError("handle_incoming chỉ nhận kết nối ghép đôi")
        adm = None if self._closed else self._gate.admit(ip, hello.device_id, loop.time())
        if adm is None or adm.slot is None:
            log.debug("ghép đôi: từ chối (bận) yêu cầu từ %s", ip)
            await _send_and_close(conn, PairAbort(AbortReason.BUSY), BUSY_REPLY_TIMEOUT)
            return

        run = self._register(adm.slot, ip, None)
        run.peer_name = hello.name
        run.peer_device_id = hello.device_id
        if adm.cancel_outgoing is not None:
            outgoing = self._runs.get(adm.cancel_outgoing.id)
            if outgoing is not None:
                log.debug("ghép đôi: hai bên cùng chủ động với %s, nhường phiên khởi xướng", ip)
                outgoing.replaced_by = run
                outgoing.cancel(AbortReason.BUSY)

        try:
            # Hàm kiểm chữ ký chỉ dựng từ chứng chỉ đã kiểm; chứng chỉ hỏng thì phiên tự hủy
            # khi Start, và hàm luôn trả False.
            verify: ProofVerifier = _reject_proof
            try:
                peer_cert = peer_cert_from_pem(request.cert)
                remote: DeviceCert | None = _device_cert(peer_cert)
                verify = functools.partial(verify_pairing_proof, peer_cert)
            except Exception as e:
                # Mọi lỗi khi phân tích chứng chỉ của máy kia đều là chứng chỉ không hợp lệ
                # (protocol mục 5.1), kể cả lỗi lạ của thư viện: phiên gửi pair_abort{invalid}
                # khi Start và IP bị tính chờ tăng dần. Chỉ ghi tên lớp lỗi, không ghi PEM (mvp N9).
                log.debug(
                    "ghép đôi: chứng chỉ trong pair_request từ %s không hợp lệ (%s)", ip, type(e).__name__
                )
                remote = None
            known = self._store.get(remote.device_id) if remote is not None else None
            run.known_name = known.name if known is not None else None
            session = ResponderSession(
                local=self._local,
                peer=remote,
                peer_hello=hello,
                nonce=secrets.token_bytes(NONCE_SIZE),
                verify_proof=verify,
                known_fingerprint=known.fingerprint if known is not None else None,
            )
            run.outcome = await self._drive(run, conn, session)
        finally:
            try:
                if not conn.closed:
                    await _send_and_close(conn, None, ABORT_ON_CANCEL_TIMEOUT)
            finally:
                # Bị hủy thêm lần nữa khi đang đóng: vẫn nhả gate và báo kết quả.
                self._end(run, run.outcome or PairingOutcome.CANCELLED, report=True)

    # ---- Quyết định, hủy, đóng -------------------------------------------------------------

    def decide(self, session_id: int, accepted: bool) -> bool:
        """Chuyển quyết định của người dùng (`True` = mã trùng) vào phiên `session_id`.

        `accepted` không phải bool → ValueError. Trả True khi đã chuyển; False khi id lạ,
        phiên đã xong, chưa tới lúc hỏi, hoặc đã quyết rồi.
        """
        if type(accepted) is not bool:
            raise ValueError("accepted phải là bool")
        if type(session_id) is not int:
            return False
        run = self._runs.get(session_id)
        if run is None or run.done.is_set() or run.decided:
            return False
        session = run.session
        if session is None or session.state is not State.CONFIRMING or session.local_confirmed:
            return False
        run.decided = True
        run.queue.put_nowait(UserDecision(accepted))
        return True

    async def cancel_all(self) -> None:
        """Hủy mọi phiên đang chạy (`pair_abort{user}`) và chờ chúng kết thúc; không raise.

        Chờ tối đa CLOSE_SESSIONS_TIMEOUT; phiên còn lại thì hủy cứng task của nó và chờ
        thêm tối đa ABORT_ON_CANCEL_TIMEOUT + 1 giây.
        """
        runs = list(self._runs.values())
        for run in runs:
            run.cancel(AbortReason.USER)
        left = await self._wait_done(runs, CLOSE_SESSIONS_TIMEOUT)
        if not left:
            return
        for run in left:
            if run.task is not None and not run.task.done():
                log.warning("ghép đôi: phiên %d không dừng sau khi hủy, hủy cứng", run.slot.id)
                run.task.cancel()
        left = await self._wait_done(left, ABORT_ON_CANCEL_TIMEOUT + 1)
        for run in left:
            log.warning("ghép đôi: phiên %d vẫn chưa dừng", run.slot.id)

    async def close(self) -> None:
        """Ngừng nhận yêu cầu mới và hủy mọi phiên; gọi nhiều lần không lỗi."""
        self._closed = True
        self._gate.accepting = False
        await self.cancel_all()

    def abort_all(self) -> None:
        """Hủy cứng ngay, đồng bộ: dừng nhận yêu cầu mới (như `close`), `task.cancel()` cho
        task của mọi phiên đang chạy trừ task đang gọi, và từ đây không bao giờ ghi
        trusted.json nữa. Không chờ. Gọi nhiều lần không lỗi.

        Node gọi hàm này khi `close()` bị hủy, trước khi nhả `node.lock`: một phiên còn chạy
        nền sau đó không được ghi kho mà node khác có thể đang giữ.
        """
        self._closed = True
        self._aborted = True
        self._gate.accepting = False
        current = asyncio.current_task()
        for run in list(self._runs.values()):
            if run.task is not None and run.task is not current and not run.task.done():
                run.task.cancel()

    @staticmethod
    async def _wait_done(runs: list[_Run], timeout: float) -> list[_Run]:
        """Chờ `done` của các phiên tối đa `timeout`; trả các phiên chưa xong."""
        waiters = {
            asyncio.create_task(run.done.wait(), name=f"{_TASK_NAME}.wait"): run
            for run in runs
            if not run.done.is_set()
        }
        if not waiters:
            return []
        try:
            await asyncio.wait(set(waiters), timeout=timeout)
        finally:
            for waiter in waiters:
                waiter.cancel()
            await asyncio.wait(set(waiters))
        return [run for run in waiters.values() if not run.done.is_set()]

    # ---- Vòng sự kiện của một phiên --------------------------------------------------------

    async def _drive(self, run: _Run, conn: Connection, session: PairingSession) -> PairingOutcome:
        """Chạy phiên tới khi nó trả `Close`; kết nối luôn đã đóng khi hàm trả về.

        Bị hủy cứng khi phiên chưa xong → `Cancel(user)`, thực hiện các hành động trong
        ABORT_ON_CANCEL_TIMEOUT, rồi để CancelledError bay ra; chưa chốt thì hủy luôn phiên
        thay thế (nếu có) trước. Phiên đã ra `Close` nhưng chưa đóng xong kết nối cũng chỉ
        được đóng gọn trong ABORT_ON_CANCEL_TIMEOUT; quá hạn thì abort, nên kết nối luôn đã
        đóng cả khi CancelledError bay ra. Lệnh hủy qua `_Run.cancel` được xét trước message mạng.
        """
        loop = asyncio.get_running_loop()
        run.session = session
        recv: asyncio.Task | None = None  # conn.receive() đang chờ (tối đa MỘT)
        local: asyncio.Task | None = None  # run.queue.get()
        reading = True
        try:
            actions = session.handle(Start(), loop.time())
            while True:
                # Phiên kết thúc mà không ghép đôi: gửi pair_abort rồi đóng trong tổng cộng
                # FAILED_CLOSE_TIMEOUT, để máy kia không đọc cũng không giữ được gate lâu hơn.
                deadline = loop.time() + FAILED_CLOSE_TIMEOUT if _ends_unpaired(actions) else None
                close = await self._perform(run, conn, actions, deadline)
                if close is None and run.prompt_failed and session.state is not State.DONE:
                    # Không hiện được mã: phần còn lại của lô (pair_reveal) đã bị bỏ, n_B
                    # không rời máy. Hủy phiên; vòng sau gửi pair_abort và đóng như mọi
                    # phiên kết thúc không ghép đôi.
                    reason = _PROMPT_FAILED_REASONS[run.slot.role]
                    actions = session.handle(Cancel(reason), loop.time())
                    continue
                if close is not None:
                    run.outcome = self._outcome_of(run, close)
                    await _stop(recv)
                    recv = None
                    if deadline is None:
                        await conn.close()  # đóng gọn để pair_confirm cuối kịp tới máy kia
                    else:
                        try:
                            async with asyncio.timeout_at(deadline):
                                await conn.close()  # hết giờ thì close() tự abort
                        except TimeoutError:
                            pass
                    return run.outcome
                if reading and recv is None:
                    recv = asyncio.create_task(conn.receive(), name=f"{_TASK_NAME}.recv")
                if local is None:
                    local = asyncio.create_task(run.queue.get(), name=f"{_TASK_NAME}.local")
                assert session.deadline is not None
                wait = max(session.deadline - loop.time(), _MIN_WAIT)
                pending = {t for t in (recv, local) if t is not None}
                done, _ = await asyncio.wait(pending, timeout=wait, return_when=asyncio.FIRST_COMPLETED)
                event: Event
                if run.cancel_event is not None:
                    # Lệnh hủy đi trước mọi thứ, kể cả message đã đọc xong cùng lúc và Cancel
                    # vừa vào hàng đợi mà `local` chưa kịp lấy: phiên đã bị hủy thì không hiện
                    # mã nữa. Cancel luôn kết thúc phiên nên nhánh này chạy tối đa một lần.
                    event = run.cancel_event
                elif recv is not None and recv in done:  # rồi tới message mạng
                    event, reading = _map_receive(recv)
                    recv = None
                elif local in done:
                    event = local.result()
                    local = None
                else:
                    event = Tick()
                actions = session.handle(event, loop.time())
        except asyncio.CancelledError:
            run.cancel_replacement()  # trước mọi await dọn dẹp bên dưới
            try:
                async with asyncio.timeout(ABORT_ON_CANCEL_TIMEOUT):
                    if session.state is not State.DONE:
                        log.debug("ghép đôi: phiên %d bị hủy cứng", run.slot.id)
                        await self._perform(run, conn, session.handle(Cancel(), loop.time()))
                    # Phiên đã DONE (bị hủy giữa lúc gửi pair_abort và lúc bắt đầu close) cũng
                    # phải đóng ở đây: không thì bên gọi đóng gọn tới CLOSE_TIMEOUT của net.
                    await _stop(recv)
                    recv = None
                    await conn.close()  # bị hủy vì hết giờ thì close() tự abort
            except TimeoutError:
                pass
            finally:
                if not conn.closed:
                    conn.abort()  # hết giờ hoặc bị hủy thêm lần nữa trước khi close() kịp chạy
            raise
        finally:
            # Không await gì khác trước khi hủy hai task con; bị hủy thêm lần nữa thì task
            # con thứ hai vẫn được dừng.
            try:
                await _stop(local)
            finally:
                await _stop(recv)

    async def _perform(
        self, run: _Run, conn: Connection, actions: list[Action], deadline: float | None = None
    ) -> Close | None:
        """Thực hiện hành động đúng thứ tự; trả `Close` nếu có (luôn là hành động cuối).

        Mỗi lần gửi chờ tối đa SEND_TIMEOUT, và không quá `deadline` (`loop.time()`) nếu có.
        Không hiện được mã → đặt `run.prompt_failed`, bỏ mọi hành động còn lại, trả None.
        Gửi `pair_confirm` không xong → đặt `run.confirm_send_failed`; `SavePeer` gặp sau đó
        (cùng lô hay lô sau, khi `pair_confirm` của máy kia tới) bị bỏ.
        """
        loop = asyncio.get_running_loop()
        for action in actions:
            if isinstance(action, SendMessage):
                send_deadline = loop.time() + SEND_TIMEOUT
                if deadline is not None:
                    send_deadline = min(send_deadline, deadline)
                try:
                    async with asyncio.timeout_at(send_deadline):
                        await conn.send(action.message)
                except (ConnectionLostError, TimeoutError) as e:
                    # Các lần receive sau trả nốt message đã đệm rồi ra ConnectionLost; vẫn làm tiếp
                    # các hành động sau.
                    log.debug("ghép đôi: gửi %s thất bại (%s)", action.message.TYPE, type(e).__name__)
                    if isinstance(action.message, PairConfirm):
                        # "Đã GỬI" là đã ghi xong vào kết nối (protocol mục 5.1): máy kia có thể
                        # chưa nhận nên chưa lưu, máy này cũng không lưu.
                        run.confirm_send_failed = True
            elif isinstance(action, ShowCode):
                if not self._show_code(run, conn, action):
                    run.prompt_failed = True
                    return None
            elif isinstance(action, SavePeer):
                if run.confirm_send_failed:
                    log.debug(
                        "ghép đôi: không lưu thiết bị %s vì chưa gửi được pair_confirm",
                        action.peer.device_id[:8],
                    )
                else:
                    self._save(run, action)
            elif isinstance(action, Close):
                return action
        return None

    def _show_code(self, run: _Run, conn: Connection, action: ShowCode) -> bool:
        """Gọi `on_prompt`; False nếu không hiện được mã (callback raise hoặc không có).

        Mã của vai trả lời được đếm (`gate.code_shown`) trước khi gọi callback, nên vẫn
        tính kể cả khi callback lỗi.
        """
        loop = asyncio.get_running_loop()
        session = run.session
        assert session is not None and session.deadline is not None
        recent = self._gate.code_shown(run.slot, loop.time()) if run.slot.role is Role.RESPONDER else 0
        prompt = PairingPrompt(
            session_id=run.slot.id,
            role=run.slot.role,
            address=run.address,
            peer_name=conn.peer.hello.name,
            peer_device_id=conn.peer.hello.device_id,
            code=action.code,
            expires_at=session.deadline,
            recent_codes=recent,
            known_name=run.known_name,
        )
        try:
            if self._on_prompt is None:
                raise RuntimeError("không có on_prompt")
            self._on_prompt(prompt)
        except Exception:
            # Như _call: không ghi mã hay nonce vào log (mvp N9).
            log.exception("ghép đôi: không hiện được mã của phiên %d, hủy phiên", run.slot.id)
            return False
        run.code_shown = True
        return True

    def _save(self, run: _Run, action: SavePeer) -> None:
        peer = action.peer
        if self._aborted:
            # Node đã (hoặc sắp) nhả khóa: không ghi trusted.json nữa.
            log.warning("ghép đôi: bỏ lưu thiết bị %s vì node đang dừng", peer.device_id[:8])
            run.save_failed = True
            return
        if self._before_save is not None:
            try:
                self._before_save(peer.device_id)
            except Exception as e:
                log.error("ghép đôi: không lưu được thiết bị %s: %s", peer.device_id[:8], type(e).__name__)
                run.save_failed = True
                return
        try:
            # Ghép đôi lại cũng ghi đè mục cũ: tên theo hello, paired_at mới (protocol mục 5.5).
            run.device = self._store.add(PeerCert(peer.device_id, peer.fingerprint, peer.pem), action.name)
        except (TrustStoreError, ValueError) as e:
            log.error("ghép đôi: không lưu được thiết bị %s: %s", peer.device_id[:8], type(e).__name__)
            run.save_failed = True
            return
        try:
            self._on_trust_changed()
        except Exception:
            log.exception("on_trust_changed raise")

    @staticmethod
    def _outcome_of(run: _Run, close: Close) -> PairingOutcome:
        run.peer_reason = close.peer_reason
        if run.prompt_failed:
            return PairingOutcome.PROMPT_FAILED
        if run.confirm_send_failed and close.outcome is Outcome.PAIRED:
            return PairingOutcome.CONNECTION_LOST  # không lưu (xem _perform)
        if run.save_failed:
            return PairingOutcome.SAVE_FAILED
        return PairingOutcome(close.outcome.value)

    # ---- Đăng ký, kết thúc -----------------------------------------------------------------

    def _register(self, slot: Slot, address: str, port: int | None) -> _Run:
        run = _Run(slot, address, port)
        self._runs[slot.id] = run
        return run

    def _end(self, run: _Run, outcome: PairingOutcome, *, report: bool) -> None:
        """Nhả slot của gate, dựng kết quả, gọi `on_finished` (nếu `report`), đặt `done`.

        Kết nối đã đóng trước bước này (thứ tự: kết nối đóng → gate.finish → on_finished).
        """
        loop = asyncio.get_running_loop()
        session = run.session
        if session is not None and session.outcome is not None:
            core_outcome = session.outcome  # PAIRED kể cả khi lưu lỗi: giao thức đã thành công
            if core_outcome is Outcome.PAIRED and run.confirm_send_failed:
                # Máy này chưa gửi được pair_confirm nên không lưu: tính như mất kết nối
                # (vai trả lời: một lần thất bại của IP đó).
                core_outcome = Outcome.CONNECTION_LOST
        elif run.slot.role is Role.INITIATOR:
            core_outcome = Outcome.CONNECTION_LOST  # chỉ để nhả slot (khởi xướng không tính bộ đếm)
        else:
            core_outcome = Outcome.CANCELLED
        try:
            self._gate.finish(run.slot, core_outcome, loop.time())
        finally:
            self._runs.pop(run.slot.id, None)
            run.result = PairingFinished(
                session_id=run.slot.id,
                role=run.slot.role,
                outcome=outcome,
                address=run.address,
                port=run.port,
                peer_name=run.peer_name,
                peer_device_id=run.peer_device_id,
                peer_reason=run.peer_reason,
                device=run.device if outcome is PairingOutcome.PAIRED else None,
                known_name=run.known_name,
                code_shown=run.code_shown,
            )
            log.info(
                "ghép đôi kết thúc: vai %s, %s, thiết bị %s, kết quả %s",
                run.slot.role.value,
                run.address,
                (run.peer_device_id or "?")[:8],
                outcome.value,
            )
            if report:
                self._call(self._on_finished, run.result)
            run.done.set()

    def _report_early(self, outcome: PairingOutcome, ip: str, port: int) -> PairingFinished:
        """Kết quả của `pair_with` chưa giữ được slot (đã đóng, hoặc đang có phiên khác)."""
        result = PairingFinished(
            session_id=None,
            role=Role.INITIATOR,
            outcome=outcome,
            address=ip,
            port=port,
            peer_name=None,
            peer_device_id=None,
            peer_reason=None,
            device=None,
            known_name=None,
            code_shown=False,
        )
        log.info("ghép đôi tới %s: %s", ip, outcome.value)
        self._call(self._on_finished, result)
        return result

    @staticmethod
    def _call(callback: Callable, arg: object) -> None:
        try:
            callback(arg)
        except Exception:
            log.exception("callback ghép đôi raise")


def _reject_proof(payload: bytes, signature: bytes) -> bool:
    """Hàm kiểm chữ ký khi chứng chỉ trong `pair_request` hỏng: luôn sai."""
    return False


def _ends_unpaired(actions: list[Action]) -> bool:
    """Lô hành động kết thúc phiên (`Close` cuối) với kết quả khác `paired`."""
    return bool(actions) and isinstance(actions[-1], Close) and actions[-1].outcome is not Outcome.PAIRED


def _map_receive(task: asyncio.Task) -> tuple[Event, bool]:
    """Kết quả của `conn.receive()` → (sự kiện, còn đọc tiếp không). `detail` chỉ là tên lớp lỗi."""
    try:
        msg = task.result()
    except ConnectionLostError:
        return ConnectionLost(), False
    except (FramingError, MessageError) as e:  # gồm UnknownMessageType, WrongConnectionKind
        return BadMessage(type(e).__name__), False
    if msg is None:
        return ConnectionLost(), False
    return MessageReceived(msg), True


async def _stop(task: asyncio.Task | None) -> None:
    """Hủy `task` (nếu còn chạy) và chờ nó kết thúc; không raise lỗi của task."""
    if task is None:
        return None
    if not task.done():
        task.cancel()
    await asyncio.wait({task})
    if not task.cancelled():
        task.exception()  # đánh dấu đã xem lỗi, tránh cảnh báo "never retrieved"
    return None
