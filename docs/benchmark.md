# Benchmark

> **Vai trò:** số đo thực tế của các yêu cầu phi chức năng và kết quả kiểm tiêu chí MVP hackathon.
> **Nguồn duy nhất cho:** định nghĩa từng phép đo, môi trường, kết quả từng lần đo và kết luận so với ngưỡng.
> **Không chứa:** ngưỡng yêu cầu → [mvp.md](mvp.md) mục 9 (tham chiếu theo mã `mvp N1`…, không chép số). Thiết kế khám phá, TTL, chu kỳ kiểm còn sống và cận trên đã tính → [protocol.md](protocol.md) mục 8. Trạng thái giai đoạn → [ke_hoach.md](ke_hoach.md) mục 5.1.
> **Cập nhật:** 2026-11-05

## 1. Quy ước

- Mỗi lần đo là một mục con riêng, ghi ngày, commit, môi trường hai phía và script đã dùng. Lần đo cũ giữ nguyên, không sửa số.
- Thống kê: số lần hợp lệ, trung vị, p95, nhỏ nhất, lớn nhất; p95 theo hạng gần nhất (với 10 lần thì bằng lớn nhất). Lần hỏng ghi riêng kèm lý do: **quá hạn** (không thấy sự kiện trong thời gian chờ, tính là không đạt) hoặc **lỗi đo** (môi trường hỏng, không tính vào kết quả).
- Mỗi giá trị là **cận trên** (bảo thủ); khi có, ghi cả cận dưới. Kết luận dùng cận trên: **ĐẠT** khi đủ số lần hợp lệ tối thiểu, không lần nào quá hạn và mọi cận trên dưới ngưỡng; **KHÔNG ĐẠT** khi có lần quá hạn hoặc cận dưới chạm ngưỡng; còn lại **CHƯA ĐỦ DỮ LIỆU**.
- Không có số thật thì ghi **chưa đo**, không bao giờ điền số ước lượng.
- Đo trên máy ảo hoặc môi trường khác máy thật thì ghi rõ giới hạn ngay trong lần đo đó.
- Số thập phân viết bằng dấu phẩy; thời gian tính bằng giây (s) trừ khi ghi ms.

## 2. Tổng hợp

| Mã | Lần đo gần nhất | Kết luận |
|---|---|---|
| mvp N1 | 2026-11-05: hai máy Windows thật (11 ↔ 10) qua Wi-Fi 2,4 GHz, cùng điểm phát (mục 3.6); trước đó 2026-10-23: host Windows 11 + máy ảo Ubuntu bridged (mục 3.3) | **ĐẠT trên hai máy thật qua Wi-Fi** cho phần xuất hiện, thoát app và mất mạng đột ngột (tắt Wi-Fi, app bị giết); máy **ngủ** thật, mạng dây và kịch bản mất gói ở hai lần resolve đầu chưa đo (mục 3.4) |
| mvp N2 | 2026-10-29/30: đo tay qua giao diện, hai máy Windows thật qua Wi-Fi 2,4 GHz, một file 1,89 GiB (mục 5.4) | **CHƯA ĐỦ DỮ LIỆU**: lần đo tay cho tỉ số khoảng 0,96 nhưng không theo phương pháp mục 5.1 (1 lần Teleport, 2 lần SMB, một cỡ file, bấm giờ tay); lượt đo theo mục 5.1 và mạng dây chưa đo (mục 5.3) |
| mvp N3 | 2026-11-05: 10 GiB qua Wi-Fi 2,4 GHz giữa hai máy Windows thật, RAM hai phía, 1 lần (mục 4.10). 2026-10-26: `teleport send` / `receive` thật, hai tiến trình trên một máy Windows 11, loopback, 1 / 5 / 10 GiB (mục 4.6); lúc rảnh của `receive` 10 phút (mục 4.7); ổ đích USB dừng ở bước kiểm ổ (mục 4.8). 2026-10-28: trước/sau thay đổi ghi trạng thái nối lại bền, 1 GiB và 1000 file nhỏ (mục 4.9) | **CHƯA ĐỦ DỮ LIỆU**: phần truyền qua loopback ĐẠT cả ba tiêu chí mục 4.1 với 1, 5 và 10 GiB; lúc rảnh của CLI chỉ ghi nhận; ổ đích chậm (USB có sẵn là FAT32, mục 4.8), lúc rảnh của app có giao diện chưa đo (mục 4.4). Sau thay đổi ghi trạng thái nối lại bền (mục 4.9), tiêu chí 1 và 2a vẫn ĐẠT với 1 GiB và 1000 file nhỏ. Qua Wi-Fi giữa hai máy thật (mục 4.10), RSS tăng 4,8 MiB bên gửi và 6,0 MiB bên nhận, Q4 − Q1 âm ở cả hai; D3 ĐẠT với 1 lần theo quyết định của người dùng (mục 4.10) |
| mvp N4 | 2026-10-31: `teleport send` / `receive` thật, hai tiến trình trên một máy Windows 11, qua proxy TCP trên loopback, file 1 GiB, cắt ở 85 % theo 6 kiểu (mục 7.3) | **CHƯA ĐỦ DỮ LIỆU**: trên loopback Windows phần gửi thừa mỗi gián đoạn lớn nhất 24,31 MiB, ĐẠT ở mọi lần (49/49); theo tiêu chí ở mục 7.1 thì **không đặt** `SO_RCVBUF`/`SO_SNDBUF` trên Windows. Linux (máy ảo), card mạng thật / Wi-Fi và macOS chưa đo (mục 7.4, D5) |
| mvp N5 | — | chưa đo |
| mvp N6 | 2026-11-02: hai `Node` thật trong một tiến trình trên một máy Windows 11, loopback, `FakeClipboard` (mục 9.3); backend Qt `read`/`write` ảnh thật, nền Qt offscreen, cùng máy (M4, mục 9.4) | **KHÔNG ĐẠT** ở ca ảnh 8192² dễ nén (cận dưới trên nền offscreen đã vượt ngưỡng ảnh, mục 9.4); các ca còn lại **CHƯA ĐỦ DỮ LIỆU** (D6): trên loopback văn bản 1 KB và 1 MiB, ảnh PNG 10 MiB đều dưới ngưỡng ở mọi lần, RAM phẳng sau 1000 clip; backend Qt nhanh với ảnh 1920×1080 và 3840×2160 nhưng ảnh 8192² dễ nén (PNG 3,53 MiB) đã tốn khoảng 4,3–5,0 s (p95 `read` + `write`, lượt r1 và r3), vượt ngưỡng ảnh, chủ yếu do mã hóa PNG; ảnh khó nén vượt trần nay bị loại sau dưới 0,75 s nhờ kiểm sơ bộ (trước: tới 24,3 s); Wi-Fi 5 giữa hai máy thật (D6) và clipboard thật của Windows chưa đo (mục 9.5) |
| mvp N7 | — | chưa đo |
| mvp N8 | — | chưa đo |
| mvp N9 | — | chưa đo |
| mvp N10 | — | chưa đo |
| mvp N11 | 2026-10-31: bộ cài Inno Setup thử (PR E2), cài/gỡ silent `/CURRENTUSER` 3 lần trên máy dev Windows 11 (mục 8.4); trước đó cỡ zip GUI trước/sau A2 (mục 8.2) | **CHƯA ĐỦ DỮ LIỆU**: cỡ bộ cài dưới trần theo cả hai cách hiểu “MB”, không cần khởi động lại và gỡ sạch thư mục cài, khóa gỡ cài đặt, lối tắt ở chế độ một người dùng; chế độ quản trị (rule tường lửa) và máy ảo sạch chưa đo (mục 8.3) |
| mvp N12 | — | chưa đo |
| mvp mục 4.1 (H1–H5) | 2026-11-05: zip RC1 `7824259`, hai máy Windows thật qua Wi-Fi 2,4 GHz (mục 6.1) | **ĐẠT** cả năm tiêu chí (mục 6) |

## 3. mvp N1: Khám phá

### 3.1. Định nghĩa phép đo

Mọi khoảng thời gian tính trên **một đồng hồ**: `time.perf_counter()` của host. Máy ảo chỉ gửi về *khoảng* thời gian trên đồng hồ của nó (từ lúc nhận lệnh tới lúc bắt đầu quảng bá, bắt đầu `Node.close()`, giết tiến trình), không bao giờ so mốc của hai máy với nhau. Mốc “thấy” / “mất” là lúc `Node` phát `DeviceOnline` / `DeviceOffline` (`teleport.app.node`, gọi đồng bộ trên event loop).

| Ca | Đo từ | Đo tới | Cận dưới | So với phần nào của mvp N1 |
|---|---|---|---|---|
| `appear_vm` | node mới (danh tính mới) trên VM bắt đầu quảng bá (vào `MdnsDiscovery.advertise`) | node trên host phát `DeviceOnline` | trừ RTT kênh điều khiển | xuất hiện |
| `appear_host` | node mới trên host bắt đầu quảng bá | node trên VM phát `DeviceOnline`, mốc lúc host nhận báo | trừ RTT | xuất hiện |
| `open_host` *(bổ sung)* | gọi `Node.start()` trên host khi VM đang quảng bá | host phát `DeviceOnline` cho VM | (một đồng hồ, không qua kênh) | xuất hiện |
| `exit_vm` | gọi `Node.close()` trên VM (gửi goodbye) | host phát `DeviceOffline` | trừ RTT | thoát app |
| `exit_host` | gọi `Node.close()` trên host | VM phát `DeviceOffline`, mốc lúc host nhận báo | trừ RTT | thoát app |
| `link_down` | ngay trước lệnh hypervisor cắt liên kết card mạng VM | host phát `DeviceOffline` | tính từ lúc lệnh hypervisor trả về | mất mạng đột ngột hoặc ngủ |
| `pause_vm` | ngay trước lệnh hypervisor tạm dừng VM (giả lập ngủ / treo) | host phát `DeviceOffline` | tính từ lúc lệnh trả về | mất mạng đột ngột hoặc ngủ |
| `kill_vm` *(bổ sung)* | giết cây tiến trình `teleport listen` trên VM (không goodbye) | host phát `DeviceOffline` | trừ RTT | mất mạng đột ngột hoặc ngủ |
| `kill_host` *(bổ sung)* | giết cây tiến trình `teleport listen` trên host | VM phát `DeviceOffline`, mốc lúc host nhận báo | trừ RTT | mất mạng đột ngột hoặc ngủ |
| `link_down_reappear`, `pause_vm_reappear` | ngay trước lệnh cắm lại mạng / cho VM chạy tiếp | host phát `DeviceOnline` lại | tính từ lúc lệnh trả về | chỉ ghi nhận (mvp N1 không có ngưỡng cho việc này) |

Ca *bổ sung* là cách hiểu thêm của người đo, không thay ca chính: `open_host` là “mở app thấy máy đã có”; `kill_*` là app bị giết, với máy bên kia giống hệt mất mạng đột ngột.

### 3.2. Phương pháp

- Hai node đo đạc dùng API có sẵn (`Node`, `MdnsOptions`; `teleport listen --json` cho ca `kill_*`), thư mục cấu hình tạm riêng, lắng nghe 127.0.0.1 cổng ngẫu nhiên, không ghép đôi, không tự kết nối (`accept_pairing=False`, `auto_connect=False`); mDNS quảng bá và duyệt như `teleport listen`. Ca xuất hiện dùng danh tính mới mỗi lần (thiết bị máy kia chưa từng thấy).
- Host chạy `n1_host.py` (điều phối, giữ mọi mốc); VM chạy `n1_vm_agent.py` (bật/tắt node theo lệnh qua TCP, đẩy sự kiện về ngay). Trước mỗi lần đo, host ping agent 3 lần để có RTT; độ trễ một chiều của kênh nằm trong khoảng 0…RTT.
- Mốc bắt đầu quảng bá / bắt đầu đóng mDNS lấy bằng một lớp con của `MdnsDiscovery` gắn vào `teleport.app.node.MdnsDiscovery` trong tiến trình đo; `src/` không sửa.
- Ca mất mạng / ngủ: hypervisor cắt liên kết (VirtualBox `controlvm … setlinkstateN off`; script cũng hỗ trợ VMware `vmrun disconnectNamedDevice` và Hyper-V `Disconnect-VMNetworkAdapter`) hoặc tạm dừng VM (`pause`; Hyper-V `Suspend-VM`). Sau khi cắt, host ping agent: còn trả lời thì lần đó là lỗi đo (lệnh không có hiệu lực). Lệnh hypervisor chạy trong thread để không làm trễ mốc sự kiện.
- Trước mỗi lần cắt / giết, chờ ngẫu nhiên (phân bố đều, hạt giống ghi trong kết quả) trong một khoảng rộng bằng TTL bản ghi (protocol mục 8), để mẫu phủ mọi pha của TTL và của nhịp kiểm còn sống. Giữa lúc xuất hiện và lúc thoát cũng chờ ngẫu nhiên vài giây (ghi trong `settle_s`).
- Mỗi ca lặp 10 lần; mọi lần chờ có giới hạn; cả lượt đo có giới hạn thời gian; kết thúc (kể cả Ctrl+C) thì cắm lại mạng, cho VM chạy tiếp, tắt mọi node và xóa thư mục tạm.
- Dữ liệu thô: JSON Lines (`results.jsonl` trên host, `agent.jsonl` trên VM), gồm môi trường hai phía, cấu hình, ngưỡng đọc từ `mvp.md` lúc chạy, mọi sự kiện và mọi lần đo.

**Nguồn sai số**

| Nguồn | Xử lý |
|---|---|
| Độ trễ một chiều của kênh điều khiển (ca có VM nhận lệnh hoặc VM báo về) | Đo RTT trước mỗi lần; ghi cận trên (gồm trễ) và cận dưới (trừ RTT lớn nhất) |
| Thời gian chạy lệnh hypervisor (ca `link_down`, `pause_vm`) | Kẹp giữa mốc trước và sau lệnh; ghi thời gian lệnh (`hv_call_s`) |
| Pha của TTL bản ghi và nhịp kiểm còn sống lúc cắt | Chờ ngẫu nhiên trước khi cắt, hạt giống ghi lại |
| Trễ event loop của node quan sát | Là một phần của điều cần đo (mốc lấy ngay khi `Node` phát sự kiện) |
| Đồng hồ máy ảo khi đo khoảng ngắn trên VM | Chỉ dùng cho khoảng vài ms–vài giây ngay sau khi nhận lệnh; không dùng qua lúc VM bị tạm dừng |
| Host và VM dùng chung CPU | Ghi số CPU/RAM của VM; xem giới hạn bên dưới |

### 3.3. Lần đo 2026-10-23: host Windows 11 + máy ảo bridged

Người dùng đã chấp nhận máy ảo bridged thay máy thật thứ hai cho lần đo này. Mã đo: `main` tại commit `efa9d5b`, không sửa (`src_dirty: false` ở cả hai phía). Script: `n1_host.py`, `n1_vm_agent.py`, `n1_common.py` (mục 3.5).

| Lượt | Ca | Thời lượng | Hạt giống |
|---|---|---|---|
| preflight (03:47 UTC) | kiểm kênh agent, hypervisor, mDNS hai chiều | — | — |
| `run-20261023T034748255Z` | `appear_vm`, `exit_vm`, `appear_host`, `exit_host`, `open_host` | 322,6 s | 992322527 |
| `run-20261023T035326280Z` | `kill_vm`, `kill_host` | 1860,2 s | 4130361009 |
| `run-20261023T042452185Z` | `link_down`, `link_down_reappear`, `pause_vm`, `pause_vm_reappear` | 2098,2 s | 780602171 |

**Môi trường** (ghi tự động trong `results.jsonl`, giống nhau ở cả ba lượt trừ tốc độ liên kết Wi-Fi)

| | Host | Máy ảo |
|---|---|---|
| Hệ điều hành | Windows 11, bản 10.0.26300 | Ubuntu 26.04.1 LTS (theo người dùng); `results.jsonl` ghi kernel Linux 7.0.0-38-generic, glibc 2.43. Trường `ostype` của VirtualBox ghi “Ubuntu 25.04 (64-bit)”, là kiểu khai báo lúc tạo VM |
| Python | 3.14.5 | 3.14.4 |
| Teleport | `__version__` 0.0.1, commit `efa9d5bb35a60bb0c7855703c6e62fc464f45b8c`, digest mã nguồn `30a05fd463396837fcaa037fc5c7b777fdbd5b4b94f31ef55bdf62ab75257e22` | giống host (cùng commit, cùng digest) |
| zeroconf / ifaddr / cryptography | 0.151.5 / 0.2.0 / 50.0.2 | 0.151.5 / 0.2.0 / 50.0.2 |
| CPU | Intel Core i7-12800H, 20 luồng | cùng CPU, 2 vCPU |
| RAM | 15,7 GiB | cấp 4096 MB, hệ điều hành khách thấy 3,3 GiB |
| Card mạng | Wi-Fi: Intel Wi-Fi 6 AX201 160MHz, liên kết 103–143 Mbps tùy lượt; hồ sơ mạng Public; card dây Intel I219-LM không cắm | `enp0s3`, driver `e1000` (VirtualBox 82540EM), bridged lên card Wi-Fi AX201 của host |
| Địa chỉ quảng bá | `172.18.96.1`, `192.168.1.7` (xem phần Ghi nhận bên dưới) | `192.168.1.3` |
| Hypervisor | VirtualBox 7.2.16 r174877, VM 2 vCPU, 4096 MB, mạng bridged; Guest Additions trong VM báo 6.0.0 r127566 | — |
| Đồng hồ | `QueryPerformanceCounter()`, độ phân giải 100 ns | `CLOCK_MONOTONIC`, độ phân giải 1 ns |

**RTT kênh điều khiển** (host ↔ agent trong VM, TCP): preflight 10 lần, trung vị 1,79 ms, lớn nhất 5,07 ms. Trong các lượt đo, lấy RTT lớn nhất của 3 ping trước mỗi lần đo có dùng kênh (60 lần): trung vị 4,13 ms, nhỏ nhất 1,34 ms, lớn nhất 64,87 ms.

**Thời gian lệnh hypervisor** (`hv_call_s`): cắt liên kết 0,036–0,116 s; cắm lại 0,037–0,190 s; tạm dừng 0,039–0,081 s; chạy tiếp 0,029–0,077 s. Thời gian chờ ngẫu nhiên trước khi cắt / giết thực tế nằm trong 11,3–68,8 s.

**Kết quả** (giây, cận trên, trên đồng hồ của host; “cận dưới lớn nhất” là giá trị lớn nhất trong các cận dưới)

| Ca | Hợp lệ / hỏng | Trung vị | p95 | Min | Max | Cận dưới lớn nhất | Kết luận |
|---|---|---|---|---|---|---|---|
| `appear_vm` | 10 / 0 | 1,101 | 1,161 | 1,048 | 1,161 | 1,157 | ĐẠT |
| `appear_host` | 10 / 0 | 1,075 | 1,140 | 1,036 | 1,140 | 1,137 | ĐẠT |
| `open_host` *(bổ sung)* | 10 / 0 | 0,107 | 0,144 | 0,068 | 0,144 | — | ĐẠT |
| `exit_vm` | 10 / 0 | 0,003 | 0,006 | 0,002 | 0,006 | 0,001 | ĐẠT |
| `exit_host` | 10 / 0 | 0,005 | 0,008 | 0,004 | 0,008 | 0,004 | ĐẠT |
| `link_down` | 10 / 0 | 61,847 | 82,518 | 23,355 | 82,518 | 82,451 | ĐẠT |
| `pause_vm` | 10 / 0 | 58,743 | 74,616 | 26,071 | 74,616 | 74,560 | ĐẠT |
| `kill_vm` *(bổ sung)* | 10 / 0 | 58,669 | 87,681 | 32,891 | 87,681 | 87,670 | ĐẠT |
| `kill_host` *(bổ sung)* | 10 / 0 | 55,948 | 71,767 | 23,486 | 71,767 | 71,763 | ĐẠT |
| `link_down_reappear` | 10 / 0 | 10,044 | 12,442 | 7,683 | 12,442 | 12,385 | chỉ ghi nhận |
| `pause_vm_reappear` | 10 / 0 | 17,008 | 17,011 | 0,379 | 17,011 | 16,980 | chỉ ghi nhận |

Không có lần nào quá hạn hay lỗi đo (0 / 0 ở mọi ca). Ở bốn ca mất mạng / ngủ / bị giết, mọi giá trị đều nằm dưới cận trên đã tính ở protocol mục 8.

**Kết luận mvp N1: ĐẠT trên máy ảo bridged** (cả ba phần: xuất hiện, thoát app, mất mạng đột ngột hoặc ngủ; 10 lần hợp lệ mỗi ca). Kết luận này chỉ có giá trị trong giới hạn dưới đây; chưa thay được phép đo trên hai máy thật (mục 3.4).

**Ghi nhận** (không phải yêu cầu, không có ngưỡng)

- Thấy lại sau khi cắm lại mạng (`link_down_reappear`): trung vị 10,044 s, trong khoảng 7,683–12,442 s.
- Thấy lại sau khi VM chạy tiếp (`pause_vm_reappear`): 9/10 lần nằm sát nhau trong 17,003–17,011 s (cận dưới 16,933–16,980 s); một lần (lần 5) chỉ 0,379 s. Giá trị gần như cố định này là quan sát cần tìm hiểu; lần đo này chưa có dữ liệu để biết nó đến từ đâu (node trên VM, zeroconf, hay đồng hồ VM sau khi chạy tiếp).
- Host quảng bá cả `172.18.96.1` dù node lọc card ảo (protocol mục 2.1). Theo danh sách card trong `results.jsonl`, `172.18.96.1/20` nằm trên card “Hyper-V Virtual Ethernet Adapter”, tên Windows `vEthernet (WSL (Hyper-V firewall))`. Nguyên nhân và cách sửa ghi ở mục `### Fixed` của [CHANGELOG.md](CHANGELOG.md) (địa chỉ ưu tiên lấy theo tuyến multicast); lần đo này chạy trên mã trước khi sửa (commit `efa9d5b`), nên chưa có số đo với bản đã sửa. VM vẫn thấy host đúng hạn (`appear_host`), nhưng địa chỉ này đi vào danh sách địa chỉ máy kia sẽ thử kết nối.

**Giới hạn của lần đo này**

- Gói tin giữa host và máy ảo bridged được hypervisor chuyển ngay trong máy, không qua điểm phát Wi-Fi, router hay switch. Phép đo vì vậy không kiểm cách mạng thật xử lý multicast (Wi-Fi tiết kiệm điện, tốc độ multicast thấp, IGMP snooping, cô lập thiết bị). Trên hai máy thật qua Wi-Fi, mDNS có thể chậm hoặc mất gói nhiều hơn.
- Host và máy ảo dùng chung CPU, RAM và card mạng.
- VirtualBox chạy trên nền Hyper-V của Windows (VirtualBox hiện biểu tượng rùa ở thanh trạng thái VM), nên hiệu năng và độ đều của thời gian trong VM có thể khác khi VirtualBox chạy trực tiếp trên phần cứng; lần đo này không đo ảnh hưởng đó. Lúc cài, người dùng thấy kernel của VM báo *soft lockup*. Hai điều này không được ghi trong `results.jsonl`.
- Cắt liên kết ở hypervisor giống rút cáp ở phía máy ảo, không giống hệt rớt Wi-Fi hay đổi điểm phát.
- Tạm dừng VM là đóng băng, không phải máy ngủ thật: hệ điều hành khách không nhận thông báo ngủ, và đồng hồ sau khi chạy tiếp tùy vào hypervisor / Guest Additions.
- Chỉ một cặp hệ điều hành: Windows 11 ↔ Ubuntu 26.04. Các ca cắt mạng / tạm dừng chỉ có Windows làm bên quan sát; riêng `exit_host`, `appear_host` và `kill_host` có Linux làm bên quan sát. Cả hai phía chạy Python 3.14, chưa đo với Python 3.12.
- Các node không ghép đôi: `DeviceOnline` / `DeviceOffline` đến từ mDNS, không phụ thuộc kết nối điều khiển. Đường ưu tiên thiết bị đã ghép đôi khi danh sách đầy (protocol mục 8) không được kiểm ở đây.
- Giới hạn đã biết ở protocol mục 8 (hai lần resolve đầu đều mất gói) **chưa đo**: cần chèn mất gói có chủ đích.

### 3.4. Việc còn lại

