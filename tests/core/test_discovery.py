"""Test `teleport.core.discovery` theo kế hoạch PR 3 (mục 2.2–2.4 và mục 4) và bước 1.3 (ưu tiên
thiết bị đã ghép đôi, danh sách tràn, probe thưa dần, cắt đầu vào địa chỉ).

Viết từ đặc tả, không từ code: TXT ↔ dữ liệu, cắt tên, tên dịch vụ, lọc địa chỉ, nhận diện card ảo,
chọn địa chỉ quảng bá và máy trạng thái `DiscoveryTracker`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import ipaddress
import itertools
import math

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# Hằng/hàm mới của bước 1.3 (ưu tiên, tràn, probe thưa dần, cắt đầu vào) được truy cập qua module,
# để khi chúng chưa có thì chỉ các test mới đỏ, không làm hỏng import của cả file.
import teleport.core.discovery as core_discovery
from teleport.core.discovery import (
    MAX_ADDRESSES,
    MAX_RESOLVE_FAILURES,
    MAX_TRACKED_SERVICES,
    PROBE_INTERVAL,
    RECORD_TTL,
    RESOLVE_TIMEOUT,
    SERVICE_TYPE,
    TXT_NAME_MAX_BYTES,
    DeviceAdded,
    DeviceRemoved,
    DeviceUpdated,
    DiscoveredDevice,
    DiscoveryRecordError,
    DiscoveryTracker,
    InterfaceAddress,
    ResolvedService,
    TrackerOutput,
    TxtRecord,
    build_txt,
    device_id_from_service_name,
    filter_addresses,
    is_virtual_interface,
    parse_service,
    parse_txt,
    select_local_addresses,
    service_name,
    truncate_txt_name,
)
from teleport.core.messages import MAX_SAFE_INTEGER, PROTOCOL_VERSION, MessageError, validate_device_name

E = "\U0001f600"  # 😀, 4 byte UTF-8
EE = "ệ"  # ệ, 3 byte UTF-8
ZWJ = "‍"


def make_id(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()[:32]


SELF = make_id("self")
PEER = make_id("peer")
PEER2 = make_id("peer2")


def txt_bytes(device_id: str, name: str = "PC", os: str = "windows") -> dict[bytes, bytes | None]:
    """TXT dạng zeroconf trả về (`AsyncServiceInfo.properties`) dựng từ `build_txt`."""
    return {k.encode(): v.encode() for k, v in build_txt(device_id, name, os).items()}


def good_txt(**override: bytes | None) -> dict[bytes, bytes | None]:
    txt = txt_bytes(PEER)
    for key, value in override.items():
        txt[key.encode()] = value
    return txt


def resolved(
    device_id: str = PEER,
    *,
    name: str = "PC",
    os: str = "windows",
    port: object = 47474,
    addresses: tuple = ("192.168.1.20",),
    txt: dict[bytes, bytes | None] | None = None,
    svc: str | None = None,
) -> ResolvedService:
    return ResolvedService(
        name=svc if svc is not None else service_name(device_id),
        txt=txt if txt is not None else txt_bytes(device_id, name, os),
        port=port,
        addresses=addresses,
    )


def device(
    device_id: str = PEER, *, name: str = "PC", port: int = 47474, addresses=("192.168.1.20",)
) -> DiscoveredDevice:
    return DiscoveredDevice(
        device_id=device_id,
        name=name,
        os="windows",
        proto=PROTOCOL_VERSION,
        port=port,
        addresses=tuple(addresses),
    )


# --- Hằng số -------------------------------------------------------------------------------------


def test_constants_match_plan():
    assert SERVICE_TYPE == "_teleport._tcp.local."
    assert RECORD_TTL == 60
    assert TXT_NAME_MAX_BYTES == 200
    assert MAX_ADDRESSES == 16
    assert MAX_TRACKED_SERVICES == 256
    assert PROBE_INTERVAL == 15.0
    assert RESOLVE_TIMEOUT == 3.0
    assert MAX_RESOLVE_FAILURES == 2


def test_discovery_record_error_is_value_error():
    assert issubclass(DiscoveryRecordError, ValueError)


def test_data_classes_are_frozen():
    rec = TxtRecord(device_id=PEER, name="PC", os="windows", proto=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.name = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        device().port = 1  # type: ignore[misc]


def test_tracker_output_defaults_are_empty():
    out = TrackerOutput()
    assert out.events == () and out.resolve == () and out.probe == () and out.notes == ()


# --- truncate_txt_name ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a" * 64, "a" * 64),
        (EE * 64, EE * 64),  # 192 byte
        (E * 64, E * 50),  # 256 → 200 byte
        (E * 49 + "ab" + E * 13, E * 49 + "ab"),
        (E * 49 + "a " + E * 13, E * 49 + "a"),  # bỏ khoảng trắng cuối sau khi cắt
        (E * 40 + EE * 24, E * 40 + EE * 13),
        (E * 49 + "a" + ZWJ + E * 13, E * 49 + "a"),  # bỏ ZWJ cuối sau khi cắt
        (E * 49 + ZWJ + " x" + E * 10, E * 49),  # bỏ dần cả khoảng trắng lẫn ZWJ
        (E * 49 + "　　" + E * 10, E * 49),  # khoảng trắng Unicode (isspace)
        ("Máy A 😀", "Máy A 😀"),
    ],
    ids=["ascii64", "e3x64", "emoji64", "ab", "a_space", "mixed", "zwj", "zwj_space", "ideo_space", "short"],
)
def test_truncate_txt_name_vectors(name, expected):
    result = truncate_txt_name(name)
    assert result == expected
    assert len(result.encode("utf-8")) <= TXT_NAME_MAX_BYTES


def test_truncate_keeps_trailing_zwj_when_no_cut_needed():
    # Chỉ bỏ ZWJ cuối khi đã phải cắt; tên ≤ 200 byte được trả nguyên.
    assert truncate_txt_name("a" + ZWJ) == "a" + ZWJ


def test_truncate_at_exact_limit_is_unchanged():
    name = E * 50
    assert len(name.encode()) == 200
    assert truncate_txt_name(name) == name


def test_truncate_one_byte_over_limit():
    name = E * 50 + "a"  # 201 byte
    assert truncate_txt_name(name) == E * 50


@pytest.mark.parametrize("bad", ["", " a", "a ", "a\n", "x" * 65, "a‮b", None, 5], ids=repr)
def test_truncate_rejects_invalid_name(bad):
    with pytest.raises(MessageError):
        truncate_txt_name(bad)


def reference_truncate(name: str) -> str:
    """Bản tham chiếu viết lại đúng 4 bước của kế hoạch mục 2.3."""
    if len(name.encode("utf-8")) <= 200:
        return name
    out, size = [], 0
    for ch in name:
        n = len(ch.encode("utf-8"))
        if size + n > 200:
            break
        out.append(ch)
        size += n
    result = "".join(out)
    while result and (result[-1].isspace() or result[-1] == ZWJ):
        result = result[:-1]
    return result


def _is_valid_name(value: str) -> bool:
    try:
        validate_device_name(value)
    except MessageError:
        return False
    return True


name_chars = st.sampled_from([E, EE, "a", "Z", " ", ZWJ, "中", "　", "\U0001f468"]) | st.characters(
    exclude_categories=("Cs", "Cc")
)
valid_names = st.text(alphabet=name_chars, min_size=1, max_size=64).filter(_is_valid_name)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
@given(valid_names)
def test_property_truncate_txt_name(name):
    result = truncate_txt_name(name)
    assert result, "tên sau khi cắt không được rỗng"
    assert len(result.encode("utf-8")) <= TXT_NAME_MAX_BYTES
    assert name.startswith(result)
    assert validate_device_name(result) == result
    if len(name.encode("utf-8")) <= TXT_NAME_MAX_BYTES:
        assert result == name
    else:
        assert not result[-1].isspace() and result[-1] != ZWJ
    assert result == reference_truncate(name)


# --- build_txt / parse_txt -----------------------------------------------------------------------


def test_build_txt_has_exactly_the_four_keys():
    assert build_txt(PEER, "PC-Nha", "windows") == {
        "id": PEER,
        "name": "PC-Nha",
        "os": "windows",
        "proto": str(PROTOCOL_VERSION),
    }


def test_build_txt_truncates_long_name():
    assert build_txt(PEER, E * 64, "linux")["name"] == E * 50


@pytest.mark.parametrize(
    ("device_id", "name", "os"),
    [
        (PEER.upper(), "PC", "windows"),
        (PEER[:-1], "PC", "windows"),
        (PEER, "", "windows"),
        (PEER, " PC", "windows"),
        (PEER, "PC", "Windows"),
        (PEER, "PC", ""),
        (PEER, "PC", "a" * 17),
    ],
    ids=["id_upper", "id_short", "name_empty", "name_space", "os_upper", "os_empty", "os_long"],
)
def test_build_txt_rejects_invalid_fields(device_id, name, os):
    with pytest.raises(MessageError):
        build_txt(device_id, name, os)


def test_parse_txt_valid_record():
    assert parse_txt(txt_bytes(PEER, "Máy A 😀", "macos")) == TxtRecord(
        device_id=PEER, name="Máy A 😀", os="macos", proto=PROTOCOL_VERSION
    )


device_ids = st.from_regex(r"[0-9a-f]{32}", fullmatch=True)
os_names = st.from_regex(r"[a-z0-9_]{1,16}", fullmatch=True)


@pytest.mark.slow
@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.filter_too_much])
@given(device_ids, valid_names, os_names)
def test_property_build_then_parse_roundtrip(device_id, name, os):
    txt = {k.encode(): v.encode() for k, v in build_txt(device_id, name, os).items()}
    assert parse_txt(txt) == TxtRecord(
        device_id=device_id, name=truncate_txt_name(name), os=os, proto=PROTOCOL_VERSION
    )


def test_parse_txt_ignores_unknown_keys():
    txt = good_txt(extra=b"1", flag=None)
    txt[b"\xff\xfe"] = b"\x00"
    assert parse_txt(txt).device_id == PEER


@pytest.mark.parametrize("key", [b"id", b"name", b"os", b"proto"])
def test_parse_txt_rejects_missing_key(key):
    txt = good_txt()
    del txt[key]
    with pytest.raises(DiscoveryRecordError):
        parse_txt(txt)


@pytest.mark.parametrize("key", [b"id", b"name", b"os", b"proto"])
def test_parse_txt_rejects_none_value(key):
    txt = good_txt()
    txt[key] = None
    with pytest.raises(DiscoveryRecordError):
        parse_txt(txt)


@pytest.mark.parametrize("key", [b"id", b"name", b"os", b"proto"])
def test_parse_txt_keys_are_case_sensitive(key):
    txt = good_txt()
    txt[key.upper()] = txt.pop(key)
    with pytest.raises(DiscoveryRecordError):
        parse_txt(txt)


@pytest.mark.parametrize(
    "value",
    [
        PEER.upper().encode(),
        PEER[:-1].encode(),
        (PEER + "0").encode(),
        PEER.encode() + b"\n",
        b"",
        b"\xff" * 32,
        ("é" + PEER[2:]).encode("utf-8"),
        "０".encode() + PEER[1:].encode(),  # chữ số 0 toàn chiều rộng
    ],
    ids=repr,
)
def test_parse_txt_rejects_bad_id(value):
    with pytest.raises(DiscoveryRecordError):
        parse_txt(good_txt(id=value))


@pytest.mark.parametrize(
    "value",
    [
        b"\xff",
        b"PC\xc3",  # UTF-8 bị cắt cụt
        b"\xed\xa0\x80",  # surrogate mã hóa UTF-8 (không hợp lệ ở chế độ strict)
        b"",
        b" PC",
        b"PC ",
        b"P\nC",
        "a‮b".encode(),
        b"x" * 65,
        (E * 50 + "a").encode(),  # 201 byte, 51 code point: vượt giới hạn byte
    ],
    ids=repr,
)
def test_parse_txt_rejects_bad_name(value):
    with pytest.raises(DiscoveryRecordError):
        parse_txt(good_txt(name=value))


def test_parse_txt_accepts_name_of_exactly_200_bytes():
    assert parse_txt(good_txt(name=(E * 50).encode())).name == E * 50


@pytest.mark.parametrize(
    "value", [b"Windows", b"", b"mac os", b"a" * 17, "ｗｉｎ".encode(), b"\xff"], ids=repr
)
def test_parse_txt_rejects_bad_os(value):
    with pytest.raises(DiscoveryRecordError):
        parse_txt(good_txt(os=value))


@pytest.mark.parametrize(
    "value",
    [
        b"0",
        b"01",
        b"+1",
        b"-1",
        b"1.0",
        b" 1",
        b"1\n",
        b"",
        "١".encode(),  # chữ số Ả Rập ١
        "１".encode(),  # chữ số 1 toàn chiều rộng
        b"1_0",
        b"0x1",
        str(MAX_SAFE_INTEGER + 1).encode(),  # 9007199254740992
        b"1" * 17,
    ],
    ids=repr,
)
def test_parse_txt_rejects_bad_proto(value):
    with pytest.raises(DiscoveryRecordError):
        parse_txt(good_txt(proto=value))


@pytest.mark.parametrize("value", [1, 2, 99, MAX_SAFE_INTEGER])
def test_parse_txt_accepts_any_proto_in_range(value):
    # proto khác PROTOCOL_VERSION vẫn hợp lệ: bên trên quyết định có nói chuyện được không.
    assert parse_txt(good_txt(proto=str(value).encode())).proto == value


def test_parse_txt_wraps_decode_error_with_cause():
    with pytest.raises(DiscoveryRecordError) as info:
        parse_txt(good_txt(name=b"\xff"))
    assert isinstance(info.value.__cause__, UnicodeDecodeError)


def test_parse_txt_wraps_message_error_with_cause():
    with pytest.raises(DiscoveryRecordError) as info:
        parse_txt(good_txt(os=b"Windows"))
    assert isinstance(info.value.__cause__, MessageError)


txt_keys = st.sampled_from([b"id", b"name", b"os", b"proto", b"ID", b"Name", b"x", b""]) | st.binary(
    max_size=8
)
txt_values = st.none() | st.binary(max_size=210) | st.sampled_from(list(txt_bytes(PEER).values()))


@pytest.mark.slow
@settings(max_examples=500, deadline=None)
@given(st.dictionaries(txt_keys, txt_values, max_size=8))
def test_fuzz_parse_txt_only_raises_discovery_record_error(txt):
    try:
        rec = parse_txt(txt)
    except DiscoveryRecordError:
        return
    assert isinstance(rec, TxtRecord)
    assert validate_device_name(rec.name) == rec.name
    assert type(rec.proto) is int and 1 <= rec.proto <= MAX_SAFE_INTEGER


@settings(max_examples=300, deadline=None)
@given(st.fixed_dictionaries({}, optional={k.encode(): txt_values for k in ("id", "name", "os", "proto")}))
def test_fuzz_parse_txt_near_valid(txt):
    base = good_txt()
    base.update(txt)
    try:
        rec = parse_txt(base)
    except DiscoveryRecordError:
        return
    assert isinstance(rec, TxtRecord)


# --- service_name / device_id_from_service_name --------------------------------------------------


def test_service_name_format():
    assert service_name(PEER) == f"{PEER}._teleport._tcp.local."


def test_device_id_from_service_name_roundtrip():
    assert device_id_from_service_name(service_name(PEER)) == PEER


def test_device_id_from_service_name_accepts_uppercase_suffix():
    assert device_id_from_service_name(f"{PEER}._TELEPORT._TCP.LOCAL.") == PEER
    assert device_id_from_service_name(f"{PEER}._Teleport._tcp.Local.") == PEER


@pytest.mark.parametrize(
    "name",
    [
        "notanid._teleport._tcp.local.",
        f"{PEER.upper()}._teleport._tcp.local.",
        f"{PEER[:-1]}._teleport._tcp.local.",
        f"{PEER}0._teleport._tcp.local.",
        f"a.{PEER}._teleport._tcp.local.",
        f"{PEER}\n._teleport._tcp.local.",
        "._teleport._tcp.local.",
        "_teleport._tcp.local.",
        f"{PEER}_teleport._tcp.local.",
        f"{PEER}._teleport._tcp.local",
        f"{PEER}._http._tcp.local.",
        f"{PEER}._teleport._udp.local.",
        f"{PEER}._teleport._tcp.local.x",
        "",
    ],
    ids=repr,
)
def test_device_id_from_service_name_rejects(name):
    assert device_id_from_service_name(name) is None


# --- filter_addresses ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        "127.0.0.1",
        "127.255.0.9",
        "169.254.1.1",
        "224.0.0.251",
        "239.255.255.250",
        "0.1.2.3",
        "0.0.0.0",
        "255.255.255.255",
        "240.0.0.1",
        "01.2.3.4",
        "1.2.3",
        "1.2.3.4 ",
        " 1.2.3.4",
        "1.2.3.4/32",
        "256.1.1.1",
        "",
        "::1",
        "fe80::1",
        "2001:db8::1",
        "::ffff:192.168.1.1",
        None,
        3232235777,
        b"\xc0\xa8\x01\x01",
        ipaddress.IPv4Address("192.168.1.1"),
    ],
    ids=repr,
)
def test_filter_addresses_drops_bad_entry(bad):
    assert filter_addresses([bad, "192.168.1.5"]) == ("192.168.1.5",)


@pytest.mark.parametrize(
    "good", ["192.168.1.5", "10.0.0.1", "172.16.0.1", "100.64.0.1", "8.8.8.8", "192.0.2.10", "198.51.100.7"]
)
def test_filter_addresses_keeps_usable_ipv4(good):
    assert filter_addresses([good]) == (good,)


def test_filter_addresses_empty():
    assert filter_addresses([]) == ()
    assert filter_addresses(["127.0.0.1", "::1"]) == ()


def test_filter_addresses_dedupes_and_sorts_numerically():
    result = filter_addresses(["10.0.0.10", "9.1.1.1", "10.0.0.9", "10.0.0.10", "9.1.1.1"])
    assert result == ("9.1.1.1", "10.0.0.9", "10.0.0.10")


def test_filter_addresses_accepts_any_iterable():
    assert filter_addresses(a for a in ["10.0.0.2", "10.0.0.1"]) == ("10.0.0.1", "10.0.0.2")


def test_max_raw_addresses_constant():
    assert core_discovery.MAX_RAW_ADDRESSES == 1024


def test_filter_addresses_ignores_entries_after_the_first_1024():
    # Địa chỉ hợp lệ ở vị trí 1025 bị bỏ: chỉ 1024 phần tử đầu được xét.
    items = ["127.0.0.1"] * 1024 + ["10.0.0.1"]
    assert filter_addresses(items) == ()


def test_filter_addresses_considers_entry_at_position_1024():
    items = ["127.0.0.1"] * 1023 + ["10.0.0.1"]
    assert filter_addresses(items) == ("10.0.0.1",)


def test_filter_addresses_cut_happens_before_dedupe_and_sort():
    # 1024 phần tử đầu cho ra 10.0.0.9; 10.0.0.1 (nhỏ hơn) ở phía sau bị bỏ dù sắp xếp sẽ đưa nó lên đầu.
    items = ["10.0.0.9"] * 1024 + ["10.0.0.1"]
    assert filter_addresses(items) == ("10.0.0.9",)


def test_filter_addresses_terminates_on_endless_iterator():
    assert filter_addresses(itertools.repeat("10.0.0.1")) == ("10.0.0.1",)


def test_filter_addresses_reads_at_most_1024_items():
    consumed = 0

    def endless():
        nonlocal consumed
        while True:
            consumed += 1
            yield "127.0.0.1"

    assert filter_addresses(endless()) == ()
    assert consumed <= 1024


def test_parse_service_rejects_when_only_usable_address_is_past_1024():
    with pytest.raises(DiscoveryRecordError):
        parse_service(resolved(addresses=("127.0.0.1",) * 1024 + ("192.168.1.20",)))


def test_filter_addresses_caps_at_16_smallest():
    addrs = [f"10.0.0.{i}" for i in range(20, 0, -1)]  # 20 địa chỉ, thứ tự ngược
    result = filter_addresses(addrs)
    assert len(result) == MAX_ADDRESSES == 16
    assert result == tuple(f"10.0.0.{i}" for i in range(1, 17))


def test_filter_addresses_lan_only_drops_public_before_cap():
    """`lan_only` bỏ địa chỉ Internet công khai trước khi cắt còn 16, nên địa chỉ công khai (sắp
    trước theo số) không đẩy mất địa chỉ LAN; mặc định vẫn giữ (địa chỉ của máy này)."""
    public = [f"8.8.{i}.1" for i in range(MAX_ADDRESSES)]
    lan = ["192.168.1.20", "10.0.0.1", "100.64.0.1", "192.0.2.10"]
    assert filter_addresses([*public, *lan], lan_only=True) == (
        "10.0.0.1",
        "100.64.0.1",
        "192.0.2.10",
        "192.168.1.20",
    )
    assert filter_addresses(public) == tuple(public)


def test_parse_service_drops_public_addresses():
    """Protocol mục 8: máy trong LAN không khiến node tự gọi ra Internet (mvp N9) qua mDNS."""
    assert parse_service(resolved(addresses=("8.8.8.8", "192.168.1.20", "1.1.1.1"))).addresses == (
        "192.168.1.20",
    )
    with pytest.raises(DiscoveryRecordError):
        parse_service(resolved(addresses=("8.8.8.8", "1.1.1.1")))


@pytest.mark.slow
@settings(max_examples=300, deadline=None)
@given(
    st.lists(
        st.ip_addresses(v=4).map(str)
        | st.ip_addresses(v=6).map(str)
        | st.text(max_size=16)
        | st.integers()
        | st.none(),
        max_size=40,
    )
)
def test_property_filter_addresses(items):
    result = filter_addresses(items)
    assert isinstance(result, tuple)
    assert len(result) <= 16
    parsed = [ipaddress.IPv4Address(a) for a in result]
    assert parsed == sorted(set(parsed))
    for a in parsed:
        assert not (a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified or a.is_reserved)
        assert a not in ipaddress.IPv4Network("0.0.0.0/8")
    assert all(type(a) is str and a in items for a in result)


# --- parse_service -------------------------------------------------------------------------------


def test_parse_service_valid():
    r = resolved(addresses=("10.0.0.2", "127.0.0.1", "10.0.0.1", "fe80::1"), port=1)
    assert parse_service(r) == DiscoveredDevice(
        device_id=PEER,
        name="PC",
        os="windows",
        proto=PROTOCOL_VERSION,
        port=1,
        addresses=("10.0.0.1", "10.0.0.2"),
    )


def test_parse_service_accepts_port_65535_and_uppercase_suffix():
    r = resolved(port=65535, svc=f"{PEER}._TELEPORT._TCP.LOCAL.")
    assert parse_service(r).port == 65535


@pytest.mark.parametrize(
    "r",
    [
        resolved(svc="notanid._teleport._tcp.local."),
        resolved(svc=f"{PEER}._http._tcp.local."),
        resolved(txt=txt_bytes(PEER2)),  # id trong TXT khác nhãn instance
        resolved(txt=good_txt(os=b"Windows")),
        resolved(txt={}),
        resolved(port=0),
        resolved(port=65536),
        resolved(port=-1),
        resolved(port=True),
        resolved(port=None),
        resolved(port=47474.0),
        resolved(port="47474"),
        resolved(addresses=()),
        resolved(addresses=("127.0.0.1", "169.254.1.1", "::1")),
    ],
    ids=[
        "bad_label",
        "wrong_type",
        "id_mismatch",
        "bad_txt",
        "empty_txt",
        "port0",
        "port65536",
        "port_neg",
        "port_true",
        "port_none",
        "port_float",
        "port_str",
        "no_addr",
        "no_usable_addr",
    ],
)
def test_parse_service_rejects(r):
    with pytest.raises(DiscoveryRecordError):
        parse_service(r)


# --- is_virtual_interface ------------------------------------------------------------------------

VIRTUAL_NAMES = [
    "vEthernet (WSL)",
    "Hyper-V Virtual Ethernet Adapter",
    "docker0",
    "br-1a2b",
    "veth12",
    "virbr0",
    "vmnet8",
    "vboxnet0",
    "tun0",
    "wg0",
    "tailscale0",
    "ztabc",
    "utun3",
    "TAP-Windows Adapter V9",
    "WireGuard Tunnel",
    "ZeroTier Virtual Port",
    "VirtualBox Host-Only Ethernet Adapter",
    "  DOCKER0  ",
    "bridge0",
    "awdl0",
    "llw0",
    "Npcap Loopback Adapter",
    "Cisco AnyConnect Secure Mobility Client",
    "Wintun Userspace Tunnel",
]
REAL_NAMES = [
    "Wi-Fi",
    "Ethernet",
    "Ethernet 2",
    "Intel(R) Wi-Fi 6 AX201 160MHz",
    "Realtek PCIe GbE Family Controller",
    "en0",
    "eth0",
    "wlan0",
    "enp3s0",
    "wlp2s0",
    "br0",
]


@pytest.mark.parametrize("name", VIRTUAL_NAMES)
def test_is_virtual_interface_detects_virtual(name):
    assert is_virtual_interface([name]) is True


@pytest.mark.parametrize("name", REAL_NAMES)
def test_is_virtual_interface_keeps_real(name):
    assert is_virtual_interface([name]) is False


def test_is_virtual_interface_any_name_matches():
    # Tên adapter trên Windows là GUID; tên dễ đọc mới cho biết card ảo.
    guid = "{4D36E972-E325-11CE-BFC1-08002BE10318}"
    assert is_virtual_interface((guid, "Hyper-V Virtual Ethernet Adapter", "vEthernet (WSL)")) is True
    assert is_virtual_interface((guid, "Intel(R) Wi-Fi 6 AX201 160MHz", "Wi-Fi")) is False
    assert is_virtual_interface(n for n in ["eth0", "docker0"]) is True


def test_is_virtual_interface_no_names_is_not_virtual():
    assert is_virtual_interface([]) is False


# --- select_local_addresses ----------------------------------------------------------------------


def iface(ip: str, *names: str) -> InterfaceAddress:
    return InterfaceAddress(ip=ip, names=names)


WIFI = iface("192.168.1.10", "{GUID-1}", "Intel(R) Wi-Fi 6 AX201 160MHz", "Wi-Fi")
ETH = iface("10.0.0.5", "eth0", "eth0", "eth0")
WSL = iface("172.20.0.1", "{GUID-2}", "Hyper-V Virtual Ethernet Adapter", "vEthernet (WSL)")
DOCKER = iface("172.17.0.1", "docker0", "docker0", "docker0")
LOOP = iface("127.0.0.1", "lo", "lo", "lo")
LINK_LOCAL = iface("169.254.3.4", "Ethernet 2", "Ethernet 2", "Ethernet 2")


def test_select_drops_virtual_loopback_and_link_local():
    assert select_local_addresses([WIFI, WSL, LOOP, LINK_LOCAL, DOCKER]) == ("192.168.1.10",)


def test_select_keeps_preferred_even_on_virtual_card():
    assert select_local_addresses([WIFI, WSL], preferred="172.20.0.1") == ("172.20.0.1", "192.168.1.10")


WSL_HYPERV = iface("172.18.96.1", "{GUID-3}", "Hyper-V Virtual Ethernet Adapter")
EXTERNAL_VSWITCH = iface("192.168.1.20", "{GUID-4}", "Hyper-V Virtual Ethernet Adapter #2")


def test_select_external_vswitch_keeps_only_preferred_lan_address():
    # Hyper-V External vSwitch: máy ra ngoài LAN qua card "#2" (trông như card ảo).
    # preferred = nguồn của tuyến ra ngoài LAN → giữ nó, card WSL vẫn bị lọc.
    assert select_local_addresses([WSL_HYPERV, EXTERNAL_VSWITCH], preferred="192.168.1.20") == (
        "192.168.1.20",
    )


def test_select_external_vswitch_without_preferred_uses_all_ascending():
    # LAN không gateway → không có preferred; mọi ứng viên đều trên card ảo → dùng tất cả, tăng dần.
    assert select_local_addresses([EXTERNAL_VSWITCH, WSL_HYPERV]) == ("172.18.96.1", "192.168.1.20")


def test_select_puts_preferred_first_then_ascending():
    assert select_local_addresses([ETH, WIFI], preferred="192.168.1.10") == ("192.168.1.10", "10.0.0.5")
    assert select_local_addresses([WIFI, ETH]) == ("10.0.0.5", "192.168.1.10")


@pytest.mark.parametrize("preferred", [None, "10.9.9.9", "127.0.0.1", "169.254.3.4", "0.0.0.0", "bogus"])
def test_select_ignores_preferred_that_is_not_a_candidate(preferred):
    assert select_local_addresses([WIFI, ETH, LOOP, LINK_LOCAL], preferred=preferred) == (
        "10.0.0.5",
        "192.168.1.10",
    )


def test_select_falls_back_to_virtual_cards_when_nothing_else():
    assert select_local_addresses([WSL, DOCKER, LOOP]) == ("172.17.0.1", "172.20.0.1")


def test_select_returns_empty_when_no_candidate():
    assert select_local_addresses([]) == ()
    assert select_local_addresses([LOOP, LINK_LOCAL]) == ()
    assert select_local_addresses([LOOP], preferred="127.0.0.1") == ()


def test_select_dedupes_same_ip():
    assert select_local_addresses([WIFI, iface("192.168.1.10", "Wi-Fi")], preferred="192.168.1.10") == (
        "192.168.1.10",
    )


def test_select_caps_at_16():
    many = [iface(f"10.0.1.{i}", f"eth{i}") for i in range(1, 21)]
    assert select_local_addresses(many) == tuple(f"10.0.1.{i}" for i in range(1, 17))


def test_select_caps_at_16_keeping_preferred_first():
    # preferred là địa chỉ lớn nhất trong 20: vẫn phải được giữ và đứng đầu.
    many = [iface(f"10.0.1.{i}", f"eth{i}") for i in range(1, 21)]
    result = select_local_addresses(many, preferred="10.0.1.20")
    assert len(result) == 16
    assert result == ("10.0.1.20", *(f"10.0.1.{i}" for i in range(1, 16)))


# --- DiscoveryTracker: tham số -------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", SELF.upper(), SELF[:-1], None, 123])
def test_tracker_rejects_invalid_self_id(bad):
    with pytest.raises(ValueError):
        DiscoveryTracker(bad)


@pytest.mark.parametrize("bad_now", [math.nan, math.inf, -math.inf])
def test_tracker_rejects_non_finite_now(bad_now):
    t = DiscoveryTracker(SELF)
    with pytest.raises(ValueError):
        t.due_probes(bad_now)
    t.service_seen(service_name(PEER))
    with pytest.raises(ValueError):
        t.resolve_done(service_name(PEER), resolved(), bad_now)


def test_tracker_devices_is_read_only_mapping():
    t = DiscoveryTracker(SELF)
    assert dict(t.devices) == {}
    with pytest.raises(TypeError):
        t.devices[PEER] = device()  # type: ignore[index]


def no_requests(out: TrackerOutput) -> bool:
    return out.resolve == () and out.probe == ()


def known(t: DiscoveryTracker, now: float = 0.0, dev_id: str = PEER, **kw) -> str:
    """Đưa `dev_id` vào trạng thái đã có thiết bị hợp lệ, không pending; trả tên chuẩn."""
    name = service_name(dev_id)
    assert t.service_seen(name).resolve == (name,)
    assert t.resolve_done(name, resolved(dev_id, **kw), now).events == (
        DeviceAdded(parse_service(resolved(dev_id, **kw))),
    )
    return name


# --- DiscoveryTracker: service_seen --------------------------------------------------------------


def test_seen_new_service_requests_resolve():
    t = DiscoveryTracker(SELF)
    out = t.service_seen(service_name(PEER))
    assert out.events == ()
    assert out.resolve == (service_name(PEER),)
    assert out.probe == ()


@pytest.mark.parametrize("name", [service_name(SELF), f"{SELF}._TELEPORT._TCP.LOCAL."])
def test_seen_self_is_ignored_with_note(name):
    t = DiscoveryTracker(SELF)
    out = t.service_seen(name)
    assert out.events == () and no_requests(out)
    assert out.notes
    assert no_requests(t.due_probes(1e9))


@pytest.mark.parametrize(
    "name",
    [
        "notanid._teleport._tcp.local.",
        f"{PEER}._http._tcp.local.",
        "",
        f"{PEER.upper()}._teleport._tcp.local.",
    ],
)
def test_seen_bad_name_is_ignored_with_note(name):
    t = DiscoveryTracker(SELF)
    out = t.service_seen(name)
    assert out.events == () and no_requests(out)
    assert out.notes


def test_seen_while_pending_marks_dirty_and_resolves_again_after_result():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    assert t.service_seen(name) == TrackerOutput()  # đang pending: không yêu cầu resolve lần hai
    out = t.resolve_done(name, resolved(), 10.0)
    assert out.events == (DeviceAdded(device()),)
    assert out.resolve == (name,)  # dirty → resolve lại
    out = t.resolve_done(name, resolved(name="PC2"), 10.5)
    assert out.events == (DeviceUpdated(device=device(name="PC2"), previous=device()),)
    assert no_requests(out)


def test_seen_known_device_triggers_new_resolve():
    t = DiscoveryTracker(SELF)
    name = known(t)
    out = t.service_seen(name)  # zeroconf Updated
    assert out.events == () and out.resolve == (name,) and out.probe == ()


UPPER = f"{PEER}._TELEPORT._TCP.LOCAL."


def test_seen_uppercase_suffix_resolves_canonical_name():
    t = DiscoveryTracker(SELF)
    assert t.service_seen(UPPER).resolve == (service_name(PEER),)
    assert t.resolve_done(service_name(PEER), resolved(), 0.0).events == (DeviceAdded(device()),)


def test_uppercase_suffix_while_dirty_resolves_canonical_name():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    assert t.service_seen(UPPER) == TrackerOutput()  # dirty
    assert t.resolve_done(name, resolved(), 0.0).resolve == (name,)


def test_uppercase_suffix_then_probe_uses_canonical_name():
    t = DiscoveryTracker(SELF)
    t.service_seen(UPPER)
    t.resolve_done(service_name(PEER), resolved(), 0.0)
    assert t.due_probes(15.0).probe == (service_name(PEER),)


def test_seen_is_full_then_new_candidate_ignored():
    t = DiscoveryTracker(SELF, max_services=3)
    ids = [make_id(f"p{i}") for i in range(4)]
    for i in ids[:3]:
        assert t.service_seen(service_name(i)).resolve == (service_name(i),)
    out = t.service_seen(service_name(ids[3]))
    assert out.events == () and no_requests(out) and out.notes
    # Ứng viên cũ không bị đẩy ra: vẫn nhận kết quả.
    assert t.resolve_done(service_name(ids[0]), resolved(ids[0]), 1.0).events == (
        DeviceAdded(device(ids[0])),
    )
    # Ứng viên bị từ chối chưa có yêu cầu resolve nào: kết quả tới cũng bị bỏ.
    assert t.resolve_done(service_name(ids[3]), resolved(ids[3]), 1.0).events == ()
    # Ứng viên không pending bị gone thì được xóa ngay; id đang chờ trong danh sách tràn được
    # nhận và resolve trong cùng output (đặc tả 1.3 mục 1b).
    assert t.service_gone(service_name(ids[0])).resolve == (service_name(ids[3]),)


def test_self_does_not_count_toward_limit():
    t = DiscoveryTracker(SELF, max_services=1)
    t.service_seen(service_name(SELF))
    assert t.service_seen(service_name(PEER)).resolve == (service_name(PEER),)


def test_default_limit_is_256():
    t = DiscoveryTracker(SELF)
    for i in range(256):
        name = service_name(make_id(f"n{i}"))
        assert t.service_seen(name).resolve == (name,)
    out = t.service_seen(service_name(make_id("one-too-many")))
    assert no_requests(out) and out.notes


def test_seen_known_candidate_still_accepted_when_full():
    t = DiscoveryTracker(SELF, max_services=1)
    name = known(t)
    assert t.service_seen(name).resolve == (name,)


# --- DiscoveryTracker: resolve_done --------------------------------------------------------------


def test_resolve_valid_adds_device():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    dev = device(addresses=("10.0.0.1", "10.0.0.2"))
    out = t.resolve_done(name, resolved(addresses=("10.0.0.2", "10.0.0.1", "127.0.0.1")), 5.0)
    assert out.events == (DeviceAdded(dev),)
    assert no_requests(out)
    assert dict(t.devices) == {PEER: dev}


def test_resolve_same_result_twice_emits_nothing():
    t = DiscoveryTracker(SELF)
    name = known(t)
    assert t.due_probes(15.0).probe == (name,)
    out = t.resolve_done(name, resolved(), 15.0)
    assert out.events == () and no_requests(out)


@pytest.mark.parametrize(
    "changed",
    [
        {"name": "Máy mới"},
        {"port": 47475},
        {"addresses": ("192.168.1.21",)},
        {"os": "linux"},
    ],
    ids=["name", "port", "addresses", "os"],
)
def test_resolve_changed_result_emits_updated(changed):
    t = DiscoveryTracker(SELF)
    name = known(t)
    t.service_seen(name)
    out = t.resolve_done(name, resolved(**changed), 1.0)
    new = parse_service(resolved(**changed))
    assert out.events == (DeviceUpdated(device=new, previous=device()),)
    assert t.devices[PEER] == new


def test_known_device_removed_only_after_two_failed_probes_then_comes_back():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    assert t.due_probes(15.0).probe == (name,)
    out = t.resolve_done(name, None, 15.0)
    assert out.events == () and no_requests(out)  # một lần thất bại: chống nhấp nháy
    assert t.devices[PEER] == device()
    assert no_requests(t.due_probes(29.9))
    assert t.due_probes(30.0).probe == (name,)
    out = t.resolve_done(name, None, 30.0)
    assert out.events == (DeviceRemoved(device()),)  # lần thứ hai: bỏ thiết bị
    assert PEER not in t.devices
    # Ứng viên vẫn được giữ (đã từng hợp lệ): lần kiểm sau phát hiện máy quay lại.
    assert no_requests(t.due_probes(44.9))
    assert t.due_probes(45.0).probe == (name,)
    assert t.resolve_done(name, resolved(), 45.0).events == (DeviceAdded(device()),)


def test_valid_result_resets_failure_count():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    t.due_probes(15.0)
    assert t.resolve_done(name, None, 15.0).events == ()
    t.due_probes(30.0)
    assert t.resolve_done(name, resolved(), 30.0).events == ()
    t.due_probes(45.0)
    assert t.resolve_done(name, None, 45.0).events == ()  # đếm lại từ 0: chưa Removed
    assert PEER in t.devices


def test_invalid_record_on_known_device_counts_as_alive():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    t.due_probes(15.0)
    assert t.resolve_done(name, None, 15.0).events == ()
    t.due_probes(30.0)
    out = t.resolve_done(name, resolved(txt=good_txt(os=b"Windows")), 30.0)
    assert out.events == () and out.notes  # bản sai: giữ bản cũ, failures = 0
    t.due_probes(45.0)
    assert t.resolve_done(name, None, 45.0).events == ()  # None, sai, None → chưa Removed
    assert t.devices[PEER] == device()
    t.due_probes(60.0)
    assert t.resolve_done(name, None, 60.0).events == (DeviceRemoved(device()),)


def test_resolve_invalid_keeps_previous_valid_device():
    t = DiscoveryTracker(SELF)
    name = known(t)
    t.service_seen(name)
    out = t.resolve_done(name, resolved(txt=good_txt(os=b"Windows")), 1.0)
    assert out.events == () and no_requests(out)
    assert out.notes
    assert t.devices[PEER] == device()


@pytest.mark.parametrize("second", ["none", "bad"])
@pytest.mark.parametrize("first", ["none", "bad"])
def test_never_valid_candidate_dropped_after_two_failures(first, second):
    def result(kind):
        return None if kind == "none" else resolved(txt=good_txt(os=b"Windows"))

    t = DiscoveryTracker(SELF, max_services=1)
    name = service_name(PEER)
    t.service_seen(name)
    out = t.resolve_done(name, result(first), 0.0)
    assert out.events == () and no_requests(out) and out.notes
    # Lần thất bại đầu: vẫn là ứng viên, vẫn chiếm chỗ (PEER2 vào danh sách tràn) và vẫn được kiểm.
    assert no_requests(t.service_seen(service_name(PEER2)))
    assert t.due_probes(15.0).probe == (name,)
    out = t.resolve_done(name, result(second), 15.0)
    assert out.events == () and out.probe == () and out.notes
    # Lần thứ hai: ứng viên bị xóa, chỗ được giải phóng và trao ngay cho PEER2 đang chờ.
    assert out.resolve == (service_name(PEER2),)
    assert dict(t.devices) == {}
    assert no_requests(t.due_probes(1e6))


def test_never_valid_candidate_dropped_after_two_failures_even_when_dirty():
    # Review lần 2: không còn ngoại lệ cho ứng viên đang dirty.
    t = DiscoveryTracker(SELF, max_services=1)
    name = service_name(PEER)
    t.service_seen(name)
    assert t.resolve_done(name, None, 0.0).events == ()  # thất bại lần 1
    assert t.due_probes(15.0).probe == (name,)
    assert t.service_seen(name) == TrackerOutput()  # đang pending → dirty
    out = t.resolve_done(name, None, 15.0)  # thất bại lần 2
    assert out.events == () and no_requests(out), "ứng viên bị xóa thì không resolve lại dù dirty"
    assert out.notes
    assert dict(t.devices) == {}
    assert no_requests(t.due_probes(1e6))
    # Chỗ trong max_services được giải phóng.
    assert t.service_seen(service_name(PEER2)).resolve == (service_name(PEER2),)


def test_ever_valid_candidate_without_device_is_kept_after_more_failures():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = 0.0
    for _ in range(2):  # None, None → Removed
        now += 15.0
        t.due_probes(now)
        t.resolve_done(name, None, now)
    assert PEER not in t.devices
    # Thêm nhiều lần thất bại: vẫn giữ và vẫn kiểm, theo khoảng thưa dần (mục 1c).
    for gap in (15.0, 30.0, 60.0, 120.0):
        now += gap
        assert t.due_probes(now).probe == (name,)
        assert t.resolve_done(name, None, now).events == ()
    now += 240.0
    assert t.due_probes(now).probe == (name,)
    assert t.resolve_done(name, resolved(), now).events == (DeviceAdded(device()),)


@pytest.mark.parametrize(
    "bad",
    [
        resolved(txt=good_txt(os=b"Windows")),
        resolved(txt=txt_bytes(PEER2)),
        resolved(port=0),
        resolved(addresses=("127.0.0.1",)),
    ],
    ids=["bad_os", "id_mismatch", "port0", "loopback_only"],
)
def test_resolve_invalid_without_device_only_notes(bad):
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    out = t.resolve_done(name, bad, 1.0)
    assert out.events == () and no_requests(out)
    assert out.notes
    assert dict(t.devices) == {}


def test_resolve_for_unknown_or_not_pending_name_is_ignored():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    assert t.resolve_done(name, resolved(), 1.0).events == ()
    assert dict(t.devices) == {}
    t.service_seen(name)
    t.resolve_done(name, resolved(), 2.0)
    # Gọi thêm lần nữa khi không còn pending: bỏ qua.
    out = t.resolve_done(name, resolved(name="Khác"), 3.0)
    assert out.events == () and no_requests(out)
    assert t.devices[PEER] == device()


# --- DiscoveryTracker: service_gone --------------------------------------------------------------


def test_gone_removes_known_device():
    t = DiscoveryTracker(SELF)
    name = known(t)
    out = t.service_gone(name)
    assert out.events == (DeviceRemoved(device()),)
    assert dict(t.devices) == {}
    assert no_requests(t.due_probes(1e6))


def test_gone_unknown_emits_nothing():
    t = DiscoveryTracker(SELF)
    assert t.service_gone(service_name(PEER)).events == ()
    assert t.service_gone("notanid._teleport._tcp.local.").events == ()
    assert t.service_gone(service_name(SELF)).events == ()


def test_gone_while_pending_then_late_result_is_dropped_and_candidate_deleted():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    out = t.service_gone(name)
    assert out.events == () and no_requests(out)
    out = t.resolve_done(name, resolved(), 1.0)
    assert out.events == () and no_requests(out)
    assert out.notes
    assert dict(t.devices) == {}
    assert no_requests(t.due_probes(1e6))
    # Đã xóa hẳn: thấy lại là ứng viên mới.
    assert t.service_seen(name).resolve == (name,)


def test_gone_while_pending_with_device_removes_device_immediately():
    t = DiscoveryTracker(SELF)
    name = known(t)
    assert t.service_seen(name).resolve == (name,)  # pending
    out = t.service_gone(name)
    assert out.events == (DeviceRemoved(device()),)
    assert no_requests(out)
    assert dict(t.devices) == {}
    # Kết quả của resolve cũ tới muộn: bỏ, không Added lại.
    out = t.resolve_done(name, resolved(), 1.0)
    assert out.events == () and no_requests(out)
    assert dict(t.devices) == {}


def test_gone_then_seen_while_pending_never_requests_second_resolve():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    assert t.service_seen(name).resolve == (name,)
    t.service_gone(name)
    out = t.service_seen(name)  # quay lại khi resolve cũ vẫn đang chạy
    assert out.events == () and no_requests(out)
    for _ in range(3):  # lặp gone/seen: vẫn không có yêu cầu thứ hai
        assert no_requests(t.service_gone(name))
        assert no_requests(t.service_seen(name))
    assert no_requests(t.due_probes(1e6))
    # Kết quả của resolve cũ bị bỏ (có thể là dữ liệu trước khi đi), rồi yêu cầu resolve mới.
    out = t.resolve_done(name, resolved(name="Cũ"), 1.0)
    assert out.events == ()
    assert out.notes
    assert out.resolve == (name,)
    assert dict(t.devices) == {}
    # Kết quả của resolve mới cho dữ liệu mới.
    out = t.resolve_done(name, resolved(name="Mới"), 2.0)
    assert out.events == (DeviceAdded(device(name="Mới")),)
    assert no_requests(out)


def test_gone_then_seen_with_device_drops_old_result_and_readds():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0, name="Cũ")
    assert t.due_probes(15.0).probe == (name,)
    assert t.service_gone(name).events == (DeviceRemoved(device(name="Cũ")),)
    assert no_requests(t.service_seen(name))
    out = t.resolve_done(name, resolved(name="Cũ"), 16.0)
    assert out.events == () and out.resolve == (name,)
    assert t.resolve_done(name, resolved(name="Mới"), 17.0).events == (DeviceAdded(device(name="Mới")),)


def test_tombstone_counts_toward_limit_until_resolved():
    t = DiscoveryTracker(SELF, max_services=1)
    name = service_name(PEER)
    t.service_seen(name)
    t.service_gone(name)  # bia mộ: vẫn pending, vẫn chiếm chỗ
    out = t.service_seen(service_name(PEER2))
    assert no_requests(out) and out.notes
    # Bia mộ được xóa: PEER2 (đang trong danh sách tràn) được nhận trong cùng output.
    assert t.resolve_done(name, None, 1.0).resolve == (service_name(PEER2),)


def test_gone_while_dirty_cancels_reresolve():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    t.service_seen(name)  # dirty
    t.service_gone(name)
    out = t.resolve_done(name, resolved(), 1.0)
    assert out.events == () and no_requests(out)
    assert no_requests(t.due_probes(1e6))


def test_device_can_be_added_again_after_gone():
    t = DiscoveryTracker(SELF)
    name = known(t)
    t.service_gone(name)
    assert t.service_seen(name).resolve == (name,)
    assert t.resolve_done(name, resolved(), 1.0).events == (DeviceAdded(device()),)


# --- DiscoveryTracker: due_probes ----------------------------------------------------------------


def test_due_probes_boundary_at_probe_interval():
    t = DiscoveryTracker(SELF)
    name = known(t, 1000.0)
    assert no_requests(t.due_probes(1014.9))
    out = t.due_probes(1015.0)
    assert out.probe == (name,)
    assert out.resolve == () and out.events == ()
    # Đã pending: không yêu cầu lần nữa.
    assert no_requests(t.due_probes(1015.0))
    assert no_requests(t.due_probes(2000.0))


def test_due_probes_skips_pending_candidate_never_resolved():
    t = DiscoveryTracker(SELF)
    t.service_seen(service_name(PEER))
    assert no_requests(t.due_probes(1e6))


def test_due_probes_sorted_by_device_id():
    t = DiscoveryTracker(SELF)
    ids = sorted((make_id(f"s{i}") for i in range(5)), reverse=True)
    for i in ids:
        t.service_seen(service_name(i))
        t.resolve_done(service_name(i), resolved(i), 0.0)
    out = t.due_probes(15.0)
    assert out.probe == tuple(service_name(i) for i in sorted(ids))
    assert out.resolve == () and out.events == ()


def test_due_probes_uses_custom_interval():
    t = DiscoveryTracker(SELF, probe_interval=2.0)
    name = known(t, 0.0)
    assert no_requests(t.due_probes(1.99))
    assert t.due_probes(2.0).probe == (name,)


def test_due_probes_counts_from_last_attempt_even_if_failed():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    t.resolve_done(name, resolved(txt={}), 7.0)  # thất bại lần đầu: vẫn giữ ứng viên
    assert no_requests(t.due_probes(21.9))
    assert t.due_probes(22.0).probe == (name,)


# --- DiscoveryTracker: ưu tiên thiết bị đã ghép đôi (bước 1.3, mục 1a) ---------------------------

PRIO = make_id("prio")
PRIO2 = make_id("prio2")
PRIO3 = make_id("prio3")
A = make_id("a")
B = make_id("b")


def svc(device_id: str) -> str:
    return service_name(device_id)


def test_priority_candidate_accepted_when_full():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO])
    known(t, 0.0, A)
    out = t.service_seen(svc(PRIO))
    assert out.resolve == (svc(PRIO),) and out.events == ()
    assert t.resolve_done(svc(PRIO), resolved(PRIO), 1.0).events == (DeviceAdded(device(PRIO)),)
    # Ứng viên không ưu tiên vẫn bị chặn ở giới hạn.
    assert no_requests(t.service_seen(svc(B)))


def test_priority_candidates_do_not_count_toward_limit():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO, PRIO2, PRIO3])
    for pid in (PRIO, PRIO2, PRIO3):
        known(t, 0.0, pid)
    # Ba ứng viên ưu tiên, 0 ứng viên thường: vẫn còn đúng một chỗ cho ứng viên thường.
    assert t.service_seen(svc(A)).resolve == (svc(A),)
    out = t.service_seen(svc(B))
    assert no_requests(out) and out.notes


def test_set_priority_accepts_new_priority_when_full():
    t = DiscoveryTracker(SELF, max_services=1)
    known(t, 0.0, A)
    out = t.set_priority([PRIO])
    assert isinstance(out, TrackerOutput)
    assert out.events == () and no_requests(out)  # PRIO chưa từng thấy: chưa có gì để resolve
    assert t.service_seen(svc(PRIO)).resolve == (svc(PRIO),)


def test_set_priority_accepts_any_iterable():
    t = DiscoveryTracker(SELF, max_services=1)
    known(t, 0.0, A)
    t.set_priority(i for i in [PRIO])
    assert t.service_seen(svc(PRIO)).resolve == (svc(PRIO),)


def test_set_priority_admits_id_waiting_in_overflow():
    t = DiscoveryTracker(SELF, max_services=1)
    known(t, 0.0, A)
    assert no_requests(t.service_seen(svc(PRIO)))  # đầy: vào danh sách tràn
    out = t.set_priority([PRIO])
    assert out.resolve == (svc(PRIO),)
    assert out.events == () and out.probe == ()
    assert t.resolve_done(svc(PRIO), resolved(PRIO), 1.0).events == (DeviceAdded(device(PRIO)),)
    # PRIO đã rời danh sách tràn: chỗ trống sau đó không yêu cầu resolve nó lần nữa.
    assert no_requests(t.service_gone(svc(A)))


def test_set_priority_replaces_the_whole_set():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO])
    known(t, 0.0, A)
    t.set_priority([PRIO2])
    # PRIO không còn ưu tiên: bị chặn ở giới hạn như ứng viên thường.
    out = t.service_seen(svc(PRIO))
    assert no_requests(out) and out.notes
    assert t.service_seen(svc(PRIO2)).resolve == (svc(PRIO2),)


def test_set_priority_on_pending_candidate_does_not_request_second_resolve():
    t = DiscoveryTracker(SELF, max_services=1)
    assert t.service_seen(svc(A)).resolve == (svc(A),)  # đang pending
    out = t.set_priority([A])
    assert no_requests(out) and out.events == ()
    assert t.resolve_done(svc(A), resolved(A), 1.0).events == (DeviceAdded(device(A)),)


@pytest.mark.parametrize("bad", ["", PEER.upper(), PEER[:-1], PEER + "0", None, 123, PEER.encode()], ids=repr)
def test_set_priority_rejects_invalid_id_and_keeps_state(bad):
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO])
    known(t, 0.0, A)
    assert no_requests(t.service_seen(svc(B)))  # B trong danh sách tràn
    with pytest.raises(MessageError):
        t.set_priority([B, PRIO2, bad])
    # Không đổi gì: B không được nhận (vẫn chờ), PRIO vẫn ưu tiên, PRIO2 chưa ưu tiên.
    assert no_requests(t.service_seen(svc(PRIO2)))
    assert t.service_seen(svc(PRIO)).resolve == (svc(PRIO),)
    assert t.service_gone(svc(A)).resolve == (svc(B),)


def test_set_priority_with_a_bare_string_raises():
    # Một chuỗi là Iterable[str] gồm các ký tự đơn: không ký tự nào là device_id hợp lệ.
    t = DiscoveryTracker(SELF)
    with pytest.raises(MessageError):
        t.set_priority(PRIO)


@pytest.mark.parametrize("bad", ["", PEER.upper(), None], ids=repr)
def test_constructor_rejects_invalid_priority_id(bad):
    with pytest.raises(ValueError):
        DiscoveryTracker(SELF, priority_ids=[PRIO, bad])


def test_self_id_in_priority_is_ignored():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[SELF])
    out = t.set_priority([SELF, PRIO])
    assert out.events == () and no_requests(out)
    out = t.service_seen(svc(SELF))
    assert out.events == () and no_requests(out) and out.notes
    assert SELF not in t.devices
    # Máy này không chiếm chỗ: vẫn còn chỗ cho một ứng viên thường.
    assert t.service_seen(svc(A)).resolve == (svc(A),)
    assert no_requests(t.due_probes(1e6))


def test_demoted_candidate_is_kept_but_blocks_new_regular_candidates():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO])
    known(t, 0.0, PRIO)
    known(t, 0.0, A)  # ứng viên thường duy nhất: đầy
    out = t.set_priority([])
    # Thôi ưu tiên: không đẩy ra, không có sự kiện.
    assert out.events == () and no_requests(out)
    assert set(t.devices) == {PRIO, A}
    # Hai ứng viên thường > giới hạn 1: ứng viên mới phải chờ.
    out = t.service_seen(svc(B))
    assert no_requests(out) and out.notes
    # Vẫn kiểm còn sống cả hai.
    assert set(t.due_probes(15.0).probe) == {svc(PRIO), svc(A)}
    t.resolve_done(svc(PRIO), resolved(PRIO), 15.0)
    t.resolve_done(svc(A), resolved(A), 15.0)
    # Xóa A: còn 1 ứng viên thường = giới hạn, chưa có chỗ cho B.
    assert t.service_gone(svc(A)).resolve == ()
    # Xóa PRIO: 0 < 1, B được nhận.
    out = t.service_gone(svc(PRIO))
    assert out.events == (DeviceRemoved(device(PRIO)),)
    assert out.resolve == (svc(B),)


def test_demoting_many_candidates_evicts_none():
    ids = [PRIO, PRIO2, PRIO3]
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=ids)
    for pid in ids:
        known(t, 0.0, pid)
    out = t.set_priority([])
    assert out.events == () and no_requests(out)
    assert set(t.devices) == set(ids)
    assert set(t.due_probes(15.0).probe) == {svc(i) for i in ids}


def test_gone_priority_device_is_removed_and_can_return_when_full():
    t = DiscoveryTracker(SELF, max_services=1, priority_ids=[PRIO])
    known(t, 0.0, A)
    known(t, 0.0, PRIO)
    assert t.service_gone(svc(PRIO)).events == (DeviceRemoved(device(PRIO)),)
    assert t.service_seen(svc(PRIO)).resolve == (svc(PRIO),)


def test_promoting_tracked_regular_candidate_admits_oldest_overflow_at_once():
    # Nâng một ứng viên thường lên ưu tiên làm trống một chỗ: id cũ nhất trong danh sách tràn
    # được nhận ngay trong output của set_priority (PR-1 bổ sung, mục C).
    t = DiscoveryTracker(SELF, max_services=1)
    known(t, 0.0, A)
    assert no_requests(t.service_seen(svc(B)))  # tràn, cũ nhất
    assert no_requests(t.service_seen(svc(PRIO2)))  # tràn, mới hơn
    out = t.set_priority([A])
    assert out.events == () and out.probe == ()
    assert out.resolve == (svc(B),)
    # Đã đầy lại (B là ứng viên thường duy nhất): PRIO2 vẫn chờ.
    out = t.service_seen(svc(PRIO2))
    assert no_requests(out) and out.notes
    assert set(t.devices) == {A}


# --- DiscoveryTracker.is_priority (PR-1 bổ sung, mục A) --------------------------------------------


def test_is_priority_true_for_ids_given_to_constructor():
    t = DiscoveryTracker(SELF, priority_ids=[PRIO, PRIO2])
    assert t.is_priority(PRIO) is True
    assert t.is_priority(PRIO2) is True


def test_is_priority_false_for_regular_id():
    t = DiscoveryTracker(SELF, priority_ids=[PRIO])
    assert t.is_priority(A) is False
    known(t, 0.0, A)  # đang theo dõi nhưng không ưu tiên
    assert t.is_priority(A) is False


def test_is_priority_follows_set_priority():
    t = DiscoveryTracker(SELF, priority_ids=[PRIO])
    t.set_priority([PRIO2])
    assert t.is_priority(PRIO) is False
    assert t.is_priority(PRIO2) is True
    t.set_priority([])
    assert t.is_priority(PRIO2) is False


def test_is_priority_unchanged_after_rejected_set_priority():
    t = DiscoveryTracker(SELF, priority_ids=[PRIO])
    with pytest.raises(MessageError):
        t.set_priority([PRIO2, "bad"])
    assert t.is_priority(PRIO) is True
    assert t.is_priority(PRIO2) is False


def test_is_priority_false_for_self_even_when_listed():
    t = DiscoveryTracker(SELF, priority_ids=[SELF, PRIO])
    assert t.is_priority(SELF) is False
    t.set_priority([SELF])
    assert t.is_priority(SELF) is False


@pytest.mark.parametrize(
    "bad",
    ["", "bad", PRIO.upper(), PRIO[:-1], PRIO + "0", svc(PRIO), "x" * 10_000, None, 123, PRIO.encode()],
    ids=repr,
)
def test_is_priority_false_for_invalid_id_without_raising(bad):
    t = DiscoveryTracker(SELF, priority_ids=[PRIO])
    assert t.is_priority(bad) is False


# --- DiscoveryTracker: danh sách tràn (bước 1.3, mục 1b) -----------------------------------------


def test_max_overflow_names_constant():
    assert core_discovery.MAX_OVERFLOW_NAMES == 1024


def full_tracker(max_services: int = 1) -> DiscoveryTracker:
    """Tracker đã theo dõi đủ `max_services` thiết bị hợp lệ (id make_id('full<i>')), không pending."""
    t = DiscoveryTracker(SELF, max_services=max_services)
    for i in range(max_services):
        known(t, 0.0, make_id(f"full{i}"))
    return t


FULL0 = make_id("full0")
FULL1 = make_id("full1")
X = [make_id(f"x{i}") for i in range(5)]


def test_overflow_seen_when_full_returns_note_and_no_request():
    t = full_tracker()
    out = t.service_seen(svc(X[0]))
    assert out.events == () and no_requests(out) and out.notes


def test_overflow_admitted_in_same_output_when_device_gone():
    t = full_tracker()
    t.service_seen(svc(X[0]))
    out = t.service_gone(svc(FULL0))
    assert out.events == (DeviceRemoved(device(FULL0)),)
    assert out.resolve == (svc(X[0]),) and out.probe == ()
    assert t.resolve_done(svc(X[0]), resolved(X[0]), 1.0).events == (DeviceAdded(device(X[0])),)


def test_overflow_admitted_when_tombstone_resolves():
    t = DiscoveryTracker(SELF, max_services=1)
    t.service_seen(svc(A))  # pending
    t.service_seen(svc(X[0]))  # tràn
    out = t.service_gone(svc(A))
    assert no_requests(out), "bia mộ vẫn chiếm chỗ tới khi resolve của nó trả về"
    out = t.resolve_done(svc(A), resolved(A), 1.0)
    assert out.events == ()
    assert out.resolve == (svc(X[0]),)


@pytest.mark.parametrize("kind", ["none", "bad"])
def test_overflow_admitted_when_never_valid_candidate_dropped(kind):
    def result():
        return None if kind == "none" else resolved(A, txt=txt_bytes(A) | {b"os": b"Windows"})

    t = DiscoveryTracker(SELF, max_services=1)
    t.service_seen(svc(A))
    assert no_requests(t.resolve_done(svc(A), result(), 0.0))
    t.service_seen(svc(X[0]))  # tràn
    assert t.due_probes(15.0).probe == (svc(A),)
    out = t.resolve_done(svc(A), result(), 15.0)
    assert out.events == () and out.notes
    assert out.resolve == (svc(X[0]),)


def test_overflow_admitted_when_dirty_never_valid_candidate_dropped():
    t = DiscoveryTracker(SELF, max_services=1)
    t.service_seen(svc(A))
    t.resolve_done(svc(A), None, 0.0)
    t.service_seen(svc(X[0]))  # tràn
    t.due_probes(15.0)
    assert t.service_seen(svc(A)) == TrackerOutput()  # dirty
    out = t.resolve_done(svc(A), None, 15.0)
    assert out.resolve == (svc(X[0]),), "A bị bỏ (không resolve lại dù dirty), X0 được nhận"


def test_overflow_is_fifo_and_stale_entries_give_way():
    # Phần tử tràn đã cũ (dịch vụ mất không goodbye) resolve thất bại 2 lần rồi nhường chỗ cho phần tử sau.
    t = full_tracker()
    for x in X[:3]:
        assert no_requests(t.service_seen(svc(x)))
    out = t.service_gone(svc(FULL0))
    assert out.resolve == (svc(X[0]),)
    assert no_requests(t.resolve_done(svc(X[0]), None, 0.0))
    assert t.due_probes(15.0).probe == (svc(X[0]),)
    out = t.resolve_done(svc(X[0]), None, 15.0)
    assert out.resolve == (svc(X[1]),)
    assert no_requests(t.resolve_done(svc(X[1]), None, 15.0))
    assert t.due_probes(30.0).probe == (svc(X[1]),)
    assert t.resolve_done(svc(X[1]), None, 30.0).resolve == (svc(X[2]),)


def cycle_out(t: DiscoveryTracker, current: str, now: float = 1.0) -> tuple[str, ...]:
    """Cho `current` (đang pending) có bản ghi hợp lệ rồi bị gone; trả các tên được nhận thêm."""
    t.resolve_done(svc(current), resolved(current), now)
    return t.service_gone(svc(current)).resolve


def test_overflow_duplicate_keeps_original_position():
    t = full_tracker()
    t.service_seen(svc(X[0]))
    t.service_seen(svc(X[1]))
    t.service_seen(svc(X[0]))  # đã có: giữ vị trí, không dồn xuống cuối
    assert t.service_gone(svc(FULL0)).resolve == (svc(X[0]),)
    assert cycle_out(t, X[0]) == (svc(X[1]),)
    assert cycle_out(t, X[1]) == (), "X0 không được nằm hai lần trong danh sách tràn"


def test_overflow_uppercase_suffix_is_admitted_with_canonical_name():
    t = full_tracker()
    t.service_seen(f"{X[0]}._TELEPORT._TCP.LOCAL.")
    t.service_seen(svc(X[0]))  # cùng device_id: không trùng
    assert t.service_gone(svc(FULL0)).resolve == (svc(X[0]),)
    assert cycle_out(t, X[0]) == ()


def test_gone_removes_id_from_overflow_silently():
    t = full_tracker()
    t.service_seen(svc(X[0]))
    t.service_seen(svc(X[1]))
    out = t.service_gone(svc(X[0]))
    assert out.events == () and no_requests(out)
    assert t.service_gone(svc(FULL0)).resolve == (svc(X[1]),)
    assert cycle_out(t, X[1]) == ()


def test_overflow_never_holds_self_or_invalid_names():
    t = full_tracker()
    for name in (svc(SELF), f"{SELF}._TELEPORT._TCP.LOCAL.", "notanid._teleport._tcp.local.", ""):
        assert no_requests(t.service_seen(name))
    assert t.service_gone(svc(FULL0)).resolve == ()
    assert SELF not in t.devices


def test_overflow_admits_one_per_freed_slot():
    t = full_tracker(2)
    for x in X[:3]:
        t.service_seen(svc(x))
    assert t.service_gone(svc(FULL0)).resolve == (svc(X[0]),)
    assert t.service_gone(svc(FULL1)).resolve == (svc(X[1]),)
    # Đầy lại: X2 vẫn chờ.
    assert no_requests(t.service_seen(svc(X[3])))


def test_overflow_keeps_newest_1024_and_drops_oldest():
    t = full_tracker()
    waiting = [make_id(f"o{i}") for i in range(1025)]
    for w in waiting:
        out = t.service_seen(svc(w))
        assert no_requests(out) and out.notes
    admitted = list(t.service_gone(svc(FULL0)).resolve)
    current = waiting[1]
    for _ in range(1100):
        more = cycle_out(t, current)
        if not more:
            break
        admitted.extend(more)
        current = device_id_from_service_name(more[-1])
    assert admitted == [svc(w) for w in waiting[1:]], "giữ 1024 phần tử mới nhất, theo FIFO"


def test_overflow_entry_seen_again_after_admission_is_not_duplicated():
    t = full_tracker()
    t.service_seen(svc(X[0]))
    assert t.service_gone(svc(FULL0)).resolve == (svc(X[0]),)
    assert t.service_seen(svc(X[0])) == TrackerOutput()  # đang pending → dirty
    out = t.resolve_done(svc(X[0]), resolved(X[0]), 1.0)
    assert out.events == (DeviceAdded(device(X[0])),)
    assert out.resolve == (svc(X[0]),)


# --- DiscoveryTracker: probe thưa dần cho thiết bị đã chết (bước 1.3, mục 1c) ---------------------


def test_max_probe_backoff_constant():
    assert core_discovery.MAX_PROBE_BACKOFF == 240.0


def kill_by_probes(t: DiscoveryTracker, name: str, start: float, interval: float = PROBE_INTERVAL) -> float:
    """Thiết bị đang hiện (resolve gần nhất ở `start`) thất bại 2 lần → DeviceRemoved; trả `now` cuối."""
    now = start
    for i in range(MAX_RESOLVE_FAILURES):
        now += interval
        assert t.due_probes(now).probe == (name,)
        out = t.resolve_done(name, None, now)
        if i == MAX_RESOLVE_FAILURES - 1:
            assert len(out.events) == 1 and isinstance(out.events[0], DeviceRemoved)
    return now


def expect_gaps(t: DiscoveryTracker, name: str, now: float, gaps, eps: float = 0.01) -> float:
    """Mỗi khoảng trong `gaps`: chưa đến hạn ở `now + gap - eps`, đến hạn đúng ở `now + gap`, rồi thất bại."""
    for gap in gaps:
        assert no_requests(t.due_probes(now + gap - eps)), f"probe sớm hơn khoảng {gap} s"
        now += gap
        assert t.due_probes(now).probe == (name,), f"không probe sau khoảng {gap} s"
        assert t.resolve_done(name, None, now).events == ()
    return now


def test_dead_device_probe_interval_doubles_up_to_240():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0)
    expect_gaps(t, name, now, [15.0, 30.0, 60.0, 120.0, 240.0, 240.0, 240.0])


def test_dead_device_backoff_with_small_interval_caps_at_240():
    t = DiscoveryTracker(SELF, probe_interval=2.0)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0, interval=2.0)
    expect_gaps(t, name, now, [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 240.0, 240.0])


def test_dead_device_backoff_starts_from_custom_interval():
    t = DiscoveryTracker(SELF, probe_interval=100.0)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0, interval=100.0)
    expect_gaps(t, name, now, [100.0, 200.0, 240.0, 240.0])


def test_valid_record_resets_backoff_and_device_is_probed_every_interval_again():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0)
    now = expect_gaps(t, name, now, [15.0, 30.0, 60.0, 120.0])  # khoảng kế tiếp sẽ là 240
    now += 240.0
    assert t.due_probes(now).probe == (name,)
    assert t.resolve_done(name, resolved(), now).events == (DeviceAdded(device()),)
    # Thiết bị đang hiện: về nhịp 15 s.
    for _ in range(3):
        assert no_requests(t.due_probes(now + 14.99))
        now += 15.0
        assert t.due_probes(now).probe == (name,)
        assert t.resolve_done(name, resolved(), now).events == ()
    # Chết lần nữa: khoảng thưa dần bắt đầu lại từ 15, không nối tiếp 240 cũ.
    now = kill_by_probes(t, name, now)
    expect_gaps(t, name, now, [15.0, 30.0])


def test_service_seen_resets_backoff_and_resolves_at_once():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0)
    now = expect_gaps(t, name, now, [15.0, 30.0, 60.0])  # khoảng kế tiếp sẽ là 120
    out = t.service_seen(name)  # zeroconf báo Added/Updated
    assert out.resolve == (name,), "service_seen phải resolve ngay, không chờ hết khoảng thưa"
    now += 5.0
    assert t.resolve_done(name, None, now).events == ()
    # Khoảng đã về probe_interval (lần thất bại này có thể nhân đôi một lần: tối đa 30 s), không còn 120.
    assert no_requests(t.due_probes(now + 14.99))
    assert t.due_probes(now + 30.0).probe == (name,)


def test_service_seen_with_valid_record_restores_device_and_normal_cadence():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = kill_by_probes(t, name, 0.0)
    now = expect_gaps(t, name, now, [15.0, 30.0, 60.0, 120.0])
    assert t.service_seen(name).resolve == (name,)
    now += 1.0
    assert t.resolve_done(name, resolved(), now).events == (DeviceAdded(device()),)
    assert no_requests(t.due_probes(now + 14.99))
    assert t.due_probes(now + 15.0).probe == (name,)


def test_live_device_is_probed_every_interval_without_backoff():
    t = DiscoveryTracker(SELF)
    name = known(t, 0.0)
    now = 0.0
    for i in range(20):
        assert no_requests(t.due_probes(now + 14.99))
        now += 15.0
        assert t.due_probes(now).probe == (name,)
        # Xen kẽ một lần thất bại (vẫn còn thiết bị): nhịp vẫn là 15 s.
        result = None if i % 2 == 0 else resolved()
        assert t.resolve_done(name, result, now).events == ()
    assert PEER in t.devices


def test_never_valid_candidate_is_not_backed_off():
    t = DiscoveryTracker(SELF)
    name = service_name(PEER)
    t.service_seen(name)
    t.resolve_done(name, None, 0.0)
    assert no_requests(t.due_probes(14.99))
    assert t.due_probes(15.0).probe == (name,)


# --- DiscoveryTracker: hypothesis chuỗi thao tác ngẫu nhiên --------------------------------------

POOL = [make_id(f"h{i}") for i in range(6)]
VARIANTS = ["none", "v1", "v2", "bad", "mismatch"]


def variant_result(device_id: str, variant: str) -> ResolvedService | None:
    if variant == "none":
        return None
    if variant == "v1":
        return resolved(device_id, name="Một", addresses=("10.0.0.1",))
    if variant == "v2":
        return resolved(device_id, name="Hai", port=5000, addresses=("10.0.0.2", "10.0.0.1"))
    if variant == "bad":
        return resolved(device_id, txt=txt_bytes(device_id, os="x") | {b"os": b"Windows"})
    other = POOL[(POOL.index(device_id) + 1) % len(POOL)]
    return resolved(device_id, txt=txt_bytes(other))


ops = st.lists(
    st.one_of(
        st.tuples(st.just("seen"), st.sampled_from([*POOL, SELF, "bad"])),
        st.tuples(st.just("seen_upper"), st.sampled_from(POOL)),
        st.tuples(st.just("gone"), st.sampled_from([*POOL, SELF, "bad"])),
        st.tuples(st.just("done"), st.integers(0, 50), st.sampled_from(VARIANTS)),
        st.tuples(st.just("stray"), st.sampled_from(POOL), st.sampled_from(VARIANTS)),
        st.tuples(
            st.just("probe"),
            st.floats(min_value=0.0, max_value=20.0, allow_nan=False)
            | st.floats(min_value=0.0, max_value=300.0, allow_nan=False),
        ),
        st.tuples(st.just("prio"), st.frozensets(st.sampled_from([*POOL, SELF]))),
        st.tuples(st.just("prio_bad"), st.frozensets(st.sampled_from(POOL))),
    ),
    max_size=80,
)


def _svc(key: str) -> str:
    return "notanid._teleport._tcp.local." if key == "bad" else service_name(key)


def _tracked_ids(t: DiscoveryTracker) -> set[str]:
    """Nội bộ: device_id của mọi ứng viên (kể cả bia mộ).

    Chỉ dùng để kiểm bất biến không quan sát được từ ngoài.
    """
    candidates = getattr(t, "_candidates", None)
    assert candidates is not None, "test cần thuộc tính nội bộ `_candidates` để kiểm bất biến"
    return set(candidates)


def _overflow_ids(t: DiscoveryTracker) -> list[str]:
    """Nội bộ: danh sách tràn theo thứ tự (phần tử là device_id hoặc tên dịch vụ)."""
    overflow = getattr(t, "_overflow", None)
    assert overflow is not None, "test cần thuộc tính nội bộ `_overflow` để kiểm bất biến"
    return [device_id_from_service_name(x) or x for x in overflow]


@pytest.mark.slow
@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(ops, st.integers(1, 4), st.frozensets(st.sampled_from([*POOL, SELF])))
def test_property_tracker_invariants(steps, max_services, initial_priority):
    """Mô phỏng net theo hợp đồng 2.4 + 7.1/7.4: mỗi tên trong `resolve`/`probe` được trả lời đúng
    một lần bằng `resolve_done`, theo thứ tự tùy ý, xen kẽ với seen/gone/due_probes/set_priority.

    Bất biến (bước 1.3): số ứng viên không ưu tiên ≤ max_services (chỉ được tạm vượt ngay sau khi
    thôi ưu tiên, và khi đang vượt thì không tăng); thiết bị ưu tiên luôn được nhận; danh sách tràn
    ≤ 1024, không trùng, không chứa id đang theo dõi, máy này hay id ưu tiên.
    """
    t = DiscoveryTracker(SELF, max_services=max_services, priority_ids=initial_priority)
    priority = set(initial_priority) - {SELF}
    now = 100.0
    # device_id → tên đang được net resolve. Chỉ xóa khi net đã gọi resolve_done cho yêu cầu đó:
    # service_gone KHÔNG hủy một resolve đang chạy.
    outstanding: dict[str, str] = {}
    model: dict[str, DiscoveredDevice] = {}
    cap = max_services  # giới hạn hiện hành cho số ứng viên không ưu tiên

    def apply(out: TrackerOutput) -> None:
        assert isinstance(out, TrackerOutput)
        for ev in out.events:
            if isinstance(ev, DeviceAdded):
                assert ev.device.device_id not in model, "Added hai lần không có Removed ở giữa"
                model[ev.device.device_id] = ev.device
            elif isinstance(ev, DeviceUpdated):
                did = ev.device.device_id
                assert model.get(did) == ev.previous, "Updated.previous phải là bản đã biết"
                assert ev.device != ev.previous
                assert ev.previous.device_id == did
                model[did] = ev.device
            else:
                assert isinstance(ev, DeviceRemoved)
                assert model.pop(ev.device.device_id) == ev.device, "Removed phải mang bản cuối đã biết"
        for name in (*out.resolve, *out.probe):
            did = device_id_from_service_name(name)
            assert did is not None and did != SELF
            assert name == service_name(did), "phải dùng tên chuẩn"
            assert did not in outstanding, f"hai yêu cầu resolve cùng lúc cho {did}"
            outstanding[did] = name
        assert dict(t.devices) == model, "áp tuần tự sự kiện phải dựng lại đúng devices"
        assert SELF not in t.devices

    def check_structure(*, new_cap_allowed: bool = False) -> None:
        nonlocal cap
        tracked = _tracked_ids(t)
        over = _overflow_ids(t)
        assert len(over) <= core_discovery.MAX_OVERFLOW_NAMES
        assert len(set(over)) == len(over), "danh sách tràn có phần tử trùng"
        assert not set(over) & tracked, "danh sách tràn chứa id đang theo dõi"
        assert not set(over) & priority, "danh sách tràn chứa id ưu tiên"
        assert SELF not in over and SELF not in tracked
        assert all(x in POOL for x in over)
        assert set(outstanding) <= tracked, "resolve đang chạy cho id không còn là ứng viên"
        assert set(model) <= tracked
        regular = tracked - priority
        if not new_cap_allowed:
            assert len(regular) <= cap, f"{len(regular)} ứng viên thường > giới hạn {cap}"
        # Đúng sau mọi bước, kể cả khi nâng một ứng viên thường lên ưu tiên (chỗ nó nhả ra
        # phải được lấp ngay từ danh sách tràn).
        if over:
            assert len(regular) >= max_services, "còn chỗ mà danh sách tràn chưa được lấy"
        cap = max(max_services, len(regular))

    check_structure()

    def deliver(did: str, variant: str) -> None:
        name = outstanding.pop(did)
        over_before = set(_overflow_ids(t))
        out = t.resolve_done(name, variant_result(did, variant), now)
        assert out.probe == ()
        # Ngoài resolve lại chính nó (dirty/stale), chỉ được nhận thêm id từ danh sách tràn.
        for n in out.resolve:
            other = device_id_from_service_name(n)
            assert other == did or other in over_before
        apply(out)
        check_structure()

    def seen(name: str, did: str | None) -> None:
        tracked_before = _tracked_ids(t)
        regular_before = tracked_before - priority
        out = t.service_seen(name)
        assert out.probe == ()
        if did is None or did == SELF:
            assert out.events == () and no_requests(out)
        apply(out)
        if did is not None and did != SELF:
            tracked_after = _tracked_ids(t)
            if did in priority:
                assert did in tracked_after, "thiết bị ưu tiên phải luôn được nhận"
            elif did not in tracked_before:
                if len(regular_before) < max_services:
                    assert did in tracked_after
                    assert out.resolve == (service_name(did),)
                else:
                    assert did not in tracked_after
                    assert did in _overflow_ids(t)
                    assert no_requests(out) and out.notes
        check_structure()

    for step in steps:
        kind = step[0]
        if kind == "seen":
            seen(_svc(step[1]), step[1] if step[1] != "bad" else None)
        elif kind == "seen_upper":
            seen(f"{step[1]}._TELEPORT._TCP.LOCAL.", step[1])
        elif kind == "gone":
            over_before = set(_overflow_ids(t))
            out = t.service_gone(_svc(step[1]))
            assert out.probe == ()
            for n in out.resolve:  # chỉ được nhận id từ danh sách tràn
                assert device_id_from_service_name(n) in over_before
            apply(out)
            if step[1] in POOL:
                assert step[1] not in _overflow_ids(t)
            check_structure()
        elif kind == "done":
            if not outstanding:
                continue
            did = sorted(outstanding)[step[1] % len(outstanding)]
            deliver(did, step[2])
        elif kind == "stray":
            # Kết quả cho id không có yêu cầu nào đang chạy: phải bị bỏ qua hoàn toàn.
            did = step[1]
            if did in outstanding:
                continue
            out = t.resolve_done(service_name(did), variant_result(did, step[2]), now)
            assert out.events == () and no_requests(out)
            apply(out)
            check_structure()
        elif kind == "probe":
            now += step[1]
            out = t.due_probes(now)
            assert out.events == () and out.resolve == ()
            assert list(out.probe) == sorted(out.probe, key=device_id_from_service_name)
            apply(out)
            check_structure()
        elif kind == "prio":
            tracked_before = _tracked_ids(t)
            over_before = set(_overflow_ids(t))
            new_priority = set(step[1]) - {SELF}
            out = t.set_priority(step[1])
            priority = new_priority
            assert out.events == () and out.probe == ()
            requested = {device_id_from_service_name(n) for n in out.resolve}
            assert requested <= over_before, "set_priority chỉ resolve id đang chờ trong danh sách tràn"
            assert (priority & over_before) <= requested, "id ưu tiên đang chờ phải được resolve ngay"
            apply(out)
            regular_after = _tracked_ids(t) - priority
            if regular_after - tracked_before:  # có nhận thêm ứng viên thường: phải còn trong giới hạn
                assert len(regular_after) <= max_services
            check_structure(new_cap_allowed=True)
        else:  # prio_bad: một phần tử sai → MessageError, trạng thái không đổi
            tracked_before = _tracked_ids(t)
            over_before = _overflow_ids(t)
            with pytest.raises(MessageError):
                t.set_priority([*sorted(step[1]), "bad"])
            assert _tracked_ids(t) == tracked_before
            assert _overflow_ids(t) == over_before
            assert dict(t.devices) == model
            check_structure()

    # Không còn seen/gone: trả lời hết các yêu cầu thì chuỗi resolve phải dừng (không vòng lặp vô hạn).
    for _ in range(6 * len(POOL) + 4):
        if not outstanding:
            break
        deliver(min(outstanding), "none")
    assert not outstanding, "tracker yêu cầu resolve mãi không dừng"


# =================================================================================================
# PR-4: `NetworkWatch` (đặc tả PR-4 mục 2.2, NW1–NW5). Truy cập qua module để file vẫn import được
# khi tên mới chưa có.
# =================================================================================================

NW_INTERVAL = 5.0
NW_A = ("192.168.1.5",)
NW_AB = ("192.168.1.5", "10.0.0.2")
NW_WALL = 1_700_000_000.0


def nw(addresses=NW_A, mono: float = 100.0, wall: float = NW_WALL):
    return core_discovery.NetworkWatch(addresses, mono, wall)


def test_nw_constants_and_values():
    assert core_discovery.WAKE_JUMP == 15.0
    change = core_discovery.NetworkChange
    assert {c.value for c in change} == {"none", "addresses", "woke"}
    assert change.NONE == "none" and change.ADDRESSES == "addresses" and change.WOKE == "woke"


def test_nw1_nothing_changed_is_none():
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + 5, interval=NW_INTERVAL) == core_discovery.NetworkChange.NONE
    assert w.sample(list(NW_A), 110.0, NW_WALL + 10, interval=NW_INTERVAL) == "none"  # list = tuple


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (NW_A, NW_AB),  # thêm
        (NW_AB, NW_A),  # bớt
        (NW_AB, tuple(reversed(NW_AB))),  # chỉ đổi thứ tự
        (NW_A, ()),  # mất hết
        ((), NW_A),  # có lại
        (NW_A, ("192.168.1.6",)),  # đổi
    ],
    ids=["them", "bot", "thu_tu", "mat_het", "co_lai", "doi"],
)
def test_nw2_address_change_is_addresses(before, after):
    w = nw(before)
    assert w.sample(after, 105.0, NW_WALL + 5, interval=NW_INTERVAL) == "addresses"
    # Giá trị mới được lưu: lần đo sau không đổi gì → NONE.
    assert w.sample(after, 110.0, NW_WALL + 10, interval=NW_INTERVAL) == "none"


def test_nw2_address_change_wins_over_clock_jump():
    w = nw()
    assert w.sample(NW_AB, 100.0 + 3600, NW_WALL + 7200, interval=NW_INTERVAL) == "addresses"


def test_nw3_monotonic_jump_while_asleep_is_woke():
    jump = core_discovery.WAKE_JUMP
    w = nw()
    gm = NW_INTERVAL + jump + 1
    assert w.sample(NW_A, 100.0 + gm, NW_WALL + gm, interval=NW_INTERVAL) == "woke"
    w = nw()
    gm = NW_INTERVAL + jump - 1
    assert w.sample(NW_A, 100.0 + gm, NW_WALL + gm, interval=NW_INTERVAL) == "none"


def test_nw3_thresholds_are_strict():
    jump = core_discovery.WAKE_JUMP
    w = nw()
    gm = NW_INTERVAL + jump
    assert w.sample(NW_A, 100.0 + gm, NW_WALL + gm, interval=NW_INTERVAL) == "none"
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + 5 + jump, interval=NW_INTERVAL) == "none"


def test_nw4_wall_clock_jump_with_stopped_monotonic_is_woke():
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + NW_INTERVAL + 3600, interval=NW_INTERVAL) == "woke"
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + NW_INTERVAL - 3600, interval=NW_INTERVAL) == "woke"


def test_nw4_small_wall_drift_is_none():
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + NW_INTERVAL - 2.0, interval=NW_INTERVAL) == "none"


def test_nw_each_sample_updates_baseline():
    w = nw()
    assert w.sample(NW_A, 105.0, NW_WALL + 3605, interval=NW_INTERVAL) == "woke"
    # Mốc mới là (105, …3605): lần đo kế bình thường → NONE (không báo WOKE mãi).
    assert w.sample(NW_A, 110.0, NW_WALL + 3610, interval=NW_INTERVAL) == "none"
    assert w.sample(NW_A, 110.0, NW_WALL + 3610, interval=NW_INTERVAL) == "none"  # mono bằng: được


def test_nw_interval_is_per_call():
    w = nw()
    assert w.sample(NW_A, 150.0, NW_WALL + 50, interval=60.0) == "none"
    assert w.sample(NW_A, 200.0, NW_WALL + 100, interval=1.0) == "woke"


@pytest.mark.parametrize(
    "make",
    [
        lambda: core_discovery.NetworkWatch("1.2.3.4", 0.0, 0.0),
        lambda: core_discovery.NetworkWatch(NW_A, math.nan, 0.0),
        lambda: core_discovery.NetworkWatch(NW_A, 0.0, math.inf),
        lambda: core_discovery.NetworkWatch(NW_A, "0", 0.0),
    ],
    ids=["chuoi_don", "mono_nan", "wall_inf", "mono_chuoi"],
)
def test_nw5_constructor_rejects_bad_arguments(make):
    with pytest.raises((ValueError, TypeError)):
        make()


@pytest.mark.parametrize(
    "call",
    [
        lambda w: w.sample("1.2.3.4", 105.0, 5.0, interval=NW_INTERVAL),
        lambda w: w.sample(NW_A, 99.0, 5.0, interval=NW_INTERVAL),
        lambda w: w.sample(NW_A, math.nan, 5.0, interval=NW_INTERVAL),
        lambda w: w.sample(NW_A, 105.0, math.nan, interval=NW_INTERVAL),
        lambda w: w.sample(NW_A, 105.0, 5.0, interval=0.0),
        lambda w: w.sample(NW_A, 105.0, 5.0, interval=-1.0),
        lambda w: w.sample(NW_A, 105.0, 5.0, interval=math.nan),
        lambda w: w.sample(NW_A, 105.0, 5.0, interval=math.inf),
    ],
    ids=[
        "chuoi_don",
        "mono_giam",
        "mono_nan",
        "wall_nan",
        "interval_0",
        "interval_am",
        "interval_nan",
        "interval_inf",
    ],
)
def test_nw5_sample_rejects_bad_arguments(call):
    w = nw(NW_A, 100.0, 0.0)
    with pytest.raises((ValueError, TypeError)):
        call(w)
