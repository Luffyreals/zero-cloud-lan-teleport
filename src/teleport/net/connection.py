"""Kết nối trên một cổng: nhận/mở kết nối, trao `hello`, phân loại, giới hạn, keepalive.

Đặc tả ở docs/protocol.md mục 2, 3 và 4.1–4.2. Module này chỉ làm I/O và thực thi các
luật đã có: bảng loại kết nối nằm ở `teleport.core.messages` (`opening_kind`,
`allowed_types`), keepalive ở `teleport.core.keepalive`, khung khối ở
`teleport.core.blocks`. Không có quyết định nghiệp vụ nào ở đây (ghép đôi, chống trùng,
nối lại, lượt truyền là việc của tầng trên). Trên kết nối dữ liệu, module chỉ là đường
ống: không băm payload, không biết lượt truyền.

- `Listener` nhận **TCP trần** rồi gọi `start_tls` cho từng kết nối với `SSLContext`
  hiện tại, nên đổi danh sách tin cậy (`update_trusted`) có hiệu lực ngay mà không
  mở lại cổng. Kết nối đã bắt đầu bắt tay bằng context cũ được kiểm lại lúc nhận
  `control_open` hay `data_open` (protocol mục 7). Nhận hay từ chối một kết nối (số kết
  nối đang mở đầu, tốc độ bắt tay, pool ưu tiên cho IP đã xác thực mTLS) do
  `teleport.core.admission.AdmissionGate` quyết định; `Listener` chỉ thực thi. Kết nối
  ghép đôi, điều khiển và dữ liệu đều được giao qua `on_connection`; handler của kết
  nối dữ liệu kết thúc mà chưa đóng kết nối thì kết nối bị cắt (abort).
- `open_pairing` / `open_control` thử song song mọi địa chỉ của một máy và giữ kết
  nối thành công đầu tiên. `open_data` mở kết nối dữ liệu tới **đúng một** địa chỉ,
  một lần thử (protocol mục 4.1). `open_control` và `open_data` kiểm chứng chỉ server
  ngay trong bắt tay.
- `Connection` gửi/nhận message đã kiểm theo loại kết nối; trên kết nối dữ liệu thì
  đọc/ghi byte thô và khung khối (`write_block` / `read_block`), có backpressure, hạn
  “không nhận byte” (`IdleTimeout`) và hạn `drain()`. `ControlChannel` giữ kết nối
  điều khiển sống bằng `ping`/`pong`.

Các hằng số thời gian và cỡ đoạn được đọc **lúc dùng** (biến toàn cục của module), để
test rút ngắn được bằng `monkeypatch.setattr`; riêng `ssl_shutdown_timeout` của
transport được đặt lúc mở kết nối, nên test vá `CLOSE_TIMEOUT` / `DRAIN_TIMEOUT` trước
khi tạo `Listener` hay gọi `open_*`. Các giới hạn số kết nối và tốc độ nằm ở
`teleport.core.admission`, cũng đọc lúc dùng.

Không bao giờ ghi nội dung message, payload khối hay chứng chỉ vào log (mvp N9): chỉ
ghi `type`, địa chỉ, fingerprint và lý do. Các lần từ chối theo từng kết nối ghi ở mức
DEBUG, để lũ kết nối không làm ngập log.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import math
import ssl
import time
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Self, cast

from teleport.core.admission import AdmissionGate, Refusal, Ticket
from teleport.core.blocks import (
    BLOCK_HEADER,
    BLOCK_SIZE,
    MAX_FILE_SIZE,
    BlockError,
    BlockHeader,
    check_block,
    pack_header,
    parse_header,
)
from teleport.core.framing import (
    HEADER,
    MAX_MESSAGE_SIZE,
    MAX_PAIRING_MESSAGE_SIZE,
    FramingError,
    decode_body,
    decode_header,
    encode_message,
)
from teleport.core.keepalive import DEAD_AFTER, PING_INTERVAL, Keepalive, KeepaliveAction
from teleport.core.messages import (
    MAX_SAFE_INTEGER,
    PROTOCOL_VERSION,
    ConnectionKind,
    ControlOpen,
    DataOpen,
    Hello,
    Message,
    MessageError,
    PairRequest,
    Ping,
    Pong,
    UnknownMessageType,
    allowed_types,
    check_message_kind,
    opening_kind,
    parse_message,
    to_dict,
)
from teleport.net import tls
from teleport.net.stream import read_message
from teleport.trust.identity import (
    Identity,
    InvalidCertificate,
    PeerCert,
    fingerprint_of_der,
    peer_cert_from_der,
    peer_cert_from_pem,
)

DEFAULT_PORT = 47474  # protocol §2.1
OPENING_TIMEOUT = 10.0  # protocol §2.3: TCP/TLS + hello + message mở đầu, cả chuỗi
DRAIN_TIMEOUT = 30.0  # một đoạn gửi không xong trong 30 s → đóng
CLOSE_TIMEOUT = 5.0  # đóng gọn (TLS close_notify) tối đa 5 s, quá thì abort
IDLE_TIMEOUT = 30.0  # protocol §2.3: kết nối dữ liệu đang chờ đọc mà không nhận byte nào → cắt
_SEND_CHUNK = 64 * 1024  # đoạn ghi; trên kết nối dữ liệu bằng đoạn 64 KiB của protocol §4.2
_READ_CHUNK = 64 * 1024
_MAX_ADDRESSES = 16  # số địa chỉ tối đa cho mỗi lần mở kết nối (bằng số địa chỉ mDNS quảng bá)

# Trần tổng số byte đọc bỏ sau close_notify của ta, cho mỗi lần đóng gọn
# (`_discard_after_close_notify`). Vượt trần thì thôi đọc bỏ và để asyncio cắt kết nối như
# trước (abort), để máy kia gửi lũ không giữ CPU của node suốt lần đóng. Ghép đôi: chỉ có
# message nhỏ. Điều khiển: đủ cho một khung lớn nhất máy kia đang gửi dở (mảnh clip) cộng
# một khung nữa (ping, pong…).
_DISCARD_LIMIT_PAIRING = 64 * 1024
_DISCARD_LIMIT_CONTROL = 2 * (MAX_MESSAGE_SIZE + HEADER.size)

_TASK_NAME = "teleport.connection"
_BROADCAST = ipaddress.IPv4Address("255.255.255.255")
_CONTROL_OPEN_FRAME = encode_message(to_dict(ControlOpen()))

# Móc giới hạn tốc độ của `write_raw` / `write_block`: nhận số byte n của đoạn payload sắp
# ghi, luôn 1 ≤ n ≤ `_SEND_CHUNK` (đoạn 64 KiB của protocol §4.2, nên bên gọi dùng được
# `TokenBucket` có burst 64 KiB). Được gọi trong lúc giữ khóa gửi, trước khi byte của đoạn
# đó tới writer; header khung không tính.
BeforeChunk = Callable[[int], Awaitable[None]]

log = logging.getLogger(__name__)


# ---- Ngoại lệ ------------------------------------------------------------------------------


class ConnectError(Exception):
    """Mở kết nối thất bại. `address`: IPv4 dạng chấm của lần thử gây lỗi (None nếu không gắn địa chỉ).

    `str(e)` chỉ để ghi log; `app` ánh xạ **lớp** ngoại lệ sang thông báo của mvp mục 8.
    """

    def __init__(self, message: str, *, address: str | None = None) -> None:
        super().__init__(message)
        self.address = address


class Unreachable(ConnectError):
    """Lỗi TCP/TLS, hết giờ, hoặc máy kia không nói giao thức Teleport (“Thấy nhưng không kết nối được”)."""


class Rejected(ConnectError):
    """Bắt tay TLS xong rồi mới thấy EOF / lỗi SSL / reset, trước khi có `hello` (“X từ chối kết nối”)."""


class IdentityMismatch(ConnectError):
    """Chứng chỉ server khác chứng chỉ đã lưu hay không hợp lệ, hoặc CN ≠ `hello.device_id`.

    Thông báo: “Danh tính thay đổi”.

    Khác chứng chỉ đã lưu: hỏng ngay trong bắt tay (kết nối điều khiển và kết nối dữ
    liệu), hoặc sai fingerprint sau bắt tay. `actual_fingerprint`: fingerprint chứng chỉ
    server đã đưa; None khi bắt tay hỏng (không lấy được chứng chỉ của máy kia).
    """

    def __init__(
        self, message: str, *, address: str | None = None, actual_fingerprint: str | None = None
    ) -> None:
        super().__init__(message, address=address)
        self.actual_fingerprint = actual_fingerprint


class VersionMismatch(ConnectError):
    """`hello` của server có `protocol` khác phiên bản của máy này (“Khác phiên bản giao thức”)."""

    def __init__(self, message: str, *, address: str | None = None, peer_protocol: int) -> None:
        super().__init__(message, address=address)
        self.peer_protocol = peer_protocol


class ConnectionLostError(Exception):
    """Kết nối đã mở bị đứt hoặc đã đóng.

    Lỗi socket/TLS, drain quá DRAIN_TIMEOUT, dùng sau `close()` hay `abort()`, máy kia
    đóng giữa một khung của kết nối dữ liệu, hoặc hết hạn chờ đọc (`IdleTimeout`).
    """


class IdleTimeout(ConnectionLostError):
    """Kết nối dữ liệu: đang chờ đọc mà không nhận được byte nào trong `idle_timeout` (protocol §2.3).

    Khi lỗi này bay ra, kết nối đã bị cắt (`closed` là True). Chỉ kế thừa
    ConnectionLostError, **không** kế thừa TimeoutError / OSError, để `except OSError`
    không nuốt mất nó.
    """


# Lỗi càng đứng trước càng nên báo người dùng: sai danh tính là dấu hiệu giả mạo, bị
# từ chối nghĩa là máy kia đã thấy máy này, còn không kết nối được là ít thông tin nhất.
_ERROR_RANK: tuple[type[ConnectError], ...] = (IdentityMismatch, Rejected, VersionMismatch, Unreachable)


def most_relevant_error(errors: Iterable[ConnectError]) -> ConnectError:
    """Lỗi nên báo người dùng khi mọi địa chỉ đều thất bại.

    IdentityMismatch > Rejected > VersionMismatch > Unreachable; cùng mức thì lấy lỗi
    đứng trước. Rỗng → ValueError.
    """

    def rank(item: tuple[int, ConnectError]) -> tuple[int, int]:
        index, error = item
        for level, cls in enumerate(_ERROR_RANK):
            if isinstance(error, cls):
                return level, index
        return len(_ERROR_RANK), index

    items = list(enumerate(errors))
    if not items:
        raise ValueError("cần ít nhất một lỗi")
    return min(items, key=rank)[1]


# ---- Kết nối -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeerInfo:
    """Máy ở đầu kia của một kết nối."""

    address: str  # IPv4 dạng chấm của máy kia
    port: int  # cổng TCP phía máy kia
    hello: Hello  # hello máy kia đã gửi, đã kiểm
    # Chứng chỉ TLS máy kia, đã qua peer_cert_from_der; None chỉ ở phía server của kết
    # nối ghép đôi (client ẩn danh).
    cert: PeerCert | None

    @property
    def fingerprint(self) -> str | None:
        return None if self.cert is None else self.cert.fingerprint


def _abort(writer: asyncio.StreamWriter) -> None:
    """Đóng ngay (abort, không chờ close_notify; không hứa RST); gọi nhiều lần không lỗi."""
    try:
        writer.transport.abort()
    except Exception:  # transport đã đóng hoặc đang đóng dở
        log.debug("abort transport thất bại", exc_info=True)


async def _drain(writer: asyncio.StreamWriter) -> None:
    """`drain()` tối đa `DRAIN_TIMEOUT`: máy kia không bao giờ đọc thì bên gửi không treo mãi."""
    async with asyncio.timeout(DRAIN_TIMEOUT):
        await writer.drain()


async def _write_chunks(writer: asyncio.StreamWriter, data: bytes) -> None:
    """Ghi `data` theo đoạn ≤ 64 KiB; mỗi đoạn `drain()` tối đa `DRAIN_TIMEOUT`.

    Lỗi (`TimeoutError`, `OSError`, `ssl.SSLError`) bay ra nguyên trạng. Dùng trong lúc
    mở đầu kết nối; `Connection` có vòng ghi riêng để biết đã ghi tới đâu.
    """
    for start in range(0, len(data), _SEND_CHUNK):
        writer.write(data[start : start + _SEND_CHUNK])
        await _drain(writer)


def _ssl_shutdown_timeout(kind: ConnectionKind | None) -> float:
    """`ssl_shutdown_timeout` của transport: phải ≥ hạn `Connection.close` của loại kết nối đó.

    Nhỏ hơn thì transport tự cắt giữa lúc đóng gọn và bỏ phần đuôi còn trong bộ đệm.
    `None`: phía `Listener`, lúc `start_tls` chưa biết loại kết nối. Đọc hằng lúc dùng,
    nên test phải vá hằng trước khi mở kết nối.
    """
    if kind is ConnectionKind.PAIRING or kind is ConnectionKind.CONTROL:
        return CLOSE_TIMEOUT
    return max(CLOSE_TIMEOUT, DRAIN_TIMEOUT)


_DISCARD_HOOK = "_teleport_discard_after_close_notify"  # đánh dấu trên SSLProtocol: đã cài móc


def _discard_after_close_notify(writer: asyncio.StreamWriter, *, limit: int = _DISCARD_LIMIT_PAIRING) -> None:
    """Cài móc để lúc đóng gọn, dữ liệu máy kia gửi sau close_notify của ta bị đọc bỏ.

    Gọi ngay trước `writer.close()`. Không có móc: máy kia còn gửi (ping, message) trước
    khi đọc tới close_notify của ta thì `unwrap()` của `asyncio.sslproto` ném
    `APPLICATION_DATA_AFTER_CLOSE_NOTIFY`, transport bị cắt khi còn dữ liệu chưa đọc →
    RST, và máy kia (Windows) bỏ luôn phần đuôi ta đã gửi còn nằm trong bộ đệm nhận của
    nó. Móc bọc `_do_shutdown` **trên instance** SSLProtocol: trước khi gọi bản gốc, đọc
    bỏ mọi bản ghi đã giải mã được (OpenSSL cho đọc sau khi đã gửi close_notify) tới khi
    hết dữ liệu (`SSLWantReadError`) hay gặp close_notify của máy kia
    (`SSLZeroReturnError`); lỗi SSL khác để bản gốc xử lý như cũ. Rồi gỡ tạm dừng đọc
    socket (`_resume_socket_reading`), vì ở trạng thái SHUTDOWN không ai gỡ, close_notify
    của máy kia sẽ không tới. Hạn đóng không đổi.

    Tổng số byte đọc bỏ của cả lần đóng tối đa `limit` (bên gọi chọn theo loại kết nối:
    `_DISCARD_LIMIT_PAIRING` / `_DISCARD_LIMIT_CONTROL`): vượt thì thôi đọc bỏ, bản gốc gặp
    dữ liệu sau close_notify và cắt kết nối như hành vi cũ.

    Dựa vào thuộc tính nội bộ của `asyncio.sslproto` (giống nhau ở Python 3.12–3.14): thiếu
    thuộc tính nào thì ghi log DEBUG và giữ hành vi cũ, không raise. Gọi nhiều lần chỉ cài
    một móc.
    """
    proto = getattr(writer.transport, "_ssl_protocol", None)
    if getattr(proto, _DISCARD_HOOK, False):
        return
    original = getattr(proto, "_do_shutdown", None)
    if (
        not callable(original)
        or getattr(proto, "_sslobj", None) is None
        or not hasattr(proto, "_eof_received")
    ):
        log.debug("không cài được móc đọc bỏ lúc đóng (asyncio.sslproto đã đổi?)")
        return

    discarded = 0  # số byte đã đọc bỏ trong lần đóng này

    def do_shutdown() -> None:
        nonlocal discarded
        sslobj = getattr(proto, "_sslobj", None)
        if sslobj is not None and discarded <= limit and not getattr(proto, "_eof_received", True):
            try:
                # Dữ liệu sau close_notify của ta: không giao cho tầng trên.
                while discarded <= limit and (chunk := sslobj.read(_READ_CHUNK)):
                    discarded += len(chunk)
            except (ssl.SSLWantReadError, ssl.SSLZeroReturnError):
                pass  # hết dữ liệu đã tới, hoặc máy kia đã trả close_notify
            except ssl.SSLError:
                pass  # bản gốc gặp lỗi SSL trong `unwrap()` (không nhất thiết cùng lỗi) và abort như cũ
            if discarded > limit:
                log.debug("đọc bỏ lúc đóng quá %d byte, để asyncio cắt kết nối", limit)
            else:
                _resume_socket_reading(proto)
        original()

    setattr(proto, "_do_shutdown", do_shutdown)  # noqa: B010 (ghi đè trên instance, không phải lớp)
    setattr(proto, _DISCARD_HOOK, True)


def _resume_socket_reading(proto: object) -> None:
    """Gỡ tạm dừng đọc socket lúc đóng gọn, sau khi đã đọc bỏ (móc của `_discard_after_close_notify`).

    Hai chỗ có thể đã tạm dừng: bộ đệm TLS của SSLProtocol đầy (`_control_ssl_reading` tự
    gỡ khi bộ đệm đã cạn), và phía `Listener`, StreamReader giữ transport TCP gốc nên tạm
    dừng thẳng trên socket khi tầng trên không đọc (comment ở `Listener._handle`); ở trạng
    thái SHUTDOWN không ai gỡ chỗ thứ hai, nên gỡ ở đây khi bộ đệm TLS không còn đầy.
    """
    try:
        control = getattr(proto, "_control_ssl_reading", None)
        if callable(control):
            control()
        raw = getattr(proto, "_transport", None)
        if raw is not None and not getattr(proto, "_ssl_reading_paused", True) and not raw.is_reading():
            raw.resume_reading()
    except Exception:  # transport đã đóng hoặc đang đóng dở
        log.debug("gỡ tạm dừng đọc lúc đóng thất bại", exc_info=True)


def _byte_view(data: object, name: str) -> memoryview:
    """`data` thành memoryview một chiều kiểu byte, nên `nbytes` là số byte thật.

    Chỉ nhận `bytes`, `bytearray`, `memoryview`; vùng nhớ không liền (C-contiguous) hay
    memoryview đã giải phóng → ValueError. Bên gọi phải `release()` view trả về, để
    bytearray của bên gọi đổi cỡ được ngay cả khi có ngoại lệ.
    """
    if not isinstance(data, bytes | bytearray | memoryview):
        raise ValueError(f"{name} phải là bytes, bytearray hoặc memoryview")
    view = memoryview(data)  # memoryview đã giải phóng → ValueError
    if view.c_contiguous and view.format == "B" and view.ndim == 1:
        return view
    try:
        if not view.c_contiguous:
            raise ValueError(f"{name} phải là vùng nhớ liền (C-contiguous)")
        try:
            return view.cast("B")
        except TypeError as e:
            raise ValueError(f"{name} không đọc được thành dãy byte") from e
    finally:
        view.release()  # view `cast` vẫn giữ buffer tới khi chính nó được giải phóng


def _check_before_chunk(before_chunk: object) -> None:
    if before_chunk is not None and not callable(before_chunk):
        raise ValueError("before_chunk phải là None hoặc hàm async nhận số byte")


def _idle_timeout(value: object) -> float:
    """`idle_timeout` của `read_*`: None → `IDLE_TIMEOUT` (đọc lúc gọi).

    Phải là số (không phải bool) hữu hạn > 0, nếu không → ValueError.
    """
    if value is None:
        value = IDLE_TIMEOUT
    if type(value) is bool or not isinstance(value, int | float):
        raise ValueError("idle_timeout phải là số giây dương hữu hạn")
    try:
        seconds = float(value)
    except OverflowError as e:  # số nguyên quá lớn
        raise ValueError("idle_timeout phải là số giây dương hữu hạn") from e
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("idle_timeout phải là số giây dương hữu hạn")
    return seconds


def _max_size(kind: ConnectionKind) -> int:
    return MAX_MESSAGE_SIZE if kind is ConnectionKind.CONTROL else MAX_PAIRING_MESSAGE_SIZE


class Connection:
    """Một kết nối đã trao `hello` và đã biết loại (ghép đôi, điều khiển hoặc dữ liệu).

    Kết nối ghép đôi và điều khiển chở message (`send` / `receive`). Kết nối dữ liệu
    không có message nào sau `data_open` (protocol mục 4.2): nó chở khung khối
    (`write_block` / `read_block`) và byte thô (`write_raw` / `read_raw`). `send` /
    `receive` trên kết nối dữ liệu, hay `read_*` / `write_*` trên loại khác → ValueError.

    Quy ước đóng kết nối dữ liệu cho tầng trên: bên gửi file đã gửi xong khối cuối →
    `close()` (đóng gọn, chờ bên nhận đọc hết, tối đa `DRAIN_TIMEOUT`); bỏ dở giữa chừng
    → `abort()`; bên nhận file nhận None → `abort()` ở phía client, hoặc trả về từ
    handler ở phía server (`Listener` cắt kết nối).
    """

    def __init__(
        self,
        *,
        kind: ConnectionKind,
        peer: PeerInfo,
        is_server: bool,
        opening: PairRequest | ControlOpen | DataOpen | None,
        opened_at: float,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Chỉ `Listener` và `open_pairing` / `open_control` / `open_data` gọi, trừ seam test dưới đây.

        Seam không socket cho kết nối dữ liệu: test dựng thẳng `Connection(kind=DATA, ...)`
        với `reader` là `asyncio.StreamReader` thật (tạo bên trong loop đang chạy; test
        dùng `feed_data` / `feed_eof`) và `writer` giả. Các đường đọc, ghi, `abort` và
        `close` của kết nối dữ liệu chỉ dùng `reader.read`, `reader.at_eof`, `writer.write`,
        `writer.drain` (async), `writer.close`, `writer.wait_closed` (async),
        `writer.transport.abort` và `writer.transport.is_closing`; writer giả có thêm
        `get_extra_info(name)` trả None là đủ.
        """
        self._kind = kind
        self._peer = peer
        self._is_server = is_server
        self._opening = opening
        self._opened_at = opened_at
        self._reader = reader
        self._writer = writer
        self._send_lock = asyncio.Lock()
        self._receiving = False  # đang có một receive() / read_*() chờ
        self._frame_started = False  # lần đọc hiện tại đã đọc ít nhất một byte của khung
        self._closed = False
        # Chỉ chiều gửi đã khóa: gửi lỗi sau khi máy kia đã đóng gọn (xem `send`); vẫn đọc được.
        self._send_closed = False
        self._close_called = False  # máy này đã gọi close() (khác với tự abort khi lỗi)
        self._close_done = asyncio.Event()
        # Móc của ControlChannel (keepalive): gọi sau mỗi đoạn gửi xong / mỗi lần đọc được dữ liệu.
        self._on_sent: Callable[[], None] | None = None
        self._on_received: Callable[[], None] | None = None

    def __repr__(self) -> str:
        side = "server" if self._is_server else "client"
        return f"<Connection {self._kind.value} {side} {self._peer.address}:{self._peer.port}>"

    @property
    def kind(self) -> ConnectionKind:
        return self._kind

    @property
    def peer(self) -> PeerInfo:
        return self._peer

    @property
    def is_server(self) -> bool:
        """True: `Listener` nhận; False: `open_*` mở."""
        return self._is_server

    @property
    def opening(self) -> PairRequest | ControlOpen | DataOpen | None:
        """Phía server: message mở đầu client đã gửi (`PairRequest` / `ControlOpen` / `DataOpen`).

        Phía client: None (kể cả kết nối do `open_data` mở).
        """
        return self._opening

    @property
    def opened_at(self) -> float:
        """`loop.time()` lúc xác định loại.

        Server: lúc nhận message mở đầu; client: lúc mở xong (đã gửi xong `control_open`
        / `data_open` nếu có).
        """
        return self._opened_at

    @property
    def closed(self) -> bool:
        """True sau `close()`, `abort()` hay một lỗi làm hỏng kết nối.

        Gửi lỗi vì máy kia đã đóng gọn (xem `send`) chỉ khóa chiều gửi, không làm `closed` True.
        """
        return self._closed

    async def send(self, msg: Message) -> None:
        """Gửi một message.

        Kiểu không được phép trên loại kết nối này (trên kết nối dữ liệu: mọi kiểu), hoặc
        khung lớn hơn giới hạn → ValueError (lỗi lập trình, không gửi gì). Kết nối đã đóng,
        lỗi socket/TLS, hoặc một đoạn không gửi xong trong `DRAIN_TIMEOUT` →
        ConnectionLostError (kết nối bị đóng ngay). Các lần gửi đồng thời không xen byte
        vào nhau.

        Ngoại lệ: lỗi socket/TLS (không phải hết `DRAIN_TIMEOUT`) khi máy kia **đã đóng gọn**
        trước đó (đã nhận EOF: close_notify hay FIN trần, không lỗi đọc) → ConnectionLostError
        nhưng chỉ khóa chiều gửi: không abort, `closed` vẫn False, các lần gửi sau →
        ConnectionLostError ngay mà không ghi gì, còn `receive` vẫn trả nốt các message máy
        kia đã gửi trước khi đóng rồi None. Nhờ vậy một message trả lời gửi hỏng không làm
        mất `cancel` còn trong bộ đệm đọc. Tầng trên vẫn phải `close()` như thường.

        Bị hủy (ví dụ do `asyncio.timeout` của bên gọi) khi đã ghi ít nhất một đoạn của
        khung → kết nối bị đóng ngay (abort), vì máy kia có thể đã nhận nửa khung; lần gửi
        sau → ConnectionLostError. Bị hủy khi đang chờ lượt gửi hoặc trước đoạn đầu → chưa
        ghi gì, kết nối vẫn dùng được.
        """
        msg_type = getattr(msg, "TYPE", None)
        if msg_type not in allowed_types(self._kind):
            raise ValueError(f"không gửi được {msg_type} trên kết nối {self._kind.value}")
        try:
            data = encode_message(to_dict(msg))
        except FramingError as e:
            raise ValueError(str(e)) from e
        if len(data) - HEADER.size > _max_size(self._kind):
            raise ValueError(f"message quá lớn cho kết nối {self._kind.value}: {len(data)} byte")
        await self._send_frame(data)

    async def _send_frame(self, frame: bytes | Callable[[], bytes | None]) -> None:
        """Ghi một khung đã mã hóa (không kiểm loại; dùng cả cho `control_open`).

        `frame` là hàm thì được gọi **sau khi đã giữ khóa gửi**, ngay trước đoạn ghi đầu
        (không có await ở giữa), để nội dung khung lấy theo trạng thái lúc thật sự gửi
        (`pong` mang `t` mới nhất); hàm trả None → không gửi gì.

        Ghi theo đoạn ≤ 64 KiB, mỗi đoạn `drain()` tối đa `DRAIN_TIMEOUT`, báo keepalive
        sau mỗi đoạn. Bị hủy sau khi đã ghi một đoạn → abort (xem `send`).
        """
        if self._closed or self._send_closed:
            raise ConnectionLostError("kết nối đã đóng")
        async with self._send_lock:
            if self._closed or self._send_closed:
                raise ConnectionLostError("kết nối đã đóng")
            data = frame() if callable(frame) else frame
            if data is None:
                return
            written = False  # đã đưa ít nhất một đoạn của khung xuống transport
            try:
                for start in range(0, len(data), _SEND_CHUNK):
                    self._writer.write(data[start : start + _SEND_CHUNK])
                    written = True
                    await _drain(self._writer)
                    if self._on_sent is not None:
                        self._on_sent()
            except OSError as e:  # gồm ssl.SSLError và TimeoutError (drain quá DRAIN_TIMEOUT)
                if not isinstance(e, TimeoutError) and self._peer_closed_cleanly():
                    # Máy kia đã đóng gọn: phần nó gửi trước đó vẫn nằm trong bộ đệm đọc.
                    log.debug("%r: gửi thất bại sau khi máy kia đã đóng gọn, khóa chiều gửi", self)
                    self._send_closed = True
                else:
                    self._abort()
                raise ConnectionLostError(f"gửi thất bại: {type(e).__name__}") from e
            except asyncio.CancelledError:
                if written:  # máy kia có thể đã nhận nửa khung: không dùng tiếp được
                    log.debug("%r: gửi bị hủy giữa khung, abort", self)
                    self._abort()
                raise
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng trong lúc gửi")

    def _peer_closed_cleanly(self) -> bool:
        """Kết nối ghép đôi / điều khiển: máy kia đã đóng gọn (reader đã nhận EOF, không lỗi đọc).

        EOF ở đây là close_notify hay FIN trần (asyncio không phân biệt với reader).

        `StreamReader` không có API công khai cho “đã nhận EOF” khi bộ đệm còn dữ liệu
        (`at_eof()` cần bộ đệm rỗng), nên đọc `_eof` qua getattr; thiếu thì coi như chưa
        đóng gọn (giữ hành vi cũ: abort). Reset hay lỗi TLS đặt `exception()` của reader.
        """
        if self._kind is ConnectionKind.DATA or self._closed:
            return False
        reader = self._reader
        return getattr(reader, "_eof", False) is True and reader.exception() is None

    async def receive(self) -> Message | None:
        """Đọc một message đã kiểm (`parse_message`, rồi đúng loại kết nối).

        Trả về None khi máy kia đóng gọn ở ranh giới message. Lỗi khung → FramingError;
        message sai (kể cả UnknownMessageType, WrongConnectionKind) → MessageError;
        lỗi socket/TLS hoặc kết nối đã đóng → ConnectionLostError. Gọi khi một `receive`
        khác đang chờ → RuntimeError. Trên kết nối dữ liệu → ValueError ngay, trước mọi
        I/O (dùng `read_block` / `read_raw`).

        Không tự đặt thời gian chờ; bên gọi bọc trong `asyncio.timeout`. Bị hủy khi đã đọc
        một phần khung → kết nối bị đóng ngay (abort), vì phần đã đọc không trả lại được và
        đọc tiếp sẽ lệch khung; lần dùng sau → ConnectionLostError. Bị hủy khi chưa đọc
        byte nào của khung → kết nối vẫn dùng được, message kế tiếp không bị mất. Chiều gửi
        đã khóa vì máy kia đóng gọn (xem `send`) không ảnh hưởng `receive`.

        Header vượt trần → abort rồi FramingError (protocol mục 2.3): phần thân chưa đọc
        thì đọc tiếp sẽ lệch khung; lần dùng sau → ConnectionLostError. Thân sai (JSON hỏng,
        MessageError) thì không abort: khung đã đọc trọn, bên gọi còn đóng gọn được (ví dụ
        `ControlChannel` gửi nốt `pong` đang chờ).
        """
        if self._kind is ConnectionKind.DATA:
            raise ValueError("kết nối dữ liệu không chở message: dùng read_block / read_raw")
        if self._closed:
            raise ConnectionLostError("kết nối đã đóng")
        if self._receiving:
            raise RuntimeError("đang có một receive() khác chờ trên kết nối này")
        self._receiving = True
        self._frame_started = False
        try:
            header = await self._read_exactly(HEADER.size, at_boundary=True)
            if header is None:
                return None
            try:
                length = decode_header(header, _max_size(self._kind))
            except FramingError:
                log.debug("%r: header vượt trần, abort", self)
                self._abort()
                raise
            body = await self._read_exactly(length, at_boundary=False)
            assert body is not None
            msg = parse_message(decode_body(body))
            check_message_kind(self._kind, msg)
            return msg
        except asyncio.CancelledError:
            if self._frame_started:
                log.debug("%r: nhận bị hủy giữa khung, abort", self)
                self._abort()
            raise
        finally:
            self._receiving = False

    async def _read_exactly(self, n: int, *, at_boundary: bool) -> bytearray | None:
        """Đọc đúng `n` byte; báo keepalive sau **mỗi** lần đọc được dữ liệu.

        Trả về chính bộ đệm đã đọc (không chép sang `bytes`: `decode_body` nhận `bytearray`).
        EOF trước byte đầu tiên khi `at_boundary` → None; EOF giữa chừng → FramingError.
        """
        buf = bytearray()
        while len(buf) < n:
            try:
                chunk = await self._reader.read(min(n - len(buf), _READ_CHUNK))
            except OSError as e:  # gồm ssl.SSLError
                raise ConnectionLostError(f"đọc thất bại: {type(e).__name__}") from e
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng")
            if not chunk:
                if at_boundary and not buf:
                    return None
                raise FramingError(f"kết nối bị cắt: mới nhận {len(buf)}/{n} byte")
            buf += chunk
            self._frame_started = True
            if self._on_received is not None:
                self._on_received()
        return buf

    # ---- Kết nối dữ liệu -------------------------------------------------------------------
    # Thứ tự kiểm trong mọi `read_*` / `write_*`: sai loại kết nối → ValueError; tham số sai
    # → ValueError; kết nối đã đóng → ConnectionLostError; đang có `read_*` khác chờ →
    # RuntimeError (chỉ với `read_*`). Mọi lỗi đọc hay ghi khác đều để lại `closed` là True.

    def _require_data(self, name: str) -> None:
        if self._kind is not ConnectionKind.DATA:
            raise ValueError(
                f"{name} chỉ dùng trên kết nối dữ liệu, không dùng trên kết nối {self._kind.value}"
            )

    async def write_raw(
        self, data: bytes | bytearray | memoryview, *, before_chunk: BeforeChunk | None = None
    ) -> None:
        """Ghi byte thô lên kết nối dữ liệu, theo đoạn ≤ `_SEND_CHUNK`.

        Độ dài là số byte của buffer (`nbytes`), không phải `len(data)`. Móc
        `before_chunk(n)` được gọi trước mỗi đoạn. `data` rỗng trên kết nối còn mở thì
        không làm gì (không gọi móc). Tham số, chia đoạn, kiểm đóng, lỗi, hủy và ý nghĩa của
        “trả về thành công”: như `write_block`, với cả lần gọi là một khung.
        """
        self._require_data("write_raw")
        _check_before_chunk(before_chunk)
        view = _byte_view(data, "data")
        try:
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng")
            if view.nbytes:
                await self._write_frame(None, view, before_chunk)
        finally:
            view.release()

    async def write_block(
        self,
        index: int,
        sha256: bytes,
        payload: bytes | bytearray | memoryview,
        *,
        before_chunk: BeforeChunk | None = None,
    ) -> None:
        """Ghi một khung khối: header 41 byte rồi payload (protocol mục 4.2).

        Không băm lại payload: `sha256` là hash bên gọi đã tính. Tham số sai (`index`
        ngoài 0…2³²−1, `sha256` không phải đúng 32 byte kiểu `bytes`, payload không phải
        `bytes` / `bytearray` / `memoryview` liền, rỗng hay dài hơn `BLOCK_SIZE` byte,
        `before_chunk` không gọi được) → ValueError, trước mọi I/O. Kết nối đã đóng →
        ConnectionLostError, kiểm cả trước và ngay sau khi lấy được khóa gửi (trước móc
        đầu tiên).

        Giữ khóa gửi cả lần gọi, nên các lần ghi đồng thời không xen byte vào nhau. Header
        được ghi bằng **một** lần `write` (không chia đoạn, không gọi móc, không `drain`
        riêng). Payload được ghi theo đoạn ≤ `_SEND_CHUNK` (đọc lúc dùng); với mỗi đoạn:
        `await before_chunk(n)` (móc giới hạn tốc độ, chỉ tính payload), kiểm đóng, ghi một
        bản chép của đoạn, rồi `drain()` tối đa `DRAIN_TIMEOUT`.

        Kiểm đóng (ngay trước header và trước mỗi đoạn): kết nối đã đóng, hoặc máy kia đã
        đóng (`transport.is_closing()`: đã nhận close_notify; `reader.at_eof()`: đã nhận
        FIN, mà bên nhận file không bao giờ gửi gì) → abort nếu chưa, rồi
        ConnectionLostError. Lý do: sau close_notify hay FIN, asyncio bỏ byte ghi mà không
        báo lỗi, và `drain()` vẫn trả về ngay. Lỗi socket/TLS, hoặc một đoạn `drain()`
        quá `DRAIN_TIMEOUT` → abort rồi ConnectionLostError (protocol mục 2.3).

        Móc raise (mọi ngoại lệ, kể cả ConnectionLostError của một kết nối khác mà móc
        dùng), hoặc bị hủy (kể cả trong lúc móc đang ngủ): đã ghi ít nhất một byte của
        khung → abort, vì máy kia có thể đã nhận nửa khung; chưa ghi byte nào (kể cả đang
        chờ khóa gửi) → kết nối vẫn dùng được. Ngoại lệ của móc bay ra nguyên trạng.

        Trả về thành công chỉ nghĩa là byte đã giao xuống TLS và hệ điều hành, không phải
        máy kia đã nhận: sự thật là bitfield của bên nhận. Giới hạn còn lại: máy kia gửi
        byte rác rồi FIN thì `reader.at_eof()` còn False (`net` không đọc chỗ rác đó), nên
        vẫn có thể có một khoảng ngắn byte bị bỏ âm thầm, tới khi transport đóng hẳn. Sau
        khi hàm trả về, kết nối không giữ tham chiếu tới `payload` (mỗi đoạn đã được chép):
        bên gọi sửa hay dùng lại buffer được.
        """
        self._require_data("write_block")
        _check_before_chunk(before_chunk)
        view = _byte_view(payload, "payload")
        try:
            header = pack_header(index, view.nbytes, sha256)  # tham số sai → ValueError
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng")
            await self._write_frame(header, view, before_chunk)
        finally:
            view.release()

    async def _write_frame(
        self, header: bytes | None, view: memoryview, before_chunk: BeforeChunk | None
    ) -> None:
        """Vòng ghi một khung của kết nối dữ liệu (xem `write_block`); tham số đã kiểm."""
        async with self._send_lock:
            # Kiểm lại sau khi chờ khóa, trước móc: không gọi móc (trừ token) cho kết nối chết.
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng")
            written = False  # đã đưa ít nhất một byte của khung xuống writer
            try:
                if header is not None:
                    written = True
                    self._put(header)
                start, total = 0, view.nbytes
                while start < total:
                    end = min(total, start + _SEND_CHUNK)
                    if before_chunk is not None:
                        await before_chunk(end - start)
                    written = True
                    self._put(bytes(view[start:end]))  # chép: không giữ buffer của bên gọi
                    await self._drain_data()
                    start = end
            except BaseException:
                # Lỗi gửi (`_put`, `_drain_data`) đã cắt kết nối. Còn lại là móc raise (kể cả
                # ConnectionLostError của một kết nối khác mà móc dùng) hoặc bị hủy: kết nối
                # chưa đóng, mà máy kia có thể đã nhận nửa khung → không dùng tiếp được.
                if written and not self._closed:
                    log.debug("%r: ghi bị ngắt giữa khung, abort", self)
                    self._abort()
                raise
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng trong lúc gửi")

    def _put(self, chunk: bytes) -> None:
        """Kiểm đóng (xem `write_block`) rồi đưa `chunk` xuống writer, không chờ."""
        if self._closed:
            raise ConnectionLostError("kết nối đã đóng")
        if self._writer.transport.is_closing() or self._reader.at_eof():
            log.debug("%r: máy kia đã đóng kết nối trong lúc gửi, abort", self)
            self._abort()
            raise ConnectionLostError("máy kia đã đóng kết nối")
        try:
            self._writer.write(chunk)
        except OSError as e:  # gồm ssl.SSLError
            self._abort()
            raise ConnectionLostError(f"gửi thất bại: {type(e).__name__}") from e

    async def _drain_data(self) -> None:
        try:
            await _drain(self._writer)
        except OSError as e:  # gồm ssl.SSLError và TimeoutError (drain quá DRAIN_TIMEOUT)
            self._abort()
            raise ConnectionLostError(f"gửi thất bại: {type(e).__name__}") from e

    async def read_raw(
        self, n: int, *, at_boundary: bool, idle_timeout: float | None = None
    ) -> bytearray | None:
        """Đọc đúng `n` byte (1…`BLOCK_SIZE`) từ kết nối dữ liệu; trả một `bytearray` mới.

        `at_boundary=True` nghĩa là đây là đầu một khung: EOF trước byte đầu → None (kết
        nối không tự đóng; gọi lại vẫn None). None chỉ nghĩa là “không còn khung nào”, không
        chứng minh máy kia đã gửi xong hay đã đóng gọn (asyncio coi FIN không kèm
        close_notify là EOF sạch). EOF sau khi đã đọc ít nhất một byte, hoặc EOF khi
        `at_boundary=False` → abort rồi ConnectionLostError: đứt giữa khung là đứt kết nối
        bình thường, không phải khung sai (protocol mục 4.2).

        Đọc theo đoạn ≤ `_READ_CHUNK` (không dùng `readexactly`), nên bộ đệm của
        `StreamReader` vẫn có trần và backpressure vẫn chạy; bộ đệm trả về lớn dần theo byte
        thực nhận. Đang chờ socket mà không có byte nào trong `idle_timeout` giây (None:
        đọc `IDLE_TIMEOUT` lúc gọi) → abort rồi IdleTimeout. Đồng hồ đặt lại mỗi khi có
        byte; thời gian không gọi đọc không tính. Hạn bắn khi kết nối đã đóng (`close()` /
        `abort()` đang chạy) → ConnectionLostError, không phải IdleTimeout. Lỗi
        socket/TLS → abort rồi ConnectionLostError.

        Tham số sai (`n` không phải số nguyên 1…`BLOCK_SIZE`, `at_boundary` không phải
        bool, `idle_timeout` không phải số dương hữu hạn) → ValueError. Đọc và ghi đồng
        thời trên cùng kết nối thì được. Bị hủy khi `at_boundary=True` và chưa đọc byte nào
        → kết nối vẫn dùng được; mọi trường hợp khác → abort.
        """
        self._require_data("read_raw")
        if type(n) is not int or not 1 <= n <= BLOCK_SIZE:
            raise ValueError(f"n phải là số nguyên 1…{BLOCK_SIZE}")
        if type(at_boundary) is not bool:
            raise ValueError("at_boundary phải là bool")
        timeout = _idle_timeout(idle_timeout)
        self._start_reading()
        idle = asyncio.timeout(timeout)
        try:
            async with idle:
                return await self._read_data(n, at_boundary=at_boundary, idle=idle, timeout=timeout)
        except TimeoutError as e:
            raise self._idle_error(idle, timeout) from e
        except asyncio.CancelledError:
            if self._frame_started or not at_boundary:
                log.debug("%r: đọc bị hủy giữa khung, abort", self)
                self._abort()
            raise
        finally:
            self._receiving = False

    async def read_block(
        self, *, size: int, idle_timeout: float | None = None
    ) -> tuple[BlockHeader, bytearray] | None:
        """Đọc một khung khối của file `size` byte; trả `(header, payload)` hoặc None.

        Đọc header 41 byte ở ranh giới khung, giải mã (`parse_header`) và đối chiếu với
        `size` (`check_block`) **trước khi** đọc payload (protocol mục 4.2): sai → abort
        rồi BlockError, payload không bị đọc. Đúng → đọc đúng `header.length` byte payload
        vào một `bytearray` mới. Không băm payload và không kiểm thứ tự `block_index`: tầng
        trên so `sha256` (ngoài event loop) và đếm khối sai (`teleport.core.transfer`), không
        phải kiểm lại header.

        EOF trước byte đầu của header → None (như `read_raw` với `at_boundary=True`); EOF
        giữa header hay giữa payload → abort rồi ConnectionLostError, không phải BlockError.
        Hạn chờ đọc, lỗi socket và thứ tự kiểm như `read_raw`; `size` không phải số nguyên
        0…`MAX_FILE_SIZE` → ValueError. BlockError là lớp con của ValueError: bên gọi bắt
        BlockError trước. Bị hủy khi chưa có byte nào của header → kết nối vẫn dùng được;
        còn lại → abort.
        """
        self._require_data("read_block")
        if type(size) is not int or not 0 <= size <= MAX_FILE_SIZE:
            raise ValueError(f"size phải là số nguyên 0…{MAX_FILE_SIZE}")
        timeout = _idle_timeout(idle_timeout)
        self._start_reading()
        idle = asyncio.timeout(timeout)
        try:
            async with idle:
                raw = await self._read_data(BLOCK_HEADER.size, at_boundary=True, idle=idle, timeout=timeout)
                if raw is None:
                    return None
                try:
                    header = parse_header(raw)
                    check_block(header, size)
                except BlockError:
                    log.debug("%r: header khối sai, cắt", self)  # không ghi nội dung header
                    self._abort()
                    raise
                payload = await self._read_data(header.length, at_boundary=False, idle=idle, timeout=timeout)
                assert payload is not None
                return header, payload
        except TimeoutError as e:
            raise self._idle_error(idle, timeout) from e
        except asyncio.CancelledError:
            if self._frame_started:
                log.debug("%r: đọc bị hủy giữa khung, abort", self)
                self._abort()
            raise
        finally:
            self._receiving = False

    def _start_reading(self) -> None:
        if self._closed:
            raise ConnectionLostError("kết nối đã đóng")
        if self._receiving:
            raise RuntimeError("đang có một read_* khác chờ trên kết nối này")
        self._receiving = True
        self._frame_started = False

    async def _read_data(
        self, n: int, *, at_boundary: bool, idle: asyncio.Timeout, timeout: float
    ) -> bytearray | None:
        """Đọc đúng `n` byte theo đoạn ≤ `_READ_CHUNK`; mỗi lần có byte thì dời hạn `idle`.

        Một hạn cho cả lần gọi `read_*`, dời bằng `reschedule` thay vì tạo một timer cho
        mỗi đoạn. EOF: xem `read_raw`.
        """
        loop = asyncio.get_running_loop()
        buf = bytearray()  # lớn dần theo byte thực nhận, không cấp sẵn `n` byte
        while len(buf) < n:
            try:
                chunk = await self._reader.read(min(n - len(buf), _READ_CHUNK))
            except OSError as e:  # gồm ssl.SSLError, ConnectionResetError
                self._abort()
                raise ConnectionLostError(f"đọc thất bại: {type(e).__name__}") from e
            if self._closed:
                raise ConnectionLostError("kết nối đã đóng")
            if not chunk:
                if at_boundary and not buf:
                    return None
                self._abort()
                raise ConnectionLostError(f"kết nối bị cắt giữa khung: mới nhận {len(buf)}/{n} byte")
            buf += chunk
            self._frame_started = True
            idle.reschedule(loop.time() + timeout)
        return buf

    def _idle_error(self, idle: asyncio.Timeout, timeout: float) -> ConnectionLostError:
        """Lỗi cho TimeoutError vừa thoát khỏi hạn chờ đọc; cắt kết nối nếu chưa đóng."""
        if self._closed:  # close() / abort() đang chạy: lỗi phản ánh nguyên nhân thật
            return ConnectionLostError("kết nối đã đóng")
        self._abort()
        if not idle.expired():  # phòng thủ: TimeoutError không phải của hạn chờ đọc
            return ConnectionLostError("đọc thất bại: TimeoutError")
        log.debug("%r: không nhận được byte nào trong %.1f s, cắt", self, timeout)
        return IdleTimeout(f"không nhận được byte nào trong {timeout:g} s")

    # ---- Đóng ------------------------------------------------------------------------------

    def _abort(self) -> None:
        self._closed = True
        _abort(self._writer)
        self._close_done.set()

    def abort(self) -> None:
        """Cắt kết nối ngay: đóng transport, không gửi close_notify, không chờ.

        Gọi nhiều lần không lỗi. Lần dùng sau → ConnectionLostError; một `read_*` /
        `receive` đang chờ cũng ném ConnectionLostError. Không hứa gửi TCP RST: hệ điều
        hành chỉ gửi RST khi còn dữ liệu chưa đọc. Dùng khi bỏ dở kết nối dữ liệu, hay khi
        tầng trên từ chối nó sau khi kiểm `data_open` (protocol mục 4.1).
        """
        self._close_called = True
        self._abort()

    async def close(self) -> None:
        """Đóng gọn (TLS close_notify) và chờ máy kia trả close_notify; quá hạn thì abort.

        Hạn là tổng cả lần đóng: `CLOSE_TIMEOUT` với kết nối ghép đôi và điều khiển,
        `DRAIN_TIMEOUT` với kết nối dữ liệu, để bên đọc chậm vẫn đọc hết phần đuôi còn
        trong bộ đệm; quá hạn thì phần đuôi chưa tới được gửi lại theo `resume`, như một
        lần đứt kết nối dữ liệu (protocol mục 2.3). `ssl_shutdown_timeout` của transport
        được đặt lúc mở, không nhỏ hơn hạn này.

        Kết nối ghép đôi và điều khiển: trong lúc chờ close_notify, dữ liệu máy kia gửi sau
        close_notify của ta (ping, message) bị đọc bỏ, không giao cho tầng trên, để transport
        không bị cắt (RST) làm máy kia mất phần đuôi ta đã gửi (`_discard_after_close_notify`).
        Đọc bỏ có trần theo loại kết nối (`_DISCARD_LIMIT_PAIRING`, `_DISCARD_LIMIT_CONTROL`):
        máy kia gửi quá trần thì kết nối bị cắt như trước.
        Kết nối dữ liệu giữ hành vi cũ: dữ liệu chỉ đi một chiều, bên nhận đóng giữa chừng
        thì RST là đúng ý, để bên gửi dừng ngay.

        Gọi nhiều lần hay đồng thời đều được, không raise; các lời gọi sau chờ lời gọi đầu.
        Bị hủy giữa chừng thì abort rồi mới để CancelledError bay ra.
        """
        self._close_called = True
        if self._closed:
            await self._close_done.wait()
            return
        self._closed = True
        timeout = DRAIN_TIMEOUT if self._kind is ConnectionKind.DATA else CLOSE_TIMEOUT
        try:
            if self._kind is ConnectionKind.PAIRING:
                _discard_after_close_notify(self._writer, limit=_DISCARD_LIMIT_PAIRING)
            elif self._kind is ConnectionKind.CONTROL:
                _discard_after_close_notify(self._writer, limit=_DISCARD_LIMIT_CONTROL)
            self._writer.close()
            async with asyncio.timeout(timeout):
                await self._writer.wait_closed()
        except Exception as e:  # hết giờ, lỗi SSL/socket khi đóng
            log.debug("%r: đóng gọn thất bại (%s), abort", self, type(e).__name__)
            _abort(self._writer)
        except BaseException:  # bị hủy
            _abort(self._writer)
            raise
        finally:
            self._close_done.set()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()


