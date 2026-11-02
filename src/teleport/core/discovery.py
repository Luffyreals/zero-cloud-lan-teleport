"""Khám phá thiết bị qua mDNS/DNS-SD (sans-IO): bản ghi TXT, lọc địa chỉ, theo dõi thiết bị.

Đặc tả ở docs/protocol.md mục 8. Module không mở socket, không xem đồng hồ: tầng
`net` (`teleport.net.discovery`) bọc thư viện zeroconf, đưa tên dịch vụ và kết quả
resolve vào `DiscoveryTracker` cùng thời gian monotonic `now`, rồi thực hiện các
lệnh resolve và chuyển sự kiện thiết bị mà tracker trả về. `NetworkWatch` nhận các
lần đọc địa chỉ và đồng hồ định kỳ, báo khi mạng đổi hoặc máy vừa thức dậy (để `app`
khởi động lại hoặc quảng bá lại mDNS).

Mọi bản ghi mDNS đến từ máy khác nên không bao giờ được tin: tên dịch vụ, TXT,
cổng và địa chỉ đều được kiểm ở đây (`parse_service`); bản ghi sai bị bỏ qua.

Vì python-zeroconf nâng TTL của bản ghi PTR nhận được lên tối thiểu 1125 s, máy
tắt đột ngột (không gửi goodbye) sẽ không bị báo `Removed` sớm. Tracker tự kiểm
còn sống: cứ `PROBE_INTERVAL` giây resolve lại SRV/TXT/A (TTL 60 s); thất bại
`MAX_RESOLVE_FAILURES` lần liên tiếp thì báo `DeviceRemoved` (protocol mục 8).

Cũng vì zeroconf chỉ báo `Added` một lần cho mỗi PTR, dịch vụ bị bỏ qua lúc tracker
đã đầy được ghi vào danh sách tràn và nhận lại khi có chỗ; thiết bị đã ghép đôi
(tập ưu tiên) luôn được nhận, không tính vào giới hạn.
"""

from __future__ import annotations

import ipaddress
import itertools
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from teleport.core.messages import (
    MAX_SAFE_INTEGER,
    PROTOCOL_VERSION,
    MessageError,
    validate_device_id,
    validate_device_name,
    validate_os,
)
from teleport.core.numbers import is_finite

SERVICE_TYPE = "_teleport._tcp.local."
RECORD_TTL = 60  # giây, cho mọi bản ghi quảng bá (host_ttl và other_ttl)
TXT_NAME_MAX_BYTES = 200  # độ dài UTF-8 tối đa của `name` trong TXT
MAX_ADDRESSES = 16  # số địa chỉ IPv4 tối đa mỗi thiết bị, cả khi quảng bá và khi nhận
MAX_RAW_ADDRESSES = 1024  # số phần tử đầu vào tối đa `filter_addresses` xét
MAX_TRACKED_SERVICES = 256  # số ứng viên không ưu tiên tối đa tracker theo dõi cùng lúc
MAX_OVERFLOW_NAMES = 1024  # số device_id tối đa chờ chỗ trong danh sách tràn
PROBE_INTERVAL = 15.0  # giây giữa hai lần resolve lại để kiểm thiết bị còn sống
MAX_PROBE_BACKOFF = 240.0  # giây, khoảng probe tối đa cho thiết bị đã biến mất
RESOLVE_TIMEOUT = 3.0  # giây chờ tối đa cho một lần resolve
MAX_RESOLVE_FAILURES = 2  # số lần resolve thất bại liên tiếp trước khi coi thiết bị đã biến mất
WAKE_JUMP = 15.0  # giây: đồng hồ nhảy quá mức này thì coi là máy vừa thức dậy (`NetworkWatch`)

_SERVICE_SUFFIX = "." + SERVICE_TYPE
_PROTO_RE = re.compile(r"[1-9][0-9]{0,15}")
_ZWJ = "\u200d"  # escape, không viết ký tự vô hình vào mã nguồn

# Nhận ra card mạng ảo theo tên (Adapter.name, Adapter.nice_name, IP.nice_name của
# ifaddr), so sau `casefold().strip()`: card ảo khi tên bắt đầu bằng một tiền tố hoặc
# chứa một chuỗi con dưới đây (Docker, WSL, Hyper-V, VPN, máy ảo…).
_VIRTUAL_PREFIXES = (
    "docker",
    "br-",
    "veth",
    "virbr",
    "vmnet",
    "vboxnet",
    "tun",
    "tap",
    "wg",
    "tailscale",
    "zt",
    "utun",
    "ipsec",
    "ppp",
    "llw",
    "awdl",
    "bridge",
    "lxc",
    "lxd",
    "cni",
    "flannel",
    "podman",
    "vethernet",
)
_VIRTUAL_SUBSTRINGS = (
    "virtual",
    "hyper-v",
    "vmware",
    "virtualbox",
    "tap-windows",
    "wintun",
    "wireguard",
    "tailscale",
    "zerotier",
    "openvpn",
    "vpn",
    "anyconnect",
    "fortinet",
    "globalprotect",
    "pangp",
    "docker",
    "wsl",
    "loopback",
    "npcap",
)
_ZERO_NETWORK = ipaddress.IPv4Network("0.0.0.0/8")


