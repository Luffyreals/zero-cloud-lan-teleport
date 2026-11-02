"""Cửa nhận kết nối của cổng chung (sans-IO): giới hạn số kết nối đang mở đầu và tốc độ bắt tay.

Đặc tả ở docs/protocol.md mục 2.3. Module không mở socket, không xem đồng hồ: `net`
(`Listener`) đưa IP của máy kia cùng thời gian monotonic `now` vào `AdmissionGate`
rồi chỉ thực thi quyết định (từ chối = `transport.abort()` trước `start_tls`).

Vòng đời một kết nối vào:

1. `admit(ip, now)` ngay khi nhận TCP, trước mọi `await` → `Ticket` (nhận) hoặc
   `Refusal` (lý do từ chối). Thứ tự kiểm: chọn pool → số kết nối đang mở đầu (theo
   IP, rồi tổng, của pool đó) → bucket token theo IP → bucket tổng. Chỉ trừ token khi
   qua mọi bước; bị từ chối ở bước nào thì không trừ gì, nên một IP đập liên tục không
   làm cạn ngân sách chung.
2. Bắt tay TLS xong: client không gửi chứng chỉ → `anonymous(ticket, now)` (False: vượt
   giới hạn kết nối ẩn danh, dùng chung hai pool); client gửi chứng chỉ đã được context
   tin cậy chấp nhận → `trusted(ticket, now)` hoàn token đã trừ, vì chỉ bắt tay hỏng
   hoặc ẩn danh mới tiêu ngân sách (máy không có khóa riêng không bắt tay xong được nên
   không bao giờ được hoàn).
3. `finish(ticket, now)` khi biết loại kết nối hoặc khi kết nối kết thúc (gọi lại không sao).

Hai pool: `GENERAL` cho IP lạ, `PRIORITY` cho IP đã chứng minh bằng mTLS — có kết nối
điều khiển sống (vào, đã qua kiểm `is_trusted`; hoặc ra, chứng chỉ server đã được kiểm
trong bắt tay), báo bằng `control_opened` / `control_closed`, hoặc kết nối cuối mới đóng
chưa quá `PRIORITY_TTL`. IP ưu tiên chỉ dùng pool ưu tiên (đầy thì không rơi về pool
chung), nên kẻ lạ làm đầy pool chung không chặn được máy đã ghép đôi. Không bao giờ cấp
ưu tiên theo địa chỉ mDNS (mDNS không xác thực). `retain_trusted` bỏ ưu tiên của thiết
bị vừa hủy ghép đôi, kể cả khi kết nối của nó còn sống. TTL tính theo `now` monotonic:
trên Linux/macOS thời gian máy ngủ không được tính.

Ngân sách lỗi và hạ ưu tiên: mTLS chứng minh *thiết bị*, không chứng minh *IP* — kẻ lạ
relay nguyên byte tới một máy tin cậy là có ưu tiên cho IP của mình. Vì vậy mỗi IP ưu
tiên có một ngân sách lỗi (`PRIORITY_STRIKES` lần, hồi 1 lần mỗi `STRIKE_REFILL` giây;
một kết nối điều khiển của IP đó đóng sau khi đã sống ít nhất `STRIKE_CREDIT_AFTER` giây
thì cộng lại 1). Không cộng theo từng lần bắt tay tin cậy: kẻ relay cắt kết nối là máy
tin cậy nối lại qua nó sau 1 s, nên kẻ đó sẽ tự nạp lại được. Vé pool ưu tiên kết thúc
mà chưa `trusted` (TCP trần, bắt tay hỏng, hết giờ, ẩn danh, lần thử thua bị client
hủy) trừ 1; hết ngân sách
thì IP đó bị hạ tới `now + PRIORITY_TTL`: mất luôn handle sống và mốc đóng của nó,
`control_opened` trong thời gian này không cấp gì (trả 0), kết nối mới vào pool chung.
Hết hạn thì chỉ một `control_opened` mới mới cấp lại ưu tiên (ngân sách lại đầy).

Bộ nhớ có trần: bảng bucket của pool chung chỉ thêm mục khi nhận, bỏ mục đã đầy lại mà
không có vé sống, tối đa `MAX_TRACKED_IPS` mục; bảng ưu tiên tối đa `MAX_PRIORITY_IPS`
(đầy thì bỏ mục hết hiệu lực, rồi mục không còn kết nối sống và đóng lâu nhất). Việc dọn
chỗ khi bảng đầy không bao giờ bỏ mục đang có vé sống hoặc kết nối điều khiển sống; bảng
ưu tiên đầy mà mục nào cũng còn như vậy thì IP mới không được ưu tiên (`control_opened`
trả 0). Hủy ghép đôi và hạ ưu tiên thì vẫn bỏ ưu tiên dù kết nối còn sống. Bảng IP bị hạ tối đa
`MAX_DEMOTED_IPS` (đầy thì bỏ mục hết hạn sớm nhất).
"""