# ---- Keepalive -----------------------------------------------------------------------------


class CloseReason(StrEnum):
    """Vì sao `ControlChannel.run` kết thúc."""

    PEER_CLOSED = "peer_closed"  # EOF gọn ở ranh giới message
    KEEPALIVE = "keepalive"  # không nhận byte nào trong dead_after
    CONNECTION_LOST = "connection_lost"  # lỗi socket/TLS, gửi không tiến triển DRAIN_TIMEOUT
    PROTOCOL_ERROR = "protocol_error"  # FramingError, MessageError (trừ UnknownMessageType), sai loại
    LOCAL = "local"  # máy này gọi conn.close() (hoặc Listener.close())


def _lost_reason(conn: Connection) -> CloseReason:
    return CloseReason.LOCAL if conn._close_called else CloseReason.CONNECTION_LOST


async def _after_send_lost(conn: Connection) -> CloseReason:
    """Keepalive / `_pong_loop` gửi hỏng: kết nối hỏng thì kết thúc với lý do mất kết nối.

    Chỉ chiều gửi khóa (máy kia đã đóng gọn, `closed` vẫn False) thì thôi gửi và chờ tới
    khi bị hủy, để vòng đọc trả nốt các message đã đệm rồi kết thúc với `PEER_CLOSED`;
    vòng đọc không chờ socket nữa (EOF đã tới) nên không cần keepalive.
    """
    if conn.closed or not conn._send_closed:
        return _lost_reason(conn)
    await asyncio.get_running_loop().create_future()  # chỉ kết thúc khi `run` hủy task này
    raise AssertionError("không tới được")


