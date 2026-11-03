# MVP — Zero-Cloud LAN Teleport v1.0

> **Vai trò:** đặc tả sản phẩm — giải quyết vấn đề gì, cho ai, gồm những gì, trông ra sao, đạt chuẩn nào thì được phát hành.
> **Nguồn duy nhất cho:** phạm vi MVP, tính năng và tiêu chí chấp nhận (F1–F12), yêu cầu phi chức năng (N1–N12), thông báo lỗi, tiêu chí phát hành.
> **Không chứa:** thiết kế kỹ thuật, lộ trình và tiến độ → [ke_hoach.md](ke_hoach.md). Ý tưởng, nguyên tắc và tầm nhìn → [y_tuong.md](y_tuong.md). Thuật ngữ, quy ước và bản đồ tài liệu → [README.md](README.md).
> **Cập nhật:** 2026-11-03

---

## 1. Tóm tắt một trang

**Teleport** là ứng dụng desktop giúp chuyển file nặng hàng chục GB và đồng bộ clipboard giữa các máy tính **trong cùng mạng Wi-Fi/LAN**. Dữ liệu đi thẳng từ máy này sang máy kia, **không qua cloud, không cần tài khoản**.

| | |
|---|---|
| **Cho ai** | Người làm việc với nhiều máy tính hoặc ngồi cạnh đồng nghiệp: lập trình viên, designer, dựng video, văn phòng nhỏ, gia đình |
| **Vấn đề** | Chuyển file giữa hai máy cách nhau 20cm vẫn phải qua Zalo (nén ảnh, giới hạn dung lượng), Google Drive (upload rồi download, tốn gấp đôi thời gian), USB (phải tìm, cắm, rút) hoặc chia sẻ thư mục Windows (cấu hình phức tạp) |
| **Giải pháp** | Mở app → máy kia tự hiện trên radar → kéo file thả vào → xong |
| **Khác biệt** | Rớt mạng giữa chừng vẫn **tự nối lại và chỉ gửi phần còn thiếu**; kiểm tra toàn vẹn từng khối; đồng bộ clipboard; không tài khoản, không telemetry |
| **Nền tảng** | Windows 10/11 (chính), macOS 12+, Ubuntu 22.04+ |
| **Mô hình** | Ứng dụng cài trên máy, hoạt động hoàn toàn offline trong mạng nội bộ |

---

## 2. Vấn đề & người dùng mục tiêu

### 2.1. Chân dung người dùng

| Người dùng | Bối cảnh | Nhu cầu chính | Hiện đang làm |
|---|---|---|---|
| **Minh — lập trình viên** | Laptop công ty + PC ở nhà, hay chuyển bản build 2–5GB, dump database | Nhanh, không giới hạn dung lượng, không phải đăng nhập tài khoản cá nhân lên máy công ty | USB hoặc Google Drive |
| **Lan — dựng video** | Quay xong copy footage 30–80GB từ laptop sang máy dựng | Ổn định với file cực lớn, rớt Wi-Fi không phải gửi lại từ đầu | Ổ cứng rời |
| **Văn phòng 5 người** | Gửi tài liệu, ảnh chụp màn hình qua lại cả ngày | Gửi nhanh cho người ngồi cạnh, copy đoạn văn từ máy này dán sang máy kia | Zalo, email cho chính mình |

### 2.2. Vì sao giải pháp hiện tại chưa ổn

| Cách | Tốc độ | File lớn | Riêng tư | Dễ dùng | Rớt mạng |
|---|---|---|---|---|---|
| Zalo / Messenger | Phụ thuộc Internet | ❌ giới hạn, nén ảnh | ❌ qua máy chủ, phải đăng nhập | ✅ | Gửi lại từ đầu |
| Google Drive | Upload + download ≈ gấp đôi | ⚠️ chậm | ⚠️ lưu trên cloud | ✅ | Tùy |
| USB | Nhanh | ✅ | ✅ | ⚠️ phải có USB, cắm rút | — |
| Chia sẻ thư mục Windows (SMB) | Nhanh | ✅ | ⚠️ cấu hình quyền phức tạp | ❌ | Gửi lại từ đầu |
| **Teleport** | **Tối đa tốc độ LAN** | **✅ hàng chục GB** | **✅ mã hóa, không cloud** | **✅ kéo thả** | **✅ chỉ gửi phần thiếu** |

---

## 3. Giá trị cốt lõi

Ý nghĩa từng giá trị: [y_tuong.md](y_tuong.md) mục 3. MVP đo từng giá trị bằng các tính năng và yêu cầu sau:

| Giá trị | Tính năng | Yêu cầu đo được |
|---|---|---|
| **Zero-Friction** | F1, F2, F3 | N1, N11, mục 9.1 |
| **Zero-Cloud** | F8, F10 | N8, N9 |
| **Zero-RAM-Overflow** | F4 | N3 |
| **Không sợ rớt mạng** | F6, F7 | N4, N5 |

---

## 4. Phạm vi MVP

| ✅ Có trong MVP (v1.0) | ❌ Không có trong MVP |
|---|---|
| Ứng dụng desktop Windows / macOS / Linux | Ứng dụng điện thoại Android / iOS |
| Tự khám phá thiết bị qua mDNS + nhập IP thủ công | Truyền qua Internet / khác mạng |
| Ghép đôi bằng mã 6 số | Tài khoản, đăng nhập |
| Gửi một hoặc nhiều file (kéo thả hoặc chọn file) | Gửi cả thư mục, đồng bộ thư mục |
| Hỏi người nhận chấp nhận / từ chối | Gửi một lúc tới nhiều thiết bị |
| Tự nối lại sau rớt mạng, kể cả khi đã tắt app nhận | Chế độ khách qua trình duyệt |
| Kiểm tra toàn vẹn bằng SHA-256 Merkle | Nén dữ liệu khi truyền |
| Đồng bộ clipboard văn bản và ảnh | Đồng bộ clipboard dạng file |
| Khay hệ thống, chạy nền, khởi động cùng máy | Tự động cập nhật ngầm |
| Giao diện Tiếng Việt + English | Ngôn ngữ khác |
| Dòng lệnh (CLI) cho người dùng nâng cao | Plugin / API cho bên thứ ba |

Thứ tự làm các mục “không có” sau v1.0: [ke_hoach.md](ke_hoach.md) mục 5.3. Nếu trễ tiến độ, một số mục “có” được hoãn theo thứ tự ở mục 14.

### 4.1. MVP hackathon

Bản tối thiểu để demo ở buổi demo hackathon, nhỏ hơn MVP v1.0 ở trên. Lịch làm: [ke_hoach.md](ke_hoach.md) mục 5.5.

**Có:** giao diện trên Windows: danh sách cuộc trò chuyện theo từng máy, trang “Tìm máy mới” (radar, ô nhập IP), ghép đôi bằng mã 6 số, kéo thả hoặc “Gửi file…”, hộp thoại Nhận / Từ chối, lượt truyền có tiến độ, tốc độ, trạng thái “Đang nối lại…” và nút hủy; tự nối lại và kiểm tra toàn vẹn như F6, F7; bản zip chạy không cần cài Python. CLI giữ như F12.

**Có trong bản zip nhưng không nằm trong kịch bản demo:** trang “Chờ ghép đôi” (F3), hệ điều hành bằng chữ và trạng thái “đang bận” (F2), khay hệ thống và chạy nền (F9), trang Cài đặt kèm khởi động cùng Windows (F10), English (F11), đồng bộ clipboard (F8), dùng bằng bàn phím và trình đọc màn hình, sáng/tối (N12). Bộ cài thử Inno Setup (N11) được build riêng, không phải bản zip, chưa ký số.

**Để sau hackathon:** kiểm thủ công đủ N12; bộ cài ký số và bản phát hành chính thức; macOS và Linux có bản đóng gói; luồng máy đã ghép đôi cài lại Teleport trên giao diện (F3, mục 8; CLI đã gợi ý ở `teleport list`).

**Đạt khi** cả năm tiêu chí sau đạt trên **hai máy Windows thật cùng một mạng Wi-Fi**, mỗi máy chạy bản zip, không gõ lệnh nào (trừ lệnh kiểm hash). Mỗi tiêu chí ghi kết quả và ngày vào [benchmark.md](benchmark.md).

| Mã | Tiêu chí | Cách kiểm |
|---|---|---|
| H1 | Máy kia hiện trên radar trong thời gian mvp N1 nêu; ghép đôi xong bằng mã 6 số xác nhận ở cả hai máy | Trước khi đo, hủy ghép đôi ở **cả hai** máy. Bấm giờ từ lúc mở app máy B tới lúc B hiện trên radar máy A, rồi ghép đôi |
| H2 | Kéo một file ≥ 1 GiB thả vào máy kia; máy nhận hiện hộp thoại, bấm Nhận; file nhận có SHA-256 trùng file gốc | `Get-FileHash` ở hai máy |
| H3 | Đang gửi file ở H2, tắt Wi-Fi một máy khi tiến độ khoảng 50%, chờ 10 giây rồi bật lại: lượt truyền tự chạy tiếp, tiến độ không về 0, SHA-256 trùng | Quan sát tiến độ; `Get-FileHash` |
| H4 | Đóng hẳn app nhận giữa lượt truyền rồi mở lại: lượt truyền tự chạy tiếp và hoàn tất, SHA-256 trùng (F6) | Như H3 |
| H5 | Gửi lại đúng file ở H2: máy nhận lưu thành `ten (1).ext`, file cũ không đổi; máy thứ ba chưa ghép đôi (hoặc máy B sau khi máy A hủy ghép đôi với B) không gửi được file tới máy A: máy B thấy câu của dòng “Máy kia từ chối máy này” (mục 8), máy A không hiện hộp thoại nhận và không có file mới | Xem thư mục nhận; `Get-FileHash` file cũ. Với máy B: hủy ghép đôi ở máy A, giữ nguyên ở máy B, rồi B gửi file tới A; kiểm xong hủy nốt ở máy B để **cả hai** máy về chưa ghép đôi |

Từ 03/11 tới hết buổi demo, `main` đóng băng tính năng: chỉ nhận bản sửa lỗi, luật ở [ke_hoach.md](ke_hoach.md) mục 5.5. Bản zip đã kiểm H1–H5 được chốt theo commit. Không đạt kịp thì demo bằng CLI cho phần giao diện còn thiếu; H2–H5 vẫn phải đạt bằng CLI.

Kịch bản demo hackathon (5 phút): các dòng 0:00–3:00 của mục 13, thêm H4 (đóng app nhận rồi mở lại) và dòng 4:00 (tắt Internet của router). Bỏ clipboard và so sánh với Google Drive.

---

## 5. Tính năng & tiêu chí chấp nhận

Mỗi tính năng có các user story (US) và tiêu chí chấp nhận (AC). Một tính năng chỉ được coi là xong khi **mọi AC đều đạt** và có test tự động tương ứng (trừ AC về giao diện thì kiểm thủ công). Giai đoạn làm từng tính năng: [ke_hoach.md](ke_hoach.md) mục 5.

### F1. Cài đặt & lần chạy đầu
- **US-01:** Là người dùng mới, tôi muốn cài app và dùng được ngay mà không phải cấu hình gì.
- **AC:**
  - Bộ cài Windows ≤ 80MB, cài xong không cần khởi động lại máy; bộ cài tự tạo rule tường lửa cho mạng Private.
  - Lần chạy đầu chỉ hỏi 2 thứ: **tên thiết bị** (mặc định = tên máy) và **thư mục nhận** (mặc định = `Downloads/Teleport`), kèm câu hỏi có khởi động cùng hệ điều hành không (chỉ trên hệ điều hành hỗ trợ khởi động cùng máy, mặc định bật; ghi khi Teleport đã chạy được). Màn hình: mục 7.6.
  - Ngay dưới ô tên thiết bị có dòng: “Tên này hiện với mọi máy trong cùng mạng, kể cả máy lạ chưa ghép đôi. Nếu không muốn lộ tên mình, hãy đặt tên khác.” Muốn ẩn máy này khỏi máy chưa ghép đôi thì dùng công tắc ở F10; những gì máy này để lộ: mục 11.
  - Từ lúc mở bộ cài tới lúc gửi xong file đầu tiên mất < 2 phút với người chưa từng dùng.

### F2. Radar khám phá thiết bị
- **US-02:** Tôi muốn thấy các máy đang mở Teleport trong cùng mạng mà không phải gõ IP.
- **US-03:** Khi mạng chặn mDNS, tôi vẫn muốn kết nối bằng cách nhập IP.
- **AC:**
  - Thiết bị mới xuất hiện trên radar trong < 3 giây; thiết bị thoát app biến mất trong < 10 giây; thiết bị mất mạng đột ngột hoặc ngủ biến mất trong < 2 phút.
  - Mỗi thiết bị hiển thị tên, biểu tượng loại máy chung (không dùng logo hệ điều hành), hệ điều hành bằng chữ và trạng thái. Trạng thái trên màn “Tìm máy mới”: đã ghép đôi / chưa ghép đôi. Ở danh sách cuộc trò chuyện: trực tuyến / ngoại tuyến / đang bận (còn lượt chưa xong với máy đó, hiện cụ thể như “Đang gửi · 62%”); hệ điều hành hiện ở dòng phụ khi chưa có hoạt động nào với máy đó, và luôn có ở chú thích. Trạng thái luôn có chữ, không chỉ màu.
  - Ô nhập IP luôn có trên màn hình radar (“Tìm máy mới”).
  - Máy đã ghép đôi tự nối lại tới địa chỉ kết nối được gần nhất khi mạng chặn mDNS (sau khởi động lại hay mất kết nối), không phải nhập lại IP, nếu địa chỉ của máy đó không đổi.
  - Thấy thiết bị qua mDNS mà không kết nối được → báo lỗi “Wi-Fi chặn thiết bị” (mục 8).