- N1 trên hai máy thật trong cùng mạng Wi-Fi: đã đo, ĐẠT cho xuất hiện, thoát app và mất mạng đột ngột (mục 3.6). Còn lại thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D1): máy **ngủ** thật (ca `pause` với `--hv manual`, cho máy thứ hai ngủ rồi đánh thức) **chưa đo**; mạng dây **chưa đo**; Wi-Fi 5 GHz **chưa đo**.
- Một lần “thấy lại sau khi cắm lại mạng” quá hạn 300 s trên hai máy thật dù mạng của máy kia đã có lại (mục 3.6, Ghi nhận): **chưa tìm hiểu** nguyên nhân.
- Kiểm kịch bản mất gói ở hai lần resolve đầu (protocol mục 8): **chưa đo**. Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D1).
- Thêm cặp hệ điều hành khác (macOS, Windows ↔ Windows) theo mvp N10: **chưa đo**. Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D7).
- Tìm hiểu hai ghi nhận ở mục 3.3 (thấy lại ≈ 17 s sau khi VM chạy tiếp; địa chỉ card Hyper-V được quảng bá).

### 3.5. Cách đo lại

Script nằm ngoài repo, trong thư mục `n1-bench` cạnh thư mục repo (không commit); hướng dẫn từng bước (chuẩn bị VM, mở tường lửa tạm chỉ cho IP của VM, dọn dẹp) ở `HUONG_DAN.md` trong thư mục đó, dữ liệu thô của lần đo này ở `results/`. Trên VM chép `n1_common.py` và `n1_vm_agent.py`, cài Teleport đúng commit cần đo vào `.venv`.

```
# trong VM
python n1_vm_agent.py --bind <VM_IP> --allow-host <HOST_IP>

# trên host, trong thư mục n1-bench, dùng python của .venv trong repo
python n1_host.py preflight --vm-ip <VM_IP> --hv vbox --vm <tên VM>
python n1_host.py run --vm-ip <VM_IP> --hv vbox --vm <tên VM> --cases vm_subject,host_subject,open
python n1_host.py run --vm-ip <VM_IP> --hv vbox --vm <tên VM> --cases kill_vm,kill_host
python n1_host.py run --vm-ip <VM_IP> --hv vbox --vm <tên VM> --cases link_down,pause
python n1_host.py summarize (Get-ChildItem results\run-*\results.jsonl).FullName --write results\n1-tonghop
```

Lệnh trên host viết cho PowerShell (Python trên Windows không tự mở rộng `run-*`).

`vm_subject` gồm `appear_vm` + `exit_vm`, `host_subject` gồm `appear_host` + `exit_host`, `open` là `open_host`, `link_down` và `pause` kèm ca thấy lại tương ứng. Mỗi lượt ghi vào `results/run-<giờ UTC>/` (`results.jsonl`, `summary.md`, `summary.json`); `--repeat` (mặc định 10) và `--seed` chỉnh số lần và hạt giống. Preflight phải báo đạt mới chạy tiếp.

### 3.6. Lần đo 2026-11-05: hai máy Windows thật qua Wi-Fi

Người dùng tự chạy theo hướng dẫn từng bước; đợt đo D1 ([ke_hoach.md](ke_hoach.md) mục 5.4), một phần. Định nghĩa các ca: mục 3.1; phương pháp như mục 3.2, khác ở chỗ “VM” là **máy thật thứ hai** (chạy `n1_vm_agent.py`) và ca `link_down` do người dùng tự tắt / bật Wi-Fi của máy đó (`--hv manual`, xem Cách chạy bên dưới). Trong bảng và trong `results.jsonl`, “host” là máy A, “VM” là máy B.

Mã đo: `main` tại commit `28ab2d2`, không sửa (`src_dirty: false` ở máy A). Máy B chạy mã nguồn tải từ GitHub đúng commit đó (không có git); hai máy cùng digest mã nguồn `54c2c04ac27f2e455b864af237862ea1b5b891e894d16b9bea7db4537c363ac9`. Kết quả áp dụng cho `main` tại `7824259` (ngày đo): từ `28ab2d2` tới đó không đổi `net/discovery.py`, `core/discovery.py` hay `app/node.py`. Script: `n1_host.py`, `n1_vm_agent.py`, `n1_common.py`, `n1_firewall.ps1` (mục 3.5).

| Lượt | Ca | Thời lượng | Hạt giống |
|---|---|---|---|
| preflight (2026-11-04 23:53 UTC) | kiểm kênh agent, mDNS hai chiều | — | — |
| `run-20261105T000548516Z` | `appear_vm`, `exit_vm`, `appear_host`, `exit_host`, `open_host` | 322,9 s | 4025347513 |
| `run-20261105T001957386Z` | `kill_vm`, `kill_host` | 1903,3 s | 48246278 |
| `run-20261105T012139969Z` | `link_down`, `link_down_reappear` (10 lần) | 1431,0 s | 3989379707 |
| `run-20261105T015352789Z` | `link_down`, `link_down_reappear` (2 lần, đo bù lần 3 của lượt trên) | 270,0 s | 3450610562 |

**Lượt hỏng, không tính:** `run-20261105T005721724Z` (lượt thử: không ai tắt Wi-Fi trong 5 phút, script ghi lỗi rồi bị dừng bằng Ctrl+C); `run-20261105T010309573Z` và `run-20261105T010337291Z` (agent còn giữ node của lượt bị Ctrl+C, từ chối bật node mới: không có lần đo nào). `run-20261105T011314036Z` (lượt thử 2 lần để kiểm agent nối lại sau khi tắt Wi-Fi; một lần người dùng nhấn Enter sau khoảng 85 s) cũng không tính.

**Môi trường** (ghi tự động trong `results.jsonl`, trừ dòng Wi-Fi)

| | Máy A (host) | Máy B (VM) |
|---|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 | Windows 10 Enterprise LTSC, bản 10.0.19044 (21H2, không phải 22H2 mà mvp N10 nêu) |
| Python | 3.14.5 | 3.15.1 |
| Teleport | `__version__` 0.1.0a0, commit `28ab2d2`, digest như trên | giống máy A (cùng digest) |
| zeroconf / ifaddr / cryptography | 0.151.5 / 0.2.0 / 50.0.2 | **0.151.6** / 0.2.0 / 50.0.2 |
| CPU / RAM | Intel Core i7-12800H, 20 luồng / 15,7 GiB | Intel Core i3-1005G1 1,20 GHz, 4 luồng / 11,7 GiB |
| Wi-Fi | Intel Wi-Fi 6 AX201, 802.11ax, 2,4 GHz kênh 9, liên kết nhận / gửi 206 / 122 Mbps, tín hiệu 91 %, hồ sơ Private | Intel Wi-Fi 6 AX201, 802.11ax, kênh 9 (2,4 GHz), liên kết nhận / gửi 229 / 143 Mbps, tín hiệu 90 %, hồ sơ Private |
| Địa chỉ quảng bá | `192.168.1.7` | `192.168.1.16` |
| Đồng hồ | `QueryPerformanceCounter()`, độ phân giải 100 ns | như máy A |

Hai máy cùng một mạng Wi-Fi, cùng điểm phát. Dòng Wi-Fi do người dùng ghi bằng `netsh wlan show interfaces` ngày 2026-11-03, không ghi lại ngày đo; hai máy đã khởi động lại giữa hai ngày, IP không đổi. Tường lửa: quy tắc tạm của `n1_firewall.ps1` (máy A `-Role host`, máy B `-Role vm`), chỉ cho IP của máy kia. Trong lúc đo, app Teleport (bản zip) đã thoát trên cả hai máy.

**RTT kênh điều khiển** (máy A ↔ agent trên máy B, TCP): preflight 10 lần, trung vị 6,38 ms, lớn nhất 50,08 ms. Trong các lượt (lớn nhất của 3 ping trước mỗi lần đo có dùng kênh): lượt xuất hiện / thoát trung vị 8,59 ms, lớn nhất 49,00 ms; lượt giết trung vị 12,94 ms, lớn nhất 34,68 ms.

**Ca `link_down` trên máy thật.** Script hiện lời nhắc trên máy A; người dùng tắt Wi-Fi máy B (ô Wi-Fi trong bảng mạng của Windows) rồi nhấn Enter trên máy A; cắm lại cũng vậy. Cận trên tính từ lúc lời nhắc hiện, cận dưới từ lúc nhấn Enter; khoảng giữa hai mốc ở các lần hợp lệ là 3,2–6,5 s. Thời điểm tắt / bật thật lấy từ log `Microsoft-Windows-WLAN-AutoConfig/Operational` của máy B (sự kiện 8003 ngắt, 8001 kết nối; đồng hồ máy B lệch máy A dưới khoảng 1 s theo các mốc ghép được):

- Lần 3 của `run-20261105T012139969Z`: Wi-Fi tắt 01:25:55, **bật lại** 01:26:20–01:26:23 và 01:26:24–01:26:25 (người dùng bấm nhầm), rồi mới tắt hẳn tới 01:26:40; máy A báo mất lúc 01:26:35. Mạng không tắt liên tục nên lần này là **lỗi đo**, đã đo bù bằng `run-20261105T015352789Z`.
- Lần 7: Wi-Fi bật lại khoảng 1 s ngay lúc tắt (01:33:08–01:33:09); chỉ làm cận trên lớn hơn chừng 1,6 s, giữ.
- Các lần còn lại và hai lần đo bù: đúng một cặp ngắt → kết nối.

**Kết quả** (giây, cận trên, trên đồng hồ của máy A; “cận dưới lớn nhất” là giá trị lớn nhất trong các cận dưới)

| Ca | Hợp lệ / quá hạn / lỗi đo | Trung vị | p95 | Min | Max | Cận dưới lớn nhất | Kết luận |
|---|---|---|---|---|---|---|---|
| `appear_vm` | 10 / 0 / 0 | 1,126 | 1,142 | 1,077 | 1,142 | 1,121 | ĐẠT |
| `appear_host` | 10 / 0 / 0 | 1,101 | 1,157 | 1,048 | 1,157 | 1,151 | ĐẠT |
| `open_host` *(bổ sung)* | 10 / 0 / 0 | 0,124 | 0,182 | 0,062 | 0,182 | — | ĐẠT |
| `exit_vm` | 10 / 0 / 0 | 0,008 | 0,013 | 0,004 | 0,013 | 0,007 | ĐẠT |
| `exit_host` | 10 / 0 / 0 | 0,054 | 0,066 | 0,046 | 0,066 | 0,048 | ĐẠT |
| `link_down` (gộp hai lượt) | 11 / 0 / 1 | 47,834 | 81,076 | 28,154 | 81,076 | 77,566 | ĐẠT |
| `kill_vm` *(bổ sung)* | 10 / 0 / 0 | 52,073 | 79,131 | 24,311 | 79,131 | 79,100 | ĐẠT |
| `kill_host` *(bổ sung)* | 10 / 0 / 0 | 42,552 | 81,470 | 25,141 | 81,470 | 81,453 | ĐẠT |
| `link_down_reappear` (gộp, bỏ lần 3) | 10 / 1 / 0 | 17,034 | quá hạn | 17,022 | 17,051 (các lần ok) | 13,533 | chỉ ghi nhận |

Ở ba ca mất mạng / bị giết, mọi giá trị đều nằm dưới cận trên đã tính ở protocol mục 8. `exit_host` (máy B quan sát) chậm hơn `exit_vm` khoảng 45 ms, phù hợp với CPU yếu hơn của máy B; vẫn rất xa ngưỡng.

**Kết luận mvp N1 trên hai máy thật qua Wi-Fi 2,4 GHz: ĐẠT** cho phần xuất hiện, phần thoát app và phần mất mạng đột ngột (tắt Wi-Fi; app bị giết), 10 lần hợp lệ trở lên mỗi ca. Phần máy **ngủ** chưa đo trên máy thật (mục 3.4); với máy ảo, ca tạm dừng đã ĐẠT (mục 3.3).

**Ghi nhận** (không phải yêu cầu, không có ngưỡng)

- Thấy lại sau khi bật lại Wi-Fi: 10 lần nằm trong 17,022–17,051 s **tính từ lúc máy A báo mất** (lời nhắc cắm lại hiện ngay lúc đó), không phụ thuộc lúc người dùng bật Wi-Fi. Khớp với lần probe đầu tiên của thiết bị đã biến mất: `PROBE_INTERVAL` cộng thời gian resolve, sau đó probe thưa dần tới `MAX_PROBE_BACKOFF` (`core/discovery.py`). Máy A thấy lại nhờ tự hỏi, không phải nhờ máy B quảng bá lại khi có mạng.
- **Lần 10 của `run-20261105T012139969Z` quá hạn 300 s.** Máy A báo mất lúc 01:40:21,7; theo log WLAN, Wi-Fi máy B kết nối lại lúc 01:40:28 và giữ kết nối tới hết lượt (không có ngắt nào sau đó). Theo backoff ở trên, máy A lẽ ra đã probe node cũ khoảng 17, 49, 111 và 233 s sau khi mất, nhưng không thấy lại. Ngay sau khi quá hạn, script bật một node **mới** trên máy B và máy A thấy nó sau khoảng 1,5 s, nên mạng và mDNS của máy B lúc đó bình thường. Dữ liệu này chưa đủ để biết lỗi ở phía máy B (node đã sống qua lần card Wi-Fi mất IP) hay phía máy A (probe của tên cũ). Nếu là lỗi thật, một thiết bị mất mạng lâu hơn thời gian phát hiện (ở đây ít nhất khoảng 28 s) có thể không hiện lại trên radar nhiều phút sau khi mạng có lại.

**Giới hạn của lần đo này**

- Chỉ Wi-Fi 2,4 GHz, một điểm phát, một cặp Windows 11 ↔ Windows 10 LTSC 21H2; không có mạng dây.
- Mốc tắt Wi-Fi do người bấm: cận trên gồm thời gian phản ứng (3,2–6,5 s ở các lần hợp lệ). Kết luận dùng cận trên nên chỉ bảo thủ hơn.
- Máy B chạy Python 3.15.1 và zeroconf 0.151.6 (máy A 0.151.5): đều trong khoảng `pyproject.toml` cho phép, nhưng khác bản của máy A.
- Node đo đạc chạy từ mã nguồn bằng Python, không phải bản zip có giao diện; app không chạy song song trong lúc đo.
- Các node không ghép đôi, như mục 3.3.
- Kịch bản mất gói ở hai lần resolve đầu (protocol mục 8) **chưa đo**.

**Cách chạy lượt này** (khác mục 3.5): máy B cài mã nguồn đúng commit vào `C:\tp-bench\teleport\.venv` và chép `n1_common.py`, `n1_vm_agent.py`, `n1_firewall.ps1` vào `C:\tp-bench\tools`. PowerShell Administrator trên máy B: `n1_firewall.ps1 -Action open -Role vm -PeerIp <IP máy A> -Program <python gốc của máy B>`; trên máy A: `-Role host -PeerIp <IP máy B> -Program <python gốc của máy A>`. Rồi:

```
# máy B
C:\tp-bench\teleport\.venv\Scripts\python.exe n1_vm_agent.py --bind <IP máy B> --allow-host <IP máy A>
# máy A, trong n1-bench, PYTHONPATH trỏ src của mã cần đo
& $PY n1_host.py preflight --vm-ip <IP máy B>
& $PY n1_host.py run --vm-ip <IP máy B> --cases vm_subject,host_subject,open
& $PY n1_host.py run --vm-ip <IP máy B> --cases kill_vm,kill_host
& $PY n1_host.py run --vm-ip <IP máy B> --hv manual --cases link_down
```

Dừng `n1_host.py` bằng Ctrl+C giữa lượt thì phải khởi động lại agent trên máy B trước lượt sau: agent còn giữ node bị đo và từ chối bật node mới. Lời nhắc của `--hv manual` vẫn viết cho máy ảo (“bỏ chọn 'Cable connected'”): với máy thật, tắt / bật Wi-Fi rồi nhấn Enter. Kiểm thời điểm tắt / bật thật trên máy B:

```
Get-WinEvent -FilterHashtable @{LogName='Microsoft-Windows-WLAN-AutoConfig/Operational'; StartTime=<đầu lượt>; EndTime=<cuối lượt>} | Where-Object Id -in 8001,8003
```

Dọn: `n1_firewall.ps1 -Action close` trên cả hai máy.

## 4. mvp N3: Bộ nhớ

### 4.1. Định nghĩa phép đo

Đo bộ nhớ của **từng tiến trình node** (gửi, nhận) từ một tiến trình điều phối thứ ba, bằng `GetProcessMemoryInfo` của Windows (đọc qua `ctypes`, không dùng `psutil`). “RSS” ở đây là *working set* (`WorkingSetSize`); ghi kèm *private bytes* (`PrivateUsage`, bộ nhớ riêng đã cam kết), vì working set có cả trang dùng chung (DLL).

| Đại lượng | Cách lấy |
|---|---|
| RSS lúc bắt đầu | Working set đọc ngay trước khi điều phối ra lệnh gửi; lúc này hai node đã nối kết nối điều khiển và đã rảnh 3 s |
| RSS đỉnh | `PeakWorkingSetSize` (đỉnh do nhân ghi, không lỡ mẫu) đọc 0,5 s sau khi cả hai bên báo `TransferFinished`. Đỉnh này tính từ lúc tiến trình khởi động, nên luôn ≥ đỉnh thật trong lúc truyền; ghi kèm đỉnh nhân đọc lúc bắt đầu để biết đỉnh có rơi vào lúc truyền không |
| RSS tăng (cận trên) | RSS đỉnh − RSS lúc bắt đầu. Dùng giá trị này để kết luận |
| RSS tăng (lấy mẫu) | Working set lớn nhất trong các mẫu lấy mỗi 10 ms (thực tế khoảng 15 ms, theo nhịp hẹn giờ của Windows) từ lúc ra lệnh gửi tới 0,5 s sau khi xong, trừ RSS lúc bắt đầu; dùng để vẽ đường RSS |
| Private bytes tăng (cận trên) | `PeakPagefileUsage` sau cùng − private bytes lúc bắt đầu |
| Thông lượng (chỉ tham khảo, không phải mvp N2) | Kích thước file / (lúc bên gửi nhận `TransferFinished` − lúc bên gửi gọi `transfers.send`), cùng đồng hồ `time.perf_counter()` của tiến trình gửi. Gồm cả `offer`/`accept`, `fsync`, đọc lại và kiểm Merkle ở bên nhận |

Kết luận phần truyền: so RSS tăng (cận trên) với ngưỡng RSS tăng của mvp N3 theo cách hiểu chặt hơn (MB = 10⁶ byte); “không tăng theo kích thước” xét bằng hai cách: RSS tăng của 1 GiB so với 64 MiB, và đỉnh RSS lấy mẫu theo từng phần tư thời gian truyền 1 GiB.

**Phép đo qua CLI thật (từ mục 4.6).** Hai node là hai lệnh `teleport` thật, mỗi bên `TELEPORT_HOME` riêng: bên nhận `teleport receive --yes --json --dir <D> --port <p>`, bên gửi `teleport send <file> --to <mã máy nhận> --address 127.0.0.1:<p> --json`; cả hai để `--host` mặc định nên bật mDNS như khi người dùng chạy. Mốc của mỗi tiến trình là lúc điều phối đọc được dòng JSON tương ứng trên stdout của chính tiến trình đó. Các đại lượng khác bảng trên:

| Đại lượng | Cách lấy (chế độ CLI) |
|---|---|
| RSS lúc bắt đầu | Working set đọc ngay khi đọc được dòng `offer` của tiến trình đó (bên gửi: lượt vừa tạo, chưa gửi dữ liệu; bên nhận: vừa nhận `offer`). Ghi kèm `PeakWorkingSetSize` lúc đó (đỉnh lúc bắt đầu) |
| RSS đỉnh | Giá trị lớn hơn giữa `PeakWorkingSetSize` đọc 0,5 s sau dòng `result` muộn hơn của hai bên và working set lớn nhất trong các mẫu 10 ms; ghi kèm private bytes (mẫu 10 ms và `PeakPagefileUsage`) |
| Thời gian truyền của một tiến trình | Từ dòng `offer` tới dòng `result` của chính tiến trình đó, chia bốn phần bằng nhau Q1…Q4; max RSS Qk là working set lớn nhất trong các mẫu 10 ms của phần k |
| CPU | Thời gian CPU (người dùng + nhân) từ `GetProcessTimes`, đọc ở dòng `offer` và dòng `result` |
| Thông lượng (chỉ tham khảo) | Kích thước file / (dòng `result` − dòng `offer` của bên gửi) |

Tiêu chí phần truyền qua CLI, viết ngày 2026-10-26 **trước khi đo** và không đổi sau:

1. RSS tăng (cận trên) dưới ngưỡng RSS tăng của mvp N3, hiểu MB = 10⁶ byte, ở **mọi** lần đo, cả tiến trình gửi lẫn tiến trình nhận.
2. Đường RAM phẳng: ở mọi lần và cả hai tiến trình, max RSS Q4 − max RSS Q1 ≤ 4 MiB; và với mỗi tiến trình, trung vị RSS tăng (cận trên) của 10 GiB − trung vị của 1 GiB ≤ dao động của các lần 1 GiB (lớn nhất − nhỏ nhất RSS tăng, cận trên).
3. Mọi lần: SHA-256 file nhận khớp file nguồn; thư mục `.teleport` trong thư mục nhận không còn file nào sau khi bên nhận thoát; `send` thoát mã 0 và `receive` thoát mã 0 khi dừng bằng Ctrl+C (`CTRL_BREAK_EVENT`).

Số lần: 1 GiB × 10, 5 GiB × 5, 10 GiB × 5, xen thứ tự. **ĐẠT** khi đủ số lần hợp lệ và cả ba tiêu chí đúng ở mọi lần; lần nào sai tiêu chí 3 hoặc quá hạn thì **KHÔNG ĐẠT**; lỗi đo (môi trường hỏng) không tính, đo bù.

**Qua card mạng giữa hai máy** (viết ngày 2026-10-26, trước khi đo). Bên gửi là `teleport send … --address <IP máy nhận>:47474 --json` trên host, đo như bảng trên. Bên nhận là `teleport receive --yes --json --dir <D> --port 47474` trên máy thật thứ hai, đo bằng một script chạy trên chính máy đó, cùng các đại lượng và cùng cách lấy mốc như bảng trên nhưng trên đồng hồ của máy nhận (không so mốc giữa hai máy); hai phía ghép theo `transfer_id`. Mỗi lần đo bật `receive` mới; máy nhận rảnh 3 s sau dòng `receiving` rồi mới báo sẵn sàng, host chờ báo đó mới gửi. Lý do: `receive` mở cổng trước khi in `receiving` và in dồn các sự kiện tới sớm, nên lượt bắt đầu trước mốc sẵn sàng thì mốc `offer` không dùng được; lần như vậy là **lỗi đo**. Tiêu chí 1, 2 (phần Q4 − Q1) và 3 ở trên áp dụng cho từng lần, cả hai phía; phần so 10 GiB với 1 GiB của tiêu chí 2 dùng các lần 1 GiB qua cùng mạng (lượt đo mvp N2, mục 5.1) nếu có, không có thì ghi chưa xét.

**Lúc rảnh qua CLI (chỉ ghi nhận).** `teleport receive --yes --json --dir <D> --port <p>` (mDNS bật như mặc định) chạy 10 phút, một thiết bị tin cậy giữ kết nối điều khiển với nó suốt thời gian đó. Mỗi giây đọc working set, private bytes, và CPU tính theo % một lõi (Δ thời gian CPU / Δ thời gian thực × 100). Không dùng để kết luận phần lúc rảnh của mvp N3: phần đó cần app có giao diện (Giai đoạn 4).

### 4.2. Phương pháp

- Hai node là **hai tiến trình Python riêng**, mỗi bên một thư mục cấu hình riêng (danh tính riêng), đã tin nhau: `trusted.json` dựng sẵn bằng `TrustStore.add` như fixture `trust_each_other` của test, không qua ghép đôi. Nghe `127.0.0.1` cổng ngẫu nhiên, không mDNS. Bên gửi nối kết nối điều khiển tới bên nhận bằng `Node.connect_hint`; kết nối dữ liệu đi cùng chiều.
- Bên nhận: `Node(receive_dir=…, auto_accept=True)`; bên gửi gọi `node.transfers.send(device_id, [path])`. Cấu hình mặc định của mã, không vá hằng số nào (khác test: không đổi `connection.DRAIN_TIMEOUT`), không giới hạn tốc độ.
- File nguồn là dữ liệu ngẫu nhiên (`os.urandom`), tạo một lần mỗi lượt, đặt cùng ổ với thư mục nhận. Mỗi lần đo bật hai tiến trình mới, truyền một file, so SHA-256 file nhận với file nguồn, xóa file nhận, tắt hai node (`Node.close()`).
- Lặp 10 vòng; mỗi vòng đo cả 64 MiB và 1 GiB, đổi thứ tự xen kẽ giữa các vòng. Mọi lần chờ có giới hạn (một lần truyền tối đa 600 s, cả lượt tối đa 3 giờ); kết thúc thì tắt mọi tiến trình và xóa thư mục làm việc (file nguồn, thư mục nhận, thư mục cấu hình).

