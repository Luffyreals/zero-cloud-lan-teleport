"""Giữ kết nối điều khiển tới các thiết bị tin cậy (sans-IO): chống trùng, nối lại, chặn.

Đặc tả ở docs/protocol.md mục 6.1 và 6.2. Module không mở socket, không xem đồng hồ:
tầng `app` đưa sự kiện (mDNS thấy/mất thiết bị, danh sách tin cậy đổi, kết quả một
lần mở kết nối, kết nối vào, kết nối mất, mạng đổi, hẹn giờ) cùng thời gian monotonic
`now` vào `LinkTracker`, rồi thực hiện các hành động nó trả về:

- `Connect`: mở kết nối điều khiển (luôn kiểm với chứng chỉ đã lưu trong `trusted.json`),
  rồi báo kết quả qua `connect_finished`;
- `CancelConnect`: hủy lần mở đang chạy (không báo `connect_finished` cho lần đó);
- `CloseConnection`: đóng một kết nối;
- `Notify`: báo một sự kiện kết nối (`LinkUp`, `LinkDown`, `LinkFailed` cho người dùng;
  `LinkSwitched` chỉ cho các phần khác của `app`).

Luật chính:

- Tối đa một kết nối điều khiển cho mỗi thiết bị. Hai kết nối cùng sống: kết nối cũ
  đã mở ≥ `REPLACE_AFTER` giây, hoặc hai kết nối do cùng một bên mở → giữ kết nối mới;
  còn lại (hai bên gọi nhau cùng lúc) giữ kết nối do bên có `device_id` nhỏ hơn mở.
  Đổi kết nối không báo người dùng: giữ kết nối mới thì phát `LinkSwitched` (sau
  `CloseConnection` của kết nối cũ) để `app` chuyển kênh điều khiển sang kết nối mới;
  giữ kết nối cũ thì chỉ đóng kết nối mới.
- Nối lại theo lịch 1, 2, 4… ≤ 30 s. Máy kia từ chối, danh tính không khớp hay khác
  phiên bản giao thức thì “chặn”: không thử lại theo lịch, chỉ khi có sự kiện mDNS
  hoặc mạng đổi (vẫn theo lịch tính từ lần thử trước), hoặc người dùng thao tác.
  Ngoại lệ, chỉ cho bị từ chối: thiết bị đang `hold` (còn lượt truyền dở) thì vẫn thử lại
  theo lịch, mỗi lần cách lần thất bại ≥ `max(EVENT_RETRY_GAP, lịch)`, và chỉ báo một lần,
  vì lỗi tạm (máy kia khởi động lại, mạng chập) trông giống bị từ chối. `hold(False)` để lại
  tối đa một lần thử đã hẹn (không còn nếu địa chỉ mDNS đã cũ); lần đó bị từ chối thì chặn
  hẳn như trên.
- Mọi lần thử do sự kiện cách lần trước ≥ `EVENT_RETRY_GAP` (kể cả khi bị chặn: không
  sớm hơn `max(EVENT_RETRY_GAP, lịch)`), nên kẻ giả mạo mDNS chỉ làm node thử với tốc
  độ có trần. Lịch 1, 2, 4… là lịch theo thời gian, không bị giới hạn này.
- Mỗi loại lỗi chỉ báo một lần cho tới khi kết nối được hoặc người dùng thao tác;
  “không kết nối được” chỉ báo sau `UNREACHABLE_REPORT_AFTER` lần thất bại liên tiếp.
- mDNS chỉ là gợi ý địa chỉ: thiết bị biến mất khỏi mDNS thì ngừng thử lại (trừ khi
  đang `hold`, xem dưới), nhưng kết nối đang sống không bị đóng.
- Lịch §6.2 (hẹn giờ, đếm lần “không kết nối được” → `LinkFailed`) chỉ chạy khi có địa chỉ
  mDNS còn tươi hoặc thiết bị đang `hold` (protocol §6.1, §6.2). Thiết bị chỉ có `hint` chỉ
  được thử khi có thao tác người dùng hoặc sự kiện (`hint`, `retry_now`, `network_changed`,
  `trusted_changed`, `hold(True)`): không hẹn lịch, không đếm tới `UNREACHABLE_REPORT_AFTER`.
  Riêng lần thử do chính `hint()` gây ra (ngay lúc gọi, hoặc lần kế tiếp khi gọi lúc đang thử)
  mà “không kết nối được” thì luôn báo `LinkFailed(UNREACHABLE)` ngay, có lịch hay không, tối
  đa một lần cho mỗi lần gọi `hint` (người dùng đưa địa chỉ và đang chờ kết quả, ví dụ
  `teleport send --address`; mDNS có thể báo máy đi trước khi đếm đủ). Khi có lịch, lịch và bộ
  đếm vẫn chạy như thường (đã báo thì không báo lại tới khi kết nối được hay người dùng thao
  tác); các lần thử khác tới địa chỉ `hint` không báo.
- `hint` là địa chỉ do người dùng đưa (ví dụ khi mDNS bị chặn): tracker nhớ nó tới khi có
  `hint` mới hoặc thiết bị thôi tin cậy, kể cả sau khi mDNS báo thiết bị biến mất. Gọi
  `hint` tính là người dùng thao tác (gỡ chặn, xóa bộ đếm, thử ngay).
- Địa chỉ đích của một lần thử (`_target`): địa chỉ mDNS nếu còn tươi; không thì `hint`;
  không thì địa chỉ mDNS cũ (chỉ còn khi đang `hold`). Có cả `hint` và mDNS tươi cùng
  cổng: địa chỉ `hint` trước rồi địa chỉ mDNS, bỏ trùng, tối đa `_MAX_ADDRESSES`. Khác
  cổng: lần thử do chính `hint()` gây ra dùng địa chỉ/cổng `hint` (gọi lúc đang thử thì
  lần thử kế tiếp, sau khi lần đó kết thúc, dùng `hint`), các lần sau dùng mDNS. Không có
  địa chỉ nào ở trên thì dùng địa chỉ đã lưu (`saved`, xem dưới); `saved` không bao giờ gộp
  với địa chỉ khác, để lỗi của lần thử nhắm vào nó nhận diện được. Giới hạn đã biết: đang
  `hold` thì địa chỉ mDNS cũ đứng trước `saved`, kể cả khi địa chỉ cũ không còn đúng.
- `remember` (protocol §6.2, gạch “Địa chỉ đã lưu”): `app` đưa địa chỉ đã quan sát được của
  thiết bị tin cậy (lúc khởi động, từ `trusted.json`; hoặc vừa kết nối ra thành công). Chỉ
  nhận địa chỉ không phải Internet công khai (`is_saveable`). Tracker nhớ đúng một địa chỉ
  (`saved`) tới khi thôi tin cậy, có địa chỉ khác, hoặc lần thử tới đó gặp sai danh tính.
  Lần thử nhắm vào `saved` mà không `hold` có lịch riêng: thất bại thứ n hẹn lại sau
  `min(SAVED_RETRY_BASE · 2^(n−1), SAVED_RETRY_MAX)`; sau `SAVED_MAX_ATTEMPTS` lần liên tiếp
  (một “đợt”) thì chỉ còn một lần mỗi `SAVED_RETRY_MAX`, kể cả lần thử do sự kiện. Lịch này
  không báo `LinkFailed(UNREACHABLE)` và không tính vào bộ đếm §6.2. Đợt bắt đầu lại khi kết
  nối được, có địa chỉ khác, người dùng thao tác (`hint`, `retry_now`, `trusted_changed`),
  mạng đổi, hoặc mất kết nối hiện tại; sự kiện mDNS và `hold` không bắt đầu lại đợt (mDNS do
  người khác điều khiển được). Sai danh tính tại `saved`: quên nó trong phiên, không báo,
  không chặn. Lỗi chặn khác (bị từ chối, khác phiên bản) thì như mọi địa chỉ. Đang `hold`
  thì lần thử tới `saved` theo lịch §6.2. mDNS báo máy đi (không `hold`) thì thử `saved` sau
  `SAVED_GONE_GRACE`; mất kết nối, `hold(False)`, hay lần thử khác “không kết nối được” mà
  không còn lịch nào, thì sau `SAVED_RETRY_BASE` (hết đợt thì vẫn theo nhịp `SAVED_RETRY_MAX`).
- `LinkFailed.from_hint` đánh dấu lỗi của lần thử do `hint()` gây ra (kèm `addresses`, `port`
  của lần thử đó), để `app` biết lỗi thuộc địa chỉ người dùng vừa đưa. Lỗi chặn của lần thử
  đó luôn được báo, kể cả khi cùng loại đã được báo. Lần thử đó “không kết nối được” hay sai
  danh tính khi có `saved` thì quên `hint`, kể cả khi `hint` trùng `saved` (địa chỉ nhập sai
  không che địa chỉ đã lưu); sai danh tính lúc đó không chặn thiết bị, và lịch `saved` chạy
  tiếp; `hint` trùng `saved` mà sai danh tính thì `saved` cũng bị quên trong phiên.
- `hold(device_id, True)` (app gọi khi thiết bị còn lượt truyền dở, protocol §6.1, §6.2):
  mDNS báo biến mất thì địa chỉ cũ chỉ bị đánh dấu cũ (`stale`), lịch nối lại vẫn chạy;
  `hold(False)` lúc địa chỉ đã cũ thì quên nó như khi mDNS vừa báo biến mất. `hold` chỉ
  áp cho thiết bị tin cậy, không sống qua lần thôi tin cậy, và không bao giờ trả
  `CloseConnection` hay `Notify`.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from teleport.core.messages import MessageError, validate_device_id
from teleport.core.numbers import is_finite

# Thời gian tính bằng giây; đọc lúc dùng để test rút ngắn được bằng monkeypatch.
# protocol §6.1: kết nối cũ đã mở ≥ 15 s thì kết nối mới thay. Phải lớn hơn hạn mở kết nối
# (net OPENING_TIMEOUT, protocol §2.3) cộng độ lệch đo giữa hai bên: một lần mở chậm của hai
# bên gọi nhau cùng lúc nếu bị coi là “nối lại” ở một bên thì hai bên đóng hai kết nối khác
# nhau, mất cả hai, và lặp lại mãi nếu lần mở chậm lặp lại.
REPLACE_AFTER = 15.0
RETRY_BASE = 1.0  # protocol §6.2: lịch 1, 2, 4… giây
RETRY_MAX = 30.0  # … tối đa 30 s
EVENT_RETRY_GAP = 2.0  # sự kiện mDNS/mạng: hai lần thử tới cùng máy cách nhau ≥ 2 s
UNREACHABLE_REPORT_AFTER = 3  # báo "không kết nối được" sau 3 lần thất bại liên tiếp
# Địa chỉ đã lưu (`remember`, protocol §6.2): lịch 5, 10, 20, 40, 80 s… ≤ 300 s; một “đợt” tối đa
# 6 lần thất bại liên tiếp, rồi một lần mỗi SAVED_RETRY_MAX; mDNS báo máy đi thì chờ 15 s.
SAVED_RETRY_BASE = 5.0
SAVED_RETRY_MAX = 300.0
SAVED_MAX_ATTEMPTS = 6
SAVED_GONE_GRACE = 15.0

_MAX_ADDRESSES = 16  # như net.connection: số địa chỉ tối đa cho một lần mở kết nối
_MAX_DELAY_EXPONENT = 20  # chặn số mũ của lịch thử lại (2**20 · 1 s đã vượt xa RETRY_MAX)
_BROADCAST = ipaddress.IPv4Address("255.255.255.255")


class ConnectResult(StrEnum):
    """Kết quả một lần mở kết nối điều khiển (`app` ánh xạ từ ngoại lệ của `net`)."""

    OK = "ok"
    UNREACHABLE = "unreachable"  # net.Unreachable
    REJECTED = "rejected"  # net.Rejected
    IDENTITY_MISMATCH = "identity_mismatch"  # net.IdentityMismatch
    VERSION_MISMATCH = "version_mismatch"  # net.VersionMismatch


_BLOCKING = frozenset(
    {ConnectResult.REJECTED, ConnectResult.IDENTITY_MISMATCH, ConnectResult.VERSION_MISMATCH}
)


@dataclass(frozen=True, slots=True)
class Connect:
    """Mở kết nối điều khiển tới `addresses:port` (so fingerprint đã lưu), rồi `connect_finished`."""

    device_id: str
    attempt_id: int  # tracker cấp, tăng dần từ 1
    addresses: tuple[str, ...]
    port: int


@dataclass(frozen=True, slots=True)
class CancelConnect:
    """Hủy lần thử đang chạy; KHÔNG gọi `connect_finished` cho lần thử đó."""

    device_id: str
    attempt_id: int


@dataclass(frozen=True, slots=True)
class CloseConnection:
    """Đóng kết nối `conn_id` (lấy ra khỏi bảng ngay, đóng nền)."""

    device_id: str
    conn_id: int


@dataclass(frozen=True, slots=True)
class LinkUp:
    """Thiết bị chuyển từ 0 sang 1 kết nối điều khiển."""

    device_id: str
    conn_id: int
    outgoing: bool  # True: máy này mở


@dataclass(frozen=True, slots=True)
class LinkDown:
    """Thiết bị chuyển từ 1 về 0 kết nối (mất, hoặc thôi tin cậy)."""

    device_id: str
    conn_id: int


@dataclass(frozen=True, slots=True)
class LinkFailed:
    """Báo người dùng; `result` khác OK; mỗi loại tối đa một lần (xem `LinkTracker`).

    `from_hint`: lỗi của lần thử do `hint()` gây ra; khi đó `addresses`, `port` là đích của lần
    thử đó (còn lại: `()`, None).
    """

    device_id: str
    result: ConnectResult
    from_hint: bool = False
    addresses: tuple[str, ...] = ()
    port: int | None = None


@dataclass(frozen=True, slots=True)
class LinkSwitched:
    """Kết nối điều khiển hiện tại đổi từ `old_conn_id` sang `conn_id` (chống trùng, protocol §6.1).

    Không báo người dùng (thiết bị vẫn kết nối); `app` chuyển kênh điều khiển sang kết nối mới.
    """

    device_id: str
    old_conn_id: int
    conn_id: int
    outgoing: bool  # True: máy này mở kết nối MỚI


LinkEvent = LinkUp | LinkDown | LinkFailed | LinkSwitched


@dataclass(frozen=True, slots=True)
class Notify:
    """Báo một sự kiện kết nối (cho người dùng, trừ `LinkSwitched`)."""

    event: LinkEvent


LinkAction = Connect | CancelConnect | CloseConnection | Notify


@dataclass(slots=True)
class _Conn:
    conn_id: int
    since: float  # `now` lúc kết nối thành kết nối hiện tại (đồng hồ của máy này)
    local: bool  # máy này mở


_Target = tuple[tuple[str, ...], int]  # (địa chỉ, cổng)


@dataclass(slots=True)
class _Device:
    """Trạng thái của một thiết bị (tin cậy, hoặc chưa tin cậy nhưng đang thấy qua mDNS / có `hint`)."""

    trusted: bool = False
    seen: _Target | None = None  # (địa chỉ, cổng) mDNS gần nhất
    stale: bool = False  # mDNS đã báo biến mất trong lúc `held`: `seen` là địa chỉ cũ
    hint: _Target | None = None  # (địa chỉ, cổng) người dùng đưa qua `hint`
    held: bool = False  # còn lượt truyền dở (`hold`): không quên `seen` khi mDNS báo biến mất
    hint_next: bool = False  # `hint()` vừa gọi: lần `_start` kế tiếp dùng `hint_target()`
    hint_attempt: int | None = None  # attempt_id của lần thử do `hint()` gây ra (đang chạy)
    saved: _Target | None = None  # đúng một địa chỉ đã quan sát được (`remember`)
    saved_failures: int = 0  # lần thử `saved` (không `held`) “không kết nối được” liên tiếp trong đợt
    saved_attempt: int | None = None  # attempt_id của lần thử nhắm vào `saved` (đang chạy)
    saved_last: float | None = None  # `now` của lần thử `saved` gần nhất
    attempt_target: _Target | None = None  # đích của lần thử đang chạy
    current: _Conn | None = None
    attempt: int | None = None  # attempt_id đang chạy
    dirty: bool = False  # có sự kiện mDNS/mạng trong lúc đang thử
    failures: int = 0  # số lần thất bại liên tiếp
    blocked: bool = False  # máy kia từ chối / danh tính sai / khác phiên bản
    next_at: float | None = None  # lần thử đã hẹn
    last_start: float | None = None  # `now` của lần thử gần nhất
    reported: set[ConnectResult] = field(default_factory=set)  # loại lỗi đã báo

    def fresh(self) -> _Target | None:
        """Địa chỉ mDNS còn tươi (chưa bị báo biến mất)."""
        return self.seen if not self.stale else None

    def target(self) -> _Target | None:
        """Địa chỉ đích của lần thử theo lịch / do sự kiện (luật trong docstring module)."""
        fresh = self.fresh()
        if fresh is not None and self.hint is not None and fresh[1] == self.hint[1]:
            return _merge(self.hint, fresh)
        if fresh is not None:
            return fresh
        if self.hint is not None:
            return self.hint
        if self.seen is not None:
            return self.seen  # địa chỉ cũ, chỉ còn khi đang `held`
        return self.saved

    def from_saved(self) -> bool:
        """`target()` lấy từ nhánh `saved` (không có địa chỉ mDNS, kể cả cũ, và không có `hint`)."""
        return self.seen is None and self.hint is None and self.saved is not None

    def hint_target(self) -> _Target | None:
        """Địa chỉ của lần thử do `hint()` gây ra: `hint`, gộp với mDNS tươi nếu cùng cổng."""
        if self.hint is None:
            return None
        fresh = self.fresh()
        if fresh is not None and fresh[1] == self.hint[1]:
            return _merge(self.hint, fresh)
        return self.hint

    def scheduled(self) -> bool:
        """Lịch §6.2 có chạy không: có địa chỉ mDNS tươi, hoặc đang `held` và có địa chỉ đích."""
        return self.fresh() is not None or (self.held and self.target() is not None)

    def eligible(self) -> bool:
        """Đủ điều kiện thử: tin cậy, có địa chỉ đích, chưa kết nối, không đang thử."""
        return self.trusted and self.target() is not None and self.current is None and self.attempt is None


def _merge(hint: _Target, fresh: _Target) -> _Target:
    """`hint` và mDNS tươi cùng cổng: địa chỉ `hint` trước, bỏ trùng, tối đa `_MAX_ADDRESSES`."""
    addresses = tuple(dict.fromkeys(hint[0] + fresh[0]))[:_MAX_ADDRESSES]
    return addresses, hint[1]


def _delay(failures: int) -> float:
    """Lịch thử lại: 1, 2, 4, 8, 16, 30, 30… giây (n ≥ 1)."""
    exponent = min(max(failures, 1) - 1, _MAX_DELAY_EXPONENT)
    return min(RETRY_BASE * 2**exponent, RETRY_MAX)


def _check_id_number(name: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} phải là số nguyên ≥ 1")
    return value


def _check_port(port: object) -> int:
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port phải là số nguyên 1–65535")
    return port


def _check_addresses(addresses: object) -> tuple[str, ...]:
    """1–16 IPv4 dạng chấm viết chuẩn, không phải 0.0.0.0, multicast hay broadcast; bỏ trùng."""
    if isinstance(addresses, str | bytes) or not isinstance(addresses, Sequence):
        raise ValueError("addresses phải là một dãy địa chỉ, không phải một chuỗi")
    items = list(addresses)
    if not 1 <= len(items) <= _MAX_ADDRESSES:
        raise ValueError(f"addresses phải có 1–{_MAX_ADDRESSES} địa chỉ")
    for value in items:
        if not isinstance(value, str):
            raise ValueError("địa chỉ phải là chuỗi IPv4 dạng chấm")
        try:
            _check_ip(value)
        except ValueError as e:
            # Đầu vào của bên gọi (người dùng nhập, mDNS đã kiểm): trích giá trị cho dễ sửa.
            raise ValueError(f"{e}: {value!r}") from None
    return tuple(dict.fromkeys(items))


def _check_ip(value: object) -> str:
    """Một IPv4 dạng chấm viết chuẩn, không phải 0.0.0.0, multicast hay broadcast.

    Thông điệp lỗi không chứa giá trị (giá trị có thể đến từ file hay từ máy khác).
    """
    if not isinstance(value, str):
        raise ValueError("địa chỉ phải là chuỗi IPv4 dạng chấm")
    try:
        ip = ipaddress.IPv4Address(value)
    except ValueError:
        raise ValueError("địa chỉ phải là IPv4 dạng chấm") from None
    if str(ip) != value:
        raise ValueError("địa chỉ phải là IPv4 dạng chấm")
    if ip.is_unspecified or ip.is_multicast or ip == _BROADCAST:
        raise ValueError("địa chỉ không phải địa chỉ của một máy")
    return str(ip)


def check_endpoint(ip: object, port: object) -> tuple[str, int]:
    """Kiểm một địa chỉ `(ip, port)`; trả `(ip, port)`, sai → ValueError (thông điệp không chứa giá trị).

    `ip`: IPv4 dạng chấm viết chuẩn (`str(IPv4Address(ip)) == ip`, nên chặn luôn khoảng trắng, số 0
    ở đầu, chuỗi dài), không phải 0.0.0.0, multicast hay 255.255.255.255; loopback và link-local
    được phép; không IPv6. `port`: `int` (không phải `bool`) 1–65535. Cùng luật với địa chỉ của
    `hint` / `device_seen`, nên mọi địa chỉ lưu được đều đưa vào tracker được.
    """
    return _check_ip(ip), _check_port(port)


def is_saveable(ip: str) -> bool:
    """Địa chỉ được lưu và tự thử lại không: hợp lệ theo `check_endpoint` và không phải Internet công khai.

    True cho RFC 1918, link-local, loopback, 100.64.0.0/10…; False cho địa chỉ công khai
    (`IPv4Address.is_global`) và giá trị sai. Node không tự gọi ra Internet (mvp N9).
    """
    try:
        return not ipaddress.IPv4Address(_check_ip(ip)).is_global
    except ValueError:
        return False


class LinkTracker:
    """Máy trạng thái giữ kết nối điều khiển của một node (sans-IO).

    Mọi phương thức kiểm tham số trước khi đổi trạng thái: sai → MessageError
    (`device_id`), ValueError / TypeError (còn lại), trạng thái giữ nguyên. `now` là
    thời gian monotonic (giây), không được giảm giữa các lời gọi. `device_id` của
    chính máy này bị bỏ qua (trả `[]`).

    Trong một lời gọi, hành động của mỗi thiết bị theo thứ tự `CloseConnection` /
    `CancelConnect`, rồi `Notify`, rồi `Connect`; lời gọi xét nhiều thiết bị duyệt
    theo `device_id` tăng dần.

    Tracker nhớ địa chỉ mDNS của mọi thiết bị đang thấy (cả chưa tin cậy, để thiết bị
    vừa ghép đôi mà đang thấy thì nối được ngay), và `hint` của mọi thiết bị được đưa
    (cả chưa tin cậy); bên gọi bảo đảm số thiết bị đang thấy / có `hint` có giới hạn. Địa
    chỉ đã lưu (`remember`) chỉ nhớ cho thiết bị đang tin cậy.
    """

    def __init__(self, own_device_id: str) -> None:
        self._own_id = validate_device_id(own_device_id)
        self._devices: dict[str, _Device] = {}
        self._next_attempt = 1
        self._last_now: float | None = None

    # ---- Truy vấn ------------------------------------------------------------------------

    def connected(self) -> dict[str, int]:
        """Bản sao: device_id → conn_id của kết nối hiện tại."""
        return {d: dev.current.conn_id for d, dev in self._devices.items() if dev.current is not None}

    def attempting(self) -> dict[str, int]:
        """Bản sao: device_id → attempt_id của lần thử đang chạy."""
        return {d: dev.attempt for d, dev in self._devices.items() if dev.attempt is not None}

    def next_wakeup(self) -> float | None:
        """Thời điểm sớm nhất trong các lần thử đã hẹn (gọi `tick` lúc đó); None nếu không có."""
        times = [dev.next_at for dev in self._devices.values() if dev.next_at is not None]
        return min(times) if times else None

    # ---- Sự kiện -------------------------------------------------------------------------

    def trusted_changed(self, device_ids: Iterable[str], now: float) -> list[LinkAction]:
        """Thay toàn bộ tập thiết bị tin cậy (`trusted.json` vừa đổi).

        Thiết bị thôi tin cậy: đóng kết nối (kèm `LinkDown`), hủy lần thử, quên lịch và
        các lỗi đã báo. Thiết bị mới tin cậy: xóa bộ đếm, đang thấy thì thử ngay.
        """
        if isinstance(device_ids, str | bytes):
            raise MessageError("tập tin cậy phải là một tập device_id, không phải một chuỗi")
        ids = {validate_device_id(d) for d in device_ids}
        now = self._check_now(now)
        ids.discard(self._own_id)
        self._last_now = now
        actions: list[LinkAction] = []
        old = {d for d, dev in self._devices.items() if dev.trusted}
        for device_id in sorted(old | ids):
            if device_id in old and device_id not in ids:
                actions.extend(self._untrust(device_id))
            elif device_id in ids and device_id not in old:
                dev = self._devices.setdefault(device_id, _Device())
                dev.trusted = True
                actions.extend(self._user_retry(device_id, dev, now))
        return actions

    def device_seen(
        self, device_id: str, addresses: Sequence[str], port: int, now: float
    ) -> list[LinkAction]:
        """mDNS thấy (hoặc thấy lại, đổi địa chỉ) thiết bị: nhớ địa chỉ, thử nếu đủ điều kiện."""
        validate_device_id(device_id)
        addrs = _check_addresses(addresses)
        port = _check_port(port)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.setdefault(device_id, _Device())
        dev.seen = (addrs, port)
        dev.stale = False
        if not dev.trusted:
            return []
        return self._event_retry(device_id, dev, now)

    def device_gone(self, device_id: str, now: float) -> list[LinkAction]:
        """mDNS báo thiết bị biến mất: ngừng thử lại; KHÔNG đóng kết nối, KHÔNG hủy lần thử.

        Đang `hold`: chỉ đánh dấu địa chỉ là cũ, lịch nối lại giữ nguyên. Còn `hint`: vẫn nhớ,
        nhưng chỉ thử khi có thao tác người dùng hay sự kiện (không theo lịch). Còn `saved` (và
        không có `hint`): hẹn thử nó sau `SAVED_GONE_GRACE` (`_saved_followup`).
        """
        dev = self._lookup(device_id, now)
        if dev is None:
            return []
        if dev.held and dev.trusted:
            if dev.seen is not None:
                dev.stale = True
            return []
        self._forget_seen(device_id, dev)
        if dev.trusted:
            self._saved_followup(dev, now, SAVED_GONE_GRACE)
        return []

    def hint(self, device_id: str, addresses: Sequence[str], port: int, now: float) -> list[LinkAction]:
        """Người dùng đưa địa chỉ của thiết bị: nhớ, gỡ chặn, xóa bộ đếm, thử ngay nếu đủ điều kiện.

        Thiết bị chưa tin cậy thì chỉ nhớ (thử khi nó được tin cậy). Kiểm tham số như
        `device_seen`. Lần thử do lời gọi này dùng địa chỉ/cổng `hint` (gộp với mDNS tươi
        nếu cùng cổng, xem docstring module); nó “không kết nối được” thì báo
        `LinkFailed(UNREACHABLE)` ngay, một lần, kể cả khi lịch §6.2 đang chạy.
        """
        validate_device_id(device_id)
        addrs = _check_addresses(addresses)
        port = _check_port(port)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.setdefault(device_id, _Device())
        dev.hint = (addrs, port)
        if not dev.trusted:
            return []
        dev.failures = 0
        dev.saved_failures = 0
        dev.blocked = False
        dev.reported.clear()
        if dev.eligible():
            dev.hint_next = True
            return [self._start(device_id, dev, now)]
        if dev.attempt is not None:
            # Lần thử đang chạy có thể nhắm địa chỉ cũ: thất bại thì thử lại sớm, tới địa chỉ `hint`.
            dev.dirty = True
            dev.hint_next = True
        return []

    def remember(self, device_id: str, ip: str, port: int, now: float) -> list[LinkAction]:
        """Địa chỉ đã quan sát được của thiết bị tin cậy (`app`: lúc khởi động từ `trusted.json`,
        hoặc vừa kết nối ra thành công tới đúng thiết bị).

        Kiểm `device_id` (MessageError), `check_endpoint` (ValueError), `now` (TypeError /
        ValueError); sai thì trạng thái giữ nguyên. Máy này, thiết bị không tin cậy hay địa chỉ
        Internet công khai (`is_saveable`) → `[]` và không nhớ. Nhớ đúng một địa chỉ (`saved`);
        địa chỉ khác địa chỉ cũ thì bắt đầu lại đợt. `hint` trùng đúng địa chỉ này (và không còn
        lần thử `hint` chờ chạy) thì bị bỏ: địa chỉ người dùng đưa đã thành địa chỉ đã lưu. Đang
        có lần thử chạy thì chỉ nhớ; không thì, nếu đích là `saved`, không bị chặn và (`held`
        hoặc đợt còn lượt), thử như một sự kiện (≥ `EVENT_RETRY_GAP`).
        """
        validate_device_id(device_id)
        ip, port = check_endpoint(ip, port)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.get(device_id)
        if dev is None or not dev.trusted or not is_saveable(ip):
            return []
        target: _Target = ((ip,), port)
        if dev.saved != target:
            dev.saved = target
            dev.saved_failures = 0
        if dev.hint == target and not dev.hint_next:
            dev.hint = None
        if dev.attempt is not None:
            return []
        if (
            dev.eligible()
            and dev.from_saved()
            and not dev.blocked
            and (dev.held or dev.saved_failures < SAVED_MAX_ATTEMPTS)
        ):
            return self._event_retry(device_id, dev, now)
        return []

    def hold(self, device_id: str, held: bool, now: float) -> list[LinkAction]:
        """Giữ (`held=True`) hay thả địa chỉ của thiết bị còn lượt truyền dở (protocol §6.1, §6.2).

        Giữ: mDNS báo biến mất thì không quên địa chỉ, lịch nối lại vẫn chạy. Lúc đổi từ thả sang
        giữ, thiết bị đủ điều kiện, không bị chặn và chưa có lịch (lần hẹn của lịch địa chỉ đã lưu
        không tính, kể cả khi đã hết đợt) thì thử như một sự kiện
        (≥ `EVENT_RETRY_GAP`); gọi lặp `hold(True)` không làm gì. Thả: địa chỉ đã cũ thì quên nó
        như `device_gone`; không còn mDNS tươi thì ngừng lịch §6.2, và nếu đích là địa chỉ đã lưu
        thì hẹn thử nó sau `SAVED_RETRY_BASE` (`_saved_followup`). Thiết bị lạ hay không tin cậy →
        `[]`. Chỉ có thể trả `Connect`, không bao giờ `CloseConnection` hay `Notify`.
        """
        if type(held) is not bool:
            raise TypeError("held phải là bool")
        dev = self._lookup(device_id, now)
        if dev is None or not dev.trusted:
            return []
        if held:
            was_held, dev.held = dev.held, True
            # Lần hẹn của lịch `saved` (tới SAVED_RETRY_MAX) không tính là “đã có lịch”: lượt truyền
            # mới không phải chờ nó; từ nay lịch §6.2 chạy. `hold` do app điều khiển, máy khác không bật được.
            scheduled = dev.next_at is not None and not dev.from_saved()
            if not was_held and not dev.blocked and dev.eligible() and not scheduled:
                return self._event_retry(device_id, dev, now)
            return []
        if dev.held:
            dev.held = False
            self._forget_seen(device_id, dev, stale_only=True)
            # Lịch §6.2 vừa dừng: còn địa chỉ đã lưu thì lịch `saved` chạy tiếp (hết đợt: `_saved_floor`).
            self._saved_followup(dev, now, SAVED_RETRY_BASE)
        return []

    def network_changed(self, now: float) -> list[LinkAction]:
        """Mạng đổi hoặc máy vừa thức dậy: thử ngay (theo giới hạn tốc độ) mọi thiết bị chưa nối."""
        now = self._check_now(now)
        self._last_now = now
        actions: list[LinkAction] = []
        for device_id in sorted(self._devices):
            dev = self._devices[device_id]
            if dev.trusted:
                dev.saved_failures = 0  # mạng đổi: đợt `saved` bắt đầu lại
                actions.extend(self._event_retry(device_id, dev, now))
        return actions

    def retry_now(self, device_id: str, now: float) -> list[LinkAction]:
        """Người dùng thao tác (ví dụ vừa ghép đôi lại): gỡ chặn, xóa bộ đếm, thử ngay."""
        dev = self._lookup(device_id, now)
        if dev is None or not dev.trusted:
            return []
        return self._user_retry(device_id, dev, now)

    def connect_finished(
        self, device_id: str, attempt_id: int, result: ConnectResult, conn_id: int | None, now: float
    ) -> list[LinkAction]:
        """Kết quả lần thử `attempt_id`; `conn_id` (do `app` cấp) chỉ có khi `OK`."""
        validate_device_id(device_id)
        _check_id_number("attempt_id", attempt_id)
        result = ConnectResult(result)
        if result is ConnectResult.OK:
            if conn_id is None:
                raise ValueError("kết quả OK phải có conn_id")
            self._check_new_conn_id(conn_id)
        elif conn_id is not None:
            raise ValueError("chỉ kết quả OK mới có conn_id")
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.get(device_id)
        if dev is None or dev.attempt != attempt_id:
            # Lần thử cũ, đã hủy, hoặc thiết bị đã thôi tin cậy: kết nối hoàn tất muộn bị đóng.
            return [CloseConnection(device_id, conn_id)] if conn_id is not None else []
        dev.attempt = None
        from_hint = dev.hint_attempt == attempt_id
        from_saved = dev.saved_attempt == attempt_id
        target = dev.attempt_target
        dev.hint_attempt = dev.saved_attempt = dev.attempt_target = None
        if result is ConnectResult.OK:
            assert conn_id is not None
            self._reset_failures(dev)
            dev.dirty = False
            if not dev.trusted:
                return [CloseConnection(device_id, conn_id)]
            return self._add_connection(device_id, dev, conn_id, True, now)
        if from_saved:
            handled = self._saved_failed(dev, result, now)
            if handled is not None:
                return handled
        return self._failed(device_id, dev, result, now, from_hint=from_hint, target=target)

    def incoming_control(self, device_id: str, conn_id: int, now: float) -> list[LinkAction]:
        """Máy kia vừa mở kết nối điều khiển tới máy này (đã qua `control_open`)."""
        validate_device_id(device_id)
        self._check_new_conn_id(conn_id)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.get(device_id)
        if dev is None or not dev.trusted:
            return [CloseConnection(device_id, conn_id)]  # phòng thủ: Listener đã chặn
        return self._add_connection(device_id, dev, conn_id, False, now)

    def connection_lost(self, device_id: str, conn_id: int, now: float) -> list[LinkAction]:
        """Kết nối `conn_id` đã đóng; là kết nối hiện tại thì báo `LinkDown` và hẹn thử lại."""
        validate_device_id(device_id)
        _check_id_number("conn_id", conn_id)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return []
        dev = self._devices.get(device_id)
        if dev is None or dev.current is None or dev.current.conn_id != conn_id:
            return []
        dev.current = None
        dev.saved_failures = 0  # mất kết nối hiện tại: đợt `saved` bắt đầu lại
        if dev.trusted and dev.scheduled() and not dev.blocked:
            dev.next_at = now + _delay(max(dev.failures, 1))
        else:
            self._saved_followup(dev, now, SAVED_RETRY_BASE)
        return [Notify(LinkDown(device_id, conn_id))]

    def tick(self, now: float) -> list[LinkAction]:
        """Hẹn giờ: bắt đầu các lần thử đã tới hạn (`next_wakeup`)."""
        now = self._check_now(now)
        self._last_now = now
        actions: list[LinkAction] = []
        for device_id in sorted(self._devices):
            dev = self._devices[device_id]
            if dev.next_at is not None and dev.next_at <= now:
                dev.next_at = None
                if dev.eligible():
                    actions.append(self._start(device_id, dev, now))
        return actions

    # ---- Nội bộ --------------------------------------------------------------------------

    def _check_now(self, now: object) -> float:
        if isinstance(now, bool) or not isinstance(now, int | float):
            raise TypeError("now phải là số giây (đồng hồ monotonic)")
        if not is_finite(now):
            raise ValueError("now phải là số hữu hạn")
        if self._last_now is not None and now < self._last_now:
            raise ValueError("now không được giảm")
        return float(now)

    def _check_new_conn_id(self, conn_id: object) -> int:
        conn_id = _check_id_number("conn_id", conn_id)
        for dev in self._devices.values():
            if dev.current is not None and dev.current.conn_id == conn_id:
                raise ValueError(f"conn_id {conn_id} đang là kết nối hiện tại của một thiết bị")
        return conn_id

    def _lookup(self, device_id: str, now: float) -> _Device | None:
        """Kiểm tham số chung (`device_id`, `now`); trả mục của thiết bị (None: máy này / chưa biết)."""
        validate_device_id(device_id)
        now = self._check_now(now)
        self._last_now = now
        if device_id == self._own_id:
            return None
        return self._devices.get(device_id)

    def _start(self, device_id: str, dev: _Device, now: float) -> Connect:
        """Bắt đầu một lần thử tới `dev.target()`, hoặc `dev.hint_target()` khi `hint_next`."""
        from_hint = dev.hint_next
        target = dev.hint_target() if from_hint else None
        dev.hint_next = False
        from_saved = False
        if target is None:
            from_saved = dev.from_saved()
            target = dev.target()
        assert target is not None
        attempt_id = self._next_attempt
        self._next_attempt += 1
        dev.attempt = attempt_id
        dev.attempt_target = target
        dev.hint_attempt = attempt_id if from_hint else None
        dev.saved_attempt = attempt_id if from_saved else None
        if from_saved:
            dev.saved_last = now
        dev.last_start = now
        dev.next_at = None
        dev.dirty = False
        addresses, port = target
        return Connect(device_id, attempt_id, addresses, port)

    @staticmethod
    def _reset_failures(dev: _Device) -> None:
        dev.failures = 0
        dev.saved_failures = 0
        dev.blocked = False
        dev.reported.clear()
        dev.next_at = None

    def _event_retry(self, device_id: str, dev: _Device, now: float) -> list[LinkAction]:
        """Thử do sự kiện (mDNS, mạng đổi), có giới hạn tốc độ."""
        if dev.eligible():
            if dev.last_start is None:
                earliest = now
            elif dev.blocked:
                # Theo lịch tính từ lần thử trước, nhưng không sớm hơn EVENT_RETRY_GAP.
                earliest = dev.last_start + max(EVENT_RETRY_GAP, _delay(dev.failures))
            else:
                earliest = dev.last_start + EVENT_RETRY_GAP
            earliest = self._saved_floor(dev, earliest)
            if now >= earliest:
                return [self._start(device_id, dev, now)]
            dev.next_at = earliest if dev.next_at is None else min(dev.next_at, earliest)
        elif dev.attempt is not None and dev.target() is not None:
            dev.dirty = True
        return []

    def _user_retry(self, device_id: str, dev: _Device, now: float) -> list[LinkAction]:
        """Thử do người dùng hoặc vì vừa được tin cậy: gỡ chặn, không xét khoảng cách."""
        dev.failures = 0
        dev.saved_failures = 0
        dev.blocked = False
        dev.reported.clear()
        if dev.eligible():
            return [self._start(device_id, dev, now)]
        return []

    def _failed(
        self,
        device_id: str,
        dev: _Device,
        result: ConnectResult,
        now: float,
        *,
        from_hint: bool,
        target: _Target | None,
    ) -> list[LinkAction]:
        """Lần thử hiện tại thất bại (`dev.attempt` đã được xóa); `from_hint`: lần thử do `hint()` gây
        ra, `target`: đích của lần thử."""
        if dev.current is not None:
            # Máy kia đã nối tới trong lúc thử: không tính là thất bại.
            dev.dirty = False
            dev.hint_next = False
            return []
        dev.failures += 1
        actions: list[LinkAction] = []
        if from_hint and target is not None:
            failed = LinkFailed(device_id, result, True, target[0], target[1])
        else:
            failed = LinkFailed(device_id, result)
        # Địa chỉ người dùng đưa sai (không tới được, hay là máy khác) không được che địa chỉ đã lưu:
        # quên `hint` (trừ khi người dùng vừa đưa `hint` mới trong lúc thử), lịch `saved` chạy tiếp.
        # `hint` trùng `saved` cũng bị quên: không thì nó đứng trước `saved` và lịch `saved` không chạy.
        drop_hint = (
            from_hint
            and not dev.hint_next
            and result in (ConnectResult.UNREACHABLE, ConnectResult.IDENTITY_MISMATCH)
            and dev.saved is not None
        )
        same_as_saved = drop_hint and dev.hint == dev.saved
        if drop_hint:
            dev.hint = None
        if drop_hint and result is ConnectResult.IDENTITY_MISMATCH:
            # Không chặn: lỗi thuộc địa chỉ vừa nhập, không thuộc thiết bị (nó vẫn có thể ở `saved`).
            # Địa chỉ vừa nhập chính là `saved` thì `saved` giờ là của máy khác: quên nó trong phiên.
            if same_as_saved:
                dev.saved = None
                dev.saved_failures = 0
            dev.reported.add(result)
            actions.append(Notify(failed))
            if dev.dirty and dev.last_start is not None and dev.target() is not None:
                dev.next_at = self._saved_floor(dev, max(now, dev.last_start + EVENT_RETRY_GAP))
            elif dev.scheduled():
                dev.next_at = now + _delay(max(dev.failures, 1))
            dev.dirty = False
            self._saved_followup(dev, now, SAVED_RETRY_BASE)
            return actions
        if result is ConnectResult.UNREACHABLE:
            dev.blocked = False
            scheduled = dev.scheduled()
            if scheduled:
                dev.next_at = now + _delay(dev.failures)
                if dev.dirty and dev.last_start is not None:
                    dev.next_at = min(dev.next_at, max(now, dev.last_start + EVENT_RETRY_GAP))
            elif dev.dirty and dev.last_start is not None and dev.target() is not None:
                # Chỉ có `hint`: không theo lịch, nhưng sự kiện tới trong lúc thử vẫn được thử lại.
                dev.next_at = max(now, dev.last_start + EVENT_RETRY_GAP)
            # Lần thử do `hint()` gây ra (mỗi lần gọi `hint` gây ra tối đa một lần thử): luôn báo
            # ngay cho người dùng vừa đưa địa chỉ, có lịch hay không, kể cả khi đã báo cho lần
            # `hint` trước. Còn lại: chỉ báo sau UNREACHABLE_REPORT_AFTER lần thất bại liên tiếp
            # khi lịch chạy, và chỉ một lần.
            due = scheduled and dev.failures >= UNREACHABLE_REPORT_AFTER and result not in dev.reported
            if from_hint or due:
                dev.reported.add(result)
                actions.append(Notify(failed))
            dev.dirty = False
            # Không còn lịch nào khác (ví dụ mDNS báo máy đi trong lúc thử): thử địa chỉ đã lưu.
            self._saved_followup(dev, now, SAVED_RETRY_BASE)
            return actions
        assert result in _BLOCKING
        dev.blocked = True
        if result is ConnectResult.REJECTED and dev.held and dev.trusted and dev.scheduled():
            # Còn lượt truyền dở: lỗi tạm (máy kia đang khởi động lại, mạng chập) trông giống bị
            # từ chối, nên vẫn thử lại theo lịch, không sớm hơn EVENT_RETRY_GAP (trần RETRY_MAX).
            dev.next_at = now + max(EVENT_RETRY_GAP, _delay(dev.failures))
        else:
            dev.next_at = None
        # Lỗi chặn của lần thử do `hint()` gây ra luôn được báo: người dùng đang chờ kết quả.
        if from_hint or result not in dev.reported:
            dev.reported.add(result)
            actions.append(Notify(failed))
        if dev.dirty:
            dev.dirty = False
            actions.extend(self._event_retry(device_id, dev, now))
        return actions

    def _saved_failed(self, dev: _Device, result: ConnectResult, now: float) -> list[LinkAction] | None:
        """Lần thử nhắm vào `saved` thất bại (`dev.attempt` đã được xóa).

        Trả None khi lần thử được xử lý như mọi lần thử (`_failed`): máy kia đã nối tới, bị từ
        chối / khác phiên bản, hay “không kết nối được” khi đang `held` (lịch §6.2).
        """
        if dev.current is not None:
            return None
        if result is ConnectResult.IDENTITY_MISMATCH:
            # IP đã lưu giờ là của máy khác (đổi chủ): quên trong phiên, không báo, không chặn,
            # không tăng bộ đếm §6.2; `trusted.json` không bị sửa (app không biết lần này).
            dev.saved = None
            dev.saved_failures = 0
            if (dev.hint_next or dev.dirty) and dev.last_start is not None:
                dev.next_at = max(now, dev.last_start + EVENT_RETRY_GAP)
            elif dev.scheduled():
                dev.next_at = now + _delay(max(dev.failures, 1))
            else:
                dev.next_at = None
            dev.dirty = False
            return []
        if result is not ConnectResult.UNREACHABLE or dev.held:
            return None
        dev.saved_failures += 1
        if (dev.dirty or dev.hint_next) and dev.last_start is not None:
            dev.next_at = self._saved_floor(dev, max(now, dev.last_start + EVENT_RETRY_GAP))
        elif dev.saved_failures < SAVED_MAX_ATTEMPTS:
            exponent = min(dev.saved_failures - 1, _MAX_DELAY_EXPONENT)
            dev.next_at = now + min(SAVED_RETRY_BASE * 2**exponent, SAVED_RETRY_MAX)
        else:
            dev.next_at = now + SAVED_RETRY_MAX  # hết đợt: một lần mỗi SAVED_RETRY_MAX
        dev.dirty = False
        return []

    @staticmethod
    def _saved_floor(dev: _Device, at: float) -> float:
        """Hết đợt `saved` (không `held`): lần thử tới `saved` không sớm hơn lần trước + SAVED_RETRY_MAX."""
        if (
            dev.from_saved()
            and not dev.held
            and dev.saved_failures >= SAVED_MAX_ATTEMPTS
            and dev.saved_last is not None
        ):
            return max(at, dev.saved_last + SAVED_RETRY_MAX)
        return at

    def _saved_followup(self, dev: _Device, now: float, delay: float) -> None:
        """Hẹn thử `saved` sau `delay` khi không còn lịch nào khác (mDNS báo máy đi, mất kết nối…).

        Chỉ khi tin cậy, không bị chặn, không `held`, chưa kết nối, không đang thử, chưa hẹn, và
        đích là `saved`. Cách lần thử trước ≥ `EVENT_RETRY_GAP`; hết đợt thì theo `_saved_floor`.
        """
        if (
            not dev.trusted
            or dev.blocked
            or dev.held
            or dev.current is not None
            or dev.attempt is not None
            or dev.next_at is not None
            or not dev.from_saved()
        ):
            return
        at = now + delay
        if dev.last_start is not None:
            at = max(at, dev.last_start + EVENT_RETRY_GAP)
        dev.next_at = self._saved_floor(dev, at)

    def _add_connection(
        self, device_id: str, dev: _Device, conn_id: int, local: bool, now: float
    ) -> list[LinkAction]:
        """Một kết nối mới đã sống (ra hoặc vào); áp luật chống trùng nếu đã có kết nối."""
        old = dev.current
        dev.hint_next = False
        if old is None:
            dev.current = _Conn(conn_id, now, local)
            self._reset_failures(dev)
            return [Notify(LinkUp(device_id, conn_id, local))]
        if now - old.since >= REPLACE_AFTER or old.local == local:
            keep_new = True
        else:
            # Hai bên gọi nhau cùng lúc: giữ kết nối do bên có device_id nhỏ hơn mở.
            keep_local = self._own_id < device_id
            keep_new = local == keep_local
        if keep_new:
            dev.current = _Conn(conn_id, now, local)
            return [
                CloseConnection(device_id, old.conn_id),
                Notify(LinkSwitched(device_id, old.conn_id, conn_id, local)),
            ]
        return [CloseConnection(device_id, conn_id)]

    def _forget_seen(self, device_id: str, dev: _Device, *, stale_only: bool = False) -> None:
        """Quên địa chỉ mDNS (`stale_only`: chỉ khi nó đã cũ); lịch §6.2 hết chạy thì dừng nó."""
        if not stale_only or dev.stale:
            dev.seen = None
            dev.stale = False
        if not dev.scheduled() and not dev.hint_next:
            # Còn `hint_next`: lần thử tới `hint` (đã hẹn, hoặc sau khi lần đang chạy thất bại)
            # là do người dùng, không phải lịch §6.2, nên giữ `next_at` và `dirty` cho nó.
            dev.next_at = None
            dev.dirty = False
        if not dev.trusted and dev.hint is None:
            del self._devices[device_id]

    def _untrust(self, device_id: str) -> list[LinkAction]:
        """Thiết bị thôi tin cậy: đóng kết nối, hủy lần thử, quên mọi thứ trừ địa chỉ mDNS tươi.

        `hint`, `saved`, `held` và địa chỉ mDNS cũ (`stale`) cũng bị quên.
        """
        dev = self._devices[device_id]
        actions: list[LinkAction] = []
        notify: list[LinkAction] = []
        if dev.current is not None:
            actions.append(CloseConnection(device_id, dev.current.conn_id))
            notify.append(Notify(LinkDown(device_id, dev.current.conn_id)))
        if dev.attempt is not None:
            actions.append(CancelConnect(device_id, dev.attempt))
        fresh = dev.fresh()
        if fresh is not None:
            self._devices[device_id] = _Device(seen=fresh)
        else:
            del self._devices[device_id]
        return actions + notify