from __future__ import annotations

import ipaddress
import logging
import math
import re
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from teleport.core.numbers import is_finite

# Đọc lúc dùng để test chỉnh được bằng monkeypatch (protocol §2.3). Tốc độ tính bằng
# lần bắt tay mỗi giây, burst bằng số lần.
MAX_OPENING_PER_IP = 4  # pool chung: kết nối đang mở đầu (chưa biết loại) mỗi IP
MAX_OPENING_TOTAL = 64  # pool chung: tổng
MAX_ANONYMOUS_PER_IP = 1  # ẩn danh chưa vào phiên, mỗi IP (dùng chung hai pool; protocol §5.3)
MAX_ANONYMOUS_TOTAL = 8  # ẩn danh, tổng
HANDSHAKE_RATE_PER_IP = 1.0  # pool chung: bucket theo IP
HANDSHAKE_BURST_PER_IP = 2
HANDSHAKE_RATE_TOTAL = 4.0  # pool chung: bucket tổng
HANDSHAKE_BURST_TOTAL = 4
PRIORITY_OPENING_PER_IP = 4  # pool ưu tiên: kết nối đang mở đầu mỗi IP
PRIORITY_OPENING_TOTAL = 16  # pool ưu tiên: tổng
PRIORITY_RATE_PER_IP = 2.0  # pool ưu tiên: bucket theo IP
PRIORITY_BURST_PER_IP = 4
PRIORITY_RATE_TOTAL = 4.0  # pool ưu tiên: bucket tổng
PRIORITY_BURST_TOTAL = 4
PRIORITY_TTL = 24 * 3600.0  # giữ ưu tiên 24 h sau khi kết nối cuối đóng
MAX_TRACKED_IPS = 4096  # số IP tối đa trong bảng bucket của pool chung
MAX_PRIORITY_IPS = 256  # số IP ưu tiên tối đa
MAX_DEMOTED_IPS = 1024  # số IP bị hạ ưu tiên tối đa
PRIORITY_STRIKES = 4  # số lần lỗi được tha cho mỗi IP ưu tiên trước khi hạ
STRIKE_REFILL = 600.0  # số giây để hồi 1 lần lỗi (> 0)
STRIKE_CREDIT_AFTER = 60.0  # kết nối điều khiển sống ≥ chừng này giây: lúc đóng cộng lại 1

_MAX_FINGERPRINTS_PER_IP = 64  # mốc đóng giữ cho một IP (nhiều máy sau một NAT)
_PRUNE_STEP = 4  # số mục đầu bảng xét bỏ mỗi lần `admit`
_FINGERPRINT_RE = re.compile(r"[0-9a-f]{64}")

log = logging.getLogger(__name__)


class Pool(StrEnum):
    GENERAL = "general"  # IP lạ
    PRIORITY = "priority"  # IP đã chứng minh bằng mTLS