class _PendingPong:
    """Ô giữ `t` của `ping` mới nhất chưa trả (protocol mục 2.3).

    `ping` tới dồn thì ghi đè `t`, nên mỗi kết nối có tối đa một `pong` chờ gửi và lũ
    `ping` không làm RAM tăng. Mỗi lần `put` tăng `_gen`; `pong` chỉ tính là đã trả khi
    gửi xong `t` của đúng lần `put` mới nhất (`ping` tới trong lúc đang gửi thì còn chờ).
    """

    __slots__ = ("_gen", "_sent_gen", "_t", "wakeup")

    def __init__(self) -> None:
        self._t = 0
        self._gen = 0  # số lần put
        self._sent_gen = 0  # `_gen` của pong gửi xong gần nhất
        self.wakeup = asyncio.Event()  # được set mỗi lần put

    def put(self, t: int) -> None:
        self._t = t
        self._gen += 1
        self.wakeup.set()

    def take(self) -> tuple[int, int] | None:
        """`(gen, t)` của pong đang chờ; None nếu không có. Không xóa ô: gửi xong mới gọi `sent`."""
        return None if self._gen == self._sent_gen else (self._gen, self._t)

    def sent(self, gen: int) -> None:
        self._sent_gen = max(self._sent_gen, gen)