### 4.3. Lần đo 2026-10-26: đo sơ bộ Giai đoạn 2, loopback trên một máy

Lượt `run-20261025T182834Z` (giờ UTC). Mã đo: nhánh `feat/transfer-manager`, commit `5c2ed74` cộng thay đổi chưa commit của bước gắn engine truyền file vào `Node` (`src/teleport/app/node.py` sửa, `src/teleport/app/transfers.py` mới); digest mã nguồn `src/teleport` (SHA-256 trên đường dẫn + nội dung mọi file `.py`) `a7143d814e2b7637582f1c7cd61f7ca8f91ae62647e4e9526675694e030624d4`. Script: `n3_bench.py`, `n3_node.py` (mục 4.5).

**Môi trường**

| | |
|---|---|
| Hệ điều hành | Windows 11, bản 10.0.26300 |
| Python | 3.14.5 (64 bit), `.venv` của repo |
| Teleport | `__version__` 0.0.1 (mã nạp từ `src/` của worktree, đã kiểm trong từng tiến trình) |
| cryptography / zeroconf / ifaddr | 50.0.2 / 0.151.5 / 0.2.0 (zeroconf không dùng: tắt mDNS) |
| CPU | Intel Core i7-12800H, 20 luồng |
| RAM | 15,7 GiB; còn trống lúc bắt đầu lượt 3,4 GiB (máy đang chạy các ứng dụng khác) |
| Ổ đĩa | NVMe SSD SSSTC CL1-3D512-Q11 512 GB; file nguồn và thư mục nhận cùng ổ |
| Mạng | Loopback `127.0.0.1` (không qua card mạng) |

**Kết quả** (10 lần hợp lệ mỗi cỡ, 0 lần hỏng; mọi lần đều `done` ở cả hai bên, SHA-256 khớp, không sót file trong thư mục nhận, hai tiến trình thoát mã 0). Đơn vị MiB; mỗi ô là trung vị / p95 / min / max.

| Cỡ file | Tiến trình | RSS lúc bắt đầu | RSS đỉnh (nhân) | RSS tăng, cận trên | RSS tăng, lấy mẫu | Private bytes lúc bắt đầu | Private bytes tăng, cận trên |
|---|---|---|---|---|---|---|---|
| 64 MiB | gửi | 49,7 / 50,1 / 49,1 / 50,1 | 53,5 / 54,0 / 53,2 / 54,0 | 3,9 / 4,2 / 3,2 / 4,2 | 3,9 / 4,2 / 3,2 / 4,2 | 31,5 / 32,1 / 30,9 / 32,1 | 3,7 / 4,0 / 2,7 / 4,0 |
| 64 MiB | nhận | 49,4 / 50,5 / 49,2 / 50,5 | 60,8 / 61,4 / 57,0 / 61,4 | 11,2 / 12,0 / 6,5 / 12,0 | 8,7 / 9,4 / 3,3 / 9,4 | 31,6 / 32,2 / 31,3 / 32,2 | 11,6 / 12,3 / 6,8 / 12,3 |
| 1 GiB | gửi | 49,8 / 50,3 / 49,3 / 50,3 | 53,6 / 54,0 / 53,0 / 54,0 | 3,8 / 4,2 / 3,5 / 4,2 | 3,8 / 4,2 / 3,5 / 4,2 | 31,6 / 32,6 / 31,2 / 32,6 | 3,6 / 3,9 / 3,0 / 3,9 |
| 1 GiB | nhận | 49,3 / 49,8 / 49,1 / 49,8 | 61,3 / 61,9 / 60,3 / 61,9 | 11,7 / 12,6 / 10,8 / 12,6 | 10,3 / 11,7 / 8,8 / 11,7 | 31,6 / 32,2 / 31,3 / 32,2 | 12,1 / 13,1 / 10,5 / 13,1 |

Ở cả 40 lần (2 cỡ × 2 tiến trình × 10), đỉnh nhân đọc lúc bắt đầu bằng đúng RSS lúc bắt đầu, nên “RSS đỉnh (nhân)” chính là đỉnh trong lúc truyền, không lẫn đỉnh lúc khởi động.

**Đường RSS khi truyền 1 GiB** (RSS lớn nhất trong từng phần tư thời gian truyền, MiB, theo mẫu)

| Lần | Thời gian (s) | Gửi: Q1 / Q2 / Q3 / Q4 | Nhận: Q1 / Q2 / Q3 / Q4 |
|---|---|---|---|
| 2 | 15,6 | 53,2 / 53,2 / 53,2 / 53,2 | 58,3 / 58,6 / 58,5 / 58,5 |
| 3 | 10,5 | 53,6 / 53,6 / 53,6 / 53,6 | 58,2 / 58,3 / 60,0 / 58,2 |
| 6 | 8,8 | 53,9 / 53,9 / 53,9 / 53,9 | 57,7 / 59,8 / 58,0 / 57,1 |
| 7 | 10,3 | 53,7 / 53,7 / 53,7 / 53,7 | 58,7 / 58,6 / 60,6 / 60,5 |
| 10 | 12,9 | 53,4 / 53,4 / 53,4 / 53,5 | 58,3 / 57,4 / 59,6 / 58,8 |
| 11 | 8,2 | 54,0 / 54,0 / 54,0 / 54,0 | 59,3 / 58,6 / 59,3 / 58,1 |
| 14 | 11,7 | 53,7 / 53,7 / 53,7 / 53,7 | 59,1 / 58,4 / 58,5 / 58,4 |
| 15 | 11,4 | 53,0 / 53,0 / 53,0 / 53,0 | 58,1 / 59,4 / 55,5 / 58,5 |
| 18 | 7,4 | 54,0 / 54,0 / 54,0 / 54,0 | 60,2 / 59,0 / 58,7 / 58,7 |
| 19 | 15,0 | 53,2 / 53,2 / 53,2 / 53,2 | 59,7 / 58,7 / 60,9 / 60,5 |

**Thông lượng loopback** (chỉ tham khảo, không phải mvp N2; trung vị / p95 / min / max)

| Cỡ file | MB/s (10⁶ byte/s) | Thời gian (s) |
|---|---|---|
| 64 MiB | 133,6 / 162,9 / 18,2 / 162,9 | 0,50 / 3,70 / 0,41 / 3,70 |
| 1 GiB | 98,1 / 145,8 / 68,7 / 145,8 | 10,97 / 15,63 / 7,37 / 15,63 |

Lần chậm nhất của 64 MiB (18,2 MB/s, 3,70 s) là lần đo đầu tiên của lượt, ngay sau khi tạo file nguồn; lần đo này không tìm hiểu nguyên nhân. Thông lượng dao động mạnh vì hai node, file nguồn và thư mục nhận dùng chung CPU và ổ, và máy đang chạy các ứng dụng khác.

**Kết luận**

- RSS tăng khi truyền 1 GiB: cận trên lớn nhất 12,6 MiB (tiến trình nhận), 4,2 MiB (tiến trình gửi), dưới ngưỡng của mvp N3 ở cả 10 lần, cả hai tiến trình: **ĐẠT** (tiêu chí sơ bộ).
- Không tăng theo kích thước: RSS tăng của 1 GiB so với 64 MiB khác nhau trong khoảng dao động giữa các lần (gửi: trung vị 3,8 so với 3,9 MiB; nhận: 11,7 so với 11,2 MiB, cỡ 64 MiB tự dao động 6,5–12,0 MiB); trong lúc truyền 1 GiB, đường RSS phẳng (bảng trên, không phần tư nào tăng dần): **ĐẠT** với hai cỡ đã đo.
- **mvp N3 nói chung: CHƯA ĐỦ DỮ LIỆU**: mvp N3 đòi cả các cỡ lớn hơn và phần lúc rảnh (mục 4.4).

**Ghi nhận** (không phải kết luận)

- Lúc rảnh (đã nối kết nối điều khiển, chưa truyền), working set mỗi tiến trình node khoảng 49–50,5 MiB, private bytes khoảng 31–32,6 MiB. Đây là node không có giao diện và **không bật mDNS**, nên không dùng để kết luận phần lúc rảnh của mvp N3.
- Tiến trình nhận tăng nhiều hơn tiến trình gửi (khoảng 11–12 MiB so với 4 MiB). Lần đo này không tách xem phần tăng đó thuộc phần nào của mã.

**Giới hạn của lần đo này**

- Hai tiến trình trên cùng một máy, qua loopback: không qua card mạng, không có mất gói hay trễ thật; khi mạng chậm hơn đĩa, hàng chờ ở hai bên có thể đầy theo cách khác.
- Ổ đích là NVMe SSD nhanh và dùng chung với ổ nguồn; ca “ổ đích chậm” (bên nhận phải chờ đĩa) chưa đo.
- File nguồn vừa được tạo nên nằm trong bộ đệm file của Windows; bộ đệm file của hệ điều hành không tính vào working set của tiến trình, và phép đo này không đo nó.
- Chỉ một file mỗi lượt, một lượt mỗi lần; không đo nhiều file hay nhiều lượt cùng lúc. Không giới hạn tốc độ.
- Chỉ Windows 11 và Python 3.14; chưa đo Linux, macOS, Python 3.12.

### 4.4. Việc còn lại

- File 1 GiB, 5 GiB và 10 GiB qua CLI thật trên loopback: đã đo, ĐẠT (mục 4.6).
- Ổ đích chậm mà RAM không tăng: **chưa đo**; USB có sẵn không dùng được (FAT32, mục 4.8). Cần một USB định dạng NTFS hoặc exFAT, còn ≥ 8 GB trống (định dạng lại USB hiện có thì xóa dữ liệu trên đó: người dùng quyết), hoặc ổ ảo giới hạn tốc độ trong máy ảo. Script đã có `--recv-dir` (mục 4.5). Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D4).
- 10 GiB từ host sang máy thật thứ hai (Windows, Wi-Fi) qua card mạng, RAM hai phía ([ke_hoach.md](ke_hoach.md) mục 5.4, D3): đã đo **1 lần** qua Wi-Fi 2,4 GHz (mục 4.10), ĐẠT theo quyết định của người dùng (1 lần là đủ). Còn **chưa đo**: mạng dây, và phần so 10 GiB với 1 GiB của tiêu chí 2 (cần các lần 1 GiB qua cùng mạng, lượt mvp N2 mục 5.1).
- Phần lúc rảnh của mvp N3: lệnh CLI đã ghi nhận (mục 4.7); app có giao diện **chưa đo** (Giai đoạn 4). Đo CPU cần tránh bẫy lõi tiết kiệm điện của Windows (EcoQoS).
- Hệ điều hành khác (Linux, macOS làm bên nhận và bên gửi), Python 3.12: **chưa đo**. Hệ điều hành khác thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D7); Python 3.12 đo được trên máy này, không thuộc đợt đo.

### 4.5. Cách đo lại

Script nằm ngoài repo (không commit): `n3_bench.py` (điều phối, đọc bộ nhớ, tóm tắt) và `n3_node.py` (một node trong tiến trình riêng, điều khiển qua stdin/stdout bằng JSON Lines; stdin đọc bằng `os.read` trong thread). Chỉ chạy trên Windows. Trong PowerShell, ở thư mục chứa hai script:

```
$env:PYTHONPATH = "<thư mục repo hoặc worktree>\src"
& "<repo>\.venv\Scripts\python.exe" n3_bench.py --repeat 10 --sizes 64MiB,1GiB
```

`--sizes` nhận `64MiB`, `256MiB`, `1GiB`, `5GiB`; `--settle` (mặc định 3 s) là thời gian rảnh trước khi gửi, `--sample-ms` (mặc định 10) là nhịp lấy mẫu, `--work` là thư mục làm việc (mặc định `work/` cạnh script; bị xóa khi xong, trừ khi có `--keep`). Mỗi lượt ghi vào `results/run-<giờ UTC>/`: `results.jsonl` (môi trường, cấu hình, từng lần đo kèm mọi sự kiện của hai node), `samples-<lần>-<cỡ>.csv` (đường RSS và private bytes theo thời gian), `summary.md`, `summary.json`, và stderr của từng tiến trình node.

**Qua CLI thật (mục 4.6, 4.7).** Cùng thư mục có `n3_cli.py` (chạy lệnh `teleport` thật bằng `python -m teleport`, dùng lại phần đọc bộ nhớ của `n3_bench.py` và `n3_node.py` làm thiết bị giữ kết nối ở chế độ `idle`) và `n3_cli_report.py` (in bảng từ `results.jsonl`). `.venv\Scripts\python.exe` là trình chuyển tiếp: nó bật python gốc làm tiến trình con, nên script tìm tiến trình con đó (Toolhelp32 theo PID cha) và đo nó. Ctrl+C cho `receive` là `CTRL_BREAK_EVENT` gửi tới nhóm tiến trình riêng của lệnh.

```
$env:PYTHONPATH = "<thư mục repo hoặc worktree>\src"
$PY = "<repo>\.venv\Scripts\python.exe"
& $PY n3_cli.py transfer --plan 1GiB:10,5GiB:5,10GiB:5      # mục 4.6
& $PY n3_cli.py transfer --plan 1GiB:5,5GiB:1 --recv-dir E:\  # thư mục nhận trên ổ khác (ổ chậm), chưa chạy
& $PY n3_cli.py idle --duration 600                          # mục 4.7
$env:PYTHONIOENCODING = "utf-8"; & $PY n3_cli_report.py results\cli-transfer-<giờ UTC>\results.jsonl
```

`transfer` kiểm chỗ trống trước (mặc định ≥ 30 GiB, `--min-free-gib`; trước mỗi lần còn kiểm ≥ cỡ file + 2 GiB trên ổ nhận), tạo file nguồn ngẫu nhiên một lần mỗi cỡ, xếp thứ tự xen kẽ các cỡ, xóa file nhận sau mỗi lần và xóa thư mục làm việc khi xong. Kết quả ở `results/cli-transfer-<giờ UTC>/` và `results/cli-idle-<giờ UTC>/` (`results.jsonl` hoặc `results.json`, mẫu `.csv`, `summary.md`, stderr của từng lệnh).

**Qua card mạng với máy thật thứ hai (mục 4.1, 5.1).** Cùng thư mục có `n3_net_host.py` (host: chạy `teleport send` và `robocopy`, đo RAM bên gửi), `may2_nhan.py` (máy thứ hai, một file độc lập chỉ cần thư viện chuẩn: chạy `teleport receive`, đo RAM bên nhận, SHA-256 file nhận, mã thoát; ghi file sẵn sàng vào share), `may2_chuanbi.ps1` (máy thứ hai: quy tắc tường lửa tạm chỉ cho IP host và hồ sơ Private, share SMB và tài khoản tạm; `-Action close` gỡ hết) và `n3_net_report.py` (ghép hai phía theo `transfer_id`, in bảng). Hướng dẫn từng bước cho cả hai máy, kể cả dọn dẹp: `HUONG-DAN-MAY-THU-HAI.md` trong thư mục đó. Lệnh chính:

```
# máy thứ hai (c3: bỏ --no-sha; c4: giữ --no-sha)
& $PY2 may2_nhan.py --home C:\tp-bench\home --dir C:\tp-bench\share\teleport --runs 0 [--no-sha]
# host
& $PY n3_net_host.py --home <home đo> --to May2-Bench --address <IP2>:47474 --ready-file \\<IP2>\tpbench\san-sang.txt --plan 10GiB:3
& $PY n3_net_host.py --home <home đo> --to May2-Bench --address <IP2>:47474 --ready-file \\<IP2>\tpbench\san-sang.txt --smb \\<IP2>\tpbench\smb --plan 1GiB:5,5GiB:5
& $PY n3_net_report.py --host results\net-<giờ UTC>\results.jsonl --may2 <thư mục may2-…>\results.jsonl
```

Hai script đã chạy thử trọn vòng trên một máy (hai danh tính tạm, loopback, “SMB” là thư mục cục bộ, file 64 MiB), kể cả nhánh máy nhận chưa sẵn sàng; chưa chạy giữa hai máy thật.

### 4.6. Lần đo 2026-10-26: qua CLI thật, loopback trên một máy

Lượt `cli-transfer-20261026T023051Z` (giờ UTC; lần đo đầu bắt đầu 02:34, lần cuối 02:56; cả lượt 1574 s, gồm 219 s tạo file nguồn). Tiêu chí: mục 4.1, viết trước lượt này.