class Refusal(StrEnum):
    """Lý do `admit` từ chối, theo thứ tự kiểm."""

    OPENING_PER_IP = "opening_per_ip"  # IP này đã đủ kết nối đang mở đầu trong pool của nó
    OPENING_TOTAL = "opening_total"  # pool đã đủ kết nối đang mở đầu (hoặc bảng IP đầy)
    RATE_PER_IP = "rate_per_ip"  # bucket theo IP hết token
    RATE_TOTAL = "rate_total"  # bucket tổng của pool hết token


@dataclass(frozen=True, slots=True)
class Ticket:
    """Vé của một kết nối đã được nhận; `ip` đã chuẩn hóa (IPv4-mapped IPv6 → IPv4)."""

    id: int
    ip: str
    pool: Pool


@dataclass(slots=True)
class _Bucket:
    """Bucket token; `tokens` đúng tại `stamp`, nạp lại tuyến tính tới `burst`."""

    tokens: float
    stamp: float

    def available(self, now: float, rate: float, burst: float) -> float:
        elapsed = now - self.stamp
        refill = elapsed * rate if elapsed > 0 else 0.0
        return min(float(burst), self.tokens + refill)

    def take(self, now: float, rate: float, burst: float) -> None:
        self.tokens = self.available(now, rate, burst) - 1
        self.stamp = now

    def give_back(self, now: float, rate: float, burst: float) -> None:
        self.tokens = min(float(burst), self.available(now, rate, burst) + 1)
        self.stamp = now


@dataclass(slots=True)
class _Entry:
    """Một IP của pool chung."""

    bucket: _Bucket
    opening: int = 0  # vé sống của pool chung từ IP này


@dataclass(slots=True)
class _Priority:
    """Một IP ưu tiên."""

    bucket: _Bucket
    strikes: _Bucket  # ngân sách lỗi: trần PRIORITY_STRIKES, hồi 1 mỗi STRIKE_REFILL giây
    opening: int = 0  # vé sống của pool ưu tiên từ IP này
    handles: dict[int, str] = field(default_factory=dict)  # kết nối điều khiển sống → fingerprint
    closed: dict[str, float] = field(default_factory=dict)  # fingerprint → lúc đóng, tăng dần

    def active(self, now: float) -> bool:
        if self.handles:
            return True
        if not self.closed:
            return False
        return now - next(reversed(self.closed.values())) < PRIORITY_TTL

    def last_closed(self) -> float:
        return next(reversed(self.closed.values())) if self.closed else -math.inf


def _strike_rate() -> float:
    """Tốc độ hồi ngân sách lỗi (lần mỗi giây); `STRIKE_REFILL` ≤ 0 nghĩa là hồi ngay."""
    return 1.0 / STRIKE_REFILL if STRIKE_REFILL > 0 else math.inf


@dataclass(slots=True)
class _Live:
    """Trạng thái của một vé chưa `finish`."""

    ticket: Ticket
    anonymous: bool = False
    refunded: bool = False


def _normalize_ip(ip: object) -> str:
    """IP dạng chuẩn để tra bảng; IPv4-mapped IPv6 → IPv4. Sai → ValueError."""
    if not isinstance(ip, str):
        raise ValueError("ip phải là chuỗi địa chỉ IP")
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError as e:
        raise ValueError(f"ip không hợp lệ: {ip!r:.80}") from e
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped)
    return str(addr)


def _check_ticket(ticket: object) -> Ticket:
    if not isinstance(ticket, Ticket):
        raise TypeError("ticket phải là Ticket")
    return ticket


def _check_fingerprint(fp: object) -> str:
    if not isinstance(fp, str) or not _FINGERPRINT_RE.fullmatch(fp):
        raise ValueError("fingerprint phải là đúng 64 ký tự hex thường")
    return fp