### F3. Ghép đôi
- **US-04:** Lần đầu gửi tới một máy, tôi muốn chắc chắn mình đang gửi đúng máy, không phải kẻ giả mạo.
- **US-05:** Tôi muốn hủy ghép đôi một thiết bị không còn tin tưởng.
- **AC:**
  - Bấm vào thiết bị chưa ghép đôi → hai máy cùng hiện **mã 6 số**; người dùng xác nhận trùng khớp ở **cả hai máy** thì mới ghép đôi xong. Không xác nhận trong 60 giây thì phiên ghép đôi tự hủy.
  - Kẻ đứng giữa không thể chuẩn bị trước để ra mã trùng: mỗi lần thử giả mạo chỉ có xác suất trúng 1/1.000.000.
  - Sau khi ghép đôi, hai máy tự nhận ra nhau sau khi khởi động lại, không hỏi lại.
  - Máy chưa ghép đôi không thể gửi file hay clipboard tới máy này, theo cả hai chiều.
  - Chứng chỉ của một thiết bị đã ghép đôi bị thay đổi → chặn kết nối và cảnh báo (mục 8).
  - Có danh sách “Thiết bị tin cậy” trong cài đặt, có nút hủy ghép đôi. Hủy ghép đôi có hiệu lực ngay: kết nối đang mở với máy đó bị đóng; máy đó thấy thông báo “từ chối kết nối từ máy này” (mục 8).
  - Máy đã ghép đôi cài lại Teleport hiện như một thiết bị mới chưa ghép đôi; app gợi ý ghép đôi lại và đề nghị xóa mục cũ trùng tên (mục 8).
  - Máy này nhận yêu cầu ghép đôi từ máy khác khi:
    - giao diện, máy này đang *hiện* (F10): luôn nhận;
    - giao diện, máy này đang *ẩn* (F10): chỉ trong lúc mở màn hình “Chờ ghép đôi” (nút “Chờ ghép đôi” ở màn Tìm máy mới, mục 7.1, 7.5); đóng màn hình thì thôi nhận;
    - CLI: chỉ trong lúc chạy `teleport listen`.

    Màn hình “Chờ ghép đôi” **đang mở** khi nó là trang đang hiện của cửa sổ Teleport và cửa sổ đang hiện; thu nhỏ cửa sổ vẫn tính là mở. Đóng cửa sổ xuống khay hay chuyển sang trang khác là đóng; hiện lại cửa sổ khi màn hình đó vẫn là trang đang hiện thì mở lại. Không có hạn tự đóng.

    Mở màn hình “Chờ ghép đôi” hoặc chạy `teleport listen` gọi là **chế độ chờ ghép đôi**. Ngoài các trường hợp trên, máy gửi yêu cầu thấy “chưa sẵn sàng ghép đôi” (mục 8).

    Đóng màn hình “Chờ ghép đôi” hay chuyển sang ẩn không hủy phiên ghép đôi đã nhận (kể cả phiên chưa hiện mã); chỉ yêu cầu mới bị từ chối.
  - Hạn chế máy lạ làm phiền: chỉ một phiên ghép đôi tại một thời điểm; sau mỗi lần từ chối hay hết giờ, máy đó phải chờ lâu dần (10 giây, 20 giây… tối đa 10 phút) mới gửi được yêu cầu mới. Đây là mức tốt nhất có thể trong LAN, không chống được máy cố tình đổi địa chỉ liên tục; ghép đôi vẫn an toàn vì cần xác nhận mã ở cả hai máy.
  - Khi nhận yêu cầu ghép đôi, máy này hiện tối đa **5 mã mỗi phút** (gộp mọi máy gửi yêu cầu); quá thì yêu cầu mới nhận “chưa sẵn sàng ghép đôi” (mục 8). Từ mã thứ **3** trong 1 phút, máy này cảnh báo có thể có người đang thử giả mạo (mục 8). Nhờ vậy kẻ đứng giữa chỉ thử được vài mã trong lúc người dùng chờ xác nhận.
  - Không ghép đôi đè lên một thiết bị tin cậy có cùng mã thiết bị nhưng danh tính khác; phải hủy ghép đôi mục cũ trước, và khi đó cài đặt theo thiết bị cũ cũng bị xóa.
  - Ghép đôi lại với một thiết bị tin cậy (cùng mã thiết bị, cùng danh tính, ví dụ sau khi ghép đôi một phía): lời hỏi hiện thêm tên đã lưu, và tên mới nếu tên sẽ đổi (mục 7.2). Ghép đôi xong, **cả hai máy** cập nhật tên theo tên máy kia đang dùng, vì lúc ghép đôi mỗi máy đã xác minh máy kia giữ đúng khóa của thiết bị đó ([protocol.md](protocol.md) mục 5.1, 5.5). Máy lạ chỉ có chứng chỉ công khai của thiết bị đó thì bị chặn trước khi hiện mã.
  - Máy đã ghép đôi đổi tên (F10): máy này cập nhật tên đã lưu ở lần kết nối kế tiếp với máy đó, không hỏi lại. Kết nối giữa hai máy đã ghép đôi xác thực cả hai bên bằng chứng chỉ đã lưu, nên chỉ chính máy đó đổi được tên của nó; máy lạ hay bản quảng bá trên mạng không đổi được ([protocol.md](protocol.md) mục 5.5).

### F4. Gửi file
- **US-06:** Tôi muốn kéo một hoặc nhiều file thả lên máy ở cột trái để gửi.
- **US-07:** Là người nhận, tôi muốn biết ai gửi gì và được quyền từ chối.
- **AC:**
  - Kéo thả (lên một máy ở cột trái, hay vào luồng của máy đang mở), hoặc “Gửi file” (nút ở thanh dưới luồng của máy đang chọn, phím Ctrl+O, hay chuột phải vào thiết bị → “Gửi file…”), đều được; hỗ trợ chọn nhiều file. Chép file trong File Explorer (macOS: Finder) rồi nhấn Ctrl+V trong cửa sổ chính khi đang mở luồng của một máy cũng gửi ngay như thả file, không hỏi lại; chỉ gửi bản sao, kể cả khi chép bằng “Cắt”; Ctrl+V trong ô nhập chữ vẫn dán chữ như thường; clipboard không phải file thì không gửi gì (mục 8). Enter hay bấm đúp một máy ở cột trái mở cuộc trò chuyện với máy đó (tiêu điểm tới nút “Gửi file”).
  - Mỗi file tối đa 4 TB (2⁴² byte, [protocol.md](protocol.md) mục 3.3). File lớn hơn bị chặn ngay lúc chọn, trước khi gửi gì cho máy kia (mục 8).
  - Máy nhận hiện hộp thoại: tên người gửi, danh sách file, tổng dung lượng, nút **Nhận** / **Từ chối**; hoặc, khi đang mở đúng cuộc trò chuyện với máy gửi, một bong bóng lời mời có cùng các nút; trả lời ở một chỗ thì chỗ kia đóng (mục 7.3). Có tùy chọn “Luôn nhận từ thiết bị này” (tương đương tắt “Hỏi trước khi nhận” của thiết bị đó trong cài đặt).
  - Không đủ dung lượng trống → máy nhận tự từ chối ngay, máy gửi được báo cần bao nhiêu và còn bao nhiêu.
  - Thư mục nhận nằm trên ổ không chứa được file lớn như vậy (ổ FAT32, thường là USB cũ: mỗi file phải nhỏ hơn 4 GB) → máy nhận tự từ chối ngay cả lượt gửi, không hỏi người dùng; hai máy đều được báo lý do (mục 8).
  - Trùng tên file → tự đặt `ten (1).ext`, không bao giờ ghi đè.
  - Tên file chứa `..`, đường dẫn tuyệt đối, ký tự cấm hay tên thiết bị đặc biệt của Windows (`CON`, `NUL`…) → được làm sạch, file luôn nằm trong thư mục nhận.
  - Máy gửi kiểm tên file trước khi gửi: tên chứa ký tự điều khiển (ví dụ dấu xuống dòng, hay gặp trên macOS/Linux) thì không gửi và báo người dùng đổi tên (mục 8); tên quá dài thì máy gửi tự cắt ngắn, giữ đuôi file (giới hạn: [protocol.md](protocol.md) mục 3.3), và máy nhận thấy tên đã cắt trong hộp thoại nhận.
  - File chỉ xuất hiện với tên thật **sau khi** đã kiểm tra toàn vẹn xong; trong lúc nhận, dữ liệu nằm trong thư mục tạm ẩn `.teleport` bên trong thư mục nhận.

### F5. Theo dõi & quản lý lượt truyền
- **US-08:** Tôi muốn biết đang gửi tới đâu, còn bao lâu, và hủy được khi cần.
- **AC:**
  - Mỗi lượt truyền hiển thị: % hoàn thành, tốc độ hiện tại, thời gian còn lại, trạng thái (đang xếp hàng / đang chờ chấp nhận / đang gửi / đang nối lại / đang kiểm tra / xong / lỗi / đã hủy). Mỗi chiều giữa hai máy chạy một lượt truyền tại một thời điểm; lượt khác xếp hàng.
  - Nút **Hủy** ở cả hai bên; hủy thì máy nhận xóa file tạm.
  - Nhận xong có thông báo hệ thống; bấm vào thông báo mở thư mục chứa file.
  - Lịch sử tối đa 100 lượt truyền gần nhất với mỗi thiết bị (tối đa 1000 lượt tổng), lưu trên máy; xóa được lịch sử với một thiết bị hay toàn bộ; hủy ghép đôi có hỏi xóa lịch sử với thiết bị đó.

### F6. Tự nối lại khi rớt mạng
- **US-09:** Wi-Fi chập chờn hoặc tôi gập laptop giữa chừng, tôi không muốn gửi lại từ đầu.
- **AC:**
  - Mất kết nối → trạng thái chuyển “Đang nối lại…”, tự thử lại liên tục (1s, 2s, 4s… tối đa 30s một lần) trong 24 giờ.
  - Có mạng lại → tiếp tục từ khối còn thiếu. Lượng dữ liệu gửi lại ≤ phần chưa nhận + 64 MiB.
  - Tắt hẳn app nhận (hoặc khởi động lại máy) rồi mở lại → vẫn nối lại được, cùng giới hạn gửi lại như trên.
  - File nguồn bị sửa trong lúc gián đoạn hoặc trong lúc gửi → hủy lượt truyền, báo rõ lý do.
  - Tắt app **gửi** thì lượt truyền không nối lại được: máy nhận báo “máy gửi đã hủy” và dọn file tạm.
  - Lượt quá hạn nối lại thì file tạm của nó bị xóa: ngay lúc đó nếu app nhận đang chạy, không thì ngay khi app nhận được mở lại (CLI: lần chạy `teleport receive` kế tiếp với cùng thư mục nhận). File tạm không thuộc lượt nào còn sống, bỏ dở quá 7 ngày, được tự dọn khi app nhận chạy (chỉnh được trong cài đặt).

> Vì sao là 64 MiB: khối đã nhận nhưng chưa kịp ghi bền xuống đĩa (máy nhận `fsync` mỗi 16 khối 1 MiB, cộng hàng đợi ghi và bộ đệm mạng) phải gửi lại. Xem [ke_hoach.md](ke_hoach.md) mục 3.4.

### F7. Kiểm tra toàn vẹn
- **US-10:** Tôi muốn chắc chắn file nhận được giống hệt file gốc.
- **AC:**
  - Mỗi khối 1 MiB được kiểm tra SHA-256; khối sai được gửi lại tự động.
  - Cuối lượt truyền, máy nhận **đọc lại toàn bộ file từ đĩa** và so từng khối, rồi so khớp Merkle root; khớp thì mới đổi sang tên thật.
  - Test: sửa 1 byte bất kỳ trong file tạm khi đang tạm dừng → phát hiện và gửi lại đúng khối đó.

### F8. Đồng bộ clipboard
- **US-11:** Tôi muốn copy đoạn văn hoặc ảnh chụp màn hình trên máy này rồi dán ngay trên máy kia.
- **AC:**
  - Bật/tắt riêng cho từng thiết bị đã ghép đôi; **mặc định tắt**; ghép đôi lại cũng về tắt; clipboard chỉ đi khi cả hai máy cùng bật cho nhau.
  - Văn bản tới máy kia trong < 500ms; ảnh ≤ 10MB trong < 2 giây trên Wi-Fi 5.
  - Bật hai chiều cùng lúc không gây vòng lặp vô hạn.
  - Bỏ qua nội dung mà trình quản lý mật khẩu đánh dấu nhạy cảm.
  - Có biểu tượng trên khay báo vừa nhận clipboard từ máy nào.

### F9. Khay hệ thống & chạy nền
- **US-12:** Tôi muốn app luôn sẵn sàng nhận mà không chiếm chỗ trên thanh tác vụ.
- **AC:**
  - Đóng cửa sổ thì app thu xuống khay, vẫn nhận file và clipboard.
  - Menu khay: Mở Teleport, Gửi file…, Tạm dừng nhận, Thoát.
  - Tùy chọn khởi động cùng hệ điều hành (bật nếu người dùng đồng ý ở lần chạy đầu).
  - Khi chạy nền không truyền gì: CPU ~0%, RAM < 150MB.
  - Khi đang truyền, tiêu đề cửa sổ (ví dụ “60% · ZCL Teleport”) và tooltip khay hiện % tổng của các lượt đang chạy. Số đổi theo mốc và không dồn dập, để không làm phiền trình đọc màn hình (N12).

### F10. Cài đặt
- **AC:** có đủ các mục sau, đổi xong có hiệu lực ngay:
  - Tên thiết bị · Thư mục nhận · Khởi động cùng hệ điều hành
  - Giao diện: chế độ màu (theo hệ điều hành / sáng / tối) · màu nhấn (chọn trong các màu đặt sẵn) · ngôn ngữ (F11)
  - Cho máy chưa ghép đôi thấy máy này (**mặc định bật**)
  - Theo từng thiết bị tin cậy: Hỏi trước khi nhận · Đồng bộ clipboard · Hủy ghép đôi
  - Giới hạn tốc độ gửi · Dọn file tạm sau N ngày (mặc định 7)
  - Kiểm tra cập nhật (**mặc định tắt**; có từ giai đoạn 6) · Xuất log · Phím tắt (chỉ xem, không đổi được phím)
  - “Khởi động cùng hệ điều hành” hiện có trên Windows (ẩn trên hệ điều hành chưa hỗ trợ)
- **AC của “Cho máy chưa ghép đôi thấy máy này”** (bật: máy này đang *hiện*; tắt: đang *ẩn*):
  - Tắt thì máy này ngừng quảng bá trên mạng và biến mất khỏi radar của máy khác như khi thoát app (N1). Bật lại thì máy này quảng bá lại ngay.
  - Đang ẩn, máy này vẫn thấy máy khác trên radar, vẫn tự kết nối tới thiết bị tin cậy đang hiện (và tới địa chỉ đã kết nối được gần nhất của thiết bị tin cậy, F2), và gửi/nhận file, clipboard như thường.
  - Ngay dưới công tắc có dòng: “Máy đã ghép đôi tự kết nối được khi ít nhất một trong hai máy đang hiện, hoặc khi hai máy đã từng kết nối và địa chỉ không đổi.”
  - Đang ẩn và không ở chế độ chờ ghép đôi (F3): máy chưa ghép đôi kết nối tới cổng của Teleport bị cắt ngay sau bắt tay, trước khi máy này gửi tên, phiên bản app hay hệ điều hành, trừ máy mà máy này đang chủ động ghép đôi tới ([protocol.md](protocol.md) mục 2, 8).
  - Đang ẩn vẫn ghép đôi được: máy này chủ động ghép đôi tới máy kia, hoặc mở màn hình “Chờ ghép đôi” (F3, mục 7.5) để máy kia nhập IP thủ công. Khi đang ẩn, màn hình đó có dòng: “Máy này đang ẩn nên máy kia không tự thấy. Hãy nhập IP của máy này ở máy kia.”

### F11. Đa ngôn ngữ
- **AC:** Toàn bộ chuỗi giao diện có bản Tiếng Việt và English; mặc định theo ngôn ngữ hệ điều hành; đổi ngôn ngữ không cần khởi động lại.

### F12. Dòng lệnh (CLI)
- **US-13:** Là người dùng nâng cao, tôi muốn gửi file bằng script.
- **AC:**
  - Các lệnh: `teleport list`, `teleport listen` (chờ máy khác ghép đôi), `teleport pair <thiết bị>`, `teleport unpair <thiết bị>`, `teleport send <file...> --to <thiết bị>`, `teleport receive`.
  - `<thiết bị>` là tên hoặc tiền tố `device_id` (ít nhất 4 ký tự, như `teleport list` hiện). Khớp nhiều thiết bị → báo lỗi kèm danh sách để chọn, không tự đoán. Riêng `teleport pair` còn nhận `ip` hoặc `ip:cổng`, để ghép đôi được khi mạng chặn mDNS.
  - `teleport send` chỉ gửi tới thiết bị đã ghép đôi (`--to` tìm trong thiết bị tin cậy). Khi mạng chặn mDNS: thêm `--address ip[:cổng]` (vẫn cần `--to`, để kiểm đúng danh tính máy đó). `--limit-rate R` giới hạn tốc độ gửi, tính theo byte/giây hệ nhị phân (`20M` = 20 MB/s, `512K`), tối thiểu `64K`. Một lần chạy gửi một lượt (1–1000 file, không gửi thư mục). Mất kết nối thì tự nối lại như F6. Ctrl+C hủy lượt; máy nhận được báo ngay, hoặc khi hai máy nối lại được.
  - `teleport receive` nhận file từ mọi thiết bị đã ghép đôi tới khi Ctrl+C, hỏi `[c/k]` cho từng lượt (mục 7.3); `--yes` tự nhận mọi lượt, không hỏi (cảnh báo lúc khởi động); `--dir D` đổi thư mục nhận, mặc định là thư mục nhận đã lưu trong cài đặt (giao diện), chưa có thì `Teleport` trong thư mục Tải về của hệ điều hành. Không nhận yêu cầu ghép đôi (dùng `teleport listen`). Ctrl+C tạm dừng các lượt đang nhận, không hủy; chạy lại `teleport receive` với cùng thư mục nhận thì nhận tiếp phần còn thiếu, không hỏi lại (thời hạn như F6).
  - Mã thoát khác 0 khi lỗi (0 thành công, 1 lỗi lúc chạy, 2 cú pháp lệnh sai); `send` trả 0 chỉ khi lượt gửi xong, `receive` trả 0 khi dừng bằng Ctrl+C (kể cả khi có lượt tạm dừng). Có `--json` cho đầu ra máy đọc được.

