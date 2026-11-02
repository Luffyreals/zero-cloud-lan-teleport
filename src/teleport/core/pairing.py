"""Máy trạng thái ghép đôi (sans-IO): thứ tự `pair_*`, hết giờ, lý do hủy, chống làm phiền.

Đặc tả ở docs/protocol.md mục 2.3 và 5. Module không đọc socket, không xem đồng
hồ, không sinh số ngẫu nhiên: tầng `app` sinh nonce (`secrets.token_bytes`), đưa
thời gian monotonic `now` vào mọi lời gọi, rồi thực hiện các hành động trả về.

Một phiên (`InitiatorSession` hoặc `ResponderSession`) nhận *sự kiện* qua
`handle(event, now)` và trả về danh sách *hành động*. Cách `app` nối phiên với
kết nối thật:

- Đọc message bằng `read_message(..., MAX_PAIRING_MESSAGE_SIZE)` bọc trong
  `asyncio.timeout(deadline - now)`; hết giờ → `Tick`.
- `read_message` trả `None`, hoặc `OSError` / `ssl.SSLError` → `ConnectionLost`.
- `FramingError`, `MessageError` (gồm `UnknownMessageType`) → `BadMessage`.
- Thực hiện hành động đúng thứ tự trả về. `Close` luôn là hành động cuối: đóng
  gọn (`close()` rồi `wait_closed()`) để `pair_confirm` cuối cùng vẫn tới máy kia.
- Gửi lỗi (kết nối đã đứt) thì bỏ qua và vẫn thực hiện các hành động sau, nhất là
  `Close` và `PairingGate.finish`. Riêng `pair_confirm` của máy này chưa ghi xong vào
  kết nối thì bỏ `SavePeer` (protocol mục 5.1: chỉ lưu khi đã GỬI và đã NHẬN).

Bên trả lời (B) cam kết nonce trước, kiểu Bluetooth numeric comparison (protocol mục
5.1). Năm bất biến mà máy trạng thái giữ:

1. Bên khởi xướng (A) chỉ ký và gửi n_A (`pair_nonce`) sau khi đã nhận `pair_commit`.
2. B chỉ gửi n_B (`pair_reveal`) sau khi đã nhận n_A, và mã đã hiện trong cùng bước
   (`ShowCode` đứng trước `SendMessage(PairReveal)`).
3. A chỉ hiện mã khi cam kết của B đúng với n_B và fingerprint của B.
4. A không bao giờ tự thử lại một phiên thất bại: mỗi phiên khởi xướng là một thao tác
   của người dùng. Nhường phiên (hai bên cùng chủ động) thì máy này chuyển sang vai
   trả lời, và vai này vẫn cam kết trước.
5. B chỉ hiện mã (và chỉ gửi `pair_reveal`) sau khi chữ ký trong `pair_nonce` đã hợp lệ:
   A chứng minh giữ khóa riêng của chứng chỉ trong `pair_request` bằng cách ký
   `proof_payload` (protocol mục 5.2). B đã được bắt tay TLS chứng minh.

`core` không phân tích chứng chỉ và không làm mật mã khóa công khai: `app` gọi
`trust.peer_cert_from_pem` / `peer_cert_from_der` rồi đưa kết quả vào dưới dạng
`DeviceCert`, và đưa vào hàm ký (`ProofSigner`, vai khởi xướng) hoặc hàm kiểm
(`ProofVerifier`, vai trả lời) của `trust`. Các kiểm tra thuần logic (CN khớp `hello`,
tự ghép với chính mình, ghép đè danh tính) nằm ở đây.

`PairingGate` quyết định có nhận một yêu cầu ghép đôi tới hay không (một phiên
tại một thời điểm, chờ tăng dần theo IP, giới hạn số mã hiện ra, hai bên cùng chủ
động; protocol mục 5.3). Bên trả lời chờ `pair_nonce` với hạn riêng NONCE_TIMEOUT, ngắn
hơn MESSAGE_TIMEOUT, để một máy lạ không giữ được phiên lâu trước khi mã hiện ra.
Giới hạn số kết nối ẩn danh là việc của `core.admission` (tầng `net` thực thi).
"""

from __future__ import annotations

import re
from collections import deque
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from teleport.core.messages import (
    CERT_PEM_HEADER,
    MAX_CERT_PEM_LEN,
    AbortReason,
    Hello,
    Message,
    PairAbort,
    PairCommit,
    PairConfirm,
    PairNonce,
    PairRequest,
    PairReveal,
    validate_device_id,
)
from teleport.core.numbers import is_finite
from teleport.core.pairing_code import (
    NONCE_SIZE,
    PROOF_SIGNATURE_SIZE,
    check_commitment,
    make_commitment,
    pairing_code,
    proof_payload,
)

# Vai khởi xướng: ký `proof_payload` bằng khóa danh tính, trả 64 byte r ‖ s.
ProofSigner = Callable[[bytes], bytes]
# Vai trả lời: (payload, chữ ký 64 byte) → True chỉ khi chữ ký đúng với khóa trong
# chứng chỉ của máy kia. Phiên chỉ coi là đúng khi kết quả `is True`.
ProofVerifier = Callable[[bytes, bytes], bool]