class DiscoveryRecordError(ValueError):
    """Bản ghi mDNS của máy khác không hợp lệ: tên dịch vụ, TXT, cổng hoặc địa chỉ sai."""


@dataclass(frozen=True, slots=True)
class TxtRecord:
    """Nội dung bản ghi TXT đã kiểm tra (protocol mục 8)."""

    device_id: str
    name: str
    os: str
    proto: int  # khác PROTOCOL_VERSION vẫn hợp lệ; so phiên bản là việc của tầng trên


@dataclass(frozen=True, slots=True)
class ResolvedService:
    """Dữ liệu thô `net` lấy từ zeroconf cho một dịch vụ, CHƯA kiểm tra."""

    name: str  # tên instance đầy đủ, ví dụ "<device_id>._teleport._tcp.local."
    txt: Mapping[bytes, bytes | None]  # = AsyncServiceInfo.properties
    port: int | None
    addresses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    """Một thiết bị tìm thấy trên mạng, đã qua `parse_service`."""

    device_id: str
    name: str
    os: str
    proto: int
    port: int
    addresses: tuple[str, ...]  # 1–16 IPv4 đã lọc, sắp tăng dần


@dataclass(frozen=True, slots=True)
class DeviceAdded:
    """Thiết bị mới xuất hiện (hoặc quay lại sau khi đã báo `DeviceRemoved`)."""

    device: DiscoveredDevice


@dataclass(frozen=True, slots=True)
class DeviceUpdated:
    """Thiết bị đã biết đổi tên, cổng, địa chỉ, os hoặc proto."""

    device: DiscoveredDevice
    previous: DiscoveredDevice


@dataclass(frozen=True, slots=True)
class DeviceRemoved:
    """Thiết bị biến mất (goodbye hoặc kiểm còn sống thất bại). `device` là bản cuối đã biết."""

    device: DiscoveredDevice


DeviceEvent = DeviceAdded | DeviceUpdated | DeviceRemoved


@dataclass(frozen=True, slots=True)
class InterfaceAddress:
    """Một địa chỉ IP của card mạng máy này, kèm các tên của card (để nhận ra card ảo)."""

    ip: str
    names: tuple[str, ...]  # Adapter.name, Adapter.nice_name, IP.nice_name


# ---- Bản ghi TXT ---------------------------------------------------------------------------


def truncate_txt_name(name: str) -> str:
    """Cắt tên thiết bị cho vừa `TXT_NAME_MAX_BYTES` byte UTF-8 (protocol mục 8).

    Tên sai → MessageError. Tên vừa thì trả nguyên; không thì lấy tiền tố dài nhất
    theo code point vừa giới hạn, rồi bỏ khoảng trắng và U+200D (ZWJ) ở cuối. Kết
    quả luôn khác rỗng và vẫn là tên hợp lệ. Cắt theo code point, không theo
    grapheme: emoji ghép có thể bị cắt mất phần sau.
    """
    validate_device_name(name)
    if len(name.encode("utf-8")) <= TXT_NAME_MAX_BYTES:
        return name
    size = 0
    end = 0
    for ch in name:
        size += len(ch.encode("utf-8"))
        if size > TXT_NAME_MAX_BYTES:
            break
        end += 1
    result = name[:end]
    while result and (result[-1].isspace() or result[-1] == _ZWJ):
        result = result[:-1]
    # Tên dài quá 200 byte có tối đa 64 ký tự nên phải chứa ký tự 4 byte; khoảng trắng
    # và ZWJ dài tối đa 3 byte, nên tiền tố ≥ 197 byte không thể toàn là chúng.
    return validate_device_name(result)


def build_txt(device_id: str, name: str, os: str) -> dict[str, str]:
    """Bản ghi TXT để quảng bá. Tham số sai → MessageError."""
    validate_device_id(device_id)
    return {
        "id": device_id,
        "name": truncate_txt_name(name),
        "os": validate_os(os),
        "proto": str(PROTOCOL_VERSION),
    }