class ControlChannel:
    """Chạy một kết nối điều khiển: đọc message, trả `pong`, gửi `ping` đúng hạn, phát hiện chết.

    Dùng một lần: `run(on_message)` chạy tới khi kết nối kết thúc và luôn đóng kết nối.
    Ba task con: vòng đọc, keepalive và `_pong_loop`; `pong` gửi ở task riêng để một lần
    gửi lớn đang giữ khóa gửi không chặn vòng đọc.
    """

    def __init__(
        self, conn: Connection, *, ping_interval: float = PING_INTERVAL, dead_after: float = DEAD_AFTER
    ) -> None:
        """`conn.kind` khác CONTROL → ValueError; tham số thời gian kiểm như `Keepalive`."""
        if not isinstance(conn, Connection):
            raise TypeError("conn phải là Connection")
        if conn.kind is not ConnectionKind.CONTROL:
            raise ValueError("ControlChannel chỉ dùng cho kết nối điều khiển")
        Keepalive(0.0, ping_interval=ping_interval, dead_after=dead_after)  # chỉ để kiểm tham số
        self._conn = conn
        self._ping_interval = ping_interval
        self._dead_after = dead_after
        self._started = False

    @property
    def connection(self) -> Connection:
        return self._conn

    async def run(self, on_message: Callable[[Message], None]) -> CloseReason:
        """Chạy tới khi kết nối kết thúc; trả lý do. Kết nối luôn được đóng khi `run` trả về.

        `on_message` là hàm đồng bộ, được gọi đúng thứ tự nhận cho mọi message hợp lệ (kể
        cả `ping`: `pong` của nó đã được *xếp lịch* cho `_pong_loop` trước khi gọi, nhưng
        có thể chưa gửi); việc lâu thì tự tạo task. `ping` dồn khi `pong` chưa gửi được
        thì gộp: chỉ trả `t` của `ping` mới nhất (protocol mục 2.3). `on_message` raise →
        đóng kết nối rồi raise lại. Nhiều task con cùng xong thì ưu tiên kết quả của vòng
        đọc, rồi keepalive, rồi `_pong_loop`. Lúc dọn, còn `pong` chờ mà kết nối chưa hỏng
        thì gửi nốt rồi mới đóng gọn; cả hai dùng chung một hạn `CLOSE_TIMEOUT` (tổng thời
        gian dọn ≤ `CLOSE_TIMEOUT`), quá hạn thì abort. Gọi lần hai → RuntimeError.
        `ping` / `pong` gửi hỏng vì máy kia đã đóng gọn (chỉ khóa chiều gửi, xem
        `Connection.send`) không kết thúc `run`: vòng đọc giao nốt các message đã đệm rồi
        kết thúc với `PEER_CLOSED`.
        Bị hủy lần nữa trong lúc dọn → abort kết nối ngay; các task con kết thúc ở vòng
        lặp kế tiếp.
        """
        if self._started:
            raise RuntimeError("ControlChannel.run chỉ gọi được một lần")
        self._started = True
        conn = self._conn
        if conn.closed:
            return CloseReason.LOCAL

        loop = asyncio.get_running_loop()
        keepalive = Keepalive(loop.time(), ping_interval=self._ping_interval, dead_after=self._dead_after)
        pending = _PendingPong()
        conn._on_sent = lambda: keepalive.sent(loop.time())
        conn._on_received = lambda: keepalive.received(loop.time())
        timer = asyncio.create_task(self._keepalive_loop(keepalive), name=f"{_TASK_NAME}.keepalive")
        reader = asyncio.create_task(self._read_loop(on_message, pending), name=f"{_TASK_NAME}.reader")
        ponger = asyncio.create_task(self._pong_loop(pending), name=f"{_TASK_NAME}.pong")
        tasks = (reader, timer, ponger)  # thứ tự ưu tiên kết quả
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            # Vòng đọc đứng đầu vì nó mang lỗi của on_message.
            return next(task for task in tasks if task in done).result()
        finally:
            # Gỡ móc và hủy task trước mọi await: bị hủy thêm lần nữa trong lúc dọn thì
            # keepalive cũng không còn gắn vào kết nối.
            conn._on_sent = None
            conn._on_received = None
            for task in tasks:
                task.cancel()
            try:
                await asyncio.wait(tasks)
                # Gửi nốt pong và đóng gọn dùng chung **một** hạn CLOSE_TIMEOUT, để cả việc
                # dọn không lâu hơn thời gian `Listener.close` / node chờ một kết nối.
                async with asyncio.timeout(CLOSE_TIMEOUT):
                    await self._flush_pong(pending)
                    await conn.close()
            except TimeoutError:
                log.debug("%r: dọn quá %.1f s, abort", conn, CLOSE_TIMEOUT)
                conn._abort()
            except BaseException:
                # Bị hủy lần nữa trong lúc dọn: không await thêm, đóng ngay rồi để lỗi bay ra.
                # Các task con đã bị hủy và kết thúc ở vòng lặp kế tiếp.
                conn._abort()
                raise

    async def _flush_pong(self, pending: _PendingPong) -> None:
        """Gửi nốt `pong` còn chờ nếu kết nối chưa hỏng; lỗi gửi thì bỏ qua. Hạn do `run` đặt."""
        if pending.take() is None or self._conn.closed:
            return
        try:
            await self._send_pong(pending)
        except ConnectionLostError:
            log.debug("%r: không gửi nốt được pong lúc đóng", self._conn)

    async def _send_pong(self, pending: _PendingPong) -> None:
        """Gửi một `pong`; `t` chỉ được đọc khi đã giữ khóa gửi, nên luôn là `t` mới nhất.

        Chờ khóa trong lúc `ping` mới tới thì pong này mang luôn `t` mới: không bao giờ có
        một pong mang `t` cũ đang chờ khóa cộng một pong chờ nữa. Lỗi gửi → ConnectionLostError.
        """
        claimed: list[int] = []  # `gen` của pong đã lấy ra để gửi

        def frame() -> bytes | None:
            item = pending.take()
            if item is None:
                return None
            gen, t = item
            claimed.append(gen)
            return encode_message(to_dict(Pong(t=t)))

        await self._conn._send_frame(frame)
        if claimed:
            pending.sent(claimed[0])

    async def _keepalive_loop(self, keepalive: Keepalive) -> CloseReason:
        loop = asyncio.get_running_loop()
        while True:
            action = keepalive.poll(loop.time())
            if action is KeepaliveAction.DEAD:
                log.debug("%r: không nhận được gì trong %.1f s, coi là mất", self._conn, self._dead_after)
                return CloseReason.KEEPALIVE
            if action is KeepaliveAction.SEND_PING:
                t = int(time.monotonic() * 1000) % (MAX_SAFE_INTEGER + 1)
                try:
                    await self._conn.send(Ping(t=t))
                except ConnectionLostError:
                    return await _after_send_lost(self._conn)
                continue
            await asyncio.sleep(max(0.0, keepalive.next_wakeup() - loop.time()))

    async def _pong_loop(self, pending: _PendingPong) -> CloseReason:
        """Gửi `pong` cho `ping` mới nhất chưa trả; chỉ kết thúc khi gửi thất bại."""
        while True:
            await pending.wakeup.wait()
            pending.wakeup.clear()
            if pending.take() is None:
                continue
            try:
                await self._send_pong(pending)
            except ConnectionLostError:
                return await _after_send_lost(self._conn)

    async def _read_loop(self, on_message: Callable[[Message], None], pending: _PendingPong) -> CloseReason:
        conn = self._conn
        while True:
            try:
                msg = await conn.receive()
            except ConnectionLostError:
                return _lost_reason(conn)
            except UnknownMessageType as e:
                # Bản mới hơn gửi message mới: bỏ qua (protocol mục 3.3). Cắt ngắn vì `type` do máy kia đặt.
                log.debug("%r: bỏ qua %.80s", conn, e)
                continue
            except (FramingError, MessageError) as e:
                log.debug("%r: lỗi giao thức (%s), đóng", conn, type(e).__name__)
                return CloseReason.PROTOCOL_ERROR
            if msg is None:
                return CloseReason.PEER_CLOSED
            if isinstance(msg, Ping):
                pending.put(msg.t)  # xếp lịch pong trước on_message; không await ở đây
            on_message(msg)