# Thời gian tính bằng giây (protocol mục 2.3, 5.1, 5.3).
MESSAGE_TIMEOUT = 10.0  # bên khởi xướng chờ pair_commit, rồi chờ pair_reveal
NONCE_TIMEOUT = 5.0  # bên trả lời chờ pair_nonce, tính từ lúc gửi pair_commit (protocol mục 2.3)
CONFIRM_TIMEOUT = 60.0  # người dùng quyết định, tính từ lúc hiện mã
# Máy này đã xác nhận: chờ thêm pair_confirm của máy kia tới shown_at + 60 + 10, vì
# người dùng máy kia có thể bấm sát giây thứ 60 và message còn phải đi qua mạng.
CONFIRM_GRACE = 10.0
BACKOFF_BASE = 10.0  # lần thất bại đầu: chờ 10 s, rồi gấp đôi
BACKOFF_MAX = 600.0  # tối đa 10 phút
BACKOFF_FORGET_AFTER = 600.0  # quên một IP sau 600 s yên lặng kể từ khi hết thời gian chờ
MAX_TRACKED_IPS = 1024  # giới hạn bộ nhớ cho bộ đếm theo IP
# Giới hạn số mã hiện ra ở vai trả lời (docs/mvp.md F3): mỗi mã là một lần kẻ giả mạo
# được đoán, nên chặn số lần đoán bất kể đổi IP; từ mã thứ WARN_RECENT_CODES thì cảnh báo.
CODE_WINDOW = 60.0  # cửa sổ đếm mã, giây
MAX_CODES_PER_WINDOW = 5  # đủ số mã này trong cửa sổ → yêu cầu mới nhận pair_abort{busy}
WARN_RECENT_CODES = 3  # giao diện cảnh báo khi số mã trong cửa sổ (kể cả mã đang hiện) ≥ số này

_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")
# Số mũ tối đa khi tính thời gian chờ: 2**32 · 10 s đã vượt xa BACKOFF_MAX, và chặn
# OverflowError khi đổi số nguyên khổng lồ sang float.
_MAX_BACKOFF_EXPONENT = 32
_MAX_ALIASES = 15  # địa chỉ khác của máy đích (net mở tới tối đa 16 địa chỉ)
# Số mốc hiện mã giữ trong bộ nhớ (cố định lúc tạo gate). MAX_CODES_PER_WINDOW lớn hơn số
# này thì bộ đếm không bao giờ đạt giới hạn, nên `admit` báo ValueError thay vì âm thầm tắt nó.
_MAX_CODE_TIMES = 64


class PairingUsageError(RuntimeError):
    """`app` gọi máy trạng thái sai thứ tự (lỗi lập trình, không phải lỗi của máy kia)."""


class Role(StrEnum):
    """Vai trò trong phiên ghép đôi."""

    INITIATOR = "initiator"
    RESPONDER = "responder"


class State(StrEnum):
    """Trạng thái của phiên."""

    IDLE = "idle"  # chưa nhận Start
    AWAIT_COMMIT = "await_commit"  # bên khởi xướng đã gửi pair_request
    AWAIT_NONCE = "await_nonce"  # bên trả lời đã gửi pair_commit
    AWAIT_REVEAL = "await_reveal"  # bên khởi xướng đã gửi pair_nonce
    CONFIRMING = "confirming"  # đã hiện mã, chờ hai bên xác nhận
    DONE = "done"  # đã trả Close


class Outcome(StrEnum):
    """Kết quả của phiên, mang trong `Close`."""

    PAIRED = "paired"
    USER_REJECTED = "user_rejected"  # người dùng máy này bấm “Không trùng”
    TIMEOUT = "timeout"  # máy này hết giờ
    PROTOCOL_ERROR = "protocol_error"  # message sai, sai thứ tự, cam kết/chữ ký sai, cert sai, tự ghép
    IDENTITY_CONFLICT = "identity_conflict"  # device_id đã tin cậy nhưng fingerprint khác
    PEER_REJECTED = "peer_rejected"  # nhận pair_abort{user}
    PEER_BUSY = "peer_busy"  # nhận pair_abort{busy}
    PEER_TIMEOUT = "peer_timeout"  # nhận pair_abort{timeout}
    PEER_INVALID = "peer_invalid"  # nhận pair_abort{invalid}
    PEER_ABORTED = "peer_aborted"  # nhận pair_abort với reason lạ nhưng đúng dạng
    CONNECTION_LOST = "connection_lost"
    CANCELLED = "cancelled"  # app hủy: Ctrl+C, tắt node, nhường phiên, không hiện được mã


_PEER_ABORT_OUTCOMES: dict[str, Outcome] = {
    AbortReason.USER: Outcome.PEER_REJECTED,
    AbortReason.BUSY: Outcome.PEER_BUSY,
    AbortReason.TIMEOUT: Outcome.PEER_TIMEOUT,
    AbortReason.INVALID: Outcome.PEER_INVALID,
}


@dataclass(frozen=True, slots=True)
class DeviceCert:
    """Chứng chỉ của một thiết bị, đã được `trust` kiểm tra.

    Cùng tên trường với `teleport.trust.PeerCert` để `app` đổi qua lại 1:1. `core`
    coi `pem` là chuỗi mờ, chỉ kiểm dạng; sai → ValueError (hoặc MessageError).
    """

    device_id: str
    fingerprint: str  # 64 ký tự hex thường
    pem: str

    def __post_init__(self) -> None:
        validate_device_id(self.device_id)
        _validate_fingerprint(self.fingerprint, "fingerprint")
        if not isinstance(self.pem, str):
            raise ValueError("pem phải là chuỗi")
        if len(self.pem) > MAX_CERT_PEM_LEN:
            raise ValueError(f"pem dài quá {MAX_CERT_PEM_LEN} ký tự")
        if not self.pem.startswith(CERT_PEM_HEADER):
            raise ValueError(f"pem phải bắt đầu bằng {CERT_PEM_HEADER}")