def _txt_value(txt: Mapping[bytes, bytes | None], key: bytes) -> bytes:
    value = txt.get(key)
    if value is None:
        # Thiếu khóa, hoặc khóa không có "=" (zeroconf trả None).
        raise DiscoveryRecordError(f"TXT thiếu {key.decode()}")
    if not isinstance(value, bytes):
        raise DiscoveryRecordError(f"TXT {key.decode()} phải là bytes")
    return value


def parse_txt(txt: Mapping[bytes, bytes | None]) -> TxtRecord:
    """Kiểm bản ghi TXT nhận được (dạng `AsyncServiceInfo.properties`); sai → DiscoveryRecordError.

    Khóa so chính xác, chữ thường; khóa lạ bị bỏ qua; một khóa sai làm hỏng cả bản ghi.
    """
    if not isinstance(txt, Mapping):
        raise DiscoveryRecordError("TXT phải là mapping")
    try:
        device_id = validate_device_id(_txt_value(txt, b"id").decode("ascii"))
        raw_name = _txt_value(txt, b"name")
        if len(raw_name) > TXT_NAME_MAX_BYTES:
            raise DiscoveryRecordError(f"TXT name dài quá {TXT_NAME_MAX_BYTES} byte")
        name = validate_device_name(raw_name.decode("utf-8"))
        os = validate_os(_txt_value(txt, b"os").decode("ascii"))
        raw_proto = _txt_value(txt, b"proto").decode("ascii")
        if not _PROTO_RE.fullmatch(raw_proto) or int(raw_proto) > MAX_SAFE_INTEGER:
            raise DiscoveryRecordError(f"TXT proto phải là số nguyên 1…{MAX_SAFE_INTEGER}")
    except (UnicodeDecodeError, MessageError) as e:
        raise DiscoveryRecordError(f"TXT không hợp lệ: {e}") from e
    return TxtRecord(device_id=device_id, name=name, os=os, proto=int(raw_proto))


# ---- Tên dịch vụ và địa chỉ ----------------------------------------------------------------


def service_name(device_id: str) -> str:
    """Tên instance quảng bá: `<device_id>._teleport._tcp.local.`. Mã sai → MessageError."""
    return validate_device_id(device_id) + _SERVICE_SUFFIX


def device_id_from_service_name(name: str) -> str | None:
    """Lấy device_id từ tên instance; tên sai dạng → None.

    Hậu tố `._teleport._tcp.local.` so không phân biệt hoa thường (chỉ ASCII); nhãn
    còn lại phải đúng 32 ký tự hex thường.
    """
    if not isinstance(name, str) or len(name) <= len(_SERVICE_SUFFIX):
        return None
    suffix = name[-len(_SERVICE_SUFFIX) :]
    # isascii(): chặn ký tự Unicode mà lower() đổi thành chữ ASCII (ví dụ dấu Kelvin → "k").
    if not suffix.isascii() or suffix.lower() != _SERVICE_SUFFIX:
        return None
    try:
        return validate_device_id(name[: -len(_SERVICE_SUFFIX)])
    except MessageError:
        return None


def _usable_ipv4(value: object) -> ipaddress.IPv4Address | None:
    """IPv4 dùng được để kết nối trong LAN; còn lại (kể cả không phải chuỗi) → None."""
    if not isinstance(value, str):
        return None
    try:
        addr = ipaddress.IPv4Address(value)
    except ValueError:
        return None
    if (
        addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_unspecified
        or addr.is_reserved
        or addr in _ZERO_NETWORK
    ):
        return None
    return addr


def filter_addresses(addresses: Iterable[object], *, lan_only: bool = False) -> tuple[str, ...]:
    """Giữ IPv4 dùng được, bỏ trùng, sắp tăng dần theo số, tối đa `MAX_ADDRESSES`.

    Bị bỏ: phần tử không phải chuỗi, không phải IPv4 (kể cả có số 0 đứng đầu),
    loopback, link-local, multicast, reserved (240/4, 255.255.255.255) và 0.0.0.0/8.
    `lan_only` bỏ thêm địa chỉ Internet công khai (`is_global`) trước khi cắt còn
    `MAX_ADDRESSES`: dùng cho bản ghi nhận được, vì node không tự gọi ra Internet
    (mvp N9) mà mDNS không xác thực (protocol mục 8).
    Chỉ xét `MAX_RAW_ADDRESSES` phần tử đầu của đầu vào; phần sau bị bỏ, để một bản
    ghi cực lớn từ máy khác không tốn thời gian xử lý tùy ý.
    """
    head = itertools.islice(addresses, MAX_RAW_ADDRESSES)
    usable = {
        addr
        for value in head
        if (addr := _usable_ipv4(value)) is not None and not (lan_only and addr.is_global)
    }
    return tuple(str(addr) for addr in sorted(usable)[:MAX_ADDRESSES])