# ---- Server --------------------------------------------------------------------------------


class _Refused(Exception):
    """Từ chối một kết nối trong lúc mở đầu (chỉ dùng nội bộ, để ghi log lý do)."""


def _other_protocol(obj: dict) -> int | None:
    """`protocol` của một dict `hello` khác phiên bản của máy này; None nếu không phải trường hợp đó.

    Kiểm trên dict, trước `parse_message`, để `hello` của bản mới có trường lạ vẫn ra đúng lỗi phiên bản.
    """
    protocol = obj.get("protocol")
    if obj.get("type") == "hello" and type(protocol) is int and protocol != PROTOCOL_VERSION:
        return protocol
    return None


def _server_context(identity: Identity, trusted_certs: Iterable[str]) -> ssl.SSLContext:
    """Context phía server của cổng chung; PEM sai → ValueError hoặc `ssl.SSLError`."""
    pems = list(trusted_certs)
    for pem in pems:
        # `ssl` báo TypeError cho chuỗi không phải ASCII: đổi về ValueError cho đồng nhất.
        if not isinstance(pem, str) or not pem.isascii():
            raise ValueError("chứng chỉ tin cậy phải là chuỗi PEM ASCII")
    return tls.server_context(identity, pems, allow_anonymous=True)


def _pem_fingerprints(trusted_certs: Iterable[str]) -> list[str]:
    """Fingerprint của các PEM tin cậy đọc được; PEM sai bị bỏ qua (mất ưu tiên là chiều an toàn)."""
    result: list[str] = []
    for pem in trusted_certs:
        try:
            result.append(peer_cert_from_pem(pem).fingerprint)
        except InvalidCertificate:
            log.debug("bỏ qua một chứng chỉ tin cậy không đọc được khi cập nhật ưu tiên")
    return result


