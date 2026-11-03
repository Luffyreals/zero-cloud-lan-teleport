# Kế hoạch dự án — Zero-Cloud LAN Teleport v1.0

> **Vai trò:** kế hoạch kỹ thuật — làm thế nào, bằng công nghệ gì, theo thứ tự nào, đang tới đâu.
> **Nguồn duy nhất cho:** các quyết định đã chốt, thiết kế kỹ thuật, lộ trình và **trạng thái giai đoạn**, danh sách phép đo của đợt đo trên thiết bị thật (mục 5.4), quy trình, kiểm thử, rủi ro kỹ thuật, việc cần chốt.
> **Không chứa:** phạm vi, tính năng, tiêu chí chấp nhận và con số chất lượng → [mvp.md](mvp.md) (tham chiếu theo mã F1–F12, N1–N12). Ý tưởng, nguyên tắc và tầm nhìn → [y_tuong.md](y_tuong.md). Thuật ngữ, quy ước và bản đồ tài liệu → [README.md](README.md).
> **Bản chính thức về kỹ thuật:** đặc tả giao thức [protocol.md](protocol.md) và trạng thái từng module [architecture.md](architecture.md); khi lệch nhau thì hai file đó đúng.
> **Cập nhật:** 2026-11-03

---

## 1. Các quyết định đã chốt

| Câu hỏi | Quyết định |
|---|---|
| Loại dự án | **Sản phẩm phát hành cho người dùng thật**: người dùng phổ thông tải bộ cài về là dùng được; phát hành theo phiên bản; có CI, kiểm thử tự động, tài liệu người dùng, chính sách bảo mật và quyền riêng tư |
| Nền tảng v1.0 | **Desktop ↔ desktop**: Windows là chính; macOS và Linux được CI build/test và có bộ cài |
| Ngôn ngữ chính | **Python 3.12+** cho toàn bộ ứng dụng |
| Ngôn ngữ bổ trợ | **C/C++** và **Java** cho công cụ phụ trợ (mục 4.2), không nằm trên đường găng của v1.0 |
| Repo | **Public** trên GitHub `Nha-Cong-Dong/zero-cloud-lan-teleport`: mã nguồn và mọi tài liệu trong `docs/` đều công khai |
| Giấy phép | **GPL-3.0-or-later** (file `LICENSE`). Mọi bản phân phối đã sửa đổi phải mở mã theo GPL. Thư viện chạy/đóng gói phải tương thích GPLv3: chỉ dùng MIT/MIT-0/BSD/Apache-2.0/PSF-2.0/LGPL; LGPL chỉ cho gói đóng vào dạng file riêng người dùng thay được, không cho thành phần liên kết tĩnh; thành phần lồng bên trong một gói đã duyệt (liệt kê trong SBOM của gói, hoặc thư viện C đi kèm CPython) được dùng thêm các giấy phép dễ dãi tương thích GPLv3: ISC, Zlib, 0BSD, Unicode-3.0, Unicode-DFS-2016, Apache-2.0 WITH LLVM-exception, bzip2-1.0.6, public domain, giấy phép chỉ đòi giữ thông báo của `dtoa.c` (David M. Gay, trong lõi CPython); ngoại lệ là PyInstaller (GPL kèm bootloader exception). DLL runtime MSVC (`vcruntime140*.dll`) đi kèm runtime Python thuộc ngoại lệ System Library của GPLv3. Qt và PySide6 (bản GUI) dùng theo nhánh LGPL-3.0, đóng `--onedir` để DLL Qt là file riêng người dùng thay được; thành phần lồng trong DLL Qt và shiboken6 (theo `qt_attribution.json` của đúng phiên bản Qt; qtsvg không có file đó nên theo `REUSE.toml`) được dùng thêm: CC0-1.0, FTL (FreeType, kèm câu ghi công FTL đòi), Libpng và libpng-2.0, MIT-open-group, X11, HPND, HPND-sell-variant, Imlib2, MPL-2.0 (chỉ dữ liệu Public Suffix List), Python-2.0 (mã CPython chép vào shiboken6), BSD-3-Clause kèm ngoại lệ của PCRE2, giấy phép ICC của hồ sơ màu sRGB, giấy phép header Wintab, SHA-1 public domain; DLL runtime MSVC đi kèm PySide6 (`msvcp140*.dll`, `vcruntime140*.dll`) cũng theo ngoại lệ System Library. Tài sản không phải mã của giao diện (icon, font, mục 4.1) chép nguyên dạng từ dự án gốc ở một commit ghim: MIT của icon là tương thích; OFL-1.1 chỉ cho file font đóng nguyên dạng file dữ liệu riêng kèm `OFL.txt` (tác phẩm gộp, không phải “tương thích GPLv3”), không dùng cho mã hay thành phần nào khác. Universal CRT (`ucrtbase.dll`, `api-ms-win-*.dll`) không được đóng vào: đó là thành phần có sẵn của Windows 10 trở lên (nền tảng tối thiểu ở mvp N10), không phải file của bên thứ ba. Bộ cài Windows dùng Inno Setup (bản ghim và SHA-256 trong `.github/workflows/build-gui.yml`): stub cài đặt và trình gỡ `unins000.exe` mà nó đặt vào thư mục cài theo giấy phép Inno Setup, kiểu zlib (dùng, sửa, phân phối lại tự do, kể cả thương mại; bản nhị phân phải giữ nguyên thông báo bản quyền và địa chỉ web sẵn có, ví dụ trong hộp About; bản sửa đổi phải ghi rõ là đã sửa), là chương trình riêng gộp cùng Teleport, không liên kết với mã Teleport; bản dịch `Vietnamese.isl` (thư mục `Files/Languages/Unofficial/` của repo `jrsoftware/issrc`, đúng tag của bản ghim, chép nguyên văn) không có dòng giấy phép riêng, là đóng góp trong repo đó nên được coi (suy luận, không có văn bản riêng xác nhận) theo `license.txt` của repo; văn bản giấy phép nằm ở `packaging/inno/licenses/` và được cài vào `{app}\licenses\`. Công cụ chỉ dùng khi phát triển được phép khác (ví dụ `hypothesis` MPL-2.0) |
| Ưu tiên | **Hoàn thành MVP v1.0 trước** (desktop ↔ desktop); điện thoại và các việc “Sau v1.0” chưa làm |
| Nguồn lực | Làm một mình |
| Thời hạn | Không có hạn cố định → kiểm soát bằng các bản phát hành (mục 5), mốc tham khảo ~15 tuần tới v1.0 |
| Hackathon | Demo khoảng 08/11/2026, phạm vi [mvp.md](mvp.md) mục 4.1, lịch mục 5.5 |
| Ngôn ngữ giao diện | Tiếng Việt và English |
| Tên sản phẩm | **Zero-Cloud LAN Teleport** (dạng viết liền `zero-cloud-lan-teleport`, đã dùng cho repo và tên gói phân phối); tên ngắn hiển thị trong app và bộ cài là **ZCL Teleport** (`APP_NAME` ở `src/teleport/ui/texts.py`), còn định danh kỹ thuật (gói `teleport`, lệnh `teleport`, `Teleport.exe`, thư mục cấu hình và thư mục nhận) giữ “Teleport” để không mất dữ liệu cũ; biểu tượng là logo vẽ ở `src/teleport/ui/logo.py`. Chốt 01/11/2026 |

---

## 2. Khác biệt so với ý tưởng ban đầu

**Python có làm được không? Có.** Những phần nặng (mã hóa TLS, băm SHA-256, ghi đĩa) đều chạy bằng code C bên trong Python (OpenSSL, `hashlib`), nên tốc độ vẫn đạt mức của mạng Wi-Fi/LAN thông thường. Đổi lại cần điều chỉnh vài chỗ so với bản ý tưởng đầu tiên; [y_tuong.md](y_tuong.md) hiện hành đã theo các điều chỉnh này:

| Hạng mục | Ý tưởng ban đầu | Kế hoạch | Lý do |
|---|---|---|---|
| Kênh truyền | WebRTC DataChannel | **TCP + TLS 1.3** (`asyncio` + `ssl` có sẵn) | Trong LAN không cần NAT traversal. Thư viện WebRTC (`aiortc`) và QUIC (`aioquic`) cho Python viết bằng Python thuần nên chậm; TCP + TLS dùng OpenSSL nên nhanh và dễ bảo trì hơn nhiều. |
| Backpressure | Theo dõi bộ đệm gửi | `await writer.drain()` + hàng đợi có giới hạn | Cơ chế có sẵn của `asyncio`: bộ đệm vượt ngưỡng thì `drain()` tự chờ. Kết hợp với cửa sổ TCP, đây chính là backpressure đầu-cuối. |
| Mã hóa | DTLS / AES-GCM | **TLS 1.3** + ghim chứng chỉ sau ghép đôi | TLS 1.3 đã dùng AES-GCM / ChaCha20 bên trong. Rủi ro thật là MITM lúc ghép đôi → xử lý bằng mã xác minh 6 số có nonce cam kết. |
| Gói tin | Header 57 byte mỗi mảnh, kèm hash | Message điều khiển (JSON) + **khung dữ liệu nhị phân** gọn | Hash SHA-256 32 byte nằm trong header của chính khối (mục 3.4); TCP/TLS đã chống hỏng dữ liệu trên đường truyền. |
| Kích thước mảnh | 64KB hoặc 256KB | **Khối 1 MiB** | Khối lớn giảm số hash, kích thước bitfield và chi phí Python mỗi khối; RAM vẫn chỉ giữ ~10 khối. |
| Giao diện | Web / app nhẹ | **PySide6 (Qt)** | Kéo thả file cho ra đường dẫn thật (đọc thẳng từ đĩa), vẽ radar dễ, `QClipboard` theo dõi clipboard sẵn, giao diện native trên cả 3 hệ điều hành. |
| Nền tảng | Laptop ↔ điện thoại hoặc laptop ↔ laptop | **Desktop ↔ desktop** ở v1.0; điện thoại để sau v1.0 | Làm một mình; app điện thoại là một sản phẩm riêng, dùng lại cùng giao thức. |
| Ghép đôi | Chỉ nhắc cho clipboard | **Bắt buộc ghép đôi** cho cả file lẫn clipboard; có dự phòng nhập IP thủ công | Chống giả mạo thiết bị và chống máy lạ gửi rác trên Wi-Fi chung. |
| RAM | < 100MB tuyệt đối | **RAM tăng thêm khi truyền nằm trong ngưỡng mvp N3 và không tăng theo kích thước file** | Riêng Python + Qt đã chiếm khoảng 60–90MB lúc khởi động. Điều cần đảm bảo là bộ nhớ không phình ra khi truyền file 10GB. |

---

## 3. Thiết kế kỹ thuật

```
┌────────────────────────── App Teleport (mỗi máy) ──────────────────────────┐
│  ui (PySide6)   radar, lượt truyền, ghép đôi, khay  │  cli   lệnh `teleport` │
│                 ▲ Qt signals (NodeHost: node chạy ở thread asyncio riêng)  │
│  app      Node · PairingService · TransferManager · ClipboardSync          │
│  net      tls (TLS 1.3 + mTLS) · stream · discovery (zeroconf) · connection │
│  trust    identity (khóa + chứng chỉ tự ký) · store (thiết bị tin cậy)     │
│  core     framing · messages · pairing_code · blocks · merkle · bitfield · │
│           transfer (máy trạng thái gửi/nhận, nối lại) — sans-IO            │
└─────────────────────────────────────────────────────────────────────────────┘
               ▲  TLS 1.3, mTLS: chỉ thiết bị đã ghép đôi  ▼
                          App Teleport trên máy khác