def parse_service(resolved: ResolvedService) -> DiscoveredDevice:
    """Kiểm dữ liệu resolve của một dịch vụ; sai → DiscoveryRecordError."""
    device_id = device_id_from_service_name(resolved.name)
    if device_id is None:
        raise DiscoveryRecordError(f"tên dịch vụ không hợp lệ: {resolved.name!r}")
    txt = parse_txt(resolved.txt)
    if txt.device_id != device_id:
        raise DiscoveryRecordError("id trong TXT khác nhãn của tên dịch vụ")
    port = resolved.port
    if type(port) is not int or not 1 <= port <= 65535:
        raise DiscoveryRecordError("cổng phải là số nguyên 1–65535")
    addresses = filter_addresses(resolved.addresses, lan_only=True)
    if not addresses:
        raise DiscoveryRecordError("không có địa chỉ IPv4 dùng được")
    return DiscoveredDevice(
        device_id=device_id,
        name=txt.name,
        os=txt.os,
        proto=txt.proto,
        port=port,
        addresses=addresses,
    )


# ---- Địa chỉ của máy này -------------------------------------------------------------------


def is_virtual_interface(names: Iterable[str]) -> bool:
    """Card mạng có phải card ảo (Docker, WSL, Hyper-V, VPN, máy ảo…) không, đoán theo tên."""
    for name in names:
        if not isinstance(name, str):
            continue
        n = name.casefold().strip()
        if n.startswith(_VIRTUAL_PREFIXES) or any(s in n for s in _VIRTUAL_SUBSTRINGS):
            return True
    return False


def select_local_addresses(
    interfaces: Iterable[InterfaceAddress], preferred: str | None = None
) -> tuple[str, ...]:
    """Chọn địa chỉ IPv4 của máy này để quảng bá (protocol mục 2.1).

    Ứng viên là địa chỉ qua bộ lọc của `filter_addresses`. Bỏ địa chỉ chỉ nằm trên
    card ảo, với hai ngoại lệ: luôn giữ `preferred` nếu nó là ứng viên; và nếu mọi
    ứng viên đều trên card ảo thì dùng tất cả.

    `preferred` là địa chỉ nguồn của tuyến ra ngoài LAN do `net` cung cấp. Nó được
    giữ dù card trông như card ảo vì máy ra ngoài qua chính card đó (Hyper-V External
    vSwitch, máy khách Hyper-V). `preferred` đứng đầu, còn lại tăng dần; tối đa
    `MAX_ADDRESSES`. Thứ tự này chỉ ảnh hưởng gợi ý của `teleport listen` và phép so
    sánh của `NetworkWatch`; bên nhận sắp lại tăng dần qua `filter_addresses`.
    """
    real: dict[ipaddress.IPv4Address, bool] = {}
    for iface in interfaces:
        addr = _usable_ipv4(iface.ip)
        if addr is not None:
            real[addr] = real.get(addr, False) or not is_virtual_interface(iface.names)
    preferred_addr = _usable_ipv4(preferred)
    if preferred_addr not in real:
        preferred_addr = None
    kept = [addr for addr, is_real in real.items() if is_real or addr == preferred_addr]
    if not kept:
        kept = list(real)
    ordered = sorted(kept, key=lambda addr: (addr != preferred_addr, addr))
    return tuple(str(addr) for addr in ordered[:MAX_ADDRESSES])


# ---- Theo dõi thiết bị ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TrackerOutput:
    """Kết quả một lời gọi `DiscoveryTracker`; `net` xử lý theo thứ tự các trường.

    Mỗi tên trong `resolve` hoặc `probe` phải được trả lại qua `resolve_done` đúng
    một lần. `net` ưu tiên chạy `resolve` (thiết bị mới hoặc vừa đổi) trước `probe`
    (kiểm còn sống), để kiểm định kỳ không làm chậm việc tìm thấy thiết bị mới.
    """

    events: tuple[DeviceEvent, ...] = ()
    resolve: tuple[str, ...] = ()  # resolve lần đầu, sau thay đổi, hoặc khi dịch vụ quay lại
    probe: tuple[str, ...] = ()  # resolve lại để kiểm còn sống
    notes: tuple[str, ...] = ()  # lý do bỏ qua, `net` ghi log DEBUG


_EMPTY = TrackerOutput()