def _now() -> float:
    """Đồng hồ monotonic đưa vào `AdmissionGate` (giờ của loop đang chạy)."""
    return asyncio.get_running_loop().time()


def _check_hello(hello: object) -> Hello:
    if not isinstance(hello, Hello):
        raise ValueError("hello phải là Hello")
    if hello.protocol != PROTOCOL_VERSION:
        raise ValueError(f"hello.protocol phải là {PROTOCOL_VERSION}")
    return hello


def _check_port(port: object, lo: int) -> int:
    if type(port) is not int or not lo <= port <= 65535:
        raise ValueError(f"port phải là số nguyên {lo}–65535")
    return port


def _check_ipv4(value: object, field: str) -> ipaddress.IPv4Address:
    """IPv4 dạng chấm, viết chuẩn (không số 0 đầu, không khoảng trắng)."""
    if not isinstance(value, str):
        raise ValueError(f"{field} phải là chuỗi IPv4 dạng chấm")
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError as e:
        raise ValueError(f"{field} phải là IPv4 dạng chấm: {value!r}") from e
    if str(ip) != value:
        raise ValueError(f"{field} phải là IPv4 dạng chấm: {value!r}")
    return ip


class Listener:
    """Lắng nghe trên một cổng, nhận kết nối ghép đôi, điều khiển và dữ liệu (protocol mục 2).

    Mỗi kết nối hợp lệ được giao cho `on_connection(conn)`; tầng trên phân nhánh theo
    `conn.kind`. Khi coroutine đó kết thúc (trả về, raise hay bị hủy), Listener đóng kết
    nối: kết nối ghép đôi và điều khiển được đóng gọn (`close`); kết nối dữ liệu chưa
    đóng thì bị cắt (`abort`), vì handler kết thúc mà chưa đóng là bỏ dở. Handler phải
    sống suốt thời gian dùng kết nối; muốn đóng gọn kết nối dữ liệu thì tự gọi
    `conn.close()` trong handler. Dùng một lần: `start()`, rồi `close()`.

    Mỗi kết nối TCP mới qua `AdmissionGate.admit` trước mọi `await`; bị từ chối thì
    `transport.abort()` trước TLS (protocol mục 2.3). IP được ưu tiên khi có kết nối điều
    khiển vào đã qua kiểm `is_trusted`, hoặc khi node báo kết nối điều khiển ra thành
    công (`note_outgoing_control`); mất ưu tiên khi các kết nối từ IP đó dùng pool ưu
    tiên mà không bắt tay xong bằng chứng chỉ còn tin cậy vượt ngân sách lỗi (hạ ưu tiên).
    Kết nối dữ liệu được hoàn token như kết nối điều khiển, nhưng không cấp và không giữ
    ưu tiên. `net` chỉ kiểm phần của nó với `data_open` (chứng chỉ client còn tin cậy lúc
    nhận, CN khớp `hello`, message đúng luật, đúng loại); các kiểm tra theo lượt truyền
    (protocol mục 4.1) là việc của tầng trên, làm trước `await` đầu tiên của handler.
    """

    def __init__(
        self,
        identity: Identity,
        hello: Hello,
        trusted_certs: Iterable[str],
        is_trusted: Callable[[str], bool],
        on_connection: Callable[[Connection], Awaitable[None]],
        *,
        allow_anonymous: Callable[[str], bool] | None = None,
    ) -> None:
        """`hello` lệch danh tính hoặc khác phiên bản giao thức → ValueError; PEM sai → lỗi của `ssl`.

        `trusted_certs`: PEM của thiết bị tin cậy (`TrustStore.cert_pems()`);
        `is_trusted(fingerprint)`: thiết bị còn tin cậy không (`TrustStore.is_trusted`),
        kiểm lại lúc nhận `control_open` hay `data_open`, không có `await` nào từ lần kiểm
        đó tới phần đồng bộ đầu tiên của `on_connection`. Chỉ khi trả đúng `True` mới tính
        là còn tin cậy; giá trị khác (kể cả giá trị “truthy” như `1`) hoặc raise → coi như
        không tin cậy.

        `allow_anonymous(ip)` (chế độ ẩn, protocol mục 2.3): gọi đồng bộ ngay sau bắt tay TLS với
        mọi kết nối không có chứng chỉ client còn tin cậy, trước khi gửi `hello`. Không trả đúng
        `True` (hoặc raise) → cắt kết nối, không gửi byte ứng dụng nào. None → luôn cho.
        """
        _check_hello(hello)
        if allow_anonymous is not None and not callable(allow_anonymous):
            raise TypeError("allow_anonymous phải là None hoặc hàm")
        if hello.device_id != identity.device_id:
            raise ValueError("hello.device_id phải là device_id của danh tính này")
        self._identity = identity
        self._ctx = _server_context(identity, trusted_certs)
        self._hello_frame = encode_message(to_dict(hello))
        self._is_trusted = is_trusted
        self._allow_anonymous = allow_anonymous
        self._on_connection = on_connection
        self._server: asyncio.Server | None = None
        self._port: int | None = None
        self._starting = False
        self._closed = False
        self._close_done: asyncio.Event | None = None
        # Task của mọi kết nối (đang mở đầu hoặc đã giao), kèm writer để abort khi đóng.
        self._tasks: dict[asyncio.Task, asyncio.StreamWriter] = {}
        self._connections: set[Connection] = set()
        self._gate = AdmissionGate()

    async def start(self, host: str = "0.0.0.0", port: int = DEFAULT_PORT) -> int:
        """Bắt đầu lắng nghe; trả về cổng thật (`port=0` để hệ điều hành chọn).

        `host` phải là IPv4 dạng chấm; `port` 0–65535 → ValueError. Cổng bận → OSError.
        Gọi lần hai, hoặc sau `close()` → RuntimeError.
        """
        _check_ipv4(host, "host")
        _check_port(port, 0)
        if self._starting or self._closed:
            raise RuntimeError("Listener chỉ start được một lần")
        self._starting = True
        try:
            # start_serving=False: bind xong là trả về ngay, không có `await` nào giữa lúc bind
            # và lúc có tham chiếu tới server (bị hủy ở đó thì server rò, cổng mở tới hết tiến trình).
            server = await asyncio.start_server(self._handle, host, port, start_serving=False)
        except BaseException:
            self._starting = False  # cho phép thử lại (ví dụ với cổng khác)
            raise
        self._server = server  # close() chạy song song từ đây cũng đóng được cổng
        try:
            if self._closed:  # close() chạy trong lúc đang mở cổng
                raise RuntimeError("Listener đã đóng")
            await server.start_serving()
            if self._closed:
                raise RuntimeError("Listener đã đóng")
        except BaseException:
            server.close()
            if not self._closed:
                self._server = None
                self._starting = False  # cho phép thử lại
            raise
        self._port = server.sockets[0].getsockname()[1]
        log.debug("lắng nghe trên %s:%d", host, self._port)
        return self._port

    @property
    def port(self) -> int | None:
        """Cổng đang lắng nghe; None trước `start()`."""
        return self._port

    @property
    def opening_count(self) -> int:
        """Số kết nối đang mở đầu (chưa biết loại), cả hai pool."""
        return self._gate.opening_count

    @property
    def refusals(self) -> dict[Refusal, int]:
        """Số kết nối bị từ chối trước TLS, theo lý do (bản sao; chẩn đoán, test, đo)."""
        return self._gate.refusals

    def is_priority(self, ip: str) -> bool:
        """Kết nối mới từ `ip` có vào pool ưu tiên không (chẩn đoán, test). `ip` sai → ValueError."""
        return self._gate.is_priority(ip, _now())

    def note_outgoing_control(self, ip: str, fingerprint: str) -> int:
        """Node vừa mở xong kết nối điều khiển **ra** tới `ip` (thiết bị `fingerprint`).

        Chứng chỉ server đã được kiểm trong bắt tay (`open_control`), nên `ip` được ưu tiên
        như khi có kết nối điều khiển vào: tới khi `release_outgoing_control(handle)`, rồi
        thêm `PRIORITY_TTL`. Gọi đồng bộ ngay khi `open_control` trả về (không `await` ở
        giữa), trong loop đang chạy. Trả handle; 0 nghĩa là không cấp (IP đang bị hạ ưu
        tiên, hoặc bảng ưu tiên đầy). `ip` / `fingerprint` sai → ValueError.
        """
        handle = self._gate.control_opened(ip, fingerprint, _now())
        if handle == 0:
            log.debug("%s: không cấp ưu tiên (IP bị hạ ưu tiên hoặc bảng đầy)", ip)
        return handle

    def release_outgoing_control(self, handle: int) -> None:
        """Kết nối ra của `handle` đã kết thúc; gọi lại, hay handle 0: không làm gì."""
        self._gate.control_closed(handle, _now())

    @property
    def connection_count(self) -> int:
        """Số kết nối đã giao cho `on_connection` mà chưa đóng."""
        return len(self._connections)

    def set_hello(self, hello: Hello) -> None:
        """Thay `hello` gửi cho các kết nối từ giờ (máy này đổi tên); đồng bộ.

        Kiểm như `__init__`: lệch danh tính hoặc khác phiên bản giao thức → ValueError (giữ bản
        cũ). Kết nối đang bắt tay có thể nhận bản cũ hay bản mới; kết nối đã mở giữ bản đã gửi.
        """
        _check_hello(hello)
        if hello.device_id != self._identity.device_id:
            raise ValueError("hello.device_id phải là device_id của danh tính này")
        self._hello_frame = encode_message(to_dict(hello))

    def update_trusted(self, trusted_certs: Iterable[str]) -> None:
        """Thay danh sách tin cậy: mọi kết nối mới từ giờ dùng context mới; cổng không đổi.

        Dựng context mới trước rồi mới thay: lỗi (`ssl.SSLError`, ValueError) thì giữ
        context cũ và raise. Không đụng tới kết nối đang mở. Trước khi dựng context, IP của
        thiết bị không còn trong danh sách mất ưu tiên ngay (kể cả khi kết nối của nó còn
        sống, và kể cả khi dựng context lỗi). Sau `close()` thì không làm gì.
        """
        if self._closed:
            return
        pems = list(trusted_certs)
        self._gate.retain_trusted(_pem_fingerprints(pems))
        ctx = _server_context(self._identity, pems)
        self._ctx = ctx

    async def close(self) -> None:
        """Ngừng nhận, hủy mọi kết nối (handler của `app` nhận CancelledError), chờ có giới hạn.

        Kết nối dữ liệu đã giao bị cắt ngay (abort) trước khi hủy task, nên không có lần
        đóng gọn nào kéo tới `DRAIN_TIMEOUT`; handler đang đọc hay ghi trên đó nhận
        CancelledError hoặc ConnectionLostError. Kết nối ghép đôi và điều khiển được đóng
        gọn như thường (`CLOSE_TIMEOUT`). Gọi nhiều lần không lỗi; lời gọi đồng thời chờ
        lời gọi đầu.
        """
        if self._close_done is not None:
            await self._close_done.wait()
            return
        self._closed = True
        self._close_done = asyncio.Event()
        try:
            if self._server is not None:
                self._server.close()
            for delivered in list(self._connections):
                if delivered.kind is ConnectionKind.DATA:
                    delivered.abort()  # không đóng gọn: không chờ tới DRAIN_TIMEOUT
            tasks = dict(self._tasks)
            for task in tasks:
                task.cancel()
            if tasks:
                _, pending = await asyncio.wait(set(tasks), timeout=CLOSE_TIMEOUT + 1)
                by_writer = {conn._writer: conn for conn in self._connections}
                for task in pending:
                    log.warning("kết nối %s không dừng sau khi hủy, abort", task.get_name())
                    conn = by_writer.get(tasks[task])
                    if conn is None:
                        _abort(tasks[task])  # còn đang mở đầu
                    else:
                        # Qua Connection để `ControlChannel.run` (nếu có) báo LOCAL, không PEER_CLOSED.
                        conn._close_called = True
                        conn._abort()
            if self._server is not None:
                # Từ Python 3.12.1, wait_closed chờ mọi kết nối đóng: phải có giới hạn.
                try:
                    async with asyncio.timeout(CLOSE_TIMEOUT):
                        await self._server.wait_closed()
                except TimeoutError:
                    log.warning("server chưa đóng hết kết nối sau %.1f s", CLOSE_TIMEOUT)
        finally:
            self._close_done.set()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    # ---- Một kết nối -----------------------------------------------------------------------

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        # Không được có điểm dừng (await thật) nào trước `start_tls` (trong `_handshake`):
        # ClientHello tới trước khi start_tls tạm dừng đọc có thể rơi vào bộ đệm StreamReader
        # cũ và làm bắt tay treo (Python < 3.14). Các `await` trước đó không dừng thật.
        # Sau `start_tls`, `reader` vẫn giữ transport TCP gốc (asyncio chỉ thay transport của
        # writer): khi bộ đệm đầy, nó tạm dừng đọc ngay trên socket, nên backpressure của kết
        # nối dữ liệu phía server vẫn chạy (đo ở test backpressure phía Listener).
        peername = writer.get_extra_info("peername")
        ip, port = (peername[0], peername[1]) if isinstance(peername, tuple) else ("", 0)
        task = asyncio.current_task()
        assert task is not None
        task.set_name(f"{_TASK_NAME} {ip}:{port}")
        if self._closed:
            _abort(writer)
            return
        try:
            decision = self._gate.admit(ip, _now())
        except ValueError:  # peername không phải địa chỉ IP
            log.debug("địa chỉ máy kia không hợp lệ (%.60r), đóng ngay", peername)
            _abort(writer)
            return
        if not isinstance(decision, Ticket):
            # DEBUG: lũ kết nối không được làm ngập log; số đếm ở `refusals`.
            log.debug("%s: từ chối trước TLS (%s)", ip, decision.value)
            _abort(writer)
            return
        # Vé cấp ngay trước try/finally: mọi đường ra đều trả chỗ (finish gọi lại không sao).
        ticket = decision
        try:
            self._tasks[task] = writer
            await self._serve(reader, writer, ticket, port)
        finally:
            self._tasks.pop(task, None)
            self._gate.finish(ticket, _now())

    async def _serve(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ticket: Ticket, port: int
    ) -> None:
        """Mở đầu kết nối rồi giao cho `on_connection`; luôn đóng kết nối khi xong.

        Vé được trả lúc giao kết nối (đã biết loại), và lần nữa trong `_handle`. Chỉ kết
        nối điều khiển vào mới cấp ưu tiên cho IP; kết nối dữ liệu thì không. Khi handler
        kết thúc: kết nối ghép đôi và điều khiển được đóng gọn; kết nối dữ liệu chưa đóng
        thì bị cắt (handler đã tự gọi `close()` thì chỉ chờ lần đóng đó xong).
        """
        ip = ticket.ip
        conn: Connection | None = None
        handle = 0  # kết nối điều khiển vào: handle ưu tiên của gate
        try:
            try:
                async with asyncio.timeout(OPENING_TIMEOUT):
                    kind, cert, hello, opening = await self._handshake(reader, writer, ticket)
            except _Refused as e:
                log.debug("%s: từ chối kết nối: %s", ip, e)
                return
            except TimeoutError:
                log.debug("%s: hết giờ mở đầu kết nối", ip)
                return
            except (OSError, FramingError, MessageError, InvalidCertificate) as e:
                log.debug("%s: từ chối kết nối: %s", ip, type(e).__name__)
                return
            except Exception:
                log.exception("lỗi không mong đợi khi mở đầu kết nối từ %s", ip)
                return

            # Giao kết nối. Không có await nào giữa lần gọi is_trusted (trong _handshake) và
            # on_connection: app ghi nhận được kết nối trước khi lệnh hủy ghép đôi nào chạy xen.
            loop = asyncio.get_running_loop()
            self._gate.finish(ticket, loop.time())
            conn = Connection(
                kind=kind,
                peer=PeerInfo(address=ip, port=port, hello=hello, cert=cert),
                is_server=True,
                opening=opening,
                opened_at=loop.time(),
                reader=reader,
                writer=writer,
            )
            self._connections.add(conn)
            if kind is ConnectionKind.CONTROL:
                assert cert is not None
                # Cùng khối đồng bộ với lần kiểm is_trusted: IP vừa chứng minh bằng mTLS.
                handle = self._gate.control_opened(ip, cert.fingerprint, loop.time())
                if handle == 0:
                    log.debug("%s: không cấp ưu tiên (IP bị hạ ưu tiên hoặc bảng đầy)", ip)
            try:
                await self._on_connection(conn)
            except Exception:
                log.exception("on_connection raise với %r", conn)
            else:
                if conn.kind is ConnectionKind.DATA and not conn.closed:
                    log.debug("%r: handler trả về mà kết nối dữ liệu chưa đóng, cắt", conn)
        finally:
            if handle:
                self._gate.control_closed(handle, _now())
            if conn is None:
                _abort(writer)  # từ chối: không đóng gọn, kẻ tấn công không giữ được socket
            else:
                try:
                    if conn.kind is ConnectionKind.DATA and not conn.closed:
                        # Handler kết thúc (trả về, raise hay bị hủy) mà chưa đóng: bỏ dở → cắt,
                        # không đóng gọn (protocol mục 2.3, 4.1), không để socket sống tới DRAIN_TIMEOUT.
                        conn.abort()
                    await conn.close()  # kết nối dữ liệu đã đóng: chỉ chờ lần đóng đang chạy xong
                finally:
                    self._connections.discard(conn)

    async def _handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, ticket: Ticket
    ) -> tuple[ConnectionKind, PeerCert | None, Hello, PairRequest | ControlOpen | DataOpen]:
        """Bắt tay TLS, trao `hello`, đọc message mở đầu.

        Kết nối không có chứng chỉ client còn tin cậy (ẩn danh, hay chứng chỉ vừa thôi tin cậy):
        hỏi `allow_anonymous` trước khi gửi `hello`, không có `await` ở giữa. Với `control_open`
        và `data_open`, kiểm lại `is_trusted` sau khi đọc message mở đầu (context bắt tay có thể
        đã cũ); đây là lần kiểm cuối trước khi `_serve` giao kết nối, không có `await` nào ở
        giữa. Từ chối → `_Refused`, hoặc lỗi I/O / khung / message bay ra nguyên trạng.
        """
        # Await đầu tiên của kết nối (xem _handle). Context hiện tại lúc gọi. Chưa biết loại
        # kết nối, nên hạn tắt TLS phải đủ cho lần đóng gọn dài nhất (kết nối dữ liệu).
        await writer.start_tls(self._ctx, ssl_shutdown_timeout=_ssl_shutdown_timeout(None))

        ssl_object = writer.get_extra_info("ssl_object")
        der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
        cert: PeerCert | None = None
        if der is not None:
            cert = peer_cert_from_der(der)
            # Máy kia đã ký CertificateVerify bằng khóa riêng của một chứng chỉ mà context chấp
            # nhận; context có thể cũ (vừa hủy ghép đôi) nên kiểm lại danh sách hiện tại. Còn tin
            # cậy thì lần bắt tay này không tiêu ngân sách tốc độ, và vé ưu tiên không tính là
            # một lần lỗi của IP (protocol mục 2.3).
            if self._still_trusted(cert.fingerprint):
                self._gate.trusted(ticket, _now())
            elif not self._anonymous_allowed(ticket.ip):
                raise _Refused("máy đang ẩn")
        else:
            # Chế độ ẩn: hỏi trước `gate.anonymous` (token đã trừ ở `admit`, nên từ chối ở đây
            # không lách được giới hạn tốc độ) và trước khi ghi `hello`.
            if not self._anonymous_allowed(ticket.ip):
                raise _Refused("máy đang ẩn")
            if not self._gate.anonymous(ticket, _now()):
                raise _Refused("quá giới hạn kết nối ẩn danh")

        # Trước message mở đầu, server không gửi gì ngoài hello (protocol mục 2.1).
        await _write_chunks(writer, self._hello_frame)

        obj = await read_message(reader, MAX_PAIRING_MESSAGE_SIZE)
        if obj is None:
            raise _Refused("EOF trước hello")
        peer_protocol = _other_protocol(obj)
        if peer_protocol is not None:
            shown = peer_protocol if 0 <= peer_protocol < 1_000_000 else "?"
            log.info("%s: khác phiên bản giao thức (protocol %s), đóng", ticket.ip, shown)
            raise _Refused("khác phiên bản giao thức")
        hello = parse_message(obj)
        if not isinstance(hello, Hello):
            raise _Refused(f"message đầu là {hello.TYPE}, không phải hello")
        if cert is not None and cert.device_id != hello.device_id:
            raise _Refused("CN của chứng chỉ khác hello.device_id")

        obj = await read_message(reader, MAX_PAIRING_MESSAGE_SIZE)
        if obj is None:
            raise _Refused("EOF trước message mở đầu")
        opening = parse_message(obj)
        kind = opening_kind(opening, has_client_cert=cert is not None)
        if kind is not ConnectionKind.PAIRING:
            assert cert is not None
            # Bắt tay có thể đã dùng context cũ, trước khi máy này bị hủy ghép đôi (protocol mục 7).
            if not self._still_trusted(cert.fingerprint):
                raise _Refused(f"{cert.fingerprint} không còn trong danh sách tin cậy")
        return kind, cert, hello, cast(PairRequest | ControlOpen | DataOpen, opening)

    def _anonymous_allowed(self, ip: str) -> bool:
        """`allow_anonymous(ip)` là đúng `True`; None → True; raise → False (log DEBUG, tránh ngập log)."""
        allow = self._allow_anonymous
        if allow is None:
            return True
        try:
            return allow(ip) is True
        except Exception as e:
            log.debug("%s: allow_anonymous raise (%s), từ chối", ip, type(e).__name__)
            return False

    def _still_trusted(self, fingerprint: str) -> bool:
        try:
            return self._is_trusted(fingerprint) is True
        except Exception:
            log.exception("is_trusted raise, coi như không tin cậy")
            return False