Mã đo: worktree `p2-8`, nhánh `chore/phase2-close`, commit `ce6dc2f`, `src/` không sửa. Lệnh chạy bằng `python.exe` của `.venv` ở checkout chính, nhưng mã nạp từ `src/` của worktree `p2-8` qua `PYTHONPATH` (đã kiểm `teleport.__file__`), không phải từ bản cài editable. Cây `src` của `ce6dc2f` trùng cây `src` của `513c963` (merge #29 trên `main`): cùng git tree `7977d30`. Digest `src/teleport` (cách tính ở mục 4.3) của worktree: `6c973c2ab839ce60b53153236decbe1bce893c98cd3fa4b89f0e92e920e7c301`; checkout chính cho digest khác chỉ vì kết thúc dòng CRLF ở 4 file (so bỏ CR thì không khác). Kết quả dưới đây áp dụng cho commit khác khi `src/teleport/core`, `trust`, `net`, `app` không đổi so với cây này; đổi các phần đó thì phải đo lại.

**Môi trường**

| | |
|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 |
| Python | 3.14.5 (64 bit, `C:\Python314`, qua `.venv`) |
| Teleport | `__version__` 0.0.1 |
| cryptography / zeroconf / ifaddr | 50.0.2 / 0.151.5 / 0.2.0; mDNS bật ở cả hai lệnh (`receiving.discovery: true` ở mọi lần) |
| CPU | Intel Core i7-12800H, 20 luồng |
| RAM | 15,7 GiB; còn trống lúc bắt đầu lượt 5,1 GiB |
| Ổ đĩa | NVMe SSD SSSTC CL1-3D512-Q11 512 GB; file nguồn và thư mục nhận cùng ổ; trống 50,7 GiB trước lượt, 33,6–34,5 GiB trước từng lần đo |
| Mạng | loopback: `send --address 127.0.0.1:<p>`; hai lệnh vẫn nghe `0.0.0.0` như mặc định |
| Nguồn điện | cắm sạc, không bật tiết kiệm pin; power plan Balanced, chế độ nguồn của Windows 11 là **Best power efficiency** (overlay `961cc777-2547-4f9d-8174-7d86181b8a7a`), không phải Best performance như kế hoạch đo đề ra; người đo không đổi cài đặt này |
| Defender | bảo vệ thời gian thực bật (giữ như thực tế) |
| Tiến trình node | không ở Efficiency mode: `ProcessPowerThrottling` không đặt (ControlMask = StateMask = 0) và lớp ưu tiên Normal ở cả hai tiến trình, mọi lần |
| Tải khác | lúc bắt đầu lượt không có tiến trình python, pytest hay PyInstaller nào khác; theo phiên điều phối, các agent khác chạy pytest và build PyInstaller trên máy này trong lúc lượt chạy (script không ghi tên tiến trình). CPU cả máy bận (`GetSystemTimes`, trong từng lần đo): 12,1–21,9 %, trong đó hai node Teleport chiếm chừng một lõi (khoảng 5 % của 20 luồng) |

Ảnh hưởng của tải khác: working set là bộ nhớ của chính tiến trình, tải CPU của tiến trình khác không làm nó tăng. Thiếu RAM thì Windows có thể cắt working set, làm số đo *thấp* hơn thật; private bytes (bộ nhớ cam kết, không bị cắt) dùng để đối chiếu: private bytes tăng (cận trên) lớn nhất 13,0 MiB, cùng cỡ RSS tăng lớn nhất 12,6 MiB, nên không thấy dấu hiệu working set bị cắt. Thông lượng thì chịu ảnh hưởng (chỉ tham khảo).

**Kết quả** (20 lần hợp lệ, 0 lần hỏng; thứ tự 1, 5, 10, 1 | 1, 10, 5, 1 | … GiB, xem `results.jsonl`). Đơn vị MiB; mỗi ô là trung vị / p95 / min / max.

| Cỡ file | Số lần | Tiến trình | RSS lúc bắt đầu | RSS đỉnh | RSS tăng, cận trên | RSS tăng, lấy mẫu | Max Q4 − max Q1 | Private bytes lúc bắt đầu | Private bytes tăng, cận trên |
|---|---|---|---|---|---|---|---|---|---|
| 1 GiB | 10 | gửi | 52,7 / 53,3 / 52,4 / 53,3 | 57,3 / 58,3 / 56,8 / 58,3 | 4,5 / 5,0 / 4,2 / 5,0 | 4,5 / 5,0 / 4,2 / 5,0 | 0,0 / 0,2 / 0,0 / 0,2 | 33,2 / 34,0 / 32,5 / 34,0 | 4,1 / 4,5 / 3,5 / 4,5 |
| 1 GiB | 10 | nhận | 54,0 / 54,8 / 53,6 / 54,8 | 65,1 / 66,3 / 64,6 / 66,3 | 11,0 / 12,5 / 10,3 / 12,5 | 9,5 / 11,4 / 8,2 / 11,4 | −0,2 / 2,0 / −2,5 / 2,0 | 34,2 / 34,8 / 33,6 / 34,8 | 11,9 / 13,0 / 11,3 / 13,0 |
| 5 GiB | 5 | gửi | 52,7 / 53,1 / 52,5 / 53,1 | 57,5 / 57,9 / 57,1 / 57,9 | 4,8 / 4,9 / 4,6 / 4,9 | 4,8 / 4,9 / 4,6 / 4,9 | 0,0 / 0,3 / 0,0 / 0,3 | 33,4 / 33,6 / 33,0 / 33,6 | 4,1 / 4,3 / 4,0 / 4,3 |
| 5 GiB | 5 | nhận | 54,2 / 54,5 / 54,1 / 54,5 | 65,8 / 66,1 / 64,5 / 66,1 | 11,6 / 11,7 / 10,3 / 11,7 | 10,9 / 11,5 / 9,7 / 11,5 | −0,4 / 0,8 / −2,3 / 0,8 | 34,7 / 34,9 / 34,5 / 34,9 | 12,0 / 12,9 / 11,2 / 12,9 |
| 10 GiB | 5 | gửi | 52,6 / 52,8 / 52,5 / 52,8 | 57,9 / 58,2 / 57,1 / 58,2 | 5,3 / 5,4 / 4,6 / 5,4 | 5,3 / 5,4 / 4,6 / 5,4 | −0,1 / 0,6 / −0,7 / 0,6 | 33,2 / 33,6 / 33,1 / 33,6 | 4,3 / 4,8 / 4,2 / 4,8 |
| 10 GiB | 5 | nhận | 54,2 / 54,5 / 53,4 / 54,5 | 66,1 / 66,9 / 65,4 / 66,9 | 12,0 / 12,6 / 11,7 / 12,6 | 11,2 / 11,4 / 10,6 / 11,4 | −0,4 / 0,5 / −1,2 / 0,5 | 34,5 / 35,1 / 33,7 / 35,1 | 12,7 / 13,0 / 11,9 / 13,0 |

Ở cả 40 cặp (20 lần × 2 tiến trình), đỉnh nhân đọc lúc `offer` bằng đúng RSS lúc bắt đầu, và đỉnh nhân sau cùng lớn hơn nó: RSS đỉnh là đỉnh trong lúc truyền, không lẫn đỉnh lúc khởi động. Tiến trình gửi đã thoát trước lúc đọc đỉnh (20/20 lần); đỉnh vẫn đọc được qua handle còn mở và gồm cả lúc đóng node, nên vẫn là cận trên. Nhịp mẫu: trung vị 10,4 ms, khe lớn nhất 64,1 ms (đỉnh nhân không lỡ gì trong các khe đó).

**Đường RSS khi truyền 5 GiB và 10 GiB** (working set lớn nhất trong từng phần tư thời gian truyền của mỗi tiến trình, MiB, theo mẫu)

| Lần | Cỡ | Thời gian gửi (s) | Gửi: Q1 / Q2 / Q3 / Q4 | Nhận: Q1 / Q2 / Q3 / Q4 |
|---|---|---|---|---|
| 2 | 5 GiB | 131,4 | 57,9 / 57,9 / 57,9 / 57,9 | 64,8 / 64,7 / 65,5 / 65,6 |
| 3 | 10 GiB | 172,6 | 57,9 / 57,2 / 57,2 / 57,2 | 64,2 / 63,7 / 63,6 / 63,6 |
| 6 | 10 GiB | 143,4 | 57,8 / 57,9 / 57,4 / 57,5 | 64,8 / 65,7 / 65,7 / 65,2 |
| 7 | 5 GiB | 70,9 | 57,5 / 57,4 / 57,5 / 57,5 | 64,1 / 64,6 / 64,5 / 64,5 |
| 10 | 5 GiB | 52,6 | 57,6 / 57,6 / 57,6 / 57,6 | 65,4 / 64,9 / 65,2 / 63,1 |
| 11 | 10 GiB | 111,3 | 57,8 / 57,8 / 57,8 / 57,9 | 65,4 / 65,2 / 64,7 / 65,2 |
| 14 | 10 GiB | 126,2 | 57,0 / 57,1 / 56,9 / 56,9 | 65,1 / 65,1 / 64,5 / 63,9 |
| 15 | 5 GiB | 56,3 | 57,0 / 57,0 / 57,3 / 57,3 | 63,7 / 63,7 / 64,0 / 63,3 |
| 18 | 5 GiB | 52,0 | 56,9 / 57,1 / 57,1 / 57,1 | 65,1 / 65,1 / 65,5 / 64,6 |
| 19 | 10 GiB | 115,3 | 57,6 / 57,6 / 58,2 / 58,2 | 65,4 / 64,6 / 65,1 / 65,0 |

Các lần 1 GiB nằm trong cột “Max Q4 − max Q1” của bảng trên (lớn nhất 2,0 MiB, lần 12, tiến trình nhận).

**Thông lượng loopback và CPU** (chỉ tham khảo, không phải mvp N2; trung vị / p95 / min / max; CPU tính theo % một lõi trong thời gian truyền của tiến trình đó)

| Cỡ file | MB/s (10⁶ byte/s) | Thời gian gửi (s) | CPU gửi (%) | CPU nhận (%) | CPU cả máy bận (%) |
|---|---|---|---|---|---|
| 1 GiB | 120,7 / 159,0 / 38,6 / 159,0 | 8,9 / 27,8 / 6,8 / 27,8 | 27,9 / 37,8 / 9,9 / 37,8 | 67,8 / 85,5 / 21,1 / 85,5 | 16,2 / 21,9 / 12,3 / 21,9 |
| 5 GiB | 95,3 / 103,2 / 40,9 / 103,2 | 56,3 / 131,4 / 52,0 / 131,4 | 28,1 / 31,9 / 13,8 / 31,9 | 62,4 / 81,8 / 34,2 / 81,8 | 16,1 / 21,1 / 12,1 / 21,1 |
| 10 GiB | 85,1 / 96,5 / 62,2 / 96,5 | 126,2 / 172,6 / 111,3 / 172,6 | 25,8 / 31,1 / 15,6 / 31,1 | 67,6 / 74,5 / 37,4 / 74,5 | 19,0 / 20,2 / 15,0 / 20,2 |

Bốn lần đầu của lượt (lần 1–4, ngay sau khi tạo 16 GiB file nguồn, lúc máy có tải khác) chậm hơn rõ: 38,6–62,2 MB/s; lần đo này không tách nguyên nhân. Thời gian gửi tính từ dòng `offer` tới dòng `result` của `send`, gồm cả `fsync`, đọc lại và kiểm Merkle ở bên nhận.

**Đánh giá theo tiêu chí mục 4.1**

| Tiêu chí | Số đo | Kết quả |
|---|---|---|
| 1. RSS tăng (cận trên) dưới ngưỡng mvp N3 mọi lần, hai tiến trình | lớn nhất: gửi 5,4 MiB, nhận 12,6 MiB (13 164 544 byte, lần 6, 10 GiB) | **ĐẠT** (20/20 lần, cả hai tiến trình) |
| 2a. Max Q4 − max Q1 ≤ 4 MiB mọi lần, hai tiến trình | lớn nhất 2,0 MiB (lần 12, nhận) | **ĐẠT** (40/40) |
| 2b. Trung vị RSS tăng 10 GiB − trung vị 1 GiB ≤ dao động các lần 1 GiB | gửi: 5,27 − 4,54 = 0,73 MiB ≤ 0,85 MiB (4,18–5,03); nhận: 12,01 − 10,97 = 1,03 MiB ≤ 2,25 MiB (10,29–12,54) | **ĐẠT** (cả hai tiến trình) |
| 3. SHA-256 khớp, `.teleport` không còn file, `send` và `receive` thoát mã 0 | 20/20 lần: hai bên `result: done`, SHA-256 khớp, `.teleport` trống, mã thoát 0 / 0 (cả trình chuyển tiếp lẫn python con); `receive` dừng sau Ctrl+C trong 0,30–0,40 s | **ĐẠT** |

**Kết luận phần truyền qua CLI trên loopback (1 GiB, 5 GiB, 10 GiB; hai tiến trình): ĐẠT** cả ba tiêu chí, đủ số lần (10 / 5 / 5), không lần nào quá hạn hay hỏng. mvp N3 nói chung vẫn **CHƯA ĐỦ DỮ LIỆU**: còn ổ đích chậm, 10 GiB qua card mạng giữa hai máy, và phần lúc rảnh (mục 4.4).

**Ghi nhận** (không phải kết luận)

- Trung vị RSS tăng của tiến trình gửi nhích dần theo cỡ: 4,54 / 4,81 / 5,27 MiB với 1 / 5 / 10 GiB (nhận: 10,97 / 11,58 / 12,01 MiB). Phần chênh nằm trong tiêu chí 2b nhưng sát biên ở bên gửi (0,73 so với 0,85 MiB); trong từng lần, đường RSS vẫn phẳng (tiêu chí 2a). Lần đo này không tách phần chênh đó đến từ đâu; đo thêm cỡ lớn hơn (ví dụ 20 GiB) sẽ cho biết nó có tiếp tục tăng không: **chưa đo**.
- Mức RSS lúc bắt đầu qua CLI (gửi khoảng 52,7 MiB, nhận khoảng 54 MiB) cao hơn node API không mDNS ở mục 4.3 (khoảng 49,5 MiB); lệnh CLI có bật mDNS và nạp thêm mã CLI, nhưng lần đo này không tách phần chênh thuộc về đâu. Phần tăng khi truyền gần với mục 4.3.

**Giới hạn của lần đo này**

- Hai tiến trình trên một máy qua loopback; ổ đích là NVMe nhanh, dùng chung với ổ nguồn. Ổ đích chậm và hai máy thật qua card mạng chưa đo (mục 4.4).
- Máy đang ở chế độ nguồn Best power efficiency và có tải của các agent khác: ảnh hưởng thông lượng và CPU, không thấy ảnh hưởng tới RAM (đối chiếu private bytes ở trên).
- Một file mỗi lượt, không giới hạn tốc độ; chỉ Windows 11 và Python 3.14.

### 4.7. Lần đo 2026-10-26: lúc rảnh qua CLI, chỉ ghi nhận

Lượt `cli-idle-20261026T025718Z` (giờ UTC, 02:57:26–03:07:32). Cùng mã đo và cách nạp mã như mục 4.6 (commit `ce6dc2f`, `src/` của worktree `p2-8`), cùng máy và chế độ nguồn. Định nghĩa: mục 4.1, “Lúc rảnh qua CLI”. Script: `n3_cli.py idle --duration 600` (mục 4.5).

**Cấu hình**

- `teleport receive --yes --json --dir <D> --port <p>`, `--host` mặc định nên nghe `0.0.0.0` và bật mDNS (quảng bá và duyệt); `receiving` báo `discovery: true`, quảng bá `192.168.1.7` (Wi-Fi). Thư mục nhận trống, không có lượt truyền nào.
- Thiết bị tin cậy giữ kết nối: một node API (`n3_node.py`, tiến trình riêng, không mDNS, nghe `127.0.0.1`) nối kết nối điều khiển tới `receive` bằng `connect_hint`; `receive` báo `device_connected` lúc 02:57:27 và chỉ báo `device_disconnected` lúc dừng (03:07:32), nên kết nối được giữ suốt 10 phút (có ping giữ kết nối của protocol mục 2.3).
- Lấy mẫu bắt đầu 5 s sau khi kết nối xong, mỗi giây một mẫu, 600 mẫu. Tiến trình `receive` không ở Efficiency mode (ControlMask = StateMask = 0, ưu tiên Normal).
- Tải khác: lúc bắt đầu có 5 tiến trình python của các agent khác đang chạy; CPU cả máy bận trung vị 12,7 %, nhỏ nhất 3,1 %, lớn nhất 41,4 % (theo từng giây); trung bình cả 10 phút 14,2 %. RAM trống lúc bắt đầu 5,6 GiB.

**Kết quả** (600 mẫu; trung vị / p95 / min / max)

| Đại lượng | Giá trị |
|---|---|
| Working set (MiB) | 55,2 / 55,3 / 53,6 / 55,3; mẫu đầu 54,4, mẫu cuối 54,0; đỉnh nhân lúc cuối 55,3 |
| Private bytes (MiB) | 35,1 / 35,2 / 34,5 / 35,2; mẫu đầu 34,5, mẫu cuối 34,7 |
| CPU (% một lõi, từng giây) | 0,0 / 0,0 / 0,0 / 1,6; 580 giây bằng 0, 20 giây bằng 1,6 |
| CPU trung bình 10 phút (% một lõi) | 0,05 (0,3125 s CPU trong 600,0 s) |

`GetProcessTimes` tăng theo bước 15,625 ms, nên CPU từng giây chỉ nhận các giá trị 0 hoặc bội của 1,5625 %; giá trị trung bình 10 phút mới có ý nghĩa ở mức dưới 1 %. `receive` thoát mã 0 sau Ctrl+C, node giữ kết nối thoát mã 0.

**Ghi nhận, không phải kết luận phần lúc rảnh của mvp N3.** Đây là lệnh CLI không giao diện; phần lúc rảnh của mvp N3 xét cho app có giao diện, đo ở Giai đoạn 4 (cửa chặn ở đó). Working set và private bytes không tăng dần trong 10 phút (mẫu cuối thấp hơn trung vị).

**Giới hạn của lần đo này**

- Một thiết bị tin cậy, nối qua loopback; không có thiết bị nào khác quảng bá mDNS trong mạng mà `receive` thấy được trong lúc đo (không ghi `device_online`), nên chưa đo tải của nhiều thiết bị hay của mạng có nhiều gói mDNS.
- 10 phút; chưa đo lâu hơn (rò rỉ chậm) hay sau khi đã truyền file.
- Có tải của các agent khác trên máy; số CPU ở trên là thời gian CPU của riêng tiến trình `receive`, không gồm tải đó.

### 4.8. Lần thử 2026-10-26: ổ đích chậm trên USB, dừng ở bước kiểm ổ

Kế hoạch: `n3_cli.py transfer --plan 1GiB:5,5GiB:1 --recv-dir D:\<thư mục mới>`, file nguồn trên SSD, thư mục nhận trên USB, xét theo ba tiêu chí CLI của mục 4.1. Trước khi ghi, người đo kiểm ổ `D:` (chỉ đọc): phải là ổ USB, hệ file NTFS hoặc exFAT (không FAT32), còn ≥ 8 GB trống. Một điều kiện sai thì dừng, không ghi gì lên ổ.

| Kiểm | Kết quả đọc được | Đạt? |
|---|---|---|
| Ổ USB thật | `Get-Disk`: “General UDisk”, BusType USB, 62 914 560 000 byte, MBR; thiết bị `USB\VID_048D&PID_1234`; `Get-Volume`: DriveType Removable | đạt |
| Hệ file | **FAT32** (cụm 32 KiB) | **không đạt** |
| Chỗ trống | 36 420 714 496 byte (≈ 33,9 GiB) | đạt |
| Tình trạng volume (ghi thêm) | HealthStatus Warning, OperationalStatus “Full Repair Needed”; `fsutil dirty query D:` báo volume “Dirty” | — |

Vì hệ file là FAT32, lượt đo **không chạy**; không có file nào được ghi lên `D:`, nên không có gì phải xóa. Ngoài quy tắc đã đặt, FAT32 không chứa được file ≥ 4 GiB nên lần 5 GiB chắc chắn hỏng vì hệ file, không phải vì Teleport. Tốc độ ghi tuần tự của USB: **chưa đo** (cần ghi lên ổ).

| Tiêu chí (mục 4.1) | Kết quả |
|---|---|
| 1. RSS tăng (cận trên) dưới ngưỡng mvp N3 | **chưa đo** |
| 2. Đường RAM phẳng | **chưa đo** |
| 3. SHA-256 khớp, `.teleport` trống, mã thoát 0 / 0 | **chưa đo** |

**Kết luận phần ổ đích chậm: CHƯA ĐỦ DỮ LIỆU** (chưa đo). Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D4).

**Việc cần để đo:** một USB NTFS hoặc exFAT còn ≥ 8 GB trống. Định dạng lại ổ hiện có thành exFAT/NTFS sẽ xóa khoảng 26 GB dữ liệu đang có trên đó: người dùng quyết, người đo không làm. Ổ đang báo cần sửa lỗi, nên sửa lỗi (hoặc định dạng lại) trước. VID/PID `048D:1234` là mã chung, hay gặp ở USB không rõ hãng; nếu dùng lại ổ này, kiểm dung lượng thật trước, vì USB khai khống dung lượng làm hỏng dữ liệu ghi và khiến SHA-256 không khớp mà không do Teleport.

### 4.9. Lần đo 2026-10-28: trước/sau P3-3a (ghi trạng thái nối lại bền), loopback trên một máy

Mục đích: xem việc ghi `transfer.json` và `.state` bền khi nhận (P3-3a, [architecture.md](architecture.md) mục 4) có làm xấu mvp N3 hay thông lượng không. Ba lượt, giờ UTC 2026-10-27 17:01–17:56 (giờ máy 2026-10-28 00:01–00:56).

**Mã đo** (cùng commit gốc `e1d9a58`)

| Bên | Worktree, nhánh | `src` | Digest `src/teleport` (cách tính ở mục 4.3) |
|---|---|---|---|
| trước | `p3-2`, `feat/transfer-restore` | sạch | `62f1be94f026f815076dd36905b028250fc989aabf8022848c3aff46ebaed4c3` |
| sau | `p3-3a`, `feat/resume-storage` | thay đổi chưa commit ở `app/storage.py`, `app/transfers.py`, `core/resume_state.py` | `06295d338ea57a920e4c1e594406819537d0db89748da20a8395ffc246c5d272` |

Cùng `python.exe` của `.venv` ở checkout chính; mã nạp từ `src/` của đúng worktree qua `PYTHONPATH`. Trước **mỗi** lần đo, script chạy `python -c` với đúng môi trường của hai tiến trình đo và kiểm `teleport.__file__` nằm trong worktree của bên đó (72/72 lần đúng).

**Cách đo.** Như phép đo qua CLI thật ở mục 4.1: `teleport receive --yes --json --dir <D> --port <p>` và `teleport send <nguồn> --to <mã> --address 127.0.0.1:<p> --json`, mỗi bên `TELEPORT_HOME` riêng (danh tính và `trusted.json` riêng cho bên trước và bên sau), mDNS bật như mặc định. Khác mục 4.6: chờ 2 s sau dòng `receiving` rồi mới bật `send`. RSS lúc bắt đầu, RSS đỉnh, RSS tăng (cận trên), max Q4 − max Q1, CPU, thông lượng: định nghĩa ở mục 4.1 (chế độ CLI); “thời gian gửi” là từ dòng `offer` tới dòng `result` của `send`.

- **Ca 1 GiB:** một file ngẫu nhiên 1 GiB.
- **Ca 1000 file nhỏ:** 1000 file, cỡ ngẫu nhiên đều trong 4–64 KiB, nội dung ngẫu nhiên, seed 20261027 (tổng 35 174 623 byte, cùng bộ file cho mọi lần); gửi một lượt bằng mẫu `<thư mục>\f*.bin`.
- **Thứ tự xen kẽ:** vòng r chạy một cặp 1 GiB (trước/sau, đảo thứ tự theo r) rồi một cặp 1000 file (thứ tự ngược cặp 1 GiB). Mỗi lần bật hai tiến trình mới; sau mỗi lần so SHA-256 từng file nhận với nguồn, kiểm `.teleport` không còn file, xóa file nhận.
- **Lượt chính** `d1-20261027T171134Z`: 10 cặp mỗi ca, thêm một cặp khởi động mỗi ca ở đầu lượt, **không tính** (lý do ở lượt 1 dưới đây). **Lượt 1** `d1-20261027T170113Z`: đúng số lần của kế hoạch (1 GiB × 5, 1000 file × 3 mỗi bên), không có cặp khởi động. **Lượt chẩn đoán** `d1-20261027T174055Z`: đếm `os.fsync`, không dùng cho số đo chính (mục cuối).

**Môi trường.** Như mục 4.6 (Windows 11 Pro 10.0.26300, Python 3.14.5, i7-12800H 20 luồng, RAM 15,7 GiB, NVMe SSSTC CL1-3D512-Q11 NTFS, cryptography 50.0.2, zeroconf 0.151.5, `__version__` 0.1.0a0), khác: RAM trống lúc bắt đầu lượt chính 5,1 GiB; ổ C trống 40,3 GiB; file nguồn và thư mục nhận cùng ổ, thư mục làm việc `%TEMP%\tpd1`. Cắm sạc, power plan Balanced với chế độ nguồn **Best power efficiency** (overlay `961cc777-…`); Defender thời gian thực bật. Mọi tiến trình đo: không Efficiency mode (ControlMask = StateMask = 0), ưu tiên Normal. Lúc bắt đầu không có tiến trình python nào khác; CPU cả máy bận trong từng lần đo: 7,1–28,3 %.

**Kết quả lượt chính** (10 lần hợp lệ mỗi bên mỗi ca, 0 lần hỏng; mọi lần hai bên `result: done`, SHA-256 khớp mọi file, `.teleport` không còn file, mã thoát 0 / 0). Trung vị / p95 / min / max; RSS tính bằng MiB.

| Đại lượng | 1 GiB, trước | 1 GiB, sau | 1000 file, trước | 1000 file, sau |
|---|---|---|---|---|
| Thời gian gửi (s) | 11,08 / 17,38 / 5,74 / 17,38 | 10,40 / 14,04 / 6,22 / 14,04 | 26,41 / 32,63 / 11,25 / 32,63 | 38,85 / 62,11 / 19,89 / 62,11 |
| Thông lượng (MB/s, 10⁶ byte/s) | 97,4 / 187,0 / 61,8 / 187,0 | 103,2 / 172,5 / 76,5 / 172,5 | 1,33 / 3,13 / 1,08 / 3,13 | 0,91 / 1,77 / 0,57 / 1,77 |
| Nhận: RSS đỉnh | 65,63 / 66,19 / 63,45 / 66,19 | 65,83 / 66,59 / 64,69 / 66,59 | 58,63 / 58,88 / 58,45 / 58,88 | 60,28 / 60,49 / 60,04 / 60,49 |
| Nhận: RSS tăng, cận trên | 11,15 / 11,93 / 9,57 / 11,93 | 11,20 / 11,90 / 9,59 / 11,90 | 3,58 / 4,09 / 3,02 / 4,09 | 4,58 / 6,05 / 3,96 / 6,05 |
| Nhận: private bytes tăng, cận trên | 12,39 / 13,17 / 11,41 / 13,17 | 11,89 / 12,40 / 10,24 / 12,40 | 3,41 / 4,18 / 2,92 / 4,18 | 4,47 / 6,35 / 4,14 / 6,35 |
| Nhận: max Q4 − max Q1 | 0,04 / 2,74 / −2,20 / 2,74 | 0,01 / 1,21 / −8,56 / 1,21 | 1,97 / 2,67 / 1,03 / 2,67 | 2,88 / 3,53 / 2,41 / 3,53 |
| Gửi: RSS tăng, cận trên | 4,39 / 4,86 / 4,17 / 4,86 | 4,33 / 4,55 / 4,08 / 4,55 | 1,29 / 1,57 / 0,72 / 1,57 | 1,40 / 1,52 / 0,97 / 1,52 |
| Nhận: CPU trong lúc truyền (s) | 5,40 / 7,20 / 4,59 / 7,20 | 5,66 / 9,05 / 4,88 / 9,05 | 12,14 / 16,34 / 6,59 / 16,34 | 24,69 / 30,14 / 11,09 / 30,14 |

Số thô, thời gian gửi (s), theo thứ tự chạy:

| Ca, bên | Các lần |
|---|---|
| 1 GiB, trước | 11,87; 6,80; 12,60; 12,89; 5,74; 17,39; 12,03; 10,29; 8,03; 7,42 |
| 1 GiB, sau | 11,53; 6,22; 10,52; 7,53; 11,87; 14,04; 10,28; 6,51; 11,91; 6,29 |
| 1000 file, trước | 11,25; 14,20; 31,32; 32,63; 26,46; 31,29; 26,35; 12,33; 12,00; 28,76 |
| 1000 file, sau | 19,89; 61,16; 35,74; 40,72; 58,73; 62,11; 36,99; 20,58; 23,64; 42,04 |

**So từng cặp liền kề** (thời gian sau / thời gian trước, 10 cặp mỗi ca): 1 GiB trung vị 0,85, nhỏ nhất 0,58, lớn nhất 2,07 (8 cặp sau nhanh hơn, 2 cặp chậm hơn); 1000 file trung vị 1,72, nhỏ nhất 1,14, lớn nhất 4,31 (**10/10 cặp sau chậm hơn**). CPU tiến trình nhận sau / trước: 1 GiB trung vị 1,02 (0,94–1,36); 1000 file trung vị 1,82 (1,46–2,92).

**Lượt 1** (5 + 3 lần mỗi bên, không cặp khởi động; 16/16 lần hợp lệ, cùng các kiểm như trên). Thời gian gửi (s): 1 GiB trước 21,23; 10,06; 8,48; 10,79; 8,34 (trung vị 10,06), sau 19,88; 8,43; 11,65; 4,00; 10,11 (trung vị 10,11); 1000 file trước 16,58; 24,58; 12,83 (trung vị 16,58), sau 63,98; 24,25; 19,93 (trung vị 24,25). RSS tăng (cận trên) của tiến trình nhận: 1 GiB trung vị 11,14 (trước) và 11,39 MiB (sau), lớn nhất 11,57 và 12,39 MiB; 1000 file trung vị 3,51 và 4,29 MiB, lớn nhất 3,96 và 5,65 MiB. Lần 1000 file đầu tiên (bên sau, ngay sau khi tạo bộ file) chậm bất thường: `send` mất 19,3 s từ lúc bật tới dòng `offer` (các lần khác dưới 1 s), nghi do file nguồn vừa tạo (bộ đệm, quét của Defender; không kiểm). Vì vậy lượt chính thêm một cặp khởi động không tính.

**Lượt chẩn đoán: số `fsync` và thời gian trong `fsync` của tiến trình nhận.** Một `sitecustomize.py` (đặt sau `src` trong `PYTHONPATH` của tiến trình đo, chỉ ở lượt này) bọc `os.fsync`: đếm theo loại file và bấm giờ từng lần gọi. Trên Windows mọi `fsync` của `storage` đi qua `os.fsync` (`_fsync_dir` không làm gì). Lượt này còn chạy một luồng lấy mẫu ngăn xếp mỗi 2 ms nên chậm hơn lượt chính; chỉ dùng số đếm và tỉ lệ. 1 cặp 1 GiB và 3 cặp 1000 file, sau một cặp khởi động.

| Ca | `fsync` mỗi lượt, trước | `fsync` mỗi lượt, sau | Thời gian trong `fsync` (s), trước | Thời gian trong `fsync` (s), sau | Thời gian gửi (s), trước | Thời gian gửi (s), sau |
|---|---|---|---|---|---|---|
| 1000 file | 3000: `.part` 2000, file đích giữ chỗ 1000 | 8001: `.state` 3000, `.state.<hex>.tmp` 1000, `transfer.json.<hex>.tmp` 1001, `.part` 2000, file đích giữ chỗ 1000 | 1,62; 1,90; 1,63 | 9,87; 7,93; 9,31 | 14,96; 16,27; 14,80 | 23,79; 21,71; 27,49 |
| 1 GiB | 66 (`.part` 65) | 135 (`.part` 65, `.state` 66, tạm 3) | 1,21 | 6,72, trong đó `.state` 0,24 | 3,99 | 9,54 |