@dataclass(slots=True)
class _Candidate:
    """Một dịch vụ zeroconf đang theo dõi, khóa theo device_id."""

    name: str  # tên chuẩn `service_name(device_id)`, không dùng tên thô zeroconf báo
    pending: bool = False  # đang chờ `resolve_done` (tối đa một yêu cầu mỗi device_id)
    dirty: bool = False  # zeroconf báo thay đổi trong lúc đang resolve → resolve lại
    # Bia mộ: dịch vụ bị `Removed` khi resolve còn chạy. Ứng viên được giữ (vẫn tính vào
    # `max_services`) tới khi resolve đó trả về, để không bao giờ có hai resolve cùng lúc.
    gone: bool = False
    stale: bool = False  # kết quả của resolve đang chạy đã cũ, sẽ bị bỏ
    failures: int = 0  # số lần resolve thất bại liên tiếp
    ever_valid: bool = False  # đã từng có bản ghi hợp lệ
    last_attempt: float | None = None  # `now` của lần `resolve_done` gần nhất
    # Giây giữa hai lần probe: `probe_interval`, trừ khi thiết bị đã biến mất (thưa dần).
    probe_delay: float = PROBE_INTERVAL
    device: DiscoveredDevice | None = None  # bản hợp lệ gần nhất, nếu thiết bị đang hiện


def _check_now(now: object) -> float:
    """`now` phải là số hữu hạn (giây, đồng hồ monotonic)."""
    if isinstance(now, bool) or not isinstance(now, int | float):
        raise TypeError("now phải là số giây (đồng hồ monotonic)")
    if not is_finite(now):
        raise ValueError("now phải là số hữu hạn")
    return float(now)


def _check_priority_ids(device_ids: Iterable[str]) -> frozenset[str]:
    """Tập device_id ưu tiên; phần tử sai (hoặc truyền một chuỗi thay vì tập) → MessageError."""
    if isinstance(device_ids, str | bytes):
        raise MessageError("tập ưu tiên phải là một tập device_id, không phải một chuỗi")
    return frozenset(validate_device_id(device_id) for device_id in device_ids)