# ---- Client --------------------------------------------------------------------------------


def _check_addresses(addresses: object) -> list[str]:
    """1–16 IPv4 dạng chấm; bỏ 0.0.0.0, multicast, 255.255.255.255; bỏ trùng, giữ thứ tự.

    Loopback được phép (test dùng 127.0.0.1). Bỏ xong không còn địa chỉ nào → ValueError.
    """
    if isinstance(addresses, str | bytes):
        raise ValueError("addresses phải là một danh sách địa chỉ, không phải một chuỗi")
    try:
        items = list(addresses)  # type: ignore[call-overload]
    except TypeError as e:
        raise ValueError("addresses phải là một danh sách địa chỉ") from e
    if not 1 <= len(items) <= _MAX_ADDRESSES:
        raise ValueError(f"addresses phải có 1–{_MAX_ADDRESSES} địa chỉ")
    result: list[str] = []
    for value in items:
        ip = _check_ipv4(value, "địa chỉ")
        if ip.is_unspecified or ip.is_multicast or ip == _BROADCAST:
            continue  # không phải địa chỉ của một máy
        if value not in result:
            result.append(value)
    if not result:
        raise ValueError("không có địa chỉ nào kết nối tới được")
    return result


async def open_pairing(addresses: Sequence[str], port: int, hello: Hello) -> Connection:
    """Mở kết nối ghép đôi (ẩn danh) tới một máy; thử song song mọi địa chỉ.

    Không gửi gì sau `hello`: `app` gửi `pair_request` bằng `conn.send`. Tham số sai →
    ValueError (trước mọi I/O). Mọi địa chỉ thất bại → lỗi đáng báo nhất (`most_relevant_error`).
    """
    addrs = _check_addresses(addresses)
    _check_port(port, 1)
    _check_hello(hello)
    return await _open_any(addrs, port, tls.client_context(), hello, ConnectionKind.PAIRING, None)