---

## 6. Luồng người dùng chính

### 6.1. Lần đầu dùng (2 máy, chưa ghép đôi)
```
Máy A: cài & mở app ──► đặt tên “Laptop-Minh” ──► thấy radar trống
Máy B: cài & mở app ──► đặt tên “PC-Nha”
Máy A: “PC-Nha” hiện trên radar (< 3s)
Máy A: kéo video.mp4 (8GB) thả vào “PC-Nha”
       └─ chưa ghép đôi ──► cả hai máy hiện mã 6 số “482 913”
          └─ người dùng xác nhận trùng ở cả hai máy ──► đã ghép đôi
Máy B: hộp thoại “Laptop-Minh muốn gửi video.mp4 (8,0 GB)” ──► Nhận
Máy A + B: thanh tiến độ, tốc độ, thời gian còn lại
Máy B: thông báo “Đã nhận video.mp4” ──► bấm để hiện file trong thư mục
```

### 6.2. Rớt mạng giữa chừng
```
Đang gửi 85% ──► Wi-Fi mất
  Hai máy: trạng thái “Đang nối lại…” (không báo lỗi, không mất tiến độ)
Wi-Fi có lại ──► tự kết nối ──► so bitfield ──► gửi tiếp phần còn thiếu
  ──► kiểm tra Merkle root ──► “Đã nhận”
```

### 6.3. Clipboard
```
Cài đặt ▸ Thiết bị tin cậy ▸ bật “Đồng bộ clipboard” ở cả hai máy
  (PC-Nha trên máy A, máy A trên PC-Nha)
Máy A: Ctrl+C một đoạn văn ──► (< 0,5s) ──► Máy B: Ctrl+V dán được
```

---

## 7. Màn hình (wireframe)

### 7.1. Cửa sổ chính — khung chat theo từng máy
```
┌─ ZCL Teleport ──────────────────────────────────────────────────────────┐
│ [▶] ZCL Teleport  [⌕] [⚙] │ (PC) PC-Nha                       [📂] [⋯]  │
│ ┌────────────────────────┐ │ ● Trực tuyến · Windows · 192.168.1.20       │
│ │(PC)● PC-Nha            │ ├─────────────────────────────────────────────┤
│ │      Đang gửi · 62%    │ │            — Đã ghép đôi · 28/10 —          │
│ └────────────────────────┘ │ ┌ anh-cuoi.zip · 1,8 GB ┐                   │
│ (Lap)● MacBook-Lan         │ │ ✓ Đã lưu · Hiện tr…  │                   │
│        Đã nhận bao-cao.pdf │ └───────────────────────┘                   │
│ (Lap)○ Ubuntu-Lab          │              ┌ phim-4k.mkv · 18 GB      ┐  │
│        Ngoại tuyến·hôm qua │              │███████░░░░ 62%       ✕   │  │
│ ＋ Ghép đôi máy mới         │              │94 MB/s · còn 1 phút      │  │
│                            │              └──────────────────────────┘  │
│                            │ ┌ PC-Nha muốn gửi 2 file (340 MB) ┐        │
│ (◆) Máy này            [⧉] │ │ [Từ chối] [Nhận]                │        │
│     Laptop-Minh            │ └─────────────────────────────────┘        │
│     Địa chỉ: 192.168.1.15  │ [Gửi file]                                 │
│     ● Sẵn sàng nhận        │                     hoặc kéo file vào đây  │
├────────────────────────────┴─────────────────────────────────────────────┤
│ ↓ Lưu vào: Downloads\Teleport                      [Mở thư mục] [Đổi…]   │
└──────────────────────────────────────────────────────────────────────────┘
```

- Cột trái là các máy đã ghép đôi (mỗi máy một cuộc trò chuyện); cuối cột là máy này, kèm địa chỉ và trạng thái.
- Cột trái sắp: máy đang truyền, rồi máy trực tuyến, rồi theo hoạt động gần nhất; mỗi hàng có trạng thái và hoạt động gần nhất; thả file lên một hàng là gửi cho máy đó; chuột phải có Gửi file…, Hủy ghép đôi….
- ⌕ mở màn “Tìm máy mới” (radar, có “Nhập IP thủ công” và “Chờ ghép đôi”).
- Chưa ghép đôi máy nào thì bên phải là “Ghép đôi máy đầu tiên”.
- Cửa sổ hẹp thì cột trái thu gọn, chỉ còn avatar (tên và trạng thái ở chú thích khi trỏ chuột).
- Bên phải là luồng của máy đang chọn: gửi đi nằm bên phải, nhận vào nằm bên trái (câu chữ của từng lượt: mục 7.3). Thanh dưới luồng có “Gửi file” (Ctrl+O) và câu “hoặc kéo file vào đây”; Ctrl+V gửi các file vừa chép trong File Explorer tới máy đang mở (F4); không gửi được cả thư mục (mục 4). Clipboard vừa nhận từ máy đó hiện thành một dòng mảnh ở cuối luồng (không phải bong bóng; mỗi luồng chỉ giữ dòng mới nhất, chỉ trong lần mở app này): “Clipboard · đã chép vào máy này” hay “Clipboard · chưa chép được vào máy này” kèm nút “Thử lại”, dòng dưới là dòng đầu của văn bản hay “Ảnh *1920* × *1080* · *2,4 MB*”. Nút gửi clipboard thủ công để sau (máy gửi chưa biết máy kia đã bật đồng bộ hay chưa). Mốc sự kiện trong luồng (“Đã ghép đôi · 28/10”, “Mất kết nối”) để sau; luồng chỉ có mốc thời gian.
- “Đổi…” ở chân cửa sổ đổi thư mục nhận chung cho mọi thiết bị; thư mục mới được lưu và dùng cho các lần mở app sau. Thư mục nhận đã lưu không mở được lúc mở app thì app vẫn chạy nhưng không nhận file: thẻ máy này ghi “Không nhận file”, chân cửa sổ nói thư mục nào hỏng và vẫn có “Đổi…” (câu chữ ở mục 8).
- Không hiện tên Wi-Fi.

Màn “Tìm máy mới”:
```
┌─ ZCL Teleport ───────────────────────────────────────────────────┐
│ [← Quay lại]  Tìm máy mới                 [ Nhập IP thủ công… ]  │
│                ·          ·          ·                           │
│   (PC) PC-Khách         ╭───╮        (PC) PC-Nha · đã ghép       │
│     Chưa ghép đôi       │ ◉ │                                    │
│                ·        ╰───╯ Bạn          (Lap) Laptop-Bảo      │
│                ·          ·          ·       Chưa ghép đôi       │
│ Đang tìm trong mạng… Bấm một máy để ghép đôi.   [ Chờ ghép đôi ] │
└──────────────────────────────────────────────────────────────────┘
```

### 7.2. Ghép đôi
```
┌─ Ghép đôi ────────────────────────────────┐
│  Hãy so mã dưới đây với mã trên màn hình  │
│  máy kia.                                 │
│                                           │
│              4 8 2   9 1 3                │
│                                           │
│  Máy kia tự xưng là “MacBook”             │
│  (mã máy 3f2a9c1e, 192.168.1.5)           │
│                                           │
│  [ Không trùng ]          [ Trùng khớp ]  │
└───────────────────────────────────────────┘
```

Tên máy kia do chính máy đó tự đặt và chưa được xác thực ([protocol.md](protocol.md) mục 3.3). Nếu tên đứng ngay trước mã, kẻ đứng giữa đặt tên kiểu `PC-A:   382 104` là hiện được một mã giả đúng chỗ người dùng nhìn. Vì vậy lời hỏi ghép đôi, ở giao diện lẫn CLI, theo đúng bố cục sau:

- Tiêu đề chỉ là “Ghép đôi”, không chứa tên máy kia.
- Mã đứng riêng và đứng **trước** mọi chữ do máy kia đặt. Giao diện: một dòng chữ lớn chỉ có mã. CLI: dòng `Mã ghép đôi:   382 104`, chỉ gồm nhãn cố định và mã. Không chữ nào do máy kia đặt được đứng trước mã hay cùng dòng với mã.
- Cảnh báo nhiều mã (mục 8), nếu có, nằm ngay dưới mã.
- Tên máy kia nằm sau mã, luôn trong ngoặc “…”, kèm mã máy (8 ký tự đầu của `device_id`) và địa chỉ:
  - dài quá **32 cột** thì bị cắt và thêm `…`, tổng vẫn ≤ 32 cột; chữ rộng (CJK, phần lớn emoji) tính 2 cột, dấu kết hợp và ZWJ (U+200D) tính 0 cột, ký tự khác 1 cột;
  - ký tự trông như khoảng trắng mà không phải dấu cách thường U+0020 được hiện thành `·`: các khoảng trắng Unicode khác (U+00A0, U+1680, U+2000–U+200A, U+202F, U+205F, U+3000) và các ký tự trống U+2800, U+3164, U+115F, U+1160, U+FFA0;
  - ký tự vô hình và ký tự đổi hướng chữ cũng hiện thành `·`: mọi ký tự định dạng (loại Cf, ví dụ RLO U+202E, LRI U+2066, PDI U+2069, LRM U+200E, RLM U+200F, U+200B), trừ ZWJ (U+200D) và ZWNJ (U+200C) mà emoji ghép và chữ Ba Tư cần, cùng U+2028, U+2029. Nhờ vậy câu đứng sau tên không bị đảo hướng hiển thị.
- Máy kia đã ghép đôi với máy này (F3, ghép đôi lại) thì hiện thêm tên đã lưu, theo cùng cách hiện tên ở trên; tên đã lưu khác tên máy kia tự xưng thì hiện thêm tên mới mà máy này sẽ lưu khi ghép đôi xong.

Bản CLI, ví dụ ở `teleport listen` với đủ các dòng tùy chọn:
```
Có yêu cầu ghép đôi. Hãy so mã dưới đây với mã trên màn hình máy kia.
Mã ghép đôi:   382 104
Cảnh báo: máy này đã hiện 3 mã ghép đôi trong 1 phút qua. Nếu bạn không tự ghép đôi nhiều lần như vậy, có thể có người đang thử giả mạo: hãy từ chối (gõ k).
Máy kia tự xưng là “MacBook Pro” (mã máy 3f2a9c1e, 192.168.1.5).
Máy này đã ghép đôi với mã máy 3f2a9c1e trước đây, tên đã lưu: “MacBook”.
Ghép đôi xong, tên sẽ đổi thành “MacBook Pro”.
Trùng khớp? [c/k]:
```

| Thứ tự | Khi nào | Dòng |
|---|---|---|
| 1 | `teleport listen` | `Có yêu cầu ghép đôi. Hãy so mã dưới đây với mã trên màn hình máy kia.` |
| 1 | `teleport pair` | `Hãy so mã dưới đây với mã trên màn hình máy kia.` |
| 2 | Luôn có | `Mã ghép đôi:   <mã>` (nhãn, ba dấu cách, mã dạng `382 104`) |
| 3 | Máy nhận yêu cầu ghép đôi đã hiện từ 3 mã trong 1 phút | Câu cảnh báo ở mục 8, giữ nguyên |
| 4 | Luôn có | `Máy kia tự xưng là “<tên>” (mã máy <mã máy>, <địa chỉ>).` |
| 5 | Máy kia đã ghép đôi (cả hai vai) | `Máy này đã ghép đôi với mã máy <mã máy> trước đây, tên đã lưu: “<tên đã lưu>”.` |
| 6 | Máy kia đã ghép đôi và tên đã lưu khác tên máy kia tự xưng | `Ghép đôi xong, tên sẽ đổi thành “<tên>”.` |
| 7 | Luôn có | `Trùng khớp? [c/k]: ` |

- `<tên>` và `<tên đã lưu>` hiện theo cách ở trên; `<mã máy>` là 8 ký tự đầu của `device_id`.
- Máy gửi yêu cầu là bên khởi xướng, máy nhận yêu cầu là bên trả lời ([protocol.md](protocol.md) mục 5.1). Thường `teleport pair` là bên khởi xướng; khi hai máy cùng ghép đôi với nhau thì một bên `teleport pair` chuyển sang vai trả lời ([protocol.md](protocol.md) mục 5.3). Vì vậy dòng 1 xét theo lệnh, còn dòng 3 xét theo vai.

Bản giao diện dùng cùng các dòng, khác ở chỗ:
- Hộp hiện ở **cả hai máy**, bất kể vai. Dòng 1 xét theo vai: bên trả lời dùng dòng 1 của `teleport listen`, bên khởi xướng dùng dòng 1 của `teleport pair`.
- Dòng 2 không có nhãn: chỉ có mã, chữ rất lớn, căn giữa. Nhãn “Mã ghép đôi” chỉ dành cho trình đọc màn hình.
- Dòng 3 là câu cảnh báo bản giao diện ở mục 8, kèm biểu tượng cảnh báo.
- Dòng 4–6 nhỏ hơn, màu dịu.
- Dòng 7 thay bằng hai nút “Không trùng” và “Trùng khớp”. Nút mặc định (Enter) là “Không trùng”; Esc hay đóng hộp cũng là “Không trùng”.
- Mã vẽ thành hai nhóm ba ô (khoảng giữa hai nhóm rộng hơn), vẫn là chữ thuần cho trình đọc màn hình.
- Dưới tên máy kia, trên hai nút: đếm ngược thời gian còn lại để xác nhận, gồm một thanh mảnh ngắn dần và chữ “Còn *43* giây để xác nhận”; từ 10 giây trở xuống chữ đổi màu cảnh báo (thanh vẫn ngắn dần, không chỉ dựa vào màu).
- Hết thời gian xác nhận thì hộp tự đóng. Phiên kết thúc vì bất kỳ lý do gì thì hộp cũng tự đóng.
- Không có cửa sổ Teleport nào đang được dùng (cửa sổ ẩn, thu nhỏ hay bị cửa sổ khác che) thì hiện thêm bóng thoại ở khay (mục 8).

### 7.3. Có file gửi tới
```
┌─ Laptop-Minh muốn gửi 3 file (8,4 GB) ────┐
│   video.mp4        8,0 GB                 │
│   thumbnail.png    2,1 MB                 │
│   script.docx      380 KB                 │
│  Lưu vào: D:\Downloads\Teleport  [Đổi…]   │
│  ☐ Luôn nhận từ thiết bị này              │
│        [ Từ chối ]            [ Nhận ]    │
└───────────────────────────────────────────┘
```

“Đổi…” đổi thư mục nhận **chung** cho mọi thiết bị (như trong Cài đặt), không riêng lượt này, và chỉ được khi chưa có lượt nhận nào đã chấp nhận. Đổi xong thì mọi hộp đang mở được kiểm lại chỗ trống trên thư mục mới: không đủ chỗ thì lượt đó bị từ chối và hộp tự đóng; bấm Nhận trong lúc đang kiểm lại thì lượt được nhận ngay khi kiểm xong mà đủ chỗ.