# ---- Sự kiện vào ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Start:
    """Bắt đầu phiên: bên khởi xướng gửi pair_request, bên trả lời gửi pair_commit."""


@dataclass(frozen=True, slots=True)
class MessageReceived:
    """Nhận được một message hợp lệ (đã qua `parse_message`) từ máy kia."""

    message: Message

    def __post_init__(self) -> None:
        if not isinstance(self.message, Message):
            raise TypeError(f"không phải message: {type(self.message).__name__}")


@dataclass(frozen=True, slots=True)
class BadMessage:
    """Nhận được dữ liệu hỏng: `FramingError`, `MessageError` hoặc `UnknownMessageType`."""

    detail: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.detail, str):
            raise TypeError("detail phải là chuỗi")


@dataclass(frozen=True, slots=True)
class UserDecision:
    """Người dùng máy này bấm “Trùng” (`True`) hoặc “Không trùng” (`False`)."""

    accepted: bool

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise ValueError("accepted phải là bool")


@dataclass(frozen=True, slots=True)
class Tick:
    """Đồng hồ chạy: `app` gửi khi chờ message quá `deadline`."""


@dataclass(frozen=True, slots=True)
class ConnectionLost:
    """Kết nối đứt: EOF, lỗi socket hoặc lỗi SSL."""


@dataclass(frozen=True, slots=True)
class Cancel:
    """`app` hủy phiên. `reason` chỉ là `user` hoặc `busy`.

    `user`: Ctrl+C, tắt node, hoặc vai khởi xướng không hiện được mã. `busy`: nhường phiên
    (hai bên cùng chủ động), hoặc vai trả lời không hiện được mã (protocol mục 5.1).
    """

    reason: str = AbortReason.USER

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or self.reason not in (AbortReason.USER, AbortReason.BUSY):
            raise ValueError("reason của Cancel chỉ được là 'user' hoặc 'busy'")
        # Đổi AbortReason về str thuần để so sánh và hiển thị nhất quán.
        object.__setattr__(self, "reason", str.__str__(self.reason))


Event = Start | MessageReceived | BadMessage | UserDecision | Tick | ConnectionLost | Cancel


# ---- Hành động ra --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SendMessage:
    """Gửi message cho máy kia."""

    message: Message


@dataclass(frozen=True, slots=True)
class ShowCode:
    """Hiện mã cho người dùng so. `code` là 6 chữ số thô; giao diện tự gọi `format_code`."""

    code: str


@dataclass(frozen=True, slots=True)
class SavePeer:
    """Lưu máy kia vào `trusted.json`. Luôn đứng ngay trước `Close(PAIRED)`.

    Ghép đôi lại (máy kia đã có trong `trusted.json` với cùng fingerprint) cũng ghi đè
    mục cũ, cập nhật tên theo `name`, ở cả hai vai: máy kia đã chứng minh giữ khóa riêng
    (bắt tay TLS ở vai khởi xướng, chữ ký trong `pair_nonce` ở vai trả lời; protocol mục 5.5).
    """

    peer: DeviceCert
    name: str  # tên trong hello của máy kia


@dataclass(frozen=True, slots=True)
class Close:
    """Kết thúc phiên và đóng kết nối. Luôn là hành động cuối, đúng một lần mỗi phiên.

    `peer_reason` là `reason` của `pair_abort` nhận được (nếu có); `detail` để ghi log.
    """

    outcome: Outcome
    peer_reason: str | None = None
    detail: str = ""


Action = SendMessage | ShowCode | SavePeer | Close


# ---- Hàm phụ -------------------------------------------------------------------------------


def _validate_fingerprint(value: object, field: str) -> str:
    if not isinstance(value, str) or not _FINGERPRINT_RE.fullmatch(value):
        raise ValueError(f"{field} phải là đúng 64 ký tự hex thường")
    return value


def _check_now(now: object, last: float | None) -> float:
    """`now` phải là số hữu hạn và không nhỏ hơn lần gọi trước của cùng đối tượng."""
    if isinstance(now, bool) or not isinstance(now, int | float):
        raise TypeError("now phải là số giây (đồng hồ monotonic)")
    if not is_finite(now):
        raise ValueError("now phải là số hữu hạn")
    if last is not None and now < last:
        raise ValueError("now không được nhỏ hơn lần gọi trước")
    return float(now)


# ---- Phiên ghép đôi ------------------------------------------------------------------------