Với file nhỏ, mỗi file cần 3 `fsync` trước và 8 sau (cộng 1 lần `transfer.json` lúc tạo thư mục tạm). Thời gian trong `fsync` tăng thêm 6,0–8,3 s mỗi lượt 1000 file (từng cặp), cùng cỡ với phần thời gian gửi tăng thêm ở cùng lượt (5,4–12,7 s): `fsync` của `.state` (3 lần mỗi file, trung bình 1,3–1,5 ms mỗi lần) là phần tốn nhất, rồi đến `.state.<hex>.tmp` và `transfer.json.<hex>.tmp` (trung bình 0,9–1,8 ms mỗi lần). Phần CPU tăng thêm của tiến trình nhận (lượt chính: trung vị 12,1 → 24,7 s) chưa tách được giữa thời gian nhân của `FlushFileBuffers` và mã Python (mã hóa, ghi `transfer.json`, `.state`). Với 1 GiB, `fsync` của `.state` chỉ thêm 0,24 s; thời gian `fsync` của `.part` dao động mạnh giữa các lần (1,2–12,3 s cho cùng 65 lần), nên cặp 1 GiB của lượt này không dùng để so.

**Đánh giá**

| Câu hỏi | Số đo | Kết quả |
|---|---|---|
| mvp N3, tiêu chí 1 (mục 4.1): RSS tăng (cận trên) dưới ngưỡng mvp N3, mọi lần, cả hai tiến trình | lớn nhất ở bên sau: nhận 12,39 MiB (lượt 1, 1 GiB), gửi 4,60 MiB; 1000 file: nhận 6,05 MiB | **ĐẠT**, cả trước và sau (28/28 lần mỗi bên: lượt 1 và lượt chính, không kể cặp khởi động) |
| mvp N3, tiêu chí 2a: max Q4 − max Q1 ≤ 4 MiB | lớn nhất ở bên sau: 1 GiB 1,21 MiB; 1000 file 3,82 MiB (lượt 1) | **ĐẠT** mọi lần |
| P3-3a có làm RSS khi nhận 1 GiB tăng không | trung vị RSS tăng nhận 11,15 → 11,20 MiB (+0,05), RSS đỉnh 65,63 → 65,83 MiB | không thấy khác biệt vượt dao động giữa các lần (9,6–11,9 MiB) |
| P3-3a có làm RSS khi nhận 1000 file tăng không | trung vị RSS tăng nhận 3,58 → 4,58 MiB (+1,00), RSS đỉnh 58,63 → 60,28 MiB (+1,65); max Q4 − max Q1 1,97 → 2,88 MiB | có, khoảng 1 MiB; vẫn xa ngưỡng |
| Thông lượng 1 GiB | trung vị thời gian 11,08 → 10,40 s (−6 %); tỉ số từng cặp trung vị 0,85 (0,58–2,07) | không thấy chậm đi; độ nhiễu giữa các lần (5,7–17,4 s) lớn hơn mọi chênh lệch có thể có |
| Thời gian 1000 file nhỏ | trung vị 26,41 → 38,85 s (+47 %); tỉ số từng cặp trung vị 1,72 (1,14–4,31), 10/10 cặp chậm hơn | **chậm hơn rõ**; phần lớn do `fsync` thêm (lượt chẩn đoán) |

**Kết luận:** P3-3a **không làm xấu mvp N3** ở hai ca đã đo (1 GiB, 1000 file nhỏ, loopback): hai tiêu chí đo được đều ĐẠT ở cả trước và sau; RSS tăng thêm khoảng 1 MiB khi nhận 1000 file, không đổi khi nhận 1 GiB. Thông lượng 1 GiB không thấy chậm đi. Gửi 1000 file nhỏ chậm hơn khoảng 1,5–1,7 lần (trung vị +47 %, tỉ số cặp 1,72) vì số `fsync` mỗi file tăng từ 3 lên 8. mvp N3 nói chung vẫn **CHƯA ĐỦ DỮ LIỆU** như mục 4.4; lần đo này không đo 5 / 10 GiB nên không xét tiêu chí 2b, và không thay kết quả mục 4.6 cho mã sau P3-3a.

**Ghi nhận** (không phải kết luận)

- Ca 1000 file có hai nhóm thời gian rõ ở cả hai bên (trước: 11–14 s và 26–33 s; sau: 20–24 s và 36–62 s), và CPU của tiến trình nhận tăng theo cùng nhóm (trước 6,6–8,6 s so với 12–16 s). Lần đo này không tìm nguyên nhân; có thể do lõi hiệu năng và lõi tiết kiệm điện của CPU, hoặc chế độ nguồn Best power efficiency. Vì nhóm chậm có ở cả hai bên và các cặp chạy liền nhau, so từng cặp đáng tin hơn so trung vị.
- Mã sau P3-3a đòi thư mục nhận chừa nhiều chỗ hơn (`TEMP_PATH_RESERVE`, [architecture.md](architecture.md) mục 4 “Thư mục nhận”): thư mục nhận dài 187 ký tự trong scratchpad bị `receive` của bên sau từ chối (`PathTooLongError`), bên trước nhận được. Vì vậy thư mục làm việc đặt ở `%TEMP%\tpd1`.
- Max Q4 − max Q1 của tiến trình nhận ở ca 1000 file (bên sau tới 3,82 MiB) gần mức 4 MiB của tiêu chí 2a; bên trước cũng tăng dần trong lượt (tới 2,67 MiB). Lần đo này không tách phần tăng đó thuộc phần nào của mã. Một lượt có tối đa 1000 file ([protocol.md](protocol.md) mục 3.3), nên 1000 file là ca nhiều file nhất của một lượt; nhiều lượt 1000 file liên tiếp trong một tiến trình chưa đo.

**Giới hạn của lần đo này**

- Hai tiến trình trên một máy qua loopback, ổ NVMe nhanh dùng chung cho nguồn và đích. Trên ổ chậm (USB, HDD) mỗi `fsync` đắt hơn nhiều, nên phần chậm thêm của ca nhiều file nhỏ có thể lớn hơn ở đây: **chưa đo**.
- Chế độ nguồn Best power efficiency và Defender bật; thông lượng dao động mạnh giữa các lần (1 GiB: 62–187 MB/s), nên 10 cặp chỉ cho thấy không có chậm đi lớn ở ca 1 GiB, không loại được chênh lệch nhỏ.
- Chỉ 1 GiB và 1000 file 4–64 KiB; không đo 5 / 10 GiB, file vừa (vài MiB), hay nhiều lượt cùng lúc. Chỉ Windows 11 và Python 3.14.

**Cách đo lại.** Script nằm ngoài repo, trong scratchpad của phiên đo (thư mục `d1-p3-3a`, không bền): `d1_ab.py` (điều phối A/B, dùng lại `n3_bench.py` và `n3_cli.py` của mục 4.5, chép cùng thư mục), `d1_report.py` (bảng trung vị, số thô), `d1_pairs.py` (tỉ số từng cặp), `d1_diag.py` và `diag/sitecustomize.py` (lượt chẩn đoán). Trong PowerShell, ở thư mục chứa script (thư mục làm việc phải ngắn, xem ghi nhận ở trên):

```
$env:PYTHONPATH = "<worktree trước>\src"   # chỉ để điều phối tạo danh tính; tiến trình đo có PYTHONPATH riêng
& $PY d1_ab.py --before <worktree trước> --after <worktree sau> --big-runs 10 --small-runs 10 --warmup --work $env:TEMP\tpd1
& $PY d1_report.py results\d1-<giờ UTC>\results.jsonl ; & $PY d1_pairs.py results\d1-<giờ UTC>\results.jsonl
$env:D1_PROFILE = "1"; & $PY d1_ab.py ... --big-runs 1 --small-runs 3 --warmup --diag ; & $PY d1_diag.py results\d1-<giờ UTC>
```

### 4.10. Lần đo 2026-11-05: 10 GiB qua Wi-Fi giữa hai máy Windows thật (D3)

Phép đo “Qua card mạng giữa hai máy” ở mục 4.1, script ở mục 4.5 (`n3_net_host.py` trên máy gửi, `may2_nhan.py` trên máy nhận). Chiều máy A → máy B. Người dùng chạy theo hướng dẫn từng bước; trong lúc đo không dùng hai máy.

**Mã đo.** Commit `40da800` (`main`), cây `src` `89d3f8226770d4e05f3f327f5dc8fcf47077346c`, giống `src` của zip RC1 `7824259` dùng ở mục 6.1.
- Máy A nạp `src` lấy bằng `git archive 40da800 src` qua `PYTHONPATH` (script ghi `teleport.__file__`), với `python.exe` của `.venv` ở checkout chính.
- Máy B dùng bản clone mới ở `40da800` (`git rev-parse HEAD:src` khớp, script ghi commit, `src_dirty` rỗng), cài `pip install -e .` vào `.venv` riêng.
- Hai node chạy `teleport send` / `teleport receive` thật với danh tính đo riêng (`TELEPORT_HOME`), ghép đôi bằng `teleport pair` ngay trước khi đo.

**Môi trường.**

| | Máy A (gửi) | Máy B (nhận) |
|---|---|---|
| Hệ điều hành | Windows 11 Pro 10.0.26300 | Windows 10 Enterprise LTSC 2021, 21H2 (19044.7807) |
| CPU, RAM | i7-12800H (20 luồng), 15,7 GiB | i3-1005G1 (4 luồng), 11,7 GiB |
| Ổ đĩa | SSD NVMe 512 GB (file nguồn) | SSD NVMe 256 GB, NTFS (thư mục nhận, còn 26,8 GiB trống lúc đầu) |
| Python, cryptography, zeroconf | 3.14.5, 50.0.2, 0.151.5 | 3.15.1, 50.0.2, 0.151.6 |
| Wi-Fi | Intel AX201, 802.11ax, 2,4 GHz kênh 9, liên kết rx 172 / tx 88 Mbps, sóng 68 % (lúc kết thúc) | Intel AX201, liên kết 163 Mbps (lúc bắt đầu) |
| Nguồn | cắm sạc, pin 100 %; lớp nguồn khi cắm sạc `961cc777-…` (không phải “Hiệu suất tốt nhất”) | cắm sạc, pin 100 %; lớp nguồn `ded574b5-…` (Hiệu suất tốt nhất) |

Cùng một điểm phát, hồ sơ mạng Private ở cả hai máy. Máy B mở tạm cổng 47474 (chỉ cho IP máy A) và một share SMB chỉ để chuyển file “sẵn sàng” và kết quả, không dùng để truyền.

**Lượt đo.** Máy A `results/net-20261105T033554Z`, máy B `may2-20261105T033538Z`. File nguồn 10 GiB (10 737 418 240 byte) ngẫu nhiên, SHA-256 `35085990262e67368c998ed2129b7223e932ac46c82174329c7794818e95073d`. Trước đó có một lần chạy thử 64 MiB (`net-20261105T033355Z`), không tính.

| Đại lượng | Máy A (`send`) | Máy B (`receive`) |
|---|---|---|
| Kết quả, mã thoát | `done`, 0 | `done`, 0 (dừng sau 0,33 s) |
| Working set lúc bắt đầu | 54,1 MiB | 51,9 MiB |
| RSS tăng (cận trên) | **4,8 MiB** | **6,0 MiB** |
| RSS tăng (lấy mẫu) | 4,8 MiB | 5,7 MiB |
| Private bytes tăng (cận trên) | 4,2 MiB | 5,8 MiB |
| Đỉnh rơi vào lúc truyền | có | có |
| Max RSS Q1 / Q2 / Q3 / Q4 | 59,0 / 57,5 / 57,5 / 57,7 MiB | 57,6 / 56,4 / 56,4 / 56,7 MiB |
| Q4 − Q1 | −1,3 MiB | −0,9 MiB |
| Số mẫu, khoảng cách mẫu trung vị / lớn nhất | 208 615, 10,3 / 26,3 ms | 212 618, 10,2 / 39,3 ms |
| Thời gian truyền (dòng `offer` → `result`) | 2180,7 s | 2180,7 s |
| CPU trong lúc truyền | 59,4 s | 64,7 s |

Thông lượng 4,92 MB/s (10⁶ byte, chỉ tham khảo; không phải mvp N2). SHA-256 của file nhận (băm sau khi nhận, 13,0 s) khớp file nguồn. Không có lần thử lại, không có lỗi đo.

**So với tiêu chí ở mục 4.1** (viết trước khi đo):

| Tiêu chí | Kết quả |
|---|---|
| 1. RSS tăng (cận trên) dưới ngưỡng của mvp N3 (MB = 10⁶ byte) | Đúng ở cả hai phía: 4,8 MiB và 6,0 MiB |
| 2. Q4 − Q1 ≤ 4 MiB | Đúng ở cả hai phía: −1,3 MiB và −0,9 MiB |
| 2. Trung vị 10 GiB − trung vị 1 GiB ≤ dao động của các lần 1 GiB | Chưa xét: chưa có lần 1 GiB qua cùng mạng |
| 3. SHA-256 khớp, `send` / `receive` thoát mã 0 | Đúng |
| 3. `.teleport` không còn file sau khi bên nhận thoát | **Sai theo câu chữ**: còn `transfer.json` của lượt 10 GiB và của lần chạy thử 64 MiB. Đây là hành vi thiết kế từ sau khi tiêu chí được viết: lượt đã xong giữ bản ghi tới hết thời hạn nhớ lượt đã kết thúc ([architecture.md](architecture.md) mục 4, `remove_temp(keep_record)`; [protocol.md](protocol.md) mục 6.3). Không còn `.part`, `.state` hay file tạm nào. Tiêu chí giữ nguyên, không sửa sau khi đo |

**Kết luận:** **ĐẠT cho D3, theo quyết định của người dùng**. Lần 10 GiB qua Wi-Fi cho RAM tăng dưới ngưỡng mvp N3 nhiều lần và đường RAM phẳng ở cả hai phía.

**Quyết định của người dùng (2026-11-05, sau khi đo):**
- 1 lần 10 GiB là đủ cho D3. Mục 4.1 không nêu số lần cho phép đo qua card mạng; hướng dẫn ở mục 4.5 định 3 lần.
- Tiêu chí 3 được coi là đạt khi `.teleport` không còn file tạm (`.part`, `.state`, `.tmp`); `transfer.json` của lượt đã xong được giữ theo thiết kế.

Phần so 10 GiB với 1 GiB của tiêu chí 2 vẫn chưa xét, như mục 4.1 cho phép khi chưa có lượt 1 GiB qua cùng mạng. Theo quy ước mục 1, nếu không có quyết định này thì kết luận sẽ là CHƯA ĐỦ DỮ LIỆU.

**Giới hạn:**
- Chỉ Wi-Fi 2,4 GHz; mỗi byte qua sóng hai lần nên tốc độ thấp (khoảng 4,9 MB/s). Mạng dây chưa đo.
- Máy A không ở chế độ “Hiệu suất tốt nhất”. Việc này có thể làm chậm phía gửi, nhưng không làm RAM tăng thêm.
- Máy B chạy Windows 10 21H2, không phải phiên bản mvp N10 nêu.
- ke_hoach mục 5.4 định đo D3 cùng lượt D2 (mvp N2); lượt N2 chưa chạy.

## 5. mvp N2: Hiệu năng so với SMB

### 5.1. Định nghĩa phép đo

Viết ngày 2026-10-26, **trước khi đo**, không đổi sau.

- **Chiều và mạng:** host → máy thật thứ hai trong cùng LAN, ghi rõ loại mạng (dây hay Wi-Fi, băng tần, tốc độ liên kết hai phía). Đích của Teleport và của SMB nằm trên cùng một ổ của máy nhận (hai thư mục con của cùng một share).
- **Teleport:** `teleport send <file> --to <máy nhận> --address <IP>:47474 --json` tới `teleport receive --yes --json` (danh tính đo đạc riêng, đã ghép đôi). Thời gian = từ ngay trước khi bật lệnh `send` tới lúc host đọc được dòng `result` của nó, trên `time.perf_counter()` của host: gồm khởi động tiến trình, bắt tay TLS, `offer` / `accept`, truyền, `fsync` và kiểm Merkle ở bên nhận. Ghi kèm thời gian từ dòng `offer` tới dòng `result`. Lần nào kết quả khác `done` thì không phải lần hợp lệ của Teleport và được ghi riêng.
- **SMB:** `robocopy <thư mục nguồn> \<IP>\<share>\<thư mục> <tên file> /R:0 /W:0 /NP /NJH /NJS /NFL /NDL` (mặc định của robocopy, không `/J`, không `/MT`), phiên SMB đã mở sẵn bằng `net use` với tài khoản cục bộ, cấu hình ký / mã hóa SMB mặc định của Windows (ghi lại). Thời gian = từ lúc bật tới lúc robocopy thoát, cùng đồng hồ. Hợp lệ khi mã thoát 1 (đã chép) và cỡ file đích đúng. File đích bị xóa sau mỗi lần.
- **Cùng một file nguồn** ngẫu nhiên trên SSD của host cho cả hai cách, mỗi cỡ một file. Cỡ 1 GiB và 5 GiB, mỗi cỡ 5 lần mỗi cách, xen thứ tự: mỗi vòng đảo thứ tự cỡ, và đảo Teleport / SMB theo vòng và cỡ; nghỉ 10 s giữa hai lần.
- **Tỉ số** theo từng cỡ = trung vị thời gian SMB / trung vị thời gian Teleport (bằng tốc độ Teleport / tốc độ SMB). Ghi kèm tỉ số từng cặp (lần Teleport thứ k với lần SMB thứ k cùng cỡ): nhỏ nhất, trung vị, lớn nhất.
- **Kết luận:** **ĐẠT** khi đủ 5 lần hợp lệ mỗi cách mỗi cỡ, không lần Teleport nào kết thúc khác `done` vì lỗi của Teleport, và tỉ số của cả hai cỡ ≥ ngưỡng của mvp N2; **KHÔNG ĐẠT** khi tỉ số của một cỡ dưới ngưỡng; còn lại **CHƯA ĐỦ DỮ LIỆU**. Kết luận chỉ có giá trị cho loại mạng đã đo.

**Nguồn sai số đã biết**

| Nguồn | Xử lý |
|---|---|
| Bộ đệm ghi của máy chủ SMB: robocopy có thể thoát khi dữ liệu còn trong bộ đệm của máy nhận, còn Teleport chờ `fsync` | Không bù; ghi là thiên lệch bất lợi cho Teleport |
| File nguồn nằm trong bộ đệm file của host | Như nhau cho hai cách (cùng file, xen thứ tự) |
| Thời gian khởi động tiến trình Python của `send` | Tính vào Teleport (người dùng cũng chịu); ghi kèm thời gian `offer` → `result` |
| Tốc độ Wi-Fi dao động theo thời gian | Xen thứ tự; ghi `netsh wlan show interfaces` hai phía trước mỗi lần |

### 5.2. Phương pháp

Script `n3_net_host.py` (host), `may2_nhan.py` và `may2_chuanbi.ps1` (máy thứ hai), `n3_net_report.py` (tổng hợp); lệnh và hướng dẫn ở mục 4.5. Mỗi lần Teleport cũng đo RAM hai phía theo mục 4.1 (“Qua card mạng giữa hai máy”), nên các lần 1 GiB và 5 GiB của lượt này là thêm số đo mvp N3 qua mạng. Trên máy thứ hai, script không băm file nhận trong lượt này, để máy rảnh giữa các lần.

### 5.3. Việc còn lại

- Lượt đầu (host Windows 11 → máy thứ hai Windows 10/11, **cả hai qua Wi-Fi**) theo phương pháp mục 5.1: **chưa đo**; đã có một lần đo tay chỉ để tham khảo (mục 5.4). Giới hạn đã biết trước: qua Wi-Fi, mỗi byte đi qua sóng hai lần và Wi-Fi là nút cổ chai cho cả hai cách, nên tỉ số đo được không cho biết Teleport có theo kịp SMB trên mạng dây gigabit (khi CPU và Python mới là giới hạn). Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D2, D3).
- Mạng dây gigabit giữa hai máy thật: **chưa đo**. Thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D2).

### 5.4. Lần đo 2026-10-29/30: đo tay qua giao diện, Wi-Fi 2,4 GHz (chỉ tham khảo)

Lần đo tay của người dùng trên hai máy thật trước buổi demo hackathon, **không theo phương pháp mục 5.1**: không script, bấm giờ tay, Teleport chạy qua giao diện, mỗi cách chỉ một hoặc hai lần, một cỡ file. Ghi lại để có số đầu tiên giữa hai máy thật; không dùng để kết luận mvp N2.

**Môi trường**

| | Máy gửi (host) | Máy nhận |
|---|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 | Windows 10 (bản cụ thể không ghi) |
| Mạng | Wi-Fi Intel Wi-Fi 6 AX201, băng 2,4 GHz, kênh 9, 802.11ax, tốc độ liên kết nhận / gửi 155 / 163 Mbit/s, tín hiệu 91% (ghi một lần, trước lượt đo SMB) | Cùng mạng Wi-Fi, cùng điểm truy cập; Intel Wi-Fi 6 AX201, băng 2,4 GHz, kênh 9, 802.11ax, tốc độ liên kết nhận / gửi 103 / 122 Mbit/s, tín hiệu 93% (ghi một lần, sau lượt đo) |
| Ổ nguồn / đích | NVMe SSD 512 GB | Thư mục nhận của Teleport và thư mục share SMB cùng ổ C: (theo người dùng); loại ổ không ghi |
| Teleport | Bản GUI build thử `teleport-gui-0.1.0a0-5425f64-windows` (workflow “Build GUI (thử)”, commit `5425f648b861734d4ac30df795cc37aff8e5e42b`, Python 3.12.10) | Cùng bản |

**File:** một video có sẵn, 2 024 701 407 byte (1,89 GiB), không phải file ngẫu nhiên.

**Cách đo**

- **SMB:** `Measure-Command { robocopy <thư mục nguồn> \\<IP máy nhận>\SmbTest <tên file> /J /NP }` trên máy gửi; phiên SMB mở bằng File Explorer với một tài khoản cục bộ tạm trên máy nhận. Khác mục 5.1: có `/J` (chép không qua bộ đệm), thời gian lấy từ `Measure-Command`, không kiểm mã thoát và cỡ file đích bằng script. File đích được xóa giữa hai lần.
- **Teleport:** gửi qua giao diện, bấm giờ tay từ lúc bên nhận bấm “Nhận” tới lúc danh sách lượt truyền hiện “Xong ✓”. Khác mục 5.1: không tính khởi động tiến trình, bắt tay và `offer`; mốc do người bấm, không phải `time.perf_counter()`.
- Các lần không xen thứ tự: hai lần SMB liền nhau, lần Teleport sau đó.

**Kết quả** (MB/s = 10⁶ byte/s)

| Cách | Lần | Thời gian (s) | MB/s |
|---|---|---|---|
| SMB | 1 | 373 | 5,43 |
| SMB | 2 | 371 | 5,46 |
| Teleport | 1 | 387 | 5,23 |

Tỉ số trung vị SMB / Teleport = 372 / 387 ≈ 0,96; theo từng cặp với lần SMB 1 và 2: 0,96 và 0,96.

**Lần không hợp lệ:** một lần Teleport trước đó, cùng file, cùng mạng, mất 529 s (3,83 MB/s). Không tính vì mốc bấm giờ không rõ (có thể gồm thời gian chờ bấm “Nhận”) và lần đo cách lượt SMB nhiều giờ; không tìm hiểu thêm nguyên nhân.

**Giới hạn**

- Cả hai máy qua Wi-Fi 2,4 GHz: mỗi byte đi qua sóng hai lần và Wi-Fi là nút cổ chai cho cả hai cách (mục 5.3), nên tỉ số không cho biết Teleport có theo kịp SMB trên mạng dây.
- Một lần Teleport, hai lần SMB, một cỡ file; bấm giờ tay sai số cỡ vài giây.
- Mốc của Teleport không gồm khởi động và bắt tay, còn SMB có `/J`: hai thiên lệch ngược chiều, không bù.

## 6. MVP hackathon (mvp mục 4.1)

Tiêu chí H1–H5, cách kiểm và điều kiện đạt (máy, mạng, bản chạy): [mvp.md](mvp.md) mục 4.1. Lịch kiểm: [ke_hoach.md](ke_hoach.md) mục 5.5. Mỗi lần kiểm là một mục con riêng theo quy ước mục 1: ngày, commit của bản zip, hai máy (hệ điều hành, card mạng), mạng Wi-Fi, kết quả từng bước và hash hai phía.