Tên file do máy gửi đặt (đã làm sạch, [ke_hoach.md](ke_hoach.md) mục 3.3) hiện như tên máy ở mục 7.2 (ký tự trông như khoảng trắng, ký tự vô hình và ký tự đổi hướng chữ thành `·`, chữ rộng 2 cột, dấu kết hợp và ZWJ 0 cột) nhưng tối đa **48 cột**, và dài hơn thì **cắt ở giữa, giữ đuôi** (`ten-rat-dai…cuoi.mp4`), để phần mở rộng vẫn còn thấy. Tên máy gửi theo mục 7.2. Máy gửi không có tên (không còn trong thiết bị tin cậy) thì hiện 8 ký tự đầu của mã máy.

Bản giao diện: dòng đầu là ““*Laptop-Minh*” muốn gửi *3* file (*8,4 GB*) tới máy này.” (chữ lớn, đậm), rồi các dòng file như bản CLI dưới đây, “Lưu vào: …” kèm “Đổi…”, ô “Luôn nhận từ thiết bị này” và hai nút. Mỗi lượt một hộp, không chặn cửa sổ chính; Enter, Esc và nút đóng hộp đều là **Từ chối**; máy gửi hủy (hay lượt kết thúc vì lý do khác) khi hộp còn mở thì hộp tự đóng.
- **Hộp hay bong bóng:** lời mời luôn có một bong bóng có nút Nhận / Từ chối trong luồng của máy gửi. Hộp chỉ **không** bật khi người dùng đang thấy đúng chỗ đó: cửa sổ chính đang được dùng, không thu nhỏ, đang mở cuộc trò chuyện với máy gửi và luồng đang ở cuối. Còn lại (cửa sổ ẩn hay thu nhỏ, đang ở trang khác, đang mở máy khác, đang cuộn lên đọc) thì bật hộp. Ẩn hay thu nhỏ cửa sổ khi còn lời mời chỉ có bong bóng thì bật hộp cho lời mời đó. Mỗi lời mời chỉ có một câu trả lời: trả lời ở hộp thì bong bóng thôi hỏi và ngược lại.
- Tối đa 3 hộp mở cùng lúc; lời mời tới sau xếp hàng và hộp của nó mở khi một hộp đóng.
- Đang đổi thư mục nhận thì “Nhận” tạm tắt (“Chờ đổi thư mục nhận xong”), “Từ chối” vẫn bấm được; đổi xong thì bật lại. Đổi không được thì câu lỗi hiện ngay dưới dòng “Lưu vào”.
- Máy gửi mất kết nối khi lời mời còn chờ: thêm dòng “Mất kết nối với *Laptop-Minh*. Bạn vẫn trả lời được; nếu nhận, file sẽ bắt đầu khi hai máy nối lại.”; nối lại thì dòng đó mất.
- “Luôn nhận từ thiết bị này” chỉ có hiệu lực khi bấm **Nhận**: lượt này được nhận và các lượt sau từ máy đó tự nhận (tắt “Hỏi trước khi nhận”, mục 7.4). Bấm Từ chối thì ô tick bị bỏ qua. Các lời mời khác đang chờ từ máy đó vẫn chờ trả lời.

Luồng của mỗi máy (khung bên phải của cửa sổ chính, mục 7.1) có một bong bóng cho mỗi lượt với máy đó: gửi đi bên phải, nhận vào bên trái, cũ ở trên, mới ở dưới; giữa hai bong bóng cách nhau từ 60 phút hay khác ngày có dòng mốc giờ (“Hôm nay 10:40”, “Hôm qua 21:03”, “28/10 21:03”). Luồng gồm các lượt trong lần mở app này và lịch sử với máy đó (F5, đọc lại mỗi lần mở cuộc trò chuyện). Đang cuộn lên mà có lượt mới thì hiện nút “↓ Mới”. Máy chưa có lượt nào thì luồng ghi “Kéo file vào đây để gửi cho *PC-Nha*”. Mỗi bong bóng:
- Dòng 1: biểu tượng loại file, “*video.mp4*” (nhiều file: “*3* file”), cỡ (“*8,0 GB*”; mục lịch sử thêm giờ: “*8,0 GB* · 21:03”) và nút “Hủy” khi chưa xong. Không ghi tên máy kia (luồng đã thuộc một máy).
- Dòng 2: thanh tiến độ, chỉ khi lượt chưa kết thúc.
- Dòng 3: nhãn ngắn (“Đang gửi”, “Đang nhận”, “Đang chờ”, “Đang kiểm tra”, “Đang nối lại…”, “Đã lưu” (nhận xong), “Đã gửi” (gửi xong), “Đã từ chối”, “Đã hủy”, “Lỗi”) và một dòng phụ: khi đang truyền “*45,0*% · *120 MB/s* · còn *2 phút*” (phần trăm làm tròn xuống, chưa xong thì không hiện 100%; chưa đo được tốc độ thì bỏ phần tốc độ và thay “còn …” bằng “đang tính thời gian còn lại”; đang nối lại hay chờ dữ liệu thì câu ở mục 8); khi chờ thì câu chờ như bản CLI ở bảng dưới (máy nhận: “Đang chờ bạn trả lời” hoặc “Đang xếp hàng”); khi xong “Đã kiểm tra toàn vẹn” (bên nhận mà file phải lưu tên khác vì đã có file trùng tên: “Đã lưu thành *video-demo (1).mp4* · Đã kiểm tra toàn vẹn”; từ hai file đổi tên: “Đã lưu *2* file với tên mới · Đã kiểm tra toàn vẹn”); khi dừng vì lỗi thì câu của mục 8. Lỗi có viền màu nhấn đỏ kèm biểu tượng cảnh báo (không chỉ bằng màu); xong có dấu ✓.
- Dòng 4: “Hiện trong thư mục” (bên nhận đã xong; mở thư mục và chọn sẵn file vừa nhận); “Gửi lại” (bên gửi kết thúc không thành, trừ khi hủy ghép đôi; chỉ trong lần mở app này, bấm được một lần).
- Vừa chọn file xong mà lượt chưa bắt đầu: bong bóng tạm “Đang chuẩn bị…”.
- Lời mời nhận file đang chờ trả lời: bong bóng có viền màu nhấn, nhãn “Đang chờ” và “Đang chờ bạn trả lời”, danh sách tên file (khi nhiều file), “Lưu vào: …” kèm “Đổi…”, ô “Luôn nhận từ thiết bị này” và hai nút **Từ chối** / **Nhận**; không có nút “Hủy” (từ chối là cách duy nhất để không nhận). Trả lời xong (ở đây hay ở hộp) thì các nút biến mất và bong bóng đi tiếp như lượt thường.

Bản CLI (`teleport receive`), mỗi lần một lời hỏi; lượt tới sau xếp hàng tới khi lời hỏi trước được trả lời. Tối đa 10 dòng file, còn lại gộp thành một dòng; cột dung lượng thẳng hàng:
```
“Laptop-Minh” muốn gửi 3 file (8,4 GB):
  video.mp4        8,0 GB
  thumbnail.png    2,1 MB
  script.docx      380 KB
Lưu vào: D:\Downloads\Teleport
Nhận? [c/k]:
```
- Hơn 10 file: dòng thứ 11 là `  … và 990 file khác`.
- Trả lời: `c` (nhận), `k` (từ chối, in “Đã từ chối.”); gõ khác thì “Hãy gõ c (nhận) hoặc k (từ chối).” rồi hỏi lại. Dòng gõ trước lúc hiện lời hỏi bị bỏ. Đầu vào đóng (không đọc được câu trả lời) thì từ chối lượt đang hỏi và mọi lượt sau (mục 8). Không có hạn chờ trả lời.
- `--yes`: không hỏi; vẫn in các dòng trên, trừ dòng `Nhận? [c/k]:`.

Các dòng khác của `teleport receive` / `teleport send` (*nghiêng* là chỗ điền):

| Khi nào | Dòng |
|---|---|
| `receive` khởi động | “Teleport đang chờ nhận file.” / “  Tên:      *X*” / “  Mã máy:   *a71c04d2*” / “  Lưu vào:  *D:\Downloads\Teleport*”, các cảnh báo (mục 8), rồi “Nhấn Ctrl+C để dừng.”; có lượt nhận dở thì sau đó mỗi lượt một dòng (mục 8, dòng “CLI: `receive` mở lại khi có lượt nhận dở”) |
| `send` khởi động | “Đang tìm “*PC-Nha*” trong mạng…” hoặc “Đang kết nối tới “*PC-Nha*” tại *192.168.1.5:47474*…”; có `--limit-rate`: “Giới hạn tốc độ gửi: *20 MB/s*.” |
| `send` đã kết nối | “Đã kết nối với “*PC-Nha*”. Gửi *3* file (*8,4 GB*).” |
| `send` chờ máy nhận trả lời | “Đang chờ *PC-Nha* trả lời…” |
| `send` chờ máy nhận xong lượt trước | “Đang chờ *PC-Nha* nhận xong lượt trước…” |
| Mất kết nối giữa lượt | “Đang nối lại…” |
| Đang kiểm tra toàn vẹn một file | “Đang kiểm tra *video.mp4*…” |
| Tiến độ (mỗi giây; không phải terminal thì mỗi 10 giây) | “  *42,0*% · *3,4 GB* / *8,4 GB* · *85,2 MB/s* · còn *1 phút 2 giây* · *video.mp4* (*1*/*3*)” (thụt hai dấu cách đầu dòng); chưa đo được tốc độ thì thay “còn …” bằng “đang tính thời gian còn lại”; `receive` thêm “*Laptop-Minh*: ” sau hai dấu cách đó |
| `send`: một file xong | “Đã gửi *video.mp4* (*1*/*3*).” |
| `send`: cả lượt xong | “Đã gửi xong *3* file (*8,4 GB*) tới *PC-Nha*.” |
| `receive`: một file xong | “Đã lưu: *D:\…\video (1).mp4*” |
| `receive`: cả lượt xong | “Đã nhận xong *3* file (*8,4 GB*) từ *Laptop-Minh*.” |
| Ctrl+C lần đầu | “Đang dừng… (nhấn Ctrl+C lần nữa để thoát ngay)”; `receive` in câu tạm dừng cho mỗi lượt đang nhận (mục 8, dòng “CLI: `receive` dừng (Ctrl+C) khi đang nhận”); `receive` dừng xong in “Đã dừng.”, `send` dừng trước khi có lượt in “Đã hủy.” |

Trên terminal, dòng tiến độ được vẽ lại tại chỗ, cắt vừa bề ngang và không vẽ khi đang có lời hỏi.

### 7.4. Cài đặt ▸ Thiết bị tin cậy
```
┌─ Thiết bị tin cậy ──────────────────────────────────────────────────┐
│ PC-Nha    Windows  ☑ Hỏi trước khi nhận  ☑ Clipboard   [ Hủy ghép ] │
│ MacBook   macOS    ☑ Hỏi trước khi nhận  ☐ Clipboard   [ Hủy ghép ] │
└─────────────────────────────────────────────────────────────────────┘
```
Ô thứ hai là “Đồng bộ clipboard” (mặc định tắt). Câu đầu mục: “Các máy đã ghép đôi với máy này. Bỏ chọn
“Hỏi trước khi nhận” để tự nhận file từ máy đó. Clipboard chỉ đồng bộ khi cả hai máy cùng bật “Đồng bộ
clipboard”; mật khẩu chép từ trình quản lý mật khẩu không được gửi.”

### 7.5. Chờ ghép đôi
```
┌─ Chờ ghép đôi ────────────────────────────┐
│  Đang chờ máy khác gửi yêu cầu ghép đôi.  │
│                                           │
│  Tên:      Laptop-Minh                    │
│  Mã máy:   a71c04d2                       │
│  Địa chỉ:  192.168.1.20         [ Chép ]  │
│                                           │
│  Máy này đang ẩn nên máy kia không tự     │
│  thấy. Hãy nhập IP của máy này ở máy kia. │
│                                           │
│                                 [ Đóng ]  │
└───────────────────────────────────────────┘
```
- Mở bằng nút “Chờ ghép đôi” ở màn Tìm máy mới (mục 7.1); máy này nhận yêu cầu ghép đôi thế nào khi màn hình mở hay đóng: F3.
- “Đang chờ máy khác gửi yêu cầu ghép đôi.” chỉ hiện khi chế độ chờ ghép đôi đã mở được; không mở được thì hiện câu lỗi ở mục 8.
- “Địa chỉ”: mọi địa chỉ IPv4 của máy này, kèm `:cổng` khi cổng khác cổng mặc định (protocol mục 2), giống `teleport listen`. Mỗi địa chỉ một hàng, có nút “Chép” chép đúng chuỗi đó. Chưa đọc xong: “Đang lấy địa chỉ…”; đọc xong mà không có địa chỉ nào: câu ở mục 8.
- Hai dòng “Máy này đang ẩn…” chỉ hiện khi máy này đang ẩn (F10).
- Có yêu cầu ghép đôi thì lời hỏi hiện theo mục 7.2.

### 7.6. Lần chạy đầu
```
┌─ ZCL Teleport ────────────────────────────────────┐
│                                                   │
│               (logo) ZCL Teleport                 │
│                                                   │
│  Gửi file lớn giữa các máy trong cùng mạng.       │
│  Không qua cloud.                                 │
│                                                   │
│  (i) Không tài khoản, không máy chủ trung gian    │
│  (i) Mã hóa đầu cuối giữa hai máy                 │
│  (i) Tự nối lại khi rớt mạng, không phải gửi      │
│      lại từ đầu                                   │
│                                                   │
│  Tên thiết bị                                     │
│  [ Laptop-Minh                               ]    │
│  (dòng ngay dưới ô tên thiết bị ở F1)             │
│                                                   │
│  Thư mục nhận file                                │
│  C:\Users\Minh\Downloads\Teleport     [ Đổi… ]    │
│                                                   │
│  Khởi động cùng Windows             [ Bật ━● ]    │
│  Teleport chạy ẩn ở khay hệ thống từ khi bạn      │
│  đăng nhập Windows, để luôn sẵn sàng nhận file.   │
│                                                   │
│  Bấm Bắt đầu để Teleport chạy và hiện máy này     │
│  với các máy khác trong mạng.                     │
│                                                   │
│                 [   Bắt đầu   ]                   │
│                                                   │
└───────────────────────────────────────────────────┘
```
- Hiện khi mở giao diện mà máy chưa có danh tính, kể cả khi mở bằng `--background` (cửa sổ vẫn hiện). Máy đã có danh tính (từ CLI hay từ bản trước) không bao giờ hiện màn này.
- Chưa bấm “Bắt đầu” thì Teleport không chạy, không quảng bá và chưa tạo danh tính.
- “(i)” là biểu tượng trang trí của từng ý; mọi trạng thái và lỗi trên màn đều có chữ, không chỉ dùng màu (N12).
- **Tên thiết bị:** điền sẵn tên đã lưu, chưa có thì tên máy (F1). Tên máy không dùng được làm tên thiết bị (rỗng, quá dài, có ký tự điều khiển) thì ô để trống, có chữ mờ “Ví dụ: Laptop-Minh”, và người dùng phải gõ tên. Tên được kiểm khi bấm “Bắt đầu”, khi nhấn Enter trong ô (Enter trong ô làm như bấm “Bắt đầu”) và khi rời ô đã sửa; lỗi “rỗng” chỉ hiện khi bấm “Bắt đầu” hay nhấn Enter. Lỗi hiện ngay dưới ô (mục 8), tiêu điểm về ô, gõ tiếp thì lỗi ẩn. Tên để nguyên như gợi ý thì không ghi vào cài đặt; tên đã sửa được lưu trước khi máy này quảng bá.
- **Thư mục nhận:** hiện thư mục đã lưu, chưa có thì thư mục mặc định (F1); đường dẫn dài thì cắt ở giữa, đầy đủ ở chú thích. “Đổi…” mở hộp chọn thư mục. Thư mục riêng của Teleport bị từ chối ngay lúc chọn; thư mục đã chọn mà lúc bấm “Bắt đầu” không dùng được thì màn quay lại đây, giữ tên đã gõ, tiêu điểm ở “Đổi…”. Cả hai lỗi hiện ngay dưới hàng thư mục (mục 8).
- **Khởi động cùng Windows:** hàng chỉ hiện trên hệ điều hành hỗ trợ (F10). Công tắc bật sẵn, trừ khi Teleport đang được đặt khởi động từ bản khác hay Windows đang tắt Teleport trong danh sách ứng dụng khởi động: khi đó công tắc tắt sẵn và dưới hàng có câu tương ứng của dòng “Giao diện, Cài đặt: khởi động cùng Windows” (mục 8). Lựa chọn chỉ được ghi khi Teleport đã chạy được, không ghi lúc bấm. Công tắc tắt thì chỉ gỡ khởi động cùng Windows đang bật cho chính bản này; bản khác và lựa chọn tắt trong danh sách ứng dụng khởi động của Windows giữ nguyên. Bật không được thì Teleport vẫn chạy và báo (mục 8); đổi lại trong Cài đặt.
- Bấm “Bắt đầu” (tên hợp lệ) thì màn chuyển sang “Đang khởi động…”. Khởi động lỗi (trừ lỗi thư mục đã chọn ở trên) thì hiện câu của dòng “Giao diện: … khi khởi động” tương ứng ở mục 8 với nút “Thử lại”; “Thử lại” dùng lại đúng tên, thư mục và lựa chọn đã chọn.
- Lỗi khởi động đến sau khi danh tính đã được tạo (ví dụ thư mục đã chọn không dùng được): tên đã sửa đã được lưu, thư mục không dùng được thì không lưu. Người dùng thoát app thay vì sửa rồi bấm lại thì lần mở sau không hiện màn này nữa: Teleport dùng thư mục đã lưu hay mặc định, lựa chọn khởi động cùng Windows bị bỏ; đổi lại trong Cài đặt.
- Bàn phím: tiêu điểm đầu ở ô tên (có lỗi thư mục thì ở “Đổi…”); Tab theo thứ tự ô tên → “Đổi…” → công tắc (khi hiện) → “Bắt đầu”; Space bật/tắt công tắc.