class PairingSession:
    """Lớp cơ sở cho hai vai; không tạo trực tiếp.

    Quy tắc chung của `handle` (khi phiên không ở IDLE hay DONE), xét theo thứ tự:
    hết giờ (`now >= deadline`) → `pair_abort{timeout}`, sự kiện bị bỏ; nhận
    `pair_abort` → đóng, không trả lời; message hỏng hoặc sai lúc → `pair_abort{invalid}`;
    mất kết nối → đóng; `Cancel` → `pair_abort{reason}`; `Tick` chưa tới hạn và
    `UserDecision` ngoài lúc hỏi người dùng → không làm gì.

    Bảo đảm: `Close` xuất hiện đúng một lần và luôn cuối danh sách; `SavePeer` tối đa
    một lần, chỉ khi máy này đã gửi VÀ đã nhận `pair_confirm`; `ShowCode` tối đa một lần.
    """

    def __init__(
        self,
        *,
        role: Role,
        local: DeviceCert,
        peer: DeviceCert | None,
        peer_hello: Hello,
        nonce: bytes,
        known_fingerprint: str | None,
    ) -> None:
        if type(self) is PairingSession:
            raise TypeError("dùng InitiatorSession hoặc ResponderSession")
        if not isinstance(local, DeviceCert):
            raise ValueError("local phải là DeviceCert")
        if peer is not None and not isinstance(peer, DeviceCert):
            raise ValueError("peer phải là DeviceCert")
        if not isinstance(peer_hello, Hello):
            raise ValueError("peer_hello phải là Hello")
        if not isinstance(nonce, bytes) or len(nonce) != NONCE_SIZE:
            raise ValueError(f"nonce phải là đúng {NONCE_SIZE} byte")
        if known_fingerprint is not None:
            _validate_fingerprint(known_fingerprint, "known_fingerprint")

        self._role = role
        self._local = local
        self._peer = peer
        self._peer_hello = peer_hello
        self._nonce = nonce
        self._known_fingerprint = known_fingerprint

        self._state = State.IDLE
        self._deadline: float | None = None
        self._shown_at: float | None = None
        self._code: str | None = None
        self._outcome: Outcome | None = None
        self._local_confirmed = False
        self._peer_confirmed = False
        self._last_now: float | None = None

    @property
    def role(self) -> Role:
        return self._role

    @property
    def state(self) -> State:
        return self._state

    @property
    def deadline(self) -> float | None:
        """Hạn chót của bước hiện tại; None khi IDLE hoặc DONE."""
        return self._deadline

    @property
    def code(self) -> str | None:
        """Mã 6 số, có giá trị sau `ShowCode`."""
        return self._code

    @property
    def outcome(self) -> Outcome | None:
        """Kết quả, có giá trị sau `Close`."""
        return self._outcome

    @property
    def local_confirmed(self) -> bool:
        """Máy này đã gửi `pair_confirm`."""
        return self._local_confirmed

    @property
    def peer_confirmed(self) -> bool:
        """Đã nhận `pair_confirm` của máy kia."""
        return self._peer_confirmed

    def handle(self, event: Event, now: float) -> list[Action]:
        """Xử lý một sự kiện tại thời điểm `now` (giây, monotonic); trả về hành động cần làm.

        Event không đúng kiểu → TypeError; `now` không hữu hạn hoặc lùi → ValueError;
        gọi sai thứ tự (sự kiện khác `Start`/`Cancel`/`ConnectionLost` khi IDLE, `Start`
        lần hai) → PairingUsageError.
        """
        if not isinstance(event, Event):
            raise TypeError(f"không phải sự kiện ghép đôi: {type(event).__name__}")
        self._last_now = _check_now(now, self._last_now)

        if self._state is State.IDLE:
            if isinstance(event, Start):
                return self._start(now)
            if isinstance(event, Cancel):
                # Chưa gửi gì cho máy kia nên chỉ đóng (kể cả khi nhường với reason busy).
                return self._close(Outcome.CANCELLED)
            if isinstance(event, ConnectionLost):
                return self._close(Outcome.CONNECTION_LOST)
            raise PairingUsageError(f"phiên chưa bắt đầu: không nhận {type(event).__name__}")

        if isinstance(event, Start):
            raise PairingUsageError("phiên đã bắt đầu")
        if self._state is State.DONE:
            return []

        assert self._deadline is not None
        if now >= self._deadline:
            return self._abort(AbortReason.TIMEOUT, Outcome.TIMEOUT)

        if isinstance(event, Tick):
            return []
        if isinstance(event, ConnectionLost):
            return self._close(Outcome.CONNECTION_LOST)
        if isinstance(event, Cancel):
            return self._abort(event.reason, Outcome.CANCELLED)
        if isinstance(event, BadMessage):
            return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, event.detail)
        if isinstance(event, UserDecision):
            if self._state is State.CONFIRMING and not self._local_confirmed:
                return self._decide(event.accepted)
            return []

        msg = event.message
        if isinstance(msg, PairAbort):
            outcome = _PEER_ABORT_OUTCOMES.get(msg.reason, Outcome.PEER_ABORTED)
            return self._close(outcome, peer_reason=msg.reason)
        if self._state is State.CONFIRMING and isinstance(msg, PairConfirm) and not self._peer_confirmed:
            return self._on_peer_confirm()
        actions = self._on_message(msg, now)
        if actions is None:
            detail = f"message {msg.TYPE} không hợp lệ ở trạng thái {self._state}"
            return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, detail)
        return actions

    # ---- Phần riêng của từng vai ----

    def _start(self, now: float) -> list[Action]:
        raise NotImplementedError

    def _on_message(self, msg: Message, now: float) -> list[Action] | None:
        """Xử lý message theo bảng của vai; None nếu message không hợp lệ lúc này."""
        raise NotImplementedError

    def _code_args(self, peer_nonce: bytes) -> tuple[str, str, bytes, bytes]:
        """Đối số cho `pairing_code`, luôn theo thứ tự (khởi xướng, trả lời)."""
        raise NotImplementedError

    # ---- Phần chung ----

    def _self_or_conflict(self, peer: DeviceCert) -> Outcome | None:
        """Kiểm tra trước khi hiện mã: tự ghép với chính mình, ghép đè danh tính."""
        if peer.fingerprint == self._local.fingerprint or peer.device_id == self._local.device_id:
            return Outcome.PROTOCOL_ERROR
        if self._known_fingerprint is not None and self._known_fingerprint != peer.fingerprint:
            return Outcome.IDENTITY_CONFLICT
        return None

    def _show_code(self, peer_nonce: bytes, now: float) -> ShowCode:
        self._code = pairing_code(*self._code_args(peer_nonce))
        self._shown_at = now
        self._deadline = now + CONFIRM_TIMEOUT
        self._state = State.CONFIRMING
        return ShowCode(self._code)

    def _decide(self, accepted: bool) -> list[Action]:
        if not accepted:
            return self._abort(AbortReason.USER, Outcome.USER_REJECTED)
        self._local_confirmed = True
        send = SendMessage(PairConfirm())
        if self._peer_confirmed:
            return [send, *self._paired()]
        # Người dùng máy kia vẫn chỉ có tới shown_at + 60; phần thêm là cho message đi tới.
        assert self._shown_at is not None
        self._deadline = self._shown_at + CONFIRM_TIMEOUT + CONFIRM_GRACE
        return [send]

    def _on_peer_confirm(self) -> list[Action]:
        self._peer_confirmed = True
        if self._local_confirmed:
            return self._paired()
        # Hạn chót giữ nguyên shown_at + 60: người dùng máy này vẫn phải quyết trong 60 s.
        return []

    def _paired(self) -> list[Action]:
        assert self._peer is not None
        # Tới đây thì known_fingerprint (nếu có) trùng fingerprint của máy kia: khác thì
        # phiên đã dừng với IDENTITY_CONFLICT trước khi hiện mã.
        return [SavePeer(self._peer, self._peer_hello.name), *self._close(Outcome.PAIRED)]

    def _abort(self, reason: str, outcome: Outcome, detail: str = "") -> list[Action]:
        return [SendMessage(PairAbort(reason)), *self._close(outcome, detail=detail)]

    def _close(self, outcome: Outcome, *, peer_reason: str | None = None, detail: str = "") -> list[Action]:
        self._state = State.DONE
        self._deadline = None
        self._outcome = outcome
        return [Close(outcome, peer_reason=peer_reason, detail=detail)]