async def open_control(
    addresses: Sequence[str], port: int, identity: Identity, hello: Hello, expected_cert_pem: str
) -> Connection:
    """Mở kết nối điều khiển (mTLS) tới một thiết bị tin cậy; thử song song mọi địa chỉ.

    `expected_cert_pem`: chứng chỉ đã lưu khi ghép đôi (`TrustedDevice.cert_pem`). Server
    phải đưa đúng chứng chỉ đó ngay trong bắt tay (`tls.trusted_client_context`); nếu
    không, bắt tay hỏng trước khi máy này gửi chứng chỉ của mình → IdentityMismatch. Sau
    bắt tay fingerprint vẫn được so toàn bộ trước khi gửi bất kỳ byte nào. Tham số sai,
    kể cả PEM không phải chứng chỉ thiết bị hợp lệ → ValueError (trước mọi I/O). Mọi địa
    chỉ thất bại → lỗi đáng báo nhất (`most_relevant_error`).
    """
    addrs = _check_addresses(addresses)
    _check_port(port, 1)
    _check_hello(hello)
    if hello.device_id != identity.device_id:
        raise ValueError("hello.device_id phải là device_id của danh tính này")
    try:
        expected = peer_cert_from_pem(expected_cert_pem)
    except InvalidCertificate as e:
        raise ValueError(f"expected_cert_pem không phải chứng chỉ thiết bị hợp lệ: {e}") from e
    # PEM đã chuẩn hóa: đúng một chứng chỉ làm anchor, fingerprint không lệch PEM.
    ctx = tls.trusted_client_context(identity, expected.pem)
    return await _open_any(addrs, port, ctx, hello, ConnectionKind.CONTROL, expected.fingerprint)


async def _open_any(
    addresses: list[str],
    port: int,
    ctx: ssl.SSLContext,
    hello: Hello,
    kind: ConnectionKind,
    expected_fingerprint: str | None,
) -> Connection:
    """Thử mọi địa chỉ cùng lúc; giữ kết nối thành công đầu tiên, đóng mọi kết nối thừa.

    Mỗi lần thử chỉ đi tới khi đã kiểm xong `hello` của server; `control_open` chỉ được
    gửi trên kết nối thắng, sau khi các lần thử khác đã bị hủy và đóng, nên server không
    bao giờ nhận một kết nối điều khiển thừa. Không để lại task hay socket, kể cả khi
    chính hàm này bị hủy.
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + OPENING_TIMEOUT  # gửi control_open vẫn nằm trong thời hạn mở kết nối
    hello_frame = encode_message(to_dict(hello))
    tasks = [
        asyncio.create_task(
            _attempt(address, port, ctx, hello_frame, kind, expected_fingerprint),
            name=f"{_TASK_NAME}.open {address}:{port}",
        )
        for address in addresses
    ]
    winner: Connection | None = None
    try:
        pending = set(tasks)
        while pending and winner is None:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:  # theo thứ tự địa chỉ
                if task in done and task.exception() is None:
                    winner = task.result()
                    break
    finally:
        for task in tasks:
            task.cancel()
        try:
            await asyncio.wait(tasks)
        except BaseException:  # bị hủy trong lúc dọn: kết nối thắng cũng không được trả về
            if winner is not None:
                winner._abort()
            raise
        finally:
            for task in tasks:
                if task.done() and not task.cancelled() and task.exception() is None:
                    conn = task.result()
                    if conn is not winner:
                        conn._abort()
    if winner is not None:
        if kind is ConnectionKind.CONTROL:
            await _send_opening(winner, _CONTROL_OPEN_FRAME, deadline)
        winner._opened_at = loop.time()
        return winner

    errors: list[ConnectError] = []
    for address, task in zip(addresses, tasks, strict=True):
        exc = task.exception()
        if not isinstance(exc, ConnectError):
            raise cast(BaseException, exc)  # lỗi lập trình: không che đi
        log.debug("kết nối tới %s:%d thất bại: %s: %s", address, port, type(exc).__name__, exc)
        errors.append(exc)
    raise most_relevant_error(errors)


async def _send_opening(conn: Connection, frame: bytes, deadline: float) -> None:
    """Gửi message mở đầu (`control_open` / `data_open`, đã mã hóa) trước `deadline` (giờ của loop).

    Lỗi socket/TLS hoặc hết giờ → abort rồi Unreachable. Bị hủy → abort rồi để
    CancelledError bay ra: kết nối không được trả về thì không được để lại socket.
    """
    address = conn.peer.address
    try:
        async with asyncio.timeout_at(deadline):
            await conn._send_frame(frame)
    except (ConnectionLostError, TimeoutError) as e:
        conn._abort()
        cause = e.__cause__ if e.__cause__ is not None else e
        raise Unreachable(f"gửi message mở đầu thất bại: {type(cause).__name__}", address=address) from e
    except BaseException:
        conn._abort()
        raise


async def open_data(
    address: str, port: int, identity: Identity, hello: Hello, expected_cert_pem: str, opening: DataOpen
) -> Connection:
    """Mở kết nối dữ liệu (mTLS) tới một thiết bị tin cậy: đúng một địa chỉ, một lần thử.

    Kết nối dữ liệu chỉ mở tới đúng địa chỉ (IP và cổng) của kết nối điều khiển hiện tại,
    không thử song song, không tự thử lại (protocol mục 4.1): lần thử thua bị hủy giữa
    bắt tay tính là một lần lỗi của IP đó ở máy kia. Lịch thử lại là việc của tầng trên
    (thực thi hành động của `teleport.core.transfer`).

    `address`: một chuỗi IPv4 dạng chấm viết chuẩn (không phải danh sách; không nhận
    0.0.0.0, multicast, 255.255.255.255; loopback được); `port` 1–65535; `hello` đúng
    phiên bản giao thức và của chính `identity`; `expected_cert_pem`: chứng chỉ đã lưu
    của máy kia (`TrustedDevice.cert_pem`); `opening`: `data_open` sẽ gửi. Tham số sai →
    ValueError, trước mọi I/O.

    Bắt tay với `tls.trusted_client_context` như `open_control`; cả chuỗi TCP + TLS + đọc
    `hello` của server + gửi `data_open` nằm trong một hạn `OPENING_TIMEOUT`. Lỗi của lần
    thử duy nhất được ném thẳng: chứng chỉ server không qua kiểm trong bắt tay →
    IdentityMismatch (`actual_fingerprint` None; máy kia không nhận được chứng chỉ client,
    `hello` hay `data_open`); fingerprint lệch, chứng chỉ không hợp lệ hay CN khác
    `hello.device_id` → IdentityMismatch; EOF / lỗi SSL / reset trước `hello`, sau bắt tay
    → Rejected; `protocol` khác → VersionMismatch; lỗi TCP/TLS khác, hết hạn, `hello` sai
    hay gửi `data_open` lỗi → Unreachable. Bị hủy → không để lại socket hay task.

    Server không xác nhận `data_open` (protocol mục 2.1, 4.1): server từ chối sau khi đọc
    nó thì máy này chỉ thấy ở lần đọc hoặc ghi đầu tiên (None hoặc ConnectionLostError).
    Kết nối trả về có `opening` là None; `peer.port` là `port`.
    """
    ip = _check_ipv4(address, "address")
    if ip.is_unspecified or ip.is_multicast or ip == _BROADCAST:
        raise ValueError(f"address không phải địa chỉ của một máy: {address!r}")
    _check_port(port, 1)
    _check_hello(hello)
    if hello.device_id != identity.device_id:
        raise ValueError("hello.device_id phải là device_id của danh tính này")
    try:
        expected = peer_cert_from_pem(expected_cert_pem)
    except InvalidCertificate as e:
        raise ValueError(f"expected_cert_pem không phải chứng chỉ thiết bị hợp lệ: {e}") from e
    if not isinstance(opening, DataOpen):
        raise ValueError("opening phải là DataOpen")
    opening_frame = encode_message(to_dict(opening))
    # PEM đã chuẩn hóa: đúng một chứng chỉ làm anchor, fingerprint không lệch PEM.
    ctx = tls.trusted_client_context(identity, expected.pem)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + OPENING_TIMEOUT  # gửi data_open vẫn nằm trong thời hạn mở kết nối
    hello_frame = encode_message(to_dict(hello))
    conn = await _attempt(address, port, ctx, hello_frame, ConnectionKind.DATA, expected.fingerprint)
    await _send_opening(conn, opening_frame, deadline)
    conn._opened_at = loop.time()
    return conn


async def _attempt(
    address: str,
    port: int,
    ctx: ssl.SSLContext,
    hello_frame: bytes,
    kind: ConnectionKind,
    expected_fingerprint: str | None,
) -> Connection:
    """Một lần thử tới một địa chỉ (protocol mục 2.2). Lỗi → ConnectError; không để lại socket.

    Chỉ đi tới khi đã đọc và kiểm xong `hello` của server; không gửi message mở đầu
    (`_open_any` gửi `control_open` trên kết nối thắng, `open_data` gửi `data_open`).
    Ranh giới Unreachable / Rejected là lúc bắt tay TLS xong: server đóng ngay các kết nối
    vượt giới hạn trước TLS, nên lỗi trước đó không được coi là “bị từ chối” (protocol
    §6.2). Ngoại lệ duy nhất trước ranh giới đó: chứng chỉ server không qua kiểm trong bắt
    tay (`ssl.SSLCertVerificationError`, chỉ có ở kết nối điều khiển và dữ liệu) →
    IdentityMismatch. Máy kia đưa đúng chứng chỉ đã lưu mà không có khóa riêng thì bắt
    tay hỏng với lỗi SSL khác → Unreachable.
    """
    writer: asyncio.StreamWriter | None = None
    try:
        async with asyncio.timeout(OPENING_TIMEOUT):
            try:
                reader, writer = await asyncio.open_connection(
                    address, port, ssl=ctx, ssl_shutdown_timeout=_ssl_shutdown_timeout(kind)
                )
            except ssl.SSLCertVerificationError as e:  # lớp con của OSError: phải đứng trước
                # Chứng chỉ server khác chứng chỉ đã lưu: hỏng ở máy này, trước khi gửi chứng chỉ client.
                raise IdentityMismatch(
                    "chứng chỉ của máy kia khác chứng chỉ đã lưu", address=address, actual_fingerprint=None
                ) from e
            except OSError as e:  # gồm ssl.SSLError
                raise Unreachable(f"không mở được TCP/TLS: {type(e).__name__}", address=address) from e

            # Kiểm danh tính server trước khi gửi bất kỳ byte nào.
            ssl_object = writer.get_extra_info("ssl_object")
            der = ssl_object.getpeercert(binary_form=True) if ssl_object is not None else None
            if der is None:
                raise IdentityMismatch("máy kia không gửi chứng chỉ", address=address)
            actual = fingerprint_of_der(der)
            if expected_fingerprint is not None:
                try:
                    tls.verify_fingerprint(actual, expected_fingerprint)
                except tls.FingerprintMismatch as e:
                    raise IdentityMismatch(
                        "fingerprint khác fingerprint đã lưu", address=address, actual_fingerprint=actual
                    ) from e
            try:
                cert = peer_cert_from_der(der)
            except Exception as e:  # InvalidCertificate; phòng thủ: lỗi lạ cũng là danh tính sai
                raise IdentityMismatch(
                    "chứng chỉ của máy kia không hợp lệ", address=address, actual_fingerprint=actual
                ) from e

            # Dưới TLS 1.3, client bị từ chối chỉ thấy lỗi ở lần đọc đầu: phải đọc được hello.
            try:
                await _write_chunks(writer, hello_frame)
                obj = await read_message(reader, MAX_PAIRING_MESSAGE_SIZE)
            except FramingError as e:
                raise Unreachable("máy kia không nói giao thức Teleport", address=address) from e
            except OSError as e:  # gồm ssl.SSLError, ConnectionResetError
                detail = f"máy kia đóng kết nối trước hello: {type(e).__name__}"
                raise Rejected(detail, address=address) from e
            if obj is None:
                raise Rejected("máy kia đóng kết nối trước hello", address=address)
            peer_protocol = _other_protocol(obj)
            if peer_protocol is not None:
                raise VersionMismatch(
                    "máy kia dùng phiên bản giao thức khác", address=address, peer_protocol=peer_protocol
                )
            try:
                server_hello = parse_message(obj)
            except MessageError as e:
                raise Unreachable("hello của máy kia không hợp lệ", address=address) from e
            if not isinstance(server_hello, Hello):
                raise Unreachable("máy kia không gửi hello", address=address)
            if server_hello.device_id != cert.device_id:
                raise IdentityMismatch(
                    "CN của chứng chỉ khác hello.device_id", address=address, actual_fingerprint=actual
                )
    except TimeoutError as e:
        if writer is not None:
            _abort(writer)
        raise Unreachable(f"hết giờ sau {OPENING_TIMEOUT} s", address=address) from e
    except BaseException:
        if writer is not None:
            _abort(writer)
        raise

    return Connection(
        kind=kind,
        peer=PeerInfo(address=address, port=port, hello=server_hello, cert=cert),
        is_server=False,
        opening=None,
        opened_at=asyncio.get_running_loop().time(),
        reader=reader,
        writer=writer,
    )