| Mã | Lần kiểm gần nhất | Kết luận |
|---|---|---|
| H1 | 2026-11-05, zip `7824259` (mục 6.1) | **ĐẠT**: B hiện trên radar A sau 1,74–2,11 s (bấm tay, 3 lần); ghép đôi xong, mã 6 số trùng ở hai máy |
| H2 | 2026-11-05, zip `7824259` (mục 6.1) | **ĐẠT**: 1 GiB qua kéo thả, hộp thoại Nhận ở B, SHA-256 trùng |
| H3 | 2026-11-05, zip `7824259` (mục 6.1) | **ĐẠT**: tắt Wi-Fi máy B hai lần (50,7 % và 89,8 %), tự chạy tiếp, không về 0, SHA-256 trùng |
| H4 | 2026-11-05, zip `7824259` (mục 6.1) | **ĐẠT**: thoát app B ở khoảng 41 %, mở lại sau khoảng 20 s, tự chạy tiếp không hỏi Nhận lại, SHA-256 trùng |
| H5 | 2026-11-05, zip `7824259` (mục 6.1) | **ĐẠT**: bản mới lưu thành `demo-1GiB (1).bin`, file cũ không đổi; B sau khi A hủy ghép đôi bị từ chối, A không có hộp thoại và không có file mới |

Lần đo tay N2 ở mục 5.4 không tính cho H2: không so SHA-256 của file ở hai máy.

### 6.1. Lần kiểm 2026-11-05: zip RC1 `7824259`, hai máy Windows thật qua Wi-Fi

Kiểm trước lịch chính thức ngày 06/11 ở [ke_hoach.md](ke_hoach.md) mục 5.5 vì có máy mượn sớm hơn. Lần kiểm này đủ điều kiện của mvp mục 4.1: zip RC1, hai máy Windows thật, cùng một mạng Wi-Fi, chỉ gõ lệnh kiểm hash. Người dùng thao tác và bấm giờ; số liệu dưới đây là số người dùng báo lại.

**Bản chạy.** Cả hai máy chạy zip `teleport-gui-0.1.0a0-7824259-windows` (34 384 865 byte). Zip được build bằng workflow “Build GUI (thử)” (run 41953253539) trên `main` `7824259`; build và test frozen đều đạt. Zip `40da800` có `src/` giống hệt `7824259`, và `main` không đổi `src/` từ `7824259` tới `40da800`.

**Môi trường.**

| | Máy A (gửi, “Tung”) | Máy B (nhận, “DESKTOP-D3TLUTA”) |
|---|---|---|
| Hệ điều hành | Windows 11 Pro 10.0.26300 (Insider) | Windows 10 Enterprise LTSC 10.0.19044 (21H2) |
| CPU, RAM | i7-12800H, 15,7 GiB | i3-1005G1, 11,7 GiB |
| Card Wi-Fi | Intel AX201, 802.11ax | Intel AX201, 802.11ax |
| Mạng | 2,4 GHz kênh 9, cùng điểm phát, hồ sơ Private | như máy A |
| IP | 192.168.1.7 | 192.168.1.16 |
| Ngôn ngữ giao diện | Tiếng Việt | Tiếng Anh (theo ngôn ngữ Windows của B) |

File thử là `demo-1GiB.bin` trên máy A: 1 073 741 824 byte ngẫu nhiên, SHA-256 `BC26062F5AA02CF7B5B46312317ECCA6D4160ACC1CF3DE4FF0FD9A091E201FC3`. Thư mục nhận của B là `Downloads\Teleport`, của A là `Downloads`.

**Kết quả từng bước.**

| Mã | Thao tác và kết quả | Kết luận |
|---|---|---|
| H1 | Hai máy chưa ghép đôi. Bấm tay từ lúc mở `Teleport.exe` trên B tới lúc B hiện trên radar A, 3 lần: 2,11 / 1,74 / 2,02 s. Các số này là cận trên vì có cả thời gian phản xạ của người bấm, và đều dưới ngưỡng xuất hiện của mvp N1. Ghép đôi từ radar A: mã 6 số trùng ở hai máy, xác nhận ở cả hai | ĐẠT |
| H2 | A kéo thả `demo-1GiB.bin` vào cuộc trò chuyện của B. B hiện hộp thoại và bấm Nhận. Từ lúc bấm Nhận tới lúc xong mất 4 phút 29 s (bấm tay, khoảng 3,99 MB/s; giao diện hiện khoảng 4,2 MB/s lúc 64 %). SHA-256 của `demo-1GiB.bin` ở B trùng file gốc | ĐẠT |
| H3 | A gửi lại file, B lưu thành `demo-1GiB (1).bin`. Tắt Wi-Fi máy B ở 50,7 % và bật lại sau khoảng 13 s; tắt lần nữa ở 89,8 % và bật lại sau khoảng 20 s. Thời gian tắt do người dùng ước lượng, không bấm giờ, nhưng cả hai lần đều ≥ 10 s. Cả hai lần lượt truyền đều tự chạy tiếp, tiến độ không về 0. SHA-256 trùng file gốc | ĐẠT |
| H4 | A gửi lại file, B lưu thành `demo-1GiB (2).bin`. Thoát app B (khay → Thoát) ở khoảng 41 %. A hiện “Đang nối lại… · 41,9 % · Đang chờ DESKTOP-D3TLUTA nối lại…” và dải “đang ngoại tuyến”. Mở lại B sau khoảng 20 s: lượt truyền tự chạy tiếp từ 45,4 %, không hỏi Nhận lại, rồi hoàn tất. SHA-256 trùng file gốc | ĐẠT |
| H5 | Sau khi xóa các bản `(1)` và `(2)`, A gửi lại file: B lưu thành `demo-1GiB (1).bin`, và SHA-256 của `demo-1GiB.bin` cũ vẫn trùng file gốc. A hủy ghép đôi B, B giữ nguyên rồi gửi `thu-h5.txt` tới A. B hiện “Tung refused the connection from this device. That device may have unpaired.” kèm nút “Pair again” (câu tiếng Anh của dòng “Máy kia từ chối máy này”, mvp mục 8). A không hiện hộp thoại nhận; `Test-Path` của `thu-h5.txt` trong thư mục nhận của A trả `False`. B hủy ghép đôi nốt, cả hai về chưa ghép đôi | ĐẠT |

**Kết luận:** H1–H5 **ĐẠT** trên zip `7824259`.

**Ghi nhận** (không chặn tiêu chí nào):
- Ở H3, khi mất Wi-Fi ngắn, thẻ trên máy A chỉ hiện “50,7 % · đang tính thời gian còn lại” rồi “89,8 % · Đang chờ DESKTOP-D3TLUTA phản hồi…”, không hiện “Đang nối lại…”. Chữ “Đang nối lại…” chỉ thấy ở H4, khi app B đã thoát.
- Sau khi mở lại app B ở H4, hai thẻ cũ (H2, H3) trong lịch sử của B chỉ còn “Saved”, mất dòng “Saved as demo-1GiB (1).bin” và “Integrity verified” vốn hiện trước khi thoát app. Chưa tìm hiểu nguyên nhân.

**Giới hạn:**
- Thời gian ở H1, H2 và độ dài lúc tắt Wi-Fi ở H3, H4 đều bấm tay hoặc do người dùng ước lượng.
- Chỉ đo trên Wi-Fi 2,4 GHz; mỗi tiêu chí kiểm một lần, riêng H1 bấm giờ 3 lần.
- Máy B chạy Windows 10 21H2, không phải phiên bản mvp N10 nêu.
- Nếu zip chốt ngày 07/11 khác commit `7824259`, phải kiểm lại các H mà thay đổi có thể ảnh hưởng ([ke_hoach.md](ke_hoach.md) mục 5.5).

## 7. mvp N4: Nối lại

### 7.1. Định nghĩa phép đo

- **Phần gửi thừa của một lượt** = `payload_sent − cỡ file`, với `payload_sent` lấy từ dòng `result` của `teleport send --json` (tức `TransferFinished.payload_sent`; cách đếm và vì sao là cận trên: [architecture.md](architecture.md) mục 5, “Byte payload đã gửi”). Không đếm header khung, TLS hay kết nối điều khiển.
- **Phần gửi thừa mỗi gián đoạn** = phần gửi thừa của lượt chia cho số lần gián đoạn trong lượt. Mỗi lượt ở đây có đúng một lần gián đoạn, nên hai số bằng nhau.
- **Vị trí cắt:** khi tổng byte TCP chiều gửi → nhận đi qua proxy (mọi kết nối, gồm TLS và kết nối điều khiển) chạm 85 % cỡ file. Vì phần TLS và khung, vị trí này tương ứng khoảng 84–85 % payload.
- **So với mvp N4:** “phần chưa nhận” tính theo bitfield bên nhận ([protocol.md](protocol.md) mục 4.3). Phần gửi thừa mỗi gián đoạn phải nằm trong phần cộng thêm của mvp N4.
- **Tiêu chí chốt bộ đệm socket** (quyết định ghi ở [protocol.md](protocol.md) mục 4.3, đoạn “Giới hạn gửi lại”): lấy giá trị **lớn nhất** của phần gửi thừa mỗi gián đoạn qua mọi lần đo trên một hệ điều hành (gồm cả khối đã nhận mà chưa đánh dấu, không chỉ bộ đệm socket). Lớn nhất ≤ 48 MiB → không đặt `SO_RCVBUF`/`SO_SNDBUF` trên hệ điều hành đó; vượt → đặt theo hệ điều hành.
- Thống kê theo mục 1. Kết luận từng lần: ĐẠT khi lượt xong (`result: done` ở hai bên, mã thoát `send` = 0, SHA-256 khớp) và phần gửi thừa nằm trong ngưỡng mvp N4.

### 7.2. Phương pháp

Script `n4_bench.py` chạy hai tiến trình con thật, `teleport receive --json --yes --host 127.0.0.1 --port 0` và `teleport send --json --address 127.0.0.1:<cổng proxy>`, cấu hình riêng mỗi lượt (hai danh tính mới, đã tin nhau trong `trusted.json`), không mDNS, không giới hạn tốc độ. Giữa hai bên là proxy `TcpProxy` của `tests/conftest.py` (bộ đệm nhỏ có backpressure, mặc định `SO_RCVBUF`/`SO_SNDBUF` của socket proxy 64 KiB, đoạn 64 KiB), để phần byte nằm trong proxy lúc cắt không làm phình số đo; biến thể “proxy bộ đệm mặc định” bỏ hai lệnh đặt bộ đệm của proxy. Socket của Teleport ở hai đầu luôn dùng mặc định của hệ điều hành (mã đo không đặt bộ đệm).

Proxy tự chặn đúng lúc chạm vị trí cắt (`TcpProxy.block_at`), rồi theo kiểu:

| Kiểu | Làm gì sau khi chặn |
|---|---|
| `rst` | RST mọi kết nối ngay, cho chuyển tiếp lại |
| `block10` / `block60` | chặn 10 / 60 s (không chuyển byte, không đóng gì), rồi cho đi tiếp |
| `block10rst` | chặn 10 s, RST mọi kết nối, cho chuyển tiếp lại |
| `kill` | sau 1 s, giết `receive` (TerminateProcess), chạy lại `receive` cùng thư mục nhận, chờ `restored`, đổi đích proxy, RST kết nối cũ, cho chuyển tiếp lại |
| `killlive` | không chặn trước: script đọc bộ đếm proxy khoảng 1 ms một lần và giết `receive` ngay khi chạm vị trí cắt, trong lúc dữ liệu đang chạy; rồi chặn proxy (giữ kết nối mới), chạy lại `receive` như `kill` |

Hai kiểu `kill`/`killlive` là ca “tắt app nhận” của mvp N4; các kiểu còn lại là ca rớt mạng. File nguồn 1 GiB ngẫu nhiên, dùng lại giữa các lượt; mỗi lượt kiểm SHA-256 file nhận, rồi xóa thư mục tạm của lượt. Thứ tự các kiểu xen kẽ trong từng vòng. Ngoài số đo chính, script ghi: số khối đã `MARK` trong `.state` lúc cắt (đọc độc lập bằng helper `_read_state_file` của `tests/conftest.py`), các `status` của `send`, số kết nối proxy đã nhận, thời gian.

### 7.3. Lần đo 2026-10-31: loopback trên một máy Windows 11

Bốn lượt, giờ UTC 2026-10-30 23:11–23:38: `run-20261030T231150Z` (4 kiểu chính × 5), `run-20261030T232458Z` (`killlive`, `block10rst` × 5), `run-20261030T232931Z` (proxy bộ đệm mặc định: `rst`, `killlive`, `block60` × 3), `run-20261030T233530Z` (`killlive` × 10). Kiểu `killlive` được thêm vào script sau lượt đầu; nhánh `kill` không đổi.

Mã đo: worktree `c0-so-buf`, nhánh `claude/c0-so-buf`, commit `411e2f4` (`main`), `src/` không sửa (`src_dirty: false`). Lệnh chạy bằng `python.exe` của `.venv` ở checkout chính, mã nạp từ `src/` của worktree qua `PYTHONPATH` (đã kiểm `teleport.__file__`).

**Môi trường**

| | |
|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 |
| Python | 3.14.5 (64 bit, qua `.venv`) |
| Teleport | `__version__` 0.1.0a0, commit `411e2f4d6135898581ef22716c1a6cb9ddac4d0b` |
| cryptography / zeroconf | 50.0.2 / 0.151.5 (mDNS tắt ở cả hai lệnh vì `--host 127.0.0.1`) |
| CPU / RAM | Intel Core i7-12800H, 20 luồng / 15,7 GiB, trống 5,5 GiB lúc bắt đầu |
| Mạng | loopback 127.0.0.1 qua proxy; `SO_RCVBUF`/`SO_SNDBUF` ban đầu của socket TCP mới: 65 536 / 65 536 byte; `netsh int tcp show global`: Receive Window Auto-Tuning Level `normal` |
| Tải khác | các agent khác chạy `pytest` trên máy này trong lúc đo (thấy ít nhất hai lượt pytest bắt đầu 06:20 và 06:38 giờ máy) |

**Kết quả** (phần gửi thừa mỗi gián đoạn, MiB; 1 gián đoạn mỗi lượt; p95 theo hạng gần nhất)

| Kiểu | Proxy | Hợp lệ / hỏng | Trung vị | p95 | Min | Max | Kết luận |
|---|---|---|---|---|---|---|---|
| `rst` | 64 KiB | 5 / 0 | 2,50 | 2,56 | 2,44 | 2,56 | ĐẠT |
| `block10` | 64 KiB | 5 / 0 | 0,00 | 0,00 | 0,00 | 0,00 | ĐẠT |
| `block60` | 64 KiB | 5 / 0 | 2,50 | 2,62 | 2,31 | 2,62 | ĐẠT |
| `block10rst` | 64 KiB | 5 / 0 | 2,19 | 2,44 | 2,12 | 2,44 | ĐẠT |
| `kill` | 64 KiB | 5 / 0 | 7,25 | 7,62 | 6,75 | 7,62 | ĐẠT |
| `killlive` | 64 KiB | 15 / 0 | 23,69 | 24,31 | 6,94 | 24,31 | ĐẠT |
| `rst` | mặc định | 3 / 0 | 2,31 | 2,50 | 1,56 | 2,50 | ĐẠT |
| `block60` | mặc định | 3 / 0 | 2,69 | 2,81 | 2,44 | 2,81 | ĐẠT |
| `killlive` | mặc định | 3 / 0 | 24,19 | 24,25 | 23,31 | 24,25 | ĐẠT |

Lớn nhất qua mọi lần: **24,31 MiB** (25 493 504 byte, `killlive`, proxy 64 KiB). Cả 49 lượt xong với `result: done` hai bên, SHA-256 khớp, mã thoát `send` 0, thư mục tạm đã xóa; không lần nào quá hạn hay lỗi đo.

**Phần gửi thừa đến từ đâu** (theo số khối đã `MARK` lúc cắt; khối 1 MiB)

- `block10`: kết nối không đứt (không có `reconnecting`), byte bị giữ trong proxy đi tiếp, không gửi lại gì.
- `rst`, `block10rst`, `block60`: có `reconnecting`. Trước khi gửi `resume`, bên nhận đánh dấu các khối đã ghi mà chưa đánh dấu ([protocol.md](protocol.md) mục 4.3), nên phần gửi thừa chỉ còn dữ liệu đang trên đường lúc đứt (bộ đệm socket hai đầu, proxy, khối đang đọc dở): 1,56–2,81 MiB. Với `block60`, `.state` lúc hết chặn đã có 869 khối, tức bên nhận đã tự đánh dấu phần còn lại trong lúc chặn.
- `kill`, `killlive`: phần đã nhận mà chưa `MARK` mất theo tiến trình. Khi lần `MARK` gần nhất trước lúc giết là khối 848 (vị trí cắt khoảng 870,4–871,8 MiB byte TCP), phần gửi thừa 23,0–24,31 MiB; khi là khối 864 thì 6,75–8,38 MiB. Phần lớn nhất vì vậy là các khối chưa đánh dấu (cận trên ở [protocol.md](protocol.md) mục 4.3), phần do bộ đệm socket cộng proxy chỉ khoảng 1,5–2,8 MiB như ở các kiểu rớt mạng.
- Proxy bộ đệm mặc định không làm số đo lớn hơn rõ so với proxy 64 KiB (lớn nhất 2,81 so với 2,62 MiB ở các kiểu rớt mạng; 24,25 so với 24,31 MiB ở `killlive`).

**Kết luận**

- Trên loopback Windows: mọi lần nằm trong ngưỡng mvp N4 (**ĐẠT**, 49/49).
- Tiêu chí chốt bộ đệm (mục 7.1): lớn nhất 24,31 MiB ≤ 48 MiB → **không đặt** `SO_RCVBUF`/`SO_SNDBUF` trên Windows (theo số đo loopback). Linux chưa đo (mục 7.4); quyết định cho Linux và lý do: [protocol.md](protocol.md) mục 4.3.

**Giới hạn của lần đo này**

- Loopback: RTT gần bằng 0, nên tự điều chỉnh bộ đệm của Windows (theo băng thông × RTT) có thể giữ bộ đệm nhỏ hơn khi qua card mạng thật; phần do bộ đệm socket trên mạng thật có thể lớn hơn số ở đây. Card mạng thật và Wi-Fi: D5.
- Có thêm một proxy ở giữa; proxy giữ tối đa vài đoạn 64 KiB và bộ đệm socket của chính nó, làm số đo lớn hơn một chút chứ không nhỏ hơn.
- Vị trí cắt tính theo byte TCP qua proxy, không theo payload; `killlive` giết theo bộ đếm đọc khoảng 1 ms một lần, nên vị trí giết lệch tới khoảng 1,4 MiB sau mốc.
- Chỉ Windows 11 ↔ Windows 11 trên cùng một máy, Python 3.14, một cỡ file (1 GiB); có tải của các agent khác (thông lượng không phải đối tượng đo).

### 7.4. Việc còn lại

- **Linux: chưa đo.** Máy ảo `Teleport-N1` (mục 3.3) đang tắt; phiên đo không có kênh chạy lệnh trong máy ảo (agent của mục 3.5 chỉ có lệnh cho N1, không có `guestcontrol` hay SSH đã cấu hình), Teleport trong máy ảo còn ở commit `efa9d5b` và phải cập nhật lên commit cần đo (cần Internet trong máy ảo), và chiều máy ảo gửi → host nhận cần mở tường lửa của host bằng quyền Administrator. Cần người dùng chạy theo mục 7.5; dời vào đợt đo D5 ([ke_hoach.md](ke_hoach.md) mục 5.4).
- Card mạng thật, Wi-Fi (tắt Wi-Fi giữa lượt rồi bật lại) và macOS: **chưa đo**, thuộc đợt đo trên thiết bị thật ([ke_hoach.md](ke_hoach.md) mục 5.4, D5).
- Nhiều file trong một lượt, và nhiều lần gián đoạn trong một lượt: **chưa đo**.

### 7.5. Cách đo lại

Script nằm ngoài repo (không commit). Chạy bằng `python.exe` của `.venv`, với `PYTHONPATH` trỏ `src` của mã cần đo; thư mục tạm của mỗi lượt nằm trong `%TEMP%` (đường dẫn dài hơn thì `receive` báo đường dẫn quá dài), file nguồn ở `%TEMP%\teleport-n4-data` (xóa khi xong).

```
# loopback, trên một máy (PowerShell)
$env:PYTHONIOENCODING = "utf-8"
& $PY n4_bench.py --repo <repo> --kinds rst,block10,block60,kill --repeat 5 --size-mib 1024 --out results
& $PY n4_bench.py --repo <repo> --kinds killlive,block10rst --repeat 5 --size-mib 1024 --out results
& $PY n4_bench.py --repo <repo> --kinds rst,killlive,block60 --repeat 3 --size-mib 1024 --proxy-buf os --out results
& $PY n4_bench.py --summarize (Get-ChildItem results\run-*.jsonl).FullName
```

Linux, host Windows ↔ máy ảo Ubuntu bridged, cắt bằng `VBoxManage controlvm Teleport-N1 setlinkstate1 off`, chờ 10 / 60 s, `on` (script `n4_vm_host.py`, chạy trên host; không có proxy, hai đầu là socket thật của Windows và Linux):

1. Trong máy ảo: cập nhật Teleport lên đúng commit cần đo (`git fetch`, `git checkout <commit>`, `.venv/bin/pip install -e .`); `sudo ufw status` là *active* thì mở cổng 47474 chỉ cho IP host.
2. Ghép đôi một lần: máy ảo `teleport --config-dir ~/n4/R listen --port 47474`; host `teleport --config-dir <S> pair <VM_IP>:47474`; xác nhận mã hai bên.
3. Chiều host gửi → máy ảo nhận: máy ảo `teleport --config-dir ~/n4/R receive --json --yes --dir ~/n4/nhan --port 47474`, và xóa file đã nhận xong giữa các lượt (`rm ~/n4/nhan/*.bin`). Host:
   `& $PY n4_vm_host.py --vm Teleport-N1 --config-dir <S> --to <tên máy ảo> --address <VM_IP>:47474 --src <file 1 GiB> --kinds link10,link60 --repeat 3`
4. Chiều máy ảo gửi → host nhận (đo `SO_SNDBUF` của Linux): mở tường lửa host tạm cho IP máy ảo (Administrator, như `n1_firewall.ps1` ở mục 3.5), rồi host `& $PY n4_vm_host.py --role recv-host --vm Teleport-N1 --config-dir <S> --dir <thư mục nhận> --port 47474 --kinds link10,link60 --repeat 3`; mỗi lượt chạy `teleport --config-dir ~/n4/R send --json <file> --to <tên host> --address <HOST_IP>:47474` trong máy ảo và dán dòng `result` của nó khi script hỏi.
5. Dọn: `VBoxManage controlvm Teleport-N1 setlinkstate1 on` (script tự bật lại khi lỗi), đóng tường lửa, xóa file nhận.

## 8. mvp N11: Cài đặt (cỡ gói)

### 8.1. Định nghĩa phép đo