class InitiatorSession(PairingSession):
    """Bên khởi xướng (A): gửi `pair_request`, chờ `pair_commit`, gửi `pair_nonce`, chờ `pair_reveal`.

    `peer` là chứng chỉ của B lấy từ bắt tay TLS; cam kết của B được kiểm bằng
    `peer.fingerprint`. `known_fingerprint` là fingerprint đã lưu cho `peer.device_id`
    trong `trusted.json` (nếu có).

    `sign_proof` ký `proof_payload` bằng khóa danh tính của máy này (`trust`), gọi đúng
    một lần khi nhận `pair_commit`, trước mọi thay đổi trạng thái. Không gọi được →
    ValueError lúc tạo phiên; trả về thứ không phải `bytes` dài PROOF_SIGNATURE_SIZE →
    PairingUsageError (lỗi lập trình); hàm ký raise thì lỗi bay ra nguyên vẹn.
    """

    def __init__(
        self,
        *,
        local: DeviceCert,
        peer: DeviceCert,
        peer_hello: Hello,
        nonce: bytes,
        sign_proof: ProofSigner,
        known_fingerprint: str | None = None,
    ) -> None:
        if not isinstance(peer, DeviceCert):
            raise ValueError("peer phải là DeviceCert")
        if not callable(sign_proof):
            raise ValueError("sign_proof phải gọi được")
        super().__init__(
            role=Role.INITIATOR,
            local=local,
            peer=peer,
            peer_hello=peer_hello,
            nonce=nonce,
            known_fingerprint=known_fingerprint,
        )
        self._sign_proof = sign_proof
        self._commitment: str | None = None  # cam kết của B, nhận trong pair_commit

    def _start(self, now: float) -> list[Action]:
        peer = self._peer
        assert peer is not None
        # Lỗi phát hiện trước khi gửi pair_request: chỉ đóng, không gửi gì (protocol mục 5.1).
        if peer.device_id != self._peer_hello.device_id:
            return self._close(Outcome.PROTOCOL_ERROR, detail="CN chứng chỉ không khớp hello.device_id")
        problem = self._self_or_conflict(peer)
        if problem is not None:
            return self._close(problem)
        self._state = State.AWAIT_COMMIT
        self._deadline = now + MESSAGE_TIMEOUT
        return [SendMessage(PairRequest(cert=self._local.pem))]

    def _on_message(self, msg: Message, now: float) -> list[Action] | None:
        if self._state is State.AWAIT_COMMIT and isinstance(msg, PairCommit):
            # Bất biến 1: n_A chỉ rời máy (và chỉ ký) sau khi đã có cam kết của B. Ký trước
            # mọi thay đổi trạng thái: hàm ký lỗi thì phiên giữ nguyên.
            assert self._peer is not None
            payload = proof_payload(
                self._local.fingerprint, self._peer.fingerprint, self._nonce, msg.commitment
            )
            signature = self._sign_proof(payload)
            if not isinstance(signature, bytes) or len(signature) != PROOF_SIGNATURE_SIZE:
                raise PairingUsageError(f"sign_proof phải trả đúng {PROOF_SIGNATURE_SIZE} byte")
            self._commitment = msg.commitment
            self._state = State.AWAIT_REVEAL
            self._deadline = now + MESSAGE_TIMEOUT
            return [SendMessage(PairNonce(nonce=self._nonce.hex(), signature=signature.hex()))]
        if self._state is State.AWAIT_REVEAL and isinstance(msg, PairReveal):
            assert self._peer is not None and self._commitment is not None
            peer_nonce = bytes.fromhex(msg.nonce)
            # Bất biến 3: cam kết sai thì không hiện mã.
            if not check_commitment(self._peer.fingerprint, peer_nonce, self._commitment):
                return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, "cam kết nonce sai")
            return [self._show_code(peer_nonce, now)]
        return None

    def _code_args(self, peer_nonce: bytes) -> tuple[str, str, bytes, bytes]:
        assert self._peer is not None
        return self._local.fingerprint, self._peer.fingerprint, self._nonce, peer_nonce