---

## 8. Thông báo lỗi & tình huống đặc biệt

Nguyên tắc: nói **chuyện gì xảy ra** và **người dùng nên làm gì**, không dùng thuật ngữ kỹ thuật.

Nút “Gửi lại” ở cột cuối (giao diện: trong phiên): chỉ có trên bong bóng của lượt gửi trong lần mở app này, không có trên mục lịch sử.

Dung lượng hiển thị cho người dùng tính theo hệ nhị phân, như Windows Explorer: 1 KB = 1024 byte, 1 MB = 1024 KB, 1 GB = 1024 MB, 1 TB = 1024 GB. Mọi con số trong app (thông báo, tiến độ, giới hạn) dùng cùng cách tính này.

| Tình huống | Thông báo | Hành động gợi ý |
|---|---|---|
| Không thấy thiết bị nào | Giao diện: “Chưa thấy thiết bị nào. Hãy mở Teleport trên máy kia, kiểm tra hai máy dùng chung một mạng Wi-Fi và tường lửa của Windows cho phép Teleport.” CLI: “Chưa thấy thiết bị nào. Hãy mở Teleport trên máy kia và kiểm tra hai máy dùng chung một mạng Wi-Fi.” | Nút “Nhập IP thủ công” |
| Trang “Tìm máy mới” có máy trong mạng | Giao diện: “Bấm vào một máy để ghép đôi. Máy đã ghép đôi hiện mờ.” | Bấm vào máy để ghép đôi |
| Thấy nhưng không kết nối được (cô lập thiết bị) | “Thấy *PC-Nha* nhưng không kết nối được. Mạng Wi-Fi này có thể đang chặn các thiết bị nói chuyện với nhau (hay gặp ở quán cà phê, khách sạn).” Giao diện thêm câu: “Hãy thử dùng điểm phát Wi-Fi từ điện thoại.” | Gợi ý dùng hotspot điện thoại |
| Tường lửa chặn | “Tường lửa của Windows đang chặn Teleport nhận kết nối.” (máy bị chặn tự phát hiện và hiện; nếu chiều ngược lại vẫn kết nối được thì Teleport vẫn chạy, chỉ hiện gợi ý) | Nút “Mở hướng dẫn” |
| Không mở được kết nối truyền dữ liệu tới máy kia nhiều lần liên tiếp (máy mở kết nối báo) | “Không mở được kết nối truyền dữ liệu tới *PC-Nha*; tường lửa trên máy đó có thể đang chặn Teleport. Teleport vẫn đang thử lại.” | Tự thử lại |
| macOS chưa cho quyền mạng cục bộ | “Teleport chưa được phép dùng mạng cục bộ nên không thấy máy khác.” | Nút “Mở Cài đặt hệ thống” |
| Không đủ dung lượng | Máy nhận: “Đã từ chối *3* file từ *Laptop-Minh*: không đủ chỗ trống, cần *12,4 GB*, *ổ D:* còn *8,1 GB*.” Máy gửi: “*PC-Nha* không đủ chỗ trống để nhận: cần *12,4 GB*, ổ lưu file trên máy đó còn *8,1 GB*.” | Máy nhận: nút “Đổi thư mục nhận” |
| Thư mục nhận nằm trên ổ không chứa được file lớn như vậy (FAT32: mỗi file phải nhỏ hơn 4 GB) | Máy nhận: “Đã từ chối 3 file từ *Laptop-Minh*: ổ *E:* chỉ chứa được file nhỏ hơn 4 GB, mà *video.mp4* nặng 8,0 GB.” Máy gửi: “*PC-Nha* không nhận được *video.mp4* (8,0 GB): ổ lưu file trên máy đó chỉ chứa được file nhỏ hơn 4 GB.” | Máy nhận: nút “Đổi thư mục nhận” (chọn ổ khác). Máy gửi: nút “Gửi lại” sau khi máy kia đổi thư mục nhận |
| Cách gọi ổ của thư mục nhận trong hai câu trên | Windows: “ổ *D:*”; ổ mạng Windows: “ổ mạng *\\máy\chia-sẻ*”; macOS, Linux: “ổ chứa */home/minh/Downloads/Teleport*” | — |
| Danh tính thiết bị thay đổi (cùng mã thiết bị, khác chứng chỉ), khi máy này kết nối hoặc gửi yêu cầu ghép đôi tới máy đó | “*PC-Nha* đang dùng một danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy này. Kết nối đã bị chặn.” | Không cho ghép đôi đè; nút “Hủy ghép đôi *PC-Nha*” (kèm cảnh báo), sau đó mới ghép đôi lại được |
| Một máy gửi yêu cầu ghép đôi tới máy này, tự xưng là một thiết bị đã ghép đôi (cùng mã thiết bị) nhưng dùng danh tính khác | “Một máy chưa xác minh tự xưng là *PC-Nha* nhưng dùng danh tính khác với lúc ghép đôi. Có thể có người đang giả mạo máy đó. Yêu cầu ghép đôi đã bị chặn.” | Không gợi ý hủy ghép đôi: máy thật có thể không liên quan |
| Máy đã ghép đôi cài lại Teleport | “Có một *PC-Nha* mới chưa ghép đôi. Nếu máy đó vừa cài lại Teleport, hãy ghép đôi lại.” | Nút “Ghép đôi”; ghép xong thì hỏi xóa mục *PC-Nha* cũ |
| Máy kia từ chối máy này | “*PC-Nha* từ chối kết nối từ máy này. Có thể máy đó đã hủy ghép đôi.” | Nút “Ghép đôi lại” |
| Máy kia chưa sẵn sàng ghép đôi | Giao diện: “*PC-Nha* đang bận hoặc vừa có một lần ghép đôi không thành. Hãy chờ một lát rồi thử lại.” CLI: “*PC-Nha* chưa sẵn sàng ghép đôi: máy đó đang ẩn, đang ghép đôi với máy khác, chưa mở chế độ chờ ghép đôi, hoặc cần chờ một lát sau lần thử trước. Hãy thử lại sau.” (chưa biết tên thì hiện IP, ví dụ *192.168.1.5*) | Nút “Thử lại”; CLI gợi ý `teleport listen` |
| Nhập IP thủ công nhưng không kết nối được | “Không kết nối được tới *192.168.1.5:47474*. Hãy kiểm tra Teleport đang chạy trên máy đó, hai máy dùng chung một mạng, và tường lửa cho phép Teleport.” | Nút “Thử lại” |
| Thiết bị trả lời bằng danh tính không hợp lệ khi ghép đôi | “Thiết bị ở *192.168.1.5:47474* gửi danh tính không hợp lệ nên kết nối đã bị chặn. Có thể có người đang giả mạo.” | — |
| Ghép đôi với chính máy này | “Đó là chính máy này. Hãy nhập địa chỉ của máy kia.” | — |
| Danh tính của chính máy này bị hỏng | “Không đọc được danh tính của máy này. Teleport sẽ không tự tạo danh tính mới để khỏi mất các ghép đôi.” | Nút “Tạo danh tính mới” (cảnh báo phải ghép đôi lại) |
| Mã ghép đôi không trùng / hết giờ (sau khi đã hiện mã) | “Ghép đôi với *MacBook* chưa xong. Nếu mã trên hai máy khác nhau, có thể có người đang giả mạo.” | Nút “Thử lại” (chỉ ở máy gửi yêu cầu ghép đôi; giao diện chọn sẵn nút “Đóng”) |
| Phiên ghép đôi dừng trước khi hiện mã (máy kia ngắt kết nối, gửi dữ liệu sai hoặc quá hạn chờ) | Máy gửi yêu cầu ghép đôi: “Ghép đôi với *MacBook* chưa xong vì phiên dừng trước khi hiện mã. Hãy thử lại.” Máy nhận yêu cầu ghép đôi (CLI; giao diện: dòng “Giao diện: phiên ghép đôi do máy khác gửi tới dừng trước khi hiện mã”): “Một máy tự xưng là *MacBook* đã yêu cầu ghép đôi nhưng phiên dừng trước khi hiện mã.” | Máy gửi yêu cầu: nút “Thử lại”. Máy nhận yêu cầu: không cần làm gì |
| Máy nhận yêu cầu ghép đôi đã hiện từ 3 mã trở lên trong 1 phút | “Cảnh báo: máy này đã hiện *3* mã ghép đôi trong 1 phút qua. Nếu bạn không tự ghép đôi nhiều lần như vậy, có thể có người đang thử giả mạo: hãy từ chối (gõ k).” | Hiện ngay dưới mã; từ chối nếu không tự ghép đôi. Câu trên là bản CLI; giao diện thay “hãy từ chối (gõ k)” bằng “hãy bấm “Không trùng”” |
| Không hiện được mã ghép đôi (giao diện lỗi) | “Không hiện được mã ghép đôi trên máy này nên đã hủy ghép đôi. Hãy thử lại.” | Nút “Thử lại” (chỉ ở máy gửi yêu cầu ghép đôi) |
| Khác phiên bản giao thức | “*PC-Nha* đang dùng phiên bản Teleport khác. Hãy cập nhật cả hai máy lên cùng phiên bản.” | — |
| Chọn gửi file lớn hơn 4 TB | “Không gửi được *backup.img* (5,2 TB): Teleport chỉ gửi được file tối đa 4 TB. Hãy chia file thành nhiều phần nhỏ hơn rồi gửi.” | Lượt gửi không bắt đầu; bỏ file đó ra rồi gửi lại các file còn lại |
| Chọn gửi file có tên chứa ký tự điều khiển (ví dụ dấu xuống dòng; [protocol.md](protocol.md) mục 3.3) | “Không gửi được *bao�cao.txt*: tên file có ký tự không hiển thị được. Hãy đổi tên file rồi gửi lại.” | Lượt gửi không bắt đầu. Trong thông báo, mỗi ký tự điều khiển hiện thành `�` (U+FFFD), không in thẳng ra màn hình |
| File nguồn bị sửa khi đang gián đoạn hoặc khi đang gửi | Máy gửi: “*video.mp4* đã bị thay đổi trên máy gửi nên không thể gửi tiếp. Hãy gửi lại.” Máy nhận: “*video.mp4* đã bị thay đổi trên *Laptop-Minh* nên không nhận tiếp được. Các file đã nhận xong vẫn giữ nguyên; hãy nhờ gửi lại.” | Nút “Gửi lại” |
| Người nhận từ chối, hoặc máy nhận từ chối với lý do máy này không biết | “*PC-Nha* đã từ chối nhận file.” (máy nhận tự từ chối thì chỉ in “Đã từ chối.”) | — |
| Máy nhận chưa bật nhận file (đang chạy `teleport listen`, hay chỉ đang gửi) | “*PC-Nha* chưa bật nhận file. Trên máy đó hãy chạy `teleport receive` rồi gửi lại.” Giao diện: “*PC-Nha* đang không nhận file mới (có thể đã tạm dừng nhận, hoặc chưa mở được thư mục nhận). Hãy nhờ bật lại việc nhận file trên máy đó rồi gửi lại.” | Giao diện: nút “Gửi lại” |
| Máy nhận đang nhận một lượt khác từ máy này | Trạng thái “Đang chờ *PC-Nha* nhận xong lượt trước…” (không phải lỗi, lượt xếp hàng) | Tự xử lý |
| Người gửi hủy | Máy nhận: “*Laptop-Minh* đã hủy lượt gửi. Các file chưa nhận xong đã được xóa; file đã nhận xong vẫn giữ nguyên.”; hủy khi máy nhận còn đang hỏi: “*Laptop-Minh* đã hủy lượt gửi.” Máy gửi (tự hủy): “Đã hủy lượt gửi tới *PC-Nha*. Các file đã gửi xong vẫn nằm trên máy đó.” | — |
| Người nhận hủy giữa chừng (giao diện: nút Hủy; CLI `receive` khi Ctrl+C thì tạm dừng, không hủy) | Máy gửi: “*PC-Nha* đã dừng nhận giữa chừng. Các file đã gửi xong vẫn nằm trên máy đó.” Máy nhận (tự hủy): “Đã hủy nhận từ *Laptop-Minh*. File đã nhận xong vẫn giữ nguyên.” | Máy gửi: nút “Gửi lại” |
| Lỗi ghi đĩa ở máy nhận (ghi, `fsync` hay đổi tên lỗi) | Máy nhận: “Không lưu được *video.mp4* vào *D:\Downloads\Teleport* vì ổ đĩa báo lỗi khi ghi (ổ có thể đã đầy, bị rút ra hoặc bị hỏng). Đã dừng nhận từ *Laptop-Minh*; các file đã nhận xong vẫn giữ nguyên.” Máy gửi: “*PC-Nha* gặp lỗi khi nhận nên đã dừng lượt gửi. Hãy xem thông báo trên máy đó rồi gửi lại.” (máy nhận chỉ gửi `cancel{error}`) | Máy nhận: nút “Đổi thư mục nhận”. Máy gửi: nút “Gửi lại” |
| Không đọc được file nguồn khi đang gửi | Máy gửi: “Không đọc được *video.mp4* trên máy này nữa (file có thể đang bị chương trình khác khóa, hoặc nằm trên ổ vừa bị rút ra). Đã dừng gửi tới *PC-Nha*.” Máy nhận: “*Laptop-Minh* đã dừng gửi *video.mp4* vì gặp lỗi trên máy đó. Các file đã nhận xong vẫn giữ nguyên; hãy nhờ gửi lại.” | Nút “Gửi lại” |
| Dữ liệu nhận bị hỏng quá số lần gửi lại cho phép | Máy nhận: “Dữ liệu nhận từ *Laptop-Minh* bị hỏng nhiều lần liên tiếp nên đã dừng nhận *video.mp4*. Các file đã nhận xong vẫn giữ nguyên; hãy nhờ gửi lại.” Máy gửi: câu máy gửi của dòng “Lỗi ghi đĩa ở máy nhận” | Nút “Gửi lại” |
| Máy kia gửi dữ liệu không đúng giao thức | “Lượt gửi với *PC-Nha* đã dừng vì máy đó gửi dữ liệu không hợp lệ. Hãy cập nhật Teleport trên cả hai máy rồi thử lại.” | — |
| Thư mục tạm của lượt đã có sẵn mà Teleport không dùng tiếp được (hỏng, lỗi đĩa, hay không do Teleport trên máy này tạo; hiếm) | Máy nhận: “Không nhận được lượt gửi từ *Laptop-Minh* vì thư mục tạm của lượt này đã có sẵn mà Teleport không dùng tiếp được. Hãy nhờ gửi lại.” Máy gửi: câu máy gửi của dòng “Lỗi ghi đĩa ở máy nhận” | Nút “Gửi lại” |
| Lượt dừng vì lý do khác (lý do máy này không biết, máy kia không còn biết lượt này…) | Máy gửi: “*PC-Nha* đã dừng lượt gửi.” Máy nhận: “*Laptop-Minh* đã dừng lượt gửi.” | — |
| Đã tắt app gửi khi lượt truyền đang gián đoạn | “*Laptop-Minh* đã hủy lượt gửi *video.mp4*. Hãy nhờ gửi lại.” | — |
| Mất mạng | “Đang nối lại…” (không phải lỗi) | Tự xử lý |
| Giao diện: mất mạng giữa lượt (thẻ ở trạng thái “Đang nối lại…”) | Dòng phụ: “*45,0*% · Đang chờ *PC-Nha* nối lại…” (không hiện tốc độ và thời gian còn lại) | Tự xử lý |
| Giao diện, máy nhận: đang truyền mà từ 5 giây trở lên không có dữ liệu mới | Dòng phụ: “*45,0*% · Đang chờ dữ liệu…” (không hiện tốc độ và thời gian còn lại) | Tự xử lý |
| Giao diện, máy gửi: đang truyền mà từ 5 giây trở lên không gửi thêm được dữ liệu (kể cả lúc máy nhận đang kiểm tra file lớn) | Dòng phụ: “*45,0*% · Đang chờ *PC-Nha* phản hồi…” (không hiện tốc độ và thời gian còn lại) | Tự xử lý |
| Mất kết nối quá lâu (quá hạn nối lại; kể cả lượt nhận dở khi app nhận mở lại sau hạn nối lại) | Máy gửi: “Mất kết nối với *PC-Nha* quá lâu nên lượt gửi đã dừng. Hãy gửi lại.” Máy nhận: “Mất kết nối với *Laptop-Minh* quá lâu nên đã dừng nhận. Các file chưa nhận xong đã được xóa; file đã nhận xong vẫn giữ nguyên.” | Nút “Gửi lại” |
| Chọn gửi file không có quyền đọc | “Không mở được *video.mp4*: máy này không có quyền đọc file đó.” | Lượt gửi không bắt đầu |
| Chọn gửi một thư mục | “*ảnh* không phải là file. Teleport chưa gửi được cả thư mục; hãy chọn từng file.” | Lượt gửi không bắt đầu |
| Chọn một file hai lần | “Có file được chọn hai lần. Hãy chọn mỗi file một lần.” | Lượt gửi không bắt đầu |
| Chọn gửi file không tồn tại | “Không tìm thấy file *D:\x\video.mp4*.” | Lượt gửi không bắt đầu |
| Ổ đĩa báo lỗi khi kiểm file chọn gửi | “Không đọc được *video.mp4*: ổ đĩa báo lỗi.” | Lượt gửi không bắt đầu |
| Chọn quá số file một lượt | “Mỗi lần gửi được tối đa *1000* file.” | Lượt gửi không bắt đầu |
| Giao diện: Thoát (menu khay, Ctrl+Q, đóng cửa sổ khi không có khay hệ thống) khi còn lượt gửi chưa xong | Hộp “Thoát Teleport?”: “Đang gửi file tới *PC-Nha*. Thoát bây giờ sẽ hủy lượt gửi.” (nhiều máy: “Đang gửi file tới *2* máy. Thoát bây giờ sẽ hủy các lượt gửi.”). Chỉ còn lượt nhận dở thì thoát ngay, không hỏi (lượt nhận chạy tiếp khi mở lại app). Windows tắt máy hay đăng xuất thì không hỏi | Nút “Thoát”, “Không” (mặc định) |
| Giao diện: đóng cửa sổ khi app chạy được ở khay hệ thống (chỉ lần đầu tiên; đã báo thì không báo lại, kể cả ở các lần mở app sau) | Bóng thoại ở khay: “Teleport vẫn chạy ở khay hệ thống và vẫn nhận file. Chọn Thoát trong menu khay để tắt hẳn.” Đang tạm dừng nhận thì thay bằng: “Teleport vẫn chạy ở khay hệ thống nhưng đang tạm dừng nhận file mới và clipboard. Chọn Thoát trong menu khay để tắt hẳn.” | — |
| Giao diện: biểu tượng khay | Chú thích khi trỏ chuột: tên app, rồi các dòng “Đang truyền *2* lượt”, “Không nhận file: không mở được thư mục nhận” hoặc “Đã tạm dừng nhận file mới và clipboard”; không có dòng nào thì “Sẵn sàng nhận”. Trong 5 giây sau khi nhận clipboard, ngay dưới tên app có thêm dòng “Vừa nhận clipboard từ *PC-Nha*” (hay hai câu clipboard ở dưới). Biểu tượng có dấu nhỏ ở góc, khác nhau cả hình lẫn màu: đang truyền, vừa nhận clipboard (5 giây), đã tạm dừng nhận, không nhận file (ưu tiên: không nhận file > tạm dừng > vừa nhận clipboard > đang truyền) | — |
| Giao diện: tạm dừng nhận (mục “Tạm dừng nhận” có dấu chọn trong menu khay) | Thẻ máy này có huy hiệu “Đã tạm dừng nhận”, mô tả: “File mới gửi tới sẽ bị từ chối, clipboard gửi tới sẽ bị bỏ qua; lượt đang nhận vẫn tiếp tục. Bỏ chọn “Tạm dừng nhận” trong menu khay để nhận lại.” Chặn lời mời nhận file mới (lượt đang chạy, đang hỏi hay đang nối lại vẫn tiếp tục) và bỏ clipboard gửi tới (vẫn gửi clipboard đi), chỉ trong lần mở app này (mở lại app là nhận lại). Máy không có khay hệ thống thì không có mục này | Bỏ chọn trong menu khay |
| Vừa sao chép nội dung vượt trần clip ([protocol.md](protocol.md) mục 3.3) khi đang đồng bộ clipboard với ít nhất một máy đang kết nối | Tooltip khay 5 giây: “Clipboard quá lớn nên không gửi. Hãy gửi dạng file.” | Dùng “Gửi file” |
| Nhận clipboard nhưng không chép được vào máy này (ứng dụng khác đang giữ clipboard) | Luồng của *PC-Nha*: “Clipboard · chưa chép được vào máy này”; tooltip khay 5 giây: “Chưa chép được clipboard từ *PC-Nha*” | Nút “Thử lại” trong cuộc trò chuyện với *PC-Nha* (clipboard đó không còn để chép lại thì dòng dưới đổi thành “Clipboard này không còn để chép lại.”) |
| Giao diện: “Gửi file…” trong menu khay | Menu con liệt kê các máy đã ghép đôi (máy ngoại tuyến: “*PC-Nha* (ngoại tuyến)”); chọn một máy thì hiện cửa sổ ở cuộc trò chuyện đó và mở hộp chọn file. Chưa ghép đôi máy nào: mục mờ “Chưa ghép đôi với máy nào” và mục “Tìm máy mới…” | Chọn máy rồi chọn file |
| Giao diện, máy nhận: thư mục nhận không còn hoặc không dùng được khi nhận một lượt | “Không nhận được lượt gửi từ *Laptop-Minh* vì thư mục nhận *D:\Downloads\Teleport* không còn hoặc không dùng được, và Teleport không tạo lại được (có thể thư mục chứa nó đã bị xóa, hoặc ổ đã bị rút ra). Hãy kiểm tra lại rồi nhờ gửi lại.” | Nút “Đổi thư mục nhận” |
| Giao diện: có file gửi tới | Hộp hỏi ở mục 7.3; khi không có cửa sổ Teleport nào đang được dùng (cửa sổ ẩn, thu nhỏ hay bị cửa sổ khác che) thì thêm bóng thoại ở khay: “Có file đang chờ bạn nhận.” | Nút “Nhận”, “Từ chối” trong hộp hỏi. Bấm vào bóng thoại: hiện cửa sổ chính và đưa hộp hỏi lên trước |
| Giao diện: nhận xong một lượt | Bóng thoại ở khay: “Đã nhận *3* file từ *Laptop-Minh*.” (một file: “Đã nhận *video.mp4* từ *Laptop-Minh*.”, với tên file đã lưu trên máy này, ví dụ *video (1).mp4* khi thư mục nhận đã có file cùng tên) | Nhiều lượt xong cách nhau vài giây gộp thành một bóng thoại (“Đã nhận *4* file từ *2* máy.” khi từ nhiều máy). Không báo khi người dùng đang mở đúng cuộc trò chuyện đó. Bấm vào bóng thoại: mở thư mục và chọn sẵn file vừa nhận (hệ không hỗ trợ: mở thư mục chứa file). Nút “Hiện trong thư mục” trên thẻ của lượt |
| Giao diện: địa chỉ của máy này (để nhập IP thủ công ở máy kia) | Khi Teleport đang chạy: dòng chọn được “Địa chỉ: *192.168.1.5*” (thêm “:*cổng*” khi không phải cổng mặc định, [protocol.md](protocol.md) mục 2.1); máy có nhiều địa chỉ thì hiện địa chỉ đầu, các địa chỉ còn lại ở chú thích khi trỏ chuột: “Các địa chỉ khác của máy này: …”. Cập nhật khi đổi mạng (đọc lại mỗi 10 giây). Không đọc được địa chỉ nào thì không hiện dòng này | — |
| Giao diện: chưa có lượt truyền nào trong lần mở app này | “Kéo file vào một thiết bị để gửi” (ở khung lượt truyền) | — |
| Giao diện: thả file vào chỗ không có máy ở cột trái | “Thả file lên một thiết bị để gửi.” | — |
| Giao diện: nhấn Ctrl+V trong luồng của một máy mà clipboard không phải file đã chép (chữ, ảnh, liên kết web) | “Ctrl+V ở đây chỉ gửi file đã chép trong File Explorer. Chữ và ảnh đi qua “Đồng bộ clipboard” với *PC-Nha* (Cài đặt ▸ Thiết bị tin cậy, cần bật ở cả hai máy): chép ở máy này rồi dán thẳng ở máy kia.” (macOS: “Finder”, Linux: “trình quản lý file”) | Nút “Mở Cài đặt”: mở Thiết bị tin cậy, tiêu điểm ở “Đồng bộ clipboard” của máy đó |
| Giao diện: nhấn Ctrl+V để gửi file khi chưa chọn máy nào | “Ghép đôi một máy trước (Ctrl+N), rồi nhấn Ctrl+V để gửi file đã chép.” | — |
| Giao diện: gửi tới thiết bị chưa ghép đôi | Mở luồng ghép đôi (mục 7.2); ghép xong thì tự gửi | — |
| Giao diện: gửi tiếp khi đang chờ ghép đôi để gửi một lượt khác | “Đang chờ ghép đôi với *PC-Nha* để gửi file. Hãy chờ xong rồi gửi tiếp.” (*PC-Nha* là máy đang chờ ghép đôi, không phải máy vừa được chọn gửi) | Chờ lần ghép đôi đang chạy xong rồi gửi lại |
| Giao diện: gửi tới thiết bị mà lần kết nối gần nhất bị chặn, hoặc lần kết nối mở cho chính lượt gửi đó bị chặn | Câu của dòng “Máy kia từ chối máy này”, “Danh tính thiết bị thay đổi” hoặc “Khác phiên bản giao thức” | Lượt gửi không bắt đầu; lượt đã hiện trên danh sách mà chưa gửi được lời mời thì bị gỡ, không chờ nối lại. Kèm nút trên dải thông báo: bị từ chối → “Ghép đôi lại”; danh tính thay đổi → “Hủy ghép đôi” (hỏi xác nhận kèm cảnh báo); khác phiên bản → không có nút |
| Giao diện: bấm “Ghép đôi lại” khi máy kia không có trong mạng (ví dụ đã ghép bằng IP vì mạng chặn mDNS) | “Không thấy “*PC-Nha*” trong mạng. Nếu mạng chặn việc tìm thiết bị, hãy nhập địa chỉ IP của máy đó để ghép đôi lại.” | Không bắt đầu ghép đôi; mở màn “Tìm máy mới”, câu hiện ở thanh thông báo của màn đó, đặt tiêu điểm vào ô nhập IP |
| Giao diện: gửi tới thiết bị đã ghép đôi nhưng chưa kết nối | Trạng thái “Đang chờ kết nối tới *PC-Nha*…” (không phải lỗi). Máy đó ngoại tuyến thì thanh dưới luồng ghi: “*PC-Nha* đang ngoại tuyến. File gửi lúc này sẽ chờ và tự gửi khi máy đó mở Teleport trong cùng mạng, nếu Teleport trên máy này vẫn chạy (kể cả khi chỉ còn ở khay).” | Tự xử lý |
| Giao diện: gửi tới thiết bị không (còn) ghép đôi | “Chưa ghép đôi với *PC-Nha* nên chưa gửi được. Hãy ghép đôi rồi gửi lại.” | Lượt gửi không bắt đầu |
| Giao diện: không gửi được vì lỗi khác lúc bắt đầu lượt | “Không gửi được file tới *PC-Nha*. Hãy thử lại.” | Lượt gửi không bắt đầu |
| Giao diện: lượt nhận dở được khôi phục khi mở lại app | Trạng thái “Đang chờ *Laptop-Minh* nối lại…” | Tự xử lý |
| Giao diện: khởi động khi một lệnh CLI đang chạy cùng thư mục cấu hình | “Teleport đang chạy ở nơi khác với thư mục cấu hình này (ví dụ lệnh “teleport receive” trong cửa sổ dòng lệnh).” kèm dòng “Hãy dừng nó rồi bấm Thử lại.” | Nút “Thử lại” |
| Giao diện: mở app khi một bản Teleport khác cùng thư mục cấu hình đang tắt hoặc không phản hồi | “Teleport đang tắt hoặc chưa phản hồi.” kèm dòng “Hãy thử lại sau giây lát.” | Nút “OK” |
| Giao diện: không dùng được thư mục cấu hình khi khởi động | “Không dùng được thư mục cấu hình *D:\X* (*lỗi*).” kèm dòng “Hãy kiểm tra quyền ghi vào thư mục đó rồi bấm Thử lại.” | Nút “Thử lại” |
| Giao diện: không dùng được thư mục cấu hình ngay lúc mở app (trước khi có cửa sổ) | Câu chính như dòng trên, kèm dòng “Hãy kiểm tra quyền ghi vào thư mục đó rồi mở lại Teleport.” | Nút “OK” |
| Giao diện: danh tính của máy này hỏng khi khởi động | Câu của dòng “Danh tính của chính máy này bị hỏng”, kèm dòng “Hãy chạy “teleport identity” trong cửa sổ dòng lệnh để xem chi tiết.” | Nút “Thử lại” (nút “Tạo danh tính mới” làm sau) |
| Giao diện: không đọc được `trusted.json` khi khởi động | “Không đọc được danh sách thiết bị đã ghép đôi. Teleport sẽ không tự xóa nó để khỏi mất các ghép đôi.” kèm dòng “Hãy chạy “teleport receive” trong cửa sổ dòng lệnh để xem chi tiết.” | Nút “Thử lại” |
| Giao diện: thư mục nhận đã lưu không mở được khi khởi động (ổ bị rút, mất quyền ghi…) | App vẫn chạy nhưng không nhận file, không tự chuyển sang thư mục khác. Dải thông báo: “Teleport đang không nhận file vì không mở được thư mục nhận *E:\Teleport*. Hãy kiểm tra ổ đĩa và quyền ghi rồi chọn lại thư mục đó, hoặc chọn thư mục khác.” Thẻ máy này: “Không nhận file”; chân cửa sổ: “Không nhận file: không mở được *E:\Teleport*”. Đang chạy nền (cửa sổ không hiện): thêm bóng thoại ở khay “Teleport đang không nhận file vì không mở được thư mục nhận. Mở Teleport để chọn thư mục khác.” | Nút “Chọn thư mục nhận” trên dải thông báo; nút “Đổi…” ở chân cửa sổ |
| Giao diện: đổi thư mục nhận khi đang nhận file | “Chưa đổi được thư mục nhận vì đang nhận file. Hãy đổi lại sau khi các lượt nhận xong.” | Thư mục nhận giữ nguyên; đổi lại sau bằng “Đổi…” |
| Giao diện: thư mục vừa chọn để nhận file không dùng được (không tạo, không ghi được, đường dẫn quá dài…) | “Không dùng được thư mục *E:\Teleport*. Hãy chọn thư mục khác mà bạn có quyền ghi.” | Nút “Chọn thư mục khác” |
| Giao diện: thư mục vừa chọn là thư mục riêng của Teleport (thư mục cấu hình hay nằm trong nó, hoặc thư mục `.teleport`) | “Không dùng được thư mục *D:\Teleport\.teleport* để nhận file vì Teleport dùng nó cho việc riêng. Hãy chọn thư mục khác.” | Nút “Chọn thư mục khác” |
| Giao diện: đổi thư mục nhận mà không ghi được cài đặt | “Chưa đổi được thư mục nhận vì không ghi được cài đặt của Teleport. Hãy kiểm tra quyền ghi vào thư mục cấu hình rồi thử lại.” | Thư mục nhận giữ nguyên |
| Giao diện: đổi thư mục nhận gặp lỗi khác | “Chưa đổi được thư mục nhận vì một lỗi không mong đợi. Hãy thử lại.” | Thư mục nhận giữ nguyên |
| Giao diện: không mở được cổng khi khởi động | “Không mở được cổng để nhận kết nối (*lỗi*).” kèm dòng “Hãy đóng ứng dụng đang dùng cổng đó rồi bấm Thử lại.” | Nút “Thử lại” |
| Giao diện: lỗi khác khi khởi động | “Teleport không khởi động được vì một lỗi không mong đợi.” kèm dòng “Hãy bấm Thử lại; nếu vẫn lỗi, hãy chạy “teleport receive” trong cửa sổ dòng lệnh để xem chi tiết.” | Nút “Thử lại” |
| Giao diện: mở app khi máy chưa có danh tính (lần chạy đầu, F1, mục 7.6) | Màn lần chạy đầu với nội dung theo mục 7.6. Chưa bấm thì Teleport không chạy, không quảng bá | Nút “Bắt đầu” |
| Giao diện, lần chạy đầu: tên thiết bị rỗng / sai | Câu của dòng “Giao diện, Cài đặt: tên thiết bị rỗng / sai” (ngay dưới ô tên) | Sửa tên rồi bấm “Bắt đầu” |
| Giao diện, lần chạy đầu: thư mục vừa chọn không dùng được / là thư mục riêng của Teleport | Câu của dòng “Giao diện: thư mục vừa chọn để nhận file không dùng được” / “Giao diện: thư mục vừa chọn là thư mục riêng của Teleport”, hiện ngay dưới hàng thư mục (thư mục không dùng được chỉ biết khi bấm “Bắt đầu”: màn quay lại lần chạy đầu, giữ tên đã gõ) | Nút “Đổi…” |
| Giao diện, lần chạy đầu: không bật được khởi động cùng Windows | “Chưa bật được khởi động cùng Windows vì Windows không cho ghi cài đặt khởi động. Bạn có thể bật lại trong Cài đặt.” ở dải thông báo của cửa sổ chính; Teleport vẫn chạy. Đang có dải báo thư mục nhận không mở được (dòng “Giao diện: thư mục nhận đã lưu không mở được khi khởi động”) thì chỉ hiện dải đó | Nút “Mở Cài đặt” |
| Giao diện: trạng thái của một thiết bị trên màn “Tìm máy mới” (dạng danh sách) | Sau tên và “(đã ghép)” / “(chưa ghép)” (mục 7.1): “đã kết nối”, “đang trong mạng” hoặc “không thấy trong mạng”. Thiết bị đã ghép đôi mà lần kết nối gần nhất lỗi thì thêm câu của dòng “Thấy nhưng không kết nối được” (chỉ khi còn thấy trong mạng), “Máy kia từ chối máy này”, “Danh tính thiết bị thay đổi” hoặc “Khác phiên bản giao thức”, tới khi kết nối lại được | — |
| Giao diện: trạng thái của một máy ở danh sách cuộc trò chuyện | “Trực tuyến”, “Ngoại tuyến” hoặc lượt đang chạy (“Đang gửi · 62%”…), rồi hoạt động gần nhất. Lần kết nối gần nhất lỗi thì nhãn ngắn “Bị từ chối kết nối”, “Danh tính đã đổi”, “Khác phiên bản” hoặc “Không kết nối được”, kèm câu đầy đủ ở chú thích. Đang kéo file qua hàng: “Thả để gửi *n* file” | — |
| Giao diện: đang ghép đôi (máy này gửi yêu cầu, máy kia chưa hiện mã) | Hộp “Ghép đôi” có thanh chờ và câu “Đang ghép đôi với “*PC-Nha*”…” (ghép bằng IP: “*192.168.1.5:47474*” thay cho tên) | Nút “Hủy” |
| Giao diện: ghép đôi xong | “Đã ghép đôi với “*PC-Nha*”.” ở thanh thông báo của luồng chat, không mở hộp (cả hai máy); không có cửa sổ Teleport nào đang được dùng (cửa sổ ẩn, thu nhỏ hay bị cửa sổ khác che) thì thêm bóng thoại ở khay. Ghép đôi lỗi vẫn hiện hộp | Nút “Đóng” của dải thông báo |
| Giao diện, màn “Chờ ghép đôi” (mục 7.5): không tìm thấy địa chỉ IPv4 nào của máy này | “Không tìm thấy địa chỉ mạng nào của máy này. Hãy kiểm tra máy đã nối Wi-Fi hoặc dây mạng.” (tự mất khi có lại địa chỉ) | Nối mạng |
| Giao diện, màn “Chờ ghép đôi” (mục 7.5): không mở được chế độ chờ ghép đôi | “Chưa mở được chế độ chờ ghép đôi. Hãy đóng màn này rồi thử lại.” (không hiện “Đang chờ…”) | Đóng màn rồi mở lại |
| Giao diện: bấm ghép đôi một thiết bị vừa rời mạng | “Không thấy “*PC-Nha*” trong mạng nữa. Hãy thử lại.” | — |
| Giao diện: ghép đôi khi máy này đang có phiên ghép đôi khác | “Máy này đang có một phiên ghép đôi khác. Hãy thử lại sau.” | — |
| Giao diện: đã xác nhận ghép đôi nhưng không lưu được | “Đã xác nhận ghép đôi với “*PC-Nha*” nhưng không lưu được danh sách thiết bị đã ghép đôi. Hãy kiểm tra quyền ghi thư mục cấu hình rồi ghép đôi lại.” | — |
| Giao diện: danh tính thiết bị thay đổi khi máy này gửi yêu cầu ghép đôi | Câu của dòng “Danh tính thiết bị thay đổi”, kèm dòng “Muốn ghép đôi lại thì hãy hủy ghép đôi mục cũ trước (chuột phải vào thiết bị → Hủy ghép đôi…).” | — |
| Giao diện: phiên ghép đôi do máy khác gửi tới dừng trước khi hiện mã | Không hiện gì (máy lạ không làm phiền được bằng cách mở rồi bỏ phiên). Ngoại lệ: máy này cũng vừa bấm ghép đôi với máy đó và phiên của máy này nhường cho phiên kia (hai máy cùng chủ động): hiện câu của máy gửi yêu cầu ở dòng “Phiên ghép đôi dừng trước khi hiện mã” | — |
| Giao diện: có yêu cầu ghép đôi khi không có cửa sổ Teleport nào đang được dùng (cửa sổ ẩn, thu nhỏ hay bị cửa sổ khác che) | Bóng thoại ở khay: “Có yêu cầu ghép đôi” | Hộp mã (mục 7.2) vẫn mở. Bấm vào bóng thoại: hiện cửa sổ chính và đưa hộp mã lên trước |
| Giao diện: hủy ghép đôi (chuột phải vào thiết bị đã ghép → “Hủy ghép đôi…”, hay nút “Hủy ghép đôi…” ở Cài đặt → Thiết bị tin cậy) | Hộp “Hủy ghép đôi”: “Hủy ghép đôi với “*PC-Nha*”? Hai máy sẽ không gửi file cho nhau được nữa cho tới khi ghép đôi lại.”, có ô “Xóa cả lịch sử truyền file với máy này” (bật sẵn). Xong: “Đã hủy ghép đôi với “*PC-Nha*”.” ở dải thông báo như dòng “Giao diện: ghép đôi xong”. Lỗi (hộp): “Không hủy ghép đôi được với “*PC-Nha*”. Hãy thử lại.” | Nút “Hủy ghép đôi”, “Không” (mặc định) |
| Giao diện, Cài đặt: tên thiết bị rỗng / sai | “Hãy nhập tên thiết bị.” / “Tên thiết bị cần từ 1 đến 64 ký tự và không có ký tự điều khiển.” (ngay dưới ô tên) | Sửa tên; Esc trả tên cũ |
| Giao diện: bấm Nhận với “Luôn nhận từ thiết bị này” nhưng không lưu được cài đặt | “Chưa lưu được “Luôn nhận” cho *Laptop-Minh* vì không ghi được cài đặt của Teleport. Hãy thử lại trong Cài đặt ▸ Thiết bị tin cậy (bỏ chọn “Hỏi trước khi nhận”).” (lượt này vẫn được nhận) | — |
| Giao diện, Cài đặt: không lưu được cài đặt | “Chưa lưu được cài đặt vì không ghi được vào thư mục cấu hình của Teleport. Hãy kiểm tra quyền ghi rồi thử lại.” Lỗi khác: “Chưa lưu được cài đặt vì một lỗi không mong đợi. Hãy thử lại.” (control trở về giá trị cũ) | Thử lại |
| Giao diện, Cài đặt: không đọc được cài đặt hiện tại | “Không đọc được cài đặt hiện tại.” | Nút “Thử lại” |
| Giao diện, Cài đặt: khởi động cùng Windows | Đọc registry lỗi: “Không đọc được cài đặt khởi động của Windows.” Ghi lỗi: “Chưa đổi được việc khởi động cùng Windows vì Windows không cho ghi cài đặt khởi động. Hãy thử lại.” Windows đang tắt Teleport ở danh sách ứng dụng khởi động: “Windows đang tắt Teleport trong danh sách ứng dụng khởi động. Bật công tắc này để cho phép lại.” Bản khác đang được đặt: “Teleport đang được đặt khởi động cùng Windows từ một thư mục cài hoặc thư mục cấu hình khác. Bật công tắc để dùng bản này.” | Bật lại công tắc |
| Giao diện, Cài đặt: máy này đang ẩn | Dưới công tắc: “Đang ẩn: máy chưa ghép đôi không thấy máy này và không gửi được yêu cầu ghép đôi tới. Muốn ghép đôi với máy mới, hãy mở Tìm máy mới trên máy này rồi bấm vào máy kia.”; dưới ô tên: “Máy này đang ẩn nên chỉ máy đã ghép đôi thấy tên này.” | — |
| Giao diện, Cài đặt: xóa toàn bộ lịch sử | Hộp “Xóa toàn bộ lịch sử”: “Xóa lịch sử truyền file với mọi máy, kể cả máy đã hủy ghép đôi? File đã nhận vẫn còn nguyên trong thư mục nhận.” Xong: “Đã xóa toàn bộ lịch sử truyền file.” Lỗi: “Chưa xóa được lịch sử truyền file. Hãy thử lại.” | Nút “Xóa lịch sử”, “Không” (mặc định) |
| Giao diện, Cài đặt: xuất log | Xong: “Đã lưu log vào *D:\Logs\teleport-log-20261031-101500.zip*.” Không ghi được: “Không lưu được file log vào *đường dẫn*. Hãy chọn thư mục khác mà bạn có quyền ghi.” Lỗi khác: “Không xuất được log vì một lỗi không mong đợi. Hãy thử lại.” | Nút “Mở thư mục” (khi xong) |
| Giao diện: nhập IP thủ công sai | Câu của dòng “CLI: `--address` của `send` sai” (*x* là chữ đã nhập) | Sửa lại trong ô nhập |
| CLI: `--limit-rate` sai | “Tốc độ không hợp lệ: “*x*”. Hãy nhập ví dụ 20M (20 MB/s) hoặc 512K; tối thiểu 64K.” | — |
| CLI: `--address` của `send` sai | “*x* không phải địa chỉ IPv4 hợp lệ. Hãy nhập ví dụ 192.168.1.5 hoặc 192.168.1.5:47474.” | — |
| CLI: `send` / `receive` / `unpair` / `listen` / `pair` khi một node khác (lệnh CLI khác hay giao diện) đang chạy cùng thư mục cấu hình | “Teleport đang chạy với thư mục cấu hình này.” kèm dòng “Hãy dừng `teleport receive` hoặc `teleport listen` đang chạy, hoặc chọn Thoát trong menu khay của Teleport, rồi thử lại.” | — |
| CLI: `send` không thấy máy nhận trong mạng | “Không thấy *PC-Nha* trong mạng. Hãy kiểm tra máy đó đang chạy `teleport receive` và hai máy dùng chung một mạng; nếu mạng chặn mDNS, hãy thêm `--address <ip[:cổng]>`.” | — |
| CLI: `send` không bật được khám phá mDNS | “Không tìm được *PC-Nha* vì không bật được khám phá mDNS (*lý do*). Hãy thêm `--address <ip[:cổng]>`.” | — |
| CLI: không dùng được thư mục nhận | “Không dùng được thư mục nhận *D:\X*:” rồi một trong các đuôi: “thư mục ẩn `.teleport` bên trong là liên kết hoặc thuộc người dùng khác. Hãy xóa nó hoặc chọn thư mục khác bằng `--dir`.” / “đường dẫn quá dài. Hãy chọn thư mục có đường dẫn ngắn hơn bằng `--dir`.” / “máy này không có quyền ghi vào đó. Hãy chọn thư mục khác bằng `--dir`.” / “ổ đĩa báo lỗi hoặc không phản hồi. Hãy chọn thư mục khác bằng `--dir`.” / “đó không phải là thư mục (có thể là một file trùng tên). Hãy chọn thư mục khác bằng `--dir`.” | — |
| CLI: `receive --yes` | “Cảnh báo: đang tự nhận mọi file từ mọi thiết bị đã ghép đôi, không hỏi trước (`--yes`).” | — |
| CLI: `receive` khi chưa ghép đôi với thiết bị nào | “Máy này chưa ghép đôi với thiết bị nào nên chưa nhận được file. Hãy ghép đôi trước: `teleport listen` trên một máy, `teleport pair` trên máy kia.” | — |
| CLI: `receive` không quảng bá được qua mDNS | “Cảnh báo: chưa quảng bá được qua mDNS (*lý do*); máy khác vẫn gửi được bằng `teleport send … --address <IP của máy này>`.” | — |
| CLI: `receive` / `send` khi máy này đang ẩn (F10; đổi ở giao diện) | “Cảnh báo: máy này đang ẩn (đã tắt “Cho máy chưa ghép đôi thấy máy này” trong cài đặt) nên không quảng bá trong mạng; máy đã ghép đôi tự kết nối được với máy này khi máy kia đang hiện, hoặc khi hai máy đã từng kết nối và địa chỉ không đổi.” (`listen` khi ẩn in câu của màn hình “Chờ ghép đôi”, F10) | Bật lại ở cài đặt của giao diện |
| CLI: `receive` không đọc được câu trả lời `[c/k]` (đầu vào đã đóng) | “Không đọc được câu trả lời (đầu vào đã đóng) nên đã từ chối. Hãy dùng `--yes` để tự nhận.” (in một lần); mỗi lượt bị từ chối khi chưa hiện lời hỏi (đang xếp hàng, hay tới sau khi đầu vào đóng) thêm: “Đã từ chối *3* file từ *Laptop-Minh* vì không đọc được câu trả lời (đầu vào đã đóng).” | — |
| CLI: `listen` / `pair` không đọc được câu trả lời `[c/k]` (đầu vào đã đóng) | “Không đọc được câu trả lời (đầu vào đã đóng) nên đã từ chối ghép đôi.” (in một lần); mọi lời hỏi ghép đôi sau đó tự bị từ chối | — |
| CLI: `receive` dừng (Ctrl+C) khi còn lượt chưa hiện lời hỏi | Mỗi lượt đó: “Đã từ chối *3* file từ *Laptop-Minh* vì đang dừng nhận.” (lượt đang hỏi thì không in “Đã từ chối.”); lượt đang nhận thì tạm dừng (dòng “CLI: `receive` dừng (Ctrl+C) khi đang nhận”) | — |
| CLI: `receive` dừng (Ctrl+C) khi đang nhận | Máy nhận, mỗi lượt: “Đã tạm dừng nhận *video.mp4* từ *Laptop-Minh*. Chạy lại `teleport receive` (cùng thư mục nhận) để nhận tiếp phần còn thiếu, miễn là máy gửi vẫn đang chờ; quá 24 giờ kể từ lúc mất kết nối thì lần chạy sau sẽ xóa phần nhận dở.” (lượt nhiều file: “*3* file” thay cho tên file). Máy gửi: “Đang nối lại…” (dòng “Mất mạng”); chưa nối lại được thì thêm câu ở dòng “CLI: `send` chưa nối lại được trong lúc chờ nối lại” | — |
| CLI: `receive` mở lại khi có lượt nhận dở | Ngay sau phần đầu (mục 7.3), mỗi lượt: “Tiếp tục nhận *3* file từ *Laptop-Minh* (đã nhận *4,2 GB* / *8,0 GB*). Đang chờ máy đó kết nối lại…”, không hỏi `[c/k]`. Lượt đã quá hạn nối lại: dòng “Mất kết nối quá lâu” | Tự xử lý |
| CLI: `send` chưa nối lại được trong lúc chờ nối lại | “Chưa nối lại được với *PC-Nha*. Teleport vẫn đang thử lại (tối đa 24 giờ). Hãy kiểm tra máy đó vẫn đang chạy `teleport receive` và hai máy còn chung một mạng.” (một lần mỗi đợt mất kết nối) | Kiểm tra máy nhận đang chạy `teleport receive` và cùng mạng |