class AdmissionGate:
    """Quyết định nhận hay từ chối từng kết nối vào; xem docstring của module.

    Mọi hàm nhận `now` (giây, monotonic): không phải số → TypeError; NaN, vô hạn hoặc
    nhỏ hơn lần gọi trước → ValueError. Tham số sai thì trạng thái không đổi.
    """

    def __init__(self) -> None:
        self._last_now: float | None = None
        self._next_ticket = 1
        self._next_handle = 1
        self._live: dict[int, _Live] = {}
        self._entries: OrderedDict[str, _Entry] = OrderedDict()  # pool chung, dùng lâu nhất đứng đầu
        self._priority: dict[str, _Priority] = {}
        self._handles: dict[int, tuple[str, float]] = {}  # handle sống → (IP, lúc mở)
        self._demoted: dict[str, float] = {}  # IP bị hạ ưu tiên → hết hạn lúc (`now`)
        self._opening = {Pool.GENERAL: 0, Pool.PRIORITY: 0}
        self._total: dict[Pool, _Bucket] = {}  # bucket tổng của mỗi pool, tạo đầy ở lần dùng đầu
        self._anonymous: dict[str, int] = {}  # IP → số vé ẩn danh sống
        self._anonymous_total = 0
        self._refusals = dict.fromkeys(Refusal, 0)

    # ---- Thuộc tính ------------------------------------------------------------------------

    @property
    def opening_count(self) -> int:
        """Số vé sống (kết nối đang mở đầu, cả hai pool)."""
        return len(self._live)

    @property
    def anonymous_count(self) -> int:
        """Số vé sống đã được nhận là ẩn danh."""
        return self._anonymous_total

    @property
    def refusals(self) -> dict[Refusal, int]:
        """Số lần từ chối theo lý do (bản sao, đủ mọi lý do)."""
        return dict(self._refusals)

    @property
    def tracked_ips(self) -> int:
        """Số IP trong bảng bucket của pool chung (≤ MAX_TRACKED_IPS)."""
        return len(self._entries)

    @property
    def demoted_ips(self) -> int:
        """Số IP trong bảng hạ ưu tiên (≤ MAX_DEMOTED_IPS; có thể gồm mục hết hạn chưa dọn)."""
        return len(self._demoted)

    # ---- Vé --------------------------------------------------------------------------------

    def admit(self, ip: str, now: float) -> Ticket | Refusal:
        """Nhận hay từ chối một kết nối TCP mới từ `ip`; xem thứ tự kiểm ở docstring module.

        `ip` không phải địa chỉ IP → ValueError. Bảng pool chung đầy mà không bỏ được mục
        nào (mục nào cũng có vé sống) → `Refusal.OPENING_TOTAL`.
        """
        ip = _normalize_ip(ip)
        now = self._advance(now)
        self._prune(now)
        record = self._active_priority(ip, now)
        entry: _Entry | None = None
        bucket: _Bucket | None
        if record is not None:
            pool = Pool.PRIORITY
            opening = record.opening
            per_ip_limit, total_limit = PRIORITY_OPENING_PER_IP, PRIORITY_OPENING_TOTAL
            bucket = record.bucket
            rate, burst = PRIORITY_RATE_PER_IP, PRIORITY_BURST_PER_IP
            total_rate, total_burst = PRIORITY_RATE_TOTAL, PRIORITY_BURST_TOTAL
        else:
            pool = Pool.GENERAL
            entry = self._entries.get(ip)
            opening = 0 if entry is None else entry.opening
            per_ip_limit, total_limit = MAX_OPENING_PER_IP, MAX_OPENING_TOTAL
            bucket = None if entry is None else entry.bucket
            rate, burst = HANDSHAKE_RATE_PER_IP, HANDSHAKE_BURST_PER_IP
            total_rate, total_burst = HANDSHAKE_RATE_TOTAL, HANDSHAKE_BURST_TOTAL

        if opening >= per_ip_limit:
            return self._refuse(Refusal.OPENING_PER_IP)
        if self._opening[pool] >= total_limit:
            return self._refuse(Refusal.OPENING_TOTAL)
        available = float(burst) if bucket is None else bucket.available(now, rate, burst)
        if available < 1:
            return self._refuse(Refusal.RATE_PER_IP)
        total = self._total.get(pool) or _Bucket(float(total_burst), now)
        if total.available(now, total_rate, total_burst) < 1:
            return self._refuse(Refusal.RATE_TOTAL)
        if pool is Pool.GENERAL and entry is None:
            if not self._make_room():
                return self._refuse(Refusal.OPENING_TOTAL)
            entry = _Entry(_Bucket(float(burst), now))
            self._entries[ip] = entry

        # Qua mọi bước: trừ token, giữ chỗ.
        total.take(now, total_rate, total_burst)
        self._total[pool] = total
        if record is not None:
            record.bucket.take(now, rate, burst)
            record.opening += 1
        else:
            assert entry is not None
            entry.bucket.take(now, rate, burst)
            entry.opening += 1
            self._entries.move_to_end(ip)
        self._opening[pool] += 1
        ticket = Ticket(self._next_ticket, ip, pool)
        self._next_ticket += 1
        self._live[ticket.id] = _Live(ticket)
        return ticket

    def anonymous(self, ticket: Ticket, now: float) -> bool:
        """Bắt tay xong mà client không gửi chứng chỉ: còn chỗ ẩn danh thì giữ chỗ, trả True.

        False: vượt `MAX_ANONYMOUS_PER_IP` / `MAX_ANONYMOUS_TOTAL` (vé vẫn phải `finish`),
        hoặc vé đã `finish`, không do gate này cấp, hay đã `trusted`. Gọi lại trên vé đã
        được nhận là ẩn danh → True, không đếm thêm.
        """
        _check_ticket(ticket)
        self._advance(now)
        live = self._live.get(ticket.id)
        if live is None or live.ticket != ticket or live.refunded:
            return False
        if live.anonymous:
            return True
        ip = ticket.ip
        if self._anonymous.get(ip, 0) >= MAX_ANONYMOUS_PER_IP or self._anonymous_total >= MAX_ANONYMOUS_TOTAL:
            return False
        live.anonymous = True
        self._anonymous[ip] = self._anonymous.get(ip, 0) + 1
        self._anonymous_total += 1
        return True

    def trusted(self, ticket: Ticket, now: float) -> None:
        """Bắt tay xong với chứng chỉ client đã tin cậy: hoàn token đã trừ cho vé này.

        Hoàn 1 token vào bucket theo IP và bucket tổng của pool trên vé (không vượt burst);
        không đổi ngân sách lỗi. Một lần mỗi vé; vé ẩn danh, vé đã `finish` hay không do
        gate này cấp: không làm gì.
        """
        _check_ticket(ticket)
        now = self._advance(now)
        live = self._live.get(ticket.id)
        if live is None or live.ticket != ticket or live.refunded or live.anonymous:
            return
        live.refunded = True
        total = self._total[ticket.pool]  # có từ lúc cấp vé
        if ticket.pool is Pool.PRIORITY:
            total.give_back(now, PRIORITY_RATE_TOTAL, PRIORITY_BURST_TOTAL)
            record = self._priority.get(ticket.ip)
            if record is not None:  # luôn còn: không bỏ mục có vé sống
                record.bucket.give_back(now, PRIORITY_RATE_PER_IP, PRIORITY_BURST_PER_IP)
        else:
            total.give_back(now, HANDSHAKE_RATE_TOTAL, HANDSHAKE_BURST_TOTAL)
            entry = self._entries.get(ticket.ip)
            if entry is not None:  # luôn còn: không bỏ mục có vé sống
                entry.bucket.give_back(now, HANDSHAKE_RATE_PER_IP, HANDSHAKE_BURST_PER_IP)

    def finish(self, ticket: Ticket, now: float) -> None:
        """Trả chỗ của vé (đang mở đầu, ẩn danh). Gọi lại, hay vé lạ: không làm gì.

        Vé pool ưu tiên chưa được `trusted` mà IP vẫn đang ưu tiên → trừ 1 vào ngân sách
        lỗi, hết ngân sách thì hạ ưu tiên IP đó (docstring module). IP đã mất ưu tiên
        (hủy ghép đôi, hết TTL, đã bị hạ) thì không làm gì thêm.
        `now` được kiểm như mọi hàm khác, kể cả khi vé lạ hay đã `finish`.
        """
        _check_ticket(ticket)
        now = self._advance(now)
        live = self._live.get(ticket.id)
        if live is None or live.ticket != ticket:
            return
        del self._live[ticket.id]
        ip = ticket.ip
        self._opening[ticket.pool] -= 1
        if ticket.pool is Pool.PRIORITY:
            record = self._priority.get(ip)
            if record is not None:
                record.opening -= 1
                if record.opening == 0 and not record.handles and not record.closed:
                    del self._priority[ip]  # đã mất ưu tiên (retain_trusted), giữ tới khi hết vé
        else:
            entry = self._entries.get(ip)
            if entry is not None:
                entry.opening -= 1
        if live.anonymous:
            count = self._anonymous[ip] - 1
            if count:
                self._anonymous[ip] = count
            else:
                del self._anonymous[ip]
            self._anonymous_total -= 1
        if ticket.pool is Pool.PRIORITY and not live.refunded:
            self._strike(ip, now)

    # ---- Ưu tiên ---------------------------------------------------------------------------

    def control_opened(self, ip: str, fingerprint: str, now: float) -> int:
        """Có kết nối điều khiển đã xác thực mTLS với `ip` (thiết bị `fingerprint`): cấp ưu tiên.

        Gọi cho kết nối vào đã qua kiểm `is_trusted`, và cho kết nối ra đã kiểm chứng chỉ
        server trong bắt tay. Trả handle (≥ 1) để báo `control_closed`. Trả 0 và không cấp
        ưu tiên (`control_closed(0)` không làm gì) khi `ip` đang bị hạ ưu tiên, hoặc khi
        bảng ưu tiên đầy (`MAX_PRIORITY_IPS`) mà mục nào cũng còn kết nối sống hoặc vé
        sống. `fingerprint` không phải 64 ký tự hex thường → ValueError.
        """
        ip = _normalize_ip(ip)
        _check_fingerprint(fingerprint)
        now = self._advance(now)
        if self._is_demoted(ip, now):
            return 0
        record = self._priority.get(ip)
        if record is None:
            if not self._make_priority_room(now):
                return 0
            record = _Priority(
                _Bucket(float(PRIORITY_BURST_PER_IP), now), _Bucket(float(PRIORITY_STRIKES), now)
            )
            self._priority[ip] = record
        handle = self._next_handle
        self._next_handle += 1
        record.handles[handle] = fingerprint
        self._handles[handle] = (ip, now)
        return handle

    def control_closed(self, handle: int, now: float) -> None:
        """Kết nối của `handle` đã đóng: IP còn ưu tiên thêm `PRIORITY_TTL` từ `now`.

        Kết nối đã sống ít nhất `STRIKE_CREDIT_AFTER` giây → cộng lại 1 vào ngân sách lỗi
        của IP (không vượt `PRIORITY_STRIKES`). Handle 0, handle lạ, đã đóng hoặc đã bị
        xóa (`retain_trusted`, hạ ưu tiên): không làm gì. `handle` không phải int → TypeError.
        """
        if isinstance(handle, bool) or not isinstance(handle, int):
            raise TypeError("handle phải là số nguyên")
        now = self._advance(now)
        item = self._handles.pop(handle, None)
        if item is None:
            return
        ip, opened_at = item
        record = self._priority[ip]
        if now - opened_at >= STRIKE_CREDIT_AFTER and not self._is_demoted(ip, now):
            record.strikes.give_back(now, _strike_rate(), PRIORITY_STRIKES)
        fingerprint = record.handles.pop(handle)
        record.closed.pop(fingerprint, None)
        record.closed[fingerprint] = now  # giữ thứ tự tăng dần theo lúc đóng
        while len(record.closed) > _MAX_FINGERPRINTS_PER_IP:
            del record.closed[next(iter(record.closed))]

    def retain_trusted(self, fingerprints: Iterable[str]) -> None:
        """Chỉ giữ ưu tiên do các thiết bị trong `fingerprints` (danh sách tin cậy hiện tại) mang lại.

        Fingerprint không còn trong danh sách: handle sống của nó bị xóa (hủy ghép đôi
        thắng kết nối đang sống) và mốc đóng của nó bị bỏ; IP không còn gì giữ thì về
        pool chung ngay. Vé đang sống không bị ảnh hưởng. `fingerprints` là một chuỗi,
        hoặc có phần tử không phải 64 ký tự hex thường → ValueError, trạng thái không đổi.
        """
        if isinstance(fingerprints, str | bytes):
            raise ValueError("fingerprints phải là một dãy fingerprint, không phải một chuỗi")
        keep = {_check_fingerprint(fp) for fp in fingerprints}
        for ip, record in list(self._priority.items()):
            for handle, fp in list(record.handles.items()):
                if fp not in keep:
                    del record.handles[handle]
                    del self._handles[handle]
            for fp in [fp for fp in record.closed if fp not in keep]:
                del record.closed[fp]
            if record.opening == 0 and not record.handles and not record.closed:
                del self._priority[ip]

    def is_priority(self, ip: str, now: float) -> bool:
        """`ip` có đang được ưu tiên không (kết nối mới từ đó vào pool ưu tiên); bị hạ → False."""
        ip = _normalize_ip(ip)
        now = self._advance(now)
        return self._active_priority(ip, now) is not None

    def priority_strikes(self, ip: str, now: float) -> float | None:
        """Ngân sách lỗi còn lại của `ip` (đã tính phần hồi tới `now`); chẩn đoán, test, đo.

        None: `ip` không được ưu tiên (không có mục ưu tiên, hết hạn, hoặc đang bị hạ).
        `ip` sai → ValueError.
        """
        ip = _normalize_ip(ip)
        now = self._advance(now)
        record = self._active_priority(ip, now)
        if record is None:
            return None
        return record.strikes.available(now, _strike_rate(), PRIORITY_STRIKES)

    # ---- Nội bộ ----------------------------------------------------------------------------

    def _advance(self, now: object) -> float:
        """Kiểm `now` rồi đẩy đồng hồ của gate; gọi sau khi đã kiểm mọi tham số khác."""
        if isinstance(now, bool) or not isinstance(now, int | float):
            raise TypeError("now phải là số giây (đồng hồ monotonic)")
        if not is_finite(now):
            raise ValueError("now phải là số hữu hạn")
        if self._last_now is not None and now < self._last_now:
            raise ValueError("now không được nhỏ hơn lần gọi trước")
        self._last_now = float(now)
        return self._last_now

    def _refuse(self, reason: Refusal) -> Refusal:
        self._refusals[reason] += 1
        return reason

    def _active_priority(self, ip: str, now: float) -> _Priority | None:
        """Mục ưu tiên của `ip` nếu còn hiệu lực; mục hết hiệu lực mà không còn vé thì bỏ."""
        record = self._priority.get(ip)
        if record is None:
            return None
        if not self._is_demoted(ip, now) and record.active(now):
            return record
        if record.opening == 0:
            del self._priority[ip]
        return None

    def _is_demoted(self, ip: str, now: float) -> bool:
        """`ip` có đang bị hạ ưu tiên không; mục đã hết hạn thì bỏ."""
        until = self._demoted.get(ip)
        if until is None:
            return False
        if now < until:
            return True
        del self._demoted[ip]
        return False

    def _strike(self, ip: str, now: float) -> None:
        """Một vé ưu tiên của `ip` kết thúc mà không bắt tay tin cậy: trừ ngân sách lỗi hoặc hạ."""
        record = self._active_priority(ip, now)
        if record is None:
            return  # đã ở pool chung: không còn ưu tiên để hạ
        rate, cap = _strike_rate(), PRIORITY_STRIKES
        if record.strikes.available(now, rate, cap) >= 1:
            record.strikes.take(now, rate, cap)
        else:
            self._demote(ip, now)

    def _demote(self, ip: str, now: float) -> None:
        """Hạ ưu tiên `ip` tới `now + PRIORITY_TTL`; bỏ handle sống và mốc đóng của nó.

        Handle bị bỏ thì `control_closed` của nó không làm gì (như `retain_trusted`). Mục
        ưu tiên còn vé sống thì giữ tới khi hết vé. Bảng hạ đầy: bỏ các mục đã hết hạn,
        rồi mục hết hạn sớm nhất.
        """
        self._demoted.pop(ip, None)  # thêm lại ở cuối, với hạn mới
        if len(self._demoted) >= MAX_DEMOTED_IPS:
            for other, until in list(self._demoted.items()):
                if now >= until:
                    del self._demoted[other]
            while self._demoted and len(self._demoted) >= MAX_DEMOTED_IPS:
                del self._demoted[min(self._demoted, key=self._demoted.__getitem__)]
        if len(self._demoted) < MAX_DEMOTED_IPS:  # trần ≤ 0 (chỉ có trong test): không ghi
            self._demoted[ip] = now + PRIORITY_TTL
        record = self._priority.get(ip)
        if record is not None:
            for handle in record.handles:
                del self._handles[handle]
            record.handles.clear()
            record.closed.clear()
            if record.opening == 0:
                del self._priority[ip]
        # DEBUG: lũ kết nối không được làm ngập log; số IP bị hạ ở `demoted_ips`.
        log.debug("%s: vé ưu tiên kết thúc mà không bắt tay tin cậy, hạ ưu tiên", ip)

    def _prune(self, now: float) -> None:
        """Bỏ dần các mục đầu bảng pool chung đã đầy lại mà không có vé sống."""
        rate, burst = HANDSHAKE_RATE_PER_IP, HANDSHAKE_BURST_PER_IP
        for _ in range(_PRUNE_STEP):
            if not self._entries:
                return
            ip, entry = next(iter(self._entries.items()))
            if entry.opening:
                self._entries.move_to_end(ip)  # đang dùng: xếp xuống cuối
            elif entry.bucket.available(now, rate, burst) >= burst:
                del self._entries[ip]
            else:
                return  # các mục sau được dùng gần hơn, cũng chưa đầy lại

    def _make_room(self) -> bool:
        """Chỗ cho một mục mới của pool chung; đầy thì bỏ mục dùng lâu nhất không có vé sống."""
        while len(self._entries) >= MAX_TRACKED_IPS:
            victim = next((ip for ip, entry in self._entries.items() if not entry.opening), None)
            if victim is None:
                return False
            del self._entries[victim]
        return True

    def _make_priority_room(self, now: float) -> bool:
        """Chỗ cho một IP ưu tiên mới; đầy thì bỏ mục hết hiệu lực, rồi mục đóng lâu nhất.

        Không bao giờ bỏ mục còn kết nối sống hoặc vé sống.
        """
        if len(self._priority) < MAX_PRIORITY_IPS:
            return True
        for ip, record in list(self._priority.items()):
            if record.opening == 0 and not record.active(now):
                del self._priority[ip]
        if len(self._priority) < MAX_PRIORITY_IPS:
            return True
        records = self._priority.items()
        idle = sorted((r.last_closed(), ip) for ip, r in records if not (r.handles or r.opening))
        while idle and len(self._priority) >= MAX_PRIORITY_IPS:
            del self._priority[idle.pop(0)[1]]
        return len(self._priority) < MAX_PRIORITY_IPS