```

- Phân tầng `core ← trust ← net ← app ← ui / cli`, được kiểm tra tự động trong repo. Logic truyền file và nối lại nằm ở `core` dưới dạng máy trạng thái thuần (sự kiện vào, hành động ra); `net` chỉ đọc/ghi socket.
- Mô hình tiến trình: mỗi thư mục cấu hình một node. Tới `v0.2`, mỗi lần chạy CLI là một node. Từ `v0.3`, giao diện chạy node trong một thread riêng của tiến trình giao diện; CLI và giao diện cùng thư mục cấu hình loại trừ nhau qua `node.lock`, còn IPC CLI↔giao diện hoãn lại ([architecture.md](architecture.md) mục 2, 5).
- Mô tả chính thức và trạng thái từng module: [architecture.md](architecture.md).

### 3.1. Khám phá, kết nối & ghép đôi
*(mvp F2, F3)*
- **Một cổng TCP** cho mọi kết nối (mặc định 47474; bận thì lấy cổng khác và quảng bá qua mDNS). Một cổng thì rule tường lửa của bộ cài, nhập IP thủ công và mDNS đều đơn giản. Ba loại kết nối trên cùng cổng, client khai báo loại bằng message đầu tiên sau `hello`: ghép đôi (`pair_request`, client không gửi chứng chỉ), điều khiển (`control_open`) và dữ liệu (`data_open`), hai loại sau cần chứng chỉ đã tin cậy — `protocol.md` mục 2.
- Thư viện `zeroconf` quảng bá dịch vụ `_teleport._tcp.local.` với thuộc tính `id`, `name`, `os`, `proto`; không quảng bá fingerprint. Mọi bản ghi có TTL ngắn thay cho mặc định 75 phút của mDNS, và bên nhận tự resolve lại theo chu kỳ (zeroconf giữ PTR nhận được rất lâu), để máy mất mạng đột ngột biến mất khỏi radar trong thời hạn mvp N1 (`protocol.md` mục 8). Tên instance là `device_id`; TXT `name` được cắt ≤ 200 byte (`protocol.md` mục 8). Chỉ dùng IPv4, bỏ card ảo; client thử song song mọi địa chỉ được quảng bá khi mở kết nối ghép đôi hoặc điều khiển (`protocol.md` mục 2.1, 8). Dự phòng: nhập IP thủ công (`ip` hoặc `ip:cổng`).
- **Danh tính:** mỗi máy có khóa ECDSA P-256 và chứng chỉ X.509 tự ký; fingerprint = SHA-256 của chứng chỉ (DER). Tên thiết bị chỉ để hiển thị. Danh tính gắn với thư mục cấu hình: xóa thư mục cấu hình (cài lại sạch) là một thiết bị mới (`protocol.md` mục 1, 7).
- **Ghép đôi lần đầu** (kiểu *numeric comparison* của Bluetooth): bên khởi xướng gửi chứng chỉ, bên trả lời gửi **cam kết** cho nonce của mình, bên khởi xướng gửi nonce kèm **chữ ký** bằng khóa danh tính (chứng minh nó giữ khóa riêng của chứng chỉ vừa gửi, vì chứng chỉ thì ai cũng lấy được), bên trả lời kiểm chữ ký, hiện mã rồi mới lộ nonce. Bên trả lời không cần ký: bắt tay TLS đã chứng minh nó giữ khóa riêng. Bên trả lời là bên cam kết vì nó là máy đang chờ ghép đôi: kẻ đứng giữa gọi tới nó không biết trước được mã, nên mỗi lần thử đều làm nó hiện mã. Mã 6 số tính từ hai fingerprint **và hai nonce**. Nếu mã chỉ tính từ hai fingerprint, kẻ đứng giữa có thể sinh khóa offline tới khi ra mã trùng; có nonce cam kết thì mỗi lần thử chỉ trúng với xác suất 10⁻⁶. Công thức, luồng message `pair_*`, chống làm phiền và test vector: `protocol.md` mục 5.
- Luồng ghép đôi là **máy trạng thái sans-IO** ở `core/pairing.py` (sự kiện vào: message tới, người dùng xác nhận/từ chối, hết giờ; hành động ra: gửi message, hiện mã, lưu thiết bị, đóng). `app/pairing.py` chỉ sinh nonce, đưa vào hàm ký/kiểm chữ ký của `trust`, và nối máy trạng thái với kết nối thật. Nhờ vậy test được bằng `hypothesis` mọi thứ tự message, message trùng, message sai lúc.
- Người dùng thấy mã trùng thì bấm “Xác nhận” **ở cả hai máy** (hết giờ: mvp F3) → mỗi máy lưu chứng chỉ và fingerprint của máy kia vào `trusted.json`. Những lần sau, TLS chỉ chấp nhận chứng chỉ đã lưu. Có thể **hủy ghép đôi** bất cứ lúc nào, có hiệu lực ngay (`protocol.md` mục 7).
- **Xác thực hai chiều:** module `ssl` của Python không cho tự viết hàm kiểm tra chứng chỉ phía server. Phương án: nạp chứng chỉ của các thiết bị tin cậy làm trust anchor cho `SSLContext` của server, chế độ `CERT_OPTIONAL`; vì vậy chứng chỉ có dấu hiệu CA bị từ chối. Client gửi chứng chỉ lạ bị từ chối ngay khi bắt tay; client không gửi chứng chỉ chỉ được ghép đôi, xác thực ở tầng ứng dụng bằng mã 6 số. Đã kiểm chứng bằng test (`tests/net/test_tls.py`).
- `SSLContext` không gỡ được trust anchor đã nạp, nên mỗi lần danh sách tin cậy đổi (ghép đôi, hủy ghép đôi) node tạo context mới. Listener nhận **TCP trần** và mỗi kết nối gọi `start_tls` với context **hiện tại**, nên đổi danh sách tin cậy chỉ là thay context, không mở lại listener; kết nối đã bắt tay bằng context cũ được kiểm lại fingerprint lúc nhận `control_open`. Node đóng kết nối đang mở với máy vừa bị hủy. Không đổi context giữa chừng bằng `sni_callback`. Server tắt session ticket (`num_tickets = 0`, đã có test): nếu không, máy đã bị hủy ghép đôi dùng lại session cũ thì bỏ qua được bước kiểm chứng chỉ (đã kiểm chứng bằng test trong `tests/net/test_tls.py`).
- **Kết nối điều khiển:** mỗi cặp thiết bị tin cậy đang trực tuyến giữ đúng một kết nối, mở sẵn; cả hai bên đều có thể chủ động kết nối. Kết nối mới thay kết nối cũ, trừ khi hai bên gọi nhau cùng lúc (cách nhau dưới ngưỡng ở `protocol.md` mục 6.1) thì giữ kết nối do bên có `device_id` nhỏ hơn mở; hai kết nối do cùng một bên mở thì kết nối mới thay. Kết nối dữ liệu đi **cùng chiều** với kết nối điều khiển, nên tường lửa chặn một chiều vẫn truyền được file. Có keepalive `ping`/`pong` để phát hiện mất kết nối (`protocol.md` mục 2.3, 4.1, 6.1).
- Lỗi thường gặp cần phát hiện và báo rõ (mvp mục 8): Windows Firewall chặn cổng; Wi-Fi bật **cô lập thiết bị** (thấy nhau qua mDNS nhưng không kết nối được); macOS từ chối quyền Local Network. Nhìn từ máy gửi, tường lửa chặn và cô lập thiết bị giống hệt nhau; phân biệt bằng cách cho máy nhận tự kiểm (Windows: hồ sơ mạng đang là Public hay Private và rule của app có bật không) rồi hiện hướng dẫn trên chính máy đó.

### 3.2. Truyền file & backpressure
*(mvp F4, F5, N3)*
- **Khối:** 1 MiB, là đơn vị băm, nối lại và ghi bitfield. File 10 GiB = 10 240 khối, bitfield 1,25 KiB.
- **Bên gửi:** băm từng khối và gửi hash **ngay trong header của khung khối** (`protocol.md` mục 4.2):
  ```python
  while block := f.read(BLOCK_SIZE):  # chỉ giữ 1 khối trong RAM
      digest = hashlib.sha256(block).digest()
      writer.write(BLOCK_HEADER.pack(0x02, idx, len(block), digest) + block)
      await writer.drain()  # ← backpressure: chờ khi bộ đệm đầy
  ```
- **Bên nhận:** đọc từng khung → băm lại và so với hash trong header → đẩy vào `asyncio.Queue(maxsize=8)` → luồng ghi đĩa (`DiskExecutor` của node, [architecture.md](architecture.md) mục 5) ghi vào `.part` đúng vị trí `idx × BLOCK_SIZE`, cứ 16 khối thì `fsync` và cập nhật trạng thái nối lại (mục 3.4). Ổ đĩa chậm → hàng đợi đầy → ngừng đọc socket → TCP báo bên gửi chậm lại. Kết quả: RAM tối đa khoảng 8–10 khối, bất kể file lớn cỡ nào.
- **Giới hạn tốc độ gửi** (tùy chọn trong cài đặt): token bucket áp theo từng đoạn 64 KiB, để dòng byte không ngưng lâu tới mức bên nhận tưởng mất kết nối.
- Mỗi lượt truyền chỉ có một kết nối dữ liệu, các file được gửi lần lượt, và mỗi chiều giữa hai máy chỉ chạy một lượt truyền (lượt khác xếp hàng), nên RAM không tăng theo số file hay số lượt truyền.
- **Hoàn tất:** đọc lại `.part` từ đĩa và so từng khối → so Merkle root → `fsync` → đổi tên không ghi đè (mục 3.4).
- Mô hình tiến trình tới `v0.2`: mỗi lệnh CLI là một node giữ `node.lock`, nên trên cùng một thư mục cấu hình không chạy được `teleport receive` và `teleport send` cùng lúc, và `teleport send` phải chạy tới khi lượt xong; mất kết nối thì nó chờ nối lại (thời hạn: Giai đoạn 2 ở mục 5.2, từ Giai đoạn 3 theo `protocol.md` mục 6.2). Giới hạn này hết ở `v0.3` khi giao diện giữ node (`architecture.md` mục 2).

### 3.3. An toàn khi nhận
*(mvp F4, N8 — bắt buộc, không cắt khi trễ tiến độ)*
- Làm sạch tên file trong `offer` để chặn ghi ra ngoài thư mục nhận (path traversal) và tên mà hệ điều hành xử lý bất ngờ. Chỉ giữ phần tên cuối (bỏ mọi `/` và `\`), rồi:
  - loại `..`, đường dẫn tuyệt đối, ký tự ổ đĩa (`C:`), ký tự cấm trên Windows (`<>:"/\|?*`, mã 0–31) — `:` còn mở alternate data stream trên NTFS;
  - bỏ dấu chấm và khoảng trắng ở cuối tên (Windows tự cắt, có thể làm hai tên khác nhau thành một);
  - tên thiết bị đặc biệt của Windows (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`, `LPT1`–`LPT9`, kể cả khi có đuôi như `NUL.txt`) được đổi tên;
  - ký tự điều khiển, ký tự vô hình và ký tự đổi hướng chữ như ở tên thiết bị (`protocol.md` mục 3.3);
  - chuẩn hóa NFC (macOS lưu NFD), giới hạn 255 byte UTF-8 và đường dẫn đầy đủ không vượt giới hạn của hệ điều hành;
  - tên rỗng sau khi làm sạch → `file`.
- Giới hạn độ dài đường dẫn theo từng hệ điều hành, và tên dự phòng khi hệ file từ chối tên: [architecture.md](architecture.md) mục 4 “Thư mục nhận”.
- Kiểm tra dung lượng trống trước khi nhận; không đủ thì tự trả `reject{no_space, needed, available}`.
- Trùng tên (với file đã có, hoặc giữa hai file trong cùng `offer`, không phân biệt hoa thường) thì tự đặt `ten (1).ext`, không bao giờ ghi đè; tên kèm hậu tố ` (n)` vẫn phải nằm trong giới hạn độ dài ở trên, nên phần tên trước đuôi file được cắt bớt khi cần. Bước đổi tên cuối cùng **không bao giờ ghi đè** và chạy được trên mọi hệ file (kể cả ổ USB FAT/exFAT): ghi tên đích vào trạng thái nối lại, tạo file đích rỗng bằng `O_CREAT | O_EXCL` để giữ chỗ tên (đã có thì thử ` (1)`, ` (2)`…), ghi vào trạng thái nối lại rằng đã giữ được chỗ, rồi `os.replace` file tạm đè lên chính file giữ chỗ đó (thử lại khi Windows báo `PermissionError` vì antivirus đang mở file). Bị ngắt giữa chừng thì chỉ dùng lại file giữ chỗ mà trạng thái nối lại chứng minh là của mình; file khác mang tên đó không bao giờ bị xóa hay ghi đè (`protocol.md` mục 4.4). Không dùng `os.rename` trần (trên POSIX nó ghi đè không báo) hay `os.link` (FAT/exFAT không hỗ trợ).
- File tạm **không** nằm cạnh file thật mà trong thư mục ẩn `<thư mục nhận>/.teleport/<transfer_id>/`, để tên file nhận được (ví dụ `x.mp4.part.state`) không bao giờ đụng file tạm của lượt truyền khác.
- Luôn hỏi người nhận chấp nhận, trừ khi họ đã tắt “Hỏi trước khi nhận” cho thiết bị đó.
- Mọi message nhận từ máy khác đều không được tin: sai một trường là cả message bị từ chối; có giới hạn kích thước, thời gian chờ và fuzz test.

### 3.4. Toàn vẹn & nối lại
*(mvp F6, F7, N4, N5)*
- Bên gửi băm từng khối **trong khi gửi** và gửi hash trong header của chính khối đó; cuối file gửi `complete{merkle_root}`. Nhờ vậy không phải băm cả file 10 GiB trước khi bắt đầu, và hash không bao giờ tới sau dữ liệu.
- Bên nhận băm lại khối khi nhận và so ngay. Cứ 16 khối: `fsync` file `.part` → nối một bản ghi đánh dấu các khối đó, kèm hash, vào nhật ký `.state` → `fsync` `.state` (bitfield chỉ chứa khối **đã khớp hash và đã nằm trên đĩa**; `protocol.md` mục 4.3). Mỗi 16 MiB một lần `fsync` `.part` và một lần `fsync` `.state`, chi phí nhỏ so với thời gian truyền (đo ở Giai đoạn 2; nếu ảnh hưởng N2 thì nới chu kỳ và tính lại N4). Với file nhỏ, chi phí tính theo từng file: `transfer.json`, header `.state`, `TARGET` và `RESERVED` của mỗi file đều được `fsync`, nên nhận nhiều file nhỏ chậm hơn rõ ([benchmark.md](benchmark.md) mục 4.9).
- **Vì sao `.state` là nhật ký chỉ ghi thêm:** thiết kế cũ ghi nguyên tử lại *toàn bộ* trạng thái ở mỗi lần đánh dấu (manifest, bitfield, hash mọi khối đã đánh dấu), nên tổng byte ghi tăng theo bình phương số khối, cỡ 2N² byte với N khối: file 100 GiB tốn khoảng 20 GiB ghi đĩa chỉ cho trạng thái. Nhật ký chỉ nối thêm bản ghi của các khối vừa đánh dấu, nên tổng byte ghi tỉ lệ thuận với số khối; manifest chỉ nằm ở `transfer.json`. Định dạng, cách đọc lại và gộp: [architecture.md](architecture.md) mục 4.
- **Vì sao không gửi hash theo lô trên kênh điều khiển** (thiết kế cũ): kết nối điều khiển và kết nối dữ liệu không có thứ tự với nhau, nên hash có thể tới sau dữ liệu; bên nhận phải dừng đọc ở mỗi ranh giới lô để chờ hash, và giới hạn gửi lại phụ thuộc vào thứ tự giữa hai kết nối. Hash nằm trong header khung (32 byte cho mỗi 1 MiB, ~0,003%) xóa bỏ cả hai vấn đề mà không tốn thêm RAM hay đọc file hai lần.
- **Giới hạn dữ liệu gửi lại:** khối đã nhận nhưng chưa được đánh dấu có bit = 0 nên sẽ được gửi lại. Số khối đó ≤ 16 + 8 (hàng đợi) + 1, cộng bộ đệm socket (cách chặn: `protocol.md` mục 4.3, chốt ở Giai đoạn 3 theo số đo). “Phần chưa nhận” tính theo bitfield của bên nhận (`protocol.md` mục 4.3).
- **Kiểm tra cuối:** khi có `complete` và đủ mọi bit, bên nhận **đọc lại toàn bộ `.part` từ đĩa** và so từng khối với hash đã lưu, rồi mới so Merkle root. Không có bước này thì byte bị sửa trong `.part` lúc tạm dừng (mvp F7) sẽ lọt qua, vì bitfield và hash đã lưu vẫn nói khối đó đúng. Khối sai → xóa bit, gửi `resume` → bên gửi gửi lại đúng khối đó. Quá 3 lần vẫn sai (ví dụ ổ hỏng) → `cancel{error}`. Bước này là trạng thái “đang kiểm tra” ở mvp F5; tốn một lần đọc file ở tốc độ đĩa.
- **Một cơ chế gửi lại duy nhất:** `resume{bitfield}` (các khối bên nhận đã có) gửi được lúc nào cũng được: khi nối lại, khi kết nối dữ liệu đóng mà còn thiếu khối, khi lượt đọc lại thấy khối sai, và với bitfield toàn 0 khi Merkle root không khớp. Không cần message `corrupt` riêng. Mỗi `resume` có `seq`, và mỗi kết nối dữ liệu mang `resume_seq` của đúng `resume` nó phục vụ, nên `data_open` tới trước `resume` cũng không làm gửi sai khối.
- **Message điều khiển bị mất** (kết nối đứt hoặc bị thay đúng lúc `offer`, `complete`, `verified`, `cancel` đang trên đường) không làm treo lượt truyền: mọi message gửi lại được và nhận trùng không gây hại, và mỗi kết nối điều khiển mới mở đầu bằng một lượt đồng bộ lại (`protocol.md` mục 6.3).
- **Nối lại:** mất kết nối → tự thử lại (lịch và thời hạn: `protocol.md` mục 6.2) → bên nhận gửi `resume{bitfield}` → bên gửi chỉ gửi những khối có bit = 0 (`protocol.md` mục 6).
- File nguồn thay đổi (kích thước/mtime khác manifest), kiểm khi nối lại **và** trước khi gửi `complete` → bên gửi gửi `cancel{source_changed}`, báo người dùng.
- Tắt app gửi: v1.0 không lưu lượt truyền của bên gửi; khi nối lại, bên gửi trả `cancel{unknown_transfer}` và bên nhận dọn file tạm.
- File tạm bỏ dở thì tự dọn: lượt nhận dở của máy này hết hạn theo thời hạn nối lại (`protocol.md` mục 6.2), file tạm khác theo hạn của mvp F6 ([architecture.md](architecture.md) mục 4 “Dọn tạm”).
- **Merkle root:** tính từ danh sách hash các khối (lá) theo cây nhị phân; lẻ nút thì nút cuối được đẩy thẳng lên tầng trên (`protocol.md` mục 4.4).

### 3.5. Giao thức (tóm tắt)
Đặc tả chính thức: [protocol.md](protocol.md), có **số phiên bản** riêng, độc lập với phiên bản app (hiện là phiên bản 1; quy tắc tăng số: `protocol.md` mục 9). Bảng dưới chỉ là tóm tắt; khi lệch nhau thì `protocol.md` đúng. Mọi thay đổi định dạng trên dây phải sửa `protocol.md` trong cùng PR.

Mọi kết nối đi vào **một cổng**, bắt tay TLS 1.3, rồi hai bên gửi `hello`; khác phiên bản giao thức thì đóng kết nối kèm thông báo “hãy cập nhật app”. Có 3 loại kết nối:
- **Ghép đôi:** client không gửi chứng chỉ; chỉ có `pair_*`; message ≤ 16 KiB.
- **Điều khiển** (mTLS, một kết nối mở sẵn cho mỗi cặp máy): message `[4 byte độ dài][JSON UTF-8]`, tối đa 1 MiB. JSON dễ đọc và dễ debug; message điều khiển ít và nhỏ nên không ảnh hưởng tốc độ.
- **Dữ liệu** (mTLS, một kết nối cho mỗi lượt truyền, mở cùng chiều với kết nối điều khiển): sau `hello` là `data_open{transfer_id, file_index, resume_seq}`, rồi bên gửi file ghi các khung khối nhị phân.

| Message điều khiển (`type`) | Hướng | Nội dung |
|---|---|---|
| `hello` | ↔ | phiên bản giao thức, `device_id`, tên thiết bị, phiên bản app, hệ điều hành |
| `pair_request` / `pair_commit` / `pair_nonce` / `pair_reveal` / `pair_confirm` / `pair_abort` | ↔ | ghép đôi: chứng chỉ, cam kết của bên trả lời, hai nonce, chữ ký của bên khởi xướng (trong `pair_nonce`), xác nhận, lý do hủy — chỉ trên kết nối ghép đôi |
| `control_open` / `data_open` | client → server | mở đầu kết nối điều khiển / dữ liệu (`transfer_id`, `file_index`, `resume_seq`) |
| `offer` | gửi → nhận | `transfer_id`, danh sách file (tên, kích thước, mtime), `block_size` |
| `accept` / `reject` | nhận → gửi | nhận tất cả / lý do từ chối (danh sách lý do và trường kèm theo: `protocol.md` mục 3.3) |
| `resume` | nhận → gửi | `transfer_id`, `file_index`, `seq`, bitfield các khối đã có; gửi lúc nào cũng được (nối lại, gửi lại khối thiếu hoặc sai) |
| `complete` | gửi → nhận | `transfer_id`, `file_index`, `merkle_root` |
| `verified` | nhận → gửi | file đã kiểm tra xong và mang tên thật |
| `cancel` | ↔ | `transfer_id`, lý do (danh sách: `protocol.md` mục 3.3) |
| `clipboard` | ↔ | một mảnh của một clip: `clip_id`, `kind` (`text` / `image/png`), `sha256`, `total`, `index`, `count`, dữ liệu (văn bản hoặc base64); trường và luật: `protocol.md` mục 3.2, 3.3 |
| `ping` / `pong` | ↔ | giữ kết nối, phát hiện mất kết nối |

**Khung khối nhị phân** (rút gọn từ bảng gói tin trong bản ý tưởng ban đầu), đóng gói bằng `struct.pack("!BII32s", ...)`:

| Trường | Byte | Kiểu | Ghi chú |
|---|---|---|---|
| `type` | 1 | UInt8 | `0x02` = khối dữ liệu |
| `block_index` | 4 | UInt32 (BE) | Hỗ trợ tới 4 tỷ khối × 1 MiB |
| `length` | 4 | UInt32 (BE) | Đúng bằng độ dài khối; khối cuối có thể ngắn hơn 1 MiB |
| `sha256` | 32 | bytes | SHA-256 của `payload` |
| `payload` | biến thiên | bytes | Dữ liệu thô |

### 3.6. Đồng bộ clipboard
*(mvp F8, N6)*
- Dùng `QClipboard.dataChanged` (văn bản + ảnh), **chưa** polling: chỉ chuyển sang polling 500 ms khi đo trên máy thật thấy signal không đáng tin trên một hệ điều hành. Giới hạn đã biết, chưa thử máy thật: Wayland không báo `dataChanged` khi app không ở tiền cảnh (và hạn chế ghi), macOS có thể chỉ báo khi app đang được kích hoạt. Lõi làm việc qua giao diện `ClipboardBackend`; bản Qt do tầng `ui` cung cấp; điều phối (gộp các lần đổi, hàng gửi, hàng ghi, trần RAM) ở `teleport.app.clipboard` ([architecture.md](architecture.md) mục 5).
- Phần sans-IO (chia, ráp, chống vòng lặp, giới hạn tốc độ, lọc nhạy cảm) ở `teleport.core.clipboard`; hành vi và hợp đồng với `app`/`ui` ở docstring của module đó.
- **Chống vòng lặp** bằng fingerprint: văn bản là SHA-256 của văn bản đã chuẩn hóa như trên dây (`\r\n` thành `\n`, `protocol.md` mục 3.3), nên hệ điều hành đổi xuống dòng khi ghi clipboard không làm đổi fingerprint; bên nhận tính fingerprint từ văn bản đã ráp, không lấy `sha256` trên dây (bên gửi khác có thể không chuẩn hóa); ảnh là SHA-256 của **pixel** đã giải mã (kèm kích thước và định dạng pixel), không phải của byte PNG, vì mã hóa lại PNG ra byte khác. **Một** `LoopGuard` cho cả node nhớ các fingerprint vừa ghi từ máy khác (cả fingerprint đọc lại sau khi ghi); clipboard đổi thành nội dung trùng thì không gửi. Máy chỉ gửi nội dung do chính người dùng nó tạo ra, **không chuyển tiếp** clip nhận được: với 3 máy, máy thứ hai không gửi tiếp cho máy thứ ba clip mà máy thứ nhất đã gửi thẳng cho cả hai.
- Bật/tắt theo từng thiết bị đã ghép đôi, **mặc định tắt** (clipboard có thể chứa mật khẩu); ghép đôi lại cũng đặt về tắt. Không có message báo bật/tắt: mỗi máy chỉ gửi tới và nhận từ máy mình đã bật, nên clip chỉ đi khi **cả hai máy** cùng bật cho nhau ([protocol.md](protocol.md) mục 3.3; bật một chiều thì máy gửi tốn băng thông cho clip bị bỏ, chấp nhận để giữ nguyên dây). Không bật với máy nào đang kết nối thì clipboard máy này không bị đọc. “Tạm dừng nhận” bỏ cả clipboard gửi tới (vẫn gửi đi được).
- Bỏ qua nội dung được trình quản lý mật khẩu đánh dấu nhạy cảm. Windows: có định dạng `ExcludeClipboardContentFromMonitorProcessing`, hoặc `CanIncludeInClipboardHistory` / `CanUploadToCloudClipboard` mang DWORD bằng 0. macOS: `org.nspasteboard.ConcealedType`; Linux: `x-kde-passwordManagerHint`. So tên không phân biệt hoa thường, cả tên trần lẫn dạng `application/x-qt-…-mime;value="…"` của Qt. Không đọc được giá trị DWORD thì coi là nhạy cảm. Tên trên macOS/Linux chưa kiểm tay (Giai đoạn 5, phần giao diện).
- Văn bản và ảnh lớn được chia thành nhiều message nhỏ, nên một lần gửi clipboard không giữ kết nối điều khiển lâu và `ping`/`pong` vẫn chen vào được giữa các mảnh; khối dữ liệu file đi trên kết nối riêng. Cách chia, trần dung lượng và luật ráp: [protocol.md](protocol.md) mục 3.3.
- Rủi ro chấp nhận: lịch sử clipboard của Windows (Win+V) và clipboard đám mây lưu cả nội dung nhận từ máy khác (nội dung nhạy cảm thì vẫn không gửi); một máy đã ghép đôi và đã bật đồng bộ có thể gửi ảnh liên tục ở mức tối đa bên nhận chấp nhận, làm máy này giải mã và ghi ảnh liên tục: không thêm trần riêng; RAM chưa đo (sẽ ghi ở [benchmark.md](benchmark.md) mục 9.5). Máy giữ clip dở, bỏ dở clip hay dội mảnh đầu liên tục bị đẩy ra khỏi trần RAM chung khi máy khác cần chỗ ([architecture.md](architecture.md) mục 5, “Clipboard ở tầng app”); máy tin cậy vẫn có thể gửi clip thật liên tục ở mức tối đa như trên. Cách xử lý: tắt đồng bộ hay hủy ghép đôi với máy đó.

### 3.7. Quyền riêng tư & “Zero-Cloud”
*(mvp N9)*
- Không telemetry, không tài khoản, không gọi bất kỳ máy chủ nào ngoài LAN.
- Kiểm tra bản cập nhật (đọc GitHub Releases) là **tùy chọn, mặc định tắt**, và là kết nối Internet duy nhất app có thể tạo ra.
- Log chỉ lưu trên máy, không ghi nội dung file hay clipboard. Có nút “Xuất log” để người dùng tự gửi khi báo lỗi.
- **Theo dõi thiết bị qua nhiều mạng:** `device_id` cố định và tên thiết bị lộ cho mọi máy trong mạng (qua mDNS) và cho máy nào kết nối tới cổng (qua chứng chỉ và `hello`), nên người lạ nhận ra được cùng một máy ở nhiều mạng; chi tiết những gì lộ: `protocol.md` mục 8. Giảm thiểu ở v1.0: lần chạy đầu nói rõ tên hiện với mọi máy (mvp F1) và công tắc ẩn máy khỏi máy chưa ghép đôi (mvp F10, Giai đoạn 4). Quảng bá ẩn danh để sau v1.0 (mục 5.3); tự ẩn khi Windows ở mạng Public: mục 9.

---

## 4. Công nghệ

### 4.1. Thư viện & công cụ

| Mục đích | Thư viện / công cụ | Giấy phép |
|---|---|---|
| Quản lý môi trường & gói | `venv` + `pip` (có thể chuyển sang `uv`) | — |
| Mạng bất đồng bộ, TLS | `asyncio`, `ssl` (có sẵn) | PSF |
| mDNS, đọc card mạng | `zeroconf` (≥ 0.148, < 0.152), `ifaddr` | LGPL-2.1-or-later / MIT |
| Tạo chứng chỉ | `cryptography` | Apache/BSD |
| Giao diện (extra `gui`) | `PySide6-Essentials` (kèm `shiboken6`) | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only (dùng theo LGPL-3.0, mục 1) |
| Icon và font của giao diện (tài sản trong `src/teleport/ui/assets/`, nguồn và commit ghim ở `SOURCE_ASSETS` của `packaging/pyinstaller/third_party.py`) | Fluent UI System Icons (SVG `_regular`, `microsoft/fluentui-system-icons`); font biến thiên Bricolage Grotesque (`google/fonts`) | MIT / OFL-1.1 (đóng nguyên dạng, mục 1) |
| Đo RAM | `psutil` | BSD |
| Kiểm thử | `pytest`, `pytest-asyncio`, `hypothesis`, `pytest-qt`, `pytest-xdist` | MIT / Apache / MPL / MIT / MIT |
| Lint & format | `ruff` | MIT |
| Kiểm tra kiểu | `mypy` (từ Giai đoạn 2) | MIT |
| Biên dịch bản dịch `.ts` → `.qm` (chỉ khi phát triển, gọi từ `packaging/i18n/update.py`; không đóng vào bản build; chỉ `.qm` sinh ra và nguồn `.ts` của nó được đóng, mang giấy phép của dự án) | `lrelease` đi kèm `PySide6-Essentials` | như `PySide6-Essentials` |
| CI / phát hành | GitHub Actions | — |
| Đóng gói | `PyInstaller` chế độ `--onedir` → Inno Setup (Windows; script `packaging/inno/teleport.iss`, bản dịch tiếng Việt `Vietnamese.isl` của `jrsoftware/issrc`), `.dmg` (macOS), AppImage (Linux) | GPL kèm bootloader exception / giấy phép Inno Setup, kiểu zlib (mục 1) / tùy công cụ |

### 4.2. Vai trò của C/C++ và Java
Giao thức chỉ gồm JSON và khung nhị phân `struct`, không phụ thuộc Python, nên ngôn ngữ khác nói chuyện được với app. Ba hướng bổ trợ, đều **tùy chọn** và làm sau khi phần lõi Python đã chạy:

| Ngôn ngữ | Việc bổ trợ | Khi nào làm | Giá trị |
|---|---|---|---|
| C++ | **Bộ nhận tham chiếu** (`tools/cpp-receiver`): nhận file theo đúng giao thức, viết bằng C++ thuần + OpenSSL | Giai đoạn 6 | Benchmark tham chiếu: biết nút thắt nằm ở mạng hay ở Python; kiểm chứng đặc tả giao thức đủ rõ để triển khai độc lập |
| C/C++ | **Module mở rộng** (`pybind11`) cho đoạn code nóng, nếu profiling chỉ ra | Chỉ khi Giai đoạn 2 đo thấy Python là nút thắt | Tăng tốc có số liệu trước/sau |
| Java | **Client dòng lệnh** (`tools/java-client`) gửi/nhận file bằng cùng giao thức | Sau v1.0 | Bước đệm cho app Android (Android dùng Java/Kotlin) |

Ghi chú: `hashlib` và `ssl` của Python vốn đã chạy bằng C (OpenSSL), nên nhiều khả năng **không cần** module C++. Đo trước rồi mới tối ưu.

### 4.3. Cấu trúc repo
Repo Git: GitHub `Nha-Cong-Dong/zero-cloud-lan-teleport` (public, GPL-3.0-or-later). Mọi tài liệu, kể cả y_tuong, mvp và ke_hoach, nằm trong `docs/`.
```
teleport/                      # ← gốc repo
  README.md  LICENSE  pyproject.toml   # gốc repo chỉ có 3 file này (ngoài các file ẩn .gitignore, .gitattributes)
  .claude/CLAUDE.md            # hướng dẫn cho Claude Code
  .claude/agents/              # đội subagent (danh sách: .claude/CLAUDE.md)
  .github/workflows/           # ci.yml; build-cli.yml, build-gui.yml (build thử bản CLI, bản GUI và bộ cài Windows, chạy tay)
  docs/                        # mọi tài liệu .md: README (mục lục, thuật ngữ), y_tuong, mvp, ke_hoach,
                               #   architecture, protocol, CONTRIBUTING, SECURITY, CHANGELOG,
                               #   benchmark, hieu_du_an, (sau này) hướng dẫn người dùng
  src/teleport/                # core/ trust/ net/ app/ ui/ + tiện ích dùng chung và cli.py
  tests/                       # core/, trust/, net/, app/, … theo tầng
  packaging/pyinstaller/       # cấu hình build PyInstaller (cách build: docs/CONTRIBUTING.md)
  packaging/inno/              # script bộ cài Inno Setup cho Windows, bản dịch, giấy phép Inno (cách build: docs/CONTRIBUTING.md)
  packaging/i18n/              # update.py: cập nhật bản dịch .ts/.qm của giao diện (luật: docs/CONTRIBUTING.md, Bản dịch)
  tools/                       # (tùy chọn) cpp-receiver/, java-client/
```
Danh sách module và trạng thái từng module: [architecture.md](architecture.md) mục 3. Module chỉ được tạo khi có code thật.

---

## 5. Lộ trình (~15 tuần tới v1.0)

Nguyên tắc: **làm bằng dòng lệnh (CLI) trước, giao diện sau.** Phần lõi có test chạy được thì gắn UI mới nhanh và ít lỗi. Làm một mình và không có hạn cố định thì rủi ro lớn nhất là kéo dài mãi hoặc ôm thêm tính năng, nên mỗi bản phát hành là một **bản chạy được, dùng được**, gắn tag Git và có ghi chú trong `CHANGELOG.md`.

### 5.1. Tổng quan & trạng thái

Đây là **nơi duy nhất ghi trạng thái giai đoạn**. Trạng thái từng module xem [architecture.md](architecture.md).

| # | Giai đoạn | Thời lượng | Hết tuần | Bản phát hành | Tính năng (mvp) | Người dùng làm được gì | Trạng thái |
|---|---|---|---|---|---|---|---|
| 0 | Nền tảng, repo, CI | 1 tuần | 1 | — | — | — | ✅ Đã xong |
| 1 | Khám phá & ghép đôi | 2 tuần | 3 | — | F2, F3 (lõi + CLI), F12 một phần | Thấy máy khác và ghép đôi qua CLI | ✅ Đã xong (N1 đạt khi đo trên máy ảo bridged, [benchmark.md](benchmark.md) mục 3.3; đo lại trên hai máy thật trong đợt đo, mục 5.4) |
| 2 | Truyền file, backpressure, an toàn khi nhận | 3 tuần | 6 | `v0.1.0-alpha` | F4, F5 (CLI), F12 | Gửi file lớn qua CLI giữa 2 máy đã ghép đôi | ⏸ Code xong, chờ đợt đo (mục 5.4) |
| 3 | Merkle & tự nối lại | 3 tuần | 9 | `v0.2.0-alpha` | F6, F7 | Rớt mạng vẫn tự nối lại, chỉ gửi phần còn thiếu. **Bản CLI đầu tiên đáng cho người dùng kỹ thuật dùng thử** | ⏳ Đang làm |
| 4 | Giao diện, khay hệ thống, đa ngôn ngữ | 2 tuần | 11 | `v0.3.0-beta` | F2–F5 (giao diện), F9, F10, F11 | Dùng hoàn toàn bằng giao diện: radar, kéo thả, ghép đôi | ⏳ Phần lớn đã xong (từng việc: mục 5.2); còn thông báo lỗi theo mvp mục 8, đo RAM khi rảnh (N3), kiểm AC giao diện, D8 và phần cho buổi demo hackathon (mục 5.5) |
| 5 | Đồng bộ clipboard | 1 tuần | 12 | `v0.4.0-beta` | F8 | Đồng bộ clipboard | ⏳ Code xong (module: [architecture.md](architecture.md) mục 3); còn ca ảnh 8192² vượt mvp N6 ([benchmark.md](benchmark.md) mục 9.4) và đợt đo (mục 5.4); chưa thử tay trên máy thật (Wayland, macOS, trình quản lý mật khẩu) |
| 6 | Hoàn thiện, bộ cài, phát hành | 3 tuần | 15 | `v1.0.0` | F1, toàn bộ N1–N12 | Bộ cài 3 hệ điều hành, tài liệu người dùng, đã thử với người dùng thật | ⏳ Đang làm bộ cài Windows (Inno Setup, build thử chạy tay, chưa ký mã: [CONTRIBUTING.md](CONTRIBUTING.md) “Bộ cài Windows”); phần còn lại chưa làm |

Ký hiệu trạng thái: [README.md](README.md) mục 4. Giai đoạn ⏸ còn chờ gì: dòng “Xong khi” của nó ở mục 5.2.

Phiên bản app đánh số theo [SemVer](https://semver.org/lang/vi/); phiên bản giao thức đánh số riêng (mục 3.5). Tiến độ được ghi lại qua commit, GitHub Issues/Milestones và mục `[Unreleased]` của `CHANGELOG.md`.

### 5.2. Chi tiết từng giai đoạn

#### Giai đoạn 0 — Nền tảng, repo, CI ✅
- Đã có nền C/C++/Java nên chỉ cần tập trung vào phần riêng của Python: `async`/`await` và `asyncio` (khác mô hình thread của Java), `struct` (tương tự `struct` trong C / `ByteBuffer` trong Java), module `ssl`, `pytest`.
- Bài tập khởi động: chat TCP giữa 2 máy trong LAN qua TLS.
- Dựng `pyproject.toml`, cấu trúc thư mục, repo GitHub, CI chạy `ruff` + `pytest` trên Windows/macOS/Linux.
- **Xong khi:** 2 máy chat được với nhau qua TLS; CI xanh trên cả 3 hệ điều hành.

#### Giai đoạn 1 — Khám phá & ghép đôi ✅
- ✅ mTLS với chứng chỉ tự ký được kiểm chứng (`net/tls.py`).
- ✅ Nền ghép đôi không mạng (PR #1): `core/messages.py` (`hello`, `pair_*`), `core/pairing_code.py` (nonce cam kết), `trust/identity.py` (kiểm tra chứng chỉ máy khác), `trust/store.py` (`trusted.json`), `lock.py` (một node mỗi thư mục cấu hình).
- ✅ Chốt đặc tả kết nối (`protocol.md` mục 2, 5–9): một cổng `CERT_OPTIONAL` (đã kiểm chứng bằng test), ba loại kết nối, giới hạn và thời gian chờ, chống làm phiền khi ghép đôi, hủy ghép đôi, `hello.os`. Danh tính hỏng hoặc thiếu một nửa báo lỗi thay vì tự tạo lại.
- ✅ `core/pairing.py`: máy trạng thái ghép đôi sans-IO (mục 3.1), test bằng `hypothesis`.
- ✅ `core/messages.py`: `control_open`, `ping`, `pong`.
- ✅ Khám phá mDNS: `core/discovery.py` (bản ghi TXT, lọc địa chỉ, nhận ra card ảo, máy trạng thái `DiscoveryTracker` tự kiểm còn sống) và `net/discovery.py` (zeroconf: quảng bá, cập nhật, goodbye, duyệt) — `protocol.md` mục 8.
- ✅ `net/connection.py` (listener một cổng, phân loại kết nối, trao `hello`, giới hạn và thời gian chờ, keepalive, thay `SSLContext` khi danh sách tin cậy đổi), `core/keepalive.py` (keepalive sans-IO) và bảng loại kết nối trong `core/messages.py` (`ConnectionKind`, `allowed_types`, `opening_kind`).
- ✅ `app/pairing.py` (luồng ghép đôi trên mạng, chống làm phiền, nhường phiên khi hai bên cùng chủ động), `app/node.py` (lắng nghe, cổng dự phòng, nhận kết nối điều khiển, hủy ghép đôi đóng kết nối ngay), `app/settings.py` (`settings.json`), `app/devices.py` (địa chỉ nhập tay, tìm thiết bị theo tên / tiền tố mã), `atomic.py` (ghi file nguyên tử dùng chung).
- ✅ `app/node.py` phần còn lại: giữ kết nối điều khiển tới thiết bị tin cậy (`core/links.py`: chống trùng, nối lại theo lịch, chặn khi bị từ chối), mDNS trong node; quảng bá lại khi card mạng/địa chỉ đổi hoặc máy thức dậy, để máy khác thấy lại ngay (`protocol.md` mục 6, 8).
- ✅ CLI: `teleport listen`, `teleport pair <ip[:cổng]>`, `teleport unpair <thiết bị>`; `--json`; mã thoát 0/1/2.
- ✅ CLI còn lại: `teleport list`, `teleport pair <thiết bị>`; `<thiết bị>` là tên hoặc tiền tố `device_id` (mvp F12).
- ✅ Đo N1 giữa host và máy ảo bridged: đạt ([benchmark.md](benchmark.md) mục 3.3). Tiêu chí tự nhận ra nhau sau khi khởi động lại và từ chối máy chưa ghép đôi có test integration (`tests/app/test_pairing.py`, `tests/app/test_node.py`, `tests/net/test_tls.py`).
- **Xong khi:** đạt N1 (đo trên máy ảo bridged được chấp nhận ở giai đoạn này; đo lại trên hai máy thật: mục 5.4, D1); ghép đôi xong thì tự nhận ra nhau sau khi khởi động lại; máy chưa ghép đôi không mở được kết nối điều khiển hay dữ liệu theo cả hai chiều (chỉ mở được kết nối ghép đôi).

#### Giai đoạn 2 — Truyền file, backpressure, an toàn khi nhận
- Làm trước khi bắt đầu giai đoạn này (không đổi trạng thái ✅ của Giai đoạn 1), đã xong ✅: giới hạn tốc độ bắt tay mới, theo IP và ngân sách chung, cùng pool ưu tiên cho IP đã xác thực mTLS (`teleport.core.admission`, `protocol.md` mục 2.3); client kết nối ra dùng `CERT_REQUIRED` với đúng chứng chỉ đã lưu của máy kia (`protocol.md` mục 2.1, 2.2, 8; mục 8 bên dưới).
- ✅ `core/blocks.py`: khung khối nhị phân kèm hash; `core/merkle.py`, `core/bitfield.py` (dời lên từ Giai đoạn 3, vì định dạng trên dây của protocol 1 được chốt đủ ở `v0.1.0-alpha`); `core/messages.py`: thêm `data_open` và các message truyền file, kiểm tra hợp lệ mọi trường.
- ✅ `core/transfer.py` (nối vào mạng ở `app/transfers.py`): máy trạng thái gửi/nhận, không I/O: `offer`/`accept`/`reject`, nhiều file, hủy; `resume`/`complete`/`verified`; toàn vẹn trong một phiên (kiểm hash từng khối, `resume` xin lại khối sai hay thiếu khi kết nối dữ liệu đứt, lượt đọc lại `.part` cuối, so Merkle root, giới hạn số lần gửi lại → `cancel{error}`); kiểm file nguồn đổi trước `complete` (`cancel{source_changed}`); `cancel{unknown_transfer}` và bia mộ trong bộ nhớ (`protocol.md` mục 6.3).
- ✅ Đồng bộ lại trong bộ nhớ khi kết nối điều khiển bị thay hoặc có lại (`protocol.md` mục 6.3): mất kết nối điều khiển thì chờ nối lại tối đa 30 s (Giai đoạn 3 nâng lên hạn của mvp F6, `protocol.md` mục 6.2), quá hạn thì lượt truyền thất bại, xóa file tạm, giữ các file đã `verified`.
- Giới hạn của Giai đoạn 2: chưa có nhật ký `.state`: bit bật khi khối đã khớp hash và `.part` đã `fsync`; lỗi ghi hay `fsync` `.part` dừng lượt ([architecture.md](architecture.md) mục 4). Trạng thái lượt truyền và bia mộ chỉ nằm trong bộ nhớ, nên bên nhận khởi động lại thì mất hết. Bên nhận bị tắt đột ngột giữa lượt thì thư mục tạm `.teleport/<transfer_id>/` của lượt đó còn lại (node không xóa thư mục không chứng minh được là của mình), nên `offer` gửi lại của chính lượt đó sau khi bên nhận chạy lại thất bại (`cancel{error}`; bên nhận báo nguyên nhân riêng, `TransferResult.TEMP_EXISTS`); người gửi gửi lại thành lượt mới. Giai đoạn 3 sửa bằng `transfer.json` và bia mộ trên đĩa.
- ✅ `app/transfers.py`: chạy máy trạng thái trên kết nối thật, đọc/ghi `.part` theo khối ([architecture.md](architecture.md) mục 5 “Truyền file ở tầng app”).
- ✅ An toàn khi nhận (mục 3.3): làm sạch tên, file tạm trong `.teleport/`, đổi tên không ghi đè; hủy ở cả hai bên (máy nhận xóa file tạm); giới hạn tốc độ gửi.
- ✅ Kiểm hệ file của thư mục nhận trước `accept` (FAT32, mục 8): có file không chứa được thì tự `reject` cả lượt với lý do `file_too_large` (`protocol.md` mục 3.3).
- ✅ Thêm thông báo lỗi ghi đĩa (ghi hay `fsync` `.state`/`.part` lỗi, [architecture.md](architecture.md) mục 4) vào mvp mục 8: trưởng nhóm soạn nguyên văn, người dùng duyệt.
- ✅ CLI: `teleport send <file...> --to <tên>` kèm tiến độ và tốc độ, `teleport receive`; mã thoát khác 0 khi lỗi; `--json`.
- ✅ Build thử CLI bằng PyInstaller để sớm phát hiện vấn đề đóng gói / antivirus (chạy tay, cách build: [CONTRIBUTING.md](CONTRIBUTING.md)).
- **Xong khi** (kiểm được ngay, đã đạt): truyền file cỡ lớn nhất mvp N3 nêu thành công qua `teleport send` / `receive` thật và đạt phần truyền của N3 trên loopback ([benchmark.md](benchmark.md) mục 4.6); test path traversal và tên đặc biệt (`../../x`, `C:\Windows\x`, `CON`, `NUL.txt`, `a.txt:ads`, `x.`, `x.part.state`) đều bị chặn hoặc đổi tên; không có trường hợp nào ghi đè file sẵn có.
- **Xong khi** (đợt đo trên thiết bị thật, mục 5.4): D3, D4. → **`v0.1.0-alpha`** (thời điểm gắn tag: mục 5.4).

#### Giai đoạn 3 — Merkle & tự nối lại
- ✅ Trạng thái bền trên đĩa: `core/resume_state.py` (nhật ký `.state`, [architecture.md](architecture.md) mục 4) và `transfer.json`, đọc/ghi ở `app/storage.py` (nối vào lượt truyền ở `app/transfers.py`); bia mộ của lượt truyền đã hủy lưu trên đĩa (`protocol.md` mục 6.3).
- ✅ Nối lại trong thời hạn mvp F6 sau khi mất kết nối điều khiển (`protocol.md` mục 6.2: hạn và lịch thử lại; trạng thái “Đang nối lại…”); tắt app nhận rồi mở lại vẫn nối tiếp; phát hiện file nguồn thay đổi khi nối lại; dọn file tạm cũ.
- ✅ Đo phần gửi thừa do bộ đệm socket và chốt `SO_RCVBUF`/`SO_SNDBUF`: không đặt (`protocol.md` mục 4.3; số đo trên Windows: [benchmark.md](benchmark.md) mục 7; Linux qua máy ảo dời vào D5).
- **Xong khi** (kiểm được ngay: test tự động, loopback, máy ảo): đạt mọi AC của F6 (trừ việc chỉnh số ngày dọn file tạm trong cài đặt, Giai đoạn 4), F7 và N5, và N4 trong test tự động, cụ thể: (a) mất đường truyền ở mốc mvp N4 nêu (proxy trên loopback cắt hay chặn kết nối; cắt liên kết card mạng của máy ảo) → có lại → hoàn tất, lượng gửi lại trong ngưỡng mvp N4; (b) sửa 1 byte trong `.part` → phát hiện và gửi lại đúng 1 khối; (c) tắt hẳn app nhận (đóng có trật tự, và giết tiến trình) rồi mở lại → vẫn nối lại được, lượng gửi lại trong ngưỡng mvp N4; (d) test `hypothesis` ngắt kết nối ngẫu nhiên → file cuối luôn đúng; đã chốt `SO_RCVBUF`/`SO_SNDBUF` theo số đo (`protocol.md` mục 4.3; Linux, card mạng thật và macOS: D5).
- **Xong khi** (đợt đo trên thiết bị thật, mục 5.4): D5. → **`v0.2.0-alpha`** (thời điểm gắn tag: mục 5.4).

#### Giai đoạn 4 — Giao diện, khay hệ thống, đa ngôn ngữ
- ✅ Cửa sổ chính theo mvp mục 7.1: khung chat hai cột, cột trái là các máy đã ghép đôi, mỗi máy một luồng; radar và “Nhập IP thủ công” ở màn “Tìm máy mới”.
- ✅ Gửi file theo mvp F4 (thả lên máy ở cột trái hay vào luồng, nút “Gửi file”, chuột phải → “Gửi file…”); hộp thoại chấp nhận ở máy nhận; mỗi lượt truyền là một bong bóng trong luồng, có tiến độ/tốc độ/thời gian còn lại/trạng thái và nút hủy; thông báo hệ thống khi nhận xong; lịch sử theo từng thiết bị (mvp F5).
- ✅ Hộp thoại ghép đôi; màn hình cài đặt các mục F10 (còn “Kiểm tra cập nhật”: [architecture.md](architecture.md) mục 3).
- ✅ Công tắc “Cho máy chưa ghép đôi thấy máy này” (mvp F10, mặc định bật): tắt thì node ngừng quảng bá mDNS nhưng vẫn duyệt và tự kết nối ra tới thiết bị tin cậy; đang ẩn mà không ở chế độ chờ ghép đôi (mvp F3) thì cắt kết nối ẩn danh ngay sau bắt tay TLS, không gửi `hello` (`protocol.md` mục 2.3, 8).
- ✅ Nút và màn hình “Chờ ghép đôi” (mvp F3, mục 7.5; `ui/wait_pairing.py`). Giao diện bật/tắt việc nhận ghép đôi trong lúc node đang chạy, theo công tắc ở F10 và việc mở/đóng màn hình đó, qua `Node.accept_pairing` (đã đổi được lúc chạy).
- Các thông báo lỗi theo mvp mục 8.
- ✅ Khay hệ thống, chạy nền (F9); node chạy trong tiến trình giao diện, một bản giao diện mỗi thư mục cấu hình ([architecture.md](architecture.md) mục 2).
- IPC CLI↔giao diện (CLI gửi lệnh cho node của giao diện thay vì tự chạy node): **dời ra khỏi Giai đoạn 4**, chưa có lịch. Tới khi có, CLI và giao diện cùng thư mục cấu hình loại trừ nhau và CLI báo phải thoát giao diện trước (mvp mục 8).
  - Lưu ý khi làm IPC: tới `v0.2`, CLI in ra stdout đồng bộ ngay trên event loop của node, nên terminal ngừng đọc (ví dụ đang tạm dừng cuộn) có thể làm cả node đứng chờ. Máy khác trong LAN không gây ra được việc này. Khi node chạy trong tiến trình giao diện, việc in hay gửi sự kiện cho CLI qua IPC không được chặn event loop của node.
  - Node sống lâu trong tiến trình giao diện: mở lại `Node` (cùng tiến trình) hay để tiến trình khác lấy `node.lock` vừa nhả phải chờ đuôi đĩa của node cũ xong, không thì có thể mở lại đúng lượt mà thread đĩa cũ còn ghi và lượt nối lại hỏng; giữ một event loop suốt đời ứng dụng để đuôi đĩa chạy xong (đuôi đĩa: [architecture.md](architecture.md) mục 5, “Thứ tự `Node.close()`”).
- ✅ Tiếng Việt và English bằng Qt Linguist (F11); dùng được bằng bàn phím, theo chế độ sáng/tối (N12; phần chưa kiểm tay: [architecture.md](architecture.md) mục 3).
- Đo RAM khi rảnh (N3) ngay ở bản này.
- Đo lại N1 trên hai máy thật: chuyển vào đợt đo (mục 5.4).
- **Xong khi** (kiểm được ngay): dùng trọn vẹn không cần dòng lệnh; đạt AC giao diện của F2–F5, F9–F11.
- **Xong khi** (đợt đo trên thiết bị thật, mục 5.4): D8, phần giao diện. → **`v0.3.0-beta`** (thời điểm gắn tag: mục 5.4).

#### Giai đoạn 5 — Đồng bộ clipboard
- Văn bản và ảnh chụp màn hình; chống vòng lặp; công tắc theo thiết bị; bỏ qua nội dung nhạy cảm; biểu tượng khay báo vừa nhận (mục 3.6).
- **Xong khi** (kiểm được ngay, trên loopback): đạt mọi AC của F8.
- **Xong khi** (đợt đo trên thiết bị thật, mục 5.4): D6, và D8 phần clipboard (Wayland, macOS, trình quản lý mật khẩu; mục 3.6). → **`v0.4.0-beta`** (thời điểm gắn tag: mục 5.4).

#### Giai đoạn 6 — Hoàn thiện & phát hành v1.0
- Bộ cài: Inno Setup (Windows, tự tạo rule tường lửa cho mạng Private), `.dmg` (macOS), AppImage (Linux), build tự động bằng GitHub Actions khi gắn tag; lần chạy đầu theo F1; đạt N11.
- Ký mã (code signing) cho Windows để giảm cảnh báo SmartScreen. Chi phí chứng chỉ cần cân nhắc; chưa có thì ghi rõ hướng dẫn “More info → Run anyway”.
- Benchmark công bố ở [benchmark.md](benchmark.md): tốc độ (so với SMB và Google Drive), RAM theo thời gian, thời gian phát hiện, lượng dữ liệu gửi lại khi nối lại. (Tùy chọn) so sánh với bộ nhận C++.
- Tài liệu người dùng: cài đặt, ghép đôi, khắc phục sự cố (tường lửa, cô lập Wi-Fi). `SECURITY.md`, chính sách quyền riêng tư.
- Thử nghiệm với người dùng thật (mvp mục 9.1), sửa lỗi; test soak (N7).
- Tuân thủ giấy phép khi đóng gói: dùng PyInstaller `--onedir` (không `--onefile`) để người dùng thay được thư viện LGPL (Qt/PySide6, zeroconf); bộ cài kèm `LICENSE` (GPL-3.0), văn bản giấy phép các thư viện bên thứ ba, và chỉ dẫn lấy mã nguồn đúng phiên bản.
- Trước bản phát hành thật: thêm dòng bản quyền của các crate chỉ theo MIT liên kết tĩnh vào `_rust.pyd` của `cryptography` (ví dụ `openssl-sys`, `pem`) vào `THIRD-PARTY-NOTICES.txt`.
- Đáp ứng LGPL-2.1 §6 cho zeroconf: phát hành kèm sdist của zeroconf, hoặc kèm lời đề nghị cung cấp mã nguồn bằng văn bản (hiện `SOURCE.txt` chỉ dẫn link PyPI/GitHub).
- **Xong khi:** đạt toàn bộ tiêu chí phát hành ở mvp mục 12, gồm D1–D8 của đợt đo (mục 5.4). → **`v1.0.0`**.

### 5.3. Sau v1.0
1. App Android (Java/Kotlin, dùng cùng giao thức): mDNS cần `MulticastLock`, clipboard qua share-sheet.
2. Chế độ khách qua trình duyệt cho điện thoại không cài app (thứ tự với mục 1 chưa chốt, xem mục 9).
3. Gửi tới nhiều thiết bị cùng lúc, gửi/đồng bộ thư mục.
4. App iOS.
5. Quảng bá mDNS ẩn danh: người nghe thụ động không còn đọc được `device_id` cố định (mục 3.7).

Ý tưởng mới trong lúc làm v1.0 ghi vào GitHub Issues với nhãn `after-1.0`.

### 5.4. Đợt đo trên thiết bị thật

Máy chính có thêm một máy ảo Ubuntu bridged ([benchmark.md](benchmark.md) mục 3.3) và hiện mượn tạm được một máy Windows 10 thật (mới có một lần đo tay, chỉ để tham khảo: [benchmark.md](benchmark.md) mục 5.4), nên mọi phép đo cần máy thật thứ hai hay thiết bị khác được **dồn vào một đợt**, làm một lượt khi có thiết bị. Việc code các giai đoạn không chờ đợt này: dòng “Xong khi” của mỗi giai đoạn ở mục 5.2 tách phần kiểm được ngay (test tự động, loopback, máy ảo) khỏi phần thuộc đợt đo, và chính các dòng đó ghi giai đoạn nào chờ mã D nào. Mục này là nơi duy nhất liệt kê các phép đo của đợt; định nghĩa phép đo, script và kết quả ở [benchmark.md](benchmark.md), ngưỡng và điều kiện đo ở [mvp.md](mvp.md) mục 9.

| Mã | Phép đo | Thiết bị cần | Định nghĩa, cách đo |
|---|---|---|---|
| D1 | mvp N1 giữa hai máy thật, qua Wi-Fi có điểm phát thật và qua mạng dây; kịch bản mất gói ở hai lần resolve đầu ([protocol.md](protocol.md) mục 8) | Máy thật thứ hai | [benchmark.md](benchmark.md) mục 3 |
| D2 | mvp N2: Teleport so với SMB, qua Wi-Fi và qua mạng dây | Máy thật thứ hai chạy Windows | [benchmark.md](benchmark.md) mục 5 |
| D3 | mvp N3 khi truyền qua card mạng giữa hai máy, với cỡ file lớn nhất mvp N3 nêu, RAM hai phía; đo cùng lượt D2 | Máy thật thứ hai | [benchmark.md](benchmark.md) mục 4.1 (“Qua card mạng giữa hai máy”), 4.4 |
| D4 | mvp N3 khi ổ đích chậm; nhận nhiều file nhỏ trên ổ chậm (mục 8, dòng rủi ro “nhiều file nhỏ”) | USB định dạng NTFS hoặc exFAT, hoặc ổ ảo giới hạn tốc độ | [benchmark.md](benchmark.md) mục 4.4, 4.8 |
| D5 | mvp N4 trên mạng thật: tắt Wi-Fi giữa lượt truyền rồi bật lại; phần gửi thừa do bộ đệm socket qua card mạng thật, trên Linux (máy ảo bridged được) và trên macOS ([protocol.md](protocol.md) mục 4.3) | Máy thật thứ hai hoặc máy ảo Linux bridged; một máy macOS | [benchmark.md](benchmark.md) mục 7.4, 7.5 |
| D6 | mvp N6 trên loại mạng Wi-Fi mà mvp N6 nêu | Máy thật thứ hai; điểm phát Wi-Fi đúng loại đó | [benchmark.md](benchmark.md) mục 9 (việc còn lại: 9.5) |
| D7 | mvp N10: các hệ điều hành mvp N10 nêu gửi/nhận qua lại, gồm N1 và truyền file cho từng cặp | Máy thật cho từng hệ điều hành đó | [benchmark.md](benchmark.md), mục mvp N10 (viết khi đo) |
| D8 | Kiểm thủ công trên thiết bị thật (mục 7, dòng “Thủ công trên thiết bị thật”) | Hai máy thật, nhiều mạng | Mục 7 |

- Không thuộc đợt đo (đo được trên một máy, theo giai đoạn của chúng): mvp N3 lúc rảnh của app có giao diện, N4 và N5 bằng test tự động, N7, N8, N9, N11, N12.
- Một mã D chỉ xong khi [benchmark.md](benchmark.md) có kết luận ĐẠT cho nó, hoặc người dùng chấp nhận kết quả khác và mvp được sửa theo.
- Phần nào đo sớm được trên máy ảo (ví dụ một phần D7 với Ubuntu) thì cứ đo và ghi vào benchmark kèm giới hạn; mã D đó vẫn mở tới khi đo trên thiết bị thật, trừ khi người dùng chấp nhận số đo máy ảo như ở Giai đoạn 1.
- Kết quả không đạt thì sửa code trong giai đoạn đang làm lúc đó, rồi đo lại mã D đó.
- Giai đoạn còn mã D mở thì chưa gắn tag. Đợt đo chạy trên `main` lúc đo; sau đợt đo chỉ gắn tag của giai đoạn mới nhất có cả hai dòng “Xong khi” đã đạt, lên đúng commit `main` đã dùng để đo. Tag của các giai đoạn ⏸ cũ hơn bị bỏ qua, và mục phiên bản của tag đó trong `CHANGELOG.md` gộp mọi thay đổi từ trước. Đợt đo phải xong trước `v1.0.0` (mvp mục 12). Sau đợt đo, giai đoạn nào không còn mã D mở thì đổi ⏸ thành ✅ ở mục 5.1.

### 5.5. Lịch tới buổi demo hackathon

Phạm vi và tiêu chí H1–H5: [mvp.md](mvp.md) mục 4.1. Buổi demo hết tuần 4 của hackathon, khoảng 08/11/2026. Lịch này giữ các ngày cần hai máy thật và các bản zip dùng để kiểm H1–H5.

**Đóng băng từ 03/11 tới hết buổi demo** (quyết định 03/11, theo review Checkpoint 3, thay cho quyết định bỏ đóng băng ngày 01/11):
- `main` chỉ nhận bản sửa lỗi: lỗi tìm được trên máy thật, lỗi chặn một tiêu chí H, hoặc sửa tài liệu cho khớp bản demo. Tính năng mới và việc hoàn thiện theo mục 5.2 (Giai đoạn 4–5) làm ở nhánh riêng, merge sau buổi demo.
- Mỗi PR sửa dưới khoảng 300 dòng `src/`. Trước khi merge, người dùng tự viết 3 dòng trong mô tả PR: sửa gì, dữ liệu từ máy khác đi vào đâu, test nào chứng minh. Chưa có 3 dòng đó thì chưa merge.
- Không thêm file test mới chỉ để theo một thay đổi giao diện.

Máy thật thứ hai (máy mượn) chỉ có mặt các ngày 02, 06, 07 và 08/11, nên mọi việc cần hai máy thật dồn vào các ngày đó.

| Ngày | Việc | Xong khi |
|---|---|---|
| 30/10–01/11 | Sửa những lỗi giao diện người xem sẽ thấy (thẻ lượt truyền, tiến độ, bấm vào thiết bị), ghi lỗi không bắt được vào log; build zip thử từ `main` bằng CI; kiểm tay hai node trên một máy bằng mã nguồn | Bản sửa đã merge vào `main`; có zip thử từ CI; kiểm tay hai node trên một máy đạt |
| 02/11 | **Kiểm sớm** trên hai máy thật bằng zip thử, đúng mạng sẽ dùng ngày 08/11: mDNS (H1), sơ bộ H2–H5, đo tốc độ để chọn cỡ file | Lần chạy đầu của zip trên máy mượn chưa cài Python chạy được; có danh sách lỗi trên máy thật |
| 03/11–04/11 | Bắt đầu đóng băng; sửa lỗi tìm được ngày 02/11; cập nhật README và mvp mục 4.1 theo đúng bản sẽ demo | Lỗi của ngày 02/11 đã sửa và merge vào `main`; README và mvp mục 4.1 khớp `main` |
| 05/11 | Build zip ứng viên RC1 từ `main` bằng CI, `pytest -m demo` trên commit của zip, `pytest -m frozen`; kiểm tay trên exe của RC1; chạy `soat-tai-lieu`; chuẩn bị hai máy và mạng | Có zip ứng viên |
| 06/11 | **Kiểm H1–H5 chính thức** trên RC1 | H1–H5 có kết quả trong [benchmark.md](benchmark.md) mục 6 |
| 07/11 | Có sửa thì build RC2 và kiểm lại các H bị ảnh hưởng; **18:00 chốt zip**; quay video dự phòng; tập lại, có một lần đi đường CLI và một lần không có mDNS (nhập IP) | Zip chốt, commit của zip ghi ở [benchmark.md](benchmark.md) mục 6 |
| 08/11 | Chuẩn bị lại hai máy và mạng như 05/11; không build, không sửa | — |

- Kiểm sớm ngày 02/11 **không tính là đạt**, kể cả khi đủ H1–H5: không ghi kết quả H vào [benchmark.md](benchmark.md) mục 6.
- Zip đổi commit sau 06/11 (RC2 hay bản sửa khác) thì kiểm lại các H mà thay đổi đó có thể ảnh hưởng, trên đúng zip mới, trước khi chốt.

Các ngày kiểm chính thức 06–07/11 đo luôn được D1, D3, D5 (mục 5.4) nếu kịp; không kịp thì để lại cho đợt đo.

---

## 6. Quy trình phát triển
Bản chính thức: [CONTRIBUTING.md](CONTRIBUTING.md). Tóm tắt:
- **Nhánh:** `main` luôn chạy được và được bảo vệ (chỉ merge qua Pull Request khi CI xanh). Mỗi việc làm trên nhánh riêng `feat/...`, `fix/...`.
- **Commit:** theo [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, `test:`, `chore:`), giúp viết `CHANGELOG.md` dễ dàng.
- **CI** (`.github/workflows/ci.yml`): các bước kiểm tra và ma trận hệ điều hành × Python ở [CONTRIBUTING.md](CONTRIBUTING.md). `mypy` có từ đầu Giai đoạn 2 (cấu hình trong `pyproject.toml`).
- **Đội subagent** trong `.claude/agents/`: vai trò và quy trình ở `.claude/CLAUDE.md`. Chỉ commit và push khi người dùng đồng ý.
- **Phát hành:** các bước, cách đánh số và cách phát hành bản thử nghiệm ở [CONTRIBUTING.md](CONTRIBUTING.md). Build bộ cài tự động khi gắn tag và GitHub Release là việc của Giai đoạn 6; hiện chỉ có build thử chạy tay (`workflow_dispatch`): bản CLI, bản GUI (zip) và bộ cài Windows thử (Inno Setup, chưa ký mã; [CONTRIBUTING.md](CONTRIBUTING.md) “Bộ cài Windows”).
- **Theo dõi công việc:** GitHub Issues + Milestones tương ứng từng bản phát hành ở mục 5.1.

---

## 7. Kiểm thử

| Loại | Nội dung | Phục vụ |
|---|---|---|
| Unit test | Đóng/mở khung, message, mã ghép đôi (test vector), Merkle root (so với kết quả tính tay trên file nhỏ), bitfield, đọc/ghi state, làm sạch tên file | F3, F4, F7 |
| Tích hợp | 2 node trên cùng máy qua `127.0.0.1` với 2 thư mục cấu hình khác nhau; proxy TCP nhỏ tự viết để cắt kết nối giữa chừng hoặc làm chậm đường truyền | F4–F6, N4 |
| Property test (`hypothesis`) | Ngắt tại vị trí ngẫu nhiên, nối lại nhiều lần → hash file cuối luôn khớp. Fuzz bộ đọc message bằng dữ liệu ngẫu nhiên | N5, N8 |
| Benchmark | Tốc độ so với SMB, RSS theo thời gian, thời gian phát hiện, byte gửi lại | N1–N4 |
| Soak test | 100 lượt truyền liên tiếp, kiểm tra không rò bộ nhớ, không còn file tạm | N7 |
| Thủ công trước mỗi bản beta/1.0 | Trên một máy: giao diện, trợ năng (bàn phím, tương phản, chế độ sáng/tối) | N12, AC giao diện |
| Thủ công trên thiết bị thật | 2 máy thật trên Wi-Fi nhà, văn phòng, quán cà phê; các hệ điều hành của mvp N10; phát hiện tường lửa và cô lập thiết bị (mvp mục 8); đồng bộ clipboard (mục 3.6). Làm trong đợt đo (mục 5.4) | N10, AC giao diện |

Quy ước viết test (marker, fixture, chỗ test thay được): [architecture.md](architecture.md) mục 6.

---

## 8. Rủi ro kỹ thuật & thực thi

Rủi ro về sản phẩm và thị trường (cô lập Wi-Fi, SmartScreen, cạnh tranh, thứ tự cắt giảm khi trễ): mvp mục 14.

| Rủi ro | Giảm thiểu |
|---|---|
| Mới làm quen `asyncio` | Giai đoạn 0 dành riêng để học; làm CLI trước UI |
| Trộn Qt với asyncio phức tạp | Không trộn hai event loop: node chạy loop `asyncio` chuẩn trong thread riêng, Qt chỉ gọi node qua cầu `NodeHost`, thoát có hạn ([architecture.md](architecture.md) mục 5); lõi không phụ thuộc Qt nên test riêng được |
| Python chậm hơn mong đợi (N2) | Đo trong đợt đo trên thiết bị thật (mục 5.4, D2); thông lượng loopback tham khảo: [benchmark.md](benchmark.md) mục 4.6; tăng kích thước khối hoặc bộ đệm socket; module C++ nếu thật sự cần |
| Python + Qt khó đạt ngưỡng RAM lúc rảnh của mvp N3 | Đo sớm từ `v0.3.0-beta`; tối ưu, hoặc nới yêu cầu có lý do và sửa N3 trong mvp.md |
| Vi phạm điều kiện LGPL/GPL khi đóng gói | Đóng gói `--onedir`, không sửa mã thư viện LGPL, kèm văn bản giấy phép và chỉ dẫn lấy mã nguồn; kiểm lại trong Giai đoạn 6 |
| Bộ cài PyInstaller nặng (N11) hoặc bị antivirus báo nhầm | Build thử từ Giai đoạn 2; gửi mẫu cho các hãng antivirus nếu bị báo nhầm |
| Windows Firewall chặn | Bộ cài tạo rule; app phát hiện và hướng dẫn khi bị chặn |
| python-zeroconf nâng TTL bản ghi PTR nhận được lên ≥ 1125 s, nên máy tắt đột ngột không tự biến mất trong thời hạn mvp N1 | Bên nhận tự kiểm còn sống bằng cách resolve lại SRV/TXT/A theo chu kỳ (`protocol.md` mục 8); đo N1 ([benchmark.md](benchmark.md), đo lại trên hai máy thật: mục 5.4, D1); kiểm lại hành vi này mỗi khi nâng phiên bản zeroconf |
| VPN full-tunnel chiếm tuyến ra ngoài LAN: IP của card VPN thành địa chỉ nguồn ưu tiên (`protocol.md` mục 2.1), nên được quảng bá ra LAN dù là card ảo và được `teleport listen` gợi ý | Việc sau: ngoại lệ “luôn giữ địa chỉ nguồn ưu tiên” không áp cho card dạng đường hầm (tun, wg, utun, ppp, ipsec, wintun, wireguard, openvpn, vpn, tailscale, zt…), vẫn áp cho Hyper-V/bridge (External vSwitch) |
| `NetworkWatch` so cả thứ tự địa chỉ quảng bá: địa chỉ ưu tiên đổi (ví dụ tuyến ra ngoài chuyển từ Wi-Fi sang Ethernet) mà tập địa chỉ giữ nguyên vẫn bị coi là đổi mạng: khởi động lại mDNS và báo `network_changed` cho các kết nối điều khiển, không cần thiết | Việc sau: `NetworkWatch` so tập địa chỉ thay vì dãy có thứ tự (`protocol.md` mục 8) |
| Từ chối dịch vụ ghép đôi trong LAN (giữ phiên, đổi IP, làm đầy giới hạn kết nối ẩn danh, bắt tay TLS với chuỗi chứng chỉ client lớn) | Chờ tăng dần theo IP, giới hạn số mã hiện ra, hạn chờ `pair_nonce` ngắn (`protocol.md` mục 2.3); phần còn lại chấp nhận theo `protocol.md` mục 5.3. Giới hạn kết nối đang mở đầu một mình không đủ giữ event loop nhanh khi máy lạ gửi chuỗi chứng chỉ client lớn (đã đo, `protocol.md` mục 2.3), nên đã thêm ✅ giới hạn tốc độ bắt tay mới theo IP và ngân sách chung, áp trước `start_tls`, cùng pool ưu tiên cho IP đã xác thực mTLS để thiết bị đã ghép đôi vẫn nối lại được (`teleport.core.admission`, `protocol.md` mục 2.3; giới hạn còn lại ở đó) |
| Kẻ lạ trong LAN có nhiều IP, đầu độc mDNS và xoay vòng relay tới thiết bị tin cậy thật chặn được pool ưu tiên (ngân sách lỗi tính theo IP; giới hạn M3, `protocol.md` mục 2.3) | Chấp nhận cho v1.0 (cần nhiều IP và kẻ tấn công trong LAN; kết nối đang sống không bị ảnh hưởng). Việc sau: ngân sách lỗi theo thiết bị (fingerprint) đã cấp ưu tiên, trừ ngay lúc nhận vé ưu tiên |
| Lũ TCP trần: client reset giữa SYN và `accept`, asyncio in một dòng traceback “Accept failed on a socket” (WinError 64 trên Windows) mỗi lần chạy lũ; server vẫn chạy tiếp, kết nối đó không vào `AdmissionGate` nên không tính vào `refusals` (lần đo T2, `protocol.md` mục 2.3) | Vô hại về chức năng, chỉ gây nhiễu log. Việc sau: nuốt hoặc hạ mức log riêng lỗi này ở vòng `accept` |
| **Cả hai bên** giữ hash mọi khối của file đang truyền trong RAM (bên gửi để tính Merkle root, `protocol.md` mục 4.2; bên nhận để đọc lại và tính Merkle root): 32 byte mỗi khối, tới 128 MiB cho file 4 TiB (trần `size`, `protocol.md` mục 3.3). Gộp `.state` của file 4 TiB mà dựng cả bản gọn trong RAM thì thêm khoảng 144 MiB | Lưu hash dồn trong một `bytearray` 32·N byte, không dùng `list[bytes]` (khoảng 80 byte mỗi khối); gộp và đọc lại `.state` theo từng đoạn ([architecture.md](architecture.md) mục 4). Vẫn trong ngưỡng mvp N3 ở các cỡ file N3 đo, nhưng RAM tăng theo kích thước file (trái mục 2, dòng RAM). Gộp `.state` trong lúc nhận đọc lại chính `.state` nên dùng thêm RAM tạm 32 byte mỗi khối, chỉ trong lúc gộp (hiếm). Nếu đo thấy vượt mvp N3, phương án là đọc hash từ `.state` theo từng đoạn thay vì giữ cả danh sách trong RAM |
| Bộ đệm socket do hệ điều hành tự điều chỉnh có thể lớn, làm tăng phần gửi thừa ở mvp N4 (`protocol.md` mục 4.3) | Đo ở Giai đoạn 3; vượt ngưỡng thì đặt bộ đệm theo từng hệ điều hành, đặt trước `connect` ở phía client |
| Nhận nhiều file nhỏ chậm hơn rõ vì mỗi file có thêm vài lần `fsync` để bền sau khi sập (mvp F6, F7); số đo trên loopback: [benchmark.md](benchmark.md) mục 4.9, ổ chậm chưa đo | Đo trên ổ chậm cùng D4 (mục 5.4); nhiều lượt liên tiếp trong một tiến trình đo ở Giai đoạn 3 trên loopback. Làm mvp N2 (D2) hay N7 không đạt thì bớt `fsync` mà vẫn giữ thứ tự bền ([architecture.md](architecture.md) mục 4) |
| Lượt nhận dở (đang chờ nối lại, kể cả lượt được khôi phục sau khi app nhận khởi động lại) vẫn giữ chỗ trống cho phần còn thiếu (`promised_bytes` của `teleport.core.transfer`) suốt thời hạn nối lại (`protocol.md` mục 6.2), nên `offer` mới trong lúc đó có thể bị tự từ chối vì thiếu chỗ dù đĩa đang trống | Chấp nhận cho v1.0: giữ chỗ là để lượt dở chắc chắn nhận xong được. Người dùng hủy lượt dở (giao diện, Giai đoạn 4; CLI chưa có lệnh hủy lượt nhận dở, chỉ chờ hết hạn nối lại) thì chỗ được trả ngay; lượt quá hạn nối lại thì hết hạn và file tạm bị xóa (`protocol.md` mục 6.2) |
| Thư mục nhận nằm trên FAT32 (mỗi file phải nhỏ hơn 4 GiB) mà lượt truyền có file lớn hơn: ghi `.part` thất bại giữa chừng | Giai đoạn 2: bên nhận kiểm hệ file của thư mục nhận trước `accept`; có file không chứa được thì tự `reject` cả lượt, không hỏi người dùng (mvp F4, thông báo ở mvp mục 8). Nhận dạng hệ file ở `teleport.app.storage.volume_info` ([architecture.md](architecture.md) mục 4 “Thư mục nhận”); không nhận ra hệ file thì không giới hạn, lỗi `EFBIG` đi theo lỗi ghi đĩa |
| Kết nối điều khiển **đi ra** từng dùng `CERT_NONE` và gửi chứng chỉ client trong lúc bắt tay, trước khi so fingerprint của server: máy giả bản ghi mDNS (SRV/A) của một thiết bị tin cậy thu được `device_id` và fingerprint cố định của máy này, kể cả khi máy này đang ẩn | Đã làm ✅: client của kết nối điều khiển và kết nối dữ liệu kiểm chứng chỉ server ngay trong bắt tay bằng đúng chứng chỉ đã lưu (`CERT_REQUIRED`), nên từ chối server sai trước khi gửi chứng chỉ client; lỗi kiểm chứng chỉ đó tính là danh tính không khớp, không phải không kết nối được (`protocol.md` mục 2.2, 8) |
| `teleport send --address` trỏ nhầm tới **một thiết bị tin cậy khác** (không phải máy ở `--to`): chứng chỉ server không khớp chứng chỉ đã lưu của máy ở `--to`, nên CLI báo danh tính khác, có thể có người giả mạo (mvp mục 8, “Danh tính thiết bị thay đổi”), dù không có ai giả mạo | Chấp nhận ở `v0.1.0-alpha`: kết nối bị từ chối trong bắt tay, không lộ gì và không gửi gì, chỉ là câu báo gây hiểu nhầm. Việc sau: nhận ra chứng chỉ server là của một thiết bị tin cậy khác để báo đúng là địa chỉ đó thuộc máy nào |
| Lỗ hổng bảo mật (path traversal, dữ liệu độc hại từ máy khác) | Kiểm tra hợp lệ mọi trường nhận được; fuzz test; `SECURITY.md` để nhận báo lỗi |
| Làm một mình, không có hạn → kéo dài, ôm thêm tính năng | Bám các bản phát hành ở mục 5.1; ý tưởng mới ghi Issues nhãn `after-1.0`; nếu trễ thì cắt theo thứ tự ở mvp mục 14 |
| Chỉ có 1 máy để thử (máy thứ hai hiện chỉ mượn tạm, mục 5.4) | Chạy 2 node trên cùng máy qua `127.0.0.1` cho phát triển hằng ngày; mượn máy thứ 2 hoặc dùng máy ảo (VirtualBox, mạng bridged) cho test LAN thật; N1 đã đo theo cách này ([benchmark.md](benchmark.md) mục 3.3); mọi phép đo cần thiết bị thật dồn vào đợt đo (mục 5.4) |

---

## 9. Việc cần chốt

Đây là danh sách câu hỏi mở duy nhất của dự án.

1. **Ngân sách ký mã** cho Windows/macOS.
2. **Chế độ khách cho điện thoại** (qua trình duyệt) có làm ngay sau v1.0, trước app Android, hay không.
3. **App iOS và CLA** (sau v1.0): điều khoản App Store xung đột với GPL. Muốn đưa app lên App Store thì chủ bản quyền phải cấp thêm giấy phép riêng, nên cần người đóng góp ký thỏa thuận chuyển quyền (CLA) **trước khi** nhận code của họ. Chưa có người đóng góp ngoài nên chưa cần; cần quyết trước khi nhận Pull Request đầu tiên từ bên ngoài.
4. **Tự ẩn khi Windows ở mạng Public:** có tự ngừng quảng bá mDNS (như tắt công tắc ẩn ở mvp F10) khi Windows đang đặt mạng hiện tại là Public hay không. Lợi: ở quán cà phê, khách sạn, người lạ không đọc được `device_id` và tên máy (mục 3.7). Hại: Windows hay đặt nhầm mạng nhà là Public, và khi đó máy này biến mất khỏi radar của máy khác. Chỉ áp cho Windows. Chốt ở Giai đoạn 6.