---

## 9. Yêu cầu phi chức năng

Đây là **nguồn duy nhất** cho các con số chất lượng của v1.0. Kế hoạch kỹ thuật và kiểm thử tham chiếu theo mã N1–N12.

| Mã | Nhóm | Yêu cầu | Cách đo |
|---|---|---|---|
| N1 | Khám phá | Thiết bị mới xuất hiện < 3 giây; thoát app thì biến mất < 10 giây; mất mạng đột ngột hoặc ngủ thì biến mất < 2 phút | Log thời điểm mDNS |
| N2 | Hiệu năng | ≥ 70% tốc độ copy qua chia sẻ thư mục Windows (SMB) trên cùng mạng | Benchmark mỗi bản phát hành, công bố ở [benchmark.md](benchmark.md) |
| N3 | Bộ nhớ | Khi truyền: RSS tăng < 50MB so với lúc rảnh với file 1GB, 5GB, 10GB (đường RAM phẳng). Khi rảnh: RAM < 150MB, CPU ~0% | `psutil` + biểu đồ RSS, mỗi bản phát hành |
| N4 | Nối lại | Rớt mạng hoặc tắt app nhận ở bất kỳ điểm nào → gửi lại ≤ phần chưa nhận + 64 MiB (ở 85%: ≤ 15% + 64 MiB) | Test tự động, đếm byte gửi lại |
| N5 | Toàn vẹn | 100% file nhận khớp Merkle root; sửa 1 byte bất kỳ đều bị phát hiện | Test tự động |
| N6 | Clipboard | Văn bản < 500ms; ảnh ≤ 10MB < 2 giây trên Wi-Fi 5 | Log timestamp hai đầu |
| N7 | Độ tin cậy | 100 lượt truyền liên tiếp (file nhỏ lẫn lớn) không crash, không rò bộ nhớ, không sót file tạm | Test soak tự động |
| N8 | Bảo mật | TLS 1.3 bắt buộc; ngoài bước ghép đôi (có xác nhận mã 6 số), chỉ thiết bị đã ghép đôi mới kết nối được; mọi dữ liệu nhận từ máy khác đều được kiểm tra hợp lệ | Test tự động + fuzz test |
| N9 | Quyền riêng tư | Không telemetry, không tài khoản; không có kết nối Internet nào trừ kiểm tra cập nhật (tùy chọn, mặc định tắt); log không chứa nội dung file/clipboard | Kiểm tra mã + theo dõi kết nối mạng |
| N10 | Tương thích | Windows 10 (22H2) và 11; macOS 12+; Ubuntu 22.04+; các hệ điều hành gửi/nhận qua lại được với nhau | CI + ma trận thử thủ công |
| N11 | Cài đặt | Bộ cài Windows ≤ 80MB, không cần khởi động lại; gỡ cài đặt sạch (tùy chọn giữ cài đặt và thiết bị tin cậy) | Kiểm tra trên máy ảo sạch |
| N12 | Trợ năng | Dùng được hoàn toàn bằng bàn phím; tương phản màu đạt WCAG AA; theo chế độ sáng/tối của hệ điều hành | Kiểm thủ công trước bản beta |