class ResponderSession(PairingSession):
    """Bên trả lời (B): tạo sau khi đã đọc `pair_request` và `PairingGate.admit` trả ACCEPT.

    Gửi `pair_commit`, chờ `pair_nonce` tối đa NONCE_TIMEOUT, kiểm chữ ký trong đó, rồi
    hiện mã và gửi `pair_reveal`.
    `peer` là kết quả `peer_cert_from_pem(request.cert)`, hoặc None nếu chứng chỉ hỏng
    (phiên sẽ gửi `pair_abort{invalid}` khi Start). `known_fingerprint` như bên khởi xướng.

    `verify_proof(payload, signature)` kiểm chữ ký bằng khóa trong chứng chỉ `peer`
    (`trust`), gọi đúng một lần khi nhận `pair_nonce`. Chỉ kết quả `is True` mới là đúng;
    còn lại → `pair_abort{invalid}`, PROTOCOL_ERROR, không hiện mã. Không gọi được →
    ValueError lúc tạo phiên; hàm kiểm raise thì lỗi bay ra nguyên vẹn.
    """

    def __init__(
        self,
        *,
        local: DeviceCert,
        peer: DeviceCert | None,
        peer_hello: Hello,
        nonce: bytes,
        verify_proof: ProofVerifier,
        known_fingerprint: str | None = None,
    ) -> None:
        if not callable(verify_proof):
            raise ValueError("verify_proof phải gọi được")
        super().__init__(
            role=Role.RESPONDER,
            local=local,
            peer=peer,
            peer_hello=peer_hello,
            nonce=nonce,
            known_fingerprint=known_fingerprint,
        )
        self._verify_proof = verify_proof
        self._commitment: str | None = None  # cam kết máy này gửi trong pair_commit

    def _start(self, now: float) -> list[Action]:
        peer = self._peer
        if peer is None:
            return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, "chứng chỉ không hợp lệ")
        if peer.device_id != self._peer_hello.device_id:
            detail = "CN chứng chỉ không khớp hello.device_id"
            return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, detail)
        problem = self._self_or_conflict(peer)
        if problem is not None:
            return self._abort(AbortReason.INVALID, problem)
        self._state = State.AWAIT_NONCE
        # Hạn ngắn hơn MESSAGE_TIMEOUT: trước khi hiện mã, máy lạ giữ slot duy nhất của
        # PairingGate lâu nhất là chừng này (protocol mục 5.3).
        self._deadline = now + NONCE_TIMEOUT
        self._commitment = make_commitment(self._local.fingerprint, self._nonce)
        return [SendMessage(PairCommit(self._commitment))]

    def _on_message(self, msg: Message, now: float) -> list[Action] | None:
        if self._state is State.AWAIT_NONCE and isinstance(msg, PairNonce):
            assert self._peer is not None and self._commitment is not None
            peer_nonce = bytes.fromhex(msg.nonce)
            # Bất biến 5: máy kia chưa chứng minh giữ khóa riêng thì không hiện mã.
            payload = proof_payload(
                self._peer.fingerprint, self._local.fingerprint, peer_nonce, self._commitment
            )
            if self._verify_proof(payload, bytes.fromhex(msg.signature)) is not True:
                # Không ghi chữ ký hay payload vào detail (mvp N9).
                return self._abort(AbortReason.INVALID, Outcome.PROTOCOL_ERROR, "chữ ký trong pair_nonce sai")
            # Bất biến 2: hiện mã TRƯỚC, rồi mới để n_B rời máy.
            show = self._show_code(peer_nonce, now)
            return [show, SendMessage(PairReveal(self._nonce.hex()))]
        return None

    def _code_args(self, peer_nonce: bytes) -> tuple[str, str, bytes, bytes]:
        assert self._peer is not None
        return self._peer.fingerprint, self._local.fingerprint, peer_nonce, self._nonce


# ---- Chống làm phiền (protocol mục 5.3) -----------------------------------------------------


class Decision(StrEnum):
    """Nhận hay từ chối (`pair_abort{busy}`) một yêu cầu ghép đôi tới."""

    ACCEPT = "accept"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class Slot:
    """Vé cho phiên đang chạy; `id` tăng dần trong một `PairingGate`."""

    id: int
    role: Role
    ip: str
    aliases: frozenset[str] = frozenset()  # địa chỉ khác của cùng máy đích (chỉ phiên khởi xướng)


@dataclass(frozen=True, slots=True)
class Admission:
    """Kết quả `PairingGate.admit`.

    `cancel_outgoing` khác None khi hai bên cùng chủ động và máy này nhường: `app` gửi
    `Cancel(BUSY)` cho phiên khởi xướng của slot đó (phiên đó không cần gọi `finish`).
    """

    decision: Decision
    slot: Slot | None = None
    cancel_outgoing: Slot | None = None


@dataclass(slots=True)
class _IpRecord:
    failures: int
    blocked_until: float