class DiscoveryTracker:
    """Máy trạng thái theo dõi thiết bị từ thông báo của zeroconf (sans-IO).

    `net` gọi `service_seen` / `service_gone` theo sự kiện của ServiceBrowser, thực
    hiện mọi tên trong `TrackerOutput.resolve` và `TrackerOutput.probe` rồi trả kết
    quả qua `resolve_done`, và định kỳ gọi `due_probes` để kiểm thiết bị còn sống.
    Tên yêu cầu resolve luôn là tên chuẩn `service_name(device_id)`.

    Thiết bị chỉ bị xóa khi zeroconf báo `Removed` (goodbye) hoặc sau
    `MAX_RESOLVE_FAILURES` lần resolve thất bại liên tiếp. Ứng viên chưa từng có bản
    ghi hợp lệ mà thất bại ngần ấy lần thì bị bỏ hẳn để nhường chỗ. Ứng viên đã từng
    hợp lệ nhưng đã biến mất vẫn được giữ và probe thưa dần: khoảng cách nhân đôi
    sau mỗi lần thất bại, từ `probe_interval` tới tối đa `MAX_PROBE_BACKOFF`.

    Thiết bị ưu tiên (đã ghép đôi; `priority_ids`, `set_priority`) luôn được nhận và
    không tính vào `max_services`. Dịch vụ không ưu tiên đến lúc đã đủ thì vào danh
    sách tràn (FIFO, tối đa `MAX_OVERFLOW_NAMES`, đầy thì bỏ tên cũ nhất); mỗi khi
    một ứng viên bị xóa và có chỗ, tên cũ nhất trong danh sách tràn được nhận và
    yêu cầu resolve ngay trong kết quả của lời gọi đó. Vì zeroconf chỉ báo `Added`
    một lần cho mỗi PTR, không có danh sách này thì dịch vụ đã bị bỏ qua sẽ vô hình
    tới khi PTR được làm mới.

    Bất biến: `devices` không chứa máy này; số ứng viên không ưu tiên ≤
    `max_services`, trừ khi tạm vượt vì ứng viên đang theo dõi thôi ưu tiên (khi đó
    không nhận thêm ứng viên không ưu tiên tới khi xuống dưới giới hạn); danh sách
    tràn chỉ khác rỗng khi đã đủ, và không chứa máy này, ứng viên hay id ưu tiên;
    với mỗi device_id, sự kiện có dạng `Added (Updated)* Removed`, lặp lại được; áp
    tuần tự các sự kiện dựng lại đúng `devices`; mỗi device_id có tối đa một yêu
    cầu resolve đang chờ (kể cả qua `Removed` rồi `Added` lại).
    """

    def __init__(
        self,
        self_device_id: str,
        *,
        max_services: int = MAX_TRACKED_SERVICES,
        probe_interval: float = PROBE_INTERVAL,
        priority_ids: Iterable[str] = (),
    ) -> None:
        validate_device_id(self_device_id)
        if type(max_services) is not int or max_services < 1:
            raise ValueError("max_services phải là số nguyên ≥ 1")
        if isinstance(probe_interval, bool) or not isinstance(probe_interval, int | float):
            raise TypeError("probe_interval phải là số giây")
        if not is_finite(probe_interval) or probe_interval <= 0:
            raise ValueError("probe_interval phải là số hữu hạn > 0")
        self._self_id = self_device_id
        self._max_services = max_services
        self._probe_interval = float(probe_interval)
        self._priority = _check_priority_ids(priority_ids) - {self_device_id}
        self._candidates: dict[str, _Candidate] = {}
        self._regular = 0  # số ứng viên không ưu tiên (tính vào `max_services`)
        self._overflow: dict[str, None] = {}  # danh sách tràn: dict giữ thứ tự chèn (FIFO)
        self._devices: dict[str, DiscoveredDevice] = {}
        self._devices_view = MappingProxyType(self._devices)

    @property
    def devices(self) -> Mapping[str, DiscoveredDevice]:
        """Thiết bị đang hiện, khóa theo device_id (chỉ đọc, luôn phản ánh trạng thái hiện tại)."""
        return self._devices_view

    # ---- Ứng viên, ưu tiên và danh sách tràn ---------------------------------------------------

    def _add_candidate(self, device_id: str) -> _Candidate:
        cand = self._candidates[device_id] = _Candidate(
            name=service_name(device_id), probe_delay=self._probe_interval
        )
        if device_id not in self._priority:
            self._regular += 1
        return cand

    def _drop_candidate(self, device_id: str) -> tuple[str, ...]:
        """Xóa ứng viên; trả các tên vừa nhận từ danh sách tràn (cần resolve)."""
        del self._candidates[device_id]
        if device_id not in self._priority:
            self._regular -= 1
        return self._admit_overflow()

    def _admit_overflow(self) -> tuple[str, ...]:
        """Nhận tên cũ nhất trong danh sách tràn tới khi đủ lại hoặc hết danh sách."""
        names = []
        while self._overflow and self._regular < self._max_services:
            device_id = next(iter(self._overflow))
            del self._overflow[device_id]
            cand = self._add_candidate(device_id)
            cand.pending = True
            names.append(cand.name)
        return tuple(names)

    def _remember_overflow(self, device_id: str) -> None:
        """Ghi device_id vào cuối danh sách tràn (đã có thì giữ vị trí; đầy thì bỏ tên cũ nhất)."""
        if device_id in self._overflow:
            return
        while self._overflow and len(self._overflow) >= MAX_OVERFLOW_NAMES:
            del self._overflow[next(iter(self._overflow))]
        self._overflow[device_id] = None

    def is_priority(self, device_id: str) -> bool:
        """`device_id` có trong tập ưu tiên hiện tại không; id sai (hoặc của máy này) → False."""
        return isinstance(device_id, str) and device_id in self._priority

    def set_priority(self, device_ids: Iterable[str]) -> TrackerOutput:
        """Thay toàn bộ tập thiết bị ưu tiên (thiết bị đã ghép đôi); bỏ qua máy này.

        Phần tử sai → MessageError, trạng thái giữ nguyên. Id ưu tiên đang chờ trong
        danh sách tràn được nhận và yêu cầu resolve ngay. Ứng viên thường đang theo
        dõi được nâng lên ưu tiên thì nhả một chỗ trong `max_services`, nên id cũ nhất
        trong danh sách tràn được nhận (và yêu cầu resolve) ngay trong kết quả này. Id
        thôi ưu tiên đang được theo dõi vẫn giữ, nhưng từ nay tính vào `max_services`.
        """
        self._priority = _check_priority_ids(device_ids) - {self._self_id}
        self._regular = sum(1 for device_id in self._candidates if device_id not in self._priority)
        names = []
        for device_id in [d for d in self._overflow if d in self._priority]:
            del self._overflow[device_id]
            cand = self._add_candidate(device_id)
            cand.pending = True
            names.append(cand.name)
        # Ứng viên đang theo dõi vừa thành ưu tiên thì nhả chỗ trong `max_services`.
        names.extend(self._admit_overflow())
        return TrackerOutput(resolve=tuple(names)) if names else _EMPTY

    # ---- Thông báo của zeroconf và kết quả resolve ---------------------------------------------

    def service_seen(self, name: str) -> TrackerOutput:
        """zeroconf báo dịch vụ `Added` hoặc `Updated`."""
        device_id = device_id_from_service_name(name)
        if device_id is None:
            return TrackerOutput(notes=(f"bỏ qua tên dịch vụ không hợp lệ: {name!r}",))
        if device_id == self._self_id:
            return TrackerOutput(notes=("bỏ qua dịch vụ của chính máy này",))
        cand = self._candidates.get(device_id)
        if cand is None:
            if device_id not in self._priority and self._regular >= self._max_services:
                self._remember_overflow(device_id)
                return TrackerOutput(
                    notes=(f"bỏ qua {name!r} (chờ chỗ): đã theo dõi đủ {self._max_services} dịch vụ",)
                )
            self._overflow.pop(device_id, None)
            cand = self._add_candidate(device_id)
        else:
            # zeroconf vừa thấy lại dịch vụ: trở về nhịp probe thường.
            cand.probe_delay = self._probe_interval
            if cand.pending:
                # Kể cả bia mộ: resolve cũ còn chạy, chờ nó trả về rồi mới resolve lại.
                cand.gone = False
                cand.dirty = True
                return _EMPTY
        cand.pending = True
        return TrackerOutput(resolve=(cand.name,))

    def service_gone(self, name: str) -> TrackerOutput:
        """zeroconf báo dịch vụ `Removed` (goodbye hoặc hết TTL)."""
        device_id = device_id_from_service_name(name)
        if device_id is None:
            return _EMPTY
        cand = self._candidates.get(device_id)
        if cand is None:
            self._overflow.pop(device_id, None)
            return _EMPTY
        events: tuple[DeviceEvent, ...] = ()
        if cand.device is not None:
            events = (DeviceRemoved(cand.device),)
            del self._devices[device_id]
            cand.device = None
        resolve: tuple[str, ...] = ()
        if cand.pending:
            # Giữ làm bia mộ tới khi resolve đang chạy trả về; kết quả của nó đã cũ.
            cand.gone = True
            cand.stale = True
            cand.dirty = False
            cand.failures = 0
        else:
            resolve = self._drop_candidate(device_id)
        return TrackerOutput(events=events, resolve=resolve)

    def resolve_done(self, name: str, result: ResolvedService | None, now: float) -> TrackerOutput:
        """Kết quả resolve một tên tracker đã yêu cầu; `result` None khi resolve thất bại."""
        now = _check_now(now)
        if result is not None and not isinstance(result, ResolvedService):
            raise TypeError("result phải là ResolvedService hoặc None")
        device_id = device_id_from_service_name(name)
        if device_id is None:
            return _EMPTY
        cand = self._candidates.get(device_id)
        if cand is None or not cand.pending:
            return _EMPTY
        cand.pending = False
        cand.last_attempt = now

        if cand.stale:
            cand.stale = False
            note = (f"bỏ kết quả resolve cũ của {name!r}: dịch vụ đã bị xóa trong lúc resolve",)
            if cand.gone:
                return TrackerOutput(resolve=self._drop_candidate(device_id), notes=note)
            # Dịch vụ đã quay lại trong lúc chờ: resolve mới.
            cand.dirty = False
            cand.pending = True
            return TrackerOutput(resolve=(cand.name,), notes=note)

        events: list[DeviceEvent] = []
        notes: list[str] = []
        device: DiscoveredDevice | None = None
        if result is not None:
            try:
                device = parse_service(result)
                if device.device_id != device_id:
                    raise DiscoveryRecordError("kết quả resolve thuộc dịch vụ khác")
            except DiscoveryRecordError as e:
                device = None
                notes.append(f"bỏ qua bản ghi của {name!r}: {e}")

        if device is not None:
            cand.failures = 0
            cand.ever_valid = True
            cand.probe_delay = self._probe_interval
            if cand.device is None:
                events.append(DeviceAdded(device))
            elif device != cand.device:
                events.append(DeviceUpdated(device, previous=cand.device))
            cand.device = self._devices[device_id] = device
        elif cand.device is not None and result is not None:
            # Bản ghi mới bị sai nhưng máy vẫn trả lời: giữ bản hợp lệ cũ, coi là còn sống.
            cand.failures = 0
        else:
            if cand.device is None and cand.ever_valid:
                # Thiết bị đã biến mất: probe thưa dần để máy tắt lâu không tốn mạng.
                limit = max(MAX_PROBE_BACKOFF, self._probe_interval)
                cand.probe_delay = min(cand.probe_delay * 2, limit)
            cand.failures += 1
            if result is None:
                notes.append(f"resolve {name!r} thất bại ({cand.failures} lần liên tiếp)")
            if cand.failures >= MAX_RESOLVE_FAILURES:
                cand.failures = 0
                if cand.device is not None:
                    events.append(DeviceRemoved(cand.device))
                    del self._devices[device_id]
                    cand.device = None
                elif not cand.ever_valid:
                    # Chưa từng hợp lệ: bỏ hẳn để nhường chỗ trong `max_services`, kể cả khi
                    # đang `dirty` (không resolve thêm).
                    notes.append(f"ngừng theo dõi {name!r}: chưa từng có bản ghi hợp lệ")
                    admitted = self._drop_candidate(device_id)
                    return TrackerOutput(events=tuple(events), resolve=admitted, notes=tuple(notes))

        resolve: tuple[str, ...] = ()
        if cand.dirty:
            cand.dirty = False
            cand.pending = True
            resolve = (cand.name,)
        return TrackerOutput(events=tuple(events), resolve=resolve, notes=tuple(notes))

    def due_probes(self, now: float) -> TrackerOutput:
        """Các dịch vụ đến hạn kiểm còn sống.

        Hạn là `probe_interval` giây từ lần resolve trước; thiết bị đã biến mất thì
        theo khoảng thưa dần (tối đa `MAX_PROBE_BACKOFF`).
        """
        now = _check_now(now)
        due = []
        for _, cand in sorted(self._candidates.items()):
            if (
                not cand.pending
                and cand.last_attempt is not None
                and now - cand.last_attempt >= cand.probe_delay
            ):
                cand.pending = True
                due.append(cand.name)
        return TrackerOutput(probe=tuple(due)) if due else _EMPTY