Ngoài ra: CI xanh trên 3 hệ điều hành và mọi tính năng lõi có test tự động.

### 9.1. Thử nghiệm với người dùng thật

App không có telemetry, nên trải nghiệm được đo bằng thử nghiệm trực tiếp với 5–10 người, trên ít nhất 3 kiểu mạng (nhà, văn phòng, Wi-Fi công cộng):

| Chỉ số | Mục tiêu v1.0 |
|---|---|
| Thời gian từ mở bộ cài tới gửi xong file đầu tiên | < 2 phút |
| Tỉ lệ người thử gửi thành công không cần hỗ trợ | ≥ 90% |
| Lỗi nghiêm trọng còn mở khi phát hành | 0 |

---

## 10. Kiến trúc tóm tắt

```
┌──────────── App Teleport (Python 3.12+) ────────────┐
│ Giao diện: PySide6 — radar, lượt truyền, ghép đôi,   │
│            khay hệ thống          │ CLI `teleport`   │
│ Lõi asyncio:                                         │
│   khám phá (mDNS) · danh tính (chứng chỉ tự ký)      │
│   ghép đôi (mã 6 số) · kết nối TLS 1.3 ghim cert     │
│   gửi/nhận theo khối 1 MiB + backpressure            │
│   SHA-256 Merkle + bitfield nối lại · clipboard      │
└──────────────────────────────────────────────────────┘
            ▲ TLS 1.3, chỉ thiết bị đã ghép đôi ▼
                  App Teleport trên máy khác
```