- **Cỡ thư mục:** tổng `st_size` của mọi file trong `dist\teleport-gui\` do PyInstaller `--onedir` tạo từ `packaging/pyinstaller/teleport-gui.spec` (không tính cỡ thư mục, cụm đĩa).
- **Cỡ zip:** cỡ file zip tạo từ thư mục đó bằng `zipfile` của Python, `ZIP_DEFLATED` mức 6, gốc zip là `teleport-gui\`, file xếp theo đường dẫn. Đây **không** phải zip artifact của workflow “Build GUI (thử)” (do GitHub nén) và **không** phải bộ cài mà mvp N11 đặt trần; chỉ để so các bản build với nhau.
- **Cỡ bộ cài:** `Length` của file `teleport-setup-<phiên bản>-x64.exe` do ISCC build từ `packaging/inno/teleport.iss` và thư mục `dist\teleport-gui\` (mục “Bộ cài Windows” trong `CONTRIBUTING.md`). Đây là cỡ mà trần của mvp N11 áp vào.
- **Cỡ sau khi cài:** tổng `Length` của mọi file trong thư mục cài sau khi cài silent xong, **kể cả** `unins000.exe` và `unins000.dat` của Inno; đếm số file cùng lúc. Không tính cỡ thư mục, cụm đĩa, lối tắt Start Menu và khóa registry.
- **Không cần khởi động lại:** dòng `Need to restart Windows?` trong log của bộ cài (`/LOG=`) và của trình gỡ.
- **Gỡ sạch:** sau khi trình gỡ chạy xong, thư mục cài, khóa `HKCU\...\Uninstall\{AppId}_is1` và lối tắt Start Menu đều không còn. Dữ liệu người dùng ở `%APPDATA%\Teleport` được giữ khi gỡ silent theo thiết kế ([architecture.md](architecture.md) mục 4, “Bộ cài Windows”), không thuộc phép kiểm này.
- Đơn vị: byte; MiB = 2²⁰ byte; MB = 10⁶ byte.

### 8.2. Lần đo 2026-10-30/31: trước/sau A2 (QtSvg, 47 icon SVG, font Bricolage Grotesque)

**Môi trường build** (như nhau cho ba bản, cùng một venv build riêng trong scratchpad)

| | |
|---|---|
| Máy | Windows 11 Pro 10.0.26300 |
| Công cụ | PyInstaller 6.22.3 (contrib hooks 2026.9), PySide6-Essentials 6.12.0, Python 3.14.5 |
| Nguồn | Worktree `feat/ui-assets`, trên commit `9639b08` (A1) cộng thay đổi chưa commit của A2; ba bản build từ ba trạng thái của cây làm việc, không có commit riêng. `teleport.__version__` = `0.1.0a0` |

**Kết quả**

| Bản | Số file | Thư mục (B) | Thư mục (MiB) | Zip (B) | Zip (MiB) | Nguồn số |
|---|---|---|---|---|---|---|
| Trước A2 | 97 | 79 593 643 | 75,91 | 33 969 172 | 32,40 | `dong-goi` đo (build 30/10 23:13 giờ máy); kiểm lại 31/10 từ thư mục build và zip còn trong scratchpad: khớp từng byte, zip tạo lại cũng khớp |
| Chỉ phần đóng gói của A2 | 149 | 80 787 141 | 77,04 | 34 584 189 | 32,98 | `dong-goi` đo (build 30/10 23:22 giờ máy); kiểm lại 31/10 như dòng trên: khớp |
| Sau A2 | 149 | 80 803 033 | 77,06 | 34 601 261 | 33,00 | `do-dac` đo 31/10 (build 31/10 06:22 giờ máy); zip tạo lại khớp |

“Chỉ phần đóng gói” đã có đủ 52 file mới của A2 (danh sách file giống hệt bản sau A2); hai bản khác nhau chủ yếu ở mã Python của `ui` (archive PYZ trong `Teleport.exe`, +15 891 B); `THIRD-PARTY-NOTICES.txt` +1 B, `SOURCE.txt` và `base_library.zip` khác nội dung nhưng cùng cỡ.

**Chênh lệch sau A2 so với trước A2:** thư mục +1 209 390 B (+1,52%), zip +632 089 B (+1,86%), +52 file. Phần thêm vào thư mục:

| Thành phần | B |
|---|---|
| `Qt6Svg.dll` | 608 056 |
| `QtSvg.pyd` | 116 536 |
| `BricolageGrotesque.ttf` (+ `OFL.txt`: tổng 412 899) | 408 496 |
| 47 icon SVG (+ `LICENSE`: tổng 46 273) | 45 195 |
| `Teleport.exe` (chứa archive PYZ, tức mã Python của `ui`) | 15 891 |
| `THIRD-PARTY-NOTICES.txt` | 9 017 |
| `SOURCE.txt` | 718 |

Phần lớn thêm vào là QtSvg (724 592 B, khoảng 60%) và font (khoảng 34%); icon chỉ khoảng 4%.

### 8.3. So với mvp N11 và việc còn lại

Từ 2026-10-31 (mục 8.4, bộ cài thử của PR E2, chế độ `/CURRENTUSER`, máy dev chứ không phải máy ảo sạch):

| Tiêu chí của mvp N11 | Số đo | Kết luận |
|---|---|---|
| Cỡ bộ cài ≤ trần | 26 078 484 B = 24,87 MiB = 26,08 MB (10⁶): dưới trần dù “MB” là MiB hay 10⁶ byte, còn dư khoảng 3 lần | **ĐẠT** (cả hai cách hiểu) |
| Không cần khởi động lại | Log cài và log gỡ: `Need to restart Windows? No` ở cả 3 lần | **ĐẠT ở chế độ một người dùng**; chế độ quản trị (có rule tường lửa) chưa đo |
| Gỡ cài đặt sạch | 3/3 lần: thư mục cài, khóa `Uninstall\{AppId}_is1`, lối tắt Start Menu mất; log gỡ `Removed all? Yes` | **ĐẠT ở chế độ một người dùng**; tùy chọn xóa dữ liệu (chỉ hỏi khi gỡ có giao diện) và chế độ quản trị chưa kiểm |
| Kiểm trên máy ảo sạch | — | **chưa đo** |

- Cỡ **sau khi cài** là 85 256 013 B = 81,31 MiB = 85,26 MB (10⁶), 151 file: **trên** con số 80 dù hiểu “MB” theo cách nào. mvp N11 chỉ đặt trần cho bộ cài, không cho cỡ sau khi cài; ghi lại để chủ của `mvp.md` quyết có cần trần cho cỡ này không. Riêng các file của app (không tính `unins000.*`) là 80 826 254 B = 77,08 MiB = 80,83 MB; trình gỡ của Inno thêm 4 429 759 B.
- Cỡ zip ở mục 8.2 chỉ để so các bản build với nhau. Bộ cài (`lzma2/max`, nén khối) bằng 75 % zip “Sau A2” của mục 8.2 (26 078 484 / 34 601 261 B); hai bản build khác nhau (thư mục `dist` chênh 24 414 B) nên tỉ lệ này chỉ để tham khảo.
- Còn **chưa đo**: (1) cài/gỡ ở chế độ quản trị (mặc định khi cài bằng tay, cần quyền quản trị): “không cần khởi động lại” và việc tạo/xóa hai rule tường lửa; (2) toàn bộ phép kiểm trên **máy ảo Windows sạch** như mvp N11 yêu cầu (máy dev đã có sẵn `%APPDATA%\Teleport`, Python, VC++ runtime…); (3) gỡ có giao diện với lựa chọn giữ/xóa cài đặt và thiết bị tin cậy. Thuộc Giai đoạn 6 ([ke_hoach.md](ke_hoach.md) mục 5.2).

Trước 2026-10-31 (giữ nguyên):

- Trần của mvp N11 áp cho **bộ cài** Windows; chưa có bộ cài nên mục này là **chưa đo**. Cỡ zip ở trên chỉ để tham khảo: bộ cài nén cùng các file này, nhưng cỡ còn tùy công cụ và mức nén.
- Zip sau A2 dưới trần của mvp N11 với khoảng cách lớn. Thư mục đã giải nén (cái người dùng thấy sau khi cài) xấp xỉ trần: dưới trần nếu “MB” trong mvp N11 là MiB, **trên** trần nếu là 10⁶ byte. mvp N11 không nói rõ đơn vị và không đặt trần cho cỡ sau khi cài; ghi lại để chủ của `mvp.md` quyết.
- Còn lại: cỡ bộ cài thật, “không cần khởi động lại” và gỡ cài đặt sạch, kiểm trên máy ảo sạch theo mvp N11 (Giai đoạn 6, [ke_hoach.md](ke_hoach.md) mục 5.2).

**Cách đo lại:** build theo `CONTRIBUTING.md`, rồi chạy script tạo zip và in cỡ (đặt ngoài repo, nội dung đúng như dưới):

```python
import sys, zipfile, pathlib

dist = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
total = 0
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
    for p in sorted((dist / "teleport-gui").rglob("*")):
        if p.is_file():
            total += p.stat().st_size
            z.write(p, p.relative_to(dist).as_posix())