class PairingGate:
    """Cửa vào cho các phiên ghép đôi của một node: một phiên tại một thời điểm, chờ tăng dần.

    `accepting`: giao diện True khi máy đang hiện, hoặc khi máy đang ẩn mà màn hình
    “Chờ ghép đôi” đang mở (mvp F3); CLI chỉ True khi đang chạy `teleport listen`.
    Bộ đếm theo IP và bộ đếm mã hiện ra chỉ nằm trong bộ nhớ, chỉ tính phiên mà máy
    này là bên trả lời.
    """

    def __init__(self, own_device_id: str, *, accepting: bool = False) -> None:
        self._own_device_id = validate_device_id(own_device_id)
        self.accepting = accepting
        self._active: Slot | None = None
        self._next_id = 1
        self._records: dict[str, _IpRecord] = {}
        self._codes: deque[float] = deque(maxlen=_MAX_CODE_TIMES)  # mốc hiện mã (vai trả lời), tăng dần
        self._last_now: float | None = None

    @property
    def accepting(self) -> bool:
        return self._accepting

    @accepting.setter
    def accepting(self, value: bool) -> None:
        if type(value) is not bool:
            raise ValueError("accepting phải là bool")
        self._accepting = value

    @property
    def active(self) -> Slot | None:
        """Phiên đang chạy (khởi xướng hoặc trả lời), None nếu rảnh."""
        return self._active

    def initiating_to(self, ip: str) -> bool:
        """Máy này có đang khởi xướng ghép đôi tới `ip` không (`ip` là `Slot.ip` hay nằm trong `aliases`).

        Dùng cho chế độ ẩn: máy đang ẩn vẫn nhận kết nối ẩn danh từ địa chỉ này, để luật hai
        bên cùng chủ động của `admit` còn chạy được. `ip` cùng dạng chuẩn như `admit`; sai
        → ValueError.
        """
        _check_ip(ip)
        active = self._active
        return (
            active is not None and active.role is Role.INITIATOR and (ip == active.ip or ip in active.aliases)
        )

    def begin_outgoing(self, ip: str, *, also: Iterable[str] = ()) -> Slot | None:
        """Giữ chỗ cho một phiên khởi xướng tới `ip`; None nếu đang có phiên khác.

        Không xét `accepting`: người dùng chủ động ghép đôi thì luôn được. `ip` phải ở
        cùng một dạng chuẩn do `net` bảo đảm (IPv4 dạng chấm, không tiền tố `::ffff:`),
        vì luật hai bên cùng chủ động so `ip` theo chuỗi.

        `also`: các địa chỉ khác của cùng máy đích (`Slot.aliases`), để luật hai bên cùng
        chủ động vẫn áp khi máy kia gửi yêu cầu từ một địa chỉ khác `ip`. Bỏ trùng và bỏ
        chính `ip`; phần tử sai, `also` là một chuỗi, hoặc còn hơn 15 địa chỉ → ValueError
        (gate giữ nguyên).
        """
        _check_ip(ip)
        if isinstance(also, str | bytes):
            raise ValueError("also phải là một dãy địa chỉ, không phải một chuỗi")
        aliases: dict[str, None] = {}
        for value in also:
            _check_ip(value)
            if value != ip:
                aliases[value] = None
        if len(aliases) > _MAX_ALIASES:
            raise ValueError(f"also có tối đa {_MAX_ALIASES} địa chỉ khác ip")
        if self._active is not None:
            return None
        return self._new_slot(Role.INITIATOR, ip, frozenset(aliases))

    def admit(self, ip: str, peer_device_id: str, now: float) -> Admission:
        """Quyết định với một `pair_request` tới từ `ip`; `peer_device_id` lấy từ `hello`.

        Xét theo thứ tự, dừng ở luật đầu tiên khớp: tự ghép → BUSY; hai bên cùng chủ
        động (máy này đang khởi xướng tới `ip`, hoặc `ip` nằm trong `aliases` của phiên
        đó) → bên có `device_id` lớn hơn nhường phiên khởi xướng; không nhận ghép đôi →
        BUSY; đang có phiên → BUSY; IP đang bị chờ → BUSY (không kéo dài thời gian chờ);
        đã hiện đủ MAX_CODES_PER_WINDOW mã trong CODE_WINDOW giây qua → BUSY (không ghi
        gì vào bộ đếm theo IP); còn lại → ACCEPT. Luật hai bên cùng chủ động đứng trước
        nên không bị giới hạn số mã chặn, nhưng mã của phiên đó vẫn được đếm.

        `ip` phải ở cùng một dạng chuẩn do `net` bảo đảm (IPv4 dạng chấm, không tiền tố
        `::ffff:`): bộ đếm và luật hai bên cùng chủ động so `ip` theo chuỗi.
        MAX_CODES_PER_WINDOW lớn hơn số mốc gate giữ được (64) → ValueError, gate giữ nguyên.
        """
        if MAX_CODES_PER_WINDOW > _MAX_CODE_TIMES:
            raise ValueError(f"MAX_CODES_PER_WINDOW không được lớn hơn {_MAX_CODE_TIMES}")
        _check_ip(ip)
        validate_device_id(peer_device_id)
        self._last_now = _check_now(now, self._last_now)
        self._prune(now)

        busy = Admission(Decision.BUSY)
        if peer_device_id == self._own_device_id:
            return busy
        active = self._active
        if active is not None and active.role is Role.INITIATOR and (ip == active.ip or ip in active.aliases):
            # device_id chưa được xác thực trên kết nối ẩn danh, nên luật cần IP khớp.
            if self._own_device_id > peer_device_id:
                return Admission(Decision.ACCEPT, self._new_slot(Role.RESPONDER, ip), cancel_outgoing=active)
            return busy
        if not self._accepting or active is not None:
            return busy
        blocked = self.blocked_until(ip)
        if blocked is not None and now < blocked:
            return busy
        if self._count_codes(now) >= MAX_CODES_PER_WINDOW:
            return busy
        return Admission(Decision.ACCEPT, self._new_slot(Role.RESPONDER, ip))

    def code_shown(self, slot: Slot, now: float) -> int:
        """Báo phiên của `slot` vừa hiện mã; trả số mã đã hiện trong CODE_WINDOW giây qua.

        Chỉ ghi khi `slot` là phiên đang chạy và máy này là bên trả lời; slot khởi xướng
        hoặc slot đã xong thì không ghi, chỉ trả số đếm hiện tại. Số trả về gồm cả mã vừa
        ghi; một mã thôi được đếm đúng tại `t + CODE_WINDOW`. `slot` không phải Slot →
        ValueError; `now` như `admit`.
        """
        if not isinstance(slot, Slot):
            raise ValueError("slot phải là Slot")
        self._last_now = _check_now(now, self._last_now)
        if slot == self._active and slot.role is Role.RESPONDER:
            self._codes.append(self._last_now)
        return self._count_codes(now)

    def recent_codes(self, now: float) -> int:
        """Số mã đã hiện (vai trả lời) trong CODE_WINDOW giây qua.

        Không ghi mốc mới (chỉ bỏ các mốc đã ra khỏi cửa sổ); `now` được kiểm và đẩy đồng
        hồ của gate như `admit`.
        """
        self._last_now = _check_now(now, self._last_now)
        return self._count_codes(now)

    def finish(self, slot: Slot, outcome: Outcome, now: float) -> None:
        """Báo phiên của `slot` đã kết thúc với `outcome`; slot không còn active → bỏ qua.

        Chỉ phiên trả lời mới cập nhật bộ đếm: PAIRED xóa bộ đếm của IP, CANCELLED giữ
        nguyên, kết quả khác tăng số lần thất bại và đặt thời gian chờ 10, 20, 40… ≤ 600 s.
        """
        if not isinstance(slot, Slot):
            raise ValueError("slot phải là Slot")
        outcome = Outcome(outcome)
        self._last_now = _check_now(now, self._last_now)
        keep = None
        if slot == self._active:
            self._active = None
            if slot.role is Role.RESPONDER:
                self._record_outcome(slot.ip, outcome, now)
                keep = slot.ip
        self._prune(now, keep=keep)

    def blocked_until(self, ip: str) -> float | None:
        """Thời điểm IP hết bị chờ (cùng đồng hồ với `now`); None nếu không có bộ đếm."""
        record = self._records.get(ip)
        return None if record is None else record.blocked_until

    def failures(self, ip: str) -> int:
        """Số lần thất bại liên tiếp đang tính cho IP."""
        record = self._records.get(ip)
        return 0 if record is None else record.failures

    def _count_codes(self, now: float) -> int:
        """Bỏ các mốc đã ra khỏi cửa sổ (`t + CODE_WINDOW <= now`) rồi đếm phần còn lại."""
        codes = self._codes
        while codes and codes[0] + CODE_WINDOW <= now:
            codes.popleft()
        return len(codes)

    def _new_slot(self, role: Role, ip: str, aliases: frozenset[str] = frozenset()) -> Slot:
        slot = Slot(self._next_id, role, ip, aliases)
        self._next_id += 1
        self._active = slot
        return slot

    def _record_outcome(self, ip: str, outcome: Outcome, now: float) -> None:
        if outcome is Outcome.PAIRED:
            self._records.pop(ip, None)
            return
        if outcome is Outcome.CANCELLED:
            return
        record = self._records.get(ip)
        failures = 1 if record is None else record.failures + 1
        exponent = min(failures - 1, _MAX_BACKOFF_EXPONENT)
        wait = min(BACKOFF_BASE * 2.0**exponent, BACKOFF_MAX)
        self._records[ip] = _IpRecord(failures, now + wait)

    def _prune(self, now: float, *, keep: str | None = None) -> None:
        """Quên IP đã yên lặng đủ lâu; giữ tối đa MAX_TRACKED_IPS mục.

        IP đang có phiên trả lời chưa xong thì không coi là yên lặng. `keep` là IP vừa
        được `finish` ghi: không bao giờ bị xóa khi vượt giới hạn, để IP vừa thất bại
        luôn bị chặn.
        """
        active = self._active
        busy_ip = active.ip if active is not None and active.role is Role.RESPONDER else None
        expired = [
            ip
            for ip, r in self._records.items()
            if ip != busy_ip and now >= r.blocked_until + BACKOFF_FORGET_AFTER
        ]
        for ip in expired:
            del self._records[ip]
        excess = len(self._records) - MAX_TRACKED_IPS
        if excess > 0:
            candidates = [ip for ip in self._records if ip not in (keep, busy_ip)]
            oldest = sorted(candidates, key=lambda ip: self._records[ip].blocked_until)[:excess]
            for ip in oldest:
                del self._records[ip]


def _check_ip(ip: object) -> None:
    if not isinstance(ip, str) or not ip:
        raise ValueError("ip phải là chuỗi khác rỗng")