- Kết nối trực tiếp bằng TCP + TLS 1.3 trong mạng nội bộ; không có máy chủ trung gian.
- File được chia thành khối 1 MiB, đọc và ghi thẳng giữa hai ổ đĩa; RAM chỉ giữ vài khối.
- Thiết kế chi tiết: [ke_hoach.md](ke_hoach.md) mục 3. Đặc tả giao thức: [protocol.md](protocol.md).

---

## 11. Bảo mật & quyền riêng tư

| Mối đe dọa | Ví dụ | Biện pháp trong MVP |
|---|---|---|
| Nghe lén trên Wi-Fi chung | Người cùng quán cà phê bắt gói tin | Toàn bộ dữ liệu mã hóa TLS 1.3 |
| Giả mạo thiết bị (MITM) | Kẻ xấu đặt tên máy “PC-Nha” | Ghép đôi bằng mã 6 số có nonce cam kết (kẻ giữa không thể dò trước khóa cho trùng mã); lời hỏi hiện mã trước tên do máy kia tự đặt (mục 7.2); sau đó chỉ chấp nhận đúng chứng chỉ đã ghim |
| Thiết bị lạ gửi rác | Máy lạ spam file | Máy chưa ghép đôi không kết nối được; mặc định luôn hỏi trước khi nhận |
| File độc hại ghi đè hệ thống | Tên file `..\..\Windows\x.dll` | Làm sạch tên, chỉ ghi trong thư mục nhận, không ghi đè |
| Dữ liệu điều khiển độc hại | Message cực lớn hoặc sai định dạng | Giới hạn kích thước, kiểm tra hợp lệ từng trường, fuzz test |
| Lộ mật khẩu qua clipboard | Copy mật khẩu từ trình quản lý mật khẩu | Clipboard mặc định tắt; bỏ qua nội dung đánh dấu nhạy cảm |
| Thu thập dữ liệu người dùng | — | Không telemetry, không tài khoản, không máy chủ |
| Theo dõi thiết bị qua nhiều mạng | Người lạ ở quán cà phê, khách sạn ghi lại mã thiết bị và tên máy mà Teleport quảng bá, rồi nhận ra cùng chiếc laptop đó ở mạng khác | Lần chạy đầu nói rõ tên thiết bị hiện với mọi máy trong mạng và cho đặt tên khác (F1, F10); công tắc “Cho máy chưa ghép đôi thấy máy này” (F10): tắt thì máy này không quảng bá, và khi không ở chế độ chờ ghép đôi (F3) thì máy chưa ghép đôi kết nối tới cũng không nhận được tên, phiên bản app hay hệ điều hành. Chưa chặn trong MVP: mã thiết bị cố định, và máy nào kết nối tới cổng của Teleport vẫn đọc được nó trong chứng chỉ; quảng bá ẩn danh để sau v1.0, việc tự ẩn khi Windows ở mạng Public còn đang cân nhắc ([ke_hoach.md](ke_hoach.md) mục 3.7, 9). Những gì máy này để lộ: [protocol.md](protocol.md) mục 8 |

Báo lỗ hổng bảo mật theo [SECURITY.md](SECURITY.md) (đã có từ Giai đoạn 0; bản hoàn chỉnh cho v1.0).

---

## 12. Tiêu chí phát hành MVP (Definition of Done)

- [ ] Mọi tiêu chí chấp nhận F1–F12 đều đạt.
- [ ] Mọi yêu cầu phi chức năng N1–N12 đều đạt, có số liệu trong [benchmark.md](benchmark.md).
- [ ] Đạt các chỉ số thử nghiệm người dùng ở mục 9.1.
- [ ] CI xanh trên Windows, macOS, Linux.
- [ ] Bộ cài cho 3 hệ điều hành được build tự động khi gắn tag `v1.0.0` (nếu trễ tiến độ, bộ cài macOS/Linux có thể hoãn theo mục 14; khi đó ghi rõ ở đây); bộ cài kèm `LICENSE`, giấy phép các thư viện bên thứ ba và chỉ dẫn lấy mã nguồn.
- [ ] Test soak 100 lượt truyền đạt.
- [ ] Tài liệu người dùng: cài đặt, ghép đôi, khắc phục sự cố (tường lửa, Wi-Fi chặn thiết bị).
- [ ] `SECURITY.md`, chính sách quyền riêng tư, `CHANGELOG.md` cho v1.0.0.
- [x] Đã chốt giấy phép phần mềm: GPL-3.0-or-later.
- [ ] Không còn lỗi nghiêm trọng đang mở.

---

## 13. Kịch bản demo (5 phút)

| Phút | Hành động | Điểm muốn chứng minh |
|---|---|---|
| 0:00 | Mở Teleport trên 2 laptop; máy kia tự hiện trên radar | Zero-Friction, không gõ IP |
| 0:30 | Ghép đôi bằng mã 6 số | Bảo mật dễ hiểu với người thường |
| 1:00 | Kéo file 10GB thả vào máy kia; mở Task Manager cạnh bên | Tốc độ LAN, RAM đứng yên |
| 2:00 | Rút dây/tắt Wi-Fi ở ~80%, đợi 10 giây, bật lại | Tự nối lại, chỉ gửi phần thiếu |
| 3:00 | Nhận xong, hiện “Đã kiểm tra toàn vẹn” | SHA-256 Merkle |
| 3:30 | Ctrl+C một đoạn văn + ảnh chụp màn hình → Ctrl+V trên máy kia | Clipboard đồng bộ |
| 4:00 | Tắt Internet của router, gửi tiếp vẫn chạy | Zero-Cloud thật sự |
| 4:30 | So sánh nhanh với Google Drive (số liệu benchmark) | Lợi thế thời gian |

---

## 14. Rủi ro sản phẩm

Rủi ro kỹ thuật và thực thi: [ke_hoach.md](ke_hoach.md) mục 8.

| Rủi ro | Ảnh hưởng | Hướng xử lý |
|---|---|---|
| Wi-Fi công cộng/văn phòng chặn thiết bị nói chuyện với nhau | Không dùng được ở quán cà phê, khách sạn | Phát hiện và báo rõ; gợi ý hotspot |
| SmartScreen / antivirus cảnh báo app chưa ký; macOS Gatekeeper chặn app chưa ký (macOS 15 phải mở Cài đặt hệ thống mới chạy được) | Người dùng sợ, không cài; khó đạt mục 9.1 (≥ 90% tự cài được) | Ký mã nếu có ngân sách (ke_hoach mục 9); hướng dẫn rõ từng bước |
| Cạnh tranh: LocalSend, KDE Connect, Nearby Share | Khó nổi bật | Tập trung vào nối lại theo khối, file cực lớn, clipboard |
| Trễ tiến độ (làm một mình) | v1.0 kéo dài | Hoãn sang sau v1.0 theo thứ tự: công cụ C++/Java → bộ cài macOS/Linux → clipboard ảnh. Không cắt nối lại/toàn vẹn (F6, F7) và an toàn khi nhận (F4). Hoãn mục nào thì sửa mục 4 và mục 12 tương ứng |

---

## 15. Lộ trình & việc cần chốt

- Lộ trình, các bản phát hành và **trạng thái hiện tại**: [ke_hoach.md](ke_hoach.md) mục 5.
- Các câu hỏi còn mở: [ke_hoach.md](ke_hoach.md) mục 9.