# ---- Mạng đổi, máy thức dậy ----------------------------------------------------------------


class NetworkChange(StrEnum):
    """Kết quả một lần `NetworkWatch.sample`."""

    NONE = "none"
    ADDRESSES = "addresses"  # danh sách địa chỉ quảng bá đổi (cả thứ tự)
    WOKE = "woke"  # máy vừa thức dậy (hoặc giờ hệ thống bị chỉnh)


def _check_clock(name: str, value: object) -> float:
    """Giá trị đồng hồ: số hữu hạn (giây)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"{name} phải là số giây")
    if not is_finite(value):
        raise ValueError(f"{name} phải là số hữu hạn")
    return float(value)


def _check_address_list(addresses: object) -> tuple[str, ...]:
    if isinstance(addresses, str | bytes) or not isinstance(addresses, Iterable):
        raise ValueError("addresses phải là một dãy địa chỉ, không phải một chuỗi")
    items = tuple(addresses)
    if not all(isinstance(a, str) for a in items):
        raise ValueError("địa chỉ phải là chuỗi")
    return items


class NetworkWatch:
    """Phát hiện mạng đổi hoặc máy vừa thức dậy, từ các lần đọc định kỳ (sans-IO).

    `app` cứ `interval` giây đọc địa chỉ quảng bá (`local_ipv4_addresses`), đồng hồ
    monotonic và đồng hồ hệ thống, rồi gọi `sample`. Địa chỉ khác lần trước (cả thứ
    tự) → `ADDRESSES`; không thì đồng hồ nhảy → `WOKE`: khoảng monotonic giữa hai lần
    đọc vượt `interval + WAKE_JUMP` (nền tảng mà monotonic chạy trong lúc ngủ, như
    Windows), hoặc khoảng đồng hồ hệ thống lệch khoảng monotonic quá `WAKE_JUMP`
    (nền tảng mà monotonic dừng lúc ngủ, như Linux, macOS; cả khi giờ bị chỉnh tay).
    """

    def __init__(self, addresses: Sequence[str], mono: float, wall: float) -> None:
        """Tham số sai → ValueError / TypeError."""
        self._addresses = _check_address_list(addresses)
        self._mono = _check_clock("mono", mono)
        self._wall = _check_clock("wall", wall)

    def sample(self, addresses: Sequence[str], mono: float, wall: float, *, interval: float) -> NetworkChange:
        """Một lần đọc mới; lưu lại cả ba giá trị. Tham số sai (gồm `mono` giảm) → ValueError /
        TypeError, trạng thái giữ nguyên."""
        items = _check_address_list(addresses)
        mono = _check_clock("mono", mono)
        wall = _check_clock("wall", wall)
        interval = _check_clock("interval", interval)
        if interval <= 0:
            raise ValueError("interval phải > 0")
        if mono < self._mono:
            raise ValueError("mono không được giảm")
        gap_mono = mono - self._mono
        gap_wall = wall - self._wall
        changed = items != self._addresses
        self._addresses, self._mono, self._wall = items, mono, wall
        if changed:
            return NetworkChange.ADDRESSES
        if gap_mono > interval + WAKE_JUMP or abs(gap_wall - gap_mono) > WAKE_JUMP:
            return NetworkChange.WOKE
        return NetworkChange.NONE