print(f"thư mục {total} B; zip {out.stat().st_size} B")
```

```powershell
python -I zipsize.py <thư mục dist> <đường dẫn zip ra>
```

### 8.4. Bộ cài

#### Lần đo 2026-10-31: bộ cài Inno Setup thử của PR E2, cài/gỡ `/CURRENTUSER`

**Môi trường**

| | |
|---|---|
| Máy | Windows 11 Pro 10.0.26300, Intel Core i7-12800H, RAM 15,7 GiB; máy dev, **không** phải máy ảo sạch (đã có `%APPDATA%\Teleport` từ trước, không bị bộ cài động tới) |
| Quyền | Không elevated; cài với `/CURRENTUSER` nên không tạo rule tường lửa (log cài không có dòng `netsh`) |
| Nguồn | Worktree `installer-e2-439eb3`, commit `f42b64f` **cộng thay đổi chưa commit** của PR E2 sau các sửa lỗi soát code (bộ cài build lại 31/10 14:25 giờ máy; `dist` không build lại) (`packaging/inno/`, `build-gui.yml`, `pyproject.toml`, docs; không đổi `src/`). `teleport.__version__` = `0.1.0a0` |
| Build | `dist\teleport-gui\` (149 file, 80 827 447 B) build bằng `.venv` của worktree: Python 3.14.5, PyInstaller 6.22.3 theo `packaging/pyinstaller/requirements.txt`; bộ cài build bằng ISCC 6.7.3 (log cài: `Inno Setup version 6.7.3`), `Compression=lzma2/max`, `SolidCompression=yes` |
| Bộ cài | `installer\teleport-setup-0.1.0a0-x64.exe`, SHA-256 `C3A416A42DE5EA1D1D4F37A7D534C434E62C683BAB0295E4CA5C90DA0DE38D10` |

**Cách chạy mỗi lần:** `teleport-setup-….exe /VERYSILENT /SUPPRESSMSGBOXES /CURRENTUSER /NORESTART /DIR=%TEMP%\tpn11\app /LOG=…`, đo thư mục cài và khóa gỡ cài đặt, rồi `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /LOG=…` và chờ tới khi khóa và thư mục mất. `/NORESTART` để bộ cài không tự khởi động lại máy nếu cần; log vẫn ghi `Need to restart Windows?` đúng như khi không có cờ này. Không chạy app.

**Kết quả** (3 lần, 0 lần hỏng; số liệu cỡ giống hệt nhau ở cả 3 lần)

| Đại lượng | B | MiB | MB (10⁶) | Số file |
|---|---|---|---|---|
| Bộ cài | 26 078 484 | 24,87 | 26,08 | 1 |
| Thư mục sau khi cài (kể cả `unins000.*`) | 85 256 013 | 81,31 | 85,26 | 151 |
| Trong đó `unins000.exe` + `unins000.dat` | 4 376 082 + 53 677 = 4 429 759 | 4,22 | 4,43 | 2 |
| Trong đó file của app | 80 826 254 | 77,08 | 80,83 | 149 |

- So với `dist\teleport-gui\`: bộ cài bỏ `DOC-TRUOC.txt` (2 714 B) và thêm `licenses\InnoSetup-license.txt` (1 521 B), ngoài ra giống hệt danh sách file.
- `EstimatedSize` trong khóa gỡ cài đặt (Inno tự tính, hiện ở “Apps”): 83 180 KiB.
- Khởi động lại: log cài và log gỡ đều `Need to restart Windows? No` ở cả 3 lần; Restart Manager báo không có ứng dụng nào giữ file.
- Gỡ: 3/3 lần thư mục cài, khóa `HKCU\...\Uninstall\{A82B1EF5-F24A-4DA0-841B-09F4E2F6D4C1}_is1` và `Teleport.lnk` trong Start Menu đều mất; log gỡ `Removed all? Yes`. Giá trị `Teleport` ở `HKCU\...\Run` không có trước và sau. Lối tắt Desktop không được tạo (tùy chọn mặc định tắt).
- Thời gian (đồng hồ `Stopwatch`, chỉ ghi nhận, mvp N11 không đặt ngưỡng): cài 4,79 / 8,70 / 3,82 s; gỡ 2,12 / 1,55 / 2,26 s.

**Giới hạn:** máy dev chứ không phải máy ảo sạch; chỉ chế độ một người dùng; không có lần cài có giao diện. Kết luận so với mvp N11 ở mục 8.3.

**Cách đo lại:** build `dist\teleport-gui\` và bộ cài theo `CONTRIBUTING.md` (ISCC chạy qua PowerShell, không qua Git Bash), kiểm máy chưa cài Teleport bằng bộ cài, rồi chạy script đo (đặt ngoài repo; lưu UTF-8 **có BOM** để Windows PowerShell 5.1 đọc đúng tiếng Việt), trong PowerShell không elevated:

```powershell
& <scratchpad>\n11_installer.ps1 -Setup installer\teleport-setup-0.1.0a0-x64.exe -DistDir dist\teleport-gui -Repeat 3
```

Script (`n11_installer.ps1`, phiên đo 2026-10-31) dừng ngay nếu khóa gỡ cài đặt của Teleport đã có ở HKCU hoặc HKLM, nếu `%TEMP%\tpn11` đã có hoặc nếu đang elevated; mỗi lần cài/gỡ có hạn 180 s; cuối cùng xóa `%TEMP%\tpn11` (chỉ khi khóa gỡ cài đặt đã mất). Đường dẫn cài phải ngắn: thư mục quá sâu làm bộ cài lỗi 206.

## 9. mvp N6: Clipboard

### 9.1. Định nghĩa phép đo

- **Độ trễ một clip:** từ ngay trước lúc máy A “sao chép” (`FakeClipboard.set_text` / `set_image` ở A) tới lúc backend của máy B ghi xong nội dung đó (mục mới trong `FakeClipboard.writes` của B, mốc `time.monotonic()`). Hai node chạy trong **một** tiến trình, cùng đồng hồ `time.monotonic()`, nên không phải so đồng hồ hai máy. Số đo đã gồm thời gian gộp `CLIP_DEBOUNCE` của bên gửi (docstring `app/clipboard.py`). Lần hợp lệ: B ghi đúng nội dung A sao chép (so nguyên văn bản / byte PNG); không thấy trong 15 s là **quá hạn**.
- **Mốc phụ** (để biết phần nào tốn thời gian): A bắt đầu đọc backend (hết gộp), A bắt đầu gửi mảnh `index 0` (`Connection.send`), B nhận mảnh cuối (`ClipboardSync.on_message`), B ghi xong. Bốn đoạn: *gộp* (sao chép → đọc), *đọc → mảnh 0* (đọc, fingerprint, `split_clip`), *mảnh 0 → mảnh cuối tới B* (gửi mọi mảnh qua TLS, B đọc khung, kiểm message, ráp), *mảnh cuối → ghi* (kiểm SHA-256, fingerprint, ghi).
- **RAM (M3):** working set và private bytes của tiến trình (`GetProcessMemoryInfo` qua `ctypes`, như mục 4.1; gồm **cả hai** node và script), và `tracemalloc` (byte Python còn cấp phát, tính từ lúc bật ngay trước clip đo đầu tiên). Đọc trước clip đo đầu tiên (sau 20 clip khởi động, 3 s nghỉ, `gc.collect()`) và 5 s sau clip cuối, trước và sau `gc.collect()`. Tiêu chí “phẳng” chốt **trước khi đo**: tăng < 10 MB (10⁶ byte), xét working set và `tracemalloc` sau `gc`.

### 9.2. Phương pháp

- Hai `Node` thật (A gửi, B nhận), mỗi node một thư mục cấu hình riêng trong thư mục làm việc của script, đã tin nhau (`trusted.json` dựng bằng `TrustStore.add`, như fixture `trust_each_other`), nghe `127.0.0.1` cổng ngẫu nhiên, không mDNS; A nối B bằng `Node.connect_hint`; bật “Đồng bộ clipboard” ở cả hai đầu (`Node.set_clipboard`). Backend là `FakeClipboard` (`app/clipboard.py`): không giải mã ảnh, fingerprint ảnh là hash của byte PNG. Không vá hằng số nào (gộp, giới hạn tốc độ, trần RAM đều là mặc định của mã).
- **M1, M2** (tuần tự): mỗi lần một nội dung mới (văn bản ASCII ngẫu nhiên có mã riêng ở đầu; PNG đủ cấu trúc chunk, IHDR hợp lệ 3000×3000, IDAT là byte ngẫu nhiên, tổng đúng 10 MiB); chờ B ghi rồi nghỉ 0,3 s mới sao chép tiếp. Nhịp vì vậy ≤ 2,2 clip/s, dưới giới hạn tốc độ của bên gửi (docstring `app/clipboard.py`, “Hàng gửi”), nên số đo không gồm thời gian chờ token. 3 lần khởi động đầu không tính.
- **M3:** 1000 clip xen kẽ văn bản 100 000 byte và PNG 1 000 000 byte (mỗi clip khác nhau), nhịp mở đều (không chờ B), sau 20 clip khởi động. Hai nhịp: 0,25 s (4 clip/s, bằng giới hạn của bên gửi) và 0,2 s (5 clip/s, vượt giới hạn đó: clip mới thay clip đang chờ token ở bên gửi, theo thiết kế). Ở M3, `FakeClipboard.writes` chỉ giữ mốc thời gian, không giữ nội dung (danh sách này là bản ghi của đồ giả, không phải của app), và script chỉ đếm `ClipboardEvent` (lượt 1 còn giữ các event, xem mục 9.3).
- Mọi lần chờ có hạn; xong thì `Node.close()` cả hai và xóa thư mục cấu hình.

### 9.3. Lần đo 2026-11-02: tầng app (`app.clipboard`) với `FakeClipboard`, loopback trên một máy Windows 11

Hai lượt liền nhau, 00:59–01:09 và 01:09–01:23 giờ máy, cùng script. Lượt 2 chạy lại vì máy có tải nền nặng (bảng môi trường); số của hai lượt khớp nhau.

**Môi trường**

| | |
|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 |
| Python | 3.14.5 (64 bit, qua `.venv` ở checkout chính), `ProactorEventLoop` |
| Teleport | `__version__` 0.1.0a0; worktree `ui-clipboard-d5-91ccf3`, commit `8dcecf2` (`main`) **cộng thay đổi chưa commit của tầng app** (`app/clipboard.py` mới; `app/node.py`, `core/clipboard.py` sửa). SHA-256 (12 ký tự đầu) lúc đo, giống nhau trước và sau hai lượt: `app/clipboard.py` `9c5497958bd9`, `app/node.py` `5ff6d5616ab1`, `core/clipboard.py` `9c82f1e97d2f`. Mã nạp từ `src/` của worktree qua `PYTHONPATH` (đã kiểm `teleport.__file__`); tầng `ui` (đang được sửa song song) không được nạp |
| cryptography | 50.0.2 (mDNS tắt) |
| CPU / RAM | Intel Core i7-12800H, 20 luồng / 15,7 GiB, trống 2,7–5,3 GiB lúc bắt đầu từng phép đo |
| Mạng | loopback 127.0.0.1, TLS 1.3 như khi chạy thật |
| Tải nền | các agent khác chạy song song 2–6 tiến trình `pytest` (cả `-n 4` lẫn test giao diện); CPU toàn máy bận trung bình 54–91 % trong từng phép đo (`GetSystemTimes`) |

**Kết quả độ trễ** (ms; mọi lần hợp lệ: 0 quá hạn, 0 sai nội dung; p95 theo hạng gần nhất)

| Phép đo | Lượt | Số lần | Trung vị | p95 | Min | Max | So với ngưỡng mvp N6 (chỉ trên loopback) |
|---|---|---|---|---|---|---|---|
| M1 văn bản 1 KB | 1 | 200 | 158,1 | 161,1 | 154,2 | 163,6 | dưới ngưỡng văn bản |
| M1 văn bản 1 KB | 2 | 200 | 158,4 | 161,9 | 154,2 | 164,0 | dưới ngưỡng văn bản |
| M1 văn bản 1 MiB | 1 | 200 | 264,4 | 335,3 | 202,7 | 379,8 | dưới ngưỡng văn bản |
| M1 văn bản 1 MiB | 2 | 200 | 261,9 | 320,2 | 213,6 | 415,9 | dưới ngưỡng văn bản |
| M2 PNG 10 MiB | 1 | 20 | 1131,5 | 1293,9 | 1052,6 | 1328,9 | dưới ngưỡng ảnh |
| M2 PNG 10 MiB | 2 | 20 | 1044,2 | 1134,3 | 775,2 | 1136,1 | dưới ngưỡng ảnh |

**Thời gian đi đâu** (ms, trung vị / p95 của từng đoạn ở mục 9.1)

| Phép đo | Lượt | Gộp | Đọc → mảnh 0 | Mảnh 0 → mảnh cuối tới B | Mảnh cuối → ghi |
|---|---|---|---|---|---|
| M1 1 KB | 2 | 155,7 / 157,7 | 1,0 / 2,1 | 0,4 / 1,8 | 0,6 / 1,5 |
| M1 1 MiB | 1 | 165,9 / 176,1 | 34,0 / 67,9 | 29,2 / 63,8 | 23,4 / 63,0 |
| M1 1 MiB | 2 | 166,4 / 174,8 | 34,9 / 69,9 | 29,3 / 65,6 | 23,4 / 50,0 |
| M2 10 MiB | 1 | 172,0 / 180,4 | 304,3 / 382,6 | 614,3 / 745,3 | 26,7 / 42,8 |
| M2 10 MiB | 2 | 173,6 / 179,8 | 273,6 / 337,1 | 565,7 / 627,5 | 27,3 / 36,8 |

- Văn bản nhỏ: gần như toàn bộ là thời gian gộp. Với nội dung lớn, đoạn “gộp” dài hơn `CLIP_DEBOUNCE` 10–20 ms vì mốc đầu đặt trước `set_text`, mà `FakeClipboard.set_text` tự tính fingerprint của nội dung trước khi báo đổi, và vì loop còn bận với clip trước.
- Ảnh 10 MiB: đoạn lớn nhất là *mảnh 0 → mảnh cuối* (20 mảnh base64, khoảng 14 MB trên dây; trên loopback đoạn này chủ yếu là CPU: TLS, đọc và kiểm khung JSON, giải base64), rồi *đọc → mảnh 0* (SHA-256 và chia base64 10 MiB trong executor). Đoạn ghi nhỏ vì `FakeClipboard` không giải mã PNG; backend Qt thật sẽ thêm thời gian giải mã (M4, chưa đo).

**Kết quả RAM (M3)** (MiB = 2²⁰ byte; MB = 10⁶ byte; “tăng” = sau `gc` − trước)

| Lượt | Nhịp | Clip B ghi / 1000 | Working set trước → sau (MiB) | Tăng working set | Tăng private bytes | `tracemalloc` sau `gc` (đỉnh) | Max working set ¼ đầu / ¼ cuối (MiB) | Kết luận (tăng < 10 MB) |
|---|---|---|---|---|---|---|---|---|
| 1 | 0,25 s | 1000 | 71,99 → 72,43 | +0,45 MB | +0,21 MB | 4,13 MiB (7,37) | 73,2 / 73,2 | phẳng |
| 2 | 0,25 s | 998 | 71,10 → 68,66 | −2,56 MB | −3,09 MB | 3,34 MiB (7,40) | 71,8 / 71,4 | phẳng |
| 2 | 0,2 s | 800 | 71,50 → 71,46 | −0,05 MB | +0,38 MB | 3,32 MiB (7,37) | 71,3 / 70,3 | phẳng |

- `tracemalloc` còn lại sau `gc` không tăng theo số clip: khoảng 1,27 MiB là các mảnh base64 của clip ảnh cuối mà A vừa gửi (cấp ở `split_clip`), 0,95 MiB là ảnh cuối trong clipboard giả của B, 0,95 MiB là ảnh cuối trong clipboard giả của A (do script tạo), dưới 0,15 MiB là danh sách mốc của script. Lượt 1 còn giữ mọi `ClipboardEvent` trong script (khoảng 0,47 MiB cho 2000 event); lượt 2 chỉ đếm.
- Nhịp 0,2 s: B ghi 800/1000 vì giới hạn tốc độ của bên gửi, clip mới thay clip đang chờ (đúng thiết kế, không phải lỗi). Nhịp 0,25 s lượt 2: B ghi 998/1000, 2 clip bị clip sau thay ở chỗ chờ khi loop chậm (CPU toàn máy bận trung bình 91 % trong phép đo đó).
- Working set đỉnh của tiến trình (hai node cộng script, tính từ lúc khởi động): 74,8–76,0 MiB.

**Kết luận**

- Trên loopback với `FakeClipboard`: văn bản 1 KB, 1 MiB và ảnh PNG 10 MiB đều dưới ngưỡng mvp N6 ở mọi lần của cả hai lượt (p95 văn bản lớn nhất 335,3 ms, ảnh chậm nhất 1328,9 ms); RAM phẳng sau 1000 clip ở cả hai nhịp.
- So với mvp N6: **CHƯA ĐỦ DỮ LIỆU**, vì mvp N6 đặt ngưỡng trên Wi-Fi 5 giữa hai máy (D6) và chưa có backend clipboard thật (M4).
- Phép tính (không phải số đo) cho D6: phần không phụ thuộc mạng của ảnh 10 MiB (gộp + đọc → mảnh 0 + mảnh cuối → ghi) có p95 cộng lại khoảng 0,6 s trên máy này, nên trên Wi-Fi còn khoảng 1,4 s cho khoảng 14 MB trên dây cộng thời gian giải mã PNG của backend Qt.

**Giới hạn của lần đo này**

- Loopback, RTT gần 0; hai node chung một tiến trình và một loop (CPU của hai bên dồn lên một luồng; trên hai máy thật mỗi bên một luồng nhưng có thêm mạng).
- `FakeClipboard` không đọc/ghi clipboard của hệ điều hành và không mã hóa/giải mã ảnh; thời gian của `QClipboard` và giải mã PNG chưa có (M4).
- Máy có tải nền nặng của các agent khác (bảng môi trường).
- RAM là của cả tiến trình (hai node cộng script), không tách được từng node.

### 9.4. Lần đo 2026-11-02: M4, backend Qt (`QtClipboardBackend`), nền Qt offscreen trên một máy Windows 11

05:37–05:47 giờ máy, một lượt.

**Định nghĩa**

- **`read`:** ảnh đã nằm trên clipboard (script đặt `setImage` một bản sao mới, cùng ảnh, `cacheKey` mới, nên không đi đường tắt “vọng của lần ghi”), đo từ ngay trước `await backend.read()` tới lúc nó trả về, trên loop asyncio ở thread riêng như node thật (`time.perf_counter`). Gồm chuyển việc sang thread Qt, `clipboard.image()`, rồi trong pool: đổi `RGBA8888`, fingerprint, mã hóa PNG (docstring `ui/clipboard_qt.py`, “Đọc”). Lần hợp lệ: `OK` có fingerprint đúng bằng fingerprint tính trước, hoặc `TOO_LARGE` khi PNG vượt `MAX_PNG_BYTES` (khi đó thời gian vẫn gồm trọn lần mã hóa).
- **`write`:** từ ngay trước `await backend.write(PNG, png)` tới lúc trả về; `png` là đúng byte mà `encode_image` tạo cho ảnh đó (thứ máy gửi sẽ gửi). Gồm giải mã PNG, đổi `RGBA8888`, fingerprint trong pool, `setImage` và đọc lại trên thread Qt. Lần hợp lệ: `OK` và fingerprint đầu đúng bằng fingerprint mong đợi.
- **Lệch thread Qt:** `QTimer` 10 ms (`PreciseTimer`) trên thread Qt, slot Python ghi `perf_counter`; số ghi là khoảng cách lớn nhất giữa hai lần chạy slot trong lúc một thao tác chạy (10 ms là không lệch). Vì slot là Python, số này gồm cả lúc thread Qt chờ GIL, đúng như các slot của app.
- **RAM:** working set của tiến trình (`GetProcessMemoryInfo`), lấy mẫu mỗi 2 ms ở một thread riêng; số ghi là mức tăng đỉnh trong một thao tác so với ngay trước thao tác đó (lớn nhất qua mọi lần).
- **Ảnh thử:** `Format_RGB32` (đục, như ảnh chụp màn hình), hai loại: *dễ nén* (gradient chéo ba màu vẽ bằng `QPainter`) và *khó nén* (nhiễu ngẫu nhiên `os.urandom`, trường hợp xấu nhất cho PNG). Ba cỡ: 1920×1080, 3840×2160, 8192×8192.
- Mỗi tổ hợp một tiến trình riêng; 1 lần khởi động + 12 lần đo cho mỗi thao tác; `gc.collect()` và nghỉ 0,25 s trước mỗi lần. Thêm 3 lần đo từng bước (`_rgba`, `_fingerprint`, mã hóa PNG; giải mã PNG) gọi thẳng các hàm của module, ngoài backend, để biết phần nào tốn thời gian.

**Môi trường**

| | |
|---|---|
| Hệ điều hành | Windows 11 Pro, bản 10.0.26300 |
| Python / Qt | 3.14.5 (64 bit, `.venv` ở checkout chính); PySide6 6.12.0, nền QPA **`offscreen`** (clipboard trong tiến trình của Qt; không chạm clipboard thật của Windows) |
| Teleport | `__version__` 0.1.0a0; worktree `ui-clipboard-d5-91ccf3`, commit `8dcecf2` (`main`) **cộng thay đổi chưa commit của D5**; `ui/clipboard_qt.py` SHA-256 (12 ký tự đầu) `cfad91a7c4cc` (đã có `convertTo` tại chỗ và bỏ lần qua pool thứ hai khi đọc lại cùng `cacheKey`). Mã nạp từ `src/` của worktree qua `PYTHONPATH` (đã kiểm `teleport.__file__`) |
| CPU / RAM | Intel Core i7-12800H, 20 luồng / 15,7 GiB, trống khoảng 6,6 GiB lúc bắt đầu |
| Tải nền | một agent khác chạy test song song: 2 tiến trình `pytest` lúc bắt đầu hai tổ hợp 1920×1080, 0 ở các tổ hợp sau; CPU toàn máy bận trung bình 23–43 % trong từng tổ hợp (`GetSystemTimes`) |

**Kết quả** (ms; mọi lần hợp lệ: 0 lỗi, 0 sai fingerprint, 0 quá hạn; p95 theo hạng gần nhất)

| Ảnh | PNG | Thao tác | Số lần | Trung vị | p95 | Min | Max | Lệch Qt lớn nhất | RAM tăng đỉnh (MiB) |
|---|---|---|---|---|---|---|---|---|---|
| 1920×1080 gradient | 0,11 MiB | `read` → `OK` | 12 | 111,7 | 131,6 | 110,0 | 131,6 | 11,9 | 8 |
| 1920×1080 gradient | | `write` | 12 | 20,8 | 28,2 | 19,1 | 28,2 | 11,2 | 8 |
| 1920×1080 nhiễu | 6,84 MiB | `read` → `OK` | 12 | 478,0 | 534,5 | 451,7 | 534,5 | 12,2 | 28 |
| 1920×1080 nhiễu | | `write` | 12 | 51,1 | 58,7 | 47,7 | 58,7 | 12,1 | 15 |
| 3840×2160 gradient | 0,37 MiB | `read` → `OK` | 12 | 354,2 | 371,4 | 346,2 | 371,4 | 18,3 | 33 |
| 3840×2160 gradient | | `write` | 12 | 69,7 | 70,5 | 68,6 | 70,5 | 13,3 | 32 |
| 3840×2160 nhiễu | 27,21 MiB (vượt `MAX_PNG_BYTES`) | `read` → `TOO_LARGE` | 12 | 1880,3 | 1938,1 | 1868,6 | 1938,1 | 21,0 | 114 |
| 3840×2160 nhiễu | | `write` (*) | 12 | 196,8 | 224,3 | 193,6 | 224,3 | 14,7 | 59 |
| 8192×8192 gradient | 3,53 MiB | `read` → `OK` | 12 | 3020,0 | 3250,8 | 2931,9 | 3250,8 | 92,3 | 267 |
| 8192×8192 gradient | | `write` | 12 | 956,9 | 1058,9 | 941,9 | 1058,9 | 35,2 | 260 |
| 8192×8192 nhiễu | 219,42 MiB (vượt `MAX_PNG_BYTES`) | `read` → `TOO_LARGE` | 12 | 18375,1 | 24306,5 | 16677,7 | 24306,5 | 325,0 | 914 |
| 8192×8192 nhiễu | | `write` (*) | 12 | 1982,1 | 2116,1 | 1790,5 | 2116,1 | 69,4 | 476 |

(*) PNG lớn hơn `MAX_PNG_BYTES` không bao giờ tới backend của máy nhận (bên nhận bỏ trước khi ráp xong); hai dòng này chỉ là cận trên của thời gian giải mã.

Working set đỉnh của cả tiến trình (gồm cả lúc script tạo ảnh thử và PNG mẫu, nên lớn hơn phần của backend): 86 / 120 / 159 / 266 / 848 / 1708 MiB theo thứ tự sáu tổ hợp trên.

**Thời gian đi đâu** (ms, trung vị của 3 lần, gọi thẳng các hàm trong module, ngoài backend)

| Ảnh | `read`: đổi `RGBA8888` / fingerprint / mã hóa PNG | `write`: giải mã PNG / đổi `RGBA8888` / fingerprint |
|---|---|---|
| 1920×1080 gradient | 0,5 / 5,8 / 106,9 | 12,6 / 1,0 / 5,6 |
| 1920×1080 nhiễu | 0,5 / 5,2 / 451,3 | 45,4 / 0,7 / 5,3 |
| 3840×2160 gradient | 2,1 / 21,7 / 333,3 | 49,6 / 3,1 / 21,5 |
| 3840×2160 nhiễu | 2,1 / 21,3 / 1862,1 | 178,8 / 2,9 / 20,9 |
| 8192×8192 gradient | 20,2 / 176,6 / 2951,9 | 759,3 / 26,3 / 176,7 |
| 8192×8192 nhiễu | 21,7 / 195,5 / 18859,3 | 1847,9 / 29,8 / 207,2 |

- `read`: mã hóa PNG (`QImageWriter`) chiếm 94–99 % thời gian ở mọi cỡ; phần chuyển việc giữa các thread và `clipboard.image()` (offscreen) không đáng kể (tổng ba bước gần bằng thời gian `read`).
- `write`: giải mã PNG là phần lớn nhất; fingerprint (SHA-256 của 256 MiB ở 8192²) khoảng 180–210 ms. Thời gian đọc lại sau `setImage` không đáng kể (offscreen trả đúng ảnh đã đặt, cùng `cacheKey`, không qua pool lần hai).
- **Lệch thread Qt**, đo thêm từng bước với `QTimer` 10 ms (3 lần, 8192²): mã hóa PNG và SHA-256 không giữ GIL (lệch 11–14 ms suốt 3–21 s); các bước giữ GIL làm thread Qt chờ: chép PNG từ `QByteArray` sang `bytes` (`buffer.data().data()`: 113–221 ms với PNG 219 MiB, 1,6 ms với PNG 3,5 MiB), `convertTo` 8192² (lệch 22–30 ms), giải mã PNG 8192² (lệch 27–34 ms ảnh gradient, 66–89 ms ảnh nhiễu). Lệch 325 ms ở `read` 8192² nhiễu chủ yếu do bước chép PNG 219 MiB đó; lệch 92 ms ở `read` 8192² gradient chưa tách hết được (các bước đo riêng chỉ giải thích tới khoảng 30 ms).
- **RAM**: `read` 8192² tăng tới 267 MiB với ảnh dễ nén (ảnh 256 MiB tách khỏi bản của clipboard khi `convertTo`) và 914 MiB với ảnh nhiễu (thêm `QByteArray` của PNG 219 MiB đang lớn dần và bản `bytes` của nó); `write` 8192² tăng 260 MiB (gradient) và 476 MiB (nhiễu, PNG vượt trần nên không xảy ra ở máy nhận thật).

**Kết luận**

- Với PNG trong `MAX_PNG_BYTES`, phần backend thêm vào độ trễ một clip ảnh (`read` ở máy gửi + `write` ở máy nhận, p95, máy này, offscreen): 1920×1080 khoảng 0,16 s (gradient) và 0,59 s (nhiễu); 3840×2160 gradient khoảng 0,44 s; **8192×8192 gradient khoảng 4,3 s, riêng `read` đã 2,9–3,3 s**, tức vượt ngưỡng ảnh của mvp N6 ngay cả khi mạng tức thì, dù PNG chỉ 3,53 MiB. Phần tốn nhất là mã hóa PNG ở máy gửi (2,95 s trung vị), rồi giải mã ở máy nhận (0,76 s).
- Ảnh khó nén lớn: 3840×2160 nhiễu trả `TOO_LARGE` sau khoảng 1,9 s mã hóa; **8192×8192 nhiễu mất 16,7–24,3 s mới biết `TOO_LARGE`, dài hơn `CLIP_READ_TIMEOUT`** (`app/clipboard.py`): trong app thật lần đọc đó quá hạn, việc mã hóa vẫn chạy tiếp trong pool tới hết (cờ hủy chỉ được kiểm giữa các bước), và trong lúc đó mọi lần đọc ảnh mới trả `FAILED` ngay (docstring `ui/clipboard_qt.py`). Lệch thread Qt lớn nhất của ca này là 325 ms, các ca còn lại ≤ 92,3 ms.
- So với mvp N6: **KHÔNG ĐẠT** ở ca ảnh 8192² dễ nén: phần backend đo được là cận dưới của độ trễ một clip (chưa tính mạng) và đã vượt ngưỡng ảnh trên máy này (mục 1). Các ca còn lại **CHƯA ĐỦ DỮ LIỆU** (chưa đo trên máy thật với clipboard của hệ điều hành và Wi-Fi 5, D6).

**Giới hạn của lần đo này**

- Nền **offscreen**: `clipboard.image()` và `setImage` chỉ đổi đối tượng trong tiến trình. Trên Windows thật, `clipboard.image()` phải chuyển DIB/PNG của hệ điều hành ngay trên thread Qt (với ảnh 8192² có thể tới cỡ giây, docstring `ui/clipboard_qt.py`) và `setImage` phải xuất dữ liệu cho hệ điều hành; phần này **chưa đo**, nên số `read`/`write` và lệch Qt ở trên là cận dưới của máy thật.
- Ảnh nhiễu là trường hợp xấu nhất của PNG; ảnh chụp thật nằm giữa hai loại. Một máy, một lượt, có tải nền nhẹ (bảng môi trường).

#### Đo lại 2026-11-02 (lượt r3): sau khi thêm kiểm sơ bộ zlib trước mã hóa PNG

06:24–06:30 giờ máy, một lượt. Bảng trên là lượt r1 (“trước”). Thay đổi giữa hai lượt: `read` chạy `prescreen` (nén zlib mức thấp theo khối, dừng khi vượt `PRESCREEN_LIMIT_BYTES`, docstring `ui/clipboard_qt.py`) trước khi mã hóa PNG; vượt thì trả `TOO_LARGE` mà không mã hóa PNG. Mức nén PNG giữ mặc định của Qt (cỡ PNG của r3 bằng r1). Một lượt thử xen giữa (r2) còn đổi mức nén PNG, đã bỏ thay đổi đó, nên không dùng số r2.

- Định nghĩa, ảnh thử, số lần, script: như trên (lượt `-Tag r3`, 12 lần mỗi thao tác, mọi lần hợp lệ: 0 lỗi, 0 sai fingerprint, 0 quá hạn).
- Môi trường: như trên, trừ `ui/clipboard_qt.py` SHA-256 (12 ký tự đầu) `e014884587d2`; mã nạp từ `src/` của worktree (đã kiểm `teleport.__file__`).
- **Tải nền nặng hơn r1:** phiên chính chạy toàn bộ pytest song song (2 lượt `-n 4`, 2 tiến trình `pytest` cùng các worker) suốt cả lượt r3; CPU toàn máy bận trung bình 30–45 % trong từng tổ hợp (r1: 23–43 %, pytest chỉ chạy ở hai tổ hợp đầu). Số r3 của các ca `OK` vì vậy có nhiễu, thiên về chậm hơn: phần mã hóa PNG đo riêng (cùng một hàm ở hai lượt) lệch so với r1 từ −4 % tới +15 % (5 trên 6 tổ hợp chậm hơn).

| Ảnh | Thao tác | Trung vị r1 → r3 | p95 r1 → r3 | Min / Max r3 | Lệch Qt lớn nhất r1 → r3 | RAM tăng đỉnh r1 → r3 (MiB) |
|---|---|---|---|---|---|---|
| 1920×1080 gradient | `read` → `OK` | 111,7 → 144,3 | 131,6 → 153,5 | 137,3 / 153,5 | 11,9 → 12,0 | 8 → 9 |
| 1920×1080 gradient | `write` | 20,8 → 21,5 | 28,2 → 23,1 | 20,2 / 23,1 | 11,2 → 10,7 | 8 → 8 |
| 1920×1080 nhiễu | `read` → `OK` | 478,0 → 625,9 | 534,5 → 672,3 | 591,8 / 672,3 | 12,2 → 13,4 | 28 → 29 |
| 1920×1080 nhiễu | `write` | 51,1 → 55,2 | 58,7 → 89,2 | 48,8 / 89,2 | 12,1 → 11,4 | 15 → 15 |
| 3840×2160 gradient | `read` → `OK` | 354,2 → 442,8 | 371,4 → 465,8 | 412,9 / 465,8 | 18,3 → 17,8 | 33 → 33 |
| 3840×2160 gradient | `write` | 69,7 → 80,5 | 70,5 → 91,8 | 72,6 / 91,8 | 13,3 → 13,6 | 32 → 32 |
| 3840×2160 nhiễu | `read` → `TOO_LARGE` | **1880,3 → 345,9** | **1938,1 → 379,1** | 317,9 / 379,1 | 21,0 → 18,5 | **114 → 36** |
| 3840×2160 nhiễu | `write` (*) | 196,8 → 226,9 | 224,3 → 251,9 | 208,1 / 251,9 | 14,7 → 15,1 | 59 → 59 |
| 8192×8192 gradient | `read` → `OK` | 3020,0 → 3399,4 | 3250,8 → 3812,8 | 3260,5 / 3812,8 | 92,3 → 116,7 | 267 → 267 |
| 8192×8192 gradient | `write` | 956,9 → 1118,8 | 1058,9 → 1170,3 | 1015,7 / 1170,3 | 35,2 → 50,3 | 260 → 260 |
| 8192×8192 nhiễu | `read` → `TOO_LARGE` | **18375,1 → 648,2** | **24306,5 → 737,4** | 593,9 / 737,4 | **325,0 → 111,6** | **914 → 260** |
| 8192×8192 nhiễu | `write` (*) | 1982,1 → 1828,7 | 2116,1 → 2282,0 | 1715,3 / 2282,0 | 69,4 → 66,1 | 476 → 476 |

(*) như bảng r1: chỉ là cận trên của thời gian giải mã. `write` không đổi mã giữa hai lượt; chênh lệch ở các dòng `write` là do tải nền.

**Giá của bước kiểm sơ bộ** (ms, gọi thẳng `prescreen` trên ảnh `RGBA8888`, trung vị 3 lần, cùng lúc pytest chạy): 1920×1080 gradient 24,0, nhiễu 186,8 (chưa vượt mức, đi tiếp sang mã hóa PNG); 3840×2160 gradient 46,3, nhiễu 382,3 (dừng ở mức); 8192×8192 gradient 164,9, nhiễu 400,3 (dừng ở mức). Với ảnh `OK`, đây là thời gian cộng thêm vào `read`; phần chênh r1 → r3 còn lại của các ca `OK` khớp với mức chậm do tải nền nói trên.

**Kết luận r3**

- Ảnh khó nén vượt trần giờ được loại sớm: `TOO_LARGE` sau khoảng 0,35 s (3840×2160) và 0,65 s (8192×8192, max 0,74 s, trước là 16,7–24,3 s), nay ngắn hơn nhiều so với `CLIP_READ_TIMEOUT` (`app/clipboard.py`), nên không còn ca quá hạn để việc mã hóa chạy tiếp trong pool như ở kết luận r1. RAM tăng đỉnh của ca 8192² nhiễu giảm từ 914 xuống 260 MiB (chỉ còn bản ảnh sau `convertTo`), lệch thread Qt lớn nhất từ 325 xuống 111,6 ms (không còn bước chép PNG 219 MiB).
- Ảnh `OK` trả thêm giá kiểm sơ bộ: khoảng 24–47 ms với ảnh dễ nén 1920×1080 và 3840×2160, 165 ms với 8192² dễ nén, khoảng 190 ms với 1920×1080 nhiễu (ca xấu nhất của ảnh vẫn vừa trần: trên ảnh này phải nén hết rồi mới mã hóa PNG).
- Phần backend thêm vào một clip ảnh trong trần (p95 `read` + `write`, r3, có tải nền): 1920×1080 khoảng 0,18 s (gradient) và 0,76 s (nhiễu); 3840×2160 gradient khoảng 0,56 s; **8192×8192 gradient khoảng 5,0 s** (r1: 4,3 s), vẫn vượt ngưỡng ảnh của mvp N6 ngay cả khi mạng tức thì; phần tốn nhất vẫn là mã hóa PNG ở máy gửi (3,39 s trung vị khi đo riêng ở r3), rồi giải mã ở máy nhận (0,87 s).
- So với mvp N6: như r1, **KHÔNG ĐẠT** ở ca 8192² dễ nén (phần backend, cận dưới, vẫn vượt ngưỡng ảnh trên máy này); các ca còn lại **CHƯA ĐỦ DỮ LIỆU** (D6). Nên đo lại các ca `OK` khi máy rảnh để tách hẳn phần tải nền.

### 9.5. Việc còn lại

- **Wi-Fi 5 giữa hai máy thật: chưa đo** (D6, [ke_hoach.md](ke_hoach.md) mục 5.4). Cần máy thật thứ hai và điểm phát Wi-Fi đúng loại mvp N6 nêu; mỗi đầu chỉ dùng đồng hồ của chính nó (ví dụ đo khứ hồi A → B → A trên đồng hồ A), không so đồng hồ hai máy.
- **M4 trên clipboard thật của Windows** (nền `windows`: thời gian `clipboard.image()` chuyển DIB trên thread Qt, `setImage`, lệch Qt): **chưa đo**; cần một phiên máy thật mà người dùng chấp nhận clipboard bị ghi đè trong lúc đo (mục 9.4 chỉ đo offscreen).
- M1–M4 trên Linux và macOS: chưa đo.

### 9.6. Cách đo lại

Script `n6_bench.py` và `summ.py` nằm ngoài repo (không commit); thư mục cấu hình node tạo trong `cfg\` cạnh script và tự xóa. Chạy từ thư mục gốc của checkout cần đo, bằng `python.exe` của `.venv`, `PYTHONPATH` trỏ `src` (kiểm `teleport_file` trong file kết quả):

```powershell
$env:PYTHONPATH = 'src'; $env:PYTHONIOENCODING = 'utf-8'
& $PY <scratchpad>\n6_bench.py --mode m1 --size 1024 --repeat 200 --out m1-1k.json
& $PY <scratchpad>\n6_bench.py --mode m1 --size 1048576 --repeat 200 --out m1-1m.json
& $PY <scratchpad>\n6_bench.py --mode m2 --repeat 20 --out m2.json          # PNG 10 MiB
& $PY <scratchpad>\n6_bench.py --mode m3 --count 1000 --interval 0.25 --out m3.json
& $PY <scratchpad>\n6_bench.py --mode m3 --count 1000 --interval 0.2 --out m3-5hz.json
python <scratchpad>\summ.py m1-1k.json m1-1m.json m2.json m3.json m3-5hz.json
```

Tham số khác: `--gap` (nghỉ giữa hai lần ở M1/M2, mặc định 0,3 s), `--warmup` (mặc định 3), `--timeout` (mặc định 15 s mỗi lần).

**M4** (mục 9.4): `m4_bench.py`, `run_all.ps1`, `summ_m4.py`, `lag_steps.py`, cũng ngoài repo. `m4_bench.py` tự dừng nếu `QT_QPA_PLATFORM` không phải `offscreen`, có hạn cho từng thao tác (`--timeout`, mặc định 60 s) và cho cả lượt (`--budget`, mặc định 600 s), cuối cùng xóa clipboard của Qt và ghi một file JSON (có `teleport_file`, `qpa`). Chạy từ thư mục gốc của checkout cần đo (khoảng 10 phút, phần lớn là ca 8192² nhiễu):

```powershell
& <scratchpad>\run_all.ps1 -Py $PY -Repeat 12 -Tag r1      # lượt sau kiểm sơ bộ: -Tag r3; 3 cỡ × 2 loại ảnh, mỗi tổ hợp một tiến trình, đặt sẵn PYTHONPATH=src và QT_QPA_PLATFORM=offscreen
& $PY <scratchpad>\summ_m4.py <scratchpad>\r1-*.json         # bảng kết quả và phân rã từng bước
$env:PYTHONPATH = 'src'; $env:QT_QPA_PLATFORM = 'offscreen'
& $PY <scratchpad>\lag_steps.py --w 8192 --h 8192 --kind noise --repeat 3   # lệch Qt theo từng bước
```
