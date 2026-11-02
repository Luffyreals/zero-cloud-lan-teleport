"""Node với mDNS thật trên 127.0.0.1 (đặc tả PR-4 mục 4.6, M1–M3).

Bộ lọc địa chỉ (protocol §8) bỏ loopback, nên node quảng bá địa chỉ TEST-NET `192.0.2.x`
(`advertise_addresses`); M2 bọc `open_control` để nối về `127.0.0.1`. Mỗi test chỉ xét sự kiện về
device_id của chính nó, vì tiến trình khác có thể cũng đang quảng bá trên loopback.
Đặt `TELEPORT_SKIP_MDNS=1` để bỏ qua.
"""

import asyncio
import time

import pytest
from support import wait_until

from teleport.app.node import (
    DeviceConnected,
    DeviceDisconnected,
    DeviceOffline,
    DeviceOnline,
    MdnsOptions,
    scan_devices,
)
from teleport.lock import NodeLock

pytestmark = [
    pytest.mark.integration,
    pytest.mark.mdns,
    pytest.mark.usefixtures("no_leaks"),
    pytest.mark.filterwarnings("error::ResourceWarning"),
    pytest.mark.filterwarnings("error::pytest.PytestUnraisableExceptionWarning"),
]

LOCAL = "127.0.0.1"


def opts(n: int) -> MdnsOptions:
    return MdnsOptions(
        interfaces=(LOCAL,),
        advertise_addresses=(f"192.0.2.{n}",),
        probe_interval=1.0,
        resolve_timeout=0.5,
        probe_tick=0.2,
    )


@pytest.mark.slow
@pytest.mark.demo
async def test_m1_two_unpaired_nodes_see_each_other(node_factory):
    A = await node_factory("A", mdns=opts(11))
    B = await node_factory("B", mdns=opts(12))
    assert A.discovery_active and B.discovery_active, (A.discovery_error, B.discovery_error)
    seen_b = await A.rec.wait_event(DeviceOnline, B.id, timeout=5)
    seen_a = await B.rec.wait_event(DeviceOnline, A.id, timeout=5)
    for ev, other, n in ((seen_b, B, 12), (seen_a, A, 11)):
        assert ev.device.paired is False
        assert ev.device.online is True
        assert ev.device.port == other.port
        assert ev.device.addresses == (f"192.0.2.{n}",)
        assert ev.device.name == other.name
    assert A.connected_devices() == frozenset()


@pytest.mark.slow
async def test_m2_trusted_nodes_connect_and_goodbye(node_factory, trust_each_other, count_open_control):
    counter = count_open_control(rewrite_to=LOCAL)
    trust_each_other("A", "B")
    A = await node_factory("A", mdns=opts(21))
    B = await node_factory("B", mdns=opts(22))
    await wait_until(
        lambda: A.connected_devices() == {B.id} and B.connected_devices() == {A.id}, 8, "hai bên chưa kết nối"
    )
    await asyncio.sleep(0.5)
    assert A.connected_devices() == {B.id} and B.connected_devices() == {A.id}
    n_up_b = len(B.rec.events_of(DeviceConnected, A.id)) - len(B.rec.events_of(DeviceDisconnected, A.id))
    assert n_up_b == 1
    assert {c.addresses for c in counter.calls} <= {("192.0.2.21",), ("192.0.2.22",)}
    # Kết nối có thể lập trước khi mDNS của B kịp thấy A (A thấy B trước): chờ B thấy A rồi mới đóng.
    await B.rec.wait_event(DeviceOnline, A.id, timeout=8)
    t0 = time.monotonic()
    await A.close()
    await B.rec.wait_event(DeviceOffline, A.id, timeout=3)
    assert time.monotonic() - t0 <= 3.0, "goodbye mDNS phải tới trong ≤ 3 s"
    await B.rec.wait_event(DeviceDisconnected, A.id, timeout=3)


# Thời gian quét của M3. B đã quảng bá xong trước khi quét, nên máy quét chỉ thấy B khi B trả lời
# truy vấn của nó. zeroconf gửi truy vấn lúc ~0,1 s, ~1,1 s, ~5,1 s (STARTUP_QUERIES, giãn n² giây).
# Lần đầu không có kết quả ở đây (đo: luôn thấy B từ ~1,1 s): B vừa multicast bản ghi lúc khởi
# động nên không multicast lại trong 1 s (RFC 6762 §6), còn trả lời unicast cho câu hỏi QU đi về
# 127.0.0.1:5353, nơi nhiều socket zeroconf cùng bind. Lần ~1,1 s có thể hỏng khi tiến trình khác
# cũng dùng mDNS trên loopback (đo: thấy B tới 2,35 s, quá hạn 2 s cũ). 6 s chứa cả lần ~5,1 s.
M3_SCAN_TIMEOUT = 6.0


@pytest.mark.slow
async def test_m3_scan_sees_node_without_advertising_or_locking(node_factory, tmp_path):
    B = await node_factory("B", mdns=opts(31))
    dir_x = tmp_path / "X"
    scan = asyncio.create_task(
        scan_devices(dir_x, timeout=M3_SCAN_TIMEOUT, mdns=MdnsOptions(interfaces=(LOCAL,), advertise=False)),
        name="test.scan",
    )
    await asyncio.sleep(0.5)
    lock = NodeLock(dir_x)
    lock.acquire()  # list không giữ node.lock
    lock.release()
    result = await asyncio.wait_for(scan, M3_SCAN_TIMEOUT + 10)
    views = {v.device_id: v for v in result.devices}
    assert B.id in views, "scan_devices không thấy B"
    vb = views[B.id]
    assert (vb.online, vb.paired, vb.port, vb.addresses) == (True, False, B.port, ("192.0.2.31",))
    await asyncio.sleep(1.0)
    assert B.rec.events_of(DeviceOnline, result.device_id) == [], "máy chỉ quét không được quảng bá"
